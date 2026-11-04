"""Seguimiento de pedidos de repuestos de cada orden, al estilo de una empresa de mensajería.

- Ocho etapas en orden fijo. Se avanza de una en una; retroceder o saltar es una corrección de administración con motivo. Ninguna etapa se
  completa sola por el paso del tiempo.
- La situación (en espera, retraso, incidencia de transporte, cancelación) es aparte de la etapa: un retraso no borra lo ya completado.
  Cancelado es definitivo. Un pedido vencido (fecha estimada pasada sin recibir) solo se advierte internamente.
- Cada alta, cambio de etapa, de situación o de datos queda en order_part_events (no se modifica ni se borra), con fecha, hora y responsable.
- El cliente ve, en el enlace público, solo: nombre y marca del repuesto, etapa, fechas (solicitud, estimada si se registró, recepción),
  última actualización y los mensajes que el taller marcó como públicos. Nunca costos, proveedor, pedido, guía, enlaces ni notas internas.
- Cambiar de etapa no crea compras, facturas, cobros ni movimientos de inventario: la recepción en inventario se hace con sus procedimientos.
  Una línea de compra ya registrada se asocia a un solo pedido (índice único): no se duplica el pedido."""
import json
import re
from datetime import date

STAGES = (('solicitado', 'Repuesto solicitado', 'Solicitado'), ('confirmado', 'Pedido confirmado', 'Confirmado'),
          ('preparacion', 'En preparación por el proveedor', 'Preparación'), ('transito', 'En camino / en tránsito', 'En tránsito'),
          ('recibido', 'Repuesto recibido en el taller', 'Recibido'), ('instalacion', 'En proceso de instalación', 'Instalación'),
          ('instalado', 'Instalación finalizada', 'Finalizado'), ('listo', 'Equipo listo para entrega', 'Listo para entrega'))
CODES = [s[0] for s in STAGES]
# Situación: etiqueta y tono (gris pendiente, azul en proceso, amarillo en espera, naranja retraso, verde completado, rojo incidencia).
SITUATIONS = {'normal': ('Sin novedad', 'azul'), 'espera_confirmacion': ('En espera de confirmación', 'amarillo'), 'espera_proveedor': ('En espera del proveedor', 'naranja'),
              'retrasado': ('Retrasado', 'naranja'), 'incidencia_transporte': ('Incidencia de transporte', 'rojo'), 'cancelado': ('Pedido cancelado', 'rojo')}
MESSAGES = {
    'solicitado': 'Estimado cliente: le informamos que hemos iniciado la gestión de adquisición del repuesto necesario para su equipo. Podrá consultar las actualizaciones desde el enlace de seguimiento de su orden.',
    'confirmado': 'Le comunicamos que el proveedor ha confirmado el pedido del repuesto solicitado. Continuaremos informándole sobre su proceso de entrega.',
    'preparacion': 'El proveedor está preparando el repuesto solicitado para su envío. Le informaremos cuando se encuentre en camino.',
    'transito': 'Su repuesto se encuentra en proceso de transporte hacia nuestras instalaciones. Actualizaremos el seguimiento cuando recibamos nueva información.',
    'recibido': 'Nos complace informarle que el repuesto solicitado ha llegado a nuestro taller. Procederemos con la revisión e instalación correspondiente.',
    'instalacion': 'Nuestro equipo técnico está realizando la instalación del repuesto y las verificaciones necesarias para comprobar su correcto funcionamiento.',
    'instalado': 'La instalación del repuesto ha finalizado. Estamos realizando las pruebas finales de funcionamiento de su equipo.',
    'listo': 'Le informamos que los trabajos correspondientes han finalizado y su equipo se encuentra listo para entrega, sujeto a las condiciones de retiro de su orden.',
    'espera_confirmacion': 'Estamos a la espera de la confirmación del proveedor sobre el repuesto solicitado. Le informaremos en cuanto la recibamos.',
    'espera_proveedor': 'El repuesto solicitado se encuentra en espera de disponibilidad por parte del proveedor. Le informaremos en cuanto tengamos novedades.',
    'retrasado': 'Le informamos que la llegada del repuesto solicitado presenta un retraso por parte del proveedor. Le mantendremos informado sobre la nueva fecha estimada.',
    'incidencia_transporte': 'Se presentó una novedad en el transporte del repuesto. Estamos gestionándola con el proveedor y le informaremos en cuanto tengamos novedades.',
    'cancelado': 'Le informamos que el pedido del repuesto fue cancelado. Nos comunicaremos con usted para indicarle las alternativas disponibles.',
}
FIELDS = {'name': ('Nombre del repuesto', 160), 'brand': ('Marca', 80), 'compatible_model': ('Modelo compatible', 120), 'reference': ('Código o referencia', 80),
          'supplier_order': ('Número de pedido', 60), 'carrier': ('Empresa transportista', 80), 'tracking_number': ('Número de guía', 80),
          'tracking_url': ('Enlace de rastreo', 300), 'internal_note': ('Observaciones internas', 1500)}
