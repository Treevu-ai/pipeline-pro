"""
db.py — Capa de persistencia PostgreSQL para Pipeline_X.

Reemplaza:
  - output/.wa_sessions.json   → tabla wa_sessions
  - _jobs dict en api.py       → tabla pipeline_jobs
  - _bot_states dict en api.py → tabla bot_states

Si DATABASE_URL no está configurada, degrada silenciosamente a archivos
locales / dicts en memoria (desarrollo local sin add-on).

Inicialización: llamar db.init() una sola vez al arrancar la app (lifespan).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("db")

# ─── Configuración ────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Railway usa "postgres://" pero psycopg2 requiere "postgresql://"
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = "postgresql://" + _DATABASE_URL[len("postgres://"):]

_USE_DB = False   # se activa en init() si la conexión es exitosa
_pool   = None    # psycopg2.pool.ThreadedConnectionPool


# ─── Init ─────────────────────────────────────────────────────────────────────

def init() -> None:
    """
    Inicializa el pool de conexiones y crea las tablas si no existen.
    Seguro de llamar múltiples veces — idempotente.
    """
    global _pool, _USE_DB

    if not _DATABASE_URL:
        log.warning("db: DATABASE_URL no configurada — usando fallback a archivos/memoria")
        return

    try:
        import psycopg2.pool as pg_pool
        _pool = pg_pool.ThreadedConnectionPool(1, 8, _DATABASE_URL)
        _create_tables()
        _USE_DB = True
        log.info("db: PostgreSQL conectado y tablas verificadas")
    except Exception as exc:
        log.error("db: no se pudo conectar a PostgreSQL (%s) — usando fallback", exc)
        _USE_DB = False


@contextmanager
def _conn():
    """Context manager — obtiene conexión del pool, hace commit o rollback."""
    if not _pool:
        raise RuntimeError("db: pool no inicializado")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def _create_tables() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wa_sessions (
                    phone       TEXT PRIMARY KEY,
                    state       TEXT NOT NULL DEFAULT 'idle',
                    data        JSONB NOT NULL DEFAULT '{}',
                    updated_at  TIMESTAMPTZ DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_jobs (
                    job_id      TEXT PRIMARY KEY,
                    kind        TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    params      JSONB NOT NULL DEFAULT '{}',
                    result      JSONB,
                    error_msg   TEXT,
                    created_at  TIMESTAMPTZ DEFAULT now(),
                    finished_at TIMESTAMPTZ
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_states (
                    chat_id     BIGINT PRIMARY KEY,
                    data        JSONB NOT NULL DEFAULT '{}',
                    updated_at  TIMESTAMPTZ DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    phone        TEXT PRIMARY KEY,
                    plan         TEXT NOT NULL DEFAULT 'starter',
                    status       TEXT NOT NULL DEFAULT 'active',
                    activated_at TIMESTAMPTZ DEFAULT now(),
                    expires_at   TIMESTAMPTZ,
                    notes        TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id          BIGSERIAL PRIMARY KEY,
                    phone       TEXT,
                    event_type  TEXT NOT NULL,
                    metadata    JSONB NOT NULL DEFAULT '{}',
                    created_at  TIMESTAMPTZ DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS events_type_ts
                ON events (event_type, created_at DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS events_phone_ts
                ON events (phone, created_at DESC);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    phone            TEXT PRIMARY KEY,
                    name             TEXT,
                    default_city     TEXT,
                    email            TEXT,
                    empresa          TEXT,
                    leads_mensuales  TEXT,
                    updated_at       TIMESTAMPTZ DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_tokens (
                    phone        TEXT PRIMARY KEY,
                    token        TEXT NOT NULL,
                    created_at   TIMESTAMPTZ DEFAULT now(),
                    expires_at   TIMESTAMPTZ DEFAULT now() + INTERVAL '30 days'
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payment_links (
                    id          TEXT PRIMARY KEY,
                    phone       TEXT,
                    plan        TEXT NOT NULL,
                    amount      INTEGER NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    created_at  TIMESTAMPTZ DEFAULT now(),
                    expires_at  TIMESTAMPTZ DEFAULT now() + INTERVAL '24 hours'
                );
            """)
            # Limpiar sesiones WA viejas (>24h) en cada arranque
            try:
                cur.execute("""
                    DELETE FROM wa_sessions
                    WHERE updated_at < now() - INTERVAL '24 hours';
                """)
                # Jobs viejos (>7 días) — evitar acumulación indefinida
                cur.execute("""
                    DELETE FROM pipeline_jobs
                    WHERE created_at < now() - INTERVAL '7 days';
                """)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# Sesiones WhatsApp
# ═══════════════════════════════════════════════════════════════════════════════

def get_session(phone: str) -> dict:
    """Lee la sesión del número. Devuelve {'state': 'idle'} si no existe."""
    if not _USE_DB:
        return _file_get_session(phone)
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM wa_sessions WHERE phone = %s", (phone,)
                )
                row = cur.fetchone()
                return dict(row[0]) if row else {"state": "idle"}
    except Exception as exc:
        log.error("get_session(%s): %s", phone, exc)
        return _file_get_session(phone)   # fallback a archivo


def set_session(phone: str, data: dict) -> None:
    """Guarda/actualiza la sesión del número (upsert)."""
    if not _USE_DB:
        _file_set_session(phone, data)
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO wa_sessions (phone, state, data, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (phone) DO UPDATE
                        SET state      = EXCLUDED.state,
                            data       = EXCLUDED.data,
                            updated_at = now()
                """, (phone, data.get("state", "idle"), json.dumps(data)))
    except Exception as exc:
        log.error("set_session(%s): %s", phone, exc)
        _file_set_session(phone, data)    # fallback a archivo


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline Jobs
# ═══════════════════════════════════════════════════════════════════════════════

def new_job(kind: str, params: dict) -> str:
    """Crea un nuevo job en estado 'pending'. Devuelve job_id."""
    job_id = str(uuid.uuid4())
    if not _USE_DB:
        _mem_jobs[job_id] = _make_job_dict(job_id, kind, params)
        return job_id
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO pipeline_jobs (job_id, kind, status, params)
                    VALUES (%s, %s, 'pending', %s)
                """, (job_id, kind, json.dumps(params)))
    except Exception as exc:
        log.error("new_job: %s", exc)
        _mem_jobs[job_id] = _make_job_dict(job_id, kind, params)
    return job_id


def update_job(job_id: str, status: str,
               result: Any = None, error: str | None = None) -> None:
    """Actualiza estado, result y/o error de un job."""
    if not _USE_DB:
        if job_id in _mem_jobs:
            _mem_jobs[job_id].update({"status": status, "result": result, "error": error})
            if status in ("done", "failed"):
                _mem_jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE pipeline_jobs
                    SET status      = %s,
                        result      = %s,
                        error_msg   = %s,
                        finished_at = CASE WHEN %s IN ('done','failed') THEN now() ELSE finished_at END
                    WHERE job_id = %s
                """, (
                    status,
                    json.dumps(result) if result is not None else None,
                    error,
                    status,
                    job_id,
                ))
    except Exception as exc:
        log.error("update_job(%s): %s", job_id, exc)


def get_job(job_id: str) -> dict | None:
    """Lee un job por ID. None si no existe."""
    if not _USE_DB:
        return _mem_jobs.get(job_id)
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT job_id, kind, status, params, result,
                           error_msg, created_at, finished_at
                    FROM pipeline_jobs WHERE job_id = %s
                """, (job_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id":          row[0],
                    "kind":        row[1],
                    "status":      row[2],
                    "params":      dict(row[3]) if row[3] else {},
                    "result":      dict(row[4]) if row[4] else None,
                    "error":       row[5],
                    "created_at":  row[6].isoformat() if row[6] else None,
                    "finished_at": row[7].isoformat() if row[7] else None,
                }
    except Exception as exc:
        log.error("get_job(%s): %s", job_id, exc)
        return _mem_jobs.get(job_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Bot States (Telegram)
# ═══════════════════════════════════════════════════════════════════════════════

def get_bot_state(chat_id: int) -> dict:
    """Lee el estado del chat de Telegram. {} si no existe."""
    if not _USE_DB:
        return dict(_bot_states_mem.get(chat_id, {}))
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM bot_states WHERE chat_id = %s", (chat_id,)
                )
                row = cur.fetchone()
                return dict(row[0]) if row else {}
    except Exception as exc:
        log.error("get_bot_state(%s): %s", chat_id, exc)
        return dict(_bot_states_mem.get(chat_id, {}))


