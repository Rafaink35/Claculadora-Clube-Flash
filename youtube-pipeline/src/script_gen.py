"""Etapa 1: gera roteiro (script.md) e metadados (metadata.json) com o Claude."""
import json, os
from pathlib import Path

import pandas as pd


def get_topic(cfg, slug):
    """Procura o tema no backlog: o slug é o tema 'slugificado' ou o número da linha."""
    df = pd.read_csv(cfg["paths"]["backlog"])
    for i, tema in enumerate(df["tema"], start=1):
        if slug in (slugify(tema), str(i)):
            return tema
    raise SystemExit(f"Tema '{slug}' não encontrado em {cfg['paths']['backlog']}")


def slugify(text):
    import re, unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:50]


def run(cfg, slug, dry_run=False):
    out = Path(cfg["paths"]["output"]) / slug
    out.mkdir(parents=True, exist_ok=True)
    if (out / "script.md").exists():
        print("[script] já existe, pulando (apague script.md para refazer)")
        return
    tema = get_topic(cfg, slug)
    prompt = Path("templates/script_prompt.md").read_text(encoding="utf-8").format(
        language="português do Brasil" if cfg["language"] == "pt" else "English", tema=tema)

    # Sem chave de API: salva o prompt para colar no Claude manualmente.
    if dry_run or not os.getenv("ANTHROPIC_API_KEY"):
        (out / "prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"[script] sem chamada de API. Prompt salvo em {out/'prompt.txt'}")
        return

    import anthropic  # usa créditos de API: só roda sem --dry-run e com chave
    resp = anthropic.Anthropic().messages.create(
        model=cfg.get("script_model", "claude-sonnet-5-5"), max_tokens=6000,
        messages=[{"role": "user", "content": prompt}])
    text = resp.content[0].text
    data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    (out / "script.md").write_text(data.pop("script_md"), encoding="utf-8")
    (out / "metadata.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[script] gerado em {out}")
