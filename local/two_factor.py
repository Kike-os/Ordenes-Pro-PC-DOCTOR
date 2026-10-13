"""Verificación en dos pasos del personal: código de una aplicación de autenticación (TOTP, RFC 6238) y códigos de recuperación.

Es opcional y la activa cada usuario desde su perfil. La contraseña sigue siendo obligatoria: el código es un segundo paso, nunca un
sustituto. El secreto se guarda en la base (el algoritmo lo necesita para calcular el código); los códigos de recuperación, solo como
huella. Un mismo código no sirve dos veces."""
import base64,hashlib,hmac,json,re,secrets,struct,time
from urllib.parse import quote

ISSUER='Órdenes Pro PC-DOCTOR'
STEP=30;DIGITS=6;WINDOW=1          # se acepta el código vigente y el inmediato anterior o siguiente (relojes con ±30 s de diferencia)
CHALLENGE_SECONDS=300;CHALLENGE_FAILS=5;RECOVERY_CODES=10


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
    row=row_of(c,user_id);on=bool(row and row['confirmed_at'])
    return {'enabled':on,'since':row['confirmed_at'] if on else None,'recovery_left':len(json.loads(row['recovery'])) if on else 0}


def begin(c,user):
    """Inicia la activación: genera un secreto sin confirmar. No protege nada hasta que el usuario demuestre que su aplicación lo tiene."""
    if active(c,user['id']):return None
    secret=new_secret()
    c.execute('INSERT INTO user_mfa(user_id,secret,created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET secret=excluded.secret,confirmed_at=NULL,last_step=0,recovery=\'[]\',created_at=excluded.created_at',(user['id'],secret,int(time.time())))
    return {'secret':secret,'uri':uri(secret,user['email'] or user['username'])}


def confirm(c,user,code,now=None):
    """Confirma la activación con un código válido y devuelve los códigos de recuperación (única vez que se ven)."""
    row=row_of(c,user['id'])
    if not row or row['confirmed_at']:return None
    step=matching_step(row['secret'],code,now)
    if step is None:return None
    codes,stored=new_recovery()
    c.execute('UPDATE user_mfa SET confirmed_at=?,last_step=?,recovery=? WHERE user_id=?',(int(time.time() if now is None else now),step,stored,user['id']))
    return codes


def check(c,user_id,code,now=None):
    """Valida el segundo paso: 'totp' o 'recovery' si el código es correcto (y lo consume), None si no."""
    row=row_of(c,user_id)
    if not row or not row['confirmed_at']:return None
    step=matching_step(row['secret'],code,now,row['last_step'])
    if step is not None:
        c.execute('UPDATE user_mfa SET last_step=? WHERE user_id=?',(step,user_id));return 'totp'
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
