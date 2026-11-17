"""Centro de pendientes 2.0 (1.5.287): lo que requiere una acción real, calculado en cada consulta desde su módulo de origen.

Reglas (separadas a propósito):
- Pendiente / En proceso: lo decide el estado del registro de origen. No hay una tabla de pendientes ni un «resolver» aquí: cada
  pendiente desaparece solo cuando cambia su condición (la cita se confirma, el presupuesto se decide, la orden se entrega…).
- Leído / No leído: usa notification_reads, igual que las notificaciones. Marcar como visto no resuelve nada.
- Visible / Oculto: los pendientes no se pueden ocultar (ocultar es solo para notificaciones informativas).
- Normal / Importante / Urgente: prioridad calculada con fechas y estados reales (vencimientos, plazos, prioridad de la orden).
Este módulo solo lee: no escribe en la base ni cambia ningún registro.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta

import appointments

MODULES = {'orders': 'Órdenes pendientes', 'appointments': 'Citas por confirmar', 'quotes': 'Presupuestos por aprobar', 'parts': 'Repuestos en seguimiento',
           'messages': 'Mensajes por responder', 'licenses': 'Licencias por vencer', 'alerts': 'Alertas del sistema'}
ADMIN_ONLY = ('licenses', 'alerts')
RANK = {'urgente': 0, 'importante': 1, 'normal': 2}
ORDER_PROGRESS = ('diagnostico', 'reparacion', 'pruebas', 'revision_recurrente', 'esperando_repuesto')
ORDER_WAITING = {'pendiente': 'Por iniciar el diagnóstico', 'diagnostico': 'Diagnóstico en curso', 'reparacion': 'Reparación en curso', 'pruebas': 'Pruebas de calidad',
                 'revision_recurrente': 'Revisión por falla recurrente', 'esperando_repuesto': 'Espera un repuesto', 'presupuesto': 'Espera la aprobación del cliente',
                 'esperando_cliente': 'Espera respuesta del cliente', 'espera_entrega': 'Por coordinar la entrega', 'listo': 'Listo: por entregar'}
PART_BEFORE_ARRIVAL = ('solicitado', 'confirmado', 'preparacion', 'transito')
# Avisos de situación que sí exigen una acción de administración (el resto de notificaciones son informativas).
SYSTEM_ALERT = re.compile(r'(autocare:(incident|recurrent|connection):|storage:|backup:|update:|mailquota:|mail:bounce:|maildelivery:|alert:(license-mail|part-notices|accounts|terms-draft):)')


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _moment(value):
    try:
        moment = datetime.fromisoformat(str(value))
        return moment if moment.tzinfo else moment.replace(tzinfo=appointments.TZ)
    except (TypeError, ValueError):
        return None


def _iso(value):
    """Fecha comparable y legible por el navegador; '' si el registro no la tiene."""
    if isinstance(value, (int, float)) and value:
        return datetime.fromtimestamp(value, appointments.TZ).isoformat(timespec='seconds')
    moment = _moment(value)
    return moment.isoformat(timespec='seconds') if moment else ''


def _item(module, key, title, **extra):
    base = {'key': 'pending:' + module + ':' + key, 'module': module, 'title': title, 'detail': '', 'client': '', 'responsible': '', 'responsible_id': None,
            'state': 'pendiente', 'priority': 'normal', 'due': '', 'overdue': False, 'at': '', 'href': '', 'actions': [], 'waiting': '', 'resolves': ''}
    base.update(extra)
    return base


def _orders(c, user, now, mine):
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    rows = c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status,o.priority,o.estimated_delivery,o.assigned_to,o.updated_at,o.received_at,o.created_at,"
                     "s.label status_label,cl.name client,d.brand,d.model,u.name tech FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id "
                     "JOIN clients cl ON cl.id=d.client_id LEFT JOIN users u ON u.id=o.assigned_to WHERE o.status!='entregado'" + mine('o.assigned_to') + " ORDER BY o.id", mine.args).fetchall()
    out = []
    for r in rows:
        due = _day(r['estimated_delivery'])
        overdue = bool(due and due < today)
        priority = 'urgente' if overdue or r['priority'] == 'urgente' else 'importante' if (due and due <= tomorrow) or r['priority'] == 'alta' or r['status'] == 'revision_recurrente' else 'normal'
        actions = [{'label': 'Abrir orden', 'href': '#orders?id=%d' % r['id']}]
        if r['status'] in ('listo', 'espera_entrega'):
            actions.append({'label': 'Ver entregas', 'href': '#deliveries'})
        device = ' '.join(x for x in (r['brand'], r['model']) if x) or 'Equipo'
        out.append(_item('orders', '%d:%s' % (r['id'], r['status']), 'Orden ' + r['code'] + ' · ' + r['status_label'], detail=device, client=r['client'],
                         responsible=r['tech'] or 'Sin asignar', responsible_id=r['assigned_to'], state='en_proceso' if r['status'] in ORDER_PROGRESS else 'pendiente',
                         priority=priority, due=due.isoformat() if due else '', overdue=overdue, at=_iso(r['updated_at']) or _iso(r['received_at']) or _iso(r['created_at']),
                         href=actions[0]['href'], actions=actions, waiting=ORDER_WAITING.get(r['status'], r['status_label']),
                         resolves='Desaparece cuando la orden se entrega al cliente.'))
    return out


def _appointments(c, user, now, mine):
    rows = c.execute("SELECT a.id,a.public_code,a.customer_name,a.starts_at,a.created_at,a.technician_id,a.service_code,COALESCE(NULLIF(a.services_summary,''),s.label,a.service_code) service,"
                     "u.name tech FROM appointments a LEFT JOIN appointment_services s ON s.code=a.service_code LEFT JOIN users u ON u.id=a.technician_id "
                     "WHERE a.deleted_at IS NULL AND a.status='solicitada'" + mine('a.technician_id') + " ORDER BY a.starts_at", mine.args).fetchall()
    out = []
    for r in rows:
        start = _moment(r['starts_at'])
        hours = (start - now).total_seconds() / 3600 if start else 999
        priority = 'urgente' if hours <= 24 else 'importante' if hours <= 72 else 'normal'
        href = '#appointments?appointment=%d' % r['id']
        out.append(_item('appointments', str(r['id']), 'Cita por confirmar · ' + r['public_code'], detail=r['service'], client=r['customer_name'],
                         responsible=r['tech'] or 'Sin asignar', responsible_id=r['technician_id'], priority=priority, due=_iso(r['starts_at']), overdue=hours < 0,
                         at=_iso(r['created_at']), href=href, actions=[{'label': 'Confirmar o gestionar', 'href': href}],
                         waiting='Fecha pasada sin confirmar: reprográmala o ciérrala' if hours < 0 else 'Confirmar con el cliente (registra su autorización)',
                         resolves='Desaparece al confirmar, reprogramar, cancelar o eliminar la cita en la Agenda.'))
    return out


def _quotes(c, user, now, mine):
    today = now.date()
    rows = c.execute("SELECT q.id,q.code,q.status,q.valid_until,q.sent_at,q.updated_at,q.order_id,o.assigned_to,cl.name client,u.name tech FROM quotes q JOIN orders o ON o.id=q.order_id "
                     "JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id LEFT JOIN users u ON u.id=o.assigned_to "
                     "WHERE q.deleted_at='' AND q.status IN ('enviado','modificacion')" + mine('o.assigned_to') + " ORDER BY q.id", mine.args).fetchall()
    out = []
    for r in rows:
        href = '#orders?id=%d' % r['order_id']
        common = dict(client=r['client'], responsible=r['tech'] or 'Sin asignar', responsible_id=r['assigned_to'], href=href, actions=[{'label': 'Revisar presupuesto', 'href': href}])
        if r['status'] == 'modificacion':
            out.append(_item('quotes', '%d:modificacion' % r['id'], 'El cliente pide cambios · ' + r['code'], detail='Revisión solicitada por el cliente', priority='importante',
                             at=_iso(r['updated_at']), waiting='Preparar una versión nueva del presupuesto', resolves='Desaparece al enviar una versión nueva o cancelar el presupuesto.', **common))
            continue
        valid = _day(r['valid_until'])
        sent = _moment(r['sent_at'])
        expired = bool(valid and valid < today)
        late = bool(sent and (now - sent).days >= 3)
        priority = 'urgente' if expired else 'importante' if (valid and valid <= today + timedelta(days=2)) or late else 'normal'
        out.append(_item('quotes', '%d:enviado' % r['id'], 'Presupuesto por aprobar · ' + r['code'], detail='Vigencia vencida: el cliente ya no puede decidir' if expired else 'Enviado al cliente',
                         priority=priority, due=valid.isoformat() if valid else '', overdue=expired, at=_iso(r['sent_at']) or _iso(r['updated_at']),
                         waiting='Crear una versión nueva o llamar al cliente' if expired else 'Espera la decisión del cliente',
                         resolves='Desaparece cuando el cliente decide o el taller lo reemplaza o cancela.', **common))
    return out


def _parts(c, user, now, mine, admin):
    import order_part_requests as parts
    today = now.date()
    stages, situations = {s[0]: s[2] for s in parts.STAGES}, parts.SITUATIONS
    tech = '' if admin else ' AND (r.technician_id=? OR o.assigned_to=? OR o.assigned_to IS NULL)'
    rows = c.execute("SELECT r.id,r.name,r.stage,r.situation,r.eta,r.updated_at,r.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,COALESCE(r.technician_id,o.assigned_to) owner,"
                     "cl.name client,u.name tech FROM order_part_requests r JOIN orders o ON o.id=r.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id "
                     "LEFT JOIN users u ON u.id=COALESCE(r.technician_id,o.assigned_to) WHERE r.situation!='cancelado' AND r.stage NOT IN ('instalado','listo') AND o.status!='entregado'" + tech + " ORDER BY r.id",
                     () if admin else (user['id'], user['id'])).fetchall()
    out = []
    for r in rows:
        eta = _day(r['eta'])
        late = bool(eta and eta < today and r['stage'] in PART_BEFORE_ARRIVAL)
        priority = ('urgente' if r['situation'] in ('retrasado', 'incidencia_transporte') or late else
                    'importante' if r['situation'] in ('espera_confirmacion', 'espera_proveedor') or r['stage'] == 'recibido' or (eta and eta <= today + timedelta(days=2) and r['stage'] in PART_BEFORE_ARRIVAL) else 'normal')
        href = '#orders?id=%d' % r['order_id']
        situation = '' if r['situation'] == 'normal' else ' · ' + situations.get(r['situation'], (r['situation'],))[0]
        out.append(_item('parts', '%d:%s:%s' % (r['id'], r['stage'], r['situation']), 'Repuesto · ' + r['code'] + ' · ' + (r['name'] or 'Repuesto')[:60],
                         detail=stages.get(r['stage'], r['stage']) + situation, client=r['client'], responsible=r['tech'] or 'Sin asignar', responsible_id=r['owner'],
                         state='pendiente' if r['stage'] == 'recibido' else 'en_proceso', priority=priority, due=eta.isoformat() if eta and r['stage'] in PART_BEFORE_ARRIVAL else '',
                         overdue=late, at=_iso(r['updated_at']), href=href, actions=[{'label': 'Ver seguimiento', 'href': href}],
                         waiting='Recibido: instalar y continuar la orden' if r['stage'] == 'recibido' else 'Llegada estimada vencida: consulta al proveedor' if late else 'Seguimiento del pedido',
                         resolves='Desaparece cuando el repuesto queda instalado, se cancela el pedido o se entrega la orden.'))
    if admin:
        for r in c.execute("SELECT x.id,x.status,x.origin,x.created_at,r.name,r.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,cl.name client FROM order_part_cancellations x "
                           "JOIN order_part_requests r ON r.id=x.request_id JOIN orders o ON o.id=r.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id "
                           "WHERE x.status IN ('solicitada','en_revision') ORDER BY x.id").fetchall():
            href = '#orders?id=%d' % r['order_id']
            out.append(_item('parts', 'cancel:%d:%s' % (r['id'], r['status']), 'Cancelación de repuesto por decidir · ' + r['code'], detail=(r['name'] or 'Repuesto')[:80] + (' · pedida por el cliente' if r['origin'] == 'cliente' else ''),
                             client=r['client'], responsible='Administración', state='en_proceso' if r['status'] == 'en_revision' else 'pendiente', priority='importante', at=_iso(r['created_at']),
                             href=href, actions=[{'label': 'Revisar solicitud', 'href': href}], waiting='Decisión de administración', resolves='Desaparece al aprobar o rechazar la solicitud.'))
    return out


def _messages(c, user, now, admin):
    out = []
    if admin:
        rows = c.execute("SELECT ac.id,ac.mode,ac.assigned_to,ac.updated_at,COALESCE(cl.name,'') client FROM adi_conversations ac LEFT JOIN clients cl ON cl.id=ac.client_id "
                         "WHERE ac.mode!='closed' AND ((ac.mode='human' AND ac.assigned_to IS NULL) OR (ac.last_seen_admin='' AND EXISTS(SELECT 1 FROM adi_messages m WHERE m.conversation_id=ac.id AND m.author='client'))) ORDER BY ac.id").fetchall()
        for r in rows:
            waiting = r['mode'] == 'human' and r['assigned_to'] is None
            out.append(_item('messages', 'chat:%d:%s' % (r['id'], 'asesor' if waiting else 'nueva'), ('Cliente espera a un asesor' if waiting else 'Conversación nueva sin revisar') + ' · #%d' % r['id'],
                             detail='Atención en vivo', client=r['client'] or 'Visitante del chat', responsible='Sin asignar', priority='urgente' if waiting else 'importante', at=_iso(r['updated_at']),
                             href='#live', actions=[{'label': 'Responder conversación', 'href': '#live'}], waiting='Responder en Atención en vivo',
                             resolves='Desaparece cuando alguien toma o abre la conversación, o se cierra.'))
        labels = {'confirm': 'Confirma su mantenimiento', 'reschedule': 'Pide otra fecha para su mantenimiento', 'decline': 'No desea el mantenimiento'}
        for r in c.execute("SELECT x.id,x.action,x.created_at,m.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,cl.name client FROM maintenance_responses x JOIN maintenance m ON m.id=x.maintenance_id "
                           "JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE x.handled_at='' ORDER BY x.id").fetchall():
            href = '#maintenance?order=%d' % r['order_id']
            out.append(_item('messages', 'maintenance:%d' % r['id'], labels.get(r['action'], 'Respuesta de mantenimiento') + ' · ' + r['code'], detail='Respuesta por enlace seguro', client=r['client'],
                             responsible='Sin asignar', priority='importante' if r['action'] == 'reschedule' else 'normal', at=_iso(r['created_at']), href=href,
                             actions=[{'label': 'Gestionar respuesta', 'href': href}], waiting='Revisar y registrar la gestión', resolves='Desaparece al marcar la respuesta como gestionada.'))
    try:
        import pqrs
        if admin:
            rows = c.execute("SELECT p.id,p.code,p.category,p.status,p.priority,p.name,p.created_at,p.updated_at,p.first_response_at,p.assigned_to,u.name tech FROM pqrs_cases p LEFT JOIN users u ON u.id=p.assigned_to "
                             "WHERE p.status IN ('recibida','en_revision','asignada','en_solucion') ORDER BY p.id").fetchall()
        else:
            rows = c.execute("SELECT p.id,p.code,p.category,p.status,p.priority,p.name,p.created_at,p.updated_at,p.first_response_at,p.assigned_to,u.name tech FROM pqrs_cases p LEFT JOIN users u ON u.id=p.assigned_to "
                             "WHERE p.assigned_to=? AND p.status IN ('asignada','en_revision','en_solucion') ORDER BY p.id", (user['id'],)).fetchall()
    except Exception as error:
        print('pendientes pqrs', type(error).__name__, flush=True)
        rows = []
    for r in rows:
        created = _moment(r['created_at'])
        limit = created + timedelta(hours=pqrs.FIRST_RESPONSE_HOURS) if created and not r['first_response_at'] else None
        late = bool(limit and limit < now)
        priority = 'urgente' if late or r['priority'] == 'urgente' else 'importante' if r['category'] in ('queja', 'reclamo') or r['priority'] == 'alta' else 'normal'
        href = '#pqrs?id=%d' % r['id']
        out.append(_item('messages', 'pqrs:%d:%s' % (r['id'], r['status']), 'PQRS por responder · ' + r['code'], detail=pqrs.CATEGORY_LABELS.get(r['category'], (r['category'],))[0],
                         client=r['name'], responsible=r['tech'] or 'Sin asignar', responsible_id=r['assigned_to'], state='pendiente' if r['status'] == 'recibida' else 'en_proceso',
                         priority=priority, due=limit.isoformat(timespec='seconds') if limit else '', overdue=late, at=_iso(r['updated_at']) or _iso(r['created_at']), href=href,
                         actions=[{'label': 'Responder PQRS', 'href': href}], waiting='Primera respuesta pendiente' if not r['first_response_at'] else 'Solución en curso',
                         resolves='Desaparece cuando la PQRS se responde, espera al cliente o se cierra.'))
    return out


def _licenses(c, now):
    import licenses
    out = []
    for u in licenses.expiring(c, now, 500):
        days = u['days_left']
        priority = 'urgente' if days <= 7 else 'importante' if days <= 15 else 'normal'
        text = 'Vencida hace %d día%s' % (-days, '' if days == -1 else 's') if days < 0 else 'Vence hoy' if days == 0 else 'Vence en %d día%s' % (days, '' if days == 1 else 's')
        out.append(_item('licenses', '%d:%s' % (u['id'], u['expires_at']), 'Licencia por vencer · ' + (u['product'] or 'Licencia')[:60], detail=text + (' · ' + u['code'] if u['code'] else ''),
                         client=u['client'] or 'Sin cliente', responsible='Administración', priority=priority, due=u['expires_at'], overdue=days < 0, at=_iso(u['expires_at']),
                         href='#licenses', actions=[{'label': 'Consultar licencia', 'href': '#licenses'}], waiting='Ofrecer la renovación al cliente',
                         resolves='Desaparece cuando la licencia se renueva o deja de estar vigente en Licencias Pro.'))
    return out


def _alerts(notices):
    out = []
    for n in notices:
        if not SYSTEM_ALERT.match(n['key']) or n.get('kind') not in ('warning', 'error'):
            continue
        critical = n['kind'] == 'error' or n['key'].startswith(('storage:', 'backup:'))
        # Se conserva la clave del aviso: leerlo aquí o en Notificaciones es lo mismo, pero ocultarlo no lo quita de los pendientes.
        out.append(dict(_item('alerts', '', n['title'], detail=n.get('detail', ''), responsible='Administración', priority='urgente' if critical else 'importante', at=n.get('at', ''),
                              href=n.get('href', ''), actions=[{'label': 'Abrir detalle', 'href': n.get('href', '')}] if n.get('href') else [],
                              waiting='Revisar la causa', resolves='Desaparece cuando la condición deja de existir en su módulo.'), key=n['key']))
    return out


def build(c, user, now, notices=()):
    """Pendientes visibles para esta persona. `notices` son las notificaciones ya calculadas (incluidas las ocultas) para derivar las alertas."""
    admin = user['role'] == 'administrador'

    class Mine:
        """Filtro de técnico: lo asignado a esa persona o todavía sin asignar. Administración ve todo."""
        args = () if admin else (user['id'],)

        def __call__(self, column):
            return '' if admin else ' AND (%s=? OR %s IS NULL)' % (column, column)
    mine = Mine()
    items = []
    for name, part in (('orders', lambda: _orders(c, user, now, mine)), ('appointments', lambda: _appointments(c, user, now, mine)), ('quotes', lambda: _quotes(c, user, now, mine)),
                       ('parts', lambda: _parts(c, user, now, mine, admin)), ('messages', lambda: _messages(c, user, now, admin)),
                       ('licenses', lambda: _licenses(c, now) if admin else []), ('alerts', lambda: _alerts(notices) if admin else [])):
        try:
            items += part()
        except Exception as error:
            # Un módulo con error no oculta los demás; administración lo ve como alerta para no confundirlo con «sin pendientes».
            print('pendientes', name, type(error).__name__, flush=True)
            if admin:
                items.append(_item('alerts', 'error:' + name, 'No se pudieron calcular: ' + MODULES[name].lower(), detail='Inténtalo de nuevo en unos minutos.',
                                   priority='importante', at=now.isoformat(timespec='seconds'), waiting='Revisar el registro del servidor'))
    read = {row['key'] for row in c.execute('SELECT key FROM notification_reads WHERE user_id=?', (user['id'],))}
    for item in items:
        item['read'] = item['key'] in read
    items.sort(key=lambda i: (RANK[i['priority']], not i['overdue'], i['due'] or '9999', i['at']))
    modules = [m for m in MODULES if admin or m not in ADMIN_ONLY]
    summary = {m: {'label': MODULES[m], 'count': 0, 'urgent': 0, 'overdue': 0, 'unread': 0} for m in modules}
    for item in items:
        box = summary[item['module']]
        box['count'] += 1
        box['urgent'] += item['priority'] == 'urgente'
        box['overdue'] += item['overdue']
        box['unread'] += not item['read']
    people = sorted({(i['responsible_id'] or 0, i['responsible']) for i in items if i['responsible']}, key=lambda p: p[1].lower())
    payload = {'items': items, 'summary': summary, 'modules': modules, 'responsibles': [{'id': p[0], 'name': p[1]} for p in people],
               'totals': {'count': len(items), 'urgent': sum(1 for i in items if i['priority'] == 'urgente'), 'overdue': sum(1 for i in items if i['overdue']),
                          'unread': sum(1 for i in items if not i['read'])}}
    payload['rev'] = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    payload['generated_at'] = now.isoformat(timespec='seconds')
    return payload


def keys(c, user, now, notices=()):
    return {item['key'] for item in build(c, user, now, notices)['items']}
