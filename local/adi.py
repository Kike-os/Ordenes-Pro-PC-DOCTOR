"""Respuestas acotadas de Adi. La IA nunca recibe permisos para ejecutar escrituras."""
import json,os,re,urllib.request,urllib.error
import appointments,order_workspace,maintenance

SYSTEM_PUBLIC=("Eres Adi, asistente virtual de PC-DOCTOR S.A. Habla español con tono amable y profesional. "
"Identifícate como asistente virtual cuando sea pertinente. No afirmes ser humana. "
"No inventes diagnósticos, precios, garantías, fechas de entrega ni avances. Para esos asuntos solicita revisión del taller. "
"No solicites contraseñas ni números completos de tarjetas. Reserva citas mediante el enlace del sistema.")
SYSTEM_ADMIN=("Eres Adi, asistente administrativa de PC-DOCTOR S.A. Responde en español de forma clara. "
"Usa solamente los datos reales que aparecen en el contexto. No ejecutes cambios, envíos ni escrituras. "
"Para una modificación indica que debe confirmarla y ejecutarla un usuario autorizado.")

def order_status(c,code,identification):
 row=c.execute("SELECT o.code,s.label status,d.brand,d.model FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.code=? AND cl.identification=?",(code,identification)).fetchone()
 return dict(row) if row else None

def admin_answer(c,text):
 q=text.casefold()
 if 'en espera' in q:
  n=c.execute("SELECT count(*) FROM orders WHERE status='pendiente'").fetchone()[0];return f"Hay {n} orden(es) en espera."
 if 'listo' in q and ('entrega' in q or 'retirar' in q):
  rows=list(c.execute("SELECT o.code,cl.name,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.status='listo' ORDER BY o.id DESC LIMIT 10"))
  return 'Órdenes listas para entregar: '+('; '.join(f"{r['code']} · {r['name']} · {r['brand'] or ''} {r['model'] or ''}" for r in rows) if rows else 'ninguna.')
 if 'esperan respuesta' in q or 'esperando respuesta' in q:
  n=c.execute("SELECT count(*) FROM orders WHERE status='esperando_cliente'").fetchone()[0];return f"Hay {n} orden(es) que esperan respuesta del cliente."
 if 'presupuesto' in q:
  rows=list(c.execute("SELECT o.code,cl.name,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.status='presupuesto' ORDER BY o.id DESC LIMIT 10"))
  return 'Presupuestos pendientes: '+('; '.join(f"{r['code']} · {r['name']} · {r['brand'] or ''} {r['model'] or ''}" for r in rows) if rows else 'ninguno.')
 if 'cita' in q:
  from datetime import timedelta
  day=appointments.now().date()+timedelta(days=1) if 'mañana' in q else appointments.now().date()
  start=appointments.stamp(appointments.datetime.combine(day,appointments.time.min,appointments.TZ));end=appointments.stamp(appointments.datetime.combine(day+timedelta(days=1),appointments.time.min,appointments.TZ))
  rows=appointments.admin_rows(c,start,end)
  return f"Citas del {day.strftime('%d/%m/%Y')}: "+('; '.join(f"{r['starts_at'][11:16]} · {r['customer_name']} · {r['service_label']} · {appointments.STATUSES[r['status']]}" for r in rows) if rows else 'ninguna.')
 if 'mantenimiento' in q:
  rows=[r for r in maintenance.rows(c) if r['state'] in ('scheduled','appointment')][:10]
  return 'Próximos mantenimientos: '+('; '.join(f"{r['code']} · {r['client']} · {r['due_date']}" for r in rows) if rows else 'ninguno programado.')
 match=re.search(r'PCD-\d{8}-\d{4,}',text,re.I)
 if match and 'historial' in q:
  rows=c.execute("SELECT o.code,h.status_label,h.comment,h.occurred_at,u.name actor FROM orders o JOIN order_history h ON h.order_id=o.id LEFT JOIN users u ON u.id=h.actor_id WHERE o.code=? ORDER BY h.id DESC LIMIT 10",(match[0],)).fetchall()
  return 'Historial registrado: '+('; '.join(f"{r['occurred_at']} · {r['status_label']} · {r['comment']} · {r['actor'] or 'sistema'}" for r in rows) if rows else 'no hay eventos disponibles para esa orden.')
 if 'redact' in q or 'notificación' in q:
  return 'Puedo ayudarte a redactar un mensaje. Incluye únicamente el estado o el dato ya confirmado que deseas comunicar; revisa el texto antes de enviarlo.'
 return None

