"""Indicadores del Centro de Control Técnico.

Todo se calcula con las órdenes registradas: no hay datos simulados ni información económica.
Las fechas se agrupan en la hora de Ecuador."""
from datetime import date, datetime, timedelta

from reception import DEVICE_TYPES, ECUADOR_TZ

PERIODS = {'day': 'Diario', 'week': 'Semanal', 'month': 'Mensual', 'year': 'Anual'}
STATUS_ORDER = ('pendiente', 'reparacion', 'esperando_cliente', 'presupuesto', 'espera_entrega', 'listo', 'entregado')
MAX_BUCKETS = 120
MAX_ROWS = 200


class ReportError(ValueError):
    pass


def _day(value):
    """Fecha local de Ecuador a partir de un entero (época) o un texto ISO; None si no hay dato válido."""
    if value in (None, ''):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, ECUADOR_TZ).date()
        moment = datetime.fromisoformat(str(value))
        return (moment.astimezone(ECUADOR_TZ) if moment.tzinfo else moment).date()
    except (ValueError, OverflowError, OSError):
        return None


def _bucket(day, period):
    if period == 'week':
        return day - timedelta(days=day.weekday())
    if period == 'month':
        return day.replace(day=1)
    if period == 'year':
        return day.replace(month=1, day=1)
    return day


def _next(start, period):
    if period == 'week':
        return start + timedelta(days=7)
    if period == 'month':
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    if period == 'year':
        return start.replace(year=start.year + 1)
    return start + timedelta(days=1)


MONTHS = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')


def _label(start, period):
    if period == 'year':
        return str(start.year)
    if period == 'month':
        return MONTHS[start.month - 1] + ' ' + str(start.year)
    return '%02d %s' % (start.day, MONTHS[start.month - 1])


def parse_filters(query, today):
    """Valida los filtros recibidos por URL. Cualquier valor desconocido se rechaza."""
    arg = lambda name: (query.get(name, [''])[0] or '').strip()
    period = arg('period') or 'day'
    if period not in PERIODS:
        raise ReportError('Periodo inválido.')
    try:
        last = date.fromisoformat(arg('to')) if arg('to') else today
        default = {'day': 29, 'week': 83, 'month': 364, 'year': 365 * 4}[period]
        first = date.fromisoformat(arg('from')) if arg('from') else last - timedelta(days=default)
    except ValueError:
        raise ReportError('Fecha inválida.')
    if first > last:
        raise ReportError('La fecha inicial no puede ser posterior a la final.')
    if (last - first).days > 3660:
        raise ReportError('El rango máximo es de diez años.')
    technician = arg('technician')
    if technician and technician != 'none' and not technician.isdigit():
        raise ReportError('Técnico inválido.')
    kind = arg('type')
    if kind and kind not in DEVICE_TYPES:
        raise ReportError('Tipo de equipo inválido.')
    status = arg('status')
    if status and status not in STATUS_ORDER:
        raise ReportError('Estado inválido.')
    return {'period': period, 'from': first, 'to': last, 'status': status, 'type': kind, 'technician': technician}


def _orders(c):
    rows = c.execute(
        "SELECT o.id,o.code,o.status,o.created_at,o.received_at,o.delivered_at,o.estimated_delivery,o.assigned_to,"
        "COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,cl.name client "
        "FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id ORDER BY o.id")
    result = []
    for row in rows:
        item = dict(row)
        item['received'] = _day(item['received_at']) or _day(item['created_at'])
        item['delivered'] = _day(item['delivered_at']) if item['status'] == 'entregado' else None
        result.append(item)
    return result


