"""Premium Billing Center · reportes y exportaciones de facturación (docs/FACTURACION-REPORTES.md). Solo lectura: no emite, no envía al
SRI, no consume secuenciales ni cambia comprobantes.

Reglas (nada se estima):
- Ambiente: los reportes son de UN ambiente. Por omisión el vigente (producción si la emisión real está activa); pruebas y producción
  nunca se suman entre sí.
- «Facturado»: comprobantes emitidos sin rechazo (pendiente, enviado, autorizado). Borradores y rechazados no suman.
- «Cobrado» se distingue de «facturado»: órdenes y ventas de licencias usan sus cobros ACTUALES (un pago anulado después de facturar deja
  saldo); el resto (proformas, ventas de inventario, facturas directas) usa las formas de pago registradas en la factura, sin el crédito.
- Notas de crédito: las registradas (no descartadas) del mismo ambiente y rango, por su fecha de emisión o de creación.
- Las exportaciones usan exactamente los mismos filtros de la pantalla y quedan en la auditoría."""
from datetime import date, timedelta

import equipment
import invoicing

BILLED = ('pendiente', 'enviado', 'autorizado')
MAX_ROWS = 5000
COLUMNS = ['Comprobante', 'Ambiente', 'Emisión', 'Cliente', 'Identificación', 'Vinculado', 'Estado SRI', 'Formas de pago',
           'Importe sin IVA', 'Monto de IVA', 'Importe total', 'Monto cobrado', 'Monto por cobrar', 'Clave de acceso']
WIDTHS = [62, 0, 40, 78, 48, 66, 38, 62, 38, 32, 40, 40, 40, 0]   # 0: la columna va al Excel y al CSV, no al PDF (por ancho)
SOURCE_LABELS = {'orden': 'Orden', 'venta_licencia': 'Venta', 'proforma': 'Proforma', 'venta_inventario': 'Venta'}


class ReportError(Exception):
    pass


def parse(arg, now):
    """Filtros válidos desde la consulta. El ambiente por omisión es el vigente."""
    env = arg('env') if arg('env') in invoicing.ENVIRONMENTS else invoicing.active_environment()
    status = arg('status') if arg('status') in invoicing.STATUS and arg('status') != 'descartado' else ''
    method = arg('method') if invoicing.METHOD_KEY.fullmatch(arg('method') or '') else ''
    f = {'status': status, 'q': arg('q')[:80], 'from': arg('from') if invoicing.DATE.fullmatch(arg('from') or '') else '',
         'to': arg('to') if invoicing.DATE.fullmatch(arg('to') or '') else '', 'env': env, 'method': method}
    if f['from'] and f['to'] and f['from'] > f['to']:
        f['from'], f['to'] = f['to'], f['from']
    return f


def _chunks(ids, size=400):
    ids = list(ids)
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def _dues(c, rows):
    """Saldo actual de cada orden y venta de licencia facturada (para separar lo cobrado de lo facturado)."""
    orders, sales = {}, {}
    for part in _chunks({r['order_id'] for r in rows if r['source_kind'] == 'orden' and r['order_id']}):
        for oid, due in c.execute('SELECT o.id,' + equipment.BUDGET + '-' + equipment.PAID + ' FROM orders o WHERE o.id IN (' + ','.join('?' * len(part)) + ')', part):
            orders[oid] = int(due or 0)
    for part in _chunks({r['license_sale_id'] for r in rows if r['source_kind'] == 'venta_licencia' and r['license_sale_id']}):
        for sid, due in c.execute("SELECT s.id,s.total_cents-COALESCE((SELECT SUM(amount_cents) FROM license_sale_payments p WHERE p.sale_id=s.id AND p.status='confirmado'),0) "
                                  'FROM license_sales s WHERE s.id IN (' + ','.join('?' * len(part)) + ')', part):
            sales[sid] = int(due or 0)
    return orders, sales


def _payments(c, ids):
    out = {}
    for part in _chunks(ids):
        for r in c.execute('SELECT invoice_id,method,SUM(amount_cents) total FROM invoice_payments WHERE invoice_id IN (' + ','.join('?' * len(part)) + ') GROUP BY 1,2 ORDER BY 1,3 DESC', part):
            out.setdefault(r['invoice_id'], []).append((r['method'], int(r['total'] or 0)))
    return out


