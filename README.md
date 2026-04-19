<!-- La vista README en github.com NO ejecuta Jekyll ni CSS: sin fondos ni animaciones aquí.
     Efectos visuales → GitHub Pages con carpeta `/docs` (véase tabla de estado abajo). -->

<p align="center">
  <img
    src="https://raw.githubusercontent.com/Treevu-ai/pipeline-pro/main/docs/assets/readme-hero.png"
    alt="Pipeline_X — prospección B2B con IA para MIPYME LatAm"
    width="100%"
  />
</p>

<h1 align="center">Pipeline_X · Agente SDR</h1>

<p align="center">
  <strong>Scrape → califica con LLM → borradores email/WhatsApp · Perú & LatAm</strong><br/>
  <sub>OpenAI (<code>gpt-4o-mini</code>) primario · Groq fallback · Green API opcional · API Railway</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-3776AB?logo=python&logoColor=white" alt="Python 3.9+" />
  <img src="https://img.shields.io/badge/OpenAI-chat-412991?logo=openai&logoColor=white" alt="OpenAI" />
  <img src="https://img.shields.io/badge/WhatsApp-Green_API-25D366?logo=whatsapp&logoColor=white" alt="WhatsApp" />
  <img src="https://img.shields.io/badge/GitHub-Pages-Jekyll-CB6297?logo=githubpages&logoColor=white" alt="Jekyll Pages" />
</p>

---

## Estado del proyecto (snapshot)

| Área | Estado |
|------|--------|
| Pipeline scrape + qualify (`pipeline.py`, `sdr_agent.py`) | Estable · LLM OpenAI → Groq |
| API (`api.py`) · `/health` degradado solo por fallos críticos | Producción típica Railway |
| Piloto outreach (`scripts/run_outreach_pilot.py`) | Generación de mensajes + envío WA · **dedup por teléfono PE** (`utils.whatsapp_digits_pe`) · CSV `output/pilot_outreach_batch2.csv` |
| Docs / web | **`docs/`** · Jekyll **Cayman** + CSS propio (`assets/css/style.scss`): cabecera con **imagen de fondo**, degradado y cuerpo con fondo fijo · activar **Settings → Pages → `/docs`** · URL típica: `https://<org>.github.io/<repo>/` |


Roadmap operativo y decisión GO/HOLD: carpeta **`tasks/`** (`todo.md`, `planner-outreach-pilot.md`).

---

## Por qué existe

Las **MIPYME B2B** pierden tiempo armando listas manualmente (Maps, Excel). **Pipeline_X** encuentra negocios con señales **(reseñas, web, ubicación)** y devuelve **CSV enriquecido**, **score 0–100** y **primer contacto personalizado**. El mensaje va al **negocio**, no a una persona inventada.

---

## Inicio rápido

```bash
pip install -r requirements.txt
playwright install chromium    # scraping fallback

# Flujo recomendado: scrape + calificación + HTML
python pipeline.py "estudio contable Lima Peru" --limit 20 --report

# Solo calificar CSV existente · canal WhatsApp
python sdr_agent.py output/leads_raw.csv output/leads_calificados.csv --channel whatsapp --report

# Piloto outreach (tras pick_pilot_leads): generar borradores por ángulo + gancho A/B
python scripts/run_outreach_pilot.py generate output/pilot_outreach_batch2.csv

# Vista previa / envío WhatsApp (Green API) · dedup automático
python scripts/run_outreach_pilot.py send output/pilot_outreach_batch2.csv --dry-run
python scripts/run_outreach_pilot.py send output/pilot_outreach_batch2.csv --confirm   # solo cuando quieras enviar de verdad
```

---

## Entorno: LLM y scraping

| Entorno | LLM | Variables típicas | Scraping (orden de fallback) |
|---------|-----|-------------------|--------------------------------|
| CLI (`pipeline.py`, `sdr_agent.py`) | `llm_client`: OpenAI → Groq | `OPENAI_API_KEY` · opcional `GROQ_API_KEY` | Apify → SerpApi → Google Places API → Playwright |
| API (`api.py`) | Igual | + keys de scraping según uso | Igual cadena |

