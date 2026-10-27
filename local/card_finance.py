"""Centro de Métodos de Pago: tarjetas, factores DATAFAST de diferido con intereses y recargo comercial configurable.

Reglas que se aplican SIEMPRE en el servidor (la interfaz solo las refleja):
- Los factores salen de la base (tabla DATAFAST precargada por la migración 076); nunca de un PDF ni del navegador.
- Solo se aceptan combinaciones banco · marca · categoría configuradas y activas; el plazo debe tener un factor vigente.
- «Diferido sin intereses» usa factor 0 %: no se aplica ningún factor de la tabla con intereses.
- El recargo comercial es independiente del interés bancario y se aplica una sola vez, sobre el importe base.
- Todo en centavos enteros con redondeo monetario controlado (mitad hacia arriba); la última letra absorbe el ajuste para que la
  suma de las letras sea exactamente el total.
Orden de cálculo: base → recargo → subtotal financiable → interés de diferido → total → letras."""
import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MONTHS = (3, 4, 5, 6, 9, 10, 12, 15, 18, 24, 36)
MODES = {'corriente': 'Corriente', 'diferido_con_intereses': 'Diferido con intereses', 'diferido_sin_intereses': 'Diferido sin intereses'}
METHODS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia bancaria', 'deposito': 'Depósito bancario', 'debito': 'Tarjeta de débito',
           'credito_corriente': 'Tarjeta de crédito corriente', 'diferido_con_intereses': 'Tarjeta de crédito diferida con intereses',
           'diferido_sin_intereses': 'Tarjeta de crédito diferida sin intereses'}
SURCHARGE_METHODS = ('debito', 'credito_corriente', 'diferido_con_intereses', 'diferido_sin_intereses')
MAX_BASE_CENTS = 99_999_999


