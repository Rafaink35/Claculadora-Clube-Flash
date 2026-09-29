"""
Extrai a lista de parceiros ativos — nome, categoria e desconto individual
(quando documentado na condição comercial) — do Mapa de Parceiros B2C.
Usado pelo agente (Mingo) como base de conhecimento LOCAL/estática, pra
responder "qual o desconto de tal parceiro" sem precisar de chamada extra
à API (reduz uso de cota e risco de rate limit).

Esta é a base de fallback: quando a planilha do Google (time de parcerias)
não estiver configurada ou a leitura falhar, o app usa isto.

Uso:
    python scripts/extrair_parceiros.py caminho/Mapa_de_Parceiros_B2C.xlsx data/parceiros.json
"""

import json
import re
import sys

import openpyxl

CATEGORIAS_VALIDAS = {
    "Conveniência", "Refeição", "Bem-estar", "Mobilidade", "Educação",
    "Saúde", "Cultura", "Alimentação", "Pets",
}
PCT_RE = re.compile(r"(\d{1,3})\s*%")


def extrair(caminho_xlsx: str) -> list[dict]:
    wb = openpyxl.load_workbook(caminho_xlsx, data_only=True)
    ws = wb["Parceiros"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    parceiros = []
    for row in rows:
        status, parceiro, categoria, condicao = row[0], row[1], row[2], row[3]
        if not status or "ativo" not in status.lower() or "desativ" in status.lower():
            continue
        if not parceiro or categoria not in CATEGORIAS_VALIDAS:
            continue

        pcts = [int(m) for m in PCT_RE.findall(str(condicao or "")) if 0 < int(m) <= 100]
        desconto_pct = pcts[0] if pcts else None  # primeiro % citado na condição, se houver

        parceiros.append({
            "nome": str(parceiro).strip(),
            "categoria": str(categoria).strip(),
            "desconto_pct": desconto_pct,
        })
    return parceiros


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python scripts/extrair_parceiros.py <entrada.xlsx> <saida.json>")
        sys.exit(1)

    entrada, saida = sys.argv[1], sys.argv[2]
    dados = extrair(entrada)
    com_pct = sum(1 for p in dados if p["desconto_pct"] is not None)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(dados)} parceiros extraídos ({com_pct} com % documentado) -> {saida}")
