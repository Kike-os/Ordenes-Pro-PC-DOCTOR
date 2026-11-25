"""PC-DOCTOR — Tech Retail Thermal Edition 4.2 · Epson Precision Print: factura electrónica en ticket térmico a 203 dpi.

80 mm (Epson TM-m30 / TM-m30II): página PDF de 80 mm de ancho con el contenido centrado en 68 mm (72 mm imprimibles menos 2 mm de seguridad
por lado). 58 mm: página de 58 mm con 44 mm de contenido (48 mm imprimibles). La página mide exactamente el ancho del papel para que el
controlador no aplique los márgenes físicos dos veces; la altura se calcula con el contenido real (sin alto fijo ni espacio al final, solo
el avance mínimo para el corte).

Solo REPRESENTA un comprobante ya emitido: no emite, no consume secuenciales, no cambia pagos, caja, inventario ni el estado tributario, y no
envía nada. Los importes salen tal cual de la factura registrada; nada se recalcula. Blanco y negro, logotipo original en escala de grises
(sin redibujarlo). Tipografía Helvetica (métricas de Arial): texto 8 pt, secundario 7,5, secciones 8,5, título 10, número 9, total 12,
pie y clave 7,5; interlineado 1,2; negrita solo en encabezados, número, estado e importes principales.

Clave de acceso: completa en texto, en QR y en Code 128 REAL dividido en partes (80 mm: 2 partes de 24 y 25 dígitos; 58 mm: 3 partes), con
módulos de 2 puntos y zona de silencio de 10 módulos. Un solo Code 128 de 49 dígitos solo cabe a 1 punto por módulo (el lector falló en 4 de
cada 10 claves); a 2 puntos mide 85 mm y no cabe en el cabezal de 72 mm. El RIDE A4 conserva su Code 128 único. Nunca imprime credenciales.
Mientras no esté autorizada por el SRI en producción, cada copia lo dice: no es un comprobante válido."""
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import pydyf
import segno

from code128 import widths as barcode_widths

from corporate import settings as corporate
from document_logo import pixels as logo_pixels
from receipt_pdf import WIDTHS
from reception import ECUADOR_TZ

MM = 72 / 25.4
DOT = 72 / 203
SIZES80 = {'body': 8, 'small': 7.5, 'section': 8.5, 'title': 10, 'number': 9, 'total': 12, 'footer': 7.5, 'key': 7.5, 'brand': 10}
SIZES58 = {'body': 7, 'small': 6.5, 'section': 7.5, 'title': 9, 'number': 8, 'total': 11, 'footer': 6.5, 'key': 6.5, 'brand': 9}
FORMATS = {'80': {'page': 80 * MM, 'content': 68 * MM, 'logo_mm': 24, 'sizes': SIZES80, 'parts': (24, 25), 'label': 'Ticket térmico 80 mm'},
           '58': {'page': 58 * MM, 'content': 44 * MM, 'logo_mm': 18, 'sizes': SIZES58, 'parts': (16, 16, 17), 'label': 'Ticket térmico 58 mm'}}
LEAD = 1.2
MODULE_DOTS = 2           # módulo del Code 128: 2 puntos = 0,25 mm (1 punto no es legible de forma fiable)
QUIET = 10                # zona de silencio en módulos, a cada lado
BAR_HEIGHT = 8 * MM
TOP = 1.5 * MM
CUT_FEED = 2 * MM         # avance mínimo bajo el pie; el corte automático lo añade la impresora
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


# Clave de acceso en el ticket: 'qr' (moderno y compacto: un QR con los 49 dígitos y la clave legible debajo) o 'barras' (Code 128
# dividido en partes, formato anterior). Si el contador o el SRI exigieran código de barras en el ticket, se vuelve a 'barras'.
KEY_FORMAT = 'qr'


def key_parts(key, fmt='80'):
    """Partes de la clave de acceso para el Code 128 (en orden). Unidas forman la clave completa."""
    out, i = [], 0
    for n in FORMATS[fmt]['parts']:
        out.append(key[i:i + n])
        i += n
    if i < len(key):
        out[-1] += key[i:]
    return [part for part in out if part]


