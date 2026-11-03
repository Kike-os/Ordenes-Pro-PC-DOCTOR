"""Autorizaciones de recepción aplicables según el tipo de equipo registrado (el dato estructurado, no el texto del modelo).

Cada tipo del catálogo pertenece a una categoría con sus apartados aplicables: sistema operativo («os»), archivos y respaldos
(«files») y formateo o eliminación de datos («risk»). Lo que no aplica se oculta en el formulario, en el enlace del cliente y
en los comprobantes, y figura como «No aplica»: nunca como autorización ni como rechazo. Las decisiones registradas no se
modifican ni se borran; si en un apartado que ya no aplica consta una autorización expresa, se sigue mostrando.

Comprobantes: las órdenes registradas desde la migración 086 usan esta presentación. Las anteriores conservan su comprobante
tal como se emitió (el PDF es determinista: misma huella que el enviado) hasta que el personal genera una versión corregida,
que queda registrada con su número de revisión, motivo, responsable y las huellas del original y de la corregida."""
import copy
import json
import re

from reception import DEVICE_TYPES

SECTIONS = {'os': 'Acceso al sistema operativo', 'files': 'Acceso a archivos personales y respaldos', 'risk': 'Formateo, reinstalación y eliminación de datos'}
SHORT = {'os': 'sistema operativo', 'files': 'archivos y respaldos', 'risk': 'formateo, reinstalación o eliminación de datos'}
ORDER = ('os', 'files', 'risk')
EXCEPTION_TEXT = ('El equipo guarda información del cliente (memoria interna, cuentas, documentos escaneados o configuración) '
                  'y la intervención puede acceder a ella, modificarla o borrarla')
FALLBACK = 'otros'
# Catálogo inicial. «exception»: apartados que se piden solo si el técnico marca que el equipo guarda información del cliente.
DEFAULT = [
    {'code': 'computadoras', 'label': 'Computadoras', 'sections': ['os', 'files', 'risk'], 'exception': [],
     'types': ['portatil', 'notebook', 'gaming', 'escritorio', 'mini_pc', 'aio', 'aio_hp', 'aio_lenovo', 'aio_dell', 'servidor']},
    {'code': 'moviles', 'label': 'Tablets y celulares', 'sections': ['os', 'files', 'risk'], 'exception': [], 'types': ['tablet', 'celular']},
    {'code': 'almacenamiento', 'label': 'Discos HDD y SSD', 'sections': ['files', 'risk'], 'exception': [], 'types': ['hdd', 'ssd']},
    {'code': 'consolas', 'label': 'Consolas', 'sections': [], 'exception': ['os', 'files', 'risk'], 'types': ['consola']},
    {'code': 'impresoras', 'label': 'Impresoras', 'sections': [], 'exception': ['files', 'risk'], 'types': ['impresora']},
    {'code': 'perifericos', 'label': 'Mouse, teclado y monitor', 'sections': [], 'exception': [], 'types': ['mouse', 'teclado', 'monitor']},
    {'code': 'red', 'label': 'Equipos de red', 'sections': [], 'exception': ['files', 'risk'], 'types': ['router']},
    # Un equipo sin categoría conocida conserva todos los apartados: es preferible pedir una decisión que omitirla.
    {'code': FALLBACK, 'label': 'Otros equipos', 'sections': ['os', 'files', 'risk'], 'exception': [], 'types': ['otro']},
]
KEY = 'authorization_profiles'


def _normalize(groups):
    """Cada tipo del catálogo pertenece exactamente a una categoría; los tipos sin asignar van a «Otros equipos»."""
    groups = [dict(g, sections=[s for s in ORDER if s in g.get('sections', [])], exception=[s for s in ORDER if s in g.get('exception', [])],
                   types=[t for t in DEVICE_TYPES if t in g.get('types', [])]) for g in groups]  # orden estable: el del catálogo
    if not any(g['code'] == FALLBACK for g in groups):
        groups.append(copy.deepcopy(next(g for g in DEFAULT if g['code'] == FALLBACK)) | {'types': []})
    seen = set()
    for g in groups:
        g['types'] = [t for t in g['types'] if not (t in seen or seen.add(t))]
    missing = [t for t in DEVICE_TYPES if t not in seen]
    next(g for g in groups if g['code'] == FALLBACK)['types'].extend(missing)
    return groups


def load(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (KEY,)).fetchone()
    try:
        groups = json.loads(row['value'])['groups'] if row else copy.deepcopy(DEFAULT)
    except (ValueError, KeyError, TypeError):
        groups = copy.deepcopy(DEFAULT)
    return _normalize(groups)


