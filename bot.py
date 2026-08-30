import requests

url = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

params = {
    "limit": 5000,
    "subject": "filter",
    "isLoadMore": "true",
    "t": "1788095997510",
    "timezone": "America/Sao_Paulo",
}

headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.tipminer.com",
    "Referer": "https://www.tipminer.com/",
    "User-Agent": "Mozilla/5.0",
}

r = requests.get(url, params=params, headers=headers, timeout=30)

print("Status:", r.status_code)
print("Tipo:", r.headers.get("content-type"))

if r.ok:
    dados = r.json()
    print("Quantidade:", len(dados))
    print("Primeira rodada:", dados[0])
else:
    print("Resposta:", r.text[:500])
