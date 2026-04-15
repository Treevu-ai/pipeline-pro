"""
scripts/test_apify_call.py — Diagnóstico manual de la llamada a Apify.

Uso:
    APIFY_API_KEY=<tu_token> python scripts/test_apify_call.py [query] [limit]

Ejemplos:
    APIFY_API_KEY=apify_abc123 python scripts/test_apify_call.py "Abogados en Lima" 5
    APIFY_API_KEY=apify_abc123 python scripts/test_apify_call.py

El script replica exactamente la petición POST que realiza scraper._search_via_apify
y muestra el código HTTP, cabeceras relevantes y el cuerpo de la respuesta.
No escribe nada en la base de datos ni dispara el pipeline.

Notas de seguridad:
- Nunca guardes APIFY_API_KEY en este archivo ni en el repositorio.
- Pasa la clave únicamente como variable de entorno.
"""
from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Configuración por defecto — ajusta según necesites
# ---------------------------------------------------------------------------
DEFAULT_QUERY = "Restaurantes en Lima"
DEFAULT_LIMIT = 5
ACTOR_ID      = "compass~crawler-google-places"
ACTOR_TIMEOUT = int(os.environ.get("APIFY_ACTOR_TIMEOUT_S", "120"))
HTTP_TIMEOUT  = int(os.environ.get("APIFY_HTTP_TIMEOUT_S", "180"))
TRUNCATE_BODY = 4000   # caracteres máximos del body a mostrar en pantalla
# ---------------------------------------------------------------------------


def trunc(s: str, n: int) -> str:
    """Trunca texto para la salida por pantalla."""
    if not s:
        return ""
    return s if len(s) <= n else s[:n] + f"\n…[truncated at {n} chars, total={len(s)}]"


def run(query: str, limit: int, api_key: str) -> None:
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx no está instalado. Ejecuta: pip install httpx")
        sys.exit(1)

    run_url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
    params = {"token": api_key, "timeout": ACTOR_TIMEOUT, "memory": 512}
    body = {
        "searchStringsArray": [query],
        "maxCrawledPlacesPerSearch": min(limit, 20),
        "language": "es",
        "countryCode": "pe",
        "includeHistogram": False,
        "includeOpeningHours": False,
        "includePeopleAlsoSearch": False,
    }

    print(f"\n{'='*60}")
    print(f"Apify diagnostic call")
    print(f"  Actor   : {ACTOR_ID}")
    print(f"  Query   : {query!r}")
    print(f"  Limit   : {limit}")
    print(f"  Timeouts: actor={ACTOR_TIMEOUT}s  http={HTTP_TIMEOUT}s")
    print(f"{'='*60}\n")
    print("Sending POST request… (may take up to", HTTP_TIMEOUT, "seconds)\n")

    try:
        with httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT, connect=10)) as client:
            resp = client.post(run_url, params=params, json=body)
    except httpx.TimeoutException as e:
        print(f"TIMEOUT after {HTTP_TIMEOUT}s: {e}")
        sys.exit(2)
    except httpx.RequestError as e:
        print(f"REQUEST ERROR: {e}")
        sys.exit(3)

    print(f"HTTP Status : {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type', 'n/a')}")
    print(f"x-request-id: {resp.headers.get('x-request-id', 'n/a')}")
    print(f"x-apify-error-type: {resp.headers.get('x-apify-error-type', 'n/a')}\n")

    raw_body = resp.text
    print(f"--- Response body ({len(raw_body)} chars) ---")
    print(trunc(raw_body, TRUNCATE_BODY))

    # Try to parse as JSON and show summary
    try:
        data = resp.json()
        if isinstance(data, list):
            print(f"\n✓ Parsed as JSON list — {len(data)} item(s) returned.")
            if data:
                print("First item keys:", list(data[0].keys()) if data else [])
        else:
            print(f"\n✓ Parsed as JSON ({type(data).__name__}) — not a list.")
            if isinstance(data, dict) and "error" in data:
                print("Error message:", data.get("error", {}).get("message", data))
    except ValueError:
        print("\n✗ Response is NOT valid JSON.")

    if resp.status_code >= 400:
        print(f"\n✗ HTTP error {resp.status_code}. Check token/quota/actor in app.apify.com.")
        sys.exit(4)
    else:
        print("\n✓ Call succeeded.")


def main() -> None:
    api_key = os.environ.get("APIFY_API_KEY", "").strip()
    if not api_key:
        print(
            "ERROR: APIFY_API_KEY environment variable is not set.\n"
            "Usage: APIFY_API_KEY=<token> python scripts/test_apify_call.py [query] [limit]"
        )
        sys.exit(1)

    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    try:
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LIMIT
    except ValueError:
        print(f"ERROR: limit must be an integer, got {sys.argv[2]!r}")
        sys.exit(1)

    run(query, limit, api_key)


if __name__ == "__main__":
    main()
