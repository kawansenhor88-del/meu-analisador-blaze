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
# BUSCAR HISTÓRICO REAL DA DOUBLE (TIPMINER)
# ==============================================================================
def puxar_dados_blaze():
    urls = [
        "https://tipminer.com"
    ]
    
    ultimo_erro = None
    
    for url in urls:
        try:
            print("=========================================")
            print("BUSCANDO HISTÓRICO REAL DA DOUBLE (TIPMINER)")
            print("URL:", url)
            print("=========================================")
            
            resposta = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Origin": "https://tipminer.com",
                    "Referer": "https://tipminer.com/"
                }
            )
            
            print("STATUS TIPMINER:", resposta.status_code)
            print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))
            print("TAMANHO DA RESPOSTA:", len(resposta.text))
            
            resposta.raise_for_status()
            
            # ------------------------------------------------------------------
            # CONVERTER RESPOSTA PARA JSON
            # ------------------------------------------------------------------
            try:
                dados_brutos = resposta.json()
                
                # Trata possíveis variações de encapsulamento da API do TipMiner
                if isinstance(dados_brutos, dict) and "rounds" in dados_brutos:
                    dados = dados_brutos["rounds"]
                elif isinstance(dados_brutos, dict) and "data" in dados_brutos:
                    dados = dados_brutos["data"]
                else:
                    dados = dados_brutos
            except Exception as erro_json:
                print("=========================================")
                print("A RESPOSTA NÃO É JSON")
                print("=========================================")
                raise
            
            # VERIFICAR FORMATO
            if not isinstance(dados, list):
                raise ValueError(f"A API retornou um formato inesperado: {type(dados).__name__}")
                
            if len(dados) == 0:
                raise ValueError("A API respondeu, mas não retornou nenhuma rodada.")
                
            historico = []
            
            # ------------------------------------------------------------------
            # PROCESSAR RODADAS
            # ------------------------------------------------------------------
            for rodada in dados:
                try:
                    created_at = rodada.get("created_at") or rodada.get("createdAt")
                    color = rodada.get("color")
                    roll = rodada.get("roll") or rodada.get("result")
                    
                    if not created_at or color is None or roll is None:
                        continue
                        
                    # CONVERTER DATA
                    data_texto = created_at.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(data_texto)
                    
                    # CONVERTER UTC PARA HORÁRIO DE BRASÍLIA
                    if dt.tzinfo is not None:
                        dt_brasilia = dt.astimezone(timezone(timedelta(hours=-3)))
                    else:
                        dt_brasilia = dt
                        
                    horario = dt_brasilia.strftime("%H:%M:%S")
                    
                    # CONVERTER COR
                    cor_str = str(color).lower()
                    if cor_str in ["0", "white", "branco"]:
                        cor = "Branco"
                    elif cor_str in ["1", "red", "vermelho"]:
                        cor = "Vermelho"
                    elif cor_str in ["2", "black", "preto"]:
                        cor = "Preto"
                    else:
                        cor = f"Desconhecido ({color})"
                        
                    historico.append({
                        "tempo": horario,
                        "resultado": cor,
                        "numero": roll
                    })
                except Exception as erro_rodada:
                    print("ERRO AO PROCESSAR RODADA:", str(erro_rodada))
                    continue
                    
            # VERIFICAR RESULTADO FINAL
            if not historico:
                raise ValueError("A API respondeu, mas nenhuma rodada pôde ser processada.")
                
            print("=========================================")
            print("RODADAS RECEBIDAS:", len(historico))
            print("RODADA MAIS RECENTE:", historico[0] if historico else 'Nenhuma')
            print("RODADA MAIS ANTIGA:", historico[-1] if historico else 'Nenhuma')
            print("=========================================")
            
            return json.dumps(historico, ensure_ascii=False)
            
        except Exception as erro:
            ultimo_erro = erro
            print("=========================================")
            print("FALHA AO BUSCAR NESTA URL")
            print("TIPO:", type(erro).__name__)
            print("ERRO:", str(erro))
            print("=========================================")
            continue
            
    # TODAS AS FONTES FALHARAM
    raise RuntimeError(f"Não foi possível obter o histórico real da Double. Último erro: {ultimo_erro}")

# ==============================================================================
# COMANDO /START
# ==============================================================================
@bot.message_handler(commands=["start"])
def iniciar(message):
    print("COMANDO /START RECEBIDO")
    bot.reply_to(
        message,
        "🤖 Bot online!\n\nEnvie uma pergunta sobre o histórico da Double."
    )

# ==============================================================================
# RECEBER MENSAGENS
# ==============================================================================
@bot.message_handler(func=lambda message: True)
def responder_usuario(message):
    print("=========================================")
    print("NOVA MENSAGEM RECEBIDA")
    print("USUÁRIO:", message.from_user.id)
    print("MENSAGEM:", message.text)
    print("=========================================")
    
    try:
        pergunta_usuario = message.text or ""
        
        # TESTE DO TELEGRAM
        if pergunta_usuario.strip().upper() == "TESTE 123":
            bot.reply_to(
                message,
                "✅ Telegram - Render - Bot está funcionando."
            )
            print("TESTE 123 RESPONDIDO COM SUCESSO")
            return
            
        # BUSCAR DADOS REAIS
        print("BUSCANDO HISTÓRICO REAL...")
        dados_blaze = puxar_dados_blaze()
        print("DADOS RECEBIDOS COM SUCESSO.")
        print(dados_blaze[:2000])
        
        # INSTRUÇÃO PARA GEMINI
        instrucao_ia = """
Você é um interpretador estatístico estrito.
Analise SOMENTE o histórico JSON fornecido.

Cada rodada possui:
- tempo
- resultado
- numero

O histórico está ordenado da rodada mais recente para a mais antiga.

Você pode responder perguntas sobre:
- Último resultado;
- Último branco;
- Último vermelho;
- Último preto;
- horário de determinada rodada;
- número de determinada rodada;
- quantidade total de rodadas;
- quantidade de brancos;
- quantidade de vermelhos;
- quantidade de pretos;
- percentuais;
- sequências;
- maior sequência;
- menor sequência;
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
13. Quando perguntarem pelo último resultado de uma cor, procure a ocorrência mais recente no histórico.
"""
        
        # ENVIAR PARA GEMINI
        conteudo_envio = (
            f"HISTÓRICO REAL DA DOUBLE:\n{dados_blaze}\n\n"
                    
