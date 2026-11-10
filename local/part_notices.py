"""Avisos automáticos al cliente sobre sus repuestos, solo ante eventos reales y relevantes.

- Eventos: pedido confirmado, despachado, llegada a Ecuador, ingreso y liberación de aduana, recibido en PC-DOCTOR, listo para entrega,
  retraso importante, solicitud de cancelación recibida, cancelación aprobada o rechazada y reembolso registrado. Los pasos internos menores
  (preparación, cambios de datos, tránsito nacional) no generan avisos.
- Un aviso por evento y canal: la clave única (repuesto + evento + canal) impide duplicados por reintentos o dobles clics.
- Canales: correo (si el cliente tiene un correo válido y no pidió dejar de recibir correos) y WhatsApp Business (solo si está configurado
  con una plantilla aprobada y el cliente tiene un celular válido). Sin canal disponible, el aviso queda «omitido» con el motivo.
- «enviado» significa aceptado por el servidor de correo o por WhatsApp Business, nunca «entregado»: la entrega y la lectura llegan solo por
  el aviso del proveedor (order_messages). Cada envío queda además en la comunicación de la orden.
- Reintento controlado: un aviso fallido se reintenta (botón «Reintentar» o tarea diaria) hasta 3 intentos, con el mismo texto.
- Administración puede apagar los avisos automáticos (Pedidos de repuestos → Avisos al cliente); apagados, no se genera ninguno.
- Los textos nunca incluyen proveedor, transportista, guía, costos ni notas internas."""
import re

import order_followups
import order_part_requests as parts
from order_part_requests import stamp

MAX_ATTEMPTS = 3
SETTING = 'part_notices_auto'
GREETING = 'Estimado/a cliente:'
CLOSING = 'Gracias por confiar en PC-DOCTOR.\n\nAtentamente,\nPC-DOCTOR | Servicio Técnico Especializado.'
# Evento → (asunto, texto). {part} es el nombre público del repuesto.
EVENTS = {
    'confirmado': ('Pedido de repuesto confirmado', 'Le informamos que el pedido del repuesto {part} para su orden fue confirmado. Continuaremos informándole sobre su proceso de entrega.'),
    'despachado': ('Repuesto despachado', 'El repuesto {part} fue despachado y se encuentra en camino hacia PC-DOCTOR.'),
    'llegada_pais': ('Repuesto en Ecuador', 'El repuesto {part} llegó a Ecuador y continuará con su proceso de importación.'),
    'aduana_revision': ('Repuesto en proceso de aduana', 'El repuesto {part} ingresó al proceso de aduana en Ecuador. Le informaremos cuando sea liberado.'),
    'aduana_liberado': ('Repuesto liberado de aduana', 'El repuesto {part} fue liberado de aduana y continúa su traslado hacia Otavalo.'),
    'recibido': ('Repuesto recibido en PC-DOCTOR', 'Nos complace informarle que el repuesto {part} llegó a nuestro taller. Procederemos con su instalación y las pruebas correspondientes.'),
    'listo': ('Equipo listo para entrega', 'Los trabajos con el repuesto {part} finalizaron y su equipo se encuentra listo para entrega, sujeto a las condiciones de retiro de su orden.'),
    'retraso': ('Retraso en la llegada del repuesto', 'La llegada del repuesto {part} presenta un retraso. Le informaremos la nueva fecha estimada en cuanto esté confirmada.'),
    'cancelacion_solicitada': ('Solicitud de cancelación recibida', 'PC-DOCTOR confirma la recepción de su solicitud de cancelación del repuesto {part} asociado a su orden.\n\n'
                               'Nuestro departamento administrativo revisará el estado del pedido y las condiciones correspondientes.\n\nLe notificaremos el resultado de su solicitud.'),
    'cancelacion_aprobada': ('Cancelación aprobada', 'Le informamos que la cancelación de su pedido del repuesto {part} ha sido aprobada.\n\nEl pedido ha sido actualizado en nuestro sistema.\n\n'
                             'En caso de existir pagos anticipados, nuestro departamento administrativo le comunicará el procedimiento correspondiente.'),
    'cancelacion_rechazada': ('Solicitud de cancelación revisada', 'Su solicitud de cancelación del repuesto {part} fue revisada y no pudo aprobarse. Nuestro personal se comunicará con usted para explicarle el motivo y las alternativas.'),
    'reembolso': ('Reembolso registrado', 'Le informamos que se registró un reembolso relacionado con la cancelación del repuesto {part}. Ante cualquier consulta, comuníquese con nuestro departamento administrativo.'),
}
LABELS = {k: v[0] for k, v in EVENTS.items()}
STAGE_EVENTS = ('confirmado', 'despachado', 'llegada_pais', 'aduana_revision', 'aduana_liberado', 'recibido', 'listo')
ALWAYS = ('cancelacion_solicitada', 'cancelacion_aprobada', 'cancelacion_rechazada', 'reembolso')  # se avisan aunque el repuesto esté oculto en el enlace


