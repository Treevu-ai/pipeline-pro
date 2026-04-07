"""
llm_client.py — Cliente LLM usando Groq API.

Reemplaza la llamada a Ollama con Groq, manteniendo
la misma interfaz: call(system, user) -> dict.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import config as cfg
import exceptions as exc

_client = None


def _get_client():
    global _client
    if _client is None:
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise exc.ConfigurationError("GROQ_API_KEY no está configurada en las variables de entorno")
        _client = Groq(api_key=api_key)
    return _client


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


def call(system: str, user: str) -> dict[str, Any]:
    """
    Llama a Groq con reintentos y backoff exponencial.

    Interfaz idéntica a ollama_call() para facilitar la migración.

    Args:
        system: Prompt del sistema.
        user:   Prompt del usuario.

    Returns:
        Diccionario con la respuesta del LLM.

    Raises:
        OllamaError: Si Groq no responde tras todos los reintentos.
    """
    client = _get_client()
    model = cfg.GROQ.get("model", "llama-3.3-70b-versatile")
    retries = cfg.GROQ.get("retries", 3)
    backoff = cfg.GROQ.get("backoff_s", 2)
    temperature = cfg.GROQ.get("temperature", 0.2)

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            return _parse_json_loose(content)
        except exc.LLMResponseError:
            raise
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = backoff * attempt
                time.sleep(wait)

    raise exc.OllamaError(
        f"Groq no respondió después de {retries} intentos",
        model=model,
    ) from last_err
