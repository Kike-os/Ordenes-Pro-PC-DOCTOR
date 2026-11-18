"""Licencias Pro Premium 4.0 (1.5.290): control de vigencias, seguimiento comercial de renovaciones, dispositivos y reportes.

Se apoya en licenses.py (inventario, credenciales selladas, activación, vencimientos y renovación) sin cambiar sus reglas:
- Tres estados separados para evitar contradicciones: inventario (disponible, reservada, entregada, anulada, vencida sin vender),
  activación (sin activar, activada, no aplica) y vigencia (vigente, por vencer, vencida, renovada, perpetua, sin fecha, anulada).
- Seguimiento comercial por ciclo (licencia + fecha de vencimiento): sin contactar, contactado, esperando respuesta, aceptado y
  rechazado se registran (solo anexado); «completado» lo da la renovación registrada. Aceptar NO cambia la vigencia: la vigencia solo
  cambia al registrar la renovación con su fecha efectiva (licenses.renew).
- Nada aquí envía correos ni mensajes: «Contactar» abre el teléfono, WhatsApp o el correo de la persona que gestiona.
- Las credenciales nunca salen de estas consultas.
"""
import json
import re
from datetime import date, timedelta

import licenses
from licenses import LicenseError, stamp

FOLLOW = {'sin_contactar': 'Sin contactar', 'contactado': 'Contactado', 'esperando_respuesta': 'Esperando respuesta', 'aceptado': 'Aceptado',
          'rechazado': 'Rechazado', 'completado': 'Completado'}
CHANNELS = {'telefono': 'Teléfono', 'whatsapp': 'WhatsApp', 'correo': 'Correo', 'presencial': 'Presencial', 'otro': 'Otro'}
INVENTORY = {'disponible': 'Disponible', 'reservada': 'Reservada', 'entregada': 'Entregada', 'anulada': 'Anulada', 'vencida': 'Vencida sin vender'}
ACTIVATION = {'sin_activar': 'Sin activar', 'activada': 'Activada', 'no_aplica': 'No aplica'}
VALIDITY = {'vigente': 'Vigente', 'por_vencer': 'Próxima a vencer', 'vencida': 'Vencida', 'renovada': 'Renovada', 'perpetua': 'Perpetua',
            'sin_fecha': 'Sin fecha aplicable', 'anulada': 'Anulada'}
# Semáforo: verde activa, amarillo próxima a vencer, rojo vencida, gris sin activar o sin fecha aplicable.
LIGHT = {'vigente': 'verde', 'por_vencer': 'amarillo', 'vencida': 'rojo'}
WINDOW_DAYS = 90   # el seguimiento comercial muestra lo que vence dentro de este margen (o ya venció) y lo gestionado en el ciclo


def _has(c, table):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _ready(c, table):
    if not _has(c, table):
        raise LicenseError('Esta función necesita una actualización de la base de datos que todavía no se aplicó. Avisa a administración.', 503)


def axes(row, today, soon):
    """Estados de inventario, activación y vigencia de una unidad (y su semáforo). Nunca se contradicen: cada uno mira su propio dato."""
    status = row['status']
    inventory = status if status in INVENTORY else 'disponible'
    delivered = status in ('entregada', 'reservada')
    activation = ('activada' if row.get('activated') else 'sin_activar') if delivered else 'no_aplica'
    days = (date.fromisoformat(row['expires_at']) - today).days if row.get('expires_at') else None
    if status == 'anulada':
        validity = 'anulada'
    elif row.get('renewed_to'):
        validity = 'renovada'
    elif row.get('duration') == 'perpetua':
        validity = 'perpetua'
    elif days is None:
        validity = 'sin_fecha'
    elif days < 0:
        validity = 'vencida'
    elif days <= soon:
        validity = 'por_vencer'
    else:
        validity = 'vigente'
    light = 'gris' if activation == 'sin_activar' else LIGHT.get(validity, 'gris')
    return {'inventory': inventory, 'inventory_label': INVENTORY[inventory], 'activation': activation, 'activation_label': ACTIVATION[activation],
            'validity': validity, 'validity_label': VALIDITY[validity], 'light': light, 'days_left': days}


def with_axes(c, rows, now):
    soon = licenses.display_settings(c)['soon_days']
    for row in rows:
        row['axes'] = axes(row, now.date(), soon)
    return rows


