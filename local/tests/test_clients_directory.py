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
        # Ficha: citas, última atención y datos faltantes; consultar no modifica ningún cliente.
        detail=self.request('/api/clients/%d'%first['body']['id'],cookie=cookie)['body']
        self.assertEqual((detail['appointments'],detail['last_service'],detail['missing']),([],'',[]))
        with app.connect() as c:self.assertEqual([tuple(row) for row in c.execute('SELECT * FROM clients ORDER BY id')],before)

    def test_fold_matches_sqlite(self):
        self.assertEqual(client_registry.fold('  GÓMEZ   Peñafiel Ü '),'gomez penafiel u')
        with app.connect() as c:self.assertEqual(c.execute('SELECT '+client_registry.fold_sql('?'),('GÓMEZ Peñafiel Ü',)).fetchone()[0],'gomez penafiel u')


if __name__=='__main__':unittest.main()