def set_bot_state(chat_id: int, data: dict) -> None:
    """Guarda/actualiza el estado del chat de Telegram."""
    if not _USE_DB:
        _bot_states_mem[chat_id] = data
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_states (chat_id, data, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (chat_id) DO UPDATE
                        SET data       = EXCLUDED.data,
                            updated_at = now()
                """, (chat_id, json.dumps(data)))
    except Exception as exc:
        log.error("set_bot_state(%s): %s", chat_id, exc)
        _bot_states_mem[chat_id] = data


def delete_bot_state(chat_id: int) -> None:
    """Elimina el estado del chat (reset)."""
    if not _USE_DB:
        _bot_states_mem.pop(chat_id, None)
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bot_states WHERE chat_id = %s", (chat_id,)
                )
    except Exception as exc:
        log.error("delete_bot_state(%s): %s", chat_id, exc)
        _bot_states_mem.pop(chat_id, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Fallbacks en memoria / archivo
# ═══════════════════════════════════════════════════════════════════════════════

_mem_jobs:       dict[str, dict] = {}
_bot_states_mem: dict[int, dict] = {}


def _make_job_dict(job_id: str, kind: str, params: dict) -> dict:
    return {
        "id": job_id, "kind": kind, "status": "pending",
        "params": params, "result": None, "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }


# Fallback a archivo JSON para sesiones WA (mismo formato que antes)
_SESSIONS_FILE = Path("output/.wa_sessions.json")


def _file_get_session(phone: str) -> dict:
    try:
        if _SESSIONS_FILE.exists():
            data = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
            return dict(data.get(phone, {"state": "idle"}))
    except Exception:
        pass
    return {"state": "idle"}


def _file_set_session(phone: str, data: dict) -> None:
    try:
        _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        all_data: dict = {}
        if _SESSIONS_FILE.exists():
            all_data = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
        all_data[phone] = data
        _SESSIONS_FILE.write_text(
            json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.error("_file_set_session(%s): %s", phone, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# Subscribers (clientes con plan activo)
# ═══════════════════════════════════════════════════════════════════════════════

def is_active_subscriber(phone: str) -> bool:
    """
    Devuelve True si el número tiene un plan activo (no expirado).
    Siempre False si no hay DB (fallback).
    """
    if not _USE_DB:
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM subscribers
                    WHERE phone = %s
                      AND status = 'active'
                      AND (expires_at IS NULL OR expires_at > now())
                """, (phone,))
                return cur.fetchone() is not None
    except Exception as exc:
        log.error("is_active_subscriber(%s): %s", phone, exc)
        return False


def get_subscriber(phone: str) -> dict | None:
    """Lee el registro del suscriptor. None si no existe."""
    if not _USE_DB:
        return None
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT phone, plan, status, activated_at, expires_at, notes
                    FROM subscribers WHERE phone = %s
                """, (phone,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "phone":        row[0],
                    "plan":         row[1],
                    "status":       row[2],
                    "activated_at": row[3].isoformat() if row[3] else None,
                    "expires_at":   row[4].isoformat() if row[4] else None,
                    "notes":        row[5],
                }
    except Exception as exc:
        log.error("get_subscriber(%s): %s", phone, exc)
        return None


def upsert_subscriber(phone: str, plan: str = "starter",
                      days: int | None = 30, notes: str = "") -> dict:
    """
    Crea o actualiza un suscriptor.
    days=None → sin expiración (acceso permanente hasta cancelar manualmente).
    Devuelve el registro resultante.
    """
    if not _USE_DB:
        log.warning("upsert_subscriber: DB no disponible")
        return {}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO subscribers (phone, plan, status, activated_at, expires_at, notes)
                    VALUES (%s, %s, 'active', now(), 
                            CASE WHEN %s IS NOT NULL THEN now() + %s::interval ELSE NULL END,
                            %s)
                    ON CONFLICT (phone) DO UPDATE
                        SET plan         = EXCLUDED.plan,
                            status       = 'active',
                            activated_at = now(),
                            expires_at   = CASE WHEN EXCLUDED.expires_at IS NOT NULL THEN now() + EXCLUDED.expires_at::interval ELSE NULL END,
                            notes        = EXCLUDED.notes
                """, (phone, plan, days, days, notes))
        log.info("Subscriber activado: phone=%s plan=%s days=%s", phone, plan, days)
        return get_subscriber(phone) or {}
    except Exception as exc:
        log.error("upsert_subscriber(%s): %s", phone, exc)
        return {}


