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
# ---- Logistics Pro (05/11/2026): pasos detallados del traslado según el tipo de envío. La etapa general (stage) sigue con sus 8 valores:
# cada paso del traslado cuenta como «transito» para el seguimiento público (6 etapas) y para los pedidos anteriores (sin tipo de envío).
FLOWS = {'internacional': ('solicitado', 'confirmado', 'preparacion', 'despachado', 'transito_internacional', 'llegada_pais', 'aduana_revision', 'aduana_liberado',
                           'distribucion_nacional', 'ruta_otavalo', 'recibido', 'instalacion', 'instalado', 'listo'),
         'nacional': ('solicitado', 'confirmado', 'preparacion', 'despachado', 'transito_nacional', 'ruta_otavalo', 'recibido', 'instalacion', 'instalado', 'listo')}
TRANSIT = ('despachado', 'transito_internacional', 'llegada_pais', 'aduana_revision', 'aduana_liberado', 'distribucion_nacional', 'ruta_otavalo', 'transito_nacional')
STEP_LABELS = {'solicitado': 'Pedido solicitado', 'confirmado': 'Pedido confirmado', 'preparacion': 'Preparación del repuesto', 'despachado': 'Despachado en el país de origen',
               'transito_internacional': 'En tránsito internacional', 'llegada_pais': 'Llegada al país de destino', 'aduana_revision': 'En revisión aduanera',
               'aduana_liberado': 'Liberado por aduana', 'distribucion_nacional': 'En distribución nacional', 'ruta_otavalo': 'En ruta hacia Otavalo',
               'transito_nacional': 'En tránsito nacional', 'recibido': 'Recibido en PC-DOCTOR', 'instalacion': 'Instalación y pruebas', 'instalado': 'Proceso finalizado',
               'listo': 'Listo para entrega'}
NATIONAL_LABELS = {'despachado': 'Despachado'}
PHASES = {'internacional': (('pedido', 'Pedido', 'box', ('solicitado', 'confirmado', 'preparacion')), ('aereo', 'Transporte aéreo', 'plane', ('despachado', 'transito_internacional')),
                            ('aduana', 'Aduana', 'customs', ('llegada_pais', 'aduana_revision', 'aduana_liberado')), ('terrestre', 'Distribución nacional', 'truck', ('distribucion_nacional', 'ruta_otavalo')),
                            ('recepcion', 'Recepción', 'check', ('recibido',)), ('servicio', 'Instalación y entrega', 'wrench', ('instalacion', 'instalado', 'listo'))),
          'nacional': (('pedido', 'Pedido', 'box', ('solicitado', 'confirmado', 'preparacion')), ('terrestre', 'Transporte terrestre', 'truck', ('despachado', 'transito_nacional', 'ruta_otavalo')),
                       ('recepcion', 'Recepción', 'check', ('recibido',)), ('servicio', 'Instalación y entrega', 'wrench', ('instalacion', 'instalado', 'listo')))}
# Incidencias logísticas: etiqueta y situación general equivalente (la que ve el cliente, siempre genérica). Ninguna avanza el seguimiento.
INCIDENTS = {'retraso_transporte': ('Retraso de transporte', 'retrasado'), 'vuelo_reprogramado': ('Vuelo retrasado o reprogramado', 'retrasado'),
             'retencion_aduanera': ('Retención aduanera', 'incidencia_transporte'), 'documentacion_pendiente': ('Documentación pendiente', 'espera_confirmacion'),
             'cambio_transportista': ('Cambio de transportista', 'espera_proveedor'), 'problema_entrega': ('Problema de entrega', 'incidencia_transporte'),
             'extraviado': ('Pedido extraviado', 'incidencia_transporte'), 'devuelto': ('Pedido devuelto al remitente', 'incidencia_transporte')}


def step_label(code, shipping=''):
    if not shipping:  # pedidos anteriores: sus etiquetas de siempre
        return dict((s[0], s[1]) for s in STAGES).get(code, code)
    return (NATIONAL_LABELS.get(code) if shipping == 'nacional' else None) or STEP_LABELS.get(code) or dict((s[0], s[1]) for s in STAGES).get(code, code)


