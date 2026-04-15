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
- `PLAYBOOK_ES` — ruta al playbook en español LatAm (ver sección abajo)

## Localización en español

El repositorio incluye artefactos listos para usar en español neutro de Latinoamérica:

| Archivo | Descripción |
|---|---|
| `playbooks/PLAYBOOK_es.md` | Instrucciones del sistema, adaptaciones por país y ejemplos few-shot |
| `prompts/es_prompts.json` | Prompts estructurados (system, request_template, few_shot_examples) |
| `templates/messages_es.md` | Plantillas de email formal/informal y WhatsApp corto/detallado |

### Uso rápido

**1. Cargar el playbook en español en el agente:**

```python
import config as cfg
from pathlib import Path

# Leer el playbook en español (si existe)
playbook_path = Path(cfg.PLAYBOOK_ES)
if playbook_path.exists():
    playbook_es = playbook_path.read_text(encoding="utf-8")
    # Pasar playbook_es como system prompt al LLM
```

**2. Seleccionar canal al calificar:**

```bash
# Email (por defecto)
python sdr_agent.py leads.csv output/calificados.csv --channel email

# WhatsApp
python sdr_agent.py leads.csv output/calificados.csv --channel whatsapp

# Ambos
python sdr_agent.py leads.csv output/calificados.csv --channel both
```

**3. Adaptaciones por país disponibles en `playbooks/PLAYBOOK_es.md`:**

| País | Registro tributario | Tratamiento recomendado |
|---|---|---|
| 🇵🇪 Perú | SUNAT / RUC | Usted (formal), tú (WhatsApp) |
| 🇨🇴 Colombia | DIAN / NIT | Usted (siempre en B2B) |
| 🇲🇽 México | SAT / RFC | Tú (tech), usted (tradicional) |

**4. Ejecutar tests de localización:**

```bash
pip install -r requirements.txt
pytest -q tests/test_playbook_prompts.py
```

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
├── playbooks/
│   └── PLAYBOOK_es.md    # Playbook en español LatAm con few-shot y adaptaciones
├── prompts/
│   └── es_prompts.json   # Prompts estructurados en español (system + few-shot)
├── templates/
│   └── messages_es.md    # Plantillas email/WhatsApp formales e informales
├── tests/
│   ├── test_sdr.py       # 26 tests unitarios del agente
│   ├── test_scraper.py   # 21 tests unitarios del scraper
│   └── test_playbook_prompts.py  # Tests de localización en español
├── examples/
│   └── leads_input.csv   # 10 leads de ejemplo (MIPYME Perú)
└── output/               # CSVs, reportes y logs se guardan aquí
```