def snapshot(c,now):
 """Indicadores del taller en este momento; todo sale de la base, sin estimaciones."""
 from datetime import timedelta
 today=now.date().isoformat()
 count=lambda sql,*args:c.execute(sql,args).fetchone()[0]
 start=appointments.stamp(appointments.datetime.combine(now.date(),appointments.time.min,appointments.TZ));end=appointments.stamp(appointments.datetime.combine(now.date()+timedelta(days=1),appointments.time.min,appointments.TZ))
 statuses={r['status']:r['total'] for r in c.execute('SELECT status,COUNT(*) total FROM orders GROUP BY status')}
 upcoming=c.execute("SELECT customer_name,starts_at FROM appointments WHERE deleted_at IS NULL AND starts_at>=? AND starts_at<? AND status IN ('solicitada','confirmada','reprogramada') ORDER BY starts_at LIMIT 1",(appointments.stamp(now),end)).fetchone()
 return {'updated_at':now.isoformat(timespec='seconds'),'statuses':{code:statuses.get(code,0) for code in order_workspace.STATUSES},'active':sum(total for code,total in statuses.items() if code!='entregado'),
  'overdue':count("SELECT COUNT(*) FROM orders WHERE estimated_delivery!='' AND estimated_delivery<? AND status!='entregado'",today),
  'received_today':count("SELECT COUNT(*) FROM orders WHERE substr(received_at,1,10)=?",today),'delivered_today':count("SELECT COUNT(*) FROM orders WHERE substr(COALESCE(delivered_at,''),1,10)=?",today),
  'appointments_today':count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND starts_at>=? AND starts_at<? AND status IN ('solicitada','confirmada','reprogramada')",start,end),
  'next_appointment':(upcoming['starts_at'][11:16]+' · '+upcoming['customer_name']) if upcoming else '',
  'appointments_requested':count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status='solicitada' AND starts_at>=?",appointments.stamp(now)),
  'clients':count('SELECT COUNT(*) FROM clients'),'clients_review':count('SELECT COUNT(*) FROM clients WHERE needs_review=1'),
  'chats_waiting':count("SELECT COUNT(*) FROM adi_conversations WHERE mode='human'"),'accounts_pending':count("SELECT COUNT(*) FROM users WHERE approval='pending'")}

def order_rows(c,where,args=(),limit=8):
 return c.execute("SELECT o.id,o.code,cl.name,d.brand,d.model,s.label status,o.estimated_delivery FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status WHERE "+where+" ORDER BY o.id DESC LIMIT ?",(*args,limit)).fetchall()

def order_line(r):return f"{r['code']} · {r['name']} · {' '.join(x for x in (r['brand'],r['model']) if x) or 'equipo sin especificar'}"

def admin_reply(c,text,now):
 """Respuesta administrativa con enlaces a los módulos. Solo lectura: nunca ejecuta cambios."""
 q=plain(text);live=snapshot(c,now);today=now.date().isoformat();link=lambda label,href:{'label':label,'href':href}
 has=lambda *keys:any(k in q for k in keys)
 match=re.search(r'PCD-\d{8}-\d{4,}',text,re.I)
 if match and not has('historial'):
  row=c.execute("SELECT o.id,o.code,s.label status,cl.name,d.brand,d.model,o.estimated_delivery,o.priority FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.code=?",(match[0].upper(),)).fetchone()
  if not row:return {'answer':'No existe una orden con el número '+match[0].upper()+'.','links':[link('Ver órdenes','#orders')]}
  return {'answer':f"{row['code']} está en «{row['status']}». Cliente: {row['name']}. Equipo: {' '.join(x for x in (row['brand'],row['model']) if x) or 'sin especificar'}. Entrega estimada: {row['estimated_delivery'] or 'sin definir'}.",'links':[link('Abrir la orden','#orders?id='+str(row['id']))]}
 if has('resumen','como va','como esta el taller','estado del taller','que hay hoy','panorama') or q in ('hoy','dia'):
  s=live['statuses'];parts=[f"{live['active']} órdenes activas ({s['pendiente']} en espera, {s['reparacion']} en proceso, {s['esperando_cliente']+s['presupuesto']} esperando al cliente, {s['listo']+s['espera_entrega']} listas para entregar)",f"{live['received_today']} recibidas y {live['delivered_today']} entregadas hoy",f"{live['overdue']} con entrega vencida",f"{live['appointments_today']} citas para hoy"+(' (próxima: '+live['next_appointment']+')' if live['next_appointment'] else '')]
  if live['appointments_requested']:parts.append(f"{live['appointments_requested']} citas por confirmar")
  if live['chats_waiting']:parts.append(f"{live['chats_waiting']} conversaciones esperando a un asesor")
  if live['accounts_pending']:parts.append(f"{live['accounts_pending']} solicitudes de cuenta por revisar")
  return {'answer':'Resumen del taller: '+'; '.join(parts)+'.','links':[link('Centro de Operaciones','#home'),link('Órdenes activas','#orders?active=1')]}
 if has('vencid','atrasad','retras','fuera de plazo'):
  rows=order_rows(c,"o.estimated_delivery!='' AND o.estimated_delivery<? AND o.status!='entregado'",(today,))
  return {'answer':(f"Hay {live['overdue']} orden(es) con entrega vencida: "+'; '.join(order_line(r)+' (prevista '+r['estimated_delivery']+')' for r in rows)+'.') if rows else 'No hay órdenes con la entrega vencida.','links':[link('Órdenes activas','#orders?active=1')]}
 if has('procesando','en proceso','en reparacion','reparando'):
  rows=order_rows(c,"o.status='reparacion'")
  return {'answer':(f"Hay {live['statuses']['reparacion']} orden(es) en proceso: "+'; '.join(order_line(r) for r in rows)+'.') if rows else 'No hay órdenes en proceso.','links':[link('Ver en proceso','#orders?status=reparacion')]}
 if has('entregad') and has('hoy'):
  return {'answer':f"Hoy se han entregado {live['delivered_today']} equipo(s) y se han recibido {live['received_today']}.",'links':[link('Órdenes entregadas','#orders?status=entregado')]}
 if has('recibid','ingresad','ingresaron','entraron') and has('hoy'):
  rows=order_rows(c,"substr(o.received_at,1,10)=?",(today,))
  return {'answer':(f"Hoy se recibieron {live['received_today']} orden(es): "+'; '.join(order_line(r) for r in rows)+'.') if rows else 'Hoy todavía no se ha recibido ningún equipo.','links':[link('Ver órdenes','#orders')]}
 if has('cliente') and has('cuant','total','numero'):
  return {'answer':f"Hay {live['clients']} clientes registrados; {live['clients_review']} tienen la ficha por completar.",'links':[link('Clientes','#clients'),link('Fichas por completar','#clients?filter=review')]}
 found=re.search(r'(?:cliente|buscar?|ordenes de)\s+(?:a\s+|de\s+|llamad[oa]\s+)?([a-z0-9ñ@. ]{3,60})$',q)
 if found and not has('cuant'):
  term=found[1].strip()
  rows=c.execute("SELECT c.id,c.name,c.phone,(SELECT COUNT(*) FROM orders o JOIN devices d ON d.id=o.device_id WHERE d.client_id=c.id) orders FROM clients c WHERE instr(lower(c.name||' '||c.identification||' '||COALESCE(c.phone,'')||' '||COALESCE(c.email,'')||' '||c.trade_name),?)>0 ORDER BY c.name LIMIT 6",(term,)).fetchall()
  if rows:return {'answer':f"Encontré {len(rows)}{' o más' if len(rows)==6 else ''} cliente(s) para «{term}»: "+'; '.join(f"{r['name']} ({r['orders']} órdenes)" for r in rows)+'.','links':[link(r['name'][:40],'#clients?id='+str(r['id'])) for r in rows[:4]]}
  return {'answer':f"No encontré clientes que coincidan con «{term}».",'links':[link('Clientes','#clients')]}
 if has('solicitud') and has('cuenta','acceso','usuario'):
  return {'answer':f"Hay {live['accounts_pending']} solicitud(es) de cuenta por revisar.",'links':[link('Usuarios y permisos','#settings?tab=users')]}
 if has('conversacion','chat','asesor'):
  return {'answer':f"Hay {live['chats_waiting']} conversación(es) esperando a un asesor.",'links':[link('Atención en vivo','#live')]}
 factual=admin_answer(c,text)
 if factual:
  links=[link('Agenda de citas','#appointments')] if 'cita' in q else [link('Mantenimientos','#maintenance')] if 'mantenimiento' in q else [link('Órdenes','#orders?active=1')]
  return {'answer':factual,'links':links}
 if has('cuantas ordenes','total de ordenes','ordenes activas','ordenes hay'):
  return {'answer':f"Hay {live['active']} órdenes activas y {live['statuses']['entregado']} entregadas en total.",'links':[link('Órdenes activas','#orders?active=1')]}
 if has('redact','notificacion','mensaje para','correo para'):
  drafted=ask(text,admin=True)
  if drafted:return {'answer':drafted,'links':[],'source':'ia'}
 return {'answer':'Puedo responder con datos reales del sistema sobre: resumen del taller, órdenes en espera, en proceso, vencidas, listas para entregar o por número (PCD-…), presupuestos, recibidas o entregadas hoy, citas de hoy o mañana, mantenimientos, clientes y solicitudes de cuenta. No ejecuto cambios: esos se hacen en cada módulo.','links':[],'source':'guia'}

