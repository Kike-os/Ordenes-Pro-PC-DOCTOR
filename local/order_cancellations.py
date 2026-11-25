"""Smart Cancellation & Closure Management (docs/CANCELACION-ORDENES.md).

Flujo (el estado administrativo se calcula con datos reales; solo se guardan solicitada, cancelada, cerrada y anulada):
  1. Cancelación solicitada   → el personal (con verificación de identidad) o el cliente desde el portal seguro la registra.
  2. Reparación cancelada      → administración la confirma: la orden pasa a «En espera de entrega» (se detiene el trabajo técnico),
                                 se cancelan los presupuestos que esperaban aprobación y se avisa al cliente (plantilla aprobada).
  3. Pendiente de liquidación  → hay saldo por cobrar (solo trabajos AUTORIZADOS) o un saldo a favor por devolver.
  4. Pendiente de retiro       → liquidada, falta devolver el equipo.
  5. Cerrada por cancelación   → equipo devuelto y obligaciones resueltas (solo entonces).
Reglas: nada se borra (fotos, diagnóstico, presupuestos, pagos, facturas, conversaciones e historial se conservan); no se generan cobros
automáticos ni se mueven inventarios o pagos por sí solos (los repuestos y los movimientos se muestran para que el personal los resuelva);
confirmar, reabrir y cerrar son exclusivos de administración y quedan en el historial inmutable y en la auditoría."""
import base64
import hmac
import json
import re

import equipment

REASONS = {'cliente_desiste': 'El cliente decide no continuar con la reparación', 'costo': 'El costo de la reparación no le conviene',
           'tiempo': 'El tiempo de reparación es demasiado largo', 'repuesto': 'No hay repuesto disponible o tarda demasiado',
           'sin_solucion': 'El equipo no tiene una reparación viable', 'otro_proveedor': 'Prefiere atenderse con otro proveedor', 'otro': 'Otro motivo'}
STATES = {'solicitada': 'Cancelación solicitada', 'cancelada': 'Reparación cancelada', 'pendiente_liquidacion': 'Pendiente de liquidación',
          'pendiente_retiro': 'Pendiente de retiro', 'cerrada': 'Cerrada por cancelación', 'anulada': 'Cancelación anulada (orden reabierta)'}
ACTIVE = ('solicitada', 'cancelada')
FILE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'application/pdf'}
MAX_FILE = 4 * 1024 * 1024


class CancelError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status = status
        self.fields = fields or {}


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_cancellations'").fetchone())


def stamp(now):
    return now.isoformat(timespec='seconds')


def _admin(user):
    return bool(user) and user['role'] == 'administrador'


def current(c, oid):
    """Cancelación vigente (solicitada, cancelada o cerrada) de la orden, o None. Una anulada no cuenta."""
    if not installed(c):
        return None
    return c.execute("SELECT * FROM order_cancellations WHERE order_id=? AND state!='anulada' ORDER BY id DESC LIMIT 1", (oid,)).fetchone()


def blocks_status_change(c, oid):
    """Texto de bloqueo si la orden tiene una cancelación en curso (el estado lo maneja este módulo); None si no."""
    row = current(c, oid)
    if row and row['state'] in ACTIVE:
        return 'Esta orden tiene una cancelación en curso: gestiónala desde «Cancelación» (reabrir, liquidar o devolver el equipo).'
    return None


def _event(c, cid, kind, detail, user, now):
    c.execute('INSERT INTO order_cancellation_events(cancellation_id,kind,detail,actor_id,actor_name,created_at) VALUES (?,?,?,?,?,?)',
              (cid, kind, detail[:600], user['id'] if user else None, (user['name'] if user else 'Cliente (portal seguro)')[:120], stamp(now)))


