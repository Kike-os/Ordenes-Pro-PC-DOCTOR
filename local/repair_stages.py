"""Etapas visuales de la reparación (1.5.252): UNA sola fuente para el panel del taller, el seguimiento público y la hoja A4.

Seis etapas: Recepción · Diagnóstico · Reparación · Pruebas técnicas · Listo para retirar · Entregado (iconos de Lucide, ISC).
Los estados de la base no cambian (pendiente, reparacion, esperando_cliente, presupuesto, revision_recurrente, listo, espera_entrega, entregado):
se mapean a estas etapas con datos REGISTRADOS, nunca por el paso del tiempo:
- el estado de la orden fija el tramo (en espera → Recepción; en proceso → Diagnóstico a Pruebas; listo o en espera de entrega → Listo para
  retirar; entregado → todo completo);
- dentro del tramo «en proceso», la etapa la marca el último seguimiento técnico registrado (diagnóstico; reparación, novedad o repuesto;
  pruebas de funcionamiento). Sin seguimiento técnico, la orden en proceso está en Diagnóstico;
- un seguimiento que diga más de lo que permite el estado (p. ej. «servicio finalizado» con la orden aún en proceso) no adelanta nada:
  manda el estado;
- en revisión por falla recurrente, la etapa operativa vuelve a Diagnóstico (con alerta ámbar) y solo cuentan los seguimientos posteriores.
Las fechas salen de los registros (recepción, seguimientos, cambios de estado, entrega); una etapa completada sin registro propio no lleva fecha.
No se exponen notas: solo la etapa, su estado y su fecha. Solo lectura."""
import hashlib
from datetime import datetime

STAGES = (('recepcion', 'Recepción', 'clipboard-check'), ('diagnostico', 'Diagnóstico', 'scan-search'), ('reparacion', 'Reparación', 'wrench'),
          ('pruebas', 'Pruebas técnicas', 'shield-check'), ('listo', 'Listo para retirar', 'package-check'), ('entregado', 'Entregado', 'handshake'))
# Iconos SVG de Lucide (lucide.dev, licencia ISC), trazo de 24 × 24.
ICONS = {
    'clipboard-check': '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
    'scan-search': '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3"/><path d="m16 16-1.9-1.9"/>',
    'wrench': '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    'shield-check': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    'package-check': '<path d="m16 16 2 2 4-4"/><path d="M21 10V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l2-1.14"/><path d="m7.5 4.27 9 5.15"/><polyline points="3.29 7 12 12 20.71 7"/><line x1="12" x2="12" y1="22" y2="12"/>',
    'handshake': '<path d="m11 17 2 2a1 1 0 1 0 3-3"/><path d="m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 2 0 0 0 1.42.25L21 4"/><path d="m21 3 1 11h-2"/><path d="M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3"/><path d="M3 4h8"/>',
    'check': '<path d="M20 6 9 17l-5-5"/>',
    'arrow-right': '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    'rotate-ccw': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    'message-square': '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    'package': '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    'bell': '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/><path d="M3.26 15.33A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.67C19.41 13.96 18 12.5 18 8A6 6 0 0 0 6 8c0 4.5-1.41 5.96-2.74 7.33"/>',
    'plane': '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>',
    'truck': '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
    'x-circle': '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    'clipboard-list': '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'flag': '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
}
IN_PROCESS = ('reparacion', 'esperando_cliente', 'presupuesto', 'revision_recurrente', 'diagnostico', 'esperando_repuesto', 'pruebas')
# 1.5.257: etapa mínima que demuestra el propio estado (los seguimientos registrados pueden adelantarla dentro del tramo «en proceso»).
FLOOR = {'diagnostico': 1, 'presupuesto': 1, 'esperando_cliente': 1, 'revision_recurrente': 1, 'reparacion': 2, 'esperando_repuesto': 2, 'pruebas': 3}
READY = ('listo', 'espera_entrega')
# Seguimiento técnico registrado → etapa que demuestra (los de comunicación, pago o incidencia no mueven la etapa).
KIND_STAGE = {'recepcion': 0, 'diagnostico': 1, 'presupuesto_enviado': 1, 'esperando_autorizacion': 1, 'presupuesto_rechazado': 1, 'presupuesto_aprobado': 2,
              'reparacion': 2, 'novedad': 2, 'repuesto': 2, 'pruebas': 3, 'finalizado': 4, 'listo_entrega': 4, 'entrega': 5}
