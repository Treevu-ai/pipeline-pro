"""
sdr_agent.py — Agente SDR para MIPYME en LatAm.

Lee un CSV de leads, califica cada uno con un LLM local (Ollama) y genera:
  - Etapa CRM, score, encaje, timeline, bloqueadores y notas
  - Borrador de mensaje (email o WhatsApp) listo para revisar y enviar

Uso:
    python sdr_agent.py leads.csv output/leads_calificados.csv
    python sdr_agent.py leads.csv output/leads_calificados.csv --max 10
    python sdr_agent.py leads.csv output/leads_calificados.csv --resume
    python sdr_agent.py leads.csv output/leads_calificados.csv --channel whatsapp
    python sdr_agent.py leads.csv output/leads_calificados.csv --report
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import logging
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config as cfg
import constants as const
import exceptions as exc
import models
import utils

# ─── Logging ─────────────────────────────────────────────────────────────────

def _setup_logging(log_dir: Path) -> logging.Logger:
    """
    Configura el logging para el agente SDR.

    Args:
        log_dir: Directorio donde guardar los logs.

    Returns:
        Logger configurado.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"sdr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt="%H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    logger = logging.getLogger("sdr_agent")
    logger.addHandler(fh)
    logger.info("Log guardado en: %s", log_file)
    return logger

log = logging.getLogger("sdr_agent")


# ─── Pre-scoring basado en reglas (sin LLM) ───────────────────────────────────

def pre_score(row: dict[str, Any]) -> int:
    """
    Calcula un score base con reglas deterministas antes de llamar al LLM.

    Args:
        row: Diccionario con datos del lead.

    Returns:
        Score base (0-65).
    """
    weights = cfg.ICP["score_weights"]
    score = weights["base"]

    # Industria
    industry = str(row.get(const.ColumnNames.INDUSTRIA, "")).strip()
    if any(t.lower() in industry.lower() for t in cfg.ICP["target_industries"]):
        score += weights["industry_match"]

    # Facturas pendientes
    try:
        invoices = int(float(str(row.get(const.ColumnNames.FACTURAS_PENDIENTES, 0))))
    except (ValueError, TypeError):
        invoices = 0

    if invoices >= cfg.ICP["high_value_invoices"]:
        score += weights["invoices_high"]
    elif invoices >= cfg.ICP["min_invoices_pending"]:
        score += weights["invoices_low"]

    # Email
    email = str(row.get(const.ColumnNames.EMAIL, "")).strip()
    if email and "@" in email and "." in email.split("@")[-1]:
        score += weights["has_email"]

    # Teléfono (soporta múltiples nombres de columna)
    phone = str(row.get(const.ColumnNames.TELEFONO, row.get("phone", ""))).strip()
    if phone and len(phone.replace(".", "").replace("+", "")) >= 7:
        score += weights["has_phone"]

    # Contacto (soporta múltiples nombres de columna)
    if str(row.get(const.ColumnNames.CONTACTO_NOMBRE, row.get("contact_name", ""))).strip():
        score += weights.get("has_contact", 0)

    # Cargo (soporta múltiples nombres de columna)
    if str(row.get(const.ColumnNames.CARGO, row.get("position", ""))).strip():
        score += weights.get("has_cargo", 0)

    # Palabras clave excluidas
    empresa = str(row.get(const.ColumnNames.EMPRESA, "")).lower()
    if any(kw.lower() in empresa for kw in cfg.ICP["excluded_keywords"]):
        score = max(0, score - 40)

    # Capear el pre-score en 65 para dejar margen al LLM
    return min(score, cfg.QUALIFICATION["max_pre_score"])


def should_skip(row: dict[str, Any]) -> bool:
    """
    Devuelve True si la fila ya fue calificada y se usa --resume.

    Args:
        row: Diccionario con datos del lead.

    Returns:
        True si el lead ya fue procesado, False en caso contrario.
    """
    stage = utils.normalize(str(row.get(const.ColumnNames.CRM_STAGE, "")))
    return bool(stage) and stage not in const.CRMStages.INITIAL


# ─── Llamada a Ollama ─────────────────────────────────────────────────────────

