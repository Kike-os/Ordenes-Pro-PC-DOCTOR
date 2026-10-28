"""Facturas de Órdenes Pro emitidas a través de AZUR (ambiente de PRUEBAS mientras la emisión real no esté autorizada).

Flujo: Emitir en Órdenes Pro (secuencial propio y XML de control) → «Enviar al SRI (AZUR)» → AZUR firma y envía → «Consultar estado»
(o la consulta periódica) → autorizada: se guardan clave de acceso, número y fecha de autorización, PDF y XML → correo desde la cuenta de
facturación (en pruebas, solo a la dirección de prueba). Sin duplicados: la clave de idempotencia y el secuencial propio se fijan antes de
llamar a AZUR, así un reintento o un doble clic consulta en lugar de emitir otra vez. Numeración: el punto de emisión de Órdenes Pro
(AZUR_PUNTO_EMISION) debe coincidir con los Datos fiscales y ser distinto del que usa Mi Negocio."""
import base64
import hashlib
import json
import os
import re
import secrets

import azur_client as az
import invoicing

PAY_TYPES = ('01', '15', '16', '17', '18', '19', '20', '21')


def stamp(now):
    return now.isoformat(timespec='seconds')


def log(c, invoice_id, action, result, code='', detail='', http_status=None, request_key='', user=None, now=None):
    """Registro de cada operación con AZUR. Nunca guarda credenciales ni el cuerpo enviado."""
    c.execute('INSERT INTO azur_operations(invoice_id,action,request_key,http_status,result,code,detail,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
              (invoice_id, action, request_key, http_status, result, code[:60], detail[:600], user['id'] if user else None, stamp(now)))


def point(env=None):
    env = os.environ if env is None else env
    return env.get('AZUR_PUNTO_EMISION', '').strip()


def readiness(c, env=None):
    """Estado de la integración sin secretos: credenciales, punto de emisión y coincidencia con los Datos fiscales."""
    st = az.status(env)
    cfg = invoicing.settings(c)
    expected = point(env)
    mine = '%s-%s' % (cfg['establishment'], cfg['emission_point'])
    problems = list(st['problems'])
    if not expected:
        problems.append('Falta AZUR_PUNTO_EMISION (por ejemplo 001-002): el punto de emisión exclusivo de Órdenes Pro, distinto del de Mi Negocio.')
    elif expected != mine:
        problems.append('El punto de emisión de AZUR (%s) no coincide con los Datos fiscales de Órdenes Pro (%s): se evita así un choque de numeración.' % (expected, mine))
    if cfg['missing']:
        problems.append('Faltan datos fiscales: ' + ', '.join(cfg['missing']) + '.')
    recent = [dict(r) for r in c.execute('SELECT o.id,o.invoice_id,o.action,o.result,o.code,o.detail,o.http_status,o.created_at,COALESCE(u.name,\'Sistema\') actor '
                                         'FROM azur_operations o LEFT JOIN users u ON u.id=o.actor_id ORDER BY o.id DESC LIMIT 30')]
    return dict(st, ready=not problems, problems=problems, point=expected, fiscal_point=mine, test_mode=invoicing.TEST_MODE, operations=recent)


