"""Sistema de controles de selección: reglas que no se ven en una prueba de valores. El visto no puede depender de imágenes data: (las bloquea la
política de seguridad), la exclusión no puede alcanzar al formulario de inicio de sesión y los componentes deben ser globales."""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'static'


class ControlSystemTests(unittest.TestCase):
    def block(self, name):
        css = (STATIC / name).read_text(encoding='utf-8')
        return css[css.index('/* ===== Sistema de controles de selección'):]

    def test_tick_is_drawn_with_css_because_csp_blocks_data_images(self):
        app = (STATIC.parent / 'app.py').read_text(encoding='utf-8')
        self.assertNotRegex(re.search(r'DEFAULT_CSP="[^"]*"', app)[0].split('img-src')[1].split(';')[0], 'data:')
        for name in ('app.css', 'quote.css', 'tracking.css'):
            block = self.block(name)
            self.assertNotIn('data:image', block, name)
            self.assertRegex(block, r':checked::before\{content:""', name)
            self.assertRegex(block, r':indeterminate::before\{content:""', name)

    def test_exclusion_list_does_not_reach_the_login_form(self):
        for name in ('app.css', 'quote.css', 'tracking.css'):
            self.assertNotRegex(self.block(name), r'[,(]\.access-card[,)]', name)

    def test_public_pages_keep_the_same_tokens(self):
        tokens = lambda name: set(re.findall(r'--ctl-[a-z-]+(?=:)', self.block(name)))
        self.assertEqual(tokens('quote.css'), tokens('tracking.css'))
        self.assertLessEqual(tokens('quote.css'), tokens('app.css'))

    def test_components_are_top_level_because_of_strict_mode(self):
        js = (STATIC / 'app.js').read_text(encoding='utf-8')
        for name in ('AppCheckbox', 'AppSwitch', 'AppRadioGroup', 'AppSelectionCard', 'AppTableSelection', 'asSwitch'):
            self.assertRegex(js, r'(?m)^function %s\(' % name, name)
        self.assertLess(js.index('function AppCheckbox('), js.index('const OF_LOOK='))
        self.assertGreater(js.index('function AppCheckbox('), js.index("async function dashboard") if 'async function dashboard' in js else 0)

    def test_selection_of_records_never_uses_a_switch(self):
        js = (STATIC / 'licenses.js').read_text(encoding='utf-8')
        self.assertNotIn("asSwitch(pick)", js)
        self.assertIn('AppTableSelection({ids:()=>slice.map(r=>r.id)', js)


if __name__ == '__main__':
    unittest.main()
