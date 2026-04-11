"""
pdf_report.py — Generador de PDF demo para Pipeline_X.

Estructura:
  Pagina 1: Top 3 leads completos (empresa, tel, email, score, razon, mensaje, boton WA)
  Pagina 2: Leads 4-N con datos truncados (censurados, mensaje bloqueado)
  Pagina 3: CTA con planes en soles y URL de pago

Usage:
    from pdf_report import build_demo_pdf
    pdf_bytes = build_demo_pdf(target="Ferreterias en Los Olivos", leads=[...])
"""
from __future__ import annotations

import re as _re
import urllib.parse as _urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fpdf import FPDF

# ─── Fuente TTF Unicode (tildes, n~, etc.) ────────────────────────────────────
_FONTS_DIR   = Path(__file__).parent / "fonts"
_FONT_FAMILY = "DejaVu"

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
_WA_GREEN = (37, 211, 102)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_landline(phone: str) -> bool:
    """Fijos peruanos no son WhatsApp-able. Móviles empiezan con 9."""
    p = _re.sub(r"[\s\-\(\)\+]", "", phone or "")
    if p.startswith("51"):
        p = p[2:]
    return bool(p) and not p.startswith("9")


def _normalize_wa_phone(phone: str) -> str:
    """Retorna número internacional para wa.me, solo si es móvil válido."""
    digits = _re.sub(r"\D", "", phone or "")
    if len(digits) == 9 and digits.startswith("9"):
        return "51" + digits
    return ""


def _score_color(score) -> tuple[int, int, int]:
    s = int(score or 0)
    if s >= 70: return _GREEN
    if s >= 40: return _AMBER
    return _RED


def _censor(value: str, keep_last: int = 2) -> str:
    v = (value or "").strip()
    if not v:
        return "**********"
    return "*" * max(len(v) - keep_last, 4) + v[-keep_last:]


def _censor_email(email: str) -> str:
    e = (email or "").strip()
    if not e or "@" not in e:
        return "****@***.***"
    user, domain = e.split("@", 1)
    return user[:1] + "***@" + domain[:3] + "***"


# ─── Clase PDF ────────────────────────────────────────────────────────────────

class _PipelineXPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_font(_FONT_FAMILY, style="",   fname=str(_FONTS_DIR / "DejaVuSans.ttf"))
        self.add_font(_FONT_FAMILY, style="B",  fname=str(_FONTS_DIR / "DejaVuSans-Bold.ttf"))
        self.add_font(_FONT_FAMILY, style="I",  fname=str(_FONTS_DIR / "DejaVuSans-Oblique.ttf"))

    def footer(self):
        self.set_y(-11)
        self.set_font(_FONT_FAMILY, "I", 7)
        self.set_text_color(*_GRAY)
        self.cell(0, 5, "Pipeline_X  |  pipelinex.app  |  Reporte generado automáticamente", align="C")


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
    pdf.cell(0, 7, "Agente SDR con IA para pequeños negocios", ln=1)

    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "B", 10)
    pdf.set_text_color(*_WHITE)
    pdf.cell(0, 6, f"Reporte: {target[:65]}", ln=1)

    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_GREEN)
    fecha = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    pdf.cell(0, 5, f"{total} negocios analizados  |  {qualified} con alto potencial  |  {fecha}", ln=1)


def _score_bar(pdf: _PipelineXPDF, x: float, y: float, score, w: float = 28) -> None:
    s = int(score or 0)
    h = 3.5
    pdf.set_fill_color(*_LGRAY)
    pdf.rect(x, y, w, h, "F")
    color = _score_color(s)
    pdf.set_fill_color(*color)
    pdf.rect(x, y, w * s / 100, h, "F")
    pdf.set_xy(x + w + 2, y - 0.3)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*color)
    pdf.cell(14, 4, f"{s}/100", ln=0)