def payload(c, invoice_id):
    """JSON de emisión de AZUR a partir de la factura ya emitida en Órdenes Pro (los totales los recalcula AZUR y deben coincidir)."""
    d = invoicing.detail(c, invoice_id)
    inv = d['invoice']
    if inv['consumer_final']:
        buyer = {'tipo_identificacion': '07', 'identificacion': '9999999999999', 'razon_social': 'CONSUMIDOR FINAL', 'direccion': inv['buyer_address'] or 'S/N'}
    else:
        buyer = {'tipo_identificacion': inv['buyer_id_type'], 'identificacion': inv['buyer_id'], 'razon_social': inv['buyer_name'], 'direccion': inv['buyer_address'] or 'S/N'}
        if inv['buyer_phone']:
            buyer['telefono'] = inv['buyer_phone']
    # El correo del comprador NO se envía a AZUR: el envío lo hace Órdenes Pro desde la cuenta de facturación (y en pruebas, nunca al cliente).
    items = []
    for i in d['items']:
        unit = i['unit_price_micros'] / 1e6
        items.append({'codigo_principal': (i['code'] or 'ITEM-%d' % i['position'])[:25], 'descripcion': i['description'][:300], 'cantidad': i['quantity'],
                      'precio_unitario': round(unit, 6), 'descuento': round(i['discount_cents'] / 100, 2), 'tipoproducto': 1 if i.get('catalog_id') else 2,
                      'tipo_iva': int(i['tax_code']) if str(i['tax_code']).isdigit() else 4})
    pays = [{'tipo': p['sri_code'] if p['sri_code'] in PAY_TYPES else '20', 'total': round(p['amount_cents'] / 100, 2), 'tiempo': 'dias', 'plazo': 0} for p in d['payments']] or \
        [{'tipo': '20', 'total': round(inv['total_cents'] / 100, 2), 'tiempo': 'dias', 'plazo': 0}]
    extra = [{'nombre': 'Sistema', 'detalle': 'Órdenes Pro · factura %d' % inv['id']}]
    for name, value in (('Orden', inv['order_code']), ('Venta', inv['sale_code']), ('Proforma', inv['proforma_code'])):
        if value:
            extra.append({'nombre': name, 'detalle': value})
    issue = inv['issue_date'] or ''
    return {'codigoDoc': '01', 'emisor': {'fecha_emision': issue.replace('-', '/'), 'secuencial': '%09d' % int(inv['sequential'])}, 'comprador': buyer, 'items': items,
            'pagos': pays, 'informacion_adicional': extra}


def _row(c, invoice_id):
    row = c.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not row:
        raise invoicing.InvoiceError('Factura no encontrada.', 404)
    return row


