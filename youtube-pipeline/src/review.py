"""Etapa 6: portão de aprovação. Gera review.md (checklist) e verifica antes do upload."""
import re
from pathlib import Path

CHECKLIST = [
    "Todos os `[VERIFICAR]` conferidos",
    "Nenhum `[INSERIR RESULTADO REAL]` restante",
    "Nenhum dado interno/real de cliente ou empregador na tela",
    "Título e thumbnail não prometem algo que o vídeo não entrega",
    "Legendas revisadas",
    "Áudio claro, sem trechos cortados",
]
PLACEHOLDERS = ["[VERIFICAR]", "[INSERIR RESULTADO REAL]"]


def pending_markers(out):
    """Conta marcadores que ainda estão no roteiro (informativo para o criador)."""
    script = out / "script.md"
    text = script.read_text(encoding="utf-8") if script.exists() else ""
    return {p: text.count(p) for p in PLACEHOLDERS}


def check_approved(out):
    """Retorna (ok, motivos). Só aprova se TODAS as caixas estiverem marcadas."""
    review = out / "review.md"
    if not review.exists():
        return False, ["review.md não existe: rode a etapa review"]
    boxes = re.findall(r"^- \[( |x|X)\]", review.read_text(encoding="utf-8"), re.M)
    reasons = []
    if len(boxes) < len(CHECKLIST):
        reasons.append("checklist incompleto/alterado")
    if any(b == " " for b in boxes):
        reasons.append(f"{boxes.count(' ')} item(ns) do checklist sem marcar")
    left = {k: v for k, v in pending_markers(out).items() if v}
    if left:
        reasons.append(f"marcadores ainda no roteiro: {left}")
    return not reasons, reasons


def run(cfg, slug, dry_run=False):
    out = Path(cfg["paths"]["output"]) / slug
    review = out / "review.md"
    if review.exists():  # não sobrescreve as marcações do criador
        ok, why = check_approved(out)
        print("[review] APROVADO" if ok else f"[review] pendente: {'; '.join(why)}")
        return
    if dry_run:
        return
    out.mkdir(parents=True, exist_ok=True)
    left = pending_markers(out)
    lines = [f"# Revisão: {slug}", "",
             "Marque `[x]` em cada item. O upload só roda com tudo marcado.", ""]
    lines += [f"- [ ] {item}" for item in CHECKLIST]
    lines += ["", f"Marcadores ainda no roteiro: {left}"]
    review.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[review] checklist criado em {review}")
