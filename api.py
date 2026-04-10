"""
api.py — API REST para AgentePyme SDR.

Endpoints:
  GET  /health                  Estado del servicio
  POST /scrape                  Busca leads en Google Maps
  POST /qualify                 Califica una lista de leads con Groq
  POST /enrich                  Enriquece contactos (emails, redes sociales)
  POST /pipeline                Pipeline completo: scrape → califica
  POST /jobs/pipeline           Lanza pipeline en background
  GET  /jobs/{job_id}           Estado del job
  GET  /jobs/{job_id}/result    Resultado del job
  POST /deliver                 Pipeline + entrega CSV por Telegram
  POST /webhook/telegram        Webhook del bot de Telegram

Variables de entorno requeridas:
  GROQ_API_KEY                — clave de API de Groq (o ANTHROPIC_API_KEY)
  TELEGRAM_BOT_TOKEN          — token del bot externo Alex (@BotFather)
  TELEGRAM_BOT_TOKEN_INTERNO  — token del bot interno de gestión (bot_interno.py)
  ADMIN_CHAT_ID               — tu chat_id de Telegram (acceso al bot interno)
  NOTION_DB_ID                — ID de la BD Notion para marcar leads (opcional)
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

import config as cfg
import constants as const

log = logging.getLogger("api")


# ─── Plan helpers ─────────────────────────────────────────────────────────────

def _resolve_tier(request: Request) -> str:
    """Lee X-Plan-Tier header y lo valida. Default: 'free'."""
    tier = request.headers.get("X-Plan-Tier", const.PlanTier.FREE).lower()
    return tier if tier in const.PlanTier.ALL else const.PlanTier.FREE


def _plan_limits(tier: str) -> dict:
    """Devuelve el dict de plan para el tier dado."""
    return cfg.PLANS.get(tier, cfg.PLANS[const.PlanTier.FREE])


def _enforce_plan(tier: str, leads_requested: int, wants_sunat: bool) -> tuple[int, bool]:
    """
    Aplica los límites del plan sobre los parámetros de la petición.
    Devuelve (leads_limit_efectivo, enrich_sunat_efectivo).
    """
    plan = _plan_limits(tier)
    features = plan.get("features", {})
    effective_limit  = min(leads_requested, plan["leads_limit"])
    effective_sunat  = wants_sunat and features.get("enrich_sunat", False)
    return effective_limit, effective_sunat


def _start_bot_interno() -> None:
    """Arranca bot_interno en un hilo de fondo con su propio event loop.
    Usa run_async() para evitar el registro de signal handlers (solo permitido
    en el hilo principal), que es lo que hace run_polling() y causaba el fallo silencioso."""
    if not (os.environ.get("TELEGRAM_BOT_TOKEN_INTERNO") and os.environ.get("ADMIN_CHAT_ID")):
        return

    def _run():
        try:
            import bot_interno
            log.info("PipeAssist iniciando en hilo de fondo...")
            bot_interno.main(embedded=True)  # stop_signals=() evita error de signal en hilo
        except Exception as e:
            log.error("PipeAssist falló: %s", e, exc_info=True)

    threading.Thread(target=_run, daemon=True, name="pipeassist-bot").start()


def _register_whatsapp_webhook() -> None:
    """Registra el webhook de WhatsApp en Green API al arrancar la app."""
    webhook_url = cfg.GREEN_API.get("webhook_url", "")
    instance    = cfg.GREEN_API.get("id_instance", "")
    if not webhook_url or not instance:
        return   # Green API no configurada, omitir silenciosamente
    try:
        import wa_sender
        ok = wa_sender.set_webhook(webhook_url)
        if ok:
            log.info("WhatsApp webhook registrado: %s", webhook_url)
    except Exception as exc:
        log.warning("No se pudo registrar webhook de WhatsApp: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_bot_interno()
    await asyncio.to_thread(_register_whatsapp_webhook)
    yield




_SWAGGER_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { font-family: 'IBM Plex Mono', 'Courier New', monospace !important; }

  body, .swagger-ui { background: #000 !important; color: #e5e5e5 !important; }

  /* Top bar — reemplazar azul con negro */
  .swagger-ui .topbar { background: #000 !important; border-bottom: 1px solid #1a1a1a !important; padding: 10px 20px !important; }
  .swagger-ui .topbar .download-url-wrapper { display: none !important; }
  .swagger-ui .topbar-wrapper img { display: none !important; }
  .swagger-ui .topbar-wrapper::before {
    content: 'Pipeline_X SDR API';
    font-family: 'IBM Plex Mono', monospace !important;
    font-weight: 700;
    font-size: 14px;
    color: #fff;
    letter-spacing: -0.02em;
  }

  /* Info block */
  .swagger-ui .info { margin: 24px 0 16px !important; border-bottom: 2px solid #000 !important; padding-bottom: 16px !important; }
  .swagger-ui .info h2.title { color: #fff !important; font-size: 22px !important; font-weight: 700 !important; }
  .swagger-ui .info .description p { color: #6b7280 !important; font-size: 13px !important; }
  .swagger-ui .info a { color: #4ade80 !important; }
  .swagger-ui .info .base-url { color: #6b7280 !important; }

  /* Scheme container */
  .swagger-ui .scheme-container { background: #000 !important; border-bottom: 1px solid #1a1a1a !important; padding: 12px 0 !important; box-shadow: none !important; }

  /* Section tags */
  .swagger-ui .opblock-tag { border-bottom: 1px solid #1a1a1a !important; color: #fff !important; font-size: 15px !important; font-weight: 700 !important; }
  .swagger-ui .opblock-tag:hover { background: #111 !important; }
  .swagger-ui .opblock-tag small { color: #6b7280 !important; font-weight: 400 !important; }

  /* Endpoint blocks */
  .swagger-ui .opblock { background: #0a0a0a !important; border: 1px solid #1a1a1a !important; margin-bottom: 4px !important; border-radius: 0 !important; }
  .swagger-ui .opblock.is-open { border-color: #2a2a2a !important; }
  .swagger-ui .opblock .opblock-summary { border-bottom: 1px solid #1a1a1a !important; }
  .swagger-ui .opblock .opblock-summary:hover { background: #111 !important; }
  .swagger-ui .opblock-summary-description { color: #a3a3a3 !important; }
  .swagger-ui .opblock-summary-path { color: #e5e5e5 !important; }
  .swagger-ui .opblock-body { background: #0a0a0a !important; }

  /* GET → verde */
  .swagger-ui .opblock.opblock-get { border-left: 3px solid #4ade80 !important; }
  .swagger-ui .opblock.opblock-get .opblock-summary-method { background: #000 !important; color: #4ade80 !important; border: 1px solid #4ade80 !important; }
  /* POST → blanco */
  .swagger-ui .opblock.opblock-post { border-left: 3px solid #fff !important; }
  .swagger-ui .opblock.opblock-post .opblock-summary-method { background: #fff !important; color: #000 !important; }
  /* DELETE → rojo tenue */
  .swagger-ui .opblock.opblock-delete .opblock-summary-method { background: #000 !important; color: #f87171 !important; border: 1px solid #f87171 !important; }

  /* Parámetros y tablas */
  .swagger-ui table thead tr th, .swagger-ui table thead tr td { color: #6b7280 !important; border-bottom: 1px solid #1a1a1a !important; font-size: 11px !important; text-transform: uppercase !important; letter-spacing: .06em !important; }
  .swagger-ui .parameters-col_description p { color: #a3a3a3 !important; }
  .swagger-ui .parameter__name { color: #e5e5e5 !important; }
  .swagger-ui .parameter__type { color: #4ade80 !important; }
  .swagger-ui .prop-type { color: #4ade80 !important; }

  /* Inputs */
  .swagger-ui input, .swagger-ui textarea, .swagger-ui select {
    background: #111 !important; color: #e5e5e5 !important;
    border: 1px solid #2a2a2a !important; border-radius: 0 !important;
  }
  .swagger-ui input:focus, .swagger-ui textarea:focus { border-color: #4ade80 !important; outline: none !important; }

  /* Botones */
  .swagger-ui .btn { border-radius: 0 !important; font-weight: 600 !important; }
  .swagger-ui .btn.execute { background: #4ade80 !important; color: #000 !important; border-color: #4ade80 !important; }
  .swagger-ui .btn.execute:hover { opacity: .85 !important; }
  .swagger-ui .btn.cancel { background: #000 !important; color: #fff !important; border-color: #2a2a2a !important; }
  .swagger-ui .btn.authorize { background: #000 !important; color: #4ade80 !important; border-color: #4ade80 !important; }

  /* Responses */
  .swagger-ui .responses-inner { background: #0a0a0a !important; }
  .swagger-ui .response-col_status { color: #4ade80 !important; font-weight: 700 !important; }
  .swagger-ui .microlight { background: #111 !important; color: #e5e5e5 !important; border: 1px solid #1a1a1a !important; }
  .swagger-ui .highlight-code { background: #0a0a0a !important; }
  .swagger-ui pre { background: #111 !important; color: #e5e5e5 !important; border: 1px solid #1a1a1a !important; padding: 12px !important; }
  .swagger-ui code { color: #4ade80 !important; }

  /* Models */
  .swagger-ui section.models { background: #0a0a0a !important; border: 1px solid #1a1a1a !important; }
  .swagger-ui section.models h4 { color: #fff !important; }
  .swagger-ui .model-box { background: #111 !important; }
  .swagger-ui .model { color: #e5e5e5 !important; }

  /* Misc */
  .swagger-ui .opblock-description-wrapper p { color: #a3a3a3 !important; }
  .swagger-ui .tab li { color: #6b7280 !important; }
  .swagger-ui .tab li.active { color: #fff !important; }
  .swagger-ui hr { border-color: #1a1a1a !important; }
  .swagger-ui svg { fill: currentColor !important; }
  .swagger-ui .arrow { fill: #6b7280 !important; }

  /* Version badge */
  .swagger-ui .info .version { background: #1a1a1a !important; color: #4ade80 !important; border: 1px solid #2a2a2a !important; }
</style>
"""

