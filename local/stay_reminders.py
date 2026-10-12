"""Avisos por correo al cliente sobre la permanencia de su equipo en el taller.

Apagados hasta que administración los activa. Se envía un aviso por orden y etapa (por defecto a los 60, 75, 85 y 90
días del ingreso), nunca repetido, y se suspenden en cuanto la orden queda entregada. El texto es informativo: invita a
coordinar el retiro y no anuncia cargos, sanciones ni decisiones sobre el equipo. «sent» significa que el servidor de
correo aceptó el mensaje."""
import re
from datetime import datetime

import stay
from reception import ECUADOR_TZ

BATCH = 3
MAIL = re.compile(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+')


def stage_for(days, config):
    """Etapa que corresponde hoy: la última ya alcanzada. Antes del primer aviso no hay etapa."""
    reached = [day for day in config['mail_days'] if days >= day]
    return max(reached) if reached else None


def pending(c, now, config):
    out = []
    rows = c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status,o.created_at,o.received_at,o.delivered_at,d.brand,d.model,cl.name client,cl.email "
                     "FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.status!='entregado' ORDER BY o.id").fetchall()
    for row in rows:
        item = dict(row)
        info = stay.compute(item, now, config)
        stage = stage_for(info['days'], config) if info else None
        if stage is None or not MAIL.fullmatch((item['email'] or '').strip()):
            continue
        # Con un aviso de esta etapa o de una posterior ya registrado no se envía nada: nunca se repite ni se retrocede.
        if c.execute('SELECT 1 FROM stay_reminders WHERE order_id=? AND stage>=?', (item['id'], stage)).fetchone():
            continue
        out.append((item, info, stage))
    return out


def message_for(item, info, config):
    device = ' '.join(part for part in (item.get('brand') or '', item.get('model') or '') if part) or 'su equipo'
    since = datetime.fromisoformat(info['started_at']).strftime('%d/%m/%Y')
    lines = ['Estimado/a ' + item['client'] + ':', '',
             'Le recordamos que ' + device + ', registrado con la orden ' + item['code'] + ', se encuentra en nuestro taller desde el ' + since + ' (' + str(info['days']) + ' días).']
    if info['days'] >= config['limit']:
        lines.append('El equipo ha cumplido el plazo de permanencia de %d días. Le pedimos comunicarse con nosotros para coordinar su retiro o conocer el estado del servicio.' % config['limit'])
    else:
        lines.append('Le agradecemos comunicarse con nosotros para coordinar su retiro o conocer el estado del servicio. El plazo de permanencia es de %d días desde el ingreso.' % config['limit'])
    lines += ['', 'Si ya coordinó el retiro o el equipo continúa en reparación por indicación del taller, puede ignorar este mensaje.', '', 'Atentamente,', '',
              'Departamento de Servicio Técnico', 'PC-DOCTOR S.A.']
    return 'PC-DOCTOR S.A. | Aviso de permanencia de su equipo — Orden N.º ' + item['code'], '\n'.join(lines)


def run(c, now, deliver, limit=BATCH):
    """Envía hasta «limit» avisos pendientes. «deliver(destinatario, asunto, cuerpo)» devuelve el identificador del mensaje o lanza una excepción."""
    config = stay.settings(c)
    summary = {'sent': 0, 'failed': 0, 'left': 0}
    todo = pending(c, now, config)
    summary['left'] = max(0, len(todo) - limit)
    for item, info, stage in todo[:limit]:
        email = item['email'].strip()
        reserved = c.execute("INSERT OR IGNORE INTO stay_reminders(order_id,stage,recipient,result,created_at) VALUES (?,?,?,'processing',?)", (item['id'], stage, email, now.isoformat(timespec='seconds')))
        if reserved.rowcount != 1:
            continue
        # El envío espera al servidor de correo: la reserva se confirma antes para no retener la base.
        c.commit()
        subject, body = message_for(item, info, config)
        try:
            message_id = deliver(email, subject, body) or ''
            result, detail = 'sent', 'El servidor de correo aceptó el mensaje.'
            summary['sent'] += 1
        except Exception as error:
            message_id, result, detail = '', 'failed', str(error)[:200]
            summary['failed'] += 1
        c.execute('UPDATE stay_reminders SET result=?,detail=?,message_id=? WHERE order_id=? AND stage=?', (result, detail, str(message_id)[:300], item['id'], stage))
        if result == 'sent':
            from order_workspace import event
            event(c, item['id'], None, now, 'follow_up', 'Aviso de permanencia enviado al cliente por correo (día %d del plazo de %d).' % (stage, config['limit']))
        c.commit()
    return summary


def for_order(c, order_id):
    return [dict(row) for row in c.execute('SELECT stage,recipient,result,message_id,detail,created_at FROM stay_reminders WHERE order_id=? ORDER BY stage', (order_id,))]


def status(c, now):
    config = stay.settings(c)
    todo = pending(c, now, config)
    recent = c.execute("SELECT r.stage,r.recipient,r.result,r.created_at,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code FROM stay_reminders r JOIN orders o ON o.id=r.order_id ORDER BY r.id DESC LIMIT 6").fetchall()
    return {'enabled': bool(config['mail']), 'days': config['mail_days'], 'pending_total': len(todo),
            'pending': [{'code': item['code'], 'client': item['client'], 'stage': stage, 'days': info['days']} for item, info, stage in todo[:20]], 'recent': [dict(row) for row in recent]}
