"""Documentos de la factura: RIDE (representación impresa), políticas comerciales con versiones y detalle de garantías, y su envío al cliente.

- Políticas: el texto corporativo lo carga administración. Una versión solo se publica con su validación legal registrada (quién y
  cuándo) y, publicada, no cambia nunca. Cada factura queda asociada al emitirse a la versión vigente de su alcance (físico o digital):
  los cambios posteriores no alteran lo que ya se entregó.
- Envío al cliente: solo de facturas AUTORIZADAS por el SRI en ambiente de producción; una sola vez por factura, con reintentos
  controlados y registro de cada resultado. Un comprobante de pruebas nunca se envía como si fuera autorizado: solo puede enviarse a la
  dirección de prueba configurada, marcado como «PRUEBA — SIN VALIDEZ TRIBUTARIA».
- Garantías: las de PC-DOCTOR y del fabricante de cada unidad facturada o consumida en la orden, por separado, con sus fechas."""
import base64
import json
import re
from datetime import date

import invoicing
from document_canvas import BLUE, GRAY, INK, WIDTHS, Canvas

SCOPES = {'fisico': 'Productos físicos y servicios', 'digital': 'Productos digitales (licencias)'}
DEFAULT_TITLE = 'Políticas de Venta, Cambios, Devoluciones y Garantías — PC-DOCTOR S.A.'
MAX_TRIES = 3
MIN_BODY = 200
A4 = (595.28, 841.89)
RED = (.70, .12, .16)


class DocumentError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def usd(cents):
    return '$' + format(cents // 100, ',').replace(',', '.') + ',%02d' % (cents % 100)


def dmy(text):
    try:
        return date.fromisoformat(str(text)[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return str(text or '—')


# ---- Configuración ----------------------------------------------------------------------------------------------------

def _state(c, key, default=''):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


def _set_state(c, key, value, now):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))


def settings(c):
    return {'auto': _state(c, 'invoice_docs_auto', 'on') == 'on', 'test_recipient': _state(c, 'invoice_docs_test_recipient', '')}


def save_settings(c, data, user, now):
    email = str(data.get('test_recipient', '') or '').strip()[:200]
    if email and not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(\.[^\s@<>.]+)+', email):
        raise DocumentError('Correo de prueba no válido.', fields={'test_recipient': 'Correo no válido.'})
    _set_state(c, 'invoice_docs_auto', 'on' if str(data.get('auto', '')) in ('1', 'true', 'True', 'on') else 'off', now)
    _set_state(c, 'invoice_docs_test_recipient', email, now)
    return settings(c)


# ---- Políticas comerciales ----------------------------------------------------------------------------------------------

def _policy(c, policy_id):
    row = c.execute('SELECT * FROM sales_policies WHERE id=?', (policy_id,)).fetchone() if str(policy_id or '').isdigit() else None
    if not row:
        raise DocumentError('Versión de las políticas no encontrada.', 404)
    return dict(row)


def _public(row):
    out = {k: row[k] for k in ('id', 'scope', 'code', 'version', 'title', 'body', 'status', 'legal_validated_by', 'legal_validated_at', 'published_at', 'archived_at', 'created_at', 'updated_at')}
    out['scope_label'] = SCOPES[row['scope']]
    return out


def policies(c):
    rows = [dict(r) for r in c.execute('SELECT p.*,(SELECT COUNT(*) FROM invoice_policies i WHERE i.policy_id=p.id) invoices FROM sales_policies p ORDER BY p.scope,p.id DESC')]
    out = {}
    for scope, label in SCOPES.items():
        mine = [dict(_public(r), invoices=r['invoices']) for r in rows if r['scope'] == scope]
        out[scope] = {'label': label, 'current': next((r for r in mine if r['status'] == 'vigente'), None), 'draft': next((r for r in mine if r['status'] == 'borrador'), None), 'history': mine}
    return {'scopes': out, 'settings': settings(c), 'default_title': DEFAULT_TITLE, 'min_body': MIN_BODY}


def save_policy(c, data, user, now):
    """Borrador nuevo o edición del borrador de un alcance. Solo los borradores se editan; lo publicado no cambia."""
    scope = str(data.get('scope', ''))
    if scope not in SCOPES:
        raise DocumentError('Elige a qué productos aplica.', fields={'scope': 'Alcance no válido.'})
    text = lambda key, size: re.sub(r'[ \t]+', ' ', str(data.get(key, '') or '')).strip()[:size]
    code, version, title = text('code', 40).upper(), text('version', 20), text('title', 200)
    body = str(data.get('body', '') or '').replace('\r\n', '\n').strip()[:60000]
    errors = {}
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{1,39}', code):
        errors['code'] = 'Letras, números y guiones (ej.: PCD-POL-VTA).'
    if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z.-]{0,19}', version):
        errors['version'] = 'Ej.: 2026.10.1'
    if len(title) < 5:
        errors['title'] = 'Indica el título del documento.'
    policy_id = data.get('id')
    current = _policy(c, policy_id) if str(policy_id or '').isdigit() else None
    if current and current['status'] != 'borrador':
        raise DocumentError('Una versión publicada no se modifica: crea una versión nueva.', 409)
    if not errors and c.execute('SELECT 1 FROM sales_policies WHERE scope=? AND version=? AND id!=?', (scope, version, current['id'] if current else 0)).fetchone():
        errors['version'] = 'Esa versión ya existe para este alcance.'
    if not current and c.execute("SELECT 1 FROM sales_policies WHERE scope=? AND status='borrador'", (scope,)).fetchone():
        raise DocumentError('Ya hay un borrador para este alcance: edítalo o descártalo.', 409)
    if errors:
        raise DocumentError('Revisa los datos del documento.', fields=errors)
    if current:
        c.execute('UPDATE sales_policies SET scope=?,code=?,version=?,title=?,body=?,updated_by=?,updated_at=? WHERE id=?', (scope, code, version, title, body, user['id'], stamp(now), current['id']))
        return current['id']
    return c.execute("INSERT INTO sales_policies(scope,code,version,title,body,status,created_by,created_at,updated_by,updated_at) VALUES (?,?,?,?,?,'borrador',?,?,?,?)",
                     (scope, code, version, title, body, user['id'], stamp(now), user['id'], stamp(now))).lastrowid


