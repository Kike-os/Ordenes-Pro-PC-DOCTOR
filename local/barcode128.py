"""Código de barras Code 128 (juego B) en SVG, sin dependencias.

Codifica el identificador real de la orden (letras, cifras y guiones). El SVG es vectorial: se lee igual en pantalla y al imprimir."""

# Anchos de barras y espacios de los 107 símbolos (barra, espacio, barra, espacio, barra, espacio); el último es la parada.
PATTERNS = ('212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 221312 231212 112232 122132 122231 113222 123122 123221 '
            '223211 221132 221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 212123 212321 232121 111323 131123 131321 '
            '112313 132113 132311 211313 231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 231131 213113 213311 213131 '
            '311123 311321 331121 312113 312311 332111 314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 112412 122114 '
            '122411 142112 142211 241211 221114 413111 241112 134111 111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 '
            '214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 114131 311141 411131 211412 211214 211232 2331112').split()
START_B, STOP = 104, 106


class BarcodeError(ValueError):
    pass


def symbols(text):
    """Símbolos de Code 128-B para el texto: inicio, datos, dígito de control (módulo 103) y parada."""
    if not text or len(text) > 48 or any(not 32 <= ord(char) <= 126 for char in text):
        raise BarcodeError('El identificador solo admite caracteres ASCII imprimibles (hasta 48).')
    values = [ord(char) - 32 for char in text]
    check = (START_B + sum(value * position for position, value in enumerate(values, 1))) % 103
    return [START_B, *values, check, STOP]


def modules(text):
    """Secuencia de módulos (1 = barra, 0 = espacio), sin zonas de silencio."""
    bits = []
    for symbol in symbols(text):
        for index, width in enumerate(PATTERNS[symbol]):
            bits.extend([1 - index % 2] * int(width))
    return bits


def svg(text, height=56, quiet=10, color='#000000', background='#ffffff'):
    """SVG con zona de silencio a ambos lados. Un módulo mide una unidad; el tamaño real lo decide quien lo muestra."""
    bits = modules(text)
    width = len(bits) + 2 * quiet
    bars, start = [], None
    for position, bit in enumerate(bits + [0]):
        if bit and start is None:
            start = position
        elif not bit and start is not None:
            bars.append('<rect x="%d" y="0" width="%d" height="%d"/>' % (start + quiet, position - start, height))
            start = None
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" preserveAspectRatio="none" role="img" aria-label="Código de barras %s" shape-rendering="crispEdges">'
            '<rect width="%d" height="%d" fill="%s"/><g fill="%s">%s</g></svg>') % (width, height, width * 2, height, text.replace('&', '').replace('<', '').replace('"', ''), width, height, background, color, ''.join(bars))
