"""PDF corporativo del presupuesto: datos del cliente y de la orden, ítems con su decisión, desglose de impuestos,
condiciones y, si existe, la evidencia de la aceptación del cliente con su firma manuscrita (trazos vectoriales)."""
import json
from datetime import datetime

import quotes
from corporate import settings
from document_canvas import Canvas, BLUE, GRAY
from reception import DEVICE_TYPES, ECUADOR_TZ

W, H, M = 595.28, 841.89, 42
INK = (.08, .13, .22)
MARK = {'aprobado': ('APROBADO', (.10, .50, .32)), 'rechazado': ('RECHAZADO', (.72, .18, .22)), 'pendiente': ('PENDIENTE', (.62, .44, .08)), 'cancelado': ('CANCELADO', (.45, .49, .56))}


def _stamp(value):
    try:
        return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return ''


def render(quote, order):
    """`quote`: resultado de quotes.detail; `order`: documento de la orden (cliente, equipo)."""
    company = settings()
    pdf = Canvas(W, H, 'Presupuesto ' + quote['code'])
    state = {'y': 0}

    def page():
        pdf.page()
        height = pdf.logo(M, 30, 92)
        pdf.text('PRESUPUESTO', W - M - 150, 34, 17, True, BLUE)
        pdf.text('N.º ' + quote['code'], W - M - 150, 56, 10, True, INK)
        pdf.text(quotes.STATUS[quote['status']].upper(), W - M - 150, 71, 8.5, True, MARK.get({'aprobado': 'aprobado', 'rechazado': 'rechazado', 'cancelado': 'cancelado'}.get(quote['status'], 'pendiente'))[1])
        pdf.text(company['name'] + ' · ' + company['specialty'], M, 36 + height, 8, False, GRAY)
        pdf.line(M, 58 + height, W - 2 * M)
        state['y'] = 70 + height

    def need(space):
        if state['y'] + space > H - 60:
            footer()
            page()

    def footer():
        pdf.line(M, H - 44, W - 2 * M)
        pdf.text(company['name'] + ' · WhatsApp ' + company['whatsapp'] + ' · ' + company.get('website', ''), M, H - 38, 7.5, False, GRAY)
        pdf.text('Página ' + str(pdf.pages), W - M - 46, H - 38, 7.5, False, GRAY)

    def heading(text,space=34):
        state['y'] += 6
        need(space)
        pdf.text(text.upper(), M, state['y'], 8.5, True, BLUE)
        pdf.line(M, state['y'] + 13, W - 2 * M)
        state['y'] += 20

    def pairs(rows):
        half = (W - 2 * M) / 2
        for index in range(0, len(rows), 2):
            need(26)
            for column, (label, value) in enumerate(rows[index:index + 2]):
                x = M + column * half
                pdf.text(label, x, state['y'], 7.5, False, GRAY)
                pdf.text(pdf.wrap(value or 'No registrado', half - 12, 9.5)[0], x, state['y'] + 10, 9.5, True, INK)
            state['y'] += 28

    page()
    heading('Datos del cliente y de la orden')
    device = ' '.join(part for part in (DEVICE_TYPES.get(order.get('type'), order.get('type') or ''), order.get('brand') or '', order.get('model') or '') if part)
    pairs([('Cliente', order.get('client')), ('Identificación', order.get('identification')), ('Orden de servicio', order.get('code')), ('Equipo', device),
           ('Fecha de emisión', _stamp(quote['sent_at'] or quote['created_at'])), ('Válido hasta', datetime.fromisoformat(quote['valid_until']).strftime('%d/%m/%Y') if quote['valid_until'] else 'Sin fecha límite indicada'),
           ('Técnico asignado', order.get('responsible') or 'Sin asignar'), ('Número de serie', order.get('serial') or 'No registrado')])

    heading('Servicios y productos cotizados')
    columns = [(M, 'Descripción'), (W - M - 232, 'Cant.'), (W - M - 196, 'P. unitario'), (W - M - 128, 'Importe'), (W - M - 62, 'Decisión')]
    for x, title in columns:
        pdf.text(title, x, state['y'], 7.5, True, GRAY)
    state['y'] += 14
    for item in quote['items']:
        lines = pdf.wrap(item['description'] + ('' if item['taxed'] else ' (tarifa 0 %)'), W - 2 * M - 246, 9)
        need(13 * len(lines) + 10)
        for offset, text in enumerate(lines):
            pdf.text(text, M, state['y'] + 12 * offset, 9, False, INK)
        pdf.text(str(item['quantity']), W - M - 232, state['y'], 9, False, INK)
        pdf.text(quotes.usd(item['unit_cents']), W - M - 196, state['y'], 9, False, INK)
        pdf.text(quotes.usd(item.get('net_cents', item['line_cents'])), W - M - 128, state['y'], 9, True, INK)
        label, color = MARK[item['status']]
        pdf.text(label, W - M - 62, state['y'] + 1, 7.5, True, color)
        state['y'] += 12 * len(lines) + 5
        pdf.line(M, state['y'], W - 2 * M)
        state['y'] += 6
    if not quote['items']:
        pdf.text('Este presupuesto todavía no tiene ítems.', M, state['y'], 9, False, GRAY)
        state['y'] += 16

    totals, rate = quote['totals'], quote['tax_rate_bp'] / 100
    decided = quote['status'] in ('aprobado', 'parcial', 'rechazado')
    rows = ([('Importe antes del descuento', totals['gross']), ('%s (%g %%)' % (quotes.DISCOUNTS[totals['discount_bp']], totals['discount_bp'] / 100), -totals['discount'])] if totals.get('discount_bp') else []) + [('Subtotal con IVA %g %%' % rate, totals['base_taxed']), ('Subtotal tarifa 0 %', totals['base_zero']), ('IVA %g %%' % rate, totals['tax']), ('TOTAL COTIZADO', totals['quoted'])]
    if decided:
        rows += [('Total aprobado', totals['approved']), ('Importe rechazado', totals['rejected'])]
    need(16 * len(rows) + 12)
    state['y'] += 4
    for label, value in rows:
        strong = label.isupper() or label == 'Total aprobado'
        pdf.text(label, W - M - 232, state['y'], 9.5 if strong else 9, strong, INK if strong else GRAY)
        pdf.text(('− ' + quotes.usd(-value)) if value < 0 else quotes.usd(value), W - M - 128, state['y'], 9.5 if strong else 9, strong, INK)
        state['y'] += 16
    pdf.text('Los precios incluyen impuestos. Este documento es un presupuesto; no constituye una factura.', M, state['y'], 7.5, False, GRAY)
    state['y'] += 18

    if quote['notes']:
        heading('Observaciones')
        for text in pdf.wrap(quote['notes'], W - 2 * M, 9):
            need(13)
            pdf.text(text, M, state['y'], 9, False, INK)
            state['y'] += 12
        state['y'] += 8

    heading('Condiciones de autorización')
    for paragraph in (quote['conditions'] or quotes.CONDITIONS).split('\n'):
        for text in pdf.wrap(paragraph, W - 2 * M, 8.5):
            need(12)
            pdf.text(text, M, state['y'], 8.5, False, INK)
            state['y'] += 11.5
        state['y'] += 4

    acceptance = quote.get('acceptance')
    heading('Decisión del cliente', 190 if acceptance else 50)
    if acceptance:
        pairs([('Firmado por', acceptance['signer_name']), ('Fecha y hora (Ecuador)', _stamp(acceptance['created_at'])), ('Método de verificación', acceptance['method']), ('Huella de la evidencia (SHA-256)', acceptance['evidence_hash'][:40] + '…')])
        strokes = json.loads(acceptance['signature']) if acceptance['signature'] else []
        if strokes:
            box_w, box_h, top = 240, 72, state['y']
            pdf.text('Firma manuscrita digitalizada', M, top, 7.5, False, GRAY)
            pdf.stream.set_color_rgb(.08, .13, .22, stroke=True)
            pdf.stream.set_line_width(1)
            for stroke in strokes:
                pdf.stream.move_to(M + stroke[0][0] / 1000 * box_w, H - (top + 12 + stroke[0][1] / 300 * box_h))
                for x, y in stroke[1:]:
                    pdf.stream.line_to(M + x / 1000 * box_w, H - (top + 12 + y / 300 * box_h))
                pdf.stream.stroke()
            pdf.line(M, top + 14 + box_h, box_w)
            state['y'] = top + 22 + box_h
        pdf.text('Esta firma es un trazo manuscrito digitalizado con registro de fecha, hora y método de verificación. No es una firma electrónica certificada.', M, state['y'], 7.5, False, GRAY)
        state['y'] += 14
    elif decided:
        pdf.text('Decisión registrada por el personal del taller el ' + _stamp(quote['decided_at']) + ' (sin firma del cliente en este documento).', M, state['y'], 9, False, INK)
        state['y'] += 14
    else:
        pdf.text('Pendiente de la decisión del cliente.', M, state['y'], 9, False, GRAY)
        state['y'] += 14
    footer()
    return pdf.finish()
