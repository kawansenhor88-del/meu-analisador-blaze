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
TIPMINER_AUTH_TOKEN = os.environ.get("TIPMINER_AUTH_TOKEN")

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

if not TIPMINER_AUTH_TOKEN:
raise RuntimeError("TIPMINER_AUTH_TOKEN não configurado.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(**name**)

# ============================================================

# CONVERTER COR

# ============================================================

def mapear_cor(resultado):

```
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
```

# ============================================================

# BUSCAR HISTÓRICO DO TIPMINER

# ============================================================

def buscar_rodadas(limite=2000):

```
headers = {
    "Accept": "*/*",
    "Accept-Language": "pt-BR",
    "Authorization": f"Bearer {TIPMINER_AUTH_TOKEN}",
    "Content-Type": "application/json",
    "Origin": "https://www.tipminer.com",
    "Referer": "https://www.tipminer.com/",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": (
        '"Chromium";v="127", '
        '"Not)A;Brand";v="99", '
        '"Microsoft Edge Simulate";v="127", '
        '"Lemur";v="127"'
    ),
    "Sec-Ch-Ua-Mobile": "?1",
    "Sec-Ch-Ua-Platform": '"Android"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
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
    "timezone": "America/Sao_Paulo",
    "t": int(time.time() * 1000),
    "_cb": str(__import__("uuid").uuid4()),
}

resposta = requests.get(
    TIPMINER_HISTORY_URL,
    params=params,
    headers=headers,
    timeout=30,
)

print("========================================")
print("TIPMINER HISTORY")
print("HTTP:", resposta.status_code)
print("TAMANHO:", len(resposta.content), "bytes")
print("CONTENT-TYPE:", resposta.headers.get("content-type"))
print("========================================")

resposta.raise_for_status()

try:
    dados = resposta.json()
except Exception as erro:

    print("❌ JSON INVÁLIDO")
    print("ERRO:", erro)
    print("INÍCIO DA RESPOSTA:")
    print(resposta.text[:500])

    raise

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
```

# ============================================================

# FORMATAR RODADA

# ============================================================

def formatar_rodada(numero, rodada):

```
if not isinstance(rodada, dict):
    return f"{numero:04d} | {rodada}"

resultado = (
    rodada.get("result")
    if rodada.get("result") is not None
    else rodada.get("resultado")
)

instant = rodada.get("instant", "N/A")
uuid = rodada.get("uuid", "N/A")
tipo = rodada.get("type", "N/A")

cor = mapear_cor(resultado)

return (
    f"{numero:04d} | "
    f"Resultado: {resultado} | "
    f"{cor} | "
    f"Tipo: {tipo} | "
    f"Instant: {instant} | "
    f"ID: {str(uuid)[:12]}"
)
```

# ============================================================

# START

# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

```
bot.reply_to(
    message,
    "✅ BOT DE TESTE FUNCIONANDO!\n\n"
    "Envie:\n"
    "2000 rodadas\n\n"
    "para consultar o histórico disponível."
)
```

# ============================================================

# PEDIDO DAS RODADAS

# ============================================================

@bot.message_handler(func=lambda message: True)
def receber_mensagem(message):

```
texto = (message.text or "").lower()

if "rodada" in texto:

    if "2000" in texto or "2.000" in texto:

        limite = 2000

    elif "500" in texto:

        limite = 500

    elif "1000" in texto or "1.000" in texto:

        limite = 1000

    else:

        limite = 200

    bot.send_message(
        message.chat.id,
        f"🔎 Buscando até {limite:,} rodadas no TipMiner..."
        .replace(",", ".")
    )

    try:

        rodadas = buscar_rodadas(limite)

        quantidade = len(rodadas)

        print("SOLICITADAS:", limite)
        print("RECEBIDAS:", quantidade)

        if quantidade == 0:

            bot.send_message(
                message.chat.id,
                "⚠️ A API não retornou nenhuma rodada."
            )

            return

        bot.send_message(
            message.chat.id,
            "📊 RESULTADO\n\n"
            f"Solicitadas: {limite:,}\n"
            f"Recebidas: {quantidade}\n\n"
            "🔐 Requisição autenticada."
            .replace(",", ".")
        )

        # ------------------------------------------------
        # ENVIA AS RODADAS EM BLOCOS
        # ------------------------------------------------

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

        # ------------------------------------------------
        # RESUMO
        # ------------------------------------------------

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
            f"Solicitadas: {limite:,}\n"
            f"Recebidas: {quantidade}\n\n"
            f"⚪ Brancos: {brancos}\n"
            f"🔴 Vermelhos: {vermelhos}\n"
            f"⚫ Pretos: {pretos}\n"
            "================================"
            .replace(",", ".")
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
    "Para testar, envie:\n"
    "2000 rodadas"
)
```

# ============================================================

# WEBHOOK

# ============================================================

@app.route("/telegram/webhook", methods=["POST"])
def receber_webhook():

```
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
```

# ============================================================

# HEALTH CHECK

# ============================================================

@app.route("/", methods=["GET", "HEAD"])
def inicio():

```
return "Bot webhook de teste online.", 200
```

@app.route("/health")
def health():

```
return "OK", 200
```

# ============================================================

# CONFIGURAR WEBHOOK

# ============================================================

def configurar_webhook():

```
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
```

# ============================================================

# SERVIDOR

# ============================================================

if **name** == "**main**":

```
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
```
            