DATES = {'purchase_date': 'Fecha de compra', 'eta': 'Fecha estimada de llegada', 'received_at': 'Fecha de recepción'}
LINKS = {'supplier_id': 'Proveedor', 'purchase_item_id': 'Línea de compra', 'inventory_item_id': 'Producto del inventario', 'technician_id': 'Técnico responsable'}


class PartError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def _staff(user):
    if user['role'] not in ('administrador', 'tecnico'):
        raise PartError('Acceso no permitido.', 403)


def _text(data, key, limit):
    return re.sub(r'[ \t]+', ' ', str(data.get(key, '') or '')).strip()[:limit]


def _date(data, key):
    value = str(data.get(key, '') or '').strip()
    if not value:
        return ''
    try:
        return date.fromisoformat(value).isoformat() if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else _bad(key)
    except ValueError:
        return _bad(key)


def _bad(key):
    raise PartError('%s no válida.' % DATES.get(key, 'Fecha'), 400, {key: 'Usa una fecha real (AAAA-MM-DD).'})


def _values(c, oid, data, current=None):
    """Datos administrativos validados. Ningún campo es obligatorio salvo el nombre: cada pedido tiene lo suyo."""
    out = {k: _text(data, k, limit) for k, (_, limit) in FIELDS.items()}
    out.update({k: _date(data, k) for k in DATES})
    if len(out['name']) < 2:
        raise PartError('Indica el nombre del repuesto.', 400, {'name': 'Obligatorio.'})
    if out['tracking_url'] and not re.fullmatch(r'https://[^\s<>"\']{4,295}', out['tracking_url']):
        raise PartError('El enlace de rastreo debe empezar por https://', 400, {'tracking_url': 'Enlace no válido.'})
    try:
        out['quantity'] = int(str(data.get('quantity', '1') or '1'))
    except ValueError:
        out['quantity'] = 0
    if not 1 <= out['quantity'] <= 999:
        raise PartError('Cantidad no válida.', 400, {'quantity': 'Entre 1 y 999.'})
    if out['purchase_date'] and out['eta'] and out['eta'] < out['purchase_date']:
        raise PartError('La fecha estimada no puede ser anterior a la compra.', 400, {'eta': 'Anterior a la compra.'})
    for key in LINKS:
        raw = str(data.get(key, '') or '').strip()
        out[key] = int(raw) if raw.isdigit() else None
    checks = {'supplier_id': 'SELECT 1 FROM suppliers WHERE id=? AND active=1', 'inventory_item_id': 'SELECT 1 FROM inventory_items WHERE id=? AND active=1',
              'technician_id': "SELECT 1 FROM users WHERE id=? AND active=1 AND role IN ('administrador','tecnico')", 'purchase_item_id': "SELECT 1 FROM purchase_items x JOIN purchases p ON p.id=x.purchase_id WHERE x.id=? AND p.status!='anulada'"}
    for key, sql in checks.items():
        if out[key] and (not current or current[key] != out[key]) and not c.execute(sql, (out[key],)).fetchone():
            raise PartError('%s no válido.' % LINKS[key], 400, {key: 'No válido.'})
    if out['purchase_item_id']:
        other = c.execute('SELECT r.id,o.code FROM order_part_requests r JOIN orders o ON o.id=r.order_id WHERE r.purchase_item_id=? AND r.id!=?',
                          (out['purchase_item_id'], current['id'] if current else 0)).fetchone()
        if other:
            raise PartError('Esa línea de compra ya está asociada al pedido de repuesto de la orden %s: no se crea otro pedido.' % other['code'], 409, {'purchase_item_id': 'Ya asociada.'})
    return out


