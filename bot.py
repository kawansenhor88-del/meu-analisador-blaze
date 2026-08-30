import requests
import json

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/live"

PARAMS = {
    "limit": "400",
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo"
}

print("========================================")
print("TIPMINER HISTORICAL TEST")
print("========================================")

try:
    response = requests.get(
        URL,
        params=PARAMS,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        },
        timeout=30
    )

    print("STATUS:", response.status_code)
    print("CONTENT-TYPE:", response.headers.get("Content-Type"))

    response.raise_for_status()

    data = response.json()

    print("RESPONSE TYPE:", type(data).__name__)
    print("ROUNDS RECEIVED:", len(data))

    print("")
    print("========================================")
    print("POSITIONS 0, 99, 100, 199, 200, 299, 300, 399")
    print("========================================")

    for position in [0, 99, 100, 199, 200, 299, 399]:
        if position < len(data):
            print("")
            print("POSITION:", position)
            print(json.dumps(data[position], ensure_ascii=False))

    print("")
    print("========================================")
    print("FIRST RECORD")
    print("========================================")

    print(json.dumps(data[0], ensure_ascii=False))

    print("")
    print("========================================")
    print("LAST RECORD")
    print("========================================")

    print(json.dumps(data[-1], ensure_ascii=False))

except Exception as error:
    print("")
    print("========================================")
    print("ERROR")
    print("========================================")
    print(type(error).__name__)
    print(str(error))
