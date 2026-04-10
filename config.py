"""
config.py — Edita este archivo para adaptar el agente a tu producto y mercado.
"""
from __future__ import annotations
import os

# ─── Conexión a Ollama (legacy — solo para uso local) ─────────────────────────
OLLAMA = {
    "url": "http://127.0.0.1:11434/api/chat",
    "model": "mistral:7b-instruct-q4_0",
    "timeout_s": 180,
    "temperature": 0,   # 0 = determinista — mismos datos → mismo score siempre
    "retries": 3,
    "backoff_s": 2,
}

# ─── Claude API (producción — prioridad sobre Groq) ──────────────────────────
# Requiere variable de entorno: ANTHROPIC_API_KEY
CLAUDE = {
    "model": "claude-haiku-4-5-20251001",  # rápido y barato (~$0.01/lead)
    "max_tokens": 1024,
    "temperature": 0,   # 0 = determinista
    "retries": 3,
    "backoff_s": 2,
}

# ─── Groq API (fallback si ANTHROPIC_API_KEY no está disponible) ──────────────
# Requiere variable de entorno: GROQ_API_KEY
GROQ = {
    "model": "llama-3.3-70b-versatile",   # o "llama-3.1-8b-instant" para menor latencia
    "temperature": 0,   # 0 = determinista
    "retries": 3,
    "backoff_s": 2,
}

# ─── Google Places API ───────────────────────────────────────────────────────
# Requiere variable de entorno: GOOGLE_PLACES_API_KEY
# Habilitar en: console.cloud.google.com → APIs → "Places API (New)"
GOOGLE_PLACES_API_KEY: str = os.environ.get("GOOGLE_PLACES_API_KEY", "")

# ─── Tu producto ─────────────────────────────────────────────────────────────
PRODUCT = {
    "name": "Pipeline_X",
    "short_pitch": (
        "Automatizamos la búsqueda y calificación de empresas cliente "
        "para que tu equipo B2B solo hable con negocios listos para comprar."
    ),
    # EDITA ESTO: describe qué vendes en 2-3 frases concretas.
    # El agente usa este texto para personalizar los borradores.
    # Ejemplo: "Ofrecemos factoring express para MIPYME: adelanto de facturas
    # pendientes en 48 horas, sin garantías hipotecarias, desde S/. 5,000."
    "description": (
        "Ofrecemos un agente SDR automatizado B2B que encuentra negocios reales "
        "(tiendas, constructoras, transportistas, clínicas, etc.) en Google Maps, "
        "los califica con IA y redacta mensajes de primer contacto personalizados "
        "por industria. Pipeline_X prospeta empresas, no personas individuales."
    ),
    "benefits": [
        "Encuentra negocios de cualquier industria en Google Maps en minutos",
        "Calificación automática con score 0–100 por empresa",
        "Borradores de mensaje personalizados por sector e industria",
        "Pipeline limpio con etapas CRM, score y siguiente acción recomendada",
    ],
    "cta": "¿Podemos agendar 20 minutos esta semana para mostrarte cómo funciona?",
}

