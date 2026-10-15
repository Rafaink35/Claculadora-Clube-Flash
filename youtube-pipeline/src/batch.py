"""Planejamento em lote: roteiros dos próximos temas + calendário de publicação do mês."""
import calendar
from datetime import date

import pandas as pd

from src import script_gen

DAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}  # monday=0


def slots(cfg, month):
    """Datas do mês nos dias da semana configurados (ex.: terça e quinta)."""
    y, m = map(int, month.split("-"))
    wanted = {DAYS[d.lower()] for d in cfg["schedule"]["days"]}
    n = calendar.monthrange(y, m)[1]
    return [date(y, m, d) for d in range(1, n + 1) if date(y, m, d).weekday() in wanted]


def run(cfg, month, dry_run=False):
    path = cfg["paths"]["backlog"]
    df = pd.read_csv(path, dtype=str).fillna("")
    # pendentes e já em produção: rodar de novo escolhe os mesmos temas
    todo = df[df["status"].isin(["pendente", "em_producao"])].head(cfg["schedule"]["videos_per_month"])
    dates = slots(cfg, month)
    if todo.empty:
        raise SystemExit("[batch] backlog sem temas pendentes")
    print(f"Calendário {month} ({cfg['schedule']['time']}, {cfg['schedule']['timezone']}):")
    for (idx, row), d in zip(todo.iterrows(), dates):
        slug = script_gen.slugify(row["tema"])
        print(f"  {d:%d/%m} ({d.strftime('%a')}): {row['tema']}  [{slug}]")
        script_gen.run(cfg, slug, dry_run)
        df.loc[idx, ["status", "data_alvo"]] = ["em_producao", d.isoformat()]
    if len(dates) < len(todo):
        print(f"[batch] atenção: só {len(dates)} datas no mês para {len(todo)} temas")
    if not dry_run:
        df.to_csv(path, index=False, encoding="utf-8")
