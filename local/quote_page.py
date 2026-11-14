"""Páginas públicas del presupuesto (enlace privado /presupuesto/<token>) con diseño Premium compacto (1.5.282).

- Mismo flujo y mismas reglas que antes: identidad con los últimos cuatro dígitos → decisión por servicio → confirmación con nombre,
  aceptación expresa, firma (y documento si el taller lo pidió). Los nombres de los campos del formulario no cambian.
- Los importes salen del servidor: cada partida lleva su importe neto, su base y su IVA calculados con quotes.split (los precios ya
  incluyen IVA). El navegador solo SUMA esos valores para el total seleccionado; nunca vuelve a calcular impuestos.
- Sin estilos ni guiones en línea (CSP del sistema). Sin JavaScript la página sigue funcionando: el servidor valida todo.
- Iconos Lucide (licencia ISC en static/lucide-LICENSE) dibujados con trazos fijos; sin recursos externos.
- Las proformas siguen usando quotes._shell y quote.css: esta página no las toca."""
import html
import re
from datetime import date, datetime
from urllib.parse import quote as urlquote

import quotes

E = html.escape
ASSET = '285'  # versión de los estáticos (evita cachés antiguas al publicar)

ICONS = {
    'copy': '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    'check': '<path d="M20 6 9 17l-5-5"/>',
    'x': '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    'message-circle': '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/>',
    'file-text': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    'download': '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    'printer': '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6"/><rect x="6" y="14" width="12" height="8" rx="1"/>',
    'shield-check': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    'calendar': '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    'monitor': '<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
    'list-checks': '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
    'signature': '<path d="m21 17-2.156-1.868A.5.5 0 0 0 18 15.5v.5a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1c0-2.545-3.991-3.97-8.5-4a1 1 0 0 0 0 5c4.153 0 4.745-11.295 5.708-13.5a2.5 2.5 0 1 1 3.31 3.284"/><path d="M3 21h18"/>',
    'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    'circle-check': '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    'info': '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    'lock': '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    'eye': '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    'rotate-ccw': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    'check-check': '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>',
}
CHOICES = (('aprobado', 'check', 'Aprobar', ' este servicio'), ('rechazado', 'x', 'No lo apruebo', ''), ('pendiente', 'clock', 'Lo decidiré después', ''))
GROUPS = (('servicio', 'Servicio técnico'), ('licencia', 'Licencia'), ('seguridad', 'Seguridad y antivirus'), ('repuesto', 'Repuesto o componente'), ('otro', 'Producto'))


def icon(name, cls='qp-ico'):
    return '<svg class="%s" viewBox="0 0 24 24" aria-hidden="true" focusable="false">%s</svg>' % (cls, ICONS[name])


def _now(now=None):
    if now is not None:
        return now
    from reception import reception_now
    return reception_now()


def _day(value):
    """Fecha dd/mm/aaaa a partir de una fecha o marca ISO; '' si no hay."""
    if not value:
        return ''
    try:
        return (date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value).date()).strftime('%d/%m/%Y')
    except ValueError:
        return ''


def expired(quote, now):
    """La vigencia («Válido hasta») ya pasó: el cliente no puede aprobar ni rechazar (decisión del 12/11/2026)."""
    return bool(quote.get('valid_until')) and quote['valid_until'] < _now(now).date().isoformat()


def validity(quote, now=None):
    """Vigencia calculada con los datos reales: estado, texto y avance (días transcurridos de la vigencia total)."""
    end = quote.get('valid_until') or ''
    if not end:
        return {'state': 'none', 'label': 'Sin fecha límite indicada', 'total': 0, 'left': 0}
    today = _now(now).date()
    last = date.fromisoformat(end)
    start_text = (quote.get('sent_at') or quote.get('created_at') or '')[:10]
    try:
        start = date.fromisoformat(start_text) if start_text else today
    except ValueError:
        start = today
    total, left = max(1, (last - start).days), (last - today).days
    if left < 0:
        return {'state': 'expired', 'label': 'Vencido el %s' % last.strftime('%d/%m/%Y'), 'total': total, 'left': 0}
    if left == 0:
        return {'state': 'soon', 'label': 'Vence hoy', 'total': total, 'left': 0}
    return {'state': 'soon' if left <= 3 else 'ok', 'label': ('Vigente · queda 1 día' if left == 1 else 'Vigente · quedan %d días' % left), 'total': total, 'left': min(left, total)}


def whatsapp(text=''):
    """Enlace de WhatsApp al contacto empresarial configurado (corporate.settings). '' si no hay número."""
    from corporate import settings
    digits = re.sub(r'\D', '', settings().get('whatsapp') or '')
    if len(digits) == 10 and digits.startswith('0'):
        digits = '593' + digits[1:]
    if len(digits) < 8:
        return ''
    return 'https://wa.me/%s%s' % (digits, ('?text=' + urlquote(text)) if text else '')


