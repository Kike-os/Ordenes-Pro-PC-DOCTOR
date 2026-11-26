"""Smart Catalog & Inventory Pro 3.0: tipos y subcategorías, registro temporal o permanente, coincidencias, depuración en simulación y
real (archivar, nunca borrar), protección comercial, restauración, origen no verificable, galería de fotografías y ejecución desde la
tarea programada del servidor. Base temporal y datos ficticios; no se envía nada."""
import base64
import json
import unittest
from datetime import timedelta

import test_invoicing
import app
import catalog_smart

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')


class SmartCatalogTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def admin(self):
        cookie, csrf = self.login()
        return cookie, csrf, (lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf))

    def item(self, post, name, **extra):
        out = post('/api/catalog', name=name, price='12,50', price_mode='incluido', **extra)
        self.assertEqual(out['status'], 200, out['body'])
        return out['body']['id']

    def quote_with(self, post, item_id, key):
        order = post('/api/orders', **self.order_data({'request_key': 'smart-catalog-order-' + key}))['body']
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        saved = post('/api/quotes/%d' % quote, action='save', items=[{'catalog_id': item_id, 'description': 'Artículo ficticio', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 1250, 'taxed': True}])
        self.assertEqual(saved['status'], 200, saved['body'])
        return quote

    def state(self, item_id, now=None):
        with app.connect() as c:
            return next(r for r in catalog_smart.evaluate(c, now or app.reception_now()) if r['id'] == item_id)

    def test_types_subcategories_and_registration_modes(self):
        cookie, csrf, post = self.admin()
        tax = self.request('/api/catalog/taxonomy', cookie=cookie)['body']
        codes = [t['code'] for t in tax['types']]
        self.assertEqual(codes, ['servicio', 'repuesto', 'producto', 'consumible', 'impresion', 'accesorio', 'licencia', 'componente'])
        consumable = next(t for t in tax['types'] if t['code'] == 'consumible')
        self.assertIn('Tóneres compatibles', [s['name'] for s in consumable['subcategories']])
        self.assertEqual(next(t for t in tax['types'] if t['code'] == 'servicio')['fields'], [])              # un servicio no pide marca, modelo ni foto
        sub = next(s['id'] for s in consumable['subcategories'] if s['name'] == 'Tintas originales')
        from_catalog = self.item(post, 'Tinta ficticia negra 664', type='consumible', subcategory=str(sub), brand='Marca X', model='T664')
        from_quote = self.item(post, 'Cabezal ficticio DX5', type='impresion', origin='presupuesto')
        with app.connect() as c:
            rows = {r['item_id']: dict(r) for r in c.execute('SELECT * FROM catalog_profiles')}
            cats = {r['id']: r['category'] for r in c.execute('SELECT id,category FROM catalog_items')}
        self.assertEqual((rows[from_catalog]['mode'], rows[from_catalog]['origin'], rows[from_catalog]['model'], cats[from_catalog]), ('permanente', 'catalogo', 'T664', 'otro'))
        self.assertEqual((rows[from_quote]['mode'], rows[from_quote]['origin'], cats[from_quote]), ('temporal', 'presupuesto', 'repuesto'))   # categoría base compatible
        bad = post('/api/catalog', name='Artículo ficticio malo', price='1', price_mode='incluido', type='consumible', subcategory='999999')
        self.assertEqual(bad['status'], 400)
        dup = post('/api/catalog', name='  tinta FICTICIA negra   664 ', price='1', price_mode='incluido', type='consumible', check_duplicates=True)
        self.assertEqual(dup['status'], 409);self.assertEqual(dup['body']['duplicates'][0]['id'], from_catalog)     # no se duplica
        added = post('/api/catalog/smart', action='subcategory', type_code='componente', name='Cristales de cuarzo')
        self.assertEqual(added['status'], 200)
        new_type = post('/api/catalog/smart', action='type', label='Equipos reacondicionados', base_category='otro', icon='box', marca=True, modelo=True, foto=True)
        self.assertEqual(new_type['status'], 200);self.assertIn('equipos_reacondicionados', [t['code'] for t in new_type['body']['taxonomy']['types']])

    def test_cleanup_simulation_then_real_archive_and_restore(self):
        cookie, csrf, post = self.admin()
        item = self.item(post, 'Repuesto ficticio temporal', type='repuesto', origin='presupuesto')
        quote = self.quote_with(post, item, '0001')
        self.assertEqual(self.state(item)['state'], 'en_uso')                                                  # presupuesto vigente: plazo suspendido
        old = (app.reception_now() - timedelta(days=40)).isoformat(timespec='seconds')
        with app.connect() as c:
            c.execute("UPDATE quotes SET status='rechazado',decided_at=?,updated_at=? WHERE id=?", (old, old, quote))
            c.execute('UPDATE catalog_items SET created_at=? WHERE id=?', (old, item))
            c.execute('UPDATE catalog_profiles SET created_at=? WHERE item_id=?', (old, item))
            line_before = tuple(c.execute('SELECT description,unit_cents,quantity FROM quote_items WHERE quote_id=?', (quote,)).fetchone())
            c.commit()
        self.assertEqual(self.state(item)['state'], 'pendiente')
        sim = post('/api/catalog/smart', action='run')['body']
        self.assertEqual((sim['result']['mode'], sim['result']['would_clean'], sim['result']['cleaned']), ('simulacion', 1, 0))
        self.assertFalse(self.state(item)['archived'])                                                         # la simulación no toca nada
        self.assertEqual(post('/api/catalog/smart', action='settings', mode='activa')['status'], 400)          # exige confirmación escrita
        self.assertEqual(post('/api/catalog/smart', action='settings', mode='activa', confirm=catalog_smart.CONFIRM_ACTIVATE)['status'], 200)
        real = post('/api/catalog/smart', action='run')['body']['result']
        self.assertEqual(real['cleaned'], 1)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM catalog_items WHERE id=?', (item,)).fetchone()[0], 1)   # archivado, no borrado
            self.assertEqual(tuple(c.execute('SELECT description,unit_cents,quantity FROM quote_items WHERE quote_id=?', (quote,)).fetchone()), line_before)
        listed = [r['id'] for r in self.request('/api/catalog', cookie=cookie)['body']['rows']]
        self.assertNotIn(item, listed)
        self.assertEqual(self.state(item)['state'], 'depurado')
        self.assertEqual(post('/api/catalog/smart', action='restaurar', item_id=str(item))['status'], 200)
        self.assertIn(item, [r['id'] for r in self.request('/api/catalog', cookie=cookie)['body']['rows']])
        self.assertEqual(self.state(item)['state'], 'protegido')                                              # restaurado queda protegido
        events = [e['event'] for e in self.request('/api/catalog/smart', cookie=cookie)['body']['history'] if e['item_id'] == item]
        for expected in ('creado', 'simulacion', 'depurado', 'restaurado'):
            self.assertIn(expected, events)

    def test_commercial_protection_and_reuse_suspends_the_clock(self):
        cookie, csrf, post = self.admin()
        old = (app.reception_now() - timedelta(days=60)).isoformat(timespec='seconds')
        approved = self.item(post, 'Repuesto ficticio aprobado', type='repuesto', origin='presupuesto')
        reused = self.item(post, 'Repuesto ficticio reutilizado', type='repuesto', origin='presupuesto')
        stocked = self.item(post, 'Repuesto ficticio con ficha', type='repuesto', origin='presupuesto')
        kept = self.item(post, 'Repuesto ficticio protegido', type='repuesto', origin='presupuesto')
        q1 = self.quote_with(post, approved, '0002')
        q2 = self.quote_with(post, reused, '0003')
        self.quote_with(post, reused, '0004')                                                                  # otro presupuesto vigente
        with app.connect() as c:
            c.execute("UPDATE quotes SET status='aprobado',decided_at=? WHERE id=?", (old, q1))
            c.execute("UPDATE quotes SET status='rechazado',decided_at=? WHERE id=?", (old, q2))
            for i in (approved, reused, stocked, kept):
                c.execute('UPDATE catalog_items SET created_at=? WHERE id=?', (old, i))
            c.execute("INSERT INTO inventory_items(catalog_id,kind,sku,created_at,updated_at) VALUES(?, 'repuesto', 'SKU-FICT-1', ?, ?)", (stocked, old, old))
            c.commit()
        self.assertEqual(post('/api/catalog/smart', action='proteger', item_id=str(kept), reason='Se usa en campañas')['status'], 200)
        states = {i: self.state(i)['state'] for i in (approved, reused, stocked, kept)}
        self.assertEqual(states, {approved: 'protegido', reused: 'en_uso', stocked: 'protegido', kept: 'protegido'})
        post('/api/catalog/smart', action='settings', mode='activa', confirm=catalog_smart.CONFIRM_ACTIVATE)
        self.assertEqual(post('/api/catalog/smart', action='run')['body']['result']['cleaned'], 0)              # nada protegido se toca

    def test_legacy_items_without_verifiable_origin_are_never_cleaned(self):
        cookie, csrf, post = self.admin()
        old = (app.reception_now() - timedelta(days=90)).isoformat(timespec='seconds')
        with app.connect() as c:
            legacy = c.execute("INSERT INTO catalog_items(name,category,price_cents,taxed,available,created_at,updated_at) VALUES('Producto ficticio antiguo','otro',500,1,1,?,?)", (old, old)).lastrowid
            c.commit()
        row = self.state(legacy)
        self.assertEqual((row['origin'], row['mode'], row['state']), ('desconocido', 'permanente', 'permanente'))
        report = self.request('/api/catalog/smart/report', cookie=cookie)['body']['rows']
        self.assertIn(legacy, [r['id'] for r in report])                                                        # se informa, no se depura

    def test_gallery_validation_permissions_and_cron(self):
        cookie, csrf, post = self.admin()
        item = self.item(post, 'Accesorio ficticio con fotos', type='accesorio')
        ok = post('/api/catalog/%d/gallery' % item, mime='image/png', data=base64.b64encode(PNG).decode(), width='1', height='1')
        self.assertEqual(ok['status'], 200, ok['body']);self.assertEqual(len(ok['body']['gallery']), 1)
        fake = post('/api/catalog/%d/gallery' % item, mime='image/png', data=base64.b64encode(b'no es una imagen').decode())
        self.assertEqual(fake['status'], 400)                                                                    # se valida el contenido real
        pid = ok['body']['gallery'][0]['id']
        self.assertEqual(self.request('/api/catalog/%d/gallery/%d' % (item, pid), cookie=cookie)['body'], PNG)
        self.assertEqual(post('/api/catalog/%d/gallery' % item, action='delete', photo_id=str(pid))['body']['gallery'], [])
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(post('/api/catalog/%d/gallery' % item, mime='image/png', data=base64.b64encode(PNG).decode())['status'], 403)
        self.assertEqual(self.request('/api/cron/reminders')['status'], 200)
        with app.connect() as c:
            self.assertTrue(catalog_smart.settings(c)['last_run'])                                              # la tarea del servidor la ejecuta

    def test_quote_pdf_includes_jpeg_photos_only_when_enabled(self):
        cookie, csrf, post = self.admin()
        jpeg = base64.b64decode('/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=')
        item = self.item(post, 'Teclado ficticio con foto', type='repuesto')
        with app.connect() as c:
            c.execute("INSERT INTO catalog_images(item_id,mime,data,updated_at,updated_by) VALUES(?,?,?,?,?)", (item, 'image/jpeg', jpeg, '2026-11-26T10:00:00-05:00', self.uid));c.commit()
        quote = self.quote_with(post, item, '0009')
        import quotes, quote_pdf
        with app.connect() as c:
            plain = quotes.with_pdf_photos(c, quotes.detail(c, quotes.get(c, quote)))
            self.assertNotIn('pdf_photos', plain)                                                                 # desactivado por defecto
            self.assertEqual(post('/api/catalog/smart', action='settings', quote_photos=True)['status'], 200)
            with_photos = quotes.with_pdf_photos(c, quotes.detail(c, quotes.get(c, quote)))
            self.assertIn(item, with_photos['pdf_photos'])
            order = app.order_document(c, with_photos['order_id'])
        pdf = quote_pdf.render(with_photos, order)
        self.assertTrue(pdf.startswith(b'%PDF'));self.assertIn(b'/DCTDecode', pdf)


if __name__ == '__main__':
    unittest.main()
