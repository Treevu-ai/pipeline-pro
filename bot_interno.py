"""
bot_interno.py — Asistente interno de gestión Pipeline_X (PipeAssist).

Acceso exclusivo: ADMIN_CHAT_ID.

Comandos:
  /pipeline <query> [--limit N] [--channel X]  — Scrape + calificación → CSV
  /buscar <query> [--limit N]                  — Solo scrape, sin LLM
  /historial [N]                               — Últimas N ejecuciones (default: 5)
  /top [N]                                     — Top N leads por score (default: 10)
  /calificados                                 — Leads en etapa "Calificado"
  /seguimiento                                 — Leads "En seguimiento"
  /stats [run_id]                              — Estadísticas del run
  /csv [run_id]                                — Reenvía el CSV de un run
  /status                                      — Estado del sistema
  /test                                        — Test rápido del LLM
  /help                                        — Lista de comandos

Texto libre → asistente LLM con contexto del último pipeline.

Variables de entorno:
  TELEGRAM_BOT_TOKEN_INTERNO  — token del bot
  ADMIN_CHAT_ID               — tu Telegram chat_id
  GROQ_API_KEY / ANTHROPIC_API_KEY
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

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
log = logging.getLogger("pipeassist")

# ─── Auth ────────────────────────────────────────────────────────────────────

def _get_admin_id() -> int | None:
    raw = os.environ.get("ADMIN_CHAT_ID", "")
    return int(raw) if raw.strip().lstrip("-").isdigit() else None


def _is_admin(update: Update) -> bool:
    admin_id = _get_admin_id()
    return admin_id is not None and update.effective_user.id == admin_id


async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ Acceso no autorizado.")


# ─── Historial de runs ────────────────────────────────────────────────────────

_HISTORY_FILE = Path("output/.pipeassist_history.json")
_MAX_HISTORY  = 10  # runs guardados


def _load_history() -> list[dict]:
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(history: list[dict]) -> None:
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(
            json.dumps(history[-_MAX_HISTORY:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("No se pudo guardar historial: %s", e)


def _add_run(query: str, leads: list[dict], kind: str = "pipeline") -> dict:
    """Agrega un run al historial y devuelve el run guardado."""
    history = _load_history()
    run = {
        "run_id":    str(uuid.uuid4())[:8],
        "kind":      kind,
        "query":     query,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total":     len(leads),
        "leads":     leads,
    }
    history.append(run)
    _save_history(history)
    return run


def _get_run(run_id: str | None) -> dict | None:
    """Devuelve el run por ID o el último si run_id es None."""
    history = _load_history()
    if not history:
        return None
    if run_id is None:
        return history[-1]
    for run in reversed(history):
        if run["run_id"] == run_id:
            return run
    return None


# ─── Helpers de pipeline ─────────────────────────────────────────────────────

def _run_scrape_sync(query: str, limit: int) -> list[dict]:
    from scraper import scrape_google_maps, enrich_leads
    leads = scrape_google_maps(query, limit)
    return enrich_leads(leads)


def _run_qualify_sync(leads: list[dict], channel: str) -> list[dict]:
    from sdr_agent import qualify_row, pre_score
    import config as cfg
    results = []
    for lead in leads:
        base_score = pre_score(lead)
        try:
            result = qualify_row(lead, channel, base_score)
            result["qualify_error"] = ""
        except Exception as e:
            result = {k: "" for k in cfg.OUTPUT_KEYS if k != "qualify_error"}
            result["qualify_error"] = str(e)
        results.append({**lead, **result})
    return results


def _leads_to_csv(leads: list[dict]) -> bytes:
    if not leads:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(leads[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(leads)
    return buf.getvalue().encode("utf-8-sig")


# ─── Parseo de flags ──────────────────────────────────────────────────────────

def _parse_flags(text: str) -> tuple[str, int, str]:
    """Extrae (query, limit, channel) de un texto con flags opcionales."""
    limit, channel = 20, "whatsapp"
    m = re.search(r"--limit\s+(\d+)", text)
    if m:
        limit = min(int(m.group(1)), 50)
        text = text[:m.start()] + text[m.end():]
    m = re.search(r"--channel\s+(email|whatsapp|both)", text)
    if m:
        channel = m.group(1)
        text = text[:m.start()] + text[m.end():]
    return text.strip(), limit, channel


# ─── Estadísticas ─────────────────────────────────────────────────────────────

def _stats_text(run: dict) -> str:
    leads = run["leads"]
    total = len(leads)
    if total == 0:
        return "Sin leads en este run."

    scored = [l for l in leads if isinstance(l.get("lead_score"), (int, float))]
    scores = [int(l["lead_score"]) for l in scored]

    avg  = round(sum(scores) / len(scores), 1) if scores else 0
    high = sum(1 for s in scores if s >= 70)
    mid  = sum(1 for s in scores if 50 <= s < 70)
    low  = sum(1 for s in scores if s < 50)

    stages = Counter(l.get("crm_stage", "—") for l in leads)
    industries = Counter(l.get("industria", l.get("categoria", "—")) for l in leads if l.get("industria") or l.get("categoria"))
    emails = sum(1 for l in leads if l.get("email"))
    phones = sum(1 for l in leads if l.get("telefono"))
    sites  = sum(1 for l in leads if l.get("sitio_web"))

    ts = run["timestamp"][:16].replace("T", " ")
    lines = [
        f"📊 *Stats — {run['query']}*",
        f"_Run `{run['run_id']}` · {ts}_\n",
        f"*Total leads:* {total}",
        f"*Score promedio:* {avg}",
        f"*Score ≥70:* {high}  |  50–69: {mid}  |  <50: {low}\n",
        "*Etapas CRM:*",
    ]
    for stage, count in stages.most_common():
        lines.append(f"  • {stage}: {count}")

    if industries:
        lines.append("\n*Industrias:*")
        for ind, count in industries.most_common(5):
            lines.append(f"  • {ind}: {count}")

    lines += [
        f"\n*Cobertura de contacto:*",
        f"  📧 Email: {emails}/{total}",
        f"  📞 Teléfono: {phones}/{total}",
        f"  🌐 Sitio web: {sites}/{total}",
    ]
    return "\n".join(lines)


# ─── Resumen de leads ──────────────────────────────────────────────────────────

def _leads_text(leads: list[dict], title: str, max_show: int = 10) -> str:
    if not leads:
        return f"_{title}: sin resultados._"

    top = sorted(leads, key=lambda x: x.get("lead_score", 0), reverse=True)[:max_show]
    lines = [f"*{title}* ({len(leads)} leads)\n"]

    for i, lead in enumerate(top, 1):
        empresa = lead.get("empresa", "—")
        score   = lead.get("lead_score", "—")
        stage   = lead.get("crm_stage", "—")
        action  = lead.get("next_action", "—")
        email   = lead.get("email", "")
        tel     = lead.get("telefono", "")
        city    = lead.get("ciudad", "")

        contact = " | ".join(filter(None, [city, email or tel]))
        lines.append(f"*{i}. {empresa}*  — Score {score} · {stage}")
        if contact:
            lines.append(f"   {contact}")
        lines.append(f"   → {action}")

    if len(leads) > max_show:
        lines.append(f"\n_... y {len(leads) - max_show} más. Usa /csv para el listado completo._")

    return "\n".join(lines)


# ─── Keyboard de acciones rápidas ────────────────────────────────────────────

def _kb_after_pipeline(run_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data=f"stats:{run_id}"),
            InlineKeyboardButton("🏆 Top 10", callback_data=f"top10:{run_id}"),
        ],
        [
            InlineKeyboardButton("✅ Calificados", callback_data=f"cal:{run_id}"),
            InlineKeyboardButton("📎 CSV", callback_data=f"csv:{run_id}"),
        ],
    ])


def _kb_historial(runs: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for run in reversed(runs[-5:]):
        ts    = run["timestamp"][5:16].replace("T", " ")
        label = f"{ts} · {run['query'][:22]} ({run['total']})"
        rows.append([InlineKeyboardButton(label, callback_data=f"run:{run['run_id']}")])
    return InlineKeyboardMarkup(rows)


# ─── LLM conversacional ───────────────────────────────────────────────────────

_ASSISTANT_SYSTEM = """
Eres PipeAssist, el asistente interno de gestión de Pipeline_X.
Ayudas al administrador a analizar resultados de su pipeline de prospección B2B.

