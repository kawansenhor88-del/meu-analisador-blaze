import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# CONFIGURAÇÃO
# ============================================================

TOKEN = os.getenv("TIPMINER_TOKEN")

URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

PARAMS = {
    "timezone": "America/Sao_Paulo",
    "subject": "filter",
    "limit": 2000,
}

HEADERS = {
    "accept": "*/*",
    "accept-language": "pt-BR",
    "content-type": "application/json",
    "origin": "https://www.tipminer.com",
    "referer": "https://www.tipminer.com/",
    "user-agent": "Mozilla/5.0",
}


# ============================================================
# CONVERTER HORÁRIO
# ============================================================

def converter_horario(instant):
    try:
        dt = datetime.fromisoformat(
            instant.replace("Z", "+00:00")
        )

        dt = dt.astimezone(
            ZoneInfo("America/Sao_Paulo")
        )

        return dt.strftime("%d/%m/%Y %H:%M:%S.%f")[:-3]

    except Exception:
        return instant


# ============================================================
# BUSCAR HISTÓRICO
# ============================================================

def buscar_historico():

    if not TOKEN:
        print("ERRO: TIPMINER_TOKEN não está configurado.")
        return None

    headers = HEADERS.copy()
    headers["authorization"] = f"Bearer {TOKEN}"

    print("=" * 60)
    print("TESTE DO BOT - TIPMINER HISTORY")
    print("=" * 60)

    print("Solicitando 2.000 rodadas...")

    try:
        resposta = requests.get(
            URL,
            params=PARAMS,
            headers=headers,
            timeout=30
        )

    except requests.RequestException as erro:
        print("ERRO DE CONEXÃO:")
        print(erro)
        return None

    print("Status HTTP:", resposta.status_code)

    if resposta.status_code != 200:
        print("API retornou erro:")
        print(resposta.text[:2000])
        return None

    try:
        dados = resposta.json()

    except ValueError:
        print("ERRO: resposta não é JSON.")
        return None

    if isinstance(dados, list):
        return dados

    if isinstance(dados, dict):

        for chave, valor in dados.items():

            if isinstance(valor, list):
                print("Lista encontrada em:", chave)
                return valor

    print("Não encontrei a lista de rodadas.")
    return None


# ============================================================
# MOSTRAR RODADAS
# ============================================================

def mostrar_rodadas(rodadas):

    total = len(rodadas)

    print()
    print("=" * 60)
    print("TOTAL RECEBIDO:", total)
    print("=" * 60)

    if total == 0:
        print("Nenhuma rodada recebida.")
        return

    # --------------------------------------------------------
    # 10 MAIS RECENTES
    # --------------------------------------------------------

    primeiras = rodadas[:10]

    print()
    print("🔵 10 PRIMEIRAS RODADAS — MAIS RECENTES")
    print("-" * 60)

    for posicao, rodada in enumerate(primeiras):

        numero = rodada.get("result")
        horario = rodada.get("instant")

        print(
            f"Posição {posicao} | "
            f"Número: {numero} | "
            f"Horário: {converter_horario(horario)}"
        )

    # --------------------------------------------------------
    # 10 MAIS ANTIGAS
    # --------------------------------------------------------

    ultimas = rodadas[-10:]

    inicio = total - 10

    print()
    print("🟤 10 ÚLTIMAS RODADAS — MAIS ANTIGAS")
    print("-" * 60)

    for indice, rodada in enumerate(ultimas):

        posicao = inicio + indice

        numero = rodada.get("result")
        horario = rodada.get("instant")

        print(
            f"Posição {posicao} | "
            f"Número: {numero} | "
            f"Horário: {converter_horario(horario)}"
        )

    print()
    print("=" * 60)
    print("TESTE FINALIZADO")
    print("=" * 60)


# ============================================================
# EXECUÇÃO
# ============================================================

def main():

    rodadas = buscar_historico()

    if rodadas is None:
        return

    mostrar_rodadas(rodadas)


if __name__ == "__main__":
    main()
