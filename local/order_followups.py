"""Centro de seguimiento técnico y comunicación con el cliente de cada orden.

- Seguimientos con tipo, nota interna (solo el taller), mensaje para el cliente (visible solo si se marca), próxima acción, prioridad,
  presupuesto relacionado y evidencias. Son inmutables: una corrección es otro seguimiento que referencia al anterior. Cada uno deja su
  evento en el historial de la orden (order_history), así el seguimiento del inicio y las órdenes antiguas no cambian.
- Mensajes al cliente con plantillas y datos reales (sin la nota interna). «Preparado» no es un envío: solo el proveedor (WhatsApp Business)
  o el servidor de correo confirman «enviado»; «entregado» y «leído» llegan únicamente por el aviso del proveedor.
- WhatsApp Business (API de Meta) por variables de entorno: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_APP_SECRET y
  WHATSAPP_VERIFY_TOKEN; WHATSAPP_TEMPLATE_NAME (y WHATSAPP_TEMPLATE_LANG, «es» por defecto) para la plantilla aprobada de fuera de las 24 h.
  Sin configurar, solo hay opción manual (abrir WhatsApp), registrada como «preparado».
- La ventana «Comunicación con el cliente» recupera el último seguimiento comunicable (sources/compose); los registros técnicos anteriores
  del historial eran internos y solo se usan si el técnico los elige expresamente."""
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
    'diagnostico': 'Diagnóstico técnico', 'novedad': 'Novedad importante', 'reparacion': 'Reparación en proceso', 'repuesto': 'Repuesto necesario',
    'presupuesto': 'Presupuesto pendiente', 'autorizacion': 'Solicitud de autorización', 'completado': 'Reparación terminada', 'pruebas': 'Pruebas realizadas',
    'listo': 'Equipo listo para retirar', 'recordatorio': 'Recordatorio de retiro',
}
# Plantilla sugerida según el tipo del seguimiento que se comunica.
TEMPLATE_FOR_KIND = {'recepcion': 'novedad', 'diagnostico': 'diagnostico', 'novedad': 'novedad', 'repuesto': 'repuesto', 'presupuesto_enviado': 'presupuesto',
                     'esperando_autorizacion': 'autorizacion', 'presupuesto_aprobado': 'reparacion', 'presupuesto_rechazado': 'novedad', 'reparacion': 'reparacion',
                     'pruebas': 'pruebas', 'finalizado': 'completado', 'listo_entrega': 'listo', 'comunicacion': 'novedad', 'incidencia': 'novedad', 'pago': 'novedad',
                     'entrega': 'novedad'}
