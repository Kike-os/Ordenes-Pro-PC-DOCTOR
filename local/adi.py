"""Respuestas acotadas de ADI. La IA nunca recibe permisos para ejecutar escrituras."""
import json,os,re,urllib.request,urllib.error
import appointments,order_workspace,maintenance,reception

SYSTEM_PUBLIC=("Eres ADI, asistente virtual de PC-DOCTOR S.A. Habla español latinoamericano con tono cálido, amable y profesional, como una recepcionista atenta. "
"Responde de forma breve y natural (normalmente de una a tres frases) y no repitas saludos ni la misma información; tus respuestas también se escuchan en voz alta. "
"Explica los servicios técnicos de manera sencilla. Mantén el contexto de la conversación. "
"Para precios usa ÚNICAMENTE los «precios_registrados_iva_incluido» del contexto validado; si el servicio no aparece, di que el taller lo confirmará con un presupuesto. "
"Cuando el cliente lo pida o el caso lo requiera (reclamos, garantías, decisiones del taller), ofrece hablar con un asesor humano. "
"Identifícate como asistente virtual cuando sea pertinente. No afirmes ser humana. "
"No inventes diagnósticos, precios, garantías, fechas de entrega ni avances. Para esos asuntos solicita revisión del taller. "
"No solicites contraseñas ni números completos de tarjetas. Reserva citas mediante el enlace del sistema. "
"Los horarios y la disponibilidad de citas vienen SIEMPRE en el contexto validado de cada mensaje: usa únicamente esos datos, distingue atención presencial, hora límite para solicitar citas y atención virtual, y no menciones ningún otro horario. No puedes reservar, reprogramar ni confirmar citas: indica que se reservan y confirman en /citas, y ofrece solo las horas libres que figuren en el contexto.")
SYSTEM_ADMIN=("Eres ADI, asistente administrativa de PC-DOCTOR S.A. Responde en español de forma clara. "
"Usa solamente los datos reales que aparecen en el contexto. No ejecutes cambios, envíos ni escrituras. "
"Para una modificación indica que debe confirmarla y ejecutarla un usuario autorizado.")

ORDER_CHECK_HINT='Para proteger tus datos, el estado de una reparación se consulta con un código temporal: pulsa «Consultar reparación», escribe tu número de orden y te enviaremos el código al correo registrado en ella.'

def order_status(c,code,identification):
 row=c.execute("SELECT o.code,s.label status,d.brand,d.model FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.code=? AND cl.identification=?",(reception.current_order_code(c,code),identification)).fetchone()
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
 match=re.search(r'(?:PCD-\d{8}-\d{4,}|OP-\d{4,})(?:-E\d{2})?',text,re.I)
 if match and 'historial' in q:
  rows=c.execute("SELECT o.code,h.status_label,h.comment,h.occurred_at,u.name actor FROM orders o JOIN order_history h ON h.order_id=o.id LEFT JOIN users u ON u.id=h.actor_id WHERE o.code=? ORDER BY h.id DESC LIMIT 10",(reception.current_order_code(c,match[0]),)).fetchall()
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
 match=re.search(r'(?:PCD-\d{8}-\d{4,}|OP-\d{4,})(?:-E\d{2})?',text,re.I)
 if match and not has('historial'):
  row=c.execute("SELECT o.id,o.code,s.label status,cl.name,d.brand,d.model,o.estimated_delivery,o.priority FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.code=?",(reception.current_order_code(c,match[0]),)).fetchone()
  if not row:return {'answer':'No existe una orden con el número '+match[0].upper()+'.','links':[link('Ver órdenes','#orders')]}
  return {'answer':f"{row['code']} está en «{row['status']}». Cliente: {row['name']}. Equipo: {' '.join(x for x in (row['brand'],row['model']) if x) or 'sin especificar'}. Entrega estimada: {row['estimated_delivery'] or 'sin definir'}.",'links':[link('Abrir la orden','#orders?id='+str(row['id']))]}
 if has('inasistencia','no asistio','no asistieron','reagend'):
  # Inasistencias de los últimos 7 días, enlaces enviados y citas reagendadas. Solo lectura.
  since=(now-appointments.timedelta(days=7)).isoformat()
  missed=c.execute("SELECT COUNT(*) FROM appointment_events WHERE event='no_show_auto' AND created_at>=?",(since,)).fetchone()[0]
  sent=c.execute("SELECT COUNT(*) FROM appointment_reschedule_links WHERE mail_status='enviado' AND created_at>=?",(since,)).fetchone()[0]
  failed=c.execute("SELECT COUNT(*) FROM appointment_reschedule_links WHERE mail_status='error' AND created_at>=?",(since,)).fetchone()[0]
  again=c.execute("SELECT COUNT(*) FROM appointment_reschedule_links WHERE used_at>=?",(since,)).fetchone()[0]
  answer=('En los últimos siete días se registraron %d inasistencias automáticas; %d clientes recibieron su enlace de reagendamiento%s y %d reagendaron su cita.'%(missed,sent,(' (%d con error de envío)'%failed) if failed else '',again)) if missed or sent or again else 'No se registraron inasistencias en los últimos siete días.'
  return {'answer':answer,'links':[link('Abrir la agenda','#appointments')]}
 if has('licencia','renovacion','renovar','vencen','por vencer'):
  # Licencias Pro: próximas renovaciones (7 días) y resultado real de los recordatorios enviados. Solo lectura.
  import licenses
  soon=[u for u in licenses.expiring(c,now,500) if 0<=u['days_left']<=7]
  ids=[u['id'] for u in soon];marks=','.join('?'*len(ids)) or 'NULL'
  sent={r[0] for r in c.execute("SELECT DISTINCT unit_id FROM license_notices WHERE status='enviado' AND unit_id IN (%s)"%marks,ids)} if ids else set()
  failed={r[0] for r in c.execute("SELECT DISTINCT unit_id FROM license_notices WHERE status='error' AND unit_id IN (%s)"%marks,ids)}-sent if ids else set()
  if not soon:answer='No hay licencias que venzan durante los próximos siete días.'
  else:
   n=len(soon);answer=('Tiene %d licencia%s próxima%s a vencer durante los siguientes siete días.'%(n,'' if n==1 else 's','' if n==1 else 's'))
   answer+=' %d cliente%s ya recibi%s su recordatorio'%(len(sent),'' if len(sent)==1 else 's','ó' if len(sent)==1 else 'eron') if sent else ' Ningún cliente recibió todavía su recordatorio'
   answer+=(' y %d presenta%s un error de envío.'%(len(failed),'' if len(failed)==1 else 'n') if failed else '.')
  return {'answer':answer,'links':[link('Abrir Licencias Pro','#licenses')]}
 if has('resumen','como va','como esta el taller','estado del taller','que hay hoy','panorama') or q in ('hoy','dia'):
  s=live['statuses'];parts=[f"{live['active']} órdenes activas ({s['pendiente']} en espera, {s['reparacion']+s.get('revision_recurrente',0)} en proceso, {s['esperando_cliente']+s['presupuesto']} esperando al cliente, {s['listo']+s['espera_entrega']} listas para entregar)",f"{live['received_today']} recibidas y {live['delivered_today']} entregadas hoy",f"{live['overdue']} con entrega vencida",f"{live['appointments_today']} citas para hoy"+(' (próxima: '+live['next_appointment']+')' if live['next_appointment'] else '')]
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
  links=[link('Agenda de Citas','#appointments')] if 'cita' in q else [link('Mantenimientos','#maintenance')] if 'mantenimiento' in q else [link('Órdenes','#orders?active=1')]
  return {'answer':factual,'links':links}
 if has('cuantas ordenes','total de ordenes','ordenes activas','ordenes hay'):
  return {'answer':f"Hay {live['active']} órdenes activas y {live['statuses']['entregado']} entregadas en total.",'links':[link('Órdenes activas','#orders?active=1')]}
 if has('redact','notificacion','mensaje para','correo para'):
  drafted=ask(text,admin=True)
  if drafted:return {'answer':drafted,'links':[],'source':'ia'}
 return {'answer':'Puedo responder con datos reales del sistema sobre: resumen del taller, órdenes en espera, en proceso, vencidas, listas para entregar o por número (PCD-…), presupuestos, recibidas o entregadas hoy, citas de hoy o mañana, mantenimientos, clientes y solicitudes de cuenta. No ejecuto cambios: esos se hacen en cada módulo.','links':[],'source':'guia'}

def ask(text,admin=False,context=None):
 import adi_ai
 api_key=adi_ai.openai_key()
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

def catalog_prices(c,text,limit=25):
 """Servicios y productos disponibles del catálogo con su precio final (IVA incluido). Primero los que coinciden con la consulta."""
 import quotes
 words=[w for w in re.findall(r'[a-záéíóúñ0-9]{4,}',plain(text)) if w not in ('precio','cuanto','cuesta','costo','valor','tarifa','servicio','servicios','quiero','tienen','cobran')]
 rows=[r for r in quotes.catalog(c,only_available=True) if not r['tax_pending']]
 score=lambda r:sum(1 for w in words if w in plain(r['name']+' '+(r['description'] or '')))
 rows.sort(key=lambda r:-score(r))
 return [{'nombre':r['name'],'precio':quotes.usd(r['price_cents'])} for r in rows[:limit]] or 'sin precios registrados'

def _dot(text):
 return text if text.endswith('.') else text+'.'

def hours_facts(c,now=None):
 """Horarios vigentes leídos del sistema en cada consulta: atención presencial (y si está abierta ahora), franjas de la Agenda de Citas y atención virtual."""
 import business_hours
 from reception import ECUADOR_TZ
 from datetime import datetime
 info=business_hours.public(c,now or datetime.now(ECUADOR_TZ));agenda=schedule_text(appointments.settings(c)['hours'])
 config=business_hours.get(c);limits=business_hours.limits_text(config)
 # No se citan las franjas internas de la agenda como «horario»: las horas concretas se consultan siempre en la disponibilidad real.
 return {'zona_horaria':'America/Guayaquil (Ecuador)','hoy':info['today'],'hora_actual':info['now'],'atencion_presencial':info['presencial'] or 'sin horario presencial configurado','estado_presencial_ahora':info['status']['label'],
         'cierres_extraordinarios':[item['date']+(' ('+item['note']+')' if item['note'] else '') for item in info['closures']],
         'solicitud_de_citas':(_dot('Las solicitudes de cita en línea se reciben: '+limits)+' Esa hora límite es para enviar la solicitud; no significa que haya técnicos atendiendo hasta entonces.') if limits else 'Las solicitudes de cita en línea se reciben a cualquier hora.',
         'citas':'Las citas se atienden dentro del horario presencial y solo en las horas que la agenda tenga libres; se reservan y confirman en /citas.',
         'atencion_virtual':info['virtual_message'] or 'No disponible','asesores_humanos':'Los asesores responden en el horario de atención presencial; fuera de ese horario la solicitud queda registrada.'}

def booking_link(day,hour,service):
 """Enlace interno que abre la Agenda de Citas con fecha, hora y servicio ya elegidos. El chat lo muestra como botón «Reservar…».
 No reserva nada: el cliente completa sus datos y consentimientos en /citas, y la disponibilidad se vuelve a comprobar al confirmar."""
 return '/citas?fecha=%s&hora=%s&servicio=%s'%(day,hour,service)

def next_slots(c,limit=3):
 """Próximas horas realmente libres en la agenda (el mismo cálculo que usa la página de reservas), para un diagnóstico o el primer servicio activo."""
 from datetime import timedelta
 service=c.execute("SELECT code,label FROM appointment_services WHERE active=1 ORDER BY (code='diagnostico') DESC,rowid LIMIT 1").fetchone()
 if not service:return []
 found=appointments.alternatives(c,(appointments.now().date()+timedelta(days=1)).isoformat(),service['code'],'',False,limit)
 return [{'servicio':service['label'],'fecha':item['date'],'hora':item['time'],'enlace':booking_link(item['date'],item['time'],service['code']),'texto':item['date'][8:]+'/'+item['date'][5:7]+' a las '+appointments.clock12(item['time'])} for item in found]

def hours_answer(c,now=None,topic=''):
 """Respuesta breve sobre horarios, sin IA: distingue atención presencial, solicitud de citas y atención virtual."""
 facts=hours_facts(c,now);presencial=_dot('Atención presencial (hora de Ecuador): '+facts['atencion_presencial'])+' '+_dot(facts['estado_presencial_ahora'])
 if topic=='virtual':return (facts['atencion_virtual'] if facts['atencion_virtual']!='No disponible' else 'La atención virtual no está activa en este momento.')+' '+_dot('La atención presencial es: '+facts['atencion_presencial'])
 if topic=='solicitud':return facts['solicitud_de_citas']+' '+facts['citas']
 lines=[presencial,facts['solicitud_de_citas'],facts['citas']]
 if facts['atencion_virtual']!='No disponible':lines.append(facts['atencion_virtual'])
 return ' '.join(lines)

def requested_slot(text,now=None):
 """Fecha y hora que pide el cliente en frases como «mañana a las 10:00 a. m.» o «hoy a las 4 de la tarde». Devuelve (fecha, 'HH:MM') o None."""
 from datetime import timedelta
 q=plain(text);base=(now or appointments.now()).astimezone(appointments.TZ).date();rest=q.replace('de la manana','')
 day=base+timedelta(days=2) if 'pasado manana' in rest else base+timedelta(days=1) if re.search(r'\bmanana\b',rest) else base if re.search(r'\bhoy\b',rest) else None
 match=re.search(r'\b(\d{1,2})(?:[:.h](\d{2}))?\s*(a\.?\s?m\b\.?|p\.?\s?m\b\.?|de la manana|de la tarde|de la noche|horas|hrs)?',q)
 if not match or day is None:return None
 hour,minute,suffix=int(match[1]),int(match[2] or 0),(match[3] or '').replace(' ','').replace('.','')
 if suffix in ('pm','delatarde','delanoche') and hour<12:hour+=12
 if suffix=='am' and hour==12:hour=0
 if not (0<=hour<24 and 0<=minute<60) or not (match[2] or match[3]):return None
 return day.isoformat(),'%02d:%02d'%(hour,minute)

def slot_answer(c,text,now=None):
 """Comprueba en la agenda real la hora que pide el cliente. No reserva nada: la cita se confirma en /citas."""
 wanted=requested_slot(text,now)
 if not wanted:return None
 day,hour=wanted;service=c.execute("SELECT code,label FROM appointment_services WHERE active=1 ORDER BY (code='diagnostico') DESC,rowid LIMIT 1").fetchone()
 if not service:return None
 label=day[8:]+'/'+day[5:7]+' a las '+appointments.clock12(hour)
 try:free=[item['time'] for item in appointments.available_slots(c,day,service['code'])]
 except ValueError:free=[]
 if hour in free:return 'El '+label+' está libre en este momento para '+service['label'].lower()+'. Toca para reservarlo:\n'+booking_link(day,hour,service['code'])+'\nCompletarás tus datos en la Agenda de Citas; la cita queda confirmada cuando el sistema te muestra su código.'
 options=appointments.alternatives(c,day,service['code'],hour,False,3) or appointments.alternatives(c,day,service['code'],'',False,3)
 if options:return 'El '+label+' no está disponible. Opciones libres más próximas (toca una para reservarla):\n'+'\n'.join(booking_link(item['date'],item['time'],service['code']) for item in options)+'\nTambién puedes elegir otra fecha en /citas.'
 return 'El '+label+' no está disponible y no veo espacios libres en los próximos días. Un asesor puede ayudarte: usa «Contactar soporte técnico».'

