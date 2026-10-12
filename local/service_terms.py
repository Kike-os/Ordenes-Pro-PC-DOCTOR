"""Condiciones aprobadas, versiones inmutables y evidencias de aceptación."""
from datetime import date
import hashlib
import html
import json
import re
import secrets
from reception import public_base_url

TITLE='Condiciones de Recepción y Servicios'
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
    data['pdf_url']='/conditions/'+row['id']+'.pdf'
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
    return '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>Condiciones de servicio | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16.png?v=2"><link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png?v=2"><link rel="icon" type="image/png" sizes="48x48" href="/static/favicon-48.png?v=2"><link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png?v=2"><link rel="stylesheet" href="/static/app.css"></head><body data-page="conditions"><main class="conditions-document"><header><img src="/static/logo-original.png" alt="Logotipo oficial PC-DOCTOR" width="2826" height="2049"><div><span class="eyebrow">PC-DOCTOR S.A.</span><h1>'''+escape(row['title'])+'''</h1></div></header><p class="conditions-version">Versión '''+escape(row['version'])+''' · Vigente desde '''+escape(row['effective_date'])+'''</p><ol>'''+items+'''</ol><footer><p>Documento público de consulta. Este enlace no muestra datos personales ni el estado de reparaciones.</p><p class="conditions-hash">SHA-256: '''+escape(row['content_hash'])+'''</p></footer></main></body></html>'''


def required():
    import os
    from reception import production_enabled
    return production_enabled() or os.getenv('REQUIRE_SERVICE_TERMS','').lower() in ('1','true','yes')


# --- Gestión documental: numeración automática, borrador pendiente y comparación entre versiones ---------------------------------------

def next_version(c,today):
    """Siguiente número AAAA.M.N: continúa la serie del mes en curso o empieza en 1 al cambiar de mes. Nunca reutiliza un número."""
    prefix='%d.%d.'%(today.year,today.month);highest=0
    for row in c.execute('SELECT version FROM service_terms'):
        match=re.fullmatch(re.escape(prefix)+r'(\d+)',row['version'])
        if match:highest=max(highest,int(match[1]))
    return prefix+str(highest+1)


def _words(old,new):
    """Diferencia palabra a palabra de un párrafo modificado: lista de (tipo, texto)."""
    import difflib
    a,b=re.findall(r'\s+|[^\s]+',old),re.findall(r'\s+|[^\s]+',new);out=[]
    for tag,i1,i2,j1,j2 in difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        if tag in ('equal',):out.append(('same',''.join(a[i1:i2])))
        if tag in ('delete','replace'):out.append(('removed',''.join(a[i1:i2])))
        if tag in ('insert','replace'):out.append(('added',''.join(b[j1:j2])))
    return out


def compare(old_text,new_text):
    """Compara dos textos por párrafos. Devuelve los bloques en orden y el recuento de añadidos, retirados y modificados."""
    import difflib
    a,b=paragraphs(old_text or ''),paragraphs(new_text or '');blocks=[];stats={'added':0,'removed':0,'changed':0}
    for tag,i1,i2,j1,j2 in difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        if tag=='equal':blocks+=[{'kind':'same','text':text} for text in a[i1:i2]]
        elif tag=='delete':blocks+=[{'kind':'removed','text':text} for text in a[i1:i2]];stats['removed']+=i2-i1
        elif tag=='insert':blocks+=[{'kind':'added','text':text} for text in b[j1:j2]];stats['added']+=j2-j1
        else:
            pairs=min(i2-i1,j2-j1)
            for k in range(pairs):blocks.append({'kind':'changed','text':b[j1+k],'before':a[i1+k],'words':_words(a[i1+k],b[j1+k])});stats['changed']+=1
            blocks+=[{'kind':'removed','text':text} for text in a[i1+pairs:i2]];stats['removed']+=i2-i1-pairs
            blocks+=[{'kind':'added','text':text} for text in b[j1+pairs:j2]];stats['added']+=j2-j1-pairs
    return {'blocks':blocks,'stats':stats,'identical':not any(stats.values())}


