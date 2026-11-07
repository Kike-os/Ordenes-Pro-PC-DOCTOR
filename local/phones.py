"""Teléfonos de clientes en cualquier país (1.5.251): una sola regla para validar, guardar, buscar y armar enlaces de WhatsApp.

Usa `phonenumbers` (la versión en Python de libphonenumber, la misma base de reglas que usa el formulario con libphonenumber-js), incluida en
`vendor/` como el resto de bibliotecas. Ecuador (+593) es el país predeterminado: un número escrito sin prefijo internacional se interpreta como
ecuatoriano (0991234567, 991234567, 062920000…), y uno con «+» o «00» se interpreta en su propio país, sin duplicar el código.

- `normalize(valor)` → (E.164, error): lo que se guarda al registrar o editar, p. ej. «+593991234567».
- `whatsapp(valor)` → solo cifras con código de país para wa.me, o '' si el número no sirve para WhatsApp (los fijos no). No afirma que el número
  tenga WhatsApp activo: eso solo lo sabe WhatsApp.
- `search_digits(texto)` → cifras significativas para buscar: encuentra el mismo número guardado en formato antiguo o internacional.
- `display(valor)` → formato legible («+593 99 123 4567»); si no se puede interpretar, el texto tal como está guardado.
Los números antiguos no se reescriben en la base: se interpretan al leerlos y se guardan en E.164 solo cuando alguien edita y guarda la ficha."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import phonenumbers  # noqa: E402
from phonenumbers import PhoneNumberFormat, PhoneNumberType, NumberParseException  # noqa: E402

DEFAULT_REGION = 'EC'
ALLOWED = re.compile(r'[+0-9 ().\-]{3,40}')
NOT_WHATSAPP = (PhoneNumberType.FIXED_LINE, PhoneNumberType.TOLL_FREE, PhoneNumberType.PREMIUM_RATE, PhoneNumberType.SHARED_COST, PhoneNumberType.PAGER,
                PhoneNumberType.UAN, PhoneNumberType.VOICEMAIL)
REASONS = {
    NumberParseException.INVALID_COUNTRY_CODE: 'El código de país no existe.',
    NumberParseException.NOT_A_NUMBER: 'Escribe solo números (puedes usar espacios).',
    NumberParseException.TOO_SHORT_NSN: 'El número está incompleto.',
    NumberParseException.TOO_SHORT_AFTER_IDD: 'El número está incompleto.',
    NumberParseException.TOO_LONG: 'El número tiene dígitos de más.',
}


def parse(value, region=DEFAULT_REGION):
    """Número interpretado (o None). «00» al inicio cuenta como prefijo internacional; 593… sin «+» también se reconoce si así es válido."""
    raw = str(value or '').strip()
    if not raw or not ALLOWED.fullmatch(raw):
        return None
    text = '+' + raw[2:] if raw.startswith('00') else raw
    try:
        number = phonenumbers.parse(text, region)
    except NumberParseException:
        number = None
    if number is not None and phonenumbers.is_valid_number(number):
        return number
    digits = re.sub(r'\D', '', text)
    if not text.startswith('+') or digits.startswith('593'):
        found = _ecuador(digits, text) if (region == 'EC' or text.startswith('+593')) else None
        if found:
            return found
    if not text.startswith('+') and len(digits) >= 10:  # código de país pegado sin «+», p. ej. 593991234567 o 573001234567
        try:
            alt = phonenumbers.parse('+' + digits, None)
            if phonenumbers.is_valid_number(alt):
                return alt
        except NumberParseException:
            pass
    return _ecuador(digits, text) or (number if number is not None and phonenumbers.is_valid_number(number) else None)


# Regla de Ecuador que el sistema ya aceptaba (celular 09 + 8 cifras; fijo 0[2-7] + 7 cifras): las tablas de la biblioteca no incluyen todos
# los prefijos móviles en uso (p. ej. 092, 093, 095, 097), así que un número con esta forma nunca se rechaza.
ECUADOR = re.compile(r'(?:0?9\d{8}|0[2-7]\d{7})')


def _ecuador(digits, text):
    national = digits[3:] if digits.startswith('593') and (text.startswith('+') or len(digits) >= 11) else digits
    if national.startswith('593'):
        return None
    if ECUADOR.fullmatch(national) or ECUADOR.fullmatch('0' + national):
        try:
            return phonenumbers.parse('+593' + national.lstrip('0'), None)
        except NumberParseException:
            return None
    return None


def error(value, region=DEFAULT_REGION):
    """Mensaje claro cuando el número no es válido ('' si lo es o si está vacío)."""
    raw = str(value or '').strip()
    if not raw or parse(raw, region):
        return ''
    if not ALLOWED.fullmatch(raw):
        return 'Escribe solo números, espacios y el prefijo «+».'
    text = '+' + raw[2:] if raw.startswith('00') else raw
    try:
        number = phonenumbers.parse(text, region)
    except NumberParseException as exc:
        return REASONS.get(exc.error_type, 'El número no tiene un formato válido.')
    country = phonenumbers.region_code_for_number(number) or region
    check = phonenumbers.is_possible_number_with_reason(number)
    name = COUNTRY_NAMES.get(country, country)
    if check == phonenumbers.ValidationResult.TOO_SHORT:
        return 'El número está incompleto para %s.' % name
    if check == phonenumbers.ValidationResult.TOO_LONG:
        return 'El número tiene dígitos de más para %s.' % name
    if check == phonenumbers.ValidationResult.INVALID_LENGTH:
        return 'La cantidad de dígitos no corresponde a un número de %s.' % name
    return 'El número no es válido para %s (+%s).' % (name, number.country_code)


def normalize(value, region=DEFAULT_REGION):
    """(E.164, mensaje de error). Vacío → ('', '')."""
    raw = str(value or '').strip()
    if not raw:
        return '', ''
    number = parse(raw, region)
    if not number:
        return '', error(raw, region) or 'El número no tiene un formato válido.'
    return phonenumbers.format_number(number, PhoneNumberFormat.E164), ''


def tidy(value, limit=40):
    """Para documentos (facturas, proformas): E.164 si el número es válido; si no, el texto tal como se escribió (nunca se pierde un dato)."""
    raw = str(value or '').strip()[:limit]
    return normalize(raw)[0] or raw


def valid(value, region=DEFAULT_REGION):
    return bool(parse(value, region))


def display(value):
    number = parse(value)
    return phonenumbers.format_number(number, PhoneNumberFormat.INTERNATIONAL) if number else str(value or '').strip()


def whatsapp(value):
    """Cifras con código de país para wa.me ('' si no sirve: vacío, inválido o número fijo/servicio). Nunca duplica el prefijo."""
    number = parse(value)
    if not number or phonenumbers.number_type(number) in NOT_WHATSAPP:
        return ''
    return phonenumbers.format_number(number, PhoneNumberFormat.E164)[1:]


def search_digits(text):
    """Cifras para buscar: el número nacional significativo si el texto es un teléfono reconocible; si no, el texto sin espacios ni guiones."""
    clean = str(text or '').replace('-', '').replace('+', '')
    number = parse(text) if len(re.sub(r'\D', '', str(text or ''))) >= 7 else None
    return phonenumbers.national_significant_number(number) if number else clean


def as_query(text):
    """Si todo el texto de una búsqueda es un teléfono («099 123 4567», «+57 300…»), sus cifras significativas; si no, None."""
    raw = str(text or '').strip()
    if not re.fullmatch(r'[+0-9 ().\-]+', raw) or len(re.sub(r'\D', '', raw)) < 7:
        return None
    number = parse(raw)
    return phonenumbers.national_significant_number(number) if number else None  # solo un teléfono válido cambia la búsqueda


def same(a, b):
    """True si los dos textos son el mismo teléfono (formato antiguo o internacional)."""
    x, y = parse(a), parse(b)
    return bool(x and y and x.country_code == y.country_code and x.national_number == y.national_number)


COUNTRY_NAMES = {'EC': 'Ecuador', 'CO': 'Colombia', 'PE': 'Perú', 'US': 'Estados Unidos', 'ES': 'España', 'MX': 'México', 'AR': 'Argentina', 'CL': 'Chile',
                 'VE': 'Venezuela', 'BO': 'Bolivia', 'BR': 'Brasil', 'PA': 'Panamá', 'CR': 'Costa Rica', 'IT': 'Italia', 'DE': 'Alemania', 'FR': 'Francia',
                 'GB': 'Reino Unido', 'CA': 'Canadá', 'CN': 'China', 'UY': 'Uruguay', 'PY': 'Paraguay', 'CU': 'Cuba', 'DO': 'República Dominicana'}
