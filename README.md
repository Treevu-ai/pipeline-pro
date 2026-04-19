# AgentePyme SDR

Agente SDR para MIPYME en Latinoamérica.
Lee un CSV de leads, los califica con LLM y genera borradores de mensaje listos para enviar.

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

## Entornos, LLM y scraping (matriz rápida)

| Entorno | LLM usado | Variables requeridas | Scraping (orden real de fallback) |
|---|---|---|---|
| CLI local (`sdr_agent.py`, `pipeline.py`) | `llm_client.call()` → OpenAI primario (`gpt-4o-mini`) / Groq fallback | `OPENAI_API_KEY` recomendado; `GROQ_API_KEY` opcional de respaldo | Apify → SerpApi → Google Places API → Playwright |
| API Railway (`api.py`) | OpenAI primario / Groq fallback | `OPENAI_API_KEY` y opcionalmente `GROQ_API_KEY` + vars de bot/webhook | Misma cadena: Apify → SerpApi → Google Places API → Playwright |

Notas:
- Si no hay `GROQ_API_KEY`, se intenta `OPENAI_API_KEY`.
- Si faltan ambas, la calificación LLM falla por configuración.
- Para scraping, si un proveedor no responde o no devuelve resultados, se pasa al siguiente fallback.

## Requisitos

- Python 3.9+
- Al menos una clave de LLM: `GROQ_API_KEY` o `OPENAI_API_KEY`
- `pip install -r requirements.txt`

## Instalación rápida

```bash
pip install -r requirements.txt
playwright install chromium          # navegador para scraping
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
- `CLAUDE` / `GROQ` — modelo, retries, backoff
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
├── config.py             # Configuración de producto, ICP y proveedores LLM
├── requirements.txt
├── playbooks/
│   └── PLAYBOOK_es.md    # Playbook en español LatAm con few-shot y adaptaciones
├── prompts/
│   └── es_prompts.json   # Prompts estructurados en español (system + few-shot)
├── templates/
│   └── messages_es.md    # Plantillas email/WhatsApp formales e informales
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
