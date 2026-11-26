"""ADI 3.0 · fase 4: estado de cuenta del cliente en PDF A4 y ticket térmico de 80 mm (Premium Billing Center).

Documento INFORMATIVO: no es una factura ni un comprobante tributario y así lo dice. Valores tomados de la cartera consolidada
(collections_center.portfolio), es decir, de los mismos cargos y pagos de cada orden; nada se recalcula aparte. Intereses autorizados:
siempre $0,00 (no se aplican intereses). Las simulaciones solo aparecen en la versión INTERNA, separadas y marcadas «SIMULACIÓN — no
exigible», y nunca suman al saldo. Logotipo original en escala de grises, sin redibujarlo."""
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import pydyf

from corporate import settings as corporate
from document_logo import pixels as logo_pixels
from receipt_pdf import WIDTHS

MM = 72 / 25.4
FORMATS = {'a4': {'page': 595.28, 'content': 595.28 - 2 * 42, 'height': 841.89, 'logo': 34 * MM, 'base': 9.5},
           '80': {'page': 80 * MM, 'content': 68 * MM, 'height': None, 'logo': 24 * MM, 'base': 8}}
PORTAL = 'https://ordenes-pro.ecuadorpcdoctor.com'


class StatementError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def data_for(c, client_id, now, internal=False):
    import collections_center as cc
    client = c.execute('SELECT id,name,COALESCE(identification,\'\') identification FROM clients WHERE id=?', (client_id,)).fetchone()
    if not client:
        raise StatementError('Cliente no encontrado.', 404)
    port = cc.portfolio(c, now, client_id=client_id)
    items = [it for it in port['items'] if it['balance_cents'] > 0 or it['credit_cents'] > 0]
    pays = {}
    for r in c.execute("SELECT COALESCE(o.group_id,o.id) main,COALESCE(SUM(CASE WHEN p.kind='pago' THEN p.amount_cents ELSE -p.amount_cents END),0) cents FROM order_payments p "
                       "JOIN orders o ON o.id=p.order_id JOIN devices d ON d.id=o.device_id WHERE d.client_id=? AND p.voided_at IS NULL GROUP BY COALESCE(o.group_id,o.id)", (client_id,)):
        pays[r['main']] = r['cents']
    rows = [{'code': it['code'], 'device': it['devices'], 'charges': it['charges_cents'], 'paid': pays.get(it['main_id'], 0), 'balance': it['balance_cents'],
             'credit': it['credit_cents'], 'due': it['due_date'], 'basis': it['due_basis'] or 'Se paga al retirar', 'days': it['days_overdue'],
             'pending': it['pending_cents'], 'state': it['state_label'], 'simulated': it['simulated_interest_cents'] if internal else None, 'invoices': ', '.join(i['number'] for i in it['invoices'])} for it in items]
    return {'client': dict(client), 'cutoff': now, 'rows': rows, 'balance': sum(r['balance'] for r in rows), 'credit': sum(r['credit'] for r in rows),
            'pending': sum(r['pending'] for r in rows), 'grace': port['policy']['grace_days'], 'internal': internal,
            'simulated': sum(r['simulated'] or 0 for r in rows) if internal else None}


def _money(cents):
    import collections_center as cc
    return cc.usd(cents)


