"""Monitor de errores de ADI AutoCare e incidencia INC-20261020-003: detalle exacto de cada error (sin datos sensibles), agrupación con
contador, resolución con historial, reapertura automática, advertencia que vuelve a la normalidad al resolver, causa concreta, mensaje
comprensible ante un fallo temporal de la base y bloqueo de envíos simultáneos del mismo presupuesto. Base temporal y datos ficticios."""
import sqlite3
import threading
import time
import unittest
from datetime import timedelta
from unittest.mock import patch
import test_app
import app,autocare,stability,quotes


def failure(message='No se pudo contactar la base de datos remota.',operation='UPDATE mail_archive'):
    try:
        try:raise ConnectionResetError('reset')
        except ConnectionResetError as cause:
            error=sqlite3.OperationalError(message);error.operation=operation;raise error from cause
    except sqlite3.OperationalError as error:return error


class ErrorMonitorTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def incidents(self):
        with app.connect() as c:return autocare.incidents(c)

    def test_error_detail_is_exact_grouped_and_free_of_sensitive_data(self):
        user={'id':1,'name':'Persona de prueba'}
        for _ in range(2):app.note_runtime_error('POST','/api/quotes/7',failure("constraint failed: 'cliente@example.invalid' 0991234567"),user,503)
        with app.connect() as c:errors=autocare._load(c,'autocare_errors',[])
        last=errors[-1]
        self.assertEqual((last['method'],last['path'],last['module'],last['status'],last['user'],last['ref'],last['operation'],last['origin'],last['type']),
                         ('POST','/api/quotes/:id','Presupuestos',503,'Persona de prueba','7','UPDATE mail_archive','ConnectionResetError','OperationalError'))
        self.assertRegex(last['code'],r'^ERR-[0-9A-F]{6}$');self.assertNotIn('example.invalid',str(errors));self.assertNotIn('0991234567',str(errors))
        found=[i for i in self.incidents() if i['key'].startswith('error:Presupuestos')]
        self.assertEqual(len(found),1);self.assertEqual((found[0]['count'],found[0]['details']['status'],len(found[0]['occurrences'])),(2,503,2))
        self.assertEqual(autocare.LEVELS[found[0]['severity']],'Crítico')

    def test_resolved_incident_clears_the_warning_and_reopens_the_same_code_if_it_returns(self):
        now=app.reception_now()
        app.note_runtime_error('POST','/api/quotes/3',failure())
        with app.connect() as c:
            self.assertEqual(stability.checks(c,now=now)[-1][3]()[0],'warning')
            text=stability.checks(c,now=now)[-1][3]()[1]
        self.assertIn('Se registró 1 fallo en el módulo Presupuestos durante operaciones POST (/api/quotes/:id',text)
        with app.connect() as c:
            detail=autocare.service_detail(c,'errors',now)
            self.assertTrue(detail['concrete']);self.assertIn('Revisar /api/quotes/:id y la operación de base de datos asociada (UPDATE mail_archive)',detail['action'])
            code=next(i['code'] for i in autocare.incidents(c) if i['key'].startswith('error:'))
            autocare.update_incident(c,code,'resuelta','Corregido en remote_db (conexiones inactivas).','Administración',now+timedelta(seconds=5))
            self.assertEqual(stability.checks(c,now=now)[-1][3](),'Sin errores de ejecución pendientes en la última hora')
            self.assertTrue(autocare._load(c,'autocare_errors',[]))  # el historial técnico se conserva
        later=app.reception_now()+timedelta(seconds=10)
        with patch.object(app,'reception_now',return_value=later):app.note_runtime_error('POST','/api/quotes/3',failure())
        item=next(i for i in self.incidents() if i['key'].startswith('error:'))
        self.assertEqual((item['code'],item['status'],item['reopened'],item['count']),(code,'activa',True,2))
        self.assertEqual([h['status'] for h in item['history']],['resuelta','activa'])

    def test_database_failure_message_is_clear_and_logged(self):
        cookie,csrf=self.login()
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'error-monitor-order-0001'}),cookie=cookie,csrf=csrf)['body']
        quote=self.request('/api/orders/%d/quote'%order['id'],{},cookie=cookie,csrf=csrf)['body']['id']
        with patch.object(quotes,'save',side_effect=failure(operation='DELETE FROM quote_items')):
            result=self.request('/api/quotes/%d'%quote,{'action':'save','items':[]},cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],503)
        self.assertEqual(result['body']['error'],'No se pudo guardar el presupuesto por un problema temporal de base de datos. Intente nuevamente.')
        with app.connect() as c:last=autocare._load(c,'autocare_errors',[])[-1]
        self.assertEqual((last['user'],last['status'],last['ref']),('Persona de prueba',503,str(quote)))

    def test_simultaneous_sends_of_the_same_quote_send_once(self):
        cookie,csrf=self.login()
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'error-monitor-order-0002'}),cookie=cookie,csrf=csrf)['body']
        quote=self.request('/api/orders/%d/quote'%order['id'],{},cookie=cookie,csrf=csrf)['body']['id']
        self.request('/api/quotes/%d'%quote,{'action':'save','items':[{'description':'Servicio ficticio','category':'servicio','quantity':1,'unit_cents':2000,'taxed':True}]},cookie=cookie,csrf=csrf)
        sent,results=[],[]
        def deliver(config,message,recipients):time.sleep(0.4);sent.append(recipients);return {'refused':{},'dsn':False,'trace':[]}
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value={'username':'taller@example.invalid','password':'x'}),patch.object(app.mail_pro,'deliver',side_effect=deliver):
            threads=[threading.Thread(target=lambda:results.append(self.request('/api/quotes/%d'%quote,{'action':'send'},cookie=cookie,csrf=csrf))) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join()
        self.assertEqual(sorted(r['status'] for r in results),[200,409]);self.assertEqual(len(sent),1)
        self.assertIn('ya se está enviando',next(r for r in results if r['status']==409)['body']['error'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM quote_links WHERE quote_id=?",(quote,)).fetchone()[0],1)
            self.assertIsNone(c.execute("SELECT 1 FROM system_state WHERE key=?",('quote-sending:'+str(quote),)).fetchone())  # reserva liberada


if __name__=='__main__':unittest.main()
