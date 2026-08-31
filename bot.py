import os
import requests

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

PARAMS = {
    "limit": "1000",
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo"
}

TOKEN = os.getenv("TIPMINER_TOKEN")

HEADERS = {
    "Accept": "*/*",
    "Authorization": f"Bearer {TOKEN}",
    "Origin": "https://www.tipminer.com",
    "Referer": "https://www.tipminer.com/",
    "User-Agent": "Mozilla/5.0"
}

print("================================")
print("TIPMINER TEST 1000")
print("================================")

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

    if len(data) >= 1000:
        print("")
        print("SUCCESS!")
        print("1000 ROUNDS RECEIVED!")

        for pos in [0, 99, 100, 199, 299, 399, 499, 599, 699, 799, 899, 999]:
            r = data[pos]

            print("")
            print("POSITION:", pos)
            print("RESULT:", r.get("result"))
            print("TYPE:", r.get("type"))
            print("INSTANT:", r.get("instant"))

    else:
        print("")
        print("WARNING!")
        print("EXPECTED: 1000")
        print("RECEIVED:", len(data))

except Exception as erro:
    print("")
    print("ERROR:", type(erro).__name__)
    print("DETAIL:", str(erro))
