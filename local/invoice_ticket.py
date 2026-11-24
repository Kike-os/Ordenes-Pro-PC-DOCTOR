"""PC-DOCTOR — Tech Retail Invoice 4.0: factura electrónica en ticket térmico de 80 mm (72 mm útiles) o 58 mm (48 mm útiles) a 203 dpi.

Solo REPRESENTA un comprobante ya emitido: no emite, no consume secuenciales, no cambia pagos, caja, inventario ni el estado tributario, y no
envía nada. Los importes salen tal cual de la factura registrada (partidas, impuestos y formas de pago); nada se recalcula ni se redondea
de otra forma. Blanco y negro, logotipo original convertido a escala de grises (sin redibujarlo), una página de altura variable por copia.
La clave de acceso va completa en texto y en un QR (en 72 o 48 mm un Code 128 de 49 dígitos solo cabe a un punto por módulo y el lector no lo
lee de forma fiable: falló en 4 de cada 10 claves; por eso no se imprime. El RIDE A4 conserva su Code 128). Nunca imprime credenciales, contraseñas ni
claves de activación. Mientras no esté autorizada por el SRI en producción, cada copia lo dice: no es un comprobante válido."""
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import pydyf
import segno

from corporate import settings as corporate
from document_logo import pixels as logo_pixels
from receipt_pdf import WIDTHS
from reception import ECUADOR_TZ

MM = 72 / 25.4
DOT = 72 / 203
FORMATS = {'80': {'width': 72 * MM, 'logo_mm': 20, 'base': 8.2, 'label': 'Ticket térmico 80 mm'},
           '58': {'width': 48 * MM, 'logo_mm': 15, 'base': 7.2, 'label': 'Ticket térmico 58 mm'}}
MARGIN = 1 * MM
BAR_HEIGHT = 10 * MM
STATUS_TEXT = {'autorizado': 'AUTORIZADA POR EL SRI', 'pendiente': 'PENDIENTE DE AUTORIZACIÓN', 'enviado': 'ENVIADA AL SRI · EN ESPERA',
               'rechazado': 'RECHAZADA POR EL SRI', 'borrador': 'BORRADOR'}
FOOTER = ('Gracias por confiar en PC-DOCTOR.', 'Tecnología que inspira confianza.')
PORTAL = 'https://ordenes-pro.ecuadorpcdoctor.com'
SRI_PORTAL = 'srienlinea.sri.gob.ec'


class TicketError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def money(cents):
    cents = int(cents or 0)
    sign = '-' if cents < 0 else ''
    whole, frac = divmod(abs(cents), 100)
    return '%s$%s,%02d' % (sign, format(whole, ',d').replace(',', '.'), frac)


def unit_price(micros):
    whole, frac = divmod(int(micros or 0), 1_000_000)
    digits = ('%06d' % frac).rstrip('0')
    return '%s,%s' % (format(whole, ',d').replace(',', '.'), (digits + '00')[:max(2, len(digits))])