def _lead_card_full(pdf: _PipelineXPDF, lead: dict, index: int) -> None:
    """Tarjeta completa: tel, email, maps link, razón, mensaje, botón WA."""
    y0       = pdf.get_y()
    score    = int(lead.get("lead_score") or 0)
    msg      = (lead.get("draft_message") or "")[:200]
    why      = (lead.get("qualification_notes") or lead.get("fit_product") or lead.get("next_action") or "")[:130]
    phone    = (lead.get("telefono") or lead.get("telefono_web") or "").strip()
    email    = (lead.get("email") or lead.get("email_alternativo") or lead.get("email_guess") or "").strip()
    maps_url = (lead.get("maps_url") or "").strip()

    intl       = _normalize_wa_phone(phone)
    is_mobile  = bool(intl)
    is_landline = _is_landline(phone) if phone else False

    # URL del botón
    wa_url = mailto_url = ""
    if is_mobile and msg:
        wa_url = f"https://wa.me/{intl}?text={_urlparse.quote(msg[:500], safe='')}"
    elif email and msg:
        mailto_url = (
            f"mailto:{email}"
            f"?subject={_urlparse.quote('Propuesta comercial', safe='')}"
            f"&body={_urlparse.quote(msg[:500], safe='')}"
        )

    card_h = 68

    # Fondo + franja color
    pdf.set_fill_color(*_LIGHT)
    pdf.rect(10, y0, 190, card_h, "F")
    color = _score_color(score)
    pdf.set_fill_color(*color)
    pdf.rect(10, y0, 3, card_h, "F")

    # Badge número
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
    pdf.cell(115, 6, (lead.get("empresa") or "—")[:48], ln=0)

    # Score
    pdf.set_xy(155, y0 + 3)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_GRAY)
    pdf.cell(10, 4, "Score", ln=0)
    _score_bar(pdf, 165, y0 + 4, score, w=25)

    # Industria | Ciudad
    tag = "  |  ".join(filter(None, [(lead.get("industria") or "")[:30], (lead.get("ciudad") or "")[:20]]))
    pdf.set_xy(27, y0 + 10)
    pdf.set_font(_FONT_FAMILY, "I", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(160, 4, tag, ln=1)

    # Teléfono
    pdf.set_xy(27, y0 + 15)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(14, 4, "Tel:", ln=0)
    if not phone:
        pdf.set_font(_FONT_FAMILY, "I", 8)
        pdf.cell(80, 4, "No disponible", ln=1)
    elif is_landline:
        pdf.set_font(_FONT_FAMILY, "B", 9)
        pdf.set_text_color(*_AMBER)
        pdf.cell(55, 4, phone[:22], ln=0)
        pdf.set_font(_FONT_FAMILY, "I", 7)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 4, "  Fijo — no disponible en WA", ln=1)
    else:
        pdf.set_font(_FONT_FAMILY, "B", 9)
        pdf.set_text_color(*_BLACK)
        pdf.cell(80, 4, phone[:22], ln=1)

    # Email
    pdf.set_xy(27, y0 + 20)
    pdf.set_font(_FONT_FAMILY, "", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(14, 4, "Email:", ln=0)
    pdf.set_font(_FONT_FAMILY, "" if email else "I", 8)
    pdf.set_text_color(*(_BLACK if email else _GRAY))
    pdf.cell(100, 4, (email or "No disponible")[:50], ln=1)

    # Link Google Maps
    if maps_url:
        pdf.set_xy(27, y0 + 25)
        pdf.set_font(_FONT_FAMILY, "I", 7.5)
        pdf.set_text_color(*_DBLUE)
        pdf.cell(60, 4, "Ver en Google Maps >>", ln=0)
        pdf.link(27, y0 + 25, 60, 4, maps_url)

    # Disclaimer
    pdf.set_xy(100, y0 + 25)
    pdf.set_font(_FONT_FAMILY, "I", 6)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 4, "* Datos extraídos automáticamente. Verifica antes de contactar.", ln=1)

    # Razón
    if why:
        pdf.set_xy(27, y0 + 30)
        pdf.set_font(_FONT_FAMILY, "", 7.5)
        pdf.set_text_color(*_GRAY)
        pdf.cell(18, 4, "Razón:", ln=0)
        pdf.set_text_color(*_BLACK)
        pdf.multi_cell(155, 3.8, why, ln=1)

    # Mensaje sugerido
    if msg:
        msg_y = y0 + 39
        pdf.set_fill_color(*_LBLUE)
        pdf.rect(27, msg_y, 173, 14, "F")
        pdf.set_xy(29, msg_y + 1.5)
        pdf.set_font(_FONT_FAMILY, "B", 7)
        pdf.set_text_color(*_DBLUE)
        pdf.cell(0, 4, "Mensaje sugerido:", ln=1)
        pdf.set_x(29)
        pdf.set_font(_FONT_FAMILY, "I", 7.5)
        pdf.set_text_color(*_DBLUE)
        pdf.multi_cell(169, 3.8, f'"{msg}"', ln=1)

    # Botón acción
    action_url = wa_url or mailto_url
    if action_url:
        btn_y     = y0 + 55
        btn_color = _WA_GREEN if wa_url else _DBLUE
        btn_label = "Enviar mensaje por WhatsApp >>" if wa_url else "Enviar mensaje por Email >>"
        pdf.set_fill_color(*btn_color)
        pdf.rect(27, btn_y, 100, 8, "F")
        pdf.set_xy(27, btn_y + 1)
        pdf.set_font(_FONT_FAMILY, "B", 8)
        pdf.set_text_color(*_WHITE)
        pdf.cell(100, 6, btn_label, align="C", ln=0)
        pdf.link(27, btn_y, 100, 8, action_url)

    pdf.set_y(y0 + card_h + 4)


