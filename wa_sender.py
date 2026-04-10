"""
wa_sender.py — Envío de mensajes WhatsApp via Green API.

Wrapper minimalista sobre la REST API de Green API.
El número ya está vinculado vía QR en console.green-api.com.

Uso:
    from wa_sender import send_text, mark_read
    send_text("51987654321", "Hola, gracias por escribir.")
"""
from __future__ import annotations

import logging
import os

import httpx

import config as cfg

log = logging.getLogger("wa_sender")


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _base_url() -> str:
    url    = cfg.GREEN_API["api_url"].rstrip("/")
    inst   = cfg.GREEN_API["id_instance"]
    token  = cfg.GREEN_API["token"]
    return f"{url}/waInstance{inst}"


def _token() -> str:
    return cfg.GREEN_API["token"]


def _chat_id(phone: str) -> str:
    """
    Convierte número a formato chatId de Green API.
    Acepta: '51987654321', '+51987654321', '987654321' (asume Perú +51).
    """
    phone = phone.strip().lstrip("+").replace(" ", "").replace("-", "")
    if not phone.startswith("51") and len(phone) == 9:
        phone = "51" + phone          # asumir Perú si solo 9 dígitos
    return f"{phone}@c.us"


# ─── API pública ──────────────────────────────────────────────────────────────

def send_text(phone: str, text: str, timeout: int = 10) -> dict:
    """
    Envía un mensaje de texto al número dado.

    Args:
        phone: Número del destinatario (cualquier formato).
        text:  Texto del mensaje (máx 20.000 caracteres).

    Returns:
        Dict con {"idMessage": "..."} si OK.

    Raises:
        httpx.HTTPStatusError: si la API devuelve error HTTP.
    """
    url  = f"{_base_url()}/sendMessage/{_token()}"
    body = {"chatId": _chat_id(phone), "message": text}
    log.debug("WA send → %s: %r", phone, text[:80])
    r = httpx.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def mark_read(phone: str, id_message: str, timeout: int = 5) -> None:
    """
    Marca un mensaje como leído (muestra los dos ticks azules).
    Mejora la UX — el usuario sabe que recibió respuesta.
    """
    url  = f"{_base_url()}/readChat/{_token()}"
    body = {"chatId": _chat_id(phone), "idMessage": id_message}
    try:
        httpx.post(url, json=body, timeout=timeout)
    except Exception as exc:
        log.debug("mark_read falló (no crítico): %s", exc)


def set_webhook(webhook_url: str, timeout: int = 10) -> bool:
    """
    Configura el webhook de Green API para recibir mensajes entrantes.
    Llamar una sola vez al iniciar la app (o cuando cambia la URL).

    Args:
        webhook_url: URL pública donde Green API enviará los mensajes.
                     Ej: "https://tu-api.railway.app/webhook/whatsapp"

    Returns:
        True si se guardó correctamente.
    """
    url  = f"{_base_url()}/setSettings/{_token()}"
    body = {
        "webhookUrl":                      webhook_url,
        "incomingWebhook":                 "yes",
        "outgoingWebhook":                 "no",
        "stateWebhook":                    "no",
        "markIncomingMessagesReaded":      "yes",
        "delaySendMessagesMilliseconds":   1000,
    }
    r = httpx.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    ok = r.json().get("saveSettings", False)
    if ok:
        log.info("Webhook configurado: %s", webhook_url)
    else:
        log.warning("Green API no confirmó el webhook: %s", r.text)
    return ok


def get_state(timeout: int = 5) -> str:
    """
    Devuelve el estado de la instancia: 'authorized', 'notAuthorized', etc.
    Útil para healthcheck.
    """
    url = f"{_base_url()}/getStateInstance/{_token()}"
    try:
        r = httpx.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json().get("stateInstance", "unknown")
    except Exception as exc:
        log.warning("getStateInstance falló: %s", exc)
        return "error"
