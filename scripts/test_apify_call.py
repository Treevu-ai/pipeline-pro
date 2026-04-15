#!/usr/bin/env python3
"""
scripts/test_apify_call.py

Script de diagnóstico que replica la POST a Apify usada por scraper.py.

Uso:
  export APIFY_API_KEY="tu_token"
  python3 scripts/test_apify_call.py "Abogados en Lima"

Esto imprimirá:
  - HTTP status
  - Algunos headers relevantes (X-Request-Id, Retry-After, Content-Type)
  - Body truncado a 2000 caracteres

Qué pegar en el chat para diagnóstico:
  - Línea "Status: <número>"
  - Líneas "Header <nombre>: <valor>" (si aparecen)
  - Sección "Body (truncated):" completa
  NO incluyas la URL con el token visible.
"""
from __future__ import annotations

import os
import sys

try:
    import httpx
except ImportError:
    print("Instala httpx: pip install httpx")
    sys.exit(1)


def trunc(s: str | None, n: int = 2000) -> str:
    """Trunca s a n caracteres añadiendo marca de truncamiento."""
    if s is None:
        return ""
    s = str(s)
    if len(s) <= n:
        return s
    return s[:n] + "...[truncated]"


def main() -> None:
    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        print("Error: export APIFY_API_KEY before running this script.")
        sys.exit(2)

    if len(sys.argv) < 2:
        print('Usage: python3 scripts/test_apify_call.py "Tu consulta"')
        sys.exit(2)

    query = sys.argv[1]
    actor_id = "compass~crawler-google-places"
    actor_timeout_s = int(os.environ.get("APIFY_ACTOR_TIMEOUT_S", "120"))
    http_timeout_s = int(os.environ.get("APIFY_HTTP_TIMEOUT_S", "180"))

    run_url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    # Token passed as query param — never printed
    params = {"token": api_key, "timeout": actor_timeout_s, "memory": 512}
    body = {
        "searchStringsArray": [query],
        "maxCrawledPlacesPerSearch": 20,
        "language": "es",
        "countryCode": "pe",
        "includeHistogram": False,
        "includeOpeningHours": False,
        "includePeopleAlsoSearch": False,
    }

    print(
        f"POST https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
        f" (token omitted) actor_timeout={actor_timeout_s}s http_timeout={http_timeout_s}s"
    )
    print(f"Query: {query!r}")

    try:
        with httpx.Client(timeout=http_timeout_s) as client:
            resp = client.post(run_url, params=params, json=body)
    except httpx.TimeoutException as e:
        print(f"Request timed out after {http_timeout_s}s: {e}")
        sys.exit(3)
    except Exception as e:
        print(f"Request failed: {e}")
        sys.exit(3)

    print(f"Status: {resp.status_code}")

    # Mostrar headers útiles (no dump completo — no exponer token)
    for h in ("X-Request-Id", "x-request-id", "Content-Type", "Retry-After"):
        if h.lower() in {k.lower() for k in resp.headers}:
            val = resp.headers.get(h) or resp.headers.get(h.lower())
            print(f"Header {h}: {val}")

    print("\nBody (truncated):")
    print(trunc(resp.text, 2000))


if __name__ == "__main__":
    main()