def ask(text,admin=False,context=None):
 api_key=os.getenv('OPENAI_API_KEY','').strip()
 if not api_key:return None
 payload={'model':os.getenv('OPENAI_MODEL','gpt-4.1-mini'),'instructions':SYSTEM_ADMIN if admin else SYSTEM_PUBLIC,'input':text[:3000],'max_output_tokens':350}
 if context:payload['instructions']+=' Contexto validado del sistema: '+str(context)[:3500]
 req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=12) as response:data=json.loads(response.read(50000))
  parts=[]
  for item in data.get('output',[]):
   if item.get('type')=='message':
    parts.extend(part.get('text','') for part in item.get('content',[]) if part.get('type')=='output_text')
  answer=' '.join(parts).strip()
  return answer[:2500] or None
 except (OSError,ValueError,KeyError,urllib.error.URLError):return None

def reply(c,text,admin=False,context=None):
 if admin:
  factual=admin_answer(c,text)
  if factual:return factual
 answer=ask(text,admin,context)
 if answer:return answer
 return fallback(c,text)

DAYS=('lunes','martes','miércoles','jueves','viernes','sábado','domingo')

def plain(text):
 import unicodedata
 return ''.join(ch for ch in unicodedata.normalize('NFD',text.casefold()) if not unicodedata.combining(ch))

def schedule_text(hours):
 """Agrupa días consecutivos con el mismo horario configurado en la agenda."""
 groups=[]
 for item in sorted((h for h in hours if h['enabled']),key=lambda h:h['weekday']):
  span=(item['start_time'],item['end_time'])
  if groups and groups[-1][2]==span and groups[-1][1]==item['weekday']-1:groups[-1][1]=item['weekday']
  else:groups.append([item['weekday'],item['weekday'],span])
 return '; '.join((DAYS[a] if a==b else DAYS[a]+' a '+DAYS[b])+' de '+span[0]+' a '+span[1] for a,b,span in groups)