def draft(c):
    row=c.execute('SELECT d.*,COALESCE(u.name,\'\') author FROM service_terms_draft d LEFT JOIN users u ON u.id=d.updated_by WHERE d.id=1').fetchone()
    return dict(row) if row else None


def save_draft(c,data,user,now):
    """Guarda el borrador de trabajo. No publica nada: queda pendiente de la aprobación de administración."""
    fields,errors=validate_publication(dict(data,version='borrador',effective_date=now.date().isoformat(),approved=True))
    errors={key:value for key,value in errors.items() if key in ('full_text','compact_text')}
    note=str(data.get('note','')).strip()[:500]
    if errors:return errors
    c.execute('INSERT INTO service_terms_draft(id,full_text,compact_text,note,updated_by,updated_at) VALUES (1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET full_text=excluded.full_text,compact_text=excluded.compact_text,note=excluded.note,updated_by=excluded.updated_by,updated_at=excluded.updated_at',
              (fields['full_text'],fields['compact_text'],note,user['id'],now.isoformat(timespec='seconds')))
    return {}


def publish_next(c,data,user,now):
    """Publica con numeración automática cuando no se indica versión, registra los cambios frente a la versión vigente y retira el borrador."""
    previous=current(c,now) or c.execute('SELECT * FROM service_terms ORDER BY published_at DESC LIMIT 1').fetchone()
    payload=dict(data);automatic=not str(payload.get('version','')).strip()
    if automatic:payload['version']=next_version(c,now.date())
    if not str(payload.get('effective_date','')).strip():payload['effective_date']=now.date().isoformat()
    # Con numeración automática, un texto idéntico al vigente no genera una versión nueva (no habría nada que aprobar).
    if automatic and previous and str(payload.get('full_text','')).strip().replace('\r\n','\n')==previous['full_text'] and str(payload.get('compact_text','')).strip().replace('\r\n','\n')==previous['compact_text']:
        return None,{'full_text':'El texto es idéntico al de la versión vigente: no hay cambios que publicar.'}
    tid,errors=publish(c,payload,user,now)
    if errors:return None,errors
    stats=compare(previous['full_text'] if previous else '',payload['full_text'])['stats']
    c.execute('INSERT INTO service_terms_changes(terms_id,previous_id,note,added,removed,changed,created_at) VALUES (?,?,?,?,?,?,?)',
              (tid,previous['id'] if previous else None,str(data.get('note','')).strip()[:500],stats['added'],stats['removed'],stats['changed'],now.isoformat(timespec='seconds')))
    c.execute('DELETE FROM service_terms_draft')
    return tid,{}


def overview(c,now):
    """Datos del módulo de administración: versión vigente, siguiente número, borrador pendiente e historial con sus cambios."""
    active=current(c,now);rows=[]
    for row in c.execute("SELECT t.*,COALESCE(u.name,'') publisher,ch.previous_id,ch.note,ch.added,ch.removed,ch.changed FROM service_terms t LEFT JOIN users u ON u.id=t.published_by LEFT JOIN service_terms_changes ch ON ch.terms_id=t.id ORDER BY t.published_at DESC"):
        item=metadata(row);item.update(publisher=row['publisher'],previous_id=row['previous_id'],note=row['note'] or '',changes=None if row['added'] is None else {'added':row['added'],'removed':row['removed'],'changed':row['changed']},
                                       current=bool(active and row['id']==active['id']),scheduled=row['effective_date']>now.date().isoformat());rows.append(item)
    pending=draft(c)
    return {'rows':rows,'current':({**metadata(active),'full_text':active['full_text'],'compact_text':active['compact_text']} if active else None),'next_version':next_version(c,now.date()),'today':now.date().isoformat(),
            'draft':({**pending,'diff':compare(active['full_text'] if active else '',pending['full_text']),'compact_changed':bool(active) and pending['compact_text']!=active['compact_text']} if pending else None)}
