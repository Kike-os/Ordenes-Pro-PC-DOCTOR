"""ADI Enterprise AI 3.0 · Smart Communication — fase 1 (docs/ADI-COMUNICACION.md).

1. Análisis integral de la orden: reúne en el servidor lo registrado y lo filtra antes de mostrarlo o de pasarlo a la IA. Nunca incluye
   notas internas, costos de adquisición, márgenes, contraseñas ni credenciales, y las notas de la orden no cambian estas reglas.
2. Mensajes por motivo: cada motivo solo se ofrece si los datos registrados lo justifican. El sistema escribe la base con datos reales;
   la IA solo puede mejorar la redacción de los motivos técnicos y nunca recibe importes. Los motivos de pago los escribe solo el sistema.
3. Control previo al envío: 12 comprobaciones con la orden consultada de nuevo. Un bloqueo impide continuar; el envío real sigue siendo el
   de la comunicación de la orden, que confirma destinatario y resultado.
4. Retrasos: detecta retrasos verificables y, si son atribuibles a PC-DOCTOR, lo reconoce sin culpar al cliente y permite registrar la
   incidencia en el Centro de Control para el responsable.

Nada de este módulo envía mensajes, registra pagos, cambia saldos, aplica intereses ni modifica la orden. Compromisos de pago (fase 2),
intereses en simulación (fase 3) y estados de cuenta (fase 4) aparecen como «todavía no disponible», sin inventar datos."""
import re
from datetime import date, datetime, timedelta

READY = ('listo', 'espera_entrega')
WAITING_PARTS = ('solicitado', 'confirmado', 'preparacion', 'transito')
COLLECTION = ('pago_pendiente',)           # motivos de cobranza: horario y máximo diario estrictos
FINANCIAL = ('pago_pendiente', 'confirmacion_pago', 'listo_entrega')  # pueden llevar importes
HOURS = (8, 19)                            # lunes a viernes laborables, hora de Ecuador
DUPLICATE_HOURS = 24
LATER = {
    'compromiso_pago': 'Disponible con el módulo de compromisos de pago (fase 2 de ADI 3.0).',
    'compromiso_incumplido': 'Disponible con el módulo de compromisos de pago (fase 2 de ADI 3.0).',
    'estado_cuenta': 'Disponible con los estados de cuenta (fase 4 de ADI 3.0).',
    'aviso_intereses': 'Los intereses solo se simulan: no se comunican a clientes sin validación jurídica y contable y autorización expresa.'}
GROUPS = (('servicio', 'Servicio técnico'), ('entrega', 'Entrega y posventa'), ('pagos', 'Pagos'))
PURPOSES = {
    'recepcion': ('Recepción del equipo', 'servicio'),
    'diagnostico_inicio': ('Inicio del diagnóstico', 'servicio'),
    'diagnostico_fin': ('Diagnóstico finalizado', 'servicio'),
    'presupuesto_disponible': ('Presupuesto disponible', 'servicio'),
    'presupuesto_pendiente': ('Presupuesto pendiente de aprobación', 'servicio'),
    'info_adicional': ('Solicitud de información adicional', 'servicio'),
    'repuesto_transito': ('Repuestos en tránsito', 'servicio'),
    'retraso_reparacion': ('Retraso en la reparación', 'servicio'),
    'retraso_repuesto': ('Retraso en la llegada de repuestos', 'servicio'),
    'ampliacion_plazo': ('Ampliación de plazos', 'servicio'),
    'reparacion_finalizada': ('Reparación finalizada', 'entrega'),
    'listo_entrega': ('Equipo listo para entregar', 'entrega'),
    'recordatorio_retiro': ('Recordatorio de retiro', 'entrega'),
    'garantia': ('Garantía', 'entrega'),
    'posventa': ('Atención posventa', 'entrega'),
    'pago_pendiente': ('Pago pendiente', 'pagos'),
    'confirmacion_pago': ('Confirmación de pago', 'pagos'),
    'compromiso_pago': ('Compromiso de pago', 'pagos'),
    'compromiso_incumplido': ('Compromiso incumplido', 'pagos'),
    'estado_cuenta': ('Estado de cuenta', 'pagos'),
    'aviso_intereses': ('Aviso de intereses', 'pagos')}
SENSITIVE = re.compile(r'\b(contrase[nñ]a|clave|password|pin|patr[oó]n de desbloqueo|costo de (compra|adquisici[oó]n)|margen|utilidad|precio de proveedor|nota interna)\b', re.I)
CEDULA = re.compile(r'\b\d{10}(\d{3})?\b')


class CommsError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _day(value):
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def _fmt(value):
    d = _day(value)
    return d.strftime('%d/%m/%Y') if d else ''


def _has(c, table):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _mask(number):
    return '…' + number[-2:] if number else ''