def save_api_token(phone: str, token: str) -> bool:
    """Guarda o actualiza el token de API para un usuario."""
    if not _USE_DB:
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO api_tokens (phone, token, created_at, expires_at)
                    VALUES (%s, %s, now(), now() + INTERVAL '30 days')
                    ON CONFLICT (phone) DO UPDATE
                        SET token = EXCLUDED.token,
                            created_at = now(),
                            expires_at = now() + INTERVAL '30 days'
                """, (phone, token))
        return True
    except Exception as exc:
        log.error("save_api_token(%s): %s", phone, exc)
        return False


def get_api_token(phone: str) -> str | None:
    """Obtiene el token activo de un usuario."""
    if not _USE_DB:
        return None
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT token FROM api_tokens
                    WHERE phone = %s AND expires_at > now()
                """, (phone,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        log.error("get_api_token(%s): %s", phone, exc)
        return None


def save_payment_link(phone: str, payment_id: str, plan: str, amount: int) -> bool:
    """Guarda un link de pago generado."""
    if not _USE_DB:
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payment_links (id, phone, plan, amount, status, created_at, expires_at)
                    VALUES (%s, %s, %s, %s, 'pending', now(), now() + INTERVAL '24 hours')
                    ON CONFLICT (id) DO UPDATE
                        SET status = 'pending',
                            phone = EXCLUDED.phone,
                            plan = EXCLUDED.plan,
                            amount = EXCLUDED.amount
                """, (payment_id, phone, plan, amount))
        return True
    except Exception as exc:
        log.error("save_payment_link(%s): %s", payment_id, exc)
        return False


def confirm_payment(payment_id: str) -> dict | None:
    """Confirma un pago y activa la suscripción."""
    if not _USE_DB:
        return None
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE payment_links
                    SET status = 'paid'
                    WHERE id = %s AND status = 'pending' AND expires_at > now()
                    RETURNING phone, plan, amount
                """, (payment_id,))
                row = cur.fetchone()
                if not row:
                    return None
                phone, plan, amount = row
                _db.upsert_subscriber(phone, plan=plan, days=30)
                return {"phone": phone, "plan": plan, "amount": amount}
    except Exception as exc:
        log.error("confirm_payment(%s): %s", payment_id, exc)
        return None


