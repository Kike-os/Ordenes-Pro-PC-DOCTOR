"""ADI 3.0 · fases 4 y 5: ADI Smart Collections (centro de cartera), expediente económico del cliente, marcas de gestión, equipos
pendientes de retiro, auditoría de comunicaciones y propuestas de seguimiento por eventos (docs/ADI-CARTERA.md).

Fuente única: los mismos cargos y pagos de la tarjeta financiera de cada orden (equipment.BUDGET / PAID y los pagos generales), consolidados
por orden una sola vez: una obligación no se suma dos veces por estar ligada a orden, presupuesto y factura. Una factura autorizada no es una
factura pagada. Nada de este módulo registra pagos, cambia saldos, aplica intereses, envía mensajes ni dispone de equipos: solo calcula,
muestra, guarda marcas de gestión (migración 121) y PROPONE mensajes que una persona revisa y envía por el flujo habitual.

Exigibilidad (criterio operativo, revisable jurídicamente): un saldo es exigible desde la ENTREGA del equipo o desde la fecha acordada de un
compromiso de pago; mientras el equipo está en el taller o listo para retirar, el saldo está «por vencer» (se paga al retirar). Nunca se
cuenta mora desde la fecha de ingreso."""
import re
from datetime import date, datetime, timedelta

READY = ('listo', 'espera_entrega')
AGES = (('sin_atraso', 'Sin atraso'), ('1_30', '1 a 30 días'), ('31_60', '31 a 60 días'), ('61_90', '61 a 90 días'), ('mas_90', 'Más de 90 días'))
FLAG_KINDS = {'suspension': 'Recordatorios suspendidos', 'derivacion': 'Derivado a administración', 'observacion': 'Observación administrativa',
              'conciliacion': 'Conciliación solicitada'}
MILESTONES = (7, 15, 30, 60, 85, 90)            # días de retraso que generan una propuesta de seguimiento
PICKUP_ALERTS = (30, 60, 85, 90)               # días desde que el equipo quedó listo
RECENT_DAYS = 3                                 # una gestión en estos días frena nuevas propuestas
NOT_INSTALLED = 'Las marcas de cartera necesitan la migración 121 (Sistema → Migraciones).'


class CollectionsError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def _has(c, table):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _day(value):
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def usd(cents):
    whole, frac = divmod(abs(int(cents or 0)), 100)
    return ('-' if int(cents or 0) < 0 else '') + '$%s,%02d' % (format(whole, ',d').replace(',', '.'), frac)


# Estado financiero → (etiqueta, tono). Lo decide el servidor con reglas verificables; nunca la IA.
STATE_LABELS = {'pago_al_retirar': ('Pago al retirar', 'celeste'), 'por_vencer': ('Por vencer', 'azul'), 'vence_hoy': ('Vence hoy', 'amarillo'),
                'pago_vencido': ('Pago vencido', 'naranja'), 'mora_90': ('Mora superior a 90 días', 'rojo'), 'pendiente_conciliacion': ('Pendiente de conciliación', 'violeta'),
                'acuerdo_vigente': ('Acuerdo de pago vigente', 'azul'), 'compromiso_incumplido': ('Compromiso incumplido', 'naranja'), 'pagado': ('Pago completado', 'verde'),
                'en_revision': ('En revisión', 'gris'), 'saldo_a_favor': ('Saldo a favor del cliente', 'verde'), 'requiere_revision': ('Requiere revisión', 'gris')}


def device_label(members):
    """Equipos sin repetir la marca («HP HP 240» → «HP 240») ni el mismo equipo varias veces."""
    out = []
    for m in members:
        brand, model = (m.get('brand') or '').strip(), (m.get('model') or '').strip()
        name = model if brand and model.lower().startswith(brand.lower()) else ' '.join(x for x in (brand, model) if x)
        if name and name not in out:
            out.append(name)
    return ' · '.join(out) or 'Equipo'


def _age(days):
    if days is None or days <= 0:
        return 'sin_atraso'
    return '1_30' if days <= 30 else '31_60' if days <= 60 else '61_90' if days <= 90 else 'mas_90'


def _mask(phone):
    digits = re.sub(r'\D', '', phone or '')
    return '…' + digits[-2:] if len(digits) >= 4 else ''


# ---- Cartera ---------------------------------------------------------------------------------------------------------------------------

def _units(c, client_id=None):
    import equipment
    where, args = ('WHERE d.client_id=?', (client_id,)) if client_id else ('', ())
    return [dict(r) for r in c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,COALESCE(o.group_id,o.id) main_id,o.status status_code,s.label status,"
                                       "o.delivered_at,o.received_at,o.created_at,cl.id client_id,cl.name client,COALESCE(cl.phone,'') phone,d.brand,d.model,"
                                       + equipment.BUDGET + " budget_cents," + equipment.PAID + " paid_cents FROM orders o JOIN devices d ON d.id=o.device_id "
                                       "JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status " + where + " ORDER BY o.id", args)]


