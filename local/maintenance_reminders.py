"""Recordatorios de mantenimiento preventivo por correo y respuesta del cliente desde un enlace seguro.

Se envían a los clientes con correo válido, salvo a quienes rechazaron o se dieron de baja, una vez por etapa (30, 15, 7, 3
y 0 días antes de la fecha recomendada). Cada correo incluye el enlace para dejar de recibirlos. Están apagados hasta que administración los activa. «sent» significa que el servidor de correo aceptó
el mensaje. La página del cliente no muestra datos personales: solo el equipo, la fecha y la cita propuesta."""
import html
import re
from datetime import datetime

import maintenance
from corporate import settings
from order_tracking import HEAD
from reception import ECUADOR_TZ, public_base_url

STAGES = (30, 15, 7, 3, 0)
BATCH = 3
ACTIONS = {'confirm': 'Confirmó la fecha propuesta', 'reschedule': 'Pidió otro horario', 'decline': 'No desea recibir recordatorios'}
MAIL = re.compile(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+')


def enabled(c):
    row = c.execute("SELECT value FROM system_state WHERE key='maintenance_reminders'").fetchone()
    return bool(row and row['value'] == 'on')


def stage_for(days_left):
    """Etapa que corresponde hoy: la más cercana ya alcanzada. Fuera de la ventana (más de 30 días o más de 3 de retraso) no hay aviso."""
    if days_left is None or days_left > STAGES[0] or days_left < -3:
        return None
    return min(stage for stage in STAGES if max(days_left, 0) <= stage)


def link(token):
    return public_base_url().rstrip('/') + '/mantenimiento/' + token


def pending(c, today):
    out = []
    for row in maintenance.rows(c, today):
        stage = stage_for(row.get('days_left'))
        if stage is None or row['state'] not in ('scheduled', 'appointment') or row['consent'] == 'declined' or not MAIL.fullmatch((row.get('email') or '').strip()):
            continue
        if c.execute('SELECT 1 FROM maintenance_reminders WHERE maintenance_id=? AND generation=? AND stage=?', (row['id'], row['generation'], stage)).fetchone():
            continue
        out.append((row, stage))
    return out


def message_for(row, stage):
    days = row['days_left']
    when = datetime.fromisoformat(row['due_date']).strftime('%d/%m/%Y')
    lead = 'hoy' if days <= 0 else 'mañana' if days == 1 else 'dentro de %d días' % days
    device = ' '.join(part for part in (row.get('brand') or '', row.get('model') or '') if part) or 'su equipo'
    lines = ['Estimado/a ' + row['client'] + ':', '', 'Le recordamos que el mantenimiento preventivo de ' + device + ' está recomendado para el ' + when + ' (' + lead + ').']
    if row.get('appointment_start') and row.get('appointment_status') in ('solicitada', 'confirmada', 'reprogramada'):
        start = datetime.fromisoformat(row['appointment_start']).astimezone(ECUADOR_TZ)
        lines.append('Cita ' + ('confirmada' if row['appointment_status'] == 'confirmada' else 'propuesta') + ': ' + start.strftime('%d/%m/%Y a las %H:%M') + ' (' + row.get('appointment_code', '') + ').')
    lines += ['', 'Desde este enlace seguro puede confirmar la fecha, pedir otro horario o dejar de recibir recordatorios:', link(row['unsubscribe_token']), '',
              'Orden original: ' + row['code'] + '.', '', 'Atentamente,', '', 'Departamento de Servicio Técnico', 'PC-DOCTOR S.A.']
    return 'PC-DOCTOR S.A. | Recordatorio de mantenimiento preventivo — ' + device, '\n'.join(lines)


def run(c, now, deliver, limit=BATCH):
    """Envía hasta «limit» recordatorios pendientes. «deliver(destinatario, asunto, cuerpo)» lanza una excepción si falla."""
    summary = {'sent': 0, 'failed': 0, 'left': 0}
    todo = pending(c, now.astimezone(ECUADOR_TZ).date())
    summary['left'] = max(0, len(todo) - limit)
    for row, stage in todo[:limit]:
        email = row['email'].strip()
        reserved = c.execute("INSERT OR IGNORE INTO maintenance_reminders(maintenance_id,generation,stage,recipient,result,created_at) VALUES (?,?,?,?,'processing',?)", (row['id'], row['generation'], stage, email, now.isoformat(timespec='seconds')))
        if reserved.rowcount != 1:
            continue
        c.commit()
        subject, body = message_for(row, stage)
        try:
            deliver(email, subject, body)
            result, detail = 'sent', 'El servidor de correo aceptó el mensaje.'
            summary['sent'] += 1
        except Exception as error:
            result, detail = 'failed', str(error)[:200]
            summary['failed'] += 1
        c.execute('UPDATE maintenance_reminders SET result=?,detail=? WHERE maintenance_id=? AND generation=? AND stage=?', (result, detail, row['id'], row['generation'], stage))
        if result == 'sent':
            from order_workspace import event
            event(c, row['order_id'], None, now, 'maintenance', 'Recordatorio de mantenimiento enviado al cliente (' + ('día previsto' if stage == 0 else 'faltan %d días o menos' % stage) + ').')
        c.commit()
    return summary


def status(c, today):
    todo = pending(c, today)
    last = c.execute('SELECT recipient,result,stage,created_at FROM maintenance_reminders ORDER BY id DESC LIMIT 5').fetchall()
    responses = [dict(row) for row in c.execute("SELECT r.id,r.maintenance_id,r.action,r.note,r.created_at,o.id order_id,o.code,cl.name client FROM maintenance_responses r JOIN maintenance m ON m.id=r.maintenance_id JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE r.handled_at='' ORDER BY r.id DESC LIMIT 50")]
    for item in responses:
        item['label'] = ACTIONS[item['action']]
    return {'enabled': enabled(c), 'stages': list(STAGES), 'pending': [{'client': row['client'], 'code': row['code'], 'stage': stage, 'due_date': row['due_date']} for row, stage in todo[:20]], 'pending_total': len(todo),
            'recent': [dict(row) for row in last], 'responses': responses}


# --- Página pública del cliente -----------------------------------------------------------------------------------------

def _page(title, body):
    company = settings()
    return HEAD % (title, html.escape(company['specialty'])) + body + '<footer><p>WhatsApp: %s</p><p class="tracking-note">Esta página no contiene datos personales. Sus respuestas llegan al taller para coordinar la atención.</p></footer></main></body></html>' % html.escape(company['whatsapp'])


def missing_page():
    return _page('Enlace no disponible', '<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace no existe o ya no está activo. Comuníquese con el taller para coordinar su mantenimiento.</p></section>')


def lookup(c, token):
    for row in maintenance.rows(c):
        if row['unsubscribe_token'] == token:
            return row
    return None


def page(row, token, notice='', error=''):
    e = html.escape
    device = ' '.join(part for part in (row.get('brand') or '', row.get('model') or '') if part) or 'Equipo registrado'
    when = datetime.fromisoformat(row['due_date']).strftime('%d/%m/%Y')
    facts = [('Equipo', device), ('Fecha recomendada', when)]
    if row.get('appointment_start') and row.get('appointment_status') in ('solicitada', 'confirmada', 'reprogramada'):
        start = datetime.fromisoformat(row['appointment_start']).astimezone(ECUADOR_TZ)
        facts.append(('Cita ' + ('confirmada' if row['appointment_status'] == 'confirmada' else 'propuesta'), start.strftime('%d/%m/%Y a las %H:%M')))
    rows = ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (e(label), e(value)) for label, value in facts)
    head = '<section class="tracking-card auth-card"><small>MANTENIMIENTO PREVENTIVO</small><h1>Orden %s</h1><dl>%s</dl>' % (e(row['code']), rows)
    if notice:
        return _page('Mantenimiento preventivo', head + '<p class="auth-done" role="status">%s</p></section>' % e(notice))
    if row['state'] not in ('scheduled', 'appointment'):
        return _page('Mantenimiento preventivo', head + '<p>Este mantenimiento ya no está pendiente. Si necesita atención, comuníquese con el taller.</p></section>')
    alert = '<p class="auth-alert" role="alert">%s</p>' % e(error) if error else ''
    form = lambda action, label, extra='', cls='': '<form method="post" action="/mantenimiento/%s" class="auth-form"><input type="hidden" name="action" value="%s">%s<button type="submit"%s>%s</button></form>' % (e(token), action, extra, ' class="%s"' % cls if cls else '', e(label))
    body = head + alert + form('confirm', 'Confirmar esta fecha') \
        + form('reschedule', 'Solicitar otro horario', '<label for="note">¿Qué día y hora le conviene? (opcional)</label><textarea id="note" name="note" maxlength="300" rows="2"></textarea>', 'auth-secondary') \
        + (form('decline', 'No deseo recibir recordatorios', '', 'auth-secondary') if row['consent'] != 'declined' else '<p class="auth-hint">Ya no recibe recordatorios de este mantenimiento.</p>') + '</section>'
    return _page('Mantenimiento preventivo', body)