def _lead_card_locked(pdf: _PipelineXPDF, lead: dict, index: int) -> None:
    """Tarjeta bloqueada: tel y email censurados."""
    y0     = pdf.get_y()
    card_h = 25
    score  = int(lead.get("lead_score") or 0)

    pdf.set_fill_color(*_LIGHT)
    pdf.rect(10, y0, 190, card_h, "F")
    color = _score_color(score)
    pdf.set_fill_color(*color)
    pdf.rect(10, y0, 3, card_h, "F")

    # Badge
    pdf.set_fill_color(*color)
    pdf.rect(16, y0 + 4, 7, 7, "F")
    pdf.set_xy(16, y0 + 4)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_WHITE)
    pdf.cell(7, 7, str(index), align="C", ln=0)

    # Empresa
    pdf.set_xy(27, y0 + 3)
    pdf.set_font(_FONT_FAMILY, "B", 10)
    pdf.set_text_color(*_BLACK)
    pdf.cell(90, 5, (lead.get("empresa") or "—")[:42], ln=0)

    # Score
    pdf.set_xy(148, y0 + 3)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_GRAY)
    pdf.cell(10, 4, "Score", ln=0)
    _score_bar(pdf, 158, y0 + 4, score, w=22)

    # Tel censurado
    phone = (lead.get("telefono") or lead.get("telefono_web") or "").strip()
    pdf.set_xy(27, y0 + 10)
    pdf.set_font(_FONT_FAMILY, "", 7.5)
    pdf.set_text_color(*_GRAY)
    pdf.cell(12, 4, "Tel:", ln=0)
    pdf.set_font(_FONT_FAMILY, "B", 8)
    pdf.set_text_color(*_RED)
    pdf.cell(42, 4, _censor(phone), ln=0)

    # Email censurado
    email = (lead.get("email") or lead.get("email_alternativo") or "").strip()
    pdf.set_xy(83, y0 + 10)
    pdf.set_font(_FONT_FAMILY, "", 7.5)
    pdf.set_text_color(*_GRAY)
    pdf.cell(14, 4, "Email:", ln=0)
    pdf.set_font(_FONT_FAMILY, "B", 8)
    pdf.set_text_color(*_RED)
    pdf.cell(50, 4, _censor_email(email), ln=1)

    # Bloqueado
    pdf.set_fill_color(*_RED)
    pdf.rect(27, y0 + 16, 171, 6, "F")
    pdf.set_xy(27, y0 + 16)
    pdf.set_font(_FONT_FAMILY, "B", 7)
    pdf.set_text_color(*_WHITE)
    pdf.cell(171, 6, "[BLOQUEADO] Activa tu plan para ver datos completos y el mensaje personalizado", align="C", ln=1)

    pdf.set_y(y0 + card_h + 3)


