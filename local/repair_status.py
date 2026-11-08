"""Estados de reparación (1.5.257): una sola fuente para el panel, el seguimiento público, la hoja A4, los reportes y los avisos.

- Once estados. Cada uno es una ETAPA normal del proceso, una ESPERA o una INCIDENCIA (el color y la etiqueta lo distinguen) o el CIERRE.
- Compatibilidad: los códigos anteriores no cambian; el historial (inmutable) conserva sus etiquetas antiguas («En espera», «Procesando»,
  «Aprobación de presupuesto», …) y `code_for_label` las reconoce.
- Cambios automáticos SOLO ante un evento real y registrado (seguimiento técnico, envío o decisión de un presupuesto, pedido, recepción o
  instalación de un repuesto). Nunca por el paso del tiempo. La aprobación de un presupuesto no marca que la reparación comenzó.
- Auditoría: cada cambio queda en order_status_log (anterior, nuevo, quién, cuándo, motivo y evento que lo produjo) además del historial.
- Avisos al cliente solo en cambios relevantes (presupuesto pendiente, respuesta pendiente, espera de repuesto, revisión por falla
  recurrente y equipo listo), uno por cambio y canal, sin repetir el mismo aviso en 72 h y respetando las preferencias del cliente."""
from datetime import datetime, timedelta

# código: (etiqueta, tipo, icono Lucide, tono, etapa visual 0–5, explicación para el cliente)
STATUS = {
    'pendiente': ('En espera de diagnóstico', 'etapa', 'clock', 'gris', 0,
                  'Su equipo fue recibido y está en cola para la revisión técnica. Le informaremos cuando comience el diagnóstico.'),
    'diagnostico': ('Diagnóstico en proceso', 'etapa', 'scan-search', 'azul', 1,
                    'Nuestro equipo técnico está evaluando su equipo para determinar el origen de la falla. Al terminar le informaremos el resultado y, si corresponde, el presupuesto.'),
    'reparacion': ('Reparación en proceso', 'etapa', 'wrench', 'indigo', 2,
                   'Nuestro equipo técnico está realizando los trabajos correspondientes en su equipo. Una vez finalizados, procederemos con las pruebas de funcionamiento '
                   'y control de calidad. Le notificaremos cuando su equipo esté listo para retirar.'),
    'presupuesto': ('Pendiente de aprobación de presupuesto', 'espera', 'clipboard-list', 'ambar', 1,
                    'Le enviamos un presupuesto. Los trabajos continuarán cuando usted lo apruebe; ningún servicio se realiza sin su autorización.'),
    'esperando_cliente': ('Esperando respuesta del cliente', 'espera', 'message-square', 'violeta', 1,
                          'Necesitamos una confirmación o información de su parte para continuar con el servicio. Por favor, comuníquese con nosotros.'),
    'esperando_repuesto': ('Esperando repuesto', 'espera', 'package', 'naranja', 2,
                           'Su equipo requiere un componente que ya fue solicitado. Continuaremos con el servicio cuando lo recibamos y le informaremos cada avance.'),
    'revision_recurrente': ('Revisión por falla recurrente', 'incidencia', 'rotate-ccw', 'rojo', 1,
                            'Su equipo está en una revisión técnica adicional por una falla que se repitió. El historial anterior se conserva completo.'),
    'pruebas': ('Pruebas técnicas y control de calidad', 'etapa', 'shield-check', 'celeste', 3,
                'Los trabajos finalizaron y estamos verificando el funcionamiento de su equipo antes de entregarlo.'),
    'espera_entrega': ('En espera de entrega', 'etapa', 'truck', 'turquesa', 4,
                       'Estamos preparando y coordinando la entrega de su equipo.'),
    'listo': ('Listo para entregar', 'etapa', 'package-check', 'verde', 4,
              'Su equipo está terminado y disponible para retiro en nuestro local, sujeto a las condiciones de retiro de su orden.'),
    'entregado': ('Entregado', 'cierre', 'handshake', 'cierre', 5, 'El equipo fue entregado. Gracias por confiar en PC-DOCTOR.'),
}
ORDER = ('pendiente', 'diagnostico', 'reparacion', 'presupuesto', 'esperando_cliente', 'esperando_repuesto', 'revision_recurrente', 'pruebas',
         'espera_entrega', 'listo', 'entregado')
LABELS = {code: STATUS[code][0] for code in ORDER}
KIND_LABEL = {'etapa': 'Etapa del proceso', 'espera': 'Espera', 'incidencia': 'Incidencia', 'cierre': 'Cierre'}
# Etiquetas que guardó el historial con versiones anteriores (no se reescriben: se reconocen).
LEGACY = {'En espera': 'pendiente', 'Pendiente': 'pendiente', 'Procesando': 'reparacion', 'En reparación': 'reparacion', 'En diagnóstico': 'diagnostico',
          'Aprobación de presupuesto': 'presupuesto', 'En revisión por falla recurrente': 'revision_recurrente', 'Listo para entrega': 'listo'}
WORKING = ('pendiente', 'diagnostico', 'reparacion', 'revision_recurrente', 'pruebas')  # etapas a las que se vuelve cuando termina una espera
OPEN = tuple(code for code in ORDER if code != 'entregado')
WAITING_PARTS = ('solicitado', 'confirmado', 'preparacion', 'transito')

# Evento real → (estados desde los que aplica, estado nuevo, explicación para el historial).
RULES = {
    'followup:diagnostico': (('pendiente',), 'diagnostico', 'Diagnóstico técnico registrado: comienza la revisión del equipo.'),
    'followup:reparacion': (('pendiente', 'diagnostico', 'esperando_repuesto'), 'reparacion', 'Reparación registrada por el técnico: inicio efectivo de los trabajos.'),
    'followup:repuesto': (('pendiente', 'diagnostico', 'reparacion', 'revision_recurrente'), 'esperando_repuesto', 'Seguimiento «Esperando repuesto» registrado.'),
    'followup:pruebas': (('diagnostico', 'reparacion', 'revision_recurrente'), 'pruebas', 'Pruebas de funcionamiento registradas: control de calidad en curso.'),
    'followup:finalizado': (('diagnostico', 'reparacion', 'revision_recurrente'), 'pruebas', 'Trabajos finalizados: pasan a pruebas técnicas y control de calidad.'),
    'quote_sent': (('pendiente', 'diagnostico', 'reparacion', 'revision_recurrente', 'esperando_repuesto', 'pruebas', 'esperando_cliente'), 'presupuesto',
                   'Presupuesto enviado al cliente para su aprobación.'),
    'part_requested': (('pendiente', 'diagnostico', 'reparacion', 'revision_recurrente'), 'esperando_repuesto', 'Pedido de repuesto registrado.'),
    'part_installing': (('pendiente', 'diagnostico', 'esperando_repuesto'), 'reparacion', 'Instalación del repuesto registrada: inicio efectivo de la reparación.'),
}
SOURCES = {'manual': 'Cambio manual', 'edicion': 'Edición de la orden', 'orden_registrada': 'Orden registrada', 'quote_sent': 'Presupuesto enviado',
           'quote_approved': 'Presupuesto aprobado', 'part_requested': 'Repuesto solicitado', 'part_received': 'Repuesto recibido', 'part_installing': 'Instalación de repuesto',
           'followup:diagnostico': 'Seguimiento técnico', 'followup:reparacion': 'Seguimiento técnico', 'followup:repuesto': 'Seguimiento técnico',
           'followup:pruebas': 'Seguimiento técnico', 'followup:finalizado': 'Seguimiento técnico'}

# Avisos al cliente: estado → (asunto, texto). Los demás cambios no avisan (son internos o menores).
NOTICE = {
    'presupuesto': ('Presupuesto pendiente de aprobación', 'Su orden tiene un presupuesto pendiente de aprobación. Los trabajos continuarán cuando usted lo autorice.'),
    'esperando_cliente': ('Necesitamos su respuesta', 'Para continuar con el servicio de su equipo necesitamos una confirmación o información de su parte. Por favor, comuníquese con nosotros.'),
    'esperando_repuesto': ('Su equipo espera un repuesto', 'Su equipo requiere un componente que ya fue solicitado. Continuaremos con el servicio cuando lo recibamos y le informaremos cada avance.'),
    'revision_recurrente': ('Revisión técnica adicional', 'Su equipo ingresó a una revisión técnica adicional por una falla que se repitió. Esto puede modificar el plazo de entrega; '
                            'le informaremos la nueva fecha cuando esté confirmada.'),
    'listo': ('Equipo listo para retirar', 'Su equipo está terminado y disponible para retiro en nuestro local, sujeto a las condiciones de retiro de su orden.'),
}
SETTING = 'status_notices_auto'
REPEAT_HOURS = 72
QUIET_MINUTES = 10  # 1.5.259: entre dos avisos de la misma orden (evita dos correos seguidos al corregir un estado)
MAX_ATTEMPTS = 3


