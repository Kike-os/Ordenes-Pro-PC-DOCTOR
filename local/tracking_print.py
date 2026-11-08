"""Seguimiento de reparación en hoja A4 (1.5.248): informe técnico por secciones para imprimir o guardar como PDF.

Secciones: A cabecera corporativa · B equipo · C progreso de la reparación · D repuestos (con su trayectoria estática) · E observaciones y
avisos · G historial · H transporte · I información técnica · F pie (con QR y código de barras al final y, en cada hoja, el pie corporativo
con la numeración que dibuja seguimiento-a4.css).

Dos versiones que nunca se mezclan:
- «public»: se construye SOLO con lo que ya devuelve order_tracking.lookup (el mismo modelo seguro de la página pública: sin nombre, serie,
  identificación, falla, notas, importes, proveedor, transportista ni guía).
- «admin»: exige sesión de administración o técnico (lo comprueba app.py) y añade cliente, serie, responsable, observaciones internas,
  novedades logísticas, transporte, historial de modificaciones y evidencias.
No escribe nada: solo lee. Los campos que no existen se omiten; nada se inventa. Todo el texto se escapa.
"""
from datetime import datetime
import html

from corporate import settings
from reception import DEVICE_TYPES, ECUADOR_TZ

# Datos del pie corporativo (indicados por la empresa para el documento A4).
ADDRESS = 'Calle Bolívar #608 y García Moreno, junto al Banco Pichincha'
CITY = 'Otavalo, Imbabura, Ecuador'
SITE = 'ecuadorpcdoctor.com'
STAGES = (('Recepción', ('pendiente',)), ('Diagnóstico y reparación', ('diagnostico', 'reparacion', 'esperando_cliente', 'presupuesto', 'esperando_repuesto', 'revision_recurrente', 'pruebas')),
          ('Listo para retiro', ('listo', 'espera_entrega')), ('Entrega', ('entregado',)))
FLAGS = {'esperando_cliente': 'Esperando su respuesta para continuar con la reparación.', 'presupuesto': 'Presupuesto pendiente de su aprobación.',
         'revision_recurrente': 'Equipo en revisión por falla recurrente.', 'esperando_repuesto': 'Esperando la llegada de un repuesto.'}
STEP_WORD = {'done': 'Completado', 'current': 'En curso', 'pending': 'Pendiente', 'skipped': 'No registrada'}
HISTORY_EVENTS = {'created': 'Orden recibida', 'status': 'Cambio de estado', 'follow_up': 'Seguimiento técnico', 'maintenance': 'Mantenimiento', 'proforma': 'Proforma comercial'}
e = html.escape


def _when(value, with_time=True):
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value or '') if value and '/' in str(value) else ''  # ya formateada (dd/mm/aaaa hh:mm)
    if 'T' not in str(value):
        return moment.strftime('%d/%m/%Y')
    return (moment.astimezone(ECUADOR_TZ) if moment.tzinfo else moment).strftime('%d/%m/%Y %H:%M' if with_time else '%d/%m/%Y')


def _sort_key(value):
    """Orden cronológico para fechas ISO o ya formateadas (dd/mm/aaaa hh:mm)."""
    text = str(value or '')
    try:
        return datetime.strptime(text, '%d/%m/%Y %H:%M').strftime('%Y-%m-%dT%H:%M')
    except ValueError:
        try:
            return datetime.fromisoformat(text).astimezone(ECUADOR_TZ).strftime('%Y-%m-%dT%H:%M:%S.%f') if 'T' in text else text
        except (TypeError, ValueError):
            return text


def budget(c, oid):
    """(código, etiqueta) del presupuesto vigente, sin importes: el último no borrador ni cancelado. ('', '') si no existe."""
    try:
        import quotes
        row = c.execute("SELECT status FROM quotes WHERE order_id=? AND status NOT IN ('borrador','cancelado') ORDER BY version DESC,id DESC LIMIT 1", (oid,)).fetchone()
        return (row['status'], quotes.STATUS.get(row['status'], '')) if row else ('', '')
    except Exception:
        return ('', '')  # base anterior a los presupuestos


def budget_label(c, oid):
    return budget(c, oid)[1]


