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

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

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

_FOOTER = "Pipeline_X · pipelinex.app"

# ─── Textos ───────────────────────────────────────────────────────────────────

_BIENVENIDA = (
    "👋 Hola, soy *Pipeline_X*.\n\n"
    "Te ayudo a conseguir más clientes sin contratar a nadie.\n"
    "Dime a qué tipo de negocio le quieres vender y en qué ciudad — "
    "en minutos recibes aquí mismo una lista de prospectos listos para contactar."
)

_INFO_BODY = (
    "En 3 pasos:\n"
    "1️⃣ Escribes qué buscas — *\"Ferreterías en Trujillo\"*\n"
    "2️⃣ Buscamos en Google Maps y calificamos con IA (score 0–100)\n"
    "3️⃣ Recibes aquí en WhatsApp un PDF con leads + mensajes listos para enviar\n\n"
    "Sin instalar nada. Sin aprender ningún sistema. Solo abres el PDF y llamas."
)

_PRECIOS_BODY = (
    "💰 *Planes Pipeline_X*\n\n"
    "• Free — S/0 · 10 leads, sin tarjeta\n"
    "• *Starter — S/149/mes · reportes ilimitados* ⭐\n"
    "• Pro — S/299/mes · mayor volumen + API\n"
    "• Reseller — S/1,099/mes · white-label para agencias\n\n"
    "Menos que el costo de un vendedor por un día.\n"
    "Sin contrato. Cancela cuando quieras."
)

_PEDIR_TARGET = (
    "¿Qué tipo de empresas quieres prospectar?\n\n"
    "Escribe industria + ciudad:\n"
    "_\"Ferreterías en Trujillo\"_ · _\"Clínicas en Lima\"_"
)

_PROCESANDO = "⏳ Buscando *\"{target}\"* en Google Maps... esto toma ~2 min ☕"

_YA_REGISTRADO = "Tu reporte ya está en camino ✅"

_NO_ENTENDIDO = "No entendí eso 🤔 ¿En qué puedo ayudarte?"

# ─── Constructores de respuesta ───────────────────────────────────────────────

def _r_menu() -> list[dict]:
    return [_b(
        _BIENVENIDA,
        [("demo", "🚀 Demo gratis"), ("precios", "💰 Precios"), ("info", "❓ Cómo funciona")],
        footer=_FOOTER,
    )]

def _r_info() -> list[dict]:
    return [_b(
        _INFO_BODY,
        [("demo", "🚀 Probar gratis"), ("precios", "💰 Ver precios")],
        footer=_FOOTER,
    )]

def _r_precios() -> list[dict]:
    return [_b(
        _PRECIOS_BODY,
        [("demo", "🚀 Probar gratis"), ("contacto", "💬 Hablar con alguien")],
        footer=_FOOTER,
    )]

def _r_pedir_target() -> list[dict]:
    return [_t(_PEDIR_TARGET)]

def _r_procesando(target: str = "") -> list[dict]:
    return [_t(_PROCESANDO.format(target=target or "tu búsqueda"))]

def _r_post_demo() -> list[dict]:
    return [_b(
        "Esto es solo una muestra.\nCon el plan Starter (S/149/mes) tienes reportes ilimitados, "
        "validación SUNAT y mensajes personalizados por industria.\n\n"
        "¿Quieres buscar otro rubro? Escribe el nombre del negocio y ciudad.",
        [("demo", "🔍 Nueva búsqueda"), ("upgrade", "🚀 Plan completo"), ("preguntas", "💬 Preguntas")],
        footer=_FOOTER,
    )]

def _r_contacto() -> list[dict]:
    return [_t(
        "📧 contacto@pipelinex.app\n"
        "🤖 Telegram: t.me/Pipeline_X_bot (respuesta inmediata)"
    )]

def _r_ya_registrado() -> list[dict]:
    return [_b(
        _YA_REGISTRADO,
        [("demo", "🔄 Nuevo reporte"), ("precios", "💰 Ver planes")],
        footer=_FOOTER,
    )]

def _r_garantia() -> list[dict]:
    return [_b(
        "Entendido 👌\n\n"
        "Nuestra garantía es simple:\n"
        "Si tu primer reporte no incluye al menos *5 leads calificados* "
        "(score ≥ 60), te generamos otro sin costo — sin preguntas.\n\n"
        "Pero antes de pagar, puedes probarlo gratis ahora mismo.\n"
        "Dinos qué tipo de empresas buscas y en qué ciudad 👇",
        [("demo", "🚀 Probar gratis primero"), ("precios", "💰 Ver planes")],
        footer=_FOOTER,
    )]

def _r_no_entendido() -> list[dict]:
    return [_b(
        _NO_ENTENDIDO,
        [("demo", "🚀 Demo gratis"), ("precios", "💰 Precios"), ("info", "❓ Info")],
        footer=_FOOTER,
    )]


# ─── Detección de intención ───────────────────────────────────────────────────

