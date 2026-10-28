"""Caja por sesiones: apertura con conteo por denominaciones, ingresos y egresos, arqueo, cierre definitivo, fondo del siguiente turno,
revisión de diferencias, ajustes posteriores, historial y reportes (A4 y térmico de 80 mm).

Reglas que se aplican SIEMPRE en el servidor (la interfaz solo las refleja):
- Una sola sesión abierta (o en arqueo) por caja; si ya hay una, se devuelve esa y no se crea otra.
- Los cobros de órdenes, licencias y anticipos se leen de sus propias tablas y se vinculan a la sesión al registrarse: nunca se copian,
  así no se cuentan dos veces. La caja solo guarda sus propios ingresos y egresos.
- Efectivo esperado = fondo inicial + entradas en efectivo − salidas en efectivo. Diferencia = contado − esperado. Ningún ajuste automático.
- Transferencias y depósitos son dinero recibido solo cuando administración los confirma; las tarjetas, al liquidarse. Nada de eso se
  suma al efectivo del cajón.
- Un cierre se guarda como una foto inmutable; una corrección posterior es un ajuste aparte con su motivo.
- Todo en centavos enteros."""
import json
import re
import sqlite3
from datetime import datetime, timedelta

import banking

SHIFTS = ('Mañana', 'Tarde', 'Noche', 'Jornada completa')
STATUS = {'abierta': 'Caja abierta', 'arqueo': 'En proceso de arqueo', 'revision': 'Pendiente de revisión', 'cerrada': 'Cerrada correctamente',
          'cerrada_diferencia': 'Cerrada con diferencia', 'anulada': 'Anulada'}
OPEN = ('abierta', 'arqueo')
METHODS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia', 'deposito': 'Depósito', 'debito': 'Tarjeta de débito', 'credito': 'Tarjeta de crédito',
           'cheque': 'Cheque', 'otro': 'Otro'}
IN_KINDS = {'venta_directa': 'Venta directa', 'cobro_factura': 'Cobro de factura anterior', 'retencion_recibida': 'Retención recibida', 'otro_ingreso': 'Otro ingreso autorizado'}
OUT_KINDS = {'gasto_operativo': 'Gasto operativo', 'pago_proveedor': 'Pago a proveedor', 'devolucion': 'Devolución de dinero', 'reembolso': 'Reembolso autorizado',
             'nota_credito': 'Pago mediante nota de crédito', 'devolucion_anticipo': 'Devolución de anticipo', 'retencion': 'Retención aplicada',
             'retiro': 'Retiro de efectivo', 'salida_extraordinaria': 'Salida extraordinaria', 'gasto_menor': 'Gasto menor', 'deposito_banco': 'Depósito de efectivo en el banco',
             'otro_egreso': 'Otro egreso autorizado'}
# Egresos que solo administración puede registrar (autorización administrativa expresa).
ADMIN_OUT = ('reembolso', 'devolucion', 'devolucion_anticipo', 'retiro', 'salida_extraordinaria', 'nota_credito')
MAX_QTY = 100000
CLOSED_MESSAGE = 'La caja se encuentra cerrada. Debe abrir un turno de caja antes de registrar esta operación.'


