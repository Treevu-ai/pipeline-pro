# ACTIVE CAMPAIGN — PIPELINE_X SDR OS (STACK-ALIGNED)

## Campaign Brief
- ICP:
  - Prioridad 1: Estudios contables, agencias y consultorias (canal intermediario).
  - Prioridad 2: MYPE de retail/comercio, construccion/inmobiliaria, logistica/transporte.
- Offer:
  - Pipeline_X automatiza prospeccion B2B: descubre empresas reales, califica con score y redacta primer contacto personalizado.
- Channel:
  - WhatsApp y Email (priorizar WhatsApp cuando exista telefono valido).
- Constraints:
  - Peru primero.
  - No outreach sin personalizacion contextual.
  - No considerar campana exitosa sin evidencia KPI.

## KPI Targets (Validation Phase)
- Contact coverage: >= 60%
- Reply rate: >= 8%
- Qualified rate: >= 20%
- Time-to-first-reply: <= 24h (pilotos)
- Time end-to-end per run (20 leads): <= 35 min

## Data Sources and Execution Contract
- Scraping entrypoint: `pipeline.py`
- Qualification entrypoint: `sdr_agent.py` (`llm_client`: OpenAI primario `gpt-4o-mini`, Groq fallback)
- Fallback scraping chain: Apify -> SerpApi -> Google Places API -> Playwright
- Notion output DB: `Pipeline_X — Leads`
- Campaign evidence files: `output/*.csv`

## Loop (Mandatory)
1. PLANNER
2. EXECUTOR
3. VALIDATOR
4. LEARNING
5. Repeat (or GO/HOLD/PIVOT decision)

## Planner Output (Required Before Send)
- [x] ICP concreto por campana — Batch #2: estudios contables, Lima (Perú)
- [x] Meta cuantitativa del batch — N=20 leads scrape + qualify
- [x] 3 message angles definidos — ver `tasks/planner-outreach-pilot.md`
- [x] Variable de experimento (A/B) definida — mismo doc (hook operativo vs crecimiento)

## Active Tasks
- [x] Definir KPIs de validacion y regla GO/HOLD/PIVOT
- [x] Alinear README con entorno x LLM x scraping
- [x] Ejecutar scraping de validacion y documentar fuente efectiva
- [x] Cargar N=5 pilotos en Notion (`Pipeline_X — Leads`)
- [x] Activar LLM keys (`OPENAI_API_KEY`; opcional `GROQ_API_KEY`) en entorno de prueba — verificado en corrida 2026-04-18 (local)
- [x] Ejecutar corrida completa scrape + qualify (20 leads) y registrar resultados — ver Batch #2
- [ ] Ejecutar outreach batch y registrar replies/no replies/objeciones — lista preparada: `output/pilot_outreach_batch2.csv` (generada con `scripts/pick_pilot_leads.py`); guía `tasks/planner-outreach-pilot.md`
- [ ] Correr VALIDATOR cualitativo: checklist `tasks/validator-checklist.md` + borradores en CSV/HTML; el resumen numérico ya disponible con `scripts/validator_summary.py`
- [ ] Decidir estado de campana: GO / HOLD / PIVOT — evidencia parcial hasta outreach

## Batch Log
- Batch #1
  - Query: `ferreteria lima`
  - Leads scraped: 5
  - Qualification: omitted (`--no-qualify`, missing LLM keys)
  - Effective source: Playwright + Google Maps
  - Notion rows created: 5

- Batch #2 (2026-04-18)
  - Query: `estudio contable Lima Peru`
  - Leads: 20 scrape + 20 qualify
  - Tiempo total pipeline: ~3.5 min (objetivo: <= 35 min)
  - Fuente scrape: Google Places API (Apify respondió 201 pero parse falló por `categoryName` null — corregido en `map_category` / Apify para próxima corrida)
  - Emails en scrape web: 14/20 (~70 % contact coverage a nivel listing)
  - LLM: 20/20 vía OpenAI (`api.openai.com` 200), sin fallback Groq en logs
  - Artefactos: `output/batch_validacion_20_icp_raw.csv`, `output/batch_validacion_20_icp_calificados.csv`, `output/batch_validacion_20_icp_calificados.html`

## Review (2026-04-18)
- Stack LLM: OpenAI (`gpt-4o-mini`) como primario; Groq solo fallback (`llm_client.call`, `call_raw` para batch, Alex en `telegram_bot`, `/health` en API).
- Batch #2 confirma end-to-end scrape → enrich web → qualify en ICP prioritario con tiempos dentro de KPI operativo.
- Piloto outreach: ángulos + A/B en `tasks/planner-outreach-pilot.md`; CSV de trabajo `output/pilot_outreach_batch2.csv` (12 leads, score ≥ 58).

## Decision Log
- 2026-04-18: HOLD (actualizado tras Batch #2)
  - Reason: pipeline y calificación ok en volumen; **aún sin evidencia de outreach** (reply rate, objeciones).
  - Next: definir 3 angles + ejecutar outreach piloto (WhatsApp/email) y registrar métricas; repetir VALIDATOR.

