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


STATES = {'confirmado': 'Confirmado', 'verificado': 'Verificado · falta confirmar', 'pendiente': 'Pendiente de confirmar', 'sin_configurar': 'Sin configurar',
          'inactivo': 'Inactivo'}
SOURCE = 'DATAFAST · tabla de factores de diferido con intereses'


def _last_confirmation(c, factor_id):
    return c.execute('SELECT * FROM card_factor_confirmations WHERE factor_id=? ORDER BY id DESC LIMIT 1', (factor_id,)).fetchone()


def factor_state(row, confirmation, today):
    """Estado real de un factor guardado. «verificado» (cargado de la tabla oficial, sin confirmación administrativa) sí sirve para cobrar;
    «pendiente» (sin valor) e «inactivo» (fuera de su vigencia) no. «confirmado» exige que la confirmación sea del mismo porcentaje."""
    if row is None:
        return 'sin_configurar'
    if row['status'] == 'pendiente' or row['factor_bp'] is None:
        return 'pendiente'
    if row['valid_from'] > today or (row['valid_to'] and row['valid_to'] < today):
        return 'inactivo'
    return 'confirmado' if confirmation and confirmation['factor_bp'] == row['factor_bp'] else 'verificado'


def _table_meta(c):
    """Versión de la tabla que comparten la mayoría de los factores vigentes (una corrección suelta no cambia la versión de la tabla)."""
    return c.execute("SELECT source,version,valid_from FROM card_factors WHERE status='vigente' GROUP BY source,version,valid_from ORDER BY COUNT(*) DESC,MAX(id) DESC LIMIT 1").fetchone()


def factor_table(c, today=None):
    """Tabla de factores por grupo y plazo con el estado de cada uno y los bancos de cada grupo (para administración)."""
    today = today or date.today().isoformat()
    groups = {}
    for r in c.execute('SELECT group_code,bank,brand,category FROM card_products WHERE active=1 ORDER BY group_code,bank,brand,category'):
        groups.setdefault(r['group_code'], []).append('%s · %s · %s' % (r['bank'], r['brand'], r['category']))
    confirmations = {r['factor_id']: r for r in c.execute('SELECT f.* FROM card_factor_confirmations f JOIN (SELECT factor_id,MAX(id) id FROM card_factor_confirmations '
                                                           'GROUP BY factor_id) last ON last.id=f.id')}
    rows = {}
    for r in c.execute("SELECT * FROM card_factors WHERE status IN ('vigente','pendiente')"):
        conf = confirmations.get(r['id'])
        state = factor_state(r, conf, today)
        rows.setdefault(r['months'], {})[r['group_code']] = {
            'id': r['id'], 'factor_bp': r['factor_bp'], 'status': r['status'], 'state': state, 'usable': state in ('confirmado', 'verificado'),
            'valid_from': r['valid_from'], 'valid_to': r['valid_to'], 'version': r['version'], 'source': r['source'], 'note': r['note'],
            'confirmed_at': conf['confirmed_at'] if conf and state == 'confirmado' else '', 'confirmed_by': conf['actor'] if conf and state == 'confirmado' else ''}
    meta = _table_meta(c)
    codes = sorted(r[0] for r in c.execute('SELECT code FROM card_factor_groups'))
    # Combinaciones de cada grupo ya separadas (banco, marca y categoría) y un resumen calculado con lo guardado: nada se estima ni se rellena.
    combos = {code: [] for code in codes}
    for r in c.execute('SELECT group_code,bank,brand,category FROM card_products WHERE active=1 ORDER BY group_code,bank,brand,category'):
        combos.setdefault(r['group_code'], []).append({'bank': r['bank'], 'brand': r['brand'], 'category': r['category']})
    cells = [(m, code, rows.get(m, {}).get(code)) for m in MONTHS for code in codes]
    states = {key: 0 for key in STATES}
    for _, _, f in cells:
        states[f['state'] if f else 'sin_configurar'] += 1
    summary = {'groups': sum(1 for code in codes if combos.get(code)), 'groups_total': len(codes),
               'banks': c.execute('SELECT COUNT(DISTINCT bank) FROM card_products WHERE active=1').fetchone()[0],
               'combinations': sum(len(v) for v in combos.values()), 'months': len([m for m in MONTHS if any(f and f['usable'] for mm, _, f in cells if mm == m)]),
               'months_total': len(MONTHS), 'total': len(cells), 'states': states, 'usable': states['confirmado'] + states['verificado'],
               'pending': states['pendiente'], 'missing': states['sin_configurar']}
    return {'groups': {code: groups.get(code, []) for code in codes}, 'combos': combos, 'summary': summary, 'states': STATES,
            'rows': [{'months': m, 'factors': rows.get(m, {})} for m in MONTHS], 'source': dict(meta) if meta else None}


