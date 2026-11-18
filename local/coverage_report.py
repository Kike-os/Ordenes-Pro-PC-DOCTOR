"""Liquidación interna de una Cobertura PC-DOCTOR (A4 y ticket térmico de 80 mm). Solo administración; solo lee.

Es un documento INTERNO: lleva costo, proveedor, pagos y margen estimado, por eso nunca se entrega al cliente ni se enlaza desde sus
documentos. Los documentos del cliente (presupuesto, enlace, PDF, recibos y portal) se generan aparte y solo muestran el precio de su
presupuesto y el dinero realmente recibido."""
from datetime import datetime

from corporate import settings as corporate_settings
from document_canvas import GRAY, INK, Canvas
import part_coverage as pc

NAVY = (.08, .20, .38)
SOFT = (.94, .96, .99)
LINE = (.80, .85, .91)
RED = (.70, .13, .16)


def _dt(value):
    try:
        return datetime.fromisoformat(str(value)).strftime('%d/%m/%Y %H:%M')
    except ValueError:
        return str(value or '')


def collect(c, user, cov_id):
    d = pc.detail(c, user, cov_id)   # comprueba permisos (solo administración ve las cifras)
    if 'cost_cents' not in d:
        raise pc.CoverageError('Solo administración consulta la liquidación interna.', 403)
    client = c.execute('SELECT k.name FROM orders o JOIN devices v ON v.id=o.device_id JOIN clients k ON k.id=v.client_id WHERE o.id=?', (d['order_id'],)).fetchone()
    d['client'] = client['name'] if client else ''
    co = corporate_settings()
    d['company'] = {'legal': co.get('legal_name') or co.get('name') or 'PC-DOCTOR S.A.', 'ruc': co.get('ruc', '')}
    return d


def _lines(d):
    money = pc.usd
    head = [('Orden', d['order_code']), ('Presupuesto', d['quote_code']), ('Cliente', d['client']), ('Repuesto', d['line_description']), ('Cantidad', str(d['quantity'])),
            ('Estado de la cobertura', d['status_label']), ('Compra', d['purchase_label']), ('Pago al proveedor', d['payment_label']),
            ('Autorizó', (d['authorized_name'] + ' · ' + _dt(d['authorized_at'])) if d['authorized_name'] else 'Pendiente de autorización')]
    figures = [('Precio al cliente (presupuesto)', money(d['sale_cents'])), ('Costo real del repuesto', money(d['cost_cents'])),
               ('Cobertura PC-DOCTOR', '%d %%' % d['percent']), ('Importe cubierto', money(d['covered_cents'])), ('Pagado al proveedor', money(d['paid_cents'])),
               ('Pendiente con el proveedor', money(d['pending_cents'])), ('Margen bruto estimado', money(d['margin_cents']))]
    supplier = [('Proveedor', d['supplier'] or 'Sin indicar'), ('Factura o documento', d['supplier_document'] or '—')]
    payments = [('%s · %s' % (_dt(p['paid_at']), pc.cash_sessions.METHODS.get(p['method'], p['method'])),
                 ('%s%s · CJM-%d' % (money(p['amount_cents']), ' (revertido)' if p['status'] == 'revertido' else '', p['cash_movement_id']))) for p in d['payments']]
    return head, figures, supplier, payments


