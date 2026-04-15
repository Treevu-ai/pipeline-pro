#!/usr/bin/env python3
"""
scripts/test_apify_call.py — Script de diagnóstico para llamadas a Apify.

Replica exactamente la petición POST que hace scraper.py::_search_via_apify
e imprime el status HTTP, los headers relevantes y el body truncado para
ayudar a identificar problemas de token, rate-limiting o respuestas inesperadas.

USO
---
    # 1. Exportar la clave (nunca la pegues en el código):
    export APIFY_API_KEY="tu_token_apify"

    # 2. Ejecutar el script con la query deseada:
    python3 scripts/test_apify_call.py "Abogados en Lima"

    # 3. Con parámetros opcionales:
    python3 scripts/test_apify_call.py "Restaurantes en Miraflores" --limit 5 --timeout 120

    # 4. Probar con curl equivalente:
    curl -v -X POST \
      "https://api.apify.com/v2/acts/compass~crawler-google-places/run-sync-get-dataset-items?token=$APIFY_API_KEY&timeout=120&memory=512" \
      -H "Content-Type: application/json" \
      -d '{"searchStringsArray":["Abogados en Lima"],"maxCrawledPlacesPerSearch":5,"language":"es","countryCode":"pe","includeHistogram":false,"includeOpeningHours":false,"includePeopleAlsoSearch":false}' \
      | python3 -m json.tool

QUÉ BUSCAR EN LA SALIDA
-----------------------
- HTTP 200 + array JSON con items → Apify funciona correctamente.
- HTTP 200 + array vacío []       → El actor no encontró resultados; prueba otra query.
- HTTP 401                        → Token inválido o expirado. Verifica APIFY_API_KEY.
- HTTP 403                        → Token sin permisos para este actor.
- HTTP 429                        → Rate limit / cuota agotada. Revisa tu plan en Apify.
- HTTP 4xx/5xx + body JSON        → Lee el campo "error.message" del body para detalles.
- Timeout                         → Aumenta --timeout o reduce --limit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_MAX_BODY_CHARS = 2000
_ACTOR_ID = "compass~crawler-google-places"
_APIFY_BASE = "https://api.apify.com/v2"

# Allow running the script from the repo root or from within the scripts/ dir.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from utils import trunc as _utils_trunc

    def _trunc(text: str, n: int = _MAX_BODY_CHARS) -> str:
        return _utils_trunc(text, n)
except Exception:
    def _trunc(text: str, n: int = _MAX_BODY_CHARS) -> str:
        """Fallback truncation used when utils is not importable."""
        if len(text) <= n:
            return text
        return text[:n] + f"…[truncado, {len(text) - n} chars omitidos]"


def run_diagnostic(query: str, limit: int, actor_timeout: int, http_timeout: int) -> int:
    """
    Ejecuta la petición a Apify e imprime resultado diagnóstico.

    Returns:
        0 si la llamada fue exitosa (HTTP 2xx con datos), 1 en caso de error.
    """
    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        print(
            "[ERROR] La variable de entorno APIFY_API_KEY no está configurada.\n"
            "        Exporta tu token antes de ejecutar este script:\n"
            "            export APIFY_API_KEY='tu_token_apify'",
            file=sys.stderr,
        )
        return 1

    try:
        import httpx
    except ImportError:
        print("[ERROR] Instala httpx: pip install httpx", file=sys.stderr)
        return 1

    run_url = f"{_APIFY_BASE}/acts/{_ACTOR_ID}/run-sync-get-dataset-items"
    params = {"token": api_key, "timeout": actor_timeout, "memory": 512}
    body = {
        "searchStringsArray": [query],
        "maxCrawledPlacesPerSearch": limit,
        "language": "es",
        "countryCode": "pe",
        "includeHistogram": False,
        "includeOpeningHours": False,
        "includePeopleAlsoSearch": False,
    }

    print(f"[INFO] Query          : {query!r}")
    print(f"[INFO] Límite leads   : {limit}")
    print(f"[INFO] Actor timeout  : {actor_timeout}s")
    print(f"[INFO] HTTP timeout   : {http_timeout}s")
    print(f"[INFO] URL            : {run_url}")
    print(f"[INFO] Body           : {json.dumps(body, ensure_ascii=False)}")
    print()

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(http_timeout, connect=10)) as client:
            resp = client.post(run_url, params=params, json=body)
    except httpx.TimeoutException:
        elapsed = time.monotonic() - t0
        print(
            f"[ERROR] Timeout tras {elapsed:.1f}s — "
            f"prueba aumentar --timeout o reducir --limit.",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        print(f"[ERROR] Error de red: {e}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - t0

    # ── Imprimir status y headers relevantes ─────────────────────────────────
    print(f"[RESULT] Status       : {resp.status_code} (en {elapsed:.1f}s)")
    interesting_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() in (
            "content-type", "x-request-id", "retry-after",
            "x-apify-pagination-total", "x-apify-pagination-limit",
        )
    }
    print(f"[RESULT] Headers      : {interesting_headers}")

    # ── Imprimir body truncado ────────────────────────────────────────────────
    body_text = resp.text
    print(f"[RESULT] Body (chars) : {len(body_text)}")
    print(f"[RESULT] Body preview :\n{_trunc(body_text)}")
    print()

    if resp.status_code == 401:
        print("[DIAGNÓSTICO] Token inválido o expirado — verifica APIFY_API_KEY.")
        return 1
    if resp.status_code == 403:
        print("[DIAGNÓSTICO] Token sin permisos — verifica permisos en app.apify.com.")
        return 1
    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after", "?")
        print(f"[DIAGNÓSTICO] Rate limit / cuota agotada — retry-after: {retry_after}s.")
        return 1
    if resp.status_code >= 400:
        print(f"[DIAGNÓSTICO] Error HTTP {resp.status_code} — revisa el body para más detalles.")
        return 1

    # ── Intentar parsear JSON ─────────────────────────────────────────────────
    try:
        data = resp.json()
    except ValueError as e:
        print(f"[ERROR] La respuesta no es JSON válido: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, list):
        print(
            f"[ERROR] Se esperaba una lista JSON pero se recibió: {type(data).__name__}",
            file=sys.stderr,
        )
        return 1

    if not data:
        print("[DIAGNÓSTICO] El actor devolvió una lista vacía — prueba con otra query.")
        return 0

    print(f"[OK] Apify devolvió {len(data)} resultado(s).")
    print(f"[OK] Primer resultado: {_trunc(json.dumps(data[0], ensure_ascii=False, indent=2))}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnóstico de llamadas a Apify Google Maps Scraper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("query", help="Búsqueda a realizar (ej: 'Abogados en Lima')")
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Número máximo de resultados a solicitar (default: 5)",
    )
    parser.add_argument(
        "--timeout", type=int, default=120,
        help="Timeout del actor Apify en segundos (default: 120)",
    )
    parser.add_argument(
        "--http-timeout", type=int, default=180,
        help="Timeout HTTP del cliente en segundos (default: 180)",
    )
    args = parser.parse_args()
    sys.exit(run_diagnostic(args.query, args.limit, args.timeout, args.http_timeout))


if __name__ == "__main__":
    main()
