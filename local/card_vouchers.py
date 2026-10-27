"""Comprobantes (vouchers) de cobros con tarjeta: banco emisor y adquirente, marca, categoría, tipo, plazo, lote, referencia, código de
aprobación, fecha, importe y últimos cuatro dígitos, con su comprobante adjunto.

- Nunca se guardan el CVV, el PIN, la banda magnética ni el número completo: solo los últimos cuatro dígitos.
- Una autorización repetida (mismo adquirente, lote y código) se advierte y solo se registra si se confirma expresamente.
- Las correcciones quedan auditadas con el valor anterior y el nuevo. La liquidación registra la comisión real que descuenta el adquirente,
  separada del importe que pagó el cliente.
- El neto esperado usa el recargo comercial configurado en la base cuando lo asume la empresa (sin volver al PDF)."""
import re

import banking
import card_finance

STATUS = {'registrada': 'Registrada', 'autorizada': 'Autorizada', 'pendiente_liquidacion': 'Pendiente de liquidación', 'liquidada': 'Liquidada', 'reversada': 'Reversada', 'rechazada': 'Rechazada'}
TYPES = {'debito': 'Débito', 'corriente': 'Crédito corriente', 'diferido_con_intereses': 'Diferido con intereses', 'diferido_sin_intereses': 'Diferido sin intereses'}
ACQUIRERS = ('DATAFAST', 'Medianet', 'Otro')
MOVES = {'autorizar': ('registrada', 'autorizada'), 'enviar_liquidacion': ('autorizada', 'pendiente_liquidacion'), 'reversar': (('registrada', 'autorizada', 'pendiente_liquidacion'), 'reversada'),
         'rechazar': (('registrada', 'autorizada'), 'rechazada')}
EDITABLE = ('issuer_bank', 'acquirer', 'brand', 'category', 'tx_type', 'months', 'lot', 'reference', 'approval_code', 'last4', 'paid_at')


class VoucherError(ValueError):
    def __init__(self, message, status=400, fields=None, extra=None):
        super().__init__(message)
        self.status, self.fields, self.extra = status, fields or {}, extra or {}


def _clean(c, data, now):
    text = lambda key, size: re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()[:size]
    out = {'issuer_bank': text('issuer_bank', 80), 'acquirer': text('acquirer', 40) or 'DATAFAST', 'brand': text('brand', 40), 'category': text('category', 80),
           'tx_type': str(data.get('tx_type', '')), 'lot': text('lot', 20), 'reference': text('reference', 30), 'approval_code': text('approval_code', 20).upper(),
           'last4': re.sub(r'\D', '', str(data.get('last4', '') or ''))}
    errors = {}
    if len(out['issuer_bank']) < 3:
        errors['issuer_bank'] = 'Banco emisor.'
    if out['acquirer'] not in ACQUIRERS:
        errors['acquirer'] = 'Adquirente no válido.'
    if len(out['brand']) < 2:
        errors['brand'] = 'Marca de la tarjeta.'
    if out['tx_type'] not in TYPES:
        errors['tx_type'] = 'Tipo de transacción.'
    try:
        months = int(str(data.get('months', '1') or '1'))
    except ValueError:
        months = 0
    if out['tx_type'] in ('diferido_con_intereses', 'diferido_sin_intereses'):
        if months not in card_finance.MONTHS:
            errors['months'] = 'Plazo de la tabla DATAFAST.'
    else:
        months = 1
    out['months'] = months
    if not re.fullmatch(r'[A-Za-z0-9-]{1,20}', out['lot']):
        errors['lot'] = 'Número de lote.'
    if not re.fullmatch(r'[A-Za-z0-9-]{1,30}', out['reference']):
        errors['reference'] = 'Número de referencia.'
    if not re.fullmatch(r'[A-Z0-9]{2,20}', out['approval_code']):
        errors['approval_code'] = 'Código de aprobación.'
    raw_last = str(data.get('last4', '') or '').strip()
    if not re.fullmatch(r'\d{4}', out['last4']) or len(re.sub(r'\D', '', raw_last)) != 4:
        errors['last4'] = 'Solo los últimos 4 dígitos (nunca el número completo).'
    if errors:
        raise VoucherError('Revisa los datos del voucher.', 400, errors)
    try:
        out['paid_at'] = banking.when(data.get('paid_at', ''), now)
    except banking.BankError as error:
        raise VoucherError(str(error), 400, error.fields)
    return out


def expected_commission(c, amount, today):
    """Comisión estimada con el recargo configurado cuando lo asume la empresa; 0 si no hay recargo a cargo de la empresa."""
    cfg = card_finance.surcharge_settings(c)
    if not cfg['active'] or cfg['payer'] != 'empresa':
        return 0
    if (cfg['valid_from'] and today < cfg['valid_from']) or (cfg['valid_to'] and today > cfg['valid_to']):
        return 0
    return card_finance.percent_of(amount, cfg['percent_bp']) + cfg['fixed_cents']


