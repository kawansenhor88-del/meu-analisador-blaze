# ==============================================================================
# TESTE DA API HISTORY 5000
# ==============================================================================

@bot.message_handler(commands=["teste200"])
def teste_200(message):
    try:
        url = (
            "https://api.core.public.tipminer.com/"
            "v1/double/rounds/"
            "6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"
        )

        params = {
            "limit": 5000,
            "subject": "filter",
            "isLoadMore": "true",
            "t": int(time.time() * 1000),
            "timezone": "America/Sao_Paulo",
            "_cb": str(uuid.uuid4())
        }

        print("========================================")
        print("TESTE HISTORY 5000")
        print("CONSULTANDO API...")
        print("========================================")

        resposta = requests.get(
            url,
            params=params,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Cache-Control": "no-cache"
            }
        )

        print("STATUS:", resposta.status_code)

        if resposta.status_code != 200:
            bot.reply_to(
                message,
                f"❌ API respondeu HTTP {resposta.status_code}"
            )
            return

        dados = resposta.json()

        # Tentar localizar a lista de rodadas
        if isinstance(dados, list):
            rodadas = dados

        elif isinstance(dados, dict):
            rodadas = (
                dados.get("data")
                or dados.get("rounds")
                or dados.get("items")
                or dados.get("results")
                or []
            )

        else:
            rodadas = []

        print("REGISTROS RECEBIDOS:", len(rodadas))

        if not rodadas:
            print("RESPOSTA BRUTA:")
            print(json.dumps(dados, ensure_ascii=False)[:5000])

            bot.reply_to(
                message,
                "⚠️ A API respondeu 200, mas não encontrei a lista de rodadas."
            )
            return

        # Mostrar estrutura no log
        print("========================================")
        print("PRIMEIRO REGISTRO:")
        print(json.dumps(rodadas[0], ensure_ascii=False))

        print("========================================")
        print("ÚLTIMO REGISTRO:")
        print(json.dumps(rodadas[-1], ensure_ascii=False))

        print("========================================")

        bot.reply_to(
            message,
            f"🧪 TESTE HISTORY 5000\n\n"
            f"✅ HTTP: {resposta.status_code}\n"
            f"📊 Registros recebidos: {len(rodadas)}\n\n"
            f"Agora vou enviar os registros para você comparar com o TipMiner."
        )

        texto = ""

        for i, rodada in enumerate(rodadas, start=1):

            if isinstance(rodada, dict):

                numero = (
                    rodada.get("number")
                    or rodada.get("numero")
                    or rodada.get("roll")
                    or rodada.get("result")
                    or rodada.get("value")
                    or "?"
                )

                horario = (
                    rodada.get("time")
                    or rodada.get("tempo")
                    or rodada.get("createdAt")
                    or rodada.get("created_at")
                    or rodada.get("instant")
                    or rodada.get("timestamp")
                    or "?"
                )

                rodada_id = (
                    rodada.get("id")
                    or rodada.get("uuid")
                    or rodada.get("roundId")
                    or rodada.get("round_id")
                    or "?"
                )

                linha = (
                    f"{i:03d}. 🎯 {numero} | "
                    f"⏰ {horario} | "
                    f"ID: {rodada_id}\n"
                )

            else:
                linha = f"{i:03d}. {rodada}\n"

            if len(texto) + len(linha) > 3500:
                bot.send_message(
                    message.chat.id,
                    texto
                )
                texto = ""

            texto += linha

        if texto:
            bot.send_message(
                message.chat.id,
                texto
            )

        print("========================================")
        print("TESTE FINALIZADO")
        print("TOTAL ENVIADO AO TELEGRAM:", len(rodadas))
        print("========================================")

    except Exception as erro:

        print("========================================")
        print("ERRO NO TESTE HISTORY 5000")
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))
        traceback.print_exc()
        print("========================================")

        bot.reply_to(
            message,
            f"❌ Erro no teste:\n"
            f"{type(erro).__name__}: {str(erro)[:500]}"
                )
