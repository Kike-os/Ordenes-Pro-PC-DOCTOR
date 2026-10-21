"""Tareas programadas: cada llamada deja constancia (latido) y ejecuta su verificación aunque haya habido una automática hace un momento;
el aviso «no se reciben» solo aparece tras 18 h sin llamadas (antes se saltaban en silencio y alarmaba a las 12 h). Base temporal."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch
import test_app
import app,stability


class CronHeartbeatTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request

    def internal(self,c,now):
        return next(item for item in stability.checks(c,now=now) if item[0]=='internal')[3]()

    def runs(self):
        with app.connect() as c:return [r['source'] for r in stability._load(c,'stability_runs',[])]

    def test_scheduled_call_runs_even_after_a_recent_automatic_check(self):
        now=app.reception_now()
        with app.connect() as c:stability.run(c,now-timedelta(minutes=2))  # verificación automática reciente (visitas)
        with patch.dict(app.os.environ,{'CRON_SECRET':'secreto-ficticio-cron'}):
            self.assertEqual(self.request('/api/cron/stability-night')['status'],404)  # sin la cabecera de la plataforma no responde
            handler_headers={'Authorization':'Bearer secreto-ficticio-cron'}
            from email.message import Message
            import io
            h=object.__new__(app.Handler);h.path='/api/cron/stability-night';h.client_address=('127.0.0.1',1);h.headers=Message()
            for k,v in handler_headers.items():h.headers[k]=v
            out={};h.reply=lambda status,body,*a,**k:out.update(status=status);h.do_GET()
        self.assertEqual(out['status'],200)
        self.assertEqual(self.runs().count('programada'),1)
        with app.connect() as c:self.assertIn('stability-night',stability._load(c,'cron_heartbeat',{}))

    def test_warning_only_after_eighteen_hours_without_calls(self):
        now=app.reception_now()
        with patch.dict(app.os.environ,{'VERCEL':'1'}),app.connect() as c:
            stability.cron_heartbeat(c,now-timedelta(hours=16),'stability')
            self.assertNotIsInstance(self.internal(c,now),tuple)  # 16 h: dentro del margen (antes alarmaba a las 12 h)
            self.assertIn('última tarea programada',self.internal(c,now))
            state,text=self.internal(c,now+timedelta(hours=3))
            self.assertEqual(state,'warning');self.assertIn('no se reciben desde',text)
            stability.cron_heartbeat(c,now+timedelta(hours=3),'reminders')
            self.assertNotIsInstance(self.internal(c,now+timedelta(hours=3)),tuple)

    def test_scheduled_run_skips_only_while_another_is_running(self):
        now=app.reception_now()
        with app.connect() as c:
            stability._save(c,'stability_running',{'since':now.isoformat(timespec='seconds')})
            self.assertIsNone(stability.scheduled_run(c,now,'stability'))
            self.assertIn('stability',stability._load(c,'cron_heartbeat',{}))  # la llamada queda registrada igualmente


if __name__=='__main__':unittest.main()
