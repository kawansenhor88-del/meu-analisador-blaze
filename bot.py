import requests

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

PARAMS = {
    "limit": "1000",
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo"
}

HEADERS = {
    "accept": "*/*",
    "accept-language": "pt-BR",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
    "user-agent": "Mozilla/5.0"
}

print("================================")
print("TIPMINER TESTE")
print("================================")

try:
    resposta = requests.get(
        URL,
        params=PARAMS,
        headers=HEADERS,
        timeout=30
    )

    print("STATUS:", resposta.status_code)

    dados = resposta.json()

    print("TIPO:", type(dados).__name__)
    print("REGISTROS RECEBIDOS:", len(dados))

    if len(dados) == 1000:
        print("✅ 1000 REGISTROS!")
    else:
        print("⚠️ RECEBEU:", len(dados))

except Exception as erro:
    print("ERRO:", type(erro).__name__)
    print(str(erro))