def shell(title, body, dock='', wa_text=''):
    from corporate import settings
    company = settings()
    link = whatsapp(wa_text or 'Hola PC-DOCTOR, tengo una consulta sobre mi presupuesto.')
    contact = ('<a class="qp-wa qp-noprint" href="%s" target="_blank" rel="noopener noreferrer">%s<span>WhatsApp</span></a>' % (E(link, quote=True), icon('message-circle'))) if link else ''
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">'
            '<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#060d1a"><meta name="color-scheme" content="dark"><title>%s | PC-DOCTOR S.A.</title>'
            '<link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/quote-premium.css?v=%s"><script defer src="/static/quote-premium.js?v=%s"></script></head>'
            '<body class="qp-body"><a class="qp-skip" href="#qp-main">Ir al contenido</a>'
            '<header class="qp-top"><div class="qp-top-in"><img class="qp-logo" src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="2826" height="2049" decoding="async">'
            '<div class="qp-brand"><strong>%s</strong><span>%s</span></div>%s</div></header>'
            '<main id="qp-main" class="qp">%s</main>'
            '<footer class="qp-foot"><p>%s</p><p class="qp-foot-note">La firma de esta página es un trazo manuscrito digitalizado con registro de fecha, hora y método de verificación. No es una firma electrónica certificada.</p></footer>'
            '%s</body></html>') % (E(title), ASSET, ASSET, E(company['name']), E(company['specialty']), contact, body,
                                   ('WhatsApp: ' + E(company['whatsapp'])) if company.get('whatsapp') else E(company['name']), dock)


def steps(current):
    """Paso 1 Identidad · 2 Decisión · 3 Confirmación (current = 1, 2, 3 o 4 = terminado)."""
    names = ('Identidad', 'Decisión', 'Confirmación')
    parts = []
    for number, name in enumerate(names, 1):
        state = 'done' if number < current else 'current' if number == current else 'todo'
        parts.append('<li data-state="%s"%s><span class="qp-step-n">%s</span><span>%s</span></li>' % (state, ' aria-current="step"' if state == 'current' else '', icon('check', 'qp-ico qp-ico-s') if state == 'done' else number, name))
    return '<ol class="qp-steps" aria-label="Pasos para responder el presupuesto">%s</ol>' % ''.join(parts)


def hero(quote, order, now=None, state_label=None):
    """Tarjeta superior: número (con botón para copiarlo), orden, equipo, fechas, estado y vigencia. Sin importes."""
    device = ' '.join(part for part in (order.get('brand') or '', order.get('model') or '') if part) or 'Equipo'
    vig = validity(quote, now)
    status = quote['status']
    if status == 'cancelado':  # 1.5.285: un presupuesto cancelado o reemplazado ya no tiene vigencia que contar
        vig = {'state': 'expired', 'label': 'Sin vigencia: ' + ('versión reemplazada' if state_label == 'Reemplazado' else 'presupuesto cancelado'), 'total': 0, 'left': 0}
    label = state_label or ('Vencido' if status == 'enviado' and vig['state'] == 'expired' else quotes.STATUS[status])
    tone = 'expired' if label == 'Vencido' else 'replaced' if label == 'Reemplazado' else status
    issued = _day(quote.get('sent_at')) or _day(quote.get('created_at'))
    bar = ('<progress class="qp-vig-bar" max="%d" value="%d" aria-label="Días de vigencia restantes">%d de %d días</progress>' % (vig['total'], vig['left'], vig['left'], vig['total'])) if vig['total'] else ''
    facts = [('Orden vinculada', order.get('code') or '—'), ('Equipo', device), ('Emitido', issued or '—'), ('Válido hasta', _day(quote.get('valid_until')) or 'Sin fecha límite')]
    return ('<section class="qp-hero" aria-labelledby="qp-code"><div class="qp-hero-top"><div><p class="qp-eyebrow">Presupuesto</p>'
            '<h1 id="qp-code" class="qp-code">%s</h1></div><button type="button" class="qp-btn qp-btn-ghost qp-copy qp-noprint" data-qp-copy="%s" aria-label="Copiar el número de presupuesto %s" hidden>%s<span>Copiar</span></button>'
            '<span class="qp-badge" data-tone="%s">%s</span></div>'
            '<dl class="qp-facts">%s</dl>'
            '<div class="qp-vig" data-state="%s">%s<span>%s</span>%s</div><p class="qp-sr" data-qp-copy-status role="status"></p></section>'
            ) % (E(quote['code']), E(quote['code'], quote=True), E(quote['code']), icon('copy'), E(tone), E(label),
                 ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (E(k), E(v)) for k, v in facts), E(vig['state']), icon('calendar'), E(vig['label']), bar)


def missing_page():
    return shell('Enlace no disponible', '<section class="qp-panel qp-notice" data-tone="bad">%s<div><h1>Enlace no disponible</h1>'
                 '<p>Este enlace de presupuesto no existe, venció o fue reemplazado por una versión más reciente. Comunícate con el taller.</p></div></section>' % icon('triangle-alert'))


def identify_page(token, quote, order, error='', now=None):
    form = ('<section class="qp-panel qp-identify" aria-labelledby="qp-id-title">%s<div class="qp-identify-in">%s<h2 id="qp-id-title">Comprueba tu identidad</h2>'
            '<p class="qp-muted">Por tu seguridad, los servicios y los importes se muestran después de esta comprobación.</p>'
            '<form class="qp-id-form" method="post" action="/presupuesto/%s" autocomplete="off">%s<label for="last4">Escribe los <strong>últimos cuatro dígitos</strong> de tu cédula o RUC</label>'
            '<div class="qp-id-row"><input id="last4" name="last4" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" required autofocus aria-describedby="qp-id-help">'
            '<button class="qp-btn qp-btn-primary" type="submit">%s<span>Ver mi presupuesto</span></button></div>'
            '<p id="qp-id-help" class="qp-help">Solo números. Tienes un número limitado de intentos.</p></form></div></section>'
            ) % (steps(1), icon('shield-check', 'qp-ico qp-ico-l'), E(token, quote=True), ('<p class="qp-alert" role="alert">%s%s</p>' % (icon('triangle-alert'), E(error))) if error else '', icon('lock'))
    return shell('Presupuesto ' + quote['code'], hero(quote, order, now) + form, wa_text='Hola PC-DOCTOR, tengo una consulta sobre el presupuesto %s (orden %s).' % (quote['code'], order.get('code', '')))


def extras(c, items):
    """Datos del catálogo de cada partida (solo para mostrar): marca, referencia, licencia, equipos, descripción y si tiene fotografía."""
    ids = sorted({item['catalog_id'] for item in items if item.get('catalog_id')})
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    rows = {row['id']: dict(row) for row in c.execute('SELECT id,name,description,brand,code,license_term,devices FROM catalog_items WHERE id IN (%s)' % marks, ids)}
    pictures = {row[0] for row in c.execute('SELECT item_id FROM catalog_images WHERE item_id IN (%s)' % marks, ids)}
    for key, row in rows.items():
        row['image'] = key in pictures
    return rows


def lines(quote, items, extra=None):
    """Partidas visibles con su importe neto, base e IVA ya calculados en el servidor (misma regla que quotes.totals)."""
    extra = extra or {}
    out = []
    for item in items:
        if item['status'] == 'cancelado':
            continue
        amount = quotes.net(item['quantity'] * item['unit_cents'], quote['discount_bp'])
        base, tax = quotes.split(amount, item['taxed'], quote['tax_rate_bp'])
        name, _, detail = item['description'].partition(' — ')
        info = extra.get(item.get('catalog_id')) or {}
        if not detail.strip() and (info.get('description') or '').strip() and info['description'].strip().lower() != name.strip().lower():
            detail = info['description']
        tech = [(label, (info.get(key) or '').strip()) for key, label in (('brand', 'Marca'), ('code', 'Referencia'), ('license_term', 'Licencia'), ('devices', 'Equipos'))]
        out.append(dict(item, name=name.strip() or item['description'], detail=detail.strip(), net=amount, base=base, tax=tax, tech=[pair for pair in tech if pair[1]],
                        image=bool(info.get('image')), group=item['category'] if item['category'] in dict(GROUPS) else 'otro'))
    return out


def sums(rows, choices):
    """Totales de lo seleccionado para aprobar (sumas de valores del servidor) y conteos por decisión."""
    result = {'base_taxed': 0, 'base_zero': 0, 'tax': 0, 'total': 0, 'aprobado': 0, 'rechazado': 0, 'pendiente': 0, 'sin': 0}
    for row in rows:
        choice = choices.get(row['id'], '')
        result[choice if choice in ('aprobado', 'rechazado', 'pendiente') else 'sin'] += 1
        if choice == 'aprobado':
            result['total'] += row['net']
            result['tax'] += row['tax']
            result['base_taxed' if row['taxed'] else 'base_zero'] += row['base']
    return result


def _media(row, token, key):
    if row['image'] and row.get('catalog_id'):
        return '<img class="qp-thumb" src="/presupuesto/%s/imagen/%d%s" alt="" width="64" height="64" loading="lazy" decoding="async">' % (E(token, quote=True), row['catalog_id'], ('?k=' + E(key, quote=True)) if key else '')
    return '<span class="qp-thumb qp-thumb-ico">%s</span>' % quotes._icon(row)


def _price(row, quote):
    rate = quote['tax_rate_bp'] / 100
    each = ('%d × %s' % (row['quantity'], quotes.usd(row['unit_cents']))) if row['quantity'] > 1 else 'Cantidad: 1'
    tax_note = ('IVA %g %% incluido' % rate) if row['taxed'] and quote['tax_rate_bp'] else 'Tarifa 0 %'
    discount = ' · con descuento' if quote['discount_bp'] else ''
    return '<div class="qp-price"><span class="qp-price-each">%s</span><strong>%s</strong><small>%s%s</small></div>' % (E(each), E(quotes.usd(row['net'])), E(tax_note), E(discount))


