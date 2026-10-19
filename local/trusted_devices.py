"""Dispositivos de confianza para la verificación en dos pasos.

Tras validar el código, la persona puede marcar «Confiar en este equipo durante 30 días»: el navegador recibe un token aleatorio en una
cookie HttpOnly, Secure y SameSite=Strict limitada a las rutas de inicio de sesión, y el servidor guarda solo su huella. Mientras siga
vigente, ese navegador no vuelve a pedir el código; la contraseña sigue siendo obligatoria. Un equipo desconocido siempre lo pide.

La confianza se revoca al cambiar o restablecer la contraseña, al cerrar sesión en todos los dispositivos, cuando administración lo pide
(o retira el segundo paso, desactiva la cuenta o cambia su rol), al desactivar la verificación y si el token llega desde un navegador o
sistema distinto del que se autorizó (actividad sospechosa)."""
import hashlib,re,secrets,time

DAYS=30
COOKIE='pcdoctor_trust'
MAX_ACTIVE=10


def _hash(token):
    return hashlib.sha256(('ordenes-pro:confianza:'+token).encode()).hexdigest()


def describe(agent):
    """(navegador, sistema) legibles a partir del agente del navegador. Solo para identificar el equipo, no como prueba de nada."""
    text=str(agent or '')
    browser=next((name for pattern,name in ((r'Edg/','Microsoft Edge'),(r'OPR/|Opera','Opera'),(r'SamsungBrowser','Samsung Internet'),(r'Firefox/','Firefox'),
                                            (r'Chrome/|CriOS/','Chrome'),(r'Safari/','Safari')) if re.search(pattern,text)),'Navegador desconocido')
    system=next((name for pattern,name in ((r'Android','Android'),(r'iPhone|iPad|iPod','iOS'),(r'Windows','Windows'),(r'Mac OS X|Macintosh','macOS'),(r'CrOS','ChromeOS'),(r'Linux','Linux')) if re.search(pattern,text)),'Sistema desconocido')
    return browser,system


def create(c,user_id,agent,now=None):
    """Nuevo dispositivo de confianza. Devuelve el token (solo existe aquí y en la cookie)."""
    now=int(now or time.time());browser,system=describe(agent);token=secrets.token_urlsafe(32)
    c.execute('INSERT INTO trusted_devices(user_id,token_hash,name,browser,system,created_at,last_used_at,expires_at) VALUES (?,?,?,?,?,?,?,?)',
              (user_id,_hash(token),browser+' en '+system,browser,system,now,now,now+DAYS*86400))
    # Como mucho MAX_ACTIVE equipos de confianza por cuenta: el más antiguo deja de serlo.
    extra=c.execute('SELECT id FROM trusted_devices WHERE user_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY last_used_at DESC LIMIT -1 OFFSET ?',(user_id,now,MAX_ACTIVE)).fetchall()
    for row in extra:c.execute("UPDATE trusted_devices SET revoked_at=?,revoked_reason='Sustituido por un equipo más reciente' WHERE id=?",(now,row['id']))
    return token


def check(c,user_id,token,agent,now=None):
    """¿Este navegador es de confianza para esta cuenta? Devuelve (fila, motivo de rechazo). Un token usado desde otro navegador o sistema
    se revoca en el acto. Nunca sustituye a la contraseña."""
    now=int(now or time.time())
    if not token or not re.fullmatch(r'[A-Za-z0-9_-]{30,80}',token):return None,''
    row=c.execute('SELECT * FROM trusted_devices WHERE token_hash=?',(_hash(token),)).fetchone()
    if not row or row['user_id']!=user_id:return None,''
    if row['revoked_at'] or row['expires_at']<=now:return None,''
    browser,system=describe(agent)
    if (browser,system)!=(row['browser'],row['system']):
        c.execute("UPDATE trusted_devices SET revoked_at=?,revoked_reason='Actividad sospechosa: el token llegó desde otro navegador o sistema' WHERE id=?",(now,row['id']))
        return None,'suspicious'
    c.execute('UPDATE trusted_devices SET last_used_at=? WHERE id=?',(now,row['id']))
    return row,''


def revoke_all(c,user_id,reason,now=None):
    now=int(now or time.time())
    return c.execute('UPDATE trusted_devices SET revoked_at=?,revoked_reason=? WHERE user_id=? AND revoked_at IS NULL',(now,reason[:200],user_id)).rowcount


def revoke(c,user_id,device_id,reason='Revocado por la persona usuaria',now=None):
    now=int(now or time.time())
    return c.execute('UPDATE trusted_devices SET revoked_at=?,revoked_reason=? WHERE id=? AND user_id=? AND revoked_at IS NULL',(now,reason[:200],device_id,user_id)).rowcount


def active(c,user_id,now=None):
    now=int(now or time.time())
    return [dict(r) for r in c.execute('SELECT id,name,browser,system,created_at,last_used_at,expires_at FROM trusted_devices WHERE user_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY last_used_at DESC',(user_id,now))]


def cookie(token,secure,clear=False):
    value=COOKIE+'='+('' if clear else token)+'; Path=/api/login; HttpOnly; SameSite=Strict; Max-Age='+('0' if clear else str(DAYS*86400))
    return value+('; Secure' if secure else '')