def _request(c, oid, rid):
    row = c.execute('SELECT * FROM order_part_requests WHERE id=? AND order_id=?', (rid, oid)).fetchone() if str(rid).isdigit() else None
    if not row:
        raise PartError('Pedido de repuesto no encontrado.', 404)
    return row


def _event(c, row, kind, user, now, note='', public_note='', public=False, changes=None, stage=None, situation=None):
    c.execute('INSERT INTO order_part_events(request_id,kind,stage,situation,note,public_note,public,changes,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
              (row['id'], kind, stage or row['stage'], situation or row['situation'], note[:1500], public_note[:1500] if public else '', 1 if public and public_note else 0,
               json.dumps(changes, ensure_ascii=False) if changes else '', user['id'], stamp(now)))


def _message(data):
    text = str(data.get('public_note', '') or '').strip()[:1500]
    return text, bool(text) and str(data.get('publish', '')) in ('1', 'true')


def create(c, oid, data, user, now):
    """Alta de un repuesto en la orden (idempotente con request_key). Empieza en «Repuesto solicitado»."""
    _staff(user)
    if not c.execute('SELECT 1 FROM orders WHERE id=?', (oid,)).fetchone():
        raise PartError('Orden no disponible.', 404)
    key = _text(data, 'request_key', 64)
    if key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise PartError('Solicitud no válida. Recarga la página.')
        same = c.execute('SELECT id FROM order_part_requests WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id']
    v = _values(c, oid, data)
    v['technician_id'] = v['technician_id'] or user['id']
    cols = ['order_id', 'request_key', 'created_by', 'created_at', 'updated_at', *v.keys(), 'public_visible']
    vals = [oid, key or None, user['id'], stamp(now), stamp(now), *v.values(), 0 if str(data.get('public_visible', '1')) in ('0', '') else 1]
    rid = c.execute('INSERT INTO order_part_requests(' + ','.join(cols) + ') VALUES (' + ','.join('?' * len(cols)) + ')', vals).lastrowid
    row = _request(c, oid, rid)
    text, public = _message(data)
    _event(c, row, 'alta', user, now, note=_text(data, 'note', 1500) or 'Repuesto registrado.', public_note=text, public=public)
    return rid


def update(c, oid, rid, data, user, now):
    """Corrige o completa los datos administrativos; cada cambio queda en el historial con el valor anterior."""
    _staff(user)
    row = _request(c, oid, rid)
    if row['situation'] == 'cancelado':
        raise PartError('El pedido está cancelado: sus datos ya no se cambian.', 409)
    v = _values(c, oid, {**{k: row[k] for k in (*FIELDS, *DATES, *LINKS, 'quantity')}, **data}, row)
    v['technician_id'] = v['technician_id'] or row['technician_id']
    visible = row['public_visible'] if 'public_visible' not in data else (0 if str(data.get('public_visible')) in ('0', '') else 1)
    changes = {k: [row[k], v[k]] for k in v if row[k] != v[k] and not (row[k] in (None, '') and v[k] in (None, ''))}
    if visible != row['public_visible']:
        changes['public_visible'] = [row['public_visible'], visible]
    if not changes:
        return {'changed': 0}
    sets = ','.join(k + '=?' for k in v)
    c.execute('UPDATE order_part_requests SET ' + sets + ',public_visible=?,updated_at=? WHERE id=?', (*v.values(), visible, stamp(now), row['id']))
    _event(c, row, 'datos', user, now, note=_text(data, 'note', 1500) or 'Datos del repuesto actualizados.', changes=changes)
    return {'changed': len(changes)}