def render(data, fmt='80', copies=1, calibration=False):
    """PDF del ticket. `copies` páginas idénticas (1 a 5), cada una de altura variable. `calibration` añade marcas de 68 mm (o 44 mm) y de
    los bordes del área imprimible para medir los márgenes reales en papel (solo para la muestra con datos ficticios)."""
    if fmt not in FORMATS:
        raise TicketError('Formato de ticket no válido.', 400)
    copies = max(1, min(5, int(copies or 1)))
    spec = FORMATS[fmt]
    W, inner, S = spec['page'], spec['content'], spec['sizes']
    X0 = (W - inner) / 2
    X1 = X0 + inner
    inv, fiscal, company = data['invoice'], data['fiscal'], corporate()
    pdf = pydyf.PDF()
    pdf.info['Title'] = pydyf.String('FACTURA-' + (inv.get('number') or str(inv['id'])))
    pdf.info['Author'] = pydyf.String(company['name'])
    fonts = {}
    for key, name in (('F1', 'Helvetica'), ('F2', 'Helvetica-Bold'), ('F3', 'Courier')):
        font = pydyf.Dictionary({'Type': '/Font', 'Subtype': '/Type1', 'BaseFont': '/' + name, 'Encoding': '/WinAnsiEncoding'})
        pdf.add_object(font)
        fonts[key] = font.reference
    logo_px = 480 if fmt == '80' else 360
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
    qr_unit = next((n * DOT for n in (5, 4, 3, 2) if (len(qr) + 8) * n * DOT <= inner * .5), 2 * DOT)
    qr_size = (len(qr) + 8) * qr_unit
    parts = key_parts(key, fmt) if KEY_FORMAT == 'barras' else []
    bars = []
    for part in parts:
        widths = barcode_widths(part)
        span = (sum(widths) + 2 * QUIET) * MODULE_DOTS * DOT
        if span > W:
            raise TicketError('La clave de acceso no cabe en Code 128 en este ancho.', 500)
        bars.append((part, widths, span))
    valid = inv['status'] == 'autorizado' and inv['environment'] == '2'

    def compose():
        ops, y = [], TOP

        def text(value, size, font='F1', center=False, gap=1.2, x=None, width=None):
            nonlocal y
            x = X0 if x is None else x
            width = X1 - x if width is None else width
            for line in wrap(value, size, font, width):
                ops.append(('text', line, y, size, font, (W - width_of(line, size, font)) / 2 if center else x))
                y += size * LEAD
            y += gap

        def row(left, right, size, font='F1', rfont=None, gap=.8):
            """Concepto a la izquierda (con salto de línea natural) e importe alineado a la derecha, en cifras tabulares."""
            nonlocal y
            rfont = rfont or font
            rw = width_of(right, size, rfont)
            for n, line in enumerate(wrap(left, size, font, inner - rw - 6)):
                ops.append(('text', line, y, size, font, X0))
                if n == 0:
                    ops.append(('text', right, y, size, rfont, X1 - rw))
                y += size * LEAD
            y += gap

        def columns(values, size, font='F1', gap=.6):
            """Cantidad, precio unitario e importe en columnas fijas alineadas a la derecha."""
            nonlocal y
            edges = (X0 + inner * .22, X0 + inner * .62, X1)
            for value, edge in zip(values, edges):
                ops.append(('text', value, y, size, font, edge - width_of(value, size, font)))
            y += size * LEAD + gap

        def rule(gap=3, heavy=False):
            nonlocal y
            y += 1.5
            ops.append(('rule', y, .8 if heavy else .4))
            y += gap

        def heading(value):
            text(value.upper(), S['section'], 'F2', gap=1)

        # 1 · Encabezado empresarial: logo original centrado (24 mm en 80 mm) y datos fiscales registrados
        logo_w_pt = spec['logo_mm'] * MM
        logo_h_pt = logo_w_pt * logo_h / logo_w
        ops.append(('logo', y, logo_w_pt, logo_h_pt))
        y += logo_h_pt + 2.5
        trade = (fiscal.get('trade_name') or company['name'] or '').strip()
        text(trade, S['brand'], 'F2', center=True, gap=.6)
        if fiscal.get('legal_name') and fiscal['legal_name'].strip().upper() != trade.upper():
            text(fiscal['legal_name'], S['small'], center=True, gap=.4)
        text('RUC ' + (fiscal.get('ruc') or '—'), S['body'], center=True, gap=.8)
        if fiscal.get('head_office_address'):
            text('Matriz: ' + fiscal['head_office_address'], S['small'], center=True, gap=.4)
        branch = (fiscal.get('branch_address') or '').strip()
        if branch and branch != (fiscal.get('head_office_address') or '').strip():
            text('Establecimiento: ' + branch, S['small'], center=True, gap=.4)
        for contact in (company.get('whatsapp', ''), company.get('support_email', '')):
            if contact:
                text(contact, S['small'], center=True, gap=.2)
        tax = ['Obligado a llevar contabilidad: ' + ('SÍ' if str(fiscal.get('keeps_accounts', '')).upper() in ('SI', 'SÍ', '1', 'TRUE') else 'NO')]
        if fiscal.get('regime', '').startswith('rimpe'):
            tax.append('CONTRIBUYENTE ' + fiscal.get('regime_label', '').upper())
        if (fiscal.get('special_taxpayer') or '').strip():
            tax.append('Contribuyente especial: ' + fiscal['special_taxpayer'].strip())
        if (fiscal.get('withholding_agent') or '').strip():
            tax.append('Agente de retención: ' + fiscal['withholding_agent'].strip())
        for line in tax:
            text(line, S['small'], center=True, gap=.2)

        # 2 · Identificación tributaria
        rule(3, heavy=True)
        text('FACTURA ELECTRÓNICA', S['title'], 'F2', center=True, gap=.4)
        text('No. ' + (inv.get('number') or ''), S['number'], 'F2', center=True, gap=2)
        row('Emisión', when(inv.get('emitted_at') or inv.get('issue_date')), S['small'])
        if inv.get('authorized_at'):
            row('Autorización', when(inv['authorized_at']), S['small'])
        row('Ambiente', 'Producción' if inv['environment'] == '2' else 'Pruebas', S['small'])
        row('Tipo de emisión', 'Normal', S['small'])
        row('Estado', STATUS_TEXT.get(inv['status'], inv['status'].upper()), S['small'], rfont='F2')
        if not valid:
            y += 1
            text('DOCUMENTO DE PRUEBA — SIN VALIDEZ TRIBUTARIA' if inv['environment'] == '1' else 'NO AUTORIZADA POR EL SRI — SIN VALIDEZ TRIBUTARIA',
                 S['body'], 'F2', center=True, gap=.6)

        # 3 · Cliente
        rule()
        heading('Cliente')
        text('CONSUMIDOR FINAL' if inv.get('consumer_final') else (inv.get('buyer_name') or '—'), S['body'], gap=.3)
        if not inv.get('consumer_final') and inv.get('buyer_id'):
            text(('RUC ' if len(inv['buyer_id']) == 13 else 'CI ') + inv['buyer_id'], S['small'], gap=.3)
        if (inv.get('buyer_address') or '').strip() and not inv.get('consumer_final'):
            text('Dirección: ' + inv['buyer_address'].strip(), S['small'], gap=.3)
        if data.get('reference'):
            text('%s: %s' % data['reference'], S['small'], gap=.3)

        # 4 · Detalle: descripción completa y debajo cantidad, precio unitario e importe en columnas
        rule()
        heading('Detalle')
        columns(('Cant.', 'P. unit.', 'Importe'), S['small'], 'F2', gap=.8)
        for item in data['items']:
            text(item['description'], S['body'], gap=.2)
            columns((qty(item['quantity']), unit_price(item['unit_price_micros']), money(int(item['base_cents']) + int(item['discount_cents'] or 0))), S['small'])
            if int(item['discount_cents'] or 0):
                row('Descuento', money(-int(item['discount_cents'])), S['small'], gap=.2)
            y += 1.2

        # 5 · Resumen económico (valores del comprobante, sin recalcular)
        rule()
        for rate in sorted(data['groups'], reverse=True):
            label = 'Subtotal IVA %s%%' % ('%g' % (rate / 100)) if rate else 'Subtotal 0%'
            row(label, money(data['groups'][rate]['base']), S['body'])
        row('Subtotal sin impuestos', money(inv['subtotal_cents']), S['body'])
        if int(inv.get('discount_cents') or 0):
            row('Descuentos', money(inv['discount_cents']), S['body'])
        for rate in sorted(data['groups'], reverse=True):
            if rate and data['groups'][rate]['tax']:
                row('IVA %s%%' % ('%g' % (rate / 100)), money(data['groups'][rate]['tax']), S['body'])
        y += 1
        ops.append(('rule', y, .8))
        y += 2.5
        row('TOTAL', money(inv['total_cents']), S['total'], 'F2', gap=1.2)

        # 6 · Pago (formas registradas en la factura; nunca se marca «pagada» sin un pago confirmado)
        if data['payments']:
            rule()
            heading('Forma de pago')
            for p in data['payments']:
                row(p.get('label') or p.get('method') or '—', money(p['amount_cents']), S['body'], gap=.3)

        # 7 · Autorización electrónica: QR con la clave completa (o Code 128 en partes si KEY_FORMAT='barras') y la clave legible
        rule()
        heading('Clave de acceso')
        if KEY_FORMAT == 'qr':
            ops.append(('qr', y, qr_size, qr_unit, qr))
            y += qr_size
        text(' '.join(key[i:i + 10] for i in range(0, len(key), 10)), S['key'], 'F3', center=True, gap=.8)
        if inv.get('authorization_number') and inv['authorization_number'] != key:
            text('Autorización: ' + inv['authorization_number'], S['small'], center=True, gap=.8)
        first = 1
        for n, (part, widths, span) in enumerate(bars, 1):
            ops.append(('barcode', y, widths, span))
            y += BAR_HEIGHT + 1.5
            text('Código de barras %d de %d · dígitos %d a %d' % (n, len(bars), first, first + len(part) - 1), S['small'] - .5, center=True, gap=1.8)
            first += len(part)
        if KEY_FORMAT == 'barras':
            ops.append(('qr', y, qr_size, qr_unit, qr))
            y += qr_size
        text('Escanea el QR para leer la clave de acceso. Verifica la validez en ' + SRI_PORTAL, S['small'], center=True, gap=.6)

        # 8 · Pie corporativo centrado
        rule(2.5)
        text(FOOTER[0], S['footer'], center=True, gap=.2)
        text(FOOTER[1], S['footer'], center=True, gap=.2)
        text(PORTAL, S['footer'], center=True, gap=.2)
        text('Powered by Órdenes Pro', S['footer'] - .5, center=True, gap=0)
        return ops, y + CUT_FEED

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
                stream.move_to(X0, height - op[1])
                stream.line_to(X1, height - op[1])
                stream.stroke()
            elif kind == 'logo':
                _, top, lw, lh = op
                stream.push_state()
                stream.set_matrix(lw, 0, 0, lh, (W - lw) / 2, height - top - lh)
                stream.draw_x_object('Logo')
                stream.pop_state()
            elif kind == 'barcode':
                _, top, widths, span = op
                module = MODULE_DOTS * DOT
                left = snap((W - span) / 2) + QUIET * module
                for i, w in enumerate(widths):
                    if i % 2 == 0:
                        stream.rectangle(left, height - top - BAR_HEIGHT, w * module, BAR_HEIGHT)
                    left += w * module
                stream.fill()
            elif kind == 'qr':
                _, top, size, unit, cells = op
                left = snap((W - size) / 2)
                for r, values in enumerate(cells):
                    for col, dark in enumerate(values):
                        if dark:
                            stream.rectangle(left + (col + 4) * unit, height - top - (r + 5) * unit, unit, unit)
                stream.fill()
        if calibration:
            # Marcas de la muestra de calibración: bordes del contenido (68/44 mm) y del área imprimible (72/48 mm), arriba y abajo.
            printable = (72 if fmt == '80' else 48) * MM
            stream.set_line_width(.3)
            for xs, length in (((X0, X1), 4 * MM), (((W - printable) / 2, (W + printable) / 2), 2 * MM)):
                for x in xs:
                    for top in (0, height - length):
                        stream.move_to(x, height - top)
                        stream.line_to(x, height - top - length)
            stream.stroke()
        page = pydyf.Dictionary({'Type': '/Page', 'Parent': pdf.pages.reference, 'MediaBox': pydyf.Array([0, 0, W, height]), 'Resources': resources,
                                 'Contents': stream.reference})
        pdf.add_page(page)
    out = io.BytesIO()
    pdf.write(out)
    return out.getvalue()


