"""Cliente de la API REST v2 de AZUR (https://api.azur.com.ec/api). AZUR genera el XML, lo firma con el certificado del contribuyente,
lo envía al SRI y consulta su autorización.

- Credenciales SOLO por variables de entorno: AZUR_API_KEY_EMISION (api_key «API_…» del punto de emisión, para emitir) y AZUR_CREDENCIAL
  («sk_test_…», para consultar estado, documentos y anulación). Nunca se escriben en registros, mensajes de error ni en la base.
- Mientras la emisión real no esté autorizada se rechaza una credencial de producción (sk_live_/azur_live_); la clave de acceso que
  devuelve AZUR se comprueba además en el servidor (dígito de ambiente 1 = pruebas).
- Sin dependencias: urllib de la biblioteca estándar. TRANSPORT permite sustituir la red por un AZUR simulado en las pruebas."""
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode

BASE = 'https://azur.com.ec/plataforma/api/v2'
TIMEOUT = 25
LIVE_PREFIXES = ('sk_live_', 'azur_live_')
TEST_PREFIXES = ('sk_test_', 'azur_test_')
# Códigos de estado de AZUR (estables; se ramifica por el número, no por el texto).
STATES = {-1: 'Borrador en AZUR', 0: 'En proceso', 3: 'Recibido por el SRI', 4: 'Autorizado', 5: 'No autorizado', 6: 'Error de secuencial', 7: 'Error al firmar',
          9: 'Anulado', 11: 'SRI no disponible', 15: 'Establecimiento cerrado', 17: 'Corregir la firma', 18: 'Corregir el comprobante'}
FINAL_REJECTED = (5, 6, 7, 15, 17, 18)
TRANSPORT = None  # en pruebas: función (método, url, cabeceras, cuerpo) -> (estado HTTP, dict)


class AzurError(Exception):
    def __init__(self, message, code='', status=0, retryable=False):
        super().__init__(message)
        self.code, self.status, self.retryable = code, status, retryable


def config(env=None):
    env = os.environ if env is None else env
    return {'base': (env.get('AZUR_BASE', '') or BASE).rstrip('/'), 'emission': env.get('AZUR_API_KEY_EMISION', '').strip(), 'credential': env.get('AZUR_CREDENCIAL', '').strip(),
            'live_allowed': env.get('AZUR_PRODUCCION_AUTORIZADA', '').strip() == 'SI'}


def environment(cfg):
    cred = cfg['credential']
    return 'produccion' if cred.startswith(LIVE_PREFIXES) else 'pruebas' if cred.startswith(TEST_PREFIXES) else ''


def status(env=None):
    """Estado sin secretos, apto para la interfaz."""
    cfg = config(env)
    env_name = environment(cfg)
    problems = []
    if not cfg['emission']:
        problems.append('Falta la variable AZUR_API_KEY_EMISION (api_key del punto de emisión de PRUEBAS).')
    elif not cfg['emission'].startswith('API_'):
        problems.append('AZUR_API_KEY_EMISION no tiene el formato del punto de emisión (empieza con «API_»).')
    if not cfg['credential']:
        problems.append('Falta la variable AZUR_CREDENCIAL (credencial sk_test_ de la API v2).')
    elif env_name == 'produccion' and not cfg['live_allowed']:
        problems.append('La credencial es de PRODUCCIÓN y la emisión real no está autorizada: no se usa.')
    elif not env_name:
        problems.append('AZUR_CREDENCIAL no tiene un formato reconocido (sk_test_…).')
    return {'configured': not problems, 'emission_key': bool(cfg['emission']), 'credential': bool(cfg['credential']), 'environment': env_name,
            'host': re.sub(r'^https?://', '', cfg['base']).split('/')[0], 'problems': problems}


def _guard(cfg):
    if environment(cfg) == 'produccion' and not cfg['live_allowed']:
        raise AzurError('La credencial de AZUR es de producción y la emisión real no está autorizada.', 'produccion_no_autorizada')


def _request(cfg, method, path, key='credential', body=None, query=None, idem=''):
    """Llamada a AZUR. Devuelve (estado HTTP, dict). Los errores nunca incluyen la credencial ni el cuerpo enviado."""
    _guard(cfg)
    secret = cfg['emission'] if key == 'emission' else cfg['credential']
    if not secret:
        raise AzurError('Falta configurar la credencial de AZUR (%s).' % ('AZUR_API_KEY_EMISION' if key == 'emission' else 'AZUR_CREDENCIAL'), 'sin_credencial')
    url = cfg['base'] + path + ('?' + urlencode(query) if query else '')
    headers = {'X-Api-Key': secret, 'Accept': 'application/json', 'User-Agent': 'OrdenesPro-PC-DOCTOR/1'}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if idem:
        headers['Idempotency-Key'] = idem
    if TRANSPORT is not None:
        return TRANSPORT(method, url, headers, body)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            code = resp.status
    except urllib.error.HTTPError as error:
        raw, code = error.read(), error.code
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise AzurError('No hay conexión con AZUR (%s). Se puede volver a intentar sin duplicar la factura.' % type(error).__name__, 'sin_conexion', 0, True)
    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        payload = {}
    return code, payload


def _check(code, payload):
    """Convierte la respuesta en datos o en AzurError (con el código estable de AZUR)."""
    if code == 429:
        raise AzurError('AZUR limita los intentos del mismo comprobante (5 por minuto). Espera un minuto y vuelve a intentar.', 'limite', code, True)
    if isinstance(payload, dict) and payload.get('ok') is False:
        err = payload.get('error') or {}
        raise AzurError(str(err.get('mensaje') or 'AZUR rechazó la operación.')[:400], str(err.get('codigo') or ''), code, bool(err.get('reintentable')))
    if code >= 500:
        raise AzurError('AZUR no respondió correctamente (HTTP %d). Se puede reintentar.' % code, 'servidor', code, True)
    if code in (401, 403):
        raise AzurError('La credencial de AZUR falta, no es válida o no tiene permiso para esta operación.', 'credencial_invalida', code)
    if code >= 400:
        raise AzurError('AZUR rechazó la solicitud (HTTP %d).' % code, 'solicitud', code)
    return payload.get('datos', payload) if isinstance(payload, dict) else payload


def emit_invoice(cfg, payload, idem):
    """POST /factura/emision (api_key del punto de emisión). Devuelve la clave de acceso o lanza AzurError con los errores de AZUR."""
    code, data = _request(cfg, 'POST', '/factura/emision', 'emission', payload, idem=idem)
    if code == 429:
        _check(code, data)
    if isinstance(data, dict) and data.get('creado'):
        key = str(data.get('claveacceso') or '')
        if not re.fullmatch(r'\d{49}', key):
            raise AzurError('AZUR no devolvió una clave de acceso válida.', 'respuesta_invalida', code)
        return key
    errors = data.get('errors') if isinstance(data, dict) else None
    text = '; '.join(str(v) for v in (errors.values() if isinstance(errors, dict) else errors or [])) or 'AZUR no creó el comprobante.'
    occupied = bool(re.search(r'secuencial.{0,30}(ocupado|existe|duplicad|registrad)', text, re.I))
    raise AzurError(text[:400], 'secuencial_ocupado' if occupied else 'no_creado', code)


def consult(cfg, access_key):
    """POST /consulta/comprobante (api_key de emisión): estado y enlaces por clave de acceso."""
    code, data = _request(cfg, 'POST', '/consulta/comprobante', 'emission', {'claveacceso': access_key})
    return _check(code, data)


def find_invoice(cfg, text):
    """Id interno de AZUR de una factura buscando por clave de acceso o por número (GET /facturas?buscar=). None si no está."""
    code, data = _request(cfg, 'GET', '/facturas', query={'buscar': text, 'limite': 5})
    rows = _check(code, data)
    if isinstance(rows, dict):
        rows = rows.get('documentos') or rows.get('items') or rows.get('resultados') or []
    for row in rows or []:
        if isinstance(row, dict) and text in (str(row.get('claveacceso', '')), str(row.get('secuencial', '')), str(row.get('numero', ''))):
            return int(row['id'])
    return None


def state(cfg, doc_id, live=False):
    code, data = _request(cfg, 'GET', '/factura/%d/estado' % int(doc_id), query={'sri': 1} if live else None)
    return _check(code, data)


def document(cfg, doc_id, kind):
    """PDF del RIDE ('pdf'), XML autorizado ('xml_autorizado') o firmado ('xml_firmado'), en base64."""
    path = '/factura/%d/%s' % (int(doc_id), 'pdf' if kind == 'pdf' else 'xml')
    query = {'base64': 1}
    if kind == 'xml_firmado':
        query['tipo'] = 'firmado'
    code, data = _request(cfg, 'GET', path, query=query)
    data = _check(code, data)
    content = data.get('contenido') or data.get('base64') or data.get('archivo') or data.get('pdf') or data.get('xml') if isinstance(data, dict) else None
    if not content:
        raise AzurError('AZUR no devolvió el documento (%s).' % kind, 'sin_documento', code, True)
    return str(content)


def annul(cfg, doc_id, idem):
    code, data = _request(cfg, 'POST', '/factura/%d/anular' % int(doc_id), idem=idem)
    return _check(code, data)


def reprocess(cfg, doc_id, idem):
    code, data = _request(cfg, 'POST', '/factura/%d/reprocesar' % int(doc_id), idem=idem)
    return _check(code, data)


def ping(cfg):
    """Prueba de conexión con la credencial (GET /secuenciales): no emite ni cambia nada."""
    code, data = _request(cfg, 'GET', '/secuenciales')
    return _check(code, data)


def environment_of_key(access_key):
    """Dígito de ambiente de la clave de acceso del SRI (posición 24): '1' pruebas, '2' producción."""
    return access_key[23] if re.fullmatch(r'\d{49}', access_key or '') else ''