class CardError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def _round(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def percent_of(cents, bp):
    """Porcentaje en puntos básicos de un importe en centavos, redondeado al centavo (mitad hacia arriba)."""
    return _round(Decimal(cents) * Decimal(bp) / Decimal(10000))


def installments(total_cents, months):
    """Letras iguales redondeadas al centavo; la última absorbe la diferencia para que la suma sea exactamente el total."""
    months = max(1, int(months))
    each = _round(Decimal(total_cents) / Decimal(months))
    rows = [each] * (months - 1)
    rows.append(total_cents - each * (months - 1))
    return rows


def surcharge_settings(c):
    row = c.execute('SELECT * FROM card_surcharge_settings WHERE id=1').fetchone()
    if not row:
        return {'percent_bp': 0, 'fixed_cents': 0, 'payer': 'empresa', 'methods': [], 'valid_from': '', 'valid_to': '', 'active': False, 'validated': False, 'note': ''}
    out = dict(row)
    out['methods'] = json.loads(out['methods'] or '[]')
    out['active'], out['validated'] = bool(out['active']), bool(out['validated'])
    return out


def _surcharge_applies(cfg, method, today):
    if not cfg['active'] or cfg['payer'] != 'cliente' or method not in cfg['methods']:
        return False
    if cfg['valid_from'] and today < cfg['valid_from']:
        return False
    return not (cfg['valid_to'] and today > cfg['valid_to'])


def product(c, bank, brand, category):
    row = c.execute('SELECT * FROM card_products WHERE bank=? AND brand=? AND category=? AND active=1', (bank, brand, category)).fetchone()
    if not row:
        raise CardError('Esa combinación de banco, marca y categoría no está configurada.', 409, {'category': 'Combinación no configurada.'})
    return row


def factor(c, group_code, months, today):
    """Factor vigente del grupo y plazo en la fecha indicada; un factor pendiente de confirmar no se puede usar."""
    row = c.execute("SELECT * FROM card_factors WHERE group_code=? AND months=? AND status IN ('vigente','pendiente') ORDER BY id DESC LIMIT 1", (group_code, months)).fetchone()
    if not row:
        raise CardError('No hay un factor configurado para ese plazo.', 409, {'months': 'Plazo no disponible.'})
    if row['status'] == 'pendiente' or row['factor_bp'] is None:
        raise CardError('El factor de ese plazo está pendiente de confirmar con la tabla original: no se puede usar todavía.', 409, {'months': 'Factor pendiente de confirmar.'})
    if row['valid_from'] > today or (row['valid_to'] and row['valid_to'] < today):
        raise CardError('El factor de ese plazo no está vigente en esta fecha.', 409, {'months': 'Factor no vigente.'})
    return row


def _base_cents(value):
    try:
        amount = Decimal(str(value).strip().replace('$', '').replace(' ', '').replace(',', '.'))
    except Exception:
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2 or amount * 100 > MAX_BASE_CENTS:
        raise CardError('Indica un importe mayor que cero con hasta dos decimales.', 400, {'amount': 'Importe no válido.'})
    return int(amount * 100)


def simulate(c, data, today):
    """Cálculo completo de una venta con tarjeta (o de otro método, para mostrar el recargo si corresponde). Solo lectura."""
    base = _base_cents(data.get('amount', ''))
    method = str(data.get('method', 'diferido_con_intereses'))
    if method not in METHODS:
        raise CardError('Selecciona el método de pago.', 400, {'method': 'Método no válido.'})
    card = method in ('credito_corriente', 'diferido_con_intereses', 'diferido_sin_intereses')
    row = product(c, str(data.get('bank', '')), str(data.get('brand', '')), str(data.get('category', ''))) if card else None
    months, factor_row = 1, None
    if method in ('diferido_con_intereses', 'diferido_sin_intereses'):
        try:
            months = int(str(data.get('months', '')))
        except ValueError:
            months = 0
        if months not in MONTHS:
            raise CardError('Selecciona el plazo en meses.', 400, {'months': 'Plazo no válido.'})
        if method == 'diferido_con_intereses':
            factor_row = factor(c, row['group_code'], months, today)
    cfg = surcharge_settings(c)
    applies = _surcharge_applies(cfg, method, today)
    surcharge = (percent_of(base, cfg['percent_bp']) + cfg['fixed_cents']) if applies else 0
    financeable = base + surcharge
    factor_bp = factor_row['factor_bp'] if factor_row else 0
    interest = percent_of(financeable, factor_bp) if factor_bp else 0
    total = financeable + interest
    letters = installments(total, months)
    warnings = []
    if applies and not cfg['validated']:
        warnings.append('El recargo comercial está pendiente de validación contractual, tributaria y comercial antes de trasladarlo al cliente.')
    if applies or interest:
        warnings.append('Confirmar con el contador el tratamiento tributario del recargo y del interés antes de facturarlos.')
    return {'method': method, 'method_label': METHODS[method], 'modality': MODES.get(method.replace('credito_', '')) if card else None,
            'bank': row['bank'] if row else None, 'brand': row['brand'] if row else None, 'category': row['category'] if row else None, 'group': row['group_code'] if row else None,
            'months': months, 'base_cents': base, 'surcharge_applies': applies, 'surcharge_bp': cfg['percent_bp'] if applies else 0, 'surcharge_fixed_cents': cfg['fixed_cents'] if applies else 0,
            'surcharge_cents': surcharge, 'financeable_cents': financeable, 'factor_bp': factor_bp, 'interest_cents': interest, 'total_cents': total,
            'installment_cents': letters[0], 'installments': [{'number': i + 1, 'amount_cents': amount} for i, amount in enumerate(letters)],
            'factor_source': ('%s · versión %s · vigente desde %s' % (factor_row['source'], factor_row['version'], factor_row['valid_from'])) if factor_row else '',
            'warnings': warnings}


def compare(c, data, today):
    """Todos los plazos disponibles para la misma tarjeta e importe (con y sin intereses)."""
    rows = []
    for months in MONTHS:
        item = {'months': months}
        for method in ('diferido_con_intereses', 'diferido_sin_intereses'):
            try:
                r = simulate(c, {**data, 'method': method, 'months': months}, today)
                item[method] = {'total_cents': r['total_cents'], 'installment_cents': r['installment_cents'], 'factor_bp': r['factor_bp'], 'interest_cents': r['interest_cents']}
            except CardError as error:
                if 'months' not in error.fields:
                    raise
                item[method] = {'unavailable': str(error)}
        rows.append(item)
    return rows


def options(c, today):
    """Catálogo para los selectores dependientes: banco → marca → categoría (con su grupo) y plazos con factor vigente por grupo."""
    tree = {}
    for r in c.execute('SELECT bank,brand,category,group_code FROM card_products WHERE active=1 ORDER BY bank,brand,category'):
        tree.setdefault(r['bank'], {}).setdefault(r['brand'], []).append({'category': r['category'], 'group': r['group_code']})
    factors = {}
    for r in c.execute("SELECT group_code,months,factor_bp,status,valid_from,valid_to,source,version,note FROM card_factors WHERE status IN ('vigente','pendiente') ORDER BY group_code,months"):
        usable = r['status'] == 'vigente' and r['valid_from'] <= today and not (r['valid_to'] and r['valid_to'] < today)
        factors.setdefault(r['group_code'], []).append({'months': r['months'], 'factor_bp': r['factor_bp'], 'status': r['status'], 'usable': usable, 'note': r['note'],
                                                        'source': r['source'], 'version': r['version'], 'valid_from': r['valid_from']})
    return {'banks': tree, 'factors': factors, 'months': list(MONTHS), 'modes': MODES, 'methods': METHODS, 'surcharge': surcharge_settings(c), 'surcharge_methods': list(SURCHARGE_METHODS)}


def factor_table(c):
    """Tabla de factores vigentes por grupo y plazo, con los bancos de cada grupo (para administración)."""
    groups = {}
    for r in c.execute('SELECT group_code,bank,brand,category FROM card_products WHERE active=1 ORDER BY group_code,bank,brand,category'):
        groups.setdefault(r['group_code'], []).append('%s · %s · %s' % (r['bank'], r['brand'], r['category']))
    rows = {}
    for r in c.execute("SELECT group_code,months,factor_bp,status FROM card_factors WHERE status IN ('vigente','pendiente')"):
        rows.setdefault(r['months'], {})[r['group_code']] = {'factor_bp': r['factor_bp'], 'status': r['status']}
    meta = c.execute("SELECT source,version,valid_from FROM card_factors WHERE status='vigente' ORDER BY id DESC LIMIT 1").fetchone()
    return {'groups': {code: groups.get(code, []) for code in sorted(r[0] for r in c.execute('SELECT code FROM card_factor_groups'))},
            'rows': [{'months': m, 'factors': rows.get(m, {})} for m in MONTHS], 'source': dict(meta) if meta else None}


def _bp(value, field, low=0, high=5000):
    text = str(value).strip().replace('%', '').replace(',', '.')
    try:
        amount = Decimal(text)
    except Exception:
        amount = None
    if amount is None or not amount.is_finite() or amount.as_tuple().exponent < -2 or not low <= amount * 100 <= high:
        raise CardError('Porcentaje no válido.', 400, {field: 'Porcentaje con hasta dos decimales (%s a %s).' % (low // 100, high // 100)})
    return int(amount * 100)


def save_surcharge(c, data, user, now):
    """Configura el recargo comercial (solo administración). Cada cambio queda en un historial que no se modifica."""
    percent = _bp(data.get('percent', '0'), 'percent')
    fixed_text = str(data.get('fixed', '') or '0').strip()
    try:
        fixed = _base_cents(fixed_text) if fixed_text not in ('0', '0,00', '0.00') else 0
    except CardError:
        raise CardError('Recargo fijo no válido.', 400, {'fixed': 'Importe con hasta dos decimales.'})
    payer = str(data.get('payer', 'cliente'))
    if payer not in ('cliente', 'empresa'):
        raise CardError('Indica quién asume el costo.', 400, {'payer': 'Opción no válida.'})
    methods = data.get('methods', [])
    if isinstance(methods, str):
        methods = [m for m in methods.split(',') if m]
    if any(m not in SURCHARGE_METHODS for m in methods):
        raise CardError('Método no válido para el recargo.', 400, {'methods': 'Método no válido.'})
    dates = {}
    for key in ('valid_from', 'valid_to'):
        value = str(data.get(key, '')).strip()
        if value:
            try:
                value = date.fromisoformat(value).isoformat() if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else None
            except ValueError:
                value = None
            if not value:
                raise CardError('Fecha no válida.', 400, {key: 'Usa una fecha real con el formato AAAA-MM-DD.'})
        dates[key] = value
    if dates['valid_from'] and dates['valid_to'] and dates['valid_to'] < dates['valid_from']:
        raise CardError('La vigencia termina antes de empezar.', 400, {'valid_to': 'Fecha anterior al inicio.'})
    active = str(data.get('active', '')) in ('1', 'true', 'on')
    validated = str(data.get('validated', '')) in ('1', 'true', 'on')
    note = re.sub(r'\s+', ' ', str(data.get('note', ''))).strip()
    if len(note) < 5:
        raise CardError('Indica el motivo del cambio (al menos 5 caracteres).', 400, {'note': 'Motivo obligatorio.'})
    stamp = now.isoformat(timespec='seconds')
    values = (percent, fixed, payer, json.dumps(sorted(set(methods))), dates['valid_from'], dates['valid_to'], int(active), int(validated), note[:300])
    c.execute('INSERT INTO card_surcharge_settings(id,percent_bp,fixed_cents,payer,methods,valid_from,valid_to,active,validated,note,updated_at,updated_by) VALUES (1,?,?,?,?,?,?,?,?,?,?,?) '
              'ON CONFLICT(id) DO UPDATE SET percent_bp=excluded.percent_bp,fixed_cents=excluded.fixed_cents,payer=excluded.payer,methods=excluded.methods,valid_from=excluded.valid_from,'
              'valid_to=excluded.valid_to,active=excluded.active,validated=excluded.validated,note=excluded.note,updated_at=excluded.updated_at,updated_by=excluded.updated_by', (*values, stamp, user['id']))
    c.execute('INSERT INTO card_surcharge_history(percent_bp,fixed_cents,payer,methods,valid_from,valid_to,active,validated,note,changed_at,changed_by,actor) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
              (*values, stamp, user['id'], user['name']))
    return surcharge_settings(c)


def surcharge_history(c):
    return [dict(r, methods=json.loads(r['methods'] or '[]')) for r in c.execute('SELECT * FROM card_surcharge_history ORDER BY id DESC LIMIT 50')]
