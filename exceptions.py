"""
exceptions.py — Excepciones personalizadas para AgentePyme SDR.

Este módulo define todas las excepciones personalizadas utilizadas
en la aplicación para un manejo de errores más específico.
"""
from __future__ import annotations


# ─── Excepción base ───────────────────────────────────────────────────────────

class AgentePymeError(Exception):
    """
    Excepción base para todos los errores de AgentePyme SDR.

    Todas las excepciones personalizadas deben heredar de esta clase.
    """

    def __init__(self, message: str, details: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error principal.
            details: Detalles adicionales del error (opcional).
        """
        self.message = message
        self.details = details or ""
        super().__init__(self.message)

    def __str__(self) -> str:
        """Representación en texto de la excepción."""
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message


# ─── Errores de validación ─────────────────────────────────────────────────────

class ValidationError(AgentePymeError):
    """
    Excepción para errores de validación de datos.

    Se lanza cuando los datos de entrada no cumplen con los requisitos.
    """

    pass


class LeadValidationError(ValidationError):
    """
    Excepción para errores de validación de datos de un lead.

    Se lanza cuando los datos de un lead son inválidos.
    """

    def __init__(self, message: str, field: str | None = None, value: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            field: Campo que causó el error (opcional).
            value: Valor que causó el error (opcional).
        """
        self.field = field
        self.value = value
        details = f"campo={field}, valor={value}" if field and value else ""
        super().__init__(message, details)


class ConfigValidationError(ValidationError):
    """
    Excepción para errores de validación de configuración.

    Se lanza cuando la configuración es inválida.
    """

    pass


# ─── Errores de scraping ───────────────────────────────────────────────────────

class ScrapingError(AgentePymeError):
    """
    Excepción base para errores de scraping.

    Se lanza cuando ocurre un error durante el scraping de datos.
    """

    pass


class GoogleMapsError(ScrapingError):
    """
    Excepción para errores específicos de Google Maps.

    Se lanza cuando hay problemas al scrapear Google Maps.
    """

    pass


class WebsiteScrapingError(ScrapingError):
    """
    Excepción para errores al scrapear un sitio web.

    Se lanza cuando hay problemas al extraer datos de un sitio web.
    """

    def __init__(self, message: str, url: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            url: URL que causó el error (opcional).
        """
        self.url = url
        details = f"url={url}" if url else ""
        super().__init__(message, details)


class SunatError(ScrapingError):
    """
    Excepción para errores al consultar SUNAT.

    Se lanza cuando hay problemas con la API de SUNAT.
    """

    def __init__(self, message: str, ruc: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            ruc: RUC que causó el error (opcional).
        """
        self.ruc = ruc
        details = f"ruc={ruc}" if ruc else ""
        super().__init__(message, details)


# ─── Errores de calificación ───────────────────────────────────────────────────

class QualificationError(AgentePymeError):
    """
    Excepción base para errores de calificación.

    Se lanza cuando ocurre un error durante la calificación de leads.
    """

    pass


class OllamaError(QualificationError):
    """
    Excepción para errores al comunicarse con Ollama.

    Se lanza cuando hay problemas con la API de Ollama.
    """

    def __init__(self, message: str, model: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            model: Modelo que causó el error (opcional).
        """
        self.model = model
        details = f"model={model}" if model else ""
        super().__init__(message, details)


class LLMResponseError(QualificationError):
    """
    Excepción para errores en la respuesta del LLM.

    Se lanza cuando la respuesta del LLM es inválida o no se puede parsear.
    """

    def __init__(self, message: str, response: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            response: Respuesta que causó el error (opcional).
        """
        self.response = response
        details = f"response={response[:100]}..." if response and len(response) > 100 else f"response={response}"
        super().__init__(message, details)


# ─── Errores de enriquecimiento ───────────────────────────────────────────────

class EnrichmentError(AgentePymeError):
    """
    Excepción base para errores de enriquecimiento.

    Se lanza cuando ocurre un error durante el enriquecimiento de leads.
    """

    pass


class GoogleSearchError(EnrichmentError):
    """
    Excepción para errores al buscar en Google.

    Se lanza cuando hay problemas con la búsqueda de Google.
    """

    def __init__(self, message: str, query: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            query: Query que causó el error (opcional).
        """
        self.query = query
        details = f"query={query}" if query else ""
        super().__init__(message, details)


class ContactExtractionError(EnrichmentError):
    """
    Excepción para errores al extraer información de contacto.

    Se lanza cuando hay problemas al extraer emails, teléfonos, etc.
    """

    pass


# ─── Errores de E/S ───────────────────────────────────────────────────────────

class IOError(AgentePymeError):
    """
    Excepción base para errores de entrada/salida.

    Se lanza cuando hay problemas con archivos, CSV, etc.
    """

    pass


class CSVError(IOError):
    """
    Excepción para errores al procesar archivos CSV.

    Se lanza cuando hay problemas al leer o escribir CSV.
    """

    def __init__(self, message: str, file_path: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            file_path: Ruta del archivo que causó el error (opcional).
        """
        self.file_path = file_path
        details = f"file={file_path}" if file_path else ""
        super().__init__(message, details)


class FileNotFoundError(IOError):
    """
    Excepción para archivos no encontrados.

    Se lanza cuando un archivo requerido no existe.
    """

    def __init__(self, message: str, file_path: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            file_path: Ruta del archivo no encontrado (opcional).
        """
        self.file_path = file_path
        details = f"file={file_path}" if file_path else ""
        super().__init__(message, details)


# ─── Errores de red ───────────────────────────────────────────────────────────

class NetworkError(AgentePymeError):
    """
    Excepción base para errores de red.

    Se lanza cuando hay problemas de conectividad.
    """

    pass


class HTTPError(NetworkError):
    """
    Excepción para errores HTTP.

    Se lanza cuando una petición HTTP falla.
    """

    def __init__(self, message: str, status_code: int | None = None, url: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            status_code: Código de estado HTTP (opcional).
            url: URL que causó el error (opcional).
        """
        self.status_code = status_code
        self.url = url
        details = f"status={status_code}, url={url}" if status_code and url else ""
        super().__init__(message, details)


class TimeoutError(NetworkError):
    """
    Excepción para timeouts de red.

    Se lanza cuando una petición excede el tiempo límite.
    """

    def __init__(self, message: str, url: str | None = None, timeout: float | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            url: URL que causó el timeout (opcional).
            timeout: Tiempo límite excedido (opcional).
        """
        self.url = url
        self.timeout = timeout
        details = f"url={url}, timeout={timeout}s" if url and timeout else ""
        super().__init__(message, details)


class RateLimitError(NetworkError):
    """
    Excepción para errores de rate limiting.

    Se lanza cuando se excede el límite de peticiones.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            retry_after: Tiempo sugerido para reintentar (opcional).
        """
        self.retry_after = retry_after
        details = f"retry_after={retry_after}s" if retry_after else ""
        super().__init__(message, details)


# ─── Errores de configuración ─────────────────────────────────────────────────

class ConfigurationError(AgentePymeError):
    """
    Excepción para errores de configuración.

    Se lanza cuando hay problemas con la configuración de la aplicación.
    """

    pass


class OllamaNotAvailableError(ConfigurationError):
    """
    Excepción cuando Ollama no está disponible.

    Se lanza cuando no se puede conectar con Ollama.
    """

    pass


class PlaywrightNotAvailableError(ConfigurationError):
    """
    Excepción cuando Playwright no está disponible.

    Se lanza cuando Playwright no está instalado o configurado.
    """

    pass


# ─── Errores de pipeline ───────────────────────────────────────────────────────

class PipelineError(AgentePymeError):
    """
    Excepción para errores en el pipeline.

    Se lanza cuando hay problemas en la ejecución del pipeline.
    """

    pass


class StepFailedError(PipelineError):
    """
    Excepción cuando un paso del pipeline falla.

    Se lanza cuando un paso específico del pipeline falla.
    """

    def __init__(self, message: str, step: str | None = None) -> None:
        """
        Inicializa la excepción.

        Args:
            message: Mensaje de error.
            step: Paso que falló (opcional).
        """
        self.step = step
        details = f"step={step}" if step else ""
        super().__init__(message, details)