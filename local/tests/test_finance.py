"""Saldo real de la orden: total exigible menos pagos netos, por equipo y consolidado. Importes ficticios, siempre en centavos enteros."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,equipment,test_app


class FinanceTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def start(self,units=1,charges=(22000,)):
        """Orden con `units` equipos y los cargos indicados (centavos) en cada uno."""
        self.cookie,self.csrf=self.login();post=lambda path,body:self.request(path,body,cookie=self.cookie,csrf=self.csrf)
        main=post('/api/orders',self.order_data({'serial':'FIN-0001','request_key':'finance-fixture-key-0001'}))['body'];ids=[main['id']]
        for index in range(1,units):ids.append(post('/api/orders',self.order_data({'serial':'FIN-%04d'%(index+1),'request_key':'finance-fixture-key-%04d'%(index+1),'group_order_id':str(main['id']),'new_unit':'1'}))['body']['id'])
        with app.connect() as c:
            for oid,cents in zip(ids,charges):
                if cents:c.execute('INSERT INTO order_budget(order_id,labor_cents) VALUES (?,?)',(oid,cents))
            c.commit()
        return ids

    def pay(self,oid,amount,**extra):return self.request('/api/orders/%d/payments'%oid,dict({'amount':amount,'method':'efectivo'},**extra),cookie=self.cookie,csrf=self.csrf)
    def void(self,oid,pid,reason='Registro ficticio equivocado'):return self.request('/api/orders/%d/payments/void'%oid,{'payment_id':str(pid),'reason':reason},cookie=self.cookie,csrf=self.csrf)
    def finance(self,oid):return self.request('/api/orders/%d/finance'%oid,cookie=self.cookie)['body']['finance']
    def state(self,oid):unit=self.finance(oid)['unit'];return unit['state'],unit['balance_cents'],unit['paid_cents'],unit['credit_cents']

    def test_three_states_follow_the_real_balance(self):
        (oid,)=self.start()
        self.assertEqual(self.state(oid),('pendiente',22000,0,0))                                            # 1. $220,00 sin pagos
        self.assertEqual(self.pay(oid,'180')['status'],201);self.assertEqual(self.state(oid),('parcial',4000,18000,0))  # 2. abono de $180,00
        self.assertEqual(self.pay(oid,'40,00')['status'],201);self.assertEqual(self.state(oid),('pagado',0,22000,0))    # 3. pagado
        summary=self.finance(oid);self.assertEqual((summary['unit']['state_label'],summary['order']['state'],summary['multiple']),('Sin saldo pendiente','pagado',False))
        # La tarjeta, el detalle de la orden y la regla de entrega leen la misma fuente.
        order=self.request('/api/orders/%d'%oid,cookie=self.cookie)['body']['order']
        self.assertEqual((order['money']['state'],order['money']['balance_cents'],order['group']['totals']['paid_cents'],len(order['payments'])),('pagado',0,22000,2))
        self.assertEqual(self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=self.cookie,csrf=self.csrf)['status'],200)

    def test_order_without_charges_is_not_reported_as_paid(self):
        (oid,)=self.start(charges=(0,))
        self.assertEqual(self.state(oid),('sin_cargos',0,0,0));self.assertEqual(self.finance(oid)['unit']['state_label'],'Sin cargos registrados')  # 4
        refused=self.pay(oid,'10');self.assertEqual(refused['status'],400);self.assertIn('no hay cargos',refused['body']['error'])

    def test_voided_payment_and_discount_recalculate(self):
        (oid,)=self.start()
        pid=self.pay(oid,'180')['body']['id'];self.assertEqual(self.void(oid,pid)['body']['balance_cents'],22000);self.assertEqual(self.state(oid),('pendiente',22000,0,0))  # 5
        # 6. Un descuento del presupuesto aprobado reduce el total exigible (el importe de la orden guarda el neto aprobado).
        import quotes
        self.assertEqual(quotes.net(22000,1000),19800)
        with app.connect() as c:c.execute('UPDATE order_budget SET labor_cents=? WHERE order_id=?',(quotes.net(22000,1000),oid));c.commit()
        self.assertEqual(self.state(oid),('pendiente',19800,0,0));self.assertEqual(self.pay(oid,'198.01')['status'],400);self.assertEqual(self.pay(oid,'198')['status'],201);self.assertEqual(self.state(oid)[0],'pagado')

    def test_units_keep_their_own_balance_and_general_payments_count_once(self):
        first,second=self.start(units=2,charges=(22000,10000))
        self.assertEqual(self.pay(first,'20')['status'],201)                                                    # 7. presupuestos independientes
        self.assertEqual((self.state(first),self.state(second)),(('parcial',20000,2000,0),('pendiente',10000,0,0)))
        whole=self.finance(second);self.assertEqual((whole['order']['budget_cents'],whole['order']['paid_cents'],whole['order']['balance_cents'],whole['order']['state'],whole['multiple']),(32000,2000,30000,'parcial',True))
        # 8. Pago general: baja el saldo de la orden, no el de ningún equipo, hasta que se asigna.
        general=self.pay(second,'150',scope='general',method='transferencia',note='Transferencia ficticia 001');self.assertEqual(general['status'],201,general['body'])
        whole=self.finance(first);self.assertEqual((whole['order']['paid_cents'],whole['order']['balance_cents'],whole['order']['general_cents']),(17000,15000,15000))
        self.assertEqual((self.state(first)[1],self.state(second)[1]),(20000,10000))
        self.assertEqual(self.pay(first,'150.01',scope='general')['status'],400)                                 # no supera el saldo de la orden
        blocked=self.request('/api/order-status',{'id':str(second),'status':'entregado'},cookie=self.cookie,csrf=self.csrf);self.assertEqual(blocked['status'],409);self.assertIn('pagos generales sin asignar',blocked['body']['error'])
        assign=lambda oid,**body:self.request('/api/orders/%d/payments/assign'%oid,dict(payment_id=str(general['body']['id']),**body),cookie=self.cookie,csrf=self.csrf)
        self.assertEqual(assign(second,amount='100.01')['status'],400);self.assertEqual(assign(second)['body']['amount_cents'],10000)   # sin importe: lo que falta al equipo
        self.assertEqual((self.state(second),self.finance(first)['order']['general_cents'],self.finance(first)['order']['balance_cents']),(('pagado',0,10000,0),5000,15000))
        self.assertEqual(assign(first,amount='50.01')['status'],400);self.assertEqual(assign(first,amount='50')['status'],201);self.assertEqual(self.finance(first)['order']['general_cents'],0)
        self.assertEqual(assign(first)['status'],400)                                                           # ya no queda nada por asignar
        # El pago pertenece a su orden: otra orden no puede asignarlo ni anularlo.
        other=self.request('/api/orders',self.order_data({'serial':'FIN-9999','request_key':'finance-fixture-key-9999'}),cookie=self.cookie,csrf=self.csrf)['body']['id']
        self.assertEqual(self.request('/api/orders/%d/payments/assign'%other,{'payment_id':str(general['body']['id'])},cookie=self.cookie,csrf=self.csrf)['status'],404);self.assertEqual(self.void(other,general['body']['id'])['status'],404)
        # Entregado el segundo equipo, el pago general que lo cubrió ya no se anula.
        self.assertEqual(self.request('/api/order-status',{'id':str(second),'status':'entregado'},cookie=self.cookie,csrf=self.csrf)['status'],200);self.assertEqual(self.void(first,general['body']['id'])['status'],409)
        rows=self.request('/api/orders/%d'%first,cookie=self.cookie)['body']['order'];self.assertEqual([p['kind'] for p in rows['payments']],['pago','asignacion']);self.assertEqual(len(rows['group']['general_payments']),1)

    def test_double_click_and_retries_do_not_duplicate(self):
        (oid,)=self.start();key='clave-de-solicitud-ficticia-0001'
        first=self.pay(oid,'50',request_key=key);again=self.pay(oid,'50',request_key=key)                        # 9
        self.assertEqual((first['status'],again['status'],again['body']['id'],again['body'].get('duplicate')),(201,200,first['body']['id'],True))
        self.assertEqual(self.state(oid),('parcial',17000,5000,0));self.assertEqual(self.pay(oid,'60',request_key=key)['status'],409);self.assertEqual(self.pay(oid,'10',request_key='corta')['status'],400)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_payments').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='order_payment_recorded'").fetchone()[0],1)
            # Un movimiento registrado no se edita ni se borra.
            for sql in ('UPDATE order_payments SET amount_cents=1','DELETE FROM order_payments',"UPDATE order_payments SET kind='devolucion'"):
                with self.assertRaises(Exception):c.execute(sql)

    def test_invalid_amounts_and_permissions(self):
        (oid,)=self.start()
        for amount in ('-10','0','abc','10.999','',' ','1e3','NaN','99999999'):self.assertEqual(self.pay(oid,amount)['status'],400,amount)
        self.assertEqual(self.pay(oid,'10',kind='regalo')['status'],400);self.assertEqual(self.pay(oid,'10',scope='general')['status'],400)     # orden de un solo equipo
        self.assertEqual(self.request('/api/orders/%d/payments'%oid,{'amount':'10','method':'efectivo'},cookie=self.cookie)['status'],403)      # sin CSRF
        self.assertEqual(self.request('/api/orders/%d/finance'%oid)['status'],401);self.assertEqual(self.request('/api/orders/999999/finance',cookie=self.cookie)['status'],404)
        self.assertEqual(self.pay(oid,'100')['status'],201)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        self.assertEqual(self.pay(oid,'20')['status'],201)                                                       # el técnico registra pagos…
        self.assertEqual(self.pay(oid,'10',kind='devolucion',note='Devolución ficticia')['status'],403)          # …pero no devoluciones ni anulaciones
        self.assertEqual(self.void(oid,1)['status'],403)

    def test_large_amounts_refunds_and_overpayment(self):
        (oid,)=self.start(charges=(1234567,))
        self.assertEqual(self.state(oid),('pendiente',1234567,0,0));self.assertEqual(equipment.usd(1234567),'$12345.67')   # 11. más de $9.999,99
        self.assertEqual(self.pay(oid,'12345.67')['status'],201);self.assertEqual(self.state(oid),('pagado',0,1234567,0))
        # 12. Los cargos bajan después de pagar: el exceso es saldo a favor, no cero.
        with app.connect() as c:c.execute('UPDATE order_budget SET labor_cents=1000000 WHERE order_id=?',(oid,));c.commit()
        self.assertEqual(self.state(oid),('credito',0,1234567,234567));self.assertEqual(self.finance(oid)['order']['credit_cents'],234567)
        refund=lambda amount,**extra:self.pay(oid,amount,kind='devolucion',**extra)
        self.assertEqual(refund('100')['status'],400)                                                            # exige motivo o referencia
        self.assertEqual(refund('99999',note='Devolución ficticia')['status'],400)                               # no supera lo pagado
        done=refund('2345.67',note='Devolución ficticia por ajuste');self.assertEqual(done['status'],201,done['body']);self.assertEqual(self.state(oid),('pagado',0,1000000,0))
        first=self.request('/api/orders/%d'%oid,cookie=self.cookie)['body']['order']['payments'];self.assertEqual([(p['kind'],p['amount_cents']) for p in first],[('pago',1234567),('devolucion',234567)])
        self.assertEqual(self.void(oid,first[0]['id'])['status'],409)                                            # el pago tiene una devolución: primero se anula esta
        self.assertEqual(self.void(oid,first[1]['id'])['status'],200);self.assertEqual(self.state(oid)[0],'credito')
        with app.connect() as c:self.assertEqual([r[0] for r in c.execute("SELECT action FROM audit WHERE action LIKE 'order_%' AND action!='order_created' ORDER BY id")][-3:],['order_payment_recorded','order_refund_recorded','order_payment_voided'])

    def test_summary_is_exact_integer_arithmetic(self):
        self.assertEqual(equipment.cents_of('0,10'),10);self.assertEqual(equipment.cents_of('0.1'),10);self.assertEqual(equipment.cents_of('1234.5'),123450);self.assertIsNone(equipment.cents_of('0.001'));self.assertIsNone(equipment.cents_of(0.1+0.2))
        self.assertEqual(equipment.summary(10,10)['state'],'pagado');self.assertEqual(equipment.summary(0,0)['state'],'sin_cargos');self.assertEqual(equipment.summary(0,5),{'budget_cents':0,'paid_cents':5,'balance_cents':0,'credit_cents':5,'state':'credito','state_label':'Saldo a favor del cliente'})


if __name__=='__main__':unittest.main()
