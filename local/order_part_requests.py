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
from datetime import date, datetime

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


# ---- Mapa de ruta (06/11/2026): mismo modelo para el panel interno y el enlace público. Todo sale del paso real registrado: el vehículo
# (avión o camión) se ubica en su tramo según ese paso y, al cargar, recorre solo el trecho desde el paso anterior; nunca se simulan
# kilómetros, ubicación GPS ni avance por el tiempo transcurrido. Lienzo SVG de 1000 × 158 unidades (se escala con el ancho). El vehículo
# va en su propio carril y se detiene antes de cada punto de control (margen CLEARANCE): nunca tapa un punto ni sus textos.
MAP_Y = 80
CLEARANCE = 58   # distancia mínima (en unidades del lienzo) entre el centro del vehículo y el de un punto de control
LANE = -24       # carril del camión: sobre la línea de ruta, nunca encima de los puntos ni de sus textos
MAPS = {
    'internacional': {'nodes': (('origen', 120, ('solicitado', 'confirmado', 'preparacion', 'despachado')), ('ecuador', 520, ('llegada_pais', 'aduana_revision', 'aduana_liberado')),
                                ('otavalo', 740, ('ruta_otavalo',)), ('taller', 895, ('recibido', 'instalacion', 'instalado', 'listo'))),
                      'segments': (('air', 'aire', 'M120 80 Q320 0 520 80', ('despachado', 'transito_internacional')),
                                   ('road1', 'tierra', 'M520 80 L740 80', ('aduana_liberado', 'distribucion_nacional', 'ruta_otavalo')),
                                   ('road2', 'tierra', 'M740 80 L895 80', ('recibido',))),
                      'vehicle': {'despachado': ('plane', 'air', 0.0, 0.0, 'parked'), 'transito_internacional': ('plane', 'air', 0.0, 0.5, 'moving'),
                                  'llegada_pais': ('plane', 'air', 0.5, 1.0, 'landed'), 'aduana_liberado': ('truck', 'road1', 0.0, 0.0, 'parked'),
                                  'distribucion_nacional': ('truck', 'road1', 0.0, 0.45, 'moving'), 'ruta_otavalo': ('truck', 'road1', 0.45, 1.0, 'moving'),
                                  'recibido': ('truck', 'road2', 0.0, 1.0, 'arrived')}},
    'nacional': {'nodes': (('origen', 120, ('solicitado', 'confirmado', 'preparacion', 'despachado')), ('otavalo', 690, ('ruta_otavalo',)),
                           ('taller', 895, ('recibido', 'instalacion', 'instalado', 'listo'))),
                 'segments': (('road1', 'tierra', 'M120 80 L690 80', ('despachado', 'transito_nacional', 'ruta_otavalo')), ('road2', 'tierra', 'M690 80 L895 80', ('recibido',))),
                 'vehicle': {'despachado': ('truck', 'road1', 0.0, 0.0, 'parked'), 'transito_nacional': ('truck', 'road1', 0.0, 0.5, 'moving'),
                             'ruta_otavalo': ('truck', 'road1', 0.5, 1.0, 'moving'), 'recibido': ('truck', 'road2', 0.0, 1.0, 'arrived')}}}
NODE_TEXT = {'internacional': {'origen': ('Origen', 'globe'), 'ecuador': ('Ecuador · Aduana', 'customs'), 'otavalo': ('Otavalo', 'pin'), 'taller': ('PC-DOCTOR', 'shop')},
             'nacional': {'origen': ('Despacho', 'box'), 'otavalo': ('Otavalo', 'pin'), 'taller': ('PC-DOCTOR', 'shop')}}
VEHICLE_TEXT = {'parked': 'listo para salir', 'moving': 'en camino', 'stopped': 'detenido por una novedad', 'landed': 'aterrizó en Ecuador', 'arrived': 'llegó a PC-DOCTOR'}


