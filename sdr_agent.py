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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
load_dotenv()

import config as cfg
import constants as const
import exceptions as exc
import llm_client
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

_DATE_FMTS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y")

def _months_active(date_str: str) -> int:
    """
    Devuelve los meses transcurridos desde la fecha de inscripción/apertura.
    Soporta los formatos más comunes en datos SUNAT y Google Maps.
    Retorna 0 si la fecha es inválida o ausente.
    """
    if not date_str or str(date_str).strip() in ("", "nan", "None"):
        return 0
    for fmt in _DATE_FMTS:
        try:
            dt = datetime.strptime(str(date_str).strip(), fmt)
            delta = relativedelta(datetime.now(), dt)
            return max(0, delta.years * 12 + delta.months)
        except ValueError:
            continue
    return 0


# ─── Pre-scoring basado en reglas (sin LLM) ───────────────────────────────────

def pre_score(row: dict[str, Any]) -> int:
    """
    Calcula un score base con reglas deterministas antes de llamar al LLM.
    Basado en señales de Google Maps: reseñas, rating, sitio web y distrito.

    Args:
        row: Diccionario con datos del lead.

    Returns:
        Score base (0-65).
    """
    weights = cfg.ICP["score_weights"]
    score = weights["base"]

    # ── Industria ────────────────────────────────────────────────────────────
    # Prioridad: CIIU (código oficial SUNAT) > texto libre de industria.
    # CIIU es 100% confiable; el texto de Google Maps puede ser ambiguo.
    ciiu = str(row.get(const.ColumnNames.CIIU, "")).strip()
    industry = str(row.get(const.ColumnNames.INDUSTRIA, "")).strip()
    industry_matched = False
    if ciiu:
        prefix = ciiu[:2]
        if prefix in const.CIIU_TO_INDUSTRY:
            matched_label = const.CIIU_TO_INDUSTRY[prefix]
            if matched_label in cfg.ICP["target_industries"]:
                score += weights["industry_match"]
                industry_matched = True
    if not industry_matched and industry:
        if any(t.lower() in industry.lower() for t in cfg.ICP["target_industries"]):
            score += weights["industry_match"]

    # Reseñas de Google Maps
    try:
        resenas = int(float(str(row.get(const.ColumnNames.NUM_RESENAS, 0) or 0)))
    except (ValueError, TypeError):
        resenas = 0

    if resenas >= cfg.ICP["reviews_high"]:
        score += weights["reviews_high"]
    elif resenas >= cfg.ICP["reviews_mid"]:
        score += weights["reviews_mid"]

    # Velocidad de reseñas (reseñas / mes de actividad)
    # Un negocio con 80 reseñas en 6 meses es mucho más activo que
    # uno con 80 reseñas en 10 años.
    fecha = str(row.get("fecha_inscripcion", row.get("fecha_inicio_actividades", ""))).strip()
    meses = _months_active(fecha)
    if meses > 0 and resenas > 0:
        velocity = resenas / meses
        if velocity >= cfg.ICP["review_velocity_high"]:
            score += weights.get("review_velocity_high", 0)
        elif velocity >= cfg.ICP["review_velocity_mid"]:
            score += weights.get("review_velocity_mid", 0)

    # Rating de Google Maps
    try:
        rating = float(str(row.get(const.ColumnNames.RATING, 0) or 0))
    except (ValueError, TypeError):
        rating = 0.0

    if rating >= cfg.ICP["rating_min_good"]:
        score += weights["rating_good"]

    # Sitio web
    sitio_web = str(row.get(const.ColumnNames.SITIO_WEB, "")).strip()
    if sitio_web and sitio_web not in ("", "nan", "None"):
        score += weights["has_website"]

    # Email
    email = str(row.get(const.ColumnNames.EMAIL, "")).strip()
    if email and "@" in email and "." in email.split("@")[-1]:
        score += weights["has_email"]

    # Teléfono
    phone = str(row.get(const.ColumnNames.TELEFONO, row.get("phone", ""))).strip()
    if phone and len(phone.replace(".", "").replace("+", "").replace(" ", "")) >= 7:
        score += weights["has_phone"]

    # ── Distrito (proxy de nivel socioeconómico) ─────────────────────────────
    # Construimos address_fields con todos los campos de dirección disponibles.
    # Ubigeo se resuelve ANTES del matching para que ciudades de los 15 mercados
    # contribuyan aunque no estén escritas en el campo ciudad del CSV.
    ubigeo = str(row.get(const.ColumnNames.UBIGEO, "")).strip()
    ciudad_ubigeo = ""
    if ubigeo and len(ubigeo) >= 2:
        ciudad_ubigeo = const.UBIGEO_DEPT_TO_CITY.get(ubigeo[:2], "").lower()

    address_fields = " ".join([
        str(row.get(const.ColumnNames.CIUDAD, "")),
        str(row.get(const.ColumnNames.DIRECCION, "")),
        str(row.get(const.ColumnNames.DIRECCION_FISCAL, "")),
        ciudad_ubigeo,
    ]).lower()
    if any(d in address_fields for d in cfg.ICP["distritos_high"]):
        score += weights["distrito_high"]
    elif any(d in address_fields for d in cfg.ICP["distritos_medium"]):
        score += weights["distrito_medium"]

    # ── Régimen tributario (proxy de tamaño/capacidad de pago) ───────────────
    # Régimen General > MYPE > RER > RUS.  Solo suma si hay dato oficial SUNAT.
    regimen = str(row.get(const.ColumnNames.REGIMEN_TRIBUTARIO, "")).strip().upper()
    if regimen:
        size = 0
        for key, val in const.REGIMEN_SIZE.items():
            if key in regimen:
                size = val
                break
        if size >= 4:
            score += weights.get("regimen_general", 0)
        elif size >= 3:
            score += weights.get("regimen_mype", 0)
        elif size >= 2:
            score += weights.get("regimen_rer", 0)
        # RUS no suma — microempresa, capacidad de pago insuficiente

    # ── Contacto ──────────────────────────────────────────────────────────────
    if str(row.get(const.ColumnNames.CONTACTO_NOMBRE, row.get("contact_name", ""))).strip():
        score += weights.get("has_contact", 0)

    # Cargo
    if str(row.get(const.ColumnNames.CARGO, row.get("position", ""))).strip():
        score += weights.get("has_cargo", 0)

    # Capear el pre-score en 65 para dejar margen al LLM
    return min(score, cfg.QUALIFICATION["max_pre_score"])


