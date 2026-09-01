import os
import requests


URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

PARAMS = {
    "timezone": "America/Sao_Paulo",
    "subject": "filter",
    "limit": 2000,
}

TOKEN = os.getenv("TIPMINER_TOKEN")

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
    "user-agent": "Mozilla/5.0",
}


def main():
    print("=" * 50)
    print("TIPMINER TESTE HISTORY TIMEZONE")
    print("=" * 50)

    if not TOKEN:
        print("ERRO: TIPMINER_TOKEN não configurado.")
        return

    HEADERS["authorization"] = f"Bearer {TOKEN}"

    try:
        resposta = requests.get(
            URL,
            params=PARAMS,
            headers=HEADERS,
            timeout=30
        )

        print("Status HTTP:", resposta.status_code)
        print("URL:", resposta.url)

        resposta.raise_for_status()

        dados = resposta.json()

    except Exception as erro:
        print("ERRO:")
        print(erro)
        return

    print()
    print("Tipo recebido:", type(dados).__name__)

    if isinstance(dados, list):
        rodadas = dados

    elif isinstance(dados, dict):

        rodadas = None

        for chave, valor in dados.items():

            if isinstance(valor, list):
                rodadas = valor
                print("Lista encontrada em:", chave)
                break

        if rodadas is None:
            print("Não encontrei a lista de rodadas.")
            print(dados)
            return

    else:
        print("Formato desconhecido.")
        print(dados)
        return

    print()
    print("=" * 50)
    print("RESULTADO")
    print("=" * 50)

    print("QUANTIDADE DE RODADAS:", len(rodadas))

    if len(rodadas) > 0:

        print()
        print("PRIMEIRA RODADA:")
        print(rodadas[0])

        print()
        print("ÚLTIMA RODADA:")
        print(rodadas[-1])

        print()
        print("PRIMEIRA POSIÇÃO: 0")
        print("ÚLTIMA POSIÇÃO:", len(rodadas) - 1)

    print()
    print("=" * 50)
    print("TESTE FINALIZADO")
    print("=" * 50)


if __name__ == "__main__":
    main()
