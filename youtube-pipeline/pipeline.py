#!/usr/bin/env python3
"""Orquestrador. Uso: python pipeline.py <slug> [--stage script|audio|captions] [--dry-run]"""
import argparse, sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from src import audio, captions, script_gen

STAGES = {"script": script_gen, "audio": audio, "captions": captions}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", help="slug ou número do tema no backlog")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_dotenv()
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    slug = args.slug
    if slug.isdigit():  # número da linha no backlog -> slug do tema
        slug = script_gen.slugify(script_gen.get_topic(cfg, slug))
        print(f"slug: {slug}")
    for name, mod in STAGES.items():
        if args.stage in (None, name):
            mod.run(cfg, slug, args.dry_run)


if __name__ == "__main__":
    main()