# ─── ICP (Ideal Customer Profile) ─────────────────────────────────────────────
# El agente usa estas reglas ANTES del LLM para pre-calcular un score base.
ICP = {
    # Sectores con fit real probado para Pipeline_X.
    # Deliberadamente estrecha: industry_match (+15 pts) debe ser una señal fuerte,
    # no un comodín que se activa para el 90% de leads.
    "target_industries": [
        # Canal intermediario — quienes revenden el servicio SDR
        "Contabilidad", "Estudio Contable", "Contador",
        "Marketing", "Agencia", "Consultoría", "Consultor",
        # Canal MYPE directa — quienes necesitan leads para su propio negocio
        "Retail", "Comercio",
        "Construcción", "Inmobiliaria",
        "Logística", "Transporte",
    ],
    "excluded_keywords": [            # empresas a descartar automáticamente
        "holding", "SAC inactiva", "en liquidación",
    ],
    # Señales de Google Maps
    "reviews_high": 50,               # reseñas → negocio activo y establecido
    "reviews_mid": 10,                # reseñas mínimas para señal positiva
    "rating_min_good": 4.0,           # rating mínimo para considerar buena reputación
    # Distritos por nivel socioeconómico (proxy de capacidad de pago).
    # Cobertura: Lima + 14 ciudades = 15 ciudades principales de Perú.
    # Metodología: distritos_high → NSE A/B (target prioritario),
    #              distritos_medium → NSE C (target secundario).
    # La búsqueda es substring en ciudad + dirección + dirección_fiscal.
    "distritos_high": [
        # 1. Lima NSE A/B
        "san isidro", "miraflores", "surco", "santiago de surco",
        "san borja", "la molina", "barranco",
        # 2. Trujillo NSE A/B (urbanizaciones)
        "el golf", "california", "san andres", "el recreo",
        # 3. Arequipa NSE A/B
        "cayma", "yanahuara", "selva alegre",
        # 4. Chiclayo NSE A/B
        "santa victoria", "la primavera",
        # 5. Piura NSE A/B
        "los cocos", "country club piura",
        # 6. Cusco NSE A/B
        "san blas", "wanchaq",
        # 7. Iquitos NSE A/B
        "san juan bautista iquitos", "los rosales iquitos",
        # 8. Huancayo NSE A/B
        "el tambo", "chilca huancayo",
        # 9. Tacna NSE A/B
        "gregorio albarracin", "ciudad nueva tacna",
        # 10. Cajamarca NSE A/B
        "los fresnos cajamarca", "los sauces cajamarca",
        # 11. Chimbote NSE A/B (pesca industrial + siderurgia, Áncash)
        "nuevo chimbote", "urb. buenos aires chimbote", "la caleta chimbote",
        # 12. Ica NSE A/B (agroexportación + vitivinicultura)
        "ica centro", "los aquijes", "san isidro ica",
        # 13. Juliaca NSE A/B (hub comercial sur, Puno)
        "san roman juliaca", "urb. los alamos juliaca",
        # 14. Pucallpa NSE A/B (hub amazónico central, Ucayali)
        "yarinacocha", "urb. country pucallpa",
        # 15. Tarapoto NSE A/B (hub selva norte, San Martín)
        "banda de shilcayo", "urb. los jardines tarapoto",
    ],
    "distritos_medium": [
        # 1. Lima NSE C
        "jesús maría", "jesus maria", "lince", "magdalena", "pueblo libre",
        "san miguel", "chorrillos", "la victoria", "breña", "cercado", "lima cercado",
        # 2. Trujillo NSE C
        "el porvenir", "la esperanza", "florencia de mora", "trujillo centro",
        # 3. Arequipa NSE C
        "cercado de arequipa", "cerro colorado", "mariano melgar", "sachaca",
        # 4. Chiclayo NSE C
        "jose leonardo ortiz", "la victoria chiclayo", "reque",
        # 5. Piura NSE C
        "castilla", "piura centro", "veintiséis de octubre",
        # 6. Cusco NSE C
        "santiago cusco", "san jeronimo cusco", "cusco centro",
        # 7. Iquitos NSE C
        "punchana", "belen iquitos", "maynas",
        # 8. Huancayo NSE C
        "huancayo centro", "pilcomayo", "san agustin huancayo",
        # 9. Tacna NSE C
        "tacna centro", "pocollay", "alto de la alianza",
        # 10. Cajamarca NSE C
        "cajamarca centro", "baños del inca", "los banos del inca",
        # 11. Chimbote NSE C
        "chimbote centro", "el progreso chimbote", "villa maria chimbote",
        # 12. Ica NSE C
        "la tinguina", "subtanjalla", "parcona",
        # 13. Juliaca NSE C
        "juliaca centro", "caracoto", "san miguel juliaca",
        # 14. Pucallpa NSE C
        "pucallpa centro", "calleria", "manantay",
        # 15. Tarapoto NSE C
        "morales tarapoto", "tarapoto centro", "la banda de shilcayo",
    ],
    # Velocidad de reseñas: reseñas/mes — negocio activo vs. heredado
    "review_velocity_high": 2.0,   # ≥2 reseñas/mes → muy activo
    "review_velocity_mid":  0.5,   # ≥0.5 reseñas/mes → activo
    # Pesos calibrados para que el pre-score máximo sea ~65.
    # El LLM ajusta los 35 puntos restantes según señales cualitativas.
    "score_weights": {
        "base": 5,                    # score base mínimo (cualquier lead conocido vale algo)
        "industry_match": 15,         # puntos si la industria está en target_industries
        "reviews_high": 12,           # puntos si num_resenas >= reviews_high
        "reviews_mid": 6,             # puntos si num_resenas >= reviews_mid
        "rating_good": 8,             # puntos si rating >= rating_min_good
        "has_website": 10,            # puntos si tiene sitio web
        "has_email": 8,               # puntos si tiene email válido
        "has_phone": 6,               # puntos si tiene teléfono
        "distrito_high": 8,           # puntos si está en distrito A
        "distrito_medium": 4,         # puntos si está en distrito B
        "has_contact": 5,             # puntos si tiene nombre de contacto
        "has_cargo": 3,               # puntos si tiene cargo del contacto
        "review_velocity_high": 7,    # puntos si ≥2 reseñas/mes (negocio muy activo)
        "review_velocity_mid":  3,    # puntos si ≥0.5 reseñas/mes (negocio activo)
        # Régimen tributario SUNAT (proxy de tamaño y capacidad de pago)
        "regimen_general": 8,         # Régimen General → empresa mediana/grande
        "regimen_mype":    5,         # Régimen MYPE Tributario → MYPE establecida
        "regimen_rer":     2,         # Régimen Especial → microempresa activa
        # RUS no suma — microempresa mínima, capacidad de pago insuficiente
    },
}

