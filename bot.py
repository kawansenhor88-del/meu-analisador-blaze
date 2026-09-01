import os
import time
import uuid
import traceback
import requests
import telebot


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "A variável TELEGRAM_TOKEN não foi configurada."
    )

bot = telebot.TeleBot(TELEGRAM_TOKEN)

TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)


# ============================================================
# COR PELO NÚMERO
# ============================================================

def obter_cor(numero):

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
# PEGAR O NÚMERO DA RODADA
# ============================================================

def obter_numero(rodada):

    if isinstance(rodada, dict):

        # roll é o campo utilizado pelo TipMiner.
        campos = [
            "roll",
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
                    numero = int(valor)

                    if 0 <= numero <= 14:
                        return numero

                except:
                    pass

    else:

        try:
            numero = int(rodada)

            if 0 <= numero <= 14:
                return numero

        except:
            pass

    return None


# ============================================================
# ENCONTRAR A LISTA DE RODADAS NO JSON
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

        if campo in dados:

            valor = dados[campo]

            if isinstance(valor, list):

                return valor

    # Procura também em estruturas internas
    for valor in dados.values():

        if isinstance(valor, (dict, list)):

            resultado = encontrar_rodadas(valor)

            if resultado:

                return resultado

    return []


# ============================================================
# ENVIAR OS 200 SEM ESTOURAR O LIMITE DO TELEGRAM
# ============================================================

def enviar_registros(chat_id, linhas):

    bloco = []

    for linha in linhas:

        bloco.append(linha)

        # 100 registros por mensagem
        if len(bloco) >= 100:

            bot.send_message(
                chat_id,
                "\n".join(bloco)
            )

            bloco = []

    # Envia o restante
    if bloco:

        bot.send_message(
            chat_id,
            "\n".join(bloco)
        )


# ============================================================
# COMANDO /TESTE200
# ============================================================

@bot.message_handler(commands=["teste200"])
def teste200(message):

    try:

        # ----------------------------------------------------
        # Consulta DIRETA à API
        # ----------------------------------------------------

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

        print("====================================")
        print("TIPMINER HISTORY")
        print("STATUS:", resposta.status_code)
        print("====================================")

        # ----------------------------------------------------
        # Verifica resposta
        # ----------------------------------------------------

        if resposta.status_code != 200:

            bot.send_message(
                message.chat.id,
                f"❌ TipMiner respondeu HTTP "
                f"{resposta.status_code}"
            )

            return

        dados = resposta.json()

        rodadas = encontrar_rodadas(dados)

        if not rodadas:

            bot.send_message(
                message.chat.id,
                "❌ Não encontrei as rodadas "
                "na resposta do TipMiner."
            )

            print(resposta.text[:10000])

            return

        # ----------------------------------------------------
        # PEGAR SOMENTE 200 REGISTROS
        # ----------------------------------------------------

        rodadas = rodadas[:200]

        print(
            "REGISTROS ENCONTRADOS:",
            len(rodadas)
        )

        # ----------------------------------------------------
        # PREPARAR SAÍDA
        # ----------------------------------------------------

        linhas = []

        for posicao, rodada in enumerate(
            rodadas,
            start=1
        ):

            numero = obter_numero(rodada)

            if numero is None:

                linha = f"{posicao:03d}. ❓"

            else:

                emoji = obter_cor(numero)

                linha = (
                    f"{posicao:03d}. "
                    f"{emoji} "
                    f"{numero}"
                )

            linhas.append(linha)

        # ----------------------------------------------------
        # MENSAGEM INICIAL
        # ----------------------------------------------------

        bot.send_message(
            message.chat.id,
            "✅ TipMiner retornou "
            f"{len(rodadas)} registros.\n\n"
            "📊 Enviando os registros..."
        )

        # ----------------------------------------------------
        # ENVIA OS 200 EM BLOCOS
        # ----------------------------------------------------

        enviar_registros(
            message.chat.id,
            linhas
        )

        print("====================================")
        print("TESTE FINALIZADO")
        print("TOTAL ENVIADO:", len(rodadas))
        print("====================================")

    except Exception as erro:

        print("====================================")
        print("ERRO NO TESTE200")
        print(type(erro).__name__)
        print(str(erro))
        traceback.print_exc()
        print("====================================")

        try:

            bot.send_message(
                message.chat.id,
                "❌ Erro no teste:\n\n"
                f"{type(erro).__name__}: "
                f"{str(erro)[:800]}"
            )

        except:
            pass


# ============================================================
# INICIAR
# ============================================================

print("====================================")
print("🧪 TESTE TIPMINER INICIADO")
print("Banco: NÃO")
print("Gemini: NÃO")
print("SSE: NÃO")
print("Flask: NÃO")
print("====================================")

bot.infinity_polling(
    skip_pending=True,
    timeout=30,
    long_polling_timeout=30
    )
