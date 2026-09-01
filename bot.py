import requests
import json

# ============================================================
# TESTE: TIPMINER HISTORY + TIMEZONE
# ============================================================

URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

PARAMS = {
    "timezone": "America/Sao_Paulo",
    "subject": "filter",
    "limit": 2000,
}

# COLOQUE SEU TOKEN AQUI NO SEU COMPUTADOR
TOKEN = "COLE_SEU_BEARER_TOKEN_AQUI"

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "authorization": f"Bearer {TOKEN}",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
}


def main():
    print("========================================")
    print(" TESTE TIPMINER HISTORY + TIMEZONE")
    print("========================================")
    print("Solicitando: limit=2000")
    print()

    try:
        resposta = requests.get(
            URL,
            params=PARAMS,
            headers=HEADERS,
            timeout=30
        )

        print("Status HTTP:", resposta.status_code)
        print("URL consultada:")
        print(resposta.url)
        print()

        resposta.raise_for_status()

        dados = resposta.json()

        print("Tipo da resposta:", type(dados).__name__)

        # Descobrir onde está a lista de rodadas
        if isinstance(dados, list):
            rodadas = dados

        elif isinstance(dados, dict):
            print("Chaves principais da resposta:")
            print(list(dados.keys()))

            # Tenta encontrar automaticamente uma lista
            rodadas = None

            for chave, valor in dados.items():
                if isinstance(valor, list):
                    rodadas = valor
                    print(f"Lista encontrada na chave: {chave}")
                    break

            if rodadas is None:
                print("\nNão encontrei uma lista de rodadas automaticamente.")
                print(json.dumps(dados, indent=2, ensure_ascii=False)[:5000])
                return

        else:
            print("Formato inesperado.")
            return

        print()
        print("========================================")
        print(" RESULTADO")
        print("========================================")
        print("Quantidade de rodadas recebidas:", len(rodadas))
        print()

        if len(rodadas) == 0:
            print("A API retornou ZERO rodadas.")
            return

        # Primeira rodada
        print("----- PRIMEIRA RODADA [posição 0] -----")
        print(json.dumps(
            rodadas[0],
            indent=2,
            ensure_ascii=False
        ))

        print()

        # Última rodada
        print("----- ÚLTIMA RODADA [posição", len(rodadas) - 1, "] -----")
        print(json.dumps(
            rodadas[-1],
            indent=2,
            ensure_ascii=False
        ))

        print()
        print("========================================")
        print(" TESTE FINALIZADO")
        print("========================================")


if __name__ == "__main__":
    main()
