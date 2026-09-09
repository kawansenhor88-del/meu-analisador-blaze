import unicodedata
import os
import json
import re
import traceback
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
import telebot
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request
from google import genai
from google.genai import types


# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
DATABASE_URL = os.environ.get("DATABASE_URL")
TIPMINER_TOKEN = os.environ.get("TIPMINER_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "10000"))

# Evita atualizar/regravar as 2.000 rodadas a cada mensagem do Telegram.
# A base continua sendo exclusivamente a janela de 2.000 do endpoint /history.
HISTORY_REFRESH_SECONDS = 30

TIPMINER_URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

ANALYSIS_ROUNDS = 2000
MAX_HISTORY = ANALYSIS_ROUNDS

TIPMINER_PARAMS = {
    "timezone": "America/Sao_Paulo",
    "subject": "filter",
    "limit": ANALYSIS_ROUNDS,
}

if not TELEGRAM_TOKEN:
    raise RuntimeError("ERRO: variável TELEGRAM_TOKEN não configurada.")

if not GEMINI_KEY:
    raise RuntimeError("ERRO: variável GEMINI_KEY não configurada.")

if not DATABASE_URL:
    raise RuntimeError("ERRO: variável DATABASE_URL não configurada.")

if not TIPMINER_TOKEN:
    raise RuntimeError("ERRO: variável TIPMINER_TOKEN não configurada.")


# ==============================================================================
# SERVIÇOS
# ==============================================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
surfe_mensagens_abertas = {}
surfe_cache = {}
client = genai.Client(api_key=GEMINI_KEY)
app = Flask(__name__)


# ==============================================================================
# HISTÓRICO EM MEMÓRIA
# ==============================================================================

historico_double = deque(maxlen=MAX_HISTORY)
historico_lock = threading.Lock()
ultima_rodada_id = None
historico_atualizacao_lock = threading.Lock()
ultima_atualizacao_historico = 0.0


# ==============================================================================
# HISTÓRICO ATUALIZADO DO TIPMINER
# ==============================================================================

def buscar_historico_tipminer():
    headers = {
        "accept": "*/*",
        "accept-language": "pt-BR",
        "content-type": "application/json",
        "authorization": f"Bearer {TIPMINER_TOKEN}",
        "origin": "https://www.tipminer.com",
        "referer": "https://www.tipminer.com/",
        "user-agent": "Mozilla/5.0",
    }

    resposta = requests.get(
        TIPMINER_URL,
        params=TIPMINER_PARAMS,
        headers=headers,
        timeout=30,
    )
    print("TIPMINER HISTORY HTTP:", resposta.status_code)
    resposta.raise_for_status()
    dados = resposta.json()

    if isinstance(dados, list):
        return dados
    if isinstance(dados, dict):
        for valor in dados.values():
            if isinstance(valor, list):
                return valor
    return None


def normalizar_rodada_historica(item):
    if not isinstance(item, dict):
        return None
    resultado = item.get("result")
    instant = item.get("instant") or item.get("created_at")
    color = item.get("color") or item.get("colour")
    # No histórico do Double, o número é a fonte principal da cor:
    # 0 = Branco, 1-7 = Vermelho, 8-14 = Preto.
    numero = resultado
    if numero is None:
        numero = item.get("roll")
    if numero is None:
        numero = item.get("number")
    tipo = str(item.get("type") or "DOUBLE").upper()
    cor = converter_cor(numero)
    if cor not in ("Vermelho", "Preto", "Branco"):
        cor = cor_por_tipo(tipo, resultado=resultado, color=color)
    if cor not in ("Vermelho", "Preto", "Branco"):
        return None
    rodada_id = item.get("id") or item.get("uuid") or instant
    if rodada_id is None:
        rodada_id = f"{instant}|{cor}|{numero}"
    return {
        "rodada_id": str(rodada_id),
        "tempo": converter_horario(instant) or str(item.get("tempo") or ""),
        "resultado": cor,
        "numero": numero,
        "instant": instant,
        "tipo": tipo,
    }


def atualizar_historico_tipminer(forcar=False):
    """
    Atualiza a janela fixa de 2.000 rodadas do endpoint /history.

    IMPORTANTE:
    - Não usa SSE.
    - Não adiciona rodadas ao banco por fora.
    - Não apaga uma base válida se a API falhar ou retornar menos de 2.000.
    - Consultas normais do Telegram reutilizam a última carga por até
      HISTORY_REFRESH_SECONDS segundos, evitando lentidão.
    """
    global ultima_atualizacao_historico

    agora = time.time()

    with historico_atualizacao_lock:
        if not forcar and (agora - ultima_atualizacao_historico) < HISTORY_REFRESH_SECONDS:
            total_atual = contar_rodadas_banco()
            if total_atual == ANALYSIS_ROUNDS:
                return total_atual

        print("========================================")
        print("ATUALIZANDO AS 2.000 RODADAS DO TIPMINER")
        print("SEM SSE — HISTORY COMO FONTE")
        print("========================================")

        dados = buscar_historico_tipminer()
    if not dados:
        raise RuntimeError("A API do TipMiner não retornou histórico.")

    rodadas = []
    vistos = set()
    for item in dados:
        rodada = normalizar_rodada_historica(item)
        if not rodada or rodada["rodada_id"] in vistos:
            continue
        vistos.add(rodada["rodada_id"])
        rodadas.append(rodada)

    if len(rodadas) < ANALYSIS_ROUNDS:
        raise RuntimeError(
            f"API retornou apenas {len(rodadas)} rodadas válidas; "
            f"esperado: {ANALYSIS_ROUNDS}."
        )

    # Ordena pela data/hora e mantém as 2.000 MAIS RECENTES.
    rodadas = sorted(rodadas, key=_ordem_temporal)[-ANALYSIS_ROUNDS:]

    conn = conectar_banco()
    try:
        cursor = conn.cursor()
        # Só limpamos depois de validar a nova carga. A transação garante que
        # um erro durante a inserção devolva o banco ao estado anterior.
        cursor.execute("DELETE FROM double_rounds")

        for rodada in rodadas:
            cursor.execute(
                """
                INSERT INTO double_rounds
                (rodada_id, tempo, resultado, numero, instant, tipo, criado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (rodada_id) DO UPDATE SET
                    tempo=EXCLUDED.tempo, resultado=EXCLUDED.resultado,
                    numero=EXCLUDED.numero, instant=EXCLUDED.instant,
                    tipo=EXCLUDED.tipo
                """,
                (
                    rodada["rodada_id"],
                    rodada["tempo"],
                    rodada["resultado"],
                    str(rodada["numero"]) if rodada["numero"] is not None else None,
                    str(rodada["instant"]) if rodada["instant"] is not None else None,
                    rodada["tipo"],
                    datetime.now(timezone.utc),
                ),
            )

        conn.commit()

        # Garantia absoluta: a tabela nunca fica com mais de 2.000 registros.
        cursor.execute(
            """
            DELETE FROM double_rounds
            WHERE id NOT IN (
                SELECT id
                FROM double_rounds
                ORDER BY id DESC
                LIMIT %s
            )
            """,
            (ANALYSIS_ROUNDS,),
        )
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM double_rounds")
        total_final = cursor.fetchone()[0]
        if total_final != ANALYSIS_ROUNDS:
            raise RuntimeError(
                f"Banco ficou com {total_final} rodadas; esperado: {ANALYSIS_ROUNDS}."
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    carregar_historico_banco()
    total = contar_rodadas_banco()

    print("RODADAS RECEBIDAS PELA API:", len(dados))
    print("RODADAS VÁLIDAS:", len(rodadas))
    print("TOTAL ATUAL NO POSTGRESQL:", total)

    if total != ANALYSIS_ROUNDS:
        raise RuntimeError(
            f"Banco ficou com {total} rodadas; esperado: {ANALYSIS_ROUNDS}."
        )

    ultima_atualizacao_historico = time.time()
    return total


def carregar_historico_fixo_tipminer():
    """Carga inicial obrigatória da janela fixa de 2.000 rodadas."""
    return atualizar_historico_tipminer(forcar=True)


# ==============================================================================
# BANCO POSTGRESQL / SUPABASE
# ==============================================================================

def conectar_banco():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=30,
    )


def inicializar_banco():
    conn = conectar_banco()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS double_rounds (
                id BIGSERIAL PRIMARY KEY,
                rodada_id TEXT UNIQUE,
                tempo TEXT,
                resultado TEXT,
                numero TEXT,
                instant TEXT,
                tipo TEXT NOT NULL DEFAULT 'DOUBLE',
                criado_em TIMESTAMPTZ NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_double_rounds_instant
            ON double_rounds(instant)
            """
        )
        conn.commit()
        print("========================================")
        print("BANCO POSTGRESQL / SUPABASE INICIALIZADO")
        print("LIMITE DE RODADAS:", MAX_HISTORY)
        print("========================================")
    except Exception:
        conn.rollback()
        print("ERRO AO INICIALIZAR POSTGRESQL:")
        traceback.print_exc()
        raise
    finally:
        conn.close()


def carregar_historico_banco():
    global ultima_rodada_id

    conn = conectar_banco()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT rodada_id, tempo, resultado, numero, instant, tipo
            FROM double_rounds
            ORDER BY id DESC
            LIMIT %s
            """
            , (MAX_HISTORY,)
        )
        linhas = cursor.fetchall()

        with historico_lock:
            historico_double.clear()
            for linha in reversed(linhas):
                historico_double.append(
                    {
                        "tempo": linha["tempo"],
                        "resultado": linha["resultado"],
                        "numero": linha["numero"],
                        "instant": linha["instant"],
                        "tipo": linha["tipo"],
                    }
                )

        if linhas:
            ultima_rodada_id = str(linhas[0]["rodada_id"])

        print("========================================")
        print("HISTÓRICO CARREGADO DO POSTGRESQL")
        print("RODADAS RECUPERADAS:", len(linhas))
        print("========================================")
        return len(linhas)
    finally:
        conn.close()


# A base é fixa: nenhuma rodada individual é salva. Somente atualizar_historico_tipminer() substitui a janela de 2.000.

def contar_rodadas_banco():
    conn = conectar_banco()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM double_rounds")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def obter_historico_banco(limite=None):
    conn=conectar_banco()
    try:
        cursor=conn.cursor(cursor_factory=RealDictCursor)
        if limite is None:
            cursor.execute("""SELECT rodada_id,tempo,resultado,numero,instant,tipo,criado_em
                              FROM double_rounds ORDER BY id DESC""")
        else:
            cursor.execute("""SELECT rodada_id,tempo,resultado,numero,instant,tipo,criado_em
                              FROM double_rounds ORDER BY id DESC LIMIT %s""",(int(limite),))
        linhas=cursor.fetchall()
        return [{"rodada_id":str(x["rodada_id"]) if x["rodada_id"] is not None else None,
                 "tempo":x["tempo"],"resultado":x["resultado"],"numero":x["numero"],
                 "instant":x["instant"],"tipo":x["tipo"],
                 "criado_em":x["criado_em"].isoformat() if x["criado_em"] else None}
                for x in linhas]
    finally:
        conn.close()

def obter_ultimo_por_cor(cor):
    conn=conectar_banco()
    try:
        cursor=conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""SELECT rodada_id,tempo,resultado,numero,instant,tipo
                          FROM double_rounds
                          WHERE LOWER(resultado)=LOWER(%s)
                          ORDER BY id DESC LIMIT 1""",(cor,))
        x=cursor.fetchone()
        if not x: return None
        return {"rodada_id":str(x["rodada_id"]) if x["rodada_id"] is not None else None,"tempo":x["tempo"],
                "resultado":x["resultado"],"numero":x["numero"],
                "instant":x["instant"],"tipo":x["tipo"]}
    finally:
        conn.close()


# ==============================================================================
# CONVERSORES
# ==============================================================================

def converter_horario(valor):
    if not valor:
        return None
    try:
        texto = str(valor)
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        dt = datetime.fromisoformat(texto)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone(timedelta(hours=-3)))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return str(valor)


def converter_cor(valor):
    if valor is None:
        return None
    try:
        numero = int(valor)
        if numero == 0:
            return "Branco"
        if 1 <= numero <= 7:
            return "Vermelho"
        if 8 <= numero <= 14:
            return "Preto"
    except Exception:
        pass

    texto = str(valor).strip().lower()
    if texto in ("white", "branco"):
        return "Branco"
    if texto in ("red", "vermelho"):
        return "Vermelho"
    if texto in ("black", "preto"):
        return "Preto"
    return str(valor)


def cor_por_tipo(tipo, resultado=None, color=None):
    t = str(tipo or "").upper()
    if t == "LUCKY":
        return "Branco"
    if t == "DOUBLE":
        return "Vermelho"
    if t == "DEFAULT":
        return "Preto"
    if color is not None:
        return converter_cor(color)
    return converter_cor(resultado)


# ==============================================================================
# ADICIONAR RODADA
# ==============================================================================

def adicionar_rodada(payload):
    # Base fixa de 2.000: eventos individuais nunca são gravados.
    print("ℹ️ RODADA INDIVIDUAL IGNORADA — base fixa de 2.000.")
    return False


# ==============================================================================
# HISTÓRICO PARA A IA
# ==============================================================================

def obter_historico(limite=None):
    dados=obter_historico_banco(limite=limite)
    if not dados: raise RuntimeError("O histórico fixo de 2.000 rodadas ainda não foi carregado.")
    return dados

def identificar_cor_perguntada(pergunta):
    texto=(pergunta or "").lower()
    for cor in ("branco","vermelho","preto"):
        if cor in texto: return cor.capitalize()
    return None

def montar_resposta_ultima_cor(rodada):
    partes=[f"🎯 Último {rodada.get('resultado','').lower()}:",
            f"🕐 {rodada.get('tempo') or 'horário indisponível'}"]
    if rodada.get("numero") is not None: partes.append(f"🔢 Número: {rodada['numero']}")
    return "\n".join(partes)


# ==============================================================================
# ANÁLISE DE SEQUÊNCIAS
# ==============================================================================

def emoji_cor(cor):
    return {"Vermelho": "🔴", "Preto": "⚫", "Branco": "⚪"}.get(cor, "❓")


def formatar_data_hora(instant, tempo=None):
    if instant:
        try:
            texto = str(instant)
            if texto.endswith("Z"):
                texto = texto[:-1] + "+00:00"
            dt = datetime.fromisoformat(texto)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone(timedelta(hours=-3)))
            return dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M:%S")
        except Exception:
            pass
    return "data indisponível", str(tempo or "horário indisponível")


def _ordem_temporal(d):
    valor = d.get("instant")
    if valor:
        try:
            texto = str(valor)
            if texto.endswith("Z"):
                texto = texto[:-1] + "+00:00"
            dt = datetime.fromisoformat(texto)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    return 0.0


def normalizar_cor_analise(rodada):
    """Retorna uma cor padronizada para uma rodada da análise."""
    if not isinstance(rodada, dict):
        return None

    resultado = rodada.get("resultado")
    if resultado in ("Vermelho", "Preto", "Branco"):
        return resultado

    # Se o resultado veio como número, convertemos diretamente.
    numero = rodada.get("numero")
    cor_numero = converter_cor(numero)
    if cor_numero in ("Vermelho", "Preto", "Branco"):
        return cor_numero

    # Último recurso: usa o tipo do evento.
    tipo = str(rodada.get("tipo") or "").upper()
    if tipo == "LUCKY":
        return "Branco"
    if tipo == "DOUBLE":
        return "Vermelho"
    if tipo == "DEFAULT":
        return "Preto"

    # Também aceita resultado/color em formatos textuais conhecidos.
    for valor in (rodada.get("color"), resultado):
        if isinstance(valor, str):
            texto = valor.strip().lower()
            if texto in ("red", "vermelho"):
                return "Vermelho"
            if texto in ("black", "preto"):
                return "Preto"
            if texto in ("white", "branco"):
                return "Branco"

    return None


def _encontrar_sequencias_de_10(dados, limite=50):
    """
    Reconhece blocos reais de cores consecutivas.

    Regra única da estratégia:
    - um bloco contínuo de Vermelho ou Preto com pelo menos 10 rodadas
      gera UMA ocorrência;
    - as 10 primeiras são o gatilho;
    - as posições 11ª a 15ª são as cinco rodadas imediatamente seguintes;
    - uma sequência longa (11, 15, 20...) continua sendo a mesma ocorrência;
    - uma nova ocorrência só pode começar em um novo bloco, depois que a
      cor mudar;
    - só entram ocorrências que tenham as 15 posições disponíveis.
    """
    if not dados:
        return []

    cores = [normalizar_cor_analise(d) for d in dados]
    ocorrencias = []
    i = 0

    while i < len(dados):
        cor = cores[i]

        # Branco ou registro sem cor: não inicia sequência.
        if cor not in ("Vermelho", "Preto"):
            i += 1
            continue

        # Descobre o tamanho do bloco contínuo começando em i.
        j = i + 1
        while j < len(dados) and cores[j] == cor:
            j += 1

        tamanho_bloco = j - i

        # O bloco precisa ter pelo menos 10 da mesma cor e mais 5 rodadas
        # depois do gatilho para que a ocorrência seja analisável.
        if tamanho_bloco >= 10 and i + 15 <= len(dados):
            seq_10 = dados[i:i + 10]
            seguintes_5 = dados[i + 10:i + 15]

            # As cinco posições precisam existir e ter cor reconhecida.
            if len(seguintes_5) == 5 and all(normalizar_cor_analise(r) is not None for r in seguintes_5):
                ocorrencias.append((i, cor, seq_10, seguintes_5))
                if len(ocorrencias) >= limite:
                    break

        # Pula o bloco inteiro. Assim, 15/20 vermelhos nunca viram
        # uma segunda sequência começando dentro do mesmo bloco.
        i = j

    return ocorrencias


def analisar_sequencias_de_10_completas():
    """Analisa TODAS as ocorrências encontradas nos 2.000 registros fixos."""
    dados = obter_historico_banco(limite=ANALYSIS_ROUNDS)
    if not dados:
        return "❌ Ainda não há rodadas suficientes no histórico fixo de 2.000."

    # O banco retorna mais recente -> mais antiga; a análise precisa ser cronológica.
    dados = list(reversed(dados))
    # Analisa todas as ocorrências completas dentro dos 2.000 registros.
    ocorrencias = _encontrar_sequencias_de_10(dados, limite=len(dados))
    ocorrencias = list(reversed(ocorrencias))

    if not ocorrencias:
        return "❌ Ainda não encontrei uma sequência completa de 10 vermelhos ou 10 pretos com as 5 rodadas seguintes disponíveis."

    stats = {p: {"hits": 0, "total": 0} for p in range(11, 16)}
    blocos = []
    bateu_total = 0
    nao_bateu_total = 0

    for _, cor, seq, seguintes in ocorrencias:
        oposta = "Preto" if cor == "Vermelho" else "Vermelho"
        data_inicio, hora_inicio = formatar_data_hora(seq[0].get("instant"), seq[0].get("tempo"))
        _, hora_10 = formatar_data_hora(seq[-1].get("instant"), seq[-1].get("tempo"))

        linhas = [
            f"🔥 SEQUÊNCIA DE 10 {cor.upper()} {emoji_cor(cor)}",
            "",
            f"📅 {data_inicio}",
            f"🕐 Início: {hora_inicio}",
            f"🕐 10ª rodada: {hora_10}",
            "",
            " ".join(emoji_cor(cor) for _ in range(10)),
            "",
            "➡️ APÓS A SEQUÊNCIA",
            "",
        ]

        # No resultado final, cada sequência conta UMA única vez:
        # bateu se a cor oposta apareceu em qualquer posição da 11ª à 15ª.
        bateu_ocorrencia = any(normalizar_cor_analise(r) == oposta for r in seguintes)
        if bateu_ocorrencia:
            bateu_total += 1
        else:
            nao_bateu_total += 1

        for offset_pos, rodada in enumerate(seguintes, start=11):
            c = normalizar_cor_analise(rodada)
            _, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
            numero = rodada.get("numero")

            if c == "Branco":
                marca = f"{emoji_cor(c)} BRANCO ❌"
            elif c == oposta:
                stats[offset_pos]["hits"] += 1
                marca = f"{emoji_cor(c)} {c.upper()} ✅"
            elif c in ("Vermelho", "Preto"):
                marca = f"{emoji_cor(c)} {c.upper()} ❌"
            else:
                marca = f"❓ {numero if numero is not None else '?'} ❌"

            stats[offset_pos]["total"] += 1
            linhas.append(f"{offset_pos}ª → {marca} — {hora}")

        blocos.append("\n".join(linhas))

    resumo = [f"📊 {len(ocorrencias)} SEQUÊNCIAS ENCONTRADAS NOS 2.000 REGISTROS", ""]
    for p in range(11, 16):
        total = stats[p]["total"]
        pct = (stats[p]["hits"] / total * 100) if total else 0.0
        resumo.append(f"{p}ª → {pct:.1f}% ({stats[p]['hits']}/{total})")

    disponiveis = [p for p in range(11, 16) if stats[p]["total"]]
    if disponiveis:
        melhor = max(disponiveis, key=lambda p: stats[p]["hits"] / stats[p]["total"])
        melhor_total = stats[melhor]["total"]
        melhor_pct = stats[melhor]["hits"] / melhor_total * 100
        resumo += ["", "🏆 MAIOR FREQUÊNCIA COR OPOSTA", f"➡️ {melhor}ª RODADA — {melhor_pct:.1f}%"]

    resumo += ["", f"📈 TOTAL ANALISADO: {len(ocorrencias)} sequências"]

    total_seq = len(ocorrencias)
    taxa_acerto = (bateu_total / total_seq * 100) if total_seq else 0.0
    taxa_nao_acerto = (nao_bateu_total / total_seq * 100) if total_seq else 0.0

    resultado_final = [
        "━━━━━━━━━━━━━━━━━━",
        "📊 RESULTADO FINAL",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"🔥 SEQUÊNCIAS ENCONTRADAS: {total_seq}",
        "",
        f"✅ BATEU A COR OPOSTA: {bateu_total}",
        f"❌ NÃO BATEU A COR OPOSTA: {nao_bateu_total}",
        "",
        f"📈 TAXA DE ACERTO: {taxa_acerto:.1f}%",
        f"📉 TAXA DE NÃO ACERTO: {taxa_nao_acerto:.1f}%",
    ]

    detalhes_finais = "\n\n".join(blocos) + "\n\n" + "\n".join(resultado_final)
    return ["\n".join(resumo), detalhes_finais]

def analisar_sequencias_de_cores_iguais():
    """
    Segunda estratégia: resumo das sequências de Vermelho/Preto iguais.

    Regras:
    - Uma sequência começa quando há 2 ou mais Vermelhos ou Pretos consecutivos.
    - Uma sequência longa conta como uma única sequência pelo seu tamanho real.
      Ex.: 10 vermelhos = uma sequência de 10, não várias de 2, 3, 4...
    - Branco ou uma cor diferente encerra a sequência.
    - O resultado mostra a quantidade por tamanho/cor e a data/hora da ocorrência
      mais recente daquele tamanho.
    """
    dados = obter_historico_banco(limite=ANALYSIS_ROUNDS)
    if not dados:
        return "❌ Ainda não há rodadas suficientes no histórico."

    # O banco retorna mais recente -> mais antiga. A análise de sequência precisa
    # ser feita da mais antiga -> mais recente.
    dados = list(reversed(dados))

    contagens = {}
    ultima_ocorrencia = {}

    i = 0
    while i < len(dados):
        cor = normalizar_cor_analise(dados[i])

        if cor not in ("Vermelho", "Preto"):
            i += 1
            continue

        inicio = i
        j = i + 1
        while j < len(dados) and normalizar_cor_analise(dados[j]) == cor:
            j += 1

        tamanho = j - inicio

        if tamanho >= 2:
            chave = (cor, tamanho)
            contagens[chave] = contagens.get(chave, 0) + 1

            # Guarda a ocorrência mais recente daquele tamanho.
            rodada_final = dados[j - 1]
            ultima_ocorrencia[chave] = rodada_final

        i = j

    if not contagens:
        return "❌ Nenhuma sequência de 2 ou mais cores iguais foi encontrada."

    # Ordena por tamanho da sequência e, dentro do mesmo tamanho, Vermelho antes Preto.
    itens = sorted(
        contagens.items(),
        key=lambda item: (item[0][1], 0 if item[0][0] == "Vermelho" else 1)
    )

    linhas = ["📊 SEQUÊNCIAS DE CORES IGUAIS — 2.000 RODADAS", ""]

    for (cor, tamanho), quantidade in itens:
        rodada = ultima_ocorrencia[(cor, tamanho)]
        data, hora = formatar_data_hora(
            rodada.get("instant"), rodada.get("tempo")
        )
        palavra = "ocorrência" if quantidade == 1 else "ocorrências"
        linhas.append(
            f"{emoji_cor(cor)} {tamanho} iguais — {quantidade} {palavra}"
        )
        linhas.append(f"📅 {data}")
        linhas.append(f"🕐 {hora}")
        linhas.append("")

    # Maior sequência real encontrada.
    maior_tamanho = max(tamanho for (_, tamanho) in contagens)
    maiores = [
        (cor, tamanho)
        for (cor, tamanho) in contagens
        if tamanho == maior_tamanho
    ]

    # Se houver empate, mostra todas as cores da maior sequência.
    linhas.append("🏆 MAIOR SEQUÊNCIA")
    for cor, tamanho in maiores:
        rodada = ultima_ocorrencia[(cor, tamanho)]
        data, hora = formatar_data_hora(
            rodada.get("instant"), rodada.get("tempo")
        )
        linhas.append(f"➡️ {tamanho} {emoji_cor(cor)}")
        linhas.append(f"📅 {data}")
        linhas.append(f"🕐 {hora}")

    total_sequencias = sum(contagens.values())
    linhas += [
        "",
        f"📚 Rodadas analisadas: {len(dados):,}",
        f"🔢 Sequências encontradas: {total_sequencias}",
    ]

    return "\n".join(linhas)


def analisar_atraso_do_branco():
    """
    Estratégia do Branco:
    - Usa todos os 2.000 registros, em ordem cronológica.
    - Cada Branco inicia um intervalo.
    - O próximo Branco encerra o intervalo.
    - Conta somente as rodadas Vermelho/Preto entre os dois Brancos,
      sem contar o Branco inicial nem o Branco final.
    - Calcula o horário de início, horário de término e duração real.
    """
    dados = obter_historico_banco(limite=ANALYSIS_ROUNDS)
    if not dados:
        return "❌ Ainda não há rodadas suficientes no histórico fixo de 2.000."

    dados = list(reversed(dados))
    brancos = [i for i, rodada in enumerate(dados)
               if normalizar_cor_analise(rodada) == "Branco"]

    if len(brancos) < 2:
        return "❌ É necessário encontrar pelo menos 2 brancos nos 2.000 registros para calcular o intervalo."

    intervalos = []
    for pos in range(len(brancos) - 1):
        inicio_idx = brancos[pos]
        fim_idx = brancos[pos + 1]
        inicio = dados[inicio_idx]
        fim = dados[fim_idx]

        # Quantidade de rodadas entre os dois brancos.
        rodadas_sem_branco = max(0, fim_idx - inicio_idx - 1)

        data_inicio, hora_inicio = formatar_data_hora(
            inicio.get("instant"), inicio.get("tempo")
        )
        data_fim, hora_fim = formatar_data_hora(
            fim.get("instant"), fim.get("tempo")
        )

        duracao_segundos = None
        try:
            a = str(inicio.get("instant") or "")
            b = str(fim.get("instant") or "")
            if a.endswith("Z"):
                a = a[:-1] + "+00:00"
            if b.endswith("Z"):
                b = b[:-1] + "+00:00"
            dt_a = datetime.fromisoformat(a)
            dt_b = datetime.fromisoformat(b)
            if dt_a.tzinfo is None:
                dt_a = dt_a.replace(tzinfo=timezone.utc)
            if dt_b.tzinfo is None:
                dt_b = dt_b.replace(tzinfo=timezone.utc)
            duracao_segundos = max(0, int((dt_b - dt_a).total_seconds()))
        except Exception:
            duracao_segundos = None

        if duracao_segundos is not None:
            horas, resto = divmod(duracao_segundos, 3600)
            minutos, segundos = divmod(resto, 60)
            if horas:
                duracao = f"{horas}h {minutos}m {segundos}s"
            elif minutos:
                duracao = f"{minutos}m {segundos}s"
            else:
                duracao = f"{segundos}s"
        else:
            duracao = "indisponível"

        intervalos.append({
            "data_inicio": data_inicio,
            "hora_inicio": hora_inicio,
            "data_fim": data_fim,
            "hora_fim": hora_fim,
            "rodadas": rodadas_sem_branco,
            "duracao": duracao,
            "duracao_segundos": duracao_segundos if duracao_segundos is not None else -1,
        })

    # Mais recentes primeiro, para facilitar a conferência no Telegram.
    intervalos.reverse()

    maior = max(intervalos, key=lambda x: x["rodadas"])
    menor = min(intervalos, key=lambda x: x["rodadas"])
    media = sum(x["rodadas"] for x in intervalos) / len(intervalos)

    texto = [
        "⚪ ATRASO DO BRANCO",
        "",
        "📚 Análise completa dos 2.000 registros",
        "",
        "📖 COMO FUNCIONA A ESTRATÉGIA",
        "",
        "Esta estratégia procura todos os intervalos entre um Branco e o próximo Branco dentro dos 2.000 registros.",
        "",
        "⚪ Quando sai um Branco, começa a contagem.",
        "🔴⚫ Cada rodada Vermelho ou Preto sem Branco aumenta o atraso em +1.",
        "⚪ Quando sai o próximo Branco, a contagem termina.",
        "",
        "O bot informa automaticamente quantas rodadas ficaram sem pagar Branco, o horário em que o intervalo começou, o horário em que terminou e o tempo real que durou.",
        "",
        "⚠️ A análise mostra o comportamento histórico dos 2.000 registros e não garante quando o próximo Branco irá acontecer.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📊 RESUMO GERAL",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"⚪ Intervalos entre brancos: {len(intervalos)}",
        f"📊 Média sem Branco: {media:.1f} rodadas",
        f"📉 Menor atraso: {menor['rodadas']} rodada(s)",
        f"🚨 Maior atraso: {maior['rodadas']} rodadas",
        f"📅 Maior atraso: {maior['data_inicio']}",
        f"🕐 Início: {maior['hora_inicio']}",
        f"🕐 Fim: {maior['hora_fim']}",
        f"⏱️ Duração: {maior['duracao']}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📋 INTERVALOS ENCONTRADOS",
        "━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for n, item in enumerate(intervalos, 1):
        texto.extend([
            f"⚪ Intervalo {n}",
            f"📅 {item['data_inicio']} → {item['data_fim']}",
            f"🕐 Início: {item['hora_inicio']}",
            f"🕐 Fim: {item['hora_fim']}",
            f"🔢 SEM PAGAR BRANCO: {item['rodadas']} rodadas",
            f"⏱️ Duração: {item['duracao']}",
            "",
        ])

    return "\n".join(texto)


def _estatisticas_surfe(caminho):
    """Calcula os dois caminhos do SURFE em ordem cronológica."""
    stats = {
        "Preto": {"acertos": 0, "erros": 0, "maior_gale": 0, "gale_counts": {}},
        "Vermelho": {"acertos": 0, "erros": 0, "maior_gale": 0, "gale_counts": {}},
    }
    gale = {"Preto": 0, "Vermelho": 0}
    registros = []

    for rodada in caminho:
        saiu = normalizar_cor_analise(rodada)
        if saiu not in ("Preto", "Vermelho", "Branco"):
            continue

        numero = len(registros) + 1
        bloco = ((numero - 1) // 2) % 2
        jogaria_preto = "Preto" if bloco == 0 else "Vermelho"
        jogaria_vermelho = "Vermelho" if bloco == 0 else "Preto"
        resultados = {}

        for nome, jogaria in (("Preto", jogaria_preto), ("Vermelho", jogaria_vermelho)):
            # Branco conta como Gale, sem interromper nem reiniciar o caminho.
            if saiu == "Branco":
                stats[nome]["erros"] += 1
                gale[nome] += 1
                stats[nome]["maior_gale"] = max(
                    stats[nome]["maior_gale"], gale[nome]
                )
                stats[nome]["gale_counts"][gale[nome]] = (
                    stats[nome]["gale_counts"].get(gale[nome], 0) + 1
                )
                resultados[nome] = f"❌ GALE {gale[nome]}"
                continue

            if saiu == jogaria:
                stats[nome]["acertos"] += 1
                gale[nome] = 0
                resultados[nome] = "✅ ACERTO"
            else:
                stats[nome]["erros"] += 1
                gale[nome] += 1
                stats[nome]["maior_gale"] = max(
                    stats[nome]["maior_gale"], gale[nome]
                )
                stats[nome]["gale_counts"][gale[nome]] = (
                    stats[nome]["gale_counts"].get(gale[nome], 0) + 1
                )
                resultados[nome] = f"❌ GALE {gale[nome]}"

        data, hora = formatar_data_hora(
            rodada.get("instant"), rodada.get("tempo")
        )
        registros.append({
            "numero": numero,
            "numero_real": rodada.get("numero", "?"),
            "data": data,
            "hora": hora,
            "saiu": saiu,
            "jogaria_preto": jogaria_preto,
            "jogaria_vermelho": jogaria_vermelho,
            "resultado_preto": resultados["Preto"],
            "resultado_vermelho": resultados["Vermelho"],
        })

    return registros, stats


def _resumo_surfe_estrategia(stats, nome, titulo):
    """Resumo principal do SURF, sem exibir os Gales."""
    st = stats[nome]
    total = st["acertos"] + st["erros"]
    pct = (st["acertos"] / total * 100) if total else 0.0

    return "\n".join([
        titulo,
        f"✅ ACERTOS: {st['acertos']}",
        f"❌ ERROS: {st['erros']}",
        f"📈 APROVEITAMENTO: {pct:.1f}%",
    ])


def _emoji_numero_gale(numero):
    mapa = {
        "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
        "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣",
    }
    return "".join(mapa.get(c, c) for c in str(numero))


def _resumo_gales_surfe(stats, nome, titulo):
    st = stats[nome]
    maior = _emoji_numero_gale(st["maior_gale"])
    partes = [titulo, f"🔥 MAIOR GALE: GALE {maior}"]
    for n in sorted(st["gale_counts"]):
        partes.append(f"📊 GALE {_emoji_numero_gale(n)}: {st['gale_counts'][n]}")
    return "\n".join(partes)


def obter_brancos_surfe():
    """Retorna todos os Brancos dos 2.000 registros em ordem antiga -> recente."""
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    return [
        (i, rodada)
        for i, rodada in enumerate(dados)
        if normalizar_cor_analise(rodada) == "Branco"
    ]


def montar_botoes_brancos_surfe(brancos, inicio=0, fim=None):
    """Monta os Brancos em duas colunas, mantendo a ordem cronológica."""
    fim = len(brancos) if fim is None else min(fim, len(brancos))
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    itens = brancos[inicio:fim]

    for pos in range(0, len(itens), 2):
        botoes = []
        for offset in (0, 1):
            if pos + offset >= len(itens):
                break
            indice, rodada = itens[pos + offset]
            _, hora = formatar_data_hora(
                rodada.get("instant"), rodada.get("tempo")
            )
            # O índice é o índice cronológico dentro dos 2.000 registros.
            botoes.append(
                telebot.types.InlineKeyboardButton(
                    f"⚪ {hora}",
                    callback_data=f"surfe_branco:{indice}",
                )
            )
        markup.row(*botoes)

    return markup


def _montar_linhas_estrategia_surfe(registros, estrategia, numero_final_analise=None):
    """Monta as linhas de uma estratégia com espaçamento de controle."""
    linhas = []

    for item in registros:
        jogaria = (
            item["jogaria_preto"]
            if estrategia == "Preto"
            else item["jogaria_vermelho"]
        )
        resultado = (
            item["resultado_preto"]
            if estrategia == "Preto"
            else item["resultado_vermelho"]
        )

        numero = int(item["numero"])
        numero_real = str(item.get("numero_real", "?"))
        cor_real = emoji_cor(item["saiu"])
        if cor_real in ("🔴", "⚫"):
            cor_real += "\uFE0F"

        cor_jogada = emoji_cor(jogaria)
        if cor_jogada in ("🔴", "⚫"):
            cor_jogada += "\uFE0F"

        if resultado.startswith("❌ GALE"):
            gale = int(resultado.split()[-1])
            # Mantém G1 a G9. A partir do G10 usa uma única letra:
            # G10=GA, G11=GB, G12=GC ... G35=GZ.
            # Isso evita aumentar a largura da linha quando o Gale passa de 9.
            if 10 <= gale <= 35:
                identificador_gale = chr(ord("A") + (gale - 10))
            else:
                identificador_gale = str(gale)
            marcador = f"❌G{identificador_gale}"
        else:
            marcador = "✅"

        # Espaço padronizado entre o número da rodada e a primeira bolinha.
        # É IGUAL em todas as rodadas (01 a 50).
        espaco_rodada = "\u2007"

        # SOMENTE 01 a 08 recebem o ajuste fino ANTES do número da rodada.
        # Assim a linha inteira desloca levemente para a direita, sem aumentar
        # o espaço entre "01/02/..." e a primeira bolinha.
        ajuste_01_08 = ""
        if 1 <= numero <= 8:
            valor_config = (
                AJUSTE_01_08_ANTES_SETA_ESQUERDA
                if estrategia == "Vermelho"
                else AJUSTE_01_08_ANTES_SETA_DIREITA
            )
        elif 100 <= numero <= 999 and (numero % 100) <= 7:
            # Mesmo ajuste fino nas 8 primeiras rodadas de cada centena.
            valor_config = (
                AJUSTE_CENTENA_00_07_ANTES_SETA_ESQUERDA
                if estrategia == "Vermelho"
                else AJUSTE_CENTENA_00_07_ANTES_SETA_DIREITA
            )

        else:
            valor_config = 0.0

        # Calibração EXCLUSIVA da última rodada da quantidade escolhida.
        # Valor positivo = seta vai para a direita.
        # Valor negativo = seta vai para a esquerda.
        if numero == numero_final_analise and numero in AJUSTE_FINAL_SURF:
            chave = "esquerda" if estrategia == "Vermelho" else "direita"
            valor_config += AJUSTE_FINAL_SURF[numero][chave]

        valor_ajuste = max(0.0, float(valor_config))
        parte_inteira = int(valor_ajuste)
        decimos = int(round((valor_ajuste - parte_inteira) * 10))
        ajuste_01_08 = ("\u3164" * parte_inteira) + ("\u200A" * decimos)

        espaco_cor = "\u2007" if len(numero_real) == 1 else ""

        numero_formatado = f"{numero:02d}"
        linha = (
            f"{numero_formatado}{espaco_rodada}{cor_real}{numero_real}{espaco_cor}"
            f"{ajuste_01_08}-{cor_jogada}{marcador}"
        )
        linhas.append(linha)

    return linhas


def _largura_visual_surfe(texto):
    """Calcula uma largura aproximada de célula para alinhamento monoespaçado."""
    largura = 0
    for caractere in texto:
        if unicodedata.combining(caractere):
            continue
        if unicodedata.east_asian_width(caractere) in ("W", "F"):
            largura += 2
        else:
            largura += 1
    return largura


def _preencher_visual_surfe(texto, largura_alvo):
    """Completa uma linha até a largura visual alvo sem alterar seu conteúdo."""
    faltam = max(0, largura_alvo - _largura_visual_surfe(texto))
    return texto + (" " * faltam)


# =========================================================
# AJUSTE MANUAL DO ALINHAMENTO ENTRE AS COLUNAS DO SURF
# ALTERE SOMENTE ESTES DOIS NÚMEROS PARA TESTAR:
# =========================================================
ESPACO_APOS_G = 2.0
ESPACO_APOS_CHECK = 3.4

# Ajuste fino SOMENTE das rodadas 01 a 08.
# 0.1 = um ajuste mínimo para a direita.
# Você pode testar 0.2, 0.3, 0.4... sem mexer nas rodadas 09 a 50.
# Ajustes independentes SOMENTE para as rodadas 01 a 08.
# Quanto maior, mais a respectiva coluna vai para a direita.
AJUSTE_01_08_ANTES_SETA_ESQUERDA = 0.2
AJUSTE_01_08_ANTES_SETA_DIREITA = 0.2

# Ajuste fino das 8 primeiras rodadas de cada centena:
# 100–107, 200–207, 300–307 ... 900–907.
AJUSTE_CENTENA_00_07_ANTES_SETA_ESQUERDA = 0.2
AJUSTE_CENTENA_00_07_ANTES_SETA_DIREITA = 0.2

# =========================================================
# CALIBRAÇÃO SOMENTE DA ÚLTIMA RODADA DE CADA BOTÃO DO SURF
# =========================================================
# esquerda/direita: mexem SOMENTE antes da seta (-) da respectiva camada.
#   +0.1 = um pouco para a direita | -0.1 = um pouco para a esquerda
# separador: mexe SOMENTE no espaço entre as duas colunas.
#   +0.1 = afasta as colunas | -0.1 = aproxima as colunas
#
# Estes valores NÃO alteram 100/200/300... quando aparecem no meio da análise.
# Só alteram o número que for exatamente a ÚLTIMA rodada selecionada.
AJUSTE_FINAL_SURF = {
    100:  {"esquerda": 0.0, "direita": 0.0, "separador": 0.0},
    200:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    300:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    400:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    500:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    600:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    700:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    800:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    900:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    1000: {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
}

def _montar_surfe_duas_colunas(registros, numero_final_analise=None):
    """Monta as duas colunas do SURF com espaçamento padronizado."""
    vermelho = _montar_linhas_estrategia_surfe(registros, "Vermelho", numero_final_analise)
    preto = _montar_linhas_estrategia_surfe(registros, "Preto", numero_final_analise)

    linhas = [
        "SURF🔴" + ("\u2007" * 5) + "SURF⚫",
        "",
    ]

    for esquerda, direita in zip(vermelho, preto):
        # Compensação manual com ajuste decimal.
        # Parte inteira -> ㅤ (U+3164)
        # Cada 0.1      -> Hair Space (U+200A)
        def criar_espaco(valor):
            valor = max(0.0, float(valor))
            parte_inteira = int(valor)
            decimos = int(round((valor - parte_inteira) * 10))

            return ("\u3164" * parte_inteira) + ("\u200A" * decimos)

        # Como ❌G ocupa mais largura que ✅, cada final tem seu próprio ajuste.
        if esquerda.endswith("✅"):
            valor_separador = ESPACO_APOS_CHECK
        elif "❌G" in esquerda:
            valor_separador = ESPACO_APOS_G
        else:
            valor_separador = ESPACO_APOS_G

        # GA–GZ na coluna esquerda: a letra fica visualmente um pouco mais larga
        # no Telegram. Reduz 0.1 SOMENTE do espaço depois do Gale para manter
        # a coluna direita alinhada. G1–G9 permanecem exatamente como estão.
        if re.search(r"❌G[A-Z]$", esquerda):
            valor_separador -= 0.1

        # Ajuste independente do espaço entre as colunas SOMENTE na última rodada.
        # Valor negativo aproxima a coluna direita; positivo afasta.
        numero_linha = int(esquerda.split()[0])
        if numero_linha == numero_final_analise and numero_linha in AJUSTE_FINAL_SURF:
            valor_separador += AJUSTE_FINAL_SURF[numero_linha]["separador"]

        separador = criar_espaco(valor_separador)
        linhas.append(esquerda + separador + direita)

    return "\n".join(linhas)



def _montar_blocos_surfe(registros):
    """Divide a exibição do SURF sem cortar uma rodada no meio."""
    if not registros:
        return []

    blocos_registros = []
    bloco_atual = []

    for item in registros:
        numero = int(item["numero"])

        # Mantém os cortes já aprovados:
        # 01–99, 100–199, 200–299, 300–399...
        if bloco_atual and numero >= 100 and numero % 100 == 0:
            blocos_registros.append(bloco_atual)
            bloco_atual = []

        bloco_atual.append(item)

    if bloco_atual:
        blocos_registros.append(bloco_atual)

    # Exceção SOMENTE para o final da análise:
    # se o último bloco tiver apenas 1 rodada (ex.: 400 sozinho),
    # junta essa última rodada ao bloco anterior.
    if len(blocos_registros) >= 2 and len(blocos_registros[-1]) == 1:
        blocos_registros[-2].extend(blocos_registros[-1])
        blocos_registros.pop()

    numero_final_analise = int(registros[-1]["numero"])

    return [
        _montar_surfe_duas_colunas(bloco, numero_final_analise)
        for bloco in blocos_registros
    ]

def analisar_surfe_inicial():
    """Prepara o painel do SURF para escolha do Branco inicial."""
    brancos = obter_brancos_surfe()
    if not brancos:
        return None

    introducao = "\n".join([
        "⚪ SURF — ESCOLHA O BRANCO",
        "",
        "👇 Escolha abaixo o Branco onde você quer iniciar o Surf.",
        "",
        "📊 Ao clicar em um Branco, o bot vai analisar todas as rodadas",
        "a partir dele até o resultado mais recente, mostrando como o Surf",
        "teria se comportado começando exatamente naquele ponto.",
        "",
        "🕐 Os Brancos estão organizados do mais antigo para o mais recente,",
        "para que a análise respeite a ordem real das rodadas.",
        "",
        "💡 Você pode escolher qualquer Branco para testar diferentes pontos de entrada.",
        "",
        "⚪ Selecione um Branco abaixo:",
    ])
    return {"intro": introducao, "brancos": brancos}

def analisar_surfe_a_partir_do_branco(indice_branco, limite=None):
    """Analisa o SURF a partir do Branco, seguindo as rodadas posteriores até as mais recentes."""
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    if indice_branco < 0 or indice_branco >= len(dados):
        return None

    if normalizar_cor_analise(dados[indice_branco]) != "Branco":
        return None

    branco = dados[indice_branco]
    data_branco, hora_branco = formatar_data_hora(
        branco.get("instant"), branco.get("tempo")
    )

    # O Branco escolhido é o gatilho. O SURF começa pela rodada imediatamente
    # posterior a ele e segue cronologicamente até as rodadas mais recentes.
    caminho = dados[indice_branco + 1:]
    if limite is not None:
        caminho = caminho[:limite]

    registros, stats = _estatisticas_surfe(caminho)

    return {
        "branco": branco,
        "data_branco": data_branco,
        "hora_branco": hora_branco,
        "registros": registros,
        "stats": stats,
    }


def montar_resultado_surfe(analise):
    """Monta o cabeçalho, as rodadas escolhidas e o resumo do SURF."""
    registros = analise["registros"]
    cabecalho = "\n".join([
        f"🏄 SURF-{len(registros)} RODADAS",
        "",
        f"⚪ Branco inicial: {analise['data_branco']} às {analise['hora_branco']}",
        f"📚 Analisadas: {len(registros)}",
    ])

    rodadas = _montar_surfe_duas_colunas(registros)

    estatistica = "\n".join([
        "📊 RESULTADO — APÓS O BRANCO",
        f"⚪ {analise['data_branco']} às {analise['hora_branco']}",
        f"📚 Das {len(registros)} rodadas após o Branco",
        "",
        _resumo_surfe_estrategia(analise["stats"], "Preto", "⚫ SURFE — 2 PRETOS"),
        "",
        _resumo_surfe_estrategia(analise["stats"], "Vermelho", "🔴 SURFE — 2 VERMELHOS"),
    ])

    return cabecalho + "\n\n§§§SURF_RODADAS§§§\n\n" + rodadas + "\n\n§§§SURF_ESTATISTICA§§§\n\n" + estatistica


def montar_controle_geral_surfe(analise):
    """Resumo geral desde o Branco escolhido até a rodada mais recente."""
    stats = analise["stats"]
    total = len(analise["registros"])

    return "\n".join([
        "📊 RESULTADO GERAL — DO INÍCIO DO BRANCO",
        "",
        "📖 COMO ENTENDER O RESULTADO",
        "",
        "Esta análise mostra como os dois SURF teriam se comportado",
        "a partir do Branco escolhido, até o resultado mais recente.",
        "",
        "⚫ 2 PRETOS → 2 Pretos, depois 2 Vermelhos, repetindo.",
        "🔴 2 VERMELHOS → 2 Vermelhos, depois 2 Pretos, repetindo.",
        "",
        "✅ Acerto = a cor que saiu foi a indicada pelo SURF.",
        "❌ Erro = a cor foi diferente e o Gale aumentou.",
        "📈 Aproveitamento = porcentagem de acertos.",
        "🔥 Maior Gale = maior sequência de Gales registrada.",
        "📊 Gale 1, 2, 3... = quantidade de vezes que cada Gale ocorreu.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"⚪ Início: {analise['data_branco']} às {analise['hora_branco']}",
        f"📚 Total de rodadas analisadas: {total}",
        "",
        _resumo_surfe_estrategia(stats, "Preto", "⚫ SURFE — 2 PRETOS"),
        "",
        _resumo_surfe_estrategia(stats, "Vermelho", "🔴 SURFE — 2 VERMELHOS"),
        "",
        "⚠️ Estatística histórica. Não garante o resultado da próxima rodada.",
    ])



def painel_markup():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🔥 SEQUÊNCIA CORES IGUAIS 10X — COMPLETA", callback_data="seq10")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📊 SEQUÊNCIA DE CORES IGUAIS", callback_data="seqcores")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("⚪ ATRASO DO BRANCO", callback_data="branco_atraso")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("⚪ SURF", callback_data="surfe")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📊 Últimas 50", callback_data="ult50"),
        telebot.types.InlineKeyboardButton("📚 Total", callback_data="total"),
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🕐 Última rodada", callback_data="ultima")
    )
    return markup

# ==============================================================================
# TELEGRAM
# ==============================================================================

@bot.message_handler(commands=["start"])
def iniciar(message):
    print("COMANDO /START RECEBIDO")
    # IMPORTANTE: /start não consulta PostgreSQL/Supabase nem a API.
    # Isso evita que uma conexão lenta com o banco atrase a entrega do painel.
    bot.reply_to(
        message,
        "🤖 Bot online!\n\n"
        "📊 Painel de controle pronto.\n"
        f"💾 Base de análise: {ANALYSIS_ROUNDS:,} rodadas\n\n"
        "Escolha uma análise no painel ou envie uma pergunta.",
        reply_markup=painel_markup()
    )


@bot.message_handler(commands=["atualizar"])
def atualizar_manual(message):
    try:
        total = atualizar_historico_tipminer(forcar=True)
        bot.reply_to(
            message,
            f"✅ Histórico atualizado com sucesso.\n\n"
            f"📚 Base fixa: {total:,} rodadas."
        )
    except Exception as erro:
        bot.reply_to(
            message,
            f"❌ Falha ao atualizar o histórico.\n"
            f"Erro: {type(erro).__name__}: {str(erro)[:250]}"
        )


@bot.message_handler(commands=["painel"])
def abrir_painel(message):
    try:
        # O painel também usa o banco local para abrir imediatamente.
        total = contar_rodadas_banco()

        bot.reply_to(
            message,
            f"🎯 PAINEL DE ESTRATÉGIAS\n\n"
            f"🔥 SEQUÊNCIA CORES IGUAIS 10X\n"
            f"📊 SEQUÊNCIA DE CORES IGUAIS\n"
            f"📚 Rodadas na base fixa: {total}\n"
            f"💾 Base fixa de análise: {ANALYSIS_ROUNDS:,} rodadas\n\n"
            "Clique na estratégia para gerar o resultado:",
            reply_markup=painel_markup()
        )
    except Exception as erro:
        bot.reply_to(message, f"❌ Não consegui abrir o painel: {type(erro).__name__}")


@bot.callback_query_handler(func=lambda call: call.data in ("surfe_ocultar",))
def surfe_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        ids = surfe_mensagens_abertas.pop(chat_id, [])
        surfe_cache.pop(chat_id, None)
        for message_id in ids:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
    except Exception as erro:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_branco:"))
def surfe_branco_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id

        indice = int(call.data.split(":", 1)[1])

        # Guarda somente o Branco escolhido. A análise das 50 rodadas
        # acontece somente quando o usuário clicar em VER SURFE.
        dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
        if indice < 0 or indice >= len(dados) or normalizar_cor_analise(dados[indice]) != "Branco":
            bot.send_message(chat_id, "❌ Não foi possível localizar o Branco escolhido no histórico.")
            return

        surfe_cache[chat_id] = {"branco_index": indice}

        _, hora_branco = formatar_data_hora(
            dados[indice].get("instant"), dados[indice].get("tempo")
        )

        explicacao = "\n".join([
            "🏄 SURFE — ANÁLISE ESTATÍSTICA",
            "",
            "⚪ BRANCO SELECIONADO",
            f"🕐 {hora_branco}",
            "",
            "📊 ESCOLHA AS RODADAS",
            "",
            "Selecione quantas rodadas após esse Branco",
            "você deseja analisar no SURF.",
            "",
            "🔴 SURF 2 VERMELHOS",
            "⚫ SURF 2 PRETOS",
            "",
            "📚 Você pode analisar de 50 até 1.000 rodadas.",
            "",
            "👇 Escolha uma quantidade:",
        ])

        markup = telebot.types.InlineKeyboardMarkup(row_width=3)
        quantidades = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)
        botoes = [
            telebot.types.InlineKeyboardButton(
                str(qtd), callback_data=f"surfe_qtd:{qtd}"
            )
            for qtd in quantidades
        ]
        for pos in range(0, len(botoes), 3):
            markup.row(*botoes[pos:pos + 3])
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🔽 OCULTAR SURF", callback_data="surfe_ocultar"
            )
        )
        m = bot.send_message(chat_id, explicacao, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro no SURF: {type(erro).__name__}: {str(erro)[:250]}"
            )
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_qtd:"))
def surfe_quantidade_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        if estado.get("branco_index") is None:
            bot.send_message(chat_id, "❌ Escolha primeiro um ⚪ Branco para iniciar o SURF.")
            return

        quantidade = int(call.data.split(":", 1)[1])
        if quantidade not in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000):
            return
        estado["quantidade"] = quantidade
        surfe_cache[chat_id] = estado

        # Antes de mostrar a explicação do SURF, confirma se a quantidade
        # escolhida realmente existe após o Branco selecionado.
        analise = analisar_surfe_a_partir_do_branco(estado["branco_index"], limite=quantidade)
        if not analise:
            bot.send_message(chat_id, "❌ Não foi possível recuperar o Branco inicial.")
            return

        if len(analise["registros"]) < quantidade:
            disponiveis = len(analise["registros"])
            quantidade_texto = f"{quantidade:,}".replace(",", ".")
            disponiveis_texto = f"{disponiveis:,}".replace(",", ".")

            dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
            _, hora_branco = formatar_data_hora(
                dados[estado["branco_index"]].get("instant"),
                dados[estado["branco_index"]].get("tempo")
            )

            mensagem = "\n".join([
                "❌ QUANTIDADE INDISPONÍVEL",
                "",
                f"⚪ Após o Branco selecionado existem apenas {disponiveis_texto} rodadas disponíveis.",
                "",
                f"📊 Você solicitou {quantidade_texto} rodadas, mas ainda não existem {quantidade_texto} rodadas após esse Branco.",
                "",
                "🏄 SOBRE A ANÁLISE SURF",
                "",
                "Após o Branco selecionado, serão analisados dois caminhos simultaneamente:",
                "",
                "⚫ SURFE 2 PRETOS:",
                "⚫⚫ → 🔴🔴 → ⚫⚫ → 🔴🔴...",
                "",
                "🔴 SURFE 2 VERMELHOS:",
                "🔴🔴 → ⚫⚫ → 🔴🔴 → ⚫⚫...",
                "",
                "✅ Se a cor for igual: ACERTO",
                "❌ Se for diferente: GALE 1, GALE 2, GALE 3...",
                "",
                "⚪ Os próximos Brancos não interrompem nem reiniciam o caminho.",
                "",
                f"🕐 Branco selecionado: {hora_branco}",
                "",
                f"💡 Você pode escolher outra quantidade ou analisar agora todas as {disponiveis_texto} rodadas disponíveis.",
                "",
                "👇 Clique abaixo para continuar:",
            ])

            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            if disponiveis > 0:
                markup.add(
                    telebot.types.InlineKeyboardButton(
                        f"👁️ VER {disponiveis_texto} RODADAS DISPONÍVEIS",
                        callback_data=f"surfe_disponiveis:{disponiveis}"
                    )
                )
            markup.add(
                telebot.types.InlineKeyboardButton(
                    "🔽 OCULTAR SURF", callback_data="surfe_ocultar"
                )
            )
            m = bot.send_message(chat_id, mensagem, reply_markup=markup)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            return

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("👁️ VER SURFE", callback_data="surfe_ver"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
        _, hora_branco = formatar_data_hora(
            dados[estado["branco_index"]].get("instant"),
            dados[estado["branco_index"]].get("tempo")
        )
        quantidade_texto = f"{quantidade:,}".replace(",", ".")
        explicacao = "\n".join([
            "🏄 SURFE — ANÁLISE ESTATÍSTICA",
            "",
            f"📚 Serão analisadas as {quantidade_texto} rodadas após o Branco selecionado.",
            "",
            "📌 COMO FUNCIONA:",
            "",
            "Após o Branco selecionado, começamos dois caminhos simultaneamente:",
            "",
            "⚫ SURFE 2 PRETOS:",
            "⚫⚫ → 🔴🔴 → ⚫⚫ → 🔴🔴...",
            "",
            "🔴 SURFE 2 VERMELHOS:",
            "🔴🔴 → ⚫⚫ → 🔴🔴 → ⚫⚫...",
            "",
            "A cada rodada, comparamos a cor que realmente",
            "saiu com a cor que cada SURFE teria jogado.",
            "",
            "✅ Se a cor for igual: ACERTO",
            "❌ Se for diferente: GALE 1, GALE 2, GALE 3...",
            "O Gale continua aumentando até acertar.",
            "",
            "⚪ Os Brancos seguintes não interrompem",
            "nem reiniciam o caminho. A análise continua",
            f"normalmente até completar as {quantidade_texto} rodadas.",
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"🕐 Branco selecionado: {hora_branco}",
            "",
            f"👇 Clique abaixo para visualizar as {quantidade_texto} rodadas:",
        ])
        m = bot.send_message(chat_id, explicacao, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_disponiveis:"))
def surfe_disponiveis_callback(call):
    try:
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        if estado.get("branco_index") is None:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "❌ Escolha primeiro um ⚪ Branco para iniciar o SURF.")
            return

        disponiveis = int(call.data.split(":", 1)[1])
        if disponiveis <= 0:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "❌ Não existem rodadas disponíveis após esse Branco.")
            return

        # Usa exatamente todas as rodadas disponíveis após o Branco selecionado.
        estado["quantidade"] = disponiveis
        surfe_cache[chat_id] = estado

        # Reaproveita o mesmo fluxo já usado pelo botão VER SURFE.
        surfe_ver_callback(call)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "surfe_ver")
def surfe_ver_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")
        quantidade = estado.get("quantidade")

        if indice is None:
            bot.send_message(chat_id, "❌ Escolha primeiro um ⚪ Branco para iniciar o SURF.")
            return

        if quantidade is None:
            bot.send_message(chat_id, "❌ Escolha primeiro a quantidade de rodadas.")
            return

        analise = analisar_surfe_a_partir_do_branco(indice, limite=quantidade)
        if not analise:
            bot.send_message(chat_id, "❌ Não foi possível recuperar o Branco inicial.")
            return

        if len(analise["registros"]) < quantidade:
            disponiveis = len(analise["registros"])
            quantidade_texto = f"{quantidade:,}".replace(",", ".")
            disponiveis_texto = f"{disponiveis:,}".replace(",", ".")

            dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
            _, hora_branco = formatar_data_hora(
                dados[estado["branco_index"]].get("instant"),
                dados[estado["branco_index"]].get("tempo")
            )

            mensagem = "\n".join([
                "❌ QUANTIDADE INDISPONÍVEL",
                "",
                f"⚪ Após o Branco selecionado existem apenas {disponiveis_texto} rodadas disponíveis.",
                "",
                f"📊 Você solicitou {quantidade_texto} rodadas, mas ainda não existem {quantidade_texto} rodadas após esse Branco.",
                "",
                "🏄 SOBRE A ANÁLISE SURF",
                "",
                "Após o Branco selecionado, serão analisados dois caminhos simultaneamente:",
                "",
                "⚫ SURFE 2 PRETOS:",
                "⚫⚫ → 🔴🔴 → ⚫⚫ → 🔴🔴...",
                "",
                "🔴 SURFE 2 VERMELHOS:",
                "🔴🔴 → ⚫⚫ → 🔴🔴 → ⚫⚫...",
                "",
                "✅ Se a cor for igual: ACERTO",
                "❌ Se for diferente: GALE 1, GALE 2, GALE 3...",
                "",
                "⚪ Os próximos Brancos não interrompem nem reiniciam o caminho.",
                "",
                f"🕐 Branco selecionado: {hora_branco}",
                "",
                f"💡 Você pode escolher outra quantidade ou analisar agora todas as {disponiveis_texto} rodadas disponíveis.",
                "",
                "👇 Clique abaixo para continuar:",
            ])

            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            if disponiveis > 0:
                markup.add(
                    telebot.types.InlineKeyboardButton(
                        f"👁️ VER {disponiveis_texto} RODADAS DISPONÍVEIS",
                        callback_data=f"surfe_disponiveis:{disponiveis}"
                    )
                )
            markup.add(
                telebot.types.InlineKeyboardButton(
                    "🔽 OCULTAR SURF", callback_data="surfe_ocultar"
                )
            )

            m = bot.send_message(chat_id, mensagem, reply_markup=markup)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            return

        # Guarda exatamente o mesmo recorte que acabou de ser exibido no SURF.
        # A área APOSTA e a análise por gatilho reutilizam este resultado, evitando
        # reconstruir o Branco por uma posição que pode mudar na janela móvel.
        estado["ultima_analise"] = analise
        surfe_cache[chat_id] = estado

        resultado = montar_resultado_surfe(analise)

        # Cabeçalho e estatística continuam separados.
        # As rodadas agora são enviadas em blocos naturais:
        # 01–99, 100–199, 200–299 ... sem corte por caracteres.
        partes = resultado.split("§§§SURF_RODADAS§§§", 1)
        mensagem_cabecalho = partes[0].strip()
        restante = partes[1] if len(partes) == 2 else ""
        partes2 = restante.split("§§§SURF_ESTATISTICA§§§", 1)
        mensagem_estatistica = partes2[1].strip() if len(partes2) == 2 else ""

        if mensagem_cabecalho:
            m = bot.send_message(chat_id, mensagem_cabecalho)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        # Repete SURF🔴 / SURF⚫ no topo de cada novo bloco.
        for bloco_rodadas in _montar_blocos_surfe(analise["registros"]):
            m = bot.send_message(chat_id, bloco_rodadas)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        if mensagem_estatistica:
            m = bot.send_message(chat_id, mensagem_estatistica)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🔥 VER GALES",
                callback_data="surfe_gales"
            )
        )
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🔥 GALE AVANÇADO",
                callback_data="surfe_gale_avancado"
            )
        )
        markup.add(
            telebot.types.InlineKeyboardButton(
                "💰 APOSTA",
                callback_data="surfe_aposta_menu"
            )
        )
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🔽 OCULTAR SURF",
                callback_data="surfe_ocultar"
            )
        )

        m = bot.send_message(
            chat_id,
            f"👇 Depois das {quantidade} rodadas, você pode consultar os Gales:",
            reply_markup=markup
        )
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro no SURF: {type(erro).__name__}: {str(erro)[:250]}"
            )
        except Exception:
            pass


def _formatar_reais_surfe(valor):
    valor = Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _parse_valor_aposta_surfe(texto):
    bruto = (texto or "").strip().upper().replace("R$", "").replace(" ", "")
    if not bruto:
        raise InvalidOperation
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    valor = Decimal(bruto)
    if valor <= 0:
        raise InvalidOperation
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _simular_aposta_surfe(analise, caminho, limite_gale, entrada):
    """Simula a gestão por ciclos sobre os mesmos resultados exibidos no SURF."""
    campo = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
    linhas = []
    saldo = Decimal("0.00")
    menor_saldo = Decimal("0.00")
    maior_saldo = Decimal("0.00")
    maior_drawdown = Decimal("0.00")
    maior_aposta_usada = Decimal("0.00")
    sequencia_perdas = 0
    maior_gale_usado = 0
    stops = 0
    acertos_diretos = 0
    ciclos_recuperados = 0
    rodadas_perdidas = 0
    prejuizo_stops = Decimal("0.00")

    for registro in analise["registros"]:
        resultado = registro[campo]
        aposta = entrada * (Decimal(2) ** sequencia_perdas)
        maior_aposta_usada = max(maior_aposta_usada, aposta)

        if resultado.startswith("✅"):
            # Se não havia perda anterior, foi acerto direto. Caso contrário,
            # a aposta vencedora recupera as perdas do ciclo e deixa +1 entrada.
            if sequencia_perdas == 0:
                acertos_diretos += 1
                marcador = "✅ DIRETO"
            else:
                ciclos_recuperados += 1
                marcador = f"✅ RECUPEROU G{sequencia_perdas}"
            saldo += aposta
            sequencia_perdas = 0
        else:
            rodadas_perdidas += 1
            saldo -= aposta
            sequencia_perdas += 1
            maior_gale_usado = max(maior_gale_usado, sequencia_perdas)
            marcador = f"❌ G{sequencia_perdas}"
            if sequencia_perdas >= limite_gale:
                stops += 1
                prejuizo_stops += entrada * ((Decimal(2) ** limite_gale) - Decimal(1))
                marcador += " 🛑 STOP"
                sequencia_perdas = 0

        menor_saldo = min(menor_saldo, saldo)
        maior_saldo = max(maior_saldo, saldo)
        maior_drawdown = max(maior_drawdown, maior_saldo - saldo)
        numero_texto = f"{int(registro['numero']):>3}"
        marcador_compacto = marcador
        if marcador_compacto.startswith("✅ RECUPEROU G"):
            marcador_compacto = marcador_compacto.replace("✅ RECUPEROU G", "♻️ REC.G", 1)
        elif marcador_compacto.startswith("❌ G"):
            marcador_compacto = marcador_compacto.replace("❌ G", "❌ G", 1)
        elif marcador_compacto == "✅ DIRETO":
            marcador_compacto = "✅ DIRETO"

        # Colunas compactas para leitura no Telegram.
        # Os espaços são apenas visuais e não alteram nenhum cálculo.
        marcador_coluna = f"{marcador_compacto:<15}"
        valor_coluna = _formatar_reais_surfe(aposta).replace("R$ ", "R$")
        saldo_coluna = _formatar_reais_surfe(saldo).replace("R$ ", "")
        linhas.append(
            f"{numero_texto}  {marcador_coluna} {valor_coluna:<10} {saldo_coluna}"
        )

    risco_ciclo = entrada * ((Decimal(2) ** limite_gale) - Decimal(1))
    aposta_maxima_limite = entrada * (Decimal(2) ** (limite_gale - 1))
    ciclos_para_recuperar_stop = int(risco_ciclo / entrada)
    ciclos_positivos = acertos_diretos + ciclos_recuperados
    lucro_ciclos_positivos = entrada * ciclos_positivos

    # Se a amostra terminar no meio de um Gale, esse ciclo ainda está aberto:
    # as perdas já aconteceram, mas ainda não houve acerto nem STOP.
    perda_ciclo_aberto = Decimal("0.00")
    if sequencia_perdas > 0:
        perda_ciclo_aberto = entrada * ((Decimal(2) ** sequencia_perdas) - Decimal(1))

    saldo_por_ciclos = lucro_ciclos_positivos - prejuizo_stops - perda_ciclo_aberto

    return {
        "linhas": linhas,
        "saldo": saldo,
        "saldo_por_ciclos": saldo_por_ciclos,
        "menor_saldo": menor_saldo,
        "maior_drawdown": maior_drawdown,
        "maior_aposta_usada": maior_aposta_usada,
        "aposta_maxima_limite": aposta_maxima_limite,
        "risco_ciclo": risco_ciclo,
        "ciclos_para_recuperar_stop": ciclos_para_recuperar_stop,
        "stops": stops,
        "acertos_diretos": acertos_diretos,
        "ciclos_recuperados": ciclos_recuperados,
        "ciclos_positivos": ciclos_positivos,
        "lucro_ciclos_positivos": lucro_ciclos_positivos,
        "prejuizo_stops": prejuizo_stops,
        "rodadas_perdidas": rodadas_perdidas,
        "maior_gale_usado": maior_gale_usado,
        "ciclo_aberto_gale": sequencia_perdas,
        "perda_ciclo_aberto": perda_ciclo_aberto,
    }



def _obter_analise_surfe_selecionada(chat_id):
    """Retorna o mesmo recorte exibido no SURF sempre que ele estiver em cache."""
    estado = surfe_cache.get(chat_id) or {}
    quantidade = estado.get("quantidade")
    indice = estado.get("branco_index")
    analise = estado.get("ultima_analise")

    if quantidade is None or indice is None:
        return None

    if analise and len(analise.get("registros", [])) == int(quantidade):
        return analise

    analise = analisar_surfe_a_partir_do_branco(indice, limite=quantidade)
    if analise and len(analise.get("registros", [])) == int(quantidade):
        estado["ultima_analise"] = analise
        surfe_cache[chat_id] = estado
        return analise
    return None


def _analisar_entrada_por_gatilho(analise, caminho, gatilho):
    """Cria uma nova sequência usando o Gale escolhido como gatilho de entrada."""
    campo = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
    registros = analise.get("registros", [])
    oportunidades = []

    # O gatilho aparece em uma rodada; a entrada é avaliada somente na rodada seguinte.
    for pos in range(len(registros) - 1):
        atual = registros[pos]
        resultado_atual = str(atual.get(campo, ""))
        if resultado_atual != f"❌ GALE {gatilho}":
            continue

        proxima = registros[pos + 1]
        resultado_entrada = str(proxima.get(campo, ""))
        oportunidades.append({
            "gatilho_rodada": int(atual.get("numero", pos + 1)),
            "entrada_rodada": int(proxima.get("numero", pos + 2)),
            "acertou": resultado_entrada.startswith("✅"),
            "resultado_original": resultado_entrada,
        })

    sequencia_perdas = 0
    maior_gale = 0
    gale_counts = {}
    acertos = 0
    erros = 0
    acertos_diretos = 0
    ciclos_recuperados = 0
    linhas = []

    for numero_oportunidade, item in enumerate(oportunidades, start=1):
        if item["acertou"]:
            acertos += 1
            if sequencia_perdas == 0:
                acertos_diretos += 1
                marcador = "✅ DIRETO"
            else:
                ciclos_recuperados += 1
                marcador = f"♻️ REC.G{sequencia_perdas}"
                sequencia_perdas = 0
        else:
            erros += 1
            sequencia_perdas += 1
            maior_gale = max(maior_gale, sequencia_perdas)
            gale_counts[sequencia_perdas] = gale_counts.get(sequencia_perdas, 0) + 1
            marcador = f"❌ G{sequencia_perdas}"

        # Deixa explícito o que é gatilho do SURF e o que é Gale da aposta.
        if marcador.startswith("❌ G"):
            marcador_exibicao = marcador.replace("❌ G", "❌ APOSTA G", 1)
        else:
            marcador_exibicao = marcador

        linhas.append(
            f"{numero_oportunidade:02d}  🎯 G{gatilho} na {item['gatilho_rodada']} → "
            f"💰 Entrada {item['entrada_rodada']} → {marcador_exibicao}"
        )

    total = len(oportunidades)
    taxa = (acertos / total * 100) if total else 0.0
    unidades = acertos - erros

    if total < 20:
        classificacao = "AMOSTRA PEQUENA ⚠️"
    elif unidades > 0:
        classificacao = "POSITIVA NO RECORTE ✅"
    elif unidades < 0:
        classificacao = "NEGATIVA NO RECORTE ❌"
    else:
        classificacao = "NEUTRA NO RECORTE ➖"

    return {
        "gatilho": gatilho,
        "oportunidades": oportunidades,
        "linhas": linhas,
        "total": total,
        "acertos": acertos,
        "erros": erros,
        "taxa": taxa,
        "unidades": unidades,
        "classificacao": classificacao,
        "acertos_diretos": acertos_diretos,
        "ciclos_recuperados": ciclos_recuperados,
        "maior_gale": maior_gale,
        "gale_counts": gale_counts,
        "ciclo_aberto_gale": sequencia_perdas,
    }


def _enviar_blocos_gatilho_surfe(chat_id, linhas):
    """Envia a entrada por gatilho em mensagens separadas de até 10 entradas."""
    if not linhas:
        return

    # Cada grupo de 10 entradas vira um novo balão/mensagem no Telegram.
    # Isso evita que uma sequência grande continue no mesmo balão e bata
    # no limite de caracteres da mensagem.
    for inicio in range(0, len(linhas), 10):
        bloco = linhas[inicio:inicio + 10]
        m = bot.send_message(chat_id, "\n".join(bloco))
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)


def _enviar_blocos_aposta_surfe(chat_id, linhas):
    """Envia a simulação em novos balões, com no máximo 10 entradas por mensagem."""
    if not linhas:
        return

    # Regra visual: 1–10 em um balão, 11–20 em outro, e assim por diante.
    for inicio in range(0, len(linhas), 10):
        bloco = linhas[inicio:inicio + 10]
        eh_ultimo = inicio + 10 >= len(linhas)
        markup = None
        if eh_ultimo:
            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                telebot.types.InlineKeyboardButton(
                    "⬆️ ENTENDER A SIMULAÇÃO ⬆️",
                    callback_data="surfe_aposta_simulacao_info",
                )
            )
        m = bot.send_message(chat_id, "\n".join(bloco), reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)


def _receber_valor_aposta_surfe(message):
    chat_id = message.chat.id
    estado = surfe_cache.get(chat_id) or {}
    try:
        caminho = estado.get("aposta_caminho")
        limite_gale = estado.get("aposta_limite_gale")
        indice = estado.get("branco_index")
        quantidade = estado.get("quantidade")
        if caminho not in ("Vermelho", "Preto") or not limite_gale or indice is None or not quantidade:
            bot.send_message(chat_id, "❌ A configuração da APOSTA expirou. Abra novamente o botão 💰 APOSTA.")
            return

        try:
            entrada = _parse_valor_aposta_surfe(message.text)
        except (InvalidOperation, ValueError):
            msg = bot.send_message(
                chat_id,
                "❌ Valor inválido.\n\n"
                "Digite somente o valor da aposta inicial.\n"
                "Exemplos: 0,10 | 0,20 | 1,00"
            )
            bot.register_next_step_handler(msg, _receber_valor_aposta_surfe)
            return

        analise = _obter_analise_surfe_selecionada(chat_id)
        if not analise:
            bot.send_message(chat_id, "❌ As rodadas selecionadas não estão mais disponíveis para a simulação.")
            return

        resultado = _simular_aposta_surfe(analise, caminho, int(limite_gale), entrada)
        campo_base = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
        resultados_base = [str(x.get(campo_base, "")).startswith("✅") for x in analise["registros"]]
        estado["gale_avancado_base"] = {
            "resultados": resultados_base,
            "entrada": str(entrada),
            "titulo": "💵 SIMULAÇÃO CONTÍNUA",
            "subtitulo": f"⚪ {analise['data_branco']} às {analise['hora_branco']}",
        }
        surfe_cache[chat_id] = estado
        cor = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "2 VERMELHOS" if caminho == "Vermelho" else "2 PRETOS"

        cabecalho = "\n".join([
            f"💰 SIMULAÇÃO DE APOSTA — SURF{cor}",
            "",
            f"🏄 Caminho: SURF {nome}",
            f"📚 Rodadas: {quantidade}",
            f"⚪ Branco inicial: {analise['data_branco']} às {analise['hora_branco']}",
            f"💵 Entrada inicial: {_formatar_reais_surfe(entrada)}",
            f"🎯 Limite escolhido: G{limite_gale}",
            "",
            "📌 REGRA DA SIMULAÇÃO",
            "A cada perda, a próxima aposta dobra.",
            f"Se perder também no G{limite_gale}, registra STOP.",
            "Na rodada seguinte ao STOP, volta para a entrada inicial.",
            "Se acertar antes do limite, o próximo ciclo também volta para a entrada inicial.",
            "",
            "👇 Abaixo está a simulação sobre a mesma sequência de rodadas do SURF:",
        ])
        m = bot.send_message(chat_id, cabecalho)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
        _enviar_blocos_aposta_surfe(chat_id, resultado["linhas"])

        status = "POSITIVO ✅" if resultado["saldo"] > 0 else ("NEGATIVO ❌" if resultado["saldo"] < 0 else "EMPATE ➖")
        compensou = "SIM ✅" if resultado["saldo"] >= 0 else "NÃO ❌"
        maior_gale_texto = f"G{resultado['maior_gale_usado']}" if resultado["maior_gale_usado"] else "Nenhum"

        resumo_linhas = [
            "📊 RESULTADO FINANCEIRO DA SIMULAÇÃO",
            "",
            f"🏄 SURF {nome}",
            f"📚 Rodadas analisadas: {quantidade}",
            f"💵 Entrada inicial: {_formatar_reais_surfe(entrada)}",
            f"🎯 Limite escolhido: G{limite_gale}",
            "",
            "📊 RESULTADO DOS CICLOS",
            "",
            f"🟢 Acertos diretos: {resultado['acertos_diretos']}",
            f"♻️ Ciclos recuperados no Gale: {resultado['ciclos_recuperados']}",
            f"🛑 Stops no G{limite_gale}: {resultado['stops']}",
            f"💰 Ciclos positivos: {resultado['ciclos_positivos']}",
            f"💵 Lucro dos ciclos positivos: +{_formatar_reais_surfe(resultado['lucro_ciclos_positivos'])}",
            f"💸 Prejuízo total dos Stops: -{_formatar_reais_surfe(resultado['prejuizo_stops'])}",
        ]

        if resultado["ciclo_aberto_gale"] > 0:
            resumo_linhas.extend([
                f"⏳ Ciclo em aberto no final: G{resultado['ciclo_aberto_gale']}",
                f"📌 Perda já acumulada nesse ciclo: -{_formatar_reais_surfe(resultado['perda_ciclo_aberto'])}",
            ])

        resumo_linhas.extend([
            "",
            "💰 RESULTADO FINAL",
            "",
            f"📈 Saldo final: {_formatar_reais_surfe(resultado['saldo'])} — {status}",
            f"📉 Maior déficit a partir do saldo inicial: {_formatar_reais_surfe(resultado['menor_saldo'])}",
            f"📉 Maior queda a partir de um pico: {_formatar_reais_surfe(resultado['maior_drawdown'])}",
            "",
            f"🔥 Maior Gale realmente utilizado: {maior_gale_texto}",
            f"💵 Maior aposta realmente realizada: {_formatar_reais_surfe(resultado['maior_aposta_usada'])}",
            f"🎯 Maior aposta permitida no G{limite_gale}: {_formatar_reais_surfe(resultado['aposta_maxima_limite'])}",
            "",
            "♻️ RECUPERAÇÃO DAS PERDAS",
            "",
            f"🛑 Valor de 1 STOP completo no G{limite_gale}: -{_formatar_reais_surfe(resultado['risco_ciclo'])}",
            f"🎯 Para recuperar 1 STOP completo: {resultado['ciclos_para_recuperar_stop']} ciclos de +{_formatar_reais_surfe(entrada)}",
            f"📊 As sequências deste recorte compensaram as perdas no saldo final? {compensou}",
            "",
            "⚠️ Esta é uma simulação matemática baseada somente nas rodadas analisadas. Resultado passado não garante resultado futuro.",
        ])
        resumo = "\n".join(resumo_linhas)
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("⬆️ ENTENDER O RESULTADO ⬆️", callback_data="surfe_aposta_info"))
        markup.add(telebot.types.InlineKeyboardButton("💰 NOVA SIMULAÇÃO", callback_data="surfe_aposta_continua"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, resumo, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(chat_id, f"❌ Erro na simulação de APOSTA: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_simulacao_info")
def surfe_aposta_simulacao_info_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        sem_limite = (
            estado.get("gatilho_modo") == "sem_limite"
            or estado.get("aposta_modo") == "sem_limite"
        )
        linhas = [
            "ℹ️ COMO ENTENDER A SIMULAÇÃO",
            "",
            "Cada linha representa uma entrada realizada pela estratégia.",
            "",
            "❌ PERDEU",
            "A entrada perdeu. Na próxima oportunidade válida, o valor aumenta seguindo a progressão.",
            "",
            "♻️ RECUPEROU",
            "Depois de uma ou mais perdas, a entrada acertou e recuperou o ciclo. A próxima entrada volta ao valor inicial.",
            "",
            "✅ ACERTO DIRETO",
            "A entrada acertou usando o valor inicial, sem precisar de progressão.",
            "",
            "💵 VALOR DA APOSTA",
            "É o valor utilizado naquela entrada. Exemplo com R$10: R$10 → R$20 → R$40 → R$80...",
            "",
            "📊 SALDO",
            "É o lucro ou prejuízo total acumulado depois daquela entrada.",
            "",
            "📌 EXEMPLO",
            "❌  R$40,00  R$-70,00 = apostou R$40, perdeu e o saldo acumulado ficou em -R$70.",
            "♻️  R$80,00  R$10,00 = apostou R$80, recuperou o ciclo e o saldo acumulado passou para +R$10.",
        ]
        if sem_limite:
            linhas += [
                "",
                "♾️ SEM LIMITE",
                "Não existe um Gale máximo configurado para interromper a simulação. A progressão histórica continua até uma recuperação ou até terminar o recorte analisado.",
            ]
        else:
            linhas += [
                "",
                "🛑 STOP",
                "No modo COM LIMITE, aparece quando a entrada perde também no Gale definido como limite. O ciclo é encerrado e a próxima oportunidade recomeça com a entrada inicial.",
            ]
        linhas += [
            "",
            "📌 Na Entrada por Gatilho, a simulação utiliza somente as oportunidades geradas pelo gatilho escolhido.",
        ]
        m = bot.send_message(chat_id, "\n".join(linhas))
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_info")
def surfe_aposta_info_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        texto = "\n".join([
            "ℹ️ COMO ENTENDER O RESULTADO DA APOSTA",
            "",
            "🟢 ACERTOS DIRETOS",
            "São os ciclos em que a primeira aposta acertou, sem precisar entrar em Gale.",
            "",
            "♻️ CICLOS RECUPERADOS NO GALE",
            "O ciclo começou com uma ou mais perdas, mas acertou antes do limite escolhido. As apostas dobradas recuperam as perdas anteriores e deixam somente o lucro-base da entrada inicial.",
            "",
            "💰 CICLOS POSITIVOS",
            "É a soma dos acertos diretos com os ciclos recuperados no Gale. Cada ciclo positivo acrescenta o valor da entrada inicial ao resultado líquido.",
            "",
            "🛑 STOP",
            "Acontece quando a sequência perde também no Gale definido como limite. O ciclo é encerrado e a rodada seguinte volta para a aposta inicial.",
            "",
            "💸 PREJUÍZO TOTAL DOS STOPS",
            "É a soma das perdas de todos os ciclos que chegaram ao limite e não recuperaram.",
            "",
            "⏳ CICLO EM ABERTO",
            "Se as rodadas analisadas terminarem no meio de uma sequência de Gale, essas perdas já contam no saldo, mas o ciclo ainda não teve acerto nem STOP.",
            "",
            "📈 SALDO FINAL",
            "Mostra o resultado líquido real no fim do recorte: lucros dos ciclos positivos menos Stops e menos eventual ciclo ainda aberto.",
            "",
            "🔥 MAIOR GALE UTILIZADO",
            "É o maior Gale que realmente apareceu durante a simulação, mesmo que o limite escolhido fosse maior.",
            "",
            "💵 MAIOR APOSTA REALIZADA",
            "É o maior valor que realmente precisou ser apostado dentro das rodadas analisadas.",
            "",
            "📉 MAIOR DÉFICIT / MAIOR QUEDA",
            "Mostram o pior momento financeiro da simulação e ajudam a enxergar o risco, não apenas o saldo final.",
            "",
            "♻️ RECUPERAÇÃO DE 1 STOP",
            "Mostra quantos ciclos positivos, cada um com o lucro da entrada inicial, seriam necessários para compensar completamente um STOP.",
            "",
            "⚠️ A simulação usa apenas o histórico selecionado e não garante que o mesmo comportamento se repita no futuro.",
        ])
        m = bot.send_message(chat_id, texto)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_menu")
def surfe_aposta_menu_callback(call):
    """Abre o painel das análises disponíveis dentro de APOSTA."""
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        analise = _obter_analise_surfe_selecionada(chat_id)
        estado = surfe_cache.get(chat_id) or {}
        quantidade = estado.get("quantidade")
        if not analise or quantidade is None:
            bot.send_message(chat_id, "❌ Escolha primeiro o Branco e a quantidade de rodadas.")
            return

        texto = "\n".join([
            "💰 APOSTA — ANÁLISES",
            "",
            f"📚 Recorte atual: {quantidade} rodadas",
            f"⚪ Branco: {analise['data_branco']} às {analise['hora_branco']}",
            "",
            "Escolha qual tipo de análise deseja realizar:",
            "",
            "💵 SIMULAÇÃO CONTÍNUA",
            "Aposta rodada após rodada, usando a progressão e o limite de Gale escolhidos.",
            "",
            "🎯 ENTRADA POR GATILHO",
            "Espera um Gale específico aparecer no SURF e só considera entrada na rodada seguinte.",
            "Depois o bot cria uma nova sequência somente com essas oportunidades e mede os Gales entre elas.",
            "",
            "👇 Escolha uma análise:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("💵 SIMULAÇÃO CONTÍNUA", callback_data="surfe_aposta_continua"))
        markup.add(telebot.types.InlineKeyboardButton("🎯 ENTRADA POR GATILHO", callback_data="surfe_aposta_gatilho"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro em APOSTA: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_continua")
def surfe_aposta_continua_callback(call):
    """Mantém a simulação financeira contínua já existente."""
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        quantidade = estado.get("quantidade")
        analise = _obter_analise_surfe_selecionada(chat_id)
        if quantidade is None or not analise:
            bot.send_message(chat_id, "❌ Escolha primeiro o Branco e a quantidade de rodadas.")
            return

        texto = "\n".join([
            "💵 SIMULAÇÃO CONTÍNUA — SURF",
            "",
            f"📚 Esta simulação usará exatamente as mesmas {quantidade} rodadas analisadas após o Branco selecionado.",
            f"⚪ Branco: {analise['data_branco']} às {analise['hora_branco']}",
            "",
            "📌 COMO FUNCIONA",
            "Você escolhe qual caminho do SURF deseja testar, define até qual Gale aceita dobrar e depois informa o valor da aposta inicial.",
            "",
            "❌ A cada perda, a próxima aposta dobra.",
            "✅ Ao acertar, o próximo ciclo volta para a aposta inicial.",
            "🛑 Se perder também no limite de Gale escolhido, o sistema registra o prejuízo daquele ciclo e reinicia a rodada seguinte com a aposta inicial.",
            "",
            "📊 No final o bot calcula ganhos, perdas, quantidade de stops, maior aposta, perda máxima por ciclo, menor saldo e saldo final.",
            "",
            "🏄 ESCOLHA O SURF PARA SIMULAR",
            "🔴 SURF 2 VERMELHOS começa: 🔴🔴 → ⚫⚫ → 🔴🔴...",
            "⚫ SURF 2 PRETOS começa: ⚫⚫ → 🔴🔴 → ⚫⚫...",
            "",
            "👇 Escolha um dos caminhos:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="surfe_aposta_caminho:Vermelho"))
        markup.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="surfe_aposta_caminho:Preto"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR ÀS ANÁLISES", callback_data="surfe_aposta_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro na SIMULAÇÃO CONTÍNUA: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_gatilho")
def surfe_aposta_gatilho_callback(call):
    """Explica e inicia a análise de entrada condicionada a um Gale do SURF."""
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        quantidade = estado.get("quantidade")
        analise = _obter_analise_surfe_selecionada(chat_id)
        if quantidade is None or not analise:
            bot.send_message(chat_id, "❌ Escolha primeiro o Branco e a quantidade de rodadas.")
            return

        texto = "\n".join([
            "🎯 ENTRADA POR GATILHO",
            "",
            "📖 COMO FUNCIONA",
            "",
            "Nesta análise você NÃO considera entrada em todas as rodadas.",
            "O bot primeiro acompanha normalmente o SURF escolhido.",
            "",
            "Exemplo escolhendo G3:",
            "❌ G1 → apenas observa",
            "❌ G2 → apenas observa",
            "❌ G3 → 🎯 GATILHO ATIVADO",
            "➡️ A rodada seguinte vira a entrada da análise.",
            "",
            "Se essa entrada perder, o bot não entra imediatamente de novo.",
            "Ele espera aparecer OUTRO G3 e usa a rodada seguinte como a próxima oportunidade.",
            "",
            "Assim é criada uma nova sequência somente com as entradas após o G3.",
            "O bot mede quantos acertos, erros e Gales consecutivos apareceram nessa nova sequência.",
            "",
            "📊 Também mostra a taxa histórica 1:1 e a maior sequência de perdas entre os gatilhos.",
            "⚠️ Uma amostra pequena ou um bom resultado passado não garante vantagem futura.",
            "",
            f"📚 Serão usadas exatamente as mesmas {quantidade} rodadas do SURF atual.",
            "",
            "👇 Primeiro escolha qual caminho deseja analisar:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="surfe_gatilho_caminho:Vermelho"))
        markup.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="surfe_gatilho_caminho:Preto"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR ÀS ANÁLISES", callback_data="surfe_aposta_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro na ENTRADA POR GATILHO: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_caminho:"))
def surfe_gatilho_caminho_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        caminho = call.data.split(":", 1)[1]
        if caminho not in ("Vermelho", "Preto"):
            return

        estado = surfe_cache.get(chat_id) or {}
        if not _obter_analise_surfe_selecionada(chat_id):
            bot.send_message(chat_id, "❌ O recorte do SURF não está mais disponível.")
            return
        estado = surfe_cache.get(chat_id) or estado
        estado["gatilho_caminho"] = caminho
        surfe_cache[chat_id] = estado

        cor = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "2 VERMELHOS" if caminho == "Vermelho" else "2 PRETOS"
        texto = "\n".join([
            "🎯 ESCOLHA O GALE-GATILHO",
            "",
            f"🏄 Caminho: {cor} SURF {nome}",
            "",
            "O Gale escolhido será apenas o SINAL para observar uma entrada na rodada seguinte.",
            "",
            "Exemplo: escolhendo G3, toda vez que o SURF chegar ao G3, o bot confere a próxima rodada e adiciona essa oportunidade à nova sequência.",
            "",
            "👇 Escolha o gatilho que deseja estudar:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=3)
        botoes = [telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"surfe_gatilho_gale:{n}") for n in range(1, 10)]
        for pos in range(0, len(botoes), 3):
            markup.row(*botoes[pos:pos + 3])
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="surfe_aposta_gatilho"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao escolher o SURF do gatilho: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_gale:"))
def surfe_gatilho_gale_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        gatilho = int(call.data.split(":", 1)[1])
        if gatilho not in range(1, 10): return
        estado = surfe_cache.get(chat_id) or {}
        caminho = estado.get("gatilho_caminho")
        analise = _obter_analise_surfe_selecionada(chat_id)
        if caminho not in ("Vermelho", "Preto") or not analise:
            bot.send_message(chat_id, "❌ Escolha novamente o SURF e o Gale-gatilho.")
            return
        resultado = _analisar_entrada_por_gatilho(analise, caminho, gatilho)
        if not resultado["total"]:
            bot.send_message(chat_id, f"❌ Nenhuma oportunidade completa após G{gatilho} foi encontrada neste recorte.")
            return
        estado["gatilho_gale"] = gatilho
        estado["gatilho_resultado"] = resultado
        surfe_cache[chat_id] = estado
        maior = f"G{resultado['maior_gale']}" if resultado['maior_gale'] else "Nenhum"
        texto = "\n".join([
            f"🎯 GATILHO G{gatilho} — MODO FINANCEIRO", "",
            f"🔎 Oportunidades encontradas: {resultado['total']}",
            f"🔥 Maior Gale observado entre os gatilhos: {maior}", "",
            "♾️ SEM LIMITE",
            "Deixa a progressão seguir historicamente até o acerto e calcula lucro total, maior Gale solucionado, maior aposta e capital exigido no pior ciclo.", "",
            "🛑 COM LIMITE",
            "Você escolhe G1 a G9. Ao atingir o limite sem acerto, registra STOP e reinicia na próxima oportunidade do mesmo gatilho.", "",
            "👇 Escolha o modo:",
        ])
        markup=telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("♾️ SEM LIMITE", callback_data="surfe_gatilho_modo:sem_limite"))
        markup.add(telebot.types.InlineKeyboardButton("🛑 COM LIMITE", callback_data="surfe_gatilho_modo:com_limite"))
        markup.add(telebot.types.InlineKeyboardButton("🎯 TESTAR OUTRO GATILHO", callback_data=f"surfe_gatilho_caminho:{caminho}"))
        m=bot.send_message(chat_id,texto,reply_markup=markup); surfe_mensagens_abertas.setdefault(chat_id,[]).append(m.message_id)
    except Exception as erro:
        traceback.print_exc(); bot.send_message(call.message.chat.id, f"❌ Erro ao analisar gatilho: {type(erro).__name__}: {str(erro)[:200]}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_modo:"))
def surfe_gatilho_modo_callback(call):
    bot.answer_callback_query(call.id)
    chat_id=call.message.chat.id; modo=call.data.split(":",1)[1]
    estado=surfe_cache.get(chat_id) or {}; gatilho=estado.get("gatilho_gale")
    if not gatilho: bot.send_message(chat_id,"❌ Escolha novamente o Gale-gatilho."); return
    if modo=="com_limite":
        markup=telebot.types.InlineKeyboardMarkup(row_width=3)
        bs=[telebot.types.InlineKeyboardButton(f"G{n}",callback_data=f"surfe_gatilho_limite:{n}") for n in range(1,10)]
        for pos in range(0,9,3): markup.row(*bs[pos:pos+3])
        m=bot.send_message(chat_id,"🛑 LIMITE DA PROGRESSÃO ENTRE GATILHOS\n\nEscolha o Gale máximo antes de registrar STOP:",reply_markup=markup); surfe_mensagens_abertas.setdefault(chat_id,[]).append(m.message_id); return
    estado["gatilho_modo"]="sem_limite"; estado.pop("gatilho_limite",None); surfe_cache[chat_id]=estado
    msg=bot.send_message(chat_id,"💵 VALOR INICIAL — GATILHO SEM LIMITE\n\nDigite o valor da primeira aposta.\nExemplos: 0,10 | 1,00 | 10,00")
    surfe_mensagens_abertas.setdefault(chat_id,[]).append(msg.message_id); bot.register_next_step_handler(msg,_receber_valor_gatilho_surfe)

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_limite:"))
def surfe_gatilho_limite_callback(call):
    bot.answer_callback_query(call.id); chat_id=call.message.chat.id
    limite=int(call.data.split(":",1)[1]); estado=surfe_cache.get(chat_id) or {}
    estado["gatilho_modo"]="com_limite"; estado["gatilho_limite"]=limite; surfe_cache[chat_id]=estado
    msg=bot.send_message(chat_id,f"💵 VALOR INICIAL — GATILHO COM LIMITE G{limite}\n\nDigite o valor da primeira aposta:")
    surfe_mensagens_abertas.setdefault(chat_id,[]).append(msg.message_id); bot.register_next_step_handler(msg,_receber_valor_gatilho_surfe)

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_aposta_caminho:"))
def surfe_aposta_caminho_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        caminho = call.data.split(":", 1)[1]
        if caminho not in ("Vermelho", "Preto"):
            return
        estado = surfe_cache.get(chat_id) or {}
        if estado.get("branco_index") is None or estado.get("quantidade") is None:
            bot.send_message(chat_id, "❌ Escolha primeiro o Branco e a quantidade de rodadas.")
            return
        estado["aposta_caminho"] = caminho
        estado.pop("aposta_limite_gale", None)
        surfe_cache[chat_id] = estado

        cor = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "2 VERMELHOS" if caminho == "Vermelho" else "2 PRETOS"
        texto = "\n".join([
            "⚙️ MODO DA SIMULAÇÃO",
            "",
            f"🏄 Escolhido: {cor} SURF {nome}",
            "",
            "♾️ SEM LIMITE",
            "A progressão histórica continua até encontrar um acerto. O resultado mostra o maior Gale solucionado, a maior aposta realizada, o capital exigido no pior ciclo e o lucro/prejuízo final.",
            "",
            "🛑 COM LIMITE",
            "Você escolhe G1 a G9. Se perder também no limite escolhido, registra STOP e o próximo ciclo volta para a entrada inicial.",
            "",
            "👇 Escolha como deseja simular:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("♾️ SEM LIMITE", callback_data="surfe_aposta_modo:sem_limite"))
        markup.add(telebot.types.InlineKeyboardButton("🛑 COM LIMITE", callback_data="surfe_aposta_modo:com_limite"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="surfe_aposta_continua"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao escolher o SURF: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass



@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_aposta_modo:"))
def surfe_aposta_modo_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        modo = call.data.split(":", 1)[1]
        estado = surfe_cache.get(chat_id) or {}
        caminho = estado.get("aposta_caminho")
        if caminho not in ("Vermelho", "Preto"):
            bot.send_message(chat_id, "❌ Escolha primeiro qual SURF deseja simular.")
            return
        if modo == "com_limite":
            texto = "🎯 LIMITE DE GALE\n\n👇 Escolha até qual Gale deseja aceitar antes do STOP:"
            markup = telebot.types.InlineKeyboardMarkup(row_width=3)
            botoes = [telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"surfe_aposta_gale:{n}") for n in range(1, 10)]
            for pos in range(0, len(botoes), 3): markup.row(*botoes[pos:pos + 3])
            markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data=f"surfe_aposta_caminho:{caminho}"))
            m = bot.send_message(chat_id, texto, reply_markup=markup)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            return
        if modo != "sem_limite": return
        estado["aposta_modo"] = "sem_limite"
        estado.pop("aposta_limite_gale", None)
        surfe_cache[chat_id] = estado
        msg = bot.send_message(chat_id, "💵 VALOR DA APOSTA INICIAL — SEM LIMITE\n\nDigite o valor inicial.\nExemplos: 0,10 | 1,00 | 10,00\n\n♾️ O bot deixará cada progressão histórica seguir até o acerto e mostrará o maior valor necessário no recorte.")
        surfe_mensagens_abertas.setdefault(chat_id, []).append(msg.message_id)
        bot.register_next_step_handler(msg, _receber_valor_sem_limite_surfe)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao escolher modo: {type(erro).__name__}: {str(erro)[:200]}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_aposta_gale:"))
def surfe_aposta_gale_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        limite = int(call.data.split(":", 1)[1])
        if limite not in range(1, 10):
            return
        estado = surfe_cache.get(chat_id) or {}
        caminho = estado.get("aposta_caminho")
        if caminho not in ("Vermelho", "Preto"):
            bot.send_message(chat_id, "❌ Escolha primeiro qual SURF deseja simular.")
            return
        estado["aposta_limite_gale"] = limite
        surfe_cache[chat_id] = estado
        cor = "🔴" if caminho == "Vermelho" else "⚫"

        texto = "\n".join([
            "💵 VALOR DA APOSTA INICIAL",
            "",
            f"🏄 SURF escolhido: {cor}",
            f"🎯 Limite escolhido: G{limite}",
            "",
            "Agora digite quanto deseja apostar na primeira entrada.",
            "",
            "Exemplos:",
            "0,10",
            "0,20",
            "1,00",
            "",
            "📌 O sistema calculará automaticamente os valores dobrados até o limite escolhido e mostrará qual seria a maior aposta e o risco máximo do ciclo.",
            "",
            "👇 Digite o valor da entrada inicial:",
        ])
        msg = bot.send_message(chat_id, texto)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(msg.message_id)
        bot.register_next_step_handler(msg, _receber_valor_aposta_surfe)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao escolher Gale: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_gales")
def surfe_gales_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")
        quantidade = estado.get("quantidade")
        if indice is None or quantidade is None:
            bot.send_message(chat_id, "❌ Escolha primeiro o Branco e a quantidade de rodadas.")
            return
        analise = analisar_surfe_a_partir_do_branco(indice, limite=quantidade)
        if not analise or len(analise["registros"]) < quantidade:
            bot.send_message(chat_id, "❌ Não há rodadas suficientes para consultar os Gales.")
            return
        texto = "\n\n".join([
            _resumo_gales_surfe(analise["stats"], "Preto", "🔥 GALES — SURF⚫"),
            _resumo_gales_surfe(analise["stats"], "Vermelho", "🔥 GALES — SURF🔴"),
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro nos GALES: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_controle")
def surfe_controle_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")

        if indice is None:
            bot.send_message(
                chat_id,
                "❌ Escolha primeiro um ⚪ Branco para iniciar o SURF."
            )
            return

        analise = analisar_surfe_a_partir_do_branco(indice, limite=None)
        if not analise:
            bot.send_message(
                chat_id,
                "❌ Não foi possível recuperar o Branco inicial."
            )
            return

        resultado = montar_controle_geral_surfe(analise)

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🔽 OCULTAR SURF",
                callback_data="surfe_ocultar"
            )
        )

        m = bot.send_message(chat_id, resultado, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro no CONTROLE GERAL: {type(erro).__name__}: {str(erro)[:250]}"
            )
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data in ("surfe", "seq10", "seqcores", "branco_atraso", "ult50", "total", "ultima"))
def painel_callback(call):
    try:
        bot.answer_callback_query(call.id)
        # As estratégias usam diretamente os 2.000 registros já salvos no banco.
        # NÃO atualizar a API ao clicar, para a análise responder imediatamente.

        if call.data == "surfe":
            analise = analisar_surfe_inicial()
            chat_id = call.message.chat.id

            if not analise:
                bot.send_message(
                    chat_id,
                    "❌ Não encontrei nenhum ⚪ Branco nos 2.000 registros."
                )
                return

            # Limpa o estado anterior e as mensagens antigas do SURF.
            surfe_cache.pop(chat_id, None)
            surfe_mensagens_abertas[chat_id] = []

            msg = bot.send_message(chat_id, analise["intro"])
            surfe_mensagens_abertas[chat_id].append(msg.message_id)

            brancos = analise["brancos"]

            # Primeiro bloco: os 10 Brancos mais antigos.
            primeiros = brancos[:10]
            if primeiros:
                msg = bot.send_message(
                    chat_id,
                    "⚪ PRIMEIROS 10 BRANCOS MAIS ANTIGOS",
                    reply_markup=montar_botoes_brancos_surfe(
                        brancos, 0, len(primeiros)
                    )
                )
                surfe_mensagens_abertas[chat_id].append(msg.message_id)

            # Demais Brancos: continuam do antigo para o mais recente.
            # Divide em blocos para nenhum Branco recente ficar de fora do teclado.
            if len(brancos) > 10:
                TAMANHO_BLOCO_BRANCOS = 40
                for inicio_bloco in range(10, len(brancos), TAMANHO_BLOCO_BRANCOS):
                    fim_bloco = min(inicio_bloco + TAMANHO_BLOCO_BRANCOS, len(brancos))
                    msg = bot.send_message(
                        chat_id,
                        "⚪ DEMAIS BRANCOS — DO MAIS ANTIGO AO MAIS RECENTE",
                        reply_markup=montar_botoes_brancos_surfe(
                            brancos, inicio_bloco, fim_bloco
                        )
                    )
                    surfe_mensagens_abertas[chat_id].append(msg.message_id)

            msg = bot.send_message(
                chat_id,
                f"⚪ TOTAL DE BRANCOS: {len(brancos)}",
                reply_markup=telebot.types.InlineKeyboardMarkup().add(
                    telebot.types.InlineKeyboardButton(
                        "🔽 OCULTAR SURF",
                        callback_data="surfe_ocultar"
                    )
                )
            )
            surfe_mensagens_abertas[chat_id].append(msg.message_id)
            return

        if call.data == "seqcores":
            resultado = analisar_sequencias_de_cores_iguais()
            bot.send_message(call.message.chat.id, resultado)
            return

        if call.data == "branco_atraso":
            resultado = analisar_atraso_do_branco()
            # Telegram aceita no máximo 4096 caracteres por mensagem.
            for pos in range(0, len(resultado), 3900):
                bot.send_message(call.message.chat.id, resultado[pos:pos + 3900])
            return

        if call.data == "total":
            total = contar_rodadas_banco()
            bot.send_message(
                call.message.chat.id,
                f"📚 TOTAL NO HISTÓRICO\n\n🔢 {total:,} rodadas\n💾 Limite: {MAX_HISTORY:,}"
            )
            return

        if call.data == "ultima":
            dados = obter_historico_banco(limite=1)
            if not dados:
                bot.send_message(call.message.chat.id, "❌ Nenhuma rodada registrada ainda.")
                return

            r = dados[0]
            data, hora = formatar_data_hora(r.get("instant"), r.get("tempo"))
            cor = normalizar_cor_analise(r)
            bot.send_message(
                call.message.chat.id,
                f"🕐 ÚLTIMA RODADA\n\n"
                f"📅 {data}\n"
                f"⏰ {hora}\n"
                f"🎰 {r.get('numero')}\n"
                f"{emoji_cor(cor)} {str(cor or 'desconhecida').upper()}"
            )
            return

        if call.data == "ult50":
            dados = obter_historico_banco(limite=50)
            linhas = ["📊 ÚLTIMAS 50 RODADAS", ""]
            for n, r in enumerate(dados, 1):
                _, hora = formatar_data_hora(r.get("instant"), r.get("tempo"))
                cor = normalizar_cor_analise(r)
                linhas.append(f"{n:02d}. {emoji_cor(cor)} {r.get('numero')} — {hora}")
            bot.send_message(call.message.chat.id, "\n".join(linhas))
            return

        bot.send_message(
            call.message.chat.id,
            "📚 COMO FUNCIONA\n\n"
            "Esta estratégia procura, dentro dos 2.000 registros, momentos em que ocorreram "
            "10 resultados consecutivos da mesma cor.\n\n"
            "Depois de encontrar uma sequência de 10 cores iguais, analisamos as rodadas "
            "seguintes para verificar em qual posição a cor oposta apareceu.\n\n"
            "📊 O objetivo é identificar estatisticamente o comportamento das rodadas após "
            "uma sequência de 10 resultados iguais.\n\n"
            "⚠️ A análise é estatística/histórica e não garante o resultado da próxima rodada."
        )

        resultado = analisar_sequencias_de_10_completas()
        if isinstance(resultado, list):
            bot.send_message(call.message.chat.id, resultado[0])
            detalhes = resultado[1]
            for pos in range(0, len(detalhes), 3900):
                bot.send_message(call.message.chat.id, detalhes[pos:pos + 3900])
        else:
            bot.send_message(call.message.chat.id, resultado)

    except Exception as erro:
        traceback.print_exc()
        bot.send_message(
            call.message.chat.id,
            f"❌ Erro na análise: {type(erro).__name__}: {str(erro)[:250]}"
        )


@bot.message_handler(func=lambda message: True)
def responder_usuario(message):
    try:
        pergunta_usuario = message.text or ""
        if pergunta_usuario.strip().upper() == "TESTE 123":
            bot.reply_to(message, "✅ Telegram - Render - Bot está funcionando.")
            return

        # Reutiliza a base de 2.000 por alguns segundos para não fazer
        # uma requisição + 2.000 INSERTs a cada mensagem.
        atualizar_historico_tipminer()

        cor = identificar_cor_perguntada(pergunta_usuario)
        texto = pergunta_usuario.lower()
        ultima = any(x in texto for x in ("último", "última", "ultimo", "ultima"))

        # Último branco/vermelho/preto: consulta direta e atualizada no PostgreSQL.
        if cor and ultima:
            rodada = obter_ultimo_por_cor(cor)
            if not rodada:
                bot.reply_to(message, f"❌ Não encontrei nenhum {cor.lower()} salvo no histórico.")
            else:
                bot.reply_to(message, montar_resposta_ultima_cor(rodada))
            return

        # Para perguntas gerais, enviamos as 2.000 rodadas atuais ao Gemini.
        dados = obter_historico(limite=ANALYSIS_ROUNDS)
        instrucao_ia = """
Você é o ANALISADOR ESTATÍSTICO do bot da Double.

REGRA PRINCIPAL:
- Analise SOMENTE o histórico JSON fornecido.
- Cada registro é uma rodada/evento: DOUBLE=Vermelho, DEFAULT=Preto, LUCKY=Branco (0).
- O histórico está ordenado da rodada mais recente para a mais antiga.
- Nunca invente dados, horários, resultados, ocorrências ou percentuais.
- Não faça previsão, palpite, recomendação de aposta, estratégia de aposta ou gerenciamento de banca.
FORMATO DAS RESPOSTAS:
- Responda em português do Brasil.
- Seja MUITO direto e organizado.
- Não escreva introduções como "Aqui estão...", "Com base..." ou explicações da metodologia.
- Não repita a pergunta do usuário.
- Não faça textos longos ou relatórios.
- Use no máximo 12 linhas quando a pergunta puder ser respondida de forma resumida.
- Use emojis para facilitar a leitura.
- Use SEMPRE data e hora com segundos quando o horário estiver disponível.
- Não use Markdown com **, # ou tabelas.

QUANDO PEDIR RODADAS RECENTES:
- Mostre somente a quantidade solicitada, da mais recente para a mais antiga.
- Uma rodada deve ocupar UMA ÚNICA LINHA, neste formato:
  "1. 🕐 03:32:46 — 🔴 Vermelho — Nº 7"
- Não escreva "tipo: DOUBLE/DEFAULT/LUCKY", pois a cor já informa isso.
- Se houver data disponível e a consulta envolver mais de uma data, inclua a data de forma compacta.

QUANDO PEDIR ESTATÍSTICAS OU SEQUÊNCIAS:
- Mostre primeiro o resultado principal.
- Agrupe ocorrências por tamanho/cor quando isso for possível.
- Evite listar cada ocorrência individual se o usuário não pedir isso.
- Termine com um resumo curto, se houver informação útil.
EXEMPLO DE ESTILO:
📊 RESULTADO
🔴 5 iguais — 3 ocorrências
⚫ 5 iguais — 2 ocorrências
🏆 Maior: 7 🔴
📅 28/08/2026 🕐 03:11:10

IMPORTANTE: precisão primeiro, simplicidade depois. Entregue somente o que responde à pergunta.
"""
        conteudo = (
            "HISTÓRICO DA DOUBLE SALVO NO BANCO POSTGRESQL:\n" +
            json.dumps(dados, ensure_ascii=False) +
            "\n\nPERGUNTA DO USUÁRIO:\n" + pergunta_usuario
        )
        resposta = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=conteudo,
            config=types.GenerateContentConfig(
                system_instruction=instrucao_ia,
                temperature=0.1
            )
        )
        if not resposta.text:
            raise RuntimeError("Gemini retornou uma resposta vazia.")

        texto_resposta = resposta.text.strip()
        # Telegram está sendo usado sem parse_mode: remova marcadores Markdown
        # que deixam a resposta visualmente poluída (ex.: **Horário:**).
        texto_resposta = texto_resposta.replace("**", "")
        texto_resposta = texto_resposta.replace("__", "")
        # Reduz excesso de linhas em branco sem alterar o conteúdo.
        while "\n\n\n" in texto_resposta:
            texto_resposta = texto_resposta.replace("\n\n\n", "\n\n")

        bot.reply_to(message, texto_resposta)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.reply_to(
                message,
                "❌ Ainda não consegui obter os dados da Double.\n\n" +
                f"Erro: {type(erro).__name__}: {str(erro)[:300]}"
            )
        except Exception:
            pass




def _simular_sequencia_financeira(resultados, entrada, limite=None):
    """Simula uma sequência booleana; limite=None significa progressão histórica sem STOP."""
    saldo=Decimal("0.00"); menor=Decimal("0.00"); pico=Decimal("0.00"); drawdown=Decimal("0.00")
    perdas=0; maior_gale=0; maior_gale_solucionado=0; maior_aposta=Decimal("0.00")
    acertos_diretos=0; recuperados=0; stops=0; linhas=[]
    pior_capital=Decimal("0.00")
    maior_capital_total=Decimal("0.00")
    capital_ciclo_atual=Decimal("0.00")
    for i, acertou in enumerate(resultados,1):
        aposta=entrada*(Decimal(2)**perdas); maior_aposta=max(maior_aposta,aposta)
        capital_ciclo_atual += aposta
        maior_capital_total=max(maior_capital_total,capital_ciclo_atual)
        if acertou:
            if perdas: recuperados+=1; maior_gale_solucionado=max(maior_gale_solucionado,perdas); marcador="♻️"
            else: acertos_diretos+=1; marcador="✅"
            saldo += aposta; perdas=0; capital_ciclo_atual=Decimal("0.00")
        else:
            saldo -= aposta; perdas += 1; maior_gale=max(maior_gale,perdas); marcador="❌"
            pior_capital=max(pior_capital, entrada*((Decimal(2)**perdas)-Decimal(1)))
            if limite is not None and perdas>=limite:
                stops+=1; marcador = "🛑"; perdas=0; capital_ciclo_atual=Decimal("0.00")
        pico=max(pico,saldo); menor=min(menor,saldo); drawdown=max(drawdown,pico-saldo)
        linhas.append(f"{i:02d}  {marcador}   {_formatar_reais_surfe(aposta)}   {_formatar_reais_surfe(saldo)}")
    if perdas:
        pior_capital=max(pior_capital,entrada*((Decimal(2)**perdas)-Decimal(1)))
    return {"saldo":saldo,"menor":menor,"drawdown":drawdown,"maior_gale":maior_gale,"maior_gale_solucionado":maior_gale_solucionado,"maior_aposta":maior_aposta,"pior_capital":pior_capital,"maior_capital_total":maior_capital_total,"aberto":perdas,"diretos":acertos_diretos,"recuperados":recuperados,"stops":stops,"linhas":linhas}


def _enviar_resultado_financeiro_novo(chat_id, titulo, subtitulo, resultados, entrada, limite=None):
    r=_simular_sequencia_financeira(resultados,entrada,limite)
    estado = surfe_cache.get(chat_id) or {}
    estado["gale_avancado_base"] = {
        "resultados": list(resultados),
        "entrada": str(entrada),
        "titulo": titulo,
        "subtitulo": subtitulo,
    }
    surfe_cache[chat_id] = estado
    _enviar_blocos_aposta_surfe(chat_id,r["linhas"])
    modo="♾️ SEM LIMITE" if limite is None else f"🛑 COM LIMITE G{limite}"
    saldo_txt=("+" if r["saldo"]>0 else "")+_formatar_reais_surfe(r["saldo"])
    linhas=[titulo,"",subtitulo,f"⚙️ Modo: {modo}",f"💵 Entrada inicial: {_formatar_reais_surfe(entrada)}","","📊 RESULTADO DOS CICLOS","",f"🟢 Acertos diretos: {r['diretos']}",f"♻️ Ciclos recuperados: {r['recuperados']}"]
    if limite is not None: linhas.append(f"🛑 Stops: {r['stops']}")
    linhas += ["","💰 RESULTADO FINANCEIRO","",f"💰 Lucro/prejuízo total: {saldo_txt}",f"📈 Saldo final: {saldo_txt}",f"🔥 Maior Gale observado: G{r['maior_gale']}" if r['maior_gale'] else "🔥 Maior Gale observado: Nenhum",f"♻️ Maior Gale solucionado: G{r['maior_gale_solucionado']}" if r['maior_gale_solucionado'] else "♻️ Maior Gale solucionado: Nenhum",f"💵 Maior aposta individual realizada: {_formatar_reais_surfe(r['maior_aposta'])}",f"💸 Perdas acumuladas antes da recuperação: {_formatar_reais_surfe(r['pior_capital'])}",f"🏦 Capital total necessário no pior ciclo: {_formatar_reais_surfe(r['maior_capital_total'])}",f"📈 Retorno sobre o capital do pior ciclo: {(r['saldo'] / r['maior_capital_total'] * Decimal('100')):.2f}%" if r['maior_capital_total'] > 0 else "📈 Retorno sobre o capital do pior ciclo: 0,00%",f"📉 Maior déficit: {_formatar_reais_surfe(r['menor'])}",f"📉 Maior drawdown: {_formatar_reais_surfe(r['drawdown'])}"]
    if r['aberto']:
        linhas += ["",f"⏳ Ciclo em aberto no final: G{r['aberto']}","⚠️ Esse Gale ainda não foi solucionado dentro do recorte."]

    # Referência numérica baseada exclusivamente no pior ciclo encontrado neste recorte.
    capital_ref = r['maior_capital_total']
    capital_mais_resultado = capital_ref + r['saldo']
    retorno_ref = (r['saldo'] / capital_ref * Decimal("100")) if capital_ref > 0 else Decimal("0")
    retorno_ref_txt = f"{retorno_ref:.2f}".replace(".", ",")
    resultado_ref_txt = ("+" if r['saldo'] > 0 else "") + _formatar_reais_surfe(r['saldo'])
    capital_final_txt = _formatar_reais_surfe(capital_mais_resultado)
    maior_gale_ref = r['maior_gale_solucionado'] or r['maior_gale']

    linhas += [
        "",
        "💡 REFERÊNCIA DE CAPITAL — NESTA ANÁLISE",
        "",
        f"🏦 Capital necessário: {_formatar_reais_surfe(capital_ref)}",
        f"💰 Lucro/prejuízo obtido: {resultado_ref_txt}",
        f"💵 Capital + resultado: {capital_final_txt}",
        f"📈 Retorno sobre o capital de referência: {retorno_ref_txt}%",
        "",
        (f"📌 Neste recorte histórico, para atravessar o maior ciclo encontrado (G{maior_gale_ref}), "
         f"a simulação precisou de até {_formatar_reais_surfe(capital_ref)} de capital e terminou com "
         f"{resultado_ref_txt} de lucro/prejuízo."),
        "",
        f"⚠️ {_formatar_reais_surfe(capital_ref)} é uma referência baseada no pior ciclo encontrado neste recorte histórico; não representa a banca necessária para resultados futuros.",
        "",
        "⚠️ Resultado referente somente ao recorte histórico analisado; não garante o mesmo comportamento em novas rodadas.",
    ]
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    m=bot.send_message(chat_id,"\n".join(linhas), reply_markup=markup); surfe_mensagens_abertas.setdefault(chat_id,[]).append(m.message_id)


def _receber_valor_gatilho_surfe(message):
    chat_id=message.chat.id; estado=surfe_cache.get(chat_id) or {}
    try: entrada=_parse_valor_aposta_surfe(message.text)
    except Exception:
        msg=bot.send_message(chat_id,"❌ Valor inválido. Digite novamente, por exemplo: 0,10 | 1,00"); bot.register_next_step_handler(msg,_receber_valor_gatilho_surfe); return
    resultado=estado.get("gatilho_resultado") or {}; ops=resultado.get("oportunidades",[])
    if not ops: bot.send_message(chat_id,"❌ A análise do gatilho expirou. Escolha o gatilho novamente."); return
    resultados=[bool(x.get("acertou")) for x in ops]; limite=estado.get("gatilho_limite") if estado.get("gatilho_modo")=="com_limite" else None
    gatilho=estado.get("gatilho_gale"); caminho=estado.get("gatilho_caminho"); cor="🔴" if caminho=="Vermelho" else "⚫"
    analise=_obter_analise_surfe_selecionada(chat_id)
    branco_txt = f"⚪ APÓS O BRANCO SELECIONADO\n📅 {analise['data_branco']} às {analise['hora_branco']}" if analise else "⚪ APÓS O BRANCO SELECIONADO"
    _enviar_resultado_financeiro_novo(chat_id,f"🎯 RESULTADO FINANCEIRO — GATILHO G{gatilho}",f"{branco_txt}\n\n🏄 {cor} SURF | 🔎 {len(resultados)} oportunidades",resultados,entrada,limite)


def _receber_valor_sem_limite_surfe(message):
    chat_id=message.chat.id; estado=surfe_cache.get(chat_id) or {}
    try: entrada=_parse_valor_aposta_surfe(message.text)
    except Exception:
        msg=bot.send_message(chat_id,"❌ Valor inválido. Digite novamente, por exemplo: 0,10 | 1,00"); bot.register_next_step_handler(msg,_receber_valor_sem_limite_surfe); return
    analise=_obter_analise_surfe_selecionada(chat_id); caminho=estado.get("aposta_caminho")
    if not analise or caminho not in ("Vermelho","Preto"): bot.send_message(chat_id,"❌ A simulação expirou. Abra novamente a APOSTA."); return
    campo="resultado_vermelho" if caminho=="Vermelho" else "resultado_preto"; resultados=[str(x.get(campo,"")).startswith("✅") for x in analise["registros"]]
    cor="🔴" if caminho=="Vermelho" else "⚫"; _enviar_resultado_financeiro_novo(chat_id,"💵 SIMULAÇÃO CONTÍNUA — SEM LIMITE",f"🏄 {cor} SURF | 📚 {len(resultados)} rodadas",resultados,entrada,None)



def _runs_perdas_gale_avancado(resultados):
    """Retorna cada sequência de perdas uma única vez, com posição inicial e final."""
    runs = []
    inicio = None
    perdas = 0
    for i, acertou in enumerate(resultados):
        if not acertou:
            if inicio is None:
                inicio = i
            perdas += 1
            continue
        if perdas:
            runs.append({"inicio": inicio, "perdas": perdas, "fim": i, "solucionado": True})
        inicio = None
        perdas = 0
    if perdas:
        runs.append({"inicio": inicio, "perdas": perdas, "fim": len(resultados) - 1, "solucionado": False})
    return runs


def _resultados_gale_avancado_por_caminho(analise, caminho):
    campo = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
    return [str(x.get(campo, "")).startswith("✅") for x in analise.get("registros", [])]


def _ocorrencias_gale_avancado(analise, caminho, ponto):
    """Cada sequência que ultrapassou o Gale observado conta somente uma vez."""
    resultados = _resultados_gale_avancado_por_caminho(analise, caminho)
    runs = _runs_perdas_gale_avancado(resultados)
    ocorrencias = []
    for run in runs:
        if run["perdas"] <= ponto:
            continue
        ocorrencias.append({
            "caminho": caminho,
            "inicio": run["inicio"],
            "fim": run["fim"],
            "perdas": run["perdas"],
            "solucionado": run["solucionado"],
        })
    return ocorrencias


def _resumo_ponto_gale_avancado(resultados, ponto, entrada):
    """Simula dinheiro somente depois do Gale observado, reiniciando a cada ocorrência."""
    runs = _runs_perdas_gale_avancado(resultados)
    elegiveis = [r for r in runs if r["perdas"] > ponto]
    entradas = []
    profundidades = []
    abertas = 0
    for r in elegiveis:
        restante = r["perdas"] - ponto
        profundidades.append(restante)
        entradas.extend([False] * restante)
        if r["solucionado"]:
            entradas.append(True)
        else:
            abertas += 1
    sim = _simular_sequencia_financeira(entradas, entrada, None) if entradas else None
    return {
        "ponto": ponto,
        "ocorrencias": len(elegiveis),
        "profundidades": profundidades,
        "maior_restante": max(profundidades) if profundidades else 0,
        "abertas": abertas,
        "resultados": entradas,
        "sim": sim,
    }


def _candidatos_gale_avancado_surfe(analise):
    resultados_v = _resultados_gale_avancado_por_caminho(analise, "Vermelho")
    resultados_p = _resultados_gale_avancado_por_caminho(analise, "Preto")
    runs_v = _runs_perdas_gale_avancado(resultados_v)
    runs_p = _runs_perdas_gale_avancado(resultados_p)
    maior_v = max((r["perdas"] for r in runs_v), default=0)
    maior_p = max((r["perdas"] for r in runs_p), default=0)
    maior = max(maior_v, maior_p)

    if maior < 4:
        return maior_v, maior_p, []

    inicio = max(2, maior // 2 - 1)
    candidatos = []
    for ponto in range(inicio, maior):
        qtd_v = sum(1 for r in runs_v if r["perdas"] > ponto)
        qtd_p = sum(1 for r in runs_p if r["perdas"] > ponto)
        if qtd_v or qtd_p:
            candidatos.append({"ponto": ponto, "vermelho": qtd_v, "preto": qtd_p})
    return maior_v, maior_p, candidatos


@bot.callback_query_handler(func=lambda call: call.data == "surfe_gale_avancado")
def surfe_gale_avancado_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        analise = _obter_analise_surfe_selecionada(chat_id)
        if not analise:
            bot.send_message(chat_id, "❌ O recorte do SURF expirou. Escolha novamente o Branco e a quantidade de rodadas.")
            return

        maior_v, maior_p, candidatos = _candidatos_gale_avancado_surfe(analise)
        maior = max(maior_v, maior_p)
        if maior < 4 or not candidatos:
            bot.send_message(
                chat_id,
                "🔥 GALE AVANÇADO\n\n"
                f"🔴 Maior Gale SURF: G{maior_v}\n"
                f"⚫ Maior Gale SURF: G{maior_p}\n\n"
                "📌 Neste recorte não apareceu um Gale grande o suficiente para a análise avançada ser útil."
            )
            return

        estado = surfe_cache.get(chat_id) or {}
        estado["gale_avancado_candidatos"] = candidatos
        surfe_cache[chat_id] = estado

        texto = [
            "🔥 GALE AVANÇADO", "",
            f"⚪ Branco: {analise['data_branco']} às {analise['hora_branco']}",
            f"📚 Recorte: {len(analise['registros'])} rodadas", "",
            "📌 COMO FUNCIONA", "",
            "👁️ Você escolhe até qual Gale apenas observar, sem apostar.",
            "🎯 A entrada começa somente na oportunidade seguinte ao Gale escolhido.",
            "🔴⚫ O bot mostra as ocorrências reais usando o mesmo visual do SURF, com os dois lados juntos.",
            "📊 Cada sequência é contada uma única vez, mesmo que avance por vários Gales.", "",
            f"🔴 Maior Gale encontrado: G{maior_v}",
            f"⚫ Maior Gale encontrado: G{maior_p}", "",
            "👇 Escolha o Gale que deseja deixar em observação:"
        ]

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for item in candidatos:
            ponto = item["ponto"]
            total = item["vermelho"] + item["preto"]
            aviso = " ⚠️" if total < 5 else ""
            markup.add(telebot.types.InlineKeyboardButton(
                f"👁️ APÓS G{ponto} — 🔴 {item['vermelho']} | ⚫ {item['preto']}{aviso}",
                callback_data=f"surfe_gale_avancado_ponto:{ponto}"
            ))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, "\n".join(texto), reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro no Gale Avançado: {type(erro).__name__}: {str(erro)[:220]}")


def _recortar_visual_surfe_original(analise, inicio, fim):
    """Monta o recorte do Gale Avançado com alinhamento automático próprio.

    O SURF principal não é alterado. As duas colunas usam as MESMAS linhas
    individuais do SURF já aprovado; aqui apenas normalizamos automaticamente
    o ponto onde a coluna da direita começa. Assim exemplos com 2/3/4 dígitos,
    ✅, G1–G9 e GA–GZ não precisam de calibração ocorrência por ocorrência.
    """
    registros = analise.get("registros") or []
    if not registros or inicio < 0 or fim < inicio or fim >= len(registros):
        return ""

    trecho = registros[inicio:fim + 1]
    numero_final_analise = int(registros[-1]["numero"])

    # Reaproveita exatamente o montador de cada lado do SURF normal.
    esquerda = _montar_linhas_estrategia_surfe(
        trecho, "Vermelho", numero_final_analise
    )
    direita = _montar_linhas_estrategia_surfe(
        trecho, "Preto", numero_final_analise
    )

    if not esquerda or not direita:
        return ""

    # Âncora automática: a coluna direita começa sempre depois da maior largura
    # visual encontrada na coluna esquerda desta ocorrência. Isso elimina a
    # necessidade de ajustes específicos para cada exemplo.
    largura_alvo = max(_largura_visual_surfe(linha) for linha in esquerda)

    linhas = ["SURF🔴" + ("\u2007" * 5) + "SURF⚫", ""]
    for linha_esq, linha_dir in zip(esquerda, direita):
        largura_atual = _largura_visual_surfe(linha_esq)
        faltam = max(0, largura_alvo - largura_atual)

        # Figure Space mantém uma largura mais estável no texto normal do Telegram.
        # Um espaço-base separa as colunas mesmo na linha mais larga.
        separador = ("\u2007" * (faltam + 1))
        linhas.append(linha_esq + separador + linha_dir)

    return "\n".join(linhas)


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gale_avancado_ponto:"))
def surfe_gale_avancado_ponto_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        ponto = int(call.data.split(":", 1)[1])
        analise = _obter_analise_surfe_selecionada(chat_id)
        if not analise:
            bot.send_message(chat_id, "❌ O recorte do SURF expirou. Abra novamente o Gale Avançado.")
            return

        ocorrencias = (
            _ocorrencias_gale_avancado(analise, "Vermelho", ponto)
            + _ocorrencias_gale_avancado(analise, "Preto", ponto)
        )
        ocorrencias.sort(key=lambda x: (x["inicio"], 0 if x["caminho"] == "Vermelho" else 1))

        if not ocorrencias:
            bot.send_message(chat_id, f"❌ Nenhuma sequência ultrapassou G{ponto} neste recorte.")
            return

        estado = surfe_cache.get(chat_id) or {}
        estado["gale_avancado_ponto"] = ponto
        surfe_cache[chat_id] = estado

        qtd_v = sum(1 for x in ocorrencias if x["caminho"] == "Vermelho")
        qtd_p = sum(1 for x in ocorrencias if x["caminho"] == "Preto")
        intro = [
            f"🔥 OCORRÊNCIAS — APÓS G{ponto}", "",
            f"👁️ G1 até G{ponto}: somente observação.",
            f"💰 A entrada começa na oportunidade seguinte ao G{ponto}.",
            "🔎 Abaixo estão os exemplos reais recortados da própria tabela do SURF.",
            "🔴⚫ Os dois lados continuam juntos para facilitar a conferência.", "",
            f"🔴 Ocorrências SURF: {qtd_v}",
            f"⚫ Ocorrências SURF: {qtd_p}",
            f"📊 Total de exemplos: {len(ocorrencias)}",
        ]
        m = bot.send_message(chat_id, "\n".join(intro))
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        registros = analise["registros"]
        for n, oc in enumerate(ocorrencias, 1):
            inicio = oc["inicio"]
            fim = oc["fim"]
            trecho = registros[inicio:fim + 1]
            if not trecho:
                continue

            lado = "🔴 SURF" if oc["caminho"] == "Vermelho" else "⚫ SURF"
            rodada_inicio = int(registros[inicio]["numero"])
            idx_gale = inicio + ponto - 1
            idx_entrada = inicio + ponto
            rodada_gale = int(registros[idx_gale]["numero"]) if idx_gale < len(registros) else "?"
            rodada_entrada = int(registros[idx_entrada]["numero"]) if idx_entrada < len(registros) else "?"
            rodada_fim = int(registros[fim]["numero"])
            status_fim = "✅ recuperou" if oc["solucionado"] else "⏳ terminou em aberto"

            titulo = (
                f"🔥 OCORRÊNCIA {n} — {lado}\n\n"
                f"📍 Começou: rodada {rodada_inicio}\n"
                f"👁️ G{ponto}: rodada {rodada_gale}\n"
                f"💰 Entrada após G{ponto}: rodada {rodada_entrada}\n"
                f"🏁 Terminou: rodada {rodada_fim} — {status_fim}\n\n"
            )
            # Usa exatamente as linhas já renderizadas pelo SURF principal.
            # Assim o recorte do Gale Avançado fica 100% com o mesmo alinhamento.
            visual = _recortar_visual_surfe_original(analise, inicio, fim)
            m = bot.send_message(chat_id, titulo + visual)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            f"💵 SIMULAR VALOR A PARTIR DO G{ponto}",
            callback_data=f"surfe_gale_avancado_valor:{ponto}"
        ))
        markup.add(telebot.types.InlineKeyboardButton("🔄 TROCAR GALE OBSERVADO", callback_data="surfe_gale_avancado"))
        m = bot.send_message(
            chat_id,
            f"💵 SIMULAÇÃO FINANCEIRA — APÓS G{ponto}\n\n"
            "📌 A simulação usa somente as ocorrências mostradas acima.\n"
            f"👁️ G1 até G{ponto} não recebem aposta.\n"
            f"🎯 A primeira entrada financeira acontece somente depois do G{ponto}.",
            reply_markup=markup
        )
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao mostrar as ocorrências: {type(erro).__name__}: {str(erro)[:220]}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gale_avancado_valor:"))
def surfe_gale_avancado_valor_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        ponto = int(call.data.split(":", 1)[1])
        estado = surfe_cache.get(chat_id) or {}
        estado["gale_avancado_ponto"] = ponto
        surfe_cache[chat_id] = estado

        msg = bot.send_message(
            chat_id,
            f"💵 VALOR DA ENTRADA — APÓS G{ponto}\n\n"
            f"👁️ G1 até G{ponto}: somente observação.\n"
            f"🎯 A primeira aposta começa na oportunidade seguinte ao G{ponto}.\n\n"
            "Digite o valor da entrada inicial.\n"
            "Exemplos: 0,10 | 1,00 | 10,00"
        )
        bot.register_next_step_handler(msg, _receber_valor_gale_avancado_surfe)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao solicitar o valor: {type(erro).__name__}: {str(erro)[:220]}")


def _receber_valor_gale_avancado_surfe(message):
    chat_id = message.chat.id
    estado = surfe_cache.get(chat_id) or {}
    ponto = estado.get("gale_avancado_ponto")
    if not ponto:
        bot.send_message(chat_id, "❌ O Gale observado expirou. Abra novamente o Gale Avançado.")
        return

    try:
        entrada = _parse_valor_aposta_surfe(message.text)
    except Exception:
        msg = bot.send_message(chat_id, "❌ Valor inválido. Digite novamente, por exemplo: 0,10 | 1,00 | 10,00")
        bot.register_next_step_handler(msg, _receber_valor_gale_avancado_surfe)
        return

    analise = _obter_analise_surfe_selecionada(chat_id)
    if not analise:
        bot.send_message(chat_id, "❌ O recorte do SURF expirou. Abra novamente o Gale Avançado.")
        return

    blocos = [
        f"📊 RESULTADO — GALE AVANÇADO APÓS G{ponto}", "",
        f"⚪ Branco: {analise['data_branco']} às {analise['hora_branco']}",
        f"📚 Recorte: {len(analise['registros'])} rodadas",
        f"👁️ Gale observado: G{ponto}",
        f"💵 Entrada inicial: {_formatar_reais_surfe(entrada)}", "",
        f"📌 G1 até G{ponto} ficaram somente em observação.",
        f"🎯 O dinheiro entrou somente na oportunidade seguinte ao G{ponto}.",
    ]

    for caminho, emoji, nome in (("Vermelho", "🔴", "SURF 2 VERMELHOS"), ("Preto", "⚫", "SURF 2 PRETOS")):
        resultados = _resultados_gale_avancado_por_caminho(analise, caminho)
        info = _resumo_ponto_gale_avancado(resultados, int(ponto), entrada)
        sim = info.get("sim")
        blocos += ["", f"{emoji} {nome}"]
        if not sim:
            blocos += [f"🔎 Ocorrências após G{ponto}: 0", "📌 Sem entradas financeiras neste lado."]
            continue

        saldo = sim["saldo"]
        saldo_txt = ("+" if saldo > 0 else "") + _formatar_reais_surfe(saldo)
        capital = sim["maior_capital_total"]
        retorno = (saldo / capital * Decimal("100")) if capital > 0 else Decimal("0")
        retorno_txt = f"{retorno:.2f}".replace(".", ",")
        blocos += [
            f"🔎 Ocorrências após G{ponto}: {info['ocorrencias']}",
            f"🔥 Maior progressão financeira após G{ponto}: G{info['maior_restante']}",
            f"💰 Lucro/prejuízo: {saldo_txt}",
            f"💵 Maior aposta realizada: {_formatar_reais_surfe(sim['maior_aposta'])}",
            f"🏦 Capital necessário no pior ciclo: {_formatar_reais_surfe(capital)}",
            f"📈 Retorno sobre esse capital: {retorno_txt}%",
            f"♻️ Ciclos recuperados: {sim['recuperados']}",
            f"🟢 Acertos diretos: {sim['diretos']}",
        ]
        if sim["aberto"]:
            blocos.append(f"⏳ Ciclo em aberto no final: G{sim['aberto']}")

    blocos += [
        "",
        f"👁️ GALE USADO COMO OBSERVAÇÃO: G{ponto}",
        "⚠️ Resultado referente somente às ocorrências históricas encontradas neste recorte; não garante comportamento futuro."
    ]

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton(
        f"💵 SIMULAR OUTRO VALOR APÓS G{ponto}",
        callback_data=f"surfe_gale_avancado_valor:{ponto}"
    ))
    markup.add(telebot.types.InlineKeyboardButton("🔄 TROCAR GALE OBSERVADO", callback_data="surfe_gale_avancado"))
    markup.add(telebot.types.InlineKeyboardButton("💰 APOSTA", callback_data="surfe_aposta_menu"))
    markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))

    m = bot.send_message(chat_id, "\n".join(blocos), reply_markup=markup)
    surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)


# ==============================================================================
# WEBHOOK DO TELEGRAM
# ==============================================================================

@app.route("/" + TELEGRAM_TOKEN, methods=["POST"])
def receber_webhook():
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as erro:
        print("========================================")
        print("ERRO NO WEBHOOK")
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))
        print("========================================")
        traceback.print_exc()
        return "ERROR", 500


@app.route("/", methods=["GET"])
def home():
    return "Bot Online!"


# ==============================================================================
# CONFIGURAR WEBHOOK
# ==============================================================================

def configurar_webhook():
    if not RENDER_EXTERNAL_URL:
        print("RENDER_EXTERNAL_URL não encontrada.")
        print("Webhook não configurado automaticamente.")
        return

    webhook_url = RENDER_EXTERNAL_URL.rstrip("/") + "/" + TELEGRAM_TOKEN

    try:
        bot.remove_webhook()
        time.sleep(1)
        sucesso = bot.set_webhook(url=webhook_url)

        print("========================================")
        print("WEBHOOK TELEGRAM")
        print("URL:", webhook_url)
        print("RESULTADO:", sucesso)
        print("========================================")
    except Exception as erro:
        print("ERRO AO CONFIGURAR WEBHOOK:")
        print(type(erro).__name__)
        print(str(erro))
        traceback.print_exc()


# ==============================================================================
# INICIALIZAÇÃO
# ==============================================================================

if __name__ == "__main__":
    print("STARTING DOUBLE BOT")
    print("====================")

    inicializar_banco()
    carregar_historico_fixo_tipminer()

    try:
        print("TESTE INICIAL POSTGRESQL:", contar_rodadas_banco(), "rodadas")
    except Exception as erro:
        print("⚠️ POSTGRESQL NÃO RESPONDEU NO TESTE INICIAL:")
        print(type(erro).__name__, str(erro))

    configurar_webhook()

    print("====================")
    print("TIPMINER TOKEN: SIM")
    print("BASE FIXA: EXATAMENTE 2.000 RODADAS MAIS RECENTES")
    print("FLASK STARTING")
    print("PORT:", PORT)

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )
