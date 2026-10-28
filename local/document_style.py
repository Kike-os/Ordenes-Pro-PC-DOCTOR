"""Identidad visual compartida de la proforma comercial y de la factura (RIDE) de PC-DOCTOR: fondo blanco, azul oscuro corporativo, logo
original proporcionado, encabezado con jerarquía, tabla con el encabezado repetido en cada página y filas que nunca se parten entre páginas,
totales destacados y pie discreto con la paginación. Solo presentación: los importes y los datos tributarios llegan ya calculados."""
import re

from code128 import widths as code128_widths
from corporate import settings as corporate
from document_canvas import GRAY, INK, WIDTHS, Canvas

TRADE_NAME = 'PC-DOCTOR'  # nombre comercial en los documentos (la razón social legal se muestra aparte en la factura)
A4 = (595.28, 841.89)
M = 36  # margen lateral
NAVY = (.06, .17, .33)
LINE = (.83, .86, .90)
SOFT = (.95, .96, .98)
RED = (.70, .12, .16)
WHITE = (1, 1, 1)
BOTTOM = A4[1] - 58  # límite inferior del contenido (el pie ocupa lo demás)


def text_width(text, size):
    return sum(WIDTHS.get(ch, 556) for ch in str(text)) * size / 1000


def filename(kind, number):
    """Nombre de archivo automático: PC-DOCTOR_PROFORMA_PF-000001.pdf · PC-DOCTOR_FACTURA_001-001-000000001.pdf."""
    return '%s_%s_%s.pdf' % (TRADE_NAME, kind, re.sub(r'[^A-Za-z0-9-]', '', str(number)) or 'SIN-NUMERO')


