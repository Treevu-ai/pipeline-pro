#!/usr/bin/env python3
"""
validator_summary.py — Resumen cuantitativo para sesión VALIDATOR desde CSV calificado.

Lee cualquier CSV generado por pipeline/sdr_agent con columnas estándar y muestra
distribuciones, cobertura de contacto y muestras ordenadas por score.

Ejemplos:
  python scripts/validator_summary.py
  python scripts/validator_summary.py output/mi_batch_calificados.csv
  python scripts/validator_summary.py output/leads.csv --json > resumen.json
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def _parse_score(raw: str) -> float | None:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None
    try:
        return float(str(raw).replace(",", "."))
    except ValueError:
        return None


def _boolish_non_empty(s: str | None) -> bool:
    return bool(s and str(s).strip())


def summarize(rows: list[dict[str, str]]) -> dict:
    n = len(rows)
    scores: list[float] = []
    errors = 0
    for r in rows:
        sc = _parse_score(r.get("lead_score", ""))
        if sc is not None:
            scores.append(sc)
        if _boolish_non_empty(r.get("qualify_error", "")):
            errors += 1

    def counter_col(key: str) -> dict[str, int]:
        c: Counter[str] = Counter()
        for r in rows:
            v = (r.get(key) or "").strip()
            c[v or "(vacío)"] += 1
        return dict(c.most_common())

    with_email = sum(
        1 for r in rows if _boolish_non_empty(r.get("email", ""))
    )

    ranked: list[tuple[float, str]] = []
    for r in rows:
        sc = _parse_score(r.get("lead_score", ""))
        if sc is None:
            continue
        ranked.append((sc, (r.get("empresa") or "(sin nombre)").strip()[:80]))

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[: min(5, len(ranked))]
    bottom = ranked[-min(5, len(ranked)) :] if ranked else []

    summary: dict = {
        "total_rows": n,
        "qualify_errors": errors,
        "contact_email_count": with_email,
        "contact_email_pct": round(100.0 * with_email / n, 1) if n else 0.0,
        "lead_score": {},
        "distributions": {
            "crm_stage": counter_col("crm_stage"),
            "fit_product": counter_col("fit_product"),
            "intent_timeline": counter_col("intent_timeline"),
            "decision_maker": counter_col("decision_maker"),
            "prioridad": counter_col("prioridad"),
        },
        "top_by_score": [{"empresa": e, "lead_score": s} for s, e in top],
        "bottom_by_score": [{"empresa": e, "lead_score": s} for s, e in bottom],
    }

    if scores:
        summary["lead_score"] = {
            "min": min(scores),
            "max": max(scores),
            "mean": round(statistics.mean(scores), 2),
            "median": round(statistics.median(scores), 2),
        }

    err_rows = [
        {"empresa": (r.get("empresa") or "").strip()[:120], "qualify_error": (r.get("qualify_error") or "")[:300]}
        for r in rows
        if _boolish_non_empty(r.get("qualify_error", ""))
    ]
    summary["error_samples"] = err_rows[:10]

    subs = []
    seen: set[str] = set()
    for r in rows:
        sub = (r.get("draft_subject") or "").strip()
        if sub and sub not in seen:
            seen.add(sub)
            subs.append(sub[:160])
        if len(subs) >= 5:
            break
    summary["sample_draft_subjects"] = subs

    return summary


def _print_human(summary: dict) -> None:
    print("VALIDATOR — Resumen\n" + "=" * 48)
    print(f"Filas totales      : {summary['total_rows']}")
    print(f"Errores calificación: {summary['qualify_errors']}")
    print(f"Con email (campo)  : {summary['contact_email_count']} ({summary['contact_email_pct']}%)")
    ls = summary.get("lead_score") or {}
    if ls:
        print(f"lead_score min/max : {ls['min']} / {ls['max']}")
        print(f"lead_score media   : {ls['mean']} (mediana {ls['median']})")
    print()

    for label, key in (
        ("crm_stage", "crm_stage"),
        ("fit_product", "fit_product"),
        ("intent_timeline", "intent_timeline"),
        ("prioridad", "prioridad"),
    ):
        block = summary["distributions"].get(key) or {}
        if not block or all(k == "(vacío)" for k in block):
            continue
        print(f"— {label} —")
        for k, v in block.items():
            print(f"  {k!r}: {v}")
        print()

    print("— Top por score —")
    for item in summary["top_by_score"]:
        print(f"  [{item['lead_score']:.0f}] {item['empresa']}")
    print()
    print("— Bottom por score —")
    for item in summary["bottom_by_score"]:
        print(f"  [{item['lead_score']:.0f}] {item['empresa']}")
    print()

    if summary.get("sample_draft_subjects"):
        print("— Muestra de asuntos (draft_subject) —")
        for s in summary["sample_draft_subjects"]:
            print(f"  • {s}")
        print()

    if summary.get("error_samples"):
        print("— Filas con qualify_error (máx. 10) —")
        for e in summary["error_samples"]:
            print(f"  • {e['empresa']}: {e['qualify_error'][:200]}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resumen VALIDATOR desde CSV de leads calificados.",
    )
    parser.add_argument(
        "csv",
        nargs="?",
        type=Path,
        default=Path("output/batch_validacion_20_icp_calificados.csv"),
        help="Ruta al CSV calificado (default: output/batch_validacion_20_icp_calificados.csv)",
    )
    parser.add_argument("--json", action="store_true", help="Salida JSON en stdout")
    args = parser.parse_args()

    path: Path = args.csv
    if not path.is_file():
        print(f"No existe el archivo: {path}", file=sys.stderr)
        return 2

    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("CSV vacío o sin filas de datos.", file=sys.stderr)
        return 3

    data = summarize(rows)
    data["source_file"] = str(path.resolve())

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_human(data)
        print(f"Fuente: {data['source_file']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
