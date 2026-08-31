import requests
import json

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

PARAMS = {
    "limit": 1000,
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo"
}

HEADERS = {
    "Accept": "*/*",
    "Origin": "https://www.tipminer.com",
    "Referer": "https://www.tipminer.com/",
    "User-Agent": "Mozilla/5.0"
}

print("======================================")
print("TIPMINER HISTORICAL TEST")
print("======================================")

try:
    response = requests.get(
        URL,
        params=PARAMS,
        headers=HEADERS,
        timeout=30
    )

    print("STATUS:", response.status_code)
    print("CONTENT-TYPE:", response.headers.get("content-type"))

    response.raise_for_status()

    data = response.json()

    print("RESPONSE TYPE:", type(data).__name__)
    print("ROUNDS RECEIVED:", len(data))

    print("")
    print("======================================")
    print("CHECKING BLOCKS")
    print("======================================")

    positions = [
        0, 99,
        100, 199,
        200, 299,
        300, 399,
        400, 499,
        500, 599,
        600, 699,
        700, 799,
        800, 899,
        900, 999
    ]

    for pos in positions:
        if pos < len(data):
            rodada = data[pos]

            print("")
            print("POSITION:", pos)
            print("UUID:", rodada.get("uuid"))
            print("TYPE:", rodada.get("type"))
            print("RESULT:", rodada.get("result"))
            print("INSTANT:", rodada.get("instant"))

    print("")
    print("======================================")
    print("FINAL RESULT")
    print("======================================")

    if len(data) == 1000:
        print("SUCCESS!")
        print("1000 ROUNDS RECEIVED CORRECTLY.")
    else:
        print("WARNING!")
        print("EXPECTED: 1000")
        print("RECEIVED:", len(data))

except Exception as erro:
    print("")
    print("======================================")
    print("ERROR")
    print("======================================")
    print(type(erro).__name__)
    print(str(erro))