WORD = {'done': 'Completado', 'current': 'En curso', 'warn': 'En espera', 'pending': 'Pendiente'}
# Avisos: (tono, título, explicación, icono, etiqueta). La etiqueta es neutral: la lee también el cliente.
ALERTS = {'presupuesto': ('ambar', 'Presupuesto pendiente de aprobación', 'La reparación continuará cuando se apruebe el presupuesto.', 'clock', 'Pendiente de aprobación'),
          'esperando_cliente': ('ambar', 'Esperando respuesta del cliente', 'Necesitamos su respuesta para continuar con el servicio.', 'message-square', 'Respuesta pendiente'),
          'revision_recurrente': ('ambar', 'Revisión por falla recurrente', 'El equipo volvió a revisión técnica. El historial anterior se conserva completo.', 'rotate-ccw', 'En revisión'),
          'esperando_repuesto': ('naranja', 'Esperando repuesto', 'El servicio continuará cuando llegue el componente solicitado.', 'package', 'En espera')}


def icon(name, cls='rp-ic'):
    return ('<svg class="%s" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            'aria-hidden="true" focusable="false">%s</svg>' % (cls, ICONS[name]))


def _iso(value):
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        from reception import ECUADOR_TZ
        return datetime.fromtimestamp(value, ECUADOR_TZ).isoformat(timespec='seconds')
    return str(value)


def _second(value):
    """Momento al segundo (los seguimientos se guardan al segundo y el historial al microsegundo): compara sin falsos «antes»."""
    from datetime import timezone
    try:
        moment = datetime.fromisoformat(str(value)).replace(microsecond=0)
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


# ---- Barra única de avisos (1.5.255) ------------------------------------------------------------------------------------------------------
# Un aviso por presupuesto vigente, por estado especial y por repuesto (varios repuestos se agrupan en un solo aviso con su lista).
# Tono = color semántico; el texto siempre dice el estado. El destino abre el presupuesto o el seguimiento del repuesto (panel) o su tarjeta (cliente).
QUOTE_NOTICE = {'enviado': ('ambar', 'Presupuesto pendiente'), 'modificacion': ('ambar', 'Presupuesto en revisión'), 'aprobado': ('verde', 'Presupuesto aprobado'),
                'parcial': ('violeta', 'Aprobado parcialmente'), 'rechazado': ('rojo', 'Presupuesto rechazado')}
STATUS_NOTICE = {'esperando_cliente': ('ambar', 'message-square', 'Respuesta pendiente', 'Necesitamos su respuesta para continuar con el servicio.'),
                 'revision_recurrente': ('ambar', 'rotate-ccw', 'Falla recurrente', 'El equipo volvió a revisión técnica; el historial anterior se conserva.'),
                 'esperando_repuesto': ('naranja', 'package', 'Esperando repuesto', 'El servicio continuará cuando llegue el componente solicitado.')}
TONE_RANK = {'rojo': 0, 'naranja': 1, 'ambar': 2, 'violeta': 3, 'celeste': 4, 'azul': 5, 'verde': 6}


def part_notice(r):
    """(tono, icono, estado) de un pedido de repuesto según su paso real; None si ya terminó (instalado o listo)."""
    if r['situation'] == 'cancelado':
        return 'rojo', 'x-circle', 'Pedido cancelado'
    stage, step, ship = r['stage'], r['logistics'] or r['stage'], r['shipping'] or ''
    if stage in ('instalado', 'listo'):
        return None
    if stage == 'instalacion':
        return 'violeta', 'wrench', 'Instalación en proceso'
    if stage == 'recibido':
        return 'verde', 'package-check', 'Repuesto recibido'
    if stage == 'solicitado':
        tone, ic, text = 'azul', 'clipboard-list', 'Solicitud registrada'
    elif stage in ('confirmado', 'preparacion'):
        tone, ic, text = 'ambar', 'clock', 'Esperando despacho'
    elif step in ('llegada_pais', 'aduana_revision'):
        tone, ic, text = 'naranja', 'shield-check', 'En aduana de Ecuador'
    elif step in ('aduana_liberado', 'distribucion_nacional', 'ruta_otavalo'):
        tone, ic, text = 'azul', 'truck', 'En camino a Otavalo'
    elif ship == 'internacional' or step == 'transito_internacional':
        tone, ic, text = 'celeste', 'plane', 'En tránsito internacional'
    elif ship == 'nacional' or step in ('transito_nacional', 'despachado'):
        tone, ic, text = 'azul', 'truck', 'En tránsito nacional'
    else:
        tone, ic, text = 'azul', 'truck', 'Repuesto en camino'
    if r['situation'] in ('retrasado', 'incidencia_transporte', 'espera_proveedor', 'espera_confirmacion'):
        tone = 'naranja' if r['situation'] in ('retrasado', 'incidencia_transporte') else 'ambar'
        text += {'retrasado': ' · con retraso', 'incidencia_transporte': ' · novedad en el traslado', 'espera_proveedor': ' · en espera de disponibilidad',
                 'espera_confirmacion': ' · en espera de confirmación'}[r['situation']]
    return tone, ic, text


def notices(c, oid, status, public=False):
    """Avisos de la orden, de mayor a menor prioridad (rojo → verde). Solo datos registrados; nada se calcula por tiempo."""
    out = []
    if status != 'entregado':
        try:
            import quotes
            q = c.execute("SELECT id,code,status FROM quotes WHERE order_id=? AND deleted_at='' AND status NOT IN ('borrador','cancelado') ORDER BY version DESC,id DESC LIMIT 1", (oid,)).fetchone()
        except Exception:
            q = None
        if q and q['status'] in QUOTE_NOTICE and not (q['status'] in ('aprobado', 'parcial', 'rechazado') and status in ('listo', 'espera_entrega')):
            tone, label = QUOTE_NOTICE[q['status']]
            out.append({'kind': 'quote', 'code': q['status'], 'tone': tone, 'icon': 'clock' if tone == 'ambar' else 'clipboard-check' if tone in ('verde', 'violeta') else 'x-circle',
                        'label': label, 'detail': quotes.STATUS.get(q['status'], label) + ('' if public else ' · ' + q['code']), 'target': None if public else {'type': 'quote', 'id': q['id']}})
        if status == 'presupuesto' and not (q and q['status'] in QUOTE_NOTICE):
            out.append({'kind': 'status', 'code': status, 'tone': 'ambar', 'icon': 'clock', 'label': 'Presupuesto pendiente', 'detail': 'Aprobación de presupuesto pendiente.', 'target': None})
        if status in STATUS_NOTICE:
            tone, ic, label, detail = STATUS_NOTICE[status]
            out.append({'kind': 'status', 'code': status, 'tone': tone, 'icon': ic, 'label': label, 'detail': detail, 'target': None})
    try:
        import order_part_requests as opr
        rows = c.execute("SELECT * FROM order_part_requests WHERE order_id=?" + (" AND public_visible=1" if public else '') + " ORDER BY id", (oid,)).fetchall()
    except Exception:
        rows = []
    items = []
    for r in rows:
        found = part_notice(r)
        if not found or (status == 'entregado' and r['situation'] == 'cancelado'):
            continue
        tone, ic, text = found
        name = r['name']
        if public:
            name = opr._scrub(r['name'], opr.private_terms(c, r)) or 'Repuesto'
        items.append({'id': r['id'], 'name': name, 'tone': tone, 'icon': ic, 'label': text})
    if len(items) == 1:
        p = items[0]
        out.append({'kind': 'part', 'code': 'repuesto', 'tone': p['tone'], 'icon': p['icon'], 'label': p['label'], 'detail': p['name'], 'target': {'type': 'part', 'id': p['id']}, 'items': items})
    elif items:
        top = min(items, key=lambda p: TONE_RANK.get(p['tone'], 9))
        out.append({'kind': 'part', 'code': 'repuestos', 'tone': top['tone'], 'icon': 'package', 'label': 'Repuestos (%d)' % len(items),
                    'detail': '; '.join('%s: %s' % (p['name'], p['label']) for p in items), 'target': {'type': 'parts'}, 'items': items})
    if items:  # con repuestos a la vista, su aviso ya dice el paso real: no se repite «Esperando repuesto»
        out = [n for n in out if not (n['kind'] == 'status' and n['code'] == 'esperando_repuesto')]
    out.sort(key=lambda n: TONE_RANK.get(n['tone'], 9))
    return out


def compute(c, oid, public=False):
    """Etapas de la orden `oid` (o None si no existe). `public`: avisos solo con lo que ve el cliente."""
    o = c.execute('SELECT id,status,received_at,created_at,delivered_at,updated_at,revision FROM orders WHERE id=?', (oid,)).fetchone()
    if not o:
        return None
    labels = {r[0]: r[1] for r in c.execute('SELECT code,label FROM statuses')}
    status = o['status']
    history = [dict(r) for r in c.execute("SELECT occurred_at,event,status_label FROM order_history WHERE order_id=? ORDER BY occurred_at,id", (oid,))]
    import repair_status
    code_of = {**repair_status.LEGACY, **{v: k for k, v in labels.items()}}  # también las etiquetas anteriores a 1.5.257
    # Inicio de la última revisión por falla recurrente: lo anterior queda en el historial, pero la etapa operativa se cuenta desde ahí.
    since = ''
    if status == 'revision_recurrente':
        since = next((h['occurred_at'] for h in reversed(history) if code_of.get(h['status_label']) == 'revision_recurrente'), '')
    try:
        import order_followups
        hidden = order_followups._superseded(c, oid)
    except Exception:
        hidden = set()
    follow = [dict(r) for r in c.execute('SELECT id,kind,created_at FROM order_followups WHERE order_id=? ORDER BY id', (oid,)) if r['id'] not in hidden]
    first = {}
    evidence = 0
    for f in follow:
        stage = KIND_STAGE.get(f['kind'])
        if stage is None or (since and _second(f['created_at']) < _second(since)):
            continue
        first.setdefault(stage, f['created_at'])
        evidence = max(evidence, stage)
    # Tramo que permite el estado; dentro de él, la etapa la marca lo registrado.
    if status == 'entregado':
        current, finished = 5, True
    elif status in READY:
        current, finished = 4, False
    elif status in IN_PROCESS:
        current, finished = (1 if status == 'revision_recurrente' and not evidence else min(3, max(FLOOR.get(status, 1), evidence))), False
    else:  # pendiente (en espera)
        current, finished = 0, False
    dates = {0: _iso(o['received_at']) or _iso(o['created_at']), 5: _iso(o['delivered_at'])}
    for stage, at in first.items():
        if 1 <= stage <= 3:
            dates[stage] = at
    for h in history:
        code = code_of.get(h['status_label'])
        if code in READY and h['event'] == 'status':
            dates.setdefault(4, h['occurred_at'])
        if code == 'entregado' and not dates.get(5):
            dates[5] = h['occurred_at']
    parts_waiting = 0
    try:
        parts_waiting = c.execute("SELECT COUNT(*) FROM order_part_requests WHERE order_id=? AND situation!='cancelado' AND stage IN "
                                  "('solicitado','confirmado','preparacion','transito')", (oid,)).fetchone()[0]
    except Exception:
        pass
    warn = status in ALERTS or (parts_waiting and current in (1, 2, 3) and status in IN_PROCESS)
    out = []
    for i, (code, label, ic) in enumerate(STAGES):
        state = 'done' if finished or i < current else ('warn' if warn else 'current') if i == current else 'pending'
        at = dates.get(i, '') if state != 'pending' else ''
        out.append({'code': code, 'label': label, 'icon': ic, 'state': state, 'at': at, 'word': WORD[state]})
    alerts = []
    if status in ALERTS:
        tone, title, text, ic, tag = ALERTS[status]
        alerts.append({'code': status, 'tone': tone, 'title': title, 'text': text, 'icon': ic, 'tag': tag})
    if parts_waiting and status in IN_PROCESS and status != 'esperando_repuesto':
        alerts.append({'code': 'repuesto', 'tone': 'ambar', 'title': 'Esperando repuesto' if parts_waiting == 1 else 'Esperando %d repuestos' % parts_waiting,
                       'text': 'El avance del envío se muestra en «Seguimiento de repuestos».', 'icon': 'package', 'tag': 'En camino'})
    done = sum(1 for s in out if s['state'] == 'done')
    return {'notices': notices(c, oid, status, public), 'stages': out, 'current': None if finished else current, 'finished': finished, 'done': done, 'total': len(out),
            'percent': round(100 * done / len(out)), 'status': status, 'status_label': labels.get(status, status), 'alerts': alerts,
            'current_label': out[current]['label'] if not finished else 'Entregado', 'next_label': out[current + 1]['label'] if not finished and current < 5 else ''}


def signature(c, oid):
    """Huella de todo lo que ve el seguimiento (estado, seguimientos, repuestos, evidencias). Cambia solo si cambió algo registrado."""
    parts = [str(x) for x in c.execute("SELECT status,COALESCE(updated_at,''),COALESCE(revision,0) FROM orders WHERE id=?", (oid,)).fetchone() or ()]
    for sql in ('SELECT COUNT(*),COALESCE(MAX(id),0) FROM order_followups WHERE order_id=?', 'SELECT COUNT(*),COALESCE(MAX(updated_at),\'\') FROM order_part_requests WHERE order_id=?',
                'SELECT COUNT(*),COALESCE(MAX(id),0) FROM order_history WHERE order_id=?'):
        try:
            parts += [str(x) for x in c.execute(sql, (oid,)).fetchone()]
        except Exception:
            parts.append('-')
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]


