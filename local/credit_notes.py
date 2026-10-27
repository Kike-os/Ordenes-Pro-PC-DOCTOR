"""Notas de crédito (solo ambiente de pruebas del SRI; la emisión real sigue desactivada): anulación total o parcial de una factura emitida.

- Una factura en borrador no lleva nota de crédito: se descarta. Solo se acredita lo facturado y no acreditado antes (por partida).
- Motivo obligatorio; numeración propia (tipo 04) con clave de acceso y XML sin firmar, como la factura.
- Si la factura nació de una venta del inventario y se acredita completa, sus unidades pueden volver al inventario con un solo
  movimiento de devolución (sin duplicarlo en un reintento)."""
import re

import invoicing
import sri_xml

EMITTED = ('pendiente', 'enviado', 'autorizado')


class CreditNoteError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def credited(c, invoice_id):
    """Cantidades ya acreditadas por partida de la factura (notas emitidas)."""
    return {r['invoice_item_id']: r['qty'] for r in c.execute("SELECT i.invoice_item_id,SUM(i.quantity) qty FROM credit_note_items i JOIN credit_notes n ON n.id=i.credit_note_id "
                                                               "WHERE n.invoice_id=? AND n.status='pendiente' GROUP BY i.invoice_item_id", (invoice_id,))}


def _share(value, part, whole):
    return (2 * value * part + whole) // (2 * whole)


