"""
llm_client.py — Cliente LLM con soporte para OpenAI y Groq.

Prioridad: OpenAI (gpt-4o-mini, costo-efectivo) → Groq (fallback).
Interfaz: call(system, user) -> dict
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import config as cfg
import exceptions as exc

log = logging.getLogger("llm_client")


def _parse_json_loose(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise exc.LLMResponseError(
                "No se pudo parsear JSON de la respuesta del LLM", response=text
            )
        return json.loads(m.group(0))


def _fix_encoding(obj: Any) -> Any:
    """Corrige doble-codificación UTF-8 que algunos LLMs producen en texto español.
    Ejemplo: 'presentaciÃ³n' (latin-1 mal interpretado) → 'presentación'."""
    if isinstance(obj, str):
        try:
            return obj.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return obj
    if isinstance(obj, dict):
        return {k: _fix_encoding(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fix_encoding(i) for i in obj]
    return obj


# ── OpenAI (primario) ─────────────────────────────────────────────────────────

_openai_client = None

def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise exc.LLMCallError("OPENAI_API_KEY no está configurada", model="openai")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def _call_openai(system: str, user: str) -> dict[str, Any]:
    client = _get_openai()
    model = cfg.OPENAI["model"]
    retries = cfg.OPENAI["retries"]
    backoff = cfg.OPENAI["backoff_s"]

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            msg = client.chat.completions.create(
                model=model,
                max_tokens=cfg.OPENAI["max_tokens"],
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=cfg.OPENAI.get("temperature", 0),
                response_format={"type": "json_object"},
                timeout=60,
            )
            content = (msg.choices[0].message.content or "").strip()
            return _fix_encoding(_parse_json_loose(content))
        except exc.LLMResponseError:
            raise
        except Exception as e:
            last_err = e
            log.warning("OpenAI intento %d/%d — %s: %s", attempt, retries, type(e).__name__, e)
            for attr in ("response", "body", "message", "args"):
                val = getattr(e, attr, None)
                if val:
                    try:
                        body_text = val.text if hasattr(val, "text") else str(val)
                        log.error("OpenAI error.%s: %s", attr, body_text[:500])
                    except Exception:
                        pass
            if attempt < retries:
                time.sleep(backoff * attempt)

    raise exc.LLMCallError(
        f"OpenAI no respondió después de {retries} intentos", model=model
    ) from last_err


# ── Groq (fallback) ───────────────────────────────────────────────────────────

_groq_client = None

def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise exc.ConfigurationError("GROQ_API_KEY no está configurada")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def _call_groq(system: str, user: str) -> dict[str, Any]:
    client = _get_groq()
    model = cfg.GROQ.get("model", "llama-3.3-70b-versatile")
    retries = cfg.GROQ.get("retries", 3)
    backoff = cfg.GROQ.get("backoff_s", 2)

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=cfg.GROQ.get("temperature", 0.2),
                response_format={"type": "json_object"},
                timeout=60,
            )
            content = response.choices[0].message.content or ""
            return _fix_encoding(_parse_json_loose(content))
        except exc.LLMResponseError:
            raise
        except Exception as e:
            last_err = e
            # Rate limit (429): esperar más tiempo antes de reintentar
            err_str = str(e).lower()
            if "429" in err_str or "rate limit" in err_str or "rate_limit" in err_str:
                wait = backoff * (attempt * 3)  # espera extendida en 429
                if attempt < retries:
                    time.sleep(wait)
            elif attempt < retries:
                time.sleep(backoff * attempt)

    raise exc.RateLimitError(
        f"Groq rate limit alcanzado después de {retries} intentos"
    ) if last_err and ("429" in str(last_err) or "rate" in str(last_err).lower()) else exc.LLMCallError(
        f"Groq no respondió después de {retries} intentos", model=model
    )


def _call_openai_raw(system: str, user: str) -> str:
    """OpenAI sin `response_format`: útil cuando la salida es un JSON array u otro texto."""
    client = _get_openai()
    model = cfg.OPENAI["model"]
    retries = cfg.OPENAI["retries"]
    backoff = cfg.OPENAI["backoff_s"]
    raw_max = min(16384, max(int(cfg.OPENAI.get("max_tokens", 1024)), 8192))

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            msg = client.chat.completions.create(
                model=model,
                max_tokens=raw_max,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=cfg.OPENAI.get("temperature", 0),
                timeout=120,
            )
            return (msg.choices[0].message.content or "").strip()
        except Exception as e:
            last_err = e
            log.warning(
                "OpenAI raw intento %d/%d — %s: %s", attempt, retries, type(e).__name__, e
            )
            if attempt < retries:
                time.sleep(backoff * attempt)

    raise exc.LLMCallError(
        f"OpenAI (raw) no respondió después de {retries} intentos", model=model
    ) from last_err


def _call_groq_raw(system: str, user: str) -> str:
    """Groq sin `response_format` json_object (salida texto / JSON array)."""
    client = _get_groq()
    model = cfg.GROQ.get("model", "llama-3.3-70b-versatile")
    retries = cfg.GROQ.get("retries", 3)
    backoff = cfg.GROQ.get("backoff_s", 2)

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=cfg.GROQ.get("temperature", 0.2),
                max_tokens=8192,
                timeout=90,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "429" in err_str or "rate limit" in err_str or "rate_limit" in err_str:
                wait = backoff * (attempt * 3)
                if attempt < retries:
                    time.sleep(wait)
            elif attempt < retries:
                time.sleep(backoff * attempt)

    raise exc.RateLimitError(
        f"Groq rate limit alcanzado después de {retries} intentos"
    ) if last_err and ("429" in str(last_err) or "rate" in str(last_err).lower()) else exc.LLMCallError(
        f"Groq (raw) no respondió después de {retries} intentos", model=model
    )


def call_raw(system: str, user: str) -> str:
    """
    Texto crudo del LLM (OpenAI primario → Groq fallback).
    Usar cuando la salida no es un único JSON object (p. ej. batch JSON array).
    """
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return _call_openai_raw(system, user)
        except (exc.LLMCallError, exc.RateLimitError) as e:
            if os.environ.get("GROQ_API_KEY"):
                log.warning("OpenAI falló (%s) — usando Groq como fallback (raw)", e)
                return _call_groq_raw(system, user)
            raise
    if os.environ.get("GROQ_API_KEY"):
        return _call_groq_raw(system, user)
    raise exc.ConfigurationError("Se requiere OPENAI_API_KEY o GROQ_API_KEY")


# ── Interfaz pública ──────────────────────────────────────────────────────────

def call(system: str, user: str) -> dict[str, Any]:
    """
    Llama al LLM disponible: OpenAI (primario) → Groq (fallback si OpenAI falla
    tras reintentos y hay GROQ_API_KEY).

    Args:
        system: Prompt del sistema.
        user:   Prompt del usuario.

    Returns:
        Diccionario con la respuesta del LLM.
    """
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return _call_openai(system, user)
        except (exc.LLMCallError, exc.RateLimitError) as e:
            if os.environ.get("GROQ_API_KEY"):
                log.warning("OpenAI falló (%s) — usando Groq como fallback", e)
                return _call_groq(system, user)
            raise
    if os.environ.get("GROQ_API_KEY"):
        return _call_groq(system, user)
    raise exc.ConfigurationError("Se requiere OPENAI_API_KEY o GROQ_API_KEY")
