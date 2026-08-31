import time
import uuid
import traceback
import requests
import telebot


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TELEGRAM_TOKEN = "COLOQUE_SEU_TOKEN_AQUI"

bot = telebot.TeleBot(TELEGRAM_TOKEN)


TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)


# ============================================================
# CONVERTER NÚMERO EM COR
# ============================================================

def converter_cor(numero):

    try:
        numero = int(numero)
    except:
        return "❓"

    if numero == 0:
        return "⚪"

    if 1 <= numero <= 7:
        return "🔴"

    if 8 <= numero <= 14:
        return "⚫"

    return "❓"


# ============================================================
# ENCONTRAR A LISTA DE RODADAS NA RESPOSTA
# ============================================================

def encontrar_rodadas(dados):

    if isinstance(dados, list):
        return dados

    if not isinstance(dados, dict):
        return []

    campos = [
        "data",
        "history",
        "rounds",
        "items",
        "results",
        "records",
        "content",
        "rows"
    ]

    for campo in campos:

        valor = dados.get(campo)

        if isinstance(valor, list):
            return valor

    return []


# ============================================================
# EXTRAIR NÚMERO DA RODADA
# ============================================================

def extrair_numero(rodada):

    if isinstance(rodada, dict):

        campos = [
            "number",
            "numero",
            "result",
            "value",
            "winningNumber"
        ]

        for campo in campos:

            if campo in rodada:

                valor = rodada[campo]

                try:
                    return int(valor)
                except:
                    pass

    elif isinstance(rodada, (int, float, str)):

        try:
            return int(rodada)
        except:
            pass

    return None


# ============================================================
# /TESTE200
# ============================================================

@bot.message_handler(commands=["teste200"])
def teste200(message):

    try:

        bot.send_message(
            message.chat.id,
            "🔎 Consultando diretamente a API do TipMiner..."
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

        print("================================")
        print("TESTE200")
        print("STATUS:", resposta.status_code)
        print("URL:", resposta.url)
        print("================================")

        if resposta.status_code != 200:

            bot.send_message(
                message.chat.id,
                f"❌ API respondeu HTTP {resposta.status_code}"
            )

            return

        try:

            dados = resposta.json()

        except Exception:

            bot.send_message(
                message.chat.id,
                "❌ A API respondeu, mas não retornou JSON."
            )

            print(resposta.text[:10000])

            return

        rodadas = encontrar_rodadas(dados)

        print(
            "TOTAL DE REGISTROS RECEBIDOS:",
            len(rodadas)
        )

        if not rodadas:

            bot.send_message(
                message.chat.id,
                "❌ Não encontrei a lista de rodadas na resposta da API."
            )

            print("RESPOSTA:")
            print(resposta.text[:15000])

            return

        # ====================================================
        # MOSTRAR SOMENTE COR + NÚMERO
        # ====================================================

        linhas = []

        for i, rodada in enumerate(rodadas, start=1):

            numero = extrair_numero(rodada)

            if numero is None:

                linha = f"{i:03d}. ❓"

            else:

                cor = converter_cor(numero)

                linha = f"{i:03d}. {cor} {numero}"

            linhas.append(linha)

        # ====================================================
        # ENVIAR EM BLOCOS PARA O TELEGRAM
        # ====================================================

        texto = ""

        for linha in linhas:

            if len(texto) + len(linha) + 1 > 3800:

                bot.send_message(
                    message.chat.id,
                    texto
                )

                texto = ""

            texto += linha + "\n"

        if texto:

            bot.send_message(
                message.chat.id,
                texto
            )

        print("================================")
        print("TESTE FINALIZADO")
        print("TOTAL:", len(rodadas))
        print("================================")

    except Exception as erro:

        print("================================")
        print("ERRO NO /TESTE200")
        print(type(erro).__name__)
        print(str(erro))
        traceback.print_exc()
        print("================================")

        bot.send_message(
            message.chat.id,
            "❌ Erro no teste:\n\n"
            + str(erro)[:1000]
        )


# ============================================================
# INICIAR BOT
# ============================================================

print("🤖 Bot iniciado.")

bot.infinity_polling(
    skip_pending=True,
    timeout=30,
    long_polling_timeout=30
            )