def flow(r):
    return FLOWS.get(r['shipping'] or '', CODES)


def fine(r):
    """Paso actual detallado: el logístico si está en traslado con tipo de envío; si no, la etapa general."""
    if r['shipping'] and r['stage'] == 'transito':
        return r['logistics'] if r['logistics'] in FLOWS[r['shipping']] else 'despachado'
    return r['stage']


FIELDS = {'name': ('Nombre del repuesto', 160), 'brand': ('Marca', 80), 'compatible_model': ('Modelo compatible', 120), 'reference': ('Código o referencia', 80),
          'supplier_order': ('Número de pedido', 60), 'carrier': ('Empresa transportista', 80), 'tracking_number': ('Número de guía', 80),
          'tracking_url': ('Enlace de rastreo', 300), 'internal_note': ('Observaciones internas', 1500), 'origin_country': ('País de origen', 60)}
DATES = {'purchase_date': 'Fecha de compra', 'eta': 'Fecha estimada de llegada', 'received_at': 'Fecha de recepción', 'dispatch_date': 'Fecha de despacho'}
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
    out['shipping'] = str(data.get('shipping', '') or '')
    if out['shipping'] not in ('', 'nacional', 'internacional'):
        raise PartError('Tipo de envío no válido.', 400, {'shipping': 'Nacional o internacional.'})
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


def _event(c, row, kind, user, now, note='', public_note='', public=False, changes=None, stage=None, situation=None, logistics=None, incident=None):
    c.execute('INSERT INTO order_part_events(request_id,kind,stage,situation,note,public_note,public,changes,created_by,created_at,logistics,incident) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
              (row['id'], kind, stage or row['stage'], situation or row['situation'], note[:1500], public_note[:1500] if public else '', 1 if public and public_note else 0,
               json.dumps(changes, ensure_ascii=False) if changes else '', user['id'], stamp(now), row['logistics'] if logistics is None else logistics,
               row['incident'] if incident is None else incident))


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
    if public:
        _check_public(c, row, text)
    _event(c, row, 'alta', user, now, note=_text(data, 'note', 1500) or 'Repuesto registrado.', public_note=text, public=public)
    return rid


def update(c, oid, rid, data, user, now):
    """Corrige o completa los datos administrativos; cada cambio queda en el historial con el valor anterior."""
    _staff(user)
    row = _request(c, oid, rid)
    if row['situation'] == 'cancelado':
        raise PartError('El pedido está cancelado: sus datos ya no se cambian.', 409)
    v = _values(c, oid, {**{k: row[k] for k in (*FIELDS, *DATES, *LINKS, 'quantity', 'shipping')}, **data}, row)
    v['technician_id'] = v['technician_id'] or row['technician_id']
    if v['shipping'] != row['shipping'] and row['stage'] == 'transito':
        if row['shipping'] and user['role'] != 'administrador':
            raise PartError('El pedido ya está en traslado: cambiar el tipo de envío es una corrección de administración.', 403)
        v['logistics'] = 'despachado' if v['shipping'] else ''  # el traslado sigue en su primer paso del nuevo flujo
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
    steps = flow(row)
    if target not in steps:
        raise PartError('Etapa no válida.', 400, {'stage': 'No válida.'})
    have, want = steps.index(fine(row)), steps.index(target)
    note = _text(data, 'note', 1500)
    if want == have:
        raise PartError('El repuesto ya está en esa etapa.', 409)
    if want != have + 1:
        if user['role'] != 'administrador':
            raise PartError('Solo se avanza a la etapa siguiente. Saltar o retroceder es una corrección de administración.', 403)
        if len(note) < 10:
            raise PartError('Indica el motivo de la corrección de etapa (al menos 10 caracteres).', 400, {'note': 'Motivo obligatorio.'})
    coarse = 'transito' if target in TRANSIT else target
    logistics = target if coarse == 'transito' and row['shipping'] else ''
    received = row['received_at']
    if target == 'recibido' and want > have:
        received = _date(data, 'received_at') or now.date().isoformat()
        if received > now.date().isoformat():
            raise PartError('La fecha de recepción no puede ser futura.', 400, {'received_at': 'Fecha futura.'})
    situation = 'normal' if want > have else row['situation']  # al avanzar, un retraso o una espera anterior quedan resueltos
    text, public = _message(data)
    if public:
        _check_public(c, row, text)
    dispatch = row['dispatch_date'] or (now.date().isoformat() if target == 'despachado' else '')
    c.execute("UPDATE order_part_requests SET stage=?,logistics=?,situation=?,incident=CASE WHEN ? THEN '' ELSE incident END,received_at=?,dispatch_date=?,updated_at=? WHERE id=?",
              (coarse, logistics, situation, 1 if want > have else 0, received, dispatch, stamp(now), row['id']))
    _event(c, row, 'etapa', user, now, note=note or ('Corrección de etapa' if want < have else 'Avanza a: ' + step_label(target, row['shipping'])),
           public_note=text, public=public, stage=coarse, situation=situation, changes={'stage': [fine(row), target]}, logistics=logistics)
    return {'stage': coarse, 'logistics': logistics, 'situation': situation}


def set_situation(c, oid, rid, data, user, now):
    """Registra una espera, un retraso, una incidencia o la cancelación (con motivo) y, si se confirmó, la nueva fecha estimada."""
    _staff(user)
    row = _request(c, oid, rid)
    if row['situation'] == 'cancelado':
        raise PartError('El pedido ya está cancelado.', 409)
    situation = str(data.get('situation', ''))
    incident = ''
    if situation in INCIDENTS:
        incident, situation = situation, INCIDENTS[situation][1]
    if situation not in SITUATIONS:
        raise PartError('Situación no válida.', 400, {'situation': 'No válida.'})
    note = _text(data, 'note', 1500)
    if situation != 'normal' and len(note) < 5:
        raise PartError('Indica el motivo (al menos 5 caracteres).', 400, {'note': 'Motivo obligatorio.'})
    if situation in ('retrasado', 'espera_proveedor', 'incidencia_transporte') and CODES.index(row['stage']) >= CODES.index('recibido'):
        raise PartError('El repuesto ya se recibió: esa situación no corresponde.', 409)
    eta = _date(data, 'eta') or row['eta']
    changes = {'situation': [row['incident'] or row['situation'], incident or situation]}
    if eta != row['eta']:
        changes['eta'] = [row['eta'], eta]
    text, public = _message(data)
    if public:
        _check_public(c, row, text)
    c.execute('UPDATE order_part_requests SET situation=?,incident=?,eta=?,updated_at=? WHERE id=?', (situation, incident, eta, stamp(now), row['id']))
    _event(c, row, 'situacion', user, now, note=note or 'Sin novedad.', public_note=text, public=public, situation=situation, changes=changes, incident=incident)
    return {'situation': situation, 'incident': incident, 'eta': eta}


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
        steps_of = flow(r)
        current = fine(r)
        idx = steps_of.index(current) if current in steps_of else 0
        finished = r['stage'] == 'listo' and r['situation'] != 'cancelado'
        reached = {e['logistics'] or e['stage'] for e in events if e['kind'] in ('alta', 'etapa')}
        at = {}
        for e in reversed(events):
            if e['kind'] in ('alta', 'etapa'):
                at.setdefault(e['logistics'] or e['stage'], e['created_at'])
        detail = [{'code': x, 'label': step_label(x, r['shipping']), 'state': 'done' if i < idx or finished else 'current' if i == idx else 'pending',
                   'at': at.get(x, '') if i <= idx else ''} for i, x in enumerate(steps_of)]
        for d in detail:
            if d['state'] == 'done' and d['code'] not in reached and d['code'] not in ('solicitado',):
                d['state'] = 'skipped'  # superado por una corrección de administración, sin evento propio: nunca se pinta como completado
        route = []
        if r['shipping']:
            for code, label, icon, members in PHASES[r['shipping']]:
                pos = [steps_of.index(m) for m in members]
                state = 'done' if max(pos) < idx or finished else 'current' if min(pos) <= idx <= max(pos) else 'pending'
                route.append({'code': code, 'label': label, 'icon': icon, 'state': state})
        incident = INCIDENTS.get(r['incident'], ('', ''))[0]
        moving = r['situation'] == 'normal'
        vehicle = ''
        if r['situation'] != 'cancelado' and r['shipping']:
            vehicle = {'despachado': 'plane-parked' if r['shipping'] == 'internacional' else 'truck-parked', 'transito_internacional': 'plane' if moving else 'plane-stopped',
                       'llegada_pais': 'plane-landed', 'distribucion_nacional': 'truck' if moving else 'truck-stopped', 'ruta_otavalo': 'truck' if moving else 'truck-stopped',
                       'transito_nacional': 'truck' if moving else 'truck-stopped', 'recibido': 'truck-arrived'}.get(current, '')
        customs = ''
        if r['shipping'] == 'internacional' and idx >= steps_of.index('llegada_pais'):
            customs = ({'documentacion_pendiente': 'Documentación requerida', 'retencion_aduanera': 'Retención aduanera'}.get(r['incident'])
                       or {'llegada_pais': 'Llegada al país · pendiente de revisión', 'aduana_revision': 'En proceso aduanero'}.get(current)
                       or ('Liberado por aduana' if 'aduana_liberado' in reached else 'Sin registro de liberación aduanera'))
        item.update(fine=current, fine_label=step_label(current, r['shipping']), detail=detail, route=route, vehicle_mode=vehicle, customs=customs, incident_label=incident,
                    shipping_label={'nacional': 'Nacional', 'internacional': 'Internacional'}.get(r['shipping'], 'Sin definir'))
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
            'staff': [dict(r) for r in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN ('administrador','tecnico') ORDER BY name")],
            'flows': {k: [{'code': x, 'label': step_label(x, k)} for x in v] for k, v in FLOWS.items()}, 'incidents': {k: {'label': v[0], 'situation': v[1]} for k, v in INCIDENTS.items()}}


