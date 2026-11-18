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
WINDOW_DAYS = 90
# 1.5.291 · Costo de compra protegido. Roles que pueden consultarlo (hoy, solo administración; los técnicos no lo reciben nunca).
COST_ROLES = ('administrador',)
COST_KEYS = frozenset({'purchase_cents', 'purchase_price', 'unit_cost_cents', 'cost_cents', 'margin_cents', 'margin_pct', 'cost_total_cents', 'cost', 'margin',
                       'margin_total', 'cost_total'})


def costs_allowed(user):
    return bool(user) and user.get('role') in COST_ROLES if isinstance(user, dict) else bool(user) and user['role'] in COST_ROLES


def strip_costs(value):
    """Copia sin costos ni márgenes (en cualquier nivel). Se aplica a las respuestas cuando el costo no se pidió o no está autorizado."""
    if isinstance(value, dict):
        return {k: strip_costs(v) for k, v in value.items() if k not in COST_KEYS}
    if isinstance(value, list):
        return [strip_costs(v) for v in value]
    return value


def reveal_costs(c, user, asked, audit=None):
    """True si se deben enviar los costos: solo si se piden expresamente y la persona está autorizada. Cada consulta queda en la
    auditoría (como mucho una vez cada 10 minutos por persona, para no llenarla con las recargas de la misma pantalla)."""
    if not asked or not costs_allowed(user):
        return False
    if audit:
        import time
        recent = c.execute("SELECT 1 FROM audit WHERE user_id=? AND action='license_costs_viewed' AND created_at>=? LIMIT 1", (user['id'], int(time.time()) - 600)).fetchone()
        if not recent:
            audit(c, user['id'], 'license_costs_viewed')
            c.commit()
    return True   # el seguimiento comercial muestra lo que vence dentro de este margen (o ya venció) y lo gestionado en el ciclo


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
    row = enrich(c, rows, now)[0]
    sale = c.execute('SELECT code,created_at,payment_status,delivery_status FROM license_sales WHERE id=?', (row['sale_id'],)).fetchone() if row.get('sale_id') else None
    row['sale'] = dict(sale) if sale else None
    row['sold_at'] = (sale['created_at'] if sale else '') or row.get('delivered_at') or ''
    client = c.execute("SELECT name,COALESCE(phone,'') phone,COALESCE(email,'') email FROM clients WHERE id=?", (row['client_id'],)).fetchone() if row['client_id'] else None
    contact = _contact({'client_phone': client['phone'], 'client_email': client['email']}) if client else {}
    devs = devices(c, unit_id)
    return {'unit': row, 'cycle': cycle(c, row) if row['status'] == 'entregada' and row['expires_at'] else None, 'followups': followups(c, unit_id),
            'devices': devs, 'devices_active': sum(1 for d in devs if not d['removed_at']), 'renewals': licenses.renewals(c, unit_id),
            'history': licenses.history(c, 60, unit_id), 'contact': contact, 'statuses': FOLLOW, 'channels': CHANNELS, 'stages': STAGES,
            'incidents': incidents(c, unit_id), 'incident_kinds': INCIDENT_KINDS,
            'can_replace': row['status'] in ('entregada', 'reservada') and not row.get('renewed_to') and c.execute(
                "SELECT 1 FROM license_units WHERE product_id=? AND status='disponible' AND id!=? AND (expires_at='' OR expires_at>=?) LIMIT 1", (row['product_id'], unit_id, now.date().isoformat())).fetchone() is not None,
            'ready': {'followups': _has(c, 'license_followups'), 'devices': _has(c, 'license_devices'), 'incidents': _has(c, 'license_incidents')}}


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
    if kind in ('ventas', 'margenes', 'rotacion'):
        if kind in COST_REPORTS and not params.get('costs_visible'):
            raise LicenseError('Este reporte muestra costos: pulsa «Mostrar costo» para consultarlo (solo personal autorizado).', 403)
        return enterprise_report(c, now, kind, params, {'kind': kind, 'title': REPORTS[kind], 'generated_at': stamp(now), 'totals': {}, 'cost_report': kind in COST_REPORTS})
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


# ===== 1.5.291 · Licencias Digitales Premium Enterprise 3.0 =====
LOW_STOCK = 2   # mismo umbral que el catálogo: con 2 o menos disponibles, «stock bajo»
# Ciclo de vida (validado por las acciones del servidor): Disponible → Reservada → Vendida → Entregada → Activada → Vencida,
# con Renovada y Anulada (cancelada, revocada o reemplazada). Una licencia agotada en stock NO es una licencia vencida.
STAGES = {'disponible': 'Disponible', 'reservada': 'Reservada', 'vendida': 'Vendida', 'entregada': 'Entregada', 'activada': 'Activada', 'vencida': 'Vencida',
          'renovada': 'Renovada', 'anulada': 'Anulada'}
INCIDENT_KINDS = {'activacion': 'Error de activación', 'clave_invalida': 'Clave inválida o rechazada', 'dispositivos': 'Límite de dispositivos', 'cliente': 'Solicitud del cliente', 'otro': 'Otra incidencia'}


def stage(row, today):
    status = row['status']
    if status == 'anulada':
        return 'anulada'
    if row.get('renewed_to'):
        return 'renovada'
    if status == 'vencida':
        return 'vencida'
    if status == 'disponible':
        return 'disponible'
    if status == 'reservada':
        return 'vendida' if row.get('sale_payment') == 'pagado' else 'reservada'
    if row.get('expires_at') and row['expires_at'] < today.isoformat():
        return 'vencida'
    return 'activada' if row.get('activated') else 'entregada'


def expiry_info(c, row, today):
    """Vencimiento real (registrado) o estimado (si se activara hoy), claramente diferenciados. Nunca se guarda una estimación."""
    if row.get('expires_at'):
        return {'kind': 'real', 'date': row['expires_at']}
    if row.get('duration') == 'perpetua':
        return {'kind': 'no_aplica', 'date': ''}
    if row['status'] in ('entregada', 'reservada') and not row.get('activated') and (row.get('validity_mode') or 'activacion') == 'activacion':
        months = licenses.months_of({'duration': row.get('duration'), 'duration_months': row.get('duration_months')})
        if months:
            return {'kind': 'estimada', 'date': licenses.add_months(today, months).isoformat()}
    return {'kind': 'pendiente', 'date': ''}


def enrich(c, rows, now):
    """Añade a cada unidad sus tres estados, su etapa del ciclo de vida y el tipo de vencimiento."""
    with_axes(c, rows, now)
    for row in rows:
        row['stage'] = stage(row, now.date())
        row['stage_label'] = STAGES[row['stage']]
        row['expiry'] = expiry_info(c, row, now.date())
    return rows


def filter_units(rows, params):
    get = lambda k: str(params.get(k, '') or '').strip()
    etapa, supplier, kind, modality, maker = get('etapa'), get('proveedor').lower(), get('tipo'), get('modalidad'), get('fabricante').lower()
    if maker:
        rows = [r for r in rows if maker in ((r.get('manufacturer') or '') + ' ' + (r.get('brand') or '')).lower()]
    if etapa:
        rows = [r for r in rows if r['stage'] == etapa or (etapa == 'vendidas' and r['stage'] in ('vendida', 'entregada', 'activada', 'renovada') or
                                                          (etapa == 'vendidas' and r['stage'] == 'vencida' and r['status'] == 'entregada'))
                or (etapa == 'activadas' and r['activated'] and r['status'] == 'entregada' and r['stage'] != 'anulada')
                or (etapa == 'por_vencer' and r['axes']['validity'] == 'por_vencer')]
    if supplier:
        rows = [r for r in rows if supplier in (r.get('batch_supplier') or '').lower()]
    if kind:
        rows = [r for r in rows if r['kind'] == kind]
    if modality:
        rows = [r for r in rows if (r.get('duration') == 'perpetua') == (modality == 'perpetua')]
    return rows


def indicators(c, now):
    """Indicadores superiores calculados de la base: productos, disponibles, reservadas, vendidas, activadas, por vencer, vencidas y
    productos agotados o con stock bajo (agotado ≠ vencido)."""
    rows = enrich(c, licenses.units(c, now), now)
    products = [p for p in licenses.products(c, now) if p.get('managed')]
    free = lambda p: (p.get('stock') or {}).get('disponible', 0)
    out = {'productos': len(products),
           'disponibles': sum(1 for r in rows if r['stage'] == 'disponible'),
           'reservadas': sum(1 for r in rows if r['stage'] == 'reservada'),
           'vendidas': sum(1 for r in rows if r['stage'] in ('vendida', 'entregada', 'activada', 'renovada') or (r['stage'] == 'vencida' and r['status'] == 'entregada')),
           'activadas': sum(1 for r in rows if r['activated'] and r['status'] == 'entregada'),
           'por_vencer': sum(1 for r in rows if r['axes']['validity'] == 'por_vencer' and r['status'] == 'entregada'),
           'vencidas': sum(1 for r in rows if r['stage'] == 'vencida'),
           'agotados': sum(1 for p in products if p.get('available') and free(p) == 0),
           'stock_bajo': sum(1 for p in products if p.get('available') and 0 < free(p) <= LOW_STOCK),
           'low_stock': LOW_STOCK}
    # 1.5.293 · Encabezado del inventario: total, activas, próximas a vencer (margen configurable, 30 días por defecto) y renovaciones
    # pendientes (ciclos sin renovar ni rechazar del seguimiento comercial).
    out.update(total=sum(1 for r in rows if r['status'] != 'anulada'),
               activas=sum(1 for r in rows if r['status'] == 'entregada' and r['activated'] and not r.get('renewed_to') and r['axes']['validity'] in ('vigente', 'por_vencer', 'perpetua')),
               soon_days=licenses.display_settings(c)['soon_days'])
    try:
        out['renovaciones_pendientes'] = sum(1 for r in pipeline(c, now)['rows'] if r['cycle']['status'] not in ('completado', 'rechazado'))
    except Exception as error:
        print('indicadores renovaciones', type(error).__name__, flush=True)
        out['renovaciones_pendientes'] = None
    return out


# ---- Incidencias y reemplazos ----
def incidents(c, unit_id=None, status=None):
    if not _has(c, 'license_incidents'):
        return []
    sql, args = ("SELECT x.*,COALESCE(a.name,'') opened_name,COALESCE(b.name,'') resolved_name,u.code,COALESCE(r.code,'') replacement_code,i.name product,COALESCE(cl.name,'') client "
                 "FROM license_incidents x JOIN license_units u ON u.id=x.unit_id JOIN catalog_items i ON i.id=u.product_id LEFT JOIN clients cl ON cl.id=u.client_id "
                 "LEFT JOIN license_units r ON r.id=x.replacement_unit_id LEFT JOIN users a ON a.id=x.opened_by LEFT JOIN users b ON b.id=x.resolved_by WHERE 1=1", [])
    if unit_id is not None:
        sql += ' AND x.unit_id=?'
        args.append(unit_id)
    if status:
        sql += ' AND x.status=?'
        args.append(status)
    return [dict(r, kind_label=INCIDENT_KINDS[r['kind']]) for r in c.execute(sql + ' ORDER BY x.id DESC LIMIT 300', args)]


def _clean(data, key, low, high, label):
    value = re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()
    if not low <= len(value) <= high:
        raise LicenseError('Indica %s (%d a %d caracteres).' % (label, low, high), fields={key: 'Obligatorio.'})
    return value


def open_incident(c, unit_id, data, user, now):
    _ready(c, 'license_incidents')
    unit = licenses.unit_row(c, unit_id)
    if unit['status'] not in ('entregada', 'reservada'):
        raise LicenseError('Las incidencias se registran sobre licencias asignadas o entregadas.', 409)
    kind = str(data.get('kind', ''))
    if kind not in INCIDENT_KINDS:
        raise LicenseError('Elige el tipo de incidencia.', fields={'kind': 'Tipo no válido.'})
    detail = _clean(data, 'detail', 10, 1000, 'qué ocurrió')
    if c.execute("SELECT 1 FROM license_incidents WHERE unit_id=? AND status='abierta' AND kind=? AND detail=?", (unit_id, kind, detail)).fetchone():
        return {'ok': True, 'duplicate': True, 'incidents': incidents(c, unit_id)}
    iid = c.execute('INSERT INTO license_incidents(unit_id,kind,detail,opened_by,opened_at) VALUES (?,?,?,?,?)', (unit_id, kind, detail, user['id'], stamp(now))).lastrowid
    licenses.event(c, 'incidencia', now, 'Incidencia abierta (%s): %s' % (INCIDENT_KINDS[kind], detail[:300]), unit_id, unit['product_id'], order=unit['order_id'], client=unit['client_id'], user=user)
    return {'ok': True, 'id': iid, 'incidents': incidents(c, unit_id)}


