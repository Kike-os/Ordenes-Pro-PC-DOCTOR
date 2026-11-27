"""Prórrogas del plazo de retiro (1.5.294): días adicionales para que el cliente retire su equipo, sobre la permanencia en taller.

Reglas:
- El plazo original es la fecha de ingreso (America/Guayaquil) más el plazo administrativo configurado (stay.settings()['limit']).
  El plazo vigente es el de la última prórroga vigente; el día límite cuenta completo (vence al terminar ese día en Ecuador).
- Otorgar: 3, 7, 15 o 30 días, o una fecha personalizada. Se suma sobre el plazo vigente o, si ya venció, sobre hoy: nunca queda una
  fecha ya pasada. Máximo 365 días por prórroga. La nueva queda «vigente» y la anterior pasa a «reemplazada» (nada se sobrescribe).
- Revocar devuelve el plazo a la prórroga o al plazo anterior; queda con su motivo.
- Solo administración otorga, reemplaza o revoca. No en órdenes entregadas (el único estado final del sistema).
- Control de concurrencia: la petición trae el plazo vigente que vio la persona; si cambió mientras tanto, 409. La misma prórroga
  repetida en 2 minutos (doble clic o reintento) no se duplica.
- No cambia el estado operativo de la orden, su número, firmas, documentos ni presupuestos, y no toca ningún cobro: el sistema no calcula
  bodegaje; el almacenaje se rige por las condiciones aceptadas.
- Avisos: interno (historial de la orden → notificaciones del equipo) y al cliente por los canales habilitados (correo del sistema y
  WhatsApp Business con su consentimiento y plantilla), con resultado registrado y reintento seguro. Recordatorios antes del nuevo plazo,
  configurables y desactivados por defecto.
"""
import json
import re
from datetime import date, datetime, timedelta

import stay
from reception import ECUADOR_TZ

PRESETS = (3, 7, 15, 30)
MAX_DAYS = 365
REASONS = {'cliente_solicita': 'El cliente solicitó más tiempo', 'espera_pago': 'Coordinación del pago', 'viaje_cliente': 'El cliente está fuera de la ciudad',
           'espera_repuesto': 'Espera de un repuesto o accesorio', 'coordinacion_retiro': 'Coordinación del retiro', 'otro': 'Otro motivo'}
STATUS = {'vigente': 'Vigente', 'reemplazada': 'Reemplazada por otra prórroga', 'revocada': 'Revocada'}
DEFAULTS = {'reminders': False, 'reminder_days': [3, 1], 'notify_client': True}
MAIL = re.compile(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+')


class ExtensionError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def ready(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_extensions'").fetchone() is not None


def settings(c):
    row = c.execute("SELECT value FROM system_state WHERE key='extension_settings'").fetchone()
    out = dict(DEFAULTS)
    try:
        stored = json.loads(row[0]) if row else {}
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        if stored.get('reminders') in (True, False):
            out['reminders'] = stored['reminders']
        if stored.get('notify_client') in (True, False):
            out['notify_client'] = stored['notify_client']
        days = stored.get('reminder_days')
        if isinstance(days, list) and days and all(isinstance(d, int) and 1 <= d <= 30 for d in days):
            out['reminder_days'] = sorted(set(days), reverse=True)[:4]
    return out


def save_settings(c, data):
    days = sorted({int(x) for x in re.split(r'[,; ]+', str(data.get('reminder_days', ''))) if x.strip().isdigit()}, reverse=True)
    if not days or len(days) > 4 or any(d < 1 or d > 30 for d in days):
        raise ExtensionError('Indica de 1 a 4 recordatorios entre 1 y 30 días antes del nuevo plazo (por ejemplo: 3, 1).', fields={'reminder_days': 'No válido.'})
    value = {'reminders': data.get('reminders') is True, 'notify_client': data.get('notify_client') is not False, 'reminder_days': days}
    c.execute("INSERT INTO system_state(key,value) VALUES ('extension_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(value),))
    return settings(c)


def today(now):
    return now.astimezone(ECUADOR_TZ).date()


def original_due(order, config):
    """Fecha límite original: día de ingreso en Ecuador + plazo administrativo (días naturales)."""
    start = stay._moment(order.get('received_at')) or stay._moment(order.get('created_at'))
    return (start.date() + timedelta(days=config['limit'])) if start else None


def live(c, order_id):
    if not ready(c):
        return None
    row = c.execute("SELECT * FROM order_extensions WHERE order_id=? AND status='vigente' ORDER BY id DESC LIMIT 1", (order_id,)).fetchone()
    return dict(row) if row else None


def live_map(c):
    """{order_id: nueva fecha} de las prórrogas vigentes (una consulta, para listados e indicadores)."""
    if not ready(c):
        return {}
    return {r[0]: r[1] for r in c.execute("SELECT order_id,new_due FROM order_extensions WHERE status='vigente'")}


def history(c, order_id):
    if not ready(c):
        return []
    rows = [dict(r, status_label=STATUS[r['status']], reason_label=REASONS[r['reason_code']]) for r in c.execute(
        "SELECT x.*,COALESCE(u.name,'') created_name,COALESCE(v.name,'') closed_name FROM order_extensions x LEFT JOIN users u ON u.id=x.created_by "
        "LEFT JOIN users v ON v.id=x.closed_by WHERE x.order_id=? ORDER BY x.id DESC", (order_id,))]
    notices = {}
    for n in c.execute('SELECT * FROM order_extension_notices WHERE order_id=? ORDER BY id', (order_id,)):
        notices.setdefault(n['extension_id'], []).append(dict(n))
    for r in rows:
        r['notices'] = notices.get(r['id'], [])
    return rows


def _order(c, order_id):
    row = c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status,o.created_at,o.received_at,o.delivered_at,d.brand,d.model,cl.name client,cl.id client_id,"
                    "COALESCE(cl.email,'') email,COALESCE(cl.phone,'') phone FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?",
                    (order_id,)).fetchone()
    return dict(row) if row else None


def state(c, order_id, now):
    """Plazo de retiro de la orden: original, vigente, prórroga vigente, si es elegible y por qué no."""
    order = _order(c, order_id)
    if not order:
        raise ExtensionError('Orden no disponible.', 404)
    config = stay.settings(c)
    first = original_due(order, config)
    current = live(c, order_id)
    due = date.fromisoformat(current['new_due']) if current else first
    t = today(now)
    reason = ''
    if not ready(c):
        reason = 'Esta función necesita una actualización de la base de datos que todavía no se aplicó.'
    elif order['status'] == 'entregado':
        reason = 'La orden ya fue entregada: no admite prórroga del plazo de retiro.'
    elif not first:
        reason = 'La orden no tiene fecha de ingreso registrada.'
    base = max(due, t) if due else t
    return {'order_id': order_id, 'code': order['code'], 'original_due': first.isoformat() if first else '', 'due': due.isoformat() if due else '',
            'base': base.isoformat(), 'days_left': (due - t).days if due else None, 'overdue': bool(due and t > due), 'extension': current,
            'eligible': not reason, 'reason': reason, 'presets': PRESETS, 'max_days': MAX_DAYS, 'reasons': REASONS, 'today': t.isoformat(),
            'channels': channels(c, order), 'settings': settings(c) if ready(c) else DEFAULTS}


def channels(c, order):
    """Canales por los que hoy se puede avisar al cliente (sin enviar nada): correo del sistema y WhatsApp Business."""
    out = []
    try:
        import mail_pro
        mail_ok = mail_pro.configured()
    except Exception:
        mail_ok = False
    out.append({'channel': 'correo', 'ok': bool(mail_ok and MAIL.fullmatch(order['email'].strip())),
                'why': '' if mail_ok and MAIL.fullmatch(order['email'].strip()) else 'El correo del sistema no está configurado.' if not mail_ok else 'El cliente no tiene un correo válido.'})
    try:
        import whatsapp_business as wa
        cfg = wa.settings(c)
        number = wa.number_for(order['phone'])
        consent = wa.consent_state(c, number, client_id=order['client_id'], scoped=True)['state'] if number else ''
        ok = wa.ready() and bool(number) and consent == 'aceptado'
        why = '' if ok else 'WhatsApp Business no está configurado.' if not wa.ready() else 'El cliente no tiene un celular válido.' if not number else 'El cliente no autorizó avisos por WhatsApp.'
    except Exception:
        ok, why = False, 'WhatsApp Business no está disponible.'
    out.append({'channel': 'whatsapp', 'ok': ok, 'why': why})
    return out


def _clean(data, key, limit, minimum=0, label='el texto'):
    value = re.sub(r'[ \t]+', ' ', str(data.get(key, '') or '')).strip()
    if len(value) > limit or len(value) < minimum:
        raise ExtensionError('Indica %s (%d a %d caracteres).' % (label, minimum, limit) if minimum else 'Indica %s en %d caracteres como máximo.' % (label, limit), fields={key: 'No válido.'})
    return value


def grant(c, order_id, data, user, now):
    """Otorga (o reemplaza) la prórroga. Devuelve la prórroga creada. Las escrituras quedan en la transacción de la petición."""
    if user['role'] != 'administrador':
        raise ExtensionError('Solo administración autoriza prórrogas del plazo de retiro.', 403)
    info = state(c, order_id, now)
    if not info['eligible']:
        raise ExtensionError(info['reason'], 409)
    if str(data.get('expected_due', '')) != info['due']:
        raise ExtensionError('El plazo de esta orden cambió mientras tanto (otra persona otorgó o revocó una prórroga). Se recargaron los datos: revisa y vuelve a intentarlo.', 409)
    base = date.fromisoformat(info['base'])
    raw_days, raw_date = str(data.get('days', '') or '').strip(), str(data.get('date', '') or '').strip()
    if raw_date:
        try:
            new_due = date.fromisoformat(raw_date)
        except ValueError:
            raise ExtensionError('Indica una fecha válida.', fields={'date': 'Fecha no válida.'})
        if new_due <= base:
            raise ExtensionError('La nueva fecha debe ser posterior al %s.' % base.strftime('%d/%m/%Y'), fields={'date': 'Debe ser posterior.'})
    elif raw_days.isdigit() and int(raw_days) in PRESETS:
        new_due = base + timedelta(days=int(raw_days))
    else:
        raise ExtensionError('Elige 3, 7, 15 o 30 días, o una fecha personalizada.', fields={'days': 'No válido.'})
    days = (new_due - base).days
    if days > MAX_DAYS:
        raise ExtensionError('Una prórroga puede ser de hasta %d días.' % MAX_DAYS, fields={'date': 'Demasiado lejana.'})
    reason_code = str(data.get('reason_code', ''))
    if reason_code not in REASONS:
        raise ExtensionError('Elige el motivo de la prórroga.', fields={'reason_code': 'Obligatorio.'})
    reason = _clean(data, 'reason', 300, 5 if reason_code == 'otro' else 0, 'el motivo')
    notes = _clean(data, 'notes', 1000, 0, 'las observaciones')
    authorized_by = _clean(data, 'authorized_by', 120, 3, 'quién autoriza la prórroga') or user['name']
    stamp = now.isoformat(timespec='seconds')
    current = info['extension']
    if current and current['new_due'] == new_due.isoformat() and current['created_by'] == user['id'] and current['created_at'] >= (now - timedelta(minutes=2)).isoformat(timespec='seconds'):
        return dict(current, duplicate=True)
    if current and c.execute("UPDATE order_extensions SET status='reemplazada',closed_by=?,closed_at=?,close_reason=? WHERE id=? AND status='vigente'",
                             (user['id'], stamp, 'Reemplazada por una nueva prórroga hasta el ' + new_due.isoformat(), current['id'])).rowcount != 1:
        raise ExtensionError('Otra persona cambió la prórroga de esta orden mientras tanto. Vuelve a intentarlo.', 409)
    new_id = c.execute('INSERT INTO order_extensions(order_id,original_due,previous_due,new_due,days,reason_code,reason,notes,authorized_by,status,created_by,created_at) '
                       "VALUES (?,?,?,?,?,?,?,?,?,'vigente',?,?)", (order_id, info['original_due'], info['due'], new_due.isoformat(), days, reason_code, reason, notes,
                                                                    authorized_by, user['id'], stamp)).lastrowid
    # Aviso interno: queda en el historial de la orden y aparece en las notificaciones del resto del equipo.
    import order_workspace
    order_workspace.event(c, order_id, user['id'], now, 'follow_up', 'Prórroga del plazo de retiro otorgada: %s → %s (%d día%s). Motivo: %s%s. Autoriza: %s.' % (
        _fmt(info['due']), _fmt(new_due.isoformat()), days, '' if days == 1 else 's', REASONS[reason_code], ' — ' + reason if reason else '', authorized_by))
    return dict(c.execute('SELECT * FROM order_extensions WHERE id=?', (new_id,)).fetchone(), duplicate=False)


def revoke(c, order_id, data, user, now):
    if user['role'] != 'administrador':
        raise ExtensionError('Solo administración revoca prórrogas.', 403)
    if not ready(c):
        raise ExtensionError('Esta función necesita una actualización de la base de datos que todavía no se aplicó.', 503)
    current = live(c, order_id)
    raw = str(data.get('extension', '') or '')
    if not current or not raw.isdigit() or int(raw) != current['id']:
        raise ExtensionError('Esa prórroga ya no está vigente (pudo cambiar mientras tanto). Se recargaron los datos.', 409)
    reason = _clean(data, 'reason', 300, 5, 'el motivo de la revocación')
    stamp = now.isoformat(timespec='seconds')
    if c.execute("UPDATE order_extensions SET status='revocada',closed_by=?,closed_at=?,close_reason=? WHERE id=? AND status='vigente'", (user['id'], stamp, reason, current['id'])).rowcount != 1:
        raise ExtensionError('Otra persona cambió la prórroga mientras tanto. Vuelve a intentarlo.', 409)
    # Vuelve a quedar vigente la prórroga anterior que esta reemplazó (si existía); si no, rige el plazo original.
    previous = c.execute("SELECT id FROM order_extensions WHERE order_id=? AND id<? AND status='reemplazada' AND new_due=? ORDER BY id DESC LIMIT 1",
                         (order_id, current['id'], current['previous_due'])).fetchone()
    restored = ''
    if previous:
        # Restituir no se permite sobre una fila cerrada (protección de la tabla): se crea una nueva fila vigente con el plazo anterior.
        old = c.execute('SELECT * FROM order_extensions WHERE id=?', (previous['id'],)).fetchone()
        c.execute('INSERT INTO order_extensions(order_id,original_due,previous_due,new_due,days,reason_code,reason,notes,authorized_by,status,created_by,created_at) '
                  "VALUES (?,?,?,?,?,?,?,?,?,'vigente',?,?)", (order_id, old['original_due'], old['previous_due'], old['new_due'], old['days'], old['reason_code'],
                                                               old['reason'], 'Restituida al revocar la prórroga posterior.', old['authorized_by'], user['id'], stamp))
        restored = old['new_due']
    import order_workspace
    order_workspace.event(c, order_id, user['id'], now, 'follow_up', 'Prórroga del plazo de retiro revocada (%s). Plazo vigente: %s. Motivo: %s.' % (
        _fmt(current['new_due']), _fmt(restored or current['original_due']), reason))
    return {'ok': True, 'due': restored or current['original_due']}


def _fmt(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return str(value)


# ---- Avisos al cliente ----
def message(order, ext, kind='otorgada', stage=0):
    device = ' '.join(x for x in (order.get('brand') or '', order.get('model') or '') if x) or 'su equipo'
    when = _fmt(ext['new_due'])
    if kind == 'otorgada':
        lines = ['Estimado/a ' + order['client'] + ':', '', 'Le informamos que ampliamos el plazo para retirar ' + device + ', registrado con la orden ' + order['code'] +
                 '. El nuevo plazo es hasta el ' + when + ' (inclusive).', '', 'Si ya coordinó el retiro, puede ignorar este mensaje.']
        subject = 'PC-DOCTOR S.A. | Prórroga del plazo de retiro — Orden N.º ' + order['code']
    else:
        lines = ['Estimado/a ' + order['client'] + ':', '', 'Le recordamos que el plazo ampliado para retirar ' + device + ' (orden ' + order['code'] + ') vence el ' + when +
                 ('' if stage <= 0 else ' (en %d día%s)' % (stage, '' if stage == 1 else 's')) + '.', '', 'Le agradecemos comunicarse con nosotros para coordinar el retiro.']
        subject = 'PC-DOCTOR S.A. | Recordatorio del plazo de retiro — Orden N.º ' + order['code']
    lines += ['', 'Atentamente,', '', 'Departamento de Servicio Técnico', 'PC-DOCTOR S.A.']
    return subject, '\n'.join(lines)


def queue_notices(c, ext, now, notify_client=True, kind='otorgada', stage=0, channels_=('correo', 'whatsapp')):
    """Registra los avisos al cliente (uno por canal; la restricción UNIQUE impide duplicarlos). Correo: queda «pendiente» para enviarse
    después de confirmar la transacción. WhatsApp: entra en la cola de WhatsApp Business con sus propias reglas (consentimiento, plantilla)."""
    order = _order(c, ext['order_id'])
    stamp = now.isoformat(timespec='seconds')
    ids = []
    for ch in channels(c, order):
        if ch['channel'] not in channels_:
            continue
        status, detail, ref, recipient = ('pendiente', '', '', order['email']) if ch['channel'] == 'correo' else ('en_cola', '', '', order['phone'])
        if not notify_client:
            status, detail = 'omitido', 'Se otorgó sin avisar al cliente.'
        elif not ch['ok']:
            status, detail = 'omitido', ch['why']
        elif ch['channel'] == 'whatsapp':
            import whatsapp_business as wa
            try:
                nid = wa.enqueue(c, 'prorroga_retiro', 'prorroga:%d:%s:%d' % (ext['id'], kind, stage), now, order_id=ext['order_id'], source='prorroga', manual=False)
            except Exception as error:
                nid, detail = None, str(error)[:200]
            ref = str(nid or '')
            if not nid:
                status, detail = 'omitido', detail or 'WhatsApp Business no lo encoló (envíos automáticos desactivados, aviso desactivado o ya enviado).'
        cur = c.execute('INSERT OR IGNORE INTO order_extension_notices(extension_id,order_id,kind,stage,channel,recipient,status,detail,message_ref,created_at,updated_at) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?,?)', (ext['id'], ext['order_id'], kind, stage, ch['channel'], recipient, status, detail, ref, stamp, stamp))
        if cur.rowcount and status == 'pendiente':
            ids.append(cur.lastrowid)
    return ids


def send_mail(c, notice_id, now, deliver):
    """Envía un aviso por correo una sola vez: lo «toma» (pendiente → enviando) antes de enviar; otra petición simultánea no lo repite.
    deliver(destinatario, asunto, cuerpo, order_id) devuelve el identificador del mensaje o lanza una excepción."""
    stamp = now.isoformat(timespec='seconds')
    if c.execute("UPDATE order_extension_notices SET status='enviando',attempts=attempts+1,updated_at=? WHERE id=? AND channel='correo' AND status='pendiente'",
                 (stamp, notice_id)).rowcount != 1:
        return None
    c.commit()
    row = dict(c.execute('SELECT * FROM order_extension_notices WHERE id=?', (notice_id,)).fetchone())
    ext = dict(c.execute('SELECT * FROM order_extensions WHERE id=?', (row['extension_id'],)).fetchone())
    order = _order(c, row['order_id'])
    subject, body = message(order, ext, row['kind'], row['stage'])
    try:
        ref = deliver(row['recipient'], subject, body, row['order_id'])
        c.execute("UPDATE order_extension_notices SET status='enviado',detail='',message_ref=?,updated_at=? WHERE id=?", (str(ref or '')[:200], now.isoformat(timespec='seconds'), notice_id))
        result = 'enviado'
    except Exception as error:
        c.execute("UPDATE order_extension_notices SET status='error',detail=?,updated_at=? WHERE id=?", (('No se pudo enviar: ' + str(error))[:300], now.isoformat(timespec='seconds'), notice_id))
        result = 'error'
    c.commit()
    return result


def retry(c, order_id, data, user, now, deliver):
    """Reintento seguro de un aviso por correo fallido (hasta 5 intentos); nunca reenvía uno ya enviado ni uno en curso."""
    if user['role'] != 'administrador':
        raise ExtensionError('Solo administración reintenta avisos.', 403)
    raw = str(data.get('notice', '') or '')
    row = c.execute("SELECT * FROM order_extension_notices WHERE id=? AND order_id=?", (int(raw), order_id)).fetchone() if raw.isdigit() else None
    if not row:
        raise ExtensionError('Aviso no encontrado.', 404)
    if row['channel'] != 'correo':
        raise ExtensionError('Los avisos por WhatsApp se reintentan desde la cola de WhatsApp Business.', 409)
    if row['status'] != 'error':
        raise ExtensionError('Este aviso no está en error (ya se envió o está en curso): no se repite.', 409)
    if row['attempts'] >= 5:
        raise ExtensionError('Se alcanzó el máximo de 5 intentos para este aviso.', 409)
    c.execute("UPDATE order_extension_notices SET status='pendiente',updated_at=? WHERE id=? AND status='error'", (now.isoformat(timespec='seconds'), row['id']))
    c.commit()
    return {'ok': True, 'result': send_mail(c, row['id'], now, deliver)}


def plan_reminders(c, now):
    """Recordatorios antes del nuevo plazo (si están activados): uno por prórroga y anticipación; nunca se repiten ni retroceden."""
    config = settings(c)
    if not ready(c) or not config['reminders']:
        return []
    t = today(now)
    out = []
    for ext in c.execute("SELECT x.* FROM order_extensions x JOIN orders o ON o.id=x.order_id WHERE x.status='vigente' AND o.status!='entregado'").fetchall():
        left = (date.fromisoformat(ext['new_due']) - t).days
        stage = next((d for d in sorted(config['reminder_days']) if 0 <= left <= d), None)
        if stage is None:
            continue
        if c.execute("SELECT 1 FROM order_extension_notices WHERE extension_id=? AND kind='recordatorio' AND stage<=?", (ext['id'], stage)).fetchone():
            continue
        out += queue_notices(c, dict(ext), now, True, 'recordatorio', stage, ('correo',))
    return out


def pending_items(c, now):
    """Para el Centro de Control: prórrogas vigentes que vencen en los próximos días o ya vencieron sin retiro."""
    if not ready(c):
        return []
    t = today(now)
    window = max(settings(c)['reminder_days'] + [3])
    out = []
    for r in c.execute("SELECT x.id,x.order_id,x.new_due,x.days,x.authorized_by,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.assigned_to,cl.name client,COALESCE(u.name,'') tech "
                       "FROM order_extensions x JOIN orders o ON o.id=x.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id "
                       "LEFT JOIN users u ON u.id=o.assigned_to WHERE x.status='vigente' AND o.status!='entregado'"):
        left = (date.fromisoformat(r['new_due']) - t).days
        if left > window:
            continue
        out.append(dict(r, left=left))
    return out
