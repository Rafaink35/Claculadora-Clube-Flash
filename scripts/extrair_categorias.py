"""
Extrai o desconto médio e o número de parceiros ativos por categoria
a partir do Mapa de Parceiros B2C (aba "Parceiros").

Uso:
    python scripts/extrair_categorias.py caminho/Mapa_de_Parceiros_B2C.xlsx data/categorias.json

Este script é o ponto de atualização do MVP: sempre que o Mapa de Parceiros
mudar (novos parceiros, novos descontos), rode de novo para atualizar o
data/categorias.json que a calculadora consome. No próximo estágio, esta
função pode ser substituída por uma query direta no Databricks/Metabase.
"""

import json
import re
import sys
from collections import defaultdict

import openpyxl

PCT_RE = re.compile(r"(\d{1,3})\s*%")

# Estimativas iniciais de frequência de uso/mês e ticket médio (R$) por
# categoria. Estes dois campos NÃO vêm do Mapa de Parceiros (que é um
# catálogo, não um log de uso) — são placeholders editáveis na própria
# calculadora, até serem substituídos por dado real de uso por colaborador.
FREQ_TICKET_PADRAO = {
    "Conveniência": {"freq": 4, "ticket": 70},
    "Refeição": {"freq": 10, "ticket": 32},
    "Bem-estar": {"freq": 1, "ticket": 130},
    "Mobilidade": {"freq": 8, "ticket": 22},
    "Educação": {"freq": 0.3, "ticket": 280},
    "Saúde": {"freq": 0.5, "ticket": 160},
    "Cultura": {"freq": 1, "ticket": 55},
    "Alimentação": {"freq": 3, "ticket": 180},
    "Pets": {"freq": 0.5, "ticket": 100},
}
FREQ_TICKET_FALLBACK = {"freq": 1, "ticket": 80}

# Correções manuais documentadas, aplicadas por cima da extração automática do
# Mapa de Parceiros. Cada uma existe porque a extração simples (média entre
# parceiros, sem peso por volume) produz um número que não reflete a economia
# real. Ver nota de cada correção para o porquê.
CORRECOES_MANUAIS = {
    "Mobilidade": {
        "desconto_original": None,  # preenchido dinamicamente abaixo
        "desconto_corrigido": 0.0,
        "nota": (
            "Corrigido em 27/09/2026: dentro da própria categoria Mobilidade, 100% do TPV "
            "real dos últimos 5 meses (Databricks) vem de Bilhete Único SPTrans (74,6%), "
            "Uber (22,2%) e Uber Cards (3,2%) — nenhum com desconto percentual documentado "
            "no Mapa de Parceiros (são recarga de transporte e crédito de app, não compra "
            "com desconto). A média simples entre parceiros não reflete a economia real "
            "gerada pela categoria; o desconto real ponderado por volume é ~0%."
        ),
    },
}


def extrair(caminho_xlsx: str) -> list[dict]:
    wb = openpyxl.load_workbook(caminho_xlsx, data_only=True)
    ws = wb["Parceiros"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    cat_pct = defaultdict(list)
    cat_active = defaultdict(int)

    for row in rows:
        status, parceiro, categoria, condicao = row[0], row[1], row[2], row[3]
        if not status or "ativo" not in status.lower() or "desativ" in status.lower():
            continue
        if not categoria:
            continue
        categoria = categoria.strip()
        cat_active[categoria] += 1
        if condicao:
            for m in PCT_RE.findall(str(condicao)):
                valor = int(m)
                if 0 < valor <= 100:
                    cat_pct[categoria].append(valor)

    resultado = []
    for categoria, n_ativos in sorted(cat_active.items(), key=lambda x: -x[1]):
        valores = cat_pct.get(categoria, [])
        desconto_medio = round(sum(valores) / len(valores), 1) if valores else 15.0
        padrao = FREQ_TICKET_PADRAO.get(categoria, FREQ_TICKET_FALLBACK)
        slug = categoria.lower()
        for de, para in [("ç", "c"), ("ê", "e"), ("ã", "a"), ("ó", "o"), ("é", "e"), ("ú", "u"), (" ", "_"), ("-", "_")]:
            slug = slug.replace(de, para)
        resultado.append(
            {
                "id": slug,
                "nome": categoria,
                "parceiros": n_ativos,
                "desconto": desconto_medio,
                "n_amostra_desconto": len(valores),
                "freq": padrao["freq"],
                "ticket": padrao["ticket"],
            }
        )

    # Aplica as correções manuais documentadas acima (ver CORRECOES_MANUAIS).
    for item in resultado:
        correcao = CORRECOES_MANUAIS.get(item["nome"])
        if correcao:
            item["desconto_medio_simples_nao_ponderado"] = item["desconto"]
            item["desconto"] = correcao["desconto_corrigido"]
            item["nota_correcao"] = correcao["nota"]

    return resultado


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python scripts/extrair_categorias.py <entrada.xlsx> <saida.json>")
        sys.exit(1)

    entrada, saida = sys.argv[1], sys.argv[2]
    dados = extrair(entrada)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(dados)} categorias extraídas de {entrada} -> {saida}")