def resolve_incident(c, unit_id, data, user, now):
    _ready(c, 'license_incidents')
    unit = licenses.unit_row(c, unit_id)
    raw = str(data.get('incident', '') or '')
    row = c.execute('SELECT * FROM license_incidents WHERE id=? AND unit_id=?', (int(raw), unit_id)).fetchone() if raw.isdigit() else None
    if not row:
        raise LicenseError('Incidencia no encontrada.', 404)
    if row['status'] == 'resuelta':
        return {'ok': True, 'duplicate': True, 'incidents': incidents(c, unit_id)}
    resolution = _clean(data, 'resolution', 10, 1000, 'cómo se resolvió')
    c.execute("UPDATE license_incidents SET status='resuelta',resolution=?,resolved_by=?,resolved_at=? WHERE id=? AND status='abierta'", (resolution, user['id'], stamp(now), row['id']))
    licenses.event(c, 'incidencia_resuelta', now, 'Incidencia resuelta (%s): %s' % (INCIDENT_KINDS[row['kind']], resolution[:300]), unit_id, unit['product_id'], order=unit['order_id'], client=unit['client_id'], user=user)
    return {'ok': True, 'incidents': incidents(c, unit_id)}


def replace_unit(c, unit_id, data, user, now):
    """Reemplazo de una licencia asignada o entregada por otra DISPONIBLE del mismo producto (clave inválida, error de activación…).
    Atómico: la nueva se toma solo si sigue disponible (dos personas no pueden usar la misma) y la anterior queda anulada, sin volver al
    inventario. La nueva hereda cliente, orden, venta y entrega; la incidencia queda resuelta con el enlace entre ambas."""
    _ready(c, 'license_incidents')
    old = licenses.unit_row(c, unit_id)
    if old['status'] not in ('entregada', 'reservada'):
        raise LicenseError('Solo se reemplaza una licencia asignada o entregada.', 409)
    if old['renewed_to']:
        raise LicenseError('Esta licencia ya fue renovada con otra clave: gestiona la vigente.', 409)
    reason = _clean(data, 'reason', 10, 500, 'el motivo del reemplazo')
    raw = str(data.get('incident', '') or '')
    incident = c.execute("SELECT * FROM license_incidents WHERE id=? AND unit_id=? AND status='abierta'", (int(raw), unit_id)).fetchone() if raw.isdigit() else None
    if raw and not incident:
        raise LicenseError('La incidencia indicada no está abierta en esta licencia.', 409)
    today = now.date().isoformat()
    for candidate in c.execute("SELECT id,code FROM license_units WHERE product_id=? AND status='disponible' AND id!=? AND (expires_at='' OR expires_at>=?) ORDER BY id LIMIT 5",
                               (old['product_id'], unit_id, today)).fetchall():
        taken = c.execute("UPDATE license_units SET status=?,quote_id=?,quote_item_id=?,order_id=?,client_id=?,delivery_id=?,sale_id=?,sale_item_id=?,reserved_at=?,delivered_at=?,"
                          "notes=?,updated_at=? WHERE id=? AND status='disponible'",
                          (old['status'], old['quote_id'], old['quote_item_id'], old['order_id'], old['client_id'], old['delivery_id'], old['sale_id'], old['sale_item_id'],
                           old['reserved_at'] or stamp(now), stamp(now) if old['status'] == 'entregada' else '', 'Reemplazo de ' + old['code'], stamp(now), candidate['id'])).rowcount
        if taken == 1:
            break
    else:
        raise LicenseError('No hay otra licencia disponible de este producto. Registra una nueva en el inventario y vuelve a intentarlo.', 409)
    if c.execute("UPDATE license_units SET status='anulada',updated_at=? WHERE id=? AND status=?", (stamp(now), unit_id, old['status'])).rowcount != 1:
        raise LicenseError('Otra persona cambió esta licencia mientras tanto. Vuelve a abrirla.', 409)
    text = 'Reemplazada por %s. Motivo: %s' % (candidate['code'], reason[:300])
    licenses.event(c, 'reemplazada', now, text, unit_id, old['product_id'], order=old['order_id'], client=old['client_id'], user=user)
    licenses.event(c, 'reemplazo', now, 'Reemplaza a %s para el mismo cliente. Motivo: %s' % (old['code'], reason[:300]), candidate['id'], old['product_id'], order=old['order_id'], client=old['client_id'], user=user)
    if incident:
        c.execute("UPDATE license_incidents SET status='resuelta',resolution=?,replacement_unit_id=?,resolved_by=?,resolved_at=? WHERE id=? AND status='abierta'",
                  (text, candidate['id'], user['id'], stamp(now), incident['id']))
    else:
        c.execute("INSERT INTO license_incidents(unit_id,kind,detail,status,resolution,replacement_unit_id,opened_by,opened_at,resolved_by,resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (unit_id, str(data.get('kind') or 'clave_invalida') if str(data.get('kind') or '') in INCIDENT_KINDS else 'clave_invalida', reason, 'resuelta', text, candidate['id'],
                   user['id'], stamp(now), user['id'], stamp(now)))
    return {'ok': True, 'new_unit_id': candidate['id'], 'new_code': candidate['code']}


