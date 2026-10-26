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
             'holder': text('holder', 300), 'holder_id': re.sub(r'\s', '', str(data.get('holder_id', '')))[:20]}
    errors = {}
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


def label(row):
    return '%s · %s · %s' % (row['bank'], TYPES.get(row['account_type'], row['account_type']), row['number'])


def copy_text(row):
    """Texto listo para enviar por WhatsApp o correo (sin datos que no sean de la cuenta)."""
    return '\n'.join(['Datos para depósito o transferencia:', 'Banco: ' + row['bank'], 'Tipo de cuenta: ' + TYPES.get(row['account_type'], row['account_type']),
                      'Número de cuenta: ' + row['number'], 'Titular: ' + row['holder'], 'RUC / identificación: ' + row['holder_id']])


def public(row):
    if not row:
        return None
    data = {k: row[k] for k in ('id', 'bank', 'account_type', 'number', 'holder', 'holder_id', 'active', 'is_default')}
    data.update(type_label=TYPES.get(row['account_type'], row['account_type']), label=label(row), copy_text=copy_text(row))
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
        c.execute('UPDATE bank_accounts SET bank=?,account_type=?,number=?,holder=?,holder_id=?,updated_at=?,updated_by=? WHERE id=?',
                  (clean['bank'], clean['account_type'], clean['number'], clean['holder'], clean['holder_id'], stamp, user['id'], int(account_id)))
        _event(c, int(account_id), 'cuenta_editada', 'Cuenta actualizada: ' + label(clean), user, now)
        return int(account_id)
    new_id = c.execute('INSERT INTO bank_accounts(bank,account_type,number,holder,holder_id,active,is_default,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,1,0,?,?,?,?)',
                       (clean['bank'], clean['account_type'], clean['number'], clean['holder'], clean['holder_id'], stamp, user['id'], stamp, user['id'])).lastrowid
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
