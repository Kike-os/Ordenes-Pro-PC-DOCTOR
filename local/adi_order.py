"""ADI Premium 4.0 (1.5.265): asistencia operativa de una orden, calculada SOLO con los datos registrados en Órdenes Pro.

- Nada aquí escribe en la orden: ADI sugiere; el técnico o administración deciden y ejecutan con los flujos y permisos de siempre
  (estados, presupuestos, pagos, mensajes). Descartar una recomendación informativa no cambia ningún dato operativo.
- Cada recomendación lleva su motivo verificable (el dato y la fecha registrados) y una huella de esos datos: si se descarta, vuelve a
  aparecer solo cuando los datos cambian (no se repite sin motivo).
- Los importes salen de equipment.finance / quotes.brief (centavos enteros): ADI nunca calcula ni inventa un valor, no marca pagos, no
  afirma vencimientos que no estén registrados ni dice que un repuesto pasó aduana sin ese paso registrado.
- Sin proveedor de IA: todo lo de este módulo es determinista. La redacción con IA sigue en status_messages (datos depurados)."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta

PRIORITIES = ('alta', 'media', 'info')
PRIORITY_LABELS = {'alta': 'Requiere acción', 'media': 'Pendiente', 'info': 'Informativo'}
REMINDER_HOURS = 72  # un recordatorio de pago dentro de este plazo se informa para no duplicarlo
READY = ('pruebas', 'espera_entrega', 'listo', 'entregado')
WAITING_PARTS = ('solicitado', 'confirmado', 'preparacion', 'transito')


class AdiOrderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _fp(*values):
    return hashlib.sha256(json.dumps(values, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


def _day(value):
    """Fecha dd/mm/aaaa de un texto ISO o de segundos; '' si no hay."""
    if value in (None, ''):
        return ''
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value)).strftime('%d/%m/%Y')
        return datetime.fromisoformat(str(value)[:19]).strftime('%d/%m/%Y')
    except ValueError:
        return ''


def _when(value):
    """datetime sin zona de un texto ISO; None si no se puede leer."""
    try:
        return datetime.fromisoformat(str(value)[:19])
    except (TypeError, ValueError):
        return None


def usd(cents):
    import equipment
    return equipment.usd(int(cents or 0))


# ---- Contexto real de la orden -----------------------------------------------------------------------------------------------------------

def context(c, oid):
    """Datos registrados que ADI usa para recomendar y revisar mensajes. None si la orden no existe."""
    import equipment
    import order_part_requests as opr
    import quotes
    import repair_status
    o = c.execute("SELECT o.id,o.code,o.status,o.findings,o.problem,o.estimated_delivery,COALESCE(o.estimated_confirmed,0) confirmed,o.terms_accepted_at,"
                  "o.updated_at,o.received_at,o.created_at,o.delivered_at,cl.name client,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id "
                  "JOIN clients cl ON cl.id=d.client_id WHERE o.id=?", (oid,)).fetchone()
    if not o:
        return None
    since = c.execute('SELECT created_at FROM order_status_log WHERE order_id=? AND to_status=? ORDER BY id DESC LIMIT 1', (oid, o['status'])).fetchone()
    finance = equipment.finance(c, oid) or {}
    unit = finance.get('unit') or equipment.money(c, oid)
    main = equipment.root(c, oid)
    pending_transfers = c.execute("SELECT COUNT(*),COALESCE(SUM(t.amount_cents),0) FROM bank_transfers t JOIN order_payments p ON p.id=t.payment_id "
                                  "WHERE p.order_id IN (?,?) AND p.voided_at IS NULL AND t.status='pendiente'", (oid, main['id'] if main else oid)).fetchone()
    payments = [p for p in equipment.payments(c, oid) if not p.get('voided_at')]
    short = dict((s[0], s[2]) for s in opr.STAGES)
    parts = []
    for r in c.execute('SELECT * FROM order_part_requests WHERE order_id=? ORDER BY id', (oid,)):
        step = opr.fine(r)
        last = c.execute("SELECT MAX(created_at) FROM order_part_events WHERE request_id=? AND kind IN ('alta','etapa')", (r['id'],)).fetchone()[0] or r['created_at']
        notified = c.execute("SELECT COUNT(*) FROM order_part_notices WHERE request_id=? AND status='enviado' AND created_at>=?", (r['id'], last)).fetchone()[0]
        parts.append({'id': r['id'], 'name': r['name'], 'stage': r['stage'], 'step': step, 'step_label': opr.STEP_LABELS.get(step) or short.get(r['stage'], r['stage']),
                      'situation': r['situation'], 'situation_label': opr.SITUATIONS.get(r['situation'], ('',))[0], 'eta': r['eta'], 'shipping': r['shipping'],
                      'changed_at': last, 'notified': bool(notified)})
    sent = lambda where, args: c.execute("SELECT created_at,template,channel FROM order_messages WHERE order_id=? AND status IN ('preparado','enviado','entregado','leido') " + where
                                         + ' ORDER BY id DESC LIMIT 1', (oid,) + args).fetchone()
    last_message = sent('', ())
    last_payment_message = sent("AND template='pago'", ())
    photos = dict(c.execute("SELECT category,COUNT(*) FROM order_photos WHERE order_id=? AND deleted_at='' GROUP BY category", (oid,)).fetchall())
    diagnosis_followups = c.execute("SELECT COUNT(*) FROM order_followups WHERE order_id=? AND kind='diagnostico'", (oid,)).fetchone()[0]
    return {'id': oid, 'code': o['code'] or 'OP-%05d' % oid, 'status': o['status'], 'status_label': repair_status.LABELS.get(o['status'], o['status']),
            'status_since': since['created_at'] if since else (o['updated_at'] or ''), 'client': o['client'] or '', 'device': ' '.join(x for x in (o['brand'], o['model']) if x),
            'findings': (o['findings'] or '').strip(), 'diagnosis_followups': diagnosis_followups, 'problem': (o['problem'] or '').strip(),
            'estimated': o['estimated_delivery'] if o['confirmed'] else '', 'terms_accepted': bool(o['terms_accepted_at']), 'received_at': o['received_at'] or o['created_at'],
            'quote': quotes.brief(c, oid), 'money': unit, 'order_money': finance.get('order'), 'multiple': bool(finance.get('multiple')),
            'payments': payments, 'pending_transfers': {'count': pending_transfers[0], 'cents': pending_transfers[1]}, 'parts': parts,
            'last_message': dict(last_message) if last_message else None, 'last_payment_message': dict(last_payment_message) if last_payment_message else None,
            'photos': photos}


# ---- Recomendaciones ---------------------------------------------------------------------------------------------------------------------

def _rec(key, priority, icon, title, reason, action, target, fingerprint, button='', dismissible=None):
    return {'key': key, 'priority': priority, 'priority_label': PRIORITY_LABELS[priority], 'icon': icon, 'title': title, 'reason': reason, 'action': action,
            'target': target, 'button': button, 'fingerprint': fingerprint, 'dismissible': priority == 'info' if dismissible is None else dismissible}


def recommendations(ctx, now=None):
    """Recomendaciones de la orden según su estado REAL. Solo aparecen las que se pueden justificar con un dato registrado."""
    now = now or datetime.now()
    out, status, since = [], ctx['status'], _day(ctx['status_since'])
    quote, money, parts = ctx['quote'], ctx['money'] or {}, ctx['parts']
    delivered = status == 'entregado'
    # Diagnóstico técnico pendiente
    if status in ('pendiente', 'diagnostico') and not ctx['findings'] and not ctx['diagnosis_followups']:
        out.append(_rec('diagnostico', 'media', 'scan-search', 'Diagnóstico técnico pendiente',
                        'La orden está en «%s»%s y no tiene un diagnóstico registrado.' % (ctx['status_label'], ' desde el ' + since if since else ''),
                        'Registrar el diagnóstico en un seguimiento técnico antes de informar al cliente.', 'followups', _fp(status, since), 'Registrar seguimiento'))
    # Presupuesto
    if quote and quote['status'] == 'borrador' and not delivered:
        out.append(_rec('presupuesto_borrador', 'media', 'file-pen', 'Presupuesto en borrador sin enviar',
                        'El presupuesto %s está en borrador por %s.' % (quote['code'], usd(quote['quoted_cents'])),
                        'Revisarlo y enviarlo al cliente para su aprobación.', 'quote', _fp(quote['id'], quote['status'], quote['quoted_cents']), 'Abrir presupuesto'))
    if quote and quote['status'] in ('enviado', 'modificacion') and not delivered:
        what = 'pidió una revisión del' if quote['status'] == 'modificacion' else 'no ha aprobado el'
        out.append(_rec('presupuesto_aprobacion', 'alta', 'clipboard-list', 'Presupuesto pendiente de aprobación',
                        'El cliente %s presupuesto %s (%s)%s.' % (what, quote['code'], usd(quote['quoted_cents']), ', enviado el ' + _day(quote['sent_at']) if quote['sent_at'] else ''),
                        'Solicitar la aprobación con el diagnóstico y el valor registrado. Todavía no corresponde informar que la reparación está terminada.',
                        'quote', _fp(quote['id'], quote['status'], quote['sent_at']), 'Generar mensaje'))
    # Cliente pendiente de respuesta
    if status == 'esperando_cliente':
        out.append(_rec('respuesta_cliente', 'alta', 'message-square', 'Cliente pendiente de respuesta',
                        'La orden espera una respuesta del cliente%s.' % (' desde el ' + since if since else ''),
                        'Contactar al cliente para obtener la confirmación o la información pendiente.', 'messages', _fp(status, since), 'Generar mensaje'))
    # Repuestos
    for p in parts:
        if p['situation'] == 'cancelado':
            continue
        eta = _when(p['eta'])
        late = bool(eta and eta.date() < now.date() and p['stage'] in WAITING_PARTS)
        if p['stage'] in WAITING_PARTS:
            reason = 'Repuesto «%s»: %s%s.' % (p['name'], p['step_label'], ' · ' + p['situation_label'] if p['situation'] != 'normal' else '')
            if late:
                reason += ' La fecha estimada registrada (%s) ya pasó.' % _day(p['eta'])
            elif eta:
                reason += ' Fecha estimada registrada: %s.' % _day(p['eta'])
            out.append(_rec('repuesto_%d' % p['id'], 'alta' if late or p['situation'] in ('retrasado', 'incidencia_transporte') else 'media', 'package',
                            'Repuesto solicitado sin recepción', reason,
                            'Confirmar con el proveedor y actualizar la etapa cuando haya un avance real.', 'parts',
                            _fp(p['id'], p['step'], p['situation'], p['eta'], late), 'Ver repuesto'))
        elif p['stage'] == 'recibido':
            out.append(_rec('repuesto_instalar_%d' % p['id'], 'media', 'package-check', 'Repuesto recibido: instalación pendiente',
                            'El repuesto «%s» figura como recibido en el taller.' % p['name'], 'Registrar la instalación cuando comience.', 'parts',
                            _fp(p['id'], p['step']), 'Ver repuesto'))
        if not p['notified'] and p['stage'] != 'solicitado' and not delivered:
            out.append(_rec('repuesto_aviso_%d' % p['id'], 'info', 'send', 'Avance del repuesto sin comunicar',
                            'La etapa «%s» del repuesto «%s» no tiene un aviso enviado al cliente después del cambio.' % (p['step_label'], p['name']),
                            'Informar el avance al cliente si corresponde.', 'parts', _fp(p['id'], p['step'], p['changed_at']), 'Generar mensaje'))
    # Reparación en curso
    if status in ('reparacion', 'revision_recurrente'):
        out.append(_rec('reparacion', 'info', 'wrench', 'Reparación pendiente de finalizar',
                        'La orden está en «%s»%s.' % (ctx['status_label'], ' desde el ' + since if since else ''),
                        'Registrar las pruebas o el cierre técnico cuando terminen los trabajos.', 'followups', _fp(status, since), 'Registrar seguimiento'))
    # Pagos
    balance = money.get('balance_cents', 0)
    if balance > 0 and not delivered:
        ready = status in ('listo', 'espera_entrega')
        out.append(_rec('saldo', 'alta' if ready else 'media', 'wallet', 'Saldo pendiente de pago',
                        'Total %s · pagado %s · saldo %s.' % (usd(money['budget_cents']), usd(money['paid_cents']), usd(balance))
                        + (' El equipo está listo: la entrega requiere registrar el pago.' if ready else ''),
                        'Informar el saldo al cliente. El pago se registra solo al recibirlo, desde Pagos.', 'payments',
                        _fp(money['budget_cents'], money['paid_cents'], status in ('listo', 'espera_entrega')), 'Consultar pagos'))
    if ctx['pending_transfers']['count']:
        out.append(_rec('transferencias', 'media', 'landmark', 'Transferencias por confirmar',
                        '%d transferencia(s) o depósito(s) por %s aún sin confirmar en Caja.' % (ctx['pending_transfers']['count'], usd(ctx['pending_transfers']['cents'])),
                        'Confirmar en Caja → transferencias que el dinero llegó a la cuenta.', 'payments',
                        _fp(ctx['pending_transfers']['count'], ctx['pending_transfers']['cents']), 'Consultar pagos'))
    # Listo para entrega
    if status in ('listo', 'espera_entrega'):
        told = ctx['last_message'] and ctx['status_since'] and str(ctx['last_message']['created_at']) >= str(ctx['status_since'])
        out.append(_rec('entrega', 'media' if not told else 'info', 'package-check', 'Equipo listo para entrega',
                        'La orden está en «%s»%s%s.' % (ctx['status_label'], ' desde el ' + since if since else '',
                                                        '; ya se comunicó al cliente el ' + _day(ctx['last_message']['created_at']) if told else '; no hay un mensaje al cliente después de ese cambio'),
                        'Coordinar el retiro con el cliente' + (' y el pago del saldo.' if balance > 0 else '.'), 'messages', _fp(status, since, bool(told)), 'Generar mensaje'))
    # Documentación
    if not ctx['terms_accepted'] and not delivered:
        out.append(_rec('condiciones', 'info', 'file-check', 'Condiciones del servicio sin aceptación registrada',
                        'La orden no tiene una aceptación de las condiciones del servicio registrada.',
                        'Compartir las condiciones con el cliente. ADI no registra aceptaciones.', 'terms', _fp(ctx['terms_accepted']), 'Ver condiciones'))
    if not ctx['photos'].get('recepcion') and status in ('pendiente', 'diagnostico'):
        out.append(_rec('fotos_recepcion', 'info', 'camera', 'Sin fotos de recepción',
                        'La orden no tiene fotografías de la categoría «Recepción».',
                        'Agregar fotos del estado en que se recibió el equipo.', 'photos', _fp(sorted(ctx['photos'].items())), 'Ver fotos'))
    out.sort(key=lambda r: PRIORITIES.index(r['priority']))
    return out


def dismissed(c, oid, user_id):
    return {(r[0], r[1]) for r in c.execute('SELECT rec_key,fingerprint FROM adi_dismissals WHERE order_id=? AND user_id=?', (oid, user_id))}


def dismiss(c, oid, user, key, fingerprint, now):
    """Oculta una recomendación INFORMATIVA para este usuario mientras sus datos no cambien. No modifica la orden."""
    ctx = context(c, oid)
    if not ctx:
        raise AdiOrderError('Orden no disponible.', 404)
    found = next((r for r in recommendations(ctx, now) if r['key'] == key and r['fingerprint'] == fingerprint), None)
    if not found:
        raise AdiOrderError('La recomendación ya cambió. Actualiza el panel.', 409)
    if not found['dismissible']:
        raise AdiOrderError('Esta recomendación depende de una acción pendiente y no se puede descartar.', 400)
    c.execute('INSERT OR IGNORE INTO adi_dismissals(user_id,order_id,rec_key,fingerprint,created_at) VALUES (?,?,?,?,?)',
              (user['id'], oid, key, fingerprint, now.isoformat(timespec='seconds')))


def payments_summary(ctx):
    """Resumen de pagos con los registros reales (sin anulados): total, pagado, saldo, movimientos y transferencias por confirmar."""
    money = ctx['money'] or {}
    rows = [{'date': _day(p.get('paid_at') or p['created_at']), 'kind': p['kind'], 'amount': usd(p['amount_cents']), 'method': p.get('method_label', ''),
             'receipt': p.get('receipt', ''), 'pending': p.get('transfer_status') == 'pendiente'} for p in ctx['payments']]
    out = {'total': usd(money.get('budget_cents', 0)), 'paid': usd(money.get('paid_cents', 0)), 'balance': usd(money.get('balance_cents', 0)),
           'credit': usd(money.get('credit_cents', 0)), 'state': money.get('state', 'sin_cargos'), 'state_label': money.get('state_label', ''),
           'balance_cents': money.get('balance_cents', 0), 'movements': rows, 'pending_transfers': ctx['pending_transfers']['count'],
           'due_date': '', 'note': 'Valores registrados en Órdenes Pro. ADI no registra ni modifica pagos.'}
    if ctx['multiple'] and ctx['order_money']:
        om = ctx['order_money']
        out['order'] = {'total': usd(om['budget_cents']), 'paid': usd(om['paid_cents']), 'balance': usd(om['balance_cents'])}
    q = ctx['quote']
    if q:
        out['quote'] = {'code': q['code'], 'status': q['status_label'], 'quoted': usd(q['quoted_cents']), 'approved': usd(q['approved_cents'])}
    return out


# ---- Revisión contextual de un mensaje para el cliente --------------------------------------------------------------------------------

AMOUNT = re.compile(r'\$\s?(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)')
READY_TEXT = re.compile(r'\b(est[aá] listo|est[aá] lista|listo para (retirar|entregar|el retiro)|lista para (retirar|entregar)|(reparaci[oó]n|trabajo|servicio)\s+(ha\s+)?(finalizad|terminad|concluid)|ya (fue|est[aá]) reparad|puede (pasar a )?retirar)', re.I)
PAID_TEXT = re.compile(r'\b(no (registra|tiene) saldo|est[aá] (totalmente )?pagad|saldo (est[aá] )?(cancelado|cubierto)|pago completo)', re.I)
OVERDUE_TEXT = re.compile(r'\b(vencid[oa]s?|venci[oó]|en mora|atrasad[oa] en (el )?pago)', re.I)
PART_ARRIVED = re.compile(r'\b(repuesto|pieza|componente)\b[^.]{0,60}\b(lleg[oó]|ha llegado|recibimos|fue recibid|ya est[aá] en (el|nuestro) taller)', re.I)
CUSTOMS = re.compile(r'\b(aduana|aduanero|liberad[oa])\b', re.I)
ECUADOR = re.compile(r'\b(lleg[oó]|lleg[oó] al pa[ií]s|est[aá] en|ingres[oó] a)\s+(a\s+)?ecuador\b', re.I)
ORDER_CODE = re.compile(r'\b(PCD-\d{8}-\d{3,}(?:-E\d{2})?|OP-\d{5,})\b')
QUOTE_WORDS = re.compile(r'presupuesto|cotizaci[oó]n|aprobaci[oó]n|aprobar|autoriza', re.I)
BALANCE_WORDS = re.compile(r'saldo|pago|pendiente de pago|abono|valor pendiente', re.I)


# «Le avisaremos cuando su equipo esté listo para retirar» habla del futuro: no afirma que ya esté listo (1.5.267).
FUTURE_LEAD = re.compile(r'\b(cuando|en cuanto|apenas|una vez que|hasta que|tan pronto (como)?)\b[^.!?\n,:;]{0,40}$', re.I)


def _says_ready(text):
    return any(not FUTURE_LEAD.search(text[max(0, m.start() - 60):m.start()]) for m in READY_TEXT.finditer(text))


def _cents_of_text(raw):
    text = raw.replace(' ', '')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    elif text.count('.') == 1 and len(text.split('.')[1]) == 3:
        text = text.replace('.', '')
    try:
        return round(float(text) * 100)
    except ValueError:
        return None


def check_message(ctx, text, channel='whatsapp'):
    """Avisos (posible error) y sugerencias (falta mencionar algo) de un mensaje según los datos REALES. Como mucho 5 en total, sin repetir."""
    text = str(text or '')
    warnings, suggestions = [], []
    status, money, quote = ctx['status'], ctx['money'] or {}, ctx['quote']
    ready = status in ('listo', 'espera_entrega', 'entregado')
    if _says_ready(text) and not ready:
        warnings.append('El mensaje dice que el equipo está listo o terminado, pero la orden está en «%s».' % ctx['status_label'])
    for code in set(ORDER_CODE.findall(text)):
        if code != ctx['code'] and not code.startswith(ctx['code'] + '-'):
            warnings.append('El mensaje menciona la orden %s, pero estás escribiendo sobre la %s.' % (code, ctx['code']))
    known = {money.get('budget_cents', 0), money.get('paid_cents', 0), money.get('balance_cents', 0)}
    if quote:
        known |= {quote['quoted_cents'], quote['approved_cents'], quote['pending_cents'], quote['authorized_cents']}
    if ctx.get('order_money'):
        known |= {ctx['order_money'].get(k, 0) for k in ('budget_cents', 'paid_cents', 'balance_cents')}
    known |= {p['amount_cents'] for p in ctx['payments'] if p.get('amount_cents')}
    known.discard(0)
    for raw in AMOUNT.findall(text):
        cents = _cents_of_text(raw)
        if cents and cents not in known:
            ref = ', '.join(x for x in ('presupuesto %s' % usd(quote['quoted_cents']) if quote else '', 'saldo %s' % usd(money.get('balance_cents', 0)) if money.get('balance_cents') else '') if x)
            warnings.append('El valor $%s no coincide con ningún importe registrado de la orden%s.' % (raw, ' (' + ref + ')' if ref else ''))
            break
    if PAID_TEXT.search(text) and money.get('balance_cents', 0) > 0:
        warnings.append('El mensaje indica que no hay saldo, pero la orden registra un saldo pendiente de %s.' % usd(money['balance_cents']))
    if OVERDUE_TEXT.search(text):
        warnings.append('Órdenes Pro no tiene una fecha de vencimiento registrada para este pago: evita decir que está vencido.')
    received = any(p['stage'] in ('recibido', 'instalacion', 'instalado', 'listo') for p in ctx['parts'] if p['situation'] != 'cancelado')
    if PART_ARRIVED.search(text) and not received:
        warnings.append('El mensaje dice que el repuesto llegó, pero ningún repuesto de la orden figura como recibido.')
    steps = {p['step'] for p in ctx['parts']}
    if CUSTOMS.search(text) and not steps & {'aduana_revision', 'aduana_liberado', 'distribucion_nacional', 'ruta_otavalo', 'recibido'}:
        warnings.append('El mensaje menciona la aduana, pero no hay un paso aduanero registrado en los repuestos.')
    if ECUADOR.search(text) and not steps & {'llegada_pais', 'aduana_revision', 'aduana_liberado', 'distribucion_nacional', 'ruta_otavalo', 'recibido', 'instalacion', 'instalado', 'listo'}:
        warnings.append('El mensaje dice que el repuesto está en Ecuador, pero esa llegada no está registrada.')
    if quote and quote['status'] in ('enviado', 'modificacion') and not QUOTE_WORDS.search(text):
        suggestions.append('Hay un presupuesto pendiente de aprobación (%s, %s): conviene mencionarlo.' % (quote['code'], usd(quote['quoted_cents'])))
    if money.get('balance_cents', 0) > 0 and status in ('listo', 'espera_entrega') and not BALANCE_WORDS.search(text):
        suggestions.append('El equipo está listo con un saldo de %s: conviene indicarlo para coordinar el retiro.' % usd(money['balance_cents']))
    if status == 'esperando_cliente' and not re.search(r'\?|confirm|respuesta|indique|responda', text, re.I):
        suggestions.append('La orden espera una respuesta del cliente: indica claramente qué necesitas que confirme.')
    words = len(text.split())
    if channel == 'whatsapp' and words > 160:
        suggestions.append('Para WhatsApp, el mensaje es largo (%d palabras): resume lo esencial.' % words)
    if re.search(r'([!?¡¿])\1{1,}', text):
        suggestions.append('Evita signos repetidos («!!», «??»): mantén un tono empresarial.')
    seen, out_w, out_s = set(), [], []
    for bucket, out in ((warnings, out_w), (suggestions, out_s)):
        for item in bucket:
            if item not in seen and len(out_w) + len(out_s) < 5:
                seen.add(item)
                out.append(item)
    return {'warnings': out_w, 'suggestions': out_s, 'status_label': ctx['status_label']}


# ---- Mensajes y documentos preparados con datos reales ---------------------------------------------------------------------------------

def payment_message(c, oid, ctx, now=None):
    """Recordatorio de saldo con los valores REALES. No se envía desde aquí; avisa si ya hubo uno reciente."""
    import order_followups
    import order_tracking
    # La plantilla «Recordatorio de pago» usa el saldo de la ORDEN (con varios equipos, el de todos): los mismos valores aquí.
    money = (ctx['order_money'] if ctx['multiple'] and ctx['order_money'] else ctx['money']) or {}
    if money.get('balance_cents', 0) <= 0:
        raise AdiOrderError('Esta orden no registra saldo pendiente: no corresponde un recordatorio de pago.', 409)
    try:
        url = order_tracking.active(c, oid)['url']
    except Exception:
        url = ''
    draft = order_followups.compose(c, oid, 'pago', followup_ids=[], tracking_url=url)
    lines = draft['body'].split('\n')
    detail = ['Total de la orden: %s.' % usd(money['budget_cents'])]
    if money.get('paid_cents'):
        detail.append('Abonado: %s.' % usd(money['paid_cents']))
    at = next((i for i, line in enumerate(lines) if line.startswith('Saldo pendiente:')), None)
    if at is not None:
        lines[at:at] = detail
    warnings = list(draft['warnings'])
    last = ctx['last_payment_message']
    when = _when(last['created_at']) if last else None
    if when and (now or datetime.now()).replace(tzinfo=None) - when.replace(tzinfo=None) < timedelta(hours=REMINDER_HOURS):
        warnings.append('Ya se envió o preparó un recordatorio de pago el %s: evita duplicarlo.' % _day(last['created_at']))
    warnings.append('No menciones vencimientos: Órdenes Pro no tiene una fecha de vencimiento registrada para este saldo.')
    return {'body': '\n'.join(lines), 'subject': draft['subject'], 'template': 'pago', 'warnings': warnings,
            'values': {'total': usd(money['budget_cents']), 'paid': usd(money.get('paid_cents', 0)), 'balance': usd(money['balance_cents'])}}


def report(ctx, recs):
    """Informe interno de situación: lo registrado y lo pendiente, sin conclusiones técnicas nuevas."""
    pay = payments_summary(ctx)
    lines = ['Informe de situación · Orden %s' % ctx['code'], 'Equipo: %s' % (ctx['device'] or 'sin especificar'),
             'Estado: %s%s' % (ctx['status_label'], ' (desde el %s)' % _day(ctx['status_since']) if _day(ctx['status_since']) else ''), '']
    lines.append('Falla reportada por el cliente: ' + (ctx['problem'] or 'no registrada'))
    lines.append('Diagnóstico técnico: ' + (ctx['findings'] if ctx['findings'] else 'pendiente (no registrado)'))
    q = ctx['quote']
    lines.append('Presupuesto: ' + ('%s · %s · %s' % (q['code'], q['status_label'], usd(q['quoted_cents'])) if q else 'sin presupuesto registrado'))
    if ctx['parts']:
        lines.append('Repuestos: ' + '; '.join('%s (%s%s)' % (p['name'], p['step_label'], ', ' + p['situation_label'] if p['situation'] != 'normal' else '') for p in ctx['parts']))
    lines.append('Pagos: total %s · pagado %s · saldo %s' % (pay['total'], pay['paid'], pay['balance']))
    if ctx['estimated']:
        lines.append('Entrega estimada confirmada: ' + _day(ctx['estimated']))
    lines.append('')
    lines.append('Pendientes:' if recs else 'Pendientes: ninguno según los datos registrados.')
    for r in recs:
        lines.append('- %s: %s' % (r['title'], r['reason']))
    lines.append('')
    lines.append('Preparado por ADI con los datos registrados en Órdenes Pro. No incluye conclusiones técnicas nuevas.')
    return '\n'.join(lines)


def panel(c, oid, user, now=None):
    """Lo que muestra el panel «Adi — Asistencia inteligente»: recomendaciones vigentes (sin las descartadas), pagos y huella para sincronizar."""
    now = now or datetime.now()
    ctx = context(c, oid)
    if not ctx:
        raise AdiOrderError('Orden no disponible.', 404)
    recs = recommendations(ctx, now)
    hidden = dismissed(c, oid, user['id'])
    visible = [r for r in recs if (r['key'], r['fingerprint']) not in hidden]
    return {'code': ctx['code'], 'status': ctx['status'], 'status_label': ctx['status_label'], 'recommendations': visible,
            'dismissed': len(recs) - len(visible), 'payments': payments_summary(ctx), 'signature': _fp([(r['key'], r['fingerprint']) for r in recs]),
            'groups': [{'priority': p, 'label': PRIORITY_LABELS[p], 'count': sum(1 for r in visible if r['priority'] == p)} for p in PRIORITIES]}