app = FastAPI(
    title="Pipeline_X SDR API",
    description="API para calificación de leads de MIPYME con IA · [pipelinex.app](https://pipelinex.app)",
    version="1.0.0",
    docs_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Job store (in-memory) ────────────────────────────────────────────────────

_jobs: dict[str, dict[str, Any]] = {}


def _new_job(kind: str, params: dict) -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "id": job_id,
        "kind": kind,
        "status": "pending",
        "params": params,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "error": None,
        "result": None,
    }
    return job_id


def _job_running(job_id: str) -> None:
    _jobs[job_id]["status"] = "running"


def _job_done(job_id: str, result: Any) -> None:
    _jobs[job_id]["status"] = "done"
    _jobs[job_id]["result"] = result
    _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def _job_failed(job_id: str, error: str) -> None:
    _jobs[job_id]["status"] = "failed"
    _jobs[job_id]["error"] = error
    _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    query: str = Field(..., description='Búsqueda para Google Maps, ej: "Retail Lima Peru"')
    limit: int = Field(20, ge=1, le=100, description="Máx. leads a obtener")
    enrich_web: bool = Field(True, description="Visitar sitios web para enriquecer datos")
    enrich_sunat: bool = Field(False, description="Consultar SUNAT por RUC (solo Perú)")


