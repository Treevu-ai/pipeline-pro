# Arquitectura de AgentePyme SDR

## Visión General

AgentePyme SDR es un sistema de calificación de leads para MIPYME en Latinoamérica que utiliza inteligencia artificial local (Ollama) para calificar prospectos y generar mensajes de outreach personalizados.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AgentePyme SDR                                      │
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │   Scraper    │───▶│  Enricher    │───▶│   SDR Agent  │───▶│  Report  │  │
│  │              │    │              │    │              │    │          │  │
│  │ Google Maps  │    │  Sitios Web  │    │   Ollama     │    │   HTML   │  │
│  │  + SUNAT     │    │  + Contactos │    │   LLM        │    │   CSV    │  │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Componentes Principales

### 1. Scraper (`scraper.py`)

**Responsabilidad:** Descubrir y enriquecer leads desde fuentes públicas.

**Fuentes de datos:**
- Google Maps: nombre, teléfono, sitio web, dirección, categoría, reseñas
- Sitios web: emails, teléfonos adicionales
- SUNAT API (Perú): razón social oficial, estado, actividad económica

**Flujo de datos:**
```
Query de búsqueda
    ↓
Google Maps (Playwright)
    ↓
Leads básicos (empresa, teléfono, sitio web)
    ↓
Enriquecimiento web (emails, teléfonos)
    ↓
Enriquecimiento SUNAT (opcional, solo Perú)
    ↓
Leads enriquecidos (CSV)
```

**Funciones principales:**
- `scrape_google_maps()`: Scrapea Google Maps usando Playwright
- `enrich_from_website()`: Extrae emails y teléfonos de sitios web
- `enrich_sunat()`: Consulta API de SUNAT
- `enrich_leads()`: Orquesta el enriquecimiento de múltiples leads

### 2. SDR Agent (`sdr_agent.py`)

**Responsabilidad:** Calificar leads y generar mensajes de outreach.

**Flujo de datos:**
```
Leads (CSV)
    ↓
Pre-scoring (reglas deterministas)
    ↓
Ollama (LLM local)
    ↓
Calificación + Borrador de mensaje
    ↓
Leads calificados (CSV + HTML)
```

**Funciones principales:**
- `pre_score()`: Calcula score base con reglas (0-65)
- `ollama_call()`: Comunica con Ollama con reintentos
- `qualify_row()`: Califica un lead individual
- `generate_html_report()`: Genera reporte visual

**Etapas de calificación:**
- **Prospección**: Lead frío sin señales suficientes
- **Calificado**: Industria objetivo + email + señal de necesidad + cargo decisor
- **En seguimiento**: Interés probable pero falta algún dato
- **Descartado**: Fuera de ICP o sin forma de contacto

### 3. Contact Enricher (`contact_enricher.py`)

**Responsabilidad:** Enriquecer contactos con información adicional.

**Fuentes de datos:**
- Google Search: encontrar sitio web de la empresa
- Sitios web: emails adicionales, teléfonos, redes sociales
- Generación heurística: emails personales basados en nombre

**Flujo de datos:**
```
Leads (CSV)
    ↓
Google Search (si no tiene sitio web)
    ↓
Sitio web
    ↓
Extracción de emails, teléfonos, redes sociales
    ↓
Generación de emails personales (guess)
    ↓
Leads enriquecidos (CSV)
```

**Funciones principales:**
- `find_website()`: Busca sitio web en Google
- `enrich_from_website()`: Extrae datos de contacto del sitio web
- `enrich_leads()`: Orquesta el enriquecimiento con paralelismo

### 4. Pipeline (`pipeline.py`)

**Responsabilidad:** Orquestar el flujo completo end-to-end.

**Flujo de datos:**
```
Query de búsqueda
    ↓
[1] Scraping (Google Maps + enriquecimiento web)
    ↓
Leads raw
    ↓
[2] Calificación (Ollama LLM)
    ↓
Leads calificados
    ↓
[3] Enriquecimiento de contactos (opcional)
    ↓
Leads finales + Reporte HTML
```

**Funciones principales:**
- `scrape_google_maps()`: Importado de scraper.py
- `qualify_leads()`: Importado de sdr_agent.py
- `enrich_contacts()`: Importado de contact_enricher.py
- `main()`: Orquesta todo el flujo

