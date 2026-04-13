"""
pdf_report.py — Generador de PDF demo para Pipeline_X.

Estructura:
  Pagina 1: Top 3 leads completos (empresa, telefono, score, por que califica, mensaje)
  Pagina 2: Leads 4-N con datos truncados (telefono censurado, mensaje bloqueado)
  Pagina 3: CTA con planes en soles y URL de pago

Usage:
    from pdf_report import build_demo_pdf
    pdf_bytes = build_demo_pdf(target="Ferreterias en Los Olivos", leads=[...])
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import os
from fpdf import FPDF

def _get_font_path(name: str) -> str | None:
    return None  # Railway no tiene fuentes locales, usar built-in

_FONT_FAMILY = "helvetica"  # Built-in, siempre disponible

# ─── Paleta ───────────────────────────────────────────────────────────────────

_DARK   = (10,  10,  26)
_PURPLE = (124, 58, 237)
_GREEN  = (34, 197, 94)
_AMBER  = (245, 158, 11)
_RED    = (200, 50,  50)
_GRAY   = (107, 114, 128)
_LGRAY  = (220, 220, 228)
_LIGHT  = (245, 247, 250)
_WHITE  = (255, 255, 255)
_BLACK  = (15,  23,  42)
_LBLUE  = (219, 234, 254)
_DBLUE  = (30,  64, 175)
_LGREEN = (220, 252, 231)


def _is_landline(phone: str) -> bool:
    """Detecta teléfonos fijos peruanos (no WhatsApp-able).
    Móviles peruanos empiezan con 9. Fijos con 01-08 u otros prefijos."""
    p = re.sub(r"[\s\-\(\)\+]", "", phone or "")
    if p.startswith("51"):   # quitar código de país
        p = p[2:]
    if not p:
        return False
    return not p.startswith("9")


def _score_color(score: int) -> tuple[int, int, int]:
    if score >= 70:
        return _GREEN
    if score >= 40:
        return _AMBER
    return _RED


def _censor_phone(phone: str) -> str:
    p = (phone or "").strip()
    if not p:
        return "**********"
    visible = p[-2:] if len(p) >= 2 else p
    return "*" * max(len(p) - 2, 6) + visible


def _wa_me_link(phone: str, message: str = "") -> str:
    """Genera link wa.me para abrir chat de WhatsApp con mensaje pre-escrito."""
    import urllib.parse
    p = re.sub(r"[\s\-\(\)\+]", "", phone or "")
    if not p:
        return ""
    # Asegurar código de país
    if not p.startswith("51") and len(p) <= 9:
        p = "51" + p
    url = f"https://wa.me/{p}"
    if message:
        url += f"?text={urllib.parse.quote(message)}"
    return url


# ─── Clase PDF ────────────────────────────────────────────────────────────────

class _PipelineXPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def footer(self):
        self.set_y(-11)
        self.set_font(_FONT_FAMILY, "I", 7)
        self.set_text_color(*_GRAY)
        self.cell(
            0, 5,
            "Pipeline_X  |  pipelinex.app  |  Reporte generado automaticamente",
            align="C",
        )


# ─── Helpers de dibujo ────────────────────────────────────────────────────────

def _header_bar(pdf: _PipelineXPDF, target: str, total: int, qualified: int) -> None:
    pdf.set_fill_color(*_DARK)
    pdf.rect(0, 0, 210, 30, "F")

    pdf.set_xy(10, 5)
    pdf.set_font(_FONT_FAMILY, "B", 14)
    pdf.set_text_color(*_PURPLE)
    pdf.cell(50, 7, "Pipeline_X", ln=0)

    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 7, "Agente SDR con IA para pequenos negocios", ln=1)

    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "B", 10)
    pdf.set_text_color(*_WHITE)
    label = f"Reporte: {target[:65]}"
    pdf.cell(0, 6, label, ln=1)

    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_GREEN)
    fecha = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    pdf.cell(
        0, 5,
        f"{total} negocios analizados  |  {qualified} con alto potencial  |  {fecha}",
        ln=1,
    )


def _score_bar(pdf: _PipelineXPDF, x: float, y: float, score: int, w: float = 28) -> None:
    h = 3.5
    pdf.set_fill_color(*_LGRAY)
    pdf.rect(x, y, w, h, "F")
    color = _score_color(score)
    pdf.set_fill_color(*color)
    pdf.rect(x, y, w * score / 100, h, "F")
    pdf.set_xy(x + w + 2, y - 0.3)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*color)
    pdf.cell(14, 4, f"{score}/100", ln=0)


def _lead_card_full(pdf: _PipelineXPDF, lead: dict, index: int) -> None:
    """Tarjeta completa: telefono, razon, mensaje."""
    msg      = (lead.get("draft_message") or "")[:200]
    why      = (lead.get("qualification_notes") or lead.get("fit_product") or lead.get("next_action") or "")[:130]
    maps_url = (lead.get("maps_url") or "").strip()
    phone    = (lead.get("telefono") or lead.get("telefono_web") or "").strip()

    # Calcular altura necesaria
    base_h = 28  # empresa + score + industria + telefono + maps link
    if why:
        base_h += 8
    if msg:
        base_h += 16
    card_h = base_h

    # Si no cabe en la página actual, nueva página
    if pdf.get_y() + card_h + 4 > pdf.h - 14:
        pdf.add_page()
        pdf.set_y(10)

    y0 = pdf.get_y()

    # Fondo
    pdf.set_fill_color(*_LIGHT)
    pdf.rect(10, y0, 190, card_h, "F")

    color = _score_color(lead.get("lead_score", 0))
    pdf.set_fill_color(*color)
    pdf.rect(10, y0, 3, card_h, "F")

    # Badge numero
    pdf.set_fill_color(*color)
    pdf.rect(16, y0 + 3, 8, 8, "F")
    pdf.set_xy(16, y0 + 3)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_WHITE)
    pdf.cell(8, 8, str(index), align="C", ln=0)

    # Empresa
    pdf.set_xy(27, y0 + 3)
    pdf.set_font(_FONT_FAMILY, "B", 11)
    pdf.set_text_color(*_BLACK)
    pdf.cell(115, 6, (lead.get("empresa") or "-")[:48], ln=0)

    # Score label + barra
    pdf.set_xy(155, y0 + 3)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_GRAY)
    pdf.cell(10, 4, "Score", ln=0)
    _score_bar(pdf, 165, y0 + 4, lead.get("lead_score", 0), w=25)

    # Industria + ciudad
    industria = lead.get("industria") or ""
    ciudad    = lead.get("ciudad") or ""
    tag       = "  |  ".join(filter(None, [industria[:30], ciudad[:20]]))
    pdf.set_xy(27, y0 + 10)
    pdf.set_font(_FONT_FAMILY, "I", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(160, 4, tag, ln=1)

    # Telefono + indicador fijo/movil + link WA
    pdf.set_xy(27, y0 + 15)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(12, 4, "Tel:", ln=0)
    if phone:
        if _is_landline(phone):
            pdf.set_font(_FONT_FAMILY, "B", 9)
            pdf.set_text_color(*_AMBER)
            pdf.cell(60, 4, phone[:22], ln=0)
            pdf.set_font(_FONT_FAMILY, "I", 7)
            pdf.set_text_color(*_GRAY)
            pdf.cell(0, 4, " Fijo - no disponible en WA", ln=1)
        else:
            wa_link = _wa_me_link(phone, msg)
            pdf.set_font(_FONT_FAMILY, "B", 9)
            pdf.set_text_color(*_DBLUE)
            pdf.cell(60, 4, phone[:22], link=wa_link, ln=0)
            pdf.set_font(_FONT_FAMILY, "I", 7)
            pdf.set_text_color(*_GREEN)
            pdf.cell(0, 4, "  Abrir chat en WhatsApp ->", link=wa_link, ln=1)
    else:
        pdf.set_font(_FONT_FAMILY, "I", 8)
        pdf.set_text_color(*_GRAY)
        pdf.cell(60, 4, "No disponible", ln=1)

    # Link Google Maps
    cur_y = y0 + 20
    if maps_url:
        pdf.set_xy(27, cur_y)
        pdf.set_font(_FONT_FAMILY, "I", 7.5)
        pdf.set_text_color(*_DBLUE)
        pdf.cell(0, 4, "Ver en Google Maps ->", link=maps_url, ln=1)
        cur_y += 5

    # Por que califica
    if why:
        pdf.set_xy(27, cur_y)
        pdf.set_font(_FONT_FAMILY, "", 7.5)
        pdf.set_text_color(*_GRAY)
        pdf.cell(18, 4, "Razon:", ln=0)
        pdf.set_text_color(*_BLACK)
        pdf.cell(155, 4, why[:100], ln=1)
        cur_y += 5

    # Mensaje sugerido
    if msg:
        msg_y = cur_y + 1
        pdf.set_fill_color(*_LBLUE)
        pdf.rect(27, msg_y, 173, 12, "F")
        pdf.set_xy(29, msg_y + 1)
        pdf.set_font(_FONT_FAMILY, "B", 7)
        pdf.set_text_color(*_DBLUE)
        pdf.cell(0, 4, "Mensaje sugerido:", ln=1)
        pdf.set_x(29)
        pdf.set_font(_FONT_FAMILY, "I", 7.5)
        pdf.set_text_color(*_DBLUE)
        pdf.cell(169, 4, f'"{msg[:120]}"', ln=1)

    pdf.set_y(y0 + card_h + 4)


def _lead_card_locked(pdf: _PipelineXPDF, lead: dict, index: int) -> None:
    """Tarjeta truncada: telefono censurado, mensaje bloqueado."""
    y0    = pdf.get_y()
    card_h = 19

    pdf.set_fill_color(*_LIGHT)
    pdf.rect(10, y0, 190, card_h, "F")

    color = _score_color(lead.get("lead_score", 0))
    pdf.set_fill_color(*color)
    pdf.rect(10, y0, 3, card_h, "F")

    # Badge
    pdf.set_fill_color(*color)
    pdf.rect(16, y0 + 5, 7, 7, "F")
    pdf.set_xy(16, y0 + 5)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_WHITE)
    pdf.cell(7, 7, str(index), align="C", ln=0)

    # Empresa
    pdf.set_xy(27, y0 + 4)
    pdf.set_font(_FONT_FAMILY, "B", 10)
    pdf.set_text_color(*_BLACK)
    pdf.cell(90, 5, (lead.get("empresa") or "-")[:42], ln=0)

    # Score barra
    pdf.set_xy(148, y0 + 4)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_GRAY)
    pdf.cell(10, 4, "Score", ln=0)
    _score_bar(pdf, 158, y0 + 5, lead.get("lead_score", 0), w=22)

    # Telefono censurado
    phone_raw = lead.get("telefono") or lead.get("telefono_web") or ""
    pdf.set_xy(27, y0 + 11)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(12, 4, "Tel:", ln=0)
    pdf.set_font(_FONT_FAMILY, "B", 8)
    pdf.set_text_color(*_RED)
    pdf.cell(45, 4, _censor_phone(phone_raw), ln=0)

    # Mensaje bloqueado
    pdf.set_fill_color(*_RED)
    pdf.rect(120, y0 + 11, 78, 5, "F")
    pdf.set_xy(122, y0 + 11)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_WHITE)
    pdf.cell(74, 5, "[BLOQUEADO] Activa tu plan para ver", align="C", ln=1)

    pdf.set_y(y0 + card_h + 3)


# ─── Pagina 3: CTA ────────────────────────────────────────────────────────────

def _page_cta(pdf: _PipelineXPDF) -> None:
    pdf.add_page()

    # Header
    pdf.set_fill_color(*_DARK)
    pdf.rect(0, 0, 210, 22, "F")
    pdf.set_xy(10, 6)
    pdf.set_font(_FONT_FAMILY, "B", 13)
    pdf.set_text_color(*_PURPLE)
    pdf.cell(55, 8, "Pipeline_X", ln=0)
    pdf.set_font(_FONT_FAMILY, "", 9)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 8, "Empieza a contactarlos hoy", ln=1)

    pdf.ln(10)

    # Titulo
    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "B", 17)
    pdf.set_text_color(*_BLACK)
    pdf.cell(0, 9, "Accede a todos tus leads", align="C", ln=1)
    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "", 10)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 7, "Sin contrato  |  Sin permanencia  |  Cancela cuando quieras", align="C", ln=1)

    pdf.ln(8)

    # ── Planes (4 columnas) ──────────────────────────────────────────────────
    plans = [
        ("Free",     "S/0",         "10 leads de prueba\nSin tarjeta",                     _GRAY,   False),
        ("Starter",  "S/129/mes",   "Reportes ilimitados\nPDF + WhatsApp + SUNAT",         _PURPLE, True),
        ("Pro",      "S/299/mes",   "Mayor volumen\nAPI REST + soporte prioritario",        _GREEN,  False),
        ("Reseller", "S/1,099/mes", "White-label\nMulti-cuenta + SLA garantizado",         _AMBER,  False),
    ]

    col_w  = 44
    gap    = 3
    x0     = (210 - (col_w * 4 + gap * 3)) / 2
    y_card = pdf.get_y()

    for i, (name, price, desc, color, popular) in enumerate(plans):
        x = x0 + i * (col_w + gap)
        h = 52

        if popular:
            # Sombra / highlight
            pdf.set_fill_color(237, 233, 254)
            pdf.rect(x - 1, y_card - 1, col_w + 2, h + 2, "F")

        bg = (248, 245, 255) if popular else _LIGHT
        pdf.set_fill_color(*bg)
        pdf.rect(x, y_card, col_w, h, "F")

        # Borde superior coloreado
        pdf.set_fill_color(*color)
        pdf.rect(x, y_card, col_w, 4, "F")

        if popular:
            pdf.set_xy(x, y_card)
            pdf.set_font(_FONT_FAMILY, "B", 6)
            pdf.set_text_color(*_WHITE)
            pdf.cell(col_w, 4, "MAS POPULAR", align="C", ln=0)

        # Nombre
        pdf.set_xy(x + 3, y_card + 6)
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.set_text_color(*_BLACK)
        pdf.cell(col_w - 6, 6, name, ln=1)

        # Precio
        pdf.set_x(x + 3)
        pdf.set_font(_FONT_FAMILY, "B", 13)
        pdf.set_text_color(*color)
        pdf.cell(col_w - 6, 8, price, ln=1)

        # Descripcion
        pdf.set_x(x + 3)
        pdf.set_font(_FONT_FAMILY, "", 7)
        pdf.set_text_color(*_GRAY)
        pdf.multi_cell(col_w - 6, 4, desc, ln=1)

    pdf.set_y(y_card + 56)

    # URL
    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "B", 15)
    pdf.set_text_color(*_PURPLE)
    pdf.cell(0, 10, "pipelinex.app/#pricing", align="C", ln=1)

    pdf.ln(6)

    # Garantia
    pdf.set_fill_color(*_LGREEN)
    g_y = pdf.get_y()
    pdf.rect(30, g_y, 150, 20, "F")
    pdf.set_fill_color(*_GREEN)
    pdf.rect(30, g_y, 3, 20, "F")

    pdf.set_xy(36, g_y + 3)
    pdf.set_font(_FONT_FAMILY, "B", 9)
    pdf.set_text_color(*_GREEN)
    pdf.cell(0, 5, "Garantia de resultado", ln=1)

    pdf.set_x(36)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_BLACK)
    pdf.multi_cell(
        138, 4,
        "Si tu primer reporte no incluye 5 leads con score >= 60, "
        "te generamos otro gratis. Sin preguntas.",
        ln=1,
    )

    pdf.ln(8)

    # Expiracion
    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "I", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 5, "Este reporte de demostracion expira en 48 horas.", align="C", ln=1)


# ─── Funcion principal ────────────────────────────────────────────────────────

def build_full_pdf(target: str, leads: list[dict[str, Any]]) -> bytes:
    """
    Genera el PDF completo (suscriptores pagos) - todos los leads sin censura.

    Args:
        target: Busqueda realizada
        leads:  Lista de dicts de leads

    Returns:
        Bytes del PDF generado.
    """
    import logging
    log = logging.getLogger("pdf_report")
    
    log.info("build_full_pdf: target=%s leads=%d", target, len(leads))
    if leads:
        scores = [l.get("lead_score", 0) for l in leads[:5]]
        log.info("build_full_pdf: first 5 scores=%s", scores)
    
    qualified = sorted(
        [l for l in leads if (l.get("lead_score") or 0) >= 60],
        key=lambda x: x.get("lead_score", 0),
        reverse=True,
    )
    all_leads = qualified + [l for l in leads if (l.get("lead_score") or 0) < 60]

    pdf = _PipelineXPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)

    pdf.add_page()
    _header_bar(pdf, target, len(leads), len(qualified))
    pdf.set_y(34)

    if all_leads:
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.set_text_color(*_PURPLE)
        pdf.cell(0, 7, f"{len(all_leads)} leads encontrados", ln=1)
        pdf.ln(2)
        for i, lead in enumerate(all_leads, 1):
            log.info("Rendering lead %d: empresa=%s score=%s", i, lead.get("empresa", "-"), lead.get("lead_score", 0))
            _lead_card_full(pdf, lead, i)
            if i % 3 == 0:
                pdf.ln(2)
    else:
        pdf.set_xy(10, 50)
        pdf.set_font(_FONT_FAMILY, "I", 10)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 10, "No se encontraron leads en esta busqueda.", ln=1)

    _page_cta(pdf)

    return bytes(pdf.output())


def build_demo_pdf(target: str, leads: list[dict[str, Any]]) -> bytes:
    """
    Genera el PDF demo de 3 paginas.

    Args:
        target: Busqueda realizada (ej: "Ferreterias en Los Olivos")
        leads:  Lista de dicts de leads (campos del modelo Lead)

    Returns:
        Bytes del PDF generado.
    """
    qualified = sorted(
        [l for l in leads if (l.get("lead_score") or 0) >= 60],
        key=lambda x: x.get("lead_score", 0),
        reverse=True,
    )
    top3 = qualified[:3]
    rest = qualified[3:] + [l for l in leads if (l.get("lead_score") or 0) < 60]

    pdf = _PipelineXPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)

    # ── Pagina 1: Top 3 completos ─────────────────────────────────────────────
    pdf.add_page()
    _header_bar(pdf, target, len(leads), len(qualified))
    pdf.set_y(34)

    if top3:
        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.set_text_color(*_PURPLE)
        pdf.cell(0, 7, f"Top {len(top3)} leads calificados - listos para contactar", ln=1)
        pdf.ln(1)
        for i, lead in enumerate(top3, 1):
            _lead_card_full(pdf, lead, i)
    else:
        pdf.set_xy(10, 50)
        pdf.set_font(_FONT_FAMILY, "I", 10)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 10, "No se encontraron leads con score >= 60 en esta busqueda.", ln=1)
        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "", 9)
        pdf.cell(0, 7, "Prueba ampliar el rubro o la ciudad.", ln=1)

    # ── Pagina 2: Leads truncados ─────────────────────────────────────────────
    if rest:
        pdf.add_page()
        _header_bar(pdf, target, len(leads), len(qualified))
        pdf.set_y(34)

        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.set_text_color(*_PURPLE)
        pdf.cell(0, 7, f"Hay {len(rest)} prospectos mas en este reporte", ln=1)

        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "", 8)
        pdf.set_text_color(*_GRAY)
        pdf.cell(
            0, 5,
            "Activa tu plan para acceder a datos completos y mensajes personalizados.",
            ln=1,
        )
        pdf.ln(2)

        for i, lead in enumerate(rest[:9], len(top3) + 1):
            _lead_card_locked(pdf, lead, i)

        if len(rest) > 9:
            pdf.set_x(10)
            pdf.set_font(_FONT_FAMILY, "I", 8)
            pdf.set_text_color(*_GRAY)
            pdf.cell(0, 6, f"... y {len(rest) - 9} leads mas disponibles en tu plan.", ln=1)

    # ── Pagina 3: CTA ─────────────────────────────────────────────────────────
    _page_cta(pdf)

    return bytes(pdf.output())
