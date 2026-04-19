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
- [x] VALIDATOR cuantitativo Batch #2 — `python scripts/validator_summary.py output/batch_validacion_20_icp_calificados.csv --out output/validator_batch2_summary.json` (ejecutado 2026-04-19)
- [ ] VALIDATOR cualitativo — leer 5 `draft_message` al azar del batch calificado + revisar tono de columnas `pilot_whatsapp` en `output/pilot_outreach_batch2.csv` (borradores piloto ya generados)
- [x] Generar borradores piloto (12 filas, ángulos A1–A3 + gancho A/B) — `python scripts/run_outreach_pilot.py generate output/pilot_outreach_batch2.csv` (2026-04-19, 12/12 OK)
- [ ] Enviar outreach (WhatsApp preferente: `scripts/run_outreach_pilot.py send … --dry-run` luego `--confirm`) y completar en CSV: `sent_at`, `channel`, `reply_status`, `reply_at`, `objection`, `notes`
- [ ] Decidir estado de campana: GO / HOLD / PIVOT — requiere evidencia de replies u objeciones tras envío

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

- Piloto outreach Batch #2 (prep 2026-04-18, borradores 2026-04-19)
  - Lista: `output/pilot_outreach_batch2.csv` (12 leads, score ≥ 58)
  - Envío WA: números normalizados a `51…` (móvil 9 dígitos; fijo Lima `(01)` → `511…`); **dedup automático** (slot 3 SyM omitido si coincide con slot 1), ver `utils.whatsapp_digits_pe` + `send`
  - Columnas operativas + mensajes piloto en `pilot_whatsapp` / email; `sent_at` aún vacío hasta envío real
  - Resumen cuantitativo batch base: `output/validator_batch2_summary.json`

## Review (2026-04-19)
- Stack LLM: OpenAI (`gpt-4o-mini`) como primario; Groq solo fallback (`llm_client.call`, `call_raw` para batch, Alex en `telegram_bot`, `/health` en API).
- Batch #2 VALIDATOR automático: N=20, qualify_errors=0, email 70%, lead_score media 69.55, crm_stage repartido (10 Calificado / 7 En seguimiento / 3 Prospección), fit_product todo `si`. Criterio checklist “email >60%” cumplido.
- Piloto: 12 borradores generados con rotación A1/A2/A3 y hook A/B; todos `planned_channel=whatsapp` en esta muestra (teléfonos presentes).
- Pendiente operativo: envío manual supervisado (`send --dry-run` → `--confirm`), registro de replies, KPI `run_outreach_pilot.py kpi`, y lectura cualitativa de 5 borradores si se desea cerrar VALIDATOR al 100%.

## Decision Log
- 2026-04-18: HOLD (tras Batch #2)
  - Reason: pipeline y calificación ok en volumen; sin evidencia de outreach (reply rate, objeciones).

- 2026-04-19: HOLD (actualizado)
  - Reason: instrumentación y borradores de piloto listos; **aún sin envíos ni respuestas registradas** — no hay reply rate medible.
  - Next: ejecutar envíos (WhatsApp), completar columnas de seguimiento en CSV; repetir KPI y decidir GO/HOLD/PIVOT con datos.