## Módulos de Soporte

### constants.py

Define constantes y nombres estandarizados para toda la aplicación.

**Contenido:**
- `ColumnNames`: Nombres de columnas CSV estandarizados
- `CRMStages`: Etapas del CRM
- `QualificationValues`: Valores posibles de calificación
- `Channel`: Canales de outreach
- `RegexPatterns`: Patrones de regex comunes
- `BLACKLIST_DOMAINS`: Dominios a excluir

**Propósito:** Mantener consistencia en toda la aplicación y evitar errores tipográficos.

### utils.py

Funciones utilitarias reutilizables en toda la aplicación.

**Funciones principales:**
- `normalize()`: Normaliza texto (quita acentos, minúsculas)
- `is_valid_email()`: Valida emails
- `is_valid_phone()`: Valida teléfonos
- `is_valid_ruc()`: Valida RUCs peruanos
- `sanitize_string()`: Sanitiza strings para prevenir XSS
- `normalize_url()`: Normaliza URLs
- `extract_domain()`: Extrae dominio de URL
- `extract_emails_from_text()`: Extrae emails de texto
- `extract_phones_from_text()`: Extrae teléfonos de texto
- `guess_personal_emails()`: Genera emails personales probables
- `rate_limit()`: Decorador para limitar tasa de llamadas
- `validate_lead_data()`: Valida datos de un lead
- `setup_logging()`: Configura logging

**Propósito:** Centralizar funciones comunes para evitar duplicación.

### models.py

Define estructuras de datos usando dataclasses.

**Clases principales:**
- `Lead`: Representa un lead con todos sus campos
- `LeadList`: Representa una lista de leads con estadísticas
- `ScrapingResult`: Resultado de una operación de scraping
- `QualificationResult`: Resultado de una calificación
- `EnrichmentResult`: Resultado de un enriquecimiento

**Propósito:** Proporcionar tipado estático y validación de datos.

### exceptions.py

Define excepciones personalizadas para manejo de errores específico.

**Jerarquía de excepciones:**
```
AgentePymeError (base)
├── ValidationError
│   ├── LeadValidationError
│   └── ConfigValidationError
├── ScrapingError
│   ├── GoogleMapsError
│   ├── WebsiteScrapingError
│   └── SunatError
├── QualificationError
│   ├── OllamaError
│   └── LLMResponseError
├── EnrichmentError
│   ├── GoogleSearchError
│   └── ContactExtractionError
├── IOError
│   ├── CSVError
│   └── FileNotFoundError
├── NetworkError
│   ├── HTTPError
│   ├── TimeoutError
│   └── RateLimitError
├── ConfigurationError
│   ├── OllamaNotAvailableError
│   └── PlaywrightNotAvailableError
└── PipelineError
    └── StepFailedError
```

**Propósito:** Proporcionar manejo de errores granular y específico.

### config.py

Configuración centralizada de la aplicación.

**Secciones:**
- `OLLAMA`: Configuración de conexión a Ollama
- `PRODUCT`: Información del producto
- `ICP`: Ideal Customer Profile
- `CHANNEL`: Canal de outreach por defecto
- `PLAYBOOK`: Instrucciones del sistema para el agente
- `OUTPUT_KEYS`: Columnas de salida del agente
- `ENRICHMENT`: Configuración de enriquecimiento
- `SCRAPING`: Configuración de scraping
- `QUALIFICATION`: Configuración de calificación
- `RATE_LIMITING`: Límites de tasa para APIs externas

**Propósito:** Centralizar toda la configuración para fácil personalización.

## Flujo de Datos Detallado

### 1. Flujo de Scraping

```
┌─────────────┐
│   Query     │ "Retail Lima"
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│  scrape_google_maps()          │
│  - Playwright abre navegador   │
│  - Navega a Google Maps        │
│  - Extrae resultados           │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  Leads básicos                  │
│  - empresa                      │
│  - industria                    │
│  - telefono                    │
│  - sitio_web                    │
│  - dirección                   │
│  - rating, reseñas              │
└──────┬──────────────────────────┘
       │
       ▼ (si no --no-enrich)
┌─────────────────────────────────┐
│  enrich_leads()                 │
│  - Visita cada sitio web       │
│  - Extrae emails               │
│  - Extrae teléfonos            │
└──────┬──────────────────────────┘
       │
       ▼ (si --enrich-sunat)
┌─────────────────────────────────┐
│  enrich_sunat()                 │
│  - Consulta API SUNAT           │
│  - Razón social oficial         │
│  - Estado, condición           │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  save_leads()                  │
│  - Guarda en CSV               │
└─────────────────────────────────┘
```

### 2. Flujo de Calificación

```
┌─────────────┐
│  Leads CSV  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│  pre_score()                    │
│  - Industria objetivo? (+15)    │
│  - Facturas altas? (+15)        │
│  - Facturas medias? (+8)        │
│  - Tiene email? (+12)           │
│  - Tiene teléfono? (+8)         │
│  - Tiene contacto? (+7)         │
│  - Tiene cargo? (+5)            │
│  - Palabras excluidas? (-40)    │
│  - Base: +5                     │
│  - Máximo: 65                   │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  qualify_row()                  │
│  - Construye prompt para LLM    │
│  - Incluye datos del lead       │
│  - Incluye pre-score            │
│  - Incluye instrucciones canal  │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  ollama_call()                  │
│  - Envía request a Ollama       │
│  - Reintenta si falla           │
│  - Backoff exponencial          │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  Respuesta LLM                  │
│  - crm_stage                    │
│  - lead_score (0-100)          │
│  - fit_product                  │
│  - intent_timeline              │
│  - decision_maker               │
│  - blocker                      │
│  - next_action                  │
│  - qualification_notes          │
│  - draft_subject                │
│  - draft_message                │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  Guardar CSV + Reporte HTML    │
└─────────────────────────────────┘
```

### 3. Flujo de Enriquecimiento de Contactos

```
┌─────────────┐
│  Leads CSV  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│  Por cada lead:                 │
│                                 │
│  ¿Tiene sitio_web?             │
│     │ No                        │
│     ▼                           │
│  find_website()                 │
│  - Google Search                │
│  - Extraer primer resultado     │
│  - Filtrar redes sociales       │
│     │                           │
│     ▼                           │
│  enrich_from_website()         │
│  - Descargar HTML               │
│  - Extraer emails               │
│  - Extraer teléfonos           │
│  - Extraer redes sociales       │
│  - Generar emails personales    │
│     │                           │
│     ▼                           │
│  Merge con lead original         │
│  - No sobrescribir existentes   │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  Guardar CSV                   │
└─────────────────────────────────┘
```

## Paralelismo y Performance

### Scraper

- **Actualmente:** Secuencial (un lead a la vez)
- **Rate limiting:** Implementado para website_scraping (3 llamadas cada 10s)
- **Optimización:** Reutilizar navegador para múltiples búsquedas (no implementado)

### SDR Agent

- **Actualmente:** Paralelo configurable (ThreadPoolExecutor)
- **Default:** 1 worker (secuencial)
- **Máximo recomendado:** 3-5 workers dependiendo de GPU/CPU
- **Rate limiting:** No implementado (Ollama maneja concurrencia internamente)

### Contact Enricher

- **Actualmente:** Paralelo configurable (ThreadPoolExecutor)
- **Default:** 1 worker (secuencial)
- **Máximo recomendado:** 2-3 workers (Google puede bloquear)
- **Rate limiting:** Implementado para website_scraping

## Manejo de Errores

### Estrategia General

1. **Excepciones específicas:** Cada módulo tiene sus propias excepciones
2. **Logging:** Todos los errores se loguean con contexto
3. **Continuidad:** El pipeline continúa con los leads que sí procesaron
4. **Códigos de salida:** Códigos estandarizados para scripts

### Códigos de Salida

| Código | Significado |
|--------|-------------|
| 0 | Éxito |
| 1 | Error genérico |
| 2 | Argumentos inválidos |
| 3 | Archivo no encontrado |
| 4 | Error de red |
| 5 | Error de validación |

## Validación de Datos

### Validación de Configuración

Al importar `config.py`, se valida automáticamente:
- URL de Ollama configurada
- Modelo de Ollama configurado
- Timeouts positivos
- ICP válido
- Canal válido

### Validación de Leads

La función `validate_lead_data()` valida:
- Campos obligatorios presentes
- Emails válidos
- Teléfonos válidos
- RUCs válidos (11 dígitos)
- URLs válidas
- Facturas pendientes no negativas

## Seguridad

### Sanitización

- `sanitize_string()`: Escapa HTML y remueve caracteres de control
- `sanitize_filename()`: Remueve caracteres inválidos de nombres de archivo

### Rate Limiting

- Implementado para APIs externas (Google, SUNAT, websites)
- Previene bloqueos por exceso de peticiones

### Validación de Entrada

- Todos los datos de entrada se validan antes de procesar
- Emails, teléfonos, URLs, RUCs se validan

## Testing

### Tests Unitarios

- `tests/test_scraper.py`: 21 tests del scraper
- `tests/test_sdr.py`: 26 tests del agente SDR

### Tests de Integración (pendientes)

- `tests/test_integration.py`: Tests del flujo completo del pipeline

## Extensibilidad

### Agregar Nuevas Fuentes de Datos

Para agregar una nueva fuente de datos:

1. Crear función de extracción en `scraper.py` o módulo separado
2. Agregar configuración en `config.py`
3. Integrar en `enrich_leads()`
4. Agregar tests unitarios

### Agregar Nuevos Canales de Outreach

Para agregar un nuevo canal:

1. Agregar canal a `Channel` en `constants.py`
2. Agregar límite de palabras en `WordLimits`
3. Agregar nota de canal en `qualify_row()`
4. Actualizar documentación

### Personalizar el Playbook

El playbook del agente se define en `config.py` bajo `PLAYBOOK`. Para personalizar:

1. Editar `PRODUCT` con información de tu producto
2. Editar `ICP` con tu perfil de cliente ideal
3. Editar `PLAYBOOK` con instrucciones específicas

## Deployment

### Requisitos

- Python 3.9+
- Ollama corriendo localmente
- Playwright Chromium instalado
- Dependencias en `requirements.txt`

### Instalación

```bash
pip install -r requirements.txt
playwright install chromium
ollama pull mistral:7b-instruct-q4_0
```

### Ejecución

```bash
# Pipeline completo
python pipeline.py "Retail Lima" --limit 20 --report

# Solo scraping
python scraper.py "Retail Lima" --limit 20

# Solo calificación
python sdr_agent.py leads.csv output.csv --report

# Solo enriquecimiento
python contact_enricher.py leads.csv output.csv
```

## Mantenimiento

### Logs

Los logs se guardan en:
- `output/logs/sdr_YYYYMMDD_HHMMSS.log` para SDR Agent
- `output/logs/agentepyme_YYYYMMDD_HHMMSS.log` para otros módulos

### Monitoreo

Métricas a monitorear:
- Tasa de éxito de scraping
- Tasa de éxito de calificación
- Tiempo de respuesta de Ollama
- Tasa de enriquecimiento exitoso

### Actualizaciones

Para actualizar el sistema:
1. Revisar cambios en `CHANGELOG.md`
2. Actualizar dependencias: `pip install -r requirements.txt --upgrade`
3. Actualizar Playwright: `playwright install --with-deps chromium`
4. Probar con datos de ejemplo

## Troubleshooting

### Problemas Comunes

**Ollama no responde:**
- Verificar que Ollama esté corriendo: `ollama list`
- Verificar URL en `config.py`
- Aumentar timeout en `config.py`

**Playwright falla:**
- Reinstalar: `playwright install --force chromium`
- Verificar que Chromium esté instalado

**Google bloquea peticiones:**
- Aumentar delay entre peticiones
- Usar modo headful para depurar
- Considerar usar proxies

**LLM responde con JSON inválido:**
- Verificar modelo en `config.py`
- Ajustar temperatura
- Revisar logs para ver respuesta cruda

## Contribución

Para contribuir al proyecto:

1. Fork el repositorio
2. Crear rama para tu feature: `git checkout -b feature/nueva-funcionalidad`
3. Commit tus cambios: `git commit -m 'Agrega nueva funcionalidad'`
4. Push a la rama: `git push origin feature/nueva-funcionalidad`
5. Abrir Pull Request

### Estándares de Código

- Seguir PEP 8
- Usar type hints
- Documentar con docstrings en formato Google
- Agregar tests para nuevas funcionalidades
- Actualizar documentación

## Licencia

Este proyecto está bajo licencia MIT. Ver archivo LICENSE para más detalles.