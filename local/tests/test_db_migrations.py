"""Sistema → Migraciones de la base de datos (1.5.317). Base temporal por prueba y datos ficticios.

Simula producción con la migración 115 sin aplicar (Vercel no ejecuta migraciones) y comprueba: que solo se aceptan migraciones que
crean tablas o índices nuevos; que sin un respaldo verificado reciente no se aplica nada; la confirmación escrita; que solo
administración puede consultarlas y aplicarlas; que al aplicar se crean las tablas, se registra la migración, ninguna tabla pierde
filas y la comprobación de estabilidad deja de marcar migraciones pendientes."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import test_app
import app
import backups as bk
import db_migrations

M115 = '115_whatsapp_identity.sql'
TABLES = ('order_authorized_contacts', 'wa_identity_state', 'wa_identity_challenges', 'wa_identity_sessions', 'wa_identity_events')


class DbMigrationsTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def unapply_115(self):
        with app.connect() as c:
            for table in TABLES:
                c.execute('DROP TABLE IF EXISTS ' + table)
            c.execute('DELETE FROM migrations WHERE name=?', (M115,))
            c.commit()

    def verified_backup(self, hours_ago=1):
        when = app.reception_now() - timedelta(hours=hours_ago)
        with app.connect() as c:
            bk.set_state(c, 'backup_runs', [{'id': 'r-ficticio', 'kind': 'respaldo', 'destination': 'gdrive', 'status': 'correcto', 'verified': True,
                                             'requested_at': when.isoformat(timespec='seconds'), 'started_at': when.isoformat(timespec='seconds'),
                                             'finished_at': when.isoformat(timespec='seconds'), 'file': 'respaldo-ficticio.tar.gz.enc'}])
            c.commit()

    def session(self):
        cookie, csrf = self.login()
        return cookie, csrf

    def test_only_additive_migrations_are_accepted(self):
        self.assertTrue(db_migrations.check(app.ROOT / 'migrations' / M115)[0])
        with tempfile.TemporaryDirectory() as folder:
            for sql in ('ALTER TABLE orders ADD COLUMN x TEXT;', 'CREATE TABLE IF NOT EXISTS t(a);\nUPDATE orders SET status=1;', 'DROP TABLE clients;',
                        "CREATE TABLE IF NOT EXISTS t(a TEXT DEFAULT ';'); DELETE FROM clients;", "CREATE TABLE IF NOT EXISTS t(a TEXT DEFAULT 'x;", 'CREATE TABLE t(a);', '-- solo un comentario'):
                path = Path(folder) / '999_prueba.sql'
                path.write_text(sql)
                self.assertFalse(db_migrations.check(path)[0], sql)
            path.write_text("-- comentario; con punto y coma\nCREATE TABLE IF NOT EXISTS t(a TEXT DEFAULT ';');\nCREATE INDEX IF NOT EXISTS t_a ON t(a);")
            self.assertTrue(db_migrations.check(path)[0])

    def test_requires_recent_verified_backup_and_confirmation(self):
        self.unapply_115()
        cookie, csrf = self.session()
        state = self.request('/api/system/migrations', cookie=cookie)['body']
        self.assertEqual([m['name'] for m in state['pending']], [M115])
        self.assertEqual(state['applicable'], [M115])
        self.assertFalse(state['ready'])
        refused = self.request('/api/system/migrations/apply', {'confirm': 'APLICAR'}, cookie=cookie, csrf=csrf)
        self.assertEqual(refused['status'], 409)
        self.assertIn('respaldo', refused['body']['error'])
        self.verified_backup(hours_ago=30)   # demasiado antiguo
        self.assertEqual(self.request('/api/system/migrations/apply', {'confirm': 'APLICAR'}, cookie=cookie, csrf=csrf)['status'], 409)
        self.verified_backup(hours_ago=1)
        self.assertEqual(self.request('/api/system/migrations/apply', {'confirm': 'si'}, cookie=cookie, csrf=csrf)['status'], 400)
        with app.connect() as c:
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='wa_identity_sessions'").fetchone())

    def test_apply_creates_tables_keeps_data_and_clears_stability(self):
        self.unapply_115()
        self.verified_backup()
        with app.connect() as c:
            before = db_migrations._counts(c)
        cookie, csrf = self.session()
        done = self.request('/api/system/migrations/apply', {'confirm': 'aplicar'}, cookie=cookie, csrf=csrf)
        self.assertEqual(done['status'], 200, done['body'])
        self.assertEqual(done['body']['applied'], [M115])
        self.assertEqual(done['body']['lost'], [])
        self.assertEqual(done['body']['status']['pending'], [])
        with app.connect() as c:
            for table in TABLES:
                self.assertTrue(c.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone(), table)
            self.assertTrue(c.execute('SELECT 1 FROM migrations WHERE name=?', (M115,)).fetchone())
            after = db_migrations._counts(c)
            self.assertTrue(all(after[t] >= n for t, n in before.items()))
            self.assertTrue(c.execute("SELECT 1 FROM audit WHERE action='migrations_applied'").fetchone())
            # Lo mismo que comprueba «Conectividad con la base de datos» en Estabilidad: todas las migraciones del código aplicadas.
            files = {p.name for p in (app.ROOT / 'migrations').glob('*.sql')}
            self.assertEqual(files - {row[0] for row in c.execute('SELECT name FROM migrations')}, set())
        # Aplicar otra vez no hace nada.
        again = self.request('/api/system/migrations/apply', {'confirm': 'APLICAR'}, cookie=cookie, csrf=csrf)
        self.assertEqual(again['status'], 409)
        self.assertIn('No hay migraciones pendientes', again['body']['error'])

    def test_database_error_is_explained_and_leaves_nothing_half_applied(self):
        import shutil
        from unittest.mock import patch
        self.unapply_115()
        self.verified_backup()
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(app.ROOT / 'migrations', Path(folder) / 'migrations')
            # Parece aditiva (pasa el análisis) pero la base la rechaza al ejecutarla.
            (Path(folder) / 'migrations' / '999_rota.sql').write_text('CREATE TABLE IF NOT EXISTS tabla_rota(a);\nCREATE INDEX IF NOT EXISTS indice_roto ON tabla_inexistente(a);')
            cookie, csrf = self.session()
            with patch.object(db_migrations, 'ROOT', Path(folder)):
                got = self.request('/api/system/migrations/apply', {'confirm': 'APLICAR'}, cookie=cookie, csrf=csrf)
            self.assertEqual(got['status'], 502, got['body'])
            self.assertIn('999_rota.sql', got['body']['error'])
            self.assertIn('Antes se aplicaron: ' + M115, got['body']['error'])
        with app.connect() as c:
            self.assertTrue(c.execute('SELECT 1 FROM migrations WHERE name=?', (M115,)).fetchone())
            self.assertFalse(c.execute("SELECT 1 FROM migrations WHERE name='999_rota.sql'").fetchone())
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='tabla_rota'").fetchone())   # nada a medias

    def test_only_administration(self):
        self.unapply_115()
        self.verified_backup()
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico'")
            c.commit()
        cookie, csrf = self.session()
        self.assertEqual(self.request('/api/system/migrations', cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/system/migrations/apply', {'confirm': 'APLICAR'}, cookie=cookie, csrf=csrf)['status'], 403)
        with app.connect() as c:
            self.assertFalse(c.execute('SELECT 1 FROM migrations WHERE name=?', (M115,)).fetchone())


if __name__ == '__main__':
    unittest.main()
