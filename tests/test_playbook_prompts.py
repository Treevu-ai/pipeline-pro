"""
tests/test_playbook_prompts.py — Tests unitarios para la localización en español.

Verifica que los artefactos de localización (prompts, playbook y plantillas)
estén correctamente creados y sean válidos.

Ejecutar:
    pytest -q tests/test_playbook_prompts.py
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

# ─── Rutas base ────────────────────────────────────────────────────────────────

PROMPTS_PATH = ROOT / "prompts" / "es_prompts.json"
PLAYBOOK_PATH = ROOT / "playbooks" / "PLAYBOOK_es.md"
TEMPLATES_PATH = ROOT / "templates" / "messages_es.md"

# Claves obligatorias en el JSON de prompts
REQUIRED_PROMPT_KEYS = {"system", "request_template", "few_shot_examples"}

# Claves obligatorias en cada salida JSON de los ejemplos few-shot
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


# ─── Fixture: carga el JSON una sola vez ──────────────────────────────────────

@pytest.fixture(scope="module")
def prompts_data() -> dict:
    """Carga y devuelve el contenido de es_prompts.json."""
    with PROMPTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


# ─── Tests: existencia de archivos ────────────────────────────────────────────

class TestArchivosExisten:
    def test_prompts_json_existe(self):
        assert PROMPTS_PATH.exists(), f"No se encontró {PROMPTS_PATH}"

    def test_playbook_es_md_existe(self):
        assert PLAYBOOK_PATH.exists(), f"No se encontró {PLAYBOOK_PATH}"

    def test_templates_messages_es_existe(self):
        assert TEMPLATES_PATH.exists(), f"No se encontró {TEMPLATES_PATH}"


# ─── Tests: es_prompts.json válido ────────────────────────────────────────────

class TestPromptsJson:
    def test_es_json_valido(self):
        """El archivo debe ser JSON parseable."""
        with PROMPTS_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_claves_requeridas(self, prompts_data):
        """Debe contener las claves: system, request_template, few_shot_examples."""
        faltantes = REQUIRED_PROMPT_KEYS - prompts_data.keys()
        assert not faltantes, f"Claves faltantes en es_prompts.json: {faltantes}"

    def test_system_es_cadena_no_vacia(self, prompts_data):
        assert isinstance(prompts_data["system"], str)
        assert len(prompts_data["system"].strip()) > 0

    def test_request_template_es_cadena_no_vacia(self, prompts_data):
        assert isinstance(prompts_data["request_template"], str)
        assert len(prompts_data["request_template"].strip()) > 0

    def test_few_shot_examples_es_lista(self, prompts_data):
        assert isinstance(prompts_data["few_shot_examples"], list)

    def test_few_shot_examples_tiene_al_menos_tres(self, prompts_data):
        assert len(prompts_data["few_shot_examples"]) >= 3, (
            "Se requieren al menos 3 ejemplos few-shot"
        )


# ─── Tests: estructura de each few-shot example ───────────────────────────────

class TestFewShotExamples:
    def test_cada_ejemplo_tiene_input(self, prompts_data):
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            assert "input" in ejemplo, f"Ejemplo {i} no tiene clave 'input'"

    def test_cada_ejemplo_tiene_output(self, prompts_data):
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            assert "output" in ejemplo, f"Ejemplo {i} no tiene clave 'output'"

    def test_input_es_cadena_no_vacia(self, prompts_data):
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            assert isinstance(ejemplo["input"], str), f"Ejemplo {i}: input debe ser str"
            assert len(ejemplo["input"].strip()) > 0, f"Ejemplo {i}: input vacío"

    def test_output_es_cadena_no_vacia(self, prompts_data):
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            assert isinstance(ejemplo["output"], str), f"Ejemplo {i}: output debe ser str"
            assert len(ejemplo["output"].strip()) > 0, f"Ejemplo {i}: output vacío"

    def test_output_es_json_valido(self, prompts_data):
        """Cada output debe ser parseable como JSON."""
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            try:
                json.loads(ejemplo["output"])
            except json.JSONDecodeError as exc:
                pytest.fail(f"Ejemplo {i}: output no es JSON válido — {exc}")

    def test_output_contiene_claves_requeridas(self, prompts_data):
        """Cada output JSON debe tener todas las claves de calificación."""
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            salida = json.loads(ejemplo["output"])
            faltantes = REQUIRED_OUTPUT_KEYS - salida.keys()
            assert not faltantes, (
                f"Ejemplo {i}: claves faltantes en output JSON: {faltantes}"
            )

    def test_crm_stage_valores_validos(self, prompts_data):
        """crm_stage debe ser uno de los valores CRM definidos."""
        valores_validos = {"Calificado", "En seguimiento", "Prospección", "Descartado"}
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            salida = json.loads(ejemplo["output"])
            assert salida["crm_stage"] in valores_validos, (
                f"Ejemplo {i}: crm_stage inválido '{salida['crm_stage']}'"
            )

    def test_lead_score_es_entero_en_rango(self, prompts_data):
        """lead_score debe ser entero entre 0 y 100."""
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            salida = json.loads(ejemplo["output"])
            score = salida["lead_score"]
            assert isinstance(score, int), f"Ejemplo {i}: lead_score debe ser int"
            assert 0 <= score <= 100, f"Ejemplo {i}: lead_score {score} fuera de rango"

    def test_fit_product_valores_validos(self, prompts_data):
        """fit_product debe ser si / no / dudoso."""
        valores_validos = {"si", "no", "dudoso"}
        for i, ejemplo in enumerate(prompts_data["few_shot_examples"]):
            salida = json.loads(ejemplo["output"])
            assert salida["fit_product"] in valores_validos, (
                f"Ejemplo {i}: fit_product inválido '{salida['fit_product']}'"
            )

    def test_ejemplos_cubren_alto_medio_descartado(self, prompts_data):
        """Los ejemplos deben cubrir al menos Calificado, En seguimiento y Descartado."""
        stages = {
            json.loads(e["output"])["crm_stage"]
            for e in prompts_data["few_shot_examples"]
        }
        assert "Calificado" in stages, "Falta ejemplo con crm_stage='Calificado'"
        assert "Descartado" in stages, "Falta ejemplo con crm_stage='Descartado'"
        seguimiento_o_prospeccion = stages & {"En seguimiento", "Prospección"}
        assert seguimiento_o_prospeccion, (
            "Falta ejemplo con crm_stage='En seguimiento' o 'Prospección'"
        )


# ─── Tests: config.PLAYBOOK_ES ────────────────────────────────────────────────

class TestConfigPlaybookES:
    def test_playbook_es_existe_en_config(self):
        """La constante PLAYBOOK_ES debe estar definida en config."""
        assert hasattr(cfg, "PLAYBOOK_ES"), "config.PLAYBOOK_ES no está definida"

    def test_playbook_es_es_cadena(self):
        assert isinstance(cfg.PLAYBOOK_ES, str)

    def test_playbook_es_apunta_al_archivo(self):
        """La ruta en PLAYBOOK_ES debe resolverse al archivo que existe."""
        ruta = ROOT / cfg.PLAYBOOK_ES
        assert ruta.exists(), (
            f"El archivo apuntado por PLAYBOOK_ES no existe: {ruta}"
        )

    def test_playbook_es_no_altera_playbook_default(self):
        """PLAYBOOK (por defecto) debe seguir definido y no ser vacío."""
        assert hasattr(cfg, "PLAYBOOK"), "config.PLAYBOOK fue eliminado"
        assert isinstance(cfg.PLAYBOOK, str)
        assert len(cfg.PLAYBOOK.strip()) > 0, "config.PLAYBOOK está vacío"

    def test_playbook_es_es_distinto_de_playbook_default(self):
        """PLAYBOOK_ES es una ruta de archivo, no el contenido inline del PLAYBOOK."""
        assert cfg.PLAYBOOK_ES != cfg.PLAYBOOK


# ─── Tests: contenido del PLAYBOOK_es.md ─────────────────────────────────────

class TestPlaybookEsMd:
    def test_playbook_no_vacio(self):
        contenido = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert len(contenido.strip()) > 0

    def test_playbook_contiene_variables_clave(self):
        contenido = PLAYBOOK_PATH.read_text(encoding="utf-8")
        for var in ("{PRODUCT}", "{company}", "{contact_name}", "{channel}"):
            assert var in contenido, f"Variable {var} no encontrada en PLAYBOOK_es.md"

    def test_playbook_contiene_adaptaciones_por_pais(self):
        contenido = PLAYBOOK_PATH.read_text(encoding="utf-8")
        for pais in ("Perú", "Colombia", "México"):
            assert pais in contenido, f"Adaptación para {pais} no encontrada"

    def test_playbook_contiene_seccion_scoring(self):
        contenido = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "scoring" in contenido.lower() or "score" in contenido.lower()

    def test_playbook_contiene_ejemplos_few_shot(self):
        contenido = PLAYBOOK_PATH.read_text(encoding="utf-8")
        assert "Calificado" in contenido
        assert "En seguimiento" in contenido
        assert "Descartado" in contenido


# ─── Tests: plantillas de mensajes ────────────────────────────────────────────

class TestTemplatesMessages:
    def test_templates_no_vacio(self):
        contenido = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert len(contenido.strip()) > 0

    def test_templates_contiene_email_formal(self):
        contenido = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "email" in contenido.lower() and "formal" in contenido.lower()

    def test_templates_contiene_whatsapp(self):
        contenido = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "whatsapp" in contenido.lower()

    def test_templates_contiene_firma_equipo(self):
        contenido = TEMPLATES_PATH.read_text(encoding="utf-8")
        assert "Equipo Pipeline_X" in contenido

    def test_templates_contiene_variables_placeholder(self):
        contenido = TEMPLATES_PATH.read_text(encoding="utf-8")
        for var in ("{PRODUCT}", "{company}", "{tu_nombre}", "{cargo}", "{tel}"):
            assert var in contenido, f"Variable {var} no encontrada en messages_es.md"