def get_subscribers_list(limit: int = 100) -> list[dict]:
    """Lista suscriptores ordenados por activación desc. Para el admin dashboard."""
    if not _USE_DB:
        return []
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT phone, plan, status, activated_at, expires_at, notes
                    FROM subscribers
                    ORDER BY activated_at DESC
                    LIMIT %s
                """, (limit,))
                return [
                    {
                        "phone":        r[0],
                        "plan":         r[1],
                        "status":       r[2],
                        "activated_at": r[3].isoformat() if r[3] else None,
                        "expires_at":   r[4].isoformat() if r[4] else None,
                        "notes":        r[5] or "",
                    }
                    for r in cur.fetchall()
                ]
    except Exception as exc:
        log.error("get_subscribers_list: %s", exc)
        return []


def cancel_subscriber(phone: str, reason: str = "") -> None:
    """Marca el suscriptor como cancelado."""
    if not _USE_DB:
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE subscribers
                    SET status = 'cancelled', notes = %s
                    WHERE phone = %s
                """, (reason or "manual cancel", phone))
        log.info("Subscriber cancelado: phone=%s", phone)
    except Exception as exc:
        log.error("cancel_subscriber(%s): %s", phone, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# Events (funnel tracking)
# ═══════════════════════════════════════════════════════════════════════════════

# Tipos de evento canónicos
class EventType:
    WA_SEARCH             = "wa_search"
    WA_REPORT_DELIVERED   = "wa_report_delivered"
    WA_UPGRADE_CLICK      = "wa_upgrade_click"
    WA_FEEDBACK           = "wa_feedback"
    WA_FOLLOWUP_SENT      = "wa_followup_sent"
    WA_TRIAL_EXPIRED      = "wa_trial_expired"
    SUBSCRIBER_ACTIVATED  = "subscriber_activated"
    SUBSCRIBER_CANCELLED  = "subscriber_cancelled"
    WA_UNSUBSCRIBED       = "wa_unsubscribed"


def get_followup_candidates(hours_min: int = 23, hours_max: int = 25) -> list[str]:
    """
    Devuelve teléfonos de usuarios que:
      - Recibieron un reporte hace entre hours_min y hours_max horas
      - NO son suscriptores activos
      - NO recibieron ya un followup en las últimas 48h
    """
    if not _USE_DB:
        return []
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT e.phone
                    FROM events e
                    WHERE e.event_type = %s
                      AND e.phone IS NOT NULL
                      AND e.created_at BETWEEN now() - INTERVAL %s AND now() - INTERVAL %s
                      AND NOT EXISTS (
                          SELECT 1 FROM subscribers s
                          WHERE s.phone = e.phone
                            AND s.status = 'active'
                            AND (s.expires_at IS NULL OR s.expires_at > now())
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM events f
                          WHERE f.phone = e.phone
                            AND f.event_type = %s
                            AND f.created_at > now() - INTERVAL '48 hours'
                      )
                """, (
                    EventType.WA_REPORT_DELIVERED,
                    f"{hours_max} hours",
                    f"{hours_min} hours",
                    EventType.WA_FOLLOWUP_SENT,
                ))
                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        log.error("get_followup_candidates: %s", exc)
        return []


def get_expired_trial_candidates() -> list[str]:
    """
    Devuelve teléfonos de usuarios cuyo trial expiró en las últimas 48h
    y aún no han recibido el mensaje de expiración.
    """
    if not _USE_DB:
        return []
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT s.phone
                    FROM subscribers s
                    WHERE s.plan = 'trial'
                      AND s.status = 'active'
                      AND s.expires_at IS NOT NULL
                      AND s.expires_at < now()
                      AND s.expires_at > now() - INTERVAL '48 hours'
                      AND NOT EXISTS (
                          SELECT 1 FROM events e
                          WHERE e.phone = s.phone
                            AND e.event_type = %s
                            AND e.created_at > now() - INTERVAL '5 days'
                      )
                """, (EventType.WA_TRIAL_EXPIRED,))
                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        log.error("get_expired_trial_candidates: %s", exc)
        return []


def get_daily_search_count(phone: str) -> int:
    """
    Cuenta las búsquedas del número realizadas hoy (hora Lima, UTC-5).
    Devuelve 0 si no hay DB (sin rate-limit en modo fallback).
    """
    if not _USE_DB:
        return 0
    try:
        from datetime import timedelta
        lima_tz = timezone(timedelta(hours=-5))
        lima_today_start = datetime.now(lima_tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM events
                    WHERE phone = %s
                      AND event_type = %s
                      AND created_at >= %s
                """, (phone, EventType.WA_SEARCH, lima_today_start))
                return (cur.fetchone() or [0])[0]
    except Exception as exc:
        log.error("get_daily_search_count(%s): %s", phone, exc)
        return 0


def get_monthly_search_count(phone: str) -> int:
    """
    Cuenta las búsquedas del número en el mes calendario actual (hora Lima, UTC-5).
    Devuelve 0 si no hay DB.
    """
    if not _USE_DB:
        return 0
    try:
        from datetime import timedelta
        lima_tz = timezone(timedelta(hours=-5))
        now_lima = datetime.now(lima_tz)
        month_start = now_lima.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM events
                    WHERE phone = %s
                      AND event_type = %s
                      AND created_at >= %s
                """, (phone, EventType.WA_SEARCH, month_start))
                return (cur.fetchone() or [0])[0]
    except Exception as exc:
        log.error("get_monthly_search_count(%s): %s", phone, exc)
        return 0


