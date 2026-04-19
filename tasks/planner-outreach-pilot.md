# Planner — Piloto outreach (Batch #2 ICP: estudios contables, Lima)

Propuesta lista para ejecutar el pilot; ajusta tono antes de enviar.

## Ángulos de mensaje (3)

| ID | Gancho | Idea central | CTA sugerido |
|----|--------|--------------|--------------|
| **A1 — Operativo** | Tiempo que el equipo pierde armando listas de pymes en Maps / Excel | Pipeline_X encuentra negocios con señales (reseñas, web, zona) y prioriza para que llamen solo a cuentas con fit | ¿Te mando un ejemplo con 5 empresas de tu zona en 2 minutos? |
| **A2 — Oferta para sus clientes** | Los estudios viven de que sus MIPYME crezcan o renueven servicios | Herramienta para identificar **pymes B2B** donde el cliente del estudio podría vender más (cadena indirecta) | ¿Te interesa ver un flujo pensado para estudios que asesoran MIPYME? |
| **A3 — Credibilidad / datos** | Decisiones en frío sin RUC ni contexto local | Lista calificada con datos verificables y notas por lead, menos “spray and pray” | ¿Te parece si te paso una captura del reporte sin compromiso? |

Rotación sugerida en piloto: **4 contactos por ángulo** si N=12 (asignar `angle_id` en notas al enviar).

## Experimento A/B (una variable)

- **Factor:** primera línea del mensaje (**hook**).
  - **Variante A:** abre con **ahorro de tiempo / operación** (alineado a A1).
  - **Variante B:** abre con **crecimiento de oportunidades para sus clientes / posicionamiento** (alineado a A2).
- **Todo lo demás igual:** mismo producto, mismo CTA corto, mismo canal en cada par A/B (ej. WhatsApp solo).
- **Medición:** reply_rate por variante + etiqueta `reply_sentiment` (positivo/neutral/objeción) en la hoja de seguimiento.

## Canal y volumen

- Preferir **WhatsApp** si hay `telefono` válido; email si solo hay email (ver columna `email`).
- Generar lista de trabajo:
  ```bash
  python scripts/pick_pilot_leads.py output/batch_validacion_20_icp_calificados.csv -n 12 --min-score 58 --out output/pilot_outreach_batch2.csv
  ```
  Ajustar `--min-score` y `-n` según tolerancia al riesgo.

## Registrar resultados (KPI validation)

Por cada fila del CSV piloto ir completando:

- `sent_at` (ISO o fecha corta)
- `channel`: whatsapp | email
- `reply_status`: none | replied | no_reply (a 96h opcional)
- `objection`: texto breve si aplica
- `notes`: variante A/B usada y ángulo (A1/A2/A3)

Objetivo fase validación: **reply rate ≥ 8%** en el conjunto del piloto (ej. ≥1 reply en 12 envíos ya da ~8.3%).

## Referencias

- Checklist sesión: `tasks/validator-checklist.md`
- Resumen cuantitativo: `python scripts/validator_summary.py output/batch_validacion_20_icp_calificados.csv`
