"""Centro de Control Operativo (1.5.288): acciones propias del centro sobre un pendiente.

Lo que cambia un registro de origen (confirmar una cita, decidir un presupuesto, avanzar un repuesto, cambiar el estado de una orden…)
se hace con los endpoints de cada módulo, que ya validan permisos, reglas y auditoría. Aquí solo hay lo que el centro añade:
- nota: observación interna del pendiente (cualquier persona que lo vea).
- recordatorio: fecha para volver a revisarlo (no lo resuelve ni lo oculta).
- reconocer / silenciar / resolucion: alertas del sistema, solo administración. Un fallo activo (crítico) no se silencia y ninguna de
  estas acciones quita la alerta: desaparece cuando su módulo deja de detectar la condición.
- asignar: responsable de una orden (solo administración), con control de revisión para no pisar cambios de otra persona.
Todo queda en pending_notes (solo anexado) y en la auditoría. Las repeticiones idénticas en pocos segundos se ignoran (doble clic).
"""
import re
from datetime import date, datetime, timedelta

import pending_center

SILENCE_HOURS = (1, 4, 8, 24, 72)


class ActionError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def _text(data, key, limit, minimum=0, label='el texto'):
    value = re.sub(r'[ \t]+', ' ', str(data.get(key, '') or '')).strip()
    value = re.sub(r'\n{3,}', '\n\n', value)
    if len(value) > limit:
        raise ActionError('Escribe %s en %d caracteres como máximo.' % (label, limit), 400, {key: 'Demasiado largo.'})
    if len(value) < minimum:
        raise ActionError('Escribe %s (al menos %d caracteres).' % (label, minimum), 400, {key: 'Obligatorio.'})
    return value


def _duplicate(c, entity, kind, body, user, now):
    """La misma acción con el mismo texto de la misma persona en los últimos 15 s: doble clic o reintento, no se registra dos veces."""
    since = (now - timedelta(seconds=15)).isoformat(timespec='seconds')
    return c.execute('SELECT id FROM pending_notes WHERE key=? AND kind=? AND body=? AND user_id=? AND created_at>=? ORDER BY id DESC LIMIT 1',
                     (entity, kind, body, user['id'], since)).fetchone()


def _record(c, item, kind, body, user, now, until=''):
    found = _duplicate(c, item['entity'], kind, body, user, now)
    if found:
        return found['id'], True
    nid = c.execute('INSERT INTO pending_notes(key,module,kind,body,until,user_id,created_at) VALUES (?,?,?,?,?,?,?)',
                    (item['entity'], item['module'], kind, body, until, user['id'], now.isoformat(timespec='seconds'))).lastrowid
    return nid, False


def _ready(c):
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pending_notes'").fetchone() is None:
        raise ActionError('Esta función necesita una actualización de la base de datos que todavía no se aplicó. Avisa a administración.', 503)


