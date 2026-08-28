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
    "https://api.core.public.tipminer.com/"
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
    if color is None:
        color = payload.get("colour")
    if roll is None:
        roll = payload.get("number")

    if resultado is None and color is None and roll is None:
        return False

    rodada_id = payload.get("id") or payload.get("uuid") or instant
    if rodada_id is not None:
        rodada_id = str(rodada_id)
        if rodada_id == ultima_rodada_id:
            return False

    cor = cor_por_tipo(tipo, resultado=resultado, color=color)
    numero = roll if roll is not None else resultado
    horario = converter_horario(instant)

    if horario is None:
        horario = datetime.now(
            timezone(timedelta(hours=-3))
        ).strftime("%H:%M:%S")

    if rodada_id is None:
        rodada_id = f"{horario}|{cor}|{numero}"

    rodada_id = str(rodada_id)
    rodada = {
        "rodada_id": rodada_id,
        "tempo": horario,
        "resultado": cor,
        "numero": numero,
        "instant": instant,
        "tipo": str(tipo).upper() if tipo else "DOUBLE",
    }

    foi_salva = salvar_rodada_banco(rodada, rodada_id)
    if not foi_salva:
        ultima_rodada_id = rodada_id
        print("RODADA JÁ EXISTE NO BANCO.")
        return False

    with historico_lock:
        if historico_double:
            ultima = historico_double[0]
            if (
                ultima.get("instant") == rodada.get("instant")
                and ultima.get("numero") == rodada.get("numero")
            ):
                ultima_rodada_id = rodada_id
                return False
        historico_double.appendleft(rodada)

    ultima_rodada_id = rodada_id

    print("========================================")
    print("NOVA RODADA DOUBLE RECEBIDA")
    print(rodada)
    print("ID:", rodada_id)
    print("HISTÓRICO EM MEMÓRIA:", len(historico_double))
    try:
        print("TOTAL NO POSTGRESQL:", contar_rodadas_banco())
    except Exception:
        print("NÃO FOI POSSÍVEL CONTAR O BANCO.")
    print("========================================")
    return True


# ==============================================================================
# PROCESSAR SSE
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

        try:
        payload = json.loads("\n".join(dados_json))
    except Exception as erro:
        print("ERRO AO CONVERTER EVENTO SSE:")
        print(erro)
        print("\n".join(dados_json)[:1000])
        return


    print("JSON SSE:")
    print(json.dumps(payload, ensure_ascii=False)[:3000])

    if not isinstance(payload, dict):
        return

    if payload.get("type") == "heartbeat":
        print("HEARTBEAT RECEBIDO")
        return

    if str(payload.get("type", "")).upper() in ("DOUBLE", "DEFAULT", "LUCKY"):
        adicionar_rodada(payload)
        return

    dados = payload.get("data")
    if isinstance(dados, dict):
        if dados.get("type") == "heartbeat":
            print("HEARTBEAT RECEBIDO")
            return
        if str(dados.get("type", "")).upper() in ("DOUBLE", "DEFAULT", "LUCKY"):
            adicionar_rodada(dados)
            return
        if any(chave in dados for chave in ("result", "color", "roll")):
            if not dados.get("type"): dados["type"] = "DOUBLE"
            adicionar_rodada(dados)
            return

    if any(chave in payload for chave in ("result", "color", "roll")):
        if not payload.get("type"): payload["type"] = "DOUBLE"
        adicionar_rodada(payload)


# ==============================================================================
# CAPTURAR TIPMINER
# ============================================================================== 

