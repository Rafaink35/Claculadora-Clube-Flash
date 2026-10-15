"""Etapa 2: limpa a voz (silêncios, ruído, loudness) e mixa música de fundo."""
import subprocess
from pathlib import Path


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def run(cfg, slug, dry_run=False):
    a = cfg["audio"]
    src = Path(cfg["paths"]["input"]) / slug / "voice.wav"
    out = Path(cfg["paths"]["output"]) / slug
    out.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise SystemExit(f"[audio] falta {src}")
    clean, mix = out / "voice_clean.wav", out / "audio_mix.wav"

    # highpass+afftdn: ruído leve; silenceremove: corta silêncios longos; loudnorm: ~-16 LUFS
    filt = (f"highpass=f=80,afftdn=nr=10,"
            f"silenceremove=stop_periods=-1:stop_duration={a['silence_min_seconds']}:"
            f"stop_threshold={a['silence_threshold_db']}dB,"
            f"loudnorm=I={a['target_lufs']}:TP=-1.5:LRA=11")
    if not clean.exists():
        print("[audio] limpando voz...")
        if not dry_run:
            ff("-i", src, "-af", filt, clean)

    tracks = sorted(Path(cfg["paths"]["music"]).glob("*.mp3")) + sorted(Path(cfg["paths"]["music"]).glob("*.wav"))
    if not tracks:
        print("[audio] sem música em music/: audio_mix = voz limpa")
        if not dry_run and not mix.exists():
            ff("-i", clean, mix)
        return
    if not mix.exists():
        print(f"[audio] mixando com {tracks[0].name}...")
        if not dry_run:
            dur = float(subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", clean]).decode())
            f = a["music_fade_seconds"]
            fc = (f"[1:a]volume={a['music_volume']},afade=t=in:d={f},"
                  f"afade=t=out:st={max(dur - f, 0)}:d={f}[m];"
                  f"[0:a][m]amix=inputs=2:duration=first:normalize=0[o]")
            ff("-i", clean, "-stream_loop", "-1", "-i", tracks[0],
               "-filter_complex", fc, "-map", "[o]", "-t", dur, mix)
