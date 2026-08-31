import os
import time
import traceback
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

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado.")

if not RENDER_EXTERNAL_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL não configurado.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)


# ============================================================
# CONVERTER COR
# ============================================================

def mapear_cor(resultado):
    try:
        numero = int(resultado)

        if numero == 0:
            return "⚪ Branco"

        if 1 <= numero <= 7:
            return "🔴 Vermelho"

        if 8 <= numero <= 14:
            return "⚫ Preto"

        return "❓ Desconhecido"

    except Exception:
        return "❓ Desconhecido"


# ============================================================
# BUSCAR RODADAS
# ============================================================

def buscar_rodadas(limite=1000):

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.tipminer.com",
        "Referer": "https://www.tipminer.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    params = {
        "limit": limite,
        "subject": "filter",
        "isLoadMore": "true",
        "timezone": "America/Sao_Paulo",
    }

    print("========================================")
    print("TIPMINER TEST 1000")
    print("SOLICITADO:", limite)
    print("========================================")

    resposta = requests.get(
        TIPMINER_HISTORY_URL,
        params=params,
        headers=headers,
        timeout=30,
    )

    print("STATUS:", resposta.status_code)
    print("CONTENT-TYPE:", resposta.headers.get("content-type"))

    resposta.raise_for_status()

    try:
        dados = resposta.json()
    except ValueError:
        print("❌ RESPOSTA NÃO É JSON")
        print(resposta.text[:1000])
        raise RuntimeError(
            "A API do TipMiner não retornou JSON."
        )

    print("RESPONSE TYPE:", type(dados).__name__)

    if isinstance(dados, list):
        return dados

    if isinstance(dados, dict):

        if isinstance(dados.get("data"), list):
            return dados["data"]

        if isinstance(dados.get("rounds"), list):
            return dados["rounds"]

        if isinstance(dados.get("results"), list):
            return dados["results"]

    return []


# ============================================================
# FORMATAR RODADA
# ============================================================

def formatar_rodada(numero, rodada):

    if not isinstance(rodada, dict):
        return f"{numero:03d} | {rodada}"

    resultado = (
        rodada.get("result")
        if rodada.get("result") is not None
        else rodada.get("resultado")
    )

    instant = rodada.get("instant", "N/A")
    uuid = rodada.get("uuid", "N/A")

    cor = mapear_cor(resultado)

    return (
        f"{numero:03d} | "
        f"Resultado: {resultado} | "
        f"{cor} | "
        f"Instant: {instant} | "
        f"ID: {str(uuid)[:12]}"
    )


# ============================================================
# COMANDO /START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "✅ BOT DE TESTE FUNCIONANDO!\n\n"
        "Envie:\n"
        "1000 rodadas\n\n"
        "para consultar as 1000 rodadas mais recentes."
    )


# ============================================================
# PEDIDO DAS RODADAS
# ============================================================

@bot.message_handler(func=lambda message: True)
def receber_mensagem(message):

    texto = (message.text or "").lower()

    if "rodada" in texto:

        bot.send_message(
            message.chat.id,
            "🔎 Buscando as 1000 rodadas mais recentes..."
        )

        try:

            rodadas = buscar_rodadas(1000)

            quantidade = len(rodadas)

            print("ROUNDS RECEIVED:", quantidade)

            if quantidade == 0:

                bot.send_message(
                    message.chat.id,
                    "⚠️ A API não retornou nenhuma rodada."
                )

                return

            bot.send_message(
                message.chat.id,
                f"✅ API retornou {quantidade} rodadas.\n\n"
                "📊 Enviando os registros..."
            )

            # =================================================
            # ENVIAR EM BLOCOS
            # =================================================

            bloco = ""

            for i, rodada in enumerate(rodadas, start=1):

                linha = formatar_rodada(i, rodada)

                if len(bloco) + len(linha) + 1 > 3800:

                    bot.send_message(
                        message.chat.id,
                        bloco
                    )

                    bloco = ""

                    time.sleep(0.3)

                bloco += linha + "\n"

            if bloco:

                bot.send_message(
                    message.chat.id,
                    bloco
                )

            # =================================================
            # RESUMO
            # =================================================

            brancos = 0
            vermelhos = 0
            pretos = 0

            for rodada in rodadas:

                if not isinstance(rodada, dict):
                    continue

                resultado = (
                    rodada.get("result")
                    if rodada.get("result") is not None
                    else rodada.get("resultado")
                )

                try:

                    numero = int(resultado)

                    if numero == 0:
                        brancos += 1

                    elif 1 <= numero <= 7:
                        vermelhos += 1

                    elif 8 <= numero <= 14:
                        pretos += 1

                except Exception:
                    pass

            bot.send_message(
                message.chat.id,
                "================================\n"
                "📊 RESUMO DO TESTE\n"
                "================================\n"
                f"Solicitadas: 1000\n"
                f"Recebidas: {quantidade}\n\n"
                f"⚪ Brancos: {brancos}\n"
                f"🔴 Vermelhos: {vermelhos}\n"
                f"⚫ Pretos: {pretos}\n"
                "================================"
            )

        except Exception as erro:

            print("❌ ERRO AO BUSCAR HISTÓRICO")
            print(type(erro).__name__)
            print(str(erro))

            traceback.print_exc()

            bot.send_message(
                message.chat.id,
                "❌ Erro ao consultar a API do TipMiner.\n\n"
                f"{type(erro).__name__}: {erro}"
            )

        return

    bot.reply_to(
        message,
        "✅ Recebi sua mensagem!\n\n"
        "Para testar, escreva:\n"
        "1000 rodadas"
    )


# ============================================================
# WEBHOOK
# ============================================================

@app.route("/telegram/webhook", methods=["POST"])
def receber_webhook():

    try:

        json_string = request.get_data().decode("utf-8")

        update = telebot.types.Update.de_json(
            json_string
        )

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
def inicio():

    return "Bot webhook de teste online.", 200


@app.route("/health")
def health():

    return "OK", 200


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
# SERVIDOR
# ============================================================

if __name__ == "__main__":

    configurar_webhook()

    print("========================================")
    print("SERVER STARTED")
    print("PORT:", PORT)
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )
