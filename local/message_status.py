"""ADI Smart Message Status · Live Read Receipts 1.0 (docs/LIVE-READ-RECEIPTS.md).

Estados (solo avanzan, nunca retroceden por un evento atrasado o duplicado): enviando → enviado → entregado → leído. «error» solo si el
mensaje no se había entregado ni leído; «reintentando» mientras hay un reintento técnico. Nada de esto reinicia el contador de cierre por
inactividad (Live Support 4.0): las confirmaciones no son actividad conversacional.

Origen de cada confirmación (nunca se simula):
- Mensajes SALIENTES (ADI o asesor) por WhatsApp: eventos firmados de Meta (sent, delivered, read, failed), enlazados por el id del mensaje.
  Si Meta no envía «read» (el cliente desactivó las confirmaciones), se conserva el último estado confirmado.
- SALIENTES por el chat web: «enviado» al guardarse; «entregado» cuando el widget del cliente lo recibe en su consulta; «leído» solo con el
  evento autenticado del widget (cookie de la conversación) cuando el mensaje estuvo visible en una pestaña activa.
- ENTRANTES del cliente: «recibido» al llegar; «leído» cuando ADI lo procesó y respondió o cuando un asesor lo vio de verdad en la
  conversación abierta (evento del panel). En WhatsApp se envía además la confirmación oficial de lectura de Meta (una sola vez)."""
from datetime import datetime

RANK = {'enviando': 0, 'reintentando': 0, 'enviado': 1, 'entregado': 2, 'leido': 3}
LABELS = {'enviando': 'Enviando', 'enviado': 'Enviado', 'entregado': 'Entregado', 'leido': 'Leído', 'error': 'Error de envío', 'reintentando': 'Reintentando'}
META = {'sent': 'enviado', 'delivered': 'entregado', 'read': 'leido', 'failed': 'error'}


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_receipts'").fetchone())


def _iso(now):
    return now.isoformat(timespec='seconds') if isinstance(now, datetime) else str(now)


def _safe(fn):
    def wrapper(c, *args, **kwargs):
        try:
            if not installed(c):
                return None
            return fn(c, *args, **kwargs)
        except Exception as error:   # un fallo de confirmaciones nunca interrumpe la atención
            print('message-status', fn.__name__, type(error).__name__, flush=True)
            return None
    wrapper.__name__ = fn.__name__
    return wrapper


def _advance(c, message_id, status, now, error='', read_by=''):
    """Avanza el estado si el nuevo es posterior (o registra un error si aún no se entregó). Devuelve True si cambió."""
    row = c.execute('SELECT status FROM message_receipts WHERE message_id=?', (message_id,)).fetchone()
    if not row:
        return False
    cur = row['status']
    stamp = _iso(now)
    if status == 'error':
        if RANK.get(cur, 0) >= RANK['entregado'] or cur == 'error':
            return False
        c.execute("UPDATE message_receipts SET status='error',failed_at=?,error=?,updated_at=? WHERE message_id=?", (stamp, error[:300], stamp, message_id))
        return True
    if RANK.get(status, -1) <= RANK.get(cur, -1) and cur != 'error':
        return False
    if cur == 'error' and status not in ('entregado', 'leido'):
        return False
    sets = ['status=?', 'updated_at=?']
    args = [status, stamp]
    if RANK[status] >= RANK['enviado']:
        sets.append("sent_at=CASE WHEN sent_at='' THEN ? ELSE sent_at END")
        args.append(stamp)
    if RANK[status] >= RANK['entregado']:
        sets.append("delivered_at=CASE WHEN delivered_at='' THEN ? ELSE delivered_at END")
        args.append(stamp)
    if status == 'leido':
        sets.append("read_at=CASE WHEN read_at='' THEN ? ELSE read_at END")
        args.append(stamp)
        if read_by:
            sets.append("read_by=CASE WHEN read_by='' THEN ? ELSE read_by END")
            args.append(read_by[:80])
    c.execute('UPDATE message_receipts SET ' + ','.join(sets) + ' WHERE message_id=?', args + [message_id])
    return True


@_safe
def record_out(c, message_id, conversation_id, channel, now, provider_id='', error=''):
    """Mensaje saliente (ADI o asesor). Web: enviado al guardarse. WhatsApp: enviado si Meta devolvió id; error si no."""
    status = 'error' if error and not provider_id else 'enviado'
    c.execute('INSERT OR IGNORE INTO message_receipts(message_id,conversation_id,channel,direction,provider_id,status,sent_at,failed_at,error,updated_at) '
              "VALUES (?,?,?,'saliente',?,?,?,?,?,?)", (message_id, conversation_id, channel, provider_id or '', status, _iso(now) if status == 'enviado' else '',
                                                        _iso(now) if status == 'error' else '', error[:300], _iso(now)))


