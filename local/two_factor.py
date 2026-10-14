"""Verificación en dos pasos del personal: código de una aplicación de autenticación (TOTP, RFC 6238) y códigos de recuperación.

Es opcional y la activa cada usuario desde su perfil. La contraseña sigue siendo obligatoria: el código es un segundo paso, nunca un
sustituto. El secreto se guarda CIFRADO en la base (el algoritmo lo necesita para calcular el código); los códigos de recuperación,
solo como huella. Un mismo código no sirve dos veces.

Cifrado del secreto (solo biblioteca estándar): clave maestra de 32 bytes fuera de la base (variable MFA_ENCRYPTION_KEY en Vercel; en el
servidor local, un archivo con permisos 0600 en la carpeta de datos). De ella se derivan con HMAC-SHA256 una clave de cifrado y otra de
autenticación. Cifrado en modo contador con HMAC-SHA256 como función pseudoaleatoria y autenticación encrypt-then-MAC (HMAC-SHA256 sobre
versión, nonce aleatorio de 16 bytes y texto cifrado). Un valor manipulado o cifrado con otra clave se rechaza."""
import base64,hashlib,hmac,json,os,re,secrets,struct,time
from pathlib import Path
from urllib.parse import quote

ISSUER='Órdenes Pro PC-DOCTOR'
STEP=30;DIGITS=6;WINDOW=1          # se acepta el código vigente y el inmediato anterior o siguiente (relojes con ±30 s de diferencia)
CHALLENGE_SECONDS=300;CHALLENGE_FAILS=5;RECOVERY_CODES=10


class KeyError_(RuntimeError):
    pass


def master_key():
    raw=os.getenv('MFA_ENCRYPTION_KEY','').strip()
    if raw:
        key=base64.urlsafe_b64decode(raw+'='*(-len(raw)%4))
        if len(key)<32:raise KeyError_('La clave de cifrado de la verificación en dos pasos no es válida.')
        return key[:32]
    if os.getenv('VERCEL'):raise KeyError_('Falta la clave de cifrado de la verificación en dos pasos en el servidor.')
    # Servidor local: clave propia en la carpeta de datos, creada una sola vez con permisos 0600.
    import app
    path=Path(app.DATA)/'mfa.key'
    if not path.exists():
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as handle:handle.write(secrets.token_bytes(32))
    return path.read_bytes()[:32]


def _keys():
    key=master_key()
    return hmac.new(key,b'ordenes-pro:mfa:cifrado',hashlib.sha256).digest(),hmac.new(key,b'ordenes-pro:mfa:autenticacion',hashlib.sha256).digest()


def _stream(key,nonce,length):
    out=b'';counter=0
    while len(out)<length:
        out+=hmac.new(key,nonce+struct.pack('>Q',counter),hashlib.sha256).digest();counter+=1
    return out[:length]


def seal(secret):
    enc,mac=_keys();nonce=secrets.token_bytes(16);plain=secret.encode()
    body=bytes(a^b for a,b in zip(plain,_stream(enc,nonce,len(plain))))
    tag=hmac.new(mac,b'v1'+nonce+body,hashlib.sha256).digest()
    return 'enc1:'+base64.urlsafe_b64encode(nonce+body+tag).decode().rstrip('=')


def unseal(value):
    """Secreto en claro solo en memoria. Admite los valores anteriores sin cifrar (se vuelven a guardar cifrados al usarse)."""
    value=str(value or '')
    if not value.startswith('enc1:'):return value
    raw=base64.urlsafe_b64decode(value[5:]+'='*(-len(value[5:])%4));nonce,body,tag=raw[:16],raw[16:-32],raw[-32:]
    enc,mac=_keys()
    if not hmac.compare_digest(tag,hmac.new(mac,b'v1'+nonce+body,hashlib.sha256).digest()):raise KeyError_('El secreto guardado no se pudo verificar.')
    return bytes(a^b for a,b in zip(body,_stream(enc,nonce,len(body)))).decode()


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code_at(secret,step):
    mac=hmac.new(base64.b32decode(secret),struct.pack('>Q',step),hashlib.sha1).digest();offset=mac[-1]&15
    return '%06d'%((struct.unpack('>I',mac[offset:offset+4])[0]&0x7fffffff)%10**DIGITS)