def rows(c, f):
    """Comprobantes con los filtros (máximo MAX_ROWS, los más recientes primero), con lo cobrado y lo pendiente de cada uno."""
    base, args = invoicing.list_where(f['status'], f['q'], f['from'], f['to'], f['env'], f['method'])
    total = c.execute('SELECT COUNT(*)' + base, args).fetchone()[0]
    found = [dict(r) for r in c.execute("SELECT i.*,o.code order_code,s.code sale_code,CASE WHEN i.source_kind='proforma' THEN (SELECT code FROM proformas WHERE id=i.source_id) "
                                       "WHEN i.source_kind='venta_inventario' THEN 'INV-'||i.source_id END other_code" + base +
                                       " ORDER BY COALESCE(NULLIF(i.issue_date,''),substr(i.created_at,1,10)) DESC,i.id DESC LIMIT ?", args + [MAX_ROWS])]
    orders, sales = _dues(c, found)
    pays = _payments(c, [r['id'] for r in found])
    out = []
    for r in found:
        billed = r['status'] in BILLED
        methods = pays.get(r['id'], [])
        if not billed:
            collected = None
            basis = ''
        elif r['source_kind'] == 'orden' and r['order_id'] in orders:
            collected = r['total_cents'] - min(r['total_cents'], max(0, orders[r['order_id']]))
            basis = 'cobros actuales de la orden'
        elif r['source_kind'] == 'venta_licencia' and r['license_sale_id'] in sales:
            collected = r['total_cents'] - min(r['total_cents'], max(0, sales[r['license_sale_id']]))
            basis = 'cobros actuales de la venta'
        else:
            collected = min(r['total_cents'], sum(v for m, v in methods if m != 'credito'))
            basis = 'formas de pago de la factura'
        ref = r['other_code'] or r['order_code'] or r['sale_code'] or ''
        out.append({'id': r['id'], 'number': invoicing.number(r), 'environment': r['environment'], 'issue_date': r['issue_date'] or '', 'created_at': r['created_at'],
                    'buyer_name': r['buyer_name'], 'buyer_id': 'Consumidor final' if r['consumer_final'] else r['buyer_id'],
                    'reference': (SOURCE_LABELS.get(r['source_kind'], 'Orden') + ' ' + ref) if ref else 'Directa', 'status': r['status'], 'status_label': invoicing.STATUS[r['status']],
                    'methods': [{'method': m, 'label': invoicing.PAYMENT_FILTERS.get(m, m.replace('_', ' ').capitalize()), 'amount_cents': v} for m, v in methods],
                    'subtotal_cents': r['subtotal_cents'], 'tax_cents': r['tax_cents'], 'total_cents': r['total_cents'], 'billed': billed,
                    'collected_cents': collected, 'outstanding_cents': None if collected is None else r['total_cents'] - collected, 'collected_basis': basis,
                    'access_key': r['access_key'] or ''})
    return out, total


def _credit_notes(c, f):
    day = "COALESCE(NULLIF(issue_date,''),substr(created_at,1,10))"
    sql, args = "SELECT COUNT(*),COALESCE(SUM(total_cents),0) FROM credit_notes WHERE status!='descartado' AND environment=?", [f['env']]
    if f['from']:
        sql += ' AND ' + day + '>=?'; args.append(f['from'])
    if f['to']:
        sql += ' AND ' + day + '<=?'; args.append(f['to'])
    try:
        n, total = c.execute(sql, args).fetchone()
    except Exception:   # tabla ausente en una base sin la migración: no se inventa un valor
        return None
    return {'count': int(n or 0), 'total_cents': int(total or 0)}


def _annual(c, env, today):
    """Facturado del año en curso frente al mismo tramo del año anterior, y por mes del año en curso."""
    day = "COALESCE(NULLIF(issue_date,''),substr(created_at,1,10))"
    marks = ','.join('?' * len(BILLED))

    def billed(start, end):
        return int(c.execute('SELECT COALESCE(SUM(total_cents),0) FROM invoices WHERE environment=? AND status IN (' + marks + ') AND ' + day + '>=? AND ' + day + '<=?',
                             [env, *BILLED, start.isoformat(), end.isoformat()]).fetchone()[0])
    year0 = today.replace(month=1, day=1)
    try:
        prev_same = today.replace(year=today.year - 1)
    except ValueError:
        prev_same = today.replace(year=today.year - 1, day=28)
    months = {('%04d-%02d' % (today.year, m)): 0 for m in range(1, today.month + 1)}
    for month, total in c.execute('SELECT substr(' + day + ',1,7),COALESCE(SUM(total_cents),0) FROM invoices WHERE environment=? AND status IN (' + marks + ') AND ' + day + '>=? AND ' + day + '<=? GROUP BY 1',
                                  [env, *BILLED, year0.isoformat(), today.isoformat()]):
        if month in months:
            months[month] = int(total or 0)
    return {'year': today.year, 'year_cents': billed(year0, today), 'prev_year_cents': billed(year0.replace(year=today.year - 1), prev_same),
            'prev_year_to': prev_same.isoformat(), 'months': [{'month': k, 'billed_cents': v} for k, v in months.items()]}


