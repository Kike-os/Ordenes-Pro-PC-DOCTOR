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
import order_drafts
import live_support
import reports
import order_search
import stay
import technical_access
import thermal_printing
import tempfile
import subprocess
import order_workspace
import equipment
import quotes
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
    # Turnstile si hay claves; si no, verificación propia y silenciosa (prueba de trabajo de un solo uso) salvo LOGIN_CAPTCHA=off.
    if os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY'):
        return 'turnstile' if bot_always() else ''
    return '' if os.getenv('LOGIN_CAPTCHA','on').strip().lower() in ('off','false','0','no') else 'local'


def captcha_always():
    # LOGIN_CAPTCHA=always exige la verificación en cada intento; por defecto solo se pide cuando hay fallos recientes.
    return os.getenv('LOGIN_CAPTCHA','on').strip().lower()=='always'


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
    body=('Estimado/a '+order['client']+':\n\nLe confirmamos que su equipo ha sido recibido correctamente en nuestro centro de servicio técnico PC-DOCTOR S.A.\n\n'
          'Adjuntamos el comprobante de recepción correspondiente a su orden de reparación N.º '+order['code']+'.\n\n'
          'En este documento podrá consultar la información registrada del equipo, el servicio solicitado y las condiciones de recepción.\n\n'
          'Gracias por confiar en nuestro servicio técnico.\n\nAtentamente,\n\nDepartamento de Servicio Técnico\nPC-DOCTOR S.A.\nwww.ecuadorpcdoctor.com')
    try:
        config=mail_pro.settings();card=mail_signature_card(c)
        message,recipients=mail_pro.build_message(config,{'to':email,'subject':'PC-DOCTOR S.A. | Confirmación de recepción — Orden N.º '+order['code'],'body':body,'from_name':corporate.settings()['name'],
            'attachments':[{'name':order['code']+'-COMPROBANTE-DE-RECEPCION.pdf','type':'application/pdf','data':base64.b64encode(pdf).decode()}]},card if card.get('enabled') else '')
        mail_pro.deliver(config,message,recipients)
    except mail_pro.MailError as error:
        print('receipt-mail',error.kind,flush=True);log('failed',str(error),email,sha)
        return 200,{'result':'failed','message':'La orden está guardada, pero el correo no se pudo enviar: '+str(error)}
    log('sent','El servidor de correo aceptó el mensaje.',email,sha)
    order_workspace.event(c,oid,user['id'],reception_now(),'follow_up','Comprobante de recepción enviado por correo a '+email+'.')
    audit(c,user['id'],'receipt_mail_sent',oid)
    return 200,{'result':'sent','recipient':email,'message':'Comprobante enviado a '+email+'. El servidor de correo aceptó el mensaje.'}


def authorization_mail_status(c,oid):
    row=c.execute('SELECT recipient,result,detail,created_at FROM order_authorization_mail WHERE order_id=? ORDER BY id DESC LIMIT 1',(oid,)).fetchone()
    return dict(row) if row else None


def send_authorization_mail(c,oid,user):
    """Avisa al correo administrativo del sistema de la autorización recién registrada y deja constancia del resultado.

    Un aviso por decisión registrada: si ya se envió el de esta decisión no se repite. «sent» significa que el servidor de
    correo aceptó el mensaje. Nunca interrumpe el registro de la orden.
    """
    order=order_document(c,oid)
    if not order:return None
    technical_access.attach(c,order);consent=order.get('access_revision') or 0
    if not consent:return None
    if c.execute("SELECT 1 FROM order_authorization_mail WHERE order_id=? AND consent_id=? AND result='sent'",(oid,consent)).fetchone():return {'result':'already'}
    now=reception_now()
    def log(result,detail='',recipient=''):
        c.execute('INSERT INTO order_authorization_mail(order_id,consent_id,recipient,result,detail,actor_id,created_at) VALUES (?,?,?,?,?,?,?)',(oid,consent,recipient,result,detail[:300],user['id'],now.isoformat(timespec='seconds')))
    try:ready=mail_pro.configured()
    except mail_pro.MailError:ready=False
    if not ready:
        log('not_configured');return {'result':'not_configured'}
    proof=order.get('access_authorization') or order.get('destructive_authorization');rows=technical_access.summary(order.get('access_authorization'),order.get('destructive_authorization'))
    device=' '.join(part for part in (DEVICE_TYPES.get(order.get('type'),order.get('type') or ''),order.get('brand') or '',order.get('model') or '') if part) or 'Equipo sin especificar'
    when=appointments.datetime.fromisoformat(proof['recorded_at']).astimezone(reception.ECUADOR_TZ).strftime('%d/%m/%Y %H:%M') if proof else now.strftime('%d/%m/%Y %H:%M')
    states={state for _,state,_ in rows};overall='Con operaciones NO AUTORIZADAS' if 'denied' in states else 'Autorizado' if states=={'authorized'} else 'Autorizado parcialmente (hay apartados pendientes)' if 'authorized' in states else 'Pendiente'
    body='\n'.join(['PC-DOCTOR S.A. — Autorización registrada','','Orden: '+order['code'],'Cliente: '+order['client'],'Equipo: '+device+(' · Serie '+order['serial'] if order.get('serial') else ''),'Estado: '+overall,'Fecha: '+when+' (Ecuador)','Registrada por: '+((proof or {}).get('operator') or user.get('name') or 'Personal del taller'),'']
        +[title+': '+technical_access.STATE_LABELS[state]+'\n  '+detail for title,state,detail in rows]
        +['','La decisión fue expresada por el cliente y registrada en pantalla por el personal en recepción; no es una firma del cliente.','','Consultar la autorización (requiere iniciar sesión en Órdenes Pro):',public_base_url().rstrip('/')+'/#orders?id='+str(oid)])
    try:
        config=mail_pro.settings();recipient=config['username']
        message,recipients=mail_pro.build_message(config,{'to':recipient,'subject':'PC-DOCTOR S.A. | Autorización registrada — Orden N.º '+order['code'],'body':body,'from_name':corporate.settings()['name']},'')
        mail_pro.deliver(config,message,recipients)
    except mail_pro.MailError as error:
        print('authorization-mail',error.kind,flush=True);log('failed',str(error));return {'result':'failed','message':str(error)}
    log('sent','El servidor de correo aceptó el mensaje.',recipient)
    order_workspace.event(c,oid,user['id'],now,'follow_up','Aviso de autorización enviado al correo administrativo.')
    return {'result':'sent','recipient':recipient}


PROFILE_PHOTO_LIMIT=300000


def image_kind(content):
    """Tipo real de una imagen según su cabecera (no según lo que diga el navegador). Solo PNG, JPEG y WebP."""
    if content[:8]==b'\x89PNG\r\n\x1a\n':return 'image/png'
    if content[:3]==b'\xff\xd8\xff' and content[-2:]==b'\xff\xd9':return 'image/jpeg'
    if content[:4]==b'RIFF' and content[8:12]==b'WEBP':return 'image/webp'
    return None


def profile_photo_stamp(c,uid):
    row=c.execute('SELECT updated_at FROM user_photos WHERE user_id=?',(uid,)).fetchone()
    return row['updated_at'] if row else ''


def maintenance_deliver(recipient,subject,body):
    """Envío de un recordatorio de mantenimiento por el correo del sistema; lanza MailError si el servidor no lo acepta."""
    config=mail_pro.settings()
    message,recipients=mail_pro.build_message(config,{'to':recipient,'subject':subject,'body':body,'from_name':corporate.settings()['name']},'')
    mail_pro.deliver(config,message,recipients)


