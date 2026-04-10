"""
telegram_bot.py — Bot de ventas Pipeline_X en Telegram.

Asistente conversacional con IA (Groq/Claude) + flujo de demo en vivo.

Flujos:
  /start            → Alex (bot de ventas conversacional)
  /start demo       → Demo en vivo: pide target → corre pipeline → entrega CSV → captura email
  /reset            → Reinicia conversación
  /planes           → Muestra planes disponibles

Variables de entorno requeridas:
  TELEGRAM_BOT_TOKEN  — token de @BotFather
  GROQ_API_KEY        — clave de Groq (console.groq.com)
  ANTHROPIC_API_KEY   — opcional, Claude como LLM primario

Deep link para landing:
  t.me/<botname>?start=demo
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import sys
import time as _time
from collections import defaultdict, deque

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
log = logging.getLogger("pipeline_x_bot")

# ─── Groq client ─────────────────────────────────────────────────────────────

def _get_groq_client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY no está configurada en las variables de entorno.")
    return Groq(api_key=api_key)

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
- Free      $0      — 10 leads gratis, sin tarjeta
- Solo      $19/mes — 30 leads, para freelancers
- Starter   $39/mes — 200 leads  ← tier principal
- Pro       $79/mes — 500 leads, acceso API
- Reseller  $299/mes — 1.000 leads, white-label, multi-cuenta (para agencias)
- Anual: Starter por $390/año (2 meses gratis)
- Precio fundador: $29/mes para los primeros 20 clientes (mismas features que Starter)

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
→ "Un SDR humano cuesta $700–900/mes. Pipeline_X desde $39. ¿Cuánto vale conseguir 10 clientes nuevos?"

"No tengo tiempo para aprenderlo"
→ "3 pasos: escribes la búsqueda, esperás 2 min, recibes el CSV con leads y mensajes. Sin config."

"¿Funciona para mi industria?"
→ "Si está en Google Maps, Pipeline_X lo encuentra. Retail, logística, salud, construcción y más."

"¿Cómo sé que la IA califica bien?"
→ "Cada lead tiene score 0–100 con justificación: por qué calificó, bloqueador y siguiente acción."

"Necesito pensarlo"
→ "Entiendo. ¿Qué información te ayudaría a decidir? Puedo generarte 10 leads reales de tu industria ahora mismo."

ETAPA 6 — CIERRE

Según el tamaño:
- 1 persona / freelancer: recomienda Solo ($19/mes)
- Equipo pequeño: recomienda Starter ($39/mes)
- Equipo de ventas: recomienda Pro ($79/mes)
- Agencia o multi-cliente: recomienda Reseller ($299/mes)

Si quiere comprar: "Escríbeme a contacto@pipelinex.io con asunto 'Acceso [Plan]' y te activamos hoy."
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

def kb_industrias() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Retail / Comercio", callback_data="ind_retail"),
         InlineKeyboardButton("🚛 Logística", callback_data="ind_logistica")],
        [InlineKeyboardButton("🏗️ Construcción", callback_data="ind_construccion"),
         InlineKeyboardButton("💼 Servicios B2B", callback_data="ind_servicios")],
        [InlineKeyboardButton("🏥 Salud", callback_data="ind_salud"),
         InlineKeyboardButton("📦 Otro", callback_data="ind_otro")],
    ])

def kb_volumen() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1–10 leads/mes", callback_data="vol_bajo"),
         InlineKeyboardButton("10–50 leads/mes", callback_data="vol_medio")],
        [InlineKeyboardButton("50+ leads/mes", callback_data="vol_alto")],
    ])

def kb_proceso() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Manual / Excel", callback_data="proc_manual"),
         InlineKeyboardButton("📣 LinkedIn / Ads", callback_data="proc_ads")],
        [InlineKeyboardButton("🤝 Referidos", callback_data="proc_referidos"),
         InlineKeyboardButton("❓ Sin proceso definido", callback_data="proc_ninguno")],
    ])

def kb_planes() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Solo — $19/mes (30 leads)", callback_data="plan_solo")],
        [InlineKeyboardButton("⭐ Starter — $39/mes (200 leads)", callback_data="plan_starter")],
        [InlineKeyboardButton("Pro — $79/mes (500 leads)", callback_data="plan_pro")],
        [InlineKeyboardButton("Reseller — $299/mes (agencias)", callback_data="plan_reseller")],
        [InlineKeyboardButton("💬 Tengo dudas", callback_data="plan_dudas")],
    ])

def kb_cierre() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Quiero acceso ahora", callback_data="cierre_acceso")],
        [InlineKeyboardButton("👀 Ver demo en vivo", callback_data="cierre_demo")],
        [InlineKeyboardButton("💬 Tengo más preguntas", callback_data="cierre_preguntas")],
    ])

def kb_post_demo() -> InlineKeyboardMarkup:
    """Teclado que aparece después de entregar los 10 leads de demo."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Quiero los 200 leads completos", callback_data="demo_upgrade")],
        [InlineKeyboardButton("💬 Tengo preguntas", callback_data="demo_preguntas")],
        [InlineKeyboardButton("👎 No me fue útil", callback_data="demo_no_util")],
    ])


