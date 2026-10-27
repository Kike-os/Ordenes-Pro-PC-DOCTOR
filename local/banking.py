"""Cuentas bancarias de la empresa: catálogo central que usan presupuestos, facturas y depósitos de los cierres de caja.

No mueve dinero ni se conecta con ningún banco: solo guarda los datos que la persona registra. Las cuentas no se eliminan (se
desactivan) y cada cambio queda en el historial de caja."""
import re

TYPES = {'corriente': 'Corriente', 'ahorros': 'Ahorros'}


class BankError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def _clean(data):
    text = lambda key, size: re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()[:size]
    clean = {'bank': text('bank', 120), 'account_type': str(data.get('account_type', '')), 'number': re.sub(r'[\s-]', '', str(data.get('number', '')))[:30],
             'holder': text('holder', 300), 'holder_id': re.sub(r'\s', '', str(data.get('holder_id', '')))[:20],
             'email': text('email', 200).lower(), 'notes': text('notes', 300), 'holder_ruc': re.sub(r'\s', '', str(data.get('holder_ruc', '') or ''))[:13]}
    errors = {}
    if clean['email'] and not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+', clean['email']):
        errors['email'] = 'Correo no válido.'
    if clean['holder_ruc']:
        import reception
        problem = reception.document_check(clean['holder_ruc'], 'ruc')[0] if re.fullmatch(r'\d{13}', clean['holder_ruc']) else 'RUC de 13 dígitos.'
        if problem:
            errors['holder_ruc'] = problem
    if len(clean['bank']) < 2:
        errors['bank'] = 'Nombre del banco.'
    if clean['account_type'] not in TYPES:
        errors['account_type'] = 'Elige Corriente o Ahorros.'
    if not re.fullmatch(r'\d{4,30}', clean['number']):
        errors['number'] = 'Solo dígitos (4 a 30).'
    if len(clean['holder']) < 3:
        errors['holder'] = 'Nombre del titular.'
    if not re.fullmatch(r'[A-Za-z0-9]{3,20}', clean['holder_id']):
        errors['holder_id'] = 'RUC o identificación del titular.'
    elif re.fullmatch(r'\d+', clean['holder_id']) and len(clean['holder_id']) in (10, 13):
        import reception
        problem, _ = reception.document_check(clean['holder_id'])
        if problem:
            errors['holder_id'] = problem
    if errors:
        raise BankError('Revisa los datos de la cuenta.', fields=errors)
    return clean


def mask(number):
    """Número de cuenta protegido para listados y reportes: solo los últimos cuatro dígitos."""
    number = str(number or '')
    return '•••• ' + number[-4:] if len(number) > 4 else number


def label(row, masked=False):
    return '%s · %s · %s' % (row['bank'], TYPES.get(row['account_type'], row['account_type']), mask(row['number']) if masked else row['number'])


def copy_text(row):
    """Texto listo para enviar por WhatsApp o correo (sin datos que no sean de la cuenta)."""
    keys = row.keys()
    lines = ['Datos para depósito o transferencia:', 'Banco: ' + row['bank'], 'Tipo de cuenta: ' + TYPES.get(row['account_type'], row['account_type']),
             'Número de cuenta: ' + row['number'], 'Titular: ' + row['holder'], 'Identificación: ' + row['holder_id']]
    if 'holder_ruc' in keys and row['holder_ruc']:
        lines.append('RUC: ' + row['holder_ruc'])
    if 'email' in keys and row['email']:
        lines.append('Envía el comprobante a: ' + row['email'])
    return '\n'.join(lines)


def public(row):
    if not row:
        return None
    data = {k: row[k] for k in ('id', 'bank', 'account_type', 'number', 'holder', 'holder_id', 'active', 'is_default')}
    keys = row.keys()
    data.update({k: row[k] if k in keys else ('' if k != 'verified' else 1) for k in ('email', 'notes', 'holder_ruc', 'verified', 'verified_at')})
    data.update(type_label=TYPES.get(row['account_type'], row['account_type']), label=label(row), masked=mask(row['number']), copy_text=copy_text(row))
    return data


