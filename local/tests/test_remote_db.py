"""Adaptador libSQL/Turso. Requiere un servidor de pruebas vacío: LIBSQL_TEST_URL=http://127.0.0.1:PUERTO."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import remote_db

URL=os.getenv('LIBSQL_TEST_URL','')


@unittest.skipUnless(URL.startswith('http://127.0.0.1:'),'Define LIBSQL_TEST_URL con un servidor libSQL local de pruebas.')
class RemoteDatabaseTests(unittest.TestCase):
    def connect(self):
        return remote_db.Connection(URL,'')

    def setUp(self):
        c=self.connect()
        c.executescript('DROP TABLE IF EXISTS fixture_child;DROP TABLE IF EXISTS fixture_parent;'
            'CREATE TABLE fixture_parent(id INTEGER PRIMARY KEY,name TEXT UNIQUE,amount REAL,payload BLOB);'
            'CREATE TABLE fixture_child(id INTEGER PRIMARY KEY,parent_id INTEGER NOT NULL REFERENCES fixture_parent(id));'
            "CREATE TRIGGER fixture_no_delete BEFORE DELETE ON fixture_parent BEGIN SELECT RAISE(ABORT,'fixture immutable'); END;")

    def tearDown(self):
        self.connect().executescript('DROP TABLE IF EXISTS fixture_child;DROP TABLE IF EXISTS fixture_parent;')

    def test_values_rows_and_cursor_metadata(self):
        with self.connect() as c:
            cursor=c.execute('INSERT INTO fixture_parent(name,amount,payload) VALUES (?,?,?)',('ñandú',1.5,b'\x00\xff'))
            self.assertEqual((cursor.lastrowid,cursor.rowcount),(1,1))
            row=c.execute('SELECT id,name,amount,payload,NULL empty,id FROM fixture_parent').fetchone()
        self.assertEqual(tuple(row),(1,'ñandú',1.5,b'\x00\xff',None,1))
        self.assertEqual((row['NAME'],row[0],len(row)),('ñandú',1,6))
        self.assertEqual(dict(row),{'id':1,'name':'ñandú','amount':1.5,'payload':b'\x00\xff','empty':None})
        with self.connect() as c:
            cursor=c.execute('SELECT id FROM fixture_parent WHERE id=?',(99,))
            self.assertEqual((cursor.fetchone(),cursor.fetchall(),cursor.rowcount),(None,[],-1))

    def test_writes_wait_for_commit_and_errors_roll_back(self):
        c=self.connect()
        c.execute("INSERT INTO fixture_parent(name) VALUES ('pendiente')")
        self.assertTrue(c.in_transaction)
        self.assertEqual(c.execute('SELECT count(*) FROM fixture_parent').fetchone()[0],1)
        self.assertEqual(self.connect().execute('SELECT count(*) FROM fixture_parent').fetchone()[0],0)
        c.close()
        with self.assertRaises(RuntimeError):
            with self.connect() as c:
                c.execute('BEGIN IMMEDIATE');c.execute("INSERT INTO fixture_parent(name) VALUES ('descartado')")
                raise RuntimeError('fallo de prueba')
        with self.connect() as c:c.executemany('INSERT INTO fixture_parent(name) VALUES (?)',[(f'fila-{n}',) for n in range(250)])
        with self.connect() as c:self.assertEqual(c.execute('SELECT count(*),max(name) FROM fixture_parent').fetchone()[0],250)

    def test_constraints_triggers_and_foreign_keys_raise_integrity_errors(self):
        with self.connect() as c:c.execute("INSERT INTO fixture_parent(name) VALUES ('único')")
        for statement in ("INSERT INTO fixture_parent(name) VALUES ('único')",'DELETE FROM fixture_parent','INSERT INTO fixture_child(parent_id) VALUES (99)'):
            with self.connect() as c:
                with self.assertRaises(sqlite3.IntegrityError):c.execute(statement)
        with self.connect() as c:
            with self.assertRaises(sqlite3.OperationalError):c.execute('SELECT * FROM fixture_missing')
            self.assertEqual(c.execute('SELECT count(*) FROM fixture_parent').fetchone()[0],1)

    def test_failed_script_leaves_no_partial_changes_and_backup_copies_everything(self):
        c=self.connect()
        with self.assertRaises(sqlite3.Error):
            c.executescript("BEGIN IMMEDIATE;INSERT INTO fixture_parent(name) VALUES ('parcial');INSERT INTO fixture_missing VALUES (1);COMMIT;")
        self.assertEqual(c.execute('SELECT count(*) FROM fixture_parent').fetchone()[0],0)
        with self.connect() as c:
            c.execute("INSERT INTO fixture_parent(name,payload) VALUES ('respaldo',?)",(b'\x01',))
            c.execute('INSERT INTO fixture_child(parent_id) VALUES (1)')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'backup.sqlite3'
            remote_db.backup(self.connect(),path)
            copy=sqlite3.connect(path)
            try:
                self.assertEqual(copy.execute('SELECT name,payload FROM fixture_parent').fetchall(),[('respaldo',b'\x01')])
                self.assertEqual(copy.execute('SELECT parent_id FROM fixture_child').fetchall(),[(1,)])
                self.assertEqual(copy.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='fixture_no_delete'").fetchone()[0],1)
            finally:copy.close()


if __name__=='__main__':
    unittest.main()