def group_of(groups, kind):
    return next((g for g in groups if kind in g['types']), next(g for g in groups if g['code'] == FALLBACK))


def profile(groups, kind, exception=False):
    group = group_of(groups, kind)
    extra = [s for s in group['exception'] if s not in group['sections']]
    on = bool(exception and extra)
    return {'group': group['code'], 'label': group['label'], 'type': kind, 'type_label': DEVICE_TYPES.get(kind, kind or 'Equipo'),
            'base': list(group['sections']), 'exception_sections': extra, 'exception_available': bool(extra), 'exception': on,
            'sections': [s for s in ORDER if s in group['sections'] or (on and s in extra)]}


def exception(c, oid):
    row = c.execute('SELECT enabled,note,updated_at,actor_id FROM order_data_exceptions WHERE order_id=?', (oid,)).fetchone()
    return dict(row) if row else None


def for_order(c, oid, kind, groups=None):
    found = exception(c, oid)
    result = profile(groups or load(c), kind, bool(found and found['enabled']))
    result['exception_note'] = (found or {}).get('note', '')
    return result


def catalog(c):
    """Catálogo para el formulario: categoría de cada tipo y apartados de cada categoría."""
    groups = load(c)
    return {'sections': SECTIONS, 'exception_text': EXCEPTION_TEXT, 'types': {t: g['code'] for g in groups for t in g['types']},
            'groups': {g['code']: {'label': g['label'], 'sections': g['sections'], 'exception': [s for s in g['exception'] if s not in g['sections']]} for g in groups}}


# --- Excepción por orden -----------------------------------------------------------------------------------------------

def set_exception(c, oid, enabled, note, user, now):
    """Registra si el equipo guarda información del cliente. Devuelve True si cambió (queda en el historial de la orden)."""
    found = exception(c, oid)
    current = (bool(found and found['enabled']), (found or {}).get('note', ''))
    wanted = (bool(enabled), ' '.join(str(note or '').split())[:300] if enabled else current[1])
    if (found is None and not enabled) or current == wanted:
        return False
    c.execute('INSERT INTO order_data_exceptions(order_id,enabled,note,actor_id,updated_at) VALUES (?,?,?,?,?) '
              'ON CONFLICT(order_id) DO UPDATE SET enabled=excluded.enabled,note=excluded.note,actor_id=excluded.actor_id,updated_at=excluded.updated_at',
              (oid, int(wanted[0]), wanted[1], user['id'], now.isoformat(timespec='seconds')))
    return True


# --- Presentación en documentos ----------------------------------------------------------------------------------------

def since(c):
    row = c.execute("SELECT value FROM system_state WHERE key='authorization_layout_since'").fetchone()
    return int(row['value']) if row and str(row['value']).isdigit() else None


def corrections(c, oid):
    return [dict(r) for r in c.execute('SELECT r.revision,r.reason,r.original_sha256,r.corrected_sha256,r.created_at,u.name actor FROM receipt_corrections r '
                                        'LEFT JOIN users u ON u.id=r.actor_id WHERE r.order_id=? ORDER BY r.revision', (oid,))]


def attach(c, order, kind):
    """Añade a la orden su categoría, la presentación de su comprobante y las correcciones. `kind` es el tipo actual del equipo."""
    order['authorization_profile'] = for_order(c, order['id'], kind)
    order['receipt_corrections'] = corrections(c, order['id'])
    start = since(c)
    order['receipt_layout'] = 'dinamico' if order['receipt_corrections'] or (start is not None and int(order.get('created_at') or 0) >= start) else 'original'
    order['receipt_correctable'] = order['receipt_layout'] == 'original' and len(order['authorization_profile']['sections']) < len(ORDER)
    return order


def presentation(order):
    """(apartados visibles [(clave, título, estado, detalle)], apartados que no aplican [clave]) para el comprobante.

    Un apartado que no aplica se omite salvo que conste una autorización expresa en él; nunca se presenta como autorizado."""
    import technical_access
    rows = technical_access.sections(order.get('access_authorization'), order.get('destructive_authorization'))
    applicable = (order.get('authorization_profile') or {}).get('sections', list(ORDER))
    shown = [(key,) + rows[key] for key in ORDER if key in applicable or rows[key][1] == 'authorized']
    return shown, [key for key in ORDER if key not in [row[0] for row in shown]]


def not_applicable_text(order, keys):
    """(título, detalle) de la fila «NO APLICA» que reúne los apartados que no corresponden al tipo de equipo."""
    if not keys:
        return '', ''
    label = (order.get('authorization_profile') or {}).get('type_label') or 'Equipo'
    names = [SHORT[k] for k in keys]
    joined = names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' y ' + names[-1]
    return 'No aplica a ' + label.lower(), joined[0].upper() + joined[1:] + '. No se solicitan para este equipo y no constan como autorización.'


# --- Configuración administrativa --------------------------------------------------------------------------------------

def validate(data):
    """Valida una configuración enviada desde administración. Devuelve (categorías, errores)."""
    errors = {}
    try:
        groups = data['groups'] if isinstance(data.get('groups'), list) else json.loads(data.get('groups') or '[]')
    except (ValueError, TypeError):
        return None, {'groups': 'Configuración no válida.'}
    if not groups or len(groups) > 20:
        errors['groups'] = 'Define entre 1 y 20 categorías.'
    clean, codes, assigned = [], set(), {}
    for index, g in enumerate(groups if isinstance(groups, list) else []):
        if not isinstance(g, dict):
            errors['groups'] = 'Configuración no válida.'
            continue
        code, label = str(g.get('code', '')).strip(), ' '.join(str(g.get('label', '')).split())
        if not re.fullmatch(r'[a-z][a-z0-9_]{1,29}', code) or code in codes:
            errors['group_%d' % index] = 'Código de categoría inválido o repetido.'
        if not 2 <= len(label) <= 60:
            errors['group_%d' % index] = 'El nombre de la categoría debe tener entre 2 y 60 caracteres.'
        sections, extra, types = (g.get(k) if isinstance(g.get(k), list) else [] for k in ('sections', 'exception', 'types'))
        if any(s not in SECTIONS for s in sections + extra) or any(t not in DEVICE_TYPES for t in types):
            errors['group_%d' % index] = 'Apartado o tipo de equipo desconocido.'
        for t in types:
            if t in assigned:
                errors['group_%d' % index] = 'El tipo «%s» ya pertenece a otra categoría.' % DEVICE_TYPES.get(t, t)
            assigned[t] = code
        codes.add(code)
        clean.append({'code': code, 'label': label, 'sections': [s for s in ORDER if s in sections], 'exception': [s for s in ORDER if s in extra and s not in sections], 'types': [t for t in DEVICE_TYPES if t in types]})
    if FALLBACK not in codes:
        errors['groups'] = 'La categoría «Otros equipos» no se puede eliminar.'
    reason = ' '.join(str(data.get('reason', '')).split())
    if len(reason) < 10:
        errors['reason'] = 'Indica el motivo del cambio (mínimo 10 caracteres).'
    return _normalize(clean) if not errors else None, errors


def save(c, data, user, now):
    groups, errors = validate(data)
    if errors:
        return None, errors
    previous = load(c)
    if previous == groups:
        return previous, {}
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, json.dumps({'groups': groups}, ensure_ascii=False)))
    c.execute('INSERT INTO authorization_profile_changes(changed_at,actor_id,reason,previous,current) VALUES (?,?,?,?,?)',
              (now.isoformat(timespec='seconds'), user['id'], ' '.join(str(data.get('reason', '')).split())[:300], json.dumps(previous, ensure_ascii=False), json.dumps(groups, ensure_ascii=False)))
    return groups, {}


def describe_change(previous, current):
    """Diferencias legibles entre dos configuraciones."""
    before = {g['code']: g for g in previous}
    out = []
    for g in current:
        old = before.pop(g['code'], None)
        if not old:
            out.append('Nueva categoría «%s»' % g['label'])
            continue
        for key, name in (('sections', 'apartados'), ('exception', 'excepción'), ('types', 'tipos')):
            if old[key] != g[key]:
                out.append('«%s»: %s %s' % (g['label'], name, ', '.join(SHORT.get(v, DEVICE_TYPES.get(v, v)) for v in g[key]) or 'ninguno'))
        if old['label'] != g['label']:
            out.append('«%s» ahora se llama «%s»' % (old['label'], g['label']))
    out += ['Categoría retirada «%s»' % g['label'] for g in before.values()]
    return out


def changes(c, limit=15):
    rows = []
    for r in c.execute('SELECT a.changed_at,a.reason,a.previous,a.current,u.name actor FROM authorization_profile_changes a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT ?', (limit,)):
        rows.append({'changed_at': r['changed_at'], 'reason': r['reason'], 'actor': r['actor'] or 'Sistema', 'summary': describe_change(json.loads(r['previous']), json.loads(r['current']))})
    return rows
