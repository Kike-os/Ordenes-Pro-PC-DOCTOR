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
}
IN_PROCESS = ('reparacion', 'esperando_cliente', 'presupuesto', 'revision_recurrente', 'diagnostico')
READY = ('listo', 'espera_entrega')
# Seguimiento técnico registrado → etapa que demuestra (los de comunicación, pago o incidencia no mueven la etapa).
KIND_STAGE = {'recepcion': 0, 'diagnostico': 1, 'presupuesto_enviado': 1, 'esperando_autorizacion': 1, 'presupuesto_rechazado': 1, 'presupuesto_aprobado': 2,
              'reparacion': 2, 'novedad': 2, 'repuesto': 2, 'pruebas': 3, 'finalizado': 4, 'listo_entrega': 4, 'entrega': 5}
WORD = {'done': 'Completado', 'current': 'En curso', 'warn': 'En espera', 'pending': 'Pendiente'}
ALERTS = {'presupuesto': ('ambar', 'Presupuesto pendiente de aprobación', 'La reparación continúa cuando se apruebe el presupuesto.'),
          'esperando_cliente': ('ambar', 'Esperando respuesta del cliente', 'Necesitamos su respuesta para continuar.'),
          'revision_recurrente': ('ambar', 'Revisión por falla recurrente', 'El equipo volvió a revisión técnica; el historial anterior se conserva.')}


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


def compute(c, oid):
    """Etapas de la orden `oid` (o None si no existe)."""
    o = c.execute('SELECT id,status,received_at,created_at,delivered_at,updated_at,revision FROM orders WHERE id=?', (oid,)).fetchone()
    if not o:
        return None
    labels = {r[0]: r[1] for r in c.execute('SELECT code,label FROM statuses')}
    status = o['status']
    history = [dict(r) for r in c.execute("SELECT occurred_at,event,status_label FROM order_history WHERE order_id=? ORDER BY occurred_at,id", (oid,))]
    code_of = {v: k for k, v in labels.items()}
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
        current, finished = (1 if status == 'revision_recurrente' and not evidence else min(3, max(1, evidence))), False
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
        tone, title, text = ALERTS[status]
        alerts.append({'code': status, 'tone': tone, 'title': title, 'text': text})
    if parts_waiting and status in IN_PROCESS:
        alerts.append({'code': 'repuesto', 'tone': 'ambar', 'title': 'Esperando repuesto' if parts_waiting == 1 else 'Esperando %d repuestos' % parts_waiting,
                       'text': 'Puede ver el avance en «Seguimiento de repuestos».'})
    done = sum(1 for s in out if s['state'] == 'done')
    return {'stages': out, 'current': None if finished else current, 'finished': finished, 'done': done, 'total': len(out),
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
    now = data['stages'][data['current']] if data['current'] is not None else data['stages'][-1]
    alerts = ''.join('<p class="rp-alert" data-tone="%s" role="status"><b>%s.</b> %s</p>' % (e(a['tone']), e(a['title']), e(a['text'])) for a in data['alerts'])
    return ('<div class="rp" data-current="%s" data-done="%d"><h2 class="sr-only">Avance de la reparación</h2><ol class="rp-steps" aria-label="Etapas de la reparación">%s</ol>'
            '<p class="rp-now"><span>Etapa actual:</span> <b>%s</b>%s</p>%s</div>'
            % ('' if data['current'] is None else data['current'], data['done'], items, e(now['label'] if not data['finished'] else 'Entregado'),
               ' · <span>siguiente: %s</span>' % e(data['next_label']) if data['next_label'] else '', alerts))