def advance(c, oid, rid, data, user, now):
    """Cambia la etapa. Normal: solo a la siguiente. Retroceder o saltar: corrección de administración con motivo."""
    _staff(user)
    row = _request(c, oid, rid)
    if row['situation'] == 'cancelado':
        raise PartError('El pedido está cancelado: ya no cambia de etapa.', 409)
    target = str(data.get('stage', ''))
    if target not in CODES:
        raise PartError('Etapa no válida.', 400, {'stage': 'No válida.'})
    have, want = CODES.index(row['stage']), CODES.index(target)
    note = _text(data, 'note', 1500)
    if want == have:
        raise PartError('El repuesto ya está en esa etapa.', 409)
    if want != have + 1:
        if user['role'] != 'administrador':
            raise PartError('Solo se avanza a la etapa siguiente. Saltar o retroceder es una corrección de administración.', 403)
        if len(note) < 10:
            raise PartError('Indica el motivo de la corrección de etapa (al menos 10 caracteres).', 400, {'note': 'Motivo obligatorio.'})
    received = row['received_at']
    if target == 'recibido' and want > have:
        received = _date(data, 'received_at') or now.date().isoformat()
        if received > now.date().isoformat():
            raise PartError('La fecha de recepción no puede ser futura.', 400, {'received_at': 'Fecha futura.'})
    situation = 'normal' if want > have else row['situation']  # al avanzar, un retraso o una espera anterior quedan resueltos
    c.execute('UPDATE order_part_requests SET stage=?,situation=?,received_at=?,updated_at=? WHERE id=?', (target, situation, received, stamp(now), row['id']))
    text, public = _message(data)
    _event(c, row, 'etapa', user, now, note=note or ('Corrección de etapa' if want < have else 'Avanza a: ' + dict((s[0], s[1]) for s in STAGES)[target]),
           public_note=text, public=public, stage=target, situation=situation, changes={'stage': [row['stage'], target]})
    return {'stage': target, 'situation': situation}


def set_situation(c, oid, rid, data, user, now):
    """Registra una espera, un retraso, una incidencia o la cancelación (con motivo) y, si se confirmó, la nueva fecha estimada."""
    _staff(user)
    row = _request(c, oid, rid)
    if row['situation'] == 'cancelado':
        raise PartError('El pedido ya está cancelado.', 409)
    situation = str(data.get('situation', ''))
    if situation not in SITUATIONS:
        raise PartError('Situación no válida.', 400, {'situation': 'No válida.'})
    note = _text(data, 'note', 1500)
    if situation != 'normal' and len(note) < 5:
        raise PartError('Indica el motivo (al menos 5 caracteres).', 400, {'note': 'Motivo obligatorio.'})
    if situation in ('retrasado', 'espera_proveedor', 'incidencia_transporte') and CODES.index(row['stage']) >= CODES.index('recibido'):
        raise PartError('El repuesto ya se recibió: esa situación no corresponde.', 409)
    eta = _date(data, 'eta') or row['eta']
    changes = {'situation': [row['situation'], situation]}
    if eta != row['eta']:
        changes['eta'] = [row['eta'], eta]
    c.execute('UPDATE order_part_requests SET situation=?,eta=?,updated_at=? WHERE id=?', (situation, eta, stamp(now), row['id']))
    text, public = _message(data)
    _event(c, row, 'situacion', user, now, note=note or 'Sin novedad.', public_note=text, public=public, situation=situation, changes=changes)
    return {'situation': situation, 'eta': eta}


def _overdue(r, today):
    return bool(r['eta']) and r['eta'] < today and CODES.index(r['stage']) < CODES.index('recibido') and r['situation'] != 'cancelado'


