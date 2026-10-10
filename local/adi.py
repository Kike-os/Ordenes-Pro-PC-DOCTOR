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
 q=text.casefold()
 if any(k in q for k in ('servicio','reparación','reparacion','diagnóstico','diagnostico','bios','impresora')):
  return 'PC-DOCTOR S.A. ofrece diagnóstico y reparación de portátiles, computadoras e impresoras, mantenimiento preventivo, programación de BIOS y reparación electrónica. Puedes solicitar una cita en /citas.'
 if any(k in q for k in ('horario','atención','atencion','contacto','whatsapp')):
  cfg=appointments.settings(c);hours=[h for h in cfg['hours'] if h['enabled']]
  return 'La agenda de citas muestra los horarios disponibles y está configurada en hora de Ecuador. WhatsApp: +593 98 746 0591. Sitio: https://ordenes-pro.ecuadorpcdoctor.com/.'
 if 'estado' in q or 'orden' in q:
  match=re.search(r'(PCD-\d{8}-\d{4,}).*?(\d{10}|\d{13})',text,re.I)
  if match:
   row=order_status(c,match[1].upper(),match[2])
   if row:return f"Tu orden {row['code']} está en estado «{row['status']}». Equipo: {row['brand'] or ''} {row['model'] or ''}. Para más información, solicita atención del taller."
  return 'Para consultar una reparación, comparte el número de orden y confirma la identificación asociada. No encuentro información privada sin ambos datos.'
 return 'Soy Adi, asistente virtual de PC-DOCTOR S.A. Puedo orientarte sobre servicios, citas y seguimiento. Para una evaluación o presupuesto, el equipo técnico debe revisar el caso.'
