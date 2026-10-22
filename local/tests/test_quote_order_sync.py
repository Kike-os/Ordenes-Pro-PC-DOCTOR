"""Sincronización Presupuesto → Orden: lo que el cliente decide en su enlace aparece en «Autorizaciones del cliente» de la orden
(descripción, cantidad, precio unitario, subtotal, total, fecha de Ecuador y evidencia), una sola vez, y queda en la base de datos.
Base temporal y datos ficticios; no se envían correos."""
import json,re,unittest
import test_app,test_quotes
import app,client_authorization,quotes

SIGN=test_quotes.SIGN


class QuoteOrderSyncTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data
    form=test_quotes.QuoteFlowTests.form;prepare=test_quotes.QuoteFlowTests.prepare

    def sent(self):
        """Orden con un presupuesto de 3 partidas enviado; el cliente abre el enlace DOS veces y verifica su identidad."""
        cookie,csrf,order,post,ids=self.prepare()
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id']
        post('/api/quotes/%d'%quote,action='save',items=[{'catalog_id':ids[0],'description':'Mantenimiento preventivo','category':'servicio','quantity':1,'unit_cents':3500,'taxed':True},
                                                       {'catalog_id':ids[1],'description':'Licencia ficticia','category':'licencia','quantity':2,'unit_cents':1250,'taxed':False},
                                                       {'catalog_id':ids[2],'description':'Disco SSD ficticio','category':'repuesto','quantity':1,'unit_cents':8000,'taxed':True}])
        path='/presupuesto/'+post('/api/quotes/%d'%quote,action='send')['body']['link'].rsplit('/',1)[1]
        self.assertEqual([self.request(path)['status'] for _ in range(2)],[200,200])  # apertura doble del enlace
        page=self.form(path,{'last4':'0017'})['body'];passkey=re.search(r'name="passkey" value="([^"]+)"',page)[1]
        items=[int(v) for v in dict.fromkeys(re.findall(r'name="decision_(\d+)"',page))]
        self.assertEqual(self.order(order['id'],cookie)['authorized_items'],[])  # enviado: todavía nada autorizado
        return cookie,post,order,quote,path,passkey,items

    def order(self,oid,cookie):
        body=self.request('/api/orders/%d'%oid,cookie=cookie)['body'];return body.get('order',body)

    def decide(self,path,passkey,items,decisions):
        fields={'passkey':passkey,'action':'decide','name':'Cliente Ficticio','accept':'on','signature':SIGN}
        fields.update({'decision_%d'%i:d for i,d in zip(items,decisions)})
        return self.form(path,fields)

    def stored(self,quote):
        with app.connect() as c:
            return (c.execute('SELECT status,decided_by,decided_at FROM quotes WHERE id=?',(quote,)).fetchone(),[r[0] for r in c.execute('SELECT status FROM quote_items WHERE quote_id=? ORDER BY id',(quote,))],
                    c.execute('SELECT COUNT(*) FROM quote_acceptances WHERE quote_id=?',(quote,)).fetchone()[0])

    def test_full_approval_reaches_the_order_once_with_amounts_date_and_evidence(self):
        cookie,post,order,quote,path,passkey,items=self.sent()
        self.assertIn('Aprobado',self.decide(path,passkey,items,['aprobado']*3)['body'])
        head,statuses,acceptances=self.stored(quote)
        self.assertEqual((head['status'],head['decided_by'],statuses,acceptances),('aprobado','cliente',['aprobado']*3,1))  # guardado en la base, no solo en pantalla
        self.assertTrue(head['decided_at'].endswith('-05:00'))  # hora de Ecuador
        views=[self.order(order['id'],cookie) for _ in range(3)]  # recarga del administrador
        self.assertEqual(len({json.dumps(v['authorized_items'],sort_keys=True) for v in views}),1)
        got=views[0]['authorized_items']
        self.assertEqual([(i['description'],i['quantity'],i['unit_cents'],i['net_cents']) for i in got],[('Mantenimiento preventivo',1,3500,3500),('Licencia ficticia',2,1250,2500),('Disco SSD ficticio',1,8000,8000)])
        self.assertEqual(len({i['id'] for i in got}),3)
        self.assertTrue(all(i['signed'] and i['signer']=='Cliente Ficticio' and i['approved_at']==head['decided_at'] and i['quote_code']==order['code']+'-P1' for i in got))
        self.assertEqual((sum(i['net_cents'] for i in got),views[0]['budget']['total_cents']),(14000,14000))  # total autorizado = total a cobrar
        # El cliente vuelve a abrir el enlace y reenvía el formulario: se muestra el resultado, sin duplicar ni cambiar nada.
        self.assertEqual(self.request(path)['status'],200);self.decide(path,passkey,items,['rechazado']*3)
        self.assertEqual(self.stored(quote),(head,statuses,acceptances))
        self.assertEqual(self.order(order['id'],cookie)['authorized_items'],got)

    def test_partial_approval_shows_only_approved_items(self):
        cookie,post,order,quote,path,passkey,items=self.sent()
        self.assertIn('Aprobado parcialmente',self.decide(path,passkey,items,['aprobado','rechazado','aprobado'])['body'])
        self.assertEqual(self.stored(quote)[1],['aprobado','rechazado','aprobado'])
        view=self.order(order['id'],cookie)
        self.assertEqual([(i['description'],i['net_cents']) for i in view['authorized_items']],[('Mantenimiento preventivo',3500),('Disco SSD ficticio',8000)])
        self.assertEqual(view['budget']['total_cents'],11500)
        versions=self.request('/api/orders/%d/quote'%order['id'],cookie=cookie)['body']['versions']
        self.assertEqual((versions[0]['status'],versions[0]['approved_cents'],versions[0]['rejected_cents']),('parcial',11500,2500))

    def test_rejection_authorizes_nothing_and_is_stored(self):
        cookie,post,order,quote,path,passkey,items=self.sent()
        self.assertIn('Rechazado',self.decide(path,passkey,items,['rechazado']*3)['body'])
        head,statuses,acceptances=self.stored(quote)
        self.assertEqual((head['status'],statuses,acceptances),('rechazado',['rechazado']*3,1))
        view=self.order(order['id'],cookie)
        self.assertEqual((view['authorized_items'],view['budget']['total_cents']),([],0))

    def test_signed_service_authorization_does_not_approve_a_pending_quote(self):
        # Caso real de la orden PCD-20261019-0005: el cliente firmó la autorización de servicio, pero no decidió el presupuesto.
        cookie,post,order,quote,path,passkey,items=self.sent()
        with app.connect() as c:
            self.assertEqual(quotes.pending_codes(c,order['id']),[order['code']+'-P1'])
        self.assertEqual(self.order(order['id'],cookie)['authorized_items'],[])
        row={'status':'signed','evidence':json.dumps({'decisions':{'service':'authorized'}}),'signed_at':'2026-10-21T19:17:47-05:00','evidence_hash':'a'*64}
        page=client_authorization.result_page('t'*30,row,{'code':order['code'],'pending_quotes':[order['code']+'-P1']})
        self.assertIn('Presupuesto pendiente: '+order['code']+'-P1',page);self.assertIn('no aprueba importes',page)
        self.assertNotIn('Presupuesto pendiente',client_authorization.result_page('t'*30,row,{'code':order['code'],'pending_quotes':[]}))
        self.decide(path,passkey,items,['aprobado']*3)
        with app.connect() as c:
            self.assertEqual(quotes.pending_codes(c,order['id']),[])  # decidido: ya no se avisa


if __name__=='__main__':
    unittest.main()
