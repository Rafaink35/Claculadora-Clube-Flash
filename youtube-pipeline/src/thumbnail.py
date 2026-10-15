"""Etapa 5: gera 2 variações (A/B) de miniatura 1280x720 com Pillow.

Texto: thumbnail_texto do metadata.json (máx. 4 palavras). Sem rosto, 1 elemento gráfico.
A: cronômetro  |  B: seta antes -> depois
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def font(size):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def draw_timer(d, cx, cy, r, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=14)
    d.line([cx, cy, cx, cy - r * 0.65], fill=color, width=14)       # ponteiro grande
    d.line([cx, cy, cx + r * 0.45, cy + r * 0.2], fill=color, width=14)
    d.rectangle([cx - 25, cy - r - 40, cx + 25, cy - r - 14], fill=color)  # botão


def draw_arrow(d, x, y, length, color):
    d.line([x, y, x + length, y], fill=color, width=24)
    d.polygon([(x + length - 10, y - 55), (x + length + 60, y), (x + length - 10, y + 55)], fill=color)


def make(cfg, text, variant, path):
    t = cfg["thumbnail"]
    W, H = t["width"], t["height"]
    img = Image.new("RGB", (W, H), t["background"])
    d = ImageDraw.Draw(img)
    color = t["text_color"]
    words = text.upper().split()
    # texto grande à esquerda, uma palavra por linha se ficar longo
    lines = words if len(words) > 2 else [" ".join(words)]
    size = 170 if len(lines) <= 2 else 130
    y = (H - len(lines) * size * 1.05) / 2
    for line in lines:
        d.text((70, y), line, font=font(size), fill=color)
        y += size * 1.05
    if variant == "A":
        draw_timer(d, 1030, 360, 150, color)
    else:
        draw_arrow(d, 760, 360, 300, color)
    img.save(path)


def run(cfg, slug, dry_run=False, text=None):
    out = Path(cfg["paths"]["output"]) / slug
    meta = out / "metadata.json"
    if not text and meta.exists():
        text = json.loads(meta.read_text(encoding="utf-8")).get("thumbnail_texto")
    if not text:
        raise SystemExit("[thumbnail] sem texto: gere o metadata.json ou use --thumb-text")
    if len(text.split()) > cfg["thumbnail"]["max_words"]:
        raise SystemExit(f"[thumbnail] máx. {cfg['thumbnail']['max_words']} palavras")
    if dry_run:
        return
    out.mkdir(parents=True, exist_ok=True)
    for v, name in (("A", "thumbnail.png"), ("B", "thumbnail_B.png")):
        make(cfg, text, v, out / name)
    print(f"[thumbnail] {out}/thumbnail.png e thumbnail_B.png")
