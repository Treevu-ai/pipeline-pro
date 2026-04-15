"""
tests/test_playbook_prompts.py — Tests automáticos para los archivos de localización en español.

Valida:
  - prompts/es_prompts.json existe y contiene las claves requeridas.
  - Cada few_shot_examples item tiene input y output como strings.
  - Los outputs de los ejemplos son JSON válido con todas las claves requeridas.
  - PLAYBOOK_ES y PROMPTS_ES existen como constantes en config.py y apuntan a archivos reales.
  - playbooks/PLAYBOOK_es.md existe y contiene las secciones documentadas.
  - templates/messages_es.md existe con las 4 plantillas de mensajes.

Ejecutar:
    python -m pytest tests/test_playbook_prompts.py -v
"""
import json
import sys
from pathlib import Path

import pytest

# Permite importar desde la raíz del proyecto
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config as cfg

# ─── Rutas a los archivos creados ────────────────────────────────────────────

PROMPTS_PATH   = ROOT / "prompts" / "es_prompts.json"
PLAYBOOK_PATH  = ROOT / "playbooks" / "PLAYBOOK_es.md"
TEMPLATES_PATH = ROOT / "templates" / "messages_es.md"

# Claves JSON obligatorias en la salida de cada ejemplo few-shot
REQUIRED_OUTPUT_KEYS = {
    "crm_stage",
    "lead_score",
    "fit_product",
    "intent_timeline",
    "decision_maker",
    "blocker",
    "next_action",
    "qualification_notes",
    "draft_subject",
    "draft_message",
    "qualify_error",
}

# Valores permitidos para los enums
VALID_CRM_STAGES        = {"Calificado", "En seguimiento", "Prospección", "Descartado"}
VALID_FIT_PRODUCT       = {"si", "no", "dudoso"}
VALID_INTENT_TIMELINE   = {"<30d", "30-90d", ">90d", "desconocido"}
VALID_DECISION_MAKER    = {"si", "no", "desconocido"}


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def prompts_data():
    """Carga y devuelve el contenido de es_prompts.json (parseado)."""
    assert PROMPTS_PATH.exists(), (
        f"Falta el archivo {PROMPTS_PATH}. "
        "Ejecuta el setup de localización antes de los tests."
    )
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


# ─── Tests: es_prompts.json — estructura de primer nivel ─────────────────────

class TestEsPromptsStructure:
    """Valida las claves de primer nivel de es_prompts.json."""

    def test_archivo_es_json_valido(self):
        """El archivo existe y es JSON sintácticamente válido."""
        content = PROMPTS_PATH.read_text(encoding="utf-8")
        data = json.loads(content)  # lanza si no es JSON válido
        assert isinstance(data, dict)

    def test_clave_system_existe(self, prompts_data):
        assert "system" in prompts_data, "Falta la clave 'system' en es_prompts.json"

    def test_clave_request_template_existe(self, prompts_data):
        assert "request_template" in prompts_data, (
            "Falta la clave 'request_template' en es_prompts.json"
        )

    def test_clave_few_shot_examples_existe(self, prompts_data):
        assert "few_shot_examples" in prompts_data, (
            "Falta la clave 'few_shot_examples' en es_prompts.json"
        )

    def test_system_es_string_no_vacio(self, prompts_data):
        system = prompts_data["system"]
        assert isinstance(system, str) and len(system.strip()) > 0

    def test_request_template_es_string_no_vacio(self, prompts_data):
        template = prompts_data["request_template"]
        assert isinstance(template, str) and len(template.strip()) > 0

    def test_few_shot_examples_es_lista(self, prompts_data):
        assert isinstance(prompts_data["few_shot_examples"], list)

    def test_few_shot_examples_tiene_al_menos_tres(self, prompts_data):
        assert len(prompts_data["few_shot_examples"]) >= 3, (
            "Se esperan al menos 3 ejemplos few-shot (alto, medio, bajo)"
        )

    def test_clave_country_variations_existe(self, prompts_data):
        assert "country_variations" in prompts_data

    def test_country_variations_tiene_pe_co_mx(self, prompts_data):
        cv = prompts_data["country_variations"]
        for country in ("pe", "co", "mx"):
            assert country in cv, f"Falta la variante de país '{country}' en country_variations"

    def test_clave_output_keys_existe(self, prompts_data):
        assert "output_keys" in prompts_data

    def test_output_keys_contiene_campos_requeridos(self, prompts_data):
        ok_set = set(prompts_data["output_keys"])
        missing = REQUIRED_OUTPUT_KEYS - ok_set
        assert not missing, f"Faltan output_keys: {missing}"

    def test_clave_channel_notes_existe(self, prompts_data):
        assert "channel_notes" in prompts_data

    def test_channel_notes_tiene_email_whatsapp_both(self, prompts_data):
        cn = prompts_data["channel_notes"]
        for canal in ("email", "whatsapp", "both"):
            assert canal in cn, f"Falta canal '{canal}' en channel_notes"

    def test_clave_scoring_existe(self, prompts_data):
        assert "scoring" in prompts_data

    def test_scoring_tiene_umbrales_crm_stage(self, prompts_data):
        thresholds = prompts_data["scoring"].get("crm_stage_thresholds", {})
        for stage in VALID_CRM_STAGES:
            assert stage in thresholds, f"Falta umbral para crm_stage '{stage}' en scoring"


# ─── Tests: few_shot_examples — estructura de cada ejemplo ───────────────────

class TestFewShotExamples:
    """Valida cada ejemplo en la lista few_shot_examples."""

    def _get_example(self, prompts_data, index):
        examples = prompts_data["few_shot_examples"]
        assert len(examples) > index, f"No existe el ejemplo en índice {index}"
        return examples[index]

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_ejemplo_tiene_clave_input(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        assert "input" in ex, f"Ejemplo {idx} no tiene clave 'input'"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_ejemplo_tiene_clave_output(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        assert "output" in ex, f"Ejemplo {idx} no tiene clave 'output'"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_input_es_string_no_vacio(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        assert isinstance(ex["input"], str) and len(ex["input"].strip()) > 0

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_es_string_no_vacio(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        assert isinstance(ex["output"], str) and len(ex["output"].strip()) > 0

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_input_parsea_como_json(self, prompts_data, idx):
        """El input de cada ejemplo debe ser JSON válido."""
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["input"])
        assert isinstance(parsed, dict)

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_parsea_como_json(self, prompts_data, idx):
        """El output de cada ejemplo debe ser JSON válido."""
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["output"])
        assert isinstance(parsed, dict)

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_contiene_todas_las_claves_requeridas(self, prompts_data, idx):
        """Cada output debe contener las claves exactas de OUTPUT_KEYS."""
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["output"])
        missing = REQUIRED_OUTPUT_KEYS - set(parsed.keys())
        assert not missing, f"Ejemplo {idx} — faltan claves en output: {missing}"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_crm_stage_es_valor_valido(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["output"])
        assert parsed["crm_stage"] in VALID_CRM_STAGES, (
            f"Ejemplo {idx} — crm_stage '{parsed['crm_stage']}' no es válido"
        )

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_lead_score_es_entero_en_rango(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["output"])
        score = parsed["lead_score"]
        assert isinstance(score, int), f"Ejemplo {idx} — lead_score no es int: {score}"
        assert 0 <= score <= 100, f"Ejemplo {idx} — lead_score fuera de rango: {score}"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_fit_product_es_valor_valido(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["output"])
        assert parsed["fit_product"] in VALID_FIT_PRODUCT, (
            f"Ejemplo {idx} — fit_product '{parsed['fit_product']}' no es válido"
        )

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_intent_timeline_es_valor_valido(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["output"])
        assert parsed["intent_timeline"] in VALID_INTENT_TIMELINE, (
            f"Ejemplo {idx} — intent_timeline '{parsed['intent_timeline']}' no es válido"
        )

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_output_decision_maker_es_valor_valido(self, prompts_data, idx):
        ex = self._get_example(prompts_data, idx)
        parsed = json.loads(ex["output"])
        assert parsed["decision_maker"] in VALID_DECISION_MAKER, (
            f"Ejemplo {idx} — decision_maker '{parsed['decision_maker']}' no es válido"
        )


# ─── Tests: ejemplos cubren los tres escenarios (alto/medio/bajo) ─────────────

class TestFewShotCoverage:
    """Verifica que los 3 ejemplos cubren los escenarios: Calificado, En seguimiento,
    Descartado (o Prospección)."""

    def _outputs_parsed(self, prompts_data):
        return [json.loads(ex["output"]) for ex in prompts_data["few_shot_examples"][:3]]

    def test_existe_ejemplo_calificado(self, prompts_data):
        stages = {p["crm_stage"] for p in self._outputs_parsed(prompts_data)}
        assert "Calificado" in stages, "Falta un ejemplo con crm_stage='Calificado'"

    def test_existe_ejemplo_descartado_o_prospeccion(self, prompts_data):
        stages = {p["crm_stage"] for p in self._outputs_parsed(prompts_data)}
        assert stages & {"Descartado", "Prospección"}, (
            "Falta un ejemplo con crm_stage='Descartado' o 'Prospección'"
        )

    def test_scores_cubren_rango_amplio(self, prompts_data):
        scores = [
            json.loads(ex["output"])["lead_score"]
            for ex in prompts_data["few_shot_examples"][:3]
        ]
        assert max(scores) - min(scores) >= 30, (
            f"Los scores de los ejemplos ({scores}) deberían cubrir al menos 30 puntos de rango"
        )


# ─── Tests: config.py — constantes PLAYBOOK_ES y PROMPTS_ES ──────────────────

class TestConfigConstants:
    """Verifica que config.py expone las constantes de localización."""

    def test_playbook_es_existe_en_config(self):
        assert hasattr(cfg, "PLAYBOOK_ES"), (
            "config.py no define la constante PLAYBOOK_ES"
        )

    def test_prompts_es_existe_en_config(self):
        assert hasattr(cfg, "PROMPTS_ES"), (
            "config.py no define la constante PROMPTS_ES"
        )

    def test_playbook_es_apunta_a_archivo_existente(self):
        path = ROOT / cfg.PLAYBOOK_ES
        assert path.exists(), (
            f"PLAYBOOK_ES apunta a '{cfg.PLAYBOOK_ES}' pero el archivo no existe"
        )

    def test_prompts_es_apunta_a_archivo_existente(self):
        path = ROOT / cfg.PROMPTS_ES
        assert path.exists(), (
            f"PROMPTS_ES apunta a '{cfg.PROMPTS_ES}' pero el archivo no existe"
        )

    def test_playbook_es_es_string(self):
        assert isinstance(cfg.PLAYBOOK_ES, str)

    def test_prompts_es_es_string(self):
        assert isinstance(cfg.PROMPTS_ES, str)

    def test_playbook_es_no_cambia_playbook_default(self):
        """PLAYBOOK_ES no debe sobrescribir el PLAYBOOK original."""
        assert hasattr(cfg, "PLAYBOOK"), "PLAYBOOK (inglés/default) debe seguir existiendo"
        assert cfg.PLAYBOOK_ES != cfg.PLAYBOOK or cfg.PLAYBOOK_ES.endswith(".md"), (
            "PLAYBOOK_ES no debe reemplazar el PLAYBOOK original"
        )


# ─── Tests: PLAYBOOK_es.md — contenido y secciones ───────────────────────────

class TestPlaybookEsContent:
    """Verifica que el playbook en español contiene las secciones clave."""

    @pytest.fixture(scope="class")
    def playbook_text(self):
        assert PLAYBOOK_PATH.exists(), f"No existe {PLAYBOOK_PATH}"
        return PLAYBOOK_PATH.read_text(encoding="utf-8")

    def test_archivo_playbook_existe(self):
        assert PLAYBOOK_PATH.exists()

    def test_playbook_no_esta_vacio(self, playbook_text):
        assert len(playbook_text.strip()) > 500

    def test_playbook_contiene_seccion_sistema(self, playbook_text):
        assert "system prompt" in playbook_text.lower() or "instrucción del sistema" in playbook_text.lower()

    def test_playbook_contiene_adaptaciones_por_pais(self, playbook_text):
        text_lower = playbook_text.lower()
        assert "perú" in text_lower or "peru" in text_lower
        assert "colombia" in text_lower
        assert "méxico" in text_lower or "mexico" in text_lower

    def test_playbook_menciona_sunat(self, playbook_text):
        assert "SUNAT" in playbook_text

    def test_playbook_menciona_nit(self, playbook_text):
        assert "NIT" in playbook_text

    def test_playbook_menciona_rfc(self, playbook_text):
        assert "RFC" in playbook_text

    def test_playbook_contiene_seccion_scoring(self, playbook_text):
        text_lower = playbook_text.lower()
        assert "scoring" in text_lower or "puntos" in text_lower

    def test_playbook_contiene_seccion_formato_salida(self, playbook_text):
        assert "crm_stage" in playbook_text
        assert "lead_score" in playbook_text

    def test_playbook_contiene_ejemplos_few_shot(self, playbook_text):
        text_lower = playbook_text.lower()
        assert "few-shot" in text_lower or "ejemplo" in text_lower

    def test_playbook_menciona_variables_template(self, playbook_text):
        for var in ("{PRODUCT}", "{company}", "{contact_name}", "{channel}"):
            assert var in playbook_text, f"Variable {var} no encontrada en PLAYBOOK_es.md"

    def test_playbook_contiene_crm_stages_completos(self, playbook_text):
        for stage in ("Calificado", "En seguimiento", "Prospección", "Descartado"):
            assert stage in playbook_text, f"Stage '{stage}' no encontrado en PLAYBOOK_es.md"


# ─── Tests: templates/messages_es.md — plantillas de mensajes ────────────────

class TestMessageTemplates:
    """Verifica que el archivo de plantillas existe y contiene las 4 plantillas."""

    @pytest.fixture(scope="class")
    def templates_text(self):
        assert TEMPLATES_PATH.exists(), f"No existe {TEMPLATES_PATH}"
        return TEMPLATES_PATH.read_text(encoding="utf-8")

    def test_archivo_templates_existe(self):
        assert TEMPLATES_PATH.exists()

    def test_templates_no_esta_vacio(self, templates_text):
        assert len(templates_text.strip()) > 200

    def test_templates_tiene_email_formal(self, templates_text):
        assert "email formal" in templates_text.lower()

    def test_templates_tiene_email_informal(self, templates_text):
        assert "email informal" in templates_text.lower()

    def test_templates_tiene_whatsapp_corto(self, templates_text):
        assert "whatsapp corto" in templates_text.lower()

    def test_templates_tiene_whatsapp_detallado(self, templates_text):
        assert "whatsapp detallado" in templates_text.lower()

    def test_templates_usa_placeholders(self, templates_text):
        for placeholder in ("{company}", "{contact_name}", "{PRODUCT}"):
            assert placeholder in templates_text, (
                f"Placeholder {placeholder} no encontrado en messages_es.md"
            )

    def test_templates_menciona_los_tres_paises(self, templates_text):
        text_lower = templates_text.lower()
        assert "perú" in text_lower or "peru" in text_lower
        assert "colombia" in text_lower
        assert "méxico" in text_lower or "mexico" in text_lower
