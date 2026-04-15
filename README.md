# AgentePyme SDR

Agente SDR para MIPYME en Latinoamérica.
Lee un CSV de leads, califica cada uno con un LLM local (Ollama) y genera borradores de mensaje listos para enviar.

## Pipeline completo (recomendado)

```bash
# Un solo comando: busca leads en Google Maps → califica → reporte
python pipeline.py "Retail Lima" --limit 20 --report
python pipeline.py "Logística Bogotá" --limit 30 --workers 2 --channel whatsapp
python pipeline.py "Construcción Trujillo" --limit 25 --enrich-sunat --report
```

O en dos pasos separados:

```bash
# Paso 1: Scraping
python scraper.py "Ferretería Arequipa" --limit 20 --output output/leads_raw.csv

# Paso 2: Calificación
python sdr_agent.py output/leads_raw.csv output/leads_calificados.csv --report
```

---

## Requisitos

- Python 3.9+
- [Ollama](https://ollama.com) corriendo localmente con un modelo descargado
- `pip install -r requirements.txt`

## Instalación rápida

```bash
pip install -r requirements.txt
playwright install chromium          # navegador para scraping
ollama pull mistral:7b-instruct-q4_0 # o el modelo que prefieras
```

## Uso

```bash
# Calificar todos los leads
python sdr_agent.py examples/leads_input.csv output/leads_calificados.csv

# Solo los primeros 5 (para probar)
python sdr_agent.py examples/leads_input.csv output/leads_calificados.csv --max 5

# Retomar sin recalificar los ya procesados
python sdr_agent.py examples/leads_input.csv output/leads_calificados.csv --resume

# Canal WhatsApp
python sdr_agent.py examples/leads_input.csv output/leads_calificados.csv --channel whatsapp

# Generar reporte HTML
python sdr_agent.py examples/leads_input.csv output/leads_calificados.csv --report
```

## Configuración

Edita `config.py` para personalizar:
- `PRODUCT` — nombre, pitch y CTA de tu negocio
- `ICP` — industrias objetivo, umbrales, keywords a excluir
- `OLLAMA` — URL, modelo, timeouts
- `CHANNEL` — canal por defecto (email / whatsapp / both)
- `PLAYBOOK` — instrucciones del sistema para el agente

## Columnas que genera el agente

| Columna | Descripción |
|---|---|
| `crm_stage` | Prospección / Calificado / En seguimiento / Descartado |
| `lead_score` | 0–100 |
| `fit_product` | si / no / dudoso |
| `intent_timeline` | <30d / 30-90d / >90d / desconocido |
| `decision_maker` | si / no / desconocido |
| `blocker` | Obstáculo principal o vacío |
| `next_action` | Acción concreta sugerida |
| `qualification_notes` | Resumen de 2-4 frases |
| `draft_subject` | Asunto del email |
| `draft_message` | Cuerpo del mensaje listo para copiar |
| `qualify_error` | Error técnico si hubo fallo (vacío si OK) |

## Estructura

```
agentepyme/
├── pipeline.py           # Orquestador: scrape → califica en un comando
├── scraper.py            # Scraper: Google Maps + sitios web + SUNAT
├── sdr_agent.py          # Calificador LLM: CSV → CSV enriquecido
├── config.py             # Configuración de producto, ICP y Ollama
├── requirements.txt
├── tests/
│   ├── test_sdr.py              # 26 tests unitarios del agente
│   ├── test_scraper.py          # 21 tests unitarios del scraper
│   └── test_playbook_prompts.py # 82 tests de localización en español
├── playbooks/
│   └── PLAYBOOK_es.md           # Playbook completo en español (LatAm)
├── prompts/
│   └── es_prompts.json          # Prompts JSON con few-shot y variantes por país
├── templates/
│   └── messages_es.md           # Plantillas de mensajes email/WhatsApp en español
├── examples/
│   └── leads_input.csv          # 10 leads de ejemplo (MIPYME Perú)
└── output/                      # CSVs, reportes y logs se guardan aquí
```

---

## Localización en español

El agente incluye una localización completa en español neutro latinoamericano, lista para
usar en Perú, Colombia y México.

### Archivos de localización

| Archivo | Descripción |
|---|---|
| `playbooks/PLAYBOOK_es.md` | Playbook completo: instrucción del sistema, adaptaciones por país, reglas de scoring y 3 ejemplos few-shot |
| `prompts/es_prompts.json` | Prompts en JSON con system prompt, request template, few-shot examples y variantes por país |
| `templates/messages_es.md` | Plantillas de mensajes listos para usar: email formal, email informal, WhatsApp corto y WhatsApp detallado |

### Cómo usar el playbook en español

1. **Cargar el system prompt desde `es_prompts.json`:**

```python
import json, pathlib
import config as cfg

prompts = json.loads(
    pathlib.Path(cfg.PROMPTS_ES).read_text(encoding="utf-8")
)
system_prompt = prompts["system"].replace("{PRODUCT}", cfg.PRODUCT["name"])
```

2. **Seleccionar variante de país** (pe / co / mx):

```python
country = "pe"  # Perú
variation = prompts["country_variations"][country]
print(f"ID fiscal: {variation['fiscal_id']}")  # → RUC
print(f"Tratamiento: {variation['treatment']}")
```

3. **Seleccionar canal de outreach:**

```python
channel = "whatsapp"  # o "email" / "both"
channel_note = prompts["channel_notes"][channel]
```

4. **Incluir ejemplos few-shot** en el user prompt para mejorar la consistencia del LLM:

```python
few_shot = "\n\n".join(
    f"Entrada:\n{ex['input']}\nSalida:\n{ex['output']}"
    for ex in prompts["few_shot_examples"]
)
```

5. **Ejecutar los tests de localización:**

```bash
pytest tests/test_playbook_prompts.py -v
```

### Criterios de calificación (resumen)

| Score | Etapa CRM |
|---|---|
| 70–100 | Calificado |
| 50–69 | En seguimiento |
| 25–49 | Prospección |
| 0–24 | Descartado |

> El comportamiento por defecto del agente **no cambia** si no usas `PLAYBOOK_ES`.
> La localización es opcional y complementaria.
