
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

# ============================================================
# AJUSTES DO LABORATÓRIO
# ============================================================
#
# A ideia agora é automática:
# 1) cada linha calcula a largura visual antes do ❌/✅
# 2) completa só o que falta até o ALVO_RESULTADO
# 3) depois calcula a largura visual da coluna esquerda inteira
# 4) completa só o que falta até o ALVO_COLUNA_DIREITA
#
# Você só mexe nesses dois alvos por camada.
# Os pesos visuais ficam centralizados mais abaixo.
#
AJUSTES = {
    2: {
        "ALVO_RESULTADO": 13.0,
        "ALVO_COLUNA_DIREITA": 24.0,
    },
    3: {
        "ALVO_RESULTADO": 14.0,
        "ALVO_COLUNA_DIREITA": 25.0,
    },
    4: {
        "ALVO_RESULTADO": 11.0,
        "ALVO_COLUNA_DIREITA": 17.0,
    },
}

# ============================================================
# SISTEMA DE ESPAÇOS
# ============================================================

ESPACO_GRANDE = "\u3164"  # HANGUL FILLER
ESPACO_FINO = "\u200A"    # HAIR SPACE

def criar_espaco(valor):
    if valor <= 0:
        return ""

    grandes = int(valor)
    resto = round(valor - grandes, 1)

    resultado = ESPACO_GRANDE * grandes

    if resto > 0:
        quantidade_finos = max(1, round(resto / 0.2))
        resultado += ESPACO_FINO * quantidade_finos

    return resultado

# ============================================================
# PESOS VISUAIS
# ============================================================
#
# Não são "pixels reais". São unidades relativas para o cálculo.
# Se o Telegram mostrar alguma pequena diferença, ajustamos só
# estes pesos ou os dois alvos da camada.
#
PESO_PADRAO = 1.0

PESOS = {
    "0": 1.0, "1": 0.8, "2": 1.0, "3": 1.0, "4": 1.0,
    "5": 1.0, "6": 1.0, "7": 1.0, "8": 1.0, "9": 1.0,
    "-": 0.6,
    " ": 0.6,

    "🔴": 1.8,
    "⚫": 1.8,
    "⚪": 1.8,
    "❌": 1.8,
    "✅": 1.8,

    "G": 1.0,
    "A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0, "E": 1.0,
    "F": 1.0, "H": 1.0, "I": 0.6, "J": 0.8, "K": 1.0,
    "L": 0.8, "M": 1.2, "N": 1.0, "O": 1.0, "P": 1.0,
    "Q": 1.0, "R": 1.0, "S": 1.0, "T": 0.9, "U": 1.0,
    "V": 1.0, "W": 1.2, "X": 1.0, "Y": 1.0, "Z": 1.0,
}

def largura_visual(texto):
    total = 0.0
    for char in texto:
        total += PESOS.get(char, PESO_PADRAO)
    return round(total, 2)

# ============================================================
# MONTAGEM AUTOMÁTICA DAS LINHAS
# ============================================================

def compensar_ate_alvo(texto, alvo):
    largura = largura_visual(texto)
    falta = alvo - largura
    return criar_espaco(falta)

def montar_coluna(numero, saiu, jogaria, resultado, alvo_resultado):
    prefixo = f"{numero}  {saiu}-{jogaria}"

    # Alinha o começo do ❌/✅.
    antes_resultado = compensar_ate_alvo(prefixo, alvo_resultado)

    return prefixo + antes_resultado + resultado

def montar_linha(dados, digitos):
    cfg = AJUSTES[digitos]

    (
        numero,
        saiu_esq,
        joga_esq,
        res_esq,
        saiu_dir,
        joga_dir,
        res_dir,
    ) = dados

    esquerda = montar_coluna(
        numero,
        saiu_esq,
        joga_esq,
        res_esq,
        cfg["ALVO_RESULTADO"],
    )

    # Mede a coluna esquerda já pronta e compensa automaticamente
    # até o ponto fixo onde deve começar a coluna direita.
    entre_colunas = compensar_ate_alvo(
        esquerda,
        cfg["ALVO_COLUNA_DIREITA"],
    )

    direita = montar_coluna(
        numero,
        saiu_dir,
        joga_dir,
        res_dir,
        cfg["ALVO_RESULTADO"],
    )

    return esquerda + entre_colunas + direita

