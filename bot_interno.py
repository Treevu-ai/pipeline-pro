"""
bot_interno.py — PipeAssist: asistente interno de gestión para Pipeline_X.

Acceso exclusivo: ADMIN_CHAT_ID.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUSCAR NEGOCIOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/pipeline sector ciudad          — Busca + califica → CSV (+ entrega si hay cliente)
/buscar sector ciudad            — Solo busca, sin calificar (más rápido)

  Opciones: --cliente "Nombre"   → asocia el run a un cliente
            --limit 30           → cuántos negocios buscar (default 20, máx 50)
            --channel whatsapp   → canal de outreach (email | whatsapp | both)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIENTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/cliente add "Nombre" [chat_id]  — Registra un cliente (chat_id opcional para entrega)
/clientes                        — Lista todos tus clientes y sus runs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VER RESULTADOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/top [N]                         — Los mejores N negocios del último pipeline
/calificados                     — Negocios listos para contactar
/seguimiento                     — Negocios que necesitan seguimiento
/stats [run_id]                  — Resumen estadístico de un pipeline
/csv [run_id]                    — Descargar el CSV
/historial [N] [--cliente X]     — Últimas búsquedas (filtra por cliente si se indica)
/entregar [run_id] [--cliente X] — Envía el reporte al cliente vía Telegram

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SISTEMA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/status                          — Estado: claves API, último run
/test                            — Prueba rápida del LLM
/help                            — Este menú

💬 También puedes escribir en texto libre para consultar sobre tus pipelines.

Variables de entorno:
  TELEGRAM_BOT_TOKEN_INTERNO  — token de PipeAssist (@BotFather)
  TELEGRAM_BOT_TOKEN          — token de Alex (para entregar reportes a clientes)
  ADMIN_CHAT_ID               — tu Telegram chat_id
  GROQ_API_KEY / OPENAI_API_KEY
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

import logging_config
import utils

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


# ─── Persistencia: Clientes ───────────────────────────────────────────────────

_CLIENTS_FILE = Path("output/.pipeassist_clients.json")


def _load_clients() -> dict[str, dict]:
    """Devuelve {nombre_lower: {nombre, chat_id, created_at}}."""
    try:
        import db as _db
        clients = _db.get_pipeassist_clients()
        if clients:
            return clients
    except Exception:
        pass
    try:
        return json.loads(_CLIENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_clients(clients: dict) -> None:
    try:
        import db as _db
        _db.save_pipeassist_clients(clients)
    except Exception as e:
        log.warning("No se pudo guardar clientes en DB: %s", e)
    try:
        _CLIENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CLIENTS_FILE.write_text(
            json.dumps(clients, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.warning("No se pudo guardar clientes en archivo: %s", e)


def _client_key(name: str) -> str:
    return name.strip().lower()


def _find_client(name: str) -> dict | None:
    clients = _load_clients()
    return clients.get(_client_key(name))


# ─── Persistencia: Historial de runs ─────────────────────────────────────────

_HISTORY_FILE = Path("output/.pipeassist_history.json")
_MAX_HISTORY  = 20


def _load_history() -> list[dict]:
    try:
        import db as _db
        runs = _db.get_pipeassist_history(limit=_MAX_HISTORY)
        if runs:
            return runs
    except Exception:
        pass
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


def _add_run(query: str, leads: list[dict], kind: str = "pipeline", cliente: str = "") -> dict:
    run = {
        "run_id":    str(uuid.uuid4())[:8],
        "kind":      kind,
        "query":     query,
        "cliente":   cliente,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total":     len(leads),
        "leads":     leads,
    }
    try:
        import db as _db
        _db.add_pipeassist_run(run)
    except Exception as e:
        log.warning("No se pudo guardar run en DB: %s", e)
    history = _load_history()
    history.append(run)
    _save_history(history)
    return run


def _get_run(run_id: str | None, cliente: str = "") -> dict | None:
    history = _load_history()
    if not history:
        return None
    if run_id:
        for run in reversed(history):
            if run["run_id"] == run_id:
                return run
        return None
    if cliente:
        key = _client_key(cliente)
        for run in reversed(history):
            if _client_key(run.get("cliente", "")) == key:
                return run
        return None
    return history[-1]


def _runs_for_client(cliente: str) -> list[dict]:
    key = _client_key(cliente)
    return [r for r in _load_history() if _client_key(r.get("cliente", "")) == key]


# ─── Helpers de pipeline ─────────────────────────────────────────────────────

def _run_scrape_sync(query: str, limit: int) -> list[dict]:
    from scraper import scrape_google_maps, enrich_leads
    return enrich_leads(scrape_google_maps(query, limit))


def _run_qualify_sync(leads: list[dict], channel: str) -> list[dict]:
    from sdr_agent import qualify_row, pre_score
    import config as cfg
    results = []
    for lead in leads:
        base = pre_score(lead)
        try:
            r = qualify_row(lead, channel, base)
            r["qualify_error"] = ""
        except Exception as e:
            r = {k: "" for k in cfg.OUTPUT_KEYS if k != "qualify_error"}
            r["qualify_error"] = str(e)
        results.append({**lead, **r})
    return results


def _leads_to_csv(leads: list[dict]) -> bytes:
    if not leads:
        return b""
    buf = io.StringIO()
    csv.DictWriter(buf, fieldnames=list(leads[0].keys()), extrasaction="ignore").writeheader()
    csv.DictWriter(buf, fieldnames=list(leads[0].keys()), extrasaction="ignore").writerows(leads)
    return buf.getvalue().encode("utf-8-sig")


# ─── Parseo de flags ──────────────────────────────────────────────────────────

def _parse_flags(text: str) -> tuple[str, int, str, str]:
    """Devuelve (búsqueda, limit, channel, cliente)."""
    limit, channel, cliente = 20, "whatsapp", ""

    m = re.search(r"--limit\s+(\d+)", text)
    if m:
        limit = min(int(m.group(1)), 50)
        text = text[:m.start()] + text[m.end():]

    m = re.search(r"--channel\s+(email|whatsapp|both)", text)
    if m:
        channel = m.group(1)
        text = text[:m.start()] + text[m.end():]

    m = re.search(r'--cliente\s+"([^"]+)"|--cliente\s+(\S+)', text)
    if m:
        cliente = (m.group(1) or m.group(2)).strip()
        text = text[:m.start()] + text[m.end():]

    return text.strip(), limit, channel, cliente


def _parse_cliente_flag(text: str) -> tuple[str, str]:
    """Extrae --cliente de un texto. Devuelve (text_sin_flag, cliente)."""
    cliente = ""
    m = re.search(r'--cliente\s+"([^"]+)"|--cliente\s+(\S+)', text)
    if m:
        cliente = (m.group(1) or m.group(2)).strip()
        text = text[:m.start()] + text[m.end():]
    return text.strip(), cliente


# ─── Entrega a cliente ────────────────────────────────────────────────────────

async def _deliver_to_client(run: dict, cliente_name: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Envía el CSV + resumen al chat_id del cliente usando el bot de Alex.
    Devuelve mensaje de resultado."""
    client = _find_client(cliente_name)
    if not client:
        return f"Cliente '{cliente_name}' no registrado. Usa /cliente add para registrarlo."

    chat_id = client.get("chat_id")
    if not chat_id:
        return f"El cliente '{cliente_name}' no tiene chat_id registrado. Agrégalo con:\n`/cliente add \"{cliente_name}\" <chat_id>`"

    alex_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not alex_token:
        return "TELEGRAM_BOT_TOKEN no configurado — no se puede entregar al cliente."

    import httpx
    api = f"https://api.telegram.org/bot{alex_token}"

    leads = run["leads"]
    scored = sorted(
        [l for l in leads if isinstance(l.get("lead_score"), (int, float)) and l["lead_score"] >= 60],
        key=lambda x: x["lead_score"], reverse=True,
    )

    lines = [
        f"✅ *Reporte listo: {run['query']}*",
        f"_{run['total']} negocios analizados · {len(scored)} calificados (score ≥60)_\n",
    ]
    for i, lead in enumerate(scored[:5], 1):
        lines.append(f"*{i}. {lead.get('empresa','—')}* — Score {lead.get('lead_score','—')} | {lead.get('crm_stage','—')}")
        lines.append(f"   → {lead.get('next_action','—')}")
    if not scored:
        lines.append("_No se encontraron negocios con score ≥60. Revisa el CSV adjunto._")
    lines.append("\n📎 Adjunto CSV con todos los negocios y mensajes de outreach listos.")

    try:
        async with httpx.AsyncClient(timeout=20) as client_http:
            # Mensaje de resumen
            await client_http.post(f"{api}/sendMessage", json={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "parse_mode": "Markdown",
            })
            # CSV
            csv_bytes = _leads_to_csv(leads)
            ts = run["timestamp"][:16].replace("T", "_").replace(":", "-")
            safe = run["query"][:25].replace(" ", "_").replace("/", "-")
            await client_http.post(
                f"{api}/sendDocument",
                data={"chat_id": str(chat_id), "caption": f"📊 {run['query']} · {run['total']} negocios"},
                files={"document": (f"pipeline_{safe}_{ts}.csv", csv_bytes, "text/csv")},
            )
        return f"✅ Reporte enviado a *{cliente_name}* (chat_id: `{chat_id}`)"
    except Exception as e:
        return f"❌ Error al enviar: {e}"