def listing(c, active_only=False):
    rows = c.execute('SELECT * FROM bank_accounts' + (' WHERE active=1' if active_only else '') + ' ORDER BY active DESC,is_default DESC,bank COLLATE NOCASE,number').fetchall()
    return [public(r) for r in rows]


def get(c, account_id, active=False):
    row = c.execute('SELECT * FROM bank_accounts WHERE id=?', (account_id,)).fetchone() if str(account_id).isdigit() else None
    if not row or (active and not row['active']):
        raise BankError('Cuenta bancaria no disponible.' + (' Está inactiva.' if row else ''), 404 if not row else 409)
    return row


def default(c):
    row = c.execute('SELECT * FROM bank_accounts WHERE is_default=1 AND active=1').fetchone()
    return public(row)


def _event(c, account_id, event, detail, user, now):
    c.execute('INSERT INTO cash_events(bank_account_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?)',
              (account_id, event, detail[:500], user['id'], user['name'], now.isoformat(timespec='seconds')))


def save(c, data, user, now):
    """Alta o edición (solo administración). El banco y el número no se repiten."""
    clean = _clean(data)
    stamp = now.isoformat(timespec='seconds')
    account_id = str(data.get('id', '') or '')
    clash = c.execute('SELECT id FROM bank_accounts WHERE lower(bank)=lower(?) AND number=?' + (' AND id!=?' if account_id else ''),
                      (clean['bank'], clean['number'], *([int(account_id)] if account_id else []))).fetchone()
    if clash:
        raise BankError('Ya existe esa cuenta en ese banco.', 409, {'number': 'Cuenta ya registrada.'})
    if account_id:
        get(c, account_id)
        before = get(c, account_id)
        changed = any(str(before[k]) != str(clean[k]) for k in ('bank', 'account_type', 'number', 'holder', 'holder_id', 'holder_ruc'))
        c.execute('UPDATE bank_accounts SET bank=?,account_type=?,number=?,holder=?,holder_id=?,email=?,notes=?,holder_ruc=?,updated_at=?,updated_by=? WHERE id=?',
                  (clean['bank'], clean['account_type'], clean['number'], clean['holder'], clean['holder_id'], clean['email'], clean['notes'], clean['holder_ruc'], stamp, user['id'], int(account_id)))
        if changed and before['verified']:
            # Si cambian los datos del banco o del titular, la cuenta vuelve a requerir verificación antes de usarse en documentos.
            c.execute("UPDATE bank_accounts SET verified=0,verified_at='',verified_by=NULL WHERE id=?", (int(account_id),))
        _event(c, int(account_id), 'cuenta_editada', 'Cuenta actualizada: ' + label(clean), user, now)
        return int(account_id)
    # Quien registra la cuenta desde el formulario la verifica con su documentación; una carga sin verificar se marca con verified='0'.
    verified = 0 if str(data.get('verified', '1')) in ('0', 'false') else 1
    new_id = c.execute('INSERT INTO bank_accounts(bank,account_type,number,holder,holder_id,email,notes,holder_ruc,verified,verified_at,verified_by,active,is_default,created_at,created_by,updated_at,updated_by) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?,1,0,?,?,?,?)',
                       (clean['bank'], clean['account_type'], clean['number'], clean['holder'], clean['holder_id'], clean['email'], clean['notes'], clean['holder_ruc'], verified,
                        stamp if verified else '', user['id'] if verified else None, stamp, user['id'], stamp, user['id'])).lastrowid
    if not c.execute('SELECT 1 FROM bank_accounts WHERE is_default=1').fetchone():
        c.execute('UPDATE bank_accounts SET is_default=1 WHERE id=?', (new_id,))
    _event(c, new_id, 'cuenta_creada', 'Cuenta registrada: ' + label(clean), user, now)
    return new_id


def set_state(c, account_id, active, user, now):
    row = get(c, account_id)
    if not active and row['is_default']:
        c.execute('UPDATE bank_accounts SET is_default=0 WHERE id=?', (row['id'],))
    c.execute('UPDATE bank_accounts SET active=?,updated_at=?,updated_by=? WHERE id=?', (1 if active else 0, now.isoformat(timespec='seconds'), user['id'], row['id']))
    _event(c, row['id'], 'cuenta_activada' if active else 'cuenta_desactivada', ('Activada: ' if active else 'Desactivada: ') + label(row), user, now)


