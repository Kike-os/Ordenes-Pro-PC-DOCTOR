"""Centro de impresión — PC-DOCTOR (Premium Billing Center 4.0).

Formatos compatibles por comprobante, preferencias por usuario (formato y copias; 80 mm por defecto) e historial de solicitudes. Nada de
esto emite, consume secuenciales, crea pagos o movimientos de caja, modifica inventario ni envía documentos: solo genera o registra.
El historial distingue la SOLICITUD (vista, descarga, impresión, reimpresión) de una impresión confirmada, que el navegador no puede saber:
nunca se registra «impreso». Si la migración 118 aún no está aplicada, el historial queda inactivo y lo demás funciona igual."""
import json
import re

FORMATS = {'80': 'Ticket térmico 80 mm', '58': 'Ticket térmico 58 mm', 'a4': 'Factura A4 (RIDE del sistema)', 'azur': 'RIDE original de AZUR'}
ACTIONS = {'vista': 'Vista previa', 'descarga': 'Descarga', 'impresion': 'Solicitud de impresión', 'reimpresion': 'Solicitud de reimpresión'}
RESULTS = {'vista': 'solicitada', 'descarga': 'descargada', 'impresion': 'enviada_al_dialogo', 'reimpresion': 'enviada_al_dialogo'}
RESULT_LABELS = {'solicitada': 'Solicitada', 'descargada': 'Descargada', 'enviada_al_dialogo': 'Enviada al diálogo de impresión (no confirmada en papel)'}
DEFAULT = {'format': '80', 'copies': 1}


class PrintError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoice_print_log'").fetchone())


def formats_for(c, invoice_id):
    """Formatos disponibles para la factura y, si no, el motivo. Un borrador no se imprime: no tiene número ni clave de acceso."""
    inv = c.execute('SELECT id,status,access_key,provider,provider_id,environment FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not inv:
        raise PrintError('Factura no encontrada.', 404)
    emitted = bool(inv['access_key'])
    why = '' if emitted else 'Emite la factura para imprimirla: un borrador no tiene número ni clave de acceso.'
    out = []
    for key in ('80', '58', 'a4'):
        out.append({'key': key, 'label': FORMATS[key], 'available': emitted, 'reason': why, 'thermal': key in ('80', '58')})
    has_azur = emitted and inv['provider'] == 'azur' and bool(inv['provider_id'])
    out.append({'key': 'azur', 'label': FORMATS['azur'], 'available': has_azur, 'thermal': False,
                'reason': '' if has_azur else (why or 'Esta factura no tiene RIDE de AZUR (no se envió por AZUR o aún no tiene documento).')})
    return out


def url_for(invoice_id, fmt, copies=1):
    if fmt in ('80', '58'):
        return '/api/invoicing/%d/ticket.pdf?format=%s&copies=%d' % (invoice_id, fmt, max(1, min(5, int(copies or 1))))
    if fmt == 'a4':
        return '/api/invoicing/%d/ride.pdf' % invoice_id
    if fmt == 'azur':
        return '/api/invoicing/%d/azur/pdf' % invoice_id
    raise PrintError('Formato no válido.')


def prefs(c, user_id):
    row = c.execute('SELECT value FROM system_state WHERE key=?', ('print_prefs:%d' % user_id,)).fetchone()
    try:
        stored = json.loads(row['value']) if row else {}
    except (TypeError, ValueError):
        stored = {}
    out = dict(DEFAULT)
    if stored.get('format') in FORMATS:
        out['format'] = stored['format']
    if str(stored.get('copies', '')).isdigit() and 1 <= int(stored['copies']) <= 5:
        out['copies'] = int(stored['copies'])
    return out


def save_prefs(c, user_id, data):
    fmt, copies = str(data.get('format', '')), str(data.get('copies', ''))
    if fmt not in FORMATS or not copies.isdigit() or not 1 <= int(copies) <= 5:
        raise PrintError('Elige un formato y de 1 a 5 copias.')
    value = json.dumps({'format': fmt, 'copies': int(copies)})
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('print_prefs:%d' % user_id, value))
    return prefs(c, user_id)


def log(c, invoice_id, user_id, data, now):
    """Registra una solicitud. No hace nada más: ni imprime, ni emite, ni envía."""
    fmt, action, copies = str(data.get('format', '')), str(data.get('action', '')), str(data.get('copies', '1') or '1')
    if fmt not in FORMATS or action not in ACTIONS or not copies.isdigit() or not 1 <= int(copies) <= 5:
        raise PrintError('Solicitud de impresión no válida.')
    if not c.execute('SELECT 1 FROM invoices WHERE id=? AND COALESCE(access_key,\'\')!=\'\'', (invoice_id,)).fetchone():
        raise PrintError('Solo se imprimen facturas emitidas.', 409)
    if not installed(c):
        return None
    if action == 'impresion' and c.execute("SELECT 1 FROM invoice_print_log WHERE invoice_id=? AND action IN ('impresion','reimpresion')", (invoice_id,)).fetchone():
        action = 'reimpresion'  # una segunda impresión se registra como reimpresión
    return c.execute('INSERT INTO invoice_print_log(invoice_id,user_id,format,copies,action,result,created_at) VALUES (?,?,?,?,?,?,?)',
                     (invoice_id, user_id, fmt, int(copies), action, RESULTS[action], now.isoformat(timespec='seconds'))).lastrowid


def history(c, invoice_id, limit=30):
    if not installed(c):
        return {'installed': False, 'rows': []}
    rows = [{'at': r['created_at'], 'user': r['name'] or '—', 'format': FORMATS.get(r['format'], r['format']), 'copies': r['copies'],
             'action': ACTIONS.get(r['action'], r['action']), 'result': RESULT_LABELS.get(r['result'], r['result'])}
            for r in c.execute('SELECT l.*,u.name FROM invoice_print_log l LEFT JOIN users u ON u.id=l.user_id WHERE l.invoice_id=? ORDER BY l.id DESC LIMIT ?', (invoice_id, limit))]
    return {'installed': True, 'rows': rows}


def center(c, invoice_id, user_id):
    return {'formats': formats_for(c, invoice_id), 'prefs': prefs(c, user_id), 'history': history(c, invoice_id),
            'urls': {f: url_for(invoice_id, f) for f in FORMATS}}
