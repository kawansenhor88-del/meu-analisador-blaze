import telebot
import requests
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from datetime import datetime
import google.generativeai as genai

# Carrega as chaves secretas do servidor
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_KEY)

def puxar_dados_blaze():
    url = "https://blaze1.space"
    try:
        resposta = requests.get(url)
        dados = resposta.json()
        historico = []
        for rodada in dados:
            data_bruta = rodada['created_at'].split(".")
            dt = datetime.strptime(data_bruta[0], "%Y-%m-%dT%H:%M:%S")
            horario_formatado = dt.strftime("%H:%M:%S")
            cor = "Branco" if rodada['color'] == 0 else ("Vermelho" if rodada['color'] == 1 else "Preto")
            historico.append({"tempo": horario_formatado, "resultado": cor, "numero": rodada['roll']})
        return json.dumps(historico)
    except:
        return "Erro ao conectar com os dados da Blaze."

@bot.message_handler(func=lambda message: True)
def responder_usuario(message):
    pergunta_usuario = message.text
    dados_blaze = puxar_dados_blaze()
    instrucao_ia = (
        "Você é um interpretador estatístico estrito. Analise o histórico JSON fornecido da Blaze. "
        "Cada rodada possui o 'tempo' (Hora:Minuto:Segundo), o 'resultado' (Cor) e o 'numero'. "
        "Responda a pergunta do usuário APENAS com contagens matemáticas exatas, horários dos registros e sequências máximas. "
        "É EXPRESSAMENTE PROIBIDO dar palpites de apostas, dicas de gerenciamento ou conselhos. Seja frio, direto e matemático."
    )
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=instrucao_ia
    )
    conteudo_envio = f"Histórico Recente da Blaze: {dados_blaze}\n\nPergunta do usuário: {pergunta_usuario}"
    resposta_gemini = model.generate_content(conteudo_envio)
    bot.reply_to(message, resposta_gemini.text)

def rodar_servidor_falso():
    porta = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(('0.0.0.0', porta), SimpleHTTPRequestHandler)
    servidor.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=rodar_servidor_falso, daemon=True).start()
    bot.polling()