def set_default(c, account_id, user, now):
    row = get(c, account_id, active=True)
    c.execute('UPDATE bank_accounts SET is_default=0 WHERE is_default=1')
    c.execute('UPDATE bank_accounts SET is_default=1 WHERE id=?', (row['id'],))
    _event(c, row['id'], 'cuenta_predeterminada', 'Predeterminada para presupuestos y facturas: ' + label(row), user, now)


def set_verified(c, account_id, user, now):
    """Administración confirma que el banco, el número y el titular coinciden con la documentación bancaria y tributaria."""
    row = get(c, account_id)
    c.execute('UPDATE bank_accounts SET verified=1,verified_at=?,verified_by=?,updated_at=?,updated_by=? WHERE id=?', (now.isoformat(timespec='seconds'), user['id'], now.isoformat(timespec='seconds'), user['id'], row['id']))
    _event(c, row['id'], 'cuenta_verificada', 'Verificada con la documentación bancaria y tributaria: ' + label(row), user, now)


# ---- Transferencias y depósitos recibidos ------------------------------------------------------------------------------------

TRANSFER_STATUS = {'pendiente': 'Pendiente de verificar', 'confirmado': 'Confirmado', 'rechazado': 'Rechazado', 'conciliado': 'Conciliado'}


def when(value, now, field='paid_at'):
    """Fecha y hora del pago (AAAA-MM-DDTHH:MM, hora de Ecuador): no futura ni de hace más de un año. Vacía = ahora."""
    from datetime import datetime, timedelta
    text = str(value or '').strip()
    if not text:
        return now.isoformat(timespec='seconds')
    try:
        moment = datetime.fromisoformat(text[:19])
    except ValueError:
        raise BankError('Fecha y hora no válidas.', fields={field: 'Usa una fecha y hora reales.'})
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=now.tzinfo)
    if moment > now + timedelta(minutes=5):
        raise BankError('La fecha del pago no puede ser futura.', fields={field: 'Fecha futura.'})
    if moment < now - timedelta(days=366):
        raise BankError('La fecha del pago es de hace más de un año.', fields={field: 'Fecha demasiado antigua.'})
    return moment.isoformat(timespec='seconds')


def next_code(c, table, prefix):
    seq = c.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone()
    top = c.execute('SELECT COALESCE(MAX(id),0) FROM ' + table).fetchone()[0]
    nid = max(seq[0] if seq else 0, top) + 1
    return nid, '%s-%06d' % (prefix, nid)


def register_transfer(c, data, user, now, payment_id=None, advance_id=None, file_id=None):
    """Registra una transferencia o depósito recibido. Nace «pendiente de verificar»: subir un comprobante no significa dinero recibido."""
    import sqlite3
    method = str(data.get('method', ''))
    if method not in ('transferencia', 'deposito'):
        raise BankError('Elige transferencia o depósito.', fields={'method': 'Método no válido.'})
    try:
        account = get(c, data.get('bank_account_id'), active=True)
    except BankError:
        raise BankError('Elige la cuenta que recibió el dinero.', fields={'bank_account_id': 'Cuenta no disponible.'})
    reference = re.sub(r'\s+', ' ', str(data.get('reference', '') or '')).strip()
    if not 3 <= len(reference) <= 60:
        raise BankError('Indica el número de depósito o la referencia bancaria.', fields={'reference': 'Entre 3 y 60 caracteres.'})
    amount = data.get('amount_cents')
    if amount is None:
        import cash_sessions
        try:
            amount = cash_sessions.cents_of(data.get('amount', ''))
        except cash_sessions.CashError as error:
            raise BankError(str(error), fields=error.fields)
    paid_at = when(data.get('paid_at', ''), now)
    source_kind = str(data.get('source_kind', '') or '')
    source_id = str(data.get('source_id', '') or '')
    if source_kind not in ('', 'orden', 'factura', 'proforma'):
        raise BankError('Documento relacionado no válido.', fields={'source_kind': 'Opción no válida.'})
    if source_kind:
        table = {'orden': 'orders', 'factura': 'invoices', 'proforma': 'proformas'}[source_kind]
        if not source_id.isdigit() or not c.execute('SELECT 1 FROM ' + table + ' WHERE id=?', (int(source_id),)).fetchone():
            raise BankError('El documento relacionado no existe.', fields={'source_id': 'Documento no encontrado.'})
    client = str(data.get('client_id', '') or '')
    client_id = int(client) if client.isdigit() and c.execute('SELECT 1 FROM clients WHERE id=?', (int(client),)).fetchone() else None
    payer = re.sub(r'\s+', ' ', str(data.get('payer', '') or '')).strip()[:160]
    note = re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()[:300]
    nid, code = next_code(c, 'bank_transfers', 'TR')
    try:
        c.execute('INSERT INTO bank_transfers(id,code,method,bank_account_id,client_id,payer,source_kind,source_id,payment_id,advance_id,reference,amount_cents,paid_at,file_id,note,status,created_by,created_at) '
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pendiente',?,?)",
                  (nid, code, method, account['id'], client_id, payer, source_kind, int(source_id) if source_kind else None, payment_id, advance_id, reference, amount, paid_at, file_id, note,
                   user['id'], now.isoformat(timespec='seconds')))
    except sqlite3.IntegrityError:
        raise BankError('Esa referencia bancaria ya está registrada en la misma cuenta.', 409, {'reference': 'Referencia repetida en esta cuenta.'})
    _payment_event(c, 'transferencia', nid, 'registrada', '%s %s de %s a %s, ref. %s (pendiente de verificar).' % (code, method, money(amount), label(account, True), reference), user, now)
    return nid


