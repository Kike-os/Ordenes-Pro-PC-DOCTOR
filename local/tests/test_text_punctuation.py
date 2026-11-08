"""Puntuación de los textos con fecha (1.5.258): la hora ya termina en «p. m.» / «a. m.», así que una frase que acaba en una fecha
no debe agregar otro punto («09:21 p. m..»). Se usa withPeriod, que lo agrega solo si falta."""
import re
import unittest
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / 'static' / 'app.js').read_text()


class DatePunctuationTests(unittest.TestCase):
    def test_dates_never_get_a_second_period(self):
        self.assertEqual(re.findall(r"format\w*Date\([^)]*\)\+'\.'", JS), [])
        self.assertIn("withPeriod(formatOrderDate(imap.checked))", JS)
        self.assertIn('function withPeriod(text)', JS)


if __name__ == '__main__':
    unittest.main()