def has_trialed(phone: str) -> bool:
    """
    Devuelve True si el número ya usó alguna vez el trial (plan='trial'),
    independientemente de si está activo o expirado.
    """
    if not _USE_DB:
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM subscribers
                    WHERE phone = %s AND plan = 'trial'
                """, (phone,))
                return cur.fetchone() is not None
    except Exception as exc:
        log.error("has_trialed(%s): %s", phone, exc)
        return False


def log_event(phone: str | None, event_type: str, metadata: dict | None = None) -> None:
    """
    Registra un evento de funnel. Fire-and-forget — nunca lanza excepciones al caller.
    Si no hay DB, descarta silenciosamente (no crítico).
    """
    if not _USE_DB:
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO events (phone, event_type, metadata)
                    VALUES (%s, %s, %s)
                """, (phone, event_type, json.dumps(metadata or {})))
    except Exception as exc:
        log.warning("log_event(%s, %s): %s", phone, event_type, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# User Profiles
# ═══════════════════════════════════════════════════════════════════════════════

def get_user_profile(phone: str) -> dict:
    if not _USE_DB:
        return {}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, default_city, email, empresa, leads_mensuales
                    FROM user_profiles WHERE phone = %s
                """, (phone,))
                row = cur.fetchone()
                if not row:
                    return {}
                return {
                    "name": row[0],
                    "default_city": row[1],
                    "email": row[2],
                    "empresa": row[3],
                    "leads_mensuales": row[4],
                }
    except Exception as exc:
        log.error("get_user_profile(%s): %s", phone, exc)
        return {}


def save_user_profile(phone: str, name: str | None = None, default_city: str | None = None,
                      email: str | None = None, empresa: str | None = None,
                      leads_mensuales: str | None = None) -> None:
    """Guarda/actualiza perfil del usuario (upsert)."""
    if not _USE_DB:
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_profiles (phone, name, default_city, email, empresa, leads_mensuales, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (phone) DO UPDATE
                        SET name           = COALESCE(EXCLUDED.name, user_profiles.name),
                            default_city   = COALESCE(EXCLUDED.default_city, user_profiles.default_city),
                            email           = COALESCE(EXCLUDED.email, user_profiles.email),
                            empresa         = COALESCE(EXCLUDED.empresa, user_profiles.empresa),
                            leads_mensuales = COALESCE(EXCLUDED.leads_mensuales, user_profiles.leads_mensuales),
                            updated_at      = now()
                """, (phone, name, default_city, email, empresa, leads_mensuales))
    except Exception as exc:
        log.error("save_user_profile(%s): %s", phone, exc)


def get_search_history(phone: str, limit: int = 3) -> list[dict]:
    """Devuelve las últimas `limit` búsquedas del usuario con target y fecha."""
    if not _USE_DB:
        return []
    try:
        from datetime import timedelta
        lima_tz = timezone(timedelta(hours=-5))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT metadata->>'target' AS target, created_at
                    FROM events
                    WHERE phone = %s
                      AND event_type = %s
                      AND metadata->>'target' IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (phone, EventType.WA_SEARCH, limit))
                rows = cur.fetchall()
                result = []
                for row in rows:
                    target = row[0]
                    created_at = row[1]
                    if created_at:
                        lima_dt = created_at.astimezone(lima_tz)
                        date_str = lima_dt.strftime("%d/%m/%Y")
                    else:
                        date_str = "—"
                    result.append({"target": target, "date": date_str})
                return result
    except Exception as exc:
        log.error("get_search_history(%s): %s", phone, exc)
        return []


