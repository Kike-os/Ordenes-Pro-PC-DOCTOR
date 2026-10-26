"""Comprobantes electrónicos del SRI (esquema offline, ficha técnica v2.34): clave de acceso y XML de la factura (versión 1.1.0).

Solo genera el documento; no lo firma ni lo transmite (eso lo hacen sri_sign y sri_ws). Todos los importes entran en centavos enteros
y los precios unitarios en millonésimas de dólar, para que no haya errores de redondeo de coma flotante."""
import re
import secrets
from xml.sax.saxutils import escape, quoteattr

DOC_TYPES = {'01': 'Factura', '04': 'Nota de crédito', '05': 'Nota de débito'}
ID_TYPES = {'04': 'RUC', '05': 'Cédula', '06': 'Pasaporte', '07': 'Consumidor final', '08': 'Identificación del exterior'}
CONSUMER_FINAL_ID = '9999999999999'
IVA_CODES = {0: '0', 1500: '4', 500: '5'}  # tabla 17 de la ficha: 0 % → 0, 15 % → 4, 5 % → 5
RIMPE_LEGENDS = {'rimpe_emprendedor': 'CONTRIBUYENTE RÉGIMEN RIMPE', 'rimpe_negocio_popular': 'CONTRIBUYENTE NEGOCIO POPULAR - RÉGIMEN RIMPE'}


class SriError(ValueError):
    pass


def mod11(digits):
    """Dígito verificador de la clave de acceso (módulo 11, pesos 2 a 7 de derecha a izquierda): 11 → 0 y 10 → 1."""
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(digits)))
    check = 11 - total % 11
    return 0 if check == 11 else 1 if check == 10 else check


def access_key(issue_date, doc_type, ruc, environment, establishment, emission_point, sequential, numeric_code=None, emission_type='1'):
    """Clave de acceso de 49 dígitos: fecha ddmmaaaa, tipo, RUC, ambiente, serie, secuencial, código numérico, tipo de emisión y verificador."""
    numeric_code = numeric_code or '%08d' % secrets.randbelow(10 ** 8)
    parts = [issue_date.strftime('%d%m%Y'), doc_type, ruc, environment, establishment + emission_point, '%09d' % sequential, numeric_code, emission_type]
    body = ''.join(parts)
    if not re.fullmatch(r'\d{48}', body):
        raise SriError('Datos insuficientes o inválidos para la clave de acceso.')
    return body + str(mod11(body))


def money(cents):
    return '%d.%02d' % divmod(cents, 100) if cents >= 0 else '-' + money(-cents)


def micros(value):
    """Precio unitario con hasta 6 decimales (el esquema 1.1.0 los admite)."""
    whole, frac = divmod(value, 1_000_000)
    return '%d.%06d' % (whole, frac)


def _tag(name, value):
    return '<%s>%s</%s>' % (name, escape(str(value)), name)


def invoice_xml(settings, invoice, items, payments):
    """XML sin firmar de una factura. `settings` es la configuración fiscal; `invoice`, `items` y `payments`, filas ya calculadas."""
    s, inv = settings, invoice
    head = [_tag('ambiente', inv['environment']), _tag('tipoEmision', '1'), _tag('razonSocial', s['legal_name'])]
    if s.get('trade_name'):
        head.append(_tag('nombreComercial', s['trade_name']))
    head += [_tag('ruc', s['ruc']), _tag('claveAcceso', inv['access_key']), _tag('codDoc', '01'), _tag('estab', inv['establishment']),
             _tag('ptoEmi', inv['emission_point']), _tag('secuencial', '%09d' % inv['sequential']), _tag('dirMatriz', s['head_office_address'])]
    if s.get('withholding_agent'):
        head.append(_tag('agenteRetencion', s['withholding_agent']))
    if s.get('regime') in RIMPE_LEGENDS:
        head.append(_tag('contribuyenteRimpe', RIMPE_LEGENDS[s['regime']]))
    info = [_tag('fechaEmision', inv['issue_date_sri'])]
    if s.get('branch_address'):
        info.append(_tag('dirEstablecimiento', s['branch_address']))
    if s.get('special_taxpayer'):
        info.append(_tag('contribuyenteEspecial', s['special_taxpayer']))
    if s.get('keeps_accounts'):
        info.append(_tag('obligadoContabilidad', s['keeps_accounts']))
    info += [_tag('tipoIdentificacionComprador', inv['buyer_id_type']), _tag('razonSocialComprador', inv['buyer_name']),
             _tag('identificacionComprador', inv['buyer_id'])]
    if inv.get('buyer_address'):
        info.append(_tag('direccionComprador', inv['buyer_address']))
    info += [_tag('totalSinImpuestos', money(inv['subtotal_cents'])), _tag('totalDescuento', money(inv['discount_cents']))]
    groups = {}
    for item in items:
        group = groups.setdefault(item['tax_code'], [0, 0])
        group[0] += item['base_cents']
        group[1] += item['tax_cents']
    info.append('<totalConImpuestos>' + ''.join('<totalImpuesto>%s%s%s%s</totalImpuesto>' % (_tag('codigo', '2'), _tag('codigoPorcentaje', code), _tag('baseImponible', money(base)), _tag('valor', money(tax)))
                                                for code, (base, tax) in sorted(groups.items())) + '</totalConImpuestos>')
    info += [_tag('propina', '0.00'), _tag('importeTotal', money(inv['total_cents'])), _tag('moneda', 'DOLAR')]
    info.append('<pagos>' + ''.join('<pago>%s%s</pago>' % (_tag('formaPago', p['sri_code']), _tag('total', money(p['amount_cents']))) for p in payments) + '</pagos>')
    details = []
    for item in items:
        tax = '<impuestos><impuesto>%s%s%s%s%s</impuesto></impuestos>' % (_tag('codigo', '2'), _tag('codigoPorcentaje', item['tax_code']), _tag('tarifa', '%g' % (item['tax_rate_bp'] / 100)),
                                                                         _tag('baseImponible', money(item['base_cents'])), _tag('valor', money(item['tax_cents'])))
        details.append('<detalle>%s%s%s%s%s%s%s</detalle>' % (_tag('codigoPrincipal', item['code'][:25]), _tag('descripcion', item['description'][:300]), _tag('cantidad', '%d.000000' % item['quantity']),
                                                            _tag('precioUnitario', micros(item['unit_price_micros'])), _tag('descuento', money(item['discount_cents'])),
                                                            _tag('precioTotalSinImpuesto', money(item['base_cents'])), tax))
    extra = []
    for name, value in (('Correo', inv.get('buyer_email')), ('Teléfono', inv.get('buyer_phone')), ('Orden', inv.get('reference'))):
        if value:
            extra.append('<campoAdicional nombre=%s>%s</campoAdicional>' % (quoteattr(name), escape(str(value)[:300])))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<factura id="comprobante" version="1.1.0"><infoTributaria>' + ''.join(head) + '</infoTributaria><infoFactura>' + ''.join(info)
            + '</infoFactura><detalles>' + ''.join(details) + '</detalles>' + ('<infoAdicional>' + ''.join(extra) + '</infoAdicional>' if extra else '') + '</factura>')
