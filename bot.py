import os
import time
import traceback

import telebot
from flask import Flask, request

# ============================================================
# CONFIGURAÇÃO
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado.")

if not RENDER_EXTERNAL_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL não configurado.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)


# ============================================================
# TESTE DO BOT
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "✅ BOT DE TESTE FUNCIONANDO!\n\n"
        "Telegram → Render → Flask → Bot OK."
    )


@bot.message_handler(func=lambda message: True)
def mensagem(message):
    bot.reply_to(
        message,
        f"✅ Recebi sua mensagem!\n\n"
        f"Você enviou: {message.text}"
    )


# ============================================================
# WEBHOOK
# ============================================================

@app.route("/telegram/webhook", methods=["POST"])
def receber_webhook():
    try:
        json_string = request.get_data().decode("utf-8")

        update = telebot.types.Update.de_json(json_string)

        bot.process_new_updates([update])

        print("✅ UPDATE DO TELEGRAM RECEBIDO")

        return "OK", 200

    except Exception as erro:
        print("❌ ERRO NO WEBHOOK")
        print(type(erro).__name__)
        print(str(erro))
        traceback.print_exc()

        return "ERROR", 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Bot webhook de teste online.", 200


# ============================================================
# CONFIGURAR WEBHOOK
# ============================================================

def configurar_webhook():

    webhook_url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/telegram/webhook"
    )

    print("========================================")
    print("CONFIGURANDO WEBHOOK")
    print("URL:", webhook_url)
    print("========================================")

    try:

        bot.remove_webhook()

        time.sleep(1)

        resultado = bot.set_webhook(
            url=webhook_url
        )

        print("RESULTADO:", resultado)
        print("✅ WEBHOOK CONFIGURADO")

    except Exception as erro:

        print("❌ ERRO AO CONFIGURAR WEBHOOK")
        print(type(erro).__name__)
        print(str(erro))

        traceback.print_exc()


# ============================================================
# INICIAR
# ============================================================

if __name__ == "__main__":

    configurar_webhook()

    port = int(os.getenv("PORT", "10000"))

    print("========================================")
    print("SERVER STARTED")
    print("PORT:", port)
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
