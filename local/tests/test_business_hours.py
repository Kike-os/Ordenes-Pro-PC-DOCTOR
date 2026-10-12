"""Horarios centralizados: atención presencial, estado abierto/cerrado, atención virtual y lo que responde ADI."""
import unittest
from datetime import datetime
from unittest.mock import patch
import test_app
import app,adi,business_hours
from reception import ECUADOR_TZ
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class BusinessHoursTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def at(self,*moment):return datetime(*moment,tzinfo=ECUADOR_TZ)

    def test_official_hours_and_open_state(self):
        config=business_hours.DEFAULTS
        self.assertEqual(business_hours.text(config),'lunes a viernes de 7:45 a. m. a 8:30 p. m.; sábado de 9:00 a. m. a 9:00 p. m.; domingo de 10:00 a. m. a 5:00 p. m.')
        # 12/10/2026 es lunes; 17 sábado; 18 domingo.
        for moment,opened in (((2026,10,12,7,44),False),((2026,10,12,7,45),True),((2026,10,12,20,29),True),((2026,10,12,20,30),False),((2026,10,17,8,59),False),((2026,10,17,20,59),True),((2026,10,18,9,59),False),((2026,10,18,16,59),True),((2026,10,18,17,0),False)):
            self.assertEqual(business_hours.status(config,self.at(*moment))['open'],opened,moment)
        self.assertEqual(business_hours.status(config,self.at(2026,10,12,22,0))['label'],'Cerrado ahora · abre mañana a las 7:45 a. m.')
        self.assertEqual(business_hours.status(config,self.at(2026,10,12,6,0))['label'],'Cerrado ahora · abre hoy a las 7:45 a. m.')
        # Un cierre extraordinario cierra ese día aunque sea laborable.
        closed=dict(config,closures=[{'date':'2026-10-13','note':'Inventario'}])
        self.assertFalse(business_hours.status(closed,self.at(2026,10,13,10,0))['open']);self.assertEqual(business_hours.status(closed,self.at(2026,10,13,10,0))['label'],'Cerrado ahora · abre mañana a las 7:45 a. m.');self.assertEqual(business_hours.status(closed,self.at(2026,10,13,10,0))['note'],'Inventario')
        # La hora es la de Ecuador aunque el reloj llegue en otra zona.
        from datetime import timezone
        self.assertTrue(business_hours.status(config,datetime(2026,10,12,13,0,tzinfo=timezone.utc))['open'])  # 08:00 en Ecuador
        self.assertFalse(business_hours.status(config,datetime(2026,10,12,12,0,tzinfo=timezone.utc))['open'])  # 07:00 en Ecuador

    def test_adi_answers_with_current_hours(self):
        with patch.dict(app.os.environ,{'OPENAI_API_KEY':''}),app.connect() as c:
            answer=adi.hours_answer(c,self.at(2026,10,12,22,0))
            self.assertIn('lunes a viernes de 7:45 a. m. a 8:30 p. m.',answer);self.assertIn('Cerrado ahora',answer);self.assertIn('las 24 horas, los 7 días de la semana',answer);self.assertIn('/citas',answer)
            self.assertIn('Abierto ahora',adi.hours_answer(c,self.at(2026,10,12,10,0)))
            self.assertIn('7:45 a. m.',adi.reply(c,'¿Cuál es el horario de atención?'))
            # El contexto validado con los horarios vigentes viaja siempre al proveedor de IA.
            seen={}
            with patch.object(adi,'ask',side_effect=lambda text,admin,context:seen.update(context=context) or 'respuesta'):adi.reply(c,'hola')
            self.assertIn('atencion_presencial',seen['context']['horarios_vigentes']);self.assertIn('asesores_humanos',seen['context']['horarios_vigentes'])

    def test_admin_changes_apply_everywhere_without_touching_appointments(self):
        public=self.request('/api/public/hours')['body'];self.assertIn('lunes a viernes',public['presencial']);self.assertIn('24 horas',public['virtual_message'])
        self.assertEqual(self.request('/api/business-hours')['status'],401)
        cookie,csrf=self.login();current=self.request('/api/business-hours',cookie=cookie)['body']
        with app.connect() as c:agenda=[tuple(r) for r in c.execute('SELECT * FROM appointment_hours ORDER BY weekday')]
        new=dict(current['config']);new['hours']=[dict(item,start='08:00',end='18:00') if item['weekday']<5 else dict(item,enabled=False) for item in new['hours']];new['closures']=[{'date':'2026-12-25','note':'Navidad'}];new['closed_message']='Estamos cerrados.'
        self.assertEqual(self.request('/api/business-hours',new,cookie=cookie)['status'],403)  # sin CSRF
        self.assertEqual(self.request('/api/business-hours',new,cookie=cookie,csrf=csrf)['status'],200)
        after=self.request('/api/public/hours')['body']
        self.assertEqual((after['presencial'],after['closed_message'],[item['date'] for item in after['closures']]),('lunes a viernes de 8:00 a. m. a 6:00 p. m.','Estamos cerrados.',['2026-12-25']))
        with patch.dict(app.os.environ,{'OPENAI_API_KEY':''}),app.connect() as c:
            self.assertIn('8:00 a. m. a 6:00 p. m.',adi.reply(c,'¿a qué hora abren?'))
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM appointment_hours ORDER BY weekday')],agenda)  # la agenda de citas no cambia
        for bad in (dict(new,hours=new['hours'][:3]),dict(new,hours=[dict(item,start='20:00',end='08:00') for item in new['hours']]),dict(new,virtual_message=''),dict(new,closures=[{'date':'ayer'}])):
            self.assertEqual(self.request('/api/business-hours',bad,cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico'")
        self.assertEqual(self.request('/api/business-hours',new,cookie=cookie,csrf=csrf)['status'],403)
        self.assertFalse(self.request('/api/business-hours',cookie=cookie)['body']['can_edit'])


if __name__=='__main__':unittest.main()
