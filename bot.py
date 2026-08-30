import requests
import traceback
from flask import Flask

# ============================================================
# CONFIGURAÇÕES
# ============================================================

PORT = int(__import__("os").environ.get("PORT", "10000"))

TIPMINER_HISTORY_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/"
    "history"
)

app = Flask(__name__)


# ============================================================
# CONVERTER COR
# ============================================================

def mapear_cor(resultado):
    try:
        numero = int(resultado)

        if numero == 0:
            return "⚪ Branco"

        if 1 <= numero <= 7:
            return "🔴 Vermelho"

        if 8 <= numero <= 14:
            return "⚫ Preto"

        return "❓ Desconhecido"

    except Exception:
        return "❓ Desconhecido"


# ============================================================
# TESTE DO HISTÓRICO
# ============================================================

def testar_historico_tipminer(limite=200):

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
        "limit": limite,
        "subject": "filter",
        "isLoadMore": "true",
        "timezone": "America/Sao_Paulo",
    }

    print("\n========================================")
    print("TESTE TIPMINER /HISTORY")
    print("========================================")
    print("Limite solicitado:", limite)
    print("URL:", TIPMINER_HISTORY_URL)

    try:
        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=30,
        )

        print("Status HTTP:", resposta.status_code)

        if resposta.status_code != 200:
            print("❌ API NÃO RETORNOU 200")
            print("Resposta:", resposta.text[:1000])
            return

        try:
            dados = resposta.json()
        except Exception:
            print("❌ A resposta não é JSON válido.")
            print("Resposta:", resposta.text[:1000])
            return

        # ----------------------------------------------------
        # IDENTIFICAR A LISTA DE RODADAS
        # ----------------------------------------------------

        if isinstance(dados, dict):

            if isinstance(dados.get("data"), list):
                rodadas = dados["data"]

            elif isinstance(dados.get("rounds"), list):
                rodadas = dados["rounds"]

            elif isinstance(dados.get("results"), list):
                rodadas = dados["results"]

            else:
                rodadas = []

        elif isinstance(dados, list):
            rodadas = dados

        else:
            rodadas = []

        # ----------------------------------------------------
        # RESULTADO
        # ----------------------------------------------------

        quantidade = len(rodadas)

        print("----------------------------------------")
        print("RODADAS RECEBIDAS:", quantidade)
        print("----------------------------------------")

        if quantidade == 0:
            print("⚠️ Nenhuma rodada encontrada.")
            print("Resposta recebida:")
            print(dados)
            return

        # ----------------------------------------------------
        # PRIMEIRA E ÚLTIMA
        # ----------------------------------------------------

        primeira = rodadas[0]
        ultima = rodadas[-1]

        print("\nPRIMEIRA RODADA:")
        print(primeira)

        print("\nÚLTIMA RODADA:")
        print(ultima)

        # ----------------------------------------------------
        # MOSTRAR AMOSTRA
        # ----------------------------------------------------

        print("\n========================================")
        print("AMOSTRA DAS PRIMEIRAS RODADAS")
        print("========================================")

        for i, rodada in enumerate(rodadas[:10], start=1):

            if not isinstance(rodada, dict):
                print(i, rodada)
                continue

            resultado = (
                rodada.get("result")
                if rodada.get("result") is not None
                else rodada.get("resultado")
            )

            instant = rodada.get("instant", "N/A")
            uuid = rodada.get("uuid", "N/A")

            print(
                f"{i:02d} | "
                f"Resultado: {resultado} | "
                f"Cor: {mapear_cor(resultado)} | "
                f"Instant: {instant} | "
                f"ID: {str(uuid)[:12]}"
            )

        # ----------------------------------------------------
        # CONTAGEM DE CORES
        # ----------------------------------------------------

        brancos = 0
        vermelhos = 0
        pretos = 0

        for rodada in rodadas:

            if not isinstance(rodada, dict):
                continue

            resultado = (
                rodada.get("result")
                if rodada.get("result") is not None
                else rodada.get("resultado")
            )

            try:
                numero = int(resultado)

                if numero == 0:
                    brancos += 1

                elif 1 <= numero <= 7:
                    vermelhos += 1

                elif 8 <= numero <= 14:
                    pretos += 1

            except Exception:
                pass

        print("\n========================================")
        print("RESUMO")
        print("========================================")
        print("Solicitadas:", limite)
        print("Recebidas:", quantidade)
        print("⚪ Brancos:", brancos)
        print("🔴 Vermelhos:", vermelhos)
        print("⚫ Pretos:", pretos)

        if quantidade >= limite:
            print("\n✅ TESTE APROVADO: recebeu o limite solicitado.")
        else:
            print(
                "\n⚠️ TESTE PARCIAL: "
                f"solicitamos {limite}, mas recebemos {quantidade}."
            )

        print("========================================\n")

    except requests.exceptions.Timeout:
        print("❌ TIMEOUT: o TipMiner demorou demais para responder.")

    except requests.exceptions.RequestException as erro:
        print("❌ ERRO DE CONEXÃO COM O TIPMINER:")
        print(erro)

    except Exception as erro:
        print("❌ ERRO INESPERADO:")
        print(erro)
        traceback.print_exc()


# ============================================================
# EXECUTAR TESTE QUANDO O SERVIÇO INICIAR
# ============================================================

print("\n🚀 SERVIÇO DE TESTE INICIANDO...")

testar_historico_tipminer(200)


# ============================================================
# ROTA FLASK
# ============================================================

@app.route("/")
def inicio():
    return "Teste TipMiner ativo."


@app.route("/health")
def health():
    return "OK"


# ============================================================
# SERVIDOR
# ============================================================

if __name__ == "__main__":

    print("========================================")
    print("SERVIDOR FLASK INICIADO")
    print("PORTA:", PORT)
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )
