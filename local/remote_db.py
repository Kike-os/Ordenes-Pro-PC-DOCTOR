"""Base remota libSQL/Turso por HTTP (protocolo Hrana) con la interfaz de sqlite3 que usa la aplicación.

Se activa solo cuando TURSO_DATABASE_URL está definido; sin esa variable la aplicación sigue usando
el archivo SQLite local. El dialecto SQL, las migraciones y los triggers no cambian.
"""
import base64
import http.client
import json
import os
import sqlite3
import threading
from urllib.parse import urlsplit

TIMEOUT = 20
CHUNK = 100
_pool = threading.local()


def configured():
    return bool(os.getenv('TURSO_DATABASE_URL', '').strip())


def connect():
    return Connection(os.environ['TURSO_DATABASE_URL'].strip(), os.getenv('TURSO_AUTH_TOKEN', '').strip())


class Row:
    """Fila con acceso por posición o por nombre, como sqlite3.Row (el primer nombre repetido gana)."""
    __slots__ = ('_names', '_index', '_values')

    def __init__(self, names, index, values):
        self._names, self._index, self._values = names, index, values

    def keys(self):
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._index[key.lower()]]
            except KeyError:
                raise IndexError('No item with that key') from None
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __eq__(self, other):
        return isinstance(other, Row) and self._names == other._names and self._values == other._values

    def __hash__(self):
        return hash((self._names, self._values))

    def __repr__(self):
        return f'<Row {dict(zip(self._names, self._values))!r}>'


class Cursor:
    def __init__(self, result=None):
        result = result or {}
        names = tuple(col['name'] for col in result.get('cols', ()))
        index = {}
        for position, name in enumerate(names):
            index.setdefault(name.lower(), position)
        self.description = tuple((name, None, None, None, None, None, None) for name in names) or None
        self._rows = [Row(names, index, tuple(_decode(value) for value in row)) for row in result.get('rows', ())]
        self._next = 0
        self.rowcount = -1 if names else result.get('affected_row_count', -1)
        rowid = result.get('last_insert_rowid')
        self.lastrowid = int(rowid) if rowid is not None else None

    def fetchone(self):
        if self._next >= len(self._rows):
            return None
        self._next += 1
        return self._rows[self._next - 1]

    def fetchall(self):
        rows, self._next = self._rows[self._next:], len(self._rows)
        return rows

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class Connection:
    """Reproduce las transacciones implícitas de sqlite3: BEGIN antes de escribir y commit() explícito.

    Las lecturas fuera de transacción no conservan estado en el servidor. Una transacción ocupa un
    flujo Hrana hasta commit/rollback; cerrar ese flujo sin confirmar descarta los cambios.
    """

    def __init__(self, url, token):
        parts = urlsplit(url)
        self._secure = parts.scheme not in ('http', 'ws')
        self._host = parts.netloc
        self._token = token
        self._baton = None
        self.in_transaction = False

    def execute(self, sql, parameters=()):
        head = sql.lstrip()[:20].upper()
        if head.startswith('PRAGMA FOREIGN_KEYS'):
            return Cursor()  # Se aplica al abrir cada transacción; el servidor ya lo activa por defecto.
        statement = _statement(sql, parameters)
        if self.in_transaction:
            cursor = Cursor(self._send([{'type': 'execute', 'stmt': statement}])[0])
            if head.startswith(('COMMIT', 'ROLLBACK', 'END')):
                self._release()
            return cursor
        if head.startswith('BEGIN'):
            self._begin(sql)
            return Cursor()
        if head.startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')):
            return Cursor(self._begin('BEGIN', statement))
        return Cursor(self._send([{'type': 'execute', 'stmt': statement}, {'type': 'close'}])[0])

    def executemany(self, sql, rows):
        rows = list(rows)
        if rows and not self.in_transaction:
            self._begin('BEGIN')
        cursor = Cursor()
        for start in range(0, len(rows), CHUNK):
            for result in self._send([{'type': 'execute', 'stmt': _statement(sql, row)} for row in rows[start:start + CHUNK]]):
                cursor = Cursor(result)
        return cursor

    def executescript(self, script):
        if self.in_transaction:
            self.commit()
        # Cerrar el flujo descarta cualquier transacción que el script haya dejado abierta al fallar.
        self._send([{'type': 'sequence', 'sql': script}, {'type': 'close'}])
        return Cursor()

    def commit(self):
        self._finish('COMMIT')

    def rollback(self):
        self._finish('ROLLBACK')

    def close(self):
        if self._baton:
            try:
                self._send([{'type': 'close'}])
            except sqlite3.Error:
                pass
        self._release()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        try:
            if kind is None:
                self.commit()
            else:
                self.close()
        finally:
            self._release()
        return False

    def _begin(self, begin, statement=None):
        steps = [{'stmt': {'sql': 'PRAGMA foreign_keys=ON'}}, {'stmt': {'sql': begin}}]
        if statement:
            steps.append({'condition': {'type': 'ok', 'step': 1}, 'stmt': statement})
        # El flujo queda abierto desde el envío: si falla la sentencia, la transacción sigue pendiente de rollback.
        self.in_transaction = True
        try:
            result = self._send([{'type': 'batch', 'batch': {'steps': steps}}])[0]
            errors = [error for error in result['step_errors'][:2] if error]
        except sqlite3.Error:
            self.close()
            raise
        if errors:
            self.close()
            raise _error(errors[0])
        if statement and result['step_errors'][2]:
            raise _error(result['step_errors'][2])
        return result['step_results'][-1] if statement else None

    def _finish(self, sql):
        if not self.in_transaction:
            return
        try:
            self._send([{'type': 'execute', 'stmt': {'sql': sql}}, {'type': 'close'}])
        finally:
            self._release()

    def _release(self):
        self._baton = None
        self.in_transaction = False

    def _send(self, requests):
        body = {'requests': requests}
        if self._baton:
            body['baton'] = self._baton
        payload = _post(self._secure, self._host, self._token, body, retry=not self._baton and not self.in_transaction)
        self._baton = payload.get('baton')
        if payload.get('base_url'):
            parts = urlsplit(payload['base_url'])
            self._secure, self._host = parts.scheme != 'http', parts.netloc
        results = []
        for item in payload['results']:
            if item['type'] != 'ok':
                raise _error(item['error'])
            response = item['response']
            if response['type'] != 'close':
                results.append(response.get('result'))
        return results


def backup(connection, path):
    """Copia el esquema y los datos remotos a un archivo SQLite local antes de migrar."""
    target = sqlite3.connect(path)
    try:
        connection.execute('BEGIN')
        objects = connection.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid").fetchall()
        tables = [item for item in objects if item['type'] == 'table']
        for table in tables:
            target.execute(table['sql'])
        for name in [table['name'] for table in tables] + ['sqlite_sequence']:
            quoted = '"' + name.replace('"', '""') + '"'
            if name == 'sqlite_sequence' and not connection.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                continue
            rows = [tuple(row) for row in connection.execute('SELECT * FROM ' + quoted)]
            if rows:
                target.executemany('INSERT INTO ' + quoted + ' VALUES (' + ','.join('?' for _ in rows[0]) + ')', rows)
        for item in objects:
            if item['type'] != 'table':
                target.execute(item['sql'])
        target.commit()
    finally:
        target.close()
        connection.rollback()


def _statement(sql, parameters):
    statement = {'sql': sql}
    if isinstance(parameters, dict):
        statement['named_args'] = [{'name': name, 'value': _encode(value)} for name, value in parameters.items()]
    elif parameters:
        statement['args'] = [_encode(value) for value in parameters]
    return statement


def _encode(value):
    if value is None:
        return {'type': 'null'}
    if isinstance(value, (bool, int)):
        return {'type': 'integer', 'value': str(int(value))}
    if isinstance(value, float):
        return {'type': 'float', 'value': value}
    if isinstance(value, str):
        return {'type': 'text', 'value': value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'type': 'blob', 'base64': base64.b64encode(bytes(value)).decode('ascii')}
    raise sqlite3.ProgrammingError(f'Tipo de parámetro no admitido: {type(value).__name__}')


def _decode(value):
    kind = value['type']
    if kind == 'null':
        return None
    if kind == 'integer':
        return int(value['value'])
    if kind == 'blob':
        data = value['base64']
        return base64.b64decode(data + '=' * (-len(data) % 4))
    return value['value']


def _error(error):
    message = error.get('message', 'Error de base de datos').removeprefix('SQLite error: ')
    kind = sqlite3.IntegrityError if str(error.get('code', '')).startswith('SQLITE_CONSTRAINT') else sqlite3.OperationalError
    return kind(message)


def _post(secure, host, token, body, retry):
    connections = _pool.__dict__.setdefault('connections', {})
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode('utf-8')
    for attempt in (1, 2):
        connection = connections.get((secure, host))
        reused = connection is not None
        if not reused:
            kind = http.client.HTTPSConnection if secure else http.client.HTTPConnection
            connection = connections[(secure, host)] = kind(host, timeout=TIMEOUT)
        try:
            connection.request('POST', '/v2/pipeline', body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        except (OSError, http.client.HTTPException) as error:
            connection.close()
            connections.pop((secure, host), None)
            # Solo se reintenta una conexión reutilizada y sin transacción abierta: nunca se repite una escritura en curso.
            if reused and retry and attempt == 1:
                continue
            raise sqlite3.OperationalError('No se pudo contactar la base de datos remota.') from error
        if response.status != 200:
            raise sqlite3.OperationalError(f'La base de datos remota respondió HTTP {response.status}.')
        return json.loads(raw)