class CashError(ValueError):
    def __init__(self, message, status=400, fields=None, extra=None):
        super().__init__(message)
        self.status, self.fields, self.extra = status, fields or {}, extra or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def usd(cents):
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return sign + '$' + format(cents // 100, ',').replace(',', '.') + ',%02d' % (cents % 100)


def is_admin(user):
    return user['role'] == 'administrador'


def event(c, entity, entity_id, name, detail, user, now):
    c.execute('INSERT INTO payment_events(entity,entity_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?,?)',
              (entity, entity_id, name, detail[:600], user['id'] if user else None, user['name'] if user else 'Sistema', stamp(now)))


def cents_of(value, field='amount', allow_zero=False):
    text = str(value if value is not None else '').strip().replace('$', '').replace(' ', '')
    if re.fullmatch(r'\d{1,3}(\.\d{3})+,\d{1,2}', text):
        text = text.replace('.', '')
    text = text.replace(',', '.')
    if not re.fullmatch(r'\d{1,8}(\.\d{1,2})?', text):
        raise CashError('Importe no válido.', 400, {field: 'Importe en USD con hasta dos decimales.'})
    whole, _, frac = text.partition('.')
    cents = int(whole) * 100 + int((frac + '00')[:2])
    if cents <= 0 and not allow_zero:
        raise CashError('El importe debe ser mayor que cero.', 400, {field: 'Importe mayor que cero.'})
    return cents


def _text(data, key, size, minimum=0, label='El texto', field=None):
    value = re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()
    if len(value) > size:
        raise CashError('%s admite hasta %d caracteres.' % (label, size), 400, {field or key: 'Hasta %d caracteres.' % size})
    if minimum and len(value) < minimum:
        raise CashError('%s es obligatorio (al menos %d caracteres).' % (label, minimum), 400, {field or key: 'Obligatorio.'})
    return value


# ---- Cajas y denominaciones ------------------------------------------------------------------------------------------------

def registers(c, active_only=True):
    return [dict(r) for r in c.execute('SELECT id,name,active FROM cash_registers' + (' WHERE active=1' if active_only else '') + ' ORDER BY id')]


def save_register(c, data, user, now):
    if not is_admin(user):
        raise CashError('Solo administración configura las cajas.', 403)
    name = _text(data, 'name', 60, 3, 'El nombre de la caja')
    rid = str(data.get('id', '') or '')
    try:
        if rid.isdigit():
            active = 0 if str(data.get('active', '1')) in ('0', 'false') else 1
            if not active and c.execute("SELECT 1 FROM cash_sessions WHERE register_id=? AND status IN ('abierta','arqueo')", (int(rid),)).fetchone():
                raise CashError('Esa caja tiene una sesión abierta: ciérrala antes de desactivarla.', 409)
            c.execute('UPDATE cash_registers SET name=?,active=? WHERE id=?', (name, active, int(rid)))
            event(c, 'caja', int(rid), 'caja_editada', 'Caja: %s (%s).' % (name, 'activa' if active else 'inactiva'), user, now)
            return int(rid)
        new = c.execute('INSERT INTO cash_registers(name,created_at,created_by) VALUES (?,?,?)', (name, stamp(now), user['id'])).lastrowid
    except sqlite3.IntegrityError:
        raise CashError('Ya existe una caja con ese nombre.', 409, {'name': 'Nombre repetido.'})
    event(c, 'caja', new, 'caja_creada', 'Caja creada: %s.' % name, user, now)
    return new


def denominations(c, active_only=True):
    return [dict(r, label=('Moneda' if r['kind'] == 'moneda' else 'Billete') + ' de ' + usd(r['value_cents']))
            for r in c.execute('SELECT id,kind,value_cents,active,position FROM cash_denominations' + (' WHERE active=1' if active_only else '') + ' ORDER BY position')]


def set_denomination(c, data, user, now):
    if not is_admin(user):
        raise CashError('Solo administración configura las denominaciones.', 403)
    row = c.execute('SELECT * FROM cash_denominations WHERE id=?', (str(data.get('id', '')),)).fetchone() if str(data.get('id', '')).isdigit() else None
    if not row:
        raise CashError('Denominación no encontrada.', 404)
    active = 0 if str(data.get('active', '')) in ('0', 'false', '') else 1
    c.execute('UPDATE cash_denominations SET active=? WHERE id=?', (active, row['id']))
    event(c, 'caja', 0, 'denominacion', '%s de %s %s (los arqueos históricos no cambian).' % (row['kind'].capitalize(), usd(row['value_cents']), 'activada' if active else 'desactivada'), user, now)


# ---- Configuración general y tarjetas de las cajas ----------------------------------------------------------------------------------
def settings(c):
    """Configuración general de la caja; si la tabla aún no existe (base sin migrar), los valores de siempre."""
    try:
        row = c.execute('SELECT default_fund_cents,require_open,difference_limit_cents,updated_at FROM cash_settings WHERE id=1').fetchone()
    except sqlite3.OperationalError:
        row = None
    return {'default_fund_cents': row['default_fund_cents'] if row else 0, 'require_open': bool(row['require_open']) if row else False,
            'difference_limit_cents': row['difference_limit_cents'] if row else 0, 'updated_at': row['updated_at'] if row else ''}


def save_settings(c, data, user, now):
    if not is_admin(user):
        raise CashError('Solo administración cambia la configuración de caja.', 403)
    fund = cents_of(data.get('default_fund', '0') or '0', 'default_fund', allow_zero=True)
    limit = cents_of(data.get('difference_limit', '0') or '0', 'difference_limit', allow_zero=True)
    if limit > 1000000:
        raise CashError('El límite de diferencia no puede superar $10.000,00.', 400, {'difference_limit': 'Límite demasiado alto.'})
    require = 1 if str(data.get('require_open', '')) in ('1', 'true') else 0
    before = settings(c)
    c.execute('UPDATE cash_settings SET default_fund_cents=?,require_open=?,difference_limit_cents=?,updated_at=?,updated_by=? WHERE id=1', (fund, require, limit, stamp(now), user['id']))
    event(c, 'caja', 0, 'configuracion', 'Configuración de caja: fondo inicial predeterminado %s → %s; apertura obligatoria %s → %s; diferencia aceptada sin revisión %s → %s.' % (
        usd(before['default_fund_cents']), usd(fund), 'sí' if before['require_open'] else 'no', 'sí' if require else 'no', usd(before['difference_limit_cents']), usd(limit)), user, now)
    return settings(c)


def session_for_payment(c, user):
    """Sesión a la que se vincula un cobro. Con la apertura obligatoria activada, sin caja abierta no se registra el cobro."""
    session = current_for(c, user)
    if session is None and settings(c)['require_open']:
        raise CashError(CLOSED_MESSAGE, 409, {'cash': 'Caja cerrada.'}, {'cash_closed': True})
    return session


def register_cards(c):
    """Cajas con su estado operativo: turno abierto (cajero, turno y código), última apertura y último cierre."""
    out = []
    for r in registers(c, False):
        s = c.execute("SELECT s.*,u.name cashier FROM cash_sessions s LEFT JOIN users u ON u.id=s.cashier_id WHERE s.register_id=? AND s.status IN ('abierta','arqueo') ORDER BY s.id DESC LIMIT 1", (r['id'],)).fetchone()
        last_open = c.execute("SELECT MAX(opened_at) FROM cash_sessions WHERE register_id=? AND status!='anulada'", (r['id'],)).fetchone()[0]
        last_close = c.execute("SELECT MAX(k.closed_at) FROM cash_session_closings k JOIN cash_sessions s ON s.id=k.session_id WHERE s.register_id=?", (r['id'],)).fetchone()[0]
        out.append(dict(r, session={'id': s['id'], 'code': code_of(s), 'cashier': s['cashier'] or '', 'shift': s['shift'] if 'shift' in s.keys() else '', 'status': s['status']} if s else None,
                        last_opened=last_open or '', last_closed=last_close or ''))
    return out


def set_denominations(c, data, user, now):
    """Activa exactamente las denominaciones indicadas (al menos una). No borra ninguna: los arqueos guardan su propio valor."""
    if not is_admin(user):
        raise CashError('Solo administración configura las denominaciones.', 403)
    ids = {int(x) for x in re.split(r'[,\s]+', str(data.get('active_ids', '') or '')) if x.isdigit()}
    rows = c.execute('SELECT id,kind,value_cents,active FROM cash_denominations').fetchall()
    if not ids or not ids <= {r['id'] for r in rows}:
        raise CashError('Deja al menos una denominación activa.', 400, {'active_ids': 'Selecciona denominaciones válidas.'})
    changed = []
    for r in rows:
        active = 1 if r['id'] in ids else 0
        if active != r['active']:
            c.execute('UPDATE cash_denominations SET active=? WHERE id=?', (active, r['id']))
            changed.append('%s de %s %s' % (r['kind'], usd(r['value_cents']), 'activada' if active else 'desactivada'))
    if changed:
        event(c, 'caja', 0, 'denominacion', 'Denominaciones: ' + '; '.join(changed) + ' (los arqueos históricos no cambian).', user, now)
    return len(changed)


def config(c):
    used = set()  # denominaciones que aparecen en arqueos guardados (nunca se eliminan; solo se desactivan)
    for r in c.execute('SELECT counts FROM cash_counts'):
        try:
            used.update(x.get('id') for x in json.loads(r['counts'] or '[]') if isinstance(x, dict))
        except ValueError:
            pass
    verified = c.execute('SELECT COUNT(*) FROM bank_accounts WHERE active=1 AND verified=1').fetchone()[0]
    return {'registers': register_cards(c), 'denominations': [dict(d, used=d['id'] in used) for d in denominations(c, False)], 'settings': settings(c), 'accounts_verified': verified}


def count_of(c, raw):
    """Conteo por denominaciones: cantidades enteras de 0 a 100000. Guarda el valor de cada denominación con el conteo, así un cambio de
    configuración no altera los arqueos históricos."""
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        raise CashError('Conteo no válido.', 400, {'counts': 'Conteo no válido.'})
    if not isinstance(items, list):
        raise CashError('Conteo no válido.', 400, {'counts': 'Conteo no válido.'})
    known = {r['id']: r for r in c.execute('SELECT * FROM cash_denominations')}
    out, seen, errors = [], set(), {}
    for item in items:
        did = item.get('id') if isinstance(item, dict) else None
        qty = str(item.get('qty', '') if isinstance(item, dict) else '').strip()
        if not isinstance(did, int) or did not in known or did in seen:
            raise CashError('Denominación no válida en el conteo.', 400, {'counts': 'Denominación no válida.'})
        seen.add(did)
        if qty == '':
            qty = '0'
        if not re.fullmatch(r'\d{1,6}', qty) or int(qty) > MAX_QTY:
            errors['qty_%d' % did] = 'Cantidad entera de 0 a %d.' % MAX_QTY
            continue
        d = known[did]
        if int(qty):
            out.append({'id': did, 'kind': d['kind'], 'value_cents': d['value_cents'], 'qty': int(qty), 'subtotal_cents': int(qty) * d['value_cents']})
    if errors:
        raise CashError('Revisa las cantidades: solo números enteros, sin negativos ni decimales.', 400, errors)
    coins = sum(r['subtotal_cents'] for r in out if r['kind'] == 'moneda')
    bills = sum(r['subtotal_cents'] for r in out if r['kind'] == 'billete')
    return {'rows': out, 'coins_cents': coins, 'bills_cents': bills, 'total_cents': coins + bills}


# ---- Sesiones -----------------------------------------------------------------------------------------------------------------

def _session(c, session_id):
    row = c.execute('SELECT * FROM cash_sessions WHERE id=?', (session_id,)).fetchone() if str(session_id).isdigit() else None
    if not row:
        raise CashError('Sesión de caja no encontrada.', 404)
    return row


def _can_see(user, row):
    return is_admin(user) or row['cashier_id'] == user['id']


def current_for(c, user):
    """Sesión abierta a la que se vinculan los cobros de esta persona: la suya o, si no tiene, la única caja abierta. None si no hay."""
    own = c.execute("SELECT id FROM cash_sessions WHERE cashier_id=? AND status IN ('abierta','arqueo') ORDER BY id DESC LIMIT 1", (user['id'],)).fetchone()
    if own:
        return own['id']
    rows = c.execute("SELECT id FROM cash_sessions WHERE status IN ('abierta','arqueo')").fetchall()
    return rows[0]['id'] if len(rows) == 1 else None


def pending_fund(c, register_id):
    """Fondo reservado por el último cierre de esta caja que todavía no recibió ninguna apertura."""
    row = c.execute("SELECT s.id,s.code,k.reserved_cents,k.delivered_by,u.name cashier FROM cash_sessions s JOIN cash_session_closings k ON k.session_id=s.id JOIN users u ON u.id=s.cashier_id "
                    "WHERE s.register_id=? AND s.status IN ('revision','cerrada','cerrada_diferencia') AND k.reserved_cents>0 "
                    "AND NOT EXISTS (SELECT 1 FROM cash_sessions n WHERE n.fund_from_session_id=s.id AND n.status!='anulada') ORDER BY s.id DESC LIMIT 1", (register_id,)).fetchone()
    return dict(row) if row else None


def open_session(c, user, data, now):
    """Abre una caja. Si esa caja ya está abierta, no crea otra (409 con la sesión existente)."""
    if user['role'] not in ('administrador', 'tecnico'):
        raise CashError('Tu cuenta no puede operar la caja.', 403)
    key = str(data.get('request_key', '') or '').strip()
    if key and not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
        raise CashError('Solicitud no válida. Recarga la página.', 400)
    if key:
        same = c.execute('SELECT id FROM cash_sessions WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id']
    rid = str(data.get('register_id', '') or '')
    reg = c.execute('SELECT * FROM cash_registers WHERE id=? AND active=1', (rid,)).fetchone() if rid.isdigit() else None
    if not reg:
        raise CashError('Elige la caja.', 400, {'register_id': 'Caja no disponible.'})
    existing = c.execute("SELECT id,code FROM cash_sessions WHERE register_id=? AND status IN ('abierta','arqueo')", (reg['id'],)).fetchone()
    if existing:
        raise CashError('La %s ya está abierta (%s): continúa con esa sesión.' % (reg['name'], existing['code']), 409, extra={'session_id': existing['id']})
    shift = str(data.get('shift', ''))
    if shift not in SHIFTS:
        raise CashError('Elige el turno.', 400, {'shift': 'Turno no válido.'})
    cashier = user['id']
    if is_admin(user) and str(data.get('cashier_id', '')).isdigit():
        found = c.execute("SELECT id FROM users WHERE id=? AND active=1 AND role IN ('administrador','tecnico')", (int(data['cashier_id']),)).fetchone()
        if not found:
            raise CashError('Cajero no válido.', 400, {'cashier_id': 'Elige un usuario activo.'})
        cashier = found['id']
    count = count_of(c, data.get('counts', '[]'))
    note = _text(data, 'note', 300, 0, 'La observación')
    fund = pending_fund(c, reg['id'])
    received_by = ''
    if fund:
        if str(data.get('fund_confirm', '')) not in ('1', 'true', 'on'):
            raise CashError('Confirma que recibiste el fondo de %s dejado por el cierre %s.' % (usd(fund['reserved_cents']), fund['code']), 400, {'fund_confirm': 'Confirma la recepción del fondo.'})
        received_by = _text(data, 'fund_received_by', 120, 5, 'El nombre de quien recibe el fondo')
        if count['total_cents'] != fund['reserved_cents'] and len(note) < 10:
            raise CashError('El conteo (%s) no coincide con el fondo entregado (%s): explica la diferencia en las observaciones.' % (usd(count['total_cents']), usd(fund['reserved_cents'])), 400, {'note': 'Explica la diferencia.'})
    sid = next_id(c, 'cash_sessions')
    code = 'CJ-%06d' % sid
    try:
        c.execute('INSERT INTO cash_sessions(id,code,register_id,shift,cashier_id,opened_by,opened_at,opening_cents,opening_note,fund_from_session_id,fund_expected_cents,fund_received_by,status,request_key) '
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'abierta',?)",
                  (sid, code, reg['id'], shift, cashier, user['id'], stamp(now), count['total_cents'], note, fund['id'] if fund else None, fund['reserved_cents'] if fund else 0, received_by, key or None))
    except sqlite3.IntegrityError:
        existing = c.execute("SELECT id FROM cash_sessions WHERE register_id=? AND status IN ('abierta','arqueo')", (reg['id'],)).fetchone()
        raise CashError('Esa caja acaba de abrirse en otra sesión.', 409, extra={'session_id': existing['id'] if existing else None})
    c.execute('INSERT INTO cash_counts(session_id,stage,counts,coins_cents,bills_cents,total_cents,final,updated_at,updated_by) VALUES (?,?,?,?,?,?,1,?,?)',
              (sid, 'apertura', json.dumps(count['rows']), count['coins_cents'], count['bills_cents'], count['total_cents'], stamp(now), user['id']))
    event(c, 'sesion', sid, 'apertura', 'Caja %s abierta (%s, turno %s) con fondo inicial %s%s.' % (code, reg['name'], shift, usd(count['total_cents']),
          ('; recibe el fondo del cierre %s (%s), confirmado por %s' % (fund['code'], usd(fund['reserved_cents']), received_by)) if fund else ''), user, now)
    return sid


def next_id(c, table):
    """Siguiente identificador de una tabla con AUTOINCREMENT (para numerar el documento al crearlo; las filas no se eliminan)."""
    seq = c.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone()
    top = c.execute('SELECT COALESCE(MAX(id),0) FROM ' + table).fetchone()[0]
    return max(seq[0] if seq else 0, top) + 1


def code_of(row):
    return row['code']


def _rows(c, session):
    """Todas las operaciones de la sesión con una referencia única cada una (sin duplicar cobros de otras tablas)."""
    sid = session['id']
    out = []
    accounts = {r['id']: r for r in c.execute('SELECT * FROM bank_accounts')}
    transfers = {}
    for t in c.execute('SELECT * FROM bank_transfers WHERE payment_id IN (SELECT id FROM order_payments WHERE cash_session_id=?) OR advance_id IN (SELECT id FROM advances WHERE cash_session_id=?)', (sid, sid)):
        transfers[('pago', t['payment_id']) if t['payment_id'] else ('anticipo', t['advance_id'])] = dict(t)
    vouchers = {}
    for v in c.execute('SELECT * FROM card_vouchers WHERE payment_id IN (SELECT id FROM order_payments WHERE cash_session_id=?) OR advance_id IN (SELECT id FROM advances WHERE cash_session_id=?)', (sid, sid)):
        vouchers[('pago', v['payment_id']) if v['payment_id'] else ('anticipo', v['advance_id'])] = dict(v)

    def settle(method, key):
        if method in ('efectivo',):
            return 'recibido', 'Recibido en efectivo'
        if method == 'cheque':
            return 'pendiente', 'Cheque pendiente de cobro'
        if method in ('transferencia', 'deposito'):
            t = transfers.get(key)
            state = t['status'] if t else 'sin_registro'
            return ('recibido', 'Confirmado por administración') if state in ('confirmado', 'conciliado') else ('pendiente', {'pendiente': 'Pendiente de verificar', 'rechazado': 'Rechazado',
                                                                                                                                 'sin_registro': 'Sin comprobante registrado'}[state])
        if method in ('debito', 'credito'):
            v = vouchers.get(key)
            if v and v['status'] == 'liquidada':
                return 'recibido', 'Liquidada'
            return 'pendiente', ('Voucher %s · %s' % (v['code'], v['status'].replace('_', ' '))) if v else 'Pendiente de voucher y liquidación'
        return 'pendiente', 'Método sin identificar: clasificar'

    for p in c.execute("SELECT p.*,o.code order_code,COALESCE(k.name,'') client,COALESCE(u.name,'') actor FROM order_payments p JOIN orders o ON o.id=p.order_id JOIN devices d ON d.id=o.device_id "
                       "LEFT JOIN clients k ON k.id=d.client_id LEFT JOIN users u ON u.id=p.created_by WHERE p.cash_session_id=? ORDER BY p.id", (sid,)):
        method = p['method_detail'] if p['method_detail'] in ('debito', 'credito', 'cheque') else ('credito' if p['method'] == 'tarjeta' else p['method'])
        if p['method'] == 'tarjeta' and not p['method_detail']:
            method = 'credito'
        refund = p['kind'] == 'devolucion'
        state, note = settle(method, ('pago', p['id']))
        if p['method'] == 'otro' and not p['method_detail']:
            state, note = 'pendiente', 'Método sin identificar: clasificar'
        acct = accounts.get(p['bank_account_id'])
        out.append({'ref': 'PAG-%d' % p['id'], 'source': 'orden', 'source_id': p['id'], 'at': p['paid_at'] or p['created_at'], 'direction': 'egreso' if refund else 'ingreso',
                    'kind': 'devolucion' if refund else 'cobro_orden', 'kind_label': 'Devolución de una orden' if refund else 'Cobro de orden de servicio', 'method': method,
                    'amount_cents': p['amount_cents'], 'document': p['order_code'], 'client': p['client'], 'actor': p['actor'], 'reference': p['reference'],
                    'bank': banking.label(acct) if acct else '', 'operation': p['operation_id'], 'voided': bool(p['voided_at']), 'state': 'anulado' if p['voided_at'] else state,
                    'state_label': 'Anulado: ' + p['void_reason'] if p['voided_at'] else note})
    for p in c.execute("SELECT p.*,s.code sale_code,COALESCE(k.name,'') client,COALESCE(u.name,'') actor FROM license_sale_payments p JOIN license_sales s ON s.id=p.sale_id "
                       "LEFT JOIN clients k ON k.id=s.client_id LEFT JOIN users u ON u.id=p.created_by WHERE p.cash_session_id=? ORDER BY p.id", (sid,)):
        method = 'credito' if p['method'] == 'tarjeta' else p['method']
        state, note = settle(method, ('licencia', p['id']))
        if p['method'] in ('transferencia', 'deposito') and p['status'] == 'confirmado':
            state, note = 'recibido', 'Confirmado en Licencias'
        out.append({'ref': 'LIC-%d' % p['id'], 'source': 'licencia', 'source_id': p['id'], 'at': p['created_at'], 'direction': 'ingreso', 'kind': 'venta_licencia',
                    'kind_label': 'Venta de licencias', 'method': method, 'amount_cents': p['amount_cents'], 'document': p['sale_code'], 'client': p['client'], 'actor': p['actor'],
                    'reference': p['reference'], 'bank': '', 'operation': '', 'voided': p['status'] == 'anulado', 'state': 'anulado' if p['status'] == 'anulado' else state,
                    'state_label': 'Anulado' if p['status'] == 'anulado' else note})
    for a in c.execute("SELECT a.*,COALESCE(k.name,'') client,COALESCE(u.name,'') actor,COALESCE(f.code,'') proforma FROM advances a LEFT JOIN clients k ON k.id=a.client_id "
                       "LEFT JOIN users u ON u.id=a.created_by LEFT JOIN proformas f ON f.id=a.proforma_id WHERE a.cash_session_id=? ORDER BY a.id", (sid,)):
        state, note = settle(a['method'], ('anticipo', a['id']))
        acct = accounts.get(a['bank_account_id'])
        out.append({'ref': a['code'], 'source': 'anticipo', 'source_id': a['id'], 'at': a['paid_at'], 'direction': 'ingreso', 'kind': 'anticipo', 'kind_label': 'Anticipo de cliente',
                    'method': a['method'], 'amount_cents': a['amount_cents'], 'document': a['proforma'], 'client': a['client'], 'actor': a['actor'], 'reference': a['reference'],
                    'bank': banking.label(acct) if acct else '', 'operation': a['operation_id'], 'voided': bool(a['voided_at']), 'state': 'anulado' if a['voided_at'] else state,
                    'state_label': 'Anulado: ' + a['void_reason'] if a['voided_at'] else note})
    for m in c.execute("SELECT m.*,COALESCE(k.name,'') client,COALESCE(u.name,'') actor FROM cash_movements m LEFT JOIN clients k ON k.id=m.client_id LEFT JOIN users u ON u.id=m.created_by "
                       "WHERE m.session_id=? ORDER BY m.id", (sid,)):
        acct = accounts.get(m['bank_account_id'])
        kinds = IN_KINDS if m['direction'] == 'ingreso' else OUT_KINDS
        if m['method'] == 'efectivo' or m['direction'] == 'egreso':
            state, note = 'recibido' if m['direction'] == 'ingreso' else 'pagado', 'Registrado en caja'
        else:
            state, note = 'pendiente', 'Por conciliar'
        if m['kind'] == 'retencion_recibida':
            state, note = 'documento', 'Comprobante de retención'
        out.append({'ref': 'CJM-%d' % m['id'], 'source': 'caja', 'source_id': m['id'], 'at': m['created_at'], 'direction': m['direction'], 'kind': m['kind'],
                    'kind_label': kinds.get(m['kind'], m['kind']), 'method': m['method'], 'amount_cents': m['amount_cents'], 'document': m['document'], 'concept': m['concept'],
                    'beneficiary': m['beneficiary'], 'client': m['client'], 'actor': m['actor'], 'reference': m['reference'], 'bank': banking.label(acct) if acct else '',
                    'authorized_by': m['authorized_by'], 'note': m['note'], 'has_file': bool(m['file_id']), 'operation': '', 'voided': bool(m['voided_at']),
                    'state': 'anulado' if m['voided_at'] else state, 'state_label': 'Anulado: ' + m['void_reason'] if m['voided_at'] else note})
    out.sort(key=lambda r: (r['at'], r['ref']))
    for r in out:
        r['method_label'] = METHODS.get(r['method'], r['method'])
    return out


