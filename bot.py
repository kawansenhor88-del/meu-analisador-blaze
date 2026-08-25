import os
import json
import traceback
import threading
import time

import psycopg2
from psycopg2.extras import RealDictCursor
from collections import deque
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
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

TIPMINER_SSE_URL = (
    "https://api.core.public.tipminer.com/"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/live"
)

RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

PORT = int(os.environ.get("PORT", "10000"))
DATABASE_URL = os.environ.get("DATABASE_URL")


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
# HISTÓRICO DA DOUBLE
# ==============================================================================

historico_double = deque(maxlen=200)

# O banco guarda TODO o histórico.
# O deque acima continua sendo apenas um cache rápido
# das últimas 200 rodadas em memória.

historico_lock = threading.Lock()

ultima_rodada_id = None


# ==============================================================================
# BANCO DE DADOS POSTGRESQL
# ==============================================================================

def conectar_banco():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não configurada no Render. "
            "Adicione a URL do PostgreSQL nas variáveis de ambiente."
        )

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def inicializar_banco():
    conn = None

    try:
        conn = conectar_banco()

        with conn.cursor() as cursor:

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rodadas_double (
                    id TEXT PRIMARY KEY,
                    tempo TEXT,
                    resultado TEXT,
                    numero TEXT,
                    instant TEXT,
                    tipo TEXT NOT NULL DEFAULT 'DOUBLE',
                    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_rodadas_double_instant
                ON rodadas_double (instant DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_rodadas_double_criado_em
                ON rodadas_double (criado_em DESC)
            """)

        conn.commit()

        print("POSTGRESQL: banco inicializado com sucesso.")

    except Exception:

        if conn is not None:
            conn.rollback()

        print("ERRO AO INICIALIZAR POSTGRESQL:")
        traceback.print_exc()

        raise

    finally:

        if conn is not None:
            conn.close()


def salvar_rodada_banco(rodada_id, rodada):
    conn = None

    try:
        conn = conectar_banco()

        with conn.cursor() as cursor:

            cursor.execute("""
                INSERT INTO rodadas_double
                    (id, tempo, resultado, numero, instant, tipo)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                str(rodada_id),
                rodada.get("tempo"),
                rodada.get("resultado"),
                None if rodada.get("numero") is None
                else str(rodada.get("numero")),
                rodada.get("instant"),
                rodada.get("tipo", "DOUBLE")
            ))

            inserida = cursor.rowcount == 1

        conn.commit()

        return inserida

    except Exception:

        if conn is not None:
            conn.rollback()

        print("ERRO AO SALVAR RODADA NO POSTGRESQL:")
        traceback.print_exc()

        return False

    finally:

        if conn is not None:
            conn.close()


def obter_historico_banco(limite=200):
    conn = None

    try:
        conn = conectar_banco()

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute("""
                SELECT tempo, resultado, numero, instant, tipo
                FROM rodadas_double
                ORDER BY criado_em DESC
                LIMIT %s
            """, (int(limite),))

            linhas = cursor.fetchall()

        return [dict(linha) for linha in linhas]

    finally:

        if conn is not None:
            conn.close()


# ==============================================================================
# CONVERTER HORÁRIO
# ==============================================================================

def converter_horario(valor):

    if not valor:
        return None

    try:

        texto = str(valor)

        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"

        dt = datetime.fromisoformat(texto)

        if dt.tzinfo is not None:
            dt = dt.astimezone(
                timezone(timedelta(hours=-3))
            )

        return dt.strftime("%H:%M:%S")

    except Exception:

        return str(valor)


# ==============================================================================
# CONVERTER COR
# ==============================================================================

def converter_cor(valor):

    if valor is None:
        return None

    try:

        numero = int(valor)

        if numero == 0:
            return "Branco"

        if numero == 1:
            return "Vermelho"

        if numero == 2:
            return "Preto"

    except Exception:
        pass

    texto = str(valor).strip().lower()

    if texto in ["white", "branco"]:
        return "Branco"

    if texto in ["red", "vermelho"]:
        return "Vermelho"

    if texto in ["black", "preto"]:
        return "Preto"

    return str(valor)


# ==============================================================================
# ADICIONAR RODADA
# ==============================================================================