def _item(row, quote, token, key, chosen=None, choose=True):
    tech = ''.join('<li><span>%s</span> %s</li>' % (E(label), E(value)) for label, value in row['tech'])
    head = ('<div class="qp-item-head">%s<div class="qp-item-txt"><p class="qp-item-cat">%s</p><h3 class="qp-item-name">%s</h3>%s%s%s</div>%s</div>'
            % (_media(row, token, key), E(dict(GROUPS).get(row['group'], 'Producto')), E(row['name']), quotes._priority(row) if row.get('priority') else '',
               ('<p class="qp-item-desc">%s</p>' % E(row['detail'])) if row['detail'] else '', ('<ul class="qp-tech">%s</ul>' % tech) if tech else '', _price(row, quote)))
    choice = ''
    if choose:
        options = ''.join('<label class="qp-opt" data-opt="%s"><input type="radio" name="decision_%d" value="%s"%s%s>%s<span class="qp-opt-l">%s<span class="qp-opt-x">%s</span></span></label>'
                          % (value, row['id'], value, ' checked' if chosen == value else '', ' required' if value == 'aprobado' else '', icon(ico), E(text), E(extra)) for value, ico, text, extra in CHOICES)
        choice = '<fieldset class="qp-choice"><legend class="qp-sr">Tu decisión sobre «%s»</legend>%s</fieldset>' % (E(row['name']), options)
    return ('<article class="qp-item" id="qp-item-%d" data-choice="%s" data-net="%d" data-base="%d" data-tax="%d" data-taxed="%d" data-name="%s">%s%s</article>'
            % (row['id'], E(chosen or ''), row['net'], row['base'], row['tax'], 1 if row['taxed'] else 0, E(row['name'], quote=True), head, choice))


def _groups(rows, render):
    """Partidas en el orden que fijó el taller (no se reordenan), bajo un único título con el número de partidas."""
    if not rows:
        return ''
    title = 'Servicios y productos cotizados'
    return '<section class="qp-group" aria-label="%s"><h2 class="qp-group-title">%s <span>%d</span></h2>%s</section>' % (E(title), E(title), len(rows), ''.join(render(row) for row in rows))


def _quoted_block(quote, items):
    """Importes cotizados originales (fijos: no cambian al seleccionar)."""
    total = quotes.totals(items, quote['tax_rate_bp'], quote['discount_bp'])
    rate = quote['tax_rate_bp'] / 100
    rows = [('Subtotal gravado con IVA %g %%' % rate, quotes.usd(total['base_taxed'])), ('Subtotal tarifa 0 %', quotes.usd(total['base_zero']))]
    if quote['discount_bp']:
        rows.append(('%s (%g %%) aplicado' % (quotes.DISCOUNTS[quote['discount_bp']], quote['discount_bp'] / 100), '− ' + quotes.usd(total['discount'])))
    rows.append(('IVA %g %%' % rate, quotes.usd(total['tax'])))
    return ('<dl class="qp-dl">%s<div class="qp-dl-total"><dt>Total cotizado</dt><dd>%s</dd></div></dl>'
            % (''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (E(k), E(v)) for k, v in rows), E(quotes.usd(total['quoted']))))


def _review(rows, choices):
    """Resumen de la selección antes de confirmar (lo rellena el servidor y lo actualiza el navegador)."""
    picked = sums(rows, choices)
    def block(kind, title, ico):
        members = [row for row in rows if choices.get(row['id']) == kind] if kind != 'pendiente' else [row for row in rows if choices.get(row['id']) not in ('aprobado', 'rechazado')]
        body = ''.join('<li><span>%s</span><strong>%s</strong></li>' % (E(row['name']), E(quotes.usd(row['net']))) for row in members) or '<li class="qp-empty">Ninguno</li>'
        return '<section class="qp-rev" data-kind="%s"><h3>%s%s <span data-qp-rev-count="%s">%d</span></h3><ul data-qp-rev-list="%s">%s</ul></section>' % (kind, icon(ico), E(title), kind, len(members), kind, body)
    return ('<div class="qp-review" data-qp-review aria-live="polite">%s%s%s<p class="qp-review-total">Importe que autorizas <strong data-qp-sum="total">%s</strong></p>'
            '<p class="qp-help">Los servicios pendientes <strong>no</strong> se cuentan como aprobados: no se realizarán hasta que los autorices en un nuevo presupuesto.</p></div>'
            ) % (block('aprobado', 'Autorizas', 'check'), block('rechazado', 'Rechazas', 'x'), block('pendiente', 'Pendientes', 'clock'), E(quotes.usd(picked['total'])))


def decision_page(token, passkey, quote, order, items, errors=None, form=None, bank='', extra=None, now=None):
    errors, form = errors or {}, form or {}
    rows = lines(quote, items, extra)
    if expired(quote, now):
        return expired_page(token, passkey, quote, order, rows, errors, form, now)
    choices = {row['id']: form.get('decision_%d' % row['id'], '') for row in rows}
    picked = sums(rows, choices)
    rate = quote['tax_rate_bp'] / 100
    problem = lambda key: ('<p class="qp-alert" role="alert">%s%s</p>' % (icon('triangle-alert'), E(errors[key]))) if errors.get(key) else ''
    decided = picked['aprobado'] + picked['rechazado'] + picked['pendiente']
    pdf = '/presupuesto/%s/documento.pdf?k=%s' % (E(token, quote=True), E(passkey, quote=True))
    selection = ('<div class="qp-sel" aria-live="polite"><p class="qp-sel-title">Tu selección</p>'
                 '<ul class="qp-counts"><li data-kind="aprobado">%s<span>Aprobados</span><strong data-qp-count="aprobado">%d</strong></li>'
                 '<li data-kind="rechazado">%s<span>Rechazados</span><strong data-qp-count="rechazado">%d</strong></li>'
                 '<li data-kind="pendiente">%s<span>Pendientes</span><strong data-qp-count="pendiente">%d</strong></li></ul>'
                 '<dl class="qp-dl"><div><dt>Subtotal gravado aprobado</dt><dd data-qp-sum="base_taxed">%s</dd></div><div><dt>Subtotal tarifa 0 %% aprobado</dt><dd data-qp-sum="base_zero">%s</dd></div>'
                 '<div><dt>IVA %g %% aprobado</dt><dd data-qp-sum="tax">%s</dd></div><div class="qp-dl-total qp-dl-chosen"><dt>Total seleccionado para aprobación</dt><dd data-qp-sum="total">%s</dd></div></dl></div>'
                 ) % (icon('check'), picked['aprobado'], icon('x'), picked['rechazado'], icon('clock'), picked['pendiente'] + picked['sin'],
                      E(quotes.usd(picked['base_taxed'])), E(quotes.usd(picked['base_zero'])), rate, E(quotes.usd(picked['tax'])), E(quotes.usd(picked['total'])))
    aside = ('<aside class="qp-side" aria-label="Resumen económico"><section class="qp-panel qp-sum"><h2 class="qp-h2">%sResumen económico</h2>'
             '<p class="qp-sum-sub">Importes cotizados (no cambian al seleccionar)</p>%s%s'
             '<div class="qp-progress"><p><span data-qp-decided>%d</span> de %d servicios decididos</p><progress data-qp-progress max="%d" value="%d" aria-label="Servicios decididos">%d de %d</progress></div>'
             '<div class="qp-side-actions"><a class="qp-btn qp-btn-primary" href="#qp-confirm" data-qp-review-go>%s<span>Revisar selección</span></a>'
             '<div class="qp-btn-row"><a class="qp-btn qp-btn-ghost" href="%s" target="_blank" rel="noopener">%s<span>Ver PDF</span></a><a class="qp-btn qp-btn-ghost" href="%s" download>%s<span>Descargar</span></a>'
             '<button type="button" class="qp-btn qp-btn-ghost" data-qp-print hidden>%s<span>Imprimir</span></button></div></div>%s</section></aside>'
             ) % (icon('list-checks'), _quoted_block(quote, items), selection, decided, len(rows), max(1, len(rows)), decided, decided, len(rows),
                  icon('eye'), pdf, icon('file-text'), pdf, icon('download'), icon('printer'), bank)
    conditions = ''.join('<li>%s%s</li>' % ('<strong>%s.</strong> ' % E(title.rstrip('.')) if title else '', E(body)) for title, body in quotes.clauses(quote['conditions'] or quotes.CONDITIONS))
    document = ''
    if quote.get('require_id'):
        document = ('<div class="qp-doc" data-quote-document><p class="qp-label">Documento de identidad</p><p class="qp-help">%s</p>'
                    '<input type="file" accept="image/png,image/jpeg,image/webp,application/pdf" aria-label="Foto o PDF de tu documento de identidad"><input type="hidden" name="id_document" value="">'
                    '<small data-quote-document-status>Formatos: foto (JPG, PNG, WebP) o PDF, hasta 700 KB. Solo se exige si apruebas algún servicio.</small></div>%s') % (E(quotes.DOCUMENT_NOTICE), problem('id_document'))
    confirm = ('<section class="qp-panel qp-confirm" id="qp-confirm" aria-labelledby="qp-confirm-title" tabindex="-1"><h2 class="qp-h2" id="qp-confirm-title">%sConfirma tu decisión</h2>%s'
               '<details class="qp-cond"><summary>Condiciones de autorización</summary><ul>%s</ul></details>'
               '<div class="qp-fields"><div class="qp-field"><label class="qp-label" for="name">Nombre completo de quien autoriza</label><input id="name" name="name" maxlength="120" value="%s" required autocomplete="name">%s</div>'
               '<div class="qp-field"><label class="qp-label" for="comment">Observaciones (opcional)</label><textarea id="comment" name="comment" rows="2" maxlength="600">%s</textarea>%s</div></div>'
               '<div class="qp-field"><p class="qp-label" id="qp-sign-label">%sFirma con el dedo o el ratón dentro del recuadro</p><div class="qp-sign" data-quote-sign><canvas width="1000" height="300" role="img" aria-labelledby="qp-sign-label"></canvas>'
               '<button type="button" class="qp-btn qp-btn-ghost qp-btn-s" data-quote-clear>%s<span>Borrar firma</span></button></div><input type="hidden" name="signature" value="">%s</div>%s'
               '<label class="qp-accept"><input type="checkbox" name="accept"%s required><span>He leído los importes y las condiciones, y confirmo mi decisión sobre cada servicio.</span></label>%s'
               '<div class="qp-confirm-actions"><button class="qp-btn qp-btn-primary qp-btn-l" type="submit" name="action" value="decide" data-qp-submit>%s<span>Confirmar decisiones</span></button>'
               '<button class="qp-btn qp-btn-ghost" type="submit" name="action" value="change" formnovalidate data-qp-submit>%s<span>Solicitar una modificación</span></button></div>'
               '<p class="qp-help">Solicitar una modificación no aprueba nada: describe el cambio en «Observaciones» y el taller te enviará una nueva versión.</p></section>'
               ) % (icon('signature'), _review(rows, choices), conditions, E(form.get('name', ''), quote=True), problem('name'), E(form.get('comment', '')), problem('comment'),
                    icon('signature'), icon('rotate-ccw'), problem('signature'), document, ' checked' if form.get('accept') == 'on' else '', problem('accept'), icon('circle-check'), icon('message-circle'))
    toolbar = ('<div class="qp-toolbar"><p class="qp-muted">Elige una opción en cada servicio. Puedes cambiarla antes de confirmar: nada se registra hasta que pulses «Confirmar decisiones».</p>'
               '<div class="qp-bulk"><button type="button" class="qp-btn qp-btn-ok" data-quote-all="aprobado" hidden>%s<span>Aprobar todo</span></button>'
               '<button type="button" class="qp-btn qp-btn-bad" data-quote-all="rechazado" hidden>%s<span>Rechazar todo</span></button></div></div>') % (icon('check-check'), icon('x'))
    body = ('%s%s<form class="qp-form" method="post" action="/presupuesto/%s" autocomplete="off" data-qp-form><input type="hidden" name="passkey" value="%s">'
            '<div class="qp-layout"><div class="qp-main">%s%s%s</div>%s</div>%s</form>'
            ) % (hero(quote, order, now), steps(2), E(token, quote=True), E(passkey, quote=True), toolbar, problem('items'),
                 _groups(rows, lambda row: _item(row, quote, token, passkey, choices.get(row['id']) or None)), aside, confirm)
    dock = ('<div class="qp-dock qp-noprint" data-qp-dock hidden><div><span>Total seleccionado</span><strong data-qp-sum="total">%s</strong></div>'
            '<a class="qp-btn qp-btn-primary" href="#qp-confirm" data-qp-review-go>%s<span>Revisar y confirmar</span></a></div>') % (E(quotes.usd(picked['total'])), icon('list-checks'))
    return shell('Presupuesto ' + quote['code'], body, dock, 'Hola PC-DOCTOR, tengo una consulta sobre el presupuesto %s (orden %s).' % (quote['code'], order.get('code', '')))


