"""Cierre de caja diario por usuario y depósitos del efectivo en las cuentas bancarias del catálogo.

- Cada persona cierra SU caja de un día (fecha de Ecuador): los cobros que registró ese día, por forma de pago, en órdenes y licencias.
- El cierre guarda una foto de esos cobros y no se modifica. Si después se registra otro cobro ese día, se avisa (no se cambia el cierre).
- Un depósito nace «pendiente»; pasa a «depositado» solo cuando la persona lo confirma (fecha, comprobante y archivo) y a
  «conciliado» solo por administración. El mismo comprobante no se repite en la misma cuenta. Nada mueve dinero real."""
import base64
import hashlib
import json
import re
import secrets
from datetime import date

import banking

METHODS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia', 'deposito': 'Depósito', 'tarjeta': 'Tarjeta', 'otro': 'Otro'}
DEPOSIT_STATUS = {'pendiente': 'Pendiente de depósito', 'depositado': 'Depositado', 'conciliado': 'Conciliado', 'anulado': 'Anulado'}
FILE_LIMIT = 5 * 1024 * 1024
FILE_TYPES = {'image/jpeg': (b'\xff\xd8\xff',), 'image/png': (b'\x89PNG\r\n\x1a\n',), 'application/pdf': (b'%PDF-',)}
PART_LIMIT = 1_500_000  # caracteres Base64 por parte: cada petición queda muy por debajo del límite de la plataforma