def adicionar_rodada(payload):

    global ultima_rodada_id

    if not isinstance(payload, dict):
        return False

    tipo = payload.get("type")

    if tipo and str(tipo).upper() != "DOUBLE":
        return False

    resultado = payload.get("result")
    instant = payload.get("instant")
    color = payload.get("color")
    roll = payload.get("roll")

    if resultado is None:
        resultado = payload.get("value")

    if instant is None:
        instant = payload.get("created_at")

    if color is None:
        color = payload.get("colour")

    if roll is None:
        roll = payload.get("number")

    if resultado is None and color is None and roll is None:
        return False

    rodada_id = (
        payload.get("id")
        or payload.get("uuid")
        or instant
    )

    if rodada_id is not None:

        rodada_id = str(rodada_id)

        if rodada_id == ultima_rodada_id:
            return False

    valor_cor = color

    if valor_cor is None:
        valor_cor = resultado

    cor = converter_cor(valor_cor)

    numero = roll

    if numero is None:
        numero = resultado

    horario = converter_horario(instant)

    if horario is None:
        horario = datetime.now(
            timezone(timedelta(hours=-3))
        ).strftime("%H:%M:%S")

    rodada = {
        "tempo": horario,
        "resultado": cor,
        "numero": numero,
        "instant": instant,
        "tipo": "DOUBLE"
    }

    # Primeiro grava no banco permanente.
    # Se o banco falhar, não avançamos o histórico em memória.

    if not salvar_rodada_banco(
        rodada_id,
        rodada
    ):

        print(
            "RODADA NÃO FOI GRAVADA NO BANCO. "
            "Ela não será adicionada ao cache."
        )

        return False

    with historico_lock:

        if historico_double:

            ultima = historico_double[0]

            if (
                ultima.get("instant") == rodada.get("instant")
                and ultima.get("numero") == rodada.get("numero")
            ):

                return False

        historico_double.appendleft(rodada)

    ultima_rodada_id = rodada_id

    print("========================================")
    print("NOVA RODADA DOUBLE RECEBIDA")
    print(rodada)
    print("HISTÓRICO:", len(historico_double))
    print("========================================")

    return True


# ==============================================================================
# PROCESSAR EVENTO SSE
# ==============================================================================

def processar_evento_sse(evento):

    if not evento:
        return

    evento = evento.strip()

    if not evento:
        return

    print("SSE EVENTO BRUTO:")
    print(evento)

    linhas = evento.splitlines()

    dados_json = []

    for linha in linhas:

        linha = linha.strip()

        if linha.startswith("data:"):

            conteudo = linha[5:].strip()

            if conteudo:
                dados_json.append(conteudo)

    if not dados_json:
        return

    texto_json = "\n".join(dados_json)

    try:

        payload = json.loads(texto_json)

    except Exception as erro:

        print(
            "ERRO AO CONVERTER EVENTO SSE PARA JSON:"
        )

        print(erro)
        print(texto_json[:1000])

        return

    print("JSON SSE:")

    print(
        json.dumps(
            payload,
            ensure_ascii=False
        )[:3000]
    )

    if not isinstance(payload, dict):
        return

    # Evento heartbeat

    if payload.get("type") == "heartbeat":

        print("HEARTBEAT RECEBIDO")

        return

    # Evento DOUBLE diretamente

    if payload.get("type") == "DOUBLE":

        adicionar_rodada(payload)

        return

    # Dados dentro de "data"

    dados = payload.get("data")

    if isinstance(dados, dict):

        if dados.get("type") == "heartbeat":

            print("HEARTBEAT RECEBIDO")

            return

        if dados.get("type") == "DOUBLE":

            adicionar_rodada(dados)

            return

        if (
            "result" in dados
            or "color" in dados
            or "roll" in dados
        ):

            dados["type"] = "DOUBLE"

            adicionar_rodada(dados)

            return

    # Resultado diretamente no payload

    if (
        "result" in payload
        or "color" in payload
        or "roll" in payload
    ):

        payload["type"] = "DOUBLE"

        adicionar_rodada(payload)


# ==============================================================================
# CAPTURAR SSE DO TIPMINER
# ==============================================================================

