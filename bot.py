import os
import json
import traceback
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta

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
                resultados[nome] = f"❌ GALE {gale[nome]}"
                continue

            if saiu == jogaria:
                stats[nome]["acertos"] += 1
                if gale[nome] > 0:
                    stats[nome]["gale_counts"][gale[nome]] = (
                        stats[nome]["gale_counts"].get(gale[nome], 0) + 1
                    )
                gale[nome] = 0
                resultados[nome] = "✅ ACERTO"
            else:
                stats[nome]["erros"] += 1
                gale[nome] += 1
                stats[nome]["maior_gale"] = max(
                    stats[nome]["maior_gale"], gale[nome]
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
    st = stats[nome]
    total = st["acertos"] + st["erros"]
    pct = (st["acertos"] / total * 100) if total else 0.0

    partes = [
        titulo,
        f"✅ Acertos: {st['acertos']}",
        f"❌ Erros: {st['erros']}",
        f"📈 Aproveitamento: {pct:.1f}%",
        f"🔥 Maior Gale: GALE {st['maior_gale']}",
    ]
    for n in sorted(st["gale_counts"]):
        partes.append(f"📊 Gale {n}: {st['gale_counts'][n]}")
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
                    f"⚪ {indice + 1} • {hora}",
                    callback_data=f"surfe_branco:{indice}",
                )
            )
        markup.row(*botoes)

    return markup


def _montar_linhas_estrategia_surfe(registros, estrategia):
    """Monta uma estratégia por vez em colunas fixas e alinhadas."""
    titulo = "⚫ SURF — 2 PRETOS" if estrategia == "Preto" else "🔴 SURF — 2 VERMELHOS"
    linhas = [titulo, ""]

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
        cor_jogada = emoji_cor(jogaria)

        if resultado.startswith("❌ GALE"):
            gale = resultado.split()[-1]
            marcador = f"❌ G{gale}"
        else:
            marcador = "✅"

        # Mantém cada campo com largura fixa. Os números e símbolos ficam
        # sempre na mesma posição em todas as linhas.
        linha = (
            f"{numero:>2}  {cor_real} {numero_real:>2}  -  "
            f"{cor_jogada}  {marcador}"
        )
        linhas.append(linha)

        if numero % 10 == 0 and numero != len(registros):
            linhas.append("────────────────────────")

    return "\n".join(linhas)

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


def montar_resultado_surfe_50(analise):
    """Resultado das 50 rodadas após o Branco escolhido, uma estratégia por vez."""
    registros = analise["registros"]
    texto = [
        "🏄 SURF — 50 RODADAS",
        "",
        f"⚪ Branco inicial: {analise['data_branco']} às {analise['hora_branco']}",
        f"📚 Analisadas: {len(registros)}",
        "",
        _montar_linhas_estrategia_surfe(registros, "Vermelho"),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"⚪ Branco inicial: {analise['data_branco']} às {analise['hora_branco']}",
        "",
        _montar_linhas_estrategia_surfe(registros, "Preto"),
        "",
        "📊 RESULTADO — APÓS O BRANCO",
        f"⚪ {analise['data_branco']} às {analise['hora_branco']}",
        f"📚 Das {len(registros)} rodadas após o Branco",
        "",
        _resumo_surfe_estrategia(analise["stats"], "Preto", "⚫ SURFE — 2 PRETOS"),
        "",
        _resumo_surfe_estrategia(analise["stats"], "Vermelho", "🔴 SURFE — 2 VERMELHOS"),
    ]
    return "\n".join(texto)

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
            "📚 Serão analisadas as 50 rodadas após o Branco selecionado.",
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
            "normalmente até completar as 50 rodadas.",
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"🕐 Branco selecionado: {hora_branco}",
            "",
            "👇 Clique abaixo para visualizar as 50 rodadas:",
        ])

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            telebot.types.InlineKeyboardButton(
                "👁️ VER SURFE",
                callback_data="surfe_ver"
            )
        )
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🔽 OCULTAR SURF",
                callback_data="surfe_ocultar"
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


@bot.callback_query_handler(func=lambda call: call.data == "surfe_ver")
def surfe_ver_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")

        if indice is None:
            bot.send_message(chat_id, "❌ Escolha primeiro um ⚪ Branco para iniciar o SURF.")
            return

        analise = analisar_surfe_a_partir_do_branco(indice, limite=50)
        if not analise:
            bot.send_message(chat_id, "❌ Não foi possível recuperar o Branco inicial.")
            return

        resultado = montar_resultado_surfe_50(analise)

        # A primeira mensagem fica somente com as 50 rodadas do SURF.
        # A segunda mensagem, logo abaixo, traz as informações estatísticas.
        partes = resultado.split("\n📊 RESULTADO — APÓS O BRANCO\n", 1)
        mensagem_rodadas = partes[0].strip()
        mensagem_estatistica = (
            "📊 RESULTADO — APÓS O BRANCO\n" + partes[1].strip()
            if len(partes) == 2 else ""
        )

        for texto_mensagem in (mensagem_rodadas, mensagem_estatistica):
            if not texto_mensagem:
                continue
            for pos in range(0, len(texto_mensagem), 3900):
                m = bot.send_message(chat_id, texto_mensagem[pos:pos + 3900])
                surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            telebot.types.InlineKeyboardButton(
                "📊 CONTROLE GERAL",
                callback_data="surfe_controle"
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
            "👇 Depois das 50 rodadas, você pode conferir o histórico completo:",
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
            if len(brancos) > 10:
                msg = bot.send_message(
                    chat_id,
                    "⚪ DEMAIS BRANCOS — DO MAIS ANTIGO AO MAIS RECENTE",
                    reply_markup=montar_botoes_brancos_surfe(
                        brancos, 10, len(brancos)
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
