"""WhatsApp Business · API oficial de Meta (Cloud API) para los avisos al cliente (1.5.275).

- Credenciales SOLO en el servidor (variables de entorno): WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_BUSINESS_ACCOUNT_ID,
  WHATSAPP_APP_SECRET y WHATSAPP_VERIFY_TOKEN (WHATSAPP_API_VERSION opcional). Nunca se devuelven al navegador ni se escriben en registros:
  la interfaz solo recibe «presente / falta» y, para los identificadores, los últimos cuatro dígitos.
- Cola propia (whatsapp_outbox), independiente del correo: pendiente → enviando → enviado → entregado → leído, o fallido / omitido con el
  motivo real. «Enviado» = aceptado por la API de Meta (con su identificador); «entregado» y «leído» llegan solo por el webhook firmado.
- Un aviso por evento (clave única): reintentos, dobles clics o dos procesos a la vez no duplican mensajes. Antes de enviar se reclama la
  fila (enviando + bloqueo) y se comprueba de nuevo que el aviso siga siendo cierto (p. ej., que la orden siga en ese estado).
- Reintentos automáticos solo para errores temporales (red, límite de envíos, servicio no disponible), con espera creciente y un máximo.
  Errores permanentes (número sin WhatsApp, plantilla inexistente o rechazada, falta de autorización) no se reintentan solos.
- Autorización del cliente: registro inmutable por número (whatsapp_consents). Sin autorización vigente no se envía ningún aviso; las citas
  usan la autorización marcada al reservar («correo electrónico o WhatsApp»). Un «BAJA» o «STOP» del cliente registra su rechazo.
- Los envíos automáticos empiezan APAGADOS: administración los activa después de comprobar la conexión y hacer un envío de prueba."""
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

API_VERSION = 'v26.0'  # versión vigente de Graph API (julio de 2026); WHATSAPP_API_VERSION la sustituye
# Fechas de retiro publicadas por Meta para las versiones que pueden quedar configuradas.
VERSION_EXPIRY = {'v19.0': '2026-05-21', 'v20.0': '2026-09-24', 'v21.0': '2027-01-21', 'v25.0': '2028-07-29'}
GRAPH = 'https://graph.facebook.com'
TRANSPORT = None  # en pruebas: función (método, url, cabeceras, cuerpo) -> (estado HTTP, dict); nunca se llama a Meta
SETTING = 'whatsapp_settings'
STATES = ('pendiente', 'enviando', 'enviado', 'entregado', 'leido', 'fallido', 'omitido')
STATE_LABELS = {'pendiente': 'Pendiente', 'enviando': 'Enviando', 'enviado': 'Enviado', 'entregado': 'Entregado', 'leido': 'Leído', 'fallido': 'Fallido', 'omitido': 'Omitido'}
DONE = ('enviado', 'entregado', 'leido')
MAX_AUTO = 5                      # intentos automáticos (solo errores temporales)
MAX_TOTAL = 10                    # tope absoluto, contando los reintentos manuales
BACKOFF = (2, 10, 30, 120)        # minutos entre intentos automáticos
LOCK_SECONDS = 120
AUTO_DELAY = 3                    # minutos de gracia en los avisos de estado: una corrección rápida no llega al cliente
REPEAT_HOURS = 72
ONCE = ('orden_registrada', 'diagnostico', 'reparacion_iniciada', 'reparacion_finalizada', 'entregado')  # una sola vez por orden

# Variables de entorno: (nombre, descripción, obligatoria, tipo, dónde se obtiene).
REQUIREMENTS = (
    ('WHATSAPP_TOKEN', 'Token de acceso permanente', True, 'secret',
     'Meta Business Suite → Configuración del negocio → Usuarios del sistema → (usuario administrador) → Generar token, con los permisos '
     'whatsapp_business_messaging y whatsapp_business_management y sin caducidad.'),
    ('WHATSAPP_PHONE_NUMBER_ID', 'Identificador del número (Phone Number ID)', True, 'id',
     'developers.facebook.com → tu aplicación → WhatsApp → Configuración de la API → «Identificador del número de teléfono».'),
    ('WHATSAPP_BUSINESS_ACCOUNT_ID', 'Identificador de la cuenta de WhatsApp Business (WABA ID)', True, 'id',
     'Misma pantalla: «Identificador de la cuenta de WhatsApp Business». Se usa para consultar plantillas y el webhook.'),
    ('WHATSAPP_APP_SECRET', 'Clave secreta de la aplicación (App Secret)', True, 'secret',
     'developers.facebook.com → tu aplicación → Configuración de la aplicación → Básica → «Clave secreta». Valida la firma del webhook.'),
    ('WHATSAPP_VERIFY_TOKEN', 'Token de verificación del webhook', True, 'secret',
     'Un texto largo y aleatorio que eliges tú. Se escribe igual en Meta (WhatsApp → Configuración → Webhook → «Token de verificación»).'),
    ('WHATSAPP_API_VERSION', 'Versión de Graph API', False, 'option', 'Opcional. Si no se define se usa %s, la versión vigente.' % API_VERSION),
)

# Eventos: código → (etiqueta, grupo, frase para la plantilla general, cuándo se envía, automático).
EVENTS = {
    'orden_registrada': ('Orden de reparación registrada', 'orden', 'registramos su equipo {equipo} con la orden de servicio {ref}', 'Al registrar la orden en la recepción.', True),
    'diagnostico': ('Equipo en proceso de diagnóstico', 'orden', 'su equipo {equipo} está en proceso de diagnóstico', 'Cuando la orden pasa a «Diagnóstico en proceso».', True),
    'diagnostico_terminado': ('Diagnóstico terminado', 'orden', 'terminamos el diagnóstico de su equipo {equipo}', 'Lo envía el personal desde la orden: solo el técnico sabe cuándo terminó.', False),
    'presupuesto_pendiente': ('Presupuesto pendiente de aprobación', 'orden', 'el presupuesto de su equipo {equipo} está pendiente de su aprobación',
                              'Cuando la orden pasa a «Pendiente de aprobación de presupuesto» con un presupuesto realmente enviado.', True),
    'presupuesto_aprobado': ('Presupuesto aprobado', 'orden', 'registramos la aprobación del presupuesto de su equipo {equipo}', 'Cuando se registra la aprobación (total o parcial).', True),
    'presupuesto_rechazado': ('Presupuesto rechazado', 'orden', 'registramos que no aprobó el presupuesto de su equipo {equipo}; no realizaremos ningún trabajo sin su autorización',
                              'Cuando se registra que el cliente no aprobó el presupuesto.', True),
    'esperando_cliente': ('Esperando respuesta del cliente', 'orden', 'necesitamos su respuesta para continuar con el servicio de su equipo {equipo}',
                          'Cuando la orden pasa a «Esperando respuesta del cliente».', True),
    'esperando_repuesto': ('Equipo en espera de repuesto', 'orden', 'su equipo {equipo} espera un repuesto que ya fue solicitado',
                           'Cuando la orden pasa a «Esperando repuesto» con un pedido activo.', True),
    'revision_recurrente': ('Revisión por falla recurrente', 'orden', 'su equipo {equipo} ingresó a una revisión técnica adicional', 'Cuando la orden pasa a «Revisión por falla recurrente».', True),
    'reparacion_iniciada': ('Reparación iniciada', 'orden', 'comenzó la reparación de su equipo {equipo}', 'Cuando la orden pasa a «Reparación en proceso» por primera vez.', True),
    'reparacion_finalizada': ('Reparación finalizada', 'orden', 'terminó la reparación de su equipo {equipo} y realizamos las pruebas de calidad',
                              'Cuando la orden pasa a «Pruebas técnicas y control de calidad».', True),
    'listo': ('Equipo listo para entregar', 'orden', 'su equipo {equipo} está listo para retirar en nuestro local', 'Cuando la orden pasa a «Listo para entregar».', True),
    'entregado': ('Equipo entregado', 'orden', 'registramos la entrega de su equipo {equipo}. Gracias por confiar en PC-DOCTOR', 'Cuando la orden pasa a «Entregado».', True),
    'recordatorio_entrega': ('Recordatorio de entrega', 'orden', 'su equipo {equipo} está listo y espera su retiro en nuestro local',
                             'A los días configurados en «Listo para entregar» sin retiro (una vez por plazo). También desde la orden.', True),
    'repuesto_solicitado': ('Repuesto solicitado', 'repuesto', 'el repuesto {repuesto} para su orden {ref} fue solicitado y confirmado', 'Cuando el pedido del repuesto queda confirmado.', True),
    'repuesto_enviado': ('Repuesto enviado', 'repuesto', 'el repuesto {repuesto} para su orden {ref} fue despachado hacia PC-DOCTOR', 'Cuando el repuesto se despacha.', True),
    'repuesto_en_pais': ('Repuesto en Ecuador', 'repuesto', 'el repuesto {repuesto} para su orden {ref} llegó a Ecuador', 'Cuando el repuesto llega al país.', True),
    'repuesto_aduana': ('Repuesto en aduana', 'repuesto', 'el repuesto {repuesto} para su orden {ref} está en proceso de aduana', 'Cuando ingresa al proceso de aduana.', True),
    'repuesto_liberado': ('Repuesto liberado de aduana', 'repuesto', 'el repuesto {repuesto} para su orden {ref} fue liberado de aduana', 'Cuando la aduana lo libera.', True),
    'repuesto_recibido': ('Repuesto recibido en PC-DOCTOR', 'repuesto', 'el repuesto {repuesto} para su orden {ref} llegó a nuestro taller', 'Cuando el repuesto llega al taller.', True),
    'repuesto_retraso': ('Retraso del repuesto', 'repuesto', 'la llegada del repuesto {repuesto} para su orden {ref} presenta un retraso', 'Cuando se registra un retraso importante.', True),
    'cancelacion_solicitada': ('Solicitud de cancelación recibida', 'repuesto', 'recibimos su solicitud de cancelación del repuesto {repuesto} de la orden {ref}',
                               'Cuando se registra la solicitud de cancelación del repuesto.', True),
    'pedido_cancelado': ('Pedido cancelado', 'repuesto', 'el pedido del repuesto {repuesto} de su orden {ref} fue cancelado', 'Cuando administración aprueba la cancelación del pedido.', True),
    'cancelacion_rechazada': ('Cancelación no aprobada', 'repuesto', 'su solicitud de cancelación del repuesto {repuesto} de la orden {ref} no pudo aprobarse',
                              'Cuando la solicitud de cancelación no se aprueba.', True),
    'reembolso': ('Reembolso registrado', 'repuesto', 'registramos un reembolso relacionado con el repuesto {repuesto} de su orden {ref}', 'Cuando se registra el reembolso.', True),
    'cita_registrada': ('Cita registrada', 'cita', 'registramos su solicitud de cita {ref} para el {cuando}', 'Cuando se registra una cita por confirmar.', True),
    'cita_confirmada': ('Cita confirmada', 'cita', 'su cita {ref} quedó confirmada para el {cuando}', 'Cuando la cita queda confirmada.', True),
    'cita_reprogramada': ('Cita reprogramada', 'cita', 'su cita {ref} fue reprogramada para el {cuando}', 'Cuando la cita cambia de fecha u hora.', True),
    'cita_cancelada': ('Cita cancelada', 'cita', 'su cita {ref} del {cuando} fue cancelada', 'Cuando la cita se cancela.', True),
    # 1.5.278 · PQRS: solo si el cliente marcó la autorización de WhatsApp en el formulario.
    'pqrs_recibida': ('PQRS recibida', 'pqrs', 'registramos su {tipo} con el número {ref}; le responderemos por correo y por este medio', 'Cuando el cliente envía una PQRS.', True),
    'pqrs_actualizada': ('Actualización de la PQRS', 'pqrs', 'su solicitud {ref} está ahora «{estado}»', 'Cuando cambia el estado de la PQRS (incluido el cierre).', True),
    'pqrs_respondida': ('Respuesta a la PQRS', 'pqrs', 'respondimos su solicitud {ref}; puede leer la respuesta en su correo o en el enlace de seguimiento', 'Cuando el personal responde al cliente.', True),
}
GROUPS = {'orden': 'Órdenes de reparación', 'repuesto': 'Repuestos', 'cita': 'Citas', 'pqrs': 'PQRS'}
# Datos que recibe la plantilla propia de cada evento ({{1}}, {{2}}, {{3}}).
PARAMS = {'orden': ('Nombre del cliente', 'Número de orden', 'Equipo'), 'repuesto': ('Nombre del cliente', 'Número de orden', 'Repuesto'),
          'cita': ('Nombre del cliente', 'Código de la cita', 'Fecha y hora'), 'pqrs': ('Nombre del cliente', 'Código PQRS', 'Estado')}
