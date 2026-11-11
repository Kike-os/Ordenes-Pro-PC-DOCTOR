"""PQRS: peticiones, quejas, reclamos y sugerencias de clientes (1.5.278).

- Formulario público (/pqrs) sin sesión, bilingüe (es-EC / en-US). El servidor valida todo y guarda el caso con un código único
  PQRS-AAAA-NNNN: el número se reserva dentro de la transacción exclusiva de la petición y el código además es UNIQUE en la base.
- Enlace con una orden: solo si el número de orden y la identificación del cliente de esa orden coinciden. La respuesta es la misma
  coincidan o no: conocer un número de orden no revela nada.
- Seguimiento público (/pqrs/seguimiento) con el código y un token privado (HMAC del código con una clave aleatoria guardada en la
  base, nunca en el código fuente). Solo muestra estado, fechas y los mensajes públicos; nunca notas internas, datos de contacto ni adjuntos.
- Adjuntos: hasta 3 fotografías o PDF de hasta 10 MiB, subidos por partes (Vercel limita cada petición a 4,5 MB). El tipo se comprueba
  por sus primeros bytes, no por el nombre; se guardan en la base (no en disco ni en una carpeta pública) y nunca se ejecutan.
- Personal: administración ve y gestiona todas; un técnico solo ve y responde las que tiene asignadas (comprobado aquí, en el servidor).
- Conservación: los casos, su historial y sus adjuntos no se borran (disparadores en la base). Decisión de administración, 11/11/2026.
- Avisos: correo al cliente en su idioma (recepción, cambios de estado, respuestas y cierre) con el resultado de cada intento y
  reintento manual; WhatsApp por la cola oficial cuando está configurada y el cliente lo autorizó."""
import base64
import csv
import hashlib
import hmac
import io
import json
import re
import secrets
from datetime import datetime, timedelta

import appointments

CATEGORIES = ('peticion', 'queja', 'reclamo', 'sugerencia')
CATEGORY_LABELS = {'peticion': ('Petición', 'Request'), 'queja': ('Queja', 'Complaint'), 'reclamo': ('Reclamo', 'Claim'), 'sugerencia': ('Sugerencia', 'Suggestion')}
STATUSES = ('recibida', 'en_revision', 'asignada', 'esperando_cliente', 'en_solucion', 'respondida', 'cerrada')
STATUS_LABELS = {'recibida': ('Recibida', 'Received'), 'en_revision': ('En revisión', 'Under review'), 'asignada': ('Asignada', 'Assigned'),
                 'esperando_cliente': ('Esperando información del cliente', 'Waiting for your information'),
                 'en_solucion': ('En proceso de solución', 'Resolution in progress'), 'respondida': ('Respondida', 'Answered'), 'cerrada': ('Cerrada', 'Closed')}
PRIORITIES = ('baja', 'normal', 'alta', 'urgente')
PRIORITY_LABELS = {'baja': 'Baja', 'normal': 'Normal', 'alta': 'Alta', 'urgente': 'Urgente'}
# Estados que un técnico puede fijar en un caso asignado (cerrar y reabrir son de administración).
TECH_STATUSES = ('en_revision', 'esperando_cliente', 'en_solucion', 'respondida')
MAX_FILES = 3
MAX_BYTES = 10 * 1024 * 1024
PART_BYTES = 2_621_440
THUMB_BYTES = 300_000
SETTINGS_KEY = 'pqrs_settings'
DEFAULTS = {'sites': ['Matriz']}
EMAIL_RE = re.compile(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+')
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
FIRST_RESPONSE_HOURS = 48  # indicador interno: casos abiertos sin primera respuesta pasado este plazo


class PqrsError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def clean(value, limit, multiline=False):
    """Texto sin caracteres de control (se muestra siempre como texto, nunca como HTML)."""
    text = CONTROL.sub('', str(value or '')).replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text) if multiline else re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip() if multiline else text.strip()
    return text[:limit]


def english(lang):
    return lang == 'en-US'


def label(table, key, lang):
    pair = table.get(key, (key, key))
    return pair[1] if english(lang) else pair[0]


# ---- Configuración ------------------------------------------------------------------------------------------------------------
def settings(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (SETTINGS_KEY,)).fetchone()
    data = dict(DEFAULTS)
    if row:
        try:
            saved = json.loads(row['value'])
            if isinstance(saved.get('sites'), list) and saved['sites']:
                data['sites'] = [str(x) for x in saved['sites']]
        except (ValueError, TypeError, AttributeError):
            pass
    return data


def save_settings(c, data, user, now):
    if user['role'] != 'administrador':
        raise PqrsError('Acceso no permitido.', 403)
    raw = str(data.get('sites', ''))
    sites, seen = [], set()
    for line in raw.split('\n'):
        name = clean(line, 80)
        if name and name.casefold() not in seen:
            sites.append(name)
            seen.add(name.casefold())
    if not sites:
        raise PqrsError('Indica al menos una sede.', 400, {'sites': 'Indica al menos una sede.'})
    if len(sites) > 20:
        raise PqrsError('Admite hasta 20 sedes.', 400, {'sites': 'Admite hasta 20 sedes.'})
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SETTINGS_KEY, json.dumps({'sites': sites}, ensure_ascii=False)))
    return settings(c)


def options(c):
    """Lo que necesita el formulario público (sin datos internos)."""
    return {'categories': list(CATEGORIES), 'sites': settings(c)['sites'], 'max_files': MAX_FILES, 'max_bytes': MAX_BYTES, 'part_bytes': PART_BYTES,
            'privacy_url': '/privacidad'}


