"""Etapa 7: envia ao YouTube como PRIVADO com publicação agendada (publishAt).

Nunca publica direto. Exige review.md aprovado. OAuth abre o navegador no seu computador.
--dry-run valida tudo sem enviar e sem precisar das bibliotecas do Google.
"""
import json, os
from datetime import datetime, timezone
from pathlib import Path

from src import review

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def build_body(cfg, meta, publish_at, title_index=0):
    desc = meta.get("descricao", "")
    chapters = meta.get("capitulos") or []
    if chapters:
        desc += "\n\nCapítulos:\n" + "\n".join(f"{c['tempo']} {c['titulo']}" for c in chapters)
    title = meta["titulos"][title_index]
    tags = meta.get("tags", [])
    # limites da API do YouTube
    if len(title) > 100:
        raise SystemExit(f"[upload] título com {len(title)} caracteres (máx. 100)")
    if len(desc) > 5000:
        raise SystemExit("[upload] descrição passa de 5000 caracteres")
    if sum(len(t) + 1 for t in tags) > 500:
        raise SystemExit("[upload] tags passam de 500 caracteres no total")
    return {
        "snippet": {"title": title, "description": desc, "tags": tags,
                    "categoryId": cfg["upload"]["category_id"],
                    "defaultLanguage": cfg["language"], "defaultAudioLanguage": cfg["language"]},
        "status": {"privacyStatus": "private",  # fixo: regra 1
                   "publishAt": publish_at, "selfDeclaredMadeForKids": False},
    }


def parse_publish_at(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise SystemExit("[upload] --publish-at precisa de fuso, ex.: 2026-10-20T11:30:00-03:00")
    if dt <= datetime.now(timezone.utc):
        raise SystemExit("[upload] --publish-at precisa estar no futuro")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def log(out, msg):
    with open(out / "upload.log", "a", encoding="utf-8") as f:  # nunca registrar tokens
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    token = Path(os.getenv("YOUTUBE_TOKEN_FILE", "token.json"))
    secret = os.getenv("YOUTUBE_CLIENT_SECRET", "client_secret.json")
    creds = Credentials.from_authorized_user_file(token, SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(secret, SCOPES).run_local_server(port=0)
        token.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def run(cfg, slug, dry_run=False, publish_at=None, title_index=0):
    out = Path(cfg["paths"]["output"]) / slug
    ok, why = review.check_approved(out)
    if not ok:
        raise SystemExit(f"[upload] bloqueado pela revisão: {'; '.join(why)}")
    if not publish_at:
        raise SystemExit("[upload] informe --publish-at (data futura com fuso)")
    meta_file, video, thumb = out / "metadata.json", out / "video_final.mp4", out / "thumbnail.png"
    for f in (meta_file, video, thumb):
        if not f.exists():
            raise SystemExit(f"[upload] falta {f}")
    if (out / "uploaded.json").exists():
        print("[upload] já enviado (uploaded.json). Apague-o só se quiser reenviar.")
        return
    body = build_body(cfg, json.loads(meta_file.read_text(encoding="utf-8")),
                      parse_publish_at(publish_at), title_index)
    if dry_run:
        print(f"[upload] DRY-RUN ok. Título: {body['snippet']['title']!r}, "
              f"agendado para {body['status']['publishAt']}, privado até lá. Nada foi enviado.")
        return

    from googleapiclient.http import MediaFileUpload
    yt = get_service()
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"[upload] {int(status.progress() * 100)}%")
    yt.thumbnails().set(videoId=resp["id"], media_body=MediaFileUpload(str(thumb))).execute()
    (out / "uploaded.json").write_text(json.dumps({"videoId": resp["id"]}), encoding="utf-8")
    log(out, f"enviado videoId={resp['id']} publishAt={body['status']['publishAt']}")
    print(f"[upload] enviado (privado, agendado): https://youtu.be/{resp['id']}")