def listing(c, oid, today):
    """Repuestos de la orden con su línea de etapas, su historial y lo asociado (compra e inventario), para el panel del taller."""
    names = {r[0]: r[1] for r in c.execute('SELECT id,name FROM users')}
    out = []
    for r in c.execute("SELECT r.*,COALESCE(s.name,'') supplier,COALESCE(g.name,'') inventory_name,p.document_number purchase_document,p.status purchase_status,p.id purchase_id "
                       'FROM order_part_requests r LEFT JOIN suppliers s ON s.id=r.supplier_id LEFT JOIN inventory_items i ON i.id=r.inventory_item_id '
                       'LEFT JOIN catalog_items g ON g.id=i.catalog_id LEFT JOIN purchase_items x ON x.id=r.purchase_item_id LEFT JOIN purchases p ON p.id=x.purchase_id '
                       'WHERE r.order_id=? ORDER BY r.id', (oid,)).fetchall():
        events = [dict(e, actor=names.get(e['created_by'], 'Sistema'), changes=json.loads(e['changes']) if e['changes'] else {})
                  for e in c.execute('SELECT * FROM order_part_events WHERE request_id=? ORDER BY id DESC', (r['id'],))]
        done = {e['stage']: e['created_at'] for e in reversed(events) if e['kind'] in ('alta', 'etapa')}
        item = dict(r)
        item.update(stage_label=dict((s[0], s[1]) for s in STAGES)[r['stage']], stage_index=CODES.index(r['stage']), situation_label=SITUATIONS[r['situation']][0],
                    tone=SITUATIONS[r['situation']][1], overdue=_overdue(r, today), technician=names.get(r['technician_id'], ''), events=events,
                    steps=[{'code': code, 'label': label, 'short': short, 'at': done.get(code, '') if CODES.index(code) <= CODES.index(r['stage']) else ''} for code, label, short in STAGES],
                    evidence=c.execute('SELECT COUNT(*) FROM order_followup_files f JOIN order_followups u ON u.id=f.followup_id WHERE u.part_request_id=?', (r['id'],)).fetchone()[0])
        out.append(item)
    return out


def options(c):
    """Datos para asociar sin duplicar: proveedores, líneas de compra recientes (con el pedido al que ya pertenecen) y productos del inventario."""
    linked = {r[0]: r[1] for r in c.execute('SELECT r.purchase_item_id,o.code FROM order_part_requests r JOIN orders o ON o.id=r.order_id WHERE r.purchase_item_id IS NOT NULL')}
    lines = [dict(r, linked_to=linked.get(r['id'], '')) for r in c.execute(
        "SELECT x.id,x.quantity,p.document_number,p.issue_date,p.status,s.name supplier,g.name product FROM purchase_items x JOIN purchases p ON p.id=x.purchase_id "
        "JOIN suppliers s ON s.id=p.supplier_id JOIN inventory_items i ON i.id=x.item_id JOIN catalog_items g ON g.id=i.catalog_id WHERE p.status!='anulada' ORDER BY x.id DESC LIMIT 200")]
    return {'stages': [{'code': a, 'label': b, 'short': s} for a, b, s in STAGES], 'situations': {k: {'label': v[0], 'tone': v[1]} for k, v in SITUATIONS.items()}, 'messages': MESSAGES,
            'suppliers': [dict(r) for r in c.execute('SELECT id,name FROM suppliers WHERE active=1 ORDER BY name')], 'purchase_lines': lines,
            'inventory': [dict(r) for r in c.execute('SELECT i.id,g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.active=1 ORDER BY g.name LIMIT 500')],
            'staff': [dict(r) for r in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN ('administrador','tecnico') ORDER BY name")]}


def public(c, oid):
    """Lo único que ve el cliente de cada repuesto visible: sin costos, proveedor, pedido, guía, enlaces ni notas internas."""
    out = []
    for r in c.execute('SELECT * FROM order_part_requests WHERE order_id=? AND public_visible=1 ORDER BY id', (oid,)).fetchall():
        events = c.execute('SELECT kind,stage,public_note,public,created_at FROM order_part_events WHERE request_id=? ORDER BY id', (r['id'],)).fetchall()
        done = {e['stage']: e['created_at'] for e in events if e['kind'] in ('alta', 'etapa')}
        out.append({'name': ' · '.join(x for x in (r['name'], r['brand']) if x), 'stage': r['stage'], 'stage_index': CODES.index(r['stage']),
                    'stage_label': dict((s[0], s[1]) for s in STAGES)[r['stage']], 'situation': r['situation'],
                    'situation_label': SITUATIONS[r['situation']][0] if r['situation'] != 'normal' else '', 'tone': SITUATIONS[r['situation']][1],
                    'requested': r['created_at'], 'eta': r['eta'] if CODES.index(r['stage']) < CODES.index('recibido') else '', 'received': r['received_at'],
                    'updated': events[-1]['created_at'] if events else r['updated_at'],
                    'steps': [{'short': short, 'at': done.get(code, '') if CODES.index(code) <= CODES.index(r['stage']) else ''} for code, _, short in STAGES],
                    'messages': [{'at': e['created_at'], 'text': e['public_note']} for e in reversed(events) if e['public'] and e['public_note']][:6]})
    return out
