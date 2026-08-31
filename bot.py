import os
import requests

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

PARAMS = {
    "limit": "1000",
    "subject": "filter",
    "isLoadMore": "true",
    "t": "1788133629539",
    "timezone": "America/Sao_Paulo",
    "_cb": "59aa192b-a03c-40e6-8838-b470fe4eeb99"
}

TOKEN = os.getenv("TIPMINER_TOKEN")

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
print("TIPMINER - TESTE REAL DE 1000")
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

    dados = resposta.json()

    print("TIPO:", type(dados).__name__)
    print("REGISTROS RECEBIDOS:", len(dados))

    print("----------------------------------------")

    if len(dados) == 1000:
        print("✅ SUCESSO!")
        print("✅ OS 1000 REGISTROS CHEGARAM!")

    elif len(dados) == 200:
        print("⚠️ RECEBEU EXATAMENTE 200")
        print("⚠️ AINDA EXISTE ALGUMA DIFERENÇA NA REQUISIÇÃO.")

    else:
        print("⚠️ QUANTIDADE:", len(dados))

    print("----------------------------------------")

    for posicao in [0, 99, 100, 199, 299, 399, 499,
                    599, 699, 799, 899, 999]:

        if posicao < len(dados):
            rodada = dados[posicao]

            print("")
            print("POSIÇÃO:", posicao)
            print("RESULTADO:", rodada.get("result"))
            print("TIPO:", rodada.get("type"))
            print("HORÁRIO:", rodada.get("instant"))

except Exception as erro:
    print("========================================")
    print("ERRO")
    print(type(erro).__name__)
    print(str(erro))