def _path_point(path, fraction):
    """Punto (x, y) y ángulo de la tangente a la fracción `fraction` de la longitud del trazo (recta o curva cuadrática)."""
    import math
    nums = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', path)]
    if 'Q' in path:
        (x0, y0, cx, cy, x1, y1) = nums
        pts = [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1) for t in (i / 200 for i in range(201))]
    else:
        (x0, y0, x1, y1) = nums
        pts = [(x0 + (x1 - x0) * i / 200, y0 + (y1 - y0) * i / 200) for i in range(201)]
    lengths = [0.0]
    for a, b in zip(pts, pts[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    goal = max(0.0, min(1.0, fraction)) * lengths[-1]
    i = next((k for k, v in enumerate(lengths) if v >= goal), len(lengths) - 1)
    a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, max(1, i))]
    return round(pts[i][0], 1), round(pts[i][1], 1), round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])), 1)


def _path_length(path):
    import math
    nums = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', path)]
    if 'Q' not in path:
        return math.dist(nums[:2], nums[2:4])
    (x0, y0, cx, cy, x1, y1) = nums
    pts = [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1) for t in (i / 200 for i in range(201))]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _safe(path, fraction):
    """Fracción del trazo con margen de seguridad: el vehículo nunca queda sobre un punto de control (se detiene antes de llegar)."""
    margin = min(0.45, CLEARANCE / _path_length(path))
    return round(margin + max(0.0, min(1.0, fraction)) * (1 - 2 * margin), 4)


def route_map(shipping, current, reached, at, finished, situation, public=False, origin_country='', customs=''):
    """Mapa del envío: nodos (origen, Ecuador y aduana, Otavalo, PC-DOCTOR), tramos (aéreo y terrestre) y vehículo. Vacío sin tipo de envío."""
    if shipping not in MAPS:
        return None
    spec, steps = MAPS[shipping], FLOWS[shipping]
    idx = steps.index(current) if current in steps else 0
    cancelled = situation == 'cancelado'
    nodes = []
    for code, x, covered in spec['nodes']:
        pos = [steps.index(m) for m in covered]
        state = 'done' if finished or idx > max(pos) else 'current' if min(pos) <= idx <= max(pos) else 'pending'
        if code == 'otavalo' and state == 'current' and current != 'ruta_otavalo':
            state = 'pending'
        label, icon = NODE_TEXT[shipping][code]
        sub = ''
        if code == 'origen':
            sub = ('Envío internacional' if public or not origin_country else origin_country) if shipping == 'internacional' else 'Envío nacional'
        elif code == 'ecuador':
            sub = customs if not public else ({'aduana_revision': 'En proceso de aduana', 'llegada_pais': 'Llegada al país'}.get(current)
                                              or ('Liberado por aduana' if 'aduana_liberado' in reached else ''))
        elif code == 'otavalo':
            sub = 'Imbabura'
        elif code == 'taller':
            sub = 'Recibido' if 'recibido' in reached else 'Destino final'
        first = next((at.get(m) for m in covered if at.get(m)), '')
        nodes.append({'code': code, 'x': x, 'label': label, 'sub': sub, 'icon': icon, 'state': state, 'at': first if state != 'pending' else '',
                      'customs': code == 'ecuador' and current in ('llegada_pais', 'aduana_revision')})
    segments = []
    for code, kind, path, covered in spec['segments']:
        pos = [steps.index(m) for m in covered]
        state = 'done' if finished or idx > max(pos) else 'active' if min(pos) <= idx <= max(pos) else 'pending'
        segments.append({'code': code, 'kind': kind, 'path': path, 'state': state})
    vehicle = None
    found = spec['vehicle'].get(current)
    if found and not cancelled and not finished:
        kind, seg, start, end, motion = found
        if motion == 'moving' and situation != 'normal':
            motion = 'stopped'
        path = next(x['path'] for x in segments if x['code'] == seg)
        start, end = _safe(path, start), _safe(path, end)
        fx, fy, fa = _path_point(path, start)
        x, y, angle = _path_point(path, end)
        lane = LANE if kind == 'truck' else 0
        y, fy = round(y + lane, 1), round(fy + lane, 1)
        vehicle = {'kind': kind, 'segment': seg, 'path': path, 'from': start, 'to': end, 'motion': motion, 'animate': motion in ('moving', 'landed', 'arrived') and end > start,
                   'x': x, 'y': y, 'angle': angle if kind == 'plane' else 0, 'fx': fx, 'fy': fy, 'lane': lane,
                   'text': ('Avión ' if kind == 'plane' else 'Vehículo de transporte ') + VEHICLE_TEXT[motion]}
    return {'mode': shipping, 'nodes': nodes, 'segments': segments, 'vehicle': vehicle, 'cancelled': cancelled, 'finished': finished,
            'customs_active': shipping == 'internacional' and current == 'aduana_revision' and not cancelled}


