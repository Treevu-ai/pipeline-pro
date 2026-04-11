"""
logging_config.py — Logging estructurado para Pipeline_X.

Uso:
    import logging_config
    logging_config.setup()          # llamar una sola vez al iniciar

Resultado:
  - Formato: "2026-04-11 12:00:00 INFO  [api] Pipeline started for 51987654321"
  - Railway captura stdout → logs visibles en dashboard con niveles filtrables
  - Nivel configurable via LOG_LEVEL env var (default: INFO)
"""
from __future__ import annotations

import logging
import os
import sys


def setup() -> None:
    """
    Configura el logging global de la aplicación.
    Idempotente — puede llamarse múltiples veces sin duplicar handlers.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level      = getattr(logging, level_name, logging.INFO)

    # Formato legible pero parseable por Railway y otros log aggregators
    fmt = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    if root.handlers:
        return   # ya configurado

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(handler)
    root.setLevel(level)

    # Silenciar loggers muy ruidosos de librerías externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    logging.getLogger("pipeline_x").info(
        "Logging configurado: level=%s", level_name
    )
