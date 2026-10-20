"""Seguimiento de entrega de correos: un registro por destinatario y su historial técnico de eventos reales.

Proveedor actual: buzón cPanel (Exim) por SMTP e IMAP. No ofrece API ni webhooks y no anuncia la extensión DSN, así que:
- «Enviado» significa que el servidor SMTP aceptó el mensaje para ese destinatario (no que llegara a su buzón).
- «Rebotado» y «Entrega demorada» llegan como informes de entrega (RFC 3464) al buzón del sistema y se leen por IMAP.
- «Entregado» solo se registra con un informe real de entrega (acción delivered/relayed), que este servidor hoy no emite.
- «Abierto» no se registra: no se insertan píxeles de seguimiento.
Ningún estado se deduce ni se simula. Los eventos duplicados se ignoran por su huella y los que llegan fuera de orden
quedan en el historial sin retroceder el estado actual.
"""
import json
import re
import sqlite3
from datetime import timedelta

import mail_pro

LABELS = {'cola': 'En cola', 'enviando': 'Enviando', 'enviado': 'Enviado', 'entregado': 'Entregado al servidor', 'demorado': 'Demorado', 'rebotado': 'Rebotado',
          'fallido': 'Fallido', 'abierto': 'Abierto', 'desconocido': 'Incidencia'}
# Qué significa cada estado para quien lo lee. «Enviado» NO es entrega final: solo que el servidor SMTP del remitente lo aceptó.
MEANING = {'cola': 'En la cola de salida, todavía sin conectar con el servidor SMTP.', 'enviando': 'Conectando o transmitiendo al servidor SMTP.',
           'enviado': 'Aceptado por el servidor SMTP del remitente. La entrega final al destinatario no está confirmada (el servidor no emite confirmaciones).',
           'entregado': 'Un informe real del servidor de destino confirmó la entrega.', 'demorado': 'El servidor informó una demora; seguirá intentando entregarlo.',
           'rebotado': 'El servidor de destino devolvió el mensaje.', 'fallido': 'El envío no se completó: el servidor SMTP no aceptó el mensaje.',
           'abierto': 'Abierto por el destinatario.', 'desconocido': 'No consta la respuesta del servidor SMTP: revisa la causa indicada.'}
# Orden de avance: un evento de menor rango que llega tarde no hace retroceder el estado.
RANK = {'cola': 0, 'enviando': 1, 'desconocido': 1, 'enviado': 2, 'demorado': 3, 'abierto': 3, 'entregado': 4, 'rebotado': 4, 'fallido': 4}
FINAL = ('entregado', 'rebotado', 'fallido')
FILTERS = {'enviados': ('enviado',), 'entregados': ('entregado',), 'pendientes': ('cola', 'enviando'), 'demorados': ('demorado',), 'rebotados': ('rebotado',), 'fallidos': ('fallido',)}
INCIDENTS = ('demorado', 'rebotado', 'fallido', 'desconocido')
STAGE_EVENTS = {'conexion': ('conectando', 'Conectando SMTP'), 'autenticacion': ('autenticado', 'Autenticado'), 'transmision': ('transmitiendo', 'Transmitiendo'), 'aceptado': ('aceptado', 'Aceptado por el servidor'), 'error': ('error_etapa', 'Error')}
KINDS = {'receipt': 'Comprobante de recepción', 'client_authorization': 'Autorización de servicio', 'authorization_notice': 'Aviso interno de autorización', 'quote': 'Presupuesto',
         'payment_receipt': 'Recibo de pago', 'stay': 'Aviso de equipo listo / permanencia', 'maintenance': 'Recordatorio de mantenimiento', 'appointment': 'Cita técnica', 'manual': 'Mensaje de Mail Pro', 'campaign': 'Comunicado a clientes'}
