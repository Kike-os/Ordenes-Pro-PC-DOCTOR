"""Centro de seguimiento técnico y comunicación con el cliente de cada orden.

- Seguimientos con tipo, nota interna (solo el taller), mensaje para el cliente (visible solo si se marca), próxima acción, prioridad,
  presupuesto relacionado y evidencias. Son inmutables: una corrección es otro seguimiento que referencia al anterior. Cada uno deja su
  evento en el historial de la orden (order_history), así el seguimiento del inicio y las órdenes antiguas no cambian.
- Mensajes al cliente con plantillas y datos reales (sin la nota interna). «Preparado» no es un envío: solo el proveedor (WhatsApp Business)
  o el servidor de correo confirman «enviado»; «entregado» y «leído» llegan únicamente por el aviso del proveedor.
- WhatsApp Business (API de Meta) por variables de entorno: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_APP_SECRET y
  WHATSAPP_VERIFY_TOKEN. Sin configurar, solo hay opción manual (abrir WhatsApp), registrada como «preparado»."""
import base64
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime

import order_workspace

# Tipos de seguimiento: etiqueta, grupo del historial y estado de la orden con el que se relaciona (solo como referencia; no lo cambia).
KINDS = {
    'recepcion': ('Recepción y evaluación', 'tecnico', 'pendiente'), 'diagnostico': ('Diagnóstico técnico', 'tecnico', 'reparacion'),
    'novedad': ('Novedad de reparación', 'tecnico', 'reparacion'), 'repuesto': ('Esperando repuesto', 'tecnico', 'reparacion'),
    'presupuesto_enviado': ('Presupuesto enviado', 'autorizacion', 'presupuesto'), 'esperando_autorizacion': ('Esperando autorización', 'autorizacion', 'esperando_cliente'),
    'presupuesto_aprobado': ('Presupuesto aprobado', 'autorizacion', 'reparacion'), 'presupuesto_rechazado': ('Presupuesto rechazado', 'autorizacion', 'esperando_cliente'),
    'reparacion': ('Reparación en proceso', 'tecnico', 'reparacion'), 'pruebas': ('Pruebas de funcionamiento', 'tecnico', 'reparacion'),
    'finalizado': ('Servicio finalizado', 'tecnico', 'listo'), 'listo_entrega': ('Listo para entregar', 'tecnico', 'listo'),
    'comunicacion': ('Comunicación con cliente', 'comunicacion', ''), 'incidencia': ('Incidencia o garantía', 'incidencia', ''),
    'pago': ('Pago registrado', 'pago', ''), 'entrega': ('Entrega del equipo', 'tecnico', 'entregado'),
}
PRIORITIES = {'baja': 'Baja', 'normal': 'Normal', 'alta': 'Alta', 'urgente': 'Urgente'}
TEMPLATES = {
    'diagnostico': 'Diagnóstico realizado', 'reparacion': 'Reparación en proceso', 'autorizacion': 'Solicitud de autorización', 'presupuesto': 'Presupuesto disponible',
    'repuesto': 'Repuesto pendiente', 'completado': 'Servicio completado', 'listo': 'Equipo listo para retirar', 'recordatorio': 'Recordatorio de retiro',
    'novedad': 'Novedad importante',
}
MAX_FILES = 3
MAX_FILE_BYTES = 900_000
MIMES = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG\r\n\x1a\n': 'image/png', b'%PDF-': 'application/pdf'}
TRANSPORT = None  # en pruebas: función (url, cabeceras, cuerpo) -> (estado HTTP, dict) que sustituye a la API de WhatsApp


class FollowupError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def _text(value, limit):
    return re.sub(r'[ \t]+', ' ', str(value or '')).strip()[:limit]


def _mime(raw):
    for magic, mime in MIMES.items():
        if raw.startswith(magic):
            return mime
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'image/webp'
    return ''


def _order(c, oid):
    row = c.execute("SELECT o.id,o.code,o.status,s.label status_label,o.findings,o.recommendations,c.name client,c.email,c.phone,d.brand,d.model,"
                    "COALESCE(NULLIF(d.kind,''),d.category) kind FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id "
                    "JOIN clients c ON c.id=d.client_id WHERE o.id=?", (oid,)).fetchone()
    if not row:
        raise FollowupError('Orden no disponible.', 404)
    return row


# ---- Seguimientos --------------------------------------------------------------------------------------------------------------------