# ============================================================
# EXEMPLOS
# ============================================================

EXEMPLOS_2 = [
    (10, "🔴7",  "⚫", "❌G1", "🔴7",  "🔴", "✅"),
    (11, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
    (25, "⚪0",  "⚫", "❌G3", "⚪0",  "🔴", "❌G1"),
    (57, "🔴3",  "⚫", "✅",   "🔴3",  "🔴", "❌G2"),
    (99, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
]

EXEMPLOS_3 = [
    (100, "🔴7",  "⚫", "❌G1", "🔴7",  "🔴", "✅"),
    (101, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
    (250, "⚪0",  "⚫", "❌G3", "⚪0",  "🔴", "❌G1"),
    (570, "🔴3",  "⚫", "✅",   "🔴3",  "🔴", "❌G2"),
    (999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
]

EXEMPLOS_4 = [
    (1000, "🔴7",  "⚫", "❌G1", "🔴7",  "🔴", "✅"),
    (1001, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
    (1250, "⚪0",  "⚫", "❌G3", "⚪0",  "🔴", "❌G1"),
    (1570, "🔴3",  "⚫", "✅",   "🔴3",  "🔴", "❌G2"),
    (1999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
]

def montar_bloco(digitos):
    exemplos = {
        2: EXEMPLOS_2,
        3: EXEMPLOS_3,
        4: EXEMPLOS_4,
    }[digitos]

    cfg = AJUSTES[digitos]

    linhas = [
        f"🧪 TESTE AUTOMÁTICO — {digitos} DÍGITOS",
        "",
        f"🎯 Alvo resultado: {cfg['ALVO_RESULTADO']}",
        f"🎯 Alvo coluna direita: {cfg['ALVO_COLUNA_DIREITA']}",
        "",
        "SURF 🔴                     SURF ⚫",
        "",
    ]

    for item in exemplos:
        linhas.append(montar_linha(item, digitos))

    return "\n".join(linhas)

def painel_teste():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(
        telebot.types.InlineKeyboardButton(
            "2️⃣ 2 DÍGITOS",
            callback_data="teste_auto:2",
        )
    )
    markup.row(
        telebot.types.InlineKeyboardButton(
            "3️⃣ 3 DÍGITOS",
            callback_data="teste_auto:3",
        )
    )
    markup.row(
        telebot.types.InlineKeyboardButton(
            "4️⃣ 4 DÍGITOS",
            callback_data="teste_auto:4",
        )
    )
    markup.row(
        telebot.types.InlineKeyboardButton(
            "📋 VER OS 3 TESTES",
            callback_data="teste_auto:todos",
        )
    )
    return markup

# ============================================================
# TELEGRAM
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "🧪 LABORATÓRIO — ALINHAMENTO AUTOMÁTICO\n\n"
        "Agora cada linha calcula sozinha quanto espaço precisa.\n\n"
        "Escolha uma camada:",
        reply_markup=painel_teste(),
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("teste_auto:"))
def callback_teste(call):
    bot.answer_callback_query(call.id)

    tipo = call.data.split(":", 1)[1]

    if tipo == "todos":
        bot.send_message(call.message.chat.id, montar_bloco(2))
        bot.send_message(call.message.chat.id, montar_bloco(3))
        bot.send_message(call.message.chat.id, montar_bloco(4))
        return

    digitos = int(tipo)
    bot.send_message(call.message.chat.id, montar_bloco(digitos))

# ============================================================
# FLASK / WEBHOOK
# ============================================================

@app.route("/", methods=["GET"])
def index():
    return "Bot laboratório automático online.", 200

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(
            request.get_data().decode("utf-8")
        )
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
    print("LABORATÓRIO AUTOMÁTICO INICIADO")
    app.run(host="0.0.0.0", port=PORT)
