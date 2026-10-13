"""Iconos del catálogo de productos y servicios.

Cada icono es un dibujo propio de trazo simple (cuadrícula de 24 × 24), definido una sola vez con primitivas (líneas y círculos) para
usarlo igual en la pantalla (como trazado SVG) y en el PDF (trazos vectoriales). No son logotipos de ninguna marca: los logotipos
oficiales se muestran con la imagen que administración sube al elemento o con el logotipo de la marca que ya tenga el sistema.

El icono se guarda en el elemento del catálogo (`catalog_items.icon`), de modo que queda ligado a su identificador y no al nombre.
Al crear un elemento sin icono se propone uno según su categoría y sus palabras clave; administración puede cambiarlo."""
import math
import re
import unicodedata

L, C = 'L', 'C'  # polilínea, círculo


def _box(x, y, w, h):
    return (L, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)


LAPTOP = [_box(4, 4, 16, 11), (L, [(2, 19), (22, 19)], False), (L, [(4, 15), (2, 19)], False), (L, [(20, 15), (22, 19)], False)]
TOWER = [_box(6, 2, 12, 20), (L, [(9, 6), (15, 6)], False), (L, [(9, 9), (15, 9)], False), (C, 12, 16, 1.6)]
SHIELD = [(L, [(12, 2), (20, 5), (20, 11), (18, 16.5), (12, 22), (6, 16.5), (4, 11), (4, 5)], True)]
ICONS = {
    'pantalla': ('Pantalla de portátil', LAPTOP + [(L, [(11, 4), (9, 8), (12.5, 10), (10.5, 15)], False), (L, [(12.5, 10), (16, 8)], False)]),
    'pantalla_gamer': ('Pantalla de portátil gamer', LAPTOP + [(L, [(11, 4), (9, 8), (12.5, 10), (10.5, 15)], False), (L, [(12.5, 10), (16, 8)], False), (L, [(6, 21.5), (10, 21.5)], False), (L, [(14, 21.5), (18, 21.5)], False)]),
    'bisagra': ('Bisagra de portátil', [(L, [(3, 20), (21, 20)], False), (L, [(4, 20), (4, 17), (20, 17), (20, 20)], False), (L, [(6, 17), (10, 4), (21, 7), (18, 17)], False), (C, 6, 17, 1.6), (L, [(2.5, 11), (5, 12)], False), (L, [(3, 7.5), (5.5, 9.5)], False)]),
    'escritorio': ('PC de escritorio', [_box(3, 3, 9, 18), (L, [(5.5, 6.5), (9.5, 6.5)], False), (C, 7.5, 16, 1.4), (C, 18, 7, 2.6), (L, [(18, 9.6), (18, 21)], False), (L, [(16, 21), (20, 21)], False)]),
    'pc_gamer': ('PC gamer', [_box(5, 2, 14, 20), (C, 12, 8, 3), (C, 12, 16, 2.2), (L, [(2, 6), (3.5, 6)], False), (L, [(2, 12), (3.5, 12)], False), (L, [(2, 18), (3.5, 18)], False), (L, [(20.5, 6), (22, 6)], False), (L, [(20.5, 12), (22, 12)], False), (L, [(20.5, 18), (22, 18)], False)]),
    'bios': ('BIOS / chip', [_box(7, 7, 10, 10), (L, [(10.5, 10.5), (9, 12), (10.5, 13.5)], False), (L, [(13.5, 10.5), (15, 12), (13.5, 13.5)], False)] + [(L, [(p, 3), (p, 7)], False) for p in (10, 14)] + [(L, [(p, 17), (p, 21)], False) for p in (10, 14)] + [(L, [(3, p), (7, p)], False) for p in (10, 14)] + [(L, [(17, p), (21, p)], False) for p in (10, 14)]),
    'antivirus': ('Antivirus y seguridad', SHIELD + [(L, [(8.5, 11.5), (11, 14), (15.5, 9)], False)]),
    'windows': ('Sistema operativo', [_box(3, 4, 8, 7), _box(13, 4, 8, 7), _box(3, 13, 8, 7), _box(13, 13, 8, 7)]),
    'ofimatica': ('Ofimática', [(L, [(6, 2), (14, 2), (19, 7), (19, 22), (6, 22)], True), (L, [(14, 2), (14, 7), (19, 7)], False), (L, [(9, 12), (16, 12)], False), (L, [(9, 15.5), (16, 15.5)], False), (L, [(9, 19), (13, 19)], False)]),
    'licencia': ('Licencia', [(C, 8, 12, 4.5), (L, [(12.5, 12), (22, 12)], False), (L, [(18, 12), (18, 15.5)], False), (L, [(21, 12), (21, 14.5)], False)]),
    'consola': ('Consola de videojuegos', [(L, [(6, 7), (18, 7), (21.5, 16), (19, 18), (15.5, 14.5), (8.5, 14.5), (5, 18), (2.5, 16)], True), (L, [(7, 10.8), (10, 10.8)], False), (L, [(8.5, 9.3), (8.5, 12.3)], False), (C, 15.2, 11.6, .9), (C, 17.4, 9.8, .9)]),
    'impresora': ('Impresora', [_box(7, 3, 10, 5), (L, [(7, 16), (4, 16), (4, 8), (20, 8), (20, 16), (17, 16)], False), _box(7, 13, 10, 8)]),
    'memoria': ('Memoria RAM', [_box(2, 7, 20, 9), (L, [(5, 16), (5, 19)], False), (L, [(9, 16), (9, 19)], False), (L, [(15, 16), (15, 19)], False), (L, [(19, 16), (19, 19)], False), _box(5, 9.5, 3, 3.5), _box(10.5, 9.5, 3, 3.5), _box(16, 9.5, 3, 3.5)]),
    'almacenamiento': ('Disco o almacenamiento', [_box(4, 3, 16, 18), (C, 12, 10, 3.6), (C, 12, 10, .8), (L, [(7, 18), (10, 18)], False)]),
    'mantenimiento': ('Mantenimiento', [(C, 12, 12, 3), (L, [(12, 2), (12, 5)], False), (L, [(12, 19), (12, 22)], False), (L, [(2, 12), (5, 12)], False), (L, [(19, 12), (22, 12)], False), (L, [(5, 5), (7, 7)], False), (L, [(17, 17), (19, 19)], False), (L, [(5, 19), (7, 17)], False), (L, [(17, 7), (19, 5)], False), (C, 12, 12, 7)]),
    'diagnostico': ('Diagnóstico', [(C, 10.5, 10.5, 6.5), (L, [(15.5, 15.5), (21, 21)], False), (L, [(7, 10.5), (9, 10.5), (10, 8), (11.5, 13), (12.5, 10.5), (14, 10.5)], False)]),
    'repuesto': ('Repuesto o componente', [_box(5, 5, 14, 14), _box(9, 9, 6, 6)] + [(L, [(p, 2), (p, 5)], False) for p in (9, 15)] + [(L, [(p, 19), (p, 22)], False) for p in (9, 15)]),
    'servicio': ('Servicio técnico', [(L, [(14.5, 5.5), (18.5, 9.5)], False), (L, [(16.5, 7.5), (5, 19), (3, 21)], False), (L, [(14.5, 5.5), (17, 3), (21, 7), (18.5, 9.5)], False), (L, [(3, 5), (6, 3), (8, 5.5), (6.5, 8), (10, 11.5)], False)]),
    'producto': ('Producto', [(L, [(12, 2), (21, 7), (21, 17), (12, 22), (3, 17), (3, 7)], True), (L, [(3, 7), (12, 12), (21, 7)], False), (L, [(12, 12), (12, 22)], False)]),
    'generico': ('Genérico', [_box(4, 4, 16, 16), (L, [(8, 12), (16, 12)], False), (L, [(12, 8), (12, 16)], False)]),
}
# Icono por omisión de cada categoría del catálogo, cuando ninguna palabra clave coincide.
BY_CATEGORY = {'servicio': 'servicio', 'licencia': 'licencia', 'seguridad': 'antivirus', 'repuesto': 'repuesto', 'otro': 'producto'}
# Palabras clave (sin tildes) → icono. Se evalúan en orden: lo más específico primero.
RULES = (
    (('pantalla', 'gamer'), 'pantalla_gamer'), (('pantalla',), 'pantalla'), (('display',), 'pantalla'), (('bisagra',), 'bisagra'),
    (('bios',), 'bios'), (('gamer',), 'pc_gamer'), (('escritorio',), 'escritorio'),
    (('playstation',), 'consola'), (('xbox',), 'consola'), (('nintendo',), 'consola'), (('consola',), 'consola'),
    (('impresora',), 'impresora'), (('memoria', 'ram'), 'memoria'), (('ssd',), 'almacenamiento'), (('disco',), 'almacenamiento'),
    (('antivirus',), 'antivirus'), (('office',), 'ofimatica'), (('windows',), 'windows'),
    (('diagnostico',), 'diagnostico'), (('chequeo',), 'diagnostico'), (('mantenimiento',), 'mantenimiento'), (('limpieza',), 'mantenimiento'),
)


def plain(text):
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text or '').lower()) if unicodedata.category(ch) != 'Mn')


def guess(category, name='', brand=''):
    """Icono propuesto para un elemento nuevo: palabras clave del nombre y la marca; si no hay coincidencia, el de su categoría."""
    words = set(re.findall(r'[a-z0-9]+', plain(name + ' ' + brand)))
    for needed, key in RULES:
        if all(any(word.startswith(part) for word in words) for part in needed):
            return key
    return BY_CATEGORY.get(category, 'generico')


def valid(key):
    return key if key in ICONS else 'generico'


def svg_path(key):
    """Trazado SVG (atributo d) del icono, para dibujarlo en pantalla con trazo redondeado."""
    parts = []
    for shape in ICONS[valid(key)][1]:
        if shape[0] == L:
            parts.append('M' + ' L'.join('%g %g' % point for point in shape[1]) + ('z' if shape[2] else ''))
        else:
            _, cx, cy, r = shape
            parts.append('M%g %ga%g %g 0 1 0 %g 0a%g %g 0 1 0 %g 0' % (cx - r, cy, r, r, 2 * r, r, r, -2 * r))
    return ' '.join(parts)


def catalog():
    return {key: {'label': label, 'path': svg_path(key)} for key, (label, _) in ICONS.items()}