GENERAL_PARAMS = ('Nombre del cliente', 'Número de orden o de cita', 'Texto del aviso')
# Estado de la orden → evento de WhatsApp.
STATUS_EVENTS = {'diagnostico': 'diagnostico', 'presupuesto': 'presupuesto_pendiente', 'esperando_cliente': 'esperando_cliente', 'esperando_repuesto': 'esperando_repuesto',
                 'revision_recurrente': 'revision_recurrente', 'reparacion': 'reparacion_iniciada', 'pruebas': 'reparacion_finalizada', 'listo': 'listo', 'entregado': 'entregado'}
# Evento de repuesto (part_notices) → evento de WhatsApp. El «listo» del repuesto es el mismo aviso que el del estado: no se repite.
PART_EVENTS = {'confirmado': 'repuesto_solicitado', 'despachado': 'repuesto_enviado', 'llegada_pais': 'repuesto_en_pais', 'aduana_revision': 'repuesto_aduana',
               'aduana_liberado': 'repuesto_liberado', 'recibido': 'repuesto_recibido', 'listo': 'listo', 'retraso': 'repuesto_retraso',
               'cancelacion_solicitada': 'cancelacion_solicitada', 'cancelacion_aprobada': 'pedido_cancelado', 'cancelacion_rechazada': 'cancelacion_rechazada', 'reembolso': 'reembolso'}
APPOINTMENT_EVENTS = {'confirmation': 'cita_confirmada', 'rescheduled': 'cita_reprogramada', 'cancelled': 'cita_cancelada', 'registered': 'cita_registrada'}
CONSENT_SOURCES = {'presencial': 'En persona (recepción)', 'telefono': 'Por llamada telefónica', 'mensaje': 'Por mensaje escrito del cliente', 'formulario': 'Formulario firmado',
                   'baja': 'El cliente escribió BAJA o STOP'}
OPT_OUT = re.compile(r'^\s*(baja|stop|parar|no deseo (recibir )?(mas |más )?(avisos|mensajes)|cancelar avisos|darme de baja|unsubscribe)\s*[.!]*\s*$', re.I)
TEMPLATE_NAME = re.compile(r'^[a-z0-9_]{1,512}$')
LANG = re.compile(r'^[a-z]{2,3}(_[A-Z]{2})?$')

# Errores de la API de Meta: código → (permanente, tipo, explicación y solución).
ERRORS = {
    '0': (False, 'red', 'No hubo respuesta de Meta (red o tiempo de espera). Se reintenta automáticamente.'),
    '1': (False, 'servicio', 'Error momentáneo de la API de Meta. Se reintenta automáticamente.'),
    '2': (False, 'servicio', 'El servicio de Meta no está disponible por ahora. Se reintenta automáticamente.'),
    '4': (False, 'limite', 'Se alcanzó el límite de llamadas de la aplicación. Se reintenta más tarde.'),
    '10': (True, 'config', 'La aplicación no tiene permiso para esta operación: revisa los permisos del token (whatsapp_business_messaging).'),
    '100': (True, 'datos', 'Meta rechazó un dato del mensaje (parámetro no válido). Revisa la plantilla y sus variables.'),
    '190': (True, 'config', 'El token de acceso no es válido o caducó: genera un token permanente de usuario del sistema y actualiza WHATSAPP_TOKEN.'),
    '200': (True, 'config', 'Faltan permisos en el token: agrega whatsapp_business_messaging y whatsapp_business_management.'),
    '368': (True, 'config', 'Meta bloqueó temporalmente la cuenta por incumplir sus políticas. Revisa la calidad de la cuenta en WhatsApp Manager.'),
    '80007': (False, 'limite', 'Se alcanzó el límite de la cuenta de WhatsApp Business. Se reintenta más tarde.'),
    '130429': (False, 'limite', 'Se superó el ritmo de envío permitido. Se reintenta más tarde.'),
    '131000': (False, 'servicio', 'Error desconocido de WhatsApp. Se reintenta automáticamente.'),
    '131005': (True, 'config', 'Acceso denegado: el token no tiene permiso sobre este número.'),
    '131008': (True, 'plantilla', 'Falta un parámetro obligatorio de la plantilla.'),
    '131009': (True, 'plantilla', 'Un parámetro de la plantilla no es válido.'),
    '131016': (False, 'servicio', 'WhatsApp está sobrecargado o no disponible. Se reintenta automáticamente.'),
    '131021': (True, 'telefono', 'El destinatario es el mismo número del remitente.'),
    '131026': (True, 'telefono', 'El mensaje no se pudo entregar: el número no tiene WhatsApp, no aceptó las condiciones de WhatsApp o usa una versión antigua.'),
    '131030': (True, 'telefono', 'El número no está en la lista de destinatarios permitidos (cuenta en modo de prueba). Agrégalo en Meta o termina la verificación del negocio.'),
    '131031': (True, 'config', 'La cuenta de WhatsApp Business está bloqueada. Revisa WhatsApp Manager.'),
    '131042': (True, 'config', 'Hay un problema con el método de pago de la cuenta de WhatsApp Business.'),
    '131045': (True, 'config', 'El número no está registrado correctamente (certificado). Completa el registro del número en WhatsApp Manager.'),
    '131047': (True, 'plantilla', 'Pasaron más de 24 horas desde el último mensaje del cliente: solo se puede usar una plantilla aprobada.'),
    '131048': (False, 'limite', 'Meta limitó los envíos por posible spam. Se reintenta más tarde; revisa la calidad de la cuenta.'),
    '131049': (True, 'limite', 'Meta decidió no entregar este mensaje para cuidar la experiencia del usuario. No se reintenta enseguida.'),
    '131051': (True, 'datos', 'Tipo de mensaje no admitido.'),
    '131056': (False, 'limite', 'Demasiados mensajes seguidos al mismo número. Se reintenta más tarde.'),
    '131057': (False, 'servicio', 'La cuenta de WhatsApp Business está en mantenimiento. Se reintenta automáticamente.'),
    '132000': (True, 'plantilla', 'La cantidad de variables no coincide con la plantilla aprobada.'),
    '132001': (True, 'plantilla', 'La plantilla no existe en ese idioma o aún no está aprobada.'),
    '132005': (True, 'plantilla', 'El texto de la plantilla con sus variables supera el largo permitido.'),
    '132007': (True, 'plantilla', 'El contenido de la plantilla incumple las políticas de WhatsApp.'),
    '132012': (True, 'plantilla', 'El formato de una variable no coincide con la plantilla.'),
    '132015': (True, 'plantilla', 'La plantilla está pausada por baja calidad. Revísala en WhatsApp Manager.'),
    '132016': (True, 'plantilla', 'La plantilla fue desactivada por Meta.'),
    '133004': (False, 'servicio', 'Servidor de WhatsApp no disponible temporalmente. Se reintenta automáticamente.'),
    '133010': (True, 'config', 'El número de WhatsApp Business no está registrado en la API de Cloud.'),
}
RETRIABLE_BY_HAND = ('config', 'plantilla', 'limite', 'incierto', 'servicio', 'red')


