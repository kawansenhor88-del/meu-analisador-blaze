import os
import time
import uuid
import requests
import telebot
from flask import Flask, request

# ============================================================
# CONFIGURAÇÕES
# ============================================================

PORT = int(os.environ.get("PORT", "10000"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/"
    "history"
)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)


# ============================================================
# BUSCAR TIPMINER
# ============================================================

def buscar_rodadas():

    print("🔥 INICIANDO TESTE TIPMINER 5000")

    headers = {
        "Accept": "*/*",

        "Origin": "https://www.tipminer.com",

        "Referer": "https://www.tipminer.com/",

        "User-Agent": (
            "Mozilla/5.0 "
            "(Linux; Android 10; K) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/127.0.0.0 "
            "Mobile Safari/537.36"
        ),

        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",

        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
    }

    params = {
        "limit": "5000",
        "subject": "filter",
        "isLoadMore": "true",
        "t": str(int(time.time() * 1000)),
        "timezone": "America/Sao_Paulo",
        "_cb": str(uuid.uuid4()),
    }

    try:

        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=60
        )

        print("========================================")
        print("🔥 RESPOSTA TIPMINER")
        print("STATUS:", resposta.status_code)
        print(
            "CONTENT-TYPE:",
            resposta.headers.get("Content-Type")
        )
        print(
            "TAMANHO:",
            len(resposta.content)
        )
        print("URL FINAL:")
        print(resposta.url)
        print("========================================")

        # ====================================================
        # MOSTRAR RESPOSTA BRUTA
        # ====================================================

        texto_bruto = resposta.text

        print("🔥 PRIMEIROS 2000 CARACTERES:")
        print(texto_bruto[:2000])
        print("========================================")

        if resposta.status_code != 200:

            return {
                "ok": False,
                "status": resposta.status_code,
                "tamanho": len(resposta.content),
                "bruto": texto_bruto[:2000],
                "erro": "HTTP diferente de 200"
            }

        # ====================================================
        # TENTAR JSON
        # ====================================================

        try:

            dados = resposta.json()

        except Exception as erro:

            return {
                "ok": False,
                "status": resposta.status_code,
                "tamanho": len(resposta.content),
                "bruto": texto_bruto[:2000],
                "erro": (
                    "JSON inválido: "
                    + str(erro)
                )
            }

        # ====================================================
        # IDENTIFICAR LISTA
        # ====================================================

        if isinstance(dados, list):

            rodadas = dados

        elif isinstance(dados, dict):

            print(
                "🔥 CHAVES:",
                list(dados.keys())
            )

            if isinstance(
                dados.get("data"),
                list
            ):

                rodadas = dados["data"]

            elif isinstance(
                dados.get("rounds"),
                list
            ):

                rodadas = dados["rounds"]

            elif isinstance(
                dados.get("results"),
                list
            ):

                rodadas = dados["results"]

            else:

                rodadas = []

        else:

            rodadas = []

        return {
            "ok": True,
            "status": resposta.status_code,
            "tamanho": len(resposta.content),
            "quantidade": len(rodadas),
            "rodadas": rodadas,
            "bruto": texto_bruto[:1000]
        }

    except Exception as erro:

        print(
            "❌ ERRO:",
            type(erro).__name__,
            str(erro)
        )

        return {
            "ok": False,
            "status": 0,
            "tamanho": 0,
            "bruto": "",
            "erro": str(erro)
        }


# ============================================================
# TELEGRAM
# ============================================================

@bot.message_handler(
    func=lambda message: True
)
def receber_mensagem(message):

    print(
        "🔥 MENSAGEM RECEBIDA:",
        message.text
    )

    texto = (
        message.text or ""
    ).lower()

    if "5000" not in texto:

        bot.send_message(
            message.chat.id,
            "Envie:\n\n5000 rodadas"
        )

        return

    bot.send_message(
        message.chat.id,
        "🔎 Consultando o TipMiner...\n\n"
        "Aguarde."
    )

    resultado = buscar_rodadas()

    # ========================================================
    # ERRO
    # ========================================================

    if not resultado["ok"]:

        mensagem = (
            "❌ ERRO NO TIPMINER\n\n"
            f"HTTP: {resultado['status']}\n"
            f"Tamanho: {resultado['tamanho']}\n\n"
            f"{resultado['erro']}\n\n"
            "📄 RESPOSTA BRUTA:\n"
            "--------------------\n"
            f"{resultado['bruto'][:2500]}"
        )

        bot.send_message(
            message.chat.id,
            mensagem
        )

        return

    # ========================================================
    # SUCESSO
    # ========================================================

    quantidade = resultado["quantidade"]

    bot.send_message(
        message.chat.id,
        "📊 RESULTADO\n\n"
        "Solicitadas: 5.000\n"
        f"Recebidas: {quantidade}\n\n"
        f"HTTP: {resultado['status']}\n"
        f"Tamanho: {resultado['tamanho']} bytes"
    )

    # ========================================================
    # PRIMEIRA E ÚLTIMA
    # ========================================================

    rodadas = resultado["rodadas"]

    if quantidade > 0:

        primeira = rodadas[0]
        ultima = rodadas[-1]

        bot.send_message(
            message.chat.id,
            "📌 PRIMEIRA RODADA:\n\n"
            + str(primeira)
        )

        bot.send_message(
            message.chat.id,
            "📌 ÚLTIMA RODADA:\n\n"
            + str(ultima)
        )


# ============================================================
# WEBHOOK
# ============================================================

@app.route(
    "/telegram/webhook",
    methods=["POST"]
)
def receber_webhook():

    try:

        print(
            "🔥 WEBHOOK RECEBEU POST"
        )

        dados = (
            request
            .get_data()
            .decode("utf-8")
        )

        update = (
            telebot.types.Update
            .de_json(dados)
        )

        bot.process_new_updates(
            [update]
        )

        print(
            "✅ UPDATE PROCESSADO"
        )

        return "OK", 200

    except Exception as erro:

        print(
            "❌ ERRO WEBHOOK:",
            str(erro)
        )

        return "ERROR", 500


# ============================================================
# ROTAS
# ============================================================

@app.route(
    "/",
    methods=["GET", "HEAD"]
)
def inicio():

    return "TESTE TIPMINER ONLINE", 200


@app.route("/health")
def health():

    return "OK", 200


# ============================================================
# CONFIGURAR WEBHOOK
# ============================================================

def configurar_webhook():

    url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/telegram/webhook"
    )

    print(
        "========================================"
    )

    print(
        "CONFIGURANDO WEBHOOK"
    )

    print(
        "URL:",
        url
    )

    bot.remove_webhook()

    time.sleep(1)

    resultado = bot.set_webhook(
        url=url
    )

    print(
        "RESULTADO:",
        resultado
    )

    if resultado:

        print(
            "✅ WEBHOOK CONFIGURADO"
        )

    else:

        print(
            "❌ WEBHOOK NÃO CONFIGURADO"
        )


# ============================================================
# SERVIDOR
# ============================================================

if __name__ == "__main__":

    configurar_webhook()

    print(
        "========================================"
    )

    print(
        "🚀 SERVER STARTED"
    )

    print(
        "PORT:",
        PORT
    )

    print(
        "========================================"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )
