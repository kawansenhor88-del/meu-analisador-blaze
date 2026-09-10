import os
from flask import Flask

app = Flask(__name__)
FIGURE_SPACE = "\u2007"

def pad_numero(numero: int, largura: int) -> str:
    txt = str(numero)
    faltam = max(0, largura - len(txt))
    return FIGURE_SPACE * faltam + txt

def montar_bloco(titulo, largura_digitos, exemplos):
    linhas = [titulo, "", "SURF 🔴                 SURF ⚫", ""]
    for item in exemplos:
        numero, saiu_esq, jogaria_esq, resultado_esq, saiu_dir, jogaria_dir, resultado_dir = item
        n = pad_numero(numero, largura_digitos)
        esquerda = f"{n}  {saiu_esq}-{jogaria_esq}{resultado_esq}"
        direita = f"{n}  {saiu_dir}-{jogaria_dir}{resultado_dir}"
        linhas.append(f"{esquerda}      {direita}")
    return "\n".join(linhas)

bloco_2 = montar_bloco(
    "CAMADA — 2 DÍGITOS",
    2,
    [
        (10, "🔴7",  "⚫", "❌G1", "🔴7",  "🔴", "✅"),
        (11, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
        (25, "⚪0",  "⚫", "❌G3", "⚪0",  "🔴", "❌G1"),
        (57, "🔴3",  "⚫", "✅",   "🔴3",  "🔴", "❌G2"),
        (99, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
    ],
)

bloco_3 = montar_bloco(
    "CAMADA — 3 DÍGITOS",
    3,
    [
        (100, "🔴7",  "⚫", "❌G1", "🔴7",  "🔴", "✅"),
        (101, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
        (250, "⚪0",  "⚫", "❌G3", "⚪0",  "🔴", "❌G1"),
        (570, "🔴3",  "⚫", "✅",   "🔴3",  "🔴", "❌G2"),
        (999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
    ],
)

bloco_4 = montar_bloco(
    "CAMADA — 4 DÍGITOS",
    4,
    [
        (1000, "🔴7",  "⚫", "❌G1", "🔴7",  "🔴", "✅"),
        (1001, "⚫12", "🔴", "❌G2", "⚫12", "⚫", "✅"),
        (1250, "⚪0",  "⚫", "❌G3", "⚪0",  "🔴", "❌G1"),
        (1570, "🔴3",  "⚫", "✅",   "🔴3",  "🔴", "❌G2"),
        (1999, "⚫14", "🔴", "❌GA", "⚫14", "⚫", "✅"),
    ],
)

SAIDA = "\n\n" + bloco_2 + "\n\n" + ("─" * 28) + "\n\n" + bloco_3 + "\n\n" + ("─" * 28) + "\n\n" + bloco_4 + "\n"

@app.route("/")
def index():
    return "<pre>" + SAIDA + "</pre>"

if __name__ == "__main__":
    print("TESTE DE ALINHAMENTO — CAMADAS SEPARADAS")
    print(SAIDA)
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
