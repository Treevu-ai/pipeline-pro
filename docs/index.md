---
layout: default
title: Inicio
---

> La **cabecera** de esta página lleva la misma imagen **`readme-hero.png`** como **fondo** (capa + degradado). Eso **no aparece** en la vista README de GitHub — solo en Pages o en `jekyll serve`.

<img class="hero" src="{{ 'assets/readme-hero.png' | relative_url }}" alt="Pipeline_X — banner" width="100%" />

## Qué es esto

**Pipeline_X** (repo **AgentePyme SDR**) automatiza la prospección B2B para **MIPYME en Latinoamérica**: descubre negocios en **Google Maps**, enriquece datos (**SUNAT / web**), **califica con IA** (OpenAI primario, Groq fallback) y genera **borradores** listos para **email y WhatsApp**.

## Flujo rápido

1. **Scrape** — Apify → SerpApi → Google Places → Playwright  
2. **Calificación** — `sdr_agent.py` + `llm_client`  
3. **Outreach piloto** — `scripts/run_outreach_pilot.py` (ángulos A1–A3, gancho A/B, deduplicación de WhatsApp)

## Repo

El código fuente y el `README` principal están en la raíz del repositorio. Esta web es una **vista Jekyll** (tema **Cayman**) para GitHub Pages: activa **Settings → Pages → Deploy from branch → `/docs`**.

**[README principal en GitHub →](https://github.com/Treevu-ai/pipeline-pro/blob/main/README.md)**
