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
# BUSCAR HISTÓRICO
# ============================================================

def buscar_historico(limite=5000):

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.tipminer.com",
        "Referer": "https://www.tipminer.com/",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/127.0.0.0 "
            "Mobile Safari/537.36"
        ),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
    }

    params = {
        "limit": limite,
        "subject": "filter",
        "isLoadMore": "true",
        "t": str(int(time.time() * 1000)),
        "timezone": "America/Sao_Paulo",
        "_cb": str(uuid.uuid4()),
    }

    print("========================================")
    print("🔎 CONSULTANDO TIPMINER")
    print("LIMIT:", limite)
    print("========================================")

    resposta = requests.get(
        TIPMINER_HISTORY_URL,
        params=params,
        headers=headers,
        timeout=60,
    )

    print("HTTP:", resposta.status_code)
    print("TAMANHO:", len(resposta.content))
    print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))
    print("URL FINAL:")
    print(resposta.url)

    resposta.raise_for_status()

    try:
        dados = resposta.json()

    except Exception as erro:

        print("❌ JSON INVÁLIDO")
        print(str(erro))
        print("RESPOSTA:")
        print(resposta.text[:3000])

        raise

    # ========================================================
    # A RESPOSTA DO LEMUR MOSTROU UMA LISTA DIRETA
    # ========================================================

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

    print("========================================")
    print("📊 RODADAS ENCONTRADAS:", len(rodadas))
    print("========================================")

    return rodadas


# ============================================================
# FORMATAR RODADA
# ============================================================

def formatar_rodada(numero, rodada):

    if not isinstance(rodada, dict):

        return (
            f"{numero:04d} | "
            f"{rodada}"
        )

    resultado = (
        rodada.get("result")
        if rodada.get("result") is not None
        else rodada.get("resultado")
    )

    instant = rodada.get(
        "instant",
        "N/A"
    )

    uuid_rodada = rodada.get(
        "uuid",
        "N/A"
    )

    cor = mapear_cor(resultado)

    return (
        f"{numero:04d} | "
        f"Resultado: {resultado} | "
        f"{cor} | "
        f"Instant: {instant} | "
        f"ID: {str(uuid_rodada)[:12]}"
    )


# ============================================================
# COMANDO /START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "✅ TESTE DE HISTÓRICO ONLINE!\n\n"
        "Envie:\n"
        "2000 rodadas"
    )


# ============================================================
# PEDIDO DAS 2000 RODADAS
# ============================================================

@bot.message_handler(func=lambda message: True)
def receber_mensagem(message):

    texto = (
        message.text or ""
    ).lower()

    if (
        "2000" in texto
        and "rodada" in texto
    ):

        bot.send_message(
            message.chat.id,
            "🔎 Buscando o histórico do TipMiner...\n\n"
            "Solicitando até 5.000 para verificar "
            "quantos registros a API realmente entrega."
        )

        try:

            rodadas = buscar_historico(5000)

            quantidade = len(rodadas)

            # ================================================
            # RESULTADO
            # ================================================

            if quantidade == 0:

                bot.send_message(
                    message.chat.id,
                    "⚠️ A API não retornou nenhuma rodada."
                )

                return

            bot.send_message(
                message.chat.id,
                "📊 RESULTADO\n\n"
                "Solicitado: 5.000\n"
                f"Recebido: {quantidade}\n\n"
                "Agora vou enviar os registros em blocos."
            )

            # ================================================
            # ENVIAR RODADAS
            # ================================================

            bloco = ""

            for i, rodada in enumerate(
                rodadas,
                start=1
            ):

                linha = formatar_rodada(
                    i,
                    rodada
                )

                if (
                    len(bloco)
                    + len(linha)
                    + 1
                    > 3800
                ):

                    bot.send_message(
                        message.chat.id,
                        bloco
                    )

                    bloco = ""

                    time.sleep(0.3)

                bloco += (
                    linha
                    + "\n"
                )

            if bloco:

                bot.send_message(
                    message.chat.id,
                    bloco
                )

            # ================================================
            # RESUMO
            # ================================================

            brancos = 0
            vermelhos = 0
            pretos = 0

            for rodada in rodadas:

                if not isinstance(
                    rodada,
                    dict
                ):
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
                "📊 RESUMO FINAL\n"
                "================================\n"
                "Solicitado: 5.000\n"
                f"Recebido: {quantidade}\n\n"
                f"⚪ Brancos: {brancos}\n"
                f"🔴 Vermelhos: {vermelhos}\n"
                f"⚫ Pretos: {pretos}\n"
                "================================"
            )

        except Exception as erro:

            print(
                "❌ ERRO AO BUSCAR HISTÓRICO"
            )

            print(
                type(erro).__name__
            )

            print(
                str(erro)
            )

            traceback.print_exc()

            bot.send_message(
                message.chat.id,
                "❌ ERRO AO CONSULTAR O TIPMINER\n\n"
                f"Tipo: {type(erro).__name__}\n"
                f"Erro: {erro}"
            )

        return

    # ========================================================
    # OUTRAS MENSAGENS
    # ========================================================

    bot.reply_to(
        message,
        "Envie:\n\n"
        "2000 rodadas"
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

        json_string = (
            request
            .get_data()
            .decode("utf-8")
        )

        update = (
            telebot.types.Update
            .de_json(json_string)
        )

        bot.process_new_updates(
            [update]
        )

        print(
            "✅ UPDATE DO TELEGRAM RECEBIDO"
        )

        return "OK", 200

    except Exception as erro:

        print(
            "❌ ERRO NO WEBHOOK"
        )

        print(
            type(erro).__name__
        )

        print(
            str(erro)
        )

        traceback.print_exc()

        return "ERROR", 500


# ============================================================
# ROTAS
# ============================================================

@app.route(
    "/",
    methods=["GET", "HEAD"]
)
def inicio():

    return (
        "Teste histórico TipMiner online.",
        200
    )


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

    print(
        "========================================"
    )

    print(
        "CONFIGURANDO WEBHOOK"
    )

    print(
        "URL:",
        webhook_url
    )

    print(
        "========================================"
    )

    try:

        bot.remove_webhook()

        time.sleep(1)

        resultado = bot.set_webhook(
            url=webhook_url
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

    except Exception as erro:

        print(
            "❌ ERRO AO CONFIGURAR WEBHOOK"
        )

        print(
            type(erro).__name__
        )

        print(
            str(erro)
        )

        traceback.print_exc()


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