def build(c, filters, today):
    statuses = {row['code']: row['label'] for row in c.execute('SELECT code,label FROM statuses')}
    people = {row['id']: row['name'] for row in c.execute("SELECT id,name FROM users WHERE approval='approved'")}
    every = _orders(c)

    def matches(order, skip=()):
        if 'status' not in skip and filters['status'] and order['status'] != filters['status']:
            return False
        if filters['type'] and order['type'] != filters['type']:
            return False
        if filters['technician']:
            if filters['technician'] == 'none':
                if order['assigned_to']:
                    return False
            elif str(order['assigned_to'] or '') != filters['technician']:
                return False
        return True

    first, last, period = filters['from'], filters['to'], filters['period']
    in_range = lambda day: bool(day) and first <= day <= last
    scoped = [order for order in every if matches(order)]
    received = [order for order in scoped if in_range(order['received'])]

    # Indicadores: recibidas y entregadas en el rango; activas, listas y vencidas según el estado actual.
    delivered = [order for order in scoped if in_range(order['delivered'])]
    spans = [(order['delivered'] - order['received']).days for order in delivered if order['received'] and order['delivered'] >= order['received']]
    active = [order for order in scoped if order['status'] != 'entregado']
    overdue = [order for order in active if (_day(order['estimated_delivery']) or today) < today]
    kpis = {'received': len(received), 'delivered': len(delivered), 'active': len(active),
            'ready': sum(1 for order in active if order['status'] in ('listo', 'espera_entrega')),
            'overdue': len(overdue), 'average_days': round(sum(spans) / len(spans), 1) if spans else None, 'average_sample': len(spans)}

    # Distribución por estado de las órdenes recibidas en el rango (sin aplicar el filtro de estado, para poder compararlos).
    base = [order for order in every if matches(order, skip=('status',)) and in_range(order['received'])]
    by_status = [{'code': code, 'label': statuses.get(code, code), 'total': sum(1 for order in base if order['status'] == code)} for code in STATUS_ORDER if code in statuses]

    # Series por periodo.
    start, buckets = _bucket(first, period), []
    while start <= last and len(buckets) < MAX_BUCKETS:
        buckets.append(start)
        start = _next(start, period)
    index = {start: position for position, start in enumerate(buckets)}
    series_received, series_delivered = [0] * len(buckets), [0] * len(buckets)
    for order in received:
        position = index.get(_bucket(order['received'], period))
        if position is not None:
            series_received[position] += 1
    for order in delivered:
        position = index.get(_bucket(order['delivered'], period))
        if position is not None:
            series_delivered[position] += 1
    # Órdenes abiertas al cierre de cada periodo: recibidas hasta esa fecha y aún no entregadas entonces.
    open_series = []
    for start in buckets:
        end = min(_next(start, period) - timedelta(days=1), today)
        open_series.append(None if start > today else sum(1 for order in scoped if order['received'] and order['received'] <= end and not (order['delivered'] and order['delivered'] <= end)))
    periods = {'keys': [start.isoformat() for start in buckets], 'labels': [_label(start, period) for start in buckets],
               'received': series_received, 'delivered': series_delivered, 'open': open_series}

    technicians = {}
    for order in scoped:
        key = order['assigned_to'] or 0
        entry = technicians.setdefault(key, {'id': key, 'name': people.get(key, 'Sin asignar') if key else 'Sin asignar', 'active': 0, 'delivered': 0})
        if order['status'] != 'entregado':
            entry['active'] += 1
        if in_range(order['delivered']):
            entry['delivered'] += 1
    technicians = sorted((entry for entry in technicians.values() if entry['active'] or entry['delivered']), key=lambda entry: (-(entry['active'] + entry['delivered']), entry['name']))

    kinds = {}
    for order in received:
        kinds[order['type']] = kinds.get(order['type'], 0) + 1
    types = sorted(({'code': code, 'label': DEVICE_TYPES.get(code, code or 'Sin tipo'), 'total': total} for code, total in kinds.items()), key=lambda entry: -entry['total'])

    return {'filters': {'period': period, 'from': first.isoformat(), 'to': last.isoformat(), 'status': filters['status'], 'type': filters['type'], 'technician': filters['technician']},
            'today': today.isoformat(), 'kpis': kpis, 'statuses': by_status, 'periods': periods, 'technicians': technicians, 'types': types,
            'options': {'periods': PERIODS, 'statuses': [{'code': code, 'label': statuses[code]} for code in STATUS_ORDER if code in statuses],
                        'types': DEVICE_TYPES, 'technicians': [{'id': key, 'name': name} for key, name in sorted(people.items(), key=lambda pair: pair[1].lower())]}}


def rows(c, filters, today, group, value):
    """Órdenes que componen un segmento o una barra del tablero."""
    every = _orders(c)
    statuses = {row['code']: row['label'] for row in c.execute('SELECT code,label FROM statuses')}
    people = {row['id']: row['name'] for row in c.execute("SELECT id,name FROM users WHERE approval='approved'")}
    first, last, period = filters['from'], filters['to'], filters['period']
    in_range = lambda day: bool(day) and first <= day <= last

    def scoped(order, skip_status=False):
        if not skip_status and filters['status'] and order['status'] != filters['status']:
            return False
        if filters['type'] and order['type'] != filters['type']:
            return False
        if filters['technician'] == 'none':
            return not order['assigned_to']
        return not filters['technician'] or str(order['assigned_to'] or '') == filters['technician']

    if group == 'status':
        if value not in STATUS_ORDER:
            raise ReportError('Estado inválido.')
        chosen = [order for order in every if scoped(order, True) and in_range(order['received']) and order['status'] == value]
    elif group == 'type':
        chosen = [order for order in every if scoped(order) and in_range(order['received']) and (order['type'] or '') == value]
    elif group in ('received', 'delivered'):
        try:
            start = date.fromisoformat(value)
        except ValueError:
            raise ReportError('Periodo inválido.')
        chosen = [order for order in every if scoped(order) and in_range(order[group]) and _bucket(order[group], period) == start]
    elif group == 'technician':
        if not value.isdigit():
            raise ReportError('Técnico inválido.')
        chosen = [order for order in every if scoped(order) and (order['assigned_to'] or 0) == int(value) and (order['status'] != 'entregado' or in_range(order['delivered']))]
    elif group == 'kpi':
        base = [order for order in every if scoped(order)]
        if value == 'received':
            chosen = [order for order in base if in_range(order['received'])]
        elif value == 'delivered':
            chosen = [order for order in base if in_range(order['delivered'])]
        elif value == 'active':
            chosen = [order for order in base if order['status'] != 'entregado']
        elif value == 'ready':
            chosen = [order for order in base if order['status'] in ('listo', 'espera_entrega')]
        elif value == 'overdue':
            chosen = [order for order in base if order['status'] != 'entregado' and (_day(order['estimated_delivery']) or today) < today]
        else:
            raise ReportError('Indicador inválido.')
    else:
        raise ReportError('Agrupación inválida.')
    chosen.sort(key=lambda order: -order['id'])
    return {'total': len(chosen), 'rows': [{'id': order['id'], 'code': order['code'] or 'OP-%05d' % order['id'], 'client': order['client'], 'status': statuses.get(order['status'], order['status']),
                                           'status_code': order['status'], 'device': ' '.join(part for part in (DEVICE_TYPES.get(order['type'], order['type'] or ''), order['brand'] or '', order['model'] or '') if part),
                                           'type': order['type'], 'responsible': people.get(order['assigned_to'], 'Sin asignar') if order['assigned_to'] else 'Sin asignar',
                                           'received': order['received'].isoformat() if order['received'] else '', 'delivered': order['delivered'].isoformat() if order['delivered'] else ''} for order in chosen[:MAX_ROWS]]}
