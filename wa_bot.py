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

_DEMO_STORE = Path("output/.demo_requests.json")

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
    "• Free — S/0 · 1 búsqueda/día, 10 leads demo\n"
    "• Básico — S/59/mes · 10 reportes/mes, 20 leads full\n"
    "• *Starter — S/149/mes · ilimitado, 30 leads* ⭐\n"
    "• Pro — S/299/mes · 50 leads + API REST\n"
    "• Reseller — S/1,099/mes · white-label para agencias\n\n"
    "Sin contrato. Cancela cuando quieras.\n"
    "¿Quieres probar 3 días gratis con acceso completo?"
)

_PEDIR_TARGET = "Solo escribeme: rubio + ciudad\n\nEj: restaurantes Lima"

_PROCESANDO = "⏳ Buscando *\"{target}\"* en Google Maps... esto toma ~2 min ☕"

# strings centralizados en messages.py — importar lazy para no crear ciclos
def _MSG(key: str, **kwargs) -> str:
    from messages import MSG
    return MSG[key].format(**kwargs) if kwargs else MSG[key]

_YA_REGISTRADO = "Tu reporte ya está en camino ✅"

_BIENVENIDA = """👋 Hola, soy Pipeline_X.

Te ayudo a encontrar leads calificados para tu negocio.

Para empezar, presiona el botón de abajo 👇"""

_NO_ENTENDIDO = """Para buscar leads, presiona *Demo gratis* y te explico cómo funciona."""

# ─── Constructores de respuesta ───────────────────────────────────────────────

def _r_menu(phone: str | None = None) -> list[dict]:
    bienvenida = _BIENVENIDA
    if phone:
        try:
            import db as _db
            profile = _db.get_user_profile(phone)
            name = profile.get("name")
            if name:
                bienvenida = f"Hola {name}! 👋\n\n" + _BIENVENIDA.split("\n\n", 1)[-1]
        except Exception:
            pass
    return [_b(
        bienvenida,
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
        "Esto es solo una muestra 👆\n\n"
        "Con el plan *Starter (S/149/mes)* tienes:\n"
        "✅ Reportes ilimitados\n"
        "✅ Todos los datos sin censura\n"
        "✅ Validación SUNAT incluida\n\n"
        "¿Quieres activar tu acceso o buscar otro rubro?",
        [("upgrade", "🚀 Quiero el plan completo"), ("demo", "🔍 Nueva búsqueda")],
        footer=_FOOTER,
    )]


def _r_upgrade(phone: str) -> list[dict]:
    """
    Respuesta al intent de upgrade.
    Notifica al CEO via PipeAssist y muestra info de transferencia si está configurada.
    La cuenta bancaria viene de la variable de entorno BANK_TRANSFER_INFO.
    Formato sugerido: "BCP · Ahorro · 123-456789-0-12 · Nombre · CCI: 002..."
    """
    from messages import MSG
    from datetime import datetime, timezone

    bank_info = os.environ.get("BANK_TRANSFER_INFO", "").strip()

    # Notificar al CEO inmediatamente
    _notify_ceo_upgrade(phone)

    if bank_info:
        texto = MSG["upgrade_intro"].format(bank_info=bank_info)
    else:
        texto = MSG["upgrade_no_bank"]

    return [_t(texto)]


def _notify_ceo_upgrade(phone: str) -> None:
    """Notifica al CEO vía PipeAssist cuando alguien toca 'Plan completo'."""
    import httpx
    from messages import MSG
    from datetime import datetime, timezone

    token_int = os.environ.get("TELEGRAM_BOT_TOKEN_INTERNO", "")
    admin_ids  = [
        aid.strip()
        for aid in os.environ.get("ADMIN_TELEGRAM_IDS",
                   os.environ.get("ADMIN_CHAT_ID", "")).split(",")
        if aid.strip()
    ]
    if not token_int or not admin_ids:
        return

    msg = MSG["upgrade_ceo_alert"].format(
        phone=phone,
        time=datetime.now(timezone.utc).strftime("%H:%M UTC"),
    )
    for aid in admin_ids:
        try:
            httpx.post(
                f"https://api.telegram.org/bot{token_int}/sendMessage",
                json={"chat_id": aid, "text": msg, "parse_mode": "Markdown"},
                timeout=6,
            )
        except Exception:
            pass