_KEYWORDS: dict[str, list[str]] = {
    "saludo":    ["hola", "buenas", "buenos dias", "buenos días", "buenas tardes", "buenas noches",
                  "hey", "hi", "hello", "buen dia", "buen día", "saludos"],
    "demo":      ["demo", "gratis", "probar", "prueba", "leads", "reporte", "ver", "🚀", "1", "nuevo reporte", "nuevo"],
    "precios":   ["precio", "precios", "costo", "plan", "planes", "cuanto", "cuánto", "tarifa", "💰", "2"],
    "info":      ["info", "que es", "qué es", "como funciona", "cómo funciona", "información", "❓", "3"],
    "contacto":  ["contacto", "hablar", "humano", "soporte", "ayuda", "llamar", "💬", "4"],
    "upgrade":   ["upgrade", "plan completo", "quiero plan", "starter", "acceso", "comprar", "🚀 quiero"],
    "preguntas": ["pregunta", "preguntas", "duda", "dudas", "💬 tengo"],
    "garantia":  ["garantia", "garantía", "reembolso", "devolucion", "devolución", "devolver", "no funciono",
                  "no funcionó", "no sirve", "mal reporte", "quiero mi dinero", "reembolsar"],
}

def _detect_intent(text: str) -> str | None:
    """Detecta la intención del mensaje o None si no hay match."""
    t = text.strip().lower()
    for intent, keywords in _KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return intent
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


_SESSION_TTL = 30 * 60        # 30 min → resetea a idle
_PIPELINE_TTL = 5 * 60        # 5 min → si sigue "running" se asume caído


def _get_session(phone: str) -> dict:
    import time
    session = _load_sessions().get(phone, {"state": "idle"})
    now = time.time()
    ts  = session.get("_ts", now)

    # Pipeline atascado → resetear
    if session.get("state") == "running_pipeline" and (now - ts) > _PIPELINE_TTL:
        session = {"state": "idle"}

    # Sesión expirada → resetear
    elif session.get("state") not in ("idle",) and (now - ts) > _SESSION_TTL:
        session = {"state": "idle"}

    return session


def _set_session(phone: str, session: dict) -> None:
    import time
    sessions = _load_sessions()
    session["_ts"] = time.time()
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

    # ── Saludo siempre resetea (cualquier estado) ─────────────────────────────
    intent = _detect_intent(text)
    if intent == "saludo":
        _set_session(phone, {"state": "menu_shown"})
        return _r_menu()

    # ── Esperando target ──────────────────────────────────────────────────────
    if state == "collecting_target":
        if len(text) < 5:
            return [_t("Necesito más detalle 😊\nEj: *\"Ferreterías en Trujillo\"*")]
        # Validar que incluya una ciudad/zona (debe tener al menos 2 palabras distintas)
        words = [w for w in text.split() if len(w) > 2]
        has_location = (
            " en " in text.lower()
            or "," in text
            or len(words) >= 2
        )
        if not has_location:
            return [_t(
                "¿En qué zona o ciudad? 📍\n\n"
                "Ejemplo: *\"Ferreterías en Miraflores\"* o *\"Clínicas Lima\"*\n\n"
                "Con la ciudad los resultados son mucho más precisos."
            )]
        _set_session(phone, {"state": "running_pipeline", "target": text})
        return [*_r_procesando(text), {"type": "pipeline_request", "target": text}]

    # ── Pipeline corriendo — no interrumpir ───────────────────────────────────
    if state == "running_pipeline":
        return [_t("⏳ Tu reporte está en proceso, ya casi está listo...")]

    # ── Ya entregado — ofrecer nuevo reporte o info ───────────────────────────
    if state == "done":
        if intent:
            return _handle_intent(phone, intent)
        # Cualquier texto libre lo tratamos como un nuevo target directamente
        if len(text) >= 5:
            words = [w for w in text.split() if len(w) > 2]
            has_location = " en " in text.lower() or "," in text or len(words) >= 2
            if has_location:
                _set_session(phone, {"state": "running_pipeline", "target": text})
                return [*_r_procesando(text), {"type": "pipeline_request", "target": text}]
        _set_session(phone, {"state": "collecting_target"})
        return [_t(
            "¿Qué tipo de empresas buscas ahora? 🔍\n\n"
            "Escribe industria + ciudad:\n"
            "_\"Restaurantes en San Isidro\"_ · _\"Clínicas en Trujillo\"_"
        )]

    # ── Cualquier otro estado — detectar intención ────────────────────────────
    if intent:
        return _handle_intent(phone, intent)

    # Sin intención detectada: primera vez → menú, después → no entendido
    if state == "idle":
        _set_session(phone, {"state": "menu_shown"})
        return _r_menu()

    return _r_no_entendido()


def _handle_intent(phone: str, intent: str) -> list[dict]:
    """Despacha la intención detectada."""
    if intent == "saludo":
        _set_session(phone, {"state": "menu_shown"})
        return _r_menu()

    if intent == "demo":
        _set_session(phone, {"state": "collecting_target"})
        return _r_pedir_target()

    if intent == "precios":
        _set_session(phone, {"state": "menu_shown"})
        return _r_precios()

    if intent == "info":
        _set_session(phone, {"state": "menu_shown"})
        return _r_info()

    if intent == "contacto":
        _set_session(phone, {"state": "menu_shown"})
        return _r_contacto()

    if intent == "upgrade":
        _set_session(phone, {"state": "menu_shown"})
        return [_t("Para activar tu acceso escríbenos a *contacto@pipelinex.io* con asunto 'Acceso Starter'.")]

    if intent == "preguntas":
        _set_session(phone, {"state": "menu_shown"})
        return [_t("Con gusto. ¿Qué quieres saber sobre Pipeline_X?")]

    if intent == "garantia":
        _set_session(phone, {"state": "menu_shown"})
        return _r_garantia()

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
