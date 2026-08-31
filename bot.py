import os
import requests

TOKEN = os.getenv("TIPMINER_TOKEN")

url = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

params = {
    "limit": 1000,
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo",
}

headers = {
    "accept": "*/*",
    "authorization": f"Bearer {TOKEN}",
    "content-type": "application/json",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
}

resposta = requests.get(
    url,
    params=params,
    headers=headers,
    timeout=30
)

print("STATUS:", resposta.status_code)

dados = resposta.json()

print("TIPO:", type(dados).__name__)
print("REGISTROS RECEBIDOS:", len(dados))
