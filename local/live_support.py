"""Centro de Atención en Tiempo Real: conversaciones del chat público atendidas por Adi o por el personal."""
import re
ORDER_CODE=re.compile(r'\bPCD-\d{8}-\d{4}\b',re.I)
LIST_SQL="""SELECT v.id,v.mode,v.assigned_to,v.created_at,v.updated_at,v.last_seen_admin,v.client_id,v.order_id,u.name operator,cl.name client,o.code order_code,
 (SELECT content FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_message,
 (SELECT author FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_author,
 (SELECT created_at FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_at,
 (SELECT COUNT(*) FROM adi_messages m WHERE m.conversation_id=v.id AND m.author='client' AND m.visibility='public' AND m.created_at>v.last_seen_admin) unread,
 (SELECT COUNT(*) FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public') total
 FROM adi_conversations v LEFT JOIN users u ON u.id=v.assigned_to LEFT JOIN clients cl ON cl.id=v.client_id LEFT JOIN orders o ON o.id=v.order_id """


def rows(c,scope='active'):
    if scope=='closed':sql=LIST_SQL+"WHERE v.mode='closed' ORDER BY v.updated_at DESC LIMIT 30"
    else:sql=LIST_SQL+"WHERE v.mode!='closed' ORDER BY v.updated_at DESC LIMIT 100"
    return [dict(r) for r in c.execute(sql)]


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
                if code not in mentioned and c.execute('SELECT 1 FROM orders WHERE code=?',(code,)).fetchone():mentioned.append(code)
    return {'conversation':info,'messages':messages,'client':dict(client) if client else None,'order':dict(order) if order else None,'actions':actions,'mentioned':mentioned[:3]}


def act(c,conv,user,data,now):
    action=data.get('action');details=''
    if action=='reply':
        content=str(data.get('message','')).strip()
        if not content or len(content)>3000:return 400,{'error':'Escribe una respuesta de hasta 3000 caracteres.'}
        if conv['mode']=='closed':return 409,{'error':'La conversación está cerrada. Reábrela para responder.'}
        c.execute("INSERT INTO adi_messages(conversation_id,author,author_id,content,created_at) VALUES (?,'operator',?,?,?)",(conv['id'],user['id'],content,now))
        c.execute("UPDATE adi_conversations SET mode='human',assigned_to=?,updated_at=? WHERE id=?",(user['id'],now,conv['id']))
        return 200,{'ok':True}
    if action in ('takeover','resume','close','reopen'):
        if action=='reopen' and conv['mode']!='closed':return 409,{'error':'La conversación ya está abierta.'}
        if action!='reopen' and conv['mode']=='closed':return 409,{'error':'La conversación está cerrada.'}
        mode={'takeover':'human','resume':'adi','close':'closed','reopen':'human'}[action]
        c.execute('UPDATE adi_conversations SET mode=?,assigned_to=?,updated_at=? WHERE id=?',(mode,user['id'] if mode=='human' else None,now,conv['id']))
    elif action=='link':
        if data.get('clear') is True:
            c.execute('UPDATE adi_conversations SET client_id=NULL,order_id=NULL WHERE id=?',(conv['id'],));details='Vínculo retirado'
        elif str(data.get('order_code','')).strip():
            code=str(data['order_code']).strip().upper()
            order=c.execute('SELECT o.id,o.code,d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.code=?',(code,)).fetchone()
            if not order:return 404,{'error':'No existe una orden con ese número.'}
            c.execute('UPDATE adi_conversations SET client_id=?,order_id=? WHERE id=?',(order['client_id'],order['id'],conv['id']));details='Orden '+order['code']
        elif str(data.get('client_id','')).isdigit():
            client=c.execute('SELECT id,name FROM clients WHERE id=?',(int(data['client_id']),)).fetchone()
            if not client:return 404,{'error':'El cliente ya no está disponible.'}
            c.execute('UPDATE adi_conversations SET client_id=?,order_id=NULL WHERE id=?',(client['id'],conv['id']));details='Cliente '+client['name']
        else:return 400,{'error':'Indica una orden o un cliente para vincular.'}
    else:return 400,{'error':'Acción de conversación inválida.'}
    c.execute('INSERT INTO adi_actions(conversation_id,user_id,action,created_at,details) VALUES (?,?,?,?,?)',(conv['id'],user['id'],'conversation_'+action,now,details))
    return 200,{'ok':True}
