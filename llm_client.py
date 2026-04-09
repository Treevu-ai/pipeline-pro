"""
llm_client.py — Cliente LLM con soporte para Claude y Groq.

Prioridad: Claude (si ANTHROPIC_API_KEY está disponible) → Groq (fallback).
Interfaz: call(system, user) -> dict
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import config as cfg
import exceptions as exc


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


# ── Claude ────────────────────────────────────────────────────────────────────

_claude_client = None

def _get_claude():
    global _claude_client
    if _claude_client is None:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise exc.LLMCallError("ANTHROPIC_API_KEY no está configurada", model="claude")
        _claude_client = anthropic.Anthropic(api_key=api_key)
    return _claude_client


def _call_claude(system: str, user: str) -> dict[str, Any]:
    client = _get_claude()
    model   = cfg.CLAUDE["model"]
    retries = cfg.CLAUDE["retries"]
    backoff = cfg.CLAUDE["backoff_s"]

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=cfg.CLAUDE["max_tokens"],
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=0,  # determinista — mismos datos → mismo score siempre
                timeout=60,
            )
            content = msg.content[0].text if msg.content else ""
            return _parse_json_loose(content)
        except exc.LLMResponseError:
            raise
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * attempt)

    raise exc.LLMCallError(
        f"Claude no respondió después de {retries} intentos", model=model
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
            if attempt < retries:
                time.sleep(backoff * attempt)

    raise exc.LLMCallError(
        f"Groq no respondió después de {retries} intentos", model=model
    ) from last_err


# ── Interfaz pública ──────────────────────────────────────────────────────────

def call(system: str, user: str) -> dict[str, Any]:
    """
    Llama al LLM disponible: Claude si ANTHROPIC_API_KEY está en el entorno,
    Groq como fallback.

    Args:
        system: Prompt del sistema.
        user:   Prompt del usuario.

    Returns:
        Diccionario con la respuesta del LLM.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_claude(system, user)
    return _call_groq(system, user)