# ─── Página 3: CTA ───────────────────────────────────────────────────────────

def _page_cta(pdf: _PipelineXPDF) -> None:
    pdf.add_page()

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

    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "B", 17)
    pdf.set_text_color(*_BLACK)
    pdf.cell(0, 9, "Accede a todos tus leads", align="C", ln=1)
    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "", 10)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 7, "Sin contrato  |  Sin permanencia  |  Cancela cuando quieras", align="C", ln=1)

    pdf.ln(8)

    plans = [
        ("Free",     "S/0",         "10 leads de prueba\nSin tarjeta",                    _GRAY,   False),
        ("Starter",  "S/149/mes",   "Reportes ilimitados\nPDF + WhatsApp + SUNAT",        _PURPLE, True),
        ("Pro",      "S/299/mes",   "Mayor volumen\nAPI REST + soporte prioritario",       _GREEN,  False),
        ("Reseller", "S/1,099/mes", "White-label\nMulti-cuenta + SLA garantizado",        _AMBER,  False),
    ]

    col_w = 44
    gap   = 3
    x0    = (210 - (col_w * 4 + gap * 3)) / 2
    y_card = pdf.get_y()

    for i, (name, price, desc, color, popular) in enumerate(plans):
        x = x0 + i * (col_w + gap)
        h = 52
        if popular:
            pdf.set_fill_color(237, 233, 254)
            pdf.rect(x - 1, y_card - 1, col_w + 2, h + 2, "F")
        pdf.set_fill_color(*(248, 245, 255) if popular else _LIGHT)
        pdf.rect(x, y_card, col_w, h, "F")
        pdf.set_fill_color(*color)
        pdf.rect(x, y_card, col_w, 4, "F")
        if popular:
            pdf.set_xy(x, y_card)
            pdf.set_font(_FONT_FAMILY, "B", 6)
            pdf.set_text_color(*_WHITE)
            pdf.cell(col_w, 4, "MÁS POPULAR", align="C", ln=0)
        pdf.set_xy(x + 3, y_card + 6)
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.set_text_color(*_BLACK)
        pdf.cell(col_w - 6, 6, name, ln=1)
        pdf.set_x(x + 3)
        pdf.set_font(_FONT_FAMILY, "B", 13)
        pdf.set_text_color(*color)
        pdf.cell(col_w - 6, 8, price, ln=1)
        pdf.set_x(x + 3)
        pdf.set_font(_FONT_FAMILY, "", 7)
        pdf.set_text_color(*_GRAY)
        pdf.multi_cell(col_w - 6, 4, desc, ln=1)

    pdf.set_y(y_card + 56)

    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "B", 15)
    pdf.set_text_color(*_PURPLE)
    pdf.cell(0, 10, "pipelinex.app/planes", align="C", ln=1)

    pdf.ln(6)

    g_y = pdf.get_y()
    pdf.set_fill_color(*_LGREEN)
    pdf.rect(30, g_y, 150, 20, "F")
    pdf.set_fill_color(*_GREEN)
    pdf.rect(30, g_y, 3, 20, "F")
    pdf.set_xy(36, g_y + 3)
    pdf.set_font(_FONT_FAMILY, "B", 9)
    pdf.set_text_color(*_GREEN)
    pdf.cell(0, 5, "Garantía de resultado", ln=1)
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
    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "I", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 5, "Este reporte de demostración expira en 48 horas.", align="C", ln=1)


# ─── Función principal ────────────────────────────────────────────────────────

def build_demo_pdf(target: str, leads: list[dict[str, Any]]) -> bytes:
    qualified = sorted(
        [l for l in leads if int(l.get("lead_score") or 0) >= 60],
        key=lambda x: int(x.get("lead_score") or 0),
        reverse=True,
    )
    top3 = qualified[:3]
    rest = qualified[3:] + [l for l in leads if int(l.get("lead_score") or 0) < 60]

    pdf = _PipelineXPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)

    # Página 1
    pdf.add_page()
    _header_bar(pdf, target, len(leads), len(qualified))
    pdf.set_y(34)

    if top3:
        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.set_text_color(*_PURPLE)
        pdf.cell(0, 7, f"Top {len(top3)} leads calificados — listos para contactar", ln=1)
        pdf.ln(1)
        for i, lead in enumerate(top3, 1):
            _lead_card_full(pdf, lead, i)
    else:
        pdf.set_xy(10, 50)
        pdf.set_font(_FONT_FAMILY, "I", 10)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 10, "No se encontraron leads con score >= 60 en esta búsqueda.", ln=1)
        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "", 9)
        pdf.cell(0, 7, "Prueba ampliar el rubro o la ciudad.", ln=1)

    # Página 2
    if rest:
        pdf.add_page()
        _header_bar(pdf, target, len(leads), len(qualified))
        pdf.set_y(34)
        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "B", 10)
        pdf.set_text_color(*_PURPLE)
        pdf.cell(0, 7, f"Hay {len(rest)} prospectos más en este reporte", ln=1)
        pdf.set_x(10)
        pdf.set_font(_FONT_FAMILY, "", 8)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 5, "Activa tu plan para acceder a datos completos y mensajes personalizados.", ln=1)
        pdf.ln(2)
        for i, lead in enumerate(rest[:9], len(top3) + 1):
            _lead_card_locked(pdf, lead, i)
        if len(rest) > 9:
            pdf.set_x(10)
            pdf.set_font(_FONT_FAMILY, "I", 8)
            pdf.set_text_color(*_GRAY)
            pdf.cell(0, 6, f"... y {len(rest) - 9} leads más disponibles en tu plan.", ln=1)

    # Página 3
    _page_cta(pdf)

    return bytes(pdf.output())


def build_full_pdf(target: str, leads: list[dict[str, Any]]) -> bytes:
    """
    PDF completo para suscriptores: todos los leads visibles, sin censura,
    sin página de CTA de upgrade.
    """
    qualified = sorted(
        [l for l in leads if int(l.get("lead_score") or 0) >= 60],
        key=lambda x: int(x.get("lead_score") or 0),
        reverse=True,
    )
    rest = [l for l in leads if int(l.get("lead_score") or 0) < 60]
    # Orden: calificados primero, luego el resto
    ordered = qualified + rest

    pdf = _PipelineXPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)

    pdf.add_page()
    _header_bar(pdf, target, len(leads), len(qualified))
    pdf.set_y(34)

    if not ordered:
        pdf.set_xy(10, 50)
        pdf.set_font(_FONT_FAMILY, "I", 10)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 10, "No se encontraron leads en esta búsqueda.", ln=1)
        return bytes(pdf.output())

    # Primera página: leads 1-N (paginación automática fpdf2)
    pdf.set_x(10)
    pdf.set_font(_FONT_FAMILY, "B", 10)
    pdf.set_text_color(*_PURPLE)
    label = f"{len(qualified)} leads calificados" if qualified else "Leads encontrados"
    if rest:
        label += f" · {len(rest)} prospectos adicionales"
    pdf.cell(0, 7, label, ln=1)
    pdf.ln(1)

    for i, lead in enumerate(ordered, 1):
        _lead_card_full(pdf, lead, i)

    return bytes(pdf.output())