def _commitments(c, today):
    import payment_commitments as pc
    if not pc.installed(c):
        return {}
    out = {}
    for row in c.execute("SELECT * FROM payment_commitments WHERE status NOT IN ('reprogramado','cancelado') ORDER BY id"):
        st, paid, pending = pc.state(c, row, today)
        if st in ('cumplido',):
            continue
        out[row['order_id']] = {'id': row['id'], 'state': st, 'state_label': pc.STATES[st], 'amount_cents': row['amount_cents'], 'due_date': row['due_date'],
                                'method': row['method'], 'paid_since_cents': paid, 'pending_transfer': pending}
    return out


def flags(c, client_id=None, active_only=True):
    if not _has(c, 'collection_flags'):
        return []
    sql, args = 'SELECT f.*,COALESCE(u.name,\'\') user FROM collection_flags f LEFT JOIN users u ON u.id=f.user_id', []
    cond = []
    if client_id:
        cond.append('f.client_id=?')
        args.append(client_id)
    if active_only:
        cond.append("f.closed_at=''")
    rows = [dict(r, kind_label=FLAG_KINDS.get(r['kind'], r['kind'])) for r in c.execute(sql + (' WHERE ' + ' AND '.join(cond) if cond else '') + ' ORDER BY f.id DESC', args)]
    today = date.today().isoformat()
    return [r for r in rows if not (active_only and r['kind'] == 'suspension' and r['until'] and r['until'] < today)]


