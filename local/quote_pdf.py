"""PDF corporativo del presupuesto (A4): encabezado con la identidad de PC-DOCTOR S.A., datos del cliente y del equipo, partidas con icono,
clasificación, descuento y estado real de autorización, resumen económico, condiciones de aprobación, bloque de aprobación en línea con
código QR (solo cuando existe un enlace vigente) y, si la hay, la evidencia de la decisión del cliente con su firma manuscrita.

El documento se compone sobre fondo blanco, con acentos de color discretos, para que se imprima sin gastar tinta. Los importes llevan
símbolo de dólar, separador de miles y dos decimales; se toman tal cual del presupuesto guardado, nunca se recalculan aquí."""
import json
from datetime import datetime

import pydyf

import catalog_icons
import quotes
from corporate import settings
from document_canvas import Canvas, BLUE, GRAY, WIDTHS
from reception import DEVICE_TYPES, ECUADOR_TZ

W, H, M = 595.28, 841.89, 40
INK = (.08, .13, .22)
SOFT = (.955, .97, .985)
LINE = (.80, .85, .90)
MARK = {'aprobado': ('APROBADO', (.10, .50, .32)), 'rechazado': ('RECHAZADO', (.72, .18, .22)), 'pendiente': ('PENDIENTE', (.62, .44, .08)), 'cancelado': ('CANCELADO', (.45, .49, .56))}
STATE = {'borrador': (.36, .43, .54), 'enviado': (.62, .44, .08), 'modificacion': (.62, .44, .08), 'parcial': (.10, .50, .32), 'aprobado': (.10, .50, .32), 'rechazado': (.72, .18, .22), 'cancelado': (.45, .49, .56)}
# La fuente base del PDF (Helvetica, WinAnsi) no tiene estos signos: se sustituyen para que nunca aparezca un «?» en el documento.
SAFE = str.maketrans({'−': '-', '‑': '-', '→': '>', '←': '<', '≥': '>=', '≤': '<=', '✓': '', '✔': '', ' ': ' ', ' ': ' ', ' ': ' '})


def _stamp(value, hour=True):
    try:
        return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M' if hour else '%d/%m/%Y')
    except (TypeError, ValueError):
        return ''


def _day(value):
    try:
        return datetime.fromisoformat(value).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return ''


def clean(text):
    """Texto apto para la fuente del documento."""
    return str(text if text is not None else '').translate(SAFE).encode('cp1252', 'replace').decode('cp1252')


