"""Borradores de Nueva orden: datos sin validar de una recepción a medio llenar. No crean órdenes, números ni documentos."""
import json
MAX_BYTES=60000
# Nunca se conservan confirmaciones de consentimiento ni claves: se vuelven a registrar al finalizar la orden.
FORBIDDEN=('terms_accept','terms_document_id','access_confirmed','destructive_confirmed')


def _clean(value,depth=0):
    if depth>4:raise ValueError()
    if isinstance(value,dict):
        if len(value)>200:raise ValueError()
        return {str(k)[:80]:_clean(v,depth+1) for k,v in value.items() if str(k) not in FORBIDDEN and 'password' not in str(k).lower() and 'contrase' not in str(k).lower()}
    if isinstance(value,list):
        if len(value)>100:raise ValueError()
        return [_clean(v,depth+1) for v in value]
    if isinstance(value,str):return value[:6000]
    if isinstance(value,(bool,int)) or value is None:return value
    raise ValueError()


def read(c,user):
    row=c.execute("SELECT id,payload,revision,created_at,updated_at FROM order_drafts WHERE user_id=? AND status='active'",(user['id'],)).fetchone()
    if not row:return None
    try:data=json.loads(row['payload'])
    except ValueError:return None
    return {'id':row['id'],'revision':row['revision'],'created_at':row['created_at'],'updated_at':row['updated_at'],'data':data}


def save(c,user,raw,revision,force,now):
    """Guarda o actualiza el único borrador del usuario. Si otra sesión lo cambió después de la revisión conocida, no lo pisa salvo petición expresa."""
    if not isinstance(raw,str) or len(raw.encode())>MAX_BYTES:return 400,{'error':'El borrador es demasiado grande para guardarlo.'}
    try:
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError()
        data=_clean(data)
    except (ValueError,RecursionError):return 400,{'error':'El borrador no tiene un formato válido.'}
    stamp=now.isoformat(timespec='seconds');current=c.execute('SELECT id,revision,status,updated_at FROM order_drafts WHERE user_id=?',(user['id'],)).fetchone()
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    if not current:
        c.execute("INSERT INTO order_drafts(user_id,payload,revision,status,created_at,updated_at) VALUES (?,?,1,'active',?,?)",(user['id'],payload,stamp,stamp))
        return 201,{'ok':True,'draft':read(c,user)}
    known=int(revision) if str(revision).isdigit() else 0
    if current['status']=='active' and known!=current['revision'] and not force:
        return 409,{'error':'Hay un borrador más reciente guardado desde otra sesión.','conflict':True,'updated_at':current['updated_at'],'revision':current['revision']}
    fresh=current['status']!='active'
    c.execute("UPDATE order_drafts SET payload=?,revision=revision+1,status='active',created_at=CASE WHEN ? THEN ? ELSE created_at END,updated_at=? WHERE id=?",(payload,1 if fresh else 0,stamp,stamp,current['id']))
    return 200,{'ok':True,'draft':read(c,user)}


def discard(c,user,now):
    """El borrador se marca como descartado y se vacía; no toca clientes, equipos, órdenes ni fotos."""
    done=c.execute("UPDATE order_drafts SET status='discarded',payload='{}',revision=revision+1,updated_at=? WHERE user_id=? AND status='active'",(now.isoformat(timespec='seconds'),user['id'])).rowcount
    return bool(done)
