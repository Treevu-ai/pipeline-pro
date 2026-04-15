"""
utils.py — Funciones utilitarias comunes para AgentePyme SDR.

Este módulo contiene funciones reutilizables utilizadas en toda la aplicación.
"""
from __future__ import annotations

import html
import logging
import re
import time
import unicodedata
import urllib.parse
from functools import wraps
from typing import Any, Callable

import constants as const

log = logging.getLogger(__name__)


# ─── Normalización de texto ────────────────────────────────────────────────────

def normalize(s: str) -> str:
    """
    Normaliza una cadena de texto.

    Quita acentos, pasa a minúsculas y elimina espacios extra.

    Args:
        s: Cadena de texto a normalizar.

    Returns:
        Cadena normalizada.

    Examples:
        >>> normalize("Café Perú")
        'cafe peru'
        >>> normalize("  Hola  Mundo  ")
        'hola mundo'
    """
    if not s:
        return ""
    # Quitar acentos
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    # Pasar a minúsculas
    s = s.lower()
    # Reemplazar múltiples espacios con uno solo
    s = re.sub(r"\s+", " ", s)
    # Quitar espacios al inicio y final
    return s.strip()


def normalize_phone(phone: str) -> str:
    """
    Normaliza un número de teléfono.

    Elimina todos los caracteres no numéricos excepto el signo +.

    Args:
        phone: Número de teléfono a normalizar.

    Returns:
        Número de teléfono normalizado.

    Examples:
        >>> normalize_phone("+51 987 654 321")
        '+51987654321'
        >>> normalize_phone("(01) 123-4567")
        '011234567'
    """
    if not phone:
        return ""
    # Mantener solo dígitos y el signo +
    return re.sub(r"[^\d+]", "", phone)


def normalize_email(email: str) -> str:
    """
    Normaliza una dirección de email.

    Pasa a minúsculas y elimina espacios.

    Args:
        email: Dirección de email a normalizar.

    Returns:
        Email normalizado.

    Examples:
        >>> normalize_email("Usuario@Ejemplo.COM")
        'usuario@ejemplo.com'
    """
    if not email:
        return ""
    return email.strip().lower()


# ─── Validación ───────────────────────────────────────────────────────────────

def is_valid_email(email: str) -> bool:
    """
    Valida si una cadena es una dirección de email válida.

    Args:
        email: Cadena a validar.

    Returns:
        True si es un email válido, False en caso contrario.

    Examples:
        >>> is_valid_email("usuario@ejemplo.com")
        True
        >>> is_valid_email("invalid-email")
        False
    """
    if not email:
        return False
    pattern = re.compile(const.RegexPatterns.EMAIL, re.IGNORECASE)
    return bool(pattern.match(email.strip()))


def is_valid_phone(phone: str) -> bool:
    """
    Valida si una cadena es un número de teléfono válido.

    Args:
        phone: Cadena a validar.

    Returns:
        True si es un teléfono válido, False en caso contrario.

    Examples:
        >>> is_valid_phone("+51987654321")
        True
        >>> is_valid_phone("123")
        False
    """
    if not phone:
        return False
    normalized = normalize_phone(phone)
    # Mínimo 9 dígitos (sin contar el +)
    digits = re.sub(r"[^\d]", "", normalized)
    return len(digits) >= const.EnrichmentConstants.MIN_PHONE_DIGITS


def is_valid_ruc(ruc: str) -> bool:
    """
    Valida si una cadena es un RUC peruano válido.

    Args:
        ruc: Cadena a validar.

    Returns:
        True si es un RUC válido, False en caso contrario.

    Examples:
        >>> is_valid_ruc("20123456789")
        True
        >>> is_valid_ruc("123")
        False
    """
    if not ruc:
        return False
    # RUC peruano: 11 dígitos
    digits = re.sub(r"\D", "", str(ruc))
    return len(digits) == 11


