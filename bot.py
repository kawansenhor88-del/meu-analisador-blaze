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
# Cada camada (2, 3 e 4 dígitos) é independente.
# Cada coluna também é independente.
#
# ANTES_SETA = espaço entre "Saiu" e o hífen/seta.
# APOS = espaço depois do resultado (G ou ✅).
#
# Use 0.0, 0.2, 0.4, 0.6, 1.0...

AJUSTES = {
    2: {
        # ⬅️ COLUNA ESQUERDA
        "ESQ_ANTES_SETA_G": 0.0,
        "ESQ_ANTES_SETA_CHECK": 0.0,
        "ESQ_APOS_G": 0.0,
        "ESQ_APOS_CHECK": 0.0,

        # ➡️ COLUNA DIREITA
        "DIR_ANTES_SETA_G": 0.0,
        "DIR_ANTES_SETA_CHECK": 0.0,
        "DIR_APOS_G": 0.0,
        "DIR_APOS_CHECK": 0.0,
    },
    3: {
        # ⬅️ COLUNA ESQUERDA
        "ESQ_ANTES_SETA_G": 0.0,
        "ESQ_ANTES_SETA_CHECK": 0.0,
        "ESQ_APOS_G": 0.0,
        "ESQ_APOS_CHECK": 0.0,

        # ➡️ COLUNA DIREITA
        "DIR_ANTES_SETA_G": 0.0,
        "DIR_ANTES_SETA_CHECK": 0.0,
        "DIR_APOS_G": 0.0,
        "DIR_APOS_CHECK": 0.0,
    },
    4: {
        # ⬅️ COLUNA ESQUERDA
        "ESQ_ANTES_SETA_G": 0.0,
        "ESQ_ANTES_SETA_CHECK": 0.0,
        "ESQ_APOS_G": 0.0,
        "ESQ_APOS_CHECK": 0.0,

        # ➡️ COLUNA DIREITA
        "DIR_ANTES_SETA_G": 0.0,
        "DIR_ANTES_SETA_CHECK": 0.0,
        "DIR_APOS_G": 0.0,
        "DIR_APOS_CHECK": 0.0,
    },
}

# Distância-base entre as duas colunas.
ENTRE_COLUNAS_FIXO = 2.0


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


def ajuste_por_resultado(resultado, cfg, lado, posicao):
    tipo = "CHECK" if resultado == "✅" else "G"
    if resultado != "✅" and not resultado.startswith("❌G"):
        return ""
    chave = f"{lado}_{posicao}_{tipo}"
    return criar_espaco(cfg[chave])


def montar_coluna(numero, saiu, jogaria, resultado, cfg, lado):
    antes = ajuste_por_resultado(resultado, cfg, lado, "ANTES_SETA")
    apos = ajuste_por_resultado(resultado, cfg, lado, "APOS")
    return f"{numero}  {saiu}{antes}-{jogaria}{resultado}{apos}"


def montar_linha(dados, digitos):
    cfg = AJUSTES[digitos]
    numero, saiu_esq, joga_esq, res_esq, saiu_dir, joga_dir, res_dir = dados

    esquerda = montar_coluna(numero, saiu_esq, joga_esq, res_esq, cfg, "ESQ")
    direita = montar_coluna(numero, saiu_dir, joga_dir, res_dir, cfg, "DIR")
    entre = criar_espaco(ENTRE_COLUNAS_FIXO)
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
        f"⬅️ ESQ antes seta — G: {cfg['ESQ_ANTES_SETA_G']} | ✅: {cfg['ESQ_ANTES_SETA_CHECK']}\n"
        f"⬅️ ESQ depois — G: {cfg['ESQ_APOS_G']} | ✅: {cfg['ESQ_APOS_CHECK']}\n"
        f"➡️ DIR antes seta — G: {cfg['DIR_ANTES_SETA_G']} | ✅: {cfg['DIR_ANTES_SETA_CHECK']}\n"
        f"➡️ DIR depois — G: {cfg['DIR_APOS_G']} | ✅: {cfg['DIR_APOS_CHECK']}"
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
