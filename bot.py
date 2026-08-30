import os
import time
import uuid
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
# BUSCAR HISTÓRICO TIPMINER
# ============================================================

def buscar_rodadas(limite=5000):

    print("🔥 ENTROU EM buscar_rodadas()")

    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
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
        "limit": limite,
        "subject": "filter",
        "isLoadMore": "true",
        "t": int(time.time() * 1000),
        "timezone": "America/Sao_Paulo",
        "_cb": str(uuid.uuid4()),
    }

    print("🔥 PREPARANDO REQUISIÇÃO TIPMINER")
    print("🔥 LIMITE:", limite)
    print("🔥 PARÂMETROS:", params)

    try:
        print("🔥 ENVIANDO REQUEST PARA TIPMINER...")

        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=60,
        )

        print("🔥 REQUEST TERMINOU")
        print("----------------------------------------")
        print("STATUS HTTP:", resposta.status_code)
        print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))
        print("TAMANHO DA RESPOSTA:", len(resposta.content))
        print("----------------------------------------")
        print("URL FINAL:")
        print(resposta.url)
        print("----------------------------------------")
        print("INÍCIO DA RESPOSTA:")
        print(resposta.text[:3000])
        print("----------------------------------------")

        if resposta.status_code != 200:
            print("❌ API NÃO RETORNOU 200")
            return []

        try:
            dados = resposta.json()
            print("🔥 JSON VÁLIDO")

        except Exception as erro:
            print("❌ A RESPOSTA NÃO É JSON")
            print("ERRO:", type(erro).__name__)
            print("DETALHE:", str(erro))
            return []

        if isinstance(dados, dict):

            print("🔥 FORMATO: OBJETO JSON")
            print("🔥 CHAVES:", list(dados.keys()))

            if isinstance(dados.get("data"), list):
                rodadas = dados["data"]

            elif isinstance(dados.get("rounds"), list):
                rodadas = dados["rounds"]

            elif isinstance(dados.get("results"), list):
                rodadas = dados["results"]

            else:
                rodadas = []

        elif isinstance(dados, list):
            print("🔥 FORMATO: LISTA JSON")
            rodadas = dados

        else:
            print("❌ FORMATO JSON DESCONHECIDO")
            rodadas = []

        print("----------------------------------------")
        print("🔥 RODADAS ENCONTRADAS:", len(rodadas))
        print("----------------------------------------")

        return rodadas

    except requests.exceptions.Timeout:
        print("❌ TIMEOUT NO TIPMINER")
        return []

    except requests.exceptions.RequestException as erro:
        print("❌ ERRO DE REQUEST")
        print(type(erro).__name__)
        print(str(erro))
        return []

    except Exception as erro:
        print("❌ ERRO INESPERADO")
        print(type(erro).__name__)
        print(str(erro))
        traceback.print_exc()
        return []


# ============================================================
# FORMATAR RODADA
# ============================================================

def formatar_rodada(numero, rodada):

    if not isinstance(rodada, dict):
        return f"{numero:04d} | {rodada}"

    resultado = (
        rodada.get("result")
        if rodada.get("result") is not None
        else rodada.get("resultado")
    )

    instant = rodada.get("instant", "N/A")
    uuid_rodada = rodada.get("uuid", "N/A")

    return (
        f"{numero:04d} | "
        f"Resultado: {resultado} | "
        f"{mapear_cor(resultado)} | "
        f"Instant: {instant} | "
        f"ID: {str(uuid_rodada)[:12]}"
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    print("🔥 /START RECEBIDO")

    bot.reply_to(
        message,
        "✅ BOT DE TESTE TIPMINER ONLINE!\n\n"
        "Envie:\n5000 rodadas"
    )


# ============================================================
# RECEBER MENSAGENS
# ============================================================

@bot.message_handler(func=lambda message: True)
def receber_mensagem(message):

    print("🔥🔥 MENSAGEM RECEBIDA:", message.text)

    texto = (message.text or "").lower()

    if "5000" not in texto or "rodada" not in texto:

        print("⚠️ COMANDO NÃO RECONHECIDO")

        bot.reply_to(
            message,
            "Envie exatamente:\n5000 rodadas"
        )

        return

    print("🔥 COMANDO 5000 RECONHECIDO")

    bot.send_message(
        message.chat.id,
        "🔎 Consultando o TipMiner...\n\n"
        "Solicitando 5.000 rodadas."
    )

    print("🔥 VOU CHAMAR TIPMINER AGORA")

    rodadas = buscar_rodadas(5000)

    print("🔥 TIPMINER TERMINOU")
    print("🔥 QUANTIDADE RECEBIDA:", len(rodadas))

    quantidade = len(rodadas)

    if quantidade == 0:

        print("❌ QUANTIDADE ZERO")

        bot.send_message(
            message.chat.id,
            "⚠️ A API não retornou as rodadas.\n\n"
            "Veja os detalhes no log do Render."
        )

        return

    bot.send_message(
        message.chat.id,
        "✅ TESTE CONCLUÍDO\n\n"
        f"Solicitadas: 5000\n"
        f"Recebidas: {quantidade}"
    )

    texto_saida = "📋 PRIMEIRAS 20 RODADAS\n\n"

    for i, rodada in enumerate(rodadas[:20], start=1):
        texto_saida += formatar_rodada(i, rodada) + "\n"

    bot.send_message(message.chat.id, texto_saida)

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
        "📊 RESUMO\n"
        "================================\n"
        f"Solicitadas: 5000\n"
        f"Recebidas: {quantidade}\n\n"
        f"⚪ Brancos: {brancos}\n"
        f"🔴 Vermelhos: {vermelhos}\n"
        f"⚫ Pretos: {pretos}\n"
        "================================"
    )


# ============================================================
# WEBHOOK
# ============================================================

@app.route("/telegram/webhook", methods=["POST"])
def receber_webhook():

    try:
        print("🔥 WEBHOOK RECEBEU POST")

        json_string = request.get_data().decode("utf-8")

        update = telebot.types.Update.de_json(json_string)

        bot.process_new_updates([update])

        print("✅ UPDATE TELEGRAM PROCESSADO")

        return "OK", 200

    except Exception as erro:
        print("❌ ERRO WEBHOOK")
        print(type(erro).__name__)
        print(str(erro))

        traceback.print_exc()

        return "ERROR", 500


# ============================================================
# ROTAS
# ============================================================

@app.route("/", methods=["GET", "HEAD"])
def inicio():
    return "Teste TipMiner 5000 online.", 200


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

        resultado = bot.set_webhook(url=webhook_url)

        print("RESULTADO:", resultado)
        print("WEBHOOK CONFIGURED")

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
