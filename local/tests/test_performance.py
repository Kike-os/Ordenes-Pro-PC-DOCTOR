"""Rendimiento sin cambiar resultados: píxeles del logo precalculados (con huella del PNG) y lecturas repetidas del cálculo de
disponibilidad hechas una sola vez. Datos ficticios."""
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import test_app
import app,appointments,document_logo
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class LogoCacheTests(unittest.TestCase):
    def test_cache_is_current_identical_and_ignored_if_logo_changes(self):
        document_logo.pixels.cache_clear()
        for width in document_logo.CACHE_WIDTHS:
            self.assertEqual(document_logo._from_cache(width),document_logo.decode(width),width)  # si falla: python -c 'import document_logo;document_logo.build_cache()'
        began=time.monotonic();document_logo.pixels(416);self.assertLess(time.monotonic()-began,1.0)
        with tempfile.TemporaryDirectory() as folder:
            other=Path(folder)/'otro.png';other.write_bytes(document_logo.LOGO.read_bytes()+b'cambio')
            with patch.object(document_logo,'LOGO',other):self.assertIsNone(document_logo._from_cache(416))
        self.assertIsNone(document_logo._from_cache(123))  # ancho sin precalcular: se decodifica como antes
        document_logo.pixels.cache_clear()


class AvailabilityCacheTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown

    def test_same_slots_with_far_fewer_queries(self):
        with app.connect() as c:
            service=appointments.services(c)[0]['code'];day=(appointments.now().date()+appointments.timedelta(days=2)).isoformat()
            plain=[];day_=appointments.date.fromisoformat(day)
            _,minutes=appointments.selected(c,service);span=appointments.day_hours(c,day_)
            if span:
                cursor=appointments.datetime.combine(day_,span[0],appointments.TZ);finish=appointments.datetime.combine(day_,span[1],appointments.TZ)
                while cursor+appointments.timedelta(minutes=minutes)<=finish:
                    free=appointments.technicians(c,cursor,minutes)
                    if free:plain.append({'time':cursor.strftime('%H:%M'),'technician_id':free[0]})
                    cursor+=appointments.timedelta(minutes=15)
            count=[0]
            raw=c.connection if hasattr(c,'connection') else c
            raw.set_trace_callback(lambda sql:count.__setitem__(0,count[0]+1))
            cached=appointments.available_slots(c,day,service)
            raw.set_trace_callback(None)
        self.assertEqual(cached,plain)
        self.assertLess(count[0],len(plain)*3+20)


if __name__=='__main__':unittest.main()