def create(c, oid, data, user, now):
    """Registra un seguimiento (y su evento en el historial). Idempotente con request_key: un doble clic no lo duplica."""
    if user['role'] not in ('administrador', 'tecnico'):
        raise FollowupError('Acceso no permitido.', 403)
    order = _order(c, oid)
    key = _text(data.get('request_key'), 64)
    if key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise FollowupError('Solicitud no válida. Recarga la página.')
        same = c.execute('SELECT id FROM order_followups WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id']
    kind = str(data.get('kind', ''))
    if kind not in KINDS:
        raise FollowupError('Elige el tipo de seguimiento.', 400, {'kind': 'Tipo no válido.'})
    internal = str(data.get('internal_note', '') or '').strip()[:2000]
    message = str(data.get('client_message', '') or '').strip()[:1500]
    if not internal and not message:
        raise FollowupError('Escribe la descripción técnica o el mensaje para el cliente.', 400, {'internal_note': 'Obligatorio.'})
    visible = 1 if str(data.get('client_visible', '')) in ('1', 'true') and message else 0
    next_action = _text(data.get('next_action'), 200)
    next_date = str(data.get('next_date', '') or '').strip()
    if next_date:
        try:
            if date.fromisoformat(next_date) < now.date():
                raise FollowupError('La fecha de seguimiento no puede ser anterior a hoy.', 400, {'next_date': 'Fecha pasada.'})
        except ValueError:
            raise FollowupError('Fecha de seguimiento no válida.', 400, {'next_date': 'Fecha no válida.'})
    priority = str(data.get('priority', 'normal') or 'normal')
    if priority not in PRIORITIES:
        raise FollowupError('Prioridad no válida.', 400, {'priority': 'Prioridad no válida.'})
    quote = None
    if str(data.get('quote_id', '') or '').isdigit():
        quote = c.execute('SELECT id FROM quotes WHERE id=? AND order_id=?', (int(data['quote_id']), oid)).fetchone()
        if not quote:
            raise FollowupError('El presupuesto no pertenece a esta orden.', 400, {'quote_id': 'No válido.'})
    corrects = None
    if str(data.get('corrects_id', '') or '').isdigit():
        corrects = c.execute('SELECT id FROM order_followups WHERE id=? AND order_id=?', (int(data['corrects_id']), oid)).fetchone()
        if not corrects:
            raise FollowupError('El seguimiento a corregir no pertenece a esta orden.', 400)
    files = _files(data.get('files', '[]'))
    label = KINDS[kind][0]
    summary = label + (': ' + internal if internal else (': ' + message if message else ''))
    if corrects:
        summary = 'Corrección del seguimiento #%d · %s' % (corrects['id'], summary)
    order_workspace.event(c, oid, user['id'], now, 'follow_up', summary[:2000])
    history_id = c.execute('SELECT MAX(id) FROM order_history WHERE order_id=?', (oid,)).fetchone()[0]
    fid = c.execute('INSERT INTO order_followups(order_id,history_id,kind,internal_note,client_message,client_visible,status_code,next_action,next_date,priority,quote_id,'
                    'corrects_id,request_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (oid, history_id, kind, internal, message, visible, order['status'], next_action, next_date, priority, quote['id'] if quote else None,
                     corrects['id'] if corrects else None, key or None, user['id'], stamp(now))).lastrowid
    for f in files:
        c.execute('INSERT INTO order_followup_files(followup_id,order_id,name,mime,size,sha256,visible_to_client,data,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (fid, oid, f['name'], f['mime'], f['size'], f['sha256'], f['visible'], f['data'], user['id'], stamp(now)))
    c.execute('UPDATE orders SET updated_at=?,revision=revision+1 WHERE id=?', (now.isoformat(timespec='microseconds'), oid))
    return fid


def _files(raw):
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        raise FollowupError('Adjuntos no válidos.', 400, {'files': 'No válidos.'})
    if not isinstance(items, list) or len(items) > MAX_FILES:
        raise FollowupError('Adjunta como máximo %d archivos por seguimiento.' % MAX_FILES, 400, {'files': 'Demasiados archivos.'})
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise FollowupError('Adjuntos no válidos.', 400, {'files': 'No válidos.'})
        try:
            raw_bytes = base64.b64decode(str(item.get('data', '')).split(',')[-1], validate=True)
        except (ValueError, TypeError):
            raise FollowupError('Un adjunto está dañado.', 400, {'files': 'Archivo dañado.'})
        mime = _mime(raw_bytes)
        if not mime:
            raise FollowupError('Solo se admiten fotografías (JPG, PNG, WEBP) e informes PDF.', 400, {'files': 'Tipo no admitido.'})
        if len(raw_bytes) > MAX_FILE_BYTES:
            raise FollowupError('Cada archivo puede pesar como máximo 900 KB.', 400, {'files': 'Archivo demasiado grande.'})
        name = re.sub(r'[^\w .()-]', '', str(item.get('name', '') or 'evidencia'))[:80] or 'evidencia'
        out.append({'name': name, 'mime': mime, 'size': len(raw_bytes), 'sha256': hashlib.sha256(raw_bytes).hexdigest(),
                    'visible': 1 if str(item.get('visible', '')) in ('1', 'true') else 0, 'data': base64.b64encode(raw_bytes).decode()})
    return out


def listing(c, oid):
    """Seguimientos de la orden con sus evidencias (sin contenido) y sus mensajes."""
    rows = [dict(r) for r in c.execute("SELECT f.*,COALESCE(u.name,'') actor,q.code quote_code FROM order_followups f LEFT JOIN users u ON u.id=f.created_by "
                                       "LEFT JOIN quotes q ON q.id=f.quote_id WHERE f.order_id=? ORDER BY f.id DESC", (oid,))]
    files = {}
    for r in c.execute('SELECT id,followup_id,name,mime,size,visible_to_client,created_at FROM order_followup_files WHERE order_id=? ORDER BY id', (oid,)):
        files.setdefault(r['followup_id'], []).append(dict(r))
    messages = [dict(r, actor=r['actor'] or '') for r in c.execute("SELECT m.id,m.followup_id,m.channel,m.template,m.recipient,m.body,m.status,m.provider_id,m.error,m.attempts,m.created_at,"
                                                                    "m.updated_at,u.name actor FROM order_messages m LEFT JOIN users u ON u.id=m.created_by WHERE m.order_id=? ORDER BY m.id DESC", (oid,))]
    for r in rows:
        r.update(kind_label=KINDS.get(r['kind'], (r['kind'],))[0], group=KINDS.get(r['kind'], ('', 'tecnico'))[1], priority_label=PRIORITIES.get(r['priority'], r['priority']),
                 files=files.get(r['id'], []), messages=[m for m in messages if m['followup_id'] == r['id']])
    return {'followups': rows, 'messages': messages, 'kinds': {k: {'label': v[0], 'group': v[1], 'status': v[2]} for k, v in KINDS.items()}, 'priorities': PRIORITIES,
            'templates': TEMPLATES, 'whatsapp': whatsapp_status()}


def file_for(c, oid, file_id):
    row = c.execute('SELECT name,mime,data FROM order_followup_files WHERE id=? AND order_id=?', (file_id, oid)).fetchone()
    if not row:
        raise FollowupError('Archivo no disponible.', 404)
    return row['name'], row['mime'], base64.b64decode(row['data'])


def public_updates(c, oid, limit=10):
    """Lo único que ve el cliente en el enlace público: los mensajes marcados como visibles (nunca la nota interna)."""
    return [{'label': KINDS.get(r['kind'], (r['kind'],))[0], 'message': r['client_message'], 'at': r['created_at']}
            for r in c.execute("SELECT kind,client_message,created_at FROM order_followups WHERE order_id=? AND client_visible=1 AND client_message!='' ORDER BY id DESC LIMIT ?", (oid, limit))]


# ---- Mensajes al cliente ---------------------------------------------------------------------------------------------------------------

def compose(c, oid, template, followup_id=None, tracking_url='', company=None):
    """Mensaje con datos reales (cliente, orden, equipo, novedad autorizada, presupuesto, enlace de seguimiento). Nunca incluye la nota interna."""
    if template not in TEMPLATES:
        raise FollowupError('Plantilla no válida.', 400, {'template': 'No válida.'})
    o = _order(c, oid)
    f = None
    if followup_id:
        f = c.execute('SELECT * FROM order_followups WHERE id=? AND order_id=?', (followup_id, oid)).fetchone()
        if not f:
            raise FollowupError('Seguimiento no disponible.', 404)
    company = company or __import__('corporate').settings()
    phone = company.get('whatsapp', '')
    device = ' '.join(x for x in (o['brand'], o['model']) if x) or 'su equipo'
    news = (f['client_message'] if f and f['client_message'] else '').strip()
    quote = None
    qid = f['quote_id'] if f and f['quote_id'] else None
    try:
        import quotes
        data = quotes.for_order(c, oid)
        versions = data['versions']
        quote = next((v for v in versions if v['id'] == qid), None) if qid else (versions[0] if versions else None)
    except Exception:
        quote = None
    amount = quotes_usd(quote['quoted_cents']) if quote and quote.get('quoted_cents') else ''
    name = (o['client'] or '').split()[0].title() if o['client'] else 'cliente'
    lines = ['Estimado/a %s:' % name, '', 'Reciba un cordial saludo de PC-DOCTOR.', '', 'Orden de servicio: %s · %s' % (o['code'], device), '']
    body = {
        'diagnostico': 'Le informamos que ya realizamos el diagnóstico de su equipo.',
        'reparacion': 'Le informamos que la reparación de su equipo se encuentra en proceso.',
        'autorizacion': 'Para continuar con el trabajo, necesitamos su autorización.',
        'presupuesto': 'El presupuesto de su servicio ya está disponible' + (' por un valor de %s.' % amount if amount else '.'),
        'repuesto': 'Estamos a la espera del repuesto necesario para continuar con la reparación. Le avisaremos en cuanto llegue.',
        'completado': 'Le informamos que el servicio de su equipo fue completado satisfactoriamente.',
        'listo': 'Su equipo está listo para ser retirado en nuestro local.',
        'recordatorio': 'Le recordamos que su equipo está listo y esperando su retiro.',
        'novedad': 'Tenemos una novedad importante sobre su equipo.',
    }[template]
    if template == 'autorizacion':
        # Como el modelo del taller: primero la novedad, luego el costo y al final la solicitud de autorización.
        lines += ([news, ''] if news else []) + (['Costo propuesto: %s.' % amount, ''] if amount else []) + [body, '', 'Quedamos atentos a su respuesta.']
    else:
        lines.append(body)
        if news:
            lines += ['', news]
    if tracking_url:
        lines += ['', 'Puede revisar el estado de su orden aquí: %s' % tracking_url]
    lines += ['', 'PC-DOCTOR', company.get('specialty', 'Servicio Técnico Especializado')] + (['Tel.: ' + phone] if phone else [])
    return '\n'.join(lines)


def quotes_usd(cents):
    import quotes
    return quotes.usd(cents)


def record(c, oid, data, user, now, status='preparado', provider_id='', error='', recipient=''):
    """Registra un mensaje con su estado real. Idempotente con request_key (un reintento o un doble clic no lo duplica)."""
    key = _text(data.get('request_key'), 64)
    if key:
        same = c.execute('SELECT * FROM order_messages WHERE request_key=?', (key,)).fetchone()
        if same:
            return dict(same), True
    channel = str(data.get('channel', ''))
    if channel not in ('whatsapp', 'whatsapp_manual', 'correo', 'copia'):
        raise FollowupError('Canal no válido.', 400)
    body = str(data.get('body', '') or '').strip()[:4000]
    if len(body) < 10:
        raise FollowupError('Escribe el mensaje para el cliente.', 400, {'body': 'Obligatorio.'})
    fid = int(data['followup_id']) if str(data.get('followup_id', '') or '').isdigit() else None
    if fid and not c.execute('SELECT 1 FROM order_followups WHERE id=? AND order_id=?', (fid, oid)).fetchone():
        raise FollowupError('Seguimiento no disponible.', 404)
    mid = c.execute('INSERT INTO order_messages(order_id,followup_id,channel,template,recipient,body,status,provider_id,error,attempts,request_key,created_by,created_at,updated_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (oid, fid, channel, _text(data.get('template'), 40), recipient[:200], body, status, provider_id, error[:400],
                                                             1 if status in ('enviado', 'error') else 0, key or None, user['id'] if user else None, stamp(now), stamp(now))).lastrowid
    return dict(c.execute('SELECT * FROM order_messages WHERE id=?', (mid,)).fetchone()), False