FIELDS = {'name': ('Nombre del repuesto', 160), 'brand': ('Marca', 80), 'compatible_model': ('Modelo compatible', 120), 'reference': ('Código o referencia', 80),
          'supplier_order': ('Número de pedido', 60), 'carrier': ('Empresa transportista', 80), 'tracking_number': ('Número de guía', 80),
          'tracking_url': ('Enlace de rastreo', 300), 'internal_note': ('Observaciones internas', 1500), 'origin_country': ('País de origen', 60),
          'national_carrier': ('Transportista nacional', 80), 'national_tracking': ('Guía nacional', 80)}
DATES = {'purchase_date': 'Fecha de compra', 'eta': 'Fecha estimada de llegada', 'received_at': 'Fecha de recepción', 'dispatch_date': 'Fecha de despacho',
         'customs_in_date': 'Fecha de ingreso a aduana', 'customs_out_date': 'Fecha de liberación de aduana'}
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
    if out['customs_in_date'] and out['customs_out_date'] and out['customs_out_date'] < out['customs_in_date']:
        raise PartError('La liberación de aduana no puede ser anterior al ingreso.', 400, {'customs_out_date': 'Anterior al ingreso.'})
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


# Hitos del repuesto que también quedan en el historial de la orden (1.5.249): recepción, instalación y pruebas, fin del proceso y cancelación.
ORDER_EVENTS = {'recibido': 'Repuesto «%s» recibido en el taller.', 'instalacion': 'Repuesto «%s»: comenzó la instalación y las pruebas.',
                'instalado': 'Repuesto «%s»: instalación y pruebas finalizadas.', 'listo': 'Repuesto «%s»: proceso finalizado; la orden puede continuar hacia la entrega.'}


def _dmy(value):
    try:
        return datetime.fromisoformat(value).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return str(value or '')


def order_event(c, oid, user, now, text):
    """Anota el hito en el historial de la orden (evento de seguimiento, con su usuario y fecha). No cambia el estado de la orden."""
    import order_workspace
    order_workspace.event(c, oid, user['id'] if user else None, now, 'follow_up', text)


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
    # Fechas de aduana: se registran solas con el evento real (si estaban vacías); nunca se suponen sin él.
    customs_in = row['customs_in_date'] or (now.date().isoformat() if target == 'aduana_revision' and want > have else '')
    customs_out = row['customs_out_date'] or (now.date().isoformat() if target == 'aduana_liberado' and want > have else '')
    c.execute("UPDATE order_part_requests SET stage=?,logistics=?,situation=?,incident=CASE WHEN ? THEN '' ELSE incident END,received_at=?,dispatch_date=?,customs_in_date=?,customs_out_date=?,updated_at=? WHERE id=?",
              (coarse, logistics, situation, 1 if want > have else 0, received, dispatch, customs_in, customs_out, stamp(now), row['id']))
    _event(c, row, 'etapa', user, now, note=note or ('Corrección de etapa' if want < have else 'Avanza a: ' + step_label(target, row['shipping'])),
           public_note=text, public=public, stage=coarse, situation=situation, changes={'stage': [fine(row), target]}, logistics=logistics)
    if want > have and target in ORDER_EVENTS:
        order_event(c, oid, user, now, ORDER_EVENTS[target] % row['name'] + (' Fecha de recepción: %s.' % _dmy(received) if target == 'recibido' else ''))
    notice = ('despachado' if target == 'transito' else target) if want > have else ''
    return {'stage': coarse, 'logistics': logistics, 'situation': situation, 'notify': [notice, 'etapa:' + notice] if notice in NOTICE_STAGES else None}


