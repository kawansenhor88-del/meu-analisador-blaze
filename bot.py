import requests
import json
import logging

# Garante que os logs apareçam no painel do Render se já não estiverem configurados
logger = logging.getLogger(__name__)

def testar_historico_tipminer(limit_solicitado):
    """
    Função auxiliar isolada para testar o comportamento do endpoint /history.
    """
    url = "https://tipminer.com"
    
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
            
            # Garante a captura da lista independente se ela vier envelopada ou direta
            if isinstance(dados, dict) and "data" in dados:
                lista_rodadas = dados["data"]
            elif isinstance(dados, list):
                lista_rodadas = dados
            else:
                lista_rodadas = []
                
            qtd_real = len(lista_rodadas)
            primeiro = lista_rodadas[0] if qtd_real > 0 else None
            ultimo = lista_rodadas[-1] if qtd_real > 0 else None
            
            # Conversão de cores solicitada (0=Branco, 1–7=Vermelho, 8–14=Preto)
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
        logger.error(f"Erro no teste da API TipMiner: {str(e)}")
        return {"sucesso": False, "status": "Erro", "erro": str(e)}

# --- HANDLER TEMPORÁRIO PARA O COMANDO TELEGRAM ---
@bot.message_handler(commands=['testeapi'])
def comando_teste_api(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏳ Iniciando testes de limites no endpoint /history diretamente pelo Render...")
    
    limites_para_testar = [200, 400, 1000, 2000]
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
                # Exibe uma parte do UUID e o timestamp para analisarmos a ordem cronológica
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
            
