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
    "direto": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgwKCA0MCwwPDg0QFCIWFBISFCkdHxgiMSszMjArLy42PE1CNjlJOi4vQ1xESVBSV1dXNEFfZl5UZU1VV1P/2wBDAQ4PDxQSFCcWFidTNy83U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1P/wgARCAC0ANkDASIAAhEBAxEB/8QAGwAAAQUBAQAAAAAAAAAAAAAABQABAgMEBgf/xAAZAQADAQEBAAAAAAAAAAAAAAAAAQIDBAX/2gAMAwEAAhADEAAAAeYSOADRvSHNo+CSi6QJJxJSklBWb0hamzcFJm2SuCuJYaKtaKyq20xZb3/Ad+PzQyGITlpqqoSal5VpB5ySqlZFIgnnlhh6AQYb5m+so6FUkh9XAyH1tFR+gaoJsLt06DGHBSGzvuB74fms4JKag6Ts7ia2M5mxtj48+I/z++9LR9cGG7gBOULa9VWaOiqrhGyFVFWG5gTV0nNTno7/AIHvturzZpKZaSsSjZtJRiCl0AeJrv32qef0G5NgoHZVQOZuqIGRORnPnrTmYYnJ0w29BRXRkEwi2Gm2nvuC73TbzayuSmZ8H1meFuWkFOPVgbRY+socQsy7ZUpltDE0D8ewXr19Vlnny5IUVQ06unBks0c+iuDOwFU69evT33A99enm83aYs6jmOkx4sVVe1K0OYDOjazZcuYqD301q+3HJShjtv2Hqq8OHHpzYte3UbWWnDi2wjF0DZtvR6Nfe8F3umvnyhdljIsJIZ82LVNkpYJ56shlsxDJZ4VD32jblO/FXS2RmOvS3j2g3qosxgSnN88Aemunfsu77ge+1386smXjIJubJEbRbvem6+jHOex9uqrFXaJzNVl1cxVW5JsPDQQqgt0BwbRpPAO/YNYHr176sd33KdZVeazgUBtIjXMZJNWjTl05hdOqNVVOOeKRCvJMBhcSQbwbRXRDxc8YEBqrtozymTE627MLbL0p73gu9qvNj4DTnjqGbsDe7FdSPbDK6Vyocd8880tWkdKc76aoutN2B2yCHOjeOUardhvzsLWYoxi/e8D32vV5xW7iZ5wCyDpJ3ZOmlFwjOuYpKKB4vEHlCQ0mcHhKIraJslFW1N7+74HvRh3SB0kDOkCSQJkgTJA7JA6SbSSBJIEkklJIGZIJlUm//xAAsEAABBAECBAYDAQADAAAAAAABAAIDBBESExAVITQFFCIjMTMgMkEkMDVA/9oACAEBAAEFAv8AyEEflU7rhtxOriGPzsNdjoY4o9g/P44QCdTkbF+MUZlfdATGOeRBKXbb0YJWoRSOZU7rgZJdkSTNj1vjY6RzmfjXrOmU0W25pw6Z72QlRxOkL2FjuEJ2qULmRlmmKwbETkbDHh9mEnciFap3XAy5YZEcmP4XRZC6L54QSdLTZNytHrlbJ5lEdaoe2K3KJX8I5yyMYqxRy6ZC4Fu97uv2lU7rhqctTlqcvniEAi3CYdLppgyWQtiiik25XNi1yzZprHEkn8GQvent0Pqd1/wBRjUpW+lWuowiMJvzZ6QNCIRHDHBoyYoogC5OOXVO6/LCwsJrtJc7PAzYYLcoRsyFMmGZTvSacDCcEyPo85LmprNRbpja6TVGqndIcQFHWkemUk6l0cNLmU9bPJBCkxOqMQox58lChThCmijiWywt8qxCmxNjEr/IhSMDVFVcY7MMkY+FhVe74BYVKAYcU2djjrVx3vMPtT2BCo5txkz/AGaspei7AF9T2d1NPpns7J8+FRfmfUr/AKX1Xf57/WHCJVTu+LVF0gtu9iq8MmdbaFNJuv8A5f6qoNNaw7ENH9fleRbiWPblB6TQb6lp6GUftyrLdyCsfYufQeFTu+AQXwLZ9qvTa5nlIApGsFrKwEXK3uZq9I3P0s801SO1z5T52xmadroqX75QdkRjQ2126/lXuk0ZPwY+sjj6rh9MUjS3Uvm5lOcd/V1lOY2H0O9TBVlKMTmPJ62QXLQVV6O1KN/pDlN1gTANqr3Sj/Z37QfcSrOSoWGOLKjObGVIdMrv2k+tn14K1OCkeTJ/Wvc1b71H9mVGffR6xY6MPtVe7QPVvVQ/aUCQnOTpBiBwY4ztT37jjO5F7nAPkAE0qMspRc4neem2SFv5UcgD9bE92LBbkhvQfrn01e7WlwTfjKbZT7fRxLjBAHNJgC9lB0IWqFB8KEkK3oUZYVuQovhWqFZhQ8uVPAGcI7EjF5slZ6Kp3akd6oI4bEU8Bidpxwwnu9nK8Pgjna2tVsNpV2SR0oIpK/l688NSCKStKaemGGpMHsgmmMNOOS7B5eXKDv8AOg1YUMLpXS1GwRUw3d4DoY7JL7sBiQHB/wCi8J+vwr5ofX4d1pAMpU6GPI2hXDfCvp8P761/2ni/7pv1LKq1t5Gztukc95qd1wZHmh/BZeYT04O+teGuDWQ7NRtF42aTwKVZwlo0y3yc9Zkcfhrg2KrIIrT4GS2fEpmyypv1IJ1l+18KaLar1O64HG5a0Pb/AGRo0KMhzDGttba0LbQhBXlW4dA0LbCEWUKyNVNrKbSxqDWiJQe2yZgdDV7rgZdUdh2GrX+fVdV6l14dVkrJWXI8HSZCYTJHJINFTu0fwwgMnQ5aDnSUWOCwtDlocgxxWkoghBpI0OWkrSVocvg6ccM9FU7ngFgcM9B0OorU5ZK1u4anLUVqOdRwSSskLW5aitblqKPUk9AvTwqd0uWQLlkC5bAuWQLlkC5ZAuWQLlkC5ZAuWQLlkC5ZAuWQLlkC5ZAuWQLlkC5ZAuWQLlkC5ZAuWQLlkC5bAuWwLlkCZ4fDG9f/xAAlEQACAQQBBAIDAQAAAAAAAAAAAQIDERIhMRATIlEgQQQwcUD/2gAIAQMBAT8B+NzL4Rd18JuWrCcvvpcuO+Q7EpWRFlRNrRS5b+vjbozueViQkuC2zITEVKqhyUarqN9WxzMmON9j/hp8ol47QlIk5aQpYEr1P4U4qHRk5WIxzTkUozb8uCEs52JNqpiVJYysiPbb0QmnLY8VBtEKu9il5WF0ufk/RGThSuinUlK9yMG3oo+Mrko5TI04Q4KdNSlscFGm0jt6I3zTJPEQ9O5W3IyvDAhC0WU4O+yNNodN3IU7M7UhRlZ3IRvdCauhrLo+BqL5IxUeDcjFmB2RUhQHFkG/scYsQmMa6Q4MjIcjJcl+i5ZbrUi21Yp3cdkE1yYO+iz9jv7N+xJ+y0vZjL2RjYgn9nll8F+lf4f/xAAkEQACAgEDBAIDAAAAAAAAAAAAAQIRIRASMQMgQVETMCIyQP/aAAgBAgEBPwHtsv6HZnSyx86N4EMj3s35oYjyWJ6SmokJuT1Y2WxxvJk58EsZRtkPdwXtHciK26MbEryRTfJF2x80PDoW0TyYqxSL8C16mBOokZNiIOmPMhRSIxtjVRZQv2G60fs6nJu/HaRjhkYuxRY4kY0zYxJ0RQuTnRjryJJHJtNp8Z8ZtKIspC1a0iWWWX2VrKyPAjaZM+zPsz7KZTEqEZv7V/D/AP/EADIQAAEDAQUFCAICAwEAAAAAAAEAAhEQAxIhMZEiMkFxchMgM0JRYYGhMKJSggQjsUD/2gAIAQEABj8C/wDJj3rLqr/qYx5uSdraBViy7suaCR8KyPZNIM3nXohBwZZu2ji90fhvkYd661MYzHsxioYCT7ItFm6RmIW6cpWNm4fCvhhLfVWXVWL7d3+OMc1dD23g30xAVm4WjdibuCDcIBnve3uoobQzFoMvSkNEqDnUvbvFCyG2X4uKtGmYgtwCgueA0tgxnCLtq/dcLseq4wScbvsuzDpImJarLqrFx27Hsi7szfIiU1t04UyWS3ftZUFlwJUu45FCd3Mq1s/Xdo9w2R/JAjGBE+tXMiQVObyi84yojir92MOBV33pZdVd4reOq3jqse8CnMeJsyiGOm//AMQcEbRx2DiGjinnKdkDu49zAfKLc4Vl1fls3erB3LJnz38cFI2udCVZdX5Wi60x6rC6P6rGNFtMYVIECI7l51YUBEill1d7dw9Vi8LZcCoQcXRK8T6W/wDSzW0dFxXFCEMSt4re+ldmFvosUtjFbWSNLLq7vaPHKkNdNPhN5ISJlXgnIzwCJW6EMIQ5IYTK3ftHlQPHFNTedbLq7rB7Jyl2ULAFA0ahPFOTlC8T6V2ZQQ2gIRdfbgjyofUYpq+a2XV3QKB735+gXmPyg1ggSKYgGgv5cIXyi70WRUigBnFOGKPKse6NCrLq7jR7ooKG+UUHOgE5imNHAei3HaJocCKNih5Uj0MUfQqy6qlM50C2szQn0FLMooptbPnTA0tKPb60f0o0suqpTaYLE4+6wMlGZyWDNSgshooUAlbztVi52qBPBZrFoPwt0J5I3lnqFeb6rDIp3Io0suqmINdpoK2GtHwpKv2hhv8A1eH+y8P9l4f7Lw/teF9rw/teEF4f2vC+14X2vD/ZeH+yxs/tBzDLTTAlYgGtl1UkOQnC09lGfcsxR5tBMJ3YkghPNoMQYzRfaCYPqnOsJBCNpaDKeKHZzMoljSYVmz/HwneTbJwN8oBu6aPHuO5DVec6SgYbnhWQYUWmM8VLd01Zypac1a8wrfrKcDxJTi0l8p17LGU3sHEnirTmmfKs/wCqs+Ro74rLsGqLLMKXulWXVVzzne2admcedWcqPkgYp57UGVayQJKeCRxRsnOAOSLHOAmVeba3vZPkjNNc7JMtxaiAmhpm6KO+K9kIj2WCYX+I45eysuqtlZ5MaL3NC2YIvZ0lopdJg8FvN1W83VbzdVvN1W83Vb7V4jFvsW+3Vb7dVvs1W+zVb7NVcaZ9TTHPOgfF60dup7i6/aDMqy6q3DnwKbZjIUj8HFce7muNcqBuTW8V2dnuqy6vwZKKHDKnzC+YUe8UHuiRwX0h7/gsurv4LNZ03jTPNZqZUSsSs1nms1ms1JrlSy6qefVZv1Xn1Xn1Wb9Vm/VefVefVefVZv1Wb9Vm/VZv1Wb9Vm/VZv1Xn1Xn1Xn1Xn1Xn1Xn1Xn1Xn1Xn1Xn1QcL0j3p/8QAKBABAAIBAwMEAgMBAQAAAAAAAQARITFBYRBRcYGRofCxwSDR8eEw/9oACAEBAAE/If8A1r+dLSrLPH8vjeukhyUbxrtHVmaGrDezVWAdYO4I6mGkyVFF6fxDotZ/y1RJX8Dus6vaDo6F9vM4HUIzh4xNDcWjY3jAXFpfZHIrqDBPjep3kht9nHb870S4o/KALN6kUtGADv1roS4Sgaqlk9SUDWjLRdYcZMvaXEYGg2Y9KL5Ne2amChbmXuDM2JcoGMDlVUohgJ7i3frLXjcilXXPdirZCWrdc4nwvVF1gzfdURQC42eaj1kXNd5TqE8wf9If6ZcDQwSBHsFndagkdmk0lOxGXiZXWFjxHNEstU+EQhopbonSprSXtM8r6/aIYtqghOxOveJRkFD4I2FXFrvp8b1/2OspK5JfPUX0bkTsjcsQW67XuQNL3m0MiyNyvVyBldo1SGgtoFxiokqbLRR1qdt+7BMwchPhf5VKgTCCbnqiM9UCDSOsy6J5db/HVaIkWF010ARU3YUz+/8ASVC9pzIz4XpXUIELw6bXEoxMxLGGhygtDwCI3Z5kRfTKlbQACHT6IJstiNi07SjSNSi0IGr3gItunwvRRKYEshglO5gmHF8TdB20jsyk1lbNF1UCgfVMUqr5m4hVw7LL2rlwbbnMGjkLimntSxa2ND6rnYHtE0M3ACetDSQelMtA2ej4jqhKfeEPzBsd5vrgmZxLE1feKx4wS5wQqhNqYx4Y69hHE2ItZ96P2jsz2dKDi5TFr9IVy7oZy/kHzGr8/mOK7nBM2NJ8D1JqjkKat8Qw1BTXN5xMO06VBoHaOhi7slgXN8TBuSODarhtN+Uvjh3lXinMlrcW/AXWYq8jorPAnzH5jsvYxXGfAdaThDwgEqB3YzgpdQ3YvMYzMVczZa2pyXEYqwPaTLgGC6XiDn7IGxLMGoRHggNbJuT5T9dNW9ycPtXvFfnIyrbtPjelTEUGHkAT3yXyAPYBfRd7ymMXdVgL3jSkNtVIyoeWJBKqoIFciYVdyZfmYiXWU63PtuOhl7m6B1uL+ejmTOZ8L0w9EykPmTPKmLUNaHunYjNHbktPIv7nz4/h/Mu85+4HoMR6sB1tafiOrzNRjxFilvyT8/8AJGKPT/MGOhygmACz3nxPSqal1MZWiNpJU4hF5Qzq4I8mjQqHMkLhQVsSw4WHi0eCGig7MDpBrgi8ZdM769QgleSMSs+jZGDV2S3eQBUsAiTKHcJgH7EVQ1DmfE9HQLyR1OzvKQve+k0nIln5lrFXdjVotAaqYQTC9/3RjX7pc/3w/wD1nZ/dMH7Irb7o9p7or/rH/Whd/dHhQ5JEX90MSmMY3jSN66pLCmanT4HoKM7fMO1QUqzF2FNyLGdYmYRQXSn8xlSFgFNTSKu7cPrLPO/DaLNSZtpUsXyDr6xqaqyLQnZU3rpvAbCptSLkpNm9PWIUaKrCQKNl7Qm9n0uJ0FEFFruzPHtBoR2zphnoBDRYGk1KsLSkzb3boYI/cfmXH7L8R/U7xfY2hElAF7YhzTMe64I9tvdxMua1O0f09ovo7MXv/lPpO8I/f/abQ2yypTq94xCZS9Zb0vMFeJ0SDo0P0fvEstesxmBpwnY0dJc+Y/PTP+DV4jWpd7Q6IO0vEB6XQvEG8LFvqQyhQyyvhWGBD8S73iaI1bZiSFo3rmASFCneBBXnhYbb2JkwLWlTFAZleKS8KT4HqrJPVggpcVDnvNjNLFZ6BjBqdGZenOk1Zgs394wyH3oh+6MkMKySgkuclOO7uy08RlzK8kHNzTdFF0OZdnQ9jgj9p0GnMoxEOXaBoNvpdFGHqq7szMynmBygdsaNIfKZ5nkzlZzodyF0djAqXEUma75hytz3nwHSqXv0u4FsTeI1R8zA9ms24u61iLSd4sGiLfEtjmIXxubzBdepvEDd3JjHvzFAjYsgUY1RJRNG2d5m9AzDHjCpd4xODetYmB2iLGr0sIvDr0oVa06Lc1Z0nCxdtOgm5UzVyyVFG73MQXgn4TWZi15ZWwPfrc3xetzfFdooKNd4EQQOpFrz3MX13XAAB0aEx1bW4lEtZYPmZOYg3erGL2HTn+niAfR+JzQe/wBSAOSHJDk6kIfYf1PsP6n2H9T7D+umOeHPDnhzw54ckOaAW8OaHPBj7tl9H//aAAwDAQACAAMAAAAQIY7idZEphDJGV8tyBshzrnrAzVRUCedjdGdiQEEwJ0Wih+Y7021/Y1N/N5/4pEfRev6g4/EN7YZihACwEmK+KArr3yadaC/Hh/ofQDMqXsJRToE9YZ0RIPfsDbznrd+1ZZ/op/4S8AOjdJFsMdVl8IRItWjiDDDffAcA/iic/8QAJhEBAQEAAgEBCAMBAAAAAAAAAQARITFRQRBhcYGRobHRIMHwMP/aAAgBAwEBPxD+LEEMMoGty38AP1epqaz6f7N+csvxcpLFslyJaHMbPI+ZbSO+Xl8/17NiQe7Hi3JXHSAo3KTKCbY21kZxA7EpMD2bYXin1DLYY5k8bo+J+7i/RLCP3k9/mDidyYMtgPEEQi5WTmUR5LWiZj6bAOttnqIch97IviKHuRJOs+35/uPmJC5NAEODdXZ5dAZQrM5tCjdthfVnFfOQk6s/u7CUnpLU9UsW3S5EOO+JYAlTnZkPQw5mhc4ycnTLlHP8XwIxCbQZxe8WknD3x1JeVmhuiWIu8Wx3LfWUvf4/V6A/76SnreVdKIdXC0kWicdWLzY+p/MgckA+6AuDEg4ZRNhuHn+i78QmxJHvff1+U9HvZ8PSAyYJWb7EIT27RwmCAL6rHked5+G/r0+sdRwQ71aO7S4vjcXFxcXFoNYR6gyY/wCTHs//xAAjEQEBAQACAQQBBQAAAAAAAAABABEhMUEQIFFhoTCRsdHw/9oACAECAQE/EPaxJDDbkO8+xjMh8pZXxcrUc2w0T4ipxPVTr28Wy9NyyB1tiA272sJ4iOZlxx6bLJfE+QtHCcdn5uBzNFCPJZZjuFky249R6j0c3NgYh8LAJZTMEE8RuGQIRKDHKH5iXXJYJd87nH6IK6S6psOSTUYsWEwwsWbjbDsdXBnIWnAkGjaTiMiyqu3KM2JbO6J4kYk6xDTmC4F1Ni920nct8297/j+o+D/v2hnmX8yeZVhDNo2LdLG2CRY7tCWDVu8egSZNdMU7tDo2fKSEgI+yc+7NFDmHi+/xF0W71H3aXHpx7dBzDsTH6THp/8QAKBABAAIBAwIGAwEBAQAAAAAAAQARITFBUWFxEIGRsdHwocHx4SAw/9oACAEBAAE/EP8AxIEqV4Klf85i0rt1on/X1vPgawDyABQXsEcGsYbW6UiV1vUhBVb6SULzR02jy0V9loyXiMWDKg2HT/gJbL8RAAywnTqKWWHSzaVteBIkYHm4mh3WBqCtl0Ur1Z85h9a5jRqzIi8FfGyCCHAeTI9gj6R9UbAWC30My0RNq0a2wfd38LqDhapoEGxwhV3LJdIpa9orsOl3CdhZCzNZnXeEvRq6dXljwrwVDmEPx9IXx3hMzSSDVmhqWGgcsvk9SK5mKF3QuPrSkKSCJFJF116DyNfOZJM0RsvPR469ZpteGjDXSZHdK5dZeFuzLUpnZERDMmAMitopKzJi9valZxiCOYluilPIOtxrf9XxCitAqKDCmuLiwIWXUUimtdZQ3W5M2OnSLKc4FQRm7H9LCv5Jheo2rKJYHYgkOm2u011KBkaV3OJu+KNjl+POGQg6GdAeQRgKM6QIiFUzatA3OYkoC1IatfdPASPAi10Jw30hwucBv07N3eJCvaqyo3o8TLiFMapZp01lmbhVU6LI6FHkQ27m5l+Xh9bz4gAAhoXn9xP7j5j9l0tXAgTS7x70jadDkgn1MeTcy3o7qr6DmPH7rjmnhX2iiAXdDNhMohb0AwEMsJAtteR4ifCaN2udA0JUqCZVqX/qb+UxlSpChZ97z/wQIQeBChNoZFCakIKal+UNMwvKzuCn2mLEPaLgC1iq8IP50/ctFTSWOnikogW6YiSy+tUXR2gsncqfwIOyC4zTajPvefDRZ4B4jtIhqYl6sLJfzGicwbzIkrm34YdqtdNN4TNElSXeBhtA1Lt8yPm6jug6+cpRM6sqiuJcah0eS7xx8CFVwvUgcddV0DllbNUmq5ZhAKK3GMP3d/ChzpO2eA6oIiZd38jrDoocWZlvIWqLLfQdpjFsWKXMFo6f7iFudR8yiQDgRBVNEHoT5mzfmS4tDmviYIgrDAQ3tPQbk0Y9z8zEwM0jP5lhZEIXgr5muO7uWpxRxm+Y74XVarTUQwFIG3ygSuGkg3ocxmHT9/gTQfxwiib9Y4ITWmW69CWLWDV0CNxCXRDSsr2ql7wOCH8ETr+hYKqCgtq2EigKJcepH1Wgeb/kNgVkHeiJsB4swMb81LtPiLXx7BGerVvGq8omxayvoRriBF8YlGqNEQNLgf57QFrT9kVLmv0g6p1ISi4MFz7XnwCCKhekEbGL5uf3EKsk9UQHhoXalE9QVQwBaqm505B6TKWlsUQgG+Lx7RudVp1WLqwfhlHMBL4hCK8pUghGJV4vSUDgH4ljtFyuuCF2/gbPbEun0xBSpyw80/y4dg4X3I/0gMZ2sE+358CUakosJZx+MJnD+MaSkcwHqsRegs/BDIDQJvJbbCx3iGSaJ09YbqLWBwRxC7z2ufPvA3t/aEQwLBqSWoDuIqRp4dsStp0ajIiLEWQNLHMEqdOAHMKnqpqHSdT2Nj3hF4X8xQdBs/LD93fwY4XTb2hgUjmf3jEhWbW94gxxb9/ER6wgo0/yPJlnNl6Bf1CjWUI20IKZjsnSBBoZ0br9zBsC35D9QyDwLVriGRn5UwwwXFzcN3vE3hDYdpSUg6xq+r3hoy4VLO12fv0i4tnTA+gSmDjVk9tI/q7+GX0UN3rcu6A9Gf1HU3rHTJZyF54lFHaM0UWbXlqLCygyfKpZHs8lnthG1Gg/eIZ/oQOg5X1UcGxyTPj842DIl5RCqju95jg9ckmCF0H3jTGWWxBczrgXsZP2ecUZ3ifQuOgXVQbQJoeukP1d/CyekKHJf1LXsKod0Q8C/A5GpQlaJQpzmFtTxqDrfSIfLxb1HftKMx5+Ejh1NFjW+8fmjKh/cV1QpAPYg+LoKCB4XmjV9wUbhq0uRu4G5HcfqLeqv0Km5Fy+SZJCKRZaO/aOGd6H5LgE0AYUD9zOyofo5jgWpfnCKPPtFHKH7mf1c+Gd7ukVs63LChQZE2hgMalbdWojYPKDzwI4UVqWvnNPHQdwHAcy6PG6o5sjWA8yGRXKgw84CzmhpvyYJMoytQHlBG+4CuqDRY9ziOQahfJPzG6wwWj8K/Q4gqe3RmEzWN4UDmLhJ9LzMxfdiiMp6QgVQiyOqb2VDOjTo3pZtPXB0hYTNFYUHrquIusWWXhoI8QzRrLoFmoxtF9tBKFdHWWehQFAOg95VnKC0ULpOXJHJZAKAdB7zvFvn5dJaYsZar3YC/MCoF48jCjgWNt0tGhZkgn9tGkvf/Yw6xnK050i9ljGdMQMdqrKOvfyh6i5TqvVoGL+ooTleW9eJ5RDmMpKtXUsjcLRY4MulVUSUbRu+Jc27RsxL69P2YxR9PKB9TWDckHSs7JJcQCVEEBsYDrGE8MDpQt9Lj44YGapjUN4+TjAcGfAQHX3sIsxqfvcUAYC7GfkEq4PmUDYNQW4U6Tvp+wfEakv+/ghkgX0g6y6B2feBSN7HiWzayCpwPu8Vmy5LTVBa/S8TMM1KQZeXMIkxg2augBb1how4TWFgdUItnaG6GjnVzw+0Yafossq6WIgugDDvhYKJCBl+aFEgxbCJf5hYllUlllWxGnKWsU3Q71UzS5p/ZmOo1rkevScx02E4viIKasWarByhQc7B63T5zV8+74CpM94AtGgP35saAzTq8tHWmXQC8+srAXWpWx11gxMju2HNPDfvKkfhRI59NOD0fxDe+vtHM/R2igJd/8AMB9D8piXlf5gnC/XSPVX3/xL1Fb97TNC9jK+i7I7vYC1Gg9dYjeBmgbCKxgiK3swNjkoPdmOK7WxT6wGv7vhiBpHLwCNHX7pEkwFW7t+3zi0RMZwWOkuDUW/ZM92ByYcsL0H2GD+FnYezDbPric4saQr+eP+jHNjHdib2S7QdILRga28QoYiRlyOqq4xA6kW+s/b8y5RJrTfMcYdYqlq0VmVYZmZeDLfQgyu6XIAAtyyhWlbsnNe4y2tKkBaW8Po+kd0UElmgo+0VmiVmLVcFwHKh5YiEMCx1bRHUGwG9EElCVE4TLiYICWrC6LzXGH0lEEBMqOktSVWuquZ9JgDVoQUKCxYAVBPwkThgBgsLc9psVvQRd3XpeL0jvSKpzcGd4XaaYqUihhHNaQth10r3z0PDB9pnQXwZ3DvGtoAdCFq7uGHKjokwjWlnUW38rLT0WRpxfy+spu6EDo6xa7yFuRnHbL6wRVLhs6TKcRRRaaSioQozo894GRVWxvKUvpGnSKoNM38vqxcPoVp2mkWEcPeJNsQhi00llY2POaPSEgpdlg52831itjDq5zrFwItXeKLeqghmZ+ailiQVrxenEavz/OV1n8vCGPNMY/0fiIbydvxP4v4h/m/iP8Aj/iU/H+J/P8AxP4v4j/i/ifxcP8Ai4/i4/i4/g/ifw/xP4f4n8P8T+H+If4f4n8/8T+P+JbZHmvxFvj/ABH/AC/xHfz1CWc4lT//2Q==",
    "gale1": "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",
    "gale2": "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",
    "gale3": "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",
    "gale4": "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",
    "gale5": "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",
    "gale6": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgwKCA0MCwwPDg0QFCIWFBISFCkdHxgiMSszMjArLy42PE1CNjlJOi4vQ1xESVBSV1dXNEFfZl5UZU1VV1P/2wBDAQ4PDxQSFCcWFidTNy83U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1P/wgARCAC0ANgDASIAAhEBAxEB/8QAGgAAAgMBAQAAAAAAAAAAAAAAAwQAAgUBBv/EABkBAAMBAQEAAAAAAAAAAAAAAAABAgMEBf/aAAwDAQACEAMQAAABQXC2ApR0FY1lA3M/qT/c/oPxGyTsSaU2ifHTvEuNvRCA/DZQn4hG35nwehM+A26iac2upBUs58tWtYSykXTDSO4J3PHJ9L5z0w/L8MzVIg2ch1TSznGtJOyijVtjTTp2xZKodnIDQjKqSwXUrV7YOXnZkljtY8+Rv4WjehsyvGa7fm9RLKho6XqcdXwRaVVZbXmcrvo/PxktOzbpbVaAlS0IpqTR0oy8/b02XEZ7LriXmj796fmqejM35hnepKxR7hYz8yT0SbeUp6rLdYmk5xtTJLTTWk7NNWQMLpX3MT0eWGhkO+TMvYZiqSXorr1mOP5x1Kez5zbHkr7GTp0bEoTPlyh6WNp1+tz2O58iTiLT086G1Neykk01cA0OM6eg876LLl4t1NZ+iw3slGv0CcZamcYZQtFG7aa+kHbq0BjrjyrgaDt17VFwYcWl1UpPn7Vc6PSz5aaauc5XPKm3jaufPSxM9S5m8ZvVtPlEjznQC1YiQUtAY+WGJjK/CN2VKk62Cp6GXPjUOnt1Dkmm2vVSikwNG0xlUL106v1Sc2NhDVvXF0gelF5TjqMrRW2POMLvZGy6xc/QxxbWSceeYCFM6VZfVuwxaMIYTgZ+j3HSYodNJpVviRd/y7De6XzXUttRZlToefbWbPree0XTPm9QIx1fzIz7qJK3oYl9BrAklaM96ilpZ84k0vagS3eOuTvQlxEUksKTNx9G3a1I2WB6Fx2qNlQgmnC59VPZeVodVlYd694levOiLSQLdpUO3FBk6LoFqOATooBODjC1rAIPnUFFagScjbSsjJ2REkgd7Il2SJVkjc5IySQJJBzsguSQckgckgSSN//EACoQAAEEAQMEAgICAwEAAAAAAAEAAgMEERITFBAhIjQFICMxJDMyQEFD/9oACAEBAAEFArFuds/NsLm2FzbC5thc2wubYXNsLm2FzbC5lhcywuZYXMsLmWFzLC5thc2wubYXNsLm2FzbC5thc2wubYXNsLm2FZ9mKs10DoQIuJG1Ck0OlAbJ9cdGwPcwj7Sw7dP7WfZrP22Ryl8bZ59Btdicn6RRukdJXMXSGUiF5y4NynsLD0psGWPBJY2G/rC1ROeJItmPTGVZ9mORgY2Ri1gxrsvFeK8elebaNoSaGtLnNe1jpozHJSDt61NrZ0rzbRhYE+XcncWFZjWpvWz7IeQNxy1uRcT1CATm9N7RENqJavJ+3Oo5miL6anaOrWOeZGGMqz7P3iGpOZ4FHvSDSUWO6HwpNaiFjpg46QxRLOFOdUqs+z9MLCwv0dzUHftkjmM35VuyoTSBSPMw0YGEQmRJ6c1BuSzEYEupH9qz7WOgCipveGVIwuLErEO0a1ZskfEiXFhXHixxYc8eBCvApmRMjhZG+PZiKFaFHQZjViKsMETq9dr2WKpZH+jjpZ9kHHSjECXHK5rdzUrrvCmf408pjirWXTLUq0hM2pSW5GyyWpJG1T/Gsyuji50ihkL7epXu8NE/hs+sUT0s+ygqnaB7vEdpHWnlSPe8V/GCyC+KpCYmSv0Mp/3ZWzETbYxjoe0LmtkaasOK/sZR7iqNAm71+tn2UFD2gmOIqLGaNYCvvJLT4l4C1KzHqbVbpWpcp4Mj9wtOGTyljOWVW/v1Jr12y/vEmtJ6Te3IO6HZlh34qkjs6lb7vyp3dnFZTDlmUIIlPFG1mcBw3WcQJjdFnKDsT5QOekH6d/lP7Z7u/wCkp7Q8MayJuUTrs6SrH9YILNTVC9ojEkSL4lK4FmtiGk9B7SmOmUqP/NrfIHHSx7LD5FMc2QENAlmAQkfIRUkBdA9cdy4xQqLhhcNqNMLho1FxiuO5Co7MgmiUji8xTM0NdHqefy9LbW7sFfebJE6M4KOVhQHbic/KGXOHx0uJGuifwpBFXY6eSXMUkVSSWOzC6uK7N+Yw1GSXYdiQPUcmuNywskdONJoZCHG0c2Y5JIi62ZlJDojKws/hXx/uTiU/ITiSW5rzY+OGm5dP8yNhm+Mswugf8Z7U0UDrXyETonqE9+jIzI7EdR9m66cNlkarPs1Id9wwVFbxD2zlf+Kou023Ml5/Z/yjZ4eXENPydqrI6ZrS/wCMnhkiXxrsW568j7/y5HSH9rvmGy2ux5L3beYFZP8AJicYqs8Me2gwGJReQdC8HbetVjDWytQZJqDZtWzYI2p2B7ZXIRPBbLbT687zxpUYthiij1Anyga1ykaZ4lZ9lko287ddMk0g/tZP17rUUSeuorcctxyLiegkAYmOJjdJthWvYWThYX/dDs4OC1wWHdMOXmvNEPRyhkrDl3WHBaXIghaegOOgVr2VgdAems51FanFbjgsrWVqKLiUXkouJAcQdZWsrWca3IuLlnt+1paj0teys/6oWrra9n/a/8QAJhEAAgICAQMEAgMAAAAAAAAAAAECEQMSIRAiMRMgMlEEQTBAcf/aAAgBAwEBPwH22bF9U79k20uDafSyyV2MukRdmS3Hgx/Pj2MpdGyWSnRLlFDXJtyJionkUFbMWZ5JdWxzNmONjfBx9D45QkyTkvAriSuf+EIqPjozI6MSWRuzHintbN++jL86iZnrKkY545cG/fyJwcW4kco5d4ujfNH5PxMaksTaMMpSnyKG8jGnF2jItpWyLxp8CitrZ2JPUWO7Kdk3SETX7MyumRjNrVEIaeSMEndmsfslo3ZHROzWH2KKX7IQ5JRaEr6OI7RYlbs1NUaI0Qomou1jkJDTJS1ItS8Cpikk6Y5L7Nl9nqHqKzdG6FyxU2bpdHFS8kY0JL9FdKNBRKNEURSPT5L9l/wUL+h//8QAIhEAAgIDAQACAgMAAAAAAAAAAAECERASITEDICJBQFFh/9oACAECAQE/AfrZZf3dlvFlkrvH6Ex+C9+tLLnTGUfssvEpKJD5NnlsbG2ONncP/BJkrR2I7kRSWGMj0UWX0l7wlx0RcWbdONcFIvosN9PkI3rZBtyErZG10l1icb4Jd6fjToSxJ0sSJiUnwjHX0UUu2Uh6sWqNY/2JJEY9Gmj3DQ+FiVlGpqaoSKPGbCRQ3R7i6ZsjZG5ujZGyPWIvDViVFZo1KKNUUI1+t/yf/8QANBAAAQMBBQgBAgQHAQAAAAAAAQACERADEiExQSIyM1FhcXKRIEKBEzBioQQjQFKCkuGx/9oACAEBAAY/ArQC0MBy4pXFK4pXFK4pXFK4pXFK4pXFK4pXFK4pXFK4pXFK4pXFK4pXFK4pXFK4pXFK4pXFKtfIoWji/E/QJu91ZOnfJVpec/Zfd2QrUOLzcI3AiG3o/Vn+ReDTHzbe3y752vkUHCxkjIh0ShfsL8EluMJzmiC59+Z/ZWtwFv4hneyUn4w0SVtUa8cNmBFMFtCKutHfSvx7Y54NHJM0ZIOK4ln+NdMO+6G2zZeHO64Jm036deqtv5jJcZEPFLTyKbJynRMcSQWac08akzXVa1d1EJhOLYzQA1Tf4f6YgotOilomB6TATecNamd0r8V+DRi0K+d1Pj7YJmYjMq065YVtfI0/4v8Aix+dkc2ubiEbVjvEcipTbRz4w2k+4LrWtn43Zw+GyJUHOlr5H8iKt6OIWAWRof1uj8iZvKAjS18j+WQMuy3yt5yz9psgCOXwvOyrAoYra+RU1k7I6rF0rVdFecTms3LX2tUDMhbi3FIag4hbv7rI+1c0mFqroyRMxii6+CPha+RqXu0pdA+9G90O6LhmjMYUjSjhOR5K6TgmK83mtPSa486Xhm1HunfC18jX7oqeqyhbUpnZQ0SnF2ZRJRNCS0yeqFzBN7KHZL6k3vSCnt5FP7fC18jVici5zATOqwAH2TU3ssTS8CZGiJ6UIKkpvZS1aJveh6FE807t8LTyq0dEVc+kUbQHkazTF7vS2CUOyuzC4jUBQj+4UihRT/JCsHBQ3PUmje9Pumy4ZLeUOnNZn0sC70sFnpyW+FvD2m0YeiwyKCMo0tPI1mQD1WNoz2tjHqVA10CmWt/yW+z/AGW+z2uIz2uIz2uIz2uI1cRq4jPa4jPa32e1vs9rB7P9ltT/AOrFBrpw5IXXj74J/er3Bv1Yolhx5KHiKZ0c4Z5UAbiSsXtB5IsfmFfvDKYV1pjBFhOSDw8AFNvOBnkgyYQsjvnqhB2TR7Hcp+N8iG8yjicFaeRUsKaLQRCDtDU+VGKbITcAwlMbatDXGMk6y/SnN5Aq07prGmCQg15nCV/ihftCLQ5AFN23OacpofE1gBAvxcCoAutWBVr5FOb+nNYo2VqLw0WFD5UZKFo3c1xU/wBjEQAfxcpVp1Eq0tBF3PNNYzOEDaa9V3Cs7QDYESVZDXGh7GmCMNl+hV+0Mkp1roDApa+RWxv2phfyztMG1SZx5ULPS3St0qLz/awvBTjPNTLp7red7UXnAd1tEnuVIBUSfSvODiVuFEvwJEAUJmKF9ruN/dG9sBo2LMUtfIq48SNEZ3n0j87NZrGkUNmBmZToN57szS08jSPhEUyKyNNea1WqMzhTCVrzpqsjgsa4VtfI/KaZoY5U+0LNYlHqoKkFfaKZ0xrrW18j/V2vkf6v/8QAKRABAAIBAwQCAgIDAQEAAAAAAQARITFBURBhcfCBkaGxINHB4fEwQP/aAAgBAQABPyEe9AGJ7pPdJ7pPdJ6pPVJ6pPVJ6pPdJ7pPdJ7pPdJ7pPVJ6pPVJ6pPVJ6pPVJ6pPdJ7pPVJ7rmPg2HCQI21HGlNREklXK6ShWwyrfaYZjhX8QdFRY0d6lDK/iGm3A4K0/n7rmX23n7UN40VXRvNuN5qDgJD4RqaduQRkVdV61CG3JCsKZgZZQAUtYDIVbGdC2VxFwkelUrNMKC8/SZMPBBNO02jRhRel1cuNN40MF1zkZSUQFSMOvG2N49ATSMW7pHVnvuYK5sxrzw7SyVFUIsDA/26HK4ehPSoCvWVU0o1pNSVAcI/tD6tVEw9c3ysI7KqZB2MwWdldKrtElQhG9WHstcdoQjgmO0c0Lp/ZMRBFpGYsYFvR1e65lEErwTuH0nePpKn/DpUEyynNRwxSlEjb1iPImKXWDv2+ZUGrQ7qcTKG3k7QzEiRIsGqt1/CsL4QS5heNunuuf4hKgQNbMzjeCZf2Lmpj4ILX6oDeSdqQ+BmXdBlJrKalSsxZqTZx+JQUAcEvfQX7WeoQIQSSXcaxXcgivqzebRMoM4MRb+6MZv4XB0K1VqaOPPoEnwDmK8GDiY7NY1RmY813YPaTNMqei5jYpAjMCVJvGq3gS8wmLjRWjEwmjEr/sIHreHTYcQqVp0j/1wDj84xqNmblhBV3jrlFiAhXZTdj8xfZYvO8LF2GkNoG1TNxMo9p6rmMoA6Q8LNI8yxliFyl10H1o+UTDfEczAfgloZbgrGA2awQpErtKPBLEl8iHPDXQY1QP/ACCPA7+OA3l3Y6eq5h0L5VKn7RU0urVHmh4Zm3LayFE90asS6ELGqaIHxrvFfZPQvsyMHwbFttzFxWN8GXbjjkm0gij6DiIhxzEwtxOnquZVMUPkFz41ENtgx+jkGC3KC4B+JV7mkqmGW3LBuZFBCoNGtIpbGJiXCF6tablpn8Iq6BcldiFAa0uKjy5cRaLoY8QiDz/cANcdH2wwJqAwC+YxhucRo1GD8koqtEuLRO0+tkHZFq2FvR/cCKm9yYTs/UvEcxtJRu/cziNOp0+Zw8wnM5CSpU8pPyJ+T/cM1aXmZmWOe4jmxUTFENKEttpmFbLpvKzSURif+jGTW4E3EVb0PuVZN3uRetOB9I9P5cROF8CDH2JmIDqW/MBh0Fkv8soLZNJaxHWP3t5kSqr3ncqBVL8b7fqYf4iBT8GCkzhFkU5bzJpNMuKobtYRICr/ADz/AGuUgp0gR0lH1+eclZhcFR0bowY7StJ8xSLK7OmSVVaWi69AAdWpiCoGrstpUyYmCrdHOaF4irLK5KKCMv5ImGiCjpd9cplWVsF2l1ZBMzdNxYyuGuA1XtAFdm1M8kbL2iG818Fx5IM9BgWzMHVGgeJ0taiZbC8E7cytSqnhmAWu7iFx0YeJ+osV/P8AqZfqrUJX4FSvFyu0ha+YiWpvzKYxkC0vmDhboMd/NG0gComNCuW0lyr1MSrgBCV9ZcTUAlE9l95YmFyk2nsy48VY4MGH7zEZFO40tojeGfRpGEtUZPxHKVU71bVGgW9Tz6xNzM/GXvb8qplSmGpxNZreY+Og1Qgt1QhJnUGlRQLudB620XELDdFO0xsS2XPzBPYF3J4noW87RA8SwahA57x5jIrDZLlVEFbt+pUPwT/kTguFFuOqOsPTTXlmLpxavVDL0MogA0CaQq9MkAAJokWUTyIvWt2F1fjieUIYssfiMTMpsNJlRvBquJilc7Duwj9reAe4EbMLNX0SFTUrotq3LZmAwuDHdYvdjcyQHeV7oWw7aV7y4aI3Bl7xyOIAlwujR+8+elgtg06OJzx0bluYzTTEKQYYtzTvLeWYb4fSVlxL12hg5xL12hvkMynWzaB6sZiutH0icWNyzDWOe9wx2hT3hoVw6TRqJa1XjoQzqxe1vDWeSOHEwW6ww3OMw3pFPqtJmLZW8wwna7RSuddYYcmNjaAiGCU+Ju5iplj3Yl+LLuPkW4uaeTGxtFCmtK0mUaHWXXkz2jBwKhWvEt1ZiG8aqNINT1XMMTxi3t0uDMR/91TaXEcfmOXp6rn/AOv/2gAMAwEAAgADAAAAEDDDG6Hi6EI8ISAFE9HLYfoSGUMPPITORzK7dORHMvszvbc2oQYtm302AcY4OEpjiBV0t3zAEhW/1/YJ+khVvoglK05c9zcKAoPktIIyidjdoGshPJ8hVBUk7Zzt3p8xol8mqU715KjTTK+sVYXuig3cXiv/AGNz6KN33yGAL/z/xAAkEQEAAgIBBAICAwAAAAAAAAABABEhMUEQIFFhcYGh8DDB8f/aAAgBAwEBPxDsuMINwtB6GbOy/G2WLR+Hz8+M3FqPrC8bISuM1HJJWuXpvE2Fg349H1z2Adk9ZMBR0KdQUMDyxAFymEtiGukBABQdFplEq1HZCqpEwM/cFGR+/ExIh+/E3VIQHKISiPA4h1dGEygm2KHCUCYje7V/3NvR6YBuVPFc4UCINsyw1DW4dOVAOWbAb/FQjfE3nMByVIFa5jjpuFX4ysPUCL8S3SLES6RBROADBuvNYhpHEcrFklmEMuzN15EYu1UWqsRE36hEr3Kt7hQhsoCtQbcUNSg1ADUS8QiBLdnQt4YdL5YLalhriI8E4gj4k9EYbCR40nkZls0HEVUvQioz12v+QyvKMVFMU8RCN9z0QIQF1EqXW/uNIwvmVWpaC9MzMOpTJLcyjsf4/wD/xAAhEQEBAQACAgICAwAAAAAAAAABABEhMRBBIFFhgTBx8P/aAAgBAgEBPxD4bMcxN8DvwYOPCsw1acJ/u3OFsW1ZN4HXwQe78FoS3GtyIHuTBzZ3IgnqE1kzzjwuNhL6gdlwVJ4YRidEUNx/v1dtbEB7jDqfB6nVI8HkBuzHnqzxl1iMkoHux3hY+A8hD7i6EsLkiMDfspLi0iwRjmDn0jgXUY0S0EjqLuxUGIz1ch7Tgo9+zTbZo2nM9pMaZTqBTsWpF5xgtCsGxJTqQOoQ6kxiTrvwK9XtQnMgFYCDPoSfuseo05b6nxHIwFsnfgO1zt9wN0sslM7jNz7vxQCB6sL+LfBvuzLUL45ufgGRvuz4P8f/xAAoEAEAAgECBAcBAQEBAAAAAAABABEhMUFRYXHRgZGhscHw8RDhIDD/2gAIAQEAAT8QEsyjAHBpPw+yfh9k/H7J+N2T8vsn5fZPy+yfl9k/D7If5fZPy+yfh9k/D7I/5fZPy+yfh9k/D7J+X2T8vsn5fZPy+yfl9k/L7J+P2T8bsl3b7Jvvopf5brPEF3nXG0T5AkABCecpXdCbVaecCDgBObLWlbyik9BXNZE2z/wSyCheat7zgRGGMJE/gKgCroEXicUiZeQF5ypj+1DWbj6KIpGj4XTbHKCTxbVoOBfCHIg1MVVrZMb8IBsW0Wl2XQo3EhtaLV5sCV/Am2lAlcLWq40cbyj4oFvu3456wxwRDhD7EaAmHX3aGCJMXBs65pb8AxGkL7EmHG7rcOd4rF2RvYqLUpqLnIlNBV2uZX7kganjqwDjzi7GAFEIxtZWmqxUNREjrJAbWVGt1LbaT7zilXgqFlZ3IQIMLhRUpvF3mOACoGK1e8C3WGud+QPzOZ5HeB+TvBBV0xg7zNUViyUusg2eUw2jZvLnLjmUQkDisWuZ8SnzmQQ7cecyVkNcWKHrwgNXLTjg9F/wYb8DQWiaNb8JmLShYL17cZgtkMvHjEwOem4MOVsWEiyVXK1ybC9ofpkWIBmwNtvKVCfYcUGGDS29yH1z2n3j4gdg1pQPYgQixpjbIlNBlgIaeWLLleOIwfm1OceIG8Wqa15ZuMe+5MQU3U9oQmEG9FWd22WWZSf0HenDmlSpVyyS3pg6u0dhQQry2lT7ji/gQIH8R/xcEA6XvDtOizrK3Mo9r4S0PeevOM0t9XBkQ6kVM9GC3xFsuhM2kQz/ADuRY71iMFgLVusvx67APd6wFH9AoPCdQ6P5iGvyJUD+i7tE4TkSqag2JBN4GssSbxMCPaGqxwnNnoCI2szn2XUES9qLBq1anHEKQyus3xHdCVFr6HSWdE0GAgLLDWiD7CgTQrPH/wAgVlLcO5xiXm7VmUSUfRT1g/gqAXAAyxhvoasELvekPVhSIcWmFTI4bxl4IlawHeWPhPiMWG5jtLhqBlUyhQEdNjNFTzy3BfXDCGBY1bEIZpc0ansBUyVHW3xFMR0hzV1EMK5B+IISqHY5xn5269h1vnFKCDYLbDYLCzgcWMutEz+xlLAeI6MTsU8IRCnQwrS+msdGycaX6t6uoscYlodC9pWm/qVfErYDRkaxogQI46xIcxorSr4X3mSX9kADSUlAUqOOkcbrZ9WGAiByYYA1Xme8opAqGlwRAYrS3q1+IYHe3oQzK4t6wra8CPQCjQIsP0N0EOSa/vvICOZs30l7Im+Km6lict4fKAi9u0B8prFPqNwArIDTfkigbtdYkQUUOLgS6SqbzSFoxGLNN+UEdUmqvpHysRA60dJsejHaITjtSpsAfP8ACkwmodxmucHUViPkjfKXJZpEqH6G6WqSkmjconF86w13ThEKNAXQBtpAldOj4iqAC0ukMXB6MlDIXQq7YGNgwl+VtIm9cGM8BQHi/wCQrq4JFswOzK87FGq3gh0fFMsYNC8MFAuykt3hurZNUyUW5cNT3j1/6Oglys/wsoxlYaA3pqBFWEaZmAE3zRgFXBicor6Eoa7f58xhLNAyr4+M5kSJmBoNsRiMnFvgB45gsdV7QxGqN5MuGwxnxFOM3FTaxDCnxlg8hT5INiAEJjpNYdZX4jtLBtsbuXw3HWcD0F/Fx8ZlX8EYJo5XF9M1jFDj95gwfuiENjPnNqpaesrA0MEcjHYunpMRO4AtaAGhEdGX0sk505ZomHNuJTI1gA48I/llBvCntURwHCY4HSHyZTJiq4xBQfB3g8g8xChZHFHHnHLuiBWoB9poH6n3EH6S8ZmWruXxmOonWYegDwU4BDpuYUHEkMveR8RyWFmh32jtPOVZNPcS1HOJUDTlAIc0yj47SnJ4BXlaZXVeaAnAPljQVVGS8t2CieQCDHqIMW0C1oxxQ+GLDDB9nhNWt6+0t4832iV/d5RRa/L8RuSjXgGZPOUFQsLSD0S2Sgy6lA3vbrKGpCBDQ5pOTcstqLcGefeEhFAE6so6yMuQaW2NuuvH3ljry1eLEfuk5MlTD0d5cwvOU+REM7csp8D3AEVrrQROorCNCC1VgRBLyXrUOHfA2JsjuR+VWBoVddYoBVm1RXDrMg3FlOL+ZSegyjNS9BQZ4qtb6y+8CLKDWucVUAqlb0tMF1BGxheUOS99SI4XnCxrsdgsfjxhKoog1KIFoubcFOsZya3DfQ1YdYoBC+Grz8oNtQQXzl7Y0uo6iKoCUaqmUdNPyNVFYs+CysnHvFGXEwV6+4mWENL1+uBC6aoROMIX2HM2desGanxqQ+lTDaj8ASgcPgS8EoECr7dJQtsWQLTfpL0qv85aHbbKumw1YzuRDSVZflDOPl6wXuzEYUl5R0V7zFNqIWjgOl/eEowIBaquLBVLsARZe4fomr0h9tKvk5PybYAaNRliOBCw4N7RUJG4vKcpcxLdA90GYHxGx4qD1l4mOlKBy3ZlZABptkBAPVlBpppry4SvsLP043LfKBdWg4eEbILy7F9ekBSDVL8fsJyGzbuGvSIZB0TIrjWDgoqcDBAzMlJSwxKMLbQcY9gtlLc61r/OMYIK3Bw/JZjeYoath0xFTmmCr9EqmHKVk9C/OIGDPoa9U1m4iBitYVZz6TLSV3vZUKCZeMVJE4Wlbg4BFQlVaM/q5j1NyldzBS3G7mVA5G4XekUCQpHWecHmlUAHIuV4avQOmYsMrRSPKFNvCp86muVY7Yg+pwZxJDleqmwEzMKsN3ZdfTHnASRdJKvnAH2zwCEy+o4DTTqlgbXEBcoJP0RegCpnUOmd4qJr1bW/8vxYYKl9tG4WRnAW1Blb4h1lv5AW3pOA9IBoekPpflAyp6gnWX6+0HS9po1PCAqKoKwr6R4tbqModAb2LZqNZZUzQNo058yBdS06feE0xKKtJV4kbNYsiXUO16wL6xyttEIqAVWghxX1Vcr9okkgUeIasyNAKTd09otJa6xcs6eT5Q/1GBilda3xdJWUwF5YWjrMoUg8jLR1iIzULWpdtdYButbZvU1I/MRaGtTglre7pBCohqt407nnG6ag8l6ecuG8Mmx99pbewNaqY7hgGm+IiyKSLpELJwhwICOtg2JiPpaaY6LknTeMVwa56sdtWeO7LCNRsZSQhoAaGq08YOCmFalo7XFFcFgKJpXCVJiy4mSVZ5xdVnYMC66QViyg0h1AMg1BQR5blLIaDYecSYq7wa8ThpANVQKNW7fWA0FbUp9ICrJTUeCNkQ34ZMZ64M8oCOlNKM1p7RQ6K0gQNdOGr5sYEKAoCgnHToigMl6zQEfCVGFcEpVvPqOKK1mvOA3L0ahKynjcGEg6ylpLbaR/ly5cuXLl/wDFy4J4DnURpXrDyYvlAn1HF/yQYMHE1j/4Gsf/AA//2Q==",
    "loss": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgwKCA0MCwwPDg0QFCIWFBISFCkdHxgiMSszMjArLy42PE1CNjlJOi4vQ1xESVBSV1dXNEFfZl5UZU1VV1P/2wBDAQ4PDxQSFCcWFidTNy83U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1P/wgARCAC0ANgDASIAAhEBAxEB/8QAGgAAAgMBAQAAAAAAAAAAAAAAAAQBAgMFBv/EABkBAAMBAQEAAAAAAAAAAAAAAAABAgMEBf/aAAwDAQACEAMQAAABpym1gqDILDfODc54joTz5KfEbqnCm6vIuk0yJVeb4hAugZKFPiEOOgc8DoHPA7abnMV9E58K3ebWXlEyFRY0VMdPLnx0Xxe5zls0yWmGDONYZNq7CajOi0688a2nJ21+UqEkAdvj9riKrFALREhJcWlW12p1VYVh595Vd3H0dEao3hq0lu88JGWlab6EqRYvCImCQBrv8XsczPqwoxjWcTNhAQruwrM6jOECcTjMfQphotV7WpfNNq3VO1UM+u0dChXJGldvNgB5dvn9DkztvTamfZj6Dgd156ed6/Eav2eZ2E7zz6Tu/wAnoZOWtMear6qGmQNN4YA2ui0HPiKacXTSa2y9DjljfyetyOvx2mNlt8fQp0ktp1jlv8/Tkce57U9FJzkTiLKKvoX5Do81OllXPZrjMq2UOhBSFdKacVnEIVbGJWPY4/Y47kYXvOzZnGfZCzu9YJ7VqtK6VuIvlkU8leSdqRWdWs8BzTcyc2x0BZ00pfPQkrLvcXtcNWzjLita9VlW0qjz1uuOXhETYwiXO+qQtOguuE32XhjuvOmdGaR0la2V8GrFBx1ON2ePXOxRmsdYrXZ5rlorGCQUEgwJHBMCCZVRNhVSbalaUX2VaLPIjgAOvx+zxr5nqp3z7KaZTfNasyKpaHMTEpk2gqC1QJJVSRI41xgdd19CWkyCggrDs8bscYkmJKLUkL2zB3nMC5WE9TMDUykdjMFqZDVykJyRLUTUJAGu1xAAACQE5kCgBMAAAAAAAagAAAUAEgDAAP/EACoQAAIBBAAFBAICAwAAAAAAAAECAAMEERIQExQhMyAiMTIjQDRBJDBC/9oACAEBAAEFAru4qpS624nW3E624nW3E624nW3E624nW3E624nW3E624nWXE6y4nW3E624nW3E624nW3E624nW3E624nW3E624nW3E624nW3EvvBbW4qq9BRSFokFmvMroqP6QMwUGgtslrRxCpB9DJrQ9V94Ldgs6g1HFzU2N2d2YsfRQoNVNUU6KGvOZUyt04jVdyy9uFACL3lNVpXm4xtSNRalLlUtaay+8CMApZWm429KLs3PWnRUNXepb6LmUaO8q0uWVbswwZTfU01m4NZmQzanCy44XvgzibGbGZ9KdqbGUavLgfacldywArVthTOHrdxCJsdfVefx/SBmEd5qTTPzKIImZXBPAfO+wi9wU9xp+303f8eY9A4027P9qVMFS2JzDsGzKtPVRPjghwfiKwaVEweV7eN34CI0xwxMcQcE5MGyxyWMRihIeofiH5gUmMGiHVp8yquON74F+CO5HClTpCkwpBTBEt1ReYQOY0fWoBRJrBUpQ1WnMJlamMUaKimKrLDVYx1RxuwFNtWIyOUdpe+AfI7huBOJUb8cojNVmya7Yp25ykRv8AJJlxkPusdwUzlKmdLdpsI/3lLYLG7Ne+CKYwzAvvc+6p45b+bMrfS38cZta+2ZkFXomZMpVPaDg1KYaEMp4BysWqGlYYe98EziZ9tPyEyofZKHkzKv1oePMq/ZWKxXzMyooIiVZmEhoy6mHje+Dgp7UvtHPtlH7Soe1Px5iY3LJKn3/5zE5Yp4pmIfce0buIRxvfBxpmGDWcxBGfNQwEQvmART+SAiM2xiHKxdAxM/odoe/G+T8eBFoFlZGSUx2KTtNlj/IqTNOcxBGq5n9h4NZvSWPU2inWbiAKZogjsOApMQEyWTEvD+AtkpVZIbjmK1Ptk/oqMlqYoh6oIDssZt5e+CU13mMynV1jfP6FNxSjMakVdhB2a+/jxPx0np6qYo2H+zHaCKuYflF2n2WD7X3gEYe1T7YhxG+fXiYmJj0bYWA/jGRM8L7wzMLZWf0ATNWmjTUzBmCZo01aaNMGYzNTMGatMHHBW1JJPG98HpDYO7CbmbtksSAxE3M5jGbmB2gYg7mbmcxoWJBPqvvB+1feD9r/xAAoEQACAgECBQQCAwAAAAAAAAABAgARAxIhBBATIjEgQVFhFDIwM3H/2gAIAQMBAT8B9FQLOnDjhHJkK+fQgBO80pyqASq2jhhNLad4wmKg4uZf69/RRG81NPM07XEU+0DFWuKvUW2Ez5Cp01MbDQVMTHq7Z0XN/Urmg1JHSjAOSZNLXAQH1VtM3EMx7fEbL1E8bygBF1XYh4htX1Px8ZN/MyIUajywtUZdrmJbMz9u0wpqloH0VMuJfMfTjW6jhCtxUAW4mjItwkhv8hQZgC0YUYsxta0ZhUCzOLPeJwn63DvxAnEmksTHnTKKMy8P7pMHECtLzLgVt1hB94mZ0O0dtTXBMbaTFalj4y7XMfatQfvrhbxcyAEUJrMGjSDUQlVoxu4xh8cqUJ9zsI28zqUtETrn4nVa7E6zQsW8wZm94czGLkZdoM31LLbmFkveNpJ7RBOn2zd+2VzrlU0xUuKxbtmRaAmK62izrrdxWo2ITvysSxLE2moRchHiY2ozJk17CXXIQHlUqVNoeQNcr9I/j//EACMRAAIBBAICAgMAAAAAAAAAAAABEQIQEiEgMTBBUWEDQEL/2gAIAQIBAT8B4ySTdOeDJfFQSrPoXfORsiR6KVOxrcjcGS4PsTu1J6KaSIdmYaMmJzapCZUynZU4NxJSxbYpJ2OUz0TjdlR+Por7P4KOx0tFNXyVUe0U1fNnSmKzQ1sTge2eoIEQbHsQrezZBiQYkGJihpMxOjYvu0nW/BJ9iKrY+CCBiUfvf//EADIQAAECAwYFAwMEAwEAAAAAAAEAEQIQIQQSIDEzQQNRYXFyIjKBEzBAQpGhsWKCwdH/2gAIAQEABj8Cs5hjIMUDlapWqVqlapWqVqlapWqVqlapWqVqlapWqVqlapWqVqlapWqVqlapWqVqlapWqVZfBRk3vT+mDNcSMRH0xNUMvVFE30xHQJr0d25fFKpob/8AuGx1p3TXw/ZbHsqjCH9z47L4Ivw73URMQuJf4V6GLZ2ZRmCC76boY+1RRXfWYLpL/wApySe+GmW5Qu0P9r0hOq1TnLknGUzEdl9SPfIKB/a+61OH9e77vlAiKAXI3i60XCeKH9G64ovwOS4aMSsvgi/9LcVdRHmMTJoVzTgvzk8RaGVF0lXJX4qQ7IRRZKPblRcPMNn1UeTnKk7L4fZiPOku6cFPtyXRXRlhbbHZvD7Iab7SfbEy64rN4fZaRPLZVTyB57Y6Lrgsvh9qsqzeqadFVOqZKhTidl8MMN6ByRzRI4UMxFxKk7JoadlmV6x8r6bh16B8le4qte6vQ06K/GHJyCpTsql1kIYuYV16S6Gdl8MIHJRShHWVFFI+MuiFdkaqHsi2aicrNGVcpFWXwwAIoyhnF3k8mNQnhqJNJxQpjgrSVl8MAxnvivDOVZNFlisvhg+MHxP5l6g7BacKoG7IdZB4Lx7r2fymx2XwwRS9QdU4UCyAptKodchyl3lUPJ53mPbHZwNoVmU8JTRBkVUj91mt04XqCyi/dex+5X/JVX/hXtJ+Vk0/c3dakKYSfIdVnKzn/CVEISr0OX4TBC9mmAnZfCR5iTFU/BfdXokegnZfCT7xJx8/idFdgpDz5zs3hIVqFFEd/wAJpEbq9FTpOzeEwJ0WRWSynksllJllIdU+2Cs7N4YnCznUo9ZZyNUCNpjnzTY7L4fl2Xw/L//EACcQAQACAQMEAgMAAwEAAAAAAAEAESExQVEQYXHwIIGRobEwwdFA/9oACAEBAAE/IbeYDlxPdJ7pPdJ7pPdJ7pPdJ6pPVJ6pPVJ7pPdJ6pPVJ6pPVJ6pPdJ7pPdJ7pPdJ7pPdJ7pPR8Rs3hgtXEVajyOZcuiRmc7ReYVQ59KlTwVnK+NRVQWx+zzQyFzumn/AGpWkHhifDnl83q+Jdn01+RJrXZecjTMRlgY2hGNRTm+LIjlX8CbDDU2gc+V3hnCPmVUYSPYgjJQvdtB3e7tHqtRRTZxSw4Ut7CabUqxrsvS6uV23DaF1zkZQK5bIaRzjaaUXQmM7sdZ6viECzY5tAEUMG8U7IOmJjlmO/4mIgDeHCe3PeZ5aYWiuyWupX845j3GTnZgmArROZpGrJKl0akHgMhlULLpVzEjJH+ky0NzqFY7F06vd8QeieL8TxfiLTP8+PfOH/cuQ+4tuNUMaKLZ63xanAgkOMp5gvENZjsigbh8zb+tIx+CKiUUgQ2st/1AjHU6PZ0tuegGjhtCaMsgm0SV/tEKiV2MiVNPhoveke5mOHwVPX6JuGn3iZRYGbhfi4hGyBgRgbXtAoxnj2KC1oljWKmQ0MVd/D4ex4hUIwu2kaMr4lWyzhLNlktUVLiA9mXgKasYr8OmiLmAXxKKKsEZZIVbJWstbD19XxEOUpwZZfMDMX8uKqYsE3tizZBbCo1xtPMMAHgVA/8AtMEK8CklOZFRELk2sv8AyL1/JHAx9lwtPugv9SflhFOvAqak+WYq7Rg/JFHeaTL6m8DkhYjY3iT3fEeEDdDVdK3AD9T8VLzCe0RL9d42ZWYyFWklypt7fyWMpHNjERMOj+QoIPq8uz8NpZTSLLnaT92EFDxdDQ4Z7viESpoJ5gktTvHAi+hjDuXXifzrQGQxo/sMJl7G50LA3JpMpEWn9ErbTFuMbwzEZP1Mhzmez4hAIlmzPwczLMiE0fD/ACMLOKoGcr9opiCO8uOIzCt/eZHE2J7YBVf8RaH6fgVdZ7PjropSzwouekCYPyiz9mFG7MMNtHassaP1GUSwjfcUuGcw5S8qirBPtFOK6ih/TNpTrF46ez46jRMS7VFmaf7dQ0g+rnJimFdGiM8MYgAGg2iMyPpGWSuvMe7Hg2hgtoS5OGXTM8RM5YuXM3ygloqumbMU2/UTasd8VKEns4jFhd4zVzKMjizt+iHJ+EZBZufqDlv0CGnu9dI+0DhpLct5sm4nqNdif7mM2QGwbRViWan4m0/Aypa3YuMrRhLErmUwx9qi6EZlW/8AxMwE2BUpRi8jkmblGpxGVv8AkroTMcwtYqIUXfEtCe7Ptoi/1Pd8dKVdC5TtldKztKqRQ7cf5dI6dKuXFL5RC3wQk6F0u2KHoeOjs8KUiXR0MpcTPzr4loCp4Sgt1Muwib6GrDIHeRod5mJo/ekFsocGqRbPw6ZVxDc3lPErtKeJTK7Su0p4ZbhluJbiWlYlMWtpXCzCEX8ojtoGBGyvMGp63idyKY9DVdStBWpYX2JYpbEF0UQLRC6hYoWss1csVf3KlFa1O61qb9OMwSAKsFcKdtgqKdhGghtvHVITIVeI7auBfiMfr7S+lPQYkgJjhtxNWmr4xNQNPaV6wu/uag0U3FW7424iJHU2wEMmFdOZQ2HWIxnRNHOBWvMzjZfiAWEBwzLA08Tcmsp6Xjp6Pj4P/iPj6vj/ANf/2gAMAwEAAgADAAAAEEOMB5Uy+dRiNPPAOUpLYWKDb8UHDDSzUMl3pMvAmBwXnMhst94JUWlJDp0m4JwWZLpOervsBqxxNAeN9iXp84KDh/QhC11lPlfeEIa4Q/itxOwlQGxeYs9nBWm5l38pbhuhe5vblQSoAS9iZQJl0f8AFckPFzx4CL7/APB8hDAB/8QAJxEBAQEAAgIBAgcAAwAAAAAAAQARITFBUWEQcSCBkaHB0fAwsfH/2gAIAQMBAT8Q+uRq1t5sh4sZJkPTfwZV8WfnfzPn44/mDWKu5BwOV/3Mqa/pb8m/9w5paDr/ALLCE8rp7fb9nx+AAC+RtVrD+CU4OZwIiwWF4Lz6XiJq7uez/wATh5k+jfYuKJXq5DGyolWtQYWC4F1DS83F7yxdMiin4EqrLXHsHFrBAYPMXeSO5jYDtyA1qx7BzbSjfNwoy772hqxLQJRJzTAROXqQNe7P2X92Z2CWA8fVlr/lY3F83OOP7MdTg3ImnqJCZt1l0LNfbc6mS3LuL/E82fFzg8LIgBhM+O5pAZUnniLq+otfCSAHyg5DPSSXUvQP3/uAfBs9xxLaoRnKCwcI3HUHbBtYelPOWzsn++I2sOeNf4tz7Z1OLLImRBB8M7AkMnFwDr37+1ytAb5vZlETMOD29b+RJ5gt0tpEFa+LRfHaL9sHN08frcLbD32/L/UvhDhlh7sGTebFiBAOclvdxKEIzthEv1P+Az9f/8QAHxEBAQEAAgIDAQEAAAAAAAAAAQARECExQSBRYXEw/9oACAECAQE/EPhs8IYeA8PgkOuTZbV79SXi7Oobasvq+Gj1YceWQe5AyW8GMdpsC8qwz9t5WTQl4xZIuB7hDvzHvdWq2Mxgf1ZmfUQ040LsywL3cTF2S+LWWyDkpxdFAP8AUJIQ6THHSS4QnqjpR3DO6XpiQp1BPUB3HDJti0gjLzJg8smjrYnCmwFpdCX3baxw9+La6Nn7spjZ9wDxJ9QHd2k/qw6EGOrWdpvOwred422cSBHq2N7m3mSaYwdcY2Njd2pL5jpec2bZMnG223cdcJvGfF/z/8QAKBABAAIBAwIGAwEBAQAAAAAAAQARITFBUWHREHGBkaHxscHwIOEw/9oACAEBAAE/EKasFXWOOrPp+yfT9k+n7J9P2T6Psh/w+yH/AA+yfV9k+r7J9H2T6Psn1fZPq+yfR9k+j7J9H2T6vsn1fZPp+yfT9k+n7J9P2T6fsn0/ZPp+yfT9kH9OILemgb7UF0IdLG2kFtHImkK1CwLXVDeNUikcSluf5gqhKANb24qvEgQg8pNALWbb/U9i2aN6l0+9Qta/qezUdGeoUyqJNpStGsJtCwG4Jk+D/Y/hxFNTdnRwDZldJWSA1Te1rzE8M9cSVly/Gs8u5bHDGNNCYE3Vhe74h4EIDL0A/b0mZsZnBy1t0KPOY4PKo9iBdeYUaQsb4UqW6ZjIeR1Hy+Yxu20HV8P6d4MRlwdhsOutxCiLeAcSo3pTHUvaL5SmLXgmHqXpczYUlAK0awcQ56ykktFEFaF4XaqMaZubQOBOLPKZLeZ/w0gMgiYOL7y9cqVlfPWIgQW7Ltr7eAbl9oH/ACSucKphb6krWFaugbr0DMzINi1XL+6RLZO/vpAYkcRp1OSIVXXEC0aWFq6EwcUsGjDGjKTTuMHUoWu5MoRddes1KDYlWsOsxrIW0DpEEapuqhB0tbioYwV2mq1zdmdq4gSANKQM2HG3t4/2dIKRAPIM6vsdp1fY7SrIryECBAgTy9J0c/AD1ichl+oiDJUeSZiF8QmlqDu9HYl7QNBoBwEpSJedV5iNopciTLcrr0YbpvtFxtNfKJFUsJUqVAtieD7IfrAqBPAhDYZZZbB1nLLjGXrvAAaBFtjpMmIPXAykc8estcVO8wPU1WPUi3ZiobmHYR45vI9IN65D1I0goa3lx8Fqdf0gCJQIxd2+ZUCEUkU8pdtu8vBcBd8oPWu0RSYihaVLc59IjSg+YMLRwbahN9fiXZVxurnoRnaU1jIXWg/MVkp74mU3cnPlDNdtu7OZQgq4DZ4gUuGfL3iVKKV8N4Y1+0LARwNHoiVJCBJLG0uoMTZd4nmDajTrAYGNGsSngdDQhJA75gxa9crTRM1GF6pqzEGnyYFzW3yEoUFKB4igF05OSOiQsdiU0C2toNdzdGJmVElD/CKjXEw2BhLg0lNWGGAINc6DxUAwVRGx1YS8A5OkwUp4os0OzTK9IWA+g/xm63moHNmhOqs19YVUVTmq58qzBIa8inJejyg2B6yF2CbEfmHwlaNwcJ06QnVtRwNOpnQmA90AD2JpkcVHzK2qMCi8aHqR7I1ODHLWYDuSjGFh6QVyht5G0qYv4cQ2RxeZYgWlXKOq8ly13zERdl8gSh7zchZHWEDYydLzGbZSyyskCnEp5GLeR7TGEboAfZ3iWLM35JbY1lJIqOdFF/MIkuMQ0jgP4gGuyG5rWUKkGx1D9wNx70q1ZGx6wZqKiBN5ZGOlTrCTD+GkKo+l4rEAiwm7HRZBfMTnE/Mxl61NUqd3H2FmXWYnrcoHP5kuLV2AfKqYSARlS9t8DycMBXFlWh+yUYvDKrjDbcjgGkbElsLy4yf1OUMzucnMBXQY2izL45ybPpFijn3dpe7CB58Ma4QEoQsvEY0Zt8C5ZnLvBa3h/lMmstkIej8Sklx5CWZNcS5YOECFJWiQ8AZJoOejNRhUYTMcxLlYgNGwmvUMQpZryETg0gvWAmYYCUNOkcjSoOblO4BmKmKsfFfuVpWZhyxHaZ9xUDFiJNnsjBKoDzQd5lqFL7C2rs4TmOsdFd/LDYRmhRLQOwxdR0cMKeaBG/AzKB6d2GWq/QhLqSnvVfEaoF3vGAoL2m0MSpj/AE0gcVDWH5ko3Ffl/wAltI+DaCx8QGuvL/NYApjAE86ETrAGQLyfqGPGi0fzmHLoBauxHacARfx+I0ZYtmCT8MWsGAAoBgA4gvDcYu4XejF2Spc1EL9W9dJbPMS3dK/czDS8R7UdyJmChbu5ToJRAjWGnuzUlac6/klgM4a+XMoVdg+I1+g037EW5bzGWcodO5iArWAtLKhrDzRtLoj/AByQVH2G/wCASjK/INerd9YJa6ruGtDqe8QF27uiXLH8EPgj3OWuurOVjl3YYavHnsj2f4rS4+VBWvxKJqW1d4zV2jljl4V+Rq+0O81Vuj+Y/hfZmf6bOriEqBjaNtEm0SMNgSATHvNV+qvPe5+N+Zo7PaKaq+FeFSoEGJKlSplEZbZZe5Y+p1ATBqoOrg76+UZWkpSj0D9xxQK1Cawq15DZjsv5iDErTcWbJuecGGR8zX+LvVcN1FBP/CvCoEBUJkQINYPKOLgYtvGy0uBG4wYvY/MWgaSqdt6mo/uIJTpeI+eh+5YpQpuO75RXk1I6Uhole0QQ6jTE/wABcqaJUqBHynmUoI5IC82lIcIx3l3gjCOrtsRuNlvWXTvHyNDABdLtgqlnsiqNLjjYbHTTeOfFaNnE2gGyhYgyGVk6j2l+XtDme06T7QXL2luXtB9Paj/wJU5XtCnVXlNin2hWlNy4tuvKJgUIvBYUspXnHkhcBqysOk/trGY3LNWav4itXMkp2PxDcrFYBrrfiXKaJzDx1ajiBAYUDWq6EAB0K0aVr+Yoi01A6X+BZkRCybmp8wxkGw2JUlvxNzZ7xDSgZ1dD1lCGZZL3NYMOGLPBdX74mKkAG8GCbaPns+0Raz5arhp+YYDU5KtNYG2nC0YVdmrtPA6kKwXsyw5fBNQ4jFjWuYOipheGeU+soHOehLOka0ClZB/PkR4BlV0XhAQgSiEFKKY8idJTIDIJfnSxdeHWgyu35YESxiV2Q+gJhQOiMLQsRlKp+CBFgAIer0YINCgoyKte6yuil2zUAoCgIE5Y4gdgF5S3eo9IrZHRGrr7+8EoZXgF8e1sD1ZrrMLGHic1HrLDrDe2i25n9vTwGsuaoYh4VCV4jUu2LRXhfhfguMyl3cXGv+P6On+B4EP/AGYy/wDH/9k=",
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
        "👇 Escolha a estratégia:"
    )

def _seletor_estrategia_bot_markup():
    m = telebot.types.InlineKeyboardMarkup(row_width=1)
    m.add(telebot.types.InlineKeyboardButton("🏄 SURF", callback_data="config_modo_surf_normal"))
    m.add(telebot.types.InlineKeyboardButton("🎯 SURF — ENTRADA POR GATILHO", callback_data="gatcfg_menu"))
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
    markup.add(telebot.types.InlineKeyboardButton("⬅️ VOLTAR", callback_data="voltar_painel_principal"))
    return markup

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
_CAPA_ANALISADOR_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/4gIcSUNDX1BST0ZJTEUAAQEAAAIMbGNtcwIQAABtbnRyUkdCIFhZWiAH3AABABkAAwApADlhY3NwQVBQTAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA9tYAAQAAAADTLWxjbXMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApkZXNjAAAA/AAAAF5jcHJ0AAABXAAAAAt3dHB0AAABaAAAABRia3B0AAABfAAAABRyWFlaAAABkAAAABRnWFlaAAABpAAAABRiWFlaAAABuAAAABRyVFJDAAABzAAAAEBnVFJDAAABzAAAAEBiVFJDAAABzAAAAEBkZXNjAAAAAAAAAANjMgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB0ZXh0AAAAAEZCAABYWVogAAAAAAAA9tYAAQAAAADTLVhZWiAAAAAAAAADFgAAAzMAAAKkWFlaIAAAAAAAAG+iAAA49QAAA5BYWVogAAAAAAAAYpkAALeFAAAY2lhZWiAAAAAAAAAkoAAAD4QAALbPY3VydgAAAAAAAAAaAAAAywHJA2MFkghrC/YQPxVRGzQh8SmQMhg7kkYFUXdd7WtwegWJsZp8rGm/fdPD6TD////tAEBQaG90b3Nob3AgMy4wADhCSU0EBAAAAAAAJBwCdAAYTGF1cmEgTSB8IERyZWFtc3RpbWUuY29tHAIAAAIABP/hDHVodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvADw/eHBhY2tldCBiZWdpbj0n77u/JyBpZD0nVzVNME1wQ2VoaUh6cmVTek5UY3prYzlkJz8+Cjx4OnhtcG1ldGEgeG1sbnM6eD0nYWRvYmU6bnM6bWV0YS8nIHg6eG1wdGs9J0ltYWdlOjpFeGlmVG9vbCAxMi40MCc+CjxyZGY6UkRGIHhtbG5zOnJkZj0naHR0cDovL3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyc+CgogPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9JycKICB4bWxuczpwbHVzPSdodHRwOi8vbnMudXNlcGx1cy5vcmcvbGRmL3htcC8xLjAvJz4KICA8cGx1czpMaWNlbnNvcj4KICAgPHJkZjpTZXE+CiAgICA8cmRmOmxpIHJkZjpwYXJzZVR5cGU9J1Jlc291cmNlJz4KICAgICA8cGx1czpMaWNlbnNvclVSTD5odHRwczovL3d3dy5kcmVhbXN0aW1lLmNvbTwvcGx1czpMaWNlbnNvclVSTD4KICAgIDwvcmRmOmxpPgogICA8L3JkZjpTZXE+CiAgPC9wbHVzOkxpY2Vuc29yPgogPC9yZGY6RGVzY3JpcHRpb24+CgogPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9JycKICB4bWxuczp4bXBSaWdodHM9J2h0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9yaWdodHMvJz4KICA8eG1wUmlnaHRzOldlYlN0YXRlbWVudD5odHRwczovL3d3dy5kcmVhbXN0aW1lLmNvbS9hYm91dC1zdG9jay1pbWFnZS1saWNlbnNlczwveG1wUmlnaHRzOldlYlN0YXRlbWVudD4KIDwvcmRmOkRlc2NyaXB0aW9uPgo8L3JkZjpSREY+CjwveDp4bXBtZXRhPgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAg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8eGQV8fZ67l71Ueuf6I8YPiVz2nMe4um2dN99xBB/YBaf+9sShsXJqAaMIw7/wD9c2cp/s2blg60/Rt0zDSH79MiNcXgQqoALseorD8e/wBztVLvs6gPVv0/e/8AOS6Rb+cP9xvHbi1xVbr4t3OcI7ymn+QNhTM82IjZV76lxHXLLADO0ba/30C+hyKF7dFezw5wIMMIXSVfXQapWBIFJEL/AHWLKN+O9q/RHql07xlEteZNUEQiUPKFWCR099Z+cnuQWfbUBIHZKJsre6aiRVMLK1Am2cuQT567f7z9FPBj5WNri0SLuZmbPV9YeAct030sPehQ9NpQglKStxDNxK3T8ISiCC8zhh3t69NRigRfsbYn05//ACOzXyoxpjJGMYbdXdnLUO/L7wgh3DeR0E+fo0g3BnLC8KZO5Kv+cyHS+7xmSqUtgshnYX602/moCR3IzCWl38AIoicofTjJcDn5fKQx/Srb5vviHtXMM+bycGFBN7+c5/8AKn4eiwH9Zo37KHRZXmIp613n0H/YPFr9sU2teOQ6BwSyduJ1EhqRgrVTfoCrK8DNu56JKHCtQEE2g7thvP7J95ue0IgQ9IK2+zuDxSxZsRTmOHl2Q1AKv0y20Z76cq+GbVJl3A/0rruekiW546X+kpRHugGX39yBpeOWznzzzzxm9GCwmZ3vsQT5v/8AeyltJhCijHJmTiU+/V9994oeTtMd8t8888pr7TIdsIdm5T0LG/8A/p6iNGqAwbpAC34/vf8A32H2/wC0s8888888ksM8888K2MscC3280/8AsuujLAd7e5gaW/8A333red2Xzzzzzzzzzzzzzzzx+bzwlOqcP4wcp9BJ6ZieRml03z/f/wCJGMc888088888888888888888dSIgB5/GXd5Jv3KYHNVXVUwY0row888888cw888888888888888v7m9RFl9ddU9okwAlP4ooJt7pcpV88888888888888888sc8888MS7nXWy4bGanbCKDmcXC29Mc889E888888c88888888888488888cd19VdSPKjvribmnlSvs88888888848888888888888888888888cMo0O3vi5nCwNm88888888888888c8888888888888080888888888889c888888888888808888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888/8QAKxEBAAIBAwIFBAMBAQEAAAAAAQARITFBUWFxEIGRobEgwdHwQOHxMFCA/9oACAEDAQE/EP8A5L0Cr2LpYiKJT/KIN3uA5WciwOonI/8AWpUB1LQlhbXpENXSW3uypUrwJvxaXFTkBL3qv5RliLCym95V6KNTm7/41KleCvAwGPBUqJEVyimmnylKI7kt3GvpK+xDasW7bH8zHd8/UEPAqVK8RwmB28SvA+Ir6dfsfH8fq1+fFdH3IdD1J+wQXPqJc1PBkwojTo1sxliwGh4mBg9DwVK+gMJKlePwnx/I58mjqygMqrz7y/7H9T/GfiX+x9oCACLutx5m7Xbc8vCS5vgQC2IGiitZn+h9YDDDCRPDV7Hx/HBUDeAILx2v7zGR+glrVg578+cAdJ9njwt1iW0LfYhleTMrtPQ0RxF8eF8NGxfa48n0iv8ARjw/RjYUDEiT4z4/jmpvo7TC3a93Hl9TFnVhlgvA9dnzlJU06XNfhwPvAgATqgyFQS4WKfLxl+BCm2hyxUX5/LmdZOonWQBVcOH7yhiQZ9vh/Gtc6GV6QdUwYHXb0iq2/RUCVB+rZ/UYLhDq2HzmNtGFYcSgQDRt52hfIrBQJmbIp5gXJknb4RQPJ5a/iMyPLiV4kKOrDL51NDyRgZ9vhE/7q1kU0TWrPr9ATVTZz22gzGz338SBCCSXq6Br23loFCtfBMtS9d5UXVpzFRTE6o6nrrEK/mBfemAgpZkEmhXXDpONcGVrRUdDeUm5z3ceJUp6QFR5ok1a8korWdGbsY0DQS4fYfEET/jRqb4D/iQTJks0TkjfXA/DERR1PAgltYgBd6mPDpFgLP6qLUKDHldiOKN2Xa1cryIhcLxH1lJe4mr1WGOBqhcsdwLtIvAR1xN9OZYqb2lgymAtI4lLooHESyZ5H3iRpKIaQ0svvFIBaAlmcTZFqTnd+0TgGCe0PiJGHwBVSziU4nZL6QTiX0+kFMWB7rP0H8z9h/M/QfzEPlSfgqsT/YfmWpTW+v5lypbIXeOJh7sOzZhAggN+lkDQgo04x5wAuqnByzVFlrl2gt47UqDaVwKjyRNuTORnoYwujl0m9SVb7EG3FMNTDvzFizyNP6hZQcEP3iJt40yC/wC9Q+Ej/Ja7O0SBF2dJoweSrz73HQqOruTO36flGfGnF7Ql+Saip9AkdYqtv/P2R8+KoKA2uD/p+J+wymQYwmCF7O2dSJgFNRrUhz/Sc1BJh9JWKI4zMq0IpbZ5+4IkV3KK/NHQEeAUQhWxwflmrtGwYCdNgx/pbxK1/feEhfT2e0ZoxpoJ1FjfyU2nD7D9lgmFmom8s23i7doVGjvLUig0TJhG/aUNEO3t+WZV4p+B5eFsqbTTqRrMmaVowfnwC2oJBDQTV9p/rRbCnzhJJBxGAnY9CV9HtD58LGcBlZuaGh0IDmCgH8hAV80wHGQfmAwB2gDMIwKVpasxAlN3vKWpsc9gmUZ9mj1l9th1dxlzRHzXtHbDT3e7FFjAbuvaMwQSbEaW95cGVAd7U7MyLBlNncl9h51Oo7S3bXXxdUazHhD8xoWiPMTaKm1VhdtdIIYDB8vaJRLVtfFADkiuvuR1QB1rwsSjodcwxdUS93YigIimwX6WjKleGl5D5gmYHu7zEG7Ch2F7YlDMrovK9HwB2gGF8XDkestGTpDfcZkOC5Tfkjg1iJqP4QRay5dPKMKuYos3FXufxNLIRo37sbXkUsms36nk/DERRKfBQRRNyIoScH3JqIHRGxm5ESSnNRndoHVOkfI2y50XylrBUDXvEldiclX7QAsVRFWR4qX/AEn4l/1n4l/1n4ljoKvJv5TQ6tLu5bVXjwcR3cJVJc7fbP3xP3xDLK1ErwqWdg+YVL3dIC5iqq+GA6V96NhTPDcSlWR17RTL3dIviC27EbANIeY3xP3PKIgf6gh92nXUfxBEUTSmz1NpZl6izkb56+XEVW2GpPevnwLACho7nnHG2m/J3PAYyDajXWzMd978S79PHgcD0T5gwTBjW60uM0y9dy0itMPWVdkq24PSAi1IlwAW1r6HzvuzhABTCXjPSPaJXYX9vB+xMJBMGLpK5oiGZbBE50NTwA2X0eyWnPpPxH3bucdoLMUswrW656yq0DsD7TJS4Lu0QXLKy7+qn73lP0fBFKyMoS2A4BWlzpgYHGfE0OUIKLq+fFEI0kTBSC3FZ9/D9/cn7biXfr4io6P2MWXHE/W6oYzVlW/Ly1R7ESXgGops9Y6Bw1BRslxCzpZhwQyxBMg1oSn8BnRFrRM8PXGCB/YQRZam3T6ArDHMukVD5jW5DWtpQkRIyVXPXw9AHoJvDKF0PxKKpaHnFMKj9pYzYCXl5qzo7yter4nu/mn6/g8K9nwiNFHxvr4AuhLSgKbQSI5SBV0xHaStfFtKv8zwWf31J+24mWb/ABmvIeuO0Nlz5sL0UoAGFKMAc4j0jzmubpXqxrV8e4C684BKBYNQ4EFArLRcRKuYztt10G8VnMSwV03eHvF7J2tsr0L3ltX1Ypm3oaSg34cKdV6wEIrodLNNrzjB0sRhhNJ0PowfaeTOg9GG8rt4BvdzIBlB05qrxAy5UshTg7R6Fkhp8FDQdfzAWmFQepHdlz4FhA4TxpEUdMzwA/tEgglIaO9EXC44Lp04cwG30lUNl+6ME6nxnhckLFpRmyLkBNa6vpEbVYq/OVZZGq4G/QJboms01jC0lKA2w7Y2t7QIdCbNCxvDtEa0bwei/A23H3QAg0q/PEuA2adRJe+qmG/28Q0sLDNOZ61NJnuDRPKa/Wst41gO3D2jCHoZcAmClUU65R1e8OuH7hN3o54BILoZfUD6G0fW231g+X4xcsvQYr8Qa7x1WWBOvnXxHJt0hHbYXLnzdCGIG0g0FR9APA4JmQV5il+0KUnHA66j1NJojsXBAAlhxS8/eAprG5WK0AGyqe0NaSNiNl6TVbiccxVkA5bL3ZZpHidVGyRZuyhR0d4304I5MnPrEDuaiBoaVu2aEGWIAjUXjrywCApQ6DiklmqUqhddLKjlwCZd8MX+Io7Xxl5y07Fa1TeE6kRMAqze6A6NRBRsbFlVo6xGqAC72vcygsMK9+wp9YSxPUstcXTcDm4DhrkYZUUlDm8hKXRw7RZ+0jfRqNVsBHqmW5vP7Rx3A2RDNwbrepQRd8G6wJSFeoNSmOGicZsMysUdrxRA1pg1XwMZx4BoIgRyIYbRkzADRRg/af5KIDBwBsqZwQ2RaL4hYDiachd6dIBzWHJtA6yuCtTyO0IF9Td6E5fVc6mJeTRkXICqCU1DYQaDZsthLVYBo3gwiCOtPxGwKwdDYSrEzIV2DgmJxx3S7XqswB/REA2WcukyaQVXoYlbR1trU15JwPoOW/IEJdtJVrBXohgyy9i5pf2uKu/SKusHi1p9MQxDoPrhluM6S4BRFbExYbjMwI1SltV6VflB1NQUVpV0bfMcgnd8wy438ykVhogda9ZRWpKctXklSVoUW+sjLYBsonsEdWRWqL96PitbRX5HyzXdL2ZX1tIdxxEArdvvVfJFHmUTHca2gDHlNqa1PtEIIquqarEgoJlW+YtqxUBpxiUkjvns02udXAmy6LiWrDMFZcX1IJM7QArlWKDTA1TbHL1lmW/8T9DwRCWg30CU3aPvcx4iTgbdmVrr8kSMHITJ7ErfW5fxEdi5fRRiNI6Lx180Q73efvczeeKe8y/uPiOu/wDNH1P8iZsQH1G6OJYItvqXz9YVsTc0ELEFu81cLvrxC9KJYmRmH6tTwFd4/wCBFqG8MCZevaD+gQCR0SorQCuYwmg07zMBK5M7wx+jhgoc2+0JRt5lJyMcoAWgFSGy5Ea2breZZ7V9NmwxD1TErTvUKVxTKa7l+wRC2X5z9TwTCNprsuLQBOpx2iiOr9aS5Vijy6QD5hnRArCUG0PnPlgwphR8werHBUgTgigOy/dYrDYPQnqLPU3xH+7uhch/dUVNDz8ELVMHUrm3d+IzQ7Oz28QUAKuxN3tw+7KS8BoGhDSBNEhxg9dfWC3GsKdS2CoSqeQOz7onMzOkKDkTrFmozgGmVox3j+51mVey35zMbfC72w94FA11XrMG5pA+8ed6x/tIjwI9XxruqAdrzWIit8P0PB4CcXDq+scQ5ByItS+3RYsnTiPQ21N8i4hS2Wy7RlY24UwqZFBMlw2R2ukSNM26wUdzQJXBtg1Y3hja1a8xivenD2fzHVAmoyvAzQ7lp/UAzJW/Xy5jprxEy9iNBGm/L3fE0BlYIWV4a+fEeA6U0l2rGvy3WLg3dwKl5+m8RGJloa8yoyyi2oswWYwOeYKo83szEgwDWQHmfoH4iollJTQIFtgCAB03gWq6GsUA+NnJNHb6Q/pZD8eKo2wZyK9poSxXC/WWtBCysBLKlRVpZLcsvDNSoCXb7wKLR5RJCdnZ2ZnU39L6Q0c+y8iCGkr3O0MOE15O5E8EBGkbGPCVWXwC5Up1Xfsbx1EnufxKQmHJRwQHCpvsxuIay57jEGVuZC5jUW/SP7R8Q9JCgiDvmf4U/wAJgFZO/YQG97oz/GiBRDe5xAqpoe8fofv4PgfTeNXwsLWHOg0KIG17MorI2Qq49yWQkterLmdDLCvIXjjpENNeo/mGp6hqfiACXy6J3JV0w06OcPPWoMvPBLHyS4HbK/xFOPaYe5HCmHRMjKh9dE6F/aAKPKwfmBJALUoCK9ewKuqcyxlc6idBiIOCWzmoPd1hLVOt7C/Kouz0X4iKOwPxBZWFkpY8hOSTkEVuQrg3u6RijsJfiC3RpOsirr9Fz0iwfAAdQUxkjSU8SniUtemT1diKrbCXy6h8sASXJ1JcJ2DR7kBZpjNzKTIYqHLyu+1cSuHDhF6mLhstksYxn+hhglHLRa+cxwnBKJK8lvrWk6wRFeqV8lVQcsABkuXYgKPau7DvzMA0vEUYAvAP5lxOjf3E2DSdSdfxBZcvTvcQqhXTwuWyiU5lJ3J1mXQBLhB8BYLtGei8X5R6DQ93nwIhOtB4HJ8dobYlOR1lAqlVXDMJWIBBTQ47DGjDybH4mGfLR3CXRhu79DliDbIaCF2R5S89oltmmIKsuU3mTQRUNYUoNON3vL8iu8VRfEVAOj6f1BB316PgCXgcOsXrF8AVohorn6bDa+8pwnYnY94t1t4lIQT1pVoQcDC5TlO0I4FD7PjcuWUDeUR5lz/souBUHFhmj7xQrfBEtjiWelnTTqQmk9PsMXHyAMAYCWIIFrTj0gwQ5dVq/iPQc8GwzVtxUZorb1NvEX6EBC+nPSMq3N8V4FyceTOt8OIjhBpH/jcuX4l1hwuHh9HMDF+FIhhGvUfQECi8BA3xlcsbdEOyRiaAUDTz4lDRBHacEeej2ZTBQ6MGRVxCVbIerz4gUQcEWqE5/RUCkgrRpefMdJvD8MRSOp9S7m017ke0UX+EFnQTavBeGgrddOjLLFDA3O14Su4qApYwHX+vARcDhOWnlxEKew/uZSrOHRIk5Fytcy4IAiYO4dXsQDR68xg2Qx2dtyYe7D7H6RbUBl+bpLFYv4RhLmAvGavd38TxK5YLDherDierDi+8YAoNCEFfAQBmLFtA13PzFacovgesLU4Rwdid0TtG0wRhUTVx8kXeETZsnTPUnT9ydP3JYUgBea+sSNMWWxwAMH8Ya8RDAwk8S5sPB9OYYZwmEb+AgvUOlK4TaP8ASE/zpzegT/HIZVl5fCTo6fEo3s2f5Awgkk8Mklyd3xMrsyvtkv8ARzTPUGViYiPhbPAa7RMWafySCDwCCqNDTo7yrirRoeJge09A+kSfXHx3wq/QNRMg5vT+TcGKwg+gHCGB/wAQC3/xLly5cZwoAbrN0CDwXLly/wDzBUIojYm0RITKra//ACL/AP/EACkRAAMAAQQBAwQDAQEBAAAAAAABESEQMUFRYSBxgTBAkaFQscGA0WD/2gAIAQIBAT8Q/wCS20vu0FbghKnj66O63CrG/wBUREk/f7pELBKK+19txPs1n/5OEJ6GLb6F/glkhDJnke3v6bpf4V74Ep6GeGPG5TnSoQ99EylKJeiP7qRe4l6k6EqoqbDei3GXRMpk0b4RNEEJ9wsseX9B4fgadg2WiZ7iAmmkmPptpSmwSiJq0Jj+349alGzoVGE7g4FuJnl4uh8viGWPDInkaaLP+zL0N03jCLo+/pQgvqp30Nk96KPE7lGiW4uLC7OrIj69ujeBYbGNeZCWtyLSxk8lQiMoPs4GxehMWSiiitEfpWsfbGOzZ1k8sa0J6s2MajMvSpZey/bKIlWxQN6+h4KwhSIkqTCekLaeUbtoxtuHyIcMkyFTfA1RyPOBrhEfQl6FuJaUpS/Rg9GzIsoTxoyHkiGuy3KaVRdDVKIJ261YgkJg2IaGlMrByBcFMF7lXGJCdFY8I5NWtEJgo2L3aI+yEIvWtJ4JR2V2RrBV0VdEQ3JCT8KLsS2M9h4bsI4wJBLR7C6ZdSHhoXhui4sB46uyg7KJNsSi1apAtVzBL0tE9UKmCrrhuEXREYDIcNkInJ8rEIhGw2xqoSIWsGFMZKOrgTyXFOPwLfRUEmrrkyTJEM45pnsyVjXWk12QhLTnboTpgqK0uSrsqyM/bNv20Voi5L0LRi2IUvocfYTzE6vwXYuS4IW7KmsEzRomrE8avHnTYxo0QRRnD4Eiobpp+Qn4/Yko8IaUWODYeTb9jaiDWJx0JjVi21aEoI4HD2OXuJ/0FstEEOFybFEkCaaQ9Lt3RsyJpLLLaJq9Pgew+AhsGJ1PgQ3BBFwxsR0PJbftpQxP/dZiirSwzGq3EcDh7DK2/BnoScEr7D8CNo9mJtdG6HdEpzzpXYxthMiazbI0zBvnb8HsMirSQeN0Kp+BbaLde4thkP8AwbODwocVi44I8iMB+BJPnSN2FLMHwJHHwXO7+RvLnA8pNI50WpZ0D4Ex4Fi+X/osWhuofInsJ6WISii3Njh7f6LdGGn2REREJKOj5Ior2NI/H/hMn/ukGq4+TbvwJJK9xveI9hJSrozT3ZZrwYtl7syTrkbSwilclaVDqdHI3uKPyJyRL8C3wYbsfHbLEKCPA17BklxwX2P0DeHhCYGrglN/MSaZdQSv4ZhJe4k99LpNM9L8Eb/JiQzyLY69yYU3Khi2U8/pC3S8nAnPkRNttkPd4WxMGxCwUGoQm/IbTGNzY7JrKQUexG5G+ETQ8VdyVPyPaqITHMPJUq3DIjkciOxui1QGhWiTqb+BZmBMqkEnc6M4eRpvGwkN4YtjoWIbTpixFxn+hLKyt0RdP2M2kl2LETkSEsM2L2P2D9A46MVmfoNxr9l1DVcVlTYrbs29zJURzbRckR4VQknyosrOmKvTf6ZtgpBbkJlDpbi2jEycbY4ZYtmwq3WJbjWDYvY/aNjRNJ60iIhbDC2C/cbnwQdkEcoQmUuiwN4L51QhqiQzkbMnyNWZH5QlezZl+wuBYe42puP+g0R+RSJ1Z+YZMurLpNW4MLWP0ZpQWRrYTH4IJDEqc6tFzp37CKUaLx6GciV0hNZTBlTHRgayV8+BLY26F7Q79uzD2hPWCWrZDkuyx2c24e72JQV6KJ+CopibZulGxFOPopG2nyfJdGk99GIafZex+5odqRGT/AnWHh6F1bH7mSZM7t8DW9hHKxJLkTXAjIxlKXyXyXzrx6KREnoedKUUEyrsbRuLRcCWwyTktXTGr4G5WgkIxm5yQh6NglbnOw26V8saJsJFgeEZ02Fxn0GrlehfTpWZ0pSlLoTvoNEDC5UKho0K2K10XxBYaY7NohMrVmD2QkWBKb7nweRPQl6GoxrRfSpWVmdLrCaobj0vCNl5YtxMjGRzJZMAlQxvGDG69xJIj+exYFcUS3EJ6XpF0eBEXSIuvtl6Hn2GrNh+CnbsbhCJR8QTsi5EzRcifro+vs0hqelCL4L4LeGN8emCbQ2cFpwLQnotWzbf7ROF9VKXR6ImSCMmMYXAyCFuIT8FKVG4393PRCacv31W4yCWk0TKUpSv7+ejn0PWaT+IglF9JeiC/gOP5nD2f/O//8QALhABAAIBAwIFBAMBAQEAAwAAAQARITFBUWFxEIGRsfAgocHRMOHxQFBggJCg/9oACAEBAAE/EP8A9UeMBrJYOQrLGP5V6FAkWxZZtZ/9IrmEBSxReaMf/kdSvwKsTRy0L/8ASLIFVll06Wf++oFrRDQA7jf8gFOaKKPXp7prps1o6AbvuekJT9rsf/kbl+OdY5VerXlrpGjIPkLVZwn8d0zOtEs2OpmIEVW1cr4P7QGd3j86xE70rXVbq/8A1LI2QG8w0bv2gMBgOS6A27/8tjwApwXrOm3hcuXLl+FwiunJ1r6nGeGAyBNxTI00JcuXLly5cuX4LD85eP2D3nz3H/zrpWDWzvXbaq1bv6jR1PdQRl506K32/wCO5cuXLly5cuXLhAxYxcuXLly5cuDM3cs0WzR16RFIiI0j4LpooFrBeAiOQH+fuA9FXjXp/wCKmDO2/UJegt7B5Fb+I0Re6ygOODv5j+e5cuXLly5cuXLly5cuLJHmXLly5cuXLgwYbxqBYnUZjrXa3XufZ9YypalhRwNXAlYUh6z+P5HkypG7UNPDT/AWrVixld4HkrP/AIDLqQBb2PevGzG08ImREyJskstwTRZ04uDo/wAly5cuXLly5fjcuXL8FxZO8WUuXLly5cuXLlwfBcuXLl/wkw3D6X/mHPZAWI8kGj20i+AW/DZvBEs/huXLly5cuXLly5cYuX9AXqR5S5cuXLly5cuXLly5cuDBgy/r+6/+bIAESkdyareIwuTv6xtDFsKLEePquMuXLlxZcuXLlyimmi0LyhuhoRbYgQK1hjiLLly5cuP1IoXLly5cuXLly4PguXLlwYMGX9X37+OUz3A4aqE1M3XP/iAvbOhE68PI0YcsDjSkTZHROPCzUKJi4sxfgk8lJ/s8f7VHb9dP9l4A+A/c+c/cJSFcwL0c7fUAVa/wPEvwX4H6hF68uXLly5cuXL8Fy5cuDLgy4MGXL+j71/FP4lea64TJVZsz9RffkznJNK0x/wCAjzJx3QrVburTME1IVXVWCgy6mdbPjSfAJ8aeGYrxcymv7o8Dd1zrBrAA3HI/SDovoMX4LiWmgvVicOM2wpyXqdTxLly5fgvwXCLlwZcGDLly4MGX/wAdVNx6fLnz/H/LRpIKSwUzrhP4wbrI0AyrBYt7whv3dYIQaqWi6HbdiUlFV3X+AW3r7exgoUqk7S3xq7+h5fSCovpQAlBcdN+A/cEpbbJfgCyulG6Mj1JgLjsYdj7j0gNSsSx8Fy/BfiXLgwYeAQMGDBgy4MHw+9f8FbVK4M6u+/8AJWwq3gvB3WXpnNYP+N6QIQ12fNv0gV2lB1YC9dpfJr+nT+LFNv5HkylId7m49GI3d5N9we3japVIDwLOJWVZ4a+fEcUBwPB6UiruS41iyxVv7nUzDbH4Bb9w7a/UAi/oJJAwggggfAZcJ96/4LQmDXWMrgd3k/kQsAEDQEuyA8GFlq21XlX/AIn1LbyGA7seeqnfbsS2xF6OhfPT+MrxQ6pa/wBRMyMPIZHzI255bQP3C3hGUAo006PD4xBEs6j8cxDRrq1/r6J6G+igVZNRLGFDvJ9BdHRz1mWmmk0R4RyP0Q8BrKRiuFE0K5facjw/y3gR8k/E+KfiAfE+0C+N9oFkJaqTjBHB1TuDCuzBly4M+5fVHmAqrQBuwHOaCJ6b9VTQ0I9nZ4ej/AbvYa623/36oGCNNJexoQ6VQeEPzxLCtaOA0P46l92D1NaeWvrE1RLE2SEw0/lNPN4XFdtYLNV5YWCRyT7b9xm1fgeGDVZrnwhyaoGnn4fVieopf0AxUJRvHCbnSOaGaHX4HZ6PlC0zBh4KxFYnJoHeXKDX6OhMEuy6lL2L0nwT8eIy3+fn+fma/s4CIFotOh0YVcPk6bP4QYMGEXroD9LrPWB4Ry5omghTkt/gEjBkXDku0Fq9n/tuYHQadR+DaIlbVtmCNvo/o1f5dcVX36M0grscrtHIWUdHfygICJYm5GnTOhawBzjb8kt4FIJmFYPnu9Ca67a6djaEIAALVaA6wkRwrU6V/SGJWlUGx5h2gmAsSx+m7ICFIliRvq512xzadnHaXV0i9aF+FhDsqjWm6+WkMhtcHyT8sREtW1+sm0fyOfKAtUUQ9RIJZAHezTzQYMGL10Bg/Q1KsA04bETcSLrQgXnWp1PSYnFnIIvcGr/ApnSlpZzrKuAAA0/j3SBg7ctc8bf8CwiyCNAC1ZcBvubaXrqyoF6A+Qdt2O1aWvV/lqUKub4/vpC1ThGVmEZc/wBIZkdSyxL5SX9dXE1L6tjzb9tIgAAA0DwJDFY1/PgijJcYzz5YQfte0sbC5c9wiKxsWZOr8P0nldmYf4UmEPDSnuLr5IBQz90xCi8A8t/NK/gFhzj7vp7RIQwPU+zWH2UWJvBgxRwwYP8AKLGgctWqFYef+HUwtFgt6X/EsWU2ECHk+bVhlWqicCFX6n8wmTJKF6r5Dfzm3uU5NyIDd0BtfOB83YYVS2Nb1zcEA6iZPdgh6Y7rXsbyrKmF6+3HvEikbVyrEY7tFupx7RSKGZ8FsuLq/DKyPIdw8T0BlXysICIBVdAIUF0zgfvWZ+yehufPT+LWQVk0oG+jnyRVvWE6niu+jtDA8BVDDBgwf5MTRIrcBKLq92PqWP8AEeodIGWqrBXLpGOtKsNBK/uPXCyWUcjm6P4FiuA4G7Y82N/Ubu6HSUXldDc/j+WpUqVBM0VunD5RUtRqW6XgisZsDLTV26aaErzcsVrcc0JWr3Rr2ik4ILKslhrxKrqqI7S2sQBvg6dRdpsWDdtW/Ep2iG0QmgBBKj5WmBl2beUPMCxGxOkwvZlXzsJUYTdduHnOFDJwEyNUaBwHhUr6BLgmqFeKApQ7btt9dIsLbo7l0ruSxAcdW67RTCWGDBgwf41hqjul09C/V+i4xQWxNmp4F6HHV/42LB9Jl0YMjY5DozIWq2vZ5xEUdfrPEIEqVKlQWPVfc38nvKWMA4z1eQ7u8pIZ7dW8cy6JBwvV+jp4LR3aLAJXAGsyG1+N+JuPZpnncZcTiULZwHSN041Lu5bRJgZD7nSOXiNxGspl+7pduGAWMymfLmP3eIq0TW3PboSgJgvA6HlKlSpUrxboKC3a4RfIbN4MXgmxP3/U/wAZl7U7f0gBqJv93mb9YBwF9b4PkwYoQYMGDLgy/wCC49zzD09fEYYYfLEQiA6qtdA2W2VFY+ov/EsWLGBycGgzu/pK3Qj95iLOAbc/PX+AgQIRUqDTSU1qNeANWBcKLoh+eYJDnuncZrtzHVV1cPfl9olE0Ha5ZFaxHsxAOGcOh25e0DBrwQt42oG5TFDi6v6iWilCOUGMzk2u3HlBdc8ZeZUUQzgxdTfyiClRhcRBiCJTwL5A7tZl08FGgTfmE9g4/Z4ZVtDa/fzbdYKQKGxpNO0qVKlRPCxNMXiluscxFQqClec32FDn+sVStqwcJMt66x5tWEKEUGDBgy5cuXEAq0GVi6g9/wB0+A/mfA/zPif5nzr8w7LRLLS7PJxPjf5j8l94/DfeX/D+8CXGVFPev0NCGnAAEA0AufPfz/w2RYviCuX9N2jTe/SKtB7PU6ms1QB1NE5Oj9RCBEYMaRsCoBtL29w7e8rEFpiPPde8QyaLTY2/JlWt4azvx7w6VB1NWusHcuVaqXbRlZ2HvAjoald5vEyiMhXabxpq1S/SXmYimdHeATMRAwbEaSAXtEP3uY+7XBfcil2e47TKnSKyzgPQlGRYFtDriKeAswPnmTJXVuF6/wAMB0bgKqhqJOi4hn3NvKOV2nZ7S/EaRIkY77/gEdpRFmYaPLfzRroUv0+BcqDwKLFvdOmEGDBhAwZcvwLgltmU0793T/nc0rkBtGfA7pfT+p/jP1P85+p0np/ULyxW+P6gMo9FGro4DiGkUpCVM2ViPH9P6nB+ibn7UqOe1PzpEKXg60cJfKO4Fry3gvZLl4+Xt9RDwVhEJCIAzjqwloMh1K4YMsITGFBYGgG8IiCbWp7diWXTr+NItpxftFdo5AldAMsJuJnDB22844IDnTzJJgDk0O/PnEtmIxShotdAOV2Jog9EW/IOrviJBAyvL9p74YCBNYb83D0ZTWY4mYUN604e5vKG3qxfq6QAFHNnu/cSalApJeC7NGVUGs6vM3mrrK1ySjVVciaUu3SEpx2bdBszWAXroeUJVXQCx0jugOR2gpjGfdeC4menueekWkABusLIuzkdX9Q8BmWA2BaeiuIoMGDDxDKajgty+h336Re7LvL+P+esXhRLHcXO/wCtzt2Vypu8+cUUUcD5Jbmo35PG0QFBQaEUZ0BnG0ayA3AOi+Q7eXieBDwKkhlzawtdtwJWRRrBumhCqBmhTF6G7viCGq6bXbvXQ0OkBC1aCHqdLR1/cRdINxrsx25e0EGByp4kFcTHA/EY0Vuq5Wa2YjRvEgk2avu093SVHDbMJ3eXqygdYQQUfmipwOEyHCOsyaOY9Y07PrGw3slSveCrNkoXlPdd20oCHQ+jdyU3rzRg6J0ZYZlU9B+8RQKAWD7PmQsU4Zl3DTylAu6FAaImIiksgXXZvNiK0yD84iRn3cQS6DK4CZEwMDgIS8IsHnf8IasGhdC9PBj+wwLYJtlYvOmkxbGC7farGH0C+ARbStenzQ/i3xsusSmrrH8qEmDHi7fqWLFFFFHHAhLA7jHDbbqFpKEstnHDsxEUSk1+ggQJawNXSEix8tae7pCKhbZod3de8CK2AtTdT7RVMQh8CjlQ8l9BawfgjC0O+Wy5oCuwGsaGOXB2No45iu8pS3dLy5e0SWdzU/DbMU2uXeLFUvunhcIGLQX6btpAcSL2Po46mI0UIjFvOsSkm3OaMDo3j04Xu3RszcbS9QcNMrWbyIocjGuLrR5HRlzaHOReX5hp7z4e57MWtLQ2HojHIRzGHufZiJAajiCu4hS2Q9GoPzLC1LbaAN1lJ2RBiNb3HW4mDL0H5PjbLj4JmDhtPKDx7D1xHpMBNdJ7nQ+p65pW0jmvTlsRuAaAQGgAYCfKfxPiv4lWnyekDMTCLDdlGJQ+ti3XfvEJWNXJ70+Dy/0khRsdrYDWaVedP4sNUK8bV9Dty7ENgLNYXiXwllI3ygnjfXwxIbyYHp2TI1Wx3OYttQ2gvOS67dYlBwjDhy0AacvOf5kP6Fh/UsP6VgGvoRfZoA12KyuhAug6fQHDtnrB/wBbGNIeUGLkwKbBpUFT7A9W/nH0A0O6jrzHhFMj1DYiIqXD0efLLrplzrDTE2I9d4Rnvu77S+FdOxwGxLlxlw6z719CwmsSkiNETZydL3Ix0Qt9hI5rEKzDznvq7hvDYAqtV0dmHKfajo7xaYNKKSNpYftOc9J/RIBISjR3XHRxKSXqFfdj2mEQijIHZI3wGy0rbtiLXaW95bUaUOpsPOAXxZGpx85X0pQjSTKkJdrtfv18DLGqIlbrYO8t2YhsGg6H0gmijv505NgldTvtQdrd3Vd2XneBaHlEROVt8/8Ah01lEKBRZ6fQZYCq4AN45FFZ4s1Z/iRYiByQ2ycBEACATjpziIyjqGoZE7QZKHA2s46O0MqC4Gm75OsbtlyNT/ST/WQL9iCXjQFGbqFWu0d/kx1lYQKM0BwBgOhC9VjI+IHXSrcdxgBIXek/cYWXZtq7cRGIbU2sW1sRYmW5SwfIOrKvvOO5qxZf0FQHMS36pwpzCvL8wqw31r1tezmW6sREqv7ijrHKzcZe30yOr8TmvA9Ubk40Sdn6QC0WQH6IFwehDpXojWOIVQXdP9B3PSW6pwqBflHEorB3evSOkWFcxoS6teX63my6231XeAiqTIpr0i/7s/3suQTgKd5H2PEeRRwXtr7eA8gC9MtVBCNvLVuvWfsYjtC0pEwxGbe3+EZf8Gj+gVZmqXbW7O/RRFqVqZD3NPI1YvZSL1ZV+3P9fP8AXz/Xz/Rz/WT/AGEKq+EKDz34mivCaj+EjsD5P1P8l+p/kP1FQMC1QB3xHM4xCrq0H3lenRZr2jtpOcOinz/IhClDnL13POLKagLWPVA5szXVt5SvpavD9jHBHS3B2IycxFgioWuEft6EQo9hnybe8UUKbVlxY/QzgQbZffV6SzPlwROo7dSYL9F+ApmCymUXrtu50YKqLVMexe0QcMUdY1hrEpIURMUPb+SMj7QN9qtILK7JV9R3IyYgNBqlQ8+emsaGcpKw73u/aNtJfVP3EOwSpoBEKkxHTnu/z+tcuXNcyxgmP29IJmU246nZsecuy22Gj5X/ABkmQsTIkIGX9bm5cMoslpe66GX0jPtLV1bKdVhylEYANVipCzmF5fXwIdQC1QXuy8Vdiixo8pizXXqvb6iaE6NT/TT/AEUKvI3eIuUsd599jqlhEjIBSBoc88wTNNjoroXQj+W8aL3d5RgY7ARiaBmC+wO96w17HrCziMAUHAGkXwfC5cOtTQC2bgDuY9jXseszYBQBQdCXZgWSKYeAy7Gnl6QYQLqrXn9Ny4aeG5MOeBeoGrqY6QoUDkGQ5E1jm8QrMJpE5M+VBLjZWp1YtA0b9C9F7EdOloBQ6AaQCpDrgP78pUQhBFA0KqoMqmotI4UNj1bR8RGYLVsN04l9hSED0Ylt5F/M6fydZ8E/M+ZfmfMvzPgX5guh+HWI6j5dZ8q/MsQCrwn5jEwKRYdY25d4KZIqrVXr4ohS0b1neKFziRATGoT4R+J8g/E+IfifLPxPjn4nyr8RJHfbxW533JdQYQMuXLlwtgFs1uwYNOkjQDKxFNs9dcPuejaMUWsAa7Hw08Qq4FQWgdIeM/calVhdXs6cwS6RE4T6BOkAAytRqyERwic+Jo7/AG8B66b+H9RNgl6jDkg+VvHRdfYS/wAEdUWMPVO+1j3fhjawVhp3WDY6sYUfUMvc39ovjfjrLCJkcl22OrGXf9Qc9zf28DCTPv8A38Fm+WpldyUbZymfc6dmO2hs/VcNVS65V+nqQvXLqrI/IjGsJdDgiUG/4ZnVx9ktt8AcHnK7NWhsdia35UjPtfu8K8EaGSgWJLWQoXaimXS/oRGnX6RULX0FCq2AblZfSjV7oChxvHC02fTdhCirNZe+kRZZC2rlZ/qM/wBln++n+un+glL+ZFimr57xsUQq7TqpdU2lwg+gLj9bJh06ycA5OzU9ajDrY6g2g7sv7qnF7HQ2+g7r6aMK69Yrbn3X6LqmACqrI6V0j0AEGkTIjEQkqLVd1fE09/tAuiBRbuL5ofBrJ8VzPufaR5YTml36ZlDQd5rs6kU2vwqdPdFiBNRiJHwuHNwtcI/b0JWrlRz5Nu+sZKU2rlfE1nxHP0KAO0Ovc2ixoMrx5W/c+tAwWxMUkQi2bVW1y1vnMcvlek+xe0OWDWfAcEd59o90KV3VmtaF2q4CAchluV4O/j0+FRinQRiMUdDZbMQMotwRBzZK7T4d+YS1ZoQwnUjEY2uSHAxoXLvVW0dPrS9D6ONbiXVbWsAXanwozodF0X3NpQS80w6eCvSRNIjYks8FQdnc6aiEEEngEet5PEZBOQ7vofdlwVNW5V1Vd11Yy73HWNNJ7DQ+lh1Wb7jrWsGql0mXShz4/cfZNELmvEaSniBh3+0GHeCdkwqABqrBQufHcz7n2TWz7f2M1S6cQcnQBj1tToxcV7NffD2jgQesKrXSa9nDfWTXyjY4AwYBwG30ms+I5+kAiJokQ12dT5N4LVF00PPj6SU3c+z4N8H0mXyaQ5ZvmXzMEZ8nqiBCgQHRFuAxljSpos9jrox9DNBpN9YkwD5mO2zNTRKHSVIGK1Du6svw0Phn/CLCA8OHUSccyNmMghFNQuYCkG0mpdWeJEZSEyGaG7vPlOfHE4q25udTUmJLlhu9qaLtMTLP8lP8lP8ABQ/q0CBzrM3QGOYcKqbOL2d+sYsqrKddF/E6y/qLaIUBCr1Y7/r5/tYf2uCASoLWWkzOVpfjF9JTP4RbGe0Z6BRIy1vpBZtG+YW0g2rhiD2anKIshRa4YkFpwo4dnaNm3LPhuZ8LpNbPs/YzU+CKyHhW4/Z5ICQS7ChNK5K7RvYrO3qXf6zWfKc/XflXPWP2NgFi9pUWzxI2erT5xGhPg+k+d0hywawV2/sRn2/3TS/OvBUUCVSYtrwAUViAXA0zHRW7jCTWpiclaxWxiBGvEBrAmepUKGUTc9DWqcPgYR0Iuxp0XKGIqaoOGuvgCgBV0ItSDxKePEZfy8korpXA5Kqvagi86aeCuJ8pz9Fo+31G4XsbjsxZlaUkFgzXc5ij831h8T958/8Az4XrDqkI22r090fgnvGzdbUDYBys8gEAtB0ILZoCha9WW+cgrOvp9GRdfti2nWbBf3Jkcp1E6yNZbhMj7sYLaUEb2hO//CWgzqr9CGp3jnOqHJPjuZ8LpN8Hp+5N0fC5VbofZHfePb612BD3Dmr3mBlHcq8XX8BCFr9GOviS/m7eBfLdJ87pDlAl7RsD8MAXdyiVR0IvomMA4TF5s+R48AZj6WkEkGM60Gp1dCEyzmgHlv1jrUUe17W7kIV3UaPnHRjPiIjT9L7hQ+kbFDfg9YBRqJkY645YLTG3Qjd01FoxgVENw4A6xDvRmnKGG6n8xj4WcE0LlYbxjhH4mQRg3xf0fK8fUNPj7pT4gkQNiYRjkqAKvZ9H3uV8LZm74jN1wHMCcVZGJ4YVsHGEwx2+R9p7n2Jl3ILkogyT47nwzfPt/cmpjGM+2+yZ989o/UPkbx/k6yjuCi82RPoBQAq6BDrfMf1CMNLJnd4kJ8/p4B8t0nwukGWU2sKlbN5z2riLKi5QURrE60dDKIlTuu+8C2mgJgLOO8ZKCLFi1ADVbELYwtpa2erAKsJZsMrAaC2ToweRFU3EVva9pf8AMq6p+CEbqFfDhh6CFsY5JT/UT1LzTU07leOVFigF0/aNzPEXnKvW/mApkzz/AHENralFZ7srB3KhkLy09Tg3cxyzriqD2wJTWhXTRq62hJhjbV5/rC54QK1XeQ117w8CLYOLasL7xRbLUsLtSK6MsF2V9AU0awnr4pgVQGqyk0TEk+QEs3LxLPsBPeoNFkTDe6wyXVWqZ6sRNvh9t7XiEwXounFzh8HDN/FaYdqlM2XZ5xBGFoyAt13g1JgoF6kNTWoOgLV8VDivuzgFI83cDQ1K6XBAET0Ip2LNAHkzLVQHP+o6sXb+04wfu8I1z7f3pqYxjPsPslc0Lit4OsBe+rt4hBLRCLPShcrHuxwUahtequkUqNCsM7hFxrKmwEs6niUFuQ9vvKsDqFRvV6NtplFDQGWUB1LgIjFWNNNmOp4E+d08E+X6TDF8EJu+v7gF5+4/uZimo9HhjAnw2iNYyF8jAtrpeIOxrZnI65Osz1lA7mH3cQmkIUFt2ekRS/g1/MRWYda0P2gEWlA51osa6SmlDD5kLqGeYFoPmg7ilJTON4IQrCS9qFdDwytgT1jot5ZZQtLzakuVZF6DFMneawLQHXoIT50uMM0PuxjUuA04nlFswQDij8pm8ppJDkqWvoxmjRQcNO/MrSNHgeeqPNqCOEzFXW+udGQgCyyrL0esRurmFdqmhywoAQssF6hoIUpNoyPpMRvtQN9ATULZ0xyRCJPgeHiGelzsAuWmE0je5VKcmqxV8PDN/E4V4HYXFLwlYQWss3VTqoUX+EQ/pJfIl/qiA6SlIwWAXK0ay4N41M+396amMYPzRtvmBqFtnhSISdsvhVzTVl7Wq0vNMwz7t9N5YEvpR3M2faELIKZcsP7mDaApVwMohjaES2+u0G+N/hdesbdGlEpEhdQFfAOtBx53MtAIMrSUqUVPW0hA7EnUYtwhCAjGfE9J8zpBrN0+e4xj4XMxQJff9xPaBVwYt3bY7TMBrkYFsBRHUSKc0mI1qyrnu9ZiOqqzmBr8RhGPNMPkZjq+Hw3MQQFZ/S0+0XyN0N/A0jkD3jMxdqRq6vfrHKX9nLrDWznZKYFqAcvT3xquH3EcUrSNOCiYS32AISoF49p8L9pZC/vK3TSpCzGEozKbaNpsW2fL/bw+G8pBbiupouuYr4YDdZXON3zuX2IkZCurMgGFqlANIzMAQHO35iVzm/s7MFdsfZ4MYRwlCi9C3ME8JmlRqzoz5PmfB9Zv4IgDMISn8sDwNqe8vvDGkIKzhqV03ZW1eAk9bJpNALDg6PaaDvUx5nMEXDR8NYDZ/mTK0XjflActlN84YmqL44FLmiqB4zCBI0XQluG4rgzV6n6RIYwcRSxbGBZQRFlaNQeSxhEw8x6uF07A/mUWN+hyn4h2jrXVvxEJgjrrbXn8RhUvEbVUPZswoNhrHstfZNysnN/vGNA+yUWPRlUIw+xmKItQG7LMMZtOFgZ8pqkHUd4ord0HwtDsWsYBVUvnKY12vzCx+IrVBnpdWiqD5kXDobPVPxGBtr+iVxO32m6DWD5+2JEhOZKhzDmmH+6vNWvIi7ZyHDY8iPiX+94/X7Y9kwtA8V7vXEN6g/OPWVPn24A0gg85qeBrCsBAYa8T5znBZfK0txwQ1VoAioI++jXt9zLuHKpyqxWnwv4OBPB3CfRj1LYoKrDebziKhgp0F3+Y4zremt5YyNFpRVPRPkH4nxD8eC3yr8T4N+IgnB1EKtovtB6/UhAh0RgwoFZdCMuWhLTICKZUY7zneODc+NYKCYgtOyNujBz93tQrc1OkGoLbxh7RZT6UjFU3qLs9EbX28AUtK+9ACRMCKzZH+ZgxgEhItpQ5ZmIGXqhixTuwWxe3SJxji3fZimPQfqMgbByq02lSK5SxcDfqlRlVKHINLTSKrOdbfuZQt4INDRs3jTRVQbdRhOgrufeOSMqNmsF7MFwhDiNmndibEbCDdYqM7qMl4B1iBEJFCFzlGobFxKC6t0SXFTRlTB3vWOMAmOc1SNdO0Y7PsHNqjQ+IMHfUgc1ZpKFgIjDAJnSbxtmCwV4VIyHfvECYLqFurTvFXIARjTjSAWWEvZKxBv5uso4KuRzr0lEposAqo9Q1nYUqkAa7goUpU5nQsccECCIXY98aSj5bGcKGsSC6q7lWNKgG6BsjBh3gXdkSujy0iXzjR1NC4qXvbAGLpjOZmyjDISmdNpta6+XLBHgAaYdN2YmLIApLCWwAph/qDK/QfqK6jpOPSL/T/qF/1YKgRzs87YgNdhZu1xHCXIWDRu3umOyUwNot7e2N3bpH+qxZ0WYC+riDgi2K6U6TADZDqE8oSsQ860MdcwrRWlml0Y9JVtYW5a6wLebl+4bTYCwCw4uVSas7KKjmNpOrQ5B9Y1NHxQz6owc9d2uhXLoRW5xoatAxFL+1gDlDThJOYUadj0gxCBcHceIe7DEVdTXDPjP1Dd9PD9fqYXlhFBDlOoP1OwPv4jrBTpDKxQwKhohjyavWK62v4vh8DzFruTIXAA8hLtNh/DN7v6Q6+SGkABV0D8T7L3o6z4/mfL8+DUpnG6AOa6XBnw7psyWJ3jMq3LyZYES3dRYNZhqEwBDDQVbhsgemZet85eXeXrgb/tEVjRdX3IgKuRyO8u7U2RdkGEp0DauLK16yrCpHQWG8pVw0ThOyWIHjNN6ukAK52OlwtHHEC1YzNaOitqDjrMQNoMWgOcS3XRXzSxaqgEGwZIXhcA707S4WUnulfiJvs5ebAiLBr1SAUcW/MwytUQclEzHiv0J8z1hEdmyHXrhH2gcKoPe1qVLFdroIB6ygDT2DKP64ABoEes+d4QwYki048/LE5NoNl35u7Eby4hrUNCFPwAOjriHRRKdaWmcwydlDpN1k2lCjJlVe6eUux52GtNV9ow1novqwbaVFW+VYuFoW8bp6Kv8AaEEHL/f8CLZszg08ks+dmfI84xxnPzoAe0Xlfgm8/wCEQKwF6lH5guZQ9c6+czDo95q7p85yxNyGBlc4NJGiCN8ZmJ4S6W2D7xmgDWAYHk4iFMaLQgOBa+RCKJBZVyxgc94wMp+wB+IzR/okRGn6EqwGw8gZRAbUL5bnx/8AMr0B7nuwdlHzPcmqrRRa2mNIfAGqgy0KONWFBuewtANu9woRzoB0d6nzL8R/EbateQjvjolYnpCJo0YNnSX1pkwBo9IjgMs0qhlnhjvLXmjTq31gZKahDq6zT3Gq5vwjTC3DrhVh1M55j/chZslgvQp14Q/bVgotLS6mea415d4gYBsLuHLD+hL9F2I2jE+W/wBmIyL09ll/b909GSzpibq2EPalPaLgW5QcPSE2jTNFo69iOzKCagK1JhiRNF6v7mmmzzIMmm/MPRHqgEzzDQLWsuFvUQW1QbR8DaMyijKuqHWIS9MDUqHvLeyWLK7MM6kF9Y3HsgqOA94qzQB6x+5jokqpTDU1rrHkcXokBE0Drlq4y1TTo6NrEYaj8ID2l0+cIlk8ZQz0SOf5CaBlYu7Fwl6kzaqxG31hcv2hn7FuNG8wI9QIGl15esS21tvmET/sMtXFndLxBGgC8OOvWUyt73TcEqCZtJuRq4OqxOo4Y+PC0CvhyRrnSlyDVTUS+hmmgOIO/miMh0rZw86IshSPT4OrGXAfmwhg7e6Kje8sb5XFv5OUZvFU1K+OJjzcdennKLQldh0XqOGLZNnLL0MOW/zBqBbV1csGoYwoQWTolgKG6pCrV+0xR3icl6l8u8t6zW66f0ggAihRMF63KhMt8yQxe8EeYqOXtaV7S+AUAXjbtmNW9j6GlVKI9mO0xi00wOPVi5L0YTCwoecP0SnI10Td0NuYNvCU+perGJlfevZjr5z5/mYdJRV8jCWa9pFtQnVv5aygCulaG/11jYO72h+NuxL9n3ohAJpvZm8NSaHo/dH5VtEFFpBuuIl1Bkahu/Edzaewy15npHujUuJVWUf1D1vHTRUxTcoA3oY+0EKj2D0lxlrqyud2fE7TTMVFscXUVibpU4fEvLicKd5kr6xS1zC8WqmdauX5whVW4j65r2cYx2A9gaftA5fTYNJWkLEAC7wTlhW6POJRdVuKCM99sVVaTGV20mSyKxwxLiEclMQVwJrm18/FogUG6GTr5y9M3SsnUlQO416wpyCEVGpjRvjMeNtROtoEFc4Y9I2plcYPrhvylcVrNakNih69dFmopFJHcrrVRttCXACrASJq1TU1BGPINrR6y4zsHs8h+ZUTepX7xDrsQKOroQ2VJ+6U7ruwzLe9HHVMpg0B6NtxKsH5W6MNSffoq+RlGHMUILYdAtez3QFoHoLunqRjQjaefsrjKpAFhnbllCS2NtQWq/BCu1ltd2VFEbCGygN2/KGQCYD0SvoackrcKuKCukA1wSQoxi9XMe8/DUH3nx38z59+YJ8X7xwmoDaHA2YnHmn7xdjwwANVrEN1c0q88HTecGjGMMC8HBFvv4Xgs+8e0dWfPczLuIvTMalpcWq8Q7jmHVNT8MvgTA7OkYfxthgF2/4sdYaneCgmVn44hbrYuj/SOYUr4O/nrLZ88xzFfBzH8DaFI5piTL5WZ8vtFlmIc+8ilhix8NH8H2EhDlmg2a8n1ijZFVt1+m2qvEth5yNiNJ2YKKXrq2xL5PWARSPgeJ4sZ8t0j+HieeoVte8tlOjgcNTSBepZvaVBVLlWBbgxG6r2SMs/JxJoBq6va58Dq8DUn3qL5W6ZqK0RVYODKIcOepFN9qBO15ia2sTUJtqMAq+UADOAISjnV74t/wAnxpRvuROzKfQ7uQpQTiAG/wADiENTVPNmOrGfg0xRegdosWX+KK/n1Qcwqt5UEy7r2jqw3CtXHSAxk2rq41aSut4qB73m/uXSm83+0eXFJbrUlFgaegWnmiG6yQbtYA8tReBtai0EuIb4y4XRe0jkSzqZJV43Zja1oA3VUNQJo1p9zQgqvi2E9IuvYX1S4BJK+h7o/mbeCNZjyT57mfP7R5Z9v7k3RjMAtHIbvKKhGLrv6wLUFvVv43lW8QZ7CfygrRlYCM3Gt78O8ri2t2dXWXqRqpZ5kIa5hZ57RQ0whrQdCfLdI/Ue3gKEk3UHPqQ/F2gmmH+iQj+hvDopJ0bwIirBDBpz1jObKR5gws4Ov72ioNIa8DYN65MMYdSgwt03irRko+U++T4HlCOC6QKR1bgOryYfVddUMC5sPqxCiHG9F/V4dd6T/Mm7u3LoM6DOs9J/nRDUT6LZTT/hJRl1mct/7GK3p/Jl35dEWMFFQTNnOvh949o6sCEYqK2CZGLKtnaf48UYUQmbWz2h/XROnKta5g7Wg4l182p1ittm2gbPM3isGqmItAbDlFd/oR7UMzZZbwo/MTgJZbpr5Nom1DHEaEsJVVz+UwVJleac5mSjZlFUD2bxH8HZilVmLJF87efee0mpn2HuR3iiycjT+5pPvLyNoqlW138SkJyEvLnrKV8guvfv21j5QORwn8Vagc4Tsbr0IitGh1Pw7xVbW18GbUfZQrKDqOsGS65b7mnZ9Y7aGzCU6U+S6T7l7R5RehlXwcIxaUsevR+VXLRcrcWWxup/mn3H3n3afO8vG060F+ZqiqBxpPs0qOywo6a5+TDRelFtnpLLo8gVYZAzc8PYq9n5dJ8P6I4DSHR8p/aswOpv9C+FNtpUVXWBnKCiz1Sg9WaXVjFzo0MCgOGaAmrULx3gZZopQcHHh9w+6OrBEEDr1lvMt5lRnrSWwBmI5QiI0iaMSXlbqnwSV4G7YLuxgNuBvOxL1lhFRSQDQodDydWA0DWw6Hk36x7LZ+0WMWLrIzXimpFdI/n7Ph/qmoiXOOXXXife+0mtFaQXawFjVrMhCRBQu0ZtXElfSSpxRau07nRiKCOtf0HfT67j1q7AcrsRMVgfDq+0OLQUbAcAaH11Bo0HXubRvilFRADW+jpDjPluk+N0jyj9DF8rZLizYZcXf0ioscxChbK4eqOg3RUQuaX959+iNQlmXG0mTrFV1H6A+Zu8Fvio5ZUw62nZqzKEgKVfQDVdD+oO2tZNUm16srxKynEpxES8ZZbtwejoxy6yMImEfpNtwvamHZZyWbz6/R917kdXxt19SiI1DmrzGjqfHSK/pS/9SOHspQ3QJwGrxppvDwNIsJ5HdE3TFFoX1MMcX1lXvN9FKCoc6CVsIbEc9S8y4mRr2qWLAuXABtobVg5dppqagoNlbB3TPh8/wz7xMcjW7q9g1hoVdertxMw/BllDS3oUQVguBo82VI4GgwHlFlyVpnjOjoxSf0PoNRiSvqMtDRGmbdwTN0GncioYnIZDkTXxBUAtZqytTWd/2lNnrXVbvf66l84nCHdZhAOMw7mvdlixTdusQEVwGfM3iGGC0aZqFYcvaXLH6CL52yX4CpYQ+hTDTwSV5k0lmAZNR1ttYqOqL5s++QlX6ARnRlMKvif7sP8ARgF++BCRt1Fqs2ZbtQ7jUYNIU5EI9zd/olOteo/UZ+gtlSkqx6Xk36z5Ph9G7fHpjmYq0BDW9GWWCu7Kq8vosiG7E6nU2+n53VHV8ATVRpznTkWxACCiuQtA67ru+ALoM6j0nQYtTlF6QWBPCx6OIDTzmz2hicoNegxMbeJQLyfgi+NsgqMFogWha0ywP9bP8Nn+4h13iFrQG/eMQLXJWZphNK1eA5XY6zFBDlg99/aDmAVuHl8wa7qfFmKXkJqMYvEs3VVjc4eSYKnP7h/iYm7yOonImp/AdTyhX6epEPU2fNvG+zNAeWtxDZe+t7fp6xVbdX6qjFIFZqq6NU0xeM6p75X6GZUpB0FDsfmbRMZiZdLZy9m8UUELQynXgh7bUqwuzWZTjhyGQ5E1jgvnbIpxtMGV1heCsS43RTtBby/BzTOH2toyXV95z4bk+6QCgm9xvKip1vBtX0k7LFuj28+/SUMEMVsb/qCAMBU5f2IMX22dZtnz/D+AGK0nLKcSarf+EX2vfm7LYgCw2WU4IQpbq6pr1mvIx4AtYAOrEUG0kB1curmf6bG0iAaReMrgOsd/V2YWmlaXCk0B8EpvLMzBniAGlzOpLcy3MtzCQVYBlZ3gF5qfUx589JSKDY1U3XVe+SPRGV03SaJB0uiN/wC0e13nGHiTcuNFf6HoxLYmGqzcPqK5ynlw9pgCN2FfjtmKUKSV9Ta0gjLiau1vX6wjpNci59w9opWspWe67diWUtdLa0F+0drEPbhNY6l2gQV3sTs6sODTijL2bR2jypaxEtwKml0Vry56mY9r5/D9ryYjCtdjAgo0j0is1pLl/U0y4cgNaGV6EfkQtbrBon38KCUaiGXqd9Poa2SH5ehvADut15XV83TpGLI3uhseUSZFJahhe7oeu0CwIAbBNsfkdnh7fo7LL/C1kJjQCjK944pNBMtqqIMALro0b0uXPH0PHI5Vtf4CcQINoFbXlzVPlj6LBWhL/wBIuVXqAu8ekBlVx5v939u0obQGVkeeHoyjz5GfVv21lG0K02Ad10qMJmApGiV6wg+GhfabREdS7t95tAQDUK9IbibFtaEVCaK7ssQC7saHv+2YHcRxmOzwypX0+2+kI6LQLTAcq6RnQbgek37ssWJu5joxHwo0AWsNe1q6+7aaVgbt9xi54HDjtER0YvMwDRTZ0+0w9rbLPQJWKQjkA2DfoR92rgLXfSL/AI3+p/tH6l6WR0T9Q0BmjatyiWfA+0+EfifFPxL/AJX2lVmwigHZK0mlRgxDgxpPiH4nyH8T5z+J8d/EE0+T0lvgS63LTo+yGXTdbp/SNAVYDVMA6sX4TS0vYegeHbPiOzw9vjsssv8ACzHqKgJsjrLmbquvtT5DG/0fBvxPgH4gmnwOk+WfiCaN8uJ0t6+1cX9BKxBm7bPSUx1rqqr1b8S1tKCEmEnoa1/SHyX4h8F+IhMNVvzGpLiT5PVartC8z3xj2HtnpFtVGL0Ne/nNFW9zU7m008wDVhYtnOdduIPLXrU3O9D8VzYoupv5QS4ji4l/exNROEdSJ6nsubo/liW4dTc5Hc+n2Ht9B5CWgMrO0ofPn9msPYG2DQ/b1YrtHaxKcW5xjtywc5TqBTo2IVcTcwdX4JXc3ojq58O2FY/opfuHfSZHuUt2fV+DEsey1cX2vXwL/En+olK2GllQcwFN24ecw+D0YPEA2hISA8BARZB0zNjjuwLWAOwBEJtaNw4V1dunf6DQvwpNfh7Iwww/WM+/VD6m9HmtWU/t/uW+X8xExWkTkQ0yt3TFXVYHxbPsS9NYOxq/T7FchXo3Tyd40tAHkmIGytwNNOV8b+jvsPQr56doa9qL01h56+NhnuHD0i1a5/h+EN2LUeeokAsGqAx+G+YIZ1RlOzw9GVgDlNfc2hLdrOdGjatbm+RwEBsTCMBK6YdJ15jrIzfP2GNUWcOewxrYijpKP/S+q2YiYQt+QOpFDSSvDU7HtKgQ2P8Axg1WWKwlL7mzoR10jKYioxsH3YeVi1q7jf2jzFNGuwmTgSLYxRKrFmK8u8WxAWUWq0ByrgJTxHY9Y17vpFCuoLlgkKNoaX8vtMwdB0CGara9JbzLeZbmEqm2rs7PlGo2P6JEW0j67eaX+CnFoctfBm3mB/rzwejn+lp/pyT+jwf0CD+uQCdYbNsZs5A55gQAMSvBU+A7YYVlaTDcvUdnxHxBChoL6Qp11otytT0VW0C+H9oF+ZveA+SKHcrUGNNv4b8Qg4DdehvBz0176iuq+J2Ts8LPF3AND3H1lforOn9yunOwYwYD30mrarxodDoeJCD1Da6XlwygOFqBM9CVT0R1VbI4SO7H3Obovux1lhdGdDXddeY0tdDOqTR/EUYuMxwJal+Qm8Biat6d3RggJM2e7eJqakKSWGIiIg0SJiptP7Pu1ggKdFtd+HoyoPte0yN7roByroQ6EW49I/LEeJbd44OCNsjNYhZVc5MXQ284tqvOVvO1HbnG1QrnnzgVVcHkH7iscrcbrrfm8+UVYMrHxe2iZ93+oIHR9wFdXq5jRwS0RocVMCDdDV7u8WP0mq1idXQPlpFpb3ct+5tGIBkNxjAtbL5W7SmABQeD0YPg9CEEEBKgSoENygScNJXaWlqqCGOhpKlSpXgMph/DsFfqPsbfyIlfGpnXPPVGDoh4Pb4zgCJSO9w8ZsfWuV2nX+k670nWektwwFQBubgWuu/DyjHXJG/Hy0+gilaTzcFUbNKuul68O8ECG00np0ejF5i1yHPbtpDiOUxSxQLQ2dG4E68RGZQ0s08m7odW0pwBox2fJLatoM9jbvEyhENo/oXhRYcI6wZYd0bV5lpFYdZ5NcrA9XpBiBxjO7uvVlkXZBQ1XYedApEY5+OaZi6PA77eUZMqt+rNdafVv953EHY0PzBEalgGhFhHdo1V4JbM5ajtw7Z6x2DBnRHdmHyBbs1uXEKKwG12yxfWYKWaJuOEh5VlZyMHIDUHnRum0vJrdW1eV3frQACBAgSpUrwNgIvQHzjdtpAKAGuMa/wW6QvlX4nyr8Sr9mf6ef6Gf7Gf6X9TKCV+txpEtT7uCwFEMGzlqbsKgeA+kD0RgkpBOHMFk9AmG2jbpP6VP6FGWYaAs3fpHa9bbPV5PeLbb9JBl5aOqsOqydxAnVNk/Y7MLovaliRYPigzGxadz0gDFcg2HKMMWdJ6PtGN41prRSQBtwBh2b+UY5a6r9TZidu06hyO8U2htozo/wAIqmIl8KAtY2IAujg7/wASi/aAV261jBDuunQNiJYuCu6VXRuZpqVToZWNL3QGwfgIETSlUdTlNXbHWZ600DQGwGA6EXFHM6ex2lQUHhDy/MJDjWXRfr7hvzebaLzR2tk3HokvtHHR3HqPiBAmH69TVS0xuZ1hAQIECV4pnUCO5ofZcGYPceDt/hvywCRbrHeC5Zflg+YLmA8sp5YBmZ+zb+IHJlnXwkEH0Ow+ILeQeGBJJGgGWMFptBcaS/dgGNAPob91y/wXLly4aYACZpuwdSLiUyngl9Q8jsvk6nrFl1pqYvk1vhzKGEDEdqYcYpaCtC1xwRCpcMwa59zuEwICDXfsMEc6t9J05iAaBpEpI207HtLjsOhqdG8WseyFdxwTpj7Ye7vEbqKusqCu1g7Wbd5cPgOiW+yShUdK9RvocZYxK+9fc6vtAG7s1i1hap20r3dJcvxFi/WiFI2PaVHDUDY1O25BeveT6Hxr4BAiQJAYLiCgfQocs1ci16R93EXoWucrXqM+W4fws3Q8/I5XiGsAOmCnUED5z/TRX93Ff3cVNHgCCEVKrVYFUbtwggk8M+j2GWStAFVaAN2ZCdKdl7G0Uiq3q2VQ8iJtmUeS+kTcgrkwjEckf6HqfyI20eno/AQLY1cRqwzAANgjs9KWwN61MMm06P2RgGyNMCka0uA6V2gq63b1WPzN4mlbiFsQ0TB1fhig1eWnYNyatJiKfyYKNJVzI6NovVG1LVjtqxVREzJ0dfN2lXZKEcBzf5TKwikdMYumuusRnLbmWebgcEKrLzCW1Er0PmIrUo04A0JcuXLly/4MpVivlsx5HoyTT2mmBonRiPgfeHzT3hJiNnjq2XV4xs9/s5dRBoUaF8Gx4fBcP4VLDlyntcuxt9NkkngEkn1QVKjFwAAquACXQBbTGOgccHmxx8ftGUUBxtDEYWtvxp0YikSk1PrvxA1uOAaxLShjgBgJRuaOhx+UEsx4fCz1uJREEcI5uXgHL1duIxOtn8c+FTvFEzFRJYlJDi+ALYOwYiLzFd5QNqh52Dd6EUN4XG5/rsSsg1q5Ou6pWaTQx2CXYdkdHyu/xK9G0rbq/Ea+rBXoD3iIo6+N/wAZlWrQdWE9I5A3pV+dRc06QRw7kEECBD+HaCBaZdHHCfwtvrQPCJPACVKlSpUSUBVoNWISKDZd5u9hvrH6IYW0EbjFxa3rnp5mjBQ5t5mz5xNFprRERRM/wDiU6Jt+TKm9mzo7PSUlELbSh8KK32mp3I+VKNi6MYTXxEARs7nZmberg9Y38oo0xSUVmODfHtEtNFIrA2V50PLmY6pAZtUxwRi0ZrJ8qmFaTKP2hMEVWKLPmhFEEtVAOBt3idFhOElRt1HXbzfzXXSb0Td/Ea2ORusEkuzk9WBBAgfQC2lk3BDgv/iBB4B4FSvqFpNF6Ez56QUNOm/CZPAI2YprDWCOCorhS4R2cb9pUYfoE5uQeZN4qQ1Vb1+zWUFMtC+BID1WAqvrtAvNTuaebfpBSfUVglYFvlawg8LUQUHMqR69YisJuTb+3vFjkjLIiF+1q9G/eYmh0ch0YISJr4p9oDc4cYaG2ne4gUahrXV37aQAAAoAoIUZ8reEUhNALYaWWCF1ORrpoSl0AoDAHQNIkxuEJ9oB9Fp6c+U2QtHkdHz/AJKdNAU4GrL6lGg4DQl5rwnY0/CQ0QQIE0FqIF9WNcGtUupqeK0L2MgKDw1/OfQFSv4aFowrqpA0XGLiphtRPmxgb2unt1OkXBAxRLDRyOYy0rkAl6FjrCABtsFB4JBE8QDSLhbK1pvHnrEK3BfVqTy1PrBBU0BusAbeqN3V7GhE5mweN/whBBBOV884RQAV20Hfkj3R5Z58R6IiPiZkLIoJhvZ8z7My5C1RfsbQMW8/cXfw9sc/Z7xaWHS/sPzpEF2wuvcfxD4DmMsipbOwze+YeTZmlwev9fb+R4e10TU/JhWIm+B1f1BKgk2AqCCBAh7ec6lEDYzmNMkUI0lB3cf8VfzMovOXpALjFZce39JiQeJEfk23DInaBeqHpo9mZC1uFJ5T5YnZ6iXx9ZL/ALh+ouz1T9SzXJQhq1qt4GbVj4Mr6QygwGwQ6IeAR8b3+PgiffvNAri3duJckPg7ZXw9spWllXAHKwTZKNZh2HXuy6RVqsZ+Ic+F8CuXjbWu6eUYkyOnJxBLQbenHl/EBHeeuWx82iYuUvuswJAWa7MCCCBDwAAANjH/AIAvXrapVfD2Y5sNBUF6B3faL1y2R57uhE1ASCrXAaGPqSJB4hiRwqzteTJAb5IN0KG+FG6HUQrzh1snQ0RWAbBb5zshJB4Hxvf9PVDoJ1O7aGGk32O5BI5NTIt2q4XwEPHTgau/ENEFppf2+FllJesZVq26BxeYw+Av7UcQw4NC9fJ7TIPgWef8JoKmg5WXDGy08x7bEbN6LtOU6wdDGBcMCCBKgCpMACzTVbT+/wCBgL6SdA/f/WnxQQB2R1hVgUAoA2D+BIn0h3R8F8Ptnb4h9A2fBz8L4b4YIiKJoyqVVf1I41k3iCaRfktfLiKW3PjtS3BB0h6Dyb99JkMq1WrGHwGJgjD2ZHZiJEaJ2RJSlrGfMUOGC/v/AEn+2/qf6j9T/Xfqf7L+p/sv1P8AZfqXBWwL+ZUPKMXPJqq1ACElHd1exoS2G2fZNzpNHSXngG7ue0ED+IUayKlO405Gsj/4jEifSAMv8Oj1y75GXjPj2au194gFUFX0QUAVyan9HVgwQysGjvy7+OyyxiYt58SEdKYv9JlOvqJ/pJ/tJ/up/pp/soPp6iGoXZ/qf7/9REWBApDhZy6ErPAMgirauUtmOqDURXReOnfaH8xn+vdOlUoal2P/AILEiR8Ayy/xegLXjg/QnpX3l3dRm6QA1WGBfkGfY6d30lSqvK6q8q6/R3wWcTLmr/NE8RfX0U/z0/wCH9cQ/rof10P6InAekPBmh4AgQjpsjFBbNM5vp+H1QR3+plK9aChWxRnGn1mOQlSDmg4L38FAV0C5gmu6qeSif96RIkYYYYf4cAbX0kHZ4PSnvLu8y1IrgqL1QYglS0xXYfnX6Q7PEZzu0t+JhGHxJ0w+sKAEPBEAopHIjKSO6nJc8DzG3ED4tosT/wA+okSPgMP1APgaoPrwA9AS7u/xgBkdpZ8DDxuydng7IQSeEICB9DB3NrDSb7P2XeXVaFQULUHRP/EbpotrETYKcg0Ho0X/ABJKiSpXiVH6QK1aPOwFaiG1LC1i/oFeJ62Q+v4lSvrAwPaZr5U+onZCCCCAlfWoMIFugbBqcOpMHabq247rZII5H+VCjWFbpS8b6f8AhVKlSpUqICqAFq7TvJaHRaLtK8FSo2ypUqVK8B9SepSpUqVKlfSGB7RqgjnGzRD6gSCDWXg1TKz5Vr1gfxMfwD3qDqAUgNm1QCwC13/6ltCo5YKPReNdf+epUqJMCr3FYUvfXTSPmBsRpE3JiyTYtLG+uusqVKiSpUqVK8Az3Q5SpUqVK+oBAQwV9IHiKlf+lea/mqXrFoxqNDGOsqBO1po+3gqVKlSpUqVKgZIMpUqVKlSpUqVKlSpUqVKlf9FbyYV0GozvVTS0+AQAWt8/9hds2dVQHLH/AAKFgY/QmTtpC/WntC0A6mvSChWzq8rVerKlSpUqVKlSpUrSJmVKlSpUqVKlSpUqV/2YRtLembI184IN8Ojv1ev/AKNSpUqVKlSohYIAbroXtM+HGLo6GaM4lSpUqVKlSpUrwZy8GGF9K9uf/WCChRpq6eYH2oq280wf+Aa06BYxva9oKt5ef/hnLJNUUBrmyZvT6LLrf/1sZjeS+Lz9v/4xv//Z"


_CAPA_BOT_FIXA_B64 = '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'
_CAPA_SURF_FIXA_B64 = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBAUEBAYFBQUGBgYHCQ4JCQgICRINDQoOFRIWFhUSFBQXGiEcFxgfGRQUHScdHyIjJSUlFhwpLCgkKyEkJST/2wBDAQYGBgkICREJCREkGBQYJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCT/wAARCAJXBQADASIAAhEBAxEB/8QAHQAAAQUBAQEBAAAAAAAAAAAAAgABAwQFBgcICf/EAFAQAAEDAgQDBgIHBQcCAwYFBQEAAgMEEQUSITEGQVEHEyJhcYEykRQjQlKhscEIFWJy0RYkM0OCkuFT8DSiskRjc8LS8RclRVSEkyY1g6P/xAAbAQEAAwEBAQEAAAAAAAAAAAAAAQIDBAUGB//EAD0RAAIBAwICBgkEAQMEAgMAAAABAgMEESExEkEFE1FhcfAiMoGRobHB0eEGFCNCMyRi8RVEUqKSwkOC4v/aAAwDAQACEQMRAD8A+VUkkkAk6ZJAOkklyQCumTpt0Akk6SAVkyeyVlAGSCfKnsgGST2SspAySeyeygApJ7JWQA7pIrJWQApWRWSsgGTblO7omspAkgLpIgLBAKyZPZKygCST2SsgGQpyboVIEnSSQCXU9n3Cx4kxkGZrvoVLaSc8ndGe/wCQK5qngkqZmQxMc+SRwaxrdyTsF9BcJcOx8NYLDQtsZj453j7ch39hsPReX0redRSxH1nt9zxem+kP2tHhg/Slt9WbGwAFgBsByXn3avxOKGibg9PJaoqhmmIOrI+nv+Q8122MYnT4LhtRiFS60UDC4jm48gPMnRfPGL4pUY1iM9fUuzSzuLiOTRyA8gNF4vQ9n1tTrJbR+Z890BYdfW66Xqx+L/G/uKe6cBIBPZfWn3YkyeyRCkDFMnSQDJk6ZAPyTjdMER0F0A9gfNLL5ILJwFAHva9kIRgaIXCxQDJJWTgXUgduyLL6J2jmdgojcm6gEmXzHzTDQgoMpUjNiEBGb3N0kTxzTeakDImbprKSOO5DeqAdrC7QWHqbJzC4aks/3BBJ4nXGw0HogJJ3UAksORB9EMhJdcjS2iUJAdY7FG9uhHMICFJENQmcLKQMBco7XTNFhdPJpZvuUAXduHT5hMRbe3zUZSBsboA3E92ANr3KjU1htyKiIsbIBkk4F0UbMx8ggCaC6w3KnbRSuFxkt/O3+qVhBA6U/E7ws/Uqpc8rqAXHUUjG5jkt1zhRi7QbDUjQ9FXJPUq5Ce8jB5jQoCEQ3CcwKa2R3kU7nBAVXxZULCRforEnjOVqZkGtjoBqSpAzIJJdWMc70RGjnG8Th7Ku6Ql5c246Ji9zt3E+6AmLC02cPZQuJLiTupIXbtPshmbrcIAEkrJIAozY26oyzNulHHpcjUojJ3MmWzTbe4ugA7n1SEeUqx37XD4GfJRg94XaAdLICGQ/ZCFHKNboEAkmmxSRxtvqfZALKDukGN6lO4ho2BKHvD90ICS7GN8O/VRvNzbknYc7rEeiT239lAASSAKfKVIHAubJiS0mykaNFG7VxsgHzu6pXzbpspKcMI1sgGcEKkIQ2ugGTgJWsnQCJ0Q3KROqSAcHVJw5pBqI7IAErIg0pFpQDNCcuLSn29kG5QBd5/CE17prJAW1QCI1SRFDqgEklYp9kAkyV0kAkkkuaASSSSASSSSASSV06AZJJJAJJOmQCTpkkAkkt0kA6SZLdAOmKSSASSSVkAkrpWSQCSTImi6AQFgnT2TWUAYpk9krIBWSsnsnsgBST2SspAySdKyAbKnsnSUAayVk9krIBJJ7JWQDJrIrJIBrJJ7JIBrJ7J0rIBrJrIrJWQA2SsnslZAKyR0F0QHJRvIcbDYIAd9Uk6YDMVIHYOaOycCwSsoA1krJ7J7IAbJnGwRaAKMkkoBvVJJOApArJWTgLU4bwKfiLF6fDoNO8N3vtoxg3cqTmoRcpbIpUqRpxc5PCR23ZLwt3srsfqmXZGSymDhu7m/22HnfovU7EKOhoIMNo4aOmYGQwsDGN6ALB494nHDGCPkicBWVF4qcdDbV3t+dl8VXqzvbjTnovDzufnFzWqdI3Xo7vRLsXnVnBdqvFX7xrxg1LJeno3XlIOj5eno3b1uuAaLlE4ukeS4lzibknclHlDQvsLehGhTVOPI+/s7aNtRjRhy85BtbRJOktzrBTFEdEKAZMnOiZSBzYpZU17FPnP8A2EA4FknnWw2Cdrr3vumcOagApJ7JyLBAJpsbHYorIWDmjLiwgt0KAbKEgAERqHnmha4l3iN7oB3uGUNHqUIbdGWX9QjY2wQEbWdUnOynRSPIAUDQXOugDIB226JBvkjP1cRfzJs39ShFVLze5AINA1ASc7Iw23Ol+gSMjnuBLiR0RuYCCOqAr3KSctsbc0WWwQEeyla4vaCd1HbM7KFZhjBOo8LRcoCLbkExF1P9LfE3LnzKJ87pN3WQDA5Tc625KIkk3O5UvIFAW2NlIBSR5ULggHab6Ig252BKUcbnuaxo8TjZSOqXQynuHFrRoCOfmgHEX8I+SJrA3S1vJRmvqT/nyfNPBK6V5D3FzjrcqAKpf38tmghjBlaCg7pWXMtr80rC10BWMdkope6dprfQp5X30CGKIkZlIJC9zzcogL7p3TPo8gjdlkcMziOQ5BM7E6k/5rvmoAbY7OuE1RIBH3bfidq4+XRRiume9vfSOe0cjyVmSMP9RqEBS7kpjGQrzIwQhkYNUBR+E+imtnb5FRlmeTKFaY3K0uLQWt+z18lIIRCOqQpwDe91bNTBl/8ABMaf5nf1UTqhriGthay53BJQDAiNjpDbTYdSqZNzc81dkjD2kW1Gyrd1cXQEYNuaNspaQULmkJkBO4h42sCou7d0U8UdgG8ypSyHLfvH+mT/AJQFPu3dFJYAeQCJ74m7OeT6JntzCwUAi+N1yiyKMaFWYxdSCIsykEaIiQ4XCkkbfS2qEtDBbkN1AGAaEjlGyj759rX/AATGRx5pgBOde9t07GADXdRjqlmcDugJwGt1TPkAChzHqUxN0A4N0+h+0EKZSA9ANwm5IUbUAIFyjDErWKck9EArWTbG6WpTO0FuqAMGIjVzh7JnOjGxcT6KO6ZAGRcJNbdJpuLJxcHRAPkTEWRXPRNqd1AGCfL5j5oXaD1QqQERbmEx2TJ+V0AKdKySAQSSCSAdMlfyCSAdMnsmQCSCSSAdMnSQCTJ0xQCSS2SCASQTpIBk9k/smUAYpJHUpKQJOU3NOgGTJ7pIBIwLaJmDmjsgBSKLZCoAySSSkB2SsntdPZQALJWR2TWQA2SsnT2QA2T2T2SsgGslZOnsgBsknToBrJrIkrIAbJ7J7JIBrJJ7JIAUkSVkA1krIgEQAALnfCN0BE85G+bvyUYCdzi9xceaZSBipI22HqhjZnPkFNZQAbJWRWStdAMlZFZM45WkoCKQ8kCcm5TKQKyIBIBEAoA4FtSva+zPhb9x4P8ATaiO1bWgOcCNY4/st99z7dFwfZxwr/aLGPpFQy9DRkPkvtI/7LP1PkF7hlXzvTV5/wBvF+P2Pkv1F0h/2sH3v6L6+4CSVkMT5ZXtZGxpc5ztmgbkr5+404mfxTjktWCRTR/VU7DyYOfqd13va3xV9Epm4DSyWlqGh9QQfhZyb7/kPNeVU8Wd11p0NZ8Eevlu9vD8mn6esFCH7qa1e3h2+35eI8UVhmKFxzG6mnNvAPdRWXuo+nj2sGyR9USB/RSWAOpSskmJspAxCcBLMOiVr6IBvNJJJAODY+ik0I9VENVMxmoF/VQAQ1IsuN1KyaC1nROJ65/+Eb5acM8ELs3m9ARRtG7jZoFyonvL3EnmpnMBHkRoq5FjYoBXT3KZJSCZr8wB5og4oY4zoANSpopqcEtkiL7HcPtdQCJ3jTxRZnNYLXJ5q4ZKHJf6O+//AMT/AIVUAOGa1gTt0UEEdRI18lmfA3wt/qot0725XEJrKSRDRTRyZm2O42UBUsTdMxQDubmdfZPZSCSKBwbLFnuLnxWsp2zUThpTH/8AqFAVGsDSSjqn90wQtOpGZ9uvROS2R7sjMgGwvdQysu7MOe6AhSUgiKRjUgZjrGx2KI6oGtudeSkJDW5iOdgEA1x1TAeK+6fvGc2H/cijdG97WhuW53vdAS/4FP3n25Ltb5Dmf0VdkLn8lekpwQ3q1Ssa1oUApNoyUnMbTkEnVWZZ8oIas9xc9+upKAtmbO3QaEIAxxFi5FTsAJLriNgzOVoYjhzWA/QXOd5zH+iApmlJ+1+Ct00DNXP0jjbmd5+XuopMSpzfu6IN9ZXFSBoe0G92uF0BTkjfM90jt3G6H6MVotYNindGAgM76ORurEcwLco1LVHVy5fA33QU8dm5uZQEzXua422TvLnjS11epYaJzS2oE5eDqY3AD8QpJGYXFras/wBzf6IDKihcL33KsujDbMH2d/VFHLBKXOjzhgNgHbqq9zmSFgJI5IA5WgA3VJ79fCppQ5wN1WIIQF2kkD2Fp1c38k7mnOQG3B10UFIwl5dcgAfNX4o4n6SSiPS4u0m/yQFOSFzvslRxQuDruFrcitF7admhqQfRhUBMbye7fnA52sgGa3IzMd3aD0QuI6qGoe8SWJvpp6KHvHdUBM5oJuN0bBmZ5j8lWzlSQveXix9UApIyX3aCb9FLE17Bq0o9B8TmtB5lCXM/6jEA+YB1zpZRzatAG7vyScWk2a4H0QkkEICItI5JrK41gI1TOjagKoSIUjmgXsgFr6m3mpANilZTBkJH+Mf9qB4YNGuJ9kAB2S3RWvsjZGgBbHdOW5QpCQAonOLigHAJ2/BP3b/un5IHOLbAEgpGV5Fi4keqALbRA+5ckw2Kkc24QEYaSjDNEmlJ7tLKAMLXsEQbmNrgepskxth5qN5ufRATGIjm35obWNrj2UWY9U7DYoBPJzJkb280IBKkDJx0TEWRDQeaAaySROqVx0KAbdJPfomQCSSTIAhsmSCcW62QCsmRhrfvJrC+9woAKSR3SKkCT8kydQBkk+ySkCSvZJMoA9ylfVMkpA5TWunB0T6IBgLlMUW2yFAMiaMxsmUjG2F+ZQD2Tgap7JHT3UAF1robIkkAySdMgJAE9k9kgNUA1k1kdki1ABZJPZKyAZKyKyVkANkrIkrIAbJWR2TWQA2T2T2SQDWTWRgJWQAWSsjslZABZPZFZKyAYAlBUO1ETTo3Vx6lTOcIY8/2jo316qoNEAtgh3NgncVJAz7R9lIJGNytATkIrJrKANZKyeyVkAyhmdc2HJSyOyN8+SrIBImhMAjA0QCsrFJSTVtTFTU7DJNM8MY0cydlG1q9Q7JuFDrxBVste7KQEezn/oPdc13cqhTdR+WcV9eRtaLqS9nidxwtgEPDWCwYfFYvaM0rx9uQ7n9B5BT8QY1TcPYRUYlUm7Ym+FvN7js0epWhZeK9qnFYxrFhhlLJmo6FxBIOkkvM+2w918pZ28ruv6Xiz4WxtJ31z6b75Pz2nIV9bU4ziM9ZVOzzzvL3npfkPIbKYNFPFfnySo6bK3M4alRVEneP0+EaBfYJLZbI/QYpaRjsiI6m51KaydOtDYBxyi5UW++6J5zOtyCFAK2iBGCL+iF5BNwpAKNpuPRAibugCLbm6RCfTmbJ2hpNs4UAFjdbqSQ93Fb7T/wCcNHIh3mopsxkJPPZAAnF04bZI6ICaI5mlvMahDJGSbhBHmLxY2tqrLGtJGd4YCbAlAVxEeidkZzajQKy6KJv/tLT6NKHwk2Y/ORqdLKBkcnuYDJ9p/hb+pVOysVAe8sJNwBlHkmERUkEQcQpoXtN2HTNt6oXMsoQC5wAQknkjLh5hD3RtspgLAlztBuUnCAa/SP/AClAV+6cXC+gVmFrRd7x9XGLkdeg90wEWmWXMT/DZKUOdCWA6A5iOqAqSPMj3Pdu43KYEt2upBESmdHZSAo5sjgSjcQ4abFVyLKZjSAGncqAEC63L5pn/Chuz74HsU5yAf4oPlYoBNbmcGjcqOVwc+zfhGgUjSbHKbFwtdQ2N1IEp4o2j4kMURJvbRFM7KLc1ALhnaWi2pG6rZ5A4gXLVFBdt3citKCkhlAElVHE+18jmkm3sgKJD3N+Ep4acglzhYrTbRUjT4q5ntG5RSNizXp5e9YD8WW2voUBDWs7iBlPs91nvHToP1WeYyFbkD31Mj5XZnuOYnqpRCHDZAZ4jJV6iPhMZO2oUcze7BNlXjc4vBudEBoSSZXNLdeqF8kjho38UdJTtlYHzzx08bjlD33sT7K1Jh0MWv7ypCPIO/ogMsUz5ZhnBDdyrTg2mjdMbeHRo6uRkwB4jjqY5nH7gI/MKCtie/Jc+Bt7DzQEcNWQ2x35lPJI143QCmJ2CY07kA0BDHm50OikmGmbmFVkY5rrfJX6aMyuaxxAO13Gw9ygI4hnF3XCgnjyusBe63HYXKway03/APXZ/VQPpsnxSwON9A2RrifkgKsMAa0MvYDVx/NC+ZjnEjToOgR1udlO4MGhIzHyWbmKAnc+530UkRaw35HdU8xT5j1Ugt1MZczbUahUlo0wc+NmbfYeasOwudv/ALI+38qAxlcgiLGgW8TlZNBI3V1MWga3IQyXjieWi7rWv081AKNRIHyWHwt0Hmo0QjJ2CkbASpBE12VwKnI58knQZQmZfIOnJASRyDKgkkvskWSAXDXW8ggLZNyCoAzjyUZNyi5G26YNUgZrS42ClbCUmtsndMQLBACRYpB5CYuLt07WPcPCNPVAMXEjYp2gc+SLuXgXOnuEIFx6qARk5jdOGEqRjBdSBoCAgMalbq3VJ7tbDdJxysv7BAStgkI8MbreTUz4XgeJhA8wqzZZG7Pd80nyOfuSUwCR5IabKEC6sNIey/sUDRlNigAyJiLKZxaBuo7Z3aIAmm7RdPsNgmccrUP0iTr+CAci/IJjoLpGZzhYpEXUgFrbostk7bAJnP6KAAdCkkSSkpAkrJ7EpEEIBckycjRIC6AZO3eyfKm2QDuCZK5KdQAU9k/NI7IBr/JLMUySkDpWSCeyAayVk6XNQBbBMHuGl0ndEykCuTzSSCQF0AUbcx8gprJMZlbZFa6gDADc7BCTck80btPD03Q2QApWTpWQA2SsislZAS2SAToggBslZHZKyAAtTEKSyYtQEdkrI7JrFANZKyKyVkANkrIrJWQA2SAT2T2QDWSRWSQA2TWRWSsgGsijZmdbYbk9Eg0nSyGrf3bO5afE7V39EBBPL30uYaNGjR5KMp9AhJQDsYZHW5K0BYWCaGLI3UandSWQA2SsiSsgBskRpfkiUNS/L4Bud0BBI/O6/LkmASRNF0A7QjASa1SNahDZq8LYBLxHjNPh8dwxxzTPH2Ixuf0HmV9C01PFS08dPBGI4YmhjGDZrRsFyvZzwr/Z/BxPUMtW1gD5L7sb9ln6nzPkurnmjpYJJ5niOKJpe9x2a0C5K+Q6Uuuvq8Mdl8z4Lpm+/c1uCHqx0Xe+bOY7ReKBwzgThC+1dV3igHNv3n+w/EheGUdOZpMxFwNz1K1eLeIZuLcelrDcQ37unjP2Ixt7nc+qUMLKSnzO2AufNe9YWv7ekk/We59L0ZZ/tKCi/Wlq/t7CCrk7qPu2/E7fyCo2UkjzI8vduUFl6EVhHrxjhDIJXZRYblSHQXPJV75nFx57KSw1raJnaBEgOpuSgGIsPVCnJuUYbfkpAGVGBbROWkcrJhc6DdQAT4nKRtmbp2tDR5oJJLmwQglY5p0uNUTmZhY7hVbqyxznMF0JBtoo3hWmQyv1DXEeQRup3sbd7CB5hCCCGI2DbXc5NUvHehjdWx6ep5lSiQxBzmi7raHp5qne6AnbYhO1zY3ZlXuRzTXKEmhlzDq06hBmtoeSCmlcIi22gOhUrWSSGzWuJUEEErgRYJoWWGY89lbNJPa5jdb0QRHI8EtDrHbkVIIqu8bWw/a+J36BVrIpJHPkc558RNz6oc3khIgSCrkb84DxvzVMkclLSvcHOAFwRqgJn+B9htuFG911Ld5GgKjIfzBQETG3cXHYKR/giL+bvCP1St1QzuzyAWs1oAaPJSCGyZS5fJC4WQBRG4tzCJzczgeuhUTL5hbdWoYJZnWiY956NF0BMAzJYaKkWmWXL5rQ+gVo3pp7fyFC6llh8UkTmX5kWUAVPTxjNJJ/hRDM7z6D3Kr946WR0jvicblTVL3Oiiga2zblzj948vkE8VPogBbmcLFSRFkJyk2DkTwImErOllL3ElAXaqO7czTq38kMFSCLEpRSd4xrXXzEW9Vp02BVr7FtDUOFuUTv6KAZlQQ9thulT4fLKWxsbd7zYBa0uC10AL5aGoY0akujIA/BCyqFLBMY2XlczK1/3L7n5JkGVXHvJmwRG8MAyNP3jzPuVF9GeRbVX4oGhosFLkATIM2KmfHIHjdpuFruiZNHf7Lx8iqFVOItOaGjqpHh7HXyDUeSkE0LgSWH4mmxRvDWDWyKGBxBdFE99zqWsJUhppz8VNJ7xH+igFMxNk1A2UwgDItd3/kpAxsRs5pbY6tAsVSmxMSPccpHIDoOikEsoGWyokGOVr2n4TdJ9WXbBQmUlAbdxPGH6FrhqOiy5qUscWjlspcOqXNeYifC7X0KtyNZfM4X90BjEEGxClhgdI/UENGpV/JEXXEYv6o2Ma29ha6AaImNpk2to31QEeG2vzQVNYzOGNBDWaW8+ZVd9XfZASPCtNPetD7b7+qzBMbqenqi0lnJ35oCYhsb8p9lIMtrhQSNzuBJIsmBDdvzQBSODzlCieQ1pPIbJFwaT5qKd+azRsNT5lAR5nWtc2SThpKPu7clIBF7XRggapswGiYqAS3GW6h3dsnuUyAW2qBE46AJg26kDKaEg3aUIZoma05hYoCZzbuFjbqnDBzv80u9DBdzQbpOqx9mNvuFAEGBpuPxUU78zrDYI45jJJZ1tdrBPPHqHj3QFeyVlKxl0TmADVABC/K7KdipHMDjcoYmWJd8kTpu6cAGtd1DhdAMY29EmsA2R/TWH/IjHsmZKZnElrW22DRZAQSuu6w2CFHMzK/yKYNsFIByqRurbcwhJsky5JN0Aje+iEgoz5kJreYQAhJOmBsboBZUgNUbTmScA07IBuScIQbolAH5ISnumQDXsn7x55lMSEiVIHLydykhThAKyVkQNkioAIGqfNbldPZLw3uSgCBafsfihJBdYCyfOBsmBB1JQAuQo3aIbKQJSwsv4j7IGMLnAKyBYWCAVkXwtzc+SQbmP69EzjmPQDQKAAkntZKyAZMismsgGSAT2SQE1k4CKyeyAGyeyeyVkArJi1FZPZARkJrKQtQ2QA2T2RWSsgBslZFZKyACyeyeyeyAFKyKyVkANkrI7I4ojI61tBuUAwtDCZ3/AOkLOJL3FztzqrFdP3smRvwM0CrE2CIhdoLipKaLO/Mdh+aiDS9waNytGOMRtDRyUkjWSsislZQAbJWRWSy3NkBG5wjaXO5fiVSc4vcXE6lS1Umd+Rp8LfxUIQDgXUjWoWi6ma1AJo1Xb9mfCwxzF/ptQy9FREOII0kk+y39T/yuSoaGfEKyGjpWGSed4Yxo5kr6F4dwODh3CIMOp7ERi73/APUed3fP8LLyulLvqafBH1meH01fdRS4Iv0pfLmzRXmna/xX3MDeHqR9pJQJKog7M3az33Plbqu74jxyn4cwaoxKosRE2zGc5Hn4Wj3/AAXz13lTjuKS1VU8vmneZJXHzXl9E2nHPrp7R+f4PE6CsesqdfP1Y7eP4JcJor/XOGmzUWJzhzxC0+Fu/mVoVUjaKm8IsfhaFiG5JJ3K+ljq8s+wguJ8TBsknshe4RtLlobkU7r2jHqUCQB3O53SJyi6ACQ20QXSJubpKQHls3MgueqN7yWgckHJQBEk8yVJHrY9FGjiNnjoUBK/RVzuVaLb78k4YPuN+SEFaNmd1uXNXQ3JE6Tpo0eaBsQaTYWuhqpzmbE34I/xPMoCNjHA7lG4FwsSVGJvJLvT0QFpgBaDzGhVaaLJJYbHUJRVBa/UaHQhWXZXgAjZAVDEQLoGtL3Bo3KuFoPL8UzGMY4kDdCSSKNjG3d8DBc+aqOlJkLzuTdTVkoEbImbHxOPU8lUshBa70SNsDYnkpIGHIW721Cpao453xOBBvZMDBPURXs8DfQqu5mXdXzI17fhsDyQ91G4fD+KElAhXaenPhjA8Ttz0Td1GxwIaLjzUkk4hpHkH6yQ5B/C3n89vmgKlVKJJfBoxvhb6dVDcnmUt0rKQFEbOt1UxZmHm3X2VdWI36Bw3CAQAUcmiPQfZ/FP3bHcre6ACJtvF12WvN3dJDFTk2kH1ktuRI0HsPzVejENO8zzFpETc7WH7buQ+f4Kg9755XSPcXPcS4k8yoBPNUOmdYOdl9UEUbmytfckA6jyQhpBRGoyCyAuyQWJbcHmCom1TWeE7jRDT1XesLX7t29Ezqdkji4jU+aAGqqM7bAqvBCZX6jQbqwaZjTrf5qzTGOOzRbKTuSgLWGUrcklQ4Wt4GX+8efsNfktCSVtNThrJ5BYWAzlZGIYg0zdxSv+ohGRpH2jzd7n8LKleV5uXEqCC7Wd9VM8Mj7dMxVljC+njkc3W2V48x/VZ8dS6HfZWqXGGd53MgAjfoT0PIoARIIJTE47beiKWUBtwU9VSNqntc1x8OxHNRnDiRYufb1QGXK50svMkmwWnRU9y2HYbvd0HMooKKKCQPJcSOqbEqlkNOIYiO8lN3kcmjYe519gpJNinqzTtd9HqJYmON8rJC0fIIKisnmaQaqoN/8A3rv6rl21MjdnFSsxCRu5uowRg1GQP7t13l7mm9zqSFlV8BjkzgeF/wCasRYw+N4OQEcx1Cu1EMdXDZhGV2rXKSTBSWl+5x/1D8km4VleCXFwB1Ft1IGo6ZzGB9vG/YeS04xPTS5YpXMyizsvN3P5bKEztomGd1szdGA/e6+yrx4oy2u6gGsKqo5zyfNVzHJNK/vJHSF/wlx1B6KsMQYeYTmvY2xzC4UAz8Rpix3eAb6O9VSW3M+KpY4jVr/wVEUFjcvB9lIKrI3O5KxTwhl3u9ApxCGi1x8kRLIxnd8LdbdfJAF4oiMpyutcm34KGeeSxLpDp5BA6sDiSdzqSq80pkPkgE2Qud4je6JzA4X5hQKdjrgFSA42CyJ5ACBjgwWLj8kMhD9iUAAFyXfJO9xjAsbE6o2AE6/CBc+ihe4vcXHmgC7+T7xTAukdqSUIaSpY5Gxna6Afus7PMJRs+SlbKzVzeuyFthyJ91AGfYJRsuAbanZP3bTyPzUmbI0kbgaBAVpyO8yjZuijAJRxxmQ+SsCCyArZSNVaa4SsBPPQpnM5WRhrYYiTy190AmQWG6Z8V+aaPE3MABggd5lqUuJGRtmwRMPMhqAZ9o2X5BVCSSSdyrz2CWHTmLhUmtJKIAomPLHXR93ogc0g2UgsPAe3Q+YUfdv6fijaO7Zry3UgdAR/jgerSoBWMbjyRhoaLcgpXCIfDM1x6AFRSghmm3NAQuOYkpk9k+VSBgla6RFkQQEkUdhcppCCbIg+w13QHe6gA2smzW5BEdBcoFIHz+QTg3Q2SGhQDkapw1PZOLKACWpAWRJ9GjMfZAM0jmy/vZFmjG8fycoy/oEs5CAM2OoFgo7I2uB02SIuUAFkipMh8vmo3Ag2KAZK6ZSwR53XOwUglhZlbc7lSAJ1IxuVpeR6KAC/wNyjc7oLIjcm55prIBrJrIrJkA1krJ7JWQA2Ssisgmfkb5nZAW7JAIrJIAbJ7IrJWQA28krI7JWQAkXQ2UlkxagAslZFZKyAGyVk9k9kAOVKyJKyAGyQCKyeyAENJNhupKt4o4O7B+sfup6aIRsdUyaMbt5rJqpnVEznu5nboq5yymeJ47CFA8onaJ6eLvpQD8I1KuXJ6OGze8cNTsrICK3QWCVlABslZGlYIALIKiXuY9PjdoPJTWABJ0A1Ky55TNKXcuQ6BCAPNEAmCkYLlCQmNUrQhAW5wjw5LxRjcOHsu2L455B9iMbn1Ow8yqVJqEXKWyMqtSNOLnN6I73sk4W7uB3EFSzxygx0wI2b9p/vsPK69KypU1NDSU8dPBGI4YmhjGDZrQLALlu0riocM4C9kD7V9YDFBY6sH2n+w28yvjpyneV9N3t4H5/VnUv7nTeT07keb9qfFf7+xkYbSvzUVC4tu06SS7Od7bD36rLw2j+iw3do92rj0Wfg1D30vfvHhadL8ytHE6juY+5afE8a+QX1VOlGnBUobI+3o0I0acaFPZGdXVBqZyQfA3Rqrp0l0pYOxLGgyrzOzyW+y38SppHZW+Z2VcCyksJRSm7rdFI92UeZUby0211QAJwLp7DqfknAspAemQjqkyPMFG83OnJFFI5psNfJQCQwEC6aFovmKs6kXzAJRMaLud8DBmPmhGSKWZ0UrWxuLSBqfNTione2xld7aKiSXvLzuTdTNlsNlDDJY2OzEOeXE9UNXBdolHLRyjMxzBwOo1V5jmSx5tC1w1CEGVZJXBRsG7z8kn0rHCzXEeyZJyQ00WZ2c7Db1ViaR1IGFhHeO8WoB0UkEUbSA52VjRdx8lRqJjUTOkOlzoOg5BSNy6zFJXjKXBp8mj+iWZ0rwZHl3ryWcpGVDmabhRgYL81KJI9vEzX1CpyR5dloQVTJYQ+/iGjh+qqSQGRxOezSdBbZCCoUcEfeP12GpUxpB9/8FNS013siDmtzHVzth5qSQpCKWm74/wCI82jHS25/RQDF6sfaZ/sH9ENfUCoqCY7iJgyRg/dH9d/dViEJLRr5JiBK7S/QBHK0SDLcWOxVBTwyeHKeWyAj1aS06EJ7XUr4xI7MTY+m6bu2j7R+SkEeTMbKeNjdSb5GC5Qhtr63SqXd2xsIOp8T/XkEALayVh0LfTKCjOJTkWHdjzDB/RVU4BKAtQgzDXnoVYZRd04tdy2PUIMMcyKoDZCMr9PQq5XvYXtYx4zNNieShgq1MXdszBZxNzdapAkYWl4N/JV46Nscoc5wc0a2siBJR0Rc1rLEveRp+QXUUkIpGd3FHTyNbpmfE1xJ5m5WIJm0FJ9LOskru7hHl9p36e/ktCixeF8YDvCVVkFyoq5xGcsVKD5U7P6Lm6hss73STFue+uVoaLeg0WzV4lEGHKQSsCorznuBcHcdUQRBLFklDuTvzWhTxMc0aKqbTMtYm40VqmjexgDntHzUsMr4gxrRYKpDAXeLkNlerKZ8pu17fxU1BSslktJdtPC0ySu6NH6nb3QBUla7BI4j3FPPLP4yydmdrWctOROp9LLdh4nEzP8A/E4QP/4w/quVkmkxGskney2c6AbNHID0C0aaHuwFDQLlZUPxCqjjfS0dNEdA6CEMOY7XPRZOLUDogXWIdHo4eS031EbGkOICKsqqfEImStIMuXJKORI2PuFKByiSuSYZNndkDct9LlIYXNa/hPurEleCEzSBo25noFv4fS2zTEAxxWGU7OJ2B/P2VCmpXx2blvI82sPwCt12INpnMooHBzIL53jZ8h+I+nIeihg1nYnFEy37rw717t3/ANSzK3GO9kZGKSlgaTq6NhBA+aqOrs4UJka8+JQiCziFL3kbm/bbqD1WLay34pG1FO03+si8J828j+nyWbU0Ejp3GNt2nXdSSUrp2tdI4NbqToFY/d1R90fMKxR0rqcukkAzbAdPNSCelpQCGXIYwFz3eQ3WhBVUJjF8NaXW5zPVeWeOCAQj/Eks+TyHIfr8lVdMG6gqoLFbUQWtHQsZfmJHG3zKq1FPdroz0uD+SRqWu1KaSqa+MMv4m6D0UoGYQWkg6EJlNLGXuuNzumbCR8RHzUgjsVPHHcht7cyUsoBvpdPIe6h/ik/Bv/KAYTxD/Jv55imNRGQbQAHrmKgSQEwbmHqmbCQ6xGqkgILS3mNQje4m1hrsoAL4g2M2Vayvgty2JF1WbGGyE6WGyAOGK1gdzqfJE2uYy7RTxOAOhN7n8U0ru7h/ik09lVAugLLq9x+GGFvo1HC7vGX581AyDNqdlPAxsb7E2aUA7WZJPCCQ7opi17Rcsd8kbKaRzvCB6k2RPgLfjkiH+u6gFVhLnnMCLdVFWP2jHqVaDonOLWPDiN7BU6qJwmJvfNqCpQK6exVmOlNruCT4dNAmQFRPuDGTtqE8kREnhaSDroo6djhJm2yq0JIWuDZpCy/MNugISx9vgQxssS54sRoArvd0xbdtW1/kG6qB1iTlzWH3hZQCrUP+x7lQI5QRI6+puha0lWAgp5Hh0bbc91GQGhCDcoBtkrlOW3SyeaAYC5R/C3N5pNjNw0DUopm2fkGzdL+aAISQkf4Zv/Mgc9pNmtI9TdAW2TKAG4XCYBEDdqcN6IAA25SLeilykch801vmgAvYIg6LmXj2TObrZDYBAG4s+xmPqheNildEPEEBHZKyMM6pEIAALkKQkDcpwLKN/wAVuiAIuaNiT7KO90kykDgEmw3KuRs7tuVR00emcj0VgBQAo487rcuaKUgmw2GykIEUeX7Tt1CiIBsmsjsmshINkrJ0kA1krIrJWQA8tVUkd3jy7lyU1S/KMg3O6iDdEBqWT2RZU4agAsnsislZADZKyOyVkANk1kVkxQAEJrI7JrWQDWTWR2TWQA2T2T2SQDAKalpnVMojb7noFHZaZIwfDzK7SeXRo6f/AGVJyxtuZ1J8Kwt2Z+OVLWFtJF8Me/qsYmykkeXuLjc36qF5VoxwsFoR4VgEm5stKmg7mMA/EdSq9BBnd3rho3bzK0LKxYGwSsislZQAbJWRWQyyCCMvPt6oCriE+Udy0+blRTucXuLjuUgEATRdStFkzGqVrUIYmjyXvfZtwieGsDEtSzLX1oEkwO8bfss9hqfM+S8+7KeFRjuOivqY81FQEPII0fL9lvtufQL3RwvrzXzvTF3r1Efb9j5Xp6+1/bQ9v0X1KlRNFSwyTzPEcUbS973bNaBclfO3FWPz8Z8SS1bcwhJ7unYfsRjb57n1XoHbPxZ9Fp2cOUslpZwJKoj7LPss99z5W6rz/A6Awxd88eN408gtuibbq4ddLd7eBr0HZ9XT/czWr28PyW2MjoaW2zWD5rDmldNI6R+7j8lfxapD39w0+FnxeZWcvZguZ9DTjjVjJWT2Sk+rjzHc6BWNM4K0xu63RBsnOqjmf9ke6lEkb3ZnXTJ2tvryTE3KkDh1uQTt1QJwbG6AMsJ1Cnp4BcE3QM1tl5oW1ErDo5QQW5O6jsLPc4+dk0keZhZzKgbVG/jAPmrkZZMy7SCRv6KNiNjOaDtayd2itVELg8OY2+be3VQOp5z/AJZTJOSEq3TssWsvY8yo4Kdxk8bSMvVW5Ye5pi4/HKcrfTmf0RshshGIRAkOpw8X0OYgonVkdvq6dvu8lV/o/RLuyxNBoaMcbZYGucLh4sfIrPlg7t5adwrGH1NnOgcdH6t9UdXCZsrmEBw0N+igjmZzm2Qq79CkI1LPmhjpnMku8Cw19VYtkemgeS1jfjcVN9KibK5ghbI0GwcXEX81LIRSUj59pJLxx/qflp7rNAOllG43NP6TEG6Usd/5nf1QRDvmF+UDUgt6KrHPl0cCrENVHG8i9g4WKEYK00Ihky8jqEDmKzUtzt/iadFCGPP2fxCklEBaihjt4j7KQxG4voOt0dw0F5+FvLr0CEgSPbE4NILja51tZAZo+UZ93KFzi5xcTcnUplILEcge46WRTQ5rPbsdD5FV2uLXAjkr0L2nf4HCxQFX6OVNHTlrbqdrc1gLWG+qleQG2Fj7qAUXx3dqtGjFLTsZLXsdIyUlrA1+Q6bm9io4KJ1XMyJgGd7rAnYeaq4jMKmqIiJ7mId3H/KOfvv7qCDVlxDBITaKgqZPP6Tb/wCVRGro62eOClo5IXPNsz5s1/K1gs6OHNZaFLHEyxcLOGx6KCCKtpiGB9iTHoR0CqMnAW7W2mtPGQ4SaPHR3P5rAkpZGSua2NzgDoQpJQb5dL3VYDvZA0bkqX6JUOGkLz7Kejo3tJc9pa7YA8lJJeoKMOu0G0cbDI89GjUn/vqFtti4eMTH3xg5hc+GIWVR0H7vpYqYg99Uhs0v8LN2N9/iPshlnZGPJV3Kj4k7A6eIugOJl3ISNZb3IUM1E1oML3EB4BuDo4bj1CjdVQv0NreakbJHU07Yg8Z4B4RzLL/ofzQEUTIWC2gIQ1FdHC0hpuVRxESslD2Xs/e3VVCyV+7X/IqcEjz1Tp3Ekq5h7DG3OLlz9A3qqkFG+WXLlIA1OnJbuHsZRsfXy2Hdnu4Qech2+Q1+SMk0qWhwuQvZV1NcyWN2Vwgga5l+diXD02Q1lPglK0ubUYo+3LuGf/Uhp6iPuwGlG97XCzrFVIMnvWSxiaLO1jiQ1x0cLfqsOVj4JHMJ2PzXUhkT2vp2gDvPEz+Yf12+SxsSo3ujEoabt0PorpkmZnd1Szu6p+6k5Md8k7KeV72sDHAuNhcKQXMKjcZXS5yGgWPn5LZj+gl4iq554nuaHNEUYfp53Isq8NLHTxeI2ijGZx6//dVm1AkldK62dxufLoFANYwYQwXNViB//jt/+tVL0s+d1OZXMYcp7xoB+QJQCVruakhMbJfFYMeMrv0PsoBi1jXQVLvESDqCeih75/VamI0pcxwt44yVkWPRWA5e480UTS59+iDKeitxx2DWN3O6AY5WgF7srSbCwujaynftUgHoWWVaokD5LN+Fvhb/AFUSAtSNDX5QSfMhRzgkh5JIItrysgjeQ4AnRWu7Dg5h57eqAp2ThhKNrS42APyVsxNjYAoBTY05vTmrMbowM0znNYTa7RcpCHMQ1o1Kr1DgX5Wm7W6Dz80BqR0lHMzMyqld5CMf1VeenYw/VmQ23LgAqMUr4XBzDYrWpqyKdhZMLE6XCAzpo3PIPK1lJFBysrn0dgJF7g6XCKBgAJtc+QUZBA6ItGiriN0kobyGpKvSuc0HwO/2lBC2zb21cblARVc5iEbfcjy2TB7Xtve6rVDzPUOLdRew9E7aZ9tTZAFG5rKoHlsVckjzDa9tQqXc5VoU3gpgZDcAE36BAM0PI0jd8kErHgfCdVaLqKQD+/wNv1a7+iinZBC0OFWyQk2Aa0/qoBXDcrSdgBclZ73mR5cea0KlrjTuA05nzWdZWQEp6WY95kebh2noVBZLUFSCzUx635jdC0NAUhJeRmNzzTy94xviYbeYUArSG5TAaWRFwP2RdIaaoBtL6kBSsjade9Z+Krk3N0lILAcA67XXtzCibcOIKaJ1nW5FSPFjeygDEXTFqlYOZSIugIW3CIWO7mj1TnT0UJNzdAT5W/8AUYmvzabqGyNh3CAE3B1TgEo3N2KkbHYICDLZEy4v0Urm8k1rDyCEZHbG9wuBp6pGJ/T8VFk+04oS88tAgJDcbKIkD1UrHfV+YULt0JGRxRmR4b80CvU0XdsuficpBIGgAAbBTwRgAyu+EbeZQRRmV4aOf4KaoeLiNnwtVSH2ELyXOJKGydJSSNZIhPZPZABZKyOyayACyTiGtLjsEdlUq5bkRt5alAREmR5ceaNMxuimii7x1j8I1JQGmAlZOAnsgBt5J06VkAySfdJACQmsjSsgAyoSFJZCQgBSsnsUgFIGskUYClpaSSsqGQRC7nm3p5qG8LLIbSWWXMGoRM51VLYQxa3OxP8AwsfGa811U5wvkGjB0C3OJKyPD6ZmF0xsGAd6Rz8v1XJuJ1J5rGl6X8j9hz0czfWv2eADjZCxhmkDG80zir9BT92zvHDxO29FsdJZjjbGwMaNAi8k6ZAJJPZNZAOBcrMr6jvpMrT4GaK3Wz9xDlB8bvwCywgEApGN1QhTsbZAExquUNDUYhVw0dLGZKid4jjYObiqzAvYOxfhG0b+JauPV14qMEbDZz/fYe65bu5VCm5v2eJw312rak6j9nidzwxw7BwxgtPhsABMYvLIB/iSH4nfP8AEfEWO0/DWC1WKVWrIG+FnOR50a0epWuW8l4L2u8WOx/HG4PRSZqOheWnKdJZtifbYe6+Xs6Erqt6Xiz4yxtp3tx6W27fntOUbJVcR4zPiFa8ySTSGWR3meQ8uXsteuqPodPcaPdo0JYdSNoqYNuA7dx81k4hVfS6guB8DdG+i+tik3hbI+4jFN4WyKxNzc6pWSsiAWp0DxRGR9htzVepk7yQgfC3QK9VH6DSBm00+v8rVmBVTzqVTy8guOVtyq+bW6KZ+Z1hsEAF1cuH8TdEIF07TYgI3N10IF1AAypZbmyOwHO/siibmdl5lAMRkiJ66BRhpKt1UJDY7fCL/ADTRwk8lGSuSrlKkpC5s4Lff0Us0eVqkpIDa9tXbJkZ0LMfdPcBJKyInYuvY/JSyRQRi5q4fYO/osut1nLAdGeH35oQ9wFibquCuDTZ3b35WSB9hfQWQ1we58bybsDQwAclUgnbHI1/TcdQtN8bZoTlIIIuCoehD0ZR7ooXNAGoU0LZXDNIx4HKzUNSJHt8MEgA55VIKbIw+UEctVdbMyANfO1xYTbw7n5pqWmcGgW8TlVrZO9nyt1Yzwt/UqdyyeTT+k0D2+AVHocqia6KaTJEyQG17vI1+SzowWK3Tzhr2v0zNN1BAVZA+TunFxLWDLl6a3QCCwWpPEx+WRn+HILjy8vZZjpnRPcwtJINtApTCeSKVgaFUIJdYblTSyOkJ8Lvknp4rDO4anZWRdEoBd8TtANXFJ7YWC/fg+jShrXCJjYR8R8T/AC6BU7k7oSWS+O4DXlxJ6WTysLorA7G9uqq6q1E8uaHX1G6kEbKclGaYjkp2kMdYag6hS67kG3ooBnSQlmqs0kT3FkY3cefJO8hzibaDqjfJ9Goy+1pJ7tb5N5n32+aAu08+EFga6qmY7n9Tf9VZMGD5DJ+8Kh3PKIRc/wDmXMtGqsxU5fsVDRDNQCVsL3QOy96wtDudj/3ZUIIc2hGq1MPhL4TETq3xN9FXxGF1HIJW/C/fyKjJGR44QwKGsqWwtyt+I/gq/wC8HbKJkL66cBpvfU+QU+JJPRyTsa9zTdryLg87c11NBgdLPZtditPQzWBdE+N7rXF9wLLLwujZB3lbUtH0WjAe4H7bvss9z+AKgOIvrZnyPuXPcXE+ZVWQ2db/AGdwWNtzxLR6f+4l/osipgpWSF9HUsrYGuymRsbmjN0s7VZbonvG5+au4FF3U8lNIfq6luXXk/7J+enuo2IK9ViMtRiE76jWV7sxNrAjlbysoKoF7Lgq3jFE7uTNG20kPxDnbn8liuxBwba2qsu4kjlfk8yiw2R4ro3M1P2r7W5qG4k1Juugw7BHxwtAYTPMR4RuL7D1U5wSWcPwmfE5MtOYmm9ryytjF+l3EC60ZeEMUphd5pGjr9Mi/wDqWfjkJp5YcMiIc2jv3rhs+Y/F7CwaPQqrlfI2zybKuSCeopzTzCGSWB8lr2ilbJYeeUlZmOyS5qdgAbDGyzQObr+InzOn4KSCn+hVjKpgvlOreThzCvYrRCpiLI9WuAfE78v6KUSc9HiEkOgRPxadw0NlScxzXFrgQQbEFNZWwSWRXzl7XBxzAgi3VdNDMKuwkDWSO+IHRoPqsHCqYucZ3jwt0b5lbM7TFQZdO9qdv4Ywd/c/gCoZBtu4Urmxd6X0bWb3NXF/9SyaunFM4MfU0z3k2DY5mvJPsoml4hy5za2ypTULXOErHZZGm4PmoQI8WkkFMGMcBGXAv6+Xsslsjgd10dUxs8Ydl8Eo1HQ8x81zs0ToJXRu3H4qxJO2cgalBLVPcLAqG5dopqSDvJLu+Bup8/JAXGyTSxsMnxZQPM+qToZmtDsvhOxuE1TN3cTn/ad4WrMzG1rmykF57ZALuIt/MEDi9sby0akWv0CqK3G/MwO57FAVmxlwvZC4WKtuIjNuR1HooJLOOiAiViPM5ovvyUTGZnW5c1oUzGMa6ofYNj0bfm7l/VAHDhlc9gfHE8tOxDh/VO+hqY23lAaB954/qqxrjHcRfMoS76Xo82cqkkji5kbywDMW2B6KrHTuf5LRhYRCA4XLND5jkme1sRvsCmQV20jWjqoZ7xkW0Vp04t4VAI3VEgb8z0CZJwTUTpDCS7Vt9Ffgp3zNPdzRCxtlMoaR7Ks9wp4S4DRosB58lmNe9rswcbnmhCRtTQGDWaohH/8AsufwQkERksIuWmxt1CyXOe/4iSr9A8yxmNx8TPyUE4K0BY0nSxClMoRzUWabM0hodv6oxQMA1c4+miDBAwiaQN5c1ZrHtbT5AbF5t7J4aVsJOp8XMqjXSd7UnITkb4WoMEL4hyQFp81K0HmncABdSMFyB3exC+40Kovj7qVzOQ29FLRyO7wt1sRqrzYRJ4u6Eh/lvZCDMygqSGFpzSO2GgHUq4+F3KmHtGoXtLfC5uW3K1kyCrObDLzKiu61rmyJ+ryT1SuAFJALWm4KIuuLIS6+ylY3OwICGyVlKGgXvunZHfU7JkENiFYBJAJ3SMdz5JpXZG2G5QEl39XBC4uO5J9UDauZrbCR/wA1GZHudmc4uPmUAcnwW6lRhqmLcwQtbdABZNsbqcRpu7A1TJGRx+KIB/8AEopXZRbmUwnlbtI75oCZwcNwfdRyPLQGgb6koRM9zgXuJA81M+PM1AV9Xb6osqNreiaTwhAR3sU103qk0FxAGpKEk1NH3j7keFv4q6AhijEbA0ct1ew+nEjjLJ/hx6nzKhvCIbwshBn0Snuf8WT8AqinqZjPKXnbl6KKyJBLtBslZFZKykkGySdJAMUkrJWQATSCKMuPss9oLnFx3Klq5O9kyD4W/mmY3RSAgLBW2M7pgadzqf6KOmjDnZ3C7Wa+p5BSm5NzuVALieySdANZNZFa6VkAwTkJWT2QA2SRWTWUgZMQislZQCMjVKyIhMgGC6fD4WYDg8mJ1Dfr5RaJp312H6qjwxg5xWuzSD+7QeKQnY9AqnF+O/vKsLYTaniu2IDn1cuaq+sn1S25/Y4az62oqEdt39F7TCrJ3VE73vdmcSS4nmVUeUbnWChJLiANSV0o7tiWkg+kTbeFupWsAhpqcU8IZ9rdx81JZSAUkVklAGSJDGOe7ZqcNJIA3Ko4rUAEU7DoPiQFKomdPKXn2QBMiaLlSCSNqmCBoUjVUq2b/BfDE3F3EFNhjMzYT9ZUSD/LiG59TsPMr6apaKChpoqWmibFBCwMjY3ZrQLALl+yrgr+yvDrZqqO2I14Es9xrG37LPYanzPkuwqZYqWnlqJ5GxxRNL3vds1oFyV8j0ld9fV4Y7I+E6Yvv3Nbhh6sdF3vtOI7UeLf7JcPO+jyBuIVl4acDdv3n+w/EheFYDQd481ctzY+G/M9Ve4w4jn4+4qlrBmbSt+rp2H/AC4gd/U7n1VjNHR02gsyMaBe7Y237elwv1nufSdG2f7Wgov1nq/t7Cti9T3TBAw+J+/kFjKSaV08rpHm5cboF6EVhHrQjwrA2yt4dA17nzy6QwjM4nn5KvFE+aRscbcz3mwHUq1j0rKRkeFQG4js6Zw+07ook/6oib/qt2ZdXUurKl8zvtHQdByChkcGN8yiaFBJ43E/JWSxoXSS0AsEx02Ssb2RZD5KxIzG3KNxykdUTG2FlG85nKAOJP4VPTTNEgDmgA6X6KJsRIvZMWKCGaslP9W7N8KeGogisPozX/zEoo7so29/qGtuQqP0tp2jb+JVNzLcvzzQzx5W0sMd+YBJSaBTQSz7mNvhHmdL+yzjUVH2Gtb/AKf6rVhmp3RNdJIwEjxNPVQ9CHoYrGl2pKkMeisyMgikIika5m48vJCXs5Ob81bJbJUey260cPZKYGt1OY+Ec1WZTmoma02DNybrQkd9EpnytIDyMkYHLqfYKG+REpciMyREkfSYgQbEElG3uiLmqpx6yLIyJu7U4JwbD2v7l5j+ItOUrKib1Wjh04+jmO/iYdPRRTxt74kCzXahRkhMrloUL3ZdVb7oHkopIMxDW7lSmWTJaOvlZC6Mi7L3HkeatMpzUC4lgZ5PlDT8ihjiZDEXlvgjbc+Z5fiszvCXlx1JNyp8Bvsar6DILmopvaYFVhpYtsRfdVszToCp6c6OZbzCIsinI17pXGQ3cTck80/dqeYZiDbUaJ2t0ViSuYilC0hxttzU7hyRMiu4N2G5P6oSM0OGzg0+brIiZRu8f7x/VUp5e9lc7YbAdAgUguj6x1s1zzsbo6yGWaqu4BrAAIwNg3koaEES2OgI381qGMui1+Jmo9Oiq2RkototOiIMdDqDorDZmuGiGRzcu6jJGSKHFZop2ZGNNjqDzC16RrsWkIia0uH33Bo9LkgLMpKMOJkI1doPRWcXgEDoqBg/wfFKRzkO49hYfNQ2Q2bQ4WrnC/dQf/14/wD6lWqsOmw1wEoia47BsjXE/IrOgjuBdov6K5SUjGVTJiBbZ3mCoyyNSvi1Y+empaERd3A0mR5B/wASTa59BYAeqjgpAG6BaldRtyOaBdw1aepWU3EgG5WsIcNDdEycl6NgYPERbzVasxCKIWj8Th0WdUTzS6lxA6KTCaQ11WGOB7tnief0QGvFWz17GSyMLZJR4gPtHa/utin4PrJmi+DzD1pj/RVa2op8OoJMuT6VUtMUQJH1bftP9baD1WF9JrgAG11UQOQmcf1Ub7BHVycG1MDe8dhUjQ3W5gIt+Cg/eLsEZLWiMyTNblhdyjedA8+mtvOy5qSoqJGFs1TOWncPkd+pXUUM9LimGMEhY52XupGgjUjmo8QZlI1s7MxNyeallpgBcWVCJk2HVT6ZwJDToeo5FXJKg5N1JJn1dQynNnC6mwzFY54XQuaR3Z8DuWvL9VnVwMr8oaXOcbADmVv4TgEUEV6g5Yom95M7r5Dz5BTkMpyYXHVSGQ0we5xuTlOqZ2DwxC7qMf7Ct2ixrFaSm7qkxWrp4y4ubFHKQ1gJvYBU6jGOIHOJdjFe/wBZimWMmYHQwgMcwtibu1o1t5LLdi5qp3SyeEnQDk0DYBbsERqKZ0kznPmY453ONy4HY/ouaxWlFJUnKPA/xN/UKyJLv7xYB8SifisfK5WVullKtgk2qLETO50LmeEjMD0KeaKF780zGuNrC5UNBSyQtDiDnfy6BX6XEamlnkbTTuYwWDrW8RHNAUxTUp2ib8ymLBE3Kxtm3vZa5xqttrVSfgs+okfO6SR73SPOt3G+nRRkGPWzd9NYXysGUD9VBZWqyO5EoHk5Q6KwI1JA/K+3Ipd2TqjijDPEd+SAkeGvtcAgbIcjB9gJ5J305aIyA61zpdEzE6wkNbIB6NCgCYwDYWuhrpWuLII75Ix83Hcq6BJUAGWRz3AaXUVRStLRINxoVBOCg2MlSt+rN1M1gtohkYSEyTgKOuyvAI8J0KtuayVoDxcXuqNPBaQPcNBsp5amSme3uXlj7XJHRAkS/R4m/wCW0p2tZHcsaG33UTccxBmnfkj0COGskrZT38ribeAO6qC/CQYg/PI2Fh8LBc25kqFsYHJXK6EgCUDUaOVZrxzTJKiLIAE0b+6ma5vxXtbqndIC02Knw6gfM4zOY+wOgyndRntLKDbwkW3AM8eYCx0zbXT/AL0jj07uInycVWxGKd8vdshl7uP+A6nmVTML2/Exw9QQoymW6qS5GiysdVTFsgaB9nLsqlfTujlEoHhfv5FV2uMTg5p1ButZsrK2C2Xwu38ip2KcJmDUJnNuLBaYw+FjdYy7zzFJ0MLHNcyMtI/iJUZJ4SpBB3LNRYnUqnJO/vnPje5vIWNtFer5QyHKPjcbegWbZWRm1qS/TqkbTye7ilDKXF2ZxLjrclQpDQgjdWKkkzdcyiN1YvdK/UXTIaIY2F7rKdgyXCdpA3FgncATdMkAhoc65BUwyAWEf4oYqhsLiwxRPHVw1Ur6yFrbthi9Mp/qoIIQLG35qrK7PITy2Cstl74lxa0a7NFgoTHleR8lIIw1OWqdsV0L2EckyMjQG929FM3K0kloJPVBFGQM3MpCpbG8gxteOpJQgk7wHTu2pg1P9Jgtfumemv8AVMHCYEgBoPIclBBA9pkeS3bYJdzbchMc0bi3onAc7dSSCQBzup4X5mW5hRloRxMyi/MqCA2xhpJLrX5WVeWznGx0RvqAQWhuvW6hzeSIlDEK1Rw/5h9AoIozK8NHuVogAAADQKSSSGF88jYmC7nGwWhiGWkjZRRG+XWQ9Sp8OhGH0Lq+UDvJBliaenVZzyXuLnG5JuSs0+J9yMlLjl3IislZHZMtDUFKyJNZADZNZHbRNZANZQ1Mvcxkj4joFPusyol7+Y2+EaBADG1TgHYboWNVqljteUjRug8ygJMndMEY5au9UyfdKyAvWSARAIg1ABZLKjypEICOyeyKyVkANk1kdkrIALJWRWSsgBLbp4KaWqmjghYXySODWtHMpzouy4Uw+DBcIn4mxFugaW0zDu7lceZOg8rrGvWVKHFz5eJz3VfqafFu9ku1lXH5ouGMFjwamePpEzc07xuBz+e3ovO5pO8eXcuXotHHMSmxGslnndeWV2Z1tgOQHksp5slvSdOOu738SLWg6UPS1k9W+8je5XMMpszu/cNBo3zKqRROqJmxt5n5LdjjbGxrGCzQLBbnSKyayOyaygApAJ7KWniEjvFo1urimSG8EM8oo6Z0rvicLNCwHOL3Fzjck3JVvFaz6XUnL/hs0aFTRBCspGBC1qlaEDCC9G7GeC/7S4/+8auLNh2GuD3Bw0ll3a32+I+g6rgsNw6qxavp6CiidLU1MgjjYObiV9ZcIcK0/B/D9LhEBDjE3NLJb/EkPxO+e3kAvJ6VvOpp8EfWl8jxOmr7qKPBF+lL5c2azhfVePdu/Gv0OkbwtQyfX1IElWQfhj+yz1O58rdV6bxXxFS8J4BV4vVkFkDPAz/qSH4Wj1P4XXy3C+r4kxmoxfEHmWaWQyveebjy9AvL6ItOOfWy2j8zxOg7HranXz9WO3e/wXMHoBSU4c4fWP1Pl5KDFanPJ3DT4W/F5laNZP8ARYC77R0aPNc+SSSSSSV9NFZ1PsYLL4mMnISV7BsLkxeuZTt0Z8Ujvut5q8pKKyzSUlFOT2LOHNbhWHSYvMAXn6umaebjzXOuLpXue9xc5xu4nmVq8SYkyvrRDTaUlMO7iA2NtyskkMaSVSmm1xPdmdJN+nLdgTyBtmDfmoM3kjIa91zqSmyjPYLQ1BO9yl3hHRKQEOshshJZpj3riDvuFN9EaJBc2zbK5w9wxi+MvM9DRudBF/iTyOEcMf8ANI6zR7lbb6bhTCrfvbGZ8UnA1pcHYBGD0M8g/wDSw+qzc1nCMZVFxYWpgOZCweNzWjzKs4dwvjGNPDsIwXE8Rbf/ANnpnub8wFrx8ZjCwHYHw5guDgatqaqP6VUHzzS3F/5WBUcU7QuIsVaWV/EeMVbf+mKh0UQ/0g2/AKmZvZefPeVzJ7Lz57zQqez3jMRn6bhcGHsO4rKqGE/J7wfwWZUcFYlAzNLiWCMHQYnCfycsGSukkdmAY09bXPzNyoZJZJTd73OI6lSoVe1e78hQqdqXs/JbqcNlpXWdUUknnHUNf+RVMlwJF/kU1ymWyT5m0U+Y+YnmpaaFs8gY6eOEfekvb8AoU6ksdRhvClLVgf8A9xYcwnkA9x/JXX8H4XEQ2o4wo6QnQd7RVDR88tlxSt02L4hRjLBVzMb93MS0+x0WEqUnqpv4fY55UZt5U38Psd7h/ZcMUt+7uMeFK5x2Y6qMTz7OAUmI9iXGVJEZWYLJUxjXvKKVlQ0/7TdcIMWZMf75Q083V8Y7p/zbp+C2cF4jr8KlbLgXENdh0g1EUspaD5Zhp8wFhKlXWsZJ+K+32MJ0q61jLPivt9inLw9imF1LhUUkzHt0LHsLXfI6qXuBdpewHmA5elYf2947TMZS8W4Vh+O0pFr1ULS4j+F4W5Dg3ZJ2pgNoqqbhvEnfDFK/NHfyPJYSu6tN/wAsNO1GDu6lP/NHTtXn6nj+RpFm0UZ9j/VV5aXIc5hEXsR+a9A4w/Zy4x4WjdW0DBi+H/E2Wmdd1vQbrzMRSU9VacSB7Dle197t8iCuqnVhP1X9zqp1oT9V/cbEZX9wyBoIYXZnO6nkP++qptiNlrVEYewssOoKoHpzW6ZvFlfJrol3joy0jcKVwyi6GCLvJC92w/NWRdFgeM7b8lJYt0MQ92qGqPcwgg2e86W5DqqTppX7vcfdSSX3g75APOyjllyU7mgHM85b9Aq0crmuBcS4A3sSrbsrwW/ZdsUJKYYpGU7nC9kcTLOyu3BsrvhDbBQQ2UXPdGLWWjSVAliY4mz9jfmq72Ne6ytUjY25pHt+riF7dTyHzRkFqCnjtYUjHediVMcLZMNaXL6NIVeHHamkjDRWzi2wDyqtZxFilQxzGVlQ1hFiO8NyqaldWasETKN5neR9S3Mxp2LuX9fZZ7C3OXyyBznEkkncqxh9QKukAl1uMjwsyopDBM6InVux6jqo8QaH0umZs8E+ShlxV7T9Uz3K3eCOybi/tBlH7iwp7qUOs+tnPd07P9Z3Pk25X0LwV+yjw1hAjn4qr58bqtCaeC8NOD0+875j0UOSRVySPnbhemxLih5oqGiqa6ra6wjp4i91jtoNl6ngf7KvFGMWqa+GnwoSeJ30mY5h/oZf8SF9U4Dw5hXDdC2kwfDaLCaQD/DgiDL+ttSfMq3LiVJTjLm7woSmeE4N+yDwxEGuxfGq+rdzZTNETfmcxXcYN+zx2b4JEY4eHnVVzmLqqeSQk/MD8F2r8aJ/wov0UZxOsf8ADlaPRWSZZJlWj7P+EcOc11NwrhEbmjKHCkYSB6kErTZQYTDo3DKJnpA0foqpnq37yu9k2SZ28jz7qyyWwy2+hwqXR2HUTh5wNP6KpPwZwvXXNRw9hEl981LHr+CdrJWnR3zUgdJzAP4JgHNYx2EdnWO+KfhulhfawfTPfE4f7Tb8FxGM/shcK1ji7DcaxjD77Nc5szR8wD+K9hjZMdW39nAqdk08WjgffRMEnzXXfsl4ngtRHV4XicWLZL3jlAid5EcvxXmHaXgOM8JzU+GV2F1VHE7xvlkjIZI7kA7Ygeq+6G14vZ4slUw0OJ07qarp4aiF4s6OZge13qDoo4VkjB+dcBcADdSuqco8Wq+wOMP2auDeI2yTYUyTAqt1yHUmsJPnGdPkQvn3j3sD4y4KbLUyUgxTDmXP0uhBeGjq9nxN/Eeaq4tDB503E4oJw4i7D4Xjq3mpcRwmCtaIxJdt8zZGC6rUOEnEarI3WNvikd0CuYnXHCO7LYmSOc7SN17ZR6In2EGU/hqnZ/nTfIKMYNFE9r2ve7Kb5XAWK1ZeIxLH4cMoQTztJcf+dZ0uLvc5rXUtPGwkZnMDr29yVZNkg1swpad0mYd47wsHn19llxVHdiwWvidM2aEtbq5viaRzCwu75hWRJbNZpqVF9OLXhw5fiq5ahbG57w0DUqQaLnxkG2rHjRVmwsYbkuPspgxsUfk0bqIV8eWzqVhPXMf6oAjlOyNjGHNJJ8DBmI69Aqz6i4uyKMel/wCqnYBI2x2cN+iAq5HzyF7t3G5VuKBrNeaUbcpLSNRoVK4gBRklIillfFZzeRU/fxvZmGrXjUdFUmzSaAKWGnIaG3sBqShbAcTIgLOfJ8glLA1w8Ejj6tCjbW0waA6leXDmJSL+1kX7zjaPBSD/AFSEqCy7wxZgL36NaLn+ioF5kkL3bnVdJhPD9djtL34jZBSuFjPMcrL+XNx9Lre4e4BgrK6Oiw+hqser3bMawiMeeUa283Gy5qt3Tg+Hd9iPXsuhLq6j1kViH/k9F+fYcPR4fV4g/JR001Q4biNhNvXotuk4NrDZ1XU01Jblm7x3ybp+K9kbwZgvDlO3+2HEUFKG/wD6XhAa9zT0c/SNp9MxWfP2n8NYC7u+F+EsODm7VVc36TKT1u8ZR7NXJO6qy0jp8X9vefQ236ftaeJVW5/+sfe/Sa74nJYfwI/FRlpMOxXFC7wnuITlP+0H81uU/Y9ilM0GThiGiA+1iM7Ij/8A9HD8lBi3bDxrjTDFJjVTDCdoqd3dMHs2y5aSoxCteXyzyvcdySueTk/Wk/fj4I9uhQoU8dVRgv8A9eL4yw/gdweD5KKOz8T4YpbfZbWxEj/ZdZdSBRusMWw6W3/SmJ/Rc4KKd3xOPzRtw3q4rmlCn2nt0a12tIx09iNR+NyDTvw4eTlGMaufFld6kFVo8OYBqLqVtDADcxn2KzxTR3KV5LsRpU0/Dda22KUT3ecbGH8wtGPhHs7xKLJDjtXhbzt31KS0e7HH8lRwzD+H5QRiMuIQO5OgjZIB6gkFa8fAWAYmLYdxfQskO0ddHJTn52c38VpTbXqy+P5OC8tYVf8APTXjw5+LjJIqzdi2L4i0/wBmuKsJxXS7Y2TMa8/6XBrvwXC8Sdn3HfDMhGLYTXRtBvmDCWlegV3Zbxhg0f0uCnNXTDUVFI8Tx265mEge9ksL7ReMeG2fRzXVJpxoYJ/rYj5ZXXC7I3dSnpLXz7PmfOV/01a3K4qLx4PT2tcS9nCjx8htRGWOaWPG4IsWlUDE/MW2NwvoZnEHZ/xjaPivhmOiqHf+34Se7cD1MZ0+VlmY32AS4hBLiPAONUnEdOBmNLcRVTB5sO666N7GenM+avv09WttXrHt5e9Nr3tPuPCnRubuCEAGq08Zw+uwetkosSoZ6OpjNnRTMLXD5rOOq7Yyysnz9Snwy4XuODceakZHK4XDDbz0ShYGnM7Qeau9zZmYyRgdS5MlOBsq92dnCyKzWNLjs0InGMWtKxxJtYXugqGl0NxfQ6qUZtFO5JJvqUiCpGs2U/cqclStE7I/XY6FWi24FhcqGSK2isBojYC82AsCUIJWQutrYe4UcrCHAW0PMG6laInC4qGH/SVE98QdlbK1520BUFRpXd3GXdNAqKtVIcWNA2B1VcNViQbKSB+R9jsUNkspJAG6AsSxF9i0ahSNhdbdn+5P8LQXm3Uos9Nzm/BVZXJC+FwcActudjdDO/IzzOgUr5ISQ2N7nE+VgqtQ67/IKUSiJJMp6WLvH5j8LVYsWaWHu2XPxO3Wrg2GHEqsMItDH4pHdB091RaHPcGsBc5xsANyV1NbGOH8Jjw9pH0uoGeYj7I6fp81jUk1iMd2YVqjWIR3fnJmYtWisqbR6QxjKwDa3VUbIrJiFpGKSwjWMVFYQxFk1kSVlJYAhKyOyayACyVkdkzrNBcTYDUoCpWzd1FkB8T9PQKlGxPJIZ5i/ly9FIxtgpATWlxDWi5OgV5wDWtjb8LRb1PMqKmjytMp56N/Uo1AEknCdAaGVOAldOEAxTIrJWQA2SRWSAQAWSR2SyoAE1kVk4Y57g1oJcTYAbkoQanDGAScQ4rHSgEQt8czhyYOXqdlc7Q+Ioayqbh1JlbQYf4Ghuz3gW08hsPddDiJZ2ecIMpIyBjWJi7yN4xbU/6QbDzJXktZNnd3bTdrd/Mrz6D/AHFV1n6q0X1f2PKtn+6rO4fqR0j39r+iK73lxLibk6qB7kb3bqXD6U1U93D6tmrv6L0D1i7hlL3UXeuHjf8AgFdsiskgAsmsjITWQAhpJAAuTsgxio+gU4pWn61+riOS0qSOOlp5MQnsGRjwA8yuTq6l9XUPmeblx+SqtX4FM8T8CFIJkbQrlwmhSNQALpOAuEajjbiWlwmHM2Jxz1Eo/wAuIfEfXkPMrOpNQi5S2RlVqRpxc5PRHqv7PvA3dxycW10dnPDoaEOGw2fJ7/CPde0OjudBulR0VPh1HDR0kTYaeBgjjjbs1oFgFxXbBxyOC+F3imktidfeGlAOrPvSewOnmQvi6k53txlbvbwPz+tUqX9zmO8tF3LzueR9tfGZ4o4ibgGHvz0GHvLXOadJZtnO9G7D3WLQUrKOlbEOQ1KysAoC0GqkBzO111KvYnVmKLumnxP/AAC+uo0Y0oKnHZH3Fvbxo040YbIoYhVfSZzl+Bujf6qoU5TLoR1pYBPounxFp4R4cZTE5cUxMZn9Yo+n6epPRPwRgkdVPPjWIAMwzDG97I52znjUN8+vy6rm8exefH8WqMQnuDI6zGfcYNh/3zXPJ9ZU4Fst/Hkvqck5ddV6tbR1fjyX1ZQaFBUvzOyg6BTSv7tl/tHQKpYnZdJ2DBWIWNDruIB81FEB3gB112C6fhjgut4kqJXtYyKmpxmqKid2SCnb1kd/8o1KpUqRgsyZSrUjTXFJ4RjMoJap4dHlEexe46A9PM+QW42pwPhiBl8GkxHFTrmr3ZYY+hETdXf6jbyVvGeJMH4eaaHhUuqaloyyYxMwB3pAz/Lb/F8R6hcS+aSSQyve573G5c43JPXVZxTqavRGMOKrq9F7smvi/EOK8QZHYrXPMLP8KBoDY4x0ZG2zWj0AWcKwQi1NGIz986v+fL2VcuLjcm5TLZQSWDdQSWAnOc9xc5xcTuSd0KdJWLjJ7E7JXRB1kAmwvds1StoZ3/Cy/uFGJCOalZO4HQoAhhdYdoHH0IQuoalnxwSj/SVbhrJBs4rQgqpnEAOJJ2AU4BhfR3c2lL6O7ovoThPs5wqbBYv3zQRVNTMM7i+92X2AI2U1b2EcPV13UdTW0DzsARIz5HX8VbhJwfOncOHJLIRuF69jfYNxFh7XSYf9HxWIa2hdkk/2u39ivPMQwWqw+odTVdNNTTN3jlYWuHsVVxZGAuGoMLrc1HX41LhUkjvDJND3tKf5wPE31AK6HiHsr4h4UpIcX7uKXDprGHEKKYT0knS0g+E+TrLjnUbm8l0fBPaJxJwBUvOF1IloZtKnDqkd5S1LeYew6e41VJRysFJRTWDrOBO3fifgKZtLNO+emGj6afVpHuvVpoey/t+pPDGzA+IXt8MjCGku9dnDyK80r+HuGu0mgfivCVG6nqo2l9dgGa81OOclMftxjm3cdFxtVw3i/BYp8YpZfpWGyOtFW05OQOH2HfceOhXnVbVLWGj8+48yraKOtPR/D2dns9pq8ddkfE3ZvUuhxOA1FE531FbCLxvHQ/dPkuPGH+IuMRc4m+t19Kdl3btRY7QN4d4yhjq6R7e772VocQOhvuud7Z/2fpcJp5OKuCpJMQwZw7ySmY7O+Bu92W+JvluEo3LeVLdb+fr8iaFy5ZjLdb9v/HevgeGOpTsacf7VAY2s8IFgOQUL6iTZsrx/qKVPKXXY6+be/Vdyb5nfFsryl08pcRYDQDoEjCFPK2xzW33QlwA3VzRFcxWR07x8DuWoTufdFHEW628TvwUkllkcbzmcHXtbQ2UndR/x/wC7/hU34i6KTLBlDALagG566pfTZ5De7B/oCgF6OJrSbX16oMRkADaWF3gb4nkfad/xso6Spe6Qskte1xopJou8d3gHkVVlWU2wcyVMyBWWRtFl6P2V9jGK9pNQKoudh+CROyzVzm6vPNkQPxO89hz6Krljcq5Y3OT4K4axXiPGW4XhGHzVs8wuWxt0YPvOOzR5lfSHBf7N2AYW+DEeLXx4tWsFxSNJFNGejuclvYeRXpHC/DGB8CYU3CuH6FlND/mP3lnd957t3H8BystJ0jG+J47x/JvIeqybctjJycti9SBkNMyOCKKnpYhlYA0MYwdGtH6J3YpHEbUsed/33D8gqAE1UQZHEjkOQV2CkaOS0jTwaQp4IHuqqt15JHEdBoFLFQjmrrIgFK1gtstUjVJIrMpQOSmbAApw30T6dVJJEIwn7sKUAFSCAnmApBW7vyS7tWvozuoTGmeNrFAVsiISyM2cbdDqpHQvG7T7IC1ALvI5NJGtaeo0TmidbNE648igLLpmOdEbtJCjADbPLAbOBIH4KzFVsl3OqibUsl8MzbHk4IZaQN8bDp95v6hRjGwOJ4y7EuGuJhPVUNNFhWIzHM6enYAyV38bBofUWK+T+0jsz4l4NxqQY7Q5YJHZaepi8UEjRsGu5HyNivuNlXJA4B+x2PIp8Sw3DeIsOmw/EaSCrpZ25ZIZm5mu/wCfNVaTZB+dT6LLpZVZYA3cL6B7Xf2fKzhJs2NcMtmxDCG3fLTHxT0g6/xs89xzvuvB6yRgbca+irqnqB6TJNFlv4ovyWfWUN53GItDTqbnYqXDO8lqXvF2Ma0h1ud+SkmnpIZHMmklDgARkYCPfVSiCiKDKPiaT6oWwCEE7vOnoEUtfADZjZXDzACBkwqMzh4bHYm6uiStWy2AiG+7lUVupgvKXXvm11UX0d3kpySQgkahWqWbN4Hb8lEYCEoo3Z8w0tzQkvyuzZSywdazroO4kdqXN+ZRQmKOxqHPAdtlFz+astdQPOUTT3/+GP6qrZZJleNnd3zWvyQ1kvdsELdHO1f5DkFYPdtmAgMjsupztAWhhfCE2JTPrq6Y0uHXzd6dXzeTBz9ToPwWdSrCmuKbwjpt7arXmqdKOWzHwzCKvGaj6PRQOleBdxGjWDq47Aeq67D+GMNwVzZJ8mJ1nJpB7lh8hu8+unktSgZPWvjwTh+iyRk3EbN3W3e9x6c3HQeS05cdw/gxpgweSHEMZtaXEyM0dOebYAdz/wC8P+m268qrc1KrxHRfE+3sehra0SlWXHU/9V9/b7EXX4LHRsjruMa2SiYWh0WHRW+kvbyuDpC3116NKp1/apVU9BJhPD9JDhWHu0MVPcGTzkefFIfU28lxtVVzV8zpZ5HyveS5znuJJPUk80oaUvIsFnGCgtT15VKlaSUdX52Wy8dX3kU89ViExkqJXyOPU7eis0+HOdqRYea0KekZGAcoJ6q9BSySfCyw6nQLKdxyiepadD5fHVeWUYqFjOVyrLIQOSviha0eOUE9Gi/4rZ4b4Zix2rdAattPlFzcZnEeQXLxOTwe6ranQg5yWEjnRFpsnEOq9twbst4biDXVIqKx3PPJlb8mrsMN4K4ZpbdzgdBcc3xB5+brrphZVJbvB41x+pbSjpGDl7l59x8yth9EXc+i+vaPCMNjAEeHUTfSBg/RXf3Lh04tJhtC4H71Ow/otl0XJ/3+B5kv11Sg/wDB/wC34PjYQp+5X17U9nPCeIX+k8O4a4nmyEMPzbZc7ifYDwhXBxphXYe87GKXO0ezgfzVJdF1Vs0zpofrzo+TxVhKPua+efgfN+F4tieB1AqMNrqmjlH2oJCw/huuri7R4sVAi4twOkxcHQ1cIFPVDzztFnf6gV1uO/s7YxRh0mD4jS4iwaiOX6mT8btPzC81xvhnFOH6k0+K0FRRy8hKywd6HY+y55Qr0PWWnw+x7lC56K6UeaM05d2kl8pGxL2ecP8AFhMnCOMMFS7UUFblgqL9G65H+xB8ly01BxFwRiRbK2roqmB2+rHMP5hAQ5hu0kEa6LrsK7RJpKRmFcU0gx3DmjKx0jrVNOOscu/sbhVVSM1iWnyFWwr0HxU/Tj2aKX0jLwaXiy9R9pXD/G1E3CO0jBIsUjAysxGNobUxedxv/wB7rh+Of2fp6Gjk4h4HrG8R4CPG5sWtRTjo5m5sujxjs1jxSikxng6sGLUbBmlga3LVU388fMfxNuFz3DPFuNcGYk2ooaqWnkabOA1a8dHDYhddO5qUt9V59/nU+YvegLW9TlQ9GS5bJPsa3g/Zjnwvc8fqgW+AtLTfUHkoLGy+oMT4Q4J7cqZ0tGKbhrjEtuMoy01a7zHIn5+q+feK+EMY4LxibB8coZKOsh3a4aPHJzTs4HqF7FGvGpHMT88v+jqtpVdOqsNefau9ae3QwNQb9FeZaSPycFTcFPSSEXjPqFsea4jNGUkO3CkDwdFL3bSblgJ804jZb/Dahm0QtbmfmOwUNbJq2MctSroa1g6NGqzHXkeXncm6sjMBLUahHkSIUgtstNED1GqhLLGx3CekfZxYdt1cEbTrlaSedrqCrKeQKSGIA5j7KwYx9xvyQluQaDbkoyRkrVbtRGOWpVfIVJ3ge4kjfmkS0BSSR5iwgjdMRnQuNzdG14AAUkjd2SQBqSr8TBGwNChpWX+scPRa+C4RPjeJQUFOPHK7V3Jrebj6BRKSissiclFOUtkbHCOHxwRzY7Wi1NS3EYP23+Xp+ZWZW1kuIVUlVMbvkN7dByHst/jKup4Xw4Bh9m0lCAH2+3J5+n5krmlhQzL+WXPbwOW2zPNeS1e3cuXv3HTOKdCd10HWMkldJAJKyeyRCEgqliU+Vohbu7U+iuyPbEwvdsBdYrnumkL3bkoAomKxFGZHtYNL7noFGwWCv00WSLOR4n/gEATyNGgWaNAhREJrIBJJ7JWQGiAnCeycBAMlZFZKyAGyQRWSsgBskismQgEhdt2dcPQl83E+LERYZhoc9rnbPeBqfQfmQubwDBKriLF6bDKNt5J3WLuTG83HyAXW9rWM0uFQUvA2Euy0tExr61w+07drD5/aPmQuC7qSlJW9PeW/cuf2R5t/UlOUbWlvLd9keb9uyOB4t4kn4gxSoxWa7DMcsEf/AEoxsPlqfMrmXGwUtTMZpS77I0A8lXe4LthBQiox2R6FOnGnFQisJAm73BrbknSy36SnFLA2Mb7uPUqhhFHe9S8aDRnr1WqFcuJMnSUAYqaio31tQ2Fg31cegUG50WtXzDhnBSTYV1ULAc2BZzljRbsyqz4VhbswuKcSbJM2gpz9TBobcysBJzi5xcTcnUlMrxjhYLxjwrA41KMaIQEYUkhN9Lr6s7FuAP7H8LNq6uLLimJBs0194mbsj+RufM+S8g7Cez4cXcR/vOuizYZhbmyPDhpNLu1npzPoOq+p8ui+d6Zus/wR9v2Plun73P8Apoe36Io1k8NDSzVVRI2KCFhkke46NaBckr5K4y4mn7ReMZ8RfnbRxnu6WN32Iht7nc+q9R/aK47dTQRcH4fKe+qQJa0sOrY/ss99z5AdV5NhVK2jphceN2616ItOrh10t3t4GnQVj1cP3E1q9vD8lxzmQRWGjWhYs8pnkc87lXK+bMe7B9VRIXtxR9FFAFT4fh1Vi1fT0FFEZKiokEcbR1PXyG6hXo3BMUXA/CdZx1XxNNRM00+FxP8AtuOhd72+QPVY3FbqoZWreiXeY3dx1NPMVmT0S7W9jP7TK2n4dw6j4GwyQObSgS10jf8AMkOtj+Z9hyXnjQLXJ0CKoqaiuqpqqqldLPO8ySPcdXOJuSgkZnZlBtfdKFLqoKLevN9rItqHUU1FvL3b7W92VZJBJITsNgijY6R7Yoml8jzZoA3KYwtDsrX5nbAAblez9l/Zrh2FYJLxvxv/AHXBacFzI3Gz6t3KNvlfc89hpdTWrRpxyWr140o55mRwR2VQuwqTibies/deA0+slUfjnP8A04AdzyL/AJdVzvHHH/8AaFkeEYNSNwnh2lJ+j0MZ+I/fkP2nnqUXab2nYj2hYm3wijwml+roqCLSOFg20Gl7Knwl2f1/E1NPitRNFhWBUZ/vWK1VxDH/AAtA1kkPJjdfRUpUZSfWVd+zs/JnRoSk+trb8l2fk5hkT5XhkbXPc42DWi5J9FPU4bNROy1doJOcbvjHqOXuuixbHMJwoPouE4KiGPZ2I1JAqqgeQGkTT90a9SVyrg+RxcSSTuV1naM7L9m/umRiCQtzZTlvbNbS6FzS1ACnTJIB0ySSAdOChToCxE7Vdt2a4Q3F8dZNOLwUtpHA7F3ILhYzqvYOzU0GHYXHmqIO/mOd47wXHQK0SUexYWxrmhdFSUodZcthNW1zQWeIdRqupoKoG11oWNanohpomxbhTCOI6X6NjGHU9bFaw71vib/K7cexVyieHgarYp4Q8DRQyD5543/ZymhElXwpMaqPf6DUOtIPJj9nehsfMrxHEcDqqGpkpqqmlp54jlfFKwtcw9CCv0AZh4cNly/HnZfgvG9GWYhT91VsbaGtiA72PyP3m+R/BV0ZGD4ew+tr8Br4MQw+plpKuneHxTROyuY4cwV7XwlxXRdpEdRFSQ0VHxVPHauwiYBtBxE0cwP8qfoRzXBdovZ1jPAmJfRcShzwyEmCrjH1cw8uh6tOoXEsE9HUx1EEj4ZonB7JGGzmOBuCDyKpKPaUazozsOMOD/3RBNxDwsat+FwS9zXUdQ0iqwmb/pzDm3o/YruuxTtur8EqGUFbIaijeQ18TzsOoW12d8Wx9oYkrGikHGVLT91W0s9mwY/Sj4mycs/n9k67HTzTtH4Lg4Vnh4n4ZE/9nq6VzGskFpcPqGnx00o5Oab26hcVegprTSS2Zw3FtxrTSS2Z6p2ydgdBxNQScc9n8bXmQGWrw6IfHzL4xyd1bz5L5pli7h2bZzTsvbux/tyrOHsRip55HPpXkNljJ0PmPNdF299jVDi9N/8AiNwhG11HMO9xGkiGgP8A1WgbfxD36rGhWfqVNGuX1Xd8vAzt679SppJecru+XgfObhcAOaQCL2Ub4Y3fYP8AuVjED3Ba0Hx7qlJXznm0ejAu+Lyd8JZWQu6Y03DTceaUriInWGp8N+ijFXI5wD3XbfXSytANcC2+jtvVWLme2Ankpmxlg2VqJrRyRua0qGyGyoCGODtiFrwMjnhD2nwuH4qg2kNQ8MYLkr2zsQ7Gf7TkYzjUbhgFK/wxnQ1sg+yP4Adzz26rKc1FZM5zUVlkPY32EVHFxi4g4lD6bAWuzRQAkSV9jy6R9XbnYdV9NsdBRU0NFRQR01NC0RxQxNDWMaNgANlFNUhjWxxsbHGxoaxjBZrWjQADkEEWZ58z+CyinN5ZlFObyyy152bq47lWKemubnUp6enAtor8UVl0xjg6YxwPDCGqy1qFrQEWZXLhggIg5RZvNLMpBLnTF6jLk2bzQE7XeIequtKzA+xGq0GP0QE4SQgokAkzmNd8QBTp0BC+mYfh8KryQPZuLjqFeS3QGW5qeKZ8B0Nx0V2Wna/Vuh/BUpIyw2cLFAT2jqGksAP3mFVnNdTHOwkx31B3b6oA50bg5psVcZI2obcWEg0IOx/4UNAKCqbM2xOq8E7cf2dIsbZPxFwbSNixG5fU4fHoyp6ujGzX+Wx9d/bp2fRz3sQIaDZzfulWaWsErbHVUfYyD4ElwEYVSuikGV0dzJcWObmP0XI1UbXyve7UuK+wP2huxufiPC5+IuGIQMSi+srKaMf+LjA1c0ffH/mA6r5Klo3AXKpqtxgyHwjko4vqZQT8J0KvyxBqpTkDZXTBakjFiPcFR91Jl8LCUow8Rtzam3yCJpaRm76ED+cKSUQmGQHxtLR5qaKEOIaLAbk9BzKTsuUlssZt0co5O8MMjWaX36kdELIrzy97MXN0aNGjoEIeW6oRsu94B4NiqIv7Q4uxooIPHFFINJjyJHNt9h9o+QKwuLiFCDnM7bS0qXNRUqe7+AuF+G4YaaPGMejPdFuanozoZxyc/ozy3d5BaEs1RxDXOa17IomNzSSOGWOGMczbYDkB6BNiuITY5XFkbrl5OrjoBzJPIALPrapoh/d9E4/Rmm737Gd33j5DkOXqvFc51pcU9+zkj9FtLSnY0urpat7vm39i5iGOMZSuwvBw6Ch/zpSLS1ZHN55N6MGg53OqwxGXHyUjWnYbfmrUEBeQ1rbkrTKgjelbuo8EUMFzstakonEA2sOpUtNQshs59nO6cgrZfZcVWvxaI+qsOjI0lxVBRRRxa5Q49SpXSE7lQF6HOufDZ7CnCCwixnVzCcRdhuIQ1LTbK7xeY5rL7yyXfKUmnlCdSE4uMtmfQGD4g2RjHB9w4AhdVQ1LSBqvF+DMec+gZG913RHIfTkvQcOxYEDxL2aNbKR+b9KdGuMmkeh0kw01WrBIDZcNS45TxWMk8TP5ngLYpOJsPcQPp1Jf/wCM3+q7oVUfI3NjU3SOvisVOGArFo8TinA7uWOT+R4P5LSjqOtx6rpjJM8OrSlF4ZM+EEKjiOFUuJUz6WtpoaqB28czA5p9ir4mCYvBUtJlITnBprc8b4x7AsPrmvqeG5/oM+/0aYl0LvIO3b+IXiWPcNYrw3Wuo8WopaWYbB48Lx1adiPRfZkmVYnEGCYdxFQvocUpI6qB2wcNWHq07tPmF5lz0dCesNH8D7roT9a3Vs1Tuv5If+y9vP2+8+RMNxWtwStjrcOqpaWpiN2SxOyuH/HkurqqzBO0hmWujpsH4jd8NU3wU1a7o8f5bz94aHmrvaH2R13CokxDDnPrcLGrnW+sgH8YG4/iHvZedjReNJToPgmj9Kpu16Tpq5t5a9q3Xc1zXc/FcmDXUGJcM4lJTVUctNPC+zmu0LSP+916VhvEnD3atgkfCvaBbvmDLQ4w2wmpncg48x6+/Vc3BjdNxBQMwniJxvG3JSYja8kHRj+bo/xby6LlMQoKrAa99PPYOYdC03a4ciDzBGt1pTquEuOm/Peebf8AR1O6p9RdRw1s1y74vs7U/B50b57tL7L8Z7McaOH4owS08t30lbELxVLOrT16jkuWgja1mf7TtvRfSnCPFeDcZ4AeBOOW/SMLn0pKwn6yhk5FruQ/+2y8d7SezvE+zHG5MJxFokY4ZqSqYPBUxcnjz6jkV7tvcRrRytz8o6W6JrWFZ0qi03T5Ndq+q5e44r6e8AtayPQ/EW3JSGJSAWMUV+uVAYwFGYzyXVoeG00W4JnTAl1s19QBYKu6Lu5S22m4TUz+6lF9joVcnh70tykAg8+ikykiARCyCWA2uFbEJH+Yz8UnMy28TXBMlMlaCHI3xaE6nyCjFfOwuEUz2NJ0AKsVJyQE83+EenNUAyykjcttxOdzcskjz53UsBBadb21uVn5SjgkMUgN9DoVGA12BzRZJDbY6hQyG2is1DtNDqqrmuJ1VkSgEcTO8eBy5oS0hWYmZGa7ndSSThwA00AXpmDQN4F4KfjUzQMWxUd3SsdvGzcG3p4j/pXP9mXCA4sx69S22G0IE9U86NIGzb+dtfIFT8c8Sf2nx6SaE2oaf6mlbsMg3dbzOvpZefWl11VUFstZfRe35Hl3Ev3FZW0dlrL6L27+BzupJJJc4m5J3JTorWQvcAF3HpAkoSQge9CMxcBbU7DqmQS77JxotnCeCuI8ZymlwuZsZ/zZx3bPmd/Zdvg/YuzSTGMUcTzipW2H+536BcdbpChR9aX1OG46TtqHrzWexas8yCVl33aLg3D3DVNS4XhdG0Vkp72SZ8hc9rBoBr1P5Lz2pl+jROkO/IdStreuq8FUisJ9ptaXKuKaqxTSe2Shic+Z4hadG6u9VWjaoxd7i46km5up2Cy3OosUsHfyhv2RqfRaM1mnKOW6moaT6LRuqJBr+ZVUkuJJ3KhPLK5yximsiSCksDZQ1k/cRafE7QKysernNROSPhGjfRAdTZOAiSsgBTp7JrIBJJ0rIQCQmtzRW1XbdlvBreKcd+kVjQMLoLTVDnaNeRq1l/a58gsq1WNKDnLZGVetGlB1JbI3uHxD2WcBTcU10TTjGJtEdDA8agHVot/5j5ABeK4rVzzPkfUSumqah5lnkcdXOJuV2fafxuOMuJJauJx/ddBeCiZsHC+r7dXH8AF57K8vc57tzquezpSSdWp60t+5ckctjQkk61X15b9y5L2ELzZNTQOq6hsTdL7noOZQPctzC6P6LT53i0kmp8hyC7T0Cy1jY2tYwWa0WAT2RWStogGshIRKxh+Hz4pWxUdOLySOsOgHMn0UNpLLIlJRWXsXuHMPje+XEavw0tKM1zsXf8f0XJcQ4w/GsSkqHaR3yxt6NXV9oGIw4TTw8OUD9Ihedw3J6H81wCxo5n/I+e3gc1vmo3WfPbw/Ik4STroOocK7hGF1WNYlTYbQxOmqqqQRRMHNxP5KmAvoX9m7s+MUEnGNfF4pM0NA1w2bs+T3+Ee65bu4VCm5v2eJx3t0rek6j9nier8EcIUvBPDVHgtLZxhbmmltrLKfid89vIBPxtxXS8E8N1mNVdndy20UV9ZZDo1o9T+AK6AgjQL5c7cuOTxpxW3A6CUuwzC3FhLTpLNs53oPhHv1Xy9nbyuq2ZeLPj7G2leXHp7bvz3nDxVNXxDi1VjWJSOmqKmQyPc7mT08uQ8gr08wY0lBGxsEQY3QBVp353W5BfXJckfbxilotiFzi4kncoSnKE3vYAknQADUqxc6HgLg+fjXiKDDmhzaVn1tXKNo4gddep2Hqp+1ri+DiPH24dhmVmDYS36NSsZ8DiNHOHlpYeQ812uNVDeyPsxjwmIhnEvELc9Q4fFBERY6+QOUeZceS8Ray2gC4aP81V1n6q0X1f0PNoL9xWdw/VjpH6v6IR8DS47BQd893kinlu4MHwt/Eru+x3syqO07imOh1hw2ntLW1HJrOg8yuupNQXEzvqTUI8UjqOwvsnp8ajm4y4oP0Xh/DwZM8nhExHIf1XPdsfajN2hYs2no/wC64HQ/V0dKwZWho0zEdfyXZ/tC9pVE6Cn7P+FC2nwbDQGSiI2ErhpbzC57se7O8KloantA44aYuFcLd9XC7fEqgbRNHMX367dVy0KbnLrp+zz57TkoU+OXXz9nnz2jcCdk2H0XDv8Ab7tEfLRcON1pKFnhqcVfyawcmH73ToNVy/H3aNiPGlXDC6CHDcKogWUGFUoywUbPIfaeebjqtPtL7T8T4+xh1bW2hjaO7oqJmkdHD9kAfetb8+luQwvBavGq6GioaeSoqqh4ZHEwXc5xXcsncnkpRUz6l4bG1z3uNg1ouSei9V4N7FapzY67iVroIz4m0TTZ7v5z9n0GvovTOznscpOCIGV+INjq8Zc25fuym/hZ1PV3yXXVcYsbhaqJdI834h4Tw6uwv93MpIoIGCzGxNy5PMLw7ibher4fqXMmaXRE+CQDQ/8AK+lMUblBsF5dx7j2E0UL6Wsy1E7hpTt1PqTyUySJZ44d0yOQtc9zmtyNJ0be9kCyKiSSSQCSSSQBx7q1G4AqtHujDtUBuYZjdfhzw6jrqmncNjHIQu8wDti4nwxzRNPBiEY+zUM1/wBwsV5aySxVuKptzV0ycn1Hwh25cO4gWQ4q2XCZjpnf44Sf5hqPcL1/CsWpquBk9NURVELxdskTw5rvcL4JhrepXUcI8c41wlViowjEJIATd8JOaKTyc06fqpyD7xoaiN4GoVuWNkjdLLxDs97dMI4l7qhxDJheKO0DXO+pmP8AC47HyK9QhxvXK4kKMEkfFHDWF8SYTPhWLUramkmGrToWnk5p5OHIr427Vuzat7PcW7l5dU4dUEmlq8ts4+67o8dOe4X2q+pbM3cLneLOF8K4uwWpwjFYhJTzt3HxRu5PaeRCENHwbQ4pW4JiUGJYdUPpqumeJIpWHVpH6dRzX0BhPEuF8YcOVWPVUDZMLxBraLijDo9XwOt4KyMfeZa4O5aCDct18d464MrOCsfqcHrxd8RzRygeGaM/C8ev4G4WdwnxbWcH4s6pp/raaeMwVVOT4Zozy9QbEHkR6rOSM5LJa4x4SrezjiaXDZ5WzMFpqWqjN2VMDtWSNPQj9V7d2D9szKRwwbFC2SknGRzX6jXTZeeSzxdoPCNRgMhviOARvrcJkOrpqEm8kF+fd/G3yzDkvO8JrX4VWNcHlr2O5FcFzR6z0o6TWxwXNHj9KLxNbPz8T1D9oHsldwNxGMZwpvecO4sTJTPbqIH7mInpzb5ei8jfGAvr/s2x/Ce17gKr4Hxx4c6WIiB51cx41a4eYOvzXyvxTwxiPCXEFdgeKRllVRymN3Rw5OHkRYq1tXVSPY+zsfn4F7auqkU9n2dj7PPIwXt6KalfmbkJ1CGSwRQsyDMdyutM7Ey62Fj3XL8l99LozSNO1T/5CqLq0wyloY2QDrfdaeBRYjxBi1JhOG0cctXVytiiZYnU8z5Dc+iiWmpEtNTvexnsxquPuI+4cXDC6W0lbUgFvh5RtP3nW9hcr6zkkpqGkhw6ghZDR0rBHFGwWAA02VDhPhWh7N+EqXAaKzpy3PUzWsZZDu4+vTkAAp2R99JbquNZqTycabqTyPCx0zrlatLTActUVFh5c29rNGl1fytj8DPcrrisHZFDRxAbqYaBACldaGgeZLMo8yWZSA8yWdRF6bOgJS5NmUWdLOgJQ62qtMrWt5EqhnThyA024g37rlIzEIjuHD2WUHog9AbTKmF+0gv5qS+mhWFnUjJnMN2vI9EBtJLPixFw0kAcOo3VyKaOYXY6/lzQBppI2yts4IgkUBl1MLoXa6jkeqgDnMdmabFbL2NkaWOFwVk1ULqeTKdjseqAlbOH6uaCQLEdQqsrfokocw3jdq0/ogzFrg4HUIhI14MUmjHbH7pVWgadLVNlaAd+S+Y/2juyF2DVT+LsBpSaCqk/v1PE3/w8rj/iAcmuO/Q+q+hYJXU8pY7Qg2K1J6emxegmo6uJk1POwxyxvFw9pFiCqb6Mg/OOrw6pbe8L/wA1likLp/rAQGakHmvXu1Ls8quAeJ6jDbh1FJeajme4DvIidAb827H08157V05LrOe0kfdcD+SqnjQkxKuQRRH7z9B6cyswhXq5rn1BDhbKLAeSrmIjdaJkohFx6LQp5szGu5jQqk4W5K/gGHVGLYnDQ0zXOfO4N0F7eaickk5PkbUqcpyUIrLZ0nAnAs3FOLhro70MZzOcTla62tieQA1ceQ9Qus41x6nnczC8OLW0FKMoLRYSuAsXW6cgOQXR8XGk7PuHI+FcMIbXSsb9PkadW8+6v66u6n0C8rc4vfqb21K+b43d1eul6q9VfU/QOi7SNrSWmW+fb+Oz38ybvnxQvjj0dL8Z55eiGNhAt1RQsc921yVqx0AhbmlF3nZv9VtOaie7a2kqryinT05eQAFqQxMhbZo15lC1mUJ7lcc5uR9Ha28aKzzJC9D3h6oCUDn2VVE3nWwSl/mgMihL0BerqByyuCcyeabvFAXps6twGX7hmpRYrUUGYU8uQu30U0mNV8+klZO4dM5sscPUgfZVcWawrp7l8VDnG7nF3qbqaOYcwFmiVSCXzWbgzup3SNmCsdEbxvcw9WOI/JdDhPH3EuEW+hY7XRtH2HSl7fk64XFNnspW1HmilKOqeC9SnQrrFWKa71n5ns2Cdv2O0pazFaOjxCPm5g7mT5i4/BeiYD2wcMY9lj+lnD6h2nc1lmXPk74T8wvlptSeqlFVfddVPpCtDd58T5+9/R/R1zrCPA/9v2292D7M+mBwDg4EEXBB0IQOqWuXy1w12h45ww4No6x0lNfWlmOaM+nNvsvYOE+1DCeJQ2Fzvodcf/Z5HaO/ldz9N16VG/hU0ejPiekv0jc2WZx9OHavquXxR3shEgINiCLEHUELwHth4KoOHa+nr8Mj7mGszZ6cfCx4tq3oDfZe0nERyK847ZpfpGG4eSblszh/5VW+UZ0nnkb/AKWnWt7+Ci8RllNdujPFcxQ1kj6qBkUji9sYswndo6eilnYA42Vdzl4CynofrVVKSwylBUGlktfYr1zBK7DO1/hL+wPEczYq+MF+D4g7eGUDRhPMHbzHoF5FWQl5zNGv5p8KxCSgqY5WPcx7HBzXA2II5rtpVHB9ZA+V6Tsad3TdrX2/q+x+d1zRx3EPD2JcL41WYNi1O6nraOQxyxnr1HUEag8wVnFq+l+0bAoO2js8HFmHRNPFOAw5a1jB4qynHPzI1I9x0XzTcWuF79OopxUo7M/H7y0nbVZUaixJPD8/FdxXlYXEBo1KsmbuWgvu4beaeCMvu+3kFBWOzPyAaN39VsmedNGjDLRvZmL5fSw/qqstXC+TJEx9ibZnEfkFRDD1SylhupSMcFuqiJYHc2/kq4Yr0MrZogT6EKIRgEg8kyVyV8qB7bkNHNW3xAjQEKu5pjvfc7ImEwJntuALm3MqPOhJubpAFxAHNWwXJYW5zc7BW4IJKqaOCFjpJZXBjGNFy5xNgAomNyNAC9X7GeGaWghre0DHRlw3CWn6MHD/ABZtiR1tcAfxHyWFzWVGDm/Z3vkjmurhUKbm/Yu18kX+LYouzTgak4PpJG/vbEm9/iMjNw07i/nbKPIHqvM26DZaON45VcTYzV4xW/41U8uy30jb9lo8gLBUst9lna0XSh6XrPV+JjZW7o0/T1k9W+9/bYFrHSvbGxrnPcQ1rWi5J6BdHh3ZXxRihDn00dDGftVT8p/2i5Wx2U8MvrcTkxqoZeCkOWG+zpSN/YfiQvXDM2FhfK5rGDdzjYD3K8vpDpWVGp1VHfmeR0p01OhV6mhjK3feedYP2J4dTuEmLYhPWu5xwjumfPUn8F3GFcNYHgbQMPwulgcPt5Mz/wDcblZeLdpvCuDhwlxJlRI3/LpWmQ/MaD5ricW7bp6kOZgmEsiG3fVbsx/2jT8SvO6q/u/Wzjv0R5LpdJXvrZx36I9bcQ/W91hYvxbgODXbV4rTMkH+Ux+d59hdeGYtxTj+Ok/vHF6h8Z/yYnd3GPZtlmQwsjN22v1XbR6B51Ze7z9Dvt/01zrT933f2NHHcSqcdxiqxKa4dO+7W/cYNGt9guaxGo76buwfCzT1K066rNNTkj43aNWENSvoYRUYqK2R9VTgoRUY7INi08HoJMQq2sY24BuVnMaSQANTou7w+kHDuAfTHgfSKnwxg768/wBfkq1J8K03ZWrU4Vpu9jMxaYCQUsfwQ6Hzcs8BG4lxJJuTumsrxWFgvCPCsDWTgJWRtaCbuNmjUnoFJYpYjN3MIYPik/ALNiZfVHVzmrqHSWs3Zo6DkjjbYIDqQnTWT2QDJ7JWRWQgayayKyewKgBUlHUYhVw0dLEZaid4jjjaNXOJsAvUe0msh7OeCaLgLCZWnFMQj73EZ2btjPxG/wDEfCP4QUfZPhFDwzg1f2hY4y0FIxzKJh3e7YuHmT4R7ryjibHavGsSrcar35q2vkLiOUbdg0eTRYLzpf6mvw/1hv3v8HBNfuK3D/WPxf4MGslDnCFlhHHppzKz5XKeQ5QquV88rY2C7nGwC9I70W8IovpVQZJBeKPU+Z5BbztdUFNTNpIGQs+zuep5lSFCQCEyIpFABe2q7bD4G8D8Jy8Q1rQ2trBkpInbgHY/r6WUHZvwj/afGTPVNDcMoAJql7vhPMM97XPkCuY7UOMjxbxDIad1sPpSYqdg2IG7vf8AouGrLrqvUR2WsvovaedXl19VW8dlrL6L2nJVdTLWVElRM8vkkcXOcdySokycLv2PRSwJEmTtFyoIOo7OOCqjjziqkwiHO2AnvKqUD/DhHxH1Ow8yF9qUNBT4bRQUVJE2Gnp42xRRtGjWgWAXAdhvZ6eCeFG1FZFlxXEw2aouNY2fYj9gbnzPkvQa+upsLop66slbDTU8bpZZHbNaBclfK9I3PX1eGOyPjulLv9xV4Y7LRHnvbj2gDgjhR1PSSBuK4kHQU4B8UbbeOT2BsPM+S+ZsKovo8PeSXL363O61eL+KqntI4xqsbnDmUjD3VNCf8uIfCPU7nzKgcQ0eQXuWVt1FNRe73PoOj7RW9JRe73Ip3ZW6blU3KWR2dxKjK7UeggCV6J2RcL0tTV1PFuNFseDYIDM5zxpJKBcDzy6H1LQuHwnCKzHsUpcLw+PvKqrlEUY5C+5PkBcn0Xfdr+MUvDWE0PZvgkgMFE1smISt0Msp1DT7+I+w5LkupOWKMN5fBczgvZyli3pvWW/cub+iPPuNOKqrjTiSsxmpu3vXZYYyf8KIfC35b+ZKw5pe6Zp8R2UlsovbZU5JDK8kj0XTCKilGOyOynCMIqMVoi3R0dRiM8NNTxGWaZ7Y42AXLnE2A+a+m+KXUn7PXZHBw/RSx/2jxdmaqlb8QJGvsNguQ/Zf4GiqsSruOsYYBhmBsJh7weF01r3/ANI/Erz3tP4tr+0bjWrr3PdIx0hZBHfRrRtZcdT+Wp1fJb+fh7zjq/zVOr5Lfz8PeQdmnBFT2k8cUeDmUtgkcaitqXH/AAYG6vcTy00HmQuz7ZO0jD+IMThwfA4GwcK4BGKfDqVmjZXbd4R52v1yj+JaHC1PD2e9jdfiTSBinErxTd4N+4BOWFp/iILnEfZAH2gvIK0tkm7oODgwnM77zvtH/vkF2xaex2xaewFHR1GL10cMEclRVVEgaxjBd0jydAB1X1z2TdjsPZ/hbausaybHaln10u4gaf8ALZ+p5+iwP2ceySPDaOPjDFIP79Ut/uEbx/gxH/M/mdy6D1Xv4oLR3K2Swao5Sqpy1puuaxLw3sF2OMNyAhq8I7aO0c8NxOwTDZR+9J2XlkadaZh/+Y8ug16K2cEnN9pvaa3C5JcJwd7ZK0eGacatg8h1d+S8RqJnzyulle6SR5zOc43JPUlSTyFziSSSdSTzVcrNvJUZMnTKAJJJJAJJJJAGw6p76oWp0AQdZSNkKhSvZAW2TEc1Yiqi3ms4ORNkspyDegrb2BK9m7Mu2qbCxFhPEU756PRkNW7V8PQO+83z3C8BjnIKuwVpbzUpk5Puyix6OaNj45GvjeA5r2m4cDzBV11YJW6FfKvZd2pv4fmjwrFJXOw2R1o3k3NO4/8Ay+XJe/0+OxloAcCCLgg7hWJOf7a+A28acMSVNMwOxTDgZYCN5Gbuj9xqPMea+RKlpjdovrDtM49dgGCugpJP7/VgsiAOrBzcvl7G6cxu722/xevVVkVZe4X4unwLuqqFjDX4fMKile4XDmnSSJw5tcDt69Vi1UsVXI+ojYI/GTkGzWk6D22VNsmV4cOSdjgyTX4TofRZOOuSjjzPQOzPjGXhfG6aqjkLQx4J1XuH7Q3DdHxrwnhvaHhEcb52RiKtsBqzk4+bT+B8l8q0sj4pd9QV9Tfs941DxXw7ivBmJOEkVVA4Ma49RYry7mDo1Oshz+fL7e08m4g6NXrI/wBvny+3tPmurw/wiQhgseRGvsqj3CIX5rV4t4eqOE+IK7Bam4kpJSwH7zfsn3FliTOMrWnmNCvQpy4opp6M9KnJSipJ6MFgDnE2X1P+yv2aswzDpeO8Vpx30zTHQNePhj5v9XH8B5r5+7N+DqjjTi/DcEY1/d1EmadwHwQt1cfloPMhfeVTFFhOHUmDUcLY4qeNrQxg0bYWA9hosq89eFGNeevAvPZ57ihVzOqp3SOuSStDB8MFQTI/wxN1c5VKKB9TUNia3Umy6Wfu6eEUkQsyMXkI5laU4YRtShwognmDQBGMjQLMb0HX1UANkLnd48uJ3WhhtEJSJpB4B8I6lbJGyHpaMlofIN9mpp6Mbs0PRahChkCsSYsgLDYixUZcrFbO0nI2xtuVSLkAeZLMo86bMhJJmTFyjLk2ZASZrJ86hLk2dAWBIiEirB6cPQgs94i7xVc6cPQFwSI2ylpuCQRzCpiREHoDYp8S+zN/uH6q8Hgi4IIK5wPVmmrXQG17sO4QG3oVXrw00xzDXl6p46hsjQ5puCquIThxbGOWpQFA6IHai3VG6xQEISQve59ifibpfqFeoKktcBdUXizg7lzRlroHtIN2PF2lZyRLRzvbh2cx9ovBkrIGNOK0IdU0TrakgeKP0cNPWy+IwY2vcwOuRo4EWIK/RWgnL2ZefJfG37R/Z3/YztFdiFHHkw3HQ6pjDR4WTf5jB7kO/wBSo9VkqeT4jEwFsgtroVnuAK1nsY6J7JNR+qqSMazQSM+SJl4ozXsAOugXuHZNgFNwhwvV8eYjG3vIz3OHsePjmtfNbo3f1t0XmfCfDL+Ksfo8Ng+tfLI1oaBuSQAP+/Neq9seM0lLU0fCeGS5qDBohDdu0ku73e5uvK6TqueLePPfw8/Q+i6GtOOam+efdzft2Xt7DzvGMUnxOtmqp5C+SVxc4k7kqvTxueQACXOO1lD/AIkoC9X4B4bh4Y4cfx/i0TZHtkMGD0sguJp/+qRzazfzIVFFRjwrY+yg+KWngl38l52WWZTuHIeE6NoxJoOLTRiR0P8A+0YdQHf+8cOX2R5nTAe50she75dFoY3UTy1knfyPlnc4yTyPNy6Q6m5T4Bg1Xj+K0+G0bM00zrX5NHNx8gNVxSblLQ+sowjQpYm9tW+X/BZ4W4YquJa0xRgsp47GaYjRo6DzK7qv7P8ADDAI4onRFosHNOp9V6LgvClHgGFRUFIzwsF3PI1kdzcfVQ19BZpsF2q1SjrufOy6clUq/wAbwjwzGOCq2jLnQOEzBy2K5idkkDyyVhY4bghet8b4vHgFJs11TLcRMP8A6j5LyCpnknldLK4ue43JK5nBJ4R7Ebh1KfE9wS9AXISUJcrJHNKoGXJZlHdIFTgz6wmDkTXaKC6IOUNF41CfMiD1XDkQcq8JvGqWGyIxKqociDlVxNo12i2JvNGJj1VIPRh6o4HRC6ZfbP5qaOoLSC0kEG4IOoKzBJ5qRstlRwOund9p6bwt2oVVLkpMWkdNFs2oOrm/zdR57q92iYwzEKGiDJA5peXAg3BFl5S2ZXGV8z4WQukcWMJLQeV1p18+BwkcsOjrd3EbimsNe4nnFzdVZBbWylz5ua6vhHBIJYpKitjD2ytLGscPs8ysIRcnhHrXNeNGk5SOMa0TuEYcGPPwk7X81lV0EtPO5r2OjcDYtIsQei6binBJMCru7AL6eTxRPtuOh8wrM1CzizheWriAGLYU0fSG86mm2Enm5mx6tseRXRSi08HhX1WM4qS2flfYm7IeN5eEOKqaZ8n91md3U7DsWHRUO3rs5j4E4s+m4a0fuPGQaqjc34Y3HV8fsTceR8lx/wBZDJY+Egr3vAaSHtt7F8Q4WqXtfjWDjvqNzvizAHIfQ6sPqF6NrPhlw8mfDfqO262mrhL0o6Pw5P2PTwZ8xOcQTlsSNQPNZeYuJJ35rQgjdTySU8zCyRjiHNO4I0IVeqhDJS4bO/NeqmfBTi+ZAHWQuf5KXuwUDm+LKOasjnZJSOLcxt4f1V6J+ZpyOtbcZrKtZsMdz8LR81RcS9xc7cm6YyUaya8kkjdTINOecf1WRM9zibm5PNA48gkDcWUpYJSwCpoG28XyUTRmNlYaLKWSzZ4X4creLMeo8FoBeeqky5raRt+08+QFyvT+1zGqTDoqDgHBTlw7CGN+kW/zJbaA9bXJPm7yV3s7oo+y3s6q+Oa+Jv73xZv0fDInjUNOx9yMx8mjqvLnmaeWSoqJHSzSuL5HuNy5xNyT7rzo/wA9bj/rDbvfN+w81L9xX436sNu99vsBy9ExDhsUR8IVrDMHxXHZTFheHVNUQbExsJaPU7BdrkorLeh3OSisyeEbMPaNjOGYRBhODwUtDFC2xmy95I9x1LtdASfJc1ieJ4lizzJimIVNUd7SyEtHtsF32F9i+P1QDsRq6XDmHcD614HoNPxXXYX2QcL0FnVcdRikg3NS+zD/AKW2HzuvKle2dBtw1fd9zxZ9IWFtJuGsn2LPx/J4DTxzYnOIKOlnqXXs2OGMuJ9gu3wTso4lxINM9PDhkR51LvF/sbc/Oy9zpMPosNhENDSU9JEPsQxhg/BFNJFBGZJZGRxjdzyAB7lcFfpyo3ilHHxPMuP1FVlpRhjx1fn3nnuHdjuBYcw1GLVlRWhgLni/dRgDUk21t7ryrG6qirMVqpsOpmUtGXnuYm3s1g0B15nf3Xpvadx7hz8EkwrCMQhqaipd3cxhdmEcY1Ou2u3zXjFbP3cWUfE7T0C9LouNaadau3l7L8HrdDRuKkXXuJPL0SfZ4FSsnM8xsfC3QKNrULQpoInzysiYC57yGgDmV6zPbOl4D4adj+Kgvafo8IzSO/RX+K8TZiOKOZAR9Gp/qorbG25/76LrcTpmdnvBMGGts3FMRbeQjdgtr8gbepK86IXHQn103V5LRfVnHQn103V/qtF9WNZKycBOAuw7BgL6KvjE4p6dtM0/WS+J/k3kPdXWFkYfNJ8EYzO/oucqJ31dQ+Z58Tzf08kAoW3VuGIyvawbnn0UMTbBadDDlYZDoXbeiEmxZPZKyVlBAk6Sa6AdbnBnC1RxhxDS4VDmax5zTSAf4cQ+J36DzIWEAvW4Zh2RdnbqjRvE2PDLED8VOy2/+kG/8xHRct3WcIqMPWlovv7DmuazhFRj60tF9/YYvbHxbTVdZBwphBbHg+DAMeGHwvlaLW8w0aepK8hq6gzyl52GgHQKziE5aO5Di5x8TyTcn1WXK+wsFpb0I0aagv8AkvQoqlBQRFPLe608CosjTVyDxO0Z5DmVn0NI7EKoR7Mbq89AunAa0ANAAAsAOQW5uMQhITlCUA1lNQ0FRiVbT0VJEZaiokEUbB9pxNgol612Y4RRcGcNVvaNj7LRwxubQxu3dyzDzcfCPK5XNdV1Rhxc9ku1nNdV+ppuW75LtZV7UcUo+y/gmm4IwmZpxOvZ3tdM3fKdz5ZjoPILwBxJK1eJeIK3ijG6zGMQk7yoq5DI7o0cmjyAsB6LKKWlDqoYlrJ6t95Wzt3Rh6Wsnq33iTpAJ7WXSdQwXqvYD2ff2t4obilbFnwrCnCV9xpLNuxnn94+g6rzbCsMqsYxGmw+hiM1VUyNiijH2nE2C+2uA+EKXgXhijwSlAc6JuaeUD/FlPxO+eg8gF5vSV11NPhjuzyelrzqaXDH1n8joSeZXgf7R/H7pDFwPhkn1kuWWvc07DdsZ/8AUfZesdoHGlNwJwvWY1UBrnxtyQRE/wCLKfhb+p8gV8iRT1WJ1tTjGIyumra2R0r3u3uTcrzeirXjl1stl8zy+h7TrJ9dLZbeP4JaaFtLA2JvLc9Smmffwo3OsLqBxX0SPqERlMQiIXU9mvBMvHPFEFA4EUMP19bINA2Icr9XHT59FWpNQi5S2RWpUVOLnLZHXcDU0HZjwPWdoGKRNdiNaw02EwP3Ob7VvMi/8rfNeNVVVUV9VNV1Urpqid5klkcdXuJuSu67ZeOouMOJ/omHENwbCQaajYz4XEaOePW1h5ALgJZBEwuO/ILC2hLWpP1pfBckc1rTetafrS+C5IgqZde6HuhpoJaqeOnp4y+WV4jY0blxNgFAXEkuOpK9U/Zx4Xi4g7SaWrrGg0OERur5yRoMvw399fZbVZ8EXI6Ks+CDl2Hona1jDOybsnwTs+w5wZXVMDZq5zTqXO1N/U/kvA+F6SsxnE6fCsOidLXYjK2liAGozGxPy/C63e2bjJ/GnHeIV5cXQiQsiHRo0C6PsRgj4XwTi3tGqWA/uWiNJh+bZ1XP4QR5tH5rK2pfx5e7MLSl/HxS3flDdpuOU1RjM2HYeQ/B+FKZuG0Qb8MtSfC+X/cHO/0tWZ2J8BHjfiyNtZEXYXQ2nqzyfr4Y/wDUR8gVHV4U3DuyWjxGoDn1uK4s4N62ZHd/rq5n4r6R7IODW8FcF0lLNGG19SPpNWba53DRv+kWHzXVTR1wjhYPS8NdHGxrWsaxrQAGgWAHQK/U17Y4SFhMqhG3os+rxPvH5A5a4NDn+1Ljem4L4bqcWls+oJ7qlhP+ZKdvYbnyC+McVxKpxOtnrayZ09TUPMksjt3OK7/tt46dxfxVJDTzF2G4bmgpwDo91/G/3It6ALzKV9yVVshkT3XKjTuKZVIGSTpkAkkkkAk6ZOEA4SSSQDpkrpIB7pXTJIAg5SNksodk4KAuw1OU6r1bgDtNbRYdJQ4nKSKaMugeTq5o+x/ReOh1lLHKQQpTwDt8X4oqOIsUlrqpxJebMbyY3kAsnEWtnYQRuqNG8vcALknkF1eFYDHM5slbfL/0xz9VDB57NEInlpOy7CuwXD8R4TwKahMUeJBsjaphBFxmOVxNtyLLp5OzWIRVWPOivT2zQRuFmNaPie49L6AczfoshobfQ3CxqPOMcjGprjHI5kcJYw/xU8DakgXLIXXcfQbn2XX9jHFEnDnHOHSOkdHeYRPadLXNrFXMHnpoKyOSpz90w5nZPiNuQXSY7wzgvG7Y8c4ef9Gxqkc2R0Mhs6cNN7E8z0dvyPIrzbqtlOnUWj59jPLvK+U6dRaPn2PkSftQ8OROxyHHqewzu7qW3Q6tPscwXiNPSsDgSbtGpX0H2pzQ8T4XilK2S76Z8YGuoLo2vb/5m2914dh+DS4jNDQU5LqiqkZDGP4nEAfiVXomu50Gp7pv3PVEdEXDnRanum/c9UfSH7K3CsNBhtZxdWsJfVvMVMLa92w62/mf/wCle4mR08j5HNALzcrH4P4fpeG8AosOhA7mjgbTQj72UWL/AHNz6lbjWgBddHM/SfM66OZ5m+bCpJ/oswla0E7WU1W/I0RXu4+J56lQeQ3QvdmeS7ddiR3JE9FTGqmDNco1cegXQsa1jQ1osALAKrh1N9HpxceN+p/orVlcsIhZuKVfcN7th8bt/IK/UTNpoXSv2aPmuWnndNI6Rxu5xugEXKMvTFyjL0BJnTF6izpi9CSXMlmUOZLMgJC9NmUedDn1QE+ZPnUOdPmQE2ZOHqDMnzICwHow9Vg5GHoCwHo2vVYORh6Au09S6E6G45hFJL3jy7qqYepWPQE2hRSwOZEJDoCjgjuczvkrndCVhYRoRYoDJiYJZO7J0eCPfkh8QiER1DXXB6KaOjeKowk6t1v5KGZpjkczmDZUkb01knpZXROBaTouS7duDRxv2d1Zp489fh/99prDxEtHjaPVt/kF0ocR6rSoqprmOjeAb8jsVjJ4JqUucT85MZjfE5kYJAcMx/RZnd33K9A7YOF5OE+PsbwbI4QR1Blpyf8ApP8AEz8Db2XH4NhJxHFaamlOWJz80h6MGrvwCcSjHLK0qbqSUIrV6HsvYfg1PwrgGMca1g8dDTHuQf8AryCzB6htz/qXmuJ1kldVy1Ery+SRxc4nmSvSOM604T2cYDgUJtUYxK/E5o275CcsTfkFwIwqClA+kSCSbmwHwt8r8yvBoT6ycq8ubwvBefgfoPR1o2nGktFpnuWnxeX7TQ4A4Um4u4josLjuPpEoY5/3G7uPsLleqdpeM01XxLBhOHtDcE4ZpcsbB8NwBa/m52VeRUldPQSiWinkppG7PhcWEe4Wi3FauopKiCR5kkq5WyyyuN3vIvYE+pur1Kjaa7T6G1slGrGSfqp+97v3aL29oJe+aR0jyXOcS4k8yV9DdjnAX7jwQYtWQWr8QYHAOGsUO7R6nc+y8n7KeFHcUcW09LUwk0lKe/qgR9lp+E+psPmvrWmjY9ujQPIcl0dH2+W6j9h5n6t6WdKEbSnz1fhyX19xgT0Ya3Zc3xBUU2FUFTX1b8kEDC9x/QeZ2XeVkAsbL587fOJ/75Fw3TP8MIE9Vbm4jwt9hr7hddy1Tjk+d6EhK7rqmtt34edDyviPHKjH8Unr6g2Lz4GcmN5NCxXuUsr7lV3OXkxWdT76tJRXCgS6yEuTFyElapHBKYWayfMo7pZlbBn1hLmThyhzJw5RgsqhPmTgqHOnzqvCbKqTZk+ZQhyIOUYNFUJQ5GHKEORByq0axmShyIOUOZEHKrRqqhMJLKWOWx3VXMiY8ZhmNhfVUcTop12mb2EUprZxm/wmnXz8l6Fhnha0AWA0AXH4K1rWtDduS7HDuStSjg2vZ8UcGjiuBxcQYXJRvsH2zRP+4/kfTqvL8GxCp4V4khmlYY308pjmjcLgtOjmkcwQT6r2WiabBcJ2r8NmMxY7A3wvIiqLfe+y7329gt6kNONcjxre4XE6E9peficr2hcLswisFZRXNBP4oze+QfdPmNvMAHmj7JeM38FcZUVeXn6M93c1Lb6OjcbH5b+y6Tg4RcXUzOHK1wAxKmdTwSO+xUsBMZ9w1rT6BeU1EMtDVSQTNLJYnlj2ncOBsQpinjKOW4a4nSq66Yfenlff26nUftJcHw8JdosmJ0TR+7saYK2BzfhzH4wPfX3XmrgyZgzC7dwvfeM2M7R/2eaXEi0y4jwvUtjkcN+5OnysR8l8+VUpp2tyWDjt6L16M+KKZ+a9JW0qFZwfnv8AasP2koZF/wBIfMoXxR/EGgEdFX/ec1vhYD1sFGa6dxAc/wAN9QBZbJM8mSJqogxBlyDe5VJ5A0BurVUA5mnqFRKtEqhk43TImi5VixJG2wvzK7jsk4Cd2gcXwUErXDDqYfSK2QaWjB+G/Vx0+fRcSzM4hoBJOgA3JX0BXwt7G+yaDBoj3XE3Ere9qnj44Iraj2Byjzc4rju6soxUIetLRfV+w5bqo4x4Yes9F9/Ycv2scYs4x4n7qiIbg+Fg01GxmjTbRzwPO1h5ALkFDGAxoA0AUmYgLSlSVOChHZFqVNU4qEdkMYqiokjp6eMySyuDGNG7nE2A+a+keE+Hxwvw9SYUwguibmlcPtyHVx+enoAvAuGMdj4cxmPFZaH6dJA0mCIvyNEh0DibHbXbmtDiLta4sxGKQ/TWYdB/06NuUnyzm7vyXndI2ta5kqcNIrXPeeT0raXF5KNKnpFatvt/B7fjOOUOERl1fWU9Kwal00gb+a4XFu3DhrDszKNtTiUo/wCk3Iz/AHO/QLwKrrZq6YzVMsk0jjcvkcXE+5UBcVSj0JSjrUefgZ2/6dox1qycvgj0zGu3TiCvuzDoaXDYzza3vJPm7T8FxVfxHiGLOL8SxCqrHk3+tkLgPQbBY6S9SlbUqXqRSPYo2dCj/jil57Sy+tNrMaB6qu+R0jszjcoSkFudQbV6p2H8GR4riM/EeJAMw3C2mQuf8JeBf8N153w/glZxHjFJhNBEZKmqkEbAOXUnyA1XuvanWUXAPCGH9n+DPAkkjEtbI3dzfPzcR8gvOvqrbVtT9aXwXNnBe1JNKhT9aXwXNnmvGPEcnFPEFTiLriEuyQMP2Yxt7nc+qxrJWTrupwUIqEdkddOnGnFQjshgE4CQTukbTQvqHi7YxoOruQVy5Qxup7tjaNh1+OT15BZcTdUz3unldI83c43J81YjbYXQkmpoe9kawXsdz0C2oaZ0ws0WYOfRVcNpXOyhjS6WUgNAW9irGYXTR0TCDI4XeVnOWGordmNSeGordkFk2idMVc1EmTqaio5sQq4qSnZnmmcGMHmUbSWWQ2kss63sz4chxPFHYtiIa3DMN+ukL/he8C4HoNz6DqsHj7i+TirHajFpS4QN+qpYz9mMbe53Pqun43xKHhvAKbhDDX+JzRJWSDd19bH+Y6+gC8orqjvpMoPgZoPM9Vw20XVqO4l4R8O32nDbRdWo7iXhHw7faVpZCS57jck3KpSvLjYakqWaXkrWCUZnmNU9vgjPhvzd/wALvPQNPDKP6DTZSLSP1f8A0VolKyZAJNa6R0RxtdI9rGNc97iGta0XJJ2AUEM6Ps84Nn434lgw4NcKRn1tXIPsRjl6nYeqt9v/AB9BjGLRcJ4O5rMIwchjmx/DJMBa3o0aDzuu6xqsj7DezAU0bmt4nxsakbxG2p9GA2H8RXzZJcuLnEuJNyTuV5tH/U1uufqx0XjzZwU/56vWv1Y6L6shcma0lOQSbBdR2ccFVPHXFdHg8QcIS7vaqQD/AA4W/EfU7DzIXozmoRcpbI7ZzUIuUtkWOFuyXjHi+OOfDMHmFLILtqZyIoiOoJ3HoCvVOHf2WA3JLxFjhJ3MFCz8M7v0C97pKaOipYaWnibDBCxsccbdmNAsAPZHNUR00TpZ5GRxt1c97g1o9SV81W6VrT0hofJV+ma9R4h6K+JzPCfZdwhwbLHUYVg0Qq4/hqpiZJRpbRx20PKy67M13JcFj/bbwJw7nZNjUdXOzTuaJpmdfpceH8V5Txl+0nUY9RVWEcN4TJRiqYYfpk8t5GNOhLWt0BtfW+izp2txXack/FmdOzuriSlJPxZh9s/G/wDb3jB1DRy58EwhxjjynwzS/af56iw8h5rkbj2UNNTMpoWxs2G56lSFfTUqSpxUI7I+so0Y0oKEdkM43UZRFCStDYEB73tYxrnvcQ1rWi5cTsB5r1/impZ2OdmsPDlO8N4n4iZ3tbI0+KnitYtB5aHKPMuKodjfDtDTiu49x8BmEYE0vizDSWcDS3XLcW/iI6LzHi/ieu404krccr3Hval92MvpFGPhYPID9VyS/mqcH9Y7+PYcc/5qnB/WO/jyRlNaALNVKolMkp10GgU1TKY25Bu4a+QUJaC0FdZ2At81792Zw/2H7DeIOJ3eCrxqX6HATuI26afMrwempjUStYNibXXs/a3iZwfs14P4ZhNgKX6XK0dXai/zXDevi4aS/szz758XDRX9meNTuEsz5HG5JJK9b47eOE+xfgfhWPwVGLOkx6ubzcHHLED/AKfyXlvDWCT8R8QYbhMIJlrqqOnb/qcB+q9S/adMTO1F+HUr/wC74ZQ01FEwfYDWbfiu9LCPRSwjqMB4Ylx6n7L8Pqo89NBR1WN1II0OaYZAfWzB6L3Nj37uXk3ZVxNRUHFNbw7jUhgxano6ShhZK4ZWMiiF42+eZxJXrVYRG0luytT2ENiCprAxp1XnfapxeeG+Eayogky1dT/dqcg6hzgbn2FyumxKpcSQCvnzt1xt1VjtJhTX3jo4u8cL/bf/AMAfNXehY8ymedr3VV7kcj1CTdZkDFJJJAMkkkgEkkkgEkknQCuldMkgHuldJJAJOm3SQDpkkkA6mpYu+lDAbKBWKGTu6qN3LNYoDqcHpo4LZWeL7x3Xc4BSNrJ4YXOEYke1he7Ztza/4rmcKha5wuFpY/VOo6anpoHFr5DncRuANvxUA6/tV4vo6yOPhnA3/wByoyI5Xt0EhZoAOovqvOY2lm5Ucea9yuy4C4ah4hlqY6kaZMrT0J5rPBng5dswa4AmwJ1PRXKHGW0dWHUoeHNNmuvYn/voqmK0n7sqaijmBE8Mpjd7LGmqQw6Fc9WkprBy1qKmsM7XG8QklxCpr4rtZjFIe+bybUxWdf8A1AX9yl2JcPPxftSp8w/u9A19a5x2At4D83D5LlY8dz0D4BcvjHeMDjfxD+oJC9Y/ZziDqKtxa31tT3dLts2O5PzJHyXHSpSppx7dPPsOGlSlTTWN9PPsPoumdnIOzQLNHQLap6ESUj53utYEtHVYNE1zogb69F0dbKIcPhhabGRov6L06ccI9alFJGcCCRrzWl9CEmJN0GSweVk7bLosPIlpo5ftFoaT6LVGxbumunCZ7hG0udoALlSDEx2rJkbTtOjfE71WO4qWpmM8z5XbvN1Xc5AIuQOcmLlG5yEhFyHMgLkJcgJc6EvUeZDmQEudLMosyWZAS50+dQ50s6AnzpB6gzIs3mgLAkRB+irByJrkBaD0Qcq7XIw5AWWuVmnsdeaoh6tUb7uLfdAasPJW2FUYlciugI6iaOCdrnaPLSL+QWM+bvJHPP2jdSYpN3tW4cmeFVFRnVBJLBOXWCEVHduDhe4U7oA7Du9b8TDr6LLklsDcrOSyjoikeFfta4c1tdgHEccIIq4H0czrfbjOZt/Zx+S8Z4SopMSmcyLSerljoYbjYvN3H2AHzX0d29wtxfsxxBpbmlw2ohro+obfI/8ABwPsvnrAMSGEVmDPjaM8TZamTyLmkA+wsuK5k1Sajv5Z09HW8v3OY8tV4vRfF/A3uJcRGJY2KhhtHDEyiowT8ELBlDvV1ifdYWIQCmmDRJna4Zmnqq1ZXsncXC+YmwHIBVnzyytZncXBugvyXFTp8MVFcj72hKnQpKjBZwW4mue6w1WhDG5oFwrmAYVmpBM8eJ+o9FLWBlLf8FWcT2bOWFk+gewmnp4sINRURNbWYg0ETX1kbHcBp87G/nbyXrAlbENF8t9nfaRJhIhwyp+GORslNJ91wPwnyOo919ICvjqIWTROvHI0PaeoIuF6NnUXBwrkfDfqSxqK6dWW0vp+CfEsXpsOoamuqXWhponTPPk0XXxhxHjM+O4vWYpUuvNVyuld5XOg9hovoHtux7928ETU0b8smIStp99coOZ34AD3XzPM/UrmvZ8UlHsPZ/TNsqFGdZ7y09i/PyI5HKAuRPeoS5YRR6VapqIuQlyElAXLVI4ZVCTMmzKMuHVLOp4TLrCTMnD1DnSDk4QqpPmSzlRZ7c0+dRwl+tJw9EHKuCiDiocTWNUnD0QeoA5EHKribRqk4ciDvNVw5EHqnCbxqk+ZMXqMPT3CjBp1h13ClT9IhMZPjiNvbkvQMLZfKvJ+Fq0UuMRNJsyb6s+p2/FevYNGSW6KVHU2dbihqdNQxEsGimxXCGYzhNVhsoGWojLAT9l3I+xstHB6QPi16KedgjOi7Iw01Pmqlx/JiO6Pn/h6Kalw/E7PdT4lglTHVMcDqwZwxx9nCM+l0HbLQRN4igx2mjEdPjtKyvDQNGyHSVvs8O+a7HEcEydq7aIN/u/EdJLA4AbufG5p/wDO1pWfxVRfv7sSwrFHN/vGEV7qWU8wHixH+5oP+pZRjhNefOGdVesnKMu36/8A9R+LIv2fq2PEqrHuD6k5qfG8OkY1jtu8aCR+q8Dxmllo8UqqSYFslPI6EjplNl6V2YYyOHuPsDrw7K2Osja8/wALjlP4FZXb1gf7h7UcchY3LHJUOkb7m/5WXVayxLh8+dz5rp6jmHW+H2f/ANUee2QnREdkDnL0EfIMLviWZTyUeXzTgaJrqSBZfNENNAmGuqt4Zh1Vi+IU9BRQmapqZGxRMG7nE2ChvGrIbSWWemdgfBNPjWOz8TYyGswTAG/SJJJPgfKBdo8wAMx9B1WVx1xfPxxxRWYzMXNikdkp43f5cI+EevM+ZK7ntOrqXs/4Kw3s1wiVpmLBUYpK3d5Otj/M7X+VrRzXkbDouG2Tqydd89F4fk4Lf+WTrvZ6Lw/JO0qUbKBlyVYAXado3ssTGavvJBA0+FnxeZWrX1Io6Z0n2jo0ea5guLiSTcnUlSiUK6dMASul4d7OOLOKMpwrAq2eN3+a5mSMf6nWCic4wWZPBE6kYLMnhHNpL0firsWxDgbhh2NcQ4pRwTPc2KnooLyPkkPIu0AAFybX2XnLm2VadWFRZg8orSrwqrMHlAlO1Cul7PuD6rjnimiwanuGSuzTyAf4UQ+J3y0HmQrVJxhFzlsi85KMXJ7I9c7COG6XhHhjEu0bG2ZY2RuZSBw1LBoSPNzrNC824gxqr4kxmrxaudeeqkL3Dk0cmjyAsPZemdufE9LTmh4GwcCKgwtjDOxm2cDwM/0jU+Z8l5GvPsKbnm5qby27lyOG0g5N157y+CGskiSIXoneM0XIA3Kzcdqg6RtIw+GLV1ub/wDhaE1QKKmfUH4h4WDq4/0XOavcS43JNyeqkIOJqu00XfShv2RqfRV422C38BwifEaunoadt56l4H8o6nyAuVEpJLLIlJRTb5HQ8L0DIKeoxqqFoKdpbH5u52/L3XP1lXJW1MlRIfE839B0XWcd1MGHNp+HaE2hpGgy25u5A/mfMrjea5rZueaz57eByWmama8v7beHL37mndIoSlquk7B7rs+EY4OHsMqOJKxoLw0spmH7ROl/c6el1y+EYc7E66OnFwy93u6N5q5xbjbKmZtJCQ2ioxlaBsSNCf0XPXj1j6pbc/D8nNXi6jVJe3w/JhY5is1VPLUTvL6mpcXOd0v/AN2XPyuytspaid00jpHbnYdAqU8l10JJLCOlJJYQ0cT6uoZDGLucbei6qGKOniZDGPCwWHn1KzcEou4h+kPH1kg8N+Tf+VpqSQr6ISkmJQDbr1PsR4Mgqqyo4xxktiwnBwXsdJ8L5QLl3o0a+pC8+4dwKs4mxukwihZeepflBtoxvNx8gLleh9u3FdFwtgNF2acOvyQwRtfXvadXcww+bj4j7LgvKjk1QhvL4LmzjuZttUYbv4I8t7T+N5+P+LqvFnFzaRp7mkiP2IgdPc7n1XIPKledFC7U2XXSpxpxUI7I6YQUYqK2Qzd73XtXZR2kcGdl/DMtRN9KxDHq85po4IrCJg+GPO6w8za+/kvFbJKtajGrHhlsZXFvGvHglse0cRftQcR4hnjwWgo8KjO0jx30vzPhHyXl+P8AGPEHE8pkxfGK2tv9mWUlo9G7D5LGskopW1Kl6kcEUbSjS9SKQlu4TRfR4u9ePrHj5BZ2GUn0mfM4fVs1Pmei6C63OhiJQ3TkplBCGOq0OHsArOKMao8HoGZqiqkDATswc3HyAuVQI0XrXDDo+yLs/qOMayNv79xdncYZC8asYdQ4j/zHyDRzWFxV4I+ju9EYXFbq46es9F4mR248R0eFU9B2b8Pvy4bhAa6sc0/40+9j1tck+Z8l5EXCNpc7YKSaeWpmknnkdLNK4ve9xuXOJuSfUqjUS535AdB+JV6NJU4KJejSVOCiRvkMjy47lSRRmTwggE8yo3Ny2PVWKcEm5C0Zo9jXwulAmjYBubDzJ0/Vdh294i1/Gb6Bh8FDDHTgchlYAuU4fu7FqNp2NTC23rI0K72wSum7Rsec7lVvHyK4nHNxHPJP6HA48V1HPJP6HSfsx4V++e2bBA9uZlGJas/6WG34kKxXwDtB/aMdHKTJBU47lf8A/Cjd4vazCug/ZApmxcZ4/izhpQYPI4HoS4fo0rn+xCU1naZieJvN30uGYjWhx5O7p2v/AJl2y20PQexxnE+Ly4nxtjOMxyujfPiE07HNNi28hIt6Cy9u7Ne3GmraaLBuKJmxzgBsVYfhf0D+h8185CUu8TnXLtSUYk81MXhBaI+wMWla4iSFzXxnUOabgjqvkzizGJMa4ixGve64mncW/wAoNh+AC3+HO07GOHaKagEn0mlkjcxrJDcxki12n9Fw8khcSrt5LAuNygKclMVUgSZJJAJJJJAJJJJAJJJJAJJJJAOmSSQCTpkkA6SSZAOnacrgehuhT8kB6pgdOJmRuA3aCs3iCoMmNzsBu2G0Q9hr+N1u8IND6KmedhG0n5LkTK6pqZpnamSRzvmVDBbidouy7McYNFxLFTv0jqRk9+S4yPQKzTVz8OqIqqI2fEczVRlSTiep/fnFGJVAkDWyVEhDjsGi/wCgXK1D/De+itVNSTmOaxde563WTUyHa6jBXAo5+6ma6/NfSfYRA2g4Yo22sZC+U/6nafhZfL73E3X1T2WsFPhFFFtlhYP/AChZzjqjKcNUe1UUmZgV2Sd05Bcdmho9AsvDn+Bq0IyFsjeIWpXQYI69EB0cQufJV6krpKKkzNAP1liDzBCsix0GioYzUGGgksdXkNClpK+Gtb4HWfzYd1m8RyECGK+93FSDEc5A4p3FRuKEjOKjcU5KBxQDEoS5MXICUARcmzIC5CXaoCQuTZlGX+abMgJcyfMosyQcgJQ5EHKHN5pw9AThyJrlAHIw5AThyMOUAd5osyAna9WKaXJM08r2VNrlKx3NCTpIm7K5HYC/RUoH5o2O6gFTzS5KWV3MMKEI5yWbPM9193Epg9Qk+IpwVQ61uaVNUWo6mJ33CQsqVpDQTbUKdzvqiQfVVZZPBa+yqdETjeO6ZtVgGKUjrFtTSTQkH+Jht+Nl8kuqMk0xB1AbEPIAC/5L6040kIoJjf7JXx5LIRUSD+M/muepTyz07aqqXpc/+fuXmy5lPGfq333FiFShN7K4Hi9m/Da3quaSwe7b1M6s7zCMSjlwhklg3I3IR0IWBV1pqpy6/hGyo09c6OhdTDQPfmPohY7oueUT3aNd4RfilLXBzTYtNwfNfUPZ5jZxngigqS7NJGHQv12LTp+BC+VWPK9V7J+0jDuFcPmw3F2yiCefOyZguIjYXuN7HyUUJcE9SOk6TubfEVlp5LHb5ir5MQwvDsxtFE+Zw83Gw/Bq8ikfddx2wYxT4txhJNRzxz07aeJsb43XaRa/6rgXuVZ6zbJt31dCMO756gvKjcU5KBxV0jmqTBc5RlydxQOWqRxTkPm1TZkF0rq2DDjDzJZ0F0rpgjjJMyWZR3SzJgdYSiRGHgquHIsyhxNI1mWA5OHKuHog9V4TZViwHos6rh6IO81VxNo1ifOnzKHN5p8yrwmyqliKYwyNkabOYQ4HzC9/wCVlTSwVDPhlY149xdfPGZe39ndb9I4VoHE6xh0Z9nEJjBrTqZTiel4dU92y11LLMHOvdYtPUabq22UvW6kebOhiWTnOPa/9xYlwxxLFpJhuIta8/wDu37j8D81VfRxnBu1vhJjbNppf3nTsHIB2bT2yqftLpGy8HVUsoJjgmhldboJAD+BKsQd1VdseIdxpScScNukYDzD6cEfiwqUtfPMwq4UdOSz/APFqX3Pmunmkp6lkrTZzHhwPmDdei/tKQNqOLoK4tuKulp5ieuaFp/QrzqUCKRw5gkL0Ht8qBV0mCy38bcGw9zvdhCrCeKkV586mF5TUqNWP+2XwcX/9TyR9KwjSL81n1MLInC17nkgc48iVGSbr1Yo+CY7jyTWunIvqnYOasQEG8l7R2G4HR8M4TinaZjcdqXD43RULHbyynQkedyGDzJ6Ly3hThyr4t4gosFoQe+qpA3NbRjd3OPkBcr07tr4kpKU0HAOBkMwrBGNbNlP+JMBseuW5J/icei4rlupJUI89/D87HDdydSSt489+5fnY89xfGKvH8Wq8Vr395U1cplkPIE8h5AWA8gq7SoWlTRtLnWC7EklhHWkksItwC+qnQRsyNAWpw1w/UcYcSUHD1Nmaal+aeRv+VCNXu+Wg8yqTmopylsjOc1FOUtkR4P2YcY8evZU4XhTxQHSOpqHCOJw5kE7+wK9M4d/ZViYGy8RY6553MFCyw9M7v6L3TD6CDDaOCjpIxFTU8bYooxs1oFgFcPgYXuIa0C5cTYBfOVela09IaI+WrdM16mkNEcbw52TcGcK5XUGB0z52/wCfUjvpPm7QewXXtsGhrQABsAuN4m7YeCeFw9lZjcFRUN0NPR/XPv55dB7leTcVftRT1MM9Lw5g30cPa5jaqqku9txa4a3QH1JWULW5rvLTfezCFnd3Ly033v8AJzH7QfG/9qOMX4bTS5qDB7wMsdHy3+sd8/D7Lyu5JRySvkcXPJc5xuSdyUC+oo0lSgoLkfY29FUaapx5BNAJX0p2WYNT9k/ZnXcbYnE0YniMYNPE4a5T/hM/1HxHyC8j7HeBDx5xnS0U0bjQ0x+kVbuXdg6N/wBRsPmu87d+Nm45xG3AqB4/d2EXjIZ8L5rWd7NHhHuuG7fX1VbLbeXh2e05bl9bUVBbbvwPN62rnxCsnrKqQy1E8jpZHndzibkqGya90+4XopY0R3JYGuiALiGjUnRCo6yp+h0j5QfrH+BnrzPspJMzGaoTVAhYbxw+EeZ5lVImaqNouVYjFghJapIO9k1HhbqV65wNQQ8KcJVvGWIMBlmaYqJjtyNtP5j+DSuM4A4Rn4sx2lwiK7WyHvamQf5cQ3PryHmV1XbBxHT1uLxcP4XlbhmEN7lrWfC6QCx/2jw/NefdS62ato89ZeH5PLvG61SNrHnrLw7PacFU1MtXPJUTPL5ZXF73HmTuok/JMu9LGiPSSSWDRTgJgruHxsDzUS27uLX1KSeFkmUsLJfM4wPCu7ZpWVI1PNg/7/FcbidRmd3LToNXeq08XxBz3PqH/EfCwdFzkr9yTcnUlVpw4dXuylOHDlvdkcr7aIsNpDXVQDge7Z4n+nT3VZ5L3BoBJJsAF0tBSCiphH9s6vPmrmhY9reQ5JJJXsgElumuus7N+ExxVxAwVAth9JaapJ2cL6M9/wAgVlWqxpQc5bIzq1I04OctkdtwQym7KuAq3jjFYgcRrWCOghfuWn4R5Zj4j5ALwHEsRqsWxCoxCtmdNU1MjpZZHbucTcru+2fjw8Y8RfQ6R/8A+VYbeGBrfhe7Zz/wsPILzp+gXJY0pYder60vguSOW0pyw6tT1pfBckRvcha1TUtJJVvOXRrdyVfGHRxjxOuV3naZeVMWrrMI4A4j4gcP3ZgtVJEf857ckf8AudYfJd1gv7O9XNlkxzF4advOGkbnd7uNgPYFcta9oUvXkcdfpC3o/wCSaz2bs8Ytpc7LQwrhzGMefkwzDaqr1teOMlo9TsF9KYN2ScH4HlfHhYq5m/5tY7vTf0+EfJdM2FkLBHExrGDQNaAAPQBeXW6ditKUc+J4tf8AUcFpRhnxPFeG+xPGnU7BiNRTUDTq4A94+/oNPxUHH/D2B8HilwykkqKrEph3sssrwBHHsLNGlyevIL2TF8dw/AaV9RiFXDTtY0uyveA59uTRuSvnHGMZquI8aq8XqgQ+pfdrP+mwaNb7Cyt0fXuLqpx1HiK7NMst0Zc3V7W6yo8QXJaZZAUJTXKlpYZauoipoInSzSvDGMbqXOJsAF7jeD6TONTrOy7g48YcRtFUMuFUIFRWyO0bkGoZfzt8gVmdq/HZ484okngdbDKMGnooxoMgOr7fxEfIBdjx9iUPZnwPDwJhsrTi2Jt7/FZ2HVrD9i/nsP4Qeq8Y0YCToAuOh/NPr3tsvv7fkefb/wA9R3D22j4c37fkDUyd3HYfE7ZU2jVKWQyvzH2TxtLnBrdSTYLtPQJt2gAAm6mY0gaIYmi/popHuDW3CqVNDB5W0lVBVOdpHVwON+gff9Fq9sceTtExojaSfvG+YcAf1XM946WgqABYNew/mtHi/GI+IZqHEc394dTMiqAfvsAbf3ABXO4vroy5ar5M5HBq4jPlqvk/oezfsrNMeGdodU0XMeD5R7h5/RcV2HTW4h4oc24ceG8Rt/8A0wuz/ZZxOjp6HjyhqaqCB9ThYMfevDc1mvBAv6rjuwuGSHj/ABGimbZ0+C4hDl63gJH5LqZ2s8zYbNHonLrIA4Bo8ghLkQQ7nqLdOTdMpJEkmToBkkkkAkkkkAkkkkAkkkkAkk6ZAJJOmQDpkkkA6ZJOgGT8kye6A9e4ed9H4afN9ykJ/wDKuLppPCEUXHEjcOdhkNI0Mlj7pz3O1Ata4CqxTNaFDBqNkCVU76o+iotqwENRWlzC0DcWVSCpPJ5rPnfcqaeS6pSOJKkDN8TwOpAX1V2fSBsETejQPwXyrD/jM/mH5r6f4ElyNYPIKs90Unuj2fD3/Vt9FqRu0WDhswMbfRbET9FZF0WQVLI/LE5nm0/gq2dHKb3PkFJIwe5hDmkhw2IOyerrJaotdK7MWiwKhLlE5ykCe5ROcU7nBROchInOUbnpnOUTn+aAMvQlyiL0JegJC5CXKMuQF6AlL/NMHqEvS7xAWM6bMVAHpw9ATZkQcoM6IPQFgORNcoA5GHISTh1kYeq4ciDrICy16la9VA5SNkQHTUUl6eP0U1bIRQTfy/qs+hlAp47uAFuZRV9fTmjkibK0vIsAPVCVuZLneI+qWYqEyXKcSKh0onLvqyFTlfYFSmTSypVMtg5QdEGclxvOBh82v2SvkCqfbEKkdJXD8V9Vcd1WWilF+RXyfVv/APzGpI/6rvzUYyWqzcXEvwPVyG5cACs2F6uQyWIK46kT3rSstMl6IXAVlgsqtO/QKy14suZo+goSWCVpsifIe7y8r3UV00jwGFYuOp3KriLEXlAXIC+6FzlZROWdUdxQEpEoSVdI5pyyMSgc7SydxUTitEjkqSFdNdCTqmJV8HK5hZksyAuTZlOCjqEmZNmUeZPmU4I6wkzJZlHmSzKOElVCbMiDlAHIsyjBoqhMHIg5QBycPVXE1jVLAenz3UAenzKvCbKsTh2q9Z7MKy3D3d3+Cd4/IryAPXpnZk+2FSXIA79xuTpsFWUdDptquZ+w9Xo3l4C16eIkXC4yXjDAcFjzVmKU7XD7DHZ3H2C57F+3dkLHRYHh5c7YT1Ww8w0fqUibVpZ0R6D2gZG8CYyyV7GZoLMzm2Z1wQB1Oi5ijxtlHxp2a10jg1j8BjhkPl9cxeP4pxRinEeIsqcVrZalwN2tcbNZ6NGgW7RVk0mMcKNe+/cUjcvk3PIbfip43kwVupLDfb8Vj6nD1pzVUuU/bd+a7btikM80lKNfoeGUEHoWxMJ/9S4lrGOrbyE92ZPFbe19Vr8V4ucYbjGJSDL37g5rfutuA0ewAVGn10McvujjlTbhWm9uGfyPPXAt0O6FFI/O6+wQr20fnzHaiGp6JgLBdZ2Z8FS8ecV0uFC7aUfXVco+xEN/c6AeqpUnGEXOWyM6tSNODnLZHoXZvDD2Y9nlfx9XxNOJ4k00mFRvGtj9r0JFz5N815JNPLVTyVE0jpJpXl73u1LnE3JPuu67ZeMYOJeI2YbheVmDYM36JSMZ8LiNHOHloAPIea4EBc9rB4dWe8vguSOWzpvDrT9aWvguSJGlaFFHcZz7KjAwySBo5rYjYGNDRyXS2dUmPJKynidLIbNYLle9/s/8FuwnAJOJa6K2IYwA6MOGsVOPhA/m39LLxzgLhR/aBxpS4PlJw+mIqa542yNPw36k2Hv5L66jjZDG2ONgYxgDWtaLBoGwC8Tpa44YqjHnufPdN3fDFUI7vcjqquOhppamokbFBCwySPds1oFyT7L427Q+0zGeN8brZ3V9XHhrpCKajErhGyMaDw7Enc+ZXsn7SXH37rweLhOily1WIASVRadWQA6N/wBRHyHmvmgm6v0Ta8MOtlu9i3Qlnwwdaa1ewimSTXXtH0Ik7Bc219kK9K7CuCBxZxhHU1cYdhmF2qp83wucD4GH1IufIFZV60aNN1JbIzrVY0oOctkem4HTjsT7IjWvDWcRY2AWg/FG5w8I9GN1PmV4eS5zi5zi5xNy4m5J6ldt2s8a/wBsuKZHQSZsPorwU1tna+J/ufwAXEkrlsKMowdSp60tX9F7Dms6clF1J+tLV/YSdMku87QmtL3Bo3Kw8VqxU1NmH6qMZGefU+61MQqfotGSDaSW7G+Q5n9Fz41KAONqv0UQe/M74WalU2eQ1XpPZFwM7jDimmo5mXoKS1VWuOxaDoz/AFHT0us6tRU4OctkZ1aipwc5bI7jh+EdlfZhPj87cmO46Ayma74o2EHL8hd58yF485xe4ucS5xNySdSV23a7xmOLuK5RTPvhtBempQ34XAHxPHqRp5ALh1zWdJqLqz9aWr+i9hy2VFxi6s/Wlq/ovYJMldMu07jSbqbKV8+aMRtNmD8VWLiZO6addyeiq4pUdzEIWnxP38goxlkYyUa+q+kTEg+Bujf6rPmfdSSusLKKngfWVDYmc9z0HVWLGhgdF3jzVyDwtNmX5nr7LauhiYyGJsbBZrRYJFQB7pIbp7oA4o3TSNjY0ue4hrWjck8l3PEmLDs94MZgVFIBieIgunkYdWg6OPy8I91kcI00NGZccrCGwUoJZfm7r7fmuKx/Gp8fxWfEKgm8hs1v3GjYLjqR66oov1Y6vvfL3HHUj11RRfqx372Zrnc1GA6R7WNF3ONgneVoYRTWaah41OjPTqus6y7T0zYIBGzcbnqV7J2P8DtpcMOP4hTRyTVf/hmysDu7jB+IX5uP4AdV5NSPoxVw/vB8jKPOO+MTcz8nMAdTsvScR7fXiBtNw9w8yKONoZG+rfcNaBYWY3+q83pGFarBUqK33Z5HSsLitBUaC33fcev53GzdTbkFjY1xpw7w60/vTF6SneP8vPmkP+ltz+C+fsd414s4hzfvDGp44T/k031LPk3f3XLGhibJdxdK9x5m5J/VcFHoLnVl7jy6H6ce9afu+7+x7Xjn7QOFQ5osDwupr5dhJOe6Z8hcn8FyGJ9pvFuLNIdXMoI3bx0bMlvLMbu/FUuHOzjijHS11Jg8sMJ2lqR3LPx1PsF2Vf2SU/DGA1WM8R4y3u6ePN3FG3V7tmtzO6mw2XVGlY0GorDl72dsaPR1tJR0cvezzKa88pmnkknlO75HFxPuU1wiJDhmAtfl0UbivXR7qXIe4K9H7NqCi4bwyt49xpg7iha5lFGd5Zdrjzuco9SeS4nhrApuJMZp8Phu0SG8j/uMG5/752Wr2o8URV1TT8OYUQ3CsJHdgNOkko0J8wNvW5XJc5qNUI89/D8nDd5qyVtDnv3L87HH4xi9ZxBi1VitfIZKmqkMjzyHQDyAsB6LKrJf8tvup5pO5jLufJZ1ySSTcldcYpLCO6MVFYWw4UsG5I5c1G1pdsrUMWVo+ZUslhd27cA2KZ7C4WFwonzOe7QnLyCcOB5/NVK4LlPGW0NUHW+wR8/+VRfGLa6FXKclzJmAkh0f5EFVpRleQkeZEd2Rxumiv3Ujm/ymy0+GOK8U4QxuHGMNla2qia5n1jcwcxws5pB5EaLNj1eQk4AFWLvGwL5BI5xsBck26KMiyJ7Rc20Q5SpJGTJyCkgGSTpkAkkkkAkkkkAkkkkAkkkkAkkkkAkkkkAkkkkAkk4aXGwBJ8lJ9HmH+W75ICJOj7iTmxw9lJBRTVEjY44nOe7YIAKf/HZ6rUYC7ZWI+EsTghdVzxRxQxDM4F4uR5AI2NY0eEWUNkZIAxwQTaBWnuAVSd2igZKUxVV+6sylVnDVSgPHpI09CCvpTgqSzIjfcAr5rjaXOsBqvo3gp390pH/ejYfwCxrSw0Y1pYaPYsJk8DdVvQv0XL4TJ4Grfhk81ZMvGRoB6Lvbg+iqtkR94rmmQnPUTnp3EHYqJ7rKQJz1E56Zz1C6RSAnOULnp3PUTnISOXIc/mgc9RmRASuegL1E6RAZEBKXps6gL03eICyJE/eKt3iIPQFgORh6rB6IPQFkPUjX+aqB6MSISWw9EHqqH+aNr0BZDkYdoq4eja5CSwJDzJTl6gDvNIu0UEolzJd4oM3mlnvzUHRElfJos6qm8LtVakkAY49AsSuqsrDqq5OiCOG4/qLUcmvIr5gnN6uV3V5P4r6F7Qa0mkm12aSvnyaJzZLkbqqeuCbiDaT7CeFytxm5CoxaK9TDM63ksKh6FnJvCL8A0CsC4Girw7BWGFckj6ih6qC8SGS5jKlFk4IHJZNnYoZWMlMXTkq2S07tCgkiYdhZSpZMZ0XFaMhLkBKkMXmh7onaxV00csoyIyUBUj43N3aQonFaI5amVuCSgJSJQkrRI45SEXJsyYlCSrJGDkFmSzICU2ZTgp1hLmSzKO6V0wTxkocnDvNRXThyjBZVCXMnzKK6QcowaKoTZk4d5qIOKcFRguqhKHKVlTK2Pu2yyBm+UONlXBRtBPJVaNoTfIlD0+dMyIncgKZtOzmSVk2kdkITlsNFM1jszjsD+S12YtV1FTSTUsYZJTQNhYbcgCL/AIlUY44xoGhatA0ZrjospSR6lrQk9Gw8C4fEkzZKtodrcR8vdRdoVO2jhq2sY1jXthsGiwGv/C6zB4bkaLke1ifLUMhG7sl/YE/qq0G51kdHTNGnbdG1OFcn8dPqecImjXVNuUYbYL3j8eHGq9kpXO7KOy9zoz3XEPEg32fBDb9Afm7yXFdmXDUePcQNqa0AYbhw+k1LnfCQNQ0+pHyBQ8ccVS8X8QT4g4kU7fqqdh+zGDp7nc+q46y66oqXJav6L6nBXXX1VR/qtX9F9TngNEYF0ynp4jLIG8ua7DvLdDDlbnI1Oylr6sUdM6QfGfCweanaA0WGwXVdjHBv9u+NhX1UefCMHIleHDwyyfYb8xc+Q81hVqxpxc5bI5a9aNKDqT2R7N2H8BngvhCOarjy4pidqmpJHiY0jwM9gbnzJXb41jFHw/hNXitfJ3dLSROlkd5DkPMmwHmVeAPuvnr9pfjzvJYeDaGW7Yy2oryD9rdkft8R9l8vRhO7uMvnufH0ac7259Lnq/DzseM8W8SVfF3ENdjVafrauQvDb3EbdmtHkBYLGKcpl9bGKiklsfbwgopRjshikkUt1cuHDE+aRrI2GR7iGtaBcuJ2C+hcUYzsg7KIMBhc1mO41d1Q5vxNBHjP+lpDB5krj+wLg6HEsbl4mxJoZh2DjOHP+F01rg+jR4vksrj7i2XjPiaqxRxcKe/dUzD9iIbe53PqvKrf6m4VH+sNX48l9TzKzdxcKkvVjq/Hkvqc+DySuhuldeoekHdEwZjbb9FGCq+I1X0emyNNnyi3o3mgM/Eqv6XVOc3/AA2+Fg8gqzQmRN1IAGqElyhju/vCLhmwHM8l9BVtux/sojoGkM4j4hGaZw+KFpGv+1pyj+JxXGdhfA8fEPEf7yxANbhWCgVM7n/C+TdrT5C2Y+Q81ndo/GD+NuKarEg530Vp7mlafsxA6H1OpPquCt/NWVLlHV/RfU86t/PWVH+sdX9F9TmCQB5ISUihuu89AdNdMSmJQkvxWpKd0058R8Tv6LDnmdNI6V+7jf0VzF6vvJBAw+FnxeZWXI/RSCKV62sIpPo8HeOH1kgv6N6LNwyk+l1GZw+rZqfPoF0JUAcFMUkkAlPRUb66pZAy4zHU9BzKhC1BVswPDXzn/wARKLNHToqzbS03KTbS03K3GWMMjijwWiOWGKxktzPIfquRLkc0jpXukeSXONyVC49FEIKKwhCCisImpYDVziLZu7j0C3sgY0BoAA0A6Kth1IaWDxD6x+rvLyWhhWE1fEOM0eD0H+PVSBl+TG83HyAuVMpKKyyZSUU5PZEMMElXKIYIXzSO0DI2lzj7BdfgnY9xhjGV5oo8NgP26x+U2/lF3fgvfcAwDD+GqGKkw+lhhETAwyNYA+QgfE47kndaE9XDTROmqJo4Y27vkcGtHuV85W6blJ4pRPlK/wCoZyeKEceOp5dhHYDhEJZJjmJVWIPbqYofqY7+urj8wu6wrhHAMBaBheEUdMR9sRgvP+o3Kw8b7ZuC8Gc6IYmcRnb/AJVCzvNf5tG/iuCxrt/xSqzMwPBYKRp2mrH94/8A2iw/Nc7o31162cd+iOXqOkbz1s479F7j2pwcLuN9OfReFdtfFoxrFIeH6SYPpKEiWoc03EkxGjfRoPzPkuPxzi/iXiS4xTGqqWM/5Mbu7j/2tsFjsjbG3K0WC9Ox6J6iaqVHlo9Xo7oP9vUVarLLWyHtbmmJ8rpLouEMPp31L8Ur7NoqId44u2c4aj5b/JevUmoRcme9VqKnByZrOqBwBweXN8GN4sLD70Mf/APzPkvN9eZ9ytLiLHJuIsWmrprhrvDGz7jBsP1PmVi1kuVvdg6u38gs6FNxTlL1nv57jK2ouCcp+tLV/b2Faok7+TQ+EaBB3RtfSydreiLxOcAOS3OgkijDAL7oppAIyAdXaJBrk0keZvmNVBBAAia0kpCxUrRogLVAAJWtP2jlJ9VBWMMc72ncEpmyOYQW78lcxyP+8tmaPBPG2VvuNfxuq5wymcSMpjrPSc5CdDdInVXNAviSsreFMp55zDUaBw8LuhWk7hPEZGiSmhM0Z2c0hV4tcFePXBh2QuFl0dNwHjU9i6KOIHm94Cuz9nNVBTPlfXU5LRfK1pN1YucYmV2bDxC8tLybdAgEEY6n3UgqpK33LPuqNzWjkoyCBPYqQhMpAFj0SsjTFADZKyK6SAGx6J8pPJEE4QAiMnoiEJP2giCIKCBhTt5klTMgjH2AfVCCpGoCVpDdgB6IsyjumLrKAJ7vNXMENq5rjyWc96v4TII3FxRkHY19e2TCamPrGVyIkHIo8ZxEtphExxBkOtuioMk00UJAtOeq8xu1Iy3RNYZYpLb5dFDeCJPBTmBaQCLFRZbqXV++qmp6J0z2taN1DlhalXLCyxUkIjifO4aNFm+ZOy9z7PKjvcBw9wOYtj7snzabfovHq2COCqp8OuLQgzTnzte3sPzXqHYxMKzh6rhveSjqsx65ZBf8wfmuKvPMOPzg4a88w6zzg9pwia7GrooJL21XJ4W/K0LoIJTYLWlPKNKVTKNUP0T94qYlKNkoLh6roUjrUiwZVG5+iuU7qOqOUxhrxuAbXVgU1Kz/ACmn1V0XTMV8iidJZaWJsYxodGxrRzsFjSSqSQ3SqN0ihdL5qJ03mpBM56ic8qF0yjdN5oSTOkQmRVnTeajMx6qAWzJdNn81UM3ml3/mpBb7xGJFQ7/zRCfzQkviQJ+8VETeacTeaAviTqpGvvzCzxMjbOEINFrx1UgeFnNn81IJkJNBsgU8TmkgFZjJeis08l3i6Emw0RC1o23801bKBSOFgBcbBVxMoK2qvHkve6gtFakRlTiS6qiQJ+9sqs6oolrJgyA66nRc1iVSAw6rRxSqLWho6XXKYpVEtdqs2zrhE8/7Ra4DC61w5RkfPReTGMVERLRqGiQDyO/4r0btNvBw8xrj9ZWVAA65Wi5/Jef0UjKWOkqnasa90Ev8p1/X8Fg5ZXEu07VCKrKlN4XCm+7L+ieSkyMg7LQooTclX66ijjlIDRbqqzXFhNtLBYutxrQ9KHR37Wrib2Jo2WFuhspRogpXCQOzHW1wiOiwb1wevTS4FJBZ1Yw6mdiVYyljc1r33sXbaBUXFA6d9P8AWMc5rr2BBsVKjkh3HA8y2Owj4DxCT4qinaPcoa/g12HU/eyVQkPMNbZTcFcXSTudQ1khe6143O3PkujxV7aqilba5tdZSUovDPYtlb1o8cFoedvpomm2p91C5jG7NCnqLtkcPNV3uULJhV4VsiN7lC+x3aD7KR7lA9y2ijzK0yNzIz9m3oVE6NnIkI3uUTjdbxyeVVcewEx9HhA6N3K3zTkoC5aLJxTcRsjuiax6FIuQ5yrnO3ELXolY9Chzp890IyggD0T2KDMiDkLpoezuiIB3RMHIwbqrNYpDC/ROiapGlVbNowzzI2gqZjrLTwaJs9Wxro2ubfUELt4cPwxwBfQUpPXuwsZVO1HrW1g5x4lI88jDn2sPcmwVmKOIOs+bOeTIhcn3XojMMwi1zh1LbzjCjqqulw2B7qWlp4jYi7WAFZuWdjuja8GspHAMc4yax5ByC2cNbdyyaiqdU1r3ONzey3MHjzZVlU0O7o705aanX4LFZoPkvL+1GsFTxCY27Rj/AI/Res0QFLhs9Sf8thPvyXhHENSa7G6p5dfxlt/TRadHwzUcuw4v1rcKFmqS3k0vdr9jOY0/EpGRuke1jGlz3ENa0bknYJ9ALLr+z7D6eGefiCvH91w8FzL/AGpLfp+ZC9apPhi2fk9Wp1cXI2Mflj4L4Op+GKZwFfXDvq97d7H7P6egPVcDZW8WxKfGcRnr6g/WTOzW+6OQHoFWCrRp8Edd3q/Ezt6XVx13er8RALSoYsjM53Kq00PeyAchutK7Y2lzjZrRc+S0kzST5EFc6aTuqGlY6SqqniKNjdSSTaw9TovrXsy4Ji4D4Ro8JytNUR31XIPtzOGvsNAPILxn9njgh2P4/NxjXxf3OgcY6Nrh8c1vi/0g/MjovpKwAXz/AErc5fUx5b+J8x01dcUlQjy38fwYnGXFNJwZw1XY5WEFlNGckd9ZZDo1g9TZfEOL4pVY3idVidbI6SqqpXTSvPNxN/kvWP2jePhj3EDOGqKW9FhTiZi06SVBGv8AtGnqSvHCV3dF23VU+N7v5Ho9D2nU0uOW8vkMUKdMvUPZErGH0M+JVsFHSsMk87xHG0cyTZV16t2M4FTULKvjDFLMpqJjhAT1A8Th+Q8ysLmv1NNz58vExuKvVQcjpOOK2n4A4DoOCsNkH0mqjz1b27lt/GT/ADO09AvJVf4hxuo4ixmqxSoJDp33a0/YYPhb7BZ6pZ2/U08S9Z6vxZnaUOqhh7vV+I6cFCkuo6gxbmbNGpPQLDrKg1VQ6T7OzR0HJX8SqO6hEQPik38mrJUgcK7hdJLV1TGQxOllc4MjY0XL3k2AHuqjWkkAblezdg3C9PHWVXF+K2Zh2DscY3O2dNa5d/pb+JCwuKyo03NnPdXCoUnUfL4vkjf40mj7LuzOi4KpHtGLYq0zYhIw62Px6+ZsweTSvGrrZ4y4ln4u4jrMYnuO/faJh/y4xo1vy/ElYl1S1pOnD0vWer8SlnRlTp5n6z1fj+AroSUky6TrFdCnKSAzXutrfVVzmkeGNFy42ARSP0V/BqS5NS8eTP1KkGlRUwpYGxC193HqVOmCe6gCKSZOEBNTMaX53/AzU+ayMXxB1dUnW7GaBWsSq+4hETD4nLEJsoxrkjGuRnFW8Kpu+m7548EZ0vzKpta+aRsbBdzjYLoIIm08LY27NHzUkljODuup7PeL8B4HkrcVraKtrsVkHc08ULAGxx7kl50uTYaX0HmuSSCyrUo1YOEtmY16Ma0HTnszu8b7deLsVLmYZS0eDQnZ1u9l+btB7BcHilVieOzGbGMVrK951+tkJA9BsErpiqUbWlS/xxSM6FnQof4oJee0hip44dI2BvopCLJXSJXQdQya6RKa6Alp4JKqojgiF3vNgtPirEY6SkhwGjP1UQDp3D7Tuh/M+yVDOzBMPkxB7QaiQZIGnl5rmnyOle6R7i57iSSdyVjjjlnkvmYY6yeXsvn+CN7hG0uOwCzXudI4vduVYqpc7sgOjfxKhAutjYTbBlynbLY35KIkkW80YbogJu/A2BRseHWUGVJtw8WUYICkjLXkgaHUIm3U8DxezgCN7FWRUNbsxvyChsgosaXSNbbdbFbAKjh6KZgJdRyGF/k13iafmHBUJZc5DgAHDY2Wxw4/6VVSYbPlbDXx9xc/Zk3Y7/dYe6zqPC4uwyrNqPF2anJOGqa6s19JJR1MkMrCx8bi1zTuCDsqy2TyjeLTWUFG7I4OHJekcIYq2fD8hPijNnLzVbHDmImirQCfBJ4XfojRDXM9SbVA7aIZJO8DmnYiyxo64cnKf6Zdu5CEo4jGqY0tbI07X0WYSuo4kg7w99zcuWeLHayAV1G7dFdA7dACUydMhIySSSkCSsl7JIBJwmv5pxugCBRA6oUrqCCVu+iNp0UQNuSPkgDLkLn25oc4G34oXOQCc66sRP7uPRVL3OpROksLAoAKiUyyEk3A0Ckik8IVdEx1jZAXGuuVM54ZEbbnRVYzqpP8RwHILKRlMlp6N8pAZb3K6TDaB2H0dTXOYJXU8RkDeVxssuhh1zEhrRqSeS1uOKKpwuHCqHvABV0zasxtuDZxIaHedhf3XFVk5zVPO5wVpuc4087/AEMCnhkloqyumeXTVDxGCedzd36fNeidhNRHh/FktDUyDusRpnRlo6t8Xztc+y4Sui+id3Ql7R9HbZ2v2zq79B7KbBsUmwLF6HGIbk0k7JQB9oA6j3Fx7rapDrKbXb5R0Th1lJrt8o+rIqKShmdFJu02uNj5hatNJyVigEGL4aySIh2VrXxP+/E4ZmH5Gyg7l0L9Ray8y2r8meXb1sLDJzJZD3+XW6ikfZVZZbDdepTnk9SnPJejqi2QPabEG63WVHesa8G4IuuPE3mtvD6i9K3XZdEWdMWX6xxkhcFz8r7ErWkn0Kwqx+SQ2Vi+Rny6qB8yikmVd8yEk75lE6VV3TKN03mpJLDpkBnVV83moXToC6Z7c0Pf+aomdCZvNAX++80Ym81midG2dAaYm80/erOE46oxN5oSaAmRtmWe2ZSNlQGk2XzUjZVmtm81K2ZCTTZKrVPLbVY7JVailICEpGr36qyzOllNtVCZ/CbKWhAs6aQ2a1VbwbU45eBu8smMqqGdpccp0voop6lsbHPJ2F1Rs6qcMlPFawF79dtFzNTK+qm7saA6k9BzKvVlTnuQb3WbilXDh8YgOkkzM8rv+nENT87fguarPkj17OinmpPZfHuPLe1nEjX4zRYdT3LaeHOR0Ljpf/SB81zFJQCTDqymc/M8tErel2729irNXiwxatrMTlbYyyGw6N+yPkAqUeJNp6mN7W2YDZ3m06H8FpwtQ4VyPMVeM7p1p7N4fg9PkdBgjRjWEakGppBkkHMt5O/RUqqkMJKs8J4bWRcXfRaJ7S4skJY7aZgaXW9SBp5rcxHDIMQiFXRStLH8jyPMHoV5lV9XUyno9T9BsKf7604Zr+WGj70uf3OVpxlfropZFJPSGnO9yFA92ivnieUcrg6KcJbkb3EKlVVF3BnTVTzzCNpcVmlxkcXHcrqpQ5nh31zj0IvVmjh1YaOrinabFjgfZenNqhNT5mm7Xt09CvJGOsu24exTv6BsbneKLwm6pWhzPR6Fu8N03zKVf9XO5vmqbnXWhjABlzjnqssuXOkencT9IF5ULiie66hc5bRR5VaoC8qJxROKjcVskebUkCSgJREoCVojjmxiUN05KAlWRzykFdK6G6QKnBXiDBRAqMFGCoaLxkSAogVGD0RhUaOiEgwSpYzcqJqsQtu4aLOR2UU20dFw9EATId10IqMqwsOcIoG8rq06o00JXK1ln1VOShTSNL6YRzWVjFdeFxubBRyVRAOpWJiVS6Z4iBPUhaKJw162FoKkGd9+pXY4HTl2WwXMYbTkvAXonCWGPqqiNjWkkkBcleR73Q9Lgg5y5BcZVrcE4V8RAc8F/rbb5uIXgrLuJe74nG5K9L7Z8a+k4sMLhdeKHwG3Ru/zdf5Lziy9Ho+nw0+LtPgP1Ze9fdqmtor4vX5YQdNTSVc8cETc0kjg1oXT8RVbMPoafAKR31cQD5yPtP8AP8/kqeAtbhtNLikrQXAZIQeZWbJI+eR0sjsz3kuJPMrqxxS7l8z49rjnrsvmRgIw26QarFPHmfe2gWpdstUsXdx+Z3UkWHVnEOK0WAYczPV10jYwOQB5nyGpPkE7pWQxOkfo1ouV7R+zfwM5sNRxtiMVp6vNDQtcPgj2c8euw8geq5LmuqNNzfs8Tiu7lUKbqPfl4nr3CvDlHwlw/RYJQgCCkjDM1rF7t3OPmTcrF7VuOI+AuD6rEWub9Om+oo2HnKftejRc+y7A2Gp0XyD23cenjfi+WOllzYXhpdT01jo838cnuRp5AL5+xt3cVsy23Z8xYWzuq+Zbbvz3nnk0sk0j5JXmSR7i5z3G5cSbklRFG5AV9WfaIYpkikrElzCMMnxjEYKGnbeSZwaD90cz7L07jnE4cJwij4Tw45YYmNdPbn0B9T4j7LD4Cp4cEoajH6tuuUtiB3I8vUrFrKyWuq5aqd2aSVxe4rkcetqpvaPz/ByuPWVE3tH5/giSTJErqOoScEAFzjZrRc+QTKniVRkjEDTq7V3pyCkFGomNRM6Q8zoOgQAJgpGML3Bo3OigF/AsKqcWxCCkpYzJPUSCKJvVx/QL2LtKxOn4P4Vw7gPCpNO7EtY8buF76/zOufQBZvZXhtJw/hdXxhiLPq6djmUwPPk5w8yfCPdcNi+KVON4nU4jVvzT1Dy93l0A8gLD2XnP/UXGP6w+MvweQ/8AV3eP6U/jL8fMq3uldMlsvRPXEmKV010ArpXTJIDJp4XVU7Y27Hc9Aujja2NjWNFmtFgFSwyk+jw53D6x+p8h0V4FAFdK6G6a6AO6TpGxMMjjYBBe2qzq+pMju7B0G/qgK88zp5XSO57DoFA5ydxsjpIPpU4afgbq7+iAvYVT92zv3DxP+HyC0LoBa1kSAK6a6a6a6AK6a6a6SAV0xKRKG6AclT0NOKibx6Rs8Tj5dFXGpAGp5KWtqBS0wpYz436yEfkqyfJFZ52RDi2IGvqbt0iYMrB5dVmzy90zT4joFKSACToAqEj3SvLjtyHQKUsLCCSisIj2RB3TdC4tHxI4w21wdeltlJIwDQ3xXudrIwGeajcLOThATNyjYfNSR03eF0gOg/NVwjhndG8WJsdx1UEBSgxC/wBonRR99J1/BWql3eloZ4gBuoRA8/YcfQKMgBkjnPAcVbbUOjAIuDyIOxVdseR4z6HkDuUpAcnoj1IZ0vGEH74oqPiaIAitb3dUG/YqWCzv9ws73K41wsV2PAtVDVzVHDmISiOjxUBscjtoakf4b/IG5afJ3kuexjCp8KrpqSpYY5YXlj2ncEbrCjLhbpPlt4fjY5qElCTovlt4fjYowxOmeGMF3HYdVLBE6xkaDePVRwydxKyVh8bHBw9QuuENDR4xTVGQfuzF4tD/ANJ53Hs78CtKtRwNK1VweMeV+AKKuL4mu6hXm1PmVm1dFLhFS+mLSA12n/fRJtQbK8ZKSyi0JqS4kaNU5s1O5tuWi5OsjMcpB0W+KjRZeIQh7jI089lc0Mq9kxOqTwWnVCSoLDlDdOhQD6JFMkSgF7lJLmkpA6dCCn90AV09jugT8lADGnO6cOsLc+qjT30QBk+YQkncoS4piboB7oXFK6ZSBJkk4CAkjkGziR5qxFUQR6kOeeg0VUC1z0QtbmNgqOKZRxTOt4HwSq424pw/CW+GB8oLw3ZrBqSfZafaBjNPi3aBiWIQkPoMOLaemA2c2MZW29SCV0vA1GOz7s3xbjKos2vr2/QMNB3zO0c4egufZeW1AEMbYMxLr55D1d/wvOpNVa0pr1Vovr9EebSxVrymtlovr9iF0j5pHyyOLnvJc4nmTur0U4dRlttWKhcBTUkoZJmLbt5jqu9o9Bo+ov2euL2Y3wpTUFQ4/SMKk+hy66mBxJjd7aj/AEr0zGqOehqHQVDLE6tcNnjqF8ndlfG8PB3F0FRK9jaCrApqsXtlY46O/wBJsfS6+1K9px7haOcAGenAa62t7c/cWPuvIr0MTk14r6/c8e4t8Tk14r6/c4CdzgFmzzEutfZXK18sZLXD8FkzE3uFpbz7S9vMlbLrutPDKosc6InQ6hYBfbmr1FJez83whdqng7lPBuyVG6zq5+YZgnfOLalVZpQ4HVbpm6kUpJ7E3KrPn80FS/K49FTdN5qcl0yy6fdQun81WfMoXzKSxadP5qF06qOnUZm1QkuGfzTd+qJl80u981IL4mRCZZ/feacTeaEmkJ0bZvNZrZfNSNlugNJsymZLqs1sinjkUA0GyKVr1SY9TNchJdZIrLJtFQYVOxygukW+8LiANzop6qoEcIpmHQfEepUMAyMdN93QepVSSS53VWbx0Q+extdZ+LSkRBgdqdSp5HAAuuufxipe4Ed4b2toVnI66MuHRm1wfgzMfx2OjlfliYDLO4f5cbdXE9NF5f2pcVQzfvF9K3I/FJjBAwf5dO0gae2Ue5XrLYX8C9l9RVHwYvxI76NTgmxZBu53y/ML5u4hxOmxLEzJT3eyAdzG4nSw5j1NysYQy8s7r25xT4Y6Lb7v6FGR8FDRd0Wh5fuPP/hZb3xHk/5p66bvJrWIDRYKuV1KJ4TlyOq4Zxt2GYtg+NtLiaCdkcwO5j8/VpI9lsce0NbwLxdWRUrw6jncJo2n4JY3atPyO64bDagQzuikNoZ2924/d6H2P6r1THYZeN+yehxUDNifDz/3fWDdxj3jcfbT/SuOtBRmm9vv+T6To+6nOk1BtTWqa/8AJfdad7OHlx+krBdznQv5tcLj5hZ8mIRi+V+f0WS8EON1NS2fnb9rcLRW0ILKMJ9NXNxJRnjPb50Hnq3zu10A2CUUwvZw900kZGtlGtkljCPNlUqKfFJ6l90YYW6g3F9Fr8PvyTvF9C3ULFo5Yy8MlJDToD0W/h9N9GzOvqVzVdNGfQ9GR45qpDZfA0K4iSL0WK91itaR+ZtisiqFnlc8VqezdvCyROeo3FM5xUbnFbqJ4tSqJ7teiic7zTudfZRuK0SOCpMcutoEBcmcUJNlokcspjlyG9zumJTKyRg5hXSuhunB5JgJhhEEARAqrNYskBRA9UARDZVZ0RZI03KvUjSXA9FRjbcq9Acg0KxqHpWfrZZsMnAaAndUrP7+wUZmJ5rBRPZlXLc9XlaSVUoInVdRnI8/RQSOMsgjabm+tl0WG0gpqdoA8cuntzKirPgj3stY0Hc1sv1Y7lzCKF0kgNtyvVMFgHDXDNdj0wazu29zTl32pnDT5C59lzXCGBy4jXQ08EZe97gAAN1X7feLo6f6PwjhsgNPQgskc06PlP8AiO9vhHoVw04urPhR7nS13Cyt+B9mX4dnteF73yPHsZrnYlidRVlxcHuswnfKNvnv7qtTwmpnbGL6nU9Aogr1Gfo7DL9o6BfRKKjFRR+N160qs5VJ7t595ZxOoEjmU8ekUIsAOqqAJAX1OqIBWisLBglhYHY25V6JmRoHzUNPFreymqZhSwOlPIaeqhspJ8jT4U4YqOPeLqDh2mzCFzu8q5Wj/DiGrj8tB5kL7JoMPpsMooKGkibDTU8bYoo27NaBYBeZ/s+8Af2X4W/fVdFbFcYAldmGscO7G+V/iPqOi9Rq6mGhpZqqplbFBAwySSONg1oFyT7L5vpGv1tTgjsj5TpS466pwR2XzPMe33j3+yHChw2jmy4niwdDHlOsUX23+X3R5nyXyaRYLqe0XjObjzi2sxl5cKcnuqWM/wCXC34R6nc+ZXLkL2rK26mmlze573R9qrekovd7gEKNyldooiu09EFXMJoHYlXRU4vlJu49G81TXWYHE3CMKkrngfSJfDGD15f1VZvC0KTbS03LXEVe0mLDaewgpwAQNi7/AIWMkSXElxJJNyTzSSEeFYQhHhWEJJIpwrFxnvEbHPds0XKxJZHTSOe7dxur2KT/AAwN/md+gVABSB2hbXDOBzY5icFHDo6Z2XN9xv2newWTGwvcGjmvT+EoYuE+HZ8enYPpEzMlOw75fsj3OvoFz3FV04eju9F4nJeV3Sp+h6z0XiS9omLwUsNJwxh3hpaJje8A5uA8IPpufMrhCjnnkqZ5J5nl8kji97jzJ3QJb0VSgoe/xLWlsqFJU93zfa+bGSKRTLc6RJJJIBkk6ZAW7pXQ3uldAFdK6G6e4a0ucbAICKrqBDHp8R2WUTz3JRzzGeQvOg5DyULnIAXEk2GpK2KOn+jQhp+I6u9VSw2nzv752zdG+ZWkCgDBT5kF0roA73SvohBSugHSuhumLkARchJTXTtAcbk2aNSUBIyQQM71wudmhUpHmRxc7Uk3JRTTd6640aNAOgUEsgjYXHfkoXaQlzIKuX/LHqVWukSSSSbkpEgc9VIAdYv/ADUjXNFlGE46ISTObcaIQ07gFEyTuwL6qbvy7d5UEEG24IRMbzUxtuZG6+d1E62Y5SUAMryfC06DdRDNfQke6MMN9UfdnohBFctN+ashwe31CgfGbaBTRxObYdEAPdSj4bexXeYhhr+0Hhd2NwgHGsMY1mIxjeaMaNnH4B3nrzXEtkbzuD0WvwvxTVcLYxDiNLZ2W7ZInatljOjmOHMELnrwk1xQ9Zbfb2nLcU5SSnD1lt9vacy+IxPLXaELsODYYOI8NrOG53AT2NTROdyePib7haHaHwbB3FPxTgDTLgmI+JltTTybuid5jl1C4jDayowjEIK6nfkngeHsPmFVyVxSzF4fyaKuSuaOYPEvkzsmTPxvDzR1DDHiuHjunh2hkaOv/f5rBmLonWcC31Xc8VUcOL4dR8cYA0B7mf3qEcnDRwPp+Vly9eyPGqI4hSACwvIw7tIWFtXWM7Ln3PsOS0uFvjCzqux9n2MoVOm6CSXMCqufS90Jl5XXpHroimb4jZQFWJDdV3bqSUK4skmSQkV0rpJIBJ7pkkAikkkgH2T3Q3SugCTXTXSQD3STBPZAMUkjumQDogQ0X5obJFAK5K6fs84Oq+NeJaTC6Zhs94Mj+TGDcn2XNwQvnlbHG0ue42AHMr26aWLsd4EbQROa3izHofrCPio6Y/k5y4rys4xVOn60tvucV7XcIqnT9aXnJz/a/wAW0WJ41T4FhLwcF4fZ9FpgNpZftyfMfIea83e7MSSbkm5KvGNkbCXAFoPPW6hNXE3QNA/0rShSVKChHkXoUlTgox5FTUkDqrTS2JnkNT5pjUxv0tr6JrB4LStjcCGQOcS4A33X2J+zB2oxcS4GeGcRlviFBGIhmOs0GzHeZHwn/SvjhoLSRYroeC+LK/gviOix3D83fUr7uZsJWHRzD5EfoVlVhlZW6MqkM6rdH2dxfhb6Gskbls06grjKi7SRyXp9FjGG9pfB1LjmFSd7njzWPxNPNruhB0K88xSkfFI5pbYgryP8U+HlyPIa6qfCtnsY8khCkoqj6zui8Nz6AnYFVpg5psqshsd11qWUdKllYOgdO5t2vBa4aEKu+W2qqivFRE0u0kYA1x69Con1FxuuiE8rU6Kc8irH5hcLNkmViWa9ws2d5B3WyZ0RkG+bzUL5vNQukULpVbJqid0qiMihdJ5qMyKSSz3vmm71VTIh73kpJLneohL5qkJUQkQF9snmpmP81nNkViN6Avsf5qxG9UGPVmN91BKL8b7qzG5UI3K3EVGSyLrCpoyXOa1oLiTYAc1Wbst3A6V9PTyYrJFdsd2RF22fmfb81DZpFEWKltI6Oha4F0YvJb753+Wyzn3BIO4VmmYKmqknkJNrvcSqk0rRmN9zdUybxWSjXTFkZ1ATcD8LzcZcSMhkOWig+tqJDs1g81SrTJXTspacF8srg1rRuSV0XaHjtJ2Q8BHh+nlH74xJgfXSMPiYw7Rjzdt6XKzk86HdQjj037Pv7PnhHm37QPaV++cYfBhz8tLHEaSja3TJANHP9XnQeS8Tpp7PLfvBHiVZUYlWS1dTK0ySG5A2aOQHkAqZcGEEG56raMcI82vW45ZWy2JqvWzwNtCq2a6uxuaW5njQjbqgdIwbNb8lbJnw51yVgV6V2S8YU2E4u+jxR3/5TisQw/EL6hoP+HN6tdv5XXneYP0sPkrtHIyl3aHAizm9R0WdWKlHDO+yqOnUynp5wanaBwjWcH8S1eGVLLd24ljxs9p2cDzBC5pjnRPDgdQvYnPZ2p8CNos3e8RcPQkwO+1WUY5eb49rdPRePSRPjcWuBBHJVozyuGW6NOkKPBNVobS18H51XcXDJHLDmGl9x0VNx1TMcYyeh3Cd7g43WkY4OarW6xJvcQK3cKxAvj7txu5unsufuFdpIpI3NkaNxcDqFSrFOOp1dG3M6VXMNVzOkEwKqVRBBKiZUZm+qZ0lyuJRaZ9TUuFOGCo9yjc5STNsbqBzrLpisng1ZNPDEXIC5MXISVokcU5jkoSUxKZWwYuQkkrpKSg4T+6FEEZaIQRAJgEQVGbxQQUgF0LQpGNKo2ddOIbBZTtdZRtCdyyep3w9FEhegdIdhuonOOqt4dSuqZgOXMqrxFZZpT4601Thuy5g1D3jw9ws0a3K6zDaU1U4fl00DR0CqUlI0hsTG+Eb25+S9d7NuD6SOCbiPHLRYRh472VxH+IRswdSTovJq1XUlhH3tvRpdGWvWVNfm3yS+hakmi7KuBX47UlseL4hEW0bXbwx28UpHvYeZC+W8UxCXFa6WrlJu86AnYcgu27Yu0qr7QOJZ35slLG4MZE0+FjW/CweQ59TdcAvYsrdU1xdvn4n5l0/0nO4qOk3l5zLG2eSXdFad7y+YmNuVaOwHIKGAXcTyH5qey7z5liCkYy6FoViJvNHoVbwTxNtZdX2VcF//iDxvDTzxl2E4baprDyeQfDH7n8LrkJ5nRRhsbS+aQhkbALlzjsvrbsi4BbwFwdTUcrB+8am1TWv5mQj4b9GjT5rgva/VU9N2eZf3PU0njd7HZtYGgAAADYDYLwz9pfj44fh0PB1BLaorgJa0tOrIQfCz/URf0HmvYOKeIqPhLAK3G691qejiLyOb3fZaPMmwXxFj2O1vFOOVuN4i/PU1kpkd0aOTR5AWA9F5vRttxz6yWy+Z5PRVr1lTrJbL5mcRpohOikKjkNgvoT6lIieVEUZKE72spJLWF0RratrLeBurluYhOJpGxsP1cQyt8+pUFDH9Aor7Syc/wA0Kjd5KrV5GsmRIVJYZKSVsMTpHbNG3Up7LOxGfM8QtOjd/VAVHOMjy5xuSblSNahY1TRMzuDRzQGzwpgxxbEo43A90PFIejBv89l0HGmMivrG0UJApqXwgDYutY/LZSUIbw1w+ZrZaup+Ecx0+Q1XMkkkkkknclcsF1lTjey0X1Zw049dWdV7R0XjzYJSTpl1HcJCnSQCTJFJANdK6SZAWQlzQ5k90AQuSqmIVF7QNOm7lNNMIWZjvyWY5xJLjqTqUALihYx00jY27n8Ezir9BB3TO8cPE/byCkFuNrYmNY3QNFk901011ACunQXT3QBXSugBT3QBXTEobpEoB73KCofb6pp21d69E5f3Tc3M6NVcqCBKjUTd4+wPhbt5qeplyMyjd35KmpJCBQkXcSkTlSBQIWxRtyg3QDXVPl6oQO53TdMXuPNDuUkJHBIO6IPKBE1tzZCCUSKS7iNGu+Sjj8Jv7KTOTu8D1coATAQQXAgDqmfLl23Kjc64vmBI80D7mxTBBIHBx1KNuW/xKv6Im3UYIaPSOy/jijwGWfAcfaKnh7FR3dREd4XcpG9CFldp/Z1WcF4qDEfpWG1I72kq2DwTRn9RzHJce17TuV7B2Y9oWE4nhJ4E43Pe4TObUVY860ch0Gp2HntyOm3BVhKjLrqaz2r6nBVhKjPrqevajhOzzixmAVz8PxEk4TXeCYH/ACncpB6c/JaPFWEycI4o+eh+spZtXNHwvb1aVD2o9mGKcAYoWys76hlJdBUsHgkb+h8k/B+PtxiiHDuIys7wC1JJN8Lv/duPLyKzqcMv9TS1T3X18Uc1eKf+qpap+svr4o5yto2VbXVlB4mHV8Y3HmB+iy8110GKYTWYJWSy07HMyG0kR3Z69R5hZz46OviD4nGGr+013wvPl0XZSqpxzuvO530Kqccp5Xncz8yB6J7HMcWuaWuG4KErpR1pgpk5TKSR0ySdAMkkkgEkknQCSTJIB04CQCJrboBBqcjKNd1IG2F1cgogwCWp3+yxUlNR3M51FHcpx04bGZZvCOQ5lQEX2+S2pMHq60mQtLI2i6q1OFyYbTtnn+KQkRt6+azjWi3jOpnCvFvGdewzjpok0XKcWJ1XofB/CGHYVh7OLOKwRQNP9zoRpJXSDkOjRzKV7iNGOZbvZdrJuLiNGOZb8l2s1+AsDw3gjB2cbcSwtkldf910D/iqJPvEfdHVcHxFjGIcQY1UYriE7p6mpfnkefwA6AbBS8X8T4lxVizq+reAAMkMMekcEY2YwcgFixOkLtSbc1hb0JJurUfpP4dxzW1CSbrVH6T+HcS1UhLWgH4fxVT4+qsOlBNy29uSB1Q7l4R5LsR2ohsQpWy/MIXTl24BPWyFjbuJ5IWLAkF9ATfXRTxyE/Yd8lUE9naWACsR1Oo1UNFWewdgPatP2fcRilrHudgNc4NqQdoX7CQfk7y9F9O8X4FT1VM3FKDJJTztDw6M3brqCD0K+D4Z3tHhJX0R2D9rwwGGLhbieoL8HnAbBPIb/RXH7J/gP4ei4rmiprHnPnc47ikprHnJtYjAWOIssapBAzD0K9V4x4RFL/eae0lPIMzXN1Fl5rXwdxIQ4HLexC4ITlF8Mt0efGUovhktUZbXuBJadRuEf0gaXOhVepJikOQ6cioZJC6PTcG5XXCfM6Iz1TLUkw6qnNJmuo+9vzUcj11RZ1xkRveeqgfJ5p5Haqs9y0TN4skMijMijL0BfqrGhL3qYyKEuTZvNSST50TZPNVg9SNddMgtserEb1SjKsxkqMkl2NytRPVGMq5CLlRklF+LVXYmlVKdh0Wth9JLWTtgiHiPM7BVbNIos4ThsuJ1Tadnhbu+Q7MbzJXRY1iUYgjwmiZaFgDGgf8Ae5OpRsbTYPh4pWNElTKbk9fM+Q6K3RYLDhlG/Fq5xAaPA0fEXdB5+fJZuRtHQxsVgiwfDY6EG9TP45j0byb8/wAlyGIyuDSGG5Wni1RPV1Ek8hu952HIcgFoYHg1NhFI7ifiUd3h8NzBA42dUvHIeXUqrkdNKGX3AYHR0/Z9gT+Mccja6tkBGG0khtmd98+Q3XzBx5xtXcYY9U11ZO+UOkc4Od9px3db8AOQXXdqPa3Xcc47JKHf3NhyMY3RoaNmtHJo/E6rgpYWZ+8jYCH+IGy0pxxqzO5uOJcEdvOnnd+wyHSeRShj7+QNvpuT5LSkD7WIJHmFVL2wh2VobfpzW2ThwBUvyDK3TkPJVcxPMqzFH9LlsXNaLXJdsEb4Gs2LCOoKjiS0NVSlLVbFQPc03BVgSOkabb2QlgO1k8eRgI3J59EZenFp4b0NDhbiKt4WxemxKhmMU0Dw9rhyPpzHIjmCux7QMIw/GqJnGPDsTY6OqcG1lKw3+hTkXI/kdqWn23C88MZvYC66XgriB2BVr4ak5qCqb3U8bxdjmn7w6c77jcLGrHXrI7npWFRNftq3qvn2Pz51Zy5uluLLpuLuHDg1a50UbxTyeOMnXwnUajQjzG65hxstKdRTWUcd5aTtajp1CaOISQPy27xpzW5keSenrO7b3br5dwRu0qFrnsyyMJBB+RVmnpWVsmjxG61y235KZYSfFsRR45SiqXrfMsUsxkzWsSNTb81YL9N/ksp7ZqCcEHK4fC4bFSx1md13WBJ5DQLKVPOq2O6je8K6uppJFuR19FWfoVKeqik3URRas21kAlCSkShutTglIdMmKV1ODPI6SZOhORwjBCBOAoZeLJAUbdULWnorEUN7XWcmkdlGEpMeOMuVtkOyKGA6aK7HCLC49lyVKp9DaWTa1KZisFDMx8OUuaQHi49F0UOEPmDX5G5RycbX/wCFnYph08bxJM7NmNgR/wB7LKncRcuHJ6F30TWp0nU4WZkTM7gulwejDgCAQs2gw8yPGmi9Q7PeBK3inEGU1NHkgZ4p53aMiZzJKwu62fQjud/QdlGjGV1cPEY65Zpdm/ANRxRiIFhFSQjPPM7RsbBuSVm9vXa1Svij4N4Vf3eGUnhzM07x1rGQ+Z5dBr0Wj2xdr+G8K4QeBeCJB3TRasrG7zu8z08ufpv87RufPK+eVznvcblzjck9V0WVnpxS/wCfx8/Df579RfqCVWpww0a0S/8AFdr/AN7X/wAV/uehtbkaAk4kbC5OgRI6ZmdxkOw0b/VeufDMljZkaGjkjAT2RNCFB2NurMYFtdlFGFZpcPq8ZxCkwbDozJW10rYY2jzO/p+gKpJmU2ekfs/cCf2q4pfxNWxXw3CHgU4cNJajl7N39bL6gIIWPwXwpR8F8NUOB0IHd00dnvtrLIdXPPmT+izu03jeHgDhGrxd2V1UfqaSM/5kzvh9hqT5BfO3FR3FXT2Hy11UldVvR8EeIftKcenF8Zi4QoZb0tA4S1hadHzEaN/0g/M+S8Yy20U80k1VPLVVMjpaid5kkkdqXOJuSfdRkL36FJUoKCPpbagqUFBETlXlN1PI6yrO1W50kZVnDqfvpwTsFXsXOsNytejiEMOm7h+CAmmfndpoBo0eSBOUyASSdKyAinmEETpDuNAOpWNq4knUk6qzXz97L3YPhZp6lQsbdSA2hb/CuGCsrBNK28UVnOvz6D/vosSKIyyNjaCSTbRdfPlwXCm0sZ+umHiI5df6LGq3jhW7MK8njhjuytjuJfvGtJafqo/Czz6lZt0k11eEVFKKNIQUIqK5DpuaSRVi4kySYoBJJk6AZOmJsldAHdOCguoaqfu2ZWnxO/AICGpn72Sw+FugUDnJr2CA3cbDUlATU0PfzC/wt1P9FqXUFPGIIg3nuT1KkzIA7proS5NdAHdK6G6V0AV7J7oLpsyAMlNfck2A1J6BDdBO/aEer/0CAF0hldnIsNmjoEznBoLjsExVapkucg2G6AikeZHlx5oCbFIusm+LyQgYkuKNum+yYNA1SKEhlzExc1Nk03CWTzCEC8wNEk46DVOWm17IAUTHFhuN0Nk49EGQnyudvb2UdkWUEXuQmsgFtsja87GyEMJ2BRhhHNQGM5xvYbIQn32Ti/S6EDt81biLXkAkKoA7popmFt+arJFJLQ9j4A7VsPfhP9i+PY3V2ASAMp6wjNLQnl5uYPmPMaLme0zsrrODKhmIYc4V+D1A72lrac5mPbuCCNFxkb2W1F/ddtwL2pV/BjHYZPTsxfh+d158MqHeEX3dGfsO9NDzC4JUpQlx0t+a5M4HScJcdPf4MyKHiGXianbRYgc1ZEwiOT4XSADa/M+R3XKVMLRMTG+xvsdCvXOJezfB+MKGTiXs4qzUxxjvKnDXeGqpD5s5j+JtwvK69s1RO5s8ZjrBo+4t3h6+v5q1s4qT4dO1dn4Frwxk+FY7V2fgqmpc9oZOM4bs4bhRvY0eJsjXN8tx7KJ2YEh1wRobpl3qONj0VHGwbm8wgKQJCRN1YuMnTJIBJJJIBJJJ0AyIBIWCcPA5IBw0lTRN1sBcqAyHlohzO6lQ0Q0zZpWwQHvHua+QfIeilhmgNT3sxc4/Z5BqwQ4jYlX8Kp3VtQGvlyMYMznE2DR1vyXPUp4Tk2ctWkknKTPQKIRNw810wEcEYu7NpYdf+9VweMYnJjmImRrHBvwRRjWzeXutfEq+fH2xYXhoMeH0wu6SQ5Q8/feTsOg/VWKeai4Xja6gBlrSP/GSs8Q/+Ew/D/M72C4aEOqbljM3suxd5wW8OpzNrM3suxd5bwbhrDeF4mYjxDGKvECM9PhIda3R8x+y3+HcrNx7GMR4grnVmIVHevtkY1oysiYNmMbs1o6Ko/EHVD3PeHEvOZxcSS49SeZUMkwdtcLaFOXFxz1l8u5G1OnLi46jzL5dyIpCWBV3SXOpUkhDhYuuFWc0X0cuuKO2CE4WG6icFK8WNr39k12gea0NURAeRUjLja6fKDrc2Tl1hYC6kkC/Rgv6KSMvB5BCyzjvYqZlgN/wUMhk0czzoXOt0utKkqpY2hrZXAdN1mMLb81ahlG2ULOSMpI977Ge3N/DcMfDfFcj63AX+CKYjNJR3/8AVH5bjlpovWeKeD4ZaZuJ4ZKyroJ295HNEczSDtqF8dQ1LWOBEdl6P2c9teM9nswpmsbX4JKfr8Pldpru6M/Zd+B59Vx1qKqePaclWkqm+/advV0bo3Oic2/3VizNdGTbkvVYqbhvtMwl2McHVjZnNF5qN3hmgd0c39djyK4nFMFmjc6OWJzKhpNwRa//ACuJSlSlwzPPzKlLhmcpKbm4Nj0UQn5O+anq4nMcQRYhUH35rvhJM9CnLJJI4HbVVnuSL7KJzwd1tFnTFicUBKTnBRly0TNkwi5NmQFyYOVslyYFSNULXKVhUZBYjKtxqrFqrcRaNyobLFqJq0KaMaXVGGVoIsLq7Tza3I06BVbLI28OpXVD7AHKB8VtF1dE+OniZHAxgktYuXI09dK4AZTYcgbLq+G5YJqmOIteHHQaX/8AssZSNYo3sEwCSpqWzSXkeTuRsg4vq31c0WFUbnSRwH6wjZz+nsupYZmMOHYa0mcjLJIBpEOg8/NYvE/FPCPZPRCoxicVGJvbeGjis6V562+yP4j+KqouWxbjS3MpmAYfw3hz8f4mkbFTQNzthc6xkPK/QfmvnvtY7Tq/tArnR53U+Fx+CKFgy3aNhbkPL5qLtC7TsZ7RcUNRiUvcUcZ+oo4nfVxDqfvO8z7WXF1M7MpaHXWsY4IlWbWEUHQU+1ne6o1Uovkiu1rdtd1ddM1rwXXcBy6qm+KOTMQ8t5+ILZGLKbpXDd7v9yjeTJu4+6dwF9HJmtGYXNx6q5CBuWNLeRKbMpZGAk2Fh63UJbbmoLvKHvdLVNlcDYgo2jTW10JjlhCVw0uUTZXEgZj81BbzRsygjNc+ShpGsZyyd3wjxJRS0Y4d4mzy4S4nuKlozS0DjzA+1GTuz3Gu9PjHs9r+GpGTWZU0M7e8p6undnhnZ95rufpuNiAubgmYx2jbLseFO0Wo4chkw2sgZiuBzm8+HTnw3+/G7eN/mN+YK5JKUZcUD3KNSjUpKnXeUtu1eH2+Rw7C2F/iaHNOjh5KSWjfGGvhfe+oF7H1C7zGuAqHiOjmxvgepdX0kYz1FE8AVVGP42Ddv8bbj02XERRyNH0KoJjsTkzcj0PkVoqmdVvzRyztOB8LWYv1ZLbPjy8Ht2cxNroaqLuK5rmvGglaNR6hUp6d0L7Ah7d2ubs4KWpiMT3Me1we3TXcKDM62W5tvZawSWsdjiuakp+jWWZLnz8H2/MlgqHR6OBLfyVlwD2hzbW8lRRNeW7EpKOdURSuHFcMtUSOFkJSzhyYqURJp7DJwkLIgFJVLI1k4CcNupWQkqrkawpN7EbWXUzIiTsp4qfqFajjYwXeWi3IlYSqHp0LFvVkMNP1C0KejuLEWRU81IB8QcfJadNNREXlkDR0BXFWqyXI+o6O6PotrM17yCGjc4hrASegWxRYSIxnmALuTeQR01XSWy04bbmf+VvYLhQxKQF84DeQaLk+gXl1q03psfb2NhbUl1jaljs2/JnMhc/wMaTfosXFA+prBSsALYz4iNdei7HGqltDfDcNivUu8L3jUsHS/X8l0HD/AGeYZwthA4m49qhhWG/FFA7/AMRVno1u+vVRbqWcpZZl0te0VS/llww+L7kvn2czL7Ouzio4ic6eZzaLDafxVNZNoyMevM+SbtQ7bsOwjDJODez9vcULbsqa37dS7mSf0XJ9p3bfW8WwfuTAacYNw9CcsdNEbOkHVx6leVkr2LWxx6VTn593z59h+a9NfqOVdqFHSK2XJd/fLv2X9dfSHkc+eUve5z3vNy5xuSeqnaMoAGyjhbYZlIXWXqdx8e9dWJ13EMb8TtFcY0MaGjYBV6VtyZTudB6KyFJRhBG0XQNUjCobKSZKC2Npc7QAXXuP7NPATpn1HHGIRavzU+HtcNhs+Qf+ke68g4V4Yq+OOJqHh6iu01D7zSDaKIaucfQfjZfa+EYVSYJhdLhtDEIqWkibDEwcmgWHuvMv6/DHgW7PI6Sr8EOrW7+RZtZfJPbnx5/bbi91HSS5sKwkughIOkst/HJ8xYeQ817f278fu4L4SdSUMuXFsVzU9PbeNlvHJ7A2HmV8nNiEUYZ0/FZ9H2+P5H7DHoy2/wDyy9gBCiepnaKvM6wXsI91IryuuVA4o3lRgF7g0blSSWaGDvZMx2C0+ajp4hDEGgandGgHKEpykgEFFVzfR4C77R0b6qULJraj6RPZvwM0Hn5oCBjbm5U7RYJmNU8EJmlaxovcoDV4epAZDVSaMj116oq2qdVzulO2zR0CmqXikpWUkZ5Xeeqo3VIrL4jKCy+NiSSTXVzUV0k10roB0yYlK6AV090KV0A6Sa6V0AnODGlxNgNSs57zI8vOl+XRTVUuY92DoNXeqrlAMSrFFFc967lo1V42GR4aPfyWg2zWhoFgNkAd0robpXQD5k+ZBdK6AMFPmUeZK6APMmvohunGuiATpO6YX2udgOpUTQWi5NydSepTOf3r8w+Fujf6pXQDSyZG358lTuTdFLL3j9NhsgQDW59ETZDyaPko73KMEjZAFmJIzEBMbcgk113C4unccuwQgEuKa/VPulogEy+YWCmHk4XUTdTvb1T5mja5QE1m+aFzQdjZCJHO2YFMO6IGYjz1VW8FWyu5th8SYA9SrraeFzb3On4qFzHM/wAvL7JxIcQLARoTukYy25AJCNgN9h8lbiie8XAuOllVywVlLBnFxJUjGl5sN1otpm31j+QWhFSQlze4aGm2pcLm6pKskZSrpGDkLvs7KWOHNuCPVdLTYOxtzlYXH7Ttbe2y2MP4OqapzTHC+S+vgYT+QXNUvYR3OapfQitTjI6XMLBpPsrLMOdpeJxPyXq+F9nvfEd8ypjBNjki0b811WG9ldBe7+/kJ2JH6LyavTdKLweTV6bpReDxHC/3hhFVHX4ZJPR1UJzMnheWvafULbxnHsN4ty/2rw809edP3th0IBcessOgd6tsfIr3CLsfgkZdjZQP4o1l4t2QlrbRtsd75Cuf/q8MqUotd5h/1ZZUpQa7z55x3g2soovplNLDilB/+7oyXZf52nxNP8wC5l8RbqCHDqF9GS9mVZQSCogeGSDS8ZLSuV4i7PMPmLn1c0NJOd5YyAT6jYr0bbpmnLRvJ6Fr01Tl6LPGUl0WO8Kx4U4mDFqGuZ0jflePUH+qxG0+ckMe3N91xsV7UKsZrii9D24VoTXFF6ECSkkp5YvjjcPZRq6eTRNPYSSSSkkSSSSASSScNLjYAlAMkpjA1g+skaD91upUtLDRySD6RUPiZ/CzM7+iq5JLJVzSWSs1tzutWio5JYgx57mnJub6ZvlqV0GD4fw7mb3dRnkPOXQ/0Xa0vA0dUGHL4n2LWue1uYdbkrzLnpGENGseJ5Vz0jCGjTR579JexraehpXtib9twF79QNh66nzRjAZZLSPbMXP1JOpK984U7H6cSd9UxRPGWzWXDxfqurPZhTsFiy4GwyjReRLpqCf8Uc955MullH/FBvvPlo4DMxt2xvJ8woZcIqWg3iPyX1DWdmtH3Q2id1yaFcxifZg3xOZPAba6kBVh05HOJLBWHTSziSwfPE1E5rfFGW252Vb6FncAH79QvYcT4GphM2H6wSSuysb8QLui5HF+HhhVVJBNGxskTrOY8WsehXrUOkYVNj1bfpGFRaHGT0Rp7A5nX10VZ/hN7fguofRxCkfVFj2RteGZg/Qk8gCsqsjjlb9U25vu4Bd8K3Ed8K3EZJlLtLlTNpXOF2v9+SlnoqikLRNAYy4XGZtrjqFao6DEKsCOKmeWHX4LBaOaxk2c1jKMw/VyFt81uYUsbcxFiVpU2FskqGCod3cebx5WXcB5C4Wph2G0ZrS36PPNFmOVrLZiOV91WVVIpKqkYkbXbkA38lYhpiXA5SV2mHcOfT3GWOOjp4uTc17fO5K6HDuEpY6lsdP3NRc/E2Lf5hck7uKOWd1FHn1PQSzHwst5WV2LBg92VzLHY6L3jCuxyB2V8tfGXEB1g0gX6XIXXUXY1hZYHF4kdptay4nfcTxBZOT945PEUfOuA02KcO4jFieDSVVJVxatmgcWn0PUeR0XruHdsGG47Eyi45w00VXazcTo2XaT1fHuPVt/QL0cdk1EyHu4zIGDYA6LFxbshw94dnsZQPCZBdUnXlj+WOhWdaeMVI6HC8R8OSd0MTw+eDEsOk+GrpXZ2H1tsfI6rjqmLIvTYuzqu4fldPhNb9Ee4WcYfCHDo4bEeRCyMV4PqKsvlqDSwSt1dLFZjT5ubsPaypSuYp4T0M4XEYvC2POpdFXc+yv8QU8eCy5Ja2imB5wTB1vUclkiSKoZnhma4dF6dOplZPRp1crIZeozKoJJsm5Cruqh1XTF5OuMsl3vQm73VZ5qx1TfTB1CujZGo2ZTMl81jtqh1U8dWAd0ZJtRPvzV6HVYkFWw8wtOnqW6WIVGy6RsQR3K1KaFptdY1PV6gWt5uIAHudFqQ4tg1MAanFoJH/8AQoyJXe7vhHzKxlI0SN6hpHSPayNhe52gAFyV3mHRYVwJR/vrirE6XCmFv1bJHfWu/lbuT6ArhaPirG3QiLheghw0PFvpRb39Q70c4ZW+wUuG9hNfxdLJiuPVtbLVSH/EqM0j3D1J0HkslNZ1JcixxV2+109O6i4Lw2Wgpni30+ojvK8dWt2b6m58gvHq+gq8TqJausfPU1EpzSSzEue89SSvqrD+xzB6Kkip2gBrGgAWupn9kmFOaQCAP5AtG6nYUWD4+lwN9jenuP5Vn1eBThneR0osD1ufkvrqu7GKd7TknaR0yWXDY32Phs/dyVMNK03Ae45rnloNfwUKo1ui2Ez5ompKixa6LugdCWtsVmzYe1pOaVxPmF75ifZXiWGOcaeWKoOUnwEPuPT/AIXHYtwzh7MOfJWU7H1okADISYwWczcXF/YLaNZMcJ5Y6gOXO25b1sq5haDYuAt15rv3YJSx0zqrDXMiLBaSCd93+oNwHD2v5Lma0Nc4h7Iif5Vqp5I4TDdva11G4kaWWwyjp5mnMDDYaPHw+hVTumDcOI62U8RqllFHvD0/FJpHQhaX0GMhrm3eDvYWsjbRwa3D7dP+VDqI1jbzb3KHc3bm2t1G6ZrBdbMFAaqzWUrydvC0krYoeB8UnkyNomMLtLzSNZk/3OFljKvGO7O+n0bUqPMFp7TlRG940j08kTaZx+wSvRYezmeH/wARX4cGg65Js5/8oK16TgDD5BYTGU/wMP6rjn0hCOx9Bb/pmvUXFLTxPM8Lqq7BK6Kvw6oqKOrhOaOaF5a5p9Qurn4o4e4uvHxVQ/u7EXf/AKpQRDI89ZYR/wCplv5Supf2aZx9TSTP8y1ZmIdl9UyJ0jcPcXDkTa/4rD9/Tk/SO9fp2tTi+qqR8M7+zBxHEHC1ZQUoq4pYMToBpHW0ju8YB0dzafJwBXMFvNejR8IYvhMhnhY+kcRYmOQC46HXUeqysUwBk7i6WOKCbm+Kzb+rRp8rLqo3sF6Ocnk3n6buZrrEsPs5Pwf395xhSutCtwaekuQ+KZnVjxf5Kk2AyGzSL/ddoV6EZxkspnylW1q0p8E44fn3ggp7pPikj+JpCC6tuYvMdGFdEHEKO6V0wFMlEhCITP8AvFQhye6hxNI1WtmTid/3ikJCogUQ1VcI1jUk+ZOx56qeJx5KCKJ7wS1jnAbkC9lpUOHSzm7niFnMkXPsAsakoxWp6dnSq1JJRWS1hj5e/YLF9zbKNSV6vwjw3j2JUUk1M2PD6RotPiFU8RQwt5+M8/S5XAYbidPgDg+gwsVlSP8AOrNWj0YP1KkxTG+IuL5Yo8XxCpmiboyEeGGIfwsFmgey8qrBVJcUtEj7eyuq1pS6miuKb7dl9/l4noFT2l8G9mkbouF6dvE+PDQ4lVMtSwu6xs3efMryHivi/HeNsUkxTHq+atqX7F58LB0a3Zo8guwp+zeaaNt2gm24O6kf2YVTBdkId7KaV7b01iJw3fQV/cz6ytNNvv8Ah+FoeXOiJ5FA2DO61ivQ6ns/r4jcUpPkRosmfhiuhzF1KxvloLfiu2F/Tlszxrj9M3MNXHPhqcu5oaLKO3ePEY25+i2qjC5o9Xw/7XAqpHRd2S5zHAu3vyXVCtFni3HR1WGjWPeA2wFgNAiBUjoWt5n3CHKAtVI82dFx0YxdbQI84jjLygDSTddd2W8Dv4/4xpsPe0/u+m/vFY8bd2D8Pq4+H5rKrWjCLnLZHPUjwxcpbI9t/Z04COAcPv4jrosuIYuAYw4ax04Ph9Mx19LL2KWWOnhfNNI2OKNpe97jYNaBck+yjhjbFG2ONoaxoDWtaLAAbALx79pDjx2D4BHwtQyFtbijc1SWnWOnB1H+oi3oCvm6U3dVs9p8uozuq/ieMdo3Gb+PuL6zGbkUbD3FEw/ZhadD6uN3H1XLO1Qh2RjWgaWTF2l19PTiopJH0dOmopJASGypTOuVZmfoqT1obETyreHQXPeEaKq1pkeGjmtWJgjYGjkpBKmumSQDpJt0+2uyArV8/cw5WnxP0HpzWZG1SVMxqZy77I0b6J2CyAPYLWwqIQRuqH8tlm08ZllDeS1ZnBrGxN2G6q9dCstdCKSR0jy525N0N0k11YsOmKa6V0AimSukTogEmSTIB0kySASV0xKa9kBQvzO5QkpXRwszvuR4W/ipBNTx5G3PxFTXQpXUAK6V0N0roAiU1010iUA9090CcFAFeyCWQhvdt+J256BO5wY0uOw/FQtvcudq52pQBjawGiiqZcoyDc7+ikc4MaXHkqb3Fzi46koBr2T6lCnaeSAQTgpy030F0shCAYuPLRHcuaCTohsQL2uEbRmGu3RCBvD1ugJ10CmEf8JslkbzGVQMkW+6Qbc2AJKkEIP2/wAEQZZhaw77lMjIzrBga4gEdEDS0dEu7H3vknADUICL3HmfRTtqZJQ1rrBrRYW0VfU6KWKNgIfckg7KrRVosscL7tHmSrD6lsL7RPc8DmDZZ7hqbXQW13Ko4ZM3TT3NiLEmsN3tP9VZZjTw4FjGRt26/mskZxTZo3ZbX+Lc+l1VjvI8NaSXONgOpWToxe5i6MZHobMdip6aI00FNJKHazSStN/IM5e66HB+KK2atFXiBje9rg2z5ba+QH/2XlkWFSPDC5jjmvtIxttbcyuzwPhuCFtLVQUNLNMX5HxVX94ba181vCy3vdeVd0KKjq/PvPIurejGOr8+8+heE558RjJbGx2v2XDRd1QYbV7mEBtt+8AXknB1Jwpg0UlY6mE9Y/xFsERyxdQyOMuDR7ld7hvaJRPBioMLxWYx2BzQ9yB7yEH8F87b0aam5NvHuPEt6NGM3Jt4OxYK+E+COGw5PmOvyauG7TOI8QwygBZLh1NM85Y7TSOcT/KBqoOKOOpHUrzU4RKyJo2NawE+zTqvm/tDxeLEalrqenrKVrSb95WGS/lYk2XdTSuZdVF+j7DuU1cS6mD08+BPxL2o8V00ktPJjkRJ0yxQAj8SvP8AEuI8QxIf3mpL7X5WVWpkzu0zH13VR4uV9NbWdKkliKz4I+itbOlSSxFZ8AXOLjclMnyprLvPQDE0jRYPdbpfRCXX3ATJKMEYEmT2TKSRJJ0kAye6VkrIBk6VkrIBw4jUEgrZwbijEMJqe+ilLzzEhJBWQ1g5i6mYyINJJIPLS6yqQhNcMlkxqwhNcMlk+huzntrqnGKkkwOmOW396bWZWN9Q65+S9x4U4nxfiPO99bhRI2hhqHZgPO7Bf2XxHgmMUtAWmZj5ADqGsFvzXqHB3HVAxwjpG4oJjsIm2/EvsF8xdWsraTlRjiPdn7nzdzQnbT4qUfR7tD6vq6bEzD4G4fm6vc9y4viirnwmjlrKqhFUYRciFzdR1sbLkaDjfjmeSNn7vqZaIN1IqYDUHpo7T8VR4miqccgMmIM4vpG52tLZamCON5J0aAxwuTtovOryhWa5e1P5HJcShWSw/in8jz7iLtN4fqajuYIDQyNJPexvOZp8wBZcXXcSmYh0tf8ASBKCSXsDj731W7xtQDCGeLAYaSnLzaSBtpcp38bmanzXmT+6ZI8sE5ZmOUOcL289N19BYWtJw4oL5M9axtKTjmGfgas+NVEkYhMgfECSI3NGUHqAo31UJYLsAf5NsFVo3NlzhkRLhqCTsnla4m9gCvUVNLRHqKmloXW1Anex0pEwYMoBPwjyT1FfWzSd1Ex9raZSbAKnC1rvDJ7C9grlTCadjWmcx3H+G0XThSY4UmaGHV/dMBrWwC2gkddzvQDZakHGE9Jf6LVSRAbGNoafwXHPmbs4F3RW3UscMIkqXiK4uGCQF59hf8bKkqKerKSopvLO3w3tGdh7RG897FfVrR3Zt5EXXXYV2qUpq4IKKnZE2RuWSTEJ5HEOPPMLAAeQXisMVFKfHUVLB/8ACDv/AJl6Nwf2cV+PWbDLV0kJAd9KqaNrS0/ZDTnza8rBctxQpRWZHPWoUorLPpfgOsp8QgHcY3h2LyWGZtM5p7vqDrc+pAXolPSzxsu2NoPTMvE+zzs/wnAKhkUtVSyYo5rnRukdFHKMps5zMrQ4gHqSvUYcQqqCnjim/eOJva0NdLTTsOY9SLNAv5LltVTi2+RhbOnFt8jpTK6FhdIx5sNcouuZ414mpsJwuSeSnaQ0XtLI2In5qHE8SqX0xdFRVcb92ukrwC0+lnBeIdp0uMT1DqqtqKdzSMobcvfYc7hoH4K91dcS6qL389ha5u8rq4vfz2Gfxr2y4nIx8FDHSwQWsA1mci3PMV5FjXGuM4mXOqq+oeD9kusPkrGJTd5Jl1NysCtpwXOy3IW1tbQjyL29vFboyKysmncS5zj6lVYqyppnZoZpIz1a4hXpaRx5KB1KV6cUksHpxSSwSt4lxPZ8/e/ztBPzRDiOpPxMafRVTSnohNMVPCuwuorsLhx+U7sPzQ/v1/3XfNU/ox6JfRj0U4RbBeGPyN2afmi/tHMNmfis8Up6IhSHomEC7/aetb8AYD53KGTinF3izat8Y/gFlWFGT9kqRtDfdpTC7CSL96Vcj800z5STrncTdatGyaoLXxvLf5SqYw6+zT8lo4fSTRPBaCFWSXIlHXcPcY4twtUM+i101hrYg5T7Fe8dn/b5U1U0VLicL5c1m3Y3X5XXg9BhkdeWySixaAPi/RdlwrBJhFW2WCCMzNcDG83JHtsuKpFb8zRI+w8Pq2VtMyZjZmtcNpGFp+RVgvAdbW/ovNeD+LsdNIxlVT00lmm7RmYT0Pwmy62n4jnqWss3DY3E2cJKsgt9iwXXRRqqSxzKOJszylrdA/ToN1x3FfEGH4VTGeWjdnbf63M0ZT5ly6KojxGoiLIainyPBzPY5wc3+UgL537VMPpqfiOOGt4pjxioBJlw58clRIwb3LWHwAczvbkqVk5FoYK/GXHWEVTJJoOIWSkNBdTyXBvza1w+L8F5lifFeH1kIjNLES0kh+uY+uqir+G8HqaCqrqTiGFslMM0kDKaZ8ZJNgGPte38w06rjpCyNw1c4c7iyQpRWxZyZsYzjNDXtiEeHU1M6NuV5iuO8PUgmwPosCT6M+QARkXNtHWQSuPorVLQQVNM67mun3Az6W6W6rZRwVzkU5YWtikc5zYxlZyyj0VWeJsYHduLg4XPK3kpailfG4Zy7QX1BAHkqbpsuhcCOijhNYSWdRnTSAZcoP5p3VjhFk7vKeT27qu4NkPhLm+6ideI3JJ8iocEzphWlHmblDis8LXNha6VxblAkc8EHqLGy28PxuvlrHfvjDjVPuGvJaGPvbqCOXVcMyR88mVrnF5+EX391q4dg81RUuL4pX5CLjMPx1usKtGOHxHq2V/W4o9Xl/L5M9r4aldiOSKCkbEct+7dKD73XoGE8M4hma7uqZjOZMtyPYBeRcHYfQ0Bkiq43VdPazIpY87rdQGXLfIXXoFDi3D+BU7JXUeN0kbzpnfUNv5C5XhVKceLQ+0nd3EqaWNX7/odu7Dq+AEdxTOYNnd+5hPyGi5XjfiRmGYXJ4qKOdv2TMXtPs5qx8c7Q8HnjeYWY/ldoP725rfkSvJuJMVjqS57YZ3Muf8AxEwefXf9FEaPFLhRFvTdOLrV1jGvP44yVOJOM62tcS2enGbdsQC5Koxaqm0fOT6J6uQl18kbbi4yhUnXOq+gt7eEI4SPielelbivUfpvHZrgZ8z3H4io7k7lOQmyrsWEfOycm9QmzPaLZiR0KReHbj5IbJWTCHHLZiv0SulYpWUlRXThyayVlATYYlts0KRlY5g8Mcd+pF1DlSyqHFM1jVqR1TLD8Sq5AA+Z5aNmg2A9giirJmm7ZS0+qrZUTW2Oyq4RxsaxuKzllyb9p0mHcXV9HGIXtY8XvmdqV6Dwjxpg81SxuJULQLjUTOb/AFXlUNNI+NsoBa0dNVv4JWQ0b2umcXEH7u34Lx721pSi3Fa9x970F0nd8SpV6j4H29njoz6x4cwnDsXpWVNPQNdE/UObUtIK3peEI3x2igdFz8MjTf5rwjgrjYUMgbRuqYc/POQw+xNgvS6HivFXSvfVTzVNK8DI2Cojicw8+WoPqvEi4w9Ga1O3pDo+6jPjpTzHlq/vgqcU8NuoGuJD735kLyjHaqlimdAKSKplFwWsc0H5hen41ifDhe+SpwusfPKMpdVOdIDfocxb+S8k4q4aoauSqnw/DayH6PYSZo3NyE7EBxuQrUIwc9dj0aF1Wp2+Gsvv0925x2J1sOcxzUUsDmuuQ7f0sVky1NO5wyCW3PM5WMTpJKdpj7nEO6ZoXyWsTzOl/wA1lEsHwg+5uvpLeEcaHxHSd5VlN8WF7PwW3SRu+G/ug0UIc9mtt/JLvCd11KJ4FWo28v5Er5Y4263udABqvrPsT4Li4K4QiM8YZieI2qaondgI8EfsD8yV4L2McGN4l4m/eddHnw7Cy2TI4aSy/Yb6D4j6DqvqGkq/Fqbkr5npy61VvB97+iPH6RuJOPVe80cZxqjwDCKvFcQlEVLSROlkd5DkPM7DzK+L+KeKarjHiGtxusP1tVIXBl7iJg0aweQFgvVP2j+PhUSU3BtDLcMLaivLTz3ZGf8A1H2XiOYMFgLDyXZ0PauNLrJbv5GFjQ6uPG938g3kFROdYWTOkUMki95I7kgJX6qs9yN7rlDDH30oby5qSSzRQ5R3hGp2Vu6bQCw2CV1ICukmunugHCrYjP3cPdt+J/4BWcwaCSbAC5Kx5ZTUTOkOx2HQIBo2qWyTBpspI2F7hbe9h6oC7RMETC88vzROdc3Kd1mtDBs38SgJUIhIclCSldMVJI90ya6SAe6YlMmugCumTXSugHuldMSmugHKZNdJAZ4GYgDcq3GwRtDQoadlvGeeynugHSuhukgHvqldCldAFdJDdK6AJODqhuhkflGUfE78AgGe7vH6fC38SnCFtgLDkhkkyM03KAjnkzOy8go0ySkCRNGtymB8k4N1ADL7aJiWncFMUyAIvAblaLA7p2OIGhsha25TubYboQIyO5fmhuTubpXASugC+IfEVINt1DYom3vYmw6oAiQDa5+SQIRnusttz1SaI762+aggG6laCweIgBD3rWE5W6eqAvznYD3UEFgFkhDQST56IXHIbNsPMBRMGt8wFlZEElTdzG3sNSNAPVQ9Cr0IPj+J7j7I2xU5Lc75iPtZWA/LVG1kLA9ryXvI8OQ6A+Z5+ytYfRvfrdtgfK5/NVlLCKykksl7h3DBWzQiD6ZE5jw50jbNAseVtb+ZK9IgwiJj3FlHTveHBzZJZxI/fQuz3B+dtVzWD0JAZ3jSWb+MhxB8g42/BdxSVM2GyQ1dHHVyyhwu2oAe13ycLLwb6o5PRnz9/Vcnodzw3xljQjkigwKd0MXhbJCIo4ibbNuW39tFYxvjfFJbN/s29jQ3431ETnA9AA78brIj4xxKWKV1ZhlZAA6waHskDx1AuHD0K5rHuIprPf3M7GjXM9trf+bVeEqU5Ph4Vjxb+p4XDOT4OFY8fyZHF2N4o+V5ka9rDq1hsQ0+zl5ti1TUz5jIdGEAlxFhfkF1OK4jM9zmyslBcb3LLC3mbrjcYdHNUkteXNGgu4H5WJX0XR9FQSWD6Ho6goYWCmGh+wuqssTsxs1WmeAbIZHlxudB0Xsxzk9uOUyp3RG4skI78iUUhJ56IA4t5rQ2QnMDd7BAQOp+Sls1+gb4vIoDE69rKSwNh5pWbyujbCXb2A6pEtGjQD5lABYFOGE7Ap8xHNLOep+akCZE5x0TuyjRCX25lJpc82DQ4qAK45Eo4wwnVTCnjazPJZnlfdR97G3ZighieSOWnkkZInNDS1wI5hP37T9kFICFxBDSD+Cgo0WqOlhlaHmqMdt80RI/BdTgUlFSyXllq5HNNw6GJxB9L2XKaZbiaIAHmCLLQosQigkEZfmsdHM1b+NiuO4pucTjuKbnE9dwLtDnwwNbBFWSxg2DZGsBaOZ+PX0stPHMbw7iylP02nxKrFODM1s8zYI4yB8QawnX5nVeaUEoqWARSZi7duXKb+d7D8VbfQY1Owd1E8PBs0GVlreeq8CVlTjPiXovxweC7SEZ8S0fiT8RcU1MJjirKV7qc+LKJryZh55jYXPr+S4VzIzDPkMj3uIyd5E12Uc7m9wei38bllglb9IMbKhpJMkb+8LP9ug+a54Sxgh7C9zifFovZtIKMNEexaR4YaIVOBC1rJJxlJ+58PmrBjZNctkDvMg3QSRtnIkItfc2ypmXiBylpHPxaruWp2rUkDKaJpzF+e3xtAOU+h3Uc9RA9lnd7K/77yB+ATPyvb4ntb8yoKiGEZe5mc8ncFtlfBpgUcJqZAyKJ73HZrRcqf8AdsTIwZa6lgdexY91yPZoKsYbh1Q0SPknbSQuYWPlfewB65QSlS4JJUvcYHwVEbXBpcc7W+uwuobIbLmAYNh1XVtFXiEr6W9nGjgc559M4DfxX0F2Z4yzDqZsc1BUTSAiMuM7crQG2GXM7cgC5387WXiVDQ1zHw5anB6aRtx3YjL3MF9Nb6k9BqvRuFMKxGvljDcVnZCdnwU8cZJ8r3K4LuKktWcVzFSWrPS8HoK8ysxTiOnwvGBFUumoGuqrPpy4mzWMEdnHluV2B4kxappLt4crKLcBss8Nx52DlxvCGB4/wo94YKPE6eR5cZ5PBVsB5F2z/wAFu1/Ec8bSJKKqb5hoP5OXlznpwxPNqVP6xKmL8Q1zYz9Jo5WNA1IljIPtmXlPF/EUNTnDo3tcdBdoufxXV8QY9HLGb/SIzro6Ekj5LzLH3xd4HOmee8GYXjINvS6tb26bzIULdSlmRyNafr3OZG7LfQEhVKiAcyLnkFenJJ0aT6qB2c2u3TzXuQie3CJmvg6BRmkzclpmLyCEx+S3RukZZox0Qmj8lqd3bkm7sHkpLmX9FHNqL6ED9laXda6NCWS32UBnCjH3UbaQcwr4F9MpRhn8KElJtI37qkbSfwq62O3JTsA+6oBTipdfgV6Gny2+r/FSNYXbM+ZU8MEuYHMxoHIi6hlkXaEmEA5PkV0OG4s2F7Q+Ilo6lYbHuAAyg26FWIJXZheM233CxlHJdHqvDXF0ULozEJGPGhLHaf8AqXpeF8V1GIBl8Gkr7DZ8kXzGZy8EweshMzC+KWMX+yWkL1HhzGWwFjY+8maRe+UNt5G5WDi08ok7p76jFHPih4Wpo7CzjPWCIj2YCfdZFfhdVw/w8YafC8Fpaht3Go0IzE6OuW3LuWp1VhvFGJyRgtwWa7fhIq4rfPdcxxjiGPYzSSRtpRTvIGQvqWuaD1s3VXc29CEjx/jXDjWNc2aSnbiviFTMIWgS3NwDlAsQOfPovNK/huohF++je618jQb2916xxJHiFRVCpq4mfSC0Nkyu8LiOY5j01XK1VDK5x0blsXbi/lbRaw0JaPP58NfC2MzCZucaFzfD7WUP0SNoDjUMB6ZSutnpq5sjHtZTAxg27xxII56OFlzeJUt2tmYWxh97/WNc0EdCP6LXJTAs1WynEnfd9TAkFp1seh5hZUrXOOuS3S36qalmmpJi9s7C06OaLkOHTZPWOZO4PjysFvhDbEJglFFzABobFAQTu75hWDGbX0ICcljSQyIvuNyPyUNnRCD56DU9IZQ5wma11vCMvxeV+S6Gh4fjMAfmlbUMINxFfNztubHzssalidJK1zhp05/IarqcFeYAx0TDI4CxJAvvt1XHXk0tGfRdGW9OUlxx+Z2XC+NuwuHKKGsz/djjLx+GX8QtGt4pxmch8mG1FIxuxdJHdw9C7RZNHjM2UAUMrHZQzNmYLD3KHEMzi4xVoBts+Mgn3BK8acVxao+6oQXCnl6dy+qMnGJ/pMmZ9O5huSXWYT75SuSxKRoLhNLJl3IDCSfTkFp4jPPGHNtYjTwuDifx0XOVkjsx0dcaWy2XbbUsM8npe+XBw49/lFKqkZI/wmzQLC4sqzm8r3Uj33JTtkaNXDN6r1Y6I+DqNVJttkTYHHkmewN01+SnMpJJY0BR5yTZzgPZWTZlKnBLCICPJNoFYkz5A4AFv3hqoc7uv4KyeTCcFF4EWAMDuRQ2HQoy9zhYuJCYEbFt/dSslJKLegFh5pwEbmNbuHDyunY1jiB4hdMhU9cDAXOykEQLbm1vIo8rIH/E4nyCcSNIsGjVUcuw64UktJbkYjF9NlNHA0kXOidsbsue2iNuliqOR0U6KT1RoU47uItaAG9SVYp5o22zxZupuAqbJSYw3Te6TXG+3yXHKOc5PoqVfg4eE7DDsSMIYIi63Q//AHXZ4Tj1TG0GJ5fr8Ny331C8yoZu7a02L23tY6W+f9V0mHYi0WDc4Py/FeNdUMPKR91YXMa9Pgmz1ikq8Oq4S+vxWZgO0DKXMw+viu78lgcRVdFPPJVUlTPWSQkAkxOb6jmLeSxY5pHscWPkY862zBwKKofBE0mSaaUW2e23yH/C44rU1lZKDby/h9jgOKKp1fVuNMH02vja0aE87WOo9rrmHwnNYPc55OgyHVdZjM0c0xzXLh8IdoQsR921DZHRlzRudLr6O1qOMUsHwPS1lGVRtvOvnTkUY4HstqL/AMyEU76ieOmh8U0rgxjRqSSbAKepmY13he1wOovoV13ZtgomrDjVQ02iuyAON7u5uv5bepW9W46qm6kj5q9jCnFpcj2HgPBoeFMBpsMiIc9ozzSD7ch3P6DyC2uJOKYOFOHqzGagginZ9Ww/5kh0a33P4XWFQ1jGWGfVeV9sXGYx7FI8Epph9Dw8kyW/zJjof9o09br5a2tZXVx6fiz550uslqcJU19RidfU4lXSmaqqpHSyPJvdxNyoXPuhu0aDVCXey+0jFJYR1Mdz7DVQufdKR3JQuKuVHc5W6OPIzMdyqkLO8kAWi3S3RSA0iU10kA4RAobpnPDGl7joAgK+I1GVghadXan0VSNqZzjNIZHblStFggHHQK1SNsDKfRv6lVWtL3hjd3fgFeNmgNA0AsEARKEprproByUrpkroBJJkroBJrpXTEoBXTobpXQBXTXTXTXQD3SukEyAjvYWSuhuldAFdNdNdNdAFdK6G6V0A90k1019UAdw0Fx0AUYJcS87n8Amec7so+EbpwgHvbVV3vL3X5ckcz9Mo5qJAMknSHopAk43SseicCwUAYpXCR1SsgHv0SOqYBFZADZOnASsTsCgGCJrc25sOqWU2OmyYlCBFljuE4sNyUNynsSgC8Nt0TcuxNkBaQNx7JNF+qggk8A6lS9+ySIQkPYL38OoKjbGL9VNGxwNw3Tz0UMqwoaW9iJB7g3WzhsUrIwbtAB2BKzWuexw6fdY3da2HuEhb4C1t75bWt/VYVM4Oeq3g6HC6eoLs8cJLAb2a4An5rqKY4vM6AU1PBGWPDgaiUEO052F1gYZPoAWSNGwXQUOI5n2dHMzkHubZeNcJvkeHcpvXBvyVNVDG41VIQQL3ie17D6XIP4LnsVxEAZvrmgtuGiEC3qS4K5PUE5n/AEuFr/vOcSR8xouWxeF9Q54NZTyWFzmlNiflquKhQTlqcdCgnL0jFx6qo3kvlkqZQRZrXBmh/wBxXL1D4pJS6KLu2cgTcrTxWAxkAyRPsLeF11lFi+ht4KMdD6O3pxjHQBziBYaKvI66mefNV5COZXWkdkUR6I2Rtc0uN9EAcy/2ipnh0jbRtIarmqIzI1ujWAHqdUDpXO3KTmOabHQ+aHL/ABBSBxK4eY6FE1wkNu71/hKCw+8FPFLFG2wvc87IAZI2R/bPooyWcg4+pTubmJOcE+aYRucfCL+iAa4GzQjZO+P4bD2Td07nYeqXd/xBAE6fP8bQT5aKVlIZG59WD+JBCI43Zn3ceSOaUy6CSzellAI8sTTYvcfQJszGm7dQkIXO+EtPoUxhf90oQ0E50Ug1c5p9LhWKQQ58pqbA6XdGbD5Kp3bhuFbw+SFklpGNceTnOsGnzVJ7aGc16Oh1WARRPsX1DoI3D/EdC8tBHmNgt+LGmRU74YZQHZiM5a5pe3qDYED3uuVjz1LSP3rTZWm5i3b7KaU1DPCypiLSN2Ai3rovJqUVOWvn4HkVKKnLXz8CHGZXF2RsT3RnRni5+g/5WREwiUuc10bR4SBrqr80TgCXvc+2l23CqSUwZlLHR36A3IXbSwo4O2klGOCWsFgDfKBsShY+Mts6ZvsCppAZacZsryRa+yy3U8jH6NK2gbx1LcndEG5IHIgb+yKn7inOdlZMXO0LWxgfiVXEc0rTljcR15KOSGdjw0NzOPJhv+S0RojoPov0yzamqc1lgcrpnSE+wFlo4bgVI5x+r71jQMpkJ166clhYPFXxuIfTzPYRo3KdPRdlQx1GQZaacFrNQ1o0+Z3VJaFZHQ4JRMp4g2Gnp4rWuWMA19bL0DhVk1M0CGlbIGm4DJA3fnchef4dNiQexrcLly2+OSVtx7f8rtsHqKlwzVNHPAxpBdkIfc9bA3t5arhrI4a0Wz0L9+1ENP4sNri7y7twA9cyyK7EzVxkgOZcaCTw6/kohxLRSlscEskzraiOFzreumirYlUNqGNc6rfHz0icbdNF5/V66o4erWdjlOIxPGx5knpogR9p1z+AK4DFatlQWNbIJHxNDMwYQHD3XXY9QUcj3yOqS8jW3d5M343XI17omyubGLNGwNh+S9K3gsHfQhgzXsvrooHW2srMuvMKF2Xa4Xakd0UQFt+Sa1uSlNkBVjREZHkhyoyUJJ6KSRkvZPfySv6oSNbyRC/RMPdGDbkSgCbe3JSsB6fJRB3kVI13qgLDDZWGybXCqNdbe6la7pdVwWL8brC9rjyV2nlZcXJHqs2BxHIq2yTP9nX5KrRKZtU0waR3T43XO2oP5LsuHsZjpntErjGfhIyGx+S88pnNMmQtsfnZdfw9iLKUta+HyDmD81lKOSyPUqXGZvo16aimqX8mkiJp93f0KrVGK1jmSvrMLngeRlGRzZQBzsR+oUWHV1HKGxx1Izlubu9SfwUlZUZWEM19rfqs0sFjgMemY577NlOS5cHxOBA6rh8TmZOZGxNma6xeJI3Ea7c9Oi7viWpnyuDqV8rTo7u3fpuvP68n4o6d8OVx+JltT7LaIOXqpMUpDHVOxV1mH4RGHEX5O8uVlRqa2F2SL6PTVTHj6w3yanbL90hXa1gzyude5uXFoHiB6lZRMEQLY4Mw38RvstUVaKlZRQU+V0U9g4EmOXRzfcaEeaqNeNlJVgyPvc3Ooa4fkqRzMNiCFYqty1dp2sjjA2J35dFXYeZN1IHv10Ft7DcrKR6NDtaL9K6NrgTYhu+U/jst+hM74y6IRMbtdxOhXPxUskxbMwxx5d2WIzLdppJGMaBFINbanw39Vx1T6OwzF66I2ad9W1ju9kjYL3Dgy4t5i4I9rqrPMDI4Oq448ovmex2T0Fr/AJKcMNTDaSaOFo1s/Nb5gELIrqOMgmOsw2RxvcCcX065lyJJs+gnUcIb/EqVc1Nch+JNu3drInuLvQkALBq3UxNonSv0uS4BtvzViriEDi5tZRu0uRG83Hle35LLkAJ0la70/wCV30qaWx8lf3cpaNLz4sZ+W/xW9UI15hSNpZXi7Wlw8kf0NzPEfDbqLLo4kuZ5PU1Ja8IAaWC5I9FE8tJ1HyU0jHOtbL81C6I8yB7qUVqprRLQeJ7NQ4uDTy3uhd3WuVh9bpiy32h7FIxu+y5rvQq2EYNyaxgbw9PxTg21DR7pCOQn4HH2U2RwZZ8bh5kqG0TCEnrj4ELnl24b62TNeQbi3yRljPvj3QmMffapyirjPOSQSNd8TLnqCnsyxIcdOSBsbjsLeqNsQbrIbjoFV4N48T3QTZS1paBoeqON6iAbf4rBSNDPvj5KrNqbl2lxpa4Cz7HzCIXjOpB9FXY5oFw8X5KRr3E6AH3WDienCrnHaa1LViSNkTw42OmQa/8AK16R0UTzeVwIPOM6/K65ynkIIs17etlrUmS9nSZemZhA+YuuGvTR9X0Zdt4zv2s6qnrpacNMbXvJ1BczwhR1VRVSx3yEuvcuzXuqUEDm2ImgeANs3/2U8smVmhHnfkvM4UnofW8blHMm17jDr3SZsz4g93IkDRZUweCdAOYAIC1cTqAC27r3H2eX9FkyztJIGffmCvVoJ8Ox8V0nKCqNOXyKsFFPVVEcGVpLjYOsDYcyvScHmjw+CKmjfG2KNtmgLjMJpWxA1LHtD3+Ea2NvRbMD3uDRcAjmFS6/k9Hkj4i8g5PC2Oi4h4rbgODS1Mb2/SH/AFcA/jPP23Xjgc5z3SPcXOcSS46kk81qcSYm/FcQyl47iC7I9dD1PusvbmF22NsqMO9nmqm46hZkxcmJUb3LvKMZzlGSnJTxM7yQDkpILdJHkjzcyp7oRysnuhAV091GCiugDBVOvluRCD5uVh8gjY552CzgS95e7cm6ANjQjJsEINgkxpmlDPs7u9EBZpG5WmQ7u28gpbpr222SugHJSuhuldAFdMSmukSgFdIlMShugHuldNdJAJPdDdK6AJIJrpXQBJkrproCC6V0Ke6AdK6G6V0A90rprpIByUL3WFhudkibIQbnMfZAE0WFki4AEpKKR1zYbBACTc3KSZOpA9uafMh5JAXUAK/qlyS2TAoBJJzomJQC2RC4CEC5Rc/JAFmHM2SDx95ASCmsgJLjrdCdOSYeqK+mqEDX6BPdDolYoAmkAqQPHK6jDSn2QMsMJ5CylLS9mpNwqsbjmBcCR0urETZnuu4eHzKoyjLdNG8yAZxbmLrcga0SsjztAYPFbZY1OxgIB8R/BXqeN50c67TyXPU1OWpqdfSuiyi7/DubFaffDIAzXpY7rAwyBoZ4T/uWn3TreEA+ZdovLqxWTyqsFkOqkkDCBTtab63Jv+a5TFjNNKXENYG/ZbqFv1LJWNuXU7RubuuVgYpVlzXAzx5B9lgtf5bra3jroa28NdDBqGyMeS8AX5Ku86aqw9pmeSB5qrOC3QlenE9WKIJX9FWcSSpHpRk30a2/UrVG8SMRuO4sOpRZu6FmEk9VLM8uAaXNKiJaFYsRkkm5NymUgbnNgLlG5rIm+LV3QckBAnRF4OzQEsxQCZEXnoOqnc8Qts0aqvc9SnD3D7RQDF5JudymuVIwuebZQfZE6ONrrEn0CAhueqVypCI+QcfUpZmjZgQAxte53hv6q4x4jb4pLnoFC2d7BoG2TCNzyXZd1DIYUlQ4/Cwep1UZnlOl7egUrou7aHO0HRSwfRSfrS4eiggLCmPE4kzFoIte41+a6aGGWdr444g5508Nrj2BWCyCkcMwc/5KeGjcbmnOa2+bSy5aseJ5OStHieS/UslpTlIaHN3O+vRUms+szXuT1RPjqmGzg0dbuUkAY43flbl81WKwUisEE7u72P4qWkaxkTpJXRh/2GF2581FVxNqnARauCoTxSREtecp6LdLJ0RWRVtXUSSFsrhYHZvwoaR0hlHd3DvJPBQuqnhrXtLjsCtmHhqsoY+/qZo4IfvbrU1NvC6yWCnzVRzMaLmw1WtScQMDQ8ObD3jbjMb26XtsVzMIp5nsZF39YL+PXKF0dLQ4jLTup6enp6aB+lgLut6lZtFXFHTYJXmLJI+UCN/xPc4C/uTddxhWJ09Q0ujmY5gNrtO/6rz/AAfA30bo3zGR2TbQEe2i7fBMfipbQlma5tfIQVzVaedjnq087Gvh9cJYpWtpnMfnJuWEZhyOu6z8TqX6gsIubWJ1+S1qrEXCPSBx/lcuZxPEarM5kdA8abucFhGnl5OeNLLyczjtQJCQxjmvv4iTyXNzxZHHMVpYridW9zh3QYL2J3WXmGjnEuuOZXdCOEdsIYRVkazMddVEQBorTwOVlA+46LVG6RHcICQnc8BROcTrlCksEShKa55tTggoBaJ9E1wEroB04KHMETSgHzi9rowU1wiaR0CAJrlNG7qLKJqka4c7qAWo5AOasse42s26pxOF9wrUcgChli/Tuy2JgF/vArocLa6Y2hLZv4RJlP4rnqUukIDWknyXQ4ZglRLKyfLkDQdza6o0WR0FLW1mGgMfhVdE3e8L2vb8lcfxM4xEup6i43BYWn11QUdNPTM1dmH84RVlVPFE4kXb1zLPBZGVXYzHVNcWNcCeZadPwXK4rMyVxyU7nuGpe9vhC6GtqZXRl4Y75Lna6tdGHF4eL73arpF0jnsSdAc+YBgds61yuXrYpGy54qcyMtq4O1v1XSV0wkhIjLRcHfmsCmidBHJdpc5zrFoPJWTJlHQy85cwmQnOBzbayzJiWPNhotXFZzBHljy3Jvfp5LJ+md4Q2Zot1armaI2zPBuBqruGvd34IZmJVYR+O8T7tViK4s4NOZvRZzfI77WLTUmzdpW9ySwOzENt/KtOnfJ9E7vvHXvnyv1ufI8li01S2Vl3RvuTqbLQjiaGtOd1vJxu32XDUXafUWk8r0dh6k1Bbdscltz4QbLHrhI65LXXcL3LLArpm01dI0dzVUndbkuqMpA81m1VRFBI5js0ztHF8Ege2/uFSE9dDpuKKcfTbXj9DlX07xd+TS9rlQEW3WtUVVLK9znSThx6tComKmlfYTPHS7V3wk+Z8pcUYJ/xvPuFTgR+NziDyAQTSPmdqSAepUjmmM2uDZRunbfVg9kW+SJNKPA3hAueGaMULi4m5BRlzDzIQnXQELRHHUeeYF7bpiQiMTuhKHu3dCraHO1LsJKd5a8DvCG8xdKdrnPJbctQMicXC7TZTTAsADRZQ99DaKbptS2RWykck+yfMb3uUs7vVWOfQmhlOx280T3E7aoIwSCXtFk3e5fhAVManWptRSkxa9EQB6FMJndApoprnVoUPKJpqMnjIIClj0I1IQyOcTrokxxCo9TojiMjQgmdfQnXRaMM1mjw216bLHhnA0IWjDPH4bOc08wea5KsO4+jsLlL+xtwTAxhty3noVLd2Sxdboqcb4HC4mb7hSgMc3/FGi85x1PrqdZNdvtIqlosbkBZh8UzQ0lovrm2WjNGHXJuRyWdLA258l1UcYPC6TUpbaF+aWEsBAyEaAhZtbiksFM+KOQd48WBOmnVSUzjGTGWlzHDmsmuvMc5BZY5bHUFbUaazhnyd5Sb3RnlrhuE7bgpy3Kdx7Ji5ekjxZRSY7nWCjLknOuUJVjNiJVqnjyNzHcqvEzO8dBuroKFQrpXQ3SQgO6e6C6aSTumF3yQEFXIXvEY2G/qgaLIG3JudypL2QDPOUKzTR91Fc/E7UqvE3vZNfhbqVaLkARKV0N0roB7pXQ3SzIArpXQXSugCuhJSumugHuldDdPdAPdJNdNdAFdPdDdK6AK6V0IKW6AguldCnQD3TXTJIB7p0N0ibC6ATzfT5pJgnugGe6wUaTjmKSkCT2TJBALmnukmUAe6Td7pk+yAK909vIIOaSAImxTG6ZOdUAkyV0ggEj9UISJtsUAYYE4F1HmPVPcoQG5vQpBhtoELdPNO15BUEMnjA2NgrJjEcYOYFU2RumdurMEHeOs91gFVmcizA85g4bdAtKKUuAsx1vRQUzItGtOgWjFMx3guAAuebOebLlHVSxsA7t4BVmSaYsJDpLqrFiEbfBfZWBUNeNOa5pLXODlktdik9szr2edd7hUamPLdz3Zj0steocWt/QBY9XPIXGw9FpA1plCZwB2IVaRubXRTTFw1da6pTOPJdcUdcURSBrTZxuoHOHIaJ3E80BK1RuhXHRLN5BMkpJJGTOZsAmJbIbk2KG1+SJsdzqdEAjC61xqEg0noFK+QRsyt5qvcoA8oG7gnuzqSo0kBZbLG1tmix6oCy+oIKhUkUTnnS4CARaeYTWurT3CJlgL+aqGRxN72QBCN3RWKctiuXuHoq1yeafKgJJjJM6979ELYJOidoI2VmF79gLqCCFueM81bgklfq3MSFYjia9viGqOOLujcC3mqSM5IECYm5YfdTQMu68mjQgke48yqz3OtYlZcJlwk8dWyKozA6A6KpVSOqqh0jrElV5t1DmI5lapGsYmjT52EFgAK6SlnbiWGuoal7g692u81ylAZTUsAu4Ero6isGHubkbmlI0apZYKhZPgs4jkbdpOjguwwzGYTlBeB6rlqLDa7GpRLUP7tvRdjgnC9FCW5sz3Hm4qr7yHg6fDcSpXEB0rCPMrqKI0ZbmhdGT1FliYdhtHC1rO6Y71C24aamjYAyNrfQLJpGckixLO0NIDmk+qxMUnDWG+XXzWs6OIDRjSs+uEYY52QXHkqqKRVROFrXtD3x5CWv3Ntlk1VGxmsZLgtTFcaa6V0fdAEabLCmqHuJyaXW6RukyKQAc1C7Kndn56oCB0Vy4Jt5ISQE5I6IDYoSM54QnXZOWhDohAtkswSNk1ghI9wU9+iGwTghAGHKRrlGCEbUBID0RtcowVK0+SAmY2/JWGZgdAFBFcq9BFfdQSSwVssDm2NvMLpsMrHTWLpM3ldYEUbDpZTsZLG4CLXNoFVrJKO+pJTlHhKOoqA0fDf1WNhGHyxNDp55XEja+gWo+jgePHmP8AqVcF0ZddiTY2m7Bp5rlcZxtjIXlsVzbbddfVUVLY/VNXP11LC0m0bAPRSXRxVRJFLGCH2JFyCNllMf8AR6ktJDmSCxvyXRYqY2X8DQuSxCYBxDSL+Sku9Vgo4pHIHuaW36WWO9jmnVpC6KXDntgZNI5xzcwVRdHHDd7/ABtVjNGfGXNI5LSpnWd1BCoPc17yWaN5KzTA3FisZno20mmkjZpGC1mWPXVWhnaCAD6LIYXB2hIPkrLaiUD/ABCuaUGe3TrpLDWApRK++WJziq0kExBLog08rlTSVUmWweR6KjVyPd4i9x91MUVrSWM6leakle4uIBPkq5ppAdQQtKinETbPBddKrgzfWRPuDyJWym1oedO2jJcZQc0hoBOyidGTqE8jXA63URJWiRxVJLOGhd24pxA7nohDy3YqeKcu0Ks8mMFTk8MaxY3mVG+STYCylknaLiyg7wlQlzLVZJaJg55PvFLvHj7RRZxzCYuHRXOdv/cOyRv2mgqQGF3koCb8krI0WjVa0xktFgLbXv6KPuWX+JNG5zb2TEOJuVRLBtKcZJPAfcj7wThrWnVyGO4OqdzTfyQlYxlIlMrC0Agm3NMMpOhUTWkqVjC0qrSRtGUpbosU8TS7xut0U8LXiUlwBHJVQ03urcLnDS5WMz07bGUsGjBbm1XWAOG4VCF5dorcY0XDNH1FvPK0De0jcXCrTFnMK1lFtyo5GsIIIUQZa4pOS0Mirq+6uxouFQmljc8ZSdRseRWo+IyucAPCPxVGophYuboV3U3E+XvKdXDa287FSRgubanyVdxc297BGJTFIb6hDIO88YXXHQ8Cq1LWO4GtkJSPRPG25udgrnK2TwtDG+ZUgKjBRXQqHdK6EOT3QgK6rVD878o2b+akkkyMJ5nZV2oA26IXHknulEMz8x2CAsRNEbA3nuUd0F0roA7pXQ3TXQBXSuhunugHumumumugCumuldNdAPdK6ZK6Ae6V0ySAe6caIeaSAJK6a6a6AgunuhCdAJK6a6SAe6a9zdMTySQBIXu0sldCdUAySSdSBJJ0yAe6RTJKAOkmS9EAk6ZJAJEENrJ7oB9ErprpkASWiYJ0A+iV01k4sgGvdOAeSRIGykjeOYUEMJmcG6ssjdLzDQoHkkaJ4XuY651VWZs1YYXOysY4q/HC2EWJ1VCmEjwHNNlcEMzyLlc8jnkW42svewV1hAbpYLNbTyN2chqJJ4W3vos3HJi455lupnbGblyzKmrjuTe5UgpnVLc73+yp1dH3V7G60hFbGsIrYqzzZz0CpyPcNOSkkfl0QsaHtJOi6EjpiisX35Ib+SkeACo7gK5oGA221kxIA0CEuzaIibNshINyUhcc0NykpAZdfdD4UyZAGGtJ0TkNabFM3wi6E6lAHnA2CcTubso0rICUzZxZyQia74Soww9FNG3uxcoBxDbdyIMbzcoHPLnXSGu6AuMELdzdSMnY0WBAVIC/NSxxtJ1UAvw1Mbd7lSuqgR4Qq8TM4ADUZjDFVlGC6c3vZCZgfiCCR4GwURdcKMFcEphEps07omYQ94Lr2aEFN/iXJsApqvEnCMxRG19ypRKLeGMhopBLbPZW6hzaqX6RFbMOSxMPldnyvN2nqtSNmR12nRC2DUw/FKmneM4JAXYYXjrJANC0hcrQuaQMzVt0phaAbWVWiGjtqHGTMWtjj910EFUCwZ3AFefU1Y9thG6wPNbdHLYDvJiSVVxK8J081dExty8aLKqcXpnNJMrfS6gdHFI0hziQVkVuDQyOJjcb+qJBIyMdMdROXwtvruFmOIaLFX6kz0T8j25mKnUPjfZw0WiNEVHvHJV3PVh5bysoHEKSSJ0nkgMiNxCjcQhIxeeiWZMSgcboA7pXUevVMSgJsycWUHNECQgJ22UrSAqwcjD7ICy1yMPCrtdfkVMw9QoBYZKB1V6nmvboqEb2jkrUUpvo1CTWge081qU9O+TK4ZWga3K55j3gixsVepPpM8gYXkN8lBJ1cWLthtG8F5A3amlx1jb2jkPshoooqdgFgT1Ktnu3D4W/JQWRi1HEFwfqZPksLEMafI12WMj1XV1DY8p8DfkufxOGJ7TZoCF0cTiD6qpJzOAHksealfGQS29+a3K36uRzNdSqLpCxhLhcJg0bwDDM6SjdDJYW2JWNNC4BzXObZT18xnYRES09AsV5lvle51x5qxmlljhuV1lcphlF+aqMOuqsMcspnfb6PJcYSdSRdTBl9bqrFZzbk2UrHW5rFnp03xEpzbAKGSIlwaTupWuefhTuBHjI1VMs6urXCG+JrIxZt7BZ873NddvyVh1byKhmLJBdp8SvBY3Oa4qKWkSIlso8YsVWfAAbApSuc3RQF5PNbxTPIq1I7NCcyx3RRlrSgOqFaYOXiw8pErwHG90Jb0Ud/NPc9UwQ5p7ofISpO7aBclA2S26kcO8boobZeEYtZW4IazqkcgQ5XA7Iw27dkEdeQwlA5Iw8FR90SjbDl1UPBaHGO67tAFIwZR4iFGS4bBBqd1GMmilwvJYzsadETZG3uVXF0YVXE1jVZbbI1SskynqqLQSdFahaQQSspRR30Ksmy9DJrsr0UjiBoqUD2A6hX2OaRcLjqeB9FaJtesTtBtcoJnAsIuAhc47BV5mSOabErOMcs7atVxjhLIJexkZAcLrKkqLOdmF+ilkaWPs4qvMATddlOKR83e15TWFpgqPDXkkhQC7T5KWV13WAsoXgjmu2J81WeuROB5I2eEWUbLk3KO9lc5m86hgpXQ3SuhUNOChuhkfZvmUAMrs7/IJhomakTohAib6BTMblaAo4hu4+ykugCuldDdNdAHdK6G6V0Ad010N090A90robpXQBXSuhuldAFdNdNdK6AK6V0N0roArpXQ3SugCuldDcpXKAhSTXSugH90uSZI7oBWJ1TpkibIBiUkySkDpJJIBJJJIBJJJIBJBJJAOU10kkAkkkkAkkkkA4SKV03NQBXKK9gmToBXunBTJxqhAbXlSxkE6qIWARtBJVWVZq0srmAWV1lU5ZdMDpqr7GA21WEkjmmkWhWEc0MlV3jCCELY2cyiLIwqYRTQgiqu7JaVVramR1w0aJ6t7WP8O6hEhcLELWMeZrGPMplpJuU5flFiFM/K0aKs91yVqjZakbiCdEDgiKBysaCbYHVJ7r7IUgpArJWTpkArJwEidEyAPMAlmBQJwEAYYDqmzNHJImwQ80AfedAnLyd0CQQBAAogxCCpY2koBMj1VmOHmos2VTMkcVALLMzQLInDNvugYTzRk2UYKNEL42G91VkblOitS6aqs9wcFAIXPOwKZrL6lOUTHa2UkkjDbZalG8m11QijuVcheGEBCUblNIBZakBz21WJSEPI1W5RBjLXN1DDN7DabOBfZazKZlxrssemqcrQAdFejq/NEiEjTvZtrqGWcRtPMqo6tIFyqs9c43shOCriVc19wRcrCc8uJCvVTXF5eVQkeBzQlETwRzUTrp3yg7lROkupAzieqjJPVJzkBchIV7pXQZkxcFICJTXCAuTXUAlBCIOUN04NkBONVI2yha6ykBCAnYVK0XKgYQpmG6AsRgAq3EegVWMNV2AgBQSW6aEyEEhatNE5pBF9FnU0w0WtT1LWt5IC/FM4CxUolJGhUEU0cg5IahoDCWO1VSw9TM7Ibn8VgVlTqQdlJWSTAWzrHq5XkEblTglMpVskb3HqsCtqe7uCVo1Tjc3NiseqZmJJKnBdSKkMhMxcRoVWr4z3mYKeZzWDQKuZCRYoQnqVmk3UjXlC8W1CYElVaOinLBbjcQFOyxVWO43ViM3IFlhI9WhLtL0Lg0aBTEh7bEKGEgNUpkaAuZ7nuQfo6lWopmOFxoQsx+ZjyRdak79NCs6RxLjot6bZ5F7COdNAnszRhxG6qvhHJSuncG5VA55ut0eVUa2YBYQhITlxunDrhaHJhMCycMJTE6pBxCkppzDEXUqRtmc1FmJTbqrWTVTUdkG6XXRMJChypWU4RXjlnJJ3iWc9VGiAUYLKcgszkQd5IdkrqDRPBIDdSNZdRMUrXG6ozoptcyVrQ1TxsLioGb3VqJ11jM9O3SbLVPC02ur7I2jQKhG/KrDagAbrkmmz6G2nTiid8fMFQSucGnVJ1TcbqGWUFtrqIxZpWqww8GfMSXG6rPNlNO6xNiq0huu6CPk7merIZCLqI6o3oV0I8eo8sbQJJiUgrHOx06FOpKhXUTjmddE42FuqEaIQOmtc2SJTsFtUBINBYJJkroB0k10roB+aSa6SAe6V010kAV0roUkAV0yZJAEmumSugCSuhT3QD3STXSQD3TJkroCJJJJSBXTpkkArpFIpkAk6ZOEAkkkkAkkkkAktkkkAkkkkAkkkkAkkkkAkkkkAgkkkgHCSYJ1AEiCEIggDaLqVoUTd1I12qqyjLkBVprzsCqMbrKVshBus2jFo0Gk9U8nwHVVG1HVJ1RcWuqYKYYLWZ367o3sY3SygMuU3CjdM9xV8M0w2RVRyu0KquddTTC5uTdQkLVG0UDdMSnKZSWGSSSCkCSSSQCS2SSsgHCWZMkgH33SsmSAQBWT2TDRONUAbQApWvtoFENETbkqASsFyrMYsFXYbKUOJQFoWsk4aXUIcbJjIbKCBnu0sVX5o3uuokIE4X2RMbbUpgUbWkoSTxElTNGt1DGcospWjzQF6lkII1WvTTk21WHDpzV+mls8ISdJSzmwWgyosLhYNNVWOiuMqidFBBqmUu5qOSUNGqpCd3IqKWRx3KAKomDuazJnAvspp3Ac1SmdrcKSRnGxsgdZRmXVCXkqSQiUBKEuQlyAO6YlBmTZkAZKV0Ga6WZAHmKIFRBycOQE4KJpUGZEHqAW2FTxlUmvuVMx1kBoxHRX4BmA6LKgersM5BshJrRMAsr8QZk3WNHVEbqdtU47XUA0i8s+EqGStkGgKpuqnKs+pcDcoCaoqnkalZNXVObtqpp6kyCwWdO/QgndCSlVyl+t7LPkGYXurM2hPNVnAnVCSq+zhYhQSsAGm6tPaq0u9rqSUyo59zZO3RJ7bFIFVZvTZK16lZIWqtzUrCspI76VR5Lgmcn7xxULXIg8BYtHpRqN7sIhzt1G9gsidPZV3yEm6tFMyq1IJdoz2BQPapHyqMyAraOTzKrgyMhMicgJWhyS0ERdMRZPdJCjwxgiAumT3QlYHy2TJXJSCFtOQ9kgUrpKCRwnQogoLJhNUrBdRBTR6KkjppLUmjCsxuA0sqzDZStf0WMlk9WhJIuNIRaKBr0/elYcLPSjVjjUkcFDLsdU7pTZQPeXK8YsxrVY40K799SoXlSyBQO0XTE8GsyJ26Y7InBAStUcEgUkimVzBjp7pkzihUY6lOmSKkgQFypAgGidAEmuldMoA9090N0roArpEoUroArpXTXSugCumumuldAOnuhukgHuldMkgHSumSugCukhuldAOldNdK6ABJJJSBJ0vVMUAkkySASdJJAJJLRJAJJJJAJJJJAJJJJAJJJJAJJJJAJJJJAJJJJAJOmTqAOEQQhOEBIDojCjCNpUFGSjZSA6KFrlICqFGg0g3qUOZIuQgcuAUT33TkoCQpRZIFxuNVGQicUJKuaIFyBGUJQkZJJP8lIGSSukgEkkkgEkkkgEnTJ0A6cJgjFkA7FI0gclHcImlATMHVSNUQdZSB4soBLmCF5BCAuQF90IGcUBTlyElQAmqRrrKEKVhsEBOHXspRsq7XW1U7HXF0BNG4hXadwuLrPDrK3BpqhJqxSDSytxyc1mscFajeAEBeEtxugklsN1EJLhA4hAM9+bdVpRcaKd5FlXe+ykkru03QFyKR2qiJQDlyHMhJQlyAkzIcyG6V0AV091HdLMgJLpwVGCnDkBICjaVECiDkBO06qZrlVa7VTMdyUAtxSEK3FI7dUYyFajfbZAXYnk7qy2QgaKg2QKUS9EBbMnhJKgdLe4UTpSoXyWF0JHklyXIWfUOL/ABXU75bg7qlK/cXQkhkAtcqCR4LbBPK/TRQOKAhdcEm91VqCSdFYlcdQoJCCOqEohffLqowVI5yjIsoNYhNKlaVAFKxUkjqpSJw9P8SiBRh1lng7Iz7R8iTmAhLOhL7KNSW4kL2WKhcLFWHvuoXarWLOGrFcgLpinIQq5ysSdMkhUdOmToWQtE6ZJCyEkE90lAEAiCFGAoZeITVIw3Ubd1K0gKjOqmTNAKkCrh1kYes2juhNJE4fZPnChEibOq8JsqxM54UL32TFyBxurKJjUqtgucoX6oyo3aLWKPOqyyAShKI6oStEckgSmJTlMrGLEmSSUlBJblJJAPdK6ZJQB7pJkkA6V0ySkBXTJklACuldCkmAFdK6G6V0AV0rpkyYAV0rprpkwArpJkyAJK6a6V0A6SFJMASSSSkCTJ0yASdMnQCSSSQCS9kkkAkkkkAkkkkAkkkkAkkkkAkkkkAkkkkAkkkkAk4TJIB0QQgpwoAQRAoQU6FWiQFGHKEFEHKuCMEl0rlBdOCmCMDlCQnuhJUolAuQlOUKksMmKdMhIydMldSBJJJIBJJJIBJJJIBJwmToB06ZOEA6NqAIggDunBQgp+SgBXTFNdMSgESmCZIFASNRAqIFG1ASNNyp2OBFlWDrbKRrrIC00aq3EbDQqix6tROvzQF2N5VmN1lRY5WWv0QFsP0T59NVWEmiIuuEAUj1WkcUT3nZQPKAFxQEpEoSUAiUJSKYoSOmJTXSJQCvdJCldCAwU90F0roCQFGCogUQKEkzSpWOsq4KNrrIC4x6sMksFQY9TsksgLrXqQSWVMSIzJogLDpVG+XRQGVRPkKAKSU2VOZ90ckirSOugBJ1Ub3A6BJx81C91tUJAlcoC5G919VE4hQSmRuTDVO46IVBrFhBEEAKJVZvFkgNk91GHJ8ypg3Uw7oCU10xKlIrKYigJTkoSVZIxkximTpirGLGSSKZSUHT3TBJQTkJJMldC2R0rpJITkdOChunuoLJhgowVECiBVWjWMiUFECogUQKrg3jMkuldCCnuowaqQiUxKYlCSpSKSkM4oHJyhOiujlmwSExTkoSVZGEhimTlMrGTGSSSUlBJJJIBJJJIBJJJIBJJJIBJJJIBJJJIBJJJIBJJJIBJJJIBJJJIBJJJIBJBJIIBJJJIBJkkkAk6SSASSSSASSSSASSSSASSSSASSSSASSSSgCSSSUgSSSSASSSSASSSSASdJJAOEV+SSSggcFOkkoIFdPmskkoIHJQkpJKSUCU10klJYEpkklIEkkkgEkkkoAkkkkAkkklIEkkkgCCdJJAIFECkkgHBRJJIBrpJJIBrpkklAFdPmSSQBscpQUkkBKx3JTxvISSQFuOS4U4eCEkkAbXIy66SSkET3KJx0SSQETjZDdJJQBXTFJJACSkCkkgGuldJJAK6SSSAcFEHJJISG0owUkkATX2UzX6JJICRsiMPukkgE7a6hc42SSQggkdoqxddJJCSF71CXXCSSAhc5RkpJISgSUySSguhAogUklVm0WPe6V0klBpkSYpJIirYKYpJKSjGKZJJSZ5EmSSUkDhJJJAh0kklBYSSSSAcJJJKCw4RBJJCyY90QKSSqbRYSSSSg0yNdMSkkhVsBztUJKSSujnk2CShJSSVjFsZMkkpM2JJJJSQJJJJAKyWySSASSSSASSSSASSSSASXmkkgEkkkgEUkkkAkkkkAkkkkAkkkkArJJJID//2Q=='
_CAPA_CONTROLE_FIXA_B64 = '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'

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
    """Aviso curto: somente caminho chegando + Gale atual."""
    global alertas_gatilho_chegando_message_id
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
    """Cancela apenas o caminho candidato. A mensagem AGUARDANDO continua."""
    global alertas_gatilho_chegando_message_id
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
    if op_atual.get("modo") == "entrada_gatilho":
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
    if op_atual.get("modo") == "entrada_gatilho":
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
        if operacao.get("modo") == "entrada_gatilho":
            alertas_gatilho_nivel_aposta = 0
        return

    if operacao.get("modo") == "entrada_gatilho":
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
        operacao = {
            "modo": "entrada_gatilho",
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

    if ALERTAS_MODO_ESTRATEGIA == "entrada_gatilho":
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
        bot.edit_message_text(
            _texto_seletor_estrategia_bot(),
            call.message.chat.id,
            call.message.message_id,
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
        _editar_balao_com_capa(
            call.message,
            _CAPA_BOT_FIXA_B64,
            "capa_bot.jpg",
            _texto_controle_bot(),
            bot_controle_markup(),
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
