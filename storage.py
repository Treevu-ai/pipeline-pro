"""
storage.py — Almacenamiento de PDFs para Pipeline_X.

Prioridad:
  1. Cloudflare R2 (S3-compatible) si las variables R2_* están configuradas.
  2. Filesystem local como fallback (desarrollo local / Railway sin R2).

Variables de entorno requeridas para R2:
  R2_ACCOUNT_ID        → tu Cloudflare Account ID
  R2_ACCESS_KEY_ID     → R2 Access Key ID (desde R2 → Manage API Tokens)
  R2_SECRET_ACCESS_KEY → R2 Secret Access Key
  R2_BUCKET_NAME       → nombre del bucket (ej: pipeline-x-reports)
  R2_PUBLIC_URL        → URL pública del bucket (ej: https://pub-xxx.r2.dev)
                         Si no está, se sirve vía /r/{token} en streaming.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("storage")

# ─── Configuración ────────────────────────────────────────────────────────────

_ACCOUNT_ID    = os.environ.get("R2_ACCOUNT_ID", "")
_ACCESS_KEY    = os.environ.get("R2_ACCESS_KEY_ID", "")
_SECRET_KEY    = os.environ.get("R2_SECRET_ACCESS_KEY", "")
_BUCKET        = os.environ.get("R2_BUCKET_NAME", "pipeline-x-reports")
_PUBLIC_URL    = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")

_USE_R2 = bool(_ACCOUNT_ID and _ACCESS_KEY and _SECRET_KEY)

# Directorio local de fallback
_LOCAL_DIR = Path("output/reports")
_LOCAL_DIR.mkdir(parents=True, exist_ok=True)


def _r2_client():
    """Devuelve cliente boto3 apuntando a Cloudflare R2."""
    import boto3
    endpoint = f"https://{_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name="auto",
    )


# ─── API pública ──────────────────────────────────────────────────────────────

def save_report(data: bytes) -> str:
    """
    Guarda el PDF y devuelve un token único.
    En R2: sube como {token}.pdf.
    En local: escribe en output/reports/{token}.pdf.
    """
    token = secrets.token_urlsafe(8)
    key   = f"{token}.pdf"

    if _USE_R2:
        try:
            client = _r2_client()
            client.put_object(
                Bucket=_BUCKET,
                Key=key,
                Body=data,
                ContentType="application/pdf",
            )
            log.info("PDF subido a R2: %s (%d bytes)", key, len(data))
            return token
        except Exception as exc:
            log.error("R2 upload falló, usando fallback local: %s", exc)

    # Fallback local
    path = _LOCAL_DIR / key
    path.write_bytes(data)
    log.info("PDF guardado en local: %s (%d bytes)", path, len(data))
    return token


def get_report_url(token: str, api_base: str) -> str:
    """
    Devuelve la URL de descarga del PDF.
    - R2 con URL pública: URL directa al bucket.
    - R2 sin URL pública: presigned URL (válida 48h).
    - Local: URL del endpoint /r/{token} de la API.
    """
    key = f"{token}.pdf"

    if _USE_R2:
        if _PUBLIC_URL:
            return f"{_PUBLIC_URL}/{key}"
        try:
            client = _r2_client()
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": _BUCKET, "Key": key},
                ExpiresIn=172800,  # 48 horas
            )
            return url
        except Exception as exc:
            log.error("R2 presigned URL falló: %s", exc)

    return f"{api_base}/r/{token}"


def get_report_bytes(token: str) -> bytes | None:
    """
    Lee los bytes del PDF (solo usado en fallback local para servir vía streaming).
    En R2 con URL pública/presigned no se necesita.
    """
    if _USE_R2:
        try:
            client = _r2_client()
            obj = client.get_object(Bucket=_BUCKET, Key=f"{token}.pdf")
            return obj["Body"].read()
        except Exception as exc:
            log.error("R2 get_object falló: %s", exc)
            return None

    path = _LOCAL_DIR / f"{token}.pdf"
    return path.read_bytes() if path.exists() else None


def delete_old_reports(max_age_days: int = 7) -> int:
    """
    Elimina PDFs con más de max_age_days días. Devuelve cantidad eliminada.
    """
    import time as _time

    deleted = 0

    if _USE_R2:
        try:
            client  = _r2_client()
            cutoff  = _time.time() - max_age_days * 86400
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=_BUCKET):
                for obj in page.get("Contents", []):
                    if obj["LastModified"].timestamp() < cutoff:
                        client.delete_object(Bucket=_BUCKET, Key=obj["Key"])
                        deleted += 1
            if deleted:
                log.info("R2 cleanup: %d PDFs eliminados (>%dd)", deleted, max_age_days)
        except Exception as exc:
            log.error("R2 cleanup falló: %s", exc)
        return deleted

    # Fallback local
    now = _time.time()
    for f in _LOCAL_DIR.glob("*.pdf"):
        try:
            if now - f.stat().st_mtime > max_age_days * 86400:
                f.unlink()
                deleted += 1
        except Exception:
            pass
    if deleted:
        log.info("Local cleanup: %d PDFs eliminados (>%dd)", deleted, max_age_days)
    return deleted


def report_exists(token: str) -> bool:
    """Comprueba si el PDF existe."""
    if _USE_R2:
        try:
            _r2_client().head_object(Bucket=_BUCKET, Key=f"{token}.pdf")
            return True
        except Exception:
            return False
    return (_LOCAL_DIR / f"{token}.pdf").exists()