def enabled(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (SETTING,)).fetchone()
    return not (row and row['value'] == 'off')


def set_enabled(c, on, user):
    if user['role'] != 'administrador':
        raise parts.PartError('Solo administración cambia este ajuste.', 403)
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SETTING, 'on' if on else 'off'))


def _client(c, oid):
    return c.execute("SELECT o.code,COALESCE(cl.email,'') email,COALESCE(cl.phone,'') phone FROM orders o JOIN devices d ON d.id=o.device_id "
                     'JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (oid,)).fetchone()


def _channels(c, oid):
    """(canal, destinatario, motivo de omisión) para cada canal, según los datos y preferencias reales del cliente."""
    import mail_pro
    who = _client(c, oid)
    email = who['email'].strip().lower()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(\.[^\s@<>.]+)+', email):
        mail = (email, 'El cliente no tiene un correo válido registrado.')
    elif c.execute('SELECT 1 FROM mail_optouts WHERE lower(email)=?', (email,)).fetchone():
        mail = (email, 'El cliente pidió no recibir correos.')
    else:
        try:
            ready = mail_pro.configured()
        except mail_pro.MailError:
            ready = False
        mail = (email, '' if ready else 'El correo del sistema no está configurado.')
    # 1.5.275: WhatsApp Business tiene su propia cola (whatsapp_business), con autorización del cliente, plantillas por evento y estados de
    # entrega; aquí queda solo el correo, con las mismas reglas de siempre.
    return (('correo',) + mail,)


def emit(c, row, event, key, now):
    """Registra los avisos de un evento (uno por canal; repetido, no crea otro). Devuelve los id pendientes de enviar."""
    if event not in EVENTS:
        return []
    if not row['public_visible'] and event not in ALWAYS:
        return []
    try:  # WhatsApp: cola y ajustes propios (no depende del interruptor del correo) y nunca impide el aviso por correo
        import whatsapp_business
        whatsapp_business.on_part(c, row, event, key, now)
    except Exception as error:
        print('whatsapp-part', type(error).__name__, flush=True)
    if not enabled(c):
        return []
    out = []
    for channel, recipient, skip in _channels(c, row['order_id']):
        cur = c.execute("INSERT INTO order_part_notices(request_id,event_key,event,channel,status,detail,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?) "
                        'ON CONFLICT(request_id,event_key,channel) DO NOTHING', (row['id'], key, event, channel, 'omitido' if skip else 'pendiente', skip, stamp(now), stamp(now)))
        if cur.rowcount and not skip:
            out.append(cur.lastrowid)
    return out


def text_for(c, row, event):
    terms = parts.private_terms(c, row)
    name = parts._scrub(row['name'], terms) or 'solicitado'
    who = _client(c, row['order_id'])
    subject, body = EVENTS[event]
    import order_tracking
    link = order_tracking.active(c, row['order_id'])['url']
    text = '\n\n'.join(filter(None, [GREETING, body.format(part='«%s»' % name), 'Orden de servicio: %s.' % who['code'],
                                     'Puede consultar el avance en el seguimiento de su orden: ' + link if link else '', CLOSING]))
    return 'PC-DOCTOR · Orden %s · %s' % (who['code'], subject), text


def deliver(c, ids, now, send_mail):
    """Envía los avisos indicados (pendientes o fallidos con intentos disponibles). `send_mail(c, oid, to, subject, body)` lanza si falla.
    Cada intento queda en order_messages (comunicación de la orden) con su estado real."""
    import mail_pro
    sent = []
    for nid in ids:
        n = c.execute('SELECT * FROM order_part_notices WHERE id=?', (nid,)).fetchone()
        if not n or n['status'] not in ('pendiente', 'fallido') or n['attempts'] >= MAX_ATTEMPTS:
            continue
        row = c.execute('SELECT * FROM order_part_requests WHERE id=?', (n['request_id'],)).fetchone()
        subject, body = text_for(c, row, n['event'])
        channel = dict((ch, (rec, skip)) for ch, rec, skip in _channels(c, row['order_id'])).get(n['channel'])
        if channel is None:  # avisos de WhatsApp anteriores a 1.5.275: ahora van por la cola de WhatsApp Business
            continue
        if channel[1]:
            c.execute("UPDATE order_part_notices SET status='omitido',detail=?,updated_at=? WHERE id=?", (channel[1], stamp(now), nid))
            continue
        key = 'part-notice-%d' % nid
        try:
            if n['channel'] == 'correo':
                existing = c.execute('SELECT id FROM order_messages WHERE request_key=?', (key,)).fetchone()
                try:
                    send_mail(c, row['order_id'], channel[0], subject, body)
                    message = order_followups.retry(c, existing['id'], 'enviado', '', '', now) if existing else \
                        order_followups.record(c, row['order_id'], {'channel': 'correo', 'body': body, 'subject': subject, 'template': 'repuesto', 'request_key': key}, None, now, 'enviado',
                                               recipient=channel[0])[0]
                except mail_pro.MailError as error:
                    message = order_followups.retry(c, existing['id'], 'error', '', str(error), now) if existing else \
                        order_followups.record(c, row['order_id'], {'channel': 'correo', 'body': body, 'subject': subject, 'template': 'repuesto', 'request_key': key}, None, now, 'error',
                                               error=str(error), recipient=channel[0])[0]
            else:
                # Fuera de la ventana de 24 h Meta solo acepta plantillas aprobadas: se envía la plantilla con el nombre y el número de orden.
                message, _ = order_followups.send_whatsapp(c, row['order_id'], {'mode': 'template', 'request_key': key, 'recipient': channel[0], 'body': body}, None, now)
        except order_followups.FollowupError as error:
            c.execute("UPDATE order_part_notices SET status='fallido',detail=?,attempts=attempts+1,updated_at=? WHERE id=?", (str(error)[:300], stamp(now), nid))
            continue
        ok = message['status'] in ('enviado', 'entregado', 'leido')
        c.execute('UPDATE order_part_notices SET status=?,detail=?,attempts=attempts+1,message_id=?,updated_at=? WHERE id=?',
                  ('enviado' if ok else 'fallido', ('Aceptado por el servidor de correo.' if n['channel'] == 'correo' else 'Aceptado por WhatsApp Business.') if ok
                   else (message.get('error') or 'No se pudo enviar.')[:300], message['id'], stamp(now), nid))
        parts_log(c, row['id'], n, ok, now)
        if ok:
            sent.append(nid)
    return sent


def parts_log(c, rid, n, ok, now):
    import part_cancellations
    part_cancellations.log(c, rid, 'aviso', 'enviado' if ok else 'fallido', '%s · %s' % (LABELS[n['event']], 'correo' if n['channel'] == 'correo' else 'WhatsApp'),
                           'sistema', None, now, {'notice_id': n['id'], 'event': n['event'], 'channel': n['channel']})


def retry_failed(c, now, send_mail, request_id=None):
    """Reintento controlado: fallidos con intentos disponibles (de un repuesto o de todos)."""
    sql = "SELECT id FROM order_part_notices WHERE status='fallido' AND attempts<?" + (' AND request_id=?' if request_id else '')
    ids = [r[0] for r in c.execute(sql, (MAX_ATTEMPTS, request_id) if request_id else (MAX_ATTEMPTS,))]
    return deliver(c, ids, now, send_mail)


def listing(c, rid):
    return [dict(r, label=LABELS.get(r['event'], r['event'])) for r in c.execute('SELECT * FROM order_part_notices WHERE request_id=? ORDER BY id DESC', (rid,))]
