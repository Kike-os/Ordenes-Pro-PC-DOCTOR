"""Ingreso de mercadería por proveedor: factura electrónica XML del SRI, comprobante adjunto o sin factura, y corrección de lo registrado.

- Lo que no está confirmado (borrador) se edita, se quita o se descarta sin tocar las existencias.
- Lo confirmado nunca se borra: se corrige con movimientos controlados del Kardex (reversos por partida, ajustes de costo auditados).
- El XML se lee sin resolver entidades externas ni DTD, y no se consulta al SRI: se comprueba su estructura, la autorización que trae,
  el dígito verificador de la clave de acceso y que los totales cuadren. La vista previa no escribe nada."""
import hashlib
import json
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.etree import ElementTree

import inventory
from inventory import InventoryError, event, stamp

MAX_XML_BYTES = 1_000_000
MAX_LINES = 300
SOURCES = {'manual': 'Registro manual', 'xml': 'Factura electrónica XML', 'comprobante': 'Comprobante adjunto', 'sin_factura': 'Sin factura adjunta'}


# ---- Lectura del XML ------------------------------------------------------------------------------------------------------------------

def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _find(node, name):
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _text(node, name, default=''):
    found = _find(node, name) if node is not None else None
    return (found.text or '').strip() if found is not None and found.text else default