def respond(c, row, action, note, now):
    """Registra la respuesta del cliente. No modifica la agenda: el personal coordina la cita con esa información."""
    if action not in ACTIONS:
        return None
    if row['state'] not in ('scheduled', 'appointment'):
        return 'Este mantenimiento ya no está pendiente.'
    stamp = now.isoformat(timespec='seconds')
    note = ' '.join(str(note or '').split())[:300] if action == 'reschedule' else ''
    recent = c.execute("SELECT action,note FROM maintenance_responses WHERE maintenance_id=? AND handled_at='' ORDER BY id DESC LIMIT 1", (row['id'],)).fetchone()
    if not recent or (recent['action'], recent['note']) != (action, note):
        c.execute('INSERT INTO maintenance_responses(maintenance_id,action,note,created_at) VALUES (?,?,?,?)', (row['id'], action, note, stamp))
        from order_workspace import event
        event(c, row['order_id'], None, now, 'maintenance', 'Respuesta del cliente por enlace seguro: ' + ACTIONS[action].lower() + ('. ' + note if note else '.'))
    if action == 'decline':
        c.execute("UPDATE maintenance SET consent='declined',consent_at=?,consent_actor=NULL,updated_at=? WHERE id=?", (stamp, stamp, row['id']))
        return 'Listo: no recibirá más recordatorios de este mantenimiento.'
    return 'Gracias. Registramos su confirmación; el taller le contactará si hace falta algún ajuste.' if action == 'confirm' else 'Gracias. Recibimos su solicitud; el taller le contactará para acordar el nuevo horario.'
