"""Limpieza segura del catálogo (1.5.268). Datos ficticios en una base temporal: nunca se eliminan productos reales.

Cubre: eliminar un inactivo sin dependencias; proteger ventas, facturas, órdenes técnicas (presupuestos), licencias e inventario;
selección múltiple y eliminación masiva parcial; archivar lo protegido y restaurarlo; filtros (archivados fuera del catálogo operativo);
activos nunca se eliminan; permisos en el servidor; registro y auditoría; inventario y facturación intactos."""
import unittest

import test_app  # primero: prepara la ruta de importación y la base temporal
import app
import catalog_cleanup

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')


class CatalogCleanupTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    tearDown, request, login, order_data = test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login, test_app.SecurityTests.order_data

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        self.cookie, self.csrf = self.login()

    def post(self, path, **body):
        return self.request(path, body, cookie=self.cookie, csrf=self.csrf)

    def item(self, name, category='otro', available=False, price='10.00'):
        got = self.post('/api/catalog', name=name, description='Ficticio', category=category, brand='', price=price, price_mode='incluido', license_term='', devices='', available=True)
        self.assertEqual(got['status'], 200, got['body'])
        iid = got['body']['id']
        if not available:
            with app.connect() as c:
                c.execute('UPDATE catalog_items SET available=0 WHERE id=?', (iid,));c.commit()
        return iid

    def reference(self, table, column, iid):
        """Fila de referencia mínima (solo en la base de prueba): rellena lo obligatorio sin validar otras relaciones."""
        with app.connect() as c:
            c.execute('PRAGMA foreign_keys=OFF');c.execute('PRAGMA ignore_check_constraints=ON')
            cols = [r for r in c.execute('PRAGMA table_info(%s)' % table) if r[1] != 'id']
            values = {r[1]: (iid if r[1] == column else 1 if 'INT' in (r[2] or '').upper() else 'ficticio-%s-%d' % (r[1], iid)) for r in cols if r[3] and r[4] is None or r[1] == column}
            c.execute('INSERT INTO %s(%s) VALUES (%s)' % (table, ','.join(values), ','.join('?' * len(values))), tuple(values.values()))
            c.commit()
            c.execute('PRAGMA ignore_check_constraints=OFF');c.execute('PRAGMA foreign_keys=ON')

    def rows(self):
        return {r['id']: r for r in self.request('/api/catalog?all=1', cookie=self.cookie)['body']['rows']}

    def cleanup(self, **body):
        if isinstance(body.get('ids'), list):body['ids'] = ','.join(map(str, body['ids']))  # la API solo acepta textos y booleanos
        return self.post('/api/catalog/cleanup', **body)

    def snapshot(self, c):
        return [c.execute('SELECT COUNT(*),COALESCE(SUM(quantity),0) FROM inventory_movements').fetchone()[:], c.execute('SELECT COUNT(*) FROM invoice_items').fetchone()[0],
                c.execute('SELECT COUNT(*) FROM quote_items').fetchone()[0], c.execute('SELECT COUNT(*) FROM proforma_items').fetchone()[0]]

    def test_inactive_without_dependencies_is_deleted_with_record_and_audit(self):
        iid = self.item('Cable ficticio sin uso')
        with app.connect() as c:c.execute("INSERT INTO catalog_images(item_id,mime,data,updated_at) VALUES (?,'image/png',x'89504e47','2026-11-09')", (iid,));c.commit()
        review = self.cleanup(action='review', ids=[iid])['body']
        self.assertEqual((review['deletable'], review['protected'], review['rows'][0]['state']), (1, 0, 'eliminable'))
        self.assertEqual(self.cleanup(action='delete', ids=[iid])['status'], 400)  # sin confirmación no se ejecuta
        done = self.cleanup(action='delete', ids=[iid], confirm=True)['body']
        self.assertEqual([d['id'] for d in done['deleted']], [iid])
        with app.connect() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM catalog_items WHERE id=?', (iid,)).fetchone())
            self.assertEqual(c.execute('SELECT COUNT(*) FROM catalog_images WHERE item_id=?', (iid,)).fetchone()[0], 0)
            rec = c.execute('SELECT name,outcome,user_id,code FROM catalog_removals WHERE item_id=?', (iid,)).fetchone()
            self.assertEqual((rec['name'], rec['outcome'], rec['user_id']), ('Cable ficticio sin uso', 'eliminado', 1));self.assertTrue(rec['code'].startswith('PS-'))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='catalog_item_deleted' AND entity_id=?", (iid,)).fetchone()[0], 1)
            with self.assertRaises(Exception):c.execute('DELETE FROM catalog_removals')
        history = self.request('/api/catalog/removals', cookie=self.cookie)['body']['rows']
        self.assertEqual((history[0]['name'], history[0]['outcome'], history[0]['actor']), ('Cable ficticio sin uso', 'eliminado', 'Persona de prueba'))

    def test_sales_invoices_licenses_and_inventory_are_protected(self):
        cases = {'proforma_items': 'catalog_id', 'invoice_items': 'catalog_id', 'license_sale_items': 'product_id', 'license_units': 'product_id', 'inventory_items': 'catalog_id'}
        ids = {}
        for table, column in cases.items():
            ids[table] = self.item('Producto ficticio %s' % table)
            self.reference(table, column, ids[table])
        with app.connect() as c:before = self.snapshot(c)
        review = self.cleanup(action='review', ids=list(ids.values()))['body']
        self.assertEqual((review['deletable'], review['protected']), (0, len(cases)))
        labels = {r['id']: ' '.join(x['label'] for x in r['reasons']) for r in review['rows']}
        self.assertIn('proformas y ventas', labels[ids['proforma_items']]);self.assertIn('facturas electrónicas', labels[ids['invoice_items']])
        self.assertIn('ventas de licencias', labels[ids['license_sale_items']]);self.assertIn('ficha de inventario', labels[ids['inventory_items']])
        done = self.cleanup(action='delete', ids=list(ids.values()), confirm=True)['body']
        self.assertEqual((done['deleted'], len(done['kept'])), ([], len(cases)))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM catalog_items WHERE id IN (%s)' % ','.join(map(str, ids.values()))).fetchone()[0], len(cases))
            self.assertEqual(self.snapshot(c), before)

    def test_products_used_in_technical_orders_are_protected(self):
        iid = self.item('Pasta térmica ficticia', category='repuesto', available=True)
        order = self.post('/api/orders', **self.order_data({'request_key': 'catalog-cleanup-order-0001'}))['body']
        quote = self.post('/api/orders/%d/quote' % order['id'])['body']['id']
        saved = self.post('/api/quotes/%d' % quote, action='save', items=[{'catalog_id': iid, 'description': 'Pasta térmica ficticia', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 1500, 'taxed': True}])
        self.assertEqual(saved['status'], 200, saved['body'])
        with app.connect() as c:c.execute('UPDATE catalog_items SET available=0 WHERE id=?', (iid,));c.commit()
        row = self.cleanup(action='review', ids=[iid])['body']['rows'][0]
        self.assertEqual((row['state'], row['orders']), ('protegido', 1));self.assertIn('presupuestos de órdenes técnicas', row['message'])
        self.assertEqual(self.cleanup(action='delete', ids=[iid], confirm=True)['body']['deleted'], [])
        with app.connect() as c:self.assertEqual(c.execute('SELECT catalog_id FROM quote_items WHERE quote_id=?', (quote,)).fetchone()[0], iid)

    def test_bulk_partial_delete_archives_protected_and_never_touches_active(self):
        free = [self.item('Libre ficticio %d' % n) for n in range(3)]
        used = self.item('Usado ficticio');self.reference('invoice_items', 'catalog_id', used)
        active = self.item('Activo ficticio', available=True)
        review = self.cleanup(action='review', ids=free + [used, active])['body']
        self.assertEqual((review['deletable'], review['protected'], review['active']), (3, 1, 1))
        done = self.cleanup(action='delete', ids=free + [used, active], confirm=True, archive_protected=True)['body']
        self.assertEqual((sorted(d['id'] for d in done['deleted']), [a['id'] for a in done['archived']], [s['id'] for s in done['skipped']]), (sorted(free), [used], [active]))
        rows = self.rows()
        self.assertTrue(rows[used]['archived']);self.assertEqual(rows[used]['refs'], 1);self.assertIn(active, rows);self.assertTrue(rows[active]['available'])
        self.assertFalse(any(i in rows for i in free))
        # Archivado: fuera del catálogo operativo (presupuestos, ADI), consultable en la lista completa y restaurable.
        operational = {r['id'] for r in self.request('/api/catalog', cookie=self.cookie)['body']['rows']}
        self.assertNotIn(used, operational);self.assertIn(active, operational)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT outcome FROM catalog_removals WHERE item_id=?", (used,)).fetchone()[0], 'archivado')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_items WHERE catalog_id=?', (used,)).fetchone()[0], 1)
        back = self.cleanup(action='restore', ids=[used], confirm=True)['body']
        self.assertEqual([r['id'] for r in back['restored']], [used]);self.assertFalse(self.rows()[used]['archived'])
        # Activar un archivado lo devuelve al catálogo operativo.
        self.cleanup(action='archive', ids=[used], confirm=True)
        self.post('/api/catalog', id=str(used), name='Usado ficticio', description='Ficticio', category='otro', brand='', price='10.00', price_mode='incluido', license_term='', devices='', available=True)
        self.assertFalse(self.rows()[used]['archived'])

    def test_inventory_archive_lots_count_as_archived(self):
        iid = self.item('Archivado por inventario ficticio')
        with app.connect() as c:
            c.execute("INSERT INTO inventory_reinit_batches(code,reason,items,summary,created_by,created_at) VALUES ('AR-000099','Prueba ficticia','{\"inventory\": [], \"catalog\": [%d]}','[]',1,'2026-11-09T10:00:00')" % iid);c.commit()
        self.assertTrue(self.rows()[iid]['archived'])
        self.assertTrue(self.cleanup(action='review', ids=[iid])['body']['rows'][0]['deletable'])

    def test_permissions_and_validation(self):
        iid = self.item('Permisos ficticio')
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=1");c.commit()
        try:
            self.assertEqual(self.cleanup(action='delete', ids=[iid], confirm=True)['status'], 403)
            self.assertEqual(self.cleanup(action='review', ids=[iid])['status'], 403)
            self.assertFalse(any(r.get('archived') for r in self.rows().values()))
        finally:
            with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE id=1");c.commit()
        self.assertEqual(self.cleanup(action='delete', ids=[], confirm=True)['status'], 400)
        self.assertEqual(self.cleanup(action='borrar', ids=[iid], confirm=True)['status'], 400)
        self.assertEqual(self.request('/api/catalog/cleanup', {'action': 'review', 'ids': str(iid)})['status'], 401)

    def test_price_history_is_kept_so_the_product_is_only_archived(self):
        iid = self.item('Precio cambiado ficticio', available=True)
        self.post('/api/catalog', id=str(iid), name='Precio cambiado ficticio', description='Ficticio', category='otro', brand='', price='12.00', price_mode='incluido', license_term='', devices='', available=False)
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM catalog_price_history WHERE item_id=?', (iid,)).fetchone()[0], 1)
        row = self.cleanup(action='review', ids=[iid])['body']['rows'][0]
        self.assertEqual(row['state'], 'protegido');self.assertIn('historial de precios', row['message'])
        self.assertEqual([a['id'] for a in self.cleanup(action='delete', ids=[iid], confirm=True, archive_protected=True)['body']['archived']], [iid])

    def test_unknown_foreign_key_also_protects(self):
        iid = self.item('Red de seguridad ficticio')
        with app.connect() as c:
            c.execute('CREATE TABLE tabla_futura_ficticia(id INTEGER PRIMARY KEY, producto INTEGER REFERENCES catalog_items(id))')
            c.execute('INSERT INTO tabla_futura_ficticia(producto) VALUES (?)', (iid,));c.commit()
        row = self.cleanup(action='review', ids=[iid])['body']['rows'][0]
        self.assertEqual(row['state'], 'protegido');self.assertIn('tabla_futura_ficticia', row['message'])


if __name__ == '__main__':
    unittest.main()
