# TESTE ISOLADO DE ALINHAMENTO DO SURF
# ------------------------------------
# Este arquivo NAO altera o bot.py.
# Objetivo: testar uma unica regra que funcione para indices de 2, 3 e 4 digitos.
#
# Ideia principal:
# - O indice da rodada ocupa SEMPRE 4 posicoes visuais.
# - Para completar as posicoes faltantes usamos FIGURE SPACE (U+2007),
#   que tende a ter a mesma largura visual de um algarismo.
# - O numero real tambem ocupa um campo fixo de 2 algarismos.
# - O marcador da esquerda (✅ / ❌Gx) recebe compensacao automatica.
# - Nao existe regra especial para 99, 999, 1000 etc.

FIGURE_SPACE = "\u2007"   # espaco com largura proxima a um digito
HAIR_SPACE = "\u200A"     # ajuste fino


def campo_indice(numero: int, largura: int = 4) -> str:
    """Faz 10, 100 e 1000 terminarem na mesma coluna visual."""
    texto = str(numero)
    faltam = max(0, largura - len(texto))
    return (FIGURE_SPACE * faltam) + texto


def campo_numero_real(numero_real) -> str:
    """Reserva 2 posicoes para 0..14 sem regra por faixa."""
    texto = str(numero_real)
    if len(texto) == 1:
        return texto + FIGURE_SPACE
    return texto


def marcador_normalizado(marcador: str) -> str:
    """
    Normaliza a largura FINAL da coluna esquerda.
    A ideia e compensar apenas o marcador, nunca o numero da rodada.

    O valor fino abaixo e propositalmente centralizado aqui para calibracao.
    Se o Telegram pedir um ajuste, mexemos SO nesta funcao.
    """
    if marcador == "✅":
        # ✅ e visualmente menor que ❌G1 no Telegram.
        return marcador + (FIGURE_SPACE * 2) + (HAIR_SPACE * 4)

    if marcador.startswith("❌G"):
        # G1..G9 e GA..GZ ficam no mesmo campo-base.
        return marcador + FIGURE_SPACE

    return marcador + FIGURE_SPACE


def montar_coluna(numero, cor_real, numero_real, cor_jogada, marcador):
    indice = campo_indice(numero)
    real = campo_numero_real(numero_real)
    return f"{indice}{FIGURE_SPACE}{cor_real}{real}-{cor_jogada}{marcador_normalizado(marcador)}"


def montar_linha(numero, saiu_cor, saiu_numero,
                  jogada_esq, marcador_esq,
                  jogada_dir, marcador_dir):
    esquerda = montar_coluna(numero, saiu_cor, saiu_numero, jogada_esq, marcador_esq)
    direita = montar_coluna(numero, saiu_cor, saiu_numero, jogada_dir, marcador_dir)

    # Separacao entre as duas colunas e fixa.
    # Como os campos internos ja foram normalizados, nao depende de 2/3/4 digitos.
    separador_colunas = FIGURE_SPACE * 2
    return esquerda + separador_colunas + direita


def gerar_teste():
    casos = [
        (10,   "🔴", 7,  "⚫", "❌G1", "🔴", "✅"),
        (11,   "⚫", 12, "🔴", "❌G2", "⚫", "✅"),
        (99,   "⚪", 0,  "🔴", "❌G3", "⚫", "❌G1"),
        (100,  "🔴", 3,  "⚫", "✅",   "🔴", "❌G1"),
        (101,  "⚫", 14, "🔴", "❌G1", "⚫", "✅"),
        (999,  "🔴", 6,  "⚫", "❌G2", "🔴", "✅"),
        (1000, "🔴", 7,  "⚫", "❌G1", "🔴", "✅"),
        (1001, "⚪", 0,  "🔴", "❌G2", "⚫", "❌G1"),
        (1099, "⚫", 12, "🔴", "✅",   "⚫", "❌G1"),
        (1100, "🔴", 5,  "⚫", "❌G3", "🔴", "✅"),
        (1499, "⚫", 8,  "🔴", "❌GA", "⚫", "✅"),
        (1999, "🔴", 2,  "⚫", "✅",   "🔴", "❌G2"),
    ]

    linhas = [
        "TESTE DE ALINHAMENTO — 2 / 3 / 4 DÍGITOS",
        "",
        "SURF🔴" + (FIGURE_SPACE * 8) + "SURF⚫",
        "",
    ]

    for caso in casos:
        linhas.append(montar_linha(*caso))

    return "\n".join(linhas)


if __name__ == "__main__":
    saida = gerar_teste()
    print(saida)

    with open("teste_alinhamento_saida.txt", "w", encoding="utf-8") as arquivo:
        arquivo.write(saida)

    print("\nArquivo criado: teste_alinhamento_saida.txt")
