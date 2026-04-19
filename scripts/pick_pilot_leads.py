#!/usr/bin/env python3
"""
pick_pilot_leads.py — Selecciona N leads de un CSV calificado para un piloto de outreach.

Prioridad (por defecto):
  1) columna `prioridad` = Alta (si existe)
  2) `lead_score` numérico descendente
  3) con `telefono` no vacío (WhatsApp) sobre sin teléfono

Añade columnas operativas vacías para que completes al contactar:
  pilot_slot, sent_at, channel, reply_status, reply_at, objection, notes

Ejemplos:
  python scripts/pick_pilot_leads.py output/batch_validacion_20_icp_calificados.csv -n 12
  python scripts/pick_pilot_leads.py output/leads.csv -n 10 --min-score 60 --out output/piloto_wa.csv
  python scripts/pick_pilot_leads.py output/leads.csv -n 8 --require-phone
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

PILOT_COLS = [
    "pilot_slot",
    # Generación piloto (`scripts/run_outreach_pilot.py generate`)
    "angle_id",
    "hook_variant",
    "planned_channel",
    "pilot_whatsapp",
    "pilot_email_subject",
    "pilot_email_body",
    "pilot_generated_at",
    # Seguimiento manual tras envío
    "sent_at",
    "channel",
    "reply_status",
    "reply_at",
    "objection",
    "notes",
]


def _score_val(row: dict[str, str]) -> float:
    raw = (row.get("lead_score") or "").strip()
    if not raw:
        return -1.0
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return -1.0


def _has_phone(row: dict[str, str]) -> bool:
    t = (row.get("telefono") or "").strip()
    digits = re.sub(r"\D", "", t)
    return len(digits) >= 8


def _prio_rank(row: dict[str, str]) -> int:
    p = (row.get("prioridad") or "").strip().lower()
    if p.startswith("alta"):
        return 0
    if p.startswith("media"):
        return 1
    if p.startswith("baja"):
        return 2
    return 3


def sort_key(row: dict[str, str], prefer_phone: bool) -> tuple:
    pr = _prio_rank(row)
    sc = _score_val(row)
    ph = 0 if (prefer_phone and _has_phone(row)) else 1
    # menor tupla = mejor: prioridad, -score, phone first
    return (pr, -sc, ph)


def main() -> int:
    ap = argparse.ArgumentParser(description="Selecciona leads para piloto de outreach.")
    ap.add_argument("csv", type=Path, help="CSV calificado (*_calificados.csv)")
    ap.add_argument("-n", "--count", type=int, default=12, help="Cuántos leads (default: 12)")
    ap.add_argument("--min-score", type=float, default=None, metavar="S", help="Filtrar lead_score >= S")
    ap.add_argument(
        "--require-phone",
        action="store_true",
        help="Solo filas con teléfono razonable",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Salida (default: output/pilot_outreach_<stem>.csv)",
    )
    args = ap.parse_args()

    if not args.csv.is_file():
        print(f"No existe: {args.csv}", file=sys.stderr)
        return 2

    with args.csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    filtered: list[dict[str, str]] = []
    for r in rows:
        if args.min_score is not None:
            sv = _score_val(r)
            if sv < args.min_score:
                continue
        if args.require_phone and not _has_phone(r):
            continue
        filtered.append({k: (v or "") for k, v in r.items()})

    filtered.sort(key=lambda r: sort_key(r, prefer_phone=True))

    picked = filtered[: args.count]

    if not picked:
        print(
            "No hay leads que cumplan filtros. Prueba sin --min-score o --require-phone.",
            file=sys.stderr,
        )
        return 3

    out_path = args.out
    if out_path is None:
        stem = args.csv.stem.replace("_calificados", "").replace(".", "_")
        out_path = Path("output") / f"pilot_outreach_{stem}.csv"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    base_fields = list(picked[0].keys())
    # evitar duplicar si ya existían columnas piloto
    extra = [c for c in PILOT_COLS if c not in base_fields]
    fieldnames = base_fields + extra

    for i, row in enumerate(picked, start=1):
        row["pilot_slot"] = str(i)
        for c in PILOT_COLS:
            if c != "pilot_slot" and c not in row:
                row[c] = ""

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in picked:
            w.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"Seleccionados: {len(picked)} / candidatos tras filtros: {len(filtered)} / total CSV: {len(rows)}")
    print(f"Escrito: {out_path.resolve()}")
    print("\nSiguiente: python scripts/run_outreach_pilot.py generate <este_csv>")
    print("luego seguimiento: sent_at, channel (whatsapp|email), reply_status, reply_at, objection, notes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