def render(quote, order, link=None):
    """`quote`: resultado de quotes.detail; `order`: documento de la orden (cliente, equipo).
    `link`: {'url', 'expires_at'} del enlace privado vigente, solo si quien pide el documento ya lo tiene; sin él no se dibuja ningún QR."""
    company = settings()
    pdf = Canvas(W, H, 'Presupuesto ' + quote['code'])
    state = {'y': 0}
    decided = quote['status'] in quotes.DECIDED

    def width(text, size, bold=False):
        return sum(WIDTHS.get(char, 556) for char in text) * size / 1000 * (1.06 if bold else 1)

    def text(value, x, y, size=9, bold=False, color=INK, right=False):
        value = clean(value)
        pdf.text(value, x - width(value, size, bold) if right else x, y, size, bold, color)

    def fill(x, y, w, h, color):
        pdf.stream.set_color_rgb(*((1, 1, 1) if pdf.mono else color))
        pdf.stream.rectangle(x, H - y - h, w, h)
        pdf.stream.fill()

    def rule(y, x=M, w=W - 2 * M, color=LINE):
        fill(x, y, w, .6, color)

    def wrap(value, room, size):
        return pdf.wrap(clean(value), room, size)

    def anchor(url, x, y, w, h):
        note = pydyf.Dictionary({'Type': '/Annot', 'Subtype': '/Link', 'Rect': pydyf.Array([x, H - y - h, x + w, H - y]), 'Border': pydyf.Array([0, 0, 0]), 'A': pydyf.Dictionary({'S': '/URI', 'URI': pydyf.String(url)})})
        pdf.pdf.add_object(note)
        current = pdf.current.get('Annots')
        pdf.current['Annots'] = pydyf.Array((list(current) if current else []) + [note.reference])

    def footer():
        rule(H - 46)
        text(company['name'] + '  ·  WhatsApp ' + company['whatsapp'] + '  ·  ' + company.get('website', '').replace('https://', '').rstrip('/'), M, H - 39, 7.5, False, GRAY)
        text('Presupuesto ' + quote['code'] + '  ·  Página ' + str(pdf.pages), W - M, H - 39, 7.5, False, GRAY, True)
        text('Documento informativo. No constituye factura ni comprobante de venta autorizado por el SRI.', M, H - 29, 6.8, False, GRAY)

    def page(first=False):
        pdf.page()
        fill(0, 0, W, 5, BLUE)
        if first:
            height = pdf.logo(M, 26, 96)
            text(company['name'], M + 108, 34, 13, True, INK)
            text(company['specialty'], M + 108, 51, 8.5, False, GRAY)
            text('WhatsApp ' + company['whatsapp'], M + 108, 64, 8, False, GRAY)
            text(company.get('website', '').replace('https://', '').rstrip('/'), M + 108, 75, 8, False, GRAY)
            text('PRESUPUESTO TÉCNICO', W - M, 30, 15, True, BLUE, True)
            text('N.º ' + quote['code'], W - M, 51, 10.5, True, INK, True)
            label = quotes.STATUS[quote['status']].upper()
            box = width(label, 8, True) + 16
            fill(W - M - box, 67, box, 15, STATE[quote['status']])
            text(label, W - M - 8, 70.5, 8, True, (1, 1, 1), True)
            issued = _stamp(quote['sent_at'] or quote['created_at'], False)
            text('Emisión: ' + issued + '   ·   Vence: ' + (_day(quote['valid_until']) or 'sin fecha límite'), W - M, 90, 8, False, GRAY, True)
            top = max(26 + height, 104) + 8
            rule(top, color=BLUE)
            state['y'] = top + 12
        else:
            text(company['name'] + '  ·  Presupuesto técnico', M, 18, 8.5, True, BLUE)
            text('N.º ' + quote['code'] + '  ·  ' + quotes.STATUS[quote['status']], W - M, 18, 8.5, False, GRAY, True)
            rule(32)
            state['y'] = 44

    def need(space):
        if state['y'] + space > H - 58:
            footer()
            page()
            return True
        return False

    def heading(label, space=40):
        state['y'] += 4
        need(space)
        fill(M, state['y'], 3, 11, BLUE)
        text(label.upper(), M + 9, state['y'] + .5, 9, True, BLUE)
        state['y'] += 18

    def pairs(rows, columns=3):
        cell = (W - 2 * M) / columns
        for index in range(0, len(rows), columns):
            need(28)
            for column, (label, value) in enumerate(rows[index:index + columns]):
                x = M + column * cell
                text(label, x, state['y'], 7.2, False, GRAY)
                text(wrap(value or 'No registrado', cell - 10, 9.2)[0], x, state['y'] + 10, 9.2, True, INK)
            state['y'] += 27

    page(True)

    # --- Cliente y equipo ---
    heading('Datos del cliente y del equipo')
    device = ' '.join(part for part in (DEVICE_TYPES.get(order.get('type'), order.get('type') or ''), order.get('brand') or '', order.get('model') or '') if part)
    pairs([('Cliente', order.get('client')), ('Identificación', order.get('identification')), ('Orden de servicio', order.get('code')),
           ('Equipo', device), ('Número de serie', order.get('serial') or 'No registrado'), ('Técnico responsable', order.get('responsible') or 'Sin asignar')])

    # --- Partidas ---
    heading('Productos y servicios cotizados')
    left, c_qty, c_unit, c_disc, c_total, c_state = M + 26, W - M - 252, W - M - 190, W - M - 132, W - M - 72, W - M
    room = c_qty - 20 - left

    def table_head():
        fill(M, state['y'] - 3, W - 2 * M, 17, SOFT)
        text('Descripción', left, state['y'] + 1, 7.4, True, GRAY)
        for x, title in ((c_qty, 'Cant.'), (c_unit, 'P. unitario'), (c_disc, 'Descuento'), (c_total, 'Importe'), (c_state, 'Autorización')):
            text(title, x, state['y'] + 1, 7.4, True, GRAY, True)
        state['y'] += 21

    table_head()
    for item in quote['items']:
        lines = wrap(item['description'] + ('' if item['taxed'] else ' (tarifa 0 %)'), room, 9)
        priority = quotes.PRIORITIES.get(item.get('priority') or '')
        height = max(11.5 * len(lines) + (13 if priority else 0), 20)
        if need(height + 12):
            table_head()
        catalog_icons.draw(pdf, item.get('icon') or 'generico', M + 2, state['y'] - 2, 17)
        for offset, row in enumerate(lines):
            text(row, left, state['y'] + 11.5 * offset, 9, offset == 0 and len(lines) == 1, INK)
        if priority:
            top = state['y'] + 11.5 * len(lines) + 1
            fill(left, top, 3, 9.5, priority[2])
            text(priority[0].upper(), left + 7, top + 1, 6.8, True, priority[2])
        full = item['quantity'] * item['unit_cents']
        net = item.get('net_cents', item['line_cents'])
        text(str(item['quantity']), c_qty, state['y'], 9, False, INK, True)
        text(quotes.usd(item['unit_cents']), c_unit, state['y'], 9, False, INK, True)
        text('-' + quotes.usd(full - net) if full != net else '—', c_disc, state['y'], 9, False, GRAY, True)
        text(quotes.usd(net), c_total, state['y'], 9, True, INK, True)
        label, color = MARK[item['status']]
        if item['status'] == 'pendiente':
            label = 'POR DECIDIR' if decided else 'BORRADOR' if quote['status'] == 'borrador' else 'PENDIENTE'
            color = MARK['cancelado'][1] if quote['status'] == 'borrador' else color
        text(label, c_state, state['y'] + 1, 7, True, color, True)
        state['y'] += height + 5
        rule(state['y'])
        state['y'] += 7
    if not quote['items']:
        text('Este presupuesto todavía no tiene partidas.', left, state['y'], 9, False, GRAY)
        state['y'] += 18
    if any(item.get('priority') for item in quote['items']):
        need(26)
        x = M
        for key, (label, _, color) in quotes.PRIORITIES.items():
            fill(x, state['y'], 3, 8, color)
            note = label + ': ' + {'necesario': 'recomendado para solucionar el problema', 'obligatorio': 'indispensable para la intervención', 'opcional': 'adicional, a su elección'}[key]
            text(note, x + 6, state['y'], 6.8, False, GRAY)
            x += width(note, 6.8) + 20
        state['y'] += 11
        text('La clasificación es informativa: ninguna partida queda autorizada sin la aprobación del cliente.', M, state['y'], 6.8, False, GRAY)
        state['y'] += 14

    # --- Resumen económico ---
    totals, rate = quote['totals'], quote['tax_rate_bp'] / 100
    rows = []
    if totals.get('discount_bp'):
        rows += [('Importe original', quotes.usd(totals['gross']), False), ('Descuento autorizado (%g %%)' % (totals['discount_bp'] / 100), '-' + quotes.usd(totals['discount']), False)]
    rows += [('Subtotal gravado', quotes.usd(totals['base_taxed']), False), ('Subtotal tarifa 0 %', quotes.usd(totals['base_zero']), False), ('IVA %g %%' % rate, quotes.usd(totals['tax']), False)]
    after = []
    if decided:
        after += [('Total autorizado', quotes.usd(totals['approved']), (.10, .50, .32)), ('Importe rechazado', quotes.usd(totals['rejected']), GRAY)]
        if totals['pending']:
            after.append(('Por decidir', quotes.usd(totals['pending']), GRAY))
    box_w, box_x = 250, W - M - 250
    need(15 * len(rows) + 30 + 15 * len(after) + 24)
    state['y'] += 2
    for label, value, _ in rows:
        text(label, box_x + 10, state['y'], 9, False, GRAY)
        text(value, W - M - 10, state['y'], 9, False, INK, True)
        state['y'] += 15
    fill(box_x, state['y'], box_w, 24, BLUE)
    text('TOTAL COTIZADO', box_x + 10, state['y'] + 7, 10, True, (1, 1, 1))
    text(quotes.usd(totals['quoted']), W - M - 10, state['y'] + 6, 11.5, True, (1, 1, 1), True)
    state['y'] += 31
    for label, value, color in after:
        text(label, box_x + 10, state['y'], 9, True, color)
        text(value, W - M - 10, state['y'], 9, True, color, True)
        state['y'] += 15
    text('Los precios incluyen los impuestos indicados. Valores en dólares de los Estados Unidos de América.', M, state['y'], 7.2, False, GRAY)
    state['y'] += 16

    if quote['notes']:
        heading('Observaciones')
        for row in wrap(quote['notes'], W - 2 * M, 9):
            need(13)
            text(row, M, state['y'], 9, False, INK)
            state['y'] += 12
        state['y'] += 6

    # --- Condiciones ---
    heading('Condiciones de aprobación y ejecución', 60)
    for title, body in quotes.clauses(quote['conditions'] or quotes.CONDITIONS):
        lines = wrap(body, W - 2 * M, 8.2)
        need((11 if title else 0) + 10.5 * min(len(lines), 2) + 4)
        if title:
            text(title, M, state['y'], 8.2, True, INK)
            state['y'] += 11
        for row in lines:
            need(11)
            text(row, M, state['y'], 8.2, False, INK)
            state['y'] += 10.5
        state['y'] += 4

    # --- Aprobación en línea (QR) o decisión registrada ---
    acceptance = quote.get('acceptance')
    if quote['status'] == 'enviado':
        heading('Revisa y aprueba tu presupuesto en línea', 150)
        top = state['y']
        if link:
            size = 104
            fill(M, top, W - 2 * M, size + 20, SOFT)
            fill(M + 10, top + 10, size, size, (1, 1, 1))
            pdf.qr(link['url'], M + 10, top + 10, size)
            pdf.current['Annots'] = pydyf.Array(list(pdf.current['Annots']))
            x, y = M + size + 26, top + 12
            for row in wrap('Escanea el código QR o utiliza el enlace seguro para revisar los productos y servicios cotizados. Podrás autorizar las partidas seleccionadas y registrar tu aceptación electrónica.', W - M - x - 10, 9):
                text(row, x, y, 9, False, INK)
                y += 12
            y += 4
            label = 'Abrir mi presupuesto en línea'
            fill(x, y, width(label, 9, True) + 20, 18, BLUE)
            text(label, x + 10, y + 4.5, 9, True, (1, 1, 1))
            anchor(link['url'], x, y, width(label, 9, True) + 20, 18)
            y += 26
            text('Enlace vigente hasta el ' + _stamp(link['expires_at']) + ' (hora de Ecuador)' + ('  ·  Presupuesto válido hasta el ' + _day(quote['valid_until']) if quote['valid_until'] else ''), x, y, 7.6, False, GRAY)
            y += 11
            text('Estado: pendiente de la decisión del cliente.', x, y, 7.6, False, GRAY)
            y += 11
            for row in wrap('Enlace personal y privado: no lo reenvíes. Se te pedirán los últimos cuatro dígitos de tu identificación. Escanear el código no aprueba nada: cada partida se autoriza de forma expresa.', W - M - x - 10, 7.6):
                text(row, x, y, 7.6, False, GRAY)
                y += 10
            state['y'] = max(top + size + 28, y + 6)
        else:
            for row in wrap('El enlace privado de aprobación se envió a ' + (quote['sent_to'] or 'el correo registrado del cliente') + ' el ' + _stamp(quote['sent_at']) + '. Por seguridad el sistema no conserva el enlace: el código QR aparece en el documento que recibe el cliente.', W - 2 * M, 9):
                text(row, M, state['y'], 9, False, INK)
                state['y'] += 12
            state['y'] += 6
    elif quote['status'] in ('borrador', 'modificacion'):
        heading('Aprobación en línea', 40)
        for row in wrap('Este presupuesto es un borrador: todavía no se ha enviado al cliente y no tiene un enlace de aprobación.' if quote['status'] == 'borrador' else 'El cliente solicitó una modificación. El enlace anterior ya no sirve; al enviar la nueva versión se emitirá otro.', W - 2 * M, 9):
            text(row, M, state['y'], 9, False, GRAY)
            state['y'] += 12
        state['y'] += 6
    elif quote['status'] == 'cancelado':
        heading('Presupuesto anulado', 40)
        text('Este presupuesto fue anulado y no admite aprobación. Se conserva únicamente como registro.', M, state['y'], 9, False, GRAY)
        state['y'] += 16

    if decided:
        heading('Decisión del cliente', 190 if acceptance else 50)
        if acceptance:
            pairs([('Firmado por', acceptance['signer_name']), ('Fecha y hora (Ecuador)', _stamp(acceptance['created_at'])), ('Presupuesto y versión', quote['code'])], 3)
            pairs([('Método de verificación', acceptance['method']), ('Huella de la evidencia (SHA-256)', acceptance['evidence_hash'][:40] + '…')], 2)
            strokes = json.loads(acceptance['signature']) if acceptance['signature'] else []
            if strokes:
                box_w, box_h, top = 240, 72, state['y']
                text('Firma manuscrita digitalizada', M, top, 7.5, False, GRAY)
                pdf.stream.set_color_rgb(.08, .13, .22, stroke=True)
                pdf.stream.set_line_width(1)
                for stroke in strokes:
                    pdf.stream.move_to(M + stroke[0][0] / 1000 * box_w, H - (top + 12 + stroke[0][1] / 300 * box_h))
                    for x, y in stroke[1:]:
                        pdf.stream.line_to(M + x / 1000 * box_w, H - (top + 12 + y / 300 * box_h))
                    pdf.stream.stroke()
                rule(top + 14 + box_h, M, box_w)
                state['y'] = top + 22 + box_h
            for row in wrap('Esta firma es un trazo manuscrito digitalizado con registro de fecha, hora y método de verificación. No es una firma electrónica certificada.', W - 2 * M, 7.5):
                text(row, M, state['y'], 7.5, False, GRAY)
                state['y'] += 10
        else:
            for row in wrap('Decisión registrada por el personal del taller el ' + _stamp(quote['decided_at']) + '. No consta firma del cliente en este documento.', W - 2 * M, 9):
                text(row, M, state['y'], 9, False, INK)
                state['y'] += 12
    footer()
    return pdf.finish()