def matching_step(secret,code,now=None,after=0):
    """Paso de tiempo al que corresponde el código, o None. `after` es el último paso ya usado: impide repetir un código."""
    code=re.sub(r'\s','',str(code or ''))
    if not re.fullmatch(r'[0-9]{6}',code):return None
    current=int((time.time() if now is None else now)//STEP)
    for step in range(current-WINDOW,current+WINDOW+1):
        if step>after and hmac.compare_digest(code_at(secret,step),code):return step
    return None


def uri(secret,account):
    return 'otpauth://totp/%s:%s?secret=%s&issuer=%s&algorithm=SHA1&digits=%d&period=%d'%(quote(ISSUER),quote(account),secret,quote(ISSUER),DIGITS,STEP)


def _mark(code):
    return hashlib.sha256(('recuperacion:'+re.sub(r'[^A-Z0-9]','',str(code or '').upper())).encode()).hexdigest()


def new_recovery():
    """Códigos de recuperación (se muestran una sola vez) y sus huellas para guardar."""
    codes=['-'.join(''.join(secrets.choice('ABCDEFGHJKMNPQRSTUVWXYZ23456789') for _ in range(5)) for _ in range(2)) for _ in range(RECOVERY_CODES)]
    return codes,json.dumps([_mark(code) for code in codes])


def row_of(c,user_id):
    return c.execute('SELECT * FROM user_mfa WHERE user_id=?',(user_id,)).fetchone()


def active(c,user_id):
    row=row_of(c,user_id)
    return bool(row and row['confirmed_at'])


def status(c,user_id):
    """Estado real: 'off' (no configurado), 'pending' (configuración iniciada sin verificar) u 'on' (protección activa)."""
    row=row_of(c,user_id);on=bool(row and row['confirmed_at'])
    return {'enabled':on,'state':'on' if on else 'pending' if row else 'off','since':row['confirmed_at'] if on else None,'recovery_left':len(json.loads(row['recovery'])) if on else 0}


def begin(c,user):
    """Inicia la activación: genera un secreto sin confirmar. No protege nada hasta que el usuario demuestre que su aplicación lo tiene."""
    if active(c,user['id']):return None
    secret=new_secret()
    # Una clave nueva sustituye a cualquier otra mostrada antes (que deja de servir). Se guarda cifrada.
    c.execute('INSERT INTO user_mfa(user_id,secret,created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET secret=excluded.secret,confirmed_at=NULL,last_step=0,recovery=\'[]\',created_at=excluded.created_at',(user['id'],seal(secret),int(time.time())))
    return {'secret':secret,'uri':uri(secret,user['email'] or user['username'])}


def confirm(c,user,code,now=None):
    """Confirma la activación con un código válido y devuelve los códigos de recuperación (única vez que se ven)."""
    row=row_of(c,user['id'])
    if not row or row['confirmed_at']:return None
    step=matching_step(unseal(row['secret']),code,now)
    if step is None:return None
    codes,stored=new_recovery()
    c.execute('UPDATE user_mfa SET confirmed_at=?,last_step=?,recovery=? WHERE user_id=?',(int(time.time() if now is None else now),step,stored,user['id']))
    return codes


def check(c,user_id,code,now=None):
    """Valida el segundo paso: 'totp' o 'recovery' si el código es correcto (y lo consume), None si no."""
    row=row_of(c,user_id)
    if not row or not row['confirmed_at']:return None
    secret=unseal(row['secret'])
    step=matching_step(secret,code,now,row['last_step'])
    if step is not None:
        c.execute('UPDATE user_mfa SET last_step=?,secret=? WHERE user_id=?',(step,row['secret'] if row['secret'].startswith('enc1:') else seal(secret),user_id));return 'totp'
    left=json.loads(row['recovery']);mark=_mark(code)
    if len(re.sub(r'[^A-Za-z0-9]','',str(code or '')))==10 and mark in left:
        left.remove(mark);c.execute('UPDATE user_mfa SET recovery=? WHERE user_id=?',(json.dumps(left),user_id));return 'recovery'
    return None


def renew_recovery(c,user_id):
    codes,stored=new_recovery();c.execute('UPDATE user_mfa SET recovery=? WHERE user_id=? AND confirmed_at IS NOT NULL',(stored,user_id));return codes


def remove(c,user_id):
    c.execute('DELETE FROM user_mfa WHERE user_id=?',(user_id,));c.execute('DELETE FROM mfa_challenges WHERE user_id=?',(user_id,))


def challenge(c,user_id,remember,digest):
    """Tras una contraseña correcta: reserva un intento de segundo paso de corta duración. Aún no hay sesión."""
    now=int(time.time());token=secrets.token_urlsafe(32)
    c.execute('DELETE FROM mfa_challenges WHERE expires<? OR user_id=?',(now,user_id))
    c.execute('INSERT INTO mfa_challenges(token_hash,user_id,remember,expires) VALUES (?,?,?,?)',(digest(token),user_id,1 if remember else 0,now+CHALLENGE_SECONDS))
    return token


def answer(c,token,code,digest,now=None):
    """Resuelve el segundo paso. Devuelve (estado, fila): 'ok' con el desafío consumido, 'bad' si el código no vale (quedan intentos),
    'expired' si el desafío caducó, no existe o agotó sus intentos (hay que volver a escribir la contraseña)."""
    moment=int(time.time() if now is None else now)
    row=c.execute('SELECT * FROM mfa_challenges WHERE token_hash=?',(digest(str(token or '')),)).fetchone()
    if not row or row['expires']<moment or row['fails']>=CHALLENGE_FAILS:
        if row:c.execute('DELETE FROM mfa_challenges WHERE token_hash=?',(row['token_hash'],))
        return 'expired',None
    kind=check(c,row['user_id'],code,now)
    if not kind:
        c.execute('UPDATE mfa_challenges SET fails=fails+1 WHERE token_hash=?',(row['token_hash'],))
        return ('expired' if row['fails']+1>=CHALLENGE_FAILS else 'bad'),None
    c.execute('DELETE FROM mfa_challenges WHERE token_hash=?',(row['token_hash'],))
    return 'ok',dict(row,kind=kind)