def summary(c, session):
    """Totales calculados desde las operaciones registradas (nunca desde cifras de la interfaz)."""
    rows = _rows(c, session)
    live = [r for r in rows if not r['voided']]
    by_method = {m: {'in_cents': 0, 'out_cents': 0, 'count': 0} for m in METHODS}
    for r in live:
        if r['kind'] == 'retencion_recibida':
            continue
        slot = by_method[r['method']]
        slot['in_cents' if r['direction'] == 'ingreso' else 'out_cents'] += r['amount_cents']
        slot['count'] += 1
    cash_in, cash_out = by_method['efectivo']['in_cents'], by_method['efectivo']['out_cents']
    expected = session['opening_cents'] + cash_in - cash_out
    income = [r for r in live if r['direction'] == 'ingreso' and r['kind'] != 'retencion_recibida']
    outgo = [r for r in live if r['direction'] == 'egreso']
    received = sum(r['amount_cents'] for r in income if r['state'] == 'recibido')
    pending = [r for r in live if r['state'] == 'pendiente']
    groups = {}
    for r in income:
        groups.setdefault(r['kind'], {'label': r['kind_label'], 'cents': 0, 'count': 0})
        groups[r['kind']]['cents'] += r['amount_cents']
        groups[r['kind']]['count'] += 1
    out_groups = {}
    for r in outgo:
        out_groups.setdefault(r['kind'], {'label': r['kind_label'], 'cents': 0, 'count': 0})
        out_groups[r['kind']]['cents'] += r['amount_cents']
        out_groups[r['kind']]['count'] += 1
    vouchers = [dict(v) for v in c.execute('SELECT * FROM card_vouchers WHERE cash_session_id=? ORDER BY id', (session['id'],))]
    transfers = [dict(t, account=banking.label(c.execute('SELECT * FROM bank_accounts WHERE id=?', (t['bank_account_id'],)).fetchone(), masked=True))
                 for t in c.execute('SELECT * FROM bank_transfers WHERE payment_id IN (SELECT id FROM order_payments WHERE cash_session_id=?) OR advance_id IN (SELECT id FROM advances WHERE cash_session_id=?) ORDER BY id',
                                    (session['id'], session['id']))]
    adjustments = [dict(a) for a in c.execute("SELECT a.*,COALESCE(u.name,'') actor FROM cash_adjustments a LEFT JOIN users u ON u.id=a.created_by WHERE a.session_id=? ORDER BY a.id", (session['id'],))]
    cash = [r for r in live if r['method'] == 'efectivo' and r['kind'] != 'retencion_recibida']
    refunds = ('devolucion', 'devolucion_anticipo', 'reembolso', 'nota_credito')
    breakdown = {'opening_cents': session['opening_cents'],
                 'sales_cents': sum(r['amount_cents'] for r in cash if r['direction'] == 'ingreso' and r['kind'] != 'otro_ingreso'),
                 'other_in_cents': sum(r['amount_cents'] for r in cash if r['direction'] == 'ingreso' and r['kind'] == 'otro_ingreso'),
                 'out_cents': sum(r['amount_cents'] for r in cash if r['direction'] == 'egreso' and r['kind'] not in refunds),
                 'refunds_cents': sum(r['amount_cents'] for r in cash if r['direction'] == 'egreso' and r['kind'] in refunds)}
    breakdown['expected_cents'] = breakdown['opening_cents'] + breakdown['sales_cents'] + breakdown['other_in_cents'] - breakdown['out_cents'] - breakdown['refunds_cents']
    accounts = {}
    for t in transfers:
        slot = accounts.setdefault(t['account'], {'account': t['account'], 'transfer_cents': 0, 'deposit_cents': 0, 'count': 0})
        slot['deposit_cents' if t.get('method') == 'deposito' else 'transfer_cents'] += t['amount_cents']
        slot['count'] += 1
    collections = {'cash_cents': by_method['efectivo']['in_cents'], 'transfer_cents': by_method['transferencia']['in_cents'], 'deposit_cents': by_method['deposito']['in_cents'],
                   'card_cents': by_method['debito']['in_cents'] + by_method['credito']['in_cents'], 'datafast_cents': sum(v['amount_cents'] for v in vouchers if v['status'] not in ('rechazada', 'reversada')),
                   'other_cents': by_method['cheque']['in_cents'] + by_method['otro']['in_cents']}
    collections['total_cents'] = sum(v for k, v in collections.items() if k != 'datafast_cents')
    return {'rows': rows, 'by_method': by_method, 'opening_cents': session['opening_cents'], 'cash_breakdown': breakdown, 'by_account': list(accounts.values()), 'collections': collections, 'cash_in_cents': cash_in, 'cash_out_cents': cash_out, 'expected_cash_cents': expected,
            'income_cents': sum(r['amount_cents'] for r in income), 'outgo_cents': sum(r['amount_cents'] for r in outgo), 'received_cents': received,
            'pending_cents': sum(r['amount_cents'] for r in income if r['state'] == 'pendiente'), 'pending': [{'ref': r['ref'], 'label': r['kind_label'], 'state_label': r['state_label'],
                                                                                                                'amount_cents': r['amount_cents'], 'method_label': r['method_label']} for r in pending],
            'income_groups': groups, 'outgo_groups': out_groups, 'operations': len(live), 'vouchers': vouchers, 'transfers': transfers, 'adjustments': adjustments,
            'adjusted_cents': sum(a['amount_cents'] for a in adjustments), 'general': general_data(c, session, rows)}


def _window(session, closing):
    end = closing['closed_at'] if closing else '9999'
    return session['opened_at'], end


