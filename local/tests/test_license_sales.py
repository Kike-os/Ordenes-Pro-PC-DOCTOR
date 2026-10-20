"""Ventas de licencias independientes de las órdenes técnicas: número propio, carrito, reservas, pagos, entrega, cancelación y
correo sin claves. Datos ficticios en una base temporal."""
import base64
import unittest
from unittest.mock import patch
import test_app,test_licenses
import app,licenses,license_sales
from test_licenses import SERIAL,PNG,PDF


class LicenseSalesTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request
    login=test_app.SecurityTests.login
    order_data=test_app.SecurityTests.order_data
    _base=vars(test_licenses.LicenseProTests)
    admin=_base['admin'];new_product=_base['new_product'];client_id=_base['client_id'];unit=_base['unit'];today=_base['today']

    def stock(self,pid,prefix,count):
        if count:self.assertEqual(self.post('/api/licenses/units/bulk',product_id=str(pid),lines='\n'.join('%s-%04d'%(prefix,n) for n in range(count)))['status'],201)

    def catalog(self):
        """Dos productos: antivirus (3 claves) y Microsoft 365 (2 cuentas)."""
        self.admin()
        av=self.new_product(name='Bitdefender Antivirus Plus ficticio',key='BITD-FICT-0000')['product_id'];self.stock(av,'BITD-FICT-X',2)
        ms=self.new_product(name='Microsoft 365 ficticio',line='microsoft',key='M365-FICT-0000',price='99,90')['product_id'];self.stock(ms,'M365-FICT-X',1)
        return av,ms,self.client_id()

    def sale(self,client,items,**extra):
        return self.post('/api/licenses/sales',**dict(dict(client_id=str(client),items=items),**extra))

    def detail(self,sale):return self.get('/api/licenses/sales/%d'%sale)['body']

    def test_cart_sale_without_order_reserves_keys_and_numbers_daily(self):
        av,ms,client=self.catalog()
        made=self.sale(client,[{'product_id':av,'quantity':2,'discount':'5'},{'product_id':ms,'quantity':1}],notes='Venta de mostrador')
        self.assertEqual(made['status'],201,made['body'])
        day=app.reception_now().strftime('%Y%m%d');self.assertEqual(made['body']['code'],'VLIC-%s-0001'%day)
        d=self.detail(made['body']['sale'])
        self.assertEqual((d['subtotal_cents'],d['discount_cents'],d['total_cents'],d['order_id'],d['payment_status'],d['delivery_status']),(2*3000+9990,500,2*3000+9990-500,None,'pendiente','pendiente'))
        self.assertEqual([u['state'] for u in d['units']],['reservada']*3)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE status='disponible'").fetchone()[0],2)
            self.assertIsNone(c.execute('SELECT 1 FROM orders o JOIN devices d ON d.id=o.device_id WHERE d.client_id=? AND o.id>1000000',(client,)).fetchone())
        self.assertNotIn('BITD-FICT',str(d))
        # Las claves reservadas no se ofrecen a otra venta: solo queda 1 antivirus.
        again=self.sale(client,[{'product_id':av,'quantity':2}]);self.assertEqual(again['status'],409);self.assertIn('Solo hay 1',again['body']['error'])
        self.assertEqual(self.sale(client,[{'product_id':av,'quantity':1}])['body']['code'],'VLIC-%s-0002'%day)

    def test_invalid_cart_is_all_or_nothing(self):
        av,ms,client=self.catalog()
        for items,status in (([],400),([{'product_id':av,'quantity':1},{'product_id':av,'quantity':1}],400),([{'product_id':av,'quantity':0}],400),
                             ([{'product_id':av,'quantity':1,'discount':'31'}],400),([{'product_id':av,'quantity':1},{'product_id':ms,'quantity':5}],409)):
            self.assertEqual(self.sale(client,items)['status'],status,items)
        self.assertEqual(self.post('/api/licenses/sales',items=[{'product_id':av,'quantity':1}])['status'],400)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM license_sales').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE status='disponible'").fetchone()[0],5)

    def test_payments_partial_pending_confirmed_and_receipts(self):
        av,ms,client=self.catalog()
        sale=self.sale(client,[{'product_id':av,'quantity':1}],payment={'amount':'10','method':'efectivo','confirmed':True})['body']['sale']
        self.assertEqual(self.detail(sale)['payment_status'],'parcial')
        path='/api/licenses/sales/%d'%sale
        self.assertEqual(self.post(path,action='pay',amount='5',method='transferencia')['status'],400)  # sin referencia ni comprobante
        fake=self.post(path,action='pay',amount='5',method='transferencia',receipt=PDF,receipt_type='image/png');self.assertEqual(fake['status'],400)
        pending=self.post(path,action='pay',amount='20',method='transferencia',reference='TRX-0001',receipt=PNG,receipt_type='image/png',receipt_name='transferencia.png')
        self.assertEqual(pending['status'],200,pending['body']);d=pending['body']['detail']
        # Por confirmar: no cuenta como pagado.
        self.assertEqual((d['payment_status'],d['paid_cents'],d['pending_cents']),('parcial',1000,2000))
        self.assertEqual(self.post(path,action='pay',amount='1',method='efectivo')['status'],400)  # supera el saldo
        transfer=d['payments'][-1];self.assertTrue(transfer['has_receipt'])
        receipt=self.get('/api/licenses/payments/%d/receipt'%transfer['id']);self.assertEqual(receipt['status'],200);self.assertTrue(receipt['body'].startswith(b'\x89PNG'))
        done=self.post(path,action='confirm_payment',payment_id=str(transfer['id']))['body']['detail'];self.assertEqual((done['payment_status'],done['balance_cents']),('pagado',0))
        voided=self.post(path,action='void_payment',payment_id=str(transfer['id']),reason='Transferencia devuelta por el banco')['body']['detail']
        self.assertEqual((voided['payment_status'],[p['status'] for p in voided['payments']]),('parcial',['confirmado','anulado']))
        with app.connect() as c:
            with self.assertRaises(Exception):c.execute('UPDATE license_sale_payments SET amount_cents=1 WHERE id=?',(transfer['id'],))
            with self.assertRaises(Exception):c.execute('DELETE FROM license_sale_payments')

    def test_delivery_requires_balance_acceptance_and_hides_keys(self):
        av,ms,client=self.catalog()
        sale=self.sale(client,[{'product_id':av,'quantity':2},{'product_id':ms,'quantity':1}])['body']['sale'];path='/api/licenses/sales/%d'%sale
        blocked=self.post(path,action='deliver');self.assertEqual(blocked['status'],409);self.assertIn('accept_balance',blocked['body']['fields'])
        self.assertEqual(self.detail(sale)['delivery_status'],'pendiente')
        today=self.today().isoformat()
        done=self.post(path,action='deliver',accept_balance=True,activated=True,activated_at=today)
        self.assertEqual(done['status'],200,done['body']);self.assertIn('/licencias/',done['body']['link']);self.assertNotIn('BITD',str(done['body']))
        d=self.detail(sale);self.assertEqual(d['delivery_status'],'entregado');self.assertEqual(d['payment_status'],'pendiente')
        self.assertEqual({u['state'] for u in d['units']},{'activa'});self.assertTrue(all(u['expires_at'] for u in d['units']))
        self.assertEqual(self.post(path,action='deliver',accept_balance=True)['status'],409)
        self.assertEqual(self.post(path,action='cancel',reason='Ya no lo quiere')['status'],409)
        with app.connect() as c:
            row=c.execute('SELECT * FROM license_deliveries WHERE id=?',(d['delivery_id'],)).fetchone()
            self.assertEqual((row['kind'],row['client_id'],row['order_id'],row['balance_cents']),('directa',client,None,d['total_cents']))
        self.assertEqual(self.post(path,action='link')['status'],200)

    def test_cancel_requires_voided_payments_and_releases_keys(self):
        av,ms,client=self.catalog()
        sale=self.sale(client,[{'product_id':av,'quantity':2}],payment={'amount':'5','method':'efectivo','confirmed':True})['body']['sale'];path='/api/licenses/sales/%d'%sale
        self.assertEqual(self.post(path,action='cancel',reason='Cliente desiste')['status'],409)
        reserved=self.detail(sale)['units'][0]['id']
        for action in ('release','void'):self.assertEqual(self.post('/api/licenses/units/%d'%reserved,action=action,reason='Intento desde inventario')['status'],409,action)
        pay=self.detail(sale)['payments'][0]['id'];self.post(path,action='void_payment',payment_id=str(pay),reason='Reembolso en efectivo')
        self.assertEqual(self.post(path,action='cancel',reason='x')['status'],400)
        d=self.post(path,action='cancel',reason='Cliente desiste de la compra')['body']['detail']
        self.assertEqual((d['payment_status'],d['delivery_status'],d['units']),('cancelado','cancelado',[]))
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE status='disponible' AND sale_id IS NULL").fetchone()[0],5)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM license_sale_items WHERE sale_id=?',(sale,)).fetchone()[0],1)
            with self.assertRaises(Exception):c.execute('DELETE FROM license_sales')
        self.assertEqual(self.post(path,action='pay',amount='1',method='efectivo')['status'],409)

    def test_order_link_is_optional_and_must_belong_to_client(self):
        av,ms,client=self.catalog()
        self.assertEqual(self.sale(client,[{'product_id':av,'quantity':1}],order_code='PCD-NO-EXISTE')['status'],201)  # sin «vincular» no se usa
        with app.connect() as c:
            order=c.execute('SELECT o.id,o.code FROM orders o JOIN devices d ON d.id=o.device_id WHERE d.client_id=? ORDER BY o.id LIMIT 1',(client,)).fetchone()
            other=c.execute("INSERT INTO clients(name,phone,identification) VALUES ('Otra Persona Ficticia','0990000001','1710034065')").lastrowid
        self.assertEqual(self.sale(client,[{'product_id':av,'quantity':1}],link_order=True)['status'],400)
        self.assertEqual(self.sale(other,[{'product_id':av,'quantity':1}],link_order=True,order_code=order['code'])['status'],409)
        linked=self.sale(client,[{'product_id':ms,'quantity':1}],link_order=True,order_code=order['code'],deliver=True,accept_balance=True)
        self.assertEqual(linked['status'],201,linked['body'])
        self.assertEqual(self.detail(linked['body']['sale'])['order_id'],order['id'])
        with app.connect() as c:
            self.assertTrue(c.execute("SELECT 1 FROM order_history WHERE order_id=? AND comment LIKE ?",(order['id'],'%'+linked['body']['code']+'%')).fetchone())

    def test_sale_and_delivery_in_one_step_sends_mail_without_keys(self):
        av,ms,client=self.catalog();sent=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_institutional',side_effect=lambda *a,**k:sent.append(a)):
            made=self.sale(client,[{'product_id':av,'quantity':1},{'product_id':ms,'quantity':1}],payment={'amount':'129,90','method':'tarjeta','confirmed':True},deliver=True,send_mail=True)
        self.assertEqual(made['status'],201,made['body']);self.assertEqual(made['body']['mail'],'sent')
        subject,body=sent[0][4],sent[0][5]
        self.assertIn(made['body']['code'],subject);self.assertIn('1 × Bitdefender Antivirus Plus ficticio',body);self.assertIn('Instrucciones de activación',body)
        self.assertNotIn('FICT-0000',body);self.assertNotIn('FICT-X',body)
        d=self.detail(made['body']['sale']);self.assertEqual((d['payment_status'],d['delivery_status']),('pagado','entregado'))
        listing=self.get('/api/licenses/sales?q=bitdefender')['body']['rows'];self.assertEqual([r['code'] for r in listing],[made['body']['code']])
        self.assertEqual(self.get('/api/licenses/sales?delivery=pendiente')['body']['rows'],[])

    def test_only_administration(self):
        av,ms,client=self.catalog()
        sale=self.sale(client,[{'product_id':av,'quantity':1}])['body']['sale']
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        for path in ('/api/licenses/sales','/api/licenses/sales/%d'%sale):self.assertEqual(self.get(path)['status'],403,path)
        self.assertEqual(self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':av,'quantity':1}])['status'],403)
        self.assertEqual(self.post('/api/licenses/sales/%d'%sale,action='cancel',reason='Prueba de permisos')['status'],403)


class LicenseSalesDeliveriesViewTests(LicenseSalesTests):
    """Rediseño de Ventas y Entregas: estado por producto, entrega parcial, filtros combinados, reservas solo de presupuestos y registro
    completo de cada entrega, siempre sin claves ni credenciales."""
    order_with_quote=LicenseSalesTests._base['order_with_quote'];approve=LicenseSalesTests._base['approve']
    test_cart_sale_without_order_reserves_keys_and_numbers_daily=test_invalid_cart_is_all_or_nothing=test_payments_partial_pending_confirmed_and_receipts=None
    test_delivery_requires_balance_acceptance_and_hides_keys=test_cancel_requires_voided_payments_and_releases_keys=test_order_link_is_optional_and_must_belong_to_client=None
    test_sale_and_delivery_in_one_step_sends_mail_without_keys=test_only_administration=None

    def rows(self,**query):
        from urllib.parse import urlencode
        return self.get('/api/licenses/sales?'+urlencode(query))['body']['rows']

    def test_item_states_partial_delivery_and_responsible(self):
        av,ms,client=self.catalog()
        sale=self.sale(client,[{'product_id':av,'quantity':2},{'product_id':ms,'quantity':1}])['body']['sale']
        row=self.rows()[0];self.assertEqual((row['delivery_view'],row['delivery_view_label']),('pendiente','Pendiente de entrega'))
        self.assertEqual([(i['product_name'],i['quantity'],i['delivery_state']) for i in row['items']],[('Bitdefender Antivirus Plus ficticio',2,'pendiente'),('Microsoft 365 ficticio',1,'pendiente')])
        self.assertTrue(all('has_logo' in i for i in row['items']))
        self.post('/api/licenses/sales/%d'%sale,action='deliver',accept_balance=True)
        row=self.rows()[0];self.assertEqual(row['delivery_view'],'entregado');self.assertEqual({i['delivery_state'] for i in row['items']},{'entregado'})
        with app.connect() as c:name=c.execute('SELECT name FROM users WHERE id=?',(self.uid,)).fetchone()[0]
        self.assertEqual(row['delivered_name'],name)
        # Una devolución de una de las dos claves deja la venta y ese producto en «Entrega parcial»; los datos no se borran.
        unit=next(u for u in self.detail(sale)['units'] if u['product']=='Bitdefender Antivirus Plus ficticio')
        self.assertEqual(self.post('/api/licenses/units/%d'%unit['id'],action='void',reason='Devolución autorizada por el cliente')['status'],200)
        row=self.rows()[0];self.assertEqual((row['delivery_status'],row['delivery_view'],row['delivery_view_label']),('entregado','parcial','Entrega parcial'))
        self.assertEqual([(i['delivered'],i['returned'],i['delivery_state']) for i in row['items']],[(1,1,'parcial'),(1,0,'entregado')])
        self.assertNotIn('FICT-X',str(row));self.assertNotIn('FICT-0000',str(row))
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM license_sale_items WHERE sale_id=?',(sale,)).fetchone()[0],2)

    def test_search_by_number_client_identification_product_and_combined_filters(self):
        av,ms,client=self.catalog()
        paid=self.sale(client,[{'product_id':ms,'quantity':1}],payment={'amount':'99,90','method':'efectivo','confirmed':True})['body']
        due=self.sale(client,[{'product_id':av,'quantity':1}])['body']
        for q,expected in ((paid['code'],[paid['code']]),('0100000017',[due['code'],paid['code']]),('microsoft',[paid['code']]),('no-existe-xyz',[])):
            self.assertEqual([r['code'] for r in self.rows(q=q)],expected,q)
        self.assertEqual([r['code'] for r in self.rows(payment='pagado',delivery='pendiente')],[paid['code']])
        self.assertEqual([r['code'] for r in self.rows(q='bitdefender',payment='pagado')],[])
        self.assertEqual([r['code'] for r in self.rows(q='bitdefender',payment='pendiente',delivery='pendiente')],[due['code']])

    def test_reservations_only_from_approved_quotes_grouped_and_history_by_product(self):
        av,ms,client=self.catalog()
        order,quote=self.order_with_quote(av,quantity=2);self.assertEqual(self.approve(quote)['status'],200)
        with app.connect() as c:code=c.execute('SELECT code FROM orders WHERE id=?',(order,)).fetchone()[0]
        # Una venta vinculada a la misma orden reserva su clave, pero no aparece como reserva de presupuesto.
        self.sale(client,[{'product_id':ms,'quantity':1}],link_order=True,order_code=code)
        waiting=self.get('/api/licenses/deliveries')['body']['waiting'];row=next(w for w in waiting if w['order_id']==order)
        self.assertEqual(len(row['reserved']),2);self.assertEqual(row['client_id'],client)
        self.assertEqual([(g['product'],g['quantity'],g['state']) for g in row['groups']],[('Bitdefender Antivirus Plus ficticio',2,'Reservada, pendiente de entrega')])
        self.assertTrue(row['groups'][0]['quote']);self.assertTrue(row['groups'][0]['reserved_at']);self.assertNotIn('FICT-X',str(waiting))
        self.assertEqual(self.post('/api/licenses/deliver',order_id=str(order),accept_balance=True)['status'],200)
        self.assertEqual(self.post('/api/licenses/deliver',order_id=str(order),accept_balance=True)['status'],409)  # sin entregas duplicadas
        data=self.get('/api/licenses/deliveries')['body'];self.assertFalse([w for w in data['waiting'] if w['order_id']==order and w['reserved']])
        entry=data['history'][0];self.assertEqual((entry['client_id'],entry['order_id'],entry['sale_code']),(client,order,''))
        self.assertEqual([(g['product'],g['count'],g['delivered'],len(g['codes'])) for g in entry['products']],[('Bitdefender Antivirus Plus ficticio',2,2,2)])
        self.assertTrue(all(code.startswith('LIC-') for code in entry['products'][0]['codes']));self.assertNotIn('FICT-X',str(data))

    def test_delivery_log_lists_events_without_keys_and_is_admin_only(self):
        av,ms,client=self.catalog()
        sale=self.sale(client,[{'product_id':av,'quantity':1},{'product_id':ms,'quantity':1}],deliver=True,accept_balance=True)['body']
        delivery=self.detail(sale['sale'])['delivery_id']
        log=self.get('/api/licenses/deliveries/%d/events'%delivery);self.assertEqual(log['status'],200)
        events=log['body']['rows'];self.assertTrue(events);self.assertTrue(all(e['created_at'] and e['actor'] for e in events))
        self.assertEqual({e['unit_code'] for e in events if e['unit_code']},{u['code'] for u in self.detail(sale['sale'])['units']})
        self.assertNotIn('FICT-X',str(events));self.assertNotIn('FICT-0000',str(events))
        history=self.get('/api/licenses/deliveries')['body']['history'][0];self.assertEqual(history['sale_code'],sale['code'])
        self.assertEqual(self.get('/api/licenses/deliveries/999999/events')['status'],404)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(self.get('/api/licenses/deliveries/%d/events'%delivery)['status'],403)


if __name__=='__main__':unittest.main()