NOTICE_STAGES = ('confirmado', 'despachado', 'llegada_pais', 'aduana_revision', 'aduana_liberado', 'recibido', 'listo')


def set_situation(c, oid, rid, data, user, now):
    """Registra una espera, un retraso o una incidencia (con motivo) y, si se confirmó, la nueva fecha estimada. La cancelación pasa por
    part_cancellations (la decide administración y queda en su registro)."""
    _staff(user)
    row = _request(c, oid, rid)
    if row['situation'] == 'cancelado':
        raise PartError('El pedido ya está cancelado.', 409)
    situation = str(data.get('situation', ''))
    if situation == 'cancelado':
        import part_cancellations
        if user['role'] != 'administrador':
            raise PartError('La cancelación la decide administración: registra una solicitud de cancelación para que la revise.', 403)
        result = part_cancellations.direct(c, oid, rid, {**data, 'reason_code': data.get('reason_code') or 'administrativa', 'confirm_supplier': '1', 'confirm_transit': '1'}, user, now)
        return {'situation': 'cancelado', **result, 'notify': ['cancelacion_aprobada', 'cancelacion_aprobada:%d' % result['cancellation_id']]}
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
    last = c.execute('SELECT MAX(id) FROM order_part_events WHERE request_id=?', (row['id'],)).fetchone()[0]
    return {'situation': situation, 'incident': incident, 'eta': eta, 'notify': ['retraso', 'retraso:%d' % last] if situation == 'retrasado' else None}


def stages(r, events):
    """Etapas visibles del repuesto: UNA sola fuente para el seguimiento público, el panel del taller, el avance y la hoja A4.
    Una etapa superada solo cuenta como completada si tiene su evento real registrado (alta o etapa); si se superó por una corrección de
    administración sin ese evento, queda «no registrada» y no suma al avance. `events`: filas con kind, stage, logistics y created_at."""
    first, fine_first = {}, {}
    for e in events:
        if e['kind'] in ('alta', 'etapa'):
            first.setdefault(e['stage'], e['created_at'])
            fine_first.setdefault(e['logistics'] or e['stage'], e['created_at'])
    shipping = r['shipping'] if r['shipping'] in PUBLIC_FLOWS else ''
    flow_ = PUBLIC_FLOWS[shipping] if shipping else PUBLIC_STEPS
    current = fine(r)
    key = current if shipping else r['stage']
    seen = fine_first if shipping else first
    group = next((i for i, s in enumerate(flow_) if key in s[2]), 0)
    finished = r['stage'] == 'listo' and r['situation'] != 'cancelado'
    out = []
    for i, (code, label, members) in enumerate(flow_):
        state = 'done' if i < group or finished else 'current' if i == group else 'pending'
        if state == 'done' and code != 'solicitud' and not any(x in seen for x in members):
            state = 'skipped'
        at = min((seen[x] for x in members if x in seen), default='') if state in ('done', 'current') else ''
        out.append({'code': code, 'label': label, 'state': state, 'at': at, 'color': round(i * 5 / max(1, len(flow_) - 1))})
    return {'first': first, 'fine_first': fine_first, 'shipping': shipping, 'flow': flow_, 'current': current, 'group': group, 'finished': finished, 'steps': out}


