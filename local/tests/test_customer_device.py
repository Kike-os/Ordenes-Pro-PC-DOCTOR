"""Customer Device Intelligence projection and browser regression with fictitious data."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import os
import unittest

from test_public_identity_visual import ROOT, contrast, sync_playwright

import battery_diagnostics as diagnostics
import customer_device as device
import order_tracking
import order_part_requests
import part_route
import repair_stages
from app import qr_image


def reading(value, unit):
    return {'value': value, 'unit': unit, 'status': 'sistema'}


def assessment(percent=85, **advanced):
    return {'status': 'evaluada' if percent is not None else 'pendiente', 'percent': percent,
            'created_at': '2026-11-28T09:30:00-05:00', 'advanced': advanced}


class CustomerDeviceTests(unittest.TestCase):
    def test_original_logo_and_international_plane(self):
        route = order_part_requests.route_map('internacional', 'transito_internacional',
                                              {'despachado'}, {}, False, 'normal', public=True)
        logistics = part_route.render(route, 'p1', 'Repuesto de demostración')
        self.assertIn('animateMotion', logistics)
        self.assertEqual(sha256(logistics.encode()).hexdigest(),
                         '085cc0a3ce93549c00a1d975efb248e7b5b17ac10442de2bc04a096d7732ef09')
        css = ROOT.joinpath('static', 'ticket.css').read_text()
        animation_css = '\n'.join(line for line in css.splitlines() if 'lgx' in line)
        self.assertEqual(sha256(animation_css.encode()).hexdigest(),
                         '9844fd0d6445bf9f8ef04fda4ce72330948e864b8f04569069ed93127098e5d5')
        self.assertEqual(sha256(ROOT.joinpath('static', 'logo-original.png').read_bytes()).hexdigest(),
                         'c1621de6b1a7e266d67dbd16b834835704e89f6d6274f249c5ed7fb3ccc66f3a')

    def test_in_review_and_projected_advisor_never_expose_private_fields(self):
        cfg = {**device.DEFAULTS, 'cdi_pending': True, 'cdi_electrical': True, 'cdi_warranty': False}
        pending = device.battery_view(assessment(None, in_review=True, share=['explanation']), cfg)
        self.assertEqual(pending['evaluation'], 'En evaluación')
        self.assertIsNone(pending['percent'])
        saved = device.battery_view(assessment(
            85, share=['explanation', 'replacement', 'electrical'],
            readings={'battery_nominal': reading('97.543', 'V')},
            findings={'bms': {'status': 'resuelto', 'notes': 'NOTA INTERNA FICTICIA'}},
            installation={'kind': 'new', 'date': '2026-11-28', 'warranty': 'GARANTÍA OCULTA'},
        ), cfg)
        markup = device.render({'battery': saved})
        self.assertIn('Falla del BMS (resuelto)', markup)
        for private in ('97.543', 'NOTA INTERNA FICTICIA', 'GARANTÍA OCULTA', '85 %'):
            self.assertNotIn(private, markup)

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
        cfg = {**device.DEFAULTS, 'cdi_pending': True, 'cdi_physical': True}
        self.assertFalse(device.battery_view(assessment(in_review=True, percent=None, share=['health']), device.DEFAULTS))
        self.assertFalse(device.battery_view(assessment(None, condition='absent', share=['physical']), device.DEFAULTS))
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
                self.assertEqual(result['comparison'], [('Batería anterior', 62)])
            else:
                self.assertEqual(comparison['Reemplazo'], 'Batería nueva instalada')
                self.assertEqual(result['comparison'], [('Batería anterior', 62), ('Batería instalada', 85)])
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
            return {'device': [('Tipo', 'Portátil'), ('Serie', '••••1984'), ('Recepción', '2026-11-28')], 'kind': 'portatil',
                    'battery': device.battery_view(assessment(percent, share=['health'], hazards=['inflamacion']),
                                                   device.DEFAULTS)}
        when = '2026-11-28T09:30:00-05:00'
        current = 2
        stages = []
        for index, (code, label, icon) in enumerate(repair_stages.STAGES):
            state = 'done' if index < current else 'current' if index == current else 'pending'
            stages.append({'code': code, 'label': label, 'icon': icon, 'state': state,
                           'at': when if index <= current else '', 'word': repair_stages.WORD[state]})
        repair = {'stages': stages, 'current': current, 'done': current, 'total': len(stages), 'finished': False,
                  'status': 'reparacion', 'status_label': 'En reparación', 'percent': round(100*current/len(stages)),
                  'current_label': stages[current]['label'], 'next_label': stages[current+1]['label'], 'notices': [], 'alerts': []}
        route = order_part_requests.route_map('internacional', 'transito_internacional', {'despachado'}, {}, False, 'normal', public=True)
        part = {'id': 1, 'name': 'Repuesto de demostración', 'brand': '', 'stage': 'transito', 'situation': 'normal',
                'tone': 'azul', 'status_label': 'En tránsito', 'step_label': 'Transporte aéreo', 'description': 'Despacho de prueba.',
                'map_html': part_route.render(route,'p1','Repuesto de demostración'), 'map': route, 'shipping':'internacional',
                'vehicle': '', 'waiting': True, 'updated': when, 'requested': when, 'eta': '', 'received': '',
                'history': [], 'done_count': 1, 'total': 3,
                'steps': [{'state': state, 'label': label, 'code': key, 'at': when if state == 'done' else '', 'color': index}
                          for index, (state,label,key) in enumerate((('done','Pedido','confirmado'),('current','En tránsito','aereo'),('pending','Recepción','recibido')))]}
        initial_info = projection(85)
        initial_info.update({'quote': {'status':'enviado'}, 'base': f'/s/{token}/cuenta'})
        initial_info['report'] = [('Comprobaciones posteriores', [('2026-11-28T09:30', 'Arranque comprobado en el equipo ficticio.')])]
        document = order_tracking.public_page({
            'code': 'OP-FICTICIA', 'status': 'reparacion', 'status_label': 'En reparación', 'repair': repair, 'parts': [part], 'signature': 'fixture-progress',
            'received': '28/11/2026 09:30', 'updated': '28/11/2026 09:30', 'device': 'Portátil de demostración',
            'customer_device': initial_info, 'customer_device_print': True,
            'customer_device_checked': initial.isoformat(),
            'customer_device_expiry': (initial + timedelta(minutes=15)).isoformat(),
        }, token, portal=True)
        captures = os.getenv('CDI_CAPTURE_DIR')
        sizes = ((1920,1080), (1366,768), (1280,720), (768,1024), (390,844)) if captures else ((320,900),(390,900),(768,900),(1280,900))
        for width, height in sizes:
            with self.subTest(width=width):
                page = browser.new_page(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                self.addCleanup(page.close)
                errors = []
                polls = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def route_asset(route):
                    from urllib.parse import urlsplit
                    path = urlsplit(route.request.url).path
                    if path.endswith('/cuenta/ficha'):
                        polls.append(path)
                        if len(polls) == 1:
                            return route.fulfill(status=503)
                        value = {**projection(61), 'device': []}
                        return route.fulfill(json={'html': device.render(value), 'print': device.render(value, printing=True),
                                                   'snapshot': 'fixture-next', 'checked_at': initial.isoformat()})
                    if path.endswith('/estado'):
                        return route.fulfill(json={'v':'fixture-progress'})
                    if path.endswith('/qr.svg'):
                        return route.fulfill(body=qr_image('https://customer.test/s/'+token,'svg'),content_type='image/svg+xml')
                    if path.startswith('/static/'):
                        file = ROOT / 'static' / path.removeprefix('/static/')
                        if file.is_file():
                            return route.fulfill(path=file)
                    return route.fulfill(content_type='text/html', body=document)
                page.route('**/*', route_asset)
                page.clock.install()
                page.goto('http://customer.test/s/' + token + '/cuenta/seguimiento')
                screen = page.locator('.cdi-grid.cdi-screen')
                self.assertEqual(page.locator('.tw-progress .rp-step').count(), 6)
                budget = page.locator('.cdi-budget-alert')
                self.assertTrue(budget.get_by_role('link', name='Ver presupuesto').is_visible())
                self.assertTrue(page.locator('.cdi-version').is_visible())
                badge = page.locator('.cdi-order-band .ticket-state')
                self.assertEqual(badge.evaluate('node=>getComputedStyle(node).maxWidth'), '100%')
                self.assertLessEqual(badge.bounding_box()['height'], 42)
                facts = page.locator('[data-cdi-public-fact]')
                self.assertEqual(facts.count(), 2)
                self.assertFalse(facts.first.is_visible())
                self.assertFalse(facts.last.is_visible())
                self.assertGreater(page.locator('.tp .lgx').count(), 0)
                self.assertIn('85 %', screen.locator('.equip-battery-percent').inner_text())
                page.evaluate("window.initialSvg=document.querySelector('.cdi-screen .equip-battery-icon');window.initialPlane=document.querySelector('.tp .lgx svg');")
                self.assertEqual(screen.locator('.equip-battery-slot').count(),5)
                self.assertTrue(screen.get_by_role('alert').is_visible())
                columns = screen.evaluate('el=>getComputedStyle(el).gridAutoFlow')
                self.assertEqual(columns, 'row' if width < 621 else 'column')
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                fg,bg=screen.get_by_role('alert').evaluate('el=>[getComputedStyle(el).color,getComputedStyle(el).backgroundColor]')
                self.assertGreater(contrast(fg,bg),4.5)
                if captures:
                    folder = Path(captures)
                    folder.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=folder/f'portal-{width}x{height}.png')
                    if width == 390:
                        page.screenshot(path=folder/'portal-movil-completo.png',full_page=True)
                page.clock.fast_forward(46_000)
                status=page.locator('[data-cdi-sync]')
                status.wait_for(state='visible')
                self.assertIn('última información disponible',status.inner_text())
                self.assertIn('85 %',screen.locator('.equip-battery-percent').inner_text())
                page.clock.fast_forward(46_000)
                page.wait_for_function("document.querySelector('.cdi-screen [data-cdi-battery]').dataset.cdiBattery==='61'")
                self.assertFalse(status.is_visible())
                self.assertTrue(page.evaluate("initialSvg===document.querySelector('.cdi-screen .equip-battery-icon')"))
                self.assertTrue(page.evaluate("initialPlane===document.querySelector('.tp .lgx svg')"))
                self.assertFalse(budget.get_by_role('link', name='Ver presupuesto').is_visible())
                self.assertTrue(facts.first.is_visible())
                self.assertTrue(facts.last.is_visible())
                page.emulate_media(media='print')
                print_view=page.locator('.cdi-print')
                self.assertTrue(print_view.is_visible())
                self.assertFalse(screen.is_visible())
                self.assertEqual(print_view.locator('.equip-battery-slot').count(),5)
                self.assertIn('61 %',print_view.locator('.equip-battery-percent').inner_text())
                self.assertEqual(print_view.locator('.equip-battery-widget').evaluate(
                    'node=>node.getAnimations({subtree:true}).length'), 0)
                if captures and width == 1280:
                    page.pdf(path=Path(captures) / 'seguimiento-A4.pdf',
                             prefer_css_page_size=True, print_background=True)
                page.emulate_media(media='screen')
                page.clock.fast_forward(900_000)
                self.assertTrue(status.is_visible())
                self.assertIn('Vuelve a verificar tu identidad', status.inner_text())
                self.assertEqual(page.locator('[data-cdi-battery]').count(), 0)
                self.assertFalse(errors, errors)