def money(cents):
    return ('-' if cents < 0 else '') + '$' + format(abs(cents) // 100, ',').replace(',', '.') + ',%02d' % (abs(cents) % 100)


def _payment_event(c, entity, entity_id, name, detail, user, now):
    c.execute('INSERT INTO payment_events(entity,entity_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?,?)',
              (entity, entity_id, name, detail[:600], user['id'], user['name'], now.isoformat(timespec='seconds')))


def transfer_action(c, transfer_id, action, note, user, now):
    """Verificación autorizada (solo administración): confirmar, rechazar (con motivo) o conciliar con el estado de cuenta."""
    if user['role'] != 'administrador':
        raise BankError('Solo administración verifica transferencias y depósitos.', 403)
    row = c.execute('SELECT * FROM bank_transfers WHERE id=?', (transfer_id,)).fetchone() if str(transfer_id).isdigit() else None
    if not row:
        raise BankError('Transferencia no encontrada.', 404)
    moves = {'confirmar': ('pendiente', 'confirmado'), 'rechazar': ('pendiente', 'rechazado'), 'conciliar': ('confirmado', 'conciliado')}
    if action not in moves:
        raise BankError('Acción no válida.')
    origin, target = moves[action]
    if row['status'] != origin:
        raise BankError('Esta transferencia está %s: no se puede %s.' % (TRANSFER_STATUS[row['status']].lower(), action), 409)
    note = re.sub(r'\s+', ' ', str(note or '')).strip()[:300]
    if action == 'rechazar' and len(note) < 5:
        raise BankError('Indica el motivo del rechazo.', fields={'note': 'Motivo obligatorio.'})
    stamp = now.isoformat(timespec='seconds')
    if action == 'conciliar':
        c.execute("UPDATE bank_transfers SET status='conciliado',reconciled_by=?,reconciled_at=?,status_note=CASE WHEN ?='' THEN status_note ELSE ? END WHERE id=?", (user['id'], stamp, note, note, row['id']))
    else:
        c.execute('UPDATE bank_transfers SET status=?,verified_by=?,verified_at=?,status_note=? WHERE id=?', (target, user['id'], stamp, note, row['id']))
    _payment_event(c, 'transferencia', row['id'], target, '%s %s%s.' % (row['code'], TRANSFER_STATUS[target].lower(), (': ' + note) if note else ''), user, now)


def transfers(c, f):
    """Historial bancario con filtros: banco, cuenta, cliente, fechas, documento, referencia y estado."""
    where, args = ['1=1'], []
    if f.get('bank'):
        where.append('lower(a.bank)=lower(?)')
        args.append(f['bank'])
    if str(f.get('account', '')).isdigit():
        where.append('t.bank_account_id=?')
        args.append(int(f['account']))
    if f.get('status') in TRANSFER_STATUS:
        where.append('t.status=?')
        args.append(f['status'])
    for key, op in (('from', '>='), ('to', '<=')):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(f.get(key, ''))):
            where.append('substr(t.paid_at,1,10)' + op + '?')
            args.append(f[key])
    if f.get('q'):
        where.append("instr(lower(t.code||' '||t.reference||' '||t.payer||' '||COALESCE(k.name,'')||' '||COALESCE(o.code,'')||' '||COALESCE(f.code,'')),lower(?))>0")
        args.append(str(f['q'])[:60])
    rows = []
    for r in c.execute("SELECT t.*,a.bank,a.account_type,a.number,a.holder,COALESCE(k.name,'') client,COALESCE(u.name,'') actor,COALESCE(v.name,'') verifier,o.code order_code,f.code proforma_code "
                       'FROM bank_transfers t JOIN bank_accounts a ON a.id=t.bank_account_id LEFT JOIN clients k ON k.id=t.client_id LEFT JOIN users u ON u.id=t.created_by LEFT JOIN users v ON v.id=t.verified_by '
                       "LEFT JOIN orders o ON o.id=CASE WHEN t.source_kind='orden' THEN t.source_id END LEFT JOIN proformas f ON f.id=CASE WHEN t.source_kind='proforma' THEN t.source_id END "
                       'WHERE ' + ' AND '.join(where) + ' ORDER BY t.paid_at DESC,t.id DESC LIMIT 500', args):
        document = r['order_code'] or r['proforma_code'] or (('Factura #%d' % r['source_id']) if r['source_kind'] == 'factura' else '')
        rows.append({'id': r['id'], 'code': r['code'], 'method': r['method'], 'bank': r['bank'], 'account': '%s · %s' % (TYPES.get(r['account_type'], r['account_type']), mask(r['number'])),
                     'holder': r['holder'], 'client': r['client'] or r['payer'], 'document': document, 'reference': r['reference'], 'amount_cents': r['amount_cents'], 'paid_at': r['paid_at'],
                     'has_file': bool(r['file_id']), 'actor': r['actor'], 'status': r['status'], 'status_label': TRANSFER_STATUS[r['status']], 'status_note': r['status_note'],
                     'verifier': r['verifier'], 'payment_id': r['payment_id'], 'advance_id': r['advance_id']})
    return rows


