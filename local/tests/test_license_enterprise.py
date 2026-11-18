"""1.5.291 · Licencias Digitales Premium Enterprise 3.0 y costo de compra protegido. Datos ficticios en una base temporal.
Comprueba que el costo no sale del servidor salvo a quien está autorizado y lo pide (con auditoría), que ocultarlo no lo borra, el ciclo
de vida, los filtros, las incidencias, el reemplazo atómico, las alertas del Centro de Control y los reportes."""
import json
import unittest
from datetime import timedelta

import test_app
import app
import licenses
import license_control
import test_license_control


def contains_cost(value):
    if isinstance(value, dict):
        return any(k in license_control.COST_KEYS or contains_cost(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_cost(v) for v in value)
    return False


class LicenseEnterpriseTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login
    _B = test_license_control.LicenseControlTests
    admin, today, new_product, order_data, delivered = _B.admin, _B.today, _B.new_product, _B.order_data, _B.delivered
    del _B

    def technician(self):
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tec','tec@example.invalid','Técnico ficticio',?,'tecnico',0)", (self.hash,))
        login = self.request('/api/login', {'login': 'tec', 'password': 'contraseña-segura-de-prueba'})
        return login['cookie'].split(';')[0]

    def test_cost_is_hidden_by_default_and_only_sent_on_authorized_request(self):
        self.admin()
        unit, cid = self.delivered(30)
        meta = self.get('/api/licenses')['body']
        self.assertFalse(contains_cost(meta))                       # oculto por defecto: ni el costo ni el margen viajan
        self.assertEqual((meta['costs_visible'], meta['can_view_costs']), (False, True))
        self.assertTrue(all(p.get('price_cents') is not None for p in meta['products'] if p.get('managed')))   # el precio de venta sigue visible
        for path in ('/api/licenses/units', '/api/licenses/units/%d/dossier' % unit, '/api/licenses/reports/activas', '/api/clients/%d/licenses' % cid):
            self.assertFalse(contains_cost(self.get(path)['body']), path)
        shown = self.get('/api/licenses?costos=1')['body']
        self.assertTrue(any(p.get('purchase_cents') == 1850 for p in shown['products']))
        self.get('/api/licenses/units?costos=1')
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='license_costs_viewed'").fetchone()[0], 1)   # auditado, sin repetir en 10 min
        # Un técnico nunca recibe el costo, aunque lo pida (ficha del cliente) y no entra a Licencias Pro.
        tcookie = self.technician()
        tab = self.request('/api/clients/%d/licenses?costos=1' % cid, cookie=tcookie)
        self.assertEqual(tab['status'], 200)
        self.assertFalse(contains_cost(tab['body']))
        self.assertEqual(self.request('/api/licenses?costos=1', cookie=tcookie)['status'], 403)

    def test_hidden_cost_is_kept_when_editing_and_cost_reports_require_reveal(self):
        self.admin()
        made = self.new_product(name='Producto con costo ficticio', key='COST-FICT-0001')
        product = next(p for p in self.get('/api/licenses')['body']['products'] if p['id'] == made['product_id'])
        payload = {k: str(product[k]) for k in ('name', 'line', 'model', 'duration', 'validity_mode') if product.get(k) is not None}
        payload.update(item_id=str(made['product_id']), price='31', brand='ESET', devices='1')
        saved = self.post('/api/licenses/products', **payload)   # sin «purchase_price»: el costo estaba oculto
        self.assertIn(saved['status'], (200, 201), saved['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT purchase_cents FROM license_products WHERE item_id=?', (made['product_id'],)).fetchone()[0], 1850)   # no se borró
        self.assertEqual(self.get('/api/licenses/reports/margenes')['status'], 403)
        self.assertEqual(self.get('/api/licenses/reports/margenes.csv')['status'], 403)
        self.assertEqual(self.get('/api/licenses/reports/margenes?costos=1')['status'], 200)
        for kind in ('ventas', 'rotacion'):
            out = self.get('/api/licenses/reports/' + kind)
            self.assertEqual(out['status'], 200, (kind, out['body']))
            self.assertFalse(contains_cost(out['body']))

    def test_lifecycle_stages_indicators_and_filters(self):
        self.admin()
        active, _ = self.delivered(100)
        idle, _ = self.delivered(50, activated=False)
        late, _ = self.delivered(-2)
        rows = {r['id']: r for r in self.get('/api/licenses/units')['body']['rows']}
        self.assertEqual((rows[active]['stage'], rows[idle]['stage'], rows[late]['stage']), ('activada', 'entregada', 'vencida'))
        self.assertEqual((rows[idle]['expiry']['kind'], rows[active]['expiry']['kind']), ('estimada', 'real'))   # estimado ≠ real, y no se guarda
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT expires_at FROM license_units WHERE id=?', (idle,)).fetchone()[0], '')
        ind = self.get('/api/licenses')['body']['indicators']
        self.assertEqual((ind['productos'], ind['activadas'], ind['vencidas'], ind['vendidas']), (3, 2, 1, 3))
        self.assertEqual(ind['agotados'], 3)   # cada producto ficticio tenía 1 licencia y ya se entregó: agotado (no vencido)
        only = self.get('/api/licenses/units?etapa=activada')['body']['rows']
        self.assertEqual({r['id'] for r in only}, {active})
        self.assertEqual(len(self.get('/api/licenses/units?proveedor=mayorista')['body']['rows']), 3)
        self.assertEqual(len(self.get('/api/licenses/units?modalidad=perpetua')['body']['rows']), 0)

    def test_incidents_and_atomic_replacement(self):
        self.admin()
        unit, cid = self.delivered(200)
        url = '/api/licenses/units/%d' % unit
        product = licenses.unit_row(app.connect(), unit)['product_id'] if False else None
        self.assertEqual(self.post(url, action='incident_open', kind='activacion', detail='corto')['status'], 400)
        opened = self.post(url, action='incident_open', kind='activacion', detail='El fabricante rechaza la clave al activar.')
        self.assertEqual(opened['status'], 200, opened['body'])
        iid = opened['body']['id']
        self.assertTrue(self.post(url, action='incident_open', kind='activacion', detail='El fabricante rechaza la clave al activar.')['body']['duplicate'])
        center = [i for i in self.get('/api/pending')['body']['items'] if i['entity'] == 'licenses:incidencia:%d' % iid]
        self.assertEqual(len(center), 1)
        # Sin otra licencia del mismo producto: no se puede reemplazar.
        self.assertEqual(self.post(url, action='replace', reason='Clave rechazada por el fabricante', incident=str(iid))['status'], 409)
        with app.connect() as c:
            pid = c.execute('SELECT product_id FROM license_units WHERE id=?', (unit,)).fetchone()[0]
        added = self.post('/api/licenses/units', product_id=str(pid), key='FICT-REPL-0002')
        self.assertIn(added['status'], (200, 201), added['body'])
        done = self.post(url, action='replace', reason='Clave rechazada por el fabricante', incident=str(iid))
        self.assertEqual(done['status'], 200, done['body'])
        new = done['body']['new_unit_id']
        with app.connect() as c:
            old_row = c.execute('SELECT status FROM license_units WHERE id=?', (unit,)).fetchone()
            new_row = c.execute('SELECT status,client_id FROM license_units WHERE id=?', (new,)).fetchone()
            inc = c.execute('SELECT status,replacement_unit_id FROM license_incidents WHERE id=?', (iid,)).fetchone()
            with self.assertRaises(Exception):
                c.execute('DELETE FROM license_incidents')
        self.assertEqual((old_row[0], new_row[0], new_row[1], inc[0], inc[1]), ('anulada', 'entregada', cid, 'resuelta', new))
        self.assertEqual(self.post(url, action='replace', reason='Segundo intento de reemplazo')['status'], 409)   # la anulada ya no se reemplaza
        self.assertFalse([i for i in self.get('/api/pending')['body']['items'] if i['entity'] == 'licenses:incidencia:%d' % iid])

    def test_center_alerts_for_stock_and_activation(self):
        self.admin()
        unit, _ = self.delivered(100, activated=False)
        with app.connect() as c:
            c.execute('UPDATE license_units SET delivered_at=? WHERE id=?', (licenses.stamp(app.reception_now() - timedelta(days=10)), unit))
        items = self.get('/api/pending')['body']['items']
        kinds = {i['entity'].split(':')[1] for i in items if i['module'] == 'licenses' and i['entity'].count(':') == 2}
        self.assertIn('stock', kinds)       # producto agotado
        self.assertIn('activacion', kinds)  # entregada hace 10 días sin activación confirmada
        detail = self.get('/api/pending/item?key=licenses:activacion:%d' % unit)
        self.assertEqual(detail['status'], 200, detail['body'])
        self.assertEqual(self.post('/api/licenses/units/%d' % unit, action='activate', activated_at=self.today().isoformat())['status'], 200)
        self.assertFalse([i for i in self.get('/api/pending')['body']['items'] if i['entity'] == 'licenses:activacion:%d' % unit])

    def test_cost_protection_also_applies_through_the_production_adapter(self):
        """Producción responde por wsgi_app (no por el servidor local): el costo tampoco debe salir por ese camino."""
        import io
        import wsgi_app
        self.admin()
        unit, cid = self.delivered(30)

        def call(path, query=''):
            environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'QUERY_STRING': query, 'REMOTE_ADDR': '127.0.0.1', 'wsgi.input': io.BytesIO(b''),
                       'HTTP_COOKIE': self.cookie, 'HTTP_ORIGIN': 'http://127.0.0.1:8010'}
            status = {}
            body = b''.join(wsgi_app.application(environ, lambda s, h: status.update(s=s)))
            return status['s'], json.loads(body)
        for path in ('/api/licenses', '/api/licenses/units', '/api/licenses/units/%d/dossier' % unit, '/api/clients/%d/licenses' % cid):
            status, body = call(path)
            self.assertTrue(status.startswith('200'), (path, status, body))
            self.assertFalse(contains_cost(body), path)
        status, body = call('/api/licenses', 'costos=1')
        self.assertTrue(any(p.get('purchase_cents') == 1850 for p in body['products']))