def portfolio(c, now, filters=None, client_id=None):
    """Cartera consolidada por orden con saldo (o saldo a favor), indicadores y filtros. Valores solo de los registros existentes."""
    import equipment
    import interest_engine as ie
    filters = filters or {}
    today = now.date()
    units = _units(c, client_id)
    groups = {}
    for u in units:
        groups.setdefault(u['main_id'], []).append(u)
    free = {main: equipment.general(c, main)[1] for (main,) in c.execute("SELECT DISTINCT order_id FROM order_payments WHERE scope='general'").fetchall()} if units else {}
    commitments = _commitments(c, today)
    pending = {}
    for row in c.execute("SELECT COALESCE(o.group_id,o.id) main,COUNT(*),COALESCE(SUM(t.amount_cents),0) FROM bank_transfers t JOIN order_payments p ON p.id=t.payment_id "
                         "JOIN orders o ON o.id=p.order_id WHERE p.voided_at IS NULL AND t.status='pendiente' GROUP BY COALESCE(o.group_id,o.id)"):
        pending[row[0]] = (row[1], row[2])
    invoices = {}
    if _has(c, 'invoices'):
        import invoicing
        for r in c.execute("SELECT * FROM invoices WHERE order_id IS NOT NULL AND status NOT IN ('borrador','descartado') ORDER BY id"):
            invoices.setdefault(r['order_id'], []).append({'id': r['id'], 'number': invoicing.number(r), 'status': r['status'], 'status_label': invoicing.STATUS.get(r['status'], r['status'])})
    last_pay = {}
    for r in c.execute("SELECT COALESCE(o.group_id,o.id) main,p.method,MAX(p.created_at) at FROM order_payments p JOIN orders o ON o.id=p.order_id "
                       "WHERE p.voided_at IS NULL AND p.kind='pago' GROUP BY COALESCE(o.group_id,o.id)"):
        last_pay[r['main']] = (r['method'], r['at'])
    active_flags = {}
    for f in flags(c):
        active_flags.setdefault(f['client_id'], []).append(f)
    try:
        policy = ie.policy(c)
        table = ie._rate_table(c, policy['rate_kind'])
    except Exception:
        policy, table = ie.DEFAULT_POLICY, []
    # Coberturas, conciliación, reclamos y retiro: datos de apoyo leídos en bloque (una consulta por tipo).
    rejected, confirmed = {}, {}
    for row in c.execute("SELECT COALESCE(o.group_id,o.id) main,COUNT(*),COALESCE(SUM(p.amount_cents),0) FROM bank_transfers t JOIN order_payments p ON p.id=t.payment_id "
                         "JOIN orders o ON o.id=p.order_id WHERE p.voided_at IS NULL AND t.status='rechazado' GROUP BY COALESCE(o.group_id,o.id)"):
        rejected[row[0]] = (row[1], row[2])
    for row in c.execute("SELECT COALESCE(o.group_id,o.id) main,COALESCE(SUM(CASE WHEN p.kind='pago' THEN p.amount_cents ELSE -p.amount_cents END),0) FROM order_payments p "
                         "JOIN orders o ON o.id=p.order_id LEFT JOIN bank_transfers t ON t.payment_id=p.id WHERE p.voided_at IS NULL "
                         "AND COALESCE(t.status,'confirmado') NOT IN ('pendiente','rechazado') GROUP BY COALESCE(o.group_id,o.id)"):
        confirmed[row[0]] = row[1]
    complaints = {}
    if _has(c, 'pqrs_cases'):
        for row in c.execute("SELECT client_id,order_id,code FROM pqrs_cases WHERE category IN ('queja','reclamo') AND status!='cerrada'"):
            complaints.setdefault(('c', row['client_id']), []).append(row['code'])
            if row['order_id']:
                complaints.setdefault(('o', row['order_id']), []).append(row['code'])
    items = []
    for main, members in groups.items():
        net = sum(m['budget_cents'] - m['paid_cents'] for m in members) - free.get(main, 0)
        tr = pending.get(main, (0, 0))
        rj = rejected.get(main, (0, 0))
        if net == 0 and not tr[0] and not rj[0]:
            continue                       # sin saldo, sin transferencias por validar y sin diferencias: no es cartera
        head = next((m for m in members if m['id'] == main), members[0])
        delivered = [m for m in members if m['status_code'] == 'entregado']
        all_delivered = len(delivered) == len(members)
        delivered_at = max((m['delivered_at'] or '' for m in delivered), default='')
        ready = [m for m in members if m['status_code'] in READY]
        commit = next((commitments[m['id']] for m in members if m['id'] in commitments), None)
        cflags = active_flags.get(head['client_id'], [])
        claim = complaints.get(('o', head['id']), []) + [x for x in complaints.get(('c', head['client_id']), []) if x not in complaints.get(('o', head['id']), [])]
        due, basis, review = None, '', ''
        if commit:
            due, basis = _day(commit['due_date']), 'Compromiso de pago'
        elif all_delivered:
            if delivered_at:
                due, basis = _day(delivered_at), 'Entrega del equipo'
            else:
                review = 'Entregado sin fecha de entrega registrada: no se puede determinar desde cuándo es exigible.'
        else:
            basis = 'Se paga al retirar'
        days = (today - due).days if due and net > 0 else None
        overdue = days if days is not None and days > 0 else None
        # Estado financiero: reglas verificables, independientes del estado técnico y del de conciliación.
        if review:
            state = 'requiere_revision'
        elif rj[0] or (commit and commit['state'] == 'en_revision') or claim or any(f['kind'] in ('derivacion', 'conciliacion') for f in cflags):
            state = 'en_revision'
        elif net < 0:
            state = 'saldo_a_favor'
        elif net == 0 and tr[0]:
            state = 'pendiente_conciliacion'
        elif commit and commit['state'] in ('incumplido', 'parcial'):
            state = 'compromiso_incumplido'
        elif commit and due:
            left = (due - today).days
            state = 'vence_hoy' if left == 0 else 'por_vencer' if left <= 3 else 'acuerdo_vigente'
        elif due:
            state = 'vence_hoy' if days == 0 else 'mora_90' if overdue and overdue > 90 else 'pago_vencido' if overdue else 'vence_hoy'
        else:
            state = 'pago_al_retirar'
        paid_ok = confirmed.get(main, 0)
        if rj[0]:
            rec = ('diferencia', 'Diferencia detectada: %d transferencia(s) rechazada(s) por %s sin anular el pago' % (rj[0], usd(rj[1])))
        elif any(f['kind'] == 'conciliacion' for f in cflags):
            rec = ('en_revision', 'Conciliación en revisión')
        elif tr[0]:
            rec = ('transferencia_pendiente', 'Transferencia pendiente de validar: %s' % usd(tr[1]))
        elif paid_ok > 0 and net <= 0:
            rec = ('pago_confirmado', 'Pago confirmado')
        elif paid_ok > 0:
            rec = ('pago_parcial_confirmado', 'Pago parcial confirmado: %s' % usd(paid_ok))
        else:
            rec = ('no_aplica', 'Sin pagos registrados')
        simulated = None
        if net > 0 and commit and commit['state'] in ('incumplido', 'parcial') and table:
            try:
                sim = ie.simulate(commit['amount_cents'] - commit['paid_since_cents'], due, today, (), table, policy['grace_days'])
                simulated = int(round(float(sim['interest']) * 100))
            except ie.InterestError:
                simulated = None
        ready_at = ''
        if ready:
            for m in ready:
                row = c.execute("SELECT MIN(created_at) FROM order_status_log WHERE order_id=? AND to_status IN ('listo','espera_entrega') AND created_at>="
                                "COALESCE((SELECT MAX(created_at) FROM order_status_log WHERE order_id=? AND to_status NOT IN ('listo','espera_entrega')),'')", (m['id'], m['id'])).fetchone()[0]
                if row and (not ready_at or row < ready_at):
                    ready_at = row
        items.append({'main_id': main, 'order_id': head['id'], 'code': head['code'], 'client_id': head['client_id'], 'client': head['client'], 'phone': _mask(head['phone']),
                      'devices': device_label(members), 'units': len(members), 'status': head['status'], 'status_code': head['status_code'],
                      'all_delivered': all_delivered, 'delivered_at': delivered_at, 'charges_cents': sum(m['budget_cents'] for m in members),
                      'balance_cents': max(net, 0), 'credit_cents': max(-net, 0), 'state': state, 'state_label': STATE_LABELS[state][0], 'state_tone': 'rojo' if state == 'compromiso_incumplido' and overdue and overdue > 90 else STATE_LABELS[state][1],
                      'requires_review': review, 'claims': claim,
                      'due_date': due.isoformat() if due else '', 'due_basis': basis, 'days_overdue': overdue, 'age': _age(overdue),
                      'pickup_days': (today - _day(ready_at)).days if _day(ready_at) else None, 'ready_at': ready_at,
                      'commitment': commit, 'pending_transfers': tr[0], 'pending_cents': tr[1], 'reconciliation': rec[0], 'reconciliation_label': rec[1],
                      'confirmed_paid_cents': paid_ok, 'invoices': invoices.get(head['id'], []) + [i for m in members if m['id'] != head['id'] for i in invoices.get(m['id'], [])],
                      'last_payment_method': (last_pay.get(main) or ('', ''))[0], 'last_payment_at': (last_pay.get(main) or ('', ''))[1],
                      'simulated_interest_cents': simulated, 'flags': [{'kind': f['kind'], 'label': f['kind_label'], 'until': f['until']} for f in cflags]})
    # filtros
    q = str(filters.get('client', '') or '').strip().lower()
    oc = str(filters.get('order', '') or '').strip().lower()
    inv = str(filters.get('invoice', '') or '').strip()
    out = []
    for it in items:
        if q and q not in it['client'].lower():
            continue
        if oc and oc not in it['code'].lower():
            continue
        if inv and not any(inv in i['number'] for i in it['invoices']):
            continue
        if filters.get('due_from') and (not it['due_date'] or it['due_date'] < filters['due_from']):
            continue
        if filters.get('due_to') and (not it['due_date'] or it['due_date'] > filters['due_to']):
            continue
        if filters.get('method') and it['last_payment_method'] != filters['method'] and (it['commitment'] or {}).get('method') != filters['method']:
            continue
        if filters.get('age') and it['age'] != filters['age']:
            continue
        if filters.get('commitment') and ((it['commitment'] or {}).get('state') or 'sin') != filters['commitment']:
            continue
        if filters.get('reconciliation') and it['reconciliation'] != filters['reconciliation']:
            continue
        if filters.get('state') and it['state'] != filters['state']:
            continue
        out.append(it)
    out.sort(key=lambda it: (-(it['days_overdue'] or 0), -it['balance_cents'], it['main_id']))
    month = today.replace(day=1).isoformat()
    recovered = c.execute("SELECT COALESCE(SUM(p.amount_cents),0) FROM order_payments p JOIN orders o ON o.id=p.order_id WHERE p.voided_at IS NULL AND p.kind='pago' "
                          "AND o.delivered_at!='' AND o.delivered_at IS NOT NULL AND substr(p.created_at,1,10)>=? AND substr(p.created_at,1,10)>substr(o.delivered_at,1,10)", (month,)).fetchone()[0]
    pickups = c.execute("SELECT COUNT(*) FROM orders WHERE status IN ('listo','espera_entrega')").fetchone()[0]
    open_c = [it['commitment'] for it in items if it['commitment']]
    overdue_states = ('pago_vencido', 'mora_90', 'compromiso_incumplido')
    kpis = {'capital_cents': sum(it['balance_cents'] for it in items),
            'at_pickup_cents': sum(it['balance_cents'] for it in items if it['state'] == 'pago_al_retirar'),
            'upcoming_cents': sum(it['balance_cents'] for it in items if it['state'] in ('acuerdo_vigente', 'por_vencer', 'vence_hoy')),
            'overdue_cents': sum(it['balance_cents'] for it in items if it['state'] in overdue_states),
            'over90_cents': sum(it['balance_cents'] for it in items if it['state'] in overdue_states and (it['days_overdue'] or 0) > 90),
            'review_cents': sum(it['balance_cents'] for it in items if it['state'] in ('en_revision', 'requiere_revision')),
            'simulated_interest_cents': sum(it['simulated_interest_cents'] or 0 for it in items), 'simulation_available': bool(table),
            'authorized_interest_cents': 0, 'recovered_month_cents': recovered, 'pending_reconciliation_cents': sum(it['pending_cents'] for it in items),
            'commitments_open': sum(1 for x in open_c if x['state'] in ('pendiente', 'proximo')),
            'commitments_broken': sum(1 for x in open_c if x['state'] in ('incumplido', 'parcial')), 'pickups': pickups,
            'in_review': sum(1 for it in items if it['state'] in ('en_revision', 'requiere_revision')),
            'credit_cents': sum(it['credit_cents'] for it in items)}
    # Comprobación de consistencia: cada saldo cae en un solo grupo (sin duplicar obligaciones entre indicadores).
    groups_sum = kpis['at_pickup_cents'] + kpis['upcoming_cents'] + kpis['overdue_cents'] + kpis['review_cents'] + \
        sum(it['balance_cents'] for it in items if it['state'] in ('pendiente_conciliacion', 'saldo_a_favor', 'pagado'))
    kpis['consistent'] = groups_sum == kpis['capital_cents']
    return {'kpis': kpis, 'items': out[:300], 'total': len(out), 'ages': dict(AGES), 'states': {k: v[0] for k, v in STATE_LABELS.items()}, 'methods': equipment.METHODS, 'commitment_states': {'sin': 'Sin compromiso', **__import__('payment_commitments').STATES},
            'flags_installed': _has(c, 'collection_flags'), 'cutoff': today.isoformat(), 'policy': policy}