def general_data(c, session, rows):
    """DATOS GENERALES DEL CIERRE: solo transacciones reales del período de la sesión. Lo que el sistema todavía no registra (retenciones de
    clientes como módulo propio) sale de los registros de caja; nada se escribe a mano."""
    closing = c.execute('SELECT closed_at FROM cash_session_closings WHERE session_id=?', (session['id'],)).fetchone()
    start, end = _window(session, closing)
    live = [r for r in rows if not r['voided']]
    notes = c.execute("SELECT COUNT(*),COALESCE(SUM(total_cents),0) FROM credit_notes WHERE status='pendiente' AND emitted_at>=? AND emitted_at<=?", (start, end)).fetchone()
    invoices = c.execute("SELECT id,total_cents,discount_cents FROM invoices WHERE status IN ('pendiente','enviado','autorizado') AND emitted_at>=? AND emitted_at<=?", (start, end)).fetchall()
    credit = {r['invoice_id']: r['cents'] for r in c.execute("SELECT invoice_id,SUM(amount_cents) cents FROM invoice_payments WHERE method='credito' GROUP BY invoice_id")}
    voided = c.execute("SELECT COUNT(DISTINCT invoice_id) FROM credit_notes WHERE status='pendiente' AND scope='total' AND emitted_at>=? AND emitted_at<=?", (start, end)).fetchone()[0]
    applied = c.execute("SELECT COUNT(*),COALESCE(SUM(a.amount_cents),0) FROM advances a JOIN proformas f ON f.id=a.proforma_id JOIN invoices i ON i.id=f.invoice_id "
                        "WHERE a.voided_at='' AND i.status IN ('pendiente','enviado','autorizado') AND i.emitted_at>=? AND i.emitted_at<=?", (start, end)).fetchone()
    recovered = [r for r in live if r['source'] == 'orden' and r['direction'] == 'ingreso' and c.execute(
        "SELECT 1 FROM invoices i JOIN order_payments p ON p.order_id=i.order_id WHERE p.id=? AND i.status IN ('pendiente','enviado','autorizado') AND i.emitted_at<=?", (r['source_id'], r['at'])).fetchone()]
    pick = lambda kinds, direction=None: [r for r in live if r['kind'] in kinds and (direction is None or r['direction'] == direction)]
    total_sales = sum(i['total_cents'] for i in invoices)
    credit_sales = sum(credit.get(i['id'], 0) for i in invoices)
    return [
        ('Notas de crédito', notes[0], notes[1]), ('Anticipos recibidos', len(pick(('anticipo',))), sum(r['amount_cents'] for r in pick(('anticipo',)))),
        ('Anticipos aplicados', applied[0], applied[1]), ('Ventas realizadas (facturas emitidas)', len(invoices), total_sales),
        ('Ventas al contado', len([i for i in invoices if not credit.get(i['id'])]), total_sales - credit_sales), ('Ventas a crédito', len([i for i in invoices if credit.get(i['id'])]), credit_sales),
        ('Facturas emitidas', len(invoices), total_sales), ('Facturas anuladas (nota de crédito total)', voided, None),
        ('Retenciones recibidas', len(pick(('retencion_recibida',))), sum(r['amount_cents'] for r in pick(('retencion_recibida',)))),
        ('Retenciones aplicadas', len(pick(('retencion',), 'egreso')), sum(r['amount_cents'] for r in pick(('retencion',), 'egreso'))),
        ('Cruces con facturas (anticipos aplicados)', applied[0], applied[1]), ('Cuentas por cobrar generadas', len([i for i in invoices if credit.get(i['id'])]), credit_sales),
        ('Cuentas por cobrar recuperadas', len(recovered), sum(r['amount_cents'] for r in recovered)),
        ('Devoluciones registradas', len(pick(('devolucion', 'devolucion_anticipo', 'reembolso'))), sum(r['amount_cents'] for r in pick(('devolucion', 'devolucion_anticipo', 'reembolso')))),
        ('Descuentos aplicados en facturas', len([i for i in invoices if i['discount_cents']]), sum(i['discount_cents'] for i in invoices)),
        ('Total de operaciones del período', len(live), None)]


def view(c, user, session_id):
    s = _session(c, session_id)
    if not _can_see(user, s):
        raise CashError('Solo puedes ver tu propia caja.', 403)
    reg = c.execute('SELECT name FROM cash_registers WHERE id=?', (s['register_id'],)).fetchone()
    names = {r['id']: r['name'] for r in c.execute('SELECT id,name FROM users')}
    counts = {r['stage']: dict(r, counts=json.loads(r['counts'])) for r in c.execute('SELECT * FROM cash_counts WHERE session_id=?', (s['id'],))}
    closing = c.execute('SELECT * FROM cash_session_closings WHERE session_id=?', (s['id'],)).fetchone()
    data = summary(c, s)
    closing = dict(closing, summary=json.loads(closing['summary']), counts=json.loads(closing['counts'])) if closing else None
    events = [dict(r) for r in c.execute("SELECT event,detail,actor,created_at FROM payment_events WHERE entity='sesion' AND entity_id=? ORDER BY id DESC", (s['id'],))]
    fund_next = None
    if closing and closing['reserved_cents']:
        taken = c.execute("SELECT id,opened_at,fund_received_by FROM cash_sessions WHERE fund_from_session_id=? AND status!='anulada'", (s['id'],)).fetchone()
        fund_next = {'reserved_cents': closing['reserved_cents'], 'received': bool(taken), 'received_by': taken['fund_received_by'] if taken else '', 'session': ('CJ-%06d' % taken['id']) if taken else ''}
    return {'session': dict(s, code=code_of(s), register=reg['name'] if reg else '', cashier=names.get(s['cashier_id'], ''), opened_by_name=names.get(s['opened_by'], ''),
                            status_label=STATUS[s['status']], reviewed_by_name=names.get(s['reviewed_by'], ''), voided_by_name=names.get(s['voided_by'], '')),
            'summary': data, 'counts': counts, 'closing': closing, 'events': events, 'fund_next': fund_next, 'can_admin': is_admin(user), 'is_cashier': s['cashier_id'] == user['id']}


