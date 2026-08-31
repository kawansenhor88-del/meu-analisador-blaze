import os
import requests

TOKEN = os.environ["TIPMINER_TOKEN"]

URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/"
    "history"
)

headers = {
    "Accept": "*/*",
    "Authorization": f"Bearer {TOKEN}",
    "Origin": "https://www.tipminer.com",
    "Referer": "https://www.tipminer.com/",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 "
        "Mobile Safari/537.36"
    ),
}

params = {
    "limit": 5000,
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo",
}

r = requests.get(
    URL,
    headers=headers,
    params=params,
    timeout=30
)

print("STATUS:", r.status_code)

dados = r.json()

if isinstance(dados, list):
    rodadas = dados
elif isinstance(dados, dict):
    rodadas = (
        dados.get("data")
        or dados.get("rounds")
        or dados.get("results")
        or []
    )
else:
    rodadas = []

print("RODADAS RECEBIDAS:", len(rodadas))

if len(rodadas) == 2000:
    print("🔥 CONSEGUIMOS AS 2.000!")
elif len(rodadas) > 200:
    print("✅ A autenticação aumentou o histórico:", len(rodadas))
else:
    print("⚠️ Ainda retornou apenas:", len(rodadas))
