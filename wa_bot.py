"""
wa_bot.py — Bot de 5 respuestas automáticas para WhatsApp (Pipeline_X).

Flujo:
  Cualquier mensaje  → [R1] Menú interactivo con lista de 4 opciones
  Opción 1           → [R2] ¿Qué es Pipeline_X? + botones CTA
  Opción 2           → [R3] Planes y precios + botones CTA
  Opción 3           → [R4] Captura de email para demo gratuita
  Opción 4           → [R5] Link a Telegram + correo de soporte
  Email válido       → Guarda lead, notifica admin en Telegram

Tipos de mensaje devueltos (list[dict]):
  {"type": "text",    "text": str}
  {"type": "buttons", "body": str, "buttons": list[{"id", "text"}], "header": str, "footer": str}
  {"type": "list",    "body": str, "button_text": str, "sections": list[...], "footer": str}

Persistencia de sesiones: output/.wa_sessions.json
Leads capturados:        output/.demo_requests.json  (mismo store que API + Telegram)
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("wa_bot")

# ─── Lock por número — evita race condition con mensajes simultáneos ──────────
_phone_locks: dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()

def _get_lock(phone: str) -> threading.Lock:
    with _locks_mutex:
        if phone not in _phone_locks:
            _phone_locks[phone] = threading.Lock()
        return _phone_locks[phone]

# ─── Stores ──────────────────────────────────────────────────────────────────

_SESSIONS_STORE = Path("output/.wa_sessions.json")
_DEMO_STORE     = Path("output/.demo_requests.json")

# ─── Estados de conversación ─────────────────────────────────────────────────
# idle             → nunca ha escrito (o reiniciado)
# menu_shown       → se mostró el menú, esperando opción 1-4
# collecting_email → eligió demo (opción 3), esperando email
# done             → email capturado, conversación cerrada

# ─── Helpers para construir mensajes interactivos ─────────────────────────────

def _t(text: str) -> dict:
    """Mensaje de texto simple."""
    return {"type": "text", "text": text}


def _b(body: str, buttons: list[tuple[str, str]], header: str = "", footer: str = "") -> dict:
    """
    Mensaje con hasta 3 botones.
    buttons: lista de (id, display_text)
    """
    return {
        "type":    "buttons",
        "body":    body,
        "buttons": [{"id": bid, "text": btxt} for bid, btxt in buttons],
        "header":  header,
        "footer":  footer,
    }


def _l(body: str, rows: list[tuple[str, str, str]], footer: str = "") -> dict:
    """
    Mensaje con lista de opciones seleccionables.
    rows: lista de (id, title, description)
    """
    return {
        "type":        "list",
        "body":        body,
        "button_text": "Ver opciones",
        "sections":    [{
            "title": "Elige una opción",
            "rows":  [
                {"id": rid, "title": rtitle, "description": rdesc}
                for rid, rtitle, rdesc in rows
            ],
        }],
        "footer": footer,
    }


# ─── Textos base ──────────────────────────────────────────────────────────────

_FOOTER = "Pipeline_X — Prospección B2B para MIPYME"

_MENU_BODY = (
    "👋 Hola, soy el asistente de *Pipeline_X*.\n\n"
    "Encuentra empresas reales en Google Maps, califícalas con IA "
    "y genera mensajes de prospección listos para enviar.\n\n"
    "¿Qué quieres saber?"
)

_MENU_ROWS: list[tuple[str, str, str]] = [
    ("1", "¿Qué es Pipeline_X?",   "Cómo funciona la plataforma"),
    ("2", "Planes y precios 💰",    "Desde $0 hasta plan Reseller"),
    ("3", "Demo gratis 🚀",         "10 leads reales de tu industria"),
    ("4", "Hablar con alguien 💬",  "Telegram, email o llamada"),
]

_R2_BODY = """\
🤖 *Pipeline_X* es una plataforma de prospección B2B para MIPYME en Latinoamérica.

