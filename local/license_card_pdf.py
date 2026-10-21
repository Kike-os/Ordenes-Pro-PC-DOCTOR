"""Tarjeta de Licencias Digitales en PDF (A4). Versión pública: producto, tipo, dispositivos, fechas, vigencia y estado; nunca claves,
usuarios ni contraseñas. Versión privada (solo administración, con autorización registrada): añade las credenciales de cada licencia.
Una licencia por recuadro, con su identificador interno (LIC-…): cinco licencias del mismo producto son cinco recuadros."""
from datetime import date

from document_canvas import Canvas, BLUE, GRAY, INK

W, H = 595.28, 841.89
LEFT, RIGHT = 36, W - 36
ROSE = (0xAA / 255, 0x47 / 255, 0x7C / 255)
TEAL = (.10, .55, .52)
COLORS = {'verde': (.13, .62, .36), 'amarillo': (.86, .66, .10), 'naranja': (.91, .45, .12), 'rojo': (.80, .16, .20), 'gris': (.62, .66, .72)}
WEBSITE = 'ecuadorpcdoctor.com'


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return ''


def tone(item):
    """Color de la barra según los días restantes (verde, amarillo, naranja o rojo); gris si no tiene vencimiento o está pendiente."""
    days = item.get('days_left')
    if item.get('state') == 'vencida' or (days is not None and days < 0):
        return 'rojo'
    if days is None or not item.get('activated_at'):
        return 'gris'
    if days <= 7:
        return 'rojo'
    if days <= 15:
        return 'naranja'
    if days <= 30:
        return 'amarillo'
    return 'verde'


def remaining(item):
    """Fracción de vigencia que queda (0 a 1) calculada con las fechas reales registradas."""
    days, period = item.get('days_left'), item.get('period_days')
    if days is None or not period:
        return None
    return max(0.0, min(1.0, days / period))


def render(card, private=False):
    pdf = Canvas(W, H, 'Tarjeta de Licencias Digitales · ' + (card.get('client') or '') + (' · privada' if private else ''))
    width = RIGHT - LEFT
    state = {'y': 0}

    def fill(x, top, w, h, color):
        pdf.stream.set_color_rgb(*color)
        pdf.stream.rectangle(x, pdf.h - top - h, w, h)
        pdf.stream.fill()

    def header():
        pdf.page()
        fill(0, 0, W, 5, BLUE)
        pdf.logo(LEFT, 22, 58)
        pdf.text('PC-DOCTOR S.A.', LEFT + 70, 24, 15, True, BLUE)
        pdf.text('Tarjeta de Licencias Digitales', LEFT + 70, 44, 11, True, INK)
        pdf.text('Información de productos, activaciones y vigencias.', LEFT + 70, 60, 8.2, False, GRAY)
        tag = 'VERSIÓN PRIVADA' if private else 'VERSIÓN PÚBLICA'
        pdf.text(tag, RIGHT - 92, 24, 8, True, ROSE if private else TEAL)
        pdf.line(LEFT, 84, width)
        meta = 'Cliente: ' + (card.get('client') or '—') + ('   ·   Orden ' + card['order'] if card.get('order') else '') + ('   ·   Entregada el ' + _day(card['delivered_at']) if card.get('delivered_at') else '')
        for line in pdf.wrap(meta, width, 8.6):
            pdf.text(line, LEFT, 94, 8.6, True, INK)
        state['y'] = 116

    def footer():
        top = H - 74
        pdf.line(LEFT, top, width)
        contact = card.get('contact') or {}
        pdf.text('PC-DOCTOR S.A.', LEFT, top + 8, 8.4, True, BLUE)
        pdf.text('Teléfono: ' + contact.get('phone', '') + '   ·   Correo: ' + contact.get('email', '') + '   ·   Sitio web: ' + WEBSITE, LEFT, top + 21, 7.6, False, INK)
        note = ('Documento privado: contiene credenciales personales. Guárdelo en un lugar seguro y no lo comparta.' if private else
                'Versión pública: no incluye claves, usuarios ni contraseñas. Las credenciales son personales y deben mantenerse protegidas; '
                'el cliente las consulta en su enlace privado, con su identificación y un código.')
        for i, line in enumerate(pdf.wrap(note, width, 7)):
            pdf.text(line, LEFT, top + 34 + i * 9, 7, False, GRAY)

    def ensure(height):
        if state['y'] + height > H - 92:
            footer()
            header()

    header()
    items = card.get('items') or []
    if not items:
        pdf.text('No hay licencias entregadas en esta tarjeta.', LEFT, state['y'], 9, False, GRAY)
    for item in items:
        creds = item.get('credentials') or [] if private else []
        name_lines = pdf.wrap(item.get('product') or '', width - 120, 10.5)
        cred_lines = [(cred['label'], pdf.wrap(str(cred['value']), width - 214, 7.8)) for cred in creds]
        kind = ' · '.join(x for x in (item.get('kind'), item.get('method_label'), item.get('term') and 'Duración: ' + item['term'],
                                      item.get('devices') and str(item['devices']) + (' dispositivo autorizado' if item['devices'] == 1 else ' dispositivos autorizados')) if x)
        kind_lines = pdf.wrap(kind, width - 24, 7.8)
        # Alto ajustado al contenido: nombre, datos, fechas, barra y, en la versión privada, las credenciales.
        height = 9 + 13 * len(name_lines) + 10 * len(kind_lines) + 2 + 16 + 12 + 8 + (sum(4 + 10 * len(lines) for _, lines in cred_lines) + 11 if creds else 0) + 8
        ensure(height)
        top = state['y']
        fill(LEFT, top, width, height - 8, (.96, .97, .99))
        fill(LEFT, top, 3, height - 8, ROSE)
        y = top + 9
        for line in name_lines:
            pdf.text(line, LEFT + 12, y, 10.5, True, BLUE)
            y += 13
        status = item.get('state_label') or ''
        pdf.text(status, RIGHT - 8 - len(status) * 4.6, top + 9, 8, True, COLORS[tone(item)] if tone(item) != 'gris' else GRAY)
        pdf.text(item.get('unit_code') or '', RIGHT - 8 - len(item.get('unit_code') or '') * 4.4, top + 21, 7.6, False, GRAY)
        for line in kind_lines:
            pdf.text(line, LEFT + 12, y + 2, 7.8, False, INK)
            y += 10
        dates = ('Activación: ' + (_day(item.get('activated_at')) or 'pendiente') + '     Vencimiento: ' + (_day(item.get('expires_at')) or 'sin vencimiento') +
                 ('     Días restantes: ' + str(max(item['days_left'], 0)) if item.get('days_left') is not None else ''))
        pdf.text(dates, LEFT + 12, y + 4, 7.8, False, INK)
        y += 16
        # Barra de vigencia: largo proporcional a lo que queda del periodo real; color según los días restantes.
        fill(LEFT + 12, y, width - 24, 5, (.88, .90, .93))
        part = remaining(item)
        if part:
            fill(LEFT + 12, y, (width - 24) * part, 5, COLORS[tone(item)])
        y += 12
        if creds:
            pdf.text('Credenciales', LEFT + 12, y, 7.8, True, ROSE)
            y += 11
            for label, lines in cred_lines:
                pdf.text(label + ':', LEFT + 12, y, 7.8, True, INK)
                for line in lines:
                    pdf.text(line, LEFT + 190, y, 7.8, False, INK)
                    y += 10
                y += 4
        state['y'] = top + height
    footer()
    return pdf.finish()