def html(data, when=None):
    """Barra de etapas para el seguimiento público (mismo marcado que dibuja el panel con JavaScript)."""
    import html as h
    e = h.escape
    when = when or (lambda v: v)
    items = ''
    for i, s in enumerate(data['stages']):
        at = when(s['at']) if s['at'] else ''
        items += ('<li class="rp-step" data-state="%s" data-stage="%s"%s><span class="rp-node">%s<span class="rp-ok">%s</span></span>%s'
                  '<span class="rp-text"><b>%s</b><small>%s%s</small></span></li>'
                  % (s['state'], e(s['code']), ' aria-current="step"' if s['state'] in ('current', 'warn') else '', icon(s['icon']), icon('check', 'rp-ic-ok'),
                     '<span class="rp-line" aria-hidden="true"><i></i></span>' if i < len(data['stages']) - 1 else '', e(s['label']), e(s['word']),
                     '<time> · %s</time>' % e(at) if at else ''))
    return ('<div class="rp" data-current="%s" data-done="%d"><h2 class="sr-only">Avance de la reparación</h2><ol class="rp-steps" aria-label="Etapas de la reparación">%s</ol>%s%s</div>'
            % ('' if data['current'] is None else data['current'], data['done'], items, summary_html(data), notices_html(data.get('notices') or [])))


