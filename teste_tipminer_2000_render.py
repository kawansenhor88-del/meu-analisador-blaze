import os, sys, json, uuid, time, hashlib, requests

URL = "https://api.core.public.tipminer.com/v1/double/rounds/6ee2f33f-7dbf-40ae-b01c-b05368c806ba/history"

TOKEN = (os.environ.get("TIPMINER_TOKEN") or "").strip()
if TOKEN.lower().startswith("bearer "):
    TOKEN = TOKEN[7:].strip()

if not TOKEN:
    print("ERRO: configure TIPMINER_TOKEN no Render.")
    sys.exit(1)

print("=" * 60)
print("TESTE ISOLADO - TIPMINER HISTORY")
print("=" * 60)
print("TOKEN TAMANHO:", len(TOKEN))
print("TOKEN SHA256 :", hashlib.sha256(TOKEN.encode()).hexdigest())
print("O token NAO sera exibido.\n")

params = {
    "limit": 2000,
    "subject": "filter",
    "isLoadMore": "true",
    "t": str(int(time.time() * 1000)),
    "timezone": "America/Sao_Paulo",
    "_cb": str(uuid.uuid4()),
}
headers = {
    "Accept": "*/*",
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Origin": "https://www.tipminer.com",
    "Referer": "https://www.tipminer.com/",
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
}

s = requests.Session()
s.trust_env = False

try:
    r = s.get(URL, params=params, headers=headers, timeout=30, allow_redirects=False)
    print("HTTP:", r.status_code)
    print("URL FINAL:", r.request.url)
    safe = {k: ("Bearer [OCULTO]" if k.lower()=="authorization" else v)
            for k,v in r.request.headers.items()}
    print("HEADERS ENVIADOS:")
    print(json.dumps(safe, indent=2, ensure_ascii=False))
    print()
    data = r.json()
    qtd = len(data) if isinstance(data, list) else None
    if qtd is None and isinstance(data, dict):
        for key in ("data","results","items","rounds"):
            if isinstance(data.get(key), list):
                qtd = len(data[key])
                print("LISTA NA CHAVE:", key)
                break
    print("=" * 60)
    print("REGISTROS:", qtd)
    if qtd == 2000:
        print("SUCESSO: O RENDER RECEBEU AS 2.000 RODADAS.")
    elif qtd == 200:
        print("DIAGNOSTICO: O RENDER CONTINUA RECEBENDO APENAS 200.")
    else:
        print("DIAGNOSTICO: resposta com quantidade diferente.")
except Exception as e:
    print("ERRO:", type(e).__name__, str(e))
    sys.exit(2)
