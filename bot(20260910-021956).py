import os
import unicodedata
import telebot
from flask import Flask, request

# ============================================================
# CONFIGURAÇÃO DO RENDER / TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "10000"))

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado no Render.")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
app = Flask(__name__)


# ============================================================
# PAINEL DE AJUSTE MANUAL
# ============================================================
# VOCÊ SÓ PRECISA MEXER NESTA PARTE.
#
# ALVO_COLUNA = posição onde queremos que a coluna da direita comece.
# Aumentar o valor -> coluna da direita vai para a DIREITA.
# Diminuir o valor -> coluna da direita vai para a ESQUERDA.
#
# AJUSTE_G / AJUSTE_CHECK = compensações extras conforme o final da
# primeira coluna. Use valores positivos para abrir mais espaço e
# negativos para fechar.
#
# Cada camada é independente. Assim você pode ajustar 2, 3 e 4 dígitos
# sem estragar as outras.

AJUSTES = {
    2: {
        "ALVO_COLUNA": 19.0,
        "AJUSTE_G": 0.0,
        "AJUSTE_CHECK": 0.0,
    },
    3: {
        "ALVO_COLUNA": 20.0,
        "AJUSTE_G": 0.0,
        "AJUSTE_CHECK": 0.0,
    },
    4: {
        "ALVO_COLUNA": 21.0,
        "AJUSTE_G": 0.0,
        "AJUSTE_CHECK": 0.0,
    },
}

# Tamanho dos passos de espaço usados pelo laboratório.
# Normalmente não precisa mexer aqui.
FIGURE_SPACE = "\u2007"   # espaço maior
HAIR_SPACE = "\u200A"     # espaço fino
PASSOS_FINOS_POR_UNIDADE = 5


# ============================================================
# CÁLCULO DE LARGURA VISUAL
# ============================================================
def largura_visual(texto):
    """Estimativa da largura visual usada apenas no laboratório."""
    largura = 0.0

    for caractere in texto:
        if caractere == "\ufe0f" or unicodedata.combining(caractere):
            continue

        # Emojis / caracteres largos.
        if unicodedata.east_asian_width(caractere) in ("W", "F"):
            largura += 2.0
        else:
            largura += 1.0

    return largura


def criar_espaco(unidades):
    """Transforma um valor decimal em espaços grandes + ajuste fino."""
    unidades = max(0.0, float(unidades))

    inteiros = int(unidades)
    decimal = unidades - inteiros
    finos = int(round(decimal * PASSOS_FINOS_POR_UNIDADE))

    return (FIGURE_SPACE * inteiros) + (HAIR_SPACE * finos)


def compensacao_resultado(resultado, digitos):
    cfg = AJUSTES[digitos]

    if resultado == "✅":
        return cfg["AJUSTE_CHECK"]

    if resultado.startswith("❌G"):
        return cfg["AJUSTE_G"]

    return 0.0


def montar_linha_calculada(
    numero,
    saiu_esq,
    joga_esq,
    res_esq,
    saiu_dir,
    joga_dir,
    res_dir,
    digitos,
):
    indice = str(numero)
    esquerda = f"{indice}  {saiu_esq}-{joga_esq}{res_esq}"

    alvo = AJUSTES[digitos]["ALVO_COLUNA"]
    largura_esquerda = largura_visual(esquerda)

    faltam = alvo - largura_esquerda
    faltam += compensacao_resultado(res_esq, digitos)
    faltam = max(1.0, faltam)

    separador = criar_espaco(faltam)
    direita = f"{indice}  {saiu_dir}-{joga_dir}{res_dir}"

    return esquerda + separador + direita


# ============================================================
# EXEMPLOS DE CADA CAMADA
# ============================================================
EXEMPLOS_2 = [
    (10, "🔴7", "⚫", "❌G1", "🔴7", "🔴", "✅"),
    (11, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
    (25, "⚪0", "⚫", "❌G3", "⚪0", "🔴", "❌G1"),
    (57, "🔴3", "⚫", "✅", "🔴3", "🔴", "❌G2"),
    (99, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
]

EXEMPLOS_3 = [
    (100, "🔴7", "⚫", "❌G1", "🔴7", "🔴", "✅"),
    (101, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
    (250, "⚪0", "⚫", "❌G3", "⚪0", "🔴", "❌G1"),
    (570, "🔴3", "⚫", "✅", "🔴3", "🔴", "❌G2"),
    (999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
]

EXEMPLOS_4 = [
    (1000, "🔴7", "⚫", "❌G1", "🔴7", "🔴", "✅"),
    (1001, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
    (1250, "⚪0", "⚫", "❌G3", "⚪0", "🔴", "❌G1"),
    (1570, "🔴3", "⚫", "✅", "🔴3", "🔴", "❌G2"),
    (1999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
]


def montar_bloco(digitos, exemplos):
    cfg = AJUSTES[digitos]

    linhas = [
        f"🧪 TESTE — {digitos} DÍGITOS",
        "",
        f"⚙️ ALVO: {cfg['ALVO_COLUNA']}",
        f"⚙️ G: {cfg['AJUSTE_G']} | ✅: {cfg['AJUSTE_CHECK']}",
        "",
        "SURF 🔴                     SURF ⚫",
        "",
    ]

    for dados in exemplos:
        linhas.append(montar_linha_calculada(*dados, digitos))

    return "\n".join(linhas)


def bloco_2_digitos():
    return montar_bloco(2, EXEMPLOS_2)


def bloco_3_digitos():
    return montar_bloco(3, EXEMPLOS_3)


def bloco_4_digitos():
    return montar_bloco(4, EXEMPLOS_4)


# ============================================================
# TELEGRAM
# ============================================================
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
        "Agora os ajustes ficam no começo do código.\n"
        "Você mesmo pode alterar ALVO, G e ✅ de cada camada.\n\n"
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


# ============================================================
# FLASK / RENDER WEBHOOK
# ============================================================
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