INTRO = {
    'diagnostico': 'Le informamos que realizamos el diagnóstico de su equipo {device}, orden de servicio {code}.',
    'novedad': 'Le escribimos para informarle una novedad sobre su equipo {device}, orden de servicio {code}.',
    'reparacion': 'Le informamos que la reparación de su equipo {device}, orden de servicio {code}, se encuentra en proceso.',
    'repuesto': 'Le informamos que la reparación de su equipo {device}, orden de servicio {code}, requiere un repuesto.',
    'presupuesto': 'El presupuesto de su equipo {device}, orden de servicio {code}, está listo para su revisión.',
    'autorizacion': 'Le escribimos respecto a su equipo {device}, orden de servicio {code}.',
    'completado': 'Le informamos que terminamos la reparación de su equipo {device}, orden de servicio {code}.',
    'pruebas': 'Le informamos que realizamos las pruebas de funcionamiento de su equipo {device}, orden de servicio {code}.',
    'listo': 'Su equipo {device}, orden de servicio {code}, está listo para retirar en nuestro local.',
    'recordatorio': 'Le recordamos que su equipo {device}, orden de servicio {code}, está listo y espera su retiro en nuestro local.',
}
CLOSING = {
    'diagnostico': ['Le mantendremos informado sobre el avance.'], 'novedad': ['Le mantendremos informado sobre el avance.'],
    'reparacion': ['Le mantendremos informado sobre el avance.'], 'repuesto': ['Le avisaremos en cuanto el repuesto esté disponible.'],
    'presupuesto': ['Quedamos atentos a su aprobación para continuar.'], 'autorizacion': ['Para continuar necesitamos su autorización.', 'Quedamos atentos a su respuesta.'],
    'completado': ['Le mantendremos informado sobre la entrega.'], 'pruebas': ['Le mantendremos informado sobre el avance.'],
    'listo': ['Al retirarlo, por favor presente su comprobante de recepción.'], 'recordatorio': ['Al retirarlo, por favor presente su comprobante de recepción.'],
}
NEEDS_NEWS = ('diagnostico', 'novedad', 'autorizacion', 'pruebas', 'repuesto')  # sin novedad elegida, el borrador lleva un espacio a completar
PLACEHOLDER = '[Escriba aquí la novedad para el cliente]'
COST_BY_DEFAULT = ('autorizacion', 'presupuesto')
# Comentarios que el propio sistema deja en el historial (correos, enlaces, decisiones de presupuesto): no son novedades técnicas.
SYSTEM_NOTES = ('Comprobante de recepción enviado', 'Aviso de autorización enviado', 'Enlace de autorización enviado', 'Presupuesto ', 'Autorización electrónica del cliente')
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
                    "COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'') technician,"
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
    recommendation = str(data.get('recommendation', '') or '').strip()[:800]
    if not internal and not message and not recommendation:
        raise FollowupError('Escribe la descripción técnica o el mensaje para el cliente.', 400, {'internal_note': 'Obligatorio.'})
    visible = 1 if str(data.get('client_visible', '')) in ('1', 'true') and (message or recommendation) else 0
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
    summary = label + (': ' + internal if internal else (': ' + (message or recommendation)))
    if corrects:
        summary = 'Corrección del seguimiento #%d · %s' % (corrects['id'], summary)
    order_workspace.event(c, oid, user['id'], now, 'follow_up', summary[:2000])
    history_id = c.execute('SELECT MAX(id) FROM order_history WHERE order_id=?', (oid,)).fetchone()[0]
    fid = c.execute('INSERT INTO order_followups(order_id,history_id,kind,internal_note,client_message,recommendation,client_visible,status_code,next_action,next_date,'
                    'priority,quote_id,corrects_id,request_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (oid, history_id, kind, internal, message, recommendation, visible, order['status'], next_action, next_date, priority, quote['id'] if quote else None,
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
    messages = [dict(r, actor=r['actor'] or '', sources=_loads(r['sources']), status_label=message_label(r['channel'], r['status']))
                for r in c.execute("SELECT m.id,m.followup_id,m.channel,m.template,m.recipient,m.subject,m.body,m.status,m.provider_id,m.error,m.attempts,m.sources,"
                                   "m.created_at,m.updated_at,u.name actor FROM order_messages m LEFT JOIN users u ON u.id=m.created_by WHERE m.order_id=? ORDER BY m.id DESC", (oid,))]
    for r in rows:
        r.update(kind_label=KINDS.get(r['kind'], (r['kind'],))[0], group=KINDS.get(r['kind'], ('', 'tecnico'))[1], priority_label=PRIORITIES.get(r['priority'], r['priority']),
                 files=files.get(r['id'], []), messages=[m for m in messages if m['followup_id'] == r['id']])
    return {'followups': rows, 'messages': messages, 'kinds': {k: {'label': v[0], 'group': v[1], 'status': v[2]} for k, v in KINDS.items()}, 'priorities': PRIORITIES,
            'templates': TEMPLATES, 'template_for_kind': TEMPLATE_FOR_KIND, 'sources': sources(c, oid), 'whatsapp': whatsapp_status()}


def _loads(raw):
    try:
        value = json.loads(raw or '[]')
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def message_label(channel, status):
    """Estado legible de una comunicación: una apertura manual de WhatsApp o un texto copiado nunca se presentan como enviados."""
    if status == 'preparado':
        return 'Abierto en WhatsApp (manual, sin confirmación)' if channel == 'whatsapp_manual' else 'Preparado (copiado, no enviado)'
    if status == 'enviado' and channel == 'correo':
        return 'Enviado (aceptado por el servidor de correo)'
    return {'enviado': 'Enviado', 'entregado': 'Entregado', 'leido': 'Leído', 'error': 'Fallido'}.get(status, status)


def sources(c, oid):
    """Lo que puede usarse para redactar un mensaje, del más reciente al más antiguo. Un seguimiento es comunicable si tiene mensaje o
    recomendación para el cliente; su nota interna nunca se ofrece. Los comentarios técnicos anteriores al centro de seguimiento quedaron en el
    historial como registros internos: se listan para que el técnico decida, pero nunca se usan de forma automática."""
    out = []
    superseded = {r['corrects_id']: r['id'] for r in c.execute('SELECT id,corrects_id FROM order_followups WHERE order_id=? AND corrects_id IS NOT NULL ORDER BY id', (oid,))}
    for r in c.execute("SELECT f.id,f.kind,f.client_message,f.recommendation,f.quote_id,f.created_at,COALESCE(u.name,'') actor FROM order_followups f "
                       "LEFT JOIN users u ON u.id=f.created_by WHERE f.order_id=? ORDER BY f.id DESC", (oid,)):
        label, group = KINDS.get(r['kind'], (r['kind'], 'tecnico'))[:2]
        text = ' '.join(x for x in (r['client_message'], r['recommendation']) if x)
        out.append({'type': 'followup', 'id': r['id'], 'at': r['created_at'], 'kind': r['kind'], 'label': label, 'group': group, 'actor': r['actor'],
                    'summary': text[:220] if text else 'Solo nota interna: no se comunica.', 'communicable': bool(text), 'quote_id': r['quote_id'],
                    'superseded_by': superseded.get(r['id']), 'auto': bool(text) and group != 'pago' and r['id'] not in superseded})
    linked = {r[0] for r in c.execute('SELECT history_id FROM order_followups WHERE order_id=? AND history_id IS NOT NULL', (oid,))}
    for r in c.execute("SELECT h.id,h.occurred_at,h.comment,COALESCE(u.name,'') actor FROM order_history h LEFT JOIN users u ON u.id=h.actor_id "
                       "WHERE h.order_id=? AND h.event='follow_up' AND h.actor_id IS NOT NULL AND TRIM(h.comment)!='' ORDER BY h.id DESC", (oid,)):
        if r['id'] in linked or r['comment'].startswith(SYSTEM_NOTES):
            continue
        out.append({'type': 'history', 'id': r['id'], 'at': r['occurred_at'], 'kind': 'historial', 'label': 'Registro técnico anterior (interno)', 'group': 'tecnico',
                    'actor': r['actor'], 'summary': r['comment'][:220], 'text': r['comment'], 'communicable': False, 'quote_id': None, 'superseded_by': None, 'auto': False})
    out.sort(key=_when, reverse=True)
    return out


def _when(s):
    """Orden cronológico real: el historial guarda microsegundos y los seguimientos, segundos (comparar los textos los desordena)."""
    try:
        at = datetime.fromisoformat(s['at']).replace(microsecond=0)
    except ValueError:
        at = datetime.min
    return (at.timestamp() if at.tzinfo else 0, s['type'] == 'followup', s['id'])


def file_for(c, oid, file_id):
    row = c.execute('SELECT name,mime,data FROM order_followup_files WHERE id=? AND order_id=?', (file_id, oid)).fetchone()
    if not row:
        raise FollowupError('Archivo no disponible.', 404)
    return row['name'], row['mime'], base64.b64decode(row['data'])


def public_updates(c, oid, limit=10):
    """Lo único que ve el cliente en el enlace público: los mensajes marcados como visibles (nunca la nota interna)."""
    return [{'label': KINDS.get(r['kind'], (r['kind'],))[0], 'message': '\n'.join(x for x in (r['client_message'], r['recommendation']) if x), 'at': r['created_at']}
            for r in c.execute("SELECT kind,client_message,recommendation,created_at FROM order_followups WHERE order_id=? AND client_visible=1 "
                               "AND (client_message!='' OR recommendation!='') ORDER BY id DESC LIMIT ?", (oid, limit))]


# ---- Mensajes al cliente ---------------------------------------------------------------------------------------------------------------

def _norm(text):
    return re.sub(r'[\W_]+', ' ', text.casefold()).strip()


GREETING = re.compile(r'^\s*(estimad[oa]s?|señor(a|es)?|sr\.|sra\.|hola|buen(os|as) (días|tardes|noches))\b.{0,80}$', re.I)
COURTESY = re.compile(r'^\s*(reciban? un cordial saludo|agradecemos su (confianza|preferencia)|quedamos atentos|saludos|atentamente|cordialmente|'
                      r'gracias por|pc-doctor( s\.a\.)?\.?\s*$|servicio t[ée]cnico especializado|departamento de servicio t[ée]cnico)', re.I)


def _strip_letter(text):
    """Si la novedad se escribió como carta completa, quita su saludo, su despedida y su firma: el mensaje ya los lleva."""
    lines = (text or '').strip().splitlines()
    while lines and (not lines[0].strip() or GREETING.match(lines[0]) or COURTESY.match(lines[0])):
        lines.pop(0)
    while lines and (not lines[-1].strip() or COURTESY.match(lines[-1]) or GREETING.match(lines[-1])):
        lines.pop()
    return '\n'.join(lines)


def _paragraphs(texts, seen):
    """Une las novedades elegidas sin repetir frases: la misma frase en dos seguimientos aparece una sola vez."""
    out = []
    for text in texts:
        kept = []
        for line in re.split(r'\n+', _strip_letter(text)):
            fresh = [p for p in re.split(r'(?<=[.!?])\s+', line.strip()) if _norm(p) and _norm(p) not in seen]
            seen.update(_norm(p) for p in fresh)
            if fresh:
                kept.append(' '.join(fresh))
        if kept:
            paragraph = '\n'.join(kept)
            out.append(paragraph if paragraph[-1] in '.!?:' else paragraph + '.')
    return out


def _cost(c, oid, quote_id=None):
    """Valor del presupuesto que se podría comunicar. Por defecto solo el de un presupuesto enviado que espera respuesta (en las plantillas de
    autorización y presupuesto); en borrador aún puede cambiar y uno ya aprobado no se vuelve a pedir: se incluyen solo si se marca. Cancelado
    o rechazado, nunca."""
    try:
        import quotes
        versions = quotes.for_order(c, oid)['versions']
    except Exception:
        return None
    q = next((v for v in versions if v['id'] == quote_id), None) if quote_id else next((v for v in versions if v['status'] != 'cancelado'), None)
    if not q or q['status'] in ('cancelado', 'rechazado'):
        return None
    approved = q['status'] in ('aprobado', 'parcial')
    cents = q['approved_cents'] if approved else q['quoted_cents']
    if not cents:
        return None
    return {'quote_id': q['id'], 'code': q['code'], 'status': q['status'], 'status_label': q['status_label'], 'cents': cents, 'amount': quotes_usd(cents),
            'label': 'Valor autorizado' if approved else 'Costo propuesto', 'draft': q['status'] == 'borrador', 'approved': approved,
            'default': q['status'] in ('enviado', 'modificacion')}  # por defecto solo un presupuesto enviado y pendiente de respuesta


def _first_name(client):
    client = (client or '').strip()
    if not client:
        return 'cliente'
    if re.search(r'\b(S\.?A\.?S?|C[ÍI]A\.?|LTDA\.?|EP|CORP\.?)$', client, re.I):  # empresa: su razón social completa
        return client
    return client.split()[0].title()


def compose(c, oid, template, followup_ids=None, history_ids=(), cost=None, order_recommendations=False, tracking_url='', company=None):
    """Borrador con datos reales: cliente, orden, equipo, novedades para el cliente de los seguimientos elegidos (sin repetir frases), sus
    recomendaciones, el costo solo si corresponde y el enlace de seguimiento. Nunca incluye la nota interna de un seguimiento.

    followup_ids=None usa el último seguimiento comunicable; una lista vacía prepara un mensaje manual. history_ids son registros técnicos
    anteriores que el técnico eligió expresamente. cost: None aplica la regla de la plantilla; True o False lo deciden."""
    if template not in TEMPLATES:
        raise FollowupError('Plantilla no válida.', 400, {'template': 'No válida.'})
    o = _order(c, oid)
    available = {(s['type'], s['id']): s for s in sources(c, oid)}
    if followup_ids is None:
        auto = next((s for s in available.values() if s['type'] == 'followup' and s['auto']), None)
        followup_ids = [auto['id']] if auto else []
    chosen = []
    for kind, ids in (('followup', followup_ids), ('history', history_ids)):
        for i in ids:
            s = available.get((kind, int(i)))
            if not s:
                raise FollowupError('Seguimiento no disponible.', 404)
            if kind == 'followup' and not s['communicable']:
                raise FollowupError('Ese seguimiento solo tiene nota interna: no se comunica al cliente.', 400)
            chosen.append(s)
    chosen.sort(key=_when)  # el mensaje se lee en orden cronológico
    rows = {r['id']: r for r in c.execute('SELECT id,client_message,recommendation,quote_id FROM order_followups WHERE order_id=?', (oid,))}
    news, advice = [], []
    for s in chosen:
        if s['type'] == 'followup':
            news.append(rows[s['id']]['client_message'])
            advice.append(rows[s['id']]['recommendation'])
        else:
            news.append(s['text'])
    if order_recommendations and (o['recommendations'] or '').strip():
        advice.append(o['recommendations'])
    seen = set()
    news, advice = _paragraphs(news, seen), _paragraphs(advice, seen)
    quote_id = next((rows[s['id']]['quote_id'] for s in reversed(chosen) if s['type'] == 'followup' and rows[s['id']]['quote_id']), None)
    price = _cost(c, oid, quote_id)
    include = bool(price) and (price['default'] and template in COST_BY_DEFAULT if cost is None else bool(cost))
    company = company or __import__('corporate').settings()
    phone = company.get('whatsapp', '')
    device = ' '.join(x for x in (o['brand'], o['model']) if x)
    intro = INTRO[template].format(device=device, code=o['code']) if device else INTRO[template].replace(' {device}', '').format(code=o['code'])
    lines = ['Estimado/a %s:' % _first_name(o['client']), '', 'Reciba un cordial saludo de PC-DOCTOR.', '', intro]
    warnings = []
    for p in news + advice:
        lines += ['', p]
    if not news and template in NEEDS_NEWS:
        lines += ['', PLACEHOLDER]
        warnings.append('Completa la novedad para el cliente antes de enviar.')
    if include:
        lines += ['', '%s: %s.' % (price['label'], price['amount'])]
        if price['draft']:
            warnings.append('El presupuesto %s está en borrador: el valor aún puede cambiar.' % price['code'])
    closing = CLOSING[template]
    if include and template in ('diagnostico', 'novedad', 'repuesto', 'pruebas'):
        closing = ['Quedamos atentos a su respuesta.']
    for line in closing:
        lines += ['', line]
    if tracking_url:
        lines += ['', 'Puede revisar el estado de su orden aquí: %s' % tracking_url]
    lines += ['', 'PC-DOCTOR', company.get('specialty', 'Servicio Técnico Especializado')] + (['Tel.: ' + phone] if phone else [])
    if any(s['type'] == 'history' for s in chosen):
        warnings.append('Incluye registros técnicos anteriores, que eran internos: revisa que todo se pueda comunicar.')
    return {'body': '\n'.join(lines), 'subject': 'PC-DOCTOR · Orden %s · %s' % (o['code'], TEMPLATES[template]),
            'sources': [{'type': s['type'], 'id': s['id']} for s in chosen], 'cost': price, 'cost_included': include, 'warnings': warnings}


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
    body = message_body(data)
    used = message_sources(c, oid, data)
    fid = int(data['followup_id']) if str(data.get('followup_id', '') or '').isdigit() else next((s['id'] for s in reversed(used) if s['type'] == 'followup'), None)
    if fid and not c.execute('SELECT 1 FROM order_followups WHERE id=? AND order_id=?', (fid, oid)).fetchone():
        raise FollowupError('Seguimiento no disponible.', 404)
    subject = _text(data.get('subject'), 150) if channel == 'correo' else ''
    mid = c.execute('INSERT INTO order_messages(order_id,followup_id,channel,template,recipient,subject,body,status,provider_id,error,attempts,sources,request_key,created_by,'
                    'created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (oid, fid, channel, _text(data.get('template'), 40), recipient[:200], subject, body, status, provider_id, error[:400],
                     1 if status in ('enviado', 'error') else 0, json.dumps(used), key or None, user['id'] if user else None, stamp(now), stamp(now))).lastrowid
    return dict(c.execute('SELECT * FROM order_messages WHERE id=?', (mid,)).fetchone()), False