# ─── Estadísticas ─────────────────────────────────────────────────────────────

def _stats_text(run: dict) -> str:
    leads = run["leads"]
    total = len(leads)
    if not total:
        return "Sin leads en este run."

    scores = [int(l["lead_score"]) for l in leads if isinstance(l.get("lead_score"), (int, float))]
    avg  = round(sum(scores) / len(scores), 1) if scores else 0
    high = sum(1 for s in scores if s >= 70)
    mid  = sum(1 for s in scores if 50 <= s < 70)
    low  = sum(1 for s in scores if s < 50)

    stages     = Counter(l.get("crm_stage", "—") for l in leads)
    industries = Counter(l.get("industria", l.get("categoria", "")) for l in leads if l.get("industria") or l.get("categoria"))
    emails = sum(1 for l in leads if l.get("email"))
    phones = sum(1 for l in leads if l.get("telefono"))
    sites  = sum(1 for l in leads if l.get("sitio_web"))

    cliente_line = f"*Cliente:* {run['cliente']}\n" if run.get("cliente") else ""
    lines = [
        f"📊 *Stats — {run['query']}*",
        f"_Run `{run['run_id']}` · {run['timestamp'][:16].replace('T',' ')}_",
        cliente_line,
        f"*Total negocios:* {total}",
        f"*Score promedio:* {avg}",
        f"*Score ≥70:* {high}  |  50–69: {mid}  |  <50: {low}\n",
        "*Etapas CRM:*",
    ]
    for stage, count in stages.most_common():
        lines.append(f"  • {stage}: {count}")
    if industries:
        lines.append("\n*Industrias top:*")
        for ind, count in industries.most_common(5):
            lines.append(f"  • {ind}: {count}")
    lines += [
        "\n*Contacto disponible:*",
        f"  📧 Email: {emails}/{total}",
        f"  📞 Teléfono: {phones}/{total}",
        f"  🌐 Sitio web: {sites}/{total}",
    ]
    return "\n".join(l for l in lines if l is not None)