def create(c, invoice_id, data, user, now):
    """Crea y emite (en pruebas) una nota de crédito. Idempotente con la clave de solicitud."""
    import json
    key = str(data.get('request_key', '') or '').strip()
    if key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise CreditNoteError('Solicitud no válida. Recarga la página.')
        same = c.execute('SELECT id FROM credit_notes WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id']
    inv = c.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not inv:
        raise CreditNoteError('Factura no encontrada.', 404)
    if inv['status'] not in EMITTED:
        raise CreditNoteError('Solo una factura emitida admite nota de crédito; un borrador se descarta.', 409)
    if inv['environment'] != invoicing.TEST_ENVIRONMENT:
        raise CreditNoteError('La emisión real está desactivada.', 403)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if not 5 <= len(reason) <= 300:
        raise CreditNoteError('Indica el motivo de la nota de crédito.', 400, {'reason': 'Motivo de 5 a 300 caracteres.'})
    scope = str(data.get('scope', 'total'))
    if scope not in ('total', 'parcial'):
        raise CreditNoteError('Elige nota total o parcial.', 400, {'scope': 'Opción no válida.'})
    items = {r['id']: dict(r) for r in c.execute('SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY position', (invoice_id,))}
    done = credited(c, invoice_id)
    remaining = {iid: it['quantity'] - done.get(iid, 0) for iid, it in items.items()}
    if not any(q > 0 for q in remaining.values()):
        raise CreditNoteError('Esta factura ya está acreditada por completo.', 409)
    if scope == 'total':
        wanted = {iid: q for iid, q in remaining.items() if q > 0}
    else:
        try:
            lines = json.loads(data.get('lines', '[]')) if isinstance(data.get('lines'), str) else (data.get('lines') or [])
            wanted = {int(l['item_id']): int(l['quantity']) for l in lines if int(l['quantity']) > 0}
        except (ValueError, TypeError, KeyError):
            raise CreditNoteError('Partidas no válidas.', 400, {'lines': 'Partidas no válidas.'})
        if not wanted:
            raise CreditNoteError('Elige al menos una partida y su cantidad.', 400, {'lines': 'Sin partidas.'})
        for iid, qty in wanted.items():
            if iid not in items or qty > remaining[iid]:
                raise CreditNoteError('La cantidad supera lo facturado y no acreditado de «%s».' % (items[iid]['description'] if iid in items else iid), 400, {'lines': 'Cantidad no válida.'})
    rows = []
    for iid, qty in wanted.items():
        it = items[iid]
        if qty == remaining[iid]:
            # Lo último que queda de la partida absorbe el redondeo: lo acreditado nunca supera lo facturado.
            prev = c.execute("SELECT COALESCE(SUM(i.base_cents),0),COALESCE(SUM(i.tax_cents),0),COALESCE(SUM(i.discount_cents),0) FROM credit_note_items i JOIN credit_notes n ON n.id=i.credit_note_id "
                             "WHERE n.status='pendiente' AND i.invoice_item_id=?", (iid,)).fetchone()
            base, tax, discount = it['base_cents'] - prev[0], it['tax_cents'] - prev[1], it['discount_cents'] - prev[2]
        else:
            # Parte proporcional del total con IVA y, de ella, base e impuesto exactos (como en la factura): sin centavos de más.
            base, tax, _ = invoicing.split_inclusive(_share(it['total_cents'], qty, it['quantity']), it['tax_rate_bp'])
            discount = _share(it['discount_cents'], qty, it['quantity'])
        rows.append({'invoice_item_id': iid, 'code': it['code'], 'description': it['description'], 'quantity': qty, 'unit_price_micros': it['unit_price_micros'], 'discount_cents': discount,
                     'base_cents': base, 'tax_code': it['tax_code'], 'tax_rate_bp': it['tax_rate_bp'], 'tax_cents': tax, 'total_cents': base + tax})
    cfg = invoicing.settings(c)
    if cfg['missing']:
        raise CreditNoteError('Faltan datos fiscales en la configuración: ' + ', '.join(cfg['missing']) + '.', 409)
    subtotal, tax_total = sum(r['base_cents'] for r in rows), sum(r['tax_cents'] for r in rows)
    seq_key = (invoicing.TEST_ENVIRONMENT, cfg['establishment'], cfg['emission_point'], '04')
    c.execute('INSERT OR IGNORE INTO invoice_sequences(environment,establishment,emission_point,doc_type,last_number) VALUES (?,?,?,?,0)', seq_key)
    c.execute('UPDATE invoice_sequences SET last_number=last_number+1 WHERE environment=? AND establishment=? AND emission_point=? AND doc_type=?', seq_key)
    sequential = c.execute('SELECT last_number FROM invoice_sequences WHERE environment=? AND establishment=? AND emission_point=? AND doc_type=?', seq_key).fetchone()[0]
    issue = now.date()
    access = sri_xml.access_key(issue, '04', cfg['ruc'], invoicing.TEST_ENVIRONMENT, cfg['establishment'], cfg['emission_point'], sequential)
    stamp = now.isoformat(timespec='seconds')
    note_id = c.execute('INSERT INTO credit_notes(invoice_id,status,environment,scope,reason,subtotal_cents,tax_cents,total_cents,establishment,emission_point,sequential,access_key,issue_date,'
                        "created_by,created_at,emitted_by,emitted_at,request_key) VALUES (?,'borrador',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (invoice_id, invoicing.TEST_ENVIRONMENT, 'total' if all(wanted.get(i, 0) == q for i, q in remaining.items() if q > 0) else 'parcial', reason, subtotal, tax_total,
                         subtotal + tax_total, cfg['establishment'], cfg['emission_point'], sequential, access, issue.isoformat(), user['id'], stamp, user['id'], stamp, key or None)).lastrowid
    for r in rows:
        c.execute('INSERT INTO credit_note_items(credit_note_id,invoice_item_id,code,description,quantity,unit_price_micros,discount_cents,base_cents,tax_code,tax_rate_bp,tax_cents,total_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (note_id, r['invoice_item_id'], r['code'], r['description'], r['quantity'], r['unit_price_micros'], r['discount_cents'], r['base_cents'], r['tax_code'], r['tax_rate_bp'], r['tax_cents'], r['total_cents']))
    inv_data = dict(inv, number=invoicing.number(inv), issue_date_sri='/'.join(reversed(inv['issue_date'].split('-'))))
    note = {'environment': invoicing.TEST_ENVIRONMENT, 'access_key': access, 'establishment': cfg['establishment'], 'emission_point': cfg['emission_point'], 'sequential': sequential,
            'issue_date_sri': issue.strftime('%d/%m/%Y'), 'subtotal_cents': subtotal, 'total_cents': subtotal + tax_total, 'reason': reason}
    xml = sri_xml.credit_note_xml(cfg, note, inv_data, rows)
    c.execute("UPDATE credit_notes SET status='pendiente',xml_unsigned=? WHERE id=?", (xml, note_id))
    number = '%s-%s-%09d' % (cfg['establishment'], cfg['emission_point'], sequential)
    invoicing.event(c, invoice_id, 'nota_credito', 'Nota de crédito %s (%s) emitida en ambiente de PRUEBAS por %s: %s' % (number, 'total' if scope == 'total' else 'parcial', invoicing.quotes.usd(subtotal + tax_total), reason), now, user)
    if str(data.get('return_stock', '')) in ('1', 'true', 'on') and inv['source_kind'] == 'venta_inventario':
        _return_stock(c, inv, note_id, rows, user, now)
    return note_id


def _return_stock(c, inv, note_id, rows, user, now):
    """Las unidades de la venta acreditada vuelven al inventario con un movimiento de devolución del cliente (uno solo, aunque se reintente)."""
    import inventory
    sale = c.execute('SELECT * FROM inventory_movements WHERE id=?', (inv['source_id'],)).fetchone()
    qty = sum(r['quantity'] for r in rows)
    units = [r['unit_id'] for r in c.execute('SELECT x.unit_id FROM inventory_movement_units x JOIN inventory_units u ON u.id=x.unit_id WHERE x.movement_id=? AND u.status IN (\'vendida\',\'consumida\')', (sale['id'],))][:qty]
    inventory.move(c, sale['item_id'], 1, 'devolucion_cliente', qty, '%d.%02d' % divmod(sale['unit_cost_cents'] or 0, 100), user, now, reference_kind='nota_credito', reference_id=note_id,
                   note='Devolución por nota de crédito de la factura ' + invoicing.number(inv), request_key='nc-%d' % note_id, unit_ids=units or None)


def listing(c):
    return [dict(r, number='%s-%s-%09d' % (r['establishment'], r['emission_point'], r['sequential']) if r['sequential'] else '',
                 invoice_number=invoicing.number({'establishment': r['i_est'], 'emission_point': r['i_pt'], 'sequential': r['i_seq']}))
            for r in c.execute("SELECT n.id,n.invoice_id,n.status,n.scope,n.reason,n.total_cents,n.establishment,n.emission_point,n.sequential,n.access_key,n.emitted_at,i.buyer_name,"
                               "i.establishment i_est,i.emission_point i_pt,i.sequential i_seq FROM credit_notes n JOIN invoices i ON i.id=n.invoice_id ORDER BY n.id DESC LIMIT 300")]


def detail(c, note_id):
    n = c.execute('SELECT * FROM credit_notes WHERE id=?', (note_id,)).fetchone()
    if not n:
        raise CreditNoteError('Nota de crédito no encontrada.', 404)
    items = [dict(r) for r in c.execute('SELECT * FROM credit_note_items WHERE credit_note_id=? ORDER BY id', (note_id,))]
    return {'note': {k: n[k] for k in n.keys() if k != 'xml_unsigned'}, 'items': items, 'has_xml': bool(n['xml_unsigned'])}


def creditable(c, invoice_id):
    """Partidas de la factura con lo que todavía se puede acreditar (para el formulario)."""
    done = credited(c, invoice_id)
    return [{'id': r['id'], 'description': r['description'], 'quantity': r['quantity'], 'remaining': r['quantity'] - done.get(r['id'], 0), 'total_cents': r['total_cents']}
            for r in c.execute('SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY position', (invoice_id,))]
