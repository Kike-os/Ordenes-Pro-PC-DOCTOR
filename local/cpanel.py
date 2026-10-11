"""Consulta de solo lectura a cPanel UAPI (Email::list_pops_with_disk) para conocer el uso real de un buzón.

La autenticación usa un token de API del usuario propietario de cPanel (cabecera «Authorization: cpanel usuario:token»).
Nunca se usa la contraseña del buzón, el token no sale del servidor y los errores se clasifican sin incluir secretos.
"""
import json
import os
import re
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TIMEOUT = 8


class CpanelError(Exception):
    """kind: sin_configurar, red, tls, autenticacion, permisos, vacio, no_encontrada, respuesta."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def settings(env=None):
    env = os.environ if env is None else env
    host = str(env.get('CPANEL_HOST', '')).strip().lower()
    try:
        port = int(str(env.get('CPANEL_PORT', '2083')).strip() or 2083)
    except ValueError:
        port = 0
    return {'host': host, 'port': port, 'user': str(env.get('CPANEL_USER', '')).strip(), 'token': str(env.get('CPANEL_TOKEN', '')).strip()}


def configured(env=None):
    config = settings(env)
    return bool(config['host'] and config['user'] and config['token'])


def status(env=None):
    """Estado sin secretos, apto para mostrarse en Configuración."""
    config = settings(env)
    return {'configured': configured(env), 'host': config['host'], 'port': config['port'], 'user': config['user'], 'token': bool(config['token'])}


def mailbox_usage(address, env=None):
    """Uso y cuota del buzón `address` en bytes: {'used': int, 'limit': int|None}. Solo lectura."""
    config = settings(env)
    if not configured(env):
        raise CpanelError('sin_configurar', 'El acceso a cPanel no está configurado en el servidor (CPANEL_HOST, CPANEL_USER y CPANEL_TOKEN).')
    if not re.fullmatch(r'[a-z0-9.-]{1,253}', config['host']) or config['port'] not in (2083, 443) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', config['user']) or not re.fullmatch(r'[A-Za-z0-9]{16,128}', config['token']):
        raise CpanelError('sin_configurar', 'Los datos de acceso a cPanel no tienen un formato válido. Solo se admite HTTPS por el puerto 2083.')
    local, _, domain = str(address).strip().lower().partition('@')
    if not local or not domain:
        raise CpanelError('sin_configurar', 'La cuenta de correo configurada no es válida.')
    url = 'https://' + config['host'] + ':' + str(config['port']) + '/execute/Email/list_pops_with_disk?' + urlencode({'domain': domain, 'no_validate': '1'})
    request = Request(url, headers={'Authorization': 'cpanel ' + config['user'] + ':' + config['token'], 'Accept': 'application/json', 'User-Agent': 'OrdenesPro/1.0'})
    try:
        with urlopen(request, timeout=TIMEOUT, context=ssl.create_default_context()) as response:
            raw = response.read(2_000_001)
    except HTTPError as error:
        if error.code in (401, 403):
            raise CpanelError('autenticacion', 'cPanel rechazó el token de API (HTTP ' + str(error.code) + '). Revisa el usuario de cPanel y genera un token nuevo.') from None
        raise CpanelError('respuesta', 'cPanel respondió con un error HTTP ' + str(error.code) + '.') from None
    except ssl.SSLError:
        raise CpanelError('tls', 'El certificado de ' + config['host'] + ' no es válido para una conexión segura.') from None
    except (URLError, socket.timeout, TimeoutError, OSError) as error:
        reason = getattr(error, 'reason', error)
        if isinstance(reason, ssl.SSLError):
            raise CpanelError('tls', 'El certificado de ' + config['host'] + ' no es válido para una conexión segura.') from None
        raise CpanelError('red', 'No se pudo conectar con cPanel en ' + config['host'] + ':' + str(config['port']) + ' (sin respuesta o conexión bloqueada).') from None
    if len(raw) > 2_000_000:
        raise CpanelError('respuesta', 'cPanel devolvió una respuesta demasiado grande.')
    try:
        payload = json.loads(raw)
    except ValueError:
        # Sin token válido cPanel entrega su página de acceso en HTML en lugar de JSON.
        raise CpanelError('autenticacion', 'cPanel no aceptó la sesión: devolvió su página de acceso en lugar de datos. Revisa el usuario y el token.') from None
    if not isinstance(payload, dict) or payload.get('status') != 1:
        errors = ' '.join(str(item) for item in (payload.get('errors') or [])) if isinstance(payload, dict) else ''
        if re.search(r'permission|access|denied|feature|token', errors, re.I):
            raise CpanelError('permisos', 'El token de cPanel no tiene permiso para consultar las cuentas de correo.')
        raise CpanelError('respuesta', 'cPanel no pudo completar la consulta de almacenamiento.')
    rows = payload.get('data') if isinstance(payload.get('data'), list) else []
    if not rows:
        raise CpanelError('vacio', 'cPanel no devolvió cuentas de correo para el dominio ' + domain + '. Ese dominio puede pertenecer a otro usuario de cPanel.')
    row = next((item for item in rows if isinstance(item, dict) and str(item.get('email', '')).lower() == local + '@' + domain), None)
    if row is None:
        raise CpanelError('no_encontrada', 'La cuenta ' + local + '@' + domain + ' no pertenece al usuario de cPanel consultado.')
    try:
        used = int(float(row.get('_diskused', 0)))
        raw_limit = str(row.get('_diskquota', row.get('diskquota', '')))
        limit = None if raw_limit.strip().lower() in ('', '0', '0.00', 'unlimited', 'ilimitado') else int(float(raw_limit))
    except (TypeError, ValueError):
        raise CpanelError('respuesta', 'cPanel devolvió el uso del buzón en un formato no reconocido.') from None
    if used < 0 or (limit is not None and limit <= 0):
        raise CpanelError('respuesta', 'cPanel devolvió valores de almacenamiento no válidos.')
    return {'used': used, 'limit': limit}


def diagnose(address, env=None):
    """Pasos del diagnóstico para Configuración. Devuelve (ok, pasos, error)."""
    config, steps = settings(env), []
    steps.append('Configuración: ' + ('host ' + config['host'] + ':' + str(config['port']) + ', usuario de cPanel ' + config['user'] + ', token ' + ('cargado' if config['token'] else 'ausente') if config['host'] or config['user'] else 'sin datos de acceso a cPanel'))
    try:
        usage = mailbox_usage(address, env)
    except CpanelError as error:
        return False, steps, str(error), error.kind
    steps.append('HTTPS y certificado: válidos')
    steps.append('Autenticación con token: aceptada')
    steps.append('Email::list_pops_with_disk: cuenta ' + address + ' encontrada')
    steps.append('Uso: ' + str(usage['used']) + ' bytes · cuota: ' + (str(usage['limit']) + ' bytes' if usage['limit'] else 'sin límite configurado'))
    return True, steps, '', ''