def expired_page(token, passkey, quote, order, rows, errors, form, now):
    """Presupuesto vencido: se ve, pero no se aprueba ni se rechaza. Se puede pedir una versión actualizada o escribir por WhatsApp."""
    problem = lambda key: ('<p class="qp-alert" role="alert">%s%s</p>' % (icon('triangle-alert'), E(errors[key]))) if errors.get(key) else ''
    vig = validity(quote, now)
    wa = whatsapp('Hola PC-DOCTOR, mi presupuesto %s (orden %s) venció. ¿Pueden enviarme una versión actualizada?' % (quote['code'], order.get('code', '')))
    body = ('%s<section class="qp-panel qp-notice" data-tone="warn">%s<div><h2>Este presupuesto ya no admite aprobaciones</h2><p>%s. Los precios y la disponibilidad pueden haber cambiado, '
            'por eso ya no se puede aprobar ni rechazar desde este enlace. Pide una versión actualizada y el taller te la enviará.</p></div></section>%s'
            '<section class="qp-panel"><h2 class="qp-h2">%sServicios cotizados</h2>%s%s</section>'
            '<form class="qp-panel qp-form-change" method="post" action="/presupuesto/%s" autocomplete="off"><input type="hidden" name="passkey" value="%s">'
            '<label class="qp-label" for="comment">¿Qué necesitas? (por ejemplo: «envíenme el presupuesto actualizado»)</label><textarea id="comment" name="comment" rows="3" maxlength="600" required>%s</textarea>%s'
            '<div class="qp-confirm-actions"><button class="qp-btn qp-btn-primary" type="submit" name="action" value="change">%s<span>Solicitar una versión actualizada</span></button>%s</div></form>'
            ) % (hero(quote, order, now), icon('triangle-alert'), E(vig['label']), problem('expired'), icon('list-checks'), _groups(rows, lambda row: _item(row, quote, token, passkey, choose=False)),
                 _quoted_block(quote, rows), E(token, quote=True), E(passkey, quote=True), E(form.get('comment', '')), problem('comment'), icon('message-circle'),
                 ('<a class="qp-btn qp-btn-ghost" href="%s" target="_blank" rel="noopener noreferrer">%s<span>Escribir por WhatsApp</span></a>' % (E(wa, quote=True), icon('message-circle'))) if wa else '')
    return shell('Presupuesto ' + quote['code'], body)