Sin `OPENAI_API_KEY` y sin `GROQ_API_KEY`, la calificación LLM no arranca.

---

## Configuración

Edita **`config.py`**: `PRODUCT`, `ICP`, `CHANNEL`, **`PLAYBOOK`** (instrucciones sistema). Artefactos en español neutro LatAm:

| Archivo | Uso |
|---------|-----|
| `playbooks/PLAYBOOK_es.md` | Playbook extendido · adaptaciones 🇵🇪 🇨🇴 🇲🇽 |
| `prompts/es_prompts.json` | System · few-shot · variantes país |
| `templates/messages_es.md` | Plantillas email / WhatsApp |

Ejemplo rápido de uso de prompts JSON:

```python
import json
from pathlib import Path
import config as cfg

prompts = json.loads(Path(cfg.PROMPTS_ES).read_text(encoding="utf-8"))
system_prompt = prompts["system"].replace("{PRODUCT}", cfg.PRODUCT["name"])
```

---

## Columnas principales que genera el agente

| Columna | Descripción |
|---------|-------------|
| `crm_stage` | Prospección / Calificado / En seguimiento / Descartado |
| `lead_score` | 0–100 |
| `fit_product` | si · no · dudoso |
| `draft_subject` · `draft_message` | Listos para revisar y enviar |
| `qualify_error` | Vacío si OK |

---

## Sitio web (GitHub Pages + Jekyll) — aquí sí hay “efectos”

GitHub **solo renderiza Markdown** en el README (sin Jekyll ni CSS). Cabecera con imagen de fondo y estilos: **`docs/`** compilado por Jekyll.

### Activar Pages (evitar 404 “There isn't a GitHub Pages site here”)

1. **Settings → Pages → Build and deployment.**  
   Elige **`GitHub Actions`** como **Source** (no “Deploy from a branch”), salvo que sepas usar solo la carpeta `/docs` desde una rama.  
2. Haz **push** a `main`: el workflow **Deploy GitHub Pages (Jekyll)** (`.github/workflows/pages-jekyll.yml`) construye `docs/` y publica el sitio.  
3. URL típica: **`https://<org>.github.io/<repo>/`** · si el repo no es `pipeline-pro`, edita **`docs/_config.yml`** (`baseurl`) y usa la misma ruta en el navegador.

Guía detallada: **`docs/PUBLISH.md`**.

### Qué incluye el sitio

Tema **[Cayman](https://github.com/pages-themes/cayman)** + **`docs/assets/css/style.scss`**: cabecera con **`readme-hero.png`** como fondo y degradado encima.

### Vista previa local

```bash
cd docs
bundle install
bundle exec jekyll serve --livereload --baseurl /pipeline-pro
```

Abre `http://localhost:4000/pipeline-pro/` (cambia `/pipeline-pro` si tu `baseurl` es otro).

---

## Tests

```bash
pytest -q
```

Suite amplia incluye scraper, SDR, playbook en español, outreach piloto (sin LLM en parte de los tests).

---

## Estructura del repositorio

```
agentepyme/
├── pipeline.py           # scrape → qualify en un comando
├── scraper.py · sdr_agent.py · llm_client.py · api.py
├── wa_sender.py          # WhatsApp vía Green API (+ normalización PE)
├── outreach_pilot.py     # Lógica piloto ángulos A/B
├── scripts/
│   ├── run_outreach_pilot.py
│   ├── pick_pilot_leads.py
│   └── validator_summary.py
├── docs/                  # GitHub Pages (Jekyll Cayman)
│   ├── _config.yml
│   ├── index.md
│   ├── Gemfile
│   └── assets/
├── playbooks/ · prompts/ · templates/
├── tasks/                # Planner / backlog campaña
├── tests/
└── output/               # CSV generados (gitignore típico)
```

---

## Licencia

Sin licencia declarada en el repo: uso interno / aclarar con los mantenedores antes de redistribuir.
