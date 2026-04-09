"""
test_integration.py — Tests de integración para AgentePyme SDR.

Estos tests verifican el flujo completo del pipeline y la integración
entre los diferentes módulos.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Agregar directorio padre al path para importar módulos
sys.path.insert(0, str(Path(__file__).parent.parent))

import config as cfg
import constants as const
import exceptions as exc
import models
import utils


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_lead_data() -> dict:
    """Datos de un lead de ejemplo."""
    return {
        const.ColumnNames.EMPRESA: "Empresa Test SAC",
        const.ColumnNames.INDUSTRIA: "Retail",
        const.ColumnNames.RUC: "20123456789",
        const.ColumnNames.EMAIL: "contacto@empresa.com",
        const.ColumnNames.TELEFONO: "+51987654321",
        const.ColumnNames.CIUDAD: "Lima",
        const.ColumnNames.PAIS: "Peru",
        const.ColumnNames.FACTURAS_PENDIENTES: "25",
        const.ColumnNames.CONTACTO_NOMBRE: "Juan Pérez",
        const.ColumnNames.CARGO: "Gerente General",
        const.ColumnNames.SITIO_WEB: "https://www.empresa.com",
    }


@pytest.fixture
def sample_leads_csv(tmp_path: Path, sample_lead_data: dict) -> Path:
    """Crea un CSV de ejemplo con leads."""
    csv_path = tmp_path / "leads.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=sample_lead_data.keys())
        writer.writeheader()
        writer.writerow(sample_lead_data)
    return csv_path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Directorio de salida para tests."""
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


# ─── Tests de integración de modelos ───────────────────────────────────────────

class TestLeadModel:
    """Tests de integración de la clase Lead."""

    def test_lead_from_dict(self, sample_lead_data: dict) -> None:
        """Prueba crear un Lead desde un diccionario."""
        lead = models.Lead.from_dict(sample_lead_data)

        assert lead.empresa == "Empresa Test SAC"
        assert lead.industria == "Retail"
        assert lead.ruc == "20123456789"
        assert lead.email == "contacto@empresa.com"
        assert lead.telefono == "+51987654321"
        assert lead.ciudad == "Lima"
        assert lead.pais == "Peru"
        assert lead.facturas_pendientes == 25
        assert lead.contacto_nombre == "Juan Pérez"
        assert lead.cargo == "Gerente General"
        assert lead.sitio_web == "https://www.empresa.com"

    def test_lead_to_dict(self, sample_lead_data: dict) -> None:
        """Prueba convertir un Lead a diccionario."""
        lead = models.Lead.from_dict(sample_lead_data)
        data = lead.to_dict()

        assert data[const.ColumnNames.EMPRESA] == "Empresa Test SAC"
        assert data[const.ColumnNames.INDUSTRIA] == "Retail"
        assert isinstance(data, dict)

    def test_lead_validate(self, sample_lead_data: dict) -> None:
        """Prueba validación de un Lead."""
        lead = models.Lead.from_dict(sample_lead_data)
        errors = lead.validate()

        assert errors == []

    def test_lead_validate_missing_empresa(self) -> None:
        """Prueba validación de Lead sin empresa."""
        data = {
            const.ColumnNames.INDUSTRIA: "Retail",
        }
        lead = models.Lead.from_dict(data)
        errors = lead.validate()

        assert len(errors) > 0
        assert any("empresa" in error.lower() for error in errors)

    def test_lead_is_qualified(self, sample_lead_data: dict) -> None:
        """Prueba método is_qualified."""
        lead = models.Lead.from_dict(sample_lead_data)
        lead.crm_stage = const.CRMStages.QUALIFIED

        assert lead.is_qualified()

    def test_lead_is_processed(self, sample_lead_data: dict) -> None:
        """Prueba método is_processed."""
        lead = models.Lead.from_dict(sample_lead_data)
        lead.crm_stage = const.CRMStages.FOLLOW_UP

        assert lead.is_processed()

    def test_lead_has_contact_info(self, sample_lead_data: dict) -> None:
        """Prueba método has_contact_info."""
        lead = models.Lead.from_dict(sample_lead_data)

        assert lead.has_contact_info()

    def test_lead_get_primary_email(self, sample_lead_data: dict) -> None:
        """Prueba método get_primary_email."""
        lead = models.Lead.from_dict(sample_lead_data)

        assert lead.get_primary_email() == "contacto@empresa.com"

    def test_lead_get_primary_phone(self, sample_lead_data: dict) -> None:
        """Prueba método get_primary_phone."""
        lead = models.Lead.from_dict(sample_lead_data)

        assert lead.get_primary_phone() == "+51987654321"


class TestLeadListModel:
    """Tests de integración de la clase LeadList."""

    def test_lead_list_from_dict_list(self, sample_lead_data: dict) -> None:
        """Prueba crear LeadList desde lista de diccionarios."""
        leads_data = [sample_lead_data, sample_lead_data.copy()]
        lead_list = models.LeadList.from_dict_list(leads_data)

        assert len(lead_list.leads) == 2
        assert lead_list.total == 2

    def test_lead_list_recalculate_stats(self, sample_lead_data: dict) -> None:
        """Prueba recalcular estadísticas."""
        leads_data = [sample_lead_data.copy()]
        lead_list = models.LeadList.from_dict_list(leads_data)

        lead_list.leads[0].crm_stage = const.CRMStages.QUALIFIED
        lead_list.recalculate_stats()

        assert lead_list.qualified == 1
        assert lead_list.total == 1

    def test_lead_list_filter_by_stage(self, sample_lead_data: dict) -> None:
        """Prueba filtrar por etapa."""
        leads_data = [sample_lead_data.copy(), sample_lead_data.copy()]
        lead_list = models.LeadList.from_dict_list(leads_data)

        lead_list.leads[0].crm_stage = const.CRMStages.QUALIFIED
        lead_list.leads[1].crm_stage = const.CRMStages.PROSPECCION

        qualified = lead_list.filter_by_stage(const.CRMStages.QUALIFIED)

        assert len(qualified) == 1
        assert qualified[0].crm_stage == const.CRMStages.QUALIFIED

    def test_lead_list_get_top_leads(self, sample_lead_data: dict) -> None:
        """Prueba obtener leads con mayor score."""
        leads_data = [sample_lead_data.copy(), sample_lead_data.copy()]
        lead_list = models.LeadList.from_dict_list(leads_data)

        lead_list.leads[0].lead_score = 90
        lead_list.leads[1].lead_score = 70

        top = lead_list.get_top_leads(1)

        assert len(top) == 1
        assert top[0].lead_score == 90


# ─── Tests de integración de utils ─────────────────────────────────────────────

class TestUtilsIntegration:
    """Tests de integración de funciones utilitarias."""

    def test_normalize(self) -> None:
        """Prueba normalización de texto."""
        assert utils.normalize("Café Perú") == "cafe peru"
        assert utils.normalize("  Hola  Mundo  ") == "hola mundo"
        assert utils.normalize("") == ""

    def test_is_valid_email(self) -> None:
        """Prueba validación de emails."""
        assert utils.is_valid_email("usuario@ejemplo.com") is True
        assert utils.is_valid_email("invalid-email") is False
        assert utils.is_valid_email("") is False

    def test_is_valid_phone(self) -> None:
        """Prueba validación de teléfonos."""
        assert utils.is_valid_phone("+51987654321") is True
        assert utils.is_valid_phone("123") is False
        assert utils.is_valid_phone("") is False

    def test_is_valid_ruc(self) -> None:
        """Prueba validación de RUCs."""
        assert utils.is_valid_ruc("20123456789") is True
        assert utils.is_valid_ruc("123") is False
        assert utils.is_valid_ruc("") is False

    def test_normalize_url(self) -> None:
        """Prueba normalización de URLs."""
        assert utils.normalize_url("example.com") == "https://example.com"
        assert utils.normalize_url("http://example.com") == "https://example.com"
        assert utils.normalize_url("https://example.com") == "https://example.com"

    def test_extract_domain(self) -> None:
        """Prueba extracción de dominio."""
        assert utils.extract_domain("https://www.example.com/path") == "example.com"
        assert utils.extract_domain("example.com") == "example.com"

    def test_extract_emails_from_text(self) -> None:
        """Prueba extracción de emails de texto."""
        text = "Contactar a info@ejemplo.com o ventas@ejemplo.com"
        emails = utils.extract_emails_from_text(text)

        assert "info@ejemplo.com" in emails
        assert "ventas@ejemplo.com" in emails

    def test_extract_phones_from_text(self) -> None:
        """Prueba extracción de teléfonos de texto."""
        text = "Llamar al +51 987 654 321 o al 01-123-4567"
        phones = utils.extract_phones_from_text(text)

        assert "+51987654321" in phones
        assert "011234567" in phones

    def test_guess_personal_emails(self) -> None:
        """Prueba generación de emails personales."""
        emails = utils.guess_personal_emails("Juan Pérez", "empresa.com")

        assert "juan.perez@empresa.com" in emails
        assert "juanperez@empresa.com" in emails
        assert "juan@empresa.com" in emails

    def test_validate_lead_data(self, sample_lead_data: dict) -> None:
        """Prueba validación de datos de lead."""
        errors = utils.validate_lead_data(sample_lead_data)

        assert errors == []

    def test_validate_lead_data_missing_empresa(self) -> None:
        """Prueba validación de lead sin empresa."""
        data = {const.ColumnNames.INDUSTRIA: "Retail"}
        errors = utils.validate_lead_data(data)

        assert len(errors) > 0
        assert any("empresa" in error.lower() for error in errors)

    def test_validate_lead_data_invalid_email(self) -> None:
        """Prueba validación de lead con email inválido."""
        data = {
            const.ColumnNames.EMPRESA: "Test",
            const.ColumnNames.EMAIL: "invalid-email",
        }
        errors = utils.validate_lead_data(data)

        assert len(errors) > 0
        assert any("email" in error.lower() for error in errors)


# ─── Tests de integración de excepciones ───────────────────────────────────────

class TestExceptionsIntegration:
    """Tests de integración de excepciones personalizadas."""

    def test_agente_pyme_error(self) -> None:
        """Prueba excepción base."""
        error = exc.AgentePymeError("Error de prueba")
        assert str(error) == "Error de prueba"

    def test_agente_pyme_error_with_details(self) -> None:
        """Prueba excepción base con detalles."""
        error = exc.AgentePymeError("Error de prueba", details="detalles adicionales")
        assert "detalles adicionales" in str(error)

    def test_lead_validation_error(self) -> None:
        """Prueba excepción de validación de lead."""
        error = exc.LeadValidationError("Email inválido", field="email", value="invalid")
        assert error.field == "email"
        assert error.value == "invalid"

    def test_website_scraping_error(self) -> None:
        """Prueba excepción de scraping de sitio web."""
        error = exc.WebsiteScrapingError("No se pudo descargar", url="https://example.com")
        assert error.url == "https://example.com"

    def test_sunat_error(self) -> None:
        """Prueba excepción de SUNAT."""
        error = exc.SunatError("Error en consulta", ruc="20123456789")
        assert error.ruc == "20123456789"

    def test_ollama_error(self) -> None:
        """Prueba excepción de Ollama."""
        error = exc.OllamaError("No se pudo conectar", model="mistral:7b")
        assert error.model == "mistral:7b"

    def test_llm_response_error(self) -> None:
        """Prueba excepción de respuesta de LLM."""
        error = exc.LLMResponseError("JSON inválido", response="not json")
        assert error.response == "not json"

    def test_google_search_error(self) -> None:
        """Prueba excepción de búsqueda en Google."""
        error = exc.GoogleSearchError("Error en búsqueda", query="test query")
        assert error.query == "test query"

    def test_csv_error(self) -> None:
        """Prueba excepción de CSV."""
        error = exc.CSVError("No se pudo guardar", file_path="/path/to/file.csv")
        assert error.file_path == "/path/to/file.csv"

    def test_http_error(self) -> None:
        """Prueba excepción HTTP."""
        error = exc.HTTPError("Error HTTP", status_code=404, url="https://example.com")
        assert error.status_code == 404
        assert error.url == "https://example.com"

    def test_timeout_error(self) -> None:
        """Prueba excepción de timeout."""
        error = exc.TimeoutError("Timeout", url="https://example.com", timeout=30.0)
        assert error.url == "https://example.com"
        assert error.timeout == 30.0

    def test_rate_limit_error(self) -> None:
        """Prueba excepción de rate limit."""
        error = exc.RateLimitError("Too many requests", retry_after=60.0)
        assert error.retry_after == 60.0


# ─── Tests de integración de configuración ───────────────────────────────────

class TestConfigIntegration:
    """Tests de integración de configuración."""

    def test_config_has_ollama(self) -> None:
        """Prueba que config tiene configuración de Ollama."""
        assert "url" in cfg.OLLAMA
        assert "model" in cfg.OLLAMA
        assert "timeout_s" in cfg.OLLAMA

    def test_config_has_product(self) -> None:
        """Prueba que config tiene configuración de producto."""
        assert "name" in cfg.PRODUCT
        assert "description" in cfg.PRODUCT
        assert "cta" in cfg.PRODUCT

    def test_config_has_icp(self) -> None:
        """Prueba que config tiene ICP."""
        assert "target_industries" in cfg.ICP
        assert "score_weights" in cfg.ICP
        assert "excluded_keywords" in cfg.ICP

    def test_config_has_enrichment(self) -> None:
        """Prueba que config tiene configuración de enriquecimiento."""
        assert "blacklist_domains" in cfg.ENRICHMENT
        assert "phone_patterns" in cfg.ENRICHMENT
        assert "social_patterns" in cfg.ENRICHMENT

    def test_config_has_scraping(self) -> None:
        """Prueba que config tiene configuración de scraping."""
        assert "default_limit" in cfg.SCRAPING
        assert "default_delay" in cfg.SCRAPING

    def test_config_has_qualification(self) -> None:
        """Prueba que config tiene configuración de calificación."""
        assert "default_delay" in cfg.QUALIFICATION
        assert "word_limits" in cfg.QUALIFICATION

    def test_config_has_rate_limiting(self) -> None:
        """Prueba que config tiene configuración de rate limiting."""
        assert "google_search" in cfg.RATE_LIMITING
        assert "sunat_api" in cfg.RATE_LIMITING
        assert "website_scraping" in cfg.RATE_LIMITING


# ─── Tests de integración de constantes ───────────────────────────────────────

class TestConstantsIntegration:
    """Tests de integración de constantes."""

    def test_column_names_exist(self) -> None:
        """Prueba que existen nombres de columna."""
        assert hasattr(const.ColumnNames, "EMPRESA")
        assert hasattr(const.ColumnNames, "INDUSTRIA")
        assert hasattr(const.ColumnNames, "EMAIL")
        assert hasattr(const.ColumnNames, "TELEFONO")

    def test_crm_stages_exist(self) -> None:
        """Prueba que existen etapas CRM."""
        assert hasattr(const.CRMStages, "PROSPECCION")
        assert hasattr(const.CRMStages, "QUALIFIED")
        assert hasattr(const.CRMStages, "FOLLOW_UP")
        assert hasattr(const.CRMStages, "DISCARDED")

    def test_crm_stages_processed(self) -> None:
        """Prueba que PROCESSED contiene las etapas correctas."""
        assert const.CRMStages.QUALIFIED in const.CRMStages.PROCESSED
        assert const.CRMStages.FOLLOW_UP in const.CRMStages.PROCESSED
        assert const.CRMStages.DISCARDED in const.CRMStages.PROCESSED

    def test_qualification_values_exist(self) -> None:
        """Prueba que existen valores de calificación."""
        assert hasattr(const.QualificationValues, "FIT_PRODUCT")
        assert hasattr(const.QualificationValues, "INTENT_TIMELINE")
        assert hasattr(const.QualificationValues, "DECISION_MAKER")

    def test_channel_exists(self) -> None:
        """Prueba que existen canales."""
        assert hasattr(const.Channel, "EMAIL")
        assert hasattr(const.Channel, "WHATSAPP")
        assert hasattr(const.Channel, "BOTH")

    def test_regex_patterns_exist(self) -> None:
        """Prueba que existen patrones de regex."""
        assert hasattr(const.RegexPatterns, "EMAIL")
        assert hasattr(const.RegexPatterns, "PHONE")
        assert hasattr(const.RegexPatterns, "LINKEDIN")

    def test_blacklist_domains_exists(self) -> None:
        """Prueba que existe blacklist de dominios."""
        assert isinstance(const.BLACKLIST_DOMAINS, set)
        assert "example.com" in const.BLACKLIST_DOMAINS

    def test_category_map_exists(self) -> None:
        """Prueba que existe mapeo de categorías."""
        assert isinstance(const.CATEGORY_MAP, dict)
        assert "retail" in const.CATEGORY_MAP


# ─── Tests de integración de pipeline ─────────────────────────────────────────

class TestPipelineIntegration:
    """Tests de integración del pipeline."""

    def test_pre_score_calculation(self, sample_lead_data: dict) -> None:
        """Prueba cálculo de pre-score."""
        from sdr_agent import pre_score

        score = pre_score(sample_lead_data)

        assert 0 <= score <= 65
        assert score > 0  # Debe tener al menos el score base

    def test_pre_score_industry_match(self, sample_lead_data: dict) -> None:
        """Prueba pre-score con industria objetivo."""
        from sdr_agent import pre_score

        sample_lead_data[const.ColumnNames.INDUSTRIA] = "Retail"
        score = pre_score(sample_lead_data)

        # Debe tener puntos por industria objetivo
        assert score >= cfg.ICP["score_weights"]["base"] + cfg.ICP["score_weights"]["industry_match"]

    def test_pre_score_no_industry_match(self, sample_lead_data: dict) -> None:
        """Prueba pre-score sin industria objetivo."""
        from sdr_agent import pre_score

        # Crear lead mínimo sin industria objetivo
        minimal_lead = {
            const.ColumnNames.EMPRESA: "Test",
            const.ColumnNames.INDUSTRIA: "Industria Desconocida",
        }
        score = pre_score(minimal_lead)

        # Solo debe tener el score base
        assert score == cfg.ICP["score_weights"]["base"]

    def test_should_skip_processed(self, sample_lead_data: dict) -> None:
        """Prueba should_skip con lead procesado."""
        from sdr_agent import should_skip

        sample_lead_data[const.ColumnNames.CRM_STAGE] = const.CRMStages.QUALIFIED
        should_skip = should_skip(sample_lead_data)

        assert should_skip is True

    def test_should_skip_not_processed(self, sample_lead_data: dict) -> None:
        """Prueba should_skip con lead no procesado."""
        from sdr_agent import should_skip

        sample_lead_data[const.ColumnNames.CRM_STAGE] = const.CRMStages.PROSPECCION
        should_skip = should_skip(sample_lead_data)

        assert should_skip is False

    def test_should_skip_empty_stage(self, sample_lead_data: dict) -> None:
        """Prueba should_skip con etapa vacía."""
        from sdr_agent import should_skip

        sample_lead_data[const.ColumnNames.CRM_STAGE] = ""
        should_skip = should_skip(sample_lead_data)

        assert should_skip is False


# ─── Tests de integración de CSV ───────────────────────────────────────────────

class TestCSVIntegration:
    """Tests de integración de lectura/escritura de CSV."""

    def test_read_csv(self, sample_leads_csv: Path) -> None:
        """Prueba lectura de CSV."""
        from contact_enricher import read_csv

        leads = read_csv(sample_leads_csv)

        assert len(leads) == 1
        assert leads[0][const.ColumnNames.EMPRESA] == "Empresa Test SAC"

    def test_save_csv(self, output_dir: Path, sample_lead_data: dict) -> None:
        """Prueba guardado de CSV."""
        from contact_enricher import save_csv

        output_path = output_dir / "output.csv"
        save_csv([sample_lead_data], output_path)

        assert output_path.exists()

        # Verificar contenido
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0][const.ColumnNames.EMPRESA] == "Empresa Test SAC"

    def test_csv_roundtrip(self, output_dir: Path, sample_lead_data: dict) -> None:
        """Prueba ciclo completo de CSV."""
        from contact_enricher import read_csv, save_csv

        # Guardar
        csv_path = output_dir / "roundtrip.csv"
        save_csv([sample_lead_data], csv_path)

        # Leer
        leads = read_csv(csv_path)

        # Verificar
        assert len(leads) == 1
        assert leads[0][const.ColumnNames.EMPRESA] == sample_lead_data[const.ColumnNames.EMPRESA]
        assert leads[0][const.ColumnNames.INDUSTRIA] == sample_lead_data[const.ColumnNames.INDUSTRIA]


# ─── Tests de integración de rate limiting ─────────────────────────────────────

class TestRateLimitingIntegration:
    """Tests de integración de rate limiting."""

    def test_rate_limit_decorator(self) -> None:
        """Prueba decorador de rate limiting."""
        call_count = [0]

        @utils.rate_limit(calls=2, period=1.0)
        def test_function():
            call_count[0] += 1
            return call_count[0]

        # Primeras 2 llamadas deben pasar
        assert test_function() == 1
        assert test_function() == 2

        # Tercera llamada debe esperar (pero en test no esperamos)
        # Solo verificamos que el decorador no rompa la función
        result = test_function()
        assert result == 3


# ─── Tests de integración de enriquecimiento ─────────────────────────────────

class TestEnrichmentIntegration:
    """Tests de integración de enriquecimiento."""

    def test_extract_emails_from_html(self) -> None:
        """Prueba extracción de emails de HTML."""
        from contact_enricher import extract_emails_from_html

        html = """
        <html>
        <body>
            <a href="mailto:info@empresa.com">Contacto</a>
            <p>Email: ventas@empresa.com</p>
        </body>
        </html>
        """

        emails = extract_emails_from_html(html)

        assert "info@empresa.com" in emails
        assert "ventas@empresa.com" in emails

    def test_extract_phones_from_html(self) -> None:
        """Prueba extracción de teléfonos de HTML."""
        from contact_enricher import extract_phones_from_html

        html = """
        <html>
        <body>
            <p>Teléfono: +51 987 654 321</p>
            <a href="tel:+5112345678">Oficina</a>
        </body>
        </html>
        """

        phones = extract_phones_from_html(html)

        assert "+51987654321" in phones
        assert "+5112345678" in phones

    def test_extract_social_from_html(self) -> None:
        """Prueba extracción de redes sociales de HTML."""
        from contact_enricher import extract_social_from_html

        html = """
        <html>
        <body>
            <a href="https://linkedin.com/company/test">LinkedIn</a>
            <a href="https://facebook.com/test">Facebook</a>
            <a href="https://instagram.com/test">Instagram</a>
        </body>
        </html>
        """

        social = extract_social_from_html(html)

        assert "linkedin.com" in social.get("linkedin", "")
        assert "facebook.com" in social.get("facebook", "")
        assert "instagram.com" in social.get("instagram", "")


# ─── Tests de integración end-to-end ───────────────────────────────────────────

class TestEndToEndIntegration:
    """Tests de integración end-to-end."""

    def test_lead_creation_to_csv_roundtrip(self, output_dir: Path, sample_lead_data: dict) -> None:
        """Prueba ciclo completo: Lead → CSV → Lead."""
        from contact_enricher import save_csv, read_csv

        # Crear Lead
        lead = models.Lead.from_dict(sample_lead_data)

        # Guardar en CSV
        csv_path = output_dir / "e2e.csv"
        save_csv([lead.to_dict()], csv_path)

        # Leer del CSV
        leads = read_csv(csv_path)

        # Recrear Lead
        lead_from_csv = models.Lead.from_dict(leads[0])

        # Verificar
        assert lead_from_csv.empresa == lead.empresa
        assert lead_from_csv.industria == lead.industria
        assert lead_from_csv.email == lead.email

    def test_lead_list_statistics(self, sample_lead_data: dict) -> None:
        """Prueba estadísticas de LeadList."""
        leads_data = [sample_lead_data.copy() for _ in range(10)]
        lead_list = models.LeadList.from_dict_list(leads_data)

        # Configurar diferentes etapas
        lead_list.leads[0].crm_stage = const.CRMStages.QUALIFIED
        lead_list.leads[1].crm_stage = const.CRMStages.QUALIFIED
        lead_list.leads[2].crm_stage = const.CRMStages.QUALIFIED
        lead_list.leads[3].crm_stage = const.CRMStages.FOLLOW_UP
        lead_list.leads[4].crm_stage = const.CRMStages.FOLLOW_UP
        lead_list.leads[5].crm_stage = const.CRMStages.PROSPECCION
        lead_list.leads[6].crm_stage = const.CRMStages.PROSPECCION
        lead_list.leads[7].crm_stage = const.CRMStages.PROSPECCION
        lead_list.leads[8].crm_stage = const.CRMStages.DISCARDED
        lead_list.leads[9].crm_stage = const.CRMStages.DISCARDED

        # Configurar scores
        for i, lead in enumerate(lead_list.leads):
            lead.lead_score = 90 - i * 5

        lead_list.recalculate_stats()

        # Verificar estadísticas
        assert lead_list.total == 10
        assert lead_list.qualified == 3
        assert lead_list.following == 2
        assert lead_list.prospecting == 3
        assert lead_list.discarded == 2
        assert 0 < lead_list.avg_score < 100

    def test_top_leads_selection(self, sample_lead_data: dict) -> None:
        """Prueba selección de top leads."""
        leads_data = [sample_lead_data.copy() for _ in range(10)]
        lead_list = models.LeadList.from_dict_list(leads_data)

        # Configurar scores aleatorios
        import random
        for lead in lead_list.leads:
            lead.lead_score = random.randint(50, 100)

        # Obtener top 3
        top_3 = lead_list.get_top_leads(3)

        assert len(top_3) == 3
        # Verificar que están ordenados descendente
        assert top_3[0].lead_score >= top_3[1].lead_score
        assert top_3[1].lead_score >= top_3[2].lead_score


# ─── Tests de casos edge ──────────────────────────────────────────────────────

class TestEdgeCasesIntegration:
    """Casos borde: listas vacías, archivos inexistentes, datos inválidos."""

    def test_enrich_leads_empty_list(self) -> None:
        """enrich_leads con lista vacía debe devolver lista vacía."""
        from contact_enricher import enrich_leads
        result = enrich_leads([])
        assert result == []

    def test_read_csv_not_found(self, tmp_path: Path) -> None:
        """read_csv con archivo inexistente debe levantar FileNotFoundError."""
        from contact_enricher import read_csv
        with pytest.raises(exc.FileNotFoundError):
            read_csv(tmp_path / "nonexistent.csv")

    def test_save_csv_empty_list_no_crash(self, output_dir: Path) -> None:
        """save_csv con lista vacía no debe fallar ni crear archivo."""
        from contact_enricher import save_csv
        path = output_dir / "empty.csv"
        save_csv([], path)
        assert not path.exists()

    def test_validate_lead_data_negative_facturas(self) -> None:
        """facturas_pendientes negativo debe reportar error de validación."""
        data = {
            const.ColumnNames.EMPRESA: "Test SAC",
            const.ColumnNames.FACTURAS_PENDIENTES: "-5",
        }
        errors = utils.validate_lead_data(data)
        assert any("factura" in e.lower() for e in errors)

    def test_pre_score_all_nans(self) -> None:
        """pre_score con todos los campos como 'nan' no debe fallar."""
        from sdr_agent import pre_score
        import config as cfg
        lead = {
            const.ColumnNames.EMPRESA: "nan",
            const.ColumnNames.INDUSTRIA: "nan",
            const.ColumnNames.EMAIL: "nan",
            const.ColumnNames.TELEFONO: "nan",
            const.ColumnNames.NUM_RESENAS: "nan",
            const.ColumnNames.RATING: "nan",
        }
        score = pre_score(lead)
        assert isinstance(score, int)
        assert score == cfg.ICP["score_weights"]["base"]

    def test_lead_from_dict_extra_fields_ignored(self, sample_lead_data: dict) -> None:
        """Lead.from_dict debe ignorar campos desconocidos sin fallar."""
        data = {**sample_lead_data, "campo_inventado": "valor_cualquiera"}
        lead = models.Lead.from_dict(data)
        assert lead.empresa == sample_lead_data[const.ColumnNames.EMPRESA]

    def test_csv_with_missing_column_reads_ok(self, tmp_path: Path) -> None:
        """Un CSV sin la columna 'industria' debe leerse sin error."""
        from contact_enricher import read_csv
        csv_path = tmp_path / "minimal.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            import csv as csv_mod
            writer = csv_mod.DictWriter(f, fieldnames=["empresa", "email"])
            writer.writeheader()
            writer.writerow({"empresa": "Test SAC", "email": "a@b.com"})
        leads = read_csv(csv_path)
        assert len(leads) == 1
        assert leads[0]["empresa"] == "Test SAC"
        assert "industria" not in leads[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])