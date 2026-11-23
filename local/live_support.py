"""Centro de Atención en Tiempo Real: conversaciones del chat público atendidas por ADI o por el personal."""
import re

import reception
ORDER_CODE=re.compile(r'\b(?:PCD-\d{8}-\d{4}|OP-\d{4,})\b',re.I)
LIST_SQL="""SELECT v.id,v.mode,v.assigned_to,v.created_at,v.updated_at,v.last_seen_admin,v.client_id,v.order_id,u.name operator,cl.name client,o.code order_code,o.status order_status,
 (SELECT content FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_message,
 (SELECT author FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_author,
 (SELECT created_at FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_at,
 (SELECT COUNT(*) FROM adi_messages m WHERE m.conversation_id=v.id AND m.author='client' AND m.visibility='public' AND m.created_at>v.last_seen_admin) unread,
 (SELECT COUNT(*) FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public') total
 FROM adi_conversations v LEFT JOIN users u ON u.id=v.assigned_to LEFT JOIN clients cl ON cl.id=v.client_id LEFT JOIN orders o ON o.id=v.order_id """


def summary(c):
    """Contadores del Centro de Atenciones. Cada conversación abierta cuenta en una sola categoría:
    - waiting: con un asesor (o solicitándolo) y el último mensaje es del cliente → espera respuesta humana;
    - transferred: transferida por ADI a un asesor y ya respondida (en curso);
    - new_conversations: atendida por ADI y con mensajes del cliente que el personal aún no ha visto.
    Además devuelve las atenciones que requieren acción, de la que más tiempo lleva esperando a la más reciente."""
    counts={'new_conversations':0,'waiting':0,'transferred':0};pending=[]
    import whatsapp_handoff as handoff
    # Una solicitud de atención sin aceptar espera al personal aunque el último mensaje sea la confirmación de ADI (1.5.321).
    unattended={r[0] for r in c.execute("SELECT conversation_id FROM adi_handoffs WHERE status='pendiente'")} if handoff.installed(c) else set()
    for row in c.execute(LIST_SQL+"WHERE v.mode!='closed' ORDER BY v.updated_at"):
        if not row['total']:continue
        if row['mode']=='human':kind='waiting' if row['last_author']=='client' or row['id'] in unattended else 'transferred'
        elif row['unread'] or (row['last_seen_admin']=='' and row['last_author'] is not None):kind='new_conversations'
        else:continue
        counts[kind]+=1
        if kind!='transferred':pending.append({'id':row['id'],'kind':kind,'client':row['client'] or '','order_code':row['order_code'] or '','source':'Transferida por ADI' if row['mode']=='human' else 'Chat con ADI',
                                               'created_at':row['created_at'],'waiting_since':row['last_at'] or row['updated_at'],'unread':row['unread'],'preview':(row['last_message'] or '')[:120] if row['last_author']=='client' else ''})
    pending.sort(key=lambda item:(item['kind']!='waiting',item['waiting_since']))
    return dict(counts,pending=pending[:5],total=sum(counts.values()))


def rows(c,scope='active'):
    if scope=='closed':sql=LIST_SQL+"WHERE v.mode='closed' ORDER BY v.updated_at DESC LIMIT 30"
    else:sql=LIST_SQL+"WHERE v.mode!='closed' ORDER BY v.updated_at DESC LIMIT 100"
    out=[dict(r) for r in c.execute(sql)]
    import whatsapp_handoff as handoff
    if out and handoff.installed(c):
        ids=[r['id'] for r in out];marks=','.join('?'*len(ids))
        cases={r['conversation_id']:r for r in c.execute("SELECT conversation_id,code,priority,status FROM adi_handoffs WHERE status IN ('pendiente','asignada') AND conversation_id IN ("+marks+")",ids)}
        wa={r[0] for r in c.execute('SELECT conversation_id FROM whatsapp_conversations WHERE conversation_id IN ('+marks+')',ids)}
        for r in out:
            case=cases.get(r['id'])
            r.update(channel='whatsapp' if r['id'] in wa else 'web',case_code=case['code'] if case else '',case_priority=case['priority'] if case else '',case_status=case['status'] if case else '')
        if scope!='closed':  # las urgentes primero, luego alta; dentro de cada nivel, el orden de siempre
            rank={'urgente':0,'alta':1}
            out.sort(key=lambda r:rank.get(r.get('case_priority'),2))
    return out


def detail(c,conv,after,now):
    """Mensajes posteriores a «after» y el contexto real de la conversación. Consultarla la marca como vista por el personal."""
    messages=[dict(r) for r in c.execute('SELECT m.id,m.author,m.visibility,m.content,m.created_at,u.name operator FROM adi_messages m LEFT JOIN users u ON u.id=m.author_id WHERE m.conversation_id=? AND m.id>? ORDER BY m.id',(conv['id'],after))]
    c.execute('UPDATE adi_conversations SET last_seen_admin=? WHERE id=?',(now,conv['id']))
    info=dict(c.execute(LIST_SQL+'WHERE v.id=?',(conv['id'],)).fetchone());info['unread']=0
    client=c.execute('SELECT id,name,phone,email FROM clients WHERE id=?',(conv['client_id'],)).fetchone() if conv['client_id'] else None
    order=c.execute("SELECT o.id,o.code,o.status,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?",(conv['order_id'],)).fetchone() if conv['order_id'] else None
    actions=[dict(r) for r in c.execute('SELECT a.action,a.created_at,a.details,u.name actor FROM adi_actions a LEFT JOIN users u ON u.id=a.user_id WHERE a.conversation_id=? ORDER BY a.id DESC LIMIT 8',(conv['id'],))]
    # Órdenes que el cliente mencionó por su número exacto: se sugieren, nunca se vinculan solas.
    mentioned=[]
    if not conv['order_id']:
        for row in c.execute("SELECT content FROM adi_messages WHERE conversation_id=? AND author='client' ORDER BY id DESC LIMIT 40",(conv['id'],)):
            for code in ORDER_CODE.findall(row['content']):
                code=code.upper()
                if code not in mentioned and c.execute('SELECT 1 FROM orders WHERE code=?',(reception.current_order_code(c,code),)).fetchone():mentioned.append(code)
    import whatsapp_handoff as handoff
    try:moment=reception.reception_now();attention=handoff.for_conversation(c,conv['id'],moment)
    except Exception:attention=None
    if attention and handoff.installed(c):
        failed={r['message_id']:r['detail'] for r in c.execute("SELECT message_id,detail FROM whatsapp_operator_sends WHERE conversation_id=? AND status='fallido'",(conv['id'],))}
        for m in messages:
            if m['id'] in failed:m['whatsapp_failed']=failed[m['id']] or 'WhatsApp no aceptó el mensaje.'
    staff=[dict(r) for r in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN ('administrador','tecnico') ORDER BY name")]
    return {'conversation':info,'messages':messages,'client':dict(client) if client else None,'order':dict(order) if order else None,'actions':actions,'mentioned':mentioned[:3],
            'attention':attention,'staff':staff}


def act(c,conv,user,data,now,moment=None):
    """Acciones del personal. En las conversaciones de WhatsApp (1.5.321) la respuesta sale por WhatsApp, la solicitud de atención
    (adi_handoffs) se acepta, transfiere o cierra y el cliente recibe el aviso; si WhatsApp no acepta el mensaje, se informa."""
    import whatsapp_handoff as handoff
    if moment is None:
        moment=reception.reception_now()
    action=data.get('action');details='';extra={}
    if action=='reply':
        content=str(data.get('message','')).strip()
        if not content or len(content)>3000:return 400,{'error':'Escribe una respuesta de hasta 3000 caracteres.'}
        if conv['mode']=='closed':return 409,{'error':'La conversación está cerrada. Reábrela para responder.'}
        mid=c.execute("INSERT INTO adi_messages(conversation_id,author,author_id,content,created_at) VALUES (?,'operator',?,?,?)",(conv['id'],user['id'],content,now)).lastrowid
        c.execute("UPDATE adi_conversations SET mode='human',assigned_to=?,updated_at=? WHERE id=?",(user['id'],now,conv['id']))
        handoff.on_staff_action(c,conv['id'],'reply',user,moment)
        sent,detail=handoff.send_text(c,conv['id'],content,moment,message_id=mid)
        if sent is not None:extra['whatsapp']={'sent':bool(sent),'detail':detail}
        return 200,dict({'ok':True},**extra)
    if action=='transfer':
        target=str(data.get('user_id',''))
        row=c.execute("SELECT id,name FROM users WHERE id=? AND active=1 AND role IN ('administrador','tecnico')",(int(target),)).fetchone() if target.isdigit() else None
        if not row:return 404,{'error':'Elige una persona activa del personal.'}
        if conv['mode']=='closed':return 409,{'error':'La conversación está cerrada.'}
        c.execute("UPDATE adi_conversations SET mode='human',assigned_to=?,updated_at=? WHERE id=?",(row['id'],now,conv['id']))
        handoff.on_staff_action(c,conv['id'],'transfer',user,moment,target=row['id']);details='Transferida a '+row['name']
    elif action in ('takeover','resume','close','reopen'):
        if action=='reopen' and conv['mode']!='closed':return 409,{'error':'La conversación ya está abierta.'}
        if action!='reopen' and conv['mode']=='closed':return 409,{'error':'La conversación está cerrada.'}
        mode={'takeover':'human','resume':'adi','close':'closed','reopen':'human'}[action]
        c.execute('UPDATE adi_conversations SET mode=?,assigned_to=?,updated_at=? WHERE id=?',(mode,user['id'] if mode=='human' else None,now,conv['id']))
        note=handoff.on_staff_action(c,conv['id'],action,user,moment)
        if note:extra['warning']=note
    elif action=='link':
        if data.get('clear') is True:
            c.execute('UPDATE adi_conversations SET client_id=NULL,order_id=NULL WHERE id=?',(conv['id'],));details='Vínculo retirado'
        elif str(data.get('order_code','')).strip():
            code=str(data['order_code']).strip().upper()
            order=c.execute('SELECT o.id,o.code,d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.code=?',(reception.current_order_code(c,code),)).fetchone()
            if not order:return 404,{'error':'No existe una orden con ese número.'}
            c.execute('UPDATE adi_conversations SET client_id=?,order_id=? WHERE id=?',(order['client_id'],order['id'],conv['id']));details='Orden '+order['code']
        elif str(data.get('client_id','')).isdigit():
            client=c.execute('SELECT id,name FROM clients WHERE id=?',(int(data['client_id']),)).fetchone()
            if not client:return 404,{'error':'El cliente ya no está disponible.'}
            c.execute('UPDATE adi_conversations SET client_id=?,order_id=NULL WHERE id=?',(client['id'],conv['id']));details='Cliente '+client['name']
        else:return 400,{'error':'Indica una orden o un cliente para vincular.'}
    else:return 400,{'error':'Acción de conversación inválida.'}
    c.execute('INSERT INTO adi_actions(conversation_id,user_id,action,created_at,details) VALUES (?,?,?,?,?)',(conv['id'],user['id'],'conversation_'+action,now,details))
    return 200,dict({'ok':True},**extra)
