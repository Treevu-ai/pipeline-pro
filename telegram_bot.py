"""
telegram_bot.py — Bot de ventas Pipeline_X en Telegram.

Asistente conversacional con IA (OpenAI primario, Groq fallback) + flujo de demo en vivo.

Flujos:
  /start            → Alex (bot de ventas conversacional)
  /start demo       → Demo en vivo: pide target → corre pipeline → entrega CSV → captura email
  /reset            → Reinicia conversación
  /planes           → Muestra planes disponibles

Variables de entorno requeridas:
  TELEGRAM_BOT_TOKEN  — token de @BotFather
  OPENAI_API_KEY      — OpenAI como LLM primario (gpt-4o-mini)
  GROQ_API_KEY        — opcional, Groq como fallback si OpenAI falla

Deep link para landing:
  t.me/<botname>?start=demo
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import time as _time
from collections import defaultdict, deque
from pathlib import Path

import config as cfg
import logging_config

from groq import Groq
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logging_config.silence_sensitive_http_loggers()
log = logging.getLogger("pipeline_x_bot")

# ─── Groq client ─────────────────────────────────────────────────────────────

_groq: Groq | None = None

# ─── System prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
Eres Alex, el asistente de ventas de Pipeline_X.

Pipeline_X es una plataforma B2B de IA que automatiza la prospección de empresas
para MIPYME en Latinoamérica. Encuentra negocios reales en Google Maps (tiendas,
constructoras, transportistas, clínicas, estudios contables, etc.), los califica
con IA (score 0–100) y genera mensajes de outreach personalizados por industria.

IMPORTANTE — qué busca Pipeline_X:
- Busca NEGOCIOS (empresas, comercios, pymes), NO personas individuales.
- La fuente principal es Google Maps: cualquier negocio registrado ahí puede ser un lead.
- El cliente de Pipeline_X es una empresa que quiere venderle a otras empresas (B2B).

PLANES (usa estos precios exactos, sin inventar):
- Free      S/0      — 10 leads demo, 1 búsqueda/día, sin tarjeta
- Starter   S/129/mes — 30 leads, búsquedas ilimitadas, PDF completo  ← tier principal
- Pro       S/299/mes — 50 leads + API REST, para equipos que automatizan

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PERSONALIDAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Nombre: Alex
- Tono: profesional, directo, empático. Sin ser agresivo ni insistente.
- Español neutro latinoamericano.
- Mensajes cortos (máximo 4 líneas). Si necesitas más, usa bullets con guión.
- Usa 1 emoji por mensaje máximo. No abuses.
- NUNCA menciones precios hasta entender el dolor del prospecto.
- NUNCA hagas más de 2 preguntas en el mismo mensaje.
- El usuario puede responder con botones o con texto libre. Ambos son válidos.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLUJO DE CONVERSACIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ETAPA 1 — BIENVENIDA
Cuando el usuario escribe /start:
Saluda brevemente y pregunta en qué industria trabaja (ya se le mostraron botones).

ETAPA 2 — CALIFICACIÓN
Según la industria seleccionada, pregunta cuántos leads busca por mes
(ya se le mostraron opciones). Luego pregunta cómo los consigue hoy.

ETAPA 3 — DESCUBRIMIENTO DEL DOLOR
Identifica el dolor principal:
- "Manual/Excel"          → énfasis en automatización y tiempo ahorrado
- "LinkedIn/Ads"          → énfasis en calidad vs cantidad y costo por lead
- "Referidos"             → énfasis en escala más allá de la red personal
- "Sin proceso definido"  → énfasis en estructura y pipeline limpio
- "Mucho tiempo"          → énfasis en scraping automático
- "Leads de baja calidad" → énfasis en score IA 0-100

ETAPA 4 — PRESENTACIÓN DE VALOR
Conecta el dolor con Pipeline_X usando 2-3 beneficios concretos para SU industria.
Usa siempre un ejemplo específico con su sector.

Ejemplos:
- Retail      → "En 10 minutos: 50 tiendas del rubro calificadas con email y mensaje listo para enviar."
- Logística   → "Detecta empresas transportistas con score alto y redacta email sobre costos operativos."
- Construcción→ "Encuentra constructoras y contratistas, mensaje enfocado en flujo de caja en obra."
- Servicios   → "Cualquier tipo de negocio en Google Maps: lo encuentras, calificas y contactas sin Excel."
- Salud       → "Clínicas, laboratorios, consultorios: base de negocios del sector lista en minutos."

ETAPA 5 — MANEJO DE OBJECIONES

"Es muy caro"
→ "Un SDR humano cuesta S/2.500–3.500/mes. Pipeline_X desde S/129. ¿Cuánto vale conseguir 10 clientes nuevos?"

"No tengo tiempo para aprenderlo"
→ "3 pasos: escribes la búsqueda, esperás 2 min, recibes el PDF con leads y mensajes. Sin config."

"¿Funciona para mi industria?"
→ "Si está en Google Maps, Pipeline_X lo encuentra. Retail, logística, salud, construcción y más."

"¿Cómo sé que la IA califica bien?"
→ "Cada lead tiene score 0–100 con justificación: por qué calificó, bloqueador y siguiente acción."

"Necesito pensarlo"
→ "Entiendo. ¿Qué información te ayudaría a decidir? Puedo generarte 10 leads reales de tu industria ahora mismo."

ETAPA 6 — CIERRE

Según el tamaño:
- 1 persona / equipo pequeño: recomienda Starter (S/129/mes)
- Equipo de ventas / necesita API: recomienda Pro (S/299/mes)

Si quiere comprar: "Escríbeme a contacto@pipelinex.app con asunto 'Acceso [Plan]' y te activamos hoy."
Si quiere demo: "Puedo generarte 10 leads reales de tu industria ahora mismo. ¿Qué tipo de empresa prospectás?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLAS ABSOLUTAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Nunca inventes funcionalidades que no existen.
2. No prometas resultados garantizados.
3. No menciones competidores.
4. Mantén el foco en el dolor del prospecto, no en las features.
5. Pipeline_X busca NEGOCIOS (empresas, pymes, comercios), nunca personas individuales.
   Si el prospecto pregunta si puede buscar personas: "Pipeline_X trabaja con negocios registrados
   en Google Maps. Si tu cliente ideal es una empresa o comercio, lo encontramos."
"""