# ---- Vista pública (modelo seguro: solo se construye con campos permitidos; los textos se revisan contra datos del proveedor) -------------

PUBLIC_STEPS = (('solicitud', 'Solicitud registrada', ('solicitado',)), ('confirmado', 'Repuesto confirmado', ('confirmado', 'preparacion')),
                ('traslado', 'En traslado hacia PC-DOCTOR', ('transito',)), ('recibido', 'Recibido en el taller', ('recibido',)),
                ('instalacion', 'Instalación y pruebas', ('instalacion',)), ('finalizado', 'Proceso finalizado', ('instalado', 'listo')))
# Descripción breve de cada evento del historial público (coherente con la línea de etapas).
HISTORY_TEXT = {'solicitado': 'Se registró la solicitud del repuesto.', 'confirmado': 'El repuesto fue confirmado.', 'preparacion': 'El repuesto se prepara para su envío.',
                'transito': 'El repuesto salió hacia nuestro taller.', 'recibido': 'El repuesto llegó a nuestro taller.', 'instalacion': 'Comenzó la instalación y las pruebas.',
                'instalado': 'La instalación y las pruebas terminaron.', 'listo': 'El proceso del repuesto finalizó.'}
HISTORY_LABELS = {'solicitado': 'Solicitud registrada', 'confirmado': 'Repuesto confirmado', 'preparacion': 'En preparación para el envío', 'transito': 'En traslado hacia PC-DOCTOR',
                  'recibido': 'Recibido en el taller', 'instalacion': 'Instalación y pruebas', 'instalado': 'Instalación finalizada', 'listo': 'Proceso finalizado'}
PUBLIC_SITUATIONS = {'normal': 'Sin novedad', 'espera_confirmacion': 'En espera de confirmación', 'espera_proveedor': 'En espera de disponibilidad', 'retrasado': 'Llegada con retraso',
                     'incidencia_transporte': 'Novedad en el traslado', 'cancelado': 'Pedido cancelado'}
