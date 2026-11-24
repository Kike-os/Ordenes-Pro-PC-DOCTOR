"""Premium Billing Center · comprobantes no tributarios: recibo de pago (térmico; el A5 sigue en payment_pdf), comprobante de anticipo
(A5 y térmico) y comprobante de entrega (A4 y térmico). docs/COMPROBANTES.md.

Reglas:
- SOLO LECTURA: imprimir o descargar nunca cambia pagos, anticipos, órdenes ni facturas, ni consume secuenciales.
- No son facturas ni comprobantes de venta del SRI, y cada documento lo dice.
- Solo datos registrados: lo que no consta se indica así («No registrado»); la garantía solo se muestra si está registrada.
- El QR solo aparece con un enlace de seguimiento ACTIVO de la orden (consulta segura con token); si no lo hay, se indica."""
from datetime import datetime

from corporate import settings
from document_canvas import Canvas, BLUE, GRAY, INK
from reception import ECUADOR_TZ

ROSE = (0xAA / 255, 0x47 / 255, 0x7C / 255)
RED = (.70, .16, .20)
GREEN = (.08, .45, .30)
NOT_TAX = 'Documento interno de PC-DOCTOR S.A. No es una factura ni un comprobante de venta autorizado por el SRI.'


def usd(cents):
    value = '{:,.2f}'.format((cents or 0) / 100).replace(',', 'X').replace('.', ',').replace('X', '.')
    return '$' + value


def when(value):
    if not value:
        return 'No registrada'
    try:
        moment = datetime.fromisoformat(str(value))
        if moment.tzinfo:
            moment = moment.astimezone(ECUADOR_TZ)
        return moment.strftime('%d/%m/%Y %H:%M') if len(str(value)) > 10 else moment.strftime('%d/%m/%Y')
    except ValueError:
        return str(value)


# ───────────────────────────────────────────── datos (solo lectura)
def _tracking(c, oid):
    try:
        import order_tracking
        return order_tracking.active(c, oid)['url'] or ''
    except Exception:
        return ''


def _invoice_for_order(c, oid):
    import invoicing
    row = c.execute("SELECT * FROM invoices WHERE order_id=? AND status IN ('pendiente','enviado','autorizado') ORDER BY id DESC LIMIT 1", (oid,)).fetchone()
    return (invoicing.number(row) + ' · ' + invoicing.STATUS[row['status']]) if row else ''


def payment(c, oid, pid):
    import equipment
    found = equipment.receipt(c, oid, pid)
    if not found:
        return None
    found['tracking'] = _tracking(c, oid)
    found['invoice'] = _invoice_for_order(c, oid)
    return found


def advance(c, proforma_id, advance_id):
    import equipment
    row = c.execute("SELECT a.*,COALESCE(u.name,'') actor,COALESCE(v.name,'') void_actor FROM advances a LEFT JOIN users u ON u.id=a.created_by LEFT JOIN users v ON v.id=a.voided_by "
                    'WHERE a.id=? AND a.proforma_id=?', (advance_id, proforma_id)).fetchone()
    if not row:
        return None
    p = c.execute('SELECT * FROM proformas WHERE id=?', (proforma_id,)).fetchone()
    paid = c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM advances WHERE proforma_id=? AND voided_at=''", (proforma_id,)).fetchone()[0]
    order = c.execute('SELECT id,code FROM orders WHERE id=?', (p['order_id'],)).fetchone() if p['order_id'] else None
    concept = [r[0] for r in c.execute('SELECT description FROM proforma_items WHERE proforma_id=? ORDER BY position LIMIT 4', (proforma_id,))] if _has(c, 'proforma_items') else []
    method = equipment.PAY_METHODS.get(row['method'], row['method'])
    return {'advance': dict(row), 'method': method, 'proforma': {'code': p['code'], 'version': p['version'], 'client': p['client_name'], 'identification': p['client_identification'],
                                                               'total_cents': p['total_cents'], 'status': p['status']},
            'order_code': order['code'] if order else '', 'concept': concept, 'paid_cents': paid, 'balance_cents': max(p['total_cents'] - paid, 0),
            'credit_cents': max(paid - p['total_cents'], 0), 'tracking': _tracking(c, order['id']) if order else ''}