class CashError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def usd(cents):
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return sign + '$' + format(cents // 100, ',').replace(',', '.') + ',%02d' % (cents % 100)


def _day(value, now):
    try:
        day = date.fromisoformat(str(value or now.date().isoformat()))
    except ValueError:
        raise CashError('Fecha no válida.', fields={'day': 'Fecha no válida.'})
    if day > now.date():
        raise CashError('No se puede cerrar una caja de un día futuro.', fields={'day': 'Fecha futura.'})
    return day.isoformat()


def movements(c, user_id, day):
    """Cobros que registró la persona ese día: pagos y devoluciones de órdenes (no anulados) y pagos confirmados de licencias."""
    rows = []
    for r in c.execute("SELECT p.id,p.amount_cents,p.kind,p.method,p.created_at,o.code FROM order_payments p JOIN orders o ON o.id=p.order_id "
                       "WHERE p.created_by=? AND substr(p.created_at,1,10)=? AND p.voided_at IS NULL ORDER BY p.created_at", (user_id, day)):
        rows.append({'source': 'orden', 'id': r['id'], 'reference': r['code'], 'method': r['method'], 'kind': r['kind'],
                     'amount_cents': -r['amount_cents'] if r['kind'] == 'devolucion' else r['amount_cents'], 'at': r['created_at']})
    for r in c.execute("SELECT p.id,p.amount_cents,p.method,p.created_at,s.code FROM license_sale_payments p JOIN license_sales s ON s.id=p.sale_id "
                       "WHERE p.created_by=? AND substr(p.created_at,1,10)=? AND p.status='confirmado' ORDER BY p.created_at", (user_id, day)):
        rows.append({'source': 'licencia', 'id': r['id'], 'reference': r['code'], 'method': r['method'], 'kind': 'pago', 'amount_cents': r['amount_cents'], 'at': r['created_at']})
    return sorted(rows, key=lambda r: r['at'])


def totals(rows):
    by = {}
    for r in rows:
        by[r['method']] = by.get(r['method'], 0) + r['amount_cents']
    return {'by_method': by, 'total_cents': sum(by.values()), 'cash_cents': by.get('efectivo', 0), 'count': len(rows)}


def _event(c, closing_id, deposit_id, event, detail, user, now):
    c.execute('INSERT INTO cash_events(closing_id,deposit_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?,?)',
              (closing_id, deposit_id, event, detail[:500], user['id'], user['name'], now.isoformat(timespec='seconds')))


def _can_see(user, owner_id):
    return user['role'] == 'administrador' or user['id'] == owner_id


def day_view(c, user, owner_id, day, now):
    """Caja de una persona en un día: cobros en vivo, cierre (si existe), depósitos y avisos."""
    if not _can_see(user, owner_id):
        raise CashError('Solo puedes ver tu propia caja.', 403)
    day = _day(day, now)
    live = movements(c, owner_id, day)
    closing = c.execute('SELECT * FROM cash_closings WHERE user_id=? AND day=?', (owner_id, day)).fetchone()
    person = c.execute('SELECT id,name FROM users WHERE id=?', (owner_id,)).fetchone()
    out = {'day': day, 'user': {'id': person['id'], 'name': person['name']} if person else None, 'live': {'movements': live, **totals(live)}, 'methods': METHODS,
           'closing': None, 'deposits': [], 'accounts': banking.listing(c, active_only=True), 'can_reconcile': user['role'] == 'administrador',
           'can_close': user['id'] == owner_id}
    if closing:
        snap = json.loads(closing['movements'])
        known = {(m['source'], m['id']) for m in snap}
        late = [m for m in live if (m['source'], m['id']) not in known]
        out['closing'] = {'id': closing['id'], 'expected_cash_cents': closing['expected_cash_cents'], 'counted_cash_cents': closing['counted_cash_cents'],
                          'difference_cents': closing['difference_cents'], 'totals': json.loads(closing['totals']), 'movements': snap, 'notes': closing['notes'],
                          'closed_at': closing['closed_at'], 'late_movements': late}
        out['deposits'] = deposits(c, closing['id'])
        live_deposits = sum(d['amount_cents'] for d in out['deposits'] if d['status'] != 'anulado')
        out['closing']['deposited_cents'] = live_deposits
        out['closing']['to_deposit_cents'] = max(0, closing['counted_cash_cents'] - live_deposits)
    return out


def close(c, user, day, data, now):
    """Cierra la caja propia de un día. Una sola vez por persona y día; guarda la foto de los cobros."""
    day = _day(day, now)
    if c.execute('SELECT 1 FROM cash_closings WHERE user_id=? AND day=?', (user['id'], day)).fetchone():
        raise CashError('Tu caja de ese día ya está cerrada.', 409)
    try:
        counted = _cents(data.get('counted_cash', ''))
    except CashError:
        raise CashError('Indica el efectivo contado.', fields={'counted_cash': 'Importe no válido.'})
    rows = movements(c, user['id'], day)
    t = totals(rows)
    notes = re.sub(r'\s+', ' ', str(data.get('notes', ''))).strip()[:500]
    if counted != t['cash_cents'] and len(notes) < 5:
        raise CashError('El efectivo contado no coincide con el esperado: explica la diferencia en las observaciones.', fields={'notes': 'Explica la diferencia.'})
    closing_id = c.execute('INSERT INTO cash_closings(user_id,day,expected_cash_cents,counted_cash_cents,difference_cents,totals,movements,notes,closed_at,closed_by) VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (user['id'], day, t['cash_cents'], counted, counted - t['cash_cents'], json.dumps(t, ensure_ascii=False), json.dumps(rows, ensure_ascii=False), notes,
                            now.isoformat(timespec='seconds'), user['id'])).lastrowid
    _event(c, closing_id, None, 'caja_cerrada', 'Caja del %s cerrada: %d cobros, efectivo esperado %s, contado %s (diferencia %s).' % (day, t['count'], usd(t['cash_cents']), usd(counted), usd(counted - t['cash_cents'])), user, now)
    return closing_id


def _cents(value):
    text = str(value or '').strip().replace('$', '').replace(' ', '')
    if re.fullmatch(r'\d{1,3}(\.\d{3})+(,\d{1,2})?|\d+(,\d{1,2})?', text):
        text = text.replace('.', '').replace(',', '.')
    elif not re.fullmatch(r'\d+(\.\d{1,2})?', text):
        raise CashError('Importe no válido.')
    whole, _, frac = text.partition('.')
    cents = int(whole) * 100 + int((frac + '00')[:2])
    if cents > 100_000_000:
        raise CashError('Importe no válido.')
    return cents


def _closing(c, closing_id):
    row = c.execute('SELECT * FROM cash_closings WHERE id=?', (closing_id,)).fetchone()
    if not row:
        raise CashError('Cierre no encontrado.', 404)
    return row