DESCRIPTIONS = {'solicitud': 'Registramos la solicitud del repuesto y estamos gestionando su adquisición.', 'confirmado': 'El repuesto ha sido confirmado y se encuentra en proceso.',
                'traslado': 'El repuesto se encuentra en traslado hacia PC-DOCTOR.', 'recibido': 'El repuesto ya fue recibido en nuestro taller y será instalado.',
                'instalacion': 'Estamos realizando la instalación y las pruebas.', 'finalizado': 'El proceso del repuesto ha finalizado correctamente.',
                'espera_confirmacion': 'Estamos esperando la confirmación del repuesto. Le informaremos en cuanto la tengamos.',
                'espera_proveedor': 'El repuesto está en espera de disponibilidad. Le informaremos en cuanto tengamos novedades.',
                'retrasado': 'La llegada del repuesto presenta un retraso. Le informaremos la nueva fecha cuando esté confirmada.',
                'incidencia_transporte': 'Se presentó una novedad en el traslado del repuesto y la estamos gestionando.',
                'cancelado': 'El pedido de este repuesto fue cancelado. Nos comunicaremos con usted para indicarle las alternativas.'}
# Nombres que nunca deben llegar al cliente: mercados en línea y empresas de transporte (además de los datos de cada pedido).
PRIVATE_TERMS = ('ebay', 'mercado libre', 'mercadolibre', 'amazon', 'aliexpress', 'alibaba', 'temu', 'shein', 'wish', 'olx', 'servientrega', 'tramaco',
                 'laar courier', 'laarcourier', 'dhl', 'fedex', 'ups', 'urbano express', 'correos del ecuador', 'courier')


def _fold(text):
    import unicodedata
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text or '').lower()) if unicodedata.category(ch) != 'Mn')


def private_terms(c, row):
    """Lo que identifica al proveedor y la logística de un pedido: su proveedor, transportista, guía, pedido y dominio de rastreo."""
    terms = list(PRIVATE_TERMS)
    if row['supplier_id']:
        found = c.execute('SELECT name FROM suppliers WHERE id=?', (row['supplier_id'],)).fetchone()
        if found:
            terms.append(found[0])
    terms += [row['carrier'], row['tracking_number'], row['supplier_order']]
    host = re.match(r'https://([^/]+)', row['tracking_url'] or '')
    if host:
        terms.append(host.group(1).replace('www.', ''))
    return [t for t in (_fold(x).strip() for x in terms) if len(t) >= 3 or t == 'ups']


def leaks(text, terms):
    folded = _fold(text)
    return [t for t in terms if re.search(r'(?<![a-z0-9])' + re.escape(t) + r'(?![a-z0-9])', folded)]


def _check_public(c, row, text):
    found = leaks(text, private_terms(c, row)) if text else []
    if found:
        raise PartError('El mensaje para el cliente menciona datos del proveedor o del transporte («%s»): quítalos; el cliente solo ve el avance desde PC-DOCTOR.' % found[0],
                        400, {'public_note': 'Contiene datos del proveedor o del transporte.'})


def _scrub(text, terms):
    out = str(text or '')
    for t in terms:
        out = re.sub(r'(?i)(?<![a-z0-9])' + r'\s*'.join(re.escape(w) for w in t.split()) + r'(?![a-z0-9])', '', out)
    return re.sub(r'\s{2,}', ' ', out).strip(' ·-')