def _field(user, key):
    try:
        return user[key] if user else None
    except (KeyError, IndexError):
        return None


def _role(user):
    return _field(user, 'role')


class WhatsAppError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def stamp(now):
    from zoneinfo import ZoneInfo
    return now.astimezone(ZoneInfo('America/Guayaquil')).isoformat(timespec='seconds')  # misma zona en todas las fechas: se comparan como texto


def _text(value, limit):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


# ---- Configuración (variables de entorno) -----------------------------------------------------------------------------------------------
def config(env=None):
    env = os.environ if env is None else env
    get = lambda key: str(env.get(key, '') or '').strip()
    return {'token': get('WHATSAPP_TOKEN'), 'phone_id': get('WHATSAPP_PHONE_NUMBER_ID'), 'waba': get('WHATSAPP_BUSINESS_ACCOUNT_ID'),
            'secret': get('WHATSAPP_APP_SECRET'), 'verify': get('WHATSAPP_VERIFY_TOKEN'), 'version': get('WHATSAPP_API_VERSION') or API_VERSION}


def ready(env=None):
    cfg = config(env)
    return bool(cfg['token'] and cfg['phone_id'])


def _mask(value):
    value = str(value or '')
    return '…' + value[-4:] if len(value) > 4 else ('•' * len(value))


def requirements(env=None):
    """Qué falta y cómo completarlo. Nunca incluye el valor de un secreto; de los identificadores, solo los últimos cuatro dígitos."""
    env = os.environ if env is None else env
    out = []
    for key, label, required, kind, how in REQUIREMENTS:
        value = str(env.get(key, '') or '').strip()
        item = {'key': key, 'label': label, 'required': required, 'present': bool(value), 'kind': kind, 'how': how}
        if value and kind == 'id':
            item['hint'] = _mask(value)
        elif kind == 'option':
            item['hint'] = value or API_VERSION
        out.append(item)
    return out


def version_info(env=None):
    version = config(env)['version']
    expiry = VERSION_EXPIRY.get(version, '')
    match = re.fullmatch(r'v(\d+)\.(\d+)', version)
    return {'version': version, 'current': API_VERSION, 'expires': expiry, 'valid_format': bool(match),
            'outdated': bool(match) and int(match.group(1)) < int(API_VERSION[1:].split('.')[0]) - 1}


# ---- Ajustes (system_state; sin secretos) ------------------------------------------------------------------------------------------
DEFAULTS = {'auto': False, 'general_template': '', 'general_lang': 'es', 'test_number': '', 'test_template': 'hello_world', 'test_lang': 'en_US',
            'reminder_days': [3, 7], 'events': {}}


def settings(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (SETTING,)).fetchone()
    try:
        stored = json.loads(row['value']) if row else {}
    except (TypeError, ValueError):
        stored = {}
    out = json.loads(json.dumps(DEFAULTS))
    for key in DEFAULTS:
        if key in stored:
            out[key] = stored[key]
    events = {}
    for code in EVENTS:
        cfg = (out.get('events') or {}).get(code) or {}
        events[code] = {'on': cfg.get('on', True) is not False, 'template': str(cfg.get('template', '') or ''), 'lang': str(cfg.get('lang', '') or '')}
    out['events'] = events
    return out


def _store(c, data):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SETTING, json.dumps(data, ensure_ascii=False)))


def save_settings(c, data, user, env=None):
    if not user or _role(user) != 'administrador':
        raise WhatsAppError('Acceso no permitido.', 403)
    cur = settings(c)
    errors = {}

    def template(value, field):
        value = str(value or '').strip()
        if value and not TEMPLATE_NAME.fullmatch(value):
            errors[field] = 'Usa el nombre exacto de la plantilla en Meta: minúsculas, números y guion bajo.'
        return value

    def lang(value, field, default):
        value = str(value or '').strip() or default
        if not LANG.fullmatch(value):
            errors[field] = 'Código de idioma no válido (p. ej., es, es_EC o en_US).'
        return value

    if 'general_template' in data:
        cur['general_template'] = template(data['general_template'], 'general_template')
    if 'general_lang' in data:
        cur['general_lang'] = lang(data['general_lang'], 'general_lang', 'es')
    if 'test_template' in data:
        cur['test_template'] = template(data['test_template'], 'test_template') or 'hello_world'
    if 'test_lang' in data:
        cur['test_lang'] = lang(data['test_lang'], 'test_lang', 'en_US')
    if 'test_number' in data:
        raw = str(data['test_number'] or '').strip()
        number = number_for(raw) if raw else ''
        if raw and not number:
            errors['test_number'] = 'Escribe un celular válido con código de país (p. ej., +593 98 765 4321).'
        cur['test_number'] = number
    if 'reminder_days' in data:
        try:
            days = sorted({int(d) for d in (data['reminder_days'] or [])})
        except (TypeError, ValueError):
            days = None
        if days is None or len(days) > 3 or any(d < 1 or d > 30 for d in days):
            errors['reminder_days'] = 'Hasta tres plazos entre 1 y 30 días.'
        else:
            cur['reminder_days'] = days
    for code, value in (data.get('events') or {}).items():
        if code not in EVENTS or not isinstance(value, dict):
            continue
        item = cur['events'][code]
        if 'on' in value:
            item['on'] = bool(value['on'])
        if 'template' in value:
            item['template'] = template(value['template'], 'events.%s.template' % code)
        if 'lang' in value:
            item['lang'] = lang(value['lang'], 'events.%s.lang' % code, '') if str(value['lang'] or '').strip() else ''
    if 'auto' in data:
        want = bool(data['auto'])
        if want and not ready(env):
            errors['auto'] = 'Primero completa las credenciales de WhatsApp Business en el servidor.'
        elif want and not (cur['general_template'] or any(e['template'] for e in cur['events'].values())):
            errors['auto'] = 'Indica al menos una plantilla aprobada antes de activar los envíos automáticos.'
        else:
            cur['auto'] = want
    if errors:
        err = WhatsAppError('Revisa los datos marcados.', 400)
        err.fields = errors
        raise err
    _store(c, cur)
    return settings(c)


# ---- Números y autorización del cliente --------------------------------------------------------------------------------------------
def number_for(phone):
    """Celular en formato internacional (solo cifras) o '' si no sirve para WhatsApp (fijos, incompletos)."""
    import order_followups
    return order_followups.ecuador_number(phone)


def consent_state(c, phone):
    """Decisión vigente para un número: {'state': 'aceptado'|'rechazado'|'sin_registro', ...}."""
    if not phone:
        return {'state': 'sin_registro'}
    row = c.execute('SELECT * FROM whatsapp_consents WHERE phone=? ORDER BY id DESC LIMIT 1', (phone,)).fetchone()
    if not row:
        return {'state': 'sin_registro'}
    return {'state': row['decision'], 'source': row['source'], 'source_label': CONSENT_SOURCES.get(row['source'], row['source']), 'recorded_at': row['recorded_at'],
            'detail': row['detail']}


def record_consent(c, phone, decision, source, now, client_id=None, actor=None, detail=''):
    if decision not in ('aceptado', 'rechazado') or source not in CONSENT_SOURCES:
        raise WhatsAppError('Registro de autorización no válido.', 400)
    number = number_for(phone)
    if not number:
        raise WhatsAppError('El cliente no tiene un celular válido para WhatsApp.', 400)
    c.execute('INSERT INTO whatsapp_consents(phone,client_id,decision,source,detail,recorded_at,actor_id) VALUES (?,?,?,?,?,?,?)',
              (number, client_id, decision, source, _text(detail, 300), stamp(now), actor))
    return consent_state(c, number)