# ---- Enlace privado de seguimiento ----------------------------------------------------------------------------------------------
def _link_key(c):
    """Clave aleatoria de PQRS (se crea una vez y se guarda en la base; no está en el código ni se muestra)."""
    row = c.execute("SELECT value FROM system_state WHERE key='pqrs_link_key'").fetchone()
    if row and len(row['value']) >= 43:
        return row['value']
    key = secrets.token_urlsafe(32)
    c.execute("INSERT INTO system_state(key,value) VALUES ('pqrs_link_key',?) ON CONFLICT(key) DO NOTHING", (key,))
    return c.execute("SELECT value FROM system_state WHERE key='pqrs_link_key'").fetchone()['value']


def track_token(c, code):
    return base64.urlsafe_b64encode(hmac.new(_link_key(c).encode(), ('pqrs:' + code).encode(), hashlib.sha256).digest()[:24]).decode().rstrip('=')


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def track_url(c, base_url, code):
    return base_url.rstrip('/') + '/pqrs/seguimiento?codigo=' + code + '&token=' + track_token(c, code)


# ---- Adjuntos (formulario público) ---------------------------------------------------------------------------------------------
def _cleanup(c, now):
    limit = stamp(now - timedelta(hours=24))
    for (uid,) in c.execute("SELECT id FROM pqrs_uploads WHERE status!='usada' AND created_at<?", (limit,)).fetchall():
        c.execute('DELETE FROM pqrs_upload_parts WHERE upload_id=?', (uid,))
        c.execute('DELETE FROM pqrs_uploads WHERE id=?', (uid,))


def _draft(value):
    value = str(value or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{22,64}', value):
        raise PqrsError('Actualiza el formulario e inténtalo nuevamente.', 400)
    return value


def _upload(c, token, draft):
    token = str(token or '')
    row = c.execute('SELECT * FROM pqrs_uploads WHERE token=? AND draft=?', (token, draft)).fetchone() if re.fullmatch(r'[A-Za-z0-9_-]{22,43}', token) else None
    if not row:
        raise PqrsError('La carga no existe o expiró. Vuelve a adjuntar el archivo.', 404)
    return row


def _name(value):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(value or 'archivo')).strip(' .') or 'archivo'
    return name[:120]