En 3 pasos:
1️⃣ Escribes qué tipo de empresa buscas ("Ferreterías en Lima")
2️⃣ Pipeline_X las encuentra en Google Maps y las califica con IA (score 0–100)
3️⃣ Recibes un CSV con leads + mensajes de outreach listos para copiar

Sin Excel manual. Sin LinkedIn Ads. Sin contratar SDRs."""

_R3_BODY = """\
💰 *Planes de Pipeline_X*

• *Free* — $0 | 10 leads gratis, sin tarjeta
• *Solo* — $19/mes | 30 leads (freelancers)
• *Starter* — $39/mes | 200 leads ⭐ más popular
• *Pro* — $79/mes | 500 leads + acceso API
• *Reseller* — $299/mes | 1.000 leads + white-label (agencias)

🎁 *Precio fundador:* $29/mes para los primeros 20 clientes (mismo acceso que Starter)."""

_R4_SOLICITUD = """\
🚀 ¡Perfecto! Te genero *10 leads reales* de tu industria, gratis y ahora mismo.

Para enviarte el reporte, necesito tu email:

✉️ *¿Cuál es tu correo electrónico?*"""

_R4_CONFIRMACION = """\
✅ ¡Listo! Registré tu solicitud.

Te contactamos en menos de 2 horas en horario hábil para enviarte los 10 leads de demo.

👉 Mientras, explora el bot de Telegram: t.me/Pipeline_X_bot"""

_R5_BODY = """\
💬 *¿Prefieres hablar con alguien?*

🤖 *Bot de Telegram:* t.me/Pipeline_X_bot
   (respuesta inmediata, disponible 24/7)

📧 *Email:* contacto@pipelinex.io

