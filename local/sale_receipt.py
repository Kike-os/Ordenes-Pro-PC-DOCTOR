"""Comprobante de venta (documento NO tributario): ticket térmico de 80 mm (Epson TM-m30II: 72 mm útiles a 203 ppp, una página de altura
variable, logo monocromo) y A4. Copia del cliente, del establecimiento o ambas.

Solo lee: imprimir o reimprimir no crea ventas, cobros, movimientos de caja ni de inventario. Las partidas y el IVA se calculan con las mismas
reglas que la factura (`invoicing.split_inclusive`, precios con IVA incluido), así comprobante y factura nunca difieren. Si la venta tiene
factura electrónica, el comprobante la menciona pero no la sustituye: su representación impresa es el RIDE de Facturación.

Tipos de venta (los del Centro de Ventas): directa y desde cotización (proformas convertidas sin orden técnica), licencias (VLIC) e
inventario (salida «Venta» del Centro de Inventario)."""
from datetime import datetime

import banking
import invoicing
import license_sales
import proformas
import quotes
from corporate import settings as corporate_settings
from document_canvas import BLUE, GRAY, INK, Canvas
from reception import ECUADOR_TZ

KINDS = {'directa': 'Venta directa', 'cotizacion': 'Venta desde cotización', 'licencia': 'Venta de licencias', 'inventario': 'Venta de inventario'}
COPIES = {'cliente': ('COPIA DEL CLIENTE',), 'establecimiento': ('COPIA DEL ESTABLECIMIENTO',), 'ambas': ('COPIA DEL CLIENTE', 'COPIA DEL ESTABLECIMIENTO')}
STATES = {'pagada': 'Pagada', 'por_cobrar': 'Saldo pendiente', 'anulada': 'Anulada', 'sin_cobro': 'Cobro no registrado'}
NOTICE = 'DOCUMENTO NO TRIBUTARIO · NO VÁLIDO COMO FACTURA'
NAVY = (.08, .20, .38)
SOFT = (.94, .96, .99)
LINE = (.80, .85, .91)
DOT = 72 / 203


