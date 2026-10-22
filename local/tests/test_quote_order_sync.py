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


    def set_status(self,oid,code):
        with app.connect() as c:c.execute('UPDATE orders SET status=? WHERE id=?',(code,oid));c.commit()

    def history(self,oid):
        with app.connect() as c:return [tuple(r) for r in c.execute("SELECT event,comment FROM order_history WHERE order_id=? AND comment LIKE 'Presupuesto %' ORDER BY id",(oid,))]

    def test_approval_moves_a_waiting_order_to_processing_once(self):
        cookie,post,order,quote,path,passkey,items=self.sent()
        self.set_status(order['id'],'esperando_cliente')  # como la orden PCD-20261019-0005
        self.assertEqual(self.request('/api/orders/%d/quote'%order['id'],cookie=cookie)['body']['versions'][0]['status_label'],'Esperando aprobación')
        self.decide(path,passkey,items,['aprobado']*3);self.decide(path,passkey,items,['aprobado']*3)  # enlace repetido
        view=self.order(order['id'],cookie)
        self.assertEqual((view['status'],view['status_label']),('reparacion','Procesando'))
        moves=[h for h in self.history(order['id']) if h[0]=='status']
        self.assertEqual(len(moves),1);self.assertIn('aprobado por el cliente',moves[0][1]);self.assertIn('«Esperando respuesta del cliente» a «Procesando»',moves[0][1])
        # Persistencia: una conexión nueva (como tras reiniciar el servidor) lee lo mismo de la base de datos.
        with app.connect() as c:
            self.assertEqual(len(quotes.authorized(c,order['id'])['items']),3)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='quote_client_aprobado' AND entity_id=?",(order['id'],)).fetchone()[0],1)

    def test_rejection_keeps_the_waiting_order_and_records_it(self):
        cookie,post,order,quote,path,passkey,items=self.sent()
        self.set_status(order['id'],'esperando_cliente')
        self.decide(path,passkey,items,['rechazado']*3)
        self.assertEqual(self.order(order['id'],cookie)['status'],'esperando_cliente')
        self.assertTrue(any('rechazado' in h[1] for h in self.history(order['id'])))

    def test_finished_orders_are_never_moved_and_staff_decisions_are_labelled(self):
        cookie,post,order,quote,path,passkey,items=self.sent()
        self.set_status(order['id'],'listo')
        self.decide(path,passkey,items,['aprobado','aprobado','rechazado'])
        self.assertEqual(self.order(order['id'],cookie)['status'],'listo')  # nunca se toca «Listo», «En espera de entrega» ni «Entregado»
        cookie2,csrf2=cookie,None
        with app.connect() as c:
            self.assertEqual(quotes.STATUS['modificacion'],'Revisión solicitada')
            # Decisión del personal sobre una orden que esperaba: pasa a Procesando y el historial lo dice así (no «por el cliente»).
            c.execute("UPDATE quotes SET status='enviado',decided_at='',decided_by='' WHERE id=?",(quote,));c.execute("UPDATE quote_items SET status='pendiente' WHERE quote_id=?",(quote,))
            c.execute("UPDATE orders SET status='presupuesto' WHERE id=?",(order['id'],));c.commit()
            q=quotes.get(c,quote);quotes.decide(c,q,{i:'aprobado' for i in items},app.reception_now(),{'id':self.uid,'name':'Persona de prueba'});c.commit()
        moves=[h for h in self.history(order['id']) if h[0]=='status']
        self.assertIn('(decisión registrada por el personal)',moves[-1][1])


if __name__=='__main__':
    unittest.main()
