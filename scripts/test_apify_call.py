#!/usr/bin/env python3
"""
Diagnóstico de la llamada a Apify Google Maps Scraper.

Uso:
    export APIFY_API_KEY="tu_token"
    python3 scripts/test_apify_call.py "Abogados en Lima"

Salida: status HTTP, headers relevantes y body truncado (sin exponer el token).
No incluir APIFY_API_KEY en el chat — pega solo la salida de este script.
"""

import json
import os
import sys

try:
    import httpx
except ImportError:
    print("ERROR: httpx no está instalado. Ejecuta: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ── Configuración ─────────────────────────────────────────────────────────────
_APIFY_ACTOR_TIMEOUT_S = 60    # Apify interno: abortar actor si tarda >60 s
_APIFY_HTTP_TIMEOUT_S  = 120   # httpx: límite duro del lado cliente
_BODY_PREVIEW_CHARS    = 2000  # caracteres máximos del body a imprimir
_ACTOR_ID              = "compass~crawler-google-places"
_BASE_URL              = "https://api.apify.com/v2/acts"


def run_diagnostic(query: str) -> None:
    api_key = os.environ.get("APIFY_API_KEY", "").strip()
    if not api_key:
        print("ERROR: La variable de entorno APIFY_API_KEY no está definida.", file=sys.stderr)
        print("Exporta el token antes de ejecutar:", file=sys.stderr)
        print("  export APIFY_API_KEY=\"tu_token\"", file=sys.stderr)
        sys.exit(1)

    run_url = f"{_BASE_URL}/{_ACTOR_ID}/run-sync-get-dataset-items"
    params  = {
        "token":   api_key,
        "timeout": _APIFY_ACTOR_TIMEOUT_S,
        "memory":  512,
    }
    body = {
        "searchStringsArray":          [query],
        "maxCrawledPlacesPerSearch":   20,
        "language":                    "es",
        "countryCode":                 "pe",
        "includeHistogram":            False,
        "includeOpeningHours":         False,
        "includePeopleAlsoSearch":     False,
    }

    # Mostrar la URL sin el token
    safe_url = f"{run_url}?timeout={_APIFY_ACTOR_TIMEOUT_S}&memory=512&token=<REDACTED>"
    print(f"[diag] URL   : {safe_url}")
    print(f"[diag] Query : {query}")
    print(f"[diag] Body  : {json.dumps(body, ensure_ascii=False)}")
    print()

    try:
        with httpx.Client(timeout=httpx.Timeout(_APIFY_HTTP_TIMEOUT_S, connect=10)) as client:
            resp = client.post(run_url, params=params, json=body)
    except httpx.TimeoutException as exc:
        print(f"[diag] TIMEOUT ({_APIFY_HTTP_TIMEOUT_S}s): {exc}", file=sys.stderr)
        sys.exit(2)
    except httpx.RequestError as exc:
        print(f"[diag] REQUEST ERROR: {exc}", file=sys.stderr)
        sys.exit(3)

    # ── Imprimir resultado ────────────────────────────────────────────────────
    print(f"[diag] Status : {resp.status_code} {resp.reason_phrase}")

    interesting_headers = [
        "content-type", "x-request-id", "retry-after",
        "x-ratelimit-limit", "x-ratelimit-remaining",
    ]
    for h in interesting_headers:
        val = resp.headers.get(h)
        if val:
            print(f"[diag] Header  {h}: {val}")

    print()
    raw_body = resp.text
    preview  = raw_body[:_BODY_PREVIEW_CHARS]
    truncated = len(raw_body) > _BODY_PREVIEW_CHARS
    print(f"[diag] Body ({len(raw_body)} chars{', truncado' if truncated else ''}):")
    print(preview)
    if truncated:
        print(f"... [{len(raw_body) - _BODY_PREVIEW_CHARS} chars más omitidos]")

    # ── Interpretación rápida ─────────────────────────────────────────────────
    print()
    status = resp.status_code
    if status == 200:
        try:
            items = resp.json()
            if isinstance(items, list):
                print(f"[diag] OK — se recibieron {len(items)} items.")
            else:
                print("[diag] OK — respuesta no es lista, revisa el body.")
        except Exception:
            print("[diag] OK — no se pudo parsear JSON; revisa el body.")
    elif status == 400:
        print("[diag] 400 Bad Request — revisa los parámetros del body.")
    elif status == 401:
        print("[diag] 401 Unauthorized — APIFY_API_KEY inválida o expirada.")
    elif status == 402:
        print("[diag] 402 Payment Required — créditos de Apify agotados.")
    elif status == 403:
        print("[diag] 403 Forbidden — sin permisos para este actor.")
    elif status == 429:
        retry = resp.headers.get("retry-after", "?")
        print(f"[diag] 429 Rate Limit — espera {retry}s antes de reintentar.")
    elif status >= 500:
        print(f"[diag] {status} Error del servidor Apify — intenta más tarde.")
    else:
        print(f"[diag] Estado inesperado: {status}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Uso: python3 {sys.argv[0]} \"<query>\"")
        print("Ejemplo: python3 scripts/test_apify_call.py \"Abogados en Lima\"")
        sys.exit(1)
    run_diagnostic(" ".join(sys.argv[1:]))
