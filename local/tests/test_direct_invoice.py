"""Factura directa (borrador, cobro con pago mixto, emisión en pruebas sin simular autorizaciones, sin duplicados) y archivo de productos
físicos (vista previa, bloqueos, licencias intactas, nombres y códigos liberados para volver a registrarlos). Base temporal y datos ficticios."""
import json
import unittest

import test_app
import test_invoicing
import test_inventory_center as base
import app

ITEMS = json.dumps([{'kind': 'servicio', 'code': 'SRV-01', 'description': 'Instalación ficticia', 'quantity': '1', 'unit_price': '50,00'},
                    {'kind': 'servicio', 'description': 'Configuración ficticia', 'quantity': '2', 'unit_price': '15,00'}])


class DirectInvoiceTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure
    admin, category, new, more = (getattr(base.InventoryCenterTests, n) for n in ('admin', 'category', 'new', 'more'))

    def test_direct_invoice_draft_mixed_payment_emission_and_no_duplicates(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        setup = self.request('/api/invoicing/direct-setup', cookie=cookie)['body']
        self.assertEqual((setup['tax_rate_bp'], setup['doc_types'], setup['seller']), (1500, {'01': 'Factura'}, 'Persona de prueba'))
        draft = post('/api/proformas', origin='directa', items=ITEMS, client_name='Cliente Ficticio', client_identification='0100000017', request_key='factura-directa-0000001')
        self.assertEqual((draft['status'], draft['body']['proforma']['status'], draft['body']['totals']['total_cents']), (200, 'borrador', 8000))  # «Guardar borrador»
        pid = draft['body']['id']
        self.assertEqual([i['code'] for i in self.request('/api/proformas/%d' % pid, cookie=cookie)['body']['items']], ['SRV-01', ''])  # código propio de la partida manual
        r = post('/api/bank-accounts', action='save', bank='Banco Ficticio', account_type='ahorros', number='0011223344', holder='TITULAR FICTICIO', holder_id='0100000017')
        acc = r['body']['rows'][0]['id']
        too_much = post('/api/proformas/%d' % pid, action='checkout', payments=json.dumps([{'method': 'efectivo', 'amount': '90'}]))
        self.assertEqual(too_much['status'], 400)
        self.assertEqual(self.request('/api/proformas/%d' % pid, cookie=cookie)['body']['proforma']['status'], 'borrador')  # todo se deshizo
        pays = json.dumps([{'method': 'efectivo', 'amount': '30,00'}, {'method': 'transferencia', 'amount': '50,00', 'bank_account_id': str(acc), 'reference': 'TRX-DIRECTA-1'}])
        made = post('/api/proformas/%d' % pid, action='checkout', payments=pays, emit='1', internal_note='Entregar con funda (nota interna ficticia)', request_key='cobro-directa-000001')
        self.assertEqual(made['status'], 200, made['body'])
        inv = made['body']['invoice']
        self.assertIn('Faltan datos fiscales', made['body']['emit_error'])  # sin configuración fiscal no se emite ni se simula nada
        self.assertEqual((inv['status'], inv['total_cents'], made['body']['balance_cents']), ('borrador', 8000, 0))
        self.assertEqual(sorted((p['method'], p['amount_cents']) for p in made['body']['payments']), [('efectivo', 3000), ('transferencia', 5000)])
        again = post('/api/proformas/%d' % pid, action='checkout', payments=pays, request_key='cobro-directa-000001')
        self.assertEqual(again['body']['invoice_id'], made['body']['invoice_id'])  # sin facturas duplicadas
        with app.connect() as c:
            self.assertEqual(tuple(c.execute("SELECT COUNT(*),COUNT(DISTINCT operation_id) FROM advances WHERE proforma_id=?", (pid,)).fetchone()), (2, 1))
        self.configure(post)
        emitted = post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')['body']['invoice']
        self.assertEqual((emitted['status'], emitted['environment']), ('pendiente', '1'))  # emitida en pruebas: nunca «autorizada»

    def test_physical_products_are_archived_without_touching_licenses(self):
        self.admin()
        cat = self.category('SSD SATA 2.5"', 'Almacenamiento')
        made = self.new(cat, 'Kingston', 'A400 480 GB', units=['AR-1'], cost='20,00', sku='SA400-480', barcode='7509990001112')
        self.assertEqual(made['status'], 200, made['body'])
        item = made['body']['item']['id']
        with app.connect() as c:
            licenses = c.execute('SELECT status,COUNT(*) FROM license_units GROUP BY status').fetchall()
            catalog_before = c.execute("SELECT COUNT(*) FROM catalog_items WHERE category NOT IN ('repuesto','otro')").fetchone()[0]
        preview = self.get('/api/inventory/archive')['body']
        row = next(r for r in preview['inventory'] if r['id'] == item)
        self.assertTrue(row['blockers'])  # tiene existencias: primero se reinicializa
        self.assertEqual(self.post('/api/inventory/archive', item_ids=str(item), reason='Limpieza del catálogo (ficticia)', confirm='ARCHIVAR')['status'], 409)
        self.assertEqual(self.post('/api/inventory/reinitialize', item_ids=str(item), reason='Reingreso del inventario (ficticio)', confirm='REINICIALIZAR')['status'], 200)
        self.assertEqual(self.post('/api/inventory/archive', item_ids=str(item), reason='Limpieza del catálogo (ficticia)', confirm='NO')['status'], 400)
        done = self.post('/api/inventory/archive', item_ids=str(item), reason='Limpieza del catálogo (ficticia)', confirm='ARCHIVAR', request_key='archivo-prueba-0000001')
        self.assertEqual(done['status'], 200, done['body'])
        self.assertEqual(self.post('/api/inventory/archive', item_ids=str(item), reason='Limpieza del catálogo (ficticia)', confirm='ARCHIVAR', request_key='archivo-prueba-0000001')['body']['duplicate'], True)
        self.assertNotIn(item, [p['id'] for p in self.get('/api/inventory/products')['body']['rows']])  # fuera del catálogo activo
        self.assertIn(item, [p['id'] for p in self.get('/api/inventory/products?state=archivado')['body']['rows']])
        self.assertTrue(self.get('/api/inventory/kardex?item_id=%d' % item)['body']['rows'])  # el historial sigue disponible
        self.assertNotIn(item, [r['item_id'] for r in self.get('/api/inventory/kardex')['body']['rows']])  # el Kardex general queda como nuevo
        self.assertIn(item, [r['item_id'] for r in self.get('/api/inventory/kardex?archived=1')['body']['rows']])
        self.assertEqual(self.get('/api/inventory/center')['body']['cards']['moves_week'], 0)
        with app.connect() as c:
            row = c.execute('SELECT i.active,i.sku,i.barcode,i.alerts_enabled,g.available,g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.id=?', (item,)).fetchone()
            self.assertEqual(tuple(row)[:5], (0, '', '', 0, 0));self.assertIn('(archivado AR-', row['name'])
            self.assertEqual(c.execute('SELECT status,COUNT(*) FROM license_units GROUP BY status').fetchall(), licenses)  # licencias intactas
            self.assertEqual(c.execute("SELECT COUNT(*) FROM catalog_items WHERE category NOT IN ('repuesto','otro')").fetchone()[0], catalog_before)
        # El mismo producto se vuelve a registrar con datos actualizados (nombre, SKU, código de barras y serie liberados).
        again = self.new(cat, 'Kingston', 'A400 480 GB', units=['AR-1'], cost='22,00', sku='SA400-480', barcode='7509990001112')
        self.assertEqual(again['status'], 200, again['body'])


if __name__ == '__main__':
    unittest.main()