def progress(c, r):
    """Avance común al panel interno, al seguimiento público y a la hoja A4 (una sola lógica, 1.5.249): se cuenta sobre las MISMAS etapas
    que ve el cliente, así «X de Y etapas» y el porcentaje coinciden en todas las vistas (porcentaje = completadas / total). Solo cuentan
    las etapas con su evento real. También informa la etapa actual, la siguiente y el paso detallado (para el taller).
    La última actualización es el último evento del repuesto o de su cancelación/reembolso (no los avisos)."""
    events = c.execute("SELECT kind,stage,logistics,created_at FROM order_part_events WHERE request_id=? ORDER BY id", (r['id'],)).fetchall()
    st = stages(r, events)
    steps = st['steps']
    done = sum(1 for x in steps if x['state'] == 'done')
    nxt = next((x['label'] for x in steps if x['state'] == 'pending'), '') if r['situation'] != 'cancelado' else ''
    fine_steps = flow(r)
    idx = fine_steps.index(st['current']) if st['current'] in fine_steps else 0
    last = c.execute("SELECT MAX(at) FROM (SELECT created_at at FROM order_part_events WHERE request_id=? UNION ALL "
                     "SELECT created_at FROM order_part_log WHERE request_id=? AND kind!='aviso')", (r['id'], r['id'])).fetchone()[0]
    return {'done': done, 'total': len(steps), 'percent': round(100 * done / len(steps)), 'current': st['current'],
            'current_label': step_label(st['current'], r['shipping']), 'stage_label': steps[st['group']]['label'] if not st['finished'] else steps[-1]['label'],
            'stage_number': len(steps) if st['finished'] else st['group'] + 1, 'next_label': nxt, 'skipped': sum(1 for x in steps if x['state'] == 'skipped'),
            'step_number': idx + 1, 'step_total': len(fine_steps), 'updated': last or r['updated_at']}


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
        import part_cancellations, part_notices
        evidence_steps = {x['part_step']: x['n'] for x in c.execute("SELECT part_step,COUNT(*) n FROM order_followups WHERE part_request_id=? AND part_step!='' GROUP BY part_step", (r['id'],))}
        for d in detail:
            d['evidence'] = evidence_steps.get(d['code'], 0)
        import part_route
        item['progress'] = progress(c, r)
        item['stages'] = stages(r, list(reversed(events)))['steps']  # las mismas etapas que ve el cliente (avance común)
        item['map'] = route_map(r['shipping'], current, reached, at, finished, r['situation'], origin_country=r['origin_country'], customs=customs)
        item['map_html'] = part_route.render(item['map'], 'i%d' % r['id'], r['name'])
        item.update(
                    cancellations=part_cancellations.history(c, r['id']), cancel_context=part_cancellations.context(c, oid, r), notices=part_notices.listing(c, r['id']),
                    log=[dict(x) for x in c.execute('SELECT kind,action,note,origin,actor_id,created_at FROM order_part_log WHERE request_id=? ORDER BY id DESC', (r['id'],))])
        for x in item['log']:
            x['actor'] = names.get(x['actor_id'], 'Cliente' if x['origin'] == 'cliente' else 'Sistema')
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
            'flows': {k: [{'code': x, 'label': step_label(x, k)} for x in v] for k, v in FLOWS.items()}, 'incidents': {k: {'label': v[0], 'situation': v[1]} for k, v in INCIDENTS.items()},
            'cancel_reasons': __import__('part_cancellations').REASONS, 'cancel_channels': __import__('part_cancellations').CHANNELS,
            'notices_enabled': __import__('part_notices').enabled(c), 'whatsapp': __import__('order_followups').whatsapp_status()}


# ---- Vista pública (modelo seguro: solo se construye con campos permitidos; los textos se revisan contra datos del proveedor) -------------

PUBLIC_STEPS = (('solicitud', 'Solicitud registrada', ('solicitado',)), ('confirmado', 'Repuesto confirmado', ('confirmado', 'preparacion')),
                ('traslado', 'En traslado hacia PC-DOCTOR', ('transito',)), ('recibido', 'Recibido en el taller', ('recibido',)),
                ('instalacion', 'Instalación y pruebas', ('instalacion',)), ('finalizado', 'Proceso finalizado', ('instalado', 'listo')))