def _order(c, oid):
    row = c.execute("SELECT o.*,cl.name client,COALESCE(cl.identification,'') identification,d.brand,d.model,d.serial FROM orders o "
                    'JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (oid,)).fetchone()
    if not row:
        raise CancelError('Orden no disponible.', 404)
    return row


def verify_identity(order, data):
    """Mecanismo existente: los últimos 4 dígitos de la identificación registrada (el cliente los dice; no se guardan). Sin identificación
    registrada se exige una nota de cómo se verificó."""
    digits = re.sub(r'\D', '', str(order['identification'] or ''))
    given = re.sub(r'\D', '', str(data.get('id_last4', '') or ''))[:4]
    if len(digits) >= 4:
        if len(given) != 4 or not hmac.compare_digest(given, digits[-4:]):
            raise CancelError('Los últimos 4 dígitos no coinciden con la identificación registrada del cliente.', 400, {'id_last4': 'No coincide.'})
        return 'ultimos_4_digitos'
    note = re.sub(r'\s+', ' ', str(data.get('identity_note', '') or '')).strip()
    if len(note) < 10:
        raise CancelError('El cliente no tiene identificación registrada: describe cómo verificaste su identidad.', 400, {'identity_note': 'Obligatorio.'})
    return 'nota: ' + note[:200]


def _reason(data):
    code = str(data.get('reason', '') or '')
    detail = re.sub(r'\s+', ' ', str(data.get('detail', '') or '')).strip()
    errors = {}
    if code not in REASONS:
        errors['reason'] = 'Elige un motivo.'
    if len(detail) < 10:
        errors['detail'] = 'Escribe las observaciones (al menos 10 caracteres).'
    if errors:
        raise CancelError('Completa el motivo y las observaciones.', 400, errors)
    return code, detail[:600]


def attach(c, cid, file, user, now):
    """Evidencia de la solicitud del cliente (imagen o PDF, hasta 4 MB). Se guarda tal cual, sin modificar."""
    if not file:
        return None
    name, mime, raw = file
    if mime not in FILE_TYPES:
        raise CancelError('La evidencia debe ser una imagen (JPG, PNG, WebP) o un PDF.', 400, {'file': 'Formato no admitido.'})
    if len(raw) > MAX_FILE:
        raise CancelError('La evidencia supera los 4 MB.', 400, {'file': 'Archivo demasiado grande.'})
    fid = c.execute('INSERT INTO order_cancellation_files(cancellation_id,name,mime,size,content,uploaded_by,created_at) VALUES (?,?,?,?,?,?,?)',
                    (cid, re.sub(r'[^\w.\- ]', '_', name)[:120] or 'evidencia', mime, len(raw), base64.b64encode(raw).decode(), user['id'] if user else None, stamp(now))).lastrowid
    _event(c, cid, 'evidencia', 'Evidencia adjunta: %s (%d KB).' % (name[:80], max(1, len(raw) // 1024)), user, now)
    return fid


def request(c, oid, data, user, now, via='personal', file=None):
    if not installed(c):
        raise CancelError('Falta aplicar la migración 127 (Sistema → Migraciones).', 409)
    o = _order(c, oid)
    if o['status'] == 'entregado':
        raise CancelError('La orden ya fue entregada: no se puede cancelar la reparación.', 409)
    if current(c, oid) and current(c, oid)['state'] in ACTIVE + ('cerrada',):
        raise CancelError('La orden ya tiene una cancelación registrada.', 409)
    code, detail = _reason(data)
    method = 'portal_seguro' if via == 'portal' else verify_identity(o, data)
    cid = c.execute('INSERT INTO order_cancellations(order_id,state,reason_code,reason_detail,via,identity_method,previous_status,requested_at,requested_by,updated_at) '
                    "VALUES (?,'solicitada',?,?,?,?,?,?,?,?)", (oid, code, detail, via, method, o['status'], stamp(now), user['id'] if user else None, stamp(now))).lastrowid
    _event(c, cid, 'solicitada', '%s · %s · Identidad: %s' % (REASONS[code], detail, 'portal seguro (enlace + 4 dígitos)' if via == 'portal' else method.replace('_', ' ')), user, now)
    attach(c, cid, file, user, now)
    _order_log(c, oid, user, now, 'Cancelación solicitada: ' + REASONS[code] + '.')
    return cid


def _order_log(c, oid, user, now, text):
    try:
        import order_workspace
        order_workspace.event(c, oid, user['id'] if user else None, now, 'follow_up', text)
    except Exception as error:
        print('cancel-order-log', type(error).__name__, flush=True)


def _set_status(c, oid, new, user, now, reason):
    old = c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()['status']
    if old == new:
        return
    extra = ',delivered_at=?' if new == 'entregado' else ''
    args = [new, stamp(now)] + ([stamp(now)] if new == 'entregado' else []) + [oid]
    c.execute('UPDATE orders SET status=?,updated_at=?' + extra + ',revision=revision+1 WHERE id=?', args)
    c.execute('INSERT INTO order_status_log(order_id,from_status,to_status,actor_id,reason,source,created_at) VALUES (?,?,?,?,?,?,?)',
              (oid, old, new, user['id'] if user else None, reason[:300], 'cancelacion', stamp(now)))


def confirm(c, oid, data, user, now):
    """Administración confirma: se detiene el trabajo técnico, se cancelan los presupuestos que esperaban aprobación y se avisa al cliente."""
    if not _admin(user):
        raise CancelError('Solo administración confirma una cancelación.', 403)
    row = current(c, oid)
    if not row or row['state'] != 'solicitada':
        raise CancelError('No hay una cancelación solicitada para confirmar.', 409)
    if str(data.get('confirm', '')).strip().upper() != 'CANCELAR':
        raise CancelError('Escribe CANCELAR para confirmar.', 400, {'confirm': 'Confirmación obligatoria.'})
    o = _order(c, oid)
    c.execute("UPDATE order_cancellations SET state='cancelada',previous_status=?,confirmed_at=?,confirmed_by=?,revision=revision+1,updated_at=? WHERE id=?",
              (o['status'], stamp(now), user['id'], stamp(now), row['id']))
    cancelled = []
    import quotes
    for q in c.execute("SELECT * FROM quotes WHERE order_id=? AND deleted_at='' AND status IN ('enviado','modificacion','borrador')", (oid,)).fetchall():
        try:
            quotes.cancel(c, q, user, now, 'Reparación cancelada a solicitud del cliente.')
            cancelled.append(q['code'])
        except Exception as error:
            print('cancel-quote', type(error).__name__, flush=True)
    _set_status(c, oid, 'espera_entrega', user, now, 'Reparación cancelada a solicitud del cliente (' + REASONS[row['reason_code']] + ').')
    _event(c, row['id'], 'cancelada', 'Cancelación confirmada. Estado anterior: %s.%s' % (o['status'], (' Presupuestos cancelados: ' + ', '.join(cancelled) + '.') if cancelled else ''), user, now)
    _order_log(c, oid, user, now, 'Reparación cancelada a solicitud del cliente. El equipo queda pendiente de retiro.')
    return {'quotes_cancelled': cancelled}


def notify(c, oid, now):
    """Aviso por WhatsApp de la cancelación confirmada (plantilla aprobada; mismas reglas de consentimiento y límites). Nunca bloquea."""
    try:
        import whatsapp_business as wa
        row = current(c, oid)
        nid = wa.enqueue(c, 'orden_cancelada', 'cancelacion:%d' % row['id'], now, order_id=oid, source='cancelacion', manual=True)
        if nid:
            c.commit()
            return (wa.process(c, now, [nid]) or [None])[0]
    except Exception as error:
        print('cancel-notify', type(error).__name__, flush=True)
    return None


def reopen(c, oid, data, user, now):
    if not _admin(user):
        raise CancelError('Solo administración reabre una orden cancelada.', 403)
    row = current(c, oid)
    if not row or row['state'] not in ACTIVE:
        raise CancelError('No hay una cancelación en curso para anular.', 409)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if len(reason) < 10:
        raise CancelError('Explica por qué se reabre la orden (al menos 10 caracteres).', 400, {'reason': 'Obligatorio.'})
    o = _order(c, oid)
    if o['status'] == 'entregado':
        raise CancelError('El equipo ya fue devuelto: no se puede reabrir.', 409)
    c.execute("UPDATE order_cancellations SET state='anulada',reopened_at=?,reopened_by=?,reopen_reason=?,revision=revision+1,updated_at=? WHERE id=?",
              (stamp(now), user['id'], reason[:300], stamp(now), row['id']))
    if row['state'] == 'cancelada' and row['previous_status']:
        target = row['previous_status']
        pending = c.execute("SELECT 1 FROM quotes WHERE order_id=? AND deleted_at='' AND status IN ('enviado','modificacion')", (oid,)).fetchone()
        if target in ('presupuesto', 'esperando_cliente') and not pending:
            target = 'diagnostico'   # los presupuestos cancelados no se reactivan: se reabre en diagnóstico para emitir una nueva versión
            reason += ' (presupuesto cancelado: emitir una nueva versión)'
        _set_status(c, oid, target, user, now, 'Orden reabierta: ' + reason)
    _event(c, row['id'], 'reabierta', 'Orden reabierta: ' + reason, user, now)
    _order_log(c, oid, user, now, 'Cancelación anulada: la orden se reabre (' + reason[:200] + ').')


def close(c, oid, data, user, now):
    """Devolución del equipo y cierre: solo sin saldo por cobrar ni saldo a favor pendiente. No crea mantenimiento ni avisos de entrega."""
    if not _admin(user):
        raise CancelError('Solo administración cierra una cancelación.', 403)
    row = current(c, oid)
    if not row or row['state'] != 'cancelada':
        raise CancelError('La cancelación debe estar confirmada antes de cerrarla.', 409)
    m = equipment.money(c, oid)
    if m['balance_cents'] > 0:
        raise CancelError('Hay un saldo pendiente de %s por trabajos autorizados: regístralo o documenta la condonación antes de cerrar.' % equipment.usd(m['balance_cents']), 409)
    if m['credit_cents'] > 0:
        raise CancelError('El cliente tiene un saldo a favor de %s: registra la devolución antes de cerrar.' % equipment.usd(m['credit_cents']), 409)
    receiver = re.sub(r'\s+', ' ', str(data.get('receiver', '') or '')).strip()
    if len(receiver) < 5:
        raise CancelError('Indica quién retiró el equipo (nombre y cédula).', 400, {'receiver': 'Obligatorio.'})
    _set_status(c, oid, 'entregado', user, now, 'Equipo devuelto por cancelación. Retiró: ' + receiver[:200])
    c.execute("UPDATE order_cancellations SET state='cerrada',closed_at=?,closed_by=?,revision=revision+1,updated_at=? WHERE id=?", (stamp(now), user['id'], stamp(now), row['id']))
    _event(c, row['id'], 'cerrada', 'Equipo devuelto y cancelación cerrada. Retiró: ' + receiver[:200], user, now)
    _order_log(c, oid, user, now, 'Orden cerrada por cancelación. Equipo devuelto a ' + receiver[:200] + '.')


def state_of(c, row, oid):
    if row['state'] in ('solicitada', 'cerrada', 'anulada'):
        return row['state']
    m = equipment.money(c, oid)
    if m['balance_cents'] > 0 or m['credit_cents'] > 0:
        return 'pendiente_liquidacion'
    return 'pendiente_retiro'


def detail(c, oid, user=None):
    """Panel de la orden: cancelación vigente con su estado administrativo, liquidación y pendientes operativos (solo lectura)."""
    if not installed(c):
        return {'installed': False}
    row = current(c, oid)
    o = _order(c, oid)
    out = {'installed': True, 'reasons': REASONS, 'states': STATES, 'can_manage': _admin(user), 'order_status': o['status'],
           'has_identification': len(re.sub(r'\D', '', o['identification'] or '')) >= 4, 'cancellation': None}
    history = [dict(r) for r in c.execute('SELECT id,state,reason_code,requested_at,reopened_at,reopen_reason FROM order_cancellations WHERE order_id=? ORDER BY id DESC', (oid,))]
    out['history'] = history
    if not row:
        return out
    st = state_of(c, row, oid)
    m = equipment.money(c, oid)
    parts = [dict(r) for r in c.execute("SELECT id,name,stage,situation FROM order_part_requests WHERE order_id=? AND situation!='cancelado'", (oid,))] if _table(c, 'order_part_requests') else []
    units = [dict(r) for r in c.execute("SELECT u.internal_code,u.status,g.name FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id JOIN catalog_items g ON g.id=i.catalog_id "
                                       "WHERE u.order_id=? AND u.status IN ('reservada','vendida','consumida')", (oid,))] if _table(c, 'inventory_units') else []
    pending_quotes = [r['code'] for r in c.execute("SELECT code FROM quotes WHERE order_id=? AND deleted_at='' AND status IN ('enviado','modificacion','borrador')", (oid,))]
    out['cancellation'] = {'id': row['id'], 'state': st, 'state_label': STATES[st], 'reason': REASONS.get(row['reason_code'], row['reason_code']), 'reason_code': row['reason_code'],
                           'detail': row['reason_detail'], 'via': row['via'], 'identity': 'Portal seguro (enlace + 4 dígitos)' if row['via'] == 'portal' else ('Últimos 4 dígitos de la identificación verificados' if row['identity_method'] == 'ultimos_4_digitos' else 'Verificación manual · ' + row['identity_method'][6:]),
                           'previous_status': row['previous_status'], 'requested_at': row['requested_at'], 'confirmed_at': row['confirmed_at'], 'closed_at': row['closed_at'],
                           'money': {k: m[k] for k in ('budget_cents', 'paid_cents', 'balance_cents', 'credit_cents')},
                           'can_close': st == 'pendiente_retiro', 'parts': parts, 'inventory': units, 'pending_quotes': pending_quotes,
                           'files': [dict(r) for r in c.execute('SELECT id,name,mime,size,created_at FROM order_cancellation_files WHERE cancellation_id=?', (row['id'],))],
                           'events': [dict(r) for r in c.execute('SELECT kind,detail,actor_name,created_at FROM order_cancellation_events WHERE cancellation_id=? ORDER BY id', (row['id'],))]}
    return out


def _table(c, name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def public_state(c, oid):
    """Para el seguimiento y el portal del cliente: solo el estado y el motivo general (sin observaciones internas)."""
    row = current(c, oid)
    if not row:
        return None
    st = state_of(c, row, oid)
    return {'state': st, 'label': STATES[st], 'reason': REASONS.get(row['reason_code'], '')}


def stats(c, date_from='', date_to=''):
    """Reporte: canceladas por estado, motivos frecuentes, valores recuperados (cobros de las órdenes canceladas), devoluciones y equipos
    pendientes de retiro. Solo datos registrados."""
    if not installed(c):
        return {'installed': False}
    where, args = ["c.state!='anulada'"], []
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_from or ''):
        where.append('substr(c.requested_at,1,10)>=?'); args.append(date_from)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_to or ''):
        where.append('substr(c.requested_at,1,10)<=?'); args.append(date_to)
    rows = c.execute('SELECT c.* FROM order_cancellations c WHERE ' + ' AND '.join(where), args).fetchall()
    states, reasons, recovered, refunds = {k: 0 for k in STATES if k != 'anulada'}, {}, 0, 0
    for r in rows:
        states[state_of(c, r, r['order_id'])] += 1
        reasons[r['reason_code']] = reasons.get(r['reason_code'], 0) + 1
        for p in c.execute("SELECT kind,amount_cents FROM order_payments WHERE order_id=? AND voided_at IS NULL", (r['order_id'],)):
            if p['kind'] == 'devolucion':
                refunds += p['amount_cents']
            else:
                recovered += p['amount_cents']
    return {'installed': True, 'total': len(rows), 'states': states, 'state_labels': STATES,
            'reasons': sorted(({'code': k, 'label': REASONS.get(k, k), 'count': v} for k, v in reasons.items()), key=lambda x: -x['count']),
            'recovered_cents': recovered, 'refunds_cents': refunds, 'pending_pickup': states.get('pendiente_retiro', 0) + states.get('pendiente_liquidacion', 0)}


def acta_pdf(c, oid, now):
    """Acta de cancelación y devolución del equipo (A4): logotipo original, QR de seguimiento, cliente, equipo, motivo, liquidación y
    constancia de aceptación para firmar. Documento informativo: no es una factura ni modifica pagos."""
    import vouchers
    from reception import ECUADOR_TZ
    row = current(c, oid)
    if not row:
        raise CancelError('La orden no tiene una cancelación.', 404)
    o = _order(c, oid)
    st = state_of(c, row, oid)
    m = equipment.money(c, oid)
    s = vouchers.Sheet(595.28, 841.89, 'Acta de cancelación ' + (o['code'] or str(oid)))
    s.header('ACTA DE CANCELACIÓN Y DEVOLUCIÓN', o['code'] or str(oid), row['confirmed_at'] or row['requested_at'], 'Estado: ' + STATES[st])
    top = s.y
    tracking = vouchers._tracking(c, oid)
    s.section('Cliente y equipo')
    limit = s.RIGHT - 84 if tracking else None
    s.pair('Cliente', o['client'], limit)
    if o['identification']:
        s.pair('Identificación', o['identification'], limit)
    s.pair('Equipo', ' '.join(x for x in (o['brand'], o['model']) if x) or 'Equipo sin especificar', limit)
    s.pair('Número de serie', o['serial'] or 'No registrado', limit)
    if tracking:
        s.qr(tracking + '#' + (o['code'] or ''), 'Seguimiento seguro de la orden', top + 22)
        s.y = max(s.y, top + 22 + 64 + 18)
    s.y += 6
    s.section('Motivo de la cancelación')
    s.pair('Motivo', REASONS.get(row['reason_code'], row['reason_code']))
    s.pair('Observaciones', row['reason_detail'])
    s.pair('Solicitada', vouchers.when(row['requested_at']) + (' · portal seguro del cliente' if row['via'] == 'portal' else ' · ante el personal'))
    if row['confirmed_at']:
        s.pair('Confirmada', vouchers.when(row['confirmed_at']))
    prev = row['previous_status'] and c.execute('SELECT label FROM statuses WHERE code=?', (row['previous_status'],)).fetchone()
    s.pair('Estado anterior', (prev[0] if prev else row['previous_status']) or '—')
    s.y += 6
    s.section('Liquidación económica')
    s.totals((('Trabajos autorizados por el cliente', m['budget_cents'], False), ('Pagado', m['paid_cents'], False),
              ('Saldo a favor del cliente' if m['credit_cents'] else 'Saldo pendiente', m['credit_cents'] or m['balance_cents'], True)),
             'Solo se cobran trabajos autorizados por el cliente · calculado el ' + now.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'))
    s.section('Constancia de aceptación')
    for line in s.pdf.wrap('El cliente declara que solicitó la cancelación de la reparación, que recibe el equipo descrito en las condiciones en que se encuentra '
                           'y que la liquidación indicada refleja los trabajos que autorizó.', s.RIGHT - s.LEFT - 12, 8.4):
        s.pdf.text(line, s.LEFT + 6, s.y, 8.4, False, vouchers.INK)
        s.y += 11.5
    s.y += 40
    half = (s.RIGHT - s.LEFT - 30) / 2
    for n, label in enumerate(('Firma del cliente o persona autorizada · nombre y cédula', 'Por PC-DOCTOR S.A.')):
        x = s.LEFT + n * (half + 30)
        s.pdf.line(x, s.y, half)
        s.pdf.text(label, x, s.y + 4, 7.4, False, vouchers.GRAY)
    s.y += 26
    s.notes((vouchers.NOT_TAX,))
    return s.footer('entrega')
