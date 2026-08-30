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

# BUSCAR RODADAS

# ============================================================

def buscar_rodadas(limite=200):

```
headers = {
    "Accept": "*/*",
    "Accept-Language": "pt-BR",
    "Authorization": f"Bearer {TIPMINER_AUTH_TOKEN}",
    "Content-Type": "application/json",
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
    "timezone": "America/Sao_Paulo",
    "t": int(time.time() * 1000),
    "_cb": str(uuid.uuid4()),
}

print("========================================")
print("CONSULTANDO TIPMINER")
print("LIMIT:", limite)
print("========================================")

resposta = requests.get(
    TIPMINER_HISTORY_URL,
    params=params,
    headers=headers,
    timeout=30,
)

print("HTTP:", resposta.status_code)
print("TAMANHO:", len(resposta.content), "bytes")
print("CONTENT-TYPE:", resposta.headers.get("content-type"))

resposta.raise_for_status()

try:
    dados = resposta.json()

except Exception as erro:

    print("❌ JSON INVÁLIDO")
    print("ERRO:", erro)
    print("RESPOSTA:")
    print(resposta.text[:1000])

    raise

# --------------------------------------------------------
# A API pode devolver diretamente uma lista.
# --------------------------------------------------------

if isinstance(dados, list):

    print("FORMATO: LISTA")
    print("REGISTROS RECEBIDOS:", len(dados))

    return dados

# --------------------------------------------------------
# Ou pode devolver a lista dentro de um objeto.
# --------------------------------------------------------

if isinstance(dados, dict):

    print("FORMATO: OBJETO")
    print("CHAVES:", list(dados.keys()))

    if isinstance(dados.get("data"), list):
        print("REGISTROS EM data:", len(dados["data"]))
        return dados["data"]

    if isinstance(dados.get("rounds"), list):
        print("REGISTROS EM rounds:", len(dados["rounds"]))
        return dados["rounds"]

    if isinstance(dados.get("results"), list):
        print("REGISTROS EM results:", len(dados["results"]))
        return dados["results"]

print("⚠️ FORMATO DE RESPOSTA NÃO RECONHECIDO")

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
uuid_rodada = rodada.get("uuid", "N/A")
tipo = rodada.get("type", "N/A")

cor = mapear_cor(resultado)

return (
    f"{numero:04d} | "
    f"Resultado: {resultado} | "
    f"{cor} | "
    f"Tipo: {tipo} | "
    f"Instant: {instant} | "
    f"ID: {str(uuid_rodada)[:12]}"
)
```

# ============================================================

# /START

# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

```
bot.reply_to(
    message,
    "✅ BOT DE TESTE FUNCIONANDO!\n\n"
    "Envie uma destas opções:\n\n"
    "200 rodadas\n"
    "400 rodadas\n"
    "1000 rodadas\n"
    "2000 rodadas"
)
```

# ============================================================

# RECEBER MENSAGEM

# ============================================================

@bot.message_handler(func=lambda message: True)
def receber_mensagem(message):

```
texto = (message.text or "").lower().replace(".", "")

if "rodada" not in texto:
    bot.reply_to(
        message,
        "Envie, por exemplo:\n\n"
        "400 rodadas"
    )
    return

if "2000" in texto:
    limite = 2000

elif "1000" in texto:
    limite = 1000

elif "400" in texto:
    limite = 400

else:
    limite = 200

bot.send_message(
    message.chat.id,
    f"🔎 Consultando {limite} rodadas no TipMiner..."
)

try:

    rodadas = buscar_rodadas(limite)

    quantidade = len(rodadas)

    print("========================================")
    print("RESULTADO FINAL")
    print("SOLICITADAS:", limite)
    print("RECEBIDAS:", quantidade)
    print("========================================")

    if quantidade == 0:

        bot.send_message(
            message.chat.id,
            "⚠️ A API não retornou nenhuma rodada."
        )

        return

    # ----------------------------------------------------
    # PRIMEIRA MENSAGEM: RESULTADO DA API
    # ----------------------------------------------------

    bot.send_message(
        message.chat.id,
        "📊 RESULTADO\n\n"
        f"Solicitadas: {limite:,}\n"
        f"Recebidas: {quantidade:,}\n\n"
        f"HTTP: 200"
        .replace(",", ".")
    )

    # ----------------------------------------------------
    # ENVIAR RODADAS EM BLOCOS
    # ----------------------------------------------------

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

    # ----------------------------------------------------
    # ESTATÍSTICAS
    # ----------------------------------------------------

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
        f"Recebidas: {quantidade:,}\n\n"
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
        "❌ ERRO NO TIPMINER\n\n"
        f"{type(erro).__name__}: {erro}"
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
    
