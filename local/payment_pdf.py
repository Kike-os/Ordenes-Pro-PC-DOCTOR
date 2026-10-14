"""Recibo de un pago, un abono o una devolución registrados en una orden (A5). Refleja el movimiento tal como quedó guardado y el
estado de la cuenta al emitirlo. No es una factura ni un comprobante tributario, y así lo dice el propio documento."""
from datetime import datetime

from corporate import settings
from document_canvas import Canvas, BLUE, GRAY, INK
from reception import ECUADOR_TZ

W, H = 419.53, 595.28
LEFT, RIGHT = 30, W - 30
ROSE = (0xAA/255, 0x47/255, 0x7C/255)
RED = (.70, .16, .20)


def usd(cents):
    return '$' + format(cents // 100, ',').replace(',', '.') + ',%02d' % (cents % 100)


def number(payment):
    """Número del recibo: consecutivo del movimiento en el sistema; no se reutiliza ni cambia."""
    return 'R-%06d' % payment['id']


def _date(value):
    try:
        return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return 'No registrada'


def render(order, payment, account, methods, generated):
    """`order`: código, cliente, identificación y equipo. `payment`: el movimiento. `account`: resumen de equipment.summary al emitir,
    con `scope` («del equipo E02», «de la orden»…). `methods`: etiquetas de las formas de pago."""
    company = settings()
    refund = payment['kind'] == 'devolucion'
    title = 'COMPROBANTE DE DEVOLUCIÓN' if refund else 'RECIBO DE PAGO'
    pdf = Canvas(W, H, title.capitalize() + ' ' + number(payment) + ' · ' + order['code'] + ' · ' + company['name'])
    pdf.page()
    width = RIGHT - LEFT

    def fill(x, top, w, h, color):
        pdf.stream.set_color_rgb(*color)
        pdf.stream.rectangle(x, pdf.h - top - h, w, h)
        pdf.stream.fill()

    def right(value, top, size, bold=False, color=INK):
        from document_canvas import WIDTHS
        span = sum(WIDTHS.get(ch, 556) for ch in str(value)) * size / 1000 * (1.06 if bold else 1)
        pdf.text(value, RIGHT - span, top, size, bold, color)

    fill(0, 0, W, 4, BLUE)
    pdf.logo(LEFT, 20, 46)
    pdf.text(company['name'], LEFT + 56, 22, 14, True, BLUE)
    pdf.text(company['specialty'].upper(), LEFT + 56, 41, 6.6, True, GRAY)
    right(number(payment), 22, 12, True, BLUE)
    right(_date(payment['created_at']), 39, 7.6, False, GRAY)
    pdf.line(LEFT, 70, width)
    pdf.text(title, LEFT, 82, 13, True, BLUE)
    pdf.text('Orden ' + order['code'] + (' · pago general de la orden' if payment.get('scope') == 'general' else ''), LEFT, 100, 8.4, False, GRAY)
    y = 122

    def section(label):
        nonlocal y
        fill(LEFT, y, width, 16, (.93, .95, .98))
        fill(LEFT, y, 2.5, 16, ROSE)
        pdf.text(label.upper(), LEFT + 8, y + 4.5, 7.8, True, BLUE)
        y += 23

    def pair(label, value):
        nonlocal y
        pdf.text(label, LEFT + 6, y, 8.4, True, INK)
        for line in pdf.wrap(value or 'No registrado', width - 122, 8.4):
            pdf.text(line, LEFT + 116, y, 8.4, False, INK)
            y += 11.5
        y += 2.5

    section('Cliente y equipo')
    pair('Cliente', order['client'])
    if order.get('identification'):
        pair('Identificación', order['identification'])
    pair('Equipo', ' '.join(part for part in (order.get('brand'), order.get('model')) if part) or 'Equipo sin especificar')
    if order.get('serial'):
        pair('Serie', order['serial'])
    y += 6

    section('Devolución' if refund else 'Pago recibido')
    box = 46
    fill(LEFT, y, width, box, (.97, .98, 1))
    fill(LEFT, y, width, .6, (.75, .80, .86))
    fill(LEFT, y + box, width, .6, (.75, .80, .86))
    pdf.text('IMPORTE DEVUELTO' if refund else 'IMPORTE RECIBIDO', LEFT + 10, y + 9, 7.4, True, GRAY)
    pdf.text(usd(payment['amount_cents']), LEFT + 10, y + 21, 19, True, BLUE)
    right(methods.get(payment['method'], payment['method']), y + 11, 9.6, True, INK)
    right('Dólares de los Estados Unidos (USD)', y + 27, 7.2, False, GRAY)
    y += box + 12
    if payment.get('note'):
        pair('Motivo o referencia' if refund else 'Nota o referencia', payment['note'])
    pair('Registrado por', payment.get('actor') or 'No consta')
    if payment.get('voided_at'):
        y += 2
        fill(LEFT, y, width, 30, (1, .95, .95))
        fill(LEFT, y, 2.5, 30, RED)
        pdf.text('MOVIMIENTO ANULADO el ' + _date(payment['voided_at']), LEFT + 8, y + 6, 8.6, True, RED)
        pdf.text(pdf.wrap('Motivo: ' + (payment.get('void_reason') or 'No registrado'), width - 16, 7.8)[0], LEFT + 8, y + 18, 7.8, False, INK)
        y += 38
    y += 6

    section('Estado de la cuenta ' + account['scope'])
    for label, cents, bold in (('Total a cobrar', account['budget_cents'], False), ('Pagado a la fecha', account['paid_cents'], False),
                               ('Saldo a favor del cliente' if account['credit_cents'] else 'Saldo pendiente', account['credit_cents'] or account['balance_cents'], True)):
        pdf.text(label, LEFT + 6, y, 9.2 if bold else 8.6, bold, INK)
        right(usd(cents), y, 10.5 if bold else 8.6, bold, BLUE if bold else INK)
        y += 16 if bold else 13
    pdf.text(account['state_label'] + ' · calculado el ' + generated.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'), LEFT + 6, y, 7.4, False, GRAY)
    y += 20

    pdf.line(LEFT, y, width)
    y += 8
    for note in ('Este documento deja constancia de un movimiento registrado en el sistema de PC-DOCTOR S.A. No es una factura ni un comprobante de venta autorizado por el SRI.',
                 'El saldo corresponde al momento de emisión y puede cambiar con nuevos cargos, pagos, devoluciones o anulaciones.'):
        for line in pdf.wrap(note, width - 4, 7.2):
            pdf.text(line, LEFT + 2, y, 7.2, False, GRAY)
            y += 9.5
        y += 3
    pdf.text(company['name'] + ' · WhatsApp ' + company['whatsapp'] + ' · ' + company['website'], LEFT + 2, H - 30, 7, False, GRAY)
    return pdf.finish()