def whatsapp_config(env=None):
    env = os.environ if env is None else env
    return {'token': env.get('WHATSAPP_TOKEN', '').strip(), 'phone_id': env.get('WHATSAPP_PHONE_NUMBER_ID', '').strip(),
            'secret': env.get('WHATSAPP_APP_SECRET', '').strip(), 'verify': env.get('WHATSAPP_VERIFY_TOKEN', '').strip(), 'version': env.get('WHATSAPP_API_VERSION', 'v21.0').strip()}


def whatsapp_status(env=None):
    cfg = whatsapp_config(env)
    return {'configured': bool(cfg['token'] and cfg['phone_id']), 'webhook': bool(cfg['secret'] and cfg['verify'])}


def ecuador_number(phone):
    digits = re.sub(r'\D', '', phone or '')
    if digits.startswith('593') and len(digits) in (11, 12):
        return digits
    if digits.startswith('0') and len(digits) == 10:
        return '593' + digits[1:]
    return ''


def send_whatsapp(c, oid, data, user, now, env=None):
    """Envío por la API oficial de WhatsApp Business. Solo queda «enviado» con el identificador que devuelve Meta; un error se registra y se
    puede reintentar con la misma clave (no duplica). Fuera de las 24 h de conversación, Meta exige una plantilla aprobada."""
    cfg = whatsapp_config(env)
    if not (cfg['token'] and cfg['phone_id']):
        raise FollowupError('WhatsApp Business no está configurado: usa la opción manual (no se registra como enviado).', 409)
    o = _order(c, oid)
    number = ecuador_number(str(data.get('recipient', '') or o['phone']))
    if not number:
        raise FollowupError('El cliente no tiene un número de celular válido.', 400, {'recipient': 'Número no válido.'})
    key = _text(data.get('request_key'), 64)
    existing = c.execute('SELECT * FROM order_messages WHERE request_key=?', (key,)).fetchone() if key else None
    if existing and existing['status'] != 'error':
        return dict(existing), True
    body = str(data.get('body', '') or '').strip()[:4000]
    payload = {'messaging_product': 'whatsapp', 'to': number, 'type': 'text', 'text': {'preview_url': True, 'body': body}}
    url = 'https://graph.facebook.com/%s/%s/messages' % (cfg['version'], cfg['phone_id'])
    headers = {'Authorization': 'Bearer ' + cfg['token'], 'Content-Type': 'application/json'}
    try:
        if TRANSPORT is not None:
            code, answer = TRANSPORT(url, headers, payload)
        else:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    code, answer = resp.status, json.loads(resp.read() or b'{}')
            except urllib.error.HTTPError as err:
                code, answer = err.code, json.loads(err.read() or b'{}')
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        code, answer = 0, {'error': {'message': 'Sin conexión con WhatsApp (%s).' % type(err).__name__}}
    provider = ''
    if code == 200 and isinstance(answer, dict) and answer.get('messages'):
        provider = str(answer['messages'][0].get('id', ''))
    if provider:
        status, error = 'enviado', ''
    else:
        status, error = 'error', str((answer or {}).get('error', {}).get('message', 'WhatsApp no aceptó el mensaje.'))[:400]
    if existing:  # reintento controlado de un envío fallido: mismo registro, un intento más
        c.execute('UPDATE order_messages SET status=?,provider_id=?,error=?,attempts=attempts+1,updated_at=? WHERE id=?', (status, provider, error, stamp(now), existing['id']))
        row = dict(c.execute('SELECT * FROM order_messages WHERE id=?', (existing['id'],)).fetchone())
    else:
        row, _ = record(c, oid, dict(data, channel='whatsapp', body=body), user, now, status, provider, error, number)
    return row, False