class StatusError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def code_for_label(label, labels=None):
    """Código de una etiqueta guardada en el historial (actual o de una versión anterior)."""
    for code, text in (labels or LABELS).items():
        if text == label:
            return code
    return LEGACY.get(label, '')


def catalog():
    """Catálogo para la interfaz: orden, etiqueta, tipo, icono, tono, etapa y explicación pública."""
    return [{'code': code, 'label': LABELS[code], 'kind': STATUS[code][1], 'kind_label': KIND_LABEL[STATUS[code][1]], 'icon': STATUS[code][2], 'tone': STATUS[code][3],
             'stage': STATUS[code][4], 'public': STATUS[code][5], 'notifies': code in NOTICE} for code in ORDER]


def waiting_parts(c, oid):
    try:
        return c.execute("SELECT COUNT(*) FROM order_part_requests WHERE order_id=? AND situation!='cancelado' AND stage IN (%s)" % ','.join('?' * len(WAITING_PARTS)),
                         (oid, *WAITING_PARTS)).fetchone()[0]
    except Exception:
        return 0


def check(c, oid, old, new, reason=''):
    """Transiciones incompatibles (además de las reglas de entrega y de falla recurrente de la ruta). Devuelve el error o ''."""
    reason = ' '.join(str(reason or '').split())
    if new not in STATUS:
        return 'Selecciona un estado válido.'
    if new == 'esperando_repuesto' and old != new and not waiting_parts(c, oid) and len(reason) < 10:
        return 'La orden no tiene un pedido de repuesto activo. Regístralo en «Pedidos de repuestos» o indica el motivo (al menos 10 caracteres).'
    if new == 'pruebas' and old == 'pendiente' and len(reason) < 10:
        return 'La orden aún no tiene diagnóstico ni reparación. Indica el motivo para pasarla a pruebas (al menos 10 caracteres).'
    return ''


def log(c, oid, old, new, actor, reason, source, detail, now, notify=True):
    """Registro de auditoría del cambio y avisos al cliente (pendientes de envío; se envían tras confirmar la transacción)."""
    cur = c.execute('INSERT INTO order_status_log(order_id,from_status,to_status,actor_id,reason,source,detail,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (oid, old or '', new, actor, str(reason or '')[:2000], source, str(detail or '')[:500], now.isoformat(timespec='microseconds')))
    lid = cur.lastrowid
    if old != new:
        emit(c, oid, lid, new, source, now, notify)
    return lid


def change(c, oid, new, now, actor=None, reason='', source='manual', detail='', notify=True):
    """Cambia el estado por un evento real: orden, historial y auditoría en la misma transacción. Sin cambio real, no hace nada."""
    import order_workspace
    row = c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()
    if not row or row['status'] == new or new not in STATUS:
        return None
    old = row['status']
    c.execute('UPDATE orders SET status=?,updated_at=?,revision=revision+1 WHERE id=?', (new, now.isoformat(timespec='microseconds'), oid))
    text = (detail + ' ' if detail else '') + 'El estado pasa de «%s» a «%s».' % (LABELS.get(old, old), LABELS[new])
    order_workspace.event(c, oid, actor, now, 'status', text)
    return log(c, oid, old, new, actor, reason, source, detail, now, notify)


def _back(c, oid, wait):
    """Etapa a la que vuelve la orden cuando termina una espera: la anterior a esa espera (sin inventar una reparación iniciada)."""
    row = c.execute('SELECT from_status FROM order_status_log WHERE order_id=? AND to_status=? ORDER BY id DESC LIMIT 1', (oid, wait)).fetchone()
    previous = row['from_status'] if row else ''
    if previous in ('', 'pendiente') or previous not in WORKING:
        return 'diagnostico'
    return previous


def auto(c, oid, event, now, actor=None, detail=''):
    """Transición automática por un evento real. Devuelve el id de auditoría o None si el evento no cambia nada en el estado actual."""
    row = c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()
    if not row:
        return None
    status = row['status']
    if event == 'quote_approved':
        # Se habilita continuar: vuelve a la etapa anterior a la espera (o espera el repuesto pendiente). No marca la reparación como iniciada.
        if status not in ('presupuesto', 'esperando_cliente'):
            return None
        target = 'esperando_repuesto' if waiting_parts(c, oid) else _back(c, oid, status)
        return change(c, oid, target, now, actor, '', event, detail or 'Presupuesto aprobado: el proceso puede continuar; la reparación se marca cuando comience.')
    if event == 'part_received':
        if status != 'esperando_repuesto' or waiting_parts(c, oid):
            return None
        return change(c, oid, _back(c, oid, 'esperando_repuesto'), now, actor, '', event, detail or 'Repuesto recibido en el taller: el técnico responsable puede continuar.')
    rule = RULES.get(event)
    if not rule or status not in rule[0]:
        return None
    return change(c, oid, rule[1], now, actor, '', event, detail or rule[2])


# ---- Avisos al cliente ------------------------------------------------------------------------------------------------------------------
def enabled(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (SETTING,)).fetchone()
    return not (row and row['value'] == 'off')


def set_enabled(c, on, user):
    if user['role'] != 'administrador':
        raise StatusError('Solo administración cambia este ajuste.', 403)
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SETTING, 'on' if on else 'off'))


