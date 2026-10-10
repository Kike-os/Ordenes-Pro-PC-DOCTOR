"""Condiciones aprobadas, versiones inmutables y evidencias de aceptación."""
from datetime import date
import hashlib
import html
import json
import re
import secrets
from reception import public_base_url

TITLE='Condiciones Generales de Recepción y Servicio Técnico'
MECHANISM='checkbox_presencial'
MECHANISM_LABEL='Confirmación en pantalla registrada por el técnico'


def paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n',text.strip()) if p.strip()]


def numbered_paragraphs(text):
    for index,paragraph in enumerate(paragraphs(text),1):
        match=re.match(r'^(\d{1,3})[.)]\s+(.*)$',paragraph,re.S)
        yield (int(match[1]),match[2]) if match else (index,paragraph)


def validate_publication(data):
    fields={key:str(data.get(key,'')).strip().replace('\r\n','\n').replace('\r','\n') for key in ('version','effective_date','full_text','compact_text')}
    errors={}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,39}',fields['version']):errors['version']='Usa una versión de hasta 40 letras, números, puntos o guiones.'
    try:
        parsed=date.fromisoformat(fields['effective_date'])
        if parsed.isoformat()!=fields['effective_date']:raise ValueError()
    except ValueError:errors['effective_date']='Indica una fecha de vigencia válida (AAAA-MM-DD).'
    for key,limit,para_limit in [('full_text',60000,2000),('compact_text',6000,1000)]:
        value=fields[key]
        if not value or len(value)>limit:errors[key]=f'El texto aprobado es obligatorio y admite hasta {limit} caracteres.'
        elif any(len(p)>para_limit for p in paragraphs(value)):errors[key]='Divide el texto en párrafos separados por una línea vacía para evitar cortes.'
        elif key=='full_text' and any(sum(max(1,(len(line)+53)//54) for line in p.splitlines())>42 for p in paragraphs(value)):errors[key]='Divide los párrafos extensos con una línea vacía para conservarlos completos en el PDF A4.'
        elif any(ord(c)<32 and c!='\n' for c in value):errors[key]='El texto contiene caracteres de control no imprimibles.'
        else:
            try:value.encode('cp1252')
            except UnicodeEncodeError:errors[key]='El texto contiene símbolos no compatibles con la tipografía de impresión. Usa caracteres imprimibles en español.'
    if data.get('approved') is not True:errors['approved']='Confirma que ambos textos y la vigencia han sido aprobados por PC-DOCTOR S.A.'
    return fields,errors


def publish(c,data,user,now):
    fields,errors=validate_publication(data)
    if errors:return None,errors
    if c.execute('SELECT 1 FROM service_terms WHERE version=?',(fields['version'],)).fetchone():return None,{'version':'Esta versión ya existe. Publica una nueva para conservar el historial.'}
    canonical=json.dumps(dict(title=TITLE,**fields),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    tid=secrets.token_hex(16)
    c.execute('INSERT INTO service_terms VALUES (?,?,?,?,?,?,?,?,?)',(tid,fields['version'],fields['effective_date'],TITLE,fields['full_text'],fields['compact_text'],hashlib.sha256(canonical).hexdigest(),now.isoformat(timespec='microseconds'),user['id']))
    return tid,{}


def current(c,now):
    return c.execute('SELECT * FROM service_terms WHERE effective_date<=? ORDER BY effective_date DESC,published_at DESC,id DESC LIMIT 1',(now.date().isoformat(),)).fetchone()


def metadata(row):
    if not row:return None
    data={key:row[key] for key in ('id','version','effective_date','title','content_hash','published_at')}
    data['url']=public_base_url()+'/conditions/'+row['id']
    data['local_url']='/conditions/'+row['id']
    return data


def attach(c,order):
    tid=order.get('terms_document_id')
    if not tid:
        order['terms']=None;return order
    row=c.execute('SELECT * FROM service_terms WHERE id=?',(tid,)).fetchone()
    if not row:raise ValueError('No se encontró la versión histórica de condiciones.')
    order['terms']={**dict(row),**metadata(row)}
    actor=c.execute('SELECT name FROM users WHERE id=?',(order['terms_actor_id'],)).fetchone()
    order['terms_operator']=actor['name'] if actor else 'Usuario registrado'
    order['terms_mechanism_label']=MECHANISM_LABEL
    return order


def public_page(row):
    escape=html.escape
    items=''.join('<li value="'+str(number)+'"><p>'+escape(p).replace('\n','<br>')+'</p></li>' for number,p in numbered_paragraphs(row['full_text']))
    return '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>Condiciones de servicio | PC-DOCTOR S.A.</title><link rel="stylesheet" href="/static/app.css"></head><body data-page="conditions"><main class="conditions-document"><header><img src="/static/logo-original.png" alt="Logotipo oficial PC-DOCTOR" width="2826" height="2049"><div><span class="eyebrow">PC-DOCTOR S.A.</span><h1>'''+escape(row['title'])+'''</h1></div></header><p class="conditions-version">Versión '''+escape(row['version'])+''' · Vigente desde '''+escape(row['effective_date'])+'''</p><ol>'''+items+'''</ol><footer><p>Documento público de consulta. Este enlace no muestra datos personales ni el estado de reparaciones.</p><p class="conditions-hash">SHA-256: '''+escape(row['content_hash'])+'''</p></footer></main></body></html>'''


def required():
    import os
    from reception import production_enabled
    return production_enabled() or os.getenv('REQUIRE_SERVICE_TERMS','').lower() in ('1','true','yes')