def _leads_text(leads: list[dict], title: str, max_show: int = 10) -> str:
    if not leads:
        return f"_{title}: sin resultados._"
    top = sorted(leads, key=lambda x: x.get("lead_score", 0), reverse=True)[:max_show]
    lines = [f"*{title}* ({len(leads)} negocios)\n"]
    for i, lead in enumerate(top, 1):
        empresa = lead.get("empresa", "—")
        score   = lead.get("lead_score", "—")
        stage   = lead.get("crm_stage", "—")
        action  = lead.get("next_action", "—")
        contact = " | ".join(filter(None, [lead.get("ciudad",""), lead.get("email","") or lead.get("telefono","")]))
        lines.append(f"*{i}. {empresa}*  — Score {score} · {stage}")
        if contact:
            lines.append(f"   {contact}")
        lines.append(f"   → {action}")
    if len(leads) > max_show:
        lines.append(f"\n_... y {len(leads)-max_show} más. Usa /csv para el listado completo._")
    return "\n".join(lines)


# ─── Teclados inline ──────────────────────────────────────────────────────────

def _kb_after_pipeline(run_id: str, cliente: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📊 Stats",       callback_data=f"stats:{run_id}"),
            InlineKeyboardButton("🏆 Top 10",      callback_data=f"top10:{run_id}"),
        ],
        [
            InlineKeyboardButton("✅ Calificados", callback_data=f"cal:{run_id}"),
            InlineKeyboardButton("📎 CSV",         callback_data=f"csv:{run_id}"),
        ],
    ]
    if cliente:
        rows.append([InlineKeyboardButton(f"📤 Entregar a {cliente}", callback_data=f"deliver:{run_id}:{cliente}")])
    return InlineKeyboardMarkup(rows)