# ---- Marcas de gestión -----------------------------------------------------------------------------------------------------------------

def act(c, client_id, user, data, now, audit):
    if not _has(c, 'collection_flags'):
        raise CollectionsError(NOT_INSTALLED, 409)
    if not c.execute('SELECT 1 FROM clients WHERE id=?', (client_id,)).fetchone():
        raise CollectionsError('Cliente no encontrado.', 404)
    action = str(data.get('action', ''))
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if action in FLAG_KINDS:
        if not 10 <= len(reason) <= 400:
            raise CollectionsError('Indica el motivo (10 a 400 caracteres).', 400, {'reason': 'Obligatorio.'})
        until = ''
        if action == 'suspension':
            until_d = _day(data.get('until'))
            if not until_d or until_d < now.date() or until_d > now.date() + timedelta(days=180):
                raise CollectionsError('Indica hasta qué fecha se suspenden los recordatorios (hasta 180 días).', 400, {'until': 'Fecha no válida.'})
            until = until_d.isoformat()
        order_id = int(data.get('order_id') or 0) or None
        if order_id and not c.execute('SELECT 1 FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=? AND d.client_id=?', (order_id, client_id)).fetchone():
            raise CollectionsError('La orden no es de este cliente.', 400)
        fid = c.execute('INSERT INTO collection_flags(client_id,order_id,kind,reason,until,user_id,created_at) VALUES (?,?,?,?,?,?,?)',
                        (client_id, order_id, action, reason, until, user['id'], now.isoformat(timespec='seconds'))).lastrowid
        audit(c, user['id'], 'collection_' + action, client_id)
        return fid
    if action == 'close':
        fid = int(data.get('id') or 0)
        row = c.execute("SELECT * FROM collection_flags WHERE id=? AND client_id=? AND closed_at=''", (fid, client_id)).fetchone()
        if not row:
            raise CollectionsError('Marca no encontrada o ya cerrada.', 404)
        if row['kind'] == 'derivacion' and user['role'] != 'administrador':
            raise CollectionsError('Solo administración cierra una derivación.', 403)
        if not 5 <= len(reason) <= 400:
            raise CollectionsError('Indica cómo se cerró (5 a 400 caracteres).', 400, {'reason': 'Obligatorio.'})
        c.execute('UPDATE collection_flags SET closed_at=?,closed_by=?,close_note=? WHERE id=?', (now.isoformat(timespec='seconds'), user['id'], reason, fid))
        audit(c, user['id'], 'collection_flag_closed', client_id)
        return fid
    raise CollectionsError('Acción no válida.')


