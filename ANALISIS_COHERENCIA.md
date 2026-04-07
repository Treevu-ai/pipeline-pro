# Análisis de Coherencia y Consistencia Lógica - AgentePyme SDR

## Resumen Ejecutivo

El códigobase es funcional pero presenta varias inconsistencias lógicas, problemas de arquitectura y oportunidades de mejora. A continuación se detallan los hallazgos por categoría.

---

## 1. Inconsistencias de Nomenclatura y Datos

### 1.1 Nombres de columnas inconsistentes

**Problema:** Diferentes scripts usan nombres de columnas diferentes para el mismo concepto.

| Concepto | scraper.py | sdr_agent.py | contact_enricher.py |
|----------|------------|--------------|---------------------|
| Nombre contacto | `contacto_nombre` | `contacto_nombre` / `contact_name` | `contacto_nombre` |
| Cargo | `cargo` | `cargo` / `position` | `cargo` |
| Teléfono | `telefono` | `telefono` / `phone` | `telefono` |
| Sitio web | `sitio_web` | No usado | `sitio_web` |

**Impacto:** El código en `sdr_agent.py` líneas 77-78 y 81-85 intenta leer múltiples variantes de nombres de columna, lo que indica inconsistencia en los datos de entrada.

**Recomendación:**
```python
# Crear un módulo constants.py con nombres de columna estandarizados
COLUMN_NAMES = {
    "empresa": "empresa",
    "industria": "industria",
    "ruc": "ruc",
    "email": "email",
    "telefono": "telefono",
    "ciudad": "ciudad",
    "pais": "pais",
    "facturas_pendientes": "facturas_pendientes",
    "contacto_nombre": "contacto_nombre",
    "cargo": "cargo",
    "sitio_web": "sitio_web",
    "crm_stage": "crm_stage",
}
```

### 1.2 Normalización inconsistente

**Problema:** La función `_normalize()` se define en múltiples archivos con implementaciones similares pero no centralizadas.

- `scraper.py` línea 71
- `sdr_agent.py` línea 95
- `contact_enricher.py` línea 32

**Recomendación:** Crear un módulo `utils.py` con funciones comunes.

---

## 2. Problemas de Arquitectura

### 2.1 Acoplamiento entre módulos

**Problema:** `pipeline.py` ejecuta scripts como subprocesos en lugar de importarlos como módulos.

```python
# pipeline.py líneas 87-101
scrape_cmd = [
    sys.executable, "scraper.py",
    args.query,
    # ...
]
code = run(scrape_cmd, "SCRAPE")
```

**Impacto:**
- Pérdida de contexto y manejo de errores
- Dificultad para testing
- Sobrecarga de procesos
- No se pueden compartir objetos en memoria

**Recomendación:**
```python
# Importar funciones directamente
from scraper import scrape_google_maps, enrich_leads, save_leads
from sdr_agent import qualify_leads

# Usarlas en el mismo proceso
leads = scrape_google_maps(args.query, args.limit)
leads = enrich_leads(leads, use_sunat=args.enrich_sunat)
qualified = qualify_leads(leads, channel=args.channel)
```

### 2.2 Falta de abstracción de datos

**Problema:** No hay una clase o estructura de datos para representar un Lead. Todo se maneja como diccionarios.

**Impacto:**
- No hay validación de tipos
- Fácil introducir errores tipográficos en nombres de campos
- Difícil mantener invariantes

**Recomendación:**
```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class Lead:
    empresa: str
    industria: str
    ruc: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    ciudad: Optional[str] = None
    pais: str = "Peru"
    facturas_pendientes: int = 0
    contacto_nombre: Optional[str] = None
    cargo: Optional[str] = None
    sitio_web: Optional[str] = None

    # Campos de calificación
    crm_stage: str = "Prospección"
    lead_score: int = 0
    fit_product: str = "dudoso"
    # ... más campos

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Lead":
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
```

---

## 3. Problemas de Lógica de Negocio

### 3.1 Pre-scoring inconsistente con ICP

**Problema:** El pre-scoring en `sdr_agent.py` líneas 54-92 tiene lógica que no coincide con el ICP definido en `config.py`.

