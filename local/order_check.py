"""Consulta pública del estado de una reparación con verificación de identidad.

Conocer el número de orden no basta: el sistema envía un código temporal de seis dígitos al correo registrado en la orden
y solo quien lo recibe puede ver el estado. La respuesta al pedir el código es siempre la misma, exista o no la orden, y
no revela el correo. Tras verificar se muestran únicamente el estado y el equipo: ningún dato personal."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta

from reception import DEVICE_TYPES, ECUADOR_TZ

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
ORDER_CODE = re.compile(r'[A-Z]{2,4}-\d{4,8}(?:-\d{3,6})?')
MAIL = re.compile(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+')
NOTICE = 'Si el número corresponde a una orden con correo registrado, acabamos de enviar un código de 6 dígitos a ese correo. Caduca en %d minutos.' % CODE_MINUTES


def _hash(*parts):
    return hashlib.sha256('\x1f'.join(parts).encode()).hexdigest()


def start(c, order_code, now):
    """Crea el reto y devuelve (token, datos del correo pendiente o None). El token se entrega siempre, exista o no la orden."""
    c.execute('DELETE FROM order_checks WHERE expires_at<?', ((now - timedelta(days=1)).isoformat(timespec='seconds'),))
    token, code = secrets.token_urlsafe(24), '%06d' % secrets.randbelow(1000000)
    wanted = re.sub(r'\s+', '', str(order_code or '')).upper()
    row = c.execute("SELECT o.id,o.code,cl.name,cl.email FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE UPPER(o.code)=?", (wanted,)).fetchone() if ORDER_CODE.fullmatch(wanted) else None
    email = (row['email'] or '').strip() if row else ''
    real = bool(row and MAIL.fullmatch(email))
    c.execute('INSERT INTO order_checks(token_hash,order_id,code_hash,expires_at,created_at) VALUES (?,?,?,?,?)',
              (_hash(token), row['id'] if real else None, _hash(token, code) if real else '', (now + timedelta(minutes=CODE_MINUTES)).isoformat(timespec='seconds'), now.isoformat(timespec='seconds')))
    if not real:
        return token, None
    return token, {'email': email, 'code': code, 'order': row['code'], 'order_id': row['id']}


def verify(c, token, code, now):
    """Estado de la orden si el código es correcto; None en cualquier otro caso (sin distinguir el motivo)."""
    row = c.execute('SELECT * FROM order_checks WHERE token_hash=?', (_hash(str(token or '')),)).fetchone()
    if not row or row['verified_at'] or row['attempts'] >= MAX_ATTEMPTS or row['expires_at'] < now.isoformat(timespec='seconds'):
        return None
    c.execute('UPDATE order_checks SET attempts=attempts+1 WHERE id=?', (row['id'],))
    if not row['order_id'] or not re.fullmatch(r'\d{6}', str(code or '')) or not secrets.compare_digest(row['code_hash'], _hash(str(token), str(code))):
        return None
    c.execute('UPDATE order_checks SET verified_at=? WHERE id=?', (now.isoformat(timespec='seconds'), row['id']))
    order = c.execute("SELECT o.id,o.code,o.status,s.label status_label,o.received_at,o.created_at,o.estimated_delivery,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model "
                      "FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id WHERE o.id=?", (row['order_id'],)).fetchone()
    if not order:
        return None
    import order_tracking
    link = order_tracking.active(c, order['id'])
    received = ''
    try:
        moment = datetime.fromisoformat(order['received_at']) if order['received_at'] else datetime.fromtimestamp(order['created_at'], ECUADOR_TZ)
        received = moment.astimezone(ECUADOR_TZ).strftime('%d/%m/%Y')
    except (TypeError, ValueError, OSError):
        pass
    estimated = ''
    try:
        estimated = datetime.fromisoformat(order['estimated_delivery']).strftime('%d/%m/%Y') if order['estimated_delivery'] and order['status'] != 'entregado' else ''
    except ValueError:
        pass
    device = ' '.join(part for part in (DEVICE_TYPES.get(order['type'], ''), order['brand'] or '', order['model'] or '') if part)
    return {'id': order['id'], 'code': order['code'], 'status': order['status_label'], 'status_code': order['status'], 'device': device, 'received': received, 'estimated': estimated, 'tracking_url': link['url'] if link['active'] else ''}