class QualifyRequest(BaseModel):
    leads: list[dict[str, Any]] = Field(..., description="Lista de leads a calificar")
    channel: Literal["email", "whatsapp", "both"] = Field("email", description="Canal de outreach")


class EnrichRequest(BaseModel):
    leads: list[dict[str, Any]] = Field(..., description="Lista de leads a enriquecer")


class PipelineRequest(BaseModel):
    query: str = Field(..., description='Búsqueda para Google Maps')
    limit: int = Field(20, ge=1, le=100)
    channel: Literal["email", "whatsapp", "both"] = Field("email")
    enrich_web: bool = Field(True)
    enrich_sunat: bool = Field(False)
    qualify: bool = Field(True, description="Calificar leads tras el scraping")
    enrich_contacts: bool = Field(False, description="Enriquecer contactos al final")


# ─── Helpers async ───────────────────────────────────────────────────────────

def _run_scrape(query: str, limit: int, enrich_web: bool, enrich_sunat: bool) -> list[dict]:
    from scraper import scrape_google_maps, enrich_leads
    leads = scrape_google_maps(query, limit)
    if enrich_web:
        leads = enrich_leads(leads, use_sunat=enrich_sunat)
    return leads


def _run_qualify(leads: list[dict], channel: str) -> list[dict]:
    from sdr_agent import qualify_row, pre_score
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


def _run_enrich(leads: list[dict]) -> list[dict]:
    from contact_enricher import enrich_leads
    return enrich_leads(leads)


def _run_pipeline(req: PipelineRequest) -> dict:
    leads = _run_scrape(req.query, req.limit, req.enrich_web, req.enrich_sunat)
    qualified = _run_qualify(leads, req.channel) if req.qualify else leads
    enriched = _run_enrich(qualified) if req.enrich_contacts else qualified
    return {
        "total": len(enriched),
        "leads": enriched,
    }


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/docs", include_in_schema=False)
async def custom_docs():
    html = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Pipeline_X SDR API",
        swagger_ui_parameters={"defaultModelsExpandDepth": -1, "tryItOutEnabled": True},
    )
    body = html.body.decode().replace("</head>", f"{_SWAGGER_CSS}</head>")
    return HTMLResponse(body)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["Sistema"])
def health():
    """Estado del servicio."""
    return {"status": "ok", "product": cfg.PRODUCT["name"]}


@app.get("/plans", tags=["Sistema"])
def plans():
    """
    Devuelve todos los planes disponibles con precios, límites y features.
    Usa este endpoint para renderizar la tabla de precios en la landing.
    """
    public = {}
    for tier, plan in cfg.PLANS.items():
        public[tier] = {
            "name":          plan["name"],
            "price_monthly": plan.get("price_monthly"),
            "price_annual":  plan.get("price_annual"),
            "leads_limit":   plan["leads_limit"],
            "description":   plan["description"],
            "features":      plan.get("features", {}),
            "cta":           plan.get("cta", ""),
            "highlight":     plan.get("highlight", False),
        }
        if "slots_total" in plan:
            public[tier]["slots_total"] = plan["slots_total"]
        if "base_tier" in plan:
            public[tier]["base_tier"] = plan["base_tier"]
    return public


