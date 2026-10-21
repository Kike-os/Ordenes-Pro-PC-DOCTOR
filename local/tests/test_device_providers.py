"""Identificación por número de serie: un servicio por fabricante con interfaz común y estado real. Sin credenciales no se consulta a
nadie; HP y Lenovo no tienen adaptador (pendientes de autorización) y nunca consultan, aunque existan variables con esos nombres;
ASUS, Acer y MSI solo ofrecen consulta manual asistida. Base temporal y datos ficticios; ninguna consulta real."""
import json
import unittest
from unittest.mock import patch
import test_app
import app,device_manufacturers as makers,device_brands


class DeviceProviderTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def test_each_manufacturer_declares_its_real_mode(self):
        status=makers.statuses()
        self.assertEqual({k:v['mode'] for k,v in status.items()},{'dell':'api','hp':'pendiente','lenovo':'pendiente','asus':'manual','acer':'manual','msi':'manual'})
        self.assertFalse(any(v['automatic'] for v in status.values()))
        self.assertEqual(status['dell']['credentials'],['DELL_API_CLIENT_ID','DELL_API_CLIENT_SECRET']);self.assertIn('TechDirect',status['dell']['access'])
        self.assertEqual(status['lenovo']['credentials'],['LENOVO_CLIENT_ID']);self.assertIn('representante',status['lenovo']['access'])
        self.assertIn('prohíbe',status['msi']['access'])

    def test_pending_and_manual_makers_never_query_even_with_variables(self):
        cookie,csrf=self.login()
        env={'HP_API_KEY':'clave-ficticia','HP_API_SECRET':'secreto-ficticio','LENOVO_CLIENT_ID':'cliente-ficticio'}
        with patch.dict(app.os.environ,env),patch.object(makers,'_request',side_effect=AssertionError('no debe consultar')):
            for brand,serial in (('HP','5CD1234ABC'),('Lenovo','PF1ABCDE'),('ASUS','M3NXCV123456'),('Acer','12345678901'),('MSI','K2103N0012345')):
                found=self.request('/api/devices/identify?serial=%s&brand=%s'%(serial,brand),cookie=cookie)['body']['manufacturer']
                self.assertEqual((found['available'],found['state']),(False,'unavailable'),brand)
            options=self.request('/api/reception-options',cookie=cookie)['body']['manufacturers']
        text=json.dumps(options);self.assertNotIn('ficticio',text)
        by={m['slug']:m for m in options}
        self.assertEqual(by['dell']['hint'],'Service Tag (5 a 7 caracteres)');self.assertEqual(by['acer']['format'],r'\d{11,12}|[A-Z0-9]{22}')
        self.assertIn('developers.hp.com',by['hp']['access']);self.assertFalse(by['hp']['automatic'])

    def test_documented_formats_are_advisory(self):
        import re
        fmt={k:v[0] for k,v in device_brands.FORMATS.items()}
        self.assertTrue(re.fullmatch(fmt['dell'],'4L0WT2'));self.assertFalse(re.fullmatch(fmt['dell'],'SERIE-MUY-LARGA'))
        self.assertTrue(re.fullmatch(fmt['acer'],'12345678901'));self.assertTrue(re.fullmatch(fmt['acer'],'NXHE3AL00412345678901A'[:22]))
        self.assertTrue(re.fullmatch(fmt['hp'],'5CD1234ABC'))


if __name__=='__main__':unittest.main()