class Doc:
    """Lienzo A4 con coordenadas desde arriba. Guarda el flujo de cada página para escribir el pie al final (necesita el total de páginas)."""

    def __init__(self, title):
        self.c = Canvas(*A4, title)
        self.w, self.h = A4
        self.streams = []
        self.y = 0

    def page(self):
        self.c.page()
        self.streams.append(self.c.stream)

    # Primitivas.
    def text(self, value, x, y, size=9, bold=False, color=INK):
        self.c.text(value, x, y, size, bold, color)

    def right(self, value, x, y, size=9, bold=False, color=INK):
        self.c.text(value, x - text_width(value, size), y, size, bold, color)

    def center(self, value, x, y, size=9, bold=False, color=INK):
        self.c.text(value, x - text_width(value, size) / 2, y, size, bold, color)

    def wrap(self, value, width, size=9):
        return self.c.wrap(value, width, size)

    def rect(self, x, y, w, h, fill=None, stroke=LINE, line=.6):
        s = self.c.stream
        if fill:
            s.set_color_rgb(*fill)
            s.rectangle(x, self.h - y - h, w, h)
            s.fill()
        if stroke:
            s.set_color_rgb(*stroke, stroke=True)
            s.set_line_width(line)
            s.rectangle(x, self.h - y - h, w, h)
            s.stroke()

    def hline(self, x, y, w, color=LINE, weight=.6):
        s = self.c.stream
        s.set_color_rgb(*color)
        s.rectangle(x, self.h - y - weight, w, weight)
        s.fill()

    def logo(self, x, y, width):
        return self.c.logo(x, y, width)

    def barcode(self, value, x, y, w, h):
        """Code 128 real (con su zona de silencio) que ocupa el ancho indicado; el valor se imprime debajo con el texto legible."""
        modules = code128_widths(value)
        unit = w / (sum(modules) + 20)
        left = x + 10 * unit
        s = self.c.stream
        s.set_color_rgb(0, 0, 0)
        for i, size in enumerate(modules):
            if i % 2 == 0:
                s.rectangle(left, self.h - y - h, size * unit, h)
            left += size * unit
        s.fill()

    def qr(self, url, x, y, size):
        self.c.qr(url, x, y, size)

    def label(self, value, x, y, color=NAVY):
        """Rótulo de sección en mayúsculas, pequeño y espaciado."""
        self.text(value.upper(), x, y, 7.5, True, color)

    # Bloques compartidos.
    def brand(self, x, y, lines):
        """Logo original y nombre comercial con los datos de contacto; devuelve la altura usada."""
        h = self.logo(x, y, 92)
        tx = x + 104
        self.text(TRADE_NAME, tx, y + 2, 19, True, NAVY)
        yy = y + 26
        for value, bold in lines:
            for piece in self.wrap(value, 210, 8)[:2]:
                self.text(piece, tx, yy, 8, bold, INK if bold else GRAY)
                yy += 10.5
        return max(h, yy - y)

    def footer(self, legend='', legend_color=GRAY, contact=True):
        """Pie de todas las páginas: contacto discreto, leyenda (proforma o advertencia de prueba) y «Página n de N»."""
        company = corporate()
        info = ' · '.join(v for v in (TRADE_NAME, 'WhatsApp ' + company['whatsapp'] if company.get('whatsapp') else '', company.get('support_email', ''),
                                      re.sub(r'^https?://|/$', '', company.get('website', ''))) if v)
        total = len(self.streams)
        keep = self.c.stream
        for n, stream in enumerate(self.streams, 1):
            self.c.stream = stream
            self.hline(M, self.h - 44, self.w - 2 * M)
            if contact:
                self.text(info, M, self.h - 38, 7.5, False, GRAY)
            self.right('Página %d de %d' % (n, total), self.w - M, self.h - 38, 7.5, False, GRAY)
            if legend:
                self.center(legend, self.w / 2, self.h - 26, 7.5, True, legend_color)
        self.c.stream = keep

    def table(self, cols, rows, y, on_new_page):
        """Tabla con encabezado azul repetido en cada página. cols: (título, ancho, alineación 'l'/'r', clave, ajusta). Las filas no se parten:
        si una fila no cabe, pasa entera a la página siguiente. on_new_page() abre la página y devuelve la nueva coordenada y."""
        def head(y):
            self.rect(M, y, self.w - 2 * M, 18, fill=NAVY, stroke=None)
            x = M
            for title, w, align, _, _ in cols:
                if align == 'r':
                    self.right(title, x + w - 5, y + 5, 7.5, True, WHITE)
                else:
                    self.text(title, x + 5, y + 5, 7.5, True, WHITE)
                x += w
            return y + 22
        y = head(y)
        for n, row in enumerate(rows):
            cells = []
            for title, w, align, key, wraps in cols:
                value = str(row.get(key, '') if row.get(key) is not None else '')
                cells.append(self.wrap(value, w - 10, 8.5) if wraps else [value])
            extra = row.get('_note') or ''
            height = max(len(c) for c in cells) * 11 + (10 if extra else 0) + 6
            if y + height > BOTTOM:
                y = head(on_new_page())
            if n % 2:
                self.rect(M, y - 3, self.w - 2 * M, height, fill=SOFT, stroke=None)
            x = M
            for (title, w, align, key, wraps), lines in zip(cols, cells):
                for i, piece in enumerate(lines):
                    if align == 'r':
                        self.right(piece, x + w - 5, y + i * 11, 8.5)
                    else:
                        self.text(piece, x + 5, y + i * 11, 8.5 if key != 'code' else 8)
                x += w
            if extra:
                self.text(extra, M + cols[0][1] + 5, y + max(len(c) for c in cells) * 11, 7.5, False, GRAY)
            y += height
            self.hline(M, y - 3, self.w - 2 * M)
        return y + 4

    def totals(self, x, y, w, lines, grand):
        """Resumen con importes alineados a la derecha y el total final destacado sobre fondo azul oscuro."""
        for label, value in lines:
            self.text(label, x + 10, y, 8.5, False, INK)
            self.right(value, x + w - 10, y, 8.5)
            y += 14
        self.rect(x, y - 2, w, 26, fill=NAVY, stroke=None)
        self.text(grand[0], x + 10, y + 6, 9.5, True, WHITE)
        self.right(grand[1], x + w - 10, y + 5, 12, True, WHITE)
        return y + 30

    def finish(self):
        return self.c.finish()