def _kb_historial(runs: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for run in reversed(runs[-6:]):
        ts    = run["timestamp"][5:16].replace("T", " ")
        cli   = f" [{run['cliente']}]" if run.get("cliente") else ""
        label = f"{ts}{cli} · {run['query'][:20]} ({run['total']})"
        rows.append([InlineKeyboardButton(label, callback_data=f"run:{run['run_id']}")])
    return InlineKeyboardMarkup(rows)


# ─── LLM conversacional ───────────────────────────────────────────────────────

_ASSISTANT_SYSTEM = """
Eres PipeAssist, el asistente interno de Pipeline_X para un founder solo.
Tu rol: ayudarlo a entender y gestionar sus pipelines de prospección B2B.

Pipeline_X busca NEGOCIOS (empresas, comercios, pymes) en Google Maps, los califica
con IA y genera mensajes de outreach. Cada "lead" es un negocio, no una persona.

CONTEXTO ACTUAL:
{context}

REGLAS:
- Responde en español, máximo 6 líneas.
- Si te preguntan por datos, úsalos del contexto.
- Si el usuario quiere ejecutar algo, sugiere el comando exacto.
- No inventes datos que no estén en el contexto.
""".strip()


def _build_context(history: list[dict], clients: dict) -> str:
    if not history:
        return "Sin pipelines ejecutados aún."

    recent = history[-5:]
    runs_summary = []
    for r in reversed(recent):
        scores = [int(l["lead_score"]) for l in r["leads"] if isinstance(l.get("lead_score"), (int, float))]
        avg = round(sum(scores)/len(scores), 1) if scores else 0
        cal = sum(1 for l in r["leads"] if l.get("crm_stage") == "Calificado")
        cli = f" | Cliente: {r['cliente']}" if r.get("cliente") else ""
        runs_summary.append(
            f"  [{r['run_id']}] {r['timestamp'][:10]} · {r['query']}{cli} · {r['total']} negocios · avg={avg} · {cal} calificados"
        )

    client_lines = []
    for key, c in clients.items():
        n_runs = sum(1 for r in history if _client_key(r.get("cliente","")) == key)
        chat = f" (chat_id: {c['chat_id']})" if c.get("chat_id") else " (sin chat_id)"
        client_lines.append(f"  - {c['nombre']}{chat} · {n_runs} runs")

    ctx = "Últimos runs:\n" + "\n".join(runs_summary)
    if client_lines:
        ctx += "\n\nClientes registrados:\n" + "\n".join(client_lines)
    return ctx


def _llm_chat(user_text: str, context: str) -> str:
    system = _ASSISTANT_SYSTEM.format(context=context)

    if utils.clean_env_secret("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            import config as cfg
            client = OpenAI(api_key=utils.clean_env_secret("OPENAI_API_KEY"))
            resp = client.chat.completions.create(
                model=cfg.OPENAI["model"],
                max_tokens=350,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.7,
                timeout=60,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            pass

    if utils.clean_env_secret("GROQ_API_KEY"):
        try:
            from groq import Groq
            resp = Groq(api_key=utils.clean_env_secret("GROQ_API_KEY")).chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
                temperature=0.5, max_tokens=350,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            pass

    return "Sin LLM disponible."


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    text = (
        "🤖 *PipeAssist — Tu asistente de pipeline*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔍 *BUSCAR NEGOCIOS*\n"
        "━━━━━━━━━━━━━━━━\n"
        "`/pipeline` _sector ciudad_ — Busca, califica y entrega el CSV\n"
        "Ej: `/pipeline Ferreterías Lima`\n"
        "Ej: `/pipeline Logística Bogotá --cliente \"Empresa ABC\" --limit 30`\n\n"
        "`/buscar` _sector ciudad_ — Solo busca, sin calificar (más rápido)\n"
        "Ej: `/buscar Clínicas Trujillo --limit 40`\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "👥 *CLIENTES*\n"
        "━━━━━━━━━━━━━━━━\n"
        "`/cliente add` _Nombre_ \\[chat\\_id\\] — Registra un cliente\n"
        "`/clientes` — Lista todos tus clientes\n"
        "`/entregar` \\[--cliente _Nombre_\\] — Envía el reporte al cliente\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📊 *VER RESULTADOS*\n"
        "━━━━━━━━━━━━━━━━\n"
        "`/top` — Los mejores negocios por score\n"
        "`/calificados` — Negocios listos para contactar\n"
        "`/seguimiento` — Negocios que necesitan seguimiento\n"
        "`/stats` — Resumen estadístico\n"
        "`/csv` — Descargar el archivo\n"
        "`/historial` — Búsquedas anteriores (filtra con `--cliente`)\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚙️ *OPCIONES*\n"
        "━━━━━━━━━━━━━━━━\n"
        "`--limit 30` · `--channel whatsapp` · `--cliente \"Nombre\"`\n\n"
        "💬 _Escríbeme en texto libre para consultar tus pipelines._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    groq   = "✅" if os.environ.get("GROQ_API_KEY") else "❌"
    openai = "✅" if os.environ.get("OPENAI_API_KEY") else "—"
    alex   = "✅" if os.environ.get("TELEGRAM_BOT_TOKEN") else "❌ (entrega desactivada)"

    history = _load_history()
    clients = _load_clients()
    last    = history[-1] if history else None
    last_info = (
        f"`{last['run_id']}` · {last.get('cliente') or 'sin cliente'} · {last['query'][:25]} · {last['total']} negocios"
        if last else "Sin runs previos"
    )

    lines = [
        "🔧 *Estado del sistema*\n",
        f"*OPENAI_API_KEY:* {openai}",
        f"*GROQ_API_KEY:* {groq}",
        f"*Bot entrega (Alex):* {alex}",
        f"\n📦 *Último run:* {last_info}",
        f"📂 *Runs guardados:* {len(history)}/{_MAX_HISTORY}",
        f"👥 *Clientes registrados:* {len(clients)}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    await update.message.reply_text("Probando LLM...")
    def _do():
        import llm_client
        return str(llm_client.call('Devuelve: {"ok": true}', "test"))
    try:
        r = await asyncio.to_thread(_do)
        await update.message.reply_text(f"✅ LLM OK\n`{r}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{e}`", parse_mode="Markdown")


# ── Clientes ──────────────────────────────────────────────────────────────────

async def cmd_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    args = context.args or []
    if not args or args[0] != "add":
        await update.message.reply_text(
            "Uso: `/cliente add \"Nombre del cliente\" [chat_id]`\n\n"
            "El `chat_id` es opcional. Si lo agregas, podrás enviarle el reporte directo.\n"
            "Para obtener el chat_id de tu cliente: pídele que te envíe su ID desde @userinfobot.",
            parse_mode="Markdown",
        ); return

    rest = " ".join(args[1:]).strip()
    m = re.match(r'^"([^"]+)"\s*(\d+)?$|^(\S+)\s*(\d+)?$', rest)
    if not m:
        await update.message.reply_text(
            'Formato: `/cliente add "Nombre Empresa" 123456789`\n'
            'Si el nombre tiene espacios, ponlo entre comillas.',
            parse_mode="Markdown",
        ); return

    nombre   = (m.group(1) or m.group(3)).strip()
    chat_id  = int(m.group(2) or m.group(4)) if (m.group(2) or m.group(4)) else None
    clients  = _load_clients()
    key      = _client_key(nombre)

    clients[key] = {
        "nombre":     nombre,
        "chat_id":    chat_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_clients(clients)

    chat_info = f"chat_id: `{chat_id}`" if chat_id else "sin chat_id (agrega uno para poder entregar reportes)"
    await update.message.reply_text(
        f"✅ Cliente *{nombre}* registrado\n{chat_info}\n\n"
        f"Ahora puedes asociar pipelines a este cliente con:\n"
        f'`/pipeline Ferreterías Lima --cliente "{nombre}"`',
        parse_mode="Markdown",
    )


async def cmd_clientes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    clients = _load_clients()
    history = _load_history()

    if not clients:
        await update.message.reply_text(
            "No tienes clientes registrados.\n"
            'Agrega uno con: `/cliente add "Nombre Empresa"`',
            parse_mode="Markdown",
        ); return

    lines = ["👥 *Tus clientes*\n"]
    for key, c in clients.items():
        n_runs = sum(1 for r in history if _client_key(r.get("cliente","")) == key)
        last_run = next((r for r in reversed(history) if _client_key(r.get("cliente","")) == key), None)
        chat = f"chat_id `{c['chat_id']}`" if c.get("chat_id") else "sin chat_id"
        last_info = f"Último run: {last_run['query']} ({last_run['timestamp'][:10]})" if last_run else "Sin runs aún"
        lines.append(f"*{c['nombre']}* — {chat}")
        lines.append(f"  {n_runs} pipelines · {last_info}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Historial ─────────────────────────────────────────────────────────────────

async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    full = " ".join(context.args or []).strip()
    full, cliente = _parse_cliente_flag(full)
    n = int(full) if full.isdigit() else 5

    history = _load_history()
    if cliente:
        runs = _runs_for_client(cliente)
        title = f"📋 *Últimos runs de {cliente}* ({len(runs)} total)\n"
    else:
        runs = history
        title = f"📋 *Últimos {n} pipelines*\n"

    if not runs:
        await update.message.reply_text("Sin historial aún. Ejecuta `/pipeline` para comenzar.", parse_mode="Markdown")
        return

    subset = runs[-n:]
    lines  = [title]
    for run in reversed(subset):
        ts  = run["timestamp"][:16].replace("T", " ")
        cli = f" · 👤 {run['cliente']}" if run.get("cliente") else ""
        ico = "🔍" if run["kind"] == "scrape" else "⚙️"
        lines.append(f"{ico} `{run['run_id']}` · {ts}{cli}")
        lines.append(f"   {run['query']} — {run['total']} negocios")

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=_kb_historial(subset),
    )


# ── Top / Calificados / Seguimiento ───────────────────────────────────────────

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    args = " ".join(context.args or []).strip()
    n = int(args) if args.isdigit() else 10
    run = _get_run(None)
    if not run:
        await update.message.reply_text("Sin datos. Ejecuta /pipeline primero."); return
    scored = [l for l in run["leads"] if isinstance(l.get("lead_score"), (int, float))]
    await update.message.reply_text(
        _leads_text(scored, f"🏆 Top {n} — {run['query']}", max_show=n), parse_mode="Markdown"
    )


async def cmd_calificados(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    run = _get_run(None)
    if not run:
        await update.message.reply_text("Sin datos. Ejecuta /pipeline primero."); return
    cal = [l for l in run["leads"] if l.get("crm_stage") == "Calificado"]
    await update.message.reply_text(
        _leads_text(cal, f"✅ Calificados — {run['query']}"), parse_mode="Markdown"
    )


async def cmd_seguimiento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    run = _get_run(None)
    if not run:
        await update.message.reply_text("Sin datos. Ejecuta /pipeline primero."); return
    seg = [l for l in run["leads"] if l.get("crm_stage") == "En seguimiento"]
    await update.message.reply_text(
        _leads_text(seg, f"🔄 En seguimiento — {run['query']}"), parse_mode="Markdown"
    )


# ── Stats / CSV ───────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    run_id = (context.args or [None])[0]
    run = _get_run(run_id)
    if not run:
        await update.message.reply_text("Run no encontrado." if run_id else "Sin datos. Ejecuta /pipeline primero.")
        return
    await update.message.reply_text(_stats_text(run), parse_mode="Markdown")


async def _send_csv(chat_id: int, run: dict, context: ContextTypes.DEFAULT_TYPE) -> None:
    csv_bytes = _leads_to_csv(run["leads"])
    if not csv_bytes:
        await context.bot.send_message(chat_id=chat_id, text="Sin negocios para exportar."); return
    ts   = run["timestamp"][:16].replace("T", "_").replace(":", "-")
    safe = run["query"][:25].replace(" ", "_").replace("/", "-")
    cli  = f"_{run['cliente']}" if run.get("cliente") else ""
    await context.bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(csv_bytes),
        filename=f"pipeline{cli}_{safe}_{ts}.csv",
        caption=f"📊 {run['query']} · {run['total']} negocios" + (f" · {run['cliente']}" if run.get("cliente") else ""),
        parse_mode="Markdown",
    )


async def cmd_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    run_id = (context.args or [None])[0]
    run = _get_run(run_id)
    if not run:
        await update.message.reply_text("Run no encontrado." if run_id else "Sin datos. Ejecuta /pipeline primero.")
        return
    await _send_csv(update.effective_chat.id, run, context)


# ── Entregar ──────────────────────────────────────────────────────────────────

async def cmd_entregar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    full = " ".join(context.args or []).strip()
    full, cliente = _parse_cliente_flag(full)
    run_id = full if full else None

    run = _get_run(run_id, cliente=cliente)
    if not run:
        await update.message.reply_text(
            "No se encontró el pipeline.\n\n"
            "Uso: `/entregar --cliente \"Nombre\"`\n"
            "o: `/entregar abc123 --cliente \"Nombre\"`",
            parse_mode="Markdown",
        ); return

    if not cliente and run.get("cliente"):
        cliente = run["cliente"]

    if not cliente:
        await update.message.reply_text(
            "¿A qué cliente envío el reporte?\n\n"
            "Uso: `/entregar --cliente \"Nombre del cliente\"`\n"
            "Primero regístralo con `/cliente add`.",
            parse_mode="Markdown",
        ); return

    msg = await update.message.reply_text(f"Enviando reporte a *{cliente}*...", parse_mode="Markdown")
    result = await _deliver_to_client(run, cliente, context)
    await msg.edit_text(result, parse_mode="Markdown")


# ── Buscar / Pipeline ─────────────────────────────────────────────────────────

async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    full = " ".join(context.args or []).strip()
    if not full:
        await update.message.reply_text(
            "Uso: `/buscar sector ciudad [--limite N] [--cliente Nombre]`\n"
            "Ej: `/buscar Clínicas Trujillo --limit 40`",
            parse_mode="Markdown",
        ); return

    query, limit, _, cliente = _parse_flags(full)
    msg = await update.message.reply_text(
        f"🔍 Buscando *{query}*\n_Hasta {limit} negocios, sin calificación..._",
        parse_mode="Markdown",
    )
    try:
        leads = await asyncio.to_thread(_run_scrape_sync, query, limit)
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown"); return

    if not leads:
        await msg.edit_text("Sin resultados. Prueba con otra búsqueda."); return

    run = _add_run(query, leads, kind="scrape", cliente=cliente)
    emails = sum(1 for l in leads if l.get("email"))
    phones = sum(1 for l in leads if l.get("telefono"))
    cli_line = f"*Cliente:* {cliente}\n" if cliente else ""

    await msg.edit_text(
        f"✅ *Búsqueda completada*\n"
        f"*Sector:* {query} · *Negocios:* {len(leads)}\n"
        f"{cli_line}"
        f"📧 {emails} emails · 📞 {phones} teléfonos · Run `{run['run_id']}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📎 CSV",   callback_data=f"csv:{run['run_id']}"),
            InlineKeyboardButton("📊 Stats", callback_data=f"stats:{run['run_id']}"),
        ]]),
    )


async def cmd_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return

    full = " ".join(context.args or []).strip()
    if not full:
        await update.message.reply_text(
            "Uso: `/pipeline sector ciudad [--cliente Nombre] [--limit N] [--channel X]`\n\n"
            "Ej: `/pipeline Ferreterías Lima`\n"
            'Ej: `/pipeline Logística Bogotá --cliente "Empresa ABC" --limit 30`',
            parse_mode="Markdown",
        ); return

    query, limit, channel, cliente = _parse_flags(full)
    cli_line = f"*Cliente:* {cliente}\n" if cliente else ""

    msg = await update.message.reply_text(
        f"⚙️ *Pipeline iniciado*\n*Búsqueda:* {query}\n{cli_line}"
        f"*Límite:* {limit} negocios · *Canal:* {channel}\n_Puede tardar varios minutos..._",
        parse_mode="Markdown",
    )

    # Paso 1: Scraping
    try:
        await msg.edit_text(f"🔍 *Paso 1/2 — Buscando en Google Maps*\n`{query}`", parse_mode="Markdown")
        leads = await asyncio.to_thread(_run_scrape_sync, query, limit)
    except Exception as e:
        await msg.edit_text(f"❌ Error en búsqueda:\n`{e}`", parse_mode="Markdown"); return

    if not leads:
        await msg.edit_text("Sin resultados en Google Maps para esa búsqueda."); return

    # Paso 2: Calificación
    try:
        await msg.edit_text(
            f"🤖 *Paso 2/2 — Calificando {len(leads)} negocios con IA*\n_Canal: {channel}_",
            parse_mode="Markdown",
        )
        qualified = await asyncio.to_thread(_run_qualify_sync, leads, channel)
    except Exception as e:
        await msg.edit_text(f"❌ Error en calificación:\n`{e}`", parse_mode="Markdown"); return

    run = _add_run(query, qualified, kind="pipeline", cliente=cliente)

    scores  = [int(l["lead_score"]) for l in qualified if isinstance(l.get("lead_score"), (int, float))]
    avg     = round(sum(scores)/len(scores), 1) if scores else 0
    high    = sum(1 for s in scores if s >= 70)
    cal_n   = sum(1 for l in qualified if l.get("crm_stage") == "Calificado")

    await msg.edit_text(
        f"✅ *Pipeline completado*\n"
        f"*Búsqueda:* {query}\n"
        f"{cli_line}"
        f"*Negocios:* {len(qualified)} · *Calificados:* {cal_n} · *Score ≥70:* {high}\n"
        f"*Score promedio:* {avg} · *Run:* `{run['run_id']}`",
        parse_mode="Markdown",
        reply_markup=_kb_after_pipeline(run["run_id"], cliente),
    )


# ─── Callbacks ────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not (_get_admin_id() and query.from_user.id == _get_admin_id()):
        await query.answer("⛔ No autorizado", show_alert=True); return

    data    = query.data
    chat_id = query.message.chat_id

    if data.startswith("stats:"):
        run = _get_run(data.split(":", 1)[1])
        text = _stats_text(run) if run else "Run no encontrado."
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

    elif data.startswith("top10:"):
        run = _get_run(data.split(":", 1)[1])
        if run:
            scored = [l for l in run["leads"] if isinstance(l.get("lead_score"), (int, float))]
            await context.bot.send_message(
                chat_id=chat_id,
                text=_leads_text(scored, f"🏆 Top 10 — {run['query']}", max_show=10),
                parse_mode="Markdown",
            )

    elif data.startswith("cal:"):
        run = _get_run(data.split(":", 1)[1])
        if run:
            cal = [l for l in run["leads"] if l.get("crm_stage") == "Calificado"]
            await context.bot.send_message(
                chat_id=chat_id,
                text=_leads_text(cal, f"✅ Calificados — {run['query']}"),
                parse_mode="Markdown",
            )

    elif data.startswith("csv:"):
        run = _get_run(data.split(":", 1)[1])
        if run:
            await _send_csv(chat_id, run, context)

    elif data.startswith("deliver:"):
        # formato: deliver:run_id:nombre_cliente
        parts = data.split(":", 2)
        run_id  = parts[1] if len(parts) > 1 else None
        cliente = parts[2] if len(parts) > 2 else ""
        run = _get_run(run_id)
        if run and cliente:
            await context.bot.send_message(chat_id=chat_id, text=f"Enviando a {cliente}...")
            result = await _deliver_to_client(run, cliente, context)
            await context.bot.send_message(chat_id=chat_id, text=result, parse_mode="Markdown")

    elif data.startswith("run:"):
        run = _get_run(data.split(":", 1)[1])
        if run:
            await context.bot.send_message(
                chat_id=chat_id,
                text=_stats_text(run),
                parse_mode="Markdown",
                reply_markup=_kb_after_pipeline(run["run_id"], run.get("cliente", "")),
            )


# ─── Texto libre → asistente ──────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await _deny(update); return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    ctx = _build_context(_load_history(), _load_clients())
    try:
        reply = await asyncio.to_thread(_llm_chat, update.message.text.strip(), ctx)
    except Exception as e:
        reply = f"Error: {e}"
    await update.message.reply_text(reply or "Sin respuesta.")


# ─── Build app + Main ─────────────────────────────────────────────────────────

def _build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("test",        cmd_test))
    app.add_handler(CommandHandler("cliente",     cmd_cliente))
    app.add_handler(CommandHandler("clientes",    cmd_clientes))
    app.add_handler(CommandHandler("historial",   cmd_historial))
    app.add_handler(CommandHandler("top",         cmd_top))
    app.add_handler(CommandHandler("calificados", cmd_calificados))
    app.add_handler(CommandHandler("seguimiento", cmd_seguimiento))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("csv",         cmd_csv))
    app.add_handler(CommandHandler("entregar",    cmd_entregar))
    app.add_handler(CommandHandler("buscar",      cmd_buscar))
    app.add_handler(CommandHandler("pipeline",    cmd_pipeline))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def main(embedded: bool = False) -> None:
    token    = os.environ.get("TELEGRAM_BOT_TOKEN_INTERNO")
    admin_id = _get_admin_id()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN_INTERNO no configurado")
    if admin_id is None:
        raise ValueError("ADMIN_CHAT_ID no configurado")
    log.info("PipeAssist iniciado. Admin: %d (embedded=%s)", admin_id, embedded)
    _build_app(token).run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
        stop_signals=() if embedded else None,
    )


if __name__ == "__main__":
    main(embedded=False)
