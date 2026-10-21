"""Tarjeta de Licencias Digitales: un registro por licencia (cinco iguales son cinco), sin cruces entre clientes, método de activación con
los nombres de sus campos, PDF público sin secretos y documento privado solo con autorización expresa y registrado. Base temporal y datos
ficticios; ninguna credencial real."""
import base64
import re
import unittest
import zlib
import test_app,test_licenses
import app,licenses


def pdf_text(raw):
    """Texto de un PDF con flujos comprimidos (para comprobar qué contiene de verdad)."""
    out=[]
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream',raw,re.S):
        try:out.append(zlib.decompress(m.group(1)).decode('latin-1'))
        except zlib.error:out.append(m.group(1).decode('latin-1','replace'))
    return '\n'.join(out)


class LicenseCardTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data
    _b=vars(test_licenses.LicenseProTests);admin=_b['admin'];new_product=_b['new_product'];client_id=_b['client_id'];today=_b['today']

    def build(self):
        self.admin();client=self.client_id()
        av=self.new_product(name='Bitdefender Total Security ficticio',key='BITD-FICT-0000')['product_id']
        self.assertEqual(self.post('/api/licenses/units/bulk',product_id=str(av),lines='\n'.join('BITD-FICT-%04d'%n for n in range(1,6)))['status'],201)
        ms=self.new_product(name='Microsoft 365 Familia ficticio',line='microsoft',key='',username='cuenta.ficticia@example.invalid',password='Clave-Ficticia-123')['product_id']
        both=self.new_product(name='Suite ficticia con cuenta y clave',key='SUITE-FICT-0001',username='suite@example.invalid',password='Suite-Ficticia-9')['product_id']
        with app.connect() as c:other=c.execute("INSERT INTO clients(name,phone,identification) VALUES ('Otra Persona Ficticia','0990000001','1710034065')").lastrowid
        sale=self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':av,'quantity':5},{'product_id':ms,'quantity':1},{'product_id':both,'quantity':1}],deliver=True,accept_balance=True,activated=True,activated_at=self.today().isoformat())
        self.assertEqual(sale['status'],201,sale['body'])
        mine=self.get('/api/licenses/sales/%d'%sale['body']['sale'])['body']['delivery_id']
        theirs=self.post('/api/licenses/sales',client_id=str(other),items=[{'product_id':av,'quantity':1}],deliver=True,accept_balance=True)['body']
        return mine,self.get('/api/licenses/sales/%d'%theirs['sale'])['body']['delivery_id'],client,other

    def test_one_record_per_license_methods_and_no_secrets_in_public_versions(self):
        mine,theirs,client,other=self.build()
        with app.connect() as c:before=[tuple(r) for r in c.execute('SELECT id,code,status,client_id,delivery_id,secret,activated_at,expires_at FROM license_units ORDER BY id')]
        card=self.get('/api/licenses/deliveries/%d/card'%mine)['body']
        codes=[i['unit_code'] for i in card['items']]
        self.assertEqual(len(codes),7);self.assertEqual(len(set(codes)),7);self.assertEqual(len({i['unit_id'] for i in card['items']}),7)
        self.assertEqual(sum(1 for i in card['items'] if i['product']=='Bitdefender Total Security ficticio'),5)
        with app.connect() as c:
            owners={r[0]:(r[1],r[2]) for r in c.execute('SELECT code,client_id,delivery_id FROM license_units')}
        self.assertTrue(all(owners[code]==(client,mine) for code in codes))  # sin cruces con el otro cliente
        other_code=self.get('/api/licenses/deliveries/%d/card'%theirs)['body']['items'][0]['unit_code'];self.assertNotIn(other_code,codes)
        by={i['product']:i for i in card['items']}
        self.assertEqual((by['Microsoft 365 Familia ficticio']['method'],by['Suite ficticia con cuenta y clave']['method']),('cuenta','cuenta_clave'))
        self.assertEqual(by['Microsoft 365 Familia ficticio']['fields'],[licenses.SECRET_LABELS['username'],licenses.SECRET_LABELS['password']])
        bitd=[i for i in card['items'] if i['method']=='clave'];self.assertEqual(len(bitd),5);self.assertTrue(all(i['fields']==[licenses.SECRET_LABELS['key']] for i in bitd))
        self.assertTrue(all(i['period_days'] and i['days_left'] is not None and i['state'] in ('activa','por_vencer') for i in card['items']))
        text=str(card)
        for secret in ('BITD-FICT','Clave-Ficticia-123','cuenta.ficticia@','SUITE-FICT','Suite-Ficticia-9'):self.assertNotIn(secret,text)
        pdf=self.request('/api/licenses/deliveries/%d/card.pdf'%mine,cookie=self.cookie);self.assertEqual(pdf['status'],200);self.assertTrue(pdf['body'].startswith(b'%PDF'))
        content=pdf_text(pdf['body'])
        for secret in ('BITD-FICT','Clave-Ficticia-123','cuenta.ficticia','SUITE-FICT','Suite-Ficticia-9'):self.assertNotIn(secret,content)
        for code in codes:self.assertIn(code,content)
        self.assertIn('Tarjeta de Licencias Digitales',content);self.assertIn('ecuadorpcdoctor.com',content)
        with app.connect() as c:after=[tuple(r) for r in c.execute('SELECT id,code,status,client_id,delivery_id,secret,activated_at,expires_at FROM license_units ORDER BY id')]
        self.assertEqual(before,after)  # la tarjeta y el PDF no modifican ninguna licencia

    def test_private_document_needs_confirmation_is_admin_only_and_logged(self):
        mine,theirs,client,other=self.build()
        path='/api/licenses/deliveries/%d/private-pdf'%mine
        self.assertEqual(self.post(path)['status'],400)
        with app.connect() as c:before=c.execute("SELECT COUNT(*) FROM license_events WHERE event='credenciales_consultadas'").fetchone()[0]
        made=self.post(path,confirm=True);self.assertEqual(made['status'],200,made['body'])
        content=pdf_text(base64.b64decode(made['body']['pdf']))
        self.assertIn('VERSI',content);self.assertIn('BITD-FICT-0001',content);self.assertIn('Clave-Ficticia-123',content)
        with app.connect() as c:
            logged=c.execute("SELECT COUNT(*) FROM license_events WHERE event='credenciales_consultadas' AND delivery_id=?",(mine,)).fetchone()[0]
            self.assertEqual(logged-before if before==0 else logged,7)
            self.assertTrue(c.execute("SELECT 1 FROM audit WHERE action='license_private_document'").fetchone())
            # La auditoría no guarda credenciales.
            self.assertFalse(c.execute("SELECT 1 FROM license_events WHERE detail LIKE '%BITD-FICT%' OR detail LIKE '%Clave-Ficticia%'").fetchone())
            c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(self.post(path,confirm=True)['status'],403)
        self.assertEqual(self.request('/api/licenses/deliveries/%d/card.pdf'%mine,cookie=self.cookie)['status'],403)


if __name__=='__main__':unittest.main()
