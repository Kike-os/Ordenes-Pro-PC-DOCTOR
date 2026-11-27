"""Browser regression for the public identity component, with synthetic data."""
from datetime import datetime
import mimetypes
import re
from pathlib import Path
import sys
import time
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import client_authorization
import client_portal
import license_pages
import order_tracking
import proformas
import quote_page

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def luminance(rgb):
    channels = (int(number) / 255 for number in re.findall(r'\d+', rgb)[:3])
    return sum(weight * (value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4)
               for weight, value in zip((.2126, .7152, .0722), channels))


def contrast(foreground, background):
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + .05) / (dark + .05)


@unittest.skipUnless(sync_playwright, 'La regresión visual requiere Python Playwright y Chromium.')
class PublicIdentityVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        if not Path(cls.playwright.chromium.executable_path).is_file():
            raise unittest.SkipTest('Instala Chromium mediante playwright install chromium.')
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)
        token = 'identidad-ficticia'
        order = {'code': 'OP-FICTICIA', 'identification': '1790016919001', 'document_type': 'ruc'}
        now_ms = int(time.time() * 1000)
        tracking = order_tracking._cancel_block(
            {'id': 1, 'can_cancel': True, 'cancel_window': {
                'now_ms': now_ms, 'deadline_ms': now_ms + 3600000, 'remaining': 3600}},
            token, 'ruc')
        tracking_shell = order_tracking.CARD_HEAD % ('', 'OP-FICTICIA', '')
        cls.pages = {
            '/proforma': proformas.identify_page(token, {'code': 'PF-FICTICIA', 'client_identification': '1710034065',
                                                        'client_document_type': 'cedula'}),
            '/presupuesto': quote_page.identify_page(token, {'code': 'P-FICTICIO', 'status': 'enviado'}, order),
            '/autorizar': client_authorization.identify_page(token, order),
            '/licencias': license_pages.identify_page(token, document_kind='ruc'),
            '/seguimiento': tracking_shell + tracking + '</main></body></html>',
            '/citas': (ROOT / 'templates/appointments.html').read_text(encoding='utf-8'),
            '/cuenta': client_portal.form_page(token, order['code'], document_kind='ruc'),
            '/entrega': client_portal.account_page(token, {
                'order': dict(order, client='Cliente ficticio', brand='', model='', status_label='Entregado', status='entregado'),
                'money': {'credit_cents': 0, 'budget_cents': 100, 'paid_cents': 100, 'balance_cents': 0},
                'checked_at': datetime(2026, 1, 1), 'delivered': True, 'invoices': [], 'payments': [],
            }, client_portal.DEFAULTS),
        }
        cls.pages['/claro'] = cls.pages['/cuenta'].replace('<html ', '<html data-theme="light" ', 1)

    def open_page(self, path, width, *, motion='reduce'):
        page = self.browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion=motion)
        self.addCleanup(page.close)
        page.set_default_timeout(4000)

        def serve(route):
            location = urlsplit(route.request.url).path
            if location.startswith('/static/'):
                file = ROOT / 'static' / location.removeprefix('/static/')
                if file.is_file() and file.is_relative_to(ROOT / 'static'):
                    return route.fulfill(path=str(file), content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
            if location == '/api/public/appointments/services':
                return route.fulfill(json={'device_types': {}, 'brand_logos': {}, 'services': []})
            return route.fulfill(content_type='text/html', body=self.pages.get(location, ''))

        page.route('**/*', serve)
        page.goto('https://identity.example.invalid' + path)
        if path == '/seguimiento':
            page.locator('.tp-cancel > summary').click()
        if path == '/citas':
            page.evaluate("""() => {
                document.querySelectorAll('.booking-panel').forEach(panel => {
                    panel.hidden = panel.dataset.panel !== '3';
                });
                const type = document.querySelector('select[name=document_type]');
                type.value = 'ruc';
                type.dispatchEvent(new Event('change'));
            }""")
        return page

    def test_dark_surfaces_and_contrast_on_every_host(self):
        for width in (320, 390, 768, 1280):
            for path in sorted(self.pages.keys() - {'/claro', '/entrega'}):
                with self.subTest(width=width, path=path):
                    page = self.open_page(path, width)
                    panel = page.locator('.public-identity-panel')
                    self.assertTrue(panel.is_visible())
                    background = panel.evaluate('e => getComputedStyle(e).backgroundColor')
                    self.assertLess(luminance(background), .1)
                    for selector in ('label', '.public-identity-digits input, .public-identity-value:not([type=hidden])'):
                        colors = panel.locator(selector).first.evaluate(
                            'e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor]')
                        element_bg = background if colors[1] == 'rgba(0, 0, 0, 0)' else colors[1]
                        self.assertLess(luminance(element_bg), .1)
                        self.assertGreaterEqual(contrast(colors[0], element_bg), 4.5)
                    fields = panel.locator('.public-identity-digits input')
                    self.assertEqual(fields.count(), 0 if path == '/licencias' else 4)
                    shield = panel.locator('.public-identity-shield')
                    if shield.count():
                        self.assertEqual(shield.evaluate('e => getComputedStyle(e).animationName'), 'none')
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.close()

    def test_theme_opt_in_and_portal_delivery_surface(self):
        light = self.open_page('/claro', 768)
        panel = light.locator('.public-identity-panel')
        self.assertGreater(luminance(panel.evaluate('e => getComputedStyle(e).backgroundColor')), .8)
        delivery = self.open_page('/entrega', 320)
        self.assertTrue(delivery.get_by_text('Comprobante de entrega del equipo').is_visible())
        self.assertLess(luminance(delivery.locator('.portal-card').first.evaluate('e => getComputedStyle(e).backgroundColor')), .1)

    def test_document_copy_keyboard_advance_and_paste(self):
        for path, instruction in (('/proforma', 'cédula registrada'), ('/cuenta', 'RUC registrado')):
            with self.subTest(path=path):
                page = self.open_page(path, 390)
                self.assertTrue(page.get_by_text('Ingresa los últimos 4 dígitos de tu ' + instruction).is_visible())
                fields = page.locator('.public-identity-digits input')
                fields.nth(0).press('0')
                self.assertTrue(fields.nth(1).evaluate('e => e === document.activeElement && getComputedStyle(e).outlineStyle !== "none"'))
                fields.nth(1).evaluate("""field => {
                    const clipboardData = new DataTransfer();
                    clipboardData.setData('text/plain', '0427');
                    field.dispatchEvent(new ClipboardEvent('paste', {clipboardData, bubbles: true, cancelable: true}));
                }""")
                self.assertEqual(page.locator('input[name=last4]').input_value(), '0427')
                self.assertTrue(all(field.get_attribute('inputmode') == 'numeric' for field in fields.all()))
