#!/usr/bin/env python3
"""
run_outreach_pilot.py — Genera mensajes de piloto (ángulos A1–A3 + gancho A/B) y opcionalmente envía por WhatsApp.

  # Generar borradores en columnas pilot_* (requiere OPENAI_API_KEY o GROQ)
  python scripts/run_outreach_pilot.py generate output/pilot_outreach_batch2.csv

  # Regenerar todas las filas
  python scripts/run_outreach_pilot.py generate output/pilot_outreach_batch2.csv --force

  # Vista previa de envío WA (Green API)
  python scripts/run_outreach_pilot.py send output/pilot_outreach_batch2.csv --dry-run

  # Enviar (solo filas con teléfono, sent_at vacío, pilot_whatsapp relleno)
  python scripts/run_outreach_pilot.py send output/pilot_outreach_batch2.csv --confirm

  # KPI rápido desde columnas de seguimiento
  python scripts/run_outreach_pilot.py kpi output/pilot_outreach_batch2.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(message)s")

# Raíz del repo en sys.path para `import outreach_pilot`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import outreach_pilot as op  # noqa: E402
import utils  # noqa: E402


def _print_console(line: str, *, err: bool = False) -> None:
    """Evita UnicodeEncodeError en consolas Windows (cp1252)."""
    stream = sys.stderr if err else sys.stdout
    try:
        print(line, file=stream)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, errors="replace").decode(enc), file=stream)


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return [], []
    base = list(rows[0].keys())
    extra = op.pilot_extra_columns()
    fieldnames = base[:]
    for c in extra:
        if c not in fieldnames:
            fieldnames.append(c)
    return rows, fieldnames


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def cmd_generate(args: argparse.Namespace) -> int:
    path = Path(args.csv)
    if not path.is_file():
        print(f"No existe: {path}", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else path

    rows, fieldnames = _read_csv(path)
    if not rows:
        print("CSV vacío.", file=sys.stderr)
        return 3

    n = len(rows)
    errors = 0
    annotate = getattr(args, "annotate_notes", True)
    for row in rows:
        try:
            slot = int((row.get("pilot_slot") or "0").strip() or 0)
        except ValueError:
            slot = rows.index(row) + 1
        if slot <= 0:
            slot = rows.index(row) + 1

        angle_id, hook = op.assignment(slot, n)
        ch = op.planned_channel(row)

        row["angle_id"] = angle_id
        row["hook_variant"] = hook
        row["planned_channel"] = ch

        has_draft = bool((row.get("pilot_whatsapp") or "").strip())
        if has_draft and not args.force:
            continue

        try:
            gen = op.generate_messages(row, angle_id, hook, ch)
        except Exception as e:
            logging.error("Fila %s (%s): %s", slot, row.get("empresa", ""), e)
            errors += 1
            if args.fail_fast:
                return 4
            continue

        row.update(gen)
        if annotate:
            suffix = op.notes_suffix(angle_id, hook, ch)
            prev = (row.get("notes") or "").strip()
            row["notes"] = suffix if not prev else (prev if suffix in prev else f"{prev} | {suffix}")

    _write_csv(out_path, rows, fieldnames)
    print(f"Escrito: {out_path.resolve()} (errores LLM: {errors})")
    return 0 if errors == 0 else 5


def cmd_send(args: argparse.Namespace) -> int:
    path = Path(args.csv)
    if not path.is_file():
        print(f"No existe: {path}", file=sys.stderr)
        return 2

    rows, fieldnames = _read_csv(path)
    try:
        import config as cfg
        from wa_sender import send_text
    except ImportError as e:
        print(f"Import wa_sender: {e}", file=sys.stderr)
        return 2

    if not cfg.GREEN_API.get("token") or not cfg.GREEN_API.get("id_instance"):
        print("GREEN_API no configurada (token / id_instance).", file=sys.stderr)
        return 6

    # Incluir números ya enviados en corridas anteriores (evita re-enviar duplicados
    # si la primera fila del mismo teléfono ya tiene sent_at).
    seen_digits: set[str] = set()
    for row in rows:
        if not (row.get("sent_at") or "").strip():
            continue
        phone_raw = (row.get("telefono") or "").strip()
        norm = utils.whatsapp_digits_pe(phone_raw)
        if norm:
            seen_digits.add(norm)

    pending: list[tuple[dict[str, str], str, str, str, str]] = []
    duplicate_rows: list[dict[str, str]] = []

    for row in rows:
        if (row.get("sent_at") or "").strip():
            continue
        if (row.get("planned_channel") or "").strip() != "whatsapp":
            continue
        phone_raw = (row.get("telefono") or "").strip()
        msg = (row.get("pilot_whatsapp") or "").strip()
        if not phone_raw or not msg:
            continue

        norm = utils.whatsapp_digits_pe(phone_raw)
        if not norm:
            _print_console(
                f"[skip sin número] slot {row.get('pilot_slot')} {row.get('empresa', '')[:40]}",
                err=True,
            )
            continue

        empresa = (row.get("empresa") or "")[:50]
        slot = row.get("pilot_slot", "")

        if norm in seen_digits:
            duplicate_rows.append(row)
            _print_console(
                f"[skip duplicate] slot {slot} ({empresa[:45]}...) "
                f"mismo WhatsApp que fila anterior -> {norm}"
            )
            continue

        seen_digits.add(norm)
        pending.append((row, phone_raw, norm, msg, empresa))

    if args.dry_run:
        for _row, raw, norm, msg, empresa in pending:
            _print_console(f"[dry-run] -> {norm} ({raw}) ({empresa}): {msg[:120]}...")
        _print_console(
            f"Total a enviar (tras dedup): {len(pending)} | omitidos por duplicado: {len(duplicate_rows)}"
        )
        return 0

    if pending and not args.confirm:
        print("Usa --confirm para enviar de verdad (o --dry-run).", file=sys.stderr)
        return 7

    tag = "SKIP_WA duplicate_phone"
    for row in duplicate_rows:
        prev = (row.get("notes") or "").strip()
        if tag not in prev:
            row["notes"] = f"{prev} | {tag}" if prev else tag

    sent = 0
    for row, _raw, norm, msg, empresa in pending:
        result = send_text(norm, msg)
        if result.get("idMessage"):
            row["sent_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            row["channel"] = "whatsapp"
            sent += 1
            _print_console(f"Enviado OK: {empresa} -> {norm}")
        else:
            _print_console(f"Falló envío: {empresa} ({norm})", err=True)

    out_path = Path(args.out) if args.out else path
    _write_csv(out_path, rows, fieldnames)
    print(f"Total enviados: {sent} | filas marcadas duplicate: {len(duplicate_rows)}")
    return 0


def cmd_kpi(args: argparse.Namespace) -> int:
    path = Path(args.csv)
    if not path.is_file():
        print(f"No existe: {path}", file=sys.stderr)
        return 2

    rows, _ = _read_csv(path)
    if not rows:
        print("CSV vacío.")
        return 0

    total = len(rows)
    sent = sum(1 for r in rows if (r.get("sent_at") or "").strip())
    replies = sum(
        1
        for r in rows
        if (r.get("reply_status") or "").strip().lower() in ("replied", "reply", "si", "yes")
    )
    no_reply = sum(
        1 for r in rows if (r.get("reply_status") or "").strip().lower() in ("none", "no_reply", "no")
    )

    print(f"Filas: {total}")
    print(f"Con sent_at: {sent}")
    print(f"reply_status=replied: {replies}")
    print(f"reply_status=no_reply/none explícito: {no_reply}")
    if sent:
        print(f"Reply rate (sobre enviados): {100.0 * replies / sent:.1f}%")
    if total:
        print(f"Reply rate (sobre lista piloto): {100.0 * replies / total:.1f}%")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Piloto outreach: generar mensajes y/o enviar por WhatsApp.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Genera pilot_whatsapp / email con LLM")
    g.add_argument("csv", type=Path, help="CSV piloto")
    g.add_argument("--force", action="store_true", help="Regenera aunque ya exista pilot_whatsapp")
    g.add_argument("--fail-fast", action="store_true", dest="fail_fast", help="Aborta ante primer error LLM")
    g.add_argument(
        "--no-annotate-notes",
        action="store_true",
        help="No escribir angle/hook/planned en notes",
    )
    g.add_argument("--out", type=Path, default=None, help="Salida (default: sobrescribe el CSV de entrada)")
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("send", help="Envía WhatsApp vía Green API")
    s.add_argument("csv", type=Path)
    s.add_argument("--dry-run", action="store_true", help="Solo imprime destinos")
    s.add_argument("--confirm", action="store_true", help="Confirma envío real")
    s.add_argument("--out", type=Path, default=None, help="CSV actualizado post-envío (default: mismo archivo)")
    s.set_defaults(func=cmd_send)

    k = sub.add_parser("kpi", help="Resumen reply/sent desde el CSV")
    k.add_argument("csv", type=Path)
    k.set_defaults(func=cmd_kpi)

    args = ap.parse_args()
    if args.cmd == "generate":
        args.annotate_notes = not getattr(args, "no_annotate_notes", False)

    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
