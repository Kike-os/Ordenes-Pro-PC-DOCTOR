"""1.5.280 · Inicio de sesión PREMIUM COMPACTO: mismo contenido y mismas funciones con menos altura. El logotipo original no cambia;
el aviso legal completo sigue en la página (desplegable) con el © visible; el panel de versión conserva todos sus controles; los accesos
públicos quedan dentro de la tarjeta; el inicio de sesión sigue funcionando."""
import re
import unittest
import test_app


class LoginCompactTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def page(self):
        body=self.request('/login')['body'];return body.decode() if isinstance(body,bytes) else body

    def test_structure_keeps_everything_and_puts_public_access_inside_the_card(self):
        page=self.page()
        card=page[page.index('<section class="access-card"'):page.index('</main>')]
        self.assertIn('src="/static/logo-original.png"',card)
        order=[card.index(x) for x in ('class="original-logo"','<h1 id="access-title">','class="brand-sub"','class="lang-pick"','id="login"','id="password"','class="form-options"','class="primary submit"','class="login-ip"','id="system-version"','class="login-public"')]
        self.assertEqual(order,sorted(order))
        self.assertIn('href="/citas"',card);self.assertIn('href="/pqrs"',card)
        legal=card[card.index('class="login-ip"'):card.index('</aside>')]
        self.assertIn('<details class="login-ip-more">',legal)
        for text in ('Software privado · Propiedad intelectual protegida','Se prohíbe su reproducción, distribución, comercialización, modificación o acceso no autorizado al código fuente.','© 2026 PC-DOCTOR S.A. | Todos los derechos reservados.'):self.assertIn(text,legal)
        self.assertLess(legal.index('</details>'),legal.index('© 2026'))  # el © no queda escondido en el desplegable
        for ident in ('system-version-number','system-version-status','system-version-toggle','system-version-more','system-version-news','system-version-retry','system-version-reload','stability-login','system-version-checked'):
            self.assertRegex(card,r'id="%s"'%ident)
        self.assertRegex(card,r'aria-controls="system-version-more"[^>]*>|aria-expanded="false" aria-controls="system-version-more"')
        self.assertNotRegex(page,r'<script[^>]+defer[^>]+/static/i18n\.js')
        self.login()


if __name__=='__main__':unittest.main()
