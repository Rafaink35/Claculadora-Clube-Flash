"""Etapa 3: legendas com Whisper local (faster-whisper) -> captions.srt editável."""
from pathlib import Path


def ts(t):
    h, r = divmod(int(t * 1000), 3600000)
    m, r = divmod(r, 60000)
    s, ms = divmod(r, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def run(cfg, slug, dry_run=False):
    out = Path(cfg["paths"]["output"]) / slug
    srt = out / "captions.srt"
    audio = out / "voice_clean.wav"
    if srt.exists():
        print("[captions] já existe, pulando (o SRT pode ter edições suas)")
        return
    if not audio.exists():
        raise SystemExit("[captions] rode a etapa audio antes")
    if dry_run:
        return
    from faster_whisper import WhisperModel  # baixa o modelo na 1ª execução
    model = WhisperModel(cfg["captions"]["model"], compute_type="int8")
    segs, _ = model.transcribe(str(audio), language=cfg["language"])
    with open(srt, "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{ts(s.start)} --> {ts(s.end)}\n{s.text.strip()}\n\n")
    print(f"[captions] {srt} — revise nomes de ferramentas e termos técnicos")