def state(c, user, now):
    """Estado actual para la pantalla de caja: cajas, sesión abierta de cada una, fondo pendiente e incidencias."""
    regs = []
    for r in registers(c):
        s = c.execute("SELECT * FROM cash_sessions WHERE register_id=? AND status IN ('abierta','arqueo')", (r['id'],)).fetchone()
        last = c.execute("SELECT id,status FROM cash_sessions WHERE register_id=? AND status NOT IN ('abierta','arqueo') ORDER BY id DESC LIMIT 1", (r['id'],)).fetchone()
        cashier = c.execute('SELECT name FROM users WHERE id=?', (s['cashier_id'],)).fetchone()['name'] if s else ''
        regs.append({**r, 'session': {'id': s['id'], 'code': code_of(s), 'status': s['status'], 'status_label': STATUS[s['status']], 'cashier': cashier, 'cashier_id': s['cashier_id'],
                                      'opened_at': s['opened_at'], 'shift': s['shift']} if s else None,
                     'last': {'id': last['id'], 'code': 'CJ-%06d' % last['id'], 'status': last['status'], 'status_label': STATUS[last['status']]} if last else None,
                     'pending_fund': pending_fund(c, r['id'])})
    users = [dict(u) for u in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN ('administrador','tecnico') ORDER BY name")] if is_admin(user) else []
    return {'registers': regs, 'shifts': list(SHIFTS), 'denominations': denominations(c), 'in_kinds': IN_KINDS, 'out_kinds': OUT_KINDS, 'admin_out': list(ADMIN_OUT), 'methods': METHODS,
            'accounts': banking.listing(c, active_only=True), 'users': users, 'incidents': incidents(c), 'can_admin': is_admin(user), 'me': user['id'],
            'me_name': user['name'], 'next_code': 'CJ-%06d' % next_id(c, 'cash_sessions'), 'indicators': indicators(c, now), **{k: v for k, v in settings(c).items() if k != 'updated_at'}}


def incidents(c):
    """Cobros registrados sin una caja abierta (después de empezar a usar sesiones): quedan para asignarlos a una sesión."""
    first = c.execute('SELECT MIN(opened_at) FROM cash_sessions').fetchone()[0]
    if not first:
        return []
    return [{'ref': 'PAG-%d' % r['id'], 'id': r['id'], 'order': r['code'], 'amount_cents': r['amount_cents'], 'method': r['method'], 'at': r['created_at'], 'actor': r['actor']}
            for r in c.execute("SELECT p.id,p.amount_cents,p.method,p.created_at,o.code,COALESCE(u.name,'') actor FROM order_payments p JOIN orders o ON o.id=p.order_id LEFT JOIN users u ON u.id=p.created_by "
                               "WHERE p.cash_session_id IS NULL AND p.voided_at IS NULL AND p.created_at>=? ORDER BY p.id", (first,))]


def assign_incident(c, user, data, now):
    if not is_admin(user):
        raise CashError('Solo administración asigna cobros a una sesión.', 403)
    pid, sid = str(data.get('payment_id', '')), str(data.get('session_id', ''))
    s = _session(c, sid)
    if s['status'] not in OPEN:
        raise CashError('Solo se asigna a una caja abierta.', 409)
    row = c.execute('SELECT id,cash_session_id FROM order_payments WHERE id=?', (pid,)).fetchone() if pid.isdigit() else None
    if not row or row['cash_session_id']:
        raise CashError('Cobro no disponible.', 404)
    c.execute('UPDATE order_payments SET cash_session_id=? WHERE id=?', (s['id'], row['id']))
    event(c, 'sesion', s['id'], 'cobro_asignado', 'Cobro PAG-%d registrado sin caja abierta, asignado a esta sesión.' % row['id'], user, now)


def indicators(c, now):
    today = now.date().isoformat()
    open_rows = c.execute("SELECT * FROM cash_sessions WHERE status IN ('abierta','arqueo')").fetchall()
    available, electronic, outgo, received, pending_rec = 0, 0, 0, 0, 0
    for s in open_rows:
        d = summary(c, s)
        available += d['expected_cash_cents']
        electronic += sum(v['in_cents'] for k, v in d['by_method'].items() if k != 'efectivo')
        outgo += d['outgo_cents']
        received += d['received_cents']
        pending_rec += len(d['pending'])
    sales = c.execute("SELECT COUNT(*),COALESCE(SUM(total_cents),0) FROM invoices WHERE status IN ('pendiente','enviado','autorizado') AND substr(emitted_at,1,10)=?", (today,)).fetchone()
    import equipment
    dues = c.execute('SELECT COALESCE(SUM(MAX(' + equipment.BUDGET + '-' + equipment.PAID + ",0)),0) FROM orders o WHERE o.status!='entregado'").fetchone()[0]
    closed = c.execute("SELECT COUNT(*) FROM cash_session_closings WHERE substr(closed_at,1,10)=?", (today,)).fetchone()[0]
    diff = c.execute("SELECT COALESCE(SUM(k.difference_cents),0) FROM cash_session_closings k JOIN cash_sessions s ON s.id=k.session_id WHERE s.status!='anulada'").fetchone()[0]
    transfers = c.execute("SELECT COUNT(*) FROM bank_transfers WHERE status='pendiente'").fetchone()[0]
    cards = c.execute("SELECT COUNT(*) FROM card_vouchers WHERE status IN ('registrada','autorizada','pendiente_liquidacion')").fetchone()[0]
    return {'sales_count': sales[0], 'sales_cents': sales[1], 'received_cents': received, 'cash_available_cents': available, 'electronic_cents': electronic, 'outgo_cents': outgo,
            'receivable_cents': dues, 'closings_today': closed, 'open_registers': len(open_rows), 'difference_cents': diff, 'pending_reconciliation': transfers + cards + pending_rec}


# ---- Movimientos ----------------------------------------------------------------------------------------------------------

def add_movement(c, user, data, now, file_id=None):
    s = _session(c, data.get('session_id'))
    if not (is_admin(user) or s['cashier_id'] == user['id']):
        raise CashError('Solo el cajero de esta sesión o administración registran movimientos.', 403)
    if s['status'] != 'abierta':
        raise CashError('La caja no está abierta: %s.' % STATUS[s['status']].lower(), 409)
    key = str(data.get('request_key', '') or '').strip()
    if key and not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
        raise CashError('Solicitud no válida. Recarga la página.', 400)
    if key:
        same = c.execute('SELECT id,session_id,amount_cents FROM cash_movements WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id'], True
    direction = str(data.get('direction', ''))
    kinds = IN_KINDS if direction == 'ingreso' else OUT_KINDS if direction == 'egreso' else None
    if not kinds:
        raise CashError('Indica si es un ingreso o un egreso.', 400, {'direction': 'Opción no válida.'})
    kind = str(data.get('kind', ''))
    if kind not in kinds:
        raise CashError('Elige el tipo.', 400, {'kind': 'Tipo no válido.'})
    if direction == 'egreso' and kind in ADMIN_OUT and not is_admin(user):
        raise CashError('Este egreso requiere autorización administrativa: debe registrarlo administración.', 403, {'kind': 'Requiere administración.'})
    method = str(data.get('method', ''))
    if method not in METHODS:
        raise CashError('Elige el método.', 400, {'method': 'Método no válido.'})
    amount = cents_of(data.get('amount', ''))
    concept = _text(data, 'concept', 200, 3, 'El concepto')
    beneficiary = _text(data, 'beneficiary', 160, 3 if direction == 'egreso' else 0, 'El beneficiario')
    document = _text(data, 'document', 60, 0, 'El documento')
    reference = _text(data, 'reference', 60, 0, 'La referencia')
    note = _text(data, 'note', 300, 0, 'La observación')
    account = None
    if method in ('transferencia', 'deposito') or kind == 'deposito_banco':
        try:
            account = banking.get(c, data.get('bank_account_id'), active=True)
        except banking.BankError:
            raise CashError('Elige la cuenta bancaria.', 400, {'bank_account_id': 'Cuenta no disponible.'})
        if not reference:
            raise CashError('Indica la referencia bancaria.', 400, {'reference': 'Referencia obligatoria.'})
    if kind == 'deposito_banco' and method != 'efectivo':
        raise CashError('Un depósito desde caja sale en efectivo.', 400, {'method': 'Usa efectivo.'})
    if direction == 'egreso' and method == 'efectivo':
        available = summary(c, s)['expected_cash_cents']
        if amount > available:
            raise CashError('No hay suficiente efectivo en caja (%s disponibles).' % usd(available), 409, {'amount': 'Supera el efectivo disponible.'})
    client = str(data.get('client_id', '') or '')
    client_id = int(client) if client.isdigit() and c.execute('SELECT 1 FROM clients WHERE id=?', (int(client),)).fetchone() else None
    authorized = user['name'] if (direction == 'egreso' and kind in ADMIN_OUT) else ''
    mid = c.execute('INSERT INTO cash_movements(session_id,direction,kind,method,amount_cents,concept,beneficiary,client_id,document,reference,bank_account_id,authorized_by,note,file_id,request_key,created_by,created_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (s['id'], direction, kind, method, amount, concept, beneficiary, client_id, document, reference, account['id'] if account else None,
                                                                 authorized, note, file_id, key or None, user['id'], stamp(now))).lastrowid
    event(c, 'sesion', s['id'], 'movimiento', '%s CJM-%d: %s · %s · %s%s.' % ('Ingreso' if direction == 'ingreso' else 'Egreso', mid, kinds[kind], METHODS[method], usd(amount),
                                                                              (' · autorizado por ' + authorized) if authorized else ''), user, now)
    return mid, False


def void_movement(c, user, data, now):
    if not is_admin(user):
        raise CashError('Solo administración anula movimientos de caja.', 403)
    row = c.execute('SELECT * FROM cash_movements WHERE id=?', (str(data.get('movement_id', '')),)).fetchone() if str(data.get('movement_id', '')).isdigit() else None
    if not row:
        raise CashError('Movimiento no encontrado.', 404)
    if row['voided_at']:
        raise CashError('Ese movimiento ya estaba anulado.', 409)
    s = _session(c, row['session_id'])
    if s['status'] not in OPEN:
        raise CashError('La sesión ya se cerró: registra un ajuste posterior con su motivo.', 409)
    reason = _text(data, 'reason', 300, 10, 'El motivo de la anulación')
    c.execute('UPDATE cash_movements SET voided_at=?,voided_by=?,void_reason=? WHERE id=?', (stamp(now), user['id'], reason, row['id']))
    event(c, 'sesion', s['id'], 'movimiento_anulado', 'Movimiento CJM-%d anulado: %s' % (row['id'], reason), user, now)


# ---- Arqueo y cierre ------------------------------------------------------------------------------------------------------

def save_count(c, user, data, now):
    """Guarda el arqueo de cierre como borrador (la caja pasa a «En proceso de arqueo») o vuelve a la caja abierta."""
    s = _session(c, data.get('session_id'))
    if not (is_admin(user) or s['cashier_id'] == user['id']):
        raise CashError('Solo el cajero de esta sesión o administración hacen el arqueo.', 403)
    if s['status'] not in OPEN:
        raise CashError('La caja no está abierta.', 409)
    if str(data.get('action', '')) == 'resume':
        c.execute("UPDATE cash_sessions SET status='abierta' WHERE id=? AND status='arqueo'", (s['id'],))
        event(c, 'sesion', s['id'], 'arqueo_pausado', 'Se volvió a la caja abierta; el arqueo queda como borrador.', user, now)
        return None
    count = count_of(c, data.get('counts', '[]'))
    c.execute('INSERT INTO cash_counts(session_id,stage,counts,coins_cents,bills_cents,total_cents,final,updated_at,updated_by) VALUES (?,?,?,?,?,?,0,?,?) '
              'ON CONFLICT(session_id,stage) DO UPDATE SET counts=excluded.counts,coins_cents=excluded.coins_cents,bills_cents=excluded.bills_cents,total_cents=excluded.total_cents,'
              'updated_at=excluded.updated_at,updated_by=excluded.updated_by', (s['id'], 'cierre', json.dumps(count['rows']), count['coins_cents'], count['bills_cents'], count['total_cents'], stamp(now), user['id']))
    if s['status'] == 'abierta':
        c.execute("UPDATE cash_sessions SET status='arqueo' WHERE id=? AND status='abierta'", (s['id'],))
    event(c, 'sesion', s['id'], 'arqueo_borrador', 'Arqueo guardado como borrador: %s contados.' % usd(count['total_cents']), user, now)
    return count


def difference_type(cents):
    return 'cuadrado' if cents == 0 else 'sobrante' if cents > 0 else 'faltante'


