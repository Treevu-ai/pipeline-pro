"""
tests/test_playbook_prompts.py — Tests automáticos para playbook y prompts en español.

Valida:
- prompts/es_prompts.json existe y es JSON válido con las claves requeridas.
- Cada elemento de few_shot_examples contiene input y output strings.
- Los outputs de los ejemplos few-shot son JSON válido con los campos requeridos.
- La constante PLAYBOOK_ES existe en config.py y apunta a un archivo existente.
- El archivo playbooks/PLAYBOOK_es.md existe y contiene las secciones esperadas.
- El archivo templates/messages_es.md existe y contiene los placeholders esperados.

Ejecutar:
    python -m pytest tests/test_playbook_prompts.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Permite importar módulos desde la raíz del proyecto
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config as cfg

# ─── Rutas a los archivos nuevos ─────────────────────────────────────────────

PROMPTS_PATH = ROOT / "prompts" / "es_prompts.json"
PLAYBOOK_PATH = ROOT / "playbooks" / "PLAYBOOK_es.md"
TEMPLATES_PATH = ROOT / "templates" / "messages_es.md"

# Claves JSON requeridas en el output de cada ejemplo few-shot
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

# Valores válidos por campo en los outputs few-shot
VALID_CRM_STAGES = {"Calificado", "En seguimiento", "Prospección", "Descartado"}
VALID_FIT_PRODUCT = {"si", "no", "dudoso"}
VALID_INTENT_TIMELINE = {"<30d", "30-90d", ">90d", "desconocido"}
VALID_DECISION_MAKER = {"si", "no", "desconocido"}


# ─── Tests: prompts/es_prompts.json ──────────────────────────────────────────

class TestEsPromptsJson:
    """Valida la estructura y contenido de prompts/es_prompts.json."""

    @pytest.fixture(scope="class")
    def prompts_data(self):
        assert PROMPTS_PATH.exists(), f"Archivo no encontrado: {PROMPTS_PATH}"
        with open(PROMPTS_PATH, encoding="utf-8") as f:
            return json.load(f)

    def test_archivo_existe(self):
        assert PROMPTS_PATH.exists(), f"prompts/es_prompts.json no encontrado en {PROMPTS_PATH}"

    def test_es_json_valido(self, prompts_data):
        assert isinstance(prompts_data, dict), "El archivo debe ser un objeto JSON"

    def test_tiene_clave_system(self, prompts_data):
        assert "system" in prompts_data, "Falta la clave 'system'"

    def test_tiene_clave_request_template(self, prompts_data):
        assert "request_template" in prompts_data, "Falta la clave 'request_template'"

    def test_tiene_clave_few_shot_examples(self, prompts_data):
        assert "few_shot_examples" in prompts_data, "Falta la clave 'few_shot_examples'"

    def test_system_es_string_no_vacio(self, prompts_data):
        system = prompts_data["system"]
        assert isinstance(system, str) and len(system) > 0, "'system' debe ser un string no vacío"

    def test_request_template_es_string_no_vacio(self, prompts_data):
        template = prompts_data["request_template"]
        assert isinstance(template, str) and len(template) > 0, "'request_template' debe ser un string no vacío"

    def test_few_shot_examples_es_lista(self, prompts_data):
        assert isinstance(prompts_data["few_shot_examples"], list), "'few_shot_examples' debe ser una lista"

    def test_few_shot_examples_tiene_al_menos_tres(self, prompts_data):
        assert len(prompts_data["few_shot_examples"]) >= 3, "Se requieren al menos 3 ejemplos few-shot"

    def test_cada_ejemplo_tiene_input(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            assert "input" in example, f"Ejemplo {i} no tiene clave 'input'"
            assert isinstance(example["input"], str), f"Ejemplo {i}: 'input' debe ser string"
            assert len(example["input"]) > 0, f"Ejemplo {i}: 'input' no debe estar vacío"

    def test_cada_ejemplo_tiene_output(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            assert "output" in example, f"Ejemplo {i} no tiene clave 'output'"
            assert isinstance(example["output"], str), f"Ejemplo {i}: 'output' debe ser string"
            assert len(example["output"]) > 0, f"Ejemplo {i}: 'output' no debe estar vacío"

    def test_outputs_son_json_valido(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            try:
                parsed = json.loads(example["output"])
            except json.JSONDecodeError as e:
                pytest.fail(f"Ejemplo {i}: 'output' no es JSON válido — {e}")
            assert isinstance(parsed, dict), f"Ejemplo {i}: 'output' debe ser un objeto JSON"

    def test_outputs_tienen_claves_requeridas(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            parsed = json.loads(example["output"])
            missing = REQUIRED_OUTPUT_KEYS - set(parsed.keys())
            assert not missing, f"Ejemplo {i} le faltan claves: {missing}"

    def test_outputs_crm_stage_valido(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            parsed = json.loads(example["output"])
            assert parsed["crm_stage"] in VALID_CRM_STAGES, (
                f"Ejemplo {i}: crm_stage '{parsed['crm_stage']}' no es válido. "
                f"Valores aceptados: {VALID_CRM_STAGES}"
            )

    def test_outputs_lead_score_es_entero_en_rango(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            parsed = json.loads(example["output"])
            score = parsed["lead_score"]
            assert isinstance(score, int), f"Ejemplo {i}: lead_score debe ser entero, obtuvo {type(score)}"
            assert 0 <= score <= 100, f"Ejemplo {i}: lead_score {score} fuera del rango 0-100"

    def test_outputs_fit_product_valido(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            parsed = json.loads(example["output"])
            assert parsed["fit_product"] in VALID_FIT_PRODUCT, (
                f"Ejemplo {i}: fit_product '{parsed['fit_product']}' no es válido"
            )

    def test_outputs_intent_timeline_valido(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            parsed = json.loads(example["output"])
            assert parsed["intent_timeline"] in VALID_INTENT_TIMELINE, (
                f"Ejemplo {i}: intent_timeline '{parsed['intent_timeline']}' no es válido"
            )

    def test_outputs_decision_maker_valido(self, prompts_data):
        for i, example in enumerate(prompts_data["few_shot_examples"]):
            parsed = json.loads(example["output"])
            assert parsed["decision_maker"] in VALID_DECISION_MAKER, (
                f"Ejemplo {i}: decision_maker '{parsed['decision_maker']}' no es válido"
            )

    def test_system_contiene_variables_clave(self, prompts_data):
        system = prompts_data["system"]
        for var in ["{PRODUCT}", "{channel}"]:
            assert var in system, f"'system' debe contener la variable {var}"

    def test_request_template_contiene_variables_clave(self, prompts_data):
        template = prompts_data["request_template"]
        for var in ["{channel}", "{lead_data}", "{pre_score}"]:
            assert var in template, f"'request_template' debe contener la variable {var}"

    def test_tres_ejemplos_cubren_los_tres_escenarios(self, prompts_data):
        """Los 3 ejemplos deben tener crm_stage distintos (alto, medio, descartado)."""
        stages = {json.loads(ex["output"])["crm_stage"] for ex in prompts_data["few_shot_examples"]}
        assert "Calificado" in stages, "Debe haber al menos un ejemplo 'Calificado'"
        assert "Descartado" in stages, "Debe haber al menos un ejemplo 'Descartado'"


# ─── Tests: playbooks/PLAYBOOK_es.md ─────────────────────────────────────────

class TestPlaybookEs:
    """Valida que el playbook en español existe y tiene el contenido esperado."""

    def test_archivo_existe(self):
        assert PLAYBOOK_PATH.exists(), f"playbooks/PLAYBOOK_es.md no encontrado en {PLAYBOOK_PATH}"

    def test_archivo_no_vacio(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert len(content) > 500, "PLAYBOOK_es.md parece estar incompleto (menos de 500 caracteres)"

    def test_contiene_seccion_instruccion_sistema(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "instrucción del sistema" in content.lower(), \
            "Falta sección de instrucción del sistema"

    def test_contiene_adaptaciones_por_pais(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        for pais in ["Perú", "Colombia", "México"]:
            assert pais in content, f"Falta sección de adaptación para {pais}"

    def test_contiene_reglas_de_scoring(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "score" in content.lower(), \
            "Falta sección de reglas de scoring"

    def test_contiene_formato_json_salida(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        for key in ["crm_stage", "lead_score", "draft_message"]:
            assert key in content, f"Falta el campo '{key}' en la sección de formato de salida"

    def test_contiene_ejemplos_few_shot(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "few-shot" in content.lower() or "Ejemplo" in content, \
            "Falta sección de ejemplos few-shot"

    def test_contiene_los_tres_escenarios_en_ejemplos(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "Calificado" in content, "Falta ejemplo 'Calificado' en el playbook"
        assert "Descartado" in content, "Falta ejemplo 'Descartado' en el playbook"
        assert "En seguimiento" in content, "Falta ejemplo 'En seguimiento' en el playbook"

    def test_contiene_variables_documentadas(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        for var in ["{PRODUCT}", "{company}", "{channel}"]:
            assert var in content, f"Variable {var} no está documentada en el playbook"

    def test_contiene_referencias_sunat(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "SUNAT" in content, "Falta referencia a SUNAT (adaptación Perú)"

    def test_contiene_referencias_nit(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "NIT" in content, "Falta referencia a NIT (adaptación Colombia)"

    def test_contiene_referencias_rfc(self):
        content = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "RFC" in content, "Falta referencia a RFC (adaptación México)"


# ─── Tests: templates/messages_es.md ─────────────────────────────────────────

class TestTemplatesEs:
    """Valida que las plantillas de mensajes existen y contienen los elementos esperados."""

    def test_archivo_existe(self):
        assert TEMPLATES_PATH.exists(), f"templates/messages_es.md no encontrado en {TEMPLATES_PATH}"

    def test_archivo_no_vacio(self):
        content = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert len(content) > 200, "messages_es.md parece estar incompleto"

    def test_contiene_plantilla_email(self):
        content = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "email" in content.lower(), "Falta plantilla de email"

    def test_contiene_plantilla_whatsapp(self):
        content = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "whatsapp" in content.lower() or "WhatsApp" in content, \
            "Falta plantilla de WhatsApp"

    def test_contiene_placeholder_company(self):
        content = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "{company}" in content, "Falta placeholder {company}"

    def test_contiene_placeholder_contact_name(self):
        content = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "{contact_name}" in content, "Falta placeholder {contact_name}"

    def test_contiene_placeholder_cta(self):
        content = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "{cta}" in content, "Falta placeholder {cta}"

    def test_contiene_notas_de_localizacion(self):
        content = TEMPLATES_PATH.read_text(encoding="utf-8")
        for pais in ["Perú", "Colombia", "México"]:
            assert pais in content, f"Falta nota de localización para {pais}"


# ─── Tests: config.py — constante PLAYBOOK_ES ────────────────────────────────

class TestConfigPlaybookEs:
    """Valida que config.py tiene la constante PLAYBOOK_ES y que apunta al archivo correcto."""

    def test_constante_playbook_es_existe(self):
        assert hasattr(cfg, "PLAYBOOK_ES"), \
            "config.py no tiene la constante PLAYBOOK_ES"

    def test_playbook_es_es_string(self):
        assert isinstance(cfg.PLAYBOOK_ES, str), \
            "PLAYBOOK_ES debe ser un string con la ruta al archivo"

    def test_playbook_es_apunta_a_archivo_existente(self):
        path = ROOT / cfg.PLAYBOOK_ES
        assert path.exists(), \
            f"El archivo apuntado por PLAYBOOK_ES no existe: {path}"

    def test_playbook_existente_no_cambia_comportamiento_por_defecto(self):
        """PLAYBOOK_ES no debe modificar PLAYBOOK (comportamiento por defecto)."""
        assert hasattr(cfg, "PLAYBOOK"), "La variable PLAYBOOK original debe seguir existiendo"
        assert isinstance(cfg.PLAYBOOK, str) and len(cfg.PLAYBOOK) > 0, \
            "PLAYBOOK original no debe estar vacío"