def _recent(c, oid, event, now):
    """¿Ya se avisó al cliente de este estado (o, si está listo, del repuesto listo) en las últimas 72 h?"""
    since = (now - timedelta(hours=REPEAT_HOURS)).isoformat(timespec='seconds')
    if c.execute("SELECT 1 FROM order_status_notices WHERE order_id=? AND event=? AND status IN ('pendiente','enviado') AND created_at>=? LIMIT 1", (oid, event, since)).fetchone():
        return True
    if event == 'listo':
        try:
            return bool(c.execute("SELECT 1 FROM order_part_notices n JOIN order_part_requests r ON r.id=n.request_id WHERE r.order_id=? AND n.event='listo' "
                                  "AND n.status IN ('pendiente','enviado') AND n.created_at>=? LIMIT 1", (oid, since)).fetchone())
        except Exception:
            return False
    return False


def skip_reason(c, oid, new, source, now, notify=True):
    """Motivo por el que NO se avisa al cliente de este cambio ('' si corresponde avisar). 1.5.259: el aviso debe ser verdadero y útil:
    sin presupuesto realmente pendiente o sin pedido de repuesto activo no se avisa, y no se envían dos correos seguidos."""
    if not notify:
        return 'El personal eligió no avisar al cliente en este cambio.'
    if source == 'quote_sent':
        return 'El cliente recibe el presupuesto con su enlace de aprobación; no se envía otro aviso.'
    if new == 'presupuesto':
        quote = c.execute("SELECT status,sent_at FROM quotes WHERE order_id=? AND deleted_at='' AND status NOT IN ('borrador','cancelado') ORDER BY version DESC,id DESC LIMIT 1",
                          (oid,)).fetchone()
        if not quote or quote['status'] != 'enviado':
            return 'No hay un presupuesto enviado pendiente de aprobación: el aviso no sería cierto.'
        try:
            fresh = (now - datetime.fromisoformat(quote['sent_at'])).total_seconds() < REPEAT_HOURS * 3600
        except (TypeError, ValueError):
            fresh = False
        if fresh:
            return 'El cliente recibió el presupuesto con su enlace hace menos de %d horas.' % REPEAT_HOURS
    if new == 'esperando_repuesto' and not waiting_parts(c, oid):
        return 'No hay un pedido de repuesto activo: el aviso no sería cierto.'
    since = (now - timedelta(minutes=QUIET_MINUTES)).isoformat(timespec='seconds')
    if c.execute("SELECT 1 FROM order_status_notices WHERE order_id=? AND status IN ('pendiente','enviado') AND created_at>=? LIMIT 1", (oid, since)).fetchone():
        return 'Hubo otro aviso al cliente hace menos de %d minutos: se evita un correo seguido. Si hace falta, envíalo desde «Comunicación».' % QUIET_MINUTES
    if _recent(c, oid, new, now):
        return 'Ya se avisó al cliente de este estado en las últimas %d horas.' % REPEAT_HOURS
    return ''


