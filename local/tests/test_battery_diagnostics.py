"""Battery 6.2 validation, permissions, and history with synthetic data."""
import base64
import unittest

import app
import battery_diagnostics as battery
import order_battery
import test_app


def report(html, **overrides):
    return {'name': 'battery-report.html', 'type': 'text/html',
            'content': base64.b64encode(html.encode()).decode(), **overrides}


REPORT = '''<!doctype html><html><body>
<h1>Battery report</h1><table><tr><td>REPORT TIME</td><td>2026-11-27 08:00:00</td></tr></table>
<script>alert('fixture');</script><img src="https://example.invalid/fixture" onerror="alert(0)">
<h2>Installed batteries</h2><table>
<tr><th></th><th>BATTERY 1</th><th>BATTERY 2</th></tr>
<tr><td>NAME</td><td>Pack A</td><td>Pack B</td></tr>
<tr><td>SERIAL NUMBER</td><td>fixture-serial-A</td><td>fixture-serial-B</td></tr>
<tr><td>MANUFACTURER</td><td>Fixture</td><td>Otro</td></tr>
<tr><td>DESIGN CAPACITY</td><td>60,000 mWh</td><td>25,000 mWh</td></tr>
<tr><td>FULL CHARGE CAPACITY</td><td>51,000 mWh</td><td>10,000 mWh</td></tr>
<tr><td>CYCLE COUNT</td><td>-</td><td>123</td></tr>
</table>
<h2>Battery capacity history</h2><table><tr><td>2026-11-20</td><td>40,000 mWh</td><td>60,000 mWh</td></tr></table>
</body></html>'''


def reading(value, unit, status='sistema'):
    return {'value': value, 'unit': unit, 'status': status}


class BatteryDiagnosticRulesTests(unittest.TestCase):
    def test_capacity_units_boundaries_and_preserved_over_design(self):
        for design, full, nominal, outcome in (
            (reading('60', 'Wh'), reading('51000', 'mWh'), None, (8500, False)),
            (reading('60', 'Wh'), reading('5000', 'mAh'), '12', (10000, False)),
            (reading('1', 'Wh'), reading('1', 'mWh'), None, (10, False)),
            (reading('1', 'Ah'), reading('0', 'mAh'), None, (0, False)),
            (reading('60', 'Wh'), reading('61', 'Wh'), None, (10000, True)),
        ):
            readings = {'design': design, 'full': full}
            if nominal:
                readings['battery_nominal'] = reading(nominal, 'V')
            self.assertEqual(battery.capacity_health(readings), outcome)
        for design, full in ((reading('0', 'Wh'), reading('51', 'Wh')),
                             (reading('60', 'Wh'), reading('5', 'Ah')),
                             (reading('', 'Wh'), reading('5', 'Wh'))):
            with self.assertRaises(ValueError):
                battery.capacity_health({'design': design, 'full': full})

    def test_report_parser_separates_packs_and_ignores_active_content(self):
        result = battery.parse_report(report(REPORT, name=r'C:\fixture\battery-report.html'))
        self.assertEqual(result['name'], 'battery-report.html')
        self.assertEqual(result['date'], '2026-11-27')
        self.assertEqual(result['history'], [])
        first, second = result['batteries']
        self.assertEqual(first['readings']['full']['value'], '51000')
        self.assertNotIn('cycles', first['readings'])
        self.assertEqual(second['readings']['cycles']['value'], '123')
        self.assertNotIn('temperature', str(result))
        self.assertNotIn('example.invalid', str(result))
        for bad in (report('<html><script>Installed batteries</script></html>'),
                    report(REPORT, name='battery.exe'), report(REPORT, type='image/png'),
                    report(REPORT, content='?' * 1_400_000)):
            with self.assertRaises(ValueError):
                battery.parse_report(bad)

    def test_empty_and_safety_statuses_do_not_synthesize_readings(self):
        fields = {'readings': {'cycles': reading('', '', 'no_disponible'),
                               'current': reading('', 'mA', 'seguridad')}}
        result = battery.normalize(fields, {})
        self.assertEqual(result['readings']['cycles']['value'], '')
        self.assertEqual(result['readings']['current']['status'], 'seguridad')
        for hazard in ('inflamacion', 'corto_sospechado', 'corto_confirmado'):
            with self.subTest(hazard=hazard), self.assertRaisesRegex(ValueError, 'peligrosa'):
                battery.normalize({'hazards': [hazard],
                                   'readings': {'current': reading('1', 'A', 'medido')}}, {})
        with self.assertRaisesRegex(ValueError, 'reportados'):
            battery.normalize({'source': 'HWiNFO', 'readings': {'current': reading('1', 'A', 'medido')}}, {})


class BatteryDiagnosticIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown
    request, login = test_app.SecurityTests.request, test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def test_import_save_safety_replacements_and_public_projection(self):
        cookie, csrf = self.login()
        order = self.request('/api/orders', self.order_data({'type': 'portatil', 'request_key': 'battery-diagnostics-62-fixture'}),
                             cookie=cookie, csrf=csrf)
        self.assertEqual(order['status'], 201, order['body'])
        oid = order['body']['id']
        endpoint = f'/api/orders/{oid}/battery'

        def post(data, suffix=''):
            return self.request(endpoint + suffix, data, cookie=cookie, csrf=csrf)

        self.assertEqual(self.request(endpoint+'/report', report(REPORT))['status'], 401)
        parsed = post(report(REPORT), '/report')
        self.assertEqual(parsed['status'], 200, parsed['body'])
        self.assertEqual(len(parsed['body']['batteries']), 2)
        self.assertEqual(post(report('<html></html>'), '/report')['status'], 400)
        chosen = parsed['body']['batteries'][0]
        findings = {'carga_motherboard': {'status': 'pendiente', 'notes': 'Hallazgo interno ficticio'}}
        advanced = {**chosen, 'source': 'Windows Battery Report', 'measured_on': '2026-11-27',
                    'method': 'capacity', 'findings': findings, 'share': ['health', 'safety']}
        fields = {'revision': '0', 'status': 'evaluada', 'advanced': advanced, 'report': report(REPORT, index=0)}
        mismatch = {**fields, 'report': report(REPORT, index=1)}
        self.assertEqual(post(mismatch)['status'], 400)
        result = post(fields)
        self.assertEqual(result['status'], 200, result['body'])
        saved = result['body']['battery']
        self.assertEqual(saved['percent'], 85)
        self.assertEqual(saved['advanced']['report']['name'], 'battery-report.html')
        with app.connect() as connection:
            public = dict(order_battery.customer_assessment(connection, oid))
        self.assertEqual(public['Salud'], '85 %')
        for private in ('fixture-serial-A', 'Hallazgo interno', 'battery-report', '51000'):
            self.assertNotIn(private, str(public))

        over = {**advanced, 'readings': {**advanced['readings'], 'full': reading('61', 'Wh')},
                'hazards': ['inflamacion']}
        update = {'revision': str(saved['id']), 'status': 'evaluada', 'advanced': over}
        self.assertEqual(post(update)['status'], 400)
        risky = post({**update, 'acknowledge_capacity': True})
        self.assertEqual(risky['status'], 200, risky['body'])
        risky = risky['body']['battery']
        self.assertEqual(risky['percent'], 100)
        self.assertEqual(risky['advanced']['readings']['full']['value'], '61')
        with app.connect() as connection:
            self.assertIn('No utilice ni cargue', dict(order_battery.customer_assessment(connection, oid))['Advertencia de seguridad'])
        adi = self.request(f'/api/orders/{oid}/adi', {'action': 'report'}, cookie=cookie, csrf=csrf)
        self.assertIn('Suspende', adi['body']['report'])

        def replace(revision, model):
            return post({'revision': str(revision), 'status': 'pendiente', 'replace': True, 'warranty': '90 días',
                         'advanced': {'identity': {'model': model}, 'share': ['replacement']}})

        replacement = replace(risky['id'], 'Fixture nueva')
        self.assertEqual(replacement['status'], 200, replacement['body'])
        replacement = replacement['body']['battery']
        self.assertIsNone(replacement['percent'])
        self.assertFalse(replacement['advanced']['readings'])
        self.assertEqual(replace(risky['id'], 'Duplicado')['status'], 409)
        again = replace(replacement['id'], 'Fixture posterior')
        self.assertEqual(again['status'], 200, again['body'])
        history = self.request(endpoint, cookie=cookie)['body']['history']
        self.assertEqual(len({row['advanced']['battery_key'] for row in history}), 3)
        self.assertEqual([row['percent'] for row in history], [None, None, 100, 85])
        with app.connect() as connection:
            connection.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertEqual(post(report(REPORT), '/report')['status'], 403)