# ─── Canal de outreach ────────────────────────────────────────────────────────
# "email"     → genera draft_subject + draft_message (formato email)
# "whatsapp"  → genera solo draft_message (~80 palabras, sin asunto)
# "both"      → genera ambos
CHANNEL = "email"

# ─── Playbook del agente (instrucciones del sistema) ─────────────────────────
# Personaliza el tono, las reglas y el contexto de tu negocio aquí.
PLAYBOOK = f"""
Eres un SDR experto B2B para Latinoamérica que trabaja para {PRODUCT['name']}.

QUÉ VENDEMOS:
{PRODUCT['description']}

CONTEXTO CRÍTICO — qué es un lead en Pipeline_X:
Cada fila es un NEGOCIO (empresa, comercio, PYME), no una persona individual.
Los datos provienen de Google Maps: nombre del negocio, categoría, dirección, teléfono,
reseñas, rating, sitio web. El objetivo es contactar a ese negocio para ofrecerle Pipeline_X.
El mensaje de outreach va dirigido a la empresa, no a una persona por nombre.

REGLAS ESTRICTAS:
1. No inventes datos que no estén en la fila del lead; si falta información, indícalo en qualification_notes.
2. No prometas tasas, plazos legales, rendimientos ni resultados garantizados.
3. No menciones competidores.
4. El mensaje de outreach debe tener máximo 100 palabras, en español neutro latinoamericano.
5. El mensaje debe mencionar el dolor específico del sector del negocio (retail → rotación de inventario,
   logística → costos operativos, construcción → flujo de caja en obra, etc.).
6. Usa un solo CTA claro al final del mensaje: "{PRODUCT['cta']}"
7. Si el negocio tiene señales de alto potencial (muchas reseñas, rating alto, sitio web, distrito A, email válido, cargo decisor), sube el score.
   El score base ya viene calculado por reglas (máximo 65). Tú ajustas con señales cualitativas hasta 100.
   Señales positivas: >50 reseñas, rating ≥4.0, presencia web activa, distrito premium, email válido, cargo decisor identificado.
   Señales negativas: sin reseñas, sin sitio web, sin contacto, estado SUNAT irregular.
8. Si faltan datos críticos (email, decisor, industria), marca next_action como "completar dato" y baja el score.
9. Salida EXCLUSIVAMENTE como objeto JSON válido. Sin markdown, sin texto fuera del JSON.

CRITERIOS DE CALIFICACIÓN:
- "Calificado": industria objetivo + email + señal de necesidad clara + cargo sugiere poder de decisión.
- "En seguimiento": interés probable pero falta algún dato o señal (sin teléfono, cargo ambiguo, etc.).
- "Prospección": negocio frío sin señales suficientes, primer contacto exploratorio.
- "Descartado": fuera de ICP, sin forma de contacto, o negocio con señales negativas (liquidación, holding sin operaciones).
"""