def notices_html(items, uid='rp'):
    """Barra única de avisos (cliente): una fila compacta; en el teléfono, «Avisos (N)» abre la lista. Un repuesto lleva a su tarjeta;
    varios repuestos se agrupan en un desplegable con acceso a cada uno. Sin avisos activos, no ocupa espacio."""
    import html as h
    e = h.escape
    if not items:
        return ''
    lis = ''
    for n in items:
        chip = '%s<span>%s</span>' % (icon(n['icon'], 'rp-nt-ic'), e(n['label']))
        if n['kind'] == 'part' and len(n.get('items') or []) > 1:
            sub = ''.join('<li><a class="rp-nt-sub" data-tone="%s" href="#tp-%d">%s<span><b>%s</b><small>%s</small></span></a></li>'
                          % (e(p['tone']), p['id'], icon(p['icon'], 'rp-nt-ic'), e(p['name']), e(p['label'])) for p in n['items'])
            lis += ('<li><details class="rp-nt-group"><summary class="rp-nt-item" data-tone="%s" title="%s">%s%s</summary><ul class="rp-nt-pop">%s</ul></details></li>'
                    % (e(n['tone']), e(n['detail']), chip, icon('chevron-down', 'rp-nt-chev'), sub))
        elif n.get('target') and n['target'].get('type') == 'part':
            lis += '<li><a class="rp-nt-item" data-tone="%s" href="#tp-%d" title="%s">%s</a></li>' % (e(n['tone']), n['target']['id'], e(n['detail']), chip)
        else:
            lis += '<li><span class="rp-nt-item" data-tone="%s" title="%s">%s</span></li>' % (e(n['tone']), e(n['detail']), chip)
    count = len(items)
    return ('<div class="rp-nt" data-count="%d"><button type="button" class="rp-nt-toggle" aria-expanded="false" aria-controls="%s-nt">%s<span>Avisos (%d)</span>%s</button>'
            '<span class="rp-nt-head" aria-hidden="true">%s<span>Avisos (%d)</span></span><ul class="rp-nt-list" id="%s-nt" aria-label="Avisos de la orden">%s</ul></div>'
            % (count, uid, icon('bell', 'rp-nt-ic'), count, icon('chevron-down', 'rp-nt-chev'), icon('bell', 'rp-nt-ic'), count, uid, lis))