def public(c, oid):
    """Seguimiento de repuestos para el cliente. Se construye solo con campos permitidos (nombre, etapa, fechas, mensajes públicos):
    nunca costos, proveedor, mercado, compra, pedido, guía, transportista, enlaces ni notas. Los textos se revisan otra vez contra los datos
    del proveedor y la logística; un mensaje que los contenga no se muestra. La etapa «En traslado» solo aparece si se registró."""
    out = []
    for r in c.execute('SELECT * FROM order_part_requests WHERE order_id=? AND public_visible=1 ORDER BY id', (oid,)).fetchall():
        terms = private_terms(c, r)
        events = c.execute('SELECT kind,stage,situation,public_note,public,created_at FROM order_part_events WHERE request_id=? ORDER BY id', (r['id'],)).fetchall()
        first = {}
        for e in events:
            if e['kind'] in ('alta', 'etapa'):
                first.setdefault(e['stage'], e['created_at'])
        # Seis etapas siempre visibles. «En traslado» solo se completa si se registró; si el repuesto llegó sin ese evento (corrección de
        # administración), queda como «no registrada» y nunca se pinta como completada.
        steps = PUBLIC_STEPS
        transit = 'transito' in first
        group = next(i for i, s in enumerate(steps) if r['stage'] in s[2])
        finished = r['stage'] == 'listo' and r['situation'] != 'cancelado'
        public_steps = []
        for i, (code, label, stages) in enumerate(steps):
            state = 'done' if i < group or finished else 'current' if i == group else 'pending'
            if code == 'traslado' and state == 'done' and not transit:
                state = 'skipped'
            at = min((first[x] for x in stages if x in first), default='') if state in ('done', 'current') else ''
            public_steps.append({'code': code, 'label': label, 'state': state, 'at': at, 'color': i})
        # Vehículo: solo con un traslado real. En traslado: avanza (o se detiene si hay retraso o incidencia); recibido: llega y se detiene.
        cancelled = r['situation'] == 'cancelado'
        vehicle = ('' if cancelled or not transit else 'stopped' if r['stage'] == 'transito' and r['situation'] != 'normal' else 'transit' if r['stage'] == 'transito'
                   else 'arrived' if r['stage'] == 'recibido' else '')
        history = []
        last_stage = None
        for e in events:
            # Los pasos logísticos internos (despacho, vuelo, aduana…) son, para el cliente, un solo «En traslado»: no se repiten.
            if e['kind'] == 'etapa' and e['stage'] == last_stage and not (e['public'] and e['public_note']):
                continue
            if e['kind'] in ('alta', 'etapa'):
                last_stage = e['stage']
            label = ('Solicitud registrada' if e['kind'] == 'alta' else HISTORY_LABELS.get(e['stage'], '') if e['kind'] == 'etapa'
                     else PUBLIC_SITUATIONS.get(e['situation'], '') if e['kind'] == 'situacion' else '')
            text = e['public_note'] if e['public'] and e['public_note'] and not leaks(e['public_note'], terms) else ''
            if label or text:
                detail = (HISTORY_TEXT['solicitado'] if e['kind'] == 'alta' else HISTORY_TEXT.get(e['stage'], '') if e['kind'] == 'etapa'
                          else DESCRIPTIONS.get(e['situation'], 'La situación del repuesto volvió a la normalidad.') if e['kind'] == 'situacion' else '')
                history.append({'at': e['created_at'], 'label': label or 'Mensaje del taller', 'detail': detail, 'text': text,
                                'color': next((i for i, s in enumerate(steps) if e['stage'] in s[2]), 0), 'kind': e['kind'], 'situation': e['situation']})
        situation = r['situation']
        out.append({'name': _scrub(r['name'], terms) or 'Repuesto', 'brand': _scrub(r['brand'], terms), 'stage': r['stage'], 'situation': situation,
                    'situation_label': PUBLIC_SITUATIONS[situation] if situation != 'normal' else '', 'tone': SITUATIONS[situation][1],
                    'status_label': PUBLIC_SITUATIONS[situation] if situation != 'normal' else ('Proceso finalizado' if finished else steps[group][1]),
                    'description': DESCRIPTIONS[situation] if situation != 'normal' else DESCRIPTIONS[steps[group][0]] if not finished else DESCRIPTIONS['finalizado'],
                    'requested': r['created_at'], 'eta': r['eta'] if CODES.index(r['stage']) < CODES.index('recibido') and situation != 'cancelado' else '',
                    'received': r['received_at'], 'updated': events[-1]['created_at'] if events else r['updated_at'], 'steps': public_steps,
                    'waiting': CODES.index(r['stage']) < CODES.index('recibido') and situation != 'cancelado', 'history': history[::-1][:12],
                    'vehicle': vehicle, 'done_count': sum(1 for x in public_steps if x['state'] == 'done'), 'total': len(public_steps), 'current_index': group if not finished else len(steps)})
    return out