def consent_for_order(c, oid, data, user, now):
    """Registra la decisión del cliente de una orden (personal autorizado). La fuente es obligatoria: nunca se presume una autorización."""
    if not user or _role(user) not in ('administrador', 'tecnico'):
        raise WhatsAppError('Acceso no permitido.', 403)
    who = _order(c, oid)
    if not who:
        raise WhatsAppError('Orden no disponible.', 404)
    decision = str(data.get('decision', ''))
    source = str(data.get('source', ''))
    if source == 'baja' or source not in CONSENT_SOURCES:
        raise WhatsAppError('Indica cómo dio el cliente su respuesta.', 400)
    if decision == 'aceptado' and data.get('confirm') is not True:
        raise WhatsAppError('Confirma que el cliente autorizó expresamente recibir avisos por WhatsApp.', 400)
    return record_consent(c, who['phone'], decision, source, now, who['client_id'], user['id'], data.get('detail', ''))


# ---- Datos de cada aviso ---------------------------------------------------------------------------------------------------------
def _order(c, oid):
    return c.execute("SELECT o.id,o.code,o.status,cl.id client_id,cl.name client,COALESCE(cl.phone,'') phone,COALESCE(NULLIF(d.kind,''),d.category) kind,d.brand,d.model "
                     'FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (oid,)).fetchone()


def _first(name):
    parts = str(name or '').strip().split()
    return parts[0].title() if parts else 'cliente'


def _device(row):
    """Marca y modelo; sin ellos, el nombre visible del tipo de equipo (nunca el código interno)."""
    text = ' '.join(x for x in (row['brand'] or '', row['model'] or '') if x).strip()
    if text:
        return text
    from reception import DEVICE_TYPES
    return DEVICE_TYPES.get(row['kind'] or '', row['kind'] or 'registrado')


def _when(value):
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value or '')
    return moment.strftime('%d/%m/%Y a las %H:%M')


def subject(c, event, order_id=None, part_request_id=None, appointment_id=None, pqrs_id=None):
    """Destinatario y datos reales del aviso: dict con phone, client_id, name, ref, equipo/repuesto/cuando y order_id."""
    if pqrs_id:
        import pqrs
        p = c.execute('SELECT * FROM pqrs_cases WHERE id=?', (pqrs_id,)).fetchone()
        if not p:
            return None
        return {'phone': p['phone'], 'client_id': p['client_id'], 'name': p['name'], 'ref': p['code'], 'order_id': None, 'pqrs': dict(p),
                'tipo': pqrs.CATEGORY_LABELS[p['category']][0].lower(), 'estado': pqrs.STATUS_LABELS[p['status']][0]}
    if appointment_id:
        a = c.execute('SELECT * FROM appointments WHERE id=?', (appointment_id,)).fetchone()
        if not a:
            return None
        a = dict(a)
        return {'phone': a.get('phone') or '', 'client_id': a.get('client_id'), 'name': a.get('customer_name') or '', 'ref': a.get('public_code') or '',
                'cuando': _when(a.get('starts_at')), 'order_id': None, 'appointment': a}
    if part_request_id and not order_id:
        row = c.execute('SELECT order_id FROM order_part_requests WHERE id=?', (part_request_id,)).fetchone()
        order_id = row['order_id'] if row else None
    o = _order(c, order_id) if order_id else None
    if not o:
        return None
    out = {'phone': o['phone'], 'client_id': o['client_id'], 'name': o['client'], 'ref': o['code'], 'equipo': _device(o), 'order_id': o['id'], 'status': o['status']}
    if part_request_id:
        import order_part_requests as parts
        row = c.execute('SELECT * FROM order_part_requests WHERE id=?', (part_request_id,)).fetchone()
        out['repuesto'] = (parts._scrub(row['name'], parts.private_terms(c, row)) or 'solicitado') if row else 'solicitado'
    return out


def compose(event, info, cfg):
    """Plantilla, idioma, variables y texto legible. Usa la plantilla propia del evento o, si no hay, la plantilla general."""
    label, group = EVENTS[event][0], EVENTS[event][1]
    ev = cfg['events'][event]
    phrase = EVENTS[event][2].format(equipo=info.get('equipo', ''), repuesto='«%s»' % info.get('repuesto', ''), ref=info.get('ref', ''), cuando=info.get('cuando', ''),
                                     tipo=info.get('tipo', ''), estado=info.get('estado', ''))
    preview = '%s: %s.' % (_first(info['name']), phrase[0].upper() + phrase[1:])
    if ev['template']:
        third = {'orden': info.get('equipo', ''), 'repuesto': info.get('repuesto', ''), 'cita': info.get('cuando', ''), 'pqrs': info.get('estado', '')}[group]
        return {'template': ev['template'], 'lang': ev['lang'] or cfg['general_lang'] or 'es', 'params': [_first(info['name']), info.get('ref', ''), third],
                'preview': preview, 'label': label}
    if cfg['general_template']:
        return {'template': cfg['general_template'], 'lang': cfg['general_lang'] or 'es', 'params': [_first(info['name']), info.get('ref', ''), phrase],
                'preview': preview, 'label': label}
    return {'template': '', 'lang': '', 'params': [], 'preview': preview, 'label': label}


def blockers(c, event, info, cfg, env=None):
    """(tipo, motivo) si el aviso no puede enviarse ahora; ('', '') si puede. Solo condiciones reales y verificables."""
    if not ready(env):
        return 'config', 'WhatsApp Business no está configurado en el servidor (faltan credenciales de Meta).'
    number = number_for(info['phone'])
    if not number:
        return 'telefono', 'El cliente no tiene un celular válido para WhatsApp.'
    consent = consent_state(c, number)
    if event.startswith('pqrs_'):
        if consent['state'] == 'rechazado':
            return 'consentimiento', 'El cliente pidió no recibir avisos por WhatsApp.'
        if not (info.get('pqrs') or {}).get('whatsapp_consent'):
            return 'consentimiento', 'El cliente no autorizó avisos por WhatsApp en el formulario PQRS.'
    elif event.startswith('cita_'):
        appointment = info.get('appointment') or {}
        if consent['state'] == 'rechazado':
            return 'consentimiento', 'El cliente pidió no recibir avisos por WhatsApp.'
        if not appointment.get('communications_consent'):
            return 'consentimiento', 'El cliente no autorizó comunicaciones de la cita al reservar.'
    elif consent['state'] != 'aceptado':
        return 'consentimiento', ('El cliente pidió no recibir avisos por WhatsApp.' if consent['state'] == 'rechazado' else
                                  'El cliente no tiene registrada su autorización para recibir avisos por WhatsApp. Regístrala en «Avisos al cliente» de la orden.')
    if not compose(event, info, cfg)['template']:
        return 'plantilla', 'Falta la plantilla aprobada para «%s» (Configuración → Integraciones → WhatsApp Business).' % EVENTS[event][0]
    return '', ''


def _repeated(c, event, order_id, appointment_id, now):
    if not order_id:
        return ''
    alive = "status IN ('pendiente','enviando','enviado','entregado','leido')"
    if event in ONCE:
        if c.execute('SELECT 1 FROM whatsapp_outbox WHERE order_id=? AND event=? AND ' + alive + ' LIMIT 1', (order_id, event)).fetchone():
            return 'El cliente ya recibió este aviso de la orden.'
        return ''
    since = stamp(now - timedelta(hours=REPEAT_HOURS))
    if c.execute('SELECT 1 FROM whatsapp_outbox WHERE order_id=? AND event=? AND created_at>=? AND ' + alive + ' LIMIT 1', (order_id, event, since)).fetchone():
        return 'Ya se avisó al cliente de este evento en las últimas %d horas.' % REPEAT_HOURS
    return ''


def enqueue(c, event, key, now, order_id=None, part_request_id=None, appointment_id=None, source='', delay=0, actor=None, manual=False, env=None, pqrs_id=None):
    """Registra un aviso (uno por clave). Automático: solo con los envíos activados y el evento habilitado; si no, no se crea nada.
    Devuelve el id pendiente de enviar, o None (omitido, repetido o desactivado)."""
    if event not in EVENTS:
        return None
    cfg = settings(c)
    if not manual and (not cfg['auto'] or not ready(env) or not cfg['events'][event]['on']):
        return None
    info = subject(c, event, order_id, part_request_id, appointment_id, pqrs_id)
    if not info:
        return None
    kind, reason = blockers(c, event, info, cfg, env)
    repeated = _repeated(c, event, info['order_id'], appointment_id, now)
    if repeated:
        if manual:
            raise WhatsAppError(repeated, 409)
        kind, reason = 'repetido', repeated
    msg = compose(event, info, cfg)
    status = 'omitido' if reason else 'pendiente'
    cur = c.execute('INSERT INTO whatsapp_outbox(dedupe_key,event,source,order_id,client_id,appointment_id,part_request_id,recipient,template,template_lang,params,preview,'
                    'status,detail,reason_kind,next_attempt_at,created_by,created_at,updated_at,pqrs_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(dedupe_key) DO NOTHING',
                    (key[:120], event, source[:40], info['order_id'], info.get('client_id'), appointment_id, part_request_id, number_for(info['phone']), msg['template'],
                     msg['lang'], json.dumps(msg['params'], ensure_ascii=False), msg['preview'], status, reason, kind,
                     '' if reason else stamp(now + timedelta(minutes=delay)), actor, stamp(now), stamp(now), pqrs_id))
    if not cur.rowcount:
        return None
    return None if reason else cur.lastrowid