def _client(c, oid):
    return c.execute('SELECT cl.id,cl.name,COALESCE(cl.phone,\'\') phone,COALESCE(cl.email,\'\') email,o.delivered_at FROM orders o JOIN devices d ON d.id=o.device_id '
                     'JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (oid,)).fetchone()


# ---- Retrasos ------------------------------------------------------------------------------------------------------------------------------

def delays(ctx, now):
    """Retrasos verificables con lo registrado. Un retraso de la reparación es atribuible a PC-DOCTOR salvo que la orden espere al cliente."""
    today = now.date()
    out = []
    due = _day(ctx.get('estimated'))
    if due and due < today and ctx['status'] not in READY + ('entregado',):
        waiting_client = ctx['status'] in ('esperando_cliente', 'presupuesto')
        out.append({'kind': 'reparacion', 'days': (today - due).days, 'due': due.isoformat(), 'attributable': not waiting_client,
                    'detail': 'La fecha estimada confirmada (%s) ya pasó y la orden sigue en «%s».' % (due.strftime('%d/%m/%Y'), ctx['status_label']),
                    'cause': 'La orden espera una respuesta o aprobación del cliente.' if waiting_client else ''})
    for p in ctx.get('parts') or []:
        eta = _day(p.get('eta'))
        if p['stage'] in WAITING_PARTS and (p.get('situation') in ('retrasado', 'incidencia_transporte') or (eta and eta < today)):
            out.append({'kind': 'repuesto', 'part': p['name'], 'days': (today - eta).days if eta and eta < today else 0, 'due': eta.isoformat() if eta else '',
                        'attributable': True, 'detail': 'Repuesto «%s»: %s%s.' % (p['name'], p['step_label'], ' · llegada estimada %s' % eta.strftime('%d/%m/%Y') if eta else ''),
                        'cause': p.get('situation_label') or ''})
    return out


# ---- Análisis integral ---------------------------------------------------------------------------------------------------------------------

def _invoices(c, oid):
    if not _has(c, 'invoices'):
        return []
    import invoicing
    rows = c.execute("SELECT * FROM invoices WHERE order_id=? AND status NOT IN ('borrador','descartado') ORDER BY id", (oid,)).fetchall()
    return [{'number': invoicing.number(r), 'status': r['status'], 'status_label': invoicing.STATUS.get(r['status'], r['status']),
             'total': '$%s' % format(r['total_cents'] / 100, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.'),
             'environment': invoicing.ENVIRONMENTS.get(r['environment'], '')} for r in rows]


def _history(c, oid, limit=6):
    import repair_status
    return [{'at': r['created_at'], 'label': repair_status.LABELS.get(r['to_status'], r['to_status'])}
            for r in c.execute('SELECT to_status,created_at FROM order_status_log WHERE order_id=? ORDER BY id DESC LIMIT ?', (oid, limit))]


def _messages(c, oid, limit=5):
    return [dict(r) for r in c.execute("SELECT created_at,template,channel,status FROM order_messages WHERE order_id=? ORDER BY id DESC LIMIT ?", (oid, limit))]


def analysis(c, oid, now):
    """Expediente filtrado de la orden para comunicar (secciones con su fuente). Sin notas internas, costos, márgenes ni credenciales."""
    import adi_order
    import adi_reports
    import status_messages
    import whatsapp_business as wa
    ctx = adi_order.context(c, oid)
    if not ctx:
        raise CommsError('Orden no encontrada.', 404)
    tech = adi_reports.order_context(c, oid, for_client=True) or {'data': {}, 'internal_notes': 0}
    fin = status_messages.finance(c, oid, ctx)
    who = _client(c, oid)
    number = wa.number_for(who['phone'])
    consent = wa.consent_state(c, number)['state'] if number else ''
    data = tech['data']
    q = ctx['quote']
    rows = lambda *items: [{'label': k, 'value': v, 'source': s} for k, v, s in items if v not in (None, '', [])]
    sections = [
        {'key': 'cliente', 'title': 'Cliente y orden', 'rows': rows(
            ('Cliente', ctx['client'], 'Clientes'), ('Orden', ctx['code'], 'Órdenes'),
            ('WhatsApp registrado', ('Celular terminado en %s · autorización de avisos: %s' % (_mask(number), {'aceptado': 'aceptada', 'rechazado': 'rechazada'}.get(consent, 'sin registro'))) if number else 'Sin celular válido para WhatsApp', 'Clientes · WhatsApp'),
            ('Correo registrado', 'Sí' if '@' in who['email'] else 'No', 'Clientes'))},
        {'key': 'equipo', 'title': 'Equipo y servicio', 'rows': rows(
            ('Equipo', data.get('Equipo') or ctx['device'], 'Recepción'), ('Motivo de ingreso', data.get('Falla reportada por el cliente (no confirmada)'), 'Recepción'),
            ('Diagnóstico comunicable', data.get('Diagnóstico técnico registrado'), 'Diagnóstico'),
            ('Servicios del presupuesto', data.get('Presupuesto (sin importes)'), 'Presupuestos'),
            ('Trabajos y seguimientos', data.get('Seguimientos técnicos registrados'), 'Seguimientos'),
            ('Recomendaciones', data.get('Recomendaciones registradas'), 'Orden'))},
        {'key': 'estado', 'title': 'Estado y plazos', 'rows': rows(
            ('Estado actual', '%s desde %s' % (ctx['status_label'], _fmt(ctx['status_since']) or '—'), 'Órdenes'),
            ('Fecha estimada de entrega', _fmt(ctx['estimated']) or 'Sin fecha confirmada', 'Órdenes'),
            ('Historial', [('%s · %s' % (_fmt(h['at']) or '—', h['label'])) for h in _history(c, oid)], 'Historial de estados'),
            ('Repuestos', [('%s · %s%s' % (p['name'], p['step_label'], ' · llegada estimada %s' % _fmt(p['eta']) if p.get('eta') else '')) for p in ctx['parts']], 'Repuestos'),
            ('Garantía', 'Según las condiciones del documento de entrega' if ctx['status'] == 'entregado' else '', 'Entrega'))},
        {'key': 'dinero', 'title': 'Pagos (fuente única: pagos de la orden)', 'rows': rows(
            ('Valor presupuestado', status_messages.usd(q['quoted_cents']) if q else '', 'Presupuestos'),
            ('Valor aprobado', status_messages.usd(q['authorized_cents']) if q and q['authorized_cents'] else '', 'Presupuestos'),
            ('Total del servicio', fin['total'] if fin else '', 'Pagos de la orden'), ('Pagos y anticipos confirmados', fin['paid'] if fin else '', 'Caja'),
            ('Transferencias por conciliar', ('%d por %s (no son deuda confirmada ni pago confirmado)' % (fin['pending_transfers'], fin['pending'])) if fin and fin['pending_transfers'] else '', 'Caja · transferencias'),
            ('Saldo pendiente', fin['balance'] if fin else status_messages.UNVERIFIED, 'Pagos de la orden'),
            ('Facturas vinculadas', [('%s · %s · %s%s' % (i['number'], i['status_label'], i['total'], ' (autorizada no significa pagada)' if i['status'] == 'autorizado' else '')) for i in _invoices(c, oid)], 'Facturación'),
            ('Vencimientos', 'Sin fecha de vencimiento registrada', 'Pagos de la orden'),
            ('Compromisos de pago', 'Módulo de compromisos: fase 2 (todavía no disponible)', 'ADI 3.0'))},
        {'key': 'comunicacion', 'title': 'Comunicación', 'rows': rows(
            ('Mensajes anteriores', [('%s · %s · %s · %s' % (_fmt(m['created_at']) or '—', m['template'] or 'mensaje', m['channel'], m['status'])) for m in _messages(c, oid)] or 'Ninguno registrado', 'Comunicación de la orden'),
            ('Pendiente del cliente', 'Aprobar el presupuesto %s' % q['code'] if q and q['status'] == 'enviado' else 'Responder a la consulta del taller' if ctx['status'] == 'esperando_cliente' else 'Nada pendiente', 'Presupuestos · Órdenes'))}]
    found = delays(ctx, now)
    return {'order': {'id': oid, 'code': ctx['code'], 'status': ctx['status'], 'status_label': ctx['status_label']}, 'sections': sections, 'delays': found,
            'excluded': 'No incluye notas internas%s, costos de adquisición, márgenes, contraseñas ni credenciales.' % (' (%d omitidas)' % tech['internal_notes'] if tech.get('internal_notes') else ''),
            'purposes': purposes(c, oid, ctx, fin, now, found)}


# ---- Motivos ------------------------------------------------------------------------------------------------------------------------------

def _eligibility(c, oid, ctx, fin, now, found):
    st, q, parts = ctx['status'], ctx['quote'], ctx['parts']
    who = _client(c, oid)
    delivered = _day(who['delivered_at']) if who else None
    since = _day(ctx['status_since'])
    recent_pay = [p for p in ctx['payments'] if p.get('kind') in ('pago', 'asignacion') and p.get('transfer_status') != 'pendiente'
                  and _day(p['created_at']) and (now.date() - _day(p['created_at'])).days <= 7]
    late_rep = [d for d in found if d['kind'] == 'reparacion' and d['attributable']]
    late_part = [d for d in found if d['kind'] == 'repuesto']
    quote_wait = bool(q and q['status'] == 'enviado')
    return {
        'recepcion': (st in ('pendiente', 'diagnostico'), 'Solo mientras el equipo está recién recibido o en diagnóstico.'),
        'diagnostico_inicio': (st == 'diagnostico', 'La orden no está en diagnóstico.'),
        'diagnostico_fin': (bool(ctx['findings'] or ctx['diagnosis_followups']) and st not in READY + ('entregado', 'pendiente', 'diagnostico'), 'No hay un diagnóstico registrado o la orden ya está en otra etapa.'),
        'presupuesto_disponible': (quote_wait, 'No hay un presupuesto enviado esperando la decisión del cliente.'),
        'presupuesto_pendiente': (quote_wait and bool(q.get('sent_at')) and (now.date() - (_day(q['sent_at']) or now.date())).days >= 2, 'Solo con un presupuesto enviado hace al menos 2 días y sin decisión.'),
        'info_adicional': (st != 'entregado', 'La orden ya fue entregada.'),
        'repuesto_transito': (any(p['stage'] in WAITING_PARTS for p in parts), 'No hay repuestos pedidos pendientes de llegada.'),
        'retraso_reparacion': (bool(late_rep), 'No hay un retraso verificable atribuible a PC-DOCTOR (fecha estimada confirmada vencida).'),
        'retraso_repuesto': (bool(late_part), 'No hay un repuesto con la llegada estimada vencida o con retraso registrado.'),
        'ampliacion_plazo': (bool(_day(ctx['estimated']) and _day(ctx['estimated']) >= now.date()) and st not in READY + ('entregado',), 'Registra primero la nueva fecha estimada confirmada en la orden.'),
        'reparacion_finalizada': (st in READY, 'La orden no está lista.'),
        'listo_entrega': (st in READY, 'La orden no está lista para entregar.'),
        'recordatorio_retiro': (st in READY and bool(since) and (now.date() - since).days >= 3, 'Solo con el equipo listo desde hace al menos 3 días.'),
        'garantia': (st == 'entregado', 'Solo para equipos entregados.'),
        'posventa': (st == 'entregado' and bool(delivered) and (now.date() - delivered).days <= 30, 'Solo hasta 30 días después de la entrega registrada.'),
        'pago_pendiente': (bool(fin and fin['balance_cents'] > 0), 'No hay un saldo pendiente confirmado.' if fin else 'No se pudo verificar el estado financiero.'),
        'confirmacion_pago': (bool(recent_pay), 'No hay un pago confirmado en los últimos 7 días.')}


def purposes(c, oid, ctx, fin, now, found=None):
    found = delays(ctx, now) if found is None else found
    ok = _eligibility(c, oid, ctx, fin, now, found)
    out = []
    for key, (label, group) in PURPOSES.items():
        if key in LATER:
            out.append({'key': key, 'label': label, 'group': group, 'available': False, 'reason': LATER[key]})
            continue
        allowed, why = ok[key]
        out.append({'key': key, 'label': label, 'group': group, 'available': bool(allowed), 'reason': '' if allowed else why})
    return out


def _part_lines(ctx, only_late=False, found=()):
    names = {d['part'] for d in found if d['kind'] == 'repuesto'} if only_late else None
    lines = []
    for p in ctx['parts']:
        if p['stage'] not in WAITING_PARTS or (names is not None and p['name'] not in names):
            continue
        lines.append('%s: %s%s.' % (p['name'], p['step_label'].lower(), ', con llegada estimada el %s' % _fmt(p['eta']) if p.get('eta') else ''))
    return ' '.join(lines)


def base_text(c, oid, purpose, ctx, fin, now, note='', discreet=False):
    """Texto del motivo escrito por el sistema solo con datos registrados. Lanza CommsError si el motivo no corresponde."""
    import status_messages
    if purpose not in PURPOSES:
        raise CommsError('Elige un motivo válido.')
    if purpose in LATER:
        raise CommsError(LATER[purpose], 409)
    found = delays(ctx, now)
    allowed, why = _eligibility(c, oid, ctx, fin, now, found)[purpose]
    if not allowed:
        raise CommsError(why, 409)
    device = ctx['device'] or 'su equipo'
    q = ctx['quote']
    est = _fmt(ctx['estimated'])
    note = ' '.join(str(note or '').split())[:400]
    if discreet and purpose in FINANCIAL:
        return ('Tenemos información sobre la cuenta de su orden %s. Por protección de sus datos, para conocer el detalle responda a este mensaje '
                'y le pediremos verificar su identidad, o comuníquese con nuestro personal.' % ctx['code'])
    texts = {
        'recepcion': 'Confirmamos la recepción de %s en nuestro taller. Lo revisaremos según lo indicado al ingresar y le informaremos el resultado del diagnóstico.' % device,
        'diagnostico_inicio': 'Iniciamos el diagnóstico de %s. Al terminar la evaluación le informaremos el resultado y, si corresponde, el presupuesto.' % device,
        'diagnostico_fin': 'Finalizamos el diagnóstico de %s. %s' % (device, 'El presupuesto %s está disponible para su revisión.' % q['code'] if q and q['status'] == 'enviado' else 'Le explicaremos los resultados y los pasos a seguir.'),
        'presupuesto_disponible': 'El presupuesto %s para %s está disponible para su revisión y aprobación. Podemos aclarar cualquier duda antes de su decisión.' % (q['code'] if q else '', device),
        'presupuesto_pendiente': 'Le recordamos que el presupuesto %s, enviado el %s, está pendiente de su decisión. Sin su aprobación no realizamos ningún trabajo adicional.' % (q['code'] if q else '', _fmt(q.get('sent_at')) if q else ''),
        'info_adicional': 'Para continuar con el servicio de %s necesitamos un dato adicional: %s' % (device, note or '[escribe qué información se necesita]'),
        'repuesto_transito': 'Le informamos el estado del repuesto para %s. %s Le avisaremos en cuanto llegue al taller.' % (device, _part_lines(ctx)),
        'retraso_reparacion': ('Le ofrecemos una disculpa: la reparación de %s está tomando más tiempo del previsto y no se cumplió la fecha estimada que le indicamos. '
                               'Su equipo continúa en «%s». En cuanto tengamos una nueva fecha confirmada se la comunicaremos. Si lo desea, una persona de nuestro equipo '
                               'puede atenderle directamente.' % (device, ctx['status_label'])),
        'retraso_repuesto': ('Le ofrecemos una disculpa: el repuesto para %s presenta un retraso. %s Seguimos el envío con el proveedor y le avisaremos en cuanto llegue. '
                             'Si lo desea, una persona de nuestro equipo puede atenderle directamente.' % (device, _part_lines(ctx, True, found))),
        'ampliacion_plazo': 'Le informamos que la nueva fecha estimada de entrega de %s es el %s. Le avisaremos si hay cualquier novedad.' % (device, est),
        'reparacion_finalizada': 'La reparación de %s ha finalizado y el equipo está listo para retirar.' % device,
        'listo_entrega': 'Su equipo %s está listo para entregar. Puede retirarlo en nuestro horario de atención.' % device,
        'recordatorio_retiro': 'Le recordamos que su equipo %s está listo para retirar desde el %s. Le esperamos en nuestro horario de atención.' % (device, _fmt(ctx['status_since'])),
        'garantia': 'Gracias por confiar en PC-DOCTOR. El servicio de %s cuenta con la garantía indicada en su documento de entrega; si nota cualquier novedad relacionada, escríbanos.' % device,
        'posventa': 'Gracias por confiar en PC-DOCTOR. Queremos saber si %s funciona correctamente después del servicio. Si tiene alguna inquietud, con gusto le atendemos.' % device,
        'pago_pendiente': status_messages.payment_text(fin) if fin else '',
        'confirmacion_pago': 'Confirmamos el registro de su pago. %s' % ('El saldo de su orden está cubierto.' if fin and fin['balance_cents'] <= 0 else
                                                                         'Su orden registra un saldo pendiente de %s.' % fin['balance'] if fin else '')}
    text = texts[purpose].strip()
    if purpose == 'pago_pendiente' and fin and fin['pending_transfers']:
        text += (' Si ya realizó una transferencia o depósito, está en proceso de conciliación (%s) y lo confirmaremos en cuanto se verifique; '
                 'en ese caso no es necesario volver a pagar.' % fin['pending'])
    return text


def compose(c, oid, purpose, channel, note='', use_ai=True, tone='profesional', now=None):
    """Mensaje completo de un motivo para revisar y editar. Los motivos técnicos pueden pasar por la IA (sin importes); los de pago no."""
    import adi_ai
    import adi_order
    import adi_reports
    import order_followups
    import order_tracking
    import status_messages
    import whatsapp_business as wa
    from reception import reception_now
    now = now or reception_now()
    if channel not in status_messages.CHANNELS:
        raise CommsError('Elige WhatsApp o correo electrónico.')
    if tone not in status_messages.TONES:
        raise CommsError('Elige un tono válido.')
    ctx = adi_order.context(c, oid)
    if not ctx:
        raise CommsError('Orden no encontrada.', 404)
    fin = status_messages.finance(c, oid, ctx)
    if purpose in FINANCIAL and purpose != 'listo_entrega' and not fin:
        raise CommsError(status_messages.UNVERIFIED, 409)
    who = _client(c, oid)
    number = wa.number_for(who['phone'])
    discreet = channel == 'whatsapp' and purpose in ('pago_pendiente', 'confirmacion_pago') and (not number or wa.consent_state(c, number)['state'] != 'aceptado')
    body = base_text(c, oid, purpose, ctx, fin, now, note, discreet)
    source, warnings = 'sistema', []
    if discreet:
        warnings.append('Mensaje discreto: el celular no tiene la autorización de avisos registrada, así que no se incluyen importes. El detalle se da tras verificar la identidad.')
    technical = PURPOSES[purpose][1] != 'pagos' and purpose != 'info_adicional'
    if use_ai and technical and adi_ai.enabled(c) and adi_ai.provider():
        try:
            tech = adi_reports.order_context(c, oid, for_client=True)
            data = {k: v for k, v in tech['data'].items() if k in ('Equipo', 'Diagnóstico técnico registrado', 'Seguimientos técnicos registrados', 'Repuestos solicitados', 'Presupuesto (sin importes)')}
            data['Motivo de la comunicación'] = PURPOSES[purpose][0]
            data['Texto base verificado por el sistema'] = body
            task = ('Mejora la redacción del texto base para %s manteniendo su contenido y su motivo («%s»). No añadas fechas, importes, plazos, causas ni trabajos que no estén '
                    'en los datos; no menciones precios ni notas internas; no culpes al cliente de retrasos del taller. %s %s Máximo %d palabras.') % (
                status_messages.CHANNELS[channel], PURPOSES[purpose][0], status_messages.STATUS_RULES.get(ctx['status'], ''), status_messages.TONES[tone][1], status_messages.WORDS[channel])
            result = adi_ai.professional_message('', data, task=task, words=status_messages.WORDS[channel])
            claims, _ = adi_reports.unsupported('\n'.join('%s: %s' % kv for kv in data.items()), result['body'])
            if not claims and not re.search(r'\$\s?\d', result['body']):
                body, source = result['body'], 'adi'
                warnings += list(result['warnings'])
            else:
                warnings.append('ADI propuso afirmaciones no registradas; se mantuvo el texto del sistema.')
        except adi_ai.AdiError as error:
            warnings.append('ADI no pudo mejorar la redacción (%s). Se usa el texto del sistema.' % str(error).rstrip('.'))
    o = order_followups._order(c, oid)
    link = order_tracking.active(c, oid)['url']
    subject = 'PC-DOCTOR · Orden %s · %s' % (o['code'], PURPOSES[purpose][0])
    if channel == 'correo':
        full = order_followups.ai_wrap(c, oid, 'estado', body, cost=False, tracking_url=link)['body']
    else:
        lines = ['Hola, %s. Le saluda PC-DOCTOR.' % order_followups._first_name(o['client']), '', 'Orden %s%s' % (o['code'], ' · ' + ctx['device'] if ctx['device'] else ''), body, '']
        if link and not discreet:
            lines.append('Seguimiento: ' + link)
        full = '\n'.join(lines + ['PC-DOCTOR | Servicio Técnico'])
    return {'purpose': purpose, 'purpose_label': PURPOSES[purpose][0], 'channel': channel, 'subject': subject, 'body': full, 'source': source,
            'warnings': warnings, 'discreet': discreet, 'finance': fin, 'fingerprint': fin['fingerprint'] if fin else '', 'delays': delays(ctx, now)}


# ---- Control previo al envío ---------------------------------------------------------------------------------------------------------------

def _item(key, label, level, detail):
    return {'key': key, 'label': label, 'level': level, 'detail': detail}


def _collection_today(c, client_id, now):
    """Gestiones de cobranza salientes de hoy para el cliente, en cualquier canal (mensajes de pago y avisos de ADI con motivo de cobro)."""
    day = now.date().isoformat()
    sent = c.execute("SELECT COUNT(*) FROM order_messages m JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id WHERE d.client_id=? AND m.template='pago' "
                     "AND m.status IN ('preparado','enviado','entregado','leido') AND substr(m.created_at,1,10)=?", (client_id, day)).fetchone()[0]
    start = int(datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo).timestamp()) if now.tzinfo else int(datetime.combine(now.date(), datetime.min.time()).timestamp())
    prepared = c.execute("SELECT COUNT(*) FROM audit a JOIN orders o ON o.id=a.entity_id JOIN devices d ON d.id=o.device_id WHERE d.client_id=? AND a.action IN (%s) AND a.created_at>=?"
                         % ','.join("'adi_msg:%s'" % k for k in COLLECTION), (client_id, start)).fetchone()[0]
    return sent + prepared


def allowed_time(c, now):
    """(True, '') si es lunes a viernes laborable entre 08:00 y 19:00 (hora de Ecuador); si no, (False, motivo)."""
    import holidays
    if now.weekday() >= 5:
        return False, 'Hoy es fin de semana: la cobranza solo se gestiona de lunes a viernes laborables.'
    found = holidays.on(c, now.date())
    if found:
        return False, 'Hoy es feriado (%s): no se gestiona cobranza.' % found.get('label', 'feriado')
    if not HOURS[0] <= now.hour < HOURS[1]:
        return False, 'Fuera del horario permitido (08:00 a 19:00, hora de Ecuador).'
    return True, ''


def precheck(c, oid, purpose, channel, text, fingerprint_value, now):
    """Las 12 comprobaciones previas con la orden consultada de nuevo. level: ok | warn | block. ok=True si nada bloquea."""
    import adi_order
    import status_messages
    import whatsapp_business as wa
    if purpose not in PURPOSES:
        raise CommsError('Elige un motivo válido.')
    if channel not in status_messages.CHANNELS:
        raise CommsError('Elige WhatsApp o correo electrónico.')
    text = str(text or '')
    ctx = adi_order.context(c, oid)                                                                                     # 1
    if not ctx:
        raise CommsError('Orden no encontrada.', 404)
    fin = status_messages.finance(c, oid, ctx)
    who = _client(c, oid)
    number = wa.number_for(who['phone'])
    items = [_item('orden', 'Orden consultada de nuevo', 'ok', '%s · %s.' % (ctx['code'], ctx['status_label']))]
    if channel == 'whatsapp':                                                                                            # 2 y 3
        items.append(_item('destinatario', 'Destinatario registrado', 'ok' if number else 'block',
                           'Celular del titular terminado en %s.' % _mask(number) if number else 'El cliente no tiene un celular válido para WhatsApp.'))
    else:
        mail_ok = bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', who['email'].strip()))
        items.append(_item('destinatario', 'Destinatario registrado', 'ok' if mail_ok else 'block', 'Correo del titular registrado.' if mail_ok else 'El cliente no tiene un correo válido.'))
    items.append(_item('titular', 'El destinatario corresponde a la orden', 'ok', 'Se usa solo el contacto del titular de esta orden (nunca familiares ni terceros).'))
    elig = dict((p['key'], p) for p in purposes(c, oid, ctx, fin, now))[purpose]                                        # 4
    items.append(_item('estado', 'Estado actualizado', 'ok' if elig['available'] else 'block',
                       'El motivo «%s» corresponde al estado «%s».' % (PURPOSES[purpose][0], ctx['status_label']) if elig['available'] else elig['reason']))
    check = status_messages.verify(c, oid, fingerprint_value, text)                                                     # 5
    amounts = bool(re.search(r'\$\s?\d', text))
    if purpose in FINANCIAL or amounts:
        items.append(_item('valores', 'Valores económicos confirmados', 'ok' if check['ok'] else 'block', 'Coinciden con los pagos registrados.' if check['ok'] else ' '.join(check['problems'])))
    else:
        items.append(_item('valores', 'Valores económicos confirmados', 'ok', 'El mensaje no menciona importes.'))
    pending = fin['pending_transfers'] if fin else 0                                                                     # 6
    clarified = bool(re.search(r'concilia|por confirmar|en verificaci', text, re.I))
    if pending and (purpose == 'pago_pendiente' or re.search(r'saldo pendiente', text, re.I)) and not clarified:
        items.append(_item('pagos', 'Pagos recientes', 'block', 'Hay %d transferencia(s) por conciliar: el mensaje no puede afirmar la deuda sin aclararlo.' % pending))
    else:
        items.append(_item('pagos', 'Pagos recientes', 'warn' if pending else 'ok', 'Hay transferencias por conciliar; el mensaje lo aclara.' if pending else 'Sin transferencias por conciliar.'))
    since = int((now - timedelta(hours=DUPLICATE_HOURS)).timestamp())                                                    # 7
    dup = c.execute('SELECT COUNT(*) FROM audit WHERE action=? AND entity_id=? AND created_at>=?', ('adi_msg:' + purpose, oid, since)).fetchone()[0]
    items.append(_item('duplicado', 'Sin notificación duplicada', 'block' if dup else 'ok',
                       'Ya se preparó un mensaje con este motivo en las últimas %d horas.' % DUPLICATE_HOURS if dup else 'No hay otro mensaje con este motivo en las últimas %d horas.' % DUPLICATE_HOURS))
    leaks = []                                                                                                           # 8
    if SENSITIVE.search(text):
        leaks.append('menciona datos internos o credenciales («%s»)' % SENSITIVE.search(text).group(0))
    if CEDULA.search(text):
        leaks.append('incluye un número de identificación')
    consent = wa.consent_state(c, number)['state'] if number else ''
    if channel == 'whatsapp' and amounts and consent != 'aceptado':
        leaks.append('muestra importes a un celular sin autorización de avisos registrada (usa el mensaje discreto)')
    items.append(_item('privacidad', 'Privacidad', 'block' if leaks else 'ok', ('El mensaje ' + '; '.join(leaks) + '.') if leaks else 'Sin datos internos, credenciales ni identificaciones.'))
    in_time, why_time = allowed_time(c, now)                                                                             # 9
    if purpose in COLLECTION:
        items.append(_item('horario', 'Horario permitido', 'ok' if in_time else 'block', 'Lunes a viernes laborable, 08:00 a 19:00.' if in_time else why_time))
    else:
        items.append(_item('horario', 'Horario permitido', 'ok' if in_time else 'warn', 'Dentro del horario de atención.' if in_time else why_time.replace('la cobranza solo se gestiona', 'conviene escribir') + ' Considera enviarlo en horario laborable.'))
    if channel == 'whatsapp':                                                                                            # 10
        if not wa.ready():
            items.append(_item('whatsapp', 'Condiciones de WhatsApp Business', 'block', 'WhatsApp Business no está configurado en el servidor.'))
        else:
            window = number and _has(c, 'whatsapp_adi_inbound') and c.execute('SELECT 1 FROM whatsapp_adi_inbound WHERE sender=? AND received_at>=? LIMIT 1',
                                                                              (number, (now - timedelta(hours=24)).isoformat(timespec='seconds'))).fetchone()
            items.append(_item('whatsapp', 'Condiciones de WhatsApp Business', 'ok' if window else 'warn',
                               'El cliente escribió en las últimas 24 horas: se puede responder con texto libre.' if window else
                               'Fuera de la ventana de 24 horas de Meta: el envío necesita una plantilla aprobada; si Meta lo rechaza, queda registrado y se deriva a revisión.'))
    else:
        items.append(_item('whatsapp', 'Condiciones del canal', 'ok', 'Correo electrónico: se envía desde la comunicación de la orden.'))
    if channel == 'whatsapp':                                                                                            # 11
        level = 'block' if consent == 'rechazado' else 'ok' if consent == 'aceptado' else 'warn'
        detail = {'rechazado': 'El cliente pidió no recibir avisos por WhatsApp.', 'aceptado': 'Autorización de avisos por WhatsApp registrada.'}.get(consent, 'Sin autorización de avisos registrada: solo un mensaje discreto o una respuesta a su consulta.')
    else:
        level, detail = 'ok', 'Comunicación del servicio contratado.'
    if purpose in COLLECTION and _collection_today(c, who['id'], now):
        level, detail = 'block', 'Ya hubo una gestión de cobranza hoy con este cliente (máximo una al día entre todos los canales).'
    items.append(_item('consentimiento', 'Permisos y consentimiento', level, detail))
    items.append(_item('motivo', 'Motivo registrado', 'ok', 'Al continuar se registra el motivo «%s» en la auditoría.' % PURPOSES[purpose][0]))  # 12
    return {'ok': not any(i['level'] == 'block' for i in items), 'items': items, 'finance': fin}


def record(c, oid, purpose, user_id, audit):
    """Registra el motivo al continuar al envío (no envía nada)."""
    if purpose not in PURPOSES:
        raise CommsError('Elige un motivo válido.')
    audit(c, user_id, 'adi_msg:' + purpose, oid)


def register_delay(c, oid, user, now, audit):
    """Incidencia de retraso atribuible a PC-DOCTOR: nota en el Centro de Control para el responsable de la orden y auditoría."""
    import adi_order
    ctx = adi_order.context(c, oid)
    if not ctx:
        raise CommsError('Orden no encontrada.', 404)
    found = [d for d in delays(ctx, now) if d['attributable']]
    if not found:
        raise CommsError('No hay un retraso verificable atribuible a PC-DOCTOR en esta orden.', 409)
    body = 'Incidencia de retraso (ADI): ' + ' '.join(d['detail'] for d in found) + ' Revisar la causa, confirmar una nueva fecha y ofrecer atención humana al cliente.'
    noted = False
    if _has(c, 'pending_notes'):
        key = 'pending:orders:%d:%s' % (oid, ctx['status'])
        if not c.execute("SELECT 1 FROM pending_notes WHERE key=? AND kind='nota' AND body=? AND substr(created_at,1,10)=?", (key, body[:2000], now.date().isoformat())).fetchone():
            c.execute("INSERT INTO pending_notes(key,module,kind,body,until,user_id,created_at) VALUES (?,?,?,?,?,?,?)",
                      (key, 'orders', 'nota', body[:2000], '', user['id'], now.isoformat(timespec='seconds')))
        noted = True
    audit(c, user['id'], 'adi_delay_incident', oid)
    return {'ok': True, 'noted': noted, 'detail': body}
