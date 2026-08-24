import os
import json
import traceback
from datetime import datetime, timezone, timedelta

import requests
import telebot
from flask import Flask, request
from google import genai
from google.genai import types


# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

if not TELEGRAM_TOKEN:
    raise RuntimeError("ERRO: variável TELEGRAM_TOKEN não configurada.")

if not GEMINI_KEY:
    raise RuntimeError("ERRO: variável GEMINI_KEY não configurada.")


# ==============================================================================
# TELEGRAM
# ==============================================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)


# ==============================================================================
# GEMINI
# ==============================================================================

client = genai.Client(api_key=GEMINI_KEY)


# ==============================================================================
# FLASK
# ==============================================================================

app = Flask(__name__)


# ==============================================================================
# BUSCAR HISTÓRICO REAL DA DOUBLE
# ==============================================================================

def puxar_dados_blaze():

    url = (
        "https://blaze.bet.br/api/"
        "singleplayer-originals/originals/"
        "roulette_games/recent/1"
    )

    print("========================================")
    print("BUSCANDO HISTÓRICO REAL DA DOUBLE")
    print("URL:", url)
    print("========================================")

    try:

        resposta = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://blaze.com/"
            }
        )

        print("STATUS BLAZE:", resposta.status_code)
        print(
            "CONTENT-TYPE:",
            resposta.headers.get("Content-Type")
        )
        print(
            "TAMANHO DA RESPOSTA:",
            len(resposta.text)
        )

        resposta.raise_for_status()

        # ======================================================================
        # CONVERTER RESPOSTA PARA JSON
        # ======================================================================

        try:

            dados = resposta.json()

        except Exception as erro_json:

            print("========================================")
            print("A RESPOSTA NÃO É JSON")
            print("TIPO:", type(erro_json).__name__)
            print("ERRO:", str(erro_json))
            print("RESPOSTA:", resposta.text[:1000])
            print("========================================")

            raise RuntimeError(
                "A Blaze não retornou JSON."
            ) from erro_json

        # ======================================================================
        # VERIFICAR FORMATO
        # ======================================================================

        if not isinstance(dados, list):

            raise ValueError(
                "A API retornou um formato inesperado: "
                f"{type(dados).__name__}"
            )

        if len(dados) == 0:

            raise ValueError(
                "A API respondeu, mas não retornou nenhuma rodada."
            )

        historico = []

        # ======================================================================
        # PROCESSAR RODADAS
        # ======================================================================

        for rodada in dados:

            try:

                if not isinstance(rodada, dict):
                    continue

                created_at = rodada.get("created_at")
                color = rodada.get("color")
                roll = rodada.get("roll")

                if not created_at:
                    continue

                if color is None:
                    continue

                if roll is None:
                    continue

                # ==============================================================
                # CONVERTER DATA
                # ==============================================================

                data_texto = created_at.replace(
                    "Z",
                    "+00:00"
                )

                dt = datetime.fromisoformat(data_texto)

                # ==============================================================
                # UTC PARA HORÁRIO DE BRASÍLIA
                # ==============================================================

                if dt.tzinfo is not None:

                    dt_brasilia = dt.astimezone(
                        timezone(
                            timedelta(hours=-3)
                        )
                    )

                else:

                    dt_brasilia = dt

                horario = dt_brasilia.strftime(
                    "%H:%M:%S"
                )

                # ==============================================================
                # CONVERTER COR
                # ==============================================================

                if color == 0:
                    cor = "Branco"

                elif color == 1:
                    cor = "Vermelho"

                elif color == 2:
                    cor = "Preto"

                else:
                    cor = f"Desconhecido ({color})"

                # ==============================================================
                # ADICIONAR AO HISTÓRICO
                # ==============================================================

                historico.append(
                    {
                        "tempo": horario,
                        "resultado": cor,
                        "numero": roll
                    }
                )

            except Exception as erro_rodada:

                print(
                    "ERRO AO PROCESSAR RODADA:",
                    str(erro_rodada)
                )

                continue

        # ======================================================================
        # VERIFICAR RESULTADO FINAL
        # ======================================================================

        if not historico:

            raise ValueError(
                "A API respondeu, mas nenhuma rodada "
                "pôde ser processada."
            )

        print("========================================")
        print(
            "RODADAS RECEBIDAS:",
            len(historico)
        )

        print(
            "RODADA MAIS RECENTE:",
            historico[0]
        )

        print(
            "RODADA MAIS ANTIGA:",
            historico[-1]
        )

        print("========================================")

        return json.dumps(
            historico,
            ensure_ascii=False
        )

    except Exception as erro:

        print("========================================")
        print("FALHA AO BUSCAR HISTÓRICO")
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))
        print("========================================")

        raise RuntimeError(
            "Não foi possível obter o histórico real da Double. "
            f"Último erro: {type(erro).__name__}: {erro}"
        ) from erro


