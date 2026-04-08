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

Variables de entorno requeridas:
  GROQ_API_KEY   — clave de API de Groq
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

import config as cfg

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


@app.post("/scrape", tags=["Leads"])
async def scrape(req: ScrapeRequest):
    """
    Busca leads en Google Maps y opcionalmente enriquece con datos de sitios web y SUNAT.
    Operación síncrona — para queries grandes usa /jobs/pipeline.
    """
    loop = asyncio.get_event_loop()
    try:
        leads = await loop.run_in_executor(
            None, _run_scrape, req.query, req.limit, req.enrich_web, req.enrich_sunat
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"total": len(leads), "leads": leads}


@app.post("/qualify", tags=["Leads"])
async def qualify(req: QualifyRequest):
    """
    Califica una lista de leads usando Groq.
    Devuelve los leads con score, etapa CRM y borrador de mensaje.
    """
    if not req.leads:
        raise HTTPException(status_code=422, detail="La lista de leads está vacía")
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _run_qualify, req.leads, req.channel)
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
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _run_enrich, req.leads)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"total": len(result), "leads": result}


@app.post("/pipeline", tags=["Pipeline"])
async def pipeline(req: PipelineRequest):
    """
    Pipeline completo síncrono: scrape → califica → enriquece.
    Para limite > 20 leads se recomienda usar /jobs/pipeline.
    """
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _run_pipeline, req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


# ─── Jobs ────────────────────────────────────────────────────────────────────

@app.post("/jobs/pipeline", tags=["Jobs"], status_code=202)
async def jobs_pipeline(req: PipelineRequest):
    """
    Lanza el pipeline completo en background y devuelve un job_id.
    Consulta el estado en GET /jobs/{job_id}.
    """
    job_id = _new_job("pipeline", req.model_dump())

    async def _run():
        _job_running(job_id)
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _run_pipeline, req)
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
