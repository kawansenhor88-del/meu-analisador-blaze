import os
import requests

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

TOKEN = os.getenv("TIPMINER_TOKEN")

if not TOKEN:
    print("ERRO: TIPMINER_TOKEN não foi configurado no Render.")
    raise SystemExit(1)

PARAMS = {
    "limit": "1000",
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo"
}

HEADERS = {
    "accept": "*/*",
    "accept-language": "pt-BR",
    "authorization": "Bearer " + TOKEN,
    "content-type": "application/json",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36"
}

print("========================================")
print("TIPMINER TESTE AUTENTICADO")
print("========================================")

try:
    resposta = requests.get(
        URL,
        params=PARAMS,
        headers=HEADERS,
        timeout=30
    )

    print("STATUS:", resposta.status_code)
    print("CONTENT-TYPE:", resposta.headers.get("content-type"))

    resposta.raise_for_status()

    dados = resposta.json()

    print("RESPONSE TYPE:", type(dados).__name__)
    print("ROUNDS RECEIVED:", len(dados))

    print("========================================")

    if len(dados) >= 1000:
        print("SUCESSO!")
        print("1000 OU MAIS REGISTROS RECEBIDOS!")

    elif len(dados) == 200:
        print("RECEBEU 200 REGISTROS.")
        print("O TOKEN NÃO ALTEROU A QUANTIDADE.")

    else:
        print("RECEBEU:", len(dados))

except Exception as erro:
    print("========================================")
    print("ERRO")
    print("TIPO:", type(erro).__name__)
    print("DETALHE:", str(erro))
