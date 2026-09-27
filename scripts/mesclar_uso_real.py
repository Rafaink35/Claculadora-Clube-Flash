"""
Mescla o uso real (frequência e ticket médio por categoria, vindos do
Databricks) em cima do data/categorias.json gerado por extrair_categorias.py.

Uso:
    python scripts/mesclar_uso_real.py

Lê data/uso_real.json (formato: {"NomeDaCategoria": {"freq_media_mes": ...,
"ticket_medio": ...}, ...}) e sobrescreve freq/ticket em data/categorias.json
para as categorias presentes ali. Categorias sem entrada em uso_real.json
mantêm o valor estimado, marcado como tal em fonte_uso.

Para atualizar com uma nova consulta do Databricks: gere um novo
uso_real.json (mesmo formato) e rode este script de novo.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CATEGORIAS_PATH = DATA_DIR / "categorias.json"
USO_REAL_PATH = DATA_DIR / "uso_real.json"


def mesclar():
    with open(CATEGORIAS_PATH, encoding="utf-8") as f:
        categorias = json.load(f)

    with open(USO_REAL_PATH, encoding="utf-8") as f:
        uso_real = json.load(f)

    for cat in categorias:
        nome = cat["nome"]
        if nome in uso_real:
            real = uso_real[nome]
            cat["freq"] = real["freq_media_mes"]
            cat["ticket"] = real["ticket_medio"]
            cat["fonte_uso"] = "real (mai-set/2026)"
        else:
            cat.setdefault("fonte_uso", "estimativa (sem transação real desde 2023)")

    with open(CATEGORIAS_PATH, "w", encoding="utf-8") as f:
        json.dump(categorias, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(categorias)} categorias mescladas -> {CATEGORIAS_PATH}")


if __name__ == "__main__":
    mesclar()