# ---- Ganchos de los módulos existentes (sin cambiar el correo) -----------------------------------------------------------------------
def on_status(c, oid, lid, new, source, now, notify=True):
    """Cambio de estado registrado. Con la gracia de AUTO_DELAY: si el estado cambia antes del envío, el aviso no sale."""
    # Sin aviso si el personal eligió «sin avisar», o si el cambio es el regreso automático tras aprobar un presupuesto o recibir un
    # repuesto: esos hechos tienen su propio aviso (presupuesto aprobado, repuesto recibido) y no significan que la reparación comenzó.
    if not notify or source in ('quote_approved', 'part_received'):
        return None
    if new == 'pendiente' and source == 'orden_registrada':
        event = 'orden_registrada'
    else:
        event = STATUS_EVENTS.get(new)
    if not event:
        return None
    if event == 'presupuesto_pendiente' and not _quote_pending(c, oid):
        return None
    return enqueue(c, event, 'estado:%d' % lid, now, order_id=oid, source='estado', delay=AUTO_DELAY)


def on_quote(c, quote, status, now):
    event = {'aprobado': 'presupuesto_aprobado', 'parcial': 'presupuesto_aprobado', 'rechazado': 'presupuesto_rechazado'}.get(status)
    if event:
        return enqueue(c, event, 'presupuesto:%d:%s' % (quote['id'], status), now, order_id=quote['order_id'], source='presupuesto', delay=1)
    return None


def on_part(c, row, event, key, now):
    mapped = PART_EVENTS.get(event)
    if mapped:
        return enqueue(c, mapped, 'repuesto:%d:%s' % (row['id'], key), now, order_id=row['order_id'], part_request_id=row['id'], source='repuesto', delay=1)
    return None


def on_appointment(c, aid, event, generation, now):
    mapped = APPOINTMENT_EVENTS.get(event)
    if mapped:
        return enqueue(c, mapped, 'cita:%d:%s:%s' % (aid, generation, mapped), now, appointment_id=aid, source='cita', delay=1)
    return None


def reminders(c, now):
    """Recordatorios de entrega: órdenes en «Listo para entregar» sin retiro durante los días configurados (uno por plazo y por paso a listo)."""
    cfg = settings(c)
    if not cfg['auto'] or not cfg['events']['recordatorio_entrega']['on'] or not ready():
        return []
    out = []
    for row in c.execute("SELECT o.id,(SELECT l.id||'|'||l.created_at FROM order_status_log l WHERE l.order_id=o.id AND l.to_status='listo' ORDER BY l.id DESC LIMIT 1) last "
                         "FROM orders o WHERE o.status='listo'").fetchall():
        if not row['last']:
            continue
        lid, when = row['last'].split('|', 1)
        try:
            since = datetime.fromisoformat(when)
        except ValueError:
            continue
        for days in cfg['reminder_days']:
            if now - since >= timedelta(days=days) and now - since < timedelta(days=days + 2):
                nid = enqueue(c, 'recordatorio_entrega', 'recordatorio:%s:%d' % (lid, days), now, order_id=row['id'], source='recordatorio')
                if nid:
                    out.append(nid)
    return out


def _quote_pending(c, oid):
    quote = c.execute("SELECT status FROM quotes WHERE order_id=? AND deleted_at='' AND status NOT IN ('borrador','cancelado') ORDER BY version DESC,id DESC LIMIT 1", (oid,)).fetchone()
    return bool(quote and quote['status'] == 'enviado')


def still_true(c, row):
    """Comprobación justo antes de enviar: el aviso debe seguir siendo cierto con los datos actuales ('' si lo es)."""
    event = row['event']
    if row['source'] == 'estado' and row['order_id']:
        o = c.execute('SELECT status FROM orders WHERE id=?', (row['order_id'],)).fetchone()
        expected = 'pendiente' if event == 'orden_registrada' else next((k for k, v in STATUS_EVENTS.items() if v == event), '')
        if not o or (expected and o['status'] != expected and event != 'orden_registrada'):
            return 'El estado de la orden cambió antes del envío: el aviso ya no era cierto.'
        if event == 'presupuesto_pendiente' and not _quote_pending(c, row['order_id']):
            return 'El presupuesto ya no está pendiente de aprobación: el aviso no sería cierto.'
    if event == 'recordatorio_entrega' and row['order_id']:
        o = c.execute('SELECT status FROM orders WHERE id=?', (row['order_id'],)).fetchone()
        if not o or o['status'] != 'listo':
            return 'El equipo ya no está pendiente de retiro.'
    if row['appointment_id']:
        a = c.execute('SELECT status,deleted_at FROM appointments WHERE id=?', (row['appointment_id'],)).fetchone()
        wanted = {'cita_registrada': ('solicitada',), 'cita_confirmada': ('confirmada', 'reprogramada'), 'cita_reprogramada': ('confirmada', 'reprogramada', 'solicitada'),
                  'cita_cancelada': ('cancelada',)}.get(event, ())
        if not a or a['deleted_at'] or (wanted and a['status'] not in wanted):
            return 'La cita cambió antes del envío: el aviso ya no era cierto.'
    if row['part_request_id'] and event in ('repuesto_solicitado', 'repuesto_enviado', 'repuesto_en_pais', 'repuesto_aduana', 'repuesto_liberado', 'repuesto_recibido', 'repuesto_retraso'):
        p = c.execute('SELECT situation FROM order_part_requests WHERE id=?', (row['part_request_id'],)).fetchone()
        if not p or p['situation'] == 'cancelado':
            return 'El pedido del repuesto fue cancelado antes del envío.'
    return ''