def send(c, invoice_id, user, now, env=None):
    """Envía al SRI a través de AZUR una factura ya emitida en pruebas. Idempotente: si ya se envió, consulta en lugar de reenviar."""
    if user['role'] != 'administrador':
        raise invoicing.InvoiceError('Solo administración envía comprobantes al SRI.', 403)
    ready = readiness(c, env)
    if not ready['ready']:
        raise invoicing.InvoiceError('La integración con AZUR no está lista: ' + ' '.join(ready['problems']), 409)
    inv = _row(c, invoice_id)
    if inv['environment'] != invoicing.TEST_ENVIRONMENT:
        raise invoicing.InvoiceError('Solo se envían comprobantes del ambiente de pruebas.', 403)
    if inv['status'] == 'borrador':
        raise invoicing.InvoiceError('Primero emite la factura en Órdenes Pro (asigna el secuencial).', 409)
    if inv['provider'] == 'azur' and inv['status'] in ('enviado', 'autorizado'):
        return sync(c, invoice_id, user, now, env)  # ya está en AZUR: no se emite otra vez
    if inv['provider'] == 'azur' and inv['status'] == 'rechazado' and inv['provider_id']:
        # Rechazada por el SRI: se corrige en AZUR o en el SRI y se vuelve a procesar EL MISMO comprobante (nunca uno nuevo).
        key = 'reprocesar-%d-%d' % (invoice_id, int(inv['provider_state'] or 0))
        try:
            az.reprocess(az.config(env), inv['provider_id'], key)
        except az.AzurError as error:
            log(c, invoice_id, 'reprocesar', 'error', error.code, str(error), error.status, key, user, now)
            c.commit()
            raise invoicing.InvoiceError(str(error), 502 if error.retryable else 409)
        c.execute("UPDATE invoices SET status='enviado',updated_at=? WHERE id=?", (stamp(now), invoice_id))
        log(c, invoice_id, 'reprocesar', 'pendiente', '', 'AZUR vuelve a procesar el mismo comprobante.', 200, key, user, now)
        invoicing.event(c, invoice_id, 'azur_reprocesar', 'Reenviado a AZUR para volver a procesarlo (mismo comprobante).', now, user)
        c.commit()
        return sync(c, invoice_id, user, now, env, quiet=True)
    if inv['status'] not in ('pendiente', 'rechazado'):
        raise invoicing.InvoiceError('Esta factura no se puede enviar (%s).' % invoicing.STATUS[inv['status']].lower(), 409)
    key = inv['provider_request_key'] or 'op-%d-%s' % (invoice_id, secrets.token_hex(8))
    # La clave queda guardada ANTES de llamar a AZUR: un corte de conexión o un segundo clic reutilizan la misma y no duplican.
    c.execute("UPDATE invoices SET provider='azur',provider_request_key=?,updated_at=? WHERE id=?", (key, stamp(now), invoice_id))
    c.commit()
    cfg = az.config(env)
    body = payload(c, invoice_id)
    try:
        access = az.emit_invoice(cfg, body, key)
    except az.AzurError as error:
        if error.code == 'secuencial_ocupado':
            # El mismo secuencial ya está en AZUR (reintento tras un corte): se recupera en vez de emitir otro.
            number = '%s-%s-%09d' % (inv['establishment'], inv['emission_point'], inv['sequential'])
            doc_id = az.find_invoice(cfg, number)
            if doc_id:
                c.execute("UPDATE invoices SET provider_id=?,status='enviado',updated_at=? WHERE id=?", (doc_id, stamp(now), invoice_id))
                log(c, invoice_id, 'enviar', 'pendiente', 'recuperado', 'El secuencial ya estaba en AZUR: se recuperó el documento %d sin emitir otro.' % doc_id, error.status, key, user, now)
                c.commit()
                return sync(c, invoice_id, user, now, env)
        messages = json.loads(inv['sri_messages'] or '[]') + [{'origen': 'AZUR', 'codigo': error.code, 'mensaje': str(error), 'fecha': stamp(now)}]
        c.execute('UPDATE invoices SET sri_messages=?,updated_at=? WHERE id=?', (json.dumps(messages[-20:], ensure_ascii=False), stamp(now), invoice_id))
        log(c, invoice_id, 'enviar', 'error', error.code, str(error), error.status, key, user, now)
        invoicing.event(c, invoice_id, 'azur_error', 'AZUR no aceptó el envío: %s' % error, now, user)
        c.commit()
        raise invoicing.InvoiceError(str(error), 502 if error.retryable else 409)
    if az.environment_of_key(access) != '1':
        # Defensa: el punto de emisión de AZUR debe ser de PRUEBAS. Si la clave dice producción se detiene todo y se avisa.
        log(c, invoice_id, 'enviar', 'error', 'ambiente_produccion', 'AZUR devolvió una clave de PRODUCCIÓN (%s): revisa el punto de emisión en AZUR.' % access, 200, key, user, now)
        invoicing.event(c, invoice_id, 'azur_alerta', 'ALERTA: AZUR emitió en ambiente de PRODUCCIÓN (clave %s). El punto de emisión configurado no es de pruebas.' % access, now, user)
        c.commit()
        raise invoicing.InvoiceError('AZUR emitió en PRODUCCIÓN: el punto de emisión configurado no es de pruebas. Se detuvo la integración; revisa AZUR.', 409)
    previous = inv['access_key']
    c.execute("UPDATE invoices SET access_key=?,status='enviado',provider_state=0,updated_at=? WHERE id=?", (access, stamp(now), invoice_id))
    log(c, invoice_id, 'enviar', 'ok', 'creado', 'AZUR recibió el comprobante y lo envió al SRI de pruebas (clave %s).' % access, 200, key, user, now)
    invoicing.event(c, invoice_id, 'azur_enviado', 'Enviado al SRI de pruebas a través de AZUR (firma de AZUR). Clave de acceso %s%s.' % (
        access, (' (la clave de control local era %s)' % previous) if previous and previous != access else ''), now, user)
    c.commit()
    try:
        doc_id = az.find_invoice(cfg, access)
        if doc_id:
            c.execute('UPDATE invoices SET provider_id=? WHERE id=?', (doc_id, invoice_id))
            c.commit()
    except az.AzurError:
        pass  # se resuelve en la siguiente consulta
    return sync(c, invoice_id, user, now, env, quiet=True)


def sync(c, invoice_id, user, now, env=None, live=False, quiet=False):
    """Consulta el estado en AZUR y lo refleja sin inventar nada: solo el código 4 es «autorizado». Guarda PDF y XML al autorizarse."""
    inv = _row(c, invoice_id)
    if inv['provider'] != 'azur':
        raise invoicing.InvoiceError('Esta factura no se envió a través de AZUR.', 409)
    cfg = az.config(env)
    try:
        doc_id = inv['provider_id'] or (az.find_invoice(cfg, inv['access_key']) if inv['access_key'] else None)
        if not doc_id:
            data = az.consult(cfg, inv['access_key'])
            code = int(data.get('estado', 0) or 0)
            st = {'codigo': code, 'autorizado': code == 4, 'claveacceso': inv['access_key'], 'fecha_autorizacion': data.get('fecha_aprobado', ''), 'errores': [data.get('mensaje') or data.get('motivo')] if data.get('motivo') else []}
        else:
            if not inv['provider_id']:
                c.execute('UPDATE invoices SET provider_id=? WHERE id=?', (doc_id, invoice_id))
            st = az.state(cfg, doc_id, live)
    except az.AzurError as error:
        log(c, invoice_id, 'consultar', 'error', error.code, str(error), error.status, '', user, now)
        c.commit()
        if quiet:
            return {'invoice_id': invoice_id, 'state': inv['provider_state'], 'message': str(error)}
        raise invoicing.InvoiceError(str(error), 502 if error.retryable else 409)
    code = int(st.get('codigo', 0) or 0)
    label = az.STATES.get(code, 'Estado %d' % code)
    errors = [str(e) for e in (st.get('errores') or []) if e]
    if inv['status'] == 'autorizado':
        # Un comprobante autorizado no se modifica: solo se registra (aparte) si consta anulado en el SRI.
        if code == 9 and not annulment(c, invoice_id):
            c.execute("INSERT INTO invoice_annulments(invoice_id,annulled_at,reason,source,actor_id) VALUES (?,?,?,'sri',?)",
                      (invoice_id, stamp(now), 'Consta anulada en el SRI (consulta de estado).', user['id'] if user else None))
            invoicing.event(c, invoice_id, 'anulado', 'Consta ANULADA en el SRI (detectado al consultar el estado).', now, user)
        log(c, invoice_id, 'consultar', 'ok', str(code), label, 200, '', user, now)
        c.commit()
        return {'invoice_id': invoice_id, 'state': code, 'label': label, 'authorized': True, 'newly_authorized': False, 'errors': errors}
    updates = {'provider_state': code, 'provider_synced_at': stamp(now)}
    newly = False
    if code == 4:
        newly = True
        # Documentos ANTES de autorizar: después, el comprobante ya no se modifica.
        files = fetch_files(c, invoice_id, cfg, now, user)
        updates.update(xml_authorized=files.get('xml_autorizado', ''), xml_signed=files.get('xml_firmado', ''))
        updates.update(status='autorizado', authorization_number=str(st.get('numero_autorizacion') or st.get('claveacceso') or inv['access_key']),
                       authorized_at=str(st.get('fecha_autorizacion') or stamp(now)))
    elif code in az.FINAL_REJECTED and inv['status'] != 'rechazado':
        updates['status'] = 'rechazado'
    if errors:
        messages = json.loads(inv['sri_messages'] or '[]') + [{'origen': 'SRI/AZUR', 'codigo': str(code), 'mensaje': e, 'fecha': stamp(now)} for e in errors]
        updates['sri_messages'] = json.dumps(messages[-20:], ensure_ascii=False)
    c.execute('UPDATE invoices SET ' + ','.join(k + '=?' for k in updates) + ' WHERE id=?', (*updates.values(), invoice_id))
    log(c, invoice_id, 'consultar', 'ok' if code == 4 else 'error' if code in az.FINAL_REJECTED else 'pendiente', str(code), label + ('. ' + ' '.join(errors) if errors else ''), 200, '', user, now)
    if newly:
        invoicing.event(c, invoice_id, 'autorizado', 'AUTORIZADA por el SRI (ambiente de PRUEBAS) · número %s · %s.' % (updates['authorization_number'], updates['authorized_at']), now, user)
    elif code in az.FINAL_REJECTED and updates.get('status') == 'rechazado':
        invoicing.event(c, invoice_id, 'rechazado', '%s: %s' % (label, ' '.join(errors) or 'sin detalle'), now, user)
    c.commit()
    return {'invoice_id': invoice_id, 'state': code, 'label': label, 'authorized': code == 4, 'newly_authorized': newly, 'errors': errors,
            'reprocessable': bool(st.get('reprocesable')), 'what_to_do': str(st.get('que_hacer') or '')}


