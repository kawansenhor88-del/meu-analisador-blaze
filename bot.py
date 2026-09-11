import os
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
# AMANHÃ VOCÊ SÓ PRECISA MEXER NESTE BLOCO.
#
# Cada camada é INDEPENDENTE:
#   2 = números de 10 a 99
#   3 = números de 100 a 999
#   4 = números de 1000 a 9999
#
# COMO FUNCIONA:
#   ANTES_SETA_ESQUERDA  -> espaço antes do "-" da coluna SURF 🔴
#   ANTES_SETA_DIREITA   -> espaço antes do "-" da coluna SURF ⚫
#
#   APOS_G_ESQUERDA      -> espaço depois de ❌Gx na coluna esquerda
#   APOS_CHECK_ESQUERDA  -> espaço depois de ✅ na coluna esquerda
#
#   APOS_G_DIREITA       -> espaço depois de ❌Gx na coluna direita
#   APOS_CHECK_DIREITA   -> espaço depois de ✅ na coluna direita
#
#   ENTRE_COLUNAS         -> distância geral entre a coluna esquerda
#                            e a coluna direita
#
# Pode usar decimal: 0.2, 0.4, 1.0, 2.0, 3.4 etc.
# Valor maior = adiciona espaço.
# Valor menor = tira espaço (mínimo prático: 0.0).
#
# IMPORTANTE: mexer em uma camada NÃO altera as outras.

AJUSTES = {
    2: {
        "ANTES_SETA_ESQUERDA": 0.0,
        "ANTES_SETA_DIREITA": 0.0,
        "APOS_G_ESQUERDA": 0.0,
        "APOS_CHECK_ESQUERDA": 0.0,
        "APOS_G_DIREITA": 0.0,
        "APOS_CHECK_DIREITA": 0.0,
        "ENTRE_COLUNAS": 2.0,
    },
    3: {
        "ANTES_SETA_ESQUERDA": 0.0,
        "ANTES_SETA_DIREITA": 0.0,
        "APOS_G_ESQUERDA": 0.0,
        "APOS_CHECK_ESQUERDA": 0.0,
        "APOS_G_DIREITA": 0.0,
        "APOS_CHECK_DIREITA": 0.0,
        "ENTRE_COLUNAS": 2.0,
    },
    4: {
        "ANTES_SETA_ESQUERDA": -0.5,
        "ANTES_SETA_DIREITA": 0.4,
        "APOS_G_ESQUERDA": 0.0,
        "APOS_CHECK_ESQUERDA": 0.0,
        "APOS_G_DIREITA": 0.0,
        "APOS_CHECK_DIREITA": 0.0,
        "ENTRE_COLUNAS": 0.0,
    },
}


# ============================================================
# SISTEMA DE ESPAÇOS
# ============================================================
# ㅤ = espaço grande usado no SURF
# Hair Space = ajuste fino para valores decimais
ESPACO_GRANDE = "\u3164"
ESPACO_FINO = "\u200A"
PASSOS_FINOS_POR_UNIDADE = 5


def criar_espaco(valor):
    """Converte 0.2, 0.4, 1.0, 2.0... em espaços invisíveis."""
    valor = max(0.0, float(valor))

    inteiros = int(valor)
    decimal = valor - inteiros
    finos = int(round(decimal * PASSOS_FINOS_POR_UNIDADE))

    return (ESPACO_GRANDE * inteiros) + (ESPACO_FINO * finos)


def espaco_apos_resultado(resultado, cfg, lado):
    if resultado == "✅":
        return criar_espaco(cfg[f"APOS_CHECK_{lado}"])

    if resultado.startswith("❌G"):
        return criar_espaco(cfg[f"APOS_G_{lado}"])

    return ""


def montar_coluna(numero, saiu, jogaria, resultado, cfg, lado):
    antes_seta = criar_espaco(cfg[f"ANTES_SETA_{lado}"])
    apos_resultado = espaco_apos_resultado(resultado, cfg, lado)

    return (
        f"{numero}  "
        f"{saiu}"
        f"{antes_seta}"
        f"-{jogaria}{resultado}"
        f"{apos_resultado}"
    )


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
        numero, saiu_esq, joga_esq, res_esq, cfg, "ESQUERDA"
    )

    direita = montar_coluna(
        numero, saiu_dir, joga_dir, res_dir, cfg, "DIREITA"
    )

    entre = criar_espaco(cfg["ENTRE_COLUNAS"])

    return esquerda + entre + direita


# ============================================================
# EXEMPLOS — CADA CAMADA É SEPARADA
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

EXEMPLOS = {
    2: EXEMPLOS_2,
    3: EXEMPLOS_3,
    4: EXEMPLOS_4,
}


def montar_resumo_ajustes(digitos):
    cfg = AJUSTES[digitos]

    return (
        f"⚙️ ESQ seta: {cfg['ANTES_SETA_ESQUERDA']} | "
        f"G: {cfg['APOS_G_ESQUERDA']} | ✅: {cfg['APOS_CHECK_ESQUERDA']}\n"
        f"⚙️ DIR seta: {cfg['ANTES_SETA_DIREITA']} | "
        f"G: {cfg['APOS_G_DIREITA']} | ✅: {cfg['APOS_CHECK_DIREITA']}\n"
        f"↔️ Entre colunas: {cfg['ENTRE_COLUNAS']}"
    )


def montar_bloco(digitos):
    linhas = [
        f"🧪 TESTE — {digitos} DÍGITOS",
        "",
        montar_resumo_ajustes(digitos),
        "",
        "SURF 🔴                     SURF ⚫",
        "",
    ]

    for dados in EXEMPLOS[digitos]:
        linhas.append(montar_linha(dados, digitos))

    return "\n".join(linhas)


# ============================================================
# TELEGRAM
# ============================================================
def painel_teste():
    markup = telebot.types.InlineKeyboardMarkup()

    markup.row(
        telebot.types.InlineKeyboardButton(
            "2️⃣ 2 DÍGITOS", callback_data="teste:2"
        )
    )
    markup.row(
        telebot.types.InlineKeyboardButton(
            "3️⃣ 3 DÍGITOS", callback_data="teste:3"
        )
    )
    markup.row(
        telebot.types.InlineKeyboardButton(
            "4️⃣ 4 DÍGITOS", callback_data="teste:4"
        )
    )
    markup.row(
        telebot.types.InlineKeyboardButton(
            "📋 VER OS 3 TESTES", callback_data="teste:todos"
        )
    )

    return markup


@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "🧪 LABORATÓRIO DE ALINHAMENTO — SURF\n\n"
        "Todos os controles ficam no começo do bot.py.\n"
        "2, 3 e 4 dígitos são totalmente independentes.\n\n"
        "Escolha uma camada para testar:",
        reply_markup=painel_teste(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("teste:"))
def callback_teste(call):
    bot.answer_callback_query(call.id)
    tipo = call.data.split(":", 1)[1]

    if tipo in ("2", "3", "4"):
        bot.send_message(call.message.chat.id, montar_bloco(int(tipo)))
        return

    if tipo == "todos":
        # Separado de propósito: uma mensagem por camada.
        bot.send_message(call.message.chat.id, montar_bloco(2))
        bot.send_message(call.message.chat.id, montar_bloco(3))
        bot.send_message(call.message.chat.id, montar_bloco(4))


# ============================================================
# FLASK / RENDER WEBHOOK
# ============================================================
@app.route("/", methods=["GET"])
def index():
    return "Bot de laboratório de alinhamento online.", 200


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
    print("BOT DE LABORATÓRIO DE ALINHAMENTO INICIADO")
    app.run(host="0.0.0.0", port=PORT)