def result_page(token, quote, order, items, bank='', extra=None, now=None, replaced_by=None, newer_version=None):
    """Pantalla final con las decisiones registradas (también al volver a abrir el enlace).
    1.5.285: una versión reemplazada por otra más reciente lo dice y muestra el estado real de esa versión; sus partidas quedan «Sin efecto»."""
    if quote['status'] == 'cancelado' and replaced_by:
        return replaced_page(token, quote, order, items, extra, now, replaced_by)
    rows = lines(quote, items, extra)
    summary = quotes.totals(items, quote['tax_rate_bp'], quote['discount_bp'])
    waiting = quote['status'] in quotes.DECIDED and summary['pending'] > 0
    message = {'modificacion': 'Recibimos tu solicitud de modificación. El taller revisará el presupuesto y te enviará una nueva versión.', 'rechazado': 'Registramos que no apruebas este presupuesto. No se ejecutará ningún trabajo sin tu autorización.',
               'cancelado': 'Este presupuesto fue cancelado por el taller.'}.get(quote['status'], 'Registramos tu decisión. El taller ejecutará únicamente los servicios aprobados y te avisará del avance.')
    if waiting:
        message = 'Registramos tu decisión. Solo se ejecutarán los servicios aprobados. Los que dejaste por decidir (%s) no se realizarán por ahora: el taller te enviará un nuevo presupuesto con ellos.' % quotes.usd(summary['pending'])
    tone = {'aprobado': 'ok', 'parcial': 'ok', 'rechazado': 'bad', 'modificacion': 'warn', 'cancelado': 'bad'}.get(quote['status'], 'info')
    when = _day(quote.get('decided_at'))
    hour = (quote.get('decided_at') or '')[11:16]
    decided = quote['status'] in ('aprobado', 'parcial', 'rechazado')
    def block(kind, title, ico):
        members = [row for row in rows if row['status'] == kind]
        if not members:
            return ''
        body = ''.join('<li><span>%s%s</span><strong>%s</strong></li>' % (E(row['name']), (' ' + quotes._priority(row)) if row.get('priority') else '', E(quotes.usd(row['net']))) for row in members)
        return '<section class="qp-rev" data-kind="%s"><h3>%s%s <span>%d</span></h3><ul>%s</ul></section>' % (kind, icon(ico), E(title), len(members), body)
    lists = ''
    if decided:
        lists = '<div class="qp-review">%s%s%s</div>' % (block('aprobado', 'Autorizados', 'check'), block('rechazado', 'Rechazados', 'x'), block('pendiente', 'Por decidir', 'clock'))
    else:
        void = quote['status'] == 'cancelado'  # en un presupuesto cancelado ninguna partida sigue pendiente de decisión
        lists = '<ul class="qp-result-list">%s</ul>' % ''.join('<li><span>%s</span><strong>%s</strong><em>%s</em></li>' % (E(row['name']), E(quotes.usd(row['net'])), E('Sin efecto' if void else quotes.ITEM_STATUS[row['status']])) for row in rows)
    totals = ''
    if decided:
        totals = ('<dl class="qp-dl"><div><dt>Total cotizado</dt><dd>%s</dd></div><div class="qp-dl-total qp-dl-chosen"><dt>Total aprobado</dt><dd>%s</dd></div>'
                  '<div><dt>Importe rechazado</dt><dd>%s</dd></div>%s</dl>') % (E(quotes.usd(summary['quoted'])), E(quotes.usd(summary['approved'])), E(quotes.usd(summary['rejected'])),
                                                                                ('<div><dt>Por decidir</dt><dd>%s</dd></div>' % E(quotes.usd(summary['pending']))) if summary['pending'] else '')
    pdf = '/presupuesto/%s/documento.pdf' % E(token, quote=True)
    actions = ('<div class="qp-btn-row qp-noprint"><a class="qp-btn qp-btn-ghost" href="%s" target="_blank" rel="noopener">%s<span>Ver PDF</span></a><a class="qp-btn qp-btn-ghost" href="%s" download>%s<span>Descargar PDF</span></a>'
               '<button type="button" class="qp-btn qp-btn-ghost" data-qp-print hidden>%s<span>Imprimir</span></button></div>') % (pdf, icon('file-text'), pdf, icon('download'), icon('printer')) if quote['status'] in quotes.DECIDED else ''
    payable = bank if quote['status'] in ('aprobado', 'parcial') and not newer_version else ''
    newer_html = ''
    if newer_version:
        # 1.5.285: esta decisión sigue registrada, pero el taller envió después una versión más reciente que es la vigente.
        nv = newer_version
        state = REPLACED_STATE.get(nv['status'], nv['label'])
        amount = ('Total autorizado ' + quotes.usd(nv['approved'])) if nv['status'] in ('aprobado', 'parcial') else ('Total cotizado ' + quotes.usd(nv['quoted']))
        newer_html = ('<div class="qp-notice qp-newer" data-tone="info">%s<div><h3>Hay una versión más reciente</h3><p>La versión vigente es la %s · %s · %s. '
                    'Lo que decidiste aquí sigue registrado; para pagos y trabajos vale la versión vigente.</p></div></div>') % (icon('info'), E(nv['code']), E(state), E(amount))
    body = ('%s%s<section class="qp-panel qp-result" aria-labelledby="qp-result-title"><div class="qp-notice" data-tone="%s">%s<div><h2 id="qp-result-title">%s</h2><p>%s</p>%s</div></div>%s%s%s%s</section>%s'
            ) % (hero(quote, order, now), steps(4) if decided else '', tone, icon('circle-check' if tone == 'ok' else 'info'), E(quotes.STATUS[quote['status']]), E(message),
                 ('<p class="qp-muted">Decisión registrada el %s%s.</p>' % (E(when), (' a las ' + E(hour)) if hour else '')) if when and decided else '', newer_html, lists, totals, actions, payable)
    return shell('Presupuesto ' + quote['code'], body)


