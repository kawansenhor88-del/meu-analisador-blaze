import requests
import json

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

PARAMS = {
    "limit": 1000,
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo"
}

print("========================================")
print("TIPMINER HISTORICAL TEST - 1000")
print("========================================")

try:
    response = requests.get(
        URL,
        params=PARAMS,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Origin": "https://www.tipminer.com",
            "Referer": "https://www.tipminer.com/"
        },
        timeout=30
    )

    print("STATUS:", response.status_code)
    print("CONTENT-TYPE:", response.headers.get("Content-Type"))

    response.raise_for_status()

    data = response.json()

    print("RESPONSE TYPE:", type(data).__name__)

    if isinstance(data, list):

        print("ROUNDS RECEIVED:", len(data))

        positions = [
            0, 99, 100, 199,
            299, 399, 499, 599,
            699, 799, 899, 999
        ]

        print("")
        print("========================================")
        print("CHECKING POSITIONS")
        print("========================================")

        for position in positions:
            if position < len(data):
                print("")
                print("POSITION:", position)
                print(json.dumps(data[position], ensure_ascii=False))

        print("")
        print("========================================")
        print("FIRST RECORD")
        print("========================================")

        if data:
            print(json.dumps(data[0], ensure_ascii=False))

        print("")
        print("========================================")
        print("LAST RECORD")
        print("========================================")

        if data:
            print(json.dumps(data[-1], ensure_ascii=False))

        print("")
        print("========================================")
        print("FINAL RESULT")
        print("========================================")

        if len(data) >= 1000:
            print("SUCCESS: 1000 ROUNDS RECEIVED")
        else:
            print("ONLY", len(data), "ROUNDS RECEIVED")

    else:
        print("ERROR: RESPONSE IS NOT A LIST")
        print(json.dumps(data, ensure_ascii=False))

except Exception as error:
    print("")
    print("========================================")
    print("ERROR")
    print("========================================")
    print(type(error).__name__)
    print(str(error))