# ---- Alertas para el Centro de Control ----
def center_alerts(c, now, R=None):
    """Pendientes operativos de licencias (además de los vencimientos): stock bajo o agotado, reservas detenidas, ventas pagadas sin
    entregar, entregadas sin activar e incidencias abiertas. Cada uno desaparece cuando su condición deja de existir."""
    today = now.date()
    out = []
    for p in licenses.products(c, now):
        if not p.get('managed') or not p.get('available'):
            continue
        free = (p.get('stock') or {}).get('disponible', 0)
        if free <= LOW_STOCK:
            out.append({'kind': 'stock', 'id': p['id'], 'title': ('Licencias agotadas · ' if free == 0 else 'Stock bajo de licencias · ') + p['name'][:60],
                        'detail': '%d disponible%s%s' % (free, '' if free == 1 else 's', ' · %d por cubrir' % p['pending'] if p.get('pending') else ''),
                        'priority': 'urgente' if free == 0 and p.get('pending') else 'importante' if free == 0 else 'normal', 'at': '', 'href': '#licenses?producto=%d' % p['id'],
                        'waiting': 'Registrar nuevas licencias en el inventario', 'resolves': 'Desaparece cuando hay más de %d licencias disponibles del producto (o se desactiva).' % LOW_STOCK,
                        'decision': free == 0 and bool(p.get('pending'))})
    for r in c.execute("SELECT u.id,u.code,u.reserved_at,i.name product,COALESCE(cl.name,'') client FROM license_units u JOIN catalog_items i ON i.id=u.product_id LEFT JOIN clients cl ON cl.id=u.client_id "
                       "LEFT JOIN license_sales s ON s.id=u.sale_id WHERE u.status='reservada' AND (u.sale_id IS NULL OR s.payment_status!='pagado') AND u.reserved_at!='' AND u.reserved_at<? ORDER BY u.reserved_at LIMIT 100",
                       (stamp(now - timedelta(days=3)),)):
        out.append({'kind': 'reserva', 'id': r['id'], 'title': 'Reserva de licencia pendiente · ' + r['code'], 'detail': r['product'][:60] + ' · reservada desde ' + r['reserved_at'][:10],
                    'client': r['client'], 'priority': 'importante', 'at': r['reserved_at'], 'href': '#licenses?unidad=%d' % r['id'], 'waiting': 'Confirmar la venta o liberar la reserva',
                    'resolves': 'Desaparece cuando la licencia se vende, se entrega o se libera.', 'decision': True})
    for r in c.execute("SELECT s.id,s.code,s.created_at,COALESCE(cl.name,'') client,(SELECT COUNT(*) FROM license_units u WHERE u.sale_id=s.id AND u.status='reservada') waiting "
                       "FROM license_sales s LEFT JOIN clients cl ON cl.id=s.client_id WHERE s.payment_status='pagado' AND s.delivery_status='pendiente' ORDER BY s.id LIMIT 100"):
        out.append({'kind': 'venta', 'id': r['id'], 'title': 'Licencias vendidas sin entregar · ' + r['code'], 'detail': '%d licencia%s pagada%s por entregar' % (r['waiting'], '' if r['waiting'] == 1 else 's', '' if r['waiting'] == 1 else 's'),
                    'client': r['client'], 'priority': 'urgente', 'at': r['created_at'], 'href': '#sales', 'waiting': 'Entregar la licencia al cliente por un canal autorizado',
                    'resolves': 'Desaparece cuando la venta queda entregada o se cancela.', 'decision': True})
    for r in c.execute("SELECT u.id,u.code,u.delivered_at,i.name product,COALESCE(cl.name,'') client FROM license_units u JOIN catalog_items i ON i.id=u.product_id LEFT JOIN clients cl ON cl.id=u.client_id "
                       "LEFT JOIN license_products p ON p.item_id=u.product_id WHERE u.status='entregada' AND u.activated=0 AND u.renewed_to IS NULL AND u.delivered_at!='' AND u.delivered_at<? "
                       "AND COALESCE(p.activation_method,'')!='archivo' ORDER BY u.delivered_at LIMIT 100", (stamp(now - timedelta(days=7)),)):
        out.append({'kind': 'activacion', 'id': r['id'], 'title': 'Activación sin confirmar · ' + r['code'], 'detail': r['product'][:60] + ' · entregada el ' + r['delivered_at'][:10],
                    'client': r['client'], 'priority': 'normal', 'at': r['delivered_at'], 'href': '#licenses?unidad=%d' % r['id'], 'waiting': 'Confirmar con el cliente si la activó',
                    'resolves': 'Desaparece al confirmar la activación (o al anular o reemplazar la licencia).', 'decision': False})
    for x in incidents(c, status='abierta'):
        out.append({'kind': 'incidencia', 'id': x['id'], 'unit_id': x['unit_id'], 'title': 'Incidencia de licencia · ' + x['code'], 'detail': x['kind_label'] + ' · ' + x['detail'][:80],
                    'client': x['client'], 'priority': 'urgente' if x['kind'] in ('activacion', 'clave_invalida') else 'importante', 'at': x['opened_at'], 'href': '#licenses?unidad=%d' % x['unit_id'],
                    'waiting': 'Resolver la incidencia o reemplazar la licencia', 'resolves': 'Desaparece cuando la incidencia se registra como resuelta (o la licencia se reemplaza).', 'decision': True})
    return out


