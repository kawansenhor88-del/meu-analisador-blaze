import os
import time
import telebot
from flask import Flask, request

# ============================================================
# CONFIGURAÇÕES
# ============================================================

PORT = int(os.environ.get("PORT", "10000"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)


# ============================================================
# TESTE DO TELEGRAM
# ============================================================

@bot.message_handler(func=lambda message: True)
def receber_mensagem(message):

    print("🔥🔥 MENSAGEM RECEBIDA DO TELEGRAM")
    print("Texto:", message.text)

    bot.send_message(
        message.chat.id,
        "✅ TESTE FUNCIONOU!\n\n"
        "Telegram → Webhook → Render → Bot\n"
        "está funcionando corretamente."
    )

    print("✅ RESPOSTA ENVIADA AO TELEGRAM")


# ============================================================
# WEBHOOK
# ============================================================

@app.route("/telegram/webhook", methods=["POST"])
def receber_webhook():

    try:

        print("🔥 WEBHOOK RECEBEU POST")

        dados = request.get_data().decode("utf-8")

        print("🔥 DADOS RECEBIDOS DO TELEGRAM")

        update = telebot.types.Update.de_json(dados)

        bot.process_new_updates([update])

        print("✅ UPDATE PROCESSADO")

        return "OK", 200

    except Exception as erro:

        print("❌ ERRO NO WEBHOOK")
        print(type(erro).__name__)
        print(str(erro))

        return "ERROR", 500


# ============================================================
# ROTA PRINCIPAL
# ============================================================

@app.route("/", methods=["GET", "HEAD"])
def inicio():

    return "BOT DE TESTE ONLINE", 200


# ============================================================
# HEALTH
# ============================================================

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

    print("========================================")
    print("CONFIGURANDO WEBHOOK")
    print("URL:", url)
    print("========================================")

    bot.remove_webhook()

    time.sleep(1)

    resultado = bot.set_webhook(url=url)

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