def fallback(c,text):
 """Respuestas sin IA externa: solo datos configurados en el sistema, sin precios, diagnósticos ni plazos inventados."""
 import corporate
 q=plain(text);words=set(re.findall(r'[a-z0-9]+',q));company=corporate.settings();cfg=appointments.settings(c)
 has=lambda *keys:any(k in q for k in keys)
 if 'estado' in q or 'orden' in q or 'pcd-' in q or has('mi equipo','mi reparacion','seguimiento'):
  match=re.search(r'(PCD-\d{8}-\d{4,}).*?(\d{10}|\d{13})',text,re.I)
  if match:
   row=order_status(c,match[1].upper(),match[2])
   if row:return f"Tu orden {row['code']} está en estado «{row['status']}». Equipo: {row['brand'] or ''} {row['model'] or ''}. Para más información, solicita atención del taller."
   return 'No encuentro una orden con ese número y esa identificación. Revisa ambos datos tal como constan en tu comprobante o solicita un asesor.'
  return 'Para consultar una reparación, escribe en un solo mensaje el número de orden (por ejemplo PCD-20260101-0001) y la cédula o RUC registrados. No muestro información privada sin ambos datos.'
 if has('cita','agendar','agenda','reservar','reserva','turno'):
  return 'Puedes reservar tu cita en línea en /citas: elige el servicio, la fecha y una hora disponible. Recibirás un código para consultar, reprogramar o cancelar la cita.'
 if has('precio','costo','cuanto cuesta','cuanto vale','cuanto sale','cotiza','presupuesto','tarifa') or words&{'valor','vale','cobran'}:
  return 'El valor depende de la revisión técnica del equipo, por eso no puedo darte un precio por este medio. Puedes agendar un diagnóstico en /citas o pedir que un asesor te contacte con el botón «Solicitar un asesor».'
 if has('garantia'):
  return 'Las condiciones de garantía dependen del servicio realizado y constan en las condiciones de tu orden. Un asesor puede confirmarte tu caso: usa «Solicitar un asesor».'
 if has('horario','abren','abierto','atienden') or words&{'hora','horas'}:
  schedule=schedule_text(cfg['hours'])
  return ('Horario de atención de la agenda (hora de Ecuador): '+schedule+'.' if schedule else 'Por ahora no hay horarios de agenda habilitados.')+' Puedes ver las horas libres al reservar en /citas.'
 if has('contacto','whatsapp','telefono','llamar','correo','email','escribir'):
  return 'Puedes escribirnos por WhatsApp al '+company['whatsapp']+' o al correo '+company['support_email']+'. También puedo pasarte con un asesor en este chat.'
 if has('donde','direccion','ubicacion','ubicados','llegar') or words&{'local'}:
  return 'Para confirmar la dirección y cómo llegar, escríbenos por WhatsApp al '+company['whatsapp']+' o solicita un asesor en este chat.'
 if has('asesor','humano','persona','tecnico','alguien','operador'):
  return 'Con gusto. Pulsa «Solicitar un asesor» y una persona del equipo continuará la conversación en este mismo chat.'
 if has('servicio','reparacion','reparar','arreglar','diagnostico','mantenimiento','bios','impresora','laptop','portatil','computadora','formatear','virus','pantalla','lento','no enciende','no prende') or words&{'pc'}:
  services=', '.join(item['label'].lower() for item in cfg['services'] if item.get('active',1))
  return company['name']+' ofrece diagnóstico y reparación de portátiles, computadoras e impresoras, mantenimiento preventivo, programación de BIOS y reparación electrónica.'+(' En la agenda puedes reservar: '+services+'.' if services else '')+' El diagnóstico exacto requiere revisar el equipo; reserva en /citas.'
 if words&{'gracias','agradezco','genial','perfecto','excelente'}:
  return 'Con gusto. Si necesitas algo más, aquí estoy.'
 if words&{'adios','chao','chau'} or has('hasta luego','nos vemos'):
  return company['thanks']+' Que tengas un buen día.'
 if words&{'hola','buenas','buenos','saludos','hey','ola'}:
  return 'Hola, soy Adi, asistente virtual de '+company['name']+' Puedo ayudarte con servicios, citas, horarios, contacto y el estado de tu orden. ¿Qué necesitas?'
 return 'Soy Adi, asistente virtual de '+company['name']+' Puedo orientarte sobre servicios, citas, horarios, contacto y el estado de tu orden. Para una evaluación o presupuesto, el equipo técnico debe revisar el caso; si lo prefieres, solicita un asesor.'