def upload_start(c, data, now, ip_hash):
    import order_evidence
    _cleanup(c, now)
    draft = _draft(data.get('draft'))
    if c.execute("SELECT COUNT(*) FROM pqrs_uploads WHERE draft=? AND status!='usada'", (draft,)).fetchone()[0] >= MAX_FILES:
        raise PqrsError('Puedes adjuntar hasta 3 archivos.', 400, {'files': 'Puedes adjuntar hasta 3 archivos.'})
    try:
        size = int(str(data.get('size', '')))
    except ValueError:
        size = 0
    if size <= 0:
        raise PqrsError('El archivo está vacío.', 400, {'files': 'El archivo está vacío.'})
    if size > MAX_BYTES:
        raise PqrsError('Cada archivo puede pesar como máximo 10 MB.', 400, {'files': 'Cada archivo puede pesar como máximo 10 MB.'})
    if str(data.get('type', '')) and str(data.get('type')) not in order_evidence.EXTENSIONS:
        raise PqrsError('Solo se admiten fotografías (JPG, PNG, WEBP) y documentos PDF.', 400, {'files': 'Solo se admiten fotografías (JPG, PNG, WEBP) y documentos PDF.'})
    digest = str(data.get('sha256', '')).lower()
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise PqrsError('Carga no válida. Vuelve a adjuntar el archivo.', 400)
    parts = -(-size // PART_BYTES)
    token = secrets.token_urlsafe(24)
    c.execute('INSERT INTO pqrs_uploads(token,draft,name,size,sha256,parts,ip_hash,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (token, draft, _name(data.get('name')), size, digest, parts, ip_hash, stamp(now)))
    return {'token': token, 'parts': parts, 'part_bytes': PART_BYTES}


def upload_part(c, data):
    row = _upload(c, data.get('token'), _draft(data.get('draft')))
    if row['status'] != 'subiendo':
        raise PqrsError('Esta carga ya terminó.', 409)
    try:
        idx = int(str(data.get('index', '')))
    except ValueError:
        idx = -1
    if not 0 <= idx < row['parts']:
        raise PqrsError('Parte no válida.', 400)
    try:
        raw = base64.b64decode(str(data.get('data', '')), validate=True)
    except (ValueError, TypeError):
        raise PqrsError('Una parte del archivo llegó dañada. Reintenta.', 400)
    expected = PART_BYTES if idx < row['parts'] - 1 else row['size'] - PART_BYTES * (row['parts'] - 1)
    if len(raw) != expected:
        raise PqrsError('Una parte del archivo llegó incompleta. Reintenta.', 400)
    c.execute('INSERT OR IGNORE INTO pqrs_upload_parts(upload_id,idx,data) VALUES (?,?,?)', (row['id'], idx, base64.b64encode(raw).decode()))
    return {'index': idx}


def _bytes(c, upload_id):
    out = []
    for (idx,) in c.execute('SELECT idx FROM pqrs_upload_parts WHERE upload_id=? ORDER BY idx', (upload_id,)).fetchall():
        out.append(base64.b64decode(c.execute('SELECT data FROM pqrs_upload_parts WHERE upload_id=? AND idx=?', (upload_id, idx)).fetchone()[0]))
    return b''.join(out)


def upload_finish(c, data):
    """Verifica el archivo completo: tamaño, SHA-256 y tipo real por sus primeros bytes. Si no coincide, la carga se descarta."""
    import order_evidence
    row = _upload(c, data.get('token'), _draft(data.get('draft')))
    if row['status'] == 'lista':
        return {'token': row['token'], 'mime': row['mime'], 'size': row['size']}
    if row['status'] != 'subiendo':
        raise PqrsError('Esta carga ya se usó.', 409)
    have = c.execute('SELECT COUNT(*) FROM pqrs_upload_parts WHERE upload_id=?', (row['id'],)).fetchone()[0]
    if have != row['parts']:
        raise PqrsError('Faltan partes del archivo. Reintenta.', 409)
    raw = _bytes(c, row['id'])
    mime = order_evidence.sniff(raw)
    problem = ('El archivo no coincide con lo que se envió.' if len(raw) != row['size'] or hashlib.sha256(raw).hexdigest() != row['sha256']
               else 'Solo se admiten fotografías (JPG, PNG, WEBP) y documentos PDF.' if not mime else '')
    if problem:
        c.execute('DELETE FROM pqrs_upload_parts WHERE upload_id=?', (row['id'],))
        c.execute('DELETE FROM pqrs_uploads WHERE id=?', (row['id'],))
        raise PqrsError(problem, 400, {'files': problem})
    thumb = ''
    if mime != 'application/pdf' and data.get('thumb'):
        try:
            small = base64.b64decode(str(data.get('thumb')).split(',')[-1], validate=True)
        except (ValueError, TypeError):
            small = b''
        if small and len(small) <= THUMB_BYTES and order_evidence.sniff(small) in ('image/jpeg', 'image/png', 'image/webp'):
            thumb = base64.b64encode(small).decode()
    c.execute("UPDATE pqrs_uploads SET status='lista',mime=?,thumb=? WHERE id=?", (mime, thumb, row['id']))
    return {'token': row['token'], 'mime': mime, 'size': row['size']}


def upload_cancel(c, data):
    row = _upload(c, data.get('token'), _draft(data.get('draft')))
    if row['status'] == 'usada':
        raise PqrsError('Ese archivo ya forma parte de una PQRS.', 409)
    c.execute('DELETE FROM pqrs_upload_parts WHERE upload_id=?', (row['id'],))
    c.execute('DELETE FROM pqrs_uploads WHERE id=?', (row['id'],))
    return {'cancelled': True}


# ---- Registro ------------------------------------------------------------------------------------------------------------------
def next_code(c, year):
    """Siguiente número del año. Se llama dentro de la transacción exclusiva de la petición (BEGIN IMMEDIATE): dos solicitudes
    simultáneas no pueden reservar el mismo número, y el código es además UNIQUE en pqrs_cases."""
    c.execute('INSERT OR IGNORE INTO pqrs_sequence(year,last) VALUES (?,0)', (year,))
    c.execute('UPDATE pqrs_sequence SET last=last+1 WHERE year=?', (year,))
    number = c.execute('SELECT last FROM pqrs_sequence WHERE year=?', (year,)).fetchone()[0]
    return 'PQRS-%d-%04d' % (year, number)


def _link_order(c, order_code, identification):
    """(order_id, client_id, verificada). Solo enlaza si la identificación coincide con la del cliente de la orden."""
    import reception
    if not order_code or not identification:
        return None, None, 0
    row = c.execute('SELECT o.id,cl.id client_id,cl.identification FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.code=?',
                    (reception.current_order_code(c, order_code),)).fetchone()
    if row and re.sub(r'\W', '', str(row['identification'] or '')).upper() == re.sub(r'\W', '', identification).upper():
        return row['id'], row['client_id'], 1
    return None, None, 0


def validate(c, data):
    import phones
    fields, errors = {}, {}
    fields['category'] = str(data.get('category', ''))
    if fields['category'] not in CATEGORIES:
        errors['category'] = 'Elige el tipo de solicitud.'
    fields['name'] = clean(data.get('name'), 150)
    if len([p for p in fields['name'].split(' ') if len(p) >= 2]) < 2:
        errors['name'] = 'Ingresa tus nombres y apellidos completos.'
    fields['email'] = clean(data.get('email'), 254).lower()
    if not EMAIL_RE.fullmatch(fields['email']):
        errors['email'] = 'Ingresa un correo electrónico válido.'
    phone = clean(data.get('phone'), 40)
    if not phone or not phones.valid(phone):
        errors['phone'] = 'Ingresa un número de contacto válido.'
    fields['phone'] = (phones.normalize(phone)[0] or phone) if phone else ''
    sites = settings(c)['sites']
    fields['site'] = clean(data.get('site'), 80) or (sites[0] if len(sites) == 1 else '')
    if fields['site'] not in sites:
        errors['site'] = 'Elige la sede o establecimiento.'
    fields['subject'] = clean(data.get('subject'), 150)
    if len(fields['subject']) < 5:
        errors['subject'] = 'Escribe un asunto (mínimo 5 caracteres).'
    fields['description'] = clean(data.get('description'), 5000, multiline=True)
    if len(fields['description']) < 20:
        errors['description'] = 'Describe tu solicitud con al menos 20 caracteres.'
    fields['order_code'] = clean(data.get('order_code'), 40).upper().replace(' ', '')
    if fields['order_code'] and not re.fullmatch(r'[A-Z0-9-]{4,40}', fields['order_code']):
        errors['order_code'] = 'Revisa el número de orden: solo letras, números y guiones.'
    fields['identification'] = clean(data.get('identification'), 30)
    if fields['identification'] and not re.fullmatch(r'[A-Za-z0-9-]{5,30}', fields['identification']):
        errors['identification'] = 'Revisa el número de identificación.'
    if data.get('privacy_consent') is not True:
        errors['privacy_consent'] = 'Acepta la política de privacidad y tratamiento de datos personales.'
    fields['whatsapp_consent'] = data.get('whatsapp_consent') is True
    fields['files'] = [t for t in str(data.get('files', '')).split(',') if t][:MAX_FILES + 1]
    if len(fields['files']) > MAX_FILES:
        errors['files'] = 'Puedes adjuntar hasta 3 archivos.'
    return fields, errors


def create(c, data, now, ip_hash, base_url=''):
    """Registra la PQRS. Devuelve el código, el token privado de seguimiento y el idioma. Una petición repetida (mismo request_key)
    devuelve el caso ya registrado sin duplicarlo."""
    key = str(data.get('request_key', ''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}', key):
        raise PqrsError('Actualiza el formulario e inténtalo nuevamente.', 400)
    lang = appointments.ui_language(data.get('locale'))
    previous = c.execute('SELECT code,language FROM pqrs_cases WHERE request_key=?', (key,)).fetchone()
    if previous:
        return {'code': previous['code'], 'token': track_token(c, previous['code']), 'duplicate': True, 'language': previous['language']}
    fields, errors = validate(c, data)
    draft = str(data.get('draft', ''))
    uploads = []
    if fields['files'] and not errors.get('files'):
        try:
            _draft(draft)
            for token in fields['files']:
                row = _upload(c, token, draft)
                if row['status'] != 'lista':
                    raise PqrsError('Un archivo adjunto no terminó de subirse. Vuelve a adjuntarlo.', 400)
                uploads.append(row)
        except PqrsError as error:
            errors['files'] = str(error)
    if errors:
        raise PqrsError('Revisa los datos marcados.', 400, errors)
    order_id, client_id, verified = _link_order(c, fields['order_code'], fields['identification'])
    code = next_code(c, now.year)
    created = stamp(now)
    cur = c.execute('INSERT INTO pqrs_cases(code,request_key,track_hash,category,language,name,email,phone,site,subject,description,order_code,order_id,order_verified,client_id,'
                    'privacy_consent,whatsapp_consent,ip_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)',
                    (code, key, token_hash(track_token(c, code)), fields['category'], lang, fields['name'], fields['email'], fields['phone'], fields['site'], fields['subject'],
                     fields['description'], fields['order_code'], order_id, verified, client_id, int(fields['whatsapp_consent']), ip_hash, created, created))
    cid = cur.lastrowid
    for row in uploads:
        c.execute("UPDATE pqrs_uploads SET status='usada',case_id=? WHERE id=?", (cid, row['id']))
    event(c, cid, 'creada', True, '', '', 'recibida', None, now)
    if fields['whatsapp_consent']:
        try:
            import whatsapp_business
            whatsapp_business.record_consent(c, fields['phone'], 'aceptado', 'formulario', now, client_id, None, 'Formulario PQRS ' + code)
        except Exception as error:
            print('pqrs-whatsapp-consent', type(error).__name__, flush=True)
    queue(c, cid, 'recibida', now)
    return {'code': code, 'token': track_token(c, code), 'status': 'recibida', 'language': lang, 'created_at': created, 'id': cid}


def event(c, cid, kind, public, body, old, new, actor, now):
    return c.execute('INSERT INTO pqrs_events(case_id,kind,public,body,old_value,new_value,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
                     (cid, kind, int(bool(public)), body, old or '', new or '', actor, stamp(now))).lastrowid


# ---- Avisos al cliente ---------------------------------------------------------------------------------------------------------
EMAIL_EVENTS = ('recibida', 'estado', 'respuesta', 'cierre')
WHATSAPP_EVENTS = {'recibida': 'pqrs_recibida', 'estado': 'pqrs_actualizada', 'respuesta': 'pqrs_respondida', 'cierre': 'pqrs_actualizada'}


def queue(c, cid, kind, now, event_id=None):
    """Registra el aviso por correo (se envía al terminar la petición, fuera de la transacción) y encola el de WhatsApp."""
    case = c.execute('SELECT * FROM pqrs_cases WHERE id=?', (cid,)).fetchone()
    nid = c.execute("INSERT INTO pqrs_notifications(case_id,event,channel,recipient,result,event_id,created_at,updated_at) VALUES (?,?, 'email',?,'pendiente',?,?,?)",
                    (cid, kind, case['email'], event_id, stamp(now), stamp(now))).lastrowid
    try:
        import whatsapp_business
        whatsapp_business.enqueue(c, WHATSAPP_EVENTS[kind], 'pqrs:%d:%s:%s' % (cid, kind, event_id or 0), now, pqrs_id=cid, source='pqrs')
    except Exception as error:
        print('pqrs-whatsapp', type(error).__name__, flush=True)
    return nid


def compose_email(c, case, kind, body, base_url, config, signature=None):
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid
    import mail_pro
    import mailing
    from corporate import settings as company_settings
    company = company_settings()
    lang = case['language']
    en = english(lang)
    status = label(STATUS_LABELS, case['status'], lang)
    category = label(CATEGORY_LABELS, case['category'], lang)
    first = case['name'].split(' ')[0]
    titles = {'recibida': ('Solicitud recibida correctamente', 'Request Successfully Received'), 'estado': ('Actualización de su PQRS', 'Update on your request'),
              'respuesta': ('Respuesta a su PQRS', 'Response to your request'), 'cierre': ('PQRS cerrada', 'Request closed')}
    leads = {'recibida': ('Registramos su solicitud. Nuestro equipo la revisará y le responderá por este medio.', 'We have registered your request. Our team will review it and reply through this channel.'),
             'estado': ('Su solicitud cambió de estado.', 'The status of your request has changed.'),
             'respuesta': ('Nuestro equipo respondió su solicitud:', 'Our team has replied to your request:'),
             'cierre': ('Su solicitud fue cerrada con la siguiente resolución:', 'Your request has been closed with the following resolution:')}
    title = titles[kind][1 if en else 0]
    lead = leads[kind][1 if en else 0]
    facts = [(('Tracking number' if en else 'Número de seguimiento'), case['code']), (('Type' if en else 'Tipo'), category),
             (('Status' if en else 'Estado'), status), (('Subject' if en else 'Asunto'), case['subject'])]
    link = track_url(c, base_url, case['code']) if base_url else ''
    track = (('Track your request here (private link, do not share it): ' if en else 'Consulte el estado aquí (enlace privado, no lo comparta): ') + link) if link else ''
    greeting = ('Hello ' if en else 'Hola ') + first + ':'
    text = '\n\n'.join(x for x in (greeting, lead, body, '\n'.join(a + ': ' + b for a, b in facts), track,
                                     ('WhatsApp ' + company['whatsapp'] + ' · ' + company['website'])) if x)
    sign = signature if isinstance(signature, dict) and signature.get('enabled') else None
    sign_html, sign_cid, sign_image, sign_kind = mail_pro.signature_part(sign, config['username'].split('@')[-1]) if sign else ('', '', None, 'png')
    page = mailing.html(text, title, sign_html)
    plain = text + ('\n\n-- \n' + mail_pro.signature_text(sign) if sign else '') + '\n\n' + company['name']
    message = EmailMessage()
    message['From'] = company['name'] + ' <' + config['username'] + '>'
    message['To'] = case['email']
    message['Subject'] = title + ' — ' + case['code'] + ' | ' + company['name']
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=config['username'].split('@')[-1])
    message.set_content(plain)
    message.add_alternative(page, subtype='html')
    if sign_image:
        message.get_payload()[1].add_related(sign_image, 'image', sign_kind, cid=sign_cid, disposition='inline')
    return message, link


def deliver(c, nid, base_url):
    """Envía un aviso registrado y anota el resultado real. Nunca lanza errores hacia el caso: si falla, el caso sigue registrado."""
    import mail_pro
    row = c.execute('SELECT * FROM pqrs_notifications WHERE id=?', (nid,)).fetchone()
    if not row or row['result'] == 'enviado':
        return row['result'] if row else None
    case = c.execute('SELECT * FROM pqrs_cases WHERE id=?', (row['case_id'],)).fetchone()
    body = ''
    if row['event_id']:
        ev = c.execute('SELECT body FROM pqrs_events WHERE id=?', (row['event_id'],)).fetchone()
        body = ev['body'] if ev else ''
    now = appointments.now()
    result, detail = 'enviado', 'El servidor de correo aceptó el mensaje.'
    try:
        ready = mail_pro.configured()
    except mail_pro.MailError:
        ready = False
    if not EMAIL_RE.fullmatch(case['email'] or ''):
        result, detail = 'sin_destinatario', 'El caso no tiene un correo válido.'
    elif not ready:
        result, detail = 'sin_configurar', 'El correo del sistema no está configurado en el servidor.'
    else:
        try:
            import mail_tracking
            import mailing
            config = mail_pro.settings()
            message, link = compose_email(c, case, row['event'], body, base_url, config, mail_pro.load_signature(c, config['username']))
            archive_id = mailing.archive(c, 'pqrs', case['order_id'], case['email'], str(message['Subject']), message, 'plantilla', None, now, private=(link,))
            tracked = mail_tracking.start(c, [case['email']], kind='pqrs', subject=str(message['Subject']), now=now, archive_id=archive_id, order_id=case['order_id'])
            c.commit()
            try:
                refusal = mail_tracking.blocked(c, case['email'])
                if refusal:
                    raise mail_pro.MailError('destinatario', refusal)
                outcome = mail_pro.deliver(config, message, [case['email']])
            except mail_pro.MailError as error:
                try:
                    mail_tracking.settle(c, lambda db: (mailing.mark(db, archive_id, 'error', str(error)), mail_tracking.failed(db, tracked, error, now)))
                except Exception as failure:
                    print('pqrs-mail registro', type(failure).__name__, flush=True)
                raise
            try:
                mail_tracking.settle(c, lambda db: (mailing.mark(db, archive_id, 'enviado', 'El servidor de correo aceptó el mensaje.', str(message['Message-ID'] or ''), now),
                                                    mail_tracking.accepted(db, tracked, str(message['Message-ID'] or ''), now, outcome)))
            except Exception as failure:
                print('pqrs-mail registro', type(failure).__name__, flush=True)
        except mail_pro.MailError as error:
            print('pqrs-mail', row['event'], error.kind, flush=True)
            result, detail = 'fallido', str(error)[:300]
        except Exception as error:
            print('pqrs-mail', row['event'], type(error).__name__, flush=True)
            result, detail = 'fallido', 'No se pudo preparar el mensaje.'
    c.execute('UPDATE pqrs_notifications SET result=?,detail=?,attempts=attempts+1,updated_at=? WHERE id=?', (result, detail, stamp(appointments.now()), nid))
    return result


def pending_ids(c, cid):
    return [r[0] for r in c.execute("SELECT id FROM pqrs_notifications WHERE case_id=? AND result='pendiente' ORDER BY id", (cid,))]


# ---- Seguimiento público -------------------------------------------------------------------------------------------------------
def _public_case(c, code, token):
    code = str(code or '').strip().upper()
    if not re.fullmatch(r'PQRS-\d{4}-\d{4,}', code) or not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', str(token or '')):
        return None
    row = c.execute('SELECT * FROM pqrs_cases WHERE code=?', (code,)).fetchone()
    if not row or not hmac.compare_digest(row['track_hash'], token_hash(token)):
        return None
    return row


def public_view(c, code, token):
    """Estado y mensajes públicos. Sin correo, teléfono, notas internas, responsables ni adjuntos."""
    row = _public_case(c, code, token)
    if not row:
        raise PqrsError('No encontramos una PQRS con esos datos. Revisa el código y el enlace de seguimiento.', 404)
    timeline = []
    for ev in c.execute("SELECT kind,body,new_value,created_at FROM pqrs_events WHERE case_id=? AND public=1 ORDER BY id", (row['id'],)):
        timeline.append({'kind': ev['kind'], 'body': ev['body'] if ev['kind'] in ('respuesta', 'mensaje_cliente', 'cierre', 'reapertura') else '',
                         'status': ev['new_value'] if ev['kind'] in ('creada', 'estado', 'cierre', 'reapertura') else '', 'at': ev['created_at']})
    return {'code': row['code'], 'category': row['category'], 'status': row['status'], 'site': row['site'], 'subject': row['subject'], 'created_at': row['created_at'],
            'updated_at': row['updated_at'], 'language': row['language'], 'timeline': timeline, 'can_reply': row['status'] != 'cerrada',
            'files': c.execute("SELECT COUNT(*) FROM pqrs_uploads WHERE case_id=? AND status='usada'", (row['id'],)).fetchone()[0]}


def client_reply(c, code, token, message, now):
    row = _public_case(c, code, token)
    if not row:
        raise PqrsError('No encontramos una PQRS con esos datos. Revisa el código y el enlace de seguimiento.', 404)
    if row['status'] == 'cerrada':
        raise PqrsError('Esta PQRS está cerrada. Si necesitas ayuda, registra una nueva solicitud.', 409)
    text = clean(message, 2000, multiline=True)
    if len(text) < 2:
        raise PqrsError('Escribe tu mensaje.', 400, {'message': 'Escribe tu mensaje.'})
    event(c, row['id'], 'mensaje_cliente', True, text, '', '', None, now)
    if row['status'] in ('esperando_cliente', 'respondida'):
        event(c, row['id'], 'estado', True, '', row['status'], 'en_revision', None, now)
        c.execute("UPDATE pqrs_cases SET status='en_revision',updated_at=? WHERE id=?", (stamp(now), row['id']))
    else:
        c.execute('UPDATE pqrs_cases SET updated_at=? WHERE id=?', (stamp(now), row['id']))
    return public_view(c, code, token)


# ---- Personal ------------------------------------------------------------------------------------------------------------------
def _staff(user):
    if user['role'] not in ('administrador', 'tecnico'):
        raise PqrsError('Acceso no permitido.', 403)


def _case_for(c, user, cid):
    """El caso, si este usuario puede verlo (administración: todos; técnico: solo los asignados). Error genérico si no."""
    _staff(user)
    row = c.execute('SELECT * FROM pqrs_cases WHERE id=?', (cid,)).fetchone()
    if not row or (user['role'] != 'administrador' and row['assigned_to'] != user['id']):
        raise PqrsError('PQRS no disponible.', 404)
    return row


def _hours(a, b):
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def metrics(c, now, where='1=1', args=()):
    rows = c.execute('SELECT status,created_at,first_response_at,closed_at FROM pqrs_cases WHERE ' + where, args).fetchall()
    first = [h for h in (_hours(r['created_at'], r['first_response_at']) for r in rows if r['first_response_at']) if h is not None]
    solved = [h for h in (_hours(r['created_at'], r['closed_at']) for r in rows if r['closed_at']) if h is not None]
    late = sum(1 for r in rows if r['status'] != 'cerrada' and not r['first_response_at'] and (_hours(r['created_at'], stamp(now)) or 0) > FIRST_RESPONSE_HOURS)
    return {'total': len(rows), 'open': sum(1 for r in rows if r['status'] != 'cerrada'), 'new': sum(1 for r in rows if r['status'] == 'recibida'),
            'first_response_hours': round(sum(first) / len(first), 1) if first else None, 'resolution_hours': round(sum(solved) / len(solved), 1) if solved else None,
            'late_first_response': late, 'late_hours': FIRST_RESPONSE_HOURS,
            'by_status': {s: sum(1 for r in rows if r['status'] == s) for s in STATUSES}}


def _filters(user, params):
    where, args = [], []
    if user['role'] != 'administrador':
        where.append('p.assigned_to=?')
        args.append(user['id'])
    get = lambda name: str(params.get(name, '') or '').strip()
    if get('status') in STATUSES:
        where.append('p.status=?')
        args.append(get('status'))
    elif get('status') == 'abiertas':
        where.append("p.status!='cerrada'")
    if get('category') in CATEGORIES:
        where.append('p.category=?')
        args.append(get('category'))
    if get('site'):
        where.append('p.site=?')
        args.append(get('site')[:80])
    if get('priority') in PRIORITIES:
        where.append('p.priority=?')
        args.append(get('priority'))
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', get('from')):
        where.append('p.created_at>=?')
        args.append(get('from'))
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', get('to')):
        where.append('p.created_at<?')
        args.append((datetime.fromisoformat(get('to')) + timedelta(days=1)).date().isoformat())
    if get('assigned') == 'me':
        where.append('p.assigned_to=?')
        args.append(user['id'])
    q = get('q')[:80]
    if q:
        where.append('(p.code LIKE ? OR p.name LIKE ? OR p.email LIKE ? OR p.subject LIKE ? OR p.order_code LIKE ?)')
        args += ['%' + q + '%'] * 5
    return (' AND '.join(where) or '1=1'), args


def list_cases(c, user, params, now):
    _staff(user)
    where, args = _filters(user, params)
    try:
        page = max(1, int(str(params.get('page', '1'))))
    except ValueError:
        page = 1
    total = c.execute('SELECT COUNT(*) FROM pqrs_cases p WHERE ' + where, args).fetchone()[0]
    rows = [dict(r) for r in c.execute('SELECT p.id,p.code,p.category,p.status,p.priority,p.language,p.name,p.site,p.subject,p.order_code,p.order_verified,p.created_at,p.updated_at,'
                                       'p.first_response_at,p.closed_at,u.name assigned_name FROM pqrs_cases p LEFT JOIN users u ON u.id=p.assigned_to WHERE ' + where +
                                       " ORDER BY CASE p.status WHEN 'recibida' THEN 0 WHEN 'cerrada' THEN 2 ELSE 1 END, CASE p.priority WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, p.id DESC LIMIT 25 OFFSET ?",
                                       args + [(page - 1) * 25])]
    scope = ('p.assigned_to=?', (user['id'],)) if user['role'] != 'administrador' else ('1=1', ())
    return {'rows': rows, 'total': total, 'page': page, 'pages': max(1, -(-total // 25)), 'metrics': metrics(c, now, scope[0].replace('p.', ''), scope[1]),
            'sites': settings(c)['sites'], 'admin': user['role'] == 'administrador'}


def new_count(c, user):
    if user['role'] == 'administrador':
        return c.execute("SELECT COUNT(*) FROM pqrs_cases WHERE status='recibida'").fetchone()[0]
    if user['role'] == 'tecnico':
        return c.execute("SELECT COUNT(*) FROM pqrs_cases WHERE assigned_to=? AND status IN ('asignada','en_revision')", (user['id'],)).fetchone()[0]
    return 0


def detail(c, user, cid):
    row = dict(_case_for(c, user, cid))
    row.pop('track_hash', None)
    row.pop('request_key', None)
    row.pop('ip_hash', None)
    row['assigned_name'] = (c.execute('SELECT name FROM users WHERE id=?', (row['assigned_to'],)).fetchone() or {'name': ''})['name'] if row['assigned_to'] else ''
    if row['order_id']:
        order = c.execute('SELECT id,code FROM orders WHERE id=?', (row['order_id'],)).fetchone()
        row['order'] = dict(order) if order else None
    row['events'] = [dict(r) for r in c.execute('SELECT e.id,e.kind,e.public,e.body,e.old_value,e.new_value,e.created_at,u.name actor FROM pqrs_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.case_id=? ORDER BY e.id', (cid,))]
    row['files'] = [dict(r) for r in c.execute("SELECT id,name,size,mime,thumb,parts FROM pqrs_uploads WHERE case_id=? AND status='usada' ORDER BY id", (cid,))]
    row['notifications'] = [dict(r) for r in c.execute('SELECT id,event,channel,recipient,result,detail,attempts,created_at,updated_at FROM pqrs_notifications WHERE case_id=? ORDER BY id', (cid,))]
    try:
        import whatsapp_business
        row['whatsapp'] = [whatsapp_business.item(c, r) for r in c.execute('SELECT * FROM whatsapp_outbox WHERE pqrs_id=? ORDER BY id', (cid,))]
    except Exception:
        row['whatsapp'] = []
    row['admin'] = user['role'] == 'administrador'
    row['staff'] = [dict(r) for r in c.execute("SELECT id,name,role FROM users WHERE role IN ('administrador','tecnico') AND active=1 ORDER BY name")] if row['admin'] else []
    row['allowed_statuses'] = [s for s in STATUSES if s != 'cerrada'] if row['admin'] else list(TECH_STATUSES)
    return row


def act(c, user, cid, data, now):
    """Acciones del personal. Devuelve los ids de avisos por correo que hay que enviar al terminar la petición."""
    row = _case_for(c, user, cid)
    admin = user['role'] == 'administrador'
    action = str(data.get('action', ''))
    notify = []
    touch = lambda **extra: c.execute('UPDATE pqrs_cases SET ' + ','.join(['updated_at=?'] + [k + '=?' for k in extra]) + ' WHERE id=?', [stamp(now)] + list(extra.values()) + [cid])
    if row['status'] == 'cerrada' and action not in ('reopen', 'note', 'retry'):
        raise PqrsError('La PQRS está cerrada. Reábrela para continuar.', 409)
    if action == 'status':
        new = str(data.get('status', ''))
        allowed = [s for s in STATUSES if s != 'cerrada'] if admin else list(TECH_STATUSES)
        if new not in allowed:
            raise PqrsError('Estado no permitido.', 400, {'status': 'Estado no permitido.'})
        if new != row['status']:
            eid = event(c, cid, 'estado', True, '', row['status'], new, user['id'], now)
            touch(status=new)
            notify.append(queue(c, cid, 'estado', now, eid))
    elif action == 'assign':
        if not admin:
            raise PqrsError('Acceso no permitido.', 403)
        target = str(data.get('user_id', ''))
        staff = c.execute("SELECT id,name FROM users WHERE id=? AND role IN ('administrador','tecnico') AND active=1", (int(target),)).fetchone() if target.isdigit() else None
        if not staff and target != '':
            raise PqrsError('Elige una persona del equipo.', 400, {'user_id': 'Elige una persona del equipo.'})
        new_id = staff['id'] if staff else None
        if new_id != row['assigned_to']:
            event(c, cid, 'asignacion', False, staff['name'] if staff else 'Sin asignar', str(row['assigned_to'] or ''), str(new_id or ''), user['id'], now)
            if staff and row['status'] in ('recibida', 'en_revision'):
                eid = event(c, cid, 'estado', True, '', row['status'], 'asignada', user['id'], now)
                touch(assigned_to=new_id, status='asignada')
                notify.append(queue(c, cid, 'estado', now, eid))
            else:
                touch(assigned_to=new_id)
    elif action == 'priority':
        if not admin:
            raise PqrsError('Acceso no permitido.', 403)
        new = str(data.get('priority', ''))
        if new not in PRIORITIES:
            raise PqrsError('Prioridad no válida.', 400, {'priority': 'Prioridad no válida.'})
        if new != row['priority']:
            event(c, cid, 'prioridad', False, '', row['priority'], new, user['id'], now)
            touch(priority=new)
    elif action == 'reply':
        body = clean(data.get('body'), 5000, multiline=True)
        if len(body) < 2:
            raise PqrsError('Escribe la respuesta para el cliente.', 400, {'body': 'Escribe la respuesta para el cliente.'})
        after = str(data.get('status', 'respondida'))
        if after not in ('respondida', 'esperando_cliente', 'en_solucion'):
            after = 'respondida'
        eid = event(c, cid, 'respuesta', True, body, '', '', user['id'], now)
        extra = {'first_response_at': row['first_response_at'] or stamp(now)}
        if after != row['status']:
            event(c, cid, 'estado', True, '', row['status'], after, user['id'], now)
            extra['status'] = after
        touch(**extra)
        notify.append(queue(c, cid, 'respuesta', now, eid))
    elif action == 'note':
        body = clean(data.get('body'), 5000, multiline=True)
        if len(body) < 2:
            raise PqrsError('Escribe la nota interna.', 400, {'body': 'Escribe la nota interna.'})
        event(c, cid, 'nota', False, body, '', '', user['id'], now)
        touch()
    elif action == 'close':
        if not admin:
            raise PqrsError('Acceso no permitido.', 403)
        body = clean(data.get('body'), 2000, multiline=True)
        if len(body) < 5:
            raise PqrsError('Escribe la resolución con la que se cierra el caso.', 400, {'body': 'Escribe la resolución con la que se cierra el caso.'})
        eid = event(c, cid, 'cierre', True, body, row['status'], 'cerrada', user['id'], now)
        touch(status='cerrada', closed_at=stamp(now), resolution=body, first_response_at=row['first_response_at'] or stamp(now))
        notify.append(queue(c, cid, 'cierre', now, eid))
    elif action == 'reopen':
        if not admin:
            raise PqrsError('Acceso no permitido.', 403)
        if row['status'] != 'cerrada':
            raise PqrsError('La PQRS no está cerrada.', 409)
        body = clean(data.get('body'), 2000, multiline=True)
        if len(body) < 5:
            raise PqrsError('Indica el motivo de la reapertura.', 400, {'body': 'Indica el motivo de la reapertura.'})
        eid = event(c, cid, 'reapertura', True, body, 'cerrada', 'en_revision', user['id'], now)
        touch(status='en_revision', closed_at='')
        notify.append(queue(c, cid, 'estado', now, eid))
    elif action == 'retry':
        nid = str(data.get('notification_id', ''))
        found = c.execute("SELECT id,result FROM pqrs_notifications WHERE id=? AND case_id=?", (int(nid), cid)).fetchone() if nid.isdigit() else None
        if not found:
            raise PqrsError('Aviso no encontrado.', 404)
        if found['result'] == 'enviado':
            raise PqrsError('Ese aviso ya se envió.', 409)
        c.execute("UPDATE pqrs_notifications SET result='pendiente',updated_at=? WHERE id=?", (stamp(now), found['id']))
        notify.append(found['id'])
    else:
        raise PqrsError('Acción no válida.', 400)
    return notify


# ---- Adjuntos para el personal (por partes: Vercel limita también las respuestas) --------------------------------------------------
def file_meta(c, user, cid, fid):
    _case_for(c, user, cid)
    row = c.execute("SELECT id,name,size,mime,parts FROM pqrs_uploads WHERE id=? AND case_id=? AND status='usada'", (fid, cid)).fetchone()
    if not row:
        raise PqrsError('Archivo no disponible.', 404)
    return dict(row)


def file_part(c, user, cid, fid, idx):
    meta = file_meta(c, user, cid, fid)
    if not 0 <= idx < meta['parts']:
        raise PqrsError('Parte no válida.', 400)
    part = c.execute('SELECT data FROM pqrs_upload_parts WHERE upload_id=? AND idx=?', (fid, idx)).fetchone()
    if not part:
        raise PqrsError('Archivo no disponible.', 404)
    return {'index': idx, 'data': part['data'], 'mime': meta['mime'], 'name': meta['name'], 'parts': meta['parts']}


# ---- Exportación ---------------------------------------------------------------------------------------------------------------
def export_csv(c, user, params):
    if user['role'] != 'administrador':
        raise PqrsError('Acceso no permitido.', 403)
    where, args = _filters(user, params)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Código', 'Tipo', 'Estado', 'Prioridad', 'Idioma', 'Cliente', 'Correo', 'Teléfono', 'Sede', 'Asunto', 'Orden indicada', 'Orden verificada',
                     'Responsable', 'Recibida', 'Primera respuesta', 'Cerrada'])
    for r in c.execute('SELECT p.*,u.name assigned_name FROM pqrs_cases p LEFT JOIN users u ON u.id=p.assigned_to WHERE ' + where + ' ORDER BY p.id', args):
        cells = [r['code'], CATEGORY_LABELS[r['category']][0], STATUS_LABELS[r['status']][0], PRIORITY_LABELS[r['priority']], r['language'], r['name'], r['email'], r['phone'],
                 r['site'], r['subject'], r['order_code'], 'Sí' if r['order_verified'] else 'No', r['assigned_name'] or '', r['created_at'], r['first_response_at'], r['closed_at']]
        # Una celda que empieza por =, +, - o @ se abriría como fórmula en una hoja de cálculo: se antepone un apóstrofo.
        writer.writerow(["'" + str(x) if str(x)[:1] in ('=', '+', '-', '@') else x for x in cells])
    return '﻿' + out.getvalue()


# ---- Avisos internos (centro de notificaciones) ---------------------------------------------------------------------------------
def notifications(c, user, now):
    items = []
    if user['role'] == 'administrador':
        rows = c.execute("SELECT id,code,category,name,created_at FROM pqrs_cases WHERE status='recibida' ORDER BY id DESC LIMIT 20").fetchall()
        title = 'Nueva PQRS · '
    elif user['role'] == 'tecnico':
        rows = c.execute("SELECT id,code,category,name,updated_at created_at FROM pqrs_cases WHERE assigned_to=? AND status IN ('asignada','en_revision') ORDER BY id DESC LIMIT 20", (user['id'],)).fetchall()
        title = 'PQRS asignada · '
    else:
        return items
    for r in rows:
        items.append({'key': 'pqrs:%d:%s' % (r['id'], 'nueva' if user['role'] == 'administrador' else 'asignada'), 'kind': 'warning' if r['category'] in ('queja', 'reclamo') else 'info',
                      'icon': 'message', 'title': title + r['code'], 'detail': CATEGORY_LABELS[r['category']][0] + ' de ' + r['name'], 'at': r['created_at'],
                      'href': '#pqrs?id=%d' % r['id'], 'action': 'Ver PQRS', 'sound': True, 'group': 'event'})
    return items