@app.post("/scrape", tags=["Leads"])
async def scrape(req: ScrapeRequest, request: Request):
    """
    Busca leads en Google Maps y opcionalmente enriquece con datos de sitios web y SUNAT.
    Operación síncrona — para queries grandes usa /jobs/pipeline.

    El header `X-Plan-Tier` controla el límite de leads y acceso a SUNAT.
    Sin header → tier free (10 leads, sin SUNAT).
    """
    tier = _resolve_tier(request)
    effective_limit, effective_sunat = _enforce_plan(tier, req.limit, req.enrich_sunat)
    try:
        leads = await asyncio.to_thread(
            _run_scrape, req.query, effective_limit, req.enrich_web, effective_sunat
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"total": len(leads), "leads": leads, "plan_tier": tier, "applied_limit": effective_limit}


@app.post("/qualify", tags=["Leads"])
async def qualify(req: QualifyRequest):
    """
    Califica una lista de leads usando Groq.
    Devuelve los leads con score, etapa CRM y borrador de mensaje.
    """
    if not req.leads:
        raise HTTPException(status_code=422, detail="La lista de leads está vacía")
    try:
        result = await asyncio.to_thread(_run_qualify, req.leads, req.channel)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"total": len(result), "leads": result}


@app.post("/enrich", tags=["Leads"])
async def enrich(req: EnrichRequest):
    """
    Enriquece los contactos de una lista de leads (emails, teléfonos, redes sociales).
    """
    if not req.leads:
        raise HTTPException(status_code=422, detail="La lista de leads está vacía")
    try:
        result = await asyncio.to_thread(_run_enrich, req.leads)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"total": len(result), "leads": result}


@app.post("/pipeline", tags=["Pipeline"])
async def pipeline(req: PipelineRequest, request: Request):
    """
    Pipeline completo síncrono: scrape → califica → enriquece.
    Para limite > 20 leads se recomienda usar /jobs/pipeline.

    El header `X-Plan-Tier` controla el límite de leads y acceso a SUNAT.
    Sin header → tier free (10 leads, sin SUNAT).
    """
    tier = _resolve_tier(request)
    effective_limit, effective_sunat = _enforce_plan(tier, req.limit, req.enrich_sunat)
    enforced = req.model_copy(update={"limit": effective_limit, "enrich_sunat": effective_sunat})
    try:
        result = await asyncio.to_thread(_run_pipeline, enforced)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {**result, "plan_tier": tier, "applied_limit": effective_limit}


# ─── Jobs ────────────────────────────────────────────────────────────────────

@app.post("/jobs/pipeline", tags=["Jobs"], status_code=202)
async def jobs_pipeline(req: PipelineRequest, request: Request):
    """
    Lanza el pipeline completo en background y devuelve un job_id.
    Consulta el estado en GET /jobs/{job_id}.

    El header `X-Plan-Tier` controla el límite de leads y acceso a SUNAT.
    Sin header → tier free (10 leads, sin SUNAT).
    """
    tier = _resolve_tier(request)
    effective_limit, effective_sunat = _enforce_plan(tier, req.limit, req.enrich_sunat)
    req = req.model_copy(update={"limit": effective_limit, "enrich_sunat": effective_sunat})
    job_id = _new_job("pipeline", {**req.model_dump(), "plan_tier": tier})

    async def _run():
        _job_running(job_id)
        try:
            result = await asyncio.to_thread(_run_pipeline, req)
            _job_done(job_id, result)
        except Exception as e:
            _job_failed(job_id, str(e))

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "pending"}


@app.get("/jobs/{job_id}", tags=["Jobs"])
def get_job(job_id: str):
    """Estado de un job: pending | running | done | failed."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {
        "id": job["id"],
        "kind": job["kind"],
        "status": job["status"],
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
        "error": job["error"],
    }


@app.get("/jobs/{job_id}/result", tags=["Jobs"])
def get_job_result(job_id: str):
    """Resultado de un job completado."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if job["status"] == "pending":
        raise HTTPException(status_code=202, detail="Job todavía en cola")
    if job["status"] == "running":
        raise HTTPException(status_code=202, detail="Job en ejecución")
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job["error"])
    return job["result"]


# ─── Telegram helpers ─────────────────────────────────────────────────────────

_TG_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_TG_API        = "https://api.telegram.org/bot"
_NOTION_TOKEN  = os.environ.get("NOTION_PIPELINE_TOKEN", "")
_NOTION_DB_ID  = os.environ.get("NOTION_DB_ID", "c8e55705-b3ab-4e79-a977-cd4f7c64dd51")