def _parse_json_loose(text: str) -> dict[str, Any]:
    """
    Parsea JSON de forma permisiva.

    Intenta extraer JSON de texto que puede tener contenido adicional.

    Args:
        text: Texto que contiene JSON.

    Returns:
        Diccionario parseado.

    Raises:
        LLMResponseError: Si no se puede parsear el JSON.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise exc.LLMResponseError("No se pudo parsear JSON de la respuesta del LLM", response=text)
        return json.loads(m.group(0))


def ollama_call(system: str, user: str) -> dict[str, Any]:
    """
    Llama a Ollama con reintentos y backoff exponencial.

    Args:
        system: Prompt del sistema.
        user: Prompt del usuario.

    Returns:
        Respuesta de Ollama como diccionario.

    Raises:
        OllamaError: Si hay error al comunicarse con Ollama.
    """
    body = {
        "model": cfg.OLLAMA["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": cfg.OLLAMA["temperature"]},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        cfg.OLLAMA["url"],
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_err: Exception | None = None
    for attempt in range(1, cfg.OLLAMA["retries"] + 1):
        try:
            with urllib.request.urlopen(req, timeout=cfg.OLLAMA["timeout_s"]) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return _parse_json_loose(payload["message"]["content"])
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
            last_err = e
            wait = cfg.OLLAMA["backoff_s"] * attempt
            log.warning("Intento %d/%d falló: %s — reintentando en %ds", attempt, cfg.OLLAMA["retries"], e, wait)
            time.sleep(wait)
    raise exc.OllamaError(
        f"Ollama no respondió después de {cfg.OLLAMA['retries']} intentos",
        model=cfg.OLLAMA["model"]
    ) from last_err


# ─── Calificación de una fila ─────────────────────────────────────────────────

def qualify_row(row: dict[str, Any], channel: str, base_score: int) -> dict[str, Any]:
    """
    Califica un lead individual usando el LLM.

    Args:
        row: Diccionario con datos del lead.
        channel: Canal de outreach (email, whatsapp, both).
        base_score: Score base calculado por reglas.

    Returns:
        Diccionario con datos de calificación.

    Raises:
        QualificationError: Si hay error en la calificación.
    """
    row_json = json.dumps(row, ensure_ascii=False, indent=2)

    channel_note = {
        "email": "Genera draft_subject (asunto) y draft_message (cuerpo del email, máximo 100 palabras).",
        "whatsapp": "draft_subject debe ser string vacío. draft_message es para WhatsApp: máximo 80 palabras, sin saludos formales, tono directo.",
        "both": "Genera draft_subject para email y draft_message que sirva tanto para email como WhatsApp.",
    }.get(channel, "")

    user_prompt = f"""Datos del lead (JSON):
{row_json}

Score base calculado por reglas: {base_score}/100. Ajusta lead_score partiendo de este valor.

{channel_note}

