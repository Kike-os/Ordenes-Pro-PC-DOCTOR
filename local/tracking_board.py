"""Seguimiento de Órdenes: una tarjeta por orden con su último movimiento, contadores reales y etapas con evidencia.

No crea ni modifica nada: lee las órdenes y su historial (inmutable). Las etapas solo se marcan como completadas cuando
el historial registra un estado de esa etapa; si falta la evidencia, la etapa queda «sin registro», no completada."""
from datetime import date

from reception import DEVICE_TYPES

PAGE = 8
# Etapas del flujo real y estados configurados que pertenecen a cada una.
STAGES = (('Recibido', ('pendiente',)), ('En proceso', ('reparacion', 'esperando_cliente', 'presupuesto')), ('Listo', ('listo', 'espera_entrega')), ('Entregado', ('entregado',)))
# Contadores superiores, calculados con los estados configurados (no existe un estado «diagnóstico» propio).
COUNTERS = (('pending', 'En espera', ('pendiente',)), ('process', 'En proceso', ('reparacion',)), ('waiting', 'Esperando respuesta', ('esperando_cliente', 'presupuesto')),
            ('ready', 'Listas para entregar', ('listo', 'espera_entrega')), ('done', 'Entregadas', ('entregado',)))


class TrackingError(ValueError):
    pass


def parse(query):
    arg = lambda name: (query.get(name, [''])[0] or '').strip()
    filters = {'q': arg('q')[:80], 'status': arg('status'), 'technician': arg('technician'), 'from': arg('from'), 'to': arg('to'), 'sort': arg('sort') or 'reciente'}
    if filters['sort'] not in ('reciente', 'antiguo'):
        raise TrackingError('Orden inválido.')
    try:
        filters['page'] = max(1, min(500, int(arg('page') or '1')))
        # Tamaño de página: el carrusel del inicio pide bloques pequeños; nunca se entregan más de 50 filas por consulta.
        filters['size'] = int(arg('size') or PAGE)
        if not 3 <= filters['size'] <= 50:
            raise ValueError()
    except ValueError:
        raise TrackingError('Página inválida.')
    for key in ('from', 'to'):
        if filters[key]:
            try:
                date.fromisoformat(filters[key])
            except ValueError:
                raise TrackingError('Fecha inválida.')
    if filters['from'] and filters['to'] and filters['from'] > filters['to']:
        raise TrackingError('La fecha inicial no puede ser posterior a la final.')
    if filters['technician'] and filters['technician'] != 'none' and not filters['technician'].isdigit():
        raise TrackingError('Técnico inválido.')
    return filters


def build(c, filters):
    statuses = {row['code']: row['label'] for row in c.execute('SELECT code,label FROM statuses')}
    if filters['status'] and filters['status'] not in statuses:
        raise TrackingError('Estado inválido.')
    totals = {row['status']: row['total'] for row in c.execute('SELECT status,COUNT(*) total FROM orders GROUP BY status')}
    counters = [{'key': key, 'label': label, 'total': sum(totals.get(code, 0) for code in codes), 'status': codes[0] if len(codes) == 1 else ''} for key, label, codes in COUNTERS]
    where, args = ['1=1'], []
    if filters['q']:
        where.append("instr(lower(COALESCE(o.code,'')||' '||cl.name||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')||' '||s.label||' '||COALESCE(NULLIF(d.kind,''),d.category,'')),lower(?))>0")
        args.append(filters['q'])
    if filters['status']:
        where.append('o.status=?')
        args.append(filters['status'])
    if filters['technician'] == 'none':
        where.append('o.assigned_to IS NULL')
    elif filters['technician']:
        where.append('o.assigned_to=?')
        args.append(int(filters['technician']))
    # El filtro de fecha se aplica al último movimiento registrado de cada orden.
    if filters['from']:
        where.append("substr(COALESCE(h.occurred_at,o.received_at,''),1,10)>=?")
        args.append(filters['from'])
    if filters['to']:
        where.append("substr(COALESCE(h.occurred_at,o.received_at,''),1,10)<=?")
        args.append(filters['to'])
    source = ("FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id "
              "LEFT JOIN users u ON u.id=o.assigned_to LEFT JOIN order_history h ON h.id=(SELECT MAX(x.id) FROM order_history x WHERE x.order_id=o.id) "
              "LEFT JOIN users a ON a.id=h.actor_id WHERE " + ' AND '.join(where))
    total = c.execute('SELECT COUNT(*) ' + source, args).fetchone()[0]
    size = filters.get('size', PAGE)
    pages = max(1, (total + size - 1) // size)
    page = min(filters['page'], pages)
    rows = [dict(row) for row in c.execute(
        "SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status status_code,s.label status,o.priority,o.received_at,o.created_at,cl.name client,COALESCE(cl.phone,'') phone,COALESCE(d.serial,'') serial,"
        "COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,COALESCE(u.name,'') responsible,h.id event_id,h.event,h.comment,h.occurred_at,h.status_label,COALESCE(a.name,'') actor,"
        "(SELECT p.status_label FROM order_history p WHERE p.order_id=o.id AND p.id<h.id AND p.status_label!='' ORDER BY p.id DESC LIMIT 1) previous_label,"
        "(SELECT COUNT(*) FROM order_history x WHERE x.order_id=o.id) events " + source +
        # Orden por fecha del último movimiento: lo más reciente primero (por omisión) o lo más antiguo primero.
        (' ORDER BY COALESCE(h.id,0) ASC,o.id ASC' if filters.get('sort') == 'antiguo' else ' ORDER BY COALESCE(h.id,0) DESC,o.id DESC') + ' LIMIT ? OFFSET ?', (*args, size, (page - 1) * size))]
    seen = {}
    if rows:
        marks = ','.join('?' for _ in rows)
        for item in c.execute('SELECT DISTINCT order_id,status_label FROM order_history WHERE order_id IN (' + marks + ')', [row['id'] for row in rows]):
            seen.setdefault(item['order_id'], set()).add(item['status_label'])
    for row in rows:
        row['type_label'] = DEVICE_TYPES.get(row['type'], '')
        row['stages'] = stages(row['status_code'], seen.get(row['id'], set()), statuses, bool(row['received_at'] or row['created_at']))
    people = [{'id': row['id'], 'name': row['name']} for row in c.execute("SELECT id,name FROM users WHERE approval='approved' AND active=1 ORDER BY name COLLATE NOCASE")]
    return {'counters': counters, 'status_totals': totals, 'total_orders': sum(totals.values()), 'rows': rows, 'total': total, 'page': page, 'pages': pages, 'page_size': size,
            'filters': {key: filters.get(key, '') for key in ('q', 'status', 'technician', 'from', 'to', 'sort')},
            'options': {'statuses': [{'code': code, 'label': label} for code, label in statuses.items()], 'technicians': people}}


def stages(current, labels, statuses, received):
    """Estado de cada etapa: «current» la vigente, «done» con evidencia en el historial, «unrecorded» si quedó atrás sin registro y «pending» las posteriores."""
    position = next((index for index, (_, codes) in enumerate(STAGES) if current in codes), 0)
    out = []
    for index, (label, codes) in enumerate(STAGES):
        evidence = any(statuses.get(code) in labels for code in codes) or (index == 0 and received)
        state = 'current' if index == position else ('done' if evidence else 'unrecorded') if index < position else 'pending'
        out.append({'label': label, 'state': state})
    return out


def history(c, order_id):
    """Todos los movimientos de una orden, del más antiguo al más reciente. Nunca se resumen ni se descartan eventos."""
    import order_workspace
    return list(reversed(order_workspace.history(c, order_id)))
