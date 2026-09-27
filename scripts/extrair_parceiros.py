"""
Extrai a lista de parceiros ativos (nome + categoria) do Mapa de Parceiros
B2C. Usado pelo agente (Mingo) para responder com nomes reais de parceiro,
em vez de admitir que não sabe ou inventar.

Uso:
    python scripts/extrair_parceiros.py caminho/Mapa_de_Parceiros_B2C.xlsx data/parceiros.json
"""

import json
import sys

import openpyxl


def extrair(caminho_xlsx: str) -> list[dict]:
    wb = openpyxl.load_workbook(caminho_xlsx, data_only=True)
    ws = wb["Parceiros"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    parceiros = []
    for row in rows:
        status, parceiro, categoria = row[0], row[1], row[2]
        if not status or "ativo" not in status.lower() or "desativ" in status.lower():
            continue
        if parceiro and categoria:
            parceiros.append({
                "nome": str(parceiro).strip(),
                "categoria": str(categoria).strip(),
            })
    return parceiros


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python scripts/extrair_parceiros.py <entrada.xlsx> <saida.json>")
        sys.exit(1)

    entrada, saida = sys.argv[1], sys.argv[2]
    dados = extrair(entrada)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(dados)} parceiros extraídos de {entrada} -> {saida}")