# ---- Días de aviso interno (configurables entre los permitidos por el registro de alertas) ----
def alert_days(c):
    row = c.execute("SELECT value FROM system_state WHERE key='license_alert_days'").fetchone()
    try:
        stored = json.loads(row[0]) if row else None
    except ValueError:
        stored = None
    chosen = sorted({d for d in stored if d in licenses.ALERT_DAYS}, reverse=True) if isinstance(stored, list) else []
    return chosen or list(licenses.ALERT_DAYS)


def save_alert_days(c, data, user, now):
    raw = str(data.get('days', ''))
    days = sorted({int(x) for x in re.split(r'[,; ]+', raw) if x.strip().isdigit()}, reverse=True)
    if not days or any(d not in licenses.ALERT_DAYS for d in days):
        raise LicenseError('Elige al menos un aviso entre 30, 15, 7 y 1 días antes, o el día del vencimiento.', fields={'days': 'Días no válidos.'})
    c.execute("INSERT INTO system_state(key,value) VALUES ('license_alert_days',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(days),))
    licenses.event(c, 'configuracion', now, 'Avisos internos de vencimiento: %s.' % ', '.join('el día del vencimiento' if d == 0 else '%d días antes' % d for d in days), user=user)
    return alert_days(c)


# ---- Seguimiento comercial de renovaciones ----
def _completed(c, unit_id, expires_at):
    row = c.execute('SELECT n.created_at,COALESCE(u.name,\'\') actor FROM license_renewals n LEFT JOIN users u ON u.id=n.created_by WHERE n.unit_id=? AND n.previous_expires_at=? ORDER BY n.id DESC LIMIT 1',
                    (unit_id, expires_at)).fetchone()
    return dict(row) if row else None


def followups(c, unit_id, expires_at=None):
    if not _has(c, 'license_followups'):
        return []
    sql, args = ("SELECT f.*,COALESCE(u.name,'') actor FROM license_followups f LEFT JOIN users u ON u.id=f.user_id WHERE f.unit_id=?", [unit_id])
    if expires_at is not None:
        sql += ' AND f.expires_at=?'
        args.append(expires_at)
    return [dict(r, status_label=FOLLOW[r['status']], channel_label=CHANNELS.get(r['channel'], '')) for r in c.execute(sql + ' ORDER BY f.id DESC', args)]


def cycle(c, unit, renewed=None):
    """Estado comercial del ciclo vigente de la licencia (su fecha de vencimiento actual)."""
    expires = unit['expires_at'] or ''
    done = renewed if renewed is not None else (_completed(c, unit['id'], expires) if expires else None)
    rows = followups(c, unit['id'], expires) if expires else []
    last = rows[0] if rows else None
    status = 'completado' if done or unit.get('renewed_to') else last['status'] if last else 'sin_contactar'
    return {'expires_at': expires, 'status': status, 'status_label': FOLLOW[status], 'last': last, 'next_contact': last['next_contact'] if last else '',
            'count': len(rows), 'completed': done}


def record_followup(c, unit_id, data, user, now):
    """Registra una gestión comercial del ciclo actual. Validaciones: el ciclo debe tener vencimiento y no estar renovado; contactar exige
    canal; aceptar o rechazar exigen nota; el próximo contacto es desde hoy y dentro de un año. Repetir lo mismo en 15 s no duplica."""
    _ready(c, 'license_followups')
    unit = licenses.unit_row(c, unit_id)
    if unit['status'] != 'entregada':
        raise LicenseError('El seguimiento de renovación es para licencias entregadas a un cliente.', 409)
    if not unit['expires_at']:
        raise LicenseError('Esta licencia no tiene vencimiento (perpetua o sin activar): no hay renovación que gestionar.', 409)
    state = cycle(c, unit)
    if state['status'] == 'completado':
        raise LicenseError('Este ciclo ya se renovó. El seguimiento continúa en el próximo vencimiento.', 409)
    status = str(data.get('status', ''))
    if status not in FOLLOW or status == 'completado':
        raise LicenseError('Elige el estado del seguimiento.', fields={'status': 'Estado no válido.'})
    channel = str(data.get('channel', '') or '')
    if channel and channel not in CHANNELS:
        raise LicenseError('Elige un canal válido.', fields={'channel': 'Canal no válido.'})
    if status in ('contactado', 'esperando_respuesta') and not channel:
        raise LicenseError('Indica por qué canal se contactó al cliente.', fields={'channel': 'Obligatorio.'})
    note = re.sub(r'[ \t]+', ' ', str(data.get('note', '') or '')).strip()
    if len(note) > 1000:
        raise LicenseError('La nota admite hasta 1000 caracteres.', fields={'note': 'Demasiado larga.'})
    if status in ('aceptado', 'rechazado') and len(note) < 5:
        raise LicenseError('Indica cómo comunicó el cliente su decisión (al menos 5 caracteres).', fields={'note': 'Obligatorio.'})
    nxt = str(data.get('next_contact', '') or '')
    if nxt:
        try:
            day = date.fromisoformat(nxt)
        except ValueError:
            raise LicenseError('Indica una fecha válida para el próximo contacto.', fields={'next_contact': 'Fecha no válida.'})
        if day < now.date() or day > now.date() + timedelta(days=365):
            raise LicenseError('El próximo contacto debe ser desde hoy y dentro del próximo año.', fields={'next_contact': 'Fuera de rango.'})
        if status in ('rechazado',):
            nxt = ''
    last = state['last']
    since = stamp(now - timedelta(seconds=15))
    if last and last['status'] == status and last['channel'] == channel and last['note'] == note and last['next_contact'] == nxt and last['user_id'] == user['id'] and last['created_at'] >= since:
        return {'ok': True, 'duplicate': True, 'cycle': cycle(c, unit)}
    c.execute('INSERT INTO license_followups(unit_id,expires_at,status,channel,note,next_contact,user_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (unit_id, unit['expires_at'], status, channel, note, nxt, user['id'], stamp(now)))
    licenses.event(c, 'seguimiento', now, 'Renovación (vence %s): %s%s%s%s' % (unit['expires_at'], FOLLOW[status], ' por ' + CHANNELS[channel].lower() if channel else '',
                                                                           ' · ' + note[:200] if note else '', ' · próximo contacto ' + nxt if nxt else ''),
                   unit_id, unit['product_id'], order=unit['order_id'], client=unit['client_id'], user=user)
    return {'ok': True, 'cycle': cycle(c, unit)}


def _contact(row):
    phone = re.sub(r'\D', '', row.get('client_phone') or '')
    wa = ('593' + phone[1:] if phone.startswith('0') else phone) if len(phone) >= 9 else ''
    return {'phone': row.get('client_phone') or '', 'email': row.get('client_email') or '', 'whatsapp': wa}


def pipeline(c, now):
    """Renovaciones: licencias entregadas que vencen dentro del margen (o ya vencieron) y las renovadas en los últimos 30 días,
    con su estado comercial, último contacto y próximo contacto. Incluye los contadores por estado."""
    today, soon = now.date(), licenses.display_settings(c)['soon_days']
    limit = (today + timedelta(days=max(WINDOW_DAYS, soon))).isoformat()
    rows = []
    for r in c.execute("SELECT u.id,u.code,u.product_id,i.name product,u.expires_at,u.activated,u.activated_at,u.status,u.renewed_to,u.client_id,COALESCE(p.duration,'') duration,"
                       "COALESCE(cl.name,'') client,COALESCE(cl.phone,'') client_phone,COALESCE(cl.email,'') client_email FROM license_units u JOIN catalog_items i ON i.id=u.product_id "
                       "LEFT JOIN license_products p ON p.item_id=u.product_id LEFT JOIN clients cl ON cl.id=u.client_id "
                       "WHERE u.status='entregada' AND u.expires_at!='' AND u.renewed_to IS NULL AND u.expires_at<=? ORDER BY u.expires_at", (limit,)):
        row = dict(r)
        state = cycle(c, row)
        row.update(axes=axes(row, today, soon), cycle=state, contact=_contact(row))
        rows.append(row)
    since = stamp(now - timedelta(days=30))
    for r in c.execute("SELECT n.unit_id id,n.previous_expires_at,n.expires_at new_expires_at,n.created_at,COALESCE(us.name,'') actor,u.code,i.name product,COALESCE(cl.name,'') client,u.client_id "
                       "FROM license_renewals n JOIN license_units u ON u.id=n.unit_id JOIN catalog_items i ON i.id=u.product_id LEFT JOIN clients cl ON cl.id=u.client_id "
                       "LEFT JOIN users us ON us.id=n.created_by WHERE n.created_at>=? ORDER BY n.id DESC LIMIT 100", (since,)):
        row = dict(r)
        row['cycle'] = {'status': 'completado', 'status_label': FOLLOW['completado'], 'expires_at': row['previous_expires_at'], 'completed': {'created_at': row['created_at'], 'actor': row['actor']}}
        row['axes'] = {'light': 'verde', 'validity': 'renovada', 'validity_label': VALIDITY['renovada'], 'days_left': None}
        rows.append(row)
    counts = {k: 0 for k in FOLLOW}
    for row in rows:
        counts[row['cycle']['status']] += 1
    return {'rows': rows, 'counts': counts, 'statuses': FOLLOW, 'channels': CHANNELS, 'alert_days': alert_days(c), 'allowed_days': list(licenses.ALERT_DAYS),
            'soon_days': soon, 'ready': _has(c, 'license_followups')}


# ---- Dispositivos registrados ----
def devices(c, unit_id):
    if not _has(c, 'license_devices'):
        return []
    return [dict(r) for r in c.execute("SELECT d.*,COALESCE(a.name,'') added_name,COALESCE(b.name,'') removed_name FROM license_devices d LEFT JOIN users a ON a.id=d.added_by "
                                       "LEFT JOIN users b ON b.id=d.removed_by WHERE d.unit_id=? ORDER BY d.removed_at!='',d.id DESC", (unit_id,))]


def add_device(c, unit_id, data, user, now):
    """Equipo en el que se instaló la licencia. Respeta los dispositivos permitidos y no repite el mismo equipo activo."""
    _ready(c, 'license_devices')
    unit = licenses.unit_row(c, unit_id)
    if unit['status'] not in ('entregada', 'reservada'):
        raise LicenseError('Solo se registran equipos en licencias asignadas o entregadas.', 409)
    device = None
    raw = str(data.get('device_id', '') or '')
    if raw:
        device = c.execute("SELECT d.id,d.client_id,TRIM(COALESCE(d.brand,'')||' '||COALESCE(d.model,'')) label,COALESCE(d.serial,'') serial FROM devices d WHERE d.id=?",
                           (int(raw),)).fetchone() if raw.isdigit() else None
        if not device:
            raise LicenseError('Equipo no encontrado.', 404, {'device_id': 'No válido.'})
        if unit['client_id'] and device['client_id'] != unit['client_id']:
            raise LicenseError('Ese equipo pertenece a otro cliente.', 409, {'device_id': 'De otro cliente.'})
    label = re.sub(r'\s+', ' ', str(data.get('label', '') or (device['label'] if device else ''))).strip()
    serial = re.sub(r'\s+', ' ', str(data.get('serial', '') or (device['serial'] if device else ''))).strip()
    if not 2 <= len(label) <= 120:
        raise LicenseError('Describe el equipo (por ejemplo: Portátil HP de recepción).', fields={'label': 'Obligatorio.'})
    if len(serial) > 80:
        raise LicenseError('La serie admite hasta 80 caracteres.', fields={'serial': 'Demasiado larga.'})
    active = [d for d in devices(c, unit_id) if not d['removed_at']]
    if unit['devices'] and len(active) >= unit['devices']:
        raise LicenseError('Esta licencia permite %d dispositivo%s y ya están registrados. Retira uno antes de añadir otro.' % (unit['devices'], '' if unit['devices'] == 1 else 's'), 409)
    if any((device and d['device_id'] == device['id']) or (serial and d['serial'].lower() == serial.lower()) for d in active):
        raise LicenseError('Ese equipo ya está registrado en esta licencia.', 409)
    did = c.execute('INSERT INTO license_devices(unit_id,device_id,label,serial,added_by,added_at) VALUES (?,?,?,?,?,?)',
                    (unit_id, device['id'] if device else None, label, serial, user['id'], stamp(now))).lastrowid
    licenses.event(c, 'dispositivo', now, 'Equipo registrado: %s%s.' % (label, ' (serie ' + serial + ')' if serial else ''), unit_id, unit['product_id'], client=unit['client_id'], user=user)
    return {'ok': True, 'id': did, 'devices': devices(c, unit_id)}


def remove_device(c, unit_id, data, user, now):
    _ready(c, 'license_devices')
    unit = licenses.unit_row(c, unit_id)
    raw = str(data.get('device', '') or '')
    row = c.execute("SELECT * FROM license_devices WHERE id=? AND unit_id=?", (int(raw), unit_id)).fetchone() if raw.isdigit() else None
    if not row:
        raise LicenseError('Equipo no encontrado en esta licencia.', 404)
    if row['removed_at']:
        return {'ok': True, 'duplicate': True, 'devices': devices(c, unit_id)}
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if not 5 <= len(reason) <= 300:
        raise LicenseError('Indica el motivo del retiro (al menos 5 caracteres).', fields={'reason': 'Obligatorio.'})
    c.execute("UPDATE license_devices SET removed_at=?,removed_by=?,removed_reason=? WHERE id=? AND removed_at=''", (stamp(now), user['id'], reason, row['id']))
    licenses.event(c, 'dispositivo', now, 'Equipo retirado: %s · %s.' % (row['label'], reason), unit_id, unit['product_id'], client=unit['client_id'], user=user)
    return {'ok': True, 'devices': devices(c, unit_id)}


# ---- Expediente ----
def dossier(c, unit_id, now):
    """Ficha completa de una licencia para el panel lateral: datos, tres estados, ciclo comercial, dispositivos, renovaciones e historial.
    Sin credenciales (se consultan aparte, una a una y con registro)."""
    rows = [r for r in licenses.units(c, now) if r['id'] == unit_id]
    if not rows:
        raise LicenseError('Licencia no disponible.', 404)
    row = with_axes(c, rows, now)[0]
    client = c.execute("SELECT name,COALESCE(phone,'') phone,COALESCE(email,'') email FROM clients WHERE id=?", (row['client_id'],)).fetchone() if row['client_id'] else None
    contact = _contact({'client_phone': client['phone'], 'client_email': client['email']}) if client else {}
    devs = devices(c, unit_id)
    return {'unit': row, 'cycle': cycle(c, row) if row['status'] == 'entregada' and row['expires_at'] else None, 'followups': followups(c, unit_id),
            'devices': devs, 'devices_active': sum(1 for d in devs if not d['removed_at']), 'renewals': licenses.renewals(c, unit_id),
            'history': licenses.history(c, 60, unit_id), 'contact': contact, 'statuses': FOLLOW, 'channels': CHANNELS,
            'ready': {'followups': _has(c, 'license_followups'), 'devices': _has(c, 'license_devices')}}


# ---- Reportes ----
REPORTS = {'disponibles': 'Licencias disponibles', 'asignadas': 'Licencias asignadas', 'activas': 'Licencias activas', 'proximas': 'Próximos vencimientos',
           'vencidas': 'Licencias vencidas', 'renovaciones': 'Renovaciones realizadas', 'pendientes': 'Renovaciones pendientes', 'vendidos': 'Productos más vendidos',
           'ingresos': 'Ingresos por renovaciones', 'multiples': 'Clientes con varias licencias'}
UNIT_COLUMNS = [('code', 'Código'), ('product', 'Producto'), ('client', 'Cliente'), ('inventory', 'Inventario'), ('activation', 'Activación'), ('validity', 'Vigencia'),
                ('expires_at', 'Vencimiento'), ('days_left', 'Días'), ('sale', 'Venta u orden')]


def _range(now, params, days=365):
    get = lambda k: str(params.get(k, '') or '').strip()
    start, end = get('from') or (now.date() - timedelta(days=days)).isoformat(), get('to') or now.date().isoformat()
    try:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise LicenseError('La fecha inicial es posterior a la final.')
    except ValueError:
        raise LicenseError('Indica fechas válidas.')
    return start, end


def report(c, now, kind, params):
    """Reportes de solo lectura, sin credenciales. Los importes salen de lo registrado: «Ingresos por renovaciones» suma pagos
    CONFIRMADOS de ventas de licencias de renovación; el precio anotado en la renovación se muestra aparte y no se cuenta como cobro."""
    if kind not in REPORTS:
        raise LicenseError('Reporte no válido.', 404)
    today, soon = now.date(), licenses.display_settings(c)['soon_days']
    product = str(params.get('product', '') or '')
    out = {'kind': kind, 'title': REPORTS[kind], 'generated_at': stamp(now), 'totals': {}}
    if kind in ('disponibles', 'asignadas', 'activas', 'proximas', 'vencidas'):
        rows = with_axes(c, licenses.units(c, now, int(product) if product.isdigit() else None), now)
        test = {'disponibles': lambda a: a['inventory'] == 'disponible',
                'asignadas': lambda a: a['inventory'] in ('reservada', 'entregada'),
                'activas': lambda a: a['activation'] == 'activada' and a['validity'] in ('vigente', 'por_vencer', 'perpetua'),
                'proximas': lambda a: a['inventory'] == 'entregada' and a['validity'] == 'por_vencer',
                'vencidas': lambda a: a['validity'] == 'vencida'}[kind]
        rows = [r for r in rows if test(r['axes'])]
        out['columns'] = UNIT_COLUMNS
        out['rows'] = [{'code': r['code'], 'product': r['product'], 'client': r['client'] or '—', 'inventory': r['axes']['inventory_label'], 'activation': r['axes']['activation_label'],
                        'validity': r['axes']['validity_label'], 'expires_at': r['expires_at'] or '—', 'days_left': '' if r['axes']['days_left'] is None else r['axes']['days_left'],
                        'sale': r['sale_code'] or r['order_code'] or '—', 'light': r['axes']['light'], 'id': r['id']} for r in rows]
        out['totals'] = {'Licencias': len(rows)}
        return out
    if kind == 'pendientes':
        data = pipeline(c, now)
        rows = [r for r in data['rows'] if r['cycle']['status'] not in ('completado', 'rechazado')]
        out['columns'] = [('code', 'Código'), ('product', 'Producto'), ('client', 'Cliente'), ('expires_at', 'Vencimiento'), ('days_left', 'Días'), ('status', 'Seguimiento'), ('next_contact', 'Próximo contacto')]
        out['rows'] = [{'code': r['code'], 'product': r['product'], 'client': r['client'] or '—', 'expires_at': r['expires_at'], 'days_left': r['axes']['days_left'],
                        'status': r['cycle']['status_label'], 'next_contact': r['cycle']['next_contact'] or '—', 'light': r['axes']['light'], 'id': r['id']} for r in rows]
        out['totals'] = {'Pendientes': len(rows)}
        return out
    start, end = _range(now, params)
    hi = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    out.update({'from': start, 'to': end})
    if kind == 'renovaciones':
        rows = [dict(r) for r in c.execute("SELECT n.id,n.created_at,u.code,i.name product,COALESCE(cl.name,'') client,n.previous_expires_at,n.starts_at,n.expires_at,n.key_changed,n.price_cents,"
                                           "COALESCE(us.name,'') actor FROM license_renewals n JOIN license_units u ON u.id=n.unit_id JOIN catalog_items i ON i.id=u.product_id "
                                           "LEFT JOIN clients cl ON cl.id=u.client_id LEFT JOIN users us ON us.id=n.created_by WHERE n.created_at>=? AND n.created_at<? ORDER BY n.id DESC", (start, hi))]
        out['columns'] = [('date', 'Fecha'), ('code', 'Código'), ('product', 'Producto'), ('client', 'Cliente'), ('previous', 'Vencía'), ('new', 'Nueva vigencia'), ('key', 'Clave'), ('actor', 'Registró')]
        out['rows'] = [{'date': r['created_at'][:10], 'code': r['code'], 'product': r['product'], 'client': r['client'] or '—', 'previous': r['previous_expires_at'] or '—',
                        'new': r['starts_at'] + ' → ' + r['expires_at'], 'key': 'Nueva' if r['key_changed'] else 'Misma', 'actor': r['actor'] or 'Sistema'} for r in rows]
        out['totals'] = {'Renovaciones': len(rows)}
        return out
    if kind == 'vendidos':
        rows = [dict(r) for r in c.execute("SELECT it.product_id,it.product_name product,SUM(it.quantity) qty,SUM(it.unit_price_cents*it.quantity-it.discount_cents) total,COUNT(DISTINCT s.id) sales "
                                           "FROM license_sale_items it JOIN license_sales s ON s.id=it.sale_id WHERE s.payment_status!='cancelado' AND s.delivery_status!='cancelado' "
                                           "AND s.created_at>=? AND s.created_at<? GROUP BY it.product_id,it.product_name ORDER BY qty DESC,total DESC LIMIT 50", (start, hi))]
        out['columns'] = [('product', 'Producto'), ('qty', 'Unidades'), ('sales', 'Ventas'), ('total', 'Importe vendido')]
        out['rows'] = [{'product': r['product'], 'qty': r['qty'], 'sales': r['sales'], 'total': licenses.usd(r['total'])} for r in rows]
        out['totals'] = {'Unidades': sum(r['qty'] for r in rows), 'Importe vendido': licenses.usd(sum(r['total'] for r in rows))}
        return out
    if kind == 'ingresos':
        rows = [dict(r) for r in c.execute("SELECT p.paid_on,p.amount_cents,s.code sale,u.code,i.name product,COALESCE(cl.name,'') client FROM license_sale_payments p "
                                           "JOIN license_sales s ON s.id=p.sale_id JOIN license_units u ON u.sale_id=s.id AND u.renewed_from IS NOT NULL JOIN catalog_items i ON i.id=u.product_id "
                                           "LEFT JOIN clients cl ON cl.id=s.client_id WHERE p.status='confirmado' AND p.paid_on>=? AND p.paid_on<? GROUP BY p.id ORDER BY p.paid_on DESC", (start, hi))]
        noted = c.execute('SELECT COUNT(*),COALESCE(SUM(price_cents),0) FROM license_renewals WHERE created_at>=? AND created_at<? AND price_cents IS NOT NULL', (start, hi)).fetchone()
        out['columns'] = [('paid_on', 'Pago confirmado'), ('sale', 'Venta'), ('code', 'Licencia'), ('product', 'Producto'), ('client', 'Cliente'), ('amount', 'Importe')]
        out['rows'] = [{'paid_on': r['paid_on'], 'sale': r['sale'], 'code': r['code'], 'product': r['product'], 'client': r['client'] or '—', 'amount': licenses.usd(r['amount_cents'])} for r in rows]
        out['totals'] = {'Cobrado (pagos confirmados)': licenses.usd(sum(r['amount_cents'] for r in rows)),
                         'Precio anotado en renovaciones (no es cobro)': '%s en %d renovación%s' % (licenses.usd(noted[1]), noted[0], '' if noted[0] == 1 else 'es')}
        return out
    rows = [dict(r) for r in c.execute("SELECT cl.id,cl.name client,COUNT(*) n,SUM(u.status='entregada') delivered,GROUP_CONCAT(DISTINCT i.name) products FROM license_units u "
                                       "JOIN clients cl ON cl.id=u.client_id JOIN catalog_items i ON i.id=u.product_id WHERE u.status IN ('entregada','reservada') "
                                       "GROUP BY cl.id HAVING n>=2 ORDER BY n DESC,cl.name LIMIT 200")]
    out['columns'] = [('client', 'Cliente'), ('n', 'Licencias'), ('delivered', 'Entregadas'), ('products', 'Productos')]
    out['rows'] = [{'client': r['client'], 'n': r['n'], 'delivered': r['delivered'], 'products': (r['products'] or '').replace(',', ', ')[:300]} for r in rows]
    out['totals'] = {'Clientes': len(rows)}
    out.pop('from', None)
    out.pop('to', None)
    return out


def report_csv(data):
    import csv
    import io
    buf = io.StringIO()
    buf.write('﻿')
    writer = csv.writer(buf)
    safe = lambda v: "'" + v if isinstance(v, str) and v[:1] in ('=', '+', '-', '@', '\t', '\r') else v
    writer.writerow([data['title']] + (['%s a %s' % (data['from'], data['to'])] if data.get('from') else []))
    writer.writerow([label for _key, label in data['columns']])
    for row in data['rows']:
        writer.writerow([safe(row.get(key, '')) for key, _label in data['columns']])
    for label, value in data['totals'].items():
        writer.writerow([label, value])
    return buf.getvalue()
