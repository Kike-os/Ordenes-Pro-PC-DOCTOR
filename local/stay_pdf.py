"""Informe de permanencia de un equipo en el taller (A4). Refleja las fechas registradas; no contiene firmas ni
decisiones sobre el destino del equipo."""
from datetime import datetime

from corporate import settings
from document_canvas import Canvas, BLUE, GRAY, INK
from reception import ECUADOR_TZ

LEFT, RIGHT = 42, 553


def _date(value):
    try:
        return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return 'No registrada'


def render(order, info, delivery, generated):
    company = settings()
    width = RIGHT - LEFT
    pdf = Canvas(595.28, 841.89, 'Informe de permanencia · ' + order['code'] + ' · ' + company['name'])
    pdf.page()

    def fill(x, top, w, h, color):
        pdf.stream.set_color_rgb(*color)
        pdf.stream.rectangle(x, pdf.h - top - h, w, h)
        pdf.stream.fill()

    fill(0, 0, pdf.w, 5, BLUE)
    pdf.logo(LEFT, 26, 60)
    pdf.text(company['name'], LEFT + 72, 28, 18, True, BLUE)
    pdf.text(company['specialty'].upper(), LEFT + 72, 52, 8, True, GRAY)
    pdf.line(LEFT, 86, width)
    pdf.text('INFORME DE PERMANENCIA EN TALLER', LEFT, 102, 14, True, BLUE)
    pdf.text('Orden ' + order['code'] + '  ·  Emitido el ' + generated.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'), LEFT, 122, 9, False, GRAY)
    y = 148

    def section(title, pairs):
        nonlocal y
        fill(LEFT, y, width, 19, (.93, .95, .98))
        fill(LEFT, y, 3, 19, BLUE)
        pdf.text(title.upper(), LEFT + 10, y + 5, 9.6, True, BLUE)
        y += 27
        for label, value in pairs:
            lines = pdf.wrap(value or 'No registrado', width - 190, 9.6)
            pdf.text(label, LEFT + 7, y, 9.6, True, INK)
            for line in lines:
                pdf.text(line, LEFT + 180, y, 9.6, False, INK)
                y += 13
            y += 3
        y += 10

    section('Orden y equipo', [('Cliente', order['client']), ('Equipo', ' '.join(part for part in (order.get('brand'), order.get('model')) if part)),
                               ('Serie', order.get('serial')), ('Estado actual', order['status_label'])])
    span = '%d días y %d horas' % (info['days'], info['hours'])
    rows = [('Fecha de ingreso', _date(info['started_at'])), ('Plazo administrativo', '%d días naturales desde el ingreso' % info['limit'])]
    if info['closed']:
        rows += [('Fecha de entrega', _date(info['ended_at'])), ('Tiempo total en taller', span),
                 ('Días sobre el plazo', str(info['exceeded']) if info['exceeded'] else 'Ninguno'), ('Entrega registrada por', delivery['by'] or 'No consta en el historial')]
    else:
        rows += [('Tiempo transcurrido', span), ('Días restantes', str(info['remaining'])), ('Días sobre el plazo', str(info['exceeded']) if info['exceeded'] else 'Ninguno')]
    rows.append(('Situación', ('Entregado fuera del plazo' if info['exceeded'] else 'Entregado dentro del plazo') if info['closed'] else info['label']))
    section('Permanencia', rows)
    # Barra de avance, legible también en blanco y negro.
    fill(LEFT, y, width, 10, (.88, .91, .95))
    fill(LEFT, y, width * info['percent'] / 100, 10, BLUE)
    pdf.text('%d %% del plazo' % info['percent'], LEFT, y + 16, 8.2, False, GRAY)
    y += 40
    notes = ['El tiempo se cuenta desde la fecha de ingreso registrada hasta la entrega al cliente; el contador se detiene únicamente con el estado «Entregado».',
             'Superar el plazo genera avisos internos. El sistema no cambia el estado de la orden ni dispone del equipo de forma automática: cualquier decisión es administrativa.',
             'Este informe no contiene firmas ni constituye aceptación de condiciones por parte del cliente.']
    for note in notes:
        for line in pdf.wrap(note, width - 8, 8.6):
            pdf.text(line, LEFT + 4, y, 8.6, False, GRAY)
            y += 11.5
        y += 4
    pdf.line(LEFT, 794, width)
    pdf.text(company['website'] + '  |  WhatsApp: ' + company['whatsapp'] + '  |  ' + company['support_email'], LEFT, 802, 7.5, False, GRAY)
    return pdf.finish()
