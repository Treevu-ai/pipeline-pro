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
import utils


# ─── utils.normalize ─────────────────────────────────────────────────────────
# _normalize fue movido a utils.normalize — los tests siguen aquí por proximidad.

class TestNormalize:
    def test_quita_acento_simple(self):
        assert utils.normalize("Prospección") == "prospeccion"

    def test_quita_multiple_acentos(self):
        assert utils.normalize("Calificación") == "calificacion"

    def test_lowercase(self):
        assert utils.normalize("CALIFICADO") == "calificado"

    def test_strip_espacios(self):
        assert utils.normalize("  calificado  ") == "calificado"

    def test_cadena_vacia(self):
        assert utils.normalize("") == ""


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

    def test_keyword_excluida_no_afecta_pre_score(self):
        # El pre_score ya no penaliza — eso es trabajo de should_auto_discard.
        # El score de ambos debe ser igual (la keyword no modifica reglas numéricas).
        lead_ok = self._lead_completo()
        lead_bad = {**lead_ok, "empresa": "Holding en liquidación SA"}
        assert sdr.pre_score(lead_bad) == sdr.pre_score(lead_ok)

    def test_email_invalido_no_suma(self):
        lead_con = self._lead_completo()
        lead_sin = dict(self._lead_completo())
        lead_sin["email"] = "no-es-email"
        assert sdr.pre_score(lead_con) > sdr.pre_score(lead_sin)

    def test_resenas_altas_suman_mas(self):
        # facturas_pendientes ya no es una señal del scorecard.
        # La señal correcta son las reseñas de Google Maps.
        lead_bajo = {**self._lead_completo(), "num_resenas": "2"}
        lead_alto = {**self._lead_completo(), "num_resenas": "80"}
        assert sdr.pre_score(lead_alto) > sdr.pre_score(lead_bajo)

    def test_telefono_como_float_string_no_rompe(self):
        # Pandas puede leer el teléfono como "51987654321.0"
        lead = {**self._lead_completo(), "telefono": "51987654321.0"}
        score = sdr.pre_score(lead)
        assert isinstance(score, int)
        assert 0 <= score <= 65


# ─── should_auto_discard ─────────────────────────────────────────────────────

class TestShouldAutoDiscard:
    def test_keyword_holding_descarta(self):
        disc, motivo = sdr.should_auto_discard({"empresa": "Gran Holding SAC"})
        assert disc is True
        assert "holding" in motivo.lower()

    def test_keyword_liquidacion_descarta(self):
        disc, _ = sdr.should_auto_discard({"empresa": "Empresa en liquidación SA"})
        assert disc is True

    def test_sunat_baja_descarta(self):
        disc, motivo = sdr.should_auto_discard({"empresa": "OK Corp", "estado_sunat": "BAJA DEFINITIVA"})
        assert disc is True
        assert "sunat" in motivo.lower()

    def test_sunat_suspension_descarta(self):
        disc, _ = sdr.should_auto_discard({"empresa": "OK Corp", "estado_sunat": "suspensión temporal"})
        assert disc is True

    def test_lead_limpio_no_descarta(self):
        disc, motivo = sdr.should_auto_discard({"empresa": "Distribuidora Lima SAC", "estado_sunat": "ACTIVO"})
        assert disc is False
        assert motivo == ""

    def test_sin_campos_no_descarta(self):
        disc, _ = sdr.should_auto_discard({})
        assert disc is False


# ─── score_drift (clamping) ───────────────────────────────────────────────────

class TestScoreDrift:
    """Verifica que qualify_row clampea el score LLM dentro de [base-20, base+25]."""

    def _make_mock_llm(self, score_to_return: int):
        """Devuelve un callable que simula llm_client.call con score fijo."""
        import config as cfg
        keys = cfg.OUTPUT_KEYS

        def _mock(system, user):
            result = {k: "" for k in keys}
            result["lead_score"] = score_to_return
            result["crm_stage"] = "Calificado"
            result["fit_product"] = "si"
            result["intent_timeline"] = "<30d"
            result["decision_maker"] = "si"
            result["next_action"] = "llamar"
            result["qualification_notes"] = "mock"
            result["draft_message"] = "hola"
            return result

        return _mock

    def test_score_no_supera_base_mas_drift_up(self, monkeypatch):
        import llm_client
        import config as cfg
        base = 40
        monkeypatch.setattr(llm_client, "call", self._make_mock_llm(99))
        result = sdr.qualify_row({"empresa": "Test"}, "whatsapp", base)
        assert result["lead_score"] <= base + cfg.QUALIFICATION["score_drift_up"]

    def test_score_no_baja_mas_de_drift_down(self, monkeypatch):
        import llm_client
        import config as cfg
        base = 50
        monkeypatch.setattr(llm_client, "call", self._make_mock_llm(0))
        result = sdr.qualify_row({"empresa": "Test"}, "whatsapp", base)
        assert result["lead_score"] >= base - cfg.QUALIFICATION["score_drift_down"]

    def test_score_dentro_rango_no_se_modifica(self, monkeypatch):
        import llm_client
        base = 40
        monkeypatch.setattr(llm_client, "call", self._make_mock_llm(55))
        result = sdr.qualify_row({"empresa": "Test"}, "whatsapp", base)
        assert result["lead_score"] == 55
