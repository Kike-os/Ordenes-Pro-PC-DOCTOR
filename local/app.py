"""Evaluación local de ÓRDENES PRO. Loopback por defecto; LAN mediante configuración explícita."""
import argparse
import base64
import unicodedata
import getpass
import hashlib
import hmac
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
import threading
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerificationError, InvalidHashError
    ARGON2 = PasswordHasher(time_cost=3,memory_cost=65536,parallelism=1)
except ImportError:
    ARGON2 = None
from email.message import EmailMessage
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit, unquote, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError
from reception import (stored_category, valid_ecuador_phone, DEVICE_TYPES, validate_order, order_code, legacy_type, remember_brand, qr_image, production_enabled, reception_now, order_url, public_base_url)

import remote_db
import reception
import service_terms
import technical_access
import thermal_printing
import tempfile
import subprocess
import order_workspace
import corporate
import client_registry
import client_import
import maintenance
import appointments
import appointment_mail
import adi
import versioning
import notifications
import mail_pro
from weather import current_weather
from geography import initialize_catalog, search as search_geography, METADATA as GEO_METADATA

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'var'
DB = DATA / 'ordenes.sqlite3'


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    if remote_db.configured():
        return remote_db.connect()
    c = sqlite3.connect(DB, timeout=10, factory=Connection)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def make_backup():
    """Copia completa de la base antes de un cambio masivo. Devuelve el nombre del archivo o falla sin modificar nada."""
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = DATA / f'backup-{time.time_ns()}.sqlite3'
    try:
        if remote_db.configured():
            with remote_db.connect() as source:
                remote_db.backup(source, backup)
        else:
            source = sqlite3.connect(DB, timeout=10)
            target = sqlite3.connect(backup)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        backup.chmod(0o600)
        check = sqlite3.connect(backup)
        try:
            if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise OSError('integridad')
        finally:
            check.close()
    except (OSError, sqlite3.Error, ValueError):
        raise client_import.ImportError_('No se pudo crear la copia de seguridad; no se importó nada. En el hosting sin disco persistente, importa desde el equipo de administración.')
    return backup.name


def migrate():
    remote = remote_db.configured()
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)')
        for p in sorted((ROOT / 'migrations').glob('*.sql')):
            if not c.execute('SELECT 1 FROM migrations WHERE name=?', (p.name,)).fetchone():
                if (remote or DB.exists()) and c.execute('SELECT COUNT(*) FROM migrations').fetchone()[0]:
                    backup = DATA / f'backup-{time.time_ns()}.sqlite3'
                    if remote:
                        remote_db.backup(c, backup)
                    else:
                        target = sqlite3.connect(backup)
                        try:
                            c.backup(target)
                        finally:
                            target.close()
                    backup.chmod(0o600)
                name = p.name.replace("'", "''")
                c.executescript('BEGIN IMMEDIATE;\n' + p.read_text() + f"\nINSERT INTO migrations VALUES ('{name}');\nCOMMIT;")
        initialize_catalog(c)
        snapshot_rows = c.execute("SELECT o.id,c.name client,c.identification,c.document_type,c.trade_name,c.phone,c.email,c.province,c.province_code,c.canton,c.canton_code,c.parish,c.parish_code,c.city,c.locality_code,c.address,c.main_street,c.secondary_street,c.building_number,c.location_reference,c.geo_version,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,d.color,o.accessories,o.physical_condition,o.problem,o.technician_notes FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id WHERE o.reception_snapshot='' ").fetchall()
        for order in snapshot_rows:
            snapshot=dict(order)
            oid=snapshot.pop('id')
            c.execute('UPDATE orders SET reception_snapshot=? WHERE id=?',(json.dumps(snapshot,ensure_ascii=False),oid))
        for order in c.execute("SELECT id,code FROM orders WHERE qr_url=''").fetchall():
            c.execute('UPDATE orders SET qr_url=? WHERE id=?',(order_url(order['code']),order['id']))
    if not remote:
        DB.chmod(0o600)


def password_hash(password):
    if ARGON2 is not None:return ARGON2.hash(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=3, maxmem=64*1024*1024)
    return 'scrypt$32768$8$3$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(digest).decode()


def password_ok(password, encoded):
    if encoded.startswith('$argon2id$'):
        if ARGON2 is None:return False
        try:return ARGON2.verify(encoded,password)
        except (VerificationError,InvalidHashError):return False
    try:
        kind, n, r, p, salt, expected = encoded.split('$')
        if kind != 'scrypt' or (n, r, p) != ('32768', '8', '3'):
            return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=64*1024*1024)
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


DUMMY_HASH = password_hash(secrets.token_urlsafe(32))


def allowed_request_origin(origin, expected):
    if origin == expected:
        return True
    # Alias explícitos solo para el servidor local; nunca confiar en Host/Forwarded.
    configured=urlsplit(expected)
    if configured.scheme=='http' and configured.hostname in ('127.0.0.1','localhost'):
        port=f':{configured.port}' if configured.port else ''
        return origin in {f'http://127.0.0.1{port}',f'http://localhost{port}'}
    return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def audit(c, user_id, action, entity_id=None):
    c.execute('INSERT INTO audit(user_id,action,entity_id,created_at) VALUES (?,?,?,?)', (user_id, action, entity_id, int(time.time())))


def limited(c, bucket, limit=8, window=900):
    now = int(time.time())
    c.execute('DELETE FROM attempts WHERE expires<=?', (now,))
    c.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1,expires=CASE WHEN attempts.expires<=? THEN excluded.expires ELSE attempts.expires END', (bucket, now+window, now))
    return c.execute('SELECT count FROM attempts WHERE bucket=?', (bucket,)).fetchone()[0] > limit

def limit_reached(c,bucket):
    now=int(time.time());c.execute('DELETE FROM attempts WHERE expires<=?',(now,))
    row=c.execute('SELECT count FROM attempts WHERE bucket=? AND expires>?',(bucket,now)).fetchone()
    return bool(row and row[0]>=5)

def auth_policy(c):
    defaults = {'lockout_seconds': login_lockout_window(), 'session_hours': 8, 'remember_days': 30, 'password_min': 6}
    defaults.update({r['key']: r['value'] for r in c.execute('SELECT key,value FROM auth_policy')})
    return defaults


def verify_bot(token, action):
    if not token or len(token)>2048:
        return False
    payload=urlencode({'secret':os.getenv('TURNSTILE_SECRET_KEY',''),'response':token}).encode()
    try:
        with urlopen(Request('https://challenges.cloudflare.com/turnstile/v0/siteverify',data=payload),timeout=8) as response:
            result=json.loads(response.read(16384))
        return result.get('success') is True and result.get('hostname')==urlsplit(os.getenv('APP_URL','')).hostname and result.get('action')==action
    except (OSError, URLError, ValueError):
        return False


def bot_always():
    # Con las claves configuradas, el acceso exige verificación en cada intento salvo TURNSTILE_LOGIN_MODE=adaptive.
    return bool(os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY')) and os.getenv('TURNSTILE_LOGIN_MODE','always').strip().lower()!='adaptive'


CAPTCHA_BITS = 16
CAPTCHA_SECONDS = 300


def captcha_mode():
    # Turnstile si hay claves; si no, verificación local «No soy un robot» salvo LOGIN_CAPTCHA=off.
    if os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY'):
        return 'turnstile' if bot_always() else ''
    return '' if os.getenv('LOGIN_CAPTCHA','on').strip().lower() in ('off','false','0','no') else 'local'


def new_captcha(c):
    nonce=secrets.token_urlsafe(24)
    c.execute('INSERT INTO attempts VALUES (?,0,?)',('captcha:'+digest(nonce),int(time.time())+CAPTCHA_SECONDS))
    return {'nonce':nonce,'bits':CAPTCHA_BITS,'seconds':CAPTCHA_SECONDS}


def verify_captcha(c, token):
    # Reto de un solo uso emitido por este servidor y resuelto con prueba de trabajo SHA-256.
    match=re.fullmatch(r'local:([A-Za-z0-9_-]{20,64}):([0-9]{1,12})',token or '')
    if not match:
        return False
    bucket='captcha:'+digest(match[1])
    if not c.execute('SELECT 1 FROM attempts WHERE bucket=? AND expires>?',(bucket,int(time.time()))).fetchone():
        return False
    c.execute('DELETE FROM attempts WHERE bucket=?',(bucket,))
    word=int.from_bytes(hashlib.sha256((match[1]+':'+match[2]).encode()).digest()[:4],'big')
    return word>>(32-CAPTCHA_BITS)==0


ORDER_PHOTO_LIMIT=8


def adi_public_state(conv):
    # Estado que ve el cliente: solo se informa «asesor conectado» cuando un usuario real tomó la conversación.
    mode=conv['mode'] if conv else 'adi'
    return 'closed' if mode=='closed' else ('advisor' if conv['assigned_to'] else 'waiting') if mode=='human' else 'adi'


def terms_required():
    """Exigir condiciones publicadas para registrar órdenes es una decisión expresa de la instalación (REQUIRE_SERVICE_TERMS=true)."""
    return os.environ.get('REQUIRE_SERVICE_TERMS','').strip().lower() in ('1','true','si','sí','yes')
def mail_order_candidates(c,addresses):
    """Órdenes no entregadas del único cliente al que corresponden todos los destinatarios; sin relación inequívoca no propone nada."""
    found=set()
    for address in dict.fromkeys(addresses[:20]):
        owners=[r['id'] for r in c.execute("SELECT id FROM clients WHERE email!='' AND lower(email)=?",(address,))]
        if len(owners)!=1:return {'client':None,'orders':[],'reason':'unknown' if not owners else 'ambiguous'}
        found.add(owners[0])
    if len(found)!=1:return {'client':None,'orders':[],'reason':'none' if not found else 'several'}
    client=c.execute('SELECT id,name FROM clients WHERE id=?',(found.pop(),)).fetchone()
    orders=[dict(r) for r in c.execute("SELECT o.id,o.code,o.status,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id WHERE d.client_id=? AND o.status!='entregado' ORDER BY o.id DESC LIMIT 20",(client['id'],))]
    return {'client':dict(client),'orders':orders,'reason':''}
def mail_allowed(user):
    # El buzón compartido es de administración; los técnicos solo acceden si el servidor lo habilita.
    try:
        ready=mail_pro.configured()
    except mail_pro.MailError:
        return False
    return ready and (user['role']=='administrador' or (user['role']=='tecnico' and os.getenv('MAIL_ALLOW_TECHNICIANS','').lower() in ('1','true','yes')))


def order_document(c,oid):
    """Datos completos de una orden para sus documentos (misma composición que usan los PDF del detalle)."""
    row=c.execute('SELECT o.*,COALESCE(NULLIF(d.kind,\'\'),d.category) type,d.brand,d.model,d.serial,d.color,c.id client_id,c.name client,c.identification,c.phone,c.email,c.province,c.city,c.address,c.location_reference,s.label status_label FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?',(oid,)).fetchone()
    if not row:return None
    order=dict(row);order['current_problem']=row['problem']
    if row['reception_snapshot']:order.update(json.loads(row['reception_snapshot']))
    order['code']=row['code'] or 'OP-'+str(row['id']).zfill(5);order['email']=row['email'] or ''
    service_terms.attach(c,order);technical_access.attach(c,order);order_workspace.attach(c,order)
    return order


def receipt_mail_status(c,oid):
    rows=[dict(r) for r in c.execute('SELECT m.mode,m.recipient,m.result,m.detail,m.created_at,u.name actor FROM order_receipt_mail m LEFT JOIN users u ON u.id=m.actor_id WHERE m.order_id=? ORDER BY m.id DESC LIMIT 8',(oid,))]
    auto=c.execute("SELECT value FROM system_state WHERE key='receipt_mail_auto'").fetchone()
    return {'history':rows,'sent':any(r['result']=='sent' for r in rows),'auto':not (auto and auto['value']=='off'),'configured':mail_pro.configured()}


def send_receipt_mail(c,oid,user,mode):
    """Envía por SMTP el comprobante A4 (con las Políticas de Reparaciones) al correo del cliente y registra el resultado.

    «sent» significa que el servidor de correo aceptó el mensaje, no que el cliente lo haya recibido o leído.
    """
    import repair_policies
    from receipt_pdf import render_receipt
    order=order_document(c,oid)
    if not order:return 404,{'error':'Orden no disponible.'}
    now=reception_now().isoformat(timespec='seconds');policies=repair_policies.load()
    def log(result,detail='',recipient='',sha=''):
        c.execute('INSERT INTO order_receipt_mail(order_id,mode,recipient,result,detail,document_sha256,policies_version,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(oid,mode,recipient,result,detail[:300],sha,policies['version'],user['id'],now))
    # El envío automático ocurre una sola vez por orden; los reenvíos son siempre una acción expresa del personal.
    if mode=='auto':
        state=receipt_mail_status(c,oid)
        if not state['auto']:return 200,{'result':'disabled','message':'El envío automático del comprobante está desactivado.'}
        if state['history']:return 200,{'result':'already','message':'El comprobante de esta orden ya fue gestionado.'}
    email=(order.get('email') or '').strip()
    if not email or not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+',email):
        log('no_email');return 200,{'result':'no_email','message':'Pendiente de envío — Sin correo electrónico. Puedes descargar o imprimir el comprobante.'}
    try:ready=mail_pro.configured()
    except mail_pro.MailError:ready=False
    if not ready:
        log('not_configured','',email);return 200,{'result':'not_configured','message':'El correo del sistema no está configurado: el comprobante no se envió.'}
    pdf=render_receipt(order);sha=hashlib.sha256(pdf).hexdigest()
    body=('Estimado/a '+order['client']+':\n\nLe confirmamos que su equipo ha sido registrado correctamente en nuestro sistema de servicio técnico.\n\n'
          'Adjuntamos el comprobante de recepción correspondiente a la orden '+order['code']+', que incluye la información registrada del equipo y nuestras Políticas de Reparaciones.\n\n'
          'Le recomendamos conservar este documento para futuras consultas.\n\nAtentamente,\n\nServicio Técnico\nPC-DOCTOR S.A.')
    try:
        config=mail_pro.settings();card=mail_signature_card(c)
        message,recipients=mail_pro.build_message(config,{'to':email,'subject':'Confirmación de recepción — Orden '+order['code']+' | PC-DOCTOR S.A.','body':body,'from_name':corporate.settings()['name'],
            'attachments':[{'name':'Comprobante-'+order['code']+'.pdf','type':'application/pdf','data':base64.b64encode(pdf).decode()}]},card if card.get('enabled') else '')
        mail_pro.deliver(config,message,recipients)
    except mail_pro.MailError as error:
        print('receipt-mail',error.kind,flush=True);log('failed',str(error),email,sha)
        return 200,{'result':'failed','message':'La orden está guardada, pero el correo no se pudo enviar: '+str(error)}
    log('sent','El servidor de correo aceptó el mensaje.',email,sha)
    order_workspace.event(c,oid,user['id'],reception_now(),'follow_up','Comprobante de recepción enviado por correo a '+email+'.')
    audit(c,user['id'],'receipt_mail_sent',oid)
    return 200,{'result':'sent','recipient':email,'message':'Comprobante enviado a '+email+'. El servidor de correo aceptó el mensaje.'}


def mail_signature_card(c):
    # Firma corporativa del buzón remitente: datos validados; el HTML siempre lo compone el servidor.
    account=mail_pro.settings()['username'];row=c.execute('SELECT value FROM system_state WHERE key=?',('mail_signature_card:'+account,)).fetchone()
    try:raw=json.loads(row['value']) if row else {}
    except ValueError:raw={}
    return mail_pro.clean_signature(raw,account)


def mail_signature(c):
    row=c.execute("SELECT value FROM system_state WHERE key='mail_signature'").fetchone()
    return row['value'] if row else corporate.settings()['name']+'\n'+corporate.settings()['specialty']+'\nWhatsApp '+corporate.settings()['whatsapp']


def registration_enabled():
    return os.getenv('REGISTRATION','on').strip().lower() not in ('off','false','0','no')


def bot_required(c, ip_key):
    row=c.execute('SELECT count FROM attempts WHERE bucket=? AND expires>?',(ip_key,int(time.time()))).fetchone()
    return bool(os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY') and row and row[0]>=2)


def login_lockout_window():
    try:return max(900,min(86400,int(os.getenv('LOGIN_LOCKOUT_SECONDS','900'))))
    except ValueError:return 900

def auth_event(c,account_hash,ip_hash,result):
    account_key='login-user:'+account_hash;ip_key='login-ip:'+ip_hash
    account=c.execute('SELECT count FROM attempts WHERE bucket=?',(account_key,)).fetchone()
    ip=c.execute('SELECT count FROM attempts WHERE bucket=?',(ip_key,)).fetchone()
    c.execute('INSERT INTO login_attempt_events(account_hash,ip_hash,result,account_attempt,ip_attempt,created_at) VALUES (?,?,?,?,?,?)',(account_hash,ip_hash,result,account[0] if account else 0,ip[0] if ip else 0,int(time.time())))
    c.execute('DELETE FROM login_attempt_events WHERE created_at<?',(int(time.time())-90*86400,))


def make_session(c, user_id, remember=False):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    policy=auth_policy(c)
    age = policy['remember_days']*86400 if remember else policy['session_hours']*3600
    c.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
    c.execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest(token), user_id, csrf, int(time.time())+age))
    return token, csrf, age


def dispatch_security_job(job):
    # SMTP nunca forma parte del tiempo de respuesta público: evita enumeración por latencia.
    threading.Thread(target=job,daemon=True,name='security-mail').start()


def deliver_reset(email, token, uid):
    try:
        send_reset(email,token)
        with connect() as c:audit(c,uid,'reset_email_sent')
    except (OSError,RuntimeError,smtplib.SMTPException):
        with connect() as c:
            c.execute('DELETE FROM reset_tokens WHERE token_hash=?',(digest(token),))
            audit(c,None,'reset_delivery_failed')


def deliver_change_notice(email, uid):
    try:
        send_security_mail(email,'Contraseña actualizada — PC-DOCTOR S.A.','PC-DOCTOR S.A.\nTu contraseña de Órdenes Pro se ha actualizado. Se cerraron todas las sesiones. Si no realizaste el cambio, contacta a administración inmediatamente.')
        result='password_change_notified'
    except (OSError,RuntimeError,smtplib.SMTPException):
        result='password_notification_failed'
    with connect() as c:audit(c,uid,result)


def send_security_mail(email, subject, text, markup=None):
    host, sender = os.getenv('SMTP_HOST'), os.getenv('SMTP_FROM')
    if not host or not sender or not os.getenv('SMTP_USER') or not os.getenv('SMTP_PASSWORD'):
        raise RuntimeError('SMTP autenticado no configurado')
    msg=EmailMessage()
    msg['Subject'], msg['From'], msg['To']=subject,sender,email
    msg.set_content(text)
    if markup:msg.add_alternative(markup,subtype='html')
    with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
        smtp.send_message(msg)


def send_reset(email, token):
    base=os.getenv('APP_URL','http://127.0.0.1:8010').rstrip('/')
    if urlsplit(base).scheme!='https' and urlsplit(base).hostname not in ('127.0.0.1','localhost'):
        raise RuntimeError('La recuperación requiere HTTPS')
    url=base+'/reset?token='+token
    text=f'PC-DOCTOR S.A.\nSolicitaste recuperar el acceso a Órdenes Pro.\n{url}\nEl enlace vence en 20 minutos y es de un solo uso. Si no realizaste esta solicitud, ignora el mensaje.'
    markup=f'<html lang="es"><body style="font-family:Arial;color:#142239"><h1>PC-DOCTOR S.A.</h1><h2>Recupera tu acceso a Órdenes Pro</h2><p>Recibimos una solicitud para restablecer tu contraseña.</p><p><a style="background:#2359ac;color:white;padding:14px;display:inline-block" href="{html.escape(url,quote=True)}">Restablecer contraseña</a></p><p>Este enlace vence en 20 minutos y solo se puede usar una vez.</p><p>Si no realizaste la solicitud, ignora este mensaje.</p></body></html>'
    send_security_mail(email,'Restablecer contraseña — PC-DOCTOR S.A.',text,markup)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # No registrar URL de recuperación, contraseñas, tokens ni datos personales.
        pass

    def reply(self, status, body, content_type='application/json; charset=utf-8', cookie=None):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-src 'self' blob: https://challenges.cloudflare.com; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self'; connect-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        if cookie:
            for value in (cookie if isinstance(cookie, (list, tuple)) else [cookie]):
                self.send_header('Set-Cookie', value)
        self.end_headers()
        self.wfile.write(body)

    def cookie(self, token, age=None):
        value = f'pcdoctor_session={token}; Path=/; HttpOnly; SameSite=Strict'
        if os.getenv('SESSION_SECURE', 'false').lower() == 'true' or urlsplit(os.getenv('APP_URL','')).scheme=='https':
            value += '; Secure'
        if age is not None:
            value += f'; Max-Age={age}'
        return value

    def session(self, c):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
            token = cookies['pcdoctor_session'].value if 'pcdoctor_session' in cookies else ''
        except Exception:
            token = ''
        return c.execute('SELECT u.id,u.username,u.name,u.email,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1', (digest(token), int(time.time()))).fetchone(), token

    def page(self, name):
        content = (ROOT / 'templates' / name).read_text()
        notice = '' if production_enabled() else '<p class="evaluation-notice">Esta versión es de evaluación. Utiliza únicamente datos ficticios.</p>'
        with connect() as c:minimum=auth_policy(c)['password_min']
        content = content.replace('{{password_min}}',str(minimum)).replace('{{access_environment}}','ACCESO SEGURO' if production_enabled() else 'ENTORNO LOCAL')
        content = content.replace('{{turnstile_sitekey}}',html.escape(os.getenv('TURNSTILE_SITE_KEY',''),quote=True) if bot_always() else '').replace('{{captcha_mode}}',captcha_mode())
        content = content.replace('{{register_captcha}}','local' if captcha_mode()=='local' else '').replace('{{register_hidden}}','' if registration_enabled() else ' hidden')
        try:installed=versioning.load()['releases'][0]['version']
        except (versioning.RegistryError,IndexError):installed='—'
        pending=''
        try:
            with connect() as c:row=c.execute("SELECT value FROM system_state WHERE key='available_update'").fetchone()
            if row and installed!='—' and versioning.parse(json.loads(row['value'])['version'])>versioning.parse(installed):pending=json.loads(row['value'])['version']
        except (sqlite3.Error,ValueError,KeyError,versioning.RegistryError):pending=''
        # Con una versión posterior detectada, el indicador lo señala antes de iniciar sesión.
        content = content.replace('{{release_class}}',' has-update' if pending else '').replace('{{release_aria}}',', actualización disponible '+html.escape(pending) if pending else '').replace('{{release_note}}','<span class="release-pending">Actualización disponible · v'+html.escape(pending)+'</span>' if pending else '')
        content = content.replace('{{app_version}}',html.escape(installed))
        content = content.replace('{{evaluation_notice}}', notice).replace('{{environment_label}}', 'Servicio técnico' if production_enabled() else 'Evaluación local · Usa datos ficticios')
        self.reply(200, content, 'text/html; charset=utf-8')

    def do_GET(self):
        path = urlsplit(self.path).path
        files = {'/static/label.css':'label.css','/static/tracking.css':'tracking.css','/static/app.css':'app.css','/static/app.js':'app.js','/static/form-validation.js':'form-validation.js','/static/appointments.js':'appointments.js','/static/adi-widget.js':'adi-widget.js','/static/logo-original.png':'logo-original.png',
                 '/favicon.ico':'favicon.ico','/static/favicon.ico':'favicon.ico','/static/favicon-16.png':'favicon-16.png','/static/favicon-32.png':'favicon-32.png','/static/logo-firma.png':'logo-firma.png','/static/favicon-48.png':'favicon-48.png',
                 '/apple-touch-icon.png':'apple-touch-icon.png','/apple-touch-icon-precomposed.png':'apple-touch-icon.png','/static/apple-touch-icon.png':'apple-touch-icon.png'}
        # Logotipos de marcas: solo nombres simples dentro de static/brands; si el archivo no existe la interfaz usa un icono genérico.
        brand_logo = re.fullmatch(r'/static/brands/([a-z0-9]+(?:-[a-z0-9]+)*)\.(svg|png)', path)
        if brand_logo:
            file = ROOT / 'static' / 'brands' / (brand_logo[1][:60] + '.' + brand_logo[2])
            if not file.is_file():
                return self.reply(404, {'error':'Archivo no disponible.'})
            return self.reply(200, file.read_bytes(), 'image/svg+xml' if brand_logo[2] == 'svg' else 'image/png')
        if path in files:
            file = ROOT / 'static' / files[path]
            if not file.is_file():
                return self.reply(404, {'error':'Archivo no disponible.'})
            content_type = 'image/png' if file.suffix == '.png' else 'image/x-icon' if file.suffix == '.ico' else ('text/css; charset=utf-8' if file.suffix == '.css' else 'text/javascript; charset=utf-8')
            return self.reply(200, file.read_bytes(), content_type)
        with connect() as c:
            if path == '/citas':
                return self.page('appointments.html')
            if path == '/novedades':
                # Historial público: solo el registro de versiones ya publicado; sin datos internos ni de clientes.
                try:registry=versioning.load()
                except versioning.RegistryError:return self.reply(404,{'error':'Historial no disponible.'})
                parts=[]
                for index,release in enumerate(registry['releases']):
                    groups=''.join('<h3>'+html.escape(title)+'</h3><ul>'+''.join('<li>'+html.escape(item)+'</li>' for item in release['changes'][key])+'</ul>' for key,title in versioning.CATEGORIES.items() if release['changes'][key])
                    parts.append('<section><h2><span>v'+html.escape(release['version'])+'</span>'+('<em>Última versión</em>' if index==0 else '')+'<small>'+html.escape(release['date'][:10])+'</small></h2>'+('<p>'+html.escape(release['summary'])+'</p>' if release['summary'] else '')+groups+'</section>')
                page='<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#060d19"><title>Novedades | Órdenes Pro</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16.png?v=2"><link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png?v=2"><link rel="icon" type="image/png" sizes="48x48" href="/static/favicon-48.png?v=2"><link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png?v=2"><link rel="stylesheet" href="/static/app.css"></head><body data-page="conditions"><main class="conditions-document privacy-document changelog-document"><header><img src="/static/logo-original.png" alt="Logotipo oficial PC-DOCTOR" width="2826" height="2049"><div><span class="eyebrow">ÓRDENES PRO · PC-DOCTOR S.A.</span><h1>Novedades del sistema</h1></div></header><p class="conditions-version">Historial de versiones publicadas</p>'+''.join(parts)+'<footer><p><a href="/">Volver al inicio de sesión</a></p></footer></main></body></html>'
                return self.reply(200,page,'text/html; charset=utf-8')
            if path == '/privacidad':
                company=corporate.settings();content=(ROOT/'templates'/'privacy.html').read_text()
                for key,value in (('company',company['name']),('whatsapp',company['whatsapp']),('support_email',company['support_email'])):content=content.replace('{{'+key+'}}',html.escape(value,quote=True))
                return self.reply(200,content,'text/html; charset=utf-8')
            if path == '/api/public/appointments/services':
                # Catálogo público para la reserva: servicios, tipos de equipo y marcas con su logotipo local. Sin datos de clientes.
                brand_files={f.stem:f.name for f in sorted((ROOT / 'static' / 'brands').glob('*')) if f.suffix in ('.svg','.png') and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', f.stem)}
                brand_names=sorted({r['name'] for r in c.execute('SELECT name FROM brands')},key=str.lower)
                return self.reply(200, {'services':appointments.services(c),'device_types':DEVICE_TYPES,'timezone':'America/Guayaquil','brands':brand_names,'brand_logos':brand_files})
            if path == '/api/public/appointments/availability':
                query=parse_qs(urlsplit(self.path).query)
                try: rows=appointments.available_slots(c,query.get('date',[''])[0],query.get('service',[''])[0])
                except ValueError as error:return self.reply(400,{'error':str(error)})
                return self.reply(200,{'slots':[{'time':r['time']} for r in rows]})
            if path == '/api/public/appointments/manage':
                query=parse_qs(urlsplit(self.path).query);code=query.get('code',[''])[0][:40];token=query.get('token',[''])[0]
                row=c.execute('SELECT id,public_code,customer_name,device_type,brand,model,service_code,starts_at,status,generation,manage_token_hash FROM appointments WHERE deleted_at IS NULL AND public_code=?',(code,)).fetchone()
                if not row or not secrets.compare_digest(row['manage_token_hash'],appointments.token_hash(token)):
                    return self.reply(404,{'error':'No encontramos una cita válida con ese enlace.'})
                result=dict(row);result.pop('manage_token_hash');return self.reply(200,{'appointment':result})
            if path == '/api/public/adi/messages':
                cookies=SimpleCookie()
                try:cookies.load(self.headers.get('Cookie',''))
                except Exception:pass
                token=cookies['pcdoctor_adi'].value if 'pcdoctor_adi' in cookies else ''
                conv=c.execute('SELECT id,mode,assigned_to FROM adi_conversations WHERE token_hash=?',(digest(token),)).fetchone()
                if not conv:return self.reply(200,{'messages':[],'mode':'adi','state':'adi'})
                after=parse_qs(urlsplit(self.path).query).get('after',['0'])[0]
                try:after=max(0,int(after))
                except ValueError:after=0
                rows=[dict(r) for r in c.execute("SELECT id,author,content,created_at FROM adi_messages WHERE conversation_id=? AND visibility='public' AND id>? ORDER BY id LIMIT 100",(conv['id'],after))]
                c.execute('UPDATE adi_conversations SET last_seen_client=? WHERE id=?',(appointments.stamp(appointments.now()),conv['id']))
                return self.reply(200,{'messages':rows,'mode':conv['mode'],'state':adi_public_state(conv)})
            preference=re.fullmatch(r'/maintenance-preferences/([A-Za-z0-9_-]{40,60})',path)
            if preference:
                row=c.execute('SELECT consent FROM maintenance WHERE unsubscribe_token=?',(preference[1],)).fetchone()
                if not row:return self.reply(404,{'error':'Enlace no disponible.'})
                token=preference[1]
                body='<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Preferencias de recordatorios</title><h1>PC-DOCTOR S.A.</h1><p>Puede dejar de recibir recordatorios de mantenimiento. Esta acción no modifica su reparación.</p><form method="post" action="/maintenance-preferences/'+token+'"><button type="submit">Dejar de recibir recordatorios</button></form></html>'
                return self.reply(200,body,'text/html; charset=utf-8')
            # Seguimiento público por enlace aleatorio: respuesta idéntica para enlaces inexistentes o revocados.
            tracking_page=re.fullmatch(r'/s/([A-Za-z0-9_-]{1,64})',path)
            if tracking_page:
                import order_tracking
                if limited(c,'tracking-ip:'+digest(self.client_address[0]),40,300):return self.reply(429,{'error':'Demasiadas consultas. Intenta más tarde.'})
                found=order_tracking.lookup(c,tracking_page[1])
                return self.reply(200 if found else 404,order_tracking.public_page(found) if found else order_tracking.missing_page(),'text/html; charset=utf-8')
            if path == '/conditions':
                active=service_terms.current(c,reception_now())
                if not active:return self.reply(404,{'error':'Las condiciones vigentes aún no han sido publicadas.'})
                return self.reply(200,service_terms.public_page(active),'text/html; charset=utf-8')
            public_terms=re.fullmatch(r'/conditions/([a-f0-9]{32})',path)
            if public_terms:
                row=c.execute('SELECT * FROM service_terms WHERE id=?',(public_terms[1],)).fetchone()
                if not row:return self.reply(404,{'error':'Versión de condiciones no disponible.'})
                return self.reply(200,service_terms.public_page(row),'text/html; charset=utf-8')
            user, _ = self.session(c)
            if path in ('/', '/login') or re.fullmatch(r'/orders/[^/]{1,80}',path):
                return self.page('dashboard.html' if user else 'login.html')
            if path == '/forgot':
                return self.page('forgot.html')
            if path == '/registro':
                if not registration_enabled():return self.reply(404,{'error':'El registro de cuentas no está habilitado.'})
                return self.page('register.html')
            if path == '/reset':
                return self.page('reset.html')
            if not user:
                return self.reply(401, {'error':'Inicia sesión para continuar.'})
            agenda_item=re.fullmatch(r'/api/appointments/([0-9]+)',path)
            if agenda_item:
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                found=appointments.detail(c,int(agenda_item[1]))
                return self.reply(200,{'appointment':found}) if found else self.reply(404,{'error':'Cita no disponible.'})
            if path == '/api/appointments/availability':
                # Horarios para el personal: incluye el día de hoy (la reserva pública empieza mañana).
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                query=parse_qs(urlsplit(self.path).query)
                try: rows=appointments.available_slots(c,query.get('date',[''])[0],query.get('service',[''])[0],staff=True)
                except ValueError as error:return self.reply(400,{'error':str(error)})
                return self.reply(200,{'slots':[{'time':r['time']} for r in rows]})
            if path == '/api/agenda':
                # Agenda de Mantenimientos de Clientes: citas (misma tabla que la reserva en línea) y mantenimientos preventivos.
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                query=parse_qs(urlsplit(self.path).query);today=appointments.now().date()
                try:
                    first=appointments.date.fromisoformat(query.get('from',[''])[0]) if query.get('from',[''])[0] else today-appointments.timedelta(days=7)
                    last=appointments.date.fromisoformat(query.get('to',[''])[0]) if query.get('to',[''])[0] else today+appointments.timedelta(days=60)
                except ValueError:return self.reply(400,{'error':'Fecha no válida.'})
                if last<first or (last-first).days>400:return self.reply(400,{'error':'El período admite hasta 400 días.'})
                rows,summary=appointments.agenda(c,appointments.stamp(appointments.datetime.combine(first,appointments.time.min,appointments.TZ)),appointments.stamp(appointments.datetime.combine(last+appointments.timedelta(days=1),appointments.time.min,appointments.TZ)))
                preventive=maintenance.rows(c)
                summary['preventive']=sum(1 for r in preventive if r['state']=='scheduled' and r['due_date']>=today.isoformat())
                summary['overdue']=sum(1 for r in preventive if r['state']=='scheduled' and r['due_date']<today.isoformat())
                return self.reply(200,{'appointments':rows,'maintenance':preventive,'summary':summary,'today':today.isoformat(),'from':first.isoformat(),'to':last.isoformat(),'statuses':appointments.STATUSES,'services':appointments.services(c),'device_types':DEVICE_TYPES,'confirmation':appointments.confirmation_mode(c),'settings':appointments.settings(c) if user['role']=='administrador' else None})
            if path == '/api/appointments':
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                query=parse_qs(urlsplit(self.path).query);view=query.get('view',['day'])[0];raw=query.get('date',[''])[0]
                try:day=appointments.date.fromisoformat(raw) if raw else appointments.now().date()
                except ValueError:return self.reply(400,{'error':'Fecha inválida.'})
                if view=='month':start=appointments.datetime(day.year,day.month,1,tzinfo=appointments.TZ);next_month=appointments.date(day.year+(day.month==12),day.month%12+1,1);end=appointments.datetime.combine(next_month,appointments.time.min,appointments.TZ)
                elif view=='week':start=appointments.datetime.combine(day-appointments.timedelta(days=day.weekday()),appointments.time.min,appointments.TZ);end=start+appointments.timedelta(days=7)
                elif view=='day':start=appointments.datetime.combine(day,appointments.time.min,appointments.TZ);end=start+appointments.timedelta(days=1)
                else:return self.reply(400,{'error':'Vista de agenda inválida.'})
                rows=appointments.admin_rows(c,appointments.stamp(start),appointments.stamp(end))
                return self.reply(200,{'rows':rows,'view':view,'date':day.isoformat(),'settings':appointments.settings(c) if user['role']=='administrador' else None})
            if path == '/api/adi/status':
                # Estado real de Adi para la redacción y los canales; no expone claves.
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                import adi_ai
                usage=c.execute("SELECT COUNT(*) n FROM adi_actions WHERE action='writing_improve' AND created_at>=?",(reception_now().date().isoformat(),)).fetchone()['n']
                auto_receipt=c.execute("SELECT value FROM system_state WHERE key='receipt_mail_auto'").fetchone()
                return self.reply(200,{'writing':adi_ai.status(c),'today':usage,'channels':{'mail':mail_allowed(user),'web_chat':True,'whatsapp':False},'receipt_mail_auto':not (auto_receipt and auto_receipt['value']=='off')})
            if path == '/api/adi/admin':
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede usar la asistente administrativa.'})
                return self.reply(200,{'enabled':bool(os.getenv('OPENAI_API_KEY')),'message':'Adi responde consultas operativas desde datos autorizados.','live':adi.snapshot(c,reception_now())})
            adi_conversation=re.fullmatch(r'/api/adi/conversations(?:/([0-9]+))?',path)
            if adi_conversation:
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede usar la asistente administrativa.'})
                if adi_conversation[1]:
                    # Cada conversación solo es visible para quien la creó.
                    row=c.execute('SELECT id,title,created_at,updated_at FROM adi_admin_conversations WHERE id=? AND user_id=?',(int(adi_conversation[1]),user['id'])).fetchone()
                    if not row:return self.reply(404,{'error':'Conversación no disponible.'})
                    messages=[{'id':m['id'],'role':m['role'],'content':m['content'],'links':json.loads(m['links'] or '[]'),'created_at':m['created_at']} for m in c.execute('SELECT * FROM adi_admin_messages WHERE conversation_id=? ORDER BY id',(row['id'],))]
                    return self.reply(200,{'conversation':dict(row),'messages':messages})
                term=parse_qs(urlsplit(self.path).query).get('q',[''])[0].strip()[:100]
                if term:rows=c.execute("SELECT DISTINCT v.id,v.title,v.updated_at FROM adi_admin_conversations v LEFT JOIN adi_admin_messages m ON m.conversation_id=v.id WHERE v.user_id=? AND (instr(lower(v.title),lower(?))>0 OR instr(lower(m.content),lower(?))>0) ORDER BY v.updated_at DESC LIMIT 40",(user['id'],term,term))
                else:rows=c.execute('SELECT id,title,updated_at FROM adi_admin_conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT 40',(user['id'],))
                return self.reply(200,{'rows':[dict(r) for r in rows]})
            if path == '/api/adi/live':
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                rows=[dict(r) for r in c.execute("SELECT v.id,v.mode,v.updated_at,(SELECT content FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_message,(SELECT author FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_author FROM adi_conversations v WHERE v.mode!='closed' ORDER BY v.updated_at DESC LIMIT 100")]
                return self.reply(200,{'rows':rows})
            live_match=re.fullmatch(r'/api/adi/live/([0-9]+)',path)
            if live_match:
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                conv=c.execute('SELECT * FROM adi_conversations WHERE id=?',(int(live_match[1]),)).fetchone()
                if not conv:return self.reply(404,{'error':'Conversación no disponible.'})
                try:after=max(0,int(parse_qs(urlsplit(self.path).query).get('after',['0'])[0]))
                except ValueError:after=0
                rows=[dict(r) for r in c.execute('SELECT id,author,visibility,content,created_at FROM adi_messages WHERE conversation_id=? AND id>? ORDER BY id',(conv['id'],after))]
                safe_conv={k:conv[k] for k in ('id','mode','assigned_to','created_at','updated_at')}
                return self.reply(200,{'conversation':safe_conv,'messages':rows})
            if path == '/api/me':
                prefs=c.execute('SELECT value FROM system_state WHERE key=?',('mail_prefs:'+str(user['id']),)).fetchone() if mail_allowed(user) else None
                return self.reply(200, {'user':dict(user,mail=mail_allowed(user),mail_prefs=json.loads(prefs['value']) if prefs else None,mail_signature=mail_signature_card(c) if mail_allowed(user) else None,storage='cloud' if remote_db.configured() else 'local'),'server_time':time.time()})
            if path == '/api/weather':
                return self.reply(200, current_weather())
            if path == '/api/time':
                return self.reply(200, {'server_time':time.time(),'timezone':'America/Guayaquil'})
            if path == '/api/thermal-printer':return self.reply(200,thermal_printing.capability())
            if path == '/api/corporate':return self.reply(200,corporate.settings())
            if path in ('/api/conditions/draft','/api/conditions/draft.pdf'):
                draft=corporate.terms_draft()
                if path.endswith('.pdf'):
                    from conditions_pdf import render_conditions
                    return self.reply(200,render_conditions(draft),'application/pdf')
                return self.reply(200,draft)
            if path == '/api/conditions/current':
                active=service_terms.current(c,reception_now())
                return self.reply(200,{'terms':({**service_terms.metadata(active),'full_text':active['full_text']} if active else None),'required':terms_required()})
            if path == '/api/conditions':
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede consultar el historial de publicación.'})
                rows=c.execute('SELECT * FROM service_terms ORDER BY effective_date DESC,published_at DESC').fetchall()
                return self.reply(200,{'rows':[service_terms.metadata(r) for r in rows]})
            if path == '/api/document-logo.png':
                from document_logo import monochrome_png
                return self.reply(200,monochrome_png(),'image/png')
            if path == '/api/reception-options':
                brands = [dict(r) for r in c.execute('SELECT name,category FROM brands ORDER BY name COLLATE NOCASE')]
                # SVG primero: al ordenar por nombre, «marca.png» queda antes y «marca.svg» lo reemplaza.
                logos = {f.stem:f.name for f in sorted((ROOT / 'static' / 'brands').glob('*')) if f.suffix in ('.svg','.png') and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', f.stem)}
                import device_brands,device_manufacturers
                return self.reply(200, {'geo_metadata':GEO_METADATA,'device_types':DEVICE_TYPES,'brands':brands,'brand_logos':logos,'manufacturers':device_brands.catalog(device_manufacturers.configured())})
            if path.startswith('/api/geo/'):
                query=parse_qs(urlsplit(self.path).query)
                get=lambda key:query.get(key,[''])[0][:150]
                level=path[len('/api/geo/'):]
                if level not in ('provinces','cantons','parishes','localities'):
                    return self.reply(404, {'error':'Catálogo no disponible.'})
                return self.reply(200, {'rows':search_geography(level,get('province'),get('canton'),get('parish'),get('q')),'metadata':GEO_METADATA})
            if path.startswith('/api/order-by-code/'):
                code = unquote(path[len('/api/order-by-code/'):])
                row = c.execute('SELECT id FROM orders WHERE code=?',(code,)).fetchone()
                if not row:
                    return self.reply(404, {'error':'Orden no disponible.'})
                return self.reply(200, {'id':row['id']})
            client_detail=re.fullmatch(r'/api/clients/([0-9]+)',path)
            if client_detail:
                row=c.execute('SELECT * FROM clients WHERE id=?',(int(client_detail[1]),)).fetchone()
                if not row:return self.reply(404,{'error':'Cliente no disponible.'})
                devices=[dict(r) for r in c.execute('SELECT * FROM devices WHERE client_id=?',(row['id'],))]
                orders=[dict(r) for r in c.execute("SELECT o.id,o.code,o.created_at,o.received_at,o.status status_code,s.label status,o.problem,o.findings,o.recommendations,o.delivered_at,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,COALESCE((SELECT labor_cents+parts_cents+services_cents+digital_cents FROM order_budget b WHERE b.order_id=o.id),0) total_cents FROM orders o JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status WHERE d.client_id=? ORDER BY o.id DESC",(row['id'],))]
                batch=c.execute('SELECT filename,created_at FROM client_import_batches WHERE id=?',(row['import_batch_id'],)).fetchone() if row['import_batch_id'] else None
                return self.reply(200,{'client':client_registry.profile(row),'devices':devices,'orders':orders,'imported':dict(batch) if batch else None,'can_edit':user['role']=='administrador' or bool(row['needs_review'])})
            if path in ('/api/clients/export.csv','/api/clients/import-report.csv'):
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede exportar clientes.'})
                if path=='/api/clients/export.csv':
                    audit(c,user['id'],'clients_exported');c.commit()
                    return self.reply(200,client_import.export_csv(c),'text/csv; charset=utf-8')
                batch=parse_qs(urlsplit(self.path).query).get('batch',[''])[0]
                if not batch.isdigit() or not c.execute('SELECT 1 FROM client_import_batches WHERE id=?',(batch,)).fetchone():return self.reply(404,{'error':'Importación no disponible.'})
                return self.reply(200,client_import.report_csv(c,int(batch)),'text/csv; charset=utf-8')
            if path == '/api/clients/imports':
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede consultar importaciones.'})
                return self.reply(200,{'rows':[dict(r) for r in c.execute('SELECT b.id,b.filename,b.created_at,b.total,b.imported,b.merged,b.duplicates,b.skipped,b.errors,u.name actor FROM client_import_batches b LEFT JOIN users u ON u.id=b.actor_id ORDER BY b.id DESC LIMIT 20')]})
            if path == '/api/client-search':
                term=parse_qs(urlsplit(self.path).query).get('q',[''])[0][:150]
                rows=[dict(r) for r in c.execute("SELECT id,name,identification,document_type,phone,phone_secondary,email,trade_name,city,needs_review FROM clients WHERE instr(lower(name||' '||COALESCE(identification,'')||' '||COALESCE(phone,'')||' '||phone_secondary||' '||COALESCE(email,'')||' '||trade_name),lower(?))>0 ORDER BY name COLLATE NOCASE LIMIT 20",(term.strip(),))] if term.strip() else []
                return self.reply(200,{'rows':rows})
            if path == '/api/mail/order-link':
                # Orden activa del destinatario: el cliente se identifica por la coincidencia exacta y única de su correo, nunca por nombre.
                if not mail_allowed(user):return self.reply(403,{'error':'No tienes acceso al correo o todavía no está configurado en el servidor.'})
                if limited(c,'mail-order-link:'+str(user['id']),limit=240,window=300):return self.reply(429,{'error':'Demasiadas consultas seguidas. Espera un momento.'})
                addresses=[a.strip().lower() for a in re.split(r'[,;\s]+',parse_qs(urlsplit(self.path).query).get('to',[''])[0][:2000]) if a.strip()]
                return self.reply(200,mail_order_candidates(c,addresses))
            if path == '/api/mail/contacts':
                # Sugerencias de destinatarios: solo nombre, correo y nombre comercial de clientes reales; búsqueda acotada en el servidor.
                if not mail_allowed(user):return self.reply(403,{'error':'No tienes acceso al correo o todavía no está configurado en el servidor.'})
                if limited(c,'mail-contacts:'+str(user['id']),limit=240,window=300):return self.reply(429,{'error':'Demasiadas búsquedas seguidas. Espera un momento.'})
                term=parse_qs(urlsplit(self.path).query).get('q',[''])[0][:80].strip()
                if parse_qs(urlsplit(self.path).query).get('recent',[''])[0]=='1':
                    # Contactos frecuentes del propio usuario: destinatarios de sus últimos envíos.
                    saved=c.execute('SELECT value FROM system_state WHERE key=?',('mail_recent:'+str(user['id']),)).fetchone()
                    try:recent=json.loads(saved['value']) if saved else []
                    except ValueError:recent=[]
                    return self.reply(200,{'rows':recent[:6],'recent':True})
                if len(term)<2:return self.reply(200,{'rows':[]})
                plain=lambda text:''.join(ch for ch in unicodedata.normalize('NFD',str(text or '').lower()) if unicodedata.category(ch)!='Mn')
                term=plain(term);matches=[]
                for row in c.execute("SELECT id,name,email,trade_name,identification FROM clients ORDER BY name COLLATE NOCASE"):
                    name,mail,trade=plain(row['name']),plain(row['email']),plain(row['trade_name'])
                    if term in name or term in mail or term in trade or (term.isdigit() and len(term)>=4 and term in str(row['identification'] or '')):
                        rank=0 if name.startswith(term) or mail.startswith(term) else 1 if any(part.startswith(term) for part in name.split()) else 2
                        matches.append((0 if row['email'] else 1,rank,name,{'id':row['id'],'name':row['name'],'email':row['email'] or '','trade_name':row['trade_name'] or ''}))
                matches.sort(key=lambda item:item[:3])
                return self.reply(200,{'rows':[item[3] for item in matches[:8]],'more':len(matches)>8})
            if path == '/api/order-options':
                return self.reply(200, {'statuses':order_workspace.STATUSES,'users':[dict(r) for r in c.execute('SELECT id,name FROM users WHERE active=1 ORDER BY name')]})
            photo = re.fullmatch(r'/api/order-photo/([0-9]+)', path)
            if photo:
                # Evidencia de recepción: solo con sesión; se entrega como imagen JPEG ya validada al guardarla.
                row = c.execute('SELECT data FROM order_photos WHERE id=?', (int(photo[1]),)).fetchone()
                if not row:
                    return self.reply(404, {'error':'Foto no disponible.'})
                return self.reply(200, base64.b64decode(row['data']), 'image/jpeg')
            detail = re.fullmatch(r'/api/orders/([0-9]+)(?:/(qr\.(svg|png)|tracking-qr\.png|receipt\.pdf|thermal\.pdf|service\.pdf|label\.pdf))?', path)
            if detail:
                row = c.execute('SELECT o.*,COALESCE(NULLIF(d.kind,\'\'),d.category) type,d.brand,d.model,d.serial,d.color,c.id client_id,c.name client,c.identification,c.phone,c.email,c.province,c.city,c.address,c.location_reference,s.label status_label FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?',(int(detail[1]),)).fetchone()
                if not row:
                    return self.reply(404, {'error':'Orden no disponible.'})
                code = row['code'] or 'OP-'+str(row['id']).zfill(5)
                if detail[2]=='tracking-qr.png':
                    # QR del enlace público de seguimiento vigente: el mismo enlace que se copia y que imprime el ticket.
                    import order_tracking
                    link=order_tracking.active(c,row['id'])
                    if not link['active']:return self.reply(404,{'error':'La orden no tiene un enlace de seguimiento activo.'})
                    return self.reply(200, qr_image(link['url']+'#'+code,'png'), 'image/png')
                if detail[3]:
                    return self.reply(200, qr_image(row['qr_url'],detail[3]), 'image/svg+xml' if detail[3]=='svg' else 'image/png')
                if detail[2] in ('receipt.pdf','thermal.pdf','service.pdf','label.pdf'):
                    from receipt_pdf import render_receipt
                    pdf_order=dict(row)
                    pdf_order['current_problem']=row['problem']
                    if row['reception_snapshot']:
                        pdf_order.update(json.loads(row['reception_snapshot']))
                    service_terms.attach(c,pdf_order)
                    technical_access.attach(c,pdf_order)
                    order_workspace.attach(c,pdf_order)
                    if detail[2]=='label.pdf':
                        from label_pdf import dimensions,render_label
                        query=parse_qs(urlsplit(self.path).query)
                        try:
                            width,height=dimensions(query)
                            return self.reply(200,render_label(pdf_order,width,height,query.get('client',['0'])[0]=='1',query.get('mono',['0'])[0]=='1'),'application/pdf')
                        except ValueError as error:return self.reply(400,{'error':str(error)})
                    if detail[2]=='service.pdf':
                        from service_pdf import render_service
                        return self.reply(200,render_service(pdf_order),'application/pdf')
                    if detail[2]=='thermal.pdf':
                        from thermal_pdf import render_thermal
                        import order_tracking
                        copy=parse_qs(urlsplit(self.path).query).get('copy',['cliente'])[0]
                        if copy not in ('cliente','taller','ambas'):return self.reply(400,{'error':'Copia inválida.'})
                        pdf_order['tracking_url']=order_tracking.active(c,row['id'])['url']
                        return self.reply(200,render_thermal(pdf_order,copy),'application/pdf')
                    return self.reply(200, render_receipt(pdf_order), 'application/pdf')
                result = dict(row)
                import order_tracking
                result['tracking']=order_tracking.active(c,row['id'])
                result['receipt_mail']=receipt_mail_status(c,row['id'])
                result.pop('request_key', None)
                if result['reception_snapshot']:
                    result.update(json.loads(result['reception_snapshot']))
                result.pop('reception_snapshot',None)
                result['code'] = code
                service_terms.attach(c,result)
                technical_access.attach(c,result)
                order_workspace.attach(c,result)
                result['current_problem']=row['problem']
                result['photos']=[dict(r) for r in c.execute('SELECT id,is_main,position,size,created_at FROM order_photos WHERE order_id=? ORDER BY is_main DESC,position,id',(result['id'],))]
                result['mail']=[dict(r) for r in c.execute('SELECT id,subject,correspondent,direction,sent_at,folder,uid FROM mail_links WHERE order_id=? ORDER BY id DESC LIMIT 30',(result['id'],))] if mail_allowed(user) else None
                return self.reply(200, {'order':result})
            if path == '/api/devices/identify':
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                import device_lookup
                lookup_query=parse_qs(urlsplit(self.path).query)
                status,payload=device_lookup.identify(c,lookup_query.get('serial',[''])[0][:200],lookup_query.get('brand',[''])[0][:80],lambda:not limited(c,'device-external:'+str(user['id']),limit=40,window=3600))
                return self.reply(status,payload)
            if path in ('/api/orders', '/api/clients', '/api/devices'):
                query = parse_qs(urlsplit(self.path).query)
                term = query.get('q', [''])[0][:150]
                try:
                    page = max(1, int(query.get('page', ['1'])[0]))
                except ValueError:
                    return self.reply(400, {'error':'Página inválida.'})
                if path == '/api/orders':
                    source = 'orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status'
                    columns = "o.id,o.code,o.created_at,o.problem,o.status status_code,s.label status,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,c.name client,o.priority,o.estimated_delivery,COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'Sin asignar') responsible"
                    search = "COALESCE(o.code,'OP-'||printf('%05d',o.id))||' '||CAST(o.id AS TEXT)||' '||c.name||' '||COALESCE(c.identification,'')||' '||COALESCE(c.phone,'')||' '||COALESCE(c.trade_name,'')||' '||COALESCE(d.category,'')||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')||' '||o.problem||' '||s.label"
                    active = query.get('active', [''])[0] == '1'
                    where = ' AND o.status != \'entregado\'' if active else ''
                    ordering = 'o.id DESC'
                elif path == '/api/clients':
                    source, columns = 'clients c', "c.id,c.name,c.phone,c.phone_secondary,c.email,c.identification,c.document_type,c.trade_name,c.client_type,c.city,c.canton,c.needs_review,c.import_batch_id,(SELECT COUNT(*) FROM orders o JOIN devices d ON d.id=o.device_id WHERE d.client_id=c.id) orders"
                    search = "c.name||' '||COALESCE(c.phone,'')||' '||c.phone_secondary||' '||COALESCE(c.email,'')||' '||c.identification||' '||c.trade_name||' '||c.city"
                    where, ordering = '', 'c.name COLLATE NOCASE' if query.get('sort',[''])[0]=='name' else 'c.id DESC'
                    conditions={'review':'c.needs_review=1','complete':'c.needs_review=0','imported':'c.import_batch_id IS NOT NULL','orders':'EXISTS(SELECT 1 FROM devices d JOIN orders o ON o.device_id=d.id WHERE d.client_id=c.id)','no_id':"c.identification=''"}
                    chosen=query.get('filter',[''])[0]
                    if chosen:
                        if chosen not in conditions:return self.reply(400,{'error':'Filtro inválido.'})
                        where+=' AND '+conditions[chosen]
                    kind=query.get('type',[''])[0]
                    if kind:
                        if kind not in ('natural','empresa'):return self.reply(400,{'error':'Filtro inválido.'})
                        where+=' AND c.client_type=?';client_kind=kind
                else:
                    source = 'devices d JOIN clients c ON c.id=d.client_id'
                    columns = 'd.id,d.client_id,c.name client,COALESCE(NULLIF(d.kind,\'\'),d.category) type,d.brand,d.model,d.serial'
                    search = "c.name||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')"
                    where, ordering = '', 'd.id DESC'
                args=[term]
                if path == '/api/clients' and query.get('type',[''])[0]:args.append(query['type'][0])
                if path == '/api/orders':
                    status=query.get('status',[''])[0]
                    if status:
                        if status not in order_workspace.STATUSES:return self.reply(400,{'error':'Estado inválido.'})
                        where+=' AND o.status=?';args.append(status)
                    for name,expression in [('client','c.name'),('equipment',"COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')")]:
                        value=query.get(name,[''])[0][:150]
                        if value:where+=' AND instr(lower('+expression+'),lower(?))>0';args.append(value)
                    if query.get('from',[''])[0] and query.get('to',[''])[0] and query['from'][0]>query['to'][0]:return self.reply(400,{'error':'La fecha Desde no puede ser posterior a Hasta.'})
                    from datetime import date
                    for name,operator in [('from','>='),('to','<=')]:
                        value=query.get(name,[''])[0]
                        if value:
                            try:
                                if date.fromisoformat(value).isoformat()!=value:raise ValueError()
                            except ValueError:return self.reply(400,{'error':'Fecha de filtro inválida.'})
                            where+=" AND date(o.created_at,'unixepoch','-5 hours')"+operator+'?';args.append(value)
                condition = f' WHERE instr(lower({search}),lower(?))>0' + where
                total = c.execute('SELECT COUNT(*) FROM '+source+condition, args).fetchone()[0]
                if path=='/api/orders':page=min(page,max(1,(total+49)//50))
                rows = [dict(r) for r in c.execute('SELECT '+columns+' FROM '+source+condition+' ORDER BY '+ordering+' LIMIT 50 OFFSET ?', (*args,(page-1)*50))]
                return self.reply(200, {'rows':rows,'total':total,'page':page,'pages':max(1,(total+49)//50)})
            if path == '/api/version':
                # Versión que ejecuta realmente este servidor (la del código desplegado), para que las pestañas abiertas detecten cuándo deben recargarse.
                try:
                    latest=versioning.load()['releases'][0];changes=[text for group in ('features','improvements','fixes','security','performance') for text in latest.get('changes',{}).get(group,[])]
                    return self.reply(200,{'version':latest['version'],'date':latest.get('date',''),'summary':latest.get('summary',''),'highlights':[text[:180] for text in changes[:3]],'more':max(0,len(changes)-3)})
                except Exception:
                    return self.reply(503,{'error':'No se pudo leer la versión instalada.'})
            if path == '/api/system':
                try:return self.reply(200, versioning.overview())
                except versioning.RegistryError as error:return self.reply(500,{'error':str(error)})
            if path == '/api/reports':
                counts = [dict(r) for r in c.execute("SELECT s.code,s.label,COUNT(o.id) total FROM statuses s LEFT JOIN orders o ON o.status=s.code GROUP BY s.code ORDER BY CASE s.code WHEN 'pendiente' THEN 1 WHEN 'reparacion' THEN 2 WHEN 'esperando_cliente' THEN 3 WHEN 'presupuesto' THEN 4 WHEN 'espera_entrega' THEN 5 WHEN 'listo' THEN 6 ELSE 7 END")]
                return self.reply(200, {'statuses':counts,'clients':c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],'devices':c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]})
            if path == '/api/settings':
                if user['role'] != 'administrador':
                    return self.reply(403, {'error':'Solo administración puede acceder a la configuración.'})
                labels={'login':'Inicio de sesión','logout':'Cierre de sesión','sessions_revoked':'Cierre de todas las sesiones','other_sessions_revoked':'Cierre de otras sesiones','password_changed':'Cambio de contraseña','password_reset':'Contraseña restablecida','profile_updated':'Perfil actualizado','auth_policy_updated':'Políticas de acceso actualizadas','account_approved':'Cuenta aprobada','account_rejected':'Solicitud rechazada','account_updated':'Cuenta del equipo modificada','clients_exported':'Exportación de clientes','clients_imported':'Importación de clientes'}
                activity=[{'label':labels[r['action']],'at':r['created_at']} for r in c.execute('SELECT action,created_at FROM audit WHERE user_id=? AND action IN ('+','.join('?' for _ in labels)+') ORDER BY id DESC LIMIT 12',(user['id'],*labels))]
                return self.reply(200, {'profile':{k:user[k] for k in ('name','username','email','role')},'me':user['id'],'active_sessions':c.execute('SELECT COUNT(*) FROM sessions WHERE user_id=? AND expires>?',(user['id'],int(time.time()))).fetchone()[0],'security_activity':activity,'registration_enabled':registration_enabled(),'captcha_mode':captcha_mode(),'mail':mail_pro.status(),'mail_signature':mail_signature(c),'mail_signature_card':mail_signature_card(c) if mail_pro.configured() else None,'accounts':[dict(r) for r in c.execute("SELECT u.id,u.name,u.username,u.email,u.role,u.active,(SELECT MAX(a.created_at) FROM audit a WHERE a.user_id=u.id AND a.action='login') last_login,(SELECT COUNT(*) FROM sessions s WHERE s.user_id=u.id AND s.expires>?) sessions FROM users u WHERE u.approval='approved' ORDER BY u.id",(int(time.time()),))],'requests':[dict(r) for r in c.execute("SELECT id,name,username,email,phone,identification,job_title,requested_at,approval FROM users WHERE approval IN ('pending','rejected') ORDER BY approval,id DESC")],'smtp_configured':bool(os.getenv('SMTP_HOST')),'openai_configured':bool(os.getenv('OPENAI_API_KEY')),'login_lockout_seconds':auth_policy(c)['lockout_seconds'],'auth_policy':auth_policy(c),'antibot_configured':bool(os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY')),'origin':os.getenv('APP_URL','http://127.0.0.1:8010')})
            if path == '/api/notifications':
                result=notifications.build(c,user,reception_now(),mail_allowed(user))
                # Versión que ejecuta el servidor: permite avisar a una pestaña que quedó abierta con una versión anterior.
                try:result['app_version']=versioning.load()['releases'][0]['version']
                except Exception:pass
                return self.reply(200,result)
            if path.startswith('/api/mail/'):
                if not mail_allowed(user):return self.reply(403,{'error':'No tienes acceso al correo o todavía no está configurado en el servidor.'})
                query=parse_qs(urlsplit(self.path).query);arg=lambda name:query.get(name,[''])[0]
                client=None
                if path=='/api/mail/check':
                    # Consulta ligera para la interfaz: no leídos, cuota y correos nuevos registrados. «now=1» fuerza la sincronización.
                    try:state=notifications.mail_status(c,reception_now(),0 if arg('now')=='1' else 30)
                    except mail_pro.MailError as error:return self.reply(502,{'error':str(error),'kind':error.kind})
                    if not state:return self.reply(502,{'error':'El servidor de correo no informó la bandeja de entrada.'})
                    return self.reply(200,{'unread':state.get('unread',0),'checked':state.get('checked',''),'quota':state.get('quota'),'events':notifications.mail_events(c)[-5:]})
                if path=='/api/mail/signature':
                    return self.reply(200,{'card':mail_signature_card(c)})
                if path=='/api/mail/storage':
                    # Independiente de la lectura y el envío: si falla, el resto del correo sigue funcionando.
                    if arg('now')=='1' and limited(c,'mail-storage:'+str(user['id']),limit=30,window=300):return self.reply(429,{'error':'Espera un momento antes de volver a actualizar el almacenamiento.'})
                    storage=notifications.mail_storage(c,reception_now(),0 if arg('now')=='1' else 60)
                    return self.reply(200,{key:storage.get(key) for key in ('state','used','limit','source','checked','stale','detail','cpanel','failed')})
                try:
                    client=mail_pro.open_imap()
                    if path=='/api/mail/overview':
                        return self.reply(200,{'account':mail_pro.settings()['username'],'folders':mail_pro.overview(client),'quota':mail_pro.quota(client),'checked':reception_now().isoformat(timespec='seconds'),'signature':mail_signature(c),'signature_card':mail_signature_card(c),'page_size':mail_pro.PAGE})
                    folder,_=mail_pro.resolve(client,arg('folder') or 'INBOX')
                    if path=='/api/mail/messages':
                        try:page=max(1,int(arg('page') or '1'))
                        except ValueError:return self.reply(400,{'error':'Página inválida.'})
                        uids=mail_pro.search(client,folder['id'],arg('q'),arg('flagged')=='1',arg('unread')=='1')
                        if arg('attach')=='1':
                            # IMAP no busca por adjuntos: se revisa la estructura de los 300 mensajes más recientes del resultado.
                            uids=[row['uid'] for row in mail_pro.summaries(client,uids[:300],previews=False) if row['attachments']]
                        rows=mail_pro.summaries(client,uids[(page-1)*mail_pro.PAGE:page*mail_pro.PAGE])
                        return self.reply(200,{'rows':rows,'total':len(uids),'page':page,'pages':max(1,(len(uids)+mail_pro.PAGE-1)//mail_pro.PAGE),'folder':folder,'uidvalidity':getattr(mail_pro.search,'uidvalidity',0)})
                    if not arg('uid').isdigit():return self.reply(400,{'error':'Mensaje no válido.'})
                    if path=='/api/mail/message':
                        message=mail_pro.read_message(client,folder['id'],int(arg('uid')))
                        sender=(message['from'] or [{}])[0].get('address','') if folder['role']!='sent' else (message['to'] or [{}])[0].get('address','')
                        known=c.execute("SELECT id,name FROM clients WHERE email!='' AND lower(email)=lower(?) ORDER BY id LIMIT 1",(sender,)).fetchone() if sender else None
                        message['client']=dict(known) if known else None
                        message['links']=[dict(r) for r in c.execute('SELECT l.id,o.id order_id,o.code FROM mail_links l JOIN orders o ON o.id=l.order_id WHERE l.message_id=? ORDER BY l.id',(message['message_id'],))] if message['message_id'] else []
                        return self.reply(200,{'message':message})
                    if path=='/api/mail/attachment':
                        if not arg('part').isdigit():return self.reply(400,{'error':'Adjunto no válido.'})
                        if arg('inline')=='1':
                            kind,content=mail_pro.inline_image(client,folder['id'],int(arg('uid')),int(arg('part')))
                            return self.reply(200,content,kind)
                        name,content=mail_pro.attachment(client,folder['id'],int(arg('uid')),int(arg('part')))
                        audit(c,user['id'],'mail_attachment_downloaded');c.commit()
                        # Siempre como descarga binaria: el navegador nunca interpreta el adjunto.
                        return self.reply(200,content,'application/octet-stream')
                    return self.reply(404,{'error':'Recurso no disponible.'})
                except mail_pro.MailError as error:
                    return self.reply(400 if error.kind=='configuracion' else 502,{'error':str(error),'kind':error.kind})
                finally:
                    if client is not None:mail_pro.close_imap(client)
            if path in ('/api/dashboard','/api/activity','/api/maintenance'):
                now=reception_now();today=now.date().isoformat()
                if path=='/api/maintenance':return self.reply(200,{'rows':maintenance.rows(c),'today':today,'profiles':{k:v[0] for k,v in maintenance.PROFILES.items()}})
                activity_query=parse_qs(urlsplit(self.path).query) if path=='/api/activity' else {}
                # Historial de una sola orden: la misma fuente que el seguimiento del inicio.
                if activity_query.get('order',[''])[0]:
                    if not activity_query['order'][0].isdigit():return self.reply(400,{'error':'Orden inválida.'})
                    return self.reply(200,{'rows':order_workspace.history(c,int(activity_query['order'][0]))})
                activity=order_workspace.history(c,limit=12 if path!='/api/activity' or activity_query.get('recent',[''])[0]=='1' else 300)
                if path=='/api/activity':return self.reply(200,{'rows':activity})
                counts={r['code']:r['total'] for r in c.execute('SELECT s.code,COUNT(o.id) total FROM statuses s LEFT JOIN orders o ON o.status=s.code GROUP BY s.code')}
                source='orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status'
                columns='o.id,o.code,o.status status_code,s.label status,o.updated_at,o.estimated_delivery,c.name client,c.phone,d.brand,d.model'
                attention=[dict(r) for r in c.execute("SELECT "+columns+" FROM "+source+" WHERE o.status IN ('esperando_cliente','presupuesto','espera_entrega','listo') OR (o.estimated_delivery!='' AND o.estimated_delivery<? AND o.status!='entregado') ORDER BY CASE o.status WHEN 'esperando_cliente' THEN 1 WHEN 'presupuesto' THEN 2 WHEN 'espera_entrega' THEN 3 WHEN 'listo' THEN 4 ELSE 5 END,o.estimated_delivery,o.id LIMIT 8",(today,))]
                deliveries=[dict(r) for r in c.execute("SELECT "+columns+" FROM "+source+" WHERE o.status!='entregado' AND (o.estimated_delivery>=? OR o.status IN ('listo','espera_entrega')) ORDER BY CASE WHEN o.estimated_delivery='' THEN 1 ELSE 0 END,o.estimated_delivery,o.id LIMIT 5",(today,))]
                scheduled=[r for r in maintenance.rows(c) if r['state'] in ('scheduled','appointment')][:5]
                today_start=appointments.stamp(appointments.datetime.combine(now.date(),appointments.time.min,appointments.TZ));tomorrow=appointments.stamp(appointments.datetime.combine(now.date()+appointments.timedelta(days=1),appointments.time.min,appointments.TZ))
                today_appointments=appointments.admin_rows(c,today_start,tomorrow) if user['role'] in ('administrador','tecnico') else []
                pending_chats=c.execute("SELECT count(*) FROM adi_conversations WHERE mode='human'").fetchone()[0] if user['role']=='administrador' else 0
                assistance=None
                if user['role']=='administrador':
                    assistance=dict(c.execute("SELECT COALESCE(SUM(last_seen_admin='' AND EXISTS(SELECT 1 FROM adi_messages m WHERE m.conversation_id=ac.id AND m.author='client' AND m.visibility='public')),0) new_conversations,COALESCE(SUM(mode='human' AND (SELECT m.author FROM adi_messages m WHERE m.conversation_id=ac.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1)='client'),0) waiting,COALESCE(SUM(mode='human'),0) transferred FROM adi_conversations ac WHERE mode!='closed'").fetchone())
                return self.reply(200,{'counts':counts,'attention':attention,'activity':activity,'maintenance':scheduled,'deliveries':deliveries,'today':today,'appointments':today_appointments,'pending_chats':pending_chats,'assistance':assistance,'upcoming_appointments':c.execute("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status IN ('solicitada','confirmada','reprogramada') AND starts_at>=?",(appointments.stamp(now),)).fetchone()[0] if user['role'] in ('administrador','tecnico') else 0,'pending_accounts':c.execute("SELECT COUNT(*) FROM users WHERE approval='pending'").fetchone()[0] if user['role']=='administrador' else 0,'pending_appointments':c.execute("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status='solicitada' AND starts_at>=?",(appointments.stamp(now),)).fetchone()[0] if user['role'] in ('administrador','tecnico') else 0})
            search_route=path=='/api/search'
            if search_route:
                term=parse_qs(urlsplit(self.path).query).get('q',[''])[0].strip()[:150]
                if len(term)<2:return self.reply(200,{'rows':[]})
                source="FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status WHERE instr(lower(COALESCE(o.code,'')||' '||c.name||' '||COALESCE(c.identification,'')||' '||COALESCE(c.phone,'')||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')),lower(?))>0"
                # Vista rápida del buscador: los 8 más recientes (el código exacto primero) y el total real para la búsqueda completa.
                rows=[dict(r) for r in c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,c.name client,d.brand,d.model,d.serial,o.status status_code,s.label status "+source+" ORDER BY lower(COALESCE(o.code,''))=lower(?) DESC,o.id DESC LIMIT 8",(term,term))]
                return self.reply(200,{'rows':rows,'total':c.execute('SELECT COUNT(*) '+source,(term,)).fetchone()[0]})
            maintenance_pdf=re.fullmatch(r'/api/maintenance/([0-9]+)/(card|thermal)\.pdf',path)
            if maintenance_pdf:
                row=next((r for r in maintenance.rows(c) if r['id']==int(maintenance_pdf[1])),None)
                if not row:return self.reply(404,{'error':'Mantenimiento no disponible.'})
                try:return self.reply(200,maintenance.card(row,maintenance_pdf[2]=='thermal'),'application/pdf')
                except ValueError as error:return self.reply(400,{'error':str(error)})
        return self.reply(404, {'error':'Recurso no disponible.'})

    def do_POST(self):
        preference=re.fullmatch(r'/maintenance-preferences/([A-Za-z0-9_-]{40,60})',urlsplit(self.path).path)
        if preference:
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute('SELECT id,order_id FROM maintenance WHERE unsubscribe_token=?',(preference[1],)).fetchone()
                if not row:return self.reply(404,{'error':'Enlace no disponible.'})
                now=reception_now()
                c.execute("UPDATE maintenance SET consent='declined',consent_at=?,consent_actor=NULL,updated_at=? WHERE id=?",(now.isoformat(),now.isoformat(),row['id']))
                order_workspace.event(c,row['order_id'],None,now,'maintenance','Cliente retiró el consentimiento mediante enlace seguro.')
                return self.reply(200,'<!doctype html><html lang="es"><meta charset="utf-8"><title>Preferencias actualizadas</title><h1>PC-DOCTOR S.A.</h1><p>Recordatorios desactivados.</p></html>','text/html; charset=utf-8')
        try:
            origin = self.headers.get('Origin')
            expected = os.getenv('APP_URL', 'http://127.0.0.1:8010').rstrip('/')
            # JSON y orígenes explícitos: formularios externos no pueden enviar estos POST.
            if not allowed_request_origin(origin,expected) or self.headers.get_content_type() != 'application/json':
                return self.reply(403, {'error':'Solicitud no autorizada.'})
            path = urlsplit(self.path).path
            workspace_post=bool(re.fullmatch(r'/api/orders/[0-9]+/workspace',path))
            max_body=9000000 if path in ('/api/clients/import/preview','/api/clients/import/commit') else 6000000 if path in ('/api/mail/send','/api/mail/draft') else 100000 if path=='/api/conditions' else 900000 if re.fullmatch(r'/api/orders/[0-9]+/photos',path) else (65536 if workspace_post else 16384)
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > max_body:
                return self.reply(400, {'error':'Solicitud inválida.'})
            data = json.loads(self.rfile.read(length))
            appointment_config_post=path=='/api/appointments/config'
            if not isinstance(data, dict) or any(not isinstance(v,(str,bool)) and not (workspace_post and ((k=='lines' and isinstance(v,list)) or (k=='revision' and type(v) is int))) and not (appointment_config_post and ((k in ('hours','services','staff_hours') and isinstance(v,list)) or (k in ('holiday','new_service') and isinstance(v,dict)))) for k,v in data.items()):
                return self.reply(400, {'error':'Datos inválidos.'})
            path = urlsplit(self.path).path
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if path == '/api/public/appointments':
                    if limited(c,'appointment-ip:'+digest(self.client_address[0]),12,900):return self.reply(429,{'error':'Demasiadas solicitudes. Intenta más tarde.'})
                    key=str(data.get('request_key','')).strip()
                    if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',key):return self.reply(400,{'error':'Actualiza el formulario e inténtalo nuevamente.'})
                    previous=c.execute('SELECT id,public_code,starts_at,status FROM appointments WHERE deleted_at IS NULL AND request_key=?',(key,)).fetchone()
                    if previous:return self.reply(200,{'ok':True,'id':previous['id'],'code':previous['public_code'],'starts_at':previous['starts_at'],'status':previous['status'],'duplicate':True})
                    data['request_key']=key
                    status,payload=appointments.create(c,data)
                    if status==201:
                        # Correo al cliente con los datos guardados: solicitud recibida o cita confirmada, según el estado real.
                        payload['mail']=appointment_mail.send(c,payload['id'],appointment_mail.kind_for(payload['status']))
                        return self.reply(status,payload)
                    return self.reply(status,payload)
                if path == '/api/public/appointments/manage':
                    code=str(data.get('code',''))[:40];token=str(data.get('token',''))
                    row=c.execute('SELECT * FROM appointments WHERE deleted_at IS NULL AND public_code=?',(code,)).fetchone()
                    if not row or not secrets.compare_digest(row['manage_token_hash'],appointments.token_hash(token)):return self.reply(404,{'error':'No encontramos una cita válida con ese enlace.'})
                    if data.get('action')=='cancel':
                        if row['status'] in ('cancelada','completada','no_asistio'):return self.reply(409,{'error':'La cita ya no se puede cancelar desde este enlace.'})
                        now=appointments.stamp(appointments.now());c.execute("UPDATE appointments SET status='cancelada',updated_at=? WHERE id=?",(now,row['id']))
                        c.execute("INSERT INTO appointment_events(appointment_id,event,old_start,old_status,new_status,created_at) VALUES (?,'cancelled',?,?,?,?)",(row['id'],row['starts_at'],row['status'],'cancelada',now))
                        if row['email'] and row['communications_consent']:c.execute("INSERT OR IGNORE INTO appointment_notifications(appointment_id,generation,event,channel,result,created_at) VALUES (?,?,'cancelled','email','pending',?)",(row['id'],row['generation'],now))
                        appointment_mail.send(c,row['id'],'cancelled');return self.reply(200,{'ok':True,'status':'cancelada'})
                    if data.get('action')=='reschedule':
                        if row['status'] in ('cancelada','completada','no_asistio'):return self.reply(409,{'error':'La cita ya está cerrada y no se puede reprogramar desde este enlace.'})
                        try:start=appointments.parse_start(str(data.get('starts_at','')))
                        except ValueError as error:return self.reply(400,{'error':str(error)})
                        result=appointments.reschedule(c,row,start,None)
                        if result.get('ok'):appointment_mail.send(c,row['id'],'rescheduled')
                        return self.reply(200 if result.get('ok') else 409,result)
                    return self.reply(400,{'error':'Acción de cita inválida.'})
                if path == '/api/public/adi/message':
                    if limited(c,'adi-ip:'+digest(self.client_address[0]),30,300):return self.reply(429,{'error':'Espera un momento antes de enviar otro mensaje.'})
                    text=str(data.get('message','')).strip()
                    if not text or len(text)>3000:return self.reply(400,{'error':'Escribe un mensaje de hasta 3000 caracteres.'})
                    cookies=SimpleCookie()
                    try:cookies.load(self.headers.get('Cookie',''))
                    except Exception:pass
                    token=cookies['pcdoctor_adi'].value if 'pcdoctor_adi' in cookies else ''
                    conv=c.execute('SELECT * FROM adi_conversations WHERE token_hash=?',(digest(token),)).fetchone() if token else None
                    new_token=''
                    if not conv:
                        new_token=secrets.token_urlsafe(32);now=appointments.stamp(appointments.now())
                        cid=c.execute("INSERT INTO adi_conversations(token_hash,mode,created_at,updated_at) VALUES (?,'adi',?,?)",(digest(new_token),now,now)).lastrowid
                        conv=c.execute('SELECT * FROM adi_conversations WHERE id=?',(cid,)).fetchone()
                    now=appointments.stamp(appointments.now())
                    if conv['mode']=='closed':
                        # Una conversación finalizada se reanuda con Adi cuando el cliente vuelve a escribir; el historial se conserva.
                        c.execute("UPDATE adi_conversations SET mode='adi',assigned_to=NULL,updated_at=? WHERE id=?",(now,conv['id']));conv=c.execute('SELECT * FROM adi_conversations WHERE id=?',(conv['id'],)).fetchone()
                    c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client',?,?)",(conv['id'],text,now))
                    answer='Un asesor de PC-DOCTOR S.A. revisará tu solicitud.' if conv['mode']=='human' and not conv['assigned_to'] else None  # Con un asesor conectado, Adi no interviene.
                    context=None
                    match=re.search(r'(PCD-\d{8}-\d{4,}).*?(\d{10}|\d{13})',text,re.I)
                    if match and conv['mode']=='adi':
                        found=adi.order_status(c,match[1].upper(),match[2]);context={'orden':found} if found else None
                        if found:answer=f"Tu orden {found['code']} está en estado «{found['status']}». Equipo: {found['brand'] or ''} {found['model'] or ''}. Para más información, puedo solicitar atención del taller."
                    if answer is None and conv['mode']=='adi':answer=adi.reply(c,text,context=context)
                    if answer:
                        c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'adi',?,?)",(conv['id'],answer,now));c.execute('UPDATE adi_conversations SET updated_at=? WHERE id=?',(now,conv['id']))
                    response={'ok':True,'conversation_id':conv['id'],'mode':conv['mode'],'state':adi_public_state(conv),'messages':[dict(r) for r in c.execute("SELECT id,author,content,created_at FROM adi_messages WHERE conversation_id=? AND id>(SELECT COALESCE(MAX(id),0)-2 FROM adi_messages WHERE conversation_id=?) ORDER BY id",(conv['id'],conv['id']))]}
                    cookie='pcdoctor_adi='+new_token+'; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict'+('; Secure' if os.getenv('SESSION_SECURE','false').lower()=='true' else '') if new_token else None
                    return self.reply(201,response,cookie=cookie)
                if path == '/api/public/adi/human':
                    cookies=SimpleCookie()
                    try:cookies.load(self.headers.get('Cookie',''))
                    except Exception:pass
                    token=cookies['pcdoctor_adi'].value if 'pcdoctor_adi' in cookies else '';conv=c.execute('SELECT id,mode,assigned_to FROM adi_conversations WHERE token_hash=?',(digest(token),)).fetchone() if token else None
                    if not conv:return self.reply(404,{'error':'Inicia una conversación con Adi primero.'})
                    if conv['mode']=='human':return self.reply(200,{'ok':True,'mode':'human','state':adi_public_state(conv)})  # Ya solicitada: no se duplica el registro.
                    now=appointments.stamp(appointments.now());c.execute("UPDATE adi_conversations SET mode='human',assigned_to=NULL,updated_at=? WHERE id=?",(now,conv['id']));c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client','El cliente solicita atención humana.',?)",(conv['id'],now))
                    return self.reply(200,{'ok':True,'mode':'human','state':'waiting'})
                if path == '/api/captcha':
                    if captcha_mode()!='local':return self.reply(404,{'error':'Verificación no disponible.'})
                    if limited(c,'captcha-ip:'+digest(self.client_address[0]),limit=40,window=600):
                        return self.reply(429,{'error':'Demasiadas verificaciones. Espera unos minutos e inténtalo de nuevo.'})
                    return self.reply(200,new_captcha(c))
                if path == '/api/login':
                    login, password = str(data.get('login','')).strip(), str(data.get('password',''))
                    if not login or not password or len(login)>254 or len(password)>256 or ('@' in login and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',login)):
                        return self.reply(400,{'error':'Completa un usuario o correo válido y tu contraseña.'})
                    account_hash=digest(login.casefold());ip_hash=digest(self.client_address[0]);ip_key='login-ip:'+ip_hash;user_key='login-user:'+account_hash
                    blocked_ip=limit_reached(c,ip_key);blocked_user=limit_reached(c,user_key)
                    if blocked_ip or blocked_user:
                        auth_event(c,account_hash,ip_hash,'limited')
                        audit(c,None,'login_rate_limited')
                        return self.reply(429, {'error':'Por seguridad, el acceso está temporalmente limitado. Inténtalo más tarde o recupera tu contraseña.'})
                    if captcha_mode()=='local' and not verify_captcha(c,str(data.get('bot_token',''))):
                        return self.reply(403,{'error':'Marca «No soy un robot» para iniciar sesión.','challenge':True})
                    if (bot_always() or bot_required(c,ip_key)) and not verify_bot(str(data.get('bot_token','')),'login'):
                        return self.reply(403,{'error':'Completa la verificación de seguridad. Si falla, puedes esperar o recuperar tu contraseña.','challenge':True,'sitekey':os.getenv('TURNSTILE_SITE_KEY')})
                    row = c.execute('SELECT * FROM users WHERE (username=? OR email=?) AND active=1', (login,login)).fetchone()
                    valid = password_ok(password, row['password_hash'] if row else DUMMY_HASH)
                    if not row or not valid:
                        lock_window=auth_policy(c)['lockout_seconds']
                        limited(c,user_key,limit=4,window=lock_window);limited(c,ip_key,limit=4,window=lock_window)
                        for key in (user_key,ip_key):
                            c.execute('UPDATE attempts SET expires=? WHERE bucket=? AND count=5',(int(time.time())+lock_window,key))
                        auth_event(c,account_hash,ip_hash,'failed')
                        audit(c, None, 'login_failed')
                        if limit_reached(c,user_key) or limit_reached(c,ip_key):
                            auth_event(c,account_hash,ip_hash,'limited')
                            audit(c,None,'login_rate_limited')
                            return self.reply(429, {'error':'Por seguridad, el acceso está temporalmente limitado. Inténtalo más tarde o recupera tu contraseña.'})
                        return self.reply(401, {'error':'No pudimos iniciar sesión. Verifica tus credenciales e inténtalo nuevamente.'})
                    if ARGON2 is not None and (not row['password_hash'].startswith('$argon2id$') or ARGON2.check_needs_rehash(row['password_hash'])):
                        c.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash(password),row['id']))
                    _, previous = self.session(c)
                    c.execute('DELETE FROM sessions WHERE token_hash=?', (digest(previous),))
                    remember = data.get('remember') is True
                    token, csrf, age = make_session(c, row['id'], remember)
                    auth_event(c,account_hash,ip_hash,'success')
                    c.execute('DELETE FROM attempts WHERE bucket=?',(user_key,))
                    audit(c, row['id'], 'login')
                    return self.reply(200, {'ok':True}, cookie=self.cookie(token, age if remember else None))
                if path == '/api/register':
                    # Alta pública de solicitudes: la cuenta queda inactiva hasta que administración la apruebe.
                    if not registration_enabled():return self.reply(404,{'error':'El registro de cuentas no está habilitado.'})
                    if limited(c,'register-ip:'+digest(self.client_address[0]),limit=5,window=3600):
                        return self.reply(429,{'error':'Demasiadas solicitudes. Inténtalo más tarde.'})
                    token=str(data.get('bot_token',''))
                    if (captcha_mode()=='local' and not verify_captcha(c,token)) or (captcha_mode()=='turnstile' and not verify_bot(token,'register')):
                        return self.reply(403,{'error':'Completa la verificación de seguridad para enviar la solicitud.','challenge':True,'sitekey':os.getenv('TURNSTILE_SITE_KEY')})
                    values={key:str(data.get(key,'')).strip() for key in ('name','username','email','phone','identification','job_title')}
                    password=str(data.get('password',''));minimum=auth_policy(c)['password_min'];errors={}
                    if not values['name'] or len(values['name'])>150:errors['name']='Escribe tus nombres y apellidos.'
                    if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,50}',values['username']):errors['username']='Usa de 3 a 50 letras, números, punto, guion o guion bajo.'
                    if len(values['email'])>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']):errors['email']='Introduce un correo electrónico válido.'
                    if not valid_ecuador_phone(values['phone']):errors['phone']='Ingresa un móvil 09…, fijo con código de área o +593….'
                    if values['identification'] and (len(values['identification'])!=10 or reception.document_error(values['identification'])):errors['identification']='La cédula no es válida.'
                    if len(values['job_title'])>100:errors['job_title']='Usa hasta 100 caracteres.'
                    if not minimum<=len(password)<=256:errors['password']=f'Usa una contraseña de {minimum} a 256 caracteres.'
                    elif password!=str(data.get('repeat','')):errors['repeat']='Las contraseñas no coinciden.'
                    common_file=os.getenv('PASSWORD_BLOCKLIST_FILE','')
                    if 'password' not in errors and common_file and password.casefold() in {line.strip().casefold() for line in Path(common_file).read_text().splitlines()}:errors['password']='Esta contraseña es demasiado común.'
                    if errors:return self.reply(400,{'error':'Revisa los campos señalados.','fields':errors})
                    # Respuesta idéntica exista o no la cuenta: no se revela qué usuarios o correos están registrados.
                    hashed=password_hash(password)
                    matches=c.execute('SELECT id,approval FROM users WHERE username=? OR email=?',(values['username'],values['email'])).fetchall()
                    if len(matches)==1 and matches[0]['approval']=='rejected':
                        # Una solicitud rechazada puede volver a enviarse: se actualiza y queda de nuevo pendiente de revisión.
                        c.execute("UPDATE users SET username=?,email=?,name=?,password_hash=?,phone=?,identification=?,job_title=?,approval='pending',active=0,requested_at=?,reviewed_by=NULL,reviewed_at=NULL WHERE id=?",(values['username'],values['email'],values['name'],hashed,values['phone'],values['identification'],values['job_title'],int(time.time()),matches[0]['id']))
                        audit(c,None,'account_requested',matches[0]['id'])
                    elif not matches:
                        uid=c.execute("INSERT INTO users(username,email,name,password_hash,role,active,created_at,phone,identification,job_title,approval,requested_at) VALUES (?,?,?,?,'tecnico',0,?,?,?,?,'pending',?)",(values['username'],values['email'],values['name'],hashed,int(time.time()),values['phone'],values['identification'],values['job_title'],int(time.time()))).lastrowid
                        audit(c,None,'account_requested',uid)
                    return self.reply(201,{'ok':True,'message':'Solicitud recibida. Un administrador la revisará; podrás iniciar sesión cuando sea aprobada.'})
                if path == '/api/forgot':
                    email = str(data.get('email','')).strip()
                    if len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
                        return self.reply(400,{'error':'Introduce un correo electrónico con formato válido.'})
                    if bot_required(c,'reset-ip:'+digest(self.client_address[0])) and not verify_bot(str(data.get('bot_token','')),'forgot'):
                        return self.reply(403,{'error':'Completa la verificación de seguridad. Puedes esperar e intentarlo más tarde.','challenge':True,'sitekey':os.getenv('TURNSTILE_SITE_KEY')})
                    ip_blocked = limited(c, 'reset-ip:'+digest(self.client_address[0]), 5)
                    mail_blocked = limited(c, 'reset-email:'+digest(email.casefold()), 3)
                    row = c.execute('SELECT id,email FROM users WHERE email=? AND active=1', (email,)).fetchone()
                    if row and not ip_blocked and not mail_blocked:
                        token = secrets.token_urlsafe(32)
                        c.execute('DELETE FROM reset_tokens WHERE user_id=?', (row['id'],))
                        c.execute('INSERT INTO reset_tokens VALUES (?,?,?)', (digest(token),row['id'],int(time.time())+1200))
                        c.commit()
                        dispatch_security_job(lambda:deliver_reset(row['email'],token,row['id']))
                    return self.reply(200, {'ok':True,'message':'Si el correo está asociado a una cuenta, recibirás las instrucciones para restablecer tu contraseña.'})
                if path == '/api/reset':
                    if limited(c, 'reset-use:'+digest(self.client_address[0]), 10):
                        return self.reply(429, {'error':'Demasiados intentos. Intenta más tarde.'})
                    password = str(data.get('password',''))
                    minimum=auth_policy(c)['password_min']
                    if not minimum <= len(password) <= 256:
                        return self.reply(400, {'error':f'Usa una contraseña de {minimum} a 256 caracteres.'})
                    if 'repeat' in data and password!=data['repeat']:
                        return self.reply(400,{'error':'Las contraseñas no coinciden.'})
                    common_file=os.getenv('PASSWORD_BLOCKLIST_FILE','')
                    if common_file and password.casefold() in {line.strip().casefold() for line in Path(common_file).read_text().splitlines()}:
                        return self.reply(400,{'error':'Esta contraseña es demasiado común. Elige otra frase de contraseña.'})
                    token = str(data.get('token',''))
                    row = c.execute('SELECT t.user_id,u.email FROM reset_tokens t JOIN users u ON u.id=t.user_id WHERE token_hash=? AND expires>? AND u.active=1', (digest(token),int(time.time()))).fetchone()
                    if not row:
                        return self.reply(400, {'error':'El enlace no es válido o ha caducado.'})
                    c.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash(password),row['user_id']))
                    c.execute('DELETE FROM reset_tokens WHERE user_id=?', (row['user_id'],))
                    c.execute('DELETE FROM sessions WHERE user_id=?', (row['user_id'],))
                    c.execute('DELETE FROM attempts WHERE bucket IN (?,?)',('login-user:'+digest(row['email'].casefold()),'login-user:'+digest(c.execute('SELECT username FROM users WHERE id=?',(row['user_id'],)).fetchone()[0].casefold())))
                    audit(c, row['user_id'], 'password_reset')
                    c.commit()
                    dispatch_security_job(lambda:deliver_change_notice(row['email'],row['user_id']))
                    return self.reply(200, {'ok':True})
                user, token = self.session(c)
                if not user:
                    return self.reply(401, {'error':'Inicia sesión para continuar.'})
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''), user['csrf']):
                    return self.reply(403, {'error':'La sesión de seguridad no es válida. Recarga la página.'})
                if path=='/api/auth/policy':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede configurar la seguridad.'})
                    bounds={'lockout_seconds':(900,86400),'session_hours':(1,8),'remember_days':(1,30),'password_min':(6,128)}
                    try:
                        values={key:int(data[key]) for key in bounds}
                        if any(not low<=values[key]<=high for key,(low,high) in bounds.items()):raise ValueError()
                    except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'Revisa los límites de seguridad permitidos.'})
                    for key,value in values.items():c.execute('INSERT INTO auth_policy VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
                    audit(c,user['id'],'auth_policy_updated')
                    return self.reply(200,{'ok':True})
                if path=='/api/system/check':
                    # Solo consulta y compara; no descarga, instala ni modifica archivos.
                    try:
                        outcome=versioning.check()
                        # Se recuerda la versión posterior detectada para mostrarla en el centro de notificaciones hasta que se instale.
                        if outcome['update_available']:c.execute("INSERT INTO system_state VALUES ('available_update',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps({k:outcome['latest'][k] for k in ('version','date','summary')},ensure_ascii=False),))
                        else:c.execute("DELETE FROM system_state WHERE key='available_update'")
                        return self.reply(200,outcome)
                    except versioning.RegistryError as error:return self.reply(503,{'error':str(error)})
                if path.startswith('/api/mail/'):
                    if path=='/api/mail/test':
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede probar la conexión.'})
                        if data.get('kind')=='cpanel':
                            import cpanel
                            ok,steps,problem,kind=cpanel.diagnose(mail_pro.settings()['username'])
                            return self.reply(200,{'ok':ok,'steps':steps,'error':problem,'kind':kind})
                        try:steps=mail_pro.test_smtp() if data.get('kind')=='smtp' else mail_pro.test_imap()
                        except mail_pro.MailError as error:return self.reply(200,{'ok':False,'kind':error.kind,'error':str(error),'steps':getattr(error,'steps',[])})
                        return self.reply(200,{'ok':True,'steps':steps})
                    if not mail_allowed(user):return self.reply(403,{'error':'No tienes acceso al correo o todavía no está configurado en el servidor.'})
                    if path=='/api/mail/prefs':
                        # Preferencias de avisos del propio usuario: solo interruptores y volumen, con valores validados.
                        try:raw=json.loads(str(data.get('prefs') or '{}'))
                        except ValueError:raw=None
                        if not isinstance(raw,dict):return self.reply(400,{'error':'Preferencias no válidas.'})
                        clean={key:raw.get(key) is True for key in ('received','sent','error','mute','popups','desktop')}
                        try:clean['volume']=max(0.0,min(1.0,float(raw.get('volume',0.6))))
                        except (TypeError,ValueError):clean['volume']=0.6
                        c.execute("INSERT INTO system_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('mail_prefs:'+str(user['id']),json.dumps(clean)))
                        return self.reply(200,{'ok':True,'prefs':clean})
                    if path=='/api/mail/signature':
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede cambiar la firma.'})
                        if data.get('restore') is True or 'card' in data:
                            key='mail_signature_card:'+mail_pro.settings()['username']
                            if data.get('restore') is True:c.execute('DELETE FROM system_state WHERE key=?',(key,))
                            else:
                                try:raw=json.loads(str(data.get('card')))
                                except ValueError:return self.reply(400,{'error':'Firma no válida.'})
                                if not isinstance(raw,dict):return self.reply(400,{'error':'Firma no válida.'})
                                card=mail_pro.clean_signature(raw,mail_pro.settings()['username'])
                                if not card['name']:return self.reply(400,{'error':'Indica el nombre que aparece en la firma.','fields':{'name':'Completa este campo.'}})
                                c.execute("INSERT INTO system_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,json.dumps(card)))
                            audit(c,user['id'],'mail_signature_updated')
                            return self.reply(200,{'ok':True,'card':mail_signature_card(c)})
                        text=str(data.get('signature','')).strip()
                        if len(text)>2000:return self.reply(400,{'error':'La firma admite hasta 2000 caracteres.'})
                        c.execute("INSERT INTO system_state VALUES ('mail_signature',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(text,))
                        audit(c,user['id'],'mail_signature_updated')
                        return self.reply(200,{'ok':True})
                    client=None
                    try:
                        if path=='/api/mail/batch':
                            # Acciones sobre mensajes seleccionados: indicadores y movimientos reales en el servidor IMAP.
                            uids=[int(v) for v in str(data.get('uids','')).split(',') if v.strip().isdigit()]
                            if not uids or len(uids)>200:return self.reply(400,{'error':'Selecciona entre 1 y 200 mensajes.'})
                            action=str(data.get('action',''))
                            if action=='purge' and data.get('confirm') is not True:return self.reply(400,{'error':'Confirma la eliminación definitiva.'})
                            client=mail_pro.open_imap()
                            done=mail_pro.batch(client,str(data.get('folder','')),uids,action,str(data.get('target','')),str(data.get('uidvalidity','')) if str(data.get('uidvalidity','')).isdigit() else None)
                            audit(c,user['id'],'mail_'+action if action in ('archive','trash','restore','move','purge') else 'mail_flags')
                            return self.reply(200,{'ok':True,'done':done})
                        if path in ('/api/mail/flag','/api/mail/link'):
                            if not str(data.get('uid','')).isdigit():return self.reply(400,{'error':'Mensaje no válido.'})
                            client=mail_pro.open_imap();folder,_=mail_pro.resolve(client,str(data.get('folder','')));uid=int(data['uid'])
                            if path=='/api/mail/flag':
                                mail_pro.set_flag(client,folder['id'],uid,str(data.get('action','')))
                                return self.reply(200,{'ok':True})
                            if data.get('remove'):
                                c.execute('DELETE FROM mail_links WHERE id=?',(str(data.get('remove')),));audit(c,user['id'],'mail_unlinked')
                                return self.reply(200,{'ok':True})
                            order=c.execute('SELECT id,code FROM orders WHERE code=?',(str(data.get('order_code','')).strip().upper(),)).fetchone()
                            if not order:return self.reply(404,{'error':'No existe una orden con ese número.','fields':{'order_code':'Revisa el número de orden.'}})
                            row=mail_pro.summaries(client,[uid]) if mail_pro.search(client,folder['id']) is not None else []
                            if not row or not row[0]['message_id']:return self.reply(404,{'error':'El mensaje ya no está disponible.'})
                            outgoing=folder['role'] in ('sent','drafts');who=(row[0]['to'] if outgoing else row[0]['from']) or [{}]
                            c.execute('INSERT OR IGNORE INTO mail_links(message_id,folder,uid,order_id,subject,correspondent,direction,sent_at,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(row[0]['message_id'],folder['id'],uid,order['id'],row[0]['subject'],who[0].get('address',''),'out' if outgoing else 'in',row[0]['date'],user['id'],reception_now().isoformat(timespec='seconds')))
                            audit(c,user['id'],'mail_linked',order['id'])
                            return self.reply(200,{'ok':True,'order_id':order['id'],'code':order['code']})
                        if path in ('/api/mail/send','/api/mail/draft'):
                            draft=path.endswith('draft');key=str(data.get('request_key','')).strip()
                            if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):return self.reply(400,{'error':'Recarga el redactor e inténtalo de nuevo.'})
                            try:files=json.loads(str(data.get('attachments') or '[]'))
                            except ValueError:files=None
                            if not isinstance(files,list) or len(files)>10 or any(not isinstance(item,dict) for item in files):return self.reply(400,{'error':'Adjuntos no válidos.'})
                            config=mail_pro.settings()
                            message,recipients=mail_pro.build_message(config,{**{k:data.get(k,'') for k in ('to','cc','bcc','subject','body','in_reply_to','references')},'rich':data.get('rich') is True,'from_name':corporate.settings()['name'],'attachments':files,'draft':draft,'signature_pref':data.get('signature_pref')},(mail_signature_card(c) if data.get('signature') is True and not draft and mail_signature_card(c)['enabled'] else '') if 'signature' in data else mail_signature(c))
                            order=None;code=str(data.get('order_code','')).strip().upper()
                            if code:
                                order=c.execute('SELECT id,code FROM orders WHERE code=?',(code,)).fetchone()
                                if not order:return self.reply(404,{'error':'No existe una orden con ese número.','fields':{'order_code':'No existe una orden con ese número.'}})
                                # La vinculación se valida aquí, no en el navegador: orden en curso y de un cliente que recibe el mensaje.
                                owner=c.execute('SELECT o.status,lower(cl.email) email FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?',(order['id'],)).fetchone()
                                problem='La orden '+order['code']+' ya fue entregada: no se vincula a mensajes nuevos. Deja el campo Orden vacío.' if owner['status']=='entregado' else 'La orden '+order['code']+' no pertenece a ningún destinatario de este mensaje.' if not owner['email'] or owner['email'] not in {a.lower() for a in recipients} else ''
                                if problem and not draft:return self.reply(400,{'error':problem,'fields':{'order_code':problem}})
                            now=reception_now().isoformat(timespec='seconds')
                            if draft:
                                client=mail_pro.open_imap();folders=mail_pro.list_folders(client);target=mail_pro.by_role(folders,'drafts')
                                if not target or not mail_pro.store(client,target,message,'(\\Draft \\Seen)'):
                                    print('mail-draft no guardado',flush=True);return self.reply(502,{'error':'No se pudo guardar el borrador en el servidor de correo.'})
                                # El borrador que se estaba editando se reemplaza por la versión nueva: no quedan duplicados.
                                old=str(data.get('draft_uid',''))
                                if old.isdigit() and str(data.get('draft_folder',''))==target:mail_pro.remove_draft(client,target,int(old))
                                audit(c,user['id'],'mail_draft_saved')
                                return self.reply(201,{'ok':True,'draft':True})
                            previous=c.execute('SELECT status FROM mail_outbox WHERE request_key=?',(key,)).fetchone()
                            if previous and previous['status']=='sent':return self.reply(200,{'ok':True,'duplicate':True})
                            if previous and previous['status']=='sending':return self.reply(409,{'error':'Este mensaje ya se está enviando.'})
                            if limited(c,'mail-send:'+str(user['id']),limit=40,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de envíos por hora. Inténtalo más tarde.'})
                            c.execute("INSERT INTO mail_outbox(request_key,user_id,status,message_id,created_at,updated_at) VALUES (?,?,'sending',?,?,?) ON CONFLICT(request_key) DO UPDATE SET status='sending',updated_at=excluded.updated_at",(key,user['id'],message['Message-ID'],now,now))
                            c.commit()
                            try:mail_pro.deliver(config,message,recipients)
                            except mail_pro.MailError as error:
                                c.execute("UPDATE mail_outbox SET status='failed',updated_at=? WHERE request_key=?",(now,key));c.commit()
                                return self.reply(400 if error.kind in ('configuracion','destinatario') else 502,{'error':'No se envió el mensaje. '+str(error),'kind':error.kind,'fields':{'to':str(error)} if error.kind=='destinatario' else None})
                            # Aceptado por el servidor SMTP: recién ahora se considera enviado.
                            c.execute("UPDATE mail_outbox SET status='sent',updated_at=? WHERE request_key=?",(now,key))
                            if order:c.execute('INSERT OR IGNORE INTO mail_links(message_id,folder,uid,order_id,subject,correspondent,direction,sent_at,created_by,created_at) VALUES (?,?,0,?,?,?,?,?,?,?)',(message['Message-ID'],'',order['id'],str(message['Subject']),recipients[0],'out',now,user['id'],now))
                            audit(c,user['id'],'mail_sent',order['id'] if order else None)
                            try:
                                # Contactos frecuentes: se recuerdan los últimos destinatarios de este usuario (nombre del cliente si existe).
                                saved=c.execute('SELECT value FROM system_state WHERE key=?',('mail_recent:'+str(user['id']),)).fetchone();recent=json.loads(saved['value']) if saved else []
                                for address in recipients:
                                    known=c.execute("SELECT id,name,trade_name FROM clients WHERE email!='' AND lower(email)=lower(?) ORDER BY id LIMIT 1",(address,)).fetchone()
                                    recent=[item for item in recent if item.get('email','').lower()!=address.lower()]
                                    recent.insert(0,{'id':known['id'] if known else None,'name':known['name'] if known else address,'email':address,'trade_name':(known['trade_name'] or '') if known else ''})
                                c.execute("INSERT INTO system_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('mail_recent:'+str(user['id']),json.dumps(recent[:12])))
                            except Exception:pass
                            c.commit()
                            saved=False
                            try:
                                client=mail_pro.open_imap();folders=mail_pro.list_folders(client);sent=mail_pro.by_role(folders,'sent')
                                saved=bool(sent and mail_pro.store(client,sent,message,'(\\Seen)'))
                                old=str(data.get('draft_uid',''));drafts=mail_pro.by_role(folders,'drafts')
                                if old.isdigit() and drafts and str(data.get('draft_folder',''))==drafts:mail_pro.remove_draft(client,drafts,int(old))  # Borrador ya enviado.
                                source=str(data.get('reply_folder',''));uid=str(data.get('reply_uid',''))
                                if source and uid.isdigit() and any(f['id']==source for f in folders):
                                    client.select(mail_pro.quoted(source),readonly=False);client.uid('STORE',uid,'+FLAGS','(\\Answered)')
                            except Exception:saved=False
                            return self.reply(201,{'ok':True,'saved_in_sent':saved,'linked':order['code'] if order else ''})
                        return self.reply(404,{'error':'El servidor no reconoce esta operación de correo. Si la aplicación se actualizó hace poco, recarga la página; si continúa, hay que reiniciar el servicio.'})
                    except mail_pro.MailError as error:
                        return self.reply(400 if error.kind=='configuracion' else 502,{'error':str(error),'kind':error.kind})
                    finally:
                        if client is not None:mail_pro.close_imap(client)
                if path=='/api/notifications/read':
                    keys=None if data.get('all') is True else [key for key in str(data.get('keys','')).split(',') if key][:60]
                    notifications.mark(c,user,keys,reception_now())
                    return self.reply(200,notifications.build(c,user,reception_now(),mail_allowed(user)))
                if path=='/api/users/approval':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede revisar solicitudes.'})
                    action=str(data.get('action',''));role=str(data.get('role','tecnico'));target=str(data.get('id',''))
                    row=c.execute("SELECT id,approval FROM users WHERE id=? AND approval IN ('pending','rejected')",(target,)).fetchone() if target.isdigit() else None
                    if not row or action not in ('approve','reject') or role not in ('administrador','tecnico') or (action=='reject' and row['approval']!='pending'):return self.reply(400,{'error':'Solicitud no disponible.'})
                    if action=='approve':
                        c.execute("UPDATE users SET active=1,approval='approved',role=?,reviewed_by=?,reviewed_at=? WHERE id=?",(role,user['id'],int(time.time()),row['id']));appointments.ensure_staff_hours(c,row['id'])
                    else:c.execute("UPDATE users SET active=0,approval='rejected',reviewed_by=?,reviewed_at=? WHERE id=?",(user['id'],int(time.time()),row['id']))
                    audit(c,user['id'],'account_approved' if action=='approve' else 'account_rejected',row['id'])
                    return self.reply(200,{'ok':True})
                if path=='/api/sessions/revoke-others':
                    removed=c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user['id'],digest(token))).rowcount
                    audit(c,user['id'],'other_sessions_revoked')
                    return self.reply(200,{'ok':True,'closed':max(0,removed)})
                if path=='/api/account/password':
                    if limited(c,'password-change:'+str(user['id']),limit=6,window=900):return self.reply(429,{'error':'Demasiados intentos. Inténtalo más tarde.'})
                    current=str(data.get('current',''));password=str(data.get('password',''));minimum=auth_policy(c)['password_min']
                    stored=c.execute('SELECT password_hash,email FROM users WHERE id=?',(user['id'],)).fetchone()
                    if not password_ok(current,stored['password_hash']):return self.reply(400,{'error':'Revisa los campos señalados.','fields':{'current':'La contraseña actual no es correcta.'}})
                    if not minimum<=len(password)<=256:return self.reply(400,{'error':'Revisa los campos señalados.','fields':{'password':f'Usa una contraseña de {minimum} a 256 caracteres.'}})
                    if password!=str(data.get('repeat','')):return self.reply(400,{'error':'Revisa los campos señalados.','fields':{'repeat':'Las contraseñas no coinciden.'}})
                    if password==current:return self.reply(400,{'error':'Revisa los campos señalados.','fields':{'password':'Elige una contraseña distinta de la actual.'}})
                    common_file=os.getenv('PASSWORD_BLOCKLIST_FILE','')
                    if common_file and password.casefold() in {line.strip().casefold() for line in Path(common_file).read_text().splitlines()}:return self.reply(400,{'error':'Revisa los campos señalados.','fields':{'password':'Esta contraseña es demasiado común.'}})
                    c.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash(password),user['id']))
                    # La sesión actual se conserva; las demás quedan invalidadas en el servidor.
                    c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user['id'],digest(token)));c.execute('DELETE FROM reset_tokens WHERE user_id=?',(user['id'],))
                    c.execute("DELETE FROM attempts WHERE bucket=?",('password-change:'+str(user['id']),))
                    audit(c,user['id'],'password_changed');c.commit()
                    dispatch_security_job(lambda:deliver_change_notice(stored['email'],user['id']))
                    return self.reply(200,{'ok':True})
                if path=='/api/users/manage':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede gestionar cuentas.'})
                    target=str(data.get('id',''));action=str(data.get('action',''));role=str(data.get('role',''))
                    row=c.execute("SELECT id,role,active FROM users WHERE id=? AND approval='approved'",(target,)).fetchone() if target.isdigit() else None
                    if not row or action not in ('activate','deactivate','role') or (action=='role' and role not in ('administrador','tecnico')):return self.reply(400,{'error':'Operación no disponible.'})
                    if row['id']==user['id']:return self.reply(400,{'error':'No puedes cambiar tu propia cuenta desde aquí.'})
                    admins=c.execute("SELECT COUNT(*) FROM users WHERE role='administrador' AND active=1 AND approval='approved'").fetchone()[0]
                    if row['role']=='administrador' and row['active'] and admins<=1 and (action=='deactivate' or (action=='role' and role!='administrador')):return self.reply(400,{'error':'Debe quedar al menos un administrador activo.'})
                    if action=='role':c.execute('UPDATE users SET role=? WHERE id=?',(role,row['id']))
                    else:c.execute('UPDATE users SET active=? WHERE id=?',(1 if action=='activate' else 0,row['id']))
                    # Un cambio de rol o una desactivación cierra las sesiones abiertas de esa cuenta.
                    if action!='activate':c.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
                    audit(c,user['id'],'account_updated',row['id'])
                    return self.reply(200,{'ok':True})
                if path=='/api/sessions/revoke':
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],));audit(c,user['id'],'sessions_revoked')
                    return self.reply(200,{'ok':True,'message':'Se cerraron las sesiones activas.'},cookie=self.cookie('',0))
                if path=='/api/appointments/new':
                    # Cita registrada por el personal: mismas validaciones y disponibilidad que la reserva en línea.
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    status,payload=appointments.create(c,dict(data,privacy_consent=True,communications_consent=data.get('communications_consent') is True),user)
                    if status==201:
                        payload.pop('manage_token',None);audit(c,user['id'],'appointment_created',payload['id'])
                        payload['mail']=appointment_mail.send(c,payload['id'],appointment_mail.kind_for(payload['status']))
                        if str(data.get('maintenance_id','')).isdigit():payload['maintenance_linked']=maintenance.link_appointment(c,int(data['maintenance_id']),payload['id'],user,reception_now())
                    return self.reply(status,payload)
                appointment_route=re.fullmatch(r'/api/appointments/([0-9]+)',path)
                if path=='/api/appointments/config':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede configurar la agenda.'})
                    status,payload=appointments.update_settings(c,data)
                    if status==200:audit(c,user['id'],'appointment_settings_updated')
                    return self.reply(status,payload)
                if appointment_route:
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    row=c.execute('SELECT * FROM appointments WHERE deleted_at IS NULL AND id=?',(int(appointment_route[1]),)).fetchone()
                    if not row:return self.reply(404,{'error':'Cita no disponible.'})
                    action=data.get('action');now=appointments.stamp(appointments.now())
                    if action=='resend_mail':
                        # Reintento expreso del último aviso que corresponde al estado actual de la cita.
                        kind=appointment_mail.kind_for(row['status'])
                        if not kind:return self.reply(409,{'error':'Esta cita no tiene un aviso pendiente para su estado actual.'})
                        if limited(c,'appointment-mail:'+str(user['id']),limit=30,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de reenvíos por hora.'})
                        return self.reply(200,{'ok':True,'mail':appointment_mail.send(c,row['id'],kind,force=True)})
                    if action=='edit':
                        status,payload=appointments.edit(c,row,data,user)
                    elif action=='delete':
                        # Eliminar es una decisión de administración; la cita se conserva en la base con su auditoría.
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede eliminar citas.'})
                        payload=appointments.remove(c,row,user,data.get('reason'));status=200
                    elif action=='reschedule':
                        try:start=appointments.parse_start(str(data.get('starts_at','')))
                        except ValueError as error:return self.reply(400,{'error':str(error)})
                        result=appointments.reschedule(c,row,start,user);status=200 if result.get('ok') else 409;payload=result
                        if status==200:payload['mail']=appointment_mail.send(c,row['id'],'rescheduled')
                    elif action in ('confirmada','presente','completada','no_asistio','cancelada'):
                        if action not in appointments.STATUSES:return self.reply(400,{'error':'Estado de cita inválido.'})
                        if row['status'] in ('cancelada','completada','no_asistio') and action not in ('confirmada',):return self.reply(409,{'error':'La cita ya está cerrada.'})
                        if action==row['status']:return self.reply(200,{'ok':True})
                        # Al confirmar una solicitud se comprueba otra vez que el espacio siga libre en el servidor.
                        if action=='confirmada' and row['status'] in ('solicitada','cancelada','no_asistio') and not appointments.technicians(c,appointments.datetime.fromisoformat(row['starts_at']),row['duration_minutes'],exclude=row['id']):return self.reply(409,{'error':'Ese espacio ya no está disponible. Reprograma la cita.'})
                        c.execute('UPDATE appointments SET status=?,updated_at=? WHERE id=?',(action,now,row['id']))
                        # El cliente recibe el aviso solo cuando la cita queda efectivamente confirmada o cancelada.
                        if action=='confirmada' and row['status']=='solicitada':appointments.queue_notice(c,row,'confirmation')
                        if action=='cancelada':appointments.queue_notice(c,row,'cancelled')
                        maintenance.appointment_changed(c,row['id'],action,reception_now())
                        if action=='confirmada' and row['status']=='solicitada':payload_mail=appointment_mail.send(c,row['id'],'confirmation')
                        elif action=='cancelada':payload_mail=appointment_mail.send(c,row['id'],'cancelled')
                        c.execute('INSERT INTO appointment_events(appointment_id,actor_id,event,old_start,new_start,old_status,new_status,created_at) VALUES (?,?,?,?,?,?,?,?)',(row['id'],user['id'],'status',row['starts_at'],row['starts_at'],row['status'],action,now));status=200;payload={'ok':True}
                    else:return self.reply(400,{'error':'Acción de cita inválida.'})
                    if status==200:audit(c,user['id'],'appointment_'+str(action),row['id'])
                    return self.reply(status,payload)
                adi_manage=re.fullmatch(r'/api/adi/conversations/([0-9]+)',path)
                if adi_manage:
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede usar la asistente administrativa.'})
                    row=c.execute('SELECT id FROM adi_admin_conversations WHERE id=? AND user_id=?',(int(adi_manage[1]),user['id'])).fetchone()
                    if not row:return self.reply(404,{'error':'Conversación no disponible.'})
                    if data.get('action')=='delete':
                        c.execute('DELETE FROM adi_admin_messages WHERE conversation_id=?',(row['id'],));c.execute('DELETE FROM adi_admin_conversations WHERE id=?',(row['id'],))
                        audit(c,user['id'],'adi_conversation_deleted')
                        return self.reply(200,{'ok':True})
                    title=re.sub(r'\s+',' ',str(data.get('title',''))).strip()
                    if data.get('action')!='rename' or not title or len(title)>80:return self.reply(400,{'error':'Escribe un nombre de hasta 80 caracteres.'})
                    c.execute('UPDATE adi_admin_conversations SET title=? WHERE id=?',(title,row['id']))
                    return self.reply(200,{'ok':True,'title':title})
                if path == '/api/adi/admin':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede usar la asistente administrativa.'})
                    prompt=str(data.get('message','')).strip()
                    if not prompt or len(prompt)>2000:return self.reply(400,{'error':'Escribe una consulta de hasta 2000 caracteres.'})
                    result=adi.admin_reply(c,prompt,reception_now());answer=result['answer']
                    c.execute('INSERT INTO adi_actions(user_id,action,created_at,details) VALUES (?,?,?,?)',(user['id'],'admin_query',appointments.stamp(appointments.now()),prompt[:500]))
                    stamp=reception_now().isoformat(timespec='seconds');chosen=str(data.get('conversation_id',''))
                    conversation=c.execute('SELECT id,title FROM adi_admin_conversations WHERE id=? AND user_id=?',(chosen,user['id'])).fetchone() if chosen.isdigit() else None
                    if chosen and not conversation:return self.reply(404,{'error':'Conversación no disponible.'})
                    if not conversation:
                        title=re.sub(r'\s+',' ',prompt)[:60]
                        conversation={'id':c.execute('INSERT INTO adi_admin_conversations(user_id,title,created_at,updated_at) VALUES (?,?,?,?)',(user['id'],title,stamp,stamp)).lastrowid,'title':title}
                    c.execute("INSERT INTO adi_admin_messages(conversation_id,role,content,created_at) VALUES (?,'user',?,?)",(conversation['id'],prompt,stamp))
                    c.execute("INSERT INTO adi_admin_messages(conversation_id,role,content,links,created_at) VALUES (?,'adi',?,?,?)",(conversation['id'],answer,json.dumps(result.get('links',[]),ensure_ascii=False),stamp))
                    c.execute('UPDATE adi_admin_conversations SET updated_at=? WHERE id=?',(stamp,conversation['id']))
                    return self.reply(200,{'answer':answer,'links':result.get('links',[]),'source':result.get('source','datos'),'live':adi.snapshot(c,reception_now()),'ai_enabled':bool(os.getenv('OPENAI_API_KEY')),'conversation':{'id':conversation['id'],'title':conversation['title']},'created_at':stamp})
                live_action=re.fullmatch(r'/api/adi/live/([0-9]+)',path)
                if live_action:
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    conv=c.execute('SELECT * FROM adi_conversations WHERE id=?',(int(live_action[1]),)).fetchone()
                    if not conv:return self.reply(404,{'error':'Conversación no disponible.'})
                    action=data.get('action');now=appointments.stamp(appointments.now())
                    if action=='reply':
                        content=str(data.get('message','')).strip()
                        if not content or len(content)>3000:return self.reply(400,{'error':'Escribe una respuesta de hasta 3000 caracteres.'})
                        c.execute("INSERT INTO adi_messages(conversation_id,author,author_id,content,created_at) VALUES (?,'operator',?,?,?)",(conv['id'],user['id'],content,now));c.execute("UPDATE adi_conversations SET mode='human',assigned_to=?,updated_at=? WHERE id=?",(user['id'],now,conv['id']))
                    elif action in ('takeover','resume','close'):
                        mode={'takeover':'human','resume':'adi','close':'closed'}[action];c.execute('UPDATE adi_conversations SET mode=?,assigned_to=?,updated_at=? WHERE id=?',(mode,user['id'] if mode=='human' else None,now,conv['id']))
                        c.execute('INSERT INTO adi_actions(conversation_id,user_id,action,created_at) VALUES (?,?,?,?)',(conv['id'],user['id'],'conversation_'+action,now))
                    else:return self.reply(400,{'error':'Acción de conversación inválida.'})
                    audit(c,user['id'],'adi_conversation_'+action,conv['id']);return self.reply(200,{'ok':True})
                if path == '/api/logout':
                    c.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))
                    audit(c, user['id'], 'logout')
                    return self.reply(200, {'ok':True}, cookie=self.cookie('',0))
                maintenance_route=re.fullmatch(r'/api/maintenance/([0-9]+)',path)
                if maintenance_route:
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede modificar la agenda.'})
                    status,payload=maintenance.update(c,int(maintenance_route[1]),data,user,reception_now())
                    if status==200:audit(c,user['id'],'maintenance_updated',int(maintenance_route[1]))
                    return self.reply(status,payload)
                if path in ('/api/clients/import/preview','/api/clients/import/commit'):
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede importar clientes.'})
                    try:
                        raw=base64.b64decode(str(data.get('content','')),validate=True);filename=str(data.get('filename',''))[:200]
                        if path.endswith('preview'):
                            return self.reply(200,client_import.summary(client_import.analyze(c,raw,filename)))
                        merge=[value for value in str(data.get('merge','')).split(',') if value.strip().isdigit()]
                        result=client_import.commit(c,raw,filename,str(data.get('sha256','')),merge,user['id'],reception_now().isoformat(timespec='seconds'),make_backup)
                    except (client_import.ImportError_,ValueError) as error:
                        c.rollback()
                        return self.reply(400,{'error':str(error) if isinstance(error,client_import.ImportError_) else 'El archivo no se pudo leer.'})
                    audit(c,user['id'],'clients_imported',result['batch'])
                    return self.reply(201,result)
                if path == '/api/client-registry':
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    status,payload=client_registry.save(c,data,user)
                    if status in (200,201):audit(c,user['id'],'client_registry_saved',payload['id'])
                    return self.reply(status,payload)
                photo_route=re.fullmatch(r'/api/orders/([0-9]+)/photos',path)
                if photo_route:
                    oid=int(photo_route[1])
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if not c.execute('SELECT 1 FROM orders WHERE id=?',(oid,)).fetchone():return self.reply(404,{'error':'Orden no disponible.'})
                    action=str(data.get('action','add'))
                    if action in ('delete','main'):
                        if not str(data.get('photo_id','')).isdigit():return self.reply(400,{'error':'Foto no válida.'})
                        target=c.execute('SELECT id FROM order_photos WHERE id=? AND order_id=?',(int(data['photo_id']),oid)).fetchone()
                        if not target:return self.reply(404,{'error':'Foto no disponible.'})
                        if action=='delete':
                            if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede eliminar evidencia de una orden.'})
                            c.execute('DELETE FROM order_photos WHERE id=?',(target['id'],));audit(c,user['id'],'order_photo_deleted',oid)
                        else:
                            c.execute('UPDATE order_photos SET is_main=(id=?) WHERE order_id=?',(target['id'],oid));audit(c,user['id'],'order_photo_main',oid)
                        return self.reply(200,{'ok':True})
                    if c.execute('SELECT COUNT(*) FROM order_photos WHERE order_id=?',(oid,)).fetchone()[0]>=ORDER_PHOTO_LIMIT:return self.reply(409,{'error':'La orden ya tiene el máximo de '+str(ORDER_PHOTO_LIMIT)+' fotos.'})
                    try:content=base64.b64decode(str(data.get('data','')),validate=True)
                    except Exception:return self.reply(400,{'error':'La foto no se pudo leer.'})
                    # Solo JPEG real (cabecera y cierre), del tamaño que produce la reducción en el navegador.
                    if not (content[:3]==b'\xff\xd8\xff' and content[-2:]==b'\xff\xd9') or not 200<=len(content)<=600000:return self.reply(400,{'error':'Formato de foto no admitido o tamaño excesivo.'})
                    try:position=max(0,min(99,int(str(data.get('position','0')))))
                    except ValueError:position=0
                    main=data.get('main') is True
                    if main:c.execute('UPDATE order_photos SET is_main=0 WHERE order_id=?',(oid,))
                    pid=c.execute('INSERT INTO order_photos(order_id,position,is_main,mime,size,data,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',(oid,position,1 if main else 0,'image/jpeg',len(content),base64.b64encode(content).decode('ascii'),user['id'],reception_now().isoformat(timespec='seconds'))).lastrowid
                    audit(c,user['id'],'order_photo_added',oid)
                    return self.reply(201,{'ok':True,'id':pid})
                follow_route=re.fullmatch(r'/api/orders/([0-9]+)/follow-up',path)
                if follow_route:
                    oid=int(follow_route[1]);comment=str(data.get('comment','')).strip()
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if not c.execute('SELECT 1 FROM orders WHERE id=?',(oid,)).fetchone():return self.reply(404,{'error':'Orden no disponible.'})
                    if not comment or len(comment)>2000:return self.reply(400,{'error':'Indica un comentario de hasta 2000 caracteres.'})
                    now=reception_now();order_workspace.event(c,oid,user['id'],now,'follow_up',comment)
                    c.execute('UPDATE orders SET updated_at=?,revision=revision+1 WHERE id=?',(now.isoformat(timespec='microseconds'),oid))
                    audit(c,user['id'],'order_follow_up',oid)
                    return self.reply(201,{'ok':True})
                workspace_route=re.fullmatch(r'/api/orders/([0-9]+)/workspace',path)
                if workspace_route:
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede editar órdenes.'})
                    status,payload=order_workspace.save(c,int(workspace_route[1]),data,user,reception_now())
                    if status==200:audit(c,user['id'],'order_workspace_updated',int(workspace_route[1]))
                    return self.reply(status,payload)
                if path == '/api/conditions':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede publicar condiciones.'})
                    tid,errors=service_terms.publish(c,data,user,reception_now())
                    if errors:return self.reply(400,{'error':'Revisa los datos de publicación.','fields':errors})
                    audit(c,user['id'],'service_terms_published')
                    return self.reply(201,{'ok':True,'id':tid})
                if path in ('/api/clients', '/api/devices', '/api/order-status', '/api/settings'):
                    if user['role'] != 'administrador':
                        return self.reply(403, {'error':'Solo administración puede realizar esta operación.'})
                    if path == '/api/settings':
                        name, email = str(data.get('name','')).strip(), str(data.get('email','')).strip()
                        if not name or len(name)>150 or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
                            return self.reply(400, {'error':'Completa un nombre y correo válidos.'})
                        if c.execute('SELECT 1 FROM users WHERE email=? AND id!=?', (email,user['id'])).fetchone():
                            return self.reply(400, {'error':'Ese correo no está disponible.'})
                        c.execute('UPDATE users SET name=?,email=? WHERE id=?', (name,email,user['id']))
                        audit(c,user['id'],'profile_updated',user['id'])
                    elif path == '/api/order-status':
                        status = str(data.get('status',''))
                        oid = str(data.get('id',''))
                        if not c.execute('SELECT 1 FROM statuses WHERE code=?',(status,)).fetchone() or not c.execute('SELECT 1 FROM orders WHERE id=?',(oid,)).fetchone():
                            return self.reply(400, {'error':'Orden o estado inválido.'})
                        comment=str(data.get('comment','')).strip()
                        if len(comment)>2000:return self.reply(400,{'error':'El comentario admite hasta 2000 caracteres.'})
                        now=reception_now()
                        old=c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()[0]
                        c.execute('UPDATE orders SET status=?,updated_at=?,revision=revision+1 WHERE id=?', (status,now.isoformat(timespec='microseconds'),oid))
                        planned=maintenance.transition(c,int(oid),old,status,now)
                        # La entrega crea también la cita futura del mantenimiento (pendiente de confirmación), sin pasos manuales.
                        if planned:
                            booked=appointments.create_for_maintenance(c,planned['id'],user)
                            if booked:planned['appointment']=booked;order_workspace.event(c,int(oid),user['id'],now,'maintenance','Cita de mantenimiento preventivo generada automáticamente ('+booked['public_code']+').')
                        # Sin cambio real ni comentario no hay nada que auditar; con cambio, el registro nombra la transición.
                        if old!=status or comment:order_workspace.event(c,int(oid),user['id'],now,'status' if old!=status else 'follow_up',comment or order_workspace.transition_comment(old,status))
                        audit(c,user['id'],'order_status_updated',int(oid))
                        # La previsión de mantenimiento creada por la entrega viaja en la respuesta para avisar al instante.
                        if planned:return self.reply(200,{'ok':True,'maintenance':planned})
                    else:
                        table = 'clients' if path == '/api/clients' else 'devices'
                        keys = ('name','phone','email') if table == 'clients' else ('client_id','type','brand','model','serial')
                        values = [str(data.get(k,'')).strip() for k in keys]
                        if any(len(v)>(254 if keys[i]=='email' else 30 if keys[i]=='phone' else 150) for i,v in enumerate(values)):
                            return self.reply(400, {'error':'Los campos admiten hasta 150 caracteres.'})
                        if table == 'clients':
                            if values[1] and not valid_ecuador_phone(values[1]):
                                return self.reply(400,{'error':'Ingresa un teléfono ecuatoriano válido.','fields':{'phone':'Usa móvil 09…, fijo con código de área o +593….'}})
                            if not values[0] or (values[2] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values[2])):
                                return self.reply(400, {'error':'Indica un nombre y un correo válido si corresponde.'})
                        elif values[1] not in DEVICE_TYPES or not c.execute('SELECT 1 FROM clients WHERE id=?',(values[0],)).fetchone():
                            return self.reply(400, {'error':'Selecciona un cliente y tipo de equipo válidos.'})
                        if table == 'devices':
                            if values[4] and not re.fullmatch(r'[A-Za-z0-9-]+',values[4]):return self.reply(400,{'error':'La serie admite letras, números y guiones.','fields':{'serial':'Utiliza letras, números y guiones.'}})
                            category = values[1]
                            keys = (*keys, 'category', 'kind')
                            values[1] = legacy_type(category)
                            values.extend((stored_category(category), category))
                            remember_brand(c,values[2],category)
                        entity_id = str(data.get('id',''))
                        if entity_id:
                            if not c.execute('SELECT 1 FROM '+table+' WHERE id=?',(entity_id,)).fetchone():
                                return self.reply(404, {'error':'Registro no disponible.'})
                            c.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in keys)+' WHERE id=?',(*values,entity_id))
                        else:
                            entity_id = c.execute('INSERT INTO '+table+'('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',values).lastrowid
                        audit(c,user['id'],table+'_saved',int(entity_id))
                    return self.reply(200, {'ok':True})
                if path in ('/api/adi/write','/api/adi/settings'):
                    import adi_ai
                    if path=='/api/adi/settings':
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede cambiar esta configuración.'})
                        if data.get('writing') not in (True,False):return self.reply(400,{'error':'Valor inválido.'})
                        c.execute("INSERT INTO system_state(key,value) VALUES ('adi_writing',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('on' if data['writing'] else 'off',))
                        audit(c,user['id'],'adi_writing_'+('enabled' if data['writing'] else 'disabled'))
                        return self.reply(200,{'ok':True,'writing':adi_ai.status(c)})
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if not adi_ai.enabled(c):return self.reply(403,{'error':'La redacción con Adi está desactivada en Configuración.'})
                    if not adi_ai.provider():return self.reply(503,{'error':'Adi todavía no tiene un proveedor de IA configurado en el servidor.','kind':'configuracion'})
                    if limited(c,'adi-write:'+str(user['id']),limit=60,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de mejoras por hora. Intenta más tarde.'})
                    mode=str(data.get('mode',''));field=str(data.get('field',''))[:40]
                    try:result=adi_ai.improve(data.get('text',''),mode,field)
                    except adi_ai.AdiError as error:
                        print('adi-write',error.kind,flush=True)
                        return self.reply(error.status,{'error':str(error),'kind':error.kind})
                    # Registro de uso: quién, qué tipo de mejora y consumo. No se guarda el texto.
                    c.execute('INSERT INTO adi_actions(user_id,action,created_at,details) VALUES (?,?,?,?)',(user['id'],'writing_improve',reception_now().isoformat(timespec='seconds'),json.dumps({'mode':mode,'field':field,'model':result['model'],'tokens_in':result['tokens_in'],'tokens_out':result['tokens_out'],'missing':len(result['missing'])})))
                    return self.reply(200,{'suggestion':result['suggestion'],'missing':result['missing'],'changed':result['changed']})
                receipt_route=re.fullmatch(r'/api/orders/([0-9]+)/receipt-mail',path)
                if receipt_route or path=='/api/receipt-mail/settings':
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if not receipt_route:
                        if user['role']!='administrador' or data.get('auto') not in (True,False):return self.reply(403 if user['role']!='administrador' else 400,{'error':'No se pudo cambiar la configuración.'})
                        c.execute("INSERT INTO system_state(key,value) VALUES ('receipt_mail_auto',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('on' if data['auto'] else 'off',))
                        audit(c,user['id'],'receipt_mail_auto_'+('on' if data['auto'] else 'off'));return self.reply(200,{'ok':True,'auto':data['auto']})
                    mode=str(data.get('mode',''))
                    if mode not in ('auto','manual'):return self.reply(400,{'error':'Modo de envío inválido.'})
                    if mode=='manual' and limited(c,'receipt-mail:'+str(user['id']),limit=30,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de reenvíos por hora.'})
                    status,payload=send_receipt_mail(c,int(receipt_route[1]),user,mode)
                    if status==200:payload['receipt_mail']=receipt_mail_status(c,int(receipt_route[1]))
                    return self.reply(status,payload)
                tracking_route=re.fullmatch(r'/api/orders/([0-9]+)/tracking',path)
                if tracking_route:
                    import order_tracking
                    oid=int(tracking_route[1]);action=str(data.get('action',''))
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if action not in ('create','revoke'):return self.reply(400,{'error':'Acción inválida.'})
                    if not c.execute('SELECT 1 FROM orders WHERE id=?',(oid,)).fetchone():return self.reply(404,{'error':'Orden no disponible.'})
                    if action=='create':order_tracking.create(c,oid,user['id'],reception_now());audit(c,user['id'],'order_tracking_link_created',oid)
                    else:order_tracking.revoke(c,oid,user['id'],reception_now());audit(c,user['id'],'order_tracking_link_revoked',oid)
                    return self.reply(200,{'ok':True,'tracking':order_tracking.active(c,oid)})
                print_match=re.fullmatch(r'/api/orders/([0-9]+)/thermal-print',path)
                if print_match:
                    oid=int(print_match[1]);key=str(data.get('request_key',''))
                    if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',key):return self.reply(400,{'error':'Identificador de impresión inválido.'})
                    previous=c.execute('SELECT * FROM thermal_print_jobs WHERE request_key=?',(key,)).fetchone()
                    if previous:
                        if previous['actor_id']!=user['id'] or previous['order_id']!=oid:return self.reply(409,{'error':'Solicitud de impresión no disponible.'})
                        if previous['state']=='submitted':return self.reply(200,{'ok':True,'duplicate':True,'message':'Este trabajo ya fue enviado a la cola.'})
                        return self.reply(409,{'error':'Comprueba la cola antes de volver a imprimir; este envío está pendiente o no pudo confirmarse.'})
                    config=thermal_printing.capability()
                    if not config.get('available'):return self.reply(503,{'error':'La cola Epson local no está disponible en este servidor. Descarga el PDF para imprimirlo desde el taller.'})
                    row=c.execute('SELECT o.*,COALESCE(NULLIF(d.kind,\'\'),d.category) type,d.brand,d.model,d.serial,c.name client,c.identification,c.document_type,c.phone,s.label status_label FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?',(oid,)).fetchone()
                    if not row:return self.reply(404,{'error':'Orden no disponible.'})
                    order=dict(row)
                    if row['reception_snapshot']:order.update(json.loads(row['reception_snapshot']))
                    service_terms.attach(c,order);technical_access.attach(c,order)
                    from thermal_pdf import render_thermal
                    import order_tracking
                    copy=str(data.get('copy') or 'cliente')
                    if copy not in ('cliente','taller','ambas'):return self.reply(400,{'error':'Copia inválida.'})
                    order['tracking_url']=order_tracking.active(c,oid)['url']
                    # Cada copia es un ticket de una página: «ambas» envía dos trabajos con corte propio.
                    pdfs=[render_thermal(order,one) for one in (('cliente','taller') if copy=='ambas' else (copy,))]
                    c.execute("INSERT INTO thermal_print_jobs(request_key,order_id,actor_id,state,created_at) VALUES (?,?,?,'pending',?)",(key,oid,user['id'],reception_now().isoformat()))
                    c.commit() # Reserva persistente antes de enviar: no reimprimir automáticamente si se pierde la respuesta.
                    try:
                        with tempfile.TemporaryDirectory(prefix='pcdoctor-ticket-') as folder:
                            references=[]
                            for number,pdf in enumerate(pdfs):
                                path_pdf=Path(folder)/('ticket-%d.pdf'%number);path_pdf.write_bytes(pdf)
                                references.append(str(thermal_printing.send(path_pdf,config['queue'],thermal_printing.inspect_pdf(path_pdf)) or ''))
                            reference=', '.join(filter(None,references)) or None
                        c.execute("UPDATE thermal_print_jobs SET state='submitted',spool_reference=? WHERE request_key=?",(reference,key))
                        audit(c,user['id'],'thermal_print_submitted',oid);c.commit()
                    except (OSError,ValueError,subprocess.SubprocessError):
                        c.execute("UPDATE thermal_print_jobs SET state='uncertain' WHERE request_key=?",(key,));audit(c,user['id'],'thermal_print_unconfirmed',oid);c.commit()
                        return self.reply(503,{'error':'No se pudo confirmar el envío a la Epson. Comprueba conexión y cola antes de volver a imprimir.'})
                    return self.reply(200,{'ok':True,'message':('Dos copias enviadas' if len(pdfs)==2 else 'Trabajo enviado')+' a la cola Epson. Verifica la salida física.'})
                consent_match=re.fullmatch(r'/api/orders/([0-9]+)/authorizations',path)
                if consent_match:
                    oid=int(consent_match[1]);order=c.execute('SELECT o.*,cl.name client FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?',(oid,)).fetchone()
                    if not order:return self.reply(404,{'error':'Orden no disponible.'})
                    key=str(data.get('request_key',''))
                    if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',key):return self.reply(400,{'error':'Identificador de solicitud inválido.'})
                    if c.execute('SELECT 1 FROM order_access_consents WHERE order_id=? AND request_key=?',(oid,key)).fetchone():return self.reply(200,{'ok':True})
                    revision=c.execute('SELECT COALESCE(MAX(id),0) FROM order_access_consents WHERE order_id=?',(oid,)).fetchone()[0]
                    if str(data.get('access_revision',''))!=str(revision):return self.reply(409,{'error':'La autorización cambió. Abre nuevamente el formulario.'})
                    access,errors=technical_access.validate(data)
                    if errors:return self.reply(400,{'error':'Revisa la autorización.','fields':errors})
                    now=reception_now()
                    if data.get('complete_terms') is True and not order['terms_acceptance_id']:
                        terms=service_terms.current(c,now)
                        if not terms or data.get('terms_document_id')!=terms['id'] or data.get('terms_accept') is not True:return self.reply(409,{'error':'Revisa y acepta las condiciones vigentes.'})
                        c.execute('UPDATE orders SET terms_document_id=?,terms_acceptance_id=?,terms_accepted_at=?,terms_mechanism=?,terms_acceptor=?,terms_actor_id=? WHERE id=?',(terms['id'],secrets.token_hex(16),now.isoformat(timespec='microseconds'),service_terms.MECHANISM,order['client'],user['id'],oid))
                        audit(c,user['id'],'service_terms_accepted_later',oid)
                    technical_access.record(c,oid,user,now,order['client'],access,key)
                    audit(c,user['id'],'technical_access_recorded',oid)
                    return self.reply(201,{'ok':True})
                if path == '/api/orders':
                    client_id=str(data.get('client_id',''))
                    selected=c.execute('SELECT * FROM clients WHERE id=?',(client_id,)).fetchone() if client_id.isdigit() else None
                    if not selected:return self.reply(400,{'error':'Selecciona un cliente registrado.','fields':{'client_id':'Busca y selecciona un cliente válido.'}})
                    if selected['needs_review']:return self.reply(409,{'error':'La ficha de este cliente está incompleta. Complétala antes de crear la orden.','fields':{'client_id':'Completa la ficha del cliente para continuar.'},'incomplete_client':selected['id']})
                    appointment_id=str(data.get('appointment_id',''));linked_appointment=None
                    if appointment_id:
                        if not appointment_id.isdigit():return self.reply(400,{'error':'La cita vinculada no es válida.'})
                        linked_appointment=c.execute('SELECT * FROM appointments WHERE deleted_at IS NULL AND id=?',(int(appointment_id),)).fetchone()
                        if not linked_appointment:return self.reply(404,{'error':'La cita vinculada ya no está disponible.'})
                        if linked_appointment['converted_order_id']:return self.reply(409,{'error':'Esta cita ya fue convertida en una orden.'})
                        if linked_appointment['client_id']!=selected['id']:return self.reply(409,{'error':'La cita no corresponde al cliente seleccionado.'})
                    personal=client_registry.profile(selected)
                    incoming=dict(data)
                    incoming.update({k:personal.get(k,'') for k in client_registry.PERSONAL})
                    incoming['client']=personal['name']
                    fields, errors = validate_order(incoming)
                    client_errors={k:v for k,v in errors.items() if k in client_registry.PERSONAL or k=='client'}
                    if client_errors:return self.reply(400,{'error':'Completa la ficha del cliente antes de recibir el equipo.','fields':{'client_id':'La ficha del cliente necesita identificación, contacto y ubicación válidos.'},'client_fields':client_errors})
                    if errors:
                        return self.reply(400, {'error':'Revisa los campos señalados.','fields':errors})
                    request_key = str(data.get('request_key','')) or None
                    if request_key:
                        previous = c.execute('SELECT id,code,created_by FROM orders WHERE request_key=?',(request_key,)).fetchone()
                        if previous:
                            if previous['created_by'] != user['id']:
                                return self.reply(409, {'error':'Identificador de envío no disponible. Reabre el formulario.'})
                            return self.reply(200, {'ok':True,'id':previous['id'],'code':previous['code']})
                    received=reception_now()
                    terms=service_terms.current(c,received)
                    # Sin condiciones publicadas la orden se registra sin aceptación (no se inventa ninguna). Solo bloquea si la instalación lo exige expresamente.
                    if not terms and terms_required():
                        return self.reply(503,{'error':'Publica las condiciones aprobadas y vigentes antes de registrar recepciones.','fields':{'terms_accept':'Esta instalación exige condiciones publicadas y todavía no hay ninguna vigente.'}})
                    if terms:
                        if str(data.get('terms_document_id',''))!=terms['id']:
                            return self.reply(409,{'error':'Las condiciones vigentes han cambiado. Revísalas y registra nuevamente la aceptación.','fields':{'terms_accept':'La versión debe revisarse nuevamente.'}})
                        if data.get('terms_accept') is not True:
                            return self.reply(400,{'error':'Registra la aceptación de las condiciones.','fields':{'terms_accept':'El cliente debe revisar y aceptar las condiciones antes de guardar.'}})
                    access,access_errors=technical_access.validate(data)
                    if access_errors:return self.reply(400,{'error':'Registra la decisión de acceso del cliente.','fields':access_errors})
                    client_id=selected['id']
                    tracking,tracking_errors=order_workspace.validate(c,dict(data,problem=fields['problem'],status='pendiente',assigned_to=str(data.get('assigned_to') or user['id']),internal_notes=data.get('additional_notes',''),findings=data.get('initial_diagnosis','')))
                    if tracking_errors:return self.reply(400,{'error':'Revisa los datos de recepción.','fields':tracking_errors})
                    import device_lookup
                    # Sin duplicados: si este cliente ya tiene registrado exactamente el mismo equipo (misma serie, tipo, marca, modelo y color), se reutiliza.
                    same=c.execute("SELECT id FROM devices WHERE client_id=? AND COALESCE(NULLIF(kind,''),category)=? AND COALESCE(brand,'')=? AND COALESCE(model,'')=? AND COALESCE(color,'')=? AND COALESCE(serial,'')!='' AND upper(replace(serial,' ',''))=? ORDER BY id LIMIT 1",
                        (client_id,fields['type'],fields['brand'],fields['model'],fields['color'],device_lookup.normalize(fields['serial']))).fetchone() if fields['serial'] else None
                    identified=bool(fields['brand'] or fields['model'])
                    # La identificación queda vinculada al equipo con quién la confirmó y cuándo; las órdenes anteriores no se tocan.
                    device_id = same['id'] if same else c.execute('INSERT INTO devices(client_id,type,category,kind,brand,model,serial,color,identity_source,identity_confirmed_by,identity_confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (client_id,legacy_type(fields['type']),stored_category(fields['type']),fields['type'],fields['brand'],fields['model'],fields['serial'],fields['color'],(device_lookup.source(data.get('identity_source')) or 'manual') if identified else '',user['id'] if identified else None,received.isoformat(timespec='seconds') if identified else '')).lastrowid
                    remember_brand(c,fields['brand'],fields['type'])
                    number_date = received.strftime('%Y%m%d')
                    c.execute('INSERT INTO daily_order_sequences(reception_date,value) VALUES (?,1) ON CONFLICT(reception_date) DO UPDATE SET value=value+1',(number_date,))
                    sequence = c.execute('SELECT value FROM daily_order_sequences WHERE reception_date=?',(number_date,)).fetchone()[0]
                    code = order_code(number_date,sequence)
                    oid = c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,accessories,physical_condition,technician_notes,code,request_key,received_at,number_date,daily_sequence) VALUES (?,'pendiente',?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id,fields['problem'],user['id'],int(received.timestamp()),fields['accessories'],fields['physical_condition'],fields['technician_notes'],code,request_key,received.isoformat(timespec='microseconds'),number_date,sequence)).lastrowid
                    c.execute('UPDATE orders SET qr_url=? WHERE id=?',(order_url(code),oid))
                    import order_tracking
                    order_tracking.create(c,oid,user['id'],received)
                    c.execute('UPDATE orders SET reception_snapshot=? WHERE id=?',(json.dumps(fields,ensure_ascii=False),oid))
                    if terms:
                        c.execute('UPDATE orders SET terms_document_id=?,terms_acceptance_id=?,terms_accepted_at=?,terms_mechanism=?,terms_acceptor=?,terms_actor_id=? WHERE id=?',
                                  (terms['id'],secrets.token_hex(16),received.isoformat(timespec='microseconds'),service_terms.MECHANISM,fields['client'],user['id'],oid))
                        audit(c,user['id'],'service_terms_accepted',oid)
                    technical_access.record(c,oid,user,received,fields['client'],access,request_key or secrets.token_hex(16))
                    audit(c,user['id'],'technical_access_recorded',oid)
                    c.execute('UPDATE orders SET assigned_to=?,priority=?,estimated_delivery=?,findings=?,internal_notes=?,updated_at=? WHERE id=?',(tracking['assigned_to'],tracking['priority'],tracking['estimated_delivery'],tracking['findings'],tracking['internal_notes'],received.isoformat(timespec='microseconds'),oid))
                    order_workspace.event(c,oid,user['id'],received,'created','Recepción registrada.')
                    if linked_appointment:
                        c.execute('UPDATE appointments SET converted_order_id=?,status=CASE WHEN status IN (\'confirmada\',\'reprogramada\',\'presente\') THEN \'completada\' ELSE status END,updated_at=? WHERE id=? AND converted_order_id IS NULL',(oid,received.isoformat(timespec='microseconds'),linked_appointment['id']))
                        if c.execute('SELECT changes()').fetchone()[0]!=1:return self.reply(409,{'error':'La cita ya fue convertida en otra orden.'})
                        c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,new_status,created_at,detail) VALUES (?,?,'converted','completada',?,?)",(linked_appointment['id'],user['id'],received.isoformat(timespec='microseconds'),'Orden '+code))
                    audit(c, user['id'], 'order_created', oid)
                    return self.reply(201, {'ok':True,'id':oid,'code':code})
            return self.reply(404, {'error':'Recurso no disponible.'})
        except (ValueError, json.JSONDecodeError):
            self.reply(400, {'error':'Solicitud inválida.'})
        except Exception:
            self.reply(500, {'error':'No se pudo completar la operación.'})


def main():
    load_env()
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['serve','create-admin','create-technician','migrate'])
    args = parser.parse_args()
    migrate()
    if args.command.startswith('create-'):
        role = 'administrador' if args.command == 'create-admin' else 'tecnico'
        name = input('Nombre: ').strip()
        username = input('Usuario: ').strip()
        email = input('Correo: ').strip()
        password = getpass.getpass('Contraseña (mínimo 6 caracteres): ')
        repeat = getpass.getpass('Repetir contraseña: ')
        if not name or not re.fullmatch(r'[a-zA-Z0-9_.-]{3,50}', username) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or not 6<=len(password)<=256 or password != repeat:
            raise SystemExit('Datos inválidos o contraseñas diferentes; no se creó la cuenta.')
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if role == 'administrador' and c.execute("SELECT 1 FROM users WHERE role='administrador'").fetchone():
                raise SystemExit('Ya existe un administrador. No se modificó ninguna cuenta.')
            uid = c.execute('INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',(username,email,name,password_hash(password),role,int(time.time()))).lastrowid
            appointments.ensure_staff_hours(c,uid)
            audit(c,uid,'account_created',uid)
        print('Cuenta creada. No hay registro público.')
    elif args.command == 'serve':
        port = int(os.getenv('PORT','8010'))
        host = os.getenv('BIND_HOST', '127.0.0.1')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise SystemExit('BIND_HOST debe ser una dirección IPv4 local.')
        if address.version != 4 or address.is_unspecified or not (address.is_loopback or address.is_private) or address.is_multicast or address.is_link_local:
            raise SystemExit('Esta evaluación solo admite una IPv4 privada o de loopback explícita.')
        origin = os.getenv('APP_URL', f'http://{host}:{port}').rstrip('/')
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http','https') or parsed.hostname != host or parsed.port != port or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise SystemExit(f'APP_URL debe corresponder a la dirección de acceso, por ejemplo http://{host}:{port}')
        os.environ['APP_URL'] = origin
        try:
            server = ThreadingHTTPServer((host,port), Handler)
        except OSError as error:
            raise SystemExit(f'No se pudo iniciar el servidor local: {error}. Ejecuta este comando en tu terminal de Omarchy.')
        print(f'ÓRDENES PRO: {origin}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\nServidor detenido.')
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