def capturar_tipminer():
    print("========================================")
    print("CAPTURADOR TIPMINER INICIANDO")
    print("========================================")

    while True:
        resposta = None
        try:
            print("CONECTANDO AO SSE DO TIPMINER...")
            print(TIPMINER_SSE_URL)

            resposta = requests.get(
                TIPMINER_SSE_URL,
                stream=True,
                timeout=60,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache",
                },
            )

            print("STATUS TIPMINER:", resposta.status_code)
            print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))
            resposta.raise_for_status()

            print("========================================")
            print("SSE TIPMINER CONECTADO")
            print("AGUARDANDO EVENTOS DOUBLE/DEFAULT/LUCKY...")
            print("========================================")

            evento_atual = []

            for linha in resposta.iter_lines(decode_unicode=True):
                if linha is None:
                    continue

                if linha == "":
                    if evento_atual:
                        processar_evento_sse("
".join(evento_atual))
                        evento_atual = []
                    continue

                evento_atual.append(linha)

            if evento_atual:
                processar_evento_sse("
".join(evento_atual))

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

        print("TENTANDO RECONECTAR AO TIPMINER EM 5 SEGUNDOS...")
        time.sleep(5)


def iniciar_capturador():
    thread = threading.Thread(target=capturar_tipminer, daemon=True)
    thread.start()
    print("THREAD DO TIPMINER INICIADA.")


# ==============================================================================
# HISTÓRICO PARA A IA
# ==============================================================================

def obter_historico(limite=None):
    dados=obter_historico_banco(limite=limite)
    if not dados: raise RuntimeError("Ainda não recebi nenhuma rodada do TipMiner.")
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
    return "
".join(partes)


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


def _encontrar_sequencias_de_10(dados, limite=50):
    """
    Encontra sequências de pelo menos 10 vermelhos/pretos.
    As primeiras 10 rodadas formam o gatilho; as cinco seguintes são as posições 11ª a 15ª.
    """
    cores = []
    for d in dados:
        cor = d.get("resultado")
        if cor not in ("Vermelho", "Preto", "Branco"):
            cor = cor_por_tipo(d.get("tipo"), d.get("numero"), d.get("resultado"))
        cores.append(cor)

    ocorrencias = []
    i = 0
    # Precisamos de pelo menos 10 do gatilho + 5 seguintes (total 15 rodadas)
    while i < len(dados) - 14 and len(ocorrencias) < limite:
        cor = cores[i]
        if cor not in ("Vermelho", "Preto"):
            i += 1
            continue

        # Verifica se as próximas 9 rodadas também são da mesma cor (completando 10)
        gatilho_valido = True
        for k in range(1, 10):
            if cores[i + k] != cor:
                gatilho_valido = False
                break

        if gatilho_valido:
            # Pegamos exatamente as 10 do gatilho e as 5 imediatamente seguintes (11ª à 15ª)
            seq_10 = dados[i : i + 10]
            seguintes_5 = dados[i + 10 : i + 15]
            ocorrencias.append((i, cor, seq_10, seguintes_5))
            
            # Avança o índice para depois dessas 10 para não duplicar o mesmo gatilho
            i += 10
        else:
            i += 1

    return ocorrencias


def analisar_50_sequencias_de_10():
    """Analisa até 50 sequências mais recentes de 10 vermelhos ou 10 pretos."""
    dados_desc = []
    offset = 0
    TAMANHO_BLOCO = 5000

    while len(dados_desc) < MAX_HISTORY:
        conn = conectar_banco()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT id, rodada_id, tempo, resultado, numero, instant, tipo, criado_em
                FROM double_rounds
                ORDER BY id DESC
                LIMIT %s OFFSET %s
                """,
                (TAMANHO_BLOCO, offset),
            )
            bloco = cursor.fetchall()
        finally:
            conn.close()
        if not bloco:
            break
        dados_desc.extend(bloco)
        
        # Cronologia correta: do mais antigo para o mais recente para achar as 5 seguintes
        dados = list(reversed(dados_desc))
        teste = _encontrar_sequencias_de_10(dados, limite=100)
        if len(teste) >= 60: # Margem de segurança
            break
        offset += TAMANHO_BLOCO

    dados = list(reversed(dados_desc))
    ocorrencias = _encontrar_sequencias_de_10(dados, limite=100)
    
    # Pega as 50 ocorrências mais recentes do histórico
    ocorrencias = ocorrencias[-50:]
    # Inverte para mostrar a mais recente primeiro no Telegram
    ocorrencias = list(reversed(ocorrencias))

    if not ocorrencias:
        return "❌ Ainda não encontrei uma sequência completa de 10 vermelhos ou 10 pretos com as 5 rodadas seguintes disponíveis."

    stats = {p: {"hits": 0, "total": 0} for p in range(11, 16)}
    blocos = []

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

        for offset_pos, rodada in enumerate(seguintes, start=11):
            c = rodada.get("resultado") or cor_por_tipo(rodada.get("tipo"), rodada.get("numero"))
            _, hora = formatar_data_hora(rodada.get("instant"), rodada.get("tempo"))
            
            # Se for BRANCO na análise pós-sequência
            if c == "Branco":
                marca = f"{emoji_cor(c)} BRANCO ❌"
                stats[offset_pos]["total"] += 1
            # Se bateu a cor OPOSTA (Alvo da sua estratégia)
            elif c == oposta:
                stats[offset_pos]["hits"] += 1
                stats[offset_pos]["total"] += 1
                marca = f"{emoji_cor(c)} {c.upper()} ✅"
            # Se repetiu a cor da sequência (Erro)
            else:
                stats[offset_pos]["total"] += 1
                marca = f"{emoji_cor(c)} {c.upper()} ❌"
                
            linhas.append(f"{offset_pos}ª → {marca} — {hora}")
        blocos.append("
".join(linhas))

    resumo = [f"📊 {len(ocorrencias)} SEQUÊNCIAS MAIS RECENTES", ""]
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

    resumo += ["", f"📈 AMOSTRA: {len(ocorrencias)} sequências"]
    return ["
".join(resumo), "

".join(blocos)]


def painel_markup():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🔥 SEQUÊNCIA CORES IGUAIS 10X", callback_data="seq10"),
        telebot.types.InlineKeyboardButton("📊 Últimas 50", callback_data="ult50"),
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📚 Total", callback_data="total"),
        telebot.types.InlineKeyboardButton("🕐 Última rodada", callback_data="ultima"),
    )
    return markup

# ==============================================================================
# TELEGRAM
# ==============================================================================

@bot.message_handler(commands=["start"])
def iniciar(message):
    print("COMANDO /START RECEBIDO")
    try:
        total = contar_rodadas_banco()
    except Exception:
        total = "indisponível"

    bot.reply_to(
        message,
        "🤖 Bot online!

"
        "Captura TipMiner ativa.
"
        f"📚 Rodadas salvas no banco: {total}

"
        "Escolha uma análise no painel ou envie uma pergunta."
,
        reply_markup=painel_markup()
    )


@bot.message_handler(commands=["painel"])
def abrir_painel(message):
    try:
        total = contar_rodadas_banco()
        bot.reply_to(message, f"🎯 PAINEL DE ESTRATÉGIAS

🔥 SEQUÊNCIA CORES IGUAIS 10X
📚 Rodadas armazenadas: {total}
💾 Limite: {MAX_HISTORY:,}

Clique na estratégia para gerar o resultado:", reply_markup=painel_markup())
    except Exception as erro:
        bot.reply_to(message, f"❌ Não consegui abrir o painel: {type(erro).__name__}")


@bot.callback_query_handler(func=lambda call: call.data in ("seq10", "ult50", "total", "ultima"))
def painel_callback(call):
    try:
        bot.answer_callback_query(call.id)
        if call.data == "total":
            total = contar_rodadas_banco()
            bot.send_message(call.message.chat.id, f"📚 TOTAL NO HISTÓRICO

🔢 {total:,} rodadas
💾 Limite: {MAX_HISTORY:,}")
            return
        if call.data == "ultima":
            dados = obter_historico_banco(limite=1)
            if not dados:
                bot.send_message(call.message.chat.id, "❌ Nenhuma rodada registrada ainda.")
                return
            r = dados[0]
            data, hora = formatar_data_hora(r.get("instant"), r.get("tempo"))
            cor = r.get("resultado")
            bot.send_message(call.message.chat.id, f"🕐 ÚLTIMA RODADA

📅 {data}
⏰ {hora}
🎰 {r.get('numero')}
{emoji_cor(cor)} {str(cor).upper()}")
            return
        if call.data == "ult50":
            dados = obter_historico_banco(limite=50)
            linhas = ["📊 ÚLTIMAS 50 RODADAS", ""]
            for n, r in enumerate(dados, 1):
                _, hora = formatar_data_hora(r.get("instant"), r.get("tempo"))
                cor = r.get("resultado")
                linhas.append(f"{n:02d}. {emoji_cor(cor)} {r.get('numero')} — {hora}")
            bot.send_message(call.message.chat.id, "
".join(linhas))
            return
        resultado = analisar_50_sequencias_de_10()
        if isinstance(resultado, list):
            bot.send_message(call.message.chat.id, resultado[0])
            detalhes = resultado[1]
            for pos in range(0, len(detalhes), 3900):
                bot.send_message(call.message.chat.id, detalhes[pos:pos+3900])
        else:
            bot.send_message(call.message.chat.id, resultado)
    except Exception as erro:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, f"❌ Erro na análise: {type(erro).__name__}: {str(erro)[:250]}")


@bot.message_handler(func=lambda message: True)
def responder_usuario(message):
    try:
        pergunta_usuario=message.text or ""
        if pergunta_usuario.strip().upper()=="TESTE 123":
            bot.reply_to(message,"✅ Telegram - Render - Bot está funcionando."); return

        cor=identificar_cor_perguntada(pergunta_usuario)
        texto=pergunta_usuario.lower()
        ultima=any(x in texto for x in ("último","última","ultimo","ultima"))

        # Último branco/vermelho/preto: consulta direta e atualizada no PostgreSQL.
        if cor and ultima:
            rodada=obter_ultimo_por_cor(cor)
            if not rodada:
                bot.reply_to(message,f"❌ Não encontrei nenhum {cor.lower()} salvo no histórico.")
            else:
                bot.reply_to(message,montar_resposta_ultima_cor(rodada))
            return

        # Para perguntas gerais, enviamos no máximo as 1.000 mais recentes ao Gemini.
        # Consultas de total/última rodada são feitas diretamente no PostgreSQL.
        dados=obter_historico(limite=min(1000, MAX_HISTORY))
        instrucao_ia=""""
Você é um interpretador estatístico estrito da Double.
Analise SOMENTE o histórico JSON fornecido.
Cada registro é uma rodada/evento: DOUBLE=Vermelho, DEFAULT=Preto, LUCKY=Branco (0).
O histórico está ordenado da rodada mais recente para a mais antiga.
Quando o usuário pedir as 50 ocorrências mais novas, use somente as 50 primeiras.
Nunca invente dados, horários ou resultados. Não faça previsão, palpite, estratégia ou gerenciamento de aposta.
Responda em português e seja direto.
""""
        conteudo=("HISTÓRICO DA DOUBLE SALVO NO BANCO POSTGRESQL:
"+
                  json.dumps(dados,ensure_ascii=False)+
                  "

PERGUNTA DO USUÁRIO:
"+pergunta_usuario)
        resposta=client.models.generate_content(
            model=GEMINI_MODEL,contents=conteudo,
            config=types.GenerateContentConfig(system_instruction=instrucao_ia,temperature=0.1))
        if not resposta.text: raise RuntimeError("Gemini retornou uma resposta vazia.")
        bot.reply_to(message,resposta.text)
    except Exception as erro:
        traceback.print_exc()
        try: bot.reply_to(message,"❌ Ainda não consegui obter os dados da Double.

"+f"Erro: {type(erro).__name__}: {str(erro)[:300]}")
        except Exception: pass


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
        sucesso = bot.set_webhook(url=webhook_url)

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
    carregar_historico_banco()
    iniciar_capturador()
    configurar_webhook()

    print("====================")
    print("FLASK STARTING")
    print("PORT:", PORT)

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )
