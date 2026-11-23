"""Bloqueo de emisión y envío de comprobantes, verificado en el SERVIDOR (no solo en la interfaz).

Dos llaves, las dos deben estar abiertas para emitir o enviar:
1. Variable de entorno FACTURACION_EMISION_BLOQUEADA: cualquier valor distinto de «NO» (incluida su ausencia) = bloqueado.
2. Estado en la base (tabla invoicing_emission_lock): solo administración lo abre, con confirmación escrita y motivo; queda auditado.
Si la tabla no existe (migración 117 pendiente) o falla la lectura, se considera BLOQUEADO.

Bloquea: emitir en Órdenes Pro (consume secuencial), enviar/reprocesar/anular en AZUR, la consulta programada de AZUR y los correos
de facturas (prueba, cliente y reenvío). No bloquea consultas de solo lectura ni la vista previa local."""
import os
import re
import sqlite3

BANNER = 'CONFIGURACIÓN EN CURSO — EMISIÓN Y ENVÍO BLOQUEADOS'
CONFIRM_OPEN = 'HABILITAR EMISION'
ENV_VAR = 'FACTURACION_EMISION_BLOQUEADA'


class EmissionLocked(Exception):
    status = 423

    def __init__(self, action=''):
        super().__init__('%s. %s no está permitido hasta que administración habilite la emisión.' % (BANNER, action or 'Esta operación'))


def env_locked(env=None):
    env = os.environ if env is None else env
    return env.get(ENV_VAR, '').strip().upper() != 'NO'


def _row(c):
    try:
        row = c.execute('SELECT locked,reason,changed_by,changed_at FROM invoicing_emission_lock WHERE id=1').fetchone()
    except sqlite3.Error:
        return None
    return row


def _table(c):
    try:
        c.execute('SELECT 1 FROM invoicing_emission_lock LIMIT 1').fetchone()
        return True
    except sqlite3.Error:
        return False


def db_locked(c):
    row = _row(c)
    return True if row is None else bool(row[0])


def is_locked(c, env=None):
    return env_locked(env) or db_locked(c)


def check(c, action='', env=None):
    if is_locked(c, env):
        raise EmissionLocked(action)


def status(c, env=None):
    row = _row(c)
    return {'locked': is_locked(c, env), 'banner': BANNER if is_locked(c, env) else '', 'env_locked': env_locked(env),
            'db_locked': db_locked(c), 'table_ready': _table(c), 'reason': row[1] if row else ('Configuración en curso: emisión y envío bloqueados.' if _table(c) else 'Migración 117 pendiente: se trata como bloqueado.'),
            'changed_at': row[3] if row else '', 'confirm_text': CONFIRM_OPEN}


def set_state(c, user, data, now, env=None):
    """Abre o cierra el bloqueo en la base. Cerrar siempre se permite a administración; abrir exige confirmación escrita y motivo."""
    if not user or user['role'] != 'administrador':
        raise PermissionError('Solo administración cambia el bloqueo de emisión.')
    if not _table(c):
        raise ValueError('Falta aplicar la migración 117 (bloqueo de emisión).')
    c.execute("INSERT OR IGNORE INTO invoicing_emission_lock(id,locked,reason,changed_at) VALUES (1,1,'','')")
    lock = str(data.get('locked', '1')) != '0'
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if not lock:
        if str(data.get('confirm', '')).strip().upper() != CONFIRM_OPEN:
            raise ValueError('Escribe %s para confirmar.' % CONFIRM_OPEN)
        if not 10 <= len(reason) <= 300:
            raise ValueError('Indica el motivo (10 a 300 caracteres).')
    reason = reason or 'Bloqueo de emisión activado.'
    stamp = now.isoformat(timespec='seconds')
    c.execute('UPDATE invoicing_emission_lock SET locked=?,reason=?,changed_by=?,changed_at=? WHERE id=1', (1 if lock else 0, reason[:300], user['id'], stamp))
    c.execute('INSERT INTO invoicing_emission_lock_events(locked,reason,actor_id,created_at) VALUES (?,?,?,?)', (1 if lock else 0, reason[:300], user['id'], stamp))
    result = status(c, env)
    if not lock and result['env_locked']:
        result['warning'] = 'La base quedó abierta, pero %s sigue bloqueando en el servidor: la emisión continúa BLOQUEADA.' % ENV_VAR
    return result