# ---- Reportes empresariales (ventas, costos y márgenes, rotación) ----
REPORTS.update({'ventas': 'Ventas de licencias', 'margenes': 'Costos y márgenes', 'rotacion': 'Rotación de inventario'})
COST_REPORTS = ('margenes',)


def enterprise_report(c, now, kind, params, out):
    start, end = _range(now, params)
    hi = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    out.update({'from': start, 'to': end})
    if kind == 'ventas':
        rows = [dict(r) for r in c.execute("SELECT s.code,s.created_at,COALESCE(cl.name,'') client,s.payment_status,s.delivery_status,s.total_cents,"
                                           "(SELECT COALESCE(SUM(p.amount_cents),0) FROM license_sale_payments p WHERE p.sale_id=s.id AND p.status='confirmado') paid FROM license_sales s "
                                           "LEFT JOIN clients cl ON cl.id=s.client_id WHERE s.created_at>=? AND s.created_at<? ORDER BY s.id DESC", (start, hi))]
        group = lambda r: 'Anulada' if r['payment_status'] == 'cancelado' or r['delivery_status'] == 'cancelado' else 'Completada' if r['payment_status'] == 'pagado' and r['delivery_status'] == 'entregado' else 'En curso (reserva o pago pendiente)'
        out['columns'] = [('date', 'Fecha'), ('code', 'Venta'), ('client', 'Cliente'), ('group', 'Situación'), ('total', 'Total'), ('paid', 'Cobrado (confirmado)')]
        out['rows'] = [{'date': r['created_at'][:10], 'code': r['code'], 'client': r['client'] or '—', 'group': group(r), 'total': licenses.usd(r['total_cents']), 'paid': licenses.usd(r['paid'])} for r in rows]
        sums = {}
        for r in rows:
            g = group(r)
            sums[g] = sums.get(g, 0) + (r['paid'] if g != 'Anulada' else r['total_cents'])
        out['totals'] = {'Ventas completadas (cobrado)': licenses.usd(sums.get('Completada', 0)), 'En curso (cobrado hasta hoy)': licenses.usd(sums.get('En curso (reserva o pago pendiente)', 0)),
                         'Anuladas (no se cuentan como ingreso)': licenses.usd(sums.get('Anulada', 0))}
        return out
    if kind == 'margenes':
        # Solo ventas completadas: precio cobrado de cada partida frente al costo real de las licencias entregadas (costo del lote o del producto).
        rows = [dict(r) for r in c.execute("SELECT it.product_name product,SUM(it.quantity) qty,SUM(it.unit_price_cents*it.quantity-it.discount_cents) revenue,"
                                           "(SELECT COALESCE(SUM(COALESCE(b.unit_cost_cents,lp.purchase_cents,0)),0) FROM license_units u LEFT JOIN license_batches b ON b.id=u.batch_id "
                                           " LEFT JOIN license_products lp ON lp.item_id=u.product_id JOIN license_sale_items it2 ON it2.id=u.sale_item_id JOIN license_sales s2 ON s2.id=it2.sale_id "
                                           " WHERE u.status='entregada' AND it2.product_id=it.product_id AND s2.payment_status='pagado' AND s2.delivery_status='entregado' AND s2.created_at>=? AND s2.created_at<?) cost "
                                           "FROM license_sale_items it JOIN license_sales s ON s.id=it.sale_id WHERE s.payment_status='pagado' AND s.delivery_status='entregado' AND s.created_at>=? AND s.created_at<? "
                                           "GROUP BY it.product_id,it.product_name ORDER BY revenue DESC", (start, hi, start, hi))]
        out['columns'] = [('product', 'Producto'), ('qty', 'Unidades'), ('revenue', 'Vendido'), ('cost', 'Costo'), ('margin', 'Margen'), ('margin_pct', 'Margen %')]
        out['rows'] = [{'product': r['product'], 'qty': r['qty'], 'revenue': licenses.usd(r['revenue']), 'cost': licenses.usd(r['cost']), 'margin': licenses.usd(r['revenue'] - r['cost']),
                        'margin_pct': ('%.1f %%' % ((r['revenue'] - r['cost']) * 100 / r['revenue'])) if r['revenue'] else '—'} for r in rows]
        rev, cost = sum(r['revenue'] for r in rows), sum(r['cost'] for r in rows)
        out['totals'] = {'Vendido (ventas completadas)': licenses.usd(rev), 'Costo': licenses.usd(cost), 'Margen': licenses.usd(rev - cost)}
        return out
    # Rotación: por producto, disponibles hoy, vendidas o entregadas en el período y días promedio en inventario hasta la venta.
    rows = []
    for p in licenses.products(c, now):
        if not p.get('managed'):
            continue
        sold = c.execute("SELECT COUNT(*),AVG(julianday(substr(COALESCE(NULLIF(u.delivered_at,''),u.reserved_at),1,10))-julianday(substr(u.created_at,1,10))) FROM license_units u "
                         "WHERE u.product_id=? AND u.status IN ('entregada','reservada') AND substr(COALESCE(NULLIF(u.delivered_at,''),u.reserved_at),1,10)>=? AND substr(COALESCE(NULLIF(u.delivered_at,''),u.reserved_at),1,10)<=?",
                         (p['id'], start, end)).fetchone()
        free = (p.get('stock') or {}).get('disponible', 0)
        rows.append({'product': p['name'], 'free': free, 'sold': sold[0], 'days': '%.0f' % sold[1] if sold[1] is not None else '—',
                     'cover': ('%.1f' % (free / sold[0])) if sold[0] else '—', 'state': 'Agotado' if free == 0 else 'Stock bajo' if free <= LOW_STOCK else 'Disponible'})
    rows.sort(key=lambda r: -r['sold'])
    out['columns'] = [('product', 'Producto'), ('free', 'Disponibles'), ('sold', 'Vendidas en el período'), ('days', 'Días promedio en inventario'), ('cover', 'Cobertura (stock / ventas)'), ('state', 'Stock')]
    out['rows'] = rows
    out['totals'] = {'Productos': len(rows), 'Vendidas en el período': sum(r['sold'] for r in rows)}
    return out