# ---- Envío -------------------------------------------------------------------------------------------------------------------------
def call(method, path, env=None, payload=None, query=None):
    """Llamada a Graph API desde el servidor. Devuelve (estado HTTP, dict). El token va solo en la cabecera y nunca se registra."""
    cfg = config(env)
    url = '%s/%s/%s' % (GRAPH, cfg['version'], path.lstrip('/'))
    if query:
        url += '?' + urllib.parse.urlencode(query)
    headers = {'Authorization': 'Bearer ' + cfg['token'], 'Content-Type': 'application/json'}
    try:
        if TRANSPORT is not None:
            return TRANSPORT(method, url, headers, payload)
        req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read() or b'{}')
        except urllib.error.HTTPError as err:
            try:
                return err.code, json.loads(err.read() or b'{}')
            except ValueError:
                return err.code, {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        return 0, {'error': {'message': 'Sin conexión con Meta (%s).' % type(err).__name__, 'code': 0}}


def classify(code, answer):
    """(permanente, tipo, código, explicación) de una respuesta de error de Meta."""
    err = (answer or {}).get('error') or {}
    meta = str(err.get('code', '') if err.get('code', '') != '' else ('0' if code == 0 else ''))
    sub = str(err.get('error_subcode', '') or '')
    if meta in ERRORS:
        permanent, kind, text = ERRORS[meta]
    elif code == 0 or code >= 500 or code == 429:
        permanent, kind, text = False, 'servicio', 'Error temporal de Meta (HTTP %d). Se reintenta automáticamente.' % code
    else:
        permanent, kind, text = True, 'datos', 'Meta rechazó el mensaje.'
    detail = _text(err.get('message', ''), 160)
    title = _text(((err.get('error_data') or {}).get('details', '')), 160)
    extra = ' '.join(x for x in (detail, title) if x)
    return permanent, kind, meta + ('/' + sub if sub else ''), (text + (' Respuesta de Meta: ' + extra if extra else ''))[:400]


def _payload(row):
    params = json.loads(row['params'] or '[]')
    template = {'name': row['template'], 'language': {'code': row['template_lang'] or 'es'}}
    if params:
        template['components'] = [{'type': 'body', 'parameters': [{'type': 'text', 'text': str(p)[:1000] or '-'} for p in params]}]
    return {'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': row['recipient'], 'type': 'template', 'template': template}


def _claim(c, nid, now):
    cur = c.execute("UPDATE whatsapp_outbox SET status='enviando',locked_until=?,updated_at=? WHERE id=? AND status IN ('pendiente','fallido') "
                    "AND (locked_until='' OR locked_until<?)", (stamp(now + timedelta(seconds=LOCK_SECONDS)), stamp(now), nid, stamp(now)))
    return cur.rowcount == 1


def _record_message(c, row, provider, now):
    """Deja el envío en la comunicación de la orden (mismo historial que los mensajes manuales; el webhook actualiza ambos)."""
    if not row['order_id']:
        return None
    import order_followups
    body = '%s\n\nPlantilla aprobada de WhatsApp «%s» (%s) · Datos: %s' % (row['preview'], row['template'], row['template_lang'], ', '.join(json.loads(row['params'] or '[]')))
    try:
        message, _ = order_followups.record(c, row['order_id'], {'channel': 'whatsapp', 'body': body, 'template': 'whatsapp', 'request_key': 'wa-outbox-%d' % row['id']},
                                            None, now, 'enviado', provider, '', row['recipient'])
        return message['id']
    except order_followups.FollowupError:
        return None


def send_one(c, nid, now, env=None):
    """Envía un aviso ya reclamado o reclamable. Devuelve la fila actualizada (dict) o None si otro proceso lo tiene."""
    if not _claim(c, nid, now):
        return None
    row = c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone()
    cfg = settings(c)
    reason = still_true(c, row)
    kind = 'cambio' if reason else ''
    if not reason and row['source'] != 'prueba':
        info = subject(c, row['event'], row['order_id'], row['part_request_id'], row['appointment_id'], row['pqrs_id'])
        if not info:
            kind, reason = 'datos', 'La orden o la cita ya no está disponible.'
        else:
            kind, reason = blockers(c, row['event'], info, cfg, env)
            if not reason and number_for(info['phone']) != row['recipient']:
                c.execute('UPDATE whatsapp_outbox SET recipient=? WHERE id=?', (number_for(info['phone']), nid))  # el cliente cambió su número
    elif not ready(env):
        kind, reason = 'config', 'WhatsApp Business no está configurado en el servidor.'
    if reason:
        c.execute("UPDATE whatsapp_outbox SET status='omitido',detail=?,reason_kind=?,locked_until='',next_attempt_at='',updated_at=? WHERE id=?", (reason, kind, stamp(now), nid))
        return dict(c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone())
    row = c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone()
    code, answer = call('POST', '%s/messages' % config(env)['phone_id'], env, _payload(row))
    provider = ''
    if code == 200 and isinstance(answer, dict) and answer.get('messages'):
        provider = str(answer['messages'][0].get('id', ''))
    attempts = row['attempts'] + 1
    if provider:
        mid = _record_message(c, row, provider, now)
        c.execute("UPDATE whatsapp_outbox SET status='enviado',provider_id=?,message_id=?,attempts=?,detail=?,reason_kind='',error_code='',permanent=0,locked_until='',"
                  "next_attempt_at='',sent_at=?,updated_at=? WHERE id=?", (provider, mid, attempts, 'Aceptado por la API de WhatsApp Business.', stamp(now), stamp(now), nid))
    else:
        permanent, kind, meta, text = classify(code, answer)
        auto_left = not permanent and attempts < MAX_AUTO
        nxt = stamp(now + timedelta(minutes=BACKOFF[min(attempts - 1, len(BACKOFF) - 1)])) if auto_left else ''
        if not permanent and not auto_left:
            text = 'Se agotaron los reintentos automáticos (%d). Último error: %s' % (attempts, text)
        c.execute("UPDATE whatsapp_outbox SET status='fallido',attempts=?,detail=?,reason_kind=?,error_code=?,permanent=?,locked_until='',next_attempt_at=?,updated_at=? WHERE id=?",
                  (attempts, text[:400], kind, meta, 1 if permanent else 0, nxt, stamp(now), nid))
    return dict(c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone())


def due_ids(c, now, limit=10):
    n = stamp(now)
    # Un envío interrumpido (bloqueo vencido en «enviando») no se reenvía solo: no se sabe si Meta lo aceptó.
    c.execute("UPDATE whatsapp_outbox SET status='fallido',permanent=1,reason_kind='incierto',locked_until='',next_attempt_at='',updated_at=?,"
              "detail='El envío se interrumpió y no se confirmó si WhatsApp lo aceptó. Revisa con el cliente antes de reintentar.' "
              "WHERE status='enviando' AND locked_until<?", (n, n))
    return [r[0] for r in c.execute("SELECT id FROM whatsapp_outbox WHERE ((status='pendiente' AND next_attempt_at<=?) OR (status='fallido' AND permanent=0 AND next_attempt_at!='' "
                                    "AND next_attempt_at<=?)) AND attempts<? ORDER BY id LIMIT ?", (n, n, MAX_TOTAL, limit))]


def process(c, now, ids=None, limit=10, env=None):
    """Procesa la cola (o los id indicados). Cada envío se confirma por separado: un fallo no deshace los anteriores."""
    if not ready(env):
        return []
    out = []
    for nid in (ids if ids is not None else due_ids(c, now, limit)):
        row = send_one(c, nid, now, env)
        c.commit()
        if row:
            out.append(row)
    return out


def tick(c, now, force=False, env=None):
    """Tarea de la cola: la llama la actividad del personal (como mucho cada minuto) y la tarea diaria. Idempotente."""
    if not ready(env):
        return []
    if not force:
        last = c.execute("SELECT value FROM system_state WHERE key='whatsapp_tick'").fetchone()
        if last and last['value'] > stamp(now - timedelta(seconds=60)):
            return []
    c.execute("INSERT INTO system_state(key,value) VALUES ('whatsapp_tick',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (stamp(now),))
    reminders(c, now)
    c.commit()
    return process(c, now, None, 10, env)


# ---- Reintento manual -------------------------------------------------------------------------------------------------------------
def can_retry(c, row, env=None):
    """¿Procede el botón «Reintentar envío»? Nunca para números sin WhatsApp, avisos repetidos o ya enviados."""
    row = dict(row)
    if row['attempts'] >= MAX_TOTAL or not ready(env) or row['source'] == 'prueba':
        return False
    if row['status'] == 'fallido':
        return not row['permanent'] or row['reason_kind'] in RETRIABLE_BY_HAND
    if row['status'] == 'omitido' and row['reason_kind'] in ('consentimiento', 'plantilla', 'config', 'telefono'):
        info = subject(c, row['event'], row['order_id'], row['part_request_id'], row['appointment_id'], row['pqrs_id'])
        return bool(info) and not still_true(c, row) and blockers(c, row['event'], info, settings(c), env) == ('', '')
    return False


def retry(c, nid, user, now, env=None):
    if not user or _role(user) not in ('administrador', 'tecnico'):
        raise WhatsAppError('Acceso no permitido.', 403)
    row = c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone()
    if not row:
        raise WhatsAppError('Aviso no disponible.', 404)
    if not can_retry(c, row, env):
        raise WhatsAppError('Este aviso no se puede reintentar: revisa el motivo indicado.', 409)
    info = subject(c, row['event'], row['order_id'], row['part_request_id'], row['appointment_id'], row['pqrs_id'])
    msg = compose(row['event'], info, settings(c))
    c.execute("UPDATE whatsapp_outbox SET status='pendiente',permanent=0,reason_kind='',next_attempt_at=?,template=?,template_lang=?,params=?,recipient=?,"
              'detail=?,updated_at=? WHERE id=?', (stamp(now), msg['template'], msg['lang'], json.dumps(msg['params'], ensure_ascii=False), number_for(info['phone']),
                                                  'Reintento solicitado por %s.' % (_field(user, 'name') or 'el personal'), stamp(now), nid))
    c.commit()
    rows = process(c, now, [nid], env=env)
    return rows[0] if rows else dict(c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone())


def send_manual(c, oid, event, user, now, env=None):
    """Aviso enviado por el personal desde la orden (p. ej., «Diagnóstico terminado»): mismas reglas de autorización y plantilla."""
    if not user or _role(user) not in ('administrador', 'tecnico'):
        raise WhatsAppError('Acceso no permitido.', 403)
    if event not in EVENTS or EVENTS[event][1] != 'orden':
        raise WhatsAppError('Elige un aviso de la orden.', 400)
    if not ready(env):
        raise WhatsAppError('WhatsApp Business no está configurado en el servidor.', 409)
    info = subject(c, event, oid)
    if not info:
        raise WhatsAppError('Orden no disponible.', 404)
    kind, reason = blockers(c, event, info, settings(c), env)
    if reason:
        raise WhatsAppError(reason, 409)
    nid = enqueue(c, event, 'manual:%d:%s:%s' % (oid, event, now.strftime('%Y%m%d')), now, order_id=oid, source='manual', actor=user['id'], manual=True, env=env)
    if not nid:
        raise WhatsAppError('Este aviso ya se registró hoy para la orden.', 409)
    c.commit()
    rows = process(c, now, [nid], env=env)
    return rows[0] if rows else dict(c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone())


def send_test(c, data, user, now, env=None):
    """Envío de prueba SOLO al número autorizado guardado en los ajustes, con confirmación expresa. No usa datos de clientes."""
    if not user or _role(user) != 'administrador':
        raise WhatsAppError('Acceso no permitido.', 403)
    if not ready(env):
        raise WhatsAppError('Completa primero las credenciales de WhatsApp Business en el servidor.', 409)
    cfg = settings(c)
    if not cfg['test_number']:
        raise WhatsAppError('Guarda primero el número autorizado para pruebas.', 400)
    if data.get('confirm') is not True:
        raise WhatsAppError('Confirma que el número de prueba pertenece a PC-DOCTOR o a una persona que autorizó la prueba.', 400)
    recent = c.execute("SELECT 1 FROM whatsapp_outbox WHERE source='prueba' AND created_at>=? LIMIT 1", (stamp(now - timedelta(seconds=60)),)).fetchone()
    if recent:
        raise WhatsAppError('Espera un minuto entre envíos de prueba.', 429)
    template = cfg['test_template'] or 'hello_world'
    nid = c.execute("INSERT INTO whatsapp_outbox(dedupe_key,event,source,recipient,template,template_lang,params,preview,status,next_attempt_at,created_by,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,'pendiente',?,?,?,?)", ('prueba:%s' % now.strftime('%Y%m%d%H%M%S%f'), 'prueba', 'prueba', cfg['test_number'], template,
                                                                   cfg['test_lang'] or 'en_US', '[]', 'Mensaje de prueba con la plantilla «%s».' % template, stamp(now),
                                                                   user['id'], stamp(now), stamp(now))).lastrowid
    c.commit()
    rows = process(c, now, [nid], env=env)
    return rows[0] if rows else dict(c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (nid,)).fetchone())


# ---- Webhook ----------------------------------------------------------------------------------------------------------------------
def verify(params, env=None):
    cfg = config(env)
    if cfg['verify'] and params.get('hub.mode') == 'subscribe' and hmac.compare_digest(params.get('hub.verify_token', ''), cfg['verify']):
        return params.get('hub.challenge', '')
    return None


def _bump(c, key, value):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))


