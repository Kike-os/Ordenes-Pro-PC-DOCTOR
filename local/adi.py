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