def deposits(c, closing_id):
    rows = c.execute('SELECT d.*,f.name file_name,f.size file_size,f.mime file_mime,u.name created_name,r.name reconciled_name FROM cash_deposits d LEFT JOIN cash_deposit_files f ON f.deposit_id=d.id '
                     'LEFT JOIN users u ON u.id=d.created_by LEFT JOIN users r ON r.id=d.reconciled_by WHERE d.closing_id=? ORDER BY d.id', (closing_id,)).fetchall()
    out = []
    for r in rows:
        account = c.execute('SELECT * FROM bank_accounts WHERE id=?', (r['bank_account_id'],)).fetchone()
        out.append({'id': r['id'], 'amount_cents': r['amount_cents'], 'status': r['status'], 'status_label': DEPOSIT_STATUS[r['status']], 'deposit_date': r['deposit_date'],
                    'voucher_number': r['voucher_number'], 'notes': r['notes'], 'account': banking.public(account), 'file': {'name': r['file_name'], 'size': r['file_size'], 'mime': r['file_mime']} if r['file_name'] else None,
                    'created_at': r['created_at'], 'created_by': r['created_name'] or '', 'deposited_at': r['deposited_at'], 'reconciled_at': r['reconciled_at'],
                    'reconciled_by': r['reconciled_name'] or '', 'voided_at': r['voided_at'], 'void_reason': r['void_reason']})
    return out


