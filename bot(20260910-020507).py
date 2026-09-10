
import os
import telebot
from flask import Flask, request

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "10000"))

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado no Render.")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
app = Flask(__name__)

FIGURE_SPACE = "\u2007"

def montar_linha(numero, saiu_esq, joga_esq, res_esq,
                 saiu_dir, joga_dir, res_dir, digitos):
    numero_txt = str(numero)
    indice = (FIGURE_SPACE * max(0, digitos - len(numero_txt))) + numero_txt

    esquerda = f"{indice}  {saiu_esq}-{joga_esq}{res_esq}"
    separador = FIGURE_SPACE * 4
    direita = f"{indice}  {saiu_dir}-{joga_dir}{res_dir}"

    return esquerda + separador + direita

def bloco_2_digitos():
    return "\n".join([
        "🧪 TESTE — 2 DÍGITOS",
        "",
        "SURF 🔴                     SURF ⚫",
        "",
        montar_linha(10, "🔴7", "⚫", "❌G1", "🔴7", "🔴", "✅", 2),
        montar_linha(11, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅", 2),
        montar_linha(25, "⚪0", "⚫", "❌G3", "⚪0", "🔴", "❌G1", 2),
        montar_linha(57, "🔴3", "⚫", "✅", "🔴3", "🔴", "❌G2", 2),
        montar_linha(99, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅", 2),
    ])

def bloco_3_digitos():
    return "\n".join([
        "🧪 TESTE — 3 DÍGITOS",
        "",
        "SURF 🔴                     SURF ⚫",
        "",
        montar_linha(100, "🔴7", "⚫", "❌G1", "🔴7", "🔴", "✅", 3),
        montar_linha(101, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅", 3),
        montar_linha(250, "⚪0", "⚫", "❌G3", "⚪0", "🔴", "❌G1", 3),
        montar_linha(570, "🔴3", "⚫", "✅", "🔴3", "🔴", "❌G2", 3),
        montar_linha(999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅", 3),
    ])

def bloco_4_digitos():
    return "\n".join([
        "🧪 TESTE — 4 DÍGITOS",
        "",
        "SURF 🔴                     SURF ⚫",
        "",
        montar_linha(1000, "🔴7", "⚫", "❌G1", "🔴7", "🔴", "✅", 4),
        montar_linha(1001, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅", 4),
        montar_linha(1250, "⚪0", "⚫", "❌G3", "⚪0", "🔴", "❌G1", 4),
        montar_linha(1570, "🔴3", "⚫", "✅", "🔴3", "🔴", "❌G2", 4),
        montar_linha(1999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅", 4),
    ])

def painel_teste():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton("2️⃣ 2 DÍGITOS", callback_data="teste:2"))
    markup.row(telebot.types.InlineKeyboardButton("3️⃣ 3 DÍGITOS", callback_data="teste:3"))
    markup.row(telebot.types.InlineKeyboardButton("4️⃣ 4 DÍGITOS", callback_data="teste:4"))
    markup.row(telebot.types.InlineKeyboardButton("📋 VER OS 3 TESTES", callback_data="teste:todos"))
    return markup

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "🧪 LABORATÓRIO DE ALINHAMENTO — SURF\n\n"
        "Cada quantidade de dígitos será testada em uma camada separada.\n\n"
        "Escolha um teste:",
        reply_markup=painel_teste(),
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("teste:"))
def callback_teste(call):
    bot.answer_callback_query(call.id)
    tipo = call.data.split(":", 1)[1]

    if tipo == "2":
        bot.send_message(call.message.chat.id, bloco_2_digitos())
    elif tipo == "3":
        bot.send_message(call.message.chat.id, bloco_3_digitos())
    elif tipo == "4":
        bot.send_message(call.message.chat.id, bloco_4_digitos())
    elif tipo == "todos":
        bot.send_message(call.message.chat.id, bloco_2_digitos())
        bot.send_message(call.message.chat.id, bloco_3_digitos())
        bot.send_message(call.message.chat.id, bloco_4_digitos())

@app.route("/", methods=["GET"])
def index():
    return "Bot de teste de alinhamento online.", 200

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
        bot.process_new_updates([update])
    return "", 200

def configurar_webhook():
    if not RENDER_EXTERNAL_URL:
        print("AVISO: RENDER_EXTERNAL_URL não configurado.")
        return

    webhook_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/{TELEGRAM_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    print("Webhook configurado.")

if __name__ == "__main__":
    configurar_webhook()
    print("BOT DE TESTE DE ALINHAMENTO INICIADO")
    app.run(host="0.0.0.0", port=PORT)