# Estado de conversación — persistido en archivo JSON para sobrevivir reinicios.
_BOT_STATES_FILE = Path("output/.bot_states.json")


def _load_bot_states() -> dict[int, dict]:
    """Carga el estado del bot desde disco."""
    try:
        data = json.loads(_BOT_STATES_FILE.read_text(encoding="utf-8"))
        return {int(k): v for k, v in data.items()}
    except Exception:
        return {}


def _save_bot_states() -> None:
    """Persiste el estado del bot a disco."""
    try:
        _BOT_STATES_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BOT_STATES_FILE.write_text(
            json.dumps({str(k): v for k, v in _bot_states.items()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


_bot_states: dict[int, dict] = _load_bot_states()


async def _tg_post(method: str, payload: dict) -> None:
    if not _TG_TOKEN:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(f"{_TG_API}{_TG_TOKEN}/{method}", json=payload)


async def _tg_message(chat_id: int, text: str) -> None:
    await _tg_post("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    })


async def _tg_document(chat_id: int, filename: str, content: bytes, caption: str = "") -> None:
    if not _TG_TOKEN:
        return
    async with httpx.AsyncClient(timeout=60) as client:
        await client.post(
            f"{_TG_API}{_TG_TOKEN}/sendDocument",
            data={"chat_id": str(chat_id), "caption": caption, "parse_mode": "Markdown"},
            files={"document": (filename, content, "text/csv; charset=utf-8")},
        )


def _leads_to_csv(leads: list[dict]) -> bytes:
    if not leads:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(leads[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(leads)
    return buf.getvalue().encode("utf-8-sig")  # BOM para Excel


async def _notion_mark_delivered(target: str) -> None:
    """Busca en Notion el lead con ese target y marca Estado = Entregado."""
    if not _NOTION_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Buscar entrada con target coincidente y estado Nuevo
            search = await client.post(
                f"https://api.notion.com/v1/databases/{_NOTION_DB_ID}/query",
                headers={
                    "Authorization": f"Bearer {_NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={"filter": {"property": "Estado", "select": {"equals": "Nuevo"}}},
            )
            pages = search.json().get("results", [])
            # Buscar la página cuyo Target coincida
            page_id = None
            for page in pages:
                props = page.get("properties", {})
                tgt = props.get("Target", {}).get("rich_text", [])
                tgt_val = tgt[0]["text"]["content"] if tgt else ""
                if tgt_val.strip().lower() == target.strip().lower():
                    page_id = page["id"]
                    break
            if not page_id:
                return
            # Actualizar Estado → Entregado
            await client.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers={
                    "Authorization": f"Bearer {_NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={"properties": {"Estado": {"select": {"name": "Entregado"}}}},
            )
    except Exception:
        pass  # No bloquear la entrega si Notion falla


async def _deliver_and_notify(query: str, chat_id: int, limit: int, channel: str, enrich_sunat: bool) -> None:
    """Corre el pipeline y entrega el reporte al chat_id."""
    try:
        req = PipelineRequest(
            query=query, limit=limit, channel=channel,
            enrich_web=True, enrich_sunat=enrich_sunat,
            qualify=True, enrich_contacts=False,
        )
        result = await asyncio.to_thread(_run_pipeline, req)
        leads  = result.get("leads", [])
        total  = result.get("total", len(leads))

        # Resumen: top 5 por score
        qualified = sorted(
            [l for l in leads if l.get("lead_score", 0) >= 60],
            key=lambda x: x.get("lead_score", 0), reverse=True,
        )
        lines = [
            f"✅ *Reporte listo: {query}*",
            f"_{total} leads procesados · {len(qualified)} calificados (score ≥60)_\n",
        ]
        for i, lead in enumerate(qualified[:5], 1):
            empresa = lead.get("empresa", "—")
            score   = lead.get("lead_score", "—")
            stage   = lead.get("crm_stage", "—")
            action  = lead.get("next_action", "—")
            lines.append(f"*{i}. {empresa}* — Score {score} | {stage}")
            lines.append(f"   → {action}")
        if not qualified:
            lines.append("_No se encontraron leads con score ≥60. Revisa el CSV adjunto._")
        lines.append("\n📎 CSV adjunto con todos los leads y borradores de mensaje.")

        await _tg_message(chat_id, "\n".join(lines))

        csv_bytes = _leads_to_csv(leads)
        safe_name = query[:30].replace(" ", "_").replace("/", "-")
        await _tg_document(chat_id, f"pipeline_x_{safe_name}.csv", csv_bytes,
                           caption=f"📊 Leads: {query}")

        # Marcar lead como Entregado en Notion
        await _notion_mark_delivered(query)

    except Exception as exc:
        await _tg_message(chat_id, f"❌ Error procesando el reporte.\n`{str(exc)[:300]}`")


async def _demo_deliver_and_capture(target: str, chat_id: int) -> None:
    """
    Flujo demo desde landing (deep link ?start=demo):
    1. Corre pipeline con límite free (10 leads, sin SUNAT)
    2. Entrega resumen + CSV
    3. Muestra oferta Starter y pide email para activar acceso
    """
    try:
        req = PipelineRequest(
            query=target,
            limit=cfg.DEMO_REQUEST_LEADS_LIMIT,
            channel="email",
            enrich_web=True,
            enrich_sunat=False,   # Sin SUNAT en tier free
            qualify=True,
            enrich_contacts=False,
        )
        result = await asyncio.to_thread(_run_pipeline, req)
        leads  = result.get("leads", [])
        total  = result.get("total", len(leads))

        qualified = sorted(
            [l for l in leads if l.get("lead_score", 0) >= 60],
            key=lambda x: x.get("lead_score", 0), reverse=True,
        )

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

        await _tg_message(chat_id, "\n".join(lines))

        csv_bytes = _leads_to_csv(leads)
        safe_name = target[:30].replace(" ", "_").replace("/", "-")
        await _tg_document(chat_id, f"pipeline_x_demo_{safe_name}.csv", csv_bytes,
                           caption=f"📊 Demo gratuita — {target}")

        # Actualizar estado: esperando email
        _bot_states[chat_id] = {"flow": "demo_collecting_email", "target": target}
        _save_bot_states()

        await _tg_message(chat_id,
            "Esto es el *10% de lo que Pipeline_X entrega en Starter.*\n\n"
            "Con el plan completo ($39/mes):\n"
            "- 200 leads/mes en vez de 10\n"
            "- Enriquecimiento SUNAT (capacidad de pago real)\n"
            "- Reporte HTML con métricas\n\n"
            "¿Querés activar el acceso completo? *Escribí tu email* y te lo activo hoy."
        )

    except Exception as exc:
        log.error("Demo deliver error chat=%d: %s", chat_id, exc)
        _bot_states.pop(chat_id, None)
        _save_bot_states()
        await _tg_message(chat_id,
            "Hubo un problema procesando tu búsqueda.\n"
            "Intenta con otro sector o ciudad, o escríbenos a contacto@pipelinex.io"
        )


# ─── Demo Request endpoint ────────────────────────────────────────────────────

_DEMO_STORE = Path("output/.demo_requests.json")

def _load_demo_store() -> list[dict]:
    if _DEMO_STORE.exists():
        try:
            return json.loads(_DEMO_STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _save_demo_store(data: list[dict]) -> None:
    _DEMO_STORE.parent.mkdir(parents=True, exist_ok=True)
    _DEMO_STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class DemoRequest(BaseModel):
    nombre:    str = Field(..., min_length=2)
    empresa:   str = Field(..., min_length=2)
    ruc:       str = Field(..., pattern=r"^\d{8}$|^\d{11}$")
    email:     str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
    industria: str = Field(..., min_length=2)
    ciudad:    str = Field(..., min_length=2)


@app.post("/demo-request", tags=["Pipeline"], status_code=202)
async def demo_request(req: DemoRequest, request: Request):
    """
    Registra una solicitud de demo gratuita desde la landing.
    Deduplica por email y RUC. Lanza pipeline en background y notifica al admin.
    """
    records = _load_demo_store()

    # Deduplicación
    for r in records:
        if r["email"].lower() == req.email.lower():
            raise HTTPException(status_code=409, detail="Email ya registrado para una demo")
        if r["ruc"] == req.ruc:
            raise HTTPException(status_code=409, detail="RUC ya registrado para una demo")

    # Guardar registro
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    record = {
        "nombre":    req.nombre,
        "empresa":   req.empresa,
        "ruc":       req.ruc,
        "email":     req.email,
        "industria": req.industria,
        "ciudad":    req.ciudad,
        "ip":        ip,
        "ts":        datetime.now(timezone.utc).isoformat(),
        "status":    "pending",
    }
    records.append(record)
    _save_demo_store(records)
    log.info("Demo solicitada: %s (%s) RUC=%s", req.empresa, req.email, req.ruc)

    # Notificar al admin vía Telegram (usa bot externo Alex que ya está configurado)
    admin_id = os.environ.get("ADMIN_CHAT_ID")
    if admin_id:
        msg = (
            f"🆕 *Nueva demo solicitada*\n\n"
            f"*Empresa:* {req.empresa}\n"
            f"*RUC:* `{req.ruc}`\n"
            f"*Contacto:* {req.nombre}\n"
            f"*Email:* {req.email}\n"
            f"*Industria:* {req.industria}\n"
            f"*Ciudad:* {req.ciudad}"
        )
        asyncio.create_task(_tg_message(int(admin_id), msg))

    # Lanzar pipeline en background y entregar CSV al admin
    # Usa el límite del tier free (DEMO_REQUEST_LEADS_LIMIT = 10 leads)
    if admin_id:
        query = f"{req.industria} en {req.ciudad}"
        asyncio.create_task(
            _deliver_and_notify(
                query, int(admin_id),
                limit=cfg.DEMO_REQUEST_LEADS_LIMIT,
                channel="email",
                enrich_sunat=False,
            )
        )

    return {"ok": True, "message": "Demo en proceso"}


# ─── Deliver endpoint ─────────────────────────────────────────────────────────

class DeliverRequest(BaseModel):
    query:        str     = Field(..., description='Target de prospección, ej: "Ferreterías en Trujillo"')
    chat_id:      int     = Field(..., description="Telegram chat_id del destinatario")
    channel:      Literal["email", "whatsapp", "both"] = Field("whatsapp")
    limit:        int     = Field(20, ge=1, le=50)
    enrich_sunat: bool    = Field(False)


@app.post("/deliver", tags=["Pipeline"], status_code=202)
async def deliver(req: DeliverRequest):
    """
    Lanza el pipeline completo en background y entrega el CSV al chat_id de Telegram.
    No bloquea — devuelve job_id inmediatamente.
    """
    job_id = _new_job("deliver", req.model_dump())

    async def _bg() -> None:
        _job_running(job_id)
        try:
            await _deliver_and_notify(
                req.query, req.chat_id, req.limit, req.channel, req.enrich_sunat
            )
            _job_done(job_id, {"query": req.query, "chat_id": req.chat_id})
        except Exception as exc:
            _job_failed(job_id, str(exc))

    asyncio.create_task(_bg())
    return {"job_id": job_id, "status": "pending"}


# ─── Telegram webhook ─────────────────────────────────────────────────────────
# Alex prompt — importado desde telegram_bot para no duplicarlo.
# Importación lazy para evitar efectos en módulos que no usan el bot.
def _get_alex_prompt() -> str:
    try:
        from telegram_bot import SYSTEM_PROMPT
        return SYSTEM_PROMPT
    except Exception:
        return "Eres Alex, el asistente de ventas de Pipeline_X. Responde en español neutro."


def _alex_reply(chat_id: int, user_text: str) -> str:
    """Genera respuesta conversacional de Alex (texto libre).
    Prioridad: Anthropic → Groq. Ninguno disponible → mensaje estático."""
    state = _bot_states.setdefault(chat_id, {})
    history: list[dict] = state.setdefault("history", [])

    history.append({"role": "user", "content": user_text})
    if len(history) > 20:
        history[:] = history[-20:]

    system_prompt = _get_alex_prompt()

    # ── Anthropic (Claude) ──────────────────────────────────────────────────
    claude_key = os.environ.get("ANTHROPIC_API_KEY")
    if claude_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=claude_key)
            resp = client.messages.create(
                model=cfg.CLAUDE["model"],
                max_tokens=400,
                system=system_prompt,
                messages=history,
                temperature=1,  # Claude no acepta 0 en modo conversacional
            )
            reply = resp.content[0].text.strip() if resp.content else ""
            if reply:
                history.append({"role": "assistant", "content": reply})
                _save_bot_states()
                return reply
        except Exception:
            pass  # Intentar con Groq si falla

    # ── Groq (fallback) ─────────────────────────────────────────────────────
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            messages = [{"role": "system", "content": system_prompt}] + history
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.7,
                max_tokens=400,
            )
            reply = (resp.choices[0].message.content or "").strip()
            if reply:
                history.append({"role": "assistant", "content": reply})
                _save_bot_states()
                return reply
        except Exception:
            pass

    # ── Sin LLM disponible ──────────────────────────────────────────────────
    history.pop()  # Revertir el mensaje que se agregó
    return (
        "Hola 👋 Soy *Pipeline_X*.\n\n"
        "Puedo generarte un reporte de prospectos calificados.\n"
        "Escribe /start reporte para comenzar."
    )


@app.post("/webhook/telegram", include_in_schema=False)
async def telegram_webhook(request: Request):
    """
    Recibe updates de Telegram (registrar con setWebhook apuntando a esta URL).
    Flujos:
      /start reporte  → solicita target → corre /deliver → entrega CSV
      cualquier otro  → bot de ventas Alex (Groq)
    """
    # Verificar token secreto si está configurado
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if secret:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != secret:
            raise HTTPException(status_code=403, detail="Forbidden")

    update = await request.json()

    message = update.get("message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text    = (message.get("text") or "").strip()
    if not text:
        return {"ok": True}

    state = _bot_states.get(chat_id, {})

    # ── /start ────────────────────────────────────────────────────────────────
    if text.startswith("/start"):
        payload = text[6:].strip()
        _bot_states[chat_id] = {}  # reset

        if payload == "reporte":
            _bot_states[chat_id] = {"flow": "report"}
            await _tg_message(chat_id,
                "Hola 👋 Soy *Pipeline_X*.\n\n"
                "Vi que solicitaste un reporte desde nuestra web.\n\n"
                "¿Cuál es el target exacto que quieres prospectar?\n"
                "_Escríbelo así: Industria en Ciudad_\n\n"
                "Ej: `Ferreterías en Trujillo`"
            )
        elif payload == "demo":
            # Deep link desde landing: t.me/<bot>?start=demo
            # Entrega valor primero (10 leads gratis), pide datos después.
            _bot_states[chat_id] = {"flow": "demo"}
            await _tg_message(chat_id,
                "Hola 👋 Voy a generarte *10 leads reales* ahora mismo, sin tarjeta.\n\n"
                "¿Qué tipo de empresa estás prospectando?\n"
                "_Ej: Ferreterías en Trujillo · Clínicas en Bogotá_"
            )
        else:
            reply = await asyncio.to_thread(_alex_reply, chat_id, "/start")
            await _tg_message(chat_id, reply)
        _save_bot_states()
        return {"ok": True}

    # ── Flujo de reporte (admin): esperando target ────────────────────────────
    if state.get("flow") == "report":
        target = text
        _bot_states[chat_id] = {}
        _save_bot_states()
        asyncio.create_task(
            _deliver_and_notify(target, chat_id, limit=30, channel="whatsapp", enrich_sunat=True)
        )
        await _tg_message(chat_id,
            f"✅ *Recibido:* `{target}`\n\n"
            "Estoy escaneando Google Maps y cruzando datos SUNAT.\n"
            "Te aviso cuando el reporte esté listo _(aprox 5–15 min)_."
        )
        return {"ok": True}

    # ── Flujo demo (usuarios desde landing): esperando target ─────────────────
    if state.get("flow") == "demo":
        target = text
        _bot_states[chat_id] = {**state, "flow": "demo_running", "target": target}
        _save_bot_states()
        await _tg_message(chat_id,
            f"Buscando *{target}* en Google Maps y calificando con IA...\n"
            "_Listo en aprox. 2–5 minutos._"
        )
        # Tier free: 10 leads, sin SUNAT
        asyncio.create_task(
            _demo_deliver_and_capture(target, chat_id)
        )
        return {"ok": True}

    # ── Flujo demo: capturando email post-entrega ─────────────────────────────
    if state.get("flow") == "demo_collecting_email":
        email = text.strip()
        target = state.get("target", "")
        _bot_states[chat_id] = {}
        _save_bot_states()

        # Guardar en el mismo store que /demo-request
        records = _load_demo_store()
        if not any(r.get("email", "").lower() == email.lower() for r in records):
            from datetime import timezone
            records.append({
                "nombre": "", "empresa": "", "ruc": "",
                "email": email, "industria": target, "ciudad": "",
                "ip": f"telegram:{chat_id}",
                "ts": datetime.now(timezone.utc).isoformat(),
                "status": "demo_telegram",
            })
            _save_demo_store(records)
        log.info("Demo email capturado vía webhook: chat=%d email=%s target=%r", chat_id, email, target)

        await _tg_message(chat_id,
            f"Listo. Te contactamos a *{email}* para activar tu acceso.\n\n"
            "Normalmente lo hacemos en menos de 2 horas en horario hábil."
        )
        return {"ok": True}

    # ── Bot de ventas Alex ────────────────────────────────────────────────────
    reply = await asyncio.to_thread(_alex_reply, chat_id, text)
    await _tg_message(chat_id, reply)
    return {"ok": True}


# ─── WhatsApp webhook (Green API) ─────────────────────────────────────────────

@app.post("/webhook/whatsapp", include_in_schema=False)
async def whatsapp_webhook(request: Request):
    """
    Recibe mensajes entrantes de WhatsApp via Green API.

    Configurar en Green API console (o via wa_sender.set_webhook):
      POST /waInstance{id}/setSettings/{token}
      {"webhookUrl": "https://TU_DOMINIO/webhook/whatsapp", "incomingWebhook": "yes"}
    """
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    import wa_bot
    import wa_sender

    parsed = wa_bot.parse_green_api_payload(payload)
    if parsed is None:
        return {"ok": True}   # ignorar eventos que no son mensajes de texto

    phone, text = parsed
    id_message  = (payload.get("idMessage") or
                   payload.get("messageData", {}).get("idMessage", ""))

    # Marcar como leído (ticks azules)
    if id_message:
        await asyncio.to_thread(wa_sender.mark_read, phone, id_message)

    # Procesar y responder
    reply = await asyncio.to_thread(wa_bot.handle_message, phone, text)
    await asyncio.to_thread(wa_sender.send_text, phone, reply)

    return {"ok": True}
