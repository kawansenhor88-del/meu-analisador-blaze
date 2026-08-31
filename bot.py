import os
import requests

print("================================")
print("TIPMINER TEST 1000 - NOVO")
print("================================")

TOKEN = os.getenv("TIPMINER_AUTH_TOKEN")

print("TOKEN ENCONTRADO:", bool(TOKEN))

if not TOKEN:
    print("ERRO: TIPMINER_AUTH_TOKEN NÃO FOI ENCONTRADO.")
    raise SystemExit(1)

url = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

params = {
    "limit": 1000,
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo",
}

headers = {
    "accept": "*/*",
    "accept-language": "pt-BR",
    "authorization": f"Bearer {TOKEN}",
    "content-type": "application/json",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
}

try:
    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=30
    )

    print("STATUS:", response.status_code)
    print("CONTENT-TYPE:", response.headers.get("content-type"))
    print("TAMANHO:", len(response.content))
    print("RESPOSTA:")
    print(response.text[:1000])

except Exception as e:
    print("ERRO:", repr(e))
    raise

print("================================")
print("TESTE FINALIZADO")
print("================================")
