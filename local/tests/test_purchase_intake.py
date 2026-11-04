"""Ingreso de mercadería por proveedor (base temporal, datos ficticios): factura XML del SRI con vista previa, relación de productos y duplicados;
comprobante adjunto; ingreso sin factura; corrección de borradores y de lo confirmado; series protegidas; Centro de Proveedores y Kardex."""
import base64
import json
import unittest

import test_app
import app
import inventory
import purchase_intake
import test_inventory_center

RUC = '1790012345001'


def clave(serial='000000123', ambiente='2'):
    body = '31102026' + '01' + RUC + ambiente + '001001' + serial + '12345678' + '1'
    assert len(body) == 48
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(body)))
    check = 11 - total % 11
    return body + str(0 if check == 11 else 1 if check == 10 else check)


def linea(code, name, qty='2.000000', price='50.00', discount='0.00', total='100.00', rate='15.00', tax='15.00'):
    return ('<detalle><codigoPrincipal>%s</codigoPrincipal><descripcion>%s</descripcion><cantidad>%s</cantidad><precioUnitario>%s</precioUnitario><descuento>%s</descuento>'
            '<precioTotalSinImpuesto>%s</precioTotalSinImpuesto><impuestos><impuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje><tarifa>%s</tarifa><baseImponible>%s</baseImponible><valor>%s</valor></impuesto></impuestos></detalle>'
            % (code, name, qty, price, discount, total, rate, total, tax))


def factura(lines=None, serial='000000123', ambiente='2', subtotal='100.00', total='115.00', key=None, buyer='1790000000001', cod='01'):
    lines = lines or [linea('SSD-480', 'Disco SSD Ficticio 480 GB')]
    return ('<?xml version="1.0" encoding="UTF-8"?><factura id="comprobante" version="1.1.0"><infoTributaria><ambiente>%s</ambiente><razonSocial>DISTRIBUIDORA FICTICIA S.A.</razonSocial><nombreComercial>DISFIC</nombreComercial>'
            '<ruc>%s</ruc><claveAcceso>%s</claveAcceso><codDoc>%s</codDoc><estab>001</estab><ptoEmi>001</ptoEmi><secuencial>%s</secuencial><dirMatriz>Av. Ficticia 123</dirMatriz></infoTributaria>'
            '<infoFactura><fechaEmision>30/10/2026</fechaEmision><razonSocialComprador>PC-DOCTOR</razonSocialComprador><identificacionComprador>%s</identificacionComprador><totalSinImpuestos>%s</totalSinImpuestos><totalDescuento>0.00</totalDescuento><importeTotal>%s</importeTotal></infoFactura>'
            '<detalles>%s</detalles></factura>' % (ambiente, RUC, key or clave(serial, ambiente), cod, serial, buyer, subtotal, total, ''.join(lines)))


def autorizada(xml, estado='AUTORIZADO'):
    return ('<?xml version="1.0"?><autorizacion><estado>%s</estado><numeroAutorizacion>%s</numeroAutorizacion><fechaAutorizacion>2026-10-30T10:00:00-05:00</fechaAutorizacion><ambiente>PRODUCCIÓN</ambiente><comprobante><![CDATA[%s]]></comprobante></autorizacion>'
            % (estado, clave(), xml)).encode('utf-8')


def b64(raw):
    return base64.b64encode(raw if isinstance(raw, bytes) else raw.encode('utf-8')).decode()


class PurchaseIntakeTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login, test_app.SecurityTests.order_data
    admin, category, new, more, technician = (getattr(test_inventory_center.InventoryCenterTests, n) for n in ('admin', 'category', 'new', 'more', 'technician'))

    def product(self, model, sku='', serial=True):
        fields = dict(category_id=str(self.category('SSD SATA 2.5"', 'Almacenamiento')), brand='Ficticia', model=model, price='60,00', min_stock='0', tracking='serie' if serial else 'granel', sku=sku)
        made = self.post('/api/inventory/products', action='save', **fields)
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['id']

    def supplier(self, name='Proveedor Ficticio', identification=RUC, **extra):
        made = self.post('/api/inventory/suppliers', action='save', name=name, identification=identification, **extra)
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['id']

    def stock(self, item):
        with app.connect() as c:
            return c.execute('SELECT COALESCE(SUM(direction*quantity),0) FROM inventory_movements WHERE item_id=?', (item,)).fetchone()[0]

    def draft(self, supplier, lines, **extra):
        made = self.post('/api/inventory/purchases', action='save', supplier_id=str(supplier), issue_date='2026-10-30', items=json.dumps(lines), **dict({'document_number': '001-001-000000999'}, **extra))
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['id']

    def act(self, pid, **body):
        return self.post('/api/inventory/purchases/%d' % pid, **body)

    def test_xml_preview_mapping_duplicates_and_kardex(self):
        self.admin()
        item = self.product('SSD 480')
        sup = self.supplier()
        raw = autorizada(factura())
        before = self.request('/api/inventory/purchases', cookie=self.cookie)['body']['rows']
        view = self.post('/api/inventory/purchases/xml', file=b64(raw))
        self.assertEqual(view['status'], 200, view['body'])
        data = view['body']
        self.assertEqual((data['supplier_match']['id'], data['document_number'], data['authorized'], data['total_cents'], data['lines'][0]['unit_cost_cents'], data['lines'][0]['tax_rate_bp']), (sup, '001-001-000000123', True, 11500, 5000, 1500))
        self.assertEqual(self.request('/api/inventory/purchases', cookie=self.cookie)['body']['rows'], before)  # la vista previa no escribe
        mapping = [{'line': 0, 'item_id': item, 'serials': ['XML-SER-1', 'XML-SER-2']}]
        made = self.post('/api/inventory/purchases/from-xml', file=b64(raw), mapping=json.dumps(mapping), name='factura.xml')
        self.assertEqual(made['status'], 200, made['body'])
        pid = made['body']['id']
        self.assertEqual(self.stock(item), 0)  # borrador: no mueve existencias ni Kardex
        detail = self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']
        self.assertEqual((detail['status'], detail['source'], detail['access_key'], detail['files'][0]['kind']), ('borrador', 'xml', clave(), 'xml'))
        self.assertEqual(self.post('/api/inventory/purchases/from-xml', file=b64(raw), mapping=json.dumps(mapping))['status'], 409)  # duplicada
        self.assertEqual(self.act(pid, action='receive')['status'], 200)
        self.assertEqual(self.stock(item), 2)
        with app.connect() as c:
            move = c.execute("SELECT * FROM inventory_movements WHERE reference_kind='compra' AND reference_id=?", (pid,)).fetchone()
            units = c.execute('SELECT serial,unit_cost_cents FROM inventory_units WHERE entry_movement_id=? ORDER BY id', (move['id'],)).fetchall()
        self.assertEqual((move['supplier_id'], move['document'], move['tax_rate_bp'], move['unit_cost_cents']), (sup, '001-001-000000123', 1500, 5000))
        self.assertEqual([tuple(u) for u in units], [('XML-SER-1', 5000), ('XML-SER-2', 5000)])
        self.assertEqual(self.post('/api/inventory/purchases/xml', file=b64(raw))['body']['duplicate']['id'], pid)
        # La próxima factura del proveedor con ese código ya viene relacionada; un producto nuevo se puede crear.
        other = autorizada(factura([linea('SSD-480', 'Otra descripción', qty='1.000000', price='40', total='40.00', tax='6.00')], serial='000000124', subtotal='40.00', total='46.00', key=clave('000000124')))
        self.assertEqual(self.post('/api/inventory/purchases/xml', file=b64(other))['body']['lines'][0]['suggestion']['item_id'], item)

    def test_xml_is_validated_and_nothing_dangerous_is_processed(self):
        self.admin()
        item = self.product('SSD X')
        bad = [b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><factura>&x;</factura>', b'no es xml', autorizada(factura(), estado='NO AUTORIZADO'), factura(key='1' * 49), factura(cod='04'),
               '<?xml version="1.0"?><notaCredito/>', b64('x').encode() * 700000]
        for raw in bad:
            self.assertIn(self.post('/api/inventory/purchases/xml', file=b64(raw))['status'], (400, 409, 413), str(raw)[:60])
        plain = self.post('/api/inventory/purchases/xml', file=b64(factura(ambiente='1')))['body']
        warn = ' '.join(plain['warnings'])
        self.assertIn('no trae la autorización', warn)
        self.assertIn('PRUEBAS', warn)
        sums = self.post('/api/inventory/purchases/xml', file=b64(factura(subtotal='999.00')))['body']
        self.assertIn('no coincide', ' '.join(sums['warnings']))
        # Cantidad con decimales: no se ingresa sin indicar una entera; una línea se puede excluir.
        half = factura([linea('A', 'Cable por metros', qty='1.500000', total='15.00', tax='2.25'), linea('B', 'Disco', qty='1.000000', total='50.00', tax='7.50')], subtotal='65.00', total='74.75')
        self.assertFalse(self.post('/api/inventory/purchases/xml', file=b64(half))['body']['lines'][0]['whole_quantity'])
        new_supplier = dict(create_supplier='1', file=b64(half))
        self.assertEqual(self.post('/api/inventory/purchases/from-xml', mapping=json.dumps([{'line': 0, 'item_id': item}, {'line': 1, 'item_id': item}]), **new_supplier)['status'], 400)
        self.assertEqual(self.post('/api/inventory/purchases/from-xml', mapping=json.dumps([{'line': 1, 'item_id': item}]), **new_supplier)['status'], 400)  # línea sin relacionar
        made = self.post('/api/inventory/purchases/from-xml', mapping=json.dumps([{'line': 0, 'skip': True}, {'line': 1, 'item_id': item}]), **new_supplier)
        self.assertEqual(made['status'], 200, made['body'])
        # El proveedor se creó con los datos de la factura, sin duplicarse.
        rows = self.request('/api/inventory/suppliers', cookie=self.cookie)['body']['rows']
        self.assertEqual([(r['name'], r['identification']) for r in rows if r['identification'] == RUC], [('DISTRIBUIDORA FICTICIA S.A.', RUC)])

    def test_manual_without_invoice_attach_later_and_edit(self):
        self.admin()
        item = self.product('Cable', serial=False)
        sup = self.supplier()
        pid = self.draft(sup, [{'item_id': item, 'quantity': '5', 'unit_cost': '2,00', 'taxed': '1', 'sale_price': '4,50', 'location': 'Bodega B'}], document_number='', source='sin_factura')
        detail = self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']
        self.assertTrue(detail['document_number'].startswith('SF-'))
        self.assertEqual(detail['source'], 'sin_factura')
        self.assertEqual(self.act(pid, action='receive')['status'], 200)
        self.assertEqual(self.stock(item), 5)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT g.price_cents FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.id=?', (item,)).fetchone()[0], 450)
        # El documento puede agregarse después.
        self.assertEqual(self.act(pid, action='header', document_number='001-002-000000777', issue_date='2026-10-29', notes='Factura encontrada')['status'], 200)
        png = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\0' * 64).decode()
        upload = self.post('/api/files/upload', part='0', total='1', data=png)['body']['upload_id']
        self.assertEqual(self.act(pid, action='attach', upload_id=upload, file_name='factura.png')['status'], 200)
        detail = self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']
        self.assertEqual((detail['document_number'], detail['source'], detail['files'][0]['name']), ('001-002-000000777', 'comprobante', 'factura.png'))  # dejó de ser «sin factura»
        self.assertTrue(any('Documento: SF-' in e['detail'] for e in detail['events']))  # queda el dato anterior
        file_id = detail['files'][0]['id']
        self.assertEqual(self.request('/api/inventory/files/%d' % file_id, cookie=self.cookie)['body'][:4], b'\x89PNG')
        self.assertEqual(self.request('/api/inventory/files/%d' % file_id)['status'], 401)
        self.assertEqual(self.post('/api/inventory/files/%d' % file_id, action='discard', reason='Foto equivocada')['status'], 200)
        self.assertEqual(self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']['files'], [])
        # Documento repetido del mismo proveedor: no se duplica.
        bad = self.post('/api/inventory/purchases', action='save', supplier_id=str(sup), document_number='001-002-000000777', issue_date='2026-10-30', items=json.dumps([{'item_id': item, 'quantity': '1', 'unit_cost': '1,00'}]))
        self.assertEqual(bad['status'], 400)

    def test_draft_can_be_edited_discarded_and_entered_again(self):
        self.admin()
        a, b = self.product('Disco A'), self.product('Disco B')
        sup = self.supplier()
        pid = self.draft(sup, [{'item_id': a, 'quantity': '2', 'unit_cost': '10,00', 'serials': ['DR-1']}, {'item_id': b, 'quantity': '1', 'unit_cost': '5,00'}])
        # Quitar un producto y cambiar la cantidad del otro: el borrador no toca existencias.
        self.post('/api/inventory/purchases', action='save', id=str(pid), supplier_id=str(sup), document_number='001-001-000000999', issue_date='2026-10-30', items=json.dumps([{'item_id': a, 'quantity': '3', 'unit_cost': '10,00', 'serials': ['DR-1']}]))
        detail = self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']
        self.assertEqual([(i['item_id'], i['quantity']) for i in detail['items']], [(a, 3)])
        self.assertEqual((self.stock(a), self.stock(b)), (0, 0))
        self.assertEqual(self.act(pid, action='reenter')['status'], 409)  # primero se descarta
        self.assertEqual(self.act(pid, action='void', reason='Registré mal la compra')['status'], 200)
        again = self.act(pid, action='reenter')
        self.assertEqual(again['status'], 200, again['body'])
        new = self.request('/api/inventory/purchases/%d' % again['body']['id'], cookie=self.cookie)['body']
        self.assertEqual((new['status'], new['document_number'], new['items'][0]['serials']), ('borrador', '001-001-000000999', ['DR-1']))
        self.assertEqual(self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']['status'], 'anulada')  # el anterior queda en el historial
        # Serie repetida en el borrador: se avisa antes de confirmar.
        self.assertEqual(self.post('/api/inventory/purchases', action='save', supplier_id=str(sup), document_number='X-1', issue_date='2026-10-30', items=json.dumps([{'item_id': a, 'quantity': '2', 'unit_cost': '1', 'serials': ['RP', 'rp']}]))['status'], 400)

    def test_confirmed_entry_is_corrected_with_controlled_movements(self):
        self.admin()
        a, b, bulk = self.product('Disco A'), self.product('Disco B'), self.product('Pasta', serial=False)
        sup = self.supplier()
        pid = self.draft(sup, [{'item_id': a, 'quantity': '3', 'unit_cost': '10,00', 'serials': ['RV-1', 'RV-2', 'RV-3']}, {'item_id': b, 'quantity': '2', 'unit_cost': '20,00', 'serials': ['RV-4']}, {'item_id': bulk, 'quantity': '10', 'unit_cost': '1,00'}])
        self.assertEqual(self.act(pid, action='receive')['status'], 200)
        detail = self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']
        line_a, line_b, line_bulk = detail['items']
        # Revertir una unidad de un producto no afecta a los demás ni borra nada.
        wrong = next(u for u in line_a['units'] if u['serial'] == 'RV-2')
        undone = self.act(pid, action='reverse', line_id=str(line_a['id']), quantity='1', unit_ids=str(wrong['id']), reason='Serie equivocada')
        self.assertEqual(undone['status'], 200, undone['body'])
        self.assertEqual((self.stock(a), self.stock(b), self.stock(bulk)), (2, 2, 10))
        self.assertEqual(self.act(pid, action='reverse', line_id=str(line_bulk['id']), quantity='4', reason='Eran seis unidades')['status'], 200)
        self.assertEqual(self.stock(bulk), 6)
        self.assertEqual(self.act(pid, action='reverse', line_id=str(line_bulk['id']), quantity='7', reason='Excede lo ingresado')['status'], 400)
        self.assertEqual(self.act(pid, action='reverse', line_id=str(line_bulk['id']), quantity='1', reason='x')['status'], 400)  # motivo obligatorio
        # La serie revertida queda libre para volver a ingresarla bien.
        self.assertEqual(self.more(a, units=['RV-2'], cost='10,00', reason='compra')['status'], 200)
        # Costo: se corrige con auditoría; el movimiento original no cambia y el total se recalcula.
        self.assertEqual(self.act(pid, action='cost', line_id=str(line_b['id']), cost='25,00', reason='Factura con otro valor')['status'], 200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT old_cost_cents,new_cost_cents FROM inventory_cost_corrections').fetchone()[:2], (2000, 2500))
            self.assertEqual(c.execute('SELECT unit_cost_cents FROM inventory_movements WHERE id=?', (line_b['movement_id'],)).fetchone()[0], 2000)
            self.assertEqual(inventory.average_cost(c, b), 2500)
        self.assertEqual(self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']['items'][1]['unit_cost_cents'], 2500)
        # Lo que faltó se agrega como otra partida, también del mismo producto.
        added = self.act(pid, action='add_line', item_id=str(bulk), quantity='3', unit_cost='1,50', taxed='1')
        self.assertEqual(added['status'], 200, added['body'])
        self.assertEqual(self.stock(bulk), 9)
        # Anular revierte solo lo que queda; nada entra en negativo.
        self.assertEqual(self.act(pid, action='void', reason='Compra devuelta completa')['status'], 200)
        self.assertEqual((self.stock(b), self.stock(bulk)), (0, 0))
        self.assertEqual(self.stock(a), 1)  # la RV-2 reingresada aparte se conserva
        kardex = self.request('/api/inventory/kardex?item=%d' % bulk, cookie=self.cookie)['body']
        self.assertTrue(kardex)

    def test_same_product_twice_in_a_purchase(self):
        self.admin()
        item = self.product('Doble', serial=False)
        pid = self.draft(self.supplier(), [{'item_id': item, 'quantity': '2', 'unit_cost': '10,00'}, {'item_id': item, 'quantity': '3', 'unit_cost': '12,00'}])
        self.assertEqual(self.act(pid, action='receive')['status'], 200)
        self.assertEqual(self.stock(item), 5)
        with app.connect() as c:
            self.assertEqual(inventory.average_cost(c, item), 1120)
        self.assertEqual(self.act(pid, action='void', reason='Devuelta al proveedor')['status'], 200)
        self.assertEqual(self.stock(item), 0)

    def test_serials_are_protected_and_traceable(self):
        self.admin()
        item = self.product('SSD Kingston')
        sup = self.supplier()
        pid = self.draft(sup, [{'item_id': item, 'quantity': '4', 'unit_cost': '30,00', 'serials': ['KNG-1', 'KNG-2', 'KNG-3', 'KNG-4']}])
        self.act(pid, action='receive')
        units = self.request('/api/inventory/purchases/%d' % pid, cookie=self.cookie)['body']['items'][0]['units']
        u1, u2, u3, u4 = [u['id'] for u in units]
        url = lambda u: '/api/inventory/units/%d' % u
        # Editar: la serie equivocada se corrige; un duplicado se rechaza; queda quién, cuándo y el dato anterior.
        self.assertEqual(self.post(url(u1), action='serial', serial='KNG-2', reason='Corrección')['status'], 409)
        self.assertEqual(self.post(url(u1), action='serial', serial='KNG-1X', reason='x')['status'], 400)
        self.assertEqual(self.post(url(u1), action='serial', serial='KNG-1X', reason='Error de digitación')['status'], 200)
        detail = self.request(url(u1), cookie=self.cookie)['body']
        self.assertTrue(any('KNG-1 a KNG-1X' in e['detail'] and e['actor'] for e in detail['events']))
        self.assertEqual(self.post(url(u1), action='edit', location='Vitrina')['status'], 200)
        # Eliminar: no se borra; sale con un movimiento y libera la serie. Volver a ingresar: reemplaza en una sola operación.
        self.assertEqual(self.post(url(u2), action='discard', reason='Registro duplicado')['status'], 200)
        self.assertEqual(self.request(url(u2), cookie=self.cookie)['body']['status'], 'devuelta')
        self.assertFalse(self.request('/api/inventory/serial-check?serial=KNG-2', cookie=self.cookie)['body']['exists'])
        again = self.post(url(u3), action='reenter', serial='KNG-3B', reason='Serie mal escrita')
        self.assertEqual(again['status'], 200, again['body'])
        self.assertEqual(self.stock(item), 3)
        self.assertEqual(self.post(url(u3), action='discard', reason='Otra vez')['status'], 409)
        # Una unidad vendida queda protegida.
        with app.connect() as c:
            c.execute("UPDATE inventory_units SET status='vendida' WHERE id=?", (u4,))
            c.commit()
        self.assertEqual(self.post(url(u4), action='serial', serial='KNG-4X', reason='Intento de cambio')['status'], 409)
        self.assertEqual(self.post(url(u4), action='discard', reason='Intento de baja')['status'], 409)
        self.assertEqual(self.post(url(u4), action='reenter', serial='KNG-4Y', reason='Intento de reingreso')['status'], 409)
        self.assertEqual(self.stock(item), 3)
        panel = self.request('/api/inventory/serials?q=KNG&view=todas', cookie=self.cookie)['body']  # la vista por defecto solo muestra lo que está en inventario
        locked = {r['serial']: r['lock'] for r in panel['rows']}
        self.assertIn('vendida', locked['KNG-4'])
        self.assertEqual(locked['KNG-1X'], '')
        # Ningún reinicio: las demás unidades siguen.
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory_units WHERE item_id=?', (item,)).fetchone()[0], 5)

    def test_supplier_center_prevents_duplicates_and_shows_history(self):
        self.admin()
        sup = self.supplier('Distribuidora Uno', trade_name='DisUno', phone='0991234567', whatsapp='0991234567', city='Quito', province='Pichincha', notes='Entrega los lunes')
        self.assertEqual(self.post('/api/inventory/suppliers', action='save', name='Otra', identification=RUC)['status'], 400)
        sinruc = self.supplier('Repuestos Sin RUC', identification='')
        self.assertEqual(self.post('/api/inventory/suppliers', action='save', name='REPUESTOS  sin-ruc', identification='')['status'], 400)
        self.assertEqual(self.post('/api/inventory/suppliers', action='save', name='Teléfono malo', phone='abc')['status'], 400)
        self.assertEqual(self.post('/api/inventory/suppliers', action='save', name='Correo malo', email='no-es')['status'], 400)
        item = self.product('Mismo disco')
        p1 = self.draft(sup, [{'item_id': item, 'quantity': '1', 'unit_cost': '30,00'}])
        p2 = self.draft(sinruc, [{'item_id': item, 'quantity': '1', 'unit_cost': '28,00'}], document_number='B-1')
        self.draft(sinruc, [{'item_id': item, 'quantity': '1', 'unit_cost': '28,00'}], document_number='B-2')
        self.act(p1, action='receive')
        self.act(p2, action='receive')
        center = self.request('/api/inventory/suppliers', cookie=self.cookie)['body']
        self.assertEqual(center['kpis'], {'total': 2, 'active': 2, 'inactive': 0, 'with_purchases': 2})
        self.post('/api/inventory/suppliers', action='deactivate', id=str(sinruc))
        self.assertEqual(self.request('/api/inventory/suppliers', cookie=self.cookie)['body']['kpis']['inactive'], 1)
        sheet = self.request('/api/inventory/suppliers/%d' % sup, cookie=self.cookie)['body']
        self.assertEqual((sheet['supplier']['trade_name'], sheet['supplier']['province'], sheet['count'], sheet['products'][0]['last_cost_cents']), ('DisUno', 'Pichincha', 1, 3000))
        self.assertEqual(sheet['purchases'][0]['items'][0]['name'], sheet['products'][0]['name'])
        other = self.request('/api/inventory/suppliers/%d' % sinruc, cookie=self.cookie)['body']
        self.assertEqual({p['status'] for p in other['purchases']}, {'recibida', 'borrador'})
        # Un mismo producto puede tener varios proveedores, y la ficha los muestra.
        product = self.request('/api/inventory/products/%d/sheet' % item, cookie=self.cookie)['body']
        self.assertEqual({s['name'] for s in product['suppliers']}, {'Distribuidora Uno', 'Repuestos Sin RUC'})
        # Solo administración.
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
            c.commit()
        self.assertEqual(self.request('/api/inventory/suppliers', cookie=self.cookie)['status'], 403)
        self.assertEqual(self.post('/api/inventory/purchases/xml', file=b64(factura()))['status'], 403)


if __name__ == '__main__':
    unittest.main()
