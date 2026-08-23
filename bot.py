import os
import json
from datetime import datetime

import requests
import telebot
from flask import Flask, request
from google import genai
from google.genai import types


# ============================================================
# CONFIGURAÇÕES
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.environ.get("PORT", 10000))

if not TELEGRAM_TOKEN:
    raise RuntimeError("A variável TELEGRAM_TOKEN não foi configurada.")

if not GEMINI_KEY:
    raise RuntimeError("A variável GEMINI_KEY não foi configurada.")


# ============================================================
# TELEGRAM
# ============================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)


# ============================================================
# GEMINI - NOVA SDK
# ============================================================

client = genai.Client(api_key=GEMINI_KEY)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# BUSCAR DADOS DA BLAZE
# ============================================================

def puxar_dados_blaze():
    url = "https://blaze1.space"

    try:
        resposta = requests.get(url, timeout=10)
        resposta.raise_for_status()

        dados = resposta.json()

        historico = []

        for rodada in dados:
            try:
                data_bruta = rodada["created_at"].split(".")[0]

                dt = datetime.strptime(
                    data_bruta,
                    "%Y-%m-%dT%H:%M:%S"
                )

                horario_formatado = dt.strftime("%H:%M:%S")

                cor = (
                    "Branco"
                    if rodada["color"] == 0
                    else "Vermelho"
                    if rodada["color"] == 1
                    else "Preto"
                )

                historico.append({
                    "tempo": horario_formatado,
                    "resultado": cor,
                    "numero": rodada["roll"]
                })

            except (KeyError, ValueError, TypeError):
                continue

        return json.dumps(
            historico,
            ensure_ascii=False
        )

    except requests.RequestException as erro:
        print(f"Erro ao acessar dados da Blaze: {erro}")
        return "Erro ao conectar com os dados da Blaze."

    except ValueError as erro:
        print(f"Erro ao interpretar JSON da Blaze: {erro}")
        return "Erro ao interpretar os dados recebidos."


# ============================================================
# TELEGRAM - RECEBER MENSAGENS
# ============================================================

@bot.message_handler(func=lambda message: True)
def responder_usuario(message):

    if not message.text:
        return

    try:
        pergunta_usuario = message.text

        print(f"Mensagem recebida: {pergunta_usuario}")

        dados_blaze = puxar_dados_blaze()

        instrucao_ia = """
Você é um interpretador estatístico estrito.

Analise exclusivamente o histórico JSON fornecido.

Cada rodada possui:
- "tempo": horário da rodada
- "resultado": cor da rodada
- "numero": número obtido

Sua função é responder perguntas estatísticas sobre os dados fornecidos.

Responda somente com informações que possam ser obtidas matematicamente
a partir do histórico.

Você pode informar:
- contagens;
- frequências;
- sequências;
- sequência máxima;
- horários dos registros;
- distribuição das cores;
- números presentes no histórico;
- comparações matemáticas entre os dados.

É EXPRESSAMENTE PROIBIDO:
- dar palpites de apostas;
- prever o próximo resultado;
- recomendar cor para apostar;
- indicar entradas;
- sugerir estratégias de aposta;
- sugerir gerenciamento de banca;
- afirmar que um resultado futuro é provável.

Se os dados não forem suficientes para responder, diga claramente
que os dados fornecidos não são suficientes.

Seja frio, direto e matemático.
"""

        conteudo_envio = (
            "Histórico recente:\n"
            f"{dados_blaze}\n\n"
            "Pergunta do usuário:\n"
            f"{pergunta_usuario}"
        )

        resposta_gemini = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=conteudo_envio,
            config=types.GenerateContentConfig(
                system_instruction=instrucao_ia,
                temperature=0.1,
            ),
        )

        texto_resposta = resposta_gemini.text

        if not texto_resposta:
            texto_resposta = (
                "Não foi possível obter uma resposta do Gemini."
            )

        bot.reply_to(
            message,
            texto_resposta
        )

    except Exception as erro:
        print(f"Erro ao processar mensagem: {erro}")

        bot.reply_to(
            message,
            "Ocorreu um erro ao processar sua solicitação. "
            "Tente novamente em alguns segundos."
        )


# ============================================================
# WEBHOOK DO TELEGRAM
# ============================================================

@app.route("/" + TELEGRAM_TOKEN, methods=["POST"])
def receber_webhook():

    try:
        json_string = request.get_data().decode("utf-8")

        update = telebot.types.Update.de_json(
            json_string
        )

        bot.process_new_updates([update])

        return "OK", 200

    except Exception as erro:
        print(f"Erro no webhook: {erro}")
        return "Erro", 500


# ============================================================
# PÁGINA PRINCIPAL / HEALTH CHECK
# ============================================================

@app.route("/")
def home():
    return "Bot Online!", 200


# ============================================================
# CONFIGURAR WEBHOOK
# ============================================================

def configurar_webhook():

    if not RENDER_HOSTNAME:
        print(
            "RENDER_EXTERNAL_HOSTNAME não encontrado. "
            "Webhook não configurado."
        )
        return

    url_webhook = (
        f"https://{RENDER_HOSTNAME}/{TELEGRAM_TOKEN}"
    )

    try:
        bot.remove_webhook()
        bot.set_webhook(url=url_webhook)

        print("==========================================")
        print("WEBHOOK CONFIGURADO COM SUCESSO")
        print(f"URL: https://{RENDER_HOSTNAME}")
        print("==========================================")

    except Exception as erro:
        print(f"Erro ao configurar webhook: {erro}")


# ============================================================
# INICIAR SERVIDOR
# ============================================================

if __name__ == "__main__":

    configurar_webhook()

    print("==========================================")
    print("BOT INICIANDO...")
    print(f"PORTA: {PORT}")
    print("==========================================")

    app.run(
        host="0.0.0.0",
        port=PORT
    )