def _has(c, table):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def delivery(c, oid):
    """Datos del comprobante de entrega. None si la orden no existe; 'no_entregada' si aún no se entregó."""
    import equipment
    o = c.execute("SELECT o.*,s.label status_label,cl.name client,COALESCE(cl.identification,'') identification,d.brand,d.model,d.serial,COALESCE(NULLIF(d.kind,''),d.category) type "
                  'FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?', (oid,)).fetchone()
    if not o:
        return None
    if o['status'] != 'entregado' and not o['delivered_at']:
        return 'no_entregada'
    log = c.execute("SELECT l.created_at,TRIM(COALESCE(l.reason,'')||' '||COALESCE(l.detail,'')) note,COALESCE(u.name,'') actor FROM order_status_log l LEFT JOIN users u ON u.id=l.actor_id "
                    "WHERE l.order_id=? AND l.to_status='entregado' ORDER BY l.id DESC LIMIT 1", (oid,)).fetchone() if _has(c, 'order_status_log') else None
    services = [r['description'] for r in c.execute("SELECT i.description FROM quote_items i JOIN quotes q ON q.id=i.quote_id WHERE q.order_id=? AND i.status='aprobado' "
                                                    "AND COALESCE(q.deleted_at,'')='' ORDER BY q.id,i.position", (oid,))]
    money = equipment.money(c, oid)
    units = []
    if _has(c, 'inventory_units'):
        for u in c.execute("SELECT u.serial,u.store_warranty_to,u.maker_warranty_to,g.name FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id JOIN catalog_items g ON g.id=i.catalog_id WHERE u.order_id=? "
                           "AND (u.store_warranty_to!='' OR u.maker_warranty_to!='')", (oid,)):
            units.append({'name': u['name'], 'serial': u['serial'], 'store_to': u['store_warranty_to'], 'maker_to': u['maker_warranty_to']})
    return {'order': dict(o), 'delivered_at': o['delivered_at'] or (log['created_at'] if log else ''), 'delivered_by': log['actor'] if log else '', 'note': log['note'] if log else '',
            'services': services, 'findings': o['findings'] or '', 'recommendations': o['recommendations'] or '', 'money': money, 'warranty': units,
            'tracking': _tracking(c, oid), 'invoice': _invoice_for_order(c, oid)}