# Fallos del proveedor (no del destinatario): conexión, nombre, TLS, credenciales o servidor.
PROVIDER = ('red', 'dns', 'tls', 'credenciales', 'servidor', 'conexion', 'temporal')
ALERTS = {'quote': True, 'appointment': True, 'ready': True, 'permanent': True, 'provider': True}
# Un envío dura como máximo unos segundos (tiempo de espera SMTP de 15 s y un reintento): pasado este plazo ya no está «Enviando».
STALE_MINUTES = 3
PAGE = 25


def stamp(now):
    return now.isoformat(timespec='seconds')


def settings(c):
    row = c.execute("SELECT value FROM system_state WHERE key='mail_delivery_alerts'").fetchone()
    try:
        saved = json.loads(row['value']) if row else {}
    except ValueError:
        saved = {}
    return {key: bool(saved.get(key, default)) for key, default in ALERTS.items()}


def save_settings(c, data):
    clean = {key: data.get(key) is True for key in ALERTS}
    c.execute("INSERT INTO system_state VALUES ('mail_delivery_alerts',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(clean),))
    return clean


def enhanced(text):
    """Código ampliado (5.1.1) dentro del texto de una respuesta SMTP, si lo trae."""
    found = re.search(r'\b([245]\.\d{1,3}\.\d{1,3})\b', str(text or ''))
    return found.group(1) if found else ''


def settle(c, work, attempts=2):
    """Anota el resultado de un envío (mark, accepted, failed…) y confirma. Si la base no responde (p. ej., la conexión remota se cortó
    mientras se hablaba con el servidor de correo), deshace y repite: todas estas anotaciones son idempotentes (huellas únicas, INSERT OR
    IGNORE y UPDATE del mismo valor), así que repetirlas no duplica nada. Si aun así falla, propaga el error para registrarlo."""
    for attempt in range(attempts):
        try:
            work(c)
            c.commit()
            return True
        except sqlite3.Error:
            try:
                c.rollback()
            except sqlite3.Error:
                pass
            if attempt == attempts - 1:
                raise


def start(c, recipients, *, kind, subject, now, archive_id=None, outbox_key='', order_id=None, actor_id=None, retry_of=None):
    """Crea un registro «Enviando» por destinatario, con el evento «Mensaje creado». Devuelve {dirección: id}."""
    ids, at = {}, stamp(now)
    for address in recipients:
        if address.lower() in {key.lower() for key in ids}:
            continue
        row = c.execute('INSERT INTO mail_deliveries(archive_id,outbox_key,kind,subject,recipient,status,event_at,retry_of,order_id,actor_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (archive_id, outbox_key, kind, str(subject or '')[:300], address[:254], 'enviando', at, retry_of, order_id, actor_id, at, at)).lastrowid
        _event(c, row, 'creado', 'enviando', 'sistema', '', 'Mensaje creado.', at, now, 'created:' + str(row))
        _event(c, row, 'cola', 'enviando', 'sistema', '', 'En cola de salida: listo para conectar con el servidor SMTP.', at, now, 'queued:' + str(row))
        ids[address] = row
    return ids


def _stages(c, delivery, trace, now):
    """Etapas reales del envío (conexión, autenticación, transmisión…), cada una con su hora, en el historial. No cambian el estado."""
    for index, step in enumerate(trace or []):
        event, _ = STAGE_EVENTS.get(step.get('stage'), ('etapa', ''))
        if event == 'aceptado':
            continue  # la aceptación se registra con su propio evento de estado
        _event(c, delivery, event, 'enviando' if event != 'error_etapa' else 'fallido', 'smtp', '', step.get('detail', ''), step.get('at') or stamp(now), now, 'stage:' + str(delivery) + ':' + str(index))


def accepted(c, ids, message_id, now, result=None):
    """El servidor SMTP respondió: «Enviado» para los aceptados y rebote o fallo para los rechazados uno por uno."""
    result = result or {}
    refused = {key.lower(): value for key, value in (result.get('refused') or {}).items()}
    for address, delivery in ids.items():
        c.execute('UPDATE mail_deliveries SET message_id=? WHERE id=?', (str(message_id or '')[:300], delivery))
        _stages(c, delivery, result.get('trace'), now)
        if address.lower() in refused:
            code, text = refused[address.lower()]
            _refusal(c, delivery, code, text, now)
        else:
            record(c, delivery, 'enviado', 'aceptado', 'smtp', '250', 'Aceptado por el servidor SMTP del remitente (250).', stamp(now), 'accepted:' + str(delivery), now)
            _event(c, delivery, 'resultado', 'enviado', 'sistema', '', 'Resultado final: enviado. ' + ('El servidor solicitará informes de entrega al destino.' if result.get('dsn') else
                   'La entrega en el buzón del destinatario no se puede confirmar con este servidor (no emite confirmaciones de entrega final).'), stamp(now), now, 'result:' + str(delivery))


def failed(c, ids, error, now):
    """El envío no se completó. Con rechazos por destinatario, cada uno con su código; si no, fallo general con la etapa exacta.
    Si la conexión se cortó mientras se transmitía, no consta si el servidor lo aceptó: queda como Incidencia «sin confirmación»."""
    refused = {key.lower(): value for key, value in (getattr(error, 'refused', None) or {}).items()}
    stage = getattr(error, 'stage', '')
    where = mail_pro.STAGES.get(stage, '')
    kind = getattr(error, 'kind', 'servidor')
    smtp = getattr(error, 'smtp_code', 0) or 0
    for address, delivery in ids.items():
        _stages(c, delivery, getattr(error, 'trace', None), now)
        if address.lower() in refused:
            code_r, text = refused[address.lower()]
            _refusal(c, delivery, code_r, text, now)
        elif kind == 'sin_confirmacion':
            record(c, delivery, 'desconocido', 'sin_confirmacion', 'smtp', 'sin confirmación', str(error)[:300], stamp(now), 'unconfirmed:' + str(delivery), now,
                   reason='Servidor SMTP no devolvió confirmación (se cortó durante la transmisión).', permanent=False)
        else:
            detail = ('Falló en la etapa «' + where + '»' + (' (respuesta SMTP ' + str(smtp) + ')' if smtp else '') + '. ' if where else '') + str(error)
            record(c, delivery, 'fallido', 'error_envio', 'smtp', kind, detail[:300], stamp(now), 'failed:' + str(delivery), now,
                   reason=detail[:300], permanent=kind in ('destinatario', 'rechazo', 'configuracion'))


def _refusal(c, delivery, code, text, now):
    detail = enhanced(text) or str(code)
    if 400 <= int(code) < 500:
        # Rechazo temporal en la conexión: el mensaje NO salió; no se reintenta solo, se informa como fallido temporal.
        record(c, delivery, 'fallido', 'rechazo_temporal', 'smtp', detail, ('Rechazo temporal %s: %s' % (code, text))[:300], stamp(now), 'refused:' + str(delivery), now,
               reason='El servidor no aceptó por ahora a este destinatario (error temporal). Puedes reenviarlo más tarde.', permanent=False)
    else:
        reason = mail_pro.DSN_REASONS.get(detail) or 'El servidor rechazó la dirección del destinatario. Revisa que esté bien escrita.'
        record(c, delivery, 'rebotado', 'rechazo', 'smtp', detail, ('Rechazo %s: %s' % (code, text))[:300], stamp(now), 'refused:' + str(delivery), now,
               reason=reason, permanent=True)


def _event(c, delivery, event, status, source, code, detail, occurred, now, fingerprint):
    return c.execute('INSERT OR IGNORE INTO mail_delivery_events(delivery_id,event,status,source,code,detail,occurred_at,received_at,fingerprint) VALUES (?,?,?,?,?,?,?,?,?)',
                     (delivery, event, status, source, str(code)[:40], str(detail)[:300], occurred, stamp(now), fingerprint[:200])).rowcount == 1


def note(c, delivery, status, event, source, detail, now, fingerprint):
    """Evento informativo (p. ej., un reenvío): queda en el historial sin cambiar el estado, el código ni el motivo."""
    return _event(c, delivery, event, status, source, '', detail, stamp(now), now, fingerprint)


def record(c, delivery, status, event, source, code, detail, occurred, fingerprint, now, reason='', permanent=None):
    """Registra un evento una sola vez (por su huella) y actualiza el estado solo si representa un avance real.

    Devuelve True si el estado cambió. Un evento repetido no hace nada; uno anterior al estado vigente queda en el historial."""
    if not _event(c, delivery, event, status, source, code, detail, occurred, now, fingerprint):
        return False
    row = c.execute('SELECT status,event_at FROM mail_deliveries WHERE id=?', (delivery,)).fetchone()
    current, last = row['status'], row['event_at'] or ''
    if current in FINAL:
        apply = status in FINAL and occurred > last
    else:
        apply = RANK[status] > RANK[current] or (RANK[status] == RANK[current] and occurred >= last)
    if not apply:
        return False
    c.execute('UPDATE mail_deliveries SET status=?,code=?,reason=?,permanent=?,event_at=?,updated_at=? WHERE id=?',
              (status, str(code)[:40], (reason or ('' if status in ('enviado', 'entregado') else str(detail)))[:300], 1 if permanent else 0, occurred, stamp(now), delivery))
    return True


def from_report(c, report, base, now):
    """Aplica un informe de entrega leído del buzón. Asocia por el Message-ID real y el destinatario; devuelve los registros afectados."""
    touched = []
    for item in report.get('items') or [report]:
        if not item.get('original_id'):
            continue
        rows = c.execute('SELECT id,recipient FROM mail_deliveries WHERE message_id=?', (item['original_id'],)).fetchall()
        match = [row for row in rows if row['recipient'].lower() == item['recipient'].lower()]
        # Reenvío o alias en el destino: si el envío tenía un único destinatario, el informe le corresponde.
        if not match and len(rows) == 1:
            match = rows
        status = {'failed': 'rebotado', 'delayed': 'demorado'}.get(item['action'], 'entregado')
        event = {'rebotado': 'rebote', 'demorado': 'demora', 'entregado': 'entregado'}[status]
        detail = item['reason'] + (' Diagnóstico: ' + item['diagnostic'] if item.get('diagnostic') else '')
        for row in match:
            record(c, row['id'], status, event, 'informe', item['status'], detail, item.get('date') or stamp(now), base + ':' + item['recipient'].lower(), now,
                   reason=item['reason'], permanent=status == 'rebotado' and item['status'] in mail_pro.INVALID_ADDRESS)
            touched.append(row['id'])
    return touched


def sweep(c, now):
    """Ningún envío se queda en «Enviando»: pasado el plazo se busca el resultado real que sí quedó anotado (archivo del mensaje o cola de
    salida) y, si no lo hay, pasa a Incidencia con la causa exacta. Nada se borra y el historial conserva cada paso."""
    limit = stamp(now - timedelta(minutes=STALE_MINUTES))
    for row in c.execute("SELECT id,archive_id,outbox_key FROM mail_deliveries WHERE status IN ('cola','enviando') AND updated_at<?", (limit,)).fetchall():
        archived = c.execute('SELECT status,detail FROM mail_archive WHERE id=?', (row['archive_id'],)).fetchone() if row['archive_id'] else None
        outbox = c.execute('SELECT status FROM mail_outbox WHERE request_key=?', (row['outbox_key'],)).fetchone() if row['outbox_key'] else None
        if (archived and archived['status'] == 'enviado') or (outbox and outbox['status'] == 'sent'):
            record(c, row['id'], 'enviado', 'aceptado', 'sistema', '250', 'Recuperado del registro del mensaje: el servidor SMTP lo había aceptado, pero el seguimiento no se actualizó a tiempo.', stamp(now), 'stale:' + str(row['id']), now)
        elif (archived and archived['status'] == 'error') or (outbox and outbox['status'] == 'failed'):
            record(c, row['id'], 'fallido', 'error_envio', 'sistema', 'servidor', 'Recuperado del registro del mensaje: el envío falló. ' + ((archived['detail'] if archived else '') or ''), stamp(now), 'stale:' + str(row['id']), now,
                   reason=((archived['detail'] if archived else '') or 'El envío falló.')[:300])
        else:
            record(c, row['id'], 'desconocido', 'sin_confirmacion', 'sistema', 'sin confirmación',
                   'Servidor SMTP no devolvió confirmación registrada: el proceso de envío se interrumpió antes de anotar la respuesta del servidor (p. ej., se cortó la conexión con la base de datos o terminó el tiempo de la petición). Revisa la carpeta Enviados del buzón antes de reenviarlo.',
                   stamp(now), 'stale:' + str(row['id']), now, reason='Servidor SMTP no devolvió confirmación registrada (el envío se interrumpió).')


def blocked(c, address):
    """Motivo si la dirección fue declarada inválida por un rebote permanente y no hubo después un envío aceptado; '' si no."""
    row = c.execute("SELECT status,code,reason,permanent FROM mail_deliveries WHERE recipient=? COLLATE NOCASE AND status IN ('enviado','entregado','rebotado') ORDER BY id DESC LIMIT 1", (address,)).fetchone()
    if row and row['status'] == 'rebotado' and row['permanent']:
        return 'La dirección ' + address + ' fue rechazada de forma permanente (' + (row['code'] or 'rebote') + '): ' + row['reason']
    return ''


def _public(row):
    item = dict(row)
    item['label'] = LABELS[item['status']]
    item['meaning'] = MEANING[item['status']]
    item['kind_label'] = KINDS.get(item['kind'], 'Notificación')
    item['incident'] = item['status'] in INCIDENTS and not item['resolved_at']
    return item


def listing(c, filters):
    where, args = ['1=1'], []
    if filters.get('status') in FILTERS:
        codes = FILTERS[filters['status']]
        where.append('d.status IN (' + ','.join('?' for _ in codes) + ')')
        args += codes
    if filters.get('incidents'):
        where.append("d.status IN ('demorado','rebotado','fallido','desconocido') AND d.resolved_at=''")
    query = str(filters.get('q') or '').strip()[:120]
    if query:
        where.append("instr(lower(d.recipient||' '||d.subject),lower(?))>0")
        args.append(query)
    for key, sign in (('from', '>='), ('to', '<=')):
        value = str(filters.get(key) or '')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            where.append('substr(d.created_at,1,10)' + sign + '?')
            args.append(value)
    source = ' FROM mail_deliveries d LEFT JOIN orders o ON o.id=d.order_id WHERE ' + ' AND '.join(where)
    total = c.execute('SELECT COUNT(*)' + source, args).fetchone()[0]
    page = max(1, min(int(filters.get('page') or 1), max(1, (total + PAGE - 1) // PAGE)))
    rows = [_public(row) for row in c.execute(
        "SELECT d.*,COALESCE(o.code,'') order_code,(SELECT e.detail FROM mail_delivery_events e WHERE e.delivery_id=d.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1) last_event,"
        "(SELECT COUNT(*) FROM mail_deliveries r WHERE r.retry_of=d.id) retries" + source + ' ORDER BY d.id DESC LIMIT ? OFFSET ?', (*args, PAGE, (page - 1) * PAGE))]
    counts = {key: 0 for key in FILTERS}
    for row in c.execute('SELECT status,COUNT(*) total FROM mail_deliveries GROUP BY status'):
        for key, codes in FILTERS.items():
            if row['status'] in codes:
                counts[key] += row['total']
    pending = c.execute("SELECT COUNT(*) FROM mail_deliveries WHERE status IN ('demorado','rebotado','fallido','desconocido') AND resolved_at=''").fetchone()[0]
    counts['incidencias'] = pending
    inbox = c.execute("SELECT value FROM system_state WHERE key='mail_inbox'").fetchone()
    try:
        inbox = json.loads(inbox['value']) if inbox else {}
    except ValueError:
        inbox = {}
    imap = {'checked': inbox.get('checked', ''), 'error': inbox.get('error', '') if inbox.get('ts', 0) > 0 and inbox.get('error') else ''}
    return {'rows': rows, 'total': total, 'page': page, 'pages': max(1, (total + PAGE - 1) // PAGE), 'counts': counts, 'incidents': pending, 'meaning': MEANING, 'imap': imap}


def detail(c, delivery):
    row = c.execute("SELECT d.*,COALESCE(o.code,'') order_code FROM mail_deliveries d LEFT JOIN orders o ON o.id=d.order_id WHERE d.id=?", (delivery,)).fetchone()
    if not row:
        return None
    item = _public(row)
    item['events'] = [dict(event) for event in c.execute('SELECT event,status,source,code,detail,occurred_at,received_at FROM mail_delivery_events WHERE delivery_id=? ORDER BY occurred_at,id', (delivery,))]
    # Cadena de intentos: el intento original y sus reenvíos, cada uno con su propio estado.
    first = delivery
    seen = set()
    while True:
        parent = c.execute('SELECT retry_of FROM mail_deliveries WHERE id=?', (first,)).fetchone()
        if not parent or not parent['retry_of'] or parent['retry_of'] in seen:
            break
        seen.add(first)
        first = parent['retry_of']
    chain, queue = [], [first]
    while queue and len(chain) < 20:
        current = queue.pop(0)
        node = c.execute('SELECT id,recipient,status,created_at,retry_of FROM mail_deliveries WHERE id=?', (current,)).fetchone()
        if node:
            chain.append(dict(node, label=LABELS[node['status']]))
            queue += [child['id'] for child in c.execute('SELECT id FROM mail_deliveries WHERE retry_of=? ORDER BY id', (current,))]
    item['attempts'] = chain
    item['resend'] = resend_check(c, row)
    return item


def resend_check(c, row):
    """Si este envío puede reenviarse desde aquí y, si no, por qué (sin perder contenido ni exponer enlaces privados)."""
    if row['status'] in ('cola', 'enviando'):
        return {'allowed': False, 'reason': 'El envío todavía está en curso.'}
    if row['archive_id']:
        archived = c.execute('SELECT attachments,body_text FROM mail_archive WHERE id=?', (row['archive_id'],)).fetchone()
        if archived and archived['attachments']:
            return {'allowed': False, 'reason': 'Este correo llevaba adjuntos que se generan desde la orden (' + archived['attachments'][:120] + '). Corrige el correo del cliente y vuelve a enviarlo desde la orden.'}
        if archived and '[enlace privado omitido' in archived['body_text']:
            return {'allowed': False, 'reason': 'Este correo contenía un enlace privado de un solo uso que no se guarda. Genera un enlace nuevo desde la orden.'}
        return {'allowed': True, 'reason': ''}
    if row['outbox_key']:
        return {'allowed': bool(row['message_id']), 'reason': '' if row['message_id'] else 'No consta el identificador del mensaje original.'}
    return {'allowed': False, 'reason': 'No hay una copia del mensaje para reenviarlo.'}


def category(row):
    if row['kind'] == 'quote':
        return 'quote'
    if row['kind'] == 'appointment':
        return 'appointment'
    if row['kind'] == 'stay':
        return 'ready'
    return 'permanent'


TITLES = {'quote': 'Presupuesto no entregado', 'appointment': 'Correo de cita no entregado', 'ready': 'Aviso de equipo listo no entregado', 'permanent': 'Correo no entregado'}


def alerts(c, now):
    """Avisos del centro de notificaciones: una entrada por incidencia y cambio de estado (sin duplicados), un resumen y los fallos repetidos del proveedor."""
    config, items = settings(c), []
    since = stamp(now - timedelta(days=14))
    rows = c.execute("SELECT * FROM mail_deliveries WHERE status IN ('demorado','rebotado','fallido','entregado') AND resolved_at='' AND updated_at>=? ORDER BY updated_at DESC LIMIT 30", (since,)).fetchall()
    pending = 0
    for row in rows:
        if row['status'] == 'entregado':
            if row['updated_at'] >= stamp(now - timedelta(days=1)):
                items.append({'key': 'maildelivery:' + str(row['id']) + ':entregado', 'kind': 'success', 'icon': 'message', 'title': 'Correo entregado al servidor del destinatario',
                              'detail': row['recipient'] + ' · ' + row['subject'][:80], 'at': row['event_at'] or row['updated_at'], 'href': '#mail?view=entregas&id=' + str(row['id']), 'group': 'event'})
            continue
        group = category(row)
        if row['status'] == 'fallido' and row['code'] in PROVIDER:
            group = 'provider'
        if not config.get(group if group != 'provider' else 'permanent'):
            continue
        pending += 1
        if len(items) >= 10:
            continue
        message = ('La entrega presenta una demora. El sistema continuará comprobando su estado.' if row['status'] == 'demorado' else
                   'No se pudo entregar el correo. Revisa la dirección del destinatario.' if row['status'] == 'rebotado' and row['permanent'] else
                   'No se pudo entregar el correo.' if row['status'] == 'rebotado' else 'No se pudo completar el envío.')
        title = ('Entrega demorada' if row['status'] == 'demorado' else TITLES[group] if group in TITLES else 'Correo no enviado')
        items.append({'key': 'maildelivery:' + str(row['id']) + ':' + row['status'], 'kind': 'warning' if row['status'] == 'demorado' else 'error', 'icon': 'message',
                      'title': title + ' · ' + row['recipient'],
                      'detail': message + (' ' + row['reason'] if row['reason'] else '') + (' (' + row['code'] + ')' if row['code'] else ''),
                      'at': row['event_at'] or row['updated_at'], 'href': '#mail?view=entregas&id=' + str(row['id']), 'group': 'event', 'bounce': True})
    if pending:
        items.append({'key': 'maildelivery:summary:' + str(pending), 'kind': 'warning', 'icon': 'message', 'title': ('1 incidencia de entrega pendiente' if pending == 1 else str(pending) + ' incidencias de entrega pendientes'),
                      'detail': 'Revísalas en Mail Pro → Centro de Entrega y Seguimiento.', 'at': stamp(now), 'href': '#mail?view=entregas&filtro=incidencias', 'group': 'alert', 'quiet': True})
    if config['provider']:
        hour = now.replace(minute=0, second=0, microsecond=0)
        failures = c.execute("SELECT COUNT(*) FROM mail_deliveries WHERE status='fallido' AND code IN (" + ','.join('?' for _ in PROVIDER) + ') AND updated_at>=?', (*PROVIDER, stamp(now - timedelta(hours=1)))).fetchone()[0]
        if failures >= 3:
            items.append({'key': 'maildelivery:provider:' + hour.strftime('%Y%m%d%H'), 'kind': 'error', 'icon': 'message', 'title': 'Fallos repetidos del servidor de correo',
                          'detail': str(failures) + ' envíos fallaron en la última hora por un problema del servidor o de la conexión. Revisa Configuración → Correo y servicios.',
                          'at': stamp(now), 'href': '#mail?view=entregas&filtro=fallidos', 'group': 'event', 'bounce': True})
    return items
