"""1.5.290 · Licencias Pro Premium 4.0: estados separados (inventario, activación, vigencia), seguimiento comercial de renovaciones,
dispositivos registrados, avisos configurables, reportes, integración con el Centro de Control y permisos. Datos ficticios."""
import unittest
from datetime import timedelta

import test_app
import app
import licenses
import license_control
import test_licenses


class LicenseControlTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login
    _B = test_licenses.LicenseProTests
    admin, today, new_product, order_data = _B.admin, _B.today, _B.new_product, _B.order_data
    del _B

    def delivered(self, days, activated=True, name='Cliente ficticio de licencias', duration=None):
        """Unidad entregada a un cliente ficticio, activada y con vencimiento dentro de `days` días."""
        made = self.new_product(name='Producto ficticio %d' % days, key='FICT-%04d-KEY' % (days + 500))
        today = self.today()
        with app.connect() as c:
            unit = made['unit_id']
            cid = c.execute("INSERT INTO clients(name,phone,email) VALUES (?,?,?)", (name, '0991234567', 'cliente.licencia@example.invalid')).lastrowid
            if duration:
                c.execute('UPDATE license_products SET duration=? WHERE item_id=?', (duration, made['product_id']))
            expires = '' if duration == 'perpetua' else (today + timedelta(days=days)).isoformat()
            c.execute("UPDATE license_units SET status='entregada',client_id=?,activated=?,activated_at=?,expires_at=?,delivered_at=? WHERE id=?",
                      (cid, 1 if activated else 0, (today - timedelta(days=300)).isoformat() if activated else '', expires if activated else '', licenses.stamp(app.reception_now()), unit))
        return unit, cid

    def test_three_independent_states_and_traffic_light(self):
        self.admin()
        soon_unit, _ = self.delivered(10)
        far_unit, _ = self.delivered(200)
        late_unit, _ = self.delivered(-3)
        idle_unit, _ = self.delivered(50, activated=False)
        perp_unit, _ = self.delivered(0, duration='perpetua')
        axes = {u: self.get('/api/licenses/units/%d/dossier' % u)['body']['unit']['axes'] for u in (soon_unit, far_unit, late_unit, idle_unit, perp_unit)}
        self.assertEqual((axes[soon_unit]['validity'], axes[soon_unit]['light'], axes[soon_unit]['activation']), ('por_vencer', 'amarillo', 'activada'))
        self.assertEqual((axes[far_unit]['validity'], axes[far_unit]['light']), ('vigente', 'verde'))
        self.assertEqual((axes[late_unit]['validity'], axes[late_unit]['light']), ('vencida', 'rojo'))
        self.assertEqual((axes[idle_unit]['activation'], axes[idle_unit]['validity'], axes[idle_unit]['light']), ('sin_activar', 'sin_fecha', 'gris'))
        self.assertEqual((axes[perp_unit]['validity'], axes[perp_unit]['inventory']), ('perpetua', 'entregada'))
        # Disponible en inventario: la activación no aplica (no se contradice con la vigencia).
        with app.connect() as c:
            spare = c.execute("SELECT id FROM license_units WHERE status='disponible' LIMIT 1").fetchone()
        if spare:
            free = self.get('/api/licenses/units/%d/dossier' % spare[0])['body']['unit']['axes']
            self.assertEqual((free['inventory'], free['activation']), ('disponible', 'no_aplica'))
        body = self.get('/api/licenses/units/%d/dossier' % soon_unit)['body']
        self.assertNotIn('secret', str(body).lower().replace('secret_labels', ''))   # el expediente no lleva credenciales
        self.assertNotIn(test_licenses.SERIAL, str(body))

    def test_renewal_followup_flow_and_validation(self):
        self.admin()
        unit, _ = self.delivered(12)
        url = '/api/licenses/units/%d' % unit
        data = self.get('/api/licenses/renewals')['body']
        row = next(r for r in data['rows'] if r['id'] == unit)
        self.assertEqual((row['cycle']['status'], row['contact']['whatsapp']), ('sin_contactar', '593991234567'))
        # Validaciones: estado, canal obligatorio al contactar, nota obligatoria al aceptar o rechazar, fecha de próximo contacto.
        self.assertEqual(self.post(url, action='followup', status='inventado')['status'], 400)
        self.assertEqual(self.post(url, action='followup', status='contactado')['status'], 400)
        self.assertEqual(self.post(url, action='followup', status='aceptado', note='')['status'], 400)
        self.assertEqual(self.post(url, action='followup', status='contactado', channel='telefono', next_contact='2020-01-01')['status'], 400)
        tomorrow = (self.today() + timedelta(days=1)).isoformat()
        ok = self.post(url, action='followup', status='esperando_respuesta', channel='whatsapp', note='Pidió cotización', next_contact=tomorrow)
        self.assertEqual(ok['status'], 200, ok['body'])
        again = self.post(url, action='followup', status='esperando_respuesta', channel='whatsapp', note='Pidió cotización', next_contact=tomorrow)
        self.assertTrue(again['body'].get('duplicate'))   # doble clic
        accepted = self.post(url, action='followup', status='aceptado', channel='telefono', note='Acepta renovar por un año')
        self.assertEqual(accepted['body']['cycle']['status'], 'aceptado')
        # Aceptar NO cambia la vigencia.
        with app.connect() as c:
            before = c.execute('SELECT expires_at FROM license_units WHERE id=?', (unit,)).fetchone()[0]
        self.assertEqual(before, (self.today() + timedelta(days=12)).isoformat())
        # La renovación con su fecha efectiva completa el ciclo; el seguimiento del ciclo anterior se conserva.
        renewed = self.post(url, action='renew', duration='anual', starts_at=before)
        self.assertEqual(renewed['status'], 200, renewed['body'])
        dossier = self.get(url + '/dossier')['body']
        self.assertEqual(dossier['cycle']['status'], 'sin_contactar')   # nuevo ciclo, con el nuevo vencimiento
        self.assertEqual(len(dossier['followups']), 2)
        pipeline = self.get('/api/licenses/renewals')['body']
        self.assertTrue(any(r['id'] == unit and r['cycle']['status'] == 'completado' for r in pipeline['rows']))
        # El ciclo nuevo admite su propio seguimiento (queda con el nuevo vencimiento).
        nxt = self.post(url, action='followup', status='contactado', channel='correo')
        self.assertEqual((nxt['status'], nxt['body']['cycle']['expires_at']), (200, renewed['body']['expires_at']))
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute("UPDATE license_followups SET note='x'")
            with self.assertRaises(Exception):
                c.execute('DELETE FROM license_followups')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='license_followup'").fetchone()[0], 3)

    def test_center_shows_followup_and_rejection_closes_it(self):
        self.admin()
        unit, _ = self.delivered(5)
        center = lambda: next((i for i in self.get('/api/pending')['body']['items'] if i['entity'] == 'licenses:%d' % unit), None)
        item = center()
        self.assertEqual((item['href'], item['actions'][0]['label'], item['ref']['followup']), ('#licenses?unidad=%d' % unit, 'Gestionar renovación', 'sin_contactar'))
        tomorrow = (self.today() + timedelta(days=2)).isoformat()
        self.post('/api/licenses/units/%d' % unit, action='followup', status='esperando_respuesta', channel='correo', note='Envió propuesta', next_contact=tomorrow)
        item = center()
        self.assertEqual(item['ref']['followup'], 'esperando_respuesta')
        self.post('/api/licenses/units/%d' % unit, action='followup', status='aceptado', note='Confirmó por correo')
        item = center()
        self.assertTrue(item['decision'])
        self.assertIn('registra la renovación', item['waiting'])
        self.post('/api/licenses/units/%d' % unit, action='followup', status='rechazado', note='Cambia de proveedor')
        self.assertIsNone(center())   # el rechazo registrado cierra el pendiente…
        solved = self.get('/api/pending/resolved')['body']['rows']
        self.assertTrue(any(r['entity'] == 'licenses:%d' % unit and r['outcome'] == 'cancelado' for r in solved))   # …y queda en Solucionadas

    def test_devices_respect_limit_and_are_never_deleted(self):
        self.admin()
        unit, cid = self.delivered(100)
        url = '/api/licenses/units/%d' % unit
        self.assertEqual(self.post(url, action='device_add', label='')['status'], 400)
        first = self.post(url, action='device_add', label='Portátil de recepción', serial='SN-FICT-1')
        self.assertEqual(first['status'], 200, first['body'])
        self.assertEqual(self.post(url, action='device_add', label='Otro equipo', serial='SN-FICT-2')['status'], 409)   # permite 1 dispositivo
        device = first['body']['devices'][0]['id']
        self.assertEqual(self.post(url, action='device_remove', device=str(device), reason='')['status'], 400)
        self.assertEqual(self.post(url, action='device_remove', device=str(device), reason='Equipo dado de baja')['status'], 200)
        self.assertEqual(self.post(url, action='device_add', label='Otro equipo', serial='SN-FICT-2')['status'], 200)
        with app.connect() as c:
            other = c.execute("INSERT INTO clients(name) VALUES ('Otro cliente ficticio')").lastrowid
            dev = c.execute("INSERT INTO devices(client_id,type,category,kind,brand,model) VALUES (?,'portatil','portatil','portatil','HP','Ajeno')", (other,)).lastrowid
            with self.assertRaises(Exception):
                c.execute('DELETE FROM license_devices')
        self.post(url, action='device_remove', device=str(self.get(url + '/dossier')['body']['devices'][0]['id']), reason='Prueba de equipo ajeno')
        self.assertEqual(self.post(url, action='device_add', device_id=str(dev))['status'], 409)   # equipo de otro cliente
        dossier = self.get(url + '/dossier')['body']
        self.assertEqual((len(dossier['devices']), dossier['devices_active']), (2, 0))
        self.assertTrue(any('Equipo retirado' in e['detail'] for e in dossier['history']))

    def test_alert_days_are_configurable_and_never_duplicated(self):
        self.admin()
        unit, _ = self.delivered(14)
        self.assertEqual(self.post('/api/licenses/alert-days', days='45')['status'], 400)
        self.assertEqual(self.post('/api/licenses/alert-days', days='7,1')['status'], 200)
        with app.connect() as c:
            self.assertEqual(licenses.tick(c, app.reception_now()), [])   # 14 días: sin aviso con 7 y 1
        self.assertEqual(self.post('/api/licenses/alert-days', days='30,15,7,1,0')['status'], 200)
        with app.connect() as c:
            first = licenses.tick(c, app.reception_now())
            second = licenses.tick(c, app.reception_now())
        self.assertEqual(([u['threshold'] for u in first if u['id'] == unit], second), ([15], []))

    def test_reports_csv_and_permissions(self):
        self.admin()
        unit, _ = self.delivered(10)
        self.delivered(300, name='Cliente ficticio de licencias')
        for kind in license_control.REPORTS:
            out = self.get('/api/licenses/reports/' + kind + ('?costos=1' if kind in license_control.COST_REPORTS else ''))   # el de costos exige mostrarlos (1.5.291)
            self.assertEqual(out['status'], 200, (kind, out['body']))
        upcoming = self.get('/api/licenses/reports/proximas')['body']
        self.assertEqual([r['id'] for r in upcoming['rows']], [unit])
        pending = self.get('/api/licenses/reports/pendientes')['body']
        self.assertIn(unit, [r['id'] for r in pending['rows']])
        income = self.get('/api/licenses/reports/ingresos')['body']
        self.assertIn('Cobrado (pagos confirmados)', income['totals'])
        csv = self.get('/api/licenses/reports/activas.csv')
        self.assertEqual(csv['status'], 200)
        self.assertNotIn(test_licenses.SERIAL, csv['body'].decode('utf-8') if isinstance(csv['body'], bytes) else str(csv['body']))
        self.assertEqual(self.get('/api/licenses/reports/inventado')['status'], 404)
        self.assertEqual(self.get('/api/licenses/reports/renovaciones?from=2026-99-01')['status'], 400)
        # Un técnico no accede a Licencias Pro (ni lectura ni cambios).
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tec','tec@example.invalid','Técnico ficticio',?,'tecnico',0)", (self.hash,))
        login = self.request('/api/login', {'login': 'tec', 'password': 'contraseña-segura-de-prueba'})
        tcookie = login['cookie'].split(';')[0]
        tcsrf = self.request('/api/me', cookie=tcookie)['body']['user']['csrf']
        self.assertEqual(self.request('/api/licenses/renewals', cookie=tcookie)['status'], 403)
        self.assertEqual(self.request('/api/licenses/units/%d' % unit, {'action': 'followup', 'status': 'contactado', 'channel': 'telefono'}, cookie=tcookie, csrf=tcsrf)['status'], 403)