**config.py define:**
```python
ICP = {
    "target_industries": ["Retail", "Comercio", "Logística", ...],
    "min_invoices_pending": 5,
    "high_value_invoices": 30,
    "excluded_keywords": ["holding", "SAC inactiva", "en liquidación"],
    "score_weights": {
        "industry_match": 15,
        "invoices_high": 15,
        "invoices_low": 8,
        "has_email": 12,
        "has_phone": 8,
        "has_contact": 7,
        "has_cargo": 5,
        "base": 5,
    },
}
```

**Problema en sdr_agent.py línea 88:**
```python
if any(kw.lower() in empresa for kw in cfg.ICP["excluded_keywords"]):
    score = max(0, score - 40)
```

**Inconsistencia:** La penalización de -40 puntos no está documentada en `config.py` y puede causar scores negativos que luego se capean a 0.

**Recomendación:**
```python
# Agregar a config.py
ICP = {
    # ... campos existentes ...
    "exclusion_penalty": 40,  # Documentar la penalización
}
```

### 3.2 Lógica de "should_skip" confusa

**Problema:** La función `should_skip` en `sdr_agent.py` líneas 101-104 tiene lógica confusa.

```python
_INITIAL_STAGES = {_normalize(s) for s in ("", "Pendiente", "Prospección", "Prospeccion")}

def should_skip(row: dict) -> bool:
    stage = _normalize(str(row.get("crm_stage", "")))
    return bool(stage) and stage not in _INITIAL_STAGES
```

**Problema:**
- `"Pendiente"` está en `_INITIAL_STAGES` pero no se menciona en la documentación
- La lógica dice "skip si stage está en initial_stages" pero el código hace lo contrario
- No está claro qué etapas se consideran "iniciales"

**Recomendación:**
```python
# Definir claramente las etapas
CRM_STAGES = {
    "PROSPECCION": "Prospección",
    "QUALIFIED": "Calificado",
    "FOLLOW_UP": "En seguimiento",
    "DISCARDED": "Descartado",
}

# Etapas que indican que ya fue procesado
PROCESSED_STAGES = {CRM_STAGES["QUALIFIED"], CRM_STAGES["FOLLOW_UP"], CRM_STAGES["DISCARDED"]}

def should_skip(row: dict) -> bool:
    """Devuelve True si el lead ya fue calificado previamente."""
    stage = _normalize(str(row.get("crm_stage", "")))
    return stage in PROCESSED_STAGES
```

### 3.3 Enriquecimiento de contactos no integrado en el pipeline

**Problema:** `contact_enricher.py` es un script separado que no está integrado en `pipeline.py`.

**Impacto:** El usuario tiene que ejecutar manualmente el enriquecimiento después del pipeline.

**Recomendación:** Agregar opción al pipeline:
```python
# pipeline.py
p.add_argument("--enrich-contacts", action="store_true",
               help="Enriquecer contactos con emails personales y redes sociales")
```

---

## 4. Problemas de Manejo de Errores

### 4.1 Manejo de errores inconsistente

**Problema:** Diferentes scripts manejan errores de manera diferente.

| Script | Manejo de errores |
|--------|-------------------|
| `pipeline.py` | Exit code del subproceso |
| `sdr_agent.py` | Try/except con logging, continúa procesando |
| `contact_enricher.py` | Try/except con logging, devuelve vacío |
| `scraper.py` | Try/except con logging, continúa |

**Recomendación:** Estandarizar el manejo de errores con una estrategia clara:
```python
# utils.py
class LeadProcessingError(Exception):
    """Base exception for lead processing errors."""
    pass

class ScrapingError(LeadProcessingError):
    """Error during scraping."""
    pass

class QualificationError(LeadProcessingError):
    """Error during qualification."""
    pass

class EnrichmentError(LeadProcessingError):
    """Error during enrichment."""
    pass
```

### 4.2 Falta de validación de entrada

**Problema:** No hay validación de los datos de entrada en ningún script.

**Ejemplo:** `sdr_agent.py` asume que el CSV tiene ciertas columnas sin validar.

**Recomendación:**
```python
def validate_lead_data(data: dict) -> list[str]:
    """Valida los datos de un lead y devuelve una lista de errores."""
    errors = []

    if not data.get("empresa"):
        errors.append("Falta campo 'empresa'")

    email = data.get("email", "")
    if email and "@" not in email:
        errors.append(f"Email inválido: {email}")

    # ... más validaciones

    return errors
```

---

## 5. Problemas de Performance

### 5.1 Procesamiento secuencial en contact_enricher.py

**Problema:** `enrich_leads` procesa los leads secuencialmente sin paralelismo.

```python
# contact_enricher.py líneas 392-402
def enrich_leads(leads: list[dict], delay: float = 1.0, headful: bool = False) -> list[dict]:
    enriched = []
    for i, lead in enumerate(leads):
        enriched_lead = enrich_lead(lead, delay, headful)
        enriched.append(enriched_lead)
    return enriched
```

**Impacto:** Para 100 leads con delay de 1s, toma 100 segundos mínimo.

**Recomendación:** Agregar paralelismo similar a `sdr_agent.py`:
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def enrich_leads(leads: list[dict], delay: float = 1.0, headful: bool = False, workers: int = 1) -> list[dict]:
    if workers == 1:
        return [enrich_lead(lead, delay, headful) for lead in leads]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(enrich_lead, lead, delay, headful): i
                  for i, lead in enumerate(leads)}
        results = [None] * len(leads)
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
        return results
```

### 5.2 Búsqueda de Google ineficiente

**Problema:** `_find_website_async` abre un nuevo navegador para cada búsqueda.

**Impacto:** Muy lento para múltiples leads.

**Recomendación:** Reutilizar el contexto del navegador:
```python
async def find_websites_batch(queries: list[tuple[str, str]], headful: bool = False) -> list[str]:
    """Busca múltiples sitios web reutilizando el navegador."""
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        for empresa, ciudad in queries:
            # ... lógica de búsqueda ...
            results.append(website)

        await browser.close()
    return results
```

---

## 6. Problemas de Configuración

### 6.1 Configuración hardcoded

**Problema:** Muchos valores están hardcoded en lugar de estar en `config.py`.

**Ejemplos:**
- `contact_enricher.py` línea 55: `BLACKLIST_DOMAINS`
- `contact_enricher.py` líneas 131-135: `PHONE_PATTERNS`
- `contact_enricher.py` líneas 161-183: `SOCIAL_PATTERNS`

**Recomendación:** Mover a `config.py`:
```python
# config.py
ENRICHMENT = {
    "blacklist_domains": {
        "sentry.io", "example.com", "wixpress.com", "squarespace.com",
        "wordpress.com", "googleapis.com", "schema.org", "facebook.com",
        "instagram.com", "linkedin.com", "twitter.com", "x.com"
    },
    "phone_patterns": [
        r"(?:tel:|phone:|whatsapp:)?(\+?\d[\d\s\-().]{6,17}\d)",
        r"\+?\d{1,3}[\s\-]?\(?\d{2,3}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}",
        r"\b\d{9,11}\b",
    ],
    "social_patterns": {
        "linkedin": [
            r'linkedin\.com/(company|in)/[a-zA-Z0-9\-]+',
            r'linkedin\.com/[a-zA-Z0-9\-]+',
        ],
        # ... más patrones
    },
}
```

### 6.2 Falta de validación de configuración

**Problema:** No hay validación de que `config.py` tenga valores válidos.

**Rejemplo:** Si `OLLAMA["url"]` está mal configurado, el error solo aparece en runtime.

**Recomendación:**
```python
# config.py
def validate_config() -> list[str]:
    """Valida la configuración y devuelve errores."""
    errors = []

    if not OLLAMA.get("url"):
        errors.append("OLLAMA.url no está configurado")

    if not OLLAMA.get("model"):
        errors.append("OLLAMA.model no está configurado")

    if OLLAMA.get("timeout_s", 0) <= 0:
        errors.append("OLLAMA.timeout_s debe ser positivo")

    # ... más validaciones

    return errors

# Validar al importar
if __name__ != "__main__":  # Solo validar cuando se importa, no cuando se ejecuta como script
    config_errors = validate_config()
    if config_errors:
        raise ValueError(f"Errores de configuración: {', '.join(config_errors)}")
```

---

## 7. Problemas de Testing

### 7.1 Falta de tests de integración

**Problema:** Solo hay tests unitarios en `tests/`. No hay tests de integración que verifiquen el flujo completo.

**Recomendación:** Agregar tests de integración:
```python
# tests/test_integration.py
def test_pipeline_end_to_end():
    """Prueba el pipeline completo."""
    # 1. Scrape
    leads = scrape_google_maps("Retail Lima", limit=5)
    assert len(leads) > 0

    # 2. Enrich
    enriched = enrich_leads(leads)
    assert len(enriched) == len(leads)

    # 3. Qualify
    qualified = qualify_leads(enriched)
    assert all("crm_stage" in lead for lead in qualified)
