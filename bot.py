import os
import json
import time
import threading
from collections import deque

import requests
import telebot
from flask import Flask


# ============================================================
# CONFIGURAÇÕES
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TIPMINER_AUTH_TOKEN = os.getenv("TIPMINER_AUTH_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN not configured.")

if not TIPMINER_AUTH_TOKEN:
    raise RuntimeError("TIPMINER_AUTH_TOKEN not configured.")


TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

TIPMINER_LIVE_URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/live"
)

MAX_HISTORY = 100000

historico = deque(maxlen=MAX_HISTORY)
historico_lock = threading.Lock()


# ============================================================
# TELEGRAM
# ============================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)


# ============================================================
# CORES
# ============================================================

def converter_cor(numero):
    try:
        numero = int(numero)
    except Exception:
        return "Desconhecido"

    if numero == 0:
        return "Branco"

    if 1 <= numero <= 7:
        return "Vermelho"

    if 8 <= numero <= 14:
        return "Preto"

    return "Desconhecido"


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def normalizar_rodada(item):
    if not isinstance(item, dict):
        return None

    uuid = (
        item.get("uuid")
        or item.get("id")
        or item.get("rodada_id")
    )

    resultado = (
        item.get("result")
        if item.get("result") is not None
        else item.get("resultado")
    )

    instant = (
        item.get("instant")
        or item.get("timestamp")
        or item.get("time")
    )

    tipo = item.get("type", "DOUBLE")

    if uuid is None or resultado is None:
        return None

    try:
        resultado = int(resultado)
    except Exception:
        return None

    return {
        "uuid": str(uuid),
        "type": str(tipo),
        "result": resultado,
        "color": converter_cor(resultado),
        "instant": instant
    }


# ============================================================
# EXTRAIR RODADAS
# ============================================================

def extrair_rodadas(data):
    """
    Aceita diferentes formatos de resposta JSON.

    O objetivo é NÃO limitar a resposta a 200.
    """

    resultados = []

    if isinstance(data, list):
        resultados = data

    elif isinstance(data, dict):

        # Formatos comuns
        possiveis = [
            data.get("history"),
            data.get("rounds"),
            data.get("data"),
            data.get("results"),
            data.get("items"),
        ]

        for valor in possiveis:
            if isinstance(valor, list):
                resultados = valor
                break

        # Caso a própria resposta seja um objeto contendo
        # listas dentro de outras propriedades.
        if not resultados:
            for valor in data.values():
                if isinstance(valor, list):
                    candidatos = [
                        x for x in valor
                        if isinstance(x, dict)
                        and (
                            "uuid" in x
                            or "result" in x
                            or "instant" in x
                        )
                    ]

                    if candidatos:
                        resultados = candidatos
                        break

    rodadas = []

    for item in resultados:
        rodada = normalizar_rodada(item)

        if rodada:
            rodadas.append(rodada)

    return rodadas


# ============================================================
# BUSCAR 400 RODADAS
# ============================================================

def buscar_historico_400():
    print("\n========================================")
    print("📥 BUSCANDO HISTÓRICO DO TIPMINER")
    print("========================================")

    params = {
        "limit": 400,
        "subject": "filter",
        "isLoadMore": "true",
        "t": int(time.time() * 1000),
        "timezone": "America/Sao_Paulo",
        "_cb": "bot"
    }

    headers = {
        "accept": "*/*",
        "accept-language": "pt-BR",
        "authorization": f"Bearer {TIPMINER_AUTH_TOKEN}",
        "content-type": "application/json",
        "origin": "https://www.tipminer.com",
        "referer": "https://www.tipminer.com/",
        "user-agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Mobile Safari/537.36"
        )
    }

    try:

        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=30
        )

        print("🌐 HTTP:", resposta.status_code)

        resposta.raise_for_status()

        data = resposta.json()

        rodadas = extrair_rodadas(data)

        print("📊 RODADAS EXTRAÍDAS:", len(rodadas))

        if rodadas:
            print(
                "🔵 PRIMEIRA:",
                rodadas[0]["uuid"],
                rodadas[0]["result"],
                rodadas[0]["color"]
            )

            print(
                "🔵 ÚLTIMA:",
                rodadas[-1]["uuid"],
                rodadas[-1]["result"],
                rodadas[-1]["color"]
            )

        return rodadas

    except Exception as erro:

        print("❌ ERRO AO BUSCAR HISTÓRICO:")
        print(erro)

        return []


# ============================================================
# SALVAR NO HISTÓRICO EM MEMÓRIA
# ============================================================

def adicionar_rodadas(rodadas):

    adicionadas = 0

    with historico_lock:

        existentes = {
            item["uuid"]
            for item in historico
            if item.get("uuid")
        }

        for rodada in rodadas:

            uuid = rodada["uuid"]

            if uuid in existentes:
                continue

            historico.append(rodada)
            existentes.add(uuid)
            adicionadas += 1

    return adicionadas


# ============================================================
# INICIALIZAÇÃO DO HISTÓRICO
# ============================================================

def carregar_historico():

    print("\n========================================")
    print("🚀 INICIANDO CARREGAMENTO")
    print("========================================")

    rodadas = buscar_historico_400()

    if not rodadas:
        print("❌ Nenhuma rodada recebida.")
        return

    adicionadas = adicionar_rodadas(rodadas)

    print("\n========================================")
    print("📊 RESULTADO")
    print("========================================")
    print("Solicitadas: 400")
    print("Recebidas:", len(rodadas))
    print("Adicionadas:", adicionadas)
    print("Histórico atual:", len(historico))
    print("========================================\n")


# ============================================================
# CAPTURA LIVE
# ============================================================

def processar_live(data):

    rodada = normalizar_rodada(data)

    if not rodada:
        return

    adicionadas = adicionar_rodadas([rodada])

    if adicionadas:
        print(
            "🎯 NOVA RODADA:",
            rodada["result"],
            "|",
            rodada["color"],
            "|",
            rodada["instant"]
        )


def capturar_live():

    while True:

        try:

            print("🟢 Conectando ao LIVE do TipMiner...")

            headers = {
                "accept": "text/event-stream",
                "authorization": f"Bearer {TIPMINER_AUTH_TOKEN}",
                "origin": "https://www.tipminer.com",
                "referer": "https://www.tipminer.com/",
                "user-agent": (
                    "Mozilla/5.0 (Linux; Android 10; K) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Mobile Safari/537.36"
                )
            }

            resposta = requests.get(
                TIPMINER_LIVE_URL,
                headers=headers,
                stream=True,
                timeout=60
            )

            print(
                "🟢 LIVE conectado. HTTP:",
                resposta.status_code
            )

            for linha in resposta.iter_lines(
                decode_unicode=True
            ):

                if not linha:
                    continue

                texto = linha.strip()

                if texto.startswith("data:"):

                    conteudo = texto[5:].strip()

                    try:

                        data = json.loads(conteudo)

                        if isinstance(data, dict):

                            processar_live(data)

                        elif isinstance(data, list):

                            for item in data:
                                processar_live(item)

                    except Exception:
                        pass

        except Exception as erro:

            print("⚠️ LIVE desconectado:", erro)
            print("🔄 Reconectando em 5 segundos...")
            time.sleep(5)


# ============================================================
# TELEGRAM
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    with historico_lock:
        total = len(historico)

    bot.reply_to(
        message,
        f"🤖 TipMiner online!\n\n"
        f"📊 Rodadas carregadas: {total}\n"
        f"🔴 Vermelho: 1–7\n"
        f"⚫ Preto: 8–14\n"
        f"⚪ Branco: 0"
    )


@bot.message_handler(commands=["historico"])
def comando_historico(message):

    with historico_lock:
        dados = list(historico)

    if not dados:
        bot.reply_to(
            message,
            "❌ Nenhuma rodada carregada."
        )
        return

    ultimas = dados[-20:]

    texto = "📊 ÚLTIMAS 20 RODADAS\n\n"

    for rodada in reversed(ultimas):

        texto += (
            f"🎲 {rodada['result']} "
            f"→ {rodada['color']}\n"
            f"🕐 {rodada['instant']}\n\n"
        )

    bot.reply_to(message, texto)


@bot.message_handler(commands=["total"])
def comando_total(message):

    with historico_lock:
        total = len(historico)

    bot.reply_to(
        message,
        f"📊 TOTAL NO HISTÓRICO\n\n"
        f"🎲 {total} rodadas"
    )


# ============================================================
# FLASK
# ============================================================

@app.route("/")
def home():

    with historico_lock:
        total = len(historico)

    return {
        "status": "online",
        "historico": total
    }


@app.route("/health")
def health():

    return {
        "status": "ok"
    }


# ============================================================
# INICIAR
# ============================================================

def iniciar():

    carregar_historico()

    thread_live = threading.Thread(
        target=capturar_live,
        daemon=True
    )

    thread_live.start()

    print("🤖 Telegram iniciado.")

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )


if __name__ == "__main__":

    thread_bot = threading.Thread(
        target=iniciar,
        daemon=True
    )

    thread_bot.start()

    port = int(os.getenv("PORT", "10000"))

    print(
        f"🌐 Flask iniciado na porta {port}"
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
