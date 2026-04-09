"""
telegram_bot.py — Bot de ventas Pipeline_X en Telegram.

Asistente conversacional con IA (Groq) + botones inline para agilizar el flujo.

Variables de entorno requeridas:
  TELEGRAM_BOT_TOKEN  — token de @BotFather
  GROQ_API_KEY        — clave de Groq (console.groq.com)

Uso:
  pip install -r requirements_bot.txt
  python telegram_bot.py
"""

from __future__ import annotations

import logging
import os

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
    """Inicialización lazy del cliente Groq — no crashea al importar sin API key."""
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

PLANES:
- Starter  $39/mes — 200 negocios/mes, canal email
- Pro       $89/mes — 1.000 negocios/mes, email + WhatsApp, acceso API  ← más popular
- Agency   $199/mes — negocios ilimitados, multi-cuenta, soporte dedicado

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
→ "Un SDR humano cuesta $800–1.500/mes. Pipeline_X desde $39. ¿Cuánto vale conseguir 10 clientes nuevos?"

"No tengo tiempo para aprenderlo"
→ "3 pasos: escribes la búsqueda, esperás 2 min, recibes el CSV con leads y mensajes. Sin config."

"¿Funciona para mi industria?"
→ "Si está en Google Maps, Pipeline_X lo encuentra. Retail, logística, salud, construcción y más."

"¿Cómo sé que la IA califica bien?"
→ "Cada lead tiene score 0–100 con justificación: por qué calificó, bloqueador y siguiente acción."

"Necesito pensarlo"
→ "Entiendo. ¿Qué información te ayudaría a decidir? Puedo mostrarte un ejemplo con tu industria."

ETAPA 6 — CIERRE

Según el tamaño:
- 1–5 personas: recomienda Starter ($39/mes)
- Equipo de ventas o necesita API: recomienda Pro ($89/mes)
- Agencia o multi-cliente: recomienda Agency ($199/mes)

Si quiere comprar: "Escríbeme a contacto@pipelinex.io con asunto 'Acceso [Plan]' y te activamos hoy."
Si quiere demo: "¿Cuándo tienes 20 minutos? Agendamos una llamada rápida."

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
        [InlineKeyboardButton("Starter — $39/mes", callback_data="plan_starter")],
        [InlineKeyboardButton("⭐ Pro — $89/mes (más popular)", callback_data="plan_pro")],
        [InlineKeyboardButton("Agency — $199/mes", callback_data="plan_agency")],
        [InlineKeyboardButton("💬 Tengo dudas", callback_data="plan_dudas")],
    ])

def kb_cierre() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Quiero acceso ahora", callback_data="cierre_acceso")],
        [InlineKeyboardButton("📅 Agendar demo en vivo", callback_data="cierre_demo")],
        [InlineKeyboardButton("💬 Tengo más preguntas", callback_data="cierre_preguntas")],
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
    "plan_starter":     "Starter $39/mes",
    "plan_pro":         "Pro $89/mes",
    "plan_agency":      "Agency $199/mes",
    "plan_dudas":       "Tengo dudas sobre los planes",
    "cierre_acceso":    "Quiero acceso ahora",
    "cierre_demo":      "Quiero agendar una demo en vivo",
    "cierre_preguntas": "Tengo más preguntas",
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
    "plan_starter":     kb_cierre,
    "plan_pro":         kb_cierre,
    "plan_agency":      kb_cierre,
    "plan_dudas":       None,
    "cierre_acceso":    None,
    "cierre_demo":      None,
    "cierre_preguntas": kb_planes,
}

# ─── Conversation store ───────────────────────────────────────────────────────

_conversations: dict[int, list[dict]] = {}
MAX_HISTORY = 20


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

    reply = _get_reply(user_id, "/start")
    await update.message.reply_text(reply, reply_markup=kb_industrias())


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _conversations[user_id] = []
    await update.message.reply_text(
        "Conversación reiniciada. ¡Hola de nuevo! ¿En qué industria trabaja tu empresa?",
        reply_markup=kb_industrias(),
    )


async def cmd_planes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Aquí están los planes de Pipeline_X:",
        reply_markup=kb_planes(),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja los botones inline."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    label = LABELS.get(data, data)

    # Editar el mensaje original para mostrar qué eligió el usuario
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

    reply = _get_reply(user_id, label)

    # Determinar qué teclado mostrar a continuación
    next_kb_fn = NEXT_KB.get(data)
    reply_markup = next_kb_fn() if next_kb_fn else None

    # Casos especiales de cierre
    if data == "cierre_acceso":
        reply_markup = None
    elif data == "cierre_demo":
        reply_markup = None

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=reply,
        reply_markup=reply_markup,
    )

    # Después del proceso actual, mostrar planes si el AI menciona precios
    if data in ("proc_manual", "proc_ads", "proc_referidos", "proc_ninguno"):
        # Enviar botones de planes después de que el AI presente el valor
        followup = _get_reply(user_id, "Muéstrame los planes disponibles")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=followup,
            reply_markup=kb_planes(),
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja mensajes de texto libre."""
    user_id = update.effective_user.id
    text = update.message.text

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = _get_reply(user_id, text)
    except Exception as e:
        log.error("Error generando respuesta para user %d: %s", user_id, e)
        reply = "Tuve un problema técnico. Por favor intenta de nuevo en un momento."

    await update.message.reply_text(reply)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN no está configurado")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("planes", cmd_planes))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Pipeline_X bot iniciado con botones inline.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