def discard_policy(c, policy_id):
    row = _policy(c, policy_id)
    if row['status'] != 'borrador':
        raise DocumentError('Solo se descarta un borrador.', 409)
    c.execute('DELETE FROM sales_policies WHERE id=?', (row['id'],))


def publish_policy(c, policy_id, data, user, now):
    """Publica el borrador como versión vigente de su alcance. Exige el texto completo y la validación legal declarada por administración
    (nombre de quien validó); la versión anterior pasa a archivada y conserva sus facturas."""
    row = _policy(c, policy_id)
    if row['status'] != 'borrador':
        raise DocumentError('Esta versión ya fue publicada.', 409)
    errors = {}
    if len(row['body']) < MIN_BODY:
        errors['body'] = 'Carga el texto corporativo completo antes de publicar.'
    validator = re.sub(r'\s+', ' ', str(data.get('validated_by', '') or '')).strip()[:120]
    if len(validator) < 3:
        errors['validated_by'] = 'Indica quién realizó la validación legal.'
    if str(data.get('confirm', '')) not in ('1', 'true', 'True'):
        errors['confirm'] = 'Confirma que el texto fue validado legalmente.'
    if errors:
        raise DocumentError('No se puede publicar todavía.', fields=errors)
    c.execute("UPDATE sales_policies SET status='archivada',archived_at=?,updated_at=? WHERE scope=? AND status='vigente'", (stamp(now), stamp(now), row['scope']))
    c.execute("UPDATE sales_policies SET status='vigente',legal_validated_by=?,legal_validated_at=?,published_by=?,published_at=?,updated_by=?,updated_at=? WHERE id=?",
              (validator, stamp(now), user['id'], stamp(now), user['id'], stamp(now), row['id']))
    return row['id']


