"""
tests/test_scraper.py — Tests unitarios para funciones puras de scraper.py
(sin red, sin Playwright — solo lógica determinista)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import scraper
import utils


# ─── map_category ─────────────────────────────────────────────────────────────

class TestMapCategory:
    def test_logistica(self):
        assert scraper.map_category("Empresa de logística") == "Logística"

    def test_retail(self):
        assert scraper.map_category("Tienda de ropa") == "Retail"

    def test_construccion(self):
        assert scraper.map_category("Empresa constructora") == "Construcción"

    def test_salud(self):
        assert scraper.map_category("Clínica dental") == "Salud"

    def test_tecnologia(self):
        assert scraper.map_category("Software y tecnología") == "Tecnología"

    def test_sin_match_devuelve_original(self):
        result = scraper.map_category("Notaría pública")
        assert result == "Notaría pública"

    def test_vacio_devuelve_otro(self):
        assert scraper.map_category("") == "Otro"

    def test_case_insensitive(self):
        assert scraper.map_category("LOGÍSTICA") == "Logística"


# ─── extract_emails_from_html ─────────────────────────────────────────────────

class TestExtractEmails:
    def test_extrae_mailto(self):
        html = '<a href="mailto:ventas@empresa.pe">Contacto</a>'
        assert "ventas@empresa.pe" in scraper.extract_emails_from_html(html)

    def test_extrae_patron_texto(self):
        html = "<p>Escríbenos a contacto@mipyme.com para más información.</p>"
        assert "contacto@mipyme.com" in scraper.extract_emails_from_html(html)

    def test_deduplica(self):
        html = '<a href="mailto:info@a.com">x</a> <a href="mailto:info@a.com">y</a>'
        emails = scraper.extract_emails_from_html(html)
        assert emails.count("info@a.com") == 1

    def test_filtra_dominios_blacklist(self):
        html = '<a href="mailto:error@sentry.io">x</a> info@miempresa.pe'
        emails = scraper.extract_emails_from_html(html)
        assert not any("sentry.io" in e for e in emails)
        assert "info@miempresa.pe" in emails

    def test_html_sin_emails(self):
        html = "<p>No hay ningún correo aquí.</p>"
        assert scraper.extract_emails_from_html(html) == []

    def test_prioriza_mailto_sobre_texto(self):
        html = '<a href="mailto:ventas@emp.pe">x</a> otra@emp.pe'
        emails = scraper.extract_emails_from_html(html)
        assert emails[0] == "ventas@emp.pe"

    def test_limpia_caracteres_finales(self):
        html = "<p>Email: info@empresa.pe.</p>"
        emails = scraper.extract_emails_from_html(html)
        assert "info@empresa.pe" in emails
        assert all(not e.endswith(".") for e in emails)


# ─── guess_emails ─────────────────────────────────────────────────────────────

class TestGuessEmails:
    def test_genera_lista(self):
        guesses = scraper.guess_emails("empresa.pe")
        assert len(guesses) > 0
        assert all("@empresa.pe" in g for g in guesses)

    def test_incluye_prefijos_comunes(self):
        guesses = scraper.guess_emails("test.com")
        prefixes = [g.split("@")[0] for g in guesses]
        assert "info" in prefixes
        assert "ventas" in prefixes
        assert "contacto" in prefixes


# ─── enrich_sunat (con RUC inválido — no llama a la red) ─────────────────────

class TestEnrichSunat:
    def test_ruc_corto_devuelve_vacio(self):
        assert scraper.enrich_sunat("123") == {}

    def test_ruc_con_letras_devuelve_vacio(self):
        assert scraper.enrich_sunat("2012345678X") == {}

    def test_ruc_vacio_devuelve_vacio(self):
        assert scraper.enrich_sunat("") == {}

    def test_ruc_como_float_string(self):
        # Pandas puede leer el RUC como "20123456789.0"
        assert scraper.enrich_sunat("20123456789.0") == {}  # 13 chars después de limpiar → inválido...
        # wait, "20123456789.0" → remove non-digits → "201234567890" → 12 digits → invalid ✓


# ─── utils.trunc ─────────────────────────────────────────────────────────────

class TestTrunc:
    def test_cadena_corta_no_se_trunca(self):
        assert utils.trunc("hola", 100) == "hola"

    def test_cadena_exacta_no_se_trunca(self):
        assert utils.trunc("abcd", 4) == "abcd"

    def test_cadena_larga_se_trunca(self):
        result = utils.trunc("abcde", 4)
        assert result.startswith("abcd")
        assert "[truncated]" in result

    def test_cadena_vacia_devuelve_vacia(self):
        assert utils.trunc("", 100) == ""

    def test_ninguno_devuelve_vacio(self):
        assert utils.trunc(None, 100) == ""  # type: ignore[arg-type]

    def test_n_cero_trunca_todo(self):
        result = utils.trunc("abc", 0)
        assert "[truncated]" in result

    def test_default_n_es_2000(self):
        s = "x" * 2000
        assert utils.trunc(s) == s
        s_long = "x" * 2001
        assert "[truncated]" in utils.trunc(s_long)


# ─── config.SCRAPING — timeouts Apify ────────────────────────────────────────

class TestApifyTimeoutsConfig:
    def test_apify_actor_timeout_en_scraping(self):
        import config as cfg
        assert "apify_actor_timeout_s" in cfg.SCRAPING
        assert cfg.SCRAPING["apify_actor_timeout_s"] > 0

    def test_apify_http_timeout_en_scraping(self):
        import config as cfg
        assert "apify_http_timeout_s" in cfg.SCRAPING
        assert cfg.SCRAPING["apify_http_timeout_s"] > 0

    def test_http_timeout_mayor_que_actor_timeout(self):
        import config as cfg
        assert cfg.SCRAPING["apify_http_timeout_s"] >= cfg.SCRAPING["apify_actor_timeout_s"]

    def test_apify_api_key_es_string(self):
        import config as cfg
        assert isinstance(cfg.APIFY_API_KEY, str)

    def test_serpapi_api_key_es_string(self):
        import config as cfg
        assert isinstance(cfg.SERPAPI_API_KEY, str)

    def test_google_places_api_key_es_string(self):
        import config as cfg
        assert isinstance(cfg.GOOGLE_PLACES_API_KEY, str)