# ───────────────────────────────────────────── ticket térmico 80 mm (altura según el contenido)
class Ticket:
    """Rollo de 80 mm con 68 mm útiles (Epson TM-m30II). Se dibuja dos veces: la primera solo mide la altura."""
    W = 226.77
    LEFT = 17
    WIDTH = W - 2 * 17

    def __init__(self, title):
        self.title, self.ops = title, []

    def text(self, value, size=8.4, bold=False, center=False, gap=2.2):
        self.ops.append(('text', str(value), size, bold, center, gap))

    def pair(self, label, value, bold=False):
        self.ops.append(('pair', label, str(value or 'No registrado'), bold))

    def rule(self, gap=6):
        self.ops.append(('rule', gap))

    def space(self, h=6):
        self.ops.append(('space', h))

    def qr(self, url, caption):
        self.ops.append(('qr', url, caption))

    def _draw(self, pdf, measure=False):
        y = 12
        logo_h = 68 * pdf.ih / pdf.iw   # altura real del logo (mantiene su proporción)
        if not measure:
            pdf.logo(self.W / 2 - 34, y, 68)
        y += logo_h + 8
        for op in self.ops:
            kind = op[0]
            if kind == 'text':
                _, value, size, bold, center, gap = op
                for line in pdf.wrap(value, self.WIDTH, size):
                    if not measure:
                        x = self.W / 2 - pdf.width_of(line, size, bold) / 2 if center else self.LEFT
                        pdf.text(line, x, y, size, bold, (0, 0, 0))
                    y += size + gap
            elif kind == 'pair':
                _, label, value, bold = op
                size = 8.6 if bold else 8
                vw = pdf.width_of(value, size, bold)
                if vw <= self.WIDTH - pdf.width_of(label, 8) - 8:
                    if not measure:
                        pdf.text(label, self.LEFT, y, 8, False, (0, 0, 0))
                        pdf.text(value, self.LEFT + self.WIDTH - vw, y, size, bold, (0, 0, 0))
                    y += size + 3.4
                else:
                    if not measure:
                        pdf.text(label, self.LEFT, y, 8, False, (0, 0, 0))
                    y += 11
                    for line in pdf.wrap(value, self.WIDTH, size):
                        if not measure:
                            pdf.text(line, self.LEFT, y, size, bold, (0, 0, 0))
                        y += size + 2.6
                    y += 1
            elif kind == 'rule':
                y += op[1] / 2
                if not measure:
                    pdf.line(self.LEFT, y, self.WIDTH)
                y += op[1] / 2 + 2
            elif kind == 'space':
                y += op[1]
            elif kind == 'qr':
                _, url, caption = op
                size = 104
                if not measure:
                    pdf.qr(url, self.W / 2 - size / 2, y, size)
                y += size + 2
                for line in pdf.wrap(caption, self.WIDTH, 7.2):
                    if not measure:
                        pdf.text(line, self.W / 2 - pdf.width_of(line, 7.2) / 2, y, 7.2, False, (0, 0, 0))
                    y += 9.4
        return y + 16

    def render(self):
        probe = Canvas(self.W, 2000, self.title, mono=True)
        probe.page()
        height = max(260, self._draw(probe, measure=True))
        pdf = Canvas(self.W, height, self.title, mono=True)
        pdf.page()
        self._draw(pdf)
        return pdf.finish()


def _header(t, title, number, at):
    company = settings()
    t.text(company['name'], 9.6, True, True, 1.6)
    t.text(company['specialty'], 6.8, False, True, 1.4)
    t.rule(8)
    t.text(title, 10.4, True, True, 2)
    t.text(number + ' · ' + when(at), 8, False, True, 2)
    t.rule(8)


def _footer(t):
    company = settings()
    t.rule(8)
    t.text(NOT_TAX, 6.8, False, True, 1.6)
    t.space(4)
    t.text(company['name'] + ' · WhatsApp ' + company['whatsapp'], 6.8, False, True, 1.4)
    t.text(company['website'], 6.8, False, True, 1.4)


