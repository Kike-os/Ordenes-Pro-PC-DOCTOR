"""Mensajes de seguimiento para el cliente según el estado real de la orden (1.5.257), para WhatsApp o correo.

- ADI redacta el cuerpo con los datos técnicos registrados de la orden, ya depurados (sin nombre ni contacto del cliente, serie, precios ni
  credenciales: adi_reports.order_context). Debe distinguir lo confirmado de una posibilidad técnica y no inventar diagnósticos, trabajos,
  presupuestos ni fechas; los controles de adi_ai (_guard, repeticiones) avisan lo que no está respaldado.
- Sin ADI (desactivado, sin proveedor o con error), el cuerpo es la explicación del estado: nunca un texto inventado.
- Saludo con el nombre real, orden, equipo, enlace de seguimiento y firma los pone el sistema. Nada se envía desde aquí: el técnico revisa
  y edita el mensaje antes de enviarlo por la comunicación de la orden.

ADI Smart Follow-Up 4.0 (1.5.267):
- Estado financiero confirmado con los registros existentes (equipment.finance a través de adi_order.context; con varios equipos, el de la
  orden). Nada se calcula a partir del texto ni se crea un cálculo paralelo; si no se puede verificar, el mensaje no habla de dinero.
- El párrafo del saldo lo escribe el sistema con el importe exacto (la IA no ve importes). Solo con saldo pendiente confirmado; con
  transferencias por confirmar no se incluye por defecto.
- Las notas internas de los seguimientos no viajan a la IA; se avisa cuántas quedaron fuera.
- Revisión del contexto: datos esenciales que faltan y contradicciones entre lo registrado y el estado.
- Huella financiera: antes de enviar se comprueba que el saldo no cambió desde que se generó el texto."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta

import repair_status

CHANNELS = {'whatsapp': 'WhatsApp', 'correo': 'Correo electrónico'}
WORDS = {'whatsapp': 70, 'correo': 110}
TONES = {'profesional': ('Profesional', 'Tono profesional, cordial y claro.'),
         'formal': ('Formal', 'Tono formal y protocolario, con trato de usted.'),
         'cercano': ('Cercano', 'Tono cercano y amable, con trato de usted y sin perder la formalidad.')}
NEXT = {'pendiente': 'Le informaremos cuando comience el diagnóstico.', 'diagnostico': 'Al terminar la evaluación le informaremos el resultado.',
        'reparacion': 'Le notificaremos cuando su equipo esté listo para retirar.', 'pruebas': 'Le avisaremos en cuanto el equipo esté listo para retirar.',
        'esperando_repuesto': 'Le informaremos cuando llegue el repuesto.', 'revision_recurrente': 'Le informaremos el resultado de la revisión.'}
# Lo que el estado real permite decir: la IA lo recibe como regla, además de la explicación pública del estado.
STATUS_RULES = {
    'pendiente': 'El equipo aún no inicia el diagnóstico: no menciones fallas confirmadas ni trabajos.',
    'diagnostico': 'El diagnóstico está en curso: no presentes como confirmada ninguna causa que no figure en el diagnóstico registrado.',
    'presupuesto': 'El presupuesto espera la aprobación del cliente: ningún trabajo del presupuesto se ha realizado todavía.',
    'esperando_cliente': 'Se espera una respuesta del cliente: no digas que el trabajo continúa.',
    'esperando_repuesto': 'Se espera un repuesto: no digas que llegó ni que se instaló salvo que conste en los datos.',
    'reparacion': 'La reparación está en proceso: no digas que terminó ni que el equipo está listo.',
    'pruebas': 'El equipo está en pruebas técnicas: no digas que está listo, terminado ni reparado por completo.',
    'revision_recurrente': 'Es una nueva revisión por una falla que se repite: no prometas resultados.',
    'espera_entrega': 'El equipo está listo y espera su entrega.', 'listo': 'El equipo está listo para retirar.',
    'entregado': 'El equipo ya fue entregado al cliente.'}
READY = ('listo', 'espera_entrega')
LATE_STAGES = ('reparacion', 'pruebas', 'espera_entrega', 'listo', 'entregado')
REMINDER_HOURS = 72
UNVERIFIED = 'No se pudo verificar el estado financiero de esta orden.'


class MessageError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def usd(cents):
    import equipment
    return equipment.usd(cents)


def _today():
    from reception import reception_now
    return reception_now().date()


def _date_usable(info, today=None):
    """Una fecha estimada se comunica solo si está registrada, no pasó y el equipo todavía no está listo ni entregado."""
    if not info.get('estimated') or info['code'] in READY + ('entregado',):
        return False
    try:
        return date.fromisoformat(info['estimated']) >= (today or _today())
    except ValueError:
        return False


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return str(value)


def base_body(c, oid, include_date=True):
    """Cuerpo sin IA: la explicación pública del estado actual (y la acción que se espera del cliente, si la hay)."""
    info = repair_status.public(c, oid)
    if not info:
        raise MessageError('Orden no disponible.', 404)
    parts = ['Estado actual: %s.' % info['label'], info['text']]
    if info['action']:
        parts.append(info['action'])
    if include_date and _date_usable(info):
        parts.append('Fecha estimada de entrega: %s.' % _day(info['estimated']))
    return info, ' '.join(parts)


# ---- Estado financiero confirmado -----------------------------------------------------------------------------------------------------

def finance(c, oid, ctx=None):
    """Estado financiero de los registros existentes (sin cálculos propios). None si no se pudo verificar."""
    try:
        import adi_order
        ctx = ctx or adi_order.context(c, oid)
        if not ctx:
            return None
        scope_order = bool(ctx['multiple'] and ctx['order_money'])
        money = ctx['order_money'] if scope_order else ctx['money']
        if not money or not all(k in money for k in ('budget_cents', 'paid_cents', 'balance_cents', 'credit_cents', 'state')):
            return None
        pending = ctx['pending_transfers']
        q = ctx['quote']
        out = {'budget_cents': money['budget_cents'], 'paid_cents': money['paid_cents'], 'balance_cents': money['balance_cents'],
               'credit_cents': money['credit_cents'], 'state': money['state'], 'state_label': money.get('state_label', ''),
               'total': usd(money['budget_cents']), 'paid': usd(money['paid_cents']), 'balance': usd(money['balance_cents']), 'credit': usd(money['credit_cents']),
               'scope': 'orden' if scope_order else 'equipo', 'payments': sum(1 for p in ctx['payments'] if p.get('kind') in ('pago', 'asignacion')),
               'pending_transfers': pending['count'], 'pending_cents': pending['cents'], 'pending': usd(pending['cents']),
               'quote': {'code': q['code'], 'status_label': q['status_label'], 'authorized': usd(q['authorized_cents'])} if q else None,
               'delivered': ctx['status'] == 'entregado'}
        out['fingerprint'] = fingerprint(out)
        return out
    except Exception as error:  # el mensaje se puede preparar igual, pero sin afirmar nada sobre pagos
        print('status-message-finance', type(error).__name__, flush=True)
        return None


def fingerprint(fin):
    """Huella de los valores que el mensaje puede afirmar: si cambia, el texto generado antes ya no es fiable."""
    if not fin:
        return ''
    keys = ('budget_cents', 'paid_cents', 'balance_cents', 'credit_cents', 'state', 'pending_transfers', 'pending_cents')
    return hashlib.sha256(json.dumps([fin[k] for k in keys]).encode()).hexdigest()[:16]


def payment_default(fin):
    """Se incluye por defecto solo un saldo pendiente confirmado: sin transferencias por confirmar que puedan cambiarlo."""
    return bool(fin and fin['balance_cents'] > 0 and not fin['pending_transfers'])


def payment_text(fin):
    """Párrafo del saldo, con el importe exacto de los registros. Vacío si no hay saldo pendiente."""
    if not fin or fin['balance_cents'] <= 0:
        return ''
    if fin['paid_cents'] > 0:
        lead = 'Adicionalmente, le informamos que, considerando los abonos registrados por %s, su orden registra un saldo pendiente de %s.' % (fin['paid'], fin['balance'])
    else:
        lead = 'Adicionalmente, le informamos que su orden registra un saldo pendiente de %s.' % fin['balance']
    tail = ('Agradecemos su colaboración para completar el pago correspondiente.' if fin['delivered']
            else 'Agradecemos su colaboración para completar el pago correspondiente antes del retiro de su equipo.')
    return lead + ' ' + tail


def finance_notes(fin, include_payment):
    """Avisos internos sobre el dinero: nunca forman parte del mensaje."""
    if not fin:
        return [{'level': 'warn', 'text': UNVERIFIED + ' El mensaje no menciona pagos ni saldos.'}]
    notes = []
    many = fin['pending_transfers'] > 1
    if fin['pending_transfers']:
        notes.append({'level': 'warn', 'text': 'Hay %d transferencia%s por confirmar en Caja por %s: el saldo puede cambiar. Confírmala%s antes de informar el pago.'
                      % (fin['pending_transfers'], 's' if many else '', fin['pending'], 's' if many else '')})
    state = fin['state']
    if state == 'credito':
        notes.append({'level': 'info', 'text': 'La orden registra un saldo a favor del cliente de %s: el mensaje no menciona cobros.' % fin['credit']})
    elif state == 'pagado':
        notes.append({'level': 'info', 'text': 'Orden sin saldo pendiente: el mensaje no menciona cobros.'})
    elif state == 'sin_cargos':
        notes.append({'level': 'info', 'text': 'Todavía no hay cargos registrados en la orden: el mensaje no menciona valores.'})
    elif fin['balance_cents'] > 0 and not include_payment:
        notes.append({'level': 'info', 'text': 'Saldo pendiente de %s sin incluir en el mensaje.' % fin['balance']})
    if fin['scope'] == 'orden' and fin['balance_cents'] > 0:
        notes.append({'level': 'info', 'text': 'La orden tiene varios equipos: el saldo indicado es el de toda la orden.'})
    return notes


# ---- Revisión del contexto ------------------------------------------------------------------------------------------------------------

def review(c, oid, ctx, info, internal_notes, include_date):
    """Datos esenciales que faltan y contradicciones entre lo registrado y el estado (avisos para el operador)."""
    out = []
    status = ctx['status']
    if status in LATE_STAGES and not ctx['findings'] and not ctx['diagnosis_followups']:
        out.append({'level': 'warn', 'text': 'Falta el diagnóstico técnico registrado: el mensaje no puede explicar la falla encontrada.'})
    if status in READY:
        pending_parts = [p['name'] for p in ctx['parts'] if p['situation'] != 'cancelado' and p['stage'] not in ('instalado', 'listo')]
        if pending_parts:
            out.append({'level': 'warn', 'text': 'La orden figura lista, pero hay repuestos sin instalar: %s. Revisa el estado antes de enviar.' % ', '.join(pending_parts[:3])})
        q = ctx['quote']
        if q:
            open_items = [r['description'] for r in c.execute("SELECT description,execution FROM quote_items WHERE quote_id=? AND status='aprobado'", (q['id'],))
                          if r['execution'] != 'realizado']
            if open_items:
                out.append({'level': 'warn', 'text': 'La orden figura lista, pero hay trabajos aprobados sin marcar como realizados: %s.' % ', '.join(open_items[:3])})
    if status == 'esperando_repuesto' and not any(p['situation'] != 'cancelado' for p in ctx['parts']):
        out.append({'level': 'warn', 'text': 'La orden espera un repuesto, pero no hay ninguno registrado en Repuestos.'})
    last = c.execute('SELECT kind FROM order_followups WHERE order_id=? ORDER BY id DESC LIMIT 1', (oid,)).fetchone()
    if last and last['kind'] in ('finalizado', 'listo_entrega') and status not in READY + ('entregado',):
        out.append({'level': 'warn', 'text': 'El último seguimiento indica que el servicio terminó, pero la orden sigue en «%s». Actualiza el estado o revisa el mensaje.' % info['label']})
    if info.get('estimated') and include_date and not _date_usable(info) and status not in READY + ('entregado',):
        out.append({'level': 'info', 'text': 'La fecha estimada registrada (%s) ya pasó: no se incluye en el mensaje.' % _day(info['estimated'])})
    if internal_notes:
        out.append({'level': 'info', 'text': '%s del taller no se usó en el mensaje: es información solo para el equipo técnico.'
                    % ('1 nota interna' if internal_notes == 1 else '%d notas internas' % internal_notes)})
    return out


def _recent(ctx, key, hours, now):
    row = (ctx or {}).get(key)
    if not row:
        return ''
    try:
        when = datetime.fromisoformat(str(row['created_at']))
    except ValueError:
        return ''
    return _day(row['created_at']) if now.replace(tzinfo=None) - when.replace(tzinfo=None) < timedelta(hours=hours) else ''


# ---- Redacción -------------------------------------------------------------------------------------------------------------------------

def _adi(c, oid, channel, info, note, tone, include_progress, include_date):
    """Cuerpo redactado por ADI con el contexto técnico depurado. Devuelve (cuerpo, avisos, notas internas omitidas) o lanza adi_ai.AdiError."""
    import adi_ai
    import adi_reports
    ctx = adi_reports.order_context(c, oid, for_client=True)
    keep = ('Equipo', 'Falla reportada por el cliente (no confirmada)')
    data = dict(ctx['data']) if include_progress else {k: v for k, v in ctx['data'].items() if k in keep}
    data['Estado actual de la orden'] = info['label']
    data['Explicación del estado para el cliente'] = info['text']
    if include_date and _date_usable(info):
        data['Fecha estimada confirmada'] = info['estimated']
    task = ('Mensaje de seguimiento para %s. Explica el estado actual y lo que sigue, adaptado al tipo de equipo y al trabajo registrado. '
            'Distingue lo confirmado (diagnóstico registrado) de lo que solo es una posibilidad técnica («podría», «es posible»). '
            'Un trabajo solo figura como realizado si consta como realizado en los datos. %s No menciones precios, pagos, proveedores ni notas internas. '
            'No prometas fechas que no estén en los datos. %s Máximo %d palabras.') % (CHANNELS[channel], STATUS_RULES.get(info['code'], ''), TONES[tone][1], WORDS[channel])
    clean_note = adi_ai.redact(note, ctx['names']) if note else ''
    result = adi_ai.professional_message(clean_note, data, task=task, words=WORDS[channel])
    warnings = list(result['warnings'])
    claims, _specs = adi_reports.unsupported('\n'.join('%s: %s' % kv for kv in data.items()) + '\n' + clean_note, result['body'])
    if claims:
        warnings.append('Estas afirmaciones no constan como realizadas o comprobadas: %s. Confírmalas o cámbialas.' % ', '.join(claims))
    return result['body'], warnings, ctx.get('internal_notes', 0)


def _internal_count(c, oid):
    try:
        import adi_reports
        return adi_reports.order_context(c, oid, for_client=True).get('internal_notes', 0)
    except Exception:
        return 0


def compose(c, oid, channel, note='', use_ai=True, options=None, now=None):
    """Mensaje completo para revisar y editar. Devuelve canal, asunto, cuerpo, origen ('adi' o 'plantilla'), avisos, estado financiero
    confirmado (con su huella) y la revisión del contexto. options: payment (None = regla por defecto), progress, date y tone."""
    import adi_ai
    import adi_order
    import order_followups
    import order_tracking
    from reception import reception_now
    if channel not in CHANNELS:
        raise MessageError('Elige WhatsApp o correo electrónico.')
    options = options or {}
    tone = options.get('tone') or 'profesional'
    if tone not in TONES:
        raise MessageError('Elige un tono válido.')
    include_progress = options.get('progress', True) is not False
    include_date = options.get('date', True) is not False
    note = ' '.join(str(note or '').split())[:600]
    info, body = base_body(c, oid, include_date)
    try:
        ctx = adi_order.context(c, oid)
    except Exception as error:  # sin contexto se redacta igual; el dinero queda «no verificado»
        print('status-message-context', type(error).__name__, flush=True)
        ctx = None
    fin = finance(c, oid, ctx) if ctx else None
    wanted = options.get('payment')
    include_payment = payment_default(fin) if wanted is None else bool(wanted) and bool(fin) and fin['balance_cents'] > 0
    source, warnings, internal = 'plantilla', [], None
    if use_ai and not (adi_ai.enabled(c) and adi_ai.provider()):
        use_ai = False
        warnings = ['ADI no está disponible en este servidor: se usó la explicación del estado real. Revísala antes de enviar.']
    if use_ai:
        try:
            body, warnings, internal = _adi(c, oid, channel, info, note, tone, include_progress, include_date)
            source = 'adi'
        except adi_ai.AdiError as error:
            warnings = ['ADI no pudo redactar el mensaje (%s). Se usó la explicación del estado; revísala antes de enviar.' % str(error).rstrip('.')]
    nxt = NEXT.get(info['code'], '')
    if nxt and nxt.lower()[:20] not in body.lower():
        body = body.rstrip() + ' ' + nxt
    paragraph = payment_text(fin) if include_payment else ''
    link = order_tracking.active(c, oid)['url']
    o = order_followups._order(c, oid)
    device = ' '.join(x for x in (o['brand'], o['model']) if x)
    subject = 'PC-DOCTOR · Orden %s · %s' % (o['code'], info['label'])
    if channel == 'correo':
        full = order_followups.ai_wrap(c, oid, 'estado', body + ('\n\n' + paragraph if paragraph else ''), cost=False, tracking_url=link)['body']
    else:
        lines = ['Hola, %s. Le saluda PC-DOCTOR.' % order_followups._first_name(o['client']), '', 'Orden %s%s' % (o['code'], ' · ' + device if device else ''),
                 body.strip(), '']
        if paragraph:
            lines += [paragraph, '']
        if link:
            lines.append('Seguimiento: ' + link)
        full = '\n'.join(lines + ['PC-DOCTOR | Servicio Técnico'])
    now = now or reception_now()
    if internal is None:
        internal = _internal_count(c, oid)
    checks = review(c, oid, ctx, info, internal, include_date) if ctx else []
    if paragraph:
        sent = _recent(ctx, 'last_payment_message', REMINDER_HOURS, now)
        if sent:
            checks.append({'level': 'warn', 'text': 'Ya se envió o preparó un recordatorio de pago el %s: evita repetirlo.' % sent})
    last = _recent(ctx, 'last_message', 24, now)
    if last:
        checks.append({'level': 'info', 'text': 'Ya hay un mensaje para este cliente preparado o enviado el %s: revisa que no se repita.' % last})
    date_text = _day(info['estimated']) if _date_usable(info) else ''
    return {'channel': channel, 'channel_label': CHANNELS[channel], 'subject': subject, 'body': full, 'source': source, 'warnings': warnings,
            'status': info['code'], 'status_label': info['label'], 'order': {'id': oid, 'code': o['code'], 'device': device},
            'finance': fin, 'finance_notes': finance_notes(fin, include_payment), 'review': checks, 'payment_text': paragraph,
            'options': {'payment': include_payment, 'payment_available': bool(fin and fin['balance_cents'] > 0), 'progress': include_progress,
                        'date': include_date and bool(date_text), 'date_available': bool(date_text), 'date_value': date_text, 'tone': tone},
            'tones': {k: v[0] for k, v in TONES.items()}}


AMOUNT_IN_TEXT = re.compile(r'saldo pendiente de (\$\s?[\d.,]*\d)', re.I)


def verify(c, oid, fingerprint_value, text):
    """Comprobación antes de enviar: que el saldo no cambió desde que se generó el texto y que el importe del texto es el actual."""
    fin = finance(c, oid)
    problems = []
    quoted = AMOUNT_IN_TEXT.findall(str(text or ''))
    if not fin:
        problems.append(UNVERIFIED + ' Vuelve a generar el mensaje antes de enviarlo.')
    else:
        if fingerprint_value and fingerprint_value != fin['fingerprint']:
            problems.append('El estado financiero cambió después de generar el mensaje (saldo actual: %s). Actualiza el mensaje antes de enviarlo.' % fin['balance'])
        if quoted and fin['balance_cents'] <= 0:
            problems.append('El mensaje menciona un saldo pendiente, pero la orden ya no registra saldo.')
        elif any(amount.replace(' ', '') != fin['balance'] for amount in quoted):
            problems.append('El mensaje indica un saldo pendiente distinto del registrado (%s).' % fin['balance'])
    info = repair_status.public(c, oid) or {}
    usable = bool(info) and _date_usable(info)
    return {'ok': not problems, 'problems': problems, 'finance': fin, 'notes': finance_notes(fin, payment_default(fin)),
            'status': info.get('code', ''), 'status_label': info.get('label', ''),
            'options': {'payment': payment_default(fin), 'payment_available': bool(fin and fin['balance_cents'] > 0),
                        'date_available': usable, 'date_value': _day(info['estimated']) if usable else ''},
            'tones': {k: v[0] for k, v in TONES.items()}}
