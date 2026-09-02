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


def analisar_50_sequencias_de_10():
    """Analisa as 50 ocorrências mais recentes usando somente os 2.000 registros fixos."""
    dados = obter_historico_banco(limite=ANALYSIS_ROUNDS)
    if not dados:
        return "❌ Ainda não há rodadas suficientes no histórico fixo de 2.000."

    # O banco retorna mais recente -> mais antiga; a análise precisa ser cronológica.
    dados = list(reversed(dados))
    ocorrencias = _encontrar_sequencias_de_10(dados, limite=100)

    # As 50 ocorrências mais recentes.
    ocorrencias = ocorrencias[-50:]
    ocorrencias = list(reversed(ocorrencias))

    if not ocorrencias:
        return "❌ Ainda não encontrei uma sequência completa de 10 vermelhos ou 10 pretos com as 5 rodadas seguintes disponíveis."

    stats = {p: {"hits": 0, "total": 0} for p in range(11, 16)}
    blocos = []

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

    resumo = [f"📊 {len(ocorrencias)} SEQUÊNCIAS MAIS RECENTES", ""]
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

    resumo += ["", f"📈 AMOSTRA: {len(ocorrencias)} sequências"]
    return ["\n".join(resumo), "\n\n".join(blocos)]

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

    linhas = ["📊 SEQUÊNCIAS DE CORES IGUAIS", ""]

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


def painel_markup():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🔥 SEQUÊNCIA CORES IGUAIS 10X", callback_data="seq10")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📊 SEQUÊNCIA DE CORES IGUAIS", callback_data="seqcores")
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
    try:
        total = atualizar_historico_tipminer(forcar=True)
    except Exception:
        total = "indisponível"

    bot.reply_to(
        message,
        "🤖 Bot online!\n\n"
        "History do TipMiner atualizada.\n"
        f"📚 Rodadas atuais na base: {total}\n\n"
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
        total = atualizar_historico_tipminer()
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


@bot.callback_query_handler(func=lambda call: call.data in ("seq10", "seqcores", "ult50", "total", "ultima"))
def painel_callback(call):
    try:
        bot.answer_callback_query(call.id)
        # Usa a mesma base fixa de 2.000. Só consulta a API novamente
        # quando o cache de atualização expirar.
        atualizar_historico_tipminer()

        if call.data == "seqcores":
            resultado = analisar_sequencias_de_cores_iguais()
            bot.send_message(call.message.chat.id, resultado)
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

        resultado = analisar_50_sequencias_de_10()
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