def close(c, user, data, now):
    """Cierre definitivo. Transacción única: comprueba el estado, guarda la foto inmutable y cambia el estado en la misma operación."""
    s = _session(c, data.get('session_id'))
    if not (is_admin(user) or s['cashier_id'] == user['id']):
        raise CashError('Solo el cajero de esta sesión o administración cierran la caja.', 403)
    if s['status'] not in OPEN:
        raise CashError('No se puede cerrar: la caja no está abierta (%s).' % STATUS[s['status']].lower(), 409)
    if c.execute('SELECT 1 FROM cash_session_closings WHERE session_id=?', (s['id'],)).fetchone():
        raise CashError('Esta caja ya tiene un cierre registrado.', 409)
    count = count_of(c, data.get('counts', '[]'))
    data_sum = summary(c, s)
    expected = data_sum['expected_cash_cents']
    difference = count['total_cents'] - expected
    reason = _text(data, 'difference_reason', 300, 10 if difference else 0, 'La explicación de la diferencia')
    reserved = cents_of(data.get('reserved', '0') or '0', 'reserved', allow_zero=True)
    if reserved > count['total_cents']:
        raise CashError('No se puede reservar más efectivo del contado (%s).' % usd(count['total_cents']), 400, {'reserved': 'Supera el efectivo contado.'})
    withdrawn = count['total_cents'] - reserved
    delivered_to = _text(data, 'delivered_to', 120, 5 if withdrawn else 0, 'Quién recibe el efectivo entregado')
    note = _text(data, 'note', 500, 0, 'Las observaciones')
    if str(data.get('confirm', '')) not in ('1', 'true', 'on'):
        raise CashError('Confirma expresamente el cierre.', 400, {'confirm': 'Confirmación obligatoria.'})
    confirmed = _text(data, 'confirmed_name', 120, 5, 'El nombre de quien confirma')
    limit = settings(c)['difference_limit_cents']
    status = 'cerrada' if difference == 0 else 'cerrada_diferencia' if abs(difference) <= limit else 'revision'
    snapshot = {k: v for k, v in data_sum.items() if k != 'rows'}
    snapshot['rows'] = data_sum['rows']
    try:
        c.execute('INSERT INTO cash_session_closings(session_id,closed_at,closed_by,confirmed_name,expected_cash_cents,counted_cash_cents,difference_cents,difference_reason,reserved_cents,'
                  'withdrawn_cents,delivered_by,delivered_to,summary,counts,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (s['id'], stamp(now), user['id'], confirmed, expected, count['total_cents'], difference, reason, reserved, withdrawn, user['name'], delivered_to,
                   json.dumps(snapshot, ensure_ascii=False), json.dumps(count['rows']), note))
    except sqlite3.IntegrityError:
        raise CashError('Esta caja ya se cerró en otra sesión.', 409)
    changed = c.execute("UPDATE cash_sessions SET status=? WHERE id=? AND status IN ('abierta','arqueo')", (status, s['id'])).rowcount
    if changed != 1:
        raise CashError('El estado de la caja cambió mientras se cerraba. Recarga la página.', 409)
    c.execute('INSERT INTO cash_counts(session_id,stage,counts,coins_cents,bills_cents,total_cents,final,updated_at,updated_by) VALUES (?,?,?,?,?,?,1,?,?) '
              'ON CONFLICT(session_id,stage) DO UPDATE SET counts=excluded.counts,coins_cents=excluded.coins_cents,bills_cents=excluded.bills_cents,total_cents=excluded.total_cents,final=1,'
              'updated_at=excluded.updated_at,updated_by=excluded.updated_by', (s['id'], 'cierre', json.dumps(count['rows']), count['coins_cents'], count['bills_cents'], count['total_cents'], stamp(now), user['id']))
    event(c, 'sesion', s['id'], 'cierre', 'Cierre: esperado %s, contado %s, diferencia %s (%s); reservado para el siguiente turno %s, entregado %s%s.' % (
        usd(expected), usd(count['total_cents']), usd(difference), difference_type(difference), usd(reserved), usd(withdrawn), (' a ' + delivered_to) if withdrawn else ''), user, now)
    return {'status': status, 'difference_cents': difference, 'expected_cents': expected, 'counted_cents': count['total_cents']}


def review(c, user, data, now):
    if not is_admin(user):
        raise CashError('Solo administración revisa las diferencias de caja.', 403)
    s = _session(c, data.get('session_id'))
    if s['status'] != 'revision':
        raise CashError('Esta caja no está pendiente de revisión.', 409)
    note = _text(data, 'review_note', 300, 10, 'La observación de la revisión')
    c.execute("UPDATE cash_sessions SET status='cerrada_diferencia',reviewed_by=?,reviewed_at=?,review_note=? WHERE id=? AND status='revision'", (user['id'], stamp(now), note, s['id']))
    event(c, 'sesion', s['id'], 'revision', 'Diferencia revisada y aprobada por administración: ' + note, user, now)


def adjust(c, user, data, now):
    if not is_admin(user):
        raise CashError('Solo administración registra ajustes posteriores.', 403)
    s = _session(c, data.get('session_id'))
    if s['status'] in OPEN or s['status'] == 'anulada':
        raise CashError('Los ajustes se registran sobre una caja cerrada.', 409)
    sign = -1 if str(data.get('sign', '+')) == '-' else 1
    amount = cents_of(data.get('amount', '')) * sign
    reason = _text(data, 'reason', 300, 10, 'El motivo del ajuste')
    aid = c.execute('INSERT INTO cash_adjustments(session_id,amount_cents,reason,created_by,created_at) VALUES (?,?,?,?,?)', (s['id'], amount, reason, user['id'], stamp(now))).lastrowid
    event(c, 'sesion', s['id'], 'ajuste', 'Ajuste posterior %s: %s (el cierre original no cambia).' % (usd(amount), reason), user, now)
    return aid


def void_session(c, user, data, now):
    if not is_admin(user):
        raise CashError('Solo administración anula una sesión de caja.', 403)
    s = _session(c, data.get('session_id'))
    if s['status'] not in OPEN:
        raise CashError('Solo se anula una caja abierta sin operaciones; una caja cerrada se corrige con ajustes.', 409)
    if [r for r in _rows(c, s) if not r['voided']]:
        raise CashError('La caja tiene operaciones registradas: ciérrala con su arqueo.', 409)
    reason = _text(data, 'reason', 300, 10, 'El motivo de la anulación')
    c.execute("UPDATE cash_sessions SET status='anulada',voided_by=?,voided_at=?,void_reason=? WHERE id=?", (user['id'], stamp(now), reason, s['id']))
    event(c, 'sesion', s['id'], 'anulada', 'Sesión anulada por administración: ' + reason, user, now)


def history(c, user, f):
    """HISTORIAL Y AUDITORÍA DE CAJAS: un cajero ve sus sesiones; administración, todas. Filtros por fecha, cajero, caja, estado, tipo de diferencia y método."""
    where, args = ['1=1'], []
    if not is_admin(user):
        where.append('s.cashier_id=?')
        args.append(user['id'])
    elif str(f.get('cashier', '')).isdigit():
        where.append('s.cashier_id=?')
        args.append(int(f['cashier']))
    if str(f.get('register', '')).isdigit():
        where.append('s.register_id=?')
        args.append(int(f['register']))
    if f.get('status') in STATUS:
        where.append('s.status=?')
        args.append(f['status'])
    for key, op in (('from', '>='), ('to', '<=')):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(f.get(key, ''))):
            where.append('substr(s.opened_at,1,10)' + op + '?')
            args.append(f[key])
    if f.get('difference') in ('cuadrado', 'sobrante', 'faltante'):
        where.append({'cuadrado': 'k.difference_cents=0', 'sobrante': 'k.difference_cents>0', 'faltante': 'k.difference_cents<0'}[f['difference']])
    rows = []
    for r in c.execute("SELECT s.*,g.name register,u.name cashier,COALESCE(v.name,'') reviewer,k.closed_at,k.expected_cash_cents,k.counted_cash_cents,k.difference_cents FROM cash_sessions s "
                       "JOIN cash_registers g ON g.id=s.register_id JOIN users u ON u.id=s.cashier_id LEFT JOIN users v ON v.id=s.reviewed_by LEFT JOIN cash_session_closings k ON k.session_id=s.id WHERE "
                       + ' AND '.join(where) + ' ORDER BY s.id DESC LIMIT 300', args):
        d = summary(c, r)
        if f.get('method') in METHODS and not d['by_method'][f['method']]['count']:
            continue
        rows.append({'id': r['id'], 'code': code_of(r), 'register': r['register'], 'cashier': r['cashier'], 'shift': r['shift'], 'opened_at': r['opened_at'], 'closed_at': r['closed_at'] or '',
                     'opening_cents': r['opening_cents'], 'income_cents': d['income_cents'], 'outgo_cents': d['outgo_cents'],
                     'expected_cents': r['expected_cash_cents'] if r['expected_cash_cents'] is not None else d['expected_cash_cents'], 'counted_cents': r['counted_cash_cents'],
                     'difference_cents': r['difference_cents'], 'difference_type': difference_type(r['difference_cents']) if r['difference_cents'] is not None else '',
                     'status': r['status'], 'status_label': STATUS[r['status']], 'authorized_by': r['reviewer']})
    return {'rows': rows, 'statuses': STATUS, 'registers': registers(c, False), 'methods': METHODS,
            'cashiers': [dict(u) for u in c.execute("SELECT id,name FROM users WHERE role IN ('administrador','tecnico') ORDER BY name")] if is_admin(user) else []}


# ---- Reporte oficial de cierre (A4 y térmico 80 mm) -----------------------------------------------------------------------------