def report(c, f, now):
    """Indicadores del reporte con los filtros: documentos, facturado, cobrado, por cobrar, por forma de pago y por estado; anual y notas de crédito."""
    found, total = rows(c, f)
    billed = [r for r in found if r['billed']]
    by_method = {}
    for r in billed:
        for m in r['methods']:
            item = by_method.setdefault(m['method'], {'method': m['method'], 'label': m['label'], 'amount_cents': 0, 'documents': 0})
            item['amount_cents'] += m['amount_cents']
            item['documents'] += 1
    by_status = {}
    for r in found:
        by_status[r['status']] = by_status.get(r['status'], 0) + 1
    return {'filters': f, 'environment': f['env'], 'environment_label': invoicing.ENVIRONMENTS[f['env']], 'active_environment': invoicing.active_environment(),
            'documents': total, 'truncated': total > len(found), 'billed_documents': len(billed),
            'billed_cents': sum(r['total_cents'] for r in billed), 'tax_cents': sum(r['tax_cents'] for r in billed),
            'collected_cents': sum(r['collected_cents'] for r in billed), 'outstanding_cents': sum(r['outstanding_cents'] for r in billed),
            'by_method': sorted(by_method.values(), key=lambda x: -x['amount_cents']), 'by_status': by_status,
            'credit_notes': _credit_notes(c, f), 'annual': _annual(c, f['env'], now.date()), 'payment_filters': invoicing.payment_filters(c),
            'statuses': {k: v for k, v in invoicing.STATUS.items() if k != 'descartado'}, 'environments': invoicing.ENVIRONMENTS,
            'method_note': 'Facturado: emitidas sin rechazo. Cobrado: cobros actuales de la orden o la venta; en proformas, inventario y facturas directas, las formas de pago registradas en la factura sin el crédito.'}


def money(cents):
    return None if cents is None else round(cents / 100, 2)


def table(c, f, now):
    """(título, columnas, filas, anchos para el PDF, línea de totales) para Excel, CSV y PDF."""
    found, total = rows(c, f)
    data = []
    for r in found:
        data.append([r['number'] or 'Borrador', invoicing.ENVIRONMENTS[r['environment']], r['issue_date'] or 'Sin emitir', r['buyer_name'] or '—',
                     r['buyer_id'] or '—', r['reference'], r['status_label'], ', '.join(m['label'] for m in r['methods']) or '—',
                     money(r['subtotal_cents']), money(r['tax_cents']), money(r['total_cents']),
                     '' if r['collected_cents'] is None else money(r['collected_cents']), '' if r['outstanding_cents'] is None else money(r['outstanding_cents']), r['access_key']])
    billed = [r for r in found if r['billed']]
    from inventory import usd
    totals = ('%d comprobantes · Facturado %s (%d emitidos sin rechazo) · Cobrado %s · Por cobrar %s · IVA %s'
              % (len(found), usd(sum(r['total_cents'] for r in billed)), len(billed), usd(sum(r['collected_cents'] for r in billed)),
                 usd(sum(r['outstanding_cents'] for r in billed)), usd(sum(r['tax_cents'] for r in billed))))
    if total > len(found):
        totals += ' · Se exportan los %d más recientes de %d: acota los filtros.' % (len(found), total)
    return 'Reporte de facturación', COLUMNS, data, WIDTHS, totals


def filters_text(f):
    parts = ['Ambiente: ' + invoicing.ENVIRONMENTS[f['env']]]
    if f['from'] or f['to']:
        parts.append('Emisión: ' + (f['from'] or 'inicio') + ' a ' + (f['to'] or 'hoy'))
    if f['status']:
        parts.append('Estado: ' + invoicing.STATUS[f['status']])
    if f['method']:
        parts.append('Forma de pago: ' + invoicing.PAYMENT_FILTERS.get(f['method'], f['method'].replace('_', ' ').capitalize()))
    if f['q']:
        parts.append('Búsqueda: «' + f['q'] + '»')
    return ' · '.join(parts)