def summary_html(data):
    """Resumen profesional bajo la barra: etapa actual (con su icono y estado), siguiente etapa y avance «X de 6»."""
    import html as h
    e = h.escape
    finished = data['finished']
    now = data['stages'][-1] if finished else data['stages'][data['current']]
    nxt = data['stages'][data['current'] + 1] if not finished and data['current'] < 5 else None
    state = 'done' if finished else now['state']
    word = 'Proceso completado' if finished else {'warn': 'En espera', 'current': 'En curso'}.get(now['state'], now['word'])
    cur = ('<div class="rp-sum-item" data-kind="now" data-state="%s"><span class="rp-sum-ic">%s</span><span class="rp-sum-txt"><small>Etapa actual</small>'
           '<b>%s</b></span><em class="rp-sum-badge">%s</em></div>' % (state, icon(now['icon']), e(now['label']), e(word)))
    nex = ('<span class="rp-sum-arrow" aria-hidden="true">%s</span><div class="rp-sum-item" data-kind="next"><span class="rp-sum-ic">%s</span><span class="rp-sum-txt">'
           '<small>Siguiente etapa</small><b>%s</b></span></div>' % (icon('arrow-right'), icon(nxt['icon']), e(nxt['label']))) if nxt else ''
    bar = ('<div class="rp-sum-meter" data-done="%d" role="img" aria-label="%d de %d etapas completadas"><span><small>Avance</small><b>%d de %d etapas</b></span>'
           '<span class="rp-sum-track"><i></i></span></div>' % (data['done'], data['done'], data['total'], data['done'], data['total']))
    return '<div class="rp-summary">%s%s%s</div>' % (cur, nex, bar)


def alerts_html(alerts):
    import html as h
    e = h.escape
    return ''.join('<div class="rp-alert" data-tone="%s" data-code="%s" role="status"><span class="rp-alert-ic">%s</span><div class="rp-alert-txt"><b>%s</b><p>%s</p></div>'
                   '<em class="rp-alert-tag">%s</em></div>' % (e(a['tone']), e(a['code']), icon(a.get('icon') or 'flag'), e(a['title']), e(a['text']), e(a.get('tag') or ''))
                   for a in alerts)