def fetch_files(c, invoice_id, cfg, now, user=None):
    """PDF del RIDE de AZUR y XML firmado y autorizado. Un fallo aquí no cambia el estado: se puede volver a pedir."""
    inv = _row(c, invoice_id)
    got = {}
    for kind in ('pdf', 'xml_autorizado', 'xml_firmado'):
        try:
            content = az.document(cfg, inv['provider_id'], kind) if inv['provider_id'] else ''
        except az.AzurError as error:
            log(c, invoice_id, 'documento_' + kind, 'error', error.code, str(error), error.status, '', user, now)
            continue
        if not content:
            continue
        raw = base64.b64decode(content, validate=False)
        c.execute('INSERT INTO invoice_provider_files(invoice_id,kind,content,sha256,created_at) VALUES (?,?,?,?,?) ON CONFLICT(invoice_id,kind) DO UPDATE SET content=excluded.content,'
                  'sha256=excluded.sha256,created_at=excluded.created_at', (invoice_id, kind, content, hashlib.sha256(raw).hexdigest(), stamp(now)))
        got[kind] = raw.decode('utf-8', 'replace') if kind != 'pdf' else ''
    if got:
        log(c, invoice_id, 'documentos', 'ok', '', 'Guardados: ' + ', '.join(got), 200, '', user, now)
    return got


def file_for(c, invoice_id, kind):
    row = c.execute('SELECT content FROM invoice_provider_files WHERE invoice_id=? AND kind=?', (invoice_id, kind)).fetchone()
    if not row:
        raise invoicing.InvoiceError('Documento no disponible todavía.', 404)
    return base64.b64decode(row['content'])


def annul(c, invoice_id, user, now, data, env=None):
    """Anulación con confirmación expresa. AZUR no anula en el SRI: la solicitud la presenta el contribuyente en SRI en línea y aquí solo se
    comprueba que ya consta anulada y se refleja. Nunca se anula automáticamente."""
    if user['role'] != 'administrador':
        raise invoicing.InvoiceError('Solo administración anula comprobantes.', 403)
    if str(data.get('confirm', '')).strip() != 'ANULAR':
        raise invoicing.InvoiceError('Escribe ANULAR para confirmar.', 400, {'confirm': 'Confirmación obligatoria.'})
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if not 10 <= len(reason) <= 300:
        raise invoicing.InvoiceError('Indica el motivo de la anulación (10 a 300 caracteres).', 400, {'reason': 'Motivo obligatorio.'})
    inv = _row(c, invoice_id)
    if inv['provider'] != 'azur' or inv['status'] != 'autorizado' or not inv['provider_id']:
        raise invoicing.InvoiceError('Solo se anula una factura autorizada a través de AZUR.', 409)
    if annulment(c, invoice_id):
        return {'annulled': True, 'already': True}
    key = 'anular-%d-%s' % (invoice_id, hashlib.sha256((inv['access_key'] or '').encode()).hexdigest()[:12])
    try:
        az.annul(az.config(env), inv['provider_id'], key)
    except az.AzurError as error:
        hints = {'anulacion_no_solicitada': 'Primero presenta la solicitud de anulación en SRI en línea (Facturación Electrónica › Anulación) y vuelve a intentarlo.',
                 'anulacion_fuera_de_plazo': 'Pasó el plazo del SRI para anular: corrige con una nota de crédito.'}
        log(c, invoice_id, 'anular', 'error', error.code, str(error), error.status, key, user, now)
        c.commit()
        raise invoicing.InvoiceError(hints.get(error.code, str(error)), 409)
    c.execute("INSERT INTO invoice_annulments(invoice_id,annulled_at,reason,source,actor_id) VALUES (?,?,?,'usuario',?)", (invoice_id, stamp(now), reason, user['id']))
    log(c, invoice_id, 'anular', 'ok', '9', 'Anulación confirmada por el SRI y reflejada en AZUR. Motivo: ' + reason, 200, key, user, now)
    invoicing.event(c, invoice_id, 'anulado', 'Factura ANULADA (confirmada en el SRI). Motivo: %s' % reason, now, user)
    c.commit()
    return {'annulled': True}


def annulment(c, invoice_id):
    row = c.execute('SELECT * FROM invoice_annulments WHERE invoice_id=?', (invoice_id,)).fetchone()
    return dict(row) if row else None


def pending(c, limit=10):
    return [r[0] for r in c.execute("SELECT id FROM invoices WHERE provider='azur' AND status='enviado' ORDER BY id LIMIT ?", (limit,))]