# ─── Columnas de salida que el agente produce ────────────────────────────────
OUTPUT_KEYS = (
    "crm_stage",           # Prospección | Calificado | En seguimiento | Descartado
    "lead_score",          # 0-100
    "fit_product",         # si | no | dudoso
    "intent_timeline",     # <30d | 30-90d | >90d | desconocido
    "decision_maker",      # si | no | desconocido
    "blocker",             # texto breve o vacío
    "next_action",         # acción concreta
    "positive_signals",    # señales positivas (pipe-separated): ">50 reseñas | rating 4.5"
    "negative_signals",    # señales negativas (pipe-separated): "sin email | cargo ambiguo"
    "qualification_notes", # resumen 2-3 frases explicando el score
    "draft_subject",       # asunto del email (vacío si canal=whatsapp)
    "draft_message",       # cuerpo del mensaje listo para copiar
    "qualify_error",       # error técnico si hubo fallo
)


# ─── Configuración de enriquecimiento de contactos ─────────────────────────────
ENRICHMENT = {
    # Dominios a excluir (emails genéricos/irrelevantes)
    "blacklist_domains": {
        "sentry.io", "example.com", "wixpress.com", "squarespace.com",
        "wordpress.com", "googleapis.com", "schema.org", "facebook.com",
        "instagram.com", "linkedin.com", "twitter.com", "x.com", "tiktok.com",
        "youtube.com",
    },
    # Patrones de regex para extraer teléfonos
    "phone_patterns": [
        r"(?:tel:|phone:|whatsapp:)?(\+?\d[\d\s\-().]{6,17}\d)",
        r"\+?\d{1,3}[\s\-]?\(?\d{2,3}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}",
        r"\b\d{9,11}\b",  # Perú: 9 dígitos + código país
    ],
    # Patrones de regex para extraer redes sociales
    "social_patterns": {
        "linkedin": [
            r'linkedin\.com/(company|in)/[a-zA-Z0-9\-]+',
            r'linkedin\.com/[a-zA-Z0-9\-]+',
        ],
        "facebook": [
            r'facebook\.com/[a-zA-Z0-9\.\-]+',
            r'fb\.com/[a-zA-Z0-9\.\-]+',
        ],
        "instagram": [
            r'instagram\.com/[a-zA-Z0-9_\.]+',
        ],
        "twitter": [
            r'twitter\.com/[a-zA-Z0-9_]+',
            r'x\.com/[a-zA-Z0-9_]+',
        ],
        "youtube": [
            r'youtube\.com/(channel|c|user)/[a-zA-Z0-9\-]+',
        ],
        "tiktok": [
            r'tiktok\.com/@[a-zA-Z0-9_\.]+',
        ],
    },
    # Prefijos comunes de email corporativo
    "email_prefixes": [
        "info", "contacto", "ventas", "hola", "gerencia",
        "administracion", "soporte", "webmaster",
    ],
    # Límites de validación
    "min_phone_digits": 9,
    "max_phone_digits": 17,
    "min_domain_length": 5,
}


