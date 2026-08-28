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
    conn = conectar_banco()
    try:
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
                str(rodada.get("numero")) if rodada.get("numero") is not None else None,
                str(rodada.get("instant")) if rodada.get("instant") is not None else None,
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
                LIMIT %s
            )
            """,
            (MAX_HISTORY,),
        )
        conn.commit()
        return inseriu
    except Exception:
        conn.rollback()
        print("ERRO AO SALVAR RODADA NO POSTGRESQL:")
        traceback.print_exc()
        return False
    finally:
        conn.close()


def contar_rodadas_banco():
    conn = conectar_banco()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM double_rounds")
        res = cursor.fetchone()
        return res[0] if res else 0
    finally:
        conn.close()


def obtener_historico_banco(limite=None):
    conn = conectar_banco()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if limite is None:
            cursor.execute("""SELECT rodada_id, tempo, resultado, numero, instant, tipo, criado_em
                              FROM double_rounds ORDER BY id DESC""")
        else:
            cursor.execute("""SELECT rodada_id, tempo, resultado, numero, instant, tipo, criado_em
                              FROM double_rounds ORDER BY id DESC LIMIT %s""", (int(limite),))
        linhas = cursor.fetchall()
        return [{"rodada_id": str(x["rodada_id"]) if x["rodada_id"] is not None else None,
                 "tempo": x["tempo"], "resultado": x["resultado"], "numero": x["numero"],
                 "instant": x["instant"], "tipo": x["tipo"],
                 "criado_em": x["criado_em"].isoformat() if x["criado_em"] else None}
                for x in linhas]
    finally:
        conn.close()


def obtener_ultimo_por_cor(cor):
    conn = conectar_banco()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""SELECT rodada_id, tempo, resultado, numero, instant, tipo
                          FROM double_rounds
                          WHERE LOWER(resultado)=LOWER(%s)
                          ORDER BY id DESC LIMIT 1""", (cor,))
        x = cursor.fetchone()
        if not x: return None
        return {"rodada_id": str(x["rodada_id"]), "tempo": x["tempo"],
                "resultado": x["resultado"], "numero": x["numero"],
                "instant": x["instant"], "tipo": x["tipo"]}
    finally:
        conn.close()


# ==============================================================================
# CONVERSORES
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
            dt = dt.astimezone(timezone(timedelta(hours=-3)))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return str(valor)


def converter_cor(valor):
    if valor is None:
        return None
    try:
        numero = int(valor)
        if numero == 0:
            return "Branco"
        if 1 <= numero <= 6:
            return "Vermelho"
        if 7 <= numero <= 14:
            return "Preto"
    except Exception:
        pass

    texto = str(valor).strip().lower()
    if texto in ("white", "branco"):
        return "Branco"
    if texto in ("red", "vermelho"):
        return "Vermelho"
    if texto in ("black", "preto"):
        return "Preto"
    return str(valor)


def cor_por_tipo(tipo, resultado=None, color=None):
    t = str(tipo or "").upper()
    if t == "LUCKY":
        return "Branco"
    if t == "DOUBLE":
        return "Vermelho"
    if t == "DEFAULT":
        return "Preto"
    if color is not None:
        return converter_cor(color)
    return converter_cor(resultado)


# ==============================================================================
# ADICIONAR RODADA
# ==============================================================================

def adicionar_rodada(payload):
    global ultima_rodada_id

    if not isinstance(payload, dict):
        return False

    tipo = payload.get("type")
    if tipo and str(tipo).upper() not in ("DOUBLE", "DEFAULT", "LUCKY"):
        return False

    resultado = payload.get("result")
    instant = payload.get("instant")
    color = payload.get("color")
    roll = payload.get("roll")

    if resultado is None:
        resultado = payload.get("value")
    if instant is None:
        instant = payload.get("created_at")
