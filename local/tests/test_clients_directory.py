"""Directorio de clientes: búsqueda sin tildes, indicadores reales, datos faltantes, orden por columnas y avisos de contacto repetido."""
import unittest
from urllib.parse import quote
import test_app
import app,client_registry
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class ClientsDirectoryTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def add(self,cookie,csrf,name,identification,**extra):
        body={key:value for key,value in self.order_data().items()} | {'name':name,'identification':identification} | extra
        return self.request('/api/client-registry',body,cookie=cookie,csrf=csrf)

    def test_search_stats_missing_sort_and_similar(self):
        cookie,csrf=self.login()
        first=self.add(cookie,csrf,'María Victoria Gómez Estrada','0100000314',phone='0987654321',email='maria@example.invalid')
        self.assertEqual(first['status'],201);self.assertEqual(first['body']['similar'],[])
        second=self.add(cookie,csrf,'José Peñafiel Núñez','0100000421',phone='0987654321',email='jose@example.invalid')
        # Mismo teléfono que otra ficha: se guarda igual (los contactos compartidos son válidos) y se avisa.
        self.assertEqual(second['status'],201);self.assertEqual([(item['name'],item['match']) for item in second['body']['similar']],[('María Victoria Gómez Estrada','teléfono')])
        # Una identificación repetida sí se rechaza, sin crear ni fusionar nada.
        self.assertEqual(self.add(cookie,csrf,'Otra Persona','0100000314')['status'],409)
        with app.connect() as c:
            c.execute("INSERT INTO clients(name,phone,email,identification,needs_review) VALUES ('Importada Sin Datos','','','',1)")
            before=[tuple(row) for row in c.execute('SELECT * FROM clients ORDER BY id')]
        find=lambda q,extra='':self.request('/api/clients?q='+quote(q)+extra,cookie=cookie)['body']
        names=lambda q,extra='':[row['name'] for row in find(q,extra)['rows']]
        # Sin tildes, sin mayúsculas, palabras parciales y en cualquier orden; teléfono e identificación con o sin separadores.
        self.assertEqual(names('gomez'),['María Victoria Gómez Estrada']);self.assertEqual(names('GÓMEZ maria'),['María Victoria Gómez Estrada'])
        self.assertEqual(names('penafiel nunez'),['José Peñafiel Núñez']);self.assertEqual(names('estrada vict'),['María Victoria Gómez Estrada'])
        self.assertEqual(sorted(names('098-7654321')),sorted(['María Victoria Gómez Estrada','José Peñafiel Núñez']))
        self.assertEqual(names('0100000421'),['José Peñafiel Núñez']);self.assertIn('José Peñafiel Núñez',names('cuenca'));self.assertEqual(names('jose@example'),['José Peñafiel Núñez'])
        self.assertEqual(names('zzz no existe'),[])
        # Indicadores calculados con la base, independientes de la búsqueda.
        listing=find('gomez');self.assertEqual(listing['stats'],{'total':len(before),'complete':len(before)-1,'review':1})
        # La ficha por completar indica exactamente qué falta; las completas no llevan esa lista.
        review=find('','&filter=review')['rows'];self.assertEqual(len(review),1)
        self.assertIn('Teléfono',review[0]['missing']);self.assertIn('Identificación válida',review[0]['missing']);self.assertNotIn('missing',find('gomez')['rows'][0])
        # Orden por columnas en ambos sentidos; un criterio desconocido se rechaza.
        ordered=names('','&sort=name');self.assertEqual(ordered,sorted(ordered,key=str.casefold));self.assertEqual(names('','&sort=name&dir=desc'),ordered[::-1])
        self.assertEqual(self.request('/api/clients?sort=inventado',cookie=cookie)['status'],400)
        # Tamaño de página (10, 25 o 50), filtro por ciudad sin tildes, clientes sin órdenes y orden por registro o última atención.
        small=self.request('/api/clients?size=10',cookie=cookie)['body'];self.assertEqual((small['size'],len(small['rows'])<=10,'Cuenca' in small['cities']),(10,True,True))
        self.assertEqual(self.request('/api/clients?size=7',cookie=cookie)['status'],400)
        self.assertIn('José Peñafiel Núñez',names('','&city=CUENCA'));self.assertEqual(names('','&city=Quito'),[])
        self.assertEqual(find('','&filter=no_orders')['total']+find('','&filter=orders')['total'],len(before))
        oldest=names('','&sort=registered');self.assertEqual(oldest,names('','&sort=registered&dir=desc')[::-1])
        self.assertEqual(self.request('/api/clients?sort=last_service&dir=desc',cookie=cookie)['status'],200)
        # Ficha: citas, última atención y datos faltantes; consultar no modifica ningún cliente.
        detail=self.request('/api/clients/%d'%first['body']['id'],cookie=cookie)['body']
        self.assertEqual((detail['appointments'],detail['last_service'],detail['missing']),([],'',[]))
        with app.connect() as c:self.assertEqual([tuple(row) for row in c.execute('SELECT * FROM clients ORDER BY id')],before)

    def test_combined_filters_page_size_registration_date_and_quick_panel(self):
        cookie,csrf=self.login()
        made=self.add(cookie,csrf,'Empresa Ficticia Licencias S.A.','1790016919001',document_type='ruc',client_type='empresa',phone='0987654321',email='empresa@example.invalid')
        self.assertEqual(made['status'],201,made['body']);cid=made['body']['id']
        person=self.add(cookie,csrf,'Persona Natural Ficticia','0100000314',phone='0987654322',email='persona@example.invalid')['body']['id']
        today=app.reception_now().date().isoformat()
        with app.connect() as c:
            # Las altas nuevas guardan su fecha de registro; una ficha antigua sin fecha no se modifica ni aparece en ese filtro.
            self.assertEqual(c.execute('SELECT substr(created_at,1,10) FROM clients WHERE id=?',(cid,)).fetchone()[0],today)
            old=c.execute("INSERT INTO clients(name,phone,email,identification,client_type) VALUES ('Ficha Antigua Sin Fecha','0990000009','','','natural')").lastrowid
            uid=c.execute('SELECT id FROM users LIMIT 1').fetchone()[0]
            c.execute("INSERT INTO license_sales(code,client_id,subtotal_cents,discount_cents,total_cents,created_by,created_at,updated_at) VALUES ('VLIC-20261019-0001',?,3000,0,3000,?,?,?)",(cid,uid,today,today))
        ids=lambda extra:{row['id'] for row in self.request('/api/clients?size=50'+extra,cookie=cookie)['body']['rows']}
        self.assertEqual(ids('&has=licenses'),{cid})
        self.assertEqual(ids('&has=licenses&type=empresa'),{cid});self.assertEqual(ids('&has=licenses&type=natural'),set())
        self.assertEqual(ids('&from=%s&to=%s'%(today,today)),{cid,person});self.assertNotIn(old,ids('&from=2000-01-01'))
        self.assertEqual(ids('&q=ficticia&type=natural&from=%s'%today),{person})
        self.assertEqual(self.request('/api/clients?has=inventado',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/clients?from=19-10-2026',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/clients?from=2026-10-20&to=2026-10-19',cookie=cookie)['status'],400)
        page=self.request('/api/clients?size=15',cookie=cookie)['body'];self.assertEqual(page['size'],15)
        self.assertEqual(self.request('/api/clients',cookie=cookie)['body']['size'],50)  # los buscadores de otras pantallas siguen con 50
        row=next(r for r in page['rows'] if r['id']==cid);self.assertEqual(row['licenses'],0);self.assertTrue(row['created_at'])
        quick=self.request('/api/clients/%d'%cid,cookie=cookie)['body'];self.assertEqual([s['code'] for s in quick['license_sales']],['VLIC-20261019-0001']);self.assertEqual(quick['payments'],[])
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        tech=self.request('/api/clients/%d'%cid,cookie=cookie)['body'];self.assertEqual((tech['license_sales'],tech['payments']),(None,None))

    def test_fold_matches_sqlite(self):
        self.assertEqual(client_registry.fold('  GÓMEZ   Peñafiel Ü '),'gomez penafiel u')
        with app.connect() as c:self.assertEqual(c.execute('SELECT '+client_registry.fold_sql('?'),('GÓMEZ Peñafiel Ü',)).fetchone()[0],'gomez penafiel u')


if __name__=='__main__':unittest.main()
