import requests
import traceback

TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/"
    "history"
)

def testar_historico_tipminer():

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://tipminer.com",
        "Referer": "https://tipminer.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    params = {
        "limit": 5000,
        "subject": "filter",
        "isLoadMore": "true",
        "timezone": "America/Sao_Paulo",
    }

    print("\n========================================")
    print("TESTE TIPMINER - 2.000 RODADAS")
    print("========================================")
    print("Solicitando: limit=5000")
    print("Endpoint: /history")

    try:
        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=30,
        )

        print("Status HTTP:", resposta.status_code)

        if resposta.status_code != 200:
            print("❌ ERRO")
            print(resposta.text[:2000])
            return

        dados = resposta.json()

        # A resposta pode ser uma lista diretamente
        # ou uma lista dentro de algum campo.
        if isinstance(dados, list):
            rodadas = dados

        elif isinstance(dados, dict):
            if isinstance(dados.get("data"), list):
                rodadas = dados["data"]

            elif isinstance(dados.get("rounds"), list):
                rodadas = dados["rounds"]

            elif isinstance(dados.get("results"), list):
                rodadas = dados["results"]

            else:
                print("❌ Não encontrei a lista de rodadas.")
                print("Chaves recebidas:", list(dados.keys()))
                return

        else:
            print("❌ Formato de resposta desconhecido.")
            print(type(dados))
            return

        quantidade = len(rodadas)

        print("----------------------------------------")
        print("RODADAS RECEBIDAS:", quantidade)
        print("----------------------------------------")

        if quantidade == 2000:
            print("🔥🔥🔥 RECEBEU EXATAMENTE 2.000 RODADAS! 🔥🔥🔥")

        elif quantidade > 2000:
            print("🚨 RECEBEU MAIS DE 2.000!")

        else:
            print(
                f"⚠️ Recebeu {quantidade}, "
                "não chegou a 2.000."
            )

        # Mostrar primeira e última
        if rodadas:

            print("\nPRIMEIRA RODADA [posição 0]:")
            print(rodadas[0])

            print("\nÚLTIMA RODADA:")
            print(rodadas[-1])

        print("\n========================================")
        print("FIM DO TESTE")
        print("========================================")

    except requests.exceptions.Timeout:
        print("❌ TIMEOUT")

    except requests.exceptions.RequestException as erro:
        print("❌ ERRO DE CONEXÃO:")
        print(erro)

    except Exception as erro:
        print("❌ ERRO INESPERADO:")
        print(erro)
        traceback.print_exc()


testar_historico_tipminer()
