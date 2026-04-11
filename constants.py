"""
constants.py — Constantes y nombres estandarizados para AgentePyme SDR.

Este módulo define todos los nombres de columnas, constantes y valores
estandarizados utilizados en toda la aplicación para mantener consistencia.
"""
from __future__ import annotations

import unicodedata


def _norm(s: str) -> str:
    """Normalización mínima para comparación de etapas CRM (sin depender de utils)."""
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()

# ─── Nombres de columnas CSV ────────────────────────────────────────────────────

class ColumnNames:
    """Nombres de columnas estandarizados para CSV de leads."""

    # Campos básicos del lead
    EMPRESA = "empresa"
    INDUSTRIA = "industria"
    RUC = "ruc"
    EMAIL = "email"
    TELEFONO = "telefono"
    CIUDAD = "ciudad"
    PAIS = "pais"
    CONTACTO_NOMBRE = "contacto_nombre"
    CARGO = "cargo"
    SITIO_WEB = "sitio_web"

    # Campos de scraping
    DIRECCION = "direccion"
    CATEGORIA_ORIGINAL = "categoria_original"
    RATING = "rating"
    NUM_RESENAS = "num_resenas"
    MAPS_URL = "maps_url"
    FUENTE = "fuente"
    SCRAPED_AT = "scraped_at"

    # Campos de enriquecimiento SUNAT
    RAZON_SOCIAL_OFICIAL = "razon_social_oficial"
    ESTADO_SUNAT          = "estado_sunat"
    CONDICION_SUNAT       = "condicion_sunat"
    DIRECCION_FISCAL      = "direccion_fiscal"
    UBIGEO                = "ubigeo"
    ACTIVIDAD_ECONOMICA   = "actividad_economica"
    CIIU                  = "ciiu"
    REGIMEN_TRIBUTARIO    = "regimen_tributario"
    FECHA_INSCRIPCION     = "fecha_inscripcion"
    TIPO_CONTRIBUYENTE    = "tipo_contribuyente"

    # Campos de enriquecimiento SUNAT (financieros)
    FACTURAS_PENDIENTES = "facturas_pendientes"

    # Campos de enriquecimiento de contactos
    EMAIL_WEB = "email_web"
    EMAIL_WEB_2 = "email_web_2"
    EMAIL_WEB_3 = "email_web_3"
    TELEFONO_WEB = "telefono_web"
    TELEFONO_WEB_2 = "telefono_web_2"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    DOMINIO_WEB = "dominio_web"
    EMAIL_ESTIMADO = "email_estimado"
    EMAIL_ESTIMADO_2 = "email_estimado_2"
    EMAIL_PERSONAL_GUESS = "email_personal_guess"
    EMAIL_PERSONAL_GUESS_2 = "email_personal_guess_2"

    # Campos de calificación
    CRM_STAGE = "crm_stage"
    NOTAS_PREVIAS = "notas_previas"
    LEAD_SCORE = "lead_score"
    FIT_PRODUCT = "fit_product"
    INTENT_TIMELINE = "intent_timeline"
    DECISION_MAKER = "decision_maker"
    BLOCKER = "blocker"
    NEXT_ACTION = "next_action"
    QUALIFICATION_NOTES = "qualification_notes"
    DRAFT_SUBJECT = "draft_subject"
    DRAFT_MESSAGE = "draft_message"
    QUALIFY_ERROR = "qualify_error"

    # Alias para compatibilidad (deprecados, mantener para backwards compatibility)
    CONTACT_NAME = "contacto_nombre"  # Alias antiguo
    POSITION = "cargo"  # Alias antiguo
    PHONE = "telefono"  # Alias antiguo


# ─── Etapas CRM ─────────────────────────────────────────────────────────────────

class CRMStages:
    """Etapas del CRM estandarizadas."""

    PROSPECCION = "Prospección"
    QUALIFIED = "Calificado"
    FOLLOW_UP = "En seguimiento"
    DISCARDED = "Descartado"

    # Etapas que indican que el lead ya fue procesado
    PROCESSED = {QUALIFIED, FOLLOW_UP, DISCARDED}

    # Etapas iniciales (no procesadas) - normalizadas para comparación
    INITIAL = {_norm(s) for s in (PROSPECCION, "", "Pendiente")}


# ─── Valores de calificación ───────────────────────────────────────────────────

class QualificationValues:
    """Valores posibles para campos de calificación."""

    FIT_PRODUCT = ("si", "no", "dudoso")
    INTENT_TIMELINE = ("<30d", "30-90d", ">90d", "desconocido")
    DECISION_MAKER = ("si", "no", "desconocido")


# ─── Canales de outreach ────────────────────────────────────────────────────────

class Channel:
    """Canales de outreach."""

    EMAIL = "email"
    WHATSAPP = "whatsapp"
    BOTH = "both"

    VALID = {EMAIL, WHATSAPP, BOTH}


