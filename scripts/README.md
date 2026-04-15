# scripts/ — Utilidades operativas

## test_apify_call.py — Diagnóstico de la integración con Apify

Script de diagnóstico para verificar que la llamada al actor
`compass~crawler-google-places` de Apify funciona correctamente desde tu
entorno. Imprime el status HTTP, headers relevantes y un preview del body
**sin exponer el token**.

---

### Requisitos

| Herramienta | Versión mínima |
|-------------|---------------|
| Python      | 3.9+          |
| httpx       | 0.24+         |

---

### 1 — Bash / Linux / macOS (local)

```bash
# 1. Clona el repo (si no lo tienes)
git clone https://github.com/Treevu-ai/pipeline-pro.git
cd pipeline-pro

# 2. Instala httpx (en venv para no tocar el entorno global)
python3 -m venv .venv
source .venv/bin/activate
pip install httpx

# 3. Exporta la clave (en la MISMA terminal, NO la pegues en el chat)
export APIFY_API_KEY="tu_token_aqui"

# 4. Ejecuta el diagnóstico
python3 scripts/test_apify_call.py "Abogados en Lima"
```

---

### 2 — PowerShell (Windows)

```powershell
# 1. Abre PowerShell como usuario normal (no requiere admin)
cd pipeline-pro

# 2. Crea y activa el entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Instala httpx
pip install httpx

# 4. Exporta la clave (solo en esta sesión, sin persistirla)
$env:APIFY_API_KEY = "tu_token_aqui"

# 5. Ejecuta el diagnóstico
python scripts/test_apify_call.py "Abogados en Lima"
```

---

### 3 — Docker (sin instalar dependencias globalmente) ✅ Recomendado

```bash
# Requiere solo Docker instalado en el host

export APIFY_API_KEY="tu_token_aqui"

docker run --rm \
  -e APIFY_API_KEY \
  -v "$(pwd)/scripts:/scripts:ro" \
  python:3.11-slim \
  bash -c "pip install --quiet httpx && python /scripts/test_apify_call.py 'Abogados en Lima'"
```

O bien, usando el target del Makefile (ver sección Makefile más abajo):

```bash
export APIFY_API_KEY="tu_token_aqui"
make scripts/test-apify QUERY="Abogados en Lima"
```

---

### 4 — Kubernetes (pod temporal)

```bash
# Crea un pod efímero con la key como variable de entorno
kubectl run apify-diag --rm -it --restart=Never \
  --image=python:3.11-slim \
  --env="APIFY_API_KEY=${APIFY_API_KEY}" \
  -- bash -c "
    pip install --quiet httpx
    python - <<'EOF'
$(cat scripts/test_apify_call.py)
EOF
" -- "Abogados en Lima"
```

---

### Makefile target

El `Makefile` en la raíz del repo incluye el target `scripts/test-apify`:

```bash
# Variable QUERY es opcional; por defecto usa "Abogados en Lima"
export APIFY_API_KEY="tu_token_aqui"
make scripts/test-apify
make scripts/test-apify QUERY="Ferreterías en Bogotá"
```

---

### Qué pegar en el chat para diagnóstico

Copia y pega **únicamente** la salida del script (líneas `[diag] ...`).
Ejemplo de salida esperada (exitosa):

```
[diag] URL   : https://api.apify.com/v2/acts/compass~crawler-google-places/run-sync-get-dataset-items?timeout=60&memory=512&token=<REDACTED>
[diag] Query : Abogados en Lima
[diag] Body  : {"searchStringsArray": ["Abogados en Lima"], ...}

[diag] Status : 200 OK
[diag] Header  content-type: application/json; charset=utf-8
[diag] Header  x-request-id: abc123

[diag] Body (12345 chars):
[{"title": "Estudio García ...", "address": "Av. ...", ...}, ...]

[diag] OK — se recibieron 20 items.
```

#### Interpretación de status codes

| Status | Significado | Acción |
|--------|-------------|--------|
| 200    | Éxito       | Revisar cantidad de items |
| 400    | Parámetros incorrectos | Revisar body del request |
| 401    | Token inválido o expirado | Regenerar APIFY_API_KEY |
| 402    | Créditos agotados | Recargar cuenta Apify |
| 403    | Sin permisos | Verificar acceso al actor |
| 429    | Rate limit | Esperar y reintentar |
| 5xx    | Error servidor Apify | Reintentar más tarde |

---

### Seguridad 🔐

- **Nunca** incluyas `APIFY_API_KEY` en el chat, en commits ni en logs.
- Usa `export` en la terminal actual; no la escribas en archivos `.env` que
  puedan subirse al repo.
- El script redacta el token automáticamente en su salida (`<REDACTED>`).
- Si sospechas que el token fue expuesto, revócalo en
  [https://console.apify.com/account/integrations](https://console.apify.com/account/integrations)
  y genera uno nuevo.
