#!/usr/bin/env python3
"""
scripts/test_apify_call.py — Diagnóstico manual de la llamada a Apify.

Replica exactamente la petición POST que hace _search_via_apify en scraper.py
y muestra el código HTTP y el cuerpo de la respuesta.

Uso:
    export APIFY_API_KEY="tu_token_aqui"
    python scripts/test_apify_call.py
    python scripts/test_apify_call.py --query "Abogados en Lima" --limit 5
    python scripts/test_apify_call.py --query "Restaurantes Miraflores" --limit 10

Parámetros de entorno opcionales:
    APIFY_ACTOR_TIMEOUT_S  (default: 120)
    APIFY_HTTP_TIMEOUT_S   (default: 180)

Salida:
    - Código HTTP de la respuesta
    - Cabeceras relevantes (Content-Type, X-Apify-*)
    - Primeros 3000 caracteres del cuerpo de la respuesta
    - Número de items si la respuesta es un array JSON válido
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prueba la llamada a Apify Google Maps Scraper."
    )
    parser.add_argument(
        "--query",
        default="Restaurantes en Lima",
        help="Consulta de búsqueda (default: 'Restaurantes en Lima')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Número máximo de resultados (default: 5)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        print("ERROR: La variable de entorno APIFY_API_KEY no está definida.", file=sys.stderr)
        print("  export APIFY_API_KEY='tu_token_aqui'", file=sys.stderr)
        sys.exit(1)

    actor_timeout_s = int(os.environ.get("APIFY_ACTOR_TIMEOUT_S", "120"))
    http_timeout_s  = int(os.environ.get("APIFY_HTTP_TIMEOUT_S", "180"))

    actor_id = "compass~crawler-google-places"
    run_url  = (
        f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
        f"?token={api_key}&timeout={actor_timeout_s}&memory=512"
    )
    body = {
        "searchStringsArray": [args.query],
        "maxCrawledPlacesPerSearch": min(args.limit, 20),
        "language": "es",
        "countryCode": "pe",
        "includeHistogram": False,
        "includeOpeningHours": False,
        "includePeopleAlsoSearch": False,
    }

    print(f"Consulta   : {args.query}")
    print(f"Límite     : {args.limit}")
    print(f"Actor      : {actor_id}")
    print(f"Actor TMO  : {actor_timeout_s}s")
    print(f"HTTP TMO   : {http_timeout_s}s")
    print("-" * 60)

    try:
        import httpx
    except ImportError:
        print("ERROR: httpx no está instalado. Ejecuta: pip install httpx", file=sys.stderr)
        sys.exit(1)

    try:
        with httpx.Client(timeout=httpx.Timeout(http_timeout_s, connect=10)) as client:
            resp = client.post(
                run_url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
    except httpx.TimeoutException as te:
        print(f"TIMEOUT después de {http_timeout_s}s: {te}", file=sys.stderr)
        sys.exit(2)
    except httpx.RequestError as re:
        print(f"ERROR DE RED: {re}", file=sys.stderr)
        sys.exit(3)

    print(f"HTTP Status: {resp.status_code}")
    print("Headers relevantes:")
    for key in ("content-type", "x-apify-pagination-total", "x-apify-error-message"):
        val = resp.headers.get(key)
        if val:
            print(f"  {key}: {val}")

    print("-" * 60)
    body_text = resp.text
    print(f"Body (primeros 3000 chars):\n{body_text[:3000]}")
    if len(body_text) > 3000:
        print(f"... [{len(body_text) - 3000} chars más, truncado]")

    if resp.status_code == 200:
        try:
            data = resp.json()
            if isinstance(data, list):
                print("-" * 60)
                print(f"Items devueltos: {len(data)}")
                if data:
                    print("Primer item (keys):", list(data[0].keys()))
            else:
                print("-" * 60)
                print(f"Respuesta no es lista: {type(data)}")
        except ValueError as e:
            print(f"JSON inválido: {e}", file=sys.stderr)
            sys.exit(4)
    else:
        print("-" * 60)
        print(f"Llamada fallida con HTTP {resp.status_code}.")
        if resp.status_code == 401:
            print("→ Token inválido o expirado. Verifica APIFY_API_KEY.")
        elif resp.status_code == 403:
            print("→ Sin permisos. Verifica el plan y permisos del token en app.apify.com.")
        elif resp.status_code == 429:
            print("→ Rate limit / cuota excedida. Espera o revisa tu plan.")
        elif resp.status_code >= 500:
            print("→ Error interno de Apify. Revisa el estado en status.apify.com.")
        sys.exit(5)


if __name__ == "__main__":
    main()