# ─── Etiquetas legibles de callbacks ─────────────────────────────────────────

LABELS: dict[str, str] = {
    "ind_retail":       "Retail / Comercio",
    "ind_logistica":    "Logística",
    "ind_construccion": "Construcción",
    "ind_servicios":    "Servicios B2B",
    "ind_salud":        "Salud",
    "ind_otro":         "Otra industria",
    "vol_bajo":         "1–10 leads al mes",
    "vol_medio":        "10–50 leads al mes",
    "vol_alto":         "Más de 50 leads al mes",
    "proc_manual":      "Manual / Excel",
    "proc_ads":         "LinkedIn / Publicidad",
    "proc_referidos":   "Referidos",
    "proc_ninguno":     "Sin proceso definido",
    "plan_solo":        "Solo $19/mes",
    "plan_starter":     "Starter $39/mes",
    "plan_pro":         "Pro $79/mes",
    "plan_reseller":    "Reseller $299/mes",
    "plan_dudas":       "Tengo dudas sobre los planes",
    "cierre_acceso":    "Quiero acceso ahora",
    "cierre_demo":      "Quiero ver una demo en vivo",
    "cierre_preguntas": "Tengo más preguntas",
    "demo_upgrade":     "Quiero los 200 leads completos",
    "demo_preguntas":   "Tengo preguntas sobre la demo",
    "demo_no_util":     "No me fue útil",
}

# Qué teclado mostrar después de cada grupo de callback
NEXT_KB: dict[str, callable] = {
    "ind_retail":       kb_volumen,
    "ind_logistica":    kb_volumen,
    "ind_construccion": kb_volumen,
    "ind_servicios":    kb_volumen,
    "ind_salud":        kb_volumen,
    "ind_otro":         kb_volumen,
    "vol_bajo":         kb_proceso,
    "vol_medio":        kb_proceso,
    "vol_alto":         kb_proceso,
    "proc_manual":      None,
    "proc_ads":         None,
    "proc_referidos":   None,
    "proc_ninguno":     None,
    "plan_solo":        kb_cierre,
    "plan_starter":     kb_cierre,
    "plan_pro":         kb_cierre,
    "plan_reseller":    kb_cierre,
    "plan_dudas":       None,
    "cierre_acceso":    None,
    "cierre_demo":      None,
    "cierre_preguntas": kb_planes,
    "demo_upgrade":     None,
    "demo_preguntas":   None,
    "demo_no_util":     None,
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
    import config as cfg

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


def _leads_to_csv_bytes(leads: list[dict]) -> bytes:
    if not leads:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(leads[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(leads)
    return buf.getvalue().encode("utf-8-sig")  # BOM para Excel


def _save_demo_lead(user_id: int, target: str, email: str) -> None:
    """Persiste el email capturado post-demo en el mismo store que /demo-request."""
    import json
    from pathlib import Path
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
        "nombre":   "",
        "empresa":  "",
        "ruc":      "",
        "email":    email,
        "industria": target,
        "ciudad":   "",
        "ip":       f"telegram:{user_id}",
        "ts":       datetime.now(timezone.utc).isoformat(),
        "status":   "demo_telegram",
    })
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── LLM reply ───────────────────────────────────────────────────────────────

def _get_reply(user_id: int, user_message: str) -> str:
    global _groq
    if _groq is None:
        _groq = _get_groq_client()

    if user_id not in _conversations:
        _conversations[user_id] = []

    _conversations[user_id].append({"role": "user", "content": user_message})

    if len(_conversations[user_id]) > MAX_HISTORY:
        _conversations[user_id] = _conversations[user_id][-MAX_HISTORY:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _conversations[user_id]

    response = _groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.7,
        max_tokens=400,
    )

    reply = response.choices[0].message.content.strip()
    _conversations[user_id].append({"role": "assistant", "content": reply})
    return reply


# ─── Handlers ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _conversations[user_id] = []
    _rate_buckets[user_id].clear()
    _demo_states.pop(user_id, None)

    # Deep link: t.me/<bot>?start=demo
    args = context.args or []
    if args and args[0] == "demo":
        _demo_states[user_id] = {"state": "waiting_target"}
        await update.message.reply_text(
            "Hola 👋 Voy a generarte *10 leads reales* ahora mismo, sin tarjeta.\n\n"
            "¿Qué tipo de empresa estás prospectando?\n"
            "_Ej: Ferreterías en Trujillo · Clínicas en Bogotá · Logística en CDMX_",
            parse_mode="Markdown",
        )
        return

    reply = _get_reply(user_id, "/start")
    await update.message.reply_text(reply, reply_markup=kb_industrias())


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _conversations[user_id] = []
    _demo_states.pop(user_id, None)
    await update.message.reply_text(
        "Conversación reiniciada. ¡Hola de nuevo! ¿En qué industria trabaja tu empresa?",
        reply_markup=kb_industrias(),
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

    # Resumen top 3
    lines = [
        f"✅ *{total} leads de {target}*",
        f"_{len(qualified)} calificados (score ≥60)_\n",
    ]
    for i, lead in enumerate(qualified[:3], 1):
        empresa = lead.get("empresa", "—")
        score   = lead.get("lead_score", "—")
        action  = lead.get("next_action", "—")
        lines.append(f"*{i}. {empresa}* — Score {score}")
        lines.append(f"   → {action}")
    if not qualified:
        lines.append("_No se encontraron leads con score ≥60. Revisa el CSV adjunto._")
    lines.append("\n📎 CSV adjunto con todos los leads y borradores de mensaje.")

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="Markdown",
    )

    # Enviar CSV
    csv_bytes = _leads_to_csv_bytes(leads)
    safe_name = target[:30].replace(" ", "_").replace("/", "-")
    await context.bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(csv_bytes),
        filename=f"pipeline_x_{safe_name}.csv",
        caption=f"📊 Demo gratuita — {target}",
    )

    _demo_states[user_id] = {"state": "delivered", "target": target, "total": total}

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "Esto es el *10% de lo que Pipeline_X entrega en Starter.*\n\n"
            "Con el plan completo ($39/mes):\n"
            "- 200 leads/mes en vez de 10\n"
            "- Enriquecimiento SUNAT (capacidad de pago real)\n"
            "- Reporte HTML con métricas\n\n"
            "¿Qué querés hacer?"
        ),
        parse_mode="Markdown",
        reply_markup=kb_post_demo(),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id  = query.from_user.id
    chat_id  = query.message.chat_id
    data     = query.data
    label    = LABELS.get(data, data)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    # ── Callbacks del flujo demo ──────────────────────────────────────────────
    if data == "demo_upgrade":
        _demo_states[user_id] = {**_demo_states.get(user_id, {}), "state": "collecting_email"}
        await context.bot.send_message(
            chat_id=chat_id,
            text="Perfecto. ¿Cuál es tu email? Te activo el acceso hoy.",
        )
        return

    if data == "demo_preguntas":
        _demo_states.pop(user_id, None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Con gusto. ¿Qué quieres saber sobre Pipeline_X?",
        )
        return

    if data == "demo_no_util":
        _demo_states.pop(user_id, None)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Gracias por decírmelo — me ayuda a mejorar.\n\n"
                "¿Qué esperabas ver que no estaba? "
                "Con ese dato puedo mostrarte algo más relevante para tu caso."
            ),
        )
        return

    if data == "cierre_demo":
        # El usuario quiere demo desde el flujo de ventas → activar flujo demo
        _demo_states[user_id] = {"state": "waiting_target"}
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Perfecto. ¿Qué tipo de empresa estás prospectando?\n"
                "_Ej: Ferreterías en Trujillo · Clínicas en Bogotá_"
            ),
            parse_mode="Markdown",
        )
        return

    # ── Callbacks normales del flujo de ventas ────────────────────────────────
    if _is_rate_limited(user_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text="Vas muy rápido 🙂 Espera un momento antes de continuar.",
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    reply = _get_reply(user_id, label)

    next_kb_fn = NEXT_KB.get(data)
    reply_markup = next_kb_fn() if next_kb_fn else None

    await context.bot.send_message(
        chat_id=chat_id,
        text=reply,
        reply_markup=reply_markup,
    )

    # Mostrar planes después del dolor
    if data in ("proc_manual", "proc_ads", "proc_referidos", "proc_ninguno"):
        followup = _get_reply(user_id, "Muéstrame los planes disponibles")
        await context.bot.send_message(
            chat_id=chat_id,
            text=followup,
            reply_markup=kb_planes(),
        )


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
                "Normalmente lo hacemos en menos de 2 horas en horario hábil."
            ),
            parse_mode="Markdown",
        )
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