def run(c, user, now, data, notices=(), audit=None):
    """Ejecuta una acción del centro. Devuelve el resultado (y el pendiente actualizado si sigue existiendo)."""
    if user['role'] not in ('administrador', 'tecnico'):
        raise ActionError('Acceso no permitido.', 403)
    admin = user['role'] == 'administrador'
    action = str(data.get('action', ''))
    if action == 'assign':
        return _assign(c, user, now, data, admin, audit)
    if action not in ('note', 'remind', 'ack', 'silence', 'resolve'):
        raise ActionError('Acción no válida.')
    _ready(c)
    item = pending_center.find(c, user, now, str(data.get('key', ''))[:200], notices)
    if not item:
        # Mismo mensaje si no existe o no le corresponde: no revela pendientes de otras personas.
        raise ActionError('Este pendiente ya no está disponible: puede que se haya resuelto en su módulo.', 404)
    if action in ('ack', 'silence', 'resolve'):
        if item['module'] != 'alerts':
            raise ActionError('Esta acción es solo para alertas del sistema.', 400)
        if not admin:
            raise ActionError('Solo administración gestiona las alertas del sistema.', 403)
    until, duplicate = '', False
    if action == 'note':
        body = _text(data, 'body', 1500, 3, 'la observación')
        nid, duplicate = _record(c, item, 'nota', body, user, now)
    elif action == 'remind':
        body = _text(data, 'body', 300, 0, 'el motivo')
        raw = str(data.get('date', ''))
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            raise ActionError('Indica una fecha válida para el recordatorio.', 400, {'date': 'Fecha no válida.'})
        if day < now.date() or day > now.date() + timedelta(days=365):
            raise ActionError('El recordatorio debe ser desde hoy y dentro del próximo año.', 400, {'date': 'Fuera de rango.'})
        until = day.isoformat()
        nid, duplicate = _record(c, item, 'recordatorio', body, user, now, until)
    elif action == 'ack':
        body = _text(data, 'body', 500, 0, 'la nota')
        nid, duplicate = _record(c, item, 'reconocida', body, user, now)
    elif action == 'silence':
        if not (item.get('ref') or {}).get('can_silence'):
            raise ActionError('Un fallo activo no se puede silenciar: se mantiene visible hasta que se resuelva.', 409)
        try:
            hours = int(str(data.get('hours', '')))
        except ValueError:
            hours = 0
        if hours not in SILENCE_HOURS:
            raise ActionError('Elige una duración válida para el silencio.', 400, {'hours': 'Duración no válida.'})
        body = _text(data, 'body', 500, 5, 'el motivo del silencio')
        until = (now + timedelta(hours=hours)).isoformat(timespec='seconds')
        nid, duplicate = _record(c, item, 'silenciada', body, user, now, until)
    else:
        body = _text(data, 'body', 1500, 10, 'cómo se resolvió')
        nid, duplicate = _record(c, item, 'resolucion', body, user, now)
    if not duplicate and audit:
        audit(c, user['id'], {'note': 'pending_note', 'remind': 'pending_reminder', 'ack': 'pending_ack', 'silence': 'pending_silence', 'resolve': 'pending_resolution'}[action], nid)
    return {'ok': True, 'duplicate': duplicate, 'id': nid, 'until': until, 'entity': item['entity']}


def _assign(c, user, now, data, admin, audit):
    """Responsable de una orden. Solo administración (igual que la edición de la orden); comprueba la revisión para no pisar otro cambio."""
    if not admin:
        raise ActionError('Solo administración asigna el responsable de una orden.', 403)
    oid = str(data.get('order_id', ''))
    row = c.execute("SELECT o.id,o.revision,o.assigned_to,o.status,COALESCE(u.name,'') tech FROM orders o LEFT JOIN users u ON u.id=o.assigned_to WHERE o.id=?",
                    (int(oid),)).fetchone() if oid.isdigit() else None
    if not row:
        raise ActionError('Orden no disponible.', 404)
    if row['status'] == 'entregado':
        raise ActionError('La orden ya fue entregada.', 409)
    if str(data.get('revision', '')) != str(row['revision']):
        raise ActionError('Otra persona actualizó esta orden. Se recargaron los datos: revisa y vuelve a intentarlo.', 409)
    target = str(data.get('technician', ''))
    staff = c.execute("SELECT id,name FROM users WHERE id=? AND active=1 AND role IN ('administrador','tecnico')", (int(target),)).fetchone() if target.isdigit() else None
    if target and not staff:
        raise ActionError('Elige una persona activa del equipo.', 400, {'technician': 'No válido.'})
    new = staff['id'] if staff else None
    if new == row['assigned_to']:
        return {'ok': True, 'unchanged': True}
    stamp = now.isoformat(timespec='microseconds')
    changed = c.execute('UPDATE orders SET assigned_to=?,updated_at=?,revision=revision+1 WHERE id=? AND revision=?', (new, stamp, row['id'], row['revision'])).rowcount
    if changed != 1:
        raise ActionError('Otra persona actualizó esta orden. Se recargaron los datos: revisa y vuelve a intentarlo.', 409)
    import order_workspace
    order_workspace.event(c, row['id'], user['id'], now, 'updated', 'Responsable: %s → %s (desde el Centro de Control).' % (row['tech'] or 'Sin asignar', staff['name'] if staff else 'Sin asignar'))
    if audit:
        audit(c, user['id'], 'order_assigned', row['id'])
    return {'ok': True, 'assigned_to': new, 'name': staff['name'] if staff else ''}