def should_auto_discard(row: dict[str, Any]) -> tuple[bool, str]:
    """
    Determina si un lead debe ser descartado automáticamente por reglas duras,
    SIN pasar por el LLM.  Devuelve (descartado, motivo).

    Las reglas duras son criterios binarios de exclusión — no degradaciones de
    score — y no tienen sentido enviarlas al LLM para "ajuste cualitativo".

    Args:
        row: Diccionario con datos del lead.

    Returns:
        Tupla (bool, str): True + motivo si debe descartarse; False + "" si no.
    """
    empresa = str(row.get(const.ColumnNames.EMPRESA, "")).lower()
    for kw in cfg.ICP["excluded_keywords"]:
        if kw.lower() in empresa:
            return True, f"keyword excluida: '{kw}'"

    estado_sunat = str(row.get("estado_sunat", "")).lower()
    if estado_sunat and any(s in estado_sunat for s in ("baja", "suspension", "suspensión")):
        return True, f"estado SUNAT irregular: '{estado_sunat}'"

    return False, ""


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
- positive_signals: array de strings, máximo 3 (señales positivas que subieron el score; solo cita datos presentes en el lead, no inventes)
- negative_signals: array de strings, máximo 3 (señales negativas que bajaron el score; ídem)
- qualification_notes: string (2-3 frases explicando el score en base a las señales anteriores)
- draft_subject: string (asunto del mensaje)
- draft_message: string (cuerpo del mensaje listo para enviar)
"""

    try:
        raw = llm_client.call(cfg.PLAYBOOK, user_prompt)
    except exc.LLMCallError as e:
        raise exc.QualificationError(f"Error al llamar al LLM: {e}") from e

    result = {k: raw.get(k, "") for k in cfg.OUTPUT_KEYS if k != "qualify_error"}

    # Normalizar positive_signals / negative_signals: array → pipe-separated string
    for sig_key in ("positive_signals", "negative_signals"):
        val = result.get(sig_key, [])
        if isinstance(val, list):
            result[sig_key] = " | ".join(str(s).strip() for s in val[:3] if s)
        elif not isinstance(val, str):
            result[sig_key] = str(val)

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

    # Clamping: el LLM no puede alejarse más de DRIFT_DOWN/DRIFT_UP del pre-score,
    # pero el score final siempre respeta floor/ceiling absolutos.
    # Esto evita que un lead con base baja sea injustamente capeado
    # cuando el LLM detecta señales cualitativas fuertes.
    raw_llm  = result["lead_score"]
    _floor   = cfg.QUALIFICATION.get("score_floor", 10)
    _ceiling = cfg.QUALIFICATION.get("score_ceiling", 95)
    _low     = max(_floor,   base_score - cfg.QUALIFICATION["score_drift_down"])
    _high    = min(_ceiling, base_score + cfg.QUALIFICATION["score_drift_up"])
    result["lead_score"] = max(_low, min(_high, raw_llm))
    if raw_llm != result["lead_score"]:
        log.warning(
            "lead_score clamped: LLM=%d → final=%d (base=%d, rango=[%d,%d])",
            raw_llm, result["lead_score"], base_score, _low, _high,
        )

    # Traducir intent_timeline a texto legible
    _timeline_map = {
        "<30d":       "Inmediato (< 30 días)",
        "30-90d":     "Corto plazo (1–3 meses)",
        ">90d":       "Largo plazo (> 3 meses)",
        "desconocido": "Sin definir",
    }
    result["intent_timeline"] = _timeline_map.get(
        str(result.get("intent_timeline", "desconocido")),
        str(result.get("intent_timeline", "Sin definir")),
    )

    # Calcular prioridad sintetizada
    result["prioridad"] = _calc_prioridad(
        score=result["lead_score"],
        decision_maker=str(result.get("decision_maker", "")),
        timeline=str(result.get("intent_timeline", "")),
        stage=str(result.get("crm_stage", "")),
    )

    return result


def qualify_batch(rows: list[dict], channel: str) -> list[dict]:
    """
    Califica TODOS los leads en una sola llamada al LLM.
    Mucho más rápido que qualify_row × N (1 call vs N calls).
    Retorna lista de resultados en el mismo orden que rows.
    Si el batch falla, hace fallback a qualify_row individual.
    """
    if not rows:
        return []

    channel_note = {
        "email":     "draft_subject: asunto. draft_message: cuerpo email ≤100 palabras.",
        "whatsapp":  "draft_subject: string vacío. draft_message: WhatsApp ≤80 palabras, tono directo.",
        "both":      "draft_subject: asunto email. draft_message: sirve para email y WhatsApp.",
    }.get(channel, "")

    # Construimos un mini-resumen por lead para reducir tokens
    leads_summary = []
    for i, r in enumerate(rows):
        leads_summary.append({
            "idx": i,
            "empresa": r.get("empresa", ""),
            "industria": r.get("industria", ""),
            "ciudad": r.get("ciudad", ""),
            "telefono": r.get("telefono", ""),
            "email": r.get("email", ""),
            "sitio_web": r.get("sitio_web", ""),
            "rating": r.get("rating", ""),
            "num_resenas": r.get("num_resenas", ""),
            "base_score": pre_score(r),
        })

    user_prompt = f"""Califica estos {len(rows)} leads para Pipeline_X (software de ventas B2B para MiPYMEs en Perú).
{channel_note}