def report_pdf(c, user, session_id, link, thermal=False):
    d = view(c, user, session_id)
    s, data, closing = d['session'], d['summary'], d['closing']
    from document_canvas import Canvas, BLUE, GRAY
    from corporate import settings
    company = settings()
    lines = []  # (texto, tamaño, negrita, sangría)

    def add(text, size=8, bold=False, indent=0):
        lines.append((text, size, bold, indent))
    title = 'REPORTE OFICIAL DE CIERRE DE CAJA'
    add('PC-DOCTOR S.A. — ' + title, 11 if not thermal else 8, True)
    add('%s · RUC %s' % (company.get('name', 'PC-DOCTOR S.A.'), company.get('ruc', '') or '—'), 7.5)
    add('Cierre %s · %s · turno %s' % (s['code'], s['register'], s['shift']), 9 if not thermal else 7.5, True)
    add('Estado: %s' % s['status_label'], 8)
    add('Cajero: %s · abrió: %s' % (s['cashier'], s['opened_by_name']), 8)
    add('Apertura: %s' % _dt(s['opened_at']), 8)
    if closing:
        add('Cierre: %s · confirmado por %s' % (_dt(closing['closed_at']), closing['confirmed_name']), 8)
    add('', 4)
    add('INGRESOS DEL PERÍODO', 9, True)
    add('Monto de apertura: %s' % usd(s['opening_cents']), 8, False, 8)
    for key, g in data['income_groups'].items():
        add('%s (%d): %s' % (g['label'], g['count'], usd(g['cents'])), 8, False, 8)
    add('Total de ingresos: %s' % usd(data['income_cents']), 8, True, 8)
    add('EGRESOS Y SALIDAS DE CAJA', 9, True)
    for key, g in data['outgo_groups'].items():
        add('%s (%d): %s' % (g['label'], g['count'], usd(g['cents'])), 8, False, 8)
    add('Total de egresos: %s' % usd(data['outgo_cents']), 8, True, 8)
    add('MÉTODOS DE PAGO', 9, True)
    for key, m in data['by_method'].items():
        if m['count']:
            add('%s: entradas %s · salidas %s (%d)' % (METHODS[key], usd(m['in_cents']), usd(m['out_cents']), m['count']), 8, False, 8)
    if data['vouchers']:
        add('OPERACIONES CON TARJETA', 9, True)
        for v in data['vouchers']:
            add('%s %s · %s · lote %s · aut. %s · %s · comisión %s · neto %s · %s' % (v['brand'], v['issuer_bank'], v['tx_type'].replace('_', ' '), v['lot'], v['approval_code'],
                                                                                    usd(v['amount_cents']), usd(v['commission_cents'] + v['commission_tax_cents']),
                                                                                    usd(v['net_cents']) if v['net_cents'] is not None else 'por liquidar', v['status'].replace('_', ' ')), 7.5, False, 8)
    if data['transfers']:
        add('TRANSFERENCIAS Y DEPÓSITOS', 9, True)
        for t in data['transfers']:
            add('%s %s · %s · ref. %s · %s · %s' % (t['code'], t['method'], t['account'], t['reference'], usd(t['amount_cents']), t['status']), 7.5, False, 8)
    add('ARQUEO DE EFECTIVO — DENOMINACIONES USD', 9, True)
    counted_rows = closing['counts'] if closing else (d['counts'].get('cierre') or {}).get('counts', [])
    for r in counted_rows:
        add('%s %s × %d = %s' % ('Moneda' if r['kind'] == 'moneda' else 'Billete', usd(r['value_cents']), r['qty'], usd(r['subtotal_cents'])), 8, False, 8)
    expected = closing['expected_cash_cents'] if closing else data['expected_cash_cents']
    add('Efectivo esperado: %s' % usd(expected), 8, True, 8)
    if closing:
        add('Efectivo contado: %s' % usd(closing['counted_cash_cents']), 8, True, 8)
        add('Diferencia: %s (%s)' % (usd(closing['difference_cents']), difference_type(closing['difference_cents'])), 8, True, 8)
        if closing['difference_reason']:
            add('Explicación: ' + closing['difference_reason'], 8, False, 8)
        add('Reservado para el siguiente turno: %s · entregado: %s%s' % (usd(closing['reserved_cents']), usd(closing['withdrawn_cents']),
                                                                         (' a ' + closing['delivered_to']) if closing['withdrawn_cents'] else ''), 8, False, 8)
        if closing['note']:
            add('Observaciones: ' + closing['note'], 8, False, 8)
    if s['reviewed_by_name']:
        add('Autorizado por: %s · %s' % (s['reviewed_by_name'], s['review_note']), 8)
    for a in data['adjustments']:
        add('Ajuste posterior %s: %s (%s)' % (usd(a['amount_cents']), a['reason'], a['actor']), 7.5, False, 8)
    if data['pending']:
        add('Pendientes de conciliación: %d' % len(data['pending']), 8, True)
    if thermal:
        width = 204
        margin = 8
        wrapped = []
        probe = Canvas(width + 2 * margin, 100, 'Cierre ' + s['code'], mono=True)
        for text, size, bold, indent in lines:
            for piece in probe.wrap(text, width - indent, size) or ['']:
                wrapped.append((piece, size, bold, indent))
        height = 60 + sum(size * 1.45 for _, size, _, _ in wrapped) + 150
        pdf = Canvas(width + 2 * margin, height, 'Cierre ' + s['code'], mono=True)
        pdf.page()
        y = 8 + pdf.logo(margin + 40, 8, width - 80) + 8
        for text, size, bold, indent in wrapped:
            pdf.text(text, margin + indent / 2, y, size, bold)
            y += size * 1.45
        y += 10
        pdf.text('Firma del cajero: ______________________', margin, y, 7.5)
        pdf.text('Firma del administrador: _______________', margin, y + 14, 7.5)
        if link:
            pdf.qr(link, margin + width / 2 - 40, y + 26, 80)
        return pdf.finish()
    pdf = Canvas(595, 842, 'Cierre ' + s['code'])
    margin, width = 40, 515
    pages, page_lines = [], []
    y0 = 120
    y = y0
    for text, size, bold, indent in lines:
        for piece in pdf.wrap(text, width - indent, size) or ['']:
            if y > 760:
                pages.append(page_lines)
                page_lines, y = [], 60
            page_lines.append((piece, size, bold, indent, y))
            y += size * 1.5
    pages.append(page_lines)
    for number, chunk in enumerate(pages, 1):
        pdf.page()
        if number == 1:
            pdf.logo(margin, 30, 120)
            if link:
                pdf.qr(link, 595 - margin - 70, 26, 70)
                pdf.text('Consulta interna (requiere sesión)', 595 - margin - 150, 98, 6.5, False, GRAY)
        for text, size, bold, indent, yy in chunk:
            pdf.text(text, margin + indent, yy, size, bold, BLUE if bold and size >= 9 else (.10, .15, .22))
        pdf.text('Página %d de %d · generado %s' % (number, len(pages), _dt(datetime.now().isoformat())), margin, 812, 7, False, GRAY)
    pdf.text('Firma del cajero', margin + 20, 790, 8)
    pdf.line(margin, 786, 200)
    pdf.text('Firma del administrador', 595 - margin - 180, 790, 8)
    pdf.line(595 - margin - 200, 786, 200)
    return pdf.finish()


def _dt(value):
    try:
        return datetime.fromisoformat(str(value)).strftime('%d/%m/%Y %H:%M')
    except ValueError:
        return str(value or '')


# ---- Comprobantes adjuntos (transferencias, vouchers, sustentos) ---------------------------------------------------------------

def store_file(c, user, upload_id, name, kind, now):
    """Recompone una subida por partes (ya validada: JPG, PNG o PDF de hasta 5 MB) y la guarda como comprobante. Devuelve su id o None."""
    import cash
    import hashlib
    if not upload_id:
        return None
    if kind not in ('transferencia', 'voucher', 'egreso', 'ingreso', 'anticipo'):
        raise CashError('Tipo de comprobante no válido.')
    try:
        raw, mime, clean_name = cash._assemble(c, user, str(upload_id), name)
    except cash.CashError as error:
        raise CashError(str(error), error.status, error.fields)
    fid = c.execute('INSERT INTO payment_files(kind,name,mime,size,sha256,data,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (kind, clean_name, mime, len(raw), hashlib.sha256(raw).hexdigest(), raw, user['id'], stamp(now))).lastrowid
    c.execute('DELETE FROM cash_upload_parts WHERE upload_id=?', (str(upload_id),))
    return fid


def file_for(c, user, owner, owner_id):
    """Archivo de un movimiento, transferencia o voucher. Solo administración o quien lo registró."""
    table = {'movimiento': 'cash_movements', 'transferencia': 'bank_transfers', 'voucher': 'card_vouchers'}.get(owner)
    row = c.execute('SELECT file_id,created_by FROM ' + table + ' WHERE id=?', (owner_id,)).fetchone() if table and str(owner_id).isdigit() else None
    if not row or not row['file_id'] or not (is_admin(user) or row['created_by'] == user['id']):
        raise CashError('Comprobante no disponible.', 404)
    f = c.execute('SELECT name,mime,data FROM payment_files WHERE id=?', (row['file_id'],)).fetchone()
    return f['name'], f['mime'], bytes(f['data'])
