"""Customer Device Intelligence projection and browser regression with fictitious data."""
from datetime import datetime, timedelta, timezone
import unittest

import battery_diagnostics as diagnostics
import customer_device as device
import order_tracking
from test_public_identity_visual import ROOT, contrast, sync_playwright


def reading(value, unit):
    return {'value': value, 'unit': unit, 'status': 'sistema'}


def assessment(percent=85, **advanced):
    return {'status': 'evaluada' if percent is not None else 'pendiente', 'percent': percent,
            'created_at': '2026-11-28T09:30:00-05:00', 'advanced': advanced}


class CustomerDeviceTests(unittest.TestCase):
    def test_independent_safety_and_resolution(self):
        for condition in ('inflamacion', 'corto_sospechado', 'corto_confirmado', 'dano_termico'):
            with self.subTest(condition=condition):
                saved = device.battery_view(assessment(100, hazards=[condition], share=['health']), device.DEFAULTS)
                self.assertEqual(saved['percent'], 100)
                self.assertIn(device.HAZARDS[condition], saved['hazards'])
                with self.assertRaisesRegex(ValueError, 'resolución técnica'):
                    diagnostics.normalize({}, {'hazards': [condition]})
                normalized = diagnostics.normalize({'resolve_safety': True, 'safety_notes': 'Medida ficticia'},
                                                   {'hazards': [condition]})
                self.assertFalse(normalized['hazards'])

    def test_pending_absent_and_new_replacement_with_real_measurement(self):
        cfg = {**device.DEFAULTS, 'cdi_pending': True}
        absent = device.battery_view(assessment(None, condition='absent', share=['physical']), cfg)
        self.assertEqual(absent['evaluation'], 'Batería ausente')
        self.assertIsNone(absent['percent'])
        pending = device.battery_view(assessment(None, hazards=['fuga'], share=['health']), cfg)
        self.assertEqual(pending['evaluation'], 'Medición suspendida por seguridad')
        install = {'date': '2026-11-28', 'kind': 'new', 'before_bp': 6200, 'warranty': '90 días'}
        for percent in (None, 85):
            record = assessment(percent, share=['health', 'replacement'], installation=install)
            result = device.battery_view(record, cfg)
            comparison = dict(result['installation'])
            self.assertEqual(comparison['Garantía'], '90 días')
            if percent is None:
                self.assertEqual(comparison['Reemplazo'], 'Batería instalada — Pendiente de evaluación')
                self.assertNotIn('Después', comparison)
            else:
                self.assertEqual(comparison['Reemplazo'], 'Batería nueva instalada')
                self.assertIn('85 %', comparison['Después'])
                self.assertEqual(comparison['Variación'], '+23 puntos porcentuales')

    def test_additional_authorized_pack_keeps_its_own_percent(self):
        def pack(serial, full, approved):
            return {'identity': {'serial': serial}, 'measured_on': '2026-11-28', 'approved': approved,
                    'readings': {'design': reading('50', 'Wh'), 'full': reading(full, 'Wh')}}
        raw = {'identity': {'serial': 'active-fixture'}, 'share': ['health'],
               'auxiliary': [pack('aux-fixture-one', '35', True), pack('aux-fixture-two', '45', False)]}
        saved = diagnostics.normalize(raw, {})
        result = device.battery_view(assessment(85, **saved), device.DEFAULTS)
        self.assertEqual(result['percent'], 85)
        self.assertEqual([pack['percent'] for pack in result['auxiliary']], [70])
        html = device.render({'battery': result})
        self.assertNotIn('aux-fixture', html)
        with self.assertRaisesRegex(ValueError, 'serie'):
            diagnostics.normalize({**raw, 'auxiliary': [pack('active-fixture', '35', True)]}, {})


@unittest.skipUnless(sync_playwright, 'La regresión visual requiere Chromium.')
class CustomerDeviceVisualTests(unittest.TestCase):
    def test_verified_panel_refresh_and_static_a4(self):
        playwright = self.enterContext(sync_playwright())
        if not ROOT.joinpath(playwright.chromium.executable_path).is_file():
            self.skipTest('Instala Chromium con Playwright.')
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        initial = datetime.now(timezone.utc)
        token = 'seguimiento-ficticio'
        def projection(percent):
            return {'device': [('Tipo', 'Portátil'), ('Serie', '••••1984')], 'kind': 'portatil',
                    'battery': device.battery_view(assessment(percent, share=['health'], hazards=['inflamacion']),
                                                   device.DEFAULTS)}
        initial_info = projection(85)
        document = order_tracking.public_page({
            'code': 'OP-FICTICIA', 'status': 'diagnostico', 'status_label': 'Diagnóstico',
            'customer_device': initial_info, 'customer_device_print': True,
            'customer_device_checked': initial.isoformat(),
            'customer_device_expiry': (initial + timedelta(minutes=15)).isoformat(),
        }, token, portal=True)
        for width in (320, 390, 768, 1280):
            with self.subTest(width=width):
                page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                self.addCleanup(page.close)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def route_asset(route):
                    from urllib.parse import urlsplit
                    path = urlsplit(route.request.url).path
                    if path.endswith('/cuenta/ficha'):
                        value = projection(61)
                        return route.fulfill(json={'html': device.render(value), 'print': device.render(value, printing=True),
                                                   'snapshot': 'fixture-next', 'checked_at': initial.isoformat()})
                    if path.startswith('/static/'):
                        file = ROOT / 'static' / path.removeprefix('/static/')
                        if file.is_file():
                            return route.fulfill(path=file)
                    return route.fulfill(content_type='text/html', body=document)
                page.route('**/*', route_asset)
                page.clock.install()
                page.goto('http://customer.test/s/' + token + '/cuenta/seguimiento')
                screen = page.locator('.cdi-screen')
                self.assertIn('85 %', screen.locator('.equip-battery-percent').inner_text())
                self.assertEqual(screen.locator('.equip-battery-slot').count(),5)
                self.assertTrue(screen.get_by_role('alert').is_visible())
                columns = screen.evaluate('el=>getComputedStyle(el).gridAutoFlow')
                self.assertEqual(columns, 'row' if width < 621 else 'column')
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                fg,bg=screen.get_by_role('alert').evaluate('el=>[getComputedStyle(el).color,getComputedStyle(el).backgroundColor]')
                self.assertGreater(contrast(fg,bg),4.5)
                page.clock.fast_forward(46_000)
                page.wait_for_function("document.querySelector('.cdi-screen [data-cdi-battery]').dataset.cdiBattery==='61'")
                page.emulate_media(media='print')
                print_view=page.locator('.cdi-print')
                self.assertTrue(print_view.is_visible())
                self.assertFalse(screen.is_visible())
                self.assertEqual(print_view.locator('.equip-battery-slot').count(),5)
                self.assertIn('61 %',print_view.locator('.equip-battery-percent').inner_text())
                self.assertFalse(errors, errors)