def retry(c, message_id, status, provider_id, error, now):
    """Reintento controlado de un envío fallido: el mismo registro (mismo texto), un intento más y el resultado real del nuevo intento."""
    c.execute('UPDATE order_messages SET status=?,provider_id=?,error=?,attempts=attempts+1,updated_at=? WHERE id=?', (status, provider_id, error[:400], stamp(now), message_id))
    return dict(c.execute('SELECT * FROM order_messages WHERE id=?', (message_id,)).fetchone())


def message_body(data):
    """Texto que se registra o se envía: obligatorio y sin espacios por completar del borrador."""
    body = str(data.get('body', '') or '').strip()[:4000]
    if len(body) < 10:
        raise FollowupError('Escribe el mensaje para el cliente.', 400, {'body': 'Obligatorio.'})
    if PLACEHOLDER in body or '[Escriba' in body:
        raise FollowupError('El mensaje tiene espacios por completar: reemplaza el texto entre corchetes.', 400, {'body': 'Por completar.'})
    return body


def message_sources(c, oid, data):
    """Seguimientos usados para redactar el mensaje (JSON [{type, id}]); cada uno debe pertenecer a la orden."""
    raw = data.get('sources', '')
    items = raw if isinstance(raw, list) else _loads(raw)
    out = []
    for item in items[:20]:
        kind, ident = (item.get('type'), item.get('id')) if isinstance(item, dict) else (None, None)
        if kind not in ('followup', 'history') or not str(ident).isdigit():
            raise FollowupError('Seguimientos no válidos.', 400)
        table = 'order_followups' if kind == 'followup' else 'order_history'
        if not c.execute('SELECT 1 FROM %s WHERE id=? AND order_id=?' % table, (int(ident), oid)).fetchone():
            raise FollowupError('Seguimiento no disponible.', 404)
        out.append({'type': kind, 'id': int(ident)})
    return out