def _event(c, vid, name, detail, user, now):
    c.execute('INSERT INTO payment_events(entity,entity_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?,?)',
              ('voucher', vid, name, detail[:600], user['id'], user['name'], now.isoformat(timespec='seconds')))


def register(c, data, user, now, file_id=None):
    """Registra el voucher de un cobro con tarjeta (de una orden o de un anticipo) o suelto, y lo vincula a la caja abierta."""
    clean = _clean(c, data, now)
    payment_id = advance_id = client_id = session_id = None
    amount = None
    if str(data.get('payment_id', '')).isdigit():
        p = c.execute("SELECT p.*,d.client_id FROM order_payments p JOIN orders o ON o.id=p.order_id JOIN devices d ON d.id=o.device_id WHERE p.id=? AND p.kind='pago'", (int(data['payment_id']),)).fetchone()
        if not p or p['voided_at']:
            raise VoucherError('Pago no disponible.', 404)
        if p['method'] != 'tarjeta':
            raise VoucherError('Ese pago no es con tarjeta.', 409)
        if c.execute("SELECT 1 FROM card_vouchers WHERE payment_id=? AND status NOT IN ('rechazada')", (p['id'],)).fetchone():
            raise VoucherError('Ese pago ya tiene su voucher registrado.', 409)
        payment_id, amount, client_id, session_id = p['id'], p['amount_cents'], p['client_id'], p['cash_session_id']
    elif str(data.get('advance_id', '')).isdigit():
        a = c.execute('SELECT * FROM advances WHERE id=?', (int(data['advance_id']),)).fetchone()
        if not a or a['voided_at'] or a['method'] not in ('debito', 'credito'):
            raise VoucherError('Anticipo con tarjeta no disponible.', 404)
        if c.execute("SELECT 1 FROM card_vouchers WHERE advance_id=? AND status NOT IN ('rechazada')", (a['id'],)).fetchone():
            raise VoucherError('Ese anticipo ya tiene su voucher registrado.', 409)
        advance_id, amount, client_id, session_id = a['id'], a['amount_cents'], a['client_id'], a['cash_session_id']
    if amount is None:
        import cash_sessions
        try:
            amount = cash_sessions.cents_of(data.get('amount', ''))
        except cash_sessions.CashError as error:
            raise VoucherError(str(error), 400, error.fields)
        if str(data.get('client_id', '')).isdigit():
            client_id = int(data['client_id'])
        import cash_sessions as cs
        session_id = cs.current_for(c, user)
    dup = c.execute("SELECT code FROM card_vouchers WHERE acquirer=? AND lot=? AND approval_code=? AND status NOT IN ('rechazada','reversada')", (clean['acquirer'], clean['lot'], clean['approval_code'])).fetchone()
    if dup and str(data.get('confirm_duplicate', '')) not in ('1', 'true'):
        raise VoucherError('Ya existe el voucher %s con el mismo adquirente, lote y código de aprobación. Confirma si de verdad es otra operación.' % dup['code'], 409,
                           {'approval_code': 'Autorización ya registrada.'}, {'duplicate': dup['code']})
    nid, code = banking.next_code(c, 'card_vouchers', 'VC')
    stamp = now.isoformat(timespec='seconds')
    c.execute('INSERT INTO card_vouchers(id,code,payment_id,advance_id,cash_session_id,client_id,issuer_bank,acquirer,brand,category,tx_type,months,lot,reference,approval_code,paid_at,amount_cents,last4,file_id,'
              "status,net_cents,note,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'registrada',NULL,?,?,?,?)",
              (nid, code, payment_id, advance_id, session_id, client_id, clean['issuer_bank'], clean['acquirer'], clean['brand'], clean['category'], clean['tx_type'], clean['months'], clean['lot'],
               clean['reference'], clean['approval_code'], clean['paid_at'], amount, clean['last4'], file_id, re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()[:300], user['id'], stamp, stamp))
    _event(c, nid, 'registrada', '%s: %s %s · %s · lote %s · ref. %s · aut. %s · •••• %s · %s%s.' % (code, clean['brand'], clean['issuer_bank'], TYPES[clean['tx_type']], clean['lot'], clean['reference'],
                                                                                                clean['approval_code'], clean['last4'], banking.money(amount), ' (duplicado confirmado)' if dup else ''), user, now)
    return nid


def get(c, vid):
    row = c.execute('SELECT * FROM card_vouchers WHERE id=?', (vid,)).fetchone() if str(vid).isdigit() else None
    if not row:
        raise VoucherError('Voucher no encontrado.', 404)
    return row