def add_deposit(c, user, closing_id, data, now):
    """Registra un depósito PENDIENTE del efectivo de un cierre (no lo da por realizado). No supera el efectivo contado."""
    closing = _closing(c, closing_id)
    if not _can_see(user, closing['user_id']):
        raise CashError('Solo puedes registrar depósitos de tu propia caja.', 403)
    account = banking.get(c, data.get('bank_account_id'), active=True)
    try:
        amount = _cents(data.get('amount', ''))
    except CashError:
        raise CashError('Indica el monto a depositar.', fields={'amount': 'Importe no válido.'})
    if amount <= 0:
        raise CashError('El monto debe ser mayor que cero.', fields={'amount': 'Mayor que cero.'})
    key = str(data.get('request_key', '') or '')[:64] or None
    if key and c.execute('SELECT id FROM cash_deposits WHERE request_key=?', (key,)).fetchone():
        return c.execute('SELECT id FROM cash_deposits WHERE request_key=?', (key,)).fetchone()[0]  # reintento: no se duplica
    used = c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM cash_deposits WHERE closing_id=? AND status!='anulado'", (closing_id,)).fetchone()[0]
    if used + amount > closing['counted_cash_cents']:
        raise CashError('Los depósitos (%s) superarían el efectivo contado del cierre (%s).' % (usd(used + amount), usd(closing['counted_cash_cents'])), 409, {'amount': 'Supera el efectivo del cierre.'})
    deposit_id = c.execute('INSERT INTO cash_deposits(closing_id,bank_account_id,amount_cents,status,notes,request_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                           (closing_id, account['id'], amount, 'pendiente', re.sub(r'\s+', ' ', str(data.get('notes', ''))).strip()[:300], key, user['id'], now.isoformat(timespec='seconds'))).lastrowid
    _event(c, closing_id, deposit_id, 'deposito_pendiente', 'Depósito pendiente de %s en %s.' % (usd(amount), banking.label(account)), user, now)
    return deposit_id


def _deposit(c, deposit_id):
    row = c.execute('SELECT d.*,k.user_id owner FROM cash_deposits d JOIN cash_closings k ON k.id=d.closing_id WHERE d.id=?', (deposit_id,)).fetchone()
    if not row:
        raise CashError('Depósito no encontrado.', 404)
    return row


def upload_part(c, user, data, now):
    """Recibe una parte de un archivo. Devuelve el identificador de subida; el archivo se recompone al confirmar el depósito."""
    upload_id = str(data.get('upload_id', '') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', upload_id):
        upload_id = secrets.token_urlsafe(18)
    try:
        part, total = int(data.get('part', -1)), int(data.get('total', 0))
    except (TypeError, ValueError):
        raise CashError('Parte no válida.')
    chunk = str(data.get('data', ''))
    if not 0 <= part < total <= 20 or not chunk or len(chunk) > PART_LIMIT or not re.fullmatch(r'[A-Za-z0-9+/=]+', chunk):
        raise CashError('Parte no válida.')
    owner = c.execute('SELECT created_by FROM cash_upload_parts WHERE upload_id=? LIMIT 1', (upload_id,)).fetchone()
    if owner and owner[0] != user['id']:
        raise CashError('Subida no válida.', 403)
    c.execute('INSERT OR REPLACE INTO cash_upload_parts(upload_id,part,total,data,created_by,created_at) VALUES (?,?,?,?,?,?)', (upload_id, part, total, chunk, user['id'], now.isoformat(timespec='seconds')))
    return upload_id


def _assemble(c, user, upload_id, name):
    rows = c.execute('SELECT part,total,data,created_by FROM cash_upload_parts WHERE upload_id=? ORDER BY part', (upload_id,)).fetchall()
    if not rows or any(r['created_by'] != user['id'] for r in rows) or len(rows) != rows[0]['total'] or [r['part'] for r in rows] != list(range(rows[0]['total'])):
        raise CashError('El archivo no llegó completo. Vuelve a adjuntarlo.', 409, {'file': 'Archivo incompleto.'})
    try:
        raw = base64.b64decode(''.join(r['data'] for r in rows), validate=True)
    except ValueError:
        raise CashError('El archivo no es válido.', fields={'file': 'Archivo no válido.'})
    if not raw or len(raw) > FILE_LIMIT:
        raise CashError('El comprobante debe pesar hasta 5 MB.', fields={'file': 'Máximo 5 MB.'})
    mime = next((kind for kind, heads in FILE_TYPES.items() if any(raw.startswith(h) for h in heads)), None)
    if not mime:
        raise CashError('Solo se aceptan comprobantes JPG, PNG o PDF.', fields={'file': 'Formato no admitido.'})
    clean_name = re.sub(r'[^\w.\- ()]', '_', str(name or 'comprobante'))[:120] or 'comprobante'
    return raw, mime, clean_name


def confirm_deposit(c, user, deposit_id, data, now):
    """La persona confirma que depositó: fecha, número de comprobante y archivo. Solo entonces queda «depositado»."""
    dep = _deposit(c, deposit_id)
    if not _can_see(user, dep['owner']):
        raise CashError('Solo puedes confirmar depósitos de tu propia caja.', 403)
    if dep['status'] != 'pendiente':
        raise CashError('Este depósito no está pendiente.', 409)
    errors = {}
    try:
        when = date.fromisoformat(str(data.get('deposit_date', '')))
        if when > now.date():
            errors['deposit_date'] = 'La fecha no puede ser futura.'
    except ValueError:
        errors['deposit_date'] = 'Fecha del depósito.'
    voucher = re.sub(r'\s', '', str(data.get('voucher_number', '')))[:40]
    if not re.fullmatch(r'[A-Za-z0-9-]{3,40}', voucher):
        errors['voucher_number'] = 'Número del comprobante bancario.'
    if not data.get('upload_id'):
        errors['file'] = 'Adjunta la foto o el archivo del comprobante.'
    if errors:
        raise CashError('Completa los datos del depósito.', fields=errors)
    if c.execute("SELECT 1 FROM cash_deposits WHERE bank_account_id=? AND voucher_number=? AND status!='anulado' AND id!=?", (dep['bank_account_id'], voucher, deposit_id)).fetchone():
        raise CashError('Ese comprobante ya está registrado en esta cuenta.', 409, {'voucher_number': 'Comprobante duplicado.'})
    raw, mime, name = _assemble(c, user, str(data.get('upload_id')), data.get('file_name'))
    stamp = now.isoformat(timespec='seconds')
    c.execute('INSERT INTO cash_deposit_files(deposit_id,name,mime,size,sha256,data,created_at,created_by) VALUES (?,?,?,?,?,?,?,?)',
              (deposit_id, name, mime, len(raw), hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode(), stamp, user['id']))
    c.execute('DELETE FROM cash_upload_parts WHERE upload_id=?', (str(data.get('upload_id')),))
    c.execute("UPDATE cash_deposits SET status='depositado',deposit_date=?,voucher_number=?,deposited_by=?,deposited_at=? WHERE id=?", (when.isoformat(), voucher, user['id'], stamp, deposit_id))
    _event(c, dep['closing_id'], deposit_id, 'deposito_confirmado', 'Depósito de %s confirmado: comprobante %s del %s (%s, %s KB).' % (usd(dep['amount_cents']), voucher, when.isoformat(), name, len(raw) // 1024), user, now)


def reconcile(c, user, deposit_id, now):
    if user['role'] != 'administrador':
        raise CashError('Solo administración concilia depósitos.', 403)
    dep = _deposit(c, deposit_id)
    if dep['status'] != 'depositado':
        raise CashError('Solo se concilia un depósito confirmado.', 409)
    c.execute("UPDATE cash_deposits SET status='conciliado',reconciled_by=?,reconciled_at=? WHERE id=?", (user['id'], now.isoformat(timespec='seconds'), deposit_id))
    _event(c, dep['closing_id'], deposit_id, 'deposito_conciliado', 'Depósito de %s conciliado con el extracto bancario.' % usd(dep['amount_cents']), user, now)


def void(c, user, deposit_id, reason, now):
    """Anula un depósito pendiente (la persona o administración) o uno confirmado (solo administración). Un conciliado no se anula."""
    dep = _deposit(c, deposit_id)
    if not _can_see(user, dep['owner']):
        raise CashError('Solo puedes anular depósitos de tu propia caja.', 403)
    if dep['status'] == 'depositado' and user['role'] != 'administrador':
        raise CashError('Un depósito confirmado solo lo anula administración.', 403)
    if dep['status'] not in ('pendiente', 'depositado'):
        raise CashError('Este depósito no se puede anular.', 409)
    reason = re.sub(r'\s+', ' ', str(reason or '')).strip()[:300]
    if len(reason) < 5:
        raise CashError('Indica el motivo de la anulación.', fields={'reason': 'Motivo obligatorio.'})
    c.execute("UPDATE cash_deposits SET status='anulado',voided_by=?,voided_at=?,void_reason=? WHERE id=?", (user['id'], now.isoformat(timespec='seconds'), reason, deposit_id))
    _event(c, dep['closing_id'], deposit_id, 'deposito_anulado', 'Depósito de %s anulado: %s' % (usd(dep['amount_cents']), reason), user, now)


def file_of(c, user, deposit_id):
    dep = _deposit(c, deposit_id)
    if not _can_see(user, dep['owner']):
        raise CashError('No disponible.', 403)
    row = c.execute('SELECT name,mime,data FROM cash_deposit_files WHERE deposit_id=?', (deposit_id,)).fetchone()
    if not row:
        raise CashError('Este depósito no tiene comprobante.', 404)
    return row['name'], row['mime'], base64.b64decode(row['data'])


def history(c, user, owner_id='', status='', frm='', to=''):
    """Cierres con sus depósitos. Cada persona ve los suyos; administración ve los de todos y puede filtrar."""
    where, args = ['1=1'], []
    if user['role'] != 'administrador':
        where.append('k.user_id=?')
        args.append(user['id'])
    elif str(owner_id).isdigit():
        where.append('k.user_id=?')
        args.append(int(owner_id))
    for value, sql in ((frm, 'k.day>=?'), (to, 'k.day<=?')):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(value or '')):
            where.append(sql)
            args.append(value)
    if status in DEPOSIT_STATUS:
        where.append('EXISTS (SELECT 1 FROM cash_deposits d WHERE d.closing_id=k.id AND d.status=?)')
        args.append(status)
    rows = c.execute('SELECT k.*,u.name person FROM cash_closings k JOIN users u ON u.id=k.user_id WHERE ' + ' AND '.join(where) + ' ORDER BY k.day DESC,k.id DESC LIMIT 200', args).fetchall()
    out = []
    for r in rows:
        deps = deposits(c, r['id'])
        out.append({'id': r['id'], 'day': r['day'], 'person': r['person'], 'user_id': r['user_id'], 'expected_cash_cents': r['expected_cash_cents'], 'counted_cash_cents': r['counted_cash_cents'],
                    'difference_cents': r['difference_cents'], 'closed_at': r['closed_at'], 'deposits': deps,
                    'deposit_summary': {s: sum(d['amount_cents'] for d in deps if d['status'] == s) for s in DEPOSIT_STATUS}})
    people = [{'id': r['id'], 'name': r['name']} for r in c.execute("SELECT id,name FROM users WHERE approval='approved' AND active=1 ORDER BY name")] if user['role'] == 'administrador' else []
    return {'rows': out, 'people': people, 'statuses': DEPOSIT_STATUS}


def events(c, closing_id):
    return [dict(r) for r in c.execute('SELECT event,detail,actor,created_at,deposit_id FROM cash_events WHERE closing_id=? ORDER BY id DESC', (closing_id,))]