# ==============================================================================
# COMANDO /START
# ==============================================================================

@bot.message_handler(commands=["start"])
def iniciar(message):

    print("COMANDO /START RECEBIDO")

    bot.reply_to(
        message,
        "🤖 Bot online!\n\n"
        "Envie uma pergunta sobre o histórico da Double."
    )


# ==============================================================================
# RECEBER MENSAGENS
# ==============================================================================

@bot.message_handler(func=lambda message: True)
def responder_usuario(message):

    print("========================================")
    print("NOVA MENSAGEM RECEBIDA")

    print(
        "USUÁRIO:",
        message.from_user.id
    )

    print(
        "MENSAGEM:",
        message.text
    )

    print("========================================")

    try:

        pergunta_usuario = message.text or ""

        # ======================================================================
        # TESTE DO TELEGRAM
        # ======================================================================

        if pergunta_usuario.strip().upper() == "TESTE 123":

            bot.reply_to(
                message,
                "✅ Telegram - Render - Bot está funcionando."
            )

            print(
                "TESTE 123 RESPONDIDO COM SUCESSO"
            )

            return

        # ======================================================================
        # BUSCAR DADOS REAIS
        # ======================================================================

        print(
            "BUSCANDO HISTÓRICO REAL..."
        )

        dados_blaze = puxar_dados_blaze()

        print(
            "DADOS RECEBIDOS COM SUCESSO."
        )

        print(
            dados_blaze[:2000]
        )

        # ======================================================================
        # INSTRUÇÃO PARA GEMINI
        # ======================================================================

        instrucao_ia = """
Você é um interpretador estatístico estrito.

Analise SOMENTE o histórico JSON fornecido.

Cada rodada possui:
- tempo
- resultado
- número

O histórico está ordenado da rodada mais recente
para a mais antiga.

Você pode responder perguntas sobre:

- último resultado;
- último branco;
- último vermelho;
- último preto;
- horário de determinada rodada;
- número de determinada rodada;
- quantidade total de rodadas;
- quantidade de brancos;
- quantidade de vermelhos;
- quantidade de pretos;
- porcentagens;
- sequências;
- maior sequência;
- frequências;
- distribuição dos resultados;
- outras estatísticas diretamente calculáveis.

REGRAS:

1. Nunca invente dados.
2. Nunca invente horários.
3. Nunca invente resultados.
4. Use somente o JSON fornecido.
5. Se o dado não estiver no histórico, diga que não está disponível.
6. Nunca diga que um resultado futuro é garantido.
7. Nunca faça previsão do próximo resultado.
8. Nunca forneça palpite de aposta.
9. Nunca forneça estratégia de aposta.
10. Nunca forneça gerenciamento de banca.
11. Responda em português.
12. Seja direto.
13. Quando perguntarem pelo último resultado de uma cor,
    procure a ocorrência mais recente no histórico.
"""

        # ======================================================================
        # ENVIAR PARA GEMINI
        # ======================================================================

        conteudo_envio = (
            "HISTÓRICO REAL DA DOUBLE:\n"
            f"{dados_blaze}\n\n"
            "PERGUNTA DO USUÁRIO:\n"
            f"{pergunta_usuario}"
        )

        print(
            "ENVIANDO HISTÓRICO PARA GEMINI..."
        )

        resposta_gemini = client.models.generate_content(
            model=GEMINI_MODEL,
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

        # ======================================================================
        # RESPONDER TELEGRAM
        # ======================================================================

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
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))
        print("========================================")

        traceback.print_exc()

        try:

            bot.reply_to(
                message,
                "❌ Não consegui obter os dados da Double.\n\n"
                f"Erro: {type(erro).__name__}: "
                f"{str(erro)[:300]}"
            )

        except Exception:

            print(
                "ERRO AO ENVIAR MENSAGEM DE ERRO"
            )

            traceback.print_exc()


# ==============================================================================
# WEBHOOK
# ==============================================================================

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
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))
        print("========================================")

        traceback.print_exc()

        return "ERROR", 500


# ==============================================================================
# ROTA PRINCIPAL
# ==============================================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return "Bot Online!", 200


# ==============================================================================
# INICIALIZAÇÃO
# ==============================================================================

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
    print(
        "PORTA:",
        porta
    )
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=porta
    )