📲 Estás en el WhatsApp correcto — si prefieres que te llamemos, escribe tu número y te contactamos."""


# ─── Funciones que devuelven list[dict] para cada respuesta ───────────────────

def _r1_menu() -> list[dict]:
    return [_l(_MENU_BODY, _MENU_ROWS, footer=_FOOTER)]


def _r2_que_es() -> list[dict]:
    return [
        _t(_R2_BODY),
        _b(
            "¿Te interesa probarlo?",
            [("3", "Demo gratis 🚀"), ("2", "Ver precios 💰")],
            footer=_FOOTER,
        ),
    ]


def _r3_precios() -> list[dict]:
    return [
        _t(_R3_BODY),
        _b(
            "¿Quieres ver cómo funciona antes de decidir?",
            [("3", "Demo gratis 🚀"), ("4", "Hablar con alguien 💬")],
            footer=_FOOTER,
        ),
    ]


def _r4_solicitud() -> list[dict]:
    return [_t(_R4_SOLICITUD)]


def _r4_confirmacion() -> list[dict]:
    return [_t(_R4_CONFIRMACION)]


def _r5_contacto() -> list[dict]:
    return [_t(_R5_BODY)]


def _r_no_entendido() -> list[dict]:
    return [
        _t("No entendí esa opción 🤔"),
        _l(_MENU_BODY, _MENU_ROWS, footer=_FOOTER),
    ]


def _r_ya_registrado() -> list[dict]:
    return [
        _b(
            "Tu solicitud ya está registrada ✅\n\n¿Necesitas algo más?",
            [("2", "Ver precios 💰"), ("4", "Hablar con alguien 💬")],
            footer=_FOOTER,
        )
    ]


# ─── Detección de intención ───────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

_KEYWORDS: dict[str, list[str]] = {
    "1": ["1", "que es", "qué es", "info", "información", "informacion", "como funciona", "cómo funciona"],
    "2": ["2", "precio", "precios", "costo", "costos", "plan", "planes", "cuanto", "cuánto", "vale", "tarifa"],
    "3": ["3", "demo", "prueba", "gratis", "probar", "leads", "ver"],
    "4": ["4", "hablar", "contacto", "humano", "persona", "soporte", "ayuda", "whatsapp", "llamar"],
}

def _detect_option(text: str) -> str | None:
    """Detecta la opción elegida por el usuario (1-4) o None."""
    t = text.strip().lower()
    for option, keywords in _KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return option
    return None


def _extract_email(text: str) -> str | None:
    """Extrae el primer email válido del texto, o None."""
    m = _EMAIL_RE.search(text.strip())
    return m.group(0).lower() if m else None


# ─── Sesiones ─────────────────────────────────────────────────────────────────

def _load_sessions() -> dict[str, Any]:
    try:
        if _SESSIONS_STORE.exists():
            return json.loads(_SESSIONS_STORE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_sessions(sessions: dict[str, Any]) -> None:
    _SESSIONS_STORE.parent.mkdir(parents=True, exist_ok=True)
    _SESSIONS_STORE.write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _get_session(phone: str) -> dict:
    return _load_sessions().get(phone, {"state": "idle"})


def _set_session(phone: str, session: dict) -> None:
    sessions = _load_sessions()
    sessions[phone] = session
    _save_sessions(sessions)


# ─── Persistencia de leads ────────────────────────────────────────────────────

def _save_lead(phone: str, email: str) -> bool:
    """
    Guarda el lead en el store compartido con la API y el bot de Telegram.
    Deduplica por email. Devuelve True si se guardó, False si ya existía.
    """
    try:
        records = json.loads(_DEMO_STORE.read_text(encoding="utf-8")) if _DEMO_STORE.exists() else []
    except Exception:
        records = []

    if any(r.get("email", "").lower() == email.lower() for r in records):
        return False   # ya registrado

    records.append({
        "nombre":    "",
        "empresa":   "",
        "ruc":       "",
        "email":     email,
        "industria": "",
        "ciudad":    "",
        "ip":        f"whatsapp:{phone}",
        "ts":        datetime.now(timezone.utc).isoformat(),
        "status":    "demo_whatsapp",
    })
    _DEMO_STORE.parent.mkdir(parents=True, exist_ok=True)
    _DEMO_STORE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Lead WA guardado: phone=%s email=%s", phone, email)
    return True


# ─── Notificación al admin vía Telegram ──────────────────────────────────────

def _notify_admin_telegram(phone: str, email: str) -> None:
    """
    Envía un mensaje al ADMIN_CHAT_ID usando la Bot API de Telegram directamente
    (sin necesidad de tener el objeto Application disponible en este contexto síncrono).
    """
    import httpx

    token    = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_id = os.environ.get("ADMIN_CHAT_ID", "")
    if not token or not admin_id:
        log.warning("TELEGRAM_BOT_TOKEN o ADMIN_CHAT_ID no configurados — notificación omitida")
        return

    text = (
        f"📲 *Nuevo lead WhatsApp*\n\n"
        f"Email : `{email}`\n"
        f"Tel   : `{phone}`"
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": admin_id, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
        log.info("Admin notificado en Telegram: %s", email)
    except Exception as exc:
        log.warning("No se pudo notificar al admin: %s", exc)


# ─── Motor principal ──────────────────────────────────────────────────────────

def handle_message(phone: str, text: str) -> list[dict]:
    """
    Procesa un mensaje entrante de WhatsApp y devuelve la lista de mensajes
    a enviar (cada uno es un dict con "type" y campos adicionales).

    Serializa mensajes del mismo número con un lock para evitar race conditions.

    Args:
        phone: Número del remitente sin '+' ni '@c.us' (ej: "51987654321").
        text:  Texto del mensaje recibido.

    Returns:
        Lista de dicts de mensajes. Tipos posibles:
          {"type": "text",    "text": str}
          {"type": "buttons", "body": str, "buttons": [...], "header": str, "footer": str}
          {"type": "list",    "body": str, "button_text": str, "sections": [...], "footer": str}
    """
    with _get_lock(phone):
        return _handle_message_locked(phone, text)


def _handle_message_locked(phone: str, text: str) -> list[dict]:
    """Lógica real — llamar solo desde handle_message (ya con lock)."""
    session = _get_session(phone)
    state   = session.get("state", "idle")
    text    = (text or "").strip()

    log.info("WA msg: phone=%s state=%s text=%r", phone, state, text[:80])

    # ── Estado: esperando email ───────────────────────────────────────────────
    if state == "collecting_email":
        email = _extract_email(text)
        if not email:
            return [_t(
                "No detecté un email válido en tu mensaje.\n\n"
                "Por favor escríbelo así: *tunombre@empresa.com*"
            )]

        _save_lead(phone, email)
        _notify_admin_telegram(phone, email)
        _set_session(phone, {"state": "done", "email": email})
        return _r4_confirmacion()

    # ── Ya terminó el flujo ───────────────────────────────────────────────────
    if state == "done":
        option = _detect_option(text)
        if option:
            return _handle_option(phone, option)
        return _r_ya_registrado()

    # ── Primer mensaje o menú ─────────────────────────────────────────────────
    option = _detect_option(text)

    if option:
        return _handle_option(phone, option)

    # No se detectó opción → mostrar bienvenida/menú interactivo
    _set_session(phone, {"state": "menu_shown"})
    return _r1_menu()


def _handle_option(phone: str, option: str) -> list[dict]:
    """Maneja la opción elegida y actualiza la sesión."""
    if option == "1":
        _set_session(phone, {"state": "menu_shown"})
        return _r2_que_es()

    if option == "2":
        _set_session(phone, {"state": "menu_shown"})
        return _r3_precios()

    if option == "3":
        _set_session(phone, {"state": "collecting_email"})
        return _r4_solicitud()

    if option == "4":
        _set_session(phone, {"state": "menu_shown"})
        return _r5_contacto()

    _set_session(phone, {"state": "menu_shown"})
    return _r_no_entendido()


# ─── Utilidad: extraer teléfono del payload de Green API ─────────────────────

def parse_green_api_payload(payload: dict) -> tuple[str, str] | None:
    """
    Extrae (phone, text) del payload que manda Green API al webhook.
    Devuelve None si el mensaje no es de texto o no es entrante.

    Tipos soportados:
      - textMessage          → mensaje de texto simple
      - extendedTextMessage  → mensaje con preview de link o respuesta citada
      - quotedMessage        → respuesta a un mensaje anterior
      - buttonsResponseMessage → respuesta a un mensaje con botones
      - listResponseMessage    → selección en lista interactiva
    """
    if payload.get("typeWebhook") != "incomingMessageReceived":
        return None

    chat_id = payload.get("senderData", {}).get("chatId", "")

    if "@g.us" in chat_id:
        return None   # ignorar mensajes de grupos

    phone    = chat_id.replace("@c.us", "")
    msg_data = payload.get("messageData", {})
    msg_type = msg_data.get("typeMessage", "")

    # Texto simple
    if msg_type == "textMessage":
        text = msg_data.get("textMessageData", {}).get("textMessage", "").strip()

    # Respuesta citada o mensaje con link preview
    elif msg_type in ("extendedTextMessage", "quotedMessage"):
        data = msg_data.get("extendedTextMessageData", {})
        text = data.get("text", "").strip()
        if not text:
            text = msg_data.get("textMessageData", {}).get("textMessage", "").strip()

    # Respuesta a botones interactivos → usar el buttonId como texto
    elif msg_type == "buttonsResponseMessage":
        data = msg_data.get("buttonsResponseMessage", {})
        # selectedButtonId coincide con los IDs "1"-"4" que definimos
        text = data.get("selectedButtonId", "").strip()
        if not text:
            text = data.get("selectedButtonText", "").strip()

    # Selección en lista interactiva → usar el rowId como texto
    elif msg_type == "listResponseMessage":
        data = msg_data.get("listResponseMessage", {})
        text = data.get("singleSelectReply", {}).get("selectedRowId", "").strip()
        if not text:
            text = data.get("title", "").strip()

    else:
        return None   # audio, imagen, sticker, etc.

    if not text or not phone:
        return None

    return phone, text