def emit(c, oid, lid, new, source, now, notify=True):
    """Registra los avisos de un cambio relevante (uno por canal). Devuelve los id pendientes de enviar."""
    if new not in NOTICE or not enabled(c):
        return []
    import part_notices
    skip_all = skip_reason(c, oid, new, source, now, notify)
    out = []
    for channel, _recipient, skip in part_notices._channels(c, oid):
        reason = skip_all or skip
        cur = c.execute('INSERT INTO order_status_notices(order_id,log_id,event,channel,status,detail,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?) '
                        'ON CONFLICT(log_id,channel) DO NOTHING', (oid, lid, new, channel, 'omitido' if reason else 'pendiente', reason, stamp(now), stamp(now)))
        if cur.rowcount and not reason:
            out.append(cur.lastrowid)
    return out


def text_for(c, oid, event):
    import part_notices
    import order_tracking
    who = part_notices._client(c, oid)
    subject, body = NOTICE[event]
    link = order_tracking.active(c, oid)['url']
    text = '\n\n'.join(filter(None, [part_notices.GREETING, body, 'Orden de servicio: %s.' % who['code'],
                                     'Puede consultar el avance en el seguimiento de su orden: ' + link if link else '', part_notices.CLOSING]))
    return 'PC-DOCTOR · Orden %s · %s' % (who['code'], subject), text


def deliver(c, ids, now, send_mail):
    """Envía los avisos indicados. `send_mail(c, oid, to, subject, body)` lanza si falla. Cada intento queda en la comunicación de la orden."""
    import mail_pro
    import order_followups
    import part_notices
    sent = []
    for nid in ids:
        n = c.execute('SELECT * FROM order_status_notices WHERE id=?', (nid,)).fetchone()
        if not n or n['status'] not in ('pendiente', 'fallido') or n['attempts'] >= MAX_ATTEMPTS:
            continue
        subject, body = text_for(c, n['order_id'], n['event'])
        channel = dict((ch, (rec, skip)) for ch, rec, skip in part_notices._channels(c, n['order_id']))[n['channel']]
        if channel[1]:
            c.execute("UPDATE order_status_notices SET status='omitido',detail=?,updated_at=? WHERE id=?", (channel[1], stamp(now), nid))
            continue
        key = 'status-notice-%d' % nid
        data = {'channel': 'correo', 'body': body, 'subject': subject, 'template': 'estado', 'request_key': key}
        try:
            if n['channel'] == 'correo':
                existing = c.execute('SELECT id FROM order_messages WHERE request_key=?', (key,)).fetchone()
                try:
                    send_mail(c, n['order_id'], channel[0], subject, body)
                    message = order_followups.retry(c, existing['id'], 'enviado', '', '', now) if existing else \
                        order_followups.record(c, n['order_id'], data, None, now, 'enviado', recipient=channel[0])[0]
                except mail_pro.MailError as error:
                    message = order_followups.retry(c, existing['id'], 'error', '', str(error), now) if existing else \
                        order_followups.record(c, n['order_id'], data, None, now, 'error', error=str(error), recipient=channel[0])[0]
            else:
                message, _ = order_followups.send_whatsapp(c, n['order_id'], {'mode': 'template', 'request_key': key, 'recipient': channel[0], 'body': body}, None, now)
        except order_followups.FollowupError as error:
            c.execute("UPDATE order_status_notices SET status='fallido',detail=?,attempts=attempts+1,updated_at=? WHERE id=?", (str(error)[:300], stamp(now), nid))
            continue
        ok = message['status'] in ('enviado', 'entregado', 'leido')
        c.execute('UPDATE order_status_notices SET status=?,detail=?,attempts=attempts+1,message_id=?,updated_at=? WHERE id=?',
                  ('enviado' if ok else 'fallido', ('Aceptado por el servidor de correo.' if n['channel'] == 'correo' else 'Aceptado por WhatsApp Business.') if ok
                   else (message.get('error') or 'No se pudo enviar.')[:300], message['id'], stamp(now), nid))
        if ok:
            sent.append(nid)
    return sent


def pending_ids(c, oid=None):
    """Avisos por enviar: pendientes y fallidos con intentos disponibles (de una orden o de todas)."""
    sql = "SELECT id FROM order_status_notices WHERE (status='pendiente' OR (status='fallido' AND attempts<?))" + (' AND order_id=?' if oid else '') + ' ORDER BY id'
    return [r[0] for r in c.execute(sql, (MAX_ATTEMPTS, oid) if oid else (MAX_ATTEMPTS,))]


