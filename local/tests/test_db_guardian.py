"""Database Guardian Pro 1.0: pruebas controladas con base temporal y migraciones de PRUEBA en una carpeta temporal (nunca la base real).
Cubre conexión normal, lenta, interrumpida y recuperada; reintentos agotados y circuito; migración pendiente, incompleta, sin registro,
duplicada y modificada; dos procesos a la vez; reinicio de instancia; compatibilidad con el monitor de estabilidad; conservación de los
registros financieros y ausencia de escrituras duplicadas; y el estado verificado de 119_payment_commitments y 120_financial_rates."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_app
import app
import db_guardian as g
import db_migrations as dm
import stability

TOKEN = {'finished_at': '', 'destination': 'gdrive', 'file': 'prueba'}


class FlakyConnection:
    """Envoltorio de la conexión que falla las primeras N consultas «SELECT 1» (interrupción simulada)."""
    def __init__(self, conn, fails):
        self._c, self.fails = conn, fails

    def execute(self, sql, *args):
        if sql.strip() == 'SELECT 1' and self.fails > 0:
            self.fails -= 1
            raise sqlite3.OperationalError('No se pudo contactar la base de datos remota.')
        return self._c.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._c, name)


class GuardianTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def now(self):
        return app.reception_now()

    def sandbox(self):
        """Carpeta temporal con copias de las migraciones reales + manifiesto, para crear casos de prueba sin tocar el proyecto."""
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        mig = folder / 'migrations'
        shutil.copytree(g.MIGRATIONS, mig)
        patches = [patch.object(g, 'MIGRATIONS', mig), patch.object(g, 'MANIFEST', mig / 'MANIFEST.json'), patch.object(dm, 'ROOT', folder),
                   patch.object(dm, '_backup', lambda c, now: (dict(TOKEN, finished_at=now.isoformat()), ''))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return mig

    def admin(self):
        with app.connect() as c:
            return c.execute('SELECT * FROM users WHERE id=?', (self.uid,)).fetchone()

    # ---- 119 y 120 --------------------------------------------------------------------------------------------------------------------

    def test_119_and_120_are_verified_with_their_structure(self):
        with app.connect() as c:
            items = {i['name']: i for i in g.migrations(c)['items']}
        for name, tables in (('119_payment_commitments.sql', ['payment_commitments', 'payment_commitment_events']), ('120_financial_rates.sql', ['financial_rates'])):
            self.assertEqual(items[name]['state'], 'verificada', items[name])
            self.assertEqual(items[name]['objects']['tables'], tables)
            self.assertEqual(items[name]['missing'], [])

    # ---- Conexión ---------------------------------------------------------------------------------------------------------------------

    def test_normal_connection_is_green_with_percentiles(self):
        with app.connect() as c:
            for _ in range(6):
                got = g.check(c, self.now(), sleep=lambda s: None)
        self.assertEqual(got['level'], 'verde', got['reason'])
        self.assertIsNotNone(got['latency']['p50'])
        self.assertIsNotNone(got['latency']['p90'])
        self.assertIsNone(got['latency']['p95'])                            # no hay mediciones suficientes: no se inventa
        self.assertEqual(got['component']['potential_severity'], 'crítica')  # gravedad potencial aparte del estado actual

    def test_slow_connection_is_warning(self):
        with app.connect() as c, patch.object(g, 'SLOW_MS', -1):
            got = g.check(c, self.now(), sleep=lambda s: None)
        self.assertEqual(got['level'], 'amarillo')
        self.assertIn('lenta', got['reason'])

    def test_temporary_interruption_recovers_with_backoff(self):
        pauses = []
        with app.connect() as c:
            got = g.check(FlakyConnection(c, 2), self.now(), sleep=pauses.append)
        self.assertEqual(got['level'], 'amarillo')
        self.assertIn('recuperada tras 3 intentos', got['reason'])
        self.assertEqual(len(pauses), 2)
        self.assertTrue(all(0 < p <= g.MAX_PAUSE for p in pauses))

    def test_retries_exhausted_open_circuit_and_then_resolve(self):
        with app.connect() as c:
            for _ in range(g.CIRCUIT_FAILS):
                got = g.check(FlakyConnection(c, 99), self.now(), sleep=lambda s: None)
            self.assertEqual(got['level'], 'rojo')
            inc = g.history(c)[0]
            self.assertEqual((inc['code'], inc['status'], inc['count']), ('DB-CONN', 'intervencion', 3))   # agrupada: no satura el historial
            got = g.check(c, self.now(), sleep=lambda s: None)
            self.assertTrue(got['circuit'])                                       # circuito abierto: no insiste
            state = g._get(c, g.STATE_KEY, {})
            state['circuit_until'] = 0
            g._set(c, g.STATE_KEY, state);c.commit()
            got = g.check(c, self.now(), sleep=lambda s: None)
            self.assertEqual(got['level'], 'verde')                               # una incidencia resuelta no deja el indicador en rojo
            inc = g.history(c)[0]
            self.assertEqual(inc['status'], 'resuelta')
            self.assertTrue(inc['resolved_at'])

    def test_instance_restart_keeps_state_and_history(self):
        with app.connect() as c:
            g.check(c, self.now(), sleep=lambda s: None)
        with app.connect() as c:                                                   # conexión nueva = instancia reiniciada
            st = g.status(c, self.now())
        self.assertEqual(st['level'], 'verde')
        self.assertTrue(st['checked_at'])

    def test_gray_without_checks(self):
        with app.connect() as c:
            self.assertEqual(g.status(c, self.now())['level'], 'gris')

    # ---- Migraciones ------------------------------------------------------------------------------------------------------------------

    def test_pending_additive_migration_is_warning_not_critical(self):
        mig = self.sandbox()
        (mig / '900_prueba_guardian.sql').write_text('CREATE TABLE IF NOT EXISTS guardian_prueba (id INTEGER PRIMARY KEY, nota TEXT);\n')
        with app.connect() as c:
            got = g.check(c, self.now(), sleep=lambda s: None)
            self.assertEqual((got['level'], got['pending']), ('amarillo', ['900_prueba_guardian.sql']))
            with patch.object(stability, 'ROOT', mig.parent):
                result = stability.execute(*stability.checks(c)[0])
        self.assertEqual(result['status'], 'warning')                               # el monitor ya no lo marca como fallo crítico
        self.assertTrue(result['ok'])

    def test_apply_is_verified_logged_and_preserves_records(self):
        mig = self.sandbox()
        (mig / '900_prueba_guardian.sql').write_text('CREATE TABLE IF NOT EXISTS guardian_prueba (id INTEGER PRIMARY KEY, nota TEXT);\n'
                                                      'CREATE INDEX IF NOT EXISTS guardian_prueba_nota ON guardian_prueba(nota);\n')
        with app.connect() as c:
            before = {t: c.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0] for t in ('orders', 'order_payments', 'invoices', 'invoice_sequences', 'payment_commitments')}
            result = dm.apply(c, self.admin(), self.now(), 'APLICAR')
            self.assertEqual((result['applied'], result['verified'], result['lost']), (['900_prueba_guardian.sql'], ['900_prueba_guardian.sql'], []))
            led = c.execute("SELECT * FROM migration_ledger WHERE name='900_prueba_guardian.sql'").fetchone()
            self.assertEqual((led['result'], led['verified'], led['checksum']), ('aplicada y verificada', 1, g.checksum(mig / '900_prueba_guardian.sql')))
            with self.assertRaises(dm.MigrationError):                              # sin duplicar: nada pendiente
                dm.apply(c, self.admin(), self.now(), 'APLICAR')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM migrations WHERE name='900_prueba_guardian.sql'").fetchone()[0], 1)
            after = {t: c.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0] for t in before}
            self.assertEqual(before, after)
            self.assertIsNone(g.lock_info(c))                                        # el bloqueo se libera siempre

    def test_partial_and_unrecorded_structure_are_critical(self):
        mig = self.sandbox()
        (mig / '900_prueba_guardian.sql').write_text('CREATE TABLE IF NOT EXISTS guardian_a (id INTEGER PRIMARY KEY);\nCREATE TABLE IF NOT EXISTS guardian_b (id INTEGER PRIMARY KEY);\n')
        with app.connect() as c:
            c.execute('CREATE TABLE guardian_a (id INTEGER PRIMARY KEY)');c.commit()   # aplicada a medias, sin registro
            item = next(i for i in g.migrations(c)['items'] if i['name'] == '900_prueba_guardian.sql')
            self.assertEqual(item['state'], 'sin_registro')
            c.execute("INSERT INTO migrations VALUES ('900_prueba_guardian.sql')");c.commit()  # registrada sin toda su estructura
            item = next(i for i in g.migrations(c)['items'] if i['name'] == '900_prueba_guardian.sql')
            self.assertEqual((item['state'], item['missing']), ('incompleta', ['guardian_b']))
            got = g.check(c, self.now(), sleep=lambda s: None)
            self.assertEqual(got['level'], 'rojo')
            with patch.object(stability, 'ROOT', mig.parent):
                self.assertFalse(stability.execute(*stability.checks(c)[0])['ok'])

    def test_duplicate_and_modified_migrations_are_detected_and_block_publishing(self):
        mig = self.sandbox()
        self.assertEqual(g.precheck(), [])
        (mig / '119_otra_duplicada.sql').write_text('CREATE TABLE IF NOT EXISTS guardian_dup (id INTEGER PRIMARY KEY);\n')
        path = mig / '120_financial_rates.sql'
        path.write_text(path.read_text() + '\n-- cambio posterior\n')
        problems = g.precheck()
        self.assertTrue(any('número repetido' in p for p in problems))
        self.assertTrue(any('120_financial_rates.sql: se modificó' in p for p in problems))
        with app.connect() as c:
            states = {i['name']: i['state'] for i in g.migrations(c)['items']}
        self.assertEqual(states['120_financial_rates.sql'], 'modificada')
        self.assertIn(states['119_otra_duplicada.sql'], ('duplicada',))

    def test_two_processes_cannot_migrate_at_once(self):
        self.sandbox()
        (g.MIGRATIONS / '900_prueba_guardian.sql').write_text('CREATE TABLE IF NOT EXISTS guardian_prueba (id INTEGER PRIMARY KEY);\n')
        with app.connect() as c:
            self.assertTrue(g.acquire(c, 'instancia A', self.now()))
            self.assertFalse(g.acquire(c, 'instancia B', self.now()))
            self.assertEqual(g.status(c, self.now())['level'], 'azul')             # recuperación en curso
            with self.assertRaises(dm.MigrationError) as raised:
                dm.apply(c, self.admin(), self.now(), 'APLICAR')
            self.assertEqual(raised.exception.status, 409)
            self.assertFalse(c.execute("SELECT 1 FROM migrations WHERE name='900_prueba_guardian.sql'").fetchone())
            held = g._get(c, g.LOCK_KEY, {})
            held['epoch'] -= g.LOCK_SECONDS + 1
            g._set(c, g.LOCK_KEY, held);c.commit()                                   # instancia A se cayó: bloqueo caducado
            self.assertEqual(dm.apply(c, self.admin(), self.now(), 'APLICAR')['applied'], ['900_prueba_guardian.sql'])
            self.assertTrue(any(i['code'] == 'MIG-LOCK' for i in g.history(c)))

    def test_failure_during_update_leaves_nothing_half_applied(self):
        mig = self.sandbox()
        (mig / '900_prueba_guardian.sql').write_text('CREATE TABLE IF NOT EXISTS guardian_ok (id INTEGER PRIMARY KEY);\n'
                                                      'CREATE INDEX IF NOT EXISTS guardian_mal ON tabla_que_no_existe(x);\n')
        with app.connect() as c:
            with self.assertRaises(dm.MigrationError):
                dm.apply(c, self.admin(), self.now(), 'APLICAR')
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='guardian_ok'").fetchone())
            self.assertFalse(c.execute("SELECT 1 FROM migrations WHERE name='900_prueba_guardian.sql'").fetchone())
            self.assertIsNone(g.lock_info(c))

    # ---- Rutas, exportación e integración -----------------------------------------------------------------------------------------------

    def test_routes_export_integrity_and_notifications(self):
        cookie, csrf = self.login()
        got = self.request('/api/system/db-guardian', {'action': 'diagnose'}, cookie=cookie, csrf=csrf)
        self.assertEqual(got['status'], 200, got['body'])
        self.assertIn(got['body']['level'], ('verde', 'amarillo'))
        self.assertTrue(got['body']['migration_items'])
        integ = self.request('/api/system/db-guardian', {'action': 'integrity'}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual(integ['schema'], [])
        self.assertIn('payment_commitments', integ['tables'])
        exp = self.request('/api/system/db-guardian/export', cookie=cookie)
        self.assertEqual(exp['status'], 200)
        text = exp['body'].decode() if isinstance(exp['body'], bytes) else json.dumps(exp['body'])
        self.assertNotIn('TURSO_AUTH_TOKEN', text)
        self.assertNotIn('password', text.lower())
        self.assertEqual(self.request('/api/system/db-guardian', {'action': 'release_lock'}, cookie=cookie, csrf=csrf)['status'], 409)
        mig = self.sandbox()
        (mig / '900_prueba_guardian.sql').write_text('CREATE TABLE IF NOT EXISTS guardian_prueba (id INTEGER PRIMARY KEY);\n')
        import notifications
        with app.connect() as c:
            built = notifications.build(c, self.admin(), self.now(), limit=None)
            items = built['items'] if isinstance(built, dict) else built
            keys = [n['key'] for n in items if n['key'].startswith('guardian:')]
        self.assertIn('guardian:pending:900_prueba_guardian.sql', keys)

    def test_only_administration(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/system/db-guardian', cookie=cookie)['status'], 403)


if __name__ == '__main__':
    unittest.main()
