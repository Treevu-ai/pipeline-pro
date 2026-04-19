"""
contact_enricher.py — Enriquece contactos de leads con emails personales, redes sociales y teléfonos adicionales.

Fuentes:
  1. Google Search — encuentra sitio web de la empresa
  2. Sitio web — extrae emails adicionales, teléfonos, redes sociales
  3. Generación de emails personales — basados en nombre de contacto

Uso:
    python contact_enricher.py output/leads_calificados.csv output/leads_enriched.csv
    python contact_enricher.py output/leads_calificados.csv output/leads_enriched.csv --headful
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import config as cfg
import logging_config
import constants as const
import exceptions as exc
import utils
from scraper import fetch_html

log = logging.getLogger("contact_enricher")


# ─── Extracción de emails ───────────────────────────────────────────────────────

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


# ─── Extracción de teléfonos ────────────────────────────────────────────────────

def extract_phones_from_html(html: str) -> list[str]:
    """
    Extrae números de teléfono desde HTML.

    Args:
        html: HTML del cual extraer teléfonos.

    Returns:
        Lista de teléfonos únicos encontrados.
    """
    phones = []
    for pattern in cfg.ENRICHMENT["phone_patterns"]:
        matches = utils.re.findall(pattern, html, utils.re.IGNORECASE)
        for phone in matches:
            if isinstance(phone, tuple):
                phone = phone[0] if phone else ""
            # Limpiar el número
            phone = utils.re.sub(r"[^\d+]", "", phone)
            if len(phone) >= cfg.ENRICHMENT["min_phone_digits"]:
                phones.append(phone)

    # Dedup
    seen = set()
    result = []
    for p in phones:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


# ─── Extracción de redes sociales ───────────────────────────────────────────────

def extract_social_from_html(html: str) -> dict[str, str]:
    """
    Extrae URLs de redes sociales desde HTML.

    Args:
        html: HTML del cual extraer redes sociales.

    Returns:
        Diccionario con URLs de redes sociales.
    """
    social = {k: "" for k in cfg.ENRICHMENT["social_patterns"].keys()}

    for platform, patterns in cfg.ENRICHMENT["social_patterns"].items():
        for pattern in patterns:
            # Buscar el match completo (sin grupos de captura)
            full_match = utils.re.search(pattern, html, utils.re.IGNORECASE)
            if full_match:
                social[platform] = full_match.group(0)
                break

    return social


# ─── Búsqueda de sitio web en Google (Playwright) ───────────────────────────────

async def _find_website_async(empresa: str, ciudad: str = "", headful: bool = False) -> str:
    """
    Busca el sitio web de una empresa en Google de forma asíncrona.

    Args:
        empresa: Nombre de la empresa.
        ciudad: Ciudad (opcional).
        headful: Si abrir el navegador visible.

    Returns:
        URL del sitio web o string vacío si no se encuentra.

    Raises:
        GoogleSearchError: Si hay error en la búsqueda.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise exc.PlaywrightNotAvailableError(
            "Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium"
        )

    query = f'"{empresa}" sitio web oficial'
    if ciudad:
        query += f' {ciudad}'

    log.info("Buscando sitio web: %s", query)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=not headful, slow_mo=50 if headful else 0)
            ctx = await browser.new_context(
                locale="es-419",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()

            google_url = f"https://www.google.com/search?q={utils.urllib.parse.quote(query)}"
            log.debug("Navegando a: %s", google_url)
            await page.goto(google_url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2000)

            # Aceptar cookies si aparece
            try:
                await page.click('button:has-text("Aceptar todo")', timeout=2000)
                await page.wait_for_timeout(500)
            except Exception:
                pass

            # Buscar el primer resultado que sea un sitio web
            try:
                # Intentar múltiples selectores para resultados
                selectors = [
                    'div.g a[href^="http"]',
                    'div[data-hveid] a[href^="http"]',
                    'a[href^="http"]',
                ]

                for selector in selectors:
                    results = await page.locator(selector).all()
                    log.debug("Selector %s: %d resultados", selector, len(results))

                    for result in results[:10]:  # Primeros 10 resultados
                        href = await result.get_attribute("href")
                        if not href:
                            continue

                        # Limpiar URL de Google (quitar parámetros de redirección)
                        if "google.com" in href or "url?q=" in href:
                            continue

                        # Filtrar redes sociales y otros dominios no deseados
                        skip_domains = ["facebook.com", "linkedin.com", "youtube.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "google.com", "googleapis.com"]
                        if any(x in href.lower() for x in skip_domains):
                            continue

                        # Extraer el dominio
                        parsed = utils.urllib.parse.urlparse(href)
                        domain = parsed.netloc
                        if domain and "example.com" not in domain and len(domain) > cfg.ENRICHMENT["min_domain_length"]:
                            log.info("Sitio web encontrado: %s", domain)
                            await browser.close()
                            return f"https://{domain}"
            except Exception as e:
                log.debug("Error extrayendo resultados: %s", e)

            await browser.close()
    except Exception as e:
        if not isinstance(e, exc.PlaywrightNotAvailableError):
            raise exc.GoogleSearchError(f"Error en búsqueda de sitio web: {e}", query=query) from e
        raise

    return ""


def find_website(empresa: str, ciudad: str = "", headful: bool = False) -> str:
    """
    Busca el sitio web de una empresa en Google (wrapper síncrono).

    Args:
        empresa: Nombre de la empresa.
        ciudad: Ciudad (opcional).
        headful: Si abrir el navegador visible.

    Returns:
        URL del sitio web o string vacío si no se encuentra.
    """
    return asyncio.run(_find_website_async(empresa, ciudad, headful))


async def _find_websites_batch_async(
    queries: list[tuple[str, str]], headful: bool = False
) -> list[str]:
    """
    Busca sitios web de varias empresas reutilizando un único browser.

    Args:
        queries: Lista de (empresa, ciudad).
        headful: Si abrir el navegador visible.

    Returns:
        Lista de URLs (mismo orden que queries); string vacío si no se encuentra.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise exc.PlaywrightNotAvailableError(
            "Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium"
        )

    results = [""] * len(queries)
    _SKIP_DOMAINS = [
        "facebook.com", "linkedin.com", "youtube.com", "instagram.com",
        "twitter.com", "x.com", "tiktok.com", "google.com", "googleapis.com",
    ]

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=not headful, slow_mo=50 if headful else 0)
            ctx = await browser.new_context(
                locale="es-419",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()
            cookies_accepted = False

            for i, (empresa, ciudad) in enumerate(queries):
                if not empresa:
                    continue

                query = f'"{empresa}" sitio web oficial'
                if ciudad:
                    query += f" {ciudad}"

                log.info("Buscando sitio web [%d/%d]: %s", i + 1, len(queries), empresa)

                try:
                    google_url = (
                        f"https://www.google.com/search?q={utils.urllib.parse.quote(query)}"
                    )
                    await page.goto(google_url, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(1500)

                    if not cookies_accepted:
                        try:
                            await page.click('button:has-text("Aceptar todo")', timeout=1500)
                            await page.wait_for_timeout(300)
                            cookies_accepted = True
                        except Exception:
                            pass

                    selectors = [
                        'div.g a[href^="http"]',
                        'div[data-hveid] a[href^="http"]',
                        'a[href^="http"]',
                    ]
                    found = ""
                    for selector in selectors:
                        els = await page.locator(selector).all()
                        for el in els[:10]:
                            href = await el.get_attribute("href")
                            if not href or "google.com" in href or "url?q=" in href:
                                continue
                            if any(d in href.lower() for d in _SKIP_DOMAINS):
                                continue
                            parsed = utils.urllib.parse.urlparse(href)
                            domain = parsed.netloc
                            if (
                                domain
                                and "example.com" not in domain
                                and len(domain) > cfg.ENRICHMENT["min_domain_length"]
                            ):
                                found = f"https://{domain}"
                                break
                        if found:
                            break

                    results[i] = found
                    log.info("  → %s", found or "no encontrado")
                    await page.wait_for_timeout(800)  # pausa cortés entre búsquedas

                except Exception as e:
                    log.debug("Error buscando %s: %s", empresa, e)

            await browser.close()

    except exc.PlaywrightNotAvailableError:
        raise
    except Exception as e:
        log.warning("Batch browser search error: %s", e)

    return results


def find_websites_batch(queries: list[tuple[str, str]], headful: bool = False) -> list[str]:
    """
    Busca sitios web de múltiples empresas reutilizando un único browser (wrapper síncrono).

    Más eficiente que llamar a find_website() por cada lead.

    Args:
        queries: Lista de (empresa, ciudad).
        headful: Si abrir el navegador visible.

    Returns:
        Lista de URLs en el mismo orden que queries.
    """
    return asyncio.run(_find_websites_batch_async(queries, headful))


# ─── Enriquecimiento desde sitio web ───────────────────────────────────────────

@utils.rate_limit(**cfg.RATE_LIMITING["website_scraping"])
def enrich_from_website(url: str, nombre_contacto: str = "") -> dict[str, Any]:
    """
    Visita el sitio web y extrae emails, teléfonos y redes sociales.

    Args:
        url: URL del sitio web.
        nombre_contacto: Nombre del contacto (para generar emails personales).

    Returns:
        Diccionario con datos enriquecidos.
    """
    if not url:
        return {}

    # Normalizar URL
    url = utils.normalize_url(url)

    try:
        html = fetch_html(url)
    except Exception:
        return {}

    if not html:
        return {}

    emails = extract_emails_from_html(html)
    phones = extract_phones_from_html(html)
    social = extract_social_from_html(html)

    domain = utils.extract_domain(url)

    result = {
        const.ColumnNames.EMAIL_WEB: emails[0] if emails else "",
        const.ColumnNames.EMAIL_WEB_2: emails[1] if len(emails) > 1 else "",
        const.ColumnNames.EMAIL_WEB_3: emails[2] if len(emails) > 2 else "",
        const.ColumnNames.TELEFONO_WEB: phones[0] if phones else "",
        const.ColumnNames.TELEFONO_WEB_2: phones[1] if len(phones) > 1 else "",
        const.ColumnNames.LINKEDIN: social.get("linkedin", ""),
        const.ColumnNames.FACEBOOK: social.get("facebook", ""),
        const.ColumnNames.INSTAGRAM: social.get("instagram", ""),
        const.ColumnNames.TWITTER: social.get("twitter", ""),
        const.ColumnNames.YOUTUBE: social.get("youtube", ""),
        const.ColumnNames.TIKTOK: social.get("tiktok", ""),
        const.ColumnNames.DOMINIO_WEB: domain,
    }

    # Generar emails personales probables
    if nombre_contacto and domain:
        personal_emails = utils.guess_personal_emails(nombre_contacto, domain)
        result[const.ColumnNames.EMAIL_PERSONAL_GUESS] = personal_emails[0] if personal_emails else ""
        result[const.ColumnNames.EMAIL_PERSONAL_GUESS_2] = personal_emails[1] if len(personal_emails) > 1 else ""

    return result


# ─── Enriquecimiento de leads ───────────────────────────────────────────────────

def enrich_lead(lead: dict[str, Any], delay: float = 1.0, headful: bool = False) -> dict[str, Any]:
    """
    Enriquece un lead con información de contacto adicional.

    Args:
        lead: Diccionario con datos del lead.
        delay: Pausa entre peticiones en segundos.
        headful: Si abrir el navegador visible.

    Returns:
        Diccionario con datos enriquecidos.
    """
    empresa = lead.get(const.ColumnNames.EMPRESA, "")
    sitio_web = lead.get(const.ColumnNames.SITIO_WEB, "")
    nombre_contacto = lead.get(const.ColumnNames.CONTACTO_NOMBRE, "")
    ciudad = lead.get(const.ColumnNames.CIUDAD, "")

    log.info("Enriqueciendo: %s", empresa)

    enriched = lead.copy()

    # Si no tiene sitio web, buscarlo
    if not sitio_web:
        log.info("  Buscando sitio web...")
        try:
            sitio_web = find_website(empresa, ciudad, headful=headful)
        except exc.GoogleSearchError as e:
            log.debug("Error buscando sitio web: %s", e)
            sitio_web = ""

        if sitio_web:
            enriched[const.ColumnNames.SITIO_WEB] = sitio_web
            log.info("  Sitio web encontrado: %s", sitio_web)
        else:
            log.info("  No se encontró sitio web")

    # Enriquecer desde sitio web
    if sitio_web:
        try:
            web_data = enrich_from_website(sitio_web, nombre_contacto)
        except Exception as e:
            log.debug("Error enriqueciendo desde sitio web: %s", e)
            web_data = {}

        for key, value in web_data.items():
            if not enriched.get(key):  # No sobrescribir datos existentes
                enriched[key] = value

        # Mostrar resumen
        found = []
        if web_data.get(const.ColumnNames.EMAIL_WEB):
            found.append("email web")
        if web_data.get(const.ColumnNames.TELEFONO_WEB):
            found.append("teléfono web")
        if web_data.get(const.ColumnNames.LINKEDIN):
            found.append("LinkedIn")
        if web_data.get(const.ColumnNames.FACEBOOK):
            found.append("Facebook")
        if web_data.get(const.ColumnNames.INSTAGRAM):
            found.append("Instagram")
        if web_data.get(const.ColumnNames.EMAIL_PERSONAL_GUESS):
            found.append("email personal (guess)")

        if found:
            log.info("  Encontrado: %s", ", ".join(found))

    time.sleep(delay)

    return enriched


def enrich_leads(leads: list[dict[str, Any]], delay: float = 1.0, headful: bool = False, workers: int = 1) -> list[dict[str, Any]]:
    """
    Enriquece una lista de leads.

    Hace una búsqueda batch de sitios web (un solo browser para todos los leads
    sin sitio web) antes de procesar el enriquecimiento individual.

    Args:
        leads: Lista de leads a enriquecer.
        delay: Pausa entre peticiones en segundos.
        headful: Si abrir el navegador visible.
        workers: Número de workers paralelos.

    Returns:
        Lista de leads enriquecidos.
    """
    if not leads:
        return []

    # Pre-paso: buscar sitios web faltantes con un único browser compartido.
    needs_idx = [
        i for i, l in enumerate(leads)
        if not l.get(const.ColumnNames.SITIO_WEB)
    ]
    if needs_idx:
        queries = [
            (
                leads[i].get(const.ColumnNames.EMPRESA, ""),
                leads[i].get(const.ColumnNames.CIUDAD, ""),
            )
            for i in needs_idx
        ]
        log.info("Buscando sitios web faltantes: %d leads (batch browser)", len(needs_idx))
        try:
            found_sites = find_websites_batch(queries, headful)
        except Exception as e:
            log.warning("Batch website search failed, se intentará por lead: %s", e)
            found_sites = [""] * len(needs_idx)

        # Copiar lista para no mutar el argumento del llamador
        leads = [l.copy() for l in leads]
        for i_lead, website in zip(needs_idx, found_sites):
            if website:
                leads[i_lead][const.ColumnNames.SITIO_WEB] = website

    # Enriquecimiento desde sitios web (enrich_lead ya no llama find_website si hay sitio)
    if workers == 1:
        return [enrich_lead(lead, delay, headful) for lead in leads]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(enrich_lead, lead, delay, headful): i
                  for i, lead in enumerate(leads)}
        results = [None] * len(leads)
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
        return results


# ─── Lectura/Guardado de CSV ───────────────────────────────────────────────────

def read_csv(path: Path) -> list[dict[str, Any]]:
    """
    Lee un CSV y devuelve una lista de diccionarios.

    Args:
        path: Ruta del archivo CSV.

    Returns:
        Lista de diccionarios con los datos del CSV.

    Raises:
        CSVError: Si hay error al leer el CSV.
    """
    if not path.exists():
        raise exc.AppFileNotFoundError(f"Archivo no encontrado: {path}", file_path=str(path))

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        raise exc.CSVError(f"No se pudo leer CSV: {path}", file_path=str(path)) from e


def save_csv(leads: list[dict[str, Any]], path: Path) -> None:
    """
    Guarda una lista de diccionarios en CSV.

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
        raise exc.CSVError(f"No se pudo guardar CSV: {path}", file_path=str(path)) from e


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parsea argumentos de línea de comandos."""
    p = argparse.ArgumentParser(
        description="Enriquece contactos de leads con emails personales, redes sociales y teléfonos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python contact_enricher.py output/leads_calificados.csv output/leads_enriched.csv
  python contact_enricher.py output/leads_calificados.csv output/leads_enriched.csv --headful
  python contact_enricher.py output/leads_calificados.csv output/leads_enriched.csv --delay 2.0
  python contact_enricher.py output/leads_calificados.csv output/leads_enriched.csv --workers 3
        """,
    )
    p.add_argument("input", help="Archivo CSV de entrada con leads")
    p.add_argument("output", help="Archivo CSV de salida con leads enriquecidos")
    p.add_argument("--delay", type=float, default=1.0, help="Pausa entre peticiones en segundos (default: 1.0)")
    p.add_argument("--headful", action="store_true", help="Abrir el navegador visible (útil para depurar)")
    p.add_argument("--workers", type=int, default=1, help="Workers paralelos (default: 1)")
    return p.parse_args()


def main() -> None:
    """Función principal."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging_config.silence_sensitive_http_loggers()

    args = parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Leer leads
    log.info("Leyendo leads de: %s", input_path)
    try:
        leads = read_csv(input_path)
    except exc.CSVError as e:
        log.error("Error: %s", e)
        sys.exit(const.ExitCodes.IO_ERROR)

    if not leads:
        log.error("No se encontraron leads en el archivo de entrada.")
        sys.exit(const.ExitCodes.ERROR)

    log.info("Leads a enriquecer: %d", len(leads))

    # Enriquecer
    log.info("Iniciando enriquecimiento de contactos...")
    try:
        enriched = enrich_leads(leads, delay=args.delay, headful=args.headful, workers=args.workers)
    except Exception as e:
        log.error("Error en enriquecimiento: %s", e)
        sys.exit(const.ExitCodes.ERROR)

    # Guardar
    try:
        save_csv(enriched, output_path)
    except exc.CSVError as e:
        log.error("Error al guardar CSV: %s", e)
        sys.exit(const.ExitCodes.ERROR)

    # Resumen
    with_email_web = sum(1 for l in enriched if l.get(const.ColumnNames.EMAIL_WEB))
    with_linkedin = sum(1 for l in enriched if l.get(const.ColumnNames.LINKEDIN))
    with_facebook = sum(1 for l in enriched if l.get(const.ColumnNames.FACEBOOK))
    with_instagram = sum(1 for l in enriched if l.get(const.ColumnNames.INSTAGRAM))
    with_phone_web = sum(1 for l in enriched if l.get(const.ColumnNames.TELEFONO_WEB))
    with_personal_guess = sum(1 for l in enriched if l.get(const.ColumnNames.EMAIL_PERSONAL_GUESS))

    print(f"\n{'=' * 56}")
    print("  ENRIQUECIMIENTO COMPLETADO")
    print(f"{'=' * 56}")
    print(f"  Leads procesados           : {len(enriched)}")
    print(f"  Con email web              : {with_email_web}")
    print(f"  Con teléfono web           : {with_phone_web}")
    print(f"  Con email personal (guess) : {with_personal_guess}")
    print(f"  Con LinkedIn               : {with_linkedin}")
    print(f"  Con Facebook               : {with_facebook}")
    print(f"  Con Instagram              : {with_instagram}")
    print(f"  Guardado en               : {output_path}")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()