def webhook(c, raw, signature, now, env=None):
    """Avisos de Meta: SOLO con firma válida (X-Hub-Signature-256 con la clave secreta de la aplicación). Actualiza estados (nunca retrocede)
    y registra las bajas que escribe el cliente. Devuelve el número de cambios; -1 si la firma no es válida."""
    import order_followups
    cfg = config(env)
    expected = 'sha256=' + hmac.new(cfg['secret'].encode(), raw, hashlib.sha256).hexdigest() if cfg['secret'] else ''
    if not expected or not hmac.compare_digest(expected, signature or ''):
        row = c.execute("SELECT value FROM system_state WHERE key='whatsapp_webhook_rejected'").fetchone()
        _bump(c, 'whatsapp_webhook_rejected', json.dumps({'count': (json.loads(row['value']).get('count', 0) if row else 0) + 1, 'last': stamp(now)}))
        return -1
    try:
        payload = json.loads(raw.decode('utf-8'))
    except ValueError:
        return 0
    _bump(c, 'whatsapp_webhook_last', stamp(now))
    changed = order_followups.apply_statuses(c, payload, now)
    rank = {'enviado': 1, 'entregado': 2, 'leido': 3}
    names = {'sent': 'enviado', 'delivered': 'entregado', 'read': 'leido', 'failed': 'fallido'}
    for entry in payload.get('entry', []) or []:
        for change in entry.get('changes', []) or []:
            value = change.get('value', {}) or {}
            for st in value.get('statuses', []) or []:
                new = names.get(st.get('status', ''))
                row = c.execute('SELECT id,status FROM whatsapp_outbox WHERE provider_id=?', (str(st.get('id', '')),)).fetchone() if new and st.get('id') else None
                if not row:
                    continue
                if new == 'fallido' and row['status'] == 'enviado':
                    err = (st.get('errors') or [{}])[0]
                    permanent, kind, meta, text = classify(400, {'error': {'code': err.get('code', ''), 'message': err.get('title', ''),
                                                                          'error_data': err.get('error_data') or {}}})
                    c.execute("UPDATE whatsapp_outbox SET status='fallido',detail=?,reason_kind=?,error_code=?,permanent=1,next_attempt_at='',updated_at=? WHERE id=?",
                              ('WhatsApp informó que no pudo entregarlo. ' + text, kind, meta, stamp(now), row['id']))
                    changed += 1
                elif rank.get(new, 0) > rank.get(row['status'], 0) and row['status'] in rank:
                    extra = ',delivered_at=CASE WHEN delivered_at=\'\' THEN ? ELSE delivered_at END' + (',read_at=?' if new == 'leido' else '')
                    args = [new, stamp(now), stamp(now)] + ([stamp(now)] if new == 'leido' else []) + [row['id']]
                    c.execute('UPDATE whatsapp_outbox SET status=?,updated_at=?' + extra + ' WHERE id=?', args)
                    changed += 1
            for msg in value.get('messages', []) or []:
                text = ((msg.get('text') or {}).get('body') or (msg.get('button') or {}).get('text') or '') if isinstance(msg, dict) else ''
                number = re.sub(r'\D', '', str(msg.get('from', '') if isinstance(msg, dict) else ''))
                if number and text and OPT_OUT.match(text) and consent_state(c, number)['state'] != 'rechazado':
                    c.execute("INSERT INTO whatsapp_consents(phone,client_id,decision,source,detail,recorded_at,actor_id) VALUES (?,NULL,'rechazado','baja',?,?,NULL)",
                              (number, 'Mensaje del cliente: ' + _text(text, 60), stamp(now)))
                    changed += 1
    return changed


# ---- Comprobación de la conexión (desde el servidor) ------------------------------------------------------------------------------
def check(c, now, base_url='', env=None):
    """Comprueba credenciales, número, permisos, plantillas y webhook contra Meta. Guarda el resultado (sin secretos) para el panel."""
    cfg = config(env)
    steps = []

    def step(key, label, ok, text, solution=''):
        steps.append({'key': key, 'label': label, 'state': 'ok' if ok is True else 'warn' if ok is None else 'error', 'text': text, 'solution': solution})

    missing = [r for r in requirements(env) if r['required'] and not r['present']]
    step('variables', 'Variables del servidor', not missing, 'Todas las variables obligatorias están definidas.' if not missing else
         'Faltan: ' + ', '.join(r['key'] for r in missing) + '.', 'Agrégalas en Vercel → Settings → Environment Variables (Production) y vuelve a desplegar.' if missing else '')
    v = version_info(env)
    step('version', 'Versión de Graph API', None if v['outdated'] or not v['valid_format'] else True,
         'Se usa %s%s.' % (v['version'], (' (Meta la retira el %s)' % v['expires']) if v['expires'] else ''),
         ('Actualiza WHATSAPP_API_VERSION a %s o elimínala para usar la vigente.' % API_VERSION) if v['outdated'] or not v['valid_format'] else '')
    phone = {}
    templates = []
    if cfg['token'] and cfg['phone_id']:
        code, answer = call('GET', cfg['phone_id'], env, query={'fields': 'verified_name,display_phone_number,quality_rating,code_verification_status,name_status,platform_type,throughput,status'})
        if code == 200 and isinstance(answer, dict) and (answer.get('id') or answer.get('display_phone_number')):
            phone = {k: answer.get(k, '') for k in ('verified_name', 'display_phone_number', 'quality_rating', 'code_verification_status', 'name_status', 'platform_type', 'status')}
            phone['throughput'] = ((answer.get('throughput') or {}).get('level', '')) if isinstance(answer.get('throughput'), dict) else ''
            step('token', 'Token de acceso', True, 'Meta aceptó el token.')
            registered = phone.get('platform_type') in ('', 'CLOUD_API')
            step('numero', 'Número de WhatsApp Business', registered, '%s · %s · calidad %s' % (phone.get('display_phone_number') or '—', phone.get('verified_name') or 'sin nombre verificado',
                 phone.get('quality_rating') or 'sin dato'), '' if registered else 'Registra el número en la API de Cloud desde WhatsApp Manager.')
        else:
            permanent, kind, meta, text = classify(code, answer)
            step('token', 'Token de acceso y número', False, text, 'Revisa WHATSAPP_TOKEN y WHATSAPP_PHONE_NUMBER_ID.')
        code, answer = call('GET', 'debug_token', env, query={'input_token': cfg['token']})
        data = (answer or {}).get('data') or {}
        if code == 200 and data:
            scopes = set(data.get('scopes') or [])
            needed = {'whatsapp_business_messaging', 'whatsapp_business_management'}
            expires = data.get('expires_at') or 0
            step('permisos', 'Permisos de la aplicación', needed <= scopes, 'Permisos: ' + (', '.join(sorted(scopes & needed)) or 'ninguno de WhatsApp') +
                 ('; el token no caduca.' if not expires else '; el token caduca el %s.' % datetime.fromtimestamp(expires).strftime('%d/%m/%Y')),
                 '' if needed <= scopes else 'Genera el token con whatsapp_business_messaging y whatsapp_business_management.')
            if expires:
                step('caducidad', 'Caducidad del token', None, 'El token es temporal.', 'Usa un token permanente de usuario del sistema para producción.')
        else:
            step('permisos', 'Permisos de la aplicación', None, 'Meta no permitió leer los permisos de este token (es normal con algunos tokens).',
                 'Si los envíos fallan con el código 10 o 200, revisa los permisos del token.')
    if cfg['token'] and cfg['waba']:
        code, answer = call('GET', '%s/message_templates' % cfg['waba'], env, query={'fields': 'name,status,language,category,components,parameter_format', 'limit': '200'})
        if code == 200:
            templates = [_template_summary(t) for t in (answer.get('data') or [])]
            approved = [t for t in templates if t['status'] == 'APPROVED']
            step('plantillas', 'Plantillas de mensajes', bool(approved) or None, '%d plantillas, %d aprobadas.' % (len(templates), len(approved)),
                 '' if approved else 'Crea las plantillas de categoría «Utilidad» en WhatsApp Manager y espera su aprobación.')
        else:
            permanent, kind, meta, text = classify(code, answer)
            step('plantillas', 'Plantillas de mensajes', False, text, 'Revisa WHATSAPP_BUSINESS_ACCOUNT_ID y los permisos del token.')
        code, answer = call('GET', '%s/subscribed_apps' % cfg['waba'], env)
        subscribed = code == 200 and bool((answer or {}).get('data'))
        step('suscripcion', 'Aplicación suscrita a la cuenta', subscribed if code == 200 else None,
             'La aplicación recibe los eventos de la cuenta.' if subscribed else 'La aplicación no está suscrita a la cuenta de WhatsApp Business.' if code == 200 else
             'No se pudo comprobar la suscripción.', '' if subscribed else 'En Meta: WhatsApp → Configuración → Webhook, suscribe el campo «messages».')
    last = c.execute("SELECT value FROM system_state WHERE key='whatsapp_webhook_last'").fetchone()
    step('webhook', 'Webhook de estados', True if last else None if cfg['secret'] and cfg['verify'] else False,
         ('Último aviso firmado de Meta: %s.' % last['value']) if last else 'Todavía no llegó ningún aviso firmado de Meta.' if cfg['secret'] and cfg['verify'] else
         'Faltan WHATSAPP_APP_SECRET o WHATSAPP_VERIFY_TOKEN.', '' if last else 'URL de devolución: %s/api/public/whatsapp/webhook (campo «messages»).' % base_url.rstrip('/'))
    cfgs = settings(c)
    issues = template_issues(cfgs, templates) if templates else []
    for issue in issues:
        step('plantilla:' + issue['event'], 'Plantilla de «%s»' % issue['label'], False, issue['text'], 'Corrige el nombre, el idioma o las variables en la configuración o en Meta.')
    result = {'checked_at': stamp(now), 'ok': all(s['state'] != 'error' for s in steps) and bool(phone), 'steps': steps, 'phone': phone,
              'templates': templates[:200]}
    _bump(c, 'whatsapp_check', json.dumps(result, ensure_ascii=False))
    return result


