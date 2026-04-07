"""
telegram_bot.py — Bot de ventas Pipeline_X en Telegram.

Asistente conversacional con IA (Groq) para calificar prospectos,
presentar el producto y cerrar la venta hacia el plan correcto.

Variables de entorno requeridas:
  TELEGRAM_BOT_TOKEN  — token de @BotFather
  GROQ_API_KEY        — clave de Groq (console.groq.com)

Uso:
  pip install python-telegram-bot groq
  python telegram_bot.py
"""

from __future__ import annotations

import logging
import os

from groq import Groq
from telegram import Update
from telegram.ext import (
    Application,
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

_groq = Groq(api_key=os.environ["GROQ_API_KEY"])

# ─── System prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
Eres Alex, el asistente de ventas de Pipeline_X.

Pipeline_X es una plataforma de IA que automatiza la prospección de clientes
para MIPYME en Latinoamérica. Busca leads en Google Maps, los califica con IA
(score 0–100), y genera mensajes de outreach personalizados por industria.

PLANES:
- Starter  $39/mes — 200 leads, canal email
- Pro       $89/mes — 1.000 leads, email + WhatsApp, acceso API  ← más popular
- Agency   $199/mes — leads ilimitados, multi-cuenta, soporte dedicado

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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLUJO DE CONVERSACIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ETAPA 1 — BIENVENIDA
Cuando el usuario escribe /start o llega por primera vez:
Saluda brevemente, preséntate y pregunta: ¿A qué se dedica tu empresa?

ETAPA 2 — CALIFICACIÓN (máximo 3 preguntas en total)
Según la respuesta, pregunta 1 o 2 cosas más:
- ¿Cuántos clientes nuevos intentas conseguir por mes?
- ¿Cómo consigues tus leads hoy? (referidos, publicidad, manual, LinkedIn…)

ETAPA 3 — DESCUBRIMIENTO DEL DOLOR
Identifica el dolor principal según lo que dijo:
- "Pierdo mucho tiempo buscando leads"        → énfasis en scraping automático
- "No sé si mis leads son buenos"              → énfasis en score IA 0-100
- "No tengo tiempo para escribir mensajes"     → énfasis en borradores personalizados
- "Somos equipo pequeño / solo yo en ventas"   → énfasis en escala sin contratar
- "Uso Excel / hoja de cálculo"                → énfasis en pipeline estructurado + CSV

ETAPA 4 — PRESENTACIÓN DE VALOR
Conecta el dolor con Pipeline_X usando 2-3 beneficios concretos para SU industria.
Usa siempre un ejemplo específico con su ciudad o sector si lo mencionó.

Ejemplos por industria:
- Retail Lima       → "En 10 minutos puedes tener 50 bodegas o tiendas calificadas con su email y el primer mensaje listo."
- Logística Bogotá  → "Pipeline_X identifica transportistas y operadores logísticos con score alto y redacta el email mencionando costos operativos."
- Construcción      → "Detecta constructoras con facturas pendientes y genera mensajes enfocados en flujo de caja en obra."
- Servicios B2B     → "Cualquier industria en Google Maps: buscas, calificas y contactas sin tocar una hoja de cálculo."

ETAPA 5 — MANEJO DE OBJECIONES

"Es muy caro / no tengo presupuesto"
→ "Un SDR humano en LATAM cuesta entre $800 y $1.500/mes. Pipeline_X hace lo mismo desde $39. ¿Cuánto vale para ti conseguir 10 clientes nuevos al mes?"

"No tengo tiempo para aprenderlo"
→ "Son 3 pasos: escribes la búsqueda, esperás 2 minutos y recibes el CSV con leads calificados y mensajes listos. Sin configuración."

"¿Funciona para mi industria?"
→ "Si está en Google Maps, Pipeline_X lo encuentra. Hemos probado retail, logística, construcción, salud, servicios y más."

"¿Cómo sé que la IA califica bien?"
→ "Cada lead tiene score 0–100 con justificación: por qué calificó, cuál es el bloqueador y cuál es la siguiente acción. Tú decides a quién contactar."

"Necesito pensarlo"
→ "Entiendo. ¿Qué información te ayudaría a decidir? Puedo mostrarte un ejemplo con tu industria ahora mismo."

ETAPA 6 — CIERRE

Según el tamaño y necesidad:
- 1–5 personas o solo quien vende: recomienda Starter ($39/mes)
- Equipo de ventas de 5–20 personas o necesita API: recomienda Pro ($89/mes)
- Agencia o maneja múltiples clientes: recomienda Agency ($199/mes)

Frase de cierre: "¿Quieres que te arme una demo con leads reales de [su industria]? Te muestro el resultado en vivo."

Si el prospecto dice que quiere comprar o pedir acceso:
→ "Perfecto. Escríbeme a contacto@pipelinex.io con asunto 'Acceso [Plan]' y te activamos hoy mismo."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLAS ABSOLUTAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Nunca inventes funcionalidades que no existen.
2. Nunca prometas resultados garantizados ("vas a conseguir 100 clientes").
3. No menciones competidores.
4. Si preguntan algo técnico que no sabes, di "déjame confirmarte eso" y ofrece una demo.
5. Mantén siempre el foco en el dolor del prospecto, no en las features del producto.
"""

# ─── Conversation store (in-memory) ─────────────────────────────────────────

# { user_id: [{"role": "user"|"assistant", "content": "..."}] }
_conversations: dict[int, list[dict]] = {}
MAX_HISTORY = 20  # mensajes por usuario (se trunca al más antiguo)


def _get_reply(user_id: int, user_message: str) -> str:
    """Genera respuesta con Groq manteniendo el historial de la conversación."""
    if user_id not in _conversations:
        _conversations[user_id] = []

    _conversations[user_id].append({"role": "user", "content": user_message})

    # Mantener historial dentro del límite
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
    """Inicia o reinicia la conversación."""
    user_id = update.effective_user.id
    _conversations[user_id] = []  # reset

    reply = _get_reply(user_id, "/start")
    await update.message.reply_text(reply)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reinicia el historial del usuario."""
    user_id = update.effective_user.id
    _conversations[user_id] = []
    await update.message.reply_text("Conversación reiniciada. ¡Hola de nuevo! ¿A qué se dedica tu empresa?")


async def cmd_planes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra los planes directamente."""
    text = (
        "📋 *Planes Pipeline_X*\n\n"
        "— *Starter* $39/mes: 200 leads, email\n"
        "— *Pro* $89/mes: 1.000 leads, email + WhatsApp, API ⭐\n"
        "— *Agency* $199/mes: ilimitado, multi-cuenta\n\n"
        "¿Cuál se ajusta mejor a tu equipo?"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja mensajes de texto normales."""
    user_id = update.effective_user.id
    text = update.message.text

    # Mostrar "escribiendo..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Pipeline_X bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