def whatsapp_config(env=None):
    env = os.environ if env is None else env
    return {'token': env.get('WHATSAPP_TOKEN', '').strip(), 'phone_id': env.get('WHATSAPP_PHONE_NUMBER_ID', '').strip(),
            'secret': env.get('WHATSAPP_APP_SECRET', '').strip(), 'verify': env.get('WHATSAPP_VERIFY_TOKEN', '').strip(), 'version': env.get('WHATSAPP_API_VERSION', 'v21.0').strip(),
            'template': env.get('WHATSAPP_TEMPLATE_NAME', '').strip(), 'template_lang': env.get('WHATSAPP_TEMPLATE_LANG', 'es').strip() or 'es'}


def whatsapp_status(env=None):
    cfg = whatsapp_config(env)
    return {'configured': bool(cfg['token'] and cfg['phone_id']), 'webhook': bool(cfg['secret'] and cfg['verify']), 'template': cfg['template']}


def ecuador_number(phone):
    """Celular para WhatsApp en formato internacional (las mismas reglas que la pantalla): 09XXXXXXXX, 9XXXXXXXX o 5939XXXXXXXX; los fijos no
    sirven. Un número con prefijo internacional (+ o 00) se acepta tal cual."""
    raw = str(phone or '').strip()
    digits = re.sub(r'\D', '', raw)
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('5930'):
        digits = '593' + digits[4:]
    if len(digits) == 10 and digits.startswith('0'):
        digits = '593' + digits[1:]
    elif len(digits) == 9 and digits.startswith('9'):
        digits = '593' + digits
    if digits.startswith('593'):
        return digits if re.fullmatch(r'5939\d{8}', digits) else ''
    return digits if re.match(r'\s*(\+|00)', raw) and 8 <= len(digits) <= 15 else ''


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
    if data.get('mode') == 'template':
        # Fuera de la ventana de 24 h, Meta solo acepta una plantilla aprobada. Se envía con {{1}} = nombre del cliente y {{2}} = número de orden;
        # se registra la plantilla con sus datos, no un texto distinto al que recibió el cliente.
        if not cfg['template']:
            raise FollowupError('No hay una plantilla aprobada de WhatsApp configurada.', 409)
        params = [_first_name(o['client']), o['code']]
        payload = {'messaging_product': 'whatsapp', 'to': number, 'type': 'template', 'template': {'name': cfg['template'], 'language': {'code': cfg['template_lang']},
                   'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': p} for p in params]}]}}
        body = 'Plantilla aprobada de WhatsApp «%s» (%s) con los datos: %s.' % (cfg['template'], cfg['template_lang'], ', '.join(params))
    else:
        body = existing['body'] if existing else message_body(data)  # un reintento envía el texto registrado, no otro
        payload = {'messaging_product': 'whatsapp', 'to': number, 'type': 'text', 'text': {'preview_url': True, 'body': body}}
    message_sources(c, oid, data)
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
    if existing:
        row = retry(c, existing['id'], status, provider, error, now)
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
                # Un fallo solo cuenta mientras el mensaje figura como enviado: nunca deshace un «entregado» o «leído» ya confirmado.
                if (new == 'error' and row['status'] == 'enviado') or order.get(new, 0) > order.get(row['status'], 0):
                    error = ''
                    if new == 'error':
                        error = str(((st.get('errors') or [{}])[0]).get('title', 'Error del proveedor'))[:400]
                    c.execute('UPDATE order_messages SET status=?,error=?,updated_at=? WHERE id=?', (new, error, stamp(now), row['id']))
                    changed += 1
    return changed
