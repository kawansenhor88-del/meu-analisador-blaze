import os
import json
import time
import traceback
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import psycopg2


# ============================================================
# CAPTURADOR TIPMINER 24H - SERVIÇO WEB GRATUITO BELMO
# ============================================================

TIPMINER_SSE_URL = os.getenv(
    "TIPMINER_SSE_URL",
    "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/live",
)

DATABASE_URL = os.getenv("DATABASE_URL")
MAX_HISTORY = 100000


# ============================================================
# BANCO
# ============================================================

def conectar_banco():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não configurada.")

    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=30,
    )


def inicializar_banco():
    conn = conectar_banco()

    try:
        cur = conn.cursor()

        cur.execute("""
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
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_double_rounds_instant
            ON double_rounds(instant)
        """)

        conn.commit()

        print("========================================")
        print("BANCO POSTGRESQL/SUPABASE OK")
        print("LIMITE:", MAX_HISTORY)
        print("========================================")

    finally:
        conn.close()


def salvar_rodada(rodada):
    conn = conectar_banco()

    try:
        cur = conn.cursor()
        agora = datetime.now(timezone.utc)

        cur.execute(
            """
            INSERT INTO double_rounds
                (rodada_id, tempo, resultado, numero, instant, tipo, criado_em)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (rodada_id) DO NOTHING
            """,
            (
                rodada["rodada_id"],
                rodada.get("tempo"),
                rodada.get("resultado"),
                str(rodada["numero"]) if rodada.get("numero") is not None else None,
                str(rodada["instant"]) if rodada.get("instant") is not None else None,
                rodada.get("tipo", "DOUBLE"),
                agora,
            ),
        )

        inseriu = cur.rowcount > 0
        conn.commit()

        cur.execute(
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
        print("ERRO AO SALVAR RODADA:")
        traceback.print_exc()
        return False

    finally:
        conn.close()


def contar_rodadas():
    conn = conectar_banco()

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM double_rounds")
        return cur.fetchone()[0]

    finally:
        conn.close()


# ============================================================
# CONVERSÃO
# ============================================================

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

    except (ValueError, TypeError):
        pass

    texto = str(valor).strip().lower()

    if texto in ("white", "branco"):
        return "Branco"

    if texto in ("red", "vermelho"):
        return "Vermelho"

    if texto in ("black", "preto"):
        return "Preto"

    return None


def horario_brasilia(valor):
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


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def normalizar_rodada(payload):
    if not isinstance(payload, dict):
        return None

    tipo = str(payload.get("type") or "").upper()

    if tipo == "HEARTBEAT":
        return None

    dados = payload.get("data")

    if isinstance(dados, dict):
        candidato = dados
    else:
        candidato = payload

    tipo = str(candidato.get("type") or tipo or "DOUBLE").upper()

    if tipo == "HEARTBEAT":
        return None

    resultado = candidato.get("result")
    if resultado is None:
        resultado = candidato.get("value")

    instant = candidato.get("instant")
    if instant is None:
        instant = candidato.get("created_at")

    color = candidato.get("color")
    if color is None:
        color = candidato.get("colour")

    numero = candidato.get("roll")
    if numero is None:
        numero = candidato.get("number")

    if numero is None and resultado is not None:
        try:
            int(resultado)
            numero = resultado
        except (ValueError, TypeError):
            pass

    # Não inventa cor com base somente no tipo do evento.
    cor = None

    if color is not None:
        cor = converter_cor(color)

    if cor is None and numero is not None:
        cor = converter_cor(numero)

    if cor not in ("Vermelho", "Preto", "Branco"):
        return None

    rodada_id = (
        candidato.get("id")
        or candidato.get("uuid")
        or candidato.get("round_id")
        or candidato.get("roundId")
    )

    if rodada_id is None:
        if instant is None and numero is None:
            return None

        rodada_id = f"{instant}|{numero}|{cor}"

    return {
        "rodada_id": str(rodada_id),
        "tempo": horario_brasilia(instant),
        "resultado": cor,
        "numero": numero,
        "instant": instant,
        "tipo": tipo or "DOUBLE",
    }


# ============================================================
# SSE
# ============================================================

def processar_evento(evento):
    if not evento:
        return

    partes_data = []

    for linha in evento.splitlines():
        linha = linha.strip()

        if not linha or linha.startswith(":"):
            continue

        if linha.startswith("data:"):
            conteudo = linha[5:].strip()

            if conteudo:
                partes_data.append(conteudo)

    if not partes_data:
        return

    try:
        payload = json.loads("\n".join(partes_data))
    except Exception:
        print("JSON SSE inválido:")
        print("\n".join(partes_data)[:2000])
        return

    rodada = normalizar_rodada(payload)

    if not rodada:
        return

    try:
        foi_salva = salvar_rodada(rodada)

        if foi_salva:
            total = contar_rodadas()

            print("========================================")
            print("🟢 NOVA RODADA SALVA")
            print("ID:", rodada["rodada_id"])
            print("COR:", rodada["resultado"])
            print("NÚMERO:", rodada["numero"])
            print("HORÁRIO:", rodada["tempo"])
            print("TIPO:", rodada["tipo"])
            print("TOTAL NO BANCO:", total)
            print("========================================")
        else:
            print("↩️ Rodada já estava no banco:", rodada["rodada_id"])

    except Exception:
        print("ERRO PROCESSANDO RODADA:")
        traceback.print_exc()


# ============================================================
# CAPTURA CONTÍNUA
# ============================================================

def capturar_24h():
    print("========================================")
    print("🚀 CAPTURADOR TIPMINER 24H INICIANDO")
    print("========================================")
    print("SSE:", TIPMINER_SSE_URL)

    while True:
        resposta = None

        try:
            print("🔌 Conectando ao TipMiner...")

            resposta = requests.get(
                TIPMINER_SSE_URL,
                stream=True,
                timeout=(30, None),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

            print("STATUS:", resposta.status_code)
            print("CONTENT-TYPE:", resposta.headers.get("Content-Type"))

            resposta.raise_for_status()

            print("========================================")
            print("🟢 SSE TIPMINER CONECTADO")
            print("📡 CAPTURA CONTÍNUA ATIVA")
            print("========================================")

            evento_atual = []

            for linha in resposta.iter_lines(
                decode_unicode=True,
                chunk_size=1,
            ):
                if linha is None:
                    continue

                if isinstance(linha, bytes):
                    linha = linha.decode("utf-8", errors="replace")

                linha = linha.rstrip("\r")

                if linha == "":
                    if evento_atual:
                        processar_evento("\n".join(evento_atual))
                        evento_atual = []

                    continue

                evento_atual.append(linha)

            if evento_atual:
                processar_evento("\n".join(evento_atual))

            print("⚠️ SSE foi encerrado pelo servidor.")

        except requests.RequestException as erro:
            print("========================================")
            print("🔴 ERRO DE CONEXÃO TIPMINER")
            print(type(erro).__name__, str(erro))
            print("========================================")

        except Exception as erro:
            print("========================================")
            print("🔴 ERRO NO CAPTURADOR")
            print(type(erro).__name__, str(erro))
            print("========================================")
            traceback.print_exc()

        finally:
            if resposta is not None:
                try:
                    resposta.close()
                except Exception:
                    pass

        print("🔄 Reconectando em 5 segundos...")
        time.sleep(5)


# ============================================================
# SERVIÇO HTTP MÍNIMO PARA A BELMO
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/healthz"):
            try:
                total = contar_rodadas()
                corpo = (
                    "TipMiner capturador 24h OK\n"
                    f"rodadas_no_banco={total}\n"
                )
                status = 200
            except Exception as erro:
                corpo = f"Capturador ativo, banco com erro: {erro}\n"
                status = 503

            dados = corpo.encode("utf-8")

            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, formato, *args):
        print("HTTP:", formato % args)


def iniciar_servidor_web():
    porta = int(os.getenv("PORT", "8080"))
    servidor = ThreadingHTTPServer(("0.0.0.0", porta), HealthHandler)

    print("========================================")
    print("🌐 SERVIÇO WEB BELMO ATIVO")
    print("PORTA:", porta)
    print("HEALTH:", "/health")
    print("========================================")

    servidor.serve_forever()


# ============================================================
# INÍCIO
# ============================================================

if __name__ == "__main__":
    inicializar_banco()

    try:
        print("RODADAS EXISTENTES:", contar_rodadas())
    except Exception:
        traceback.print_exc()

    # Captura roda em segundo plano enquanto o servidor HTTP
    # mantém o Serviço Web da Belmo saudável.
    thread_captura = threading.Thread(
        target=capturar_24h,
        name="tipminer-capturador",
        daemon=True,
    )
    thread_captura.start()

    iniciar_servidor_web()
