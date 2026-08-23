import os
import json
import traceback
from datetime import datetime

import requests
import telebot
from flask import Flask, request
from google import genai
from google.genai import types


# =========================================================
# CONFIGURAÇÕES
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("ERRO: variável TELEGRAM_TOKEN não configurada.")

if not GEMINI_KEY:
    raise RuntimeError("ERRO: variável GEMINI_KEY não configurada.")


# =========================================================
# TELEGRAM
# =========================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)


# =========================================================
# GEMINI
# =========================================================

client = genai.Client(api_key=GEMINI_KEY)


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


# =========================================================
# BUSCAR HISTÓRICO
# =========================================================

def puxar_dados_blaze():

    url = "https://blaze1.space"

    try:

        print("BUSCANDO DADOS DA BLAZE...")

        resposta = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        print("STATUS BLAZE:", resposta.status_code)

        resposta.raise_for_status()

        dados = resposta.json()

        if not isinstance(dados, list):
            raise ValueError(
                f"Formato inesperado recebido da Blaze: "
                f"{type(dados).__name__}"
            )

        historico = []

        for rodada in dados:

            try:

                created_at = rodada.get("created_at")
                color = rodada.get("color")
                roll = rodada.get("roll")

                if not created_at:
                    continue

                data_bruta = created_at.split(".")[0].replace("Z", "")

                dt = datetime.strptime(
                    data_bruta,
                    "%Y-%m-%dT%H:%M:%S"
                )

                horario_formatado = dt.strftime("%H:%M:%S")

                if color == 0:
                    cor = "Branco"

                elif color == 1:
                    cor = "Vermelho"

                elif color == 2:
                    cor = "Preto"

                else:
                    cor = f"Desconhecido ({color})"

                historico.append({
                    "tempo": horario_formatado,
                    "resultado": cor,
                    "numero": roll
                })

            except Exception as erro_rodada:

                print(
                    "ERRO AO PROCESSAR RODADA:",
                    erro_rodada
                )

                continue

        print(
            "RODADAS PROCESSADAS:",
            len(historico)
        )

        return json.dumps(
            historico,
            ensure_ascii=False
        )

    except Exception as erro:

        print("========================================")
        print("ERRO AO BUSCAR DADOS DA BLAZE")
        print("========================================")
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))

        traceback.print_exc()

        return json.dumps(
            {
                "erro": "Não foi possível obter o histórico.",
                "detalhes": str(erro)
            },
            ensure_ascii=False
        )


# =========================================================
# COMANDO /START
# =========================================================

@bot.message_handler(commands=["start"])
def iniciar(message):

    print("COMANDO /START RECEBIDO")

    bot.reply_to(
        message,
        "🤖 Bot online!\n\n"
        "Envie uma pergunta sobre o histórico disponível."
    )


# =========================================================
# RECEBER MENSAGENS
# =========================================================

@bot.message_handler(func=lambda message: True)
def responder_usuario(message):

    print("========================================")
    print("NOVA MENSAGEM RECEBIDA")
    print("USUÁRIO:", message.from_user.id)
    print("MENSAGEM:", message.text)
    print("========================================")

    try:

        pergunta_usuario = message.text or ""

        # =================================================
        # TESTE SIMPLES
        # =================================================

        if pergunta_usuario.strip().upper() == "TESTE 123":

            bot.reply_to(
                message,
                "✅ Telegram → Render → Bot está funcionando."
            )

            print(
                "TESTE 123 RESPONDIDO COM SUCESSO"
            )

            return

        # =================================================
        # BUSCAR HISTÓRICO
        # =================================================

        dados_blaze = puxar_dados_blaze()

        # =================================================
        # INSTRUÇÃO PARA IA
        # =================================================

        instrucao_ia = """
Você é um interpretador estatístico estrito.

Analise somente o histórico JSON fornecido.

Cada rodada possui:
- tempo
- resultado
- numero

Sua função é responder perguntas sobre os dados que realmente
aparecem no histórico.

Você pode informar:
- quantidade de rodadas;
- contagens de cada resultado;
- horários existentes;
- sequências observadas;
- maior sequência encontrada;
- menor sequência;
- frequências;
- distribuição dos resultados;
- outras estatísticas matemáticas diretamente calculáveis
  a partir do histórico fornecido.

REGRAS IMPORTANTES:

1. Nunca invente dados.
2. Nunca invente horários.
3. Nunca diga que um resultado futuro é garantido.
4. Nunca faça previsão do próximo resultado.
5. Nunca forneça palpite de aposta.
6. Nunca forneça estratégia de aposta.
7. Nunca forneça gerenciamento de banca.
8. Se os dados forem insuficientes, diga claramente.
9. Responda em português.
10. Seja direto e matemático.
"""

        conteudo_envio = (
            "HISTÓRICO RECENTE:\n"
            f"{dados_blaze}\n\n"
            "PERGUNTA DO USUÁRIO:\n"
            f"{pergunta_usuario}"
        )

        print(
            "ENVIANDO DADOS PARA GEMINI..."
        )

        # =================================================
        # GEMINI
        # =================================================

        resposta_gemini = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=conteudo_envio,
            config=types.GenerateContentConfig(
                system_instruction=instrucao_ia,
                temperature=0.1
            )
        )

        texto_resposta = resposta_gemini.text

        if not texto_resposta:

            raise RuntimeError(
                "Gemini retornou uma resposta vazia."
            )

        print(
            "GEMINI RESPONDEU COM SUCESSO"
        )

        bot.reply_to(
            message,
            texto_resposta
        )

        print(
            "RESPOSTA ENVIADA AO TELEGRAM"
        )

    except Exception as erro:

        print("========================================")
        print("ERRO AO PROCESSAR MENSAGEM")
        print("========================================")

        print(
            "TIPO:",
            type(erro).__name__
        )

        print(
            "ERRO:",
            str(erro)
        )

        traceback.print_exc()

        print("========================================")

        # =================================================
        # MOSTRAR ERRO REAL NO TELEGRAM
        # =================================================

        try:

            bot.reply_to(
                message,
                "❌ ERRO REAL:\n\n"
                f"{type(erro).__name__}: "
                f"{str(erro)[:300]}"
            )

        except Exception:

            print(
                "ERRO AO ENVIAR MENSAGEM "
                "DE ERRO AO TELEGRAM"
            )

            traceback.print_exc()


# =========================================================
# WEBHOOK DO TELEGRAM
# =========================================================

@app.route(
    "/" + TELEGRAM_TOKEN,
    methods=["POST"]
)
def receber_webhook():

    try:

        json_string = request.get_data().decode(
            "utf-8"
        )

        update = telebot.types.Update.de_json(
            json_string
        )

        bot.process_new_updates(
            [update]
        )

        return "OK", 200

    except Exception as erro:

        print("========================================")
        print("ERRO NO WEBHOOK")
        print("========================================")

        print(
            "TIPO:",
            type(erro).__name__
        )

        print(
            "ERRO:",
            str(erro)
        )

        traceback.print_exc()

        return "ERROR", 500


# =========================================================
# ROTA PRINCIPAL
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return "Bot Online!", 200


# =========================================================
# INICIALIZAÇÃO
# =========================================================

if __name__ == "__main__":

    porta = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    hostname = os.environ.get(
        "RENDER_EXTERNAL_HOSTNAME"
    )

    if not hostname:

        raise RuntimeError(
            "RENDER_EXTERNAL_HOSTNAME não encontrado."
        )

    webhook_url = (
        f"https://{hostname}/{TELEGRAM_TOKEN}"
    )

    print("========================================")
    print("CONFIGURANDO WEBHOOK")
    print("========================================")

    print(
        "URL:",
        webhook_url
    )

    try:

        bot.remove_webhook()

        bot.set_webhook(
            url=webhook_url
        )

        print(
            "WEBHOOK CONFIGURADO COM SUCESSO"
        )

    except Exception as erro:

        print(
            "ERRO AO CONFIGURAR WEBHOOK"
        )

        print(
            "TIPO:",
            type(erro).__name__
        )

        print(
            "ERRO:",
            str(erro)
        )

        traceback.print_exc()

    print("========================================")
    print("BOT INICIANDO...")
    print("PORTA:", porta)
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=porta
        )
