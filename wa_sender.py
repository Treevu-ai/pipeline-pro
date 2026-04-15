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
import time

import httpx

import config as cfg

log = logging.getLogger("wa_sender")


# ─── Retry helper ─────────────────────────────────────────────────────────────

def _post_with_retry(url: str, retries: int = 3, **kwargs) -> httpx.Response:
    """
    POST con backoff exponencial (1s → 2s → 4s).
    Solo reintenta en errores de red y 5xx; los 4xx son errores del cliente
    y no tiene sentido reintentar.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = httpx.post(url, **kwargs)
            if r.status_code < 500:
                return r       # 2xx, 3xx, 4xx → devolver sin reintentar
            # 5xx — esperar y reintentar
            log.warning("Green API 5xx (intento %d/%d): %s", attempt + 1, retries, r.status_code)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            log.warning("Green API error de red (intento %d/%d): %s", attempt + 1, retries, exc)
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(2 ** attempt)   # 1s, 2s (no llega a 4s si retries=3)
    if last_exc:
        raise last_exc
    raise httpx.HTTPStatusError("Green API 5xx tras reintentos", request=None, response=r)


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _base_url() -> str:
    url  = cfg.GREEN_API["api_url"].rstrip("/")
    inst = cfg.GREEN_API["id_instance"]
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

    Returns:
        Dict con {"idMessage": "..."} si OK, {} si hubo error (logueado).
    """
    url  = f"{_base_url()}/sendMessage/{_token()}"
    body = {"chatId": _chat_id(phone), "message": text}
    log.debug("WA send → %s: %r", phone, text[:80])
    try:
        r = _post_with_retry(url, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        log.error("send_text error %s para %s: %s", exc.response.status_code, phone, exc.response.text[:200])
        return {}
    except Exception as exc:
        log.error("send_text exception para %s: %s", phone, exc)
        return {}


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


def send_buttons(
    phone: str,
    body: str,
    buttons: list[dict],
    header: str = "",
    footer: str = "",
    timeout: int = 10,
) -> dict:
    """
    Envía un mensaje con hasta 3 botones interactivos.

    Args:
        phone:   Número del destinatario.
        body:    Texto del cuerpo del mensaje.
        buttons: Lista de dicts {"id": str, "text": str} (máx 3 items).
        header:  Texto de cabecera (opcional).
        footer:  Texto de pie (opcional).

    Returns:
        Dict con {"idMessage": "..."} si OK, o {} si el tipo no está soportado.
    """
    url = f"{_base_url()}/sendButtons/{_token()}"
    payload: dict = {
        "chatId":   _chat_id(phone),
        "message":  body,
        "buttons":  [
            {"buttonId": b["id"], "buttonText": {"displayText": b["text"]}}
            for b in buttons[:3]
        ],
    }
    if header:
        payload["headerType"] = "TEXT"
        payload["header"]     = header
    if footer:
        payload["footer"] = footer
    log.debug("WA buttons → %s: %r", phone, body[:80])
    try:
        r = _post_with_retry(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        # Green API retorna 400 si la instancia no soporta botones interactivos;
        # en ese caso enviamos como texto plano con las opciones numeradas.
        log.warning("send_buttons no soportado (%s) — fallback texto", exc.response.status_code)
        fallback = body
        if header:
            fallback = f"*{header}*\n\n{fallback}"
        options = "\n".join(f"*{b['id']}.* {b['text']}" for b in buttons[:3])
        return send_text(phone, f"{fallback}\n\n{options}", timeout=timeout)


def send_list(
    phone: str,
    body: str,
    button_text: str,
    sections: list[dict],
    footer: str = "",
    timeout: int = 10,
) -> dict:
    """
    Envía un mensaje con lista de opciones seleccionables (máx 10 filas).

    Args:
        phone:       Número del destinatario.
        body:        Texto del cuerpo del mensaje.
        button_text: Etiqueta del botón que abre la lista.
        sections:    Lista de secciones; cada una tiene "title" y "rows":
                     [{"title": "...", "rows": [{"id": "1", "title": "...", "description": "..."}, ...]}]
        footer:      Texto de pie (opcional).

    Returns:
        Dict con {"idMessage": "..."} si OK, o {} si no está soportado.
    """
    url = f"{_base_url()}/sendListMessage/{_token()}"
    payload: dict = {
        "chatId":     _chat_id(phone),
        "message":    body,
        "buttonText": button_text,
        "sections":   [
            {
                "title": s.get("title", ""),
                "rows":  [
                    {
                        "rowId":       row["id"],
                        "title":       row["title"],
                        "description": row.get("description", ""),
                    }
                    for row in s["rows"]
                ],
            }
            for s in sections
        ],
    }
    if footer:
        payload["footer"] = footer
    log.debug("WA list → %s: %r", phone, body[:80])
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        log.warning("send_list no soportado (%s) — fallback texto", exc.response.status_code)
        # Fallback: texto con opciones numeradas
        lines = [body, ""]
        for s in sections:
            for row in s["rows"]:
                lines.append(f"*{row['id']}.* {row['title']}")
                if row.get("description"):
                    lines.append(f"   {row['description']}")
        return send_text(phone, "\n".join(lines), timeout=timeout)


def send_document(
    phone: str,
    filename: str,
    content: bytes,
    caption: str = "",
    timeout: int = 30,
) -> dict:
    """
    Envía un archivo (CSV, PDF, etc.) al número dado usando multipart upload.

    Args:
        phone:    Número del destinatario.
        filename: Nombre del archivo con extensión (ej: "leads.csv").
        content:  Bytes del archivo.
        caption:  Texto opcional que acompaña al archivo.

    Returns:
        Dict con {"idMessage": "..."} si OK.
    """
    url = f"{_base_url()}/sendFileByUpload/{_token()}"
    files   = {"file": (filename, content, "application/octet-stream")}
    data    = {"chatId": _chat_id(phone), "caption": caption, "fileName": filename}
    log.debug("WA document → %s: %s (%d bytes)", phone, filename, len(content))
    try:
        r = _post_with_retry(url, data=data, files=files, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        log.error("send_document falló (%s): %s", exc.response.status_code, exc.response.text[:200])
        raise


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


def set_typing(phone: str, typing: bool = True, timeout: int = 5) -> bool:
    """
    Activa/desactiva el indicador de "escribiendo...".
    typing=True  → muestra "Pipeline_X está escribiendo..."
    typing=False → berhenti writing indicator
    """
    url = f"{_base_url()}/setChatPresence/{_token()}"
    payload = {
        "chatId": _chat_id(phone),
        "presence": "composing" if typing else "paused",
    }
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return True
    except Exception as exc:
        log.warning("setChatPresence falló: %s", exc)
        return False