def _notify_feedback(phone: str, rating: str) -> None:
    """Notifica al CEO via PipeAssist cuando llega un feedback."""
    import httpx
    token_int = os.environ.get("TELEGRAM_BOT_TOKEN_INTERNO", "")
    admin_ids  = [
        aid.strip()
        for aid in os.environ.get("ADMIN_TELEGRAM_IDS",
                   os.environ.get("ADMIN_CHAT_ID", "")).split(",")
        if aid.strip()
    ]
    if not token_int or not admin_ids:
        return
    emoji_map = {
        "feedback_good": "👍 Muy útil",
        "feedback_ok":   "😐 Regular",
        "feedback_bad":  "👎 Poco útil",
    }
    msg = (
        f"💬 *Feedback recibido*\n\n"
        f"📱 `{phone}`\n"
        f"⭐ {emoji_map.get(rating, rating)}"
    )
    for aid in admin_ids:
        try:
            httpx.post(
                f"https://api.telegram.org/bot{token_int}/sendMessage",
                json={"chat_id": aid, "text": msg, "parse_mode": "Markdown"},
                timeout=6,
            )
        except Exception:
            pass


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
        "😔 Lamento que no quedara cómo esperabas.\n\n"
        "Pero puedo reenviarte el reporte por *Telegram* donde suele ser más estable.\n\n"
        "1. Abre: t.me/Pipeline_X_Bot\n"
        "2. Escribe /start\n"
        "3. Envía tu búsqueda\n\n"
        "¿Probamos por ahí? 🎯",
        [("contacto", "💬 Hablar con alguien")],
    )]