Devuelve EXACTAMENTE estas claves en el JSON:
- crm_stage: string ("Prospección" | "Calificado" | "En seguimiento" | "Descartado")
- lead_score: number 0-100
- fit_product: string ("si" | "no" | "dudoso")
- intent_timeline: string ("<30d" | "30-90d" | ">90d" | "desconocido")
- decision_maker: string ("si" | "no" | "desconocido")
- blocker: string (breve descripción del obstáculo, o "" si no hay)
- next_action: string (acción concreta y específica)
- qualification_notes: string (2-4 frases explicando la calificación)
- draft_subject: string (asunto del mensaje)
- draft_message: string (cuerpo del mensaje listo para enviar)
"""

    try:
        raw = ollama_call(cfg.PLAYBOOK, user_prompt)
    except exc.OllamaError as e:
        raise exc.QualificationError(f"Error al llamar a Ollama: {e}") from e

    result = {k: raw.get(k, "") for k in cfg.OUTPUT_KEYS if k != "qualify_error"}

    # Enforce límite de palabras en draft_message
    max_words = cfg.QUALIFICATION["word_limits"].get(channel, 100)
    draft = str(result.get("draft_message", ""))
    words = draft.split()
    if len(words) > max_words:
        result["draft_message"] = " ".join(words[:max_words]) + "…"
        log.warning("draft_message truncado a %d palabras (tenía %d)", max_words, len(words))

    # Coerción de lead_score a int
    try:
        result["lead_score"] = int(float(str(result["lead_score"])))
    except (ValueError, TypeError):
        result["lead_score"] = base_score
        log.warning("lead_score inválido del LLM; usando pre-score: %d", base_score)

    return result


# ─── Reporte HTML ─────────────────────────────────────────────────────────────

def generate_html_report(df: pd.DataFrame, output_path: Path) -> None:
    """
    Genera un reporte HTML con los resultados de la calificación.

    Args:
        df: DataFrame con los leads calificados.
        output_path: Ruta donde guardar el reporte.
    """
    total = len(df)
    qualified = (df[const.ColumnNames.CRM_STAGE] == const.CRMStages.QUALIFIED).sum()
    following = (df[const.ColumnNames.CRM_STAGE] == const.CRMStages.FOLLOW_UP).sum()
    prospecting = (df[const.ColumnNames.CRM_STAGE] == const.CRMStages.PROSPECCION).sum()
    discarded = (df[const.ColumnNames.CRM_STAGE] == const.CRMStages.DISCARDED).sum()
    errors = (df[const.ColumnNames.QUALIFY_ERROR].astype(str).str.strip() != "").sum()
    avg_score = df[const.ColumnNames.LEAD_SCORE].apply(pd.to_numeric, errors="coerce").mean()

    def esc(v: Any) -> str:
        return html_mod.escape(str(v) if v is not None else "")

    rows_html = ""
    for _, r in df.iterrows():
        stage_colors = {
            const.CRMStages.QUALIFIED: "#16a34a",
            const.CRMStages.FOLLOW_UP: "#d97706",
            const.CRMStages.PROSPECCION: "#2563eb",
            const.CRMStages.DISCARDED: "#dc2626",
        }
        stage = str(r.get(const.ColumnNames.CRM_STAGE, ""))
        color = stage_colors.get(stage, "#6b7280")
        score = r.get(const.ColumnNames.LEAD_SCORE, "")
        notes = esc(str(r.get(const.ColumnNames.QUALIFICATION_NOTES, "")).replace("\n", " ")[:120])
        rows_html += f"""
        <tr>
          <td>{esc(r.get(const.ColumnNames.EMPRESA, ''))}</td>
          <td>{esc(r.get(const.ColumnNames.INDUSTRIA, ''))}</td>
          <td><span style="background:{color};color:white;padding:2px 8px;border-radius:9999px;font-size:12px">{esc(stage)}</span></td>
          <td style="text-align:center;font-weight:bold">{esc(score)}</td>
          <td>{esc(r.get(const.ColumnNames.FIT_PRODUCT,''))}</td>
          <td>{esc(r.get(const.ColumnNames.INTENT_TIMELINE,''))}</td>
          <td>{esc(r.get(const.ColumnNames.NEXT_ACTION,''))}</td>
          <td style="font-size:12px;color:#4b5563">{notes}…</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Reporte SDR — {cfg.PRODUCT['name']}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f9fafb; color: #111827; }}
  .header {{ background: linear-gradient(135deg, #1e40af, #7c3aed); color: white; padding: 32px 40px; }}
  .header h1 {{ margin: 0 0 4px; font-size: 28px; }}
  .header p {{ margin: 0; opacity: 0.85; }}
  .stats {{ display: flex; gap: 16px; padding: 24px 40px; flex-wrap: wrap; }}
  .stat {{ background: white; border-radius: 12px; padding: 20px 28px; flex: 1; min-width: 140px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .stat .num {{ font-size: 36px; font-weight: 700; }}
  .stat .label {{ font-size: 13px; color: #6b7280; margin-top: 4px; }}
  .green {{ color: #16a34a; }}
  .amber {{ color: #d97706; }}
  .blue {{ color: #2563eb; }}
  .red {{ color: #dc2626; }}
  .table-wrap {{ padding: 0 40px 40px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th {{ background: #f3f4f6; padding: 12px 14px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: #374151; }}
  td {{ padding: 12px 14px; border-top: 1px solid #f3f4f6; font-size: 13px; vertical-align: top; }}
  tr:hover td {{ background: #fafafa; }}
  .footer {{ text-align: center; padding: 20px; color: #9ca3af; font-size: 12px; }}
</style>
</head>
<body>
<div class="header">
  <h1>{cfg.PRODUCT['name']} — Reporte de Calificación</h1>
  <p>Generado el {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} &nbsp;|&nbsp; {total} leads procesados</p>
</div>
<div class="stats">
  <div class="stat"><div class="num">{total}</div><div class="label">Total leads</div></div>
  <div class="stat"><div class="num green">{qualified}</div><div class="label">Calificados</div></div>
  <div class="stat"><div class="num amber">{following}</div><div class="label">En seguimiento</div></div>
  <div class="stat"><div class="num blue">{prospecting}</div><div class="label">Prospección</div></div>
  <div class="stat"><div class="num red">{discarded}</div><div class="label">Descartados</div></div>
  <div class="stat"><div class="num">{avg_score:.0f}</div><div class="label">Score promedio</div></div>
  {f'<div class="stat"><div class="num red">{errors}</div><div class="label">Errores</div></div>' if errors else ''}
</div>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Empresa</th><th>Industria</th><th>Etapa</th><th>Score</th>
        <th>Encaje</th><th>Timeline</th><th>Siguiente acción</th><th>Notas</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<div class="footer">{cfg.PRODUCT['name']} &mdash; Reporte generado automáticamente. Revisar antes de contactar.</div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    log.info("Reporte HTML: %s", output_path)


# ─── CLI y orquestación principal ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parsea argumentos de línea de comandos."""
    p = argparse.ArgumentParser(
        description="Agente SDR para MIPYME — califica leads y genera borradores de mensaje.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", help="CSV de entrada con los leads")
    p.add_argument("output", help="CSV de salida con calificación y borradores")
    p.add_argument("--max", type=int, default=None, metavar="N", help="Procesar solo los primeros N leads")
    p.add_argument("--resume", action="store_true", help="Saltar filas que ya tienen crm_stage definido")
    p.add_argument("--channel", choices=["email", "whatsapp", "both"], default=cfg.CHANNEL, help="Canal de outreach para los borradores")
    p.add_argument("--report", action="store_true", help="Generar reporte HTML además del CSV")
    p.add_argument("--delay", type=float, default=0.3, metavar="SEG", help="Pausa entre llamadas a Ollama (default: 0.3s)")
    p.add_argument("--workers", type=int, default=1, metavar="N", help="Llamadas paralelas a Ollama (default: 1). Aumentar con cuidado si tu GPU/CPU lo soporta.")
    p.add_argument("--dedup", action="store_true", help="Eliminar filas duplicadas por columna RUC antes de procesar")
    return p.parse_args()


def print_summary(df: pd.DataFrame) -> None:
    """
    Imprime un resumen de los resultados.

    Args:
        df: DataFrame con los leads calificados.
    """
    total = len(df)
    by_stage = df[const.ColumnNames.CRM_STAGE].value_counts().to_dict()
    errors = int(df[const.ColumnNames.QUALIFY_ERROR].fillna("").astype(str).str.strip().ne("").sum())
    avg_score = df[const.ColumnNames.LEAD_SCORE].apply(pd.to_numeric, errors="coerce").mean()

    print("\n" + "=" * 52)
    print(f"  RESUMEN -- {cfg.PRODUCT['name']}")
    print("=" * 52)
    print(f"  Total procesados : {total}")
    print(f"  Calificados      : {by_stage.get(const.CRMStages.QUALIFIED, 0)}")
    print(f"  En seguimiento   : {by_stage.get(const.CRMStages.FOLLOW_UP, 0)}")
    print(f"  Prospección      : {by_stage.get(const.CRMStages.PROSPECCION, 0)}")
    print(f"  Descartados      : {by_stage.get(const.CRMStages.DISCARDED, 0)}")
    print(f"  Score promedio   : {avg_score:.1f}/100")
    if errors:
        print(f"  Errores          : {errors}  ← revisar columna qualify_error")
    print("=" * 52 + "\n")


def main() -> None:
    """Función principal."""
    global log
    args = parse_args()
    src = Path(args.input)
    dst = Path(args.output)

    if not src.exists():
        logging.error("Archivo no encontrado: %s", src)
        sys.exit(exc.ExitCodes.FILE_NOT_FOUND)

    dst.parent.mkdir(parents=True, exist_ok=True)
    log = _setup_logging(dst.parent / "logs")

    try:
        df = pd.read_csv(src, dtype=str).fillna("")
    except Exception as e:
        log.error("Error al leer CSV: %s", e)
        sys.exit(exc.ExitCodes.IO_ERROR)

    if args.max:
        df = df.head(args.max)

    # ── Deduplicación por RUC ──────────────────────────────────────────────────
    if args.dedup:
        ruc_col = next((c for c in df.columns if "ruc" in c.lower()), None)
        if ruc_col:
            before = len(df)
            df = df.drop_duplicates(subset=[ruc_col], keep="first").reset_index(drop=True)
            removed = before - len(df)
            if removed:
                log.warning("Dedup: %d fila(s) eliminada(s) por %s duplicado", removed, ruc_col)
            else:
                log.info("Dedup: sin duplicados por %s", ruc_col)
        else:
            log.warning("--dedup: no se encontro columna 'ruc' en el CSV; se omite deduplicacion")

    total = len(df)
    log.info("Leads a procesar: %d | Modelo: %s | Canal: %s | Workers: %d",
             total, cfg.OLLAMA["model"], args.channel, args.workers)

    skipped = 0
    results: dict[int, dict[str, Any]] = {}
    write_lock = threading.Lock()

    def _process(idx: int, base: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """
        Califica un lead y devuelve (idx, merged).

        Args:
            idx: Índice del lead.
            base: Diccionario con datos del lead.

        Returns:
            Tupla con índice y datos mergeados.
        """
        if args.resume and should_skip(base):
            return idx, {**base, **{k: "" for k in cfg.OUTPUT_KEYS if k not in base}}

        base_score = pre_score(base)
        log.info("[%d/%d] %s | pre-score: %d", idx, total, base.get(const.ColumnNames.EMPRESA, "?"), base_score)
        try:
            result = qualify_row(base, args.channel, base_score)
            result[const.ColumnNames.QUALIFY_ERROR] = ""
        except Exception as e:
            log.error("[%d/%d] Error calificando: %s", idx, total, e)
            result = {k: "" for k in cfg.OUTPUT_KEYS if k != const.ColumnNames.QUALIFY_ERROR}
            result[const.ColumnNames.QUALIFY_ERROR] = str(e)

        time.sleep(args.delay)
        return idx, {**base, **result}

    # ── Escritura incremental con lock para concurrencia segura ───────────────
    try:
        with open(dst, "w", newline="", encoding="utf-8-sig") as f_out:
            writer: csv.DictWriter | None = None

            rows_indexed = [(i + 1, row.to_dict()) for i, (_, row) in enumerate(df.iterrows())]

            if args.workers == 1:
                # Secuencial — orden garantizado
                for idx, base in rows_indexed:
                    if args.resume and should_skip(base):
                        skipped += 1
                    ridx, merged = _process(idx, base)
                    results[ridx] = merged
                    if writer is None:
                        writer = csv.DictWriter(f_out, fieldnames=list(merged.keys()), extrasaction="ignore")
                        writer.writeheader()
                    writer.writerow(merged)
                    f_out.flush()
            else:
                # Paralelo — escritura tan pronto como cada future termina
                with ThreadPoolExecutor(max_workers=args.workers) as executor:
                    future_map = {executor.submit(_process, idx, base): idx
                                  for idx, base in rows_indexed}
                    for future in as_completed(future_map):
                        ridx, merged = future.result()
                        if args.resume and should_skip(df.iloc[ridx - 1].to_dict()):
                            skipped += 1
                        results[ridx] = merged
                        with write_lock:
                            if writer is None:
                                writer = csv.DictWriter(f_out, fieldnames=list(merged.keys()), extrasaction="ignore")
                                writer.writeheader()
                            writer.writerow(merged)
                            f_out.flush()
    except Exception as e:
        log.error("Error al procesar leads: %s", e)
        sys.exit(exc.ExitCodes.ERROR)

    log.info("CSV guardado (incremental): %s", dst)
    if skipped:
        log.info("Filas omitidas (--resume): %d", skipped)

    # Reconstruir DataFrame en orden original para el reporte y el resumen
    rows_out = [results[i] for i in sorted(results)]

    df_out = pd.DataFrame(rows_out)  # orden original preservado

    if args.report:
        report_path = dst.with_suffix(".html")
        generate_html_report(df_out, report_path)

    print_summary(df_out)


if __name__ == "__main__":
    main()