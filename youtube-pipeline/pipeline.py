#!/usr/bin/env python3
"""Orquestrador. Lote: python pipeline.py batch --month YYYY-MM [--dry-run]
Uso: python pipeline.py <slug> [--stage script|audio|captions|video|thumbnail|review|upload] [--dry-run]"""
import argparse, sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from src import audio, captions, script_gen, batch, review, thumbnail, upload, video

STAGES = {"script": script_gen, "audio": audio, "captions": captions,
          "video": video, "thumbnail": thumbnail}
# review e upload só rodam se pedidos com --stage (nada publica sem querer)
MANUAL = {"review": review, "upload": upload}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", help="slug ou número do tema no backlog")
    ap.add_argument("--stage", choices=[*STAGES, *MANUAL])
    ap.add_argument("--publish-at", help="upload: data futura ISO com fuso, ex. 2026-10-20T11:30:00-03:00")
    ap.add_argument("--month", help="batch: mês YYYY-MM")
    ap.add_argument("--thumb-text", help="texto da miniatura (máx. 4 palavras)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_dotenv()
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    if args.slug == "batch":
        if not args.month:
            sys.exit("batch exige --month YYYY-MM")
        return batch.run(cfg, args.month, args.dry_run)
    slug = args.slug
    if slug.isdigit():  # número da linha no backlog -> slug do tema
        slug = script_gen.slugify(script_gen.get_topic(cfg, slug))
        print(f"slug: {slug}")
    if args.stage in MANUAL:
        extra = (args.publish_at,) if args.stage == "upload" else ()
        MANUAL[args.stage].run(cfg, slug, args.dry_run, *extra)
        return
    for name, mod in STAGES.items():
        if args.stage in (None, name):
            if name == "thumbnail":
                mod.run(cfg, slug, args.dry_run, args.thumb_text)
            else:
                mod.run(cfg, slug, args.dry_run)


if __name__ == "__main__":
    main()
