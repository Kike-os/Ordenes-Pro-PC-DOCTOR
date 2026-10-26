"""Incidencias INC-20261026-001 (Agenda, GET /api/public/appointments/pulse, ERR-632352) e INC-20261026-002 (Notificaciones,
GET /api/notifications, ERR-B9BB24): OperationalError en remote_db.py:360 («No se pudo contactar la base de datos remota»).

Causa: la red entre la función y la base remota. El servidor cortó la conexión sin responder (RemoteDisconnected) o no respondió dentro
del plazo (TimeoutError). Eran lecturas sueltas con un solo reintento, inmediato y con el mismo plazo de 20 s, así que un corte de un par
de segundos agotaba los dos intentos; la capa WSGI convertía el fallo en HTTP 500.

Usa el servidor libSQL de pruebas sobre una base temporal con datos ficticios. No se conecta con ningún servicio real."""
import io
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

import test_app
import app
import autocare
import remote_db
from hrana_fake import FakeLibsql

with patch.dict(app.os.environ, {}):
    import wsgi_app  # fija valores por defecto del entorno al importarse: se restauran al salir


class RemotePollingTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        self.cookie, _ = self.login()
        self.server = FakeLibsql(str(app.DB), idle=5)
        self.remote = patch.dict(app.os.environ, {'TURSO_DATABASE_URL': self.server.url, 'TURSO_AUTH_TOKEN': ''})
        self.remote.start()
        self.fast = patch.multiple(remote_db, RETRY_TIMEOUT=0.4, RETRY_PAUSES=(0.05, 0.1), RETRY_DEADLINE=3.0)
        self.fast.start()
        remote_db._pool.__dict__.pop('connections', None)
        remote_db._pool.__dict__.pop('used', None)

    def tearDown(self):
        self.fast.stop()
        self.remote.stop()
        remote_db._pool.__dict__.pop('connections', None)
        remote_db._pool.__dict__.pop('used', None)
        self.server.stop()
        test_app.SecurityTests.tearDown(self)

    def wsgi(self, path, cookie=''):
        env = {}
        setup_testing_defaults(env)
        env.update(PATH_INFO=path, REQUEST_METHOD='GET', HTTP_COOKIE=cookie, **{'wsgi.input': io.BytesIO(b'')})
        seen = {}
        body = b''.join(wsgi_app.app(env, lambda status, headers, exc=None: seen.update(status=status, headers=dict(headers))))
        return int(seen['status'][:3]), seen['headers'], body

    def errors(self):
        self.remote.stop()  # el registro técnico se lee directamente de la base temporal
        try:
            with app.connect() as c:
                return autocare._load(c, 'autocare_errors', [])
        finally:
            self.remote.start()

    def test_pulse_survives_two_dropped_connections_in_a_row(self):
        """INC-20261026-001: el servidor corta dos veces seguidas la conexión (antes, el segundo corte daba HTTP 500)."""
        self.assertEqual(self.wsgi('/api/public/appointments/pulse')[0], 200)
        self.server.fail_next = 2
        status, _, body = self.wsgi('/api/public/appointments/pulse')
        self.assertEqual(status, 200, body)
        self.assertIn(b'"pulse"', body)
        self.assertEqual(self.server.fail_next, 0)
        self.assertEqual(self.errors(), [])

    def test_notifications_survive_a_server_that_does_not_answer(self):
        """INC-20261026-002: la consulta de la sesión queda sin respuesta; el intento se corta pronto y el reintento responde."""
        started = time.monotonic()
        self.assertEqual(self.wsgi('/api/notifications', self.cookie)[0], 200)
        normal = time.monotonic() - started
        self.server.hang_next, self.server.hang_seconds = 1, 4.0
        started = time.monotonic()
        status, _, body = self.wsgi('/api/notifications', self.cookie)
        self.assertEqual(status, 200, body)
        self.assertIn(b'"items"', body)
        self.assertLess(time.monotonic() - started, normal + 1.5)  # cortó el intento colgado (0,4 s) sin esperar sus 4 s
        self.assertEqual(self.errors(), [])

    def test_persistent_outage_answers_503_with_retry_after_and_names_the_cause(self):
        self.server.fail_next = 3  # los tres intentos fallan; el registro posterior del error ya encuentra la base
        started = time.monotonic()
        status, headers, body = self.wsgi('/api/public/appointments/pulse')
        self.assertLess(time.monotonic() - started, remote_db.RETRY_DEADLINE + 1)  # nunca supera el plazo total
        self.assertEqual((status, headers.get('Retry-After')), (503, '5'))
        self.assertIn('problema temporal de base de datos', body.decode())
        self.assertGreaterEqual(self.server.requests, 3)
        last = self.errors()[-1]
        self.assertEqual((last['path'], last['status'], last['type'], last['origin'], last['severity']),
                         ('/api/public/appointments/pulse', 503, 'OperationalError', 'RemoteDisconnected', 'crítica'))
        self.assertIn('conexión cortada o sin respuesta (RemoteDisconnected)', last['cause'])
        self.assertEqual(self.wsgi('/api/public/appointments/pulse')[0], 200)  # al volver la red, responde sin intervención


class RetryPolicyTests(unittest.TestCase):
    """Política de reintentos sobre una base temporal propia (una transacción interrumpida no bloquea la base de las demás pruebas)."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = self.temp.name + '/r.sqlite3'
        with sqlite3.connect(path) as c:
            c.execute('CREATE TABLE fixture(id INTEGER PRIMARY KEY,name TEXT)')
        self.server = FakeLibsql(path, idle=30)
        remote_db._pool.__dict__.pop('connections', None)
        remote_db._pool.__dict__.pop('used', None)

    def tearDown(self):
        remote_db._pool.__dict__.pop('connections', None)
        remote_db._pool.__dict__.pop('used', None)
        self.server.stop()
        self.temp.cleanup()

    def test_writes_inside_a_transaction_are_still_never_repeated(self):
        c = remote_db.Connection(self.server.url, '')
        c.execute("INSERT INTO fixture(name) VALUES ('uno')")
        self.server.fail_next = 2
        with self.assertRaises(sqlite3.OperationalError):
            c.execute("UPDATE fixture SET name='dos' WHERE id=1")
        self.assertEqual(self.server.fail_next, 1)  # un solo intento: una escritura nunca se envía dos veces
        self.server.fail_next = 0

    def test_connection_idle_by_wall_clock_is_replaced_before_sending(self):
        """En Vercel la función puede quedar congelada entre peticiones y el reloj monotónico puede no avanzar mientras tanto."""
        c = remote_db.Connection(self.server.url, '')
        c.execute('SELECT 1').fetchone()
        key = next(iter(remote_db._pool.connections))
        old = remote_db._pool.connections[key]
        remote_db._pool.used[key] = (time.monotonic(), time.time() - 600)  # «recién usada» según el reloj congelado
        c.execute('SELECT 1').fetchone()
        self.assertIsNot(remote_db._pool.connections[key], old)


if __name__ == '__main__':
    unittest.main()
