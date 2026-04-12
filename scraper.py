"""
scraper.py — Descubre y enriquece leads MIPYME desde fuentes públicas.

Fuentes:
  1. Google Maps  — nombre, teléfono, sitio web, dirección, categoría, reseñas
  2. Sitio web    — extrae email desde mailto:, texto y patrones regex
  3. SUNAT API    — enriquece con razón social oficial, estado, actividad (solo Perú)

Uso:
    python scraper.py "Retail Lima" --limit 20 --output output/leads_raw.csv
    python scraper.py "Construcción Trujillo" --limit 30 --country pe --enrich-sunat
    python scraper.py "Logística Bogotá" --limit 15 --headful
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import constants as const
import config as cfg
import exceptions as exc
import models
import utils

log = logging.getLogger("scraper")


# ─── Mapeo de categorías de Google Maps → ICP ────────────────────────────────

COUNTRY_CODES = const.CountryCodes.CODE_TO_NAME


def map_category(raw_category: str) -> str:
    """
    Intenta mapear la categoría de Google Maps a nuestro ICP.

    Args:
        raw_category: Categoría original de Google Maps.

    Returns:
        Categoría mapeada o la original si no hay match.
    """
    norm = utils.normalize(raw_category)
    for key, value in const.CATEGORY_MAP.items():
        if key in norm:
            return value
    return raw_category.strip() or "Otro"


# ─── Extracción de contacto desde sitio web ───────────────────────────────────

@utils.rate_limit(**cfg.RATE_LIMITING["website_scraping"])
def fetch_html(url: str, timeout: int = 10) -> str:
    """
    Descarga HTML de una URL.

    Args:
        url: URL a descargar.
        timeout: Timeout en segundos.

    Returns:
        HTML descargado o string vacío si falla.

    Raises:
        WebsiteScrapingError: Si hay error al descargar el HTML.
    """
    try:
        req = utils.urllib.request.Request(
            url,
            headers=const.HTTP_HEADERS,
        )
        with utils.urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset("utf-8") or "utf-8"
            return raw.decode(charset, errors="replace")
    except Exception as e:
        log.debug("Error descargando %s: %s", url, e)
        raise exc.WebsiteScrapingError(f"No se pudo descargar {url}", url=url) from e


def extract_emails_from_html(html: str) -> list[str]:
    """
    Extrae emails únicos desde HTML.

    Filtra dominios genéricos/irrelevantes.

    Args:
        html: HTML del cual extraer emails.

    Returns:
        Lista de emails únicos encontrados.
    """
    # Prioridad: mailto: links
    mailto = utils.re.findall(const.RegexPatterns.MAILTO, html, utils.re.IGNORECASE)
    # Fallback: patrón regex en texto plano
    plain = utils.re.sub(r"<[^>]+>", " ", html)
    pattern_hits = utils.re.findall(const.RegexPatterns.EMAIL, plain, utils.re.IGNORECASE)

    all_emails: list[str] = []
    for e in mailto + pattern_hits:
        e = e.strip().lower().rstrip(".,;)")
        if "@" not in e:
            continue
        domain = e.split("@")[-1]
        if domain in cfg.ENRICHMENT["blacklist_domains"]:
            continue
        all_emails.append(e)

    # Dedup preservando orden
    seen: set[str] = set()
    result: list[str] = []
    for e in all_emails:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


def guess_emails(domain: str) -> list[str]:
    """
    Genera emails probables para un dominio (heurística).

    Args:
        domain: Dominio del email.

    Returns:
        Lista de emails probables.
    """
    return [f"{p}@{domain}" for p in cfg.ENRICHMENT["email_prefixes"]]


def enrich_from_website(url: str) -> dict[str, Any]:
    """
    Visita el sitio web y extrae email y teléfonos adicionales.

    Args:
        url: URL del sitio web.

    Returns:
        Diccionario con datos enriquecidos.
    """
    if not url:
        return {}

    # Normalizar URL
    url = utils.normalize_url(url)

    try:
        html = fetch_html(url)
    except exc.WebsiteScrapingError:
        return {}

    if not html:
        return {}

    emails = extract_emails_from_html(html)
    phones = utils.extract_phones_from_text(html)
    domain = utils.extract_domain(url)

    return {
        "email": emails[0] if emails else "",
        "email_alternativo": emails[1] if len(emails) > 1 else "",
        "telefono_web": phones[0] if phones else "",
        "dominio_web": domain,
        "email_guess": guess_emails(domain)[0] if not emails else "",
    }


# ─── Enriquecimiento SUNAT (solo Perú) ───────────────────────────────────────

@utils.rate_limit(**cfg.RATE_LIMITING["sunat_api"])
def enrich_sunat(ruc: str) -> dict[str, Any]:
    """
    Consulta la API pública de SUNAT para obtener datos oficiales de la empresa.

    Solo aplica a RUCs peruanos de 11 dígitos.

    Args:
        ruc: RUC a consultar.

    Returns:
        Diccionario con datos de SUNAT o vacío si falla.

    Raises:
        SunatError: Si hay error al consultar SUNAT.
    """
    ruc = utils.re.sub(r"\D", "", str(ruc))
    if len(ruc) != 11:
        return {}

    _token = os.environ.get("APIS_PE_TOKEN", "")
    _headers = {
        "Authorization": f"Bearer {_token}",
        "User-Agent": "AgentePyme/1.0",
        "Referer": "https://apis.net.pe",
    }
    try:
        url = f"https://api.apis.net.pe/v1/ruc?numero={ruc}"
        req = utils.urllib.request.Request(url, headers=_headers)
        with utils.urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        distrito  = data.get("distrito", "")
        provincia = data.get("provincia", "")
        dpto      = data.get("departamento", "")
        direccion = " ".join(filter(None, [
            data.get("viaTipo", ""), data.get("viaNombre", ""),
            data.get("numero", ""), data.get("interior", ""),
            distrito, provincia,
        ])).strip()
        return {
            "razon_social_oficial": data.get("nombre", ""),
            "estado_sunat":         data.get("estado", ""),
            "condicion_sunat":      data.get("condicion", ""),
            "direccion_fiscal":     direccion or data.get("direccion", ""),
            "ubigeo":               data.get("ubigeo", ""),
            "actividad_economica":  "",   # apis.net.pe v1 no lo incluye
            "ciiu":                 "",
            "regimen_tributario":   "",
            "fecha_inscripcion":    "",
            "tipo_contribuyente":   data.get("tipoDocumento", ""),
            "capacidad_pago":       _capacidad_pago("", ""),
        }
    except Exception as e:
        log.debug("SUNAT lookup falló para RUC %s: %s", ruc, e)
        raise exc.SunatError(f"No se pudo consultar RUC {ruc}", ruc=ruc) from e


def _capacidad_pago(tipo_contribuyente: str, regimen: str) -> str:
    """Traduce régimen SUNAT a capacidad de pago legible para el equipo comercial."""
    t = tipo_contribuyente.upper()
    r = regimen.upper()
    # Régimen General → empresas medianas/grandes, mayor capacidad de pago
    if "GENERAL" in r or "TERCERA CATEGORIA" in t:
        return "Alta"
    # Régimen MYPE Tributario → MYPE consolidada
    if "MYPE" in r or "MYPE" in t:
        return "Media"
    # Régimen Especial de Renta → microempresa activa
    if "ESPECIAL" in r or "RER" in r:
        return "Básica"
    # RUS → microempresa mínima
    if "RUS" in r or "SIMPLIFICADO" in r or "UNICO" in r:
        return "Básica"
    return "Sin datos"


# ─── Google Places API (New) ─────────────────────────────────────────────────

_RUC_PATTERN = utils.re.compile(r"\b20\d{9}\b")


async def _extract_ruc_from_website(url: str) -> str:
    """Descarga el website del lead y extrae el RUC peruano si aparece."""
    if not url:
        return ""
    try:
        import httpx
        url = utils.normalize_url(url)
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": const.HTTP_HEADERS["User-Agent"]})
            html = resp.text
        matches = _RUC_PATTERN.findall(html)
        if matches:
            from collections import Counter
            return Counter(matches).most_common(1)[0][0]
    except Exception:
        pass
    return ""


async def _search_via_apify(query: str, limit: int) -> list[dict[str, Any]]:
    """
    Busca negocios usando Apify Google Maps Scraper.
    Requiere APIFY_API_KEY en el entorno.
    Retorna lista vacía si no hay key o la llamada falla.
    """
    api_key = cfg.APIFY_API_KEY
    if not api_key:
        return []

    try:
        import httpx, time
        _APIFY_ACTOR_TIMEOUT_S  = 60    # Apify interno: abortar actor si tarda >60s
        _APIFY_HTTP_TIMEOUT_S   = 120   # httpx: límite duro del lado cliente
        actor_id = "compass~crawler-google-places"
        run_url  = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
        params   = {"token": api_key, "timeout": _APIFY_ACTOR_TIMEOUT_S, "memory": 512}
        body = {
            "searchStringsArray": [query],
            "maxCrawledPlacesPerSearch": min(limit, 20),
            "language": "es",
            "countryCode": "pe",
            "includeHistogram": False,
            "includeOpeningHours": False,
            "includePeopleAlsoSearch": False,
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_APIFY_HTTP_TIMEOUT_S, connect=10)
        ) as client:
            try:
                resp = await client.post(run_url, params=params, json=body)
            except httpx.TimeoutException:
                log.error(
                    "Apify timeout (%ds) para '%s' — intenta reducir el límite de leads",
                    _APIFY_HTTP_TIMEOUT_S, query,
                )
                return []
            resp.raise_for_status()
            items = resp.json()

        leads: list[dict[str, Any]] = []
        for place in items:
            leads.append({
                const.ColumnNames.EMPRESA:            place.get("title", ""),
                const.ColumnNames.DIRECCION:          place.get("address", ""),
                const.ColumnNames.TELEFONO:           place.get("phone", ""),
                const.ColumnNames.RATING:             str(place.get("totalScore", "")),
                const.ColumnNames.NUM_RESENAS:        str(place.get("reviewsCount", "")),
                const.ColumnNames.SITIO_WEB:          place.get("website", ""),
                const.ColumnNames.CATEGORIA_ORIGINAL: place.get("categoryName", ""),
                const.ColumnNames.INDUSTRIA:          map_category(place.get("categoryName", "")),
                const.ColumnNames.FUENTE:             "apify_google_maps",
                "maps_url":                           place.get("url", ""),
            })
        log.info("Apify: %d resultados para '%s'", len(leads), query)
        return leads
    except Exception as e:
        log.warning("Apify falló para '%s': %s", query, e)
        return []


async def _search_via_serpapi(query: str, limit: int) -> list[dict[str, Any]]:
    """
    Busca negocios en Google Maps usando SerpApi (engine=google_maps).
    Requiere SERPAPI_API_KEY en el entorno.
    SDK: pip install google-search-results
    Precio: ~$0.015/búsqueda pay-as-you-go (hasta 20 resultados por página).
    Docs: https://serpapi.com/google-maps-api
    """
    api_key = cfg.SERPAPI_API_KEY
    if not api_key:
        return []

    try:
        def _call() -> list[dict]:
            from serpapi import GoogleSearch
            leads_raw: list[dict] = []
            start = 0
            # SerpApi devuelve 20 resultados por página; paginamos hasta cubrir el límite
            while len(leads_raw) < limit:
                params = {
                    "engine":  "google_maps",
                    "q":       query,
                    "hl":      "es",
                    "start":   start,
                    "api_key": api_key,
                }
                results = GoogleSearch(params).get_dict()
                batch   = results.get("local_results") or []
                if not batch:
                    break
                leads_raw.extend(batch)
                if len(batch) < 20:   # última página
                    break
                start += 20
            return leads_raw[:limit]

        raw = await asyncio.to_thread(_call)

        leads: list[dict[str, Any]] = []
        for place in raw:
            leads.append({
                const.ColumnNames.EMPRESA:            place.get("title", ""),
                const.ColumnNames.DIRECCION:          place.get("address", ""),
                const.ColumnNames.TELEFONO:           place.get("phone", ""),
                const.ColumnNames.RATING:             str(place.get("rating", "")),
                const.ColumnNames.NUM_RESENAS:        str(place.get("reviews", "")),
                const.ColumnNames.SITIO_WEB:          place.get("website", ""),
                const.ColumnNames.CATEGORIA_ORIGINAL: place.get("type", ""),
                const.ColumnNames.INDUSTRIA:          map_category(place.get("type", "")),
                const.ColumnNames.FUENTE:             "serpapi",
            })

        log.info("SerpApi: %d resultados para '%s'", len(leads), query)
        return leads

    except Exception as e:
        log.warning("SerpApi falló para '%s': %s", query, e)
        return []


async def _search_via_places_api(query: str, limit: int) -> list[dict[str, Any]]:
    """
    Busca negocios usando Google Places API (New).
    Requiere GOOGLE_PLACES_API_KEY en el entorno.
    Retorna lista vacía si no hay key o la llamada falla.
    """
    api_key = cfg.GOOGLE_PLACES_API_KEY
    if not api_key:
        return []

    try:
        import httpx
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.displayName,places.formattedAddress,"
                "places.nationalPhoneNumber,places.rating,"
                "places.userRatingCount,places.websiteUri,"
                "places.primaryTypeDisplayName"
            ),
        }
        body = {
            "textQuery": query,
            "languageCode": "es",
            "maxResultCount": min(limit, 20),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        leads: list[dict[str, Any]] = []
        for place in data.get("places", []):
            leads.append({
                const.ColumnNames.EMPRESA:            place.get("displayName", {}).get("text", ""),
                const.ColumnNames.DIRECCION:          place.get("formattedAddress", ""),
                const.ColumnNames.TELEFONO:           place.get("nationalPhoneNumber", ""),
                const.ColumnNames.RATING:             str(place.get("rating", "")),
                const.ColumnNames.NUM_RESENAS:        str(place.get("userRatingCount", "")),
                const.ColumnNames.SITIO_WEB:          place.get("websiteUri", ""),
                const.ColumnNames.CATEGORIA_ORIGINAL: (
                    place.get("primaryTypeDisplayName", {}).get("text", "")
                ),
                const.ColumnNames.INDUSTRIA:          map_category(
                    place.get("primaryTypeDisplayName", {}).get("text", "")
                ),
                const.ColumnNames.FUENTE:             "google_places_api",
            })
        log.info("Places API: %d resultados para '%s'", len(leads), query)
        return leads
    except Exception as e:
        log.warning("Places API falló para '%s': %s — usando fallback Playwright", query, e)
        return []


# ─── Scraper de Google Maps (Playwright async) ────────────────────────────────

async def _scrape_maps_async(query: str, limit: int, headful: bool = False) -> list[dict[str, Any]]:
    """
    Scrapea Google Maps de forma asíncrona.

    Args:
        query: Query de búsqueda.
        limit: Límite de resultados.
        headful: Si abrir el navegador visible.

    Returns:
        Lista de leads encontrados.

    Raises:
        GoogleMapsError: Si hay error al scrapear Google Maps.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise exc.PlaywrightNotAvailableError(
            "Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium"
        )

    leads: list[dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=not headful,
                slow_mo=50 if headful else 0
            )
            ctx = await browser.new_context(
                locale="es-419",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = await ctx.new_page()

            maps_url = f"https://www.google.com/maps/search/{utils.urllib.parse.quote(query)}/"
            log.info("Abriendo Google Maps: %s", maps_url)
            await page.goto(maps_url, wait_until="domcontentloaded", timeout=cfg.SCRAPING["google_maps_timeout"])
            await page.wait_for_timeout(2500)

            # Aceptar cookies si aparece el modal
            try:
                await page.click('button:has-text("Aceptar todo")', timeout=cfg.SCRAPING["cookie_accept_timeout"])
            except Exception:
                pass

            # Scroll del panel de resultados para cargar más
            feed_sel = '[role="feed"]'
            try:
                await page.wait_for_selector(feed_sel, timeout=10_000)
            except Exception:
                log.warning("No se encontró panel de resultados en Google Maps. Puede que haya cambiado la estructura.")
                await browser.close()
                raise exc.GoogleMapsError("No se encontró panel de resultados en Google Maps")

            log.info("Cargando resultados (objetivo: %d)...", limit)
            for _ in range(20):
                count = await page.locator('[role="article"]').count()
                if count >= limit:
                    break
                await page.locator(feed_sel).evaluate("el => el.scrollBy(0, 800)")
                delay = random.randint(
                    cfg.SCRAPING["scroll_delay_min"],
                    cfg.SCRAPING["scroll_delay_max"]
                )
                await page.wait_for_timeout(delay)

            articles = await page.locator('[role="article"]').all()
            log.info("Resultados encontrados: %d (procesando %d)", len(articles), min(len(articles), limit))

            for i, article in enumerate(articles[:limit]):
                empresa: dict[str, Any] = {}
                try:
                    # Nombre desde aria-label ANTES de hacer click
                    nombre_pre = (await article.get_attribute("aria-label") or "").strip()

                    await article.click()
                    delay = random.randint(
                        cfg.SCRAPING["article_click_delay_min"],
                        cfg.SCRAPING["article_click_delay_max"]
                    )
                    await page.wait_for_timeout(delay)

                    # URL de Google Maps para este negocio
                    empresa[const.ColumnNames.MAPS_URL] = page.url

                    # Nombre: panel de detalle (selectores específicos) o fallback a aria-label
                    try:
                        nombre_panel = (
                            await page.locator("h1.DUwDvf, h1.fontHeadlineLarge").first.text_content(timeout=3000) or ""
                        ).strip()
                        empresa[const.ColumnNames.EMPRESA] = (
                            nombre_panel if nombre_panel and nombre_panel.lower() not in ("resultados", "")
                            else nombre_pre
                        )
                    except Exception:
                        empresa[const.ColumnNames.EMPRESA] = nombre_pre

                    if not empresa[const.ColumnNames.EMPRESA]:
                        continue

                    # Categoría → industria
                    try:
                        cat_el = page.locator('button[jsaction*="category"]').first
                        cat_text = await cat_el.text_content(timeout=2000) or ""
                        empresa[const.ColumnNames.INDUSTRIA] = map_category(cat_text)
                        empresa[const.ColumnNames.CATEGORIA_ORIGINAL] = cat_text.strip()
                    except Exception:
                        empresa[const.ColumnNames.INDUSTRIA] = "Otro"
                        empresa[const.ColumnNames.CATEGORIA_ORIGINAL] = ""

                    # Dirección
                    try:
                        addr_btn = page.locator('[data-item-id="address"]').first
                        empresa[const.ColumnNames.DIRECCION] = (
                            await addr_btn.text_content(timeout=2000) or ""
                        ).strip()
                    except Exception:
                        empresa[const.ColumnNames.DIRECCION] = ""

                    # Teléfono
                    try:
                        tel_btn = page.locator('[data-item-id^="phone:tel"]').first
                        tel_raw = await tel_btn.get_attribute("data-item-id", timeout=2000) or ""
                        empresa[const.ColumnNames.TELEFONO] = tel_raw.replace("phone:tel:", "").strip()
                    except Exception:
                        empresa[const.ColumnNames.TELEFONO] = ""

                    # Sitio web
                    try:
                        web_btn = page.locator('[data-item-id^="authority"]').first
                        empresa[const.ColumnNames.SITIO_WEB] = (
                            await web_btn.text_content(timeout=2000) or ""
                        ).strip()
                    except Exception:
                        empresa[const.ColumnNames.SITIO_WEB] = ""

                    # Rating y reseñas (señal de actividad del negocio)
                    try:
                        # Intentar múltiples selectores para el bloque de rating
                        rating_text = ""
                        for sel in [
                            'div.F7nice',                       # contenedor rating + reseñas
                            'span[aria-label*="estrellas"]',
                            'span[aria-label*="stars"]',
                            '[jsaction*="rating"]',
                        ]:
                            try:
                                rating_text = await page.locator(sel).first.text_content(timeout=1500) or ""
                                if rating_text:
                                    break
                            except Exception:
                                continue

                        # Intentar también aria-label del elemento de rating para reseñas
                        try:
                            aria_rating = await page.locator('span[aria-label*="reseña"], span[aria-label*="review"]').first.get_attribute("aria-label", timeout=1500) or ""
                            if aria_rating:
                                rating_text = (rating_text + " " + aria_rating).strip()
                        except Exception:
                            pass

                        m = utils.re.search(r"(\d+[.,]\d+)", rating_text)
                        empresa[const.ColumnNames.RATING] = m.group(1).replace(",", ".") if m else ""
                        m2 = utils.re.search(r"([\d.,]+)\s*reseña", rating_text, utils.re.IGNORECASE)
                        if not m2:
                            m2 = utils.re.search(r"([\d.,]+)\s*review", rating_text, utils.re.IGNORECASE)
                        empresa[const.ColumnNames.NUM_RESENAS] = m2.group(1).replace(".", "").replace(",", "") if m2 else ""
                    except Exception:
                        empresa[const.ColumnNames.RATING] = ""
                        empresa[const.ColumnNames.NUM_RESENAS] = ""

                    empresa[const.ColumnNames.EMAIL] = ""
                    empresa[const.ColumnNames.FUENTE] = "Google Maps"
                    empresa[const.ColumnNames.SCRAPED_AT] = datetime.now().strftime("%Y-%m-%d %H:%M")

                    leads.append(empresa)
                    log.info("[%d/%d] %s | %s | tel: %s | web: %s",
                             i + 1, min(len(articles), limit),
                             empresa.get(const.ColumnNames.EMPRESA, "?"),
                             empresa.get(const.ColumnNames.INDUSTRIA, "?"),
                             empresa.get(const.ColumnNames.TELEFONO, "-"),
                             empresa.get(const.ColumnNames.SITIO_WEB, "-"))

                except Exception as e:
                    log.warning("[%d] Error procesando artículo: %s", i + 1, e)
                    continue

            await browser.close()
    except Exception as e:
        if not isinstance(e, exc.GoogleMapsError):
            raise exc.GoogleMapsError(f"Error al scrapear Google Maps: {e}") from e
        raise

    return leads


def scrape_google_maps(query: str, limit: int, headful: bool = False) -> list[dict[str, Any]]:
    """
    Busca negocios en Google.

    Usa Google Places API (New) si GOOGLE_PLACES_API_KEY está configurada;
    si no, hace fallback a scraping Playwright de Google Maps.

    Args:
        query: Query de búsqueda.
        limit: Límite de resultados.
        headful: Si abrir el navegador visible (solo aplica al fallback Playwright).

    Returns:
        Lista de leads encontrados.
    """
    async def _run() -> list[dict[str, Any]]:
        last_error = None
        # 1. Apify (prioridad)
        if cfg.APIFY_API_KEY:
            log.info("Usando Apify Google Maps para: %s", query)
            try:
                leads = await _search_via_apify(query, limit)
                if leads:
                    return leads
                log.info("Apify sin resultados — fallback SerpApi")
            except Exception as e:
                last_error = e
                log.warning("Apify error: %s — fallback SerpApi", e)
        # 2. SerpApi (fallback principal)
        if cfg.SERPAPI_API_KEY:
            log.info("Usando SerpApi para: %s", query)
            try:
                leads = await _search_via_serpapi(query, limit)
                if leads:
                    return leads
                log.info("SerpApi sin resultados — fallback Places API")
            except Exception as e:
                last_error = e
                log.warning("SerpApi error: %s — fallback Places API", e)
        # 3. Google Places API (fallback secundario)
        if cfg.GOOGLE_PLACES_API_KEY:
            log.info("Usando Google Places API para: %s", query)
            try:
                leads = await _search_via_places_api(query, limit)
                if leads:
                    return leads
                log.info("Places API sin resultados")
            except Exception as e:
                last_error = e
                log.warning("Places API error: %s", e)
        # 4. Playwright — solo si está disponible
        try:
            return await _scrape_maps_async(query, limit, headful)
        except Exception as e:
            log.warning("Playwright no disponible: %s", e)
            if last_error:
                raise exc.GoogleMapsError(f"Todas las fuentes fallaron. Último error: {last_error}") from last_error
            raise exc.GoogleMapsError("No se encontraron resultados y Playwright no está disponible") from e

    return asyncio.run(_run())


# ─── Enriquecimiento de leads ─────────────────────────────────────────────────

def enrich_leads(leads: list[dict[str, Any]], use_sunat: bool = False, delay: float = 1.0) -> list[dict[str, Any]]:
    """
    Visita sitios web para obtener emails y opcionalmente consulta SUNAT.

    Args:
        leads: Lista de leads a enriquecer.
        use_sunat: Si consultar SUNAT.
        delay: Pausa entre visitas en segundos.

    Returns:
        Lista de leads enriquecidos.
    """
    enriched = []
    total = len(leads)

    for i, lead in enumerate(leads):
        log.info("[%d/%d] Enriqueciendo: %s", i + 1, total, lead.get(const.ColumnNames.EMPRESA, "?"))

        # Extracción desde sitio web
        web_data = enrich_from_website(lead.get(const.ColumnNames.SITIO_WEB, ""))
        if web_data:
            lead = {**lead, **{k: v for k, v in web_data.items() if not lead.get(k)}}

        # SUNAT (opcional, solo Perú)
        if use_sunat and lead.get(const.ColumnNames.RUC):
            try:
                sunat_data = enrich_sunat(lead[const.ColumnNames.RUC])
                if sunat_data:
                    lead = {**lead, **sunat_data}
                    log.info("  SUNAT OK: %s | %s", sunat_data.get("estado_sunat"), sunat_data.get("actividad_economica"))
            except exc.SunatError as e:
                log.debug("Error SUNAT: %s", e)

        enriched.append(lead)
        time.sleep(delay + random.uniform(0, 0.5))

    return enriched


# ─── Guardado ─────────────────────────────────────────────────────────────────

def save_leads(leads: list[dict[str, Any]], path: Path) -> None:
    """
    Guarda leads en un archivo CSV.

    Args:
        leads: Lista de leads a guardar.
        path: Ruta del archivo CSV.

    Raises:
        CSVError: Si hay error al guardar el CSV.
    """
    if not leads:
        log.warning("Sin leads para guardar.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fieldnames = list(leads[0].keys())
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(leads)
        log.info("CSV guardado: %s (%d leads)", path, len(leads))
    except Exception as e:
        raise exc.CSVError(f"No se pudo guardar CSV en {path}", file_path=str(path)) from e


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parsea argumentos de línea de comandos."""
    p = argparse.ArgumentParser(
        description="Scraper de leads MIPYME desde Google Maps + sitios web.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scraper.py "Retail Lima" --limit 20
  python scraper.py "Construcción Trujillo Peru" --limit 40 --enrich-sunat
  python scraper.py "Logística Bogotá" --limit 15 --headful
  python scraper.py "Ferretería Arequipa" --limit 25 --no-enrich
        """,
    )
    p.add_argument("query", help='Búsqueda de Google Maps, ej: "Retail Lima Peru"')
    p.add_argument("--limit", type=int, default=20, help="Máx. negocios a scrapear (default: 20)")
    p.add_argument("--output", default=None, help="Archivo CSV de salida (default: output/leads_raw_TIMESTAMP.csv)")
    p.add_argument("--headful", action="store_true", help="Abrir el navegador visible (útil para depurar)")
    p.add_argument("--no-enrich", action="store_true", help="Omitir visita a sitios web (más rápido)")
    p.add_argument("--enrich-sunat", action="store_true", help="Consultar SUNAT por RUC (solo leads de Perú)")
    p.add_argument("--delay", type=float, default=1.2, help="Pausa entre visitas web en segundos (default: 1.2)")
    return p.parse_args()


def main() -> None:
    """Función principal."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.output) if args.output else Path(f"output/leads_raw_{timestamp}.csv")

    # 1. Scraping
    log.info("Iniciando scraping: '%s' | limite: %d", args.query, args.limit)
    try:
        leads = scrape_google_maps(args.query, args.limit, headful=args.headful)
    except exc.GoogleMapsError as e:
        log.error("Error en scraping: %s", e)
        sys.exit(exc.ExitCodes.NETWORK_ERROR)

    if not leads:
        log.error("No se obtuvieron leads. Verifica la query o la conexión.")
        sys.exit(exc.ExitCodes.ERROR)

    log.info("Leads encontrados: %d", len(leads))

    # 2. Enriquecimiento desde sitios web
    if not args.no_enrich:
        log.info("Enriqueciendo con datos de sitios web...")
        try:
            leads = enrich_leads(leads, use_sunat=args.enrich_sunat, delay=args.delay)
        except Exception as e:
            log.error("Error en enriquecimiento: %s", e)
            sys.exit(exc.ExitCodes.ERROR)

        emails_found = sum(1 for l in leads if l.get(const.ColumnNames.EMAIL))
        log.info("Emails encontrados: %d/%d", emails_found, len(leads))
    else:
        log.info("Enriquecimiento omitido (--no-enrich)")

    # 3. Guardar
    try:
        save_leads(leads, out_path)
    except exc.CSVError as e:
        log.error("Error al guardar CSV: %s", e)
        sys.exit(exc.ExitCodes.ERROR)

    # Resumen
    with_email = sum(1 for l in leads if l.get(const.ColumnNames.EMAIL))
    with_phone = sum(1 for l in leads if l.get(const.ColumnNames.TELEFONO))
    print(f"\n{'=' * 48}")
    print(f"  SCRAPING COMPLETADO")
    print(f"{'=' * 48}")
    print(f"  Query      : {args.query}")
    print(f"  Leads      : {len(leads)}")
    print(f"  Con email  : {with_email}")
    print(f"  Con telefono: {with_phone}")
    print(f"  Guardado en: {out_path}")
    print(f"{'=' * 48}")
    print(f"\nSiguiente paso:")
    print(f"  python sdr_agent.py {out_path} output/leads_calificados.csv --report\n")


if __name__ == "__main__":
    main()