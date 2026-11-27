"""Regresión de la ficha real con Chromium y datos ficticios."""
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest
from uuid import uuid4

import app
import test_app

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright, 'Playwright no está instalado')
class OrderActionCenterTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown
    request, login, order_data = test_app.SecurityTests.request, test_app.SecurityTests.login, test_app.SecurityTests.order_data

    def test_actions_and_manual_disclosures(self):
        cookie, csrf = self.login()
        ids = []
        for _ in range(2):
            created = self.request('/api/orders', self.order_data({'request_key': str(uuid4())}),
                                   cookie=cookie, csrf=csrf)
            self.assertEqual(created['status'], 201, created['body'])
            ids.append(created['body']['id'])
        first, second = ids
        self.assertEqual(self.request(f'/api/orders/{first}/communications')['status'], 401)
        self.assertEqual(self.request('/api/orders/99999/communications', cookie=cookie)['status'], 404)
        server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        runner = Thread(target=server.serve_forever, daemon=True)
        runner.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            name, value = cookie.split('=', 1)
            context = browser.new_context(viewport={'width': 1600, 'height': 950}, reduced_motion='reduce')
            context.add_cookies([{'name': name, 'value': value, 'url': base}])
            page = context.new_page()
            failed = False
            message = False

            def order_response(route):
                response = route.fetch()
                data = response.json()
                order = data if response.url.endswith('/communications') else data['order']
                if failed:
                    order['mail_history'] = [{
                        'subject': 'Correo ficticio fallido', 'delivery': 'fallido', 'delivery_label': 'Fallido',
                        'created_at': '2026-11-27T09:00:00-05:00',
                    }]
                if message:
                    order['messages'] = [{
                        'channel': 'whatsapp', 'status': 'entregado', 'status_label': 'Entregado',
                        'created_at': '2026-11-27T09:01:00-05:00',
                    }]
                route.fulfill(response=response, json=data)

            page.route(f'{base}/api/orders/{first}', order_response)
            page.route(f'{base}/api/orders/{first}/communications', order_response)
            page.add_init_script("localStorage.setItem('adio-expanded','1')")
            page.goto(f'{base}/#orders?id={first}')
            bar = page.get_by_role('navigation', name='Centro de acciones')
            comms = page.locator('#ex-comms-head')
            expect(bar).to_be_visible()
            expect(comms).to_have_attribute('aria-expanded', 'false')
            adi = page.locator('.adio-bar-toggle')
            expect(adi).to_have_attribute('aria-expanded', 'false')
            adi.click()
            page.evaluate('(id) => showOrderDetail(id)', first)
            expect(adi).to_have_attribute('aria-expanded', 'true')
            adi.click()
            self.assertEqual(bar.locator('.action-center-control:visible').count(), 13)
            self.assertLessEqual(bar.bounding_box()['height'], 80)
            self.assertTrue(bar.evaluate('(node) => node.scrollWidth <= node.clientWidth'), bar.evaluate('''(node) => ({
                scroll: node.scrollWidth, width: node.clientWidth,
                groups: [...node.querySelectorAll('.action-center-group')].map(g => [g.offsetWidth,g.scrollWidth,
                    [...g.querySelectorAll('.action-center-control')].map(b=>[b.textContent,b.offsetWidth,getComputedStyle(b).minWidth,getComputedStyle(b).paddingInline,getComputedStyle(b).gap,[...b.children].map(c=>[c.localName,c.className.baseVal||c.className,getComputedStyle(c).display,c.getBoundingClientRect().width])])])
            })'''))
            for action in bar.locator('.action-center-control').all():
                self.assertTrue(action.get_attribute('title'))
                self.assertTrue(action.get_attribute('aria-label'))
            expect(bar.get_by_role('button', name='Próximo mantenimiento', include_hidden=True)).to_have_attribute('aria-disabled', 'true')

            # Solicitudes reales del navegador, sin activar una impresora física.
            for label, document, digital in (
                ('Comprobante de recepción', 'receipt', False),
                ('Imprimir ticket', 'thermal', False),
                ('Ticket digital', 'thermal', True),
                ('Etiqueta de servicio', 'label', False),
                ('Hoja de servicio técnico', 'service', False),
            ):
                with page.expect_response(lambda response: (
                    f'/api/orders/{first}/{document}.pdf' in response.url
                    and ('modo=digital' in response.url) == digital
                )) as preview:
                    bar.get_by_label(label, exact=True).click()
                self.assertTrue(preview.value.body().startswith(b'%PDF'), label)
                page.locator('#receipt-dialog').evaluate('(dialog) => dialog.close()')
            with page.expect_download() as download:
                bar.get_by_role('link', name='Descargar PDF', exact=True).click()
            self.assertTrue(download.value.path().read_bytes().startswith(b'%PDF'))
            conditions = bar.get_by_role('link', name='Condiciones del servicio', exact=True)
            with context.expect_page() as conditions_tab:
                conditions.click()
            conditions_tab.value.close()
            page.evaluate("Object.defineProperty(navigator, 'canShare', {value: () => false})")
            with page.expect_download() as shared:
                bar.get_by_role('button', name='Compartir condiciones del servicio', exact=True).click()
            self.assertTrue(shared.value.path().read_bytes().startswith(b'%PDF'))
            pending = bar.get_by_role('button', name='Próximo mantenimiento', exact=True).bounding_box()
            page.mouse.click(pending['x'] + pending['width'] / 2, pending['y'] + pending['height'] / 2)
            expect(page.get_by_text('Aún sin programar', exact=True)).to_be_visible()
            with page.expect_response(f'{base}/api/orders/{first}/tracking-card') as details:
                bar.get_by_role('button', name='Tarjeta de seguimiento', exact=True).click()
            self.assertEqual(details.value.status, 200)
            page.locator('dialog.ticket-dialog[open]').evaluate('(dialog) => dialog.close()')
            with context.expect_page() as a4:
                bar.get_by_role('button', name='Seguimiento A4', exact=True).click()
            a4.value.wait_for_url(f'{base}/tarjeta/{first}/a4')
            a4.value.close()
            bar.get_by_role('button', name='Gestión técnica', exact=True).click()
            expect(page.locator('dialog.tech-editor[open]')).to_be_visible()
            page.locator('dialog.tech-editor[open]').evaluate('(dialog) => dialog.close()')
            bar.get_by_role('button', name='Cancelar reparación').click()
            expect(page.locator('dialog.oc-dialog[open]')).to_be_visible()
            page.locator('dialog.oc-dialog[open]').evaluate('(dialog) => dialog.close()')

            failed = True
            page.locator('.ex-panel').evaluate('(panel) => panel.refreshCommunications()')
            expect(comms).to_contain_text('1 fallido')
            expect(comms).to_have_attribute('aria-expanded', 'false')
            comms.focus()
            page.keyboard.press('Enter')
            expect(comms).to_have_attribute('aria-expanded', 'true')
            message = True
            page.locator('.action-center-title').click()
            page.locator('.ex-panel').evaluate('(panel) => panel.refreshCommunications()')
            expect(comms).to_contain_text('2 comunicaciones')
            expect(comms).to_have_attribute('aria-expanded', 'true')
            expect(page.get_by_text('Correo ficticio fallido')).to_be_visible()
            comms.press('Escape')
            page.evaluate('(id) => showOrderDetail(id)', first)
            expect(comms).to_have_attribute('aria-expanded', 'false')
            comms.click()
            page.reload()
            expect(comms).to_have_attribute('aria-expanded', 'false')
            comms.click()
            page.evaluate('(id) => location.hash = "orders?id="+id', second)
            expect(page.locator('.workspace-header')).to_have_attribute('data-order-id', str(second))
            expect(comms).to_have_attribute('aria-expanded', 'false')
            comms.click()
            page.evaluate('location.hash = "home"')
            expect(page.locator('.workspace-header:visible')).to_have_count(0)
            page.evaluate('(id) => location.hash = "orders?id="+id', first)
            expect(comms).to_have_attribute('aria-expanded', 'false')

            for width in (1100, 768, 390, 320):
                page.set_viewport_size({'width': width, 'height': 950})
                for category in ('Documentación', 'Servicio', 'Condiciones', 'Seguimiento'):
                    trigger = bar.get_by_role('button', name=category, exact=True)
                    expect(trigger).to_be_visible()
                    if width <= 390:
                        self.assertGreaterEqual(trigger.bounding_box()['height'], 44)
                    trigger.press('Enter')
                    expect(trigger).to_have_attribute('aria-expanded', 'true')
                    menu = trigger.locator('..').locator('.action-center-items')
                    bounds = menu.bounding_box()
                    self.assertGreaterEqual(bounds['x'], 0)
                    self.assertLessEqual(bounds['x'] + bounds['width'], width)
                    self.assertTrue(menu.evaluate('(node) => node.scrollWidth <= node.clientWidth'))
                    if width <= 390:
                        self.assertGreaterEqual(menu.locator('.action-center-control').first.bounding_box()['height'], 44)
                    trigger.press('Escape')
                    expect(trigger).to_be_focused()
                    expect(trigger).to_have_attribute('aria-expanded', 'false')
            page.evaluate("location.hash = 'sales'")
            sale_bar = page.get_by_role('navigation', name='Acciones de ventas')
            expect(sale_bar.get_by_role('button', name='Nueva venta', exact=True)).to_be_visible()
            sale_bar.get_by_role('button', name='Otras operaciones', exact=True).click()
            expect(sale_bar.get_by_role('button', name='Nueva cotización', exact=True)).to_be_visible()
            page.evaluate('(id) => location.hash = "orders?id="+id', first)
            expect(bar).to_be_visible()
            with app.connect() as database:
                database.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
            page.reload()
            expect(bar).to_be_visible()
            expect(bar.get_by_role('button', name='Gestión técnica', exact=True)).to_have_count(0)
            expect(bar.get_by_role('button', name='Cancelar reparación', exact=True)).to_be_visible()
            browser.close()
