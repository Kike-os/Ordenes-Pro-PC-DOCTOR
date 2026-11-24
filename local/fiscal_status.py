"""Smart Fiscal Status 5.0 — estado REAL de la integración tributaria (docs/SMART-FISCAL-STATUS.md).

Sustituye el aviso fijo de producción por un indicador conectado al servidor, con cuatro niveles:
- verde «Operativo»: la última comprobación con AZUR fue correcta, reciente y rápida;
- amarillo «Advertencia»: respuesta lenta, comprobación desactualizada, fallos intermitentes recientes, el SRI reportado como no disponible
  en respuestas recientes de AZUR o advertencias de configuración;
- rojo «Incidencia crítica»: la última comprobación falló (sin conexión, credencial rechazada, servicio no disponible) o la integración no
  está configurada;
- gris «Sin verificar»: no hay ninguna comprobación.
Nunca se muestra verde sin una comprobación satisfactoria.

La comprobación es de SOLO LECTURA: GET /secuenciales de AZUR (la misma prueba de conexión de Configuración), que no emite, no consume
secuenciales ni cambia nada. Se hace como mucho una vez por minuto (botón «Actualizar estado») y, automáticamente, según el intervalo
configurado (5 a 60 minutos). El SRI no se consulta directamente: su estado se infiere de las respuestas de AZUR en las consultas de facturas
(estado 11 «SRI no disponible»), y si no hay datos se muestra «sin verificar».

El estado del sistema es independiente del estado tributario de cada factura: una factura autorizada sigue autorizada aunque después AZUR o
el SRI fallen. Resultados e incidencias se guardan en system_state (sin migraciones), sin secretos."""
import json
import time
from datetime import datetime, timedelta

LEVELS = {'verde': 'Operativo', 'amarillo': 'Advertencia', 'rojo': 'Incidencia crítica', 'gris': 'Sin verificar'}
MIN_GAP = 60                    # segundos mínimos entre dos comprobaciones en vivo
SLOW_MS = 3000                  # más lento: advertencia
INTERVALS = (5, 10, 15, 30, 60)
DEFAULT_INTERVAL = 10
INCIDENTS = 30                  # historial guardado
KEY_STATE, KEY_HISTORY, KEY_INTERVAL = 'fiscal_status', 'fiscal_status_incidents', 'fiscal_status_interval'
AUTH_CODES = (401, 403)


class FiscalStatusError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _get(c, key, default):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else default
    except (TypeError, ValueError):
        return default


def _set(c, key, value):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value, ensure_ascii=False)))


def interval(c):
    value = _get(c, KEY_INTERVAL, DEFAULT_INTERVAL)
    return value if value in INTERVALS else DEFAULT_INTERVAL


def set_interval(c, minutes):
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 0
    if minutes not in INTERVALS:
        raise FiscalStatusError('Elige un intervalo de %s minutos.' % ', '.join(map(str, INTERVALS)))
    _set(c, KEY_INTERVAL, minutes)
    return minutes


def _iso(now):
    return now.isoformat(timespec='seconds')


def _classify(error):
    """(nivel, motivo, autenticación) de un fallo de AZUR, sin secretos."""
    status = getattr(error, 'status', 0) or 0
    code = getattr(error, 'code', '') or ''
    if code == 'sin_credencial' or code == 'produccion_no_autorizada':
        return 'rojo', str(error), 'sin_configurar'
    if status in AUTH_CODES:
        return 'rojo', 'AZUR rechazó la credencial (HTTP %d). Revisa la credencial en la configuración del servidor.' % status, 'rechazada'
    if code == 'sin_conexion' or status == 0:
        return 'rojo', 'No hay conexión con AZUR (sin respuesta del servicio).', 'desconocida'
    if status >= 500:
        return 'rojo', 'AZUR no está disponible (HTTP %d).' % status, 'desconocida'
    return 'amarillo', 'AZUR respondió con una advertencia (HTTP %d): %s' % (status, str(error)[:160]), 'aceptada'


def check(c, now, env=None, force=False):
    """Comprobación en vivo de solo lectura. Respeta MIN_GAP salvo que no haya ninguna previa. Devuelve el estado actualizado."""
    import azur_client as az
    state = _get(c, KEY_STATE, {})
    last = state.get('checked_epoch') or 0
    if last and time.time() - last < MIN_GAP:
        return status(c, now, env, throttled=True)
    cfg = az.config(env)
    st = az.status(env)
    started = time.monotonic()
    result = {'checked_at': _iso(now), 'checked_epoch': time.time()}
    if not st['configured']:
        result.update(level='rojo', reason='La integración con AZUR no está configurada: ' + ' '.join(st['problems']), auth='sin_configurar', latency_ms=None, ok=False)
    else:
        try:
            az.ping(cfg)
            ms = int((time.monotonic() - started) * 1000)
            result.update(level='amarillo' if ms >= SLOW_MS else 'verde', reason='Respuesta lenta de AZUR (%d ms).' % ms if ms >= SLOW_MS else '',
                          auth='aceptada', latency_ms=ms, ok=True)
        except az.AzurError as error:
            level, reason, auth = _classify(error)
            result.update(level=level, reason=reason, auth=auth, latency_ms=int((time.monotonic() - started) * 1000), ok=False, http=getattr(error, 'status', 0) or 0)
    if result['ok']:
        result['last_ok'] = result['checked_at']
    else:
        result['last_ok'] = state.get('last_ok', '')
        history = _get(c, KEY_HISTORY, [])
        history.insert(0, {'at': result['checked_at'], 'level': result['level'], 'reason': result['reason']})
        _set(c, KEY_HISTORY, history[:INCIDENTS])
    if state and state.get('ok') is False and result['ok']:
        history = _get(c, KEY_HISTORY, [])
        history.insert(0, {'at': result['checked_at'], 'level': 'verde', 'reason': 'Conexión con AZUR restablecida.'})
        _set(c, KEY_HISTORY, history[:INCIDENTS])
    _set(c, KEY_STATE, result)
    return status(c, now, env)


def _sri(c, now):
    """Estado del SRI inferido de las respuestas de AZUR en las consultas de facturas de las últimas 24 horas."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='azur_operations'").fetchone():
        return {'level': 'gris', 'label': 'Sin verificar', 'detail': 'No hay registros de consultas a AZUR.'}
    since = _iso(now - timedelta(hours=24))
    rows = c.execute("SELECT code,result,created_at FROM azur_operations WHERE action='consultar' AND created_at>=? ORDER BY id DESC LIMIT 20", (since,)).fetchall()
    if not rows:
        return {'level': 'gris', 'label': 'Sin verificar', 'detail': 'No se puede consultar el SRI directamente; no hubo consultas de facturas en las últimas 24 horas.'}
    latest = rows[0]
    if str(latest['code']) == '11':
        return {'level': 'amarillo', 'label': 'No disponible según AZUR', 'detail': 'La última consulta (%s) devolvió «SRI no disponible».' % latest['created_at'][:16].replace('T', ' ')}
    if latest['result'] == 'ok':
        return {'level': 'verde', 'label': 'Respondió (vía AZUR)', 'detail': 'La última consulta de una factura (%s) obtuvo respuesta del SRI a través de AZUR.' % latest['created_at'][:16].replace('T', ' ')}
    return {'level': 'gris', 'label': 'Sin confirmar', 'detail': 'Las consultas recientes no permiten confirmar el estado del SRI.'}


def status(c, now, env=None, throttled=False):
    """Estado actual SIN consultar a AZUR (lo guardado), con el nivel recalculado por antigüedad."""
    import azur_client as az
    state = _get(c, KEY_STATE, {})
    minutes = interval(c)
    st = az.status(env)
    out = {'interval': minutes, 'intervals': list(INTERVALS), 'throttled': throttled, 'environment': 'produccion' if st.get('environment') == 'produccion' else (st.get('environment') or ''),
           'configured': st['configured'], 'history': _get(c, KEY_HISTORY, [])[:10], 'sri': _sri(c, now), 'min_gap': MIN_GAP}
    age = 10 ** 6
    if not state:
        out.update(level='gris', reason='Todavía no hay una comprobación de la conexión con AZUR.', checked_at='', last_ok='', latency_ms=None, auth='sin_verificar', stale=True)
    else:
        try:
            age = (now - datetime.fromisoformat(state['checked_at'])).total_seconds() / 60
        except (KeyError, TypeError, ValueError):
            age = 10 ** 6
        stale = age > max(2 * minutes, 15)
        level, reason = state.get('level', 'gris'), state.get('reason', '')
        if stale and level == 'verde':
            level, reason = 'amarillo', 'La última comprobación tiene más de %d minutos: información desactualizada.' % int(age)
        recent_fail = any(h['level'] == 'rojo' and h['at'] >= _iso(now - timedelta(hours=1)) for h in _get(c, KEY_HISTORY, []))
        if level == 'verde' and recent_fail:
            level, reason = 'amarillo', 'Hubo fallos de conexión en la última hora (intermitencia); ahora responde.'
        if level == 'verde' and out['sri']['level'] == 'amarillo':
            level, reason = 'amarillo', out['sri']['detail']
        out.update(level=level, reason=reason, checked_at=state.get('checked_at', ''), last_ok=state.get('last_ok', ''), latency_ms=state.get('latency_ms'),
                   auth=state.get('auth', 'sin_verificar'), stale=stale)
    if not st['configured'] and out['level'] != 'gris':
        out.update(level='rojo', reason='La integración con AZUR no está configurada en el servidor: ' + ' '.join(st['problems']), auth='sin_configurar')
    out['label'] = LEVELS[out['level']]
    out['auth_label'] = {'aceptada': 'Credencial aceptada', 'rechazada': 'Credencial rechazada', 'sin_configurar': 'Sin configurar',
                         'desconocida': 'No comprobada (sin respuesta)', 'sin_verificar': 'Sin verificar'}.get(out['auth'], out['auth'])
    out['due'] = not state or age >= minutes
    return out


def invoice_state(inv):
    """Estado tributario propio de la factura (independiente del estado de la integración)."""
    labels = {'autorizado': 'Autorizada por el SRI', 'pendiente': 'Pendiente de envío', 'enviado': 'Enviada · en espera del SRI', 'rechazado': 'Rechazada por el SRI',
              'borrador': 'Borrador (sin emitir)', 'descartado': 'Descartada'}
    return {'code': inv.get('status', ''), 'label': labels.get(inv.get('status', ''), inv.get('status', '')),
            'kept': inv.get('status') == 'autorizado'}