def suspended(c, client_id, today):
    """Motivo si la cobranza de este cliente está suspendida o derivada; '' si no."""
    for f in flags(c, client_id):
        if f['kind'] == 'suspension' and (not f['until'] or f['until'] >= today.isoformat()):
            return 'Recordatorios de cobranza suspendidos hasta el %s: %s' % (_day(f['until']).strftime('%d/%m/%Y') if f['until'] else '—', f['reason'])
        if f['kind'] == 'derivacion':
            return 'Caso derivado a administración: %s' % f['reason']
        if f['kind'] == 'conciliacion':
            return 'Conciliación solicitada (importe o transferencia por revisar): %s' % f['reason']
    return ''


# ---- Expediente económico del cliente --------------------------------------------------------------------------------------------------

def client_file(c, client_id, now):
    import payment_commitments as pc
    client = c.execute('SELECT id,name,COALESCE(phone,\'\') phone,COALESCE(email,\'\') email FROM clients WHERE id=?', (client_id,)).fetchone()
    if not client:
        raise CollectionsError('Cliente no encontrado.', 404)
    port = portfolio(c, now, client_id=client_id)
    orders = [dict(r) for r in c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,s.label status,o.received_at,o.delivered_at,d.brand,d.model "
                                         "FROM orders o JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status WHERE d.client_id=? ORDER BY o.id DESC LIMIT 60", (client_id,))]
    ids = [o['id'] for o in orders] or [0]
    marks = ','.join('?' * len(ids))
    payments = [dict(r) for r in c.execute("SELECT p.id,p.order_id,p.amount_cents,p.kind,p.method,p.created_at,p.voided_at,COALESCE(t.status,'') transfer_status FROM order_payments p "
                                           "LEFT JOIN bank_transfers t ON t.payment_id=p.id WHERE p.order_id IN (" + marks + ") ORDER BY p.id DESC LIMIT 100", ids)]
    quotes = [dict(r) for r in c.execute("SELECT q.code,q.status,q.order_id,q.sent_at FROM quotes q WHERE q.order_id IN (" + marks + ") AND q.deleted_at='' ORDER BY q.id DESC LIMIT 40", ids)]
    invoices = []
    if _has(c, 'invoices'):
        import invoicing
        invoices = [{'id': r['id'], 'number': invoicing.number(r), 'status_label': invoicing.STATUS.get(r['status'], r['status']), 'total_cents': r['total_cents'], 'order_id': r['order_id'],
                     'authorized_at': r['authorized_at'] or ''} for r in c.execute("SELECT * FROM invoices WHERE client_id=? AND status NOT IN ('borrador','descartado') ORDER BY id DESC LIMIT 60", (client_id,))]
    commitments, agreements = [], []
    if pc.installed(c):
        for row in c.execute('SELECT * FROM payment_commitments WHERE client_id=? ORDER BY id DESC LIMIT 40', (client_id,)):
            commitments.append(pc._out(c, row, now.date()))
            agreements += [dict(e, commitment_id=row['id']) for e in pc.events(c, row['id'])]
    messages = [dict(r) for r in c.execute("SELECT m.created_at,m.template,m.channel,m.status,m.order_id,COALESCE(u.name,'') user FROM order_messages m LEFT JOIN users u ON u.id=m.created_by "
                                           "WHERE m.order_id IN (" + marks + ") ORDER BY m.id DESC LIMIT 40", ids)] if 'created_by' in [r[1] for r in c.execute('PRAGMA table_info(order_messages)')] else \
        [dict(r) for r in c.execute("SELECT created_at,template,channel,status,order_id FROM order_messages WHERE order_id IN (" + marks + ") ORDER BY id DESC LIMIT 40", ids)]
    replies = []
    if _has(c, 'whatsapp_adi_inbound'):
        import whatsapp_business as wa
        number = wa.number_for(client['phone'])
        if number:
            replies = [{'at': r['received_at'], 'status': r['status']} for r in c.execute('SELECT received_at,status FROM whatsapp_adi_inbound WHERE sender=? ORDER BY received_at DESC LIMIT 20', (number,))]
    coverages = []
    if _has(c, 'part_coverages'):
        coverages = [dict(r) for r in c.execute("SELECT order_id,covered_cents,status,authorized_at created_at FROM part_coverages WHERE order_id IN (" + marks + ") AND modality='comercial' "
                                                "AND status='autorizada' ORDER BY id DESC", ids)] if 'modality' in [r[1] for r in c.execute('PRAGMA table_info(part_coverages)')] else []
    actions = ("'adi_msg:%'", "'payment_commitment_%'", "'account_statement%'", "'interest_simulated'", "'adi_delay_incident'", "'status_message_composed'", "'adi_purpose_composed'")
    trail = [{'at': datetime.fromtimestamp(r['created_at'], now.tzinfo).isoformat(timespec='seconds') if now.tzinfo else datetime.fromtimestamp(r['created_at']).isoformat(timespec='seconds'),
              'action': r['action'], 'user': r['user'], 'entity': r['entity_id']}
             for r in c.execute("SELECT a.action,a.created_at,a.entity_id,COALESCE(u.name,'Sistema') user FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE "
                                "((a.entity_id IN (" + marks + ") AND (" + ' OR '.join('a.action LIKE ' + x for x in actions) + ")) OR (a.entity_id=? AND a.action LIKE 'collection_%')) "
                                "ORDER BY a.id DESC LIMIT 80", (*ids, client_id))]
    import interest_engine as ie
    try:
        pol = ie.policy(c)
        rates = [r for r in ie.rates(c) if r['status'] == 'validada' and r['kind'] == pol['rate_kind']]
    except Exception:
        pol, rates = ie.DEFAULT_POLICY, []
    interests = [{'code': it['code'], 'eligible': it['state'] in ('compromiso_incumplido',), 'capital': usd(it['balance_cents']), 'due': it['due_date'], 'days': it['days_overdue'],
                  'grace': pol['grace_days'], 'rate': rates[0]['rate'] if rates else 'Sin tasa validada', 'simulated': it['simulated_interest_cents'], 'authorized': 0,
                  'reason': '' if it['state'] == 'compromiso_incumplido' else 'No se simula: solo obligaciones con compromiso de pago incumplido (%s).' % it['state_label'].lower()} for it in port['items'] if it['balance_cents'] > 0]
    return {'client': {'id': client['id'], 'name': client['name'], 'phone': _mask(client['phone']), 'email': bool(client['email'])}, 'portfolio': port, 'orders': orders,
            'coverages': coverages, 'audit': trail, 'interests': interests,
            'payments': payments, 'quotes': quotes, 'invoices': invoices, 'commitments': commitments, 'agreements': agreements, 'messages': messages, 'replies': replies,
            'flags': flags(c, client_id, active_only=False)[:40], 'suspended': suspended(c, client_id, now.date())}