def _facts(rows, cls='pa4-dl'):
    rows = [(k, v) for k, v in rows if v]
    return '<dl class="%s">%s</dl>' % (cls, ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (e(k), e(v)) for k, v in rows)) if rows else ''


def _sec(cls, title, body, keep=True):
    return '<section class="pa4-sec %s%s"><h2>%s</h2>%s</section>' % (cls, ' pa4-keep' if keep else '', e(title), body) if body else ''


def _header(d, audience):
    meta = [('Orden de servicio', d['code']), ('Fecha de impresión', datetime.now(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')), ('Estado general', d['status_label'])]
    rows = ''.join('<div><dt>%s</dt><dd%s>%s</dd></div>' % (e(k), ' class="pa4-mono"' if i == 0 else ' data-printed' if i == 1 else '', e(v)) for i, (k, v) in enumerate(meta))
    return ('<header class="pa4-head"><span class="pa4-logo"><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="2826" height="2049"></span>'
            '<div class="pa4-title"><strong>%s</strong><h1>Seguimiento de Reparación</h1><small>Documento de seguimiento técnico%s</small></div><dl class="pa4-meta">%s</dl></header>'
            % (e(settings()['name']), ' · uso interno del taller' if audience == 'admin' else '', rows))


def _codes(qr_src, code):
    import barcode128
    try:
        bars = barcode128.svg(code, color='#0b1526', background='#ffffff')
    except barcode128.BarcodeError:
        bars = ''
    qr = '<img class="pa4-qr" src="%s" alt="Código QR del seguimiento de la orden %s" width="120" height="120">' % (e(qr_src), e(code)) if qr_src else ''
    return '<div class="pa4-codes">%s<div class="pa4-bars">%s<span>%s</span></div></div>' % (qr, bars, e(code)) if qr or bars else ''


def _equipment(d, audience, qr_src=''):
    left = [('Tipo de equipo', d.get('kind')), ('Marca', d.get('brand')), ('Modelo', d.get('model'))]
    if audience == 'admin':
        left = [('Cliente', d.get('client'))] + left + [('Número de serie', d.get('serial'))]
    right = [('Fecha de ingreso', d.get('received')), ('Última actualización', d.get('updated')), ('Estado de reparación', d.get('status_label')),
             ('Estado del presupuesto', d.get('budget'))]
    if audience == 'admin':
        right.append(('Técnico responsable', d.get('responsible') or 'Sin asignar'))
    return _sec('pa4-b', 'Información del equipo', '<div class="pa4-cols">%s%s%s</div>' % (_facts(left), _facts(right), _codes(qr_src, d['code'])))


def _progress(d):
    """Progreso de la reparación. 1.5.252: las 6 etapas de repair_stages (las mismas del panel y del cliente), con su estado escrito y fecha."""
    if d.get('repair'):
        r = d['repair']
        words = {'done': 'Completado', 'current': 'Etapa actual', 'warn': 'En espera', 'pending': 'Pendiente'}
        items = ''.join('<li data-state="%s"><i>%s</i><b>%s</b><small>%s%s</small></li>' % (
            'incident' if s['state'] == 'warn' else s['state'], '✓' if s['state'] == 'done' else i + 1, e(s['label']), words[s['state']],
            '<br>' + e(_when(s['at'])) if s['at'] else '') for i, s in enumerate(r['stages']))
        alerts = ''.join('<p class="pa4-alert" data-tone="warn"><b>%s.</b> %s</p>' % (e(a['title']), e(a['text'])) for a in r['alerts'])
        now = 'Reparación finalizada y entregada.' if r['finished'] else 'Etapa actual: %s.' % r['current_label']
        return _sec('pa4-c', 'Progreso de reparación', '<ol class="pa4-steps">%s</ol><p class="pa4-now"><b>Estado actual:</b> %s · %s</p>%s' % (items, e(d['status_label']), e(now), alerts))
    status = d['status']
    current = max(0, next((i for i, s in enumerate(STAGES) if status in s[1]), 0))
    done = status == 'entregado'
    items = ''
    for i, (label, _) in enumerate(STAGES):
        state = 'done' if i < current or done else 'current' if i == current else 'pending'
        if state == 'current' and status == 'revision_recurrente':
            state = 'incident'
        word = {'done': 'Completado', 'current': 'Etapa actual', 'pending': 'Pendiente', 'incident': 'Incidencia'}[state]
        items += '<li data-state="%s"><i>%s</i><b>%s</b><small>%s</small></li>' % (state, '✓' if state == 'done' else i + 1, e(label), word)
    now = 'Reparación finalizada y entregada.' if done else 'Etapa actual: %s.' % STAGES[current][0]
    return _sec('pa4-c', 'Progreso de reparación', '<ol class="pa4-steps">%s</ol><p class="pa4-now"><b>Estado actual:</b> %s %s</p>' % (items, e(d['status_label']) + ' ·', e(now)))


def _route(route, uid, name):
    if not route:
        return ''
    import part_route
    return '<div class="pa4-route">%s</div>' % part_route.render(route, uid, name)


def _track(steps):
    """Etapas del repuesto en línea horizontal (sin animación): número o ✓, nombre, estado en texto y fecha."""
    items = ''
    for i, s in enumerate(steps):
        items += '<li data-state="%s"><i>%s</i><b>%s</b><small>%s%s</small></li>' % (
            e(s['state']), '✓' if s['state'] == 'done' else '–' if s['state'] == 'skipped' else i + 1, e(s['label']), STEP_WORD.get(s['state'], ''),
            ' · ' + e(_when(s['at'], False)) if s.get('at') else '')
    return '<ol class="pa4-track">%s</ol>' % items


def _public_part(p):
    pct = p['progress']['percent'] if p.get('progress') else round(100 * p['done_count'] / max(1, p['total']))
    confirmed = next((s['at'] for s in p['steps'] if s['code'] == 'confirmado' and s['state'] in ('done', 'current') and s['at']), '')
    nxt = (p.get('progress') or {}).get('next_label', '') if p['situation'] != 'cancelado' else ''
    facts = [('Estado logístico', p['status_label'] + (' · ' + p['step_label'] if p.get('step_label') else '')), ('Próxima etapa', nxt),
             ('Tipo de envío', {'nacional': 'Nacional', 'internacional': 'Internacional'}.get(p.get('shipping'), '')),
             ('Solicitud (real)', _when(p['requested'], False)), ('Confirmación (confirmada)', _when(confirmed, False) if confirmed else ''),
             ('Disponibilidad (estimada)', _when(p['eta'], False) if p.get('eta') else ''),
             ('Recepción (real)', _when(p['received'], False) if p.get('received') else ''), ('Última actualización', _when(p['updated'])),
             ('Avance', '%d de %d etapas · %d\u00a0%%' % (p['done_count'], p['total'], pct))]
    cancel = p.get('cancellation')
    note = '<p class="pa4-alert" data-tone="warn"><b>%s.</b> %s</p>' % (e(cancel['label']), e(cancel['text'])) if cancel else ''
    return ('<article class="pa4-part" data-tone="%s"><header><div><h3>%s</h3>%s</div><span class="pa4-chip" data-tone="%s">%s</span></header><p class="pa4-desc">%s</p>%s%s%s%s</article>'
            % (e(p['tone']), e(p['name']), '<small>%s</small>' % e(p['brand']) if p.get('brand') else '', e(p['tone']), e(p['status_label']), e(p['description']),
               _facts(facts, 'pa4-dl pa4-grid'), _route(p.get('map'), 'a4p%d' % p['id'], p['name']), _track(p['steps']), note))


def _admin_part(r):
    import order_part_requests as opr
    pct = r['progress']['percent']
    nxt = r['progress'].get('next_label', '') if r['situation'] != 'cancelado' else ''
    facts = [('Estado logístico', r['fine_label'] or r['stage_label']), ('Próxima etapa', nxt), ('Situación', r['situation_label'] if r['situation'] != 'normal' else ''), ('Tipo de envío', r['shipping_label']),
             ('Referencia', r.get('reference')), ('Cantidad', str(r['quantity']) if r.get('quantity') else ''), ('Proveedor', r.get('supplier')),
             ('Solicitud (real)', _when(r['created_at'], False)), ('Disponibilidad (estimada)', _when(r['eta'], False) if r.get('eta') else ''),
             ('Recepción (real)', _when(r['received_at'], False) if r.get('received_at') else ''), ('Última actualización', _when(r['progress'].get('updated') or r['updated_at'])),
             ('Avance', '%d de %d etapas · %d\u00a0%%' % (r['progress']['done'], r['progress']['total'], pct)), ('Técnico', r.get('technician'))]
    steps = r.get('stages') or [{'label': d['label'], 'state': d['state'], 'at': d['at']} for d in r['detail']]  # las mismas etapas que el cliente
    alerts = ''
    if r.get('incident_label'):
        alerts += '<p class="pa4-alert" data-tone="alert"><b>Incidencia logística:</b> %s</p>' % e(r['incident_label'])
    if r.get('customs'):
        alerts += '<p class="pa4-alert" data-tone="info"><b>Aduana:</b> %s</p>' % e(r['customs'])
    if r.get('internal_note'):
        alerts += '<p class="pa4-alert" data-tone="info"><b>Nota interna:</b> %s</p>' % e(r['internal_note'])
    tone = opr.SITUATIONS[r['situation']][1]
    return ('<article class="pa4-part" data-tone="%s"><header><div><h3>%s</h3>%s</div><span class="pa4-chip" data-tone="%s">%s</span></header>%s%s%s%s</article>'
            % (e(tone), e(r['name']), '<small>%s</small>' % e(' · '.join(filter(None, [r.get('brand'), r.get('compatible_model')]))) if r.get('brand') or r.get('compatible_model') else '',
               e(tone), e(r['situation_label'] if r['situation'] != 'normal' else r['stage_label']), _facts(facts, 'pa4-dl pa4-grid'),
               _route(r.get('map'), 'a4i%d' % r['id'], r['name']), _track(steps), alerts))


def _notices_public(d):
    out = []
    if d['status'] in FLAGS:
        out.append(('warn', 'Aviso', FLAGS[d['status']]))
    for p in d.get('parts') or []:
        name = p['name']
        if p['situation'] != 'normal':
            out.append(('alert' if p['situation'] in ('retrasado', 'incidencia_transporte', 'cancelado') else 'warn', name, p['description']))
        elif p.get('vehicle') in ('transit', 'stopped') or (p.get('shipping') and p.get('waiting') and p.get('step_label')):
            out.append(('info', name, 'Repuesto en transporte hacia PC-DOCTOR.'))
        if p.get('eta'):
            out.append(('info', name, 'Fecha estimada de disponibilidad: %s.' % _when(p['eta'], False)))
        if p.get('received'):
            out.append(('ok', name, 'Pedido recibido en el taller el %s.' % _when(p['received'], False)))
        w = p.get('cancel_window') or {}
        if p.get('cancel_expired'):
            out.append(('muted', name, 'Plazo de solicitud de cancelación vencido (venció el %s, hora de Ecuador).' % w.get('deadline_text', '')))
        elif p.get('can_cancel'):
            out.append(('muted', name, 'La cancelación puede solicitarse desde el enlace de seguimiento hasta el %s (hora de Ecuador).' % w.get('deadline_text', '')))
    if not out:
        out.append(('ok', 'Sin avisos', 'No hay avisos pendientes para esta orden.'))
    return out


def _notices(items):
    return _sec('pa4-e', 'Observaciones y avisos', '<ul class="pa4-notes">%s</ul>' % ''.join(
        '<li data-tone="%s"><b>%s:</b> %s</li>' % (e(t), e(k), e(v)) for t, k, v in items), keep=len(items) <= 6) if items else ''


def _table(title, cols, rows, cls=''):
    """Tabla que continúa en las hojas siguientes repitiendo su encabezado; ninguna fila se parte."""
    if not rows:
        return ''
    head = ''.join('<th scope="col">%s</th>' % e(c) for c in cols)
    body = ''.join('<tr%s>%s</tr>' % (' data-state="%s"' % e(r[0]) if r[0] else '', ''.join('<td>%s</td>' % x for x in r[1:])) for r in rows)
    return '<section class="pa4-sec pa4-table %s"><h2>%s</h2><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></section>' % (cls, e(title), head, body)


def _cell(title, *lines):
    return '<b>%s</b>%s' % (e(title), ''.join('<small>%s</small>' % e(x).replace('\n', '<br>') for x in lines if x))


def _history_public(d):
    rows = []
    for p in d.get('parts') or []:
        hist = sorted(reversed(p['history']), key=lambda h: _sort_key(h['at']))  # el público llega del más reciente al más antiguo
        stage_events = [h for h in hist if h['kind'] in ('alta', 'etapa')]
        active = p['situation'] != 'cancelado' and any(s['state'] == 'current' for s in p['steps'])
        for h in hist:
            if h['kind'] in ('alta', 'etapa'):
                word = 'En curso' if active and h is stage_events[-1] else 'Completado'
            elif h['kind'] == 'situacion':
                word = 'Normalizado' if h['situation'] == 'normal' else 'Incidencia' if h['situation'] in ('retrasado', 'incidencia_transporte', 'cancelado') else 'En espera'
            elif h['kind'] == 'cancelacion':
                word = 'Registrado'
            else:
                word = 'Informado'
            rows.append((_sort_key(h['at']), 'event', e(_when(h['at'])), _cell(h['label'], p['name'], h.get('detail'), h.get('text')), e(word)))
        # Etapas sin fecha: las no registradas (superadas sin su evento) y, si el pedido sigue vigente, solo la próxima pendiente.
        for s in p['steps']:
            if s['state'] == 'skipped':
                rows.append(('~', 'skipped', '—', _cell(s['label'], p['name']), STEP_WORD['skipped']))
        nxt = next((s for s in p['steps'] if s['state'] == 'pending'), None)
        if nxt and p['situation'] != 'cancelado':
            rows.append(('~', 'pending', '—', _cell('Próxima etapa: ' + nxt['label'], p['name']), STEP_WORD['pending']))
    rows.sort(key=lambda r: r[0])
    return _table('Historial de seguimiento', ('Fecha y hora', 'Etapa', 'Estado'), [r[1:] for r in rows], 'pa4-g')


def _transport_public(d):
    rows = []
    for p in d.get('parts') or []:
        if not p.get('shipping'):
            continue
        sent = next((s['at'] for s in p['steps'] if s['code'] in ('aereo', 'traslado') and s.get('at')), '')
        rows.append(('', _cell(p['name']), e({'nacional': 'Nacional', 'internacional': 'Internacional'}[p['shipping']]), e(_when(sent, False)) or '—',
                     e(_when(p['eta'], False)) if p.get('eta') else '—', e(_when(p['received'], False)) if p.get('received') else '—'))
    return _table('Información de transporte', ('Repuesto', 'Tipo de envío', 'Despacho', 'Llegada estimada', 'Recepción en el taller'), rows, 'pa4-h')


def _technical_public(d):
    rows = [('', e(u['at']), _cell(u['label'], u['message'])) for u in sorted(d.get('updates') or [], key=lambda u: _sort_key(u['at']))]
    files = d.get('files') or []
    docs = sum(1 for f in files if f.get('mime') == 'application/pdf')
    body = _table('Información técnica · novedades del servicio', ('Fecha y hora', 'Observación autorizada'), rows, 'pa4-i')
    if files:
        body += '<p class="pa4-small">Evidencias del servicio disponibles en el enlace de seguimiento: %d fotografía(s) y %d documento(s).</p>' % (len(files) - docs, docs)
    return body


def _closing(audience):
    company = settings()
    note = ('Documento público: muestra solo el estado de la reparación, sin datos personales ni información interna.' if audience == 'public'
            else 'Documento interno con datos del cliente: no lo entregue al cliente. Para el cliente, imprima el seguimiento desde el enlace público.')
    return ('<footer class="pa4-foot"><p class="pa4-small">%s</p><p class="pa4-company"><strong>%s</strong> · %s · %s · WhatsApp: %s · %s</p></footer>'
            % (e(note), e(company['name']), e(ADDRESS), e(CITY), e(company['whatsapp']), e(SITE)))


def document(d, audience='public', qr_src='', extra=None):
    """HTML del documento A4. `d`: datos de order_tracking.lookup (público) o de staff_document (administración)."""
    assert audience in ('public', 'admin')
    body = _header(d, audience) + _equipment(d, audience, qr_src) + _progress(d)
    if audience == 'public':
        parts = ''.join(_public_part(p) for p in d.get('parts') or [])
        body += ('<section class="pa4-parts"><h2>Seguimiento de repuestos</h2>%s</section>' % parts if parts else '')
        body += _notices(_notices_public(d)) + _history_public(d) + _transport_public(d) + _technical_public(d)
    else:
        x = extra or {}
        parts = ''.join(_admin_part(r) for r in x.get('parts') or [])
        body += ('<section class="pa4-parts"><h2>Seguimiento de repuestos</h2>%s</section>' % parts if parts else '') + x.get('rest', '')
    return ('<section class="pa4" data-audience="%s" data-code="%s" aria-label="Versión para imprimir en A4">%s%s</section>'
            % (audience, e(d['code']), body, _closing(audience)))


# ---- Versión administrativa -------------------------------------------------------------------------------------------------------------

def staff_document(c, oid):
    """Datos y secciones internas de la versión administrativa. Devuelve None si la orden no existe."""
    import order_tracking
    d = order_tracking.staff_data(c, oid)
    if not d:
        return None
    row = c.execute("SELECT COALESCE(NULLIF(d.kind,''),d.category) category,d.type,d.brand,d.model,d.serial FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?", (oid,)).fetchone()
    d.update(kind=DEVICE_TYPES.get(row['category'] or row['type'], ''), brand=row['brand'] or '', model=row['model'] or '', serial=row['serial'] or '', budget=budget_label(c, oid),
             repair=__import__('repair_stages').compute(c, oid))
    names = {r[0]: r[1] for r in c.execute('SELECT id,name FROM users')}
    try:
        import order_part_requests as opr
        from reception import reception_now
        parts = opr.listing(c, oid, reception_now().date().isoformat())
    except Exception:
        parts = []
    rest = ''
    # E · Observaciones y avisos (internos).
    notes = []
    if d['status'] in FLAGS:
        notes.append(('warn', 'Aviso', FLAGS[d['status']]))
    for r in parts:
        if r['situation'] != 'normal':
            notes.append(('alert' if r['tone'] == 'rojo' else 'warn', r['name'], r['situation_label'] + ('. ' + r['incident_label'] if r.get('incident_label') else '') + '.'))
        if r.get('overdue'):
            notes.append(('alert', r['name'], 'Fecha estimada vencida sin recepción.'))
        ctx = (r.get('cancel_context') or {}).get('window') or {}
        if ctx.get('deadline_text') and r['situation'] != 'cancelado':
            notes.append(('muted', r['name'], ('Plazo de cancelación del cliente hasta el %s.' if ctx.get('open') else 'Plazo de cancelación del cliente vencido (%s).') % ctx['deadline_text']))
        for x in r.get('cancellations') or []:
            notes.append(('warn', r['name'], 'Cancelación: %s · motivo: %s · reembolso: %s.' % (x['status_label'], x['reason_label'], x['refund_label'])))
    rest += _notices(notes or [('ok', 'Sin avisos', 'No hay avisos pendientes para esta orden.')])
    # G · Historial de los repuestos (eventos internos y registro de cancelaciones y avisos).
    rows = []
    for r in parts:
        for ev in reversed(r['events']):
            if ev['kind'] == 'etapa':
                title = opr.step_label(ev.get('logistics') or ev['stage'], r['shipping'])
            elif ev['kind'] == 'situacion':
                title = 'Situación: ' + opr.SITUATIONS.get(ev['situation'], (ev['situation'],))[0]
            else:
                title = {'alta': 'Solicitud registrada', 'datos': 'Datos actualizados'}.get(ev['kind'], ev['kind'].capitalize())
            rows.append((ev['created_at'], '', e(_when(ev['created_at'])), _cell(title, r['name'], ev.get('note'), ('Mensaje al cliente: ' + ev['public_note']) if ev.get('public_note') else ''),
                         e(ev.get('actor') or 'Sistema')))
        for x in r.get('log') or []:
            rows.append((x['created_at'], '', e(_when(x['created_at'])), _cell('%s · %s' % (x['kind'].capitalize(), x['action']), r['name'], x.get('note')), e(x.get('actor') or 'Sistema')))
    rows.sort(key=lambda t: _sort_key(t[0]))
    rest += _table('Historial de seguimiento de repuestos', ('Fecha y hora', 'Etapa o evento', 'Responsable'), [t[1:] for t in rows], 'pa4-g')
    # H · Transporte (solo en la versión interna se muestran transportista, guía y país de origen).
    trows = []
    for r in parts:
        if not (r.get('shipping') or r.get('carrier') or r.get('tracking_number')):
            continue
        sent = next((x['at'] for x in r['detail'] if x['code'] == 'despachado' and x.get('at')), '')
        carrier = ' · '.join(filter(None, [r.get('carrier'), r.get('national_carrier') and 'Nacional: ' + r['national_carrier']]))
        guide = ' · '.join(filter(None, [r.get('tracking_number'), r.get('national_tracking') and 'Nacional: ' + r['national_tracking']]))
        trows.append(('', _cell(r['name']), e(r['shipping_label']), e(carrier) or '—', e(r.get('origin_country') or '') or '—', e(guide) or '—', e(_when(sent, False)) or '—',
                      e(_when(r['eta'], False)) if r.get('eta') else '—'))
    rest += _table('Información de transporte', ('Repuesto', 'Envío', 'Transportista', 'Origen', 'N.º de seguimiento', 'Despacho', 'Llegada estimada'), trows, 'pa4-h')
    # I · Información técnica interna: seguimientos (nota interna y mensaje al cliente), historial de la orden y evidencias.
    try:
        import order_followups
        follow = order_followups.listing(c, oid)['followups']
    except Exception:
        follow = []
    frows = [('', e(_when(f['created_at'])), _cell(f['kind_label'], ('Nota interna: ' + f['internal_note']) if f.get('internal_note') else '',
                                                    ('Mensaje al cliente (%s): ' % ('visible' if f.get('client_visible') else 'no visible') + f['client_message']) if f.get('client_message') else '',
                                                    ('Próxima acción: ' + f['next_action']) if f.get('next_action') else ''), e(f.get('actor') or 'Sistema'))
             for f in sorted(follow, key=lambda f: f['created_at'])]
    rest += _table('Información técnica · observaciones internas', ('Fecha y hora', 'Seguimiento', 'Responsable'), frows, 'pa4-i')
    hrows = [('', e(_when(h['occurred_at'])), _cell(HISTORY_EVENTS.get(h['event'], 'Registro'), h['status_label'], h['comment']), e(names.get(h['actor_id'], 'Sistema')))
             for h in c.execute('SELECT occurred_at,event,status_label,comment,actor_id FROM order_history WHERE order_id=? ORDER BY occurred_at,id', (oid,))]
    rest += _table('Historial de modificaciones de la orden', ('Fecha y hora', 'Evento', 'Usuario'), hrows, 'pa4-i')
    erows = [('', e(_when(x['created_at'])), _cell(x['name'], x['kind_label']), 'Sí' if x['visible'] else 'No')
             for f in sorted(follow, key=lambda f: f['created_at']) for x in [dict(y, kind_label=f['kind_label']) for y in f.get('files') or []] if not x.get('retired')]
    rest += _table('Evidencias documentadas', ('Fecha y hora', 'Archivo', 'Visible al cliente'), erows, 'pa4-i')
    return d, {'parts': parts, 'rest': rest}


HEAD = ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">'
        '<meta name="robots" content="noindex,nofollow"><title>Seguimiento A4 %s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48">'
        '<link rel="stylesheet" href="/static/ticket.css"><link rel="stylesheet" href="/static/seguimiento-a4.css"><script defer src="/static/ticket.js"></script></head>')


def staff_page(c, oid, qr_src):
    found = staff_document(c, oid)
    if not found:
        return None
    d, extra = found
    bar = ('<nav class="pa4-bar" aria-label="Acciones del documento"><button type="button" data-print>%sImprimir seguimiento A4</button><a href="/#orders?id=%d">Volver a la orden</a>'
           '<small>Vista previa de la hoja A4. En el diálogo del navegador puede elegir «Guardar como PDF».</small></nav>' % (PRINTER, d['id']))
    return HEAD % e(d['code']) + '<body class="pa4-page"><main>' + bar + document(d, 'admin', qr_src, extra) + '</main></body></html>'


PRINTER = ('<svg class="pa4-ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 9V3h12v6"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>'
           '<path d="M6 14h12v7H6z"/></svg>')