def _template_summary(t):
    body = next((comp.get('text', '') for comp in (t.get('components') or []) if comp.get('type') == 'BODY'), '')
    variables = len(set(re.findall(r'\{\{\s*(\d+)\s*\}\}', body)))
    return {'name': t.get('name', ''), 'language': t.get('language', ''), 'status': t.get('status', ''), 'category': t.get('category', ''),
            'variables': variables, 'named': t.get('parameter_format') == 'NAMED', 'body': body[:600]}


def template_issues(cfg, templates):
    """Plantillas configuradas que no existen, no están aprobadas, están en otro idioma o esperan otra cantidad de variables."""
    out = []
    index = {(t['name'], t['language']): t for t in templates}
    uses = []
    if cfg['general_template']:
        uses.append(('general', 'Plantilla general', cfg['general_template'], cfg['general_lang'] or 'es', 3))
    for code, ev in cfg['events'].items():
        if ev['template']:
            uses.append((code, EVENTS[code][0], ev['template'], ev['lang'] or cfg['general_lang'] or 'es', 3))
    for code, label, name, lang, count in uses:
        found = index.get((name, lang))
        if not found:
            other = [t['language'] for t in templates if t['name'] == name]
            text = 'No existe «%s» en %s.' % (name, lang) + (' Está en: %s.' % ', '.join(other) if other else '')
        elif found['status'] != 'APPROVED':
            text = '«%s» está en estado %s (debe estar APPROVED).' % (name, found['status'])
        elif found['named']:
            text = '«%s» usa variables con nombre; el sistema envía variables numeradas {{1}}, {{2}} y {{3}}.' % name
        elif found['variables'] != count:
            text = '«%s» tiene %d variables y el aviso envía %d.' % (name, found['variables'], count)
        else:
            continue
        out.append({'event': code, 'label': label, 'text': text})
    return out


def last_check(c):
    row = c.execute("SELECT value FROM system_state WHERE key='whatsapp_check'").fetchone()
    try:
        return json.loads(row['value']) if row else None
    except ValueError:
        return None


# ---- Lectura para la interfaz ------------------------------------------------------------------------------------------------------
def item(c, row, env=None):
    row = dict(row)
    label = EVENTS[row['event']][0] if row['event'] in EVENTS else ('Mensaje de prueba' if row['event'] == 'prueba' else row['event'])
    try:
        params = json.loads(row['params'] or '[]')
    except ValueError:
        params = []
    return {'id': row['id'], 'event': row['event'], 'label': label, 'channel': 'whatsapp', 'status': row['status'], 'status_label': STATE_LABELS.get(row['status'], row['status']),
            'detail': row['detail'], 'reason_kind': row['reason_kind'], 'error_code': row['error_code'], 'permanent': bool(row['permanent']), 'attempts': row['attempts'],
            'next_attempt_at': row['next_attempt_at'], 'recipient': _mask_phone(row['recipient']), 'template': row['template'], 'template_lang': row['template_lang'],
            'params': params, 'preview': row['preview'], 'source': row['source'], 'order_id': row['order_id'], 'part_request_id': row['part_request_id'],
            'appointment_id': row['appointment_id'], 'created_at': row['created_at'], 'updated_at': row['updated_at'], 'sent_at': row['sent_at'],
            'delivered_at': row['delivered_at'], 'read_at': row['read_at'], 'provider': bool(row['provider_id']), 'message_id': row['message_id'],
            'can_retry': can_retry(c, row, env)}


def _mask_phone(number):
    number = str(number or '')
    return ('+' + number[:3] + ' ••• ' + number[-4:]) if len(number) >= 8 else number


def for_order(c, oid, user, env=None):
    if not user or _role(user) not in ('administrador', 'tecnico'):
        raise WhatsAppError('Acceso no permitido.', 403)
    o = _order(c, oid)
    if not o:
        raise WhatsAppError('Orden no disponible.', 404)
    number = number_for(o['phone'])
    cfg = settings(c)
    rows = [item(c, r, env) for r in c.execute('SELECT * FROM whatsapp_outbox WHERE order_id=? ORDER BY id DESC LIMIT 60', (oid,))]
    return {'ready': ready(env), 'auto': cfg['auto'], 'number': _mask_phone(number), 'valid_number': bool(number), 'consent': consent_state(c, number),
            'consent_sources': {k: v for k, v in CONSENT_SOURCES.items() if k != 'baja'}, 'items': rows,
            'manual_events': [{'code': k, 'label': v[0]} for k, v in EVENTS.items() if v[1] == 'orden'], 'states': STATE_LABELS}


def for_part(c, rid, env=None):
    return [item(c, r, env) for r in c.execute('SELECT * FROM whatsapp_outbox WHERE part_request_id=? ORDER BY id DESC LIMIT 40', (rid,))]


def history(c, filters, env=None):
    where, args = [], []
    status = str(filters.get('status', '') or '')
    if status in STATES:
        where.append('status=?')
        args.append(status)
    event = str(filters.get('event', '') or '')
    if event in EVENTS or event == 'prueba':
        where.append('event=?')
        args.append(event)
    try:
        page = max(0, int(filters.get('page', 0) or 0))
    except (TypeError, ValueError):
        page = 0
    sql = 'SELECT * FROM whatsapp_outbox' + (' WHERE ' + ' AND '.join(where) if where else '')
    total = c.execute(sql.replace('SELECT *', 'SELECT COUNT(*)', 1), args).fetchone()[0]
    rows = [item(c, r, env) for r in c.execute(sql + ' ORDER BY id DESC LIMIT 50 OFFSET ?', args + [page * 50])]
    ids = sorted({x['order_id'] for x in rows if x['order_id']})
    codes = {r['id']: r['code'] for r in c.execute('SELECT id,code FROM orders WHERE id IN (%s)' % ','.join('?' * len(ids)), ids)} if ids else {}
    for r in rows:
        r['order_code'] = codes.get(r['order_id'], '')
    counts = {s: 0 for s in STATES}
    for r in c.execute('SELECT status,COUNT(*) n FROM whatsapp_outbox GROUP BY status'):
        counts[r['status']] = r['n']
    return {'rows': rows, 'total': total, 'page': page, 'counts': counts}


def overview(c, base_url='', env=None):
    """Todo lo que necesita el panel de administración. Sin secretos."""
    cfg = config(env)
    rejected = c.execute("SELECT value FROM system_state WHERE key='whatsapp_webhook_rejected'").fetchone()
    last = c.execute("SELECT value FROM system_state WHERE key='whatsapp_webhook_last'").fetchone()
    check_data = last_check(c)
    state = 'sin_configurar' if not ready(env) else ('conectado' if check_data and check_data.get('ok') else 'error' if check_data else 'sin_comprobar')
    return {'state': state, 'ready': ready(env), 'requirements': requirements(env), 'version': version_info(env), 'settings': settings(c), 'check': check_data,
            'webhook': {'url': base_url.rstrip('/') + '/api/public/whatsapp/webhook', 'verify_token': bool(cfg['verify']), 'app_secret': bool(cfg['secret']),
                        'last_event': last['value'] if last else '', 'rejected': json.loads(rejected['value']) if rejected else {'count': 0, 'last': ''}},
            'events': [{'code': k, 'label': v[0], 'group': v[1], 'group_label': GROUPS[v[1]], 'when': v[3], 'auto': v[4], 'params': PARAMS[v[1]]} for k, v in EVENTS.items()],
            'general_params': GENERAL_PARAMS, 'states': STATE_LABELS, 'errors': [{'code': k, 'permanent': v[0], 'kind': v[1], 'text': v[2]} for k, v in ERRORS.items() if k != '0']}