def maintenance_reminders_tick(c,now):
    """Envío periódico sin tarea programada: como mucho cada diez minutos, en horario diurno y por tandas pequeñas."""
    import maintenance_reminders
    if not maintenance_reminders.enabled(c) or not 8<=now.hour<19:return
    last=c.execute("SELECT value FROM system_state WHERE key='maintenance_reminders_tick'").fetchone()
    if last and last['value']>(now-appointments.timedelta(minutes=10)).isoformat(timespec='seconds'):return
    c.execute("INSERT INTO system_state(key,value) VALUES ('maintenance_reminders_tick',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(now.isoformat(timespec='seconds'),));c.commit()
    try:
        if mail_pro.configured():maintenance_reminders.run(c,now,maintenance_deliver)
    except Exception as error:print('maintenance-reminders',type(error).__name__,flush=True)


def stay_deliver(recipient,subject,body):
    """Envío de un aviso de permanencia por el correo del sistema; devuelve el Message-ID aceptado por el servidor."""
    config=mail_pro.settings()
    message,recipients=mail_pro.build_message(config,{'to':recipient,'subject':subject,'body':body,'from_name':corporate.settings()['name']},'')
    mail_pro.deliver(config,message,recipients)
    return str(message['Message-ID'] or '')


def send_verification_code(recipient,code,minutes,where,context=''):
    """Correo corporativo con un código de un solo uso, por el buzón del sistema. Lanza MailError si el servidor no lo acepta."""
    import verification_mail
    config=mail_pro.settings()
    mail_pro.deliver(config,verification_mail.build(config,recipient,code,minutes,where,context),[recipient])


def stay_reminders_tick(c,now):
    """Avisos de permanencia sin tarea programada: como mucho cada diez minutos, en horario diurno y por tandas pequeñas."""
    import stay_reminders
    if not stay.settings(c)['mail'] or not 8<=now.hour<19:return
    last=c.execute("SELECT value FROM system_state WHERE key='stay_reminders_tick'").fetchone()
    if last and last['value']>(now-appointments.timedelta(minutes=10)).isoformat(timespec='seconds'):return
    c.execute("INSERT INTO system_state(key,value) VALUES ('stay_reminders_tick',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(now.isoformat(timespec='seconds'),));c.commit()
    try:
        if mail_pro.configured():stay_reminders.run(c,now,stay_deliver)
    except Exception as error:print('stay-reminders',type(error).__name__,flush=True)


def client_authorization_auto(c):
    row=c.execute("SELECT value FROM system_state WHERE key='client_authorization_auto'").fetchone()
    return bool(row and row['value']=='on')


def send_client_authorization(c,oid,user):
    """Crea el enlace de autorización del cliente y lo envía a su correo con un código QR. Devuelve el resultado para el personal.

    El enlace solo se entrega aquí: en la base queda únicamente su huella. Un fallo del correo no borra el enlace creado."""
    import client_authorization
    order=order_document(c,oid)
    if not order:return 404,{'error':'Orden no disponible.'}
    try:ready=mail_pro.configured()
    except mail_pro.MailError:ready=False
    if not ready:return 409,{'error':'El correo del sistema no está configurado: no se puede enviar el enlace al cliente.'}
    now=reception_now()
    try:token=client_authorization.create(c,order,user,now)
    except client_authorization.AuthorizationError as error:return 400,{'error':str(error)}
    url=client_authorization.link(token);c.commit()
    body=('Estimado/a '+order['client']+':\n\nPara continuar con el servicio de su equipo (orden N.º '+order['code']+') necesitamos su autorización.\n\n'
          'Abra este enlace seguro y siga los pasos. Se le pedirán los últimos cuatro dígitos de su identificación y un código que enviaremos a este mismo correo:\n\n'+url+'\n\n'
          'También puede escanear el código QR adjunto. El enlace es personal y caduca en '+str(client_authorization.EXPIRES_DAYS)+' días. Si usted no solicitó este servicio, ignore este mensaje.\n\n'
          'Atentamente,\n\nDepartamento de Servicio Técnico\nPC-DOCTOR S.A.')
    try:
        config=mail_pro.settings();card=mail_signature_card(c)
        message,recipients=mail_pro.build_message(config,{'to':order['email'],'subject':'PC-DOCTOR S.A. | Autorización de servicio — Orden N.º '+order['code'],'body':body,'from_name':corporate.settings()['name'],
            'attachments':[{'name':order['code']+'-QR-AUTORIZACION.png','type':'image/png','data':base64.b64encode(qr_image(url,'png')).decode()}]},card if card.get('enabled') else '')
        mail_pro.deliver(config,message,recipients);result='sent'
    except mail_pro.MailError as error:
        print('client-authorization-mail',error.kind,flush=True);result='failed: '+str(error)[:200]
    c.execute('UPDATE client_authorizations SET mail_result=? WHERE token_hash=?',(result,client_authorization.digest(token)))
    if result=='sent':order_workspace.event(c,oid,user['id'] if user else None,now,'follow_up','Enlace de autorización enviado al correo del cliente.')
    return 200,{'result':'sent' if result=='sent' else 'failed','message':'Enlace enviado al correo del cliente.' if result=='sent' else 'El enlace se creó, pero el correo no se pudo enviar: '+result[8:],'url':url,'authorization':client_authorization.summary(c,oid)}


def content_disposition(filename):
    """Nombre de descarga: versión ASCII para cualquier navegador y, si tiene espacios o tildes, el nombre exacto en UTF-8 (RFC 5987)."""
    import unicodedata
    from urllib.parse import quote
    plain=''.join(ch for ch in unicodedata.normalize('NFD',filename) if not unicodedata.combining(ch));safe=re.sub(r'[^A-Za-z0-9._-]','-',plain)
    header='inline; filename="'+safe+'"'
    if safe!=filename:header+="; filename*=UTF-8''"+quote(filename,safe='')
    return header


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
    """El alta pública de cuentas se retiró (12/10/2026): las cuentas las crea administración desde Gestión de Usuarios y Accesos."""
    return False


INVITE_HOURS=72


def access_link(c,uid,hours=INVITE_HOURS):
    """Enlace temporal de un solo uso para que la persona establezca su propia contraseña. Sustituye a cualquier enlace anterior."""
    base=os.getenv('APP_URL','http://127.0.0.1:8010').rstrip('/')
    if urlsplit(base).scheme!='https' and urlsplit(base).hostname not in ('127.0.0.1','localhost'):raise RuntimeError('La invitación requiere HTTPS')
    token=secrets.token_urlsafe(32)
    c.execute('DELETE FROM reset_tokens WHERE user_id=?',(uid,))
    c.execute('INSERT INTO reset_tokens VALUES (?,?,?)',(digest(token),uid,int(time.time())+hours*3600))
    return base+'/reset?token='+token


def send_access_mail(email,name,url,invite=True,hours=INVITE_HOURS):
    """Correo de invitación o de restablecimiento de acceso. Nunca incluye contraseñas: solo el enlace temporal."""
    company=corporate.settings();e=html.escape
    title='Activa tu cuenta de Órdenes Pro' if invite else 'Restablece tu acceso a Órdenes Pro'
    lead=('Administración de '+company['name']+' creó una cuenta para ti en Órdenes Pro.' if invite else 'Administración de '+company['name']+' generó un enlace para que restablezcas tu acceso a Órdenes Pro.')
    text='\n'.join([company['name'],'',title,'','Hola, '+name+':',lead,'','Establece tu contraseña desde este enlace:',url,'','El enlace caduca en %d horas y solo puede usarse una vez. Nadie conoce tu contraseña: la eliges tú.'%hours,'Si no esperabas este mensaje, ignóralo.','',company['name'],company['website']])
    font="font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    import verification_mail
    markup=('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"></head><body style="margin:0;padding:0;background-color:#eef2f8">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#eef2f8"><tr><td align="center" style="padding:28px 12px">'
            '<table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:560px;background-color:#ffffff;border:1px solid #d9e2ef;border-radius:14px">'
            '<tr><td align="center" style="padding:26px 24px 14px"><img src="'+e(verification_mail.logo_url())+'" width="132" alt="PC-DOCTOR S.A." style="display:block;border:0;width:132px;height:auto">'
            '<div style="'+font+';font-size:18px;line-height:24px;font-weight:700;color:#143f77;padding-top:10px">'+e(company['name'])+'</div></td></tr>'
            '<tr><td style="padding:0 24px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td height="3" bgcolor="#143f77" style="height:3px;line-height:3px;font-size:0">&nbsp;</td><td width="64" height="3" bgcolor="#d94049" style="width:64px;height:3px;line-height:3px;font-size:0">&nbsp;</td></tr></table></td></tr>'
            '<tr><td align="center" style="padding:26px 28px 6px"><h1 style="margin:0;'+font+';font-size:22px;line-height:30px;color:#102744">'+e(title)+'</h1>'
            '<p style="margin:12px 0 0;'+font+';font-size:15px;line-height:23px;color:#33435a">Hola, '+e(name)+'.<br>'+e(lead)+'</p></td></tr>'
            '<tr><td align="center" style="padding:20px 28px 8px"><a href="'+e(url)+'" style="display:inline-block;background-color:#2359ac;color:#ffffff;'+font+';font-size:15px;font-weight:700;text-decoration:none;padding:13px 26px;border-radius:10px">Establecer mi contraseña</a></td></tr>'
            '<tr><td align="center" style="padding:8px 28px 4px;'+font+';font-size:13px;line-height:21px;color:#4a5a70">El enlace caduca en <strong style="color:#102744">%d horas</strong> y solo puede usarse una vez.<br>Nadie conoce tu contraseña: la eliges tú.</td></tr>'%hours+
            '<tr><td style="padding:16px 28px 6px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#fff7f7" style="border-left:3px solid #d94049"><tr><td style="padding:11px 14px;'+font+';font-size:13px;line-height:20px;color:#4a5a70">Si no esperabas este mensaje, ignóralo. Si el botón no funciona, copia este enlace en tu navegador:<br><span style="word-break:break-all;color:#2359ac">'+e(url)+'</span></td></tr></table></td></tr>'
            '<tr><td align="center" style="padding:20px 28px 24px;border-top:1px solid #e3e9f1;'+font+';font-size:12px;line-height:19px;color:#68768a"><strong style="color:#143f77">'+e(company['name'])+'</strong><br>'+e(re.sub(r'^https?://|/$','',company['website']))+'<br>Mensaje automático de seguridad de Órdenes Pro.</td></tr>'
            '</table></td></tr></table></body></html>')
    send_security_mail(email,('Activa tu cuenta' if invite else 'Restablece tu acceso')+' | '+company['name'],text,markup)


def deliver_access(c,uid,email,name,invite):
    """Genera el enlace y lo envía. Devuelve (resultado, enlace): el enlace solo se entrega a administración cuando el correo no pudo salir."""
    url=access_link(c,uid);c.commit()
    if not security_mail_ready():return 'unavailable',url
    try:send_access_mail(email,name,url,invite)
    except (OSError,RuntimeError,smtplib.SMTPException,mail_pro.MailError):return 'failed',url
    return 'sent',''


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


# Cierre por inactividad: una sesión sin actividad real de la persona durante IDLE_SECONDS deja de ser válida en el servidor.
# El navegador avisa IDLE_WARNING segundos antes. «Recordarme» alarga la vida máxima de la sesión, no el tiempo de inactividad.
IDLE_SECONDS = 15*60
IDLE_WARNING = 2*60
# El navegador lleva la cuenta exacta y avisa al servidor de la actividad como mucho una vez por minuto: el servidor concede ese margen
# antes de invalidar la sesión por su cuenta, para no cortar a quien todavía ve la cuenta atrás.
IDLE_GRACE = 75
# Esperas progresivas tras intentos fallidos consecutivos (segundos según el número de fallos acumulados).
LOGIN_WAITS = {2:3, 3:8, 4:20}
LOGIN_USER_MAX = 50
LOGIN_EMAIL_MAX = 254
PASSWORD_MAX = 128          # contraseñas nuevas
PASSWORD_LOGIN_MAX = 256    # el acceso sigue aceptando las contraseñas que ya existían


def login_wait(c, keys):
    """Segundos que faltan para poder volver a intentar el acceso con esta cuenta u origen."""
    now=int(time.time());left=0
    for key in keys:
        row=c.execute('SELECT expires FROM attempts WHERE bucket=? AND expires>?',('wait:'+key,now)).fetchone()
        if row:left=max(left,row[0]-now)
    return left


def login_risky(c, keys):
    """Hay fallos recientes con esta cuenta u origen: se exige la verificación adicional (prueba de trabajo de un solo uso)."""
    now=int(time.time())
    return any((c.execute('SELECT count FROM attempts WHERE bucket=? AND expires>?',(key,now)).fetchone() or [0])[0]>=2 for key in keys)


def make_session(c, user_id, remember=False):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    policy=auth_policy(c)
    age = policy['remember_days']*86400 if remember else policy['session_hours']*3600
    now=int(time.time())
    c.execute('DELETE FROM sessions WHERE expires<? OR last_activity<?', (now,now-IDLE_SECONDS-IDLE_GRACE))
    c.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires,last_activity) VALUES (?,?,?,?,?)', (digest(token), user_id, csrf, now+age, now))
    return token, csrf, age


def dispatch_security_job(job):
    # SMTP nunca forma parte del tiempo de respuesta público: evita enumeración por latencia.
    thread=threading.Thread(target=job,daemon=True,name='security-mail');thread.start()
    # En funciones sin servidor el proceso se congela al responder y el hilo no llega a enviar: allí se espera al envío.
    if os.getenv('VERCEL'):thread.join(15)


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


def security_mail_ready():
    """El correo de seguridad (recuperación de contraseña, avisos de cuenta) puede salir por SMTP_* o, si no está definido, por el correo del sistema (MAIL_*)."""
    if all(os.getenv(name) for name in ('SMTP_HOST','SMTP_FROM','SMTP_USER','SMTP_PASSWORD')):return 'smtp'
    try:return 'mail' if mail_pro.configured() else ''
    except mail_pro.MailError:return ''


def send_security_mail(email, subject, text, markup=None):
    route=security_mail_ready()
    if route=='mail':
        # Mismo buzón que usa Mail Pro: evita depender de una segunda configuración de correo.
        config=mail_pro.settings()
        message,recipients=mail_pro.build_message(config,{'to':email,'subject':subject,'body':text,'from_name':corporate.settings()['name']},'')
        try:mail_pro.deliver(config,message,recipients)
        except mail_pro.MailError as error:raise RuntimeError('No se pudo enviar el correo de seguridad: '+str(error))
        return
    host, sender = os.getenv('SMTP_HOST'), os.getenv('SMTP_FROM')
    if route!='smtp':
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

    def reply(self, status, body, content_type='application/json; charset=utf-8', cookie=None, filename=None):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        # Nombre con el número real de la orden cuando el documento se guarda o descarga desde el navegador.
        if filename:self.send_header('Content-Disposition',content_disposition(filename))
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
        now=int(time.time())
        return c.execute('SELECT u.id,u.username,u.name,u.email,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND (s.last_activity IS NULL OR s.last_activity>?) AND u.active=1', (digest(token), now, now-IDLE_SECONDS-IDLE_GRACE)).fetchone(), token

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
        try:published=versioning.load()['releases'][0]['date'][:10];published='/'.join(reversed(published.split('-')))
        except (versioning.RegistryError,IndexError,KeyError):published=''
        content = content.replace('{{app_date}}',html.escape(published))
        content = content.replace('{{evaluation_notice}}', notice).replace('{{environment_label}}', 'Servicio técnico' if production_enabled() else 'Evaluación local · Usa datos ficticios')
        self.reply(200, content, 'text/html; charset=utf-8')

    def do_GET(self):
        path = urlsplit(self.path).path
        files = {'/static/label.css':'label.css','/static/tracking.css':'tracking.css','/static/app.css':'app.css','/static/app.js':'app.js','/static/form-validation.js':'form-validation.js','/static/appointments.js':'appointments.js','/static/adi-widget.js':'adi-widget.js','/static/adi-orb.js':'adi-orb.js','/static/ui-select.js':'ui-select.js','/static/ticket.css':'ticket.css','/static/ticket.js':'ticket.js','/static/quote.css':'quote.css','/static/quote-sign.js':'quote-sign.js','/static/echarts.min.js':'echarts.min.js','/static/logo-original.png':'logo-original.png',
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
            if path == '/api/public/hours':
                # Horarios vigentes para las páginas públicas: los mismos que usa ADI.
                import business_hours
                return self.reply(200,business_hours.public(c,reception_now()))
            if path == '/api/public/versions':
                # Historial público de versiones (las mismas notas que ya muestra /novedades), por páginas. Sin datos técnicos ni credenciales.
                try:releases=versioning.load()['releases']
                except versioning.RegistryError:return self.reply(503,{'error':'No se pudo leer el historial de versiones.'})
                page=parse_qs(urlsplit(self.path).query).get('page',['1'])[0];page=int(page) if page.isdigit() and 1<=int(page)<=10000 else 1
                size=12;pages=max(1,(len(releases)+size-1)//size);page=min(page,pages)
                rows=[{'version':item['version'],'date':item.get('date',''),'type':versioning.TYPES.get(item.get('type'),item.get('type','')),'summary':item.get('summary',''),
                       'notes':[{'key':key,'title':title,'items':item.get('changes',{}).get(key,[])} for key,title in versioning.CATEGORIES.items() if item.get('changes',{}).get(key)]} for item in releases[(page-1)*size:page*size]]
                return self.reply(200,{'rows':rows,'page':page,'pages':pages,'total':len(releases)})
            if path == '/api/public/version':
                # Estado real de la versión, sin sesión: la instalada (la del código desplegado) frente al registro publicado. Solo expone notas ya públicas.
                # La comprobación se guarda 20 minutos para no consultar el registro en cada visita; «refresh=1» la repite (con límite).
                try:registry=versioning.load();installed=registry['releases'][0]
                except (versioning.RegistryError,IndexError):return self.reply(503,{'error':'No se pudo leer la versión instalada.'})
                now=reception_now();cached=None;refresh=parse_qs(urlsplit(self.path).query).get('refresh',[''])[0]=='1'
                try:
                    row=c.execute("SELECT value FROM system_state WHERE key='public_version_check'").fetchone();cached=json.loads(row['value']) if row else None
                except (ValueError,TypeError):cached=None
                fresh=cached and cached.get('installed')==installed['version'] and cached.get('at','')>(now-appointments.timedelta(minutes=20)).isoformat(timespec='seconds')
                if refresh and limited(c,'version-check:'+digest(self.client_address[0]),6,300):refresh=False
                if not fresh or refresh:
                    try:
                        found=versioning.check(registry,now);pending=found['pending']
                        important=any(item['type'] in ('major','minor') or item['changes'].get('security') for item in pending)
                        cached={'installed':installed['version'],'at':now.isoformat(timespec='seconds'),'state':('important' if important else 'available') if pending else 'updated','latest':found['latest']['version'] if found['latest'] else installed['version'],'pending':len(pending),'source':found['source']}
                    except versioning.RegistryError:
                        cached={'installed':installed['version'],'at':now.isoformat(timespec='seconds'),'state':'error','latest':'','pending':0,'source':'remote'}
                    c.execute("INSERT INTO system_state(key,value) VALUES ('public_version_check',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(cached),));c.commit()
                notes=[{'key':key,'title':title,'items':installed['changes'].get(key,[])} for key,title in versioning.CATEGORIES.items() if installed['changes'].get(key)]
                return self.reply(200,{'version':installed['version'],'date':installed['date'],'type':versioning.TYPES.get(installed['type'],installed['type']),'summary':installed.get('summary',''),'notes':notes,
                                       'state':cached['state'],'latest':cached['latest'],'pending':cached['pending'],'checked_at':cached['at'],'source':cached['source'],'history':len(registry['releases']),
                                       # Identificador del despliegue en ejecución (lo define la plataforma al compilar); no es un secreto.
                                       'build':(os.getenv('VERCEL_GIT_COMMIT_SHA','') or 'local')[:7],'deployment':(os.getenv('VERCEL_DEPLOYMENT_ID','') or '')[-8:],'server_time':now.isoformat(timespec='seconds')})
            if path == '/api/cron/reminders':
                # Con CRON_SECRET definido solo responde a la llamada autenticada de la plataforma. No envía nada si los avisos están apagados.
                expected=os.getenv('CRON_SECRET','')
                if expected and not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+expected):return self.reply(404,{'error':'No encontrado.'})
                now=reception_now();maintenance_reminders_tick(c,now);stay_reminders_tick(c,now)
                return self.reply(200,{'ok':True})
            if path == '/api/public/appointments/services':
                # Catálogo público para la reserva: servicios, tipos de equipo y marcas con su logotipo local. Sin datos de clientes.
                brand_files={f.stem:f.name for f in sorted((ROOT / 'static' / 'brands').glob('*')) if f.suffix in ('.svg','.png') and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', f.stem)}
                brand_names=sorted({r['name'] for r in c.execute('SELECT name FROM brands')},key=str.lower)
                return self.reply(200, {'services':appointments.services(c),'device_types':DEVICE_TYPES,'timezone':'America/Guayaquil','brands':brand_names,'brand_logos':brand_files})
            if path == '/api/public/appointments/pulse':
                # Señal ligera para sincronizar calendarios abiertos: cambia cuando cambia la agenda. Sin datos de citas ni de clientes.
                return self.reply(200,{'pulse':appointments.pulse(c),'buffer':appointments.buffer_minutes(c),'server_time':reception_now().isoformat(timespec='seconds')})
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
            maintenance_page=re.fullmatch(r'/mantenimiento/([A-Za-z0-9_-]{40,60})',path)
            if maintenance_page:
                # Página del cliente para su mantenimiento preventivo: confirmar la fecha, pedir otro horario o dejar de recibir avisos.
                import maintenance_reminders
                if limited(c,'maint-ip:'+digest(self.client_address[0]),60,300):return self.reply(429,{'error':'Demasiadas consultas. Intenta más tarde.'})
                found=maintenance_reminders.lookup(c,maintenance_page[1])
                return self.reply(200 if found else 404,maintenance_reminders.page(found,maintenance_page[1]) if found else maintenance_reminders.missing_page(),'text/html; charset=utf-8')
            # Autorización electrónica del cliente por enlace aleatorio. La respuesta es idéntica para enlaces inexistentes.
            quote_page=re.fullmatch(r'/presupuesto/([A-Za-z0-9_-]{30,80})(/documento\.pdf)?',path)
            if quote_page:
                # Presupuesto por enlace privado: identidad con los últimos cuatro dígitos antes de mostrar importes; el PDF exige esa comprobación o una decisión ya registrada.
                if limited(c,'quote-ip:'+digest(self.client_address[0]),60,300):return self.reply(429,{'error':'Demasiadas consultas. Intenta más tarde.'})
                now=reception_now();quote,link=quotes.lookup(c,quote_page[1],now)
                if not quote:return self.reply(404,quotes.missing_page(),'text/html; charset=utf-8')
                document=order_document(c,quote['order_id'])
                if quote_page[2]:
                    if quote['status']=='enviado' and not (link['usable'] and quotes.valid_passkey(link,parse_qs(urlsplit(self.path).query).get('k',[''])[0],now)):return self.reply(404,quotes.missing_page(),'text/html; charset=utf-8')
                    if quote['status'] in ('borrador','cancelado','modificacion'):return self.reply(404,quotes.missing_page(),'text/html; charset=utf-8')
                    import quote_pdf
                    number=re.sub(r'\D','',str(document.get('identification') or ''))
                    return self.reply(200,quote_pdf.render(quotes.detail(c,quote),dict(document,identification=number[:2]+'*'*max(0,len(number)-2) if number else '')),'application/pdf',filename=quote['code']+'-PRESUPUESTO.pdf')
                if quote['status']!='enviado':return self.reply(200,quotes.result_page(quote_page[1],quote,document,quotes.items_of(c,quote['id'])),'text/html; charset=utf-8')
                if not link['usable']:return self.reply(404,quotes.missing_page(),'text/html; charset=utf-8')
                return self.reply(200,quotes.identify_page(quote_page[1],quote,document),'text/html; charset=utf-8')
            authorize_page=re.fullmatch(r'/autorizar/([A-Za-z0-9_-]{20,80})(/comprobante\.pdf)?',path)
            if authorize_page:
                import client_authorization
                if limited(c,'cauth-ip:'+digest(self.client_address[0]),60,300):return self.reply(429,{'error':'Demasiadas consultas. Intenta más tarde.'})
                found=client_authorization.lookup(c,authorize_page[1],reception_now())
                if not found:return self.reply(404,client_authorization.missing_page(),'text/html; charset=utf-8')
                document=order_document(c,found['order_id'])
                if authorize_page[2]:
                    if found['status'] not in ('signed','rejected'):return self.reply(404,client_authorization.missing_page(),'text/html; charset=utf-8')
                    return self.reply(200,client_authorization.render_pdf(found),'application/pdf',filename=document['code']+'-AUTORIZACION.pdf')
                return self.reply(200,client_authorization.start_page(c,authorize_page[1],found,document),'text/html; charset=utf-8')
            # Seguimiento público por enlace aleatorio: respuesta idéntica para enlaces inexistentes o revocados.
            tracking_page=re.fullmatch(r'/s/([A-Za-z0-9_-]{1,64})(/qr\.svg|/barcode\.svg)?',path)
            if tracking_page:
                import order_tracking
                if limited(c,'tracking-ip:'+digest(self.client_address[0]),120 if tracking_page[2] else 40,300):return self.reply(429,{'error':'Demasiadas consultas. Intenta más tarde.'})
                found=order_tracking.lookup(c,tracking_page[1])
                if tracking_page[2]:
                    # Códigos reales de la tarjeta pública: el QR lleva al propio enlace de seguimiento y el de barras al número de la orden.
                    if not found:return self.reply(404,{'error':'Enlace no disponible.'})
                    if tracking_page[2]=='/qr.svg':return self.reply(200,qr_image(order_tracking.url(tracking_page[1])+'#'+found['code'],'svg'),'image/svg+xml')
                    import barcode128
                    return self.reply(200,barcode128.svg(found['code']),'image/svg+xml')
                return self.reply(200 if found else 404,order_tracking.public_page(found,tracking_page[1]) if found else order_tracking.missing_page(),'text/html; charset=utf-8')
            if path == '/conditions':
                active=service_terms.current(c,reception_now())
                if not active:return self.reply(404,{'error':'Las condiciones vigentes aún no han sido publicadas.'})
                return self.reply(200,service_terms.public_page(active),'text/html; charset=utf-8')
            terms_pdf=re.fullmatch(r'/conditions/([a-f0-9]{32})\.pdf',path)
            if terms_pdf:
                # PDF oficial de una versión publicada: mismo contenido público que la página, sin datos personales.
                row=c.execute('SELECT * FROM service_terms WHERE id=?',(terms_pdf[1],)).fetchone()
                if not row:return self.reply(404,{'error':'Versión de condiciones no disponible.'})
                import conditions_pdf
                return self.reply(200,conditions_pdf.render_conditions(dict(row)),'application/pdf',filename=conditions_pdf.FILE_NAME)
            public_terms=re.fullmatch(r'/conditions/([a-f0-9]{32})',path)
            if public_terms:
                row=c.execute('SELECT * FROM service_terms WHERE id=?',(public_terms[1],)).fetchone()
                if not row:return self.reply(404,{'error':'Versión de condiciones no disponible.'})
                return self.reply(200,service_terms.public_page(row),'text/html; charset=utf-8')
            user, _ = self.session(c)
            if path in ('/', '/login') or re.fullmatch(r'/orders/[^/]{1,80}',path):
                return self.page('dashboard.html' if user else 'login.html')
            staff_card=re.fullmatch(r'/tarjeta/([0-9]{1,12})',path)
            if staff_card:
                # Tarjeta de seguimiento para imprimir o guardar como PDF, con los datos internos: exige sesión.
                if not user:return self.page('login.html')
                import order_tracking
                found=order_tracking.staff_data(c,int(staff_card[1]))
                if not found:return self.reply(404,{'error':'Orden no disponible.'})
                return self.reply(200,order_tracking.card_page(found,'/api/orders/%d/tracking-qr.png'%found['id'] if order_tracking.active(c,found['id'])['active'] else '',False),'text/html; charset=utf-8')
            if path == '/forgot':
                return self.page('forgot.html')
            if path == '/registro':
                if not user or user['role']!='administrador':return self.reply(404,{'error':'Página no disponible.'})
                return self.reply(200,'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/#settings?tab=users"><title>Gestión de Usuarios y Accesos</title></head><body><p><a href="/#settings?tab=users">Ir a Gestión de Usuarios y Accesos</a></p></body></html>','text/html; charset=utf-8')
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
                # Estado real de ADI para la redacción y los canales; no expone claves.
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                import adi_ai
                usage=c.execute("SELECT COUNT(*) n FROM adi_actions WHERE action='writing_improve' AND created_at>=?",(reception_now().date().isoformat(),)).fetchone()['n']
                auto_receipt=c.execute("SELECT value FROM system_state WHERE key='receipt_mail_auto'").fetchone()
                return self.reply(200,{'writing':adi_ai.status(c),'today':usage,'channels':{'mail':mail_allowed(user),'web_chat':True,'whatsapp':False},'receipt_mail_auto':not (auto_receipt and auto_receipt['value']=='off')})
            if path == '/api/adi/admin':
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede usar la asistente administrativa.'})
                return self.reply(200,{'enabled':bool(adi_ai.openai_key()),'message':'ADI responde consultas operativas desde datos autorizados.','live':adi.snapshot(c,reception_now())})
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
                return self.reply(200,{'rows':live_support.rows(c,parse_qs(urlsplit(self.path).query).get('scope',['active'])[0]),'server_time':appointments.stamp(appointments.now())})
            live_match=re.fullmatch(r'/api/adi/live/([0-9]+)',path)
            if live_match:
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                conv=c.execute('SELECT * FROM adi_conversations WHERE id=?',(int(live_match[1]),)).fetchone()
                if not conv:return self.reply(404,{'error':'Conversación no disponible.'})
                try:after=max(0,int(parse_qs(urlsplit(self.path).query).get('after',['0'])[0]))
                except ValueError:after=0
                return self.reply(200,live_support.detail(c,conv,after,appointments.stamp(appointments.now())))
            if path == '/api/me':
                prefs=c.execute('SELECT value FROM system_state WHERE key=?',('mail_prefs:'+str(user['id']),)).fetchone() if mail_allowed(user) else None
                return self.reply(200, {'idle':{'seconds':IDLE_SECONDS,'warning':IDLE_WARNING},'user':dict(user,photo=profile_photo_stamp(c,user['id']),mail=mail_allowed(user),mail_prefs=json.loads(prefs['value']) if prefs else None,mail_signature=mail_signature_card(c) if mail_allowed(user) else None,storage='cloud' if remote_db.configured() else 'local'),'server_time':time.time()})
            if path == '/api/deliveries':
                # Próximas Entregas: solo equipos terminados (listos o en espera de retiro) y entregas recientes; nunca órdenes en reparación.
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                today=reception_now().date();since=(today-appointments.timedelta(days=30)).isoformat()
                rows=[dict(r) for r in c.execute("SELECT o.id,o.code,o.status,o.estimated_delivery,o.updated_at,o.delivered_at,o.assigned_to,COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'Sin asignar') responsible,cl.id client_id,cl.name client,cl.phone,cl.email,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,(SELECT e.comment FROM order_history e WHERE e.order_id=o.id AND e.comment!='' ORDER BY e.id DESC LIMIT 1) note FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.status IN ('listo','espera_entrega') OR (o.status='entregado' AND o.delivered_at>=?) ORDER BY CASE o.status WHEN 'entregado' THEN 1 ELSE 0 END,CASE WHEN o.estimated_delivery='' THEN 1 ELSE 0 END,o.estimated_delivery,o.id LIMIT 400",(since,))]
                for row in rows:
                    due=row['estimated_delivery'] or '';since_ready=row['updated_at'][:10] if row['status']!='entregado' else ''
                    row['waiting_days']=(today-appointments.date.fromisoformat(since_ready)).days if since_ready else None
                    # Estado de entrega derivado de datos reales: estado de la orden y fecha estimada.
                    row['delivery']='delivered' if row['status']=='entregado' else 'overdue' if due and due<today.isoformat() else 'pickup' if row['status']=='espera_entrega' else 'scheduled' if due>today.isoformat() else 'ready'
                    row['today']=row['status']!='entregado' and due==today.isoformat()
                return self.reply(200,{'rows':rows,'today':today.isoformat()})
            if path == '/api/receipt-mail/history':
                # Últimos envíos de comprobantes (todas las órdenes), para revisar resultados y errores.
                if user['role']!='administrador':return self.reply(403,{'error':'Acceso no permitido.'})
                rows=[dict(r) for r in c.execute('SELECT m.order_id,o.code,m.mode,m.recipient,m.result,m.detail,m.created_at,u.name actor FROM order_receipt_mail m JOIN orders o ON o.id=m.order_id LEFT JOIN users u ON u.id=m.actor_id ORDER BY m.id DESC LIMIT 30')]
                try:sender=mail_pro.settings()['username'] if mail_pro.configured() else ''
                except mail_pro.MailError:sender=''
                return self.reply(200,{'rows':rows,'sender':sender,'configured':bool(sender)})
            if path == '/api/order-draft':
                # Borrador de Nueva orden del propio usuario.
                return self.reply(200,{'draft':order_drafts.read(c,user)})
            if path == '/api/weather':
                return self.reply(200, current_weather(force=parse_qs(urlsplit(self.path).query).get('fresh',[''])[0]=='1'))
            if path == '/api/time':
                return self.reply(200, {'server_time':time.time(),'timezone':'America/Guayaquil'})
            if path == '/api/thermal-printer':return self.reply(200,thermal_printing.capability())
            if path == '/api/corporate':return self.reply(200,corporate.settings())
            if path in ('/api/conditions/draft','/api/conditions/draft.pdf'):
                draft=corporate.terms_draft()
                if path.endswith('.pdf'):
                    import conditions_pdf
                    return self.reply(200,conditions_pdf.render_conditions(draft),'application/pdf',filename=conditions_pdf.DRAFT_FILE_NAME)
                return self.reply(200,draft)
            if path == '/api/conditions/current':
                active=service_terms.current(c,reception_now())
                return self.reply(200,{'terms':({**service_terms.metadata(active),'full_text':active['full_text']} if active else None),'required':terms_required()})
            if path == '/api/conditions':
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede consultar el historial de publicación.'})
                return self.reply(200,service_terms.overview(c,reception_now()))
            terms_compare=re.fullmatch(r'/api/conditions/compare/([0-9a-f]{32})',path)
            if terms_compare:
                # Diferencias de una versión publicada frente a la inmediatamente anterior.
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede comparar versiones.'})
                row=c.execute('SELECT * FROM service_terms WHERE id=?',(terms_compare[1],)).fetchone()
                if not row:return self.reply(404,{'error':'Versión no disponible.'})
                older=c.execute('SELECT * FROM service_terms WHERE published_at<? ORDER BY published_at DESC LIMIT 1',(row['published_at'],)).fetchone()
                return self.reply(200,{'version':row['version'],'previous':older['version'] if older else '','diff':service_terms.compare(older['full_text'] if older else '',row['full_text'])})
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
            photo_view=re.fullmatch(r'/api/users/([0-9]+)/photo',path)
            if photo_view:
                # Foto de perfil de una cuenta del equipo: solo para sesiones iniciadas.
                picture=c.execute('SELECT mime,data FROM user_photos WHERE user_id=?',(int(photo_view[1]),)).fetchone()
                if not picture:return self.reply(404,{'error':'Sin foto de perfil.'})
                return self.reply(200,base64.b64decode(picture['data']),picture['mime'])
            staff_authorization=re.fullmatch(r'/api/orders/([0-9]+)/client-authorization\.pdf',path)
            if staff_authorization:
                import client_authorization
                signed=c.execute("SELECT a.*,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code FROM client_authorizations a JOIN orders o ON o.id=a.order_id WHERE a.order_id=? AND a.status IN ('signed','rejected') ORDER BY a.id DESC LIMIT 1",(int(staff_authorization[1]),)).fetchone()
                if not signed:return self.reply(404,{'error':'Esta orden no tiene una autorización firmada por el cliente.'})
                return self.reply(200,client_authorization.render_pdf(dict(signed)),'application/pdf',filename=signed['code']+'-AUTORIZACION.pdf')
            device_detail=re.fullmatch(r'/api/devices/([0-9]+)',path)
            if device_detail:
                # Ficha del equipo con su historial técnico: todas las órdenes del dispositivo, de la más reciente a la más antigua. Solo lectura.
                device=c.execute("SELECT d.id,d.client_id,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,d.color,c.name client,c.phone,c.identification FROM devices d JOIN clients c ON c.id=d.client_id WHERE d.id=?",(int(device_detail[1]),)).fetchone()
                if not device:return self.reply(404,{'error':'Equipo no disponible.'})
                device=dict(device)
                history=[dict(r) for r in c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,o.created_at,o.received_at,o.delivered_at,o.status status_code,s.label status,o.problem,o.findings,o.recommendations,COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'Sin asignar') responsible FROM orders o JOIN statuses s ON s.code=o.status WHERE o.device_id=? ORDER BY o.id DESC LIMIT 200",(device['id'],))]
                same=[dict(r) for r in c.execute("SELECT x.id,x.brand,x.model,x.serial,cl.name client,(SELECT COUNT(*) FROM orders o WHERE o.device_id=x.id) orders FROM devices x JOIN clients cl ON cl.id=x.client_id WHERE x.id!=? AND ?!='' AND lower(TRIM(COALESCE(x.serial,'')))=lower(?) ORDER BY x.id LIMIT 20",(device['id'],(device['serial'] or '').strip(),(device['serial'] or '').strip()))]
                return self.reply(200,{'device':device,'history':history,'duplicates':same,'summary':{'orders':len(history),'delivered':sum(1 for h in history if h['status_code']=='entregado'),'open':sum(1 for h in history if h['status_code']!='entregado'),'first':history[-1]['created_at'] if history else None,'last':history[0]['created_at'] if history else None}})
            client_detail=re.fullmatch(r'/api/clients/([0-9]+)',path)
            if client_detail:
                row=c.execute('SELECT * FROM clients WHERE id=?',(int(client_detail[1]),)).fetchone()
                if not row:return self.reply(404,{'error':'Cliente no disponible.'})
                devices=[dict(r) for r in c.execute('SELECT * FROM devices WHERE client_id=?',(row['id'],))]
                orders=[dict(r) for r in c.execute("SELECT o.id,o.code,o.created_at,o.received_at,o.status status_code,s.label status,o.problem,o.findings,o.recommendations,o.delivered_at,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,COALESCE((SELECT labor_cents+parts_cents+services_cents+digital_cents FROM order_budget b WHERE b.order_id=o.id),0) total_cents FROM orders o JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status WHERE d.client_id=? ORDER BY o.id DESC",(row['id'],))]
                batch=c.execute('SELECT filename,created_at FROM client_import_batches WHERE id=?',(row['import_batch_id'],)).fetchone() if row['import_batch_id'] else None
                # Citas del cliente y última atención registrada (entrega más reciente o, si no hay, último ingreso).
                dates=[dict(r) for r in c.execute("SELECT a.id,a.public_code,a.starts_at,a.status,a.duration_minutes,COALESCE(s.label,a.service_code) service,a.brand,a.model FROM appointments a LEFT JOIN appointment_services s ON s.code=a.service_code WHERE a.client_id=? AND a.deleted_at IS NULL ORDER BY a.starts_at DESC LIMIT 30",(row['id'],))]
                last=max((item['delivered_at'] or item['received_at'] or '' for item in orders),default='')
                return self.reply(200,{'client':client_registry.profile(row),'devices':devices,'orders':orders,'appointments':dates,'equipment':equipment.client_history(c,row['id']),'last_service':last,'missing':client_registry.missing(row) if row['needs_review'] else [],'imported':dict(batch) if batch else None,'can_edit':user['role']=='administrador' or bool(row['needs_review'])})
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
            detail = re.fullmatch(r'/api/orders/([0-9]+)(?:/(qr\.(svg|png)|tracking-qr\.png|receipt\.pdf|thermal\.pdf|service\.pdf|label\.pdf|stay\.pdf|barcode\.svg|tracking-card))?', path)
            if detail:
                row = c.execute('SELECT o.*,COALESCE(NULLIF(d.kind,\'\'),d.category) type,d.brand,d.model,d.serial,d.color,d.code device_code,c.id client_id,c.name client,c.identification,c.phone,c.email,c.province,c.city,c.address,c.location_reference,s.label status_label FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?',(int(detail[1]),)).fetchone()
                if not row:
                    return self.reply(404, {'error':'Orden no disponible.'})
                code = row['code'] or 'OP-'+str(row['id']).zfill(5)
                if detail[2]=='barcode.svg':
                    import barcode128
                    return self.reply(200,barcode128.svg(code),'image/svg+xml')
                if detail[2]=='tracking-card':
                    # Tarjeta Digital de Seguimiento Técnico: el mismo fragmento que se imprime, con los datos actuales de la orden.
                    import order_tracking
                    link=order_tracking.active(c,row['id'])
                    return self.reply(200,{'html':order_tracking.card(order_tracking.staff_data(c,row['id']),'/api/orders/%d/tracking-qr.png'%row['id'] if link['active'] else '',False),'code':code,'public_url':link['url'],'active':link['active'],'print_url':'/tarjeta/%d'%row['id']})
                if detail[2]=='tracking-qr.png':
                    # QR del enlace público de seguimiento vigente: el mismo enlace que se copia y que imprime el ticket.
                    import order_tracking
                    link=order_tracking.active(c,row['id'])
                    if not link['active']:return self.reply(404,{'error':'La orden no tiene un enlace de seguimiento activo.'})
                    return self.reply(200, qr_image(link['url']+'#'+code,'png'), 'image/png')
                if detail[3]:
                    return self.reply(200, qr_image(row['qr_url'],detail[3]), 'image/svg+xml' if detail[3]=='svg' else 'image/png')
                if detail[2]=='stay.pdf':
                    # Informe de permanencia: fechas registradas de ingreso y entrega frente al plazo vigente.
                    import stay_pdf
                    info=stay.compute(dict(row,status_code=row['status']),reception_now(),stay.settings(c))
                    if not info:return self.reply(404,{'error':'La orden no tiene fecha de ingreso registrada.'})
                    return self.reply(200,stay_pdf.render(dict(row,code=code),info,stay.delivery(c,row['id']),reception_now()),'application/pdf',filename=code+'-PERMANENCIA.pdf')
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
                        return self.reply(200,render_thermal(pdf_order,copy),'application/pdf',filename=code+'-TICKET.pdf')
                    return self.reply(200, render_receipt(pdf_order), 'application/pdf',filename=code+'-COMPROBANTE-DE-RECEPCION.pdf')
                result = dict(row)
                import order_tracking
                result['tracking']=order_tracking.active(c,row['id'])
                # Equipos de la orden, identidad permanente del equipo y pagos de este ingreso.
                result['group']=equipment.group(c,row['id']);result['device_code']=row['device_code'] or ''
                result['unit_code']=next((unit['unit_code'] for unit in result['group']['units'] if unit['id']==row['id']),'') if result['group']['multiple'] else ''
                result['payments']=equipment.payments(c,row['id']);result['money']=equipment.money(c,row['id']);result['payment_methods']=equipment.METHODS
                result['receipt_mail']=receipt_mail_status(c,row['id'])
                result['authorization_mail']=authorization_mail_status(c,row['id'])
                import client_authorization
                result['client_authorization']=client_authorization.summary(c,row['id']);result['client_authorization_auto']=client_authorization_auto(c)
                result['stay']=stay.compute(dict(result,status_code=result['status']),reception_now(),stay.settings(c));result['stay_settings']=stay.settings(c);result['stay_delivery']=stay.delivery(c,row['id']) if result['status']=='entregado' else None
                import stay_reminders
                result['stay_reminders']=stay_reminders.for_order(c,row['id'])
                result.pop('request_key', None)
                if result['reception_snapshot']:
                    result.update(json.loads(result['reception_snapshot']))
                result.pop('reception_snapshot',None)
                result['code'] = code
                service_terms.attach(c,result)
                technical_access.attach(c,result)
                order_workspace.attach(c,result)
                result['current_problem']=row['problem']
                # Versión oficial vigente, para consultarla desde órdenes sin aceptación registrada (no implica que esta orden la haya aceptado).
                active_terms=service_terms.current(c,reception_now());result['terms_current']=service_terms.metadata(active_terms) if active_terms else None
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
                    columns = "o.id,o.code,o.created_at,o.received_at,o.delivered_at,o.problem,o.status status_code,s.label status,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,c.name client,o.priority,o.estimated_delivery,COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'Sin asignar') responsible"
                    search = "COALESCE(o.code,'OP-'||printf('%05d',o.id))||' '||CAST(o.id AS TEXT)||' '||c.name||' '||COALESCE(c.identification,'')||' '||COALESCE(c.phone,'')||' '||COALESCE(c.trade_name,'')||' '||COALESCE(d.category,'')||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')||' '||o.problem||' '||s.label"
                    active = query.get('active', [''])[0] == '1'
                    where = ' AND o.status != \'entregado\'' if active else ''
                    stay_filter = query.get('stay', [''])[0]
                    if stay_filter:
                        if stay_filter!='overdue':return self.reply(400,{'error':'Filtro inválido.'})
                        limit_moment=reception_now()-appointments.timedelta(days=stay.settings(c)['limit'])
                        where += " AND o.status != 'entregado' AND ((COALESCE(o.received_at,'')!='' AND o.received_at<=?) OR (COALESCE(o.received_at,'')='' AND o.created_at<=?))"
                        stay_args=(limit_moment.isoformat(timespec='microseconds'),int(limit_moment.timestamp()))
                    ordering = 'o.id DESC'
                elif path == '/api/clients':
                    source, columns = 'clients c', "c.id,c.name,c.phone,c.phone_secondary,c.email,c.identification,c.document_type,c.trade_name,c.client_type,c.city,c.canton,c.needs_review,c.import_batch_id,(SELECT COUNT(*) FROM orders o JOIN devices d ON d.id=o.device_id WHERE d.client_id=c.id) orders"
                    search = "c.name||' '||COALESCE(c.phone,'')||' '||c.phone_secondary||' '||COALESCE(c.email,'')||' '||c.identification||' '||c.trade_name||' '||c.city"
                    # Orden por columnas: nombre, ciudad u órdenes, en ambos sentidos; por defecto, los más recientes.
                    sort=query.get('sort',[''])[0];descending=query.get('dir',[''])[0]=='desc'
                    last_service="(SELECT MAX(COALESCE(o.delivered_at,o.received_at,'')) FROM orders o JOIN devices d ON d.id=o.device_id WHERE d.client_id=c.id)"
                    orderings={'name':'c.name COLLATE NOCASE','city':"COALESCE(NULLIF(c.city,''),c.canton,'') COLLATE NOCASE",'orders':'orders','id':'c.identification','registered':'c.id','last_service':'COALESCE('+last_service+",'')"}
                    if sort and sort not in orderings:return self.reply(400,{'error':'Orden inválido.'})
                    where, ordering = '', (orderings[sort]+(' DESC' if descending else '')+',c.id DESC') if sort else 'c.id DESC'
                    conditions={'review':'c.needs_review=1','complete':'c.needs_review=0','imported':'c.import_batch_id IS NOT NULL','orders':'EXISTS(SELECT 1 FROM devices d JOIN orders o ON o.device_id=d.id WHERE d.client_id=c.id)','no_orders':'NOT EXISTS(SELECT 1 FROM devices d JOIN orders o ON o.device_id=d.id WHERE d.client_id=c.id)','no_id':"c.identification=''"}
                    chosen=query.get('filter',[''])[0]
                    if chosen:
                        if chosen not in conditions:return self.reply(400,{'error':'Filtro inválido.'})
                        where+=' AND '+conditions[chosen]
                    kind=query.get('type',[''])[0]
                    if kind:
                        if kind not in ('natural','empresa'):return self.reply(400,{'error':'Filtro inválido.'})
                        where+=' AND c.client_type=?';client_kind=kind
                    client_city=query.get('city',[''])[0][:80].strip()
                    if client_city:where+=" AND "+client_registry.fold_sql("COALESCE(NULLIF(c.city,''),c.canton,'')")+"=?"
                else:
                    source = 'devices d JOIN clients c ON c.id=d.client_id'
                    duplicate_sql="(SELECT COUNT(*) FROM devices x WHERE x.id!=d.id AND TRIM(COALESCE(d.serial,''))!='' AND lower(TRIM(COALESCE(x.serial,'')))=lower(TRIM(d.serial)))"
                    columns = "d.id,d.client_id,c.name client,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,d.color,(SELECT COUNT(*) FROM orders o WHERE o.device_id=d.id) orders,(SELECT o.status FROM orders o WHERE o.device_id=d.id ORDER BY o.id DESC LIMIT 1) last_status,(SELECT o.created_at FROM orders o WHERE o.device_id=d.id ORDER BY o.id DESC LIMIT 1) last_at,"+duplicate_sql+" duplicates"
                    search = "c.name||' '||COALESCE(c.identification,'')||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')"
                    where, ordering = '', 'd.id DESC'
                    device_kind=query.get('type',[''])[0]
                    if device_kind:
                        if device_kind not in DEVICE_TYPES:return self.reply(400,{'error':'Tipo de equipo inválido.'})
                        where+=" AND COALESCE(NULLIF(d.kind,''),d.category)=?"
                    if query.get('duplicates',[''])[0]=='1':where+=' AND '+duplicate_sql+'>0'
                args=[term]
                if path == '/api/clients' and query.get('type',[''])[0]:args.append(query['type'][0])
                if path == '/api/clients' and query.get('city',[''])[0].strip():args.append(client_registry.fold(query['city'][0][:80]))
                if path == '/api/devices' and query.get('type',[''])[0]:args.append(query['type'][0])
                if path == '/api/orders':
                    if query.get('stay',[''])[0]:args.extend(stay_args)
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
                if path == '/api/clients':
                    # Búsqueda de clientes sin tildes ni mayúsculas y por varias palabras en cualquier orden (nombre, razón social, nombre comercial,
                    # cédula o RUC, teléfonos, correo y ciudad). Los números también se comparan sin espacios ni guiones.
                    words=[client_registry.fold(word) for word in term.split()][:6] or ['']
                    folded=client_registry.fold_sql(search+"||' '||COALESCE(c.canton,'')")
                    digits="replace(replace(replace(COALESCE(c.phone,'')||' '||c.phone_secondary||' '||c.identification,' ',''),'-',''),'+','')"
                    condition=' WHERE '+' AND '.join('(instr('+folded+',?)>0 OR instr('+digits+',?)>0)' for _ in words)+where
                    args=[value for word in words for value in (word,word.replace('-','').replace('+','') or word)]+args[1:]
                total = c.execute('SELECT COUNT(*) FROM '+source+condition, args).fetchone()[0]
                size=50
                if path=='/api/clients':
                    size=query.get('size',['50'])[0]  # por defecto 50, como siempre; el listado permite elegir 10 o 25
                    if size not in ('10','25','50'):return self.reply(400,{'error':'Tamaño de página inválido.'})
                    size=int(size);page=min(page,max(1,(total+size-1)//size))
                if path=='/api/orders':
                    # El listado completo permite 10, 20 o 50 órdenes por página (50 por defecto, como siempre).
                    size=query.get('size',['50'])[0]
                    if size not in ('10','20','50'):return self.reply(400,{'error':'Tamaño de página inválido.'})
                    size=int(size);page=min(page,max(1,(total+size-1)//size))
                rows = [dict(r) for r in c.execute('SELECT '+columns+' FROM '+source+condition+' ORDER BY '+ordering+' LIMIT ? OFFSET ?', (*args,size,(page-1)*size))]
                if path == '/api/orders':
                    # Permanencia en taller: calculada en el servidor con las fechas guardadas de ingreso y entrega.
                    stay_config=stay.settings(c);stay_now=reception_now()
                    for item in rows:item['stay']=stay.compute(item,stay_now,stay_config)
                if path == '/api/clients':
                    # Indicadores reales del directorio y, en cada ficha por completar, qué datos obligatorios faltan exactamente.
                    counts=c.execute('SELECT COUNT(*) total,COALESCE(SUM(needs_review),0) review FROM clients').fetchone()
                    for item in rows:
                        if item['needs_review']:
                            full=c.execute('SELECT * FROM clients WHERE id=?',(item['id'],)).fetchone();item['missing']=client_registry.missing(full) if full else []
                    cities=[row[0] for row in c.execute("SELECT DISTINCT COALESCE(NULLIF(city,''),canton,'') place FROM clients WHERE COALESCE(NULLIF(city,''),canton,'')!='' ORDER BY place COLLATE NOCASE LIMIT 200")]
                    return self.reply(200, {'rows':rows,'total':total,'page':page,'pages':max(1,(total+size-1)//size),'size':size,'cities':cities,'stats':{'total':counts['total'],'complete':counts['total']-counts['review'],'review':counts['review']}})
                return self.reply(200, {'rows':rows,'total':total,'page':page,'pages':max(1,(total+size-1)//size),'size':size})
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
            if path == '/api/business-hours':
                import business_hours
                config=business_hours.get(c)
                return self.reply(200,{'config':config,'defaults':business_hours.DEFAULTS,'summary':business_hours.public(c,reception_now()),'agenda':adi.schedule_text(appointments.settings(c)['hours']),'can_edit':user['role']=='administrador'})
            if path == '/api/stay/reminders':
                if user['role']!='administrador':return self.reply(403,{'error':'Acceso no permitido.'})
                import stay_reminders
                return self.reply(200,{'reminders':stay_reminders.status(c,reception_now()),'settings':stay.settings(c)})
            if path == '/api/reports':
                counts = [dict(r) for r in c.execute("SELECT s.code,s.label,COUNT(o.id) total FROM statuses s LEFT JOIN orders o ON o.status=s.code GROUP BY s.code ORDER BY CASE s.code WHEN 'pendiente' THEN 1 WHEN 'reparacion' THEN 2 WHEN 'esperando_cliente' THEN 3 WHEN 'presupuesto' THEN 4 WHEN 'espera_entrega' THEN 5 WHEN 'listo' THEN 6 ELSE 7 END")]
                # Centro de Control Técnico: indicadores calculados con las órdenes reales; «group» devuelve las órdenes de un segmento.
                report_query=parse_qs(urlsplit(self.path).query);today=reception_now().date()
                try:
                    report_filters=reports.parse_filters(report_query,today)
                    if report_query.get('group'):return self.reply(200,reports.rows(c,report_filters,today,report_query['group'][0],report_query.get('value',[''])[0]))
                    board=reports.build(c,report_filters,today)
                except reports.ReportError as error:return self.reply(400,{'error':str(error)})
                return self.reply(200, {'board':board,'statuses':counts,'clients':c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],'devices':c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]})
            if path == '/api/settings':
                if user['role'] != 'administrador':
                    return self.reply(403, {'error':'Solo administración puede acceder a la configuración.'})
                labels={'login':'Inicio de sesión','logout':'Cierre de sesión','sessions_revoked':'Cierre de todas las sesiones','other_sessions_revoked':'Cierre de otras sesiones','password_changed':'Cambio de contraseña','password_reset':'Contraseña restablecida','profile_updated':'Perfil actualizado','auth_policy_updated':'Políticas de acceso actualizadas','account_approved':'Cuenta aprobada','account_rejected':'Solicitud rechazada','account_updated':'Cuenta del equipo modificada','clients_exported':'Exportación de clientes','clients_imported':'Importación de clientes'}
                activity=[{'label':labels[r['action']],'at':r['created_at']} for r in c.execute('SELECT action,created_at FROM audit WHERE user_id=? AND action IN ('+','.join('?' for _ in labels)+') ORDER BY id DESC LIMIT 12',(user['id'],*labels))]
                return self.reply(200, {'profile':{k:user[k] for k in ('name','username','email','role')},'me':user['id'],'active_sessions':c.execute('SELECT COUNT(*) FROM sessions WHERE user_id=? AND expires>?',(user['id'],int(time.time()))).fetchone()[0],'security_activity':activity,'registration_enabled':registration_enabled(),'captcha_mode':captcha_mode(),'mail':mail_pro.status(),'mail_signature':mail_signature(c),'mail_signature_card':mail_signature_card(c) if mail_pro.configured() else None,'accounts':[dict(r) for r in c.execute("SELECT u.id,u.name,u.username,u.email,u.role,u.active,(SELECT MAX(a.created_at) FROM audit a WHERE a.user_id=u.id AND a.action='login') last_login,(SELECT COUNT(*) FROM sessions s WHERE s.user_id=u.id AND s.expires>?) sessions FROM users u WHERE u.approval='approved' ORDER BY u.id",(int(time.time()),))],'requests':[dict(r) for r in c.execute("SELECT id,name,username,email,phone,identification,job_title,requested_at,approval FROM users WHERE approval IN ('pending','rejected') ORDER BY approval,id DESC")],'smtp_configured':bool(security_mail_ready()),'smtp_route':security_mail_ready(),'openai_configured':bool(os.getenv('OPENAI_API_KEY')),'login_lockout_seconds':auth_policy(c)['lockout_seconds'],'auth_policy':auth_policy(c),'antibot_configured':bool(os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY')),'origin':os.getenv('APP_URL','http://127.0.0.1:8010')})
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
            if path == '/api/assistance':
                # Estado del Centro de Atenciones para el inicio: contadores sin solapes y atenciones que requieren respuesta. Solo administración.
                if user['role']!='administrador':return self.reply(403,{'error':'Acceso no permitido.'})
                return self.reply(200,live_support.summary(c))
            if path == '/api/catalog':
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                query=parse_qs(urlsplit(self.path).query)
                category=query.get('category',[''])[0]
                logos={f.stem:f.name for f in sorted((ROOT/'static'/'brands').glob('*')) if f.suffix in ('.svg','.png') and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',f.stem)}
                names={name.lower() for name,*_ in quotes.INITIAL};present={r['name'].lower() for r in c.execute('SELECT name FROM catalog_items')}
                return self.reply(200,{'rows':quotes.catalog(c,query.get('q',[''])[0][:80],query.get('all',[''])[0]!='1',category if category in quotes.CATEGORIES else ''),'categories':quotes.CATEGORIES,'price_modes':quotes.PRICE_MODES,
                    'tax_rate_bp':quotes.tax_rate(c),'can_edit':user['role']=='administrador','brand_logos':logos,'initial_missing':len(names-present)})
            catalog_extra=re.fullmatch(r'/api/catalog/([0-9]{1,9})/(image|history)',path)
            if catalog_extra:
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                if catalog_extra[2]=='history':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración consulta el historial de precios.'})
                    return self.reply(200,{'rows':quotes.price_history(c,int(catalog_extra[1]))})
                picture=c.execute('SELECT mime,data FROM catalog_images WHERE item_id=?',(int(catalog_extra[1]),)).fetchone()
                if not picture:return self.reply(404,{'error':'Sin imagen.'})
                return self.reply(200,bytes(picture['data']),picture['mime'])
            quote_get=re.fullmatch(r'/api/(?:orders/([0-9]+)/quote|quotes/([0-9]+)(/pdf)?)',path)
            if quote_get:
                if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                try:
                    if quote_get[1]:
                        quotes.order_code(c,int(quote_get[1]));return self.reply(200,dict(quotes.for_order(c,int(quote_get[1])),can_manage=user['role']=='administrador'))
                    found=quotes.get(c,int(quote_get[2]))
                    if quote_get[3]:
                        import quote_pdf
                        return self.reply(200,quote_pdf.render(quotes.detail(c,found),order_document(c,found['order_id'])),'application/pdf',filename=found['code']+'-PRESUPUESTO.pdf')
                    return self.reply(200,{'quote':quotes.detail(c,found)})
                except quotes.QuoteError as error:return self.reply(error.status,{'error':str(error)})
            if path == '/api/tracking':
                # Seguimiento de Órdenes: una tarjeta por orden con su último movimiento; solo lectura, para cualquier usuario con sesión.
                import tracking_board
                try:return self.reply(200,dict(tracking_board.build(c,tracking_board.parse(parse_qs(urlsplit(self.path).query))),server_time=reception_now().isoformat(timespec='seconds')))
                except tracking_board.TrackingError as error:return self.reply(400,{'error':str(error)})
            tracking_history=re.fullmatch(r'/api/tracking/([0-9]+)',path)
            if tracking_history:
                import tracking_board
                if not c.execute('SELECT 1 FROM orders WHERE id=?',(int(tracking_history[1]),)).fetchone():return self.reply(404,{'error':'Orden no disponible.'})
                return self.reply(200,{'rows':tracking_board.history(c,int(tracking_history[1]))})
            if path in ('/api/dashboard','/api/activity','/api/maintenance'):
                now=reception_now();today=now.date().isoformat()
                if path=='/api/maintenance':
                    import maintenance_reminders
                    return self.reply(200,{'rows':maintenance.rows(c),'today':today,'profiles':{k:v[0] for k,v in maintenance.PROFILES.items()},'reminders':maintenance_reminders.status(c,now.date())})
                if path=='/api/dashboard':maintenance_reminders_tick(c,now);stay_reminders_tick(c,now)
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
                    assistance=live_support.summary(c)
                return self.reply(200,{'counts':counts,'attention':attention,'activity':activity,'maintenance':scheduled,'deliveries':deliveries,'today':today,'appointments':today_appointments,'pending_chats':pending_chats,'assistance':assistance,'upcoming_appointments':c.execute("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status IN ('solicitada','confirmada','reprogramada') AND starts_at>=?",(appointments.stamp(now),)).fetchone()[0] if user['role'] in ('administrador','tecnico') else 0,'pending_accounts':c.execute("SELECT COUNT(*) FROM users WHERE approval='pending'").fetchone()[0] if user['role']=='administrador' else 0,'pending_appointments':c.execute("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status='solicitada' AND starts_at>=?",(appointments.stamp(now),)).fetchone()[0] if user['role'] in ('administrador','tecnico') else 0})
            search_route=path=='/api/search'
            if search_route:
                term=parse_qs(urlsplit(self.path).query).get('q',[''])[0].strip()[:150]
                if len(term)<2:return self.reply(200,{'rows':[]})
                # Vista rápida del buscador: hasta 8 órdenes (el código exacto primero), sin distinguir tildes y tolerando errores de escritura.
                return self.reply(200,order_search.find(c,term))
            maintenance_pdf=re.fullmatch(r'/api/maintenance/([0-9]+)/(card|thermal)\.pdf',path)
            if maintenance_pdf:
                row=next((r for r in maintenance.rows(c) if r['id']==int(maintenance_pdf[1])),None)
                if not row:return self.reply(404,{'error':'Mantenimiento no disponible.'})
                try:return self.reply(200,maintenance.card(row,maintenance_pdf[2]=='thermal'),'application/pdf')
                except ValueError as error:return self.reply(400,{'error':str(error)})
        return self.reply(404, {'error':'Recurso no disponible.'})

    def do_POST(self):
        maintenance_post=re.fullmatch(r'/mantenimiento/([A-Za-z0-9_-]{40,60})',urlsplit(self.path).path)
        if maintenance_post:
            import maintenance_reminders
            try:length=int(self.headers.get('Content-Length','0') or 0)
            except ValueError:length=0
            if length<=0 or length>4000:return self.reply(400,{'error':'Solicitud inválida.'})
            form={key:values[0] for key,values in parse_qs(self.rfile.read(length).decode('utf-8','replace'),keep_blank_values=True).items()}
            with connect() as c:
                if limited(c,'maint-post:'+digest(maintenance_post[1]),20,900):return self.reply(429,{'error':'Demasiados intentos. Intenta más tarde.'})
                found=maintenance_reminders.lookup(c,maintenance_post[1])
                if not found:return self.reply(404,maintenance_reminders.missing_page(),'text/html; charset=utf-8')
                notice=maintenance_reminders.respond(c,found,form.get('action',''),form.get('note',''),reception_now())
                if notice is None:return self.reply(400,maintenance_reminders.page(found,maintenance_post[1],error='Elija una de las opciones.'),'text/html; charset=utf-8')
                return self.reply(200,maintenance_reminders.page(found,maintenance_post[1],notice=notice),'text/html; charset=utf-8')
        quote_post_public=re.fullmatch(r'/presupuesto/([A-Za-z0-9_-]{30,80})',urlsplit(self.path).path)
        if quote_post_public:
            try:length=int(self.headers.get('Content-Length','0') or 0)
            except ValueError:length=0
            if length<=0 or length>120000:return self.reply(400,{'error':'Solicitud inválida.'})
            form={key:values[0] for key,values in parse_qs(self.rfile.read(length).decode('utf-8','replace'),keep_blank_values=True).items()}
            token=quote_post_public[1]
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if limited(c,'quote-post:'+digest(token),30,900) or limited(c,'quote-ip:'+digest(self.client_address[0]),60,300):
                    c.commit();return self.reply(429,{'error':'Demasiados intentos. Intenta más tarde.'})
                now=reception_now();quote,link=quotes.lookup(c,token,now)
                if not quote:
                    c.commit();return self.reply(404,quotes.missing_page(),'text/html; charset=utf-8')
                document=order_document(c,quote['order_id'])
                forwarded=(self.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
                page,status=quotes.handle(c,token,quote,link,document,form,now,{'ip':(forwarded or self.client_address[0])[:60],'agent':(self.headers.get('User-Agent') or '')[:160]})
                if status:
                    # La decisión queda en el historial de la orden. No cambia el estado de la orden ni inicia trabajos.
                    order_workspace.event(c,quote['order_id'],None,now,'follow_up','Presupuesto '+quote['code']+': '+{'aprobado':'aprobado por el cliente','parcial':'aprobado parcialmente por el cliente','rechazado':'rechazado por el cliente','modificacion':'el cliente solicitó una modificación'}[status]+'.')
                    audit(c,None,'quote_client_'+status,quote['order_id'])
                c.commit()
            return self.reply(200,page,'text/html; charset=utf-8')
        authorize_post=re.fullmatch(r'/autorizar/([A-Za-z0-9_-]{20,80})',urlsplit(self.path).path)
        if authorize_post:
            import client_authorization
            try:length=int(self.headers.get('Content-Length','0') or 0)
            except ValueError:length=0
            if length<=0 or length>20000:return self.reply(400,{'error':'Solicitud inválida.'})
            form={key:values[0] for key,values in parse_qs(self.rfile.read(length).decode('utf-8','replace'),keep_blank_values=True).items()}
            token=authorize_post[1]
            with connect() as c:
                if limited(c,'cauth-post:'+digest(token),40,900) or limited(c,'cauth-ip:'+digest(self.client_address[0]),60,300):return self.reply(429,{'error':'Demasiados intentos. Intenta más tarde.'})
                now=reception_now();found=client_authorization.lookup(c,token,now)
                if not found:return self.reply(404,client_authorization.missing_page(),'text/html; charset=utf-8')
                document=order_document(c,found['order_id']);active=service_terms.current(c,now);terms=dict(active) if active else None
                def send_code(recipient,code):
                    # El código queda guardado antes de enviarlo; se envía solo al correo registrado en la orden.
                    c.commit()
                    try:send_verification_code(recipient,code,client_authorization.CODE_MINUTES,'en la página de autorización de tu orden','Autorización de la orden N.º '+document['code'])
                    except Exception:
                        with connect() as log:audit(log,None,'verification_code_failed',found['order_id'])
                        raise
                    with connect() as log:audit(log,None,'verification_code_sent',found['order_id'])
                forwarded=(self.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
                page,signed=client_authorization.handle(c,token,found,document,form,now,{'ip':(forwarded or self.client_address[0])[:60],'agent':(self.headers.get('User-Agent') or '')[:160]},send_code,terms)
                if signed:
                    state=client_authorization.summary(c,found['order_id']);decisions=state['evidence']['decisions']
                    order_workspace.event(c,found['order_id'],None,now,'follow_up','Autorización electrónica del cliente registrada: '+('servicio autorizado' if decisions['service']=='authorized' else 'servicio NO autorizado')+'.')
                    c.commit();notice='not_configured'
                    try:
                        if mail_pro.configured():
                            labels=dict((key,title) for key,title,_ in client_authorization.ITEMS);config=mail_pro.settings()
                            body='\n'.join(['PC-DOCTOR S.A. — Autorización del cliente recibida','','Orden: '+document['code'],'Cliente: '+document['client'],'Equipo: '+' '.join(part for part in (document.get('brand') or '',document.get('model') or '') if part),'Estado: '+state['status_label'],'Fecha: '+now.strftime('%d/%m/%Y %H:%M')+' (Ecuador)','']
                                +[labels[key]+': '+('AUTORIZADO' if value=='authorized' else 'NO AUTORIZADO') for key,value in client_authorization.ordered(decisions)]
                                +(['','Observaciones del cliente: '+state['evidence']['comment']] if state['evidence'].get('comment') else [])
                                +['','Condiciones: '+(state['evidence']['terms']['title']+', versión '+state['evidence']['terms']['version'] if state['evidence'].get('terms') else 'sin condiciones publicadas en la fecha de la firma'),'Huella de la evidencia: '+state['evidence_hash'],'','Consultar la autorización (requiere iniciar sesión en Órdenes Pro):',public_base_url().rstrip('/')+'/#orders?id='+str(found['order_id'])])
                            message,recipients=mail_pro.build_message(config,{'to':config['username'],'subject':'PC-DOCTOR S.A. | Autorización del cliente — Orden N.º '+document['code'],'body':body,'from_name':corporate.settings()['name']},'')
                            mail_pro.deliver(config,message,recipients);notice='sent'
                    except Exception as error:
                        print('client-authorization-notice',type(error).__name__,flush=True);notice='failed'
                    c.execute('UPDATE client_authorizations SET notice_result=? WHERE id=?',(notice,found['id']))
                return self.reply(200,page,'text/html; charset=utf-8')
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
            workspace_post=bool(re.fullmatch(r'/api/orders/[0-9]+/workspace',path));quote_json=bool(re.fullmatch(r'/api/quotes/[0-9]+',path))
            max_body=9000000 if path in ('/api/clients/import/preview','/api/clients/import/commit') else 6000000 if path in ('/api/mail/send','/api/mail/draft') else 100000 if path in ('/api/conditions','/api/order-draft','/api/conditions/draft','/api/conditions/compare') else 900000 if re.fullmatch(r'/api/orders/[0-9]+/photos',path) or path=='/api/profile/photo' or re.fullmatch(r'/api/catalog/[0-9]+/image',path) else (65536 if workspace_post or quote_json else 16384)
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > max_body:
                return self.reply(400, {'error':'Solicitud inválida.'})
            data = json.loads(self.rfile.read(length))
            appointment_config_post=path=='/api/appointments/config'
            if not isinstance(data, dict) or any(not isinstance(v,(str,bool)) and not (quote_json and k=='items' and isinstance(v,list)) and not (workspace_post and ((k=='lines' and isinstance(v,list)) or (k=='revision' and type(v) is int))) and not (appointment_config_post and ((k in ('hours','services','staff_hours') and isinstance(v,list)) or (k in ('holiday','new_service') and isinstance(v,dict)))) and not (path=='/api/business-hours' and k in ('hours','closures','request_limits') and isinstance(v,list)) for k,v in data.items()):
                return self.reply(400, {'error':'Datos inválidos.'})
            path = urlsplit(self.path).path
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if path == '/api/public/appointments':
                    if limited(c,'appointment-ip:'+digest(self.client_address[0]),12,900):return self.reply(429,{'error':'Demasiadas solicitudes. Intenta más tarde.'})
                    key=str(data.get('request_key','')).strip()
                    if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',key):return self.reply(400,{'error':'Actualiza el formulario e inténtalo nuevamente.'})
                    # Hora límite del día para solicitar citas en línea (regla aparte del horario presencial y de la disponibilidad de técnicos).
                    import business_hours
                    accepting,notice=business_hours.requests_open(business_hours.get(c),reception_now())
                    if not accepting:return self.reply(409,{'error':notice,'requests_closed':True})
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
                if path == '/api/public/adi/order/request':
                    # Consulta de reparación: el código viaja solo al correo registrado. La respuesta no revela si la orden existe.
                    import order_check
                    ip=digest(self.client_address[0]);wanted=str(data.get('order','')).strip()[:40]
                    if not wanted:return self.reply(400,{'error':'Escribe el número de orden que consta en tu comprobante.'})
                    if limited(c,'order-check-ip:'+ip,5,600) or limited(c,'order-check-order:'+digest(wanted.upper()),3,1800):return self.reply(429,{'error':'Demasiadas solicitudes de código. Espera unos minutos e inténtalo de nuevo.'})
                    try:ready=mail_pro.configured()
                    except mail_pro.MailError:ready=False
                    if not ready:return self.reply(503,{'error':'La consulta en línea no está disponible en este momento. Puedes solicitar un asesor.'})
                    token,mail=order_check.start(c,wanted,reception_now())
                    # El envío espera al servidor de correo: el reto se confirma antes para no retener la base.
                    c.commit()
                    if mail:
                        # Se registra el envío o el fallo, nunca el código.
                        try:send_verification_code(mail['email'],mail['code'],order_check.CODE_MINUTES,'en el chat de ADI donde lo solicitaste','Consulta de la orden N.º '+mail['order']);outcome='verification_code_sent'
                        except Exception as error:print('order-check-mail',type(error).__name__,flush=True);outcome='verification_code_failed'
                        audit(c,None,outcome,mail['order_id'])
                    else:time.sleep(1.2)
                    return self.reply(200,{'ok':True,'token':token,'message':order_check.NOTICE,'minutes':order_check.CODE_MINUTES})
                if path == '/api/public/adi/order/verify':
                    import order_check
                    if limited(c,'order-verify-ip:'+digest(self.client_address[0]),15,600):return self.reply(429,{'error':'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.'})
                    found=order_check.verify(c,str(data.get('token','')),str(data.get('code','')).strip(),reception_now())
                    if not found:return self.reply(400,{'error':'El código no es correcto o ya caducó. Revisa el correo o solicita uno nuevo.'})
                    audit(c,None,'order_checked_by_client',found.pop('id'))
                    return self.reply(200,{'ok':True,'order':found})
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
                        # Una conversación finalizada se reanuda con ADI cuando el cliente vuelve a escribir; el historial se conserva.
                        c.execute("UPDATE adi_conversations SET mode='adi',assigned_to=NULL,updated_at=? WHERE id=?",(now,conv['id']));conv=c.execute('SELECT * FROM adi_conversations WHERE id=?',(conv['id'],)).fetchone()
                    c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client',?,?)",(conv['id'],text,now))
                    answer='Un asesor de PC-DOCTOR S.A. revisará tu solicitud.' if conv['mode']=='human' and not conv['assigned_to'] else None  # Con un asesor conectado, ADI no interviene.
                    context=None
                    # El estado de una orden no se entrega por el chat: exige el código temporal enviado al correo registrado.
                    if conv['mode']=='adi' and re.search(r'PCD-\d{8}-\d{3,}',text,re.I):answer=adi.ORDER_CHECK_HINT
                    if answer is None and conv['mode']=='adi':
                        # El mensaje del cliente queda guardado antes de consultar a la IA, para no retener la base durante la espera.
                        c.commit();answer=adi.reply(c,text,context=context)
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
                    if not conv:return self.reply(404,{'error':'Inicia una conversación con ADI primero.'})
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
                    # Límites: usuario hasta 50 caracteres, correo hasta 254 y contraseña hasta 256 (las existentes no se truncan ni se rechazan).
                    if not login or not password or len(login)>(LOGIN_EMAIL_MAX if '@' in login else LOGIN_USER_MAX) or len(password)>PASSWORD_LOGIN_MAX or ('@' in login and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',login)):
                        return self.reply(400,{'error':'Completa un usuario o correo válido y tu contraseña.'})
                    account_hash=digest(login.casefold());ip_hash=digest(self.client_address[0]);ip_key='login-ip:'+ip_hash;user_key='login-user:'+account_hash
                    # Campo trampa: las personas no lo ven; un envío automatizado que lo rellena se trata como intento fallido, sin dar pistas.
                    if str(data.get('website','')).strip():
                        limited(c,ip_key,limit=4,window=auth_policy(c)['lockout_seconds']);auth_event(c,account_hash,ip_hash,'failed');audit(c,None,'login_bot_suspected')
                        return self.reply(401, {'error':'No pudimos iniciar sesión. Verifica tus credenciales e inténtalo nuevamente.'})
                    blocked_ip=limit_reached(c,ip_key);blocked_user=limit_reached(c,user_key)
                    if blocked_ip or blocked_user:
                        auth_event(c,account_hash,ip_hash,'limited')
                        audit(c,None,'login_rate_limited')
                        return self.reply(429, {'error':'Por seguridad, el acceso está temporalmente limitado. Inténtalo más tarde o recupera tu contraseña.'})
                    # Espera progresiva tras fallos consecutivos: el intento no se evalúa ni cuenta hasta que termine.
                    waiting=login_wait(c,(user_key,ip_key))
                    if waiting:
                        return self.reply(429,{'error':'Por seguridad, espera %d segundos antes de volver a intentarlo.'%waiting,'retry_after':waiting})
                    # Verificación adicional solo cuando hace falta (fallos recientes): prueba de trabajo de un solo uso que el navegador resuelve sin intervención.
                    if captcha_mode()=='local' and (captcha_always() or login_risky(c,(user_key,ip_key))) and not verify_captcha(c,str(data.get('bot_token',''))):
                        return self.reply(403,{'error':'Comprobando la seguridad del acceso…','challenge':True,'silent':True})
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
                        for key in (user_key,ip_key):
                            fails=(c.execute('SELECT count FROM attempts WHERE bucket=?',(key,)).fetchone() or [0])[0]
                            if fails in LOGIN_WAITS:c.execute('INSERT INTO attempts VALUES (?,0,?) ON CONFLICT(bucket) DO UPDATE SET expires=excluded.expires',('wait:'+key,int(time.time())+LOGIN_WAITS[fails]))
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
                    # El alta pública se retiró: las cuentas se crean en /api/users/create, solo por administración.
                    audit(c,None,'public_registration_blocked')
                    return self.reply(404,{'error':'El registro de cuentas no está disponible.'})
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
                    elif os.getenv('VERCEL'):
                        # Misma espera aproximada cuando no hay nada que enviar: la latencia no revela si la cuenta existe.
                        c.commit();time.sleep(1.3+secrets.randbelow(900)/1000)
                    return self.reply(200, {'ok':True,'message':'Si el correo está asociado a una cuenta, recibirás las instrucciones para restablecer tu contraseña.'})
                if path == '/api/reset':
                    if limited(c, 'reset-use:'+digest(self.client_address[0]), 10):
                        return self.reply(429, {'error':'Demasiados intentos. Intenta más tarde.'})
                    password = str(data.get('password',''))
                    minimum=auth_policy(c)['password_min']
                    if not minimum <= len(password) <= PASSWORD_MAX:
                        return self.reply(400, {'error':f'Usa una contraseña de {minimum} a {PASSWORD_MAX} caracteres.'})
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
                    if c.execute("SELECT 1 FROM audit WHERE action='account_created' AND entity_id=?",(row['user_id'],)).fetchone() and not c.execute("SELECT 1 FROM audit WHERE action='account_activated' AND entity_id=?",(row['user_id'],)).fetchone():audit(c,None,'account_activated',row['user_id'])
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
                    # Las operaciones de correo esperan a un servidor externo (IMAP/SMTP): se libera antes la base para no bloquear otros guardados.
                    c.commit()
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
                    if not minimum<=len(password)<=PASSWORD_MAX:return self.reply(400,{'error':'Revisa los campos señalados.','fields':{'password':f'Usa una contraseña de {minimum} a {PASSWORD_MAX} caracteres.'}})
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
                if path=='/api/users/create':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede crear cuentas.'})
                    if limited(c,'user-create:'+str(user['id']),limit=20,window=3600):return self.reply(429,{'error':'Demasiadas cuentas creadas en poco tiempo. Inténtalo más tarde.'})
                    name=re.sub(r'\s+',' ',str(data.get('name',''))).strip();email=str(data.get('email','')).strip();username=str(data.get('username','')).strip();role=str(data.get('role','tecnico'));errors={}
                    if not 3<=len(name)<=150:errors['name']='Escribe los nombres y apellidos.'
                    if len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):errors['email']='Introduce un correo electrónico válido.'
                    if username and not re.fullmatch(r'[a-zA-Z0-9_.-]{3,50}',username):errors['username']='Usa de 3 a 50 letras, números, punto, guion o guion bajo.'
                    if role not in ('administrador','tecnico'):errors['role']='Elige un rol válido.'
                    if not errors and c.execute('SELECT 1 FROM users WHERE lower(email)=lower(?)',(email,)).fetchone():errors['email']='Ya existe una cuenta con ese correo.'
                    if not errors and username and c.execute('SELECT 1 FROM users WHERE lower(username)=lower(?)',(username,)).fetchone():errors['username']='Ese nombre de usuario ya está en uso.'
                    if errors:return self.reply(400,{'error':'Revisa los campos señalados.','fields':errors})
                    if not username:
                        # Usuario derivado del correo; si ya existe se le añade un número.
                        stem=(re.sub(r'[^a-zA-Z0-9_.-]','',email.split('@')[0])[:44] or 'usuario').ljust(3,'0');username=stem;number=1
                        while c.execute('SELECT 1 FROM users WHERE lower(username)=lower(?)',(username,)).fetchone():number+=1;username=stem+str(number)
                    # Contraseña inicial aleatoria que nadie conoce: la persona elige la suya desde el enlace de invitación.
                    now_ts=int(time.time())
                    uid=c.execute("INSERT INTO users(username,email,name,password_hash,role,active,created_at,approval,requested_at,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,1,?,'approved',?,?,?)",(username,email,name,password_hash(secrets.token_urlsafe(48)),role,now_ts,now_ts,user['id'],now_ts)).lastrowid
                    appointments.ensure_staff_hours(c,uid);audit(c,user['id'],'account_created',uid)
                    try:result,link=deliver_access(c,uid,email,name,True)
                    except RuntimeError:result,link='unavailable',''
                    with connect() as log:audit(log,user['id'],'account_invitation_'+result,uid)
                    return self.reply(201,{'ok':True,'id':uid,'username':username,'mail':result,'link':link,'hours':INVITE_HOURS})
                if path=='/api/users/access':
                    # Restablecer el acceso de una cuenta: enlace temporal nuevo; la contraseña anterior deja de servir cuando la persona elige otra.
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede restablecer accesos.'})
                    if limited(c,'user-access:'+str(user['id']),limit=20,window=3600):return self.reply(429,{'error':'Demasiados enlaces generados. Inténtalo más tarde.'})
                    target=str(data.get('id',''));row=c.execute("SELECT id,email,name,active FROM users WHERE id=? AND approval='approved'",(target,)).fetchone() if target.isdigit() else None
                    if not row or not row['active']:return self.reply(400,{'error':'La cuenta no está disponible o está desactivada.'})
                    if row['id']==user['id']:return self.reply(400,{'error':'Para tu propia cuenta usa «Cambiar contraseña».'})
                    audit(c,user['id'],'account_access_reset',row['id'])
                    try:result,link=deliver_access(c,row['id'],row['email'],row['name'],False)
                    except RuntimeError:result,link='unavailable',''
                    return self.reply(200,{'ok':True,'mail':result,'link':link,'hours':INVITE_HOURS})
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
                if path=='/api/client-log':
                    # Registro de diagnóstico del navegador: tipo y mensaje del fallo, nunca el texto que escribe el usuario.
                    # Además del registro del servidor (que caduca pronto) se guarda en la base durante 14 días para poder investigarlo después.
                    if not limited(c,'client-log:'+str(user['id']),limit=240,window=3600):
                        kind=re.sub(r'[^\w .:@/()·+#=,-]','?',str(data.get('kind',''))[:40]);message=re.sub(r'[\r\n]+',' ',str(data.get('message',''))[:300]);place=str(data.get('where',''))[:60]
                        print('client-log','user=%d'%user['id'],kind,'|',message,'|',place,flush=True)
                        try:
                            now=reception_now()
                            c.execute('INSERT INTO client_diagnostics(user_id,kind,message,place,created_at) VALUES (?,?,?,?,?)',(user['id'],kind,message,place,now.isoformat(timespec='seconds')))
                            c.execute('DELETE FROM client_diagnostics WHERE created_at<?',((now-appointments.timedelta(days=14)).isoformat(timespec='seconds'),))
                        except Exception as error:print('client-diagnostics',type(error).__name__,flush=True)
                    return self.reply(200,{'ok':True})
                if path=='/api/order-draft':
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if data.get('action')=='discard':
                        gone=order_drafts.discard(c,user,reception_now())
                        if gone:audit(c,user['id'],'order_draft_discarded')
                        return self.reply(200,{'ok':True,'discarded':gone})
                    if limited(c,'order-draft:'+str(user['id']),limit=240,window=3600):return self.reply(429,{'error':'Demasiados guardados seguidos. Espera un momento.'})
                    status,payload=order_drafts.save(c,user,data.get('data'),data.get('revision',''),data.get('force') is True,reception_now())
                    return self.reply(status,payload)
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
                    status,payload=live_support.act(c,conv,user,data,appointments.stamp(appointments.now()))
                    if status==200:audit(c,user['id'],'adi_conversation_'+str(data.get('action')),conv['id'])
                    return self.reply(status,payload)
                if path == '/api/logout':
                    c.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))
                    audit(c, user['id'], 'logout_idle' if data.get('reason')=='idle' else 'logout')
                    return self.reply(200, {'ok':True}, cookie=self.cookie('',0))
                if path == '/api/session/activity':
                    # Lo llama el navegador solo tras actividad real (teclado, clics, navegación) o al pulsar «Continuar sesión».
                    c.execute('UPDATE sessions SET last_activity=? WHERE token_hash=?',(int(time.time()),digest(token)))
                    return self.reply(200,{'ok':True,'idle_seconds':IDLE_SECONDS,'warning_seconds':IDLE_WARNING})
                if path=='/api/maintenance/reminders':
                    import maintenance_reminders
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede gestionar los recordatorios.'})
                    now=reception_now()
                    if data.get('enabled') in (True,False):
                        c.execute("INSERT INTO system_state(key,value) VALUES ('maintenance_reminders',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('on' if data['enabled'] else 'off',))
                        audit(c,user['id'],'maintenance_reminders_'+('on' if data['enabled'] else 'off'))
                    elif data.get('action')=='run':
                        if not maintenance_reminders.enabled(c):return self.reply(409,{'error':'Activa primero los recordatorios automáticos.'})
                        try:ready=mail_pro.configured()
                        except mail_pro.MailError:ready=False
                        if not ready:return self.reply(409,{'error':'El correo del sistema no está configurado.'})
                        if limited(c,'maint-run:'+str(user['id']),limit=12,window=3600):return self.reply(429,{'error':'Espera antes de volver a enviar.'})
                        summary=maintenance_reminders.run(c,now,maintenance_deliver);audit(c,user['id'],'maintenance_reminders_run')
                        return self.reply(200,{'ok':True,'summary':summary,'reminders':maintenance_reminders.status(c,now.date())})
                    elif data.get('action')=='handled' and str(data.get('id','')).isdigit():
                        c.execute("UPDATE maintenance_responses SET handled_at=?,handled_by=? WHERE id=? AND handled_at=''",(now.isoformat(timespec='seconds'),user['id'],int(data['id'])))
                    else:return self.reply(400,{'error':'Acción no disponible.'})
                    return self.reply(200,{'ok':True,'reminders':maintenance_reminders.status(c,now.date())})
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
                catalog_image=re.fullmatch(r'/api/catalog/([0-9]{1,9})/image',path)
                if path=='/api/catalog/seed' or catalog_image:
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede modificar el catálogo.'})
                    try:
                        if catalog_image:
                            if data.get('action')=='delete':
                                c.execute('DELETE FROM catalog_images WHERE item_id=?',(int(catalog_image[1]),));audit(c,user['id'],'catalog_image_removed',int(catalog_image[1]));return self.reply(200,{'ok':True,'image':''})
                            try:content=base64.b64decode(str(data.get('data','')),validate=True)
                            except Exception:return self.reply(400,{'error':'La imagen no se pudo leer.'})
                            stamp=quotes.save_image(c,int(catalog_image[1]),content,user,reception_now());audit(c,user['id'],'catalog_image_saved',int(catalog_image[1]))
                            return self.reply(200,{'ok':True,'image':stamp})
                        # Catálogo inicial entregado por la administración: se registra una sola vez; lo que ya existe no se duplica ni se modifica.
                        result=quotes.seed_initial(c,user,reception_now());audit(c,user['id'],'catalog_seeded')
                        return self.reply(200,dict(result,ok=True))
                    except quotes.QuoteError as error:return self.reply(error.status,{'error':str(error),'fields':error.fields})
                if path in ('/api/catalog','/api/catalog/tax'):
                    # Catálogo de servicios y productos: solo administración. Cambiar un precio no altera los presupuestos ya emitidos.
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede modificar el catálogo.'})
                    try:
                        if path.endswith('/tax'):
                            rate=quotes.set_tax_rate(c,data.get('tax',''));audit(c,user['id'],'quote_tax_updated');return self.reply(200,{'ok':True,'tax_rate_bp':rate})
                        item=quotes.save_catalog_item(c,data,user,reception_now());audit(c,user['id'],'catalog_item_saved',item)
                        return self.reply(200,{'ok':True,'id':item})
                    except quotes.QuoteError as error:return self.reply(error.status,{'error':str(error),'fields':error.fields})
                quote_route=re.fullmatch(r'/api/(?:orders/([0-9]+)/quote|quotes/([0-9]+))',path)
                if quote_route:
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    now=reception_now()
                    try:
                        if quote_route[1]:
                            created=quotes.create(c,int(quote_route[1]),user,now);audit(c,user['id'],'quote_created',int(quote_route[1]))
                            return self.reply(201,{'ok':True,'id':created})
                        found=quotes.get(c,int(quote_route[2]));action=str(data.get('action',''))
                        if action=='save':
                            quotes.save(c,found,data,user,now);audit(c,user['id'],'quote_saved',found['order_id'])
                            return self.reply(200,{'ok':True,'quote':quotes.detail(c,quotes.get(c,found['id']))})
                        # Enviar, decidir en nombre del cliente, cancelar y versionar son acciones de administración, siempre registradas.
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede enviar, decidir o cancelar presupuestos.'})
                        if action=='version':
                            created=quotes.create(c,found['order_id'],user,now);audit(c,user['id'],'quote_created',found['order_id'])
                            return self.reply(201,{'ok':True,'id':created})
                        if action=='cancel':
                            quotes.cancel(c,found,user,now,str(data.get('reason','')).strip());audit(c,user['id'],'quote_cancelled',found['order_id'])
                            return self.reply(200,{'ok':True,'quote':quotes.detail(c,quotes.get(c,found['id']))})
                        if action=='decide':
                            approved={int(v) for v in str(data.get('approved','')).split(',') if v.isdigit()};rejected={int(v) for v in str(data.get('rejected','')).split(',') if v.isdigit()}
                            note=str(data.get('note','')).strip()
                            if len(note)<5:return self.reply(400,{'error':'Indica cómo comunicó el cliente su decisión (por ejemplo: «aprobó por teléfono»).','fields':{'note':'Nota obligatoria.'}})
                            status=quotes.decide(c,found,{**{i:'aprobado' for i in approved},**{i:'rechazado' for i in rejected-approved}},now,user,note='Registrado por el personal: '+note[:300])
                            order_workspace.event(c,found['order_id'],user['id'],now,'follow_up','Presupuesto '+found['code']+': decisión registrada por el personal ('+quotes.STATUS[status].lower()+').')
                            audit(c,user['id'],'quote_staff_'+status,found['order_id'])
                            return self.reply(200,{'ok':True,'quote':quotes.detail(c,quotes.get(c,found['id']))})
                        if action=='send':
                            document=order_document(c,found['order_id']);email=(document.get('email') or '').strip()
                            if not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+',email):return self.reply(409,{'error':'El cliente no tiene un correo electrónico válido registrado. Complétalo en su ficha.'})
                            if len(re.sub(r'\D','',str(document.get('identification') or '')))<6:return self.reply(409,{'error':'El cliente no tiene una identificación registrada con la que comprobar su identidad.'})
                            token=quotes.send(c,found,email,user,now);link=public_base_url().rstrip('/')+'/presupuesto/'+token
                            order_workspace.event(c,found['order_id'],user['id'],now,'follow_up','Presupuesto '+found['code']+' enviado al cliente para su aprobación.')
                            audit(c,user['id'],'quote_sent',found['order_id'])
                            # El presupuesto queda enviado y su enlace creado antes de intentar el correo: si el envío falla, el enlace se puede compartir por otro medio.
                            c.commit();result='not_configured'
                            try:
                                if mail_pro.configured():
                                    detail=quotes.detail(c,quotes.get(c,found['id']));config=mail_pro.settings();card=mail_signature_card(c)
                                    body='\n'.join(['Estimado/a '+document['client']+':','','Le enviamos el presupuesto N.º '+found['code']+' correspondiente a su orden de servicio '+document['code']+'.','',
                                        'Total cotizado: '+quotes.usd(detail['totals']['quoted'])+' (impuestos incluidos).']+(['Válido hasta el '+appointments.date.fromisoformat(detail['valid_until']).strftime('%d/%m/%Y')+'.'] if detail['valid_until'] else [])+['',
                                        'Para revisar el detalle y aprobar o rechazar cada servicio, ingrese al siguiente enlace privado:',link,'',
                                        'Por su seguridad se le pedirán los últimos cuatro dígitos de su cédula o RUC. El enlace es personal: no lo reenvíe.','',
                                        'No se ejecutará ningún trabajo sin su autorización.','','Atentamente,','','Departamento de Servicio Técnico','PC-DOCTOR S.A.'])
                                    message,recipients=mail_pro.build_message(config,{'to':email,'subject':'PC-DOCTOR S.A. | Presupuesto N.º '+found['code'],'body':body,'from_name':corporate.settings()['name']},card if card.get('enabled') else '')
                                    mail_pro.deliver(config,message,recipients);result='sent'
                            except mail_pro.MailError as error:
                                print('quote-mail',error.kind,flush=True);result='failed'
                            with connect() as log:
                                quotes.event(log,found['id'],'correo','Correo al cliente: '+{'sent':'aceptado por el servidor de correo','failed':'no se pudo enviar','not_configured':'el correo del sistema no está configurado'}[result]+'.',reception_now(),user)
                            return self.reply(200,{'ok':True,'mail':result,'recipient':email,'link':link,'quote':quotes.detail(c,quotes.get(c,found['id']))})
                        return self.reply(400,{'error':'Acción inválida.'})
                    except quotes.QuoteError as error:return self.reply(error.status,{'error':str(error),'fields':error.fields})
                payment_route=re.fullmatch(r'/api/orders/([0-9]+)/payments(/void)?',path)
                if payment_route:
                    # Pagos por equipo: los registra el personal; anularlos (con motivo) es de administración. Nunca se borran.
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if payment_route[2]:
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede anular un pago.'})
                        status,payload=equipment.void_payment(c,int(payment_route[1]),data,user,reception_now())
                        if status==200:audit(c,user['id'],'order_payment_voided',int(payment_route[1]));order_workspace.event(c,int(payment_route[1]),user['id'],reception_now(),'payment','Pago anulado. Motivo: '+str(data.get('reason','')).strip())
                    else:
                        status,payload=equipment.add_payment(c,int(payment_route[1]),data,user,reception_now())
                        if status==201:audit(c,user['id'],'order_payment_recorded',int(payment_route[1]));order_workspace.event(c,int(payment_route[1]),user['id'],reception_now(),'payment','Pago registrado: '+equipment.usd(c.execute('SELECT amount_cents FROM order_payments WHERE id=?',(payload['id'],)).fetchone()[0])+' ('+equipment.METHODS[str(data.get('method'))]+').')
                    return self.reply(status,payload)
                workspace_route=re.fullmatch(r'/api/orders/([0-9]+)/workspace',path)
                if workspace_route:
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede editar órdenes.'})
                    status,payload=order_workspace.save(c,int(workspace_route[1]),data,user,reception_now())
                    if status==200:audit(c,user['id'],'order_workspace_updated',int(workspace_route[1]))
                    return self.reply(status,payload)
                if path == '/api/conditions':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede publicar condiciones.'})
                    # Sin número de versión se asigna el siguiente de la serie; la aprobación expresa sigue siendo obligatoria.
                    tid,errors=service_terms.publish_next(c,data,user,reception_now())
                    if errors:return self.reply(400,{'error':next(iter(errors.values())) if len(errors)==1 else 'Revisa los datos de publicación.','fields':errors})
                    audit(c,user['id'],'service_terms_published')
                    return self.reply(201,{'ok':True,'id':tid,'version':c.execute('SELECT version FROM service_terms WHERE id=?',(tid,)).fetchone()[0]})
                if path in ('/api/conditions/draft','/api/conditions/draft/discard','/api/conditions/compare'):
                    # Borrador de trabajo y comparación con la versión vigente. Guardar un borrador nunca publica nada.
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    now=reception_now();active=service_terms.current(c,now)
                    if path.endswith('/compare'):
                        return self.reply(200,{'diff':service_terms.compare(active['full_text'] if active else '',str(data.get('full_text',''))),'compact_changed':bool(active) and str(data.get('compact_text','')).strip().replace('\r\n','\n')!=active['compact_text'],'current':active['version'] if active else ''})
                    if path.endswith('/discard'):
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede descartar el borrador.'})
                        c.execute('DELETE FROM service_terms_draft');audit(c,user['id'],'service_terms_draft_discarded')
                        return self.reply(200,{'ok':True})
                    errors=service_terms.save_draft(c,data,user,now)
                    if errors:return self.reply(400,{'error':next(iter(errors.values())),'fields':errors})
                    audit(c,user['id'],'service_terms_draft_saved')
                    return self.reply(200,{'ok':True})
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
                        # Revertir una entrega reabre el contador de permanencia: solo administración, y queda auditado.
                        reverted=old=='entregado' and status!='entregado'
                        if reverted and user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede revertir una entrega registrada.'})
                        if status=='entregado' and old!='entregado':
                            blocked=equipment.delivery_block(c,int(oid))
                            if blocked:return self.reply(409,{'error':blocked,'balance':True})
                        c.execute('UPDATE orders SET status=?,updated_at=?,revision=revision+1 WHERE id=?', (status,now.isoformat(timespec='microseconds'),oid))
                        planned=maintenance.transition(c,int(oid),old,status,now)
                        # La entrega crea también la cita futura del mantenimiento (pendiente de confirmación), sin pasos manuales.
                        if planned:
                            booked=appointments.create_for_maintenance(c,planned['id'],user)
                            if booked:planned['appointment']=booked;order_workspace.event(c,int(oid),user['id'],now,'maintenance','Cita de mantenimiento preventivo generada automáticamente ('+booked['public_code']+').')
                        # Sin cambio real ni comentario no hay nada que auditar; con cambio, el registro nombra la transición.
                        if old!=status or comment:order_workspace.event(c,int(oid),user['id'],now,'status' if old!=status else 'follow_up',comment or order_workspace.transition_comment(old,status))
                        audit(c,user['id'],'order_status_updated',int(oid))
                        if reverted:audit(c,user['id'],'delivery_reverted',int(oid))
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
                        if 'writing' not in data and any(key in data for key in adi_ai.CORRECTION_DEFAULTS):
                            # Corrección Inteligente: interruptores y espera antes de revisar.
                            problem=adi_ai.save_correction(c,data)
                            if problem:return self.reply(400,{'error':problem})
                            audit(c,user['id'],'adi_correction_updated')
                            return self.reply(200,{'ok':True,'writing':adi_ai.status(c)})
                        if data.get('writing') not in (True,False):return self.reply(400,{'error':'Valor inválido.'})
                        c.execute("INSERT INTO system_state(key,value) VALUES ('adi_writing',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('on' if data['writing'] else 'off',))
                        audit(c,user['id'],'adi_writing_'+('enabled' if data['writing'] else 'disabled'))
                        return self.reply(200,{'ok':True,'writing':adi_ai.status(c)})
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if not adi_ai.enabled(c):return self.reply(403,{'error':'La redacción con ADI está desactivada en Configuración.'})
                    if not adi_ai.provider():return self.reply(503,{'error':'ADI todavía no tiene un proveedor de IA configurado en el servidor.','kind':'configuracion'})
                    # La corrección automática es siempre ortográfica, con su propio límite de uso; las mejoras pedidas a mano tienen el suyo.
                    auto=data.get('auto') is True
                    if limited(c,('adi-auto:' if auto else 'adi-write:')+str(user['id']),limit=240 if auto else 60,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de mejoras por hora. Intenta más tarde.','kind':'limite'})
                    mode='ortografia' if auto else str(data.get('mode',''));field=str(data.get('field',''))[:40]
                    rules=adi_ai.correction(c)
                    if auto and not rules['auto_spelling']:return self.reply(403,{'error':'La revisión ortográfica automática está desactivada en Configuración.','kind':'desactivado'})
                    if not auto and mode!='ortografia' and not rules['professional']:return self.reply(403,{'error':'Las mejoras de redacción con ADI están desactivadas en Configuración.','kind':'desactivado'})
                    if auto and len(str(data.get('text','')))>1500:return self.reply(400,{'error':'Texto demasiado largo para la corrección automática.'})
                    # La llamada a la IA puede tardar varios segundos: se cierra antes la transacción para no bloquear otros guardados
                    # (ni otra petición de ADI del mismo usuario) mientras se espera la respuesta.
                    c.commit()
                    try:result=adi_ai.improve(data.get('text',''),mode,field)
                    except adi_ai.AdiError as error:
                        print('adi-write',error.kind,flush=True)
                        return self.reply(error.status,{'error':str(error),'kind':error.kind})
                    # Registro de uso: quién, qué tipo de mejora y consumo. No se guarda el texto.
                    c.execute('INSERT INTO adi_actions(user_id,action,created_at,details) VALUES (?,?,?,?)',(user['id'],'writing_improve',reception_now().isoformat(timespec='seconds'),json.dumps({'mode':mode,'auto':auto,'field':field,'model':result['model'],'tokens_in':result['tokens_in'],'tokens_out':result['tokens_out'],'missing':len(result['missing'])})))
                    return self.reply(200,{'suggestion':result['suggestion'],'missing':result['missing'],'changed':result['changed'],'simple':result['changed'] and adi_ai.is_simple(str(data.get('text','')).strip(),result['suggestion'])})
                receipt_route=re.fullmatch(r'/api/orders/([0-9]+)/receipt-mail',path)
                if receipt_route or path=='/api/receipt-mail/settings':
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if not receipt_route and data.get('action')=='test':
                        # Correo de prueba: va al propio buzón del sistema, nunca a un cliente.
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede enviar la prueba.'})
                        if limited(c,'receipt-mail-test:'+str(user['id']),limit=6,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de pruebas por hora.'})
                        try:
                            if not mail_pro.configured():return self.reply(200,{'result':'not_configured','message':'El correo del sistema no está configurado en el servidor.'})
                            config=mail_pro.settings();message,recipients=mail_pro.build_message(config,{'to':config['username'],'subject':'Prueba de notificaciones automáticas | Órdenes Pro','body':'Este es un correo de prueba enviado desde Configuración → Notificaciones automáticas por correo.\n\nSi lo recibes en el buzón del sistema, el envío de comprobantes está operativo.','from_name':corporate.settings()['name']},'')
                            mail_pro.deliver(config,message,recipients)
                        except mail_pro.MailError as error:
                            audit(c,user['id'],'receipt_mail_test_failed');return self.reply(200,{'result':'failed','message':'La prueba no se envió: '+str(error)})
                        audit(c,user['id'],'receipt_mail_test_sent');return self.reply(200,{'result':'sent','recipient':config['username'],'message':'Prueba enviada a '+config['username']+'. El servidor de correo aceptó el mensaje.'})
                    if not receipt_route:
                        if user['role']!='administrador' or data.get('auto') not in (True,False):return self.reply(403 if user['role']!='administrador' else 400,{'error':'No se pudo cambiar la configuración.'})
                        c.execute("INSERT INTO system_state(key,value) VALUES ('receipt_mail_auto',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('on' if data['auto'] else 'off',))
                        audit(c,user['id'],'receipt_mail_auto_'+('on' if data['auto'] else 'off'));return self.reply(200,{'ok':True,'auto':data['auto']})
                    mode=str(data.get('mode',''))
                    if mode not in ('auto','manual'):return self.reply(400,{'error':'Modo de envío inválido.'})
                    if mode=='manual' and limited(c,'receipt-mail:'+str(user['id']),limit=30,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de reenvíos por hora.'})
                    c.commit()  # El envío espera al servidor de correo: no se retiene la base mientras tanto.
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
                if path=='/api/profile/photo':
                    # Cada persona gestiona únicamente su propia foto.
                    if data.get('action')=='delete':
                        c.execute('DELETE FROM user_photos WHERE user_id=?',(user['id'],));audit(c,user['id'],'profile_photo_removed')
                        return self.reply(200,{'ok':True,'photo':''})
                    try:content=base64.b64decode(str(data.get('data','')),validate=True)
                    except Exception:return self.reply(400,{'error':'La imagen no se pudo leer.'})
                    kind=image_kind(content)
                    if not kind:return self.reply(400,{'error':'Usa una imagen PNG, JPG o WebP.'})
                    if not 200<=len(content)<=PROFILE_PHOTO_LIMIT:return self.reply(400,{'error':'La imagen es demasiado grande. El máximo es 300 KB.'})
                    stamp=reception_now().isoformat(timespec='seconds')
                    c.execute('INSERT INTO user_photos(user_id,mime,size,data,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET mime=excluded.mime,size=excluded.size,data=excluded.data,updated_at=excluded.updated_at',(user['id'],kind,len(content),base64.b64encode(content).decode(),stamp))
                    audit(c,user['id'],'profile_photo_updated')
                    return self.reply(200,{'ok':True,'photo':stamp})
                if path=='/api/business-hours':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede cambiar los horarios.'})
                    import business_hours
                    values,problem=business_hours.validate(data)
                    if problem:return self.reply(400,{'error':problem})
                    # Cambiar el horario no modifica ninguna cita existente: solo la información que se muestra y la que usa ADI.
                    business_hours.save(c,values);audit(c,user['id'],'business_hours_updated')
                    return self.reply(200,{'ok':True,'config':values,'summary':business_hours.public(c,reception_now())})
                if path=='/api/stay/settings':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede cambiar el plazo de permanencia.'})
                    values,problem=stay.validate(data,stay.settings(c))
                    if problem:return self.reply(400,{'error':problem})
                    stay.save(c,values);audit(c,user['id'],'stay_settings_updated')
                    return self.reply(200,{'ok':True,'settings':values})
                if path=='/api/stay/reminders':
                    # Avisos de permanencia por correo: activarlos o enviarlos es una decisión de administración.
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede gestionar los avisos de permanencia.'})
                    import stay_reminders
                    now=reception_now()
                    if data.get('enabled') in (True,False):
                        values=dict(stay.settings(c),mail=data['enabled']);stay.save(c,values);audit(c,user['id'],'stay_reminders_'+('on' if data['enabled'] else 'off'))
                    elif data.get('action')=='run':
                        if not stay.settings(c)['mail']:return self.reply(409,{'error':'Activa primero los avisos de permanencia.'})
                        try:ready=mail_pro.configured()
                        except mail_pro.MailError:ready=False
                        if not ready:return self.reply(409,{'error':'El correo del sistema no está configurado.'})
                        if limited(c,'stay-run:'+str(user['id']),limit=12,window=3600):return self.reply(429,{'error':'Espera antes de volver a enviar.'})
                        summary=stay_reminders.run(c,now,stay_deliver);audit(c,user['id'],'stay_reminders_run')
                        return self.reply(200,{'ok':True,'summary':summary,'reminders':stay_reminders.status(c,now)})
                    else:return self.reply(400,{'error':'Acción no disponible.'})
                    return self.reply(200,{'ok':True,'reminders':stay_reminders.status(c,now)})
                client_route=re.fullmatch(r'/api/orders/([0-9]+)/client-authorization',path)
                if client_route or path=='/api/client-authorization/settings':
                    if not client_route:
                        if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede cambiar este ajuste.'})
                        if data.get('auto') not in (True,False):return self.reply(400,{'error':'Valor inválido.'})
                        c.execute("INSERT INTO system_state(key,value) VALUES ('client_authorization_auto',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('on' if data['auto'] else 'off',))
                        audit(c,user['id'],'client_authorization_auto_'+('on' if data['auto'] else 'off'))
                        return self.reply(200,{'ok':True,'auto':data['auto']})
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    if data.get('action')!='send':return self.reply(400,{'error':'Acción inválida.'})
                    if limited(c,'cauth-send:'+str(user['id']),limit=30,window=3600):return self.reply(429,{'error':'Alcanzaste el límite de envíos por hora.'})
                    status,payload=send_client_authorization(c,int(client_route[1]),user)
                    if status==200:audit(c,user['id'],'client_authorization_sent',int(client_route[1]))
                    return self.reply(status,payload)
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
                    # La decisión queda guardada antes de intentar el aviso: un fallo del correo no la afecta.
                    c.commit();notice=None
                    try:notice=send_authorization_mail(c,oid,user)
                    except Exception as error:print('authorization-mail',type(error).__name__,flush=True)
                    return self.reply(201,{'ok':True,'authorization_mail':notice})
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
                    # Varios equipos en una orden: el ingreso nuevo se une a la orden principal del mismo cliente.
                    group_main=None;group_ref=str(data.get('group_order_id',''))
                    if group_ref:
                        group_main=equipment.root(c,int(group_ref)) if group_ref.isdigit() else None
                        if not group_main:return self.reply(404,{'error':'La orden a la que quieres agregar el equipo ya no está disponible.'})
                        if c.execute('SELECT client_id FROM devices WHERE id=?',(group_main['device_id'],)).fetchone()['client_id']!=selected['id']:
                            return self.reply(409,{'error':'La orden seleccionada pertenece a otro cliente.','fields':{'client_id':'El equipo debe ser del mismo cliente de la orden.'}})
                    # Equipo existente: se conserva su identidad e historial; sus características salen del registro, no del formulario.
                    existing_device=None;device_ref=str(data.get('device_id',''))
                    if device_ref:
                        existing_device=c.execute("SELECT d.*,COALESCE(NULLIF(d.kind,''),d.category) kind_code FROM devices d WHERE d.id=? AND d.client_id=?",(int(device_ref),selected['id'])).fetchone() if device_ref.isdigit() else None
                        if not existing_device:return self.reply(404,{'error':'El equipo seleccionado no pertenece a este cliente.'})
                        busy=c.execute("SELECT COALESCE(code,'OP-'||printf('%05d',id)) code FROM orders WHERE device_id=? AND status!='entregado' ORDER BY id DESC LIMIT 1",(existing_device['id'],)).fetchone()
                        if busy:return self.reply(409,{'error':'El equipo '+(existing_device['code'] or '')+' ya tiene un ingreso abierto ('+busy['code']+'). Entrégalo antes de registrar otro ingreso.'})
                        incoming.update({'type':existing_device['kind_code'],'brand':existing_device['brand'] or '','model':existing_device['model'] or '','serial':existing_device['serial'] or '','color':existing_device['color'] or ''})
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
                        (client_id,fields['type'],fields['brand'],fields['model'],fields['color'],device_lookup.normalize(fields['serial']))).fetchone() if fields['serial'] and not existing_device else None
                    if existing_device:same=existing_device
                    elif data.get('new_unit')=='1':
                        # «Agregar equipo similar» registra una unidad física distinta: nunca se fusiona con otra; una serie ya registrada se rechaza.
                        clash=c.execute("SELECT code FROM devices WHERE client_id=? AND COALESCE(serial,'')!='' AND upper(replace(serial,' ',''))=? LIMIT 1",(client_id,device_lookup.normalize(fields['serial']))).fetchone() if fields['serial'] else None
                        if clash:return self.reply(409,{'error':'Ese número de serie ya pertenece al equipo '+(clash['code'] or 'registrado')+' de este cliente. Usa «Seleccionar equipo existente» o corrige la serie.','fields':{'serial':'Serie ya registrada en otro equipo del cliente.'}})
                        same=None
                    identified=bool(fields['brand'] or fields['model'])
                    # La identificación queda vinculada al equipo con quién la confirmó y cuándo; las órdenes anteriores no se tocan.
                    device_id = same['id'] if same else c.execute('INSERT INTO devices(client_id,type,category,kind,brand,model,serial,color,identity_source,identity_confirmed_by,identity_confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (client_id,legacy_type(fields['type']),stored_category(fields['type']),fields['type'],fields['brand'],fields['model'],fields['serial'],fields['color'],(device_lookup.source(data.get('identity_source')) or 'manual') if identified else '',user['id'] if identified else None,received.isoformat(timespec='seconds') if identified else '')).lastrowid
                    remember_brand(c,fields['brand'],fields['type'])
                    unit_number=1
                    if group_main:
                        # El equipo adicional no consume un número de orden: lleva el de la orden principal con su sufijo (-E02, -E03…).
                        unit_number,code=equipment.next_unit(c,group_main);number_date=sequence=None
                        if not code:return self.reply(409,{'error':'La orden alcanzó el máximo de equipos permitido.'})
                    else:
                        number_date = received.strftime('%Y%m%d')
                        c.execute('INSERT INTO daily_order_sequences(reception_date,value) VALUES (?,1) ON CONFLICT(reception_date) DO UPDATE SET value=value+1',(number_date,))
                        sequence = c.execute('SELECT value FROM daily_order_sequences WHERE reception_date=?',(number_date,)).fetchone()[0]
                        code = order_code(number_date,sequence)
                    oid = c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,accessories,physical_condition,technician_notes,code,request_key,received_at,number_date,daily_sequence,group_id,unit_no) VALUES (?,'pendiente',?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id,fields['problem'],user['id'],int(received.timestamp()),fields['accessories'],fields['physical_condition'],fields['technician_notes'],code,request_key,received.isoformat(timespec='microseconds'),number_date,sequence,group_main['id'] if group_main else None,unit_number)).lastrowid
                    if group_main:audit(c,user['id'],'order_unit_added',oid)
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
                    # La orden queda guardada antes de intentar el correo: si el envío falla, la orden permanece y se puede reenviar.
                    c.commit();receipt=None
                    try:receipt=send_receipt_mail(c,oid,user,'auto')[1]
                    except Exception as error:print('receipt-mail auto',type(error).__name__,flush=True)
                    notice=None
                    try:c.commit();notice=send_authorization_mail(c,oid,user)
                    except Exception as error:print('authorization-mail',type(error).__name__,flush=True)
                    client_link=None
                    try:
                        if client_authorization_auto(c):client_link=send_client_authorization(c,oid,user)[1];client_link.pop('url',None)
                    except Exception as error:print('client-authorization auto',type(error).__name__,flush=True)
                    return self.reply(201, {'ok':True,'id':oid,'code':code,'receipt_mail':receipt,'authorization_mail':notice,'client_authorization':client_link})
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