class ReceiptError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def usd(cents):
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return sign + '$' + format(cents // 100, ',').replace(',', '.') + ',%02d' % (cents % 100)


def _dt(value):
    try:
        return datetime.fromisoformat(str(value)).strftime('%d/%m/%Y %H:%M')
    except ValueError:
        return str(value or '')


def _account(c, account_id):
    a = c.execute('SELECT bank,account_type,number FROM bank_accounts WHERE id=?', (account_id,)).fetchone() if account_id else None
    return '%s · %s •••• %s' % (a['bank'], banking.TYPES.get(a['account_type'], a['account_type']).lower(), a['number'][-4:]) if a else ''


def _line(description, quantity, unit_cents, discount_cents, rate_bp):
    """Partida con IVA incluido (como la factura): el descuento se resta del bruto y el IVA sale del neto."""
    gross = quantity * unit_cents
    net = max(0, gross - discount_cents)
    base, tax, _ = invoicing.split_inclusive(net, rate_bp)
    return {'description': description, 'quantity': quantity, 'unit_cents': unit_cents, 'discount_cents': discount_cents, 'total_cents': net,
            'base_cents': base, 'tax_cents': tax, 'rate_bp': rate_bp}


def _invoice(c, invoice_id):
    if not invoice_id:
        return None
    inv = c.execute('SELECT id,status,environment,establishment,emission_point,sequential,access_key,authorization_number,authorized_at FROM invoices WHERE id=?',
                    (invoice_id,)).fetchone()
    if not inv or inv['status'] == 'descartado':
        return None
    return {'id': inv['id'], 'number': invoicing.number(inv), 'status': inv['status'], 'status_label': invoicing.STATUS.get(inv['status'], inv['status']),
            'authorized': inv['status'] == 'autorizado', 'test': str(inv['environment']) != '2', 'access_key': inv['access_key'] or '',
            'authorization_number': inv['authorization_number'] or '', 'authorized_at': inv['authorized_at'] or ''}


def collect(c, kind, sale_id):
    """Datos normalizados de una venta para su comprobante."""
    if kind not in KINDS or not str(sale_id).isdigit():
        raise ReceiptError('Venta no válida.', 404)
    sale_id = int(sale_id)
    rate = quotes.tax_rate(c)
    general_discount = 0
    if kind in ('directa', 'cotizacion'):
        p = c.execute("SELECT p.*,COALESCE(u.name,'') seller,COALESCE(i.created_at,p.updated_at) sold_at FROM proformas p LEFT JOIN users u ON u.id=p.created_by "
                      "LEFT JOIN invoices i ON i.id=p.invoice_id WHERE p.id=? AND p.status='convertida' AND p.origin!='orden'", (sale_id,)).fetchone()
        if not p:
            raise ReceiptError('Venta no disponible.', 404)
        kind = 'directa' if p['origin'] == 'directa' else 'cotizacion'
        lines = [_line(i['description'], i['quantity'], i['unit_cents'], i['discount_cents'], p['tax_rate_bp'] if i['taxed'] else 0)
                 for i in proformas.items_of(c, sale_id) if i['status'] == 'aprobado']
        client = {'name': p['client_name'] or 'Consumidor final', 'id': p['client_identification'], 'phone': p['client_phone'], 'email': p['client_email'],
                  'address': p['client_address']}
        payments = []
        for a in c.execute("SELECT a.*,(SELECT t.status FROM bank_transfers t WHERE t.advance_id=a.id) transfer_status FROM advances a WHERE a.proforma_id=? AND a.voided_at='' ORDER BY a.id",
                           (sale_id,)):
            state = banking.TRANSFER_STATUS.get(a['transfer_status'], '') if a['method'] in ('transferencia', 'deposito') else 'Registrado'
            payments.append({'method': proformas.ADVANCE_LABELS.get(a['method'], a['method']), 'reference': a['reference'] or '', 'account': _account(c, a['bank_account_id']),
                             'amount_cents': a['amount_cents'], 'at': a['paid_at'], 'state': state or 'Registrado', 'counted': True})
        code, sold_at, seller, notes = p['code'], p['sold_at'], p['seller'], ''
        invoice = _invoice(c, p['invoice_id'])
        void = bool(p['invoice_id']) and not invoice and c.execute("SELECT 1 FROM invoices WHERE id=? AND status='descartado'", (p['invoice_id'],)).fetchone() is not None
        total = sum(x['total_cents'] for x in lines)
    elif kind == 'licencia':
        s = c.execute("SELECT s.*,k.name client,COALESCE(k.identification,'') identification,COALESCE(k.phone,'') phone,COALESCE(k.email,'') email,"
                      "COALESCE(u.name,'') seller FROM license_sales s JOIN clients k ON k.id=s.client_id LEFT JOIN users u ON u.id=s.created_by WHERE s.id=?",
                      (sale_id,)).fetchone()
        if not s:
            raise ReceiptError('Venta no disponible.', 404)
        # Nunca se imprimen claves ni cuentas de licencias: solo el producto vendido.
        lines = [_line(i['product_name'], i['quantity'], i['unit_price_cents'], i['discount_cents'], rate if i['taxed'] else 0)
                 for i in c.execute('SELECT x.*,k.taxed FROM license_sale_items x JOIN catalog_items k ON k.id=x.product_id WHERE x.sale_id=? ORDER BY x.position,x.id', (sale_id,))]
        # Recargos por pago con tarjeta de crédito: suben el total de la venta y van como partidas propias, con IVA.
        lines += [_line('Recargo por pago con tarjeta de crédito (%s %%)' % ('%.2f' % (r['percent_bp'] / 100)).rstrip('0').rstrip('.').replace('.', ','), 1, r['amount_cents'], 0, rate)
                  for r in c.execute('SELECT amount_cents,percent_bp FROM license_sale_surcharges WHERE sale_id=? AND voided_at IS NULL ORDER BY id', (sale_id,))]
        # El descuento de la venta es la suma de los de sus partidas (ya restados en cada una): solo un excedente sería un descuento general.
        general_discount = max(0, (s['discount_cents'] or 0) - sum(x['discount_cents'] for x in lines))
        client = {'name': s['client'], 'id': s['identification'], 'phone': s['phone'], 'email': s['email'], 'address': ''}
        payments = [{'method': license_sales.METHODS.get(x['method'], x['method']), 'reference': x['reference'] or '', 'account': '', 'amount_cents': x['amount_cents'],
                     'at': x['paid_on'] or x['created_at'], 'state': license_sales.PAYMENT_STATES.get(x['status'], x['status']), 'counted': x['status'] == 'confirmado'}
                    for x in c.execute("SELECT * FROM license_sale_payments WHERE sale_id=? AND status!='anulado' ORDER BY id", (sale_id,))]
        code, sold_at, seller, notes = s['code'], s['created_at'], s['seller'], ''
        inv = c.execute("SELECT id FROM invoices WHERE license_sale_id=? AND status!='descartado' ORDER BY id DESC LIMIT 1", (sale_id,)).fetchone()
        invoice = _invoice(c, inv['id'] if inv else None)
        void = s['payment_status'] == 'cancelado'
        total = s['total_cents']
    else:
        m = c.execute("SELECT m.*,k.name product,k.taxed,COALESCE(cl.name,'') client,COALESCE(cl.identification,'') identification,COALESCE(cl.phone,'') phone,"
                      "COALESCE(cl.email,'') email,COALESCE(u.name,'') seller FROM inventory_movements m JOIN inventory_items i ON i.id=m.item_id JOIN catalog_items k ON k.id=i.catalog_id "
                      "LEFT JOIN clients cl ON cl.id=m.client_id LEFT JOIN users u ON u.id=m.created_by WHERE m.id=? AND m.reason='venta' AND m.direction=-1 "
                      "AND m.reference_kind NOT IN ('factura','orden')", (sale_id,)).fetchone()
        if not m:
            raise ReceiptError('Venta no disponible.', 404)
        serials = [r[0] for r in c.execute('SELECT COALESCE(NULLIF(u.serial,\'\'),u.internal_code) FROM inventory_movement_units x JOIN inventory_units u ON u.id=x.unit_id WHERE x.movement_id=?',
                                           (sale_id,))]
        unit = (m['sale_price_cents'] or 0) + (m['discount_cents'] or 0)
        lines = [_line(m['product'] + ((' · Serie: ' + ', '.join(serials)) if serials else ''), m['quantity'], unit, (m['discount_cents'] or 0) * m['quantity'],
                       rate if m['taxed'] else 0)]
        client = {'name': m['client'] or 'Sin cliente registrado', 'id': m['identification'], 'phone': m['phone'], 'email': m['email'], 'address': ''}
        payments, code, sold_at, seller, notes = [], 'INV-%d' % sale_id, m['created_at'], m['seller'], 'El cobro de esta venta no se registró en el sistema.'
        inv = c.execute("SELECT id FROM invoices WHERE source_kind='venta_inventario' AND source_id=? AND status!='descartado' ORDER BY id DESC LIMIT 1", (sale_id,)).fetchone()
        invoice = _invoice(c, inv['id'] if inv else None)
        void = False
        total = lines[0]['total_cents']
    paid = sum(p['amount_cents'] for p in payments if p['counted'])
    balance = 0 if void or kind == 'inventario' else max(total - paid, 0)  # una venta del inventario no registra cobros: no hay saldo que mostrar
    state = 'anulada' if void else 'sin_cobro' if kind == 'inventario' else 'por_cobrar' if balance else 'pagada'
    # Desglose del IVA: exacto partida por partida. Con un descuento general (solo en licencias) el reparto entre partidas no está registrado:
    # el comprobante muestra el total con IVA incluido y no inventa una base.
    split = not general_discount
    totals = {'gross_cents': sum(x['quantity'] * x['unit_cents'] for x in lines), 'discount_cents': sum(x['discount_cents'] for x in lines) + general_discount,
              'general_discount_cents': general_discount, 'base_taxed_cents': sum(x['base_cents'] for x in lines if x['rate_bp']) if split else None,
              'base_zero_cents': sum(x['base_cents'] for x in lines if not x['rate_bp']) if split else None, 'tax_cents': sum(x['tax_cents'] for x in lines) if split else None,
              'total_cents': total, 'rate_pct': ('%g' % (rate / 100)).replace('.', ',')}
    fiscal = {}
    try:
        fiscal = invoicing.settings(c)
    except Exception:
        pass
    corp = corporate_settings()
    return {'kind': kind, 'kind_label': KINDS[kind], 'id': sale_id, 'code': code, 'sold_at': sold_at, 'seller': seller, 'client': client, 'lines': lines, 'totals': totals,
            'payments': payments, 'paid_cents': min(paid, total), 'balance_cents': balance, 'state': state, 'state_label': STATES[state], 'invoice': invoice, 'notes': notes,
            'company': {'name': fiscal.get('trade_name') or corp.get('name') or 'PC-DOCTOR S.A.', 'legal': fiscal.get('legal_name') or corp.get('name') or 'PC-DOCTOR S.A.',
                        'ruc': fiscal.get('ruc') or '', 'address': fiscal.get('head_office_address') or '',
                        'contact': ' · '.join(x for x in (corp.get('whatsapp', ''), corp.get('support_email', ''), corp.get('website', '')) if x),
                        'thanks': corp.get('thanks') or 'Gracias por su compra.'}}


def summary(c, kind, sale_id):
    """Lo que necesita la ventana de impresión (sin las partidas)."""
    d = collect(c, kind, sale_id)
    return {k: d[k] for k in ('kind', 'kind_label', 'id', 'code', 'sold_at', 'state', 'state_label', 'invoice', 'paid_cents', 'balance_cents')} | {
        'client': d['client']['name'], 'total_cents': d['totals']['total_cents'], 'copies': {k: v[0].title() if len(v) == 1 else 'Ambas copias' for k, v in COPIES.items()}}


class Flow:
    """Registra lo que se dibuja por página; las páginas y su numeración se crean al final."""

    def __init__(self, top, bottom):
        self.top, self.bottom, self.pages, self.y = top, bottom, [[]], top
        self.measure = Canvas(10, 10, 'medida')

    def op(self, *args):
        self.pages[-1].append(args)

    def need(self, height):
        if self.y + height > self.bottom:
            self.pages.append([])
            self.y = self.top
            return True
        return False

    def wrap(self, text, width, size, limit=None):
        pieces = self.measure.wrap(text, width, size)
        if limit and len(pieces) > limit:
            last = pieces[limit - 1]
            while last and self.measure.width_of(last + '…', size) > width:
                last = last[:-1]
            pieces = pieces[:limit - 1] + [last.rstrip() + '…']
        return pieces

    def width(self, text, size, bold=False):
        return self.measure.width_of(text, size, bold)


def _paint(pdf, ops, mono=False):
    for op in ops:
        kind, args = op[0], op[1:]
        if kind == 'text':
            pdf.text(*args)
        elif kind == 'box':
            if mono:
                x, y, w, h = args[:4]
                pdf.stream.set_color_rgb(0, 0, 0)
                pdf.stream.rectangle(x, pdf.h - y - h, w, h)
                pdf.stream.fill()
            else:
                pdf.box(*args)
        elif kind == 'logo':
            pdf.logo(*args)
        elif kind == 'qr':
            pdf.qr(*args)


def thermal(d, copy, link, now):
    """Ticket de 72 mm útiles, margen de 1 mm y altura según el contenido: se imprime al 100 % sin escalar. «Ambas» son dos páginas iguales."""
    W = 72 * 72 / 25.4
    M = 1 * 72 / 25.4
    IN = W - 2 * M
    pages = []
    for label in COPIES[copy]:
        f = Flow(0, 10 ** 6)

        def text(value, x, size=8.5, bold=False):
            f.op('text', value, x, f.y, size, bold)

        def center(value, size=8.5, bold=False, gap=1.3):
            for piece in f.wrap(value, IN / 1.08 if bold else IN, size):  # la negrita es más ancha: se mide con margen
                text(piece, M + (IN - f.width(piece, size, bold)) / 2, size, bold)
                f.y += size * gap

        def para(value, size=8, bold=False, indent=0):
            for piece in f.wrap(value, (IN - indent) / (1.08 if bold else 1), size):
                text(piece, M + indent, size, bold)
                f.y += size * 1.3

        def row(label_, value, size=8.5, bold=False, indent=0):
            vw = f.width(value, size, bold)
            for i, piece in enumerate(f.wrap(label_, (IN - indent - vw - 8) / (1.08 if bold else 1), size)):
                text(piece, M + indent, size, bold)
                if i == 0:
                    f.op('text', value, M + IN - vw, f.y, size, bold)
                f.y += size * 1.3

        def rule(dashed=False):
            f.y += 2
            if dashed:
                x = M
                while x < M + IN:
                    f.op('box', x, f.y, min(3, M + IN - x), .6)
                    x += 5
            else:
                f.op('box', M, f.y, IN, .9)
            f.y += 5

        f.y = 6
        logo_w = 32 * 72 / 25.4
        f.op('logo', M + (IN - logo_w) / 2, f.y, logo_w)
        f.y += logo_w * f.measure.ih / f.measure.iw + 6
        co = d['company']
        center(co['legal'], 9.5, True)
        center(('RUC ' + co['ruc']) if co['ruc'] else 'RUC no configurado', 8)
        if co['address']:
            center(co['address'], 7.5)
        if co['contact']:
            center(co['contact'], 7.5)
        rule()
        center('COMPROBANTE DE VENTA', 10.5, True)
        center(NOTICE, 8, True)
        center(label, 8)
        rule(True)
        center(d['code'], 14, True, 1.2)
        center(d['kind_label'], 8)
        f.y += 2
        row('Fecha y hora', _dt(d['sold_at']), 8)
        if d['seller']:
            row('Atendió', d['seller'], 8)
        rule(True)
        cl = d['client']
        para('CLIENTE', 8.5, True)
        para(cl['name'], 8.5)
        for value in (('Identificación: ' + cl['id']) if cl['id'] else '', ('Teléfono: ' + cl['phone']) if cl['phone'] else ''):
            if value:
                para(value, 7.8)
        rule()
        para('DETALLE', 9, True)
        for x in d['lines']:
            para(x['description'], 8.2, True)
            row('%s × %s%s' % (x['quantity'], usd(x['unit_cents']), '' if x['rate_bp'] else ' (IVA 0 %)'), usd(x['quantity'] * x['unit_cents']), 8, False, 6)
            if x['discount_cents']:
                row('Descuento', '-' + usd(x['discount_cents']), 8, False, 6)
            f.y += 1.5
        rule()
        t = d['totals']
        if t['general_discount_cents']:
            row('Descuento general', '-' + usd(t['general_discount_cents']), 8.5)
        if t['tax_cents'] is not None:
            if t['base_taxed_cents']:
                row('Subtotal IVA %s %%' % t['rate_pct'], usd(t['base_taxed_cents']), 8.5)
            if t['base_zero_cents']:
                row('Subtotal IVA 0 %', usd(t['base_zero_cents']), 8.5)
            row('IVA %s %%' % t['rate_pct'], usd(t['tax_cents']), 8.5)
        if t['discount_cents']:
            row('Descuentos incluidos', usd(t['discount_cents']), 8)
        row('TOTAL', usd(t['total_cents']), 12, True)
        if t['tax_cents'] is None:
            para('Precios con IVA incluido; el desglose consta en la factura.', 7.5)
        rule()
        para('PAGO', 9, True)
        if d['payments']:
            for p in d['payments']:
                row(p['method'], usd(p['amount_cents']), 8.2)
                detail = ' · '.join(x for x in (p['account'], ('ref. ' + p['reference']) if p['reference'] else '', p['state']) if x)
                if detail:
                    para(detail, 7.5, False, 6)
            row('Pagado', usd(d['paid_cents']), 8.5)
        else:
            para(d['notes'] or 'Sin pagos registrados.', 7.8)
        if d['balance_cents']:
            row('Saldo pendiente', usd(d['balance_cents']), 9, True)
        f.y += 2
        center('ESTADO: ' + d['state_label'].upper(), 10, True)
        inv = d['invoice'] if d['invoice'] and d['invoice']['status'] != 'borrador' else None
        if inv:
            rule(True)
            para('Factura electrónica %s · %s%s' % (inv['number'] or '(sin número)', inv['status_label'], ' (ambiente de pruebas)' if inv['test'] else ''), 7.8, True)
            para('La factura electrónica es el comprobante tributario; este ticket no la sustituye.', 7.5)
        rule()
        if link:
            modules = len(list(__import__('segno').make_qr(link, error='m').matrix)) + 8
            dots = max(2, min(4, int((IN * .55) / (modules * DOT))))
            size = modules * dots * DOT
            x = round((M + (IN - size) / 2) / DOT) * DOT
            f.y = round(f.y / DOT) * DOT
            f.op('qr', link, x, f.y, size)
            f.y += size + 2
            center('Consulta interna de la venta (requiere sesión autorizada)', 7.2)
            f.y += 3
        center(co['thanks'], 9, True)
        f.y += 3
        center('Impreso el %s (hora de Ecuador)' % now.strftime('%d/%m/%Y %H:%M'), 7.2)
        f.y += 8
        pages.append((f.y, f.pages[0]))
    height = max(h for h, _ in pages)
    pdf = Canvas(W, height, 'COMPROBANTE-' + d['code'], mono=True)
    for _, ops in pages:
        pdf.page()
        _paint(pdf, ops, True)
    return pdf.finish()


def a4(d, copy, link, now):
    W, H, L = 595, 842, 40
    R = W - L
    CW = R - L
    pdf = Canvas(W, H, 'COMPROBANTE-' + d['code'])
    for label in COPIES[copy]:
        f = Flow(92, H - 70)

        def text(value, x, y, size=9, bold=False, color=INK):
            f.op('text', value, x, y, size, bold, color)

        def right(value, x, y, size=9, bold=False, color=INK):
            f.op('text', value, x - f.width(value, size, bold), y, size, bold, color)

        co, t, cl = d['company'], d['totals'], d['client']
        f.op('logo', L, 30, 104)
        text(co['legal'], L + 118, 34, 12.5, True, NAVY)
        y = 51
        if co['ruc']:
            text('RUC ' + co['ruc'], L + 118, y, 8.4)
            y += 12
        else:
            text('RUC no configurado (Facturación › Datos fiscales)', L + 118, y, 7.8, True, (.70, .13, .16))
            y += 12
        for line in (co['address'], co['contact']):
            for piece in f.wrap(line, 210, 7.6, 2) if line else []:
                text(piece, L + 118, y, 7.6, False, GRAY)
                y += 10
        if link:
            f.op('qr', link, R - 66, 26, 66)
        right('COMPROBANTE DE VENTA', R - 74, 32, 11, True, NAVY)
        right(d['code'], R - 74, 47, 16, True, NAVY)
        right(label, R - 74, 67, 8, True, GRAY)
        right('Consulta interna: requiere sesión', R - 74, 79, 6.8, False, GRAY)
        f.y = 108
        f.op('box', L, f.y, CW, 22, (.99, .94, .86))
        notice = NOTICE + (' · La factura electrónica es el comprobante tributario' if d['invoice'] and d['invoice']['status'] != 'borrador' else '')
        text(notice, L + (CW - f.width(notice, 8.6, True)) / 2, f.y + 7, 8.6, True, (.55, .33, .02))
        f.y += 32
        # Datos de la venta y del cliente.
        half = CW / 2 - 6
        f.op('box', L, f.y, half, 78, SOFT)
        f.op('box', L + half + 12, f.y, half, 78, SOFT)
        text('VENTA', L + 10, f.y + 8, 7, True, GRAY)
        for i, (k, v) in enumerate((('Tipo', d['kind_label']), ('Fecha y hora', _dt(d['sold_at'])), ('Atendió', d['seller'] or '—'), ('Estado del pago', d['state_label']))):
            text(k, L + 10, f.y + 21 + i * 13, 8.2, False, GRAY)
            text(f.wrap(v, half - 110, 8.6, 1)[0], L + 100, f.y + 21 + i * 13, 8.6, True)
        x2 = L + half + 22
        text('CLIENTE', x2, f.y + 8, 7, True, GRAY)
        text(f.wrap(cl['name'], half - 20, 9.5, 1)[0], x2, f.y + 21, 9.5, True)
        yy = f.y + 35
        for v in (('Identificación: ' + cl['id']) if cl['id'] else '', ('Teléfono: ' + cl['phone']) if cl['phone'] else '', cl['email'], cl['address']):
            if v and yy < f.y + 74:
                text(f.wrap(v, half - 20, 8.2, 1)[0], x2, yy, 8.2, False, INK)
                yy += 12
        f.y += 90
        # Detalle.
        cols = [('Descripción', 250, 'l'), ('Cant.', 40, 'r'), ('P. unitario', 70, 'r'), ('Descuento', 70, 'r'), ('Total', 85, 'r')]
        scale = CW / sum(w for _, w, _ in cols)
        ws = [w * scale for _, w, _ in cols]

        def header():
            f.op('box', L, f.y, CW, 18, NAVY)
            x = L
            for (title, _, align), w in zip(cols, ws):
                (right(title, x + w - 6, f.y + 5, 7.6, True, (1, 1, 1)) if align == 'r' else text(title, x + 6, f.y + 5, 7.6, True, (1, 1, 1)))
                x += w
            f.y += 18
        header()
        for n, item in enumerate(d['lines']):
            pieces = f.wrap(item['description'] + ('' if item['rate_bp'] else ' (IVA 0 %)'), ws[0] - 12, 8.4, 4)
            h = 9 + 10.5 * len(pieces)
            if f.need(h):
                header()
            if n % 2:
                f.op('box', L, f.y, CW, h, (.975, .98, .99))
            for i, piece in enumerate(pieces):
                text(piece, L + 6, f.y + 5 + i * 10.5, 8.4)
            x = L + ws[0]
            values = (str(item['quantity']), usd(item['unit_cents']), ('-' + usd(item['discount_cents'])) if item['discount_cents'] else '—', usd(item['total_cents']))
            for i, (value, w) in enumerate(zip(values, ws[1:])):
                right(value, x + w - 6, f.y + 5, 8.4, i == 3)
                x += w
            f.y += h
            f.op('box', L, f.y, CW, .5, LINE)
        # Totales a la derecha; pagos a la izquierda.
        totals = []
        if t['general_discount_cents']:
            totals.append(('Descuento general', '-' + usd(t['general_discount_cents'])))
        if t['tax_cents'] is not None:
            if t['base_taxed_cents']:
                totals.append(('Subtotal IVA %s %%' % t['rate_pct'], usd(t['base_taxed_cents'])))
            if t['base_zero_cents']:
                totals.append(('Subtotal IVA 0 %', usd(t['base_zero_cents'])))
            totals.append(('IVA %s %%' % t['rate_pct'], usd(t['tax_cents'])))
        if t['discount_cents']:
            totals.append(('Descuentos incluidos', usd(t['discount_cents'])))
        pay_lines = []
        for p in d['payments']:
            pay_lines.append((p['method'] + (' · ' + p['account'] if p['account'] else ''), usd(p['amount_cents']),
                              ' · '.join(x for x in (('Ref. ' + p['reference']) if p['reference'] else '', p['state'], _dt(p['at'])) if x)))
        block = max(26 + 13 * len(totals) + 26, 30 + 24 * max(1, len(pay_lines)) + 30)
        f.need(block + 10)
        f.y += 10
        top = f.y
        tw = 220
        tx = R - tw
        f.op('box', tx, top, tw, 13 * len(totals) + 40, SOFT)
        yy = top + 8
        for k, v in totals:
            text(k, tx + 10, yy, 8.6, False, GRAY)
            right(v, R - 10, yy, 8.6)
            yy += 13
        f.op('box', tx + 10, yy + 1, tw - 20, .8, NAVY)
        text('TOTAL', tx + 10, yy + 8, 12, True, NAVY)
        right(usd(t['total_cents']), R - 10, yy + 7, 13, True, NAVY)
        if t['tax_cents'] is None:
            text('IVA incluido; el desglose consta en la factura.', tx + 10, yy + 26, 7, False, GRAY)
        pw = CW - tw - 16
        text('PAGOS', L, top + 2, 8.6, True, NAVY)
        yy = top + 16
        if pay_lines:
            for k, v, sub in pay_lines:
                text(f.wrap(k, pw - 80, 8.6, 1)[0], L, yy, 8.6, True)
                right(v, L + pw, yy, 8.6, True)
                if sub:
                    text(f.wrap(sub, pw, 7.6, 1)[0], L, yy + 11, 7.6, False, GRAY)
                yy += 24
            text('Pagado', L, yy, 8.6, False, GRAY)
            right(usd(d['paid_cents']), L + pw, yy, 8.6, True)
            yy += 13
        else:
            text(d['notes'] or 'Sin pagos registrados.', L, yy, 8.4, False, GRAY)
            yy += 13
        if d['balance_cents']:
            text('Saldo pendiente', L, yy, 9, True, (.70, .13, .16))
            right(usd(d['balance_cents']), L + pw, yy, 9, True, (.70, .13, .16))
            yy += 13
        f.y = max(yy, top + 13 * len(totals) + 40) + 12
        inv = d['invoice'] if d['invoice'] and d['invoice']['status'] != 'borrador' else None
        if inv:
            f.need(40)
            text('Factura electrónica %s · %s%s' % (inv['number'] or '(sin número)', inv['status_label'], ' (ambiente de pruebas: sin validez tributaria)' if inv['test'] else ''),
                 L, f.y, 8.6, True, NAVY)
            f.y += 12
            if inv['access_key']:
                text('Clave de acceso: ' + inv['access_key'], L, f.y, 7.6, False, GRAY)
                f.y += 11
            text('Su representación impresa es el RIDE, disponible en Facturación. Este comprobante no la sustituye.', L, f.y, 7.6, False, GRAY)
            f.y += 14
        f.need(30)
        msg = co['thanks']
        text(msg, L + (CW - f.width(msg, 11, True)) / 2, f.y + 6, 11, True, NAVY)
        f.y += 24
        total_pages = len(f.pages)
        for number, ops in enumerate(f.pages, 1):
            pdf.page()
            if number > 1:
                pdf.logo(L, 26, 64)
                pdf.text('Comprobante de venta %s · %s (continuación)' % (d['code'], label.lower()), L + 78, 40, 10, True, NAVY)
                pdf.box(L, 76, CW, 1, NAVY)
            _paint(pdf, ops)
            pdf.box(L, H - 48, CW, .6, LINE)
            pdf.text('%s · %s · %s · Impreso el %s (hora de Ecuador)' % (co['name'], d['code'], NOTICE.split(' · ')[0].capitalize(), now.strftime('%d/%m/%Y %H:%M')),
                     L, H - 40, 7, False, GRAY)
            page = 'Página %d de %d' % (number, total_pages)
            pdf.text(page, R - pdf.width_of(page, 7), H - 40, 7, False, GRAY)
    return pdf.finish()


def render(c, kind, sale_id, fmt='termico', copy='cliente', link='', now=None):
    if fmt not in ('termico', 'a4'):
        raise ReceiptError('Formato no válido.')
    if copy not in COPIES:
        raise ReceiptError('Copia no válida.')
    d = collect(c, kind, sale_id)
    now = now or datetime.now(ECUADOR_TZ)
    return d, (thermal if fmt == 'termico' else a4)(d, copy, link, now)
