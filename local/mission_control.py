"""Technical Mission Control 5.1 · resumen de ventas y finanzas para Reportes (docs/MISSION-CONTROL.md).

Cada valor sale de su módulo, sin duplicarlo ni inventarlo:
- Ventas: libro del Centro de Ventas (ventas directas, cotizaciones convertidas, licencias e inventario), sin las anuladas.
- Ingresos confirmados: cobros de órdenes registrados y no anulados, sin transferencias por validar ni rechazadas (menos devoluciones).
- Facturación autorizada: facturas AUTORIZADAS por el SRI del ambiente activo (una factura autorizada no implica pagada).
- Capital pendiente y cartera vencida: ADI Smart Collections (misma fuente y reglas).
- Gastos: egresos de caja no anulados.
- Rentabilidad: no se calcula sin el costo de lo vendido y de los servicios: se indica «sin datos suficientes».
Las comparaciones son con el mismo número de días del periodo anterior (p. ej., mes hasta hoy frente al mes anterior hasta el mismo día)."""
from datetime import date, timedelta


def _sum_by_day(rows, first, last):
    days = {}
    for at, cents in rows:
        d = str(at or '')[:10]
        if first.isoformat() <= d <= last.isoformat():
            days[d] = days.get(d, 0) + int(cents or 0)
    out, cur = [], first
    while cur <= last:
        out.append(days.get(cur.isoformat(), 0))
        cur += timedelta(days=1)
    return out


def _windows(today):
    month0 = today.replace(day=1)
    prev_month_end = month0 - timedelta(days=1)
    prev_month0 = prev_month_end.replace(day=1)
    prev_same = min(prev_month0 + timedelta(days=(today - month0).days), prev_month_end)
    year0 = today.replace(month=1, day=1)
    try:
        prev_year_same = today.replace(year=today.year - 1)
    except ValueError:
        prev_year_same = today.replace(year=today.year - 1, day=28)
    return {'today': (today, today), 'yesterday': (today - timedelta(days=1), today - timedelta(days=1)), 'month': (month0, today),
            'prev_month': (prev_month0, prev_same), 'year': (year0, today), 'prev_year': (year0.replace(year=today.year - 1), prev_year_same)}


def _block(rows, today):
    w = _windows(today)
    total = lambda key: sum(int(c or 0) for at, c in rows if w[key][0].isoformat() <= str(at or '')[:10] <= w[key][1].isoformat())
    spark_first = today - timedelta(days=29)
    return {'today': total('today'), 'yesterday': total('yesterday'), 'month': total('month'), 'prev_month': total('prev_month'), 'year': total('year'),
            'prev_year': total('prev_year'), 'series': _sum_by_day(rows, spark_first, today), 'series_from': spark_first.isoformat()}


def summary(c, now):
    today = now.date()
    out = {'today': today.isoformat(), 'sources': {}}
    try:
        import sales_center
        rows = [(r['at'], r['total_cents']) for r in sales_center.ledger(c) if r['state'] != 'anulada']
        out['sales'] = _block(rows, today)
        out['sources']['sales'] = 'Centro de Ventas (sin anuladas)'
    except Exception as error:
        out['sales'] = None
        out['sources']['sales'] = 'No disponible (%s)' % type(error).__name__
    rows = [(r[0], r[1]) for r in c.execute(
        "SELECT p.created_at,CASE WHEN p.kind='pago' THEN p.amount_cents ELSE -p.amount_cents END FROM order_payments p LEFT JOIN bank_transfers t ON t.payment_id=p.id "
        "WHERE p.voided_at IS NULL AND COALESCE(t.status,'confirmado') NOT IN ('pendiente','rechazado')")]
    out['income'] = _block(rows, today)
    out['sources']['income'] = 'Cobros de órdenes confirmados (sin transferencias por validar), menos devoluciones'
    try:
        import invoicing
        env = invoicing.active_environment()
        rows = [(r[0], r[1]) for r in c.execute("SELECT COALESCE(NULLIF(authorized_at,''),created_at),total_cents FROM invoices WHERE status='autorizado' AND environment=?", (env,))]
        out['invoiced'] = _block(rows, today)
        out['sources']['invoiced'] = 'Facturas autorizadas por el SRI (%s)' % invoicing.ENVIRONMENTS.get(env, env)
    except Exception as error:
        out['invoiced'] = None
        out['sources']['invoiced'] = 'No disponible (%s)' % type(error).__name__
    try:
        import collections_center
        k = collections_center.portfolio(c, now)['kpis']
        out['portfolio'] = {'capital_cents': k['capital_cents'], 'overdue_cents': k['overdue_cents'], 'over90_cents': k['over90_cents'], 'at_pickup_cents': k['at_pickup_cents']}
        out['sources']['portfolio'] = 'ADI Smart Collections'
    except Exception as error:
        out['portfolio'] = None
        out['sources']['portfolio'] = 'No disponible (%s)' % type(error).__name__
    try:
        rows = [(r[0], r[1]) for r in c.execute("SELECT created_at,amount_cents FROM cash_movements WHERE direction='egreso' AND COALESCE(voided_at,'')=''")]
        out['expenses'] = _block(rows, today)
        out['sources']['expenses'] = 'Egresos de caja no anulados'
    except Exception as error:
        out['expenses'] = None
        out['sources']['expenses'] = 'No disponible (%s)' % type(error).__name__
    out['profitability'] = {'available': False, 'reason': 'Sin datos suficientes: el sistema no registra el costo de todo lo vendido y de los servicios, así que no se calcula una rentabilidad.'}
    return out


def live_status(last_ok, now, interval_seconds, failures):
    """Estado del indicador EN VIVO (lo usa también la interfaz): verde al día, amarillo con retraso, rojo con fallos, gris sin datos."""
    if not last_ok:
        return 'gris'
    age = (now - last_ok).total_seconds()
    if failures >= 3:
        return 'rojo'
    if failures or age > interval_seconds * 3:
        return 'amarillo'
    return 'verde'
