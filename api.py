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
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config as cfg
import constants as const

log = logging.getLogger("api")

API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL") or os.environ.get("BASE_URL") or "https://agentepyme-api-production.up.railway.app"
REPORTS_DIR = Path("output/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Plan helpers ─────────────────────────────────────────────────────────────

def _resolve_tier(request: Request) -> str:
    """Resuelve el tier del usuario desde la DB usando X-User-Phone. Default: 'free'."""
    phone = request.headers.get("X-User-Phone", "").strip()
    if not phone:
        return const.PlanTier.FREE
    
    import db as _db
    subscriber = _db.get_subscriber(phone)
    if not subscriber:
        return const.PlanTier.FREE
    
    if subscriber.get("status") != "active":
        return const.PlanTier.FREE
    
    expires_at = subscriber.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc).isoformat():
        return const.PlanTier.FREE
    
    return subscriber.get("plan", const.PlanTier.FREE)


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
        import asyncio
        # python-telegram-bot v21 requiere un event loop en el hilo.
        # El hilo principal ya tiene uno (uvicorn), pero este hilo no.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import bot_interno
            log.info("PipeAssist iniciando en hilo de fondo...")
            bot_interno.main(embedded=True)
        except Exception as e:
            log.error("PipeAssist falló: %s", e, exc_info=True)
        finally:
            loop.close()

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


async def _followup_loop() -> None:
    """
    Cada hora busca usuarios free que recibieron un reporte ~24h atrás
    y les envía un mensaje de seguimiento para reactivarlos.
    """
    import wa_sender
    from messages import MSG
    await asyncio.sleep(120)   # esperar a que el bot esté completamente listo
    while True:
        try:
            candidates = await asyncio.to_thread(_db.get_followup_candidates)
            if candidates:
                log.info("Followup 24h: %d candidatos", len(candidates))
            # Obtener phones unsubscribed una sola vez antes del loop
            unsubscribed = await asyncio.to_thread(_db.get_unsubscribed_phones)
            for phone in candidates:
                if phone in unsubscribed:
                    log.info("Followup omitido (unsubscribed): phone=%s", phone)
                    await asyncio.sleep(2)
                    continue
                try:
                    await asyncio.to_thread(
                        wa_sender.send_text, phone, MSG["followup_24h"]
                    )
                    _db.log_event(phone, _db.EventType.WA_FOLLOWUP_SENT)
                    log.info("Followup enviado: phone=%s", phone)
                except Exception as send_exc:
                    log.warning("Followup error phone=%s: %s", phone, send_exc)
                await asyncio.sleep(2)   # pequeño delay entre envíos
        except Exception as exc:
            log.warning("followup_loop error: %s", exc)
        await asyncio.sleep(3600)   # revisar cada hora


async def _trial_expired_loop() -> None:
    """
    Cada 6 horas detecta trials expirados y envía mensaje proactivo
    recordando la búsqueda gratis + opciones de upgrade.
    """
    import wa_sender
    from messages import MSG
    await asyncio.sleep(180)   # esperar arranque completo
    while True:
        try:
            candidates = await asyncio.to_thread(_db.get_expired_trial_candidates)
            if candidates:
                log.info("Trial expirado: %d candidatos para notificar", len(candidates))
            # Obtener phones unsubscribed una sola vez antes del loop
            unsubscribed = await asyncio.to_thread(_db.get_unsubscribed_phones)
            for phone in candidates:
                if phone in unsubscribed:
                    log.info("Trial expired omitido (unsubscribed): phone=%s", phone)
                    await asyncio.sleep(2)
                    continue
                try:
                    await asyncio.to_thread(
                        wa_sender.send_text, phone, MSG["trial_expired"]
                    )
                    _db.log_event(phone, _db.EventType.WA_TRIAL_EXPIRED)
                    log.info("Trial expired msg enviado: phone=%s", phone)
                except Exception as send_exc:
                    log.warning("Trial expired error phone=%s: %s", phone, send_exc)
                await asyncio.sleep(2)
        except Exception as exc:
            log.warning("trial_expired_loop error: %s", exc)
        await asyncio.sleep(6 * 3600)   # revisar cada 6h


def _next_lima_occurrence(hour: int) -> float:
    """
    Devuelve los segundos hasta la próxima vez que sean `hour`:00 en Lima (UTC-5).
    Siempre devuelve un valor > 0 (mínimo 60s para evitar disparos dobles).
    """
    from datetime import datetime, timezone, timedelta
    LIMA = timezone(timedelta(hours=-5))
    now  = datetime.now(LIMA)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    secs = (target - now).total_seconds()
    return max(secs, 60.0)


async def _build_digest(period_label: str, hours: int, include_weekly: bool) -> str:
    stats = await asyncio.to_thread(_db.get_stats, hours // 24 or 1)
    lines = [f"📊 *{period_label} — Pipeline_X*\n"]

    lines += [
        f"🔍 Búsquedas: {stats.get('searches', 0)}",
        f"📎 Reportes entregados: {stats.get('reports_delivered', 0)}",
        f"💰 Clics upgrade: {stats.get('upgrade_clicks', 0)}",
        f"✅ Activaciones: {stats.get('activations', 0)}",
        f"💎 Suscriptores activos: {stats.get('active_subscribers', 0)}",
        f"🔄 Búsqueda→Upgrade: {stats.get('conversion', {}).get('search_to_upgrade', '—')}",
        f"💳 Upgrade→Pago: {stats.get('conversion', {}).get('upgrade_to_paid', '—')}",
    ]

    if include_weekly:
        stats7 = await asyncio.to_thread(_db.get_stats, 7)
        top = stats7.get("top_searches", [])
        if top:
            lines.append("\n*Top búsquedas (7d)*")
            for item in top[:3]:
                lines.append(f"  · {item['target']} ({item['count']}x)")

    return "\n".join(lines)


async def _digest_scheduler() -> None:
    """
    Envía resumen al CEO via PipeAssist:
      - 8:00 AM Lima → buenos días + resumen últimas 24h + top búsquedas semana
      - 8:00 PM Lima → buenas noches + resumen del día (últimas 12h)
    """
    await asyncio.sleep(30)  # esperar arranque completo
    while True:
        # Calcular cuánto falta para el próximo hito (8 AM o 8 PM Lima)
        secs_morning = _next_lima_occurrence(8)
        secs_evening = _next_lima_occurrence(20)
        sleep_secs   = min(secs_morning, secs_evening)
        is_morning   = secs_morning <= secs_evening

        await asyncio.sleep(sleep_secs)

        try:
            if is_morning:
                msg = await _build_digest("☀️ Buenos días", hours=24, include_weekly=True)
            else:
                msg = await _build_digest("🌙 Cierre del día", hours=12, include_weekly=False)
            await _notify_pipeassist(msg)
            log.info("Digest enviado (%s)", "mañana" if is_morning else "tarde")
        except Exception as exc:
            log.warning("digest_scheduler error: %s", exc)

        await asyncio.sleep(60)  # evitar doble disparo dentro del mismo minuto


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging_config
    logging_config.setup()
    # Inicializar PostgreSQL primero (sesiones, jobs, bot_states)
    await asyncio.to_thread(_db.init)
    _start_bot_interno()
    await asyncio.to_thread(_register_whatsapp_webhook)
    asyncio.create_task(_followup_loop())
    asyncio.create_task(_trial_expired_loop())
    asyncio.create_task(_digest_scheduler())
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

app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


@app.get("/r/{token}", include_in_schema=False)
async def short_report_redirect(token: str):
    """Redirect corto: /r/TOKEN → /reports/TOKEN.pdf"""
    from fastapi.responses import RedirectResponse
    path = REPORTS_DIR / f"{token}.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Reporte no encontrado o expirado")
    return RedirectResponse(url=f"/reports/{token}.pdf")

def _get_allowed_origins() -> list[str]:
    """Lee CORS_ORIGINS desde variable de entorno, permite empty para server-to-server."""
    env = os.environ.get("CORS_ORIGINS", "").strip()
    if not env:
        return []
    return [o.strip() for o in env.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Phone"],
)

# ─── Job store (PostgreSQL vía db.py) ────────────────────────────────────────

import db as _db


def _new_job(kind: str, params: dict) -> str:
    return _db.new_job(kind, params)


def _job_running(job_id: str) -> None:
    _db.update_job(job_id, "running")


def _job_done(job_id: str, result: Any) -> None:
    _db.update_job(job_id, "done", result=result)


def _job_failed(job_id: str, error: str) -> None:
    _db.update_job(job_id, "failed", error=error)


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


# ─── Auth schemas ───────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    phone: str = Field(..., description="Número de WhatsApp (formato: 51xxxxxxxxx)")
    name: Optional[str] = Field(None, description="Nombre del usuario")
    utm_source: Optional[str] = Field(None, description="utm_source para tracking")
    utm_medium: Optional[str] = Field(None, description="utm_medium para tracking")
    referral_code: Optional[str] = Field(None, description="Código de referido (opcional)")


class SignupResponse(BaseModel):
    phone: str
    plan: str
    trial_days: int
    message: str


class LoginRequest(BaseModel):
    phone: str


class LoginResponse(BaseModel):
    phone: str
    plan: str
    status: str
    expires_at: Optional[str]


class PaymentLinkRequest(BaseModel):
    plan: str = Field(..., description="Plan a comprar: basico, starter, pro, enterprise")


class PaymentLinkResponse(BaseModel):
    payment_url: str
    plan: str
    amount_soles: int
    expires_at: str


# ─── Auth helpers ──────────────────────────────────────────────────────────────

_API_KEY = os.environ.get("PIPELINE_X_API_KEY", "")

def _generate_token(phone: str) -> str:
    """Genera un token simple basado en phone + secret."""
    if not _API_KEY:
        return secrets.token_urlsafe(32)
    payload = f"{phone}:{time.time()}"
    return hmac.new(_API_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


# ─── Auth endpoints ───────────────────────────────────────────────────────────

@app.post("/auth/signup", response_model=SignupResponse, tags=["Auth"])
async def signup(req: SignupRequest, request: Request):
    """
    Registra un nuevo usuario y activa trial de 3 días.
    El usuario recibirá un código por WhatsApp para verificar su número.
    Optionally accepts a referral_code to track referrals.
    """
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="Teléfono requerido")
    
    phone = phone.replace("+51", "51").replace(" ", "").replace("-", "")
    if not phone.isdigit() or len(phone) < 9:
        raise HTTPException(status_code=400, detail="Teléfono inválido")
    
    existing = _db.get_subscriber(phone)
    if existing and existing.get("status") == "active":
        return SignupResponse(
            phone=phone,
            plan=existing.get("plan", "free"),
            trial_days=0,
            message="Ya tienes una cuenta activa"
        )
    
    utm_data = {}
    if req.utm_source:
        utm_data["utm_source"] = req.utm_source
    if req.utm_medium:
        utm_data["utm_medium"] = req.utm_medium
    
    # Apply referral code if provided
    referral_applied = False
    referral_message = ""
    if req.referral_code:
        code_info = await asyncio.to_thread(_db.validate_referral_code, req.referral_code)
        if code_info:
            # Apply referral - creates pending reward
            result = await asyncio.to_thread(_db.apply_referral, req.referral_code, phone)
            if result:
                referral_applied = True
                utm_data["referral_code"] = req.referral_code
                utm_data["referrer_phone"] = code_info["referrer_phone"]
                referral_message = " ¡Usaste un código de referido!"
    
    if utm_data:
        notes = json.dumps(utm_data)
    else:
        notes = ""
    
    _db.upsert_subscriber(phone, plan="trial", days=3, notes=notes)
    
    if req.name:
        _db.save_user_profile(phone, name=req.name)
    
    token = _generate_token(phone)
    _db.save_api_token(phone, token)
    
    return SignupResponse(
        phone=phone,
        plan="trial",
        trial_days=3,
        message=f"¡Bienvenido! Tienes 3 días de acceso completo gratis.{referral_message}"
    )


@app.post("/auth/profile", tags=["Auth"])
async def update_profile(
    name: Optional[str] = None,
    email: Optional[str] = None,
    empresa: Optional[str] = None,
    leads_mensuales: Optional[str] = None,
    request: Request = None
):
    """
    Actualiza el perfil del usuario (datos adicionales del formulario).
    """
    phone = request.headers.get("X-User-Phone", "").strip()
    if not phone:
        raise HTTPException(status_code=401, detail="X-User-Phone requerido")
    
    phone = phone.replace("+51", "51").replace(" ", "").replace("-", "")
    
    _db.save_user_profile(
        phone,
        name=name,
        email=email,
        empresa=empresa,
        leads_mensuales=leads_mensuales
    )
    
    return {"ok": True, "message": "Perfil actualizado"}


@app.get("/auth/profile", tags=["Auth"])
async def get_profile(request: Request):
    """Obtiene el perfil del usuario."""
    phone = request.headers.get("X-User-Phone", "").strip()
    if not phone:
        raise HTTPException(status_code=401, detail="X-User-Phone requerido")
    
    profile = _db.get_user_profile(phone)
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    
    return profile


@app.post("/auth/login", response_model=LoginResponse, tags=["Auth"])
async def login(req: LoginRequest, request: Request):
    """
    Autentica al usuario y devuelve su información de suscripción.
    """
    phone = req.phone.strip().replace("+51", "51").replace(" ", "").replace("-", "")
    
    subscriber = _db.get_subscriber(phone)
    if not subscriber:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    is_active = (
        subscriber.get("status") == "active" and
        (not subscriber.get("expires_at") or 
         subscriber.get("expires_at") > datetime.now(timezone.utc).isoformat())
    )
    
    plan = subscriber.get("plan", "free") if is_active else "free"
    status = "active" if is_active else "expired"
    
    return LoginResponse(
        phone=phone,
        plan=plan,
        status=status,
        expires_at=subscriber.get("expires_at")
    )


@app.post("/auth/token", tags=["Auth"])
async def get_token(request: Request):
    """
    Obtiene un token de API para usar en llamadas subsecuentes.
    Requiere header X-User-Phone.
    """
    phone = request.headers.get("X-User-Phone", "").strip()
    if not phone:
        raise HTTPException(status_code=401, detail="X-User-Phone requerido")
    
    token = _db.get_api_token(phone)
    if not token:
        token = _generate_token(phone)
        _db.save_api_token(phone, token)
    
    return {"token": token}


@app.post("/auth/payment-link", response_model=PaymentLinkResponse, tags=["Auth"])
async def payment_link(req: PaymentLinkRequest, request: Request):
    """
    Genera un link de pago (Yape/Plin) para el plan seleccionado.
    Requiere header X-User-Phone.
    """
    phone = request.headers.get("X-User-Phone", "").strip()
    if not phone:
        raise HTTPException(status_code=401, detail="X-User-Phone requerido")
    
    phone = phone.replace("+51", "51").replace(" ", "").replace("-", "")
    
    plan = req.plan.lower()
    plan_config = cfg.PLANS.get(plan)
    if not plan_config:
        raise HTTPException(status_code=400, detail="Plan no válido")
    
    amount = plan_config.get("price_soles", 0)
    if amount == 0:
        raise HTTPException(status_code=400, detail="Plan gratuito, no requiere pago")
    
    payment_id = f"pay_{phone[:6]}_{int(time.time())}"
    payment_url = f"https://yape.com.pe/{payment_id}"
    
    _db.save_payment_link(phone, payment_id, plan, amount)
    
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    
    return PaymentLinkResponse(
        payment_url=payment_url,
        plan=plan,
        amount_soles=amount,
        expires_at=expires.isoformat()
    )


# ─── Referral endpoints ───────────────────────────────────────────────────────

class ReferralCodeResponse(BaseModel):
    code: str
    plan: str
    max_referrals: int
    used_count: int
    remaining: int
    expires_at: str
    share_url: str


class ReferralInfoResponse(BaseModel):
    code: str
    referrer_phone: str
    plan: str
    remaining: int


class ReferralStatsResponse(BaseModel):
    total: int
    activated: int
    pending: int
    rewards: list[dict]


@app.post("/auth/referral/generate", response_model=ReferralCodeResponse, tags=["Referrals"])
async def generate_referral(request: Request):
    """
    Genera un código de referido único para el usuario.
    Requiere header X-User-Phone.
    
    El código puede compartirse con otros usuarios. Cuando el referido
    compra un plan, el referidor gana 1 mes gratis.
    """
    phone = request.headers.get("X-User-Phone", "").strip()
    if not phone:
        raise HTTPException(status_code=401, detail="X-User-Phone requerido")
    
    phone = phone.replace("+51", "51").replace(" ", "").replace("-", "")
    
    subscriber = _db.get_subscriber(phone)
    if not subscriber or subscriber.get("status") != "active":
        raise HTTPException(status_code=403, detail="Solo usuarios activos pueden generar códigos de referido")
    
    code_info = await asyncio.to_thread(_db.get_referral_code, phone)
    if not code_info:
        raise HTTPException(status_code=500, detail="Error generando código de referido")
    
    base_url = os.environ.get("BASE_URL", "https://pipelinex.app")
    share_url = f"{base_url}?ref={code_info['code']}"
    
    return ReferralCodeResponse(
        code=code_info["code"],
        plan=code_info["plan"],
        max_referrals=code_info["max_referrals"],
        used_count=code_info["used_count"],
        remaining=code_info["max_referrals"] - code_info["used_count"],
        expires_at=code_info["expires_at"],
        share_url=share_url,
    )


@app.get("/auth/referral/{code}", response_model=ReferralInfoResponse, tags=["Referrals"])
async def get_referral_info(code: str):
    """
    Obtiene información de un código de referido.
    Público (no requiere autenticación).
    """
    code_info = await asyncio.to_thread(_db.validate_referral_code, code)
    if not code_info:
        raise HTTPException(status_code=404, detail="Código de referido inválido o expirado")
    
    return ReferralInfoResponse(
        code=code_info["code"],
        referrer_phone=code_info["referrer_phone"][:6] + "****",
        plan=code_info["plan"],
        remaining=code_info["remaining"],
    )


@app.get("/auth/referrals", response_model=ReferralStatsResponse, tags=["Referrals"])
async def get_my_referrals(request: Request):
    """
    Obtiene los referidos del usuario autenticado.
    Requiere header X-User-Phone.
    """
    phone = request.headers.get("X-User-Phone", "").strip()
    if not phone:
        raise HTTPException(status_code=401, detail="X-User-Phone requerido")
    
    phone = phone.replace("+51", "51").replace(" ", "").replace("-", "")
    
    stats = await asyncio.to_thread(_db.get_referral_stats, phone)
    rewards = await asyncio.to_thread(_db.get_referral_rewards, phone)
    
    for r in rewards:
        if r.get("referred_phone"):
            r["referred_phone"] = r["referred_phone"][:6] + "****"
    
    return ReferralStatsResponse(
        total=stats["total"],
        activated=stats["activated"],
        pending=stats["pending"],
        rewards=rewards,
    )


# ─── Helpers async ───────────────────────────────────────────────────────────

def _run_scrape(query: str, limit: int, enrich_web: bool, enrich_sunat: bool) -> list[dict]:
    from scraper import scrape_google_maps, enrich_leads
    leads = scrape_google_maps(query, limit)
    if enrich_web:
        leads = enrich_leads(leads, use_sunat=enrich_sunat)
    return leads


def _run_qualify(leads: list[dict], channel: str) -> list[dict]:
    from sdr_agent import qualify_batch
    return qualify_batch(leads, channel)


def _run_enrich(leads: list[dict]) -> list[dict]:
    from contact_enricher import enrich_leads
    return enrich_leads(leads)


def _run_pipeline(req: PipelineRequest) -> dict:
    log.info("Pipeline start: query=%s limit=%d", req.query, req.limit)
    leads = _run_scrape(req.query, req.limit, req.enrich_web, req.enrich_sunat)
    log.info("After scrape: %d leads", len(leads))
    qualified = _run_qualify(leads, req.channel) if req.qualify else leads
    log.info("After qualify: %d leads", len(qualified))
    enriched = _run_enrich(qualified) if req.enrich_contacts else qualified
    log.info("Pipeline end: total=%d", len(enriched))
    return {
        "total": len(enriched),
        "leads": enriched,
    }


def _save_report_bytes(data: bytes) -> str:
    token = secrets.token_urlsafe(8)
    path = REPORTS_DIR / f"{token}.pdf"
    path.write_bytes(data)
    log.info("PDF saved: token=%s size=%d bytes", token, len(data))
    return token


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
async def health():
    """Estado del servicio — incluye checks de Groq y PostgreSQL."""
    import time as _time

    checks: dict[str, str] = {}

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    try:
        def _ping_db() -> bool:
            import db as _db_mod
            if not _db_mod._USE_DB:
                return False
            with _db_mod._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return True
        db_ok = await asyncio.to_thread(_ping_db)
        checks["db"] = "ok" if db_ok else "fallback_file"
    except Exception as exc:
        checks["db"] = f"error: {str(exc)[:80]}"

    # ── Groq ──────────────────────────────────────────────────────────────────
    try:
        def _ping_groq() -> bool:
            import groq as _groq_lib
            client = _groq_lib.Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
            r = client.chat.completions.create(
                model=cfg.GROQ["model"],
                messages=[{"role": "user", "content": "ok"}],
                max_tokens=3,
                timeout=8,
            )
            return bool(r.choices)
        groq_ok = await asyncio.to_thread(_ping_groq)
        checks["groq"] = "ok" if groq_ok else "no_response"
    except Exception as exc:
        checks["groq"] = f"error: {str(exc)[:80]}"

    # ── Green API ─────────────────────────────────────────────────────────────
    try:
        import wa_sender
        state = await asyncio.to_thread(wa_sender.get_state)
        checks["green_api"] = state
    except Exception:
        checks["green_api"] = "unconfigured"

    # ── API keys disponibles ────────────────────────────────────────────────
    checks["apify"] = "ok" if cfg.APIFY_API_KEY else "missing"
    checks["serpapi"] = "ok" if cfg.SERPAPI_API_KEY else "missing"
    checks["google_places"] = "ok" if cfg.GOOGLE_PLACES_API_KEY else "missing"

    overall = "ok" if all(
        v in ("ok", "authorized", "fallback_file", "unconfigured", "missing")
        for v in checks.values()
    ) else "degraded"

    return {
        "status":  overall,
        "product": cfg.PRODUCT["name"],
        "checks":  checks,
    }


@app.get("/debug/claude", tags=["Sistema"], include_in_schema=False)
async def debug_claude():
    """Test mínimo de la API de Anthropic — diagnóstico."""
    import anthropic as _anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY no configurada"}
    try:
        client = _anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=cfg.CLAUDE["model"],
            max_tokens=20,
            messages=[{"role": "user", "content": "Di 'ok'"}],
        )
        return {"ok": True, "model": cfg.CLAUDE["model"], "response": msg.content[0].text}
    except Exception as e:
        body = getattr(e, "body", None) or getattr(e, "response", None)
        return {
            "ok": False,
            "error_type": type(e).__name__,
            "error_str": str(e),
            "body": str(body)[:500] if body else None,
        }


@app.get("/debug/wa-pipeline", tags=["Sistema"], include_in_schema=False)
async def debug_wa_pipeline(target: str = "Textiles Arequipa", phone: str = "51903176598"):
    """Simula el flujo WA pipeline para diagnóstico."""
    import traceback
    import db as _db
    steps = []
    try:
        # Step 1: subscriber
        subscriber = await asyncio.to_thread(_db.get_subscriber, phone)
        steps.append({"step": "get_subscriber", "result": str(subscriber)[:200]})

        _active = (
            subscriber and subscriber.get("status") == "active" and (
                not subscriber.get("expires_at") or
                subscriber.get("expires_at") > datetime.now(timezone.utc).isoformat()
            )
        )
        plan_name = subscriber.get("plan", "free") if _active else "free"
        plan_cfg_local = cfg.PLANS.get(plan_name, cfg.PLANS["free"])
        leads_limit = plan_cfg_local.get("leads_limit", 10)
        steps.append({"step": "plan_resolve", "plan": plan_name, "limit": leads_limit, "active": _active})

        # Step 2: pipeline
        req = PipelineRequest(
            query=target, limit=leads_limit, channel="whatsapp",
            enrich_web=True, enrich_sunat=False,
            qualify=True, enrich_contacts=False,
        )
        import time as _time
        t0 = _time.monotonic()
        result = await asyncio.to_thread(_run_pipeline, req)
        elapsed = _time.monotonic() - t0
        leads = result.get("leads", [])
        steps.append({"step": "pipeline", "elapsed_s": round(elapsed, 1), "leads": len(leads)})

        # Step 3: PDF
        from pdf_report import build_demo_pdf
        pdf_bytes = await asyncio.to_thread(build_demo_pdf, target, leads)
        steps.append({"step": "pdf", "size_bytes": len(pdf_bytes)})

        return {"ok": True, "steps": steps}
    except Exception as exc:
        steps.append({"step": "ERROR", "type": type(exc).__name__, "msg": str(exc)[:300], "tb": traceback.format_exc()[-500:]})
        return {"ok": False, "steps": steps}


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

    El header `X-User-Phone` identifica al usuario para resolver su plan.
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
    No requiere autenticación — es una operación de solo lectura.
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

    El header `X-User-Phone` identifica al usuario para resolver su plan.
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

    El header `X-User-Phone` identifica al usuario para resolver su plan.
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
    job = _db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {
        "id":          job["id"],
        "kind":        job["kind"],
        "status":      job["status"],
        "created_at":  job["created_at"],
        "finished_at": job["finished_at"],
        "error":       job["error"],
    }


@app.get("/jobs/{job_id}/result", tags=["Jobs"])
def get_job_result(job_id: str):
    """Resultado de un job completado."""
    job = _db.get_job(job_id)
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

# Estado de conversación — persistido en PostgreSQL vía db.py.

def _get_bot_state(chat_id: int) -> dict:
    return _db.get_bot_state(chat_id)


def _set_bot_state(chat_id: int, data: dict) -> None:
    _db.set_bot_state(chat_id, data)


def _del_bot_state(chat_id: int) -> None:
    _db.delete_bot_state(chat_id)


def _save_bot_states() -> None:
    """No-op — compatibilidad con código que aún llama a esta función."""
    pass


def _get_admin_ids() -> list[str]:
    """
    Lee los IDs de admin desde ADMIN_TELEGRAM_IDS (comma-separated) o ADMIN_CHAT_ID.
    Permite notificar a múltiples admins sin redeploy.
    Ej: ADMIN_TELEGRAM_IDS="123456789,987654321"
    """
    multi = os.environ.get("ADMIN_TELEGRAM_IDS", "").strip()
    if multi:
        return [aid.strip() for aid in multi.split(",") if aid.strip()]
    single = os.environ.get("ADMIN_CHAT_ID", "").strip()
    return [single] if single else []


async def _notify_pipeassist(msg: str) -> None:
    """
    Envía msg a todos los admins via PipeAssist (bot interno).
    Lee ADMIN_TELEGRAM_IDS (multi) o ADMIN_CHAT_ID (fallback).
    """
    token_int = os.environ.get("TELEGRAM_BOT_TOKEN_INTERNO", "")
    if not token_int:
        return
    admin_ids = _get_admin_ids()
    if not admin_ids:
        return
    async with httpx.AsyncClient(timeout=8) as client:
        for aid in admin_ids:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{token_int}/sendMessage",
                    json={"chat_id": aid, "text": msg, "parse_mode": "Markdown"},
                )
            except Exception as exc:
                log.warning("PipeAssist notify a %s falló: %s", aid, exc)


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


async def _tg_menu(chat_id: int, text: str, buttons: list[list[tuple[str, str]]]) -> None:
    """Envía un mensaje con teclado inline. buttons es lista de filas, cada fila es lista de (text, callback_data)."""
    keyboard = [
        [{"text": t, "callback_data": d} for t, d in row]
        for row in buttons
    ]
    await _tg_post("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": keyboard},
    })


async def _tg_answer_callback(callback_query_id: str) -> None:
    """Cierra el spinner del botón inline."""
    await _tg_post("answerCallbackQuery", {"callback_query_id": callback_query_id})


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
            [l for l in leads if _int_score(l) >= 60],
            key=_int_score, reverse=True,
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


def _int_score(l: dict) -> int:
    """Convierte lead_score a int de forma segura (puede llegar como str)."""
    try:
        return int(l.get("lead_score", 0))
    except (TypeError, ValueError):
        return 0