def capturar_tipminer():

    print("========================================")
    print("CAPTURADOR TIPMINER INICIANDO")
    print("========================================")

    while True:

        resposta = None

        try:

            print(
                "CONECTANDO AO SSE DO TIPMINER..."
            )

            print(TIPMINER_SSE_URL)

            resposta = requests.get(
                TIPMINER_SSE_URL,
                stream=True,
                timeout=60,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache"
                }
            )

            print(
                "STATUS TIPMINER:",
                resposta.status_code
            )

            print(
                "CONTENT-TYPE:",
                resposta.headers.get("Content-Type")
            )

            resposta.raise_for_status()

            print("========================================")
            print("SSE TIPMINER CONECTADO")
            print("AGUARDANDO EVENTOS DOUBLE...")
            print("========================================")

            evento_atual = []

            for linha in resposta.iter_lines(
                decode_unicode=True
            ):

                if linha is None:
                    continue

                if linha == "":

                    if evento_atual:

                        processar_evento_sse(
                            "\n".join(evento_atual)
                        )

                        evento_atual = []

                    continue

                evento_atual.append(linha)

            if evento_atual:

                processar_evento_sse(
                    "\n".join(evento_atual)
                )

        except Exception as erro:

            print("========================================")
            print("ERRO NA CONEXÃO TIPMINER")
            print("TIPO:", type(erro).__name__)
            print("ERRO:", str(erro))
            print("========================================")

            traceback.print_exc()

        finally:

            if resposta is not None:

                try:
                    resposta.close()

                except Exception:
                    pass

        print(
            "TENTANDO RECONECTAR AO TIPMINER "
            "EM 5 SEGUNDOS..."
        )

        time.sleep(5)


# ==============================================================================
# INICIAR CAPTURADOR
# ==============================================================================

def iniciar_capturador():

    thread = threading.Thread(
        target=capturar_tipminer,
        daemon=True
    )

    thread.start()

    print("THREAD DO TIPMINER INICIADA.")


# ==============================================================================
# OBTER HISTÓRICO
# ==============================================================================

def obter_historico():

    # O banco é a fonte permanente.
    # O deque continua como cache local.

    dados = obter_historico_banco(200)

    if not dados:

        with historico_lock:
            dados = list(historico_double)

    if not dados:

        raise RuntimeError(
            "Ainda não existe nenhuma rodada DOUBLE no banco."
        )

    return json.dumps(
        dados,
        ensure_ascii=False
    )


# ==============================================================================
# COMANDO /START
# ==============================================================================

@bot.message_handler(commands=["start"])
def iniciar(message):

    print("COMANDO /START RECEBIDO")

    bot.reply_to(
        message,
        "🤖 Bot online!\n\n"
        "Captura TipMiner ativa.\n"
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

        if pergunta_usuario.strip().upper() == "TESTE 123":

            bot.reply_to(
                message,
                "✅ Telegram - Render - Bot está funcionando."
            )

            print(
                "TESTE 123 RESPONDIDO COM SUCESSO"
            )

            return

        print(
            "OBTENDO HISTÓRICO DO TIPMINER..."
        )

        dados_double = obter_historico()

        print(
            "HISTÓRICO TIPMINER OBTIDO."
        )

        print(
            dados_double[:5000]
        )

        instrucao_ia = """
Você é um interpretador estatístico estrito.

Analise SOMENTE o histórico JSON fornecido.

Cada rodada possui:
- tempo
- resultado
- número
- instant
- tipo

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

        conteudo_envio = (
            "HISTÓRICO REAL DA DOUBLE CAPTURADO PELO TIPMINER:\n"
            f"{dados_double}\n\n"
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
                "❌ Ainda não consegui obter os dados da Double.\n\n"
                f"Erro: {type(erro).__name__}: "
                f"{str(erro)[:300]}"
            )

        except Exception:

            print(
                "ERRO AO ENVIAR MENSAGEM DE ERRO"
            )

            traceback.print_exc()


# ==============================================================================
# WEBHOOK DO TELEGRAM
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

    return "Bot Online!"


# ==============================================================================
# CONFIGURAR WEBHOOK
# ==============================================================================

def configurar_webhook():

    if not RENDER_EXTERNAL_URL:

        print("RENDER_EXTERNAL_URL não encontrada.")
        print("Webhook não configurado automaticamente.")

        return

    webhook_url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/"
        + TELEGRAM_TOKEN
    )

    try:

        bot.remove_webhook()

        time.sleep(1)

        sucesso = bot.set_webhook(
            url=webhook_url
        )

        print("========================================")
        print("WEBHOOK TELEGRAM")
        print("URL:", webhook_url)
        print("RESULTADO:", sucesso)
        print("========================================")

    except Exception as erro:

        print("ERRO AO CONFIGURAR WEBHOOK:")
        print(type(erro).__name__)
        print(str(erro))

        traceback.print_exc()


# ==============================================================================
# INICIALIZAÇÃO DO SERVIDOR
# ==============================================================================

if __name__ == "__main__":

    print("========================================")
    print("INICIANDO BOT DOUBLE")
    print("========================================")

    inicializar_banco()

    iniciar_capturador()

    configurar_webhook()

    print("========================================")
    print("FLASK INICIANDO")
    print("PORTA:", PORT)
    print("========================================")

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
        )
