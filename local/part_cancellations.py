"""Cancelación y anulación de pedidos de repuestos, con revisión de administración y reembolsos conciliados.

- La solicita el cliente (desde el enlace de seguimiento, comprobando los últimos cuatro dígitos de su identificación) o el personal en su
  nombre (teléfono, presencial, correo o WhatsApp). Una solicitud NUNCA anula el pedido: queda pendiente hasta que administración la aprueba
  o la rechaza con justificación. Solo hay una abierta a la vez por repuesto.
- Administración también registra cancelaciones propias: proveedor, falta de disponibilidad, problema de importación, pedido duplicado o
  cancelación administrativa.
- Reglas según el punto del pedido: sin comprar se puede aprobar de inmediato; comprado exige confirmar que se revisaron los compromisos con
  el proveedor; en tránsito, aduana o transporte nacional exige una revisión administrativa expresa; recibido o instalado no se cancela por
  aquí (corresponde devolución, garantía o reclamo).
- Al aprobar, el pedido queda «cancelado» (definitivo: ya no avanza) con su evento en el historial. Nada más se toca: compras, inventario,
  ventas, facturas autorizadas y caja siguen sus propios procedimientos (una factura autorizada se corrige con nota de crédito).
- El reembolso es aparte del estado logístico: administración indica el importe a devolver (si hay pagos) y cada devolución real de la orden
  (order_payments, kind=devolucion, que pasa por caja) se vincula una sola vez. El estado (pendiente, parcial, completado) sale de esas
  devoluciones; nunca se reembolsa automáticamente.
- Todo queda en order_part_log (no se modifica ni se borra)."""
import json
import re

import order_part_requests as parts
from order_part_requests import PartError, stamp

REASONS = {'cliente_desiste': 'El cliente desiste de la compra', 'proveedor': 'Cancelación por parte del proveedor', 'sin_disponibilidad': 'Falta de disponibilidad',
           'importacion': 'Problema de importación', 'duplicado': 'Pedido duplicado', 'administrativa': 'Cancelación administrativa'}
ADMIN_REASONS = ('proveedor', 'sin_disponibilidad', 'importacion', 'duplicado', 'administrativa')
STATUS = {'solicitada': 'Cancelación solicitada', 'en_revision': 'Cancelación en revisión', 'aprobada': 'Cancelación aprobada', 'rechazada': 'Cancelación rechazada'}
REFUND = {'no_aplica': 'Sin reembolso', 'pendiente': 'Reembolso pendiente', 'parcial': 'Reembolso parcial', 'completado': 'Reembolso completado'}
CHANNELS = {'enlace': 'Enlace de seguimiento', 'telefono': 'Teléfono', 'presencial': 'Presencial', 'correo': 'Correo electrónico', 'whatsapp': 'WhatsApp', 'interno': 'Registro interno'}
PHASES = {'sin_compra': 'Sin compra registrada: se puede cancelar de inmediato.',
          'comprado': 'Repuesto ya comprado: revisa los compromisos con el proveedor antes de aprobar.',
          'transito': 'En tránsito, aduana o transporte nacional: requiere revisión administrativa antes de aprobar.',
          'recibido': 'Repuesto recibido o instalado: corresponde el procedimiento de devolución, garantía o reclamo, no una cancelación logística.',
          'cancelado': 'El pedido ya está cancelado.'}


def _admin(user):
    if not user or user['role'] != 'administrador':
        raise PartError('Solo administración decide las cancelaciones.', 403)


def phase(row):
    if row['situation'] == 'cancelado':
        return 'cancelado'
    index = parts.CODES.index(row['stage'])
    if index >= parts.CODES.index('recibido'):
        return 'recibido'
    if row['stage'] == 'transito':
        return 'transito'
    bought = bool(row['purchase_item_id'] or row['purchase_date'] or row['supplier_order']) or row['stage'] == 'preparacion'
    return 'comprado' if bought else 'sin_compra'


