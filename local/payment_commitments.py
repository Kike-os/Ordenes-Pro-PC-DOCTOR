"""ADI 3.0 · fase 2: compromisos de pago (docs/ADI-COMPROMISOS.md).

Un compromiso registra lo que el cliente ACEPTÓ (importe, fecha acordada, forma de pago y evidencia de cómo lo aceptó). No cambia la orden,
los pagos, los saldos, las facturas ni los vencimientos: su cumplimiento se CALCULA con los pagos confirmados de la orden desde que se
registró. Una transferencia por conciliar nunca convierte un compromiso en incumplido: lo deja en revisión.

Reglas: solo con un saldo pendiente confirmado; importe hasta ese saldo; fecha acordada desde hoy y hasta 180 días; más de 30 días exige
administración (modifica las condiciones económicas); un solo compromiso vigente por orden; reprogramar crea uno nuevo enlazado y exige
evidencia del cliente; cancelar es solo de administración y con motivo. ADI puede pedir una fecha estimada, pero no aprueba acuerdos,
descuentos ni condonaciones. Si la migración 119 no está aplicada, el módulo queda inactivo y lo demás funciona igual."""
import re
from datetime import date, timedelta

STATES = {'pendiente': 'Pendiente', 'proximo': 'Próximo a vencer', 'cumplido': 'Cumplido', 'parcial': 'Cumplido parcialmente', 'incumplido': 'Incumplido',
          'reprogramado': 'Reprogramado', 'cancelado': 'Cancelado', 'en_revision': 'En revisión'}
OPEN = ('pendiente', 'proximo', 'en_revision')          # vigentes: impiden otro compromiso y los recordatorios de saldo
SOURCES = {'presencial': 'En persona', 'telefono': 'Por llamada', 'mensaje': 'Por mensaje escrito', 'correo': 'Por correo', 'whatsapp': 'Por WhatsApp'}
METHODS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia', 'deposito': 'Depósito', 'tarjeta': 'Tarjeta', 'otro': 'Otra forma acordada'}
SOON_DAYS = 3
FREE_DAYS = 30          # hasta aquí lo registra el personal; más lejos, administración
MAX_DAYS = 180
NOT_INSTALLED = 'Los compromisos de pago necesitan la migración 119 (Sistema → Migraciones). Mientras tanto no se registran.'


class CommitmentError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_commitments'").fetchone())


def _day(value):
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def _fmt(value):
    d = _day(value)
    return d.strftime('%d/%m/%Y') if d else ''


def usd(cents):
    import status_messages
    return status_messages.usd(cents)


def _text(data, key, low, high, label):
    value = re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()
    if not low <= len(value) <= high:
        raise CommitmentError('%s: entre %d y %d caracteres.' % (label, low, high), 400, {key: label + ' obligatorio.' if low else label + ' demasiado largo.'})
    return value


def _paid_since(c, order_id, since):
    """Pagos confirmados (sin anular y sin transferencias por conciliar) desde `since`, y si hay transferencias por conciliar."""
    import equipment
    paid, pending = 0, False
    for p in equipment.payments(c, order_id):
        if p.get('voided_at') or p.get('kind') not in ('pago', 'asignacion') or str(p['created_at']) < since:
            continue
        if p.get('transfer_status') == 'pendiente':
            pending = True
        else:
            paid += int(p['amount_cents'] or 0)
    return paid, pending


def state(c, row, today, balance_cents=None):
    """Estado calculado del compromiso con los pagos registrados (no se guarda: cambia solo cuando cambian los pagos)."""
    if row['status'] in ('reprogramado', 'cancelado', 'en_revision'):
        return row['status'], 0, False
    paid, pending = _paid_since(c, row['order_id'], row['committed_at'])
    if balance_cents is None:
        balance_cents = _balance(c, row['order_id'])
    due = _day(row['due_date'])
    if paid >= row['amount_cents'] or (balance_cents is not None and balance_cents <= 0 and not pending):
        return 'cumplido', paid, pending
    if pending and balance_cents is not None and balance_cents <= 0:
        return 'en_revision', paid, pending           # cubierto solo con una transferencia por conciliar: se confirma en Caja
    if due and today > due:
        if pending:
            return 'en_revision', paid, pending       # transferencia por conciliar: no se declara incumplido
        return ('parcial' if paid else 'incumplido'), paid, pending
    if due and (due - today).days <= SOON_DAYS:
        return 'proximo', paid, pending
    return 'pendiente', paid, pending


def _balance(c, order_id):
    import status_messages
    fin = status_messages.finance(c, order_id)
    return fin['balance_cents'] if fin else None