Leads (JSON array):
{json.dumps(leads_summary, ensure_ascii=False)}

Devuelve un JSON array con exactamente {len(rows)} objetos, en el mismo orden (idx 0..{len(rows)-1}).
Cada objeto debe tener EXACTAMENTE estas claves:
- idx: number (igual al del input)
- crm_stage: "Prospección"|"Calificado"|"En seguimiento"|"Descartado"
- lead_score: number 0-100 (ajusta desde base_score, máximo ±25 puntos)
- fit_product: "si"|"no"|"dudoso"
- intent_timeline: "<30d"|"30-90d"|">90d"|"desconocido"
- decision_maker: "si"|"no"|"desconocido"
- blocker: string (obstáculo breve o "")
- next_action: string (acción concreta)
- positive_signals: array de strings, máx 3
- negative_signals: array de strings, máx 3
- qualification_notes: string (2-3 frases)
- draft_subject: string
- draft_message: string

Responde SOLO el JSON array, sin texto adicional."""

    try:
        raw = llm_client.call(cfg.PLAYBOOK, user_prompt)
        # llm_client.call devuelve dict; en batch esperamos lista en raw["_raw_list"] o similar
        # Pero call() parsea JSON → si el LLM devuelve array, raw será el primer elemento.
        # Necesitamos el texto raw. Usamos _call_groq directamente.
        import llm_client as _lc
        import groq as _groq_lib
        import os

        _groq = _groq_lib.Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
        resp = _groq.chat.completions.create(
            model=cfg.GROQ.get("model", "llama-3.1-8b-instant"),
            messages=[
                {"role": "system", "content": cfg.PLAYBOOK},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0,
            timeout=90,
        )
        text = resp.choices[0].message.content.strip()
        # Extraer JSON array del texto
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            raise ValueError("LLM no devolvió JSON array")
        batch_results = json.loads(m.group(0))

        # Mapear idx → resultado, aplicar post-procesado mínimo
        idx_map = {item["idx"]: item for item in batch_results}
        out = []
        for i, row in enumerate(rows):
            item = idx_map.get(i, {})
            base = pre_score(row)
            # Coerción score
            try:
                score = int(float(str(item.get("lead_score", base))))
            except (ValueError, TypeError):
                score = base
            _fl = cfg.QUALIFICATION.get("score_floor", 10)
            _cl = cfg.QUALIFICATION.get("score_ceiling", 95)
            score = max(
                max(_fl, base - cfg.QUALIFICATION["score_drift_down"]),
                min(min(_cl, base + cfg.QUALIFICATION["score_drift_up"]), score),
            )
            item["lead_score"] = score
            # Normalizar signals
            for sig in ("positive_signals", "negative_signals"):
                v = item.get(sig, [])
                item[sig] = " | ".join(str(s).strip() for s in v[:3] if s) if isinstance(v, list) else str(v)
            # Truncar draft_message
            max_w = cfg.QUALIFICATION["word_limits"].get(channel, 100)
            draft = str(item.get("draft_message", ""))
            wds = draft.split()
            if len(wds) > max_w:
                item["draft_message"] = " ".join(wds[:max_w]) + "…"
            # timeline legible
            _tmap = {"<30d": "Inmediato (< 30 días)", "30-90d": "Corto plazo (1–3 meses)",
                     ">90d": "Largo plazo (> 3 meses)", "desconocido": "Sin definir"}
            item["intent_timeline"] = _tmap.get(str(item.get("intent_timeline", "")), str(item.get("intent_timeline", "Sin definir")))
            item["prioridad"] = _calc_prioridad(score, str(item.get("decision_maker", "")),
                                                str(item.get("intent_timeline", "")), str(item.get("crm_stage", "")))
            item["qualify_error"] = ""
            out.append({**row, **item})
        log.info("qualify_batch: %d leads calificados en 1 sola llamada", len(out))
        return out

    except Exception as e:
        _FALLBACK_CAP = 5   # máx. llamadas individuales al LLM en fallback
        log.warning(
            "qualify_batch falló (%s) — fallback individual (cap=%d de %d)",
            e, min(_FALLBACK_CAP, len(rows)), len(rows),
        )
        results = []
        for i, row in enumerate(rows):
            base = pre_score(row)
            if i < _FALLBACK_CAP:
                try:
                    r = qualify_row(row, channel, base)
                    r["qualify_error"] = ""
                except Exception as err:
                    r = {k: "" for k in cfg.OUTPUT_KEYS if k != "qualify_error"}
                    r["qualify_error"] = str(err)
            else:
                # Más allá del cap: pre-score como aproximación, sin LLM
                r = {k: "" for k in cfg.OUTPUT_KEYS if k != "qualify_error"}
                r["lead_score"]  = base
                r["crm_stage"]   = "Prospección"
                r["prioridad"]   = "Media" if base >= 40 else "Baja"
                r["qualify_error"] = "batch_fallback_capped"
                log.debug("qualify_batch cap: lead %d usa pre-score=%d", i, base)
            results.append({**row, **r})
        return results


def _calc_prioridad(score: int, decision_maker: str, timeline: str, stage: str) -> str:
    """Alta / Media / Baja según score + decisor + timeline + etapa CRM."""
    if stage == "Descartado":
        return "Baja"
    is_decision_maker = decision_maker == "si"
    is_urgent = timeline in ("<30d", "Inmediato", "Inmediato (< 30 días)")
    if score >= 65 and (is_decision_maker or is_urgent):
        return "Alta"
    if score >= 65 or (score >= 45 and is_decision_maker):
        return "Media"
    if score >= 40:
        return "Media"
    return "Baja"


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
        delta = r.get("score_delta", "")
        delta_html = (
            f'<span style="font-size:10px;color:#6b7280;margin-left:4px">(Δ{delta})</span>'
            if delta != "" else ""
        )
        pos = esc(str(r.get("positive_signals", "")))
        neg = esc(str(r.get("negative_signals", "")))
        signals_html = ""
        if pos:
            signals_html += f'<div style="font-size:11px;color:#16a34a">▲ {pos}</div>'
        if neg:
            signals_html += f'<div style="font-size:11px;color:#dc2626">▼ {neg}</div>'
        rows_html += f"""
        <tr>
          <td>{esc(r.get(const.ColumnNames.EMPRESA, ''))}</td>
          <td>{esc(r.get(const.ColumnNames.INDUSTRIA, ''))}</td>
          <td><span style="background:{color};color:white;padding:2px 8px;border-radius:9999px;font-size:12px">{esc(stage)}</span></td>
          <td style="text-align:center;font-weight:bold">{esc(score)}{delta_html}</td>
          <td>{signals_html}</td>
          <td>{esc(r.get(const.ColumnNames.INTENT_TIMELINE,''))}</td>
          <td>{esc(r.get(const.ColumnNames.NEXT_ACTION,''))}</td>
          <td style="font-size:12px;color:#4b5563">{esc(str(r.get(const.ColumnNames.QUALIFICATION_NOTES, ''))[:140])}</td>
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
        <th>Empresa</th><th>Industria</th><th>Etapa</th><th>Score (Δ)</th>
        <th>Señales</th><th>Timeline</th><th>Siguiente acción</th><th>Notas</th>
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
        print(f"  Errores          : {errors}  (revisar columna qualify_error)")
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

        # ── Reglas duras: auto-descarte sin tocar el LLM ─────────────────────
        disc, motivo = should_auto_discard(base)
        if disc:
            log.info("[%d/%d] %s | AUTO-DESCARTADO: %s",
                     idx, total, base.get(const.ColumnNames.EMPRESA, "?"), motivo)
            result: dict[str, Any] = {k: "" for k in cfg.OUTPUT_KEYS}
            result.update({
                "crm_stage":            "Descartado",
                "lead_score":           0,
                "fit_product":          "no",
                "next_action":          "excluido por reglas",
                "qualification_notes":  f"Auto-descartado: {motivo}.",
                "qualify_error":        "",
                "auto_descartado":      True,
                "score_delta":          0,
            })
            return idx, {**base, **result}

        # ── Flujo normal ──────────────────────────────────────────────────────
        base_score = pre_score(base)
        log.info("[%d/%d] %s | pre-score: %d",
                 idx, total, base.get(const.ColumnNames.EMPRESA, "?"), base_score)
        try:
            result = qualify_row(base, args.channel, base_score)
            result[const.ColumnNames.QUALIFY_ERROR] = ""
        except Exception as e:
            log.error("[%d/%d] Error calificando: %s", idx, total, e)
            result = {k: "" for k in cfg.OUTPUT_KEYS if k != const.ColumnNames.QUALIFY_ERROR}
            result[const.ColumnNames.QUALIFY_ERROR] = str(e)
            result["auto_descartado"] = False
            result["score_delta"]     = 0
            time.sleep(args.delay)
            return idx, {**base, **result}

        result["auto_descartado"] = False
        result["score_delta"]     = abs(result.get("lead_score", base_score) - base_score)

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