def factor_history(c, group_code, months):
    """Versiones y confirmaciones de un grupo y plazo, de la más reciente a la más antigua (para la ventana de validación)."""
    versions = [dict(r) for r in c.execute('SELECT id,factor_bp,status,valid_from,valid_to,version,note,updated_at FROM card_factors WHERE group_code=? AND months=? ORDER BY id DESC',
                                           (group_code, months))]
    ids = [v['id'] for v in versions] or [0]
    marks = ','.join('?' * len(ids))
    confirmations = [dict(r) for r in c.execute('SELECT id,factor_id,factor_bp,previous_bp,action,note,confirmed_at,actor FROM card_factor_confirmations WHERE factor_id IN (%s) '
                                                'ORDER BY id DESC LIMIT 50' % marks, ids)]
    return {'versions': versions, 'confirmations': confirmations}


def _review_note(data):
    if str(data.get('checked', '')) not in ('1', 'true', 'on'):
        raise CardError('Marca que cotejaste los valores con la tabla original de DATAFAST.', 400, {'checked': 'Confirmación obligatoria.'})
    note = re.sub(r'\s+', ' ', str(data.get('note', ''))).strip()
    if len(note) < 5:
        raise CardError('Indica el documento o el motivo (al menos 5 caracteres).', 400, {'note': 'Documento o motivo obligatorio.'})
    return note[:300]


def confirm_factors(c, data, user, now):
    """Confirmación administrativa de uno o varios factores vigentes. Cada uno llega con el porcentaje que vio el administrador: si cambió
    mientras lo revisaba no se confirma nada. Todo se valida antes de escribir. Un factor pendiente no se confirma: primero se completa."""
    raw = data.get('items', '')
    pairs = [p for p in (raw.split(',') if isinstance(raw, str) else raw) if str(p).strip()]
    items = []
    for pair in pairs:
        m = re.fullmatch(r'(\d{1,9}):(\d{1,5})', str(pair).strip())
        if not m:
            raise CardError('Selección de factores no válida.', 400)
        items.append((int(m.group(1)), int(m.group(2))))
    if not items:
        raise CardError('No hay factores por confirmar en la selección.', 400)
    if len(items) > 200 or len({fid for fid, _ in items}) != len(items):
        raise CardError('Selección de factores no válida.', 400)
    note = _review_note(data)
    today, stamp = now.date().isoformat(), now.isoformat(timespec='seconds')
    todo, skipped = [], 0
    for fid, bp in items:
        row = c.execute('SELECT * FROM card_factors WHERE id=?', (fid,)).fetchone()
        if not row or row['status'] not in ('vigente', 'pendiente'):
            raise CardError('Un factor de la selección fue reemplazado mientras lo revisabas: actualiza la tabla.', 409)
        label = 'grupo %s a %d meses' % (row['group_code'], row['months'])
        state = factor_state(row, _last_confirmation(c, fid), today)
        if state == 'pendiente':
            raise CardError('El factor del %s está pendiente: primero complétalo con su porcentaje.' % label, 409)
        if state == 'inactivo':
            raise CardError('El factor del %s no está vigente en esta fecha.' % label, 409)
        if row['factor_bp'] != bp:
            raise CardError('El porcentaje del %s cambió mientras lo revisabas: actualiza la tabla.' % label, 409)
        if state == 'confirmado':
            skipped += 1
        else:
            todo.append(row)
    for row in todo:
        c.execute('INSERT INTO card_factor_confirmations(factor_id,factor_bp,previous_bp,action,note,confirmed_at,confirmed_by,actor) VALUES (?,?,NULL,?,?,?,?,?)',
                  (row['id'], row['factor_bp'], 'confirmado', note, stamp, user['id'], user['name']))
    return {'confirmed': len(todo), 'skipped': skipped}


def edit_factor(c, data, user, now):
    """Completa, corrige o configura el factor de un grupo y plazo desde la ventana de validación (solo administración).
    - Pendiente sin valor: se completa en la misma fila (misma versión de la tabla).
    - Vigente con otro valor: la fila anterior queda «reemplazado» (no se borra) y se crea una nueva vigente.
    - Sin fila: se crea vigente.
    El nuevo valor queda confirmado por quien lo validó. Los cobros ya registrados no se tocan: guardan su propio cálculo."""
    group = str(data.get('group', '')).strip().upper()
    if not c.execute('SELECT 1 FROM card_factor_groups WHERE code=?', (group,)).fetchone():
        raise CardError('Grupo no válido.', 400, {'group': 'Grupo no válido.'})
    try:
        months = int(str(data.get('months', '')))
    except ValueError:
        months = 0
    if months not in MONTHS:
        raise CardError('Plazo no válido.', 400, {'months': 'Plazo no válido.'})
    bp = _bp(data.get('percent', ''), 'percent', 1, 10000)
    row = c.execute("SELECT * FROM card_factors WHERE group_code=? AND months=? AND status IN ('vigente','pendiente')", (group, months)).fetchone()
    if str(row['id'] if row else '') != str(data.get('expected_id', '') or ''):
        raise CardError('Ese factor cambió mientras lo revisabas: actualiza la tabla.', 409)
    if row and row['status'] == 'vigente' and row['factor_bp'] == bp:
        raise CardError('Es el mismo porcentaje guardado: usa «Confirmar este valor».', 400, {'percent': 'Mismo porcentaje.'})
    meta = _table_meta(c)
    version = re.sub(r'\s+', ' ', str(data.get('version', '') or '')).strip()[:20] or (row['version'] if row else (meta['version'] if meta else ''))
    if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z .\-]{0,19}', version or ''):
        raise CardError('Indica la versión de la tabla DATAFAST.', 400, {'version': 'Versión de la tabla (ej.: 6.2).'})
    valid_from = str(data.get('valid_from', '') or '').strip() or (row['valid_from'] if row else (meta['valid_from'] if meta else now.date().isoformat()))
    try:
        valid_from = date.fromisoformat(valid_from).isoformat() if re.fullmatch(r'\d{4}-\d{2}-\d{2}', valid_from) else None
    except ValueError:
        valid_from = None
    if not valid_from:
        raise CardError('Fecha no válida.', 400, {'valid_from': 'Usa una fecha real con el formato AAAA-MM-DD.'})
    note = _review_note(data)
    stamp = now.isoformat(timespec='seconds')
    if row and row['status'] == 'pendiente' and version == row['version']:
        c.execute("UPDATE card_factors SET factor_bp=?,status='vigente',valid_from=?,note=?,updated_at=?,updated_by=? WHERE id=? AND status='pendiente'",
                  (bp, valid_from, note, stamp, user['id'], row['id']))
        fid, action, previous = row['id'], 'completado', None
    else:
        if row:
            c.execute("UPDATE card_factors SET status='reemplazado',updated_at=?,updated_by=? WHERE id=?", (stamp, user['id'], row['id']))
        label, n = version, 1
        while c.execute('SELECT 1 FROM card_factors WHERE group_code=? AND months=? AND version=?', (group, months, label)).fetchone():
            n += 1
            label = ('%s · corr. %d' % (version, n - 1))[:40]
        cur = c.execute("INSERT INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,note,updated_at,updated_by) VALUES (?,?,?,'vigente',?,?,?,?,?,?)",
                        (group, months, bp, valid_from, row['source'] if row else SOURCE, label, note, stamp, user['id']))
        fid, action, previous = cur.lastrowid, 'corregido' if row else 'configurado', row['factor_bp'] if row else None
    c.execute('INSERT INTO card_factor_confirmations(factor_id,factor_bp,previous_bp,action,note,confirmed_at,confirmed_by,actor) VALUES (?,?,?,?,?,?,?,?)',
              (fid, bp, previous, action, note, stamp, user['id'], user['name']))
    return {'id': fid, 'group': group, 'months': months, 'factor_bp': bp, 'action': action}


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
