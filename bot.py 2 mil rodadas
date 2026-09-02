import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request

# ============================================================
# CONFIGURAÇÕES
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TIPMINER_TOKEN = os.getenv("TIPMINER_TOKEN")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

TIPMINER_URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

TIPMINER_PARAMS = {
    "timezone": "America/Sao_Paulo",
    "subject": "filter",
    "limit": 5000,
}

app = Flask(__name__)


# ============================================================
# CONVERTER HORÁRIO
# ============================================================

def converter_horario(instant):
    try:
        data = datetime.fromisoformat(
            instant.replace("Z", "+00:00")
        )

        data = data.astimezone(
            ZoneInfo("America/Sao_Paulo")
        )

        return data.strftime("%d/%m/%Y %H:%M:%S.%f")[:-3]

    except Exception:
        return str(instant)


# ============================================================
# BUSCAR 2.000 RODADAS
# ============================================================

def buscar_historico():

    headers = {
        "accept": "*/*",
        "accept-language": "pt-BR",
        "content-type": "application/json",
        "authorization": f"Bearer {TIPMINER_TOKEN}",
        "origin": "https://www.tipminer.com",
        "referer": "https://www.tipminer.com/",
        "user-agent": "Mozilla/5.0",
    }

    try:
        resposta = requests.get(
            TIPMINER_URL,
            params=TIPMINER_PARAMS,
            headers=headers,
            timeout=30
        )

        print("TipMiner HTTP:", resposta.status_code)

        resposta.raise_for_status()

        dados = resposta.json()

    except Exception as erro:
        print("Erro ao consultar TipMiner:", erro)
        return None

    if isinstance(dados, list):
        return dados

    if isinstance(dados, dict):

        for valor in dados.values():

            if isinstance(valor, list):
                return valor

    return None


# ============================================================
# ENVIAR MENSAGEM TELEGRAM
# ============================================================

def enviar_telegram(chat_id, texto):

    try:
        resposta = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": texto
            },
            timeout=20
        )

        print("Telegram HTTP:", resposta.status_code)

    except Exception as erro:
        print("Erro Telegram:", erro)


# ============================================================
# FORMATAR RODADAS
# ============================================================

def formatar_rodada(posicao, rodada):

    numero = rodada.get("result", "?")
    instant = rodada.get("instant", "?")

    horario = converter_horario(instant)

    return (
        f"Posição {posicao}\n"
        f"Número: {numero}\n"
        f"Horário: {horario}\n"
    )


# ============================================================
# COMANDO /HISTORY
# ============================================================

def processar_history(chat_id):

    enviar_telegram(
        chat_id,
        "🔎 Buscando histórico do TipMiner...\n"
        "Aguarde."
    )

    rodadas = buscar_historico()

    if not rodadas:

        enviar_telegram(
            chat_id,
            "❌ Não consegui obter o histórico do TipMiner."
        )

        return

    total = len(rodadas)

    print("Rodadas recebidas:", total)

    # --------------------------------------------------------
    # 10 MAIS RECENTES
    # --------------------------------------------------------

    mensagem_recentes = (
        "🔵 10 RODADAS MAIS RECENTES\n"
        f"Total recebido pela API: {total}\n\n"
    )

    for posicao in range(min(10, total)):

        mensagem_recentes += formatar_rodada(
            posicao,
            rodadas[posicao]
        )

        mensagem_recentes += "\n"

    # --------------------------------------------------------
    # 10 MAIS ANTIGAS
    # --------------------------------------------------------

    mensagem_antigas = (
        "🟤 10 RODADAS MAIS ANTIGAS\n\n"
    )

    inicio = max(0, total - 10)

    for posicao in range(inicio, total):

        mensagem_antigas += formatar_rodada(
            posicao,
            rodadas[posicao]
        )

        mensagem_antigas += "\n"

    # --------------------------------------------------------
    # ENVIAR
    # --------------------------------------------------------

    enviar_telegram(
        chat_id,
        mensagem_recentes
    )

    enviar_telegram(
        chat_id,
        mensagem_antigas
    )


# ============================================================
# WEBHOOK TELEGRAM
# ============================================================

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():

    try:
        update = request.get_json()

        if not update:
            return "OK", 200

        mensagem = update.get("message")

        if not mensagem:
            return "OK", 200

        chat = mensagem.get("chat")

        if not chat:
            return "OK", 200

        chat_id = chat.get("id")

        texto = mensagem.get("text", "").strip()

        print(
            f"Mensagem recebida: {texto} | "
            f"Chat: {chat_id}"
        )

        if texto.lower() == "/history":

            processar_history(chat_id)

        elif texto.lower() == "/start":

            enviar_telegram(
                chat_id,
                "🤖 Bot de teste TipMiner ativo!\n\n"
                "Use /history para consultar "
                "as 2.000 rodadas e receber:\n\n"
                "🔵 10 mais recentes\n"
                "🟤 10 mais antigas"
            )

        return "OK", 200

    except Exception as erro:

        print("Erro no webhook:", erro)

        return "OK", 200


# ============================================================
# ROTA DE TESTE
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return "TIPMINER TELEGRAM TEST OK", 200


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == "__main__":

    if not TELEGRAM_TOKEN:
        print("ERRO: TELEGRAM_TOKEN não configurado.")

    if not TIPMINER_TOKEN:
        print("ERRO: TIPMINER_TOKEN não configurado.")

    porta = int(
        os.getenv("PORT", "10000")
    )

    print("=" * 60)
    print("TIPMINER TELEGRAM TEST")
    print("=" * 60)
    print("History: 2000")
    print("Telegram: SIM" if TELEGRAM_TOKEN else "Telegram: NÃO")
    print("TipMiner Token: SIM" if TIPMINER_TOKEN else "TipMiner Token: NÃO")
    print("Porta:", porta)

    app.run(
        host="0.0.0.0",
        port=porta
        )