CONTEXTO — qué es Pipeline_X:
Pipeline_X busca y califica NEGOCIOS (empresas, comercios, pymes) en Google Maps.
NO busca personas individuales. Cada "lead" es un negocio real con nombre, dirección,
teléfono, reseñas y email. El objetivo es contactar a esos negocios para venderles Pipeline_X.

DATOS DEL ÚLTIMO PIPELINE:
{context}

REGLAS:
- Responde en español neutro, máximo 5 líneas.
- Si te preguntan sobre leads, recuerda que son negocios, no personas.
- Si el usuario quiere ejecutar una acción (nuevo pipeline, filtrar, ver CSV),
  indícale el comando: /pipeline, /top, /calificados, /csv, /stats.
- No inventes datos que no estén en el contexto.
""".strip()


def _build_context(run: dict | None) -> str:
    if run is None:
        return "No hay datos de pipeline. Ejecuta /pipeline para comenzar."

    leads = run["leads"]
    total = len(leads)
    scored = [l for l in leads if isinstance(l.get("lead_score"), (int, float))]
    scores = [int(l["lead_score"]) for l in scored]
    avg = round(sum(scores) / len(scores), 1) if scores else 0

    stages = Counter(l.get("crm_stage", "—") for l in leads)
    top3 = sorted(scored, key=lambda x: x["lead_score"], reverse=True)[:3]

    top3_lines = "\n".join(
        f"  - {l.get('empresa','?')} score={l['lead_score']} stage={l.get('crm_stage','?')}"
        for l in top3
    )

    return (
        f"Run: {run['run_id']} | Query: {run['query']} | Fecha: {run['timestamp'][:16]}\n"
        f"Total leads: {total} | Score promedio: {avg}\n"
        f"Etapas: {dict(stages)}\n"
        f"Top 3 leads:\n{top3_lines}"
    )


def _llm_chat(user_text: str, context: str) -> str:
    system = _ASSISTANT_SYSTEM.format(context=context)

    # Anthropic primero
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            import config as cfg
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            resp = client.messages.create(
                model=cfg.CLAUDE["model"],
                max_tokens=300,
                system=system,
                messages=[{"role": "user", "content": user_text}],
                temperature=1,
            )
            return resp.content[0].text.strip() if resp.content else ""
        except Exception:
            pass

    # Groq fallback
    if os.environ.get("GROQ_API_KEY"):
        try:
            from groq import Groq
            client = Groq(api_key=os.environ["GROQ_API_KEY"])
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.5,
                max_tokens=300,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            pass

    return "Sin LLM disponible. Configura ANTHROPIC_API_KEY o GROQ_API_KEY."


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    text = (
        "🤖 *PipeAssist — Tu asistente de pipeline*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔍 *BUSCAR NEGOCIOS*\n"
        "━━━━━━━━━━━━━━━━\n"
        "`/pipeline` _sector ciudad_ — Busca, califica y te entrega el CSV\n"
        "Ej: `/pipeline Ferreterías Lima`\n"
        "Ej: `/pipeline Restaurantes Miraflores --limit 30`\n\n"
        "`/buscar` _sector ciudad_ — Solo busca, sin calificar (más rápido)\n"
        "Ej: `/buscar Clínicas Trujillo`\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📊 *VER RESULTADOS*\n"
        "━━━━━━━━━━━━━━━━\n"
        "`/top` — Los mejores negocios del último pipeline\n"
        "`/calificados` — Negocios listos para contactar\n"
        "`/seguimiento` — Negocios que necesitan seguimiento\n"
        "`/stats` — Resumen estadístico del último pipeline\n"
        "`/csv` — Descargar el archivo Excel/CSV\n"
        "`/historial` — Ver tus búsquedas anteriores\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚙️ *OPCIONES EXTRA*\n"
        "━━━━━━━━━━━━━━━━\n"
        "`--limit 30` — Cuántos negocios buscar (máx 50, default 20)\n"
        "`--channel whatsapp` — Genera mensajes para WhatsApp\n"
        "`--channel email` — Genera mensajes para email\n\n"
        "💬 También puedes escribirme en texto libre:\n"
        "_\"¿Cuántos leads calificados tengo?\"_\n"
        "_\"¿Cuál es el mejor negocio para contactar?\"_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    groq   = "✅" if os.environ.get("GROQ_API_KEY") else "❌"
    claude = "✅" if os.environ.get("ANTHROPIC_API_KEY") else "—"
    token  = "✅" if os.environ.get("TELEGRAM_BOT_TOKEN_INTERNO") else "❌"
    admin  = str(_get_admin_id() or "❌ no configurado")

    history = _load_history()
    last = history[-1] if history else None
    last_info = (
        f"`{last['run_id']}` · {last['query'][:30]} · {last['timestamp'][:16]} · {last['total']} leads"
        if last else "Sin runs previos"
    )

    lines = [
        "🔧 *Estado del sistema*\n",
        f"*ANTHROPIC_API_KEY:* {claude}",
        f"*GROQ_API_KEY:* {groq}",
        f"*BOT TOKEN INTERNO:* {token}",
        f"*ADMIN_CHAT_ID:* `{admin}`",
        f"\n📦 *Último run:* {last_info}",
        f"📂 *Runs guardados:* {len(history)}/{_MAX_HISTORY}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    await update.message.reply_text("🔄 Probando LLM...")
    def _do():
        import llm_client
        return str(llm_client.call('Devuelve exactamente: {"ok": true}', "test"))
    try:
        r = await asyncio.to_thread(_do)
        await update.message.reply_text(f"✅ LLM OK → `{r}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{e}`", parse_mode="Markdown")


async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    args = " ".join(context.args or []).strip()
    n = int(args) if args.isdigit() else 5
    history = _load_history()

    if not history:
        await update.message.reply_text("📭 Sin historial. Ejecuta /pipeline primero.")
        return

    runs = history[-n:]
    lines = [f"📋 *Últimos {len(runs)} runs:*\n"]
    for run in reversed(runs):
        ts    = run["timestamp"][:16].replace("T", " ")
        kind  = "🔍" if run["kind"] == "scrape" else "⚙️"
        lines.append(f"{kind} `{run['run_id']}` · {ts}")
        lines.append(f"   {run['query']} — {run['total']} leads")

    lines.append("\n_Usa los botones o `/stats <run_id>` para explorar._")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=_kb_historial(runs),
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    args = " ".join(context.args or []).strip()
    n = int(args) if args.isdigit() else 10
    run = _get_run(None)

    if not run:
        await update.message.reply_text("📭 Sin datos. Ejecuta /pipeline primero.")
        return

    leads = run["leads"]
    scored = [l for l in leads if isinstance(l.get("lead_score"), (int, float))]
    text = _leads_text(scored, f"🏆 Top {n} — {run['query']}", max_show=n)
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_calificados(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    run = _get_run(None)
    if not run:
        await update.message.reply_text("📭 Sin datos. Ejecuta /pipeline primero.")
        return

    cal = [l for l in run["leads"] if l.get("crm_stage") == "Calificado"]
    text = _leads_text(cal, f"✅ Calificados — {run['query']}")
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_seguimiento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    run = _get_run(None)
    if not run:
        await update.message.reply_text("📭 Sin datos. Ejecuta /pipeline primero.")
        return

    seg = [l for l in run["leads"] if l.get("crm_stage") == "En seguimiento"]
    text = _leads_text(seg, f"🔄 En seguimiento — {run['query']}")
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    run_id = (context.args or [None])[0]
    run = _get_run(run_id)
    if not run:
        await update.message.reply_text(
            "📭 Run no encontrado." if run_id else "📭 Sin datos. Ejecuta /pipeline primero."
        )
        return

    await update.message.reply_text(_stats_text(run), parse_mode="Markdown")


async def _send_csv(chat_id: int, run: dict, context: ContextTypes.DEFAULT_TYPE) -> None:
    csv_bytes = _leads_to_csv(run["leads"])
    if not csv_bytes:
        await context.bot.send_message(chat_id=chat_id, text="Sin leads para exportar.")
        return
    ts = run["timestamp"][:16].replace("T", "_").replace(":", "-")
    safe = run["query"][:25].replace(" ", "_").replace("/", "-")
    filename = f"pipeline_{safe}_{ts}.csv"
    await context.bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=f"📊 {run['query']} · {run['total']} leads · run `{run['run_id']}`",
        parse_mode="Markdown",
    )


async def cmd_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    run_id = (context.args or [None])[0]
    run = _get_run(run_id)
    if not run:
        await update.message.reply_text(
            "📭 Run no encontrado." if run_id else "📭 Sin datos. Ejecuta /pipeline primero."
        )
        return

    await _send_csv(update.effective_chat.id, run, context)


# ─── Pipeline y Buscar ────────────────────────────────────────────────────────

async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    full = " ".join(context.args or []).strip()
    if not full:
        await update.message.reply_text("⚠️ Uso: `/buscar <query> [--limit N]`", parse_mode="Markdown")
        return

    query, limit, _ = _parse_flags(full)
    msg = await update.message.reply_text(
        f"🔍 *Scraping:* {query}\n_Límite: {limit} · Sin calificación_",
        parse_mode="Markdown",
    )
    try:
        leads = await asyncio.to_thread(_run_scrape_sync, query, limit)
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown"); return

    if not leads:
        await msg.edit_text("⚠️ Sin resultados. Prueba otra búsqueda."); return

    run = _add_run(query, leads, kind="scrape")
    emails = sum(1 for l in leads if l.get("email"))
    phones = sum(1 for l in leads if l.get("telefono"))

    await msg.edit_text(
        f"✅ *Scraping completado*\n"
        f"*Query:* {query}\n"
        f"*Leads:* {len(leads)} · 📧 {emails} emails · 📞 {phones} tel\n"
        f"*Run:* `{run['run_id']}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📎 CSV", callback_data=f"csv:{run['run_id']}"),
            InlineKeyboardButton("📊 Stats", callback_data=f"stats:{run['run_id']}"),
        ]]),
    )


async def cmd_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    full = " ".join(context.args or []).strip()
    if not full:
        await update.message.reply_text(
            "⚠️ Uso: `/pipeline <query> [--limit N] [--channel X]`",
            parse_mode="Markdown",
        ); return

    query, limit, channel = _parse_flags(full)
    msg = await update.message.reply_text(
        f"⚙️ *Pipeline iniciado*\n*Query:* {query}\n*Límite:* {limit} · *Canal:* {channel}\n"
        f"_Puede tardar varios minutos..._",
        parse_mode="Markdown",
    )

    # Paso 1: Scrape
    try:
        await msg.edit_text(
            f"🔍 *Paso 1/2 — Scraping Google Maps*\n`{query}`",
            parse_mode="Markdown",
        )
        leads = await asyncio.to_thread(_run_scrape_sync, query, limit)
    except Exception as e:
        await msg.edit_text(f"❌ Error en scraping:\n`{e}`", parse_mode="Markdown"); return

    if not leads:
        await msg.edit_text("⚠️ Sin resultados en Google Maps."); return

    # Paso 2: Calificación
    try:
        await msg.edit_text(
            f"🤖 *Paso 2/2 — Calificando {len(leads)} leads*\n_Canal: {channel}_",
            parse_mode="Markdown",
        )
        qualified = await asyncio.to_thread(_run_qualify_sync, leads, channel)
    except Exception as e:
        await msg.edit_text(f"❌ Error en calificación:\n`{e}`", parse_mode="Markdown"); return

    run = _add_run(query, qualified, kind="pipeline")

    # Resumen ejecutivo
    scored = [l for l in qualified if isinstance(l.get("lead_score"), (int, float))]
    scores = [int(l["lead_score"]) for l in scored]
    avg    = round(sum(scores) / len(scores), 1) if scores else 0
    high   = sum(1 for s in scores if s >= 70)
    cal    = sum(1 for l in qualified if l.get("crm_stage") == "Calificado")

    await msg.edit_text(
        f"✅ *Pipeline completado*\n"
        f"*Query:* {query}\n"
        f"*Total:* {len(qualified)} leads · *Calificados:* {cal} · *Score ≥70:* {high}\n"
        f"*Score promedio:* {avg} · *Run:* `{run['run_id']}`",
        parse_mode="Markdown",
        reply_markup=_kb_after_pipeline(run["run_id"]),
    )


# ─── Callbacks de botones inline ──────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not (_get_admin_id() and query.from_user.id == _get_admin_id()):
        await query.answer("⛔ No autorizado", show_alert=True); return

    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("stats:"):
        run_id = data.split(":", 1)[1]
        run = _get_run(run_id)
        if run:
            await context.bot.send_message(chat_id=chat_id, text=_stats_text(run), parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Run no encontrado.")

    elif data.startswith("top10:"):
        run_id = data.split(":", 1)[1]
        run = _get_run(run_id)
        if run:
            scored = [l for l in run["leads"] if isinstance(l.get("lead_score"), (int, float))]
            text = _leads_text(scored, f"🏆 Top 10 — {run['query']}", max_show=10)
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Run no encontrado.")

    elif data.startswith("cal:"):
        run_id = data.split(":", 1)[1]
        run = _get_run(run_id)
        if run:
            cal = [l for l in run["leads"] if l.get("crm_stage") == "Calificado"]
            text = _leads_text(cal, f"✅ Calificados — {run['query']}")
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Run no encontrado.")

    elif data.startswith("csv:"):
        run_id = data.split(":", 1)[1]
        run = _get_run(run_id)
        if run:
            await _send_csv(chat_id, run, context)
        else:
            await context.bot.send_message(chat_id=chat_id, text="Run no encontrado.")

    elif data.startswith("run:"):
        run_id = data.split(":", 1)[1]
        run = _get_run(run_id)
        if run:
            await context.bot.send_message(
                chat_id=chat_id,
                text=_stats_text(run),
                parse_mode="Markdown",
                reply_markup=_kb_after_pipeline(run["run_id"]),
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text="Run no encontrado.")


# ─── Texto libre → asistente LLM ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    user_text = update.message.text.strip()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    run = _get_run(None)
    ctx = _build_context(run)

    try:
        reply = await asyncio.to_thread(_llm_chat, user_text, ctx)
    except Exception as e:
        reply = f"Error: {e}"

    await update.message.reply_text(reply or "Sin respuesta del LLM.")


# ─── Construcción de la app ───────────────────────────────────────────────────

def _build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("test",        cmd_test))
    app.add_handler(CommandHandler("historial",   cmd_historial))
    app.add_handler(CommandHandler("top",         cmd_top))
    app.add_handler(CommandHandler("calificados", cmd_calificados))
    app.add_handler(CommandHandler("seguimiento", cmd_seguimiento))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("csv",         cmd_csv))
    app.add_handler(CommandHandler("buscar",      cmd_buscar))
    app.add_handler(CommandHandler("pipeline",    cmd_pipeline))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(embedded: bool = False) -> None:
    """Arranca el bot.

    Args:
        embedded: True cuando se llama desde api.py (hilo de fondo).
                  Usa stop_signals=() para no registrar SIGINT/SIGTERM,
                  que solo está permitido en el hilo principal de Python.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN_INTERNO")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN_INTERNO no está configurado")
    admin_id = _get_admin_id()
    if admin_id is None:
        raise ValueError(
            "ADMIN_CHAT_ID no está configurado. "
            "Obtén tu ID enviando /start a @userinfobot en Telegram."
        )

    log.info("PipeAssist iniciado. Admin: %d (embedded=%s)", admin_id, embedded)
    _build_app(token).run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
        stop_signals=() if embedded else None,  # sin signal handlers en hilo de fondo
    )


if __name__ == "__main__":
    main(embedded=False)
