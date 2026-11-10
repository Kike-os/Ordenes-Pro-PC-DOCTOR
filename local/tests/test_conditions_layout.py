"""Condiciones de Recepción y Servicios (1.5.271): numeración por cláusula y cortes de página profesionales.

Se lee el PDF real generado (texto y posición de cada línea por página). Textos ficticios para pruebas; ningún documento se publica."""
import re
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conditions_pdf  # noqa: E402
import service_terms  # noqa: E402

LOREM = ('El texto de esta cláusula es ficticio y sirve solo para comprobar la distribución del documento en páginas A4 sin '
         'cortes incorrectos, con separación uniforme y sin números adicionales en los párrafos internos. ')
TITLES = ['IDENTIFICACIÓN Y RECEPCIÓN DEL EQUIPO', 'ALCANCE DEL DIAGNÓSTICO', 'DATOS PERSONALES, PRIVACIDAD Y CONTRASEÑAS',
          'RESPALDOS, FORMATEO Y PÉRDIDA DE INFORMACIÓN', 'FALLAS PREEXISTENTES Y EVIDENCIA', 'PRESUPUESTOS Y TRABAJOS ADICIONALES',
          'REPUESTOS Y DISPONIBILIDAD', 'PLAZOS Y CAMBIOS DE ESTADO', 'PAGOS Y SALDOS', 'GARANTÍA Y NUEVAS INCIDENCIAS',
          'PERMANENCIA Y ALMACENAMIENTO', 'COMUNICACIONES Y AVISOS', 'ENTREGA DEL EQUIPO', 'ACEPTACIONES DIGITALES Y AUDITORÍA',
          'RECLAMOS, CORRECCIONES Y ATENCIÓN']


def fifteen():
    """15 cláusulas con 2 a 4 párrafos cada una, como el documento ampliado (párrafos internos sin número)."""
    blocks = []
    for n, title in enumerate(TITLES, 1):
        paras = [LOREM * (1 + (n % 3)) for _ in range(2 + n % 3)]
        blocks.append('%d. %s\n%s' % (n, title.title(), paras[0]))
        blocks.extend(paras[1:])
    return '\n\n'.join(blocks)


def pages(pdf):
    """[[(y_desde_arriba, texto)]] por página, en orden."""
    out = []
    for m in re.finditer(rb'/Length (\d+)[^>]*>>\s*stream\r?\n', pdf):
        raw = pdf[m.end():m.end() + int(m[1])]
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            continue
        if b' Tj' not in data:
            continue
        lines = [(841.89 - float(y), re.sub(rb'\\(.)', rb'\1', t).decode('cp1252')) for y, t in re.findall(rb'1 0 0 1 [\d.]+ ([\d.]+) Tm\s*\(((?:\\.|[^\\)])*)\)\s*Tj', data)]
        out.append(lines)
    return out