def indicators(c, f):
    """Indicadores del Centro bancario: cuentas, verificaciones pendientes, confirmadas y total recibido por banco en el período."""
    period = []
    args = []
    for key, op in (('from', '>='), ('to', '<=')):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(f.get(key, ''))):
            period.append('substr(t.paid_at,1,10)' + op + '?')
            args.append(f[key])
    cond = (' AND ' + ' AND '.join(period)) if period else ''
    by_bank = [{'bank': r['bank'], 'cents': r['cents'], 'count': r['n']} for r in c.execute(
        "SELECT a.bank,COALESCE(SUM(t.amount_cents),0) cents,COUNT(*) n FROM bank_transfers t JOIN bank_accounts a ON a.id=t.bank_account_id WHERE t.status IN ('confirmado','conciliado')" + cond
        + ' GROUP BY a.bank ORDER BY cents DESC', args)]
    return {'accounts': c.execute('SELECT COUNT(*) FROM bank_accounts').fetchone()[0], 'active': c.execute('SELECT COUNT(*) FROM bank_accounts WHERE active=1').fetchone()[0],
            'unverified_accounts': c.execute('SELECT COUNT(*) FROM bank_accounts WHERE verified=0 AND active=1').fetchone()[0],
            'pending': c.execute("SELECT COUNT(*) FROM bank_transfers t WHERE t.status='pendiente'" + cond, args).fetchone()[0],
            'confirmed': c.execute("SELECT COUNT(*) FROM bank_transfers t WHERE t.status IN ('confirmado','conciliado')" + cond, args).fetchone()[0],
            'by_bank': by_bank, 'received_cents': sum(b['cents'] for b in by_bank)}