# ─── Límites de palabras por canal ─────────────────────────────────────────────

class WordLimits:
    """Límites de palabras para mensajes por canal."""

    EMAIL = 100
    WHATSAPP = 80
    BOTH = 100


# ─── Códigos de país ───────────────────────────────────────────────────────────

class CountryCodes:
    """Códigos de país y nombres."""

    PE = "Perú"
    CO = "Colombia"
    MX = "México"
    CL = "Chile"
    AR = "Argentina"

    CODE_TO_NAME = {
        "pe": PE,
        "co": CO,
        "mx": MX,
        "cl": CL,
        "ar": AR,
    }


# ─── Constantes de scraping ───────────────────────────────────────────────────

class ScrapingConstants:
    """Constantes para scraping."""

    DEFAULT_LIMIT = 20
    DEFAULT_DELAY = 1.2
    DEFAULT_TIMEOUT = 10
    GOOGLE_MAPS_TIMEOUT = 30_000
    COOKIE_ACCEPT_TIMEOUT = 3_000
    SCROLL_DELAY_MIN = 700
    SCROLL_DELAY_MAX = 1100
    ARTICLE_CLICK_DELAY_MIN = 1200
    ARTICLE_CLICK_DELAY_MAX = 1800


# ─── Constantes de calificación ─────────────────────────────────────────────────

class QualificationConstants:
    """Constantes para calificación."""

    DEFAULT_DELAY = 0.3
    DEFAULT_WORKERS = 1
    MAX_PRE_SCORE = 65
    MAX_SCORE = 100
    MIN_SCORE = 0


# ─── Constantes de enriquecimiento ─────────────────────────────────────────────

class EnrichmentConstants:
    """Constantes para enriquecimiento de contactos."""

    DEFAULT_DELAY = 1.0
    DEFAULT_WORKERS = 1
    MIN_PHONE_DIGITS = 9
    MAX_PHONE_DIGITS = 17
    MIN_DOMAIN_LENGTH = 5


# ─── Mapeo de categorías Google Maps → ICP ─────────────────────────────────────

CATEGORY_MAP = {
    "retail": "Retail",
    "tienda": "Retail",
    "supermerc": "Retail",
    "ferretería": "Retail",
    "ferreteria": "Retail",
    "farmacia": "Salud",
    "clínica": "Salud",
    "clinica": "Salud",
    "médico": "Salud",
    "medico": "Salud",
    "hospital": "Salud",
    "construc": "Construcción",
    "obra": "Construcción",
    "inmobiliar": "Construcción",
    "transport": "Logística",
    "logística": "Logística",
    "logistica": "Logística",
    "almac": "Logística",
    "distribuid": "Logística",
    "manufact": "Manufactura",
    "industria": "Manufactura",
    "fabric": "Manufactura",
    "restaurant": "Alimentos",
    "aliment": "Alimentos",
    "catering": "Alimentos",
    "tecnolog": "Tecnología",
    "software": "Tecnología",
    "digital": "Tecnología",
    "educac": "Educación",
    "colegio": "Educación",
    "academia": "Educación",
}


# ─── Tiers de plan ────────────────────────────────────────────────────────────

class PlanTier:
    """Identificadores de tier de plan. Deben coincidir con las claves de config.PLANS."""

    FREE            = "free"
    SOLO            = "solo"
    STARTER         = "starter"
    PRO             = "pro"
    RESELLER        = "reseller"
    STARTER_ANNUAL  = "starter_annual"
    FOUNDER         = "founder"

    # Tiers que permiten enrichment SUNAT
    SUNAT_ENABLED = {STARTER, PRO, RESELLER, STARTER_ANNUAL, FOUNDER}
    # Tiers que permiten reporte HTML
    HTML_REPORT_ENABLED = {STARTER, PRO, RESELLER, STARTER_ANNUAL, FOUNDER}
    # Tiers con acceso directo a la API
    API_ENABLED = {STARTER, PRO, RESELLER, STARTER_ANNUAL, FOUNDER}
    # Tiers con white-label
    WHITE_LABEL_ENABLED = {RESELLER}
    # Tiers válidos para validación de header
    ALL = {FREE, SOLO, STARTER, PRO, RESELLER, STARTER_ANNUAL, FOUNDER}


# ─── Patrones de regex ─────────────────────────────────────────────────────────