def correct(c, vid, data, user, now):
    """Corrección de datos con auditoría (solo administración): conserva el valor anterior en el historial."""
    if user['role'] != 'administrador':
        raise VoucherError('Solo administración corrige un voucher.', 403)
    row = get(c, vid)
    if row['status'] in ('liquidada', 'reversada'):
        raise VoucherError('Un voucher liquidado o reversado no se corrige.', 409)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if len(reason) < 10:
        raise VoucherError('Indica el motivo de la corrección.', 400, {'reason': 'Motivo obligatorio (10 caracteres).'})
    merged = {k: data.get(k, row[k]) for k in EDITABLE}
    merged['last4'] = data.get('last4', row['last4'])
    clean = _clean(c, merged, now)
    changes = [(k, row[k], clean[k]) for k in EDITABLE if str(row[k]) != str(clean[k])]
    if not changes:
        raise VoucherError('No hay cambios que corregir.', 400)
    c.execute('UPDATE card_vouchers SET ' + ','.join(k + '=?' for k, _, _ in changes) + ',updated_at=? WHERE id=?', (*[v for _, _, v in changes], now.isoformat(timespec='seconds'), row['id']))
    _event(c, row['id'], 'corregido', 'Corrección: ' + '; '.join('%s «%s» → «%s»' % (k, old, new) for k, old, new in changes) + '. Motivo: ' + reason, user, now)


def move(c, vid, action, data, user, now):
    if user['role'] != 'administrador':
        raise VoucherError('Solo administración cambia el estado de un voucher.', 403)
    row = get(c, vid)
    if action == 'liquidar':
        if row['status'] not in ('autorizada', 'pendiente_liquidacion', 'registrada'):
            raise VoucherError('Este voucher no se puede liquidar (%s).' % STATUS[row['status']].lower(), 409)
        import cash_sessions
        vals = {}
        for key in ('commission', 'commission_tax', 'withholding'):
            try:
                vals[key] = cash_sessions.cents_of(data.get(key, '0') or '0', key, allow_zero=True)
            except cash_sessions.CashError as error:
                raise VoucherError(str(error), 400, error.fields)
        net = row['amount_cents'] - sum(vals.values())
        if net < 0:
            raise VoucherError('Los descuentos superan el importe del voucher.', 400, {'commission': 'Revisa la comisión.'})
        stamp = now.isoformat(timespec='seconds')
        c.execute("UPDATE card_vouchers SET status='liquidada',commission_cents=?,commission_tax_cents=?,withholding_cents=?,net_cents=?,settled_at=?,updated_at=? WHERE id=?",
                  (vals['commission'], vals['commission_tax'], vals['withholding'], net, stamp, stamp, row['id']))
        _event(c, row['id'], 'liquidada', '%s liquidado: importe %s, comisión %s, IVA de la comisión %s, retenciones %s, neto %s.' % (
            row['code'], banking.money(row['amount_cents']), banking.money(vals['commission']), banking.money(vals['commission_tax']), banking.money(vals['withholding']), banking.money(net)), user, now)
        return
    if action not in MOVES:
        raise VoucherError('Acción no válida.')
    origin, target = MOVES[action]
    if row['status'] not in ((origin,) if isinstance(origin, str) else origin):
        raise VoucherError('Este voucher está %s: no se puede %s.' % (STATUS[row['status']].lower(), action.replace('_', ' ')), 409)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if action in ('reversar', 'rechazar') and len(reason) < 5:
        raise VoucherError('Indica el motivo.', 400, {'reason': 'Motivo obligatorio.'})
    c.execute('UPDATE card_vouchers SET status=?,updated_at=? WHERE id=?', (target, now.isoformat(timespec='seconds'), row['id']))
    _event(c, row['id'], target, '%s → %s%s.' % (row['code'], STATUS[target].lower(), (': ' + reason) if reason else ''), user, now)


def listing(c, f, today):
    where, args = ['1=1'], []
    if f.get('status') in STATUS:
        where.append('v.status=?')
        args.append(f['status'])
    for key, op in (('from', '>='), ('to', '<=')):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(f.get(key, ''))):
            where.append('substr(v.paid_at,1,10)' + op + '?')
            args.append(f[key])
    if f.get('q'):
        where.append("instr(lower(v.code||' '||v.lot||' '||v.reference||' '||v.approval_code||' '||v.brand||' '||v.issuer_bank||' '||COALESCE(k.name,'')),lower(?))>0")
        args.append(str(f['q'])[:60])
    rows = []
    for r in c.execute("SELECT v.*,COALESCE(k.name,'') client,COALESCE(u.name,'') actor,o.code order_code FROM card_vouchers v LEFT JOIN clients k ON k.id=v.client_id LEFT JOIN users u ON u.id=v.created_by "
                       'LEFT JOIN order_payments p ON p.id=v.payment_id LEFT JOIN orders o ON o.id=p.order_id WHERE ' + ' AND '.join(where) + ' ORDER BY v.id DESC LIMIT 500', args):
        expected = expected_commission(c, r['amount_cents'], today)
        rows.append({**{k: r[k] for k in r.keys() if k not in ('note',)}, 'status_label': STATUS[r['status']], 'type_label': TYPES[r['tx_type']], 'client': r['client'], 'actor': r['actor'],
                     'document': r['order_code'] or '', 'expected_commission_cents': expected, 'expected_net_cents': r['amount_cents'] - expected})
    return rows


def events(c, vid):
    return [dict(r) for r in c.execute("SELECT event,detail,actor,created_at FROM payment_events WHERE entity='voucher' AND entity_id=? ORDER BY id DESC", (vid,))]