# ---- Lectura: auditoría, línea de tiempo y vista pública --------------------------------------------------------------------------------
def audit(c, oid, limit=60):
    """Cambios de estado auditados de la orden (más reciente primero) con sus avisos y resultados."""
    rows = [dict(r) for r in c.execute("SELECT l.*,COALESCE(u.name,'') actor FROM order_status_log l LEFT JOIN users u ON u.id=l.actor_id WHERE l.order_id=? "
                                       'ORDER BY l.id DESC LIMIT ?', (oid, limit))]
    notices = {}
    for n in c.execute('SELECT log_id,event,channel,status,detail,attempts,updated_at FROM order_status_notices WHERE order_id=? ORDER BY id', (oid,)):
        notices.setdefault(n['log_id'], []).append(dict(n))
    for r in rows:
        r.update(from_label=LABELS.get(r['from_status'], r['from_status']), to_label=LABELS.get(r['to_status'], r['to_status']),
                 source_label=SOURCES.get(r['source'], r['source']), automatic=r['source'] not in ('manual', 'edicion'), notices=notices.get(r['id'], []),
                 notifies=r['to_status'] in NOTICE)
    return rows


def _iso(value):
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        from reception import ECUADOR_TZ
        return datetime.fromtimestamp(value, ECUADOR_TZ).isoformat(timespec='seconds')
    return str(value)


def timeline(c, oid, limit=12):
    """Cambios de estado de la orden, del más antiguo al más reciente, con etiquetas actuales (también los anteriores a 1.5.257).
    Sin comentarios ni notas: sirve igual para el panel y para el cliente."""
    labels = {r[0]: r[1] for r in c.execute('SELECT code,label FROM statuses')}
    o = c.execute('SELECT received_at,created_at FROM orders WHERE id=?', (oid,)).fetchone()
    if not o:
        return []
    out = [{'code': 'pendiente', 'label': 'Equipo recibido', 'at': _iso(o['received_at']) or _iso(o['created_at'])}]
    last = 'pendiente'
    for h in c.execute("SELECT occurred_at,event,status_label FROM order_history WHERE order_id=? AND event IN ('status','migration') ORDER BY occurred_at,id", (oid,)):
        code = code_for_label(h['status_label'], labels)
        if not code or code == last:
            continue
        out.append({'code': code, 'label': LABELS.get(code, h['status_label']), 'at': h['occurred_at']})
        last = code
    for item in out:
        item.update(icon=STATUS.get(item['code'], STATUS['pendiente'])[2], tone=STATUS.get(item['code'], STATUS['pendiente'])[3])
    return out[-limit:]


def public(c, oid):
    """Lo que ve el cliente: estado, explicación, tipo, última actualización, fecha estimada SOLO si está confirmada e historial de estados."""
    o = c.execute('SELECT status,updated_at,estimated_delivery,COALESCE(estimated_confirmed,0) confirmed FROM orders WHERE id=?', (oid,)).fetchone()
    if not o:
        return None
    meta = STATUS.get(o['status'], STATUS['pendiente'])
    estimated = o['estimated_delivery'] if o['confirmed'] and o['estimated_delivery'] and o['status'] != 'entregado' else ''
    action = {'presupuesto': 'Revise y apruebe el presupuesto para que podamos continuar.', 'esperando_cliente': 'Comuníquese con nosotros para continuar con el servicio.'}.get(o['status'], '')
    return {'code': o['status'], 'label': LABELS.get(o['status'], o['status']), 'kind': meta[1], 'kind_label': KIND_LABEL[meta[1]], 'icon': meta[2], 'tone': meta[3],
            'text': meta[5], 'action': action, 'updated': o['updated_at'] or '', 'estimated': estimated, 'history': timeline(c, oid)}


def suggestions(c, oid):
    """Siguientes pasos habituales para el panel (solo sugerencias: el técnico decide)."""
    row = c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()
    if not row:
        return []
    nxt = {'pendiente': ('diagnostico',), 'diagnostico': ('presupuesto', 'reparacion'), 'reparacion': ('pruebas',), 'presupuesto': (), 'esperando_cliente': (),
           'esperando_repuesto': ('reparacion',), 'revision_recurrente': ('reparacion', 'pruebas'), 'pruebas': ('listo', 'reparacion'), 'espera_entrega': ('entregado',),
           'listo': ('entregado', 'espera_entrega'), 'entregado': ()}
    return list(nxt.get(row['status'], ()))

