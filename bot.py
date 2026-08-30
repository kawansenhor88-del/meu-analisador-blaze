import requests

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

params = {
    "limit": 400,
    "subject": "filter",
    "isLoadMore": "true",
    "timezone": "America/Sao_Paulo",
}

headers = {
    "Accept": "*/*",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.tipminer.com",
    "Referer": "https://www.tipminer.com/",
}

print("========================================")
print("TESTE HISTÓRICO TIPMINER")
print("========================================")

try:
    resposta = requests.get(
        URL,
        params=params,
        headers=headers,
        timeout=30
    )

    print("STATUS:", resposta.status_code)
    print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))
    print()

    resposta.raise_for_status()

    dados = resposta.json()

    print("TIPO DA RESPOSTA:", type(dados).__name__)

    if isinstance(dados, list):
        rodadas = dados

    elif isinstance(dados, dict):
        print("CHAVES:", list(dados.keys()))

        rodadas = (
            dados.get("data")
            or dados.get("rounds")
            or dados.get("results")
            or []
        )

    else:
        rodadas = []

    print("========================================")
    print("RODADAS RECEBIDAS:", len(rodadas))
    print("========================================")

    if rodadas:
        print("\nPRIMEIRO REGISTRO:")
        print(rodadas[0])

        print("\nÚLTIMO REGISTRO:")
        print(rodadas[-1])

    else:
        print("❌ Nenhuma rodada encontrada.")
        print("\nRESPOSTA BRUTA:")
        print(resposta.text[:5000])

except Exception as erro:
    print("========================================")
    print("❌ ERRO")
    print(type(erro).__name__)
    print(str(erro))
    print("========================================")