```

### 7.2 Tests no cubren casos edge

**Problema:** Los tests existentes no cubren casos edge como:
- CSV vacío
- CSV con columnas faltantes
- Leads con datos inválidos
- Errores de red
- Ollama no disponible

**Recomendación:** Agregar tests para estos casos.

---

## 8. Problemas de Documentación

### 8.1 Docstrings inconsistentes

**Problema:** Algunas funciones tienen docstrings detalladas, otras no tienen ninguna.

**Ejemplos:**
- `pre_score` tiene docstring
- `should_skip` tiene docstring
- `ollama_call` tiene docstring
- `qualify_row` NO tiene docstring

**Recomendación:** Estandarizar docstrings con formato Google o NumPy.

### 8.2 Falta de documentación de arquitectura

**Problema:** No hay documentación sobre:
- Cómo se integran los módulos
- Flujo de datos entre scripts
- Decisiones de diseño

**Recomendación:** Crear `ARCHITECTURE.md` con diagramas y explicaciones.

---

## 9. Problemas de Seguridad

### 9.1 No hay sanitización de entrada

**Problema:** Los datos de los leads no se sanitizan antes de usarlos.

**Riesgo:** Si un lead tiene HTML/JavaScript malicioso en algún campo, podría causar problemas.

**Recomendación:**
```python
def sanitize_string(s: str) -> str:
    """Sanitiza una cadena para prevenir inyección de código."""
    # Escapar HTML
    s = html.escape(s)
    # Remover caracteres peligrosos
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', s)
    return s
```

### 9.2 No hay rate limiting

**Problema:** No hay límite de velocidad para las peticiones a APIs externas.

**Riesgo:** Bloqueo por parte de Google, SUNAT, etc.

**Recomendación:** Implementar rate limiting:
```python
from functools import wraps
import time

def rate_limit(calls: int, period: float):
    """Decorator para limitar la tasa de llamadas."""
    def decorator(func):
        last_called = [0.0]
        calls_made = [0]

        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            elapsed = now - last_called[0]

            if elapsed > period:
                calls_made[0] = 0
                last_called[0] = now

            if calls_made[0] >= calls:
                sleep_time = period - elapsed
                time.sleep(sleep_time)
                calls_made[0] = 0
                last_called[0] = time.time()

            calls_made[0] += 1
            return func(*args, **kwargs)

        return wrapper
    return decorator

# Uso
@rate_limit(calls=5, period=60)  # 5 llamadas por minuto
def fetch_html(url: str) -> str:
    # ...
```

---

## 10. Resumen de Recomendaciones Prioritarias

### Alta Prioridad (Crítico)

1. **Estandarizar nombres de columnas** - Crear `constants.py`
2. **Mejorar manejo de errores** - Crear excepciones personalizadas
3. **Agregar validación de entrada** - Validar datos antes de procesar
4. **Integrar contact_enricher en pipeline** - Hacer el flujo completo

### Media Prioridad (Importante)

5. **Refactorizar pipeline para usar imports** - Eliminar subprocesos
6. **Crear clase Lead** - Mejorar tipado y validación
7. **Agregar paralelismo a contact_enricher** - Mejorar performance
8. **Mover configuración hardcoded a config.py** - Centralizar configuración

### Baja Prioridad (Mejora)

9. **Agregar tests de integración** - Mejorar cobertura
10. **Estandarizar docstrings** - Mejorar documentación
11. **Implementar rate limiting** - Mejorar seguridad
12. **Crear ARCHITECTURE.md** - Documentar diseño

---

## Conclusión

El códigobase es funcional pero presenta varias inconsistencias que pueden causar problemas a medida que el proyecto crece. Las mejoras prioritarias deberían enfocarse en:

1. Estandarización de datos y nomenclatura
2. Mejor manejo de errores y validación
3. Integración de módulos para un flujo más coherente
4. Performance y escalabilidad

Implementar estas mejoras hará el código más mantenible, robusto y escalable.