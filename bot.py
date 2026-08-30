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
# BUSCAR UMA QUANTIDADE
# ============================================================

def testar_limite(limite):

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
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
    }

    params = {
        "limit": str(limite),
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

        print(
            f"🔥 LIMIT={limite} | "
            f"HTTP={resposta.status_code} | "
            f"BYTES={len(resposta.content)}"
        )

        if resposta.status_code != 200:

            return {
                "limite": limite,
                "status": resposta.status_code,
                "quantidade": 0,
                "erro": resposta.text[:300]
            }

        try:

            dados = resposta.json()

        except Exception as erro:

            return {
                "limite": limite,
                "status": resposta.status_code,
                "quantidade": 0,
                "erro": "JSON inválido: " + str(erro)
            }

        # ====================================================
        # LOCALIZAR LISTA
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

        return {
            "limite": limite,
            "status": resposta.status_code,
            "quantidade": len(rodadas),
            "erro": ""
        }

    except Exception as erro:

        return {
            "limite": limite,
            "status": 0,
            "quantidade": 0,
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

    if "teste" not in texto:

        bot.send_message(
            message.chat.id,
            "Envie:\n\n"
            "teste"
        )

        return

    bot.send_message(
        message.chat.id,
        "🔎 TESTE INICIADO\n\n"
        "Vou consultar:\n"
        "200\n"
        "500\n"
        "1.000\n"
        "2.000\n"
        "5.000\n\n"
        "Aguarde..."
    )

    limites = [
        200,
        500,
        1000,
        2000,
        5000
    ]

    resultados = []

    for limite in limites:

        resultado = testar_limite(
            limite
        )

        resultados.append(
            resultado
        )

        time.sleep(1)

    # ========================================================
    # MONTAR RESULTADO
    # ========================================================

    mensagem = (
        "📊 RESULTADO DO TESTE\n\n"
    )

    for resultado in resultados:

        limite = resultado["limite"]
        quantidade = resultado["quantidade"]
        status = resultado["status"]

        mensagem += (
            f"Solicitado: {limite:,}\n"
            f"Recebido: {quantidade:,}\n"
            f"HTTP: {status}\n"
        )

        if resultado["erro"]:

            mensagem += (
                f"Erro: "
                f"{resultado['erro'][:150]}\n"
            )

        mensagem += "\n"

    mensagem += (
        "================================\n"
        "🔎 FIM DO TESTE"
    )

    bot.send_message(
        message.chat.id,
        mensagem
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

    return "TESTE LIMITES TIPMINER ONLINE", 200


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
