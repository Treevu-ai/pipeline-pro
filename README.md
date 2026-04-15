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

## Localización en español

El proyecto incluye una localización completa en español (LatAm) con playbook, prompts y plantillas listas para usar.

### Archivos de localización

| Archivo | Descripción |
|---|---|
| `playbooks/PLAYBOOK_es.md` | Guía maestra del agente: instrucciones del sistema, reglas de scoring, adaptaciones por país (Perú, Colombia, México) y 3 ejemplos few-shot |
| `prompts/es_prompts.json` | System prompt, request_template y ejemplos few-shot en JSON, listos para inyectar al LLM |
| `templates/messages_es.md` | Plantillas de mensajes para email formal, email informal, WhatsApp corto y WhatsApp detallado |

### Cómo usar el playbook en español

1. **Opción rápida** — copia el system prompt de `prompts/es_prompts.json` al campo `PLAYBOOK` en `config.py`:

```python
# config.py
import json
from pathlib import Path

_es = json.loads(Path("prompts/es_prompts.json").read_text())
PLAYBOOK = _es["system"].replace("{PRODUCT}", PRODUCT["name"])
```

2. **Opción por referencia** — la constante `PLAYBOOK_ES` en `config.py` apunta al archivo `playbooks/PLAYBOOK_es.md` para referencia y documentación:

```python
import config as cfg
print(cfg.PLAYBOOK_ES)  # "playbooks/PLAYBOOK_es.md"
```

3. **Plantillas de mensaje** — usa `templates/messages_es.md` como referencia para personalizar los borradores de email y WhatsApp por sector e industria.

### Selección de canal

```bash
# Email (por defecto)
python sdr_agent.py leads.csv output.csv --channel email

# WhatsApp
python sdr_agent.py leads.csv output.csv --channel whatsapp

# Ambos
python sdr_agent.py leads.csv output.csv --channel both
```

### Adaptación por país

| País | Registro fiscal | Tratamiento recomendado |
|---|---|---|
| Perú | RUC / SUNAT | usted (formal); tuteo en WhatsApp informal |
| Colombia | NIT / DIAN | usted (siempre en B2B) |
| México | RFC / SAT | usted (CDMX/centro); tuteo aceptado en norte |

### Tests de localización

```bash
python -m pytest tests/test_playbook_prompts.py -v
```

---

## Estructura

```
agentepyme/
├── pipeline.py           # Orquestador: scrape → califica en un comando
├── scraper.py            # Scraper: Google Maps + sitios web + SUNAT
├── sdr_agent.py          # Calificador LLM: CSV → CSV enriquecido
├── config.py             # Configuración de producto, ICP y Ollama
├── requirements.txt
├── playbooks/
│   └── PLAYBOOK_es.md    # Playbook completo en español (LatAm)
├── prompts/
│   └── es_prompts.json   # System prompt + few-shot examples en JSON
├── templates/
│   └── messages_es.md    # Plantillas de email y WhatsApp en español
├── tests/
│   ├── test_sdr.py       # 26 tests unitarios del agente
│   ├── test_scraper.py   # 21 tests unitarios del scraper
│   └── test_playbook_prompts.py  # 45 tests de localización en español
├── examples/
│   └── leads_input.csv   # 10 leads de ejemplo (MIPYME Perú)
└── output/               # CSVs, reportes y logs se guardan aquí
```
