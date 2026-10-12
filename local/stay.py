"""Permanencia de cada equipo en el taller: tiempo desde el ingreso hasta la entrega, frente a un plazo administrativo.

Se calcula siempre con las fechas guardadas en el servidor (ingreso y entrega) en America/Guayaquil; no hay contadores que
se puedan desajustar. El plazo y los tramos de aviso son configurables. Superar el plazo solo genera avisos: ningún estado
cambia por sí solo y no se dispone del equipo automáticamente."""
import json
from datetime import datetime

from reception import ECUADOR_TZ

DEFAULTS = {'limit': 90, 'notice': 60, 'near': 75, 'mail_days': [60, 75, 85, 90], 'mail': False}
LEVELS = {'ok': 'Dentro del plazo', 'notice': 'Recordatorio preventivo', 'near': 'Próximo al vencimiento', 'overdue': 'Plazo administrativo vencido'}


def settings(c):
    row = c.execute("SELECT value FROM system_state WHERE key='stay_settings'").fetchone()
    data = dict(DEFAULTS)
    if row:
        try:
            data.update({key: value for key, value in json.loads(row['value']).items() if key in DEFAULTS})
        except ValueError:
            pass
    return data


def validate(data, current):
    """Ajustes válidos: plazo de 15 a 730 días y tramos crecientes por debajo del plazo."""
    try:
        limit, notice, near = int(data.get('limit', current['limit'])), int(data.get('notice', current['notice'])), int(data.get('near', current['near']))
    except (TypeError, ValueError):
        return None, 'Indica días en números enteros.'
    if not 15 <= limit <= 730:
        return None, 'El plazo debe estar entre 15 y 730 días.'
    if not 1 <= notice < near < limit:
        return None, 'Los avisos deben ser crecientes y anteriores al plazo.'
    mail_days = sorted({day for day in (notice, near, max(near + 1, limit - 5), limit) if day <= limit})
    mail = data.get('mail') if data.get('mail') in (True, False) else current['mail']
    return {'limit': limit, 'notice': notice, 'near': near, 'mail_days': mail_days, 'mail': mail}, ''


def save(c, values):
    c.execute("INSERT INTO system_state(key,value) VALUES ('stay_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(values),))


def _moment(value):
    if value in (None, ''):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, ECUADOR_TZ)
        moment = datetime.fromisoformat(str(value))
        return moment.astimezone(ECUADOR_TZ) if moment.tzinfo else moment.replace(tzinfo=ECUADOR_TZ)
    except (ValueError, OverflowError, OSError):
        return None


def level_for(days, config):
    return 'overdue' if days >= config['limit'] else 'near' if days >= config['near'] else 'notice' if days >= config['notice'] else 'ok'


def compute(order, now, config):
    """Permanencia de una orden. «order» necesita received_at o created_at, status y delivered_at."""
    start = _moment(order.get('received_at')) or _moment(order.get('created_at'))
    if not start:
        return None
    delivered = _moment(order.get('delivered_at')) if (order.get('status_code') or order.get('status')) == 'entregado' else None
    end = delivered or now.astimezone(ECUADOR_TZ)
    seconds = max(0, int((end - start).total_seconds()))
    days, hours = seconds // 86400, (seconds % 86400) // 3600
    return {'started_at': start.isoformat(timespec='seconds'), 'ended_at': delivered.isoformat(timespec='seconds') if delivered else '', 'closed': bool(delivered),
            'days': days, 'hours': hours, 'limit': config['limit'], 'remaining': max(0, config['limit'] - days), 'exceeded': max(0, days - config['limit']),
            'percent': min(100, round(seconds * 100 / (config['limit'] * 86400))), 'level': level_for(days, config), 'label': LEVELS[level_for(days, config)], 'thresholds': {'notice': config['notice'], 'near': config['near']}}


def overdue(c, now, config):
    """Órdenes sin entregar que ya superaron el plazo, de la más antigua a la más reciente."""
    out = []
    for row in c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status,o.created_at,o.received_at,o.delivered_at,cl.name client FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.status!='entregado' ORDER BY o.id"):
        item = dict(row)
        info = compute(item, now, config)
        if info and info['level'] == 'overdue':
            out.append(dict(id=item['id'], code=item['code'], client=item['client'], **info))
    return out


def delivery(c, order_id):
    """Quién registró la entrega vigente (último cambio a «Entregado» del historial) y cuándo; vacío si no consta."""
    label = c.execute("SELECT label FROM statuses WHERE code='entregado'").fetchone()
    row = c.execute("SELECT h.occurred_at,COALESCE(u.name,'') actor FROM order_history h LEFT JOIN users u ON u.id=h.actor_id WHERE h.order_id=? AND h.event='status' AND h.status_label=? ORDER BY h.id DESC LIMIT 1", (order_id, label['label'] if label else 'Entregado')).fetchone()
    return {'at': row['occurred_at'], 'by': row['actor']} if row else {'at': '', 'by': ''}


def describe(info):
    """Texto breve de la permanencia para listados, alertas e informes."""
    if not info:
        return 'Sin fecha de ingreso registrada'
    span = '%d día%s' % (info['days'], '' if info['days'] == 1 else 's')
    if info['closed']:
        return 'Entregado tras ' + span + (' (%d sobre el plazo)' % info['exceeded'] if info['exceeded'] else '')
    return span + ' en taller · ' + ('plazo superado por %d' % info['exceeded'] if info['exceeded'] else 'restan %d' % info['remaining'])