def get_broadcast_candidates(plan: str | None = None) -> list[str]:
    """
    Phones para broadcast: hicieron al menos 1 búsqueda WA, no están
    unsubscribed, opcionalmente filtrados por plan.
    """
    if not _USE_DB:
        return []
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                base_query = """
                    SELECT DISTINCT e.phone
                    FROM events e
                    WHERE e.event_type = %s
                      AND e.phone IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM events u
                          WHERE u.phone = e.phone
                            AND u.event_type = %s
                            AND NOT EXISTS (
                                SELECT 1 FROM events r
                                WHERE r.phone = u.phone
                                  AND r.event_type = %s
                                  AND r.created_at > u.created_at
                            )
                      )
                """
                if plan:
                    cur.execute(base_query + """
                        AND EXISTS (
                            SELECT 1 FROM subscribers s
                            WHERE s.phone = e.phone
                              AND s.plan = %s
                              AND s.status = 'active'
                        )
                    """, [EventType.WA_SEARCH, EventType.WA_UNSUBSCRIBED, EventType.WA_SEARCH, plan])
                else:
                    cur.execute(base_query, [EventType.WA_SEARCH, EventType.WA_UNSUBSCRIBED, EventType.WA_SEARCH])
                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        log.error("get_broadcast_candidates: %s", exc)
        return []


def get_unsubscribed_phones() -> set[str]:
    """
    Phones que se dieron de baja (wa_unsubscribed) y NO se han reactivado
    (no tienen wa_search posterior al último wa_unsubscribed).
    """
    if not _USE_DB:
        return set()
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT u.phone
                    FROM events u
                    WHERE u.event_type = %s
                      AND u.phone IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM events r
                          WHERE r.phone = u.phone
                            AND r.event_type = %s
                            AND r.created_at > u.created_at
                      )
                """, (EventType.WA_UNSUBSCRIBED, EventType.WA_SEARCH))
                return {row[0] for row in cur.fetchall()}
    except Exception as exc:
        log.error("get_unsubscribed_phones: %s", exc)
        return set()


def get_stats(days: int = 7) -> dict:
    """
    Devuelve métricas de funnel para los últimos `days` días.
    Retorna dict vacío si no hay DB.
    """
    if not _USE_DB:
        return {}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                interval = f"{days} days"

                # Conteo por tipo de evento
                cur.execute("""
                    SELECT event_type, COUNT(*) AS cnt
                    FROM events
                    WHERE created_at > now() - INTERVAL %s
                    GROUP BY event_type
                """, (interval,))
                counts = {row[0]: row[1] for row in cur.fetchall()}

                # Usuarios únicos que buscaron
                cur.execute("""
                    SELECT COUNT(DISTINCT phone) FROM events
                    WHERE event_type = %s
                      AND created_at > now() - INTERVAL %s
                """, (EventType.WA_SEARCH, interval))
                unique_searchers = (cur.fetchone() or [0])[0]

                # Suscriptores activos totales
                cur.execute("""
                    SELECT COUNT(*) FROM subscribers
                    WHERE status = 'active'
                      AND (expires_at IS NULL OR expires_at > now())
                """)
                active_subs = (cur.fetchone() or [0])[0]

                # Top 5 búsquedas
                cur.execute("""
                    SELECT metadata->>'target' AS target, COUNT(*) AS cnt
                    FROM events
                    WHERE event_type = %s
                      AND created_at > now() - INTERVAL %s
                      AND metadata->>'target' IS NOT NULL
                    GROUP BY target
                    ORDER BY cnt DESC
                    LIMIT 5
                """, (EventType.WA_SEARCH, interval))
                top_searches = [{"target": r[0], "count": r[1]} for r in cur.fetchall()]

                searches       = counts.get(EventType.WA_SEARCH, 0)
                delivered      = counts.get(EventType.WA_REPORT_DELIVERED, 0)
                upgrade_clicks = counts.get(EventType.WA_UPGRADE_CLICK, 0)
                activations    = counts.get(EventType.SUBSCRIBER_ACTIVATED, 0)

                def _pct(num, den):
                    return f"{round(num / den * 100, 1)}%" if den else "—"

                return {
                    "period_days":       days,
                    "searches":          searches,
                    "reports_delivered": delivered,
                    "upgrade_clicks":    upgrade_clicks,
                    "activations":       activations,
                    "unique_searchers":  unique_searchers,
                    "active_subscribers": active_subs,
                    "conversion": {
                        "search_to_upgrade": _pct(upgrade_clicks, searches),
                        "upgrade_to_paid":   _pct(activations, upgrade_clicks),
                        "search_to_paid":    _pct(activations, searches),
                    },
                    "top_searches": top_searches,
                }
    except Exception as exc:
        log.error("get_stats: %s", exc)
        return {}
