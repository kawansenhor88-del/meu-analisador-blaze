import os
import time
import uuid
import json
import traceback
import requests
import telebot

# ============================================================
# TESTE ISOLADO - TIPMINER HISTORY
# ============================================================
# Este arquivo NÃO usa:
# - PostgreSQL / Supabase
# - Gemini
# - SSE
# - Flask
# - o bot.py original
#
# Ele serve somente para testar o endpoint /history.
#
# Configure no Render:
# TELEGRAM_TOKEN = token do bot que será usado para o teste
#
# Depois mande no Telegram:
# /teste200
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "A variável TELEGRAM_TOKEN não foi configurada no ambiente."
    )

bot = telebot.TeleBot(TELEGRAM_TOKEN)

TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)


def extrair_numero(rodada):
    """Extrai o número original da rodada."""
    if isinstance(rodada, (int, float)):
        try:
            numero = int(rodada)
            return numero if 0 <= numero <= 14 else None
        except Exception:
            return None

    if isinstance(rodada, str):
        try:
            numero = int(rodada)
            return numero if 0 <= numero <= 14 else None
        except Exception:
            return None

    if isinstance(rodada, dict):
        # roll é o campo esperado no histórico do TipMiner.
        for campo in (
            "roll",
            "number",
            "numero",
            "result",
            "value",
            "winningNumber",
        ):
            if campo not in rodada:
                continue

            try:
                numero = int(rodada[campo])
                if 0 <= numero <= 14:
                    return numero
            except Exception:
                pass

    return None


def procurar_rodadas(obj):
    """Encontra a lista de rodadas dentro do JSON."""
    if isinstance(obj, list):
        # Se a própria lista contém rodadas, usa-a.
        if any(extrair_numero(item) is not None for item in obj[:20]):
            return obj

        # Caso esteja aninhada.
        for item in obj:
            encontrada = procurar_rodadas(item)
            if encontrada is not None:
                return encontrada

    if isinstance(obj, dict):
        # Campos mais prováveis primeiro.
        for campo in (
            "data",
            "history",
            "rounds",
            "items",
            "results",
            "records",
            "content",
            "rows",
        ):
            if campo in obj:
                encontrada = procurar_rodadas(obj[campo])
                if encontrada is not None:
                    return encontrada

        # Depois procura em qualquer outro campo.
        for valor in obj.values():
            if isinstance(valor, (dict, list)):
                encontrada = procurar_rodadas(valor)
                if encontrada is not None:
                    return encontrada

    return None


def cor(numero):
    if numero == 0:
        return "⚪"
    if 1 <= numero <= 7:
        return "🔴"
    if 8 <= numero <= 14:
        return "⚫"
    return "❓"


def enviar_blocos(chat_id, linhas):
    """Telegram aceita mensagens com até ~4096 caracteres."""
    bloco = ""

    for linha in linhas:
        if len(bloco) + len(linha) + 1 > 3800:
            bot.send_message(chat_id, bloco)
            bloco = ""

        bloco += linha + "\n"

    if bloco:
        bot.send_message(chat_id, bloco)


@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "🧪 Bot de teste da API TipMiner ativo.\n\n"
        "Use /teste200 para consultar o History."
    )


@bot.message_handler(commands=["teste200"])
def teste200(message):
    try:
        bot.send_message(
            message.chat.id,
            "🔎 Consultando diretamente o History do TipMiner..."
        )

        params = {
            "limit": 5000,
            "subject": "filter",
            "isLoadMore": "true",
            "t": int(time.time() * 1000),
            "timezone": "America/Sao_Paulo",
            "_cb": str(uuid.uuid4()),
        }

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        }

        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=30,
        )

        print("========================================")
        print("TESTE TIPMINER HISTORY")
        print("STATUS:", resposta.status_code)
        print("========================================")

        if resposta.status_code != 200:
            bot.send_message(
                message.chat.id,
                f"❌ API respondeu HTTP {resposta.status_code}"
            )
            return

        dados = resposta.json()
        rodadas = procurar_rodadas(dados)

        if not rodadas:
            print("Não foi encontrada uma lista de rodadas.")
            print(json.dumps(dados, ensure_ascii=False)[:15000])

            bot.send_message(
                message.chat.id,
                "❌ Não encontrei as rodadas na resposta da API."
            )
            return

        # O objetivo é comparar exatamente os 200 registros recebidos.
        rodadas = rodadas[:200]

        linhas = []

        for posicao, rodada in enumerate(rodadas, start=1):
            numero = extrair_numero(rodada)

            if numero is None:
                linhas.append(f"{posicao:03d}. ❓")
            else:
                linhas.append(
                    f"{posicao:03d}. {cor(numero)} {numero}"
                )

        bot.send_message(
            message.chat.id,
            "✅ API respondeu HTTP 200\n"
            f"📊 Registros usados no teste: {len(rodadas)}\n\n"
            "Somente cor + número:"
        )

        enviar_blocos(message.chat.id, linhas)

        print("TOTAL USADO:", len(rodadas))
        print("TESTE FINALIZADO")
        print("========================================")

    except Exception as erro:
        print("========================================")
        print("ERRO NO TESTE200")
        print(type(erro).__name__, str(erro))
        traceback.print_exc()
        print("========================================")

        bot.send_message(
            message.chat.id,
            "❌ Erro no teste:\n"
            f"{type(erro).__name__}: {str(erro)[:800]}"
        )


print("========================================")
print("🧪 TESTE ISOLADO TIPMINER INICIADO")
print("Banco: NÃO")
print("Gemini: NÃO")
print("SSE: NÃO")
print("Flask: NÃO")
print("========================================")

# Este bot usa polling de propósito.
# Portanto, NÃO deixe este arquivo rodando com o bot.py original
# usando o MESMO token ao mesmo tempo.
bot.infinity_polling(
    skip_pending=True,
    timeout=30,
    long_polling_timeout=30,
)
