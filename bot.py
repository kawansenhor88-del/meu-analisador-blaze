import os
import json
import traceback
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta

import requests
import telebot
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request
from google import genai
from google.genai import types


# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
DATABASE_URL = os.environ.get("DATABASE_URL")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "10000"))

TIPMINER_SSE_URL = (
    "https://tipminer.com"
    "v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/live"
)

MAX_HISTORY = 100000

if not TELEGRAM_TOKEN:
    raise RuntimeError("ERRO: variável TELEGRAM_TOKEN não configurada.")

if not GEMINI_KEY:
    raise RuntimeError("ERRO: variável GEMINI_KEY não configurada.")

if not DATABASE_URL:
    raise RuntimeError("ERRO: variável DATABASE_URL não configurada.")


# ==============================================================================
# SERVIÇOS
# ==============================================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_KEY)
app = Flask(__name__)


# ==============================================================================
# COMANDO TEMPORÁRIO DE TESTE DA API (INSERIDO COM SEGURANÇA)
# ==============================================================================

def testar_historico_tipminer(limit_solicitado):
    url = "https://tipminer.comv1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
    
    params = {
        "limit": limit_solicitado,
        "subject": "filter",
        "isLoadMore": "true",
        "timezone": "America/Sao_Paulo"
    }
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://tipminer.com",
        "Referer": "https://tipminer.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        status_code = response.status_code
        
        if status_code == 200:
            dados = response.json()
            
            if isinstance(dados, dict) and "data" in dados:
                lista_rodadas = dados["data"]
            elif isinstance(dados, list):
                lista_rodadas = dados
            else:
                lista_rodadas = []
                
            qtd_real = len(lista_rodadas)
            primeiro = lista_rodadas if qtd_real > 0 else None
            ultimo = lista_rodadas[-1] if qtd_real > 0 else None
            
            def mapear_cor(resultado):
                try:
                    res = int(resultado)
                    if res == 0: return "⚪ Branco"
                    if 1 <= res <= 7: return "🔴 Vermelho"
                    if 8 <= res <= 14: return "⚫ Preto"
                except:
                    return "❓ Desconhecido"
            
            tipos_amostra = [mapear_cor(r.get("result")) for r in lista_rodadas[:5]]
            
            return {
                "sucesso": True,
                "status": status_code,
                "qtd_real": qtd_real,
                "primeiro": primeiro,
                "ultimo": ultimo,
                "tipos": tipos_amostra
            }
        else:
            return {"sucesso": False, "status": status_code, "erro": response.text[:150]}
            
    except Exception as e:
        return {"sucesso": False, "status": "Erro", "erro": str(e)}


@bot.message_handler(commands=['testeapi'])
def comando_teste_api(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏳ Iniciando testes de limites no endpoint /history diretamente pelo Render...")
    
    limites_para_testar =
    relatorio = "📊 **Resultado do Teste de Limites API:**\n\n"
    
    for limite in limites_para_testar:
        res = testar_historico_tipminer(limite)
        
        if res["sucesso"]:
            p = res["primeiro"]
            u = res["ultimo"]
            
            relatorio += f"🔹 **Limite Solicitado: {limite}**\n"
            relatorio += f" ├ Status HTTP: {res['status']}\n"
            relatorio += f" ├ Qtd Real Recebida: {res['qtd_real']}\n"
            
            if res["qtd_real"] > 0:
                p_uuid = p.get('uuid', 'N/A')[:8] if p.get('uuid') else 'N/A'
                u_uuid = u.get('uuid', 'N/A')[:8] if u.get('uuid') else 'N/A'
                
                relatorio += f" ├ Primeiro do Lote: ID {p_uuid}... | Instante: {p.get('instant', 'N/A')}\n"
                relatorio += f" ├ Último do Lote: ID {u_uuid}... | Instante: {u.get('instant', 'N/A')}\n"
                relatorio += f" └ Cores (Amostra Top 5): {', '.join(res['tipos'])}\n"
            else:
                relatorio += " └ Nenhum registro retornado.\n"
        else:
            relatorio += f"❌ **Limite Solicitado: {limite}**\n"
            relatorio += f" └ Falhou. Status: {res['status']} | Erro: {res.get('erro')}\n"
            
        relatorio += "\n"
        
    bot.send_message(chat_id, relatorio, parse_mode="Markdown")


# ==============================================================================
# HISTÓRICO EM MEMÓRIA
# ==============================================================================

historico_double = deque(maxlen=MAX_HISTORY)
historico_lock = threading.Lock()
ultima_rodada_id = None


# ==============================================================================
# BANCO POSTGRESQL / SUPABASE
# ==============================================================================

def conectar_banco():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=30,
    )


def inicializar_banco():
    conn = conectar_banco()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS double_rounds (
                id BIGSERIAL PRIMARY KEY,
                rodada_id TEXT UNIQUE,
                tempo TEXT,
                resultado TEXT,
                numero TEXT,
                instant TEXT,
                tipo TEXT NOT NULL DEFAULT 'DOUBLE',
                criado_em TIMESTAMPTZ NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_double_rounds_instant
            ON double_rounds(instant)
            """
        )
        conn.commit()
        print("========================================")
        print("BANCO POSTGRESQL / SUPABASE INICIALIZADO")
        print("LIMITE DE RODADAS:", MAX_HISTORY)
        print("========================================")
    except Exception:
        conn.rollback()
        print("ERRO AO INICIALIZAR POSTGRESQL:")
        traceback.print_exc()
        raise
    finally:
        conn.close()


def carregar_historico_banco():
    global ultima_rodada_id

    conn = conectar_banco()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT rodada_id, tempo, resultado, numero, instant, tipo
            FROM double_rounds
            ORDER BY id DESC
            LIMIT %s
            """
            , (MAX_HISTORY,)
        )
        linhas = cursor.fetchall()

        with historico_lock:
            historico_double.clear()
            for linha in reversed(linhas):
                historico_double.append(
                    {
                        "tempo": linha["tempo"],
                        "resultado": linha["resultado"],
                        "numero": linha["numero"],
                        "instant": linha["instant"],
                        "tipo": linha["tipo"],
                    }
                )

        if linhas:
            ultima_rodada_id = str(linhas[0]["rodada_id"])

        print("========================================")
        print("HISTÓRICO CARREGADO DO POSTGRESQL")
        print("RODADAS RECUPERADAS:", len(linhas))
        print("========================================")
        return len(linhas)
    finally:
        conn.close()


def salvar_rodada_banco(rodada, rodada_id):
    max_tentativas = 3

    for tentativa in range(1, max_tentativas + 1):
        conn = None
        try:
            conn = conectar_banco()
            cursor = conn.cursor()
            agora = datetime.now(timezone.utc)

            cursor.execute(
                """
                INSERT INTO double_rounds
                (rodada_id, tempo, resultado, numero, instant, tipo, criado_em)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (rodada_id) DO NOTHING
                """,
                (
                    str(rodada_id),
                    rodada.get("tempo"),
                    rodada.get("resultado"),
                    str(rodada.get("numero"))
                    if rodada.get("numero") is not None else None,
                    str(rodada.get("instant"))
                    if rodada.get("instant") is not None else None,
                    rodada.get("tipo", "DOUBLE"),
                    agora,
                ),
            )

            inseriu = cursor.rowcount > 0
            conn.commit()

            cursor.execute(
                """
                DELETE FROM double_rounds
                WHERE id NOT IN (
                    SELECT id
                    FROM double_rounds
                    ORDER BY id DESC