def render(data, fmt='a4'):
    if fmt not in FORMATS:
        raise StatementError('Formato no válido.')
    spec = FORMATS[fmt]
    W, inner, base = spec['page'], spec['content'], spec['base']
    X0 = (W - inner) / 2
    X1 = X0 + inner
    company = corporate()
    pdf = pydyf.PDF()
    pdf.info['Title'] = pydyf.String('ESTADO-DE-CUENTA')
    fonts = {}
    for key, name in (('F1', 'Helvetica'), ('F2', 'Helvetica-Bold')):
        font = pydyf.Dictionary({'Type': '/Font', 'Subtype': '/Type1', 'BaseFont': '/' + name, 'Encoding': '/WinAnsiEncoding'})
        pdf.add_object(font)
        fonts[key] = font.reference
    lw, lh, rgb, alpha, _ = logo_pixels(400)
    gray = bytes(min(255, round((.2126 * rgb[i * 3] + .7152 * rgb[i * 3 + 1] + .0722 * rgb[i * 3 + 2]) * a / 255 + 255 - a)) for i, a in enumerate(alpha))
    logo = pydyf.Stream([gray], extra={'Type': '/XObject', 'Subtype': '/Image', 'Width': lw, 'Height': lh, 'ColorSpace': '/DeviceGray', 'BitsPerComponent': 8}, compress=True)
    pdf.add_object(logo)
    resources = pydyf.Dictionary({'Font': pydyf.Dictionary(fonts), 'XObject': pydyf.Dictionary({'Logo': logo.reference})})

    def width_of(text, size, font='F1'):
        return sum(WIDTHS.get(ch, 556) for ch in text) * size / 1000 * (1.06 if font == 'F2' else 1)

    def wrap(text, size, font, width):
        lines, cur = [], ''
        for word in str(text).split(' '):
            trial = (cur + ' ' + word).strip()
            if cur and width_of(trial, size, font) > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
        return lines

    ops = []
    y = [14 if fmt == 'a4' else 4]

    def text(value, size=base, font='F1', center=False, gap=1.2, x=None, width=None):
        x = X0 if x is None else x
        width = X1 - x if width is None else width
        for line in wrap(value, size, font, width):
            ops.append(('t', line, y[0], size, font, (W - width_of(line, size, font)) / 2 if center else x))
            y[0] += size * 1.2
        y[0] += gap

    def row(left, right, size=base, font='F1'):
        rw = width_of(right, size, font)
        lw = width_of(left, size, font)
        if rw > inner - lw - 8:
            # Valor largo (p. ej., un nombre de cliente extenso): se reparte en varias líneas alineadas a la derecha, sin invadir la etiqueta.
            room = max(inner - lw - 8, inner * .5)
            ops.append(('t', left, y[0], size, font, X0))
            for line in wrap(right, size, font, room):
                ops.append(('t', line, y[0], size, font, X1 - width_of(line, size, font)))
                y[0] += size * 1.2
            y[0] += .8
            return
        for n, line in enumerate(wrap(left, size, font, inner - rw - 8)):
            ops.append(('t', line, y[0], size, font, X0))
            if n == 0:
                ops.append(('t', right, y[0], size, font, X1 - rw))
            y[0] += size * 1.2
        y[0] += .8

    def rule(heavy=False):
        y[0] += 2
        ops.append(('r', y[0], .8 if heavy else .4))
        y[0] += 4

    lwp = spec['logo']
    lhp = lwp * lh / lw
    ops.append(('l', y[0], lwp, lhp))
    y[0] += lhp + 4
    text(company['name'], base + 2.5, 'F2', center=True, gap=.5)
    for line in (company.get('whatsapp', ''), company.get('support_email', '')):
        if line:
            text(line, base - .5, center=True, gap=.2)
    rule(True)
    text('ESTADO DE CUENTA', base + 3, 'F2', center=True, gap=.4)
    text('Documento informativo: no es una factura ni un comprobante tributario.', base - .5, center=True, gap=1)
    if data['internal']:
        text('VERSIÓN INTERNA CON SIMULACIÓN — NO ENTREGAR AL CLIENTE', base, 'F2', center=True, gap=1)
    row('Fecha de corte', data['cutoff'].strftime('%d/%m/%Y %H:%M'))
    row('Cliente', data['client']['name'])
    if data['client']['identification']:
        row('Identificación', data['client']['identification'])
    rule()
    if not data['rows']:
        text('El cliente no registra saldos pendientes a la fecha de corte.', base, center=True, gap=2)
    for r in data['rows']:
        text('Orden %s · %s' % (r['code'], r['device']), base, 'F2', gap=.4)
        if r['invoices']:
            text('Factura(s): ' + r['invoices'], base - .8, gap=.4)
        row('Capital original (cargos)', _money(r['charges']), base - .5)
        row('Pagos registrados', _money(r['paid']), base - .5)
        if r['pending']:
            row('Transferencias por conciliar (no descontadas)', _money(r['pending']), base - .5)
        row('Saldo pendiente' if not r['credit'] else 'Saldo a favor del cliente', _money(r['balance'] or r['credit']), base - .2, 'F2')
        row('Estado', r['state'], base - .8)
        row('Exigible desde', ('%s · %s' % (datetime.strptime(r['due'], '%Y-%m-%d').strftime('%d/%m/%Y'), r['basis'])) if r['due'] else r['basis'], base - .8)
        row('Días de atraso', str(r['days']) if r['days'] is not None else 'No aplica', base - .8)
        if data['internal'] and r['simulated'] is not None:
            row('SIMULACIÓN de intereses (no exigible, no suma al saldo)', _money(r['simulated']), base - .8)
        y[0] += 3
    rule(True)
    row('Período de gracia sin intereses', '%d días' % data['grace'])
    row('Tasa aplicada', 'Ninguna')
    row('Intereses autorizados', '$0,00')
    row('TOTAL ACTUALIZADO', _money(data['balance']), base + 3, 'F2')
    if data['credit']:
        row('Saldo a favor del cliente', _money(data['credit']))
    if data['internal'] and data['simulated'] is not None:
        row('Intereses simulados (referencia interna)', _money(data['simulated']), base - .5)
    rule()
    text('No se aplican intereses ni recargos. Si ya realizó un pago o una transferencia, puede estar en proceso de conciliación: escríbanos y lo '
         'verificamos. Para consultas: ' + ' · '.join(x for x in (company.get('whatsapp', ''), company.get('support_email', '')) if x) + ' · ' + PORTAL, base - 1, center=True, gap=2)
    text('Gracias por confiar en PC-DOCTOR.', base - .5, center=True, gap=0)
    height = spec['height'] or y[0] + 2 * MM
    pages, current, offset = [], [], 0
    limit = (spec['height'] - 40) if spec['height'] else None
    for op in ops:
        top = op[2] if op[0] == 't' else op[1]
        if limit and top - offset > limit:
            pages.append((current, offset))
            current, offset = [], top - 30
        current.append(op)
    pages.append((current, offset))
    for chunk, off in pages:
        stream = pydyf.Stream(compress=True)
        pdf.add_object(stream)
        stream.set_color_rgb(0, 0, 0)
        for op in chunk:
            if op[0] == 't':
                _, value, top, size, font, x = op
                stream.begin_text()
                stream.set_font_size(font, size)
                stream.set_text_matrix(1, 0, 0, 1, x, height - (top - off) - size)
                stream.show_text_string(value.encode('cp1252', 'replace'))
                stream.end_text()
            elif op[0] == 'r':
                stream.set_line_width(op[2])
                stream.move_to(X0, height - (op[1] - off))
                stream.line_to(X1, height - (op[1] - off))
                stream.stroke()
            else:
                _, top, w, h = op
                stream.push_state()
                stream.set_matrix(w, 0, 0, h, (W - w) / 2, height - (top - off) - h)
                stream.draw_x_object('Logo')
                stream.pop_state()
        pdf.add_page(pydyf.Dictionary({'Type': '/Page', 'Parent': pdf.pages.reference, 'MediaBox': pydyf.Array([0, 0, W, height]), 'Resources': resources,
                                       'Contents': stream.reference}))
    out = io.BytesIO()
    pdf.write(out)
    return out.getvalue()
