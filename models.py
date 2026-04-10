"""
models.py — Modelos de datos para AgentePyme SDR.

Este módulo define las estructuras de datos utilizadas en la aplicación.
"""
from __future__ import annotations

import html
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

import constants as const
import utils


# ─── Lead ─────────────────────────────────────────────────────────────────────

@dataclass
class Lead:
    """
    Representa un lead (cliente potencial).

    Attributes:
        empresa: Nombre de la empresa.
        industria: Industria o sector.
        ruc: RUC (opcional).
        email: Email de contacto.
        telefono: Teléfono de contacto.
        ciudad: Ciudad.
        pais: País (default: "Peru").
        contacto_nombre: Nombre del contacto.
        cargo: Cargo del contacto.
        sitio_web: URL del sitio web.

        # Campos de scraping
        direccion: Dirección física.
        categoria_original: Categoría original de Google Maps.
        rating: Calificación (rating).
        num_resenas: Número de reseñas.
        fuente: Fuente de los datos.
        scraped_at: Fecha de scraping.

        # Campos de enriquecimiento SUNAT
        razon_social_oficial: Razón social oficial.
        estado_sunat: Estado en SUNAT.
        condicion_sunat: Condición en SUNAT.
        direccion_fiscal: Dirección fiscal.
        actividad_economica: Actividad económica.
        tipo_contribuyente: Tipo de contribuyente.

        # Campos de enriquecimiento de contactos
        email_web: Email encontrado en sitio web.
        email_web_2: Segundo email encontrado.
        email_web_3: Tercer email encontrado.
        telefono_web: Teléfono encontrado en sitio web.
        telefono_web_2: Segundo teléfono encontrado.
        linkedin: URL de LinkedIn.
        facebook: URL de Facebook.
        instagram: URL de Instagram.
        twitter: URL de Twitter.
        youtube: URL de YouTube.
        tiktok: URL de TikTok.
        dominio_web: Dominio del sitio web.
        email_estimado: Email personal estimado.
        email_estimado_2: Segundo email personal estimado.

        # Campos de calificación
        crm_stage: Etapa en el CRM.
        notas_previas: Notas previas.
        lead_score: Score del lead (0-100).
        fit_product: Encaje con el producto.
        intent_timeline: Timeline de intención.
        decision_maker: Si es tomador de decisión.
        blocker: Obstáculo principal.
        next_action: Siguiente acción recomendada.
        qualification_notes: Notas de calificación.
        draft_subject: Asunto del mensaje.
        draft_message: Cuerpo del mensaje.
        qualify_error: Error de calificación.
    """

    # Campos básicos
    empresa: str
    industria: str = ""
    ruc: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    ciudad: Optional[str] = None
    pais: str = "Peru"
    contacto_nombre: Optional[str] = None
    cargo: Optional[str] = None
    sitio_web: Optional[str] = None

    # Campos de scraping
    direccion: Optional[str] = None
    categoria_original: str = ""
    rating: Optional[str] = None
    num_resenas: Optional[str] = None
    fuente: str = ""
    scraped_at: Optional[str] = None

    # Campos de enriquecimiento SUNAT
    facturas_pendientes: int = 0
    razon_social_oficial: str = ""
    estado_sunat: str = ""
    condicion_sunat: str = ""
    direccion_fiscal: str = ""
    actividad_economica: str = ""
    tipo_contribuyente: str = ""
    capacidad_pago: str = ""           # Alta | Media | Básica | Sin datos — derivado de SUNAT

    # Campos de enriquecimiento de contactos
    email_web: str = ""
    email_web_2: str = ""
    email_web_3: str = ""
    telefono_web: str = ""
    telefono_web_2: str = ""
    linkedin: str = ""
    facebook: str = ""
    instagram: str = ""
    twitter: str = ""
    youtube: str = ""
    tiktok: str = ""
    dominio_web: str = ""
    email_estimado: str = ""
    email_estimado_2: str = ""

    # Campos de calificación
    crm_stage: str = const.CRMStages.PROSPECCION
    prioridad: str = ""                # Alta | Media | Baja — calculado post-calificación
    notas_previas: str = ""
    lead_score: int = 0
    fit_product: str = "dudoso"
    intent_timeline: str = "desconocido"
    decision_maker: str = "desconocido"
    blocker: str = ""
    next_action: str = ""
    qualification_notes: str = ""
    draft_subject: str = ""
    draft_message: str = ""
    qualify_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """
        Convierte el lead a un diccionario.

        Returns:
            Diccionario con todos los campos del lead.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Lead":
        """
        Crea un Lead desde un diccionario.

        Args:
            data: Diccionario con datos del lead.

        Returns:
            Instancia de Lead.

        Examples:
            >>> Lead.from_dict({"empresa": "ACME SAC", "industria": "Retail"})
            Lead(empresa='ACME SAC', industria='Retail', ...)
        """
        # Filtrar solo campos que existen en la clase
        valid_fields = {k: v for k, v in data.items() if k in cls.__annotations__}

        # Manejar campos opcionales None - usar valores default del dataclass
        # Crear una instancia vacía para obtener los defaults
        try:
            empty_lead = cls()
            # Usar los defaults de la instancia vacía para campos faltantes
            for field in cls.__annotations__:
                if field not in valid_fields:
                    valid_fields[field] = getattr(empty_lead, field)
        except Exception:
            # Si falla, usar valores default apropiados
            defaults = {
                const.ColumnNames.EMPRESA: "",
                const.ColumnNames.INDUSTRIA: "",
                const.ColumnNames.RUC: None,
                const.ColumnNames.EMAIL: None,
                const.ColumnNames.TELEFONO: None,
                const.ColumnNames.CIUDAD: None,
                const.ColumnNames.PAIS: "Peru",
                const.ColumnNames.FACTURAS_PENDIENTES: 0,
                const.ColumnNames.CONTACTO_NOMBRE: None,
                const.ColumnNames.CARGO: None,
                const.ColumnNames.SITIO_WEB: None,
                const.ColumnNames.LEAD_SCORE: 0,
                const.ColumnNames.CRM_STAGE: const.CRMStages.PROSPECCION,
            }
            for field in cls.__annotations__:
                if field not in valid_fields:
                    valid_fields[field] = defaults.get(field, "")

        # Convertir tipos para campos numéricos
        if const.ColumnNames.FACTURAS_PENDIENTES in valid_fields:
            try:
                valid_fields[const.ColumnNames.FACTURAS_PENDIENTES] = int(float(str(valid_fields[const.ColumnNames.FACTURAS_PENDIENTES])))
            except (ValueError, TypeError):
                valid_fields[const.ColumnNames.FACTURAS_PENDIENTES] = 0

        if const.ColumnNames.LEAD_SCORE in valid_fields:
            try:
                valid_fields[const.ColumnNames.LEAD_SCORE] = int(float(str(valid_fields[const.ColumnNames.LEAD_SCORE])))
            except (ValueError, TypeError):
                valid_fields[const.ColumnNames.LEAD_SCORE] = 0

        return cls(**valid_fields)

    def validate(self) -> list[str]:
        """
        Valida los datos del lead.

        Returns:
            Lista de errores (vacía si no hay errores).
        """
        return utils.validate_lead_data(self.to_dict())

    def is_qualified(self) -> bool:
        """
        Verifica si el lead está calificado.

        Returns:
            True si el lead está calificado, False en caso contrario.
        """
        return self.crm_stage == const.CRMStages.QUALIFIED

    def is_processed(self) -> bool:
        """
        Verifica si el lead ya fue procesado.

        Returns:
            True si el lead ya fue procesado, False en caso contrario.
        """
        return self.crm_stage in const.CRMStages.PROCESSED

    def has_contact_info(self) -> bool:
        """
        Verifica si el lead tiene información de contacto.

        Returns:
            True si tiene email o teléfono, False en caso contrario.
        """
        return bool(self.email or self.telefono)

    def get_primary_email(self) -> Optional[str]:
        """
        Obtiene el email principal del lead.

        Prioridad: email > email_web > email_estimado.

        Returns:
            Email principal o None si no hay.
        """
        return self.email or self.email_web or self.email_estimado or None

    def get_primary_phone(self) -> Optional[str]:
        """
        Obtiene el teléfono principal del lead.

        Prioridad: telefono > telefono_web.

        Returns:
            Teléfono principal o None si no hay.
        """
        return self.telefono or self.telefono_web or None

    def get_social_links(self) -> dict[str, str]:
        """
        Obtiene todos los enlaces de redes sociales.

        Returns:
            Diccionario con enlaces de redes sociales.
        """
        return {
            "linkedin": self.linkedin,
            "facebook": self.facebook,
            "instagram": self.instagram,
            "twitter": self.twitter,
            "youtube": self.youtube,
            "tiktok": self.tiktok,
        }

    def __str__(self) -> str:
        """Representación en texto del lead."""
        parts = [self.empresa]
        if self.industria:
            parts.append(f"({self.industria})")
        if self.ciudad:
            parts.append(f"- {self.ciudad}")
        return " ".join(parts)

    def __repr__(self) -> str:
        """Representación detallada del lead."""
        return f"Lead(empresa='{self.empresa}', industria='{self.industria}', score={self.lead_score}, stage='{self.crm_stage}')"


# ─── LeadList ───────────────────────────────────────────────────────────────────

@dataclass
class LeadList:
    """
    Representa una lista de leads con metadatos.

    Attributes:
        leads: Lista de leads.
        total: Total de leads.
        qualified: Cantidad de leads calificados.
        following: Cantidad de leads en seguimiento.
        prospecting: Cantidad de leads en prospección.
        discarded: Cantidad de leads descartados.
        avg_score: Score promedio.
        errors: Cantidad de errores.
        created_at: Fecha de creación.
        source: Fuente de los leads.
    """

    leads: list[Lead] = field(default_factory=list)
    total: int = 0
    qualified: int = 0
    following: int = 0
    prospecting: int = 0
    discarded: int = 0
    avg_score: float = 0.0
    errors: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = ""

    def __post_init__(self) -> None:
        """Calcula estadísticas después de la inicialización."""
        self.recalculate_stats()

    def recalculate_stats(self) -> None:
        """Recalcula las estadísticas de la lista de leads."""
        self.total = len(self.leads)
        self.qualified = sum(1 for l in self.leads if l.crm_stage == const.CRMStages.QUALIFIED)
        self.following = sum(1 for l in self.leads if l.crm_stage == const.CRMStages.FOLLOW_UP)
        self.prospecting = sum(1 for l in self.leads if l.crm_stage == const.CRMStages.PROSPECCION)
        self.discarded = sum(1 for l in self.leads if l.crm_stage == const.CRMStages.DISCARDED)
        self.errors = sum(1 for l in self.leads if bool(l.qualify_error))

        if self.leads:
            scores = [l.lead_score for l in self.leads if l.lead_score is not None]
            self.avg_score = sum(scores) / len(scores) if scores else 0.0
        else:
            self.avg_score = 0.0

    def add_lead(self, lead: Lead) -> None:
        """
        Agrega un lead a la lista.

        Args:
            lead: Lead a agregar.
        """
        self.leads.append(lead)
        self.recalculate_stats()

    def add_leads(self, leads: list[Lead]) -> None:
        """
        Agrega múltiples leads a la lista.

        Args:
            leads: Lista de leads a agregar.
        """
        self.leads.extend(leads)
        self.recalculate_stats()

    def filter_by_stage(self, stage: str) -> list[Lead]:
        """
        Filtra leads por etapa.

        Args:
            stage: Etapa a filtrar.

        Returns:
            Lista de leads en la etapa especificada.
        """
        return [l for l in self.leads if l.crm_stage == stage]

    def filter_by_score(self, min_score: int, max_score: int = 100) -> list[Lead]:
        """
        Filtra leads por rango de score.

        Args:
            min_score: Score mínimo.
            max_score: Score máximo.

        Returns:
            Lista de leads en el rango de score.
        """
        return [l for l in self.leads if min_score <= l.lead_score <= max_score]

    def filter_by_industry(self, industry: str) -> list[Lead]:
        """
        Filtra leads por industria.

        Args:
            industry: Industria a filtrar.

        Returns:
            Lista de leads en la industria especificada.
        """
        normalized_industry = utils.normalize(industry)
        return [l for l in self.leads if normalized_industry in utils.normalize(l.industria)]

    def get_top_leads(self, n: int = 10) -> list[Lead]:
        """
        Obtiene los N leads con mayor score.

        Args:
            n: Número de leads a obtener.

        Returns:
            Lista de los N leads con mayor score.
        """
        return sorted(self.leads, key=lambda l: l.lead_score or 0, reverse=True)[:n]

    def to_dict_list(self) -> list[dict[str, Any]]:
        """
        Convierte la lista de leads a una lista de diccionarios.

        Returns:
            Lista de diccionarios con los datos de los leads.
        """
        return [lead.to_dict() for lead in self.leads]

    @classmethod
    def from_dict_list(cls, data: list[dict[str, Any]], source: str = "") -> "LeadList":
        """
        Crea una LeadList desde una lista de diccionarios.

        Args:
            data: Lista de diccionarios con datos de leads.
            source: Fuente de los leads.

        Returns:
            Instancia de LeadList.
        """
        leads = [Lead.from_dict(item) for item in data]
        return cls(leads=leads, source=source)


# ─── ScrapingResult ─────────────────────────────────────────────────────────────

@dataclass
class ScrapingResult:
    """
    Resultado de una operación de scraping.

    Attributes:
        success: Si la operación fue exitosa.
        leads: Lista de leads obtenidos.
        error: Mensaje de error si falló.
        query: Query utilizada.
        timestamp: Timestamp de la operación.
    """

    success: bool = False
    leads: list[Lead] = field(default_factory=list)
    error: str = ""
    query: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self) -> str:
        """Representación en texto del resultado."""
        if self.success:
            return f"ScrapingResult(success=True, leads={len(self.leads)})"
        return f"ScrapingResult(success=False, error='{self.error}')"


# ─── QualificationResult ───────────────────────────────────────────────────────

@dataclass
class QualificationResult:
    """
    Resultado de una operación de calificación.

    Attributes:
        success: Si la operación fue exitosa.
        lead: Lead calificado.
        error: Mensaje de error si falló.
        timestamp: Timestamp de la operación.
    """

    success: bool = False
    lead: Optional[Lead] = None
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self) -> str:
        """Representación en texto del resultado."""
        if self.success and self.lead:
            return f"QualificationResult(success=True, lead={self.lead.empresa}, score={self.lead.lead_score})"
        return f"QualificationResult(success=False, error='{self.error}')"


# ─── EnrichmentResult ─────────────────────────────────────────────────────────

@dataclass
class EnrichmentResult:
    """
    Resultado de una operación de enriquecimiento.

    Attributes:
        success: Si la operación fue exitosa.
        lead: Lead enriquecido.
        fields_added: Campos que se agregaron.
        error: Mensaje de error si falló.
        timestamp: Timestamp de la operación.
    """

    success: bool = False
    lead: Optional[Lead] = None
    fields_added: list[str] = field(default_factory=list)
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self) -> str:
        """Representación en texto del resultado."""
        if self.success and self.lead:
            return f"EnrichmentResult(success=True, lead={self.lead.empresa}, fields={len(self.fields_added)})"
        return f"EnrichmentResult(success=False, error='{self.error}')"