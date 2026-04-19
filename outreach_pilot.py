"""
outreach_pilot.py — Piloto de outreach con ángulos A1/A2/A3 y gancho A/B.

Usado por `scripts/run_outreach_pilot.py`. No envía mensajes por sí solo;
la generación usa `llm_client` con el playbook del proyecto.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import config as cfg
import llm_client

log = logging.getLogger("outreach_pilot")

# Descripciones alineadas a `tasks/planner-outreach-pilot.md`
ANGLE_SPECS: dict[str, str] = {
    "A1": (
        "Enfoque operativo: tiempo que el equipo pierde armando listas de pymes "
        "en Maps / Excel. Pipeline_X encuentra negocios con señales (reseñas, web, zona) "
        "y prioriza para que llamen solo a cuentas con fit. "
        "CTA sugerido (adaptar): ¿Te mando un ejemplo con pocas empresas de tu zona?"
    ),
    "A2": (
        "Oferta indirecta: los estudios viven de que sus MIPYME crezcan o renueven servicios. "
        "Herramienta para identificar pymes B2B donde el cliente del estudio podría vender más. "
        "CTA sugerido: ¿Te interesa ver un flujo pensado para estudios que asesoran MIPYME?"
    ),
    "A3": (
        "Credibilidad / datos: decisiones en frío sin contexto local. "
        "Lista calificada con datos verificables y notas por lead. "
        "CTA sugerido: ¿Te parece si te paso una captura del reporte sin compromiso?"
    ),
}

HOOK_SPECS: dict[str, str] = {
    "A": (
        "Primera frase del mensaje: abre con ahorro de tiempo / fricción operativa "
        "(listas, Maps, Excel, trabajo manual)."
    ),
    "B": (
        "Primera frase del mensaje: abre con crecimiento de oportunidades para sus clientes "
        "o posicionamiento del estudio (cadena indirecta, más cuentas facturables)."
    ),
}


def pilot_extra_columns() -> list[str]:
    """Columnas que añade el piloto además de las de seguimiento manual."""
    return [
        "angle_id",
        "hook_variant",
        "planned_channel",
        "pilot_whatsapp",
        "pilot_email_subject",
        "pilot_email_body",
        "pilot_generated_at",
    ]


def _has_phone(row: dict[str, str]) -> bool:
    t = (row.get("telefono") or "").strip()
    digits = re.sub(r"\D", "", t)
    return len(digits) >= 8


def planned_channel(row: dict[str, str]) -> str:
    """whatsapp si hay teléfono razonable; si no, email."""
    return "whatsapp" if _has_phone(row) else "email"


def angle_for_slot(slot: int, total_rows: int) -> str:
    """
    Reparte A1 → A2 → A3 en tres bandas según posición en el piloto (1-based slot).
    """
    if total_rows <= 0:
        return "A1"
    i = max(0, slot - 1)
    band = min(2, int(3 * i / total_rows))
    return ["A1", "A2", "A3"][band]


def hook_variant_for_slot(slot: int) -> str:
    """A/B alternado por fila (slot 1-based): impar → A, par → B."""
    return "A" if slot % 2 == 1 else "B"


def assignment(slot: int, total_rows: int) -> tuple[str, str]:
    return angle_for_slot(slot, total_rows), hook_variant_for_slot(slot)


def _row_subset(row: dict[str, str]) -> dict[str, Any]:
    """Campos útiles para personalizar sin mandar todo el CSV."""
    keys = (
        "empresa",
        "industria",
        "categoria_original",
        "ciudad",
        "direccion",
        "telefono",
        "email",
        "sitio_web",
        "rating",
        "num_resenas",
        "lead_score",
        "contacto_nombre",
        "cargo",
        "draft_message",
        "qualification_notes",
    )
    return {k: (row.get(k) or "").strip() for k in keys}


def build_generation_prompt(row: dict[str, str], angle_id: str, hook: str, channel: str) -> str:
    angle_id = angle_id if angle_id in ANGLE_SPECS else "A1"
    hook = hook if hook in HOOK_SPECS else "A"
    payload = _row_subset(row)
    payload["angle_id"] = angle_id
    payload["hook_variant"] = hook
    payload["planned_channel"] = channel

    return f"""Genera mensajes de primer contacto para un PILOTO de validación de Pipeline_X.

ÁNGULO ({angle_id}):
{ANGLE_SPECS[angle_id]}

VARIANTE DE GANCHO ({hook}) — obligatorio en la primera oración:
{HOOK_SPECS[hook]}

CANAL PLANIFICADO: {channel}
- Si whatsapp: campo "whatsapp" ≤80 palabras, tono cercano, sin asunto.
- Si email: "email_subject" ≤90 caracteres, "email_body" ≤100 palabras.
- Rellena siempre los tres campos JSON (whatsapp, email_subject, email_body): para el canal no usado puedes dejar texto corto o repetir adaptado.

Datos del negocio (JSON):
{json.dumps(payload, ensure_ascii=False, indent=2)}

REGLAS:
1. Dirige el mensaje al NEGOCIO (empresa), no inventes persona ni datos que no estén en el JSON.
2. Menciona al menos un dato específico del lead (nombre empresa, zona, rating, reseñas o rubro).
3. No prometas resultados garantizados ni menciones competidores.
4. Evita CTAs genéricos tipo "agendar 20 minutos para una demo"; usa cierre en forma de pregunta breve alineada al ángulo.
5. Español neutro latinoamericano.

Devuelve EXACTAMENTE un objeto JSON con las claves:
"whatsapp", "email_subject", "email_body"
(sin markdown, sin texto fuera del JSON).
"""


def generate_messages(row: dict[str, str], angle_id: str, hook: str, channel: str) -> dict[str, str]:
    """Llama al LLM y devuelve whatsapp / email_subject / email_body."""
    user = build_generation_prompt(row, angle_id, hook, channel)
    raw = llm_client.call(cfg.PLAYBOOK, user)

    wa = str(raw.get("whatsapp", "") or "").strip()
    sub = str(raw.get("email_subject", "") or "").strip()
    body = str(raw.get("email_body", "") or "").strip()
    return {
        "pilot_whatsapp": wa,
        "pilot_email_subject": sub,
        "pilot_email_body": body,
        "pilot_generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def notes_suffix(angle_id: str, hook: str, channel: str) -> str:
    return f"angle={angle_id}; hook={hook}; planned={channel}"
