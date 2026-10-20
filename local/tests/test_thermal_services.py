"""Servicios de renovación de pasta térmica para portátiles (2026-10-20): alta única sin duplicados, precios con IVA incluido (no se
suma de nuevo), iconos propios en pantalla y PDF, selección en presupuestos y presupuestos existentes intactos. Datos ficticios."""
import unittest
import zlib,re
import test_app
import app,quotes,catalog_icons
app.os.environ.setdefault('LOGIN_CAPTCHA','off')
NAMES=('Renovación de pasta térmica para portátiles sin GPU dedicada','Renovación de pasta térmica para portátiles Gamer con GPU dedicada')


class ThermalServicesTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def items(self,c):
        return {r['name']:dict(r) for r in c.execute('SELECT * FROM catalog_items WHERE name IN (?,?)',NAMES)}

    def test_created_once_with_included_tax_icons_and_no_duplicates(self):
        cookie,csrf=self.login()
        order=self.request('/api/orders',self.order_data({'request_key':'thermal-order-request-0001'}),cookie=cookie,csrf=csrf)['body']
        old=self.request('/api/orders/%d/quote'%order['id'],{},cookie=cookie,csrf=csrf)['body']['id']
        self.request('/api/quotes/%d'%old,{'action':'save','items':[{'description':'Servicio previo ficticio','category':'servicio','quantity':1,'unit_cents':4500,'taxed':True}]},cookie=cookie,csrf=csrf)
        with app.connect() as c:
            before=[tuple(r) for r in c.execute('SELECT * FROM quote_items ORDER BY id')];others=[tuple(r) for r in c.execute('SELECT * FROM catalog_items ORDER BY id')]
            first=quotes.seed_thermal_once(c,app.reception_now());again=quotes.seed_thermal_once(c,app.reception_now());manual=quotes.seed_thermal(c,{'id':self.uid,'name':'Persona de prueba','role':'administrador'},app.reception_now())
            found=self.items(c)
            self.assertEqual((first['created'],again,manual['created']),(2,None,0))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM catalog_items WHERE name IN (?,?)',NAMES).fetchone()[0],2)
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM catalog_items WHERE name NOT IN (?,?) ORDER BY id',NAMES)],others)  # los demás, sin cambios
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM quote_items ORDER BY id')],before)  # presupuestos existentes, intactos
        cpu,gpu=found[NAMES[0]],found[NAMES[1]]
        self.assertEqual((cpu['price_cents'],cpu['price_mode'],cpu['category'],cpu['icon']),(2000,'incluido','servicio','termica_portatil'))
        self.assertEqual((gpu['price_cents'],gpu['price_mode'],gpu['category'],gpu['icon']),(6500,'incluido','servicio','termica_gamer'))
        self.assertIn('CPU',cpu['description']);self.assertIn('GPU',gpu['description'])
        self.assertEqual((catalog_icons.guess('servicio',NAMES[0]),catalog_icons.guess('servicio',NAMES[1])),('termica_portatil','termica_gamer'))
        self.assertEqual(catalog_icons.guess('servicio','Mantenimiento de PC Gamer con cambio de pasta térmica del CPU'),'pc_gamer')  # sin cambios para los demás
        listed={item['name']:item for item in self.request('/api/catalog?category=servicio',cookie=cookie)['body']['rows']}
        self.assertEqual((listed[NAMES[0]]['price_cents'],listed[NAMES[1]]['price_cents']),(2000,6500))

    def test_both_selectable_in_a_quote_totals_without_adding_tax_again_and_in_pdf(self):
        cookie,csrf=self.login()
        with app.connect() as c:quotes.seed_thermal_once(c,app.reception_now());found=self.items(c)
        order=self.request('/api/orders',self.order_data({'request_key':'thermal-order-request-0002'}),cookie=cookie,csrf=csrf)['body']
        quote=self.request('/api/orders/%d/quote'%order['id'],{},cookie=cookie,csrf=csrf)['body']['id']
        items=[{'catalog_id':found[name]['id'],'description':name,'category':'servicio','quantity':1,'unit_cents':found[name]['price_cents'],'taxed':True} for name in NAMES]
        saved=self.request('/api/quotes/%d'%quote,{'action':'save','items':items},cookie=cookie,csrf=csrf);self.assertEqual(saved['status'],200,saved['body'])
        with app.connect() as c:detail=quotes.detail(c,quotes.get(c,quote))
        self.assertEqual(detail['totals']['quoted'],8500)  # 20 + 65 con IVA incluido: no se suma de nuevo
        self.assertEqual(detail['totals']['base_taxed']+detail['totals']['tax'],8500)
        self.assertEqual({i['icon'] for i in detail['items']},{'termica_portatil','termica_gamer'})
        pdf=self.request('/api/quotes/%d/pdf'%quote,cookie=cookie)['body'];self.assertEqual(pdf[:4],b'%PDF')
        text=b''.join(zlib.decompress(m) for m in re.findall(rb'stream\r?\n(.*?)\r?\nendstream',pdf,re.S) if self._inflatable(m))
        self.assertIn(b'pasta t',text.lower());self.assertIn(b'85,00',text)

    @staticmethod
    def _inflatable(data):
        try:zlib.decompress(data);return True
        except zlib.error:return False


if __name__=='__main__':unittest.main()