# Envíos con tipo definido: etapas públicas propias (el internacional muestra el vuelo y la aduana; el nacional, el traslado terrestre).
PUBLIC_FLOWS = {
    'internacional': (('solicitud', 'Solicitud registrada', ('solicitado',)), ('confirmado', 'Repuesto confirmado', ('confirmado', 'preparacion')),
                      ('aereo', 'Envío internacional', ('despachado', 'transito_internacional', 'llegada_pais')), ('aduana', 'Proceso de aduana', ('aduana_revision', 'aduana_liberado')),
                      ('nacional', 'Traslado hacia Otavalo', ('distribucion_nacional', 'ruta_otavalo')), ('recibido', 'Recibido en el taller', ('recibido',)),
                      ('instalacion', 'Instalación y pruebas', ('instalacion',)), ('finalizado', 'Proceso finalizado', ('instalado', 'listo'))),
    'nacional': (('solicitud', 'Solicitud registrada', ('solicitado',)), ('confirmado', 'Repuesto confirmado', ('confirmado', 'preparacion')),
                 ('traslado', 'Traslado nacional hacia Otavalo', ('despachado', 'transito_nacional', 'ruta_otavalo')), ('recibido', 'Recibido en el taller', ('recibido',)),
                 ('instalacion', 'Instalación y pruebas', ('instalacion',)), ('finalizado', 'Proceso finalizado', ('instalado', 'listo')))}
FLOW_TEXT = {'despachado': 'El repuesto fue despachado hacia PC-DOCTOR.', 'transito_internacional': 'El repuesto viaja hacia Ecuador.', 'llegada_pais': 'El repuesto llegó a Ecuador.',
             'aduana_revision': 'El repuesto ingresó al proceso de aduana.', 'aduana_liberado': 'El repuesto fue liberado de aduana.',
             'distribucion_nacional': 'El repuesto continúa su traslado dentro de Ecuador.', 'ruta_otavalo': 'El repuesto está en ruta hacia Otavalo.',
             'transito_nacional': 'El repuesto está en traslado nacional.'}
FLOW_LABELS = {'despachado': 'Repuesto despachado', 'transito_internacional': 'En tránsito internacional', 'llegada_pais': 'Llegada a Ecuador',
               'aduana_revision': 'En proceso de aduana', 'aduana_liberado': 'Liberado de aduana', 'distribucion_nacional': 'Traslado nacional',
               'ruta_otavalo': 'En ruta hacia Otavalo', 'transito_nacional': 'En tránsito nacional'}
