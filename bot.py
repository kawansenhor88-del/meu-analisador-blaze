import os
import json
import requests


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TIPMINER_TOKEN = os.getenv("TIPMINER_TOKEN")

HISTORY_URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

PARAMS = {
    "timezone": "America/Sao_Paulo",
    "subject": "filter",
    "limit": 2000,
}


# ============================================================
# CABEÇALHOS
# ============================================================

HEADERS = {
    "accept": "*/*",
    "accept-language": "pt-BR",
    "content-type": "application/json",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
    "user-agent": (
        "Mozilla/5.0 (Linux; Android 10; K) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Mobile Safari/537.36"
    ),
}


# ============================================================
# BUSCAR HISTÓRICO
# ============================================================

def buscar_historico():

    if not TIPMINER_TOKEN:
        print("ERRO: variável TIPMINER_TOKEN não configurada.")
        return None

    headers = HEADERS.copy()
    headers["authorization"] = f"Bearer {TIPMINER_TOKEN}"

    print("=" * 60)
    print("TESTE TIPMINER - HISTORY + TIMEZONE")
    print("=" * 60)

    print()
    print("Endpoint:")
    print(HISTORY_URL)

    print()
    print("Parâmetros:")
    print(json.dumps(PARAMS, indent=2, ensure_ascii=False))

    print()
    print("Consultando API...")

    try:
        response = requests.get(
            HISTORY_URL,
            params=PARAMS,
            headers=headers,
            timeout=30
        )

    except requests.RequestException as erro:
        print()
        print("ERRO DE CONEXÃO:")
        print(erro)
        return None

    print()
    print("Status HTTP:", response.status_code)

    if response.status_code != 200:
        print()
        print("A API não retornou HTTP 200.")
        print("Resposta:")
        print(response.text[:5000])
        return None

    try:
        dados = response.json()

    except ValueError:
        print()
        print("ERRO: a resposta não é um JSON válido.")
        print(response.text[:5000])
        return None

    return dados


# ============================================================
# LOCALIZAR LISTA DE RODADAS
# ============================================================

def encontrar_rodadas(dados):

    if isinstance(dados, list):
        return dados

    if isinstance(dados, dict):

        # Possíveis nomes comuns
        possiveis = [
            "data",
            "results",
            "rounds",
            "history",
            "items",
        ]

        for chave in possiveis:

            valor = dados.get(chave)

            if isinstance(valor, list):
                print()
                print("Lista encontrada na chave:", chave)
                return valor

        # Procura qualquer lista dentro do JSON
        for chave, valor in dados.items():

            if isinstance(valor, list):

                print()
                print("Lista encontrada na chave:", chave)
                return valor

    return None


# ============================================================
# EXIBIR RESULTADO
# ============================================================

def mostrar_resultado(dados):

    rodadas = encontrar_rodadas(dados)

    if rodadas is None:

        print()
        print("=" * 60)
        print("NÃO FOI POSSÍVEL LOCALIZAR A LISTA DE RODADAS")
        print("=" * 60)

        print()
        print("Estrutura recebida:")
        print(
            json.dumps(
                dados,
                indent=2,
                ensure_ascii=False
            )[:10000]
        )

        return

    quantidade = len(rodadas)

    print()
    print("=" * 60)
    print("RESULTADO DO TESTE")
    print("=" * 60)

    print()
    print("Rodadas recebidas:", quantidade)

    if quantidade == 0:
        print()
        print("A API retornou zero rodadas.")
        return

    # --------------------------------------------------------
    # PRIMEIRA
    # --------------------------------------------------------

    print()
    print("-" * 60)
    print("PRIMEIRA RODADA")
    print("-" * 60)

    print(
        json.dumps(
            rodadas[0],
            indent=2,
            ensure_ascii=False
        )
    )

    # --------------------------------------------------------
    # ÚLTIMA
    # --------------------------------------------------------

    print()
    print("-" * 60)
    print("ÚLTIMA RODADA")
    print("-" * 60)

    print(
        json.dumps(
            rodadas[-1],
            indent=2,
            ensure_ascii=False
        )
    )

    # --------------------------------------------------------
    # POSIÇÕES
    # --------------------------------------------------------

    print()
    print("-" * 60)
    print("POSIÇÕES")
    print("-" * 60)

    print("Primeira posição:", 0)
    print("Última posição:", quantidade - 1)

    # --------------------------------------------------------
    # CAMPOS DA PRIMEIRA RODADA
    # --------------------------------------------------------

    if isinstance(rodadas[0], dict):

        print()
        print("-" * 60)
        print("CAMPOS ENCONTRADOS")
        print("-" * 60)

        print(
            list(rodadas[0].keys())
        )

    print()
    print("=" * 60)
    print("TESTE FINALIZADO")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

def main():

    dados = buscar_historico()

    if dados is None:
        return

    mostrar_resultado(dados)


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()
