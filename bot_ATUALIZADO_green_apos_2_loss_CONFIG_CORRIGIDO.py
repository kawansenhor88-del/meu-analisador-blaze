import unicodedata
import os
import base64
import io
import json
import re
import traceback
import threading

# ==============================================================================
# CONFIGURADOR DE ESTRATÉGIA — estado em memória
# ==============================================================================
ESTRATEGIAS_CONFIG = {}
ESTRATEGIAS_GATILHO_CONFIG = {}

# Estratégia independente: GREEN APÓS 2 LOSS consecutivos.
# Usa a matemática da ENTRADA POR GATILHO como estratégia-base.
ESTRATEGIAS_GREEN_APOS_LOSS_CONFIG = {}
green_loss_contador = 0
green_loss_fase = "observando"  # observando | entrada
green_loss_tentativa = 1
green_loss_status_message_id = None

TEXTOS_CANAL_CONFIG = {}
TEXTOS_CANAL_OWNER_CHAT_ID = None

_TEXTOS_CANAL_PADRAO = {
    "online": (
        "📡 SINAIS ONLINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 BOT ONLINE\n\n"
        "📡 MONITORAMENTO INICIADO.\n"
        "🎯 AGUARDANDO OPORTUNIDADE..."
    ),
    "offline": (
        "📴 SINAIS OFFLINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 BOT OFFLINE\n\n"
        "⏸ MONITORAMENTO INTERROMPIDO."
    ),
    "chegando": (
        "⚠️ CAMINHO ÚNICO CHEGANDO\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏄 {SURF}\n\n"
        "🔥 GALE DE ATIVAÇÃO: {GALE_GATILHO}\n"
        "📍 GALE ATUAL: {GALE_ATUAL}\n\n"
        "⏳ CAMINHO EM ANDAMENTO..."
    ),
    "cancelado": (
        "🚫 CAMINHO CANCELADO\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏄 {SURF}\n\n"
        "📍 CAMINHO ACERTOU NO {GALE_ATUAL}\n"
        "🔥 GALE DE ATIVAÇÃO: {GALE_GATILHO}\n\n"
        "❌ SINAL NÃO CONFIRMADO."
    ),
    "sinal": (
        "🎯 SINAL CONFIRMADO\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔥 GALE DE ATIVAÇÃO: {GALE_GATILHO}\n\n"
        "📍 ÚLTIMA RODADA: {COR_ULTIMA} {NUMERO_ULTIMA}\n\n"
        "🎯 ENTRADA PARA {COR_ENTRADA}"
    ),
    "green": (
        "✅ GREEN\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏆 GREEN {RESULTADO_GALE}\n"
        "🎯 ENTRADA FINALIZADA COM SUCESSO."
    ),
    "loss": (
        "❌ LOSS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🛑 OPERAÇÃO FINALIZADA NO {LIMITE_GALE}\n"
        "📉 LIMITE DE GALES ATINGIDO."
    ),
    "gales": (
        "❌ NÃO BATEU\n\n"
        "🔥 VAMOS PARA O {GALE}"
    ),
}

_TEXTOS_CANAL_META = {
    "online": ("📡 SINAIS ONLINE", "ESTA É A MENSAGEM ENVIADA AUTOMATICAMENTE AO CANAL QUANDO O BOT É ATIVADO."),
    "offline": ("📴 SINAIS OFFLINE", "ESTA É A MENSAGEM ENVIADA AUTOMATICAMENTE AO CANAL QUANDO O BOT É PARADO."),
    "chegando": ("⚠️ CAMINHO ÚNICO CHEGANDO", "ESTA É A MENSAGEM ENVIADA QUANDO UM CAMINHO ÚNICO ESTÁ SE APROXIMANDO DO GALE DE ATIVAÇÃO."),
    "cancelado": ("🚫 CAMINHO CANCELADO", "ESTA É A MENSAGEM ENVIADA QUANDO O CAMINHO ACERTA ANTES DE CHEGAR AO GALE DE ATIVAÇÃO E O SINAL É CANCELADO."),
    "sinal": ("🎯 SINAL CONFIRMADO", "ESTA É A MENSAGEM ENVIADA QUANDO O CAMINHO ÚNICO REALMENTE CHEGA AO GALE DE ATIVAÇÃO. A COR E O NÚMERO VÊM SEMPRE DA RODADA REAL MAIS RECENTE."),
    "green": ("✅ GREEN", "ESTA É A MENSAGEM ENVIADA QUANDO A OPERAÇÃO ACERTA. O DIRETO/G1/G2... É DEFINIDO AUTOMATICAMENTE PELA LÓGICA."),
    "loss": ("❌ LOSS", "ESTA É A MENSAGEM ENVIADA QUANDO A OPERAÇÃO CHEGA AO LIMITE DE GALES SEM ACERTAR. O LIMITE É DEFINIDO AUTOMATICAMENTE PELA LÓGICA."),
    "gales": ("🔢 GALES DA OPERAÇÃO", "UM ÚNICO TEXTO É USADO PARA TODOS OS GALES. O BOT TROCA AUTOMATICAMENTE G1, G2, G3... ATÉ O LIMITE CONFIGURADO."),
}

_TEXTOS_CANAL_REQUIRED = {
    "online": set(),
    "offline": set(),
    "chegando": {"{SURF}", "{GALE_GATILHO}", "{GALE_ATUAL}"},
    "cancelado": {"{SURF}", "{GALE_GATILHO}", "{GALE_ATUAL}"},
    "sinal": {"{GALE_GATILHO}", "{COR_ULTIMA}", "{NUMERO_ULTIMA}", "{COR_ENTRADA}"},
    "green": {"{RESULTADO_GALE}"},
    "loss": {"{LIMITE_GALE}"},
    "gales": {"{GALE}"},
}

def _textos_canal_cfg(chat_id):
    chat_id = int(chat_id)
    if chat_id not in TEXTOS_CANAL_CONFIG:
        TEXTOS_CANAL_CONFIG[chat_id] = {
            "textos": dict(_TEXTOS_CANAL_PADRAO),
            "green_imagem": None,  # compatibilidade com configuração antiga
            "green_imagens": {},   # 0=DIRETO, 1=G1, 2=G2...
            "loss_imagem": None,
        }
    else:
        # Migração leve para quem já estava usando a versão anterior.
        TEXTOS_CANAL_CONFIG[chat_id].setdefault("green_imagens", {})
    return TEXTOS_CANAL_CONFIG[chat_id]

def _texto_canal_modelo(chat_id, chave):
    return _textos_canal_cfg(chat_id)["textos"].get(chave, _TEXTOS_CANAL_PADRAO[chave])

def _render_texto_canal(chat_id, chave, **dados):
    modelo = _texto_canal_modelo(chat_id, chave)
    for nome, valor in dados.items():
        modelo = modelo.replace("{" + nome + "}", str(valor))
    # O padrão aprovado para as mensagens públicas do canal é MAIÚSCULO.
    return modelo.upper()

def _chat_textos_ativo():
    if TEXTOS_CANAL_OWNER_CHAT_ID is not None:
        return TEXTOS_CANAL_OWNER_CHAT_ID
    if TEXTOS_CANAL_CONFIG:
        return next(reversed(TEXTOS_CANAL_CONFIG))
    return None


def _estrategia_padrao():
    return {
        "gale_gatilho": None,
        "surf": None,
        "limite_gales": None,
        "aviso_antes": None,
        "ativa": False,
        "pausada": False,
        "relatorio_qtd": 0,
        "relatorio_texto": None,
        "relatorio_bloco": [],
        "relatorio_anterior": None,
        "relatorio_geral_blocos": 0,
        "relatorio_geral_sinais": 0,
        "relatorio_geral_greens": 0,
        "relatorio_geral_saldo": 0,
    }

def _cfg(chat_id):
    chat_id = int(chat_id)
    if chat_id not in ESTRATEGIAS_CONFIG:
        ESTRATEGIAS_CONFIG[chat_id] = _estrategia_padrao()
    return ESTRATEGIAS_CONFIG[chat_id]


def _estrategia_gatilho_padrao():
    return {
        "gale_gatilho": None,
        "surf": None,
        "limite_gales": None,
        "ativa": False,
        "pausada": False,
        "green_imagens": {},
        "loss_imagem": None,
        "aviso_antes": 2,
        "relatorio_qtd": 0,
        "relatorio_texto": None,
        "relatorio_bloco": [],
        "relatorio_anterior": None,
        "relatorio_geral_blocos": 0,
        "relatorio_geral_sinais": 0,
        "relatorio_geral_greens": 0,
        "relatorio_geral_saldo": 0,
        "textos_sinais": {},
    }

def _cfg_gatilho(chat_id):
    chat_id = int(chat_id)
    if chat_id not in ESTRATEGIAS_GATILHO_CONFIG:
        ESTRATEGIAS_GATILHO_CONFIG[chat_id] = _estrategia_gatilho_padrao()
    return ESTRATEGIAS_GATILHO_CONFIG[chat_id]


def _green_loss_padrao():
    return {
        "gale_gatilho": None,
        "surf": None,
        "limite_gales": None,
        "loss_consecutivos": 2,
        "ativa": False,
        "pausada": False,
    }

def _cfg_green_loss(chat_id):
    chat_id = int(chat_id)
    if chat_id not in ESTRATEGIAS_GREEN_APOS_LOSS_CONFIG:
        ESTRATEGIAS_GREEN_APOS_LOSS_CONFIG[chat_id] = _green_loss_padrao()
    return ESTRATEGIAS_GREEN_APOS_LOSS_CONFIG[chat_id]

def _surf_nome(valor):
    if valor is None:
        return "NÃO CONFIGURADO"
    return {
        "vermelho": "🔴 SURF 2 VERMELHOS",
        "preto": "⚫ SURF 2 PRETOS",
        "ambos": "🔴⚫ OS DOIS",
    }.get(valor, "NÃO CONFIGURADO")

import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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
TIPMINER_TOKEN = os.environ.get("TIPMINER_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "10000"))

# Canal privado usado exclusivamente para os alertas do SURF ao vivo.
ALERTAS_CHAT_ID = -1004360291159

# Evita atualizar/regravar as 2.000 rodadas a cada mensagem do Telegram.
# A base continua sendo exclusivamente a janela de 2.000 do endpoint /history.
HISTORY_REFRESH_SECONDS = 30

TIPMINER_URL = (
    "https://api.core.public.tipminer.com/v1/double/rounds/"
    "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
)

ANALYSIS_ROUNDS = 2000
MAX_HISTORY = ANALYSIS_ROUNDS

TIPMINER_PARAMS = {
    "timezone": "America/Sao_Paulo",
    "subject": "filter",
    "limit": ANALYSIS_ROUNDS,
}

if not TELEGRAM_TOKEN:
    raise RuntimeError("ERRO: variável TELEGRAM_TOKEN não configurada.")

if not GEMINI_KEY:
    raise RuntimeError("ERRO: variável GEMINI_KEY não configurada.")

if not DATABASE_URL:
    raise RuntimeError("ERRO: variável DATABASE_URL não configurada.")

if not TIPMINER_TOKEN:
    raise RuntimeError("ERRO: variável TIPMINER_TOKEN não configurada.")


# ==============================================================================
# SERVIÇOS
# ==============================================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
surfe_mensagens_abertas = {}
surfe_cache = {}
controle_geral_surfe_cache = {}

# Controle do monitoramento ao vivo do canal de alertas.
# Começa DESLIGADO para não criar consultas em segundo plano sem o usuário pedir.
alertas_surfe_ativos = False
alertas_surfe_lock = threading.RLock()
CAMINHO_AO_VIVO_LIMITE = 99
caminho_ao_vivo_marcas = {}
alertas_surfe_thread = None
alertas_surfe_ultima_rodada_id = None
alertas_surfe_modo = None  # "Preto", "Vermelho" ou "Ambos"
alertas_surfe_historico = []  # janela cronológica das 2.000 rodadas
alertas_surfe_operacoes = {}  # sinais G9 ainda em andamento
alertas_surfe_sinais_emitidos = set()
alertas_surfe_caminhos_unicos_emitidos = set()  # sequências reais já sinalizadas nesta sessão
alertas_surfe_inicio_monitor_id = None
alertas_surfe_prealerta = None
alertas_surfe_registro = deque(maxlen=50)

# Registros da sessão ONLINE atual.
# Não são preenchidos retroativamente: ao ligar o monitor, a sessão começa
# da rodada mais recente e estes registros são zerados.
alertas_surfe_registro_sinais = deque(maxlen=200)
alertas_surfe_registro_sinais_seq = 0
alertas_surfe_registro_sinais_vistos_chat = {}
alertas_surfe_stats = {
    "green": 0,
    "loss": 0,
    "direto": 0,
    "gales": {n: 0 for n in range(1, 7)},
}
# Diagnóstico do monitor: permite saber que ele continua lendo as rodadas
# mesmo quando ainda não apareceu nenhum G9.
alertas_surfe_status_ultimo_envio = 0.0
alertas_surfe_ultima_rodada_detectada = None
alertas_surfe_ultimo_atraso = None
alertas_surfe_total_novas = 0

ALERTAS_SURF_INTERVALO = 5
ALERTAS_SURF_STATUS_INTERVALO = 1800  # 30 minutos
ALERTAS_SURF_GATILHO = 9
ALERTAS_SURF_STOP_GALE = 6
ALERTAS_SURF_AVISO_ANTES = 2
ALERTAS_MODO_ESTRATEGIA = "surf"
alertas_gatilho_nivel_aposta = 0
alertas_gatilho_status_message_id = None
alertas_gatilho_espera_message_id = None
alertas_gatilho_chegando_message_id = None
alertas_gatilho_caminho_message_id = None
alertas_gatilho_entrada_message_id = None
alertas_gatilho_caminho_resultados = []
alertas_gatilho_prealerta = None
alertas_gatilho_total_greens = 0
alertas_gatilho_total_loss = 0

# Estado visual exclusivo do SURF normal.
# Mantido separado da estratégia ENTRADA POR GATILHO.
alertas_surf_caminho_message_id = None
alertas_surf_entrada_message_id = None
alertas_surf_prealerta_message_id = None
alertas_surf_caminho_resultados = []

# Cartões GREEN/LOSS aprovados, compactados e embutidos no próprio .py.
_ALERTA_CARDS_B64 = {
    "direto": "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",
    "gale1": "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",
    "gale2": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgwKCA0MCwwPDg0QFCIWFBISFCkdHxgiMSszMjArLy42PE1CNjlJOi4vQ1xESVBSV1dXNEFfZl5UZU1VV1P/2wBDAQ4PDxQSFCcWFidTNy83U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1P/wgARCAC0ANgDASIAAhEBAxEB/8QAGgAAAgMBAQAAAAAAAAAAAAAABAUAAgMBBv/EABkBAAMBAQEAAAAAAAAAAAAAAAABAgMEBf/aAAwDAQACEAMQAAABRClMBJYzZB5rvoUiMZIEk6Kd7ZKkuxSVTSrdJbjfJOjnHaUnkIqVjwngDzsYUaDtOe+WWano1pWte3vKx7tQRJYrDLFR6FF6JvzXCdqoURwpbo0WEMY59AWbLqzmnS3zWjB2cgFDkCovKxLvLdFy/LzOliCsOZM+RsdNSFHKg7I822Uqe69qxq70q866UqqzriZWd9H5+MRZJt1FilDpc7Lpc0JZRknu/XRmGWQRMoNne9353jzRvz27qTKerfTPLz3X49UtC9MubSNdY6zUXzvSs7Ndicdh0rtVfpc8TxNPIrH2azNbM+g1CqLYpG1UhNfOPEAjFLdOhzsLpHOMHut06vYr9+Z8gbBSyevl87569dJJeheBGUx30HnfR5cnVJ2E5nLGid020GFywarNeOg3CwgdQJnt1Obi548hCjK+/Z6ODY8/nl7C6j85OF9PpAy8vQulq554+gROM+YfMnsz1aSvvRsLYVIzofHRBSzUGImOKTGy/RjMCuQzRtBQYbZbZ4JdrC79mcrNNj8Dd5zVF7r5lgr5HW544ig2D+idKNMXySzYCswdmWuC9R/RVaHQ7zrGSpiEjrFZB6j6tqpDGspiDklug3CPeYH05nKJEJGBg4Q+iulr1bdIYFrmBiBwoGu9Op9O35tWzWDKnc88LlLznRS3Mu9Fs7GySxJObFIcAkeFrk6KsHEt+YdGRYe6RJIFozLHxo3vsDHTTICA2UyjZomo9M9ko0nIGcmnSaEWIEmlRXp2JW5arc7yDrelxd5XoWp3gd7Sw+d5AvTtRaZXolOa5t2lIl7aklX3kiUkjOyRHJIEkgTkjJJA7JBySBJIKdkROSBJI3//xAArEAABBAECBQMFAQEBAAAAAAABAAIDBBESExAUFSE0BSIxICMkMjNBQEP/2gAIAQEAAQUCs+T/AMeDj6rPk1mRPhfE1sPLsTYIdU2N36ccI6ckkZGPpAJMkQiqgZJglDzE8LZl0thkcfg2fJhfK2KGSVrcvMLp3uH0wQuldNBtcIS4wvdqc1pcZYXRcaI7xytaLGmO6Z4sb8TlzLNoSwhx+bPkxy6WB6y7RjHDIWQu3CGXaVhj9trC5wlbFNYi25qbXbtibVFwhlMT4QAnyl8zpNR3Bgy542fJ1FanLU5Ek8QtKc3hulkY22Iu9ztE7Y5hhY45OOLI3PUse2VZ8n64vcns9hX7UkQgv1pNaiFjhjjDFEsqwczKz5P0YWFpQ9pMmoO+WSaIxZkajalKE5Ukm60MwCEQmR6k7sHBYyYwIxuhyd3crPlHgFHA+RMpFckFLEYnQVt5vJBCixcpHjkWZ5KBcnCpYImRxRtezlY0KbE9jRIaQUsQhdBX1CavK1nweFnyQVhU4N1x+N9gfqV1/tpu/Hll244bO6tahmJmyn3SySW5rZTd+NNLtR8+t7ctau97vFQd7LBzWIR4WfJQVLtA92Gg/ddbYp590Ve1e2fsentROBWObOU6o177MGyq3avKzdjNBRdp8p3ubT9ql7wE8bPk8K/aCY4irVhMuUgCuNjYmdo/lau1rc0VP3BXNNzZkEii7RPkEbeZYov75Qcg3Eh/RAZKseS4YKZ2isH7VSRojyrhy74U78DOEXZEK1J1eVz3wSRtacMn7w6HKLtNqQd93Ugc8IAE79pvLk7uRKnzt1oi0ZU/ulJ7z/yzln+1+8eF7gp3nb/wOLVvvTjqtZT3aZvgxn3Y90JwnfNjyh3cezjwc7sZGhNd94zsCkl1tEpa3demOewCSVGaVOe5zd56bYIRsZWsb2tinIKb7o2DDndps8LLHcw35JTLGkG2MSSOkMEO678diJhWYFqhQfChLCt+FGaJbkKL4Fhjl9kIGuVLXYWEKOVzFzhKe/VJwuOBmq7UjLFbadpRWEw4gJULN6bYqMktxbEwpRbNJglsW2iOzBDDydl1fTUDX2Zrm3P6q1oWVXd7iFpWExhe51ERRRBuqz5OEJXhTw/jjh/4r0/zJ4xL6hNARd3Pzqg0epeoebW0H0y0IQ5UamgXrPMSKH9llQQmZ872VnzTSzFWfJoxh4BworD42lZQ/kqrxHZfGx9kSsl9Q578oFo9SsV45ZINL/T7NZsLaLA+1ahNhlupy7VCPdlfJZZdCz4G1iorPkjtUn25Y01odEonBOi77a21trbQhCFYI12hGMLQmxuKNYoVu72tgYoWtId3dABgje4WfKbLiMnbrJshaD8/T3Xde5HK7ruu6yVkongJMNUTiWmRsbVa8jjpX+6HZ0lFjgdDuGhy0OWkoscEQQg0uOhy0laStDkWkIDhnHBqteSsBFA8NTs5K1FancNblkouJWty1EoEha3LUVqK1uRJKz2WGo8H+nQvf0yBdNgXTIF0yBdMgXTYF02BdMgXTIF0yBdMgXTIF0yBdMgXTIF0yBdMgXTIF0yBdMgXTIF0yBdNgXTYF0yBdMgX/8QAJxEAAgICAQMDBAMAAAAAAAAAAAECEQMSIRAxURMgIgQwQWEjMkL/2gAIAQMBAT8B9tll9Yyv2ZNkviXLpZZK9iVF8EWZE3GkQ/vx72PLUqJdhIa/BsJ9J5FBWzFmeSX66schyY43yO6OPA+OUJSJOSQrgTbnx+DHBQ7dGTdEI+o2QjNvnsb/AD1Mz1lSMr0dENHQ5/yUJQrgjlHL50Lo2fUcRMTccbkjFklOdGrlIhalsZltIhihF2jTaZHHGCdCgc2SeqsRLvZn5oUqjqjDCnZCErXB6bJwblZHFTseORGMl3McfkPwP5cCGNJ9yMYxHcmas0Z6R6QofscH5It9mOMWI2obGr6Q/I3RZsi11/0a9cibqjFZFNNmvNop+Rp+T5eRJ+Sn5NZeSMaIp27Jbbcdb+0iyvv/AP/EACQRAAICAgIBBAMBAAAAAAAAAAABAhEQIRIxMAMgQVETImGB/9oACAECAQE/Afdfgf8ADeLLJdjLEx9C78DnTHhlieJS4kPUcn7GxtjjZs/wetoSkPkkK4km5EY8cMYlYk2XuiWmPQqL2aORexYZPRF/rZGTbO2J7sntiikyrkKKRWG6QiXdnqClqj04/JGLs4MlG2KGxwZFMgtjHvDHXyJJHZRxOB+MUTiJjSYi8NXiObLy+zjmV/BERRTNm/sSf2UymJCHd+evP//EADQQAAEDAQUGBgIBAwUAAAAAAAEAAhEhAxASMZEgIjJBQlETM2FxcoEwoVIEgqIjQGKSsf/aAAgBAQAGPwK1+R/2k8tu1+RQhrH2k1DnRorA4YcXEHVWuCxa8i0gAmFb4WsdhIjE5OgAejT+DGBTagZoWWdo4yoGaDfDdiPKFVhzhYsDo7wiGsJIzutfkU0NcznhluSG+3eq0OEozajixHvKfMb9TTahqrcLUTFny7olQFviL3u5gUXjO3rR1I7JjuUglGzl8HFLoylBpL4aWkGM4VQZiow+sq13p8QzVl1r8im7rjGhTZsyS3JOBaamVkslksllcfUQmuzYAgAmWPSKFOapaMkGSXEHM3zy5o/1FpHovEPLknUzTBh4fVPz3r7X5FZlcRXEdVU7M3WTuRbBCNsw+zexUplo50RRyOAYWME7MctjdEqCa3WvyP4I5o3N9CRsO/5GPwfyNxutfkfxlsA1mq3cI/tVf/FVrdE0BoaB22PRQL/VGEbrX5HY3Wyt5wC4goKxTC4/0qvOizUzRc1zWIKSSuIriKwTSYXGsOaJbCJ5bFr8iq3S7hCgUCw4q3NX2i7OEaRcGcpuc3CKIthBYolcP7QPrdi/inJ/tdS61+Rv+0UJ7qgKiITUU9ylTcXY8/RCHTKai2YVLRqHvcQeae3sn+2xa/I3tTkXOdAnsq4j9puBsJo9FW7lg5wifS6IKEJqkrmh73FOd3TvbYtPkb2eyKDOq4XNPrdCMdrnEMdn2UuaQm+yNzfe5w7idgyin/JC8wjaOp2uaL2H0ud73lN+IVFmmG5huCKKKtPkdmXHVZoOd3XCdVEQgKaXUkLidquJ2qgzdUA/S4QmujJZnRNgymlBP90brTdPEb4cJW6xqqs4AzK4SfteX/kvL/yXlfteV+15X7XlBeUF5f7XlftUsD+1Wz/yXl/tY7LlmLqEj2W8AU53c3u3qhyw2nF7rdMzsP8AcXNZ3TbIgl5WEZESFw7+HusLxSE5rKAIWtqPdDwJnmmh/CrOzYA4FMfzyuPxOxACL7V1ewRo0gK1+RuGKoCbaM3qVvPvdZqPEwbohWVmXl88ysHLAnt7SrRDxKNiqb4DpHO7xrWnMDst3gbld9G+Fgs6kL/Ud9XWvyKtcXDhVUWA0Km53vcxzsky38QQFjBEMbmvDgYJiUXYhBYnWnjRPJCzLwJCBbaYpKaHZCqwh+Ec6Zppx4p9Lvo3kM5qeadavpMYbrX5FMaDGM1KdhFbK7Ktxa7I81xN1XE3VcTdVxN1XE3VcTV5jF5jFxtVHt1XmD/sq2rT/cuNmqO8HPPblcSUYyTrR4kN5J3jO34o3+N1r8ii0iQg0Zu/FzXNc9jNZ3xcbMRVFtnUnN11r8jset0XVCFM7vqV9SvqUfRV9lAzX1OxVTs2vyO1M1WazWZuzWaqUa5qpVCs1ms1mq7RccUmua69V16rr1XXquvVdeq69V16rr1XXquvVdeq69V16rr1XXquvVdeq69V16rr1XXqurVdeq69V16r/8QAKBABAAIBAwMEAgMBAQAAAAAAAQARITFBURBhcYGRsfChwSDR4fEw/9oACAEBAAE/Ifuuf/Wv57Xqq/5/dcwwQoWdbR+MArohbtAzFeYCkTYQclzADjWQe/8AEOip4K2dZcqVK6mwtYCEfb5EALTQEQIaG5F0Cmqb8RKzNr8Ew/ZAaRFBKSYfazN8AC58HaH2dZkvntLCDeDSSXAymmTrUqEod3b2j1EPiaMpslVHZNrbbhsLXaNAqeY9DxbwkvRfoPwhFlII8wG4sZ4tvSXNQMrVUtwOIMjvcRbuNxBleZq1kufdcxAazo6nMrtrG0PWWWQdqitSPMEg/wCmfSzLGPrKzHWNlyJMYDxCqytQypX5l1jbQOPEWVtG3iWGzWGnaJ0rQtYECqLbBt/sEhqK7INl4m/EWbgtsnmaiLmvX7rmAlBHmf8AY6S1AfL/AAEVhSOGJbmyNGsRVrpm1hqTbd3Gcqu52mu1a8+ZlYwkSbnquutRfLCGRRbW3T7rn+FSpUCAzQdEE+nOZTFJa5rdy/eWdBlJd0GV0aXdWo/1KBQUcS++nQfa3/gELQkhoJqdNELQRgEoB2E1EPpm4/mbtgvLWa3A6V+3B3nETgmO94OgLZ3m1YZJpHY79PouYN4QTWgcz9ormLDekqj4ZYoga0lUrOVFO4eJhIrdp9LA3WVFtmk3dFYin9MS/qgY4BDXH4RgtRrzFa2MZdI7QrqjBbyVbHE+65haaJ2ZIa8i95UAgaBG+HbUxma7zBeVDZHggsDpLEaC0cc4lMiruPWS9xnuLHXSOlwMsLsENdDAOvwjvnOg1jGGOj6rmHSrXmbRwTPKjW+sIt78Sloo3rHT5zMHzEBNMAwkWhmXA7vQ6yOyBwviqpiJhnbdi1+RcFG9B89ANNCoW5qq+YqPfLI9PquYd4VPWrfzLR2hdLUotc3jy0lOPetrGcMfiUaA+Y6GgbR31+Q9Ya6AZFBGtYrkK5mL7SsSl1iXGz0lOb/c1SxHDUqrQnvHZcr46YDt0Fma/uj5yoMwHB6GInK1jPpGDQOCotw0ZR0blgtEqIBaKdFLEqKQblJUmElC9Pmdph9AjFfABCdJz0RiuY0aXDXn/M9glSgDgqNEF8Q6EJQd4wvKksXmaz3Id+SaJfwB8wfEs94m54mv2MRi0jMe7zFQq2tu/RwPVPiNocT3KXR8wMrUy80VfazK+EnoBl1YKNmsTQDS41QrwZmKnFmpozPeMdOVw6mEXOH2CKBgt4gtIG6wJkR3lAFtGDBH/dDD/Xsm1xtuds8xitQdJj+cU+kyjmCp3fMwfBjLPgaGo6U1IwlJpcJiXvbLA1jUNdfARMB37K3X7oFv90X/ANYf/WcB7oAfsYn+xjw/dP8AoZStpyMWmX3TVH74iVrU7Spi56wlIwXamYIrJU56VjlMXE6tth1SiKIsN5arYMwjBsX+7ouC1er4ie04VYd6uYSpvura1B16xq6g7YVHpLsXCoXmNx19V6RBTc3pAqC7R0zUEApqnnpWm8PwSyELIEvLMBEY5vMXi1pWrBrfZhCgaSjtLUstCC2UEv2fwxYvefhloWjI1WYgf8NzVy/bdzhaK0O3xKA21btcuyq1MuEWcFr8mVp+w7y4/s4gYlRqGRg3eJUwcMsCV7JVOGH6W87C9XnaEO4nl9RdRbPWapn4vwxjpUXMxR0xZn1gHBWzhfrBPkVnK1V7ylxZaOPMynMOdMwCrorEPW7Kc1CjdcZRu6a2SpmfbE0QGolEZ4Z8xqxl6suVsgXV5mst9rWPEiqWkiovk4j2mC0rrfQug9swjo/0mIxOV/fHmQ9Zvh6wbj3YVbE9pR0oee5QjSEIqFBohYJt3iIUK2QuxnyZSqOjaf7lz7LmVz1Y7QUHK9ABWJqdFZmZhfeHlDrCrunql82d9O+iby4hk9ZcDamau0YTRJ0Vk7fJ0tqumgITQcy7FnzGoeS9dpUsmCD6m07yn2mDT1NpgazW5tK7sqtR2jtvLMGsUX7pVTwmhjXc2iJdY+/3E7xdAtPMzONO8ZORcHCbGOGmC0NdKGdWLB9rhrOUYqaJg7wm9cri5Spq5ZbZVVYu8VVVy6yiqWCjxKrpZKmrLtmKZPl3iKkTWoraDyQCqWCiY6tpXpMKWp1liq86ygtdFENGGUI8D7zVjSDUTe7aoA3h3o92Pdj3I96Pej3Id2Pdj349+Pfj349+Pfj349+Pfj3Y92PdiHLvQ7sO/H//2gAMAwEAAgADAAAAEOebwnQQaeTrAk/aeZaueouFWVZQcVlsSyPn85eBfpA7lpBLgANox5bAzfeZH2Wk01KRSuDCVc2VmB7jBLaFc5nbpH5B3xTRpHP+9En/AOiwt5keo/wO+8KRve6M7lnL/R7RXsCMv556CDIYii2xFHkih0Qz9x/0L8N30AB0KID/xAAnEQEAAgIABQMEAwAAAAAAAAABABEhMRBBUWFxILHBkaHR8DCB4f/aAAgBAwEBPxD0sNYWg8ANnoQOb/O8td1nt1/EXpFnKF46CBVcaYx0tiPZCqdDf4PHC+CDuUdJYRSqUzDCHLHEtEXUtgnLhAotUOC0xQyB2TDRLKVf9kFFPshBTrvGZZhRuMrSYFCiwMNylmWS9Q6CG3kr7xHWVB6Q1rz5gNmr+ZYLvEyZ1KVyQ9YQrqOjzBwzf2qHFghi+cqlnzEdhrdA5dL8y1d2RUamhe0vYVlzHtT3vxHUtxUZohm0i61VRUEqMKqKbxUcacmaCdfaVG24EPhBRLpbDqMygRIpwQY3LsXHG79vxBBv9+ko3AMQRsmJSAI3VUAyzpIisAI7/BD2lTBKtwZqWEsiWq7fM7IS4d0WCjbZeP3zLA1F5FXxRJ6B8N53LBGULPLxj6c+7KgVC2oWOZZLOGJiExMSxawDqN3gcK/gYHD/xAAiEQEBAQEAAwABBAMAAAAAAAABABEhEDFRIDBBYdGRofD/2gAIAQIBAT8Q/FZzDtvgd/BpNiyvl1amGcHLYiqC75/BuWy2aN2bAemGIbJ3PCJCNbB5zwvZb4wPZJlSTGZ/uMTGHGHqV2fpWHUuCeo0pF1P7bWQx9eA+BPeW+Fnl+2MUj6noQ+xI3J4lEI2ftA85wLsuscR7HA/YFxhO2ujbDdFxHWSDJ7kFUMOSi5MiNmGQ7Dey+xcOXtI9RUgjBd8J1+7ee7bzZ53+v6jB7/7/F9WV9mHHwQuJb4JFb2ZQtLFh5GTDVkQ8FZNowRdl7o38kn1PgD+S/ns4Oqy5Hnfkce2lp45c/A394dnX4Z+gx4//8QAKBABAAIBAwIGAwEBAQAAAAAAAQARITFBUWGBcZGhsdHxEMHw4SAw/9oACAEBAAE/EP7HL/yCVK/Cokr/AIQNt0dlhdev/eP9GUSbc47DMXEJUyqrQC8MkIVtujLoaW33zFW8n746wumztKMzwB0VhLY6/wDASyWrSF2o4A0UIGvBvHVFJ+DCfhF7QGqwiKjVohmugFdcxHhQGVdCAClWVg1SFSyhRGWeJJST3BV3hfjiMy/L13VPGRjhkIjskrY/hQha2yoOWjhvDiL8kLoUbLDAddFFrNa4ekfMhpW0Hp15lQJb8BmESLVioHKw1KSxVjFNGU8zdQ1lrpcZYE9Da244Z1ALVg1cspqQRIFdeNzN3XlXeO+X5C6pxj9SnaCdzNDrXnCXUYIiQFrTfk1gd4k5GQl4W8axWAKQZda+zaswZFhESVEBeHW4zKyqaqy+Jn/RlAfzlLGyskoGtRKgNlKzTLkLm7Uvausps1pRIMzbvUsfJCn54IoKd7MxpKdbgDTzY9osIG2VS3b43rLGBgcrGdG8euPeNM3bnUPlA4nAyiXfPEJubIHZSpkiTE5cmrOnWW5DBFK9j0ec1bSB0DYXHmgUrMdC4z4YlDMyLAbL2tzjSUDYBoKVeuOu1afn+xygYQ0BhD/Rz7BKfB6WNQIENtMcTETQDhlqSU6nCXaUPlGm1IVm47gWjEQzKLdlxH1vOthut1KofOVBhW7dQtLlW2UH5R1LXo7qrlSoJlQ5pDB4ukr1RNPRe/4/scvwECFoSTnlViGjyQRHNWeMqYtnftjQ94MoEOtKmBvNLwS5rV7RlaTLgjH46SoDVDSMVmU/0gh+xAMw6AoO0zZYYfi6j+FKgQPyTlJxeUSqksiW6O5LEhrmJQ8oVBqtIs/jBmeU8walGN6HrLfQoRFQdp1kwTNTEdn3nLoRFeHp+zmCp0dG8MORoDePTCF/rOkcFS9Hc5iq5tSo0/gymidGCWs0TmtKDu4jasOCz0hqM6om6PkGxOkfVtNK4v8Acuaa6f7lQ9gH7lyLA11EaEpK1UsRwPaJfFPFH9RFDQBqssXiZ6FYmgF2TIEOp+ZWjsFbtbd43wPX/cSEyrGhlyUbJCXK0nslxDT0nrB0Bayqoz1jX+jKEErfmSo2upAIxFPkO8WEpioO01pjBmniCyGOv1GX2hZmr9j9QDYDBq8x/wDkct2QwI7NQF7FpH0MZKK1mSDEtciym41ytrZ8YKBUHBrDGfL/AIlzVvLdNkxWd5Y+LZ8X+1GJcrX2SIBzq9SWVUHLMgNbvMZ/Q5QTBIBRS3oHyyg3KPpGMHDwGqa4G64RqyVNVxHsIfOsNvVYINzjsi5YqlApm1LF5f7MnMbkt5GsRdUJwPB4xWXV9WagmNChTe0yHkX9TD5rWb4EMlgTWxd5snS84/lbEYmcQxJX+jVKjhNJPWWC49wvickXIn6g2FA3ut4DFM4B6EEdFQITuwlfTREAutCyUg1oAAHaWy7mP0eEdA3+qSx1ibmJWDSIuJRKdIi+5+rD9IlwuGpE+L9xpxointjR+MPSPOYH9znZvgv9QdRp+qXg8I1A3PkLKxpCEWgPNKBQQqVR7T7sv9zd9owZUwYM7vhU5WUw6JlnQ8hUChBqNWRqXJsreJqMUh3EhBVQPP8AyFEzvFUUhtSWxbpCpAiJshjulek6IY1Mij3PcIi3FufYWH0ryiJS43hrpJKrEdQUAL2u7iAigwO8JXL+qXCb09YK07TobeQqXcGrpdFkr4K2mzlDjGvWLzBHbaHuxMndBbti941laN+Ip+o2hZYs4J5KauzC4EQ1dpwXrM23Kj3DC/OA1EqL8z3hu8GD0xcvnf6iUfRl0uqpYPT7yhS6R6wAksa9LuK0ZFPrARse4iGpZucyitYLGlstkDIg3Jq5ECauxLvqJt6QWmBPZWxCE5oZ7EwoqUFb85RtFBQuW9/GN4h4L9SwWIKplQd0F0niiR0i2uVwRAKUBQZJeC+o9olk/wCG7BiIQuS6bwy/l9b1FijzwVpmFIKb/XD2qKsOj3gmYovVB03UJkyzRas0l7RFrTWksd1sPD9JIhxZK9zMKeeJee7XoeBoRJkIj7HYI9fTWuvYJdJDFyKe1iX+iIPh6woIvjLU6pIlcB2gdbvY86lrlGo4I9RvCWtPibRyO5FyXK4w2ovxN4BNZW+vIAOWzXVt1F80RYAUC5DFxMQO+jENHem4YSw4qprjftBkdDp1hlGFekcysRegQt6yyXtaqar5EAeZsbd1aYLpikjN4DZT3IsEtd7iq+YtC/BZHhNdIArVh1YunmgUI0HwlUfIS69YA/dvgqFB71KYqr/KgKxBOjttqy/CCHDDpwVO+XHeX0xhqMgcHBnldIM04QtgHxcRgaAsVTTVXrLv6FoDkszrLPbFbpd4ZVOhed5P34Rc8YXFGJkiMyvXpz5KUWmfCO1r3ULLNdKGD2iG6x/ij1tUTwsT0SK8R9uBNkzaS3iDjNrRpvGobTrlddgNA97jiHZ84kpbr6MQhx9fey5rEqlE5IzbEyLaXNJTT1vWWSlkDQ7S9iWbxn+DKBBC7YL2jqUv3FIV2E5NZupcPGKitEFtA0H4dfONrP4JDmWbDHwIl+sABWhQpdOWNY0C4gEqYvXV5TFvZl8a8awy5Ig1oEvnEqKjALSmvgjUMoRdm6LLLSBBRV3hYJEyosQwPepapdDI2vJg4lEZ2ulRfLBTJ1p7mNUdIBQF3dDrFaq0KaeLn+2iyFyu3BDcCzJa8E9pha0R/wAjVFJtrdC59AIh68J0E81U+XWMQdRFaa7jKQZafAcLq0fDLGYObNMx+mn1v4gP8/aC/wBPaUF/18JZfEP8TNdp/mVr+Xwj9ZBBh47xkD0BkL/eexAgkU8yDqrzWKhXGbBVymNWLQBaLaEx0twvpfTSFnjq8To9dGZSo0s39xLRCwO7btCBOUm8b/o85dEqEQc0xW5oqkGIAtqXyYX3YOcHbJ2nkZeivKzkB4jFN4oaMVbfeffwtx5sRqVd2MGHMZTzDU7su/Hgxrjd0jND2n7mmNYGIYT3RE1ycywWaNDiBbRrEImlimIvItDrA0lTQhRwuvZgUBkrS6b1MIidQ1br2YoTM1TLJ+mY1prV0hUaU7LugiAAKi0sxEmoaC1owRrdfFq66pHSQdr2aktHaXbGO8GFvBho3il0Ba34fDzhboGAIGiIBRReC3rgzlw46MBACApHDpKdUMBttCuFMYVkiKcOsM4INWbPBLEY+RL1Nl05hsDwYCCBzuxi+zBAiI0mSYxoUOMNVcAJAIX11mVrJItqmjAwEZFUrFYiwFLS6sEITfFWcIGAwEDqcSzyZqXi7rzjKs4yzG3I4vLfqzBc6spmBpZsYOIuEwVj6PQ8oEQwAXhAovtF6CaXJ/L5sypwB2IoxqNneXcbLgdO/FRgrgRQhLqG0IWttYiWPI/EX+B8RbXyHxAvgfE+mfE+ufE+ufEV+D8T6h8T6t8T6N8T6N8T6N8T6N8T6N8T6N8T6B8T6B8T6B8T6h8T6h8T6t8RTVvNfifSfiLNvkfiU/A+J//Z",
    "gale3": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgwKCA0MCwwPDg0QFCIWFBISFCkdHxgiMSszMjArLy42PE1CNjlJOi4vQ1xESVBSV1dXNEFfZl5UZU1VV1P/2wBDAQ4PDxQSFCcWFidTNy83U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1P/wgARCAC0ANkDASIAAhEBAxEB/8QAGgAAAgMBAQAAAAAAAAAAAAAABAUAAgMBBv/EABkBAAMBAQEAAAAAAAAAAAAAAAABAgMEBf/aAAwDAQACEAMQAAABCSuhwWxwSHnu+iUpByQJJ0U728rOaHqVnN8nVeXq3ySN2q8SE8hNSsIRwMJaoORiQFJnB6rOCWla17e8rLu1BbM1zPLBS7SehbQ4n1dYhu0zrNiv0ptc4DOTbALPXpc5LhQ0y7EOU7hMF5WJWrbouW7aZtpdhhzp3ac7SylNODbl+abqVdb6VYtSM6rOulauks1UrdPQJMsAZJv1uU7hUlS0uly5DSMk9vQr4zXlbmpIrPdG/P8AHW9V5wlzZSi452zy8730A7a0H0gjrz7PbV0Op7S9Kd7zTZwqaqQ0OBf54thNvIrD1wQwEw3OVbhDfPuiV7jzT1AghS692Zi4uMBASVenX7MWdz41rpG3evlM75adVOdmmjlS2Wyo8RPsuUtE1WTi1BPVjNJCyjJmvv0FzpaQXwGZ7dDIgLuPNqnpN+z03B8OfzzSAtRed5bXp9MTmuV6OgjQIjJ0oZ589gDrTn1aSurRsPcRIyCR1sUrIA4bLFI6wF22YHMQOE3FBhfLfPnVd2D37aZ95pq7VPQVIezJVGZi+tHWrMQdI3gnpW1dqOFIGoEiDMygW5UX0VWh2P8AOMaqGISOMVnW9htHDpDxmS3mocCVWbtJJjO3ckiBtx0FP/Nenulr9ZZLENjwCUDhSC50D6N0H5v0vmhlVvlnjYgI10aszLu1s7G2+Oy6Yboj16gwW3Heu4HUiOD9GRYe6kgkC8wbgPmPfUKVTGgPAcKJQZY98KZrRPrOIded06XaJ0mHJpwXayJWk6652vQrelhWlYi1e1ZLUsHOzg707wLZ2qp5zbNvts4Hux5HXZIlySM7yREkjJJBySCkkCSQckgSSCnZEd5IHJI3/8QAKxAAAQQBAwQBBQACAwAAAAAAAQACAwQREhMhEBQVMyMFICIxMjRBJEBC/9oACAEBAAEFAr3+P/08HH33fRUERUsIbEyBmdiLuLOA/wC3Cwoaj5WubpP27WzT/wBuglaXRSNWxLpEMhe4FpV70VnPa0STNk1SOeZ35+2GMyPkrbTSqut8U79yUDJlgfGOlEAzNlbm6G7jrMbX70RjNlhbvQ7z8F6u+iJ+luvUtbtWD0yFkLhYUMm297Xur4yRIKyuRbc1RrzNYm+LpG8xvjAe6aXckdNqfufEZfz63fQCQtTlqcsnqFhFvCZIWVQ6Eue8ufqbPDBK3Ljqfjrzjq1jnmWIxDpd9H3x8rR+JGFGc08EotPSL8KoCIWFhY6wRREfoW3Zl6XfR9gCwsdNzIeo3mNvcyNXdTFbzk+bciYzjCITItRfwCFhRN21ugmQ5k6XfR0Cjic9MpFCk1TwmI16+8uyC7KNdmzHZMXZQLs4E+vC2OKNkje2jXaRqUNjJpAmWEQGCDcdLVlDP0f2el30BYVWHdk4a187IzqVx/w0HfG9+hkNsSu1Jsp7nUpbZjlkulzaLvglk24vIKWxuy6lb/KD6e86nn4cZR463fQgqHALlO7MxssaJrG42lxBYPw/T2/IVEdVvKfVEsliuIhT4ge3cZ2C06Zc9Krduf8A8k/Zd9HSp6ieIYRPL2sAVtkTI6/EH7WeLO5oqD5AUbIDrE24K/pfIGM7pizmcnkO5x8oKP7HJ6XPQW4Cr8V3n8asjWrKuHLY+Ip3/H+hqUWFlPryvkdXkY2PiKXmHbcmj5CedXzByBT/AGQjLpOHq5/jyfpR8QvJ01ona8qyV+lL6gcwqD9YK/IKVx2x/AJC33qZxdMTzKdLkCpB88XDn/2rnozku/pv8Ik6S9oTzqkNhmZJdbWyOYzeemlwQllCM0qc97gJXtAsOCNjKMmZNxhU5BbD+cOnCn4sk/n0ttJrjhxKjmLB3YxLK6RQxGV5bXYiYEDCtcSD4UJIVvRIywrchWuFYY4fEg6upIGSMLcJkjmLvHYlk3JP99L5GxVdG42KYaNPLgsKA6WkpgL3mGpCb0IryQ04nQVIw+zcAisVoYXVLLq2iDSZ5LzWSfVWDGVVf8rlhYTWlzux244mt1YYrvoTZXsG2Jqp5OE3+FV/ybkYluW4CyZz8XIm6Pq31E/8ypp8baEDSqEtdi+rNd0g9qzhQxGZ9gtqulmll6cq76KbdVl4DZY5nQuJySVH/JUTtE0zGWJHyslvuvHuSWj6lYrxzy1tJoWa7ImU3NZanqCaX6rI0sUA+RftRzugGUyHNfpd9EB0V/jdEog1zTwYnBrnxBba21trbQhQrBdu1OiaFtoMcu1Qr8lrYGlQtBT8a4GtJ9x/XS96IpNsxOEcaY7SnHJWfs5XK/JHK5XK5WSslZ6CTSFE4ha2whYKu+jrjgjC0OWgosIGh2MEENcUGOK0lFhWk4DSTtuWkrS5bbkRhAI8HOOgWVd9C4RQ6aitblkrU5Zyg4haitRWty1HAJB1uWorUQtblklA8LAR6yUopW+MgXjYF42BeMgXjIF42BeMgXjIF4yBeMgXjIF4yBeMgXjIF4yBeMgXjIF4yBeMgXjIF4yBeMgXjYF42BeNgXjIF4yBf//EACYRAAICAQMDBQADAAAAAAAAAAABAhEDEBIhEyJRIDAxQWEjMkL/2gAIAQMBAT8B9NliesZX6J3XBc9LLJ3Y6o+iDtE03FpEP78etsnk2sfKEkSVFiZZPIoK2Y8zyTr60YxyNzGrOaFXgf4Lc+STlFCuCJtz4MeNRfGjJOiK6kiMcm78JT79pn7JUjK9lIhsdEp/yURUH8Cykp93AtJMz8QMLajJox5ZSmkOLlMjalu+TN3SIYoRpjhumQxxhdCx2OxulYifyZuUiMtqaMMO6yEJXdHTf0Tg27I46djxyshCSZjj3EuHR8qhEhpVyRjFDuTNrOmzpHSFD9HB+SLa4ZJRYixjV6R+WN0Wbkblr/orXIm1wY7tiT3DhzaKfkafk7vIk/JtfkqXkjGhJ2T3XxrftIsr3//EACERAAICAgICAwEAAAAAAAAAAAABAhEQIRIxIEEDQFFx/9oACAECAQE/AfGyy/Nm8WWSzFj6F352SnR6NDLLxKXEj8jlLwbLY1ZuhfwYuT2PkkbiSbkRjWGMWxJje6J6Y9Cob2aOQ2LDJ9EHpsjNtnchPdk9sUUirkKKXQlh6QiXZPoUqVHxx2Ri7ODJR2KGxwZGLsgtj0diGOvYkh7ZRwZwOAojiKxpPwavC7zZefZWZLRE9jiUzZv9Kf6UymJCHd/e/8QAMRAAAQMABgkFAQACAwAAAAAAAQACEQMQEiExkQQgIjJBQlFxchMzYYGhMCOiQJLh/9oACAEBAAY/AtF8P+JPD+Gi+CfbsW+W3gqcmjDSHCL5Q/xtP+AOgnioLGh3pkls3AoQKMXchn+EtFyg6xa73KTgoQBo3ScLkbTCIRNh0DFFgYbQ4KDcRVovgnWXCzxBEqkc6kbeYMiQVS26QSRBu4LEHZsTHDWDRipJmrZkCj/U53U1bTYrk8AnU1Je4GGt6Jj8LWKdFshziTdhcvSJdZgC1Hyn3Ok2rrPVPfaO22ILUYwq0XwREOv6FG1RmCZuTjZxELCrBYLdqlNczdxIqo6P7cjGBvCFkYI0ZcXOtZV2gnU74AVrgMETZ4RirFn5lOMG8RjqaL4K4reKxKxOrNVG9uIJC9YXRiz5Ukptt4aWY9lZoxDBeflE9TqRw1NkShOJr0Xw/hCip46O1KV3xH8MbR6K5dq9F8P5uumeq2YHYLe/FfZP0rAaBfwU1/Cht1fyiEa9F8NTZbK2iAt6o3xC3/xXuKuKmRC4riieiMzcsSt4qyFv/i6o2Y+0Tdnq6L4VXIDgrLRAUOdfW7ui7oosxUW8LVRbZRbAvR7ouiYW7+oHCo9W3p6f21dF8K3mpxQAk3KzELuU5OdwiqfmouL4+kCHT9L7RbMSvcao6Gt7Ue2rovhWe9TpdACvtFCwyDOKYr1CNnd4qaiIwQuTVaK4qfmoq38a2i+CFTUUerjUE3srq7ulTiGOxUuaQmpwqFUdRW7uijVovghUzsjCtkQ0VAKE5Ufap9ZTOyuWKYSimOrd5Io1aL4IVN7VSTcr3BSjsnNEAQgIC/8AEbMiVvOzW87NQSVC4ZLdCaYwXEJsGUPi6p3fU0aATsVxEhe21XqyFEF3zK9v/Ze3/svb/V7X6vb/AFe0F7QXtfq9r9WzQH9V9H+r2/1WqG6OFVxhbUHuEXRE6lDw2bkW02HCVbY648FfXSeNQaOJhMZSSXOQs7pTbQ2iOqDH4XotZgvVpR3Q9DelM9Tdm9MbRw4FMfxwqGpARfSOwGAWDYC3G5LRfCoCZb0Vtm/0rf2qovIKja59jZxVEw0jqS11VGwYWSiO6d2C2zs3ym+g6etUUjdu1cYTHTs4RU2uArDRJUvd9VYrRfBN6cU4Ddm5bBiVJxqf2qY7oVR0vqiGqjhwhgxXpwLExKa+Re1F/rQvTLgJlAtpLV6YXYJjw4NA+E1k7UzUKzY4q068lUlK+4Rs969F8FSPG9ghQYmzIdVeL1CvwOKue3Nbzc1vNzW83Nbzc1vNXuMXuMW+1b7c1ApR/wBlvszW8zNTaBfwAqJKMYIufutX+U4jZYOCirRfBdQcQn0gxNc6/FcdXHUipzQJtKG3v616N4fwlYIjoh81fUr6UqK/qahPHX0XwrurxWKxWJV6F+CxWKxUSriscFisViu2uxrrUMEC9c+a5s1z5rnzXPmufNc+a581z5rnzXPmufNc+a581z5rnzXPmufNc+a581z5rnzXNmubNc2a5s1zZr//xAAoEAEAAgEDAwQCAwEBAAAAAAABABEhMUFhEFFxgZGh8MHRILHxMOH/2gAIAQEAAT8h+j4/61K/lm1waX/h93xAOwUac5RQdGAezMWToENtYAbsvxmYAvGt/EIdBtiO7rHUKSVK6hbRrKZMoB7xEwZ0qCeYRujowW7NL0iS8zatKjIIW0yRSaiken1fEZQpCjrtDDDY4cTCnmmHjB7Yu46qlQmoilaC3aUuLNWC0+yYRrJUeo1g5YOlx6Ke5EA1EowSwsTUpJ1zRj3mmXJrqW09ZZhM9yuW0rOuRZDTnOkaes4xXx0+74jlNYbqiqXVJhTFHvbhpEsqPSCdrh/ph/pl9j3mDEIl7VM5HMJctTAT1H1WUM/1DFO+1vYm44MkMYb9Q7kqrLgi7TQQmFT865SlGHUzcFwCkbP4fd8TVA8M/wBif7UWKU8vSughWSVMZCnmWINdPZUcXFbYaLATvDTrYb07xW9UYwkSWHZs3XWpWFXEtGdg26/d8fwqVAgQit6SguEZZnC8+5BmIYthrU7BWn1lz0GWLuhK6Dl7lYhVQA7EwXZ1+z46kCWQ6YVDVazJuCFBWDGq8MdQ2B3HyTS4eV3ymyOcpjXODqxldSXiusyaIYty9eJVupLjz1+j4lWXKgi9J4T4/XcoafaCrLHRJ2O4Sv8AWD9DndHklpVoR/8AcLP3hBEpLCC1Y6LY/gl4sEvEiC6zDLTRWkAjALUjeNY5HvErp9nxHTKawnlS9iUakyqw7IY2MR8WZPuJeWaXURlYXrLkPZyhylI1G80eTWIo7zSfAhTbDGCHaaplDOBEWOp+ZYHOOxKaMx6fV8Q6OSYOgnfmCRQC/SXtI8y9vclPjiNDCtxTHtMuggtqxGbD8Jg8qbTirY4Y9hm7jgs6LspnAZjxcWz7qYKj1+p4hCpivf8AGUJ4npgW7gT+zUrobcVmK4X5mBQE7MqUUHYjvU4tZRZ2YEvjtVrACUq4q9aIrEO0GijDRkBS0O0NJxffpYI5gpOuf2bRmJCesKz2eVNtKAR6YuvxjFklJpBrpw6TtdGVeH5dLkQ6qjst3SXDx+YkoXH5m5TEB5md5hX7adDOQ0HL+4Vg0IAJoPT7HiKVU1HS8oypbWkZablNWMXwfYKmfBFR4Qcky4mvmHallvG2rG+Yx20jxATX6zVccfM94ijaixacaakzTF8oqrjEdrz0+54lCzFVFdWlZbLzCarGfgZmcGL+IVLr70ggtubloQNLLinb0EXSsZrpQbrAjYOYIC0FBHMi8iDq9tIR9TnFa63clU6t09JlTXN+JaBGoTHo2iGVHiXC8TMy9BtjtKMAebZqjGxoe0KJW6uxNVfupFb/AHQO73Rc/fNz8sHt90K/yRH7GPae6P8AuzKJO4xi5ffNw/fFjKyX+JvIzm8GWUHunxPQUR6glqyB6RzBQZINtbyObRUohFgNcPklrNQwhDa0JbgE2mwdo4vnraA3eoX2g5UAxcuBatVukdUdy70jIQbzSEPjlHSBAU1T36UDvDMmF4yaC2Otuz/2iVdBvu9L7z7xAuYK1uA1hGv4S9CVxMI/Zf3Fi+1vNSBpyuLAHV7cynX1V/U7TWj1Ln2DaX0qeTi5cEW8mXBAS8m9Srl38LLigVKQX9d7TZqnMftU7NInMuH0fEqdWM+EDiwjkRi0tUdvM5ljMvC/uCXzoawaB2t83GhClti4KpaMsxSltveIEXDGH8zbm2umZYltKxKE86blR4bDVm4Aw5QbSuh3AtRMLdmnzMrR3TNNzS29prKJ9XxH/VSBgY0nePM8RFwWLadkaosWkdIejtSYMwP7400PWJfuin55WKtQHYiyWyqxU6SNxXMUdDZpMVgNJmWO07woqjhw7+Y6tw10+r4jpEUEWUHaXFGC8zzbpatZb3mYXzDyhLwhc4+U9UvuZzod9inWXGEEW1hAyNZlkmOns6cEz+7bpeK6G7rLlTQxrzOHetYERhLiVtF1FAG9Uwg3VmVtZsvWFY6DRbtA/LWJpGBpgcGXSaONbrPaYbrGsxWF9h2mWq+YgWxZDQXSGAlY09BWd5bvPu+OldrKEPvHLHdUU1etzmaV6SrTvaxStKzDODiAtiNouAtAozMl30r0itirtBCgm8yGXZA6yxA1DMVMl30qIAXGiUI6ef3mrGINS3vNogD+LK1eSPNHljyx5Y8seePPHnjzx5488eePP/B1V5Yh9I1+t3f/2gAMAwEAAgADAAAAEHPKwvav9ljlIigkrIagO4f6rzmSUklkU+nQM0dSNDwq8uDeCyJcZcFuqytODzLXUfKhOg2XoyADIEgSjoCF8Y/CWI4PKFM1vZIcQSXuORoBHThW2o3ZZmL0l3Ksvkp66aFS4eRsDHnPWWiHeCJc9fZCOfaAIvX/AGAEEAD38ID/xAAnEQEAAgICAQIGAwEAAAAAAAABABEhMRBRQWGxIHGBkaHwMMHR4f/aAAgBAwEBPxD4WkSSwuDwF0+Bnv8A3uCba+3p/wBv8S8dxXUL7lwIdkusItk2MMKjpvo9D5cXw5lHUsODCcUDlmEDuJGuEHECmCuCqKdcdqSvaTwVf1IkU+yAMjXrPqEvoe0yiQChiWKLvjUzCYvUcCtpVR3UtaywHRKwXKdwheFywvcW8wimjC+eAEI7IXWcRsYI7ryyiWncK7Hh3Cy6X+5bn4jW+Uor04krLgweuOcU3ELDBKRUzG9wrMUhIo4VHJAqZAYzEAJ37QjOU/KQUBEoviNoMTLBHVGggxueK4pLv8H+QQb/AH7SrcAahqybWAMEa+IgLZUqpTogD9PBB2lfE75Y1LCWMS1XR/c9MJZK36PrnUNRbD38wCvTGbFSvgSQXyU3ncu11A2PPj98Z/wgdyqgGZHMsmJiUTEJiYgbYB1GzwH8TA4//8QAIxEBAQEAAQQCAgMBAAAAAAAAAQARIRAxQVEgYZHwMIHB0f/aAAgBAgEBPxD4uJpqHoO/DecW3ZXq5WlnM5t4tC0oL1eP3Pg3Fszbku8INcsMQGcuRRIRrZIOOi5LemQ7lj3LBjJCQYaEIPsoB3IDDtG9Leh+IbyS54sI7Is5LfITMDOI13gFDtD30YOXDUgCIkime5DTmfPPD5n8m29StrLklpseDPRMgO8nJsZSUXJHW2QZCpB5SZ0iJJ4Z9Qwy2jDGCPyEngYfu8Gy83/D/lsO/wC/i9rJ7mHG7lBbkuQDLHsRxShaWMsPEZOTys6Q6M8LWuwIvUi6N9kntJBD7L7bPlg6rPYP667c7adeLjrxG7CNnTP5f//EACcQAQACAQIEBwEBAQAAAAAAAAEAESExQVFhcYEQkaGxwdHw8eEw/9oACAEBAAE/EPwcv+KpUCV4GElR8RCNBsBdPZ/4V/TaGqwFpOXJN+FwirqYIrxB1j7xhQzVTZWO0MEE4i1NsCZc4hxQC2Pa6qufEgSyKmkvcH5oCBbgRvi0R2YwwkSIAKmgC1ifNdogSg6Zt4sUpBbIyPCJw+wrfAiqELaFS7sDKcaV6r6Shkx4GMvmec3fZCHh4U/DaLyGJyu1U6ZgF0VCRgK6B5RSN01aKdBQaaTDEGVW+M9tHXwCChAg1WuNu8YwtC7IwwKhm6sKzz3Ym5Hci4YNU0BNdfoawVEgyC0LxULl69txy1x59Zz1aKys9c12ljUasnEly6rxpKAmuJQPVg0GdoemQz1aNfDmhuVgDkU6caGXCNeLVGn3NdL8K/ptBTewTKvFg8Y41mwTFOazdZlj+wQBoDbNBA6dxUQjnzqn9TOBvfBxAF3sxUDzoFLcSn3lsgCRUbuZioCIVWqJo56juHYnEUA6n+TB8zugbrLdvaiheObmDMEz61hNE1IX6Kumk3eLp1YXQ4C7F3nmwQx6AXnJdV6RRtGEXM5aUdoAQvQKSqprTEDx/ZygNA3Wwuf0c/p5RmcESBCBnMrSUgaayxGseBAXdPKmEUdt49gsbcsnOJlp6zyDdHbnFmX2aAu18TXeT3bmDxSoSArYU0fWJKgmccSU06u0SH271Dn4/s5QQIELQ8ahsa6viXo5aRyahjVGezofEQUlOKgaRZ8peqq+4+CbPiVRUaLaNIxUQOAKKHY184iHegUEoLYo8RZfmISmBB4oXhDgiMdyNSsdecONqxxirAsw2Y7wRThILLMbIgFEG8eYZjqI0gdttYlZ0jNAhjnGVveHIgQAaBvDIBxm8GIKrQEb0Cy9hBM/L0m9OiVKj/bhDzY1hCsv+96adY0HuI9JgLnrlcWrWGIEirltd39Qfd/zzjW1dCfMbQ/JkjVxJYYdZaGvkPqCGF1H1G1lgWfUcd0crS4UYLyhcHdELYOWpWs3PcH/AFFkLWDHMqOrQiFVDD2ThGAlou0buFoMq4Tq7d5c/JyjmBuRTJZw3JoI7EayoTaG/N4sIakUzXXhBRYEsYjbyKMss6DyP9ggkvQ1dRU+UKG5ewwUtp1wLuXKXlaUS5shGIootnnFltVvsRQREbNXmUMN3fUoesN7yR40sL8wBr6e0RrKfT/UvLN+zG0O8QA7bu0Vvh+rl4ByRlAYWdbfgmSXBbWKZagUNAmWAbvJxMy3XlRMq0axNdiLUx6MAFXBlgBmTPkzOVxiMylFay70aVamOs3zUe0xbt0lDylmrcx+Iq23hBp2l1lWyCUkTSBnmor3nLkekRgYkqD8+EYR4VrL6fi8h9zlMn0i61RUuSvM4Qves0SPSCnCgAObMc38wo5gWxZKoB6AB5EfiI1XHny6Sp2m9K+Ypi/tisEbEmm0bxB2V29YBFBZqzCjB7D8xRFqR6sAL3YOF0+pOrH5ZPmbHHEPJkesrI1ZXgfx7RXYs9fCjinvOviPid8teEBbp/vg0q9Fjp7eoX8xekVlVl6TIxyWbwg/MLmpgR3GV7FCHoIMumIeIgdJxgLiZSBEpKzfVGQFUAvZAKR9RlQM19yas7oh2xj6l+1xeOs37cnIo/VFi7Kcm4KdUA8Bk/cRYfP4il4J+JLVgGyuhviZAJbwUUBx48qj1Vylqusbg0LyAQ2F0HuTWS3XUa+I2Z3JcBmgd0/EQWLym9GXjCjV5kXntU91gXjAqZQlzmuUiPABs4R+995rjN5JCW9uk5OT0jU6x2v/AEl2RYU9YZDY4Phov3EXCWXkhsiiiWnUo8q9yUZzcWnDy1A/bSmWuCt6QbwVUbggAWlwD0GAwaaJNQUoFVouKYp0HxMuErat/MAx5iE5h1RaQq7XBlzIBoOpAqbwV8T2E+wZrSAhYc3vL4ql1Qt4jKjIrlYOGvRjQl+Va+hrtBgpU63T5gzuJ7RW+GeMMiGIABUbJTB441Et2XZy5JL0419vdRUvRsAdBiEYLehBlWaU3XJPQ08IRCzvwDCWpF0IBYCAaWdX4IWRWSTdRDqU7HmEtYBHIkkqBFAIq3vBqrlwjLO2GcdvUwPqe9Xmjg8NV1QHxGqYkqHNNoBjRjaXFMGm3kHb/IDJAC5vXDoxaLDFHDfCByEyaSyyIBOcnTMrXzBxWpjSKrJurw0FxTB6NqGkvc0iHxahlL0vayLIqFwyHhzI992JOUvVgFJWSweAwwJ5FPHnUzcuTqgXT7RrkmF3QAqF4FDZVl9IUdYqNQJxKYb3WWjEccZ5Ro6enV2hjgrnNh6uET1aQitpq6H1P4iNWyvLygdA9pZDlBsHTtLd6JO3FzqK6ENckQdcwih/lmaLi/AlGkWUumIW6yjiRqXBjLxiohnIYHHskR2kNy+1MDBZKIScllwJLrUacVqHOZast+AxC0Gds3AKzQpWO7vew7VBRzqPsywt4SoBnnNY9bXQcWNDCXUbdW+d+RGQTWJQ7EobEznPOFf00hGQhFLGqI9brvEWJx0BrXfhEtCoIJ5MbIU2gqnH48pukwx+jEFhEVqLWhzBgSKIaFGbx3jWncDgA75qArwl+9W8NWGNyANAE16VHGRK7BWsJLQOouyzSwWFtIKKW8Lwij5SGwsQXuwOgC7qUImOUNMrZdaQvrcMollbvsxoVyiDkVoloGii2X8+Iq4FalxLnbqpYZOWp35QOyc6NPw0jgDA7jGfW+0NlmzFNznn7TOzVGoaLyOiRteJGOwrjWoaidElBkksL7ME+lKP04ft/ER+ntFs/r0l3eQf8zPW9/1KQL0/zF3H4dIEcUiEHbhy2bZVDvCPVwNonFnlwlrKFqVLq11/c5glXQW5oEP9+x6RClIoyir1rRxwgWmoVcpcsBw+EWAaDiHKDQGG8p89oW1YuoDkMNSVQUgzRCDhc5qHOwccDZCG3kYOzyWbivW5ZvGGjFe33jV8sA48+Z5K8WMEWvVV4stzuw8gCPBra9rlhTWOnL/kVdW11nOSgEw6+GISt7OMEILTqcZcGmQskyBFAuJIq0KoboZ4annEWkWslLU1rlzlXMpbNGvsmWW5s1sK9SGSMg1qtYI7jai61mDxKQN0NPTMfriSkRrE26wHjgSw60aRsIRL0UsPKMfrsOLKu8wROKwEHN7RLhmVmlX7TMoC9BriYJiWl6a4Vd68oeFGoXiJPaxRyZYDCLg0TaHA1hG+dhwnMecbrZfhBjMu1J5MI2K5uWUu41lmXVcxKKqAOh/CIKhcvPjLxFBLvOGh6QsUrdG67uNWjVXLMji66dWstzqbDstp5xOkAcASqOwShC1veOiosTbbbDp9HlNDIQckCUuSqjC5fWDHEUBzh1jwU2A1ZnHTLL9RMnKOfQocIncDrBVqrt0YiaN8kqUNK2lJJzkQXYsaxrjOkB38n6nN8v6i2qvzlOEj85T+I+p/MfUU+h9T+Q+p/IfU/kPqfwX1P4D6n8B9T+G+p/AfU/gPqfwH1P4D6nN8j6nO8j6nM/HSfyH1FBzTS/8AMz6/rpFM+X/M5vl/U/M/U//Z",
    "gale4": "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",
    "gale5": "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",
    "gale6": "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",
    "loss": "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",
}

client = genai.Client(api_key=GEMINI_KEY)
app = Flask(__name__)


# ==============================================================================
# HISTÓRICO EM MEMÓRIA
# ==============================================================================

historico_double = deque(maxlen=MAX_HISTORY)
historico_lock = threading.Lock()
ultima_rodada_id = None
historico_atualizacao_lock = threading.Lock()
ultima_atualizacao_historico = 0.0


# ==============================================================================
# HISTÓRICO ATUALIZADO DO TIPMINER
# ==============================================================================

def buscar_historico_tipminer():
    headers = {
        "accept": "*/*",
        "accept-language": "pt-BR",
        "content-type": "application/json",
        "authorization": f"Bearer {TIPMINER_TOKEN}",
        "origin": "https://www.tipminer.com",
        "referer": "https://www.tipminer.com/",
        "user-agent": "Mozilla/5.0",
    }

    resposta = requests.get(
        TIPMINER_URL,
        params=TIPMINER_PARAMS,
        headers=headers,
        timeout=30,
    )
    print("TIPMINER HISTORY HTTP:", resposta.status_code)
    resposta.raise_for_status()
    dados = resposta.json()

    if isinstance(dados, list):
        return dados
    if isinstance(dados, dict):
        for valor in dados.values():
            if isinstance(valor, list):
                return valor
    return None


def normalizar_rodada_historica(item):
    if not isinstance(item, dict):
        return None
    resultado = item.get("result")
    instant = item.get("instant") or item.get("created_at")
    color = item.get("color") or item.get("colour")
    # No histórico do Double, o número é a fonte principal da cor:
    # 0 = Branco, 1-7 = Vermelho, 8-14 = Preto.
    numero = resultado
    if numero is None:
        numero = item.get("roll")
    if numero is None:
        numero = item.get("number")
    tipo = str(item.get("type") or "DOUBLE").upper()
    cor = converter_cor(numero)
    if cor not in ("Vermelho", "Preto", "Branco"):
        cor = cor_por_tipo(tipo, resultado=resultado, color=color)
    if cor not in ("Vermelho", "Preto", "Branco"):
        return None
    rodada_id = item.get("id") or item.get("uuid") or instant
    if rodada_id is None:
        rodada_id = f"{instant}|{cor}|{numero}"
    return {
        "rodada_id": str(rodada_id),
        "tempo": converter_horario(instant) or str(item.get("tempo") or ""),
        "resultado": cor,
        "numero": numero,
        "instant": instant,
        "tipo": tipo,
    }


def atualizar_historico_tipminer(forcar=False):
    """
    Atualiza a janela fixa de 2.000 rodadas do endpoint /history.

    IMPORTANTE:
    - Não usa SSE.
    - Não adiciona rodadas ao banco por fora.
    - Não apaga uma base válida se a API falhar ou retornar menos de 2.000.
    - Consultas normais do Telegram reutilizam a última carga por até
      HISTORY_REFRESH_SECONDS segundos, evitando lentidão.
    """
    global ultima_atualizacao_historico

    agora = time.time()

    with historico_atualizacao_lock:
        if not forcar and (agora - ultima_atualizacao_historico) < HISTORY_REFRESH_SECONDS:
            total_atual = contar_rodadas_banco()
            if total_atual == ANALYSIS_ROUNDS:
                return total_atual

        print("========================================")
        print("ATUALIZANDO AS 2.000 RODADAS DO TIPMINER")
        print("SEM SSE — HISTORY COMO FONTE")
        print("========================================")

        dados = buscar_historico_tipminer()
    if not dados:
        raise RuntimeError("A API do TipMiner não retornou histórico.")

    rodadas = []
    vistos = set()
    for item in dados:
        rodada = normalizar_rodada_historica(item)
        if not rodada or rodada["rodada_id"] in vistos:
            continue
        vistos.add(rodada["rodada_id"])
        rodadas.append(rodada)

    if len(rodadas) < ANALYSIS_ROUNDS:
        raise RuntimeError(
            f"API retornou apenas {len(rodadas)} rodadas válidas; "
            f"esperado: {ANALYSIS_ROUNDS}."
        )

    # Ordena pela data/hora e mantém as 2.000 MAIS RECENTES.
    rodadas = sorted(rodadas, key=_ordem_temporal)[-ANALYSIS_ROUNDS:]

    conn = conectar_banco()
    try:
        cursor = conn.cursor()
        # Só limpamos depois de validar a nova carga. A transação garante que
        # um erro durante a inserção devolva o banco ao estado anterior.
        cursor.execute("DELETE FROM double_rounds")

        for rodada in rodadas:
            cursor.execute(
                """
                INSERT INTO double_rounds
                (rodada_id, tempo, resultado, numero, instant, tipo, criado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (rodada_id) DO UPDATE SET
                    tempo=EXCLUDED.tempo, resultado=EXCLUDED.resultado,
                    numero=EXCLUDED.numero, instant=EXCLUDED.instant,
                    tipo=EXCLUDED.tipo
                """,
                (
                    rodada["rodada_id"],
                    rodada["tempo"],
                    rodada["resultado"],
                    str(rodada["numero"]) if rodada["numero"] is not None else None,
                    str(rodada["instant"]) if rodada["instant"] is not None else None,
                    rodada["tipo"],
                    datetime.now(timezone.utc),
                ),
            )

        conn.commit()

        # Garantia absoluta: a tabela nunca fica com mais de 2.000 registros.
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
            (ANALYSIS_ROUNDS,),
        )
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM double_rounds")
        total_final = cursor.fetchone()[0]
        if total_final != ANALYSIS_ROUNDS:
            raise RuntimeError(
                f"Banco ficou com {total_final} rodadas; esperado: {ANALYSIS_ROUNDS}."
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    carregar_historico_banco()
    total = contar_rodadas_banco()

    print("RODADAS RECEBIDAS PELA API:", len(dados))
    print("RODADAS VÁLIDAS:", len(rodadas))
    print("TOTAL ATUAL NO POSTGRESQL:", total)

    if total != ANALYSIS_ROUNDS:
        raise RuntimeError(
            f"Banco ficou com {total} rodadas; esperado: {ANALYSIS_ROUNDS}."
        )

    ultima_atualizacao_historico = time.time()
    return total


def carregar_historico_fixo_tipminer():
    """Carga inicial obrigatória da janela fixa de 2.000 rodadas."""
    return atualizar_historico_tipminer(forcar=True)


# ==============================================================================
# CONFIGURAÇÕES PERMANENTES DO BOT
# ==============================================================================
# Salva somente configurações/personalizações. As 2.000 rodadas continuam
# seguindo exatamente a lógica existente e não são gravadas por este recurso.
_CONFIG_PERSIST_LOCK = threading.RLock()
_CONFIG_PERSIST_ULTIMO_JSON = None
_CONFIG_PERSIST_THREAD = None

# Capas visuais gerais dos painéis principais. file_id do Telegram por chave.
CAPAS_PAINEL_CONFIG = {}

def _config_para_json():
    """Monta um snapshot JSON das configurações que devem sobreviver a deploy/restart."""
    def limpar_runtime(mapa):
        saida = {}
        for chat_id, cfg in mapa.items():
            item = dict(cfg)
            # Ativo/pausado são estado do monitor em execução, não configuração permanente.
            item["ativa"] = False
            item["pausada"] = False
            saida[str(chat_id)] = item
        return saida

    dados = {
        "estrategias": limpar_runtime(ESTRATEGIAS_CONFIG),
        "estrategias_gatilho": limpar_runtime(ESTRATEGIAS_GATILHO_CONFIG),
        "textos_canal": {str(k): v for k, v in TEXTOS_CANAL_CONFIG.items()},
        "textos_canal_owner_chat_id": TEXTOS_CANAL_OWNER_CHAT_ID,
        "capas_painel": dict(CAPAS_PAINEL_CONFIG),
    }
    return json.dumps(dados, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _salvar_configuracoes_permanentes(forcar=False):
    """Persiste automaticamente as configurações no PostgreSQL/Supabase."""
    global _CONFIG_PERSIST_ULTIMO_JSON
    try:
        payload = _config_para_json()
        with _CONFIG_PERSIST_LOCK:
            if not forcar and payload == _CONFIG_PERSIST_ULTIMO_JSON:
                return False
            conn = conectar_banco()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO bot_configuracoes (id, dados, atualizado_em)
                    VALUES (1, %s::jsonb, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        dados = EXCLUDED.dados,
                        atualizado_em = NOW()
                    """,
                    (payload,),
                )
                conn.commit()
                _CONFIG_PERSIST_ULTIMO_JSON = payload
                return True
            finally:
                conn.close()
    except Exception as erro:
        print("ERRO AO SALVAR CONFIGURAÇÕES PERMANENTES:", type(erro).__name__, str(erro))
        return False

def _carregar_configuracoes_permanentes():
    """Restaura configurações e file_id das imagens após restart/deploy."""
    global TEXTOS_CANAL_OWNER_CHAT_ID, _CONFIG_PERSIST_ULTIMO_JSON
    try:
        conn = conectar_banco()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT dados FROM bot_configuracoes WHERE id = 1")
            row = cur.fetchone()
        finally:
            conn.close()
        if not row or not row.get("dados"):
            return False
        dados = row["dados"]
        if isinstance(dados, str):
            dados = json.loads(dados)

        CAPAS_PAINEL_CONFIG.clear()
        CAPAS_PAINEL_CONFIG.update(dados.get("capas_painel") or {})

        ESTRATEGIAS_CONFIG.clear()
        for k, v in (dados.get("estrategias") or {}).items():
            cfg = _estrategia_padrao()
            cfg.update(v or {})
            cfg["ativa"] = False
            cfg["pausada"] = False
            ESTRATEGIAS_CONFIG[int(k)] = cfg

        ESTRATEGIAS_GATILHO_CONFIG.clear()
        for k, v in (dados.get("estrategias_gatilho") or {}).items():
            cfg = _estrategia_gatilho_padrao()
            cfg.update(v or {})
            cfg["ativa"] = False
            cfg["pausada"] = False
            ESTRATEGIAS_GATILHO_CONFIG[int(k)] = cfg

        TEXTOS_CANAL_CONFIG.clear()
        for k, v in (dados.get("textos_canal") or {}).items():
            TEXTOS_CANAL_CONFIG[int(k)] = v or {}
            TEXTOS_CANAL_CONFIG[int(k)].setdefault("textos", dict(_TEXTOS_CANAL_PADRAO))
            TEXTOS_CANAL_CONFIG[int(k)].setdefault("green_imagens", {})

        owner = dados.get("textos_canal_owner_chat_id")
        TEXTOS_CANAL_OWNER_CHAT_ID = int(owner) if owner is not None else None
        _CONFIG_PERSIST_ULTIMO_JSON = _config_para_json()
        print("CONFIGURAÇÕES PERMANENTES CARREGADAS COM SUCESSO")
        return True
    except Exception as erro:
        print("ERRO AO CARREGAR CONFIGURAÇÕES PERMANENTES:", type(erro).__name__, str(erro))
        traceback.print_exc()
        return False

def _loop_persistencia_configuracoes():
    """Detecta alterações feitas pelo painel e salva sem exigir botão extra."""
    while True:
        time.sleep(1.0)
        _salvar_configuracoes_permanentes(forcar=False)

def _iniciar_persistencia_configuracoes():
    global _CONFIG_PERSIST_THREAD
    if _CONFIG_PERSIST_THREAD and _CONFIG_PERSIST_THREAD.is_alive():
        return
    _CONFIG_PERSIST_THREAD = threading.Thread(
        target=_loop_persistencia_configuracoes,
        name="persistencia-config-bot",
        daemon=True,
    )
    _CONFIG_PERSIST_THREAD.start()

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
            CREATE TABLE IF NOT EXISTS bot_configuracoes (
                id INTEGER PRIMARY KEY,
                dados JSONB NOT NULL DEFAULT '{}'::jsonb,
                atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
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


# A base é fixa: nenhuma rodada individual é salva. Somente atualizar_historico_tipminer() substitui a janela de 2.000.

def contar_rodadas_banco():
    conn = conectar_banco()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM double_rounds")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def obter_historico_banco(limite=None):
    conn=conectar_banco()
    try:
        cursor=conn.cursor(cursor_factory=RealDictCursor)
        if limite is None:
            cursor.execute("""SELECT rodada_id,tempo,resultado,numero,instant,tipo,criado_em
                              FROM double_rounds ORDER BY id DESC""")
        else:
            cursor.execute("""SELECT rodada_id,tempo,resultado,numero,instant,tipo,criado_em
                              FROM double_rounds ORDER BY id DESC LIMIT %s""",(int(limite),))
        linhas=cursor.fetchall()
        return [{"rodada_id":str(x["rodada_id"]) if x["rodada_id"] is not None else None,
                 "tempo":x["tempo"],"resultado":x["resultado"],"numero":x["numero"],
                 "instant":x["instant"],"tipo":x["tipo"],
                 "criado_em":x["criado_em"].isoformat() if x["criado_em"] else None}
                for x in linhas]
    finally:
        conn.close()

def obter_ultimo_por_cor(cor):
    conn=conectar_banco()
    try:
        cursor=conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""SELECT rodada_id,tempo,resultado,numero,instant,tipo
                          FROM double_rounds
                          WHERE LOWER(resultado)=LOWER(%s)
                          ORDER BY id DESC LIMIT 1""",(cor,))
        x=cursor.fetchone()
        if not x: return None
        return {"rodada_id":str(x["rodada_id"]) if x["rodada_id"] is not None else None,"tempo":x["tempo"],
                "resultado":x["resultado"],"numero":x["numero"],
                "instant":x["instant"],"tipo":x["tipo"]}
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
        if 1 <= numero <= 7:
            return "Vermelho"
        if 8 <= numero <= 14:
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
    # Base fixa de 2.000: eventos individuais nunca são gravados.
    print("ℹ️ RODADA INDIVIDUAL IGNORADA — base fixa de 2.000.")
    return False


# ==============================================================================
# HISTÓRICO PARA A IA
# ==============================================================================

def obter_historico(limite=None):
    dados=obter_historico_banco(limite=limite)
    if not dados: raise RuntimeError("O histórico fixo de 2.000 rodadas ainda não foi carregado.")
    return dados

def identificar_cor_perguntada(pergunta):
    texto=(pergunta or "").lower()
    for cor in ("branco","vermelho","preto"):
        if cor in texto: return cor.capitalize()
    return None

def montar_resposta_ultima_cor(rodada):
    partes=[f"🎯 Último {rodada.get('resultado','').lower()}:",
            f"🕐 {rodada.get('tempo') or 'horário indisponível'}"]
    if rodada.get("numero") is not None: partes.append(f"🔢 Número: {rodada['numero']}")
    return "\n".join(partes)


# ==============================================================================
# ANÁLISE DE SEQUÊNCIAS
# ==============================================================================

def emoji_cor(cor):
    return {"Vermelho": "🔴", "Preto": "⚫", "Branco": "⚪"}.get(cor, "❓")


def formatar_data_hora(instant, tempo=None):
    if instant:
        try:
            texto = str(instant)
            if texto.endswith("Z"):
                texto = texto[:-1] + "+00:00"
            dt = datetime.fromisoformat(texto)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone(timedelta(hours=-3)))
            return dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M:%S")
        except Exception:
            pass
    return "data indisponível", str(tempo or "horário indisponível")


def _ordem_temporal(d):
    valor = d.get("instant")
    if valor:
        try:
            texto = str(valor)
            if texto.endswith("Z"):
                texto = texto[:-1] + "+00:00"
            dt = datetime.fromisoformat(texto)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    return 0.0


def normalizar_cor_analise(rodada):
    """Retorna uma cor padronizada para uma rodada da análise."""
    if not isinstance(rodada, dict):
        return None

    resultado = rodada.get("resultado")
    if resultado in ("Vermelho", "Preto", "Branco"):
        return resultado

    # Se o resultado veio como número, convertemos diretamente.
    numero = rodada.get("numero")
    cor_numero = converter_cor(numero)
    if cor_numero in ("Vermelho", "Preto", "Branco"):
        return cor_numero

    # Último recurso: usa o tipo do evento.
    tipo = str(rodada.get("tipo") or "").upper()
    if tipo == "LUCKY":
        return "Branco"
    if tipo == "DOUBLE":
        return "Vermelho"
    if tipo == "DEFAULT":
        return "Preto"

    # Também aceita resultado/color em formatos textuais conhecidos.
    for valor in (rodada.get("color"), resultado):
        if isinstance(valor, str):
            texto = valor.strip().lower()
            if texto in ("red", "vermelho"):
                return "Vermelho"
            if texto in ("black", "preto"):
                return "Preto"
            if texto in ("white", "branco"):
                return "Branco"

    return None


def _encontrar_sequencias_de_10(dados, limite=50):
    """
    Reconhece blocos reais de cores consecutivas.

    Regra única da estratégia:
    - um bloco contínuo de Vermelho ou Preto com pelo menos 10 rodadas
      gera UMA ocorrência;
    - as 10 primeiras são o gatilho;
    - as posições 11ª a 15ª são as cinco rodadas imediatamente seguintes;
    - uma sequência longa (11, 15, 20...) continua sendo a mesma ocorrência;
    - uma nova ocorrência só pode começar em um novo bloco, depois que a
      cor mudar;
    - só entram ocorrências que tenham as 15 posições disponíveis.
    """
    if not dados:
        return []

    cores = [normalizar_cor_analise(d) for d in dados]
    ocorrencias = []
    i = 0

    while i < len(dados):
        cor = cores[i]

        # Branco ou registro sem cor: não inicia sequência.
        if cor not in ("Vermelho", "Preto"):
            i += 1
            continue

        # Descobre o tamanho do bloco contínuo começando em i.
        j = i + 1
        while j < len(dados) and cores[j] == cor:
            j += 1

        tamanho_bloco = j - i

        # O bloco precisa ter pelo menos 10 da mesma cor e mais 5 rodadas
        # depois do gatilho para que a ocorrência seja analisável.
        if tamanho_bloco >= 10 and i + 15 <= len(dados):
            seq_10 = dados[i:i + 10]
            seguintes_5 = dados[i + 10:i + 15]

            # As cinco posições precisam existir e ter cor reconhecida.
            if len(seguintes_5) == 5 and all(normalizar_cor_analise(r) is not None for r in seguintes_5):
                ocorrencias.append((i, cor, seq_10, seguintes_5))
                if len(ocorrencias) >= limite:
                    break

        # Pula o bloco inteiro. Assim, 15/20 vermelhos nunca viram
        # uma segunda sequência começando dentro do mesmo bloco.
        i = j

    return ocorrencias


def analisar_sequencias_de_10_completas():
    """Analisa TODAS as ocorrências encontradas nos 2.000 registros fixos."""
    dados = obter_historico_banco(limite=ANALYSIS_ROUNDS)
    if not dados:
        return "❌ Ainda não há rodadas suficientes no histórico fixo de 2.000."

    # O banco retorna mais recente -> mais antiga; a análise precisa ser cronológica.
    dados = list(reversed(dados))
    # Analisa todas as ocorrências completas dentro dos 2.000 registros.
    ocorrencias = _encontrar_sequencias_de_10(dados, limite=len(dados))
    ocorrencias = list(reversed(ocorrencias))

    if not ocorrencias:
        return "❌ Ainda não encontrei uma sequência completa de 10 vermelhos ou 10 pretos com as 5 rodadas seguintes disponíveis."

    stats = {p: {"hits": 0, "total": 0} for p in range(11, 16)}
    blocos = []
    bateu_total = 0
    nao_bateu_total = 0

    for _, cor, seq, seguintes in ocorrencias:
        oposta = "Preto" if cor == "Vermelho" else "Vermelho"
        data_inicio, hora_inicio = formatar_data_hora(seq[0].get("instant"), seq[0].get("tempo"))
        _, hora_10 = formatar_data_hora(seq[-1].get("instant"), seq[-1].get("tempo"))

        linhas = [
            f"🔥 SEQUÊNCIA DE 10 {cor.upper()} {emoji_cor(cor)}",
            "",
            f"📅 {data_inicio}",
            f"🕐 Início: {hora_inicio}",
            f"🕐 10ª rodada: {hora_10}",
            "",
            " ".join(emoji_cor(cor) for _ in range(10)),
            "",
            "➡️ APÓS A SEQUÊNCIA",
            "",
        ]

        # No resultado final, cada sequência conta UMA única vez:
        # bateu se a cor oposta apareceu em qualquer posição da 11ª à 15ª.
        bateu_ocorrencia = any(normalizar_cor_analise(r) == oposta for r in seguintes)
        if bateu_ocorrencia:
            bateu_total += 1
        else:
            nao_bateu_total += 1

        for offset_pos, rodada in enumerate(seguintes, start=11):
            c = normalizar_cor_analise(rodada)
            _, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
            numero = rodada.get("numero")

            if c == "Branco":
                marca = f"{emoji_cor(c)} BRANCO ❌"
            elif c == oposta:
                stats[offset_pos]["hits"] += 1
                marca = f"{emoji_cor(c)} {c.upper()} ✅"
            elif c in ("Vermelho", "Preto"):
                marca = f"{emoji_cor(c)} {c.upper()} ❌"
            else:
                marca = f"❓ {numero if numero is not None else '?'} ❌"

            stats[offset_pos]["total"] += 1
            linhas.append(f"{offset_pos}ª → {marca} — {hora}")

        blocos.append("\n".join(linhas))

    resumo = [f"📊 {len(ocorrencias)} SEQUÊNCIAS ENCONTRADAS NOS 2.000 REGISTROS", ""]
    for p in range(11, 16):
        total = stats[p]["total"]
        pct = (stats[p]["hits"] / total * 100) if total else 0.0
        resumo.append(f"{p}ª → {pct:.1f}% ({stats[p]['hits']}/{total})")

    disponiveis = [p for p in range(11, 16) if stats[p]["total"]]
    if disponiveis:
        melhor = max(disponiveis, key=lambda p: stats[p]["hits"] / stats[p]["total"])
        melhor_total = stats[melhor]["total"]
        melhor_pct = stats[melhor]["hits"] / melhor_total * 100
        resumo += ["", "🏆 MAIOR FREQUÊNCIA COR OPOSTA", f"➡️ {melhor}ª RODADA — {melhor_pct:.1f}%"]

    resumo += ["", f"📈 TOTAL ANALISADO: {len(ocorrencias)} sequências"]

    total_seq = len(ocorrencias)
    taxa_acerto = (bateu_total / total_seq * 100) if total_seq else 0.0
    taxa_nao_acerto = (nao_bateu_total / total_seq * 100) if total_seq else 0.0

    resultado_final = [
        "━━━━━━━━━━━━━━━━━━",
        "📊 RESULTADO FINAL",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"🔥 SEQUÊNCIAS ENCONTRADAS: {total_seq}",
        "",
        f"✅ BATEU A COR OPOSTA: {bateu_total}",
        f"❌ NÃO BATEU A COR OPOSTA: {nao_bateu_total}",
        "",
        f"📈 TAXA DE ACERTO: {taxa_acerto:.1f}%",
        f"📉 TAXA DE NÃO ACERTO: {taxa_nao_acerto:.1f}%",
    ]

    detalhes_finais = "\n\n".join(blocos) + "\n\n" + "\n".join(resultado_final)
    return ["\n".join(resumo), detalhes_finais]

def analisar_sequencias_de_cores_iguais():
    """
    Segunda estratégia: resumo das sequências de Vermelho/Preto iguais.

    Regras:
    - Uma sequência começa quando há 2 ou mais Vermelhos ou Pretos consecutivos.
    - Uma sequência longa conta como uma única sequência pelo seu tamanho real.
      Ex.: 10 vermelhos = uma sequência de 10, não várias de 2, 3, 4...
    - Branco ou uma cor diferente encerra a sequência.
    - O resultado mostra a quantidade por tamanho/cor e a data/hora da ocorrência
      mais recente daquele tamanho.
    """
    dados = obter_historico_banco(limite=ANALYSIS_ROUNDS)
    if not dados:
        return "❌ Ainda não há rodadas suficientes no histórico."

    # O banco retorna mais recente -> mais antiga. A análise de sequência precisa
    # ser feita da mais antiga -> mais recente.
    dados = list(reversed(dados))

    contagens = {}
    ultima_ocorrencia = {}

    i = 0
    while i < len(dados):
        cor = normalizar_cor_analise(dados[i])

        if cor not in ("Vermelho", "Preto"):
            i += 1
            continue

        inicio = i
        j = i + 1
        while j < len(dados) and normalizar_cor_analise(dados[j]) == cor:
            j += 1

        tamanho = j - inicio

        if tamanho >= 2:
            chave = (cor, tamanho)
            contagens[chave] = contagens.get(chave, 0) + 1

            # Guarda a ocorrência mais recente daquele tamanho.
            rodada_final = dados[j - 1]
            ultima_ocorrencia[chave] = rodada_final

        i = j

    if not contagens:
        return "❌ Nenhuma sequência de 2 ou mais cores iguais foi encontrada."

    # Ordena por tamanho da sequência e, dentro do mesmo tamanho, Vermelho antes Preto.
    itens = sorted(
        contagens.items(),
        key=lambda item: (item[0][1], 0 if item[0][0] == "Vermelho" else 1)
    )

    linhas = ["📊 SEQUÊNCIAS DE CORES IGUAIS — 2.000 RODADAS", ""]

    for (cor, tamanho), quantidade in itens:
        rodada = ultima_ocorrencia[(cor, tamanho)]
        data, hora = formatar_data_hora(
            rodada.get("instant"), rodada.get("tempo")
        )
        palavra = "ocorrência" if quantidade == 1 else "ocorrências"
        linhas.append(
            f"{emoji_cor(cor)} {tamanho} iguais — {quantidade} {palavra}"
        )
        linhas.append(f"📅 {data}")
        linhas.append(f"🕐 {hora}")
        linhas.append("")

    # Maior sequência real encontrada.
    maior_tamanho = max(tamanho for (_, tamanho) in contagens)
    maiores = [
        (cor, tamanho)
        for (cor, tamanho) in contagens
        if tamanho == maior_tamanho
    ]

    # Se houver empate, mostra todas as cores da maior sequência.
    linhas.append("🏆 MAIOR SEQUÊNCIA")
    for cor, tamanho in maiores:
        rodada = ultima_ocorrencia[(cor, tamanho)]
        data, hora = formatar_data_hora(
            rodada.get("instant"), rodada.get("tempo")
        )
        linhas.append(f"➡️ {tamanho} {emoji_cor(cor)}")
        linhas.append(f"📅 {data}")
        linhas.append(f"🕐 {hora}")

    total_sequencias = sum(contagens.values())
    linhas += [
        "",
        f"📚 Rodadas analisadas: {len(dados):,}",
        f"🔢 Sequências encontradas: {total_sequencias}",
    ]

    return "\n".join(linhas)


def analisar_atraso_do_branco():
    """
    Estratégia do Branco:
    - Usa todos os 2.000 registros, em ordem cronológica.
    - Cada Branco inicia um intervalo.
    - O próximo Branco encerra o intervalo.
    - Conta somente as rodadas Vermelho/Preto entre os dois Brancos,
      sem contar o Branco inicial nem o Branco final.
    - Calcula o horário de início, horário de término e duração real.
    """
    dados = obter_historico_banco(limite=ANALYSIS_ROUNDS)
    if not dados:
        return "❌ Ainda não há rodadas suficientes no histórico fixo de 2.000."

    dados = list(reversed(dados))
    brancos = [i for i, rodada in enumerate(dados)
               if normalizar_cor_analise(rodada) == "Branco"]

    if len(brancos) < 2:
        return "❌ É necessário encontrar pelo menos 2 brancos nos 2.000 registros para calcular o intervalo."

    intervalos = []
    for pos in range(len(brancos) - 1):
        inicio_idx = brancos[pos]
        fim_idx = brancos[pos + 1]
        inicio = dados[inicio_idx]
        fim = dados[fim_idx]

        # Quantidade de rodadas entre os dois brancos.
        rodadas_sem_branco = max(0, fim_idx - inicio_idx - 1)

        data_inicio, hora_inicio = formatar_data_hora(
            inicio.get("instant"), inicio.get("tempo")
        )
        data_fim, hora_fim = formatar_data_hora(
            fim.get("instant"), fim.get("tempo")
        )

        duracao_segundos = None
        try:
            a = str(inicio.get("instant") or "")
            b = str(fim.get("instant") or "")
            if a.endswith("Z"):
                a = a[:-1] + "+00:00"
            if b.endswith("Z"):
                b = b[:-1] + "+00:00"
            dt_a = datetime.fromisoformat(a)
            dt_b = datetime.fromisoformat(b)
            if dt_a.tzinfo is None:
                dt_a = dt_a.replace(tzinfo=timezone.utc)
            if dt_b.tzinfo is None:
                dt_b = dt_b.replace(tzinfo=timezone.utc)
            duracao_segundos = max(0, int((dt_b - dt_a).total_seconds()))
        except Exception:
            duracao_segundos = None

        if duracao_segundos is not None:
            horas, resto = divmod(duracao_segundos, 3600)
            minutos, segundos = divmod(resto, 60)
            if horas:
                duracao = f"{horas}h {minutos}m {segundos}s"
            elif minutos:
                duracao = f"{minutos}m {segundos}s"
            else:
                duracao = f"{segundos}s"
        else:
            duracao = "indisponível"

        intervalos.append({
            "data_inicio": data_inicio,
            "hora_inicio": hora_inicio,
            "data_fim": data_fim,
            "hora_fim": hora_fim,
            "rodadas": rodadas_sem_branco,
            "duracao": duracao,
            "duracao_segundos": duracao_segundos if duracao_segundos is not None else -1,
        })

    # Mais recentes primeiro, para facilitar a conferência no Telegram.
    intervalos.reverse()

    maior = max(intervalos, key=lambda x: x["rodadas"])
    menor = min(intervalos, key=lambda x: x["rodadas"])
    media = sum(x["rodadas"] for x in intervalos) / len(intervalos)

    texto = [
        "⚪ ATRASO DO BRANCO",
        "",
        "📚 Análise completa dos 2.000 registros",
        "",
        "📖 COMO FUNCIONA A ESTRATÉGIA",
        "",
        "Esta estratégia procura todos os intervalos entre um Branco e o próximo Branco dentro dos 2.000 registros.",
        "",
        "⚪ Quando sai um Branco, começa a contagem.",
        "🔴⚫ Cada rodada Vermelho ou Preto sem Branco aumenta o atraso em +1.",
        "⚪ Quando sai o próximo Branco, a contagem termina.",
        "",
        "O bot informa automaticamente quantas rodadas ficaram sem pagar Branco, o horário em que o intervalo começou, o horário em que terminou e o tempo real que durou.",
        "",
        "⚠️ A análise mostra o comportamento histórico dos 2.000 registros e não garante quando o próximo Branco irá acontecer.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📊 RESUMO GERAL",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"⚪ Intervalos entre brancos: {len(intervalos)}",
        f"📊 Média sem Branco: {media:.1f} rodadas",
        f"📉 Menor atraso: {menor['rodadas']} rodada(s)",
        f"🚨 Maior atraso: {maior['rodadas']} rodadas",
        f"📅 Maior atraso: {maior['data_inicio']}",
        f"🕐 Início: {maior['hora_inicio']}",
        f"🕐 Fim: {maior['hora_fim']}",
        f"⏱️ Duração: {maior['duracao']}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📋 INTERVALOS ENCONTRADOS",
        "━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for n, item in enumerate(intervalos, 1):
        texto.extend([
            f"⚪ Intervalo {n}",
            f"📅 {item['data_inicio']} → {item['data_fim']}",
            f"🕐 Início: {item['hora_inicio']}",
            f"🕐 Fim: {item['hora_fim']}",
            f"🔢 SEM PAGAR BRANCO: {item['rodadas']} rodadas",
            f"⏱️ Duração: {item['duracao']}",
            "",
        ])

    return "\n".join(texto)


def _estatisticas_surfe(caminho):
    """Calcula os dois caminhos do SURFE em ordem cronológica."""
    stats = {
        "Preto": {"acertos": 0, "erros": 0, "maior_gale": 0, "gale_counts": {}},
        "Vermelho": {"acertos": 0, "erros": 0, "maior_gale": 0, "gale_counts": {}},
    }
    gale = {"Preto": 0, "Vermelho": 0}
    registros = []

    for rodada in caminho:
        saiu = normalizar_cor_analise(rodada)
        if saiu not in ("Preto", "Vermelho", "Branco"):
            continue

        numero = len(registros) + 1
        bloco = ((numero - 1) // 2) % 2
        jogaria_preto = "Preto" if bloco == 0 else "Vermelho"
        jogaria_vermelho = "Vermelho" if bloco == 0 else "Preto"
        resultados = {}

        for nome, jogaria in (("Preto", jogaria_preto), ("Vermelho", jogaria_vermelho)):
            # Branco conta como Gale, sem interromper nem reiniciar o caminho.
            if saiu == "Branco":
                stats[nome]["erros"] += 1
                gale[nome] += 1
                stats[nome]["maior_gale"] = max(
                    stats[nome]["maior_gale"], gale[nome]
                )
                stats[nome]["gale_counts"][gale[nome]] = (
                    stats[nome]["gale_counts"].get(gale[nome], 0) + 1
                )
                resultados[nome] = f"❌ GALE {gale[nome]}"
                continue

            if saiu == jogaria:
                stats[nome]["acertos"] += 1
                gale[nome] = 0
                resultados[nome] = "✅ ACERTO"
            else:
                stats[nome]["erros"] += 1
                gale[nome] += 1
                stats[nome]["maior_gale"] = max(
                    stats[nome]["maior_gale"], gale[nome]
                )
                stats[nome]["gale_counts"][gale[nome]] = (
                    stats[nome]["gale_counts"].get(gale[nome], 0) + 1
                )
                resultados[nome] = f"❌ GALE {gale[nome]}"

        data, hora = formatar_data_hora(
            rodada.get("instant"), rodada.get("tempo")
        )
        registros.append({
            "numero": numero,
            "numero_real": rodada.get("numero", "?"),
            "data": data,
            "hora": hora,
            "saiu": saiu,
            "jogaria_preto": jogaria_preto,
            "jogaria_vermelho": jogaria_vermelho,
            "resultado_preto": resultados["Preto"],
            "resultado_vermelho": resultados["Vermelho"],
        })

    return registros, stats


def _resumo_surfe_estrategia(stats, nome, titulo):
    """Resumo principal do SURF, sem exibir os Gales."""
    st = stats[nome]
    total = st["acertos"] + st["erros"]
    pct = (st["acertos"] / total * 100) if total else 0.0

    return "\n".join([
        titulo,
        f"✅ ACERTOS: {st['acertos']}",
        f"❌ ERROS: {st['erros']}",
        f"📈 APROVEITAMENTO: {pct:.1f}%",
    ])


def _emoji_numero_gale(numero):
    # Padroniza o desenho em todo o bot.
    # O 10 usa o emoji próprio 🔟, evitando diferenças visuais entre telas.
    if str(numero) == "10":
        return "🔟"

    mapa = {
        "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
        "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣",
    }
    return "".join(mapa.get(c, c) for c in str(numero))


def _numero_gale_visual(numero):
    """Usa o mesmo padrão de emoji numérico já existente no bot."""
    return _emoji_numero_gale(numero)


def _resumo_gales_surfe(stats, nome, titulo):
    st = stats[nome]
    maior = _numero_gale_visual(st["maior_gale"])
    partes = [titulo, f"🔥 MAIOR GALE: GALE {maior}"]
    for n in sorted(st["gale_counts"]):
        partes.append(f"📊 GALE {_numero_gale_visual(n)}: {st['gale_counts'][n]}")
    return "\n".join(partes)


def obter_brancos_surfe():
    """Retorna todos os Brancos dos 2.000 registros em ordem antiga -> recente."""
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    return [
        (i, rodada)
        for i, rodada in enumerate(dados)
        if normalizar_cor_analise(rodada) == "Branco"
    ]


def montar_botoes_brancos_surfe(brancos, inicio=0, fim=None):
    """Monta os Brancos em duas colunas, mantendo a ordem cronológica."""
    fim = len(brancos) if fim is None else min(fim, len(brancos))
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    itens = brancos[inicio:fim]

    for pos in range(0, len(itens), 2):
        botoes = []
        for offset in (0, 1):
            if pos + offset >= len(itens):
                break
            indice, rodada = itens[pos + offset]
            _, hora = formatar_data_hora(
                rodada.get("instant"), rodada.get("tempo")
            )
            # O índice é o índice cronológico dentro dos 2.000 registros.
            botoes.append(
                telebot.types.InlineKeyboardButton(
                    f"⚪ {hora}",
                    callback_data=f"surfe_branco:{indice}",
                )
            )
        markup.row(*botoes)

    return markup


def obter_ocorrencias_numero_surfe(numero):
    """Retorna todas as ocorrências de um número em ordem antiga -> recente."""
    numero = int(numero)
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    return [
        (i, rodada)
        for i, rodada in enumerate(dados)
        if rodada.get("numero") is not None and int(rodada.get("numero")) == numero
    ]


def montar_botoes_numero_surfe(ocorrencias, numero, inicio=0, fim=None):
    """Monta as ocorrências do número em duas colunas, igual ao painel dos Brancos."""
    numero = int(numero)
    fim = len(ocorrencias) if fim is None else min(fim, len(ocorrencias))
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    itens = ocorrencias[inicio:fim]
    cor = converter_cor(numero)
    emoji = emoji_cor(cor)

    for pos in range(0, len(itens), 2):
        botoes = []
        for offset in (0, 1):
            if pos + offset >= len(itens):
                break
            indice, rodada = itens[pos + offset]
            _, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
            botoes.append(
                telebot.types.InlineKeyboardButton(
                    f"{emoji} {hora}",
                    callback_data=f"surfe_ponto:{indice}:{numero}",
                )
            )
        markup.row(*botoes)
    return markup


def _identificacao_ponto_surfe(analise):
    """Texto do ponto inicial, funcionando para Branco ou para números 1 a 14."""
    tipo = analise.get("tipo_ponto", "Branco")
    emoji = analise.get("emoji_ponto", "⚪")
    if tipo == "Numero":
        numero = analise.get("numero_ponto")
        return f"{emoji} Número {numero}"
    return "⚪ Branco"


def _identificacao_estado_surfe(estado, dados=None):
    """Retorna rótulo e horário do ponto atualmente selecionado."""
    indice = estado.get("ponto_index", estado.get("branco_index"))
    if dados is None:
        dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    if indice is None or indice < 0 or indice >= len(dados):
        return "Ponto selecionado", "horário indisponível", "❓"
    rodada = dados[indice]
    _, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
    numero = rodada.get("numero")
    cor = normalizar_cor_analise(rodada)
    emoji = emoji_cor(cor)
    if cor == "Branco":
        return "Branco selecionado", hora, emoji
    return f"Número {numero} selecionado", hora, emoji


def _montar_linhas_estrategia_surfe(registros, estrategia, numero_final_analise=None):
    """Monta as linhas de uma estratégia com espaçamento de controle."""
    linhas = []

    for item in registros:
        jogaria = (
            item["jogaria_preto"]
            if estrategia == "Preto"
            else item["jogaria_vermelho"]
        )
        resultado = (
            item["resultado_preto"]
            if estrategia == "Preto"
            else item["resultado_vermelho"]
        )

        numero = int(item["numero"])
        numero_real = str(item.get("numero_real", "?"))
        cor_real = emoji_cor(item["saiu"])
        if cor_real in ("🔴", "⚫"):
            cor_real += "\uFE0F"

        cor_jogada = emoji_cor(jogaria)
        if cor_jogada in ("🔴", "⚫"):
            cor_jogada += "\uFE0F"

        if resultado.startswith("❌ GALE"):
            gale = int(resultado.split()[-1])
            # Mantém G1 a G9. A partir do G10 usa uma única letra:
            # G10=GA, G11=GB, G12=GC ... G35=GZ.
            # Isso evita aumentar a largura da linha quando o Gale passa de 9.
            if 10 <= gale <= 35:
                identificador_gale = chr(ord("A") + (gale - 10))
            else:
                identificador_gale = str(gale)
            marcador = f"❌G{identificador_gale}"
        else:
            marcador = "✅"

        # Espaço padronizado entre o número da rodada e a primeira bolinha.
        # É IGUAL em todas as rodadas (01 a 50).
        espaco_rodada = "\u2007"

        # SOMENTE 01 a 08 recebem o ajuste fino ANTES do número da rodada.
        # Assim a linha inteira desloca levemente para a direita, sem aumentar
        # o espaço entre "01/02/..." e a primeira bolinha.
        ajuste_01_08 = ""
        ajuste_apos_numero_direita = ""
        ajuste_antes_seta_direita = ""

        if 1 <= numero <= 8:
            valor_config = (
                AJUSTE_01_08_ANTES_SETA_ESQUERDA
                if estrategia == "Vermelho"
                else AJUSTE_01_08_ANTES_SETA_DIREITA
            )
        elif 1000 <= numero <= 1007:
            valor_config = (
                AJUSTE_CENTENA_00_07_ANTES_SETA_ESQUERDA
                if estrategia == "Vermelho"
                else 0.0
            )
            if estrategia == "Preto":
                ajuste_antes_seta_direita = "\u200A" * 2

        elif 1100 <= numero <= 1907 and (numero % 100) <= 7:
            valor_config = 0.2 if estrategia == "Vermelho" else 0.0
            if estrategia == "Preto":
                ajuste_apos_numero_direita = ""
                ajuste_antes_seta_direita = "\u200A" * 2

        elif 100 <= numero <= 907 and (numero % 100) <= 7:
            if estrategia == "Vermelho":
                valor_config = AJUSTE_CENTENA_00_07_ANTES_SETA_ESQUERDA
            else:
                valor_config = 0.0
                ajuste_apos_numero_direita = ""
                ajuste_antes_seta_direita = "\u200A" * 2

        elif numero >= 100 and (numero % 100) <= 7:
            if estrategia == "Vermelho":
                valor_config = AJUSTE_CENTENA_00_07_ANTES_SETA_ESQUERDA
            else:
                valor_config = 0.0
                valor = max(0.0, float(AJUSTE_CENTENA_00_07_APOS_NUMERO_DIREITA))
                parte_inteira = int(valor)
                decimos = int(round((valor - parte_inteira) * 10))
                ajuste_apos_numero_direita = ("\u3164" * parte_inteira) + ("\u200A" * decimos)

        else:
            valor_config = 0.0

        # Calibração EXCLUSIVA da última rodada da quantidade escolhida.
        # Valor positivo = seta vai para a direita.
        # Valor negativo = seta vai para a esquerda.
        if numero == numero_final_analise and numero in AJUSTE_FINAL_SURF:
            chave = "esquerda" if estrategia == "Vermelho" else "direita"
            valor_config += AJUSTE_FINAL_SURF[numero][chave]

        valor_ajuste = max(0.0, float(valor_config))
        parte_inteira = int(valor_ajuste)
        decimos = int(round((valor_ajuste - parte_inteira) * 10))
        ajuste_01_08 = ("\u3164" * parte_inteira) + ("\u200A" * decimos)

        espaco_cor = "\u2007" if len(numero_real) == 1 else ""

        numero_formatado = f"{numero:02d}"

        linha = (
            f"{numero_formatado}{ajuste_apos_numero_direita}{espaco_rodada}"
            f"{cor_real}{numero_real}{espaco_cor}"
            f"{ajuste_01_08}{ajuste_antes_seta_direita}-{cor_jogada}{marcador}"
        )
        linhas.append(linha)

    return linhas


def _largura_visual_surfe(texto):
    """Calcula uma largura aproximada de célula para alinhamento monoespaçado."""
    largura = 0
    for caractere in texto:
        if unicodedata.combining(caractere):
            continue
        if unicodedata.east_asian_width(caractere) in ("W", "F"):
            largura += 2
        else:
            largura += 1
    return largura


def _preencher_visual_surfe(texto, largura_alvo):
    """Completa uma linha até a largura visual alvo sem alterar seu conteúdo."""
    faltam = max(0, largura_alvo - _largura_visual_surfe(texto))
    return texto + (" " * faltam)


# =========================================================
# AJUSTE MANUAL DO ALINHAMENTO ENTRE AS COLUNAS DO SURF
# ALTERE SOMENTE ESTES DOIS NÚMEROS PARA TESTAR:
# =========================================================
ESPACO_APOS_G = 2.0
ESPACO_APOS_CHECK = 3.4

# Ajuste fino SOMENTE das rodadas 01 a 08.
# 0.1 = um ajuste mínimo para a direita.
# Você pode testar 0.2, 0.3, 0.4... sem mexer nas rodadas 09 a 50.
# Ajustes independentes SOMENTE para as rodadas 01 a 08.
# Quanto maior, mais a respectiva coluna vai para a direita.
AJUSTE_01_08_ANTES_SETA_ESQUERDA = 0.2
AJUSTE_01_08_ANTES_SETA_DIREITA = 0.2

# Ajustes finos das faixas 00–07 de TODA centena/milhar:
# 100–107, 200–207 ... 900–907, 1000–1007, 1100–1107, 1200–1207...
#
# COLUNA ESQUERDA (SURF vermelho): espaço ANTES da seta/hífen.
AJUSTE_CENTENA_00_07_ANTES_SETA_ESQUERDA = 0.2
#
# COLUNA DIREITA (SURF preto): espaço LOGO APÓS o número da rodada.
# Ex.: 1200[espaço] ⚫8-...
AJUSTE_CENTENA_00_07_APOS_NUMERO_DIREITA = 0.2

# Ajuste EXCLUSIVO para linhas de 4 dígitos (1000+).
# A coluna esquerda fica exatamente como já estava.
# Este valor reduz SOMENTE o separador antes da coluna direita,
# trazendo SURF ⚫ para a esquerda para compensar o 4º dígito.
# -0.1 = aproxima minimamente | -0.8 = aproxima 8 Hair Spaces.
AJUSTE_4_DIGITOS_SEPARADOR = -0.8

# Calibrador EXTRA somente de 1008 em diante.
# A coluna esquerda não muda; apenas aproxima a coluna direita.
# 0.2 = 2 Hair Spaces adicionais para a esquerda.
AJUSTE_DIREITA_1008_MAIS = 0.2

# =========================================================
# CALIBRAÇÃO SOMENTE DA ÚLTIMA RODADA DE CADA BOTÃO DO SURF
# =========================================================
# esquerda/direita: mexem SOMENTE antes da seta (-) da respectiva camada.
#   +0.1 = um pouco para a direita | -0.1 = um pouco para a esquerda
# separador: mexe SOMENTE no espaço entre as duas colunas.
#   +0.1 = afasta as colunas | -0.1 = aproxima as colunas
#
# Estes valores NÃO alteram 100/200/300... quando aparecem no meio da análise.
# Só alteram o número que for exatamente a ÚLTIMA rodada selecionada.
AJUSTE_FINAL_SURF = {
    100:  {"esquerda": 0.0, "direita": 0.0, "separador": 0.0},
    200:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    300:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    400:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    500:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    600:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    700:  {"esquerda": -0.2, "direita": -0.4, "separador": 0.0},
    800:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    900:  {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
    1000: {"esquerda": -0.2, "direita": -0.2, "separador": 0.0},
}

def _montar_surfe_duas_colunas(registros, numero_final_analise=None):
    """Monta as duas colunas do SURF com espaçamento padronizado."""
    vermelho = _montar_linhas_estrategia_surfe(registros, "Vermelho", numero_final_analise)
    preto = _montar_linhas_estrategia_surfe(registros, "Preto", numero_final_analise)

    linhas = [
        "SURF🔴" + ("\u2007" * 5) + "SURF⚫",
        "",
    ]

    for esquerda, direita in zip(vermelho, preto):
        # Compensação manual com ajuste decimal.
        # Parte inteira -> ㅤ (U+3164)
        # Cada 0.1      -> Hair Space (U+200A)
        def criar_espaco(valor):
            valor = max(0.0, float(valor))
            parte_inteira = int(valor)
            decimos = int(round((valor - parte_inteira) * 10))

            return ("\u3164" * parte_inteira) + ("\u200A" * decimos)

        # Como ❌G ocupa mais largura que ✅, cada final tem seu próprio ajuste.
        if esquerda.endswith("✅"):
            valor_separador = ESPACO_APOS_CHECK
        elif "❌G" in esquerda:
            valor_separador = ESPACO_APOS_G
        else:
            valor_separador = ESPACO_APOS_G

        # GA–GZ na coluna esquerda: a letra fica visualmente um pouco mais larga
        # no Telegram. Reduz 0.1 SOMENTE do espaço depois do Gale para manter
        # a coluna direita alinhada. G1–G9 permanecem exatamente como estão.
        if re.search(r"❌G[A-Z]$", esquerda):
            valor_separador -= 0.1

        # Linhas de 4 dígitos: mantém a coluna esquerda intacta e
        # aproxima SOMENTE a coluna direita, compensando o dígito extra.
        numero_linha = int(esquerda.split()[0])
        if numero_linha >= 1000:
            valor_separador += AJUSTE_4_DIGITOS_SEPARADOR

        # Ajuste EXCLUSIVO 1000–1007: move somente a coluna direita
        # mais 0.2 para a esquerda, sem alterar a coluna esquerda.
        if 1000 <= numero_linha <= 1007:
            valor_separador -= 0.2

        # A partir de 1008, aproxima um pouco mais SOMENTE a coluna direita.
        if numero_linha >= 1008:
            valor_separador -= AJUSTE_DIREITA_1008_MAIS

        # Ajuste independente do espaço entre as colunas SOMENTE na última rodada.
        # Valor negativo aproxima a coluna direita; positivo afasta.
        if numero_linha == numero_final_analise and numero_linha in AJUSTE_FINAL_SURF:
            valor_separador += AJUSTE_FINAL_SURF[numero_linha]["separador"]

        separador = criar_espaco(valor_separador)
        linhas.append(esquerda + separador + direita)

    return "\n".join(linhas)



def _montar_blocos_surfe(registros):
    """Divide a exibição do SURF sem cortar uma rodada no meio."""
    if not registros:
        return []

    blocos_registros = []
    bloco_atual = []

    for item in registros:
        numero = int(item["numero"])

        # Mantém os cortes já aprovados:
        # 01–99, 100–199, 200–299, 300–399...
        if bloco_atual and numero >= 100 and numero % 100 == 0:
            blocos_registros.append(bloco_atual)
            bloco_atual = []

        bloco_atual.append(item)

    if bloco_atual:
        blocos_registros.append(bloco_atual)

    # Exceção SOMENTE para o final da análise:
    # se o último bloco tiver apenas 1 rodada (ex.: 400 sozinho),
    # junta essa última rodada ao bloco anterior.
    if len(blocos_registros) >= 2 and len(blocos_registros[-1]) == 1:
        blocos_registros[-2].extend(blocos_registros[-1])
        blocos_registros.pop()

    numero_final_analise = int(registros[-1]["numero"])

    return [
        _montar_surfe_duas_colunas(bloco, numero_final_analise)
        for bloco in blocos_registros
    ]

def analisar_surfe_inicial():
    """Prepara o painel do SURF para escolha do Branco inicial."""
    brancos = obter_brancos_surfe()
    if not brancos:
        return None

    introducao = "\n".join([
        "⚪ SURF — ESCOLHA O BRANCO",
        "",
        "👇 Escolha abaixo o Branco onde você quer iniciar o Surf.",
        "",
        "📊 Ao clicar em um Branco, o bot vai analisar todas as rodadas",
        "a partir dele até o resultado mais recente, mostrando como o Surf",
        "teria se comportado começando exatamente naquele ponto.",
        "",
        "🕐 Os Brancos estão organizados do mais antigo para o mais recente,",
        "para que a análise respeite a ordem real das rodadas.",
        "",
        "💡 Você pode escolher qualquer Branco para testar diferentes pontos de entrada.",
        "",
        "⚪ Selecione um Branco abaixo:",
    ])
    return {"intro": introducao, "brancos": brancos}

def analisar_surfe_a_partir_do_branco(indice_branco, limite=None):
    """Analisa o SURF a partir de qualquer ponto selecionado (Branco ou número).

    O nome da função é mantido por compatibilidade com o restante do bot.
    """
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    if indice_branco < 0 or indice_branco >= len(dados):
        return None

    ponto = dados[indice_branco]
    data_ponto, hora_ponto = formatar_data_hora(
        ponto.get("instant"), ponto.get("tempo")
    )
    cor_ponto = normalizar_cor_analise(ponto)
    numero_ponto = ponto.get("numero")
    tipo_ponto = "Branco" if cor_ponto == "Branco" else "Numero"
    emoji_ponto = emoji_cor(cor_ponto)

    # O registro escolhido é o gatilho. O SURF começa na rodada imediatamente
    # posterior e segue cronologicamente até as rodadas mais recentes.
    caminho = dados[indice_branco + 1:]
    if limite is not None:
        caminho = caminho[:limite]

    registros, stats = _estatisticas_surfe(caminho)

    return {
        "branco": ponto,  # compatibilidade com funções antigas
        "data_branco": data_ponto,
        "hora_branco": hora_ponto,
        "ponto": ponto,
        "data_ponto": data_ponto,
        "hora_ponto": hora_ponto,
        "cor_ponto": cor_ponto,
        "numero_ponto": numero_ponto,
        "tipo_ponto": tipo_ponto,
        "emoji_ponto": emoji_ponto,
        "registros": registros,
        "stats": stats,
    }

def montar_resultado_surfe(analise):
    """Monta o cabeçalho, as rodadas escolhidas e o resumo do SURF."""
    registros = analise["registros"]
    identificacao = _identificacao_ponto_surfe(analise)
    cabecalho = "\n".join([
        f"🏄 SURF-{len(registros)} RODADAS",
        "",
        f"{identificacao} inicial: {analise['data_ponto']} às {analise['hora_ponto']}",
        f"📚 Analisadas: {len(registros)}",
    ])

    rodadas = _montar_surfe_duas_colunas(registros)

    estatistica = "\n".join([
        "📊 RESULTADO — APÓS O PONTO SELECIONADO",
        f"{identificacao}: {analise['data_ponto']} às {analise['hora_ponto']}",
        f"📚 Das {len(registros)} rodadas seguintes",
        "",
        _resumo_surfe_estrategia(analise["stats"], "Preto", "⚫ SURFE — 2 PRETOS"),
        "",
        _resumo_surfe_estrategia(analise["stats"], "Vermelho", "🔴 SURFE — 2 VERMELHOS"),
    ])

    return cabecalho + "\n\n§§§SURF_RODADAS§§§\n\n" + rodadas + "\n\n§§§SURF_ESTATISTICA§§§\n\n" + estatistica

def montar_controle_geral_surfe(analise):
    """Resumo geral desde o ponto escolhido até a rodada mais recente."""
    stats = analise["stats"]
    total = len(analise["registros"])

    return "\n".join([
        "📊 RESULTADO GERAL — DO PONTO SELECIONADO",
        "",
        "📖 COMO ENTENDER O RESULTADO",
        "",
        "Esta análise mostra como os dois SURF teriam se comportado",
        "a partir do ponto escolhido, até o resultado mais recente.",
        "",
        "⚫ 2 PRETOS → 2 Pretos, depois 2 Vermelhos, repetindo.",
        "🔴 2 VERMELHOS → 2 Vermelhos, depois 2 Pretos, repetindo.",
        "",
        "✅ Acerto = a cor que saiu foi a indicada pelo SURF.",
        "❌ Erro = a cor foi diferente e o Gale aumentou.",
        "📈 Aproveitamento = porcentagem de acertos.",
        "🔥 Maior Gale = maior sequência de Gales registrada.",
        "📊 Gale 1, 2, 3... = quantidade de vezes que cada Gale ocorreu.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"{_identificacao_ponto_surfe(analise)}: {analise['data_ponto']} às {analise['hora_ponto']}",
        f"📚 Total de rodadas analisadas: {total}",
        "",
        _resumo_surfe_estrategia(stats, "Preto", "⚫ SURFE — 2 PRETOS"),
        "",
        _resumo_surfe_estrategia(stats, "Vermelho", "🔴 SURFE — 2 VERMELHOS"),
        "",
        "⚠️ Estatística histórica. Não garante o resultado da próxima rodada.",
    ])



def painel_markup():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🔥 SEQUÊNCIA CORES IGUAIS 10X — COMPLETA", callback_data="seq10")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📊 SEQUÊNCIA DE CORES IGUAIS", callback_data="seqcores")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("⚪ ATRASO DO BRANCO", callback_data="branco_atraso")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("⚪⚫🔴 SURF", callback_data="surfe")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🐺 CONTROLE GERAL — SURF", callback_data="controle_geral_surfe")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📊 Últimas 50", callback_data="ult50"),
        telebot.types.InlineKeyboardButton("📚 Total", callback_data="total"),
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🕐 Última rodada", callback_data="ultima")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🔎 INVESTIGAÇÃO", callback_data="investigacao"),
        telebot.types.InlineKeyboardButton("🤖 BOT", callback_data="menu_bot"),
    )
    return markup


def bot_controle_markup():
    """Funções técnicas do monitor ficam concentradas no menu 🤖 BOT."""
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    with alertas_surfe_lock:
        alertas_ativos = alertas_surfe_ativos

    # Painel novo de configuração de estratégia.
    # É apenas interface neste primeiro passo: não altera o monitor atual.
    markup.add(
        telebot.types.InlineKeyboardButton(
            "🧠 CONFIGURAR BOT E ATIVAR",
            callback_data="configurar_estrategia"
        )
    )

    markup.add(
        telebot.types.InlineKeyboardButton("📡 REGISTROS ONLINE", callback_data="registro_alertas_surfe")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("💾 REGISTROS DE SINAIS", callback_data="registro_sinais_surfe")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🧪 TESTAR CANAL DE ALERTAS", callback_data="testar_canal_alertas")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📡 TESTAR RODADA AO VIVO", callback_data="testar_rodada_ao_vivo")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="voltar_painel_principal")
    )
    return markup


def _texto_controle_bot():
    return (
        "🤖 CONTROLE DO BOT\n\n"
        "Aqui você controla e acompanha o monitor do SURF em tempo real.\n\n"
        "Você pode ativar ou desativar os alertas e consultar os registros do monitor.\n\n"
        "⚙️ Escolha uma função abaixo."
    )


def _gale_txt(valor):
    return f"G{valor}" if valor is not None else "NÃO CONFIGURADO"

def _limite_txt(valor):
    return f"G{valor}" if valor is not None else "NÃO CONFIGURADO"

def _aviso_txt(valor):
    if valor is None:
        return "NÃO CONFIGURADO"
    if valor == 0:
        return "NÃO AVISAR"
    return f"{valor} Gale(s) antes"

def _config_completa(cfg):
    return all(cfg.get(k) is not None for k in ("gale_gatilho", "surf", "limite_gales", "aviso_antes"))



RELATORIO_AUTOMATICO_MODELO = """📊 RELATÓRIO AUTOMÁTICO
━━━━━━━━━━━━━━━━━━

🎯 SINAIS ANALISADOS: {qtd}

✅ GREENS: {greens}
❌ LOSS: {loss}
📈 TAXA DE GREEN: {taxa_green}%
📉 TAXA DE LOSS: {taxa_loss}%

━━━━━━━━━━━━━━━━━━
🎯 ONDE BATERAM OS GREENS

{distribuicao}

━━━━━━━━━━━━━━━━━━
🔥 SEQUÊNCIAS

🟢 MAIOR SEQUÊNCIA DE GREENS: {seq_green}
🔴 MAIOR SEQUÊNCIA DE LOSS: {seq_loss}
📍 MAIOR GALE UTILIZADO: {maior_gale}

━━━━━━━━━━━━━━━━━━
⚖️ BALANÇO DA PROGRESSÃO

🟢 GREENS: +{unidades_green} unidades
🔴 LOSS: -{unidades_loss} unidades

💰 SALDO: {saldo} unidades
{emoji_resultado} RESULTADO: {resultado}

━━━━━━━━━━━━━━━━━━
{comparacao}

━━━━━━━━━━━━━━━━━━
📡 NOVO BLOCO INICIADO
Próxima análise após mais {qtd} sinais."""


def _relatorio_cfg(chat_id, modo):
    return _cfg_gatilho(chat_id) if modo == "gatilho" else _cfg(chat_id)


def _relatorio_status(cfg):
    qtd = int(cfg.get("relatorio_qtd") or 0)
    return "DESATIVADO" if qtd <= 0 else f"{qtd} SINAIS"


def _relatorio_markup(modo, chat_id):
    prefix = "gatrel" if modo == "gatilho" else "rel"
    voltar = "gatcfg_menu" if modo == "gatilho" else "config_modo_surf_normal"
    m = telebot.types.InlineKeyboardMarkup(row_width=2)
    m.row(
        telebot.types.InlineKeyboardButton("25 SINAIS", callback_data=f"{prefix}_set:25"),
        telebot.types.InlineKeyboardButton("50 SINAIS", callback_data=f"{prefix}_set:50"),
    )
    m.add(telebot.types.InlineKeyboardButton("100 SINAIS", callback_data=f"{prefix}_set:100"))
    m.add(telebot.types.InlineKeyboardButton("🔢 OUTRO VALOR", callback_data=f"{prefix}_outro"))
    m.add(telebot.types.InlineKeyboardButton("👁 VER TEXTO ATUAL", callback_data=f"{prefix}_ver"))
    m.add(telebot.types.InlineKeyboardButton("✏️ ALTERAR TEXTO", callback_data=f"{prefix}_editar"))
    m.add(telebot.types.InlineKeyboardButton("♻️ RESTAURAR PADRÃO", callback_data=f"{prefix}_restaurar"))
    m.add(telebot.types.InlineKeyboardButton("🚫 DESATIVADO", callback_data=f"{prefix}_set:0"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data=voltar))
    return m


def _relatorio_exemplo(cfg):
    modelo = cfg.get("relatorio_texto") or RELATORIO_AUTOMATICO_MODELO
    dados = dict(
        qtd=50, greens=47, loss=3, taxa_green="94,0", taxa_loss="6,0",
        distribuicao="✅ DIRETO: 20\n1️⃣ GALE 1: 14\n2️⃣ GALE 2: 8\n3️⃣ GALE 3: 5",
        seq_green=18, seq_loss=1, maior_gale="G3", unidades_green=47,
        unidades_loss=45, saldo="+2", emoji_resultado="🟢", resultado="POSITIVO",
        comparacao="📚 ÚLTIMO BLOCO — 1 A 50\n\n📈 TAXA DE GREEN: 94,0%\n💰 SALDO: +2 unidades\n🟢 RESULTADO: POSITIVO\n\n━━━━━━━━━━━━━━━━━━\n📊 BLOCOS GERAIS\n\n📦 BLOCOS ANALISADOS: 4\n📈 TAXA GERAL DE GREEN: 93,5%\n💰 SALDO GERAL: +22 unidades\n🟢 RESULTADO GERAL: POSITIVO",
    )
    try:
        return modelo.format(**dados)
    except Exception:
        return RELATORIO_AUTOMATICO_MODELO.format(**dados)


def _texto_relatorio_menu(chat_id, modo):
    cfg = _relatorio_cfg(chat_id, modo)
    nome = "🎯 ENTRADA POR GATILHO" if modo == "gatilho" else "🏄 SURF"
    return (
        f"📊 RELATÓRIO AUTOMÁTICO — {nome}\n\n"
        "Gera automaticamente um relatório após a quantidade de sinais que você escolher.\n\n"
        "📊 O relatório mostra os resultados da estratégia, porcentagem de GREEN e LOSS, "
        "distribuição dos acertos por Gale, sequências, balanço da progressão, sinais anteriores e blocos gerais.\n\n"
        f"⚙️ CONFIGURAÇÃO ATUAL: {_relatorio_status(cfg)}\n\n"
        "👇 Escolha após quantos sinais deseja gerar o relatório:"
    )


def _relatorio_texto_markup(modo):
    prefix = "gatrel" if modo == "gatilho" else "rel"
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🙈 OCULTAR TEXTO", callback_data=f"{prefix}_menu"))
    m.add(telebot.types.InlineKeyboardButton("✏️ ALTERAR TEXTO", callback_data=f"{prefix}_editar"))
    m.add(telebot.types.InlineKeyboardButton("♻️ RESTAURAR PADRÃO", callback_data=f"{prefix}_restaurar"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data=f"{prefix}_menu"))
    return m

def _apagar_mensagem_seguro(chat_id, message_id):
    if not message_id:
        return
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass

def _apagar_mensagem_depois(chat_id, message_id, segundos=5):
    if not message_id:
        return
    timer = threading.Timer(segundos, _apagar_mensagem_seguro, args=(chat_id, message_id))
    timer.daemon = True
    timer.start()

def _relatorio_receber_qtd(message, modo, prompt_message_id=None, painel_message_id=None):
    try:
        qtd = int((message.text or "").strip())
        if qtd <= 0 or qtd > 10000:
            raise ValueError
    except Exception:
        bot.send_message(message.chat.id, "❌ Digite um número inteiro entre 1 e 10000.")
        return
    cfg = _relatorio_cfg(message.chat.id, modo)
    cfg["relatorio_qtd"] = qtd
    cfg["relatorio_bloco"] = []
    cfg["relatorio_anterior"] = None
    cfg["relatorio_geral_blocos"] = 0
    cfg["relatorio_geral_sinais"] = 0
    cfg["relatorio_geral_greens"] = 0
    cfg["relatorio_geral_saldo"] = 0

    # Mensagens temporárias: pedido da quantidade + resposta digitada.
    _apagar_mensagem_seguro(message.chat.id, prompt_message_id)
    _apagar_mensagem_seguro(message.chat.id, message.message_id)

    # Volta ao próprio painel do relatório já atualizado, sem criar confirmação extra.
    if painel_message_id:
        try:
            bot.edit_message_text(
                _texto_relatorio_menu(message.chat.id, modo),
                message.chat.id, painel_message_id,
                reply_markup=_relatorio_markup(modo, message.chat.id)
            )
        except Exception:
            pass


def _relatorio_receber_texto(message, modo):
    texto = (message.text or "").strip()
    if not texto:
        bot.send_message(message.chat.id, "❌ Texto vazio. Nenhuma alteração foi feita.")
        return
    # Valida placeholders sem impedir que o usuário remova alguns deles.
    cfg = _relatorio_cfg(message.chat.id, modo)
    antigo = cfg.get("relatorio_texto")
    cfg["relatorio_texto"] = texto
    try:
        _relatorio_exemplo(cfg)
    except Exception:
        cfg["relatorio_texto"] = antigo
        bot.send_message(message.chat.id, "❌ O texto contém um campo inválido entre chaves { }. Nenhuma alteração foi feita.")
        return
    bot.send_message(message.chat.id, "✅ TEXTO DO RELATÓRIO ATUALIZADO.")


def _relatorio_maior_sequencia(bloco, alvo):
    melhor = atual = 0
    for item in bloco:
        if item["resultado"] == alvo:
            atual += 1
            melhor = max(melhor, atual)
        else:
            atual = 0
    return melhor


def _relatorio_gerar(cfg, bloco):
    qtd = len(bloco)
    greens = sum(1 for x in bloco if x["resultado"] == "green")
    loss = qtd - greens
    pctg = greens / qtd * 100 if qtd else 0
    pctl = loss / qtd * 100 if qtd else 0
    dist = {}
    maior = 0
    unidades_loss = 0
    for x in bloco:
        gale = int(x.get("gale", 0))
        maior = max(maior, gale)
        if x["resultado"] == "green":
            dist[gale] = dist.get(gale, 0) + 1
        else:
            limite = int(x.get("limite", 0))
            unidades_loss += (2 ** (limite + 1)) - 1
    linhas = []
    for gale in sorted(dist):
        nome = "✅ DIRETO" if gale == 0 else f"{_emoji_numero_gale(gale)} GALE {gale}"
        linhas.append(f"{nome}: {dist[gale]}")
    if not linhas:
        linhas = ["— Nenhum GREEN neste bloco"]
    saldo = greens - unidades_loss
    if saldo > 0:
        emoji, resultado = "🟢", "POSITIVO"
    elif saldo < 0:
        emoji, resultado = "🔴", "NEGATIVO"
    else:
        emoji, resultado = "⚪", "NEUTRO"

    # O último bloco é sempre o bloco que acabou de ser fechado.
    # A faixa é calculada pela quantidade GERAL de sinais já contabilizados,
    # evitando divergência entre o título do bloco e os BLOCOS GERAIS.
    geral_blocos = int(cfg.get("relatorio_geral_blocos", 0)) + 1
    geral_sinais = int(cfg.get("relatorio_geral_sinais", 0)) + qtd
    bloco_inicio = geral_sinais - qtd + 1
    bloco_fim = geral_sinais
    ultimo_bloco_txt = (
        f"📚 ÚLTIMO BLOCO — {bloco_inicio} A {bloco_fim}\n\n"
        f"📈 TAXA DE GREEN: {pctg:.1f}%\n"
        f"💰 SALDO: {saldo:+d} unidades\n"
        f"{emoji} RESULTADO: {resultado}"
    ).replace('.', ',')

    geral_greens = int(cfg.get("relatorio_geral_greens", 0)) + greens
    geral_saldo = int(cfg.get("relatorio_geral_saldo", 0)) + saldo
    geral_pct = (geral_greens / geral_sinais * 100) if geral_sinais else 0
    if geral_saldo > 0:
        geral_emoji, geral_resultado = "🟢", "POSITIVO"
    elif geral_saldo < 0:
        geral_emoji, geral_resultado = "🔴", "NEGATIVO"
    else:
        geral_emoji, geral_resultado = "⚪", "NEUTRO"
    geral_txt = (
        "📊 BLOCOS GERAIS\n\n"
        f"📦 BLOCOS ANALISADOS: {geral_blocos}\n"
        f"📈 TAXA GERAL DE GREEN: {geral_pct:.1f}%\n"
        f"💰 SALDO GERAL: {geral_saldo:+d} unidades\n"
        f"{geral_emoji} RESULTADO GERAL: {geral_resultado}"
    ).replace('.', ',')
    comparacao = ultimo_bloco_txt + "\n\n━━━━━━━━━━━━━━━━━━\n" + geral_txt

    dados = dict(
        qtd=qtd, greens=greens, loss=loss,
        taxa_green=f"{pctg:.1f}".replace('.', ','), taxa_loss=f"{pctl:.1f}".replace('.', ','),
        distribuicao="\n".join(linhas), seq_green=_relatorio_maior_sequencia(bloco, "green"),
        seq_loss=_relatorio_maior_sequencia(bloco, "loss"), maior_gale=(f"G{maior}" if maior else "DIRETO"),
        unidades_green=greens, unidades_loss=unidades_loss, saldo=f"{saldo:+d}",
        emoji_resultado=emoji, resultado=resultado, comparacao=comparacao,
    )
    modelo = cfg.get("relatorio_texto") or RELATORIO_AUTOMATICO_MODELO
    try:
        texto = modelo.format(**dados)
    except Exception:
        texto = RELATORIO_AUTOMATICO_MODELO.format(**dados)
    cfg["relatorio_anterior"] = {"pctg": pctg, "saldo": saldo}
    cfg["relatorio_geral_blocos"] = geral_blocos
    cfg["relatorio_geral_sinais"] = geral_sinais
    cfg["relatorio_geral_greens"] = geral_greens
    cfg["relatorio_geral_saldo"] = geral_saldo
    return texto

def _relatorio_registrar(modo, resultado, gale, limite):
    configs = ESTRATEGIAS_GATILHO_CONFIG if modo == "gatilho" else ESTRATEGIAS_CONFIG
    ativos = [(cid, c) for cid, c in configs.items() if c.get("ativa")]
    if not ativos:
        return
    _, cfg = ativos[-1]
    alvo = int(cfg.get("relatorio_qtd") or 0)
    if alvo <= 0:
        return
    bloco = cfg.setdefault("relatorio_bloco", [])
    bloco.append({"resultado": resultado, "gale": int(gale), "limite": int(limite)})
    if len(bloco) < alvo:
        return
    usar = bloco[:alvo]
    del bloco[:alvo]
    try:
        texto_relatorio = _relatorio_gerar(cfg, usar).rstrip()
        if not texto_relatorio.endswith("━━━━━━━━━━━━━━━━━━"):
            texto_relatorio += "\n\n━━━━━━━━━━━━━━━━━━"
        bot.send_message(ALERTAS_CHAT_ID, texto_relatorio)
    except Exception:
        traceback.print_exc()


def _desativar_para_alteracao(chat_id, modo):
    cfg = _relatorio_cfg(chat_id, modo)
    if not cfg.get("ativa"):
        return False
    _parar_monitor_real()
    cfg["ativa"] = False
    cfg["pausada"] = False
    return True


def _texto_seletor_estrategia_bot():
    return (
        "🧠 CONFIGURAR BOT E ATIVAR\n\n"
        "📌 Escolha como o bot deverá operar o SURF.\n\n"
        "🏄 SURF\n"
        "Mantém a estratégia atual do bot exatamente como já funciona.\n\n"
        "🎯 SURF — ENTRADA POR GATILHO\n"
        "Usa um Gale do SURF como gatilho. Quando o Gale escolhido acontece, "
        "a oportunidade imediatamente seguinte vira a entrada.\n\n"
        "🔥 GREEN APÓS 2 LOSS\n"
        "Observa a Entrada por Gatilho até confirmar 2 LOSS consecutivos. Depois, espera "
        "um novo Gale de ativação para liberar a entrada.\n\n"
        "👇 Escolha a estratégia:"
    )

def _seletor_estrategia_bot_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🏄 SURF", callback_data="config_modo_surf_normal"))
    m.add(telebot.types.InlineKeyboardButton("🎯 SURF — ENTRADA POR GATILHO", callback_data="gatcfg_menu"))
    m.add(telebot.types.InlineKeyboardButton("🔥 GREEN APÓS 2 LOSS", callback_data="greenloss_menu"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR AO BOT", callback_data="menu_bot"))
    return m

def configurar_estrategia_markup(chat_id):
    cfg = _cfg(chat_id)
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)

    markup.add(telebot.types.InlineKeyboardButton(
        "📖 MANUAL DO BOT", callback_data="config_manual"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "📡 CAMINHO AO VIVO", callback_data="caminho_ao_vivo"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        f"🔥 GALE DE ATIVAÇÃO — {_gale_txt(cfg['gale_gatilho'])}",
        callback_data="config_gale_menu"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        f"🏄 ESCOLHER SURF — {_surf_nome(cfg['surf'])}",
        callback_data="config_surf_menu"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        f"🛡 LIMITE DE GALES — {_limite_txt(cfg['limite_gales'])}",
        callback_data="config_limite_menu"
    ))

    aviso_txt = "NÃO CONFIGURADO" if cfg["aviso_antes"] is None else ("NÃO AVISAR" if cfg["aviso_antes"] == 0 else f"{cfg['aviso_antes']} antes")
    markup.add(telebot.types.InlineKeyboardButton(
        f"⚠️ CAMINHO ÚNICO CHEGANDO — {aviso_txt}",
        callback_data="config_aviso_menu"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        f"📊 RELATÓRIO AUTOMÁTICO — {_relatorio_status(cfg)}",
        callback_data="rel_menu"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "✍️ CONFIGURAR TEXTOS",
        callback_data="config_textos_menu"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "🖼️ GREEN / LOSS — SURF",
        callback_data="surf_midias"
    ))

    if cfg["ativa"] and not cfg["pausada"]:
        markup.add(telebot.types.InlineKeyboardButton(
            "⏸ PARAR BOT", callback_data="config_parar_bot"
        ))
    elif cfg["ativa"] and cfg["pausada"]:
        markup.add(telebot.types.InlineKeyboardButton(
            "▶️ INICIAR NOVAMENTE", callback_data="config_retomar_bot"
        ))
    else:
        if _config_completa(cfg):
            markup.add(telebot.types.InlineKeyboardButton(
                "🟢 ATIVAR ESTRATÉGIA", callback_data="config_ativar_resumo"
            ))
        else:
            markup.add(telebot.types.InlineKeyboardButton(
                "⚙️ COMPLETE A CONFIGURAÇÃO", callback_data="config_incompleta"
            ))

    markup.add(telebot.types.InlineKeyboardButton(
        "🗑 EXCLUIR ESTRATÉGIA", callback_data="config_excluir_confirmar"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR AO BOT", callback_data="menu_bot"
    ))
    return markup



def _textos_menu_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    for chave in ("online", "offline", "chegando", "cancelado", "sinal", "gales"):
        titulo = _TEXTOS_CANAL_META[chave][0]
        m.add(telebot.types.InlineKeyboardButton(titulo, callback_data=f"texto_menu:{chave}"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_modo_surf_normal"))
    return m

def _texto_menu_principal():
    return (
        "✍️ CONFIGURAR TEXTOS\n\n"
        "AQUI VOCÊ PERSONALIZA AS FRASES E OS EMOJIS DAS MENSAGENS ENVIADAS AO CANAL.\n\n"
        "📌 OS DADOS REAIS CALCULADOS PELO BOT NÃO SÃO ALTERADOS. "
        "NÚMEROS, CORES, SURF, GALES E RESULTADOS CONTINUAM VINDO DA LÓGICA.\n\n"
        "🖼️ AS IMAGENS GREEN E LOSS FICAM EM UMA ÁREA SEPARADA NO PAINEL DO SURF.\n\n"
        "👇 ESCOLHA QUAL MENSAGEM DESEJA CONFIGURAR:"
    )

def _surf_midias_markup(chat_id):
    cfg = _textos_canal_cfg(chat_id)
    greens = cfg.get("green_imagens", {})
    total_green = sum(1 for n in range(0, 21) if str(n) in greens)
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(
        f"🟢 IMAGENS GREEN — {total_green}/21", callback_data="green_imagens_menu"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        f"🔴 IMAGEM LOSS — {'✅ SALVA' if cfg.get('loss_imagem') else '▫️ PADRÃO'}",
        callback_data="surf_loss_menu"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_modo_surf_normal"))
    return m

def _surf_loss_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🖼️ ENVIAR / TROCAR IMAGEM LOSS", callback_data="surf_loss_enviar"))
    m.add(telebot.types.InlineKeyboardButton("🗑 REMOVER IMAGEM LOSS", callback_data="surf_loss_remover"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="surf_midias"))
    return m

def _texto_item_markup(chave):
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("✏️ ALTERAR TEXTO", callback_data=f"texto_editar:{chave}"))
    if chave in ("online", "offline"):
        cfg_img = _textos_canal_cfg(TEXTOS_CANAL_OWNER_CHAT_ID) if TEXTOS_CANAL_OWNER_CHAT_ID is not None else {}
        m.add(telebot.types.InlineKeyboardButton("🖼️ CADASTRAR / TROCAR IMAGEM", callback_data=f"texto_status_imagem:{chave}"))
        m.add(telebot.types.InlineKeyboardButton("🗑 REMOVER IMAGEM", callback_data=f"texto_status_imagem_remover:{chave}"))
    if chave == "green":
        m.add(telebot.types.InlineKeyboardButton(
            "🖼️ CONFIGURAR IMAGENS GREEN",
            callback_data="green_imagens_menu"
        ))
    elif chave == "loss":
        m.add(telebot.types.InlineKeyboardButton("🖼️ ALTERAR IMAGEM 4K", callback_data="texto_imagem:loss"))
        m.add(telebot.types.InlineKeyboardButton("🗑 REMOVER IMAGEM PERSONALIZADA", callback_data="texto_imagem_remover:loss"))
    m.add(telebot.types.InlineKeyboardButton("♻️ RESTAURAR PADRÃO", callback_data=f"texto_restaurar:{chave}"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_textos_menu"))
    return m

def _texto_item_painel(chat_id, chave):
    titulo, explicacao = _TEXTOS_CANAL_META[chave]
    atual = _texto_canal_modelo(chat_id, chave)
    extras = ""
    req = sorted(_TEXTOS_CANAL_REQUIRED.get(chave, set()))
    if req:
        extras = (
            "\n\n🔒 DADOS AUTOMÁTICOS PROTEGIDOS:\n"
            + " • ".join(req)
            + "\n\nAO ALTERAR A FRASE, MANTENHA ESSES CAMPOS NO TEXTO. "
              "O BOT PREENCHE OS VALORES REAIS AUTOMATICAMENTE."
        )
    if chave in ("online", "offline"):
        if chave == "online":
            extras += ("\n\n🖼️ IMAGEM DO AVISO\n\n📌 A imagem será utilizada inicialmente para informar no canal quando o bot estiver ONLINE e o monitoramento da estratégia for iniciado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS ONLINE.")
        else:
            extras += ("\n\n🖼️ IMAGEM DO AVISO\n\n📌 A imagem será utilizada para informar no canal quando o bot estiver OFFLINE e o monitoramento da estratégia for encerrado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS OFFLINE.")
    if chave == "green":
        extras += (
            "\n\n🖼️ O GREEN PODE TER UMA IMAGEM DIFERENTE PARA CADA RESULTADO: "
            "DIRETO / SEM GALE, GALE 1, GALE 2, GALE 3... ATÉ GALE 20. "
            "A LÓGICA ESCOLHE AUTOMATICAMENTE A IMAGEM CORRETA QUANDO O GREEN ACONTECE. "
            "A IMAGEM É ENVIADA SEPARADA DO TEXTO E DO REGISTRO DA OPERAÇÃO."
        )
    elif chave == "loss":
        extras += (
            "\n\n🖼️ A IMAGEM DO LOSS É ENVIADA SEPARADA DO TEXTO E DO REGISTRO DA OPERAÇÃO. "
            "VOCÊ PODE ENVIAR UMA FOTO OU UM ARQUIVO DE IMAGEM EM ALTA QUALIDADE/4K."
        )
    return (
        f"{titulo}\n\n"
        f"{explicacao}\n\n"
        "VOCÊ PODE ESCREVER UMA MENSAGEM CURTA OU GRANDE E USAR OS EMOJIS QUE QUISER."
        f"{extras}\n\n"
        "📌 TEXTO ATUAL:\n\n"
        f"{atual}\n\n"
        "👇 ESCOLHA O QUE DESEJA FAZER:"
    )

def _receber_texto_personalizado(message, chave):
    chat_id = message.chat.id
    novo = (message.text or "").strip()
    if not novo:
        bot.send_message(chat_id, "❌ TEXTO VAZIO. NADA FOI ALTERADO.", reply_markup=_texto_item_markup(chave))
        return
    faltando = [campo for campo in _TEXTOS_CANAL_REQUIRED.get(chave, set()) if campo not in novo]
    if faltando:
        bot.send_message(
            chat_id,
            "❌ NÃO FOI POSSÍVEL SALVAR.\n\n"
            "MANTENHA OS DADOS AUTOMÁTICOS OBRIGATÓRIOS:\n"
            + "\n".join(f"• {x}" for x in sorted(faltando))
            + "\n\nISSO GARANTE QUE A PERSONALIZAÇÃO NÃO ALTERE A LÓGICA DO BOT.",
            reply_markup=_texto_item_markup(chave),
        )
        return
    _textos_canal_cfg(chat_id)["textos"][chave] = novo
    bot.send_message(
        chat_id,
        "✅ TEXTO SALVO COM SUCESSO.\n\nNO CANAL ELE SERÁ ENVIADO EM MAIÚSCULAS.",
        reply_markup=_texto_item_markup(chave),
    )

def _green_limite_imagens(chat_id):
    # O cadastro das imagens GREEN não depende do limite operacional.
    # Deixamos sempre DIRETO + GALE 1 até GALE 20 disponíveis.
    return 20

def _green_nome_resultado(gale):
    gale = int(gale)
    return "DIRETO / SEM GALE" if gale == 0 else f"GALE {gale}"

def _green_imagens_markup(chat_id):
    limite = _green_limite_imagens(chat_id)
    imagens = _textos_canal_cfg(chat_id).get("green_imagens", {})

    m = telebot.types.InlineKeyboardMarkup(row_width=2)

    botoes = []
    for gale in range(0, limite + 1):
        salvo = "✅" if str(gale) in imagens else "▫️"
        nome = "DIRETO / SEM GALE" if gale == 0 else f"GALE {gale}"
        botoes.append(
            telebot.types.InlineKeyboardButton(
                f"{salvo} {nome}",
                callback_data=f"green_imagem_item:{gale}"
            )
        )

    for i in range(0, len(botoes), 2):
        m.row(*botoes[i:i+2])

    m.add(telebot.types.InlineKeyboardButton(
        "🗑 REMOVER TODAS AS IMAGENS GREEN",
        callback_data="green_imagens_remover_todas"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR",
        callback_data="texto_menu:green"
    ))
    return m

def _green_imagens_texto(chat_id):
    return (
        "🖼️ IMAGENS DO GREEN\n\n"
        "VOCÊ PODE CADASTRAR UMA IMAGEM DIFERENTE PARA CADA RESULTADO DO GREEN.\n\n"
        "📌 EXEMPLO:\n"
        "GREEN DIRETO / SEM GALE → IMAGEM DO DIRETO\n"
        "GREEN GALE 1 → IMAGEM DO GALE 1\n"
        "GREEN GALE 2 → IMAGEM DO GALE 2\n"
        "GREEN GALE 3 → IMAGEM DO GALE 3\n"
        "...\n\n"
        "🤖 QUANDO A OPERAÇÃO ACERTAR, O BOT IDENTIFICA AUTOMATICAMENTE "
        "EM QUAL GALE BATEU E ENVIA A IMAGEM CORRESPONDENTE.\n\n"
        "🛡 AS IMAGENS FICAM DISPONÍVEIS PARA CONFIGURAÇÃO DO DIRETO / SEM GALE "
        "ATÉ O GALE 20, INDEPENDENTEMENTE DO LIMITE OPERACIONAL CONFIGURADO.\n\n"
        "✅ = IMAGEM PERSONALIZADA CADASTRADA\n"
        "▫️ = USANDO A IMAGEM PADRÃO DO BOT\n\n"
        "👇 ESCOLHA QUAL GREEN DESEJA CONFIGURAR:"
    )

def _green_imagem_item_markup(gale):
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(
        "🖼️ ENVIAR / TROCAR IMAGEM 4K",
        callback_data=f"green_imagem_enviar:{int(gale)}"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "🗑 REMOVER IMAGEM DESTE GREEN",
        callback_data=f"green_imagem_remover:{int(gale)}"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR",
        callback_data="green_imagens_menu"
    ))
    return m

def _receber_imagem_green_gale(message, gale, prompt_message_id=None):
    chat_id = message.chat.id
    gale = int(gale)
    item = None

    if getattr(message, "photo", None):
        item = {"tipo": "photo", "file_id": message.photo[-1].file_id}
    elif getattr(message, "document", None):
        mime = (message.document.mime_type or "").lower()
        if mime.startswith("image/"):
            item = {"tipo": "document", "file_id": message.document.file_id}

    if not item:
        bot.send_message(
            chat_id,
            "❌ ENVIE UMA FOTO OU UM ARQUIVO DE IMAGEM.",
            reply_markup=_green_imagem_item_markup(gale),
        )
        return

    cfg_txt = _textos_canal_cfg(chat_id)
    cfg_txt.setdefault("green_imagens", {})[str(gale)] = item

    confirmacao = bot.send_message(
        chat_id,
        f"✅ IMAGEM DO GREEN {_green_nome_resultado(gale)} SALVA."
    )
    # Limpa a imagem enviada e a mensagem temporária de envio.
    # A confirmação mostra DIRETO / GALE correspondente e some após 5 segundos.
    _apagar_mensagem_seguro(chat_id, message.message_id)
    if prompt_message_id:
        _apagar_mensagem_seguro(chat_id, prompt_message_id)
    _apagar_mensagem_depois(chat_id, confirmacao.message_id, 5)

def _receber_imagem_personalizada(message, chave, prompt_message_id=None):
    chat_id = message.chat.id
    item = None
    if getattr(message, "photo", None):
        item = {"tipo": "photo", "file_id": message.photo[-1].file_id}
    elif getattr(message, "document", None):
        mime = (message.document.mime_type or "").lower()
        if mime.startswith("image/"):
            item = {"tipo": "document", "file_id": message.document.file_id}
    if not item:
        bot.send_message(
            chat_id,
            "❌ ENVIE UMA FOTO OU UM ARQUIVO DE IMAGEM.",
            reply_markup=_texto_item_markup(chave),
        )
        return
    _textos_canal_cfg(chat_id)[f"{chave}_imagem"] = item
    confirmacao = bot.send_message(chat_id, f"✅ IMAGEM DO {chave.upper()} SALVA.")
    _apagar_mensagem_seguro(chat_id, message.message_id)
    if prompt_message_id:
        _apagar_mensagem_seguro(chat_id, prompt_message_id)
    _apagar_mensagem_depois(chat_id, confirmacao.message_id, 5)

def _enviar_imagem_resultado(chat_id, chave, gale=None):
    cfg_txt = _textos_canal_cfg(chat_id)
    destino = _destino_canal_surf(chat_id)

    if chave == "green":
        chave_gale = str(int(gale or 0))
        imagem = cfg_txt.get("green_imagens", {}).get(chave_gale)

        # Compatibilidade: se ainda houver uma imagem GREEN da versão anterior,
        # ela serve como fallback enquanto não houver imagem específica do Gale.
        if imagem is None:
            imagem = cfg_txt.get("green_imagem")

        if imagem:
            if imagem["tipo"] == "document":
                bot.send_document(destino, imagem["file_id"])
            else:
                bot.send_photo(destino, imagem["file_id"])
            return

        bot.send_photo(destino, _alerta_card_bytes("green", gale))
        return

    imagem = cfg_txt.get("loss_imagem")
    if imagem:
        if imagem["tipo"] == "document":
            bot.send_document(destino, imagem["file_id"])
        else:
            bot.send_photo(destino, imagem["file_id"])
        return

    bot.send_photo(destino, _alerta_card_bytes("loss"))





_GATTEXT_PADRAO = {
    "online": (
        "📡 SINAIS ONLINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 BOT ONLINE\n\n"
        "🎯 ENTRADA POR GATILHO — MONITORAMENTO ATIVADO\n\n"
        "📡 MONITORAMENTO INICIADO.\n"
        "🎯 AGUARDANDO OPORTUNIDADE..."
    ),
    "offline": (
        "📴 SINAIS OFFLINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 BOT OFFLINE\n\n"
        "⏸ MONITORAMENTO INTERROMPIDO."
    ),
    "espera": "⏳ AGUARDANDO NOVO G{GALE_GATILHO}\n🎯 PRÓXIMA ENTRADA: {PROXIMA_ENTRADA}",
    "chegando": "⚠️ CAMINHO CHEGANDO\n📍 GALE ATUAL: G{GALE_ATUAL}",
    "cancelado": "❌ CAMINHO CANCELADO",
    "entrada": (
        "🎯 ENTRADA CONFIRMADA\n\n"
        "🔥 GATILHO: G{GALE_GATILHO}\n"
        "🏄 {SURF}\n"
        "🎯 {NIVEL}\n"
        "➡️ ENTRADA PARA {EMOJI_COR} {COR}\n"
        "📍 DEPOIS DO NÚMERO {NUMERO} {EMOJI_ULTIMA_COR}"
    ),
    "caminho": "📊 CAMINHO DA OPERAÇÃO",
    "resultado": "📊 RESULTADO DOS SINAIS",
}

_GATTEXT_META = {
    "online": ("📡 SINAIS ONLINE", set()),
    "offline": ("📴 SINAIS OFFLINE", set()),
    "espera": ("⏳ AGUARDANDO NOVO GATILHO", {"{GALE_GATILHO}", "{PROXIMA_ENTRADA}"}),
    "chegando": ("⚠️ CAMINHO CHEGANDO", {"{GALE_ATUAL}"}),
    "cancelado": ("❌ CAMINHO CANCELADO", set()),
    "entrada": ("🎯 ENTRADA CONFIRMADA", {"{GALE_GATILHO}", "{SURF}", "{NIVEL}", "{EMOJI_COR}", "{COR}", "{NUMERO}", "{EMOJI_ULTIMA_COR}"}),
    "caminho": ("📊 CAMINHO DA OPERAÇÃO", set()),
    "resultado": ("📊 RESULTADO DOS SINAIS", set()),
}

def _gattexto_cfg(chat_id):
    cfg = _cfg_gatilho(chat_id)
    cfg.setdefault("textos_sinais", {})
    return cfg["textos_sinais"]

def _gattexto_modelo(chat_id, chave):
    return _gattexto_cfg(chat_id).get(chave) or _GATTEXT_PADRAO[chave]

def _gattexto_formatar(chat_id, chave, **dados):
    modelo = _gattexto_modelo(chat_id, chave)
    try:
        return modelo.format(**dados).upper()
    except Exception:
        return _GATTEXT_PADRAO[chave].format(**dados).upper()

def _gattexto_chat_ativo():
    ativos = [cid for cid, c in ESTRATEGIAS_GATILHO_CONFIG.items() if c.get("ativa") and not c.get("pausada")]
    if ativos:
        return ativos[0]
    return _chat_textos_ativo()

def _gattexto_menu_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    for chave in ("online", "offline", "espera", "chegando", "cancelado", "entrada", "caminho", "resultado"):
        m.add(telebot.types.InlineKeyboardButton(_GATTEXT_META[chave][0], callback_data=f"gattexto_item:{chave}"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_menu"))
    return m

def _gattexto_item_markup(chave):
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("✏️ ALTERAR TEXTO", callback_data=f"gattexto_editar:{chave}"))
    if chave in ("online", "offline"):
        m.add(telebot.types.InlineKeyboardButton("🖼️ CADASTRAR / TROCAR IMAGEM", callback_data=f"gattexto_status_imagem:{chave}"))
        m.add(telebot.types.InlineKeyboardButton("🗑 REMOVER IMAGEM", callback_data=f"gattexto_status_imagem_remover:{chave}"))
    m.add(telebot.types.InlineKeyboardButton("♻️ RESTAURAR PADRÃO", callback_data=f"gattexto_restaurar:{chave}"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gattexto_menu"))
    return m

def _gattexto_painel(chat_id, chave):
    titulo, obrigatorios = _GATTEXT_META[chave]
    extras = ""
    if obrigatorios:
        extras = "\n\n🔒 CAMPOS AUTOMÁTICOS OBRIGATÓRIOS:\n" + "\n".join(f"• {x}" for x in sorted(obrigatorios))
    if chave == "online":
        extras += "\n\n🖼️ IMAGEM DO AVISO\n\n📌 A imagem será utilizada inicialmente para informar no canal quando o bot estiver ONLINE e o monitoramento da estratégia for iniciado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS ONLINE."
    elif chave == "offline":
        extras += "\n\n🖼️ IMAGEM DO AVISO\n\n📌 A imagem será utilizada para informar no canal quando o bot estiver OFFLINE e o monitoramento da estratégia for encerrado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS OFFLINE."
    return (
        f"{titulo}\n\n"
        "Este texto pertence somente à estratégia 🎯 SURF — ENTRADA POR GATILHO.\n"
        "Alterá-lo não muda a lógica do SURF nem os cálculos do bot."
        f"{extras}\n\n📌 TEXTO ATUAL:\n\n{_gattexto_modelo(chat_id, chave)}"
    )

def _gattexto_receber(message, chave):
    chat_id = message.chat.id
    novo = (message.text or "").strip()
    if not novo:
        bot.send_message(chat_id, "❌ TEXTO VAZIO. NADA FOI ALTERADO.", reply_markup=_gattexto_item_markup(chave))
        return
    obrigatorios = _GATTEXT_META[chave][1]
    faltando = [x for x in obrigatorios if x not in novo]
    if faltando:
        bot.send_message(chat_id, "❌ MANTENHA OS CAMPOS AUTOMÁTICOS:\n" + "\n".join(f"• {x}" for x in sorted(faltando)), reply_markup=_gattexto_item_markup(chave))
        return
    _gattexto_cfg(chat_id)[chave] = novo
    bot.send_message(chat_id, "✅ TEXTO SALVO COM SUCESSO.", reply_markup=_gattexto_item_markup(chave))

def _texto_manual_gatilho():
    return (
        "📖 MANUAL — SURF ENTRADA POR GATILHO\n\n"
        "🎯 COMO FUNCIONA\n"
        "Esta estratégia utiliza os Gales do SURF como gatilho para liberar uma entrada.\n\n"
        "🔥 Exemplo — Gatilho G3:\nG1 → G2 → G3 🔥\n"
        "O G3 não é a entrada. Ele confirma que a oportunidade imediatamente seguinte será utilizada.\n\n"
        "❌ Se o DIRETO perder, o bot não entra novamente na rodada seguinte.\n"
        "⏳ Ele aguarda um NOVO G3.\n🔥 Novo G3 → 🎯 GALE 1.\n"
        "A progressão continua entre novos gatilhos até GREEN ou até o limite configurado.\n\n"
        "🧬 CAMINHOS ÚNICOS\n"
        "O bot considera somente caminhos únicos do SURF. Caminhos repetidos/convergentes que chegam à mesma sequência real de rodadas não criam gatilhos duplicados.\n\n"
        "🏄 SURF\n"
        "Você pode escolher 🔴 SURF 2 VERMELHOS, ⚫ SURF 2 PRETOS ou 🔴⚫ OS DOIS. Cada caminho é analisado separadamente.\n\n"
        "📍 PONTO INICIAL\n"
        "Pode estar relacionado a:\n⚪ Após BRANCO\n🔴 Após VERMELHO\n⚫ Após PRETO\n"
        "🔢 Independente de qualquer número.\n\n"
        "⚠️ AVISO ANTES DO GATILHO\n"
        "Define quantos Gales antes o bot avisa que um caminho está chegando. O aviso não é uma entrada.\n\n"
        "🛡 LIMITE DE GALES\n"
        "Define até qual Gale a operação pode chegar. Se bater, GREEN e reinicia; se perder no limite, LOSS e reinicia.\n\n"
        "🖼️ GREEN / LOSS\n"
        "A Entrada por Gatilho possui imagens próprias e independentes do SURF normal.\n\n"
        "📊 RESULTADOS E RELATÓRIO\n"
        "O bot mantém o resultado dos sinais e pode gerar o Relatório Automático na quantidade configurada."
    )

def _gatcfg_midias(chat_id):
    cfg = _cfg_gatilho(chat_id)
    cfg.setdefault("green_imagens", {})
    cfg.setdefault("loss_imagem", None)
    cfg.setdefault("online_imagem", None)
    cfg.setdefault("offline_imagem", None)
    return cfg

def _gatcfg_green_nome(gale):
    gale = int(gale)
    return "DIRETO / SEM GALE" if gale == 0 else f"GALE {gale}"

def _gatcfg_midias_markup(chat_id):
    cfg = _gatcfg_midias(chat_id)
    greens = cfg.get("green_imagens", {})
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    total_green = sum(1 for n in range(0, 21) if str(n) in greens)
    m.add(telebot.types.InlineKeyboardButton(
        f"🟢 IMAGENS GREEN — {total_green}/21",
        callback_data="gatcfg_green_menu"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        f"🔴 IMAGEM LOSS — {'✅ SALVA' if cfg.get('loss_imagem') else '▫️ PADRÃO'}",
        callback_data="gatcfg_loss_menu"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_menu"))
    return m

def _gatcfg_green_markup(chat_id):
    greens = _gatcfg_midias(chat_id).get("green_imagens", {})
    m = telebot.types.InlineKeyboardMarkup(row_width=2)
    botoes = []
    for gale in range(0, 21):
        salvo = "✅" if str(gale) in greens else "▫️"
        botoes.append(telebot.types.InlineKeyboardButton(
            f"{salvo} {_gatcfg_green_nome(gale)}",
            callback_data=f"gatcfg_green_item:{gale}"
        ))
    for i in range(0, len(botoes), 2):
        m.row(*botoes[i:i+2])
    m.add(telebot.types.InlineKeyboardButton(
        "🗑 REMOVER TODAS AS IMAGENS GREEN",
        callback_data="gatcfg_green_remover_todas"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_midias"))
    return m

def _gatcfg_green_item_markup(gale):
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(
        "🖼️ ENVIAR / TROCAR IMAGEM",
        callback_data=f"gatcfg_green_enviar:{int(gale)}"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "🗑 REMOVER IMAGEM DESTE GREEN",
        callback_data=f"gatcfg_green_remover:{int(gale)}"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_green_menu"))
    return m

def _gatcfg_loss_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(
        "🖼️ ENVIAR / TROCAR IMAGEM LOSS",
        callback_data="gatcfg_loss_enviar"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "🗑 REMOVER IMAGEM LOSS",
        callback_data="gatcfg_loss_remover"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_midias"))
    return m

def _gatcfg_receber_green(message, gale, prompt_message_id=None):
    chat_id = message.chat.id
    item = None
    if getattr(message, "photo", None):
        item = {"tipo": "photo", "file_id": message.photo[-1].file_id}
    elif getattr(message, "document", None):
        mime = (message.document.mime_type or "").lower()
        if mime.startswith("image/"):
            item = {"tipo": "document", "file_id": message.document.file_id}
    if not item:
        bot.send_message(chat_id, "❌ ENVIE UMA FOTO OU ARQUIVO DE IMAGEM.",
                         reply_markup=_gatcfg_green_item_markup(gale))
        return
    _gatcfg_midias(chat_id).setdefault("green_imagens", {})[str(int(gale))] = item
    confirmacao = bot.send_message(
        chat_id,
        f"✅ IMAGEM GREEN {_gatcfg_green_nome(gale)} SALVA PARA A ENTRADA POR GATILHO."
    )
    _apagar_mensagem_seguro(chat_id, message.message_id)
    if prompt_message_id:
        _apagar_mensagem_seguro(chat_id, prompt_message_id)
    _apagar_mensagem_depois(chat_id, confirmacao.message_id, 5)

def _gatcfg_receber_loss(message, prompt_message_id=None):
    chat_id = message.chat.id
    item = None
    if getattr(message, "photo", None):
        item = {"tipo": "photo", "file_id": message.photo[-1].file_id}
    elif getattr(message, "document", None):
        mime = (message.document.mime_type or "").lower()
        if mime.startswith("image/"):
            item = {"tipo": "document", "file_id": message.document.file_id}
    if not item:
        bot.send_message(chat_id, "❌ ENVIE UMA FOTO OU ARQUIVO DE IMAGEM.",
                         reply_markup=_gatcfg_loss_markup())
        return
    _gatcfg_midias(chat_id)["loss_imagem"] = item
    confirmacao = bot.send_message(chat_id, "✅ IMAGEM LOSS SALVA PARA A ENTRADA POR GATILHO.")
    _apagar_mensagem_seguro(chat_id, message.message_id)
    if prompt_message_id:
        _apagar_mensagem_seguro(chat_id, prompt_message_id)
    _apagar_mensagem_depois(chat_id, confirmacao.message_id, 5)

def _gatcfg_enviar_imagem_resultado(chave, gale=None):
    chat_id = _chat_textos_ativo()
    # O chat de configuração ativo é o mesmo dono da estratégia.
    if chat_id is None:
        # fallback para a configuração ativa
        ativos = [cid for cid, c in ESTRATEGIAS_GATILHO_CONFIG.items()
                  if c.get("ativa") and not c.get("pausada")]
        chat_id = ativos[0] if ativos else None

    cfg = _gatcfg_midias(chat_id) if chat_id is not None else {}
    destino = ALERTAS_CHAT_ID
    if chave == "green":
        imagem = cfg.get("green_imagens", {}).get(str(int(gale or 0)))
        if imagem:
            if imagem["tipo"] == "document":
                bot.send_document(destino, imagem["file_id"])
            else:
                bot.send_photo(destino, imagem["file_id"])
            return
        bot.send_photo(destino, _alerta_card_bytes("green", gale))
        return

    imagem = cfg.get("loss_imagem")
    if imagem:
        if imagem["tipo"] == "document":
            bot.send_document(destino, imagem["file_id"])
        else:
            bot.send_photo(destino, imagem["file_id"])
        return
    bot.send_photo(destino, _alerta_card_bytes("loss"))


def _gatcfg_completa(cfg):
    return all(cfg.get(k) is not None for k in ("gale_gatilho", "surf", "limite_gales"))

def _texto_gatcfg_menu(chat_id):
    cfg = _cfg_gatilho(chat_id)
    if cfg["ativa"] and not cfg["pausada"]:
        status = "🟢 ATIVA"
    elif cfg["ativa"] and cfg["pausada"]:
        status = "⏸ PAUSADA"
    else:
        status = "🔴 DESATIVADA"
    return (
        "🎯 SURF — ENTRADA POR GATILHO\n\n"
        "📌 COMO FUNCIONA\n\n"
        "Esta estratégia usa os Gales do SURF como GATILHO para liberar uma entrada.\n\n"
        "🔥 Exemplo com G3:\n"
        "G1 → G2 → G3 🔥 GATILHO\n"
        "🎯 A oportunidade imediatamente seguinte é a ENTRADA.\n\n"
        "⚠️ O G3 não é a entrada. Ele apenas confirma que a próxima oportunidade será utilizada.\n\n"
        "❌ Se a entrada não bater, o bot não continua apostando nas rodadas seguintes.\n"
        "⏳ Ele espera um NOVO G3 acontecer.\n"
        "🔥 Novo G3 → 🎯 nova oportunidade.\n\n"
        "A progressão da operação acontece ENTRE OS GATILHOS: "
        "Direto → novo gatilho/G1 → novo gatilho/G2... até o limite escolhido.\n\n"
        f"🔥 Gale-gatilho: {_gale_txt(cfg['gale_gatilho'])}\n"
        f"🏄 SURF: {_surf_nome(cfg['surf'])}\n"
        f"🛡 Limite de Gales: {_limite_txt(cfg['limite_gales'])}\n"
        f"⚠️ Aviso antes do gatilho: {'NÃO AVISAR' if cfg.get('aviso_antes', 2) == 0 else str(cfg.get('aviso_antes', 2)) + ' Gale(s) antes'}\n"
        f"📡 Status: {status}\n\n"
        "👇 Configure a estratégia:"
    )

def _gatcfg_markup(chat_id):
    cfg = _cfg_gatilho(chat_id)
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("📖 MANUAL DO BOT", callback_data="gatcfg_manual"))
    m.add(telebot.types.InlineKeyboardButton(
        f"🔥 GALE-GATILHO — {_gale_txt(cfg['gale_gatilho'])}", callback_data="gatcfg_gale_menu"))
    m.add(telebot.types.InlineKeyboardButton(
        f"🏄 ESCOLHER SURF — {_surf_nome(cfg['surf'])}", callback_data="gatcfg_surf_menu"))
    m.add(telebot.types.InlineKeyboardButton(
        f"🛡 LIMITE DE GALES — {_limite_txt(cfg['limite_gales'])}", callback_data="gatcfg_limite_menu"))
    m.add(telebot.types.InlineKeyboardButton(
        f"⚠️ AVISO ANTES — {'NÃO AVISAR' if cfg.get('aviso_antes', 2) == 0 else str(cfg.get('aviso_antes', 2)) + ' GALE(S)'}", callback_data="gatcfg_aviso_menu"))
    m.add(telebot.types.InlineKeyboardButton(
        f"📊 RELATÓRIO AUTOMÁTICO — {_relatorio_status(cfg)}", callback_data="gatrel_menu"))
    m.add(telebot.types.InlineKeyboardButton(
        "✍️ CONFIGURAR TEXTOS", callback_data="gattexto_menu"))
    m.add(telebot.types.InlineKeyboardButton(
        "🖼️ GREEN / LOSS — ENTRADA POR GATILHO", callback_data="gatcfg_midias"))
    if cfg["ativa"] and not cfg["pausada"]:
        m.add(telebot.types.InlineKeyboardButton("⏸ PARAR BOT", callback_data="gatcfg_parar"))
    elif cfg["ativa"] and cfg["pausada"]:
        m.add(telebot.types.InlineKeyboardButton("▶️ INICIAR NOVAMENTE", callback_data="gatcfg_ativar"))
    elif _gatcfg_completa(cfg):
        m.add(telebot.types.InlineKeyboardButton("🟢 ATIVAR ESTRATÉGIA", callback_data="gatcfg_ativar"))
    else:
        m.add(telebot.types.InlineKeyboardButton("⚙️ COMPLETE A CONFIGURAÇÃO", callback_data="gatcfg_incompleta"))
    m.add(telebot.types.InlineKeyboardButton("🗑 EXCLUIR CONFIGURAÇÃO", callback_data="gatcfg_excluir"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="configurar_estrategia"))
    return m

def _gatcfg_gale_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=3)
    bs = [telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"gatcfg_gale_set:{n}") for n in range(1, 21)]
    for i in range(0, len(bs), 3):
        m.row(*bs[i:i+3])
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_menu"))
    return m

def _gatcfg_surf_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="gatcfg_surf_set:vermelho"))
    m.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="gatcfg_surf_set:preto"))
    m.add(telebot.types.InlineKeyboardButton("🔴⚫ OS DOIS", callback_data="gatcfg_surf_set:ambos"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_menu"))
    return m

def _gatcfg_aviso_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=2)
    botoes = [
        telebot.types.InlineKeyboardButton(
            f"{n} GALE{'S' if n > 1 else ''} ANTES",
            callback_data=f"gatcfg_aviso_set:{n}"
        )
        for n in range(1, 6)
    ]
    for i in range(0, len(botoes), 2):
        m.row(*botoes[i:i+2])
    m.add(telebot.types.InlineKeyboardButton("🚫 NÃO AVISAR", callback_data="gatcfg_aviso_set:0"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_menu"))
    return m


def _gatcfg_limite_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=3)
    bs = [telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"gatcfg_limite_set:{n}") for n in range(1, 21)]
    for i in range(0, len(bs), 3):
        m.row(*bs[i:i+3])
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_menu"))
    return m

def _texto_configurar_estrategia(chat_id):
    cfg = _cfg(chat_id)
    if cfg["ativa"] and not cfg["pausada"]:
        status = "🟢 ATIVA"
    elif cfg["ativa"] and cfg["pausada"]:
        status = "⏸ PAUSADA"
    else:
        status = "🔴 DESATIVADA"

    aviso = _aviso_txt(cfg["aviso_antes"])

    return (
        "🧠 CONFIGURAR BOT E ATIVAR\n\n"
        "Monte aqui a lógica que o bot deverá acompanhar para gerar os sinais.\n\n"
        f"🔥 Gale de ativação: {_gale_txt(cfg['gale_gatilho'])}\n"
        f"🏄 SURF: {_surf_nome(cfg['surf'])}\n"
        f"🛡 Limite de Gales: {_limite_txt(cfg['limite_gales'])}\n"
        f"⚠️ Caminho único chegando: {aviso}\n"
        "🧬 Caminhos: somente caminhos únicos; repetidos/convergentes são descartados.\n\n"
        f"📡 Status: {status}\n\n"
        "👇 Escolha o que deseja configurar:"
    )


def _texto_manual():
    return (
        "📖 MANUAL — ESTRATÉGIAS DO BOT\n\n"
        "🧬 CAMINHOS ÚNICOS\n"
        "O bot trabalha somente com caminhos únicos reais.\n"
        "Quando vários pontos de início chegam exatamente ao mesmo caminho, "
        "eles são tratados como repetidos/convergentes e não criam sinais diferentes.\n\n"
        "🔥 GALE DE ATIVAÇÃO\n"
        "Você escolhe o Gale que deseja monitorar. O nome ATIVAÇÃO diferencia esta regra da estratégia Entrada por Gatilho.  O sinal só é confirmado se o caminho "
        "realmente alcançar esse Gale.\n\n"
        "🏄 ESCOLHER SURF\n"
        "Define se a estratégia acompanha o SURF 2 VERMELHOS, SURF 2 PRETOS ou os dois. "
        "Quando os dois são escolhidos, cada SURF continua sendo analisado separadamente.\n\n"
        "🛡 LIMITE DE GALES\n"
        "Define até qual Gale a operação poderá ser acompanhada depois que a entrada for liberada.\n\n"
        "⚠️ CAMINHO ÚNICO CHEGANDO\n"
        "Define quantos Gales antes do alvo o bot começa a avisar que um caminho único está chegando. "
        "Se o caminho quebrar antes do alvo, o acompanhamento é cancelado.\n\n"
        "🎯 SINAL\n"
        "Ao chegar ao Gale de ativação configurado, o bot libera a entrada informando a cor da entrada "
        "e depois de qual número/cor ela foi confirmada."
    )


def _voltar_config_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_modo_surf_normal"))
    return m


def _gale_menu_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=3)
    botoes = [
        telebot.types.InlineKeyboardButton(f"G{g}", callback_data=f"config_gale_set:{g}")
        for g in range(2, 21)
    ]
    for i in range(0, len(botoes), 3):
        m.row(*botoes[i:i+3])
    m.add(telebot.types.InlineKeyboardButton(
        "✏️ DIGITAR OUTRO GALE",
        callback_data="config_placeholder_digitacao:gale"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_modo_surf_normal"))
    return m


def _texto_gale_menu(chat_id):
    cfg = _cfg(chat_id)
    return (
        "🔥 GALE DE ATIVAÇÃO\n\n"
        "📌 PARA QUE SERVE ESTA CONFIGURAÇÃO?\n\n"
        "Esta opção define em qual Gale o caminho único precisa chegar para ativar a entrada da estratégia.\n\n"
        "📌 Exemplo:\n"
        "Se escolher G12, o bot acompanha o caminho e só ativa/confirma o sinal quando realmente chegar ao G12.\n\n"
        f"🔥 Gale de ativação atual: {_gale_txt(cfg['gale_gatilho'])}\n\n"
        "👇 Escolha o Gale de ativação:"
    )


def _surf_menu_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="config_surf_set:vermelho"))
    m.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="config_surf_set:preto"))
    m.add(telebot.types.InlineKeyboardButton("🔴⚫ OS DOIS", callback_data="config_surf_set:ambos"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_modo_surf_normal"))
    return m


def _texto_surf_menu(chat_id):
    cfg = _cfg(chat_id)
    return (
        "🏄 ESCOLHER SURF\n\n"
        "📌 PARA QUE SERVE ESTA CONFIGURAÇÃO?\n\n"
        "Esta opção define qual caminho do SURF o bot deverá acompanhar para procurar o Gale de ativação configurado.\n\n"
        "O bot continuará trabalhando somente com caminhos únicos, eliminando caminhos repetidos/convergentes.\n\n"
        "Você pode acompanhar somente um dos SURFs ou deixar os dois funcionando ao mesmo tempo.\n\n"
        "🔴 SURF 2 VERMELHOS\n"
        "🔴🔴 → ⚫⚫ → 🔴🔴 → ⚫⚫...\n\n"
        "⚫ SURF 2 PRETOS\n"
        "⚫⚫ → 🔴🔴 → ⚫⚫ → 🔴🔴...\n\n"
        "🔴⚫ OS DOIS\n"
        "O bot acompanha os dois SURFs simultaneamente, mas cada caminho continua sendo analisado separadamente.\n\n"
        f"📍 O ponto inicial pode estar relacionado a:\n\n⚪ Após BRANCO\n🔴 Após VERMELHO\n⚫ Após PRETO\n\n🔢 Independente de qualquer número.\n\n📍 SURF configurado atualmente:\n{_surf_nome(cfg['surf'])}\n\n"
        "👇 Escolha qual SURF deseja acompanhar:"
    )


def _limite_menu_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=3)
    botoes = [
        telebot.types.InlineKeyboardButton(f"G{g}", callback_data=f"config_limite_set:{g}")
        for g in range(1, 13)
    ]
    for i in range(0, len(botoes), 3):
        m.row(*botoes[i:i+3])
    m.add(telebot.types.InlineKeyboardButton(
        "✏️ DIGITAR OUTRO LIMITE",
        callback_data="config_placeholder_digitacao:limite"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_modo_surf_normal"))
    return m


def _texto_limite_menu(chat_id):
    cfg = _cfg(chat_id)
    return (
        "🛡 LIMITE DE GALES\n\n"
        "📌 PARA QUE SERVE ESTA CONFIGURAÇÃO?\n\n"
        "Esta opção define até qual Gale o bot poderá acompanhar uma entrada depois que o sinal for confirmado.\n\n"
        "Exemplo:\n"
        "Se o limite escolhido for G6, o bot acompanhará:\n"
        "DIRETO → G1 → G2 → G3 → G4 → G5 → G6\n\n"
        "✅ Se bater em qualquer etapa, encerra como GREEN.\n"
        "❌ Se não bater até G6, encerra como LOSS — STOP G6.\n\n"
        "💡 LEMBRE-SE\n"
        "Defina seu limite de Gales de acordo com seu objetivo de lucro e com o risco que você está disposto a assumir.\n"
        "Quanto maior o limite de Gales, maior pode ser a exposição da operação.\n\n"
        f"📍 Limite configurado atualmente: {_limite_txt(cfg['limite_gales'])}\n\n"
        "👇 Escolha o limite da operação:"
    )


def _aviso_menu_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    for n in range(1, 6):
        m.add(telebot.types.InlineKeyboardButton(
            f"{n} GALE{'S' if n > 1 else ''} ANTES",
            callback_data=f"config_aviso_set:{n}"
        ))
    m.add(telebot.types.InlineKeyboardButton("🔕 NÃO AVISAR", callback_data="config_aviso_set:0"))
    m.add(telebot.types.InlineKeyboardButton(
        "✏️ DIGITAR OUTRA QUANTIDADE",
        callback_data="config_placeholder_digitacao:aviso"
    ))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_modo_surf_normal"))
    return m


def _texto_aviso_menu(chat_id):
    cfg = _cfg(chat_id)
    alvo = cfg["gale_gatilho"]
    antes = cfg["aviso_antes"]
    atual_txt = _aviso_txt(antes)
    if alvo is None:
        exemplo_txt = "Configure primeiro o Gale de ativação para calcular onde o primeiro aviso acontecerá."
    elif antes is None:
        exemplo_txt = "Escolha abaixo quantos Gales antes deseja receber o primeiro aviso."
    elif antes == 0:
        exemplo_txt = "Sem pré-alerta. O bot só enviará mensagem quando o gatilho for confirmado."
    else:
        primeiro = max(0, alvo - antes)
        exemplo_txt = f"Com o alvo em G{alvo}, o primeiro aviso será em G{primeiro}."
    return (
        "⚠️ CAMINHO ÚNICO CHEGANDO\n\n"
        "📌 PARA QUE SERVE ESTA CONFIGURAÇÃO?\n\n"
        "Esta opção define quando o bot deve começar a avisar que um caminho único está se aproximando do Gale de ativação.\n\n"
        f"🔥 Gale de ativação: {_gale_txt(alvo)}\n"
        f"📍 Configuração atual: {atual_txt}\n\n"
        f"{exemplo_txt}\n\n"
        "Se o caminho acertar antes de chegar ao Gale de ativação, o acompanhamento é cancelado automaticamente.\n\n"
        "👇 Escolha quando deseja receber o primeiro aviso:"
    )


def _texto_resumo_ativacao(chat_id):
    cfg = _cfg(chat_id)
    aviso = "NÃO AVISAR" if cfg["aviso_antes"] == 0 else f"{cfg['aviso_antes']} Gale(s) antes"
    primeiro = max(0, cfg["gale_gatilho"] - cfg["aviso_antes"]) if cfg["aviso_antes"] else None

    linhas = [
        "🟢 ATIVAR ESTRATÉGIA",
        "",
        "📋 CONFIRA SUA CONFIGURAÇÃO",
        "",
        f"🔥 Gale de ativação: G{cfg['gale_gatilho']}",
        f"🏄 SURF: {_surf_nome(cfg['surf'])}",
        f"🛡 Limite da operação: G{cfg['limite_gales']}",
        f"⚠️ Caminho único chegando: {aviso}",
        "🧬 Caminhos: somente caminhos únicos.",
        "🔁 Repetidos/convergentes são descartados.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "📡 COMO O BOT VAI TRABALHAR",
    ]
    if primeiro is not None:
        linhas.append(f"⚠️ Primeiro aviso: G{primeiro}")
    linhas.append(f"🎯 Confirmação do sinal: G{cfg['gale_gatilho']}")
    linhas += [
        "",
        f"Após confirmar: DIRETO → G1 → ... → G{cfg['limite_gales']}",
        "✅ Acertou → GREEN",
        f"❌ Não acertou até G{cfg['limite_gales']} → LOSS",
    ]
    return "\n".join(linhas)


def _ativar_resumo_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(
        "🟢 CONFIRMAR E ATIVAR",
        callback_data="config_confirmar_ativar"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR E ALTERAR",
        callback_data="config_modo_surf_normal"
    ))
    return m


def _texto_bot_ativada(chat_id):
    cfg = _cfg(chat_id)
    aviso = "NÃO AVISAR" if cfg["aviso_antes"] == 0 else f"{cfg['aviso_antes']} Gale(s) antes"

    return (
        "📡 SINAIS ONLINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 BOT ONLINE\n\n"
        "🟢 ESTRATÉGIA ATIVADA\n\n"
        f"🔥 Gale de ativação: G{cfg['gale_gatilho']}\n"
        f"🏄 SURF: {_surf_nome(cfg['surf'])}\n"
        f"🛡 LIMITE DE GALES: G{cfg['limite_gales']}\n"
        f"⚠️ Aviso: {aviso}\n"
        "🧬 Somente caminhos únicos\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📍 MONITORAMENTO INICIADO\n\n"
        "📡 Aguardando oportunidade..."
    )


def _texto_canal_ativada(chat_id):
    return _render_texto_canal(chat_id, "online")


def _zerar_estado_sessao_online():
    """Descarta qualquer acompanhamento/sinal da sessão anterior.

    A configuração escolhida pelo usuário é preservada.
    O histórico de 2.000 rodadas também é preservado para análise.
    """
    global alertas_surfe_operacoes, alertas_surfe_sinais_emitidos
    global alertas_surfe_caminhos_unicos_emitidos, alertas_surfe_prealerta
    global alertas_surfe_registro, alertas_surfe_registro_sinais
    global alertas_surfe_registro_sinais_seq, alertas_surfe_registro_sinais_vistos_chat
    global alertas_surfe_stats, alertas_surfe_ultima_rodada_detectada
    global alertas_surfe_ultimo_atraso, alertas_surfe_total_novas
    global alertas_gatilho_nivel_aposta
    global alertas_gatilho_status_message_id, alertas_gatilho_caminho_resultados
    global alertas_gatilho_espera_message_id, alertas_gatilho_chegando_message_id
    global alertas_gatilho_caminho_message_id, alertas_gatilho_entrada_message_id, alertas_gatilho_prealerta
    global alertas_gatilho_total_greens, alertas_gatilho_total_loss
    global alertas_surf_caminho_message_id, alertas_surf_entrada_message_id, alertas_surf_prealerta_message_id, alertas_surf_caminho_resultados

    with alertas_surfe_lock:
        alertas_surfe_operacoes = {}
        alertas_surfe_sinais_emitidos = set()
        alertas_surfe_caminhos_unicos_emitidos = set()
        alertas_surfe_prealerta = None
        caminho_ao_vivo_marcas.clear()
        alertas_surfe_registro.clear()
        alertas_surfe_registro_sinais.clear()
        alertas_surfe_registro_sinais_seq = 0
        alertas_surfe_registro_sinais_vistos_chat.clear()
        alertas_surfe_stats = {
            "green": 0,
            "loss": 0,
            "direto": 0,
            "gales": {n: 0 for n in range(1, ALERTAS_SURF_STOP_GALE + 1)},
        }
        alertas_surfe_ultima_rodada_detectada = None
        alertas_surfe_ultimo_atraso = None
        alertas_surfe_total_novas = 0
        alertas_gatilho_nivel_aposta = 0
        alertas_gatilho_status_message_id = None
        alertas_gatilho_espera_message_id = None
        alertas_gatilho_chegando_message_id = None
        alertas_gatilho_caminho_message_id = None
        alertas_gatilho_entrada_message_id = None
        alertas_gatilho_caminho_resultados = []
        alertas_gatilho_prealerta = None
        alertas_gatilho_total_greens = 0
        alertas_gatilho_total_loss = 0
        alertas_surf_caminho_message_id = None
        alertas_surf_entrada_message_id = None
        alertas_surf_prealerta_message_id = None
        alertas_surf_caminho_resultados = []



def _configurar_e_iniciar_monitor_real(chat_id):
    """Aplica a configuração atual e inicia uma sessão NOVA do monitor ao vivo."""
    global ALERTAS_SURF_GATILHO, ALERTAS_SURF_STOP_GALE, ALERTAS_SURF_AVISO_ANTES
    global ALERTAS_MODO_ESTRATEGIA, alertas_gatilho_nivel_aposta
    global alertas_surfe_ativos

    cfg = _cfg(chat_id)
    ALERTAS_MODO_ESTRATEGIA = "surf"
    alertas_gatilho_nivel_aposta = 0
    ALERTAS_SURF_GATILHO = int(cfg["gale_gatilho"])
    ALERTAS_SURF_STOP_GALE = int(cfg["limite_gales"])
    ALERTAS_SURF_AVISO_ANTES = int(cfg["aviso_antes"])

    modo_cfg = cfg["surf"]
    modo_monitor = {
        "vermelho": "Vermelho",
        "preto": "Preto",
        "ambos": "Ambos",
    }.get(modo_cfg)

    if modo_monitor is None:
        raise RuntimeError("SURF não configurado.")

    with alertas_surfe_lock:
        alertas_surfe_ativos = True

    try:
        _iniciar_monitor_alertas_surfe(modo_monitor)
    except Exception:
        with alertas_surfe_lock:
            alertas_surfe_ativos = False
        raise



def _configurar_e_iniciar_monitor_gatilho(chat_id):
    """Inicia o monitor real usando a lógica ENTRADA POR GATILHO."""
    global ALERTAS_SURF_GATILHO, ALERTAS_SURF_STOP_GALE, ALERTAS_SURF_AVISO_ANTES
    global ALERTAS_MODO_ESTRATEGIA, alertas_gatilho_nivel_aposta
    global alertas_surfe_ativos

    cfg = _cfg_gatilho(chat_id)
    ALERTAS_MODO_ESTRATEGIA = "entrada_gatilho"
    ALERTAS_SURF_GATILHO = int(cfg["gale_gatilho"])
    ALERTAS_SURF_STOP_GALE = int(cfg["limite_gales"])
    ALERTAS_SURF_AVISO_ANTES = int(cfg.get("aviso_antes", 2))
    alertas_gatilho_nivel_aposta = 0

    modo_monitor = {
        "vermelho": "Vermelho",
        "preto": "Preto",
        "ambos": "Ambos",
    }.get(cfg["surf"])
    if modo_monitor is None:
        raise RuntimeError("SURF não configurado.")

    with alertas_surfe_lock:
        alertas_surfe_ativos = True
    try:
        _iniciar_monitor_alertas_surfe(modo_monitor)
    except Exception:
        with alertas_surfe_lock:
            alertas_surfe_ativos = False
        raise

def _parar_monitor_real():
    """Desliga o monitor ao vivo e descarta a sessão atual."""
    global alertas_surfe_ativos, alertas_surfe_ultima_rodada_id, alertas_surfe_modo
    with alertas_surfe_lock:
        alertas_surfe_ativos = False
        alertas_surfe_ultima_rodada_id = None
        alertas_surfe_modo = None
    _zerar_estado_sessao_online()



def _texto_sinais_offline():
    """Texto completo exibido dentro do BOT ANALISADOR."""
    return (
        "📴 SINAIS OFFLINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 BOT OFFLINE\n\n"
        "⏸ Monitoramento interrompido.\n\n"
        "📌 O acompanhamento atual foi encerrado.\n\n"
        "🔄 Ao iniciar novamente, o bot começará\n"
        "um novo monitoramento a partir da rodada\n"
        "mais recente daquele momento.\n\n"
        "🚫 Caminhos, Gales e sinais da execução\n"
        "anterior não serão continuados.\n\n"
        "🧬 Isso evita incoerências na análise dos\n"
        "caminhos, garantindo que cada novo\n"
        "monitoramento comece de um ponto válido\n"
        "e acompanhe somente os novos acontecimentos."
    )


def _texto_canal_offline(chat_id=None):
    """Texto curto enviado automaticamente ao CANAL DE SINAIS."""
    chat_id = chat_id if chat_id is not None else _chat_textos_ativo()
    if chat_id is None:
        return _TEXTOS_CANAL_PADRAO["offline"]
    return _render_texto_canal(chat_id, "offline")


def _destino_canal_surf(chat_id=None):
    """Retorna exclusivamente o canal de alertas já configurado no bot."""
    if "ALERTAS_CHAT_ID" not in globals() or not globals()["ALERTAS_CHAT_ID"]:
        raise RuntimeError("ALERTAS_CHAT_ID não está configurado.")
    return globals()["ALERTAS_CHAT_ID"]


def _enviar_imagem_status_canal(chat_id, chave, gatilho=False):
    if chave not in ("online", "offline"):
        return
    cfg_img = _gatcfg_midias(chat_id) if gatilho else _textos_canal_cfg(chat_id)
    imagem = cfg_img.get(f"{chave}_imagem")
    if not imagem:
        return
    destino = _destino_canal_surf(chat_id)
    if imagem.get("tipo") == "document":
        bot.send_document(destino, imagem["file_id"])
    else:
        bot.send_photo(destino, imagem["file_id"])

def _enviar_canal_surf(chat_id, texto):
    try:
        bot.send_message(_destino_canal_surf(chat_id), texto)
    except Exception:
        traceback.print_exc()


def _texto_exclusao(chat_id):
    cfg = _cfg(chat_id)
    aviso = "NÃO AVISAR" if cfg["aviso_antes"] == 0 else f"{cfg['aviso_antes']} Gale(s) antes"
    return (
        "🗑 EXCLUIR ESTRATÉGIA\n\n"
        "⚠️ ATENÇÃO\n\n"
        "Esta ação excluirá a configuração desta estratégia.\n\n"
        f"🔥 Gatilho: G{cfg['gale_gatilho']}\n"
        f"🏄 SURF: {_surf_nome(cfg['surf'])}\n"
        f"🛡 Limite: G{cfg['limite_gales']}\n"
        f"⚠️ Aviso: {aviso}\n\n"
        "Depois de excluir, será necessário configurar uma nova estratégia para voltar a utilizá-la.\n\n"
        "Deseja realmente excluir?"
    )


def _excluir_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(
        "🗑 SIM, EXCLUIR",
        callback_data="config_excluir_sim"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "⬅️ NÃO, VOLTAR",
        callback_data="config_modo_surf_normal"
    ))
    return m



# ==============================================================================
# INVESTIGAÇÃO — leitura detalhada dos caminhos do SURF
# ==============================================================================
# Esta área é somente para conferência. Ela não altera o motor do SURF,
# os alertas, as estatísticas oficiais ou qualquer regra já existente.

def _investigacao_texto_intro():
    return "\n".join([
        "🔎 INVESTIGAÇÃO",
        "",
        "Ferramenta para conferir detalhadamente os caminhos do SURF nas 2.000 rodadas.",
        "",
        "Escolha qual SURF deseja investigar.",
        "O bot mostrará os registros em texto, com 1 rodada antes do G1, até o Gale escolhido + 1 rodada seguinte.",
        "",
        "📌 Esta ferramenta é somente para investigação e não altera nenhuma estratégia do bot.",
        "",
        "👇 Escolha o SURF:",
    ])


def _investigacao_markup_caminhos():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton(
        "🔴 SURF 2 VERMELHOS", callback_data="investigacao_caminho:Vermelho"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "⚫ SURF 2 PRETOS", callback_data="investigacao_caminho:Preto"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR", callback_data="voltar_painel_principal"
    ))
    return markup


def _investigacao_markup_gales(caminho_nome):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    botoes = [
        telebot.types.InlineKeyboardButton(
            f"G{gale}", callback_data=f"investigacao_gale:{caminho_nome}:{gale}:0"
        )
        for gale in range(1, 17)
    ]
    for pos in range(0, len(botoes), 2):
        markup.row(*botoes[pos:pos + 2])
    markup.add(telebot.types.InlineKeyboardButton(
        "🔄 TROCAR SURF", callback_data="investigacao"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR AO PAINEL", callback_data="voltar_painel_principal"
    ))
    return markup


def _investigacao_cor_jogada(caminho_nome, pos_relativa):
    """Mesma alternância de 2 em 2 usada pelo SURF oficial."""
    bloco = ((pos_relativa - 1) // 2) % 2
    if caminho_nome == "Vermelho":
        return "Vermelho" if bloco == 0 else "Preto"
    return "Preto" if bloco == 0 else "Vermelho"


def _investigacao_montar_trecho(dados, indice_inicio, indice_g1, indice_gale_alvo, caminho_nome, gale_alvo):
    """Monta 1 rodada antes do G1, o caminho até o Gale alvo e +1 rodada seguinte."""
    trecho = []
    inicio = max(indice_inicio, indice_g1 - 1)
    fim = min(len(dados), indice_gale_alvo + 2)
    gale = 0

    for indice_abs in range(inicio, fim):
        rodada = dados[indice_abs]
        pos_relativa = indice_abs - indice_inicio
        saiu = normalizar_cor_analise(rodada)
        jogaria = _investigacao_cor_jogada(caminho_nome, pos_relativa)

        if indice_abs < indice_g1:
            resultado = "⬅️ ANTES DO G1"
            ordem = 0
            tipo = "antes"
        else:
            if saiu == jogaria:
                gale = 0
                resultado = "✅"
            else:
                gale += 1
                resultado = f"❌ G{gale}"
            ordem = indice_abs - indice_g1 + 1
            tipo = "depois" if indice_abs > indice_gale_alvo else "gale"
            if tipo == "depois":
                resultado += f"  ⬅️ DEPOIS DO G{gale_alvo}"

        data, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
        trecho.append({
            "ordem": ordem,
            "numero": rodada.get("numero", "?"),
            "saiu": saiu,
            "jogaria": jogaria,
            "resultado": resultado,
            "data": data,
            "hora": hora,
            "tipo": tipo,
        })
    return trecho


def _investigacao_encontrar(caminho_nome, gale_alvo, pagina=0, por_pagina=2):
    """Localiza CAMINHOS ÚNICOS que alcançaram o Gale escolhido.

    O cálculo do SURF continua exatamente igual ao anterior: todas as 1.999
    posições possíveis são testadas. A única diferença é a etapa de exibição:
    quando pontos iniciais diferentes chegam exatamente ao mesmo trecho real
    G1 -> Gale escolhido, essa sequência é contada apenas uma vez.

    A identidade do caminho usa as rodadas reais do trecho:
    ID/horário + número + cor, do G1 até o Gale escolhido.

    Para manter o bot leve, apenas os caminhos únicos da página solicitada
    têm o desenho completo reconstruído.
    """
    if caminho_nome not in ("Vermelho", "Preto") or not (1 <= gale_alvo <= 16):
        return 0, []

    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    pagina = max(0, int(pagina))
    primeiro = pagina * por_pagina
    ultimo = primeiro + por_pagina

    total_unicos = 0
    encontrados = []
    assinaturas_vistas = set()

    for indice_inicio in range(max(0, len(dados) - 1)):
        gale = 0
        indice_g1 = None

        for indice_abs in range(indice_inicio + 1, len(dados)):
            rodada = dados[indice_abs]
            saiu = normalizar_cor_analise(rodada)
            if saiu not in ("Preto", "Vermelho", "Branco"):
                continue

            pos_relativa = indice_abs - indice_inicio
            jogaria = _investigacao_cor_jogada(caminho_nome, pos_relativa)

            if saiu == jogaria:
                gale = 0
                indice_g1 = None
                continue

            gale += 1
            if gale == 1:
                indice_g1 = indice_abs

            if gale == gale_alvo and indice_g1 is not None:
                assinatura = []
                for idx_sig in range(indice_g1, indice_abs + 1):
                    r_sig = dados[idx_sig]
                    assinatura.append((
                        str(r_sig.get("rodada_id") or r_sig.get("instant") or r_sig.get("tempo") or ""),
                        str(r_sig.get("numero")),
                        normalizar_cor_analise(r_sig),
                    ))
                assinatura = tuple(assinatura)

                # Pontos diferentes que convergiram para o mesmo G1 -> Gale
                # representam UM caminho único.
                if assinatura in assinaturas_vistas:
                    continue
                assinaturas_vistas.add(assinatura)

                if primeiro <= total_unicos < ultimo:
                    ponto = dados[indice_inicio]
                    data_ponto, hora_ponto = formatar_data_hora(
                        ponto.get("instant"), ponto.get("tempo")
                    )
                    inicio_g1 = dados[indice_g1]
                    data_g1, hora_g1 = formatar_data_hora(
                        inicio_g1.get("instant"), inicio_g1.get("tempo")
                    )
                    trecho = _investigacao_montar_trecho(
                        dados, indice_inicio, indice_g1, indice_abs, caminho_nome, gale_alvo
                    )
                    encontrados.append({
                        "indice_inicio": indice_inicio,
                        "ponto_numero": ponto.get("numero", "?"),
                        "ponto_cor": normalizar_cor_analise(ponto),
                        "ponto_data": data_ponto,
                        "ponto_hora": hora_ponto,
                        "g1_data": data_g1,
                        "g1_hora": hora_g1,
                        "trecho": trecho,
                    })

                total_unicos += 1

    return total_unicos, encontrados


def _investigacao_linha_registro(item):
    """Linha alinhada no mesmo padrão visual usado pelo SURF."""
    numero = str(item.get("numero", "?"))
    saiu = item.get("saiu")
    jogaria = item.get("jogaria")

    # Figure Space mantém números de 1 e 2 dígitos ocupando a mesma largura
    # sem usar bloco monoespaçado/cinza do Telegram.
    numero_fmt = ("\u2007" + numero) if len(numero) == 1 else numero
    ordem = int(item.get("ordem", 0))
    ordem_fmt = "  " if item.get("tipo") == "antes" else f"{ordem:02d}"

    return (
        f"{ordem_fmt} {item['hora']}  "
        f"{emoji_cor(saiu)} {numero_fmt} - {emoji_cor(jogaria)}  {item['resultado']}"
    )


def _investigacao_enviar_resultado(chat_id, caminho_nome, gale_alvo, pagina=0):
    por_pagina = 2
    total_registros, registros = _investigacao_encontrar(
        caminho_nome, gale_alvo, pagina=pagina, por_pagina=por_pagina
    )

    emoji = "🔴" if caminho_nome == "Vermelho" else "⚫"
    nome = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"

    if not registros:
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            "↩️ ESCOLHER OUTRO GALE", callback_data=f"investigacao_caminho:{caminho_nome}"
        ))
        markup.add(telebot.types.InlineKeyboardButton(
            "🔄 TROCAR SURF", callback_data="investigacao"
        ))
        bot.send_message(
            chat_id,
            f"🔎 INVESTIGAÇÃO — {emoji} {nome}\n\n"
            f"🎯 Gale investigado: G{gale_alvo}\n"
            f"📚 Base: {ANALYSIS_ROUNDS} rodadas\n\n"
            "❌ Nenhum caminho chegou a esse Gale na janela atual.",
            reply_markup=markup,
        )
        return

    # Um caminho completo ocupa bastante texto. Dois por página continuam
    # confortavelmente abaixo do limite de mensagem do Telegram.
    total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)
    pagina = max(0, min(pagina, total_paginas - 1))
    inicio_global = pagina * por_pagina

    linhas = [
        f"🔎 INVESTIGAÇÃO — {emoji} {nome}",
        "",
        f"🎯 Gale investigado: G{gale_alvo}",
        f"📚 Base: {ANALYSIS_ROUNDS} rodadas",
        f"🧬 Caminhos únicos encontrados: {total_registros}",
        f"📄 Página: {pagina + 1}/{total_paginas}",
        "",
        "📌 Cada caminho único mostra 1 rodada antes do G1, o caminho até o Gale escolhido e + 1 rodada seguinte.",
    ]

    for deslocamento, reg in enumerate(registros):
        pos_global = inicio_global + deslocamento
        linhas += [
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"🧬 CAMINHO ÚNICO {pos_global + 1}/{total_registros}",
            f"📍 Ponto inicial: {emoji_cor(reg['ponto_cor'])} {reg['ponto_numero']} • {reg['ponto_data']} {reg['ponto_hora']}",
            f"▶️ G1 começou: {reg['g1_data']} {reg['g1_hora']}",
            "",
        ]
        linhas.extend(_investigacao_linha_registro(item) for item in reg["trecho"])

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if pagina > 0:
        nav.append(telebot.types.InlineKeyboardButton(
            "⬅️ ANTERIOR", callback_data=f"investigacao_gale:{caminho_nome}:{gale_alvo}:{pagina - 1}"
        ))
    if pagina + 1 < total_paginas:
        nav.append(telebot.types.InlineKeyboardButton(
            "PRÓXIMA ➡️", callback_data=f"investigacao_gale:{caminho_nome}:{gale_alvo}:{pagina + 1}"
        ))
    if nav:
        markup.row(*nav)
    markup.add(telebot.types.InlineKeyboardButton(
        "↩️ ESCOLHER OUTRO GALE", callback_data=f"investigacao_caminho:{caminho_nome}"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "🔄 TROCAR SURF", callback_data="investigacao"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR AO PAINEL", callback_data="voltar_painel_principal"
    ))
    bot.send_message(chat_id, "\n".join(linhas), reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "investigacao")
def investigacao_callback(call):
    try:
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            _investigacao_texto_intro(),
            reply_markup=_investigacao_markup_caminhos(),
        )
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro na investigação: {type(erro).__name__}: {str(erro)[:250]}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("investigacao_caminho:"))
def investigacao_caminho_callback(call):
    try:
        bot.answer_callback_query(call.id)
        caminho_nome = call.data.split(":", 1)[1]
        emoji = "🔴" if caminho_nome == "Vermelho" else "⚫"
        nome = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"
        bot.send_message(
            call.message.chat.id,
            f"🔎 INVESTIGAÇÃO — {emoji} {nome}\n\n"
            "Escolha qual Gale deseja investigar.\n\n"
            "O bot localizará os caminhos únicos em que esse Gale foi alcançado e mostrará cada sequência real diferente em texto.",
            reply_markup=_investigacao_markup_gales(caminho_nome),
        )
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao escolher o SURF: {type(erro).__name__}: {str(erro)[:250]}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("investigacao_gale:"))
def investigacao_gale_callback(call):
    try:
        bot.answer_callback_query(call.id, "Calculando investigação...")
        _, caminho_nome, gale_txt, pagina_txt = call.data.split(":", 3)
        _investigacao_enviar_resultado(
            call.message.chat.id,
            caminho_nome,
            int(gale_txt),
            int(pagina_txt),
        )
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao calcular a investigação: {type(erro).__name__}: {str(erro)[:250]}")


def _controle_geral_assinatura_trecho(dados, indice_g1, indice_gale):
    """Assinatura de uma ocorrência real: horário + número + cor do G1 até o Gale."""
    assinatura = []
    for idx in range(indice_g1, indice_gale + 1):
        rodada = dados[idx]
        assinatura.append((
            str(rodada.get("instant") or rodada.get("tempo") or ""),
            str(rodada.get("numero")),
            normalizar_cor_analise(rodada),
        ))
    return tuple(assinatura)


def _controle_geral_montar_trecho_unico(dados, indice_inicio, indice_g1, indice_gale, caminho_nome, gale):
    """Reaproveita exatamente o desenho da Investigação."""
    return _investigacao_montar_trecho(
        dados,
        indice_inicio,
        indice_g1,
        indice_gale,
        caminho_nome,
        gale,
    )


def _controle_geral_surfe_analisar_estrategia(caminho_nome):
    """Analisa todos os pontos e agrupa convergências em CAMINHOS ÚNICOS.

    Cada ponto inicial continua sendo testado separadamente.
    Porém, se pontos diferentes terminarem no mesmo trecho real G1 -> maior Gale
    (mesmos números/cores/horários), eles pertencem ao mesmo caminho único.
    """
    if caminho_nome not in ("Vermelho", "Preto"):
        return None

    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    if len(dados) < 2:
        return {
            "caminho": caminho_nome,
            "total_rodadas": len(dados),
            "total_pontos": 0,
            "distribuicao": {},
            "grupos": {},
        }

    # Por Gale:
    # bruto = quantidade de pontos de início cujo MAIOR Gale foi aquele.
    # grupos = ocorrências reais únicas, agrupadas pela sequência G1 -> Gale.
    distribuicao = {}
    grupos_por_gale = {}

    for indice_inicio in range(len(dados) - 1):
        gale_atual = 0
        indice_g1_atual = None

        maior_gale = 0
        maior_indice_g1 = None
        maior_indice_gale = None

        for pos_relativa, rodada in enumerate(dados[indice_inicio + 1:], 1):
            indice_abs = indice_inicio + pos_relativa
            saiu = normalizar_cor_analise(rodada)
            jogaria = _investigacao_cor_jogada(caminho_nome, pos_relativa)

            if saiu == jogaria:
                gale_atual = 0
                indice_g1_atual = None
                continue

            gale_atual += 1
            if gale_atual == 1:
                indice_g1_atual = indice_abs

            if gale_atual > maior_gale:
                maior_gale = gale_atual
                maior_indice_g1 = indice_g1_atual
                maior_indice_gale = indice_abs

        if maior_gale <= 0 or maior_indice_g1 is None or maior_indice_gale is None:
            continue

        distribuicao[maior_gale] = distribuicao.get(maior_gale, 0) + 1

        assinatura = _controle_geral_assinatura_trecho(
            dados, maior_indice_g1, maior_indice_gale
        )

        grupos_gale = grupos_por_gale.setdefault(maior_gale, {})
        grupo = grupos_gale.get(assinatura)

        ponto = dados[indice_inicio]
        data_ponto, hora_ponto = formatar_data_hora(
            ponto.get("instant"), ponto.get("tempo")
        )
        g1 = dados[maior_indice_g1]
        data_g1, hora_g1 = formatar_data_hora(g1.get("instant"), g1.get("tempo"))

        if grupo is None:
            grupos_gale[assinatura] = {
                "indice_inicio": indice_inicio,
                "indice_g1": maior_indice_g1,
                "indice_gale": maior_indice_gale,
                "ponto_numero": ponto.get("numero", "?"),
                "ponto_cor": normalizar_cor_analise(ponto),
                "ponto_data": data_ponto,
                "ponto_hora": hora_ponto,
                "g1_data": data_g1,
                "g1_hora": hora_g1,
                "quantidade_convergente": 1,
                "trecho": _controle_geral_montar_trecho_unico(
                    dados,
                    indice_inicio,
                    maior_indice_g1,
                    maior_indice_gale,
                    caminho_nome,
                    maior_gale,
                ),
            }
        else:
            grupo["quantidade_convergente"] += 1

    grupos = {}
    resumo = {}
    for gale, bruto in distribuicao.items():
        unicos = list((grupos_por_gale.get(gale) or {}).values())
        convergentes = max(0, bruto - len(unicos))
        grupos[gale] = unicos
        resumo[gale] = {
            "brutos": bruto,
            "unicos": len(unicos),
            "convergentes": convergentes,
        }

    return {
        "caminho": caminho_nome,
        "total_rodadas": len(dados),
        "total_pontos": max(0, len(dados) - 1),
        "distribuicao": distribuicao,
        "resumo": resumo,
        "grupos": grupos,
    }


def _controle_geral_surfe_texto_intro():
    return "\n".join([
        "🐺 CONTROLE GERAL — SURF",
        "",
        "📊 Ferramenta para investigar o comportamento dos Gales nas 2.000 rodadas mais recentes.",
        "",
        "📍 O ponto inicial pode estar relacionado a:\n\n⚪ Após BRANCO\n🔴 Após VERMELHO\n⚫ Após PRETO\n\n🔢 Independente de qualquer número.\n\n🔎 O sistema testa cada posição possível como ponto inicial dos caminhos do SURF 🔴 e SURF ⚫.",
        "",
        "🧬 CAMINHOS ÚNICOS",
        "",
        "Quando vários pontos iniciais chegam exatamente à mesma sequência real de rodadas, eles são agrupados como uma única ocorrência.",
        "",
        "🔁 Caminhos repetidos/convergentes não aumentam artificialmente a quantidade de Gales encontrados.",
        "",
        "🎯 Para diferenciar uma ocorrência da outra, o bot compara as rodadas reais do Gale: números, cores e horários.",
        "",
        "📌 Ao escolher um Gale, o bot mostra:",
        "📊 Registros brutos",
        "🧬 Caminhos únicos",
        "🔁 Caminhos convergentes",
        "",
        "👇 Depois aparecem somente os desenhos dos caminhos realmente diferentes.",
        "",
        "👇 Escolha o tipo de análise:",
    ])


def _controle_geral_surfe_markup_estrategias():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton("🧬 CAMINHOS ÚNICOS", callback_data="cg_menu_caminhos"))
    markup.add(telebot.types.InlineKeyboardButton("📊 SEQUÊNCIAS DE GALE", callback_data="cg_menu_sequencias"))
    markup.add(telebot.types.InlineKeyboardButton("💰 APOSTAS — GERAL", callback_data="cg_apostas_menu"))
    markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="voltar_painel_principal"))
    return markup


# ==============================================================================
# CONTROLE GERAL — APOSTAS (somente CAMINHOS ÚNICOS)
# ==============================================================================

def _cg_apostas_oportunidades(caminho_nome, gale_alvo):
    """Localiza ocorrências únicas que realmente atingiram o Gale escolhido.

    A assinatura usa as rodadas reais do G1 até o Gale-alvo. Assim, pontos de
    início convergentes não criam entradas duplicadas. A entrada começa sempre
    na rodada imediatamente seguinte ao Gale-alvo.
    """
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    if caminho_nome not in ("Vermelho", "Preto") or len(dados) < 3:
        return dados, []

    unicos = {}
    for indice_inicio in range(len(dados) - 2):
        gale_atual = 0
        indice_g1 = None
        for pos_relativa, rodada in enumerate(dados[indice_inicio + 1:], 1):
            indice_abs = indice_inicio + pos_relativa
            saiu = normalizar_cor_analise(rodada)
            jogaria = _investigacao_cor_jogada(caminho_nome, pos_relativa)
            if saiu == jogaria:
                gale_atual = 0
                indice_g1 = None
                continue
            gale_atual += 1
            if gale_atual == 1:
                indice_g1 = indice_abs
            if gale_atual == gale_alvo and indice_g1 is not None:
                if indice_abs + 1 >= len(dados):
                    break
                assinatura = _controle_geral_assinatura_trecho(dados, indice_g1, indice_abs)
                chave = (caminho_nome, assinatura)
                if chave not in unicos:
                    unicos[chave] = {
                        "caminho": caminho_nome,
                        "indice_inicio": indice_inicio,
                        "indice_g1": indice_g1,
                        "indice_gatilho": indice_abs,
                        "indice_entrada": indice_abs + 1,
                        "pos_entrada": pos_relativa + 1,
                    }
                break
    return dados, sorted(unicos.values(), key=lambda x: x["indice_gatilho"])

def _cg_apostas_resultado_surf(caminho_nome, gale_alvo, limite):
    """Após cada caminho único atingir o alvo, simula Direto -> G1... nas rodadas seguintes."""
    dados, oportunidades = _cg_apostas_oportunidades(caminho_nome, gale_alvo)
    contagem = {n: 0 for n in range(0, limite + 1)}
    loss = 0
    completas = 0
    for op in oportunidades:
        inicio = op["indice_entrada"]
        pos_base = op["pos_entrada"]
        terminou = False
        for nivel in range(0, limite + 1):
            idx = inicio + nivel
            if idx >= len(dados):
                break
            pos_rel = pos_base + nivel
            saiu = normalizar_cor_analise(dados[idx])
            jogaria = _investigacao_cor_jogada(caminho_nome, pos_rel)
            if saiu == jogaria:
                contagem[nivel] += 1
                completas += 1
                terminou = True
                break
        if not terminou and inicio + limite < len(dados):
            loss += 1
            completas += 1
    return {"oportunidades": len(oportunidades), "completas": completas, "contagem": contagem, "loss": loss}

def _cg_apostas_resultado_gatilho(caminho_nome, gale_alvo, limite):
    """Cada caminho único no alvo gera UMA entrada; perdas entre gatilhos formam a progressão."""
    dados, oportunidades = _cg_apostas_oportunidades(caminho_nome, gale_alvo)
    contagem = {n: 0 for n in range(0, limite + 1)}
    loss = 0
    nivel = 0
    completas = 0
    for op in oportunidades:
        idx = op["indice_entrada"]
        if idx >= len(dados):
            continue
        saiu = normalizar_cor_analise(dados[idx])
        jogaria = _investigacao_cor_jogada(caminho_nome, op["pos_entrada"])
        if saiu == jogaria:
            contagem[nivel] += 1
            completas += 1
            nivel = 0
        else:
            if nivel >= limite:
                loss += 1
                completas += 1
                nivel = 0
            else:
                nivel += 1
    return {"oportunidades": len(oportunidades), "completas": completas, "contagem": contagem, "loss": loss}

def _cg_apostas_menu_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🎯 GATILHO ÚNICO", callback_data="cg_apostas_estrategia:gatilho"))
    m.add(telebot.types.InlineKeyboardButton("🏄 SURF", callback_data="cg_apostas_estrategia:surf"))
    m.add(telebot.types.InlineKeyboardButton("🔎 CONCENTRAÇÃO DE LOSS", callback_data="cg_apostas_concentracao_loss"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="cg_apostas_fechar"))
    return m


def _cg_apostas_concentracao_estrategia_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🎯 GATILHO ÚNICO", callback_data="cg_apostas_concentracao_estrategia:gatilho"))
    m.add(telebot.types.InlineKeyboardButton("🏄 SURF", callback_data="cg_apostas_concentracao_estrategia:surf"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="cg_apostas_menu"))
    return m


def _cg_apostas_concentracao_markup(estrategia):
    """Primeiro escolhe o Gale de ativação principal."""
    m = telebot.types.InlineKeyboardMarkup(row_width=4)
    botoes = [
        telebot.types.InlineKeyboardButton(
            f"G{n}", callback_data=f"cg_conc_escolher_ativ:{estrategia}:{n}"
        )
        for n in range(1, 17)
    ]
    for i in range(0, len(botoes), 4):
        m.row(*botoes[i:i + 4])
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="cg_apostas_concentracao_loss"))
    return m


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_concentracao_loss")
def cg_apostas_concentracao_loss_callback(call):
    try:
        bot.answer_callback_query(call.id)
        texto = "\n".join([
            "🔎 CONCENTRAÇÃO DE LOSS",
            "━━━━━━━━━━━━━━━━━━", "",
            "📊 Escolha qual estratégia deseja comparar:", "",
            "🎯 GATILHO ÚNICO",
            "🏄 SURF", "",
            "📌 Cada estratégia será analisada separadamente,",
            "respeitando exatamente a matemática própria dela.",
        ])
        _cg_apostas_editar_balao(call, texto, _cg_apostas_concentracao_estrategia_markup())
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_apostas_concentracao_estrategia:"))
def cg_apostas_concentracao_estrategia_callback(call):
    try:
        estrategia = call.data.split(":", 1)[1]
        if estrategia not in ("gatilho", "surf"):
            return
        bot.answer_callback_query(call.id)
        nome = "🎯 GATILHO ÚNICO" if estrategia == "gatilho" else "🏄 SURF"
        texto = "\n".join([
            "🔎 CONCENTRAÇÃO DE LOSS",
            "━━━━━━━━━━━━━━━━━━", "",
            f"📌 ESTRATÉGIA: {nome}", "",
            "📊 COMO FUNCIONA", "",
            "Esta ferramenta compara diferentes configurações",
            "nas 2.000 rodadas mais recentes.", "",
            "🧬 Somente CAMINHOS ÚNICOS são considerados.", "",
            "🔥 Primeiro escolha o GALE DE ATIVAÇÃO principal.",
            "Ele é o gatilho que libera a entrada principal.", "",
            "🎯 Depois da ativação começa a operação:",
            "ENTRADA PRINCIPAL → G1 → G2 → G3...", "",
            "🛡️ Em seguida o bot compara os LIMITES DE GALES",
            "da operação. Por padrão, você pode comparar até G5",
            "ou digitar outro limite manualmente.", "",
            "📌 Para cada limite serão mostrados:", "",
            "🧬 Quantidade de operações",
            "🎯 Greens no Direto",
            "🔥 Greens em cada Gale",
            "❌ Quantidade de Loss",
            "📉 Taxa histórica de Loss",
            "🔗 Maior sequência de Loss consecutivos",
            "✅ Maior sequência de Greens consecutivos", "",
            "━━━━━━━━━━━━━━━━━━",
            "📌 Os resultados representam somente o",
            "comportamento observado no histórico analisado.", "",
            "👇 Escolha o GALE DE ATIVAÇÃO principal:",
        ])
        _cg_apostas_editar_balao(call, texto, _cg_apostas_concentracao_markup(estrategia))
    except Exception:
        traceback.print_exc()


def _cg_concentracao_limite_max_markup(estrategia, ativacao):
    m = telebot.types.InlineKeyboardMarkup(row_width=5)
    m.row(*[
        telebot.types.InlineKeyboardButton(
            f"G{n}", callback_data=f"cg_conc_maxlim:{estrategia}:{ativacao}:{n}"
        ) for n in range(1, 6)
    ])
    m.add(telebot.types.InlineKeyboardButton(
        "⌨️ DIGITAR OUTRO LIMITE", callback_data=f"cg_conc_maxlim_digitar:{estrategia}:{ativacao}"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR", callback_data=f"cg_apostas_concentracao_estrategia:{estrategia}"
    ))
    return m


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_conc_escolher_ativ:"))
def cg_concentracao_escolher_ativacao_callback(call):
    try:
        _, estrategia, ativacao = call.data.split(":")
        ativacao = int(ativacao)
        if estrategia not in ("gatilho", "surf") or ativacao not in range(1, 17):
            return
        bot.answer_callback_query(call.id)
        nome = "🎯 GATILHO ÚNICO" if estrategia == "gatilho" else "🏄 SURF"
        texto = "\n".join([
            "🔎 CONCENTRAÇÃO DE LOSS", "━━━━━━━━━━━━━━━━━━", "",
            f"📌 ESTRATÉGIA: {nome}",
            f"🔥 GALE DE ATIVAÇÃO: G{ativacao}", "",
            "🎯 O G{0} é o gatilho que libera a ENTRADA PRINCIPAL.".format(ativacao),
            "A partir dela começam os Gales da operação:", "",
            "🎯 DIRETO → 🔥 G1 → 🔥 G2 → 🔥 G3...", "",
            "🛡️ Escolha até qual LIMITE deseja comparar.",
            "Os botões rápidos vão até G5.",
            "Para outro limite, use DIGITAR OUTRO LIMITE.", "",
            "👇 Escolha o limite máximo da comparação:",
        ])
        _cg_apostas_editar_balao(call, texto, _cg_concentracao_limite_max_markup(estrategia, ativacao))
    except Exception:
        traceback.print_exc()


def _cg_concentracao_calcular(estrategia, ativacao, limite):
    """Reaproveita exatamente a matemática já usada em APOSTAS — GERAL."""
    func = _cg_apostas_resultado_gatilho if estrategia == "gatilho" else _cg_apostas_resultado_surf
    resultados = {c: func(c, ativacao, limite) for c in ("Vermelho", "Preto")}
    total_ops = sum(r["completas"] for r in resultados.values())
    total_loss = sum(r["loss"] for r in resultados.values())
    totais = {n: sum(r["contagem"][n] for r in resultados.values()) for n in range(limite + 1)}
    greens = sum(totais.values())

    todas = []
    for caminho in ("Vermelho", "Preto"):
        dados, ops = _cg_apostas_detalhes_caminho(caminho, ativacao, limite, estrategia)
        for op in ops:
            rodada = dados[op["indice_fim"]] if op["indice_fim"] < len(dados) else {}
            op = dict(op)
            op["ordem"] = _ordem_temporal(rodada)
            todas.append(op)
    todas.sort(key=lambda x: (x.get("ordem", 0), x.get("indice_fim", 0), x.get("caminho", "")))
    _, maior_green = _cg_apostas_distribuicao_sequencias(todas, "green")
    _, maior_loss = _cg_apostas_distribuicao_sequencias(todas, "loss")
    return {
        "ops": total_ops, "loss": total_loss, "greens": greens, "totais": totais,
        "taxa_loss": (total_loss / total_ops * 100) if total_ops else 0.0,
        "taxa_green": (greens / total_ops * 100) if total_ops else 0.0,
        "maior_green": maior_green, "maior_loss": maior_loss,
        "oportunidades": sum(r["oportunidades"] for r in resultados.values()),
    }


def _cg_concentracao_resultado_markup(estrategia, ativacao, max_limite):
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(
        "📊 DETALHAR UM LIMITE", callback_data=f"cg_conc_limites:{estrategia}:{max_limite}:{ativacao}"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "🛡️ TROCAR LIMITE", callback_data=f"cg_conc_escolher_ativ:{estrategia}:{ativacao}"
    ))
    m.add(telebot.types.InlineKeyboardButton(
        "🔥 TROCAR ATIVAÇÃO", callback_data=f"cg_apostas_concentracao_estrategia:{estrategia}"
    ))
    return m


def _cg_concentracao_mostrar_ativacao(call, estrategia, max_limite, ativacao):
    nome = "🎯 GATILHO ÚNICO" if estrategia == "gatilho" else "🏄 SURF"
    linhas = [
        "🔎 CONCENTRAÇÃO DE LOSS", "━━━━━━━━━━━━━━━━━━", "",
        f"📌 ESTRATÉGIA: {nome}",
        f"🔥 GALE DE ATIVAÇÃO: G{ativacao}",
        f"🔎 LIMITES COMPARADOS: G1 até G{max_limite}", "",
        "📊 COMPARAÇÃO DOS LIMITES", "",
    ]
    for limite in range(1, max_limite + 1):
        r = _cg_concentracao_calcular(estrategia, ativacao, limite)
        linhas += [
            f"🛡️ G{limite}  |  🧬 {r['ops']} operações",
            f"❌ {r['loss']} Loss — {r['taxa_loss']:.2f}%".replace(".", ","),
            f"🔗 Máx.: ✅ {r['maior_green']} Green | ❌ {r['maior_loss']} Loss", "",
        ]
    linhas += [
        "━━━━━━━━━━━━━━━━━━",
        "📌 A ativação permanece fixa. O que muda acima é somente o limite da operação.",
        "📌 Toque em DETALHAR UM LIMITE para ver Direto, Gales, Greens e Loss."
    ]
    _cg_apostas_editar_balao(call, "\n".join(linhas), _cg_concentracao_resultado_markup(estrategia, ativacao, max_limite))


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_conc_maxlim:"))
def cg_concentracao_maxlim_callback(call):
    try:
        _, estrategia, ativacao, max_limite = call.data.split(":")
        ativacao, max_limite = int(ativacao), int(max_limite)
        bot.answer_callback_query(call.id, "Calculando concentrações...")
        _cg_concentracao_mostrar_ativacao(call, estrategia, max_limite, ativacao)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, f"Erro: {type(erro).__name__}", show_alert=True)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_conc_maxlim_digitar:"))
def cg_concentracao_maxlim_digitar_callback(call):
    try:
        _, estrategia, ativacao = call.data.split(":")
        ativacao = int(ativacao)
        bot.answer_callback_query(call.id)
        cache = controle_geral_surfe_cache.setdefault(call.message.chat.id, {})
        cache["cg_conc_message_id"] = call.message.message_id
        cache["cg_conc_estrategia"] = estrategia
        cache["cg_conc_ativacao"] = ativacao
        msg = bot.send_message(
            call.message.chat.id,
            "⌨️ DIGITAR LIMITE — CONCENTRAÇÃO DE LOSS\n━━━━━━━━━━━━━━━━━━\n\n"
            "Envie somente o número do limite desejado.\n\n"
            "Exemplo: para comparar G1 até G8, envie 8."
        )
        bot.register_next_step_handler_by_chat_id(
            call.message.chat.id, _cg_concentracao_receber_limite_digitado, msg.message_id
        )
    except Exception:
        traceback.print_exc()


def _cg_concentracao_receber_limite_digitado(message, prompt_message_id=None):
    try:
        try:
            if prompt_message_id:
                bot.delete_message(message.chat.id, prompt_message_id)
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        valor = str(message.text or "").strip().upper().replace("G", "")
        if not valor.isdigit() or int(valor) < 1 or int(valor) > 100:
            bot.send_message(message.chat.id, "❌ Digite um número entre 1 e 100.")
            return
        max_limite = int(valor)
        cache = controle_geral_surfe_cache.setdefault(message.chat.id, {})
        estrategia = cache.get("cg_conc_estrategia")
        ativacao = cache.get("cg_conc_ativacao")
        message_id = cache.get("cg_conc_message_id")
        if estrategia not in ("gatilho", "surf") or not ativacao or not message_id:
            return

        class _FakeCall:
            pass
        fake = _FakeCall()
        fake.message = type("Msg", (), {"chat": message.chat, "message_id": message_id})()
        _cg_concentracao_mostrar_ativacao(fake, estrategia, max_limite, int(ativacao))
    except Exception:
        traceback.print_exc()


def _cg_concentracao_limites_markup(estrategia, max_limite, ativacao):
    m = telebot.types.InlineKeyboardMarkup(row_width=4)
    botoes = [
        telebot.types.InlineKeyboardButton(
            f"G{n}", callback_data=f"cg_conc_detalhe:{estrategia}:{max_limite}:{ativacao}:{n}"
        ) for n in range(1, max_limite + 1)
    ]
    for i in range(0, len(botoes), 4):
        m.row(*botoes[i:i + 4])
    m.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR", callback_data=f"cg_conc_maxlim:{estrategia}:{ativacao}:{max_limite}"
    ))
    return m


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_conc_limites:"))
def cg_concentracao_limites_callback(call):
    try:
        _, estrategia, max_limite, ativacao = call.data.split(":")
        bot.answer_callback_query(call.id)
        texto = "\n".join([
            "🔎 CONCENTRAÇÃO DE LOSS", "━━━━━━━━━━━━━━━━━━", "",
            f"🔥 GALE DE ATIVAÇÃO: G{ativacao}",
            f"🔎 LIMITES COMPARADOS: G1 até G{max_limite}", "",
            "👇 Escolha o LIMITE que deseja detalhar:"
        ])
        _cg_apostas_editar_balao(
            call, texto, _cg_concentracao_limites_markup(estrategia, int(max_limite), int(ativacao))
        )
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_conc_detalhe:"))
def cg_concentracao_detalhe_callback(call):
    try:
        _, estrategia, max_limite, ativacao, limite = call.data.split(":")
        ativacao, limite, max_limite = int(ativacao), int(limite), int(max_limite)
        bot.answer_callback_query(call.id, "Calculando detalhe...")
        r = _cg_concentracao_calcular(estrategia, ativacao, limite)
        nome = "🎯 GATILHO ÚNICO" if estrategia == "gatilho" else "🏄 SURF"
        linhas = [
            "🔎 CONCENTRAÇÃO — CAMINHOS ÚNICOS", "━━━━━━━━━━━━━━━━━━", "",
            f"📌 ESTRATÉGIA: {nome}",
            f"🔥 Gale de ativação: G{ativacao}",
            f"🛡️ Limite da operação: G{limite}",
            f"🧬 Operações: {r['ops']}", "",
            "📊 DISTRIBUIÇÃO DOS RESULTADOS", "",
            f"🎯 Direto: {r['totais'][0]}",
        ]
        for n in range(1, limite + 1):
            linhas.append(f"🔥 G{n}: {r['totais'][n]}")
        linhas += [
            f"❌ LOSS: {r['loss']}", "", "━━━━━━━━━━━━━━━━━━", "📈 RESULTADO", "",
            f"✅ Greens: {r['greens']}", f"❌ Loss: {r['loss']}",
            f"📈 Green: {r['taxa_green']:.2f}%".replace(".", ","),
            f"📉 Loss: {r['taxa_loss']:.2f}%".replace(".", ","), "",
            "🔗 CONSECUTIVOS", "",
            f"✅ Maior sequência de Greens: {r['maior_green']}",
            f"❌ Maior sequência de Loss: {r['maior_loss']}", "",
            "📌 Resultado histórico das 2.000 rodadas analisadas.",
        ]
        m = telebot.types.InlineKeyboardMarkup(row_width=1)
        m.add(telebot.types.InlineKeyboardButton(
            "⬅️ VOLTAR AOS LIMITES", callback_data=f"cg_conc_limites:{estrategia}:{max_limite}:{ativacao}"
        ))
        _cg_apostas_editar_balao(call, "\n".join(linhas), m)
    except Exception:
        traceback.print_exc()


def _cg_apostas_limite_markup(estrategia):
    m = telebot.types.InlineKeyboardMarkup(row_width=3)
    botoes = [
        telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"cg_apostas_limite:{n}")
        for n in range(1, 10)
    ]
    for i in range(0, len(botoes), 3):
        m.row(*botoes[i:i + 3])
    m.add(telebot.types.InlineKeyboardButton("⌨️ DIGITAR LIMITE", callback_data="cg_apostas_limite_digitar"))
    m.add(telebot.types.InlineKeyboardButton("🔝 MÁXIMO DO HISTÓRICO", callback_data="cg_apostas_limite_maximo"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data=f"cg_apostas_estrategia:{estrategia}"))
    return m


def _cg_apostas_maximo_historico():
    """Maior Gale realmente encontrado nos caminhos únicos do recorte atual."""
    maiores = []
    for caminho_nome in ("Vermelho", "Preto"):
        resultado = _controle_geral_surfe_analisar_estrategia(caminho_nome)
        if resultado and resultado.get("grupos"):
            maiores.extend(int(g) for g, grupos in resultado["grupos"].items() if grupos)
        elif resultado and resultado.get("distribuicao"):
            maiores.extend(int(g) for g, qtd in resultado["distribuicao"].items() if qtd)
    return max(maiores) if maiores else 1


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_fechar")
def cg_apostas_fechar_callback(call):
    try:
        bot.answer_callback_query(call.id)
        # A tela de Controle Geral continua logo abaixo; remove apenas o balão de APOSTAS.
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        traceback.print_exc()


def _cg_apostas_editar_balao(call, texto, reply_markup=None):
    """Navegação interna de APOSTAS no mesmo balão de texto."""
    return bot.edit_message_text(
        texto,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=reply_markup,
    )


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_menu")
def cg_apostas_menu_callback(call):
    try:
        bot.answer_callback_query(call.id)
        texto = "\n".join([
            "💰 APOSTAS — CONTROLE GERAL",
            "━━━━━━━━━━━━━━━━━━", "",
            "📊 SIMULAÇÃO DE ESTRATÉGIAS", "",
            "Analise como as estratégias teriam se comportado nas 2.000 rodadas mais recentes.", "",
            "🧬 CAMINHOS ÚNICOS",
            "Somente caminhos realmente diferentes são considerados na análise.", "",
            "📍 ORIGENS ANALISADAS",
            "⚪ Branco",
            "🔴 Vermelho",
            "⚫ Preto", "",
            "🎯 Escolha abaixo qual estratégia deseja analisar:",
        ])
        if getattr(call.message, "content_type", None) == "text":
            _cg_apostas_editar_balao(call, texto, _cg_apostas_menu_markup())
        else:
            bot.send_message(call.message.chat.id, texto, reply_markup=_cg_apostas_menu_markup())
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_apostas_estrategia:"))
def cg_apostas_estrategia_callback(call):
    try:
        bot.answer_callback_query(call.id)
        estrategia = call.data.split(":", 1)[1]
        if estrategia not in ("gatilho", "surf"):
            return
        cache = controle_geral_surfe_cache.setdefault(call.message.chat.id, {})
        cache["apostas_estrategia"] = estrategia
        nome = "🎯 GATILHO ÚNICO" if estrategia == "gatilho" else "🏄 SURF"
        texto = "\n".join([
            "💰 APOSTAS — CONTROLE GERAL",
            "━━━━━━━━━━━━━━━━━━", "",
            nome, "",
            "🔥 GALE DE ATIVAÇÃO", "",
            "Escolha o Gale que o caminho precisa atingir para liberar uma oportunidade.", "",
            "👀 Até atingir o Gale escolhido, o caminho permanece apenas em observação.", "",
            "🎯 Ao atingir o Gale, a entrada será realizada na oportunidade seguinte.", "",
            "👇 Escolha o Gale de ativação:",
        ])
        m = telebot.types.InlineKeyboardMarkup(row_width=4)
        bs = [telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"cg_apostas_alvo:{n}") for n in range(1, 17)]
        for i in range(0, len(bs), 4):
            m.row(*bs[i:i + 4])
        m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="cg_apostas_menu"))
        _cg_apostas_editar_balao(call, texto, m)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_apostas_alvo:"))
def cg_apostas_alvo_callback(call):
    try:
        bot.answer_callback_query(call.id)
        alvo = int(call.data.split(":", 1)[1])
        if alvo not in range(1, 17):
            return
        cache = controle_geral_surfe_cache.setdefault(call.message.chat.id, {})
        estrategia = cache.get("apostas_estrategia")
        if estrategia not in ("gatilho", "surf"):
            return cg_apostas_menu_callback(call)
        cache["apostas_alvo"] = alvo
        texto = "\n".join([
            "💰 APOSTAS — CONTROLE GERAL",
            "━━━━━━━━━━━━━━━━━━", "",
            "🛡️ LIMITE DE GALES", "",
            f"🔥 GALE DE ATIVAÇÃO: G{alvo}", "",
            "Defina até qual Gale a operação poderá continuar caso a entrada não acerte.", "",
            "❌ Se o limite escolhido for atingido sem Green, a operação será registrada como LOSS.", "",
            "👇 Escolha o limite:",
        ])
        _cg_apostas_editar_balao(call, texto, _cg_apostas_limite_markup(estrategia))
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_limite_digitar")
def cg_apostas_limite_digitar_callback(call):
    try:
        bot.answer_callback_query(call.id)
        cache = controle_geral_surfe_cache.setdefault(call.message.chat.id, {})
        cache["apostas_message_id"] = call.message.message_id
        msg = bot.send_message(
            call.message.chat.id,
            "⌨️ DIGITAR LIMITE DE GALES\n━━━━━━━━━━━━━━━━━━\n\n"
            "Envie somente o número do Gale desejado.\n\n"
            "Exemplo: para usar G12, envie 12."
        )
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, _cg_apostas_receber_limite_digitado, msg.message_id)
    except Exception:
        traceback.print_exc()


def _cg_apostas_receber_limite_digitado(message, prompt_message_id=None):
    try:
        try:
            if prompt_message_id:
                bot.delete_message(message.chat.id, prompt_message_id)
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        valor = str(message.text or "").strip().upper().replace("G", "")
        if not valor.isdigit() or int(valor) < 1 or int(valor) > 100:
            bot.send_message(message.chat.id, "❌ Digite um número entre 1 e 100.")
            return
        cache = controle_geral_surfe_cache.setdefault(message.chat.id, {})
        _cg_apostas_enviar_resultado(message.chat.id, int(valor), cache.get("apostas_message_id"))
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_limite_maximo")
def cg_apostas_limite_maximo_callback(call):
    try:
        bot.answer_callback_query(call.id)
        limite = _cg_apostas_maximo_historico()
        _cg_apostas_enviar_resultado(call.message.chat.id, limite, call.message.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao localizar o maior Gale: {type(erro).__name__}: {str(erro)[:180]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_apostas_limite:"))
def cg_apostas_limite_callback(call):
    try:
        bot.answer_callback_query(call.id)
        limite = int(call.data.split(":", 1)[1])
        _cg_apostas_enviar_resultado(call.message.chat.id, limite, call.message.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro em APOSTAS — GERAL: {type(erro).__name__}: {str(erro)[:220]}")
        except Exception:
            pass


def _cg_apostas_detalhes_caminho(caminho_nome, gale_alvo, limite, estrategia):
    """Retorna operações completas com os passos reais usados no resultado."""
    dados, oportunidades = _cg_apostas_oportunidades(caminho_nome, gale_alvo)
    operacoes = []

    if estrategia == "gatilho":
        nivel = 0
        passos = []
        for op in oportunidades:
            idx = op["indice_entrada"]
            if idx >= len(dados):
                continue
            rodada = dados[idx]
            saiu = normalizar_cor_analise(rodada)
            jogaria = _investigacao_cor_jogada(caminho_nome, op["pos_entrada"])
            acertou = saiu == jogaria
            passos.append({
                "nivel": nivel,
                "indice": idx,
                "numero": rodada.get("numero"),
                "cor": saiu,
                "acertou": acertou,
                "indice_gatilho": op["indice_gatilho"],
            })
            if acertou:
                operacoes.append({
                    "resultado": "green", "nivel": nivel, "passos": list(passos),
                    "indice_fim": idx, "caminho": caminho_nome,
                })
                nivel = 0
                passos = []
            elif nivel >= limite:
                operacoes.append({
                    "resultado": "loss", "nivel": limite, "passos": list(passos),
                    "indice_fim": idx, "caminho": caminho_nome,
                })
                nivel = 0
                passos = []
            else:
                nivel += 1
    else:
        for op in oportunidades:
            inicio = op["indice_entrada"]
            pos_base = op["pos_entrada"]
            passos = []
            terminou = False
            for nivel in range(0, limite + 1):
                idx = inicio + nivel
                if idx >= len(dados):
                    break
                rodada = dados[idx]
                saiu = normalizar_cor_analise(rodada)
                jogaria = _investigacao_cor_jogada(caminho_nome, pos_base + nivel)
                acertou = saiu == jogaria
                passos.append({
                    "nivel": nivel, "indice": idx, "numero": rodada.get("numero"),
                    "cor": saiu, "acertou": acertou,
                    "indice_gatilho": op["indice_gatilho"],
                })
                if acertou:
                    operacoes.append({
                        "resultado": "green", "nivel": nivel, "passos": list(passos),
                        "indice_fim": idx, "caminho": caminho_nome,
                    })
                    terminou = True
                    break
            if not terminou and inicio + limite < len(dados):
                operacoes.append({
                    "resultado": "loss", "nivel": limite, "passos": list(passos),
                    "indice_fim": inicio + limite, "caminho": caminho_nome,
                })
    return dados, operacoes


def _cg_apostas_operacoes_atuais(chat_id):
    cache = controle_geral_surfe_cache.setdefault(chat_id, {})
    estrategia = cache.get("apostas_estrategia")
    alvo = int(cache.get("apostas_alvo") or 0)
    limite = int(cache.get("apostas_limite") or 0)
    if estrategia not in ("gatilho", "surf") or alvo < 1 or limite < 1:
        return [], estrategia, alvo, limite

    todas = []
    for caminho in ("Vermelho", "Preto"):
        dados, ops = _cg_apostas_detalhes_caminho(caminho, alvo, limite, estrategia)
        for op in ops:
            rodada = dados[op["indice_fim"]] if op["indice_fim"] < len(dados) else {}
            op["ordem"] = _ordem_temporal(rodada)
            todas.append(op)
    todas.sort(key=lambda x: (x.get("ordem", 0), x.get("indice_fim", 0), x.get("caminho", "")))
    return todas, estrategia, alvo, limite


def _cg_apostas_distribuicao_sequencias(operacoes, resultado):
    dist = {}
    atual = 0
    maior = 0
    for op in operacoes + [{"resultado": None}]:
        if op.get("resultado") == resultado:
            atual += 1
            maior = max(maior, atual)
        elif atual:
            dist[atual] = dist.get(atual, 0) + 1
            atual = 0
    return dist, maior


def _cg_apostas_cor_visual(cor):
    return {"Vermelho": "🔴", "Preto": "⚫", "Branco": "⚪"}.get(cor, "⚪")


def _cg_apostas_desenho_operacao(op, alvo, numero_exemplo=None):
    linhas = []
    if numero_exemplo is not None:
        linhas.append(f"🧬 EXEMPLO {numero_exemplo}")
    caminho = op.get("caminho")
    linhas.append(f"{'🔴' if caminho == 'Vermelho' else '⚫'} SURF 2 {str(caminho).upper()}S")
    for i, passo in enumerate(op.get("passos", []), 1):
        numero = passo.get("numero")
        cor = _cg_apostas_cor_visual(passo.get("cor"))
        final = i == len(op.get("passos", []))
        if final and op.get("resultado") == "green":
            status = "✅ GREEN"
        elif final and op.get("resultado") == "loss":
            status = "❌ LOSS"
        else:
            status = "❌"
        linhas.append(f"G{alvo}  [ {i} ]  {numero} {cor}  {status}")
    return "\n".join(linhas)


def _cg_apostas_investigacao_markup(tipo):
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🧬 VER CAMINHOS", callback_data=f"cg_apostas_caminhos:{tipo}:0"))
    if tipo == "loss":
        m.add(telebot.types.InlineKeyboardButton("🎯 TESTAR GATILHO DE LOSS", callback_data="cg_apostas_gatilho_loss_menu"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR AO RESULTADO", callback_data="cg_apostas_resultado_atual"))
    return m


def _cg_apostas_gatilho_loss_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("❌ 1 LOSS", callback_data="cg_apostas_gatilho_loss:1"))
    m.add(telebot.types.InlineKeyboardButton("❌❌ 2 LOSS", callback_data="cg_apostas_gatilho_loss:2"))
    m.add(telebot.types.InlineKeyboardButton("❌❌❌ 3 LOSS", callback_data="cg_apostas_gatilho_loss:3"))
    m.add(telebot.types.InlineKeyboardButton("⌨️ DIGITAR", callback_data="cg_apostas_gatilho_loss_digitar"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="cg_apostas_analisar_loss"))
    return m


def _cg_apostas_gatilho_loss_sinais(ops, quantidade):
    quantidade = max(1, int(quantidade))
    sinais = []
    for i in range(quantidade - 1, len(ops) - 1):
        gatilho = ops[i - quantidade + 1:i + 1]
        if all(op.get("resultado") == "loss" for op in gatilho):
            sinais.append({"gatilho": gatilho, "entrada": ops[i + 1]})
    return sinais


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_gatilho_loss_menu")
def cg_apostas_gatilho_loss_menu_callback(call):
    try:
        bot.answer_callback_query(call.id)
        texto = "\n".join([
            "🎯 GATILHO DE LOSS", "━━━━━━━━━━━━━━━━━━", "",
            "📌 COMO FUNCIONA", "",
            "Esta análise verifica o que teria acontecido se uma entrada fosse feita somente após uma sequência de LOSS consecutivos.", "",
            "❌ Os LOSS anteriores funcionam apenas como gatilho.",
            "🎯 A entrada começa na operação seguinte.", "",
            "Exemplo:", "",
            "❌ LOSS", "❌ LOSS", "━━━━━━━━━━━━━━━━━━",
            "🎯 2 LOSS CONFIRMADOS", "",
            "➡️ A próxima operação passa a ser considerada como entrada.", "",
            "📊 O resultado mostrará quantos sinais foram encontrados, quantos terminaram em GREEN ou novo LOSS e em qual Gale os Greens bateram.", "",
            "👇 Escolha quantos LOSS consecutivos deseja usar como gatilho:",
        ])
        _cg_apostas_editar_balao(call, texto, _cg_apostas_gatilho_loss_markup())
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_apostas_gatilho_loss:") and call.data.split(":")[-1].isdigit())
def cg_apostas_gatilho_loss_resultado_callback(call):
    try:
        bot.answer_callback_query(call.id, "Calculando...")
        quantidade = max(1, int(call.data.split(":")[-1]))
        _cg_apostas_mostrar_gatilho_loss(call.message.chat.id, quantidade, call.message.message_id)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro no gatilho de Loss: {type(erro).__name__}: {str(erro)[:180]}")


def _cg_apostas_mostrar_gatilho_loss(chat_id, quantidade, message_id):
    ops, estrategia, alvo, limite = _cg_apostas_operacoes_atuais(chat_id)
    sinais = _cg_apostas_gatilho_loss_sinais(ops, quantidade)
    greens = [s for s in sinais if s["entrada"].get("resultado") == "green"]
    losses = [s for s in sinais if s["entrada"].get("resultado") == "loss"]
    por_gale = {n: 0 for n in range(limite + 1)}
    for sinal in greens:
        nivel = int(sinal["entrada"].get("nivel", 0))
        if nivel in por_gale:
            por_gale[nivel] += 1
    total = len(sinais)
    cache = controle_geral_surfe_cache.setdefault(chat_id, {})
    cache["apostas_gatilho_loss_qtd"] = quantidade
    linhas = [
        "🎯 RESULTADO — GATILHO DE LOSS", "━━━━━━━━━━━━━━━━━━", "",
        f"🎯 Estratégia: {'GATILHO ÚNICO' if estrategia == 'gatilho' else 'SURF'}",
        f"🔥 Gale de ativação: G{alvo}", f"🛡️ Limite: G{limite}",
        f"❌ Gatilho: {quantidade} LOSS consecutivo{'s' if quantidade != 1 else ''}", "",
        "📌 COMO LER", "",
        f"Sempre que aconteceram {quantidade} LOSS consecutivo{'s' if quantidade != 1 else ''}, o bot analisou a operação imediatamente seguinte.", "",
        "Os LOSS usados para formar o gatilho não contam como entrada.", "",
        "━━━━━━━━━━━━━━━━━━", "📊 RESULTADO", "",
        f"🎯 Sinais encontrados: {total}", "",
        f"✅ GREEN: {len(greens)} — {((len(greens)/total*100) if total else 0):.2f}%".replace('.', ','),
        f"❌ NOVO LOSS: {len(losses)} — {((len(losses)/total*100) if total else 0):.2f}%".replace('.', ','), "",
        "━━━━━━━━━━━━━━━━━━", "📍 ONDE OS GREENS BATERAM", "",
        f"🎯 Direto: {por_gale[0]}",
    ]
    for n in range(1, limite + 1):
        linhas.append(f"🔥 G{n}: {por_gale[n]}")
    linhas += ["", f"❌ LOSS: {len(losses)}"]
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🧬 VER CAMINHOS", callback_data="cg_apostas_gatilho_loss_caminhos:0"))
    m.add(telebot.types.InlineKeyboardButton("🔄 TESTAR OUTRO GATILHO", callback_data="cg_apostas_gatilho_loss_menu"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="cg_apostas_analisar_loss"))
    try:
        bot.edit_message_text("\n".join(linhas), chat_id, message_id, reply_markup=m)
    except Exception:
        try:
            bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption="\n".join(linhas), reply_markup=m)
        except Exception:
            bot.send_message(chat_id, "\n".join(linhas), reply_markup=m)


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_gatilho_loss_digitar")
def cg_apostas_gatilho_loss_digitar_callback(call):
    try:
        bot.answer_callback_query(call.id)
        cache = controle_geral_surfe_cache.setdefault(call.message.chat.id, {})
        cache["apostas_message_id"] = call.message.message_id
        msg = bot.send_message(call.message.chat.id, "⌨️ DIGITAR GATILHO DE LOSS\n━━━━━━━━━━━━━━━━━━\n\nEnvie somente a quantidade de LOSS consecutivos.\n\nExemplo: para testar após 4 LOSS, envie 4.")
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, _cg_apostas_receber_gatilho_loss, msg.message_id)
    except Exception:
        traceback.print_exc()


def _cg_apostas_receber_gatilho_loss(message, prompt_message_id=None):
    try:
        try:
            if prompt_message_id:
                bot.delete_message(message.chat.id, prompt_message_id)
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        valor = str(message.text or "").strip()
        if not valor.isdigit() or int(valor) < 1 or int(valor) > 100:
            bot.send_message(message.chat.id, "❌ Digite um número entre 1 e 100.")
            return
        cache = controle_geral_surfe_cache.setdefault(message.chat.id, {})
        message_id = cache.get("apostas_message_id")
        if message_id:
            _cg_apostas_mostrar_gatilho_loss(message.chat.id, int(valor), message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_apostas_gatilho_loss_caminhos:"))
def cg_apostas_gatilho_loss_caminhos_callback(call):
    try:
        bot.answer_callback_query(call.id)
        pagina = max(0, int(call.data.split(":")[-1]))
        cache = controle_geral_surfe_cache.setdefault(call.message.chat.id, {})
        quantidade = max(1, int(cache.get("apostas_gatilho_loss_qtd") or 1))
        ops, estrategia, alvo, limite = _cg_apostas_operacoes_atuais(call.message.chat.id)
        sinais = _cg_apostas_gatilho_loss_sinais(ops, quantidade)
        por_pagina = 3
        total_paginas = max(1, (len(sinais) + por_pagina - 1) // por_pagina)
        pagina = min(pagina, total_paginas - 1)
        ini = pagina * por_pagina
        bloco = sinais[ini:ini + por_pagina]
        linhas = ["🧬 CAMINHOS — GATILHO DE LOSS", "━━━━━━━━━━━━━━━━━━", "", f"❌ Gatilho: {quantidade} LOSS consecutivo{'s' if quantidade != 1 else ''}", ""]
        for pos, sinal in enumerate(bloco, ini + 1):
            linhas += [f"🎯 SINAL {pos}", "━━━━━━━━━━━━━━━━━━"]
            for n in range(1, quantidade + 1):
                linhas.append(f"❌ LOSS {n}")
            linhas += ["", "🔥 GATILHO CONFIRMADO", ""]
            linhas.append(_cg_apostas_desenho_operacao(sinal["entrada"], alvo))
            linhas += ["", "━━━━━━━━━━━━━━━━━━", ""]
        if not bloco:
            linhas.append("Nenhum sinal encontrado.")
        linhas.append(f"📄 Página {pagina + 1}/{total_paginas}")
        m = telebot.types.InlineKeyboardMarkup(row_width=2)
        nav = []
        if pagina > 0:
            nav.append(telebot.types.InlineKeyboardButton("◀️ ANTERIOR", callback_data=f"cg_apostas_gatilho_loss_caminhos:{pagina-1}"))
        if pagina + 1 < total_paginas:
            nav.append(telebot.types.InlineKeyboardButton("PRÓXIMA ▶️", callback_data=f"cg_apostas_gatilho_loss_caminhos:{pagina+1}"))
        if nav:
            m.row(*nav)
        m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR AO RESULTADO", callback_data=f"cg_apostas_gatilho_loss:{quantidade}"))
        _cg_apostas_editar_balao(call, "\n".join(linhas), m)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao mostrar gatilho de Loss: {type(erro).__name__}: {str(erro)[:180]}")


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_resultado_atual")
def cg_apostas_resultado_atual_callback(call):
    try:
        bot.answer_callback_query(call.id)
        cache = controle_geral_surfe_cache.setdefault(call.message.chat.id, {})
        limite = int(cache.get("apostas_limite") or 0)
        if limite:
            _cg_apostas_enviar_resultado(call.message.chat.id, limite, call.message.message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_analisar_loss")
def cg_apostas_analisar_loss_callback(call):
    try:
        bot.answer_callback_query(call.id, "Analisando Loss...")
        ops, estrategia, alvo, limite = _cg_apostas_operacoes_atuais(call.message.chat.id)
        losses = [i for i, op in enumerate(ops) if op.get("resultado") == "loss"]
        seguintes = [ops[i + 1] for i in losses if i + 1 < len(ops)]
        green_seg = sum(1 for op in seguintes if op.get("resultado") == "green")
        loss_seg = sum(1 for op in seguintes if op.get("resultado") == "loss")
        base = len(seguintes)
        dist_loss, maior_loss = _cg_apostas_distribuicao_sequencias(ops, "loss")
        por_gale = {n: 0 for n in range(limite + 1)}
        for op in seguintes:
            if op.get("resultado") == "green":
                por_gale[int(op.get("nivel", 0))] += 1
        linhas = [
            "❌ ANÁLISE APÓS LOSS", "━━━━━━━━━━━━━━━━━━", "",
            f"🎯 Estratégia: {'GATILHO ÚNICO' if estrategia == 'gatilho' else 'SURF'}",
            f"🔥 Gale de ativação: G{alvo}", f"🛡️ Limite: G{limite}", "",
            "📌 COMO LER ESTA ANÁLISE", "",
            "Esta análise verifica o que aconteceu depois de cada LOSS encontrado.", "",
            "➡️ Primeiro, mostra se a operação seguinte terminou em ✅ GREEN ou ❌ outro LOSS.", "",
            "🔥 Depois, mostra em qual Gale os Greens bateram.", "",
            "🔗 Por último, mostra quantos LOSS aconteceram consecutivamente.", "",
            "━━━━━━━━━━━━━━━━━━", f"❌ LOSS ENCONTRADOS: {len(losses)}", "", "━━━━━━━━━━━━━━━━━━",
            "➡️ PRÓXIMA OPERAÇÃO APÓS O LOSS", "",
            f"Dos {len(losses)} LOSS encontrados:", "",
            f"✅ Virou GREEN: {green_seg} — {((green_seg/base*100) if base else 0):.2f}%".replace('.', ','),
            f"❌ Virou outro LOSS: {loss_seg} — {((loss_seg/base*100) if base else 0):.2f}%".replace('.', ','),
            "", f"📍 ONDE OS {green_seg} GREENS BATERAM", "",
            f"🎯 Direto: {por_gale[0]}",
        ]
        for n in range(1, limite + 1):
            linhas.append(f"🔥 G{n}: {por_gale[n]}")
        linhas += ["", "━━━━━━━━━━━━━━━━━━", "🔗 LOSS CONSECUTIVOS", ""]
        if dist_loss:
            for tam in sorted(dist_loss):
                linhas.append(f"{'❌' * min(tam, 5)} {tam} LOSS consecutivo{'s' if tam != 1 else ''}: {dist_loss[tam]} vez{'es' if dist_loss[tam] != 1 else ''}")
            linhas += ["", f"🔥 Maior sequência: {maior_loss} LOSS"]
        else:
            linhas.append("Nenhuma sequência de LOSS encontrada.")
        _cg_apostas_editar_balao(call, "\n".join(linhas), _cg_apostas_investigacao_markup("loss"))
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro na análise após Loss: {type(erro).__name__}: {str(erro)[:180]}")


@bot.callback_query_handler(func=lambda call: call.data == "cg_apostas_analisar_green")
def cg_apostas_analisar_green_callback(call):
    try:
        bot.answer_callback_query(call.id, "Analisando Greens...")
        ops, estrategia, alvo, limite = _cg_apostas_operacoes_atuais(call.message.chat.id)
        greens = [op for op in ops if op.get("resultado") == "green"]
        dist, maior = _cg_apostas_distribuicao_sequencias(ops, "green")
        total = len(ops)
        linhas = [
            "✅ ANÁLISE DE GREENS", "━━━━━━━━━━━━━━━━━━", "",
            f"🎯 Estratégia: {'GATILHO ÚNICO' if estrategia == 'gatilho' else 'SURF'}",
            f"🔥 Gale de ativação: G{alvo}", f"🛡️ Limite: G{limite}", "",
            "📌 COMO LER ESTA ANÁLISE", "",
            "Esta análise verifica como os GREENS se distribuíram nas operações do resultado.", "",
            "📊 Primeiro, mostra a quantidade total de Greens e a taxa de acerto.", "",
            "🔗 Depois, mostra quantos Greens aconteceram consecutivamente.", "",
            "🏆 Por último, mostra a maior sequência de Greens encontrada.", "",
            "━━━━━━━━━━━━━━━━━━",
            f"✅ GREENS: {len(greens)}", f"🎯 OPERAÇÕES: {total}",
            f"📈 TAXA DE GREEN: {((len(greens)/total*100) if total else 0):.2f}%".replace('.', ','),
            "", "━━━━━━━━━━━━━━━━━━", "🔗 GREENS CONSECUTIVOS", "",
        ]
        if dist:
            for tam in sorted(dist):
                linhas.append(f"✅ {tam} Green{'s' if tam != 1 else ''} seguido{'s' if tam != 1 else ''}: {dist[tam]} vez{'es' if dist[tam] != 1 else ''}")
            linhas += ["", "🏆 MAIOR SEQUÊNCIA", f"✅ {maior} GREENS CONSECUTIVOS"]
        else:
            linhas.append("Nenhuma sequência de Green encontrada.")
        _cg_apostas_editar_balao(call, "\n".join(linhas), _cg_apostas_investigacao_markup("green"))
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro na análise de Greens: {type(erro).__name__}: {str(erro)[:180]}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_apostas_caminhos:"))
def cg_apostas_caminhos_callback(call):
    try:
        bot.answer_callback_query(call.id)
        _, tipo, pagina_txt = call.data.split(":", 2)
        pagina = max(0, int(pagina_txt))
        ops, estrategia, alvo, limite = _cg_apostas_operacoes_atuais(call.message.chat.id)
        if tipo == "loss":
            selecionadas = [op for op in ops if op.get("resultado") == "loss"]
            titulo = "❌ CAMINHOS DE LOSS"
        else:
            selecionadas = [op for op in ops if op.get("resultado") == "green"]
            titulo = "✅ CAMINHOS DE GREEN"
        por_pagina = 5
        total_paginas = max(1, (len(selecionadas) + por_pagina - 1) // por_pagina)
        pagina = min(pagina, total_paginas - 1)
        ini = pagina * por_pagina
        bloco = selecionadas[ini:ini + por_pagina]
        linhas = [titulo, "━━━━━━━━━━━━━━━━━━", "", f"🔥 Gale de ativação: G{alvo}", f"🛡️ Limite: G{limite}", ""]
        for pos, op in enumerate(bloco, ini + 1):
            linhas.append(_cg_apostas_desenho_operacao(op, alvo, pos))
            linhas.append("")
            linhas.append("━━━━━━━━━━━━━━━━━━")
            linhas.append("")
        if not bloco:
            linhas.append("Nenhuma ocorrência encontrada.")
        linhas.append(f"📄 Página {pagina + 1}/{total_paginas}")
        m = telebot.types.InlineKeyboardMarkup(row_width=2)
        nav = []
        if pagina > 0:
            nav.append(telebot.types.InlineKeyboardButton("◀️ ANTERIOR", callback_data=f"cg_apostas_caminhos:{tipo}:{pagina-1}"))
        if pagina + 1 < total_paginas:
            nav.append(telebot.types.InlineKeyboardButton("PRÓXIMA ▶️", callback_data=f"cg_apostas_caminhos:{tipo}:{pagina+1}"))
        if nav:
            m.row(*nav)
        m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR À ANÁLISE", callback_data="cg_apostas_analisar_loss" if tipo == "loss" else "cg_apostas_analisar_green"))
        _cg_apostas_editar_balao(call, "\n".join(linhas), m)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao mostrar caminhos: {type(erro).__name__}: {str(erro)[:180]}")


def _cg_apostas_enviar_resultado(chat_id, limite, message_id=None):
    cache = controle_geral_surfe_cache.setdefault(chat_id, {})
    estrategia = cache.get("apostas_estrategia")
    alvo = cache.get("apostas_alvo")
    if estrategia not in ("gatilho", "surf") or not alvo:
        return

    limite = max(1, int(limite))
    cache["apostas_limite"] = limite
    func = _cg_apostas_resultado_gatilho if estrategia == "gatilho" else _cg_apostas_resultado_surf
    resultados = {c: func(c, int(alvo), limite) for c in ("Vermelho", "Preto")}
    total_ops = sum(r["completas"] for r in resultados.values())
    total_loss = sum(r["loss"] for r in resultados.values())
    totais = {n: sum(r["contagem"][n] for r in resultados.values()) for n in range(limite + 1)}
    greens = sum(totais.values())
    taxa = (greens / total_ops * 100) if total_ops else 0.0
    taxa_loss = (total_loss / total_ops * 100) if total_ops else 0.0
    nome = "🎯 GATILHO ÚNICO" if estrategia == "gatilho" else "🏄 SURF"

    linhas = [
        "📊 RESULTADO — APOSTAS GERAL",
        "━━━━━━━━━━━━━━━━━━", "",
        "🎯 ESTRATÉGIA",
        nome, "",
        "🧬 Caminhos: SOMENTE ÚNICOS",
        f"🔥 Gale de ativação: G{alvo}",
        f"🛡️ Limite de Gales: G{limite}", "",
        "━━━━━━━━━━━━━━━━━━",
        "🔎 ANÁLISE", "",
        f"🧬 Oportunidades únicas: {sum(r['oportunidades'] for r in resultados.values())}",
        f"🎯 Operações completas: {total_ops}", "",
        "━━━━━━━━━━━━━━━━━━",
        "📊 RESULTADO GERAL", "",
        f"🎯 DIRETO: {totais[0]}",
    ]
    for n in range(1, limite + 1):
        linhas.append(f"🔥 G{n}: {totais[n]}")
    linhas += [
        f"❌ LOSS: {total_loss}", "",
        f"✅ GREENS: {greens}",
        f"❌ LOSS: {total_loss}",
        f"📈 TAXA DE GREEN: {taxa:.2f}%".replace(".", ","),
        f"📉 TAXA DE LOSS: {taxa_loss:.2f}%".replace(".", ","), "",
        "━━━━━━━━━━━━━━━━━━",
        "📍 RESULTADO POR SURF",
    ]
    for c, emoji in (("Vermelho", "🔴"), ("Preto", "⚫")):
        r = resultados[c]
        g = sum(r["contagem"].values())
        t = r["completas"]
        tx = (g / t * 100) if t else 0.0
        linhas += [
            "",
            f"{emoji} SURF 2 {c.upper()}S",
            f"🎯 Operações: {t}",
            f"✅ Greens: {g}",
            f"❌ Loss: {r['loss']}",
            f"📈 Taxa de Green: {tx:.2f}%".replace(".", ","),
        ]
    linhas += [
        "",
        "━━━━━━━━━━━━━━━━━━",
        "⚠️ Resultado baseado no histórico analisado.",
        "Não representa garantia de resultados futuros.",
    ]

    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("❌ ANALISAR LOSS", callback_data="cg_apostas_analisar_loss"))
    m.add(telebot.types.InlineKeyboardButton("✅ ANALISAR GREENS", callback_data="cg_apostas_analisar_green"))
    m.add(telebot.types.InlineKeyboardButton("🔥 TESTAR OUTRO GALE", callback_data=f"cg_apostas_estrategia:{estrategia}"))
    m.add(telebot.types.InlineKeyboardButton("🔄 TROCAR ESTRATÉGIA", callback_data="cg_apostas_menu"))
    m.add(telebot.types.InlineKeyboardButton("🐺 CONTROLE GERAL", callback_data="controle_geral_surfe"))
    texto_resultado = "\n".join(linhas)
    if message_id:
        bot.edit_message_text(texto_resultado, chat_id=chat_id, message_id=message_id, reply_markup=m)
    else:
        bot.send_message(chat_id, texto_resultado, reply_markup=m)

def _controle_geral_surfe_enviar_distribuicao(chat_id, caminho_nome):
    resultado = _controle_geral_surfe_analisar_estrategia(caminho_nome)
    if not resultado or not resultado.get("distribuicao"):
        bot.send_message(chat_id, "❌ Não encontrei Gales suficientes para montar esta análise.")
        return

    cache_chat = controle_geral_surfe_cache.setdefault(chat_id, {})
    cache_chat[caminho_nome] = resultado
    emoji = "🔴" if caminho_nome == "Vermelho" else "⚫"
    nome = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"

    linhas = [
        f"🧬 CAMINHOS ÚNICOS — {emoji} {nome}",
        "",
        f"📚 Rodadas analisadas: {resultado['total_rodadas']:,}".replace(",", "."),
        f"📍 Pontos de início testados: {resultado['total_pontos']:,}".replace(",", "."),
        "",
        "📌 Os valores abaixo já separam ocorrências reais de caminhos que apenas convergiram para a mesma sequência.",
        "",
    ]

    gales_ordenados = sorted(resultado["resumo"])
    largura_gale = max(len(str(g)) for g in gales_ordenados)
    largura_unico = max(len(str(resultado["resumo"][g]["unicos"])) for g in gales_ordenados)
    largura_bruto = max(len(str(resultado["resumo"][g]["brutos"])) for g in gales_ordenados)

    # U+2007 = espaço numérico: ocupa a mesma largura visual de um algarismo.
    # Assim o espaço fica ANTES do número e as colunas terminam no mesmo ponto.
    ESPACO_NUMERICO = "\u2007"

    for gale in gales_ordenados:
        info = resultado["resumo"][gale]

        gale_str = str(gale)
        unico_str = str(info["unicos"])
        bruto_str = str(info["brutos"])

        gale_txt = (ESPACO_NUMERICO * (largura_gale - len(gale_str))) + gale_str
        unico_txt = (ESPACO_NUMERICO * (largura_unico - len(unico_str))) + unico_str
        bruto_txt = bruto_str + (ESPACO_NUMERICO * (largura_bruto - len(bruto_str)))

        linhas.append(
            f"🔥 G{gale_txt} — 🧬 {unico_txt} único(s) • 📊 {bruto_txt} bruto(s)"
        )

    linhas += ["", "👇 Escolha um Gale para ver os caminhos únicos:"]

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    botoes = []
    for gale in sorted(resultado["resumo"]):
        info = resultado["resumo"][gale]
        botoes.append(telebot.types.InlineKeyboardButton(
            f"🔥 G{gale} — 🧬 {info['unicos']}",
            callback_data=f"cg_surfe_gale:{caminho_nome}:{gale}:0"
        ))
    for pos in range(0, len(botoes), 2):
        markup.row(*botoes[pos:pos + 2])

    markup.add(telebot.types.InlineKeyboardButton(
        "⬆️ 📖 ENTENDER A ANÁLISE ⬆️", callback_data=f"cg_surfe_entender:{caminho_nome}"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "🔄 TROCAR ESTRATÉGIA", callback_data="cg_menu_caminhos"
    ))

    bot.send_message(chat_id, "\n".join(linhas), reply_markup=markup)



def _controle_geral_surfe_sequencias(caminho_nome):
    """Conta todas as sequências (bruto) e também as ocorrências reais únicas."""
    if caminho_nome not in ("Vermelho", "Preto"):
        return None
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    distribuicao = {}
    assinaturas_por_gale = {}
    total_sequencias = 0
    for indice_inicio in range(max(0, len(dados) - 1)):
        gale_atual = 0
        indice_g1 = None
        for pos_relativa, rodada in enumerate(dados[indice_inicio + 1:], 1):
            indice_abs = indice_inicio + pos_relativa
            saiu = normalizar_cor_analise(rodada)
            bloco = ((pos_relativa - 1) // 2) % 2
            if caminho_nome == "Vermelho":
                jogaria = "Vermelho" if bloco == 0 else "Preto"
            else:
                jogaria = "Preto" if bloco == 0 else "Vermelho"
            if saiu == jogaria:
                if gale_atual > 0:
                    distribuicao[gale_atual] = distribuicao.get(gale_atual, 0) + 1
                    total_sequencias += 1
                    assinatura = _controle_geral_assinatura_trecho(dados, indice_g1, indice_abs - 1)
                    assinaturas_por_gale.setdefault(gale_atual, set()).add(assinatura)
                    gale_atual = 0
                    indice_g1 = None
            else:
                gale_atual += 1
                if gale_atual == 1:
                    indice_g1 = indice_abs
        if gale_atual > 0:
            distribuicao[gale_atual] = distribuicao.get(gale_atual, 0) + 1
            total_sequencias += 1
            assinatura = _controle_geral_assinatura_trecho(dados, indice_g1, len(dados) - 1)
            assinaturas_por_gale.setdefault(gale_atual, set()).add(assinatura)
    unicos = {g: len(v) for g, v in assinaturas_por_gale.items()}
    return {
        "caminho": caminho_nome, "total_rodadas": len(dados),
        "total_pontos": max(0, len(dados) - 1), "total_sequencias": total_sequencias,
        "distribuicao": distribuicao, "unicos": unicos,
    }

def _controle_geral_surfe_enviar_sequencias(chat_id, caminho_nome):
    resultado = _controle_geral_surfe_sequencias(caminho_nome)
    if not resultado or not resultado.get("distribuicao"):
        bot.send_message(chat_id, "❌ Não encontrei sequências de Gale nesta análise.")
        return
    emoji = "🔴" if caminho_nome == "Vermelho" else "⚫"
    nome = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"
    linhas = [
        f"📊 SEQUÊNCIAS DE GALE — {emoji} {nome}", "",
        "📌 CONTAGEM BRUTA",
        "Mantém todas as sequências, inclusive as repetidas/convergentes.",
        "",
        "🧬 CAMINHOS ÚNICOS",
        "Mostra quantas sequências reais diferentes aconteceram.",
        "",
    ]
    gales = sorted(resultado["distribuicao"])
    fmt = lambda n: f"{n:,}".replace(",", ".")
    largura_gale = max(len(str(g)) for g in gales)

    # Alinhamento visual no Telegram:
    # - U+2007 FIGURE SPACE ocupa a largura de um algarismo.
    # - U+2008 PUNCTUATION SPACE ocupa a largura de pontuação.
    #
    # Isso corrige o caso em que "1.142" tem 4 dígitos + 1 ponto,
    # enquanto "624" tem 3 dígitos e nenhum ponto.
    ESPACO_NUMERICO = "\u2007"
    ESPACO_PONTUACAO = "\u2008"

    maior_digitos_unico = max(
        sum(ch.isdigit() for ch in fmt(resultado["unicos"].get(g, 0)))
        for g in gales
    )
    maior_pontos_unico = max(
        fmt(resultado["unicos"].get(g, 0)).count(".")
        for g in gales
    )

    maior_digitos_bruto = max(
        sum(ch.isdigit() for ch in fmt(resultado["distribuicao"][g]))
        for g in gales
    )
    maior_pontos_bruto = max(
        fmt(resultado["distribuicao"][g]).count(".")
        for g in gales
    )

    for gale in gales:
        gale_str = str(gale)
        bruto_str = fmt(resultado["distribuicao"][gale])
        unico_str = fmt(resultado["unicos"].get(gale, 0))

        gtxt = (ESPACO_NUMERICO * (largura_gale - len(gale_str))) + gale_str

        digitos_unico = sum(ch.isdigit() for ch in unico_str)
        pontos_unico = unico_str.count(".")
        digitos_bruto = sum(ch.isdigit() for ch in bruto_str)
        pontos_bruto = bruto_str.count(".")

        # O número continua colado ao emoji.
        # A compensação entra DEPOIS do número, respeitando separadamente
        # a largura dos algarismos e dos pontos de milhar.
        unico = (
            unico_str
            + (ESPACO_NUMERICO * (maior_digitos_unico - digitos_unico))
            + (ESPACO_PONTUACAO * (maior_pontos_unico - pontos_unico))
        )
        bruto = (
            bruto_str
            + (ESPACO_NUMERICO * (maior_digitos_bruto - digitos_bruto))
            + (ESPACO_PONTUACAO * (maior_pontos_bruto - pontos_bruto))
        )

        linhas.append(f"🔥 G{gtxt} — 🧬 {unico} • 📌 {bruto}")
    linhas += ["", f"📌 Total bruto: {fmt(resultado['total_sequencias'])}",
               f"🧬 Total de sequências únicas: {fmt(sum(resultado['unicos'].values()))}"]
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton("⬆️ 📖 ENTENDER A ANÁLISE ⬆️", callback_data=f"cg_surfe_entender_seq:{caminho_nome}"))
    markup.add(telebot.types.InlineKeyboardButton("🔄 TROCAR ESTRATÉGIA", callback_data="cg_menu_sequencias"))
    markup.add(telebot.types.InlineKeyboardButton("🐺 CONTROLE GERAL", callback_data="controle_geral_surfe"))
    bot.send_message(chat_id, "\n".join(linhas), reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_surfe_sequencias:"))
def controle_geral_surfe_sequencias_callback(call):
    try:
        bot.answer_callback_query(call.id)
        caminho_nome = call.data.split(":", 1)[1]
        _controle_geral_surfe_enviar_sequencias(call.message.chat.id, caminho_nome)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro nas sequências de Gale: {type(erro).__name__}: {str(erro)[:250]}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_surfe_entender_seq:"))
def controle_geral_surfe_entender_sequencias_callback(call):
    try:
        bot.answer_callback_query(call.id)
        caminho_nome = call.data.split(":", 1)[1]
        emoji = "🔴" if caminho_nome == "Vermelho" else "⚫"
        nome = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"
        texto = "\n".join([
            "📖 ENTENDER A ANÁLISE", "", f"🎯 Estratégia: {emoji} {nome}", "",
            "📊 Aqui são contadas as sequências de Gale, e não apenas o pior Gale do caminho.", "",
            "💡 EXEMPLO", "G1 → G3 → G2 → G5 → G1 → G8 → G4 → G2", "",
            "Cada sequência é contabilizada no Gale em que terminou. Quando ocorre um acerto, a contagem zera e começa uma nova sequência.",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            "🔽 FECHAR EXPLICAÇÃO", callback_data=f"cg_surfe_sequencias:{caminho_nome}"
        ))
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao abrir a explicação: {type(erro).__name__}: {str(erro)[:250]}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_surfe_entender:"))
def controle_geral_surfe_entender_callback(call):
    try:
        bot.answer_callback_query(call.id)
        caminho_nome = call.data.split(":", 1)[1]
        emoji = "🔴" if caminho_nome == "Vermelho" else "⚫"
        nome = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"
        texto = "\n".join([
            "📖 ENTENDER A ANÁLISE",
            "",
            f"🎯 Estratégia: {emoji} {nome}",
            "",
            "📊 Cada rodada pode ser usada como ponto inicial. O SURF começa na rodada seguinte e segue até a mais recente.",
            "",
            "🔥 Para cada ponto, fica registrado somente o pior Gale daquele caminho.",
            "",
            "💡 EXEMPLO",
            "🔴 Número 7 — 14:32:15",
            "G1 → G3 → G2 → G5 → G1 → G8 → G4 → G2",
            "",
            "🔥 O pior foi G8. Portanto, esse ponto é contabilizado uma vez em G8.",
            "",
            "📍 Depois você pode abrir exatamente esse SURF pelo número, cor, data e horário.",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            "🔽 FECHAR EXPLICAÇÃO", callback_data=f"cg_surfe_estrategia:{caminho_nome}"
        ))
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao abrir a explicação: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass

def _controle_geral_surfe_enviar_ocorrencias(chat_id, caminho_nome, gale, pagina=0):
    cache_chat = controle_geral_surfe_cache.get(chat_id) or {}
    resultado = cache_chat.get(caminho_nome) or {}
    caminhos = (resultado.get("grupos") or {}).get(gale, [])
    info = (resultado.get("resumo") or {}).get(gale)

    if not caminhos or not info:
        bot.send_message(chat_id, "❌ Essa análise expirou. Abra o Controle Geral novamente.")
        return

    por_pagina = 2
    total_paginas = max(1, (len(caminhos) + por_pagina - 1) // por_pagina)
    pagina = max(0, min(int(pagina), total_paginas - 1))
    inicio = pagina * por_pagina
    fim = min(inicio + por_pagina, len(caminhos))
    itens = caminhos[inicio:fim]

    emoji_caminho = "🔴" if caminho_nome == "Vermelho" else "⚫"
    nome_caminho = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"

    linhas = [
        f"🔥 GALE {gale} — {emoji_caminho} {nome_caminho}",
        "",
        f"📊 Registros brutos: {info['brutos']}",
        f"🧬 Caminhos únicos: {info['unicos']}",
        f"🔁 Caminhos convergentes: {info['convergentes']}",
        "",
        "📌 Registros que chegaram à mesma sequência real de rodadas são agrupados.",
        "👇 Abaixo aparecem somente os caminhos realmente diferentes.",
        f"📄 Página: {pagina + 1}/{total_paginas}",
    ]

    for deslocamento, reg in enumerate(itens):
        pos_global = inicio + deslocamento
        linhas += [
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"🧬 CAMINHO ÚNICO {pos_global + 1}/{len(caminhos)}",
            f"🔁 Pontos que convergiram neste caminho: {reg.get('quantidade_convergente', 1)}",
            f"▶️ G1 começou: {reg['g1_data']} {reg['g1_hora']}",
            "",
        ]
        linhas.extend(_investigacao_linha_registro(item) for item in reg["trecho"])

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if pagina > 0:
        nav.append(telebot.types.InlineKeyboardButton(
            "⬅️ ANTERIOR",
            callback_data=f"cg_surfe_gale:{caminho_nome}:{gale}:{pagina - 1}"
        ))
    if pagina + 1 < total_paginas:
        nav.append(telebot.types.InlineKeyboardButton(
            "PRÓXIMA ➡️",
            callback_data=f"cg_surfe_gale:{caminho_nome}:{gale}:{pagina + 1}"
        ))
    if nav:
        markup.row(*nav)

    markup.add(telebot.types.InlineKeyboardButton(
        "↩️ VOLTAR AOS GALES", callback_data=f"cg_surfe_estrategia:{caminho_nome}"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "🔄 TROCAR ESTRATÉGIA", callback_data="controle_geral_surfe"
    ))

    bot.send_message(chat_id, "\n".join(linhas), reply_markup=markup)



@bot.callback_query_handler(func=lambda call: call.data == "cg_menu_caminhos")
def controle_geral_menu_caminhos_callback(call):
    try:
        bot.answer_callback_query(call.id)
        texto = "🧬 CAMINHOS ÚNICOS\n\n📌 Agrupa pontos que chegaram à mesma sequência real e mostra somente os caminhos realmente diferentes.\n\n👇 Escolha a estratégia:"
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="cg_surfe_estrategia:Vermelho"))
        markup.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="cg_surfe_estrategia:Preto"))
        markup.add(telebot.types.InlineKeyboardButton("🐺 CONTROLE GERAL", callback_data="controle_geral_surfe"))
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro: {type(erro).__name__}: {str(erro)[:250]}")


@bot.callback_query_handler(func=lambda call: call.data == "cg_menu_sequencias")
def controle_geral_menu_sequencias_callback(call):
    try:
        bot.answer_callback_query(call.id)
        texto = "📊 SEQUÊNCIAS DE GALE\n\n📌 Mantém a contagem completa/bruta, inclusive repetições, e também calcula quantas sequências são realmente únicas.\n\n👇 Escolha a estratégia:"
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="cg_surfe_sequencias:Vermelho"))
        markup.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="cg_surfe_sequencias:Preto"))
        markup.add(telebot.types.InlineKeyboardButton("🐺 CONTROLE GERAL", callback_data="controle_geral_surfe"))
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro: {type(erro).__name__}: {str(erro)[:250]}")


@bot.callback_query_handler(func=lambda call: call.data == "controle_geral_surfe")
def controle_geral_surfe_callback(call):
    try:
        bot.answer_callback_query(call.id)
        _editar_balao_com_capa(
            call.message,
            _CAPA_CONTROLE_FIXA_B64,
            "capa_controle.jpg",
            _controle_geral_surfe_texto_intro(),
            _controle_geral_surfe_markup_estrategias(),
        )
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro no Controle Geral: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_surfe_estrategia:"))
def controle_geral_surfe_estrategia_callback(call):
    try:
        bot.answer_callback_query(call.id)
        caminho_nome = call.data.split(":", 1)[1]
        _controle_geral_surfe_enviar_distribuicao(call.message.chat.id, caminho_nome)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro na análise geral: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_surfe_gale:"))
def controle_geral_surfe_gale_callback(call):
    try:
        bot.answer_callback_query(call.id)
        _, caminho_nome, gale_txt, pagina_txt = call.data.split(":", 3)
        _controle_geral_surfe_enviar_ocorrencias(
            call.message.chat.id, caminho_nome, int(gale_txt), int(pagina_txt)
        )
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao abrir o Gale: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_surfe_ocorrencia:"))
def controle_geral_surfe_ocorrencia_callback(call):
    try:
        bot.answer_callback_query(call.id)
        _, caminho_nome, gale_txt, pos_txt = call.data.split(":", 3)
        gale = int(gale_txt)
        pos = int(pos_txt)
        cache_chat = controle_geral_surfe_cache.get(call.message.chat.id) or {}
        resultado = cache_chat.get(caminho_nome) or {}
        ocorrencias = (resultado.get("ocorrencias") or {}).get(gale, [])
        if pos < 0 or pos >= len(ocorrencias):
            bot.send_message(call.message.chat.id, "❌ Essa ocorrência não está mais disponível. Abra a análise novamente.")
            return

        item = ocorrencias[pos]
        caminho_nome = resultado.get("caminho")
        emoji_caminho = "🔴" if caminho_nome == "Vermelho" else "⚫"
        nome_caminho = "SURF 2 VERMELHOS" if caminho_nome == "Vermelho" else "SURF 2 PRETOS"
        numero_txt = "0" if item.get("numero") is None else str(item.get("numero"))

        texto = "\n".join([
            f"🔥 G{gale} — PONTO DE INÍCIO",
            "",
            f"🎯 Estratégia: {emoji_caminho} {nome_caminho}",
            "",
            "📍 PONTO DE INÍCIO",
            f"🎨 Cor: {item['emoji']} {str(item['cor']).upper()}",
            f"🔢 Número: {numero_txt}",
            f"📅 Data: {item['data']}",
            f"🕐 Horário: {item['hora']}",
            f"📍 Rodada: {item['rodada']}",
            "",
            f"🔥 Maior Gale deste caminho: G{gale}",
            "",
            "🎯 Este é o registro exato usado como início desta ocorrência.",
        ])

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            "👁️ ABRIR ESTE SURF", callback_data=f"cg_surfe_abrir:{item['indice']}"
        ))
        markup.add(telebot.types.InlineKeyboardButton(
            f"↩️ VOLTAR AO G{gale}", callback_data=f"cg_surfe_gale:{caminho_nome}:{gale}:{pos // 12}"
        ))
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao abrir a ocorrência: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("cg_surfe_abrir:"))
def controle_geral_surfe_abrir_callback(call):
    try:
        bot.answer_callback_query(call.id)
        indice = int(call.data.split(":", 1)[1])
        _abrir_ponto_surfe(call.message.chat.id, indice)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao abrir o SURF: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass

# Capa fixa do painel principal — ANALISADOR ESTATÍSTICO.
# A imagem fica embutida no próprio .py para não depender de arquivo externo no Render.
_CAPA_ANALISADOR_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/4gIcSUNDX1BST0ZJTEUAAQEAAAIMbGNtcwIQAABtbnRyUkdCIFhZWiAH3AABABkAAwApADlhY3NwQVBQTAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA9tYAAQAAAADTLWxjbXMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApkZXNjAAAA/AAAAF5jcHJ0AAABXAAAAAt3dHB0AAABaAAAABRia3B0AAABfAAAABRyWFlaAAABkAAAABRnWFlaAAABpAAAABRiWFlaAAABuAAAABRyVFJDAAABzAAAAEBnVFJDAAABzAAAAEBiVFJDAAABzAAAAEBkZXNjAAAAAAAAAANjMgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB0ZXh0AAAAAEZCAABYWVogAAAAAAAA9tYAAQAAAADTLVhZWiAAAAAAAAADFgAAAzMAAAKkWFlaIAAAAAAAAG+iAAA49QAAA5BYWVogAAAAAAAAYpkAALeFAAAY2lhZWiAAAAAAAAAkoAAAD4QAALbPY3VydgAAAAAAAAAaAAAAywHJA2MFkghrC/YQPxVRGzQh8SmQMhg7kkYFUXdd7WtwegWJsZp8rGm/fdPD6TD////tAEBQaG90b3Nob3AgMy4wADhCSU0EBAAAAAAAJBwCdAAYTGF1cmEgTSB8IERyZWFtc3RpbWUuY29tHAIAAAIABP/hDHVodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvADw/eHBhY2tldCBiZWdpbj0n77u/JyBpZD0nVzVNME1wQ2VoaUh6cmVTek5UY3prYzlkJz8+Cjx4OnhtcG1ldGEgeG1sbnM6eD0nYWRvYmU6bnM6bWV0YS8nIHg6eG1wdGs9J0ltYWdlOjpFeGlmVG9vbCAxMi40MCc+CjxyZGY6UkRGIHhtbG5zOnJkZj0naHR0cDovL3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyc+CgogPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9JycKICB4bWxuczpwbHVzPSdodHRwOi8vbnMudXNlcGx1cy5vcmcvbGRmL3htcC8xLjAvJz4KICA8cGx1czpMaWNlbnNvcj4KICAgPHJkZjpTZXE+CiAgICA8cmRmOmxpIHJkZjpwYXJzZVR5cGU9J1Jlc291cmNlJz4KICAgICA8cGx1czpMaWNlbnNvclVSTD5odHRwczovL3d3dy5kcmVhbXN0aW1lLmNvbTwvcGx1czpMaWNlbnNvclVSTD4KICAgIDwvcmRmOmxpPgogICA8L3JkZjpTZXE+CiAgPC9wbHVzOkxpY2Vuc29yPgogPC9yZGY6RGVzY3JpcHRpb24+CgogPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9JycKICB4bWxuczp4bXBSaWdodHM9J2h0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9yaWdodHMvJz4KICA8eG1wUmlnaHRzOldlYlN0YXRlbWVudD5odHRwczovL3d3dy5kcmVhbXN0aW1lLmNvbS9hYm91dC1zdG9jay1pbWFnZS1saWNlbnNlczwveG1wUmlnaHRzOldlYlN0YXRlbWVudD4KIDwvcmRmOkRlc2NyaXB0aW9uPgo8L3JkZjpSREY+CjwveDp4bXBtZXRhPgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAg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8eGQV8fZ67l71Ueuf6I8YPiVz2nMe4um2dN99xBB/YBaf+9sShsXJqAaMIw7/wD9c2cp/s2blg60/Rt0zDSH79MiNcXgQqoALseorD8e/wBztVLvs6gPVv0/e/8AOS6Rb+cP9xvHbi1xVbr4t3OcI7ymn+QNhTM82IjZV76lxHXLLADO0ba/30C+hyKF7dFezw5wIMMIXSVfXQapWBIFJEL/AHWLKN+O9q/RHql07xlEteZNUEQiUPKFWCR099Z+cnuQWfbUBIHZKJsre6aiRVMLK1Am2cuQT567f7z9FPBj5WNri0SLuZmbPV9YeAct030sPehQ9NpQglKStxDNxK3T8ISiCC8zhh3t69NRigRfsbYn05//ACOzXyoxpjJGMYbdXdnLUO/L7wgh3DeR0E+fo0g3BnLC8KZO5Kv+cyHS+7xmSqUtgshnYX602/moCR3IzCWl38AIoicofTjJcDn5fKQx/Srb5vviHtXMM+bycGFBN7+c5/8AKn4eiwH9Zo37KHRZXmIp613n0H/YPFr9sU2teOQ6BwSyduJ1EhqRgrVTfoCrK8DNu56JKHCtQEE2g7thvP7J95ue0IgQ9IK2+zuDxSxZsRTmOHl2Q1AKv0y20Z76cq+GbVJl3A/0rruekiW546X+kpRHugGX39yBpeOWznzzzzxm9GCwmZ3vsQT5v/8AeyltJhCijHJmTiU+/V9994oeTtMd8t8888pr7TIdsIdm5T0LG/8A/p6iNGqAwbpAC34/vf8A32H2/wC0s8888888ksM8888K2MscC3280/8AsuujLAd7e5gaW/8A333red2Xzzzzzzzzzzzzzzzx+bzwlOqcP4wcp9BJ6ZieRml03z/f/wCJGMc888088888888888888888dSIgB5/GXd5Jv3KYHNVXVUwY0row888888cw888888888888888v7m9RFl9ddU9okwAlP4ooJt7pcpV88888888888888888sc8888MS7nXWy4bGanbCKDmcXC29Mc889E888888c88888888888488888cd19VdSPKjvribmnlSvs88888888848888888888888888888888cMo0O3vi5nCwNm88888888888888c8888888888888080888888888889c888888888888808888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888/8QAKxEBAAIBAwIFBAMBAQEAAAAAAQARITFBUWFxEIGRobEgwdHwQOHxMFCA/9oACAEDAQE/EP8A5L0Cr2LpYiKJT/KIN3uA5WciwOonI/8AWpUB1LQlhbXpENXSW3uypUrwJvxaXFTkBL3qv5RliLCym95V6KNTm7/41KleCvAwGPBUqJEVyimmnylKI7kt3GvpK+xDasW7bH8zHd8/UEPAqVK8RwmB28SvA+Ir6dfsfH8fq1+fFdH3IdD1J+wQXPqJc1PBkwojTo1sxliwGh4mBg9DwVK+gMJKlePwnx/I58mjqygMqrz7y/7H9T/GfiX+x9oCACLutx5m7Xbc8vCS5vgQC2IGiitZn+h9YDDDCRPDV7Hx/HBUDeAILx2v7zGR+glrVg578+cAdJ9njwt1iW0LfYhleTMrtPQ0RxF8eF8NGxfa48n0iv8ARjw/RjYUDEiT4z4/jmpvo7TC3a93Hl9TFnVhlgvA9dnzlJU06XNfhwPvAgATqgyFQS4WKfLxl+BCm2hyxUX5/LmdZOonWQBVcOH7yhiQZ9vh/Gtc6GV6QdUwYHXb0iq2/RUCVB+rZ/UYLhDq2HzmNtGFYcSgQDRt52hfIrBQJmbIp5gXJknb4RQPJ5a/iMyPLiV4kKOrDL51NDyRgZ9vhE/7q1kU0TWrPr9ATVTZz22gzGz338SBCCSXq6Br23loFCtfBMtS9d5UXVpzFRTE6o6nrrEK/mBfemAgpZkEmhXXDpONcGVrRUdDeUm5z3ceJUp6QFR5ok1a8korWdGbsY0DQS4fYfEET/jRqb4D/iQTJks0TkjfXA/DERR1PAgltYgBd6mPDpFgLP6qLUKDHldiOKN2Xa1cryIhcLxH1lJe4mr1WGOBqhcsdwLtIvAR1xN9OZYqb2lgymAtI4lLooHE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"


_CAPA_BOT_FIXA_B64 = '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'
_CAPA_SURF_FIXA_B64 = '/9j/4AAQSkZJRgABAQAAAQABAAD//gA7Q1JFQVRPUjogZ2QtanBlZyB2MS4wICh1c2luZyBJSkcgSlBFRyB2NjIpLCBxdWFsaXR5ID0gODQK/9sAQwAEAwMDAwIEAwMDBAQEBQYKBgYFBQYMCAkHCg4MDw4ODA0NDxEWEw8QFRENDRMaExUXGBkZGQ8SGx0bGB0WGBkY/9sAQwEEBAQGBQYLBgYLGBANEBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgY/8IAEQgDhAZAAwEiAAIRAQMRAf/EABwAAQEBAAMBAQEAAAAAAAAAAAABAgMEBQYHCP/EABsBAQADAQEBAQAAAAAAAAAAAAABAgMEBQYH/9oADAMBAAIQAxAAAAH+fwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACkURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRAAAAAAAAAAAAAAAAAAAAAAAAAFEURRFEURRFEURRKAAAAAAAAAAAAAAAAABRFEURRFEAAAAKRRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURRFEURYFgAAURRFEUQAAAAAAAAAAACURRFEURRFEURRFEURRAAUAAAAAAAAAAAAAApFEURRKAAEURQAKRRFEURRFEURRFEURRFEURRFEUAAAAFEAAKRRFEURRFEURRFEURRFEURRFEURYAJRFEURRFEURYAAAAAAAAAAARRFEURRAAAAAAAAAAAAAAAAAAAACkURRFEoAFEWBRFpJRKApFEURRFEWkURRFEURRFEURRFEURRFEURQURRFEURRFEWmWhlv0qb+U+r9Dm9j4R+jcuXd+aX9K4Zj86fdedpw/LPT8/q8fDS2OWhloZaGWhlqEURRFEURYARRFEURRFGWhlRGoRRFEWACURRFEURRFgAAAAAAAlEURRFEWAAAAAFAAlAApFEURRKABRFEURRKpFEURRFEUAFEURRFploSIWBQD9RPD5v6TH8reB/ZXGfxm/bvnT8zdvqGmdBoZaGWhm2mWhloZaGWhloZaGXL9Hl3fP/R/Rcvlfb8Ha7X2HP7HwvJ+v+Jt53xfP+yTfzPx3g/aKfgvH+ke1h6n470/0T4/D0Pifnf03g6vF/NH0Xgep8Rhua8eWhloZaGWoRRJoZaGWhloZXIgL7H1Z+edz+k/sD+XvV/ouH8o/P/19/MR88BLCoKUijLQyoiiKIoijLUIoiiKIUiwAiiKIoiiAAAAAAAUABSKIolAAoiiKIolAoiiKIoi0zaIolUiiKIojQzbCYgWUAqU5f2H5X9pPjur9yPiva9b8uPtP0X8W9A/VPxr9U9I/j/P7n+QHl8vEOeTZFploZaGWhloZaGbRO1y/X8f0HF6GNeN+h7+0+K/SNeL7XXzPiej8j9n8D6XRx9Lu8H1Kc/luz9AR8Z958L367fecfwHub+Z8v8f+i/nHnfXPK9TOfX+fcP3nx3s/nXUadfhZaJy0MtDDQy0MtDLUJhgH0J5P7b7H152OPwfz87Pu/JZO9y/aD8+8z9UH8uO90AACWDkY5CNDKiKMtDLUIoy0MqIoiiTQyoiiKJNDKiKIoiiAAAiiKKAUiiKABSKIoloiiKIoi0iiKIolUiiKI0M2iKJaIsM8IUCygAH6z958T9Od2dEY83x/rz1OLq8p8b3fpviD9C7fwn6Sfy/5f9B/z4ObgHbTZlsYuhloZahFpnt8X1nL7nPz8e/F/RN649U337PielfD9E9Pgx6PyXN8v73ztOr6Z1Vqdq9REeN9T8n9FGne87m5NOX848Xvef5v1tzJXV1exi/P8ZwfW/K+1+cYV0+TGhhsYbGG4ZaGeDXCU2fT/wBGed2T5XyPO5jk+z4uA7fwf1nknvvk/dPQ152j8m+S+8+DABAAQ7Dh5yKJNDLUJNDLQy1CKJNQiiKMtQiiKJNQiiKIsAIoiiLAAsKoiiLSKIoAAKI0M2iKIoKIoiiWiKI0IojQzaItM2idbl4ACpQCpQD7vudX1Dg73U8Y9f6/8uwfrHJ+ce8dr6z5v2Tk8L6H8jOl84AGu50ec7DQy0IoiiL3ab+n6fDyeJ+lcuuPWPdvXHqL7vHYt+m9z4Pn7PD+x+f8Tmrr62fN7629cXQPU9/4rhmv33S+Y605eNmZ5Pb1mSaMs2znkerx7ed8nez1/a/OIq2cUZaGWhnj5ekYAB+j+t+RfqJ931ez1jyfV+dwfQY/OOifQ9z5D6Mt7NPlfmPrfkggAEAHLxDtlJNDLUJNDLUJNDLUIokoiiKMqIok0MtQiwSiKIoy1CKIogLQKIoAKIoKIoloiiKE0IolUiiNCKI0IojQi0y0IvEdaQUAFSgAH6j7HzX0ByeH63kHua4NHW+M+q9Q+V+68v4E9/8APQAELA9HXV7hFEURRPe8r2uD6fm5OHk8/wCt5dcWqbcl47F+S8di3J99+ffS68f0WeKdPmdH0vL71debzu30EevrratlPgvo/meb1LJnPq1mZmlyzObDFsup430Piel8hwq7fnYok0MqOv094KABvA/WfT/GPqTm4vtuucnP53bOLrd7xj3dcI+X+E+t+SABAABA5uz0O+JoZahJoZUSaGVGWhlRJoZUSaEmoRRJoZUSahFEUSURRJqEUVRFBRFApFEqkUS0RQURRLRFEtEUFEWkUSqRRKpOl3fOICgAAqUA+r9z84H6R1/z8frk/Ju2fo/ofn3pHqfnN4yoKm4nt++4KdXneX7/AJB1/V8j09OTkURaZaHf73W7Xkfe+zwb5q7+ZrjuPocrjtb8l46nk7HUJ+/4fiM68X1PN8grp9fwfLj7nk+Ct8uxwYmPbuZiLMyaXMzbPtcnPx7cHkdDv9W/L5rT1fiMtQiicfL1Dp3Parp2+9ybp0fO8P0nzV+eotnez1R+q978p+qPZ7/575R+oeJ8EP0d+cD3PDAQAAEAHa6vKd2aGVEmhlRlqEUZahFGWoRRlqEUSUSaGVEUZahFGVEUZURQtEURoRRKBRKpFBRFApFpFEWkUSqRQKRRKpFEUcXQ7vSAFgoAC0zYKgqUAAAAdzpd+unf4L0qdNZV06/d6vPtw921NItM6clde7y9fk8n7v0uXzO6vnMxn08t47XTkvHYtu8dTthE8jjptxjbERuZkxqZk11mZmmnHq2Xc489LTlcV45p05yZ9T4fLS1MtQnm+n5Jns8HLn177vn2unq+N6XRvh1RfnAAIKgWAA7PCYAAgALB6kUiiLCKJNDKiLCKJNQijLQyokoiiTQyok0MqMqJNDLUJNAoKIoKJQKJaIoFJVIolAoigolAAolUiiUAOt0+50wABYKD1P0j4r7w+Q+L+9+CAAAH1fyn0Zv5n3/AAHY6/arrlJXfTNhOXh5r8/o222eWhnc1Tp5uTg5PN+w5t8OqdPPbxRpy3jtb8nd8/wBuaez4f1fzGvF5DDn9TdwNzMNzBH1E81vweXMzHs1nObU1nK2TExbK4cd8GdPR+Pyq2WWhjyPY8cuuO59Oriray5lemNOZ7PjfZG/lv1T8sOkAABrI/WPA6nlnikLAAAFPR3jkIoy1CKMtQgEoijKiKJNQiiLCKJNQiiTUIokoijLUIoKJVIoKJQFIoFACgAolAAoAKABSUJQKOt0u/wBEysAAAPtPsPzP1h8l6nlgAAAAADk49xfSK61kXs9bt2w9FUxFEpTZycO+D6zm3w6p087i1XTk1xarpyfS/Lc1qfoXxmOlbBeNl28jjHI4xyTA0xJrvOYrrOZalzMWyuc5tjcTN+bmq93y8lWpJoZ8f2vGOOJXTTJOtccRBbN938JT9b/JOTiAAACCoAAAAGpT0tKRRARRFglEUSURYARRFglEWEURYRRFGVEUZURQKRQAUACkqkUAFABRKBRKABQAKACkocfm+t5ZhYRRFEKRRKAAAAAACyxNuUXsQ5O/0PVtn2FApFRPBrF4vp+bXDvLr5d8Oo15bx2t93CLcjjqdsVbTKI0zDbCWpmK6kzNbM5tnrEzbFmYtjc53rx9pXV4EEosHler550cb406RE1CAmAAAAEogAAABSVScmOwd4EURYShAARRFhFEWEUQCURRARRFhFEABFEmoFEoCkoFABQAUSqRQAKRQAKRQUSgAUAOj3uE8+WEWAAAAAAAAAACWCxErNI5Pb8305UhpBUHDjm6/P7HJvh3z+ny64tRrya47W/IxYvtgndwTthDczDbCY1MxXUzLVuZmcrhi2TMxfnvY6vobedom3n2BYDrdmHh8fNwkAsoAAAAAAlgAKAALKXvdL1CgSiLABKIsIoiwAiiTUIoiwiiLBKIogIoiwiiAKJQKACgAUFIoAFJQAKACiUAAKAABQ8zj7/QICAAAAAAAAAAAihqdo7/AD5pUFQVKOr2uKnRw649c3tcmuPVNuS8djTkvHYttlFtsFtsEaZiNzMmNzEmupmTTWZm2VwxbFhL8/P3ePk28wi2dQCFQdHz/c8c4WoSgAAAAAlgAKAAAU0dnuSgAAEWAAEUQEUQAEUQCURYJRAARRAJRFgUAFAApKpKABQAKRQKSgAAURQAAIVBUF8/v5PLayQAAAAAAAAAABRfY6/aNINMjTNKkNMjgz2Oth6W9cWs+7kYtdN3CL8jCLbYG2BuYI0xJruZk11M5mm85zbG5mb4XscPfvy6Rpy1BUFkFQXq9geLO11SKIAAAAQsABZQAAC9/g7wAsFQLBYAAACUQCURRAJRFEAlEUSURRARRFEUACkoFAAoAAKACgAAoAAAQLBYhUFkhpmGeh6HGdFclShBUFQVBUoAAABe3juHK46cjFNM00zSsw0yNZSJ4Lvix9Ldwp08l47F9sE7YRO2CNMyWmCuphams5k52ZzOWrnt35+XWLfl2xZbYG2RWaEhqTJrzfQweY5OIAAAEAAAAALAvLO4clxTVxTTNKgtgqCoKQoAIsAAEoiwAAiiAAiiAiiAAKACgAUlAAoAFAAAKAAgAILELIDIszDUzk3OOGury5OG3JUFAAABYFgAOzx8h2Lw6Oa8ejeuOm7immRqSGpmGpjJvOMRO7wM+zsXitOrkYRO7x1O5mG2IjcxJpvOM2z5M4k57ce74drXX3OPPeLUuS4ptmmmRqQWSFmYXMwa6vNg67fGAWAAAAAIVBeXGzn1waOe8WjkvHo2xo1cjSC2CgAoAAEoiiAAiiAAAiiAAiiAAFAAFAABQAWUAAAAUEAQELEBBEEZGbkmZguZAkLAAiwAAAAAtlLvOze8chrWdGrKWygglhM2Gc6wYxrBnNyXk4kX7F6uq69m9axfsOvU804SOXPHJpyZwtlYKXWLLl5OHkOXfHs5LjRu5pQASWGc7wYxyYOPG8GJrJJRAAAAAFACwauKcm+LRza4tnJcaN3FNpSpSpSgWUAAAAAAiwAiiAAAiwAAlAAUlAABQAUAAABQQsACAgIsJLCSwmdZJjeTGOTJxzkhxtww1CKIBKIoi0i0y3oxrezGt7Mb1SaujNtJQSjM3DE3kxjlycPH2MHXnNk4XJDDUIsIoiiUC0zdUzd6M71oaaG1FUKIok1DOdwxjmycGOxk62exk6058nDdww1CKIoigAtM20zq0ltG5oupTVlLZSlFlFlFlAAAAAAAEogEogAAIsAACgAAoAFAAAABQBLAACLCLCLCLCTUMzcMTY488sOKco4ZzDhnMOGc8OGc44XNTgc9OC844bz04dctOPXIMa2M3VM20y0Iok0MtQzNw45yw4s82Thzzw4M9jJ13OOvOwOu5xwOwOveenBeanDrlpx3kpjWqZ1qmboSqRaZaGWhhoYmxxzkhxZ58nDnnh189nJ189mHWdgddzjgc44HPDivKOK8o4ryDF3TNtM6oVSVRQUFlFlAAAAAAAAEsAEogAAIBQAAUACgAAABQAASiAAAiiSiTQy1CTQw0MtDDY43IONyDiu6cbkHG5Bi7GLumLqmWqZtpm0S0RRFEURRFGWhhoZmhickONyDinKOJyDjnKOK8g43IMOQYbpi6pi6EqkWkURQURRJqEUSahlqGG4YnJDjnIOJyQxOQcbkHG5Bxt043IONyDjuxhoRoZtApKpFApKAAAAAAAACUQAEAABFhQCkoAKAAAAoAAAAAAlEURRFEUSaGVEURRFEURoZaEaGWhFpFpFEaEUCkURRFEURRFhKEURYRRJoZahFEURRFEaGbRFEWkUSgKRRFEURRFElEUZahJoZUZUZaGWhhoZaGWhlRFEURRFEUSqRRFEURRFgAAAAAABAAQAACWFBQAKAAACgAAAAAAAAKRRFEoRRFEURRKpFEUFEUSgUSgoAAAAAAAAAAAJRFEUZURRFEWmbRFEURQAAAAAAAAAABFEmoRRARRFEWEURRJoZahFEURRFEURRAAAAAJRAAAAAQACWAACUKAAoAAABQAAAAACgAAApFEoAAACkUSgAKRQAUAAAAALKAAJRFEAAAAAAAAAAAKRRFEUSgAABFEAAAAAAlEABFEAAlEUQAAAAEUQAACUQAAAEWAAACWAACWAAAFAAsoAAABQAAAAFAAACgAAAKRQAAAAoAAUAAAAAACwUAAAAAAEURRFEURRFEoAAAAAAAAAAQAAAAAAEAABAAAAAJRAAAAARYAARYAAAJRAAAAQACWAAAFAAsFAAABQAAAAUAACgAAAAsoAAAAsoAAAsoAAAAAAsFAAAAAAAAAAAAAAAAAAAAQVBUAAAAAAACAAABAAAAAJYAAAAAIAACWAAAAEWAAAEWACUQAAFAABQAAALKAAAAUAAFSgAAAAFAAAABUoAABUoAAAAAABUFAAAAAAAAQVBUFQAAAAAAAAAAAAAAAQAAACAAAAABAAAAAEAAACWAAAACAAAAlgABFgAAsoAAsoAAAsFAAABUoAAsFAAAAAsFAAAABUoAAAsFAAAAAAAABUFQUAhYAAAAAAAAAAAAAAAAAAAhYAAACAAAAAAgAAAAJYAAACAAAAAEAAAAlgAAlgAABUoABQAAALBQAAAVKAALBUoAAAABUFAAAAAsFAAAsFSgAAAAAAAAAAAAAAAAAAAAABBUFQVBYAAAAAACAAAAAIWAAAAIWAAAIWAAAAAIWAAAAAgAAJYAAALBQALKAAAAVKAAAAVKAAAVKAAAAAVBQAAAAAVBQAALBUFAAAAAAAAAAQVBSCwWAAAAAAAAAAAAAAIVAAAAAAIAAAAAIAAAgAAAAAIWAAAAAgAAAIAAAAFAAsFAAAAsoAAAAsFSgAACwVKAAAAAVBUoAAAABUFQUAACwVBUFQVBUFQWAAAAAAAAAAIWAAAAsFQVAAAAAAAAQWAAAAAQAACFgAAAACFgAAAAAEAAACWAAAAAFAAAsoAAABUoAAAAAsFAAABUoAAAAAAsFSgAAAAAAFQVKAEoAAAAAAEAkCQAQIVBUAAAAAAAAAAAAABBYAAAAAhYAAAgAAAAAgAAAAAAIAAABAAAAAAAsoAAsFAAAABUFAAAAABUFAAAsFSgAAAAAAFQVKEFASgAAAAAAAAAAFQmoKgsAEAAAAARRFEUACFQVAsFgAAAAACFIAACFIWAAAAAQAAAAAAEAAAAhYAAAACBQAAUAACwUAAAAAFQUAAAAACwVKAAALBUFIUAAAAAAAACwVBUFQVKCFQVBUFQWBUFQVAAAAAAAAQVKAAAAAAAACFQAAACFQAAAAAEAAAAABAAAAAIWAAAAAAgAUAACwUAACwUAAAAAAFQUAAAAAFQVKAAAALBUFSgAAhQAASgAAAABFEoAAAAJRFAAAABKAEFAAQVBUAFQAAAAACFQAAAAACFQAAAAAEFgAAAAEAAAAAAhYAAFAAAAsFAAABUFQUAAAAAFQWBQAAAAAVAsFQVKAAAALBUCwAVAAAAsFQVAAABYACwVBYACwVAAAAAAAAQVBUoIAVBUAAAAAABBYAAAAAhUAAAAEsFgAAAAACFQAAAAUAAAAAFQUAAAACwVKAAAAAAVBUoSgAAAAAAAAFQVBUFQVBUFQVBUFQVBUoIVBUFQVBUFQVBYFQVBUFQWAAAAAAAAAAAAAABLAAAAAAAQWAAAAIWAAAAAAAAgAAAAAIGgAAAAAAALBUoAAAAsFSgAAAAACwVBUoIUABBQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACFAABKABBUFgAAAAAAAEAAAAAgAAAAASgAhYAAAAAAEABbBUoAAAAAAAABUFSgAAACwVBQA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AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQwwwwwwwwwwwwwwwwwgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwwwwwwwwwwwwgAAAAAAAAAAAAAABDDDDDCAAAAAAAAAAAAAAAAAQAAAAAwwwwgAADDDDDAAAAAAAAAAAAAAAAAAAAAAAQQwwAAAAAAAAAAAAAAABDDDDDCAAAAAgAAAAAAAAAAAAQwAAAACAATzwwgAAAAADDzzzzywxwwwwwAwwgAAAAAAwwgAAAAAAQxxxjDAAQwwAwQgAAAAAAAAAwwwgAAAAAAAAAAAAQwwxjDDCAwASThyxjDTzzgAAAAAAAAwwxzzwAwwwwwgA+PK3LHDDDCAQwwwwQywwwADDzQjAQxzzzDCQwwwAAABDDDAQwwwgAARwgADDCAwABTygBDDzwxDDzjBhQADTATQgQwygATzzzzS+CcC5j7z7TzDCQxjAAADwSSCABDDwjDzzgADTwgAgACAAAAAAAAAACwxjDCwwAADCQAATziBCgADTCCCgAiyzwBySBwgAQRjCYU37cnYnd/cGMkAADywwQACyCCDgSADjTDwjCQzDwwhDwABDzABAwwTzwQhDwxjQyADzzgAwyjTzCRyQzgCgBQBADCzixzzCAARhwH/spbitM7stW8wDDDTxwRwRRSQAgASABwxCRjDSBQwjTyxRzCQzwAQwADDgBQxzTCBzwQzyRzARCxixgAhAhCSwASgRABDDAQwoQaF6wexi2ZRjD28wjDAgDAzSyxQggyAABCRyRyRDSxywjyxDSRygDSiAyQBwwDQDSARxByhxBzRzRjQwQBAhDQAzjSBgARDwAADWgp45ela4nLVTI5IwhDygAICgyQSRgASABhhzRixiyDxixhQhChSgBwxTBDwDxjShSBQByDyRwTgCgShhQABAgCCCAigASACzzjF9qx71ZY8/04KoK+7DSwBYMYABjRgAADAASBRAxAjQjQjSCQgxCwDQjwDyCBTBSzSjQRxzgDgyjAhCADSgCwACygwgAQAB9GvyzjEawW6qnZs+fb3dNOVbzxwlLkAAAwyCAgABgBBSgShCiSRSjDhyxCBCjxjRDwDwCxSDQiBCxDwCQzChCQywACQBSwADTjDCDXv6jDFGQRHeIGFR/nsF1WdmzCQ6gLTxgAAASQRAAAAgDACAxyDyhSAShShShyzQBCjwCRjQgwAgCQQQwAwiSwRAQABDSgAAAAABDDmcBSvCD34gCz21qV5iQ/ONzABIU0BDgAAAwAAAAABwAzARgBiQiAQgTQTiDwjyhjAxAxyjAzARCxCAzAQgxiRSzDBjCAAAAAABq/5TBiPhuAOcljP8h+KwkdjMjQBxCagAAABAgAAAiCQzCSgwjADATgxiAzCTgwCBACACQAwAACBAABAABACABAAQwQAAAAAAAAABDL9QQAymsGNJ2UNeFvD9KPHRxhAyAAAAAAABQBgAChAAAAAASAAABSASABgACAAAxCTARARhjAxiAzAzCAAwAACAgAAAAAAAAAAAAAAhCxjR7M4PMYfbQ3pUJwLADQzyAAAAAABABAABBSAAACQADAjAgDAhCRgwjAxCTARABiCABAADACAARDAAAQwxwgAAAAAAAAAATSBBziT2oBORL8pu8IYWWjLyBywiyAAAAAAAAAAAQDSwyxwwABAhCAhCABABCADABABiAAAAAAgBgAAAAAAyBSBwSgwgwwwwgAABQwxzhizyNvUsD7OSohmaZNgwCjRQAgAAASAAABBAACjjyAAwQACQgAAQAAAwCAyAwBATABiABABgAAAAAyAgBijzShywwAABBBDSBRCwjBRiyb/TKtYdtR5x7izhxgChTATBCAAAAQwDwBhgQCQDAAABCAwDAwADAgCAgBgAQAAQAAgAAASBATRyAACAwCRADTDDDAQDAgzwiRDiSzTD4KHh0lMQzBQBCAATiiBBDDDCAAADzzzgxBhwCgAAAAACQCAgAAAACABiAAyAyAAABgRgCiiBTzRBzACwAxzyghwhiQDgwzCQRCjAAThCQiAQByRxCARxTijyiRzxgwAiRSjQABACAAAAAAAABAhAgAAAATAARABgAAABgAQACSCSwzThzjhhRwhgRQxSRgjQxiQSARAShAxCjzxQzDAjjCCzixQjRTggBSQDzgiQDgCCigAAAAAAABQBAgAAgAASARAAAAQAABAwgABzCRjwADACjTwSAhiiyAzzzwjDgjSBAzyTxBCDQjhTwABQgSyADiRyAAjDCDxDwiiQiAAAAAAAABAgCgACABiASAAAAAAAAAABDDCABDzDTzzDwDxxhTBwjDDCDCSyAShDTxzzyCBzhSxjDDDDByCBAwzyDzjDzwgBDCgDDDAQwAAAAACgCgAABQACAAAAAAAAAAAAAgACDDDDygBAACDCQAAAAAAAAAAAAAADDDTiABDAAAAAAAAAAACBCAjAADABDTCAAAAAAAAABAgAAACgBQAACABAAAAAAAAAABgAARjCAAAxiCARjAzAAAAAAgABDAwwgAAAAAAAxjDDCAAADAgAAAABAACAABDAwAAADAwABAAAACAAABQABQAAAAAAAAAAAAAABAAASAAAADAAAASABQAAAAAAAQAAAAAADDDDBDCAAAAAAAAAACgAAAAAAAACgAAAAAAAAACAACAAABAAAAAgBQAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAACgAAAAACwAAAAAAAAAAAAAAAAAAAAwwAAAAAAAAAAACgAAABAAAAAAgAAQAAAAAAACABAAAAAAAAAACAAABAAAAgAAABQAAABAgABAgAAAAADAwAAAAAAAAwwwzDDDDCAAAAAAAAACAAABgAAAACAAAAAwAABAAAAAgAABQACAAAAACgAAAAAAAAAAAQAAAACQAAAAAAAACAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAAAAABAAAAAAAAAAAAAAAAAAABAgBAAAACQAAAAgACQgAAABAwAAABCQAACAgAAAAAAAAAAAAAAAAAAAAAAwwgxDCAAAABgAAAAQAAAARgAARgAAAAQAAAAAgAAAAACQACAAABAgAABAgABAgAAAAAAAAAADAQABCAQAAAAAAAAAAwwCBDDDDDAAAAAAAAAADAAAAACAAAAAAAASAAAAAAAAAABgAAAAAABQAAAAAACAAAAAAgAACQgAAABAQgAAAAAAwAACAAQwwwxjDAAAAAAAARzjDCAACAAAAAAAxAAAAAgAARgAAAARAAAAAAiAABAAAAAAAACAAABAgAAABCQAABAgAAAABCQgAAAADDAwgAgAAAAAEMEAAEQQiAAAAAAAAAAAAAxAAAAABgAASAAAABiAAAAABgAAAgAAAAAAAAAQAAABAQAAAAAAQAAAAgAAAAABAAAwAgBABBDDDDADEAwxDUGAAADDDAAQACBAAAAAAQCAAQQAAAAACAAAAAAgAAAQAAAAAgABAAACQAAAABAQAAAABCQgADCQwQAAAAADDDSwQwwgQwwwxwwwzDDDAAAAwgAAAAAAAAQzCAAQzAAAAAiAAAAAzCAAARiAAAABgAAACQAACAAAAAABAQAAAABAAgAADCAAAAAQAACAABDADCA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'
_CAPA_CONTROLE_FIXA_B64 = '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AAAEAAAAAAAQgAIAggAAgAggQgAQAQAAggwAgQwA0Acw08w4c4MAckwMAAEIIAAAQAAIokIg0kIsMEgkw88YwwEwEwE8ssEQ8Msc8MscscMc8oIAEk4wMw80gocsgAAAAAAAAMEw4888sAAEAAAAAAAAAAAIIAAAAAEAAAEcgwAQ4AQQE4II8IAAAUAAAEMcgoA0YEoUwcMAAAIAMYoEg4wE8MEU0wA8gAAEIAAAA0cQIMQ8YwIAAAIAgAAAEYAwk0IAAAAAQEUwgQEUc8sUUkAAkAAAEEAgI8EkgYkkAMQUUoEsQ4sYogsIwAQUgQQAgUQIA0ggc40wsg4EkMIwocIAQ4wYA0M4AwEAAcAAAAgAAIMcA04UYQssUc8Eogkcg0sEME0YQAks4Iw8MwoU4so8cIMAAMgQAAAEAAAEAAAAIAEAAAAAAAIAs8McoYIAAI0gAY0IAwAAAAAAAAQsAA8U0AAAAAEskAAAAAAAAcAA04MoAEAAAAEAU0cEoA8AYEAM0MAA4wwY0wIoc0EQsgUEw0kQM8IcwQ8sYE48EQ0YwYAAAAAAAAYoQQsUMIssgEUkcUYAAAAAAwAQEAUIY0AEMAMIIYIwsEEAAAA0gAMAAIIEMAgEkIEUkAEUUk0Qo8oowIgEgwE4ssUEAUEAkAAEAAMoQE4UUQQggIAQE4gAAAQAwgUUA00Aw0QMg8oAEIw4sUQAAcW4IAgAUUwQwYwQsg8cAwEkYE0gs8EQ48gQkAYY8A0AAEIwUwYoAEEAAEsU0AIAUAAIYAEsAEAIAAQAAgUYQoAAAUIAUgY00MkAIMA0os0E0wAcAEI08wAYOscIgc4k8ggEgMoAAAQA4oUU8sg4EoI8goAAIc4UUMwAUsMcAIEQMoIIM84gAEUIEAIUEcYAUMcAwM4AQUAwo0QAQE4coAIkYwwwgoQc8Q0M88oM8QgAAAQEIgUwggMkgQk008Q4c8kUcggQA0AQksAQCE44ggYAAAUoYo404wQAAEAkcgMAAEAkIkMEQ4gkUocMIcU08kIMswIoYgogu0oIAQQQIo8EY8k0kwcQoY4AIwcU4ks8Mc4MM4EMsMMAgWAgIkU0EoIAAAAQAAQgAAoAQ4gAU4MgkkAM4IswgoUMIAU4kAsU8scgA4sgAAUs0oYA0IkksEQUwsU0gEAUcwo0E0s4IEEQIIoc0ssgooYIMIEwc8k8gAAAAA4EQQAkM0IA4Y40AAEcI4gkcwIowwIg8sUIAEoMEMAUuIcUQA4YMEA88w8w4kIUcoOYIQwAEM0AEgMEwIQQAUUgQ0IAUYwgAAAAAEMMAgEkMUc0cwAYAEEIcwQkcoAYgQgU48gMIAAAAA4AAQEs0YAAAAAAQ00gQ8MQIEcEAY4M84c4oAEwAAgAAUUQEYoIMkEAAAAAAAIgEkA04cAkkkggsAIEAwEogIkQkoIIYg4UIQgAA8IAAMsEIoAAEEcAAAAkIoQ4UAgAkA4QAwogYgQwAAAAAkg4kcIwMskAAAAAAAQAAkAUkksQwQsA0soIgsIYE8AIgI8kgoEEIEAAQcEEMEcYkQAAQIUAgAQQ0IYoY8E408ww40084w4008400k4ogcYA0kAAAAAAAYkEA4M4AkY0wgQyksCgE4cgg4CkwQgoAgAAYsAAE4Mgkc4AAAAAAQ0AAAAEUcswAE0AAkIkoIA0o0AAQAIAAAEoYMgMscowUAIAAgAEAQkMoQAwgwQkIEIk4IUQAEgUIwso4AAI0IAQcw4gE4oAAAAQIsogAAAAQw4gQg0McMsMIsIk4MgAAAAAAAgYkIAUw0I4kAAAAAkAwA8Io4QEo8kcYgEccs88cssM4k4YIAgQEsIAwkgMsgwAAEwkQEYwIMAAAwEoEgkIAAAAAAAAQcwww48sIE0cYQkccMMUoEAgMYYAE8QYwEcQswUAE4IAEAQAAAAMQ4kgcIgAIEAcs40cAUAQAMMAkcsQAQ4AAg84kogUAAEgIMYs4EUUwAAAAgAQowQwAAQwggwwgoAAAkA0UEA4UQAkYAA88MMM0ssMs8sgkIAA4goSIoMYcUIAUkY8sogUsk0oAwswYAoQoQgsQkIAgsYgEQgwggwAgggwAwgAAgAgAoIAQ8AAAgEQgIAAAAAk8EUAEAEIIAQAw4AcIAAAQMEw0EkAgEMMEoQEQY0gAuk4YcAEUgo480QQkw0wMAAAAIAAAAAAAAAEEAAAAQIgAUEEkIk4k8IAQwsckgQgEAk0wswMkAUQoAgQUs4Icw4AAIc0QYYUUI0AAsMmAw6gAoUEsIYsMYs4QU48w80w0wkAAgAEYsQAIEM0kYIoQoQI8yMAQAoQ44AwgAAk4AkAo4YAAAAA4Ek088kIAUgkEAQA8IcAAA88oIwwEwAAYIEokgUgYAAAAIEAAMIAAcE4ckocscwE880M8AgAMQ8gE0E8MMogAAoIogIAo4YEAAAAEwgU44IwgIcUY8g44EMAwEEowUEwEoAQso0MQ0m4MssoA88oAo4AA4E0k84cMEsAcUg4EooIMQ0oEs4YckAAIAwMEwII88oAAIAAAUUgUI0ww4AQwAwAgQEgAUUksIcoAA8YgMkkcUAokMsAQAAgQAAgA0Q8kQIUIIQwUIgIAsMIYAAAEAUIcoAAAAgA4AAU0cIAAAAAA84w8s40QgAAAAAAAAYgEkMgUMsAQokI4IYMYUsMwMEggAAMIk4YA00ogsg0EAMQUwAA0Kq3oYgAEQwkM4QIAAkkEYQI4I8AAAAAAUYYAEwQAoE4oAAEoYUog0gocMEgAoQU2AoyAsgk6s0QUYwEQQgkAgIUsI0YwgwIwokQQw3bwQIAAgAQYAUEQUgQAowwogIAAAAAAAA4QUYoWEEccIckI0AIU8ooMEEAAI0oc4ScsEQQEkQ0Mg0YcYgAAMgYqIQsAI4AIYww4w0w488w488w4804www040Y0wAAAAAAIAAUU8IE4AA8AYQkYsEIocAQcIkAAAgCYk4kIwY0KQAM0gQ4Mw0goA8o08YwUIIAAkIUAMAEEMAIAMEIIIIMMMEMAMA4IEAMEEEIAAcUgAIIAAAAIAEwUwMk8g8cwQAIIAoEg8g8kcMk44AAAAAAAAAEQAAkAwUMUkAAIs4QAAUokosIAQAAAAAEAAMMYAAEsEAg8AsIIEQAAAAsIAAAQwQYwggAAs4AAAAwgAgk440YwkwME0sck4o48o80IAIYYyUw0og0AQEAQcAwMA8AgEEEAscckA8sYIEQIAcYgYcYgkIoAAAQwMsIEMc4wAEMcwQgAAQUAAgg8kYYAEYoUAEIAAgAAU8YAAcU4IIIAgIMQY0AwOEokwQ8cv8IQ0oMY8g8M0QEQ08gEAQIIMAAAAAAAAgwIooIMQAQAAAAAAAQAQc0YMwgggA0YwUAAAAAAIgQAAQsAQMEQgQUAQYAPbgkMggwyz/4UIQkE0EBPCowogoUIMEAgAwAAAAAAAAAAA0oAEAAAAAAAAEYIA8wEAccIM80Q8MUIMIssEMwkIAgMcMAUA4gAM0UoypwcwU8c2xkkwI8QgEdSjcEIYAkkEAAgEIAAEAAAAAAgAUQAEAIAAAAAAAgAAAAAwoI0wwwwwwwwwwwwwwwwwwwwwwwwUoAAMw0AkIAgAQgQgAE8MAoAwAAAAIoEQgA4gAA4UwAEAogcIAoMAEIMAMIIQkssEAUsMAAIEQMcwsMwwogwQQYgg4wkwcAAAQgwYQAAAAEAQAgQwwAQgAQwwQQEgAAQ4gQQQgYggQEoQMwEQkM0UAI8IMw0cAg8IEIYoggAcMIE8esoUwU8EcgQsEsQQAAAAAAAQMAkgg8EAAA8oEowMI484oIYIMMgMAEck8sM8wAAAUsgAI8YgEYE0UwoQI8Q808oe4gEcwAYgwMMAUQQoAAUcok80s4AEAAIAAAIEA08kAMAAQQEIkEME4sIwAAAAAAAAAAEAAAAAAAAAAA0g0AAAAwgkM8Mk88g8csYsUAAAQ8YwAIk4koAAwAQgQAQwAwwQAQwwggAgwgQwgIwE0M0oEQoskU8coAAEAEEEIkY4QgAAAQgkioQwYIAEIUUMAAAAUMAEEAAAAAAIEIAQkUIw0EAIAAAAAAAAAAAAAEAAIAAAQUAYAAgAYAwwss4Ac84MQEs8cscIIgkw4wQQggAAwAAgEgAkIQ44MAAMMgMgYAAEskgA8UAAQkUswgAgAAAEAAAIAEIAAwAIMgoAwAAEA8EAwAkIIEM4EoAEIIEIMIMAIAU0wsw48QIAA0AAQAEYAA4AUIc0QAUY80gAIsQUk8gAAoAIUU4QwMYQUYYgYYUAgcEccMsIAAAAAQAAsAQQQIQgI0osskgEk4Q0QAEsk4c8UgMIwQAAUgAIMUggoogsIkwYgco0MgE4osAAAIoIIecIoQYEs8AgAk4MAUUsYQOkAAAAA0AA8AkMAkUUQsEA0IMgA0UwAAQAQYQAAMYoU0IowwcUQc8AUIEQAwMQAUEgogU4sUgIAAwgcgYQYo8koYIcAIcwAIcQsQc8osEAA0AEkAQUI4wUA4wcQA408QcEIgQ0MYEwg0EO8QAoEIEUY8sA0AUgQccoIswE8EkIwQQoAgIAgQ84YgcocgAwUQgYIMEsMMMcU0AAA0A4MgE4UAQA0cAEM8sssA4kEgQU0kgAAg8AAgAoAYQwgAUYoAIsswkQwgAA0wwQE8kAAAUgAAAAAgAgQAAAgAAAAows48ksYIAAgEgkEkwAMcYcowMQ0UQEcQIAIAUgMcMAAAYAoEwoAgAg8AmwAAoUUQUQQAAEUE8U8kAAAIQg4AEUIEEAIIAIQIEYA80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'

def _enviar_capa_analisador(chat_id):
    """Envia capa + texto + botões em UMA única mensagem do Telegram."""
    try:
        foto = io.BytesIO(base64.b64decode(_CAPA_ANALISADOR_B64))
        foto.name = "capa_analisador.jpg"
        return bot.send_photo(
            chat_id,
            foto,
            caption=_texto_painel_analisador(),
            reply_markup=painel_markup()
        )
    except Exception:
        traceback.print_exc()
        return None


def _editar_balao_com_capa(message, imagem_b64, nome_arquivo, legenda, markup):
    """Troca foto, legenda e botões da própria mensagem, sem criar outra bolha."""
    foto = io.BytesIO(base64.b64decode(imagem_b64))
    foto.name = nome_arquivo
    media = telebot.types.InputMediaPhoto(foto, caption=legenda)
    return bot.edit_message_media(
        media,
        chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=markup,
    )

def _texto_painel_analisador():
    return (
        "📊 ANALISADOR ESTATÍSTICO\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔎 Central de análise das rodadas mais recentes.\n\n"
        "📈 Consulte sequências, padrões, intervalos e o comportamento dos caminhos do SURF.\n\n"
        "🤖 Acesse também o BOT para configurar e acompanhar o monitoramento em tempo real.\n\n"
        "⚙️ Escolha uma função abaixo."
    )

# ==============================================================================
# TELEGRAM
# ==============================================================================

@bot.message_handler(commands=["start"])
def iniciar(message):
    print("COMANDO /START RECEBIDO")
    # /start permanece imediato: imagem, texto e botões no mesmo balão.
    _enviar_capa_analisador(message.chat.id)


@bot.message_handler(commands=["atualizar"])
def atualizar_manual(message):
    try:
        total = atualizar_historico_tipminer(forcar=True)
        bot.reply_to(
            message,
            f"✅ Histórico atualizado com sucesso.\n\n"
            f"📚 Base fixa: {total:,} rodadas."
        )
    except Exception as erro:
        bot.reply_to(
            message,
            f"❌ Falha ao atualizar o histórico.\n"
            f"Erro: {type(erro).__name__}: {str(erro)[:250]}"
        )


@bot.message_handler(commands=["painel"])
def abrir_painel(message):
    try:
        # O painel também usa o banco local para abrir imediatamente.
        total = contar_rodadas_banco()

        bot.reply_to(
            message,
            f"🎯 PAINEL DE ESTRATÉGIAS\n\n"
            f"🔥 SEQUÊNCIA CORES IGUAIS 10X\n"
            f"📊 SEQUÊNCIA DE CORES IGUAIS\n"
            f"📚 Rodadas na base fixa: {total}\n"
            f"💾 Base fixa de análise: {ANALYSIS_ROUNDS:,} rodadas\n\n"
            "Clique na estratégia para gerar o resultado:",
            reply_markup=painel_markup()
        )
    except Exception as erro:
        bot.reply_to(message, f"❌ Não consegui abrir o painel: {type(erro).__name__}")


@bot.callback_query_handler(func=lambda call: call.data in ("surfe_ocultar",))
def surfe_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        _limpar_capa_ativa(chat_id)
        ids = surfe_mensagens_abertas.pop(chat_id, [])
        surfe_cache.pop(chat_id, None)
        for message_id in ids:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
    except Exception as erro:
        traceback.print_exc()


def _abrir_ponto_surfe(chat_id, indice):
    """Abre a escolha de quantidade para qualquer ponto inicial do SURF."""
    dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
    if indice < 0 or indice >= len(dados):
        bot.send_message(chat_id, "❌ Não foi possível localizar o registro escolhido no histórico.")
        return

    rodada = dados[indice]
    cor = normalizar_cor_analise(rodada)
    numero = rodada.get("numero")
    emoji = emoji_cor(cor)
    _, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))

    estado = {
        "branco_index": indice,  # compatibilidade com o motor existente
        "ponto_index": indice,
        "ponto_cor": cor,
        "ponto_numero": numero,
        "ponto_tipo": "Branco" if cor == "Branco" else "Numero",
    }
    surfe_cache[chat_id] = estado

    if cor == "Branco":
        titulo_ponto = "⚪ BRANCO SELECIONADO"
        apos = "esse Branco"
    else:
        titulo_ponto = f"{emoji} NÚMERO {numero} SELECIONADO"
        apos = "esse número"

    explicacao = "\n".join([
        "🏄 SURFE — ANÁLISE ESTATÍSTICA",
        "",
        titulo_ponto,
        f"🕐 {hora}",
        "",
        "📊 ESCOLHA AS RODADAS",
        "",
        f"Selecione quantas rodadas após {apos}",
        "você deseja analisar no SURF.",
        "",
        "🔴 SURF 2 VERMELHOS",
        "⚫ SURF 2 PRETOS",
        "",
        "📚 Escolha uma quantidade ou analise todas as rodadas disponíveis após o ponto.",
        "",
        "👇 Escolha uma quantidade:",
    ])

    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    quantidades = (50, 99, 200, 300, 400, 500, 600, 700, 800, 900, 999)
    botoes = [
        telebot.types.InlineKeyboardButton(str(qtd), callback_data=f"surfe_qtd:{qtd}")
        for qtd in quantidades
    ]
    for pos in range(0, len(botoes), 3):
        markup.row(*botoes[pos:pos + 3])
    markup.add(
        telebot.types.InlineKeyboardButton("♾️ TODAS", callback_data="surfe_qtd:todas")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar")
    )
    m = bot.send_message(chat_id, explicacao, reply_markup=markup)
    surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_branco:"))
def surfe_branco_callback(call):
    try:
        bot.answer_callback_query(call.id)
        indice = int(call.data.split(":", 1)[1])
        dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
        if indice < 0 or indice >= len(dados) or normalizar_cor_analise(dados[indice]) != "Branco":
            bot.send_message(call.message.chat.id, "❌ Não foi possível localizar o Branco escolhido no histórico.")
            return
        _abrir_ponto_surfe(call.message.chat.id, indice)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro no SURF: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_ponto:"))
def surfe_ponto_callback(call):
    try:
        bot.answer_callback_query(call.id)
        _, indice_txt, numero_txt = call.data.split(":", 2)
        indice = int(indice_txt)
        numero = int(numero_txt)
        dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
        if indice < 0 or indice >= len(dados) or int(dados[indice].get("numero")) != numero:
            bot.send_message(call.message.chat.id, "❌ Não foi possível localizar esse número no histórico.")
            return
        _abrir_ponto_surfe(call.message.chat.id, indice)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao abrir o registro: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_qtd:"))
def surfe_quantidade_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        if estado.get("branco_index") is None:
            bot.send_message(chat_id, "❌ Escolha primeiro um ponto para iniciar o SURF.")
            return

        escolha_quantidade = call.data.split(":", 1)[1]
        if escolha_quantidade == "todas":
            analise_total = analisar_surfe_a_partir_do_branco(
                estado["branco_index"], limite=ANALYSIS_ROUNDS
            )
            if not analise_total:
                bot.send_message(chat_id, "❌ Não foi possível recuperar o ponto inicial.")
                return
            total_disponivel_todas = len(analise_total["registros"])
            if total_disponivel_todas <= 0:
                bot.send_message(chat_id, "❌ Não existem rodadas após esse ponto inicial.")
                return

            # ♾️ TODAS não despeja todo o histórico de uma vez.
            # Abre primeiro até 999 rodadas e, se houver mais, reutiliza o fluxo
            # ➕ VER MAIS 500. Cada lote de 500 é enviado em blocos naturais
            # de 100 rodadas pelo _montar_blocos_surfe().
            quantidade = min(999, total_disponivel_todas)
            estado["modo_todas"] = True
        else:
            quantidade = int(escolha_quantidade)
            if quantidade not in (50, 99, 200, 300, 400, 500, 600, 700, 800, 900, 999):
                return
            estado["modo_todas"] = False

        estado["quantidade"] = quantidade
        surfe_cache[chat_id] = estado

        # Confirma o recorte escolhido. Em ♾️ TODAS, abre primeiro até 999
        # e permite continuar no mesmo ponto em lotes de +500.
        analise = analisar_surfe_a_partir_do_branco(estado["branco_index"], limite=quantidade)
        if not analise:
            bot.send_message(chat_id, "❌ Não foi possível recuperar o ponto inicial.")
            return

        if len(analise["registros"]) < quantidade:
            disponiveis = len(analise["registros"])
            quantidade_texto = f"{quantidade:,}".replace(",", ".")
            disponiveis_texto = f"{disponiveis:,}".replace(",", ".")

            dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
            rotulo_ponto, hora_branco, emoji_ponto = _identificacao_estado_surfe(estado, dados)

            mensagem = "\n".join([
                "❌ QUANTIDADE INDISPONÍVEL",
                "",
                f"{emoji_ponto} Após o ponto selecionado existem apenas {disponiveis_texto} rodadas disponíveis.",
                "",
                f"📊 Você solicitou {quantidade_texto} rodadas, mas ainda não existem {quantidade_texto} rodadas após esse ponto.",
                "",
                "🏄 SOBRE A ANÁLISE SURF",
                "",
                "Após o ponto selecionado, serão analisados dois caminhos simultaneamente:",
                "",
                "⚫ SURFE 2 PRETOS:",
                "⚫⚫ → 🔴🔴 → ⚫⚫ → 🔴🔴...",
                "",
                "🔴 SURFE 2 VERMELHOS:",
                "🔴🔴 → ⚫⚫ → 🔴🔴 → ⚫⚫...",
                "",
                "✅ Se a cor for igual: ACERTO",
                "❌ Se for diferente: GALE 1, GALE 2, GALE 3...",
                "",
                "⚪ Os próximos Brancos não interrompem nem reiniciam o caminho.",
                "",
                f"🕐 {rotulo_ponto}: {hora_branco}",
                "",
                f"💡 Você pode escolher outra quantidade ou analisar agora todas as {disponiveis_texto} rodadas disponíveis.",
                "",
                "👇 Clique abaixo para continuar:",
            ])

            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            if disponiveis > 0:
                markup.add(
                    telebot.types.InlineKeyboardButton(
                        f"👁️ VER {disponiveis_texto} RODADAS DISPONÍVEIS",
                        callback_data=f"surfe_disponiveis:{disponiveis}"
                    )
                )
            markup.add(
                telebot.types.InlineKeyboardButton(
                    "🔽 OCULTAR SURF", callback_data="surfe_ocultar"
                )
            )
            m = bot.send_message(chat_id, mensagem, reply_markup=markup)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            return

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("👁️ VER SURFE", callback_data="surfe_ver"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
        rotulo_ponto, hora_branco, emoji_ponto = _identificacao_estado_surfe(estado, dados)
        quantidade_texto = f"{quantidade:,}".replace(",", ".")
        explicacao = "\n".join([
            "🏄 SURFE — ANÁLISE ESTATÍSTICA",
            "",
            f"📚 Serão analisadas as {quantidade_texto} rodadas após o ponto selecionado.",
            "",
            "📌 COMO FUNCIONA:",
            "",
            "Após o ponto selecionado, começamos dois caminhos simultaneamente:",
            "",
            "⚫ SURFE 2 PRETOS:",
            "⚫⚫ → 🔴🔴 → ⚫⚫ → 🔴🔴...",
            "",
            "🔴 SURFE 2 VERMELHOS:",
            "🔴🔴 → ⚫⚫ → 🔴🔴 → ⚫⚫...",
            "",
            "A cada rodada, comparamos a cor que realmente",
            "saiu com a cor que cada SURFE teria jogado.",
            "",
            "✅ Se a cor for igual: ACERTO",
            "❌ Se for diferente: GALE 1, GALE 2, GALE 3...",
            "O Gale continua aumentando até acertar.",
            "",
            "⚪ Os Brancos seguintes não interrompem",
            "nem reiniciam o caminho. A análise continua",
            f"normalmente até completar as {quantidade_texto} rodadas.",
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"🕐 {rotulo_ponto}: {hora_branco}",
            "",
            (
                "👇 Clique abaixo para visualizar as rodadas:"
                if estado.get("modo_todas")
                else f"👇 Clique abaixo para visualizar as {quantidade_texto} rodadas:"
            ),
        ])
        m = bot.send_message(chat_id, explicacao, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_disponiveis:"))
def surfe_disponiveis_callback(call):
    try:
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        if estado.get("branco_index") is None:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "❌ Escolha primeiro um ponto para iniciar o SURF.")
            return

        disponiveis = int(call.data.split(":", 1)[1])
        if disponiveis <= 0:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "❌ Não existem rodadas disponíveis após esse ponto.")
            return

        # Usa exatamente todas as rodadas disponíveis após o Branco selecionado.
        estado["quantidade"] = disponiveis
        surfe_cache[chat_id] = estado

        # Reaproveita o mesmo fluxo já usado pelo botão VER SURFE.
        surfe_ver_callback(call)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "surfe_ver")
def surfe_ver_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")
        quantidade = estado.get("quantidade")

        if indice is None:
            bot.send_message(chat_id, "❌ Escolha primeiro um ponto para iniciar o SURF.")
            return

        if quantidade is None:
            bot.send_message(chat_id, "❌ Escolha primeiro a quantidade de rodadas.")
            return

        analise = analisar_surfe_a_partir_do_branco(indice, limite=quantidade)
        if not analise:
            bot.send_message(chat_id, "❌ Não foi possível recuperar o ponto inicial.")
            return

        if len(analise["registros"]) < quantidade:
            disponiveis = len(analise["registros"])
            quantidade_texto = f"{quantidade:,}".replace(",", ".")
            disponiveis_texto = f"{disponiveis:,}".replace(",", ".")

            dados = list(reversed(obter_historico_banco(limite=ANALYSIS_ROUNDS)))
            rotulo_ponto, hora_branco, emoji_ponto = _identificacao_estado_surfe(estado, dados)

            mensagem = "\n".join([
                "❌ QUANTIDADE INDISPONÍVEL",
                "",
                f"{emoji_ponto} Após o ponto selecionado existem apenas {disponiveis_texto} rodadas disponíveis.",
                "",
                f"📊 Você solicitou {quantidade_texto} rodadas, mas ainda não existem {quantidade_texto} rodadas após esse ponto.",
                "",
                "🏄 SOBRE A ANÁLISE SURF",
                "",
                "Após o ponto selecionado, serão analisados dois caminhos simultaneamente:",
                "",
                "⚫ SURFE 2 PRETOS:",
                "⚫⚫ → 🔴🔴 → ⚫⚫ → 🔴🔴...",
                "",
                "🔴 SURFE 2 VERMELHOS:",
                "🔴🔴 → ⚫⚫ → 🔴🔴 → ⚫⚫...",
                "",
                "✅ Se a cor for igual: ACERTO",
                "❌ Se for diferente: GALE 1, GALE 2, GALE 3...",
                "",
                "⚪ Os próximos Brancos não interrompem nem reiniciam o caminho.",
                "",
                f"🕐 {rotulo_ponto}: {hora_branco}",
                "",
                f"💡 Você pode escolher outra quantidade ou analisar agora todas as {disponiveis_texto} rodadas disponíveis.",
                "",
                "👇 Clique abaixo para continuar:",
            ])

            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            if disponiveis > 0:
                markup.add(
                    telebot.types.InlineKeyboardButton(
                        f"👁️ VER {disponiveis_texto} RODADAS DISPONÍVEIS",
                        callback_data=f"surfe_disponiveis:{disponiveis}"
                    )
                )
            markup.add(
                telebot.types.InlineKeyboardButton(
                    "🔽 OCULTAR SURF", callback_data="surfe_ocultar"
                )
            )

            m = bot.send_message(chat_id, mensagem, reply_markup=markup)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            return

        # Guarda exatamente o mesmo recorte que acabou de ser exibido no SURF.
        # A área APOSTA e a análise por gatilho reutilizam este resultado, evitando
        # reconstruir o Branco por uma posição que pode mudar na janela móvel.
        estado["ultima_analise"] = analise
        surfe_cache[chat_id] = estado

        resultado = montar_resultado_surfe(analise)

        # Cabeçalho e estatística continuam separados.
        # As rodadas agora são enviadas em blocos naturais:
        # 01–99, 100–199, 200–299 ... sem corte por caracteres.
        partes = resultado.split("§§§SURF_RODADAS§§§", 1)
        mensagem_cabecalho = partes[0].strip()
        restante = partes[1] if len(partes) == 2 else ""
        partes2 = restante.split("§§§SURF_ESTATISTICA§§§", 1)
        mensagem_estatistica = partes2[1].strip() if len(partes2) == 2 else ""

        if mensagem_cabecalho:
            m = bot.send_message(chat_id, mensagem_cabecalho)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        # Repete SURF🔴 / SURF⚫ no topo de cada novo bloco.
        for bloco_rodadas in _montar_blocos_surfe(analise["registros"]):
            m = bot.send_message(chat_id, bloco_rodadas)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        # No modo TODOS/999+, o RESULTADO só aparece quando o usuário parar
        # os registros ou quando não houver mais rodadas para carregar.
        total_disponivel = len(analisar_surfe_a_partir_do_branco(indice, limite=ANALYSIS_ROUNDS)["registros"])
        consulta_expandivel = quantidade >= 999 and quantidade < total_disponivel

        if consulta_expandivel:
            estado["consulta_registros_aberta"] = True
            surfe_cache[chat_id] = estado

            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup.add(telebot.types.InlineKeyboardButton(
                "➕ VER MAIS 500", callback_data="surfe_mais_500"
            ))
            markup.add(telebot.types.InlineKeyboardButton(
                "⏹ PARAR REGISTROS", callback_data="surfe_parar_registros"
            ))
            markup.add(telebot.types.InlineKeyboardButton(
                "🔽 OCULTAR SURF", callback_data="surfe_ocultar"
            ))
            m = bot.send_message(
                chat_id,
                f"📚 {quantidade} rodadas exibidas.\n"
                "👇 Você pode carregar mais 500 ou parar aqui para ver o resultado:",
                reply_markup=markup,
            )
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            return

        estado["consulta_registros_aberta"] = False
        surfe_cache[chat_id] = estado

        if mensagem_estatistica:
            m = bot.send_message(chat_id, mensagem_estatistica)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔥 VER GALES", callback_data="surfe_gales"))
        markup.add(telebot.types.InlineKeyboardButton("🔥 GALE AVANÇADO", callback_data="surfe_gale_avancado"))
        markup.add(telebot.types.InlineKeyboardButton("💰 APOSTA", callback_data="surfe_aposta_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))

        m = bot.send_message(
            chat_id,
            f"👇 Depois das {quantidade} rodadas, você pode consultar os Gales:",
            reply_markup=markup
        )
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro no SURF: {type(erro).__name__}: {str(erro)[:250]}"
            )
        except Exception:
            pass



def _surfe_enviar_resultado_final_registros(chat_id, analise):
    """Envia o RESULTADO somente quando a consulta de registros for encerrada."""
    estado = surfe_cache.get(chat_id) or {}
    estado["ultima_analise"] = analise
    estado["consulta_registros_aberta"] = False
    surfe_cache[chat_id] = estado

    resultado = montar_resultado_surfe(analise)
    partes = resultado.split("§§§SURF_ESTATISTICA§§§", 1)
    mensagem_estatistica = partes[1].strip() if len(partes) == 2 else ""
    if mensagem_estatistica:
        m = bot.send_message(chat_id, mensagem_estatistica)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton("🔥 VER GALES", callback_data="surfe_gales"))
    markup.add(telebot.types.InlineKeyboardButton("🔥 GALE AVANÇADO", callback_data="surfe_gale_avancado"))
    markup.add(telebot.types.InlineKeyboardButton("💰 APOSTA", callback_data="surfe_aposta_menu"))
    markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))

    total_txt = f"{len(analise['registros']):,}".replace(",", ".")
    m = bot.send_message(
        chat_id,
        f"✅ Consulta de registros encerrada em {total_txt} rodadas.\n"
        "👇 Agora você pode consultar o resultado e os Gales:",
        reply_markup=markup,
    )
    surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "surfe_parar_registros")
def surfe_parar_registros_callback(call):
    try:
        bot.answer_callback_query(call.id, "Encerrando registros...")
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        if not estado.get("consulta_registros_aberta"):
            bot.send_message(chat_id, "ℹ️ Esta consulta de registros já foi encerrada.")
            return

        analise = estado.get("ultima_analise")
        if not analise:
            indice = estado.get("branco_index")
            quantidade = int(estado.get("quantidade") or 0)
            if indice is None or quantidade <= 0:
                bot.send_message(chat_id, "❌ Não encontrei uma consulta aberta para encerrar.")
                return
            analise = analisar_surfe_a_partir_do_branco(indice, limite=quantidade)

        if not analise:
            bot.send_message(chat_id, "❌ Não foi possível calcular o resultado desta consulta.")
            return

        _surfe_enviar_resultado_final_registros(chat_id, analise)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao encerrar registros: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_mais_500")
def surfe_mais_500_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")
        quantidade_atual = int(estado.get("quantidade") or 0)
        if indice is None or quantidade_atual < 999:
            bot.send_message(chat_id, "❌ Abra primeiro uma análise de 999 rodadas.")
            return
        if not estado.get("consulta_registros_aberta", True):
            bot.send_message(chat_id, "ℹ️ Esta consulta já foi encerrada. Abra uma nova análise para continuar.")
            return

        analise_total = analisar_surfe_a_partir_do_branco(indice, limite=ANALYSIS_ROUNDS)
        if not analise_total:
            bot.send_message(chat_id, "❌ Não foi possível recuperar o ponto inicial.")
            return

        total_disponivel = len(analise_total["registros"])
        novo_total = min(quantidade_atual + 500, total_disponivel)
        if novo_total <= quantidade_atual:
            bot.send_message(chat_id, "✅ Você já chegou à rodada mais recente disponível para esse ponto inicial.")
            return

        # Recalcula até o novo limite para preservar a numeração absoluta do SURF,
        # mas envia somente o novo bloco que ainda não tinha sido exibido.
        analise_nova = analisar_surfe_a_partir_do_branco(indice, limite=novo_total)
        novos_registros = analise_nova["registros"][quantidade_atual:novo_total]
        for bloco_rodadas in _montar_blocos_surfe(novos_registros):
            m = bot.send_message(chat_id, bloco_rodadas)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        estado["quantidade"] = novo_total
        estado["ultima_analise"] = analise_nova
        surfe_cache[chat_id] = estado

        atual_txt = f"{novo_total:,}".replace(",", ".")
        disponivel_txt = f"{total_disponivel:,}".replace(",", ".")
        if novo_total < total_disponivel:
            estado["consulta_registros_aberta"] = True
            surfe_cache[chat_id] = estado

            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup.add(telebot.types.InlineKeyboardButton(
                "➕ VER MAIS 500", callback_data="surfe_mais_500"
            ))
            markup.add(telebot.types.InlineKeyboardButton(
                "⏹ PARAR REGISTROS", callback_data="surfe_parar_registros"
            ))
            markup.add(telebot.types.InlineKeyboardButton(
                "🔽 OCULTAR SURF", callback_data="surfe_ocultar"
            ))
            m = bot.send_message(
                chat_id,
                f"📚 Rodadas exibidas desde o ponto inicial: {atual_txt}\n"
                f"📍 Disponíveis até a mais recente: {disponivel_txt}\n\n"
                "👇 Carregue mais 500 ou pare aqui para ver o resultado.",
                reply_markup=markup,
            )
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
        else:
            # Chegou automaticamente à rodada mais recente: não há mais o que carregar.
            estado["consulta_registros_aberta"] = False
            surfe_cache[chat_id] = estado
            m = bot.send_message(
                chat_id,
                f"📚 Rodadas exibidas desde o ponto inicial: {atual_txt}\n"
                f"📍 Você chegou à rodada mais recente disponível."
            )
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            _surfe_enviar_resultado_final_registros(chat_id, analise_nova)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao carregar mais rodadas: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass

def _formatar_reais_surfe(valor):
    valor = Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _parse_valor_aposta_surfe(texto):
    bruto = (texto or "").strip().upper().replace("R$", "").replace(" ", "")
    if not bruto:
        raise InvalidOperation
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    valor = Decimal(bruto)
    if valor <= 0:
        raise InvalidOperation
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _simular_aposta_surfe(analise, caminho, limite_gale, entrada):
    """Simula a gestão por ciclos sobre os mesmos resultados exibidos no SURF."""
    campo = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
    linhas = []
    saldo = Decimal("0.00")
    menor_saldo = Decimal("0.00")
    maior_saldo = Decimal("0.00")
    maior_drawdown = Decimal("0.00")
    maior_aposta_usada = Decimal("0.00")
    sequencia_perdas = 0
    maior_gale_usado = 0
    stops = 0
    acertos_diretos = 0
    ciclos_recuperados = 0
    rodadas_perdidas = 0
    prejuizo_stops = Decimal("0.00")

    for registro in analise["registros"]:
        resultado = registro[campo]
        aposta = entrada * (Decimal(2) ** sequencia_perdas)
        maior_aposta_usada = max(maior_aposta_usada, aposta)

        if resultado.startswith("✅"):
            # Se não havia perda anterior, foi acerto direto. Caso contrário,
            # a aposta vencedora recupera as perdas do ciclo e deixa +1 entrada.
            if sequencia_perdas == 0:
                acertos_diretos += 1
                marcador = "✅ DIRETO"
            else:
                ciclos_recuperados += 1
                marcador = f"✅ RECUPEROU G{sequencia_perdas}"
            saldo += aposta
            sequencia_perdas = 0
        else:
            rodadas_perdidas += 1
            saldo -= aposta
            sequencia_perdas += 1
            maior_gale_usado = max(maior_gale_usado, sequencia_perdas)
            marcador = f"❌ G{sequencia_perdas}"
            if sequencia_perdas >= limite_gale:
                stops += 1
                prejuizo_stops += entrada * ((Decimal(2) ** limite_gale) - Decimal(1))
                marcador += " 🛑 STOP"
                sequencia_perdas = 0

        menor_saldo = min(menor_saldo, saldo)
        maior_saldo = max(maior_saldo, saldo)
        maior_drawdown = max(maior_drawdown, maior_saldo - saldo)
        numero_texto = f"{int(registro['numero']):>3}"
        marcador_compacto = marcador
        if marcador_compacto.startswith("✅ RECUPEROU G"):
            marcador_compacto = marcador_compacto.replace("✅ RECUPEROU G", "♻️ REC.G", 1)
        elif marcador_compacto.startswith("❌ G"):
            marcador_compacto = marcador_compacto.replace("❌ G", "❌ G", 1)
        elif marcador_compacto == "✅ DIRETO":
            marcador_compacto = "✅ DIRETO"

        # Colunas compactas para leitura no Telegram.
        # Os espaços são apenas visuais e não alteram nenhum cálculo.
        marcador_coluna = f"{marcador_compacto:<15}"
        valor_coluna = _formatar_reais_surfe(aposta).replace("R$ ", "R$")
        saldo_coluna = _formatar_reais_surfe(saldo).replace("R$ ", "")
        linhas.append(
            f"{numero_texto}  {marcador_coluna} {valor_coluna:<10} {saldo_coluna}"
        )

    risco_ciclo = entrada * ((Decimal(2) ** limite_gale) - Decimal(1))
    aposta_maxima_limite = entrada * (Decimal(2) ** (limite_gale - 1))
    ciclos_para_recuperar_stop = int(risco_ciclo / entrada)
    ciclos_positivos = acertos_diretos + ciclos_recuperados
    lucro_ciclos_positivos = entrada * ciclos_positivos

    # Se a amostra terminar no meio de um Gale, esse ciclo ainda está aberto:
    # as perdas já aconteceram, mas ainda não houve acerto nem STOP.
    perda_ciclo_aberto = Decimal("0.00")
    if sequencia_perdas > 0:
        perda_ciclo_aberto = entrada * ((Decimal(2) ** sequencia_perdas) - Decimal(1))

    saldo_por_ciclos = lucro_ciclos_positivos - prejuizo_stops - perda_ciclo_aberto

    return {
        "linhas": linhas,
        "saldo": saldo,
        "saldo_por_ciclos": saldo_por_ciclos,
        "menor_saldo": menor_saldo,
        "maior_drawdown": maior_drawdown,
        "maior_aposta_usada": maior_aposta_usada,
        "aposta_maxima_limite": aposta_maxima_limite,
        "risco_ciclo": risco_ciclo,
        "ciclos_para_recuperar_stop": ciclos_para_recuperar_stop,
        "stops": stops,
        "acertos_diretos": acertos_diretos,
        "ciclos_recuperados": ciclos_recuperados,
        "ciclos_positivos": ciclos_positivos,
        "lucro_ciclos_positivos": lucro_ciclos_positivos,
        "prejuizo_stops": prejuizo_stops,
        "rodadas_perdidas": rodadas_perdidas,
        "maior_gale_usado": maior_gale_usado,
        "ciclo_aberto_gale": sequencia_perdas,
        "perda_ciclo_aberto": perda_ciclo_aberto,
    }



def _obter_analise_surfe_selecionada(chat_id):
    """Retorna o mesmo recorte exibido no SURF sempre que ele estiver em cache."""
    estado = surfe_cache.get(chat_id) or {}
    quantidade = estado.get("quantidade")
    indice = estado.get("branco_index")
    analise = estado.get("ultima_analise")

    if quantidade is None or indice is None:
        return None

    if analise and len(analise.get("registros", [])) == int(quantidade):
        return analise

    analise = analisar_surfe_a_partir_do_branco(indice, limite=quantidade)
    if analise and len(analise.get("registros", [])) == int(quantidade):
        estado["ultima_analise"] = analise
        surfe_cache[chat_id] = estado
        return analise
    return None


def _analisar_entrada_por_gatilho(analise, caminho, gatilho):
    """Cria uma nova sequência usando o Gale escolhido como gatilho de entrada."""
    campo = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
    registros = analise.get("registros", [])
    oportunidades = []

    # O gatilho aparece em uma rodada; a entrada é avaliada somente na rodada seguinte.
    for pos in range(len(registros) - 1):
        atual = registros[pos]
        resultado_atual = str(atual.get(campo, ""))
        if resultado_atual != f"❌ GALE {gatilho}":
            continue

        proxima = registros[pos + 1]
        resultado_entrada = str(proxima.get(campo, ""))
        oportunidades.append({
            "gatilho_rodada": int(atual.get("numero", pos + 1)),
            "entrada_rodada": int(proxima.get("numero", pos + 2)),
            "acertou": resultado_entrada.startswith("✅"),
            "resultado_original": resultado_entrada,
        })

    sequencia_perdas = 0
    maior_gale = 0
    gale_counts = {}
    acertos = 0
    erros = 0
    acertos_diretos = 0
    ciclos_recuperados = 0
    linhas = []

    for numero_oportunidade, item in enumerate(oportunidades, start=1):
        if item["acertou"]:
            acertos += 1
            if sequencia_perdas == 0:
                acertos_diretos += 1
                marcador = "✅ DIRETO"
            else:
                ciclos_recuperados += 1
                marcador = f"♻️ REC.G{sequencia_perdas}"
                sequencia_perdas = 0
        else:
            erros += 1
            sequencia_perdas += 1
            maior_gale = max(maior_gale, sequencia_perdas)
            gale_counts[sequencia_perdas] = gale_counts.get(sequencia_perdas, 0) + 1
            marcador = f"❌ G{sequencia_perdas}"

        # Deixa explícito o que é gatilho do SURF e o que é Gale da aposta.
        if marcador.startswith("❌ G"):
            marcador_exibicao = marcador.replace("❌ G", "❌ APOSTA G", 1)
        else:
            marcador_exibicao = marcador

        linhas.append(
            f"{numero_oportunidade:02d}  🎯 G{gatilho} na {item['gatilho_rodada']} → "
            f"💰 Entrada {item['entrada_rodada']} → {marcador_exibicao}"
        )

    total = len(oportunidades)
    taxa = (acertos / total * 100) if total else 0.0
    unidades = acertos - erros

    if total < 20:
        classificacao = "AMOSTRA PEQUENA ⚠️"
    elif unidades > 0:
        classificacao = "POSITIVA NO RECORTE ✅"
    elif unidades < 0:
        classificacao = "NEGATIVA NO RECORTE ❌"
    else:
        classificacao = "NEUTRA NO RECORTE ➖"

    return {
        "gatilho": gatilho,
        "oportunidades": oportunidades,
        "linhas": linhas,
        "total": total,
        "acertos": acertos,
        "erros": erros,
        "taxa": taxa,
        "unidades": unidades,
        "classificacao": classificacao,
        "acertos_diretos": acertos_diretos,
        "ciclos_recuperados": ciclos_recuperados,
        "maior_gale": maior_gale,
        "gale_counts": gale_counts,
        "ciclo_aberto_gale": sequencia_perdas,
    }


def _enviar_blocos_gatilho_surfe(chat_id, linhas):
    """Envia a entrada por gatilho em mensagens separadas de até 10 entradas."""
    if not linhas:
        return

    # Cada grupo de 10 entradas vira um novo balão/mensagem no Telegram.
    # Isso evita que uma sequência grande continue no mesmo balão e bata
    # no limite de caracteres da mensagem.
    for inicio in range(0, len(linhas), 10):
        bloco = linhas[inicio:inicio + 10]
        m = bot.send_message(chat_id, "\n".join(bloco))
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)


def _enviar_blocos_aposta_surfe(chat_id, linhas):
    """Envia a simulação em novos balões, com no máximo 10 entradas por mensagem."""
    if not linhas:
        return

    # Regra visual: 1–10 em um balão, 11–20 em outro, e assim por diante.
    for inicio in range(0, len(linhas), 10):
        bloco = linhas[inicio:inicio + 10]
        eh_ultimo = inicio + 10 >= len(linhas)
        markup = None
        if eh_ultimo:
            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                telebot.types.InlineKeyboardButton(
                    "⬆️ ENTENDER A SIMULAÇÃO ⬆️",
                    callback_data="surfe_aposta_simulacao_info",
                )
            )
        m = bot.send_message(chat_id, "\n".join(bloco), reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)


def _receber_valor_aposta_surfe(message):
    chat_id = message.chat.id
    estado = surfe_cache.get(chat_id) or {}
    try:
        caminho = estado.get("aposta_caminho")
        limite_gale = estado.get("aposta_limite_gale")
        indice = estado.get("branco_index")
        quantidade = estado.get("quantidade")
        if caminho not in ("Vermelho", "Preto") or not limite_gale or indice is None or not quantidade:
            bot.send_message(chat_id, "❌ A configuração da APOSTA expirou. Abra novamente o botão 💰 APOSTA.")
            return

        try:
            entrada = _parse_valor_aposta_surfe(message.text)
        except (InvalidOperation, ValueError):
            msg = bot.send_message(
                chat_id,
                "❌ Valor inválido.\n\n"
                "Digite somente o valor da aposta inicial.\n"
                "Exemplos: 0,10 | 0,20 | 1,00"
            )
            bot.register_next_step_handler(msg, _receber_valor_aposta_surfe)
            return

        analise = _obter_analise_surfe_selecionada(chat_id)
        if not analise:
            bot.send_message(chat_id, "❌ As rodadas selecionadas não estão mais disponíveis para a simulação.")
            return

        resultado = _simular_aposta_surfe(analise, caminho, int(limite_gale), entrada)
        campo_base = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
        resultados_base = [str(x.get(campo_base, "")).startswith("✅") for x in analise["registros"]]
        estado["gale_avancado_base"] = {
            "resultados": resultados_base,
            "entrada": str(entrada),
            "titulo": "💵 SIMULAÇÃO CONTÍNUA",
            "subtitulo": f"{_identificacao_ponto_surfe(analise)} {analise['data_ponto']} às {analise['hora_ponto']}",
        }
        surfe_cache[chat_id] = estado
        cor = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "2 VERMELHOS" if caminho == "Vermelho" else "2 PRETOS"

        cabecalho = "\n".join([
            f"💰 SIMULAÇÃO DE APOSTA — SURF{cor}",
            "",
            f"🏄 Caminho: SURF {nome}",
            f"📚 Rodadas: {quantidade}",
            f"{_identificacao_ponto_surfe(analise)} inicial: {analise['data_ponto']} às {analise['hora_ponto']}",
            f"💵 Entrada inicial: {_formatar_reais_surfe(entrada)}",
            f"🎯 Limite escolhido: G{limite_gale}",
            "",
            "📌 REGRA DA SIMULAÇÃO",
            "A cada perda, a próxima aposta dobra.",
            f"Se perder também no G{limite_gale}, registra STOP.",
            "Na rodada seguinte ao STOP, volta para a entrada inicial.",
            "Se acertar antes do limite, o próximo ciclo também volta para a entrada inicial.",
            "",
            "👇 Abaixo está a simulação sobre a mesma sequência de rodadas do SURF:",
        ])
        m = bot.send_message(chat_id, cabecalho)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
        _enviar_blocos_aposta_surfe(chat_id, resultado["linhas"])

        status = "POSITIVO ✅" if resultado["saldo"] > 0 else ("NEGATIVO ❌" if resultado["saldo"] < 0 else "EMPATE ➖")
        compensou = "SIM ✅" if resultado["saldo"] >= 0 else "NÃO ❌"
        maior_gale_texto = f"G{resultado['maior_gale_usado']}" if resultado["maior_gale_usado"] else "Nenhum"

        resumo_linhas = [
            "📊 RESULTADO FINANCEIRO DA SIMULAÇÃO",
            "",
            f"🏄 SURF {nome}",
            f"📚 Rodadas analisadas: {quantidade}",
            f"💵 Entrada inicial: {_formatar_reais_surfe(entrada)}",
            f"🎯 Limite escolhido: G{limite_gale}",
            "",
            "📊 RESULTADO DOS CICLOS",
            "",
            f"🟢 Acertos diretos: {resultado['acertos_diretos']}",
            f"♻️ Ciclos recuperados no Gale: {resultado['ciclos_recuperados']}",
            f"🛑 Stops no G{limite_gale}: {resultado['stops']}",
            f"💰 Ciclos positivos: {resultado['ciclos_positivos']}",
            f"💵 Lucro dos ciclos positivos: +{_formatar_reais_surfe(resultado['lucro_ciclos_positivos'])}",
            f"💸 Prejuízo total dos Stops: -{_formatar_reais_surfe(resultado['prejuizo_stops'])}",
        ]

        if resultado["ciclo_aberto_gale"] > 0:
            resumo_linhas.extend([
                f"⏳ Ciclo em aberto no final: G{resultado['ciclo_aberto_gale']}",
                f"📌 Perda já acumulada nesse ciclo: -{_formatar_reais_surfe(resultado['perda_ciclo_aberto'])}",
            ])

        resumo_linhas.extend([
            "",
            "💰 RESULTADO FINAL",
            "",
            f"📈 Saldo final: {_formatar_reais_surfe(resultado['saldo'])} — {status}",
            f"📉 Maior déficit a partir do saldo inicial: {_formatar_reais_surfe(resultado['menor_saldo'])}",
            f"📉 Maior queda a partir de um pico: {_formatar_reais_surfe(resultado['maior_drawdown'])}",
            "",
            f"🔥 Maior Gale realmente utilizado: {maior_gale_texto}",
            f"💵 Maior aposta realmente realizada: {_formatar_reais_surfe(resultado['maior_aposta_usada'])}",
            f"🎯 Maior aposta permitida no G{limite_gale}: {_formatar_reais_surfe(resultado['aposta_maxima_limite'])}",
            "",
            "♻️ RECUPERAÇÃO DAS PERDAS",
            "",
            f"🛑 Valor de 1 STOP completo no G{limite_gale}: -{_formatar_reais_surfe(resultado['risco_ciclo'])}",
            f"🎯 Para recuperar 1 STOP completo: {resultado['ciclos_para_recuperar_stop']} ciclos de +{_formatar_reais_surfe(entrada)}",
            f"📊 As sequências deste recorte compensaram as perdas no saldo final? {compensou}",
            "",
            "⚠️ Esta é uma simulação matemática baseada somente nas rodadas analisadas. Resultado passado não garante resultado futuro.",
        ])
        resumo = "\n".join(resumo_linhas)
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("⬆️ ENTENDER O RESULTADO ⬆️", callback_data="surfe_aposta_info"))
        markup.add(telebot.types.InlineKeyboardButton("💰 NOVA SIMULAÇÃO", callback_data="surfe_aposta_continua"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, resumo, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(chat_id, f"❌ Erro na simulação de APOSTA: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_simulacao_info")
def surfe_aposta_simulacao_info_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        sem_limite = (
            estado.get("gatilho_modo") == "sem_limite"
            or estado.get("aposta_modo") == "sem_limite"
        )
        linhas = [
            "ℹ️ COMO ENTENDER A SIMULAÇÃO",
            "",
            "Cada linha representa uma entrada realizada pela estratégia.",
            "",
            "❌ PERDEU",
            "A entrada perdeu. Na próxima oportunidade válida, o valor aumenta seguindo a progressão.",
            "",
            "♻️ RECUPEROU",
            "Depois de uma ou mais perdas, a entrada acertou e recuperou o ciclo. A próxima entrada volta ao valor inicial.",
            "",
            "✅ ACERTO DIRETO",
            "A entrada acertou usando o valor inicial, sem precisar de progressão.",
            "",
            "💵 VALOR DA APOSTA",
            "É o valor utilizado naquela entrada. Exemplo com R$10: R$10 → R$20 → R$40 → R$80...",
            "",
            "📊 SALDO",
            "É o lucro ou prejuízo total acumulado depois daquela entrada.",
            "",
            "📌 EXEMPLO",
            "❌  R$40,00  R$-70,00 = apostou R$40, perdeu e o saldo acumulado ficou em -R$70.",
            "♻️  R$80,00  R$10,00 = apostou R$80, recuperou o ciclo e o saldo acumulado passou para +R$10.",
        ]
        if sem_limite:
            linhas += [
                "",
                "♾️ SEM LIMITE",
                "Não existe um Gale máximo configurado para interromper a simulação. A progressão histórica continua até uma recuperação ou até terminar o recorte analisado.",
            ]
        else:
            linhas += [
                "",
                "🛑 STOP",
                "No modo COM LIMITE, aparece quando a entrada perde também no Gale definido como limite. O ciclo é encerrado e a próxima oportunidade recomeça com a entrada inicial.",
            ]
        linhas += [
            "",
            "📌 Na Entrada por Gatilho, a simulação utiliza somente as oportunidades geradas pelo gatilho escolhido.",
        ]
        m = bot.send_message(chat_id, "\n".join(linhas))
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_info")
def surfe_aposta_info_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        texto = "\n".join([
            "ℹ️ COMO ENTENDER O RESULTADO DA APOSTA",
            "",
            "🟢 ACERTOS DIRETOS",
            "São os ciclos em que a primeira aposta acertou, sem precisar entrar em Gale.",
            "",
            "♻️ CICLOS RECUPERADOS NO GALE",
            "O ciclo começou com uma ou mais perdas, mas acertou antes do limite escolhido. As apostas dobradas recuperam as perdas anteriores e deixam somente o lucro-base da entrada inicial.",
            "",
            "💰 CICLOS POSITIVOS",
            "É a soma dos acertos diretos com os ciclos recuperados no Gale. Cada ciclo positivo acrescenta o valor da entrada inicial ao resultado líquido.",
            "",
            "🛑 STOP",
            "Acontece quando a sequência perde também no Gale definido como limite. O ciclo é encerrado e a rodada seguinte volta para a aposta inicial.",
            "",
            "💸 PREJUÍZO TOTAL DOS STOPS",
            "É a soma das perdas de todos os ciclos que chegaram ao limite e não recuperaram.",
            "",
            "⏳ CICLO EM ABERTO",
            "Se as rodadas analisadas terminarem no meio de uma sequência de Gale, essas perdas já contam no saldo, mas o ciclo ainda não teve acerto nem STOP.",
            "",
            "📈 SALDO FINAL",
            "Mostra o resultado líquido real no fim do recorte: lucros dos ciclos positivos menos Stops e menos eventual ciclo ainda aberto.",
            "",
            "🔥 MAIOR GALE UTILIZADO",
            "É o maior Gale que realmente apareceu durante a simulação, mesmo que o limite escolhido fosse maior.",
            "",
            "💵 MAIOR APOSTA REALIZADA",
            "É o maior valor que realmente precisou ser apostado dentro das rodadas analisadas.",
            "",
            "📉 MAIOR DÉFICIT / MAIOR QUEDA",
            "Mostram o pior momento financeiro da simulação e ajudam a enxergar o risco, não apenas o saldo final.",
            "",
            "♻️ RECUPERAÇÃO DE 1 STOP",
            "Mostra quantos ciclos positivos, cada um com o lucro da entrada inicial, seriam necessários para compensar completamente um STOP.",
            "",
            "⚠️ A simulação usa apenas o histórico selecionado e não garante que o mesmo comportamento se repita no futuro.",
        ])
        m = bot.send_message(chat_id, texto)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_menu")
def surfe_aposta_menu_callback(call):
    """Abre o painel das análises disponíveis dentro de APOSTA."""
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        analise = _obter_analise_surfe_selecionada(chat_id)
        estado = surfe_cache.get(chat_id) or {}
        quantidade = estado.get("quantidade")
        if not analise or quantidade is None:
            bot.send_message(chat_id, "❌ Escolha primeiro o ponto inicial e a quantidade de rodadas.")
            return

        texto = "\n".join([
            "💰 APOSTA — ANÁLISES",
            "",
            f"📚 Recorte atual: {quantidade} rodadas",
            f"{_identificacao_ponto_surfe(analise)}: {analise['data_ponto']} às {analise['hora_ponto']}",
            "",
            "Escolha qual tipo de análise deseja realizar:",
            "",
            "💵 SIMULAÇÃO CONTÍNUA",
            "Aposta rodada após rodada, usando a progressão e o limite de Gale escolhidos.",
            "",
            "🎯 ENTRADA POR GATILHO",
            "Espera um Gale específico aparecer no SURF e só considera entrada na rodada seguinte.",
            "Depois o bot cria uma nova sequência somente com essas oportunidades e mede os Gales entre elas.",
            "",
            "👇 Escolha uma análise:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("💵 SIMULAÇÃO CONTÍNUA", callback_data="surfe_aposta_continua"))
        markup.add(telebot.types.InlineKeyboardButton("🎯 ENTRADA POR GATILHO", callback_data="surfe_aposta_gatilho"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro em APOSTA: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_continua")
def surfe_aposta_continua_callback(call):
    """Mantém a simulação financeira contínua já existente."""
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        quantidade = estado.get("quantidade")
        analise = _obter_analise_surfe_selecionada(chat_id)
        if quantidade is None or not analise:
            bot.send_message(chat_id, "❌ Escolha primeiro o ponto inicial e a quantidade de rodadas.")
            return

        texto = "\n".join([
            "💵 SIMULAÇÃO CONTÍNUA — SURF",
            "",
            f"📚 Esta simulação usará exatamente as mesmas {quantidade} rodadas analisadas após o ponto selecionado.",
            f"{_identificacao_ponto_surfe(analise)}: {analise['data_ponto']} às {analise['hora_ponto']}",
            "",
            "📌 COMO FUNCIONA",
            "Você escolhe qual caminho do SURF deseja testar, define até qual Gale aceita dobrar e depois informa o valor da aposta inicial.",
            "",
            "❌ A cada perda, a próxima aposta dobra.",
            "✅ Ao acertar, o próximo ciclo volta para a aposta inicial.",
            "🛑 Se perder também no limite de Gale escolhido, o sistema registra o prejuízo daquele ciclo e reinicia a rodada seguinte com a aposta inicial.",
            "",
            "📊 No final o bot calcula ganhos, perdas, quantidade de stops, maior aposta, perda máxima por ciclo, menor saldo e saldo final.",
            "",
            "🏄 ESCOLHA O SURF PARA SIMULAR",
            "🔴 SURF 2 VERMELHOS começa: 🔴🔴 → ⚫⚫ → 🔴🔴...",
            "⚫ SURF 2 PRETOS começa: ⚫⚫ → 🔴🔴 → ⚫⚫...",
            "",
            "👇 Escolha um dos caminhos:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="surfe_aposta_caminho:Vermelho"))
        markup.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="surfe_aposta_caminho:Preto"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR ÀS ANÁLISES", callback_data="surfe_aposta_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro na SIMULAÇÃO CONTÍNUA: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_aposta_gatilho")
def surfe_aposta_gatilho_callback(call):
    """Explica e inicia a análise de entrada condicionada a um Gale do SURF."""
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        quantidade = estado.get("quantidade")
        analise = _obter_analise_surfe_selecionada(chat_id)
        if quantidade is None or not analise:
            bot.send_message(chat_id, "❌ Escolha primeiro o ponto inicial e a quantidade de rodadas.")
            return

        texto = "\n".join([
            "🎯 ENTRADA POR GATILHO",
            "",
            "📖 COMO FUNCIONA",
            "",
            "Nesta análise você NÃO considera entrada em todas as rodadas.",
            "O bot primeiro acompanha normalmente o SURF escolhido.",
            "",
            "Exemplo escolhendo G3:",
            "❌ G1 → apenas observa",
            "❌ G2 → apenas observa",
            "❌ G3 → 🎯 GATILHO ATIVADO",
            "➡️ A rodada seguinte vira a entrada da análise.",
            "",
            "Se essa entrada perder, o bot não entra imediatamente de novo.",
            "Ele espera aparecer OUTRO G3 e usa a rodada seguinte como a próxima oportunidade.",
            "",
            "Assim é criada uma nova sequência somente com as entradas após o G3.",
            "O bot mede quantos acertos, erros e Gales consecutivos apareceram nessa nova sequência.",
            "",
            "📊 Também mostra a taxa histórica 1:1 e a maior sequência de perdas entre os gatilhos.",
            "⚠️ Uma amostra pequena ou um bom resultado passado não garante vantagem futura.",
            "",
            f"📚 Serão usadas exatamente as mesmas {quantidade} rodadas do SURF atual.",
            "",
            "👇 Primeiro escolha qual caminho deseja analisar:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔴 SURF 2 VERMELHOS", callback_data="surfe_gatilho_caminho:Vermelho"))
        markup.add(telebot.types.InlineKeyboardButton("⚫ SURF 2 PRETOS", callback_data="surfe_gatilho_caminho:Preto"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR ÀS ANÁLISES", callback_data="surfe_aposta_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro na ENTRADA POR GATILHO: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_caminho:"))
def surfe_gatilho_caminho_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        caminho = call.data.split(":", 1)[1]
        if caminho not in ("Vermelho", "Preto"):
            return

        estado = surfe_cache.get(chat_id) or {}
        if not _obter_analise_surfe_selecionada(chat_id):
            bot.send_message(chat_id, "❌ O recorte do SURF não está mais disponível.")
            return
        estado = surfe_cache.get(chat_id) or estado
        estado["gatilho_caminho"] = caminho
        surfe_cache[chat_id] = estado

        cor = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "2 VERMELHOS" if caminho == "Vermelho" else "2 PRETOS"
        texto = "\n".join([
            "🎯 ESCOLHA O GALE-GATILHO",
            "",
            f"🏄 Caminho: {cor} SURF {nome}",
            "",
            "O Gale escolhido será apenas o SINAL para observar uma entrada na rodada seguinte.",
            "",
            "Exemplo: escolhendo G3, toda vez que o SURF chegar ao G3, o bot confere a próxima rodada e adiciona essa oportunidade à nova sequência.",
            "",
            "👇 Escolha o gatilho que deseja estudar:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=3)
        botoes = [telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"surfe_gatilho_gale:{n}") for n in range(1, 10)]
        for pos in range(0, len(botoes), 3):
            markup.row(*botoes[pos:pos + 3])
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="surfe_aposta_gatilho"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao escolher o SURF do gatilho: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_gale:"))
def surfe_gatilho_gale_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        gatilho = int(call.data.split(":", 1)[1])
        if gatilho not in range(1, 10): return
        estado = surfe_cache.get(chat_id) or {}
        caminho = estado.get("gatilho_caminho")
        analise = _obter_analise_surfe_selecionada(chat_id)
        if caminho not in ("Vermelho", "Preto") or not analise:
            bot.send_message(chat_id, "❌ Escolha novamente o SURF e o Gale-gatilho.")
            return
        resultado = _analisar_entrada_por_gatilho(analise, caminho, gatilho)
        if not resultado["total"]:
            bot.send_message(chat_id, f"❌ Nenhuma oportunidade completa após G{gatilho} foi encontrada neste recorte.")
            return
        estado["gatilho_gale"] = gatilho
        estado["gatilho_resultado"] = resultado
        surfe_cache[chat_id] = estado
        maior = f"G{resultado['maior_gale']}" if resultado['maior_gale'] else "Nenhum"
        texto = "\n".join([
            f"🎯 GATILHO G{gatilho} — MODO FINANCEIRO", "",
            f"🔎 Oportunidades encontradas: {resultado['total']}",
            f"🔥 Maior Gale observado entre os gatilhos: {maior}", "",
            "♾️ SEM LIMITE",
            "Deixa a progressão seguir historicamente até o acerto e calcula lucro total, maior Gale solucionado, maior aposta e capital exigido no pior ciclo.", "",
            "🛑 COM LIMITE",
            "Você escolhe G1 a G9. Ao atingir o limite sem acerto, registra STOP e reinicia na próxima oportunidade do mesmo gatilho.", "",
            "👇 Escolha o modo:",
        ])
        markup=telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("♾️ SEM LIMITE", callback_data="surfe_gatilho_modo:sem_limite"))
        markup.add(telebot.types.InlineKeyboardButton("🛑 COM LIMITE", callback_data="surfe_gatilho_modo:com_limite"))
        markup.add(telebot.types.InlineKeyboardButton("🎯 TESTAR OUTRO GATILHO", callback_data=f"surfe_gatilho_caminho:{caminho}"))
        m=bot.send_message(chat_id,texto,reply_markup=markup); surfe_mensagens_abertas.setdefault(chat_id,[]).append(m.message_id)
    except Exception as erro:
        traceback.print_exc(); bot.send_message(call.message.chat.id, f"❌ Erro ao analisar gatilho: {type(erro).__name__}: {str(erro)[:200]}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_modo:"))
def surfe_gatilho_modo_callback(call):
    bot.answer_callback_query(call.id)
    chat_id=call.message.chat.id; modo=call.data.split(":",1)[1]
    estado=surfe_cache.get(chat_id) or {}; gatilho=estado.get("gatilho_gale")
    if not gatilho: bot.send_message(chat_id,"❌ Escolha novamente o Gale-gatilho."); return
    if modo=="com_limite":
        markup=telebot.types.InlineKeyboardMarkup(row_width=3)
        bs=[telebot.types.InlineKeyboardButton(f"G{n}",callback_data=f"surfe_gatilho_limite:{n}") for n in range(1,10)]
        for pos in range(0,9,3): markup.row(*bs[pos:pos+3])
        m=bot.send_message(chat_id,"🛑 LIMITE DA PROGRESSÃO ENTRE GATILHOS\n\nEscolha o Gale máximo antes de registrar STOP:",reply_markup=markup); surfe_mensagens_abertas.setdefault(chat_id,[]).append(m.message_id); return
    estado["gatilho_modo"]="sem_limite"; estado.pop("gatilho_limite",None); surfe_cache[chat_id]=estado
    msg=bot.send_message(chat_id,"💵 VALOR INICIAL — GATILHO SEM LIMITE\n\nDigite o valor da primeira aposta.\nExemplos: 0,10 | 1,00 | 10,00")
    surfe_mensagens_abertas.setdefault(chat_id,[]).append(msg.message_id); bot.register_next_step_handler(msg,_receber_valor_gatilho_surfe)

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gatilho_limite:"))
def surfe_gatilho_limite_callback(call):
    bot.answer_callback_query(call.id); chat_id=call.message.chat.id
    limite=int(call.data.split(":",1)[1]); estado=surfe_cache.get(chat_id) or {}
    estado["gatilho_modo"]="com_limite"; estado["gatilho_limite"]=limite; surfe_cache[chat_id]=estado
    msg=bot.send_message(chat_id,f"💵 VALOR INICIAL — GATILHO COM LIMITE G{limite}\n\nDigite o valor da primeira aposta:")
    surfe_mensagens_abertas.setdefault(chat_id,[]).append(msg.message_id); bot.register_next_step_handler(msg,_receber_valor_gatilho_surfe)

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_aposta_caminho:"))
def surfe_aposta_caminho_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        caminho = call.data.split(":", 1)[1]
        if caminho not in ("Vermelho", "Preto"):
            return
        estado = surfe_cache.get(chat_id) or {}
        if estado.get("branco_index") is None or estado.get("quantidade") is None:
            bot.send_message(chat_id, "❌ Escolha primeiro o ponto inicial e a quantidade de rodadas.")
            return
        estado["aposta_caminho"] = caminho
        estado.pop("aposta_limite_gale", None)
        surfe_cache[chat_id] = estado

        cor = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "2 VERMELHOS" if caminho == "Vermelho" else "2 PRETOS"
        texto = "\n".join([
            "⚙️ MODO DA SIMULAÇÃO",
            "",
            f"🏄 Escolhido: {cor} SURF {nome}",
            "",
            "♾️ SEM LIMITE",
            "A progressão histórica continua até encontrar um acerto. O resultado mostra o maior Gale solucionado, a maior aposta realizada, o capital exigido no pior ciclo e o lucro/prejuízo final.",
            "",
            "🛑 COM LIMITE",
            "Você escolhe G1 a G9. Se perder também no limite escolhido, registra STOP e o próximo ciclo volta para a entrada inicial.",
            "",
            "👇 Escolha como deseja simular:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("♾️ SEM LIMITE", callback_data="surfe_aposta_modo:sem_limite"))
        markup.add(telebot.types.InlineKeyboardButton("🛑 COM LIMITE", callback_data="surfe_aposta_modo:com_limite"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="surfe_aposta_continua"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao escolher o SURF: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass



@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_aposta_modo:"))
def surfe_aposta_modo_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        modo = call.data.split(":", 1)[1]
        estado = surfe_cache.get(chat_id) or {}
        caminho = estado.get("aposta_caminho")
        if caminho not in ("Vermelho", "Preto"):
            bot.send_message(chat_id, "❌ Escolha primeiro qual SURF deseja simular.")
            return
        if modo == "com_limite":
            texto = "🎯 LIMITE DE GALE\n\n👇 Escolha até qual Gale deseja aceitar antes do STOP:"
            markup = telebot.types.InlineKeyboardMarkup(row_width=3)
            botoes = [telebot.types.InlineKeyboardButton(f"G{n}", callback_data=f"surfe_aposta_gale:{n}") for n in range(1, 10)]
            for pos in range(0, len(botoes), 3): markup.row(*botoes[pos:pos + 3])
            markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data=f"surfe_aposta_caminho:{caminho}"))
            m = bot.send_message(chat_id, texto, reply_markup=markup)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
            return
        if modo != "sem_limite": return
        estado["aposta_modo"] = "sem_limite"
        estado.pop("aposta_limite_gale", None)
        surfe_cache[chat_id] = estado
        msg = bot.send_message(chat_id, "💵 VALOR DA APOSTA INICIAL — SEM LIMITE\n\nDigite o valor inicial.\nExemplos: 0,10 | 1,00 | 10,00\n\n♾️ O bot deixará cada progressão histórica seguir até o acerto e mostrará o maior valor necessário no recorte.")
        surfe_mensagens_abertas.setdefault(chat_id, []).append(msg.message_id)
        bot.register_next_step_handler(msg, _receber_valor_sem_limite_surfe)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao escolher modo: {type(erro).__name__}: {str(erro)[:200]}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_aposta_gale:"))
def surfe_aposta_gale_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        limite = int(call.data.split(":", 1)[1])
        if limite not in range(1, 10):
            return
        estado = surfe_cache.get(chat_id) or {}
        caminho = estado.get("aposta_caminho")
        if caminho not in ("Vermelho", "Preto"):
            bot.send_message(chat_id, "❌ Escolha primeiro qual SURF deseja simular.")
            return
        estado["aposta_limite_gale"] = limite
        surfe_cache[chat_id] = estado
        cor = "🔴" if caminho == "Vermelho" else "⚫"

        texto = "\n".join([
            "💵 VALOR DA APOSTA INICIAL",
            "",
            f"🏄 SURF escolhido: {cor}",
            f"🎯 Limite escolhido: G{limite}",
            "",
            "Agora digite quanto deseja apostar na primeira entrada.",
            "",
            "Exemplos:",
            "0,10",
            "0,20",
            "1,00",
            "",
            "📌 O sistema calculará automaticamente os valores dobrados até o limite escolhido e mostrará qual seria a maior aposta e o risco máximo do ciclo.",
            "",
            "👇 Digite o valor da entrada inicial:",
        ])
        msg = bot.send_message(chat_id, texto)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(msg.message_id)
        bot.register_next_step_handler(msg, _receber_valor_aposta_surfe)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao escolher Gale: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_gales")
def surfe_gales_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")
        quantidade = estado.get("quantidade")
        if indice is None or quantidade is None:
            bot.send_message(chat_id, "❌ Escolha primeiro o ponto inicial e a quantidade de rodadas.")
            return
        analise = analisar_surfe_a_partir_do_branco(indice, limite=quantidade)
        if not analise or len(analise["registros"]) < quantidade:
            bot.send_message(chat_id, "❌ Não há rodadas suficientes para consultar os Gales.")
            return
        texto = "\n\n".join([
            _resumo_gales_surfe(analise["stats"], "Preto", "🔥 GALES — SURF⚫"),
            _resumo_gales_surfe(analise["stats"], "Vermelho", "🔥 GALES — SURF🔴"),
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro nos GALES: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "surfe_controle")
def surfe_controle_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        estado = surfe_cache.get(chat_id) or {}
        indice = estado.get("branco_index")

        if indice is None:
            bot.send_message(
                chat_id,
                "❌ Escolha primeiro um ponto para iniciar o SURF."
            )
            return

        analise = analisar_surfe_a_partir_do_branco(indice, limite=None)
        if not analise:
            bot.send_message(
                chat_id,
                "❌ Não foi possível recuperar o ponto inicial."
            )
            return

        resultado = montar_controle_geral_surfe(analise)

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🔽 OCULTAR SURF",
                callback_data="surfe_ocultar"
            )
        )

        m = bot.send_message(chat_id, resultado, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro no CONTROLE GERAL: {type(erro).__name__}: {str(erro)[:250]}"
            )
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_caminho:"))
def surfe_caminho_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        caminho = call.data.split(":", 1)[1]

        if caminho == "Branco":
            analise = analisar_surfe_inicial()
            if not analise:
                bot.send_message(chat_id, "❌ Não encontrei nenhum ⚪ Branco nas 2.000 rodadas disponíveis mais recentes.")
                return
            msg = bot.send_message(chat_id, analise["intro"])
            surfe_mensagens_abertas.setdefault(chat_id, []).append(msg.message_id)
            brancos = analise["brancos"]
            primeiros = brancos[:10]
            if primeiros:
                msg = bot.send_message(chat_id, "⚪ PRIMEIROS 10 BRANCOS MAIS ANTIGOS", reply_markup=montar_botoes_brancos_surfe(brancos, 0, len(primeiros)))
                surfe_mensagens_abertas[chat_id].append(msg.message_id)
            if len(brancos) > 10:
                for inicio_bloco in range(10, len(brancos), 40):
                    fim_bloco = min(inicio_bloco + 40, len(brancos))
                    msg = bot.send_message(chat_id, "⚪ DEMAIS BRANCOS — DO MAIS ANTIGO AO MAIS RECENTE", reply_markup=montar_botoes_brancos_surfe(brancos, inicio_bloco, fim_bloco))
                    surfe_mensagens_abertas[chat_id].append(msg.message_id)
            msg = bot.send_message(chat_id, f"⚪ TOTAL DE BRANCOS: {len(brancos)}", reply_markup=telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar")))
            surfe_mensagens_abertas[chat_id].append(msg.message_id)
            return

        if caminho not in ("Vermelho", "Preto"):
            return
        emoji = "🔴" if caminho == "Vermelho" else "⚫"
        numeros = range(1, 8) if caminho == "Vermelho" else range(8, 15)
        faixa = "1 a 7" if caminho == "Vermelho" else "8 a 14"
        texto = "\n".join([
            f"{emoji} SURF — ESCOLHA O {caminho.upper()}",
            "",
            f"👇 Escolha abaixo o número {caminho} onde você quer iniciar o Surf.",
            "",
            f"📊 Ao escolher um número de {faixa}, o bot mostrará todos os registros desse número nas 2.000 rodadas disponíveis mais recentes.",
            "",
            "🕐 Os registros estarão organizados do mais antigo para o mais recente, para que a análise respeite a ordem real das rodadas.",
            "",
            f"💡 Você poderá escolher qualquer horário desse número para usar aquela rodada como ponto inicial do Surf.",
            "",
            f"{emoji} Selecione um número {caminho} abaixo:",
        ])
        markup = telebot.types.InlineKeyboardMarkup(row_width=4)
        botoes = [telebot.types.InlineKeyboardButton(f"{emoji} {n}", callback_data=f"surfe_numero:{n}") for n in numeros]
        for pos in range(0, len(botoes), 4):
            markup.row(*botoes[pos:pos+4])
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        msg = bot.send_message(chat_id, texto, reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(msg.message_id)
    except Exception as erro:
        traceback.print_exc()
        try: bot.send_message(call.message.chat.id, f"❌ Erro ao abrir o caminho: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception: pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_numero:"))
def surfe_numero_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        numero = int(call.data.split(":", 1)[1])
        if numero < 1 or numero > 14:
            return
        ocorrencias = obter_ocorrencias_numero_surfe(numero)
        cor = converter_cor(numero)
        emoji = emoji_cor(cor)
        if not ocorrencias:
            bot.send_message(chat_id, f"❌ Não encontrei o número {numero} nas 2.000 rodadas disponíveis mais recentes.")
            return

        intro = "\n".join([
            f"{emoji} SURF — NÚMERO {numero}",
            "",
            f"👇 Escolha abaixo uma ocorrência do número {numero} para iniciar o SURF.",
            "",
            "📚 Base: 2.000 rodadas disponíveis mais recentes.",
            "",
            "🕐 Os registros estão organizados do mais antigo para o mais recente.",
        ])
        msg = bot.send_message(chat_id, intro)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(msg.message_id)

        primeiros = ocorrencias[:10]
        if primeiros:
            msg = bot.send_message(chat_id, f"{emoji} PRIMEIROS 10 NÚMEROS {numero} MAIS ANTIGOS", reply_markup=montar_botoes_numero_surfe(ocorrencias, numero, 0, len(primeiros)))
            surfe_mensagens_abertas[chat_id].append(msg.message_id)

        if len(ocorrencias) > 10:
            for inicio_bloco in range(10, len(ocorrencias), 40):
                fim_bloco = min(inicio_bloco + 40, len(ocorrencias))
                msg = bot.send_message(chat_id, f"{emoji} DEMAIS NÚMEROS {numero} — DO MAIS ANTIGO AO MAIS RECENTE", reply_markup=montar_botoes_numero_surfe(ocorrencias, numero, inicio_bloco, fim_bloco))
                surfe_mensagens_abertas[chat_id].append(msg.message_id)

        msg = bot.send_message(chat_id, f"{emoji} TOTAL DE NÚMEROS {numero}: {len(ocorrencias)}", reply_markup=telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar")))
        surfe_mensagens_abertas[chat_id].append(msg.message_id)
    except Exception as erro:
        traceback.print_exc()
        try: bot.send_message(call.message.chat.id, f"❌ Erro ao listar o número: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception: pass


def _buscar_rodadas_recentes_alerta(limite=10):
    """Busca rodadas diretamente no /history para o monitor ao vivo."""
    headers = {
        "accept": "*/*",
        "accept-language": "pt-BR",
        "content-type": "application/json",
        "authorization": f"Bearer {TIPMINER_TOKEN}",
        "origin": "https://www.tipminer.com",
        "referer": "https://www.tipminer.com/",
        "user-agent": "Mozilla/5.0",
    }
    params = dict(TIPMINER_PARAMS)
    params["limit"] = int(limite)
    resposta = requests.get(TIPMINER_URL, params=params, headers=headers, timeout=15)
    resposta.raise_for_status()
    dados = resposta.json()
    if isinstance(dados, dict):
        for valor in dados.values():
            if isinstance(valor, list):
                dados = valor
                break
    if not isinstance(dados, list):
        return []

    rodadas = []
    vistos = set()
    for item in dados:
        rodada = normalizar_rodada_historica(item)
        if not rodada:
            continue
        rid = rodada.get("rodada_id")
        if rid in vistos:
            continue
        vistos.add(rid)
        rodadas.append(rodada)
    return sorted(rodadas, key=_ordem_temporal)


def _alertas_caminhos_ativos():
    with alertas_surfe_lock:
        modo = alertas_surfe_modo
    if modo == "Ambos":
        return ("Vermelho", "Preto")
    if modo in ("Vermelho", "Preto"):
        return (modo,)
    return ()


def _alerta_cor_jogada(caminho_nome, pos_relativa):
    bloco = ((int(pos_relativa) - 1) // 2) % 2
    if caminho_nome == "Vermelho":
        return "Vermelho" if bloco == 0 else "Preto"
    return "Preto" if bloco == 0 else "Vermelho"


def _alerta_card_bytes(tipo, gale=0):
    if tipo == "loss":
        chave = "loss"
    elif int(gale) <= 0:
        chave = "direto"
    else:
        chave = f"gale{int(gale)}"
    bio = io.BytesIO(base64.b64decode(_ALERTA_CARDS_B64[chave]))
    bio.name = f"{chave}.jpg"
    return bio



def _gatilho_nome_nivel(nivel):
    nivel = int(nivel or 0)
    return "DIRETO" if nivel <= 0 else f"GALE {nivel}"

def _gatilho_apagar_entrada_anterior():
    global alertas_gatilho_entrada_message_id
    if not alertas_gatilho_entrada_message_id:
        return
    try:
        bot.delete_message(ALERTAS_CHAT_ID, alertas_gatilho_entrada_message_id)
    except Exception:
        pass
    alertas_gatilho_entrada_message_id = None


def _gatilho_apagar_mensagem(message_id):
    if not message_id:
        return
    try:
        bot.delete_message(ALERTAS_CHAT_ID, message_id)
    except Exception:
        pass

def _gatilho_apagar_status():
    """Compatibilidade: apaga todos os avisos temporários da nova estratégia."""
    global alertas_gatilho_status_message_id
    global alertas_gatilho_espera_message_id, alertas_gatilho_chegando_message_id
    _gatilho_apagar_mensagem(alertas_gatilho_status_message_id)
    _gatilho_apagar_mensagem(alertas_gatilho_espera_message_id)
    _gatilho_apagar_mensagem(alertas_gatilho_chegando_message_id)
    alertas_gatilho_status_message_id = None
    alertas_gatilho_espera_message_id = None
    alertas_gatilho_chegando_message_id = None

def _surf_apagar_mensagem(message_id):
    if not message_id:
        return
    try:
        bot.delete_message(ALERTAS_CHAT_ID, message_id)
    except Exception:
        pass


def _surf_status_chegando(gale_atual):
    """Um único balão temporário do SURF normal é atualizado enquanto o caminho avança."""
    global alertas_surf_prealerta_message_id
    texto = f"⚠️ CAMINHO CHEGANDO\n📍 GALE ATUAL: G{int(gale_atual)}".upper()
    try:
        if alertas_surf_prealerta_message_id:
            bot.edit_message_text(texto, ALERTAS_CHAT_ID, alertas_surf_prealerta_message_id)
            return
    except Exception:
        alertas_surf_prealerta_message_id = None
    try:
        msg = bot.send_message(ALERTAS_CHAT_ID, texto)
        alertas_surf_prealerta_message_id = msg.message_id
    except Exception:
        traceback.print_exc()


def _surf_status_cancelado():
    """Transforma somente o aviso temporário em CAMINHO CANCELADO."""
    global alertas_surf_prealerta_message_id
    chat_cfg = _gattexto_chat_ativo()
    texto = _gattexto_formatar(chat_cfg, "cancelado") if chat_cfg is not None else "❌ CAMINHO CANCELADO"
    try:
        if alertas_surf_prealerta_message_id:
            bot.edit_message_text(texto, ALERTAS_CHAT_ID, alertas_surf_prealerta_message_id)
            alertas_surf_prealerta_message_id = None
            return
    except Exception:
        alertas_surf_prealerta_message_id = None
    try:
        bot.send_message(ALERTAS_CHAT_ID, texto)
    except Exception:
        traceback.print_exc()


def _surf_limpar_prealerta_confirmado():
    global alertas_surf_prealerta_message_id
    _surf_apagar_mensagem(alertas_surf_prealerta_message_id)
    alertas_surf_prealerta_message_id = None


def _surf_nome_nivel(nivel):
    nivel = int(nivel)
    return "DIRETO" if nivel == 0 else f"GALE {nivel}"


def _surf_texto_caminho(finalizar=False):
    with alertas_surfe_lock:
        itens = list(alertas_surf_caminho_resultados)
    if not itens:
        return None
    resultados = {int(n): r for n, r in itens}
    linhas = ["📊 CAMINHO DA OPERAÇÃO", ""]
    if finalizar:
        for nivel in range(0, int(ALERTAS_SURF_STOP_GALE) + 1):
            linhas.append(f"{resultados.get(nivel, '❌')} {_surf_nome_nivel(nivel)}")
    else:
        for nivel in sorted(resultados):
            linhas.append(f"{resultados[nivel]} {_surf_nome_nivel(nivel)}")
    return "\n".join(linhas)


def _surf_atualizar_caminho(nivel, resultado, finalizar=False):
    """Mantém um único CAMINHO DA OPERAÇÃO por sinal do SURF normal."""
    global alertas_surf_caminho_message_id
    nivel = int(nivel)
    with alertas_surfe_lock:
        atualizado = False
        for i, (n, _) in enumerate(alertas_surf_caminho_resultados):
            if int(n) == nivel:
                alertas_surf_caminho_resultados[i] = (nivel, resultado)
                atualizado = True
                break
        if not atualizado:
            alertas_surf_caminho_resultados.append((nivel, resultado))
        alertas_surf_caminho_resultados.sort(key=lambda x: int(x[0]))
    texto = _surf_texto_caminho(finalizar=finalizar)
    if not texto:
        return
    try:
        if alertas_surf_caminho_message_id:
            bot.edit_message_text(texto.upper(), ALERTAS_CHAT_ID, alertas_surf_caminho_message_id)
            return
    except Exception:
        alertas_surf_caminho_message_id = None
    try:
        msg = bot.send_message(ALERTAS_CHAT_ID, texto.upper())
        alertas_surf_caminho_message_id = msg.message_id
    except Exception:
        traceback.print_exc()


def _surf_enviar_placar():
    with alertas_surfe_lock:
        greens = int(alertas_surfe_stats.get("green", 0))
        loss = int(alertas_surfe_stats.get("loss", 0))
    total = greens + loss
    taxa = (greens / total * 100.0) if total else 0.0
    taxa_txt = f"{taxa:.1f}".replace(".", ",")
    chat_cfg = _gattexto_chat_ativo()
    titulo_resultado = _gattexto_modelo(chat_cfg, "resultado") if chat_cfg is not None else "📊 RESULTADO DOS SINAIS"
    bot.send_message(ALERTAS_CHAT_ID, (
        f"{titulo_resultado}\n\n"
        f"✅ GREENS: {greens}\n"
        f"❌ LOSS: {loss}\n"
        f"🎯 TOTAL DE OPERAÇÕES: {total}\n"
        f"📈 TAXA DE GREEN: {taxa_txt}%\n\n"
        "━━━━━━━━━━━━━━━━━━"
    ))


def _surf_finalizar_ciclo_visual():
    """Mantém o resultado final no canal e prepara um caminho novo."""
    global alertas_surf_caminho_message_id, alertas_surf_entrada_message_id, alertas_surf_caminho_resultados
    with alertas_surfe_lock:
        alertas_surf_caminho_resultados = []
    alertas_surf_caminho_message_id = None
    alertas_surf_entrada_message_id = None


def _gatilho_apagar_espera_e_chegando():
    """Quando o gatilho confirma, as duas mensagens temporárias somem."""
    global alertas_gatilho_espera_message_id, alertas_gatilho_chegando_message_id
    _gatilho_apagar_mensagem(alertas_gatilho_espera_message_id)
    _gatilho_apagar_mensagem(alertas_gatilho_chegando_message_id)
    alertas_gatilho_espera_message_id = None
    alertas_gatilho_chegando_message_id = None

def _gatilho_status_espera(nivel):
    """Esta mensagem permanece até o próximo gatilho realmente confirmar."""
    global alertas_gatilho_espera_message_id
    chat_cfg = _gattexto_chat_ativo()
    texto = _gattexto_formatar(
        chat_cfg, "espera",
        GALE_GATILHO=ALERTAS_SURF_GATILHO,
        PROXIMA_ENTRADA=_gatilho_nome_nivel(nivel),
    ) if chat_cfg is not None else (
        f"⏳ AGUARDANDO NOVO G{ALERTAS_SURF_GATILHO}\n"
        f"🎯 PRÓXIMA ENTRADA: {_gatilho_nome_nivel(nivel)}"
    ).upper()
    try:
        if alertas_gatilho_espera_message_id:
            bot.edit_message_text(texto, ALERTAS_CHAT_ID, alertas_gatilho_espera_message_id)
            return
    except Exception:
        alertas_gatilho_espera_message_id = None
    try:
        msg = bot.send_message(ALERTAS_CHAT_ID, texto)
        alertas_gatilho_espera_message_id = msg.message_id
    except Exception:
        traceback.print_exc()

def _gatilho_status_chegando(gale_atual):
    """Aviso curto; no GREEN APÓS LOSS desenha somente a tentativa atual."""
    global alertas_gatilho_chegando_message_id
    if ALERTAS_MODO_ESTRATEGIA == "green_apos_loss":
        linhas = [
            "🧬 PRÓXIMA OPORTUNIDADE",
            "━━━━━━━━━━━━━━━━━━",
            "",
            f"📍 TENTATIVA {green_loss_tentativa}",
            f"🔥 OBJETIVO: G{ALERTAS_SURF_GATILHO}",
            "",
        ]
        for n in range(1, int(gale_atual) + 1):
            linhas.append(f"G{n} " + ("🎯" if n >= ALERTAS_SURF_GATILHO else "❌"))
        texto = "\n".join(linhas)
    else:
        chat_cfg = _gattexto_chat_ativo()
        texto = _gattexto_formatar(chat_cfg, "chegando", GALE_ATUAL=int(gale_atual)) if chat_cfg is not None else (
            "⚠️ CAMINHO CHEGANDO\n"
            f"📍 GALE ATUAL: G{int(gale_atual)}"
        ).upper()
    try:
        if alertas_gatilho_chegando_message_id:
            bot.edit_message_text(texto, ALERTAS_CHAT_ID, alertas_gatilho_chegando_message_id)
            return
    except Exception:
        alertas_gatilho_chegando_message_id = None
    try:
        msg = bot.send_message(ALERTAS_CHAT_ID, texto)
        alertas_gatilho_chegando_message_id = msg.message_id
    except Exception:
        traceback.print_exc()

def _gatilho_status_cancelado():
    """Cancela apenas o candidato; no GREEN APÓS LOSS avança a tentativa na mesma mensagem."""
    global alertas_gatilho_chegando_message_id, green_loss_tentativa
    if ALERTAS_MODO_ESTRATEGIA == "green_apos_loss":
        texto = f"📍 TENTATIVA {green_loss_tentativa}\n\n❌ CAMINHO CANCELADO"
        green_loss_tentativa += 1
    else:
        texto = "❌ CAMINHO CANCELADO"
    try:
        if alertas_gatilho_chegando_message_id:
            bot.edit_message_text(texto, ALERTAS_CHAT_ID, alertas_gatilho_chegando_message_id)
            return
    except Exception:
        alertas_gatilho_chegando_message_id = None
    try:
        msg = bot.send_message(ALERTAS_CHAT_ID, texto)
        alertas_gatilho_chegando_message_id = msg.message_id
    except Exception:
        traceback.print_exc()

def _gatilho_texto_caminho(finalizar=False):
    with alertas_surfe_lock:
        itens = list(alertas_gatilho_caminho_resultados)

    if not itens:
        return None

    resultados = {}
    for nivel, resultado in itens:
        resultados[int(nivel)] = resultado

    chat_cfg = _gattexto_chat_ativo()
    titulo_caminho = _gattexto_modelo(chat_cfg, "caminho") if chat_cfg is not None else "📊 CAMINHO DA OPERAÇÃO"
    linhas = [
        "🎯 SURF — ENTRADA POR GATILHO",
        "",
        titulo_caminho,
        "",
    ]

    if finalizar:
        # No resultado final mostra DIRETO + todos os Gales até o limite configurado.
        for nivel in range(0, int(ALERTAS_SURF_STOP_GALE) + 1):
            resultado = resultados.get(nivel, "❌")
            linhas.append(f"{resultado} {_gatilho_nome_nivel(nivel)}")
    else:
        # Enquanto a operação está aberta, mostra somente o que já aconteceu.
        for nivel in sorted(resultados):
            linhas.append(f"{resultados[nivel]} {_gatilho_nome_nivel(nivel)}")

    return "\n".join(linhas)


def _gatilho_atualizar_caminho(nivel, resultado, finalizar=False):
    """Mantém uma única mensagem CAMINHO DA OPERAÇÃO para o ciclo atual."""
    global alertas_gatilho_caminho_message_id

    nivel = int(nivel)
    with alertas_surfe_lock:
        atualizado = False
        for i, (n, _) in enumerate(alertas_gatilho_caminho_resultados):
            if int(n) == nivel:
                alertas_gatilho_caminho_resultados[i] = (nivel, resultado)
                atualizado = True
                break
        if not atualizado:
            alertas_gatilho_caminho_resultados.append((nivel, resultado))
        alertas_gatilho_caminho_resultados.sort(key=lambda item: int(item[0]))

    texto = _gatilho_texto_caminho(finalizar=finalizar)
    if not texto:
        return

    try:
        if alertas_gatilho_caminho_message_id:
            bot.edit_message_text(
                texto.upper(),
                ALERTAS_CHAT_ID,
                alertas_gatilho_caminho_message_id,
            )
            return
    except Exception:
        alertas_gatilho_caminho_message_id = None

    try:
        msg = bot.send_message(ALERTAS_CHAT_ID, texto.upper())
        alertas_gatilho_caminho_message_id = msg.message_id
    except Exception:
        traceback.print_exc()


def _gatilho_enviar_placar(resultado):
    global alertas_gatilho_total_greens, alertas_gatilho_total_loss
    if resultado == "green":
        alertas_gatilho_total_greens += 1
    else:
        alertas_gatilho_total_loss += 1
    total = alertas_gatilho_total_greens + alertas_gatilho_total_loss
    taxa = (alertas_gatilho_total_greens / total * 100) if total else 0
    taxa_txt = f"{taxa:.1f}".replace(".", ",")
    bot.send_message(ALERTAS_CHAT_ID, (
        "📊 RESULTADO DOS SINAIS\n\n"
        f"✅ GREENS: {alertas_gatilho_total_greens}\n"
        f"❌ LOSS: {alertas_gatilho_total_loss}\n"
        f"🎯 TOTAL DE OPERAÇÕES: {total}\n"
        f"📈 TAXA DE GREEN: {taxa_txt}%\n\n"
        "━━━━━━━━━━━━━━━━━━"
    ))


def _gatilho_finalizar_ciclo_visual():
    """Deixa as mensagens finais no canal e prepara um ciclo novo."""
    global alertas_gatilho_caminho_message_id, alertas_gatilho_entrada_message_id
    global alertas_gatilho_caminho_resultados, alertas_gatilho_prealerta

    with alertas_surfe_lock:
        alertas_gatilho_caminho_resultados = []

    # Não apagamos essas mensagens no Telegram.
    # Apenas soltamos os IDs para a próxima operação criar mensagens novas.
    alertas_gatilho_caminho_message_id = None
    alertas_gatilho_entrada_message_id = None
    alertas_gatilho_prealerta = None


def _alerta_resumo_stats():
    with alertas_surfe_lock:
        st = {
            "green": alertas_surfe_stats["green"],
            "loss": alertas_surfe_stats["loss"],
            "direto": alertas_surfe_stats["direto"],
            "gales": dict(alertas_surfe_stats["gales"]),
        }
    total = st["green"] + st["loss"]
    if total <= 0:
        return "📊 RESULTADO DOS SINAIS\n✅ GREEN: 0\n🚨 LOSS: 0"

    def pct(v):
        return (v / total * 100.0) if total else 0.0

    linhas = [
        "📊 RESULTADO DOS SINAIS",
        f"✅ GREEN: {st['green']}",
        f"🚨 LOSS: {st['loss']}",
        f"🎯 Aproveitamento: {pct(st['green']):.1f}%",
        "",
        "📈 ONDE BATEU",
        f"🎯 Direto: {st['direto']} — {pct(st['direto']):.1f}%",
    ]
    for n in range(1, ALERTAS_SURF_STOP_GALE + 1):
        linhas.append(
            f"{_emoji_numero_gale(n)} Gale {n}: {st['gales'].get(n, 0)} — {pct(st['gales'].get(n, 0)):.1f}%"
        )
    linhas.append(f"🚨 LOSS: {st['loss']} — {pct(st['loss']):.1f}%")
    return "\n".join(linhas)


def _alerta_nome_surfe(caminho_nome):
    if caminho_nome == "Vermelho":
        return "🔴 SURF 2 VERMELHOS"
    return "⚫ SURF 2 PRETOS"


def _alerta_identificacao_rodada(rodada):
    data, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
    cor = normalizar_cor_analise(rodada)
    return data, hora, cor, rodada.get("numero", "?")


def _alerta_enviar_sinal(caminho_nome, ponto, gatilho, entrada_cor, chave):
    _, _, cor_ultima, numero = _alerta_identificacao_rodada(gatilho)

    with alertas_surfe_lock:
        op_atual = alertas_surfe_operacoes.get(chave) or {}
    if op_atual.get("modo") == "green_apos_loss_observacao":
        return
    if op_atual.get("modo") in ("entrada_gatilho", "green_apos_loss"):
        _gatilho_apagar_espera_e_chegando()
        _gatilho_apagar_entrada_anterior()
    with alertas_surfe_lock:
        caminho_ao_vivo_marcas[(gatilho.get("rodada_id"), caminho_nome)] = "🎯 ENTRADA"
    referencia = "BRANCO" if str(numero) == "0" else str(numero)

    registro_id = _alerta_registrar_sinal(
        origem="SURF",
        caminho_nome=caminho_nome,
        gale=ALERTAS_SURF_GATILHO,
        inicio=ponto,
        gatilho=gatilho,
    )
    if registro_id is not None:
        with alertas_surfe_lock:
            operacao = alertas_surfe_operacoes.get(chave)
            if operacao is not None:
                operacao["registro_sinal_id"] = registro_id
                alertas_surfe_operacoes[chave] = operacao

    chat_cfg = _chat_textos_ativo()
    if op_atual.get("modo") in ("entrada_gatilho", "green_apos_loss"):
        nivel = int(op_atual.get("gale_aposta", 0))
        global alertas_gatilho_entrada_message_id
        chat_gat = _gattexto_chat_ativo()
        if chat_gat is not None:
            texto_entrada = _gattexto_formatar(
                chat_gat, "entrada",
                GALE_GATILHO=ALERTAS_SURF_GATILHO,
                SURF=_alerta_nome_surfe(caminho_nome),
                NIVEL=_gatilho_nome_nivel(nivel),
                EMOJI_COR=emoji_cor(entrada_cor),
                COR=entrada_cor.upper(),
                NUMERO=referencia,
                EMOJI_ULTIMA_COR=emoji_cor(cor_ultima),
            )
        else:
            texto_entrada = "\n".join([
                "🎯 ENTRADA CONFIRMADA", "",
                f"🔥 GATILHO: G{ALERTAS_SURF_GATILHO}",
                f"🏄 {_alerta_nome_surfe(caminho_nome)}",
                f"🎯 {_gatilho_nome_nivel(nivel)}",
                f"➡️ ENTRADA PARA {emoji_cor(entrada_cor)} {entrada_cor.upper()}",
                f"📍 DEPOIS DO NÚMERO {referencia} {emoji_cor(cor_ultima)}",
            ]).upper()
        msg_entrada = bot.send_message(ALERTAS_CHAT_ID, texto_entrada)
        alertas_gatilho_entrada_message_id = msg_entrada.message_id
    else:
        global alertas_surf_entrada_message_id
        _surf_limpar_prealerta_confirmado()
        msg_entrada = bot.send_message(ALERTAS_CHAT_ID, "\n".join([
            "🎯 ENTRADA CONFIRMADA", "",
            f"🏄 {_alerta_nome_surfe(caminho_nome)}",
            f"🔥 GALE DE ATIVAÇÃO: G{ALERTAS_SURF_GATILHO}",
            f"🎯 ENTRAR: {emoji_cor(entrada_cor)} {entrada_cor.upper()}",
            (f"🎲 APÓS BRANCO ⚪" if cor_ultima == "Branco" else f"🎲 APÓS O NÚMERO: {referencia} {emoji_cor(cor_ultima)}"),
        ]).upper())
        alertas_surf_entrada_message_id = msg_entrada.message_id



def _alerta_finalizar_green(chave, operacao, rodada, gale):
    data, hora, cor, numero = _alerta_identificacao_rodada(rodada)
    with alertas_surfe_lock:
        alertas_surfe_stats["green"] += 1
        if gale == 0:
            alertas_surfe_stats["direto"] += 1
        else:
            alertas_surfe_stats["gales"][gale] = alertas_surfe_stats["gales"].get(gale, 0) + 1
        alertas_surfe_operacoes.pop(chave, None)

    onde = "DIRETO" if gale == 0 else f"G{gale}"

    if operacao.get("modo") == "green_apos_loss":
        global green_loss_contador, green_loss_fase, green_loss_tentativa
        green_loss_contador = 0; green_loss_fase = "observando"; green_loss_tentativa = 1
        bot.send_message(ALERTAS_CHAT_ID, f"✅ GREEN APÓS 2 LOSS — {onde}\n\n📡 Voltando a observar os LOSS da estratégia-base.")
        return

    if operacao.get("modo") == "entrada_gatilho":
        _gatilho_apagar_espera_e_chegando()
        _gatilho_atualizar_caminho(gale, "✅", finalizar=True)
        _alerta_atualizar_registro_sinal(
            operacao.get("registro_sinal_id"),
            f"✅ GREEN — {onde}"
        )
        _gatcfg_enviar_imagem_resultado("green", gale)
        _gatilho_enviar_placar("green")
        _relatorio_registrar("gatilho", "green", gale, ALERTAS_SURF_STOP_GALE)
        _gatilho_finalizar_ciclo_visual()
        return

    _alerta_atualizar_registro_sinal(
        operacao.get("registro_sinal_id"),
        f"✅ GREEN — {onde}"
    )
    _surf_atualizar_caminho(gale, "✅", finalizar=True)
    chat_cfg = _chat_textos_ativo()
    if chat_cfg is not None:
        _enviar_imagem_resultado(chat_cfg, "green", gale)
    else:
        bot.send_photo(ALERTAS_CHAT_ID, _alerta_card_bytes("green", gale))
    _surf_enviar_placar()
    _relatorio_registrar("surf", "green", gale, ALERTAS_SURF_STOP_GALE)
    _surf_finalizar_ciclo_visual()



def _alerta_finalizar_loss(chave, operacao, rodada):
    data, hora, cor, numero = _alerta_identificacao_rodada(rodada)
    with alertas_surfe_lock:
        alertas_surfe_stats["loss"] += 1
        alertas_surfe_operacoes.pop(chave, None)

    if operacao.get("modo") == "green_apos_loss":
        global green_loss_contador, green_loss_fase, green_loss_tentativa
        green_loss_contador = 0; green_loss_fase = "observando"; green_loss_tentativa = 1
        bot.send_message(ALERTAS_CHAT_ID, f"❌ LOSS — GREEN APÓS 2 LOSS\n🛡️ STOP G{ALERTAS_SURF_STOP_GALE}\n\n📡 Voltando a observar os LOSS da estratégia-base.")
        return

    if operacao.get("modo") == "entrada_gatilho":
        gale_loss = int(operacao.get("gale_aposta", ALERTAS_SURF_STOP_GALE))
        _gatilho_apagar_espera_e_chegando()
        _gatilho_atualizar_caminho(gale_loss, "❌", finalizar=True)
        _alerta_atualizar_registro_sinal(
            operacao.get("registro_sinal_id"),
            f"🚨 LOSS — STOP G{ALERTAS_SURF_STOP_GALE}"
        )
        _gatcfg_enviar_imagem_resultado("loss")
        _gatilho_enviar_placar("loss")
        _relatorio_registrar("gatilho", "loss", gale_loss, ALERTAS_SURF_STOP_GALE)
        _gatilho_finalizar_ciclo_visual()
        return

    _alerta_atualizar_registro_sinal(
        operacao.get("registro_sinal_id"),
        f"🚨 LOSS — STOP G{ALERTAS_SURF_STOP_GALE}"
    )
    _surf_atualizar_caminho(ALERTAS_SURF_STOP_GALE, "❌", finalizar=True)
    chat_cfg = _chat_textos_ativo()
    if chat_cfg is not None:
        _enviar_imagem_resultado(chat_cfg, "loss")
    else:
        bot.send_photo(ALERTAS_CHAT_ID, _alerta_card_bytes("loss"))
    _surf_enviar_placar()
    _relatorio_registrar("surf", "loss", ALERTAS_SURF_STOP_GALE, ALERTAS_SURF_STOP_GALE)
    _surf_finalizar_ciclo_visual()


def _alerta_processar_operacoes(rodada):
    """Processa SURF normal ou a progressão ENTRE GATILHOS."""
    global alertas_gatilho_nivel_aposta
    with alertas_surfe_lock:
        itens = list(alertas_surfe_operacoes.items())
    if not itens:
        return
    chave, operacao = itens[0]
    saiu = normalizar_cor_analise(rodada)
    gale_atual = int(operacao.get("gale_aposta", 0))
    if saiu == operacao["entrada_cor"]:
        _alerta_finalizar_green(chave, operacao, rodada, gale_atual)
        if operacao.get("modo") in ("entrada_gatilho", "green_apos_loss"):
            alertas_gatilho_nivel_aposta = 0
        return

    if operacao.get("modo") == "green_apos_loss_observacao":
        # Simula silenciosamente a estratégia-base para contar LOSS consecutivos.
        global green_loss_contador, green_loss_fase, green_loss_tentativa
        with alertas_surfe_lock:
            alertas_surfe_operacoes.pop(chave, None)
        if saiu == operacao["entrada_cor"]:
            green_loss_contador = 0
            alertas_gatilho_nivel_aposta = 0
            return
        if gale_atual >= ALERTAS_SURF_STOP_GALE:
            green_loss_contador += 1
            alertas_gatilho_nivel_aposta = 0
            if green_loss_contador >= 2:
                green_loss_fase = "entrada"
                green_loss_tentativa = 1
                bot.send_message(ALERTAS_CHAT_ID, f"🎯 2 LOSS CONSECUTIVOS CONFIRMADOS\n\n⏳ AGUARDANDO NOVO G{ALERTAS_SURF_GATILHO}...")
            return
        alertas_gatilho_nivel_aposta = gale_atual + 1
        return

    if operacao.get("modo") in ("entrada_gatilho", "green_apos_loss"):
        # Nesta modalidade uma perda NÃO gera aposta na rodada seguinte.
        # O próximo nível só será usado quando surgir OUTRO Gale-gatilho.
        with alertas_surfe_lock:
            alertas_surfe_operacoes.pop(chave, None)

        if gale_atual >= ALERTAS_SURF_STOP_GALE:
            _alerta_finalizar_loss(chave, operacao, rodada)
            alertas_gatilho_nivel_aposta = 0
            return

        _gatilho_apagar_espera_e_chegando()
        _gatilho_atualizar_caminho(gale_atual, "❌")
        alertas_gatilho_nivel_aposta = gale_atual + 1
        _gatilho_status_espera(alertas_gatilho_nivel_aposta)
        return

    if gale_atual >= ALERTAS_SURF_STOP_GALE:
        _alerta_finalizar_loss(chave, operacao, rodada)
        return
    novo_gale = gale_atual + 1
    operacao["gale_aposta"] = novo_gale
    with alertas_surfe_lock:
        if chave in alertas_surfe_operacoes:
            alertas_surfe_operacoes[chave] = operacao
    _surf_atualizar_caminho(gale_atual, "❌")


def _alerta_estado_final_caminho(dados, indice_inicio, caminho_nome):
    """Retorna o Gale atual no fim do caminho e a próxima cor do padrão SURF."""
    gale_atual = 0
    total_depois = len(dados) - indice_inicio - 1
    if total_depois <= 0:
        return 0, _alerta_cor_jogada(caminho_nome, 1)

    for pos_relativa, rodada in enumerate(dados[indice_inicio + 1:], 1):
        saiu = normalizar_cor_analise(rodada)
        jogaria = _alerta_cor_jogada(caminho_nome, pos_relativa)
        if saiu == jogaria:
            gale_atual = 0
        else:
            gale_atual += 1

    proxima_cor = _alerta_cor_jogada(caminho_nome, total_depois + 1)
    return gale_atual, proxima_cor


def _alerta_assinatura_caminho_atual(dados, indice_inicio, caminho_nome):
    """Assinatura do Gale aberto no fim do caminho, usando as rodadas reais desde o G1."""
    gale_atual = 0
    indice_g1 = None

    for pos_relativa, rodada in enumerate(dados[indice_inicio + 1:], 1):
        indice_abs = indice_inicio + pos_relativa
        saiu = normalizar_cor_analise(rodada)
        jogaria = _alerta_cor_jogada(caminho_nome, pos_relativa)

        if saiu == jogaria:
            gale_atual = 0
            indice_g1 = None
        else:
            gale_atual += 1
            if gale_atual == 1:
                indice_g1 = indice_abs

    if gale_atual <= 0 or indice_g1 is None:
        return None

    assinatura = []
    for idx_abs in range(indice_g1, len(dados)):
        r = dados[idx_abs]
        assinatura.append((
            str(r.get("rodada_id") or r.get("instant") or r.get("tempo") or ""),
            str(r.get("numero")),
            normalizar_cor_analise(r),
        ))

    return (caminho_nome, tuple(assinatura))



def _alerta_procurar_entrada_por_gatilho(dados, indice_ativacao, caminhos):
    """Fluxo visual:
    - AGUARDANDO NOVO Gx permanece após uma perda.
    - Quando um candidato se aproxima: CAMINHO CHEGANDO + Gale atual.
    - Se quebrar: CAMINHO CANCELADO; AGUARDANDO continua.
    - Se confirmar: apaga AGUARDANDO + CHEGANDO e envia ENTRADA CONFIRMADA.
    """
    global alertas_gatilho_prealerta

    ultima = dados[-1]
    alvo = int(ALERTAS_SURF_GATILHO)
    aviso_antes = int(ALERTAS_SURF_AVISO_ANTES or 0)
    aviso_inicio = max(1, alvo - aviso_antes) if aviso_antes > 0 else None

    pre = dict(alertas_gatilho_prealerta) if alertas_gatilho_prealerta else None

    # Já existe um candidato sendo acompanhado.
    if pre:
        indice_inicio = next(
            (i for i, r in enumerate(dados) if r.get("rodada_id") == pre.get("ponto_id")),
            None
        )
        if indice_inicio is None:
            alertas_gatilho_prealerta = None
            _gatilho_status_cancelado()
            return

        gale_atual, proxima_cor = _alerta_estado_final_caminho(
            dados, indice_inicio, pre["caminho"]
        )

        # O caminho que vinha chegando quebrou.
        if gale_atual == 0:
            alertas_gatilho_prealerta = None
            _gatilho_status_cancelado()
            return

        # Enquanto se aproxima, mostra somente CAMINHO CHEGANDO + Gale atual.
        if gale_atual < alvo:
            if pre.get("ultimo_gale") != gale_atual:
                pre["ultimo_gale"] = gale_atual
                alertas_gatilho_prealerta = pre
                _gatilho_status_chegando(gale_atual)
            return

        # Gatilho confirmado: a oportunidade imediatamente seguinte é a entrada.
        assinatura_unica = _alerta_assinatura_caminho_atual(
            dados, indice_inicio, pre["caminho"]
        )
        if assinatura_unica is None:
            return

        if assinatura_unica in alertas_surfe_caminhos_unicos_emitidos:
            alertas_gatilho_prealerta = None
            _gatilho_status_cancelado()
            return

        ponto = dados[indice_inicio]
        chave = ("GATILHO", pre["caminho"], ponto.get("rodada_id"), ultima.get("rodada_id"))
        modo_operacao = "entrada_gatilho"
        if ALERTAS_MODO_ESTRATEGIA == "green_apos_loss":
            modo_operacao = "green_apos_loss" if green_loss_fase == "entrada" else "green_apos_loss_observacao"
        operacao = {
            "modo": modo_operacao,
            "caminho": pre["caminho"],
            "ponto_id": ponto.get("rodada_id"),
            "gatilho_id": ultima.get("rodada_id"),
            "entrada_cor": proxima_cor,
            "gale_aposta": int(alertas_gatilho_nivel_aposta),
            "assinatura_unica": assinatura_unica,
        }

        with alertas_surfe_lock:
            if alertas_surfe_operacoes:
                return
            alertas_surfe_caminhos_unicos_emitidos.add(assinatura_unica)
            alertas_surfe_operacoes[chave] = operacao

        alertas_gatilho_prealerta = None
        _gatilho_apagar_espera_e_chegando()
        _alerta_enviar_sinal(pre["caminho"], ponto, ultima, proxima_cor, chave)
        return

    # Sem aviso prévio: o próprio Gale de ativação é acompanhado sem mensagem CAMINHO CHEGANDO.
    if aviso_antes <= 0:
        aviso_inicio = alvo

    # Ainda sem candidato: procura um caminho que chegou ao ponto de aviso.
    for caminho_nome in caminhos:
        for indice_inicio in range(indice_ativacao, len(dados) - 1):
            gale_atual, _ = _alerta_estado_final_caminho(
                dados, indice_inicio, caminho_nome
            )
            if gale_atual != aviso_inicio:
                continue

            ponto = dados[indice_inicio]
            alertas_gatilho_prealerta = {
                "caminho": caminho_nome,
                "ponto_id": ponto.get("rodada_id"),
                "ultimo_gale": gale_atual,
            }
            if aviso_antes > 0:
                _gatilho_status_chegando(gale_atual)
            return


def _alerta_procurar_novos_g9():
    """Procura o Gale configurado. O nome antigo é mantido para não mexer no restante."""
    global alertas_surfe_prealerta

    with alertas_surfe_lock:
        dados = list(alertas_surfe_historico)
        ativo = alertas_surfe_ativos
        caminhos = _alertas_caminhos_ativos()
        inicio_id = alertas_surfe_inicio_monitor_id
        tem_operacao = bool(alertas_surfe_operacoes)
        pre = dict(alertas_surfe_prealerta) if alertas_surfe_prealerta else None

    if not ativo or not inicio_id or len(dados) < 2 or tem_operacao:
        return

    indice_ativacao = next(
        (i for i, r in enumerate(dados) if r.get("rodada_id") == inicio_id),
        None
    )
    if indice_ativacao is None:
        return

    if ALERTAS_MODO_ESTRATEGIA in ("entrada_gatilho", "green_apos_loss"):
        _alerta_procurar_entrada_por_gatilho(dados, indice_ativacao, caminhos)
        return

    ultima = dados[-1]
    alvo = int(ALERTAS_SURF_GATILHO)
    aviso_antes = max(0, int(ALERTAS_SURF_AVISO_ANTES))
    gale_para_sinal = max(1, alvo - 1)
    gale_para_aviso = max(1, alvo - aviso_antes)

    # Já existe um caminho sendo acompanhado.
    if pre:
        indice_inicio = next(
            (i for i, r in enumerate(dados) if r.get("rodada_id") == pre["ponto_id"]),
            None
        )
        if indice_inicio is None:
            with alertas_surfe_lock:
                alertas_surfe_prealerta = None
            return

        gale_atual, proxima_cor = _alerta_estado_final_caminho(
            dados, indice_inicio, pre["caminho"]
        )

        # O caminho acertou antes do alvo.
        if gale_atual == 0:
            ultimo_gale = pre.get("ultimo_gale")
            with alertas_surfe_lock:
                alertas_surfe_prealerta = None

            _surf_status_cancelado()
            return

        # Chegou ao ponto em que a PRÓXIMA oportunidade é o Gale de ativação.
        if gale_atual >= gale_para_sinal:
            assinatura_unica = _alerta_assinatura_caminho_atual(
                dados, indice_inicio, pre["caminho"]
            )
            ponto = dados[indice_inicio]
            chave = (pre["caminho"], pre["ponto_id"])
            operacao = {
                "caminho": pre["caminho"],
                "ponto_id": pre["ponto_id"],
                "gatilho_id": ultima.get("rodada_id"),
                "entrada_cor": proxima_cor,
                "gale_aposta": 0,
                "assinatura_unica": assinatura_unica,
            }

            with alertas_surfe_lock:
                if alertas_surfe_operacoes:
                    return
                if assinatura_unica in alertas_surfe_caminhos_unicos_emitidos:
                    alertas_surfe_prealerta = None
                    return
                if assinatura_unica is not None:
                    alertas_surfe_caminhos_unicos_emitidos.add(assinatura_unica)
                alertas_surfe_prealerta = None
                alertas_surfe_operacoes[chave] = operacao

            _alerta_enviar_sinal(
                pre["caminho"], ponto, ultima, proxima_cor, chave
            )
            return

        # Atualização intermediária do caminho (ex.: G10 -> G11).
        ultimo_gale = int(pre.get("ultimo_gale") or 0)
        if gale_atual > ultimo_gale:
            with alertas_surfe_lock:
                if alertas_surfe_prealerta:
                    alertas_surfe_prealerta["ultimo_gale"] = gale_atual

            if aviso_antes > 0:
                with alertas_surfe_lock:
                    caminho_ao_vivo_marcas[(ultima.get("rodada_id"), pre["caminho"])] = "➡️ AVISO"
                _surf_status_chegando(gale_atual)
        return

    # Ainda não há caminho em acompanhamento.
    for caminho_nome in caminhos:
        for indice_inicio in range(indice_ativacao, len(dados) - 1):
            gale_atual, proxima_cor = _alerta_estado_final_caminho(
                dados, indice_inicio, caminho_nome
            )

            # Sem aviso prévio: sinaliza assim que a próxima oportunidade for o alvo.
            if aviso_antes == 0 and gale_atual == gale_para_sinal:
                ponto = dados[indice_inicio]
                assinatura_unica = _alerta_assinatura_caminho_atual(
                    dados, indice_inicio, caminho_nome
                )
                chave = (caminho_nome, ponto.get("rodada_id"))
                operacao = {
                    "caminho": caminho_nome,
                    "ponto_id": ponto.get("rodada_id"),
                    "gatilho_id": ultima.get("rodada_id"),
                    "entrada_cor": proxima_cor,
                    "gale_aposta": 0,
                    "assinatura_unica": assinatura_unica,
                }

                with alertas_surfe_lock:
                    if alertas_surfe_operacoes or alertas_surfe_prealerta:
                        return
                    if assinatura_unica in alertas_surfe_caminhos_unicos_emitidos:
                        continue
                    if assinatura_unica is not None:
                        alertas_surfe_caminhos_unicos_emitidos.add(assinatura_unica)
                    alertas_surfe_operacoes[chave] = operacao

                _alerta_enviar_sinal(
                    caminho_nome, ponto, ultima, proxima_cor, chave
                )
                return

            # Com aviso: começa a acompanhar no Gale configurado para o pré-alerta.
            if aviso_antes > 0 and gale_atual == gale_para_aviso:
                ponto = dados[indice_inicio]
                with alertas_surfe_lock:
                    if alertas_surfe_operacoes or alertas_surfe_prealerta:
                        return
                    alertas_surfe_prealerta = {
                        "caminho": caminho_nome,
                        "ponto_id": ponto.get("rodada_id"),
                        "ultimo_gale": gale_atual,
                    }

                with alertas_surfe_lock:
                    caminho_ao_vivo_marcas[(ultima.get("rodada_id"), caminho_nome)] = "➡️ AVISO"
                _surf_status_chegando(gale_atual)
                return


def _caminho_ao_vivo_todas_rodadas():
    """Todas as rodadas novas desde a ativação, em ordem cronológica."""
    with alertas_surfe_lock:
        dados = list(alertas_surfe_historico)
        inicio_id = alertas_surfe_inicio_monitor_id
    if not dados or not inicio_id:
        return []
    idx = next((i for i, r in enumerate(dados) if r.get("rodada_id") == inicio_id), None)
    if idx is None:
        return []
    return dados[idx + 1:]


def _caminho_ao_vivo_linha(posicao, rodada, caminho_nome, gale_anterior):
    saiu = normalizar_cor_analise(rodada)
    jogaria = _alerta_cor_jogada(caminho_nome, posicao)
    numero = rodada.get("numero")
    if saiu == jogaria:
        gale = 0
        resultado = "✅"
    else:
        gale = gale_anterior + 1
        resultado = f"❌G{gale}"

    with alertas_surfe_lock:
        marca = caminho_ao_vivo_marcas.get((rodada.get("rodada_id"), caminho_nome), "")

    # No caminho ao vivo usamos somente símbolos para não ocupar linhas extras.
    # As marcas internas antigas continuam válidas; muda apenas a apresentação.
    if "ENTRADA" in marca:
        marca_visual = "🎯"
    elif "AVISO" in marca:
        marca_visual = "⚠️"
    else:
        marca_visual = "➡️" if marca else ""
    sufixo = f"  {marca_visual}" if marca_visual else ""
    return (
        f"{posicao:>2}  {emoji_cor(saiu)}{numero} - "
        f"{emoji_cor(jogaria)}{resultado}{sufixo}"
    ), gale


def _caminho_ao_vivo_texto():
    with alertas_surfe_lock:
        ativo = alertas_surfe_ativos
        modo = alertas_surfe_modo
        dados = list(alertas_surfe_historico)
        inicio_id = alertas_surfe_inicio_monitor_id

    if not ativo:
        return (
            "📡 CAMINHO AO VIVO — SURF\n\n"
            "🔴 Monitor desativado.\n"
            "Configure e ative uma estratégia para acompanhar."
        )

    inicio = next((r for r in dados if r.get("rodada_id") == inicio_id), None)
    if inicio is None:
        return "📡 CAMINHO AO VIVO — SURF\n\n⏳ Aguardando referência inicial..."

    data_inicio, hora_inicio = formatar_data_hora(
        inicio.get("instant"), inicio.get("tempo")
    )
    cor_inicio = normalizar_cor_analise(inicio)
    numero_inicio = inicio.get("numero")

    linhas = [
        "📡 CAMINHO AO VIVO — SURF",
        "",
        "📌 IDENTIFICAÇÃO",
        "",
        "✅ Acerto do caminho",
        "❌ Gale / caminho não bateu",
        "⚠️ Aviso de aproximação",
        "🎯 Entrada confirmada",
        "➡️ Ponto acompanhado pelo bot",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🟢 INÍCIO DO CAMINHO",
        f"🎲 Rodada inicial: {emoji_cor(cor_inicio)} {numero_inicio}",
        f"📅 Data: {data_inicio}",
        f"🕐 Horário: {hora_inicio}",
        "",
    ]

    todas = _caminho_ao_vivo_todas_rodadas()
    if not todas:
        linhas.append("⏳ Aguardando a primeira rodada nova...")
        return "\n".join(linhas)

    # Calcula desde a rodada 1 para preservar o Gale correto mesmo quando
    # as primeiras linhas já tiverem sido descartadas da janela de 99.
    inicio_visivel = max(1, len(todas) - CAMINHO_AO_VIVO_LIMITE + 1)
    caminhos = _alertas_caminhos_ativos()

    if caminhos == ("Vermelho", "Preto") or caminhos == ("Preto", "Vermelho"):
        linhas += [
            "🏄 SURF ⚫ — ⚫⚫ primeiro    |    🏄 SURF 🔴 — 🔴🔴 primeiro",
            "",
        ]
        gp = gv = 0
        visiveis = []
        for posicao, rodada in enumerate(todas, 1):
            lp, gp = _caminho_ao_vivo_linha(posicao, rodada, "Preto", gp)
            lv, gv = _caminho_ao_vivo_linha(posicao, rodada, "Vermelho", gv)
            if posicao >= inicio_visivel:
                visiveis.append(f"{lp}    |    {lv}")
        linhas.extend(visiveis)
    else:
        caminho = caminhos[0] if caminhos else "Vermelho"
        linhas.append(
            "🏄 SURF ⚫ — ⚫⚫ primeiro"
            if caminho == "Preto"
            else "🏄 SURF 🔴 — 🔴🔴 primeiro"
        )
        linhas.append("")
        gale = 0
        visiveis = []
        for posicao, rodada in enumerate(todas, 1):
            linha, gale = _caminho_ao_vivo_linha(posicao, rodada, caminho, gale)
            if posicao >= inicio_visivel:
                visiveis.append(linha)
        linhas.extend(visiveis)

    linhas += [
        "",
        f"📚 Exibindo {min(len(todas), CAMINHO_AO_VIVO_LIMITE)} "
        f"das {len(todas)} rodada(s) do caminho."
    ]
    return "\n".join(linhas)


def _caminho_ao_vivo_markup():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(
            "🔄 ATUALIZAR",
            callback_data="caminho_ao_vivo_atualizar"
        )
    )
    return markup


@bot.callback_query_handler(func=lambda call: call.data == "caminho_ao_vivo")
def caminho_ao_vivo_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        _caminho_ao_vivo_texto(),
        reply_markup=_caminho_ao_vivo_markup()
    )


@bot.callback_query_handler(func=lambda call: call.data == "caminho_ao_vivo_atualizar")
def caminho_ao_vivo_atualizar_callback(call):
    bot.answer_callback_query(call.id, "🔄 Atualizado")
    try:
        bot.edit_message_text(
            _caminho_ao_vivo_texto(),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_caminho_ao_vivo_markup()
        )
    except Exception:
        pass


def _alerta_texto_status_monitor():
    """Monta um status curto sem alterar a lógica dos sinais G9."""
    with alertas_surfe_lock:
        ativo = alertas_surfe_ativos
        modo = alertas_surfe_modo
        rodada = dict(alertas_surfe_ultima_rodada_detectada) if alertas_surfe_ultima_rodada_detectada else None
        atraso = alertas_surfe_ultimo_atraso
        total_novas = alertas_surfe_total_novas
        operacoes = len(alertas_surfe_operacoes)

    nomes = {
        "Preto": "⚫ SURF 2 PRETOS",
        "Vermelho": "🔴 SURF 2 VERMELHOS",
        "Ambos": "⚫ SURF 2 PRETOS + 🔴 SURF 2 VERMELHOS",
    }
    linhas = [
        f"📡 STATUS DO MONITOR G{ALERTAS_SURF_GATILHO}",
        "",
        f"🟢 Monitor: {'ATIVO' if ativo else 'DESATIVADO'}",
        f"🏄 Modo: {nomes.get(modo, modo or 'não definido')}",
        f"🔢 Rodadas novas detectadas: {total_novas}",
        f"🎯 Sinal em andamento: {'SIM' if operacoes else 'NÃO'}",
    ]

    if rodada:
        data, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
        cor = normalizar_cor_analise(rodada)
        linhas += [
            "",
            f"🎲 Última rodada lida: {emoji_cor(cor)} {rodada.get('numero')}",
            f"📅 {data}",
            f"🕐 Horário da rodada: {hora}",
        ]
        if atraso is not None:
            linhas.append(f"⚡ Detectada em: {atraso:.1f}s após o horário da rodada")
    else:
        linhas += ["", "⏳ Aguardando a primeira rodada nova após a ativação."]

    linhas += ["", "✅ Este aviso confirma que o monitor continua funcionando."]
    return "\n".join(linhas)



def _alerta_referencia_rodada(rodada):
    """Cor + número + data/hora; referência curta para localizar nos Registros Online."""
    if not rodada:
        return "indisponível"
    data, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
    cor = normalizar_cor_analise(rodada)
    numero = rodada.get("numero", "?")
    return f"{emoji_cor(cor)} {numero} — {data} às {hora}"


def _alerta_registrar_sinal(origem, caminho_nome=None, gale=None, inicio=None, gatilho=None):
    """Registra apenas sinais realmente produzidos durante a sessão ONLINE."""
    global alertas_surfe_registro_sinais_seq
    with alertas_surfe_lock:
        if not alertas_surfe_ativos:
            return None
        alertas_surfe_registro_sinais_seq += 1
        registro_id = alertas_surfe_registro_sinais_seq
        item = {
            "id": registro_id,
            "origem": str(origem or "SURF"),
            "caminho": caminho_nome,
            "gale": gale,
            "inicio": dict(inicio) if inicio else None,
            "gatilho": dict(gatilho) if gatilho else None,
            "resultado": "⏳ EM ANDAMENTO",
        }
        alertas_surfe_registro_sinais.append(item)
        return registro_id


def _alerta_atualizar_registro_sinal(registro_id, resultado):
    if not registro_id:
        return
    with alertas_surfe_lock:
        for item in alertas_surfe_registro_sinais:
            if item.get("id") == registro_id:
                item["resultado"] = resultado
                break


def _alerta_texto_registro_online():
    """Status do monitor + últimas rodadas recebidas somente nesta sessão ONLINE."""
    with alertas_surfe_lock:
        ativo = alertas_surfe_ativos
        modo = alertas_surfe_modo
        total_novas = alertas_surfe_total_novas
        operacoes = len(alertas_surfe_operacoes)
        ultima = dict(alertas_surfe_ultima_rodada_detectada) if alertas_surfe_ultima_rodada_detectada else None
        atraso = alertas_surfe_ultimo_atraso
        rodadas = [dict(r) for r in list(alertas_surfe_registro)]

    if modo == "Ambos":
        modo_txt = "⚫ SURF 2 PRETOS + 🔴 SURF 2 VERMELHOS"
    elif modo == "Preto":
        modo_txt = "⚫ SURF 2 PRETOS"
    elif modo == "Vermelho":
        modo_txt = "🔴 SURF 2 VERMELHOS"
    else:
        modo_txt = "Não selecionado"

    linhas = [
        "📡 REGISTROS ONLINE",
        "",
        f"{'🟢 Monitor: ATIVO' if ativo else '🔴 Monitor: DESATIVADO'}",
        f"🏄 Modo: {modo_txt}",
        f"🔢 Rodadas novas detectadas: {total_novas}",
        f"🎯 Operações abertas: {operacoes}",
        "",
    ]

    if ultima:
        data, hora = formatar_data_hora(ultima.get("instant"), ultima.get("tempo"))
        cor = normalizar_cor_analise(ultima)
        numero = ultima.get("numero")
        linhas.extend([
            f"🎲 Última rodada lida: {emoji_cor(cor)} {numero}",
            f"📅 {data}",
            f"🕐 Horário da rodada: {hora}",
        ])
        if atraso is not None:
            linhas.append(f"⚡ Detectada em: {atraso:.1f}s após o horário da rodada")
        else:
            linhas.append("⚡ Detectada em: indisponível")
    else:
        linhas.append("🎲 Última rodada lida: aguardando nova rodada")

    linhas.extend([
        "",
        "✅ Este aviso confirma que o monitor continua funcionando.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🎲 ÚLTIMAS RODADAS",
        "",
    ])

    if rodadas:
        # Mais recentes primeiro para facilitar a conferência.
        for rodada in reversed(rodadas[-20:]):
            _, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
            cor = normalizar_cor_analise(rodada)
            linhas.append(f"{emoji_cor(cor)} {rodada.get('numero', '?')} — {hora}")
    else:
        linhas.append("❌ Nenhuma rodada nova registrada nesta sessão.")

    return "\n".join(linhas)


def _alerta_texto_registros_sinais(mensagem_atualizacao=None):
    """Lista somente sinais realmente emitidos durante a sessão ONLINE atual."""
    with alertas_surfe_lock:
        itens = [dict(x) for x in list(alertas_surfe_registro_sinais)]

    linhas = [
        "💾 REGISTROS DE SINAIS",
        "",
        "📌 Aqui ficam os sinais enviados pelo bot ao canal.",
        "🔎 Cada registro mostra a origem do sinal e a referência de cor, número e horário para localizar o caminho nos Registros Online.",
        "⚡ Inclui SURF e fica preparado para registros de SUPER GALE.",
        "",
    ]

    if mensagem_atualizacao:
        linhas.extend([mensagem_atualizacao, ""])

    if not itens:
        linhas.append("❌ NENHUM SINAL REGISTRADO")
        return "\n".join(linhas)

    # Mais recentes primeiro.
    for item in reversed(itens[-20:]):
        origem = item.get("origem", "SURF")
        caminho = item.get("caminho")
        gale = item.get("gale")
        resultado = item.get("resultado") or "⏳ EM ANDAMENTO"

        if origem.upper() == "SUPER GALE":
            titulo = "⚡ SUPER GALE"
        else:
            titulo = f"🏄 {_alerta_nome_surfe(caminho)}" if caminho else "🏄 SURF"

        linhas.extend([
            f"💾 SINAL #{item.get('id')}",
            titulo,
        ])
        if gale is not None:
            linhas.append(f"🔥 Gale identificado: G{gale}")
        linhas.extend([
            f"📍 Início do caminho: {_alerta_referencia_rodada(item.get('inicio'))}",
            f"🔥 Condição encontrada: {_alerta_referencia_rodada(item.get('gatilho'))}",
            f"🎯 Resultado: {resultado}",
            "──────────────",
        ])

    return "\n".join(linhas).rstrip()


def _alerta_markup_registro_online():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton(
        "🔄 ATUALIZAR REGISTROS", callback_data="atualizar_registro_alertas_surfe"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR", callback_data="menu_bot"
    ))
    return markup


def _alerta_markup_registros_sinais():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton(
        "🔄 ATUALIZAR REGISTROS", callback_data="atualizar_registro_sinais_surfe"
    ))
    markup.add(telebot.types.InlineKeyboardButton(
        "⬅️ VOLTAR", callback_data="menu_bot"
    ))
    return markup



def _alerta_enviar_status_periodico(forcar=False):
    global alertas_surfe_status_ultimo_envio
    agora = time.monotonic()
    with alertas_surfe_lock:
        if not alertas_surfe_ativos:
            return
        ultimo = alertas_surfe_status_ultimo_envio
        if not forcar and ultimo and (agora - ultimo) < ALERTAS_SURF_STATUS_INTERVALO:
            return
        alertas_surfe_status_ultimo_envio = agora
    try:
        bot.send_message(ALERTAS_CHAT_ID, _alerta_texto_status_monitor())
    except Exception as erro:
        print("ERRO AO ENVIAR STATUS DO MONITOR:", type(erro).__name__, str(erro))


def _alerta_adicionar_rodada(rodada):
    """Processa a entrada dos sinais existentes e depois atualiza os caminhos SURF."""
    global alertas_surfe_ultima_rodada_detectada, alertas_surfe_ultimo_atraso, alertas_surfe_total_novas

    # Registra o instante REAL em que o monitor enxergou a rodada nova.
    agora_utc = datetime.now(timezone.utc)
    atraso = None
    dt_rodada = _datetime_tipminer(rodada.get("instant"))
    if dt_rodada is not None:
        try:
            atraso = max(0.0, (agora_utc - dt_rodada.astimezone(timezone.utc)).total_seconds())
        except Exception:
            atraso = None
    with alertas_surfe_lock:
        alertas_surfe_ultima_rodada_detectada = dict(rodada)
        alertas_surfe_ultimo_atraso = atraso
        alertas_surfe_total_novas += 1
        alertas_surfe_registro.append(dict(rodada))

    # Primeiro: a rodada nova é a próxima aposta dos sinais que já estavam abertos.
    _alerta_processar_operacoes(rodada)

    # Depois: ela passa a fazer parte da estatística e pode completar um NOVO G9.
    rid = rodada.get("rodada_id")
    with alertas_surfe_lock:
        ids = {r.get("rodada_id") for r in alertas_surfe_historico}
        if rid not in ids:
            alertas_surfe_historico.append(rodada)
            if len(alertas_surfe_historico) > ANALYSIS_ROUNDS:
                del alertas_surfe_historico[:-ANALYSIS_ROUNDS]
        alertas_surfe_ultima_rodada_id = rid
    _alerta_procurar_novos_g9()


def _monitorar_alertas_surfe():
    """Monitora silenciosamente e só fala no canal quando há sinal/Gale/resultado."""
    global alertas_surfe_ultima_rodada_id
    while True:
        with alertas_surfe_lock:
            ativo = alertas_surfe_ativos
            ultimo_id = alertas_surfe_ultima_rodada_id
        if not ativo:
            return

        try:
            rodadas = _buscar_rodadas_recentes_alerta(limite=10)
            if rodadas:
                # Usa o horário da última rodada REAL já processada como fronteira.
                # Assim, mesmo que a API ignore o limit, mude a janela retornada ou
                # algum ID não apareça na resposta seguinte, registros antigos não
                # voltam a ser contados como rodadas novas.
                with alertas_surfe_lock:
                    ultima_processada = (
                        dict(alertas_surfe_historico[-1])
                        if alertas_surfe_historico else None
                    )
                ultimo_ts = _ordem_temporal(ultima_processada) if ultima_processada else 0.0
                novas = [r for r in rodadas if _ordem_temporal(r) > ultimo_ts]
                novas = sorted(novas, key=_ordem_temporal)

                for rodada in novas:
                    with alertas_surfe_lock:
                        if not alertas_surfe_ativos:
                            return
                    _alerta_adicionar_rodada(rodada)
        except Exception as erro:
            print("ERRO NO MONITOR DE ALERTAS SURF:", type(erro).__name__, str(erro))

        # A cada 30 minutos envia um pequeno heartbeat para o canal.
        # Assim sabemos que o monitor está vivo mesmo se nenhum caminho chegar ao G9.
        _alerta_enviar_status_periodico()
        time.sleep(ALERTAS_SURF_INTERVALO)


def _iniciar_monitor_alertas_surfe(modo):
    """Carrega as 2.000 rodadas, escolhe o(s) SURF(s) e inicia o monitor."""
    global alertas_surfe_thread, alertas_surfe_ultima_rodada_id, alertas_surfe_modo
    global alertas_surfe_historico, alertas_surfe_operacoes, alertas_surfe_sinais_emitidos
    global alertas_surfe_caminhos_unicos_emitidos
    global alertas_surfe_inicio_monitor_id, alertas_surfe_prealerta, alertas_surfe_registro
    global alertas_surfe_stats
    global alertas_surfe_status_ultimo_envio, alertas_surfe_ultima_rodada_detectada
    global alertas_surfe_ultimo_atraso, alertas_surfe_total_novas
    global alertas_surfe_registro_sinais, alertas_surfe_registro_sinais_seq
    global alertas_surfe_registro_sinais_vistos_chat

    rodadas = _buscar_rodadas_recentes_alerta(limite=ANALYSIS_ROUNDS)
    if not rodadas:
        raise RuntimeError("TipMiner não retornou histórico para iniciar os alertas.")

    referencia = rodadas[-1].get("rodada_id")
    with alertas_surfe_lock:
        alertas_surfe_modo = modo
        alertas_surfe_historico = list(rodadas[-ANALYSIS_ROUNDS:])
        alertas_surfe_ultima_rodada_id = referencia
        alertas_surfe_operacoes = {}
        alertas_surfe_sinais_emitidos = set()
        alertas_surfe_caminhos_unicos_emitidos = set()
        alertas_surfe_inicio_monitor_id = referencia
        alertas_surfe_prealerta = None
        alertas_surfe_registro.clear()
        alertas_surfe_registro_sinais.clear()
        alertas_surfe_registro_sinais_seq = 0
        alertas_surfe_registro_sinais_vistos_chat.clear()
        alertas_surfe_stats = {
            "green": 0,
            "loss": 0,
            "direto": 0,
            "gales": {n: 0 for n in range(1, ALERTAS_SURF_STOP_GALE + 1)},
        }
        alertas_surfe_status_ultimo_envio = time.monotonic()
        alertas_surfe_ultima_rodada_detectada = None
        alertas_surfe_ultimo_atraso = None
        alertas_surfe_total_novas = 0

        if alertas_surfe_thread is None or not alertas_surfe_thread.is_alive():
            alertas_surfe_thread = threading.Thread(
                target=_monitorar_alertas_surfe,
                name="alertas-surfe",
                daemon=True,
            )
            alertas_surfe_thread.start()

    # Começa ao vivo na rodada mais recente; não dispara sinais antigos.

def _datetime_tipminer(valor):
    if not valor:
        return None
    try:
        texto = str(valor)
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        dt = datetime.fromisoformat(texto)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@bot.callback_query_handler(func=lambda call: call.data == "testar_rodada_ao_vivo")
def testar_rodada_ao_vivo_callback(call):
    try:
        bot.answer_callback_query(call.id, "Consultando TipMiner diretamente...")

        inicio_consulta = datetime.now(timezone.utc)
        dados = buscar_historico_tipminer()
        fim_consulta = datetime.now(timezone.utc)

        if not dados:
            bot.send_message(call.message.chat.id, "❌ TipMiner não retornou rodadas no teste direto.")
            return

        rodadas = []
        for item in dados:
            rodada = normalizar_rodada_historica(item)
            if rodada:
                rodadas.append(rodada)

        if not rodadas:
            bot.send_message(call.message.chat.id, "❌ Nenhuma rodada válida retornada pela TipMiner.")
            return

        # O teste não usa PostgreSQL nem o histórico já carregado do bot.
        # Escolhe pela data/hora para não depender da ordem do JSON.
        mais_recente = max(rodadas, key=_ordem_temporal)
        dt_rodada = _datetime_tipminer(mais_recente.get("instant"))
        fuso_sp = timezone(timedelta(hours=-3))
        agora_sp = fim_consulta.astimezone(fuso_sp)

        data_rodada, hora_rodada = formatar_data_hora(
            mais_recente.get("instant"), mais_recente.get("tempo")
        )
        cor = mais_recente.get("resultado")
        numero = mais_recente.get("numero")

        if dt_rodada is not None:
            atraso = max(0.0, (fim_consulta - dt_rodada.astimezone(timezone.utc)).total_seconds())
            atraso_txt = f"{atraso:.1f}s"
        else:
            atraso_txt = "indisponível"

        duracao = (fim_consulta - inicio_consulta).total_seconds()

        bot.send_message(
            call.message.chat.id,
            "📡 TESTE TIPMINER DIRETO\n\n"
            f"🎲 Mais recente: {emoji_cor(cor)} {numero}\n"
            f"📅 Data da rodada: {data_rodada}\n"
            f"🕐 Horário TipMiner: {hora_rodada}\n"
            f"🤖 Horário da consulta: {agora_sp.strftime('%H:%M:%S')}\n"
            f"⚡ Diferença rodada → bot: {atraso_txt}\n"
            f"🌐 Tempo da requisição: {duracao:.2f}s\n\n"
            "✅ Consulta feita DIRETAMENTE no /history da TipMiner.\n"
            "🚫 PostgreSQL não foi usado neste teste."
        )
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro no teste direto: {type(erro).__name__}: {str(erro)[:250]}"
            )
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "configurar_estrategia")
def configurar_estrategia_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        # O painel BOT é uma mensagem com foto. O Telegram não permite
        # edit_message_text diretamente em uma mensagem de mídia.
        # Ao entrar na configuração, removemos somente essa bolha e abrimos
        # o seletor em texto; daí os submenus existentes continuam funcionando.
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(
            chat_id,
            _texto_seletor_estrategia_bot(),
            reply_markup=_seletor_estrategia_bot_markup(),
        )
    except Exception:
        traceback.print_exc()

@bot.callback_query_handler(func=lambda call: call.data == "config_modo_surf_normal")
def config_modo_surf_normal_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        bot.edit_message_text(
            _texto_configurar_estrategia(chat_id),
            chat_id,
            call.message.message_id,
            reply_markup=configurar_estrategia_markup(chat_id),
        )
    except Exception:
        traceback.print_exc()




def _teste_enviar_imagem(chat_id, chave, gale=None):
    cfg = _textos_canal_cfg(chat_id)

    if chave == "green":
        chave_gale = str(int(gale or 0))
        imagem = cfg.get("green_imagens", {}).get(chave_gale)
        if imagem is None:
            imagem = cfg.get("green_imagem")
    else:
        imagem = cfg.get("loss_imagem")

    if imagem:
        if imagem["tipo"] == "document":
            bot.send_document(ALERTAS_CHAT_ID, imagem["file_id"])
        else:
            bot.send_photo(ALERTAS_CHAT_ID, imagem["file_id"])
    else:
        if chave == "green":
            bot.send_photo(ALERTAS_CHAT_ID, _alerta_card_bytes("green", gale))
        else:
            bot.send_photo(ALERTAS_CHAT_ID, _alerta_card_bytes("loss"))

def _teste_registro_operacao(resultado, entrada, confirmacao, hora="22:52"):
    linhas = [
        "📊 REGISTRO DA OPERAÇÃO",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"🎲 ENTRADA: {entrada}",
        f"🎯 CONFIRMAÇÃO: {confirmacao}",
        f"🏁 RESULTADO: {resultado}",
        f"🕐 HORÁRIO: {hora}",
    ]
    return "\n".join(linhas).upper()

def _executar_teste_textos_canal(chat_id):
    # Somente apresentação: não ativa monitor, não cria operação e não altera estatísticas.
    bot.send_message(
        ALERTAS_CHAT_ID,
        "🧪 MODO DE TESTE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ AS MENSAGENS A SEGUIR SÃO APENAS\n"
        "UMA SIMULAÇÃO VISUAL.\n\n"
        "🚫 NÃO É UM SINAL REAL."
    )

    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(chat_id, "online"))

    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "chegando",
        SURF="🔴 SURF 2 VERMELHOS",
        GALE_GATILHO="G12",
        GALE_ATUAL="G10",
    ))
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "chegando",
        SURF="🔴 SURF 2 VERMELHOS",
        GALE_GATILHO="G12",
        GALE_ATUAL="G11",
    ))

    # Exemplo de caminho que cancela antes do gatilho.
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "cancelado",
        SURF="🔴 SURF 2 VERMELHOS",
        GALE_GATILHO="G12",
        GALE_ATUAL="G11",
    ))

    # Novo caminho, desta vez chegando ao gatilho.
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "chegando",
        SURF="⚫ SURF 2 PRETOS",
        GALE_GATILHO="G12",
        GALE_ATUAL="G10",
    ))
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "chegando",
        SURF="⚫ SURF 2 PRETOS",
        GALE_GATILHO="G12",
        GALE_ATUAL="G11",
    ))
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "sinal",
        GALE_GATILHO="G12",
        COR_ULTIMA="🔴",
        NUMERO_ULTIMA="7",
        COR_ENTRADA="⚫ PRETO",
        SURF="⚫ SURF 2 PRETOS",
    ))

    # Um único modelo de texto para todos os Gales.
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(chat_id, "gales", GALE="G1"))
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(chat_id, "gales", GALE="G2"))

    # Exemplo GREEN completo: texto -> imagem -> registro.
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "green", RESULTADO_GALE="NO G2"
    ))
    _teste_enviar_imagem(chat_id, "green", 2)
    bot.send_message(
        ALERTAS_CHAT_ID,
        _teste_registro_operacao("GREEN ✅", "⚫ PRETO", "G2")
    )

    # Exemplo LOSS completo e separado.
    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(
        chat_id, "loss", LIMITE_GALE="G6"
    ))
    _teste_enviar_imagem(chat_id, "loss")
    bot.send_message(
        ALERTAS_CHAT_ID,
        _teste_registro_operacao("LOSS ❌", "🔴 VERMELHO", "G6")
    )

    bot.send_message(ALERTAS_CHAT_ID, _render_texto_canal(chat_id, "offline"))

    bot.send_message(
        ALERTAS_CHAT_ID,
        "🧪 TESTE FINALIZADO\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✅ TODAS AS MENSAGENS FORAM TESTADAS."
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_textos_menu")
def config_textos_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        _texto_menu_principal(),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=_textos_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "texto_testar_canal")
def texto_testar_canal_callback(call):
    bot.answer_callback_query(call.id, "🧪 ENVIANDO TESTE PARA O CANAL...")
    chat_id = call.message.chat.id
    try:
        _executar_teste_textos_canal(chat_id)
        bot.send_message(
            chat_id,
            "✅ TESTE ENVIADO PARA O CANAL.\n\n"
            "📌 FOI APENAS UMA SIMULAÇÃO VISUAL.\n"
            "🚫 O MONITORAMENTO, AS OPERAÇÕES E AS ESTATÍSTICAS NÃO FORAM ALTERADOS."
        )
    except Exception as exc:
        bot.send_message(chat_id, f"❌ ERRO AO TESTAR TEXTOS NO CANAL:\n{type(exc).__name__}: {exc}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("texto_menu:"))
def texto_menu_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":", 1)[1]
    chat_id = call.message.chat.id
    bot.edit_message_text(
        _texto_item_painel(chat_id, chave),
        chat_id,
        call.message.message_id,
        reply_markup=_texto_item_markup(chave),
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("texto_editar:"))
def texto_editar_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":", 1)[1]
    titulo = _TEXTOS_CANAL_META[chave][0]
    obrigatorios = sorted(_TEXTOS_CANAL_REQUIRED.get(chave, set()))
    detalhe = ""
    if obrigatorios:
        detalhe = "\n\n🔒 MANTENHA ESTES CAMPOS NO NOVO TEXTO:\n" + "\n".join(f"• {x}" for x in obrigatorios)
    msg = bot.send_message(
        call.message.chat.id,
        f"✏️ ALTERAR TEXTO — {titulo}\n\n"
        "ENVIE AGORA A NOVA MENSAGEM COMPLETA.\n"
        "VOCÊ PODE USAR VÁRIAS LINHAS E EMOJIS."
        f"{detalhe}\n\n"
        "📌 SOMENTE AS FRASES MUDAM. OS DADOS REAIS CONTINUAM SENDO CONTROLADOS PELA LÓGICA DO BOT.",
    )
    bot.register_next_step_handler(msg, _receber_texto_personalizado, chave)

@bot.callback_query_handler(func=lambda call: call.data.startswith("texto_restaurar:"))
def texto_restaurar_callback(call):
    chave = call.data.split(":", 1)[1]
    chat_id = call.message.chat.id
    _textos_canal_cfg(chat_id)["textos"][chave] = _TEXTOS_CANAL_PADRAO[chave]
    bot.answer_callback_query(call.id, "♻️ TEXTO PADRÃO RESTAURADO")
    bot.edit_message_text(
        _texto_item_painel(chat_id, chave),
        chat_id,
        call.message.message_id,
        reply_markup=_texto_item_markup(chave),
    )


@bot.callback_query_handler(func=lambda call: call.data == "surf_midias")
def surf_midias_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(
        "🖼️ GREEN / LOSS — SURF\n\n"
        "Estas imagens são EXCLUSIVAS do SURF normal e não alteram as imagens da Entrada por Gatilho.\n\n"
        "🟢 GREEN: DIRETO / SEM GALE + GALE 1 até GALE 20.\n"
        "🔴 LOSS: uma imagem própria.\n\n"
        "👇 Escolha o que deseja configurar:",
        chat_id, call.message.message_id, reply_markup=_surf_midias_markup(chat_id)
    )

@bot.callback_query_handler(func=lambda call: call.data == "surf_loss_menu")
def surf_loss_menu_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    salvo = "✅ IMAGEM PERSONALIZADA SALVA" if _textos_canal_cfg(chat_id).get("loss_imagem") else "▫️ USANDO IMAGEM PADRÃO DO BOT"
    bot.edit_message_text(
        f"🔴 IMAGEM LOSS — SURF\n\n{salvo}\n\nEsta imagem será usada somente no LOSS do SURF normal.",
        chat_id, call.message.message_id, reply_markup=_surf_loss_markup()
    )

@bot.callback_query_handler(func=lambda call: call.data == "surf_loss_enviar")
def surf_loss_enviar_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    msg = bot.send_message(chat_id, "🖼️ ENVIE AGORA A IMAGEM DO LOSS — SURF.")
    bot.register_next_step_handler_by_chat_id(chat_id, _receber_imagem_personalizada, "loss", msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "surf_loss_remover")
def surf_loss_remover_callback(call):
    chat_id = call.message.chat.id
    _textos_canal_cfg(chat_id)["loss_imagem"] = None
    bot.answer_callback_query(call.id, "🗑 IMAGEM LOSS REMOVIDA")
    bot.edit_message_text(
        "🔴 IMAGEM LOSS — SURF\n\n▫️ USANDO IMAGEM PADRÃO DO BOT.",
        chat_id, call.message.message_id, reply_markup=_surf_loss_markup()
    )

@bot.callback_query_handler(func=lambda call: call.data == "green_imagens_menu")
def green_imagens_menu_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(
        _green_imagens_texto(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_green_imagens_markup(chat_id),
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("green_imagem_item:"))
def green_imagem_item_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    gale = int(call.data.split(":", 1)[1])
    salvo = str(gale) in _textos_canal_cfg(chat_id).get("green_imagens", {})
    status = "✅ IMAGEM PERSONALIZADA CADASTRADA" if salvo else "▫️ USANDO IMAGEM PADRÃO DO BOT"

    bot.edit_message_text(
        f"🖼️ GREEN {_green_nome_resultado(gale)}\n\n"
        f"{status}\n\n"
        "ESTA IMAGEM SERÁ USADA SOMENTE QUANDO A OPERAÇÃO "
        f"ACERTAR EM {_green_nome_resultado(gale)}.\n\n"
        "👇 ESCOLHA O QUE DESEJA FAZER:",
        chat_id,
        call.message.message_id,
        reply_markup=_green_imagem_item_markup(gale),
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("green_imagem_enviar:"))
def green_imagem_enviar_callback(call):
    bot.answer_callback_query(call.id)
    gale = int(call.data.split(":", 1)[1])
    msg = bot.send_message(
        call.message.chat.id,
        f"🖼️ ENVIAR IMAGEM — GREEN {_green_nome_resultado(gale)}\n\n"
        "ENVIE AGORA A IMAGEM QUE DESEJA USAR.\n\n"
        "VOCÊ PODE ENVIAR COMO FOTO OU COMO ARQUIVO DE IMAGEM EM ALTA QUALIDADE/4K.\n\n"
        f"📌 ESTA IMAGEM SERÁ USADA SOMENTE NO GREEN {_green_nome_resultado(gale)}."
    )
    bot.register_next_step_handler(msg, _receber_imagem_green_gale, gale, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("green_imagem_remover:"))
def green_imagem_remover_callback(call):
    gale = int(call.data.split(":", 1)[1])
    chat_id = call.message.chat.id
    _textos_canal_cfg(chat_id).setdefault("green_imagens", {}).pop(str(gale), None)
    bot.answer_callback_query(call.id, "🗑 IMAGEM REMOVIDA")
    bot.edit_message_text(
        f"🖼️ GREEN {_green_nome_resultado(gale)}\n\n"
        "▫️ IMAGEM PERSONALIZADA REMOVIDA.\n\n"
        "O BOT VOLTOU A USAR A IMAGEM PADRÃO PARA ESTE RESULTADO.",
        chat_id,
        call.message.message_id,
        reply_markup=_green_imagem_item_markup(gale),
    )

@bot.callback_query_handler(func=lambda call: call.data == "green_imagens_remover_todas")
def green_imagens_remover_todas_callback(call):
    chat_id = call.message.chat.id
    _textos_canal_cfg(chat_id)["green_imagens"] = {}
    # Remove também o fallback antigo, para ficar realmente zerado.
    _textos_canal_cfg(chat_id)["green_imagem"] = None
    bot.answer_callback_query(call.id, "🗑 TODAS AS IMAGENS GREEN FORAM REMOVIDAS")
    bot.edit_message_text(
        _green_imagens_texto(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_green_imagens_markup(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("texto_imagem:"))
def texto_imagem_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":", 1)[1]
    msg = bot.send_message(
        call.message.chat.id,
        f"🖼️ ALTERAR IMAGEM — {chave.upper()}\n\n"
        "ENVIE AGORA A IMAGEM QUE DESEJA USAR.\n\n"
        "VOCÊ PODE ENVIAR COMO FOTO OU COMO ARQUIVO DE IMAGEM EM ALTA QUALIDADE/4K.\n\n"
        "📌 ELA SERÁ ENVIADA SEPARADA: TEXTO → IMAGEM → REGISTRO DA OPERAÇÃO."
    )
    bot.register_next_step_handler(msg, _receber_imagem_personalizada, chave)

@bot.callback_query_handler(func=lambda call: call.data.startswith("texto_imagem_remover:"))
def texto_imagem_remover_callback(call):
    chave = call.data.split(":", 1)[1]
    chat_id = call.message.chat.id
    _textos_canal_cfg(chat_id)[f"{chave}_imagem"] = None
    bot.answer_callback_query(call.id, "🗑 IMAGEM PERSONALIZADA REMOVIDA")
    bot.edit_message_text(
        _texto_item_painel(chat_id, chave),
        chat_id,
        call.message.message_id,
        reply_markup=_texto_item_markup(chave),
    )


def _receber_imagem_status_normal(message, chave, prompt_message_id=None):
    chat_id = message.chat.id
    item = None
    if getattr(message, "photo", None):
        item = {"tipo": "photo", "file_id": message.photo[-1].file_id}
    elif getattr(message, "document", None) and (message.document.mime_type or "").lower().startswith("image/"):
        item = {"tipo": "document", "file_id": message.document.file_id}
    if not item:
        bot.send_message(chat_id, "❌ ENVIE UMA FOTO OU UM ARQUIVO DE IMAGEM.")
        return
    _textos_canal_cfg(chat_id)[f"{chave}_imagem"] = item
    confirmacao = bot.send_message(chat_id, f"✅ IMAGEM — SINAIS {chave.upper()} SALVA.")
    _apagar_mensagem_seguro(chat_id, message.message_id)
    if prompt_message_id:
        _apagar_mensagem_seguro(chat_id, prompt_message_id)
    _apagar_mensagem_depois(chat_id, confirmacao.message_id, 5)

@bot.callback_query_handler(func=lambda call: call.data.startswith("texto_status_imagem:"))
def texto_status_imagem_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":", 1)[1]
    if chave == "online":
        texto = "🖼️ CADASTRAR IMAGEM\n\n📌 A imagem será utilizada inicialmente para informar no canal quando o bot estiver ONLINE e o monitoramento da estratégia for iniciado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS ONLINE.\n\n👇 Envie a imagem que deseja cadastrar."
    else:
        texto = "🖼️ CADASTRAR IMAGEM\n\n📌 A imagem será utilizada para informar no canal quando o bot estiver OFFLINE e o monitoramento da estratégia for encerrado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS OFFLINE.\n\n👇 Envie a imagem que deseja cadastrar."
    msg = bot.send_message(call.message.chat.id, texto)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, _receber_imagem_status_normal, chave, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("texto_status_imagem_remover:"))
def texto_status_imagem_remover_callback(call):
    chave = call.data.split(":", 1)[1]
    _textos_canal_cfg(call.message.chat.id)[f"{chave}_imagem"] = None
    bot.answer_callback_query(call.id, "🗑 IMAGEM REMOVIDA")
    bot.edit_message_text(_texto_item_painel(call.message.chat.id, chave), call.message.chat.id, call.message.message_id, reply_markup=_texto_item_markup(chave))

@bot.callback_query_handler(func=lambda call: call.data == "config_manual")
def config_manual_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        _texto_manual(),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=_voltar_config_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_gale_menu")
def config_gale_menu_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(
        _texto_gale_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_gale_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("config_gale_set:"))
def config_gale_set_callback(call):
    chat_id = call.message.chat.id
    valor = int(call.data.split(":", 1)[1])
    _desativado = _desativar_para_alteracao(chat_id, "surf")
    _cfg(chat_id)["gale_gatilho"] = valor
    bot.answer_callback_query(call.id, f"🔥 Gale de ativação definido: G{valor}")
    bot.edit_message_text(
        _texto_gale_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_gale_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_surf_menu")
def config_surf_menu_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(
        _texto_surf_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_surf_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("config_surf_set:"))
def config_surf_set_callback(call):
    chat_id = call.message.chat.id
    valor = call.data.split(":", 1)[1]
    _desativado = _desativar_para_alteracao(chat_id, "surf")
    _cfg(chat_id)["surf"] = valor
    bot.answer_callback_query(call.id, f"🏄 SURF definido: {_surf_nome(valor)}")
    bot.edit_message_text(
        _texto_surf_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_surf_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_limite_menu")
def config_limite_menu_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(
        _texto_limite_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_limite_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("config_limite_set:"))
def config_limite_set_callback(call):
    chat_id = call.message.chat.id
    valor = int(call.data.split(":", 1)[1])
    _desativado = _desativar_para_alteracao(chat_id, "surf")
    _cfg(chat_id)["limite_gales"] = valor
    bot.answer_callback_query(call.id, f"🛡 Limite definido: G{valor}")
    bot.edit_message_text(
        _texto_limite_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_limite_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_aviso_menu")
def config_aviso_menu_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(
        _texto_aviso_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_aviso_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("config_aviso_set:"))
def config_aviso_set_callback(call):
    chat_id = call.message.chat.id
    valor = int(call.data.split(":", 1)[1])
    _desativado = _desativar_para_alteracao(chat_id, "surf")
    _cfg(chat_id)["aviso_antes"] = valor
    msg = "🔕 Pré-alerta desativado" if valor == 0 else f"⚠️ Aviso definido: {valor} Gale(s) antes"
    bot.answer_callback_query(call.id, msg)
    bot.edit_message_text(
        _texto_aviso_menu(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_aviso_menu_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_incompleta")
def config_incompleta_callback(call):
    try:
        bot.answer_callback_query(
            call.id,
            "⚙️ Configure Gale, SURF, limite e aviso antes de ativar.",
            show_alert=True,
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: call.data == "config_ativar_resumo")
def config_ativar_resumo_callback(call):
    chat_id = call.message.chat.id
    if not _config_completa(_cfg(chat_id)):
        bot.answer_callback_query(
            call.id,
            "⚙️ Complete toda a configuração antes de ativar.",
            show_alert=True,
        )
        return
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        _texto_resumo_ativacao(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_ativar_resumo_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_confirmar_ativar")
def config_confirmar_ativar_callback(call):
    global TEXTOS_CANAL_OWNER_CHAT_ID
    chat_id = call.message.chat.id
    cfg = _cfg(chat_id)
    if not _config_completa(cfg):
        bot.answer_callback_query(
            call.id,
            "⚙️ A configuração está incompleta.",
            show_alert=True,
        )
        return
    # Nova ativação = nova sessão. Não reaproveita caminhos/Gales/sinais antigos.
    cfg["ativa"] = True
    cfg["pausada"] = False
    TEXTOS_CANAL_OWNER_CHAT_ID = chat_id
    try:
        _configurar_e_iniciar_monitor_real(chat_id)
    except Exception as erro:
        cfg["ativa"] = False
        cfg["pausada"] = False
        bot.answer_callback_query(call.id, "❌ Não foi possível iniciar o monitor", show_alert=True)
        bot.send_message(
            chat_id,
            f"❌ ERRO AO INICIAR O MONITOR REAL:\n{type(erro).__name__}: {str(erro)[:300]}"
        )
        return
    bot.answer_callback_query(call.id, "🟢 Estratégia ativada")

    # 1) No BOT ANALISADOR: mantém o painel completo da ativação.
    bot.edit_message_text(
        _texto_bot_ativada(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=configurar_estrategia_markup(chat_id),
    )

    # 2) No CANAL DE SINAIS: envia uma mensagem curta adicional.
    _enviar_imagem_status_canal(chat_id, "online", gatilho=False)
    _enviar_canal_surf(chat_id, _texto_canal_ativada(chat_id))


@bot.callback_query_handler(func=lambda call: call.data == "config_parar_bot")
def config_parar_bot_callback(call):
    chat_id = call.message.chat.id
    cfg = _cfg(chat_id)
    cfg["ativa"] = True
    cfg["pausada"] = True

    # Ao pausar, desliga o monitor real e abandona completamente a sessão.
    _parar_monitor_real()

    bot.answer_callback_query(call.id, "⏸ Estratégia pausada")

    # Canal de sinais: aviso curto e direto.
    _enviar_imagem_status_canal(chat_id, "offline", gatilho=False)
    _enviar_canal_surf(chat_id, _texto_canal_offline(chat_id))

    # Bot analisador: mantém a explicação completa sobre o reset da sessão.
    bot.edit_message_text(
        _texto_sinais_offline(),
        chat_id,
        call.message.message_id,
        reply_markup=configurar_estrategia_markup(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_retomar_bot")
def config_retomar_bot_callback(call):
    chat_id = call.message.chat.id
    cfg = _cfg(chat_id)
    # Reiniciar nunca continua a sessão pausada: começa um acompanhamento novo.
    cfg["ativa"] = True
    cfg["pausada"] = False
    try:
        _configurar_e_iniciar_monitor_real(chat_id)
    except Exception as erro:
        cfg["ativa"] = False
        cfg["pausada"] = True
        bot.answer_callback_query(call.id, "❌ Não foi possível retomar o monitor", show_alert=True)
        bot.send_message(
            chat_id,
            f"❌ ERRO AO RETOMAR O MONITOR REAL:\n{type(erro).__name__}: {str(erro)[:300]}"
        )
        return
    bot.answer_callback_query(call.id, "▶️ Estratégia retomada")

    bot.edit_message_text(
        _texto_bot_ativada(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=configurar_estrategia_markup(chat_id),
    )

    _enviar_imagem_status_canal(chat_id, "online", gatilho=False)
    _enviar_canal_surf(chat_id, _texto_canal_ativada(chat_id))


@bot.callback_query_handler(func=lambda call: call.data == "config_excluir_confirmar")
def config_excluir_confirmar_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(
        _texto_exclusao(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=_excluir_markup(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_excluir_sim")
def config_excluir_sim_callback(call):
    chat_id = call.message.chat.id
    _parar_monitor_real()
    ESTRATEGIAS_CONFIG[chat_id] = _estrategia_padrao()
    bot.answer_callback_query(call.id, "🗑 Estratégia excluída")
    _enviar_imagem_status_canal(chat_id, "offline", gatilho=False)
    _enviar_canal_surf(chat_id, _texto_canal_offline(chat_id))
    bot.edit_message_text(
        _texto_configurar_estrategia(chat_id),
        chat_id,
        call.message.message_id,
        reply_markup=configurar_estrategia_markup(chat_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("config_placeholder_digitacao:"))
def config_placeholder_digitacao_callback(call):
    bot.answer_callback_query(
        call.id,
        "✏️ A digitação manual será ligada na próxima etapa.",
        show_alert=False,
    )




@bot.callback_query_handler(func=lambda call: call.data in ("rel_menu", "gatrel_menu"))
def relatorio_menu_callback(call):
    bot.answer_callback_query(call.id)
    modo = "gatilho" if call.data.startswith("gat") else "surf"
    bot.edit_message_text(_texto_relatorio_menu(call.message.chat.id, modo), call.message.chat.id,
                          call.message.message_id, reply_markup=_relatorio_markup(modo, call.message.chat.id))


@bot.callback_query_handler(func=lambda call: call.data.startswith("rel_set:") or call.data.startswith("gatrel_set:"))
def relatorio_set_callback(call):
    modo = "gatilho" if call.data.startswith("gat") else "surf"
    valor = int(call.data.split(":", 1)[1])
    cfg = _relatorio_cfg(call.message.chat.id, modo)
    cfg["relatorio_qtd"] = valor
    cfg["relatorio_bloco"] = []
    cfg["relatorio_anterior"] = None
    cfg["relatorio_geral_blocos"] = 0
    cfg["relatorio_geral_sinais"] = 0
    cfg["relatorio_geral_greens"] = 0
    cfg["relatorio_geral_saldo"] = 0
    bot.answer_callback_query(call.id, "🚫 Relatório desativado" if valor == 0 else f"📊 Relatório a cada {valor} sinais")
    bot.edit_message_text(_texto_relatorio_menu(call.message.chat.id, modo), call.message.chat.id,
                          call.message.message_id, reply_markup=_relatorio_markup(modo, call.message.chat.id))


@bot.callback_query_handler(func=lambda call: call.data in ("rel_outro", "gatrel_outro"))
def relatorio_outro_callback(call):
    modo = "gatilho" if call.data.startswith("gat") else "surf"
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id,
        "🔢 QUANTIDADE PERSONALIZADA\n\nDigite a quantidade de sinais encerrados para gerar o relatório.\n\n📌 Exemplo: 75")
    bot.register_next_step_handler(
        msg, _relatorio_receber_qtd, modo, msg.message_id, call.message.message_id
    )


@bot.callback_query_handler(func=lambda call: call.data in ("rel_ver", "gatrel_ver"))
def relatorio_ver_callback(call):
    modo = "gatilho" if call.data.startswith("gat") else "surf"
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "👁 TEXTO ATUAL DO RELATÓRIO\n\n" + _relatorio_exemplo(_relatorio_cfg(call.message.chat.id, modo)),
        call.message.chat.id, call.message.message_id, reply_markup=_relatorio_texto_markup(modo)
    )


@bot.callback_query_handler(func=lambda call: call.data in ("rel_editar", "gatrel_editar"))
def relatorio_editar_callback(call):
    modo = "gatilho" if call.data.startswith("gat") else "surf"
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id,
        "✏️ ALTERAR TEXTO DO RELATÓRIO\n\nEnvie o novo modelo completo.\n\n"
        "Campos disponíveis: {qtd}, {greens}, {loss}, {taxa_green}, {taxa_loss}, {distribuicao}, "
        "{seq_green}, {seq_loss}, {maior_gale}, {unidades_green}, {unidades_loss}, {saldo}, "
        "{emoji_resultado}, {resultado}, {comparacao}.\n\nVocê pode mudar frases, emojis, ordem e separadores.")
    bot.register_next_step_handler(msg, _relatorio_receber_texto, modo)


@bot.callback_query_handler(func=lambda call: call.data in ("rel_restaurar", "gatrel_restaurar"))
def relatorio_restaurar_callback(call):
    modo = "gatilho" if call.data.startswith("gat") else "surf"
    _relatorio_cfg(call.message.chat.id, modo)["relatorio_texto"] = None
    bot.answer_callback_query(call.id, "♻️ Texto padrão restaurado")
    bot.edit_message_text(_texto_relatorio_menu(call.message.chat.id, modo), call.message.chat.id,
                          call.message.message_id, reply_markup=_relatorio_markup(modo, call.message.chat.id))


@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_midias")
def gatcfg_midias_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "🖼️ GREEN / LOSS — ENTRADA POR GATILHO\n\n"
        "Estas imagens são EXCLUSIVAS desta estratégia e não alteram as imagens do SURF normal.\n\n"
        "🟢 GREEN: DIRETO / SEM GALE + GALE 1 até GALE 20.\n"
        "🔴 LOSS: uma imagem própria.\n\n"
        "👇 Escolha o que deseja configurar:",
        call.message.chat.id, call.message.message_id,
        reply_markup=_gatcfg_midias_markup(call.message.chat.id)
    )

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_green_menu")
def gatcfg_green_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "🟢 IMAGENS GREEN — ENTRADA POR GATILHO\n\n"
        "Sempre ficam disponíveis DIRETO / SEM GALE e GALE 1 até GALE 20, "
        "independentemente do limite configurado.\n\n"
        "✅ = imagem personalizada\n▫️ = imagem padrão do bot",
        call.message.chat.id, call.message.message_id,
        reply_markup=_gatcfg_green_markup(call.message.chat.id)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("gatcfg_green_item:"))
def gatcfg_green_item_callback(call):
    bot.answer_callback_query(call.id)
    gale = int(call.data.split(":", 1)[1])
    bot.edit_message_text(
        f"🟢 GREEN {_gatcfg_green_nome(gale)} — ENTRADA POR GATILHO\n\n"
        "Cadastre a imagem que será enviada quando esta estratégia acertar exatamente neste resultado.",
        call.message.chat.id, call.message.message_id,
        reply_markup=_gatcfg_green_item_markup(gale)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("gatcfg_green_enviar:"))
def gatcfg_green_enviar_callback(call):
    # Mantém o fluxo rápido/estável por chat, mas com a ordem visual correta:
    # 1) mostra ENVIE AGORA; 2) arma a próxima foto como GREEN escolhido.
    chat_id = call.message.chat.id
    gale = int(call.data.split(":", 1)[1])
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        chat_id,
        f"🖼️ ENVIE AGORA A IMAGEM DO GREEN {_gatcfg_green_nome(gale)}."
    )
    bot.register_next_step_handler_by_chat_id(chat_id, _gatcfg_receber_green, gale, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gatcfg_green_remover:"))
def gatcfg_green_remover_callback(call):
    chat_id = call.message.chat.id
    gale = int(call.data.split(":", 1)[1])
    _gatcfg_midias(chat_id).setdefault("green_imagens", {}).pop(str(gale), None)
    bot.answer_callback_query(call.id, "🗑 Imagem removida")
    bot.edit_message_text(
        f"🟢 GREEN {_gatcfg_green_nome(gale)} — ENTRADA POR GATILHO\n\n▫️ USANDO IMAGEM PADRÃO DO BOT.",
        chat_id, call.message.message_id, reply_markup=_gatcfg_green_item_markup(gale)
    )

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_green_remover_todas")
def gatcfg_green_remover_todas_callback(call):
    chat_id = call.message.chat.id
    _gatcfg_midias(chat_id)["green_imagens"] = {}
    bot.answer_callback_query(call.id, "🗑 Todas as imagens GREEN removidas")
    bot.edit_message_text(
        "🟢 IMAGENS GREEN — ENTRADA POR GATILHO\n\n▫️ TODAS ESTÃO USANDO A IMAGEM PADRÃO DO BOT.",
        chat_id, call.message.message_id, reply_markup=_gatcfg_green_markup(chat_id)
    )

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_loss_menu")
def gatcfg_loss_menu_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    salvo = "✅ IMAGEM PERSONALIZADA SALVA" if _gatcfg_midias(chat_id).get("loss_imagem") else "▫️ USANDO IMAGEM PADRÃO DO BOT"
    bot.edit_message_text(
        f"🔴 LOSS — ENTRADA POR GATILHO\n\n{salvo}",
        chat_id, call.message.message_id, reply_markup=_gatcfg_loss_markup()
    )

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_loss_enviar")
def gatcfg_loss_enviar_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    msg = bot.send_message(chat_id, "🖼️ ENVIE AGORA A IMAGEM DO LOSS.")
    bot.register_next_step_handler_by_chat_id(chat_id, _gatcfg_receber_loss, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_loss_remover")
def gatcfg_loss_remover_callback(call):
    chat_id = call.message.chat.id
    _gatcfg_midias(chat_id)["loss_imagem"] = None
    bot.answer_callback_query(call.id, "🗑 Imagem LOSS removida")
    bot.edit_message_text(
        "🔴 LOSS — ENTRADA POR GATILHO\n\n▫️ USANDO IMAGEM PADRÃO DO BOT.",
        chat_id, call.message.message_id, reply_markup=_gatcfg_loss_markup()
    )

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_manual")
def gatcfg_manual_callback(call):
    bot.answer_callback_query(call.id)
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="gatcfg_menu"))
    bot.edit_message_text(_texto_manual_gatilho(), call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda call: call.data == "gattexto_menu")
def gattexto_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "✍️ CONFIGURAR TEXTOS — ENTRADA POR GATILHO\n\n"
        "Personalize as mensagens enviadas por esta estratégia. Os dados calculados, Gales, cores, números e lógica continuam protegidos.\n\n"
        "👇 Escolha qual texto deseja configurar:",
        call.message.chat.id, call.message.message_id, reply_markup=_gattexto_menu_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith("gattexto_item:"))
def gattexto_item_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":", 1)[1]
    bot.edit_message_text(_gattexto_painel(call.message.chat.id, chave), call.message.chat.id, call.message.message_id, reply_markup=_gattexto_item_markup(chave))

@bot.callback_query_handler(func=lambda call: call.data.startswith("gattexto_editar:"))
def gattexto_editar_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":", 1)[1]
    msg = bot.send_message(call.message.chat.id, "✏️ ENVIE AGORA O NOVO TEXTO.\n\nMantenha os campos automáticos mostrados no painel.")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, _gattexto_receber, chave)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gattexto_restaurar:"))
def gattexto_restaurar_callback(call):
    chave = call.data.split(":", 1)[1]
    _gattexto_cfg(call.message.chat.id).pop(chave, None)
    bot.answer_callback_query(call.id, "♻️ TEXTO PADRÃO RESTAURADO")
    bot.edit_message_text(_gattexto_painel(call.message.chat.id, chave), call.message.chat.id, call.message.message_id, reply_markup=_gattexto_item_markup(chave))

def _gattexto_receber_imagem_status(message, chave, prompt_message_id=None):
    chat_id = message.chat.id
    item = None
    if getattr(message, "photo", None):
        item = {"tipo": "photo", "file_id": message.photo[-1].file_id}
    elif getattr(message, "document", None) and (message.document.mime_type or "").lower().startswith("image/"):
        item = {"tipo": "document", "file_id": message.document.file_id}
    if not item:
        bot.send_message(chat_id, "❌ ENVIE UMA FOTO OU UM ARQUIVO DE IMAGEM.")
        return
    _gatcfg_midias(chat_id)[f"{chave}_imagem"] = item
    confirmacao = bot.send_message(chat_id, f"✅ IMAGEM — SINAIS {chave.upper()} SALVA.")
    _apagar_mensagem_seguro(chat_id, message.message_id)
    if prompt_message_id:
        _apagar_mensagem_seguro(chat_id, prompt_message_id)
    _apagar_mensagem_depois(chat_id, confirmacao.message_id, 5)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gattexto_status_imagem:"))
def gattexto_status_imagem_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":", 1)[1]
    if chave == "online":
        texto = "🖼️ CADASTRAR IMAGEM\n\n📌 A imagem será utilizada inicialmente para informar no canal quando o bot estiver ONLINE e o monitoramento da estratégia for iniciado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS ONLINE.\n\n👇 Envie a imagem que deseja cadastrar."
    else:
        texto = "🖼️ CADASTRAR IMAGEM\n\n📌 A imagem será utilizada para informar no canal quando o bot estiver OFFLINE e o monitoramento da estratégia for encerrado.\n\n🔄 Caso já exista uma imagem cadastrada, você poderá substituí-la por uma nova.\n\n📍 Esta imagem será utilizada somente no aviso de SINAIS OFFLINE.\n\n👇 Envie a imagem que deseja cadastrar."
    msg = bot.send_message(call.message.chat.id, texto)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, _gattexto_receber_imagem_status, chave, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gattexto_status_imagem_remover:"))
def gattexto_status_imagem_remover_callback(call):
    chave = call.data.split(":", 1)[1]
    _gatcfg_midias(call.message.chat.id)[f"{chave}_imagem"] = None
    bot.answer_callback_query(call.id, "🗑 IMAGEM REMOVIDA")
    bot.edit_message_text(_gattexto_painel(call.message.chat.id, chave), call.message.chat.id, call.message.message_id, reply_markup=_gattexto_item_markup(chave))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_menu")
def gatcfg_menu_callback(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bot.edit_message_text(_texto_gatcfg_menu(chat_id), chat_id, call.message.message_id,
                          reply_markup=_gatcfg_markup(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_gale_menu")
def gatcfg_gale_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "🔥 GALE-GATILHO\n\n"
        "Escolha qual Gale do SURF deverá funcionar como gatilho.\n\n"
        "📌 Ao atingir esse Gale, a oportunidade imediatamente seguinte será a entrada.",
        call.message.chat.id, call.message.message_id, reply_markup=_gatcfg_gale_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith("gatcfg_gale_set:"))
def gatcfg_gale_set_callback(call):
    chat_id = call.message.chat.id
    valor = int(call.data.split(":", 1)[1])
    _desativado = _desativar_para_alteracao(chat_id, "gatilho")
    _cfg_gatilho(chat_id)["gale_gatilho"] = valor
    bot.answer_callback_query(call.id, f"🔥 G{valor} selecionado")
    bot.edit_message_text(_texto_gatcfg_menu(chat_id), chat_id, call.message.message_id,
                          reply_markup=_gatcfg_markup(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_surf_menu")
def gatcfg_surf_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "🏄 ESCOLHER SURF\n\n"
        "Escolha qual caminho do SURF vai gerar os Gales-gatilho.\n\n"
        "📍 O ponto inicial pode estar relacionado a:\n\n"
        "⚪ Após BRANCO\n🔴 Após VERMELHO\n⚫ Após PRETO\n\n🔢 Independente de qualquer número.",
        call.message.chat.id, call.message.message_id, reply_markup=_gatcfg_surf_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith("gatcfg_surf_set:"))
def gatcfg_surf_set_callback(call):
    chat_id = call.message.chat.id
    valor = call.data.split(":", 1)[1]
    _desativado = _desativar_para_alteracao(chat_id, "gatilho")
    _cfg_gatilho(chat_id)["surf"] = valor
    bot.answer_callback_query(call.id, "🏄 SURF selecionado")
    bot.edit_message_text(_texto_gatcfg_menu(chat_id), chat_id, call.message.message_id,
                          reply_markup=_gatcfg_markup(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_limite_menu")
def gatcfg_limite_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "🛡 LIMITE DE GALES\n\n"
        "Escolha até qual Gale a operação pode chegar.\n\n"
        "📌 Exemplo — limite G3:\n\n"
        "🎯 DIRETO\n"
        "❌ Perdeu → espera novo gatilho → G1\n"
        "❌ Perdeu → espera novo gatilho → G2\n"
        "❌ Perdeu → espera novo gatilho → G3\n\n"
        "✅ Bateu → GREEN e reinicia\n"
        "❌ Perdeu no G3 → LOSS e reinicia\n\n"
        "👇 Escolha o limite:",
        call.message.chat.id, call.message.message_id, reply_markup=_gatcfg_limite_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith("gatcfg_limite_set:"))
def gatcfg_limite_set_callback(call):
    chat_id = call.message.chat.id
    valor = int(call.data.split(":", 1)[1])
    _desativado = _desativar_para_alteracao(chat_id, "gatilho")
    _cfg_gatilho(chat_id)["limite_gales"] = valor
    bot.answer_callback_query(call.id, f"🛡 Limite G{valor}")
    bot.edit_message_text(_texto_gatcfg_menu(chat_id), chat_id, call.message.message_id,
                          reply_markup=_gatcfg_markup(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_aviso_menu")
def gatcfg_aviso_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "⚠️ AVISO ANTES DO GATILHO\n\n"
        "Escolha com quantos Gales de antecedência você quer ser avisado quando um caminho estiver se aproximando do Gale de gatilho.\n\n"
        "📌 Exemplo:\n"
        "Gatilho configurado: G12\n\n"
        "• Aviso 2 antes → começa no G10\n"
        "• Aviso 1 antes → começa no G11\n"
        "• 🚫 Não avisar → aguarda o G12 diretamente\n\n"
        "O aviso não é uma entrada. Ele apenas informa que o caminho está chegando perto do gatilho.\n\n"
        "👇 Escolha quando deseja receber o aviso:",
        call.message.chat.id, call.message.message_id, reply_markup=_gatcfg_aviso_markup()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("gatcfg_aviso_set:"))
def gatcfg_aviso_set_callback(call):
    chat_id = call.message.chat.id
    valor = int(call.data.split(":", 1)[1])
    _desativado = _desativar_para_alteracao(chat_id, "gatilho")
    _cfg_gatilho(chat_id)["aviso_antes"] = valor
    bot.answer_callback_query(call.id, "🚫 Aviso desativado" if valor == 0 else f"⚠️ {valor} Gale(s) antes")
    bot.edit_message_text(_texto_gatcfg_menu(chat_id), chat_id, call.message.message_id,
                          reply_markup=_gatcfg_markup(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_incompleta")
def gatcfg_incompleta_callback(call):
    bot.answer_callback_query(call.id, "⚙️ Configure Gale-gatilho, SURF e limite.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_ativar")
def gatcfg_ativar_callback(call):
    chat_id = call.message.chat.id
    cfg = _cfg_gatilho(chat_id)
    if not _gatcfg_completa(cfg):
        bot.answer_callback_query(call.id, "⚙️ Complete a configuração.", show_alert=True)
        return
    # Evita dois motores diferentes ativos ao mesmo tempo.
    _parar_monitor_real()
    for c in ESTRATEGIAS_CONFIG.values():
        c["ativa"] = False
        c["pausada"] = False
    cfg["ativa"] = True
    cfg["pausada"] = False
    try:
        _configurar_e_iniciar_monitor_gatilho(chat_id)
    except Exception as erro:
        cfg["ativa"] = False
        bot.answer_callback_query(call.id, "❌ Erro ao iniciar", show_alert=True)
        bot.send_message(chat_id, f"❌ ERRO AO INICIAR: {type(erro).__name__}: {str(erro)[:250]}")
        return
    bot.answer_callback_query(call.id, "🟢 Entrada por Gatilho ativada")
    try:
        _enviar_imagem_status_canal(chat_id, "online", gatilho=True)
        _enviar_canal_surf(chat_id, _gattexto_modelo(chat_id, "online"))
    except Exception:
        traceback.print_exc()
    bot.edit_message_text(
        "🎯 SURF — ENTRADA POR GATILHO\n\n"
        "🟢 ESTRATÉGIA ATIVADA\n\n"
        f"🔥 Gatilho: G{cfg['gale_gatilho']}\n"
        f"🏄 SURF: {_surf_nome(cfg['surf'])}\n"
        f"🛡 Limite: G{cfg['limite_gales']}\n\n"
        "📡 Monitoramento iniciado a partir da rodada mais recente.\n"
        "⏳ Aguardando o Gale-gatilho...",
        chat_id, call.message.message_id, reply_markup=_gatcfg_markup(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_parar")
def gatcfg_parar_callback(call):
    chat_id = call.message.chat.id
    cfg = _cfg_gatilho(chat_id)
    _parar_monitor_real()
    cfg["ativa"] = True
    cfg["pausada"] = True
    try:
        _enviar_imagem_status_canal(chat_id, "offline", gatilho=True)
        _enviar_canal_surf(chat_id, _gattexto_modelo(chat_id, "offline"))
    except Exception:
        traceback.print_exc()
    bot.answer_callback_query(call.id, "⏸ Bot parado")
    bot.edit_message_text(_texto_gatcfg_menu(chat_id), chat_id, call.message.message_id,
                          reply_markup=_gatcfg_markup(chat_id))

@bot.callback_query_handler(func=lambda call: call.data == "gatcfg_excluir")
def gatcfg_excluir_callback(call):
    chat_id = call.message.chat.id
    _parar_monitor_real()
    ESTRATEGIAS_GATILHO_CONFIG[chat_id] = _estrategia_gatilho_padrao()
    bot.answer_callback_query(call.id, "🗑 Configuração excluída")
    bot.edit_message_text(_texto_gatcfg_menu(chat_id), chat_id, call.message.message_id,
                          reply_markup=_gatcfg_markup(chat_id))



# ==============================================================================
# GREEN APÓS 2 LOSS — configuração independente
# ==============================================================================
def _greenloss_texto(chat_id):
    c = _cfg_green_loss(chat_id)
    return (
        "🔥 GREEN APÓS 2 LOSS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📊 ESTRATÉGIA-BASE: ENTRADA POR GATILHO\n\n"
        f"🔥 Gale de ativação: {_gale_txt(c['gale_gatilho'])}\n"
        f"🏄 SURF: {_surf_nome(c['surf'])}\n"
        f"🛡️ Limite de Gales: {_limite_txt(c['limite_gales'])}\n"
        "❌ Gatilho: 2 LOSS consecutivos\n\n"
        "📌 Após 2 LOSS consecutivos, o bot NÃO entra imediatamente.\n"
        "Ele acompanha as tentativas até surgir novamente o Gale de ativação.\n"
        "Se a entrada perder, espera outro Gale de ativação para liberar G1, depois outro para G2, e assim por diante.\n\n"
        "🧬 Durante a espera, somente a tentativa atual fica visível; quando o caminho quebra, a mesma mensagem passa automaticamente para a próxima tentativa."
    )

def _greenloss_markup(chat_id):
    c=_cfg_green_loss(chat_id)
    m=telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton(f"🔥 GALE DE ATIVAÇÃO — {_gale_txt(c['gale_gatilho'])}", callback_data="greenloss_gale"))
    m.add(telebot.types.InlineKeyboardButton(f"🏄 ESCOLHER SURF — {_surf_nome(c['surf'])}", callback_data="greenloss_surf"))
    m.add(telebot.types.InlineKeyboardButton(f"🛡️ LIMITE DE GALES — {_limite_txt(c['limite_gales'])}", callback_data="greenloss_limite"))
    if c.get("ativa"):
        m.add(telebot.types.InlineKeyboardButton("⏹️ PARAR ESTRATÉGIA", callback_data="greenloss_parar"))
    else:
        m.add(telebot.types.InlineKeyboardButton("▶️ ATIVAR ESTRATÉGIA", callback_data="greenloss_ativar"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="config_estrategia"))
    return m

def _greenloss_nums(prefix, voltar):
    m=telebot.types.InlineKeyboardMarkup(row_width=4)
    botoes=[telebot.types.InlineKeyboardButton(f"G{i}", callback_data=f"{prefix}:{i}") for i in range(1,17)]
    m.add(*botoes)
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data=voltar))
    return m

@bot.callback_query_handler(func=lambda call: call.data == "greenloss_menu")
def greenloss_menu_cb(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(_greenloss_texto(call.message.chat.id), call.message.chat.id, call.message.message_id, reply_markup=_greenloss_markup(call.message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data == "greenloss_gale")
def greenloss_gale_cb(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text("🔥 GREEN APÓS 2 LOSS\n\nEscolha o Gale de ativação da estratégia-base:", call.message.chat.id, call.message.message_id, reply_markup=_greenloss_nums("greenloss_setgale","greenloss_menu"))

@bot.callback_query_handler(func=lambda call: call.data.startswith("greenloss_setgale:"))
def greenloss_setgale_cb(call):
    _cfg_green_loss(call.message.chat.id)["gale_gatilho"]=int(call.data.split(":")[1]); bot.answer_callback_query(call.id)
    bot.edit_message_text(_greenloss_texto(call.message.chat.id), call.message.chat.id, call.message.message_id, reply_markup=_greenloss_markup(call.message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data == "greenloss_limite")
def greenloss_limite_cb(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text("🛡️ GREEN APÓS 2 LOSS\n\nEscolha o limite da operação:", call.message.chat.id, call.message.message_id, reply_markup=_greenloss_nums("greenloss_setlim","greenloss_menu"))

@bot.callback_query_handler(func=lambda call: call.data.startswith("greenloss_setlim:"))
def greenloss_setlim_cb(call):
    _cfg_green_loss(call.message.chat.id)["limite_gales"]=int(call.data.split(":")[1]); bot.answer_callback_query(call.id)
    bot.edit_message_text(_greenloss_texto(call.message.chat.id), call.message.chat.id, call.message.message_id, reply_markup=_greenloss_markup(call.message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data == "greenloss_surf")
def greenloss_surf_cb(call):
    m=telebot.types.InlineKeyboardMarkup(row_width=1)
    for v,t in [("vermelho","🔴 SURF 2 VERMELHOS"),("preto","⚫ SURF 2 PRETOS"),("ambos","🔴⚫ OS DOIS")]: m.add(telebot.types.InlineKeyboardButton(t, callback_data=f"greenloss_setsurf:{v}"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="greenloss_menu")); bot.answer_callback_query(call.id)
    bot.edit_message_text("🏄 GREEN APÓS 2 LOSS\n\nEscolha o SURF observado:", call.message.chat.id, call.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda call: call.data.startswith("greenloss_setsurf:"))
def greenloss_setsurf_cb(call):
    _cfg_green_loss(call.message.chat.id)["surf"]=call.data.split(":",1)[1]; bot.answer_callback_query(call.id)
    bot.edit_message_text(_greenloss_texto(call.message.chat.id), call.message.chat.id, call.message.message_id, reply_markup=_greenloss_markup(call.message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data == "greenloss_ativar")
def greenloss_ativar_cb(call):
    global ALERTAS_MODO_ESTRATEGIA, ALERTAS_SURF_GATILHO, ALERTAS_SURF_STOP_GALE, ALERTAS_SURF_AVISO_ANTES
    global alertas_gatilho_nivel_aposta, green_loss_contador, green_loss_fase, green_loss_tentativa, alertas_surfe_ativos
    c=_cfg_green_loss(call.message.chat.id)
    if c.get("gale_gatilho") is None or c.get("surf") is None or c.get("limite_gales") is None:
        bot.answer_callback_query(call.id,"⚙️ Configure ativação, SURF e limite.",show_alert=True); return
    _parar_monitor_real(); _zerar_estado_sessao_online()
    for x in ESTRATEGIAS_CONFIG.values(): x["ativa"]=False; x["pausada"]=False
    for x in ESTRATEGIAS_GATILHO_CONFIG.values(): x["ativa"]=False; x["pausada"]=False
    c["ativa"]=True; c["pausada"]=False
    ALERTAS_MODO_ESTRATEGIA="green_apos_loss"; ALERTAS_SURF_GATILHO=int(c["gale_gatilho"]); ALERTAS_SURF_STOP_GALE=int(c["limite_gales"]); ALERTAS_SURF_AVISO_ANTES=max(0, int(c["gale_gatilho"]) - 1)
    alertas_gatilho_nivel_aposta=0; green_loss_contador=0; green_loss_fase="observando"; green_loss_tentativa=1
    modo={"vermelho":"Vermelho","preto":"Preto","ambos":"Ambos"}[c["surf"]]
    with alertas_surfe_lock: alertas_surfe_ativos=True
    try: _iniciar_monitor_alertas_surfe(modo)
    except Exception as e:
        c["ativa"]=False
        with alertas_surfe_lock: alertas_surfe_ativos=False
        bot.answer_callback_query(call.id,"❌ Erro ao iniciar",show_alert=True); return
    bot.answer_callback_query(call.id,"🟢 Green após 2 Loss ativado")
    bot.edit_message_text(_greenloss_texto(call.message.chat.id)+"\n\n📡 MONITORANDO\n❌ LOSS: 0/2", call.message.chat.id, call.message.message_id, reply_markup=_greenloss_markup(call.message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data == "greenloss_parar")
def greenloss_parar_cb(call):
    c=_cfg_green_loss(call.message.chat.id); c["ativa"]=False; c["pausada"]=False; _parar_monitor_real(); bot.answer_callback_query(call.id,"⏹️ Estratégia parada")
    bot.edit_message_text(_greenloss_texto(call.message.chat.id), call.message.chat.id, call.message.message_id, reply_markup=_greenloss_markup(call.message.chat.id))

# ==============================================================================
# PERSONALIZAÇÃO VISUAL — CAPAS DOS PAINÉIS PRINCIPAIS
# ==============================================================================
_CAPAS_NOMES = {
    "bot": "🤖 BOT",
    "surf": "🏄 SURF APÓS ⚪",
    "controle": "🐺 CONTROLE GERAL",
    "seq10": "🔥 SEQUÊNCIA 10X",
    "seqcores": "📊 SEQUÊNCIA DE CORES",
    "branco": "⏱️ ATRASO DO BRANCO",
}

# Guarda somente a capa que está ativa em cada chat.
# A capa permanece enquanto o usuário navega dentro da mesma função,
# mas é retirada quando ele sai dela ou abre outra função principal.
_CAPA_ATIVA_CHAT = {}

def _capa_file_id(chave):
    return CAPAS_PAINEL_CONFIG.get(chave)

def _limpar_capa_ativa(chat_id, exceto_chave=None):
    atual = _CAPA_ATIVA_CHAT.get(chat_id)
    if not atual:
        return
    chave_atual, message_id = atual
    if exceto_chave is not None and chave_atual == exceto_chave:
        return
    _apagar_mensagem_seguro(chat_id, message_id)
    _CAPA_ATIVA_CHAT.pop(chat_id, None)

def _enviar_capa_painel(chat_id, chave):
    # Capas cadastráveis pelo Telegram foram desativadas.
    # As novas capas serão fixas no código, uma por função.
    return None

def _personalizar_bot_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    for chave in ("bot", "surf", "controle", "seq10", "seqcores", "branco"):
        status = "✅" if _capa_file_id(chave) else "❌"
        m.add(telebot.types.InlineKeyboardButton(f"{status} {_CAPAS_NOMES[chave]}", callback_data=f"capa_menu:{chave}"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="voltar_painel_principal"))
    return m

def _capa_menu_markup(chave):
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🖼️ CADASTRAR / TROCAR IMAGEM", callback_data=f"capa_enviar:{chave}"))
    if _capa_file_id(chave):
        m.add(telebot.types.InlineKeyboardButton("🗑️ REMOVER IMAGEM", callback_data=f"capa_remover:{chave}"))
    m.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="personalizar_bot"))
    return m

def _texto_capa_menu(chave):
    nome = _CAPAS_NOMES.get(chave, chave.upper())
    status = "✅ CADASTRADA" if _capa_file_id(chave) else "❌ NÃO CADASTRADA"
    return (f"🖼️ CAPA — {nome}\
"
            "━━━━━━━━━━━━━━━━━━\
\
"
            f"📌 Esta imagem será exibida ao abrir o painel {nome}.\
\
"
            f"Status: {status}\
\
"
            "👇 Escolha uma opção:")

@bot.callback_query_handler(func=lambda call: call.data == "personalizar_bot")
def personalizar_bot_callback(call):
    bot.answer_callback_query(call.id)
    texto = ("🎨 PERSONALIZAR BOT\
"
             "━━━━━━━━━━━━━━━━━━\
\
"
             "🖼️ Personalize as capas das principais áreas do bot.\
\
"
             "As imagens cadastradas serão exibidas ao abrir cada função, sempre logo acima das informações e dos botões daquele painel.\
\
"
             "📌 A capa fica ligada visualmente à função: primeiro aparece a imagem e, logo abaixo, o texto do painel.\
\
"
             "📌 As imagens de SINAIS ONLINE/OFFLINE e GREEN/LOSS continuam dentro da configuração de cada estratégia.\
\
"
             "👇 Escolha o painel que deseja personalizar:")
    try:
        bot.edit_message_text(texto, call.message.chat.id, call.message.message_id, reply_markup=_personalizar_bot_markup())
    except Exception:
        bot.send_message(call.message.chat.id, texto, reply_markup=_personalizar_bot_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith("capa_menu:"))
def capa_menu_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":",1)[1]
    try:
        bot.edit_message_text(_texto_capa_menu(chave), call.message.chat.id, call.message.message_id, reply_markup=_capa_menu_markup(chave))
    except Exception:
        bot.send_message(call.message.chat.id, _texto_capa_menu(chave), reply_markup=_capa_menu_markup(chave))

@bot.callback_query_handler(func=lambda call: call.data.startswith("capa_enviar:"))
def capa_enviar_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":",1)[1]
    nome = _CAPAS_NOMES.get(chave, chave.upper())
    msg = bot.send_message(call.message.chat.id,
        "🖼️ CADASTRAR IMAGEM\
\
"
        f"📌 Esta imagem será utilizada como capa ao abrir {nome}.\
\
"
        "🔄 Caso já exista uma imagem cadastrada, ela será substituída pela nova.\
\
"
        "👇 Envie a imagem que deseja cadastrar.")
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, _capa_receber_imagem, chave, msg.message_id)

def _capa_receber_imagem(message, chave, prompt_message_id=None):
    chat_id = message.chat.id
    if not getattr(message, "photo", None):
        aviso = bot.send_message(chat_id, "❌ Envie uma imagem/foto para cadastrar a capa.")
        _apagar_mensagem_depois(chat_id, aviso.message_id, 5)
        return
    CAPAS_PAINEL_CONFIG[chave] = message.photo[-1].file_id
    _salvar_configuracoes_permanentes(forcar=True)
    _apagar_mensagem_seguro(chat_id, message.message_id)
    _apagar_mensagem_seguro(chat_id, prompt_message_id)
    conf = bot.send_message(chat_id, f"✅ CAPA — {_CAPAS_NOMES.get(chave, chave.upper())} SALVA.")
    _apagar_mensagem_depois(chat_id, conf.message_id, 5)

@bot.callback_query_handler(func=lambda call: call.data.startswith("capa_remover:"))
def capa_remover_callback(call):
    bot.answer_callback_query(call.id)
    chave = call.data.split(":",1)[1]
    CAPAS_PAINEL_CONFIG.pop(chave, None)
    _salvar_configuracoes_permanentes(forcar=True)
    try:
        bot.edit_message_text(_texto_capa_menu(chave), call.message.chat.id, call.message.message_id, reply_markup=_capa_menu_markup(chave))
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data == "menu_bot")
def menu_bot_callback(call):
    try:
        bot.answer_callback_query(call.id)
        try:
            _editar_balao_com_capa(
                call.message,
                _CAPA_BOT_FIXA_B64,
                "capa_bot.jpg",
                _texto_controle_bot(),
                bot_controle_markup(),
            )
        except Exception:
            # Quando VOLTAR AO BOT vem de um submenu em texto, não é possível
            # transformar aquela mensagem em foto com edit_message_media.
            # Substitui a bolha de texto pelo painel BOT com a capa fixa.
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            foto = io.BytesIO(base64.b64decode(_CAPA_BOT_FIXA_B64))
            foto.name = "capa_bot.jpg"
            bot.send_photo(
                call.message.chat.id,
                foto,
                caption=_texto_controle_bot(),
                reply_markup=bot_controle_markup(),
            )
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "voltar_painel_principal")
def voltar_painel_principal_callback(call):
    try:
        bot.answer_callback_query(call.id)
        _editar_balao_com_capa(
            call.message,
            _CAPA_ANALISADOR_B64,
            "capa_analisador.jpg",
            _texto_painel_analisador(),
            painel_markup(),
        )
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "ativar_alertas_surfe")
def ativar_alertas_surfe_callback(call):
    """Primeiro pergunta qual SURF deve ser acompanhado."""
    try:
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            "⚫ SOMENTE SURF 2 PRETOS", callback_data="ativar_alertas_modo:Preto"
        ))
        markup.add(telebot.types.InlineKeyboardButton(
            "🔴 SOMENTE SURF 2 VERMELHOS", callback_data="ativar_alertas_modo:Vermelho"
        ))
        markup.add(telebot.types.InlineKeyboardButton(
            "⚫🔴 OS DOIS SURFS", callback_data="ativar_alertas_modo:Ambos"
        ))
        bot.send_message(
            call.message.chat.id,
            "🔥 ALERTAS SURF — ESCOLHA O MONITORAMENTO\n\n"
            "O bot vai analisar TODOS os pontos/caminhos possíveis das 2.000 rodadas.\n\n"
            "🔕 G1 até G8: silencioso.\n"
            "🚨 G9: envia o SINAL para a próxima rodada.\n"
            "❌ Se não bater: Gale 1 até Gale 6.\n"
            "✅ Acertou: GREEN.\n"
            "🛑 Não bateu até Gale 6: LOSS / STOP.\n\n"
            "👇 Escolha qual SURF deseja acompanhar:",
            reply_markup=markup,
        )
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao abrir alertas: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("ativar_alertas_modo:"))
def ativar_alertas_modo_callback(call):
    global alertas_surfe_ativos
    try:
        modo = call.data.split(":", 1)[1]
        if modo not in ("Preto", "Vermelho", "Ambos"):
            return

        bot.answer_callback_query(call.id, "Ativando monitor...")
        with alertas_surfe_lock:
            alertas_surfe_ativos = True

        _iniciar_monitor_alertas_surfe(modo)

        nomes = {
            "Preto": "⚫ SURF 2 PRETOS",
            "Vermelho": "🔴 SURF 2 VERMELHOS",
            "Ambos": "⚫ SURF 2 PRETOS + 🔴 SURF 2 VERMELHOS",
        }
        bot.send_message(
            ALERTAS_CHAT_ID,
            "🔥 ALERTAS SURF\n\n"
            "🟢 MONITORAMENTO G9 ATIVADO\n"
            f"🏄 Modo: {nomes[modo]}\n\n"
            "🔕 O canal ficará silencioso até algum caminho chegar exatamente ao G9."
        )
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None,
            )
        except Exception:
            pass
        bot.send_message(
            call.message.chat.id,
            "🟢 ALERTAS SURF ATIVADOS.\n\n"
            f"🏄 Monitorando: {nomes[modo]}\n"
            "📚 Todos os pontos possíveis da janela de 2.000 rodadas.\n"
            "🚨 O sinal só aparece quando um caminho completar G9.\n"
            "🛑 Após o sinal, o máximo é Gale 6.",
            reply_markup=bot_controle_markup(),
        )
    except Exception as erro:
        with alertas_surfe_lock:
            alertas_surfe_ativos = False
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao ativar alertas: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "registro_alertas_surfe")
def registro_alertas_surfe_callback(call):
    try:
        bot.answer_callback_query(call.id, "Abrindo registros online...")
        bot.send_message(
            call.message.chat.id,
            _alerta_texto_registro_online(),
            reply_markup=_alerta_markup_registro_online(),
        )
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "atualizar_registro_alertas_surfe")
def atualizar_registro_alertas_surfe_callback(call):
    try:
        bot.answer_callback_query(call.id, "Atualizando...")
        bot.edit_message_text(
            _alerta_texto_registro_online(),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_alerta_markup_registro_online(),
        )
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "registro_sinais_surfe")
def registro_sinais_surfe_callback(call):
    try:
        bot.answer_callback_query(call.id, "Abrindo registros de sinais...")
        chat_id = call.message.chat.id
        with alertas_surfe_lock:
            ultimo_id = alertas_surfe_registro_sinais[-1]["id"] if alertas_surfe_registro_sinais else 0
            alertas_surfe_registro_sinais_vistos_chat[chat_id] = ultimo_id
        bot.send_message(
            chat_id,
            _alerta_texto_registros_sinais(),
            reply_markup=_alerta_markup_registros_sinais(),
        )
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "atualizar_registro_sinais_surfe")
def atualizar_registro_sinais_surfe_callback(call):
    try:
        chat_id = call.message.chat.id
        with alertas_surfe_lock:
            ultimo_atual = alertas_surfe_registro_sinais[-1]["id"] if alertas_surfe_registro_sinais else 0
            ultimo_visto = alertas_surfe_registro_sinais_vistos_chat.get(chat_id, 0)

        if ultimo_atual <= ultimo_visto:
            aviso = "❌ NENHUM SINAL NOVO"
            bot.answer_callback_query(call.id, "Nenhum sinal novo")
        else:
            quantidade_nova = ultimo_atual - ultimo_visto
            aviso = f"✅ {quantidade_nova} SINAL(IS) NOVO(S)"
            bot.answer_callback_query(call.id, "Registros atualizados")
            with alertas_surfe_lock:
                alertas_surfe_registro_sinais_vistos_chat[chat_id] = ultimo_atual

        bot.edit_message_text(
            _alerta_texto_registros_sinais(aviso),
            chat_id,
            call.message.message_id,
            reply_markup=_alerta_markup_registros_sinais(),
        )
    except Exception:
        traceback.print_exc()


@bot.callback_query_handler(func=lambda call: call.data == "status_alertas_surfe")
def status_alertas_surfe_callback(call):
    try:
        bot.answer_callback_query(call.id, "Consultando monitor...")
        bot.send_message(call.message.chat.id, _alerta_texto_status_monitor())
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao consultar status: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "desativar_alertas_surfe")
def desativar_alertas_surfe_callback(call):
    global alertas_surfe_ativos, alertas_surfe_ultima_rodada_id, alertas_surfe_modo
    try:
        with alertas_surfe_lock:
            alertas_surfe_ativos = False
            alertas_surfe_ultima_rodada_id = None
            alertas_surfe_modo = None
        bot.answer_callback_query(call.id, "Alertas desativados")
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=bot_controle_markup(),
        )
        try:
            bot.send_message(
                ALERTAS_CHAT_ID,
                "🔥 ALERTAS SURF\n\n🔴 MONITORAMENTO AO VIVO DESATIVADO.\n\n" + _alerta_resumo_stats()
            )
        except Exception:
            pass
        bot.send_message(call.message.chat.id, "🔴 ALERTAS SURF DESATIVADOS.")
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"❌ Erro ao desativar alertas: {type(erro).__name__}: {str(erro)[:250]}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "testar_canal_alertas")
def testar_canal_alertas_callback(call):
    try:
        bot.answer_callback_query(call.id, "Testando canal...")
        bot.send_message(
            ALERTAS_CHAT_ID,
            "🔥 ALERTAS SURF\n\n"
            "✅ Conexão com o canal funcionando.\n"
            "🤖 BOT ANALISADOR ESTATÍSTICO conectado com sucesso."
        )
        bot.send_message(
            call.message.chat.id,
            "✅ Teste enviado para o canal 🔥 ALERTAS SURF."
        )
    except Exception as erro:
        traceback.print_exc()
        try:
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro ao testar o canal: {type(erro).__name__}: {str(erro)[:250]}"
            )
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data in ("surfe", "seq10", "seqcores", "branco_atraso", "ult50", "total", "ultima"))
def painel_callback(call):
    try:
        bot.answer_callback_query(call.id)
        # As estratégias usam diretamente os 2.000 registros já salvos no banco.
        # NÃO atualizar a API ao clicar, para a análise responder imediatamente.

        if call.data == "surfe":
            chat_id = call.message.chat.id
            surfe_cache.pop(chat_id, None)
            surfe_mensagens_abertas[chat_id] = []

            texto = "\n".join([
                "⚪⚫🔴 SURF — ESCOLHA O CAMINHO",
                "",
                "👇 Escolha qual tipo de ponto você quer usar para iniciar a análise do SURF.",
                "",
                "⚪ BRANCO",
                "🔴 VERMELHO",
                "⚫ PRETO",
                "",
                "📊 Todos os caminhos usam o mesmo sistema do SURF. O que muda é somente o ponto inicial escolhido.",
            ])
            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup.add(telebot.types.InlineKeyboardButton("⚪ BRANCO", callback_data="surfe_caminho:Branco"))
            markup.add(telebot.types.InlineKeyboardButton("🔴 VERMELHO", callback_data="surfe_caminho:Vermelho"))
            markup.add(telebot.types.InlineKeyboardButton("⚫ PRETO", callback_data="surfe_caminho:Preto"))
            markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="voltar_painel_principal"))
            _editar_balao_com_capa(
                call.message,
                _CAPA_SURF_FIXA_B64,
                "capa_surf.jpg",
                texto,
                markup,
            )
            return

        if call.data == "seqcores":
            _enviar_capa_painel(call.message.chat.id, "seqcores")
            resultado = analisar_sequencias_de_cores_iguais()
            bot.send_message(call.message.chat.id, resultado)
            return

        if call.data == "branco_atraso":
            _enviar_capa_painel(call.message.chat.id, "branco")
            resultado = analisar_atraso_do_branco()
            # Telegram aceita no máximo 4096 caracteres por mensagem.
            for pos in range(0, len(resultado), 3900):
                bot.send_message(call.message.chat.id, resultado[pos:pos + 3900])
            return

        if call.data == "total":
            total = contar_rodadas_banco()
            bot.send_message(
                call.message.chat.id,
                f"📚 TOTAL NO HISTÓRICO\n\n🔢 {total:,} rodadas\n💾 Limite: {MAX_HISTORY:,}"
            )
            return

        if call.data == "ultima":
            dados = obter_historico_banco(limite=1)
            if not dados:
                bot.send_message(call.message.chat.id, "❌ Nenhuma rodada registrada ainda.")
                return

            r = dados[0]
            data, hora = formatar_data_hora(r.get("instant"), r.get("tempo"))
            cor = normalizar_cor_analise(r)
            bot.send_message(
                call.message.chat.id,
                f"🕐 ÚLTIMA RODADA\n\n"
                f"📅 {data}\n"
                f"⏰ {hora}\n"
                f"🎰 {r.get('numero')}\n"
                f"{emoji_cor(cor)} {str(cor or 'desconhecida').upper()}"
            )
            return

        if call.data == "ult50":
            dados = obter_historico_banco(limite=50)
            linhas = ["📊 ÚLTIMAS 50 RODADAS", ""]
            for n, r in enumerate(dados, 1):
                _, hora = formatar_data_hora(r.get("instant"), r.get("tempo"))
                cor = normalizar_cor_analise(r)
                linhas.append(f"{n:02d}. {emoji_cor(cor)} {r.get('numero')} — {hora}")
            bot.send_message(call.message.chat.id, "\n".join(linhas))
            return

        _enviar_capa_painel(call.message.chat.id, "seq10")
        bot.send_message(
            call.message.chat.id,
            "📚 COMO FUNCIONA\n\n"
            "Esta estratégia procura, dentro dos 2.000 registros, momentos em que ocorreram "
            "10 resultados consecutivos da mesma cor.\n\n"
            "Depois de encontrar uma sequência de 10 cores iguais, analisamos as rodadas "
            "seguintes para verificar em qual posição a cor oposta apareceu.\n\n"
            "📊 O objetivo é identificar estatisticamente o comportamento das rodadas após "
            "uma sequência de 10 resultados iguais.\n\n"
            "⚠️ A análise é estatística/histórica e não garante o resultado da próxima rodada."
        )

        resultado = analisar_sequencias_de_10_completas()
        if isinstance(resultado, list):
            bot.send_message(call.message.chat.id, resultado[0])
            detalhes = resultado[1]
            for pos in range(0, len(detalhes), 3900):
                bot.send_message(call.message.chat.id, detalhes[pos:pos + 3900])
        else:
            bot.send_message(call.message.chat.id, resultado)

    except Exception as erro:
        traceback.print_exc()
        bot.send_message(
            call.message.chat.id,
            f"❌ Erro na análise: {type(erro).__name__}: {str(erro)[:250]}"
        )


@bot.message_handler(func=lambda message: True)
def responder_usuario(message):
    try:
        pergunta_usuario = message.text or ""
        if pergunta_usuario.strip().upper() == "TESTE 123":
            bot.reply_to(message, "✅ Telegram - Render - Bot está funcionando.")
            return

        # Reutiliza a base de 2.000 por alguns segundos para não fazer
        # uma requisição + 2.000 INSERTs a cada mensagem.
        atualizar_historico_tipminer()

        cor = identificar_cor_perguntada(pergunta_usuario)
        texto = pergunta_usuario.lower()
        ultima = any(x in texto for x in ("último", "última", "ultimo", "ultima"))

        # Último branco/vermelho/preto: consulta direta e atualizada no PostgreSQL.
        if cor and ultima:
            rodada = obter_ultimo_por_cor(cor)
            if not rodada:
                bot.reply_to(message, f"❌ Não encontrei nenhum {cor.lower()} salvo no histórico.")
            else:
                bot.reply_to(message, montar_resposta_ultima_cor(rodada))
            return

        # Para perguntas gerais, enviamos as 2.000 rodadas atuais ao Gemini.
        dados = obter_historico(limite=ANALYSIS_ROUNDS)
        instrucao_ia = """
Você é o ANALISADOR ESTATÍSTICO do bot da Double.

REGRA PRINCIPAL:
- Analise SOMENTE o histórico JSON fornecido.
- Cada registro é uma rodada/evento: DOUBLE=Vermelho, DEFAULT=Preto, LUCKY=Branco (0).
- O histórico está ordenado da rodada mais recente para a mais antiga.
- Nunca invente dados, horários, resultados, ocorrências ou percentuais.
- Não faça previsão, palpite, recomendação de aposta, estratégia de aposta ou gerenciamento de banca.
FORMATO DAS RESPOSTAS:
- Responda em português do Brasil.
- Seja MUITO direto e organizado.
- Não escreva introduções como "Aqui estão...", "Com base..." ou explicações da metodologia.
- Não repita a pergunta do usuário.
- Não faça textos longos ou relatórios.
- Use no máximo 12 linhas quando a pergunta puder ser respondida de forma resumida.
- Use emojis para facilitar a leitura.
- Use SEMPRE data e hora com segundos quando o horário estiver disponível.
- Não use Markdown com **, # ou tabelas.

QUANDO PEDIR RODADAS RECENTES:
- Mostre somente a quantidade solicitada, da mais recente para a mais antiga.
- Uma rodada deve ocupar UMA ÚNICA LINHA, neste formato:
  "1. 🕐 03:32:46 — 🔴 Vermelho — Nº 7"
- Não escreva "tipo: DOUBLE/DEFAULT/LUCKY", pois a cor já informa isso.
- Se houver data disponível e a consulta envolver mais de uma data, inclua a data de forma compacta.

QUANDO PEDIR ESTATÍSTICAS OU SEQUÊNCIAS:
- Mostre primeiro o resultado principal.
- Agrupe ocorrências por tamanho/cor quando isso for possível.
- Evite listar cada ocorrência individual se o usuário não pedir isso.
- Termine com um resumo curto, se houver informação útil.
EXEMPLO DE ESTILO:
📊 RESULTADO
🔴 5 iguais — 3 ocorrências
⚫ 5 iguais — 2 ocorrências
🏆 Maior: 7 🔴
📅 28/08/2026 🕐 03:11:10

IMPORTANTE: precisão primeiro, simplicidade depois. Entregue somente o que responde à pergunta.
"""
        conteudo = (
            "HISTÓRICO DA DOUBLE SALVO NO BANCO POSTGRESQL:\n" +
            json.dumps(dados, ensure_ascii=False) +
            "\n\nPERGUNTA DO USUÁRIO:\n" + pergunta_usuario
        )
        resposta = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=conteudo,
            config=types.GenerateContentConfig(
                system_instruction=instrucao_ia,
                temperature=0.1
            )
        )
        if not resposta.text:
            raise RuntimeError("Gemini retornou uma resposta vazia.")

        texto_resposta = resposta.text.strip()
        # Telegram está sendo usado sem parse_mode: remova marcadores Markdown
        # que deixam a resposta visualmente poluída (ex.: **Horário:**).
        texto_resposta = texto_resposta.replace("**", "")
        texto_resposta = texto_resposta.replace("__", "")
        # Reduz excesso de linhas em branco sem alterar o conteúdo.
        while "\n\n\n" in texto_resposta:
            texto_resposta = texto_resposta.replace("\n\n\n", "\n\n")

        bot.reply_to(message, texto_resposta)

    except Exception as erro:
        traceback.print_exc()
        try:
            bot.reply_to(
                message,
                "❌ Ainda não consegui obter os dados da Double.\n\n" +
                f"Erro: {type(erro).__name__}: {str(erro)[:300]}"
            )
        except Exception:
            pass




def _simular_sequencia_financeira(resultados, entrada, limite=None):
    """Simula uma sequência booleana; limite=None significa progressão histórica sem STOP."""
    saldo=Decimal("0.00"); menor=Decimal("0.00"); pico=Decimal("0.00"); drawdown=Decimal("0.00")
    perdas=0; maior_gale=0; maior_gale_solucionado=0; maior_aposta=Decimal("0.00")
    acertos_diretos=0; recuperados=0; stops=0; linhas=[]
    pior_capital=Decimal("0.00")
    maior_capital_total=Decimal("0.00")
    capital_ciclo_atual=Decimal("0.00")
    for i, acertou in enumerate(resultados,1):
        aposta=entrada*(Decimal(2)**perdas); maior_aposta=max(maior_aposta,aposta)
        capital_ciclo_atual += aposta
        maior_capital_total=max(maior_capital_total,capital_ciclo_atual)
        if acertou:
            if perdas: recuperados+=1; maior_gale_solucionado=max(maior_gale_solucionado,perdas); marcador="♻️"
            else: acertos_diretos+=1; marcador="✅"
            saldo += aposta; perdas=0; capital_ciclo_atual=Decimal("0.00")
        else:
            saldo -= aposta; perdas += 1; maior_gale=max(maior_gale,perdas); marcador="❌"
            pior_capital=max(pior_capital, entrada*((Decimal(2)**perdas)-Decimal(1)))
            if limite is not None and perdas>=limite:
                stops+=1; marcador = "🛑"; perdas=0; capital_ciclo_atual=Decimal("0.00")
        pico=max(pico,saldo); menor=min(menor,saldo); drawdown=max(drawdown,pico-saldo)
        linhas.append(f"{i:02d}  {marcador}   {_formatar_reais_surfe(aposta)}   {_formatar_reais_surfe(saldo)}")
    if perdas:
        pior_capital=max(pior_capital,entrada*((Decimal(2)**perdas)-Decimal(1)))
    return {"saldo":saldo,"menor":menor,"drawdown":drawdown,"maior_gale":maior_gale,"maior_gale_solucionado":maior_gale_solucionado,"maior_aposta":maior_aposta,"pior_capital":pior_capital,"maior_capital_total":maior_capital_total,"aberto":perdas,"diretos":acertos_diretos,"recuperados":recuperados,"stops":stops,"linhas":linhas}


def _enviar_resultado_financeiro_novo(chat_id, titulo, subtitulo, resultados, entrada, limite=None):
    r=_simular_sequencia_financeira(resultados,entrada,limite)
    estado = surfe_cache.get(chat_id) or {}
    estado["gale_avancado_base"] = {
        "resultados": list(resultados),
        "entrada": str(entrada),
        "titulo": titulo,
        "subtitulo": subtitulo,
    }
    surfe_cache[chat_id] = estado
    _enviar_blocos_aposta_surfe(chat_id,r["linhas"])
    modo="♾️ SEM LIMITE" if limite is None else f"🛑 COM LIMITE G{limite}"
    saldo_txt=("+" if r["saldo"]>0 else "")+_formatar_reais_surfe(r["saldo"])
    linhas=[titulo,"",subtitulo,f"⚙️ Modo: {modo}",f"💵 Entrada inicial: {_formatar_reais_surfe(entrada)}","","📊 RESULTADO DOS CICLOS","",f"🟢 Acertos diretos: {r['diretos']}",f"♻️ Ciclos recuperados: {r['recuperados']}"]
    if limite is not None: linhas.append(f"🛑 Stops: {r['stops']}")
    linhas += ["","💰 RESULTADO FINANCEIRO","",f"💰 Lucro/prejuízo total: {saldo_txt}",f"📈 Saldo final: {saldo_txt}",f"🔥 Maior Gale observado: G{r['maior_gale']}" if r['maior_gale'] else "🔥 Maior Gale observado: Nenhum",f"♻️ Maior Gale solucionado: G{r['maior_gale_solucionado']}" if r['maior_gale_solucionado'] else "♻️ Maior Gale solucionado: Nenhum",f"💵 Maior aposta individual realizada: {_formatar_reais_surfe(r['maior_aposta'])}",f"💸 Perdas acumuladas antes da recuperação: {_formatar_reais_surfe(r['pior_capital'])}",f"🏦 Capital total necessário no pior ciclo: {_formatar_reais_surfe(r['maior_capital_total'])}",f"📈 Retorno sobre o capital do pior ciclo: {(r['saldo'] / r['maior_capital_total'] * Decimal('100')):.2f}%" if r['maior_capital_total'] > 0 else "📈 Retorno sobre o capital do pior ciclo: 0,00%",f"📉 Maior déficit: {_formatar_reais_surfe(r['menor'])}",f"📉 Maior drawdown: {_formatar_reais_surfe(r['drawdown'])}"]
    if r['aberto']:
        linhas += ["",f"⏳ Ciclo em aberto no final: G{r['aberto']}","⚠️ Esse Gale ainda não foi solucionado dentro do recorte."]

    # Referência numérica baseada exclusivamente no pior ciclo encontrado neste recorte.
    capital_ref = r['maior_capital_total']
    capital_mais_resultado = capital_ref + r['saldo']
    retorno_ref = (r['saldo'] / capital_ref * Decimal("100")) if capital_ref > 0 else Decimal("0")
    retorno_ref_txt = f"{retorno_ref:.2f}".replace(".", ",")
    resultado_ref_txt = ("+" if r['saldo'] > 0 else "") + _formatar_reais_surfe(r['saldo'])
    capital_final_txt = _formatar_reais_surfe(capital_mais_resultado)
    maior_gale_ref = r['maior_gale_solucionado'] or r['maior_gale']

    linhas += [
        "",
        "💡 REFERÊNCIA DE CAPITAL — NESTA ANÁLISE",
        "",
        f"🏦 Capital necessário: {_formatar_reais_surfe(capital_ref)}",
        f"💰 Lucro/prejuízo obtido: {resultado_ref_txt}",
        f"💵 Capital + resultado: {capital_final_txt}",
        f"📈 Retorno sobre o capital de referência: {retorno_ref_txt}%",
        "",
        (f"📌 Neste recorte histórico, para atravessar o maior ciclo encontrado (G{maior_gale_ref}), "
         f"a simulação precisou de até {_formatar_reais_surfe(capital_ref)} de capital e terminou com "
         f"{resultado_ref_txt} de lucro/prejuízo."),
        "",
        f"⚠️ {_formatar_reais_surfe(capital_ref)} é uma referência baseada no pior ciclo encontrado neste recorte histórico; não representa a banca necessária para resultados futuros.",
        "",
        "⚠️ Resultado referente somente ao recorte histórico analisado; não garante o mesmo comportamento em novas rodadas.",
    ]
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    m=bot.send_message(chat_id,"\n".join(linhas), reply_markup=markup); surfe_mensagens_abertas.setdefault(chat_id,[]).append(m.message_id)


def _receber_valor_gatilho_surfe(message):
    chat_id=message.chat.id; estado=surfe_cache.get(chat_id) or {}
    try: entrada=_parse_valor_aposta_surfe(message.text)
    except Exception:
        msg=bot.send_message(chat_id,"❌ Valor inválido. Digite novamente, por exemplo: 0,10 | 1,00"); bot.register_next_step_handler(msg,_receber_valor_gatilho_surfe); return
    resultado=estado.get("gatilho_resultado") or {}; ops=resultado.get("oportunidades",[])
    if not ops: bot.send_message(chat_id,"❌ A análise do gatilho expirou. Escolha o gatilho novamente."); return
    resultados=[bool(x.get("acertou")) for x in ops]; limite=estado.get("gatilho_limite") if estado.get("gatilho_modo")=="com_limite" else None
    gatilho=estado.get("gatilho_gale"); caminho=estado.get("gatilho_caminho"); cor="🔴" if caminho=="Vermelho" else "⚫"
    analise=_obter_analise_surfe_selecionada(chat_id)
    branco_txt = f"{_identificacao_ponto_surfe(analise).upper()} SELECIONADO\n📅 {analise['data_ponto']} às {analise['hora_ponto']}" if analise else "PONTO INICIAL SELECIONADO"
    _enviar_resultado_financeiro_novo(chat_id,f"🎯 RESULTADO FINANCEIRO — GATILHO G{gatilho}",f"{branco_txt}\n\n🏄 {cor} SURF | 🔎 {len(resultados)} oportunidades",resultados,entrada,limite)


def _receber_valor_sem_limite_surfe(message):
    chat_id=message.chat.id; estado=surfe_cache.get(chat_id) or {}
    try: entrada=_parse_valor_aposta_surfe(message.text)
    except Exception:
        msg=bot.send_message(chat_id,"❌ Valor inválido. Digite novamente, por exemplo: 0,10 | 1,00"); bot.register_next_step_handler(msg,_receber_valor_sem_limite_surfe); return
    analise=_obter_analise_surfe_selecionada(chat_id); caminho=estado.get("aposta_caminho")
    if not analise or caminho not in ("Vermelho","Preto"): bot.send_message(chat_id,"❌ A simulação expirou. Abra novamente a APOSTA."); return
    campo="resultado_vermelho" if caminho=="Vermelho" else "resultado_preto"; resultados=[str(x.get(campo,"")).startswith("✅") for x in analise["registros"]]
    cor="🔴" if caminho=="Vermelho" else "⚫"; _enviar_resultado_financeiro_novo(chat_id,"💵 SIMULAÇÃO CONTÍNUA — SEM LIMITE",f"🏄 {cor} SURF | 📚 {len(resultados)} rodadas",resultados,entrada,None)



def _runs_perdas_gale_avancado(resultados):
    """Retorna cada sequência de perdas uma única vez, com posição inicial e final."""
    runs = []
    inicio = None
    perdas = 0
    for i, acertou in enumerate(resultados):
        if not acertou:
            if inicio is None:
                inicio = i
            perdas += 1
            continue
        if perdas:
            runs.append({"inicio": inicio, "perdas": perdas, "fim": i, "solucionado": True})
        inicio = None
        perdas = 0
    if perdas:
        runs.append({"inicio": inicio, "perdas": perdas, "fim": len(resultados) - 1, "solucionado": False})
    return runs


def _resultados_gale_avancado_por_caminho(analise, caminho):
    campo = "resultado_vermelho" if caminho == "Vermelho" else "resultado_preto"
    return [str(x.get(campo, "")).startswith("✅") for x in analise.get("registros", [])]


def _ocorrencias_gale_avancado(analise, caminho, ponto):
    """Retorna somente as ocorrências cujo caminho terminou exatamente no Gale escolhido."""
    resultados = _resultados_gale_avancado_por_caminho(analise, caminho)
    runs = _runs_perdas_gale_avancado(resultados)
    ocorrencias = []
    for run in runs:
        if run["perdas"] != ponto:
            continue
        ocorrencias.append({
            "caminho": caminho,
            "inicio": run["inicio"],
            "fim": run["fim"],
            "perdas": run["perdas"],
            "solucionado": run["solucionado"],
        })
    return ocorrencias


def _resumo_ponto_gale_avancado(resultados, ponto, entrada):
    """Simula dinheiro somente depois do Gale observado, reiniciando a cada ocorrência."""
    runs = _runs_perdas_gale_avancado(resultados)
    elegiveis = [r for r in runs if r["perdas"] > ponto]
    entradas = []
    profundidades = []
    abertas = 0
    for r in elegiveis:
        restante = r["perdas"] - ponto
        profundidades.append(restante)
        entradas.extend([False] * restante)
        if r["solucionado"]:
            entradas.append(True)
        else:
            abertas += 1
    sim = _simular_sequencia_financeira(entradas, entrada, None) if entradas else None
    return {
        "ponto": ponto,
        "ocorrencias": len(elegiveis),
        "profundidades": profundidades,
        "maior_restante": max(profundidades) if profundidades else 0,
        "abertas": abertas,
        "resultados": entradas,
        "sim": sim,
    }


def _candidatos_gale_avancado_caminho(analise, caminho):
    """Retorna o maior Gale e os pontos viáveis somente do SURF escolhido."""
    resultados = _resultados_gale_avancado_por_caminho(analise, caminho)
    runs = _runs_perdas_gale_avancado(resultados)
    maior = max((r["perdas"] for r in runs), default=0)

    if maior < 4:
        return maior, []

    inicio = max(2, maior // 2 - 1)
    candidatos = []
    for ponto in range(inicio, maior + 1):
        quantidade = sum(1 for r in runs if r["perdas"] == ponto)
        if quantidade:
            candidatos.append({"ponto": ponto, "quantidade": quantidade})
    return maior, candidatos


@bot.callback_query_handler(func=lambda call: call.data == "surfe_gale_avancado")
def surfe_gale_avancado_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        analise = _obter_analise_surfe_selecionada(chat_id)
        if not analise:
            bot.send_message(chat_id, "❌ O recorte do SURF expirou. Escolha novamente o ponto inicial e a quantidade de rodadas.")
            return

        texto = [
            "🔥 GALE AVANÇADO", "",
            f"{_identificacao_ponto_surfe(analise)}: {analise['data_ponto']} às {analise['hora_ponto']}",
            f"📚 Recorte: {len(analise['registros'])} rodadas", "",
            "📌 COMO FUNCIONA", "",
            "👁️ Primeiro escolha qual SURF deseja analisar.",
            "🔎 O bot localizará os Gales encontrados naquele SURF.",
            "📊 Ao escolher um Gale, será mostrado o caminho completo da ocorrência:",
            "1 rodada antes → G1 → G2 → ... → Gale encontrado → 1 rodada depois.",
            "🎯 Assim você poderá acompanhar exatamente como o Gale se formou, rodada por rodada.", "",
            "👇 Escolha o SURF:"
        ]

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            "🔴 SURF — 2 VERMELHOS",
            callback_data="surfe_gale_avancado_caminho:Vermelho"
        ))
        markup.add(telebot.types.InlineKeyboardButton(
            "⚫ SURF — 2 PRETOS",
            callback_data="surfe_gale_avancado_caminho:Preto"
        ))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, "\n".join(texto), reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro no Gale Avançado: {type(erro).__name__}: {str(erro)[:220]}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gale_avancado_caminho:"))
def surfe_gale_avancado_caminho_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        caminho = call.data.split(":", 1)[1]
        if caminho not in ("Vermelho", "Preto"):
            return

        analise = _obter_analise_surfe_selecionada(chat_id)
        if not analise:
            bot.send_message(chat_id, "❌ O recorte do SURF expirou. Abra novamente o Gale Avançado.")
            return

        maior, candidatos = _candidatos_gale_avancado_caminho(analise, caminho)
        emoji = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "SURF — 2 VERMELHOS" if caminho == "Vermelho" else "SURF — 2 PRETOS"

        estado = surfe_cache.get(chat_id) or {}
        estado["gale_avancado_caminho"] = caminho
        estado["gale_avancado_candidatos"] = candidatos
        surfe_cache[chat_id] = estado

        if maior < 4 or not candidatos:
            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup.add(telebot.types.InlineKeyboardButton("🔄 TROCAR SURF", callback_data="surfe_gale_avancado"))
            bot.send_message(
                chat_id,
                f"🔥 GALE AVANÇADO — {emoji} {nome}\n\n"
                f"🔥 Maior Gale encontrado: G{maior}\n\n"
                "📌 Neste recorte não apareceu um Gale grande o suficiente para a análise avançada ser útil.",
                reply_markup=markup
            )
            return

        texto = [
            f"🔥 GALE AVANÇADO — {emoji} {nome}", "",
            f"🔥 Maior Gale encontrado: G{maior}", "",
            "🔎 Escolha qual Gale deseja visualizar.",
            "📊 O bot mostrará as ocorrências desse Gale com o caminho completo.",
            "👁️ Cada ocorrência mostra: 1 rodada antes → G1 → ... → Gale escolhido → 1 rodada depois.", "",
            "👇 Escolha o Gale:"
        ]

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for item in candidatos:
            ponto = item["ponto"]
            quantidade = item["quantidade"]
            markup.add(telebot.types.InlineKeyboardButton(
                f"🔎 GALE {_numero_gale_visual(ponto)} — {quantidade} ocorrência(s)",
                callback_data=f"surfe_gale_avancado_ponto:{ponto}"
            ))
        markup.add(telebot.types.InlineKeyboardButton("🔄 TROCAR SURF", callback_data="surfe_gale_avancado"))
        markup.add(telebot.types.InlineKeyboardButton("🔽 OCULTAR SURF", callback_data="surfe_ocultar"))
        m = bot.send_message(chat_id, "\n".join(texto), reply_markup=markup)
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao escolher o SURF: {type(erro).__name__}: {str(erro)[:220]}")


def _recortar_visual_gale_avancado_caminho(analise, inicio, fim, caminho):
    """Recorta somente o SURF escolhido, sem montar duas colunas lado a lado."""
    registros = analise.get("registros") or []
    if not registros or inicio < 0 or fim < inicio or fim >= len(registros):
        return ""

    trecho = registros[inicio:fim + 1]
    numero_final_analise = int(registros[-1]["numero"])
    linhas = _montar_linhas_estrategia_surfe(
        trecho, caminho, numero_final_analise
    )
    titulo = "SURF🔴" if caminho == "Vermelho" else "SURF⚫"
    return titulo + "\n\n" + "\n".join(linhas)


@bot.callback_query_handler(func=lambda call: call.data.startswith("surfe_gale_avancado_ponto:"))
def surfe_gale_avancado_ponto_callback(call):
    try:
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        ponto = int(call.data.split(":", 1)[1])
        analise = _obter_analise_surfe_selecionada(chat_id)
        estado = surfe_cache.get(chat_id) or {}
        caminho = estado.get("gale_avancado_caminho")

        if not analise:
            bot.send_message(chat_id, "❌ O recorte do SURF expirou. Abra novamente o Gale Avançado.")
            return
        if caminho not in ("Vermelho", "Preto"):
            bot.send_message(chat_id, "❌ Escolha novamente qual SURF deseja analisar.")
            return

        ocorrencias = _ocorrencias_gale_avancado(analise, caminho, ponto)
        ocorrencias.sort(key=lambda x: x["inicio"])

        if not ocorrencias:
            bot.send_message(chat_id, f"❌ Nenhuma ocorrência de G{ponto} foi encontrada neste SURF.")
            return

        estado["gale_avancado_ponto"] = ponto
        surfe_cache[chat_id] = estado

        emoji = "🔴" if caminho == "Vermelho" else "⚫"
        nome = "SURF — 2 VERMELHOS" if caminho == "Vermelho" else "SURF — 2 PRETOS"

        intro = [
            f"🔥 OCORRÊNCIAS — {emoji} {nome} — GALE {_numero_gale_visual(ponto)}", "",
            "🔎 Abaixo estão as ocorrências encontradas.",
            "📌 Cada desenho mostra 1 rodada antes do G1, o caminho completo do Gale e 1 rodada depois.", "",
            f"📊 Ocorrências encontradas: {len(ocorrencias)}",
        ]
        m = bot.send_message(chat_id, "\n".join(intro))
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        registros = analise["registros"]
        for n, oc in enumerate(ocorrencias, 1):
            inicio_g1 = oc["inicio"]
            fim_run = oc["fim"]

            # Uma rodada antes do G1, quando existir.
            inicio_visual = max(0, inicio_g1 - 1)

            # Em sequência solucionada, fim_run já é a rodada imediatamente
            # posterior ao último Gale (a rodada que voltou a acertar).
            # Se a sequência ficou aberta, mostramos até o último registro disponível.
            fim_visual = min(len(registros) - 1, fim_run)

            rodada_antes = int(registros[inicio_visual]["numero"]) if inicio_visual < inicio_g1 else None
            rodada_g1 = int(registros[inicio_g1]["numero"])
            idx_ultimo_gale = min(inicio_g1 + ponto - 1, len(registros) - 1)
            rodada_gale = int(registros[idx_ultimo_gale]["numero"])
            rodada_depois = int(registros[fim_visual]["numero"]) if fim_visual > idx_ultimo_gale else None

            cabecalho = [f"🔥 OCORRÊNCIA {n}", ""]
            if rodada_antes is not None:
                cabecalho.append(f"📍 1 rodada antes: {rodada_antes}")
            cabecalho += [
                f"🔥 G1 começou: rodada {rodada_g1}",
                f"👁️ G{ponto}: rodada {rodada_gale}",
            ]
            if rodada_depois is not None:
                cabecalho.append(f"🏁 1 rodada depois: {rodada_depois}")
            else:
                cabecalho.append("🏁 1 rodada depois: ainda não disponível")
            cabecalho.append("")

            # Usa o formatador já aprovado do SURF, sem alterar o alinhamento
            # nem a montagem dos registros originais.
            visual = _recortar_visual_gale_avancado_caminho(
                analise, inicio_visual, fim_visual, caminho
            )
            m = bot.send_message(chat_id, "\n".join(cabecalho) + "\n" + visual)
            surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(telebot.types.InlineKeyboardButton(
            "🔄 TROCAR GALE",
            callback_data=f"surfe_gale_avancado_caminho:{caminho}"
        ))
        markup.add(telebot.types.InlineKeyboardButton(
            "🔄 TROCAR SURF",
            callback_data="surfe_gale_avancado"
        ))
        markup.add(telebot.types.InlineKeyboardButton(
            "🔽 OCULTAR SURF",
            callback_data="surfe_ocultar"
        ))
        m = bot.send_message(
            chat_id,
            "🔎 GALE AVANÇADO — INFORMAÇÕES\n\n"
            "📌 Escolha abaixo se deseja consultar outro Gale ou trocar o SURF.",
            reply_markup=markup
        )
        surfe_mensagens_abertas.setdefault(chat_id, []).append(m.message_id)

    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro ao mostrar as ocorrências: {type(erro).__name__}: {str(erro)[:220]}")


# ==============================================================================
# WEBHOOK DO TELEGRAM
# ==============================================================================

@app.route("/" + TELEGRAM_TOKEN, methods=["POST"])
def receber_webhook():
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as erro:
        print("========================================")
        print("ERRO NO WEBHOOK")
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))
        print("========================================")
        traceback.print_exc()
        return "ERROR", 500


@app.route("/", methods=["GET"])
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

    webhook_url = RENDER_EXTERNAL_URL.rstrip("/") + "/" + TELEGRAM_TOKEN

    try:
        bot.remove_webhook()
        time.sleep(1)
        sucesso = bot.set_webhook(
            url=webhook_url,
            allowed_updates=[
                "message",
                "edited_message",
                "callback_query",
                "channel_post",
                "edited_channel_post",
            ],
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
# INICIALIZAÇÃO
# ==============================================================================

if __name__ == "__main__":
    print("STARTING DOUBLE BOT")
    print("====================")

    inicializar_banco()
    _carregar_configuracoes_permanentes()
    _iniciar_persistencia_configuracoes()
    carregar_historico_fixo_tipminer()

    try:
        print("TESTE INICIAL POSTGRESQL:", contar_rodadas_banco(), "rodadas")
    except Exception as erro:
        print("⚠️ POSTGRESQL NÃO RESPONDEU NO TESTE INICIAL:")
        print(type(erro).__name__, str(erro))

    configurar_webhook()

    print("====================")
    print("TIPMINER TOKEN: SIM")
    print("BASE FIXA: EXATAMENTE 2.000 RODADAS MAIS RECENTES")
    print("FLASK STARTING")
    print("PORT:", PORT)

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )
