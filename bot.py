import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

PORT = int(os.getenv("PORT", "10000"))

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/live"


def testar_tipminer():

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
            timeout=60
        )

        print("STATUS:", resposta.status_code)
        print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))

        resposta.raise_for_status()

        dados = resposta.json()

        print("RESPONSE TYPE:", type(dados).__name__)

        if isinstance(dados, list):

            print("ROUNDS RECEIVED:", len(dados))

            if len(dados) > 0:

                print("")
                print("FIRST RECORD:")
                print(dados[0])

                print("")
                print("LAST RECORD:")
                print(dados[-1])

            print("")
            print("========================================")

            if len(dados) == 400:
                print("SUCCESS: 400 ROUNDS RECEIVED")
            else:
                print("RECEIVED:", len(dados), "ROUNDS")

            print("========================================")

        else:
            print("ERROR: RESPONSE IS NOT A LIST")
            print(dados)

    except Exception as erro:

        print("========================================")
        print("FAILED")
        print("ERROR TYPE:", type(erro).__name__)
        print("ERROR:", str(erro))
        print("========================================")


@app.route("/")
def home():
    return "TIPMINER TEST ONLINE", 200


if __name__ == "__main__":

    print("========================================")
    print("STARTING TIPMINER TEST")
    print("PORT:", PORT)
    print("========================================")

    thread = threading.Thread(
        target=testar_tipminer,
        daemon=True
    )

    thread.start()

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
                     )
