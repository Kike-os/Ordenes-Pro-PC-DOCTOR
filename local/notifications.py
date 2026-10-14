"""Notificaciones del panel: se derivan de datos reales y su lectura se guarda por usuario."""
import json
import re
import appointments
import versioning
import mail_pro

KEY = re.compile(r'[a-z]+:[A-Za-z0-9_.:\-]{1,80}')
EVENTS = {'created': ('order', 'info', 'Nueva orden registrada'), 'status': ('status', 'info', 'Cambio de estado'),
          'maintenance': ('maintenance', 'info', 'Mantenimiento'), 'follow_up': ('note', 'info', 'Seguimiento')}


def plural(count, one, many):
    return ('1 ' + one) if count == 1 else (str(count) + ' ' + many)


def _state(c, key):
    row = c.execute("SELECT value FROM system_state WHERE key=?", (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else None
    except ValueError:
        return None


def _save(c, key, value):
    try:
        c.execute("INSERT INTO system_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
    except Exception:
        pass


def mail_events(c):
    return _state(c, 'mail_events') or []


def mail_status(c, now, max_age=60):
    """Estado de la bandeja de entrada (no leídos, cuota y correos nuevos); consulta al servidor como mucho una vez por minuto.

    Los correos nuevos se reconocen por su UID de IMAP, que es persistente: la primera consulta solo fija el punto de
    partida y no anuncia los mensajes que ya existían, y un mismo mensaje nunca se registra dos veces.
    """
    cached = _state(c, 'mail_inbox')
    if cached and now.timestamp() - cached.get('ts', 0) < max_age:
        return cached
    try:
        client = mail_pro.open_imap()
    except mail_pro.MailError as error:
        # Se anota el fallo para no reintentar la conexión en cada consulta de notificaciones.
        _save(c, 'mail_inbox', dict(cached or {}, ts=now.timestamp(), error=str(error)))
        raise
    try:
        inbox = next((item for item in mail_pro.overview(client) if item['role'] == 'inbox'), None)
        if not inbox:
            return None
        top, last = inbox['uidnext'] - 1, (cached or {}).get('last_uid')
        if last is not None and (cached or {}).get('uidvalidity') == inbox['uidvalidity'] and top > last:
            events, known = mail_events(c), {(item['uidvalidity'], item['uid']) for item in mail_events(c)}
            fresh = mail_pro.newer(client, last)
            # Informes de entrega (devoluciones y retrasos): se analizan por su estructura y se registran una sola vez.
            reports = [row['uid'] for row in fresh if row.get('report')]
            if reports:
                bounces, seen_bounces = _state(c, 'mail_bounces') or [], {(item['uidvalidity'], item['uid']) for item in (_state(c, 'mail_bounces') or [])}
                import mail_tracking
                for bounce in mail_pro.find_bounces(client, reports):
                    if (inbox['uidvalidity'], bounce['uid']) in seen_bounces:
                        continue
                    # Informe de un envío registrado: actualiza su seguimiento (una sola vez por informe y destinatario).
                    try:
                        if mail_tracking.from_report(c, bounce, 'dsn:' + str(inbox['uidvalidity']) + ':' + str(bounce['uid']), now):
                            seen_bounces.add((inbox['uidvalidity'], bounce['uid']))
                            bounces.append({'uidvalidity': inbox['uidvalidity'], 'uid': bounce['uid'], 'tracked': True, 'at': now.isoformat(timespec='seconds')})
                            continue
                    except Exception as error:
                        print('mail-tracking informe', type(error).__name__, flush=True)
                    if bounce['action'] not in ('failed', 'delayed'):
                        continue
                    try:
                        sent = c.execute("SELECT 1 FROM mail_outbox WHERE message_id=? AND status='sent'", (bounce['original_id'],)).fetchone() if bounce['original_id'] else None
                    except Exception:
                        sent = None
                    bounces.append({'uidvalidity': inbox['uidvalidity'], 'uid': bounce['uid'], 'recipient': bounce['recipient'], 'permanent': bounce['permanent'], 'action': bounce['action'], 'status': bounce['status'],
                                    'reason': bounce['reason'], 'matched': bool(sent), 'at': now.isoformat(timespec='seconds')})
                _save(c, 'mail_bounces', bounces[-30:])
            for row in reversed(fresh):
                if row['seen'] or row.get('report') or (inbox['uidvalidity'], row['uid']) in known:
                    continue
                sender = (row['from'] or [{}])[0]
                events.append({'uidvalidity': inbox['uidvalidity'], 'uid': row['uid'], 'from': (sender.get('name') or sender.get('address') or 'Remitente desconocido')[:120],
                               'subject': row['subject'][:200], 'date': row['date'], 'at': now.isoformat(timespec='seconds')})
            _save(c, 'mail_events', events[-30:])
        state = {'unread': inbox['unread'], 'total': inbox['total'], 'uidnext': inbox['uidnext'], 'uidvalidity': inbox['uidvalidity'], 'last_uid': top, 'quota': mail_pro.quota(client),
                 'account': mail_pro.settings()['username'], 'checked': now.isoformat(timespec='seconds'), 'ts': now.timestamp()}
    finally:
        mail_pro.close_imap(client)
    _save(c, 'mail_inbox', state)
    return state


def mail_storage(c, now, max_age=60):
    """Almacenamiento real del buzón: cPanel UAPI si está configurado y, si no, la cuota que informa el servidor IMAP.

    Devuelve siempre un estado explicado (ok, ilimitado, permisos, error) y conserva la última lectura válida, marcada
    como desactualizada, cuando la consulta falla. Nunca calcula ni estima valores.
    """
    import cpanel
    cached = _state(c, 'mail_storage')
    if cached and now.timestamp() - cached.get('ts', 0) < max_age:
        return cached
    address, notes, usage, source = mail_pro.settings()['username'], [], None, ''
    cpanel_state = 'sin_configurar'
    if cpanel.configured():
        try:
            usage, source, cpanel_state = cpanel.mailbox_usage(address), 'cPanel (UAPI)', 'ok'
        except cpanel.CpanelError as error:
            cpanel_state = error.kind
            notes.append('cPanel: ' + str(error))
            print('mail-storage uapi ' + error.kind, flush=True)
    if usage is None:
        try:
            client = mail_pro.open_imap()
            try:
                usage, reason = mail_pro.quota_detail(client)
            finally:
                mail_pro.close_imap(client)
            if usage is None:
                notes.append('IMAP: ' + reason)
                print('mail-storage imap sin datos: ' + reason, flush=True)
            else:
                source = 'servidor de correo (IMAP QUOTA)'
        except mail_pro.MailError as error:
            notes.append('IMAP: ' + str(error))
            print('mail-storage imap ' + error.kind, flush=True)
    stamp = now.isoformat(timespec='seconds')
    if usage is not None:
        result = {'state': 'ok' if usage['limit'] else 'unlimited', 'used': usage['used'], 'limit': usage['limit'], 'source': source, 'checked': stamp, 'ts': now.timestamp(), 'stale': False,
                  'cpanel': cpanel_state, 'detail': ' '.join(notes), 'good': {'used': usage['used'], 'limit': usage['limit'], 'source': source, 'checked': stamp, 'ts': now.timestamp()}}
    else:
        good = (cached or {}).get('good')
        state = 'permisos' if cpanel_state in ('autenticacion', 'permisos') else 'error'
        if good and now.timestamp() - good.get('ts', 0) < 86400:
            # Última lectura válida de las últimas 24 horas, identificada como desactualizada.
            result = {'state': 'ok' if good['limit'] else 'unlimited', 'used': good['used'], 'limit': good['limit'], 'source': good['source'], 'checked': good['checked'], 'ts': now.timestamp(), 'stale': True,
                      'cpanel': cpanel_state, 'detail': ' '.join(notes), 'good': good, 'failed': state}
        else:
            result = {'state': state, 'used': None, 'limit': None, 'source': '', 'checked': stamp, 'ts': now.timestamp(), 'stale': False, 'cpanel': cpanel_state, 'detail': ' '.join(notes) or 'No hay una fuente de almacenamiento disponible.', 'good': None}
    _save(c, 'mail_storage', result)
    return result


def quota_level(quota):
    """Porcentaje de ocupación real; None cuando no hay cuota configurada o el servidor no la informa."""
    if not quota or not quota.get('limit'):
        return None
    return min(100, round(quota['used'] * 100 / quota['limit']))


def build(c, user, now, mail_access=False):
    """Lista ordenada de la más reciente a la más antigua. Solo incluye lo que este usuario puede ver."""
    today = now.date().isoformat()
    stamp = now.isoformat(timespec='seconds')
    staff = user['role'] in ('administrador', 'tecnico')
    admin = user['role'] == 'administrador'
    items = []
    if admin:
        # ADI AutoCare Pro: incidencias, recuperaciones automáticas y versiones verificadas (solo administración).
        try:
            import autocare
            items += autocare.notifications(c, now)
        except Exception as error:
            print('autocare avisos', type(error).__name__, flush=True)

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
              plural(count("SELECT COUNT(*) FROM orders WHERE estimated_delivery!='' AND estimated_delivery<? AND status!='entregado'", today), 'orden con entrega vencida', 'órdenes con entrega vencida'), 'La fecha estimada de entrega ya pasó.', '#deliveries?estado=overdue')
        waiting = count("SELECT COUNT(*) FROM orders WHERE status IN ('esperando_cliente','presupuesto')")
        alert('waiting', waiting, 'message', 'warning', plural(waiting, 'orden espera respuesta o aprobación', 'órdenes esperan respuesta o aprobación'), 'Pendientes de la decisión del cliente.', '#orders?active=1')
        ready = count("SELECT COUNT(*) FROM orders WHERE status IN ('listo','espera_entrega')")
        # Un aviso por equipo que acaba de quedar listo (últimas 48 h); la clave incluye el cambio para no repetirse.
        for row in c.execute("SELECT o.id,o.code,o.updated_at,cl.name client,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.status='listo' ORDER BY o.updated_at DESC LIMIT 12"):
            try:fresh=(now-appointments.datetime.fromisoformat(row['updated_at'])).total_seconds()<172800
            except (ValueError,TypeError):fresh=False
            if fresh:items.append({'key':'ready:order:%d:%s'%(row['id'],row['updated_at'][:19]),'kind':'success','icon':'ready','title':'Equipo listo para entregar · '+row['code'],'detail':row['client']+' · '+(' '.join(x for x in (row['brand'],row['model']) if x) or 'equipo'),'at':row['updated_at'],'href':'#deliveries','action':'Ver entregas','sound':True,'group':'event'})
        alert('ready', ready, 'ready', 'warning', plural(ready, 'equipo pendiente de entrega', 'equipos pendientes de entrega'), 'Coordina el retiro o la entrega.', '#deliveries')
        # Presupuestos de las últimas 48 h: enviados (solo si el correo salió de verdad) y decididos. La aprobación no inicia ningún trabajo.
        try:
            import quotes as quotes_module
            recent = c.execute("SELECT q.id,q.code,q.status,q.updated_at,q.sent_at,q.decided_by,q.order_id,cl.name client FROM quotes q JOIN orders o ON o.id=q.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE q.deleted_at='' AND q.status IN ('enviado','aprobado','parcial','rechazado','modificacion') ORDER BY q.updated_at DESC LIMIT 15").fetchall()
        except Exception:
            recent = []
        for row in recent:
            moment = row['sent_at'] if row['status'] == 'enviado' else row['updated_at']
            try:fresh=(now-appointments.datetime.fromisoformat(moment)).total_seconds()<172800
            except (ValueError,TypeError):fresh=False
            if not fresh:
                continue
            by_client = str(row['decided_by'] or '') == 'cliente'
            if row['status'] == 'enviado':
                if quotes_module.mail_state(c, row['id']) != 'sent':
                    continue
                items.append({'key':'quote:%d:enviado:%s'%(row['id'],moment[:19]),'kind':'info','icon':'budget','title':'Presupuesto enviado · '+row['code'],'detail':'Esperando respuesta del cliente ('+row['client']+').','at':moment,'href':'#orders?id='+str(row['order_id']),'group':'event'})
                continue
            title={'aprobado':'Presupuesto aprobado '+('por el cliente' if by_client else '(registrado por el personal)'),'parcial':'Presupuesto aprobado parcialmente','rechazado':'Presupuesto rechazado '+('por el cliente' if by_client else '(registrado por el personal)'),'modificacion':'El cliente pide modificar el presupuesto'}[row['status']]
            note = quotes_module.client_note(c, row['id']) if row['status'] in ('rechazado','parcial','aprobado') else ''
            detail = row['client'] + ('. Motivo u observación: ' + note[:160] if note else '') + ('. No se autoriza ningún servicio.' if row['status'] == 'rechazado' else '. Revisa los servicios autorizados antes de iniciar trabajos.')
            items.append({'key':'quote:%d:%s:%s'%(row['id'],row['status'],row['updated_at'][:19]),'kind':'success' if row['status'] in ('aprobado','parcial') else 'warning','icon':'budget','title':title+' · '+row['code'],'detail':detail,'at':row['updated_at'],'href':'#orders?id='+str(row['order_id']),'group':'event'})
        start = appointments.stamp(appointments.datetime.combine(now.date(), appointments.time.min, appointments.TZ))
        end = appointments.stamp(appointments.datetime.combine(now.date() + appointments.timedelta(days=1), appointments.time.min, appointments.TZ))
        todays = count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND starts_at>=? AND starts_at<? AND status IN ('solicitada','confirmada','reprogramada')", start, end)
        alert('today', todays, 'calendar', 'info', plural(todays, 'cita programada para hoy', 'citas programadas para hoy'), 'Revisa la agenda del día.', '#appointments')
        requested = count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status='solicitada' AND starts_at>=?", appointments.stamp(now))
        alert('requested', requested, 'calendar', 'warning', plural(requested, 'cita por confirmar', 'citas por confirmar'), 'Solicitudes recibidas desde la agenda en línea.', '#appointments?estado=solicitada')
        # Una notificación por cita (clave única por id): cliente, servicio, fecha y hora, con acceso directo a la cita.
        for row in c.execute("SELECT a.id,a.public_code,a.customer_name,a.starts_at,a.created_at,a.status,s.label service FROM appointments a JOIN appointment_services s ON s.code=a.service_code WHERE a.deleted_at IS NULL AND a.status IN ('solicitada','confirmada') ORDER BY a.id DESC LIMIT 8"):
            when = appointments.datetime.fromisoformat(row['starts_at']).astimezone(appointments.TZ).strftime('%d/%m/%Y %H:%M')
            pending = row['status'] == 'solicitada'
            items.append({'key': 'appointment:' + str(row['id']), 'kind': 'warning' if pending else 'info', 'icon': 'calendar',
                          'title': ('Solicitud de cita por confirmar · ' if pending else 'Nueva cita registrada · ') + row['public_code'],
                          'detail': row['customer_name'] + ' · ' + row['service'] + ' · ' + when, 'at': row['created_at'],
                          'href': '#appointments?appointment=' + str(row['id']), 'action': 'Ver cita', 'sound': True, 'group': 'event'})
        # Mantenimientos preventivos: aviso de creación al entregar y recordatorios internos a 30, 15, 7 y 0 días.
        # Cada clave incluye mantenimiento, generación y umbral: se muestra una sola vez por plazo.
        for row in c.execute("SELECT m.id,m.order_id,m.generation,m.due_date,m.delivered_at,m.state,o.code,cl.name client,d.brand,d.model FROM maintenance m JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE m.state IN ('scheduled','appointment') ORDER BY m.due_date LIMIT 60"):
            device = ' '.join(x for x in (row['brand'], row['model']) if x) or 'equipo'
            days = (appointments.date.fromisoformat(row['due_date']) - now.date()).days
            delivered = appointments.datetime.fromisoformat(row['delivered_at'])
            if (now - delivered).total_seconds() < 172800:
                items.append({'key': 'maintenance:new:%d:%d' % (row['id'], row['generation']), 'kind': 'success', 'icon': 'maintenance', 'title': 'Próximo mantenimiento programado · ' + row['code'],
                              'detail': row['client'] + ' · ' + device + ' · previsto para ' + appointments.date.fromisoformat(row['due_date']).strftime('%d/%m/%Y'), 'at': row['delivered_at'], 'href': '#maintenance?order=' + str(row['order_id']), 'action': 'Ver mantenimiento', 'group': 'event'})
            threshold = next((limit for limit in (0, 7, 15, 30) if days <= limit), None)
            if threshold is not None and days >= -60:
                label = {0: 'Mantenimiento preventivo para hoy' if days == 0 else 'Mantenimiento preventivo vencido', 7: 'Mantenimiento preventivo en 7 días o menos', 15: 'Mantenimiento preventivo en 15 días o menos', 30: 'Mantenimiento preventivo en 30 días o menos'}[threshold]
                items.append({'key': 'maintenance:due:%d:%d:%d' % (row['id'], row['generation'], threshold), 'kind': 'warning' if threshold <= 7 else 'info', 'icon': 'maintenance', 'title': label + ' · ' + row['code'],
                              'detail': row['client'] + ' · ' + device + ' · ' + appointments.date.fromisoformat(row['due_date']).strftime('%d/%m/%Y'), 'at': stamp, 'href': '#maintenance', 'action': 'Ver mantenimiento', 'group': 'event'})
    if admin:
        # Protección de datos: dónde se guarda la información y si los respaldos de la base central están al día.
        import remote_db
        if not remote_db.configured():
            items.append({'key': 'storage:local', 'kind': 'warning', 'icon': 'status', 'title': 'Esta instalación usa una base de datos local', 'detail': 'Lo que registres aquí queda solo en este equipo, no en la base central en la nube.', 'at': stamp, 'href': '#system', 'group': 'alert'})
        else:
            try:
                last = _state(c, 'cloud_backup')
                age = (now - appointments.datetime.fromisoformat(last['at'])).total_seconds() if last and last.get('ok') else None
                if age is None or age > 48 * 3600:
                    items.append({'key': 'backup:late:' + today, 'kind': 'warning', 'icon': 'status', 'title': 'Respaldo de la base central atrasado', 'detail': ('El último respaldo correcto es del ' + last['at'][:10] + '.') if last and last.get('ok') else 'Todavía no se registra ningún respaldo correcto.', 'at': stamp, 'href': '#system', 'group': 'alert'})
            except Exception:
                pass
        chats = c.execute("SELECT COALESCE(SUM(last_seen_admin='' AND EXISTS(SELECT 1 FROM adi_messages m WHERE m.conversation_id=ac.id AND m.author='client')),0) FROM adi_conversations ac").fetchone()[0]
        alert('chats', chats, 'support', 'info', plural(chats, 'conversación nueva', 'conversaciones nuevas'), 'Clientes que esperan atención en vivo.', '#live')
        waiting = c.execute("SELECT COUNT(*) FROM adi_conversations WHERE mode='human' AND assigned_to IS NULL").fetchone()[0]
        alert('advisor', waiting, 'support', 'warning', plural(waiting, 'cliente espera a un asesor', 'clientes esperan a un asesor'), 'Solicitaron atención humana en el chat.', '#live')
        try:
            # Borrador de condiciones pendiente de aprobación: solo lo ve administración, que es quien publica.
            if user['role'] == 'administrador':
                pending = c.execute('SELECT updated_at FROM service_terms_draft WHERE id=1').fetchone()
                if pending:
                    items.append({'key': 'alert:terms-draft:' + pending['updated_at'], 'kind': 'warning', 'icon': 'doc', 'title': 'Borrador de condiciones pendiente de aprobación', 'detail': 'Revisa los cambios frente a la versión vigente y decide si se publican.', 'at': pending['updated_at'], 'href': '#settings?tab=terms', 'group': 'alert'})
        except Exception:
            pass
        try:
            import stay
            late = stay.overdue(c, now, stay.settings(c))
            alert('stay-overdue', len(late), 'order', 'warning', plural(len(late), 'equipo superó el plazo de permanencia', 'equipos superaron el plazo de permanencia'), 'Revisa las órdenes sin retirar: ' + ', '.join(item['code'] for item in late[:4]) + ('…' if len(late) > 4 else '') + '.', '#orders?stay=overdue')
        except Exception:
            pass
        try:
            answers = c.execute("SELECT COUNT(*) FROM maintenance_responses WHERE handled_at=''").fetchone()[0]
            alert('maintenance-answers', answers, 'support', 'info', plural(answers, 'respuesta de cliente sobre su mantenimiento', 'respuestas de clientes sobre su mantenimiento'), 'Confirmaciones o cambios de horario recibidos por enlace seguro.', '#maintenance')
        except Exception:
            pass
        accounts = c.execute("SELECT COUNT(*) FROM users WHERE approval='pending'").fetchone()[0]
        alert('accounts', accounts, 'client', 'warning', plural(accounts, 'solicitud de cuenta por revisar', 'solicitudes de cuenta por revisar'), 'Aprueba o rechaza el acceso en Configuración.', '#settings?tab=users')
    if mail_access:
        try:
            state = mail_status(c, now)
            if state and state.get('unread'):
                # Resumen silencioso: el aviso sonoro y emergente corresponde a cada correo nuevo, no al contador.
                items.append({'key': 'mail:' + str(state['uidnext']) + ':' + str(state['unread']), 'kind': 'info', 'icon': 'message', 'title': plural(state['unread'], 'correo sin leer', 'correos sin leer'),
                              'detail': 'Bandeja de entrada de ' + state['account'] + '.', 'at': state['checked'], 'href': '#mail', 'group': 'alert', 'quiet': True})
            storage = _state(c, 'mail_storage') or {}
            quota = {'used': storage['used'], 'limit': storage['limit']} if storage.get('used') is not None and not storage.get('stale') else (state or {}).get('quota')
            level = quota_level(quota)
            if level is not None and level >= 75:
                free = max(0, quota['limit'] - quota['used'])
                items.append({'key': 'mailquota:' + ('90' if level >= 90 else '75'), 'kind': 'warning', 'icon': 'message', 'title': 'Buzón de correo al ' + str(level) + ' % de su capacidad',
                              'detail': 'Quedan ' + (str(round(free / 1048576)) + ' MB' if free >= 1048576 else str(round(free / 1024)) + ' KB') + ' disponibles. No se elimina ningún correo automáticamente.', 'at': state['checked'], 'href': '#mail', 'group': 'alert'})
            try:
                import mail_tracking
                items += mail_tracking.alerts(c, now)
            except Exception as error:
                print('mail-tracking avisos', type(error).__name__, flush=True)
            for bounce in [item for item in (_state(c, 'mail_bounces') or []) if not item.get('tracked')][-8:]:
                items.append({'key': 'mail:bounce:' + str(bounce['uidvalidity']) + ':' + str(bounce['uid']), 'kind': 'error' if bounce['permanent'] else 'warning', 'icon': 'message',
                              'title': ('Correo devuelto · ' if bounce['permanent'] else 'Entrega retrasada · ') + bounce['recipient'], 'detail': bounce['reason'] + (' (' + bounce['status'] + ')' if bounce['status'] else '') + ('' if bounce['matched'] else ' No se pudo relacionar con un envío de esta aplicación.'),
                              'at': bounce['at'], 'href': '#mail?folder=INBOX&uid=' + str(bounce['uid']), 'group': 'event', 'bounce': True})
            for event in mail_events(c)[-10:]:
                items.append({'key': 'mail:new:' + str(event['uidvalidity']) + ':' + str(event['uid']), 'kind': 'info', 'icon': 'message', 'title': 'Correo nuevo · ' + event['from'], 'detail': event['subject'],
                              'at': event['at'], 'href': '#mail?folder=INBOX&uid=' + str(event['uid']), 'group': 'event', 'mail': True})
        except Exception:
            pass
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
    valid = {item['key'] for item in build(c, user, now, True)['items']}
    chosen = valid if keys is None else {key for key in keys if KEY.fullmatch(key) and key in valid}
    for key in chosen:
        c.execute('INSERT OR IGNORE INTO notification_reads(user_id,key,read_at) VALUES (?,?,?)', (user['id'], key, now.isoformat(timespec='seconds')))
    c.execute("DELETE FROM notification_reads WHERE user_id=? AND read_at<?", (user['id'], (now - appointments.timedelta(days=120)).isoformat(timespec='seconds')))
    return len(chosen)