# ---- Fase 5: equipos pendientes de retiro ----------------------------------------------------------------------------------------------

def pickups(c, now):
    """Control de retiro, independiente del seguimiento económico. Alertas a los 30, 60, 85 y 90 días desde que el equipo quedó listo.
    Nunca autoriza vender, rematar, apropiarse ni disponer del equipo: desde los 90 días el caso pasa a revisión administrativa y jurídica."""
    import equipment
    import order_extensions
    today = now.date()
    out = []
    rows = c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status,s.label status_label,cl.id client_id,cl.name client,d.brand,d.model FROM orders o "
                     "JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.status IN ('listo','espera_entrega') ORDER BY o.id").fetchall()
    for r in rows:
        ready = c.execute("SELECT MIN(created_at) FROM order_status_log WHERE order_id=? AND to_status IN ('listo','espera_entrega') AND created_at>="
                          "COALESCE((SELECT MAX(created_at) FROM order_status_log WHERE order_id=? AND to_status NOT IN ('listo','espera_entrega')),'')", (r['id'], r['id'])).fetchone()[0] or ''
        days = (today - _day(ready)).days if _day(ready) else None
        notice = c.execute("SELECT created_at,channel,status FROM order_messages WHERE order_id=? AND created_at>=? AND status IN ('enviado','entregado','leido') ORDER BY id LIMIT 1",
                           (r['id'], ready or '')).fetchone()
        try:
            ext = order_extensions.state(c, r['id'], now)
            deadline, extension = ext.get('due', ''), ext.get('extension')
            history = order_extensions.history(c, r['id']) if order_extensions.ready(c) else []
        except Exception:
            deadline, extension, history = '', None, []
        money = equipment.money(c, r['id']) or {}
        alert = max((a for a in PICKUP_ALERTS if days is not None and days >= a), default=0)
        out.append({'order_id': r['id'], 'code': r['code'], 'client_id': r['client_id'], 'client': r['client'], 'device': ' '.join(x for x in (r['brand'], r['model']) if x),
                    'status': r['status_label'], 'ready_at': ready, 'days': days, 'notice_at': notice['created_at'] if notice else '',
                    'notice_evidence': '%s · %s' % (notice['channel'], notice['status']) if notice else '', 'deadline': deadline,
                    'extensions': len(history) if isinstance(history, list) else 0, 'extension_reason': (extension or {}).get('reason_label', '') or (extension or {}).get('reason', '') if extension else '',
                    'balance_cents': money.get('balance_cents', 0), 'alert': alert,
                    'alert_label': ('Revisión administrativa y jurídica (no se dispone del equipo)' if alert >= 90 else 'Alerta de %d días' % alert) if alert else 'Sin alerta'})
    out.sort(key=lambda x: -(x['days'] or 0))
    return {'items': out, 'alerts': {str(a): sum(1 for x in out if x['alert'] == a) for a in PICKUP_ALERTS},
            'note': 'Control independiente de la cobranza. Los gastos de almacenamiento no son intereses por mora. Al cumplirse 90 días no se vende, remata, '
                    'elimina ni dispone del equipo: el caso pasa a revisión administrativa y jurídica.'}