class ConditionsLayoutTests(unittest.TestCase):
    def render(self, text, draft=True):
        return pages(conditions_pdf.render_conditions({'version': 'BORRADOR-PRUEBA', 'full_text': text, 'draft': draft, 'effective_date': '2026-11-10'}))

    def body_lines(self, page):
        # Texto de las cláusulas: entre el encabezado y el pie, excluyendo títulos (mayúsculas) y números de recuadro.
        end = next((y for y, t in page if t == 'ACEPTACIÓN Y VERSIÓN'), conditions_pdf.BOTTOM)  # el recuadro de cierre tiene otro interlineado
        return [(y, t) for y, t in page if 118 <= y < min(end, conditions_pdf.BOTTOM) and not t.isupper() and not t.isdigit() and 'continuación' not in t]

    def test_clause_parser_groups_continuation_paragraphs(self):
        parsed = service_terms.clauses(fifteen())
        self.assertEqual([c['number'] for c in parsed], list(range(1, 16)))
        self.assertTrue(all(len(c['paragraphs']) >= 2 for c in parsed))
        # Formato vigente (una cláusula por bloque) y texto compacto (párrafos numerados sin título): sin cambios.
        legacy = '1. Diagnóstico\nTexto uno.\n\n2. Datos personales\nTexto dos.'
        self.assertEqual([(c['number'], c['title'], c['paragraphs']) for c in service_terms.clauses(legacy)], [(1, 'Diagnóstico', ['Texto uno.']), (2, 'Datos personales', ['Texto dos.'])])
        compact = '1. Primera regla del ticket.\n\n2. Segunda regla del ticket.'
        self.assertEqual([(c['number'], c['title']) for c in service_terms.clauses(compact)], [(1, ''), (2, '')])
        # Una línea que termina en punto no es un título: es un párrafo numerado sin título.
        self.assertEqual(service_terms.clauses('1. Frase completa.\nCon segunda línea.')[0]['title'], '')

    def test_fifteen_clauses_have_one_number_each_and_no_inner_numbers(self):
        result = self.render(fifteen())
        flat = [t for p in result for _, t in p]
        self.assertEqual([t for t in flat if t in TITLES], TITLES)
        self.assertEqual([t for t in flat if t.isdigit() and 1 <= int(t) <= 15], [str(n) for n in range(1, 16)])
        for page in result:
            for _, t in self.body_lines(page):
                self.assertIsNone(re.match(r'^\d{1,2}\. ', t), t)
        self.assertGreater(len(result), 2)

    def test_titles_stay_with_their_text_and_no_widows_or_orphans(self):
        result = self.render(fifteen())
        line = 12.8
        for number, page in enumerate(result, 1):
            ys = sorted(y for y, _ in self.body_lines(page))
            for i, (y, t) in enumerate(page):
                if t in TITLES:
                    after = [v for v in ys if v > y]
                    self.assertGreaterEqual(len(after), 2, 'Título solo al pie: %s (página %d)' % (t, number))
            # Bloques de líneas consecutivas (un párrafo o su parte en esta página): ninguno de una sola línea si el párrafo continúa.
            runs, run = [], [ys[0]] if ys else []
            for a, b in zip(ys, ys[1:]):
                if abs(b - a - line) < .5:
                    run.append(b)
                else:
                    runs.append(run)
                    run = [b]
            if run:
                runs.append(run)
            if number < len(result) and runs:
                self.assertGreaterEqual(len(runs[-1]), 2, 'Línea huérfana al pie de la página %d' % number)
            if number > 1 and runs:
                self.assertGreaterEqual(len(runs[0]), 2, 'Línea viuda al comienzo de la página %d' % number)
            self.assertTrue(all(y < 841.89 - 10 for y, _ in page))

    def test_long_clause_continues_on_next_page_instead_of_failing(self):
        text = '1. Cláusula extensa de prueba\n' + LOREM * 30 + '\n\n2. Otra cláusula\nTexto breve.'
        result = self.render(text)
        self.assertGreaterEqual(len(result), 2)
        self.assertIn('OTRA CLÁUSULA', [t for p in result for _, t in p])
        self.assertTrue(any('continuación' in t for _, t in result[1]))

    def test_published_eight_clause_format_is_unchanged(self):
        text = '\n\n'.join('%d. Título %d\n%s' % (n, n, LOREM) for n in range(1, 9))
        result = self.render(text, draft=False)
        flat = [t for p in result for _, t in p]
        self.assertEqual([t for t in flat if t.startswith('TÍTULO')], ['TÍTULO %d' % n for n in range(1, 9)])
        self.assertEqual(len(result), 1)

    def test_public_page_keeps_continuation_inside_the_same_clause(self):
        page = service_terms.public_page({'title': 'Condiciones', 'version': 'X', 'effective_date': '2026-11-10', 'content_hash': 'a' * 64,
                                          'full_text': '1. Uno\nPrimero.\n\nSegundo párrafo.\n\n2. Dos\nTercero.'})
        self.assertEqual(page.count('<li value='), 2)
        self.assertIn('<li value="1"><p>Uno<br>Primero.</p><p>Segundo párrafo.</p></li>', page)


if __name__ == '__main__':
    unittest.main()
