"""Portal seguro del cliente (Premium Billing Center · docs/PORTAL-CLIENTE.md).

Acceso: el enlace de seguimiento ACTIVO de la orden (el del QR, con token de 128 bits) más los últimos 4 dígitos de la identificación
registrada. Con eso se abre una sesión de 15 minutos solo para esa orden y ese enlace (cookie HttpOnly, SameSite=Strict, ruta del
enlace). Intentos limitados por enlace y por dirección. Revocar el enlace cierra el acceso.

Lo que se muestra (cada parte se puede apagar en la configuración, con permisos independientes por acción):
- saldo de la orden (mismos cargos y pagos que el sistema);
- pagos con su recibo en PDF;
- comprobante de entrega (si la orden se entregó);
- facturas autorizadas de la orden con su RIDE (si AZUR ya lo entregó);
- estado de cuenta del cliente en PDF (informativo, sin simulaciones).
Solo lectura: nada de lo que hace el cliente cambia pagos, órdenes ni facturas. Cada acceso y descarga queda en la auditoría."""
import hashlib
import hmac
import html
import json
import public_identity
import secrets
from datetime import datetime, timedelta

SETTING = 'client_portal'
DEFAULTS = {'enabled': True, 'balance': True, 'receipts': True, 'delivery': True, 'invoices': True, 'statement': True}
LABELS = {'enabled': 'Portal del cliente activo', 'balance': 'Mostrar el saldo de la orden', 'receipts': 'Descargar recibos de pago',
          'delivery': 'Descargar el comprobante de entrega', 'invoices': 'Descargar facturas autorizadas (RIDE)', 'statement': 'Descargar el estado de cuenta'}
from customer_device import DEFAULTS as DEVICE_DEFAULTS, LABELS as DEVICE_LABELS

DEFAULTS.update(DEVICE_DEFAULTS)
LABELS.update({'cdi_' + key: value for key, value in DEVICE_LABELS.items()})
MINUTES = 15
COOKIE = 'pcdoctor_portal'


def _hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='client_portal_sessions'").fetchone())


def settings(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (SETTING,)).fetchone()
    try:
        saved = json.loads(row['value']) if row else {}
    except ValueError:
        saved = {}
    return {k: bool(saved.get(k, v)) for k, v in DEFAULTS.items()}


def save_settings(c, data):
    cur = settings(c)
    for key in DEFAULTS:
        if key in data:
            if not isinstance(data[key], bool):
                raise ValueError('Datos inválidos.')
            cur[key] = data[key]
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SETTING, json.dumps(cur)))
    return cur


def order_identity(c, order_id):
    return c.execute('SELECT cl.identification,cl.document_type FROM orders o JOIN devices d ON d.id=o.device_id '
                     'JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (order_id,)).fetchone()


def document_kind(c, order_id):
    row = order_identity(c, order_id)
    return public_identity.kind(row['identification'], row['document_type']) if row else ''


def verify(c, order_id, last4):
    row = order_identity(c, order_id)
    identification = row['identification'] if row else ''
    if len(public_identity.digits(identification)) < 4:
        return 'sin_identificacion'
    return 'ok' if public_identity.matches(last4, identification) else 'no'


def open_session(c, order_id, link_token, now, ip):
    token = secrets.token_urlsafe(32)
    c.execute('DELETE FROM client_portal_sessions WHERE expires_at<?', (now.isoformat(timespec='seconds'),))
    c.execute('INSERT INTO client_portal_sessions(token_hash,order_id,link_hash,created_at,expires_at,ip_hash) VALUES (?,?,?,?,?,?)',
              (_hash(token), order_id, _hash(link_token), now.isoformat(timespec='seconds'), (now + timedelta(minutes=MINUTES)).isoformat(timespec='seconds'), _hash(ip)))
    return token


def session_expiry(c, cookie_token, order_id, link_token, now):
    if not cookie_token or not installed(c):
        return None
    row = c.execute('SELECT order_id,link_hash,expires_at FROM client_portal_sessions WHERE token_hash=?', (_hash(cookie_token),)).fetchone()
    if row and row['order_id'] == order_id and hmac.compare_digest(row['link_hash'], _hash(link_token)):
        if row['expires_at'] > now.isoformat(timespec='seconds'):
            return datetime.fromisoformat(row['expires_at'])
    return None


def session_ok(c, cookie_token, order_id, link_token, now):
    return session_expiry(c, cookie_token, order_id, link_token, now) is not None

def close_session(c, cookie_token):
    if cookie_token and installed(c):
        c.execute('DELETE FROM client_portal_sessions WHERE token_hash=?', (_hash(cookie_token),))


def data(c, order_id, now):
    """Lo que ve el cliente verificado (solo de SU orden). Nada se escribe."""
    import equipment
    import invoicing
    o = c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.status,o.delivered_at,s.label status_label,cl.id client_id,cl.name client,d.brand,d.model "
                  'FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?', (order_id,)).fetchone()
    money = equipment.money(c, order_id)
    pays = [p for p in equipment.payments(c, order_id) if p['kind'] in ('pago', 'devolucion') and not p['voided_at']]
    invoices = []
    for r in c.execute("SELECT i.*,(SELECT 1 FROM invoice_provider_files f WHERE f.invoice_id=i.id AND f.kind='pdf') has_pdf FROM invoices i "
                       "WHERE i.order_id=? AND i.status='autorizado' AND i.environment='2' ORDER BY i.id", (order_id,)):
        invoices.append({'id': r['id'], 'number': invoicing.number(r), 'date': r['issue_date'], 'total_cents': r['total_cents'], 'has_pdf': bool(r['has_pdf'])})
    cancel = None
    try:
        import order_cancellations
        cancel = order_cancellations.public_state(c, order_id) if order_cancellations.installed(c) else None
        reasons = order_cancellations.REASONS
    except Exception:
        reasons = {}
    return {'cancellation': cancel, 'reasons': reasons, 'order': dict(o), 'money': money, 'payments': [{'id': p['id'], 'receipt': p['receipt'], 'at': p['created_at'], 'kind': p['kind'], 'method': p['method_label'],
                                                            'amount_cents': p['amount_cents']} for p in pays],
            'delivered': o['status'] == 'entregado' or bool(o['delivered_at']), 'invoices': invoices, 'checked_at': now}


