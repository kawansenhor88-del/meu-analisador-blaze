import requests

url = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

params = {
    "limit": 5000,
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo"
}

r = requests.get(url, params=params, timeout=30)

print("Status:", r.status_code)
print("Quantidade:", len(r.json()))
print("Primeira rodada:", r.json()[0])