def webhook_verify(params, env=None):
    cfg = whatsapp_config(env)
    if cfg['verify'] and params.get('hub.mode') == 'subscribe' and hmac.compare_digest(params.get('hub.verify_token', ''), cfg['verify']):
        return params.get('hub.challenge', '')
    return None


def webhook_status(c, raw, signature, now, env=None):
    """Avisos de Meta: solo con firma válida (X-Hub-Signature-256) se actualiza el estado a entregado, leído o error. Nunca retrocede."""
    cfg = whatsapp_config(env)
    expected = 'sha256=' + hmac.new(cfg['secret'].encode(), raw, hashlib.sha256).hexdigest() if cfg['secret'] else ''
    if not expected or not hmac.compare_digest(expected, signature or ''):
        return 0
    try:
        payload = json.loads(raw.decode('utf-8'))
    except ValueError:
        return 0
    order = {'enviado': 1, 'entregado': 2, 'leido': 3}
    names = {'sent': 'enviado', 'delivered': 'entregado', 'read': 'leido', 'failed': 'error'}
    changed = 0
    for entry in payload.get('entry', []) or []:
        for change in entry.get('changes', []) or []:
            for st in (change.get('value', {}) or {}).get('statuses', []) or []:
                new = names.get(st.get('status', ''))
                row = c.execute('SELECT id,status FROM order_messages WHERE provider_id=?', (str(st.get('id', '')),)).fetchone() if new else None
                if not row:
                    continue
                if new == 'error' or order.get(new, 0) > order.get(row['status'], 0):
                    error = ''
                    if new == 'error':
                        error = str(((st.get('errors') or [{}])[0]).get('title', 'Error del proveedor'))[:400]
                    c.execute('UPDATE order_messages SET status=?,error=?,updated_at=? WHERE id=?', (new, error, stamp(now), row['id']))
                    changed += 1
    return changed
