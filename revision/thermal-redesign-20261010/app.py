"""Evaluación local de ÓRDENES PRO. Loopback por defecto; LAN mediante configuración explícita."""
import argparse
import base64
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
from reception import (valid_ecuador_phone, DEVICE_TYPES, validate_order, order_code, legacy_type, remember_brand, qr_image, production_enabled, reception_now, order_url, public_base_url)

import service_terms
import order_workspace
import corporate
import client_registry
import maintenance
import appointments
import adi
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
    c = sqlite3.connect(DB, timeout=10, factory=Connection)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def migrate():
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)')
        for p in sorted((ROOT / 'migrations').glob('*.sql')):
            if not c.execute('SELECT 1 FROM migrations WHERE name=?', (p.name,)).fetchone():
                if DB.exists() and c.execute('SELECT COUNT(*) FROM migrations').fetchone()[0]:
                    backup = DATA / f'backup-{time.time_ns()}.sqlite3'
                    target = sqlite3.connect(backup)
                    try:
                        c.backup(target)
                    finally:
                        target.close()
                    backup.chmod(0o600)
                name = p.name.replace("'", "''")
                c.executescript('BEGIN IMMEDIATE;\n' + p.read_text() + f"\nINSERT INTO migrations VALUES ('{name}');\nCOMMIT;")
        initialize_catalog(c)
        snapshot_rows = c.execute("SELECT o.id,c.name client,c.identification,c.document_type,c.trade_name,c.phone,c.email,c.province,c.province_code,c.canton,c.canton_code,c.parish,c.parish_code,c.city,c.locality_code,c.address,c.main_street,c.secondary_street,c.building_number,c.location_reference,c.geo_version,d.category type,d.brand,d.model,d.serial,d.color,o.accessories,o.physical_condition,o.problem,o.technician_notes FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id WHERE o.reception_snapshot='' ").fetchall()
        for order in snapshot_rows:
            snapshot=dict(order)
            oid=snapshot.pop('id')
            c.execute('UPDATE orders SET reception_snapshot=? WHERE id=?',(json.dumps(snapshot,ensure_ascii=False),oid))
        for order in c.execute("SELECT id,code FROM orders WHERE qr_url=''").fetchall():
            c.execute('UPDATE orders SET qr_url=? WHERE id=?',(order_url(order['code']),order['id']))
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
    defaults = {'lockout_seconds': login_lockout_window(), 'session_hours': 8, 'remember_days': 30, 'password_min': 12}
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
        content = content.replace('{{evaluation_notice}}', notice).replace('{{environment_label}}', 'Servicio técnico' if production_enabled() else 'Evaluación local · Usa datos ficticios')
        self.reply(200, content, 'text/html; charset=utf-8')

    def do_GET(self):
        path = urlsplit(self.path).path
        files = {'/static/label.css':'label.css','/static/app.css':'app.css','/static/app.js':'app.js','/static/form-validation.js':'form-validation.js','/static/appointments.js':'appointments.js','/static/logo-original.png':'logo-original.png'}
        if path in files:
            file = ROOT / 'static' / files[path]
            if not file.is_file():
                return self.reply(404, {'error':'Archivo no disponible.'})
            content_type = 'image/png' if file.suffix == '.png' else ('text/css; charset=utf-8' if file.suffix == '.css' else 'text/javascript; charset=utf-8')
            return self.reply(200, file.read_bytes(), content_type)
        with connect() as c:
            if path == '/citas':
                return self.page('appointments.html')
            if path == '/api/public/appointments/services':
                return self.reply(200, {'services':appointments.services(c),'device_types':DEVICE_TYPES,'timezone':'America/Guayaquil'})
            if path == '/api/public/appointments/availability':
                query=parse_qs(urlsplit(self.path).query)
                try: rows=appointments.available_slots(c,query.get('date',[''])[0],query.get('service',[''])[0])
                except ValueError as error:return self.reply(400,{'error':str(error)})
                return self.reply(200,{'slots':[{'time':r['time']} for r in rows]})
            if path == '/api/public/appointments/manage':
                query=parse_qs(urlsplit(self.path).query);code=query.get('code',[''])[0][:40];token=query.get('token',[''])[0]
                row=c.execute('SELECT id,public_code,customer_name,device_type,brand,model,service_code,starts_at,status,generation,manage_token_hash FROM appointments WHERE public_code=?',(code,)).fetchone()
                if not row or not secrets.compare_digest(row['manage_token_hash'],appointments.token_hash(token)):
                    return self.reply(404,{'error':'No encontramos una cita válida con ese enlace.'})
                result=dict(row);result.pop('manage_token_hash');return self.reply(200,{'appointment':result})
            if path == '/api/public/adi/messages':
                cookies=SimpleCookie()
                try:cookies.load(self.headers.get('Cookie',''))
                except Exception:pass
                token=cookies['pcdoctor_adi'].value if 'pcdoctor_adi' in cookies else ''
                conv=c.execute('SELECT id,mode FROM adi_conversations WHERE token_hash=?',(digest(token),)).fetchone()
                if not conv:return self.reply(200,{'messages':[],'mode':'adi'})
                after=parse_qs(urlsplit(self.path).query).get('after',['0'])[0]
                try:after=max(0,int(after))
                except ValueError:after=0
                rows=[dict(r) for r in c.execute("SELECT id,author,content,created_at FROM adi_messages WHERE conversation_id=? AND visibility='public' AND id>? ORDER BY id LIMIT 100",(conv['id'],after))]
                c.execute('UPDATE adi_conversations SET last_seen_client=? WHERE id=?',(appointments.stamp(appointments.now()),conv['id']))
                return self.reply(200,{'messages':rows,'mode':conv['mode']})
            preference=re.fullmatch(r'/maintenance-preferences/([A-Za-z0-9_-]{40,60})',path)
            if preference:
                row=c.execute('SELECT consent FROM maintenance WHERE unsubscribe_token=?',(preference[1],)).fetchone()
                if not row:return self.reply(404,{'error':'Enlace no disponible.'})
                token=preference[1]
                body='<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Preferencias de recordatorios</title><h1>PC-DOCTOR S.A.</h1><p>Puede dejar de recibir recordatorios de mantenimiento. Esta acción no modifica su reparación.</p><form method="post" action="/maintenance-preferences/'+token+'"><button type="submit">Dejar de recibir recordatorios</button></form></html>'
                return self.reply(200,body,'text/html; charset=utf-8')
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
            if path == '/reset':
                return self.page('reset.html')
            if not user:
                return self.reply(401, {'error':'Inicia sesión para continuar.'})
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
            if path == '/api/adi/admin':
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede usar la asistente administrativa.'})
                return self.reply(200,{'enabled':bool(os.getenv('OPENAI_API_KEY')),'message':'Adi responde consultas operativas desde datos autorizados.'})
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
                return self.reply(200, {'user':dict(user),'server_time':time.time()})
            if path == '/api/weather':
                return self.reply(200, current_weather())
            if path == '/api/time':
                return self.reply(200, {'server_time':time.time(),'timezone':'America/Guayaquil'})
            if path == '/api/corporate':return self.reply(200,corporate.settings())
            if path in ('/api/conditions/draft','/api/conditions/draft.pdf'):
                draft=corporate.terms_draft()
                if path.endswith('.pdf'):
                    from conditions_pdf import render_conditions
                    return self.reply(200,render_conditions(draft),'application/pdf')
                return self.reply(200,draft)
            if path == '/api/conditions/current':
                active=service_terms.current(c,reception_now())
                return self.reply(200,{'terms':service_terms.metadata(active),'required':bool(active) or service_terms.required()})
            if path == '/api/conditions':
                if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede consultar el historial de publicación.'})
                rows=c.execute('SELECT * FROM service_terms ORDER BY effective_date DESC,published_at DESC').fetchall()
                return self.reply(200,{'rows':[service_terms.metadata(r) for r in rows]})
            if path == '/api/document-logo.png':
                from document_logo import monochrome_png
                return self.reply(200,monochrome_png(),'image/png')
            if path == '/api/reception-options':
                brands = [dict(r) for r in c.execute('SELECT name,category FROM brands ORDER BY name COLLATE NOCASE')]
                return self.reply(200, {'geo_metadata':GEO_METADATA,'device_types':DEVICE_TYPES,'brands':brands})
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
                orders=[dict(r) for r in c.execute('SELECT o.id,o.code,o.created_at,s.label status FROM orders o JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status WHERE d.client_id=? ORDER BY o.id DESC',(row['id'],))]
                return self.reply(200,{'client':client_registry.profile(row),'devices':devices,'orders':orders})
            if path == '/api/client-search':
                term=parse_qs(urlsplit(self.path).query).get('q',[''])[0][:150]
                rows=[dict(r) for r in c.execute("SELECT id,name,identification,document_type,phone,trade_name FROM clients WHERE instr(lower(name||' '||COALESCE(identification,'')||' '||COALESCE(phone,'')||' '||trade_name),lower(?))>0 ORDER BY name LIMIT 20",(term,))]
                return self.reply(200,{'rows':rows})
            if path == '/api/order-options':
                return self.reply(200, {'statuses':order_workspace.STATUSES,'users':[dict(r) for r in c.execute('SELECT id,name FROM users WHERE active=1 ORDER BY name')]})
            detail = re.fullmatch(r'/api/orders/([0-9]+)(?:/(qr\.(svg|png)|receipt\.pdf|thermal\.pdf|service\.pdf|label\.pdf))?', path)
            if detail:
                row = c.execute('SELECT o.*,d.category type,d.brand,d.model,d.serial,d.color,c.id client_id,c.name client,c.identification,c.phone,c.email,c.province,c.city,c.address,c.location_reference,s.label status_label FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?',(int(detail[1]),)).fetchone()
                if not row:
                    return self.reply(404, {'error':'Orden no disponible.'})
                code = row['code'] or 'OP-'+str(row['id']).zfill(5)
                if detail[3]:
                    return self.reply(200, qr_image(row['qr_url'],detail[3]), 'image/svg+xml' if detail[3]=='svg' else 'image/png')
                if detail[2] in ('receipt.pdf','thermal.pdf','service.pdf','label.pdf'):
                    from receipt_pdf import render_receipt
                    pdf_order=dict(row)
                    pdf_order['current_problem']=row['problem']
                    if row['reception_snapshot']:
                        pdf_order.update(json.loads(row['reception_snapshot']))
                    service_terms.attach(c,pdf_order)
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
                        return self.reply(200,render_thermal(pdf_order),'application/pdf')
                    return self.reply(200, render_receipt(pdf_order), 'application/pdf')
                result = dict(row)
                result.pop('request_key', None)
                if result['reception_snapshot']:
                    result.update(json.loads(result['reception_snapshot']))
                result.pop('reception_snapshot',None)
                result['code'] = code
                service_terms.attach(c,result)
                order_workspace.attach(c,result)
                result['current_problem']=row['problem']
                return self.reply(200, {'order':result})
            if path in ('/api/orders', '/api/clients', '/api/devices'):
                query = parse_qs(urlsplit(self.path).query)
                term = query.get('q', [''])[0][:150]
                try:
                    page = max(1, int(query.get('page', ['1'])[0]))
                except ValueError:
                    return self.reply(400, {'error':'Página inválida.'})
                if path == '/api/orders':
                    source = 'orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status'
                    columns = "o.id,o.code,o.created_at,o.problem,o.status status_code,s.label status,d.category type,d.brand,d.model,c.name client,o.priority,o.estimated_delivery,COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'Sin asignar') responsible"
                    search = "COALESCE(o.code,'OP-'||printf('%05d',o.id))||' '||CAST(o.id AS TEXT)||' '||c.name||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||o.problem||' '||s.label"
                    active = query.get('active', [''])[0] == '1'
                    where = ' AND o.status != \'entregado\'' if active else ''
                    ordering = 'o.id DESC'
                elif path == '/api/clients':
                    source, columns = 'clients c', 'c.id,c.name,c.phone,c.email,c.identification,c.document_type,c.trade_name'
                    search = "c.name||' '||COALESCE(c.phone,'')||' '||COALESCE(c.email,'')||' '||c.identification||' '||c.trade_name"
                    where, ordering = '', 'c.id DESC'
                else:
                    source = 'devices d JOIN clients c ON c.id=d.client_id'
                    columns = 'd.id,d.client_id,c.name client,d.category type,d.brand,d.model,d.serial'
                    search = "c.name||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')"
                    where, ordering = '', 'd.id DESC'
                args=[term]
                if path == '/api/orders':
                    status=query.get('status',[''])[0]
                    if status:
                        if status not in order_workspace.STATUSES:return self.reply(400,{'error':'Estado inválido.'})
                        where+=' AND o.status=?';args.append(status)
                    for name,expression in [('client','c.name'),('equipment',"COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')")]:
                        value=query.get(name,[''])[0][:150]
                        if value:where+=' AND instr(lower('+expression+'),lower(?))>0';args.append(value)
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
                rows = [dict(r) for r in c.execute('SELECT '+columns+' FROM '+source+condition+' ORDER BY '+ordering+' LIMIT 50 OFFSET ?', (*args,(page-1)*50))]
                return self.reply(200, {'rows':rows,'total':total,'page':page,'pages':max(1,(total+49)//50)})
            if path == '/api/reports':
                counts = [dict(r) for r in c.execute("SELECT s.code,s.label,COUNT(o.id) total FROM statuses s LEFT JOIN orders o ON o.status=s.code GROUP BY s.code ORDER BY CASE s.code WHEN 'pendiente' THEN 1 WHEN 'reparacion' THEN 2 WHEN 'esperando_cliente' THEN 3 WHEN 'presupuesto' THEN 4 WHEN 'espera_entrega' THEN 5 WHEN 'listo' THEN 6 ELSE 7 END")]
                return self.reply(200, {'statuses':counts,'clients':c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],'devices':c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]})
            if path == '/api/settings':
                if user['role'] != 'administrador':
                    return self.reply(403, {'error':'Solo administración puede acceder a la configuración.'})
                return self.reply(200, {'profile':{k:user[k] for k in ('name','username','email','role')},'accounts':[dict(r) for r in c.execute('SELECT name,username,role,active FROM users ORDER BY id')],'smtp_configured':bool(os.getenv('SMTP_HOST')),'openai_configured':bool(os.getenv('OPENAI_API_KEY')),'login_lockout_seconds':auth_policy(c)['lockout_seconds'],'auth_policy':auth_policy(c),'antibot_configured':bool(os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY')),'origin':os.getenv('APP_URL','http://127.0.0.1:8010')})
            if path in ('/api/dashboard','/api/activity','/api/maintenance'):
                now=reception_now();today=now.date().isoformat()
                if path=='/api/maintenance':return self.reply(200,{'rows':maintenance.rows(c),'today':today,'profiles':{k:v[0] for k,v in maintenance.PROFILES.items()}})
                activity=[dict(r) for r in c.execute('SELECT h.*,o.code,u.name actor FROM order_history h JOIN orders o ON o.id=h.order_id LEFT JOIN users u ON u.id=h.actor_id ORDER BY h.id DESC LIMIT ?', (50 if path=='/api/activity' else 5,))]
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
                return self.reply(200,{'counts':counts,'attention':attention,'activity':activity,'maintenance':scheduled,'deliveries':deliveries,'today':today,'appointments':today_appointments,'pending_chats':pending_chats,'assistance':assistance})
            search_route=path=='/api/search'
            if search_route:
                term=parse_qs(urlsplit(self.path).query).get('q',[''])[0].strip()[:150]
                if len(term)<2:return self.reply(200,{'rows':[]})
                rows=[dict(r) for r in c.execute("SELECT o.id,o.code,c.name client,d.brand,d.model,d.serial,s.label status FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status WHERE instr(lower(COALESCE(o.code,'')||' '||c.name||' '||COALESCE(c.identification,'')||' '||COALESCE(c.phone,'')||' '||d.brand||' '||d.model||' '||d.serial),lower(?))>0 ORDER BY o.id DESC LIMIT 10",(term,))]
                return self.reply(200,{'rows':rows})
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
            max_body=100000 if path=='/api/conditions' else (65536 if workspace_post else 16384)
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > max_body:
                return self.reply(400, {'error':'Solicitud inválida.'})
            data = json.loads(self.rfile.read(length))
            appointment_config_post=path=='/api/appointments/config'
            if not isinstance(data, dict) or any(not isinstance(v,(str,bool)) and not (workspace_post and ((k=='lines' and isinstance(v,list)) or (k=='revision' and type(v) is int))) and not (appointment_config_post and ((k in ('hours','services') and isinstance(v,list)) or (k=='holiday' and isinstance(v,dict)))) for k,v in data.items()):
                return self.reply(400, {'error':'Datos inválidos.'})
            path = urlsplit(self.path).path
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if path == '/api/public/appointments':
                    if limited(c,'appointment-ip:'+digest(self.client_address[0]),12,900):return self.reply(429,{'error':'Demasiadas solicitudes. Intenta más tarde.'})
                    key=str(data.get('request_key','')).strip()
                    if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',key):return self.reply(400,{'error':'Actualiza el formulario e inténtalo nuevamente.'})
                    previous=c.execute('SELECT id,public_code,starts_at,status FROM appointments WHERE request_key=?',(key,)).fetchone()
                    if previous:return self.reply(200,{'ok':True,'id':previous['id'],'code':previous['public_code'],'starts_at':previous['starts_at'],'status':previous['status'],'duplicate':True})
                    data['request_key']=key
                    status,payload=appointments.create(c,data)
                    if status==201:
                        if payload.get('email'):
                            pass
                        return self.reply(status,payload)
                    return self.reply(status,payload)
                if path == '/api/public/appointments/manage':
                    code=str(data.get('code',''))[:40];token=str(data.get('token',''))
                    row=c.execute('SELECT * FROM appointments WHERE public_code=?',(code,)).fetchone()
                    if not row or not secrets.compare_digest(row['manage_token_hash'],appointments.token_hash(token)):return self.reply(404,{'error':'No encontramos una cita válida con ese enlace.'})
                    if data.get('action')=='cancel':
                        if row['status'] in ('cancelada','completada','no_asistio'):return self.reply(409,{'error':'La cita ya no se puede cancelar desde este enlace.'})
                        now=appointments.stamp(appointments.now());c.execute("UPDATE appointments SET status='cancelada',updated_at=? WHERE id=?",(now,row['id']))
                        c.execute("INSERT INTO appointment_events(appointment_id,event,old_start,old_status,new_status,created_at) VALUES (?,'cancelled',?,?,?,?)",(row['id'],row['starts_at'],row['status'],'cancelada',now))
                        if row['email'] and row['communications_consent']:c.execute("INSERT OR IGNORE INTO appointment_notifications(appointment_id,generation,event,channel,result,created_at) VALUES (?,?,'cancelled','email','pending',?)",(row['id'],row['generation'],now))
                        return self.reply(200,{'ok':True,'status':'cancelada'})
                    if data.get('action')=='reschedule':
                        if row['status'] in ('cancelada','completada','no_asistio'):return self.reply(409,{'error':'La cita ya está cerrada y no se puede reprogramar desde este enlace.'})
                        try:start=appointments.parse_start(str(data.get('starts_at','')))
                        except ValueError as error:return self.reply(400,{'error':str(error)})
                        result=appointments.reschedule(c,row,start,None);return self.reply(200 if result.get('ok') else 409,result)
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
                    now=appointments.stamp(appointments.now());c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client',?,?)",(conv['id'],text,now))
                    answer='Un asesor de PC-DOCTOR S.A. revisará tu solicitud.' if conv['mode']=='human' else None
                    context=None
                    match=re.search(r'(PCD-\d{8}-\d{4,}).*?(\d{10}|\d{13})',text,re.I)
                    if match and conv['mode']=='adi':
                        found=adi.order_status(c,match[1].upper(),match[2]);context={'orden':found} if found else None
                        if found:answer=f"Tu orden {found['code']} está en estado «{found['status']}». Equipo: {found['brand'] or ''} {found['model'] or ''}. Para más información, puedo solicitar atención del taller."
                    if answer is None and conv['mode']=='adi':answer=adi.reply(c,text,context=context)
                    if answer:
                        c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'adi',?,?)",(conv['id'],answer,now));c.execute('UPDATE adi_conversations SET updated_at=? WHERE id=?',(now,conv['id']))
                    response={'ok':True,'conversation_id':conv['id'],'mode':conv['mode'],'messages':[dict(r) for r in c.execute("SELECT id,author,content,created_at FROM adi_messages WHERE conversation_id=? AND id>(SELECT COALESCE(MAX(id),0)-2 FROM adi_messages WHERE conversation_id=?) ORDER BY id",(conv['id'],conv['id']))]}
                    cookie='pcdoctor_adi='+new_token+'; Path=/; HttpOnly; SameSite=Strict'+('; Secure' if os.getenv('SESSION_SECURE','false').lower()=='true' else '') if new_token else None
                    return self.reply(201,response,cookie=cookie)
                if path == '/api/public/adi/human':
                    cookies=SimpleCookie()
                    try:cookies.load(self.headers.get('Cookie',''))
                    except Exception:pass
                    token=cookies['pcdoctor_adi'].value if 'pcdoctor_adi' in cookies else '';conv=c.execute('SELECT id,mode FROM adi_conversations WHERE token_hash=?',(digest(token),)).fetchone() if token else None
                    if not conv:return self.reply(404,{'error':'Inicia una conversación con Adi primero.'})
                    now=appointments.stamp(appointments.now());c.execute("UPDATE adi_conversations SET mode='human',updated_at=? WHERE id=?",(now,conv['id']));c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client','El cliente solicita atención humana.',?)",(conv['id'],now))
                    return self.reply(200,{'ok':True,'mode':'human'})
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
                    if bot_required(c,ip_key) and not verify_bot(str(data.get('bot_token','')),'login'):
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
                    bounds={'lockout_seconds':(900,86400),'session_hours':(1,8),'remember_days':(1,30),'password_min':(12,128)}
                    try:
                        values={key:int(data[key]) for key in bounds}
                        if any(not low<=values[key]<=high for key,(low,high) in bounds.items()):raise ValueError()
                    except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'Revisa los límites de seguridad permitidos.'})
                    for key,value in values.items():c.execute('INSERT INTO auth_policy VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
                    audit(c,user['id'],'auth_policy_updated')
                    return self.reply(200,{'ok':True})
                if path=='/api/sessions/revoke':
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],));audit(c,user['id'],'sessions_revoked')
                    return self.reply(200,{'ok':True,'message':'Se cerraron las sesiones activas.'},cookie=self.cookie('',0))
                appointment_route=re.fullmatch(r'/api/appointments/([0-9]+)',path)
                if path=='/api/appointments/config':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede configurar la agenda.'})
                    status,payload=appointments.update_settings(c,data)
                    if status==200:audit(c,user['id'],'appointment_settings_updated')
                    return self.reply(status,payload)
                if appointment_route:
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    row=c.execute('SELECT * FROM appointments WHERE id=?',(int(appointment_route[1]),)).fetchone()
                    if not row:return self.reply(404,{'error':'Cita no disponible.'})
                    action=data.get('action');now=appointments.stamp(appointments.now())
                    if action=='reschedule':
                        try:start=appointments.parse_start(str(data.get('starts_at','')))
                        except ValueError as error:return self.reply(400,{'error':str(error)})
                        result=appointments.reschedule(c,row,start,user);status=200 if result.get('ok') else 409;payload=result
                    elif action in ('confirmada','presente','completada','no_asistio','cancelada'):
                        if action not in appointments.STATUSES:return self.reply(400,{'error':'Estado de cita inválido.'})
                        if row['status'] in ('cancelada','completada','no_asistio') and action not in ('confirmada',):return self.reply(409,{'error':'La cita ya está cerrada.'})
                        c.execute('UPDATE appointments SET status=?,updated_at=? WHERE id=?',(action,now,row['id']))
                        c.execute('INSERT INTO appointment_events(appointment_id,actor_id,event,old_start,new_start,old_status,new_status,created_at) VALUES (?,?,?,?,?,?,?,?)',(row['id'],user['id'],'status',row['starts_at'],row['starts_at'],row['status'],action,now));status=200;payload={'ok':True}
                    else:return self.reply(400,{'error':'Acción de cita inválida.'})
                    if status==200:audit(c,user['id'],'appointment_'+str(action),row['id'])
                    return self.reply(status,payload)
                if path == '/api/adi/admin':
                    if user['role']!='administrador':return self.reply(403,{'error':'Solo administración puede usar la asistente administrativa.'})
                    prompt=str(data.get('message','')).strip()
                    if not prompt or len(prompt)>2000:return self.reply(400,{'error':'Escribe una consulta de hasta 2000 caracteres.'})
                    answer=adi.admin_answer(c,prompt)
                    if not answer and any(k in prompt.casefold() for k in ('redact','notificación','notificacion')):answer=adi.ask(prompt,admin=True)
                    answer=answer or 'Puedo consultar órdenes en espera, respuestas pendientes, presupuestos, citas, historial y mantenimientos. Para otros datos, revisa el módulo correspondiente.'
                    c.execute('INSERT INTO adi_actions(user_id,action,created_at,details) VALUES (?,?,?,?)',(user['id'],'admin_query',appointments.stamp(appointments.now()),prompt[:500]))
                    return self.reply(200,{'answer':answer,'ai_enabled':bool(os.getenv('OPENAI_API_KEY'))})
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
                if path == '/api/client-registry':
                    if user['role'] not in ('administrador','tecnico'):return self.reply(403,{'error':'Acceso no permitido.'})
                    status,payload=client_registry.save(c,data,user)
                    if status in (200,201):audit(c,user['id'],'client_registry_saved',payload['id'])
                    return self.reply(status,payload)
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
                        maintenance.transition(c,int(oid),old,status,now)
                        order_workspace.event(c,int(oid),user['id'],now,'status',comment or 'Estado actualizado.')
                        audit(c,user['id'],'order_status_updated',int(oid))
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
                            keys = (*keys, 'category')
                            values[1] = legacy_type(category)
                            values.append(category)
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
                if path == '/api/orders':
                    client_id=str(data.get('client_id',''))
                    selected=c.execute('SELECT * FROM clients WHERE id=?',(client_id,)).fetchone() if client_id.isdigit() else None
                    if not selected:return self.reply(400,{'error':'Selecciona un cliente registrado.','fields':{'client_id':'Busca y selecciona un cliente válido.'}})
                    appointment_id=str(data.get('appointment_id',''));linked_appointment=None
                    if appointment_id:
                        if not appointment_id.isdigit():return self.reply(400,{'error':'La cita vinculada no es válida.'})
                        linked_appointment=c.execute('SELECT * FROM appointments WHERE id=?',(int(appointment_id),)).fetchone()
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
                    if not terms and service_terms.required():
                        return self.reply(503,{'error':'Publica las condiciones aprobadas y vigentes antes de registrar recepciones.','fields':{'terms_accept':'No hay condiciones vigentes configuradas.'}})
                    if terms:
                        if str(data.get('terms_document_id',''))!=terms['id']:
                            return self.reply(409,{'error':'Las condiciones vigentes han cambiado. Revísalas y registra nuevamente la aceptación.','fields':{'terms_accept':'La versión debe revisarse nuevamente.'}})
                        if data.get('terms_accept') is not True:
                            return self.reply(400,{'error':'Registra la aceptación de las condiciones.','fields':{'terms_accept':'El cliente debe revisar y aceptar las condiciones antes de guardar.'}})
                    client_id=selected['id']
                    tracking,tracking_errors=order_workspace.validate(c,dict(data,problem=fields['problem'],status='pendiente',assigned_to=str(data.get('assigned_to') or user['id']),internal_notes=data.get('additional_notes',''),findings=data.get('initial_diagnosis','')))
                    if tracking_errors:return self.reply(400,{'error':'Revisa los datos de recepción.','fields':tracking_errors})
                    device_id = c.execute('INSERT INTO devices(client_id,type,category,brand,model,serial,color) VALUES (?,?,?,?,?,?,?)',
                        (client_id,legacy_type(fields['type']),fields['type'],fields['brand'],fields['model'],fields['serial'],fields['color'])).lastrowid
                    remember_brand(c,fields['brand'],fields['type'])
                    number_date = received.strftime('%Y%m%d')
                    c.execute('INSERT INTO daily_order_sequences(reception_date,value) VALUES (?,1) ON CONFLICT(reception_date) DO UPDATE SET value=value+1',(number_date,))
                    sequence = c.execute('SELECT value FROM daily_order_sequences WHERE reception_date=?',(number_date,)).fetchone()[0]
                    code = order_code(number_date,sequence)
                    oid = c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,accessories,physical_condition,technician_notes,code,request_key,received_at,number_date,daily_sequence) VALUES (?,'pendiente',?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id,fields['problem'],user['id'],int(received.timestamp()),fields['accessories'],fields['physical_condition'],fields['technician_notes'],code,request_key,received.isoformat(timespec='microseconds'),number_date,sequence)).lastrowid
                    c.execute('UPDATE orders SET qr_url=? WHERE id=?',(order_url(code),oid))
                    c.execute('UPDATE orders SET reception_snapshot=? WHERE id=?',(json.dumps(fields,ensure_ascii=False),oid))
                    if terms:
                        c.execute('UPDATE orders SET terms_document_id=?,terms_acceptance_id=?,terms_accepted_at=?,terms_mechanism=?,terms_acceptor=?,terms_actor_id=? WHERE id=?',
                                  (terms['id'],secrets.token_hex(16),received.isoformat(timespec='microseconds'),service_terms.MECHANISM,fields['client'],user['id'],oid))
                        audit(c,user['id'],'service_terms_accepted',oid)
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
        password = getpass.getpass('Contraseña (mínimo 12 caracteres): ')
        repeat = getpass.getpass('Repetir contraseña: ')
        if not name or not re.fullmatch(r'[a-zA-Z0-9_.-]{3,50}', username) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or not 12<=len(password)<=256 or password != repeat:
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
