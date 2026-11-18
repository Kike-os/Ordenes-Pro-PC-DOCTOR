"""Cobertura Empresarial de Repuestos — PC-DOCTOR (1.5.296).

PC-DOCTOR financia la compra de un repuesto de un presupuesto (total o parcialmente), pero el cliente sigue pagando el precio de su
presupuesto. Ejemplo: pantalla de $150,00 al cliente; costo $95,00 al proveedor; cobertura 100 % → PC-DOCTOR paga $95,00 al proveedor
(egreso real de caja) y el cliente sigue debiendo $150,00 (sus cobros son ingresos aparte). Nada de esto aparece en los documentos del
cliente: presupuesto, enlace, PDF, recibos y portal leen solo las partidas del presupuesto.

Estados separados (nunca se deducen unos de otros):
- Cobertura: solicitada → autorizada (o rechazada / cancelada). Autorizar NO mueve dinero.
- Compra: pendiente → comprado → recibido (la recepción crea, si la línea es de inventario, una sola entrada con su costo real).
- Pago al proveedor: pendiente / parcial / pagado, calculado de los pagos registrados. Cada pago es un egreso de caja «Compra de repuestos
  — Cobertura PC-DOCTOR» creado en la misma transacción, con clave única (un reintento o un doble clic no lo duplica) y sin superar lo
  cubierto. Revertir exige administración y motivo: anula el egreso si la sesión sigue abierta o registra un ingreso compensatorio.
Permisos: administración configura, autoriza, revisa y revierte; quien tiene la caja abierta (o administración) registra pagos; el técnico
solicita y consulta el estado, nunca costos, proveedor, pagos ni márgenes.
"""
import json
import re
from datetime import datetime, timedelta

import cash_sessions

STATUS = {'solicitada': 'Solicitada', 'autorizada': 'Autorizada', 'rechazada': 'Rechazada', 'cancelada': 'Cancelada'}
PURCHASE = {'pendiente': 'Compra pendiente', 'comprado': 'Comprado al proveedor', 'recibido': 'Recibido en el taller'}
PAYMENT = {'pendiente': 'Pago pendiente', 'parcial': 'Pago parcial', 'pagado': 'Pagado'}
CASH_KIND = 'cobertura_repuesto'