def calibration_data():
    """Datos FICTICIOS para la muestra de calibración: no corresponden a ninguna factura ni consumen secuenciales."""
    import random
    rnd = random.Random(4242)
    key = ''.join(rnd.choice('0123456789') for _ in range(49))
    items = [{'description': 'Mantenimiento preventivo de laptop (muestra de calibración, dato ficticio)', 'quantity': 1, 'unit_price_micros': 25_000_000,
              'base_cents': 2500, 'discount_cents': 0, 'tax_rate_bp': 1500, 'tax_cents': 375},
             {'description': 'Cambio de pasta térmica de alto rendimiento con limpieza de ventilador y revisión de temperaturas', 'quantity': 2,
              'unit_price_micros': 7_500_000, 'base_cents': 1350, 'discount_cents': 150, 'tax_rate_bp': 1500, 'tax_cents': 203}]
    inv = {'id': 0, 'number': '000-000-000000000', 'access_key': key, 'status': 'borrador', 'environment': '1', 'issue_date': '2026-01-01',
           'consumer_final': False, 'buyer_name': 'CLIENTE DE MUESTRA CON UN NOMBRE MUY LARGO PARA PROBAR EL SALTO DE LÍNEA', 'buyer_id': '9999999999',
           'buyer_address': 'Dirección ficticia de prueba', 'subtotal_cents': 3850, 'discount_cents': 150, 'tax_cents': 578, 'total_cents': 4428}
    fiscal = {'trade_name': 'PC-DOCTOR', 'legal_name': 'MUESTRA DE CALIBRACIÓN', 'ruc': '0000000000000', 'head_office_address': 'Dirección de muestra',
              'keeps_accounts': 'NO', 'regime': ''}
    return {'invoice': inv, 'fiscal': fiscal, 'items': items, 'payments': [{'label': 'Efectivo (muestra)', 'amount_cents': 4428}],
            'groups': {1500: {'base': 3850, 'tax': 578}}, 'reference': ('Muestra', 'SIN VALIDEZ')}