async def _deliver_and_notify_wa(phone: str, target: str) -> None:
    """
    Corre el pipeline y entrega el reporte al número de WhatsApp.

    Tier enforcement:
      - Suscriptor activo  → 30 leads, PDF completo (build_full_pdf), sin botones de upgrade
      - Usuario free       → 10 leads, PDF demo (build_demo_pdf), botones de upgrade al final
    """
    import traceback
    import wa_sender
    import wa_bot
    import db as _db
    from messages import MSG

    async def _progress_msg(delay: float, text: str) -> None:
        await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(wa_sender.send_text, phone, text)
        except Exception:
            pass

    try:
        subscriber  = await asyncio.to_thread(_db.get_subscriber, phone)
        _active = (
            subscriber and subscriber.get("status") == "active" and (
                not subscriber.get("expires_at") or
                subscriber.get("expires_at") > datetime.now(timezone.utc).isoformat()
            )
        )
        plan_name   = subscriber.get("plan", "free") if _active else "free"
        plan_cfg    = cfg.PLANS.get(plan_name, cfg.PLANS["free"])
        is_paid     = plan_name != "free"
        leads_limit = plan_cfg.get("leads_limit", 10)
        log.info("WA deliver: phone=%s plan=%s active=%s limit=%d", phone, plan_name, _active, leads_limit)
        # Nota: el mensaje "Buscando..." ya se envió desde wa_bot._r_procesando()
        asyncio.create_task(_notify_pipeassist(
            f"🔍 *Nueva búsqueda*\n"
            f"📱 `{phone}`\n"
            f"🎯 `{target}`\n"
            f"{'💎 Suscriptor' if is_paid else '🆓 Free'}"
        ))

        req = PipelineRequest(
            query=target, limit=leads_limit, channel="whatsapp",
            enrich_web=True, enrich_sunat=False,
            qualify=True, enrich_contacts=False,
        )

        # Mensajes de progreso intermedios (cancelados si el pipeline termina antes)
        t1 = asyncio.create_task(_progress_msg(
            30, MSG["qualify_progress"]
        ))

        import time as _time
        _t0 = _time.monotonic()
        log.info("WA pipeline START: phone=%s target=%s limit=%d", phone, target, leads_limit)
        try:
            result = await asyncio.to_thread(_run_pipeline, req)
        except Exception as pipe_exc:
            _elapsed = _time.monotonic() - _t0
            log.error("WA pipeline FAILED after %.1fs: %s\n%s", _elapsed, pipe_exc, traceback.format_exc())
            raise
        _elapsed = _time.monotonic() - _t0
        log.info("WA pipeline END: phone=%s elapsed=%.1fs leads=%d", phone, _elapsed, len(result.get("leads", [])))
        t1.cancel()
        leads  = result.get("leads", [])
        total  = result.get("total", len(leads))

        # Debug: log first 5 leads
        sample = []
        for l in leads[:5]:
            sample.append({"empresa": l.get("empresa", "-"), "score": l.get("lead_score", 0)})
        log.info("Pipeline result: total=%d leads_sample=%s", total, sample)

        qualified = sorted(
            [l for l in leads if _int_score(l) >= 60],
            key=_int_score, reverse=True,
        )

        # ── Resumen breve (sin listar empresas) ──────────────────────────────

        # ── PDF ──────────────────────────────────────────────────────────────
        safe_name = target[:30].replace(" ", "_").replace("/", "-")
        try:
            log.info("PDF gen: target=%s leads=%d qualified=%d full_pdf=%s",
                     target, len(leads), len(qualified), plan_cfg.get("full_pdf", False))
            if plan_cfg.get("full_pdf", False):
                from pdf_report import build_full_pdf
                pdf_bytes = await asyncio.to_thread(build_full_pdf, target, leads)
            else:
                from pdf_report import build_demo_pdf
                pdf_bytes = await asyncio.to_thread(build_demo_pdf, target, leads)
            token = _save_report_bytes(pdf_bytes)
            short_url = f"{API_PUBLIC_URL}/r/{token}"
            n_qualified = len(qualified)
            await asyncio.to_thread(
                wa_sender.send_text,
                phone,
                f"✅ *Reporte listo: {target}*\n"
                f"_{total} leads · {n_qualified} calificados_\n\n"
                f"📄 Descárgalo aquí 👇\n{short_url}",
            )
            log.info("PDF guardado: %s (token=%s)", safe_name, token)
        except Exception as pdf_exc:
            log.error("PDF generation/send failed: %s\n%s", pdf_exc, traceback.format_exc())
            await asyncio.to_thread(
                wa_sender.send_text, phone, MSG["error_pdf"],
            )

        # ── Estado y notificaciones ─────────────────────────────────────────
        wa_bot._set_session(phone, {"state": "done", "target": target})
        await _notion_mark_delivered(target)
        n_qualified = len([l for l in leads if _int_score(l) >= 60])
        _db.log_event(phone, _db.EventType.WA_REPORT_DELIVERED, {
            "target": target, "leads": len(leads),
            "qualified": n_qualified, "paid": is_paid,
        })

        # Notificación a admins via PipeAssist (bot interno)
        admin_msg = (
            f"{'💎' if is_paid else '📲'} *{'Reporte paid' if is_paid else 'Demo'} WA completada*\n\n"
            f"📱 Tel: `{phone}`\n"
            f"🔍 Búsqueda: `{target}`\n"
            f"📊 Leads: {len(leads)} encontrados · {n_qualified} calificados\n"
            f"📎 PDF {'completo' if is_paid else 'demo'} entregado"
        )
        await _notify_pipeassist(admin_msg)
        log.info("Admins notificados via PipeAssist: %d leads para '%s' (paid=%s)",
                 n_qualified, target, is_paid)

        # ── Post-entrega: upgrade CTA solo para free ───────────────────────
        if not is_paid:
            for msg in wa_bot._r_post_demo():
                await asyncio.to_thread(wa_sender.send_text, phone, msg["text"])
        else:
            # Suscriptor: ofrecer nueva búsqueda directamente
            await asyncio.to_thread(
                wa_sender.send_text, phone,
                MSG["subscriber_next_search"],
            )

        # ── Feedback (todos los usuarios, 90s después para no saturar) ───────
        async def _send_feedback_delayed() -> None:
            await asyncio.sleep(90)
            try:
                fb_msgs = wa_bot._r_feedback()
                for fb in fb_msgs:
                    await asyncio.to_thread(wa_sender.send_text, phone, fb["text"])
                wa_bot._set_session(phone, {"state": "feedback_prompted", "target": target})
            except Exception as fb_exc:
                log.warning("feedback send error phone=%s: %s", phone, fb_exc)

        asyncio.create_task(_send_feedback_delayed())

    except BaseException as exc:
        # Cancelar mensajes de progreso pendientes
        try:
            t1.cancel()
        except Exception:
            pass
        tb = traceback.format_exc()
        log.error("_deliver_and_notify_wa error [%s]: %s\n%s", type(exc).__name__, exc, tb)
        # Notificar al admin con detalle del error
        try:
            await _notify_pipeassist(
                f"❌ *Error pipeline WA*\n"
                f"📱 `{phone}`\n"
                f"🎯 `{target}`\n"
                f"💥 `{type(exc).__name__}: {str(exc)[:200]}`"
            )
        except BaseException:
            log.error("No se pudo notificar error al admin")
        # Debug error ya no se envía al usuario (solo al admin via PipeAssist)
        # ── Error recovery con contador ───────────────────────────────────────
        try:
            current_session = wa_bot._get_session(phone)
            error_count = current_session.get("error_count", 0) + 1
            if error_count < 2:
                wa_bot._set_session(phone, {**current_session,
                                             "state": "collecting_target",
                                             "error_count": error_count})
                await asyncio.to_thread(
                    wa_sender.send_text, phone, MSG["pipeline_error_retry"]
                )
            else:
                wa_bot._set_session(phone, {"state": "done"})
                await asyncio.to_thread(
                    wa_sender.send_text, phone, MSG["pipeline_error_final"]
                )
        except BaseException as recovery_exc:
            log.error("error_recovery failed: %s", recovery_exc)
            wa_bot._set_session(phone, {"state": "idle"})


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
            [l for l in leads if _int_score(l) >= 60],
            key=_int_score, reverse=True,
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
        _set_bot_state(chat_id, {"flow": "demo_collecting_email", "target": target})

        await _tg_menu(chat_id,
            "Esto es solo una muestra.\n\n"
            "Con el plan Starter (S/149/mes):\n"
            "• Reportes ilimitados en vez de 10 leads\n"
            "• Validación SUNAT (capacidad de pago real)\n"
            "• PDF con mensajes personalizados por industria\n\n"
            "¿Querés activar el acceso completo? *Escribí tu email* y te lo activo hoy.",
            [[("🚀 Quiero plan completo", "upgrade"), ("💬 Tengo preguntas", "contacto")]],
        )

    except Exception as exc:
        log.error("Demo deliver error chat=%d: %s", chat_id, exc)
        _del_bot_state(chat_id)
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

    # Notificar a todos los admins vía PipeAssist
    notif_msg = (
        f"🆕 *Nueva demo solicitada*\n\n"
        f"*Empresa:* {req.empresa}\n"
        f"*RUC:* `{req.ruc}`\n"
        f"*Contacto:* {req.nombre}\n"
        f"*Email:* {req.email}\n"
        f"*Industria:* {req.industria}\n"
        f"*Ciudad:* {req.ciudad}"
    )
    asyncio.create_task(_notify_pipeassist(notif_msg))

    # Lanzar pipeline en background y entregar CSV al primer admin
    # Usa el límite del tier free (DEMO_REQUEST_LEADS_LIMIT = 10 leads)
    admin_ids = _get_admin_ids()
    if admin_ids:
        query = f"{req.industria} en {req.ciudad}"
        asyncio.create_task(
            _deliver_and_notify(
                query, int(admin_ids[0]),
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
    state   = _get_bot_state(chat_id)
    history: list[dict] = list(state.get("history", []))

    history.append({"role": "user", "content": user_text})
    if len(history) > 20:
        history = history[-20:]

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
                _set_bot_state(chat_id, {**state, "history": history})
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
                _set_bot_state(chat_id, {**state, "history": history})
                return reply
        except Exception:
            pass

    # ── Sin LLM disponible ──────────────────────────────────────────────────
    return (
        "Hola 👋 Soy *Pipeline_X*.\n\n"
        "Puedo generarte un reporte de prospectos calificados.\n"
        "Escribe /start reporte para comenzar."
    )


_TG_MAIN_MENU = [
    [("🚀 Demo gratis", "demo"), ("💰 Ver precios", "precios")],
    [("❓ Cómo funciona", "info")],
]


async def _handle_tg_callback(chat_id: int, data: str) -> None:
    """Despacha el callback_data de un botón inline."""
    if data == "demo":
        _set_bot_state(chat_id, {"flow": "demo"})
        await _tg_message(chat_id,
            "🚀 Voy a generarte *10 leads reales* ahora mismo, sin tarjeta.\n\n"
            "¿Qué tipo de empresa estás prospectando?\n"
            "_Ej: Ferreterías en Trujillo · Clínicas en Bogotá_"
        )
    elif data == "precios":
        await _tg_menu(chat_id,
            "💰 *Planes Pipeline_X*\n\n"
            "• Free — S/0 · 10 leads, sin tarjeta\n"
            "• *Starter — S/149/mes · reportes ilimitados* ⭐\n"
            "• Pro — S/299/mes · mayor volumen + API\n"
            "• Reseller — S/1,099/mes · white-label para agencias\n\n"
            "Menos que el costo de un vendedor por un día.\n"
            "Sin contrato. Cancela cuando quieras.",
            [[("🚀 Probar gratis", "demo"), ("💬 Hablar con alguien", "contacto")]],
        )
    elif data == "info":
        await _tg_menu(chat_id,
            "En 3 pasos:\n"
            "1️⃣ Escribes qué buscas — *\"Ferreterías en Trujillo\"*\n"
            "2️⃣ Buscamos en Google Maps y calificamos con IA (score 0–100)\n"
            "3️⃣ Recibes aquí un PDF con leads + mensajes listos para enviar\n\n"
            "Sin instalar nada. Sin aprender ningún sistema. Solo abres el PDF y llamas.",
            [[("🚀 Demo gratis", "demo"), ("💰 Ver precios", "precios")]],
        )
    elif data == "contacto":
        await _tg_message(chat_id,
            "📧 contacto@pipelinex.app\n"
            "🤖 Telegram: t.me/Pipeline_X_bot (respuesta inmediata)"
        )
    elif data == "upgrade":
        await _tg_menu(chat_id,
            "Para activar tu acceso escríbenos a *contacto@pipelinex.app* con asunto 'Acceso Starter'.\n\n"
            "O empieza ahora mismo con la demo gratuita:",
            [[("🚀 Demo gratis", "demo")]],
        )
    else:
        await _tg_menu(chat_id, "¿En qué te puedo ayudar?", _TG_MAIN_MENU)


@app.post("/webhook/telegram", include_in_schema=False)
async def telegram_webhook(request: Request):
    """
    Recibe updates de Telegram (registrar con setWebhook apuntando a esta URL).
    Flujos:
      /start            → menú con botones inline
      /start reporte    → solicita target → corre /deliver → entrega CSV
      /start demo       → flujo demo (deep link desde landing)
      callback_query    → botones inline (demo / precios / info / contacto)
      cualquier otro    → bot de ventas Alex (Groq)
    """
    # Verificar token secreto si está configurado
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if secret:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != secret:
            raise HTTPException(status_code=403, detail="Forbidden")

    update = await request.json()

    # ── Botón inline presionado ────────────────────────────────────────────────
    cq = update.get("callback_query")
    if cq:
        chat_id = cq["message"]["chat"]["id"]
        data    = cq.get("data", "")
        await _tg_answer_callback(cq["id"])
        await _handle_tg_callback(chat_id, data)
        return {"ok": True}

    message = update.get("message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text    = (message.get("text") or "").strip()
    if not text:
        return {"ok": True}

    state = _get_bot_state(chat_id)

    # ── /start ────────────────────────────────────────────────────────────────
    if text.startswith("/start"):
        payload = text[6:].strip()
        _del_bot_state(chat_id)   # reset

        if payload == "reporte":
            _set_bot_state(chat_id, {"flow": "report"})
            await _tg_message(chat_id,
                "Hola 👋 Soy *Pipeline_X*.\n\n"
                "Vi que solicitaste un reporte desde nuestra web.\n\n"
                "¿Cuál es el target exacto que quieres prospectar?\n"
                "_Escríbelo así: Industria en Ciudad_\n\n"
                "Ej: `Ferreterías en Trujillo`"
            )
        elif payload == "demo":
            # Deep link desde landing: t.me/<bot>?start=demo
            _set_bot_state(chat_id, {"flow": "demo"})
            await _tg_message(chat_id,
                "Hola 👋 Voy a generarte *10 leads reales* ahora mismo, sin tarjeta.\n\n"
                "¿Qué tipo de empresa estás prospectando?\n"
                "_Ej: Ferreterías en Trujillo · Clínicas en Bogotá_"
            )
        else:
            # Menú principal con botones inline
            await _tg_menu(chat_id,
                "👋 Hola, soy *Pipeline_X*.\n\n"
                "Encuentra empresas reales en Google Maps, califícalas con IA "
                "y recibe mensajes de outreach listos.\n\n"
                "¿Por dónde empezamos?",
                _TG_MAIN_MENU,
            )
        return {"ok": True}

    # ── Flujo de reporte (admin): esperando target ────────────────────────────
    if state.get("flow") == "report":
        target = text
        _del_bot_state(chat_id)
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
        _set_bot_state(chat_id, {**state, "flow": "demo_running", "target": target})
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
        _del_bot_state(chat_id)

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
            "Normalmente lo hacemos dentro de las 24 horas en horario hábil."
        )
        return {"ok": True}

    # ── Bot de ventas Alex ────────────────────────────────────────────────────
    reply = await asyncio.to_thread(_alex_reply, chat_id, text)
    await _tg_message(chat_id, reply)
    return {"ok": True}


# ─── Anti-loop: deduplicación y rate-limit por número ────────────────────────
import time as _time
_seen_ids: set[str]       = set()          # idMessages ya procesados
_phone_ts: dict[str, list] = {}            # phone → lista de timestamps recientes
_MAX_MSG_PER_MIN = 6                       # máx mensajes por número por minuto


def _is_duplicate(id_message: str) -> bool:
    if not id_message:
        return False
    if id_message in _seen_ids:
        return True
    _seen_ids.add(id_message)
    if len(_seen_ids) > 2000:              # evitar crecimiento infinito
        _seen_ids.clear()
    return False


def _rate_limited(phone: str) -> bool:
    now = _time.time()
    ts  = _phone_ts.setdefault(phone, [])
    ts[:] = [t for t in ts if now - t < 60]   # últimos 60 s
    if len(ts) >= _MAX_MSG_PER_MIN:
        log.warning("Rate-limit alcanzado para %s (%d msgs/min) — ignorando", phone, len(ts))
        return True
    ts.append(now)
    return False


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

    # Deduplicación — mismo idMessage ya procesado
    if _is_duplicate(id_message):
        log.debug("Webhook duplicado ignorado: %s", id_message)
        return {"ok": True}

    # Rate-limit — cortar loops de bots
    if _rate_limited(phone):
        return {"ok": True}

    # Marcar como leído (ticks azules)
    if id_message:
        await asyncio.to_thread(wa_sender.mark_read, phone, id_message)

    # Procesar y responder (handle_message devuelve list[dict])
    try:
        messages = await asyncio.to_thread(wa_bot.handle_message, phone, text)
    except Exception as exc:
        log.error("handle_message error phone=%s: %s", phone, exc)
        return {"ok": True}

    for msg in messages:
        mtype = msg.get("type", "text")
        try:
            if mtype == "pipeline_request":
                # Lanzar pipeline en background — responde inmediatamente con "procesando"
                asyncio.create_task(_deliver_and_notify_wa(phone, msg["target"]))
            elif mtype in ("buttons", "list"):
                # Botones/listas ya no se usan — enviar como texto plano
                body = msg.get("body", "") or msg.get("text", "")
                if body:
                    await asyncio.to_thread(wa_sender.send_text, phone, body)
            else:
                await asyncio.to_thread(wa_sender.send_text, phone, msg["text"])
        except Exception as send_exc:
            log.warning("send error phone=%s type=%s: %s", phone, mtype, send_exc)

    return {"ok": True}


# ─── Admin: dashboard web ────────────────────────────────────────────────────

def _admin_html(stats: dict, subscribers: list[dict], key: str) -> str:
    """Genera el HTML del dashboard de administración."""

    def _stat_card(label: str, value, color: str = "#4ade80") -> str:
        return f"""
        <div class="card">
          <div class="card-value" style="color:{color}">{value}</div>
          <div class="card-label">{label}</div>
        </div>"""

    def _pct(val) -> str:
        return val if val else "—"

    conv  = stats.get("conversion", {})
    cards = "".join([
        _stat_card("Búsquedas",        stats.get("searches", 0)),
        _stat_card("Reportes",          stats.get("reports_delivered", 0)),
        _stat_card("Clics upgrade",     stats.get("upgrade_clicks", 0),    "#facc15"),
        _stat_card("Activaciones",      stats.get("activations", 0),       "#facc15"),
        _stat_card("Suscriptores activos", stats.get("active_subscribers", 0), "#a78bfa"),
        _stat_card("Search→Upgrade",    _pct(conv.get("search_to_upgrade")), "#fb923c"),
        _stat_card("Upgrade→Pago",      _pct(conv.get("upgrade_to_paid")),  "#fb923c"),
        _stat_card("Search→Pago",       _pct(conv.get("search_to_paid")),   "#fb923c"),
    ])

    def _row(sub: dict) -> str:
        status = sub.get("status", "")
        color = "#4ade80" if status == "active" else "#f87171"
        exp = (sub.get("expires_at") or "")[:10] or "—"
        act = (sub.get("activated_at") or "")[:10] or "—"
        return (
            f"<tr>"
            f"<td><code>{sub.get('phone','')}</code></td>"
            f"<td>{sub.get('plan','').capitalize()}</td>"
            f"<td style='color:{color}'>{status}</td>"
            f"<td>{act}</td>"
            f"<td>{exp}</td>"
            f"<td style='color:#6b7280;font-size:11px'>{sub.get('notes','')[:40]}</td>"
            f"</tr>"
        )

    rows = "".join(_row(s) for s in subscribers) if subscribers else (
        "<tr><td colspan='6' style='color:#6b7280;text-align:center'>Sin suscriptores</td></tr>"
    )

    top_html = ""
    top = stats.get("top_searches", [])
    if top:
        items = "".join(f"<li><code>{t['target']}</code> <span>×{t['count']}</span></li>" for t in top)
        top_html = f"<h2>Top búsquedas (7d)</h2><ul class='top-list'>{items}</ul>"

    period = stats.get("period_days", 7)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pipeline_X Admin</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#000;color:#e5e5e5;font-family:'IBM Plex Mono',monospace;font-size:13px;padding:24px}}
a{{color:#4ade80;text-decoration:none}}
h1{{font-size:18px;font-weight:700;color:#fff;margin-bottom:4px}}
h2{{font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.08em;margin:32px 0 12px}}
.subtitle{{color:#6b7280;font-size:12px;margin-bottom:32px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:8px}}
.card{{background:#0a0a0a;border:1px solid #1a1a1a;padding:16px 20px;min-width:140px}}
.card-value{{font-size:26px;font-weight:700;line-height:1}}
.card-label{{color:#6b7280;font-size:11px;margin-top:6px;text-transform:uppercase;letter-spacing:.06em}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}
th{{text-align:left;color:#6b7280;font-size:11px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #1a1a1a;padding:8px 12px}}
td{{padding:10px 12px;border-bottom:1px solid #111;vertical-align:middle}}
tr:hover td{{background:#0a0a0a}}
code{{background:#111;padding:2px 6px;border-radius:2px;font-size:12px}}
.top-list{{list-style:none;display:flex;flex-wrap:wrap;gap:8px}}
.top-list li{{background:#0a0a0a;border:1px solid #1a1a1a;padding:6px 12px;font-size:12px}}
.top-list li span{{color:#4ade80;margin-left:8px}}
.period-selector{{display:flex;gap:8px;margin-bottom:24px}}
.period-selector a{{padding:4px 10px;border:1px solid #2a2a2a;color:#6b7280;font-size:12px}}
.period-selector a.active{{border-color:#4ade80;color:#4ade80}}
</style>
</head>
<body>
<h1>Pipeline_X Admin</h1>
<p class="subtitle">Dashboard interno · últimos {period} días</p>

<div class="period-selector">
  <a href="?key={key}&days=1" class="{'active' if period==1 else ''}">24h</a>
  <a href="?key={key}&days=7" class="{'active' if period==7 else ''}">7d</a>
  <a href="?key={key}&days=30" class="{'active' if period==30 else ''}">30d</a>
</div>

<h2>Funnel</h2>
<div class="cards">{cards}</div>

{top_html}

<h2>Suscriptores</h2>
<table>
  <thead><tr>
    <th>Teléfono</th><th>Plan</th><th>Estado</th>
    <th>Activado</th><th>Expira</th><th>Notas</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
</body>
</html>"""


# ─── Admin: gestión de suscriptores ──────────────────────────────────────────

def _check_admin_api_key(request: Request) -> None:
    """Valida ADMIN_API_KEY en header X-Admin-Key. Lanza 403 si no coincide."""
    import os
    key = os.environ.get("ADMIN_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY no configurada")
    if request.headers.get("X-Admin-Key", "") != key:
        raise HTTPException(status_code=403, detail="Unauthorized")


class ActivateSubscriberRequest(BaseModel):
    phone:  str        = Field(..., description="Número sin '+' ni '@c.us', ej: 51987654321")
    plan:   str        = Field("starter", description="Plan: starter, pro, reseller, founder")
    days:   int | None = Field(30, description="Días de acceso. None = sin expiración")
    notes:  str        = Field("", description="Notas internas (ref. transferencia, nombre)")


@app.get("/admin", include_in_schema=False)
async def admin_dashboard(key: str = "", days: int = 7):
    """
    Dashboard web de administración.
    Acceso: /admin?key=<ADMIN_API_KEY>&days=7
    """
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key or key != admin_key:
        return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Pipeline_X Admin</title>
<style>body{background:#000;color:#e5e5e5;font-family:monospace;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}
form{display:flex;flex-direction:column;gap:12px;min-width:260px}
input{background:#0a0a0a;border:1px solid #2a2a2a;color:#e5e5e5;
padding:10px;font-family:inherit;font-size:13px}
button{background:#4ade80;color:#000;border:none;padding:10px;
font-family:inherit;font-weight:700;cursor:pointer}
h2{color:#fff;margin-bottom:8px;font-size:16px}</style></head>
<body><form method="get">
<h2>Pipeline_X Admin</h2>
<input name="key" type="password" placeholder="Admin key" autofocus>
<button type="submit">Acceder</button>
</form></body></html>""", status_code=403)

    stats       = await asyncio.to_thread(_db.get_stats, days)
    subscribers = await asyncio.to_thread(_db.get_subscribers_list)
    return HTMLResponse(_admin_html(stats, subscribers, key))


@app.post("/admin/subscribers/activate", tags=["Admin"], status_code=200,
          summary="Activar o renovar un suscriptor (requiere X-Admin-Key)")
async def admin_activate_subscriber(req: ActivateSubscriberRequest, request: Request):
    """
    Activa manualmente un suscriptor después de confirmar su pago.

    Header requerido: `X-Admin-Key: <ADMIN_API_KEY>`

    Al activar:
    - Crea o actualiza la fila en la tabla `subscribers`
    - El bot WA detectará automáticamente el tier en la próxima búsqueda
    - Envía notificación al suscriptor por WhatsApp
    """
    import db as _db
    import wa_sender
    _check_admin_api_key(request)

    subscriber = await asyncio.to_thread(
        _db.upsert_subscriber, req.phone, req.plan, req.days, req.notes
    )
    if not subscriber:
        raise HTTPException(status_code=500, detail="Error guardando en DB")

    # Notificar al suscriptor por WhatsApp
    from messages import MSG
    try:
        plan_display = req.plan.capitalize()
        days_str = f"{req.days} días" if req.days else "sin expiración"
        welcome_msg = MSG["subscriber_welcome"].format(
            plan=plan_display, days=days_str
        )
        await asyncio.to_thread(wa_sender.send_text, req.phone, welcome_msg)
    except Exception as wa_exc:
        log.warning("No se pudo enviar WA de bienvenida a %s: %s", req.phone, wa_exc)

    _db.log_event(req.phone, _db.EventType.SUBSCRIBER_ACTIVATED,
                  {"plan": req.plan, "days": req.days, "notes": req.notes})
    asyncio.create_task(_notify_pipeassist(
        f"💎 *Suscriptor activado*\n"
        f"📱 `{req.phone}`\n"
        f"📦 Plan: {req.plan.capitalize()}\n"
        f"⏳ Duración: {req.days} días\n"
        f"📝 {req.notes or '—'}"
    ))
    log.info("Admin activó suscriptor: phone=%s plan=%s days=%s", req.phone, req.plan, req.days)
    return {"ok": True, "subscriber": subscriber}


@app.get("/admin/subscribers/{phone}", tags=["Admin"],
         summary="Consultar estado de un suscriptor (requiere X-Admin-Key)")
async def admin_get_subscriber(phone: str, request: Request):
    import db as _db
    _check_admin_api_key(request)
    sub = await asyncio.to_thread(_db.get_subscriber, phone)
    if not sub:
        raise HTTPException(status_code=404, detail="Suscriptor no encontrado")
    return sub


@app.get("/admin/stats", tags=["Admin"],
         summary="KPIs de funnel (requiere X-Admin-Key)")
async def admin_stats(days: int = 7, request: Request = None):
    """
    Métricas de funnel para los últimos `days` días (default 7).

    Devuelve: búsquedas, reportes entregados, clics de upgrade,
    activaciones, suscriptores activos y tasas de conversión.
    """
    _check_admin_api_key(request)
    stats = await asyncio.to_thread(_db.get_stats, days)
    return stats


@app.delete("/admin/subscribers/{phone}", tags=["Admin"],
            summary="Cancelar suscripción (requiere X-Admin-Key)")
async def admin_cancel_subscriber(phone: str, reason: str = "", request: Request = None):
    import db as _db
    _check_admin_api_key(request)
    await asyncio.to_thread(_db.cancel_subscriber, phone, reason)
    log.info("Admin canceló suscripción: phone=%s", phone)
    return {"ok": True, "phone": phone, "status": "cancelled"}


# ─── Admin: Broadcast ─────────────────────────────────────────────────────────

class BroadcastRequest(BaseModel):
    message: str = Field(..., description="Texto del mensaje a enviar")
    plan:    str | None = Field(None, description="Filtrar por plan (ej: 'free', 'starter'). Omitir para todos.")


@app.post("/admin/broadcast", tags=["Admin"], status_code=200,
          summary="Enviar broadcast WA a candidatos (requiere X-Admin-Key)")
async def admin_broadcast(req: BroadcastRequest, request: Request):
    """
    Envía un mensaje de WhatsApp a todos los usuarios que han hecho al menos
    una búsqueda y no están unsubscribed.

    Header requerido: `X-Admin-Key: <ADMIN_API_KEY>`

    Body:
      - `message`: texto a enviar
      - `plan` (opcional): filtrar por plan activo (ej: "free", "starter")
    """
    import db as _db
    import wa_sender
    _check_admin_api_key(request)

    candidates = await asyncio.to_thread(_db.get_broadcast_candidates, req.plan)
    log.info("Broadcast: %d candidatos (plan=%s)", len(candidates), req.plan)

    sent   = 0
    failed = 0
    for phone in candidates:
        try:
            await asyncio.to_thread(wa_sender.send_text, phone, req.message)
            sent += 1
            log.info("Broadcast enviado: phone=%s", phone)
        except Exception as exc:
            failed += 1
            log.warning("Broadcast error phone=%s: %s", phone, exc)
        await asyncio.sleep(2)   # delay entre envíos

    log.info("Broadcast completado: sent=%d failed=%d", sent, failed)
    return {"sent": sent, "failed": failed, "total_candidates": len(candidates)}
