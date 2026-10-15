"""Etapa 4: monta o vídeo final (tela + b-roll + áudio + legendas) e um Short 9:16.

B-roll opcional: crie input/<slug>/broll.csv com as colunas  arquivo,inicio,duracao
(arquivo dentro de input/<slug>/broll/, tempos em segundos). O b-roll é só apoio:
cobre a tela por alguns segundos, sem trocar o áudio.
"""
import csv, subprocess
from pathlib import Path


def ff(*args, cwd=None):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True, cwd=cwd)


def run(cfg, slug, dry_run=False):
    v = cfg["video"]
    src = (Path(cfg["paths"]["input"]) / slug).resolve()
    out = (Path(cfg["paths"]["output"]) / slug).resolve()
    screen, mix, srt = src / "screen.mp4", out / "audio_mix.wav", out / "captions.srt"
    final, short = out / "video_final.mp4", out / "short_vertical.mp4"
    for f in (screen, mix, srt):
        if not f.exists():
            raise SystemExit(f"[video] falta {f} (rode as etapas anteriores)")
    if final.exists() and short.exists():
        print("[video] já existe, pulando (apague video_final.mp4 para refazer)")
        return
    if dry_run:
        return

    w, h, fps = v["width"], v["height"], v["fps"]
    # base: tela em 1920x1080 com barras se a proporção for diferente
    chain = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1[base]")
    inputs = ["-i", screen, "-i", mix]
    last = "base"
    brolls = src / "broll.csv"
    rows = list(csv.DictReader(open(brolls, encoding="utf-8"))) if brolls.exists() else []
    for n, r in enumerate(rows):
        a, d = float(r["inicio"]), float(r["duracao"])
        inputs += ["-i", src / "broll" / r["arquivo"]]
        k = n + 2  # 0 = tela, 1 = áudio
        # setpts desloca o clipe para começar em 'inicio'; enable limita a janela
        chain += (f";[{k}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                  f"fps={fps},setpts=PTS-STARTPTS+{a}/TB[b{n}]"
                  f";[{last}][b{n}]overlay=enable='between(t,{a},{a + d})':eof_action=pass[o{n}]")
        last = f"o{n}"
    # legendas queimadas (cwd = pasta de saída, evita problema de escape no caminho)
    style = "FontName=Inter,FontSize=22,Outline=2,Shadow=0,MarginV=40,Bold=1"
    chain += f";[{last}]subtitles=captions.srt:force_style='{style}'[vout]"
    print("[video] renderizando (pode demorar)...")
    ff(*inputs, "-filter_complex", chain, "-map", "[vout]", "-map", "1:a",
       "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "192k", "-shortest", final, cwd=out)

    # Short 9:16: primeiros N segundos (hook + 1º passo), recorte central
    print("[video] gerando Short vertical...")
    ff("-i", final, "-t", v["vertical_short_seconds"],
       "-vf", "crop=ih*9/16:ih,scale=1080:1920", "-c:v", "libx264", "-crf", "21",
       "-pix_fmt", "yuv420p", "-c:a", "aac", short)
    print(f"[video] {final.name} e {short.name} prontos")
