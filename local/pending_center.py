"""Centro de pendientes 2.0 (1.5.287): lo que requiere una acción real, calculado en cada consulta desde su módulo de origen.

Reglas (separadas a propósito):
- Pendiente / En proceso: lo decide el estado del registro de origen. No hay una tabla de pendientes ni un «resolver» aquí: cada
  pendiente desaparece solo cuando cambia su condición (la cita se confirma, el presupuesto se decide, la orden se entrega…).
- Leído / No leído: usa notification_reads, igual que las notificaciones. Marcar como visto no resuelve nada.
- Visible / Oculto: los pendientes no se pueden ocultar (ocultar es solo para notificaciones informativas).
- Normal / Importante / Urgente / Crítico: prioridad calculada con fechas y estados reales (vencimientos, plazos, prioridad de la orden);
  «Crítico» queda reservado a fallos graves del sistema (errores activos, almacenamiento y respaldos).
- Gestión (1.5.288): observaciones internas, reconocimientos, silencios temporales y recordatorios viven en pending_notes (solo anexado).
  Se muestran junto al pendiente, pero ninguno lo resuelve; un fallo activo (crítico) no se puede silenciar.
Este módulo solo lee: no escribe en la base ni cambia ningún registro (las escrituras están en pending_actions).
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta

import appointments

MODULES = {'orders': 'Órdenes pendientes', 'appointments': 'Citas por confirmar', 'quotes': 'Presupuestos por aprobar', 'parts': 'Repuestos en seguimiento',
           'messages': 'Mensajes por responder', 'licenses': 'Licencias por vencer', 'alerts': 'Alertas del sistema'}
ADMIN_ONLY = ('licenses', 'alerts')
RANK = {'critico': 0, 'urgente': 1, 'importante': 2, 'normal': 3}
NOTE_KINDS = {'nota': 'Observación interna', 'reconocida': 'Alerta reconocida', 'silenciada': 'Alerta silenciada', 'recordatorio': 'Recordatorio programado', 'resolucion': 'Resolución registrada'}
ORDER_PROGRESS = ('diagnostico', 'reparacion', 'pruebas', 'revision_recurrente', 'esperando_repuesto')
ORDER_WAITING = {'pendiente': 'Por iniciar el diagnóstico', 'diagnostico': 'Diagnóstico en curso', 'reparacion': 'Reparación en curso', 'pruebas': 'Pruebas de calidad',
                 'revision_recurrente': 'Revisión por falla recurrente', 'esperando_repuesto': 'Espera un repuesto', 'presupuesto': 'Espera la aprobación del cliente',
                 'esperando_cliente': 'Espera respuesta del cliente', 'espera_entrega': 'Por coordinar la entrega', 'listo': 'Listo: por entregar'}
PART_BEFORE_ARRIVAL = ('solicitado', 'confirmado', 'preparacion', 'transito')
# 1.5.289 · Estados operativos (derivados del registro de origen y de la gestión; ninguno lo resuelve). Resuelto y Cancelado viven en
# «Solucionadas», que se lee de los historiales de cada módulo.
STATES = {'pendiente': 'Pendiente', 'en_proceso': 'En proceso', 'espera_cliente': 'En espera de cliente', 'espera_tercero': 'En espera de tercero',
          'pospuesto': 'Pospuesto'}
# Reglas de vencimiento y urgencia por tipo de tarea (configurables por administración). Los valores por defecto son los criterios que
# ya usaba el centro: cambiarlos no altera ningún registro, solo cómo se priorizan los pendientes.
RULES = {
    'orders_soon_days': (1, 0, 14, 'Órdenes: prioridad media si la entrega estimada es dentro de (días)'),
    'appointments_urgent_hours': (24, 1, 168, 'Citas sin confirmar: prioridad alta si faltan (horas)'),
    'appointments_important_hours': (72, 1, 336, 'Citas sin confirmar: prioridad media si faltan (horas)'),
    'quotes_soon_days': (2, 0, 30, 'Presupuestos: prioridad media si la vigencia termina dentro de (días)'),
    'quotes_follow_days': (3, 1, 30, 'Presupuestos: prioridad media si el cliente no responde en (días)'),
    'parts_soon_days': (2, 0, 30, 'Repuestos: prioridad media si la llegada estimada es dentro de (días)'),
    'licenses_urgent_days': (7, 0, 60, 'Licencias: prioridad alta si vencen dentro de (días)'),
    'licenses_important_days': (15, 0, 90, 'Licencias: prioridad media si vencen dentro de (días)'),
}
# Pares que deben ser coherentes: el umbral de prioridad media no puede ser menor que el de prioridad alta.
RULE_PAIRS = (('appointments_urgent_hours', 'appointments_important_hours'), ('licenses_urgent_days', 'licenses_important_days'))
TRACK_KINDS = {'asignacion': 'Responsable del seguimiento', 'pospuesto': 'Pendiente pospuesto', 'reanudado': 'Pendiente reanudado'}


def rules(c):
    """Reglas vigentes: las guardadas por administración (system_state) sobre los valores por defecto, siempre dentro de su rango."""
    try:
        row = c.execute("SELECT value FROM system_state WHERE key='pending_rules'").fetchone()
        stored = json.loads(row[0]) if row else {}
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    out = {}
    for key, (default, low, high, _label) in RULES.items():
        value = stored.get(key, default)
        out[key] = value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else default
    for urgent, important in RULE_PAIRS:
        if out[important] < out[urgent]:
            out[urgent], out[important] = RULES[urgent][0], RULES[important][0]
    return out


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
            'state': 'pendiente', 'priority': 'normal', 'due': '', 'overdue': False, 'at': '', 'href': '', 'actions': [], 'waiting': '', 'resolves': '',
            'created': '', 'decision': False, 'ref': {}}
    base.update(extra)
    return base


def _orders(c, user, now, mine, R):
    today, tomorrow = now.date(), now.date() + timedelta(days=R['orders_soon_days'])
    rows = c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status,o.priority,o.estimated_delivery,o.assigned_to,o.updated_at,o.received_at,o.created_at,"
                     "s.label status_label,cl.name client,COALESCE(cl.email,'') email,d.brand,d.model,u.name tech FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id "
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
                         resolves='Desaparece cuando la orden se entrega al cliente.', created=_iso(r['received_at']) or _iso(r['created_at']),
                         decision=r['status'] in ('pendiente', 'listo', 'espera_entrega') or overdue, ref={'order_id': r['id'], 'code': r['code'], 'status': r['status']},
                         search=r['email']))
    return out


def _appointments(c, user, now, mine, R):
    rows = c.execute("SELECT a.id,a.public_code,a.customer_name,COALESCE(a.email,'') email,a.starts_at,a.created_at,a.technician_id,a.service_code,COALESCE(NULLIF(a.services_summary,''),s.label,a.service_code) service,"
                     "u.name tech FROM appointments a LEFT JOIN appointment_services s ON s.code=a.service_code LEFT JOIN users u ON u.id=a.technician_id "
                     "WHERE a.deleted_at IS NULL AND a.status='solicitada'" + mine('a.technician_id') + " ORDER BY a.starts_at", mine.args).fetchall()
    out = []
    for r in rows:
        start = _moment(r['starts_at'])
        hours = (start - now).total_seconds() / 3600 if start else 999
        priority = 'urgente' if hours <= R['appointments_urgent_hours'] else 'importante' if hours <= R['appointments_important_hours'] else 'normal'
        href = '#appointments?appointment=%d' % r['id']
        out.append(_item('appointments', str(r['id']), 'Cita por confirmar · ' + r['public_code'], detail=r['service'], client=r['customer_name'],
                         responsible=r['tech'] or 'Sin asignar', responsible_id=r['technician_id'], priority=priority, due=_iso(r['starts_at']), overdue=hours < 0,
                         at=_iso(r['created_at']), href=href, actions=[{'label': 'Confirmar o gestionar', 'href': href}],
                         waiting='Fecha pasada sin confirmar: reprográmala o ciérrala' if hours < 0 else 'Confirmar con el cliente (registra su autorización)',
                         resolves='Desaparece al confirmar, reprogramar, cancelar o eliminar la cita en la Agenda.', created=_iso(r['created_at']), decision=True,
                         ref={'appointment_id': r['id'], 'code': r['public_code'], 'starts_at': r['starts_at'], 'past': hours < 0}, search=r['email']))
    return out


def _quotes(c, user, now, mine, R):
    today = now.date()
    rows = c.execute("SELECT q.id,q.code,q.status,q.valid_until,q.sent_at,q.updated_at,q.order_id,o.assigned_to,COALESCE(o.code,'') order_code,cl.name client,COALESCE(cl.email,'') email,u.name tech FROM quotes q JOIN orders o ON o.id=q.order_id "
                     "JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id LEFT JOIN users u ON u.id=o.assigned_to "
                     "WHERE q.deleted_at='' AND q.status IN ('enviado','modificacion')" + mine('o.assigned_to') + " ORDER BY q.id", mine.args).fetchall()
    out = []
    for r in rows:
        href = '#orders?id=%d' % r['order_id']
        common = dict(client=r['client'], responsible=r['tech'] or 'Sin asignar', responsible_id=r['assigned_to'], href=href, actions=[{'label': 'Revisar presupuesto', 'href': href}],
                      created=_iso(r['sent_at']) or _iso(r['updated_at']), ref={'quote_id': r['id'], 'order_id': r['order_id'], 'code': r['code'], 'status': r['status']},
                      search=r['email'] + ' ' + r['order_code'])
        if r['status'] == 'modificacion':
            out.append(_item('quotes', '%d:modificacion' % r['id'], 'El cliente pide cambios · ' + r['code'], detail='Revisión solicitada por el cliente', priority='importante', decision=True,
                             at=_iso(r['updated_at']), waiting='Preparar una versión nueva del presupuesto', resolves='Desaparece al enviar una versión nueva o cancelar el presupuesto.', **common))
            continue
        valid = _day(r['valid_until'])
        sent = _moment(r['sent_at'])
        expired = bool(valid and valid < today)
        late = bool(sent and (now - sent).days >= R['quotes_follow_days'])
        priority = 'urgente' if expired else 'importante' if (valid and valid <= today + timedelta(days=R['quotes_soon_days'])) or late else 'normal'
        out.append(_item('quotes', '%d:enviado' % r['id'], 'Presupuesto por aprobar · ' + r['code'], detail='Vigencia vencida: el cliente ya no puede decidir' if expired else 'Enviado al cliente',
                         priority=priority, due=valid.isoformat() if valid else '', overdue=expired, at=_iso(r['sent_at']) or _iso(r['updated_at']), decision=expired,
                         waiting='Crear una versión nueva o llamar al cliente' if expired else 'Espera la decisión del cliente',
                         resolves='Desaparece cuando el cliente decide o el taller lo reemplaza o cancela.', **common))
    return out


def _parts(c, user, now, mine, admin, R):
    import order_part_requests as parts
    today = now.date()
    stages, situations = {s[0]: s[2] for s in parts.STAGES}, parts.SITUATIONS
    tech = '' if admin else ' AND (r.technician_id=? OR o.assigned_to=? OR o.assigned_to IS NULL)'
    rows = c.execute("SELECT r.id,r.name,r.stage,r.situation,r.eta,r.updated_at,r.created_at,r.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,COALESCE(r.technician_id,o.assigned_to) owner,"
                     "cl.name client,COALESCE(cl.email,'') email,u.name tech FROM order_part_requests r JOIN orders o ON o.id=r.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id "
                     "LEFT JOIN users u ON u.id=COALESCE(r.technician_id,o.assigned_to) WHERE r.situation!='cancelado' AND r.stage NOT IN ('instalado','listo') AND o.status!='entregado'" + tech + " ORDER BY r.id",
                     () if admin else (user['id'], user['id'])).fetchall()
    out = []
    for r in rows:
        eta = _day(r['eta'])
        late = bool(eta and eta < today and r['stage'] in PART_BEFORE_ARRIVAL)
        priority = ('urgente' if r['situation'] in ('retrasado', 'incidencia_transporte') or late else
                    'importante' if r['situation'] in ('espera_confirmacion', 'espera_proveedor') or r['stage'] == 'recibido' or (eta and eta <= today + timedelta(days=R['parts_soon_days']) and r['stage'] in PART_BEFORE_ARRIVAL) else 'normal')
        href = '#orders?id=%d' % r['order_id']
        situation = '' if r['situation'] == 'normal' else ' · ' + situations.get(r['situation'], (r['situation'],))[0]
        out.append(_item('parts', '%d:%s:%s' % (r['id'], r['stage'], r['situation']), 'Repuesto · ' + r['code'] + ' · ' + (r['name'] or 'Repuesto')[:60],
                         detail=stages.get(r['stage'], r['stage']) + situation, client=r['client'], responsible=r['tech'] or 'Sin asignar', responsible_id=r['owner'],
                         state='pendiente' if r['stage'] == 'recibido' else 'en_proceso', priority=priority, due=eta.isoformat() if eta and r['stage'] in PART_BEFORE_ARRIVAL else '',
                         overdue=late, at=_iso(r['updated_at']), href=href, actions=[{'label': 'Ver seguimiento', 'href': href}],
                         waiting='Recibido: instalar y continuar la orden' if r['stage'] == 'recibido' else 'Llegada estimada vencida: consulta al proveedor' if late else 'Seguimiento del pedido',
                         resolves='Desaparece cuando el repuesto queda instalado, se cancela el pedido o se entrega la orden.', created=_iso(r['created_at']),
                         decision=r['stage'] == 'recibido' or late or r['situation'] == 'incidencia_transporte',
                         ref={'order_id': r['order_id'], 'request_id': r['id'], 'code': r['code'], 'stage': r['stage'], 'situation': r['situation'], 'eta': r['eta'] or ''},
                         search=r['email']))
    if admin:
        for r in c.execute("SELECT x.id,x.status,x.origin,x.created_at,r.name,r.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,cl.name client FROM order_part_cancellations x "
                           "JOIN order_part_requests r ON r.id=x.request_id JOIN orders o ON o.id=r.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id "
                           "WHERE x.status IN ('solicitada','en_revision') ORDER BY x.id").fetchall():
            href = '#orders?id=%d' % r['order_id']
            out.append(_item('parts', 'cancel:%d:%s' % (r['id'], r['status']), 'Cancelación de repuesto por decidir · ' + r['code'], detail=(r['name'] or 'Repuesto')[:80] + (' · pedida por el cliente' if r['origin'] == 'cliente' else ''),
                             client=r['client'], responsible='Administración', state='en_proceso' if r['status'] == 'en_revision' else 'pendiente', priority='importante', at=_iso(r['created_at']),
                             href=href, actions=[{'label': 'Revisar solicitud', 'href': href}], waiting='Decisión de administración', resolves='Desaparece al aprobar o rechazar la solicitud.',
                             created=_iso(r['created_at']), decision=True, ref={'order_id': r['order_id'], 'cancellation_id': r['id'], 'code': r['code']}))
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
                             resolves='Desaparece cuando alguien toma o abre la conversación, o se cierra.', created=_iso(r['updated_at']), decision=True,
                             ref={'conversation_id': r['id'], 'kind': 'chat'}))
        labels = {'confirm': 'Confirma su mantenimiento', 'reschedule': 'Pide otra fecha para su mantenimiento', 'decline': 'No desea el mantenimiento'}
        for r in c.execute("SELECT x.id,x.action,x.created_at,m.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,cl.name client FROM maintenance_responses x JOIN maintenance m ON m.id=x.maintenance_id "
                           "JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE x.handled_at='' ORDER BY x.id").fetchall():
            href = '#maintenance?order=%d' % r['order_id']
            out.append(_item('messages', 'maintenance:%d' % r['id'], labels.get(r['action'], 'Respuesta de mantenimiento') + ' · ' + r['code'], detail='Respuesta por enlace seguro', client=r['client'],
                             responsible='Sin asignar', priority='importante' if r['action'] == 'reschedule' else 'normal', at=_iso(r['created_at']), href=href,
                             actions=[{'label': 'Gestionar respuesta', 'href': href}], waiting='Revisar y registrar la gestión', resolves='Desaparece al marcar la respuesta como gestionada.',
                             created=_iso(r['created_at']), decision=True, ref={'order_id': r['order_id'], 'response_id': r['id'], 'kind': 'maintenance', 'code': r['code']}))
    try:
        import pqrs
        if admin:
            rows = c.execute("SELECT p.id,p.code,p.category,p.status,p.priority,p.name,COALESCE(p.email,'') email,p.created_at,p.updated_at,p.first_response_at,p.assigned_to,u.name tech FROM pqrs_cases p LEFT JOIN users u ON u.id=p.assigned_to "
                             "WHERE p.status IN ('recibida','en_revision','asignada','en_solucion') ORDER BY p.id").fetchall()
        else:
            rows = c.execute("SELECT p.id,p.code,p.category,p.status,p.priority,p.name,COALESCE(p.email,'') email,p.created_at,p.updated_at,p.first_response_at,p.assigned_to,u.name tech FROM pqrs_cases p LEFT JOIN users u ON u.id=p.assigned_to "
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
                         resolves='Desaparece cuando la PQRS se responde, espera al cliente o se cierra.', created=_iso(r['created_at']),
                         decision=not r['first_response_at'], ref={'pqrs_id': r['id'], 'code': r['code'], 'status': r['status'], 'kind': 'pqrs'}, search=r['email']))
    return out


def _licenses(c, now, R):
    import licenses
    out = []
    for u in licenses.expiring(c, now, 500):
        days = u['days_left']
        priority = 'urgente' if days <= R['licenses_urgent_days'] else 'importante' if days <= R['licenses_important_days'] else 'normal'
        text = 'Vencida hace %d día%s' % (-days, '' if days == -1 else 's') if days < 0 else 'Vence hoy' if days == 0 else 'Vence en %d día%s' % (days, '' if days == 1 else 's')
        out.append(_item('licenses', '%d:%s' % (u['id'], u['expires_at']), 'Licencia por vencer · ' + (u['product'] or 'Licencia')[:60], detail=text + (' · ' + u['code'] if u['code'] else ''),
                         client=u['client'] or 'Sin cliente', responsible='Administración', priority=priority, due=u['expires_at'], overdue=days < 0, at=_iso(u['expires_at']),
                         href='#licenses', actions=[{'label': 'Consultar licencia', 'href': '#licenses'}], waiting='Ofrecer la renovación al cliente',
                         resolves='Desaparece cuando la licencia se renueva o deja de estar vigente en Licencias Pro.', decision=days <= R['licenses_urgent_days'],
                         ref={'unit_id': u['id'], 'code': u['code'] or '', 'expires_at': u['expires_at'], 'days_left': days, 'product': u['product'] or ''}))
    return out


def _alerts(notices):
    out, seen = [], {}
    # 1.5.289 · Avisos equivalentes (mismo título y mismo detalle: por ejemplo, el mismo correo devuelto varias veces) forman UN pendiente
    # con su cantidad; cada aviso original se conserva y se marca como visto junto con el grupo. Avisos distintos nunca se agrupan.
    ordered = sorted((n for n in notices if SYSTEM_ALERT.match(n['key']) and n.get('kind') in ('warning', 'error')), key=lambda n: (n.get('at', ''), n['key']))
    for n in ordered:
        signature = (n['title'], n.get('detail', ''), n['kind'])
        if signature in seen:
            first = seen[signature]
            first['ref']['count'] += 1
            first['ref']['keys'].append(n['key'])
            first['at'] = max(first['at'], n.get('at', ''))
            first['activity'] = first['at']
            continue
        critical = n['kind'] == 'error' or n['key'].startswith(('storage:', 'backup:'))
        recurrent = re.match(r'autocare:recurrent:([A-Za-z0-9_-]{1,20}):', n['key'])
        delivery = re.match(r'maildelivery:(\d+):(fallido|rebotado|demorado)$', n['key'])
        # Se conserva la clave del aviso: leerlo aquí o en Notificaciones es lo mismo, pero ocultarlo no lo quita de los pendientes.
        out.append(dict(_item('alerts', '', n['title'], detail=n.get('detail', ''), responsible='Administración', priority='critico' if critical else 'importante', at=n.get('at', ''),
                              href=n.get('href', ''), actions=[{'label': 'Abrir detalle', 'href': n.get('href', '')}] if n.get('href') else [],
                              waiting='Fallo activo: revisar la causa' if critical else 'Revisar la causa', resolves='Desaparece cuando la condición deja de existir en su módulo.',
                              created=n.get('at', ''), decision=critical,
                              ref={'severity': 'Crítica' if critical else 'Advertencia', 'source': n['key'].split(':', 1)[0], 'incident': recurrent[1] if recurrent else '',
                                   'can_silence': not critical, 'delivery_id': int(delivery[1]) if delivery else None,
                                   'recipient': n['title'].split(' · ', 1)[1] if delivery and ' · ' in n['title'] else '', 'count': 1, 'keys': [n['key']]}), key=n['key']))
        seen[signature] = out[-1]
    return out


def entity(item):
    """Registro de origen del pendiente (no cambia con su estado): ancla de las observaciones, reconocimientos y recordatorios."""
    ref, module = item.get('ref') or {}, item['module']
    if module == 'orders':
        return 'orders:%d' % ref['order_id']
    if module == 'appointments':
        return 'appointments:%d' % ref['appointment_id']
    if module == 'quotes':
        return 'quotes:%d' % ref['quote_id']
    if module == 'parts':
        return 'parts:cancel:%d' % ref['cancellation_id'] if ref.get('cancellation_id') else 'parts:%d' % ref['request_id']
    if module == 'messages':
        ident = ref.get('pqrs_id') or ref.get('conversation_id') or ref.get('response_id')
        return 'messages:%s:%s' % (ref.get('kind', ''), ident)
    if module == 'licenses':
        return 'licenses:%d' % ref['unit_id']
    return item['key']


def notes(c, entities=None, since=None):
    """Registro de gestión (pending_notes) con el nombre de quien actuó. None si la tabla todavía no existe en esta base."""
    sql, args = ("SELECT n.id,n.key,n.module,n.kind,n.body,n.until,n.created_at,n.user_id,COALESCE(u.name,'') actor FROM pending_notes n "
                 "LEFT JOIN users u ON u.id=n.user_id"), []
    where = []
    if entities is not None:
        entities = list(entities)[:400]
        if not entities:
            return []
        where.append('n.key IN (' + ','.join('?' * len(entities)) + ')')
        args += entities
    if since:
        where.append('n.created_at>=?')
        args.append(since)
    try:
        return [dict(r) for r in c.execute(sql + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY n.id', args)]
    except Exception as error:
        if 'pending_notes' in str(error):
            return None
        raise


def _overlay(c, items, now):
    """Aplica la gestión registrada sin resolver nada: un reconocimiento o una resolución registrada pasan la alerta a «En proceso»;
    un silencio vigente (solo advertencias) la deja fuera de los urgentes; un recordatorio muestra su fecha. Devuelve si la tabla existe."""
    found = notes(c, {i['entity'] for i in items})
    if found is None:
        return False
    by = {}
    for n in found:
        by.setdefault(n['key'], []).append(n)
    stamp, today = now.isoformat(timespec='seconds'), now.date().isoformat()
    for item in items:
        rows = by.get(item['entity'], [])
        item['notes'] = sum(1 for n in rows if n['kind'] == 'nota')
        last = {n['kind']: n for n in rows}
        ack, silence, reminder, resolution = last.get('reconocida'), last.get('silenciada'), last.get('recordatorio'), last.get('resolucion')
        if ack:
            item['ack'] = {'by': ack['actor'], 'at': ack['created_at'], 'body': ack['body']}
        if resolution:
            item['resolution'] = {'by': resolution['actor'], 'at': resolution['created_at'], 'body': resolution['body']}
        if item['module'] == 'alerts' and (ack or resolution):
            item['state'] = 'en_proceso'
            if resolution:
                item['waiting'] = 'Resolución registrada: sigue activa hasta que el sistema confirme que la condición desapareció'
        if silence and silence['until'] > stamp and (item.get('ref') or {}).get('can_silence'):
            item['silenced'] = silence['until']
        if reminder and reminder['until'] >= today:
            item['reminder'] = reminder['until']
            item['reminder_due'] = reminder['until'] <= today
    return True


def tracking(c, entities=None, since=None):
    """Responsables del seguimiento y aplazamientos (pending_tracking), con nombres. None si la tabla todavía no existe en esta base."""
    sql = ("SELECT t.id,t.key,t.module,t.kind,t.assignee_id,t.until,t.body,t.user_id,t.created_at,COALESCE(u.name,'') actor,COALESCE(a.name,'') assignee "
           "FROM pending_tracking t LEFT JOIN users u ON u.id=t.user_id LEFT JOIN users a ON a.id=t.assignee_id")
    where, args = [], []
    if entities is not None:
        entities = list(entities)[:400]
        if not entities:
            return []
        where.append('t.key IN (' + ','.join('?' * len(entities)) + ')')
        args += entities
    if since:
        where.append('t.created_at>=?')
        args.append(since)
    try:
        return [dict(r) for r in c.execute(sql + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY t.id', args)]
    except Exception as error:
        if 'pending_tracking' in str(error):
            return None
        raise


# Módulos cuyo responsable vive en el propio registro (la orden y la PQRS): ahí manda el módulo; el centro solo anota la fecha.
MODULE_OWNED = ('orders',)


def _track_overlay(c, items, now):
    """Responsable del seguimiento (con fecha y quién asignó) y aplazamiento vigente. Devuelve si la tabla existe."""
    found = tracking(c, {i['entity'] for i in items})
    if found is None:
        return False
    by = {}
    for t in found:
        by.setdefault(t['key'], []).append(t)
    today = now.date().isoformat()
    for item in items:
        rows = by.get(item['entity'], [])
        assign = next((t for t in reversed(rows) if t['kind'] == 'asignacion'), None)
        if assign:
            module_owned = item['module'] in MODULE_OWNED or (item['module'] == 'messages' and (item.get('ref') or {}).get('kind') == 'pqrs')
            if module_owned and assign['assignee_id'] != item['responsible_id']:
                pass   # el responsable cambió después en su módulo: manda el módulo y no se inventa una fecha de asignación
            else:
                if not module_owned:
                    item['module_responsible'] = item['responsible']
                    item['responsible'] = assign['assignee'] or 'Sin asignar'
                    item['responsible_id'] = assign['assignee_id']
                item['assigned'] = {'at': assign['created_at'], 'by': assign['actor'], 'note': assign['body']}
        pause = next((t for t in reversed(rows) if t['kind'] in ('pospuesto', 'reanudado')), None)
        if pause and pause['kind'] == 'pospuesto' and pause['until'] > today and item['priority'] != 'critico':
            item['postponed'] = {'until': pause['until'], 'by': pause['actor'], 'at': pause['created_at'], 'body': pause['body']}
    return True


def _stage(item):
    """Estado operativo: pospuesto, en espera de cliente o de tercero (según el registro de origen), en proceso o pendiente."""
    ref, module = item.get('ref') or {}, item['module']
    if item.get('postponed'):
        return 'pospuesto'
    if not item['overdue']:
        if (module == 'orders' and ref.get('status') in ('presupuesto', 'esperando_cliente')) or (module == 'quotes' and ref.get('status') == 'enviado'):
            return 'espera_cliente'
        if (module == 'orders' and ref.get('status') == 'esperando_repuesto') or (module == 'parts' and ref.get('stage') in PART_BEFORE_ARRIVAL and ref.get('situation') != 'incidencia_transporte'):
            return 'espera_tercero'
    return item['state']


def build(c, user, now, notices=(), resolved_today=False):
    """Pendientes visibles para esta persona. `notices` son las notificaciones ya calculadas (incluidas las ocultas) para derivar las alertas.
    resolved_today: añade cuántos pendientes se solucionaron hoy (solo para la vista principal; las acciones no lo necesitan)."""
    admin = user['role'] == 'administrador'
    R = rules(c)

    class Mine:
        """Filtro de técnico: lo asignado a esa persona o todavía sin asignar. Administración ve todo."""
        args = () if admin else (user['id'],)

        def __call__(self, column):
            return '' if admin else ' AND (%s=? OR %s IS NULL)' % (column, column)
    mine = Mine()
    items = []
    for name, part in (('orders', lambda: _orders(c, user, now, mine, R)), ('appointments', lambda: _appointments(c, user, now, mine, R)), ('quotes', lambda: _quotes(c, user, now, mine, R)),
                       ('parts', lambda: _parts(c, user, now, mine, admin, R)), ('messages', lambda: _messages(c, user, now, admin)),
                       ('licenses', lambda: _licenses(c, now, R) if admin else []), ('alerts', lambda: _alerts(notices) if admin else [])):
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
        group = (item.get('ref') or {}).get('keys') or [item['key']]
        item['read'] = all(k in read for k in group)
        item['entity'] = entity(item)
        item['activity'] = item['at']
        item.setdefault('notes', 0)
        item.setdefault('search', '')
    managed = _overlay(c, items, now)
    tracked = _track_overlay(c, items, now)
    me = user['id']
    attention = lambda i: not i.get('silenced') and not i.get('postponed')
    for item in items:
        item['state'] = _stage(item)
        waiting = item['state'] in ('espera_cliente', 'espera_tercero')
        item['mine'] = attention(item) and (not waiting or item['decision']) and item['responsible_id'] in (None, me)
        item['others'] = item['responsible_id'] is not None and item['responsible_id'] != me
        item['followup'] = item['state'] != 'pendiente' or bool(item.get('ack') or item.get('reminder') or item.get('assigned'))
    items.sort(key=lambda i: (RANK[i['priority']] + (2 if not attention(i) else 0), not i['decision'], not i['overdue'], i['due'] or '9999', i['at']))
    modules = [m for m in MODULES if admin or m not in ADMIN_ONLY]
    summary = {m: {'label': MODULES[m], 'count': 0, 'critical': 0, 'urgent': 0, 'overdue': 0, 'unread': 0, 'silenced': 0} for m in modules}
    for item in items:
        box = summary[item['module']]
        box['count'] += 1
        box['critical'] += item['priority'] == 'critico'
        box['urgent'] += item['priority'] in ('critico', 'urgente') and attention(item)
        box['overdue'] += item['overdue']
        box['unread'] += not item['read']
        box['silenced'] += bool(item.get('silenced'))
    people = sorted({(i['responsible_id'] or 0, i['responsible']) for i in items if i['responsible']}, key=lambda p: p[1].lower())
    count = lambda test: sum(1 for i in items if test(i))
    payload = {'items': items, 'summary': summary, 'modules': modules, 'responsibles': [{'id': p[0], 'name': p[1]} for p in people], 'managed': managed, 'tracked': tracked,
               'totals': {'count': len(items), 'critical': count(lambda i: i['priority'] == 'critico'),
                          'urgent': count(lambda i: i['priority'] in ('critico', 'urgente') and attention(i)), 'overdue': count(lambda i: i['overdue']),
                          'unread': count(lambda i: not i['read']), 'decision': count(lambda i: i['decision'] and attention(i)),
                          'silenced': count(lambda i: i.get('silenced')), 'postponed': count(lambda i: i.get('postponed')),
                          'mine': count(lambda i: i['mine']), 'others': count(lambda i: i['others']), 'followup': count(lambda i: i['followup'])}}
    if resolved_today:
        try:
            payload['totals']['resolved_today'] = resolved(c, user, now, {'from': now.date().isoformat(), 'to': now.date().isoformat()})['total']
        except Exception as error:
            print('pendientes solucionadas', type(error).__name__, flush=True)
            payload['totals']['resolved_today'] = None
    if admin:
        payload['rules'] = R
    payload['rev'] = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    payload['generated_at'] = now.isoformat(timespec='seconds')
    return payload


def keys(c, user, now, notices=()):
    return {item['key'] for item in build(c, user, now, notices)['items']}


def find(c, user, now, wanted, notices=()):
    """El pendiente visible para esta persona por su clave o su registro de origen; None si no existe o no le corresponde verlo."""
    return next((i for i in build(c, user, now, notices)['items'] if wanted in (i['key'], i['entity'])), None)


def _event(at, actor, text, kind='evento'):
    return {'at': _iso(at) or str(at or ''), 'actor': actor or 'Sistema', 'text': str(text or '').strip()[:600], 'kind': kind}


def _history(c, item, admin):
    """Actividad reciente del registro de origen (lo que ya muestra cada módulo), normalizada: fecha, persona y texto."""
    ref, module, out = item.get('ref') or {}, item['module'], []
    if module == 'orders' or (module in ('quotes', 'parts') and ref.get('order_id') and not ref.get('quote_id') and not ref.get('request_id')):
        for r in c.execute("SELECT h.occurred_at,h.event,h.status_label,h.comment,u.name actor FROM order_history h LEFT JOIN users u ON u.id=h.actor_id WHERE h.order_id=? ORDER BY h.id DESC LIMIT 25", (ref['order_id'],)):
            out.append(_event(r['occurred_at'], r['actor'], (r['comment'] or r['status_label'] or r['event']), 'estado' if r['event'] == 'status' else 'evento'))
    elif module == 'appointments':
        labels = appointments.STATUSES
        for r in c.execute("SELECT e.event,e.old_status,e.new_status,e.old_start,e.new_start,e.created_at,e.detail,u.name actor FROM appointment_events e LEFT JOIN users u ON u.id=e.actor_id "
                           "WHERE e.appointment_id=? ORDER BY e.id DESC LIMIT 25", (ref['appointment_id'],)):
            if r['new_status'] and r['new_status'] != r['old_status']:
                text = 'Estado: %s → %s' % (labels.get(r['old_status'], r['old_status'] or 'nueva'), labels.get(r['new_status'], r['new_status']))
            elif r['new_start'] and r['new_start'] != r['old_start']:
                text = 'Reprogramada: %s → %s' % (r['old_start'][:16].replace('T', ' '), r['new_start'][:16].replace('T', ' '))
            else:
                text = r['event']
            out.append(_event(r['created_at'], r['actor'], text + (' · ' + r['detail'] if r['detail'] else ''), 'estado' if r['new_status'] != r['old_status'] else 'evento'))
    elif module == 'quotes':
        for r in c.execute("SELECT e.event,e.detail,e.created_at,COALESCE(u.name,NULLIF(e.actor,''),'') actor FROM quote_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.quote_id=? ORDER BY e.id DESC LIMIT 25", (ref['quote_id'],)):
            out.append(_event(r['created_at'], r['actor'], r['detail'] or r['event']))
    elif module == 'parts' and ref.get('request_id'):
        for r in c.execute("SELECT e.kind,e.note,e.public_note,e.public,e.created_at,u.name actor FROM order_part_events e LEFT JOIN users u ON u.id=e.created_by WHERE e.request_id=? ORDER BY e.id DESC LIMIT 25", (ref['request_id'],)):
            out.append(_event(r['created_at'], r['actor'], (r['note'] or r['kind']) + (' · Aviso al cliente: ' + r['public_note'] if r['public'] and r['public_note'] else ''), 'estado' if r['kind'] in ('etapa', 'situacion') else 'evento'))
    elif module == 'messages' and ref.get('kind') == 'pqrs':
        for r in c.execute("SELECT e.kind,e.body,e.old_value,e.new_value,e.public,e.created_at,u.name actor FROM pqrs_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.case_id=? ORDER BY e.id DESC LIMIT 25", (ref['pqrs_id'],)):
            text = r['body'] if r['kind'] in ('respuesta', 'nota', 'mensaje_cliente') else '%s: %s → %s' % (r['kind'].capitalize(), r['old_value'] or '—', r['new_value'] or r['body'] or '—')
            out.append(_event(r['created_at'], r['actor'] or ('Cliente' if r['kind'] == 'mensaje_cliente' else ''), text, 'estado' if r['kind'] == 'estado' else 'evento'))
    elif module == 'licenses' and admin:
        for r in c.execute("SELECT e.event,e.detail,e.created_at,COALESCE(u.name,NULLIF(e.actor,''),'') actor FROM license_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.unit_id=? ORDER BY e.id DESC LIMIT 25", (ref['unit_id'],)):
            out.append(_event(r['created_at'], r['actor'], r['detail'] or r['event']))
    return out


def _context(c, user, item, now):
    """Datos mínimos para las acciones del panel. Los permisos reales los vuelve a comprobar cada endpoint al ejecutar."""
    admin, ref, module = user['role'] == 'administrador', item.get('ref') or {}, item['module']
    ctx = {'admin': admin}
    staff = lambda: [{'id': r['id'], 'name': r['name']} for r in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN ('administrador','tecnico') ORDER BY name")]
    if module == 'orders':
        row = c.execute("SELECT o.status,o.revision,o.assigned_to,o.estimated_delivery,COALESCE(o.problem,'') problem,COALESCE(o.findings,'') findings,COALESCE(o.recommendations,'') recommendations,s.label FROM orders o "
                        "JOIN statuses s ON s.code=o.status WHERE o.id=?", (ref['order_id'],)).fetchone()
        ctx.update(status=row['status'], status_label=row['label'], revision=row['revision'], assigned_to=row['assigned_to'], estimated_delivery=row['estimated_delivery'],
                   problem=row['problem'][:600], findings=row['findings'], recommendations=row['recommendations'],
                   quotes=[{'id': q['id'], 'code': q['code'], 'status': q['status']} for q in
                           c.execute("SELECT id,code,status FROM quotes WHERE order_id=? AND deleted_at='' ORDER BY id DESC LIMIT 5", (ref['order_id'],))])
        if admin:
            ctx['statuses'] = [{'code': r['code'], 'label': r['label']} for r in c.execute('SELECT code,label FROM statuses ORDER BY rowid')]
            ctx['staff'] = staff()
    elif module == 'parts' and ref.get('request_id'):
        import order_part_requests as parts
        row = c.execute('SELECT * FROM order_part_requests WHERE id=?', (ref['request_id'],)).fetchone()
        steps = parts.flow(row)
        here = steps.index(parts.fine(row)) if parts.fine(row) in steps else -1
        nxt = steps[here + 1] if 0 <= here < len(steps) - 1 else ''
        ctx.update(stage=parts.fine(row), stage_label=parts.step_label(parts.fine(row), row['shipping']), next=nxt, next_label=parts.step_label(nxt, row['shipping']) if nxt else '',
                   situation=row['incident'] or row['situation'], eta=row['eta'] or '', received=parts.CODES.index(row['stage']) >= parts.CODES.index('recibido'),
                   situations=[{'code': k, 'label': v[0]} for k, v in parts.SITUATIONS.items() if k != 'cancelado'] +
                   [{'code': k, 'label': v[0]} for k, v in getattr(parts, 'INCIDENTS', {}).items()])
    elif module == 'messages' and ref.get('kind') == 'pqrs':
        import pqrs
        row = c.execute('SELECT status,assigned_to FROM pqrs_cases WHERE id=?', (ref['pqrs_id'],)).fetchone()
        allowed = [s for s in pqrs.STATUSES if s != 'cerrada'] if admin else list(pqrs.TECH_STATUSES)
        ctx.update(status=row['status'], assigned_to=row['assigned_to'], statuses=[{'code': k, 'label': pqrs.STATUS_LABELS[k][0]} for k in allowed])
        if admin:
            ctx['staff'] = staff()
    elif module == 'alerts':
        ctx.update(can_silence=bool(ref.get('can_silence')), incident=ref.get('incident', ''), severity=ref.get('severity', ''), source=ref.get('source', ''),
                   delivery_id=ref.get('delivery_id'), recipient=ref.get('recipient', ''), count=ref.get('count', 1))
    # 1.5.289 · Responsable del seguimiento (salvo órdenes y PQRS, que se asignan en su módulo). Administración asigna; un técnico puede
    # tomar un pendiente sin responsable. El servidor comprueba al asignar que la persona elegida ya tenga acceso a ese pendiente.
    owned = module == 'orders' or (module == 'messages' and ref.get('kind') == 'pqrs')
    ctx['follow_owner'] = not owned
    if not owned and admin:
        roles = ('administrador',) if module in ADMIN_ONLY else ('administrador', 'tecnico')
        ctx['assignees'] = [{'id': r['id'], 'name': r['name']} for r in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN (%s) ORDER BY name" % ','.join('?' * len(roles)), roles)]
    ctx['can_take'] = not owned and not admin and item.get('responsible_id') is None
    ctx['can_postpone'] = item['priority'] != 'critico'
    return ctx


def detail(c, user, now, wanted, notices=()):
    """Panel «Gestionar pendiente»: el pendiente, su actividad en el módulo de origen, su registro de gestión y los datos para actuar."""
    item = find(c, user, now, wanted, notices)
    if not item:
        return None
    admin = user['role'] == 'administrador'
    try:
        history = _history(c, item, admin)
    except Exception as error:
        print('pendientes historial', item['module'], type(error).__name__, flush=True)
        history = []
    managed = notes(c, [item['entity']])
    log = [dict(_event(n['created_at'], n['actor'], NOTE_KINDS[n['kind']] + (': ' + n['body'] if n['body'] else '') + (' (hasta ' + n['until'][:16].replace('T', ' ') + ')' if n['until'] else ''), 'gestion'),
                note_kind=n['kind']) for n in (managed or [])]
    tracked = tracking(c, [item['entity']])
    for t in tracked or []:
        text = TRACK_KINDS[t['kind']] + (': ' + (t['assignee'] or 'Sin asignar') if t['kind'] == 'asignacion' else ' hasta ' + t['until'] if t['kind'] == 'pospuesto' else '')
        log.append(dict(_event(t['created_at'], t['actor'], text + (' · ' + t['body'] if t['body'] else ''), 'gestion'), note_kind=t['kind']))
    history = sorted(history + log, key=lambda e: e['at'], reverse=True)[:40]
    return {'item': item, 'history': history, 'notes': [dict(n, label=NOTE_KINDS[n['kind']]) for n in reversed(managed or []) if n['kind'] == 'nota'],
            'managed': managed is not None, 'tracked': tracked is not None, 'context': _context(c, user, item, now)}


# ---- Centro de actividad: lo que hizo el equipo, con persona, fecha y hora exactas. Solo lectura. ----
AUDIT_LABELS = {
    'order_status_updated': ('orders', 'Estado de la orden actualizado'), 'order_follow_up': ('orders', 'Observación técnica registrada'),
    'order_assigned': ('orders', 'Responsable de la orden asignado'), 'order_workspace_updated': ('orders', 'Seguimiento técnico de la orden actualizado'),
    'delivery_reverted': ('orders', 'Entrega revertida'), 'delivery_balance_authorized': ('orders', 'Entrega con saldo autorizada'),
    'appointment_confirmada': ('appointments', 'Cita confirmada'), 'appointment_cancelada': ('appointments', 'Cita cancelada'), 'appointment_reschedule': ('appointments', 'Cita reprogramada'),
    'appointment_completada': ('appointments', 'Cita completada'), 'appointment_no_asistio': ('appointments', 'Cita marcada «No asistió»'), 'appointment_presente': ('appointments', 'Cliente en atención'),
    'appointment_edit': ('appointments', 'Cita editada'), 'appointment_delete': ('appointments', 'Cita eliminada'), 'appointment_authorized': ('appointments', 'Autorización del cliente registrada'),
    'appointment_reactivated': ('appointments', 'Cita reactivada'), 'appointment_created': ('appointments', 'Cita registrada por el personal'),
    'quote_sent': ('quotes', 'Presupuesto enviado al cliente'), 'quote_cancelled': ('quotes', 'Presupuesto cancelado'), 'quote_staff_aprobado': ('quotes', 'Aprobación registrada por el personal'),
    'quote_staff_parcial': ('quotes', 'Aprobación parcial registrada por el personal'), 'quote_staff_rechazado': ('quotes', 'Rechazo registrado por el personal'),
    'quote_decision_notified': ('quotes', 'Confirmación de la decisión enviada'), 'quote_created': ('quotes', 'Presupuesto creado'),
    'order_part_advance': ('parts', 'Etapa del repuesto actualizada'), 'order_part_situation': ('parts', 'Situación del repuesto registrada'), 'order_part_update': ('parts', 'Datos del repuesto actualizados'),
    'order_part_create': ('parts', 'Repuesto solicitado'), 'order_part_cancel_decide': ('parts', 'Cancelación de repuesto decidida'), 'order_part_cancel_direct': ('parts', 'Repuesto cancelado'),
    'order_part_notices_retry': ('parts', 'Reintento de avisos del repuesto'),
    'autocare_check': ('alerts', 'Comprobación de AutoCare repetida'), 'autocare_incident_resuelta': ('alerts', 'Incidencia de AutoCare resuelta'),
    'autocare_incident_en_revision': ('alerts', 'Incidencia de AutoCare en revisión'), 'autocare_diagnose': ('alerts', 'Diagnóstico de AutoCare ejecutado'),
    'pqrs_reply': ('messages', 'Respuesta enviada a una PQRS'), 'pqrs_assign': ('messages', 'PQRS asignada'), 'pqrs_status': ('messages', 'Estado de PQRS actualizado'),
    'pqrs_note': ('messages', 'Nota interna en una PQRS'), 'pqrs_close': ('messages', 'PQRS cerrada'),
    'pending_note': ('', 'Observación interna registrada'), 'pending_ack': ('alerts', 'Alerta reconocida'), 'pending_silence': ('alerts', 'Alerta silenciada temporalmente'),
    'pending_reminder': ('', 'Recordatorio programado'), 'pending_resolution': ('alerts', 'Resolución de alerta registrada'),
    'pending_assign': ('', 'Responsable del seguimiento asignado'), 'pending_postpone': ('', 'Pendiente pospuesto'), 'pending_resume': ('', 'Pendiente reanudado'),
    'pending_rules_updated': ('', 'Reglas de urgencia actualizadas'), 'mail_delivery_reviewed': ('alerts', 'Incidencia de entrega de correo revisada'),
}
ACTIVITY_KINDS = {'accion': 'Acción', 'gestion': 'Gestión del centro', 'estado': 'Cambio de estado', 'lectura': 'Notificación leída', 'error': 'Error o reintento'}


def activity(c, user, now, params, paged=True):
    """Historial del centro: acciones auditadas, cambios de estado de órdenes, gestión registrada y lecturas. Administración ve todo el
    equipo; un técnico, solo lo que hizo él. Filtros: módulo, tipo, persona, desde, hasta y texto. Páginas de 100 filas (carga progresiva);
    sin paginar (CSV), hasta 2000."""
    admin = user['role'] == 'administrador'
    get = lambda key: str(params.get(key, '') or '').strip()
    start, end = get('from') or (now.date() - timedelta(days=30)).isoformat(), get('to') or now.date().isoformat()
    try:
        date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise ValueError('Indica fechas válidas.')
    if start > end:
        raise ValueError('La fecha inicial es posterior a la final.')
    who = int(get('user')) if admin and get('user').isdigit() else None if admin else user['id']
    lo = datetime.combine(date.fromisoformat(start), datetime.min.time(), appointments.TZ)
    hi = datetime.combine(date.fromisoformat(end) + timedelta(days=1), datetime.min.time(), appointments.TZ)
    rows = []
    person = ' AND a.user_id=?' if who else ''
    # La gestión del centro se lee de su propio registro (con el texto); su auditoría no se repite aquí.
    names = [n for n in AUDIT_LABELS if n not in ('pending_note', 'pending_ack', 'pending_silence', 'pending_reminder', 'pending_resolution', 'pending_assign', 'pending_postpone', 'pending_resume')]
    for r in c.execute("SELECT a.action,a.entity_id,a.created_at,a.user_id,COALESCE(u.name,'') actor FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.created_at>=? AND a.created_at<? AND a.action IN (" +
                       ','.join('?' * len(names)) + ")" + person + " ORDER BY a.id DESC LIMIT 600", (int(lo.timestamp()), int(hi.timestamp()), *names, *((who,) if who else ()))):
        module, label = AUDIT_LABELS[r['action']]
        ref = r['entity_id']
        href = ('#orders?id=%d' % ref if module in ('orders', 'quotes', 'parts') else '#appointments?appointment=%d' % ref if module == 'appointments' else
                '#pqrs?id=%d' % ref if r['action'].startswith('pqrs_') else '') if ref and not r['action'].startswith('pending_') else ''
        rows.append({'at': _iso(r['created_at']), 'actor': r['actor'] or 'Sistema', 'module': module or 'orders', 'kind': 'gestion' if r['action'].startswith('pending_') else 'accion',
                     'text': label, 'detail': '', 'ref': ('Registro %d' % ref) if ref else '', 'href': href})
    for r in c.execute("SELECT l.from_status,l.to_status,l.created_at,l.order_id,COALESCE(o.code,'') code,COALESCE(u.name,'') actor,f.label from_label,t.label to_label FROM order_status_log l "
                       "JOIN orders o ON o.id=l.order_id LEFT JOIN users u ON u.id=l.actor_id LEFT JOIN statuses f ON f.code=l.from_status LEFT JOIN statuses t ON t.code=l.to_status "
                       "WHERE l.created_at>=? AND l.created_at<?" + (' AND l.actor_id=?' if who else '') + " ORDER BY l.id DESC LIMIT 400",
                       (lo.isoformat(), hi.isoformat(), *((who,) if who else ()))):
        rows.append({'at': _iso(r['created_at']), 'actor': r['actor'] or 'Sistema', 'module': 'orders', 'kind': 'estado', 'text': 'Orden ' + r['code'] + ': ' + (r['from_label'] or r['from_status'] or 'nueva') + ' → ' + (r['to_label'] or r['to_status']),
                     'detail': '', 'ref': r['code'], 'href': '#orders?id=%d' % r['order_id']})
    managed = notes(c, None, lo.isoformat(timespec='seconds')) or []
    for n in managed:
        if n['created_at'] >= hi.isoformat(timespec='seconds') or (who and n['user_id'] != who):
            continue
        rows.append({'at': n['created_at'], 'actor': n['actor'] or 'Sistema', 'module': n['module'], 'kind': 'gestion', 'text': NOTE_KINDS[n['kind']], 'detail': n['body'],
                     'ref': n['key'], 'href': ''})
    for t in tracking(c, None, lo.isoformat(timespec='seconds')) or []:
        if t['created_at'] >= hi.isoformat(timespec='seconds') or (who and t['user_id'] != who):
            continue
        text = TRACK_KINDS[t['kind']] + (': ' + (t['assignee'] or 'Sin asignar') if t['kind'] == 'asignacion' else ' hasta ' + t['until'] if t['kind'] == 'pospuesto' else '')
        rows.append({'at': t['created_at'], 'actor': t['actor'] or 'Sistema', 'module': t['module'], 'kind': 'gestion', 'text': text, 'detail': t['body'], 'ref': t['key'], 'href': ''})
    for r in c.execute("SELECT r.key,r.read_at,COALESCE(u.name,'') actor FROM notification_reads r LEFT JOIN users u ON u.id=r.user_id WHERE r.read_at>=? AND r.read_at<?" + (' AND r.user_id=?' if who else '') + " ORDER BY r.read_at DESC LIMIT 300",
                       (lo.isoformat(), hi.isoformat(), *((who,) if who else ()))):
        module = r['key'].split(':')[1] if r['key'].startswith('pending:') else 'alerts' if SYSTEM_ALERT.match(r['key']) else ''
        rows.append({'at': _iso(r['read_at']) or r['read_at'], 'actor': r['actor'], 'module': module, 'kind': 'lectura', 'text': 'Marcado como visto', 'detail': '', 'ref': r['key'][:120], 'href': ''})
    if admin and not who:
        try:
            # Envíos fallidos o rebotados y sus reintentos (sin el destinatario: el detalle completo está en Correo).
            for r in c.execute("SELECT kind,status,reason,retry_of,created_at FROM mail_deliveries WHERE created_at>=? AND created_at<? AND (status IN ('fallido','rebotado') OR retry_of IS NOT NULL) ORDER BY id DESC LIMIT 150",
                               (lo.isoformat(), hi.isoformat())):
                retry = r['retry_of'] is not None
                rows.append({'at': _iso(r['created_at']) or r['created_at'], 'actor': 'Sistema', 'module': 'alerts', 'kind': 'error',
                             'text': ('Reintento de envío de correo' if retry else 'Envío de correo no completado') + ' (' + str(r['kind']) + ')',
                             'detail': ('Estado: ' + r['status'] + '. ' if retry else '') + str(r['reason'] or '')[:300], 'ref': '', 'href': '#mail'})
        except Exception as error:
            print('actividad correos', type(error).__name__, flush=True)
    module, kind, q = get('module'), get('kind'), get('q').lower()[:80]
    rows = [r for r in rows if (not module or r['module'] == module) and (not kind or r['kind'] == kind) and (not q or q in ' '.join((r['actor'], r['text'], r['detail'], r['ref'])).lower())]
    rows.sort(key=lambda r: r['at'], reverse=True)
    people = [{'id': r['id'], 'name': r['name']} for r in c.execute("SELECT id,name FROM users WHERE role IN ('administrador','tecnico') ORDER BY name")] if admin else []
    page = max(1, int(get('page'))) if get('page').isdigit() else 1
    chunk = rows[(page - 1) * PAGE:page * PAGE] if paged else rows[:2000]
    return {'rows': chunk, 'total': len(rows), 'page': page, 'more': paged and len(rows) > page * PAGE, 'from': start, 'to': end, 'people': people, 'kinds': ACTIVITY_KINDS, 'modules': MODULES}


def activity_csv(rows):
    """CSV para hoja de cálculo (UTF-8 con BOM). Las celdas que empiezan con = + - @ se neutralizan para que no se ejecuten como fórmulas."""
    import csv
    import io
    out = io.StringIO()
    out.write('\ufeff')
    writer = csv.writer(out)
    safe = lambda v: "'" + v if v[:1] in ('=', '+', '-', '@', '\t', '\r') else v
    writer.writerow(['Fecha y hora', 'Persona', 'Módulo', 'Tipo', 'Acción', 'Detalle', 'Referencia'])
    for r in rows:
        writer.writerow([safe(str(x)) for x in (r['at'].replace('T', ' ')[:19], r['actor'], MODULES.get(r['module'], r['module']), ACTIVITY_KINDS.get(r['kind'], r['kind']), r['text'], r['detail'], r['ref'])])
    return out.getvalue()


# ---- 1.5.289 · Solucionadas: lo que dejó de ser pendiente, leído de los historiales de cada módulo (quién, cuándo y cómo). Solo lectura. ----
OUTCOMES = {'resuelto': 'Resuelto', 'cancelado': 'Cancelado'}
PAGE = 100


def _range(now, params, days=6, limit=92):
    get = lambda key: str(params.get(key, '') or '').strip()
    start, end = get('from') or (now.date() - timedelta(days=days)).isoformat(), get('to') or now.date().isoformat()
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise ValueError('Indica fechas válidas.')
    if first > last:
        raise ValueError('La fecha inicial es posterior a la final.')
    if (last - first).days > limit:
        raise ValueError('Consulta como máximo %d días a la vez.' % limit)
    lo = datetime.combine(first, datetime.min.time(), appointments.TZ)
    hi = datetime.combine(last + timedelta(days=1), datetime.min.time(), appointments.TZ)
    return start, end, lo, hi


def resolved(c, user, now, params):
    """Pendientes solucionados en el período: órdenes entregadas, citas confirmadas o cerradas, presupuestos decididos o cancelados,
    repuestos instalados o cancelados, PQRS respondidas o cerradas, respuestas de mantenimiento gestionadas, licencias renovadas e
    incidencias de AutoCare resueltas. Administración ve a todo el equipo (y puede filtrar por persona); un técnico, lo que resolvió él.
    Varias acciones sobre el mismo registro el mismo día cuentan una vez (la última). Página de 100 filas."""
    admin = user['role'] == 'administrador'
    get = lambda key: str(params.get(key, '') or '').strip()
    start, end, lo, hi = _range(now, params)
    who = int(get('user')) if admin and get('user').isdigit() else None if admin else user['id']
    a, b = lo.isoformat(), hi.isoformat()
    rows = []

    def add(at, module, outcome, title, detail, actor, actor_id, href, ent):
        if who and actor_id != who:
            return
        rows.append({'at': _iso(at) or str(at or ''), 'module': module, 'outcome': outcome, 'title': title, 'detail': detail or '', 'actor': actor or 'Sistema',
                     'href': href, 'entity': ent})

    def safe(name, run):
        try:
            run()
        except Exception as error:
            print('solucionadas', name, type(error).__name__, flush=True)

    def orders():
        for r in c.execute("SELECT l.order_id,l.created_at,l.actor_id,COALESCE(u.name,'') actor,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,cl.name client FROM order_status_log l "
                           "JOIN orders o ON o.id=l.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id LEFT JOIN users u ON u.id=l.actor_id "
                           "WHERE l.to_status='entregado' AND l.created_at>=? AND l.created_at<? ORDER BY l.id DESC LIMIT 400", (a, b)):
            add(r['created_at'], 'orders', 'resuelto', 'Orden ' + r['code'] + ' entregada', r['client'], r['actor'], r['actor_id'], '#orders?id=%d' % r['order_id'], 'orders:%d' % r['order_id'])

    def appointment_rows():
        labels = appointments.STATUSES
        for r in c.execute("SELECT e.appointment_id,e.new_status,e.created_at,e.actor_id,COALESCE(u.name,'') actor,a.public_code,a.customer_name FROM appointment_events e "
                           "JOIN appointments a ON a.id=e.appointment_id LEFT JOIN users u ON u.id=e.actor_id WHERE e.old_status='solicitada' AND e.new_status NOT IN ('','solicitada') "
                           "AND e.created_at>=? AND e.created_at<? ORDER BY e.id DESC LIMIT 400", (a, b)):
            add(r['created_at'], 'appointments', 'cancelado' if r['new_status'] == 'cancelada' else 'resuelto', 'Cita ' + r['public_code'] + ': ' + labels.get(r['new_status'], r['new_status']),
                r['customer_name'], r['actor'], r['actor_id'], '#appointments?appointment=%d' % r['appointment_id'], 'appointments:%d' % r['appointment_id'])

    def quote_rows():
        names = {'aprobado': 'aprobado', 'parcial': 'aprobado parcialmente', 'rechazado': 'rechazado', 'cancelado': 'cancelado'}
        for r in c.execute("SELECT e.quote_id,e.event,e.created_at,e.actor_id,COALESCE(u.name,NULLIF(e.actor,''),'') actor,q.code,q.order_id FROM quote_events e JOIN quotes q ON q.id=e.quote_id "
                           "LEFT JOIN users u ON u.id=e.actor_id WHERE e.event IN ('aprobado','parcial','rechazado','cancelado') AND e.created_at>=? AND e.created_at<? ORDER BY e.id DESC LIMIT 400", (a, b)):
            add(r['created_at'], 'quotes', 'cancelado' if r['event'] == 'cancelado' else 'resuelto', 'Presupuesto ' + r['code'] + ' ' + names[r['event']],
                'Decisión registrada por el personal' if r['actor_id'] else 'Decisión del cliente' if r['event'] != 'cancelado' else '', r['actor'] or ('Cliente' if r['event'] != 'cancelado' else ''),
                r['actor_id'], '#orders?id=%d' % r['order_id'], 'quotes:%d' % r['quote_id'])

    def part_rows():
        for r in c.execute("SELECT e.request_id,e.kind,e.stage,e.situation,e.created_at,e.created_by,COALESCE(u.name,'') actor,p.name,p.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code "
                           "FROM order_part_events e JOIN order_part_requests p ON p.id=e.request_id JOIN orders o ON o.id=p.order_id LEFT JOIN users u ON u.id=e.created_by "
                           "WHERE ((e.kind='etapa' AND e.stage IN ('instalado','listo')) OR (e.kind='situacion' AND e.situation='cancelado')) AND e.created_at>=? AND e.created_at<? ORDER BY e.id DESC LIMIT 400", (a, b)):
            cancelled = r['kind'] == 'situacion'
            add(r['created_at'], 'parts', 'cancelado' if cancelled else 'resuelto', 'Repuesto ' + ('cancelado' if cancelled else 'instalado') + ' · ' + r['code'], (r['name'] or '')[:80],
                r['actor'], r['created_by'], '#orders?id=%d' % r['order_id'], 'parts:%d' % r['request_id'])
        for r in c.execute("SELECT x.id,x.status,x.decided_at,x.decided_by,COALESCE(u.name,'') actor,p.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code FROM order_part_cancellations x "
                           "JOIN order_part_requests p ON p.id=x.request_id JOIN orders o ON o.id=p.order_id LEFT JOIN users u ON u.id=x.decided_by "
                           "WHERE x.status IN ('aprobada','rechazada') AND x.decided_at>=? AND x.decided_at<? ORDER BY x.id DESC LIMIT 200", (a, b)):
            add(r['decided_at'], 'parts', 'resuelto', 'Cancelación de repuesto ' + ('aprobada' if r['status'] == 'aprobada' else 'rechazada') + ' · ' + r['code'], '', r['actor'], r['decided_by'],
                '#orders?id=%d' % r['order_id'], 'parts:cancel:%d' % r['id'])

    def message_rows():
        for r in c.execute("SELECT e.case_id,e.kind,e.new_value,e.created_at,e.actor_id,COALESCE(u.name,'') actor,p.code,p.name FROM pqrs_events e JOIN pqrs_cases p ON p.id=e.case_id "
                           "LEFT JOIN users u ON u.id=e.actor_id WHERE ((e.kind='estado' AND e.new_value IN ('respondida','esperando_cliente','cerrada')) OR e.kind='cierre') "
                           "AND e.created_at>=? AND e.created_at<? ORDER BY e.id DESC LIMIT 400", (a, b)):
            text = 'cerrada' if r['kind'] == 'cierre' or r['new_value'] == 'cerrada' else 'en espera del cliente' if r['new_value'] == 'esperando_cliente' else 'respondida'
            add(r['created_at'], 'messages', 'resuelto', 'PQRS ' + r['code'] + ' ' + text, r['name'], r['actor'], r['actor_id'], '#pqrs?id=%d' % r['case_id'], 'messages:pqrs:%d' % r['case_id'])
        if admin:
            for r in c.execute("SELECT x.id,x.handled_at,x.handled_by,COALESCE(u.name,'') actor,m.order_id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code FROM maintenance_responses x "
                               "JOIN maintenance m ON m.id=x.maintenance_id JOIN orders o ON o.id=m.order_id LEFT JOIN users u ON u.id=x.handled_by "
                               "WHERE x.handled_at>=? AND x.handled_at<? ORDER BY x.id DESC LIMIT 200", (a, b)):
                add(r['handled_at'], 'messages', 'resuelto', 'Respuesta de mantenimiento gestionada · ' + r['code'], '', r['actor'], r['handled_by'], '#maintenance?order=%d' % r['order_id'],
                    'messages:maintenance:%d' % r['id'])

    def license_rows():
        for r in c.execute("SELECT e.unit_id,e.created_at,e.actor_id,COALESCE(u.name,NULLIF(e.actor,''),'') actor,e.detail FROM license_events e LEFT JOIN users u ON u.id=e.actor_id "
                           "WHERE e.event='renovada' AND e.created_at>=? AND e.created_at<? ORDER BY e.id DESC LIMIT 200", (a, b)):
            add(r['created_at'], 'licenses', 'resuelto', 'Licencia renovada', (r['detail'] or '')[:160], r['actor'], r['actor_id'], '#licenses', 'licenses:%s' % r['unit_id'])

    def alert_rows():
        for r in c.execute("SELECT a.entity_id,a.created_at,a.user_id,COALESCE(u.name,'') actor FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.action='autocare_incident_resuelta' "
                           "AND a.created_at>=? AND a.created_at<? ORDER BY a.id DESC LIMIT 200", (int(lo.timestamp()), int(hi.timestamp()))):
            add(r['created_at'], 'alerts', 'resuelto', 'Incidencia de ADI AutoCare resuelta', '', r['actor'], r['user_id'], '#autocare', 'alerts:autocare:%s' % (r['entity_id'] or ''))

    for name, run in (('orders', orders), ('appointments', appointment_rows), ('quotes', quote_rows), ('parts', part_rows), ('messages', message_rows)):
        safe(name, run)
    if admin:
        safe('licenses', license_rows)
        safe('alerts', alert_rows)
    rows.sort(key=lambda r: r['at'], reverse=True)
    unique, seen = [], set()
    for r in rows:
        mark = (r['entity'], r['at'][:10])
        if mark not in seen:
            seen.add(mark)
            unique.append(r)
    module, outcome, q = get('module'), get('outcome'), get('q').lower()[:80]
    unique = [r for r in unique if (not module or r['module'] == module) and (not outcome or r['outcome'] == outcome) and (not q or q in ' '.join((r['title'], r['detail'], r['actor'])).lower())]
    page = max(1, int(get('page'))) if get('page').isdigit() else 1
    people = [{'id': r['id'], 'name': r['name']} for r in c.execute("SELECT id,name FROM users WHERE role IN ('administrador','tecnico') ORDER BY name")] if admin else []
    return {'rows': unique[(page - 1) * PAGE:page * PAGE], 'total': len(unique), 'page': page, 'more': len(unique) > page * PAGE, 'from': start, 'to': end,
            'people': people, 'outcomes': OUTCOMES, 'modules': MODULES}