class RegexPatterns:
    """Patrones de regex comunes."""

    EMAIL = r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    PHONE = r"(?:tel:|phone:|whatsapp:)?(\+?\d[\d\s\-().]{6,17}\d)"
    PHONE_ALT = r"\+?\d{1,3}[\s\-]?\(?\d{2,3}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}"
    PHONE_SIMPLE = r"\b\d{9,11}\b"
    MAILTO = r'mailto:([^"\'>\s?&]+)'
    LINKEDIN = r'linkedin\.com/(company|in)/[a-zA-Z0-9\-]+'
    FACEBOOK = r'facebook\.com/[a-zA-Z0-9\.\-]+'
    INSTAGRAM = r'instagram\.com/[a-zA-Z0-9_\.]+'
    TWITTER = r'twitter\.com/[a-zA-Z0-9_]+'
    X_COM = r'x\.com/[a-zA-Z0-9_]+'
    YOUTUBE = r'youtube\.com/(channel|c|user)/[a-zA-Z0-9\-]+'
    TIKTOK = r'tiktok\.com/@[a-zA-Z0-9_\.]+'


# ─── Dominios blacklist ───────────────────────────────────────────────────────

BLACKLIST_DOMAINS = {
    "sentry.io",
    "example.com",
    "wixpress.com",
    "squarespace.com",
    "wordpress.com",
    "googleapis.com",
    "schema.org",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
}


# ─── Prefijos comunes de email ─────────────────────────────────────────────────

EMAIL_PREFIXES = [
    "info",
    "contacto",
    "ventas",
    "hola",
    "gerencia",
    "administracion",
    "soporte",
    "webmaster",
]


# ─── Palabras clave excluidas ───────────────────────────────────────────────────

EXCLUDED_KEYWORDS = [
    "holding",
    "SAC inactiva",
    "en liquidación",
    "en liquidacion",
    "quiebra",
    "cerrado",
    "cerrada",
]


# ─── Headers HTTP ───────────────────────────────────────────────────────────────

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-419,es;q=0.9",
}


# ─── Códigos de salida ─────────────────────────────────────────────────────────

class ExitCodes:
    """Códigos de salida del programa."""

    SUCCESS = 0
    ERROR = 1
    INVALID_ARGS = 2
    FILE_NOT_FOUND = 3
    NETWORK_ERROR = 4
    VALIDATION_ERROR = 5
    IO_ERROR = 6


# ─── CIIU → Industria (CIIU rev.4 — sección + división) ───────────────────────
# Clave: primeros 2 dígitos del código CIIU.
# Valor: label que coincide con ICP["target_industries"].
# Solo se mapean las secciones con fit real para Pipeline_X.
CIIU_TO_INDUSTRY: dict[str, str] = {
    # Comercio al por mayor y menor
    "45": "Comercio",      # venta/reparación vehículos
    "46": "Comercio",      # comercio al por mayor
    "47": "Retail",        # comercio al por menor
    # Construcción
    "41": "Construcción",
    "42": "Construcción",  # ingeniería civil
    "43": "Construcción",  # actividades especializadas
    # Transporte y logística
    "49": "Logística",     # transporte terrestre
    "50": "Logística",     # transporte acuático
    "51": "Logística",     # transporte aéreo
    "52": "Logística",     # almacenamiento
    "53": "Logística",     # correo y mensajería
    # Inmobiliaria
    "68": "Inmobiliaria",
    # Actividades profesionales (canal intermediario)
    "69": "Contabilidad",  # contabilidad, auditoría, teneduría
    "70": "Consultoría",   # actividades de dirección/gestión
    "71": "Consultoría",   # arquitectura, ingeniería, consultoría
    "73": "Marketing",     # publicidad y estudios de mercado
    "74": "Consultoría",   # otras actividades profesionales
}

# ─── Régimen tributario → peso de tamaño (1=micro … 4=grande) ─────────────────
# Fuente: SUNAT campo regimenTributario (cuando está disponible).
REGIMEN_SIZE: dict[str, int] = {
    "NUEVO RUS":                    1,
    "NRUS":                         1,
    "RÉGIMEN ESPECIAL":             2,
    "RER":                          2,
    "RÉGIMEN MYPE TRIBUTARIO":      3,
    "RMT":                          3,
    "RÉGIMEN GENERAL":              4,
    "RG":                           4,
}

# ─── Ubigeo (primeros 2 dígitos = departamento) → ciudad principal ─────────────
# Permite identificar la ciudad a partir del código ubigeo sin lookup completo.
UBIGEO_DEPT_TO_CITY: dict[str, str] = {
    "01": "Amazonas",    "02": "Chimbote",    "03": "Apurímac",
    "04": "Arequipa",    "05": "Ayacucho",    "06": "Cajamarca",
    "07": "Callao",      "08": "Cusco",       "09": "Huancavelica",
    "10": "Huánuco",     "11": "Ica",         "12": "Huancayo",
    "13": "Trujillo",    "14": "Chiclayo",    "15": "Lima",
    "16": "Iquitos",     "17": "Madre de Dios","18": "Moquegua",
    "19": "Pasco",       "20": "Piura",       "21": "Juliaca",
    "22": "Tarapoto",    "23": "Tacna",       "24": "Tumbes",
    "25": "Pucallpa",
}