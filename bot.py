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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 10000))

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado.")

if not RENDER_EXTERNAL_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL não configurado.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)


# ============================================================
# TIPMINER HISTORY
# ============================================================

TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)


# ============================================================
# ENCONTRAR A LISTA DE REGISTROS
# ============================================================

def encontrar_lista(dados):

    if isinstance(dados, list):
        return dados

    if isinstance(dados, dict):

        # Primeiro procura os campos mais prováveis
        for campo in [
            "data",
            "history",
            "rounds",
            "items",
            "results",
            "records",
            "content",
            "rows"
        ]:

            valor = dados.get(campo)

            if isinstance(valor, list):
                return valor

        # Depois procura listas dentro de outros campos
        for valor in dados.values():

            if isinstance(valor, (dict, list)):

                resultado = encontrar_lista(valor)

                if resultado:
                    return resultado

    return []


# ============================================================
# PEGAR NÚMERO
# ============================================================

def numero_da_rodada(rodada):

    if not isinstance(rodada, dict):
        return rodada

    for campo in [
        "roll",
        "number",
        "numero",
        "result",
        "value",
        "winningNumber"
    ]:

        if campo in rodada:

            valor = rodada[campo]

            if valor is not None:

                try:
                    return int(valor)
                except:
                    return valor

    return "?"


# ============================================================
# PEGAR HORÁRIO
# ============================================================

def horario_da_rodada(rodada):

    if not isinstance(rodada, dict):
        return "?"

    for campo in [
        "time",
        "tempo",
        "createdAt",
        "created_at",
        "instant",
        "timestamp",
        "date",
        "datetime"
    ]:

        if campo in rodada:

            valor = rodada[campo]

            if valor is not None:
                return str(valor)

    return "?"


# ============================================================
# MOSTRAR UMA RODADA
# ============================================================

def resumo_rodada(posicao, rodada):

    numero = numero_da_rodada(rodada)
    horario = horario_da_rodada(rodada)

    return (
        f"Posição {posicao}\n"
        f"Número: {numero}\n"
        f"Horário: {horario}"
    )


# ============================================================
# /TESTE
# ============================================================

@bot.message_handler(commands=["teste"])
def teste(message):

    try:

        bot.send_message(
            message.chat.id,
            "🔎 Consultando a resposta bruta do History..."
        )

        params = {
            "limit": 5000,
            "subject": "filter",
            "isLoadMore": "true",
            "t": int(time.time() * 1000),
            "timezone": "America/Sao_Paulo",
            "_cb": str(uuid.uuid4())
        }

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache"
        }

        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=30
        )

        print("STATUS:", resposta.status_code)
        print("URL FINAL:", resposta.url)

        if resposta.status_code != 200:

            bot.send_message(
                message.chat.id,
                f"❌ TipMiner respondeu HTTP "
                f"{resposta.status_code}"
            )

            return

        dados = resposta.json()

        # ----------------------------------------------------
        # LISTA ENCONTRADA
        # ----------------------------------------------------

        rodadas = encontrar_lista(dados)

        total = len(rodadas)

        print("TOTAL DE REGISTROS:", total)

        if total == 0:

            bot.send_message(
                message.chat.id,
                "❌ Nenhuma lista de registros encontrada."
            )

            return

        # ----------------------------------------------------
        # CABEÇALHO
        # ----------------------------------------------------

        bot.send_message(
            message.chat.id,
            "✅ API respondeu HTTP 200\n\n"
            f"📊 Total encontrado: {total}\n\n"
            "Agora vou mostrar as posições "
            "para descobrir a ordem real."
        )

        # ----------------------------------------------------
        # PRIMEIROS REGISTROS
        # ----------------------------------------------------

        mensagem = "🔵 PRIMEIRAS POSIÇÕES\n\n"

        quantidade_inicio = min(5, total)

        for i in range(quantidade_inicio):

            mensagem += (
                resumo_rodada(
                    i,
                    rodadas[i]
                )
                + "\n\n"
            )

        bot.send_message(
            message.chat.id,
            mensagem
        )

        # ----------------------------------------------------
        # POSIÇÕES IMPORTANTES
        # ----------------------------------------------------

        posicoes = [
            0,
            1,
            98,
            99,
            100,
            101,
            198,
            199,
            200,
            201,
            998,
            999,
            1000,
            1001,
            1798,
            1799,
            1800,
            1801,
            1898,
            1899,
            1900,
            1901,
            1998,
            1999
        ]

        # Só mostra posições que realmente existem
        posicoes = [
            p for p in posicoes
            if p < total
        ]

        mensagem = "🧪 POSIÇÕES DE CONTROLE\n\n"

        for p in posicoes:

            mensagem += (
                resumo_rodada(
                    p,
                    rodadas[p]
                )
                + "\n\n"
            )

            # Mantém cada mensagem pequena
            if len(mensagem) > 3500:

                bot.send_message(
                    message.chat.id,
                    mensagem
                )

                mensagem = ""

        if mensagem:

            bot.send_message(
                message.chat.id,
                mensagem
            )

        # ----------------------------------------------------
        # ÚLTIMOS REGISTROS
        # ----------------------------------------------------

        mensagem = "🔴 ÚLTIMAS POSIÇÕES\n\n"

        inicio = max(0, total - 5)

        for i in range(inicio, total):

            mensagem += (
                resumo_rodada(
                    i,
                    rodadas[i]
                )
                + "\n\n"
            )

        bot.send_message(
            message.chat.id,
            mensagem
        )

        # ----------------------------------------------------
        # RESUMO
        # ----------------------------------------------------

        bot.send_message(
            message.chat.id,
            "✅ TESTE FINALIZADO\n\n"
            f"Total de registros encontrados: {total}\n\n"
            "Agora temos as posições 0, 199, "
            "999, 1799, 1800, 1899 e 1999 "
            "para comparar com o TipMiner."
        )

    except Exception as erro:

        print("ERRO:", type(erro).__name__, str(erro))
        traceback.print_exc()

        try:

            bot.send_message(
                message.chat.id,
                "❌ Erro:\n"
                f"{type(erro).__name__}: "
                f"{str(erro)[:800]}"
            )

        except:
            pass


# ============================================================
# WEBHOOK
# ============================================================

@app.route(
    "/telegram-webhook",
    methods=["POST"]
)
def telegram_webhook():

    try:

        json_string = request.get_data().decode(
            "utf-8"
        )

        update = telebot.types.Update.de_json(
            json_string
        )

        bot.process_new_updates(
            [update]
        )

        return "OK", 200

    except Exception as erro:

        print("Webhook error:", erro)

        return "ERROR", 500


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return "🧪 TipMiner TEST BOT online", 200


# ============================================================
# WEBHOOK
# ============================================================

def configurar_webhook():

    webhook_url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/telegram-webhook"
    )

    print("Webhook:")
    print(webhook_url)

    resultado = bot.set_webhook(
        url=webhook_url
    )

    print(
        "Webhook configurado:",
        resultado
    )


# ============================================================
# INICIAR
# ============================================================

if __name__ == "__main__":

    print("====================================")
    print("TIPMINER TEST BOT")
    print("====================================")

    print("Banco: NÃO")
    print("Gemini: NÃO")
    print("SSE: NÃO")
    print("Polling: NÃO")
    print("Webhook: SIM")

    configurar_webhook()

    app.run(
        host="0.0.0.0",
        port=PORT
        )
