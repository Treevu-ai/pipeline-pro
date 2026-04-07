"""
tests/test_sdr.py — Tests unitarios para funciones puras de sdr_agent.

Ejecutar:
    python -m pytest tests/ -v
    python -m pytest tests/ -v --tb=short
"""
import sys
from pathlib import Path

# Permite importar sdr_agent desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import sdr_agent as sdr


# ─── _normalize ───────────────────────────────────────────────────────────────

class TestNormalize:
    def test_quita_acento_simple(self):
        assert sdr._normalize("Prospección") == "prospeccion"

    def test_quita_multiple_acentos(self):
        assert sdr._normalize("Calificación") == "calificacion"

    def test_lowercase(self):
        assert sdr._normalize("CALIFICADO") == "calificado"

    def test_strip_espacios(self):
        assert sdr._normalize("  calificado  ") == "calificado"

    def test_cadena_vacia(self):
        assert sdr._normalize("") == ""


# ─── should_skip ──────────────────────────────────────────────────────────────

class TestShouldSkip:
    def test_calificado_se_salta(self):
        assert sdr.should_skip({"crm_stage": "Calificado"}) is True

    def test_en_seguimiento_se_salta(self):
        assert sdr.should_skip({"crm_stage": "En seguimiento"}) is True

    def test_descartado_se_salta(self):
        assert sdr.should_skip({"crm_stage": "Descartado"}) is True

    def test_prospeccion_con_acento_no_se_salta(self):
        assert sdr.should_skip({"crm_stage": "Prospección"}) is False

    def test_prospeccion_sin_acento_no_se_salta(self):
        # Bug histórico: sin el normalize esto devolvía True
        assert sdr.should_skip({"crm_stage": "Prospeccion"}) is False

    def test_pendiente_no_se_salta(self):
        assert sdr.should_skip({"crm_stage": "Pendiente"}) is False

    def test_vacio_no_se_salta(self):
        assert sdr.should_skip({"crm_stage": ""}) is False

    def test_columna_ausente_no_se_salta(self):
        assert sdr.should_skip({}) is False


# ─── _parse_json_loose ────────────────────────────────────────────────────────

class TestParseJsonLoose:
    def test_json_limpio(self):
        result = sdr._parse_json_loose('{"crm_stage": "Calificado", "lead_score": 85}')
        assert result["crm_stage"] == "Calificado"
        assert result["lead_score"] == 85

    def test_json_con_espacios_al_inicio(self):
        result = sdr._parse_json_loose('   {"a": 1}   ')
        assert result["a"] == 1

    def test_json_envuelto_en_texto(self):
        # Algunos modelos anteponen texto antes del JSON
        result = sdr._parse_json_loose('Aquí está el resultado:\n{"score": 72}')
        assert result["score"] == 72

    def test_json_invalido_lanza_excepcion(self):
        with pytest.raises(Exception):
            sdr._parse_json_loose("esto no es json")

    def test_json_anidado(self):
        result = sdr._parse_json_loose('{"a": {"b": 2}}')
        assert result["a"]["b"] == 2


# ─── pre_score ────────────────────────────────────────────────────────────────

class TestPreScore:
    def _lead_completo(self):
        return {
            "empresa": "Distribuidora El Pacífico SAC",
            "industria": "Logística",
            "email": "ventas@elpacificosac.pe",
            "telefono": "+51987654321",
            "facturas_pendientes": "45",
            "contacto_nombre": "Carlos Mendoza",
            "cargo": "Gerente General",
        }

    def test_lead_completo_score_alto(self):
        score = sdr.pre_score(self._lead_completo())
        assert score > 40, f"Lead completo debería puntuar >40, obtuvo {score}"

    def test_lead_completo_no_supera_65(self):
        # El pre-score está capeado en 65 para dejar margen al LLM
        score = sdr.pre_score(self._lead_completo())
        assert score <= 65, f"Pre-score no debe superar 65, obtuvo {score}"

    def test_lead_vacio_score_minimo(self):
        score = sdr.pre_score({})
        import config as cfg
        assert score == cfg.ICP["score_weights"]["base"]

    def test_industria_no_objetivo_no_suma(self):
        lead = {"industria": "Minería submarina", "email": "a@b.com",
                "facturas_pendientes": "50", "contacto_nombre": "X"}
        score_sin = sdr.pre_score(lead)
        lead_con = {**lead, "industria": "Logística"}
        score_con = sdr.pre_score(lead_con)
        assert score_con > score_sin

    def test_keyword_excluida_baja_score(self):
        lead_ok = self._lead_completo()
        lead_bad = {**lead_ok, "empresa": "Holding en liquidación SA"}
        assert sdr.pre_score(lead_bad) < sdr.pre_score(lead_ok)

    def test_email_invalido_no_suma(self):
        lead_con = self._lead_completo()
        lead_sin = dict(self._lead_completo())
        lead_sin["email"] = "no-es-email"
        assert sdr.pre_score(lead_con) > sdr.pre_score(lead_sin)

    def test_facturas_altas_suman_mas(self):
        import config as cfg
        lead_bajo = {**self._lead_completo(), "facturas_pendientes": "1"}
        lead_alto = {**self._lead_completo(), "facturas_pendientes": "50"}
        assert sdr.pre_score(lead_alto) > sdr.pre_score(lead_bajo)

    def test_telefono_como_float_string_no_rompe(self):
        # Pandas puede leer el teléfono como "51987654321.0"
        lead = {**self._lead_completo(), "telefono": "51987654321.0"}
        score = sdr.pre_score(lead)
        assert isinstance(score, int)
        assert 0 <= score <= 65
