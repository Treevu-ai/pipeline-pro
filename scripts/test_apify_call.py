#!/usr/bin/env python3
"""
scripts/test_apify_call.py — Diagnóstico de llamadas al actor Apify.

Replica exactamente la petición POST que hace scraper.py::_search_via_apify
e imprime status HTTP, headers relevantes y body truncado para facilitar el
diagnóstico de errores 401 / 403 / 429 / 5xx o JSON inválido.

Uso:
    export APIFY_API_KEY="tu_token_aqui"
    python3 scripts/test_apify_call.py "Abogados en Lima"
    python3 scripts/test_apify_call.py "Restaurantes en Miraflores" --limit 10
    python3 scripts/test_apify_call.py "Farmacias en Cusco" --actor-timeout 90 --http-timeout 120

Variables de entorno:
    APIFY_API_KEY          Token de la API de Apify (obligatorio).
    APIFY_ACTOR_TIMEOUT_S  Timeout interno del actor en segundos (default: 120).
    APIFY_HTTP_TIMEOUT_S   Timeout del cliente HTTP en segundos (default: 180).

Notas de seguridad:
    - El token se lee solo del entorno; no se muestra en la salida.
    - Los cuerpos de respuesta se truncan a 2000 caracteres para evitar
      volcar secrets o datos sensibles en logs/terminal.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Añadir el directorio raíz del proyecto al path para poder importar utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRUNC_LIMIT = 2000
RELEVANT_HEADERS = {
    "content-type",
    "x-request-id",
    "retry-after",
    "x-apify-error-type",
    "x-apify-run-id",
}

try:
    from utils import trunc as _trunc

    def trunc(s: object, n: int = TRUNC_LIMIT) -> str:
        return _trunc(s, n)
except ImportError:
    def trunc(s: object, n: int = TRUNC_LIMIT) -> str:  # type: ignore[misc]
        """Convierte *s* a string y trunca a *n* caracteres de forma segura."""
        text = str(s) if not isinstance(s, str) else s
        return text if len(text) <= n else text[:n] + "…"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico de llamadas al actor Apify (Google Maps Scraper).",
    )
    parser.add_argument("query", help="Término de búsqueda, ej: 'Abogados en Lima'")
    parser.add_argument("--limit", type=int, default=5, help="Máx. resultados (default: 5)")
    parser.add_argument(
        "--actor-timeout",
        type=int,
        default=int(os.environ.get("APIFY_ACTOR_TIMEOUT_S", "120")),
        help="Timeout interno del actor en segundos (default: 120)",
    )
    parser.add_argument(
        "--http-timeout",
        type=int,
        default=int(os.environ.get("APIFY_HTTP_TIMEOUT_S", "180")),
        help="Timeout del cliente HTTP en segundos (default: 180)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        print(
            "ERROR: La variable de entorno APIFY_API_KEY no está definida.\n"
            "Exporta tu token antes de ejecutar este script:\n"
            "  export APIFY_API_KEY='tu_token_aqui'",
            file=sys.stderr,
        )
        return 1

    try:
        import httpx
    except ImportError:
        print(
            "ERROR: httpx no está instalado. Ejecuta:\n  pip install httpx",
            file=sys.stderr,
        )
        return 1

    actor_id = "compass~crawler-google-places"
    run_url = (
        f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    )
    params = {
        "token": api_key,
        "timeout": args.actor_timeout,
        "memory": 512,
    }
    body = {
        "searchStringsArray": [args.query],
        "maxCrawledPlacesPerSearch": min(args.limit, 20),
        "language": "es",
        "countryCode": "pe",
        "includeHistogram": False,
        "includeOpeningHours": False,
        "includePeopleAlsoSearch": False,
    }

    print(f"\n{'='*60}")
    print(f"Actor  : {actor_id}")
    print(f"Query  : {args.query}")
    print(f"Limit  : {args.limit}")
    print(f"Timeouts: actor={args.actor_timeout}s  http={args.http_timeout}s")
    print(f"{'='*60}\n")
    print(f"POST {run_url}")
    print(f"Body   : {json.dumps(body, ensure_ascii=False)}\n")

    try:
        with httpx.Client(timeout=httpx.Timeout(args.http_timeout, connect=10)) as client:
            resp = client.post(run_url, params=params, json=body)
    except httpx.TimeoutException as e:
        print(f"TIMEOUT ({args.http_timeout}s): {e}", file=sys.stderr)
        return 1
    except httpx.RequestError as e:
        print(f"REQUEST ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Status : {resp.status_code}")
    filtered = {k: v for k, v in resp.headers.items() if k.lower() in RELEVANT_HEADERS}
    print(f"Headers: {json.dumps(filtered, indent=2)}")
    print(f"\nBody (primeros {TRUNC_LIMIT} chars):\n{trunc(resp.text)}\n")

    # Diagnosticar código de estado
    status = resp.status_code
    if status == 200:
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            print(f"JSON PARSE ERROR: {e}")
            return 1
        if not isinstance(data, list):
            print(f"ADVERTENCIA: Se esperaba una lista JSON, se recibió {type(data).__name__}")
            return 1
        print(f"\nResultados: {len(data)} items")
        if data:
            print("Primer item (preview):")
            first = data[0]
            for key in ("title", "address", "phone", "totalScore", "website"):
                print(f"  {key}: {first.get(key, '')}")
        else:
            print("Dataset vacío — Apify no encontró resultados para esta búsqueda.")
    elif status == 401:
        print("\nDIAGNÓSTICO: 401 Unauthorized — APIFY_API_KEY inválida o expirada.")
        print("Acción: verifica el token en https://console.apify.com/account/integrations")
        return 1
    elif status == 403:
        print("\nDIAGNÓSTICO: 403 Forbidden — token sin permisos o actor privado.")
        print("Acción: revisa los permisos del token y el acceso al actor.")
        return 1
    elif status == 429:
        retry_after = resp.headers.get("retry-after", "desconocido")
        print(f"\nDIAGNÓSTICO: 429 Too Many Requests — cuota o rate-limit superado.")
        print(f"Retry-After: {retry_after}s")
        print("Acción: espera antes de reintentar o revisa el plan/cuota en Apify.")
        return 1
    else:
        print(f"\nDIAGNÓSTICO: HTTP {status} — error inesperado del servidor Apify.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