def invoice_scopes(c, invoice_id):
    """Alcances de una factura: digital si tiene licencias; físico si tiene productos físicos o servicios. Puede tener los dos."""
    inv = c.execute('SELECT source_kind FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    cats = [r[0] or '' for r in c.execute('SELECT g.category FROM invoice_items i LEFT JOIN catalog_items g ON g.id=i.catalog_id WHERE i.invoice_id=?', (invoice_id,))]
    digital = (inv and inv['source_kind'] == 'venta_licencia') or any(cat in ('licencia', 'seguridad') for cat in cats)
    physical = any(cat not in ('licencia', 'seguridad') for cat in cats) or not cats
    return [s for s, on in (('fisico', physical and not (inv and inv['source_kind'] == 'venta_licencia')), ('digital', digital)) if on] or ['fisico']


def attach_policies(c, invoice_id, now):
    """Al emitir: asocia la versión vigente de cada alcance de la factura. Si no hay versión vigente, la factura queda sin política."""
    for scope in invoice_scopes(c, invoice_id):
        current = c.execute("SELECT id FROM sales_policies WHERE scope=? AND status='vigente'", (scope,)).fetchone()
        if current:
            c.execute('INSERT OR IGNORE INTO invoice_policies(invoice_id,policy_id,scope,created_at) VALUES (?,?,?,?)', (invoice_id, current['id'], scope, stamp(now)))


def invoice_policies(c, invoice_id):
    return [dict(_public(r)) for r in c.execute('SELECT p.* FROM invoice_policies x JOIN sales_policies p ON p.id=x.policy_id WHERE x.invoice_id=? ORDER BY x.scope', (invoice_id,))]


# ---- Dibujo común ---------------------------------------------------------------------------------------------------------

def width(text, size):
    return sum(WIDTHS.get(ch, 556) for ch in str(text)) * size / 1000


class Page:
    """Utilidades de dibujo sobre document_canvas.Canvas (coordenadas desde arriba, en puntos)."""
    def __init__(self, title):
        self.pdf = Canvas(*A4, title)
        self.w, self.h = A4

    def rect(self, x, y, w, h, fill=None, stroke=(.80, .84, .89), line=.7):
        s = self.pdf.stream
        if fill:
            s.set_color_rgb(*fill)
            s.rectangle(x, self.h - y - h, w, h)
            s.fill()
        if stroke:
            s.set_color_rgb(*stroke, stroke=True)
            s.set_line_width(line)
            s.rectangle(x, self.h - y - h, w, h)
            s.stroke()

    def right(self, text, x, y, size=9, bold=False, color=INK):
        self.pdf.text(text, x - width(text, size), y, size, bold, color)

    def center(self, text, x, y, size=9, bold=False, color=INK):
        self.pdf.text(text, x - width(text, size) / 2, y, size, bold, color)

    def barcode(self, value, x, y, w, h):
        from code128 import widths as bars
        modules = bars(value)
        unit = w / (sum(modules) + 20)
        left = x + 10 * unit
        s = self.pdf.stream
        s.set_color_rgb(0, 0, 0)
        for i, size in enumerate(modules):
            if i % 2 == 0:
                s.rectangle(left, self.h - y - h, size * unit, h)
            left += size * unit
        s.fill()


def _footer(page, number, total, note=''):
    import corporate
    company = corporate.settings()
    page.pdf.line(40, page.h - 46, page.w - 80)
    contact = ' · '.join(v for v in (company['name'], 'WhatsApp ' + company['whatsapp'], company['support_email'], re.sub(r'^https?://|/$', '', company['website'])) if v)
    page.pdf.text(contact, 40, page.h - 40, 7, False, GRAY)
    if note:
        page.pdf.text(note, 40, page.h - 30, 7, True, RED)
    page.right('Página %d de %d' % (number, total), page.w - 40, page.h - 40, 7, False, GRAY)


# ---- PDF de políticas -----------------------------------------------------------------------------------------------------

def _blocks(body):
    """Texto → bloques: «# Título», «1. Subtítulo» (línea corta numerada), viñetas «- » o «• » y párrafos."""
    out = []
    for raw in body.replace('\r\n', '\n').split('\n'):
        line = raw.strip()
        if not line:
            out.append(('gap', ''))
        elif line.startswith('#'):
            out.append(('h1', line.lstrip('#').strip()))
        elif re.match(r'^\d+(\.\d+)*[.)]?\s+\S', line) and len(line) <= 90 and not line.endswith('.'):
            out.append(('h2', line))
        elif line[:2] in ('- ', '• ', '* '):
            out.append(('li', line[2:].strip()))
        else:
            out.append(('p', line))
    return out


def policy_pdf(policy, invoice=None):
    """PDF A4 de las políticas: logo original, título, código y versión, datos de la factura y del cliente, cuerpo con títulos y viñetas,
    contacto, pie y numeración «Página n de N»."""
    lines = []  # (página, tipo, texto, y)
    page_h, top, bottom, left, text_w = A4[1], 150, A4[1] - 70, 50, A4[0] - 100
    measure = Canvas(*A4, 'medida')
    y, pages = top + (70 if invoice is not None else 52), 1
    for kind, text in _blocks(policy['body']):
        size, gap, indent = {'h1': (12, 10, 0), 'h2': (10, 6, 0), 'li': (9, 2, 14), 'p': (9, 4, 0), 'gap': (9, 4, 0)}[kind]
        wrapped = measure.wrap(text, text_w - indent - (10 if kind == 'li' else 0), size) if text else []
        need = gap + len(wrapped) * (size + 3.4)
        if kind in ('h1', 'h2'):
            need += 18  # un título no queda solo al final de la página
        if y + need > bottom:
            pages += 1
            y = top
        y += gap
        for n, piece in enumerate(wrapped):
            lines.append((pages, kind, piece, y, n == 0))
            y += size + 3.4
        if kind == 'h1':
            lines.append((pages, 'rule', '', y + 1, True))
            y += 6
    page = Page(policy['title'])
    draft = policy['status'] == 'borrador'
    for number in range(1, pages + 1):
        page.pdf.page()
        page.rect(0, 0, page.w, 118, fill=(.96, .97, .99), stroke=None)
        page.rect(0, 118, page.w, 2.2, fill=(.84, .23, .29), stroke=None)
        page.pdf.logo(left, 26, 92)
        title = page.pdf.wrap(policy['title'], page.w - 210, 13)[:3]
        for n, piece in enumerate(title):
            page.pdf.text(piece, 158, 30 + n * 17, 13, True, BLUE)
        meta = 'Código %s · Versión %s' % (policy['code'], policy['version']) + (' · Vigente desde %s' % dmy(policy['published_at']) if policy['published_at'] else '')
        page.pdf.text(meta, 158, 34 + len(title) * 17, 8.5, False, GRAY)
        if draft:
            page.pdf.text('BORRADOR — NO VIGENTE: vista previa sin validez', 158, 48 + len(title) * 17, 8.5, True, RED)
        if number == 1 and invoice is not None:
            page.rect(left, 132, page.w - 2 * left, 56, fill=(1, 1, 1))
            cells = [('Factura N.º', invoice.get('number') or 'Sin número'), ('Fecha', dmy(invoice.get('issue_date') or invoice.get('created_at'))), ('Cliente', invoice.get('buyer_name') or 'Consumidor final')]
            x = left + 12
            for label, value in cells:
                page.pdf.text(label.upper(), x, 142, 7, True, GRAY)
                page.pdf.text(page.pdf.wrap(value, 150, 10)[0], x, 156, 10, True, INK)
                x += 165
            if invoice.get('test'):
                page.pdf.text('Factura de PRUEBA: sin validez tributaria.', left + 12, 174, 8, True, RED)
        elif number == 1:
            page.pdf.text('Documento sin factura asociada (vista previa).', left, 138, 8.5, False, GRAY)
        for p, kind, text, y, first in lines:
            if p != number:
                continue
            if kind == 'rule':
                page.pdf.line(left, y, 60)
            elif kind == 'h1':
                page.pdf.text(text, left, y, 12, True, BLUE)
            elif kind == 'h2':
                page.pdf.text(text, left, y, 10, True, INK)
            elif kind == 'li':
                if first:
                    page.pdf.text('•', left + 4, y, 9, True, BLUE)
                page.pdf.text(text, left + 14, y, 9)
            else:
                page.pdf.text(text, left, y, 9)
        _footer(page, number, pages, 'BORRADOR — NO VIGENTE' if draft else '')
    return page.pdf.finish()


# ---- RIDE (representación impresa de la factura) ---------------------------------------------------------------------------

def _unit(micros):
    """Precio unitario exacto del XML (6 decimales), con al menos 2 decimales y sin ceros finales sobrantes: 8,70 · 10,4533."""
    whole, frac = divmod(int(micros), 1_000_000)
    digits = ('%06d' % frac).rstrip('0')
    return '%s,%s' % (format(whole, ',d').replace(',', '.'), (digits + '00')[:max(2, len(digits))])


def ride_pdf(c, invoice_id):
    """RIDE A4 de una factura emitida, con la identidad de PC-DOCTOR (márgenes de 15 mm): bloque del emisor (logo original, razón social, nombre
    comercial, direcciones sin repetir, contabilidad, contribuyente especial, leyenda RIMPE y agente de retención según los Datos fiscales) y bloque
    tributario (RUC, FACTURA, número, autorización, fecha y hora, ambiente, emisión y clave de acceso con su Code 128); comprador en tarjeta,
    detalle con el encabezado repetido, información adicional, formas de pago y resumen de impuestos con los valores registrados. Si no está
    autorizada por el SRI lo indica en cada página: no es un comprobante válido. No inventa ningún dato tributario."""
    import document_style as ds
    import sri_xml
    data = invoicing.detail(c, invoice_id)
    inv, s = data['invoice'], data['settings']
    if not inv['access_key']:
        raise DocumentError('La factura todavía no se emitió: no tiene RIDE.', 409)
    valid = inv['status'] == 'autorizado' and inv['environment'] == '2'
    note = '' if valid else ('DOCUMENTO DE PRUEBA — SIN VALIDEZ TRIBUTARIA' if inv['environment'] == '1' else 'NO AUTORIZADO POR EL SRI — SIN VALIDEZ TRIBUTARIA')
    doc = ds.Doc('Factura ' + inv['number'])
    L = 42.5  # 15 mm
    R = ds.A4[0] - L
    W = R - L
    PANEL = (.965, .972, .984)
    LABEL = (.42, .47, .55)

    def label(value, x, y, color=LABEL):
        doc.text(value.upper(), x, y, 6.6, True, color)

    def warning(y):
        if note:
            doc.rounded(L, y, W, 17, 5, fill=(.995, .93, .93), stroke=RED, line=.5)
            doc.center(note, ds.A4[0] / 2, y + 5, 8.5, True, RED)
            return y + 24
        return y

    def continuation():
        doc.page()
        y = warning(16)
        doc.logo(L, y - 2, 50)
        doc.text('Factura No. %s' % inv['number'], L + 62, y + 4, 11, True, ds.NAVY)
        doc.text('R.U.C. %s · %s · continuación' % (s['ruc'] or '—', s['legal_name'] or ''), L + 62, y + 20, 8.3, False, GRAY)
        doc.hline(L, y + 44, W, ds.NAVY, 1.4)
        return y + 56

    doc.page()
    top = warning(16)
    # ---- Bloque tributario (derecha): ancho suficiente para un Code 128 legible de 49 dígitos.
    tw = 268
    tx = R - tw
    ew = W - tw - 12
    rows = [('No.', inv['number'], True), ('Número de autorización', inv['authorization_number'] or ('Pendiente de autorización del SRI' if inv['environment'] == '2' else 'Ambiente de pruebas: no autorizada'), bool(inv['authorization_number'])),
            ('Fecha y hora de autorización', inv['authorized_at'][:19].replace('T', ' ') if inv['authorized_at'] else '—', False),
            ('Ambiente', 'PRODUCCIÓN' if inv['environment'] == '2' else 'PRUEBAS', True), ('Tipo de emisión', 'NORMAL', True)]
    th = 40 + 15 * (len(rows) - 1) + 24 + 66 + 8  # filas, autorización (dos líneas), clave de acceso con su código
    # ---- Bloque del emisor (izquierda): sin repetir la dirección cuando matriz y establecimiento coinciden.
    head_office, branch = (s['head_office_address'] or '').strip(), (s['branch_address'] or '').strip()
    same = head_office and branch and re.sub(r'\W+', '', head_office.lower()) == re.sub(r'\W+', '', branch.lower())
    fields = [('Razón social', s['legal_name'] or 'Razón social sin configurar', True), ('Nombre comercial', s['trade_name'] or ds.TRADE_NAME, False)]
    if same:
        fields.append(('Dirección matriz y establecimiento', head_office, False))
    else:
        fields += [('Dirección matriz', head_office, False), ('Dirección del establecimiento', branch, False)]
    fields += [('Contribuyente especial Nro.', s['special_taxpayer'], False), ('Obligado a llevar contabilidad', s['keeps_accounts'] or '—', False),
               ('Agente de retención', ('Resolución No. ' + s['withholding_agent']) if s['withholding_agent'] else '', False)]
    fields = [(k, v, b) for k, v, b in fields if v]
    legend = sri_xml.RIMPE_LEGENDS.get(s['regime'], '')
    logo_h = 0
    eh = 0
    # Altura: se calcula primero para alinear los dos bloques.
    wrapped = [(k, doc.wrap(v, ew - 28, 8.6 if not b else 9.2)[:2], b) for k, v, b in fields]
    eh = 14 + 70 + 10 + sum(9 + 10.5 * len(v) + 3 for k, v, b in wrapped) + (16 if legend else 0) + 6
    hh = max(eh, th)
    doc.rounded(L, top, ew, hh, 7, fill=None, stroke=ds.LINE)
    logo_h = doc.logo(L + 14, top + 12, 92)
    yy = top + 12 + logo_h + 10
    for k, v, b in wrapped:
        label(k, L + 14, yy)
        for i, piece in enumerate(v):
            doc.text(piece, L + 14, yy + 9 + i * 10.5, 9.2 if b else 8.6, b, ds.NAVY if b else INK)
        yy += 9 + 10.5 * len(v) + 3
    if legend:
        doc.rounded(L + 10, yy + 1, ew - 20, 14, 4, fill=PANEL, stroke=None)
        doc.center(legend, L + ew / 2, yy + 4.5, 7.4, True, ds.NAVY)
    doc.rounded(tx, top, tw, hh, 7, fill=PANEL, stroke=ds.LINE)
    doc.rounded(tx, top, tw, 30, 7, fill=ds.NAVY, stroke=None)
    doc.rect(tx, top + 22, tw, 8, fill=ds.NAVY, stroke=None)
    doc.text('FACTURA', tx + 12, top + 8, 14, True, ds.WHITE)
    doc.right('R.U.C. ' + (s['ruc'] or '—'), tx + tw - 12, top + 10.5, 9.5, True, ds.WHITE)
    yy = top + 40
    for k, v, b in rows:
        if k == 'Número de autorización':
            label(k, tx + 12, yy)
            doc.text(v, tx + 12, yy + 9, 8 if len(v) > 40 else 8.6, b, INK)
            yy += 24
            continue
        doc.text(k, tx + 12, yy, 8, False, LABEL)
        doc.right(v, tx + tw - 12, yy - .5, 9 if k == 'No.' else 8.6, b, ds.NAVY if k == 'No.' else INK)
        yy += 15
    label('Clave de acceso', tx + 12, yy + 2)
    doc.rect(tx + 6, yy + 12, tw - 12, 48, fill=ds.WHITE, stroke=None)  # fondo blanco: mejor lectura del código
    doc.barcode(inv['access_key'], tx + 6, yy + 14, tw - 12, 40)
    doc.center(inv['access_key'], tx + tw / 2, yy + 58, 7.4, False, INK)
    y = top + hh + 12
    # ---- Comprador: tarjeta gris clara a dos columnas.
    buyer = 'CONSUMIDOR FINAL' if inv['consumer_final'] else inv['buyer_name']
    half = (W - 28) / 2
    addr = doc.wrap(inv['buyer_address'] or '—', half - 4, 8.8)[:2]
    ch = 60 + 11 * max(0, len(addr) - 1) + (0 if not inv['order_code'] else 0)
    doc.rounded(L, y, W, ch, 7, fill=PANEL, stroke=ds.LINE)
    label('Comprador · Razón social / Nombres', L + 14, y + 10, ds.NAVY)
    doc.text(doc.wrap(buyer or '—', W - 28, 10.5)[0], L + 14, y + 21, 10.5, True, ds.NAVY)
    col2 = L + 14 + half + 14
    yy = y + 38
    label('Identificación', L + 14, yy)
    doc.text('9999999999999' if inv['consumer_final'] else (inv['buyer_id'] or '—'), L + 14, yy + 9, 8.8)
    label('Fecha de emisión', L + 14 + half / 2, yy)
    doc.text(dmy(inv['issue_date']), L + 14 + half / 2, yy + 9, 8.8)
    label('Dirección', col2, yy)
    for i, piece in enumerate(addr):
        doc.text(piece, col2, yy + 9 + i * 11, 8.8)
    y += ch + 12
    # ---- Detalle.
    items = [{'code': i['code'] or '', 'qty': str(i['quantity']), 'desc': i['description'], 'unit': _unit(i['unit_price_micros']),
              'disc': usd(i['discount_cents'])[1:], 'total': usd(i['base_cents'])[1:]} for i in data['items']]
    cols = [('Cód. principal', 62, 'l', 'code', True), ('Cant.', 36, 'c', 'qty', False), ('Descripción', W - 62 - 36 - 70 - 58 - 68, 'l', 'desc', True),
            ('P. unitario', 70, 'r', 'unit', False), ('Descuento', 58, 'r', 'disc', False), ('Precio total', 68, 'r', 'total', False)]
    y = doc.table(cols, items, y, continuation, left=L, width=W, size=8.7, head_h=19, pad=7)
    # ---- Información adicional y formas de pago (izquierda) · resumen de impuestos (derecha).
    info = [('Correo', inv['buyer_email']), ('Teléfono', inv['buyer_phone']), ('Orden', inv['order_code']), ('Venta', inv['sale_code'])]
    if data['bank_account']:
        b = data['bank_account']
        info.append(('Cuenta para pagos', '%s · %s · %s' % (b['bank'], b['type_label'], b['number'])))
    info = [(k, v) for k, v in info if v]
    totals = [('Subtotal ' + ('%g' % (g['rate_bp'] / 100)).replace('.', ',') + ' %', usd(g['base_cents'])) for g in data['rates']]
    totals += [('Subtotal sin impuestos', usd(inv['subtotal_cents'])), ('Total descuento', usd(inv['discount_cents']))]
    totals += [('IVA ' + ('%g' % (g['rate_bp'] / 100)).replace('.', ',') + ' %', usd(g['tax_cents'])) for g in data['rates'] if g['rate_bp']]
    sw = 210
    iw = W - sw - 14
    pays = data['payments']
    lh = 28 + 13 * max(1, len(info)) + 22 + 13 * max(1, len(pays)) + 8
    sh = 12 + 16 * len(totals) + 40
    if y + max(lh, sh) + 6 > ds.BOTTOM:
        y = continuation()
    y += 6
    doc.rounded(L, y, iw, lh, 7, fill=None, stroke=ds.LINE)
    label('Información adicional', L + 14, y + 10, ds.NAVY)
    yy = y + 26
    for k, v in info or [('—', '')]:
        doc.text(k, L + 14, yy, 8.2, True, LABEL)
        doc.text(doc.wrap(v, iw - 110, 8.6)[0] if v else '', L + 96, yy, 8.6)
        yy += 13
    yy += 6
    label('Forma de pago', L + 14, yy)
    doc.right('Valor', L + iw - 14, yy, 6.6, True, LABEL)
    yy += 14
    for pay in pays:
        doc.text(doc.wrap(pay['sri_code'] + ' · ' + pay['label'], iw - 110, 8.3)[0], L + 14, yy, 8.3)
        doc.right(usd(pay['amount_cents']), L + iw - 14, yy, 8.8, True)
        yy += 13
    tx = R - sw
    doc.rounded(tx, y, sw, sh, 7, fill=PANEL, stroke=ds.LINE)
    yy = y + 12
    for k, v in totals:
        doc.text(k, tx + 12, yy, 8.6)
        doc.right(v, tx + sw - 12, yy, 8.8)
        yy += 16
    doc.rounded(tx, y + sh - 32, sw, 32, 7, fill=ds.NAVY, stroke=None)
    doc.rect(tx, y + sh - 32, sw, 8, fill=ds.NAVY, stroke=None)
    doc.text('VALOR TOTAL', tx + 12, y + sh - 21, 9.5, True, ds.WHITE)
    doc.right(usd(inv['total_cents']), tx + sw - 12, y + sh - 24, 14, True, ds.WHITE)
    doc.footer(note, RED, margin=L)
    return doc.finish()


# ---- Garantías de la factura ------------------------------------------------------------------------------------------------

def warranty_rows(c, invoice_id):
    """Unidades con serie de la factura (o consumidas en su orden), con sus dos garantías por separado, y los productos del inventario
    facturados con la garantía que les corresponde según su ficha."""
    inv = c.execute('SELECT id,order_id FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not inv:
        raise DocumentError('Factura no encontrada.', 404)
    try:
        units = [dict(r) for r in c.execute(
            "SELECT u.id,u.internal_code,u.serial,u.status,u.sold_at,u.delivered_at,u.store_warranty_from,u.store_warranty_to,u.maker_warranty_from,u.maker_warranty_to,"
            "g.name,i.sku,i.model,i.id item_id,b.name brand,i.warranty_store_qty,i.warranty_store_unit,i.warranty_store_from,i.warranty_maker_qty,i.warranty_maker_unit,i.warranty_maker_from "
            "FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id JOIN catalog_items g ON g.id=i.catalog_id LEFT JOIN inventory_brands b ON b.id=i.brand_id "
            "WHERE u.invoice_id=? OR (? IS NOT NULL AND u.order_id=? AND u.status IN ('vendida','consumida')) ORDER BY u.id", (inv['id'], inv['order_id'], inv['order_id']))]
        products = [dict(r) for r in c.execute(
            "SELECT DISTINCT i.id item_id,g.name,i.sku,i.model,b.name brand,i.tracking,i.warranty_store_qty,i.warranty_store_unit,i.warranty_store_from,i.warranty_maker_qty,i.warranty_maker_unit,"
            "i.warranty_maker_from,x.quantity FROM invoice_items x JOIN inventory_items i ON i.catalog_id=x.catalog_id JOIN catalog_items g ON g.id=i.catalog_id "
            "LEFT JOIN inventory_brands b ON b.id=i.brand_id WHERE x.invoice_id=? ORDER BY x.position", (inv['id'],))]
    except Exception:
        return {'units': [], 'products': []}  # base sin el Centro de Inventario
    import inventory_center
    today = date.today()
    for unit in units:
        unit['store'] = inventory_center._coverage(unit['store_warranty_from'], unit['store_warranty_to'], today) if unit['store_warranty_to'] else None
        unit['maker'] = inventory_center._coverage(unit['maker_warranty_from'], unit['maker_warranty_to'], today) if unit['maker_warranty_to'] else None
    for p in products:
        p['store_label'] = inventory_center.period_label(p['warranty_store_qty'], p['warranty_store_unit']) + (' · ' + inventory_center.STARTS[p['warranty_store_from']].lower() if p['warranty_store_qty'] else '')
        p['maker_label'] = inventory_center.period_label(p['warranty_maker_qty'], p['warranty_maker_unit']) + (' · ' + inventory_center.STARTS[p['warranty_maker_from']].lower() if p['warranty_maker_qty'] else '')
        p['units'] = [u for u in units if u['item_id'] == p['item_id']]
    return {'units': units, 'products': products}


def warranty_pdf(c, invoice_id):
    """Certificado de garantías de los productos facturados: una ficha por unidad con la garantía de PC-DOCTOR y la del fabricante."""
    data = invoicing.detail(c, invoice_id)
    inv = data['invoice']
    rows = warranty_rows(c, invoice_id)
    if not rows['units'] and not any(p['warranty_store_qty'] or p['warranty_maker_qty'] for p in rows['products']):
        return None
    page = Page('Garantías · factura ' + (inv['number'] or str(invoice_id)))
    left, right = 40, A4[0] - 40
    entries = []
    for unit in rows['units']:
        cover = lambda key, label: label + ': ' + (('del %s al %s' % (dmy(unit[key + '_warranty_from']), dmy(unit[key + '_warranty_to']))) if unit[key + '_warranty_to'] else
                                                    'comienza con la entrega' if unit['sold_at'] and not unit['delivered_at'] else 'sin garantía')
        entries.append([(unit['name'], 10, True), ('Marca: %s · Modelo: %s · SKU: %s' % (unit['brand'] or '—', unit['model'] or '—', unit['sku'] or '—'), 8, False),
                        ('Código interno: %s · Serie original: %s' % (unit['internal_code'], unit['serial'] or 'sin serie del fabricante'), 8, False),
                        (cover('store', 'Garantía de PC-DOCTOR'), 8.5, True), (cover('maker', 'Garantía del fabricante'), 8.5, False)])
    for p in rows['products']:
        if p['tracking'] == 'granel' and (p['warranty_store_qty'] or p['warranty_maker_qty']):
            entries.append([(p['name'], 10, True), ('Marca: %s · Modelo: %s · SKU: %s · Cantidad: %d' % (p['brand'] or '—', p['model'] or '—', p['sku'] or '—', p['quantity']), 8, False),
                            ('Garantía de PC-DOCTOR: ' + p['store_label'], 8.5, True), ('Garantía del fabricante: ' + p['maker_label'], 8.5, False)])
    pages, layout, y = 1, [], 150
    for entry in entries:
        h = 14 + sum(s + 4 for _, s, _ in entry)
        if y + h > A4[1] - 80:
            pages, y = pages + 1, 120
        layout.append((pages, y, entry, h))
        y += h + 8
    for number in range(1, pages + 1):
        page.pdf.page()
        page.rect(0, 0, page.w, 100, fill=(.96, .97, .99), stroke=None)
        page.rect(0, 100, page.w, 2.2, fill=(.84, .23, .29), stroke=None)
        page.pdf.logo(left, 22, 84)
        page.pdf.text('Certificado de garantías', 140, 30, 14, True, BLUE)
        page.pdf.text('Factura %s · %s · %s' % (inv['number'] or 'sin número', dmy(inv['issue_date']), 'CONSUMIDOR FINAL' if inv['consumer_final'] else inv['buyer_name'] or '—'), 140, 50, 9, False, INK)
        page.pdf.text('La garantía de PC-DOCTOR y la del fabricante son independientes; cada una se cuenta desde su fecha de inicio.', 140, 64, 8, False, GRAY)
        if number == 1:
            page.pdf.text('Productos cubiertos', left, 122, 11, True, BLUE)
        for p, y0, entry, h in layout:
            if p != number:
                continue
            page.rect(left, y0, right - left, h, fill=(1, 1, 1))
            yy = y0 + 8
            for text, size, bold in entry:
                page.pdf.text(page.pdf.wrap(text, right - left - 20, size)[0], left + 10, yy, size, bold, BLUE if size == 10 else INK)
                yy += size + 4
        test = inv['environment'] != '2' or inv['status'] != 'autorizado'
        _footer(page, number, pages, 'FACTURA DE PRUEBA — SIN VALIDEZ TRIBUTARIA' if test else '')
    return page.pdf.finish()


# ---- Paquete y envío ------------------------------------------------------------------------------------------------------

def package(c, invoice_id):
    """Adjuntos del correo de una factura: RIDE, XML autorizado (si existe), políticas asociadas a la factura y garantías (si hay)."""
    data = invoicing.detail(c, invoice_id)
    inv = data['invoice']
    if not inv['access_key']:
        raise DocumentError('La factura todavía no se emitió.', 409)
    files = [{'name': __import__('document_style').filename('FACTURA', inv['number']), 'type': 'application/pdf', 'data': base64.b64encode(ride_pdf(c, invoice_id)).decode()}]
    row = c.execute('SELECT xml_authorized FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if inv['status'] == 'autorizado' and row['xml_authorized']:
        files.append({'name': 'FACTURA-%s.xml' % inv['number'], 'type': 'application/xml', 'data': base64.b64encode(row['xml_authorized'].encode('utf-8')).decode()})
    linked = invoice_policies(c, invoice_id)
    ctx = dict(inv, test=inv['environment'] != '2' or inv['status'] != 'autorizado')
    for policy in linked:
        files.append({'name': 'POLITICAS-%s-%s.pdf' % (policy['code'], policy['version']), 'type': 'application/pdf', 'data': base64.b64encode(policy_pdf(policy, ctx)).decode()})
    warranty = warranty_pdf(c, invoice_id)
    if warranty:
        files.append({'name': 'GARANTIAS-%s.pdf' % inv['number'], 'type': 'application/pdf', 'data': base64.b64encode(warranty).decode()})
    return {'invoice': inv, 'files': files, 'policies': linked, 'policy_id': linked[0]['id'] if linked else None}


def mail_log(c, invoice_id):
    rows = [dict(r) for r in c.execute("SELECT m.*,COALESCE(u.name,'Sistema') actor FROM invoice_mail m LEFT JOIN users u ON u.id=m.actor_id WHERE m.invoice_id=? ORDER BY m.id DESC", (invoice_id,))]
    for r in rows:
        r['attachments'] = json.loads(r['attachments'] or '[]')
    return rows


def _body(inv, kind, files):
    names = '\n'.join('- ' + f['name'] for f in files)
    if kind == 'prueba':
        return ('PRUEBA — SIN VALIDEZ TRIBUTARIA\n\nEste mensaje es una prueba interna de los documentos de facturación de Órdenes Pro. La factura %s es de prueba: no fue autorizada por '
                'el SRI y no es un comprobante válido.\n\nAdjuntos de la prueba:\n%s' % (inv['number'], names))
    who = 'CONSUMIDOR FINAL' if inv['consumer_final'] else inv['buyer_name']
    return ('Estimado(a) %s:\n\nAdjuntamos los documentos de su factura N.º %s del %s por %s:\n%s\n\nGracias por confiar en PC-DOCTOR S.A.' %
            (who, inv['number'], dmy(inv['issue_date']), usd(inv['total_cents']), names))


def send(c, invoice_id, kind, user, now, deliver, recipient=''):
    """Envía los documentos de una factura.

    - «cliente»: automático, una sola vez por factura y solo si está AUTORIZADA en producción; un error se reintenta hasta MAX_TRIES veces.
    - «reenvio»: manual, solo de facturas autorizadas (queda registrado cada reenvío).
    - «prueba»: a la dirección de prueba configurada; cualquier factura emitida, marcada como PRUEBA y sin validez tributaria.
    `deliver(kind_mail, title, recipient, subject, body, attachments)` es el envío institucional (archiva, sigue la entrega y lanza el error)."""
    import mail_pro
    data = invoicing.detail(c, invoice_id)
    inv = data['invoice']
    authorized = inv['status'] == 'autorizado' and inv['environment'] == '2' and not invoicing.TEST_MODE
    if kind in ('cliente', 'reenvio') and not authorized:
        raise DocumentError('Solo se envían al cliente facturas autorizadas por el SRI. Esta factura es de prueba o no está autorizada: usa «Enviar prueba».', 409)
    if kind == 'prueba':
        recipient = settings(c)['test_recipient']
        if not recipient:
            raise DocumentError('Configura primero la dirección de prueba en Facturación › Configuración.', 409, {'test_recipient': 'Sin dirección de prueba.'})
        if not inv['access_key']:
            raise DocumentError('La factura todavía no se emitió.', 409)
    elif kind in ('cliente', 'reenvio'):
        recipient = str(recipient or inv['buyer_email'] or '').strip()
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(\.[^\s@<>.]+)+', recipient):
            raise DocumentError('La factura no tiene un correo válido del comprador.', 409)
    else:
        raise DocumentError('Tipo de envío no válido.')
    row = None
    if kind == 'cliente':
        row = c.execute("SELECT * FROM invoice_mail WHERE invoice_id=? AND kind='cliente'", (invoice_id,)).fetchone()
        if row and row['status'] in ('enviado', 'enviando', 'sin_confirmacion'):
            return dict(row, skipped=True)  # una sola vez por factura (y nunca dos envíos a la vez)
        if row and row['attempts'] >= MAX_TRIES:
            raise DocumentError('Se agotaron los %d intentos automáticos: revisa el error y usa «Reenviar».' % MAX_TRIES, 409)
    pkg = package(c, invoice_id)
    names = json.dumps([f['name'] for f in pkg['files']], ensure_ascii=False)
    if row:
        c.execute("UPDATE invoice_mail SET status='enviando',attempts=attempts+1,attachments=?,recipient=?,updated_at=? WHERE id=?", (names, recipient, stamp(now), row['id']))
        mail_id = row['id']
    else:
        mail_id = c.execute("INSERT INTO invoice_mail(invoice_id,kind,recipient,status,attachments,policy_id,actor_id,created_at,updated_at) VALUES (?,?,?,'enviando',?,?,?,?,?)",
                            (invoice_id, kind, recipient, names, pkg['policy_id'], user['id'] if user else None, stamp(now), stamp(now))).lastrowid
    c.commit()  # el intento queda registrado antes de hablar con el servidor de correo
    subject = ('[PRUEBA — SIN VALIDEZ TRIBUTARIA] ' if kind == 'prueba' else '') + 'PC-DOCTOR S.A. | Factura N.º ' + inv['number']
    try:
        deliver('invoice', 'Documentos de su factura' if kind != 'prueba' else 'Prueba de documentos de facturación', recipient, subject, _body(inv, kind, pkg['files']), pkg['files'])
    except mail_pro.MailError as error:
        status = 'sin_confirmacion' if getattr(error, 'kind', '') == 'sin_confirmacion' else 'error'
        c.execute('UPDATE invoice_mail SET status=?,detail=?,updated_at=? WHERE id=?', (status, str(error)[:500], stamp(now), mail_id))
        c.commit()
        raise DocumentError('No se pudo enviar: ' + str(error), 502)
    c.execute("UPDATE invoice_mail SET status='enviado',detail=?,updated_at=? WHERE id=?", ('El servidor de correo aceptó el mensaje.', stamp(now), mail_id))
    c.commit()
    return dict(c.execute('SELECT * FROM invoice_mail WHERE id=?', (mail_id,)).fetchone())


def on_authorized(c, invoice_id, user, now, deliver):
    """Punto de enganche para cuando el SRI autorice una factura: envía los documentos al cliente si el adjunto automático está activo.
    Un fallo de correo no deshace la autorización: queda registrado para reintentar."""
    if not settings(c)['auto']:
        return None
    try:
        return send(c, invoice_id, 'cliente', user, now, deliver)
    except DocumentError as error:
        return {'error': str(error)}