def _r_feedback() -> list[dict]:
    return [_b(
        _MSG("feedback_ask"),
        [("feedback_good", "👍 Muy útil"), ("feedback_ok", "😐 Regular"), ("feedback_bad", "👎 Poco útil")],
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
                  "hey", "hi", "hello", "buen dia", "buen día", "saludos", "iniciar", "empezar", "empezamos"],
    "buscar":    ["buscar", "busqueda", "búsqueda", "prospectar", "lead", "leads", "encontrar",
                  "busco", "necesito", "quiero buscar", "dame leads", "darme leads"],
    "demo":      ["demo", "gratis", "probar", "prueba", "leads", "reporte", "ver", "🚀", "1", "nuevo reporte", "nuevo", "test"],
    "precios":   ["precio", "precios", "costo", "plan", "planes", "cuanto", "cuánto", "tarifa", "💰", "2"],
    "info":      ["info", "que es", "qué es", "como funciona", "cómo funciona", "información", "❓", "3"],
    "contacto":  ["contacto", "hablar", "humano", "soporte", "ayuda", "llamar", "💬", "4"],
    "upgrade":   ["upgrade", "plan completo", "quiero plan", "starter", "acceso", "comprar", "🚀 quiero"],
    "preguntas": ["pregunta", "preguntas", "duda", "dudas", "💬 tengo"],
    "garantia":  ["garantia", "garantía", "reembolso", "devolucion", "devolución", "devolver", "no funciono",
                  "no funcionó", "no sirve", "mal reporte", "quiero mi dinero", "reembolsar"],
    "feedback_good": ["feedback_good", "muy útil", "muy util", "excelente", "genial", "perfecto"],
    "feedback_ok":   ["feedback_ok",   "regular", "normal", "mas o menos", "más o menos", "ok"],
    "feedback_bad":  ["feedback_bad", "poco útil", "poco util", "malo", "mal", "no sirvió", "no sirvio"],
    "historial":     ["mis reportes", "historial", "mis busquedas", "mis búsquedas",
                      "que busque", "qué busqué", "repetir"],
    "unsubscribe":   ["stop", "baja", "no quiero mensajes", "cancelar mensajes", "unsubscribe",
                      "cancelar", "dar de baja", "dejar de recibir"],
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
# Persistencia delegada a db.py (PostgreSQL) con fallback a archivo JSON.

_SESSION_TTL  = 30 * 60   # 30 min → resetea a idle
_PIPELINE_TTL =  5 * 60   # 5 min  → si sigue "running" se asume caído


def _get_session(phone: str) -> dict:
    import time
    import db
    session = db.get_session(phone)
    now = time.time()
    ts  = session.get("_ts", now)

    # Pipeline atascado → resetear
    if session.get("state") == "running_pipeline" and (now - ts) > _PIPELINE_TTL:
        session = {"state": "idle"}
        db.set_session(phone, session)

    # Sesión expirada → resetear
    elif session.get("state") not in ("idle",) and (now - ts) > _SESSION_TTL:
        session = {"state": "idle"}
        db.set_session(phone, session)

    return session


def _set_session(phone: str, session: dict) -> None:
    import time
    import db
    session["_ts"] = time.time()
    db.set_session(phone, session)


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

    # ── Estado unsubscribed — solo reactivar con saludo ───────────────────────
    if state == "unsubscribed":
        intent = _detect_intent(text)
        if intent == "saludo":
            _set_session(phone, {"state": "menu_shown"})
            return _r_menu(phone)
        # Ignorar cualquier otro mensaje
        return []

    # ── Audio — respuesta amigable ────────────────────────────────────────────
    if text == "__AUDIO__":
        return [_t(_MSG("audio_not_supported"))]

    # ── Imagen ────────────────────────────────────────────────────────────────
    if text == "__IMAGE__":
        if state == "upgrade_prompted":
            _set_session(phone, {"state": "menu_shown"})
            _notify_ceo_upgrade(phone)
            return [_t(_MSG("image_received_upgrade"))]
        return [_t(_MSG("image_unknown"))]

    # ── Saludo siempre resetea (cualquier estado) ─────────────────────────────
    intent = _detect_intent(text)
    if intent == "saludo":
        _set_session(phone, {"state": "menu_shown"})
        return _r_menu(phone)

    # ── Esperando nombre ──────────────────────────────────────────────────────
    if state == "collecting_name":
        name = text.strip().title()
        try:
            import db as _db
            _db.set_user_profile(phone, name=name)
        except Exception:
            pass
        session["name"] = name
        _set_session(phone, {**session, "state": "menu_shown", "name": name})
        from messages import MSG
        bienvenida = MSG["name_saved"].format(name=name)
        return [_b(
            bienvenida,
            [("demo", "🚀 Demo gratis"), ("precios", "💰 Precios"), ("info", "❓ Cómo funciona")],
            footer=_FOOTER,
        )]

    # ── Confirmando ciudad por defecto ────────────────────────────────────────
    if state == "confirming_city":
        t_lower = text.lower().strip()
        affirm = {"sí", "si", "ok", "esa", "mismo", "allí", "ahi", "ahí", "dale", "va"}
        default_city = session.get("default_city", "")
        if t_lower in affirm and default_city:
            # Usar la ciudad guardada con el último target sin ciudad
            last_target = session.get("pending_target", "")
            full_target = f"{last_target} en {default_city}" if last_target else default_city
            return _launch_pipeline(phone, full_target, session)
        else:
            # Tratar el texto como un nuevo target
            new_text = text
            # Si no trae ubicación, pasarlo como collecting_target
            words = [w for w in new_text.split() if len(w) > 2]
            has_location = " en " in new_text.lower() or "," in new_text or len(words) >= 2
            if has_location:
                return _launch_pipeline(phone, new_text, session)
            _set_session(phone, {**session, "state": "collecting_target"})
            return [_t(_MSG("ask_target"))]

    # ── Esperando target ──────────────────────────────────────────────────────
    if state == "collecting_target":
        if len(text) < 4:
            return [_t("Necesito más detalle 😊\nEj: *\"Ferreterías en Trujillo\"*")]
        # Validar que el target tenga al menos 2 palabras (rubro + ciudad/zona)
        words = [w for w in text.split() if len(w) > 2]
        has_location = " en " in text.lower() or "," in text or len(words) >= 2
        if not has_location:
            # Verificar si hay ciudad por defecto guardada
            try:
                import db as _db
                profile = _db.get_user_profile(phone)
                default_city = profile.get("default_city") or session.get("default_city", "")
            except Exception:
                default_city = session.get("default_city", "")
            if default_city:
                _set_session(phone, {**session, "state": "confirming_city",
                                     "pending_target": text, "default_city": default_city})
                return [_t(_MSG("confirm_default_city").format(city=default_city))]
            return [_t(
                "¿En qué zona o ciudad? 📍\n\n"
                "Ejemplo: *\"Ferreterías en Miraflores\"* o *\"Clínicas Lima\"*\n\n"
                "Con la ciudad los resultados son más precisos."
            )]
        return _launch_pipeline(phone, text, session)

    # ── Pipeline corriendo — no interrumpir ───────────────────────────────────
    if state == "running_pipeline":
        return [_t(_MSG("pipeline_running"))]

    # ── Esperando comprobante de pago ─────────────────────────────────────────
    if state == "upgrade_prompted":
        # El usuario puede estar enviando texto de confirmación.
        # Si fuera imagen ya se manejó arriba.
        _set_session(phone, {"state": "menu_shown"})
        _notify_ceo_upgrade(phone)   # segunda notificación con el mensaje que mandó
        return [_t(
            "Gracias, recibido ✅\n\n"
            "Estamos verificando tu pago. En minutos te confirmamos "
            "y activamos tu acceso al plan Starter.\n\n"
            "Si tienes alguna duda escríbenos a *contacto@pipelinex.app*"
        )]

    # ── Esperando feedback del reporte ───────────────────────────────────────
    if state == "feedback_prompted":
        _set_session(phone, {"state": "done"})
        fb_intent = intent if intent in ("feedback_good", "feedback_ok", "feedback_bad") else None
        if fb_intent:
            try:
                import db as _db
                _db.log_event(phone, "wa_feedback", {"rating": fb_intent})
            except Exception:
                pass
            _notify_feedback(phone, fb_intent)
            key_map = {
                "feedback_good": "feedback_thanks_good",
                "feedback_ok":   "feedback_thanks_ok",
                "feedback_bad":  "feedback_thanks_bad",
            }
            return [_t(_MSG(key_map[fb_intent]))]
        # Si manda otra cosa → tratar como intent normal
        if intent:
            return _handle_intent(phone, intent)
        return _r_no_entendido()

    # ── Ya entregado — ofrecer nuevo reporte o info ───────────────────────────
    if state == "done":
        if intent:
            return _handle_intent(phone, intent)
        # Cualquier texto libre lo tratamos como un nuevo target directamente
        if len(text) >= 5:
            words = [w for w in text.split() if len(w) > 2]
            has_location = " en " in text.lower() or "," in text or len(words) >= 2
            if has_location:
                return _launch_pipeline(phone, text, session)
        _set_session(phone, {"state": "collecting_target"})
        return [_t(
            "¿Qué tipo de empresas buscas ahora? 🔍\n\n"
            "Escribe industria + ciudad:\n"
            "_\"Restaurantes en San Isidro\"_ · _\"Clínicas en Trujillo\"_"
        )]

    # ── Cualquier otro estado — detectar intención ────────────────────────────
    if intent:
        return _handle_intent(phone, intent)

    # Sin intención detectada: primera vez → preguntar nombre; después → no entendido
    if state == "idle":
        _set_session(phone, {"state": "collecting_name"})
        return [_t(_MSG("ask_name"))]

    if state == "menu_shown":
        return _r_no_entendido()

    return _r_no_entendido()


def _launch_pipeline(phone: str, target: str, session: dict) -> list[dict]:
    """
    Helper compartido: aplica rate limiting, guarda ciudad por defecto,
    lanza el pipeline y retorna mensajes.
    """
    # Rate limiting por plan
    try:
        import db as _db
        import config as _cfg
        sub = _db.get_subscriber(phone)
        plan_name = (
            sub.get("plan", "free")
            if sub and sub.get("status") == "active" and (
                not sub.get("expires_at") or
                sub.get("expires_at") > datetime.now(timezone.utc).isoformat()
            )
            else "free"
        )
        plan_cfg = _cfg.PLANS.get(plan_name, _cfg.PLANS["free"])
        limit_day   = plan_cfg.get("searches_per_day")
        limit_month = plan_cfg.get("searches_per_month")
        if limit_day is not None and _db.get_daily_search_count(phone) >= limit_day:
            _set_session(phone, {**session, "state": "upgrade_prompted"})
            return [_t(_MSG("daily_limit_reached"))] + _r_upgrade(phone)
        if limit_month is not None and _db.get_monthly_search_count(phone) >= limit_month:
            _set_session(phone, {**session, "state": "upgrade_prompted"})
            return [_t(_MSG("monthly_limit_reached"))] + _r_upgrade(phone)
    except Exception:
        pass

    # Extraer ciudad y guardar en perfil
    try:
        import db as _db
        city = None
        t_lower = target.lower()
        if " en " in t_lower:
            city = target.split(" en ")[-1].strip().title()
        elif "," in target:
            city = target.split(",")[-1].strip().title()
        if city:
            _db.set_user_profile(phone, default_city=city)
            session = {**session, "default_city": city}
    except Exception:
        pass

    _set_session(phone, {**session, "state": "running_pipeline", "target": target})
    try:
        import db as _db
        _db.log_event(phone, _db.EventType.WA_SEARCH, {"target": target})
    except Exception:
        pass
    return [*_r_procesando(target), {"type": "pipeline_request", "target": target}]


def _handle_intent(phone: str, intent: str) -> list[dict]:
    """Despacha la intención detectada."""
    if intent == "saludo":
        _set_session(phone, {"state": "menu_shown"})
        return _r_menu(phone)

    if intent == "buscar":
        _set_session(phone, {"state": "collecting_target"})
        return _r_pedir_target()
    
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
        try:
            import db as _db
            _db.log_event(phone, _db.EventType.WA_UPGRADE_CLICK)
            # Primera vez: activar trial de 3 días automáticamente
            if not _db.has_trialed(phone) and not _db.is_active_subscriber(phone):
                _db.upsert_subscriber(phone, plan="trial", days=3, notes="auto-trial")
                _db.log_event(phone, _db.EventType.SUBSCRIBER_ACTIVATED, {"plan": "trial"})
                _set_session(phone, {"state": "collecting_target"})
                _notify_ceo_upgrade(phone)  # re-usar notificación al CEO
                return [_t(_MSG("trial_started"))]
        except Exception:
            pass
        _set_session(phone, {"state": "upgrade_prompted"})
        return _r_upgrade(phone)

    if intent == "preguntas":
        _set_session(phone, {"state": "menu_shown"})
        return [_t("Con gusto. ¿Qué quieres saber sobre Pipeline_X?")]

    if intent == "garantia":
        _set_session(phone, {"state": "menu_shown"})
        return _r_garantia()

    if intent == "historial":
        try:
            import db as _db
            from datetime import timedelta
            history = _db.get_search_history(phone, limit=3)
        except Exception:
            history = []
        if not history:
            return [_t(_MSG("search_history_empty"))]
        items = "\n".join(
            f"• {h['target']} _{h['date']}_" for h in history
        )
        return [_t(_MSG("search_history").format(items=items))]

    if intent == "unsubscribe":
        _set_session(phone, {"state": "unsubscribed"})
        try:
            import db as _db
            _db.log_event(phone, _db.EventType.WA_UNSUBSCRIBED)
        except Exception:
            pass
        return [_t(_MSG("unsubscribed"))]

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

    # Imagen o documento (comprobante de pago u otro)
    elif msg_type in ("imageMessage", "documentMessage"):
        return phone, "__IMAGE__"

    # Audio / voz
    elif msg_type in ("audioMessage", "pttMessage"):
        return phone, "__AUDIO__"

    else:
        return None   # sticker, video, etc.

    if not text or not phone:
        return None

    return phone, text
