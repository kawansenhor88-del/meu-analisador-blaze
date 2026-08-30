import requests
import time

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/live"

print("========================================")
print("TIPMINER HISTORICAL TEST")
print("========================================")

try:
    resposta = requests.get(
        URL,
        params={
            "limit": 400,
            "subject": "filter",
            "isLoadMore": "true",
            "t": int(time.time() * 1000),
            "timezone": "America/Sao_Paulo",
            "_cb": str(time.time())
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        },
        timeout=30
    )

    print("STATUS:", resposta.status_code)
    print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))

    resposta.raise_for_status()

    dados = resposta.json()

    print("RESPONSE TYPE:", type(dados).__name__)

    if isinstance(dados, list):
        print("Rounds received:", len(dados))

        if len(dados) > 0:
            print("")
            print("FIRST RECORD:")
            print(dados[0])

            print("")
            print("LAST RECORD:")
            print(dados[-1])

        if len(dados) == 400:
            print("")
            print("SUCCESS: 400 ROUNDS RECEIVED")
        else:
            print("")
            print("RECEIVED:", len(dados), "ROUNDS")

    else:
        print("ERROR: RESPONSE IS NOT A LIST")
        print(dados)

except Exception as erro:
    print("========================================")
    print("FAILED")
    print("ERROR TYPE:", type(erro).__name__)
    print("ERROR:", str(erro))
    print("========================================")

print("TEST FINISHED")