# ─── Botones inline ───────────────────────────────────────────────────────────

def kb_start() -> InlineKeyboardMarkup:
    """Entrada principal — 3 opciones, acción de demo al frente."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Probar gratis — 10 leads reales", callback_data="start_demo")],
        [InlineKeyboardButton("💰 Planes y precios",  callback_data="start_planes"),
         InlineKeyboardButton("❓ Cómo funciona",     callback_data="start_info")],
    ])

def kb_planes() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Free — S/0  (10 leads demo)",              callback_data="plan_free")],
        [InlineKeyboardButton("⭐ Starter — S/129/mes  (30 leads, ilimitado)", callback_data="plan_starter")],
        [InlineKeyboardButton("Pro — S/299/mes  (50 leads + API REST)",   callback_data="plan_pro")],
        [InlineKeyboardButton("🚀 Probar gratis primero",                 callback_data="start_demo")],
    ])

def kb_post_demo() -> InlineKeyboardMarkup:
    """Aparece justo después de entregar el PDF de demo."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Quiero el PDF completo  (Starter S/129/mes)", callback_data="demo_upgrade")],
        [InlineKeyboardButton("💬 Tengo preguntas",  callback_data="demo_preguntas"),
         InlineKeyboardButton("👎 No fue útil",      callback_data="demo_no_util")],
    ])