# ───────────────────────────────────────────── HTML
def _usd(cents):
    return '$' + '{:,.2f}'.format((cents or 0) / 100).replace(',', 'X').replace('.', ',').replace('X', '.')


def _date(value):
    try:
        from reception import ECUADOR_TZ
        moment = datetime.fromisoformat(str(value))
        return (moment.astimezone(ECUADOR_TZ) if moment.tzinfo else moment).strftime('%d/%m/%Y' if len(str(value)) <= 10 else '%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return str(value or '')


def _page(title, body, fallback=''):
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">'
            '<meta name="robots" content="noindex,nofollow"><title>%s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/portal.css">%s%s</head>'
            '<body><main class="portal"><header class="portal-head"><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="132"><div><p class="portal-kicker">Portal seguro del cliente</p>'
            '<h1>%s</h1></div>%s</header>%s<footer class="portal-foot"><p>PC-DOCTOR S.A. · Servicio técnico especializado</p></footer></main></body></html>') % (html.escape(title), public_identity.ASSETS, fallback, html.escape(title).replace('-', '\u2011'), public_identity.connection_badge(), body)   # guion que no corta el número de orden


def unavailable_page():
    return _page('Consulta no disponible', '<section class="portal-card"><p>El portal de consulta no está disponible en este momento. Comunícate con PC-DOCTOR S.A.</p></section>')


def form_page(token, code, message='', tone='info', *, document_kind=''):
    e = html.escape
    notice = '<p class="portal-notice" data-tone="%s" role="%s">%s</p>' % (tone, 'alert' if tone == 'error' else 'status', e(message)) if message else ''
    body = ('<section class="portal-card portal-entry">%s<h2>Estado de cuenta y comprobantes</h2>'
            '<form method="post" action="/s/%s/cuenta" class="portal-form" autocomplete="off">%s'
            '<small id="last4-hint">El acceso dura %d minutos y solo vale para esta orden.</small><button type="submit">Ver mi estado de cuenta</button></form>'
            '<p class="portal-back"><a href="/s/%s">Volver al seguimiento de la orden</a></p></section>') % (notice, e(token), public_identity.fields(document_kind, connection=False), MINUTES, e(token))
    return _page('Orden ' + code, body)