def _out(c, row, today, balance_cents=None):
    st, paid, pending = state(c, row, today, balance_cents)
    return {'id': row['id'], 'order_id': row['order_id'], 'amount_cents': row['amount_cents'], 'amount': usd(row['amount_cents']),
            'balance_at': usd(row['balance_cents']), 'committed_at': row['committed_at'], 'due_date': row['due_date'], 'due': _fmt(row['due_date']),
            'method': row['method'], 'method_label': METHODS.get(row['method'], ''), 'notes': row['notes'], 'evidence': row['evidence'],
            'evidence_source': SOURCES.get(row['evidence_source'], row['evidence_source']), 'state': st, 'state_label': STATES[st],
            'paid_since_cents': paid, 'paid_since': usd(paid), 'pending_transfer': pending, 'replaces_id': row['replaces_id'],
            'approved': bool(row['approved_by']), 'days_left': (_day(row['due_date']) - today).days if _day(row['due_date']) else None}


def for_order(c, order_id, today):
    if not installed(c):
        return {'installed': False, 'items': [], 'current': None, 'message': NOT_INSTALLED}
    balance = _balance(c, order_id)
    items = [_out(c, r, today, balance) for r in c.execute('SELECT * FROM payment_commitments WHERE order_id=? ORDER BY id DESC', (order_id,))]
    current = next((i for i in items if i['state'] not in ('reprogramado', 'cancelado')), None)
    return {'installed': True, 'items': items, 'current': current, 'message': ''}


def events(c, commitment_id):
    return [dict(r) for r in c.execute('SELECT e.kind,e.detail,e.created_at,COALESCE(u.name,\'\') user FROM payment_commitment_events e LEFT JOIN users u ON u.id=e.user_id '
                                       'WHERE e.commitment_id=? ORDER BY e.id', (commitment_id,))]


def _event(c, cid, kind, detail, user, now):
    c.execute('INSERT INTO payment_commitment_events(commitment_id,kind,detail,user_id,created_at) VALUES (?,?,?,?,?)',
              (cid, kind, detail[:400], user['id'], now.isoformat(timespec='seconds')))


def _validate(c, order_id, data, user, now):
    import equipment
    import status_messages
    fin = status_messages.finance(c, order_id)
    if not fin:
        raise CommitmentError(status_messages.UNVERIFIED, 409)
    if fin['balance_cents'] <= 0:
        raise CommitmentError('La orden no registra un saldo pendiente confirmado: no corresponde un compromiso de pago.', 409)
    amount = equipment.cents_of(str(data.get('amount', '') or ''))
    if not amount:
        raise CommitmentError('Indica el importe comprometido.', 400, {'amount': 'Importe obligatorio.'})
    if amount > fin['balance_cents']:
        raise CommitmentError('El importe no puede superar el saldo pendiente (%s).' % fin['balance'], 400, {'amount': 'Hasta %s.' % fin['balance']})
    due = _day(data.get('due_date'))
    today = now.date()
    if not due or due < today or due > today + timedelta(days=MAX_DAYS):
        raise CommitmentError('Indica la fecha acordada (desde hoy y hasta %d días).' % MAX_DAYS, 400, {'due_date': 'Fecha no válida.'})
    if due > today + timedelta(days=FREE_DAYS) and user['role'] != 'administrador':
        raise CommitmentError('Un plazo de más de %d días cambia las condiciones económicas: lo registra administración.' % FREE_DAYS, 403, {'due_date': 'Requiere administración.'})
    method = str(data.get('method', '') or '')
    if method and method not in METHODS:
        raise CommitmentError('Forma de pago no válida.', 400, {'method': 'No válida.'})
    source = str(data.get('evidence_source', '') or '')
    if source not in SOURCES:
        raise CommitmentError('Indica cómo aceptó el cliente el compromiso.', 400, {'evidence_source': 'Obligatorio.'})
    evidence = _text(data, 'evidence', 10, 300, 'Evidencia de aceptación del cliente')
    notes = _text(data, 'notes', 0, 300, 'Observaciones')
    return fin, amount, due, method, source, evidence, notes


def _insert(c, order_id, user, now, fin, amount, due, method, source, evidence, notes, replaces=None):
    client = c.execute('SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?', (order_id,)).fetchone()
    invoice = c.execute("SELECT id FROM invoices WHERE order_id=? AND status NOT IN ('borrador','descartado') ORDER BY id DESC LIMIT 1", (order_id,)).fetchone() \
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoices'").fetchone() else None
    approved = user['id'] if due > now.date() + timedelta(days=FREE_DAYS) else None
    return c.execute('INSERT INTO payment_commitments(client_id,order_id,invoice_id,balance_cents,amount_cents,committed_at,due_date,method,notes,evidence,evidence_source,'
                     'status,replaces_id,approved_by,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (client['client_id'], order_id, invoice['id'] if invoice else None, fin['balance_cents'], amount, now.isoformat(timespec='seconds'), due.isoformat(),
                      method, notes, evidence, source, 'activo', replaces, approved, user['id'], now.isoformat(timespec='seconds'))).lastrowid