class CoverageError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def ready(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='part_coverages'").fetchone() is not None


def stamp(now):
    return now.isoformat(timespec='seconds')


def usd(cents):
    return cash_sessions.usd(cents)


def is_admin(user):
    return user['role'] == 'administrador'


def _cents(value, field, label):
    text = str(value if value is not None else '').strip().replace('$', '').replace(' ', '')
    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.')
    elif ',' in text:
        text = text.replace(',', '.')
    if not re.fullmatch(r'\d{1,7}(\.\d{1,2})?', text):
        raise CoverageError('Indica %s en dólares (hasta dos decimales).' % label, fields={field: 'Importe no válido.'})
    cents = round(float(text) * 100)
    if cents <= 0:
        raise CoverageError('Indica %s mayor que cero.' % label, fields={field: 'Debe ser mayor que cero.'})
    return cents


def _text(data, key, limit, minimum=0, label='el texto'):
    value = re.sub(r'[ \t]+', ' ', str(data.get(key, '') or '')).strip()
    if len(value) > limit or len(value) < minimum:
        raise CoverageError('Indica %s (%d a %d caracteres).' % (label, minimum, limit) if minimum else 'Escribe %s en %d caracteres como máximo.' % (label, limit), fields={key: 'No válido.'})
    return value


def event(c, cov_id, name, detail, user, now):
    c.execute('INSERT INTO part_coverage_events(coverage_id,event,detail,actor_id,created_at) VALUES (?,?,?,?,?)', (cov_id, name, detail[:600], user['id'] if user else None, stamp(now)))


def _row(c, cov_id):
    row = c.execute('SELECT * FROM part_coverages WHERE id=?', (int(cov_id),)).fetchone() if str(cov_id).isdigit() else None
    if not row:
        raise CoverageError('Cobertura no disponible.', 404)
    return dict(row)


def _quote(c, quote_id):
    row = c.execute('SELECT q.*,COALESCE(o.code,\'OP-\'||printf(\'%05d\',o.id)) order_code,o.assigned_to FROM quotes q JOIN orders o ON o.id=q.order_id WHERE q.id=? AND q.deleted_at=\'\'',
                    (int(quote_id),)).fetchone() if str(quote_id).isdigit() else None
    if not row:
        raise CoverageError('Presupuesto no disponible.', 404)
    return dict(row)


def _can_see_quote(user, quote):
    # Igual que los presupuestos: administración y personal técnico (que solo recibe el estado, nunca cifras internas).
    return user['role'] in ('administrador', 'tecnico')


def paid_cents(c, cov_id):
    return c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM part_coverage_payments WHERE coverage_id=? AND status='registrado'", (cov_id,)).fetchone()[0]


def payment_state(covered, paid):
    return 'pagado' if paid >= covered else 'parcial' if paid > 0 else 'pendiente'


def _supplier(c, raw, required=False):
    raw = str(raw or '')
    if not raw:
        if required:
            raise CoverageError('Elige el proveedor.', fields={'supplier_id': 'Obligatorio.'})
        return None
    row = c.execute('SELECT id,name FROM suppliers WHERE id=? AND active=1', (int(raw),)).fetchone() if raw.isdigit() else None
    if not row:
        raise CoverageError('Elige un proveedor activo.', fields={'supplier_id': 'No válido.'})
    return dict(row)


def view(c, cov, user, full=None):
    """Cobertura para la interfaz. Sin permisos financieros (técnicos) no lleva costo, proveedor, pagos, notas ni margen."""
    full = is_admin(user) if full is None else full
    paid = paid_cents(c, cov['id'])
    base = {'id': cov['id'], 'quote_id': cov['quote_id'], 'order_id': cov['order_id'], 'line_position': cov['line_position'], 'line_description': cov['line_description'],
            'linked': cov['quote_item_id'] is not None, 'status': cov['status'], 'status_label': STATUS[cov['status']], 'purchase_status': cov['purchase_status'],
            'purchase_label': PURCHASE[cov['purchase_status']], 'payment_status': payment_state(cov['covered_cents'], paid), 'payment_label': PAYMENT[payment_state(cov['covered_cents'], paid)],
            'review': cov['review'], 'requested_at': cov['requested_at'], 'authorized_at': cov['authorized_at'], 'authorized_name': cov['authorized_name'], 'revision': cov['revision'],
            'received_at': cov['received_at']}
    if not full:
        return base
    supplier = c.execute('SELECT name FROM suppliers WHERE id=?', (cov['supplier_id'],)).fetchone() if cov['supplier_id'] else None
    base.update(sale_cents=cov['sale_cents'], cost_cents=cov['cost_cents'], percent=cov['percent'], covered_cents=cov['covered_cents'], paid_cents=paid,
                pending_cents=max(0, cov['covered_cents'] - paid), margin_cents=cov['sale_cents'] - cov['cost_cents'], supplier_id=cov['supplier_id'],
                supplier=supplier['name'] if supplier else '', supplier_document=cov['supplier_document'], notes=cov['notes'], purchased_at=cov['purchased_at'],
                inventory_movement_id=cov['inventory_movement_id'], quantity=cov['quantity'], close_reason=cov['close_reason'], closed_at=cov['closed_at'])
    return base


def for_quote(c, user, quote_id):
    quote = _quote(c, quote_id)
    if not _can_see_quote(user, quote):
        raise CoverageError('Presupuesto no disponible.', 404)
    if not ready(c):
        return {'ready': False, 'rows': []}
    rows = [view(c, dict(r), user) for r in c.execute('SELECT * FROM part_coverages WHERE quote_id=? ORDER BY line_position,id', (quote['id'],))]
    out = {'ready': True, 'rows': rows, 'can_manage': is_admin(user), 'can_pay': can_pay(c, user)}
    if is_admin(user):
        out['suppliers'] = [dict(r) for r in c.execute('SELECT id,name FROM suppliers WHERE active=1 ORDER BY name')]
    return out


def open_session(c, user):
    """Caja abierta en la que esta persona puede registrar el egreso (la suya; administración, también la única abierta). None si no hay."""
    sid = cash_sessions.current_for(c, user)
    row = c.execute('SELECT * FROM cash_sessions WHERE id=?', (sid,)).fetchone() if sid else None
    if not row or row['status'] != 'abierta' or not (is_admin(user) or row['cashier_id'] == user['id']):
        return None
    return row


def can_pay(c, user):
    """Registran pagos al proveedor: administración o quien tiene su caja abierta (personal autorizado de caja)."""
    return bool(is_admin(user) or open_session(c, user))


def detail(c, user, cov_id):
    cov = _row(c, cov_id)
    quote = _quote(c, cov['quote_id'])
    if not _can_see_quote(user, quote):
        raise CoverageError('Cobertura no disponible.', 404)
    out = view(c, cov, user)
    out['quote_code'] = quote['code']
    out['order_code'] = quote['order_code']
    out['events'] = [dict(r) for r in c.execute("SELECT e.event,e.detail,e.created_at,COALESCE(u.name,'Sistema') actor FROM part_coverage_events e LEFT JOIN users u ON u.id=e.actor_id "
                                                "WHERE e.coverage_id=? ORDER BY e.id DESC", (cov['id'],))] if is_admin(user) else []
    if is_admin(user):
        out['payments'] = [dict(r) for r in c.execute("SELECT p.*,COALESCE(u.name,'') paid_name,COALESCE(v.name,'') reversed_name,m.session_id,COALESCE(m.file_id,0) file_id FROM part_coverage_payments p "
                                                      "JOIN cash_movements m ON m.id=p.cash_movement_id LEFT JOIN users u ON u.id=p.paid_by LEFT JOIN users v ON v.id=p.reversed_by "
                                                      "WHERE p.coverage_id=? ORDER BY p.id DESC", (cov['id'],))]
        out['suppliers'] = [dict(r) for r in c.execute('SELECT id,name FROM suppliers WHERE active=1 ORDER BY name')]
    out['can_manage'] = is_admin(user)
    out['can_pay'] = can_pay(c, user) and cov['status'] == 'autorizada'
    out['methods'] = cash_sessions.METHODS
    return out


def _line(c, quote, position):
    raw = str(position or '')
    item = c.execute('SELECT * FROM quote_items WHERE quote_id=? AND position=?', (quote['id'], int(raw))).fetchone() if raw.isdigit() else None
    if not item:
        raise CoverageError('Partida del presupuesto no encontrada. Guarda el presupuesto antes de configurar la cobertura.', 404)
    if item['category'] != 'repuesto':
        raise CoverageError('La cobertura PC-DOCTOR es para partidas de repuesto.', 409)
    return dict(item)


def _amounts(data, sale_cents, current=None):
    cost = _cents(data.get('cost', current['cost_cents'] / 100 if current else ''), 'cost', 'el costo real del repuesto')
    mode = str(data.get('mode', '') or ('total' if not current or current['percent'] == 100 else 'parcial'))
    if mode == 'total':
        percent = 100
    else:
        raw = str(data.get('percent', current['percent'] if current else '')).strip()
        if not raw.isdigit() or not 1 <= int(raw) <= 99:
            raise CoverageError('Indica el porcentaje de la cobertura parcial (1 a 99 %).', fields={'percent': 'No válido.'})
        percent = int(raw)
    covered = max(1, round(cost * percent / 100))
    return cost, percent, covered


def request(c, user, quote_id, data, now):
    """Solicita (técnico) o crea y autoriza (administración, con «authorize») la cobertura de una partida de repuesto."""
    if not ready(c):
        raise CoverageError('Esta función necesita una actualización de la base de datos que todavía no se aplicó.', 503)
    if user['role'] not in ('administrador', 'tecnico'):
        raise CoverageError('Acceso no permitido.', 403)
    quote = _quote(c, quote_id)
    if not _can_see_quote(user, quote):
        raise CoverageError('Presupuesto no disponible.', 404)
    if quote['status'] in ('cancelado', 'rechazado'):
        raise CoverageError('El presupuesto está %s: no admite coberturas nuevas.' % quote['status'], 409)
    item = _line(c, quote, data.get('position'))
    sale = item['unit_cents'] * item['quantity']
    cost, percent, covered = _amounts(data, sale)
    supplier = _supplier(c, data.get('supplier_id'))
    notes = _text(data, 'notes', 1000, 0, 'las observaciones privadas')
    if c.execute("SELECT 1 FROM part_coverages WHERE quote_id=? AND line_position=? AND line_description=? AND status IN ('solicitada','autorizada')",
                 (quote['id'], item['position'], item['description'])).fetchone():
        raise CoverageError('Esta partida ya tiene una cobertura en curso.', 409)
    cid = c.execute('INSERT INTO part_coverages(quote_id,order_id,quote_item_id,line_position,line_description,catalog_id,quantity,sale_cents,cost_cents,percent,covered_cents,supplier_id,'
                    "status,notes,requested_by,requested_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'solicitada',?,?,?,?)",
                    (quote['id'], quote['order_id'], item['id'], item['position'], item['description'], item['catalog_id'], item['quantity'], sale, cost, percent, covered,
                     supplier['id'] if supplier else None, notes, user['id'], stamp(now), stamp(now))).lastrowid
    event(c, cid, 'solicitada', 'Cobertura solicitada: %s · costo %s · %d %% (%s cubiertos)%s.' % (item['description'][:80], usd(cost), percent, usd(covered),
                                                                                                     ' · proveedor ' + supplier['name'] if supplier else ''), user, now)
    if is_admin(user) and data.get('authorize') is True:
        authorize(c, user, cid, dict(data, revision='0'), now)
    return cid


def authorize(c, user, cov_id, data, now):
    if not is_admin(user):
        raise CoverageError('Solo administración autoriza coberturas.', 403)
    cov = _row(c, cov_id)
    if cov['status'] != 'solicitada':
        raise CoverageError('Solo se autoriza una cobertura solicitada.', 409)
    _check_revision(cov, data)
    cost, percent, covered = _amounts(data, cov['sale_cents'], cov)
    supplier = _supplier(c, data.get('supplier_id', cov['supplier_id']), required=True)
    name = _text(data, 'authorized_name', 120, 0, 'quién autoriza') or user['name']
    if c.execute("UPDATE part_coverages SET status='autorizada',cost_cents=?,percent=?,covered_cents=?,supplier_id=?,authorized_by=?,authorized_name=?,authorized_at=?,revision=revision+1,updated_at=? "
                 "WHERE id=? AND revision=? AND status='solicitada'", (cost, percent, covered, supplier['id'], user['id'], name, stamp(now), stamp(now), cov['id'], cov['revision'])).rowcount != 1:
        raise CoverageError('Otra persona cambió esta cobertura mientras tanto. Vuelve a abrirla.', 409)
    event(c, cov['id'], 'autorizada', 'Cobertura autorizada por %s: costo %s · %d %% · %s a cargo de PC-DOCTOR · proveedor %s. No registra ninguna salida de caja.' % (
        name, usd(cost), percent, usd(covered), supplier['name']), user, now)


def _check_revision(cov, data):
    if str(data.get('revision', '')) != str(cov['revision']):
        raise CoverageError('Otra persona cambió esta cobertura mientras tanto. Se recargaron los datos: revisa y vuelve a intentarlo.', 409)


def update(c, user, cov_id, data, now):
    """Ajusta costo, porcentaje, proveedor, observaciones o datos de compra. El importe cubierto nunca queda por debajo de lo ya pagado."""
    if not is_admin(user):
        raise CoverageError('Solo administración modifica coberturas.', 403)
    cov = _row(c, cov_id)
    if cov['status'] not in ('solicitada', 'autorizada'):
        raise CoverageError('La cobertura está %s: no se modifica.' % cov['status'], 409)
    _check_revision(cov, data)
    cost, percent, covered = _amounts(data, cov['sale_cents'], cov)
    paid = paid_cents(c, cov['id'])
    if covered < paid:
        raise CoverageError('El importe cubierto (%s) no puede ser menor que lo ya pagado al proveedor (%s). Revierte primero el pago si corresponde.' % (usd(covered), usd(paid)), 409, {'cost': 'Menor que lo pagado.'})
    supplier = _supplier(c, data.get('supplier_id', cov['supplier_id']), required=cov['status'] == 'autorizada')
    notes = _text(data, 'notes', 1000, 0, 'las observaciones privadas') if 'notes' in data else cov['notes']
    changes = []
    if cost != cov['cost_cents']:
        changes.append('costo %s → %s' % (usd(cov['cost_cents']), usd(cost)))
    if percent != cov['percent']:
        changes.append('cobertura %d %% → %d %%' % (cov['percent'], percent))
    if (supplier['id'] if supplier else None) != cov['supplier_id']:
        changes.append('proveedor ' + (supplier['name'] if supplier else 'sin indicar'))
    if notes != cov['notes']:
        changes.append('observaciones privadas actualizadas')
    if not changes:
        return False
    c.execute('UPDATE part_coverages SET cost_cents=?,percent=?,covered_cents=?,supplier_id=?,notes=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?',
              (cost, percent, covered, supplier['id'] if supplier else None, notes, stamp(now), cov['id'], cov['revision']))
    event(c, cov['id'], 'editada', 'Cobertura actualizada: ' + '; '.join(changes) + '.', user, now)
    return True


def close(c, user, cov_id, data, now, status='cancelada'):
    """Rechaza (solicitada) o cancela (autorizada). Nunca si hay pagos vigentes o el repuesto ya se compró: primero se revierte o regulariza."""
    if not is_admin(user):
        raise CoverageError('Solo administración rechaza o cancela coberturas.', 403)
    cov = _row(c, cov_id)
    if status == 'rechazada' and cov['status'] != 'solicitada':
        raise CoverageError('Solo se rechaza una cobertura solicitada.', 409)
    if cov['status'] not in ('solicitada', 'autorizada'):
        raise CoverageError('La cobertura ya está %s.' % cov['status'], 409)
    if paid_cents(c, cov['id']):
        raise CoverageError('Esta cobertura tiene pagos al proveedor registrados: revierte los pagos antes de cancelarla.', 409)
    if cov['purchase_status'] != 'pendiente':
        raise CoverageError('El repuesto ya figura como %s: no se cancela la cobertura sin regularizar la compra.' % PURCHASE[cov['purchase_status']].lower(), 409)
    reason = _text(data, 'reason', 300, 10, 'el motivo')
    c.execute('UPDATE part_coverages SET status=?,closed_by=?,closed_at=?,close_reason=?,revision=revision+1,updated_at=? WHERE id=?', (status, user['id'], stamp(now), reason, stamp(now), cov['id']))
    event(c, cov['id'], status, 'Cobertura %s. Motivo: %s' % (status, reason), user, now)


def purchase(c, user, cov_id, data, now):
    """Registra la compra al proveedor (pedido o factura) sin mover dinero ni inventario."""
    if not is_admin(user):
        raise CoverageError('Solo administración registra la compra.', 403)
    cov = _row(c, cov_id)
    if cov['status'] != 'autorizada':
        raise CoverageError('Primero se autoriza la cobertura.', 409)
    if cov['purchase_status'] != 'pendiente':
        raise CoverageError('La compra ya estaba registrada.', 409)
    document = _text(data, 'supplier_document', 60, 1, 'el número de factura o documento del proveedor')
    c.execute("UPDATE part_coverages SET purchase_status='comprado',supplier_document=?,purchased_at=?,revision=revision+1,updated_at=? WHERE id=?", (document, stamp(now), stamp(now), cov['id']))
    event(c, cov['id'], 'comprado', 'Compra registrada al proveedor (documento %s). No es un pago ni una recepción.' % document, user, now)


def receive(c, user, cov_id, data, now):
    """Recepción física del repuesto. Si la partida es un artículo de inventario, crea UNA entrada (motivo «compra») con el costo real,
    vinculada a la cobertura y a la orden (clave única: un reintento no la duplica). Recibir no paga nada."""
    if not is_admin(user):
        raise CoverageError('Solo administración registra la recepción.', 403)
    cov = _row(c, cov_id)
    if cov['status'] != 'autorizada':
        raise CoverageError('Primero se autoriza la cobertura.', 409)
    if cov['purchase_status'] == 'recibido':
        return cov['inventory_movement_id']
    if cov['purchase_status'] != 'comprado':
        raise CoverageError('Registra primero la compra al proveedor.', 409)
    item = c.execute('SELECT i.id FROM inventory_items i WHERE i.catalog_id=?', (cov['catalog_id'],)).fetchone() if cov['catalog_id'] else None
    movement = None
    if item:
        import inventory
        unit = cov['cost_cents'] / cov['quantity'] / 100
        try:
            movement = inventory.move(c, item['id'], 1, 'compra', str(cov['quantity']), '%.2f' % unit, user, now, reference_kind='cobertura', reference_id=cov['id'],
                                      note='Repuesto con Cobertura PC-DOCTOR para la orden', request_key='cobertura-%d-entrada' % cov['id'], supplier_id=cov['supplier_id'],
                                      document=cov['supplier_document'], serials=[s for s in str(data.get('serials', '') or '').replace(',', '\n').split('\n') if s.strip()] or None)
        except Exception as error:
            raise CoverageError('No se pudo registrar la entrada en inventario: %s' % error, 409)
    c.execute("UPDATE part_coverages SET purchase_status='recibido',received_at=?,received_by=?,inventory_movement_id=?,revision=revision+1,updated_at=? WHERE id=?",
              (stamp(now), user['id'], movement, stamp(now), cov['id']))
    event(c, cov['id'], 'recibido', 'Repuesto recibido en el taller' + (' · entrada de inventario MOV-%d con costo %s.' % (movement, usd(cov['cost_cents'])) if movement else
                                                                         ' (la partida no es un artículo de inventario: no se registró entrada).'), user, now)
    return movement


def pay(c, user, cov_id, data, now, file_id=None):
    """Pago al proveedor: egreso real de la caja abierta de quien paga, en la misma transacción. Idempotente por «request_key»."""
    if not can_pay(c, user):
        raise CoverageError('Registran pagos al proveedor administración o quien tiene la caja abierta.', 403)
    key = str(data.get('request_key', '') or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9-]{16,56}', key):
        raise CoverageError('Solicitud no válida. Recarga la página.', 400)
    same = c.execute('SELECT id,cash_movement_id FROM part_coverage_payments WHERE request_key=?', (key,)).fetchone()
    if same:
        return {'payment_id': same['id'], 'cash_movement_id': same['cash_movement_id'], 'duplicate': True}
    cov = _row(c, cov_id)
    if cov['status'] != 'autorizada':
        raise CoverageError('Solo se pagan coberturas autorizadas.', 409)
    if not cov['supplier_id']:
        raise CoverageError('La cobertura no tiene proveedor.', 409)
    supplier = c.execute('SELECT name FROM suppliers WHERE id=?', (cov['supplier_id'],)).fetchone()
    paid = paid_cents(c, cov['id'])
    pending = cov['covered_cents'] - paid
    if pending <= 0:
        raise CoverageError('Esta cobertura ya está pagada por completo.', 409)
    amount = _cents(data.get('amount', ''), 'amount', 'el importe pagado')
    if amount > pending:
        raise CoverageError('El pago (%s) supera lo pendiente con el proveedor (%s).' % (usd(amount), usd(pending)), 409, {'amount': 'Supera lo pendiente.'})
    document = _text(data, 'supplier_document', 60, 1, 'el número de factura o documento')
    raw_when = str(data.get('paid_at', '') or '')
    try:
        when = datetime.fromisoformat(raw_when) if raw_when else now
        when = when if when.tzinfo else when.replace(tzinfo=now.tzinfo)
    except ValueError:
        raise CoverageError('Indica una fecha y hora válidas.', fields={'paid_at': 'No válida.'})
    if when > now + timedelta(minutes=5) or when < now - timedelta(days=60):
        raise CoverageError('La fecha del pago debe ser de hoy o de los últimos 60 días (nunca futura).', fields={'paid_at': 'Fuera de rango.'})
    session = open_session(c, user)
    if not session:
        raise CoverageError(cash_sessions.CLOSED_MESSAGE, 409, {'cash': 'Caja cerrada.'})
    quote = _quote(c, cov['quote_id'])
    movement = {'session_id': str(session['id']), 'direction': 'egreso', 'kind': CASH_KIND, 'method': str(data.get('method', '')), 'amount': '%.2f' % (amount / 100),
                'concept': ('Compra de repuesto · Cobertura PC-DOCTOR · Orden %s · %s' % (quote['order_code'], cov['line_description']))[:200],
                'beneficiary': supplier['name'][:160], 'document': document, 'reference': str(data.get('reference', '') or ''), 'bank_account_id': str(data.get('bank_account_id', '') or ''),
                'note': ('Pagado el %s. Presupuesto %s.' % (when.strftime('%d/%m/%Y %H:%M'), quote['code']))[:300], 'request_key': 'cov-' + key}
    try:
        mid, duplicate = cash_sessions.add_movement(c, user, movement, now, file_id, linked=True)
    except cash_sessions.CashError as error:
        raise CoverageError(str(error), error.status, error.fields)
    if duplicate:
        found = c.execute('SELECT id FROM part_coverage_payments WHERE cash_movement_id=?', (mid,)).fetchone()
        if found:
            return {'payment_id': found['id'], 'cash_movement_id': mid, 'duplicate': True}
    pid = c.execute('INSERT INTO part_coverage_payments(coverage_id,cash_movement_id,amount_cents,method,supplier_document,reference,paid_at,paid_by,request_key,created_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?)', (cov['id'], mid, amount, movement['method'], document, movement['reference'], when.isoformat(timespec='seconds'), user['id'], key, stamp(now))).lastrowid
    if not cov['supplier_document']:
        c.execute('UPDATE part_coverages SET supplier_document=?,revision=revision+1,updated_at=? WHERE id=?', (document, stamp(now), cov['id']))
    total = paid + amount
    event(c, cov['id'], 'pago', 'Pago al proveedor %s: %s (%s, documento %s) · egreso de caja CJM-%d · %s.' % (supplier['name'], usd(amount), cash_sessions.METHODS.get(movement['method'], movement['method']),
                                                                                                 document, mid, PAYMENT[payment_state(cov['covered_cents'], total)].lower()), user, now)
    return {'payment_id': pid, 'cash_movement_id': mid, 'duplicate': False, 'payment_status': payment_state(cov['covered_cents'], total)}


def reverse(c, user, payment_id, data, now, cov_id=None):
    """Reverso controlado (administración, con motivo): anula el egreso si su sesión sigue abierta; si ya se cerró, registra un ingreso
    compensatorio en la caja abierta de quien revierte. El pago queda «revertido» con su trazabilidad; nada se borra."""
    if not is_admin(user):
        raise CoverageError('Solo administración revierte pagos al proveedor.', 403)
    raw = str(payment_id or '')
    pay_row = c.execute('SELECT * FROM part_coverage_payments WHERE id=?', (int(raw),)).fetchone() if raw.isdigit() else None
    if not pay_row or (cov_id is not None and pay_row['coverage_id'] != cov_id):
        raise CoverageError('Pago no encontrado.', 404)
    if pay_row['status'] != 'registrado':
        raise CoverageError('Ese pago ya fue revertido.', 409)
    reason = _text(data, 'reason', 300, 10, 'el motivo del reverso')
    movement = c.execute('SELECT * FROM cash_movements WHERE id=?', (pay_row['cash_movement_id'],)).fetchone()
    session = c.execute('SELECT status FROM cash_sessions WHERE id=?', (movement['session_id'],)).fetchone()
    compensating = None
    try:
        if session['status'] in cash_sessions.OPEN:
            cash_sessions.void_movement(c, user, {'movement_id': str(movement['id']), 'reason': 'Reverso de pago de cobertura: ' + reason}, now)
            how = 'egreso CJM-%d anulado' % movement['id']
        else:
            current = open_session(c, user)
            if not current:
                raise CoverageError('La sesión del pago ya se cerró: abre una caja para registrar el ingreso compensatorio del reverso.', 409)
            compensating, _dup = cash_sessions.add_movement(c, user, {'session_id': str(current['id']), 'direction': 'ingreso', 'kind': 'otro_ingreso', 'method': movement['method'],
                                                                       'amount': '%.2f' % (pay_row['amount_cents'] / 100), 'concept': 'Reverso de pago de Cobertura PC-DOCTOR (CJM-%d)' % movement['id'],
                                                                       'beneficiary': movement['beneficiary'], 'document': movement['document'], 'reference': movement['reference'],
                                                                       'bank_account_id': str(movement['bank_account_id'] or ''), 'note': reason[:300],
                                                                       'request_key': 'covrev-%d-%s' % (pay_row['id'], pay_row['request_key'][:40])}, now)
            how = 'ingreso compensatorio CJM-%d' % compensating
    except cash_sessions.CashError as error:
        raise CoverageError(str(error), error.status, error.fields)
    c.execute("UPDATE part_coverage_payments SET status='revertido',reversal_movement_id=?,reversed_by=?,reversed_at=?,reverse_reason=? WHERE id=? AND status='registrado'",
              (compensating, user['id'], stamp(now), reason, pay_row['id']))
    event(c, pay_row['coverage_id'], 'pago_revertido', 'Pago de %s revertido (%s). Motivo: %s' % (usd(pay_row['amount_cents']), how, reason), user, now)
    return {'ok': True, 'compensating_movement_id': compensating}


# ---- Vínculo con el presupuesto ----
def before_save(c, quote_id):
    """Antes de recrear las partidas de un borrador: las coberturas vigentes de ese presupuesto (para volver a enlazarlas)."""
    if not ready(c):
        return []
    return [dict(r) for r in c.execute("SELECT id,line_position,line_description FROM part_coverages WHERE quote_id=? AND status IN ('solicitada','autorizada')", (quote_id,))]


def after_save(c, quote_id, kept, user, now):
    """Vuelve a enlazar cada cobertura con su partida (misma descripción; primero en la misma posición). Si la partida desapareció o dejó
    de ser un repuesto, la cobertura queda sin vínculo y marcada para revisión: nunca se borra ni se cambia el precio del cliente."""
    for cov in kept:
        items = [dict(r) for r in c.execute("SELECT id,position,category,description,unit_cents,quantity FROM quote_items WHERE quote_id=? AND description=? AND category='repuesto'",
                                              (quote_id, cov['line_description']))]
        match = next((i for i in items if i['position'] == cov['line_position']), items[0] if items else None)
        if match:
            c.execute('UPDATE part_coverages SET quote_item_id=?,line_position=?,sale_cents=?,quantity=?,review=\'\',updated_at=? WHERE id=?',
                      (match['id'], match['position'], match['unit_cents'] * match['quantity'], match['quantity'], stamp(now), cov['id']))
        else:
            c.execute("UPDATE part_coverages SET quote_item_id=NULL,review=?,revision=revision+1,updated_at=? WHERE id=?",
                      ('La partida cubierta cambió o se quitó del presupuesto: revisa la cobertura.', stamp(now), cov['id']))
            event(c, cov['id'], 'revisar', 'La partida «%s» ya no está en el borrador: la cobertura queda pendiente de revisión.' % cov['line_description'][:80], user, now)


def on_quote_cancel(c, quote_id, user, now):
    """Al cancelar un presupuesto: se cancelan las coberturas sin compra ni pagos; las que tienen compra o pagos quedan para revisión."""
    if not ready(c):
        return
    for cov in [dict(r) for r in c.execute("SELECT * FROM part_coverages WHERE quote_id=? AND status IN ('solicitada','autorizada')", (quote_id,))]:
        if paid_cents(c, cov['id']) or cov['purchase_status'] != 'pendiente':
            c.execute('UPDATE part_coverages SET review=?,updated_at=? WHERE id=?', ('Presupuesto cancelado con compra o pagos registrados: revisa la cobertura.', stamp(now), cov['id']))
            event(c, cov['id'], 'revisar', 'Presupuesto cancelado: la cobertura tiene compra o pagos y queda pendiente de revisión.', user, now)
        else:
            c.execute("UPDATE part_coverages SET status='cancelada',closed_by=?,closed_at=?,close_reason=?,revision=revision+1,updated_at=? WHERE id=?",
                      (user['id'] if user else None, stamp(now), 'Presupuesto cancelado', stamp(now), cov['id']))
            event(c, cov['id'], 'cancelada', 'Cobertura cancelada al cancelar el presupuesto (sin compra ni pagos).', user, now)


# ---- Panel financiero (administración) ----
def dashboard(c, user, params, now):
    if not is_admin(user):
        raise CoverageError('Solo administración consulta el panel financiero de coberturas.', 403)
    if not ready(c):
        return {'ready': False, 'rows': [], 'totals': {}}
    get = lambda k: str(params.get(k, '') or '').strip()
    start, end = get('from') or (now.date() - timedelta(days=90)).isoformat(), get('to') or now.date().isoformat()
    try:
        if datetime.fromisoformat(start) > datetime.fromisoformat(end):
            raise CoverageError('La fecha inicial es posterior a la final.')
    except ValueError:
        raise CoverageError('Indica fechas válidas.')
    hi = (datetime.fromisoformat(end) + timedelta(days=1)).date().isoformat()
    sql = ("SELECT p.*,q.code quote_code,COALESCE(o.code,'OP-'||printf('%05d',o.id)) order_code,COALESCE(s.name,'') supplier,COALESCE(u.name,'') requested_name "
           "FROM part_coverages p JOIN quotes q ON q.id=p.quote_id JOIN orders o ON o.id=p.order_id LEFT JOIN suppliers s ON s.id=p.supplier_id LEFT JOIN users u ON u.id=p.requested_by "
           "WHERE p.requested_at>=? AND p.requested_at<?")
    args = [start, hi]
    if get('supplier').isdigit():
        sql += ' AND p.supplier_id=?'
        args.append(int(get('supplier')))
    if get('status') in STATUS:
        sql += ' AND p.status=?'
        args.append(get('status'))
    if get('order'):
        sql += " AND COALESCE(o.code,'') LIKE ?"
        args.append('%' + get('order')[:30] + '%')
    if get('responsible'):
        sql += ' AND (p.authorized_name LIKE ? OR u.name LIKE ?)'
        args += ['%' + get('responsible')[:60] + '%'] * 2
    rows = []
    for r in c.execute(sql + ' ORDER BY p.id DESC LIMIT 1000', args):
        r = dict(r)
        paid = paid_cents(c, r['id'])
        rows.append({'id': r['id'], 'order_code': r['order_code'], 'quote_code': r['quote_code'], 'line': r['line_description'], 'supplier': r['supplier'], 'status': r['status'],
                     'status_label': STATUS[r['status']], 'purchase_label': PURCHASE[r['purchase_status']], 'purchase_status': r['purchase_status'], 'sale_cents': r['sale_cents'],
                     'cost_cents': r['cost_cents'], 'percent': r['percent'], 'covered_cents': r['covered_cents'], 'paid_cents': paid, 'pending_cents': max(0, r['covered_cents'] - paid) if r['status'] == 'autorizada' else 0,
                     'margin_cents': r['sale_cents'] - r['cost_cents'], 'payment_label': PAYMENT[payment_state(r['covered_cents'], paid)], 'authorized_name': r['authorized_name'],
                     'requested_at': r['requested_at'], 'review': r['review'], 'quote_id': r['quote_id'], 'order_id': r['order_id']})
    live = [r for r in rows if r['status'] == 'autorizada']
    month = now.date().replace(day=1).isoformat()
    monthly = c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM part_coverage_payments WHERE status='registrado' AND paid_at>=?", (month,)).fetchone()[0]
    totals = {'covered': sum(r['covered_cents'] for r in live), 'authorized_unpaid': sum(1 for r in live if r['pending_cents'] > 0),
              'paid': sum(r['paid_cents'] for r in rows), 'pending': sum(r['pending_cents'] for r in live), 'received': sum(1 for r in live if r['purchase_status'] == 'recibido'),
              'to_receive': sum(1 for r in live if r['purchase_status'] != 'recibido'), 'margin': sum(r['margin_cents'] for r in live), 'monthly_paid': monthly,
              'review': sum(1 for r in rows if r['review']), 'requested': sum(1 for r in rows if r['status'] == 'solicitada')}
    return {'ready': True, 'rows': rows, 'totals': totals, 'from': start, 'to': end, 'statuses': STATUS,
            'suppliers': [dict(s) for s in c.execute('SELECT id,name FROM suppliers ORDER BY name')]}


def dashboard_csv(data):
    import csv
    import io
    out = io.StringIO()
    out.write('﻿')
    w = csv.writer(out)
    safe = lambda v: "'" + v if isinstance(v, str) and v[:1] in ('=', '+', '-', '@', '\t', '\r') else v
    w.writerow(['Orden', 'Presupuesto', 'Repuesto', 'Proveedor', 'Cobertura', 'Compra', 'Pago', 'Precio al cliente', 'Costo', '% cubierto', 'Cubierto PC-DOCTOR', 'Pagado', 'Pendiente',
                'Margen bruto estimado', 'Autorizó', 'Solicitada'])
    money = lambda cents: '%.2f' % (cents / 100)
    for r in data['rows']:
        w.writerow([safe(x) for x in (r['order_code'], r['quote_code'], r['line'], r['supplier'], r['status_label'], r['purchase_label'], r['payment_label'], money(r['sale_cents']),
                                        money(r['cost_cents']), r['percent'], money(r['covered_cents']), money(r['paid_cents']), money(r['pending_cents']), money(r['margin_cents']),
                                        r['authorized_name'], r['requested_at'][:10])])
    return out.getvalue()
