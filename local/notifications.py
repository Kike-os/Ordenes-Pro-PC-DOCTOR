"""Notificaciones del panel: se derivan de datos reales y su lectura se guarda por usuario."""
import json
import re
import appointments
import versioning

KEY = re.compile(r'[a-z]+:[A-Za-z0-9_.:\-]{1,80}')
EVENTS = {'created': ('order', 'info', 'Nueva orden registrada'), 'status': ('status', 'info', 'Cambio de estado'),
          'maintenance': ('maintenance', 'info', 'Mantenimiento'), 'follow_up': ('note', 'info', 'Seguimiento')}


def plural(count, one, many):
    return ('1 ' + one) if count == 1 else (str(count) + ' ' + many)


def build(c, user, now):
    """Lista ordenada de la más reciente a la más antigua. Solo incluye lo que este usuario puede ver."""
    today = now.date().isoformat()
    stamp = now.isoformat(timespec='seconds')
    staff = user['role'] in ('administrador', 'tecnico')
    admin = user['role'] == 'administrador'
    items = []

    def alert(name, count, icon, kind, title, detail, href):
        # La clave incluye el día y la cantidad: si la situación cambia, vuelve a aparecer como no leída.
        if count:
            items.append({'key': f'alert:{name}:{today}:{count}', 'kind': kind, 'icon': icon, 'title': title, 'detail': detail, 'at': stamp, 'href': href, 'group': 'alert'})

    try:
        installed = versioning.load()['releases'][0]
        changes = sum(len(values) for values in installed['changes'].values())
        items.append({'key': 'version:' + installed['version'], 'kind': 'success', 'icon': 'status', 'title': 'Órdenes Pro se actualizó a v' + installed['version'],
                      'detail': plural(changes, 'cambio registrado', 'cambios registrados') + '. Abre «Sistema» para ver las novedades.', 'at': installed['date'], 'href': '#system', 'group': 'system'})
        row = c.execute("SELECT value FROM system_state WHERE key='available_update'").fetchone()
        if row:
            update = json.loads(row['value'])
            if versioning.parse(update['version']) > versioning.parse(installed['version']):
                items.append({'key': 'update:' + update['version'], 'kind': 'warning', 'icon': 'status', 'title': 'Nueva actualización disponible: v' + update['version'],
                              'detail': (update.get('summary') or 'Hay una versión publicada posterior a la instalada.')[:160], 'at': update['date'], 'href': '#system', 'group': 'alert'})
    except (versioning.RegistryError, IndexError, ValueError, KeyError):
        pass
    if staff:
        count = lambda sql, *args: c.execute(sql, args).fetchone()[0]
        alert('overdue', count("SELECT COUNT(*) FROM orders WHERE estimated_delivery!='' AND estimated_delivery<? AND status!='entregado'", today), 'alert', 'warning',
              plural(count("SELECT COUNT(*) FROM orders WHERE estimated_delivery!='' AND estimated_delivery<? AND status!='entregado'", today), 'orden con entrega vencida', 'órdenes con entrega vencida'), 'La fecha estimada de entrega ya pasó.', '#orders?active=1')
        waiting = count("SELECT COUNT(*) FROM orders WHERE status IN ('esperando_cliente','presupuesto')")
        alert('waiting', waiting, 'message', 'warning', plural(waiting, 'orden espera respuesta o aprobación', 'órdenes esperan respuesta o aprobación'), 'Pendientes de la decisión del cliente.', '#orders?active=1')
        ready = count("SELECT COUNT(*) FROM orders WHERE status IN ('listo','espera_entrega')")
        alert('ready', ready, 'ready', 'warning', plural(ready, 'equipo pendiente de entrega', 'equipos pendientes de entrega'), 'Coordina el retiro o la entrega.', '#orders?active=1')
        start = appointments.stamp(appointments.datetime.combine(now.date(), appointments.time.min, appointments.TZ))
        end = appointments.stamp(appointments.datetime.combine(now.date() + appointments.timedelta(days=1), appointments.time.min, appointments.TZ))
        todays = count("SELECT COUNT(*) FROM appointments WHERE starts_at>=? AND starts_at<? AND status IN ('solicitada','confirmada','reprogramada')", start, end)
        alert('today', todays, 'calendar', 'info', plural(todays, 'cita programada para hoy', 'citas programadas para hoy'), 'Revisa la agenda del día.', '#appointments')
        requested = count("SELECT COUNT(*) FROM appointments WHERE status='solicitada' AND starts_at>=?", appointments.stamp(now))
        alert('requested', requested, 'calendar', 'warning', plural(requested, 'cita por confirmar', 'citas por confirmar'), 'Solicitudes recibidas desde la agenda en línea.', '#appointments')
        for row in c.execute("SELECT id,public_code,customer_name,starts_at,created_at FROM appointments WHERE status IN ('solicitada','confirmada') ORDER BY id DESC LIMIT 5"):
            items.append({'key': 'appointment:' + str(row['id']), 'kind': 'info', 'icon': 'calendar', 'title': 'Nueva cita reservada · ' + row['public_code'],
                          'detail': row['customer_name'] + ' · ' + row['starts_at'][:16].replace('T', ' '), 'at': row['created_at'], 'href': '#appointments', 'group': 'event'})
    if admin:
        chats = c.execute("SELECT COALESCE(SUM(last_seen_admin='' AND EXISTS(SELECT 1 FROM adi_messages m WHERE m.conversation_id=ac.id AND m.author='client')),0) FROM adi_conversations ac").fetchone()[0]
        alert('chats', chats, 'support', 'info', plural(chats, 'conversación nueva', 'conversaciones nuevas'), 'Clientes que esperan atención en vivo.', '#live')
        accounts = c.execute("SELECT COUNT(*) FROM users WHERE approval='pending'").fetchone()[0]
        alert('accounts', accounts, 'client', 'warning', plural(accounts, 'solicitud de cuenta por revisar', 'solicitudes de cuenta por revisar'), 'Aprueba o rechaza el acceso en Configuración.', '#settings')
    if staff:
        for row in c.execute('SELECT h.id,h.order_id,h.event,h.status_label,h.comment,h.occurred_at,o.code,u.name actor FROM order_history h JOIN orders o ON o.id=h.order_id LEFT JOIN users u ON u.id=h.actor_id WHERE h.actor_id IS NULL OR h.actor_id!=? ORDER BY h.id DESC LIMIT 25', (user['id'],)):
            icon, kind, label = EVENTS.get(row['event'], ('note', 'info', 'Seguimiento'))
            text = row['status_label'] if row['event'] == 'status' else '' if row['event'] == 'created' else (row['comment'] or row['status_label'])
            items.append({'key': 'event:' + str(row['id']), 'kind': kind, 'icon': icon, 'title': row['code'] + ' · ' + label,
                          'detail': ' · '.join(part for part in (text, row['actor']) if part), 'at': row['occurred_at'], 'href': '#orders?id=' + str(row['order_id']), 'group': 'event'})
    read = {row['key'] for row in c.execute('SELECT key FROM notification_reads WHERE user_id=?', (user['id'],))}
    for item in items:
        item['read'] = item['key'] in read
    items.sort(key=lambda item: (item['group'] != 'alert', ), reverse=False)
    alerts = [item for item in items if item['group'] == 'alert']
    rest = sorted((item for item in items if item['group'] != 'alert'), key=lambda item: item['at'], reverse=True)
    ordered = alerts + rest
    return {'items': ordered[:40], 'unread': sum(1 for item in ordered[:40] if not item['read'])}


def mark(c, user, keys, now):
    """Marca como leídas solo claves que hoy pertenecen a las notificaciones de este usuario."""
    valid = {item['key'] for item in build(c, user, now)['items']}
    chosen = valid if keys is None else {key for key in keys if KEY.fullmatch(key) and key in valid}
    for key in chosen:
        c.execute('INSERT OR IGNORE INTO notification_reads(user_id,key,read_at) VALUES (?,?,?)', (user['id'], key, now.isoformat(timespec='seconds')))
    c.execute("DELETE FROM notification_reads WHERE user_id=? AND read_at<?", (user['id'], (now - appointments.timedelta(days=120)).isoformat(timespec='seconds')))
    return len(chosen)
