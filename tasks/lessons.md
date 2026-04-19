# LEARNING SYSTEM — PIPELINE_X SDR

## Pattern: No response (cold outreach)
Cause:
- Hook generico o sin contexto real del negocio.

Fix:
- Incluir 1 trigger contextual verificable (rubro, ubicacion, senal operacional).
- Usar CTA suave de diagnostico, no reunion inmediata.

Prevention Rule:
- Cada mensaje debe incluir: contexto especifico + valor concreto + CTA de bajo compromiso.

---

## Pattern: Objection on price/value
Cause:
- Se intenta vender antes de mostrar impacto.

Fix:
- Reformular mensaje con ROI operativo (tiempo ahorrado, calidad de pipeline, foco comercial).

Prevention Rule:
- No mencionar precio antes de explicar beneficio cuantificable o resultado esperado.

---

## Pattern: Campaign appears "active" but no evidence
Cause:
- Se reportan actividades (mensajes enviados) sin KPI comparables.

Fix:
- Registrar por batch: sent, replies, qualified, no-response, objections.
- Comparar contra targets antes de declarar avance.

Prevention Rule:
- Ningun cierre de campana sin evidencia numerica contra KPI target.

---

## Pattern: Mismo telefono duplicado en lista piloto
Cause:
- Google Maps devuelve dos fichas del mismo negocio con el mismo telefono.

Fix:
- Al enviar WA, deduplicar por numero normalizado (primera fila por `pilot_slot` gana); marcar `notes` con `SKIP_WA duplicate_phone` en duplicados.

Prevention Rule:
- Confiar en `run_outreach_pilot.py send` que ya deduplica; revisar dry-run antes de `--confirm`.

---

## Pattern: Segunda corrida send --confirm re-envia duplicado
Cause:
- `seen_digits` solo miraba filas pendientes; si la primera fila del mismo numero ya tenia `sent_at`, el duplicado ya no se detectaba.

Fix:
- Sembrar `seen_digits` con todos los telefonos normalizados de filas que ya tienen `sent_at` antes de armar `pending`.

Prevention Rule:
- Tras fix, una segunda `--confirm` no debe enviar al mismo `519…` dos veces.

---

## Pattern: JSON validator corrupto en Windows al redireccionar stdout
Cause:
- PowerShell `Out-File` o piping sin UTF-8 rompe acentos en JSON del VALIDATOR.

Fix:
- Usar `python scripts/validator_summary.py <csv> --out output/resumen.json` para escribir UTF-8 explícito.

Prevention Rule:
- Para artefactos JSON en este repo, preferir flag `--out` sobre redirección de shell en Windows.

---

## Pattern: Documentation drift (legacy vs real runtime)
Cause:
- README o playbooks no reflejan el flujo real (LLM providers / fallback chain).

Fix:
- Actualizar docs con matriz entorno x LLM x scraping.
- Revisar consistencia docs-codigo en cada iteracion mayor.

Prevention Rule:
- Si cambia comportamiento runtime, actualizar documentacion en la misma iteracion.

---

## Pattern: Low quality lead batch
Cause:
- Priorizacion insuficiente por intencion y fit ICP.

Fix:
- Clasificar leads por High / Medium / Low intent antes de outreach.
- Ejecutar primero High intent.

Prevention Rule:
- No dedicar la mayoria del volumen a low intent.

---

## Pattern: `dict.get("k", default)` no aplica si el JSON trae `k: null`
Cause:
- APIs (p. ej. Apify) devuelven claves con valor `null`; `get` devuelve `None` y el default no se usa, rompiendo `.strip()` u otras asunciones de string.

Fix:
- Usar `d.get("k") or ""` o normalizar con `if x is None: x = ""` al mapear campos externos.

Prevention Rule:
- En mapeo de respuestas JSON de terceros, tratar `null` explícitamente en campos de texto.

---

## Pattern: API token in query string → aparece en logs HTTP
Cause:
- Clientes HTTP en INFO imprimen URL completa; `?token=` queda en Railway/CI/logs.

Fix:
- Apify (y otros): `Authorization: Bearer` en headers; sin token en URL.
- Además `logging_config.silence_sensitive_http_loggers()` después de `basicConfig` en CLIs que usan httpx/OpenAI.

Prevention Rule:
- No usar query param para secretos salvo que la API solo lo permita así; revisar líneas que httpx registre en INFO.

---

## Pattern: `/health` parpadea `degraded` por integración no crítica
Cause:
- Un check opcional (p. ej. Green API) falla en red y el `status` global se marcaba malo aunque DB y LLM estén bien.

Fix:
- `status` **degraded** solo por fallos críticos (DB, ningún LLM usable con keys puestas). Reintentar probes ruidosos (p. ej. `getStateInstance`).

Prevention Rule:
- En health agregado, separar *liveness* de *dependencias best-effort*; no mezclar en un solo bit sin criterio.

---

## Pattern: API key "correcta" pero 401 en el servidor
Cause:
- Valor en el panel con comillas, salto de línea, espacio final, o BOM; en local el `.env` no tenía el mismo carácter.

Fix:
- `utils.clean_env_secret()` al leer `OPENAI_API_KEY` / `GROQ_API_KEY` en clientes y health.
- En hosting: una sola variable, sin comillas en el UI, o re-crear el secret.

Prevention Rule:
- Nunca asumir que "se ve bien" en el formulario; normalizar al leer.
