"""Control de series del inventario (04/11/2026): caso A (en existencia: bloqueo), B (de baja o devuelta: reingreso con la misma identidad
o liberación por administración), C (vendida: sin segunda identidad) y D (nueva, vinculada si la serie tuvo historial); restricción en la
base; vistas separadas del catálogo y de las series; nada archivado en los selectores de venta. Base temporal y datos ficticios."""
import json
import sqlite3
import unittest

import test_app
import test_inventory_center as base
import app


class InventorySerialTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    admin, category, new, more = (getattr(base.InventoryCenterTests, n) for n in ('admin', 'category', 'new', 'more'))

    def ssd(self, model='A400 480 GB', units=('SR-1', 'SR-2')):
        made = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', model, units=list(units), cost='20,00')
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['item']['id'], [u['id'] for u in made['body']['units']]

    def unit(self, uid):
        with app.connect() as c:
            return dict(c.execute('SELECT * FROM inventory_units WHERE id=?', (uid,)).fetchone())

    def check(self, serial):
        return self.get('/api/inventory/serial-check?serial=' + serial)['body']

    def stock(self, item):
        return self.get('/api/inventory/products/%d' % item)['body']['product']['stock']

    def test_case_a_and_d_and_database_guard(self):
        self.admin()
        item, (u1, _) = self.ssd()
        self.assertEqual(self.check('SR-9')['case'], 'nueva')
        dup = self.more(item, units=['sr-1'], cost='20,00')  # misma serie con otra escritura
        self.assertEqual(dup['status'], 409)
        self.assertIn('ya está en inventario', dup['body']['error']);self.assertIn(self.unit(u1)['internal_code'], dup['body']['error'])
        self.assertEqual(self.check('SR-1')['case'], 'activo')
        self.assertEqual(self.more(item, units=['SR-3'], cost='20,00')['status'], 200)  # caso D
        # La base impide una unidad en existencia que no ocupe su serie, y dos unidades con la misma serie ocupada.
        with app.connect() as c:
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute("UPDATE inventory_units SET serial_key='' WHERE id=?", (u1,))
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute("INSERT INTO inventory_units(item_id,internal_code,serial,serial_key,status,created_at,updated_at) VALUES (?,'PCD-X-1','SR-1','SR-1','disponible','x','x')", (item,))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM inventory_units WHERE serial_key!='' GROUP BY serial_key HAVING COUNT(*)>1").fetchall(), [])

    def test_case_c_sold_unit_never_gets_a_second_identity(self):
        self.admin()
        item, (u1, _) = self.ssd()
        with app.connect() as c:  # equivale a la salida por venta (la serie sigue ocupada por la unidad vendida)
            c.execute("UPDATE inventory_units SET status='vendida' WHERE id=?", (u1,));c.commit()
        found = self.check('SR-1')
        self.assertEqual((found['case'], found['unit']['id']), ('vendida', u1))
        again = self.more(item, units=['SR-1'], cost='20,00')
        self.assertEqual(again['status'], 409);self.assertIn('No se crea otra identidad', again['body']['error'])
        self.assertEqual(self.post('/api/inventory/units/%d' % u1, action='release', reason='Intento sobre una unidad vendida')['status'], 409)

    def test_case_b_same_equipment_returns_with_its_identity(self):
        self.admin()
        item, (u1, u2) = self.ssd()
        out = self.post('/api/inventory/exit', item_id=str(item), reason='baja', unit_ids=json.dumps([u1]), note='Daño ficticio')
        self.assertEqual(out['status'], 200, out['body'])
        before = self.unit(u1)
        self.assertEqual((before['status'], before['serial_key']), ('baja', 'SR-1'))  # la serie sigue ocupada: caso B
        found = self.check('SR-1')
        self.assertEqual((found['case'], found['unit']['id'], found['unit']['item_active']), ('baja', u1, True))
        blocked = self.more(item, units=['SR-1'], cost='20,00')
        self.assertEqual(blocked['status'], 409);self.assertIn('Revisa su historial', blocked['body']['error'])
        # Desde el asistente: mismo equipo → reingreso en la misma entrada (sin unidad nueva).
        body = dict(item_id=str(item), reason='compra', cost='21,00', units=json.dumps([{'serial': 'SR-1', 'reentry': u1}, {'serial': 'SR-4'}]))
        done = self.post('/api/inventory/register', **body)
        self.assertEqual(done['status'], 200, done['body'])
        back = self.unit(u1)
        self.assertEqual((back['status'], back['serial_key'], back['internal_code'], back['unit_cost_cents']), ('disponible', 'SR-1', before['internal_code'], 2100))
        self.assertEqual(self.stock(item), 3)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory_units WHERE item_id=?', (item,)).fetchone()[0], 3)  # solo SR-4 es nueva
            self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory_movement_units WHERE unit_id=?', (u1,)).fetchone()[0], 3)  # ingreso, baja y reingreso
            self.assertTrue(c.execute("SELECT 1 FROM inventory_events WHERE unit_id=? AND event='unidad_reingresada'", (u1,)).fetchone())
        detail = self.get('/api/inventory/units/%d' % u1)['body']
        self.assertEqual((detail['lock'], len(detail['movements'])), ('', 3))  # se puede corregir: nada posterior a su reingreso
        # Una unidad de otra ficha no se reingresa aquí.
        other, (o1,) = self.ssd('A400 960 GB', units=('OT-1',))
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(other), reason='baja', unit_ids=json.dumps([o1]))['status'], 200)
        wrong = self.post('/api/inventory/register', item_id=str(item), reason='compra', cost='1', units=json.dumps([{'serial': 'OT-1', 'reentry': o1}]))
        self.assertEqual(wrong['status'], 409)
        # Desde la ficha de la unidad (administración): reingreso directo con entrada de ajuste vinculada.
        restored = self.post('/api/inventory/units/%d' % o1, action='restore', reason='Volvió de revisión (ficticio)')
        self.assertEqual(restored['status'], 200, restored['body'])
        self.assertEqual((self.unit(o1)['status'], self.stock(other)), ('disponible', 1))
        with app.connect() as c:
            m = c.execute("SELECT direction,reason,quantity FROM inventory_movements WHERE reference_kind='reingreso_unidad' AND reference_id=?", (o1,)).fetchone()
            self.assertEqual(tuple(m), (1, 'ajuste_entrada', 1))
        self.assertTrue(self.get('/api/inventory/kardex?item_id=%d' % other)['body']['rows'])

    def test_case_b_released_serial_for_other_equipment_is_linked(self):
        self.admin()
        item, (u1, _) = self.ssd()
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(item), reason='devolucion_proveedor', unit_ids=json.dumps([u1]))['status'], 200)
        self.assertEqual(self.post('/api/inventory/units/%d' % u1, action='release', reason='corto')['status'], 400)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.post('/api/inventory/units/%d' % u1, action='release', reason='Otro equipo con la misma serie (ficticio)')['status'], 403)
        self.assertEqual(self.post('/api/inventory/units/%d' % u1, action='restore', reason='Intento sin permiso')['status'], 403)
        with app.connect() as c:
            c.execute("UPDATE users SET role='administrador' WHERE id=?", (self.uid,));c.commit()
        free = self.post('/api/inventory/units/%d' % u1, action='release', reason='Otro equipo con la misma serie (ficticio)')
        self.assertEqual(free['status'], 200, free['body'])
        old = self.unit(u1)
        self.assertEqual((old['status'], old['serial'], old['serial_key'], old['released_serial']), ('devuelta', 'SR-1', '', 'SR-1'))
        found = self.check('SR-1')
        self.assertEqual((found['case'], found['previous']['id']), ('nueva', u1))
        new = self.more(item, units=['SR-1'], cost='20,00')
        self.assertEqual(new['status'], 200, new['body'])
        nid = new['body']['units'][0]['id']
        with app.connect() as c:
            link = c.execute("SELECT detail FROM inventory_events WHERE unit_id=? AND event='serie_con_historial'", (nid,)).fetchone()
            self.assertIn(old['internal_code'], link['detail'])
        self.assertNotEqual(self.unit(nid)['internal_code'], old['internal_code'])  # código nuevo: los históricos no se reutilizan
        self.assertEqual(self.post('/api/inventory/units/%d' % u1, action='restore', reason='Ya no puede volver')['status'], 409)  # su serie la ocupa otra

    def test_archived_units_stay_out_of_operational_views_and_sales(self):
        self.admin()
        item, (u1, u2) = self.ssd()
        live, _ = self.ssd('A400 960 GB', units=('LV-1',))
        empty = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 240 GB', units=['EM-1'], cost='10,00')['body']['item']['id']
        self.assertEqual(self.post('/api/inventory/reinitialize', item_ids='%d,%d' % (item, empty), reason='Reingreso del inventario (ficticio)', confirm='REINICIALIZAR')['status'], 200)
        self.assertEqual(self.post('/api/inventory/archive', item_ids=str(item), reason='Limpieza del catálogo (ficticia)', confirm='ARCHIVAR')['status'], 200)
        # Series: por defecto solo lo que está en inventario; las archivadas, en su vista.
        panel = self.get('/api/inventory/serials')['body']
        self.assertEqual((panel['view'], [r['serial'] for r in panel['rows']]), ('operativas', ['LV-1']))
        self.assertEqual((panel['counts']['operativas'], panel['counts']['archivadas'], panel['counts']['baja']), (1, 2, 1))  # EM-1: de baja, ficha en uso
        arch = self.get('/api/inventory/serials?view=archivadas')['body']['rows']
        self.assertTrue(all(r['archived'].startswith('AR-') and r['serial_free'] and not r['can_restore'] and not r['can_release'] for r in arch))
        self.assertEqual(len(self.get('/api/inventory/serials?view=archivadas&q=sr-1')['body']['rows']), 1)  # la serie liberada se encuentra
        # Catálogo: cada ficha en una sola vista.
        views = {}
        for v in ('activo', 'sin_existencias', 'baja', 'archivado'):
            body = self.get('/api/inventory/products?view=' + v)['body']
            views[v] = [p['id'] for p in body['rows']]
        self.assertEqual(views, {'activo': [live], 'sin_existencias': [empty], 'baja': [], 'archivado': [item]})
        self.assertEqual(body['counts'], {'activo': 1, 'sin_existencias': 1, 'archivado': 1})
        # Selectores de venta y de órdenes: nunca reciben la ficha archivada.
        self.assertNotIn(item, [p['id'] for p in self.get('/api/inventory/products?q=Kingston')['body']['rows']])
        # La serie archivada vuelve a ingresarse como unidad nueva, vinculada a la anterior (decisión del lote RI/AR).
        again = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 480 GB', units=['SR-1'], cost='22,00')
        self.assertEqual(again['status'], 200, again['body'])
        self.assertEqual(self.check('SR-1')['case'], 'activo')
        with app.connect() as c:
            codes = [r[0] for r in c.execute('SELECT internal_code FROM inventory_units')]
            self.assertEqual(len(codes), len(set(codes)))


if __name__ == '__main__':
    unittest.main()