GROUP_TEXT = {'aereo': 'El repuesto está en su envío internacional hacia Ecuador.', 'aduana': 'El repuesto se encuentra en el proceso de aduana en Ecuador.',
              'nacional': 'El repuesto continúa su traslado hacia Otavalo.', 'traslado': 'El repuesto está en traslado nacional hacia PC-DOCTOR.'}
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
    terms += [row['carrier'], row['tracking_number'], row['supplier_order'], row['national_carrier'], row['national_tracking']]
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
        events = c.execute('SELECT kind,stage,situation,public_note,public,created_at,logistics FROM order_part_events WHERE request_id=? ORDER BY id', (r['id'],)).fetchall()
        st = stages(r, events)
        first, fine_first, shipping, steps, current, group, finished, public_steps = (st['first'], st['fine_first'], st['shipping'], st['flow'], st['current'], st['group'],
                                                                                      st['finished'], st['steps'])
        transit = 'transito' in first
        # Vehículo: solo con un traslado real. En traslado: avanza (o se detiene si hay retraso o incidencia); recibido: llega y se detiene.
        cancelled = r['situation'] == 'cancelado'
        vehicle = ('' if cancelled or not transit or shipping else 'stopped' if r['stage'] == 'transito' and r['situation'] != 'normal' else 'transit' if r['stage'] == 'transito'
                   else 'arrived' if r['stage'] == 'recibido' else '')
        reached = set(fine_first)
        at = {k: v for k, v in fine_first.items()}
        history = []
        last_stage = None
        for e in events:
            step = (e['logistics'] or e['stage']) if shipping else e['stage']
            # Sin tipo de envío, los pasos logísticos internos son, para el cliente, un solo «En traslado»: no se repiten.
            if e['kind'] == 'etapa' and step == last_stage and not (e['public'] and e['public_note']):
                continue
            if e['kind'] in ('alta', 'etapa'):
                last_stage = step
            label = ('Solicitud registrada' if e['kind'] == 'alta' else (FLOW_LABELS.get(step) if shipping else None) or HISTORY_LABELS.get(e['stage'], '') if e['kind'] == 'etapa'
                     else PUBLIC_SITUATIONS.get(e['situation'], '') if e['kind'] == 'situacion' else '')
            text = e['public_note'] if e['public'] and e['public_note'] and not leaks(e['public_note'], terms) else ''
            if label or text:
                detail = (HISTORY_TEXT['solicitado'] if e['kind'] == 'alta' else (FLOW_TEXT.get(step) if shipping else None) or HISTORY_TEXT.get(e['stage'], '') if e['kind'] == 'etapa'
                          else DESCRIPTIONS.get(e['situation'], 'La situación del repuesto volvió a la normalidad.') if e['kind'] == 'situacion' else '')
                history.append({'at': e['created_at'], 'label': label or 'Mensaje del taller', 'detail': detail, 'text': text,
                                'color': next((round(i * 5 / max(1, len(steps) - 1)) for i, s in enumerate(steps) if step in s[2]), 0), 'kind': e['kind'], 'situation': e['situation']})
        # Cancelación: estado y fecha (sin importes ni motivos internos), en el historial y en el estado actual.
        import part_cancellations
        cancel = part_cancellations.public_state(c, r['id'])
        for x in c.execute("SELECT action,created_at FROM order_part_log WHERE request_id=? AND kind='cancelacion' ORDER BY id", (r['id'],)):
            history.append({'at': x['created_at'], 'label': part_cancellations.STATUS.get(x['action'], 'Cancelación'), 'detail': '', 'text': '', 'color': 0, 'kind': 'cancelacion',
                            'situation': 'cancelado' if x['action'] == 'aprobada' else 'espera_confirmacion'})
        history.sort(key=lambda h: h['at'])
        from reception import reception_now
        cancel_window = part_cancellations.window(r, reception_now())
        cancel_allowed = part_cancellations.phase(r) not in ('recibido', 'cancelado') and not part_cancellations.open_for(c, r['id'])
        situation = r['situation']
        out.append({'name': _scrub(r['name'], terms) or 'Repuesto', 'brand': _scrub(r['brand'], terms), 'stage': r['stage'], 'situation': situation,
                    'situation_label': PUBLIC_SITUATIONS[situation] if situation != 'normal' else '', 'tone': SITUATIONS[situation][1],
                    'status_label': PUBLIC_SITUATIONS[situation] if situation != 'normal' else ('Proceso finalizado' if finished else steps[group][1]),
                    'description': DESCRIPTIONS[situation] if situation != 'normal' else (GROUP_TEXT.get(steps[group][0]) or DESCRIPTIONS.get(steps[group][0], '')) if not finished else DESCRIPTIONS['finalizado'],
                    'id': r['id'], 'shipping': shipping, 'progress': progress(c, r),
                    'step_label': FLOW_LABELS.get(current, '') if shipping and current in TRANSIT and situation == 'normal' else '', 'map': route_map(shipping, current, reached, at, finished, situation, public=True) if shipping else None,
                    'map_html': __import__('part_route').render(route_map(shipping, current, reached, at, finished, situation, public=True), 'p%d' % r['id'],
                                                                 _scrub(r['name'], terms) or 'Repuesto') if shipping else '',
                    'cancellation': cancel, 'cancel_note': part_cancellations.PUBLIC_PHASES.get(part_cancellations.phase(r), ''),
                    'cancel_window': cancel_window, 'can_cancel': cancel_allowed and cancel_window['open'],
                    'cancel_expired': cancel_allowed and not cancel_window['open'],
                    'requested': r['created_at'], 'eta': r['eta'] if CODES.index(r['stage']) < CODES.index('recibido') and situation != 'cancelado' else '',
                    'received': r['received_at'], 'updated': progress(c, r)['updated'], 'steps': public_steps,
                    'waiting': CODES.index(r['stage']) < CODES.index('recibido') and situation != 'cancelado', 'history': history[::-1][:12],
                    'vehicle': vehicle, 'done_count': sum(1 for x in public_steps if x['state'] == 'done'), 'total': len(public_steps), 'current_index': group if not finished else len(steps)})
    return out
