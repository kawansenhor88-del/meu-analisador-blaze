def carregar_historico_tipminer_400():
    print("========================================")
    print("📥 BUSCANDO 400 RODADAS DO TIPMINER")
    print("========================================")

    params = {
        "limit": 400,
        "subject": "filter",
        "isLoadMore": "true",
        "t": int(time.time() * 1000),
        "timezone": "America/Sao_Paulo",
        "_cb": str(time.time())
    }

    headers = {
        "accept": "*/*",
        "accept-language": "pt-BR",
        "authorization": f"Bearer {TIPMINER_AUTH_TOKEN}",
        "content-type": "application/json",
        "origin": "https://www.tipminer.com",
        "referer": "https://www.tipminer.com/",
        "user-agent": "Mozilla/5.0"
    }

    try:
        resposta = requests.get(
            TIPMINER_HISTORY_URL,
            params=params,
            headers=headers,
            timeout=30
        )

        print("🌐 HTTP:", resposta.status_code)

        resposta.raise_for_status()

        dados = resposta.json()

        # O endpoint pode devolver a lista diretamente
        # ou dentro de uma propriedade do JSON.
        if isinstance(dados, list):
            registros = dados

        elif isinstance(dados, dict):
            registros = None

            for chave in (
                "history",
                "rounds",
                "data",
                "results",
                "items"
            ):
                valor = dados.get(chave)

                if isinstance(valor, list):
                    registros = valor
                    break

            if registros is None:
                registros = []

                def procurar_listas(obj):
                    if isinstance(obj, list):
                        for item in obj:
                            if isinstance(item, dict):
                                if (
                                    item.get("uuid")
                                    or item.get("id")
                                    or item.get("instant")
                                    or item.get("result")
                                ):
                                    registros.append(item)
                            else:
                                procurar_listas(item)

                    elif isinstance(obj, dict):
                        for valor in obj.values():
                            procurar_listas(valor)

                procurar_listas(dados)

        else:
            registros = []

        print("📊 REGISTROS RECEBIDOS:", len(registros))

        if not registros:
            print("❌ Nenhum registro encontrado.")
            return

        adicionados = 0

        # O histórico do TipMiner vem mais recente primeiro.
        # Colocamos do mais antigo para o mais recente para
        # alimentar corretamente o histórico.
        registros = list(reversed(registros))

        for item in registros:
            if not isinstance(item, dict):
                continue

            payload = dict(item)

            if not payload.get("type"):
                payload["type"] = "DOUBLE"

            if adicionar_rodada(payload):
                adicionados += 1

        print("========================================")
        print("📊 RESULTADO DO HISTÓRICO")
        print("SOLICITADAS: 400")
        print("RECEBIDAS:", len(registros))
        print("ADICIONADAS:", adicionados)
        print("TOTAL NO POSTGRESQL:", contar_rodadas_banco())
        print("========================================")

    except Exception as erro:
        print("========================================")
        print("❌ ERRO AO BUSCAR HISTÓRICO TIPMINER")
        print("TIPO:", type(erro).__name__)
        print("ERRO:", str(erro))
        print("========================================")
        traceback.print_exc()
