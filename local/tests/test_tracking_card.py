"""Tarjeta Digital de Seguimiento: Code 128 real, QR al enlace público, etapas según el estado y privacidad de la vista pública."""
import re,unittest
import test_app
import app,barcode128,order_tracking
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class BarcodeTests(unittest.TestCase):
    def test_code128_table_checksum_and_modules(self):
        self.assertEqual(len(barcode128.PATTERNS),107);self.assertEqual(len(set(barcode128.PATTERNS)),107)
        self.assertTrue(all(sum(map(int,pattern))==11 for pattern in barcode128.PATTERNS[:106]));self.assertEqual(sum(map(int,barcode128.PATTERNS[106])),13)
        # Dígito de control: (inicio B 104 + suma de valor × posición) módulo 103. Para «PJJ123C»: 879 mod 103 = 55.
        self.assertEqual(barcode128.symbols('PJJ123C'),[104,48,42,42,17,18,19,35,55,106])
        bits=barcode128.modules('PCD-20261013-0002');self.assertEqual(len(bits),(17+2)*11+13);self.assertEqual((bits[0],bits[-1]),(1,1))
        image=barcode128.svg('PCD-20261013-0002');self.assertTrue(image.startswith('<svg'));self.assertIn('viewBox="0 0 %d 56"'%(len(bits)+20),image)
        for bad in ('','ñandú','x'*49,'a\nb'):
            with self.assertRaises(barcode128.BarcodeError):barcode128.symbols(bad)


class TrackingCardTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def test_card_follows_the_order_and_public_view_hides_personal_data(self):
        cookie,csrf=self.login()
        created=self.request('/api/orders',self.order_data({'brand':'Lenovo','model':'Modelo Ficticio','serial':'SERIE-SECRETA-1','request_key':'tracking-card-request-0001'}),cookie=cookie,csrf=csrf)['body']
        oid,code=created['id'],created['code']
        card=self.request('/api/orders/%d/tracking-card'%oid,cookie=cookie)['body']
        states=lambda markup:re.findall(r'<li data-state="(\w+)"',markup)
        self.assertEqual(states(card['html']),['current','pending','pending','pending'])  # nada futuro aparece como completado
        for text in (code,'Cliente ficticio','Lenovo Modelo Ficticio','En espera','Técnico responsable','<svg'):self.assertIn(text,card['html'])
        self.assertTrue(card['active']);self.assertEqual(card['print_url'],'/tarjeta/%d'%oid)
        token=card['public_url'].rsplit('/',1)[1]
        self.request('/api/order-status',{'id':str(oid),'status':'listo'},cookie=cookie,csrf=csrf)
        self.assertEqual(states(self.request('/api/orders/%d/tracking-card'%oid,cookie=cookie)['body']['html']),['done','done','current','pending'])
        # Vista pública: sin sesión, con el estado actual y sin nombre, serie, falla ni técnico.
        public=self.request('/s/'+token)
        self.assertEqual(public['status'],200);self.assertIn('Listo para entregar',public['body']);self.assertIn(code,public['body']);self.assertIn('/s/'+token+'/qr.svg',public['body'])
        for secret in ('Cliente ficticio','SERIE-SECRETA-1','No enciende','0100000017','0991234567','Técnico responsable','Persona de prueba'):self.assertNotIn(secret,public['body'])
        self.assertEqual(self.request('/s/'+token+'/barcode.svg')['body'],barcode128.svg(code))
        self.assertIn('<svg',str(self.request('/s/'+token+'/qr.svg')['body'])[:200])
        self.assertEqual(self.request('/api/orders/%d/barcode.svg'%oid,cookie=cookie)['body'],barcode128.svg(code))
        # Entregada: todas las etapas completas.
        self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)
        self.assertEqual(states(self.request('/s/'+token)['body']),['done']*4)
        # Vista interna para imprimir: exige sesión; el enlace revocado deja de servir y la tarjeta lo dice sin inventar un QR.
        self.assertNotIn('class="ticket"',str(self.request('/tarjeta/%d'%oid)['body']));self.assertIn('Cliente ficticio',self.request('/tarjeta/%d'%oid,cookie=cookie)['body'])
        self.assertEqual(self.request('/api/orders/%d/barcode.svg'%oid)['status'],401);self.assertEqual(self.request('/tarjeta/999999',cookie=cookie)['status'],404)
        with app.connect() as c:order_tracking.revoke(c,oid,None,app.reception_now());c.commit()
        for path in ('/s/'+token,'/s/'+token+'/qr.svg','/s/'+token+'/barcode.svg'):self.assertEqual(self.request(path)['status'],404)
        closed=self.request('/api/orders/%d/tracking-card'%oid,cookie=cookie)['body'];self.assertFalse(closed['active']);self.assertIn('Sin enlace público activo',closed['html']);self.assertNotIn('ticket-qr"',closed['html'])


if __name__=='__main__':unittest.main()