REPLACED_STATE = {'borrador': 'En preparación', 'enviado': 'Esperando tu aprobación', 'aprobado': 'Aprobado', 'parcial': 'Aprobado parcialmente',
                  'rechazado': 'Rechazado', 'modificacion': 'Revisión solicitada', 'cancelado': 'Cancelado'}


def replaced_page(token, quote, order, items, extra, now, new):
    """Enlace de una versión que el taller reemplazó por otra (create() la cancela con «Sustituido por la versión Pn»). No es una
    cancelación del trabajo: se indica la versión vigente y su estado real. Esta versión no se aprobó; sus partidas quedan sin efecto."""
    rows = lines(quote, items, extra)
    state = REPLACED_STATE.get(new['status'], new['label'])
    when = _day(new.get('decided_at'))
    hour = (new.get('decided_at') or '')[11:16]
    decided = new['status'] in quotes.DECIDED
    facts = [('Versión vigente', new['code']), ('Estado', state)]
    if decided and when:
        facts.append(('Decisión registrada', when + ((' a las ' + hour) if hour else '')))
    if new['status'] in ('aprobado', 'parcial'):
        facts.append(('Total autorizado', quotes.usd(new['approved'])))
    elif new['status'] in ('enviado', 'borrador', 'modificacion'):
        facts.append(('Total cotizado', quotes.usd(new['quoted'])))
    advice = ('Lo que decidiste en esa versión es lo que vale; este enlace ya no admite decisiones.' if decided else
              'Revisa el correo más reciente del taller para abrir la versión vigente, o escríbenos por WhatsApp.')
    body = ('%s<section class="qp-panel qp-result" aria-labelledby="qp-result-title"><div class="qp-notice" data-tone="info">%s<div><h2 id="qp-result-title">Versión reemplazada</h2>'
            '<p>El taller actualizó este presupuesto con una versión más reciente, la %s. Esta versión ya no está vigente y no se aprobó: sus servicios quedan sin efecto. %s</p></div></div>'
            '<dl class="qp-dl qp-replaced">%s</dl><ul class="qp-result-list">%s</ul></section>'
            ) % (hero(quote, order, now, 'Reemplazado'), icon('info'), E(new['code']), E(advice),
                 ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (E(k), E(v)) for k, v in facts),
                 ''.join('<li><span>%s</span><strong>%s</strong><em>Sin efecto</em></li>' % (E(row['name']), E(quotes.usd(row['net']))) for row in rows))
    return shell('Presupuesto ' + quote['code'], body, wa_text='Hola PC-DOCTOR, tengo una consulta sobre el presupuesto %s (orden %s).' % (new['code'], order.get('code', '')))