def kb_upgrade_done() -> InlineKeyboardMarkup:
    """Después de capturar email para upgrade."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Ver todos los planes", callback_data="start_planes")],
    ])


# ─── Etiquetas legibles de callbacks ─────────────────────────────────────────

LABELS: dict[str, str] = {
    "start_demo":    "Quiero probar gratis",
    "start_planes":  "Planes y precios",
    "start_info":    "Cómo funciona Pipeline_X",
    "plan_free":     "Free S/0",
    "plan_starter":  "Starter S/129/mes",
    "plan_pro":      "Pro S/299/mes",
    "demo_upgrade":  "Quiero el PDF completo (Starter)",
    "demo_preguntas":"Tengo preguntas sobre la demo",
    "demo_no_util":  "No me fue útil",
}

# ─── Rate limiter ─────────────────────────────────────────────────────────────

_RATE_WINDOW  = 60
_RATE_LIMIT   = 12
_rate_buckets: dict[int, deque] = defaultdict(deque)

def _is_rate_limited(user_id: int) -> bool:
    now = _time.monotonic()
    bucket = _rate_buckets[user_id]
    while bucket and now - bucket[0] > _RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT:
        return True
    bucket.append(now)
    return False

# ─── Conversation store ───────────────────────────────────────────────────────

_conversations: dict[int, list[dict]] = {}
MAX_HISTORY = 20

# ─── Demo state machine ───────────────────────────────────────────────────────
# Estados posibles por usuario:
#   "waiting_target"   — bot preguntó el target, esperando respuesta
#   "running"          — pipeline corriendo
#   "delivered"        — CSV entregado, esperando acción del usuario
#   "collecting_email" — usuario eligió upgrade, bot pidió email
#   "done"             — email capturado, flujo terminado

_demo_states: dict[int, dict] = {}

DEMO_LEADS_LIMIT = 10  # Tier free — debe coincidir con config.PLANS["free"]["leads_limit"]

# ─── Demo usage tracking ──────────────────────────────────────────────────────
# Persiste en disco para sobrevivir reinicios del bot.
_DEMO_RUNS_STORE = Path("output/.demo_runs.json")


def _has_used_demo(user_id: int) -> bool:
    """Devuelve True si el user_id ya consumió su demo gratuita."""
    try:
        if _DEMO_RUNS_STORE.exists():
            runs = json.loads(_DEMO_RUNS_STORE.read_text(encoding="utf-8"))
            return any(r.get("user_id") == user_id for r in runs)
    except Exception:
        pass
    return False


def _record_demo_run(user_id: int, target: str) -> None:
    """Registra que el usuario consumió su demo gratuita."""
    from datetime import datetime, timezone

    try:
        runs = json.loads(_DEMO_RUNS_STORE.read_text(encoding="utf-8")) if _DEMO_RUNS_STORE.exists() else []
    except Exception:
        runs = []

    if not any(r.get("user_id") == user_id for r in runs):
        runs.append({
            "user_id":  user_id,
            "target":   target,
            "ts":       datetime.now(timezone.utc).isoformat(),
        })
        _DEMO_RUNS_STORE.parent.mkdir(parents=True, exist_ok=True)
        _DEMO_RUNS_STORE.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_pipeline_sync(target: str) -> list[dict]:
    """
    Corre el pipeline completo en el hilo del ejecutor.
    Devuelve lista de leads enriquecidos y calificados.
    """
    # Asegurar que el directorio del proyecto esté en el path
    project_dir = os.path.dirname(os.path.abspath(__file__))
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    from scraper import scrape_google_maps, enrich_leads
    from sdr_agent import qualify_row, pre_score

    raw = scrape_google_maps(target, DEMO_LEADS_LIMIT)
    enriched = enrich_leads(raw, use_sunat=False)  # SUNAT deshabilitado en tier free

    results = []
    for lead in enriched:
        base = pre_score(lead)
        try:
            result = qualify_row(lead, "email", base)
            result["qualify_error"] = ""
        except Exception as exc:
            result = {k: "" for k in cfg.OUTPUT_KEYS if k != "qualify_error"}
            result["qualify_error"] = str(exc)
        results.append({**lead, **result})
    return results


def _save_demo_lead(user_id: int, target: str, email: str) -> None:
    """Persiste el email capturado post-demo en el mismo store que /demo-request."""
    from datetime import datetime, timezone

    store = Path("output/.demo_requests.json")
    try:
        records = json.loads(store.read_text(encoding="utf-8")) if store.exists() else []
    except Exception:
        records = []

    # Deduplicar por email
    if any(r.get("email", "").lower() == email.lower() for r in records):
        return

    records.append({
        "nombre":    "",
        "empresa":   "",
        "ruc":       "",
        "email":     email,
        "industria": target,
        "ciudad":    "",
        "ip":        f"telegram:{user_id}",
        "ts":        datetime.now(timezone.utc).isoformat(),
        "status":    "demo_telegram",
    })
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


async def _notify_admin_demo_email(context: "ContextTypes.DEFAULT_TYPE", user_id: int, email: str, target: str) -> None:
    """Notifica al admin cuando un usuario captura su email post-demo."""
    admin_id_raw = os.environ.get("ADMIN_CHAT_ID", "")
    if not admin_id_raw:
        return
    try:
        admin_id = int(admin_id_raw)
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"🎯 *Nuevo lead demo Telegram*\n\n"
                f"Email : `{email}`\n"
                f"Target: {target}\n"
                f"User  : `{user_id}`"
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        log.warning("No se pudo notificar al admin: %s", exc)


# ─── LLM reply ───────────────────────────────────────────────────────────────

def _get_reply(user_id: int, user_message: str) -> str:
    global _groq

    if user_id not in _conversations:
        _conversations[user_id] = []

    _conversations[user_id].append({"role": "user", "content": user_message})

    if len(_conversations[user_id]) > MAX_HISTORY:
        _conversations[user_id] = _conversations[user_id][-MAX_HISTORY:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _conversations[user_id]

    if os.environ.get("OPENAI_API_KEY"):
        try:
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            response = client.chat.completions.create(
                model=cfg.OPENAI["model"],
                messages=messages,
                temperature=0.7,
                max_tokens=400,
                timeout=60,
            )
            reply = (response.choices[0].message.content or "").strip()
            _conversations[user_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as exc:
            log.warning("OpenAI falló (%s); intentando Groq si hay clave", exc)

    if os.environ.get("GROQ_API_KEY"):
        try:
            if _groq is None:
                _groq = Groq(api_key=os.environ["GROQ_API_KEY"])
            response = _groq.chat.completions.create(
                model=cfg.GROQ.get("model", "llama-3.3-70b-versatile"),
                messages=messages,
                temperature=0.7,
                max_tokens=400,
            )
            reply = (response.choices[0].message.content or "").strip()
            _conversations[user_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as exc:
            log.warning("Groq también falló: %s", exc)

    reply = (
        "No puedo responder ahora: configura OPENAI_API_KEY (recomendado) "
        "o GROQ_API_KEY como respaldo."
    )
    _conversations[user_id].append({"role": "assistant", "content": reply})
    return reply


# ─── Handlers ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _conversations[user_id] = []
    _rate_buckets[user_id].clear()
    _demo_states.pop(user_id, None)

    # Deep link desde landing: t.me/<bot>?start=demo
    args = context.args or []
    if args and args[0] == "demo":
        await _start_demo_flow(update.message.reply_text, user_id)
        return

    await update.message.reply_text(
        "👋 Soy *Pipeline_X*.\n\n"
        "Escribe qué empresas buscas y te entrego un PDF con leads calificados y mensajes listos.\n\n"
        "¿Por dónde empezamos?",
        parse_mode="Markdown",
        reply_markup=kb_start(),
    )


async def _start_demo_flow(reply_fn, user_id: int) -> None:
    """Inicia el flujo de demo — reutilizable desde /start y callbacks."""
    already_used = await asyncio.to_thread(_has_used_demo, user_id)
    if already_used:
        await reply_fn(
            "Ya usaste tu demo gratuita 🎯\n\nElige tu plan para seguir prospectando:",
            reply_markup=kb_planes(),
        )
        return
    _demo_states[user_id] = {"state": "waiting_target"}
    await reply_fn(
        "¿Qué tipo de empresa buscas y en qué ciudad?\n\n"
        "_Ej: Ferreterías en Trujillo · Clínicas en Bogotá · Logística en CDMX_",
        parse_mode="Markdown",
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _conversations[user_id] = []
    _demo_states.pop(user_id, None)
    await update.message.reply_text(
        "Conversación reiniciada. ¡Hola de nuevo! ¿En qué te puedo ayudar?",
        reply_markup=kb_start(),
    )


async def cmd_planes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Planes de Pipeline_X:",
        reply_markup=kb_planes(),
    )


async def _deliver_demo(chat_id: int, user_id: int, target: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Corre el pipeline y entrega el CSV de demo directamente en el chat.
    Llamado en un task separado para no bloquear el handler.
    """
    try:
        leads = await asyncio.to_thread(_run_pipeline_sync, target)
    except Exception as exc:
        log.error("Demo pipeline error user=%d target=%r: %s", user_id, target, exc)
        _demo_states.pop(user_id, None)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Hubo un problema procesando tu búsqueda.\n"
                "Intenta con otra ciudad o sector, o escríbeme para ayudarte."
            ),
        )
        return

    total = len(leads)
    qualified = sorted(
        [l for l in leads if l.get("lead_score", 0) >= 60],
        key=lambda x: x.get("lead_score", 0),
        reverse=True,
    )

    # Generar PDF demo
    from pdf_report import build_demo_pdf
    pdf_bytes = await asyncio.to_thread(build_demo_pdf, target, leads)
    safe_name = target[:30].replace(" ", "_").replace("/", "-")
    await context.bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(pdf_bytes),
        filename=f"pipeline_x_{safe_name}.pdf",
        caption=(
            f"✅ *{total} leads · {len(qualified)} calificados*\n"
            f"📄 Reporte demo — {target}"
        ),
        parse_mode="Markdown",
    )

    _demo_states[user_id] = {"state": "delivered", "target": target, "total": total}

    # Registrar que el usuario usó su demo gratuita
    await asyncio.to_thread(_record_demo_run, user_id, target)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "Esto es una muestra.\n\n"
            "*¿Quieres que te configuremos todo el sistema para que empieces a contactar hoy mismo?*\n\n"
            "Con Starter obtienes:\n"
            "— 30 leads por búsqueda · búsquedas ilimitadas\n"
            "— SUNAT · PDF completo · S/129/mes"
        ),
        parse_mode="Markdown",
        reply_markup=kb_post_demo(),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data    = query.data

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    send = lambda text, **kw: context.bot.send_message(chat_id=chat_id, text=text, **kw)

    # ── Entrada principal ─────────────────────────────────────────────────────
    if data == "start_demo":
        await _start_demo_flow(
            lambda text, **kw: send(text, **kw),
            user_id,
        )
        return

    if data == "start_planes":
        await send("Planes de Pipeline_X:", reply_markup=kb_planes())
        return

    if data == "start_info":
        if _is_rate_limited(user_id):
            await send("Vas muy rápido 🙂 Espera un momento.")
            return
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        reply = _get_reply(user_id, LABELS["start_info"])
        await send(reply, reply_markup=kb_start())
        return

    # ── Post-demo ─────────────────────────────────────────────────────────────
    if data == "demo_upgrade":
        _demo_states[user_id] = {**_demo_states.get(user_id, {}), "state": "collecting_email"}
        await send("Perfecto. ¿Cuál es tu email? Te activo el acceso hoy.")
        return

    if data == "demo_preguntas":
        _demo_states.pop(user_id, None)
        await send("Con gusto. ¿Qué quieres saber sobre Pipeline_X?")
        return

    if data == "demo_no_util":
        _demo_states.pop(user_id, None)
        await send(
            "Gracias por decírmelo.\n\n"
            "¿Qué esperabas ver que no estaba? Con eso puedo mostrarte algo más útil."
        )
        return

    # ── Planes ────────────────────────────────────────────────────────────────
    if data.startswith("plan_"):
        if _is_rate_limited(user_id):
            await send("Vas muy rápido 🙂 Espera un momento.")
            return
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        label = LABELS.get(data, data)
        reply = _get_reply(user_id, f"Quiero saber más sobre el plan {label}")
        await send(reply, reply_markup=kb_post_demo() if "free" not in data else kb_start())
        return

    # ── Fallback: cualquier otro texto libre va a Alex ────────────────────────
    if _is_rate_limited(user_id):
        await send("Vas muy rápido 🙂 Espera un momento.")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    reply = _get_reply(user_id, LABELS.get(data, data))
    await send(reply)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text    = (update.message.text or "").strip()

    demo = _demo_states.get(user_id, {})

    # ── Flujo demo: esperando target ──────────────────────────────────────────
    if demo.get("state") == "waiting_target":
        _demo_states[user_id] = {"state": "running", "target": text}
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"Buscando *{text}* en Google Maps y calificando con IA...\n"
                "_Listo en aprox. 2–5 minutos._"
            ),
            parse_mode="Markdown",
        )
        await context.bot.send_chat_action(chat_id=chat_id, action="upload_document")
        asyncio.create_task(_deliver_demo(chat_id, user_id, text, context))
        return

    # ── Flujo demo: capturando email post-entrega ─────────────────────────────
    if demo.get("state") == "collecting_email":
        email = text
        target = demo.get("target", "")
        _demo_states[user_id] = {**demo, "state": "done", "email": email}

        try:
            await asyncio.to_thread(_save_demo_lead, user_id, target, email)
        except Exception as exc:
            log.warning("No se pudo guardar demo lead: %s", exc)

        log.info("Demo email capturado: user=%d email=%s target=%r", user_id, email, target)

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"Listo. Te contactamos a *{email}* para activar tu acceso.\n\n"
                "Normalmente lo hacemos dentro de las 24 horas en horario hábil."
            ),
            parse_mode="Markdown",
        )

        # Notificar al admin sobre el nuevo lead
        await _notify_admin_demo_email(context, user_id, email, target)
        return

    # ── Bot de ventas Alex (flujo normal) ─────────────────────────────────────
    if _is_rate_limited(user_id):
        await update.message.reply_text(
            "Vas muy rápido 🙂 Espera un momento antes de continuar."
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply = _get_reply(user_id, text)
    except Exception as exc:
        log.error("Error generando respuesta para user %d: %s", user_id, exc)
        reply = "Tuve un problema técnico. Por favor intenta de nuevo en un momento."

    await update.message.reply_text(reply)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(embedded: bool = False) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN no está configurado")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("planes", cmd_planes))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Pipeline_X bot iniciado. Deep link demo: t.me/Pipeline_X_bot?start=demo")

    if embedded:
        import asyncio as _asyncio
        _asyncio.run(app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=()))
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