def a4(c, user, cov_id, now):
    d = collect(c, user, cov_id)
    head, figures, supplier, payments = _lines(d)
    W, H, L = 595, 842, 40
    R = W - L
    pdf = Canvas(W, H, 'Cobertura PC-DOCTOR %d' % d['id'])
    pdf.page()
    logo_h = pdf.logo(L, 30, 92)   # logo original, proporción real
    pdf.text(d['company']['legal'], L + 108, 36, 11, True, NAVY)
    pdf.text(('RUC ' + d['company']['ruc']) if d['company']['ruc'] else '', L + 108, 52, 8.5, False, GRAY)
    top = 30 + logo_h + 16
    pdf.text('LIQUIDACIÓN INTERNA · COBERTURA PC-DOCTOR N.º %d' % d['id'], L, top, 12, True, NAVY)
    pdf.box(L, top + 18, R - L, 18, (.99, .93, .93))
    pdf.text('DOCUMENTO INTERNO — NO ENTREGAR AL CLIENTE. Contiene costos, proveedor y margen.', L + 8, top + 23, 8.5, True, RED)
    y = top + 52

    def block(title, rows):
        nonlocal y
        pdf.box(L, y, 3, 13, NAVY)
        pdf.text(title.upper(), L + 9, y + 1, 10, True, NAVY)
        y += 20
        for n, (label, value) in enumerate(rows):
            if n % 2:
                pdf.box(L, y - 3, R - L, 15, SOFT)
            pdf.text(label, L + 6, y, 8.6, False, GRAY)
            pieces = pdf.wrap(value, (R - L) * .58, 8.6) or ['']
            for i, piece in enumerate(pieces[:3]):
                pdf.text(piece, R - 6 - pdf.width_of(piece, 8.6, i == 0), y + i * 11, 8.6, i == 0, INK)
            y += 15 + 11 * (min(len(pieces), 3) - 1)
        y += 8

    block('Partida y estados', head)
    block('Cifras internas', figures)
    block('Proveedor', supplier)
    block('Pagos al proveedor (egresos de caja)', payments or [('Sin pagos registrados', '—')])
    pdf.text('El cliente paga el precio de su presupuesto; sus cobros se registran aparte. Autorizar la cobertura no mueve dinero: cada pago es un egreso de caja.',
             L, min(y + 6, H - 60), 7.2, False, GRAY)
    pdf.text('Generado el %s (hora de Ecuador)' % now.strftime('%d/%m/%Y %H:%M'), L, H - 40, 7.2, False, GRAY)
    return pdf.finish()


def thermal(c, user, cov_id, now):
    """72 mm útiles con margen de 1 mm; una sola página con la altura del contenido."""
    d = collect(c, user, cov_id)
    head, figures, supplier, payments = _lines(d)
    W = 72 * 72 / 25.4
    M = 1 * 72 / 25.4
    IN = W - 2 * M
    measure = Canvas(10, 10, 'medida')
    ops, y = [], [6.0]

    def center(value, size=8.5, bold=False):
        for piece in measure.wrap(value, IN, size):
            ops.append((piece, M + (IN - measure.width_of(piece, size, bold)) / 2, y[0], size, bold))
            y[0] += size * 1.32

    def row(label, value, size=8):
        vw = measure.width_of(value, size, True)
        if vw > IN * .55:
            for piece in measure.wrap(label, IN, size):
                ops.append((piece, M, y[0], size, False))
                y[0] += size * 1.3
            for piece in measure.wrap(value, IN, size):
                ops.append((piece, M + IN - measure.width_of(piece, size, True), y[0], size, True))
                y[0] += size * 1.3
            return
        for i, piece in enumerate(measure.wrap(label, IN - vw - 6, size)):
            ops.append((piece, M, y[0], size, False))
            if i == 0:
                ops.append((value, M + IN - vw, y[0], size, True))
            y[0] += size * 1.3

    def rule():
        y[0] += 2
        ops.append(('__rule__', M, y[0], IN, False))
        y[0] += 5
    center(d['company']['legal'], 9.5, True)
    center('LIQUIDACIÓN INTERNA', 9, True)
    center('Cobertura PC-DOCTOR N.º %d' % d['id'], 8.5)
    center('NO ENTREGAR AL CLIENTE', 8.5, True)
    for group in (head, figures, supplier, payments or [('Sin pagos registrados', '—')]):
        rule()
        for label, value in group:
            row(label, value)
    rule()
    center('Generado el %s' % now.strftime('%d/%m/%Y %H:%M'), 7.2)
    y[0] += 8
    pdf = Canvas(W, y[0], 'Cobertura %d' % d['id'], mono=True)
    pdf.page()
    for value, x, top, size, bold in ops:
        if value == '__rule__':
            pdf.stream.set_color_rgb(0, 0, 0)
            pdf.stream.rectangle(x, pdf.h - top - .9, size, .9)
            pdf.stream.fill()
        else:
            pdf.text(value, x, top, size, bold)
    return pdf.finish()


def render(c, user, cov_id, thermal_format=False, now=None):
    from reception import ECUADOR_TZ
    now = now or datetime.now(ECUADOR_TZ)
    return thermal(c, user, cov_id, now) if thermal_format else a4(c, user, cov_id, now)