def draw(pdf, key, x, y, size, color=(.08, .25, .47)):
    """Dibuja el icono en un lienzo PDF (document_canvas.Canvas): esquina superior izquierda (x, y) en coordenadas de página, lado `size`."""
    stream, scale, k = pdf.stream, size / 24, .5523
    px, py = (lambda value: x + value * scale), (lambda value: pdf.h - (y + value * scale))
    stream.push_state()
    stream.set_color_rgb(*((0, 0, 0) if getattr(pdf, 'mono', False) else color), stroke=True)
    stream.set_line_width(max(.6, 1.5 * scale))
    stream.set_line_cap(1)
    stream.set_line_join(1)
    for shape in ICONS[valid(key)][1]:
        if shape[0] == L:
            points = shape[1]
            stream.move_to(px(points[0][0]), py(points[0][1]))
            for point in points[1:]:
                stream.line_to(px(point[0]), py(point[1]))
            if shape[2]:
                stream.close()
        else:
            _, cx, cy, r = shape
            stream.move_to(px(cx + r), py(cy))
            for angle in range(4):
                a0, a1 = angle * math.pi / 2, (angle + 1) * math.pi / 2
                stream.curve_to(px(cx + r * (math.cos(a0) - k * math.sin(a0))), py(cy + r * (math.sin(a0) + k * math.cos(a0))),
                                px(cx + r * (math.cos(a1) + k * math.sin(a1))), py(cy + r * (math.sin(a1) - k * math.cos(a1))),
                                px(cx + r * math.cos(a1)), py(cy + r * math.sin(a1)))
        stream.stroke()
    stream.pop_state()