def reply(c,text,admin=False,context=None):
 if admin:
  factual=admin_answer(c,text)
  if factual:return factual
 # Una fecha y hora concretas se responden con la comprobación real de la agenda, sin pasar por el modelo: así nunca se inventa ni se
 # niega una disponibilidad. (En producción el modelo llegó a decir que una hora libre no lo estaba.)
 if not admin:
  try:
   checked=slot_answer(c,text)
   if checked:return checked
  except Exception:pass
 # Los horarios vigentes viajan siempre como contexto validado: ADI no usa horarios escritos de memoria.
 if not admin:
  try:
   context=dict(context or {},horarios_vigentes=hours_facts(c))
   # Precios: solo los registrados en el catálogo (con IVA incluido); ADI no calcula ni promete otros.
   if re.search(r'precio|cu[aá]nto|cuesta|costo|valor|tarifa|cobr|servicio',plain(text)):context['precios_registrados_iva_incluido']=catalog_prices(c,text)
   if re.search(r'cita|agend|reserv|turno|disponib',plain(text)):context['proximos_espacios_libres_en_la_agenda']=next_slots(c) or 'sin espacios libres en los próximos días';context['como_reservar']='La reserva se hace y se confirma en /citas; ADI no confirma citas por sí misma.'
  except Exception:pass
 answer=ask(text,admin,context) or fallback(c,text)
 # Si el cliente quiere una cita, la respuesta termina con los próximos horarios realmente libres como botones de reserva.
 # Se añaden aquí, desde la agenda, para que no dependan de lo que redacte el modelo.
 if not admin and isinstance(context,dict) and isinstance(context.get('proximos_espacios_libres_en_la_agenda'),list) and '/citas?fecha=' not in answer:
  answer=answer.rstrip()+'\nPróximos horarios libres (toca uno para reservarlo):\n'+'\n'.join(item['enlace'] for item in context['proximos_espacios_libres_en_la_agenda'])
 return answer

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
  return ORDER_CHECK_HINT
 if has('virtual','medianoche','madrugada','24 horas','las 24'):return hours_answer(c,topic='virtual')
 if has('cita','agendar','agenda','reservar','reserva','turno'):
  checked=slot_answer(c,text)
  if checked:return checked
  if has('hasta que hora','hasta cuando','limite','solicitar'):return hours_answer(c,topic='solicitud')
  # Solo se ofrecen horas que la agenda tiene libres en este momento; la reserva se confirma en /citas, que vuelve a comprobarlas.
  slots=next_slots(c)
  free=' Próximos espacios libres para '+slots[0]['servicio'].lower()+': '+_dot('; '.join(item['texto'] for item in slots)) if slots else ' En este momento no veo espacios libres en los próximos días.'
  return 'Puedes reservar tu cita en línea en /citas: elige el servicio, la fecha y una hora disponible.'+free+' La cita queda confirmada cuando el sistema te muestra su código.'
 if has('precio','costo','cuanto cuesta','cuanto vale','cuanto sale','cotiza','presupuesto','tarifa') or words&{'valor','vale','cobran'}:
  return 'El valor depende de la revisión técnica del equipo, por eso no puedo darte un precio por este medio. Puedes agendar un diagnóstico en /citas o pedir que un asesor te contacte con el botón «Contactar soporte técnico».'
 if has('garantia'):
  return 'Las condiciones de garantía dependen del servicio realizado y constan en las condiciones de tu orden. Un asesor puede confirmarte tu caso: usa «Contactar soporte técnico».'
 if has('horario','abren','abierto','atienden','domingo','sabado','feriado') or words&{'hora','horas'}:
  return hours_answer(c)
 if has('contacto','whatsapp','telefono','llamar','correo','email','escribir'):
  return 'Puedes escribirnos por WhatsApp al '+company['whatsapp']+' o al correo '+company['support_email']+'. También puedo pasarte con un asesor en este chat.'
 if has('donde','direccion','ubicacion','ubicados','llegar') or words&{'local'}:
  return 'Para confirmar la dirección y cómo llegar, escríbenos por WhatsApp al '+company['whatsapp']+' o solicita un asesor en este chat.'
 if has('asesor','humano','persona','tecnico','alguien','operador'):
  return 'Con gusto. Pulsa «Contactar soporte técnico» y una persona del equipo continuará la conversación en este mismo chat.'
 if has('servicio','reparacion','reparar','arreglar','diagnostico','mantenimiento','bios','impresora','laptop','portatil','computadora','formatear','virus','pantalla','lento','no enciende','no prende') or words&{'pc'}:
  services=', '.join(item['label'].lower() for item in cfg['services'] if item.get('active',1))
  return company['name']+' ofrece diagnóstico y reparación de portátiles, computadoras e impresoras, mantenimiento preventivo, programación de BIOS y reparación electrónica.'+(' En la agenda puedes reservar: '+services+'.' if services else '')+' El diagnóstico exacto requiere revisar el equipo; reserva en /citas.'
 if words&{'gracias','agradezco','genial','perfecto','excelente'}:
  return 'Con gusto. Si necesitas algo más, aquí estoy.'
 if words&{'adios','chao','chau'} or has('hasta luego','nos vemos'):
  return company['thanks']+' Que tengas un buen día.'
 if words&{'hola','buenas','buenos','saludos','hey','ola'}:
  return 'Hola, soy ADI, asistente virtual de '+company['name']+' Puedo ayudarte con servicios, citas, horarios, contacto y el estado de tu orden. ¿Qué necesitas?'
 return 'Soy ADI, asistente virtual de '+company['name']+' Puedo orientarte sobre servicios, citas, horarios, contacto y el estado de tu orden. Para una evaluación o presupuesto, el equipo técnico debe revisar el caso; si lo prefieres, solicita un asesor.'
