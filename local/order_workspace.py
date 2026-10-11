"""Seguimiento interno de órdenes; no modifica la recepción histórica ni su QR."""
from datetime import date
from decimal import Decimal, InvalidOperation

STATUSES={'pendiente':'En espera','reparacion':'Procesando','esperando_cliente':'Esperando respuesta del cliente','presupuesto':'Aprobación de presupuesto','espera_entrega':'En espera de entrega','listo':'Listo para entregar','entregado':'Entregado'}
BUDGET_KEYS=('labor','parts','services','digital')


def event(c,oid,actor,now,kind,comment=''):
    label=c.execute('SELECT s.label FROM orders o JOIN statuses s ON s.code=o.status WHERE o.id=?',(oid,)).fetchone()[0]
    c.execute('INSERT INTO order_history(order_id,actor_id,occurred_at,event,status_label,comment) VALUES (?,?,?,?,?,?)',(oid,actor,now.isoformat(timespec='microseconds'),kind,label,comment))


# El historial solo guarda el estado vigente de cada evento. El estado anterior se lee del evento previo de la misma
# orden; si no existe, queda vacío y la interfaz no muestra ninguna transición (no se inventa).
HISTORY_SQL="""SELECT h.*,o.code,u.name actor,(SELECT p.status_label FROM order_history p WHERE p.order_id=h.order_id AND p.id<h.id AND p.status_label!='' ORDER BY p.id DESC LIMIT 1) previous_label FROM order_history h JOIN orders o ON o.id=h.order_id LEFT JOIN users u ON u.id=h.actor_id"""


def history(c,oid=None,limit=300):
    if oid is None:return [dict(r) for r in c.execute(HISTORY_SQL+' ORDER BY h.id DESC LIMIT ?',(limit,))]
    return [dict(r) for r in c.execute(HISTORY_SQL+' WHERE h.order_id=? ORDER BY h.id DESC',(oid,))]


def transition_comment(old,new):
    return 'Estado cambiado de «%s» a «%s».'%(STATUSES.get(old,old),STATUSES.get(new,new))


def attach(c,order):
    actor=c.execute('SELECT name FROM users WHERE id=?',(order['assigned_to'],)).fetchone()
    order['responsible']=actor['name'] if actor else 'Sin asignar'
    order['history']=history(c,order['id'])
    row=c.execute('SELECT * FROM order_budget WHERE order_id=?',(order['id'],)).fetchone()
    order['budget']={k+'_cents':row[k+'_cents'] if row else 0 for k in BUDGET_KEYS}
    order['budget']['total_cents']=sum(order['budget'].values())
    order['budget_lines']=[dict(r) for r in c.execute('SELECT category,description,amount_cents FROM order_budget_lines WHERE order_id=? ORDER BY id',(order['id'],))]
    return order


def validate(c,data):
    fields={};errors={}
    for key,limit in [('problem',4000),('internal_notes',4000),('recommendations',4000),('findings',4000),('comment',2000)]:
        value=str(data.get(key,'')).strip()
        if len(value)>limit or (key=='problem' and not value):errors[key]=f'Indica un texto válido de hasta {limit} caracteres.'
        fields[key]=value
    fields['status']=str(data.get('status',''))
    if fields['status'] not in STATUSES:errors['status']='Selecciona un estado válido.'
    fields['priority']=str(data.get('priority','normal'))
    if fields['priority'] not in ('baja','normal','alta','urgente'):errors['priority']='Selecciona una prioridad válida.'
    value=str(data.get('assigned_to',''))
    if value and (not value.isdigit() or not c.execute('SELECT 1 FROM users WHERE id=? AND active=1',(value,)).fetchone()):errors['assigned_to']='Selecciona un usuario activo.'
    fields['assigned_to']=int(value) if value.isdigit() else None
    value=str(data.get('estimated_delivery',''))
    if value:
        try:
            if date.fromisoformat(value).isoformat()!=value:raise ValueError()
        except ValueError:errors['estimated_delivery']='Indica una fecha válida.'
    fields['estimated_delivery']=value
    for key in BUDGET_KEYS:
        try:
            amount=Decimal(str(data.get(key,'0')))
            if not amount.is_finite() or amount<0 or amount>Decimal('9999999.99') or amount.as_tuple().exponent < -2:raise InvalidOperation()
            fields[key+'_cents']=int(amount*100)
        except (InvalidOperation,ValueError):errors[key]='Indica un importe USD no negativo con hasta dos decimales.'
    if 'lines' in data:
        lines=data['lines'];fields['lines']=[]
        if not isinstance(lines,list) or len(lines)>100:errors['lines']='El presupuesto admite hasta 100 líneas.'
        else:
            for key in BUDGET_KEYS:fields[key+'_cents']=0
            for line in lines:
                if not isinstance(line,dict):errors['lines']='Revisa las líneas del presupuesto.';continue
                category=str(line.get('category',''));description=str(line.get('description','')).strip();amount=line.get('amount_cents')
                if category not in BUDGET_KEYS or not description or len(description)>250 or type(amount) is not int or not 0<=amount<=999999999:errors['lines']='Cada línea necesita categoría, descripción e importe válido.';continue
                fields['lines'].append((category,description,amount));fields[category+'_cents']+=amount
            if sum(fields[k+'_cents'] for k in BUDGET_KEYS)>999999999:errors['lines']='El total supera el importe máximo permitido.'
    return fields,errors


def save(c,oid,data,user,now):
    row=c.execute('SELECT revision,status FROM orders WHERE id=?',(oid,)).fetchone()
    if not row:return 404,{'error':'Orden no disponible.'}
    fields,errors=validate(c,data)
    if errors:return 400,{'error':'Revisa los campos señalados.','fields':errors}
    if str(data.get('revision',''))!=str(row['revision']):return 409,{'error':'Otro usuario actualizó esta orden. Recarga el detalle antes de guardar.'}
    keys=('problem','status','priority','assigned_to','estimated_delivery','internal_notes','recommendations','findings')
    c.execute('UPDATE orders SET '+','.join(k+'=?' for k in keys)+',updated_at=?,revision=revision+1 WHERE id=?',(*(fields[k] for k in keys),now.isoformat(timespec='microseconds'),oid))
    from maintenance import transition
    planned=transition(c,oid,row['status'],fields['status'],now)
    columns=','.join(k+'_cents' for k in BUDGET_KEYS)
    c.execute('INSERT INTO order_budget(order_id,'+columns+') VALUES (?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET '+','.join(k+'_cents=excluded.'+k+'_cents' for k in BUDGET_KEYS),(oid,*(fields[k+'_cents'] for k in BUDGET_KEYS)))
    if 'lines' in fields:
        c.execute('DELETE FROM order_budget_lines WHERE order_id=?',(oid,))
        c.executemany('INSERT INTO order_budget_lines(order_id,category,description,amount_cents) VALUES (?,?,?,?)',[(oid,*line) for line in fields['lines']])
    # Si la edición cambió el estado, el registro lo dice de forma explícita para que sirva como auditoría.
    changed=row['status']!=fields['status']
    event(c,oid,user['id'],now,'status' if changed else 'updated',fields['comment'] or (transition_comment(row['status'],fields['status']) if changed else 'Seguimiento técnico actualizado.'))
    return 200,{'ok':True}