# ---- Fase 5: auditoría de comunicaciones -----------------------------------------------------------------------------------------------

def comms_audit(c, now, filters=None):
    """Registro de comunicaciones: fecha, cliente, orden, motivo, fuente, plantilla, estado, usuario, entrega, respuesta y resultado.
    Solo datos ya registrados (sin guardar contenido sensible nuevo)."""
    filters = filters or {}
    since = _day(filters.get('from')) or (now.date() - timedelta(days=30))
    until = _day(filters.get('to')) or now.date()
    cols = [r[1] for r in c.execute('PRAGMA table_info(order_messages)')]
    user_sql = ",COALESCE(u.name,'') user" if 'created_by' in cols else ",'' user"
    join = ' LEFT JOIN users u ON u.id=m.created_by' if 'created_by' in cols else ''
    rows = [dict(r) for r in c.execute("SELECT m.id,m.order_id,m.created_at,m.template,m.channel,m.status,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,cl.id client_id,cl.name client,"
                                       "COALESCE(cl.phone,'') phone" + user_sql + " FROM order_messages m JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id "
                                       "JOIN clients cl ON cl.id=d.client_id" + join + " WHERE substr(m.created_at,1,10)>=? AND substr(m.created_at,1,10)<=? ORDER BY m.id DESC LIMIT 300",
                                       (since.isoformat(), until.isoformat()))]
    q = str(filters.get('client', '') or '').strip().lower()
    purposes = {}
    start = int(datetime.combine(since, datetime.min.time(), tzinfo=now.tzinfo).timestamp())
    for a in c.execute("SELECT a.entity_id,a.action,a.created_at,COALESCE(u.name,'') user FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.action LIKE 'adi_msg:%' AND a.created_at>=?", (start,)):
        purposes.setdefault(a['entity_id'], []).append((a['created_at'], a['action'][8:], a['user']))
    import adi_comms
    inbound = _has(c, 'whatsapp_adi_inbound')
    out = []
    for r in rows:
        if q and q not in r['client'].lower():
            continue
        at = r['created_at']
        try:
            epoch = datetime.fromisoformat(at).timestamp()
        except ValueError:
            epoch = 0
        motive = next((p for t, p, u in sorted(purposes.get(r['order_id'], []), key=lambda x: -x[0]) if abs(t - epoch) <= 3600), '')
        reply = ''
        if inbound and r['channel'] == 'whatsapp':
            import whatsapp_business as wa
            number = wa.number_for(r['phone'])
            if number:
                found = c.execute('SELECT MIN(received_at) FROM whatsapp_adi_inbound WHERE sender=? AND received_at>? AND received_at<=?',
                                  (number, at, (datetime.fromisoformat(at) + timedelta(days=7)).isoformat(timespec='seconds') if epoch else at)).fetchone()[0]
                reply = 'Respondió el %s' % found[:16].replace('T', ' ') if found else ''
        week = (datetime.fromisoformat(at) + timedelta(days=7)).isoformat(timespec='seconds') if epoch else at
        paid = c.execute('SELECT 1 FROM order_payments WHERE order_id=? AND kind=\'pago\' AND voided_at IS NULL AND created_at>=? AND created_at<=? LIMIT 1', (r['order_id'], at, week)).fetchone()
        committed = _has(c, 'payment_commitments') and c.execute('SELECT 1 FROM payment_commitments WHERE order_id=? AND created_at>=? AND created_at<=? LIMIT 1', (r['order_id'], at, week)).fetchone()
        out.append({'at': at, 'client': r['client'], 'client_id': r['client_id'], 'order_id': r['order_id'], 'code': r['code'],
                    'motive': adi_comms.PURPOSES.get(motive, (motive or '',))[0] or (r['template'] or 'Mensaje'), 'source': 'Análisis integral ADI (datos registrados)' if motive else 'Comunicación de la orden',
                    'template': r['template'] or '—', 'channel': r['channel'], 'status': r['status'], 'user': r['user'] or '—',
                    'delivery': {'entregado': 'Entregado', 'leido': 'Leído'}.get(r['status'], 'Sin confirmación' if r['status'] == 'enviado' else '—'),
                    'reply': reply or 'Sin respuesta registrada', 'result': 'Pago registrado' if paid else 'Compromiso registrado' if committed else 'Sin resultado registrado'})
    return {'from': since.isoformat(), 'to': until.isoformat(), 'items': out, 'total': len(out)}


