"""
pipeline.py — Pipeline completo: scrape → califica → reporte.

Orquesta scraper.py, sdr_agent.py y contact_enricher.py en un solo proceso.

Uso:
    python pipeline.py "Retail Lima" --limit 20
    python pipeline.py "Construcción Trujillo" --limit 40 --workers 3 --report
    python pipeline.py "Logística Bogotá" --limit 15 --channel whatsapp --enrich-sunat
    python pipeline.py "Ferretería Arequipa" --limit 25 --headful --no-qualify
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

import logging_config

import config as cfg
import constants as const
import exceptions as exc

# Importar módulos directamente en lugar de ejecutar como subprocesses
from scraper import scrape_google_maps, enrich_leads as enrich_leads_scraper, save_leads
from sdr_agent import qualify_row, pre_score, generate_html_report
import pandas as pd

log = logging.getLogger("pipeline")
load_dotenv()


# ─── Calificación de leads ─────────────────────────────────────────────────────

def qualify_leads(leads: list[dict[str, Any]], channel: str, delay: float = 0.3, workers: int = 1) -> list[dict[str, Any]]:
    """
    Califica una lista de leads usando el LLM.

    Args:
        leads: Lista de leads a calificar.
        channel: Canal de outreach (email, whatsapp, both).
        delay: Pausa entre llamadas a Ollama.
        workers: Número de workers paralelos.

    Returns:
        Lista de leads calificados.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    total = len(leads)
    results: dict[int, dict[str, Any]] = {}

    def _process(idx: int, base: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Califica un lead y devuelve (idx, merged)."""
        base_score = pre_score(base)
        log.info("[%d/%d] %s | pre-score: %d", idx, total, base.get(const.ColumnNames.EMPRESA, "?"), base_score)
        try:
            result = qualify_row(base, channel, base_score)
            result[const.ColumnNames.QUALIFY_ERROR] = ""
        except Exception as e:
            log.error("[%d/%d] Error calificando: %s", idx, total, e)
            result = {k: "" for k in cfg.OUTPUT_KEYS if k != const.ColumnNames.QUALIFY_ERROR}
            result[const.ColumnNames.QUALIFY_ERROR] = str(e)

        time.sleep(delay)
        return idx, {**base, **result}

    if workers == 1:
        # Secuencial
        for i, lead in enumerate(leads, 1):
            idx, merged = _process(i, lead)
            results[idx] = merged
    else:
        # Paralelo
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_process, i, lead): i
                          for i, lead in enumerate(leads, 1)}
            for future in as_completed(future_map):
                idx, merged = future.result()
                results[idx] = merged

    # Ordenar resultados por índice original
    return [results[i] for i in sorted(results)]


# ─── Enriquecimiento de contactos ───────────────────────────────────────────────

def enrich_contacts(leads: list[dict[str, Any]], delay: float = 1.0, headful: bool = False, workers: int = 1) -> list[dict[str, Any]]:
    """
    Enriquece los contactos de una lista de leads.

    Args:
        leads: Lista de leads a enriquecer.
        delay: Pausa entre peticiones.
        headful: Si abrir el navegador visible.
        workers: Número de workers paralelos.

    Returns:
        Lista de leads con contactos enriquecidos.
    """
    from contact_enricher import enrich_leads

    return enrich_leads(leads, delay=delay, headful=headful, workers=workers)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parsea argumentos de línea de comandos."""
    p = argparse.ArgumentParser(
        description="Pipeline completo: scrape Google Maps → califica con LLM → genera reporte.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python pipeline.py "Retail Lima" --limit 20
  python pipeline.py "Logística Bogotá" --limit 30 --workers 2 --report
  python pipeline.py "Salud Arequipa" --limit 15 --channel whatsapp --enrich-sunat
        """,
    )
    # ── Scraping ──────────────────────────────────────────────────────────────
    p.add_argument("query", help='Búsqueda para Google Maps, ej: "Retail Lima Peru"')
    p.add_argument("--limit", type=int, default=20, help="Máx. leads a scrapear (default: 20)")
    p.add_argument("--headful", action="store_true", help="Abrir navegador visible (debug)")
    p.add_argument("--no-enrich", action="store_true", help="Omitir visita a sitios web")
    p.add_argument("--enrich-sunat", action="store_true", help="Consultar SUNAT por RUC (Perú)")
    p.add_argument("--scrape-delay", type=float, default=1.2, help="Pausa entre visitas web (default: 1.2s)")

    # ── Calificación ──────────────────────────────────────────────────────────
    p.add_argument("--no-qualify", action="store_true", help="Solo scrape, sin calificación LLM")
    p.add_argument("--channel", choices=["email", "whatsapp", "both"], default="email")
    p.add_argument("--workers", type=int, default=1, help="Workers paralelos para el LLM (default: 1)")
    p.add_argument("--qualify-delay", type=float, default=0.3, help="Pausa entre llamadas a Ollama (default: 0.3s)")
    p.add_argument("--report", action="store_true", help="Generar reporte HTML")

    # ── Enriquecimiento de contactos ───────────────────────────────────────────
    p.add_argument("--enrich-contacts", action="store_true", help="Enriquecer contactos con emails personales y redes sociales")
    p.add_argument("--contact-delay", type=float, default=1.0, help="Pausa entre enriquecimiento de contactos (default: 1.0s)")
    p.add_argument("--contact-workers", type=int, default=1, help="Workers para enriquecimiento de contactos (default: 1)")

    # ── Output ────────────────────────────────────────────────────────────────
    p.add_argument("--out-dir", default="output", help="Directorio de salida (default: output/)")
    p.add_argument("--out-file", default=None, help="Nombre base del archivo de salida (sin extensión)")

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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = args.out_file or f"leads_{ts}"
    raw_csv = out_dir / f"{base_name}_raw.csv"
    qualified_csv = out_dir / f"{base_name}_calificados.csv"
    enriched_csv = out_dir / f"{base_name}_enriched.csv"

    # ── Paso 1: Scraping ──────────────────────────────────────────────────────
    print(f"\n{'='*54}")
    print(f"  PASO 1 / {'1' if args.no_qualify else '2'} — SCRAPING")
    print(f"  Query  : {args.query}")
    print(f"  Limite : {args.limit} leads")
    print(f"{'='*54}\n")

    try:
        leads = scrape_google_maps(args.query, args.limit, headful=args.headful)
    except exc.GoogleMapsError as e:
        log.error("Scraping falló: %s", e)
        sys.exit(const.ExitCodes.NETWORK_ERROR)

    if not leads:
        log.error("No se obtuvieron leads. Verifica la query o la conexión.")
        sys.exit(const.ExitCodes.ERROR)

    log.info("Leads encontrados: %d", len(leads))

    # Enriquecimiento desde sitios web
    if not args.no_enrich:
        log.info("Enriqueciendo con datos de sitios web...")
        try:
            leads = enrich_leads_scraper(leads, use_sunat=args.enrich_sunat, delay=args.scrape_delay)
        except Exception as e:
            log.error("Error en enriquecimiento: %s", e)
            sys.exit(const.ExitCodes.ERROR)

        emails_found = sum(1 for l in leads if l.get(const.ColumnNames.EMAIL))
        log.info("Emails encontrados: %d/%d", emails_found, len(leads))
    else:
        log.info("Enriquecimiento omitido (--no-enrich)")

    # Guardar leads raw
    try:
        save_leads(leads, raw_csv)
    except exc.CSVError as e:
        log.error("Error al guardar CSV: %s", e)
        sys.exit(const.ExitCodes.ERROR)

    if args.no_qualify:
        print(f"\nScraping completado. CSV en: {raw_csv}")
        print("(--no-qualify activo: calificación omitida)\n")
        return

    # ── Paso 2: Calificación ──────────────────────────────────────────────────
    print(f"\n{'='*54}")
    print(f"  PASO 2 / {'3' if args.enrich_contacts else '2'} — CALIFICACION CON LLM")
    print(f"  Entrada: {raw_csv.name}")
    print(f"  Salida : {qualified_csv.name}")
    print(f"{'='*54}\n")

    try:
        qualified = qualify_leads(leads, channel=args.channel, delay=args.qualify_delay, workers=args.workers)
    except Exception as e:
        log.error("Calificación falló: %s", e)
        sys.exit(const.ExitCodes.ERROR)

    # Guardar leads calificados
    try:
        save_leads(qualified, qualified_csv)
    except exc.CSVError as e:
        log.error("Error al guardar CSV: %s", e)
        sys.exit(const.ExitCodes.ERROR)

    # Generar reporte HTML
    if args.report:
        report_path = qualified_csv.with_suffix(".html")
        try:
            df = pd.DataFrame(qualified)
            generate_html_report(df, report_path)
        except Exception as e:
            log.error("Error al generar reporte: %s", e)

    # ── Paso 3: Enriquecimiento de contactos (opcional) ───────────────────────
    if args.enrich_contacts:
        print(f"\n{'='*54}")
        print("  PASO 3 / 3 — ENRIQUECIMIENTO DE CONTACTOS")
        print(f"  Entrada: {qualified_csv.name}")
        print(f"  Salida : {enriched_csv.name}")
        print(f"{'='*54}\n")

        try:
            enriched = enrich_contacts(qualified, delay=args.contact_delay, headful=args.headful, workers=args.contact_workers)
        except Exception as e:
            log.error("Enriquecimiento de contactos falló: %s", e)
            sys.exit(const.ExitCodes.ERROR)

        # Guardar leads enriquecidos
        try:
            save_leads(enriched, enriched_csv)
        except exc.CSVError as e:
            log.error("Error al guardar CSV: %s", e)
            sys.exit(const.ExitCodes.ERROR)

        # Resumen de enriquecimiento
        with_email_web = sum(1 for l in enriched if l.get(const.ColumnNames.EMAIL_WEB))
        with_linkedin = sum(1 for l in enriched if l.get(const.ColumnNames.LINKEDIN))
        with_facebook = sum(1 for l in enriched if l.get(const.ColumnNames.FACEBOOK))
        with_instagram = sum(1 for l in enriched if l.get(const.ColumnNames.INSTAGRAM))
        with_phone_web = sum(1 for l in enriched if l.get(const.ColumnNames.TELEFONO_WEB))
        with_personal_guess = sum(1 for l in enriched if l.get(const.ColumnNames.EMAIL_PERSONAL_GUESS))

        print(f"\n{'=' * 56}")
        print("  ENRIQUECIMIENTO DE CONTACTOS COMPLETADO")
        print(f"{'=' * 56}")
        print(f"  Con email web              : {with_email_web}")
        print(f"  Con teléfono web           : {with_phone_web}")
        print(f"  Con email personal (guess) : {with_personal_guess}")
        print(f"  Con LinkedIn               : {with_linkedin}")
        print(f"  Con Facebook               : {with_facebook}")
        print(f"  Con Instagram              : {with_instagram}")
        print(f"{'=' * 56}\n")

    # ── Resumen final ─────────────────────────────────────────────────────────
    print(f"\n{'='*54}")
    print("  PIPELINE COMPLETADO")
    print(f"{'='*54}")
    print(f"  Leads scrapeados : {raw_csv}")
    print(f"  Leads calificados: {qualified_csv}")
    if args.report:
        print(f"  Reporte HTML     : {qualified_csv.with_suffix('.html')}")
    if args.enrich_contacts:
        print(f"  Leads enriquecidos: {enriched_csv}")
    print(f"{'='*54}\n")


if __name__ == "__main__":
    main()