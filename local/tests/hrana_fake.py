"""Servidor libSQL de pruebas (protocolo Hrana v2 por HTTP) sobre un archivo SQLite local.

Reproduce lo que importa del servicio remoto: flujos con «baton» que conservan una transacción entre peticiones, lotes con
condiciones, secuencias y, sobre todo, que el servidor CIERRA las conexiones HTTP inactivas (keep-alive) al cabo de `idle`
segundos, como hace Turso. Con `stream_idle`, además, descarta la transacción de un flujo que pasó más de ese tiempo sin usarse,
con el mismo mensaje que Turso («stream was idle for too long»). Solo para pruebas automáticas: escucha en 127.0.0.1 y no tiene autenticación.
"""
import base64
import http.server
import json
import secrets
import sqlite3
import threading
import time


def _value(item):
    kind = item['type']
    if kind == 'null':
        return None
    if kind == 'integer':
        return int(item['value'])
    if kind == 'float':
        return float(item['value'])
    if kind == 'blob':
        return base64.b64decode(item['base64'])
    return item['value']


def _encode(value):
    if value is None:
        return {'type': 'null'}
    if isinstance(value, int):
        return {'type': 'integer', 'value': str(value)}
    if isinstance(value, float):
        return {'type': 'float', 'value': value}
    if isinstance(value, bytes):
        return {'type': 'blob', 'base64': base64.b64encode(value).decode()}
    return {'type': 'text', 'value': str(value)}


def _error(error):
    code = 'SQLITE_CONSTRAINT' if isinstance(error, sqlite3.IntegrityError) else 'SQLITE_ERROR'
    return {'message': 'SQLite error: ' + str(error), 'code': code}


class FakeLibsql:
    def __init__(self, path, idle=0.3, stream_idle=None):
        self.path, self.idle, self.stream_idle = path, idle, stream_idle
        self.streams, self.used, self.lock = {}, {}, threading.Lock()
        self.requests = 0
        self.fail_next = 0  # Respuestas que se cortan sin contestar (simula una caída de red en mitad de la petición).
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            timeout = idle  # Conexión inactiva más de `idle` segundos: el servidor la cierra.

            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                server.requests += 1
                if server.fail_next:
                    server.fail_next -= 1
                    self.close_connection = True
                    return
                body = json.dumps(server.pipeline(json.loads(raw))).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.url = 'http://127.0.0.1:%d' % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for stream in self.streams.values():
            stream.close()

    def _connection(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def _execute(self, c, stmt):
        args = [_value(item) for item in stmt.get('args', [])]
        if stmt.get('named_args'):
            args = {item['name'].lstrip(':@$'): _value(item['value']) for item in stmt['named_args']}
        cursor = c.execute(stmt['sql'], args)
        cols = [{'name': col[0], 'decltype': None} for col in cursor.description or ()]
        rows = [[_encode(value) for value in row] for row in cursor.fetchall()] if cols else []
        return {'cols': cols, 'rows': rows, 'affected_row_count': max(cursor.rowcount, 0), 'last_insert_rowid': str(cursor.lastrowid) if cursor.lastrowid else None}

    def pipeline(self, body):
        baton = body.get('baton')
        with self.lock:
            c = self.streams.pop(baton, None) if baton else self._connection()
            used = self.used.pop(baton, None)
        if c is not None and self.stream_idle is not None and used is not None and time.monotonic() - used > self.stream_idle:
            if c.in_transaction:
                c.rollback()
            c.close()
            message = 'interactive transaction was rolled back because the stream was idle for too long; retry the transaction'
            return {'baton': None, 'base_url': None, 'results': [{'type': 'error', 'error': {'message': message}} for _ in body['requests']]}
        if c is None:
            return {'baton': None, 'base_url': None, 'results': [{'type': 'error', 'error': {'message': 'Stream not found', 'code': 'STREAM_EXPIRED'}} for _ in body['requests']]}
        results, closed = [], False
        for request in body['requests']:
            kind = request['type']
            try:
                if kind == 'execute':
                    results.append({'type': 'ok', 'response': {'type': 'execute', 'result': self._execute(c, request['stmt'])}})
                elif kind == 'batch':
                    outcomes, errors = [], []
                    for step in request['batch']['steps']:
                        condition = step.get('condition')
                        if condition and not (condition['type'] == 'ok' and errors[condition['step']] is None and outcomes[condition['step']] is not None):
                            outcomes.append(None)
                            errors.append(None)
                            continue
                        try:
                            outcomes.append(self._execute(c, step['stmt']))
                            errors.append(None)
                        except sqlite3.Error as error:
                            outcomes.append(None)
                            errors.append(_error(error))
                    results.append({'type': 'ok', 'response': {'type': 'batch', 'result': {'step_results': outcomes, 'step_errors': errors}}})
                elif kind == 'sequence':
                    c.executescript(request['sql'])
                    results.append({'type': 'ok', 'response': {'type': 'sequence'}})
                elif kind == 'close':
                    closed = True
                    results.append({'type': 'ok', 'response': {'type': 'close'}})
            except sqlite3.Error as error:
                results.append({'type': 'error', 'error': _error(error)})
        if closed:
            if c.in_transaction:
                c.rollback()
            c.close()
            return {'baton': None, 'base_url': None, 'results': results}
        token = secrets.token_hex(8)
        with self.lock:
            self.streams[token] = c
            self.used[token] = time.monotonic()
        return {'baton': token, 'base_url': None, 'results': results}