# ---- Fase 5: propuestas de seguimiento por eventos ------------------------------------------------------------------------------------

def proposals(c, now):
    """Propuestas de comunicación por eventos (3 días antes, vencimiento, 7/15/30/60/85/90 días; retiro 30/60/85/90). NUNCA se envían solas:
    una persona las revisa y las prepara con el control previo de 12 puntos. Se detienen con saldo cancelado, acuerdo vigente, revisión,
    transferencia por conciliar, suspensión, derivación o una gestión en los últimos 3 días."""
    today = now.date()
    port = portfolio(c, now)
    recent_cut = (now - timedelta(days=RECENT_DAYS)).isoformat(timespec='seconds')
    out = []

    def recent(order_ids):
        marks = ','.join('?' * len(order_ids))
        return c.execute("SELECT MAX(created_at) FROM order_messages WHERE order_id IN (" + marks + ") AND created_at>=? AND status IN ('preparado','enviado','entregado','leido')",
                         (*order_ids, recent_cut)).fetchone()[0]

    for it in port['items']:
        if it['balance_cents'] <= 0:
            continue
        com = it['commitment']
        event = purpose = ''
        if com and com['state'] in ('pendiente', 'proximo'):
            left = (_day(com['due_date']) - today).days
            if left == 3:
                event, purpose = '3 días antes del vencimiento', 'compromiso_pago'
            elif left == 0:
                event, purpose = 'Fecha de vencimiento', 'compromiso_pago'
        elif it['days_overdue']:
            reached = max((m for m in MILESTONES if it['days_overdue'] >= m), default=0)
            if reached:
                event = '%d días de retraso' % reached
                purpose = 'compromiso_incumplido' if com and com['state'] in ('incumplido', 'parcial') else 'pago_pendiente'
        if not event:
            continue
        blocked = []
        stop = suspended(c, it['client_id'], today)
        if stop:
            blocked.append(stop)
        if com and com['state'] == 'en_revision':
            blocked.append('Compromiso en revisión.')
        if it['pending_transfers']:
            blocked.append('Transferencia por conciliar: se suspende la cobranza hasta conciliarla.')
        if it['claims']:
            blocked.append('Reclamo pendiente (%s): se suspende la cobranza hasta resolverlo.' % ', '.join(it['claims']))
        if it['state'] in ('en_revision', 'requiere_revision'):
            blocked.append('Obligación %s.' % it['state_label'].lower())
        last = recent([it['main_id'], it['order_id']])
        if last:
            blocked.append('Gestión reciente el %s.' % last[:10])
        out.append({'kind': 'cobranza', 'event': event, 'purpose': purpose, 'order_id': it['order_id'], 'code': it['code'], 'client_id': it['client_id'], 'client': it['client'],
                    'balance': usd(it['balance_cents']), 'blocked': blocked, 'ready': not blocked})
    for p in pickups(c, now)['items']:
        if not p['alert']:
            continue
        blocked = []
        last = recent([p['order_id']])
        if last:
            blocked.append('Gestión reciente el %s.' % last[:10])
        out.append({'kind': 'retiro', 'event': 'Equipo listo hace %d días' % p['days'], 'purpose': 'recordatorio_retiro', 'order_id': p['order_id'], 'code': p['code'],
                    'client_id': p['client_id'], 'client': p['client'], 'balance': usd(p['balance_cents']), 'blocked': blocked, 'ready': not blocked,
                    'review': p['alert'] >= 90})
    return {'items': out, 'automatic': False, 'rules': {'milestones': list(MILESTONES), 'pickup_alerts': list(PICKUP_ALERTS), 'recent_days': RECENT_DAYS,
                                                       'hours': 'Lunes a viernes laborables, 08:00 a 19:00 (hora de Ecuador), sin feriados; máximo una gestión de cobranza al día por cliente.',
                                                       'status': 'Propuestas manuales. El envío automático de campañas NO está autorizado: requiere aprobar estas reglas.'}}