def _parse(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise InventoryError('El archivo tiene declaraciones no permitidas: no se procesa.', 400, {'file': 'XML no admitido.'})
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise InventoryError('El archivo no es un XML válido.', 400, {'file': 'XML no válido.'})


def _decimal(value, field):
    try:
        return Decimal(str(value or '0').strip().replace(',', '.'))
    except InvalidOperation:
        raise InventoryError('El XML tiene un valor no numérico en %s.' % field, 400, {'file': 'Valor no válido.'})


def _cents(value):
    return int((value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def access_key_valid(key):
    """Dígito verificador de la clave de acceso del SRI (módulo 11 sobre los primeros 48 dígitos)."""
    if not re.fullmatch(r'\d{49}', key or ''):
        return False
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(key[:48])))
    check = 11 - total % 11
    return int(key[48]) == (0 if check == 11 else 1 if check == 10 else check)


def parse_invoice(raw):
    """Datos de la factura. Acepta el XML autorizado (con su sobre de autorización) o el comprobante solo, que queda señalado."""
    if not raw or len(raw) > MAX_XML_BYTES:
        raise InventoryError('El XML debe pesar hasta 1 MB.', 400, {'file': 'Tamaño no admitido.'})
    root = _parse(raw)
    warnings = []
    authorized = False
    state = number = when = ''
    envelope = root if _local(root.tag) == 'autorizacion' else _find(root, 'autorizacion')
    invoice = root if _local(root.tag) == 'factura' else None
    if envelope is not None:
        state = _text(envelope, 'estado').upper()
        number = _text(envelope, 'numeroAutorizacion')
        when = _text(envelope, 'fechaAutorizacion')
        if state and state != 'AUTORIZADO':
            raise InventoryError('El SRI no autorizó este comprobante (estado: %s). No se importa.' % state, 409, {'file': 'No autorizado.'})
        authorized = state == 'AUTORIZADO'
        holder = _find(envelope, 'comprobante')
        if holder is not None and (holder.text or '').strip():
            inner = holder.text.strip().encode('utf-8')
            invoice = _parse(inner)
    if invoice is None:
        invoice = _find(root, 'factura')
    if invoice is None or _local(invoice.tag) != 'factura':
        raise InventoryError('Este XML no es una factura electrónica del SRI.', 400, {'file': 'No es una factura.'})
    tax_info, head = _find(invoice, 'infoTributaria'), _find(invoice, 'infoFactura')
    if tax_info is None or head is None:
        raise InventoryError('La factura no tiene la estructura del SRI (faltan sus datos tributarios).', 400, {'file': 'Estructura no válida.'})
    if _text(tax_info, 'codDoc', '01') != '01':
        raise InventoryError('Este comprobante no es una factura (código %s).' % _text(tax_info, 'codDoc'), 400, {'file': 'No es una factura.'})
    key = _text(tax_info, 'claveAcceso')
    if not access_key_valid(key):
        raise InventoryError('La clave de acceso de la factura no es válida.', 400, {'file': 'Clave de acceso no válida.'})
    ruc = _text(tax_info, 'ruc')
    if not re.fullmatch(r'\d{13}', ruc):
        raise InventoryError('El RUC del proveedor no es válido en el XML.', 400, {'file': 'RUC no válido.'})
    if not authorized:
        warnings.append('El XML no trae la autorización del SRI: verifica la clave de acceso en el portal del SRI antes de confirmar.')
    if _text(tax_info, 'ambiente') == '1':
        warnings.append('La factura es del ambiente de PRUEBAS del SRI: no tiene validez tributaria.')
    document = '%s-%s-%s' % (_text(tax_info, 'estab'), _text(tax_info, 'ptoEmi'), _text(tax_info, 'secuencial'))
    if not re.fullmatch(r'\d{3}-\d{3}-\d{9}', document):
        raise InventoryError('El número de la factura no es válido en el XML.', 400, {'file': 'Número no válido.'})
    try:
        issue = datetime.strptime(_text(head, 'fechaEmision'), '%d/%m/%Y').date()
    except ValueError:
        raise InventoryError('La fecha de emisión no es válida en el XML.', 400, {'file': 'Fecha no válida.'})
    lines = []
    details = [n for n in invoice.iter() if _local(n.tag) == 'detalle']
    if not details:
        raise InventoryError('La factura no tiene productos.', 400, {'file': 'Sin productos.'})
    if len(details) > MAX_LINES:
        raise InventoryError('La factura supera las %d líneas admitidas.' % MAX_LINES, 400, {'file': 'Demasiadas líneas.'})
    subtotal = Decimal(0)
    tax_total = Decimal(0)
    for n, node in enumerate(details):
        qty = _decimal(_text(node, 'cantidad'), 'la cantidad')
        unit = _decimal(_text(node, 'precioUnitario'), 'el precio')
        discount = _decimal(_text(node, 'descuento'), 'el descuento')
        total = _decimal(_text(node, 'precioTotalSinImpuesto'), 'el total de línea')
        if qty <= 0:
            raise InventoryError('La línea %d del XML tiene una cantidad no válida.' % (n + 1), 400, {'file': 'Cantidad no válida.'})
        rate = 0
        other_tax = False
        line_tax = Decimal(0)
        for tax in (x for x in node.iter() if _local(x.tag) == 'impuesto'):
            value = _decimal(_text(tax, 'valor'), 'el impuesto')
            line_tax += value
            if _text(tax, 'codigo') == '2':
                rate = int((_decimal(_text(tax, 'tarifa'), 'la tarifa') * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            elif value:
                other_tax = True
        whole = qty == qty.to_integral_value()
        subtotal += total
        tax_total += line_tax
        lines.append({'line': n, 'code': _text(node, 'codigoPrincipal')[:60], 'aux_code': _text(node, 'codigoAuxiliar')[:60], 'description': re.sub(r'\s+', ' ', _text(node, 'descripcion'))[:300],
                      'quantity': int(qty) if whole else str(qty.normalize()), 'whole_quantity': bool(whole), 'unit_price': str(unit.normalize()), 'discount_cents': _cents(discount),
                      'line_total_cents': _cents(total), 'unit_cost_cents': _cents(total / qty), 'tax_rate_bp': rate, 'tax_cents': _cents(line_tax), 'other_tax': other_tax})
    declared_subtotal = _decimal(_text(head, 'totalSinImpuestos'), 'el subtotal')
    declared_total = _decimal(_text(head, 'importeTotal'), 'el total')
    # Tolerancia de un centavo por línea: el SRI admite redondeos en cada línea.
    tolerance = Decimal('0.01') * max(1, len(lines))
    if abs(subtotal - declared_subtotal) > tolerance:
        warnings.append('La suma de las líneas (%s) no coincide con el subtotal de la factura (%s).' % (inventory.usd(_cents(subtotal)), inventory.usd(_cents(declared_subtotal))))
    if any(not l['whole_quantity'] for l in lines):
        warnings.append('Hay cantidades con decimales: el inventario solo admite cantidades enteras. Excluye esas líneas o indica la cantidad entera.')
    if any(l['other_tax'] for l in lines):
        warnings.append('Hay líneas con otros impuestos (por ejemplo, ICE): no se suman al costo. Revísalas.')
    return {'access_key': key, 'authorized': authorized, 'authorization_number': number or key, 'authorized_at': when, 'environment': 'pruebas' if _text(tax_info, 'ambiente') == '1' else 'produccion',
            'supplier': {'ruc': ruc, 'name': _text(tax_info, 'razonSocial')[:300], 'trade_name': _text(tax_info, 'nombreComercial')[:300], 'address': _text(tax_info, 'dirMatriz')[:300]},
            'buyer_id': _text(head, 'identificacionComprador'), 'buyer_name': _text(head, 'razonSocialComprador'), 'document_number': document, 'issue_date': issue.isoformat(),
            'subtotal_cents': _cents(declared_subtotal), 'discount_cents': _cents(_decimal(_text(head, 'totalDescuento'), 'el descuento')), 'tax_cents': _cents(tax_total), 'total_cents': _cents(declared_total),
            'lines': lines, 'warnings': warnings, 'sha256': hashlib.sha256(raw).hexdigest()}


def _norm(text):
    return re.sub(r'[^a-z0-9 ]+', ' ', str(text or '').lower()).split()


def _suggest(c, supplier_id, line, items):
    """Producto que probablemente corresponde a la línea: el código ya usado con este proveedor, el SKU o código de barras y, por último, el nombre."""
    if supplier_id and line['code']:
        known = c.execute('SELECT item_id FROM supplier_item_codes WHERE supplier_id=? AND code=?', (supplier_id, line['code'])).fetchone()
        if known:
            return {'item_id': known['item_id'], 'why': 'Código de este proveedor'}
    for code in (line['code'], line['aux_code']):
        if code:
            for item in items:
                if code.lower() in (str(item['sku'] or '').lower(), str(item['barcode'] or '').lower()):
                    return {'item_id': item['id'], 'why': 'SKU o código de barras'}
    words = set(_norm(line['description']))
    best, score = None, 0
    for item in items:
        target = set(_norm(item['name']))
        if len(target) >= 2 and target <= words and len(target) > score:
            best, score = item, len(target)
    return {'item_id': best['id'], 'why': 'Nombre parecido: confírmalo'} if best else None


def _items(c):
    return c.execute('SELECT i.id,i.sku,i.barcode,i.tracking,g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.active=1').fetchall()


def analyze(c, raw):
    """Vista previa de la factura: no escribe nada."""
    data = parse_invoice(raw)
    supplier = c.execute('SELECT id,name,identification,active FROM suppliers WHERE identification=?', (data['supplier']['ruc'],)).fetchone()
    data['supplier_match'] = dict(supplier) if supplier else None
    same_name = None
    if not supplier:
        wanted = _norm(data['supplier']['name'])
        same_name = next((dict(r) for r in c.execute('SELECT id,name,identification,active FROM suppliers') if _norm(r['name']) == wanted), None)
    data['supplier_same_name'] = same_name
    duplicate = c.execute("SELECT id,document_number,status FROM purchases WHERE access_key=? AND status!='anulada'", (data['access_key'],)).fetchone()
    if not duplicate and supplier:
        duplicate = c.execute("SELECT id,document_number,status FROM purchases WHERE supplier_id=? AND document_number=? AND status!='anulada'", (supplier['id'], data['document_number'])).fetchone()
    data['duplicate'] = dict(duplicate) if duplicate else None
    own = _own_ruc(c)
    if own and data['buyer_id'] and data['buyer_id'] != own:
        data['warnings'].append('La factura está a nombre de otro comprador (%s).' % data['buyer_id'])
    items = _items(c)
    for line in data['lines']:
        line['suggestion'] = _suggest(c, supplier['id'] if supplier else None, line, items)
    return data


def _own_ruc(c):
    row = c.execute('SELECT ruc FROM invoice_settings WHERE id=1').fetchone()
    return (row['ruc'] if row else '') or ''


def create_from_xml(c, raw, data, user, now):
    """Crea el ingreso a partir de la factura, con los productos que el usuario relacionó. Si se pide confirmar, actualiza existencias y Kardex."""
    parsed = analyze(c, raw)
    if parsed['duplicate']:
        raise InventoryError('Esta factura ya está registrada (%s, %s).' % (parsed['duplicate']['document_number'], inventory.PURCHASE_STATUS[parsed['duplicate']['status']].lower()), 409,
                             {'file': 'Factura duplicada.'})
    supplier = parsed['supplier_match']
    if not supplier:
        chosen = str(data.get('supplier_id', '') or '')
        if chosen.isdigit():
            supplier = c.execute('SELECT id,name,identification,active FROM suppliers WHERE id=?', (int(chosen),)).fetchone()
            if not supplier:
                raise InventoryError('Proveedor no encontrado.', 404)
            if supplier['identification'] and supplier['identification'] != parsed['supplier']['ruc']:
                raise InventoryError('El RUC de la factura (%s) no coincide con el del proveedor elegido (%s).' % (parsed['supplier']['ruc'], supplier['identification']), 409, {'supplier_id': 'RUC distinto.'})
            if not supplier['identification']:
                c.execute('UPDATE suppliers SET identification=?,updated_at=?,updated_by=? WHERE id=?', (parsed['supplier']['ruc'], stamp(now), user['id'], supplier['id']))
                event(c, now, user, 'proveedor_editado', 'RUC %s tomado de la factura %s.' % (parsed['supplier']['ruc'], parsed['document_number']), supplier_id=supplier['id'])
        elif str(data.get('create_supplier', '')) == '1':
            new_id = inventory.save_supplier(c, {'name': parsed['supplier']['name'], 'identification': parsed['supplier']['ruc'], 'address': parsed['supplier']['address']}, user, now)
            supplier = {'id': new_id, 'active': 1}
        else:
            raise InventoryError('Elige el proveedor o créalo con los datos de la factura.', fields={'supplier_id': 'Proveedor obligatorio.'})
    elif not supplier['active']:
        raise InventoryError('El proveedor de la factura está desactivado: actívalo primero.', 409, {'supplier_id': 'Proveedor inactivo.'})
    try:
        mapping = json.loads(str(data.get('mapping', '[]')))
        assert isinstance(mapping, list)
    except (ValueError, AssertionError):
        raise InventoryError('Revisa los productos de la factura.', fields={'mapping': 'Datos no válidos.'})
    chosen_lines = {int(m['line']): m for m in mapping if isinstance(m, dict) and str(m.get('line', '')).isdigit()}
    lines = []
    for line in parsed['lines']:
        choice = chosen_lines.get(line['line'])
        if not choice:
            raise InventoryError('Relaciona o excluye la línea %d: %s.' % (line['line'] + 1, line['description'][:60]), fields={'mapping': 'Línea sin relacionar.'})
        if choice.get('skip'):
            continue
        qty = choice.get('quantity') if str(choice.get('quantity', '') or '') else line['quantity']
        if not line['whole_quantity'] and not str(choice.get('quantity', '') or ''):
            raise InventoryError('La línea %d tiene una cantidad con decimales: indica la cantidad entera o exclúyela.' % (line['line'] + 1), fields={'mapping': 'Cantidad no entera.'})
        lines.append({'item_id': choice.get('item_id'), 'quantity': str(qty), 'unit_cost': '%d.%02d' % divmod(line['unit_cost_cents'] if line['whole_quantity'] else line['line_total_cents'] // max(1, int(qty)), 100),
                      'tax_rate_bp': line['tax_rate_bp'], 'description': line['description'], 'supplier_code': line['code'] or line['aux_code'], 'discount_cents': line['discount_cents'],
                      'serials': choice.get('serials', []), 'location': choice.get('location', ''), 'sale_price': choice.get('sale_price', '')})
    if not lines:
        raise InventoryError('Relaciona al menos un producto de la factura.', fields={'mapping': 'Sin productos.'})
    purchase_id = inventory.save_purchase(c, {'supplier_id': str(supplier['id']), 'document_number': parsed['document_number'], 'issue_date': parsed['issue_date'], 'items': json.dumps(lines), 'notes': data.get('notes', ''), 'source': 'xml',
                                              'access_key': parsed['access_key'], 'authorization_number': parsed['authorization_number'] if parsed['authorized'] else '', 'authorized_at': parsed['authorized_at'],
                                              'xml_total_cents': parsed['total_cents']}, user, now)
    c.execute('INSERT INTO purchase_files(supplier_id,purchase_id,kind,name,mime,size,sha256,data,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
              (supplier['id'], purchase_id, 'xml', _file_name(data.get('name')) or parsed['document_number'] + '.xml', 'application/xml', len(raw), parsed['sha256'], raw, user['id'], stamp(now)))
    if str(data.get('confirm', '')) == '1':
        inventory.receive(c, purchase_id, user, now)
    return purchase_id


def _file_name(name):
    return re.sub(r'[^\w.\- ()]', '_', str(name or ''))[:120]


# ---- Adjuntos -------------------------------------------------------------------------------------------------------------------------

def attach(c, purchase_id, data, user, now):
    """Adjunta la foto o el PDF del comprobante, también después de confirmar el ingreso. Se valida con la subida por partes del sistema (hasta 5 MB)."""
    row = inventory._purchase(c, purchase_id)
    if row['status'] == 'anulada':
        raise InventoryError('El ingreso está descartado.', 409)
    file_id, name = _store(c, row['supplier_id'], row['id'], 'comprobante', data, user, now)
    if row['source'] in ('sin_factura', 'manual'):
        c.execute("UPDATE purchases SET source='comprobante' WHERE id=?", (row['id'],))
    event(c, now, user, 'compra_adjunto', 'Comprobante adjunto al ingreso %s: %s.' % (row['document_number'], name), purchase_id=row['id'], supplier_id=row['supplier_id'])
    return file_id


def attach_supplier(c, supplier_id, data, user, now):
    """Documento de respaldo del proveedor, sin relación con una compra (contrato, RUC, catálogo)."""
    row = _supplier(c, supplier_id)
    file_id, name = _store(c, row['id'], None, 'respaldo', data, user, now)
    event(c, now, user, 'proveedor_documento', 'Documento agregado: %s.' % name, supplier_id=row['id'])
    return file_id


def _supplier(c, supplier_id):
    row = c.execute('SELECT * FROM suppliers WHERE id=?', (supplier_id,)).fetchone() if str(supplier_id).isdigit() else None
    if not row:
        raise InventoryError('Proveedor no encontrado.', 404)
    return row


def _store(c, supplier_id, purchase_id, kind, data, user, now):
    import cash
    upload_id = str(data.get('upload_id', '') or '')
    try:
        raw, mime, name = cash._assemble(c, user, upload_id, str(data.get('file_name', '') or ''))
    except cash.CashError as error:
        raise InventoryError(str(error), error.status, error.fields)
    sha = hashlib.sha256(raw).hexdigest()
    if c.execute("SELECT 1 FROM purchase_files WHERE supplier_id=? AND sha256=? AND discarded_at=''", (supplier_id, sha)).fetchone():
        raise InventoryError('Ese archivo ya está adjunto a este proveedor.', 409, {'file': 'Archivo repetido.'})
    file_id = c.execute('INSERT INTO purchase_files(supplier_id,purchase_id,kind,name,mime,size,sha256,data,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (supplier_id, purchase_id, kind, name, mime, len(raw), sha, raw, user['id'], stamp(now))).lastrowid
    c.execute('DELETE FROM cash_upload_parts WHERE upload_id=?', (upload_id,))
    return file_id, name


def discard_file(c, file_id, reason, user, now):
    found = c.execute("SELECT * FROM purchase_files WHERE id=? AND discarded_at=''", (file_id,)).fetchone() if str(file_id).isdigit() else None
    if not found:
        raise InventoryError('Adjunto no disponible.', 404)
    if found['kind'] == 'xml':
        raise InventoryError('El XML es el respaldo de la importación: para quitarlo, descarta el ingreso.', 409)
    reason = _reason(reason)
    c.execute('UPDATE purchase_files SET discarded_at=?,discarded_by=?,discard_reason=? WHERE id=?', (stamp(now), user['id'], reason, found['id']))
    event(c, now, user, 'compra_adjunto', 'Adjunto %s descartado: %s' % (found['name'], reason), purchase_id=found['purchase_id'], supplier_id=found['supplier_id'])


def file_for(c, file_id):
    row = c.execute('SELECT name,mime,data FROM purchase_files WHERE id=?', (file_id,)).fetchone() if str(file_id).isdigit() else None
    if not row:
        raise InventoryError('Adjunto no disponible.', 404)
    return row['name'], row['mime'], bytes(row['data'])


def files_of(c, purchase_id=None, supplier_id=None):
    where, value = ('f.purchase_id=?', purchase_id) if purchase_id else ('f.supplier_id=?', supplier_id)
    return [dict(r) for r in c.execute("SELECT f.id,f.purchase_id,f.kind,f.name,f.mime,f.size,f.created_at,COALESCE(u.name,'') actor,COALESCE(p.document_number,'') document FROM purchase_files f LEFT JOIN users u ON u.id=f.created_by "
                                       "LEFT JOIN purchases p ON p.id=f.purchase_id WHERE f.discarded_at='' AND " + where + ' ORDER BY f.id DESC', (value,))]


def _reason(value):
    reason = re.sub(r'\s+', ' ', str(value or '')).strip()[:300]
    if len(reason) < 5:
        raise InventoryError('Indica el motivo (al menos 5 caracteres).', fields={'reason': 'Motivo obligatorio.'})
    return reason


# ---- Corrección de un ingreso ----------------------------------------------------------------------------------------------------------

def update_header(c, purchase_id, data, user, now):
    """Datos del documento de un ingreso ya confirmado (número, fecha, observaciones). El proveedor y una factura XML no cambian; queda constancia."""
    row = inventory._purchase(c, purchase_id)
    if row['status'] != 'recibida':
        raise InventoryError('Esta acción es para ingresos confirmados.', 409)
    if row['source'] == 'xml':
        raise InventoryError('Los datos de una factura electrónica vienen del XML: no se editan.', 409)
    number = re.sub(r'\s', '', str(data.get('document_number', '')))[:40]
    if not re.fullmatch(r'[A-Za-z0-9-]{1,40}', number):
        raise InventoryError('Revisa el número del documento.', fields={'document_number': 'Número no válido.'})
    if c.execute("SELECT 1 FROM purchases WHERE supplier_id=? AND document_number=? AND status!='anulada' AND id!=?", (row['supplier_id'], number, row['id'])).fetchone():
        raise InventoryError('Ese documento de este proveedor ya está registrado.', 409, {'document_number': 'Documento repetido.'})
    try:
        issue = date.fromisoformat(str(data.get('issue_date', '')))
        if issue > now.date():
            raise ValueError
    except ValueError:
        raise InventoryError('Revisa la fecha del documento.', fields={'issue_date': 'Fecha no válida.'})
    notes = re.sub(r'\s+', ' ', str(data.get('notes', ''))).strip()[:500]
    changes = [('%s: %s → %s' % (label, old, new)) for label, old, new in (('Documento', row['document_number'], number), ('Fecha', row['issue_date'], issue.isoformat()), ('Observaciones', row['notes'] or '—', notes or '—')) if old != new]
    if not changes:
        return row['id']
    source = 'manual' if row['source'] == 'sin_factura' and not number.startswith('SF-') else row['source']  # ya tiene documento
    c.execute('UPDATE purchases SET document_number=?,issue_date=?,notes=?,source=? WHERE id=?', (number, issue.isoformat(), notes, source, row['id']))
    event(c, now, user, 'compra_editada', 'Datos del ingreso corregidos. ' + ' · '.join(changes), purchase_id=row['id'], supplier_id=row['supplier_id'])
    return row['id']


def _line(c, purchase_id, line_id):
    row = c.execute('SELECT * FROM purchase_items WHERE id=? AND purchase_id=?', (line_id, purchase_id)).fetchone() if str(line_id).isdigit() else None
    if not row:
        raise InventoryError('Partida no encontrada.', 404)
    return row


def reversed_qty(c, line_id):
    return c.execute('SELECT COALESCE(SUM(quantity),0) FROM purchase_reversals WHERE purchase_item_id=?', (line_id,)).fetchone()[0]


def _line_movement(c, purchase, line):
    if line['movement_id']:
        return line['movement_id']
    row = c.execute("SELECT id FROM inventory_movements WHERE reference_kind='compra_linea' AND reference_id=? AND direction=1", (line['id'],)).fetchone() or c.execute(
        "SELECT id FROM inventory_movements WHERE reference_kind='compra' AND reference_id=? AND item_id=? AND direction=1", (purchase['id'], line['item_id'])).fetchone()
    return row['id'] if row else None


def reverse_line(c, purchase_id, line_id, qty, unit_ids, reason, user, now):
    """Revierte con un movimiento de salida lo ingresado por error en una partida confirmada (toda o parte). Solo salen unidades aún disponibles,
    y su serie queda libre para volver a ingresarla bien. No toca las demás partidas ni el resto del inventario."""
    row = inventory._purchase(c, purchase_id)
    if row['status'] != 'recibida':
        raise InventoryError('Solo se revierte lo ya confirmado. En un borrador, quita la partida y guarda.', 409)
    line = _line(c, row['id'], line_id)
    reason = _reason(reason)
    left = line['quantity'] - reversed_qty(c, line['id'])
    amount = inventory.quantity(qty)
    if left <= 0:
        raise InventoryError('Esta partida ya fue revertida por completo.', 409)
    if amount > left:
        raise InventoryError('Solo quedan %d por revertir en esta partida.' % left, fields={'quantity': 'Supera lo ingresado.'})
    item = inventory._item_row(c, line['item_id'])
    picked = None
    entry = _line_movement(c, row, line)
    if item['tracking'] == 'serie':
        free = [u['id'] for u in c.execute("SELECT id FROM inventory_units WHERE entry_movement_id=? AND status='disponible' ORDER BY id", (entry or 0,))]
        wanted = [int(u) for u in (str(unit_ids).split(',') if isinstance(unit_ids, str) else unit_ids or []) if str(u).strip().isdigit()]
        if wanted:
            if any(u not in free for u in wanted):
                raise InventoryError('Una de las unidades elegidas ya no está disponible o no pertenece a este ingreso.', 409, {'units': 'Unidad no válida.'})
            picked = wanted
        else:
            if len(free) < amount:
                raise InventoryError('No se puede revertir: ya salieron unidades de esta compra (%d de %d disponibles).' % (len(free), amount), 409)
            picked = free[:amount]
        if len(picked) != amount:
            raise InventoryError('Elige %d unidades.' % amount, fields={'units': 'Cantidad distinta.'})
    reversal = c.execute('INSERT INTO purchase_reversals(purchase_id,purchase_item_id,quantity,reason,created_by,created_at) VALUES (?,?,?,?,?,?)', (row['id'], line['id'], amount, reason, user['id'], stamp(now))).lastrowid
    movement = inventory.move(c, item['id'], -1, 'anulacion_compra', str(amount), '0', user, now, 'compra_reverso', reversal, 'Reverso de la compra %s: %s' % (row['document_number'], reason), unit_ids=picked)
    # purchase_reversals es inmutable: el movimiento se enlaza por su referencia (compra_reverso, id del reverso).
    for unit_id in picked or []:
        unit = c.execute('SELECT serial,internal_code FROM inventory_units WHERE id=?', (unit_id,)).fetchone()
        c.execute("UPDATE inventory_units SET serial_key='' WHERE id=?", (unit_id,))
        event(c, now, user, 'unidad_revertida', 'Unidad %s (serie %s) retirada por reverso de la compra %s: %s' % (unit['internal_code'], unit['serial'] or 'sin serie', row['document_number'], reason), item['id'], unit_id=unit_id, purchase_id=row['id'])
    event(c, now, user, 'compra_revertida', 'Reverso de %d × %s en la compra %s: %s' % (amount, item['name'], row['document_number'], reason), item['id'], purchase_id=row['id'], supplier_id=row['supplier_id'])
    return movement


def correct_line_cost(c, purchase_id, line_id, cost, reason, user, now):
    """Corrige el costo de una partida confirmada: el movimiento original no cambia, la corrección queda auditada y el Kardex usa el costo corregido.
    Las ventas ya realizadas conservan su precio."""
    import inventory_center as center
    row = inventory._purchase(c, purchase_id)
    if row['status'] != 'recibida':
        raise InventoryError('Solo se corrige el costo de lo confirmado. En un borrador, edita la partida.', 409)
    line = _line(c, row['id'], line_id)
    movement = _line_movement(c, row, line)
    if not movement:
        raise InventoryError('No se encontró el movimiento de esta partida.', 409)
    center.correct_cost(c, movement, cost, reason, user, now, row['document_number'], allow_purchase=True)
    _refresh_totals(c, row['id'])
    event(c, now, user, 'compra_editada', 'Costo corregido en la compra %s: %s' % (row['document_number'], _reason(reason)), line['item_id'], purchase_id=row['id'], supplier_id=row['supplier_id'])


def _refresh_totals(c, purchase_id):
    subtotal = tax = 0
    for line in c.execute('SELECT * FROM purchase_items WHERE purchase_id=?', (purchase_id,)).fetchall():
        movement = _line_movement(c, {'id': purchase_id}, line)
        cost = inventory.corrections(c, line['item_id']).get(movement, line['unit_cost_cents'])
        base = line['quantity'] * cost
        subtotal += base
        tax += (2 * base * line['tax_rate_bp'] + 10000) // 20000
    c.execute('UPDATE purchases SET subtotal_cents=?,tax_cents=?,total_cents=? WHERE id=?', (subtotal, tax, subtotal + tax, purchase_id))


def add_line(c, purchase_id, data, user, now):
    """Agrega a un ingreso confirmado lo que faltó registrar (más cantidad o un producto olvidado): entra al Kardex como una partida más."""
    row = inventory._purchase(c, purchase_id)
    if row['status'] != 'recibida':
        raise InventoryError('En un borrador, agrega la partida y guarda.', 409)
    clean = inventory.clean_line(c, data)
    line = c.execute('INSERT INTO purchase_items(purchase_id,item_id,quantity,unit_cost_cents,tax_rate_bp,description,supplier_code,serials,location,discount_cents,sale_price_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                     (row['id'], *clean)).lastrowid
    inventory.receive_line(c, row, c.execute('SELECT * FROM purchase_items WHERE id=?', (line,)).fetchone(), user, now)
    _refresh_totals(c, row['id'])
    event(c, now, user, 'compra_editada', 'Partida agregada a la compra %s.' % row['document_number'], clean[0], purchase_id=row['id'], supplier_id=row['supplier_id'])
    return line


def reenter(c, purchase_id, user, now):
    """Vuelve a empezar un ingreso descartado: crea un borrador nuevo con sus datos para corregirlos. El anterior queda en el historial."""
    row = inventory._purchase(c, purchase_id)
    if row['status'] != 'anulada':
        raise InventoryError('Primero descarta o revierte este ingreso.', 409)
    if row['source'] == 'xml':
        raise InventoryError('Para una factura XML, vuelve a importar el archivo.', 409)
    lines = c.execute('SELECT * FROM purchase_items WHERE purchase_id=?', (row['id'],)).fetchall()
    number = row['document_number']
    free = not c.execute("SELECT 1 FROM purchases WHERE supplier_id=? AND document_number=? AND status!='anulada'", (row['supplier_id'], number)).fetchone()
    new_id = c.execute('INSERT INTO purchases(supplier_id,document_number,issue_date,status,subtotal_cents,tax_cents,total_cents,notes,created_by,created_at,source) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (row['supplier_id'], number if free else inventory.no_document_number(c, now), row['issue_date'], 'borrador', row['subtotal_cents'], row['tax_cents'], row['total_cents'], row['notes'], user['id'], stamp(now), row['source'])).lastrowid
    for line in lines:
        c.execute('INSERT INTO purchase_items(purchase_id,item_id,quantity,unit_cost_cents,tax_rate_bp,description,supplier_code,serials,location,discount_cents,sale_price_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (new_id, line['item_id'], line['quantity'], line['unit_cost_cents'], line['tax_rate_bp'], line['description'], line['supplier_code'], line['serials'], line['location'], line['discount_cents'], line['sale_price_cents']))
    event(c, now, user, 'compra_guardada', 'Nuevo borrador a partir del ingreso %s (#%d), para volver a registrarlo.' % (number, row['id']), purchase_id=new_id, supplier_id=row['supplier_id'])
    return new_id


# ---- Historial por proveedor y por producto ---------------------------------------------------------------------------------------------

def supplier_sheet(c, supplier_id):
    """Ficha del proveedor: datos, compras con sus productos, productos suministrados con su historial de costos y documentos."""
    supplier = _supplier(c, supplier_id)
    purchases = [dict(r, status_label=inventory.PURCHASE_STATUS[r['status']], source_label=SOURCES.get(r['source'], ''), items=[]) for r in c.execute(
        'SELECT p.id,p.document_number,p.issue_date,p.status,p.source,p.total_cents,p.created_at FROM purchases p WHERE p.supplier_id=? ORDER BY p.issue_date DESC,p.id DESC LIMIT 300', (supplier['id'],))]
    by_id = {p['id']: p for p in purchases}
    prices = {}
    for r in c.execute("SELECT x.*,g.name,p.issue_date,p.document_number,p.status FROM purchase_items x JOIN purchases p ON p.id=x.purchase_id JOIN inventory_items i ON i.id=x.item_id JOIN catalog_items g ON g.id=i.catalog_id "
                       'WHERE p.supplier_id=? ORDER BY p.issue_date,x.id', (supplier['id'],)).fetchall():
        cost = inventory.corrections(c, r['item_id']).get(_line_movement(c, {'id': r['purchase_id']}, r), r['unit_cost_cents'])
        if r['purchase_id'] in by_id:
            by_id[r['purchase_id']]['items'].append({'item_id': r['item_id'], 'name': r['name'], 'quantity': r['quantity'], 'unit_cost_cents': cost, 'reversed': reversed_qty(c, r['id'])})
        if r['status'] == 'recibida':
            entry = prices.setdefault(r['item_id'], {'item_id': r['item_id'], 'name': r['name'], 'quantity': 0, 'history': []})
            entry['quantity'] += r['quantity'] - reversed_qty(c, r['id'])
            entry['last_cost_cents'], entry['last_date'] = cost, r['issue_date']
            entry['history'].append({'date': r['issue_date'], 'document': r['document_number'], 'unit_cost_cents': cost, 'quantity': r['quantity']})
    # Ingresos con este proveedor registrados fuera de una compra (asistente «Registrar mercadería»).
    for r in c.execute("SELECT m.*,g.name FROM inventory_movements m JOIN inventory_items i ON i.id=m.item_id JOIN catalog_items g ON g.id=i.catalog_id WHERE m.supplier_id=? AND m.direction=1 AND m.reference_kind NOT IN ('compra','compra_linea') ORDER BY m.id", (supplier['id'],)).fetchall():
        cost = inventory.corrections(c, r['item_id']).get(r['id'], r['unit_cost_cents'])
        entry = prices.setdefault(r['item_id'], {'item_id': r['item_id'], 'name': r['name'], 'quantity': 0, 'history': []})
        entry['quantity'] += r['quantity']
        entry['last_cost_cents'], entry['last_date'] = cost, r['created_at'][:10]
        entry['history'].append({'date': r['created_at'][:10], 'document': r['document'] or 'Ingreso directo', 'unit_cost_cents': cost, 'quantity': r['quantity']})
    done = [p for p in purchases if p['status'] == 'recibida']
    events = [dict(r) for r in c.execute('SELECT event,detail,actor,created_at FROM inventory_events WHERE supplier_id=? ORDER BY id DESC LIMIT 60', (supplier['id'],))]
    return {'supplier': dict(supplier), 'purchases': purchases, 'products': sorted(prices.values(), key=lambda p: p.get('last_date', ''), reverse=True), 'documents': files_of(c, supplier_id=supplier['id']),
            'count': len(done), 'total_cents': sum(p['total_cents'] for p in done), 'last_date': done[0]['issue_date'] if done else '', 'events': events}


def product_suppliers(c, item_id):
    """Proveedores de un producto (puede tener varios), con su último costo y fecha. Incluye los ingresos registrados sin compra."""
    fixed = inventory.corrections(c, item_id)
    seen = {}
    for row in c.execute("SELECT s.id,s.name,m.id movement,m.quantity,m.unit_cost_cents,m.created_at FROM inventory_movements m JOIN suppliers s ON s.id=m.supplier_id WHERE m.item_id=? AND m.direction=1 ORDER BY m.id", (item_id,)):
        info = seen.setdefault(row['id'], {'id': row['id'], 'name': row['name'], 'quantity': 0})
        info['quantity'] += row['quantity']
        info.update(last_cost_cents=fixed.get(row['movement'], row['unit_cost_cents']), last_date=row['created_at'][:10])
    return sorted(seen.values(), key=lambda s: s['last_date'], reverse=True)


# ---- Unidades: corregir, retirar y volver a ingresar ------------------------------------------------------------------------------------

def unit_lock(c, unit):
    """Por qué una unidad no se puede retirar o corregir. Vacío si está libre."""
    if unit['status'] in ('vendida', 'consumida'):
        return 'está ' + inventory.UNIT_STATUS[unit['status']].lower()
    if unit['invoice_id']:
        return 'está facturada'
    if unit['order_id']:
        return 'está vinculada a una orden técnica'
    if unit['status'] == 'reservada' or unit['reservation_id']:
        return 'está reservada'
    if unit['status'] != 'disponible':
        return 'ya no está disponible (%s)' % inventory.UNIT_STATUS[unit['status']].lower()
    moves = c.execute('SELECT COUNT(*) FROM inventory_movement_units WHERE unit_id=?', (unit['id'],)).fetchone()[0]
    if moves > 1:
        return 'tiene movimientos posteriores a su ingreso'
    return ''


def _unit(c, unit_id):
    row = c.execute('SELECT * FROM inventory_units WHERE id=?', (unit_id,)).fetchone() if str(unit_id).isdigit() else None
    if not row:
        raise InventoryError('Unidad no encontrada.', 404)
    return row


def edit_unit(c, unit_id, data, user, now):
    """Corrige la ubicación de una unidad libre. La serie se corrige con su propia acción, que también valida duplicados."""
    unit = _unit(c, unit_id)
    location = re.sub(r'\s+', ' ', str(data.get('location', '') or '')).strip()[:80]
    if location == unit['location']:
        return unit['id']
    c.execute('UPDATE inventory_units SET location=?,updated_at=?,updated_by=? WHERE id=?', (location, stamp(now), user['id'], unit['id']))
    event(c, now, user, 'unidad_editada', 'Ubicación de %s: %s → %s.' % (unit['internal_code'], unit['location'] or '—', location or '—'), unit['item_id'], unit_id=unit['id'])
    return unit['id']


def _source_purchase(c, unit):
    return c.execute("SELECT m.reference_kind,m.reference_id,x.id line,x.purchase_id FROM inventory_movements m LEFT JOIN purchase_items x ON x.movement_id=m.id WHERE m.id=?", (unit['entry_movement_id'],)).fetchone()


def discard_unit(c, unit_id, reason, user, now):
    """Retira una unidad registrada por error, si nada lo impide. No se borra: sale del inventario con un movimiento y su serie queda libre.
    Si entró por una compra, se registra como reverso de esa partida para que la compra siga cuadrando."""
    unit = _unit(c, unit_id)
    lock = unit_lock(c, unit)
    if lock:
        raise InventoryError('Esta unidad no se puede eliminar: %s.' % lock, 409)
    reason = _reason(reason)
    origin = _source_purchase(c, unit)
    line_id = purchase_id = None
    if origin and origin['line']:
        line_id, purchase_id = origin['line'], origin['purchase_id']
    elif origin and origin['reference_kind'] == 'compra_linea':
        found = c.execute('SELECT id,purchase_id FROM purchase_items WHERE id=?', (origin['reference_id'],)).fetchone()
        line_id, purchase_id = (found['id'], found['purchase_id']) if found else (None, None)
    elif origin and origin['reference_kind'] == 'compra':
        found = c.execute('SELECT id FROM purchase_items WHERE purchase_id=? AND item_id=? LIMIT 1', (origin['reference_id'], unit['item_id'])).fetchone()
        line_id, purchase_id = (found['id'], origin['reference_id']) if found else (None, None)
    if line_id and purchase_id:
        return reverse_line(c, purchase_id, line_id, 1, [unit['id']], reason, user, now)
    movement = inventory.move(c, unit['item_id'], -1, 'ajuste_salida', '1', '0', user, now, 'unidad_retirada', unit['id'], 'Registro incorrecto: ' + reason, unit_ids=[unit['id']])
    c.execute("UPDATE inventory_units SET serial_key='' WHERE id=?", (unit['id'],))
    event(c, now, user, 'unidad_retirada', 'Unidad %s (serie %s) retirada por registro incorrecto: %s' % (unit['internal_code'], unit['serial'] or 'sin serie', reason), unit['item_id'], unit_id=unit['id'])
    return movement


def reenter_unit(c, unit_id, data, user, now):
    """Descarta la unidad equivocada e ingresa la correcta en la misma operación, con su costo y ubicación. Si falla, no queda nada a medias."""
    unit = _unit(c, unit_id)
    serial = inventory.clean_serial(data.get('serial'))
    if not serial:
        raise InventoryError('Escanea o escribe la serie correcta.', fields={'serial': 'Serie obligatoria.'})
    reason = _reason(data.get('reason'))
    entry = c.execute('SELECT supplier_id,document,tax_rate_bp FROM inventory_movements WHERE id=?', (unit['entry_movement_id'],)).fetchone()
    cost = inventory.corrections(c, unit['item_id']).get(unit['entry_movement_id'], unit['unit_cost_cents'])
    discard_unit(c, unit['id'], reason, user, now)
    movement = inventory.move(c, unit['item_id'], 1, 'ajuste_entrada', '1', '%d.%02d' % divmod(cost, 100), user, now, 'unidad_reingreso', unit['id'], 'Reingreso de %s: %s' % (unit['internal_code'], reason),
                              serials=[serial], location=unit['location'], supplier_id=entry['supplier_id'] if entry else None, document=entry['document'] if entry else '', tax_rate_bp=entry['tax_rate_bp'] if entry else 0)
    new = c.execute('SELECT unit_id FROM inventory_movement_units WHERE movement_id=?', (movement,)).fetchone()[0]
    event(c, now, user, 'unidad_reingresada', 'Reemplaza a %s (serie %s).' % (unit['internal_code'], unit['serial'] or 'sin serie'), unit['item_id'], unit_id=new)
    return new


def serial_panel(c, q='', state=''):
    """Control de números de serie: unidades con su estado, si se pueden corregir y las que faltan por serie."""
    where, args = [], []
    if q:
        key = inventory.serial_key(q)
        where.append('(u.serial_key LIKE ? OR u.internal_code LIKE ? OR g.name LIKE ?)')
        args += ['%' + key + '%', '%' + key + '%', '%' + str(q).strip() + '%']
    if state == 'sin_serie':
        where.append("u.serial='' AND u.status IN ('disponible','reservada')")
    elif state in inventory.UNIT_STATUS:
        where.append('u.status=?')
        args.append(state)
    rows = c.execute("SELECT u.*,g.name product,b.name brand,COALESCE(s.name,'') supplier,m.document FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id JOIN catalog_items g ON g.id=i.catalog_id "
                     'LEFT JOIN inventory_brands b ON b.id=i.brand_id LEFT JOIN inventory_movements m ON m.id=u.entry_movement_id LEFT JOIN suppliers s ON s.id=m.supplier_id '
                     + ('WHERE ' + ' AND '.join(where) + ' ' if where else '') + 'ORDER BY u.id DESC LIMIT 300', args).fetchall()
    out = []
    for r in rows:
        lock = unit_lock(c, r)
        out.append({'id': r['id'], 'internal_code': r['internal_code'], 'serial': r['serial'], 'product': r['product'], 'brand': r['brand'] or '', 'status': r['status'], 'status_label': inventory.UNIT_STATUS[r['status']],
                    'location': r['location'], 'supplier': r['supplier'], 'document': r['document'] or '', 'lock': lock, 'serial_lock': serial_lock(r), 'created_at': r['created_at']})
    missing = c.execute("SELECT COUNT(*) FROM inventory_units WHERE serial='' AND status IN ('disponible','reservada')").fetchone()[0]
    return {'rows': out, 'missing': missing, 'statuses': inventory.UNIT_STATUS}


def serial_lock(unit):
    """La serie de una unidad vendida, facturada o vinculada a una orden es parte de esos documentos: no se cambia."""
    if unit['status'] in ('vendida', 'consumida'):
        return 'está ' + inventory.UNIT_STATUS[unit['status']].lower()
    if unit['invoice_id']:
        return 'está facturada'
    if unit['order_id']:
        return 'está vinculada a una orden técnica'
    return ''