def account_page(token, info, cfg, *, expires_at=None, verified=False):
    e, o, m = html.escape, info['order'], info['money']
    base = '/s/%s/cuenta' % e(token)
    parts = ['<section class="portal-card"><p class="portal-who">%s · Orden <strong>%s</strong> · %s</p><p class="portal-status">Estado: <strong>%s</strong></p></section>'
             % (e(o['client']), e(o['code']), e(' '.join(x for x in (o['brand'], o['model']) if x) or 'Equipo'), e(o['status_label']))]
    parts.append('<section class="portal-card"><h2>Seguimiento verificado</h2><p>Consulta el equipo y el diagnóstico autorizado.</p>'
                 '<a class="portal-callout-link" href="%s/seguimiento">Abrir seguimiento verificado</a></section>' % base)
    if cfg['balance']:
        label = 'Saldo a tu favor' if m['credit_cents'] else 'Saldo pendiente'
        parts.append('<section class="portal-card"><h2>Saldo de la orden</h2><dl class="portal-money"><div><dt>Total</dt><dd>%s</dd></div><div><dt>Pagado</dt><dd>%s</dd></div>'
                     '<div class="portal-strong"><dt>%s</dt><dd>%s</dd></div></dl><p class="portal-soft">Calculado el %s. Puede cambiar con nuevos cargos o pagos.</p></section>'
                     % (_usd(m['budget_cents']), _usd(m['paid_cents']), label, _usd(m['credit_cents'] or m['balance_cents']), info['checked_at'].strftime('%d/%m/%Y %H:%M')))
    if cfg['receipts']:
        rows = ''.join('<li><span>%s · %s · %s</span><strong>%s</strong><a href="%s/recibo/%d.pdf">Recibo %s</a></li>' % (
            e(_date(p['at'])), 'Devolución' if p['kind'] == 'devolucion' else 'Pago', e(p['method']), _usd(p['amount_cents']), base, p['id'], e(p['receipt'])) for p in info['payments'])
        parts.append('<section class="portal-card"><h2>Pagos registrados</h2>%s</section>' % (('<ul class="portal-list">%s</ul>' % rows) if rows else '<p class="portal-soft">Todavía no hay pagos registrados en esta orden.</p>'))
    docs = []
    if cfg['delivery'] and info['delivered']:
        docs.append('<li><span>Comprobante de entrega del equipo</span><a href="%s/entrega.pdf">Descargar</a></li>' % base)
    if cfg['invoices']:
        for inv in info['invoices']:
            docs.append('<li><span>Factura %s · %s · %s</span>%s</li>' % (e(inv['number']), e(_date(inv['date'])), _usd(inv['total_cents']),
                                                                    ('<a href="%s/factura/%d.pdf">Descargar RIDE</a>' % (base, inv['id'])) if inv['has_pdf'] else '<em>RIDE en preparación</em>'))
    if cfg['statement']:
        docs.append('<li><span>Estado de cuenta (todas tus órdenes con saldo)</span><a href="%s/estado.pdf">Descargar</a></li>' % base)
    if docs:
        parts.append('<section class="portal-card"><h2>Documentos</h2><ul class="portal-list">%s</ul></section>' % ''.join(docs))
    cancel = info.get('cancellation')
    if cancel:
        parts.append('<section class="portal-card portal-cancel"><h2>Cancelación de la reparación</h2><p>Estado: <strong>%s</strong></p><p class="portal-soft">%s</p></section>'
                     % (e(cancel['label']), 'Su equipo está disponible para retiro en nuestro local.' if cancel['state'] in ('pendiente_retiro', 'pendiente_liquidacion', 'cancelada') else 'PC-DOCTOR revisará su solicitud y le confirmará.'))
    elif o['status'] != 'entregado' and info.get('reasons'):
        opts = ''.join('<option value="%s">%s</option>' % (e(k), e(v)) for k, v in info['reasons'].items())
        parts.append('<details class="portal-card portal-cancel"><summary>Solicitar la cancelación de la reparación</summary><form method="post" action="%s/cancelar" class="portal-form">'
                     '<label for="reason">Motivo</label><select id="reason" name="reason" required><option value="">Elige un motivo</option>%s</select>'
                     '<label for="detail">Observaciones</label><textarea id="detail" name="detail" rows="3" minlength="10" maxlength="600" required></textarea>'
                     '<small>PC-DOCTOR revisará la solicitud y se la confirmará. Solo se cobran los trabajos que usted ya autorizó.</small>'
                     '<button type="submit">Enviar solicitud de cancelación</button></form></details>' % (base, opts))
    parts.append('<form method="post" action="%s/salir" class="portal-exit"><button type="submit">Cerrar el acceso</button><a href="/s/%s">Volver al seguimiento</a></form>' % (base, e(token)))
    content = ''.join(parts)
    fallback = ''
    if expires_at is not None:
        now = info['checked_at']
        seconds = max(0, int((expires_at-now).total_seconds()))
        target = base + '?sesion=vencida'
        fallback = '<noscript><meta http-equiv="refresh" content="%d;url=%s"></noscript>' % (seconds, target)
        clock = ('<div class="portal-session-status">%s<p>Sesión disponible <time data-portal-countdown role="timer" '
                 'datetime="PT%dS">%02d:%02d</time></p></div>') % (
                     public_identity.heading(2), seconds, *divmod(seconds,60))
        content = ('<div class="portal-session" data-portal-expires="%s" data-portal-checked="%s" data-portal-return="%s">%s%s%s</div>'
                   '<p class="portal-notice" data-portal-expired role="status" hidden>Tu acceso venció. Vuelve a comprobar tu identidad.</p>') % (
                       expires_at.isoformat(), now.isoformat(), target, clock, public_identity.SUCCESS if verified else '', content)
    return _page('Orden ' + o['code'], content, fallback)


def tracking_callout(token):
    return ('<section class="portal-callout"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h16v14H3z M3 6l12-3v3 M19 10h3v6h-6v-6z"/></svg>'
            '<strong>Acceso protegido</strong><a class="portal-callout-link" href="/s/%s/cuenta">Ver estado de cuenta y comprobantes</a>'
            '<small>Verifica tu identidad para consultar la ficha técnica autorizada y los documentos. El acceso dura %d minutos.</small></section>') % (html.escape(token), MINUTES)