def log(c, rid, kind, action, note, origin, user, now, data=None):
    c.execute('INSERT INTO order_part_log(request_id,kind,action,note,data,origin,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (rid, kind, action, note[:1500], json.dumps(data, ensure_ascii=False) if data else '', origin, user['id'] if user else None, stamp(now)))


def open_for(c, rid):
    row = c.execute("SELECT * FROM order_part_cancellations WHERE request_id=? AND status IN ('solicitada','en_revision') ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
    return dict(row) if row else None


def _refunded(c, cid):
    return c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM order_part_refunds WHERE cancellation_id=?', (cid,)).fetchone()[0]


def context(c, oid, row):
    """Lo que administración necesita ver antes de decidir: punto del pedido, pagos de la orden y lo vinculado que NO se toca."""
    import equipment
    money = equipment.money(c, oid)
    warnings = []
    if row['purchase_item_id']:
        warnings.append('Tiene una línea de compra registrada: la compra no se anula aquí; si corresponde, se gestiona en Compras.')
    if row['inventory_item_id']:
        warnings.append('Está vinculado a un producto del inventario: las existencias y reservas no cambian con la cancelación.')
    if c.execute("SELECT 1 FROM invoices WHERE order_id=? AND status='autorizado' LIMIT 1", (oid,)).fetchone():
        warnings.append('La orden tiene una factura electrónica autorizada: no se borra ni se anula aquí; si corresponde, se emite una nota de crédito.')
    state = phase(row)
    return {'phase': state, 'phase_text': PHASES[state], 'paid_cents': max(0, money['paid_cents']), 'balance_cents': money['balance_cents'], 'warnings': warnings,
            'can_request': state not in ('recibido', 'cancelado') and not open_for(c, row['id'])}


def history(c, rid):
    names = {r[0]: r[1] for r in c.execute('SELECT id,name FROM users')}
    out = []
    for r in c.execute('SELECT * FROM order_part_cancellations WHERE request_id=? ORDER BY id DESC', (rid,)):
        refunds = [dict(x, actor=names.get(x['created_by'], '')) for x in c.execute(
            'SELECT f.*,p.method,p.created_at paid_at FROM order_part_refunds f JOIN order_payments p ON p.id=f.payment_id WHERE f.cancellation_id=? ORDER BY f.id', (r['id'],))]
        out.append(dict(r, status_label=STATUS[r['status']], reason_label=REASONS[r['reason_code']], channel_label=CHANNELS.get(r['channel'], r['channel']),
                        refund_label=REFUND[r['refund_state']], refunded_cents=sum(x['amount_cents'] for x in refunds), refunds=refunds,
                        decided_by_name=names.get(r['decided_by'], ''), created_by_name=names.get(r['created_by'], '') if r['created_by'] else 'Cliente (enlace de seguimiento)'))
    return out


def _key(data):
    key = str(data.get('request_key', '') or '').strip()[:64]
    if key and not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
        raise PartError('Solicitud no válida. Recarga la página.')
    return key


def request(c, oid, rid, data, user, now, origin='personal'):
    """Registra una solicitud de cancelación (queda pendiente de revisión; el pedido no cambia). Devuelve (id, nueva)."""
    if origin == 'personal' and (not user or user['role'] not in ('administrador', 'tecnico')):
        raise PartError('Acceso no permitido.', 403)
    row = parts._request(c, oid, rid)
    key = _key(data)
    if key:
        same = c.execute('SELECT id FROM order_part_cancellations WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id'], False
    state = phase(row)
    if state in ('recibido', 'cancelado'):
        raise PartError(PHASES[state], 409)
    if open_for(c, row['id']):
        raise PartError('Ya hay una solicitud de cancelación pendiente de revisión para este repuesto.', 409)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()[:500]
    if len(reason) < 10:
        raise PartError('Indica el motivo de la cancelación (al menos 10 caracteres).', 400, {'reason': 'Motivo obligatorio.'})
    channel = 'enlace' if origin == 'cliente' else str(data.get('channel', '') or 'telefono')
    if channel not in CHANNELS:
        raise PartError('Canal no válido.', 400, {'channel': 'No válido.'})
    step = parts.fine(row)
    cid = c.execute('INSERT INTO order_part_cancellations(request_id,origin,channel,reason_code,reason,status,step_at_request,request_key,created_by,created_at,updated_at) '
                    "VALUES (?,?,?,'cliente_desiste',?,'solicitada',?,?,?,?,?)", (row['id'], origin, channel, reason, step, key or None,
                                                                              user['id'] if user and origin == 'personal' else None, stamp(now), stamp(now))).lastrowid
    log(c, row['id'], 'cancelacion', 'solicitada', reason, origin, user if origin == 'personal' else None, now, {'cancellation_id': cid, 'channel': channel, 'step': step})
    return cid, True


def _cancellation(c, row, data):
    cid = str(data.get('cancellation_id', '') or '')
    found = c.execute('SELECT * FROM order_part_cancellations WHERE id=? AND request_id=?', (int(cid), row['id'])).fetchone() if cid.isdigit() else None
    if not found:
        raise PartError('Solicitud de cancelación no encontrada.', 404)
    return dict(found)


def review(c, oid, rid, data, user, now):
    if not user or user['role'] not in ('administrador', 'tecnico'):
        raise PartError('Acceso no permitido.', 403)
    row = parts._request(c, oid, rid)
    found = _cancellation(c, row, data)
    if found['status'] != 'solicitada':
        raise PartError('La solicitud ya está en revisión o decidida.', 409)
    note = re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()[:500]
    c.execute("UPDATE order_part_cancellations SET status='en_revision',updated_at=? WHERE id=?", (stamp(now), found['id']))
    log(c, row['id'], 'cancelacion', 'en_revision', note or 'Solicitud en revisión.', 'personal', user, now, {'cancellation_id': found['id']})
    return found['id']


def _refund_due(c, oid, data):
    import equipment
    raw = str(data.get('refund_due', '') or '').strip()
    if not raw:
        return 0
    cents = equipment.cents_of(raw)
    if cents is None:
        raise PartError('Importe a devolver no válido.', 400, {'refund_due': 'Usa un importe con hasta dos decimales.'})
    paid = max(0, equipment.money(c, oid)['paid_cents'])
    if cents > paid:
        raise PartError('El importe a devolver supera lo pagado en la orden (%s).' % equipment.usd(paid), 400, {'refund_due': 'Supera lo pagado.'})
    return cents


def _approve_checks(row, data, note):
    state = phase(row)
    if state in ('recibido', 'cancelado'):
        raise PartError(PHASES[state], 409)
    if state == 'comprado' and str(data.get('confirm_supplier', '')) not in ('1', 'true'):
        raise PartError('Confirma que revisaste los compromisos con el proveedor.', 400, {'confirm_supplier': 'Confirmación obligatoria.'})
    if state == 'transito' and str(data.get('confirm_transit', '')) not in ('1', 'true'):
        raise PartError('El repuesto está en traslado: confirma la revisión administrativa del envío.', 400, {'confirm_transit': 'Confirmación obligatoria.'})
    if len(note) < 10:
        raise PartError('Indica la justificación de la decisión (al menos 10 caracteres).', 400, {'note': 'Justificación obligatoria.'})
    return state


def _close(c, row, cid, note, user, now):
    """Deja el pedido cancelado (definitivo) con su evento en el historial del repuesto."""
    c.execute("UPDATE order_part_requests SET situation='cancelado',incident='',updated_at=? WHERE id=?", (stamp(now), row['id']))
    parts._event(c, row, 'situacion', user, now, note='Cancelación aprobada: ' + note, situation='cancelado',
                 changes={'situation': [row['incident'] or row['situation'], 'cancelado'], 'cancellation_id': cid}, incident='')


def decide(c, oid, rid, data, user, now):
    """Aprueba o rechaza una solicitud. Rechazar exige justificación; aprobar sigue las reglas del punto del pedido."""
    _admin(user)
    row = parts._request(c, oid, rid)
    found = _cancellation(c, row, data)
    if found['status'] not in ('solicitada', 'en_revision'):
        raise PartError('Esta solicitud ya fue decidida.', 409)
    decision = str(data.get('decision', ''))
    note = re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()[:1000]
    if decision == 'rechazar':
        if len(note) < 10:
            raise PartError('Indica la justificación del rechazo (al menos 10 caracteres).', 400, {'note': 'Justificación obligatoria.'})
        c.execute("UPDATE order_part_cancellations SET status='rechazada',decision_note=?,decided_by=?,decided_at=?,updated_at=? WHERE id=?",
                  (note, user['id'], stamp(now), stamp(now), found['id']))
        log(c, row['id'], 'cancelacion', 'rechazada', note, 'personal', user, now, {'cancellation_id': found['id']})
        return {'status': 'rechazada', 'cancellation_id': found['id']}
    if decision != 'aprobar':
        raise PartError('Decisión no válida.', 400, {'decision': 'Aprobar o rechazar.'})
    state = _approve_checks(row, data, note)
    due = _refund_due(c, oid, data)
    c.execute("UPDATE order_part_cancellations SET status='aprobada',decision_note=?,decided_by=?,decided_at=?,refund_due_cents=?,refund_state=?,updated_at=? WHERE id=?",
              (note, user['id'], stamp(now), due, 'pendiente' if due else 'no_aplica', stamp(now), found['id']))
    _close(c, row, found['id'], note, user, now)
    log(c, row['id'], 'cancelacion', 'aprobada', note, 'personal', user, now, {'cancellation_id': found['id'], 'phase': state, 'refund_due_cents': due})
    return {'status': 'aprobada', 'cancellation_id': found['id'], 'refund_due_cents': due}


def direct(c, oid, rid, data, user, now):
    """Cancelación registrada por administración (proveedor, disponibilidad, importación, duplicado o administrativa): se aprueba al registrarla."""
    _admin(user)
    row = parts._request(c, oid, rid)
    key = _key(data)
    if key:
        same = c.execute('SELECT id FROM order_part_cancellations WHERE request_key=?', (key,)).fetchone()
        if same:
            return {'status': 'aprobada', 'cancellation_id': same['id'], 'duplicate': True}
    code = str(data.get('reason_code', '') or 'administrativa')
    if code not in ADMIN_REASONS:
        raise PartError('Motivo no válido.', 400, {'reason_code': 'No válido.'})
    if open_for(c, row['id']):
        raise PartError('Hay una solicitud del cliente pendiente: apruébala o recházala primero.', 409)
    note = re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()[:1000]
    state = _approve_checks(row, data, note)
    due = _refund_due(c, oid, data)
    cid = c.execute('INSERT INTO order_part_cancellations(request_id,origin,channel,reason_code,reason,status,step_at_request,decision_note,decided_by,decided_at,'
                    "refund_due_cents,refund_state,request_key,created_by,created_at,updated_at) VALUES (?,'personal','interno',?,?,'aprobada',?,?,?,?,?,?,?,?,?,?)",
                    (row['id'], code, note, parts.fine(row), note, user['id'], stamp(now), due, 'pendiente' if due else 'no_aplica', key or None, user['id'],
                     stamp(now), stamp(now))).lastrowid
    _close(c, row, cid, REASONS[code] + '. ' + note, user, now)
    log(c, row['id'], 'cancelacion', 'aprobada', REASONS[code] + '. ' + note, 'personal', user, now, {'cancellation_id': cid, 'reason_code': code, 'phase': state, 'refund_due_cents': due})
    return {'status': 'aprobada', 'cancellation_id': cid, 'refund_due_cents': due}


def refund(c, oid, rid, data, user, now):
    """Vincula una devolución real de la orden (existente o registrada aquí por administración, con su método) a una cancelación aprobada."""
    import equipment
    _admin(user)
    row = parts._request(c, oid, rid)
    found = _cancellation(c, row, data)
    if found['status'] != 'aprobada' or not found['refund_due_cents']:
        raise PartError('Esta cancelación no tiene un reembolso pendiente.', 409)
    remaining = found['refund_due_cents'] - _refunded(c, found['id'])
    if remaining <= 0:
        raise PartError('El reembolso ya está completado.', 409)
    pid = str(data.get('payment_id', '') or '')
    if pid:
        pay = c.execute("SELECT id,amount_cents,order_id,kind,voided_at FROM order_payments WHERE id=?", (int(pid),)).fetchone() if pid.isdigit() else None
        if not pay or pay['kind'] != 'devolucion' or pay['voided_at'] or pay['order_id'] not in (oid, equipment.root(c, oid)['id']):
            raise PartError('Elige una devolución registrada de esta orden.', 400, {'payment_id': 'No válida.'})
        if c.execute('SELECT 1 FROM order_part_refunds WHERE payment_id=?', (pay['id'],)).fetchone():
            raise PartError('Esa devolución ya está vinculada a un reembolso.', 409, {'payment_id': 'Ya vinculada.'})
        if pay['amount_cents'] > remaining:
            raise PartError('La devolución supera el importe pendiente de reembolso (%s).' % equipment.usd(remaining), 400, {'payment_id': 'Supera lo pendiente.'})
        amount = pay['amount_cents']
    else:
        amount = equipment.cents_of(str(data.get('amount', '') or ''))
        if amount is None:
            raise PartError('Indica el importe devuelto.', 400, {'amount': 'Importe no válido.'})
        if amount > remaining:
            raise PartError('El importe supera lo pendiente de reembolso (%s).' % equipment.usd(remaining), 400, {'amount': 'Supera lo pendiente.'})
        note = re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()[:250] or 'Reembolso por cancelación del repuesto ' + row['name']
        status, body = equipment.add_payment(c, oid, {'kind': 'devolucion', 'amount': str(data.get('amount', '')), 'method': str(data.get('method', '') or 'efectivo'),
                                                      'note': note if len(note) >= 5 else 'Reembolso por cancelación', 'request_key': _key(data) or '',
                                                      'bank_account_id': str(data.get('bank_account_id', '') or ''), 'reference': str(data.get('reference', '') or ''),
                                                      'paid_at': str(data.get('paid_at', '') or '')}, user, now)
        if status not in (200, 201):
            raise PartError(body.get('error', 'No se pudo registrar la devolución.'), status, body.get('fields'))
        if body.get('duplicate') and c.execute('SELECT 1 FROM order_part_refunds WHERE payment_id=?', (body['id'],)).fetchone():
            return {'refund_state': found['refund_state'], 'duplicate': True}
        pid = str(body['id'])
    fid = c.execute('INSERT INTO order_part_refunds(cancellation_id,payment_id,amount_cents,created_by,created_at) VALUES (?,?,?,?,?)',
                    (found['id'], int(pid), amount, user['id'], stamp(now))).lastrowid
    done = _refunded(c, found['id'])
    state = 'completado' if done >= found['refund_due_cents'] else 'parcial'
    c.execute('UPDATE order_part_cancellations SET refund_state=?,updated_at=? WHERE id=?', (state, stamp(now), found['id']))
    log(c, row['id'], 'reembolso', state, 'Reembolso de %s vinculado a la devolución REC-%06d.' % (equipment.usd(amount), int(pid)), 'personal', user, now,
        {'cancellation_id': found['id'], 'refund_id': fid, 'payment_id': int(pid), 'amount_cents': amount})
    return {'refund_state': state, 'refund_id': fid, 'payment_id': int(pid), 'refunded_cents': done}


def public_state(c, rid):
    """Lo que el cliente ve de una cancelación: estado y fecha, sin importes, motivos internos ni nombres."""
    row = c.execute('SELECT status,refund_state,created_at,decided_at,updated_at FROM order_part_cancellations WHERE request_id=? ORDER BY id DESC LIMIT 1', (rid,)).fetchone()
    if not row:
        return None
    text = {'solicitada': 'Recibimos su solicitud de cancelación. Nuestro departamento administrativo la revisará y le informaremos el resultado.',
            'en_revision': 'Su solicitud de cancelación está en revisión por nuestro departamento administrativo.',
            'aprobada': 'La cancelación de este repuesto fue aprobada.', 'rechazada': 'La solicitud de cancelación no fue aprobada. Nuestro personal le explicará el motivo.'}[row['status']]
    if row['status'] == 'aprobada' and row['refund_state'] in ('pendiente', 'parcial'):
        text += ' En caso de pagos anticipados, administración le comunicará el procedimiento correspondiente.'
    elif row['status'] == 'aprobada' and row['refund_state'] == 'completado':
        text += ' El reembolso correspondiente quedó registrado.'
    return {'status': row['status'], 'label': STATUS[row['status']], 'text': text, 'at': row['decided_at'] or row['created_at']}
