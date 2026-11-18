"""Centro de Control Operativo (1.5.288): acciones propias del centro sobre un pendiente.

Lo que cambia un registro de origen (confirmar una cita, decidir un presupuesto, avanzar un repuesto, cambiar el estado de una orden…)
se hace con los endpoints de cada módulo, que ya validan permisos, reglas y auditoría. Aquí solo hay lo que el centro añade:
- nota: observación interna del pendiente (cualquier persona que lo vea).
- recordatorio: fecha para volver a revisarlo (no lo resuelve ni lo oculta).
- reconocer / silenciar / resolucion: alertas del sistema, solo administración. Un fallo activo (crítico) no se silencia y ninguna de
  estas acciones quita la alerta: desaparece cuando su módulo deja de detectar la condición.
- asignar: responsable de una orden (solo administración), con control de revisión para no pisar cambios de otra persona.
- 1.5.289 · responsable del seguimiento de cualquier otro pendiente (administración; un técnico puede tomar uno sin responsable), solo a
  personas que ya tienen acceso a ese pendiente; posponer hasta una fecha con motivo (nunca un fallo crítico) y reanudar.
Todo queda en pending_notes / pending_tracking (solo anexado) y en la auditoría. Las repeticiones idénticas en pocos segundos se ignoran.
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
    if action == 'assign' and data.get('order_id') not in (None, ''):
        return _assign(c, user, now, data, admin, audit)
    if action == 'diagnosis':
        return _diagnosis(c, user, now, data, admin, audit)
    if action in ('assign', 'take', 'postpone', 'resume'):
        return _track(c, user, now, data, admin, notices, audit, action)
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
    if _has(c, 'pending_tracking'):
        # Fecha y autor de la asignación para el centro; el responsable real sigue siendo el de la orden.
        c.execute('INSERT INTO pending_tracking(key,module,kind,assignee_id,until,body,user_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
                  ('orders:%d' % row['id'], 'orders', 'asignacion', new, '', str(data.get('body', '') or '')[:300].strip(), user['id'], now.isoformat(timespec='seconds')))
    if audit:
        audit(c, user['id'], 'order_assigned', row['id'])
    return {'ok': True, 'assigned_to': new, 'name': staff['name'] if staff else ''}


def _has(c, table):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _track(c, user, now, data, admin, notices, audit, action):
    """Responsable del seguimiento (asignar / tomar) y aplazamiento (posponer / reanudar) de un pendiente que esta persona puede ver."""
    if not _has(c, 'pending_tracking'):
        raise ActionError('Esta función necesita una actualización de la base de datos que todavía no se aplicó. Avisa a administración.', 503)
    item = pending_center.find(c, user, now, str(data.get('key', ''))[:200], notices)
    if not item:
        raise ActionError('Este pendiente ya no está disponible: puede que se haya resuelto en su módulo.', 404)
    ref = item.get('ref') or {}
    stamp = now.isoformat(timespec='seconds')
    last = (pending_center.tracking(c, [item['entity']]) or [])
    if action in ('assign', 'take'):
        if item['module'] == 'orders' or (item['module'] == 'messages' and ref.get('kind') == 'pqrs'):
            raise ActionError('El responsable de este pendiente se asigna en su módulo (orden o PQRS).', 400)
        if action == 'assign' and not admin:
            raise ActionError('Solo administración asigna responsables.', 403)
        if action == 'take':
            if item.get('responsible_id') is not None:
                raise ActionError('Este pendiente ya tiene responsable. Pide a administración que lo reasigne.', 409)
            target = str(user['id'])
        else:
            target = str(data.get('user', '') or '')
        person = None
        if target:
            person = c.execute("SELECT id,name,role FROM users WHERE id=? AND active=1 AND role IN ('administrador','tecnico')", (int(target),)).fetchone() if target.isdigit() else None
            if not person:
                raise ActionError('Elige una persona activa del equipo.', 400, {'user': 'No válido.'})
            # Solo a quien ya ve ese pendiente: asignar no amplía permisos ni muestra datos de clientes a quien no le corresponden.
            seen = pending_center.find(c, {'id': person['id'], 'role': person['role']}, now, item['entity'], notices if person['role'] == 'administrador' else ())
            if not seen:
                raise ActionError('%s no tiene acceso a este pendiente. Asigna primero el técnico en su módulo.' % person['name'], 409, {'user': 'Sin acceso.'})
        new = person['id'] if person else None
        current = next((t for t in reversed(last) if t['kind'] == 'asignacion'), None)
        if current and current['assignee_id'] == new:
            return {'ok': True, 'unchanged': True, 'entity': item['entity']}
        body = _text(data, 'body', 300, 0, 'el comentario')
        tid = c.execute('INSERT INTO pending_tracking(key,module,kind,assignee_id,until,body,user_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
                        (item['entity'], item['module'], 'asignacion', new, '', body, user['id'], stamp)).lastrowid
        if audit:
            audit(c, user['id'], 'pending_assign', tid)
        return {'ok': True, 'id': tid, 'entity': item['entity'], 'assignee_id': new, 'name': person['name'] if person else ''}
    pause = next((t for t in reversed(last) if t['kind'] in ('pospuesto', 'reanudado')), None)
    if action == 'postpone':
        if item['priority'] == 'critico':
            raise ActionError('Un fallo crítico no se puede posponer: se mantiene visible hasta que se resuelva.', 409)
        try:
            day = date.fromisoformat(str(data.get('date', '')))
        except ValueError:
            raise ActionError('Indica hasta qué fecha se pospone.', 400, {'date': 'Fecha no válida.'})
        if day <= now.date() or day > now.date() + timedelta(days=90):
            raise ActionError('Pospón desde mañana y como máximo 90 días.', 400, {'date': 'Fuera de rango.'})
        body = _text(data, 'body', 300, 5, 'el motivo')
        if pause and pause['kind'] == 'pospuesto' and pause['until'] == day.isoformat() and pause['body'] == body and pause['user_id'] == user['id']:
            return {'ok': True, 'duplicate': True, 'entity': item['entity'], 'until': day.isoformat()}
        tid = c.execute('INSERT INTO pending_tracking(key,module,kind,assignee_id,until,body,user_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
                        (item['entity'], item['module'], 'pospuesto', None, day.isoformat(), body, user['id'], stamp)).lastrowid
        if audit:
            audit(c, user['id'], 'pending_postpone', tid)
        return {'ok': True, 'id': tid, 'entity': item['entity'], 'until': day.isoformat()}
    if not item.get('postponed'):
        raise ActionError('Este pendiente no está pospuesto.', 409)
    tid = c.execute('INSERT INTO pending_tracking(key,module,kind,assignee_id,until,body,user_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (item['entity'], item['module'], 'reanudado', None, '', '', user['id'], stamp)).lastrowid
    if audit:
        audit(c, user['id'], 'pending_resume', tid)
    return {'ok': True, 'id': tid, 'entity': item['entity']}


def save_rules(c, user, data, audit=None):
    """Reglas de vencimiento y urgencia (solo administración). Valida cada valor en su rango y la coherencia entre umbrales."""
    if user['role'] != 'administrador':
        raise ActionError('Solo administración cambia las reglas de urgencia.', 403)
    import json
    if data.get('reset') is True:
        clean = {key: spec[0] for key, spec in pending_center.RULES.items()}
    else:
        clean, fields = {}, {}
        for key, (default, low, high, label) in pending_center.RULES.items():
            raw = str(data.get(key, default)).strip()
            if not raw.isdigit() or not low <= int(raw) <= high:
                fields[key] = 'Entre %d y %d.' % (low, high)
                continue
            clean[key] = int(raw)
        if fields:
            raise ActionError('Revisa los valores marcados.', 400, fields)
        for urgent, important in pending_center.RULE_PAIRS:
            if clean[important] < clean[urgent]:
                raise ActionError('El umbral de prioridad media no puede ser menor que el de prioridad alta.', 400, {important: 'Debe ser mayor o igual.'})
    c.execute("INSERT INTO system_state(key,value) VALUES ('pending_rules',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(clean),))
    if audit:
        audit(c, user['id'], 'pending_rules_updated', None)
    return {'ok': True, 'rules': pending_center.rules(c)}


def _diagnosis(c, user, now, data, admin, audit):
    """Diagnóstico de la orden (hallazgos y recomendaciones) desde el panel. Mismo permiso que «Editar orden» (administración), mismos
    límites de texto y control de revisión; solo cambia esos dos campos (nunca importes, estado ni presupuesto) y queda en el historial."""
    if not admin:
        raise ActionError('Solo administración registra el diagnóstico de la orden (igual que en «Editar orden»).', 403)
    oid = str(data.get('order_id', ''))
    row = c.execute("SELECT id,status,revision,COALESCE(findings,'') findings,COALESCE(recommendations,'') recommendations FROM orders WHERE id=?",
                    (int(oid),)).fetchone() if oid.isdigit() else None
    if not row:
        raise ActionError('Orden no disponible.', 404)
    if row['status'] == 'entregado':
        raise ActionError('La orden ya fue entregada: el diagnóstico se corrige desde la orden.', 409)
    if str(data.get('revision', '')) != str(row['revision']):
        raise ActionError('Otra persona actualizó esta orden. Se recargaron los datos: revisa y vuelve a intentarlo.', 409)
    findings = _text(data, 'findings', 4000, 0, 'el diagnóstico')
    recommendations = _text(data, 'recommendations', 4000, 0, 'las recomendaciones')
    if not findings:
        raise ActionError('Escribe el diagnóstico.', 400, {'findings': 'Obligatorio.'})
    if findings == row['findings'] and recommendations == row['recommendations']:
        return {'ok': True, 'unchanged': True}
    changed = c.execute('UPDATE orders SET findings=?,recommendations=?,updated_at=?,revision=revision+1 WHERE id=? AND revision=?',
                        (findings, recommendations, now.isoformat(timespec='microseconds'), row['id'], row['revision'])).rowcount
    if changed != 1:
        raise ActionError('Otra persona actualizó esta orden. Se recargaron los datos: revisa y vuelve a intentarlo.', 409)
    import order_workspace
    order_workspace.event(c, row['id'], user['id'], now, 'updated', 'Diagnóstico actualizado desde el Centro de Control: ' + findings[:300] + ('…' if len(findings) > 300 else ''))
    if audit:
        audit(c, user['id'], 'order_workspace_updated', row['id'])
    return {'ok': True, 'revision': row['revision'] + 1}