def qty(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return ('%d' % number) if number == int(number) else ('%.2f' % number).replace('.', ',')


def when(value):
    if not value:
        return ''
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if moment.tzinfo:
            moment = moment.astimezone(ECUADOR_TZ)
        return moment.strftime('%d/%m/%Y %H:%M') if ('T' in str(value) or ' ' in str(value).strip()) else moment.strftime('%d/%m/%Y')
    except ValueError:
        return str(value)[:19]


def data_for(c, invoice_id):
    """Datos del comprobante tal como están registrados (sin recalcular). Exige que la factura esté emitida (tiene clave de acceso)."""
    import invoicing
    detail = invoicing.detail(c, invoice_id)
    inv, fiscal = detail['invoice'], detail['settings']
    if not inv.get('access_key'):
        raise TicketError('La factura todavía no se emitió: no tiene número ni clave de acceso para imprimir.')
    groups = {}
    for item in detail['items']:
        rate = int(item['tax_rate_bp'] or 0)
        g = groups.setdefault(rate, {'base': 0, 'tax': 0})
        g['base'] += int(item['base_cents'] or 0)
        g['tax'] += int(item['tax_cents'] or 0)
    reference = ''
    if inv.get('order_id'):
        row = c.execute('SELECT code FROM orders WHERE id=?', (inv['order_id'],)).fetchone()
        reference = ('Orden de servicio', row['code']) if row else ''
    elif inv.get('source_kind') == 'proforma':
        row = c.execute('SELECT code FROM proformas WHERE id=?', (inv['source_id'],)).fetchone()
        reference = ('Proforma', row['code']) if row else ''
    elif inv.get('license_sale_id'):
        row = c.execute('SELECT code FROM license_sales WHERE id=?', (inv['license_sale_id'],)).fetchone()
        reference = ('Venta de licencias', row['code']) if row else ''
    return {'invoice': inv, 'fiscal': fiscal, 'items': detail['items'], 'payments': detail['payments'], 'groups': groups, 'reference': reference}


def render(data, fmt='80', copies=1):
    """PDF del ticket. `copies` páginas idénticas (1 a 5), cada una de altura variable."""
    if fmt not in FORMATS:
        raise TicketError('Formato de ticket no válido.', 400)
    copies = max(1, min(5, int(copies or 1)))
    spec = FORMATS[fmt]
    W, base = spec['width'], spec['base']
    inner = W - 2 * MARGIN
    inv, fiscal, company = data['invoice'], data['fiscal'], corporate()
    pdf = pydyf.PDF()
    pdf.info['Title'] = pydyf.String('FACTURA-' + (inv.get('number') or str(inv['id'])))
    pdf.info['Author'] = pydyf.String(company['name'])
    fonts = {}
    for key, name in (('F1', 'Helvetica'), ('F2', 'Helvetica-Bold'), ('F3', 'Courier')):
        font = pydyf.Dictionary({'Type': '/Font', 'Subtype': '/Type1', 'BaseFont': '/' + name, 'Encoding': '/WinAnsiEncoding'})
        pdf.add_object(font)
        fonts[key] = font.reference
    logo_px = 416 if fmt == '80' else 320
    logo_w, logo_h, rgb, alpha, _ = logo_pixels(logo_px)
    gray = bytes(min(255, round((.2126 * rgb[i * 3] + .7152 * rgb[i * 3 + 1] + .0722 * rgb[i * 3 + 2]) * a / 255 + 255 - a)) for i, a in enumerate(alpha))
    logo = pydyf.Stream([gray], extra={'Type': '/XObject', 'Subtype': '/Image', 'Width': logo_w, 'Height': logo_h, 'ColorSpace': '/DeviceGray',
                                       'BitsPerComponent': 8, 'Interpolate': 'true'}, compress=True)
    pdf.add_object(logo)
    resources = pydyf.Dictionary({'Font': pydyf.Dictionary(fonts), 'XObject': pydyf.Dictionary({'Logo': logo.reference})})

    def width_of(text, size, font='F1'):
        if font == 'F3':
            return len(text) * size * .6
        return sum(WIDTHS.get(ch, 556) for ch in text) * size / 1000 * (1.06 if font == 'F2' else 1)

    def wrap(text, size, font, width):
        lines = []
        for paragraph in str(text).splitlines() or ['']:
            current = ''
            for word in paragraph.split(' '):
                trial = (current + ' ' + word).strip() if current else word
                if current and width_of(trial, size, font) > width:
                    lines.append(current)
                    current = word
                else:
                    current = trial
                while width_of(current, size, font) > width:
                    cut = len(current)
                    while cut > 1 and width_of(current[:cut], size, font) > width:
                        cut -= 1
                    lines.append(current[:cut])
                    current = current[cut:]
            lines.append(current)
        return lines

    def snap(value):
        return round(value / DOT) * DOT

    key = inv['access_key']
    qr = list(segno.make_qr(key, error='m').matrix)
    qr_unit = next((n * DOT for n in (4, 3, 2) if (len(qr) + 8) * n * DOT <= inner * .7), 2 * DOT)
    qr_size = (len(qr) + 8) * qr_unit
    valid = inv['status'] == 'autorizado' and inv['environment'] == '2'

    def compose():
        ops, y = [], 4

        def text(value, size=None, font='F1', center=False, gap=1.5, lead=1.22, x=None, width=None):
            nonlocal y
            size = size or base
            x = MARGIN if x is None else x
            width = inner - (x - MARGIN) if width is None else width
            for line in wrap(value, size, font, width):
                ops.append(('text', line, y, size, font, (W - width_of(line, size, font)) / 2 if center else x))
                y += size * lead
            y += gap

        def row(left, right, size=None, font='F1', rfont=None, gap=1.2):
            """Etiqueta a la izquierda e importe alineado a la derecha (números tabulares de Helvetica)."""
            nonlocal y
            size = size or base
            rfont = rfont or font
            rw = width_of(right, size, rfont)
            lines = wrap(left, size, font, inner - rw - 6)
            for n, line in enumerate(lines):
                ops.append(('text', line, y, size, font, MARGIN))
                if n == 0:
                    ops.append(('text', right, y, size, rfont, W - MARGIN - rw))
                y += size * 1.22
            y += gap

        def rule(gap=4, heavy=False):
            nonlocal y
            y += 1
            ops.append(('rule', y, .8 if heavy else .4))
            y += gap

        def heading(value):
            text(value.upper(), base - .6, 'F2', gap=1.2)

        # 1 · Encabezado empresarial (logo original, nombre comercial y datos fiscales registrados)
        logo_w_pt = spec['logo_mm'] * MM
        logo_h_pt = logo_w_pt * logo_h / logo_w
        ops.append(('logo', y, logo_w_pt, logo_h_pt))
        y += logo_h_pt + 4
        trade = (fiscal.get('trade_name') or company['name'] or '').strip()
        text(trade, base + 2.6, 'F2', center=True, gap=1)
        if fiscal.get('legal_name') and fiscal['legal_name'].strip().upper() != trade.upper():
            text(fiscal['legal_name'], base - .4, 'F2', center=True, gap=1)
        text('RUC ' + (fiscal.get('ruc') or '—'), base, 'F2', center=True, gap=1.5)
        if fiscal.get('head_office_address'):
            text('Matriz: ' + fiscal['head_office_address'], base - 1, center=True, gap=.6)
        branch = (fiscal.get('branch_address') or '').strip()
        if branch and branch != (fiscal.get('head_office_address') or '').strip():
            text('Establecimiento: ' + branch, base - 1, center=True, gap=.6)
        contact = ' · '.join(x for x in (company.get('whatsapp', ''), company.get('support_email', '')) if x)
        if contact:
            text(contact, base - 1.4, center=True, gap=.8)
        tax = ['Obligado a llevar contabilidad: ' + ('SÍ' if str(fiscal.get('keeps_accounts', '')).upper() in ('SI', 'SÍ', '1', 'TRUE') else 'NO')]
        if fiscal.get('regime', '').startswith('rimpe'):
            tax.append('CONTRIBUYENTE ' + fiscal.get('regime_label', '').upper())
        if (fiscal.get('special_taxpayer') or '').strip():
            tax.append('Contribuyente especial: ' + fiscal['special_taxpayer'].strip())
        if (fiscal.get('withholding_agent') or '').strip():
            tax.append('Agente de retención: ' + fiscal['withholding_agent'].strip())
        for line in tax:
            text(line, base - 1.6, center=True, gap=.4)

        # 2 · Identificación tributaria
        rule(5, heavy=True)
        text('FACTURA ELECTRÓNICA', base + 2, 'F2', center=True, gap=1)
        text('No. ' + (inv.get('number') or ''), base + 1.4, 'F2', center=True, gap=3)
        row('Emisión', when(inv.get('emitted_at') or inv.get('issue_date')))
        if inv.get('authorized_at'):
            row('Autorización', when(inv['authorized_at']))
        row('Ambiente', 'Producción' if inv['environment'] == '2' else 'Pruebas')
        row('Tipo de emisión', 'Normal')
        row('Estado', STATUS_TEXT.get(inv['status'], inv['status'].upper()), font='F1', rfont='F2')
        if not valid:
            y += 1
            text('DOCUMENTO DE PRUEBA — SIN VALIDEZ TRIBUTARIA' if inv['environment'] == '1' else 'NO AUTORIZADA POR EL SRI — SIN VALIDEZ TRIBUTARIA',
                 base - .4, 'F2', center=True, gap=1)

        # 3 · Cliente
        rule()
        heading('Cliente')
        text('CONSUMIDOR FINAL' if inv.get('consumer_final') else (inv.get('buyer_name') or '—'), base, 'F2', gap=.6)
        if not inv.get('consumer_final') and inv.get('buyer_id'):
            text(('RUC ' if len(inv['buyer_id']) == 13 else 'CI ') + inv['buyer_id'], base - .6, gap=.6)
        if (inv.get('buyer_address') or '').strip() and not inv.get('consumer_final'):
            text('Dirección: ' + inv['buyer_address'].strip(), base - 1, gap=.6)
        if data.get('reference'):
            text('%s: %s' % data['reference'], base - 1, gap=.6)

        # 4 · Productos y servicios
        rule()
        heading('Detalle')
        for item in data['items']:
            text(item['description'], base - .2, 'F2', gap=.4)
            row('%s × %s' % (qty(item['quantity']), unit_price(item['unit_price_micros'])), money(int(item['base_cents']) + int(item['discount_cents'] or 0)), base - .8, gap=.2)
            if int(item['discount_cents'] or 0):
                row('Descuento', money(-int(item['discount_cents'])), base - .8, gap=.2)
            y += 1.6

        # 6 · Resumen económico (los valores del comprobante, sin recalcular)
        rule()
        for rate in sorted(data['groups'], reverse=True):
            label = 'Subtotal IVA %s%%' % ('%g' % (rate / 100)) if rate else 'Subtotal 0%'
            row(label, money(data['groups'][rate]['base']))
        row('Subtotal sin impuestos', money(inv['subtotal_cents']))
        if int(inv.get('discount_cents') or 0):
            row('Descuentos', money(inv['discount_cents']))
        for rate in sorted(data['groups'], reverse=True):
            if rate and data['groups'][rate]['tax']:
                row('IVA %s%%' % ('%g' % (rate / 100)), money(data['groups'][rate]['tax']))
        y += 1
        ops.append(('rule', y, .8))
        y += 3
        row('TOTAL', money(inv['total_cents']), base + 4, 'F2', gap=2)

        # 7 · Pago (formas registradas en la factura; nunca se marca «pagada» sin un pago confirmado)
        if data['payments']:
            rule()
            heading('Forma de pago')
            for p in data['payments']:
                row(p.get('label') or p.get('method') or '—', money(p['amount_cents']), base - .6, gap=.4)

        # 8 · Autorización electrónica
        rule()
        heading('Clave de acceso')
        groups = ' '.join(key[i:i + 10] for i in range(0, len(key), 10))
        text(groups, base - (1.4 if W > 50 * MM else 1.9), 'F3', center=True, gap=1)
        if inv.get('authorization_number') and inv['authorization_number'] != key:
            text('Autorización: ' + inv['authorization_number'], base - 1.6, center=True, gap=1)
        y += 1
        ops.append(('qr', y, qr_size, qr_unit, qr))
        y += qr_size + 1
        text('Verifica la validez en ' + SRI_PORTAL, base - 1.6, center=True, gap=1)

        # 9 · Pie corporativo
        rule()
        text(FOOTER[0], base - .2, 'F2', center=True, gap=.4)
        text(FOOTER[1], base - 1, center=True, gap=1)
        text(PORTAL, base - 1.6, center=True, gap=.4)
        text('Powered by Órdenes Pro', base - 2, center=True, gap=0)
        return ops, y + 8

    for _ in range(copies):
        ops, height = compose()
        stream = pydyf.Stream(compress=True)
        pdf.add_object(stream)
        stream.set_color_rgb(0, 0, 0)
        for op in ops:
            kind = op[0]
            if kind == 'text':
                _, value, top, size, font, x = op
                stream.begin_text()
                stream.set_font_size(font, size)
                stream.set_text_matrix(1, 0, 0, 1, x, height - top - size)
                stream.show_text_string(value.encode('cp1252', 'replace'))
                stream.end_text()
            elif kind == 'rule':
                stream.set_line_width(op[2])
                stream.move_to(MARGIN, height - op[1])
                stream.line_to(W - MARGIN, height - op[1])
                stream.stroke()
            elif kind == 'logo':
                _, top, lw, lh = op
                stream.push_state()
                stream.set_matrix(lw, 0, 0, lh, (W - lw) / 2, height - top - lh)
                stream.draw_x_object('Logo')
                stream.pop_state()
            elif kind == 'barcode':
                _, top, widths, span = op
                left = snap((W - span) / 2) + 10 * DOT
                for i, w in enumerate(widths):
                    if i % 2 == 0:
                        stream.rectangle(left, height - top - BAR_HEIGHT, w * DOT, BAR_HEIGHT)
                    left += w * DOT
                stream.fill()
            elif kind == 'qr':
                _, top, size, unit, cells = op
                left = snap((W - size) / 2)
                for r, values in enumerate(cells):
                    for col, dark in enumerate(values):
                        if dark:
                            stream.rectangle(left + (col + 4) * unit, height - top - (r + 5) * unit, unit, unit)
                stream.fill()
        page = pydyf.Dictionary({'Type': '/Page', 'Parent': pdf.pages.reference, 'MediaBox': pydyf.Array([0, 0, W, height]), 'Resources': resources,
                                 'Contents': stream.reference})
        pdf.add_page(page)
    out = io.BytesIO()
    pdf.write(out)
    return out.getvalue()
