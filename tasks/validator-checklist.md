# Checklist VALIDATOR (post-batch calificado)

Usar después de una corrida `pipeline.py` / `sdr_agent.py` con CSV `*_calificados.csv`.

## 1. Preparación (5 min)

- [ ] Tener a mano el CSV y el HTML si existe (`*_calificados.html`).
- [ ] (Opcional piloto) Generar lista priorizada para contactar:
  ```bash
  python scripts/pick_pilot_leads.py output/<batch>_calificados.csv -n 12 --min-score 58 --out output/pilot_outreach_batch2.csv
  ```
- [ ] Ejecutar resumen automático:
  ```bash
  python scripts/validator_summary.py output/<tu_batch>_calificados.csv
  ```
  Opcional JSON: `python scripts/validator_summary.py output/<archivo>.csv --json > output/validator_resumen.json`
- [ ] Anotar **N**, **% con email**, **media/mediana de `lead_score`**, **errores `qualify_error`**.

## 2. Calidad del batch (15–20 min)

- [ ] **Distribución `crm_stage`**: ¿hay demasiados Descartado o todo en Prospección sin matices?
- [ ] **`fit_product`**: ¿ratio razonable si/no/dudoso para el ICP elegido?
- [ ] **`intent_timeline`**: ¿demasiados “desconocido” o largo plazo sin justificación?
- [ ] **Top / bottom por score**: ¿los top tienen sentido comercial? ¿los bottom son ruido esperado?
- [ ] Leer **5 borradores** (`draft_message`) al azar: tono, personalización, CTA alineado con playbook.
- [ ] **Errores técnicos**: si `qualify_error` > 0, priorizar corrección antes del siguiente batch.

## 3. Definir experimento de outreach (10 min)

- [ ] Escribir **3 ángulos de mensaje** distintos (gancho + valor + CTA bajo compromiso).
- [ ] Elegir **una variable A/B** (ej. gancho dolor vs. gancho oportunidad; largo del mensaje).
- [ ] Decidir **canal piloto** (WhatsApp / email) y **tamaño** (ej. 10–15 cuentas high/medium).

## 4. Cierre

- [ ] Actualizar `tasks/todo.md` (Batch log + decisiones).
- [ ] Si hay evidencia suficiente: marcar siguiente paso outreach; si no, HOLD con razón explícita.

## Criterios rápidos GO / HOLD

| Señal | Acción sugerida |
|------|------------------|
| Media score coherente, drafts útiles, email >60% | Avanzar a outreach piloto |
| Muchos `dudoso` + timelines vacíos | Ajustar playbook / query de scrape antes de enviar |
| `qualify_error` >10% o scores todos iguales | Revisar LLM / datos de entrada |