@_safe
def record_in(c, message_id, conversation_id, channel, now, provider_id=''):
    """Mensaje entrante del cliente: recibido por el servidor (todavía NO leído)."""
    c.execute('INSERT OR IGNORE INTO message_receipts(message_id,conversation_id,channel,direction,provider_id,status,sent_at,delivered_at,updated_at) '
              "VALUES (?,?,?,'entrante',?,'entregado',?,?,?)", (message_id, conversation_id, channel, provider_id or '', _iso(now), _iso(now), _iso(now)))


@_safe
def meta_status(c, provider_id, status, now, error=''):
    """Evento firmado de Meta (sent, delivered, read, failed) para un mensaje saliente del centro de atención."""
    new = META.get(status)
    if not new or not provider_id:
        return False
    row = c.execute("SELECT message_id FROM message_receipts WHERE provider_id=? AND direction='saliente'", (provider_id,)).fetchone()
    return bool(row) and _advance(c, row['message_id'], new, now, error, 'Cliente (WhatsApp)' if new == 'leido' else '')


@_safe
def web_delivered(c, conversation_id, up_to_id, now):
    """El widget del cliente recibió los mensajes salientes hasta up_to_id."""
    for (mid,) in c.execute("SELECT message_id FROM message_receipts WHERE conversation_id=? AND direction='saliente' AND channel='web' AND message_id<=? AND status='enviado'",
                            (conversation_id, up_to_id)).fetchall():
        _advance(c, mid, 'entregado', now)


@_safe
def web_read(c, conversation_id, up_to_id, now):
    """Evento autenticado del widget: mensajes salientes visibles en una pestaña activa hasta up_to_id."""
    n = 0
    for (mid,) in c.execute("SELECT message_id FROM message_receipts WHERE conversation_id=? AND direction='saliente' AND channel='web' AND message_id<=? AND status IN ('enviado','entregado')",
                            (conversation_id, up_to_id)).fetchall():
        n += _advance(c, mid, 'leido', now, read_by='Cliente (chat web)')
    return n


@_safe
def inbound_read(c, conversation_id, now, by, up_to_id=None, env=None, send_meta=True):
    """Mensajes del cliente leídos por ADI (al procesarlos) o por un asesor (al verlos). En WhatsApp, confirmación oficial de Meta una vez."""
    sql = "SELECT message_id,channel,provider_id,meta_read_sent FROM message_receipts WHERE conversation_id=? AND direction='entrante' AND status!='leido'"
    args = [conversation_id]
    if up_to_id is not None:
        sql += ' AND message_id<=?'
        args.append(up_to_id)
    rows = c.execute(sql + ' ORDER BY message_id', args).fetchall()
    latest_wa = None
    for r in rows:
        _advance(c, r['message_id'], 'leido', now, read_by=by)
        if r['channel'] == 'whatsapp' and r['provider_id'] and not r['meta_read_sent']:
            latest_wa = r
    if latest_wa is not None and send_meta:
        _meta_mark_read(c, latest_wa['message_id'], latest_wa['provider_id'], env)
    return len(rows)


def _meta_mark_read(c, message_id, provider_id, env=None):
    """Confirmación oficial de lectura de Meta (POST /messages con status=read). No envía contenido al cliente. Una sola vez por mensaje."""
    try:
        import whatsapp_business as wa
        if not wa.ready(env):
            return False
        code, _ = wa.call('POST', '%s/messages' % wa.config(env)['phone_id'], env, {'messaging_product': 'whatsapp', 'status': 'read', 'message_id': provider_id})
        if code == 200:
            c.execute('UPDATE message_receipts SET meta_read_sent=1 WHERE message_id=?', (message_id,))
            return True
    except Exception as error:
        print('meta-read', type(error).__name__, flush=True)
    return False


@_safe
def for_messages(c, ids):
    """Estado de cada mensaje (para el panel y el widget)."""
    ids = [int(i) for i in ids][:400]
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    return {r['message_id']: {'status': r['status'], 'label': LABELS.get(r['status'], r['status']), 'direction': r['direction'], 'channel': r['channel'],
                              'sent_at': r['sent_at'], 'delivered_at': r['delivered_at'], 'read_at': r['read_at'], 'error': r['error'], 'read_by': r['read_by']}
            for r in c.execute('SELECT * FROM message_receipts WHERE message_id IN (' + marks + ')', ids)}


@_safe
def recent(c, conversation_id, limit=60):
    """Estados de los últimos mensajes de una conversación (para actualizar los vistos sin recargarla)."""
    ids = [r[0] for r in c.execute('SELECT id FROM adi_messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?', (conversation_id, limit))]
    return for_messages(c, ids)