# ─── Sanitización ─────────────────────────────────────────────────────────────

def sanitize_string(s: str) -> str:
    """
    Sanitiza una cadena para prevenir inyección de código.

    Escapa caracteres HTML y elimina caracteres de control.

    Args:
        s: Cadena a sanitizar.

    Returns:
        Cadena sanitizada.

    Examples:
        >>> sanitize_string("<script>alert('xss')</script>")
        '&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;'
    """
    if not s:
        return ""
    # Escapar HTML
    s = html.escape(s)
    # Remover caracteres de control (excepto \n, \r, \t)
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', s)
    return s


def sanitize_filename(filename: str) -> str:
    """
    Sanitiza un nombre de archivo para que sea seguro.

    Elimina caracteres inválidos para nombres de archivo.

    Args:
        filename: Nombre de archivo a sanitizar.

    Returns:
        Nombre de archivo seguro.

    Examples:
        >>> sanitize_filename("archivo/inválido*.txt")
        'archivo_invalido.txt'
    """
    if not filename:
        return ""
    # Reemplazar caracteres inválidos con guion bajo
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    return re.sub(invalid_chars, '_', filename)


# ─── Manipulación de URLs ───────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """
    Normaliza una URL.

    Asegura que tenga el protocolo https://.

    Args:
        url: URL a normalizar.

    Returns:
        URL normalizada.

    Examples:
        >>> normalize_url("example.com")
        'https://example.com'
        >>> normalize_url("http://example.com")
        'https://example.com'
    """
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Preferir https
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url


def extract_domain(url: str) -> str:
    """
    Extrae el dominio de una URL.

    Args:
        url: URL de la cual extraer el dominio.

    Returns:
        Dominio extraído (sin www.).

    Examples:
        >>> extract_domain("https://www.example.com/path")
        'example.com'
        >>> extract_domain("example.com")
        'example.com'
    """
    if not url:
        return ""
    url = normalize_url(url)
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    # Quitar www.
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def is_valid_url(url: str) -> bool:
    """
    Valida si una cadena es una URL válida.

    Args:
        url: Cadena a validar.

    Returns:
        True si es una URL válida, False en caso contrario.

    Examples:
        >>> is_valid_url("https://example.com")
        True
        >>> is_valid_url("not-a-url")
        False
    """
    if not url:
        return False
    try:
        result = urllib.parse.urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


# ─── Rate limiting ─────────────────────────────────────────────────────────────

def rate_limit(calls: int, period: float):
    """
    Decorador para limitar la tasa de llamadas a una función.

    Args:
        calls: Número máximo de llamadas permitidas.
        period: Período de tiempo en segundos.

    Returns:
        Decorador de función.

    Examples:
        >>> @rate_limit(calls=5, period=60)
        ... def fetch_data():
        ...     # Esta función se puede llamar máximo 5 veces por minuto
        ...     pass
    """
    def decorator(func: Callable) -> Callable:
        last_called = [0.0]
        calls_made = [0]

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            now = time.time()
            elapsed = now - last_called[0]

            # Reiniciar contador si pasó el período
            if elapsed > period:
                calls_made[0] = 0
                last_called[0] = now

            # Si se excedió el límite, esperar
            if calls_made[0] >= calls:
                sleep_time = period - elapsed
                if sleep_time > 0:
                    log.debug("Rate limit: esperando %.2fs", sleep_time)
                    time.sleep(sleep_time)
                calls_made[0] = 0
                last_called[0] = time.time()

            calls_made[0] += 1
            return func(*args, **kwargs)

        return wrapper
    return decorator


# ─── Extracción de datos ───────────────────────────────────────────────────────

def extract_emails_from_text(text: str) -> list[str]:
    """
    Extrae emails únicos de un texto.

    Args:
        text: Texto del cual extraer emails.

    Returns:
        Lista de emails únicos encontrados.

    Examples:
        >>> extract_emails_from_text("Contactar a info@ejemplo.com o ventas@ejemplo.com")
        ['info@ejemplo.com', 'ventas@ejemplo.com']
    """
    if not text:
        return []

    # Buscar emails con patrón regex
    pattern = re.compile(const.RegexPatterns.EMAIL, re.IGNORECASE)
    emails = pattern.findall(text)

    # Filtrar dominios blacklist
    valid_emails = []
    for email in emails:
        email = email.strip().lower()
        if "@" in email:
            domain = email.split("@")[-1]
            if domain not in const.BLACKLIST_DOMAINS:
                valid_emails.append(email)

    # Deduplicar preservando orden
    seen = set()
    result = []
    for email in valid_emails:
        if email not in seen:
            seen.add(email)
            result.append(email)

    return result


def extract_phones_from_text(text: str) -> list[str]:
    """
    Extrae números de teléfono únicos de un texto.

    Args:
        text: Texto del cual extraer teléfonos.

    Returns:
        Lista de teléfonos únicos encontrados.

    Examples:
        >>> extract_phones_from_text("Llamar al +51 987 654 321 o al 01-123-4567")
        ['+51987654321', '011234567']
    """
    if not text:
        return []

    phones = []

    # Probar múltiples patrones
    patterns = [
        const.RegexPatterns.PHONE,
        const.RegexPatterns.PHONE_ALT,
        const.RegexPatterns.PHONE_SIMPLE,
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0] if match else ""
            normalized = normalize_phone(match)
            if is_valid_phone(normalized):
                phones.append(normalized)

    # Deduplicar
    seen = set()
    result = []
    for phone in phones:
        if phone not in seen:
            seen.add(phone)
            result.append(phone)

    return result


def guess_personal_emails(nombre: str, dominio: str) -> list[str]:
    """
    Genera emails personales probables basados en el nombre.

    Args:
        nombre: Nombre completo de la persona.
        dominio: Dominio del email (ej: "empresa.com").

    Returns:
        Lista de emails probables.

    Examples:
        >>> guess_personal_emails("Juan Pérez", "empresa.com")
        ['juan.perez@empresa.com', 'juanperez@empresa.com', 'juan_perez@empresa.com', ...]
    """
    if not nombre or not dominio:
        return []

    # Extraer primer nombre y apellido
    partes = [normalize(p) for p in nombre.split() if p]
    if not partes:
        return []

    primer_nombre = partes[0]
    apellido = partes[-1] if len(partes) > 1 else ""

    # Generar patrones comunes
    patrones = []

    if apellido:
        patrones.extend([
            f"{primer_nombre}.{apellido}@{dominio}",
            f"{primer_nombre}{apellido}@{dominio}",
            f"{primer_nombre}_{apellido}@{dominio}",
            f"{apellido}.{primer_nombre}@{dominio}",
            f"{apellido}{primer_nombre}@{dominio}",
        ])

    patrones.extend([
        f"{primer_nombre}@{dominio}",
        f"{apellido}@{dominio}" if apellido else "",
    ])

    # Patrones con iniciales
    if len(partes) >= 2 and apellido:
        inicial_apellido = apellido[0]
        patrones.extend([
            f"{primer_nombre}{inicial_apellido}@{dominio}",
            f"{inicial_apellido}{primer_nombre}@{dominio}",
        ])

    # Filtrar vacíos y deduplicar
    return list({p for p in patrones if p})


# ─── Truncado seguro ─────────────────────────────────────────────────────────

def trunc(s: object, n: int = 2000) -> str:
    """
    Convierte *s* a cadena y trunca a *n* caracteres de forma segura.

    Útil para registrar cuerpos HTTP largos en logs sin volcar secrets completos.

    Args:
        s: Objeto a convertir y truncar.
        n: Número máximo de caracteres (default: 2000).

    Returns:
        Cadena truncada con sufijo ``…`` si se truncó.

    Examples:
        >>> trunc("abcde", 3)
        'abc…'
        >>> trunc("ab", 10)
        'ab'
    """
    text = str(s) if not isinstance(s, str) else s
    if len(text) <= n:
        return text
    return text[:n] + "…"


# ─── Formateo ─────────────────────────────────────────────────────────────────

def format_currency(amount: float, currency: str = "PEN") -> str:
    """
    Formatea un monto como moneda.

    Args:
        amount: Monto a formatear.
        currency: Código de moneda (default: "PEN").

    Returns:
        Monto formateado.

    Examples:
        >>> format_currency(1234.56)
        'S/ 1,234.56'
    """
    symbols = {"PEN": "S/", "USD": "$", "EUR": "€"}
    symbol = symbols.get(currency, currency)
    return f"{symbol} {amount:,.2f}"


def truncate_words(text: str, max_words: int, suffix: str = "…") -> str:
    """
    Trunca un texto a un número máximo de palabras.

    Args:
        text: Texto a truncar.
        max_words: Número máximo de palabras.
        suffix: Sufijo a agregar si se truncó.

    Returns:
        Texto truncado.

    Examples:
        >>> truncate_words("Este es un texto largo", 3)
        'Este es un…'
    """
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + suffix


# ─── Logging ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir: str, level: int = logging.INFO) -> logging.Logger:
    """
    Configura el logging para la aplicación.

    Args:
        log_dir: Directorio donde guardar los logs.
        level: Nivel de logging.

    Returns:
        Logger configurado.
    """
    from pathlib import Path

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / f"agentepyme_{time.strftime('%Y%m%d_%H%M%S')}.log"

    fmt = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Configurar logging básico
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
    )

    # Agregar handler de archivo
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    logger = logging.getLogger("agentepyme")
    logger.addHandler(fh)
    logger.setLevel(level)

    log.info("Log guardado en: %s", log_file)

    return logger


# ─── Validación de datos de lead ───────────────────────────────────────────────

def validate_lead_data(data: dict) -> list[str]:
    """
    Valida los datos de un lead y devuelve una lista de errores.

    Args:
        data: Diccionario con datos del lead.

    Returns:
        Lista de mensajes de error (vacía si no hay errores).

    Examples:
        >>> validate_lead_data({"empresa": "ACME SAC"})
        []
        >>> validate_lead_data({})
        ['Falta campo obligatorio: empresa']
    """
    errors = []

    # Campos obligatorios
    required_fields = [
        const.ColumnNames.EMPRESA,
    ]

    for field in required_fields:
        if not data.get(field):
            errors.append(f"Falta campo obligatorio: {field}")

    # Validar email si está presente
    email = data.get(const.ColumnNames.EMAIL, "")
    if email and not is_valid_email(email):
        errors.append(f"Email inválido: {email}")

    # Validar teléfono si está presente
    phone = data.get(const.ColumnNames.TELEFONO, "")
    if phone and not is_valid_phone(phone):
        errors.append(f"Teléfono inválido: {phone}")

    # Validar RUC si está presente
    ruc = data.get(const.ColumnNames.RUC, "")
    if ruc and not is_valid_ruc(ruc):
        errors.append(f"RUC inválido: {ruc}")

    # Validar URL si está presente
    sitio_web = data.get(const.ColumnNames.SITIO_WEB, "")
    if sitio_web and not is_valid_url(sitio_web):
        errors.append(f"URL inválida: {sitio_web}")

    # Validar facturas_pendientes si está presente
    facturas = data.get(const.ColumnNames.FACTURAS_PENDIENTES)
    if facturas is not None:
        try:
            if int(float(str(facturas))) < 0:
                errors.append(f"facturas_pendientes no puede ser negativo: {facturas}")
        except (ValueError, TypeError):
            errors.append(f"facturas_pendientes debe ser un número: {facturas}")

    return errors