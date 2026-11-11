"""Idiomas de la interfaz (1.5.273). Base temporal y cuentas ficticias.

Cubre: preferencia de idioma por cuenta (solo valores conocidos, con sesión y CSRF, sin afectar a otras cuentas), /api/me la devuelve,
el módulo i18n.js se sirve y se carga antes de app.js en las páginas de acceso y en el panel, el selector de idioma de la pantalla de
acceso y que los catálogos es-EC y en-US tienen las mismas claves y los textos pedidos."""
import json
import pathlib
import re
import subprocess
import shutil
import time
import unittest

import test_app  # primero: prepara la ruta de importación y la base temporal
import app

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')
STATIC = pathlib.Path(app.__file__).resolve().parent / 'static'
TEMPLATES = pathlib.Path(app.__file__).resolve().parent / 'templates'


class LanguageTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def test_account_language_is_validated_saved_and_returned(self):
        cookie, csrf = self.login()
        self.assertIsNone(self.request('/api/me', cookie=cookie)['body']['user']['lang'])  # español por defecto (sin preferencia)
        self.assertEqual(self.request('/api/me/language', {'lang': 'fr-FR'}, cookie=cookie, csrf=csrf)['status'], 400)
        self.assertEqual(self.request('/api/me/language', {'lang': 'en-US'}, cookie=cookie)['status'], 403)  # sin CSRF
        self.assertEqual(self.request('/api/me/language', {'lang': 'en-US'})['status'], 401)  # sin sesión
        ok = self.request('/api/me/language', {'lang': 'en-US'}, cookie=cookie, csrf=csrf)
        self.assertEqual((ok['status'], ok['body']['lang']), (200, 'en-US'))
        self.assertEqual(self.request('/api/me', cookie=cookie)['body']['user']['lang'], 'en-US')
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='ui_language'").fetchone()[0], 1)
            other = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico2','tec2@example.invalid','Técnico ficticio',?,'tecnico',?)", (self.hash, int(time.time()))).lastrowid
            c.commit()
            self.assertIsNone(c.execute('SELECT value FROM system_state WHERE key=?', ('ui_lang:%d' % other,)).fetchone())
            # Un valor manipulado en la base no se devuelve.
            c.execute("UPDATE system_state SET value='xx' WHERE key=?", ('ui_lang:%d' % self.uid,));c.commit()
        self.assertIsNone(self.request('/api/me', cookie=cookie)['body']['user']['lang'])
        self.assertEqual(self.request('/api/me/language', {'lang': 'es-EC'}, cookie=cookie, csrf=csrf)['body']['lang'], 'es-EC')

    def test_login_still_works_and_pages_load_i18n_before_app(self):
        self.login()  # el inicio de sesión no cambia
        script = self.request('/static/i18n.js')
        self.assertEqual(script['status'], 200)
        for name in ('login.html', 'forgot.html', 'reset.html', 'dashboard.html'):
            html = (TEMPLATES / name).read_text()
            self.assertLess(html.index('/static/i18n.js'), html.index('/static/app.js'), name)
            self.assertNotRegex(html, r'<script[^>]*defer[^>]*src="/static/i18n.js"', name)  # sin defer: se aplica antes de mostrar
        login = (TEMPLATES / 'login.html').read_text()
        self.assertIn('Seleccione su idioma / Select your language', login)
        self.assertIn('data-lang="es-EC" aria-pressed="true"', login)
        self.assertIn('data-lang="en-US" aria-pressed="false"', login)
        self.assertIn('/static/flags/EC.svg', login);self.assertIn('/static/flags/US.svg', login)
        self.assertIn('src="/static/logo-original.png"', login)  # logo original sin cambios

    def test_catalogs_match_and_include_requested_texts(self):
        source = (STATIC / 'i18n.js').read_text()
        def table(lang):
            block = re.search(r"\n '%s':\{(.*?)\n \}" % re.escape(lang), source, re.S).group(1)
            return dict(re.findall(r"'([\w.]+)':'((?:\\'|[^'])*)'", block))
        es, en = table('es-EC'), table('en-US')
        self.assertEqual(set(es), set(en))
        self.assertGreater(len(es), 40)
        wanted = {'brand.tagline': ('Sistema de Gestión de Reparaciones', 'Repair Management System'), 'login.user': ('Usuario o correo electrónico', 'Username or Email'),
                  'login.password': ('Contraseña', 'Password'), 'login.remember': ('Recordar mi sesión', 'Remember me'),
                  'login.forgot': ('¿Olvidaste tu contraseña?', 'Forgot your password?'), 'login.submit': ('Iniciar sesión', 'Sign In'),
                  'login.book': ('Agendar cita', 'Book Appointment'), 'version.title': ('Versión del sistema', 'System Version'), 'version.news': ('Actualizaciones del sistema', 'System Updates')}
        for key, (spanish, english) in wanted.items():
            self.assertEqual((es[key], en[key]), (spanish, english), key)
        for phrase, english in (("'Sistema actualizado':'System Up to Date'", None), ("'En observación':'Under Observation'", None)):
            self.assertIn(phrase, source)
        # Cada clave usada en las plantillas existe en el catálogo.
        for name in ('login.html', 'forgot.html', 'reset.html', 'dashboard.html'):
            html = (TEMPLATES / name).read_text()
            keys = set(re.findall(r'data-i18n="([\w.]+)"', html)) | {k for attr in re.findall(r'data-i18n-attr="([^"]+)"', html) for k in re.findall(r':([\w.]+)', attr)}
            self.assertTrue(keys, name)
            self.assertFalse(keys - set(es), (name, keys - set(es)))

    @unittest.skipUnless(shutil.which('node'), 'node no disponible')
    def test_runtime_translation_rules(self):
        """Ejecuta i18n.js en Node con un DOM mínimo: traduce mensajes conocidos y patrones, y deja intacto lo desconocido."""
        harness = r"""
const store={'ordenes-pro:idioma':'en-US'};globalThis.localStorage={getItem:k=>store[k]??null,setItem:(k,v)=>{store[k]=String(v)},removeItem:k=>{delete store[k]}};
const html={lang:'',dataset:{},classList:{add(){},remove(){}}};
globalThis.document={documentElement:html,readyState:'complete',querySelectorAll:()=>[],addEventListener(){},dispatchEvent(){}};globalThis.window=globalThis;globalThis.CustomEvent=class{constructor(n,o){this.type=n;this.detail=o?.detail}};
require(process.argv[1]);const i=window.i18n;
const out={lang:i.lang,html:html.lang,
 a:i.tr('No pudimos iniciar sesión. Verifica tus credenciales e inténtalo nuevamente.'),
 b:i.tr('Por seguridad, espera 1 segundo antes de volver a intentarlo.'),c:i.tr('Por seguridad, espera 30 segundos antes de volver a intentarlo.'),
 d:i.tr('✓ Formato de correo válido.'),e:i.tr('Publicada el 10/11/2026'),f:i.tr('Sistema actualizado · comprobado a las 07:31 AM'),
 g:i.tr('Juan Pérez · Calle Bolívar 12'),h:i.tr('SN-ABC123'),k:i.t('login.submit'),pending:(i.set('es-EC',{account:'pending'}),i.pending()),es:i.tr('Contraseña introducida.')};
console.log(JSON.stringify(out));"""
        result = subprocess.run(['node', '-e', harness, str(STATIC / 'i18n.js')], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual((out['lang'], out['html']), ('en-US', 'en-US'))
        self.assertEqual(out['a'], 'We could not sign you in. Check your credentials and try again.')
        self.assertEqual(out['b'], 'For security, wait 1 second before trying again.')
        self.assertEqual(out['c'], 'For security, wait 30 seconds before trying again.')
        self.assertEqual(out['d'], '✓ Valid email format.')
        self.assertEqual(out['e'], 'Published on 11/10/2026')
        self.assertEqual(out['f'], 'System Up to Date · checked at 07:31 AM')
        self.assertEqual((out['g'], out['h']), ('Juan Pérez · Calle Bolívar 12', 'SN-ABC123'))  # datos de clientes y códigos intactos
        self.assertEqual(out['k'], 'Sign In')
        self.assertEqual(out['pending'], 'es-EC')
        self.assertEqual(out['es'], 'Contraseña introducida.')  # en español no se toca nada


if __name__ == '__main__':
    unittest.main()