# ─── Configuración de scraping ─────────────────────────────────────────────────
SCRAPING = {
    # Límites por defecto
    "default_limit": 20,
    "default_delay": 1.2,
    "default_timeout": 10,
    "google_maps_timeout": 30_000,
    "cookie_accept_timeout": 3_000,
    # Delays aleatorios (en milisegundos)
    "scroll_delay_min": 700,
    "scroll_delay_max": 1100,
    "article_click_delay_min": 1200,
    "article_click_delay_max": 1800,
}


# ─── Configuración de calificación ─────────────────────────────────────────────
QUALIFICATION = {
    # Valores por defecto
    "default_delay": 0.3,
    "default_workers": 1,
    # Límites de score.  El cap sube a 70 para absorber review_velocity.
    # El LLM sigue teniendo banda [base-20, base+25] para ajuste cualitativo.
    "max_pre_score": 70,
    "max_score": 100,
    "min_score": 0,
    # Clamping: cuánto puede alejarse el LLM del pre-score.
    # El LLM puede bajar hasta 20 pts (señal negativa fuerte que las reglas no ven)
    # o subir hasta 25 pts (señal positiva como decisor identificado, urgencia clara).
    "score_drift_down": 20,
    "score_drift_up":   25,
    # Límites de palabras por canal
    "word_limits": {
        "email": 100,
        "whatsapp": 80,
        "both": 100,
    },
}


# ─── Configuración de rate limiting ────────────────────────────────────────────
RATE_LIMITING = {
    # Límites por API externa
    "google_search": {"calls": 5, "period": 60},  # 5 llamadas por minuto
    "sunat_api": {"calls": 10, "period": 60},     # 10 llamadas por minuto
    "website_scraping": {"calls": 3, "period": 10},  # 3 llamadas cada 10 segundos
}


# ─── Validación de configuración ─────────────────────────────────────────────

def validate_config() -> list[str]:
    """
    Valida la configuración y devuelve una lista de errores.

    Returns:
        Lista de mensajes de error (vacía si no hay errores).
    """
    errors = []

    # Validar GROQ
    if not GROQ.get("model"):
        errors.append("GROQ.model no está configurado")
    if GROQ.get("retries", 0) < 0:
        errors.append("GROQ.retries no puede ser negativo")
    if GROQ.get("backoff_s", 0) < 0:
        errors.append("GROQ.backoff_s no puede ser negativo")

    # Validar ICP
    if not ICP.get("target_industries"):
        errors.append("ICP.target_industries está vacío")
    if ICP.get("min_invoices_pending", 0) < 0:
        errors.append("ICP.min_invoices_pending no puede ser negativo")
    if ICP.get("high_value_invoices", 0) < ICP.get("min_invoices_pending", 0):
        errors.append("ICP.high_value_invoices debe ser >= min_invoices_pending")

    # Validar CHANNEL
    if CHANNEL not in ("email", "whatsapp", "both"):
        errors.append(f"CHANNEL inválido: {CHANNEL}")

    # Validar ENRICHMENT
    if ENRICHMENT.get("min_phone_digits", 0) < 1:
        errors.append("ENRICHMENT.min_phone_digits debe ser >= 1")
    if ENRICHMENT.get("max_phone_digits", 0) < ENRICHMENT.get("min_phone_digits", 0):
        errors.append("ENRICHMENT.max_phone_digits debe ser >= min_phone_digits")

    return errors


# Validar configuración al importar (solo si no se ejecuta como script)
if __name__ != "__main__":
    config_errors = validate_config()
    if config_errors:
        raise ValueError(f"Errores de configuración: {', '.join(config_errors)}")
