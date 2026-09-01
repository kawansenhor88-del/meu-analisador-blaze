import os
import time
import uuid
import traceback
import requests
import telebot

from flask import Flask, request


# ============================================================
# CONFIGURAÇÕES
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 10000))

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado.")

if not RENDER_EXTERNAL_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL não configurado.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)


# ============================================================
# URL DO HISTORY DO TIPMINER
# ============================================================

TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)


# ============================================================
# COR PELO NÚMERO
# ============================================================

def obter_cor(numero):

    try:
        numero = int(numero)
    except Exception:
        return "❓"

    if numero == 0:
        return "⚪"

    if 1 <= numero <= 7:
        return "🔴"

    if 8 <= numero <= 14:
        return "⚫"

    return "❓"


# ============================================================
# PEGAR NÚMERO DA RODADA
# ============================================================

def obter_numero(rodada):

    if isinstance(rodada, dict):

        campos = [
            "roll",
            "number",
            "numero",
            "result",
            "value",
            "winningNumber"
        ]

        for campo in campos:

            if campo in rodada:

                valor = rodada[campo]

                try:

                    numero = int(valor)

                    if 0 <= numero <= 14:
                        return numero

                except Exception:
                    pass

    else:

        try:

            numero = int(rodada)

            if 0 <= numero <= 14:
                return numero

        except Exception:
            pass

    return None


# ============================================================
# ENCONTRAR AS RODADAS NO JSON
# ============================================================

def encontrar_rodadas(dados):

    if isinstance(dados, list):
        return dados

    if not isinstance(dados, dict):
        return []

    campos = [
        "data",
        "history",
        "rounds",
        "items",
        "results",
        "records",
        "content",
        "rows"
    ]

    for campo in campos:

        if campo in dados:

            valor = dados[campo]

            if isinstance(valor, list):
                return valor

    for valor in dados.values():

        if isinstance(valor, (dict, list)):

            resultado = encontrar_rodadas(valor)

            if resultado:
                return resultado

    return []


# ============================================================
# ENVIAR OS REGISTROS
# ============================================================

def enviar_registros(chat_id, linhas):

    bloco = []

    for linha in linhas:

        bloco.append(linha)

        # 100 registros por mensagem
        if len(bloco) == 100:

            bot.send_message(
                chat_id,
                "\n".join(bloco)
            )

            bloco = []

    if bloco:

        bot.send_message(
            chat_id,
            "\n".join(bloco)
        )


# ============================================================
# /START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "🧪 Teste TipMiner ativo.\n\n"
        "Use /teste200"
    )


# ============================================================
# /TESTE200
# ============================================================

@bot.message_handler(commands=["teste200"])
def teste200(message):

    try:

        print("====================================")
        print("🧪 TESTE200 INICIADO")
        print("Chat:", message.chat.id)
        print("====================================")

        bot.send_message(
            message.chat.id,
            "🔎 Consultando o TipMiner..."
        )

        # ----------------------------------------------------
        # REQUISIÇÃO DIRETA AO HISTORY
        # ----------------------------------------------------

        params = {

            "limit": 5000,

            "subject": "filter",

            "isLoadMore": "true",

            "t": int(time.time() * 1000),

            "timezone": "America/Sao_Paulo",

            "_cb": str(uuid.uuid4())
        }

        headers = {

            "User-Agent": "Mozilla/5.0",

            "Accept": "application/json",

            "Cache-Control": "no-cache"
        }

        resposta = requests.get(

            TIPMINER_HISTORY_URL,

            params=params,

            headers=headers,

            timeout=30
        )

        print("STATUS TIPMINER:", resposta.status_code)

        # ----------------------------------------------------
        # VERIFICAR HTTP
        # ----------------------------------------------------

        if resposta.status_code != 200:

            bot.send_message(

                message.chat.id,

                f"❌ TipMiner respondeu HTTP "
                f"{resposta.status_code}"
            )

            return

        # ----------------------------------------------------
        # JSON
        # ----------------------------------------------------

        dados = resposta.json()

        rodadas = encontrar_rodadas(dados)

        if not rodadas:

            bot.send_message(

                message.chat.id,

                "❌ Não encontrei as rodadas "
                "na resposta do TipMiner."
            )

            print(resposta.text[:10000])

            return

        # ----------------------------------------------------
        # PEGAR 200 REGISTROS
        # ----------------------------------------------------

        rodadas = rodadas[:200]

        print(
            "✅ TipMiner retornou:",
            len(rodadas),
            "registros"
        )

        # ----------------------------------------------------
        # PREPARAR LISTA
        # ----------------------------------------------------

        linhas = []

        for posicao, rodada in enumerate(
            rodadas,
            start=1
        ):

            numero = obter_numero(rodada)

            if numero is None:

                linhas.append(
                    f"{posicao:03d}. ❓"
                )

            else:

                linhas.append(

                    f"{posicao:03d}. "
                    f"{obter_cor(numero)} "
                    f"{numero}"
                )

        # ----------------------------------------------------
        # AVISO
        # ----------------------------------------------------

        bot.send_message(

            message.chat.id,

            "✅ TipMiner retornou "
            f"{len(rodadas)} registros.\n\n"
            "📊 Enviando os registros..."
        )

        # ----------------------------------------------------
        # ENVIAR
        # ----------------------------------------------------

        enviar_registros(

            message.chat.id,

            linhas
        )

        print("====================================")
        print("✅ TESTE200 FINALIZADO")
        print(
            "TOTAL ENVIADO:",
            len(rodadas)
        )
        print("====================================")

    except Exception as erro:

        print("====================================")
        print("❌ ERRO NO TESTE200")
        print(
            type(erro).__name__,
            str(erro)
        )

        traceback.print_exc()

        print("====================================")

        try:

            bot.send_message(

                message.chat.id,

                "❌ Erro no teste:\n\n"
                f"{type(erro).__name__}: "
                f"{str(erro)[:800]}"
            )

        except Exception:
            pass


# ============================================================
# WEBHOOK DO TELEGRAM
# ============================================================

@app.route(
    "/telegram-webhook",
    methods=["POST"]
)
def telegram_webhook():

    try:

        json_string = request.get_data().decode(
            "utf-8"
        )

        update = telebot.types.Update.de_json(
            json_string
        )

        bot.process_new_updates(
            [update]
        )

        return "OK", 200

    except Exception as erro:

        print("Erro webhook:", erro)

        return "ERROR", 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return "🧪 Teste TipMiner online", 200


# ============================================================
# CONFIGURAR WEBHOOK
# ============================================================

def configurar_webhook():

    webhook_url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/telegram-webhook"
    )

    print("Configurando webhook:")
    print(webhook_url)

    resultado = bot.set_webhook(
        url=webhook_url
    )

    print(
        "Webhook configurado:",
        resultado
    )


# ============================================================
# INICIAR
# ============================================================

if __name__ == "__main__":

    print("====================================")
    print("🧪 BOT DE TESTE TIPMINER")
    print("====================================")

    print("Banco: NÃO")
    print("Gemini: NÃO")
    print("SSE: NÃO")
    print("Polling: NÃO")
    print("Webhook: SIM")

    configurar_webhook()

    app.run(
        host="0.0.0.0",
        port=PORT
    )