def _row(c, order_id, cid):
    row = c.execute('SELECT * FROM payment_commitments WHERE id=? AND order_id=?', (cid, order_id)).fetchone()
    if not row:
        raise CommitmentError('Compromiso no encontrado.', 404)
    return row


def act(c, order_id, user, data, now, audit):
    """create | reschedule | cancel | review | close_review. Nada de esto registra pagos ni cambia saldos."""
    if not installed(c):
        raise CommitmentError(NOT_INSTALLED, 409)
    if user['role'] not in ('administrador', 'tecnico'):
        raise CommitmentError('Acceso no permitido.', 403)
    action = str(data.get('action', ''))
    today = now.date()
    if action == 'create':
        current = for_order(c, order_id, today)['current']
        if current and current['state'] in OPEN:
            raise CommitmentError('Ya hay un compromiso vigente (%s, hasta el %s). Reprográmalo o espera a que se cumpla.' % (current['amount'], current['due']), 409)
        fin, amount, due, method, source, evidence, notes = _validate(c, order_id, data, user, now)
        cid = _insert(c, order_id, user, now, fin, amount, due, method, source, evidence, notes)
        _event(c, cid, 'registrado', '%s hasta el %s · %s: %s' % (usd(amount), due.strftime('%d/%m/%Y'), SOURCES[source], evidence), user, now)
        audit(c, user['id'], 'payment_commitment_created', order_id)
        return cid
    cid = int(data.get('id') or 0)
    row = _row(c, order_id, cid)
    if action == 'reschedule':
        st = state(c, row, today)[0]
        if st in ('cumplido', 'cancelado', 'reprogramado'):
            raise CommitmentError('Este compromiso ya no se puede reprogramar (%s).' % STATES[st], 409)
        fin, amount, due, method, source, evidence, notes = _validate(c, order_id, data, user, now)
        c.execute("UPDATE payment_commitments SET status='reprogramado',updated_at=? WHERE id=?", (now.isoformat(timespec='seconds'), cid))
        new = _insert(c, order_id, user, now, fin, amount, due, method, source, evidence, notes, replaces=cid)
        _event(c, cid, 'reprogramado', 'Nuevo compromiso #%d: %s hasta el %s · %s' % (new, usd(amount), due.strftime('%d/%m/%Y'), evidence), user, now)
        _event(c, new, 'registrado', 'Reprogramación del compromiso #%d · %s: %s' % (cid, SOURCES[source], evidence), user, now)
        audit(c, user['id'], 'payment_commitment_rescheduled', order_id)
        return new
    if action == 'cancel':
        if user['role'] != 'administrador':
            raise CommitmentError('Solo administración cancela compromisos.', 403)
        reason = _text(data, 'reason', 10, 300, 'Motivo de la cancelación')
        c.execute("UPDATE payment_commitments SET status='cancelado',updated_at=? WHERE id=?", (now.isoformat(timespec='seconds'), cid))
        _event(c, cid, 'cancelado', reason, user, now)
        audit(c, user['id'], 'payment_commitment_cancelled', order_id)
        return cid
    if action == 'review':
        reason = _text(data, 'reason', 10, 300, 'Motivo de la revisión')
        c.execute("UPDATE payment_commitments SET status='en_revision',updated_at=? WHERE id=?", (now.isoformat(timespec='seconds'), cid))
        _event(c, cid, 'en_revision', reason, user, now)
        audit(c, user['id'], 'payment_commitment_review', order_id)
        return cid
    if action == 'close_review':
        if user['role'] != 'administrador':
            raise CommitmentError('Solo administración cierra una revisión.', 403)
        if row['status'] != 'en_revision':
            raise CommitmentError('El compromiso no está en revisión.', 409)
        reason = _text(data, 'reason', 10, 300, 'Resultado de la revisión')
        c.execute("UPDATE payment_commitments SET status='activo',updated_at=? WHERE id=?", (now.isoformat(timespec='seconds'), cid))
        _event(c, cid, 'revision_cerrada', reason, user, now)
        audit(c, user['id'], 'payment_commitment_review_closed', order_id)
        return cid
    raise CommitmentError('Acción no válida.')