def payment_ticket(found, methods, generated):
    import payment_pdf
    pay, order, account = found['payment'], found['order'], found['account']
    refund = pay['kind'] == 'devolucion'
    t = Ticket(('Comprobante de devolución ' if refund else 'Recibo de pago ') + payment_pdf.number(pay))
    _header(t, 'COMPROBANTE DE DEVOLUCIÓN' if refund else 'RECIBO DE PAGO', payment_pdf.number(pay), pay['created_at'])
    t.pair('Orden', order['code'])
    if found.get('invoice'):
        t.pair('Factura', found['invoice'])
    t.pair('Cliente', order['client'])
    if order.get('identification'):
        t.pair('Identificación', order['identification'])
    equipo = ' '.join(x for x in (order.get('brand'), order.get('model')) if x)
    if equipo:
        t.pair('Equipo', equipo)
    t.rule()
    t.pair('Importe devuelto' if refund else 'Importe recibido', usd(pay['amount_cents']), True)
    t.pair('Forma de pago', methods.get(pay['method'], pay['method']))
    if pay.get('note'):
        t.pair('Referencia', pay['note'])
    t.pair('Registrado por', pay.get('actor') or 'No consta')
    if pay.get('voided_at'):
        t.text('MOVIMIENTO ANULADO el ' + when(pay['voided_at']) + '. Motivo: ' + (pay.get('void_reason') or 'No registrado'), 8, True, False)
    t.rule()
    t.pair('Total a cobrar', usd(account['budget_cents']))
    t.pair('Pagado a la fecha', usd(account['paid_cents']))
    t.pair('Saldo a favor' if account['credit_cents'] else 'Saldo pendiente', usd(account['credit_cents'] or account['balance_cents']), True)
    t.text(account['state_label'] + ' · calculado el ' + generated.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'), 7, False, False)
    if found.get('tracking'):
        t.rule()
        t.qr(found['tracking'] + '#' + order['code'], 'Consulta segura del estado de la orden')
    _footer(t)
    return t.render()


def advance_number(row):
    return row['code']


def advance_ticket(info, generated):
    a, p = info['advance'], info['proforma']
    t = Ticket('Comprobante de anticipo ' + a['code'])
    _header(t, 'COMPROBANTE DE ANTICIPO', a['code'], a['paid_at'] or a['created_at'])
    t.pair('Proforma', '%s v%s' % (p['code'], p['version']))
    if info['order_code']:
        t.pair('Orden', info['order_code'])
    t.pair('Cliente', p['client'])
    if p['identification']:
        t.pair('Identificación', p['identification'])
    if info['concept']:
        t.pair('Concepto', '; '.join(info['concept']))
    t.rule()
    t.pair('Valor total acordado', usd(p['total_cents']))
    t.pair('Anticipo recibido', usd(a['amount_cents']), True)
    t.pair('Forma de pago', info['method'])
    if a['reference']:
        t.pair('Referencia', a['reference'])
    t.pair('Anticipos a la fecha', usd(info['paid_cents']))
    t.pair('Saldo a favor' if info['credit_cents'] else 'Saldo pendiente', usd(info['credit_cents'] or info['balance_cents']), True)
    t.pair('Registrado por', a['actor'] or 'No consta')
    if a['voided_at']:
        t.text('ANTICIPO ANULADO el ' + when(a['voided_at']) + '. Motivo: ' + (a['void_reason'] or 'No registrado'), 8, True)
    t.text('Saldo calculado el ' + generated.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M') + '; puede cambiar con nuevos anticipos o anulaciones.', 7)
    if info.get('tracking'):
        t.rule()
        t.qr(info['tracking'] + '#' + info['order_code'], 'Consulta segura del estado de la orden')
    _footer(t)
    return t.render()


def _device(o):
    return ' '.join(x for x in (o.get('brand'), o.get('model')) if x) or 'Equipo sin especificar'


def delivery_ticket(info, generated):
    o = info['order']
    t = Ticket('Comprobante de entrega ' + o['code'])
    _header(t, 'COMPROBANTE DE ENTREGA', o['code'], info['delivered_at'])
    t.pair('Cliente', o['client'])
    if o['identification']:
        t.pair('Identificación', o['identification'])
    t.pair('Equipo', _device(o))
    t.pair('Serie', o['serial'] or 'No registrada')
    t.rule()
    t.text('Servicio realizado', 8.4, True)
    for s in info['services'][:12] or ['No hay partidas aprobadas registradas.']:
        t.text('• ' + s, 8)
    if info['findings']:
        t.pair('Diagnóstico', info['findings'][:400])
    t.rule()
    m = info['money']
    t.pair('Total', usd(m['budget_cents']))
    t.pair('Pagado', usd(m['paid_cents']))
    t.pair('Saldo a favor' if m['credit_cents'] else 'Saldo pendiente', usd(m['credit_cents'] or m['balance_cents']), True)
    if info['invoice']:
        t.pair('Factura', info['invoice'])
    t.rule()
    t.text('Garantía', 8.4, True)
    if info['warranty']:
        for w in info['warranty']:
            t.text('• %s%s: tienda hasta %s%s' % (w['name'], (' (S/N ' + w['serial'] + ')') if w['serial'] else '', when(w['store_to']) if w['store_to'] else '—',
                                                  ('; fabricante hasta ' + when(w['maker_to'])) if w['maker_to'] else ''), 7.6)
    else:
        t.text('Sin repuestos con garantía registrada en esta orden. La garantía del servicio se rige por las condiciones aceptadas en la recepción.', 7.6)
    if info['note'] or info['recommendations']:
        t.rule()
        t.pair('Observaciones', (info['note'] + ' ' + info['recommendations']).strip()[:500])
    t.pair('Entregado por', info['delivered_by'] or 'No consta')
    t.rule(10)
    t.text('Recibí conforme el equipo descrito:', 8, False)
    t.space(26)
    t.text('Firma: ______________________________', 8)
    t.space(6)
    t.text('Nombre y C.I.: _______________________', 8)
    if info['tracking']:
        t.rule()
        t.qr(info['tracking'] + '#' + o['code'], 'Seguimiento seguro de la orden')
    _footer(t)
    return t.render()


# ───────────────────────────────────────────── A5 / A4 (documento blanco corporativo)
class Sheet:
    def __init__(self, w, h, title):
        self.W, self.H, self.LEFT, self.RIGHT = w, h, 30 if w < 500 else 42, w - (30 if w < 500 else 42)
        self.pdf = Canvas(w, h, title)
        self.pdf.page()
        self.y = 0

    def fill(self, x, top, w, h, color):
        self.pdf.box(x, top, w, h, color)

    def right(self, value, top, size, bold=False, color=INK):
        self.pdf.text(value, self.RIGHT - self.pdf.width_of(value, size, bold), top, size, bold, color)

    def header(self, title, number, at, subtitle):
        company = settings()
        self.fill(0, 0, self.W, 4, BLUE)
        self.pdf.logo(self.LEFT, 20, 46)
        self.pdf.text(company['name'], self.LEFT + 56, 22, 14, True, BLUE)
        self.pdf.text(company['specialty'].upper(), self.LEFT + 56, 41, 6.6, True, GRAY)
        self.right(number, 22, 12, True, BLUE)
        self.right(when(at), 39, 7.6, False, GRAY)
        self.pdf.line(self.LEFT, 70, self.RIGHT - self.LEFT)
        self.pdf.text(title, self.LEFT, 82, 13, True, BLUE)
        self.pdf.text(subtitle, self.LEFT, 100, 8.4, False, GRAY)
        self.y = 122

    def section(self, label):
        width = self.RIGHT - self.LEFT
        self.fill(self.LEFT, self.y, width, 16, (.93, .95, .98))
        self.fill(self.LEFT, self.y, 2.5, 16, ROSE)
        self.pdf.text(label.upper(), self.LEFT + 8, self.y + 4.5, 7.8, True, BLUE)
        self.y += 23

    def pair(self, label, value, limit=None):
        width = (limit or self.RIGHT) - self.LEFT
        self.pdf.text(label, self.LEFT + 6, self.y, 8.4, True, INK)
        for line in self.pdf.wrap(value or 'No registrado', width - 122, 8.4):
            self.pdf.text(line, self.LEFT + 116, self.y, 8.4, False, INK)
            self.y += 11.5
        self.y += 2.5

    def bullet(self, value):
        width = self.RIGHT - self.LEFT - 20
        for n, line in enumerate(self.pdf.wrap(value, width, 8.6)):
            self.pdf.text(('•  ' if n == 0 else '   ') + line, self.LEFT + 6, self.y, 8.6, False, INK)
            self.y += 12
        self.y += 1.5

    def amount_box(self, label, cents, side_label, side_note):
        width = self.RIGHT - self.LEFT
        box = 46
        self.fill(self.LEFT, self.y, width, box, (.97, .98, 1))
        self.fill(self.LEFT, self.y, width, .6, (.75, .80, .86))
        self.fill(self.LEFT, self.y + box, width, .6, (.75, .80, .86))
        self.pdf.text(label, self.LEFT + 10, self.y + 9, 7.4, True, GRAY)
        self.pdf.text(usd(cents), self.LEFT + 10, self.y + 21, 19, True, BLUE)
        self.right(side_label, self.y + 11, 9.6, True, INK)
        self.right(side_note, self.y + 27, 7.2, False, GRAY)
        self.y += box + 12

    def totals(self, rows, note):
        for label, cents, bold in rows:
            self.pdf.text(label, self.LEFT + 6, self.y, 9.2 if bold else 8.6, bold, INK)
            self.right(usd(cents), self.y, 10.5 if bold else 8.6, bold, BLUE if bold else INK)
            self.y += 16 if bold else 13
        self.pdf.text(note, self.LEFT + 6, self.y, 7.4, False, GRAY)
        self.y += 20

    def warning(self, text):
        width = self.RIGHT - self.LEFT
        self.fill(self.LEFT, self.y, width, 30, (1, .95, .95))
        self.fill(self.LEFT, self.y, 2.5, 30, RED)
        self.pdf.text(self.pdf.wrap(text, width - 16, 8.2)[0], self.LEFT + 8, self.y + 10, 8.2, True, RED)
        self.y += 38

    def qr(self, url, caption, top):
        size = 64
        self.pdf.qr(url, self.RIGHT - size, top, size)
        for n, line in enumerate(self.pdf.wrap(caption, size + 10, 6.4)):
            self.pdf.text(line, self.RIGHT - size - 4, top + size + 1 + n * 8, 6.4, False, GRAY)

    def notes(self, items):
        width = self.RIGHT - self.LEFT
        self.pdf.line(self.LEFT, self.y, width)
        self.y += 8
        for note in items:
            for line in self.pdf.wrap(note, width - 4, 7.2):
                self.pdf.text(line, self.LEFT + 2, self.y, 7.2, False, GRAY)
                self.y += 9.5
            self.y += 3

    def footer(self, kind):
        company = settings()
        width = self.RIGHT - self.LEFT
        self.pdf.business_signature(kind, self.y + 4, self.H - 44, left=self.LEFT, right=self.LEFT + width)
        self.pdf.text(company['name'] + ' · WhatsApp ' + company['whatsapp'] + ' · ' + company['website'], self.LEFT + 2, self.H - 30, 7, False, GRAY)
        return self.pdf.finish()


def advance_pdf(info, generated):
    a, p = info['advance'], info['proforma']
    s = Sheet(419.53, 595.28, 'Comprobante de anticipo ' + a['code'] + ' · ' + settings()['name'])
    s.header('COMPROBANTE DE ANTICIPO', a['code'], a['paid_at'] or a['created_at'], 'Proforma %s v%s%s' % (p['code'], p['version'], (' · Orden ' + info['order_code']) if info['order_code'] else ''))
    top = s.y
    s.section('Cliente')
    limit = s.RIGHT - 80 if info.get('tracking') else None
    s.pair('Cliente', p['client'], limit)
    if p['identification']:
        s.pair('Identificación', p['identification'], limit)
    s.pair('Concepto', '; '.join(info['concept']) or 'Proforma ' + p['code'], limit)
    if info.get('tracking'):
        s.qr(info['tracking'] + '#' + info['order_code'], 'Consulta segura de la orden', top + 22)
        s.y = max(s.y, top + 22 + 64 + 18)
    s.y += 6
    s.section('Anticipo recibido')
    s.amount_box('ANTICIPO RECIBIDO', a['amount_cents'], info['method'], 'Dólares de los Estados Unidos (USD)')
    if a['reference']:
        s.pair('Referencia', a['reference'])
    s.pair('Registrado por', a['actor'] or 'No consta')
    if a['voided_at']:
        s.warning('ANTICIPO ANULADO el ' + when(a['voided_at']) + '. Motivo: ' + (a['void_reason'] or 'No registrado'))
    s.y += 6
    s.section('Estado de la proforma')
    s.totals((('Valor total acordado', p['total_cents'], False), ('Anticipos a la fecha', info['paid_cents'], False),
              ('Saldo a favor del cliente' if info['credit_cents'] else 'Saldo pendiente', info['credit_cents'] or info['balance_cents'], True)),
             'Calculado el ' + generated.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'))
    s.notes((NOT_TAX, 'El anticipo se descuenta de la factura de la venta, que se emite al confirmarla. El saldo puede cambiar con nuevos anticipos o anulaciones.'))
    return s.footer('pago')


def delivery_pdf(info, generated):
    o = info['order']
    s = Sheet(595.28, 841.89, 'Comprobante de entrega ' + o['code'] + ' · ' + settings()['name'])
    s.header('COMPROBANTE DE ENTREGA DE EQUIPO', o['code'], info['delivered_at'], 'Orden ' + o['code'] + ' · ' + o['status_label'])
    top = s.y
    s.section('Cliente y equipo')
    limit = s.RIGHT - 84 if info['tracking'] else None
    s.pair('Cliente', o['client'], limit)
    if o['identification']:
        s.pair('Identificación', o['identification'], limit)
    s.pair('Equipo', _device(o), limit)
    s.pair('Número de serie', o['serial'] or 'No registrado', limit)
    s.pair('Fecha de entrega', when(info['delivered_at']), limit)
    if info['tracking']:
        s.qr(info['tracking'] + '#' + o['code'], 'Seguimiento seguro de la orden', top + 22)
        s.y = max(s.y, top + 22 + 64 + 18)
    s.y += 6
    s.section('Servicio realizado')
    for item in info['services'][:14] or ['No hay partidas aprobadas registradas en la orden.']:
        s.bullet(item)
    s.y += 4
    if info['findings']:
        s.pair('Diagnóstico', info['findings'][:600])
    if info['recommendations']:
        s.pair('Recomendaciones', info['recommendations'][:500])
    s.y += 6
    m = info['money']
    s.section('Estado de pago')
    s.totals((('Total del servicio', m['budget_cents'], False), ('Pagado', m['paid_cents'], False),
              ('Saldo a favor del cliente' if m['credit_cents'] else 'Saldo pendiente', m['credit_cents'] or m['balance_cents'], True)),
             (('Factura ' + info['invoice'] + ' · ') if info['invoice'] else '') + 'calculado el ' + generated.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'))
    s.section('Garantía')
    if info['warranty']:
        for w in info['warranty']:
            s.pair(w['name'][:24], ('S/N ' + w['serial'] + ' · ' if w['serial'] else '') + 'Garantía de tienda hasta ' + (when(w['store_to']) if w['store_to'] else '—')
                   + ('; del fabricante hasta ' + when(w['maker_to']) if w['maker_to'] else ''))
    else:
        s.pair('Garantía', 'Sin repuestos con garantía registrada en esta orden. La garantía del servicio se rige por las condiciones aceptadas en la recepción.')
    if info['note']:
        s.pair('Observaciones', info['note'][:500])
    s.pair('Entregado por', info['delivered_by'] or 'No consta')
    s.y += 10
    s.section('Constancia de recepción')
    s.pdf.text('Recibí conforme el equipo descrito, en las condiciones indicadas.', s.LEFT + 6, s.y, 8.4, False, INK)
    s.y += 46
    half = (s.RIGHT - s.LEFT - 30) / 2
    for n, label in enumerate(('Firma del cliente o persona autorizada', 'Nombre y número de cédula')):
        x = s.LEFT + n * (half + 30)
        s.pdf.line(x, s.y, half)
        s.pdf.text(label, x, s.y + 4, 7.4, False, GRAY)
    s.y += 26
    s.notes((NOT_TAX,))
    return s.footer('entrega')
