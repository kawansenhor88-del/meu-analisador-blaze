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
# BUSCAR 5.000 RODADAS
# ============================================================

def buscar_rodadas():

    print("🔥 INICIANDO BUSCA DE 5000 RODADAS")

    headers = {
        "Accept": "*/*",
        "Origin": "https://www.tipminer.com",
        "Referer": "https://www.tipminer.com/",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/127.0.0.0 Mobile Safari/537.36"
        ),
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

        print("🔥 STATUS:", resposta.status_code)
        print("🔥 TAMANHO:", len(resposta.content))
        print("🔥 CONTENT-TYPE:", resposta.headers.get("Content-Type"))

        if resposta.status_code != 200:

            return {
                "ok": False,
                "status": resposta.status_code,
                "tamanho": len(resposta.content),
                "quantidade": 0,
                "erro": resposta.text[:500]
            }

        try:

            dados = resposta.json()

        except Exception as erro:

            return {
                "ok": False,
                "status": resposta.status_code,
                "tamanho": len(resposta.content),
                "quantidade": 0,
                "erro": (
                    "Resposta não é JSON: "
                    + str(erro)
                )
            }

        # ====================================================
        # ENCONTRAR LISTA
        # ====================================================

        if isinstance(dados, list):

            rodadas = dados

        elif isinstance(dados, dict):

            if isinstance(dados.get("data"), list):

                rodadas = dados["data"]

            elif isinstance(dados.get("rounds"), list):

                rodadas = dados["rounds"]

            elif isinstance(dados.get("results"), list):

                rodadas = dados["results"]

            else:

                rodadas = []

        else:

            rodadas = []

        print("🔥 RODADAS ENCONTRADAS:", len(rodadas))

        return {
            "ok": True,
            "status": resposta.status_code,
            "tamanho": len(resposta.content),
            "quantidade": len(rodadas),
            "rodadas": rodadas
        }

    except Exception as erro:

        print("❌ ERRO:", type(erro).__name__)
        print("❌ DETALHE:", str(erro))

        return {
            "ok": False,
            "status": 0,
            "tamanho": 0,
            "quantidade": 0,
            "erro": str(erro)
        }


# ============================================================
# TELEGRAM
# ============================================================

@bot.message_handler(func=lambda message: True)
def receber_mensagem(message):

    print("🔥 MENSAGEM RECEBIDA:", message.text)

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

    print("🔥 VOU CONSULTAR TIPMINER")

    resultado = buscar_rodadas()

    print("🔥 BUSCA TERMINOU")

    if not resultado["ok"]:

        mensagem = (
            "❌ ERRO AO CONSULTAR TIPMINER\n\n"
            f"Status HTTP: {resultado['status']}\n"
            f"Tamanho: {resultado['tamanho']}\n\n"
            f"Erro:\n{resultado.get('erro', 'desconhecido')}"
        )

        bot.send_message(
            message.chat.id,
            mensagem
        )

        return

    quantidade = resultado["quantidade"]

    mensagem = (
        "✅ RESPOSTA DO TIPMINER\n\n"
        "Solicitado: 5.000\n"
        f"Recebido: {quantidade}\n\n"
        f"Status HTTP: {resultado['status']}\n"
        f"Tamanho da resposta: {resultado['tamanho']} bytes"
    )

    bot.send_message(
        message.chat.id,
        mensagem
    )

    # ========================================================
    # MOSTRAR PRIMEIRA E ÚLTIMA
    # ========================================================

    rodadas = resultado["rodadas"]

    if quantidade > 0:

        primeira = rodadas[0]
        ultima = rodadas[-1]

        bot.send_message(
            message.chat.id,
            "📌 PRIMEIRA RODADA RECEBIDA:\n\n"
            + str(primeira)
        )

        bot.send_message(
            message.chat.id,
            "📌 ÚLTIMA RODADA RECEBIDA:\n\n"
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

        print("🔥 WEBHOOK RECEBEU POST")

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

        print("✅ UPDATE PROCESSADO")

        return "OK", 200

    except Exception as erro:

        print("❌ ERRO WEBHOOK")
        print(type(erro).__name__)
        print(str(erro))

        return "ERROR", 500


# ============================================================
# ROTAS
# ============================================================

@app.route("/", methods=["GET", "HEAD"])
def inicio():

    return "TESTE 5000 ONLINE", 200


@app.route("/health")
def health():

    return "OK", 200


# ============================================================
# WEBHOOK
# ============================================================

def configurar_webhook():

    url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/telegram/webhook"
    )

    print("========================================")
    print("CONFIGURANDO WEBHOOK")
    print("URL:", url)
    print("========================================")

    bot.remove_webhook()

    time.sleep(1)

    resultado = bot.set_webhook(
        url=url
    )

    print("RESULTADO:", resultado)

    if resultado:

        print("✅ WEBHOOK CONFIGURADO")

    else:

        print("❌ WEBHOOK NÃO CONFIGURADO")


# ============================================================
# SERVIDOR
# ============================================================

if __name__ == "__main__":

    configurar_webhook()

    print("========================================")
    print("🚀 SERVER STARTED")
    print("PORT:", PORT)
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )
