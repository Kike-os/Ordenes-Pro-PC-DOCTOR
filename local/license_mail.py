"""Correos de Licencias Pro: avisos de renovación a clientes (30, 15, 7 y 1 días antes y el día del vencimiento, configurables) y envío
manual de la información autorizada de una licencia. Plantilla HTML corporativa adaptable a teléfonos, con el logo de PC-DOCTOR S.A., el
logo del producto y el botón «SOLICITAR RENOVACIÓN» (WhatsApp con un mensaje preparado). Nunca incluye claves, seriales ni contraseñas.

Un aviso por licencia, vencimiento y anticipación (license_notices); si falla el envío se reintenta como máximo MAX_ATTEMPTS veces.
«Enviado» significa aceptado por el servidor de correo; la entrega solo se marca con la confirmación del proveedor (seguimiento de correos)."""
import html,json,re
from datetime import date,timedelta
from email.message import EmailMessage
from email.utils import formatdate,make_msgid
from pathlib import Path
from urllib.parse import quote

DEFAULTS={'enabled':False,'days':[30,15,7,1,0],'subject':'Recordatorio de renovación de licencia | PC-DOCTOR S.A.',
          'intro':'Le informamos que su licencia de software está próxima a finalizar su período de vigencia.\n\nPara garantizar la continuidad de los servicios y beneficios asociados a su producto, le recomendamos gestionar oportunamente su renovación.'}
STAGES={30:'Recordatorio preventivo',15:'Invitación a renovar',7:'Aviso de próximo vencimiento',1:'Recordatorio urgente',0:'Notificación de vencimiento'}
MAX_ATTEMPTS=3
RETRY_HOURS=6
WHATSAPP='593987460591'
SITE='www.ecuadorpcdoctor.com'
BLUE='#1d4ed8'
ROOT=Path(__file__).resolve().parent


class NoticeError(ValueError):
    def __init__(self,message,fields=None):super().__init__(message);self.fields=fields or {}


def settings(c):
    row=c.execute("SELECT value FROM system_state WHERE key='license_notices'").fetchone()
    data=dict(DEFAULTS)
    if row:
        try:data.update({k:v for k,v in json.loads(row['value']).items() if k in DEFAULTS})
        except (ValueError,TypeError):pass
    return data


def save_settings(c,data,now):
    days=sorted({int(d) for d in str(data.get('days','')).replace(';',',').split(',') if d.strip().isdigit()},reverse=True)
    if not days or len(days)>6 or any(d>90 for d in days):raise NoticeError('Indica de 1 a 6 anticipaciones entre 0 y 90 días (por ejemplo: 30, 15, 7, 1, 0).',{'days':'Días no válidos.'})
    subject=re.sub(r'\s+',' ',str(data.get('subject') or '')).strip();intro=str(data.get('intro') or '').strip()
    if not 5<=len(subject)<=150:raise NoticeError('El asunto debe tener de 5 a 150 caracteres.',{'subject':'Asunto no válido.'})
    if not 20<=len(intro)<=1500:raise NoticeError('El mensaje debe tener de 20 a 1500 caracteres.',{'intro':'Mensaje no válido.'})
    value={'enabled':data.get('enabled') is True,'days':days,'subject':subject,'intro':intro}
    c.execute("INSERT INTO system_state(key,value) VALUES ('license_notices',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value,ensure_ascii=False),))
    return value


def opted_out(c,client_id):
    return bool(client_id and c.execute('SELECT 1 FROM license_notice_optout WHERE client_id=?',(client_id,)).fetchone())


def set_optout(c,client_id,off,user,now):
    if off:c.execute('INSERT OR IGNORE INTO license_notice_optout(client_id,created_at,created_by) VALUES (?,?,?)',(client_id,now.isoformat(timespec='seconds'),user['id']))
    else:c.execute('DELETE FROM license_notice_optout WHERE client_id=?',(client_id,))


def _valid_mail(value):
    return bool(re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+',str(value or '').strip()))


def plan(c,now):
    """Crea los avisos que tocan hoy (hora de Ecuador) y devuelve los pendientes de enviar, incluidos los reintentos. Sin duplicados:
    un aviso por licencia, vencimiento y anticipación. No avisa de perpetuas, sin vencimiento, renovadas, anuladas ni a clientes excluidos."""
    config=settings(c);today=now.date();stamp=now.isoformat(timespec='seconds')
    if config['enabled']:
        days=config['days']
        for unit in c.execute("SELECT u.id,u.client_id,u.expires_at,cl.email FROM license_units u JOIN clients cl ON cl.id=u.client_id JOIN license_products p ON p.item_id=u.product_id "
                              "WHERE u.status='entregada' AND u.expires_at!='' AND u.renewed_to IS NULL AND p.duration!='perpetua'").fetchall():
            left=(date.fromisoformat(unit['expires_at'])-today).days
            # Si la tarea no se ejecutó algún día, se envía el aviso más cercano que corresponda (nunca varios a la vez).
            threshold=next((d for d in sorted(days) if left<=d),None) if left>=0 else (0 if 0 in days and left>=-2 else None)
            if threshold is None:continue
            status,error='pendiente',''
            if opted_out(c,unit['client_id']):status,error='omitido','El cliente pidió no recibir avisos de renovación.'
            elif not _valid_mail(unit['email']):status,error='omitido','El cliente no tiene un correo válido registrado.'
            c.execute('INSERT OR IGNORE INTO license_notices(unit_id,client_id,expires_at,days,recipient,status,last_error,created_at) VALUES (?,?,?,?,?,?,?,?)',
                      (unit['id'],unit['client_id'],unit['expires_at'],threshold,(unit['email'] or '').strip(),status,error,stamp))
    return [dict(r) for r in c.execute("SELECT * FROM license_notices WHERE manual=0 AND (status='pendiente' OR (status='error' AND attempts<? AND next_retry_at<=?)) ORDER BY id LIMIT 40",(MAX_ATTEMPTS,stamp))]


def cancel_for(c,unit_id):
    """Al renovar: se suspenden los avisos pendientes o con error del vencimiento anterior."""
    c.execute("UPDATE license_notices SET status='cancelado',last_error='Licencia renovada: aviso suspendido' WHERE unit_id=? AND status IN ('pendiente','error')",(unit_id,))


def context(c,unit_id,days=None):
    row=c.execute("SELECT u.id,u.code,u.expires_at,u.activated_at,u.delivered_at,u.devices,u.term,u.client_id,i.name product,i.id product_id,i.brand,p.model,cl.name client,COALESCE(cl.email,'') email "
                  "FROM license_units u JOIN catalog_items i ON i.id=u.product_id LEFT JOIN license_products p ON p.item_id=u.product_id LEFT JOIN clients cl ON cl.id=u.client_id WHERE u.id=?",(unit_id,)).fetchone()
    if not row:return None
    data=dict(row);logo=c.execute('SELECT mime,data FROM catalog_images WHERE item_id=?',(data['product_id'],)).fetchone()
    data['logo']=(logo['mime'],bytes(logo['data'])) if logo else None;data['days']=days
    return data


def _day(value):
    if not value:return 'Sin registrar'
    try:return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
    except ValueError:return str(value)


def _fill(text,data,left):
    return (text.replace('{cliente}',data['client'] or 'cliente').replace('{producto}',data['product']).replace('{fecha}',_day(data['expires_at']))
                .replace('{dias}',str(left) if left is not None else '—'))


def whatsapp_link(product,expires):
    text='Buenos días, PC-DOCTOR S.A. Deseo solicitar la renovación de mi licencia %s, próxima a vencer el %s.'%(product,_day(expires))
    return 'https://wa.me/%s?text=%s'%(WHATSAPP,quote(text))


def build(config,data,today,kind='renewal',subject=None,intro=None):
    """Mensaje listo para enviar. kind: 'renewal' (aviso de vencimiento) o 'info' (información autorizada de la licencia)."""
    e=html.escape;settings_=dict(DEFAULTS);left=(date.fromisoformat(data['expires_at'])-today).days if data.get('expires_at') else None
    model={'suscripcion':'Suscripción','perpetua':'Perpetua','otra':'Otra'}.get(data.get('model') or '','')
    title=subject or (settings_['subject'] if kind=='renewal' else 'Información de su licencia | PC-DOCTOR S.A.')
    title=_fill(title,data,left)
    if kind=='renewal':
        stage=STAGES.get(data.get('days'),'Recordatorio de renovación')
        paragraphs=_fill(intro or settings_['intro'],data,left).split('\n\n')
        status_line='Su licencia vence hoy.' if left==0 else ('Su licencia venció el %s.'%_day(data['expires_at']) if left is not None and left<0 else 'Su licencia vence en %s día%s.'%(left,'' if left==1 else 's'))
        closing='Le invitamos a solicitar su renovación antes de la fecha indicada.' if (left or 0)>0 else 'Puede solicitar su renovación respondiendo a este correo o por WhatsApp.'
    else:
        stage='Información de su licencia';paragraphs=['Le compartimos la información de la licencia que adquirió en PC-DOCTOR S.A. Por su seguridad, las claves y contraseñas no se envían por correo.']
        status_line='Vigente hasta el %s.'%_day(data['expires_at']) if data.get('expires_at') else 'Licencia sin fecha de vencimiento registrada.';closing=''
    facts=[('Producto',data['product']),('Tipo de licencia',model or data.get('term') or '—'),('Fecha de activación',_day(data.get('activated_at'))),
           ('Fecha de vencimiento',_day(data.get('expires_at')) if data.get('expires_at') else 'Sin vencimiento'),('Tiempo restante','%d día%s'%(left,'' if left==1 else 's') if left is not None and left>=0 else ('Vencida' if left is not None else '—'))]
    link=whatsapp_link(data['product'],data.get('expires_at'))
    brand_cid,product_cid=make_msgid()[1:-1],make_msgid()[1:-1]
    rows=''.join('<tr><td style="padding:8px 12px;color:#475569;font-size:13px;border-bottom:1px solid #e2e8f0;">%s</td><td style="padding:8px 12px;color:#0f172a;font-size:14px;font-weight:600;border-bottom:1px solid #e2e8f0;">%s</td></tr>'%(e(a),e(b)) for a,b in facts)
    body=''.join('<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1f2937;">%s</p>'%e(p.strip()) for p in paragraphs if p.strip())
    product_logo='<img src="cid:%s" alt="%s" width="96" style="display:block;max-width:96px;height:auto;margin:0 auto 10px;">'%(product_cid,e(data['product'])) if data.get('logo') else ''
    button=('<table role="presentation" cellpadding="0" cellspacing="0" style="margin:22px auto;"><tr><td style="border-radius:10px;background:%s;"><a href="%s" style="display:inline-block;padding:14px 28px;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;letter-spacing:.04em;">SOLICITAR RENOVACIÓN</a></td></tr></table>'%(BLUE,e(link))) if kind=='renewal' else ''
    page=('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title></head>'
          '<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">'
          '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:20px 10px;"><tr><td align="center">'
          '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">'
          '<tr><td style="background:#ffffff;border-bottom:4px solid %s;padding:22px 24px;text-align:center;"><img src="cid:%s" alt="PC-DOCTOR S.A." width="160" style="display:block;margin:0 auto 6px;max-width:160px;height:auto;">'
          '<div style="font-size:12px;color:#475569;letter-spacing:.06em;">Tecnología, seguridad y soporte profesional</div></td></tr>'
          '<tr><td style="padding:26px 24px 8px;"><div style="font-size:12px;font-weight:700;color:%s;letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px;">%s</div>'
          '<p style="margin:0 0 14px;font-size:16px;color:#0f172a;">Estimado/a <strong>%s</strong>:</p><p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1f2937;">Reciba un cordial saludo de parte de PC-DOCTOR S.A.</p>%s</td></tr>'
          '<tr><td style="padding:6px 24px;"><div style="border:1px solid #dbeafe;border-radius:12px;padding:16px;background:#f8fbff;text-align:center;">%s'
          '<div style="font-size:12px;font-weight:700;color:%s;letter-spacing:.08em;margin-bottom:8px;">INFORMACIÓN DE SU LICENCIA</div>'
          '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="text-align:left;border-collapse:collapse;">%s</table>'
          '<p style="margin:14px 0 0;font-size:15px;font-weight:700;color:%s;">%s</p></div></td></tr>'
          '<tr><td style="padding:10px 24px 4px;text-align:center;">%s%s</td></tr>'
          '<tr><td style="padding:6px 24px 22px;"><p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#1f2937;">Agradecemos la confianza depositada en nuestros productos y servicios. Nuestro equipo estará encantado de ayudarle%s.</p>'
          '<p style="margin:0;font-size:14px;line-height:1.6;color:#1f2937;">Atentamente,<br><strong>Departamento de Licencias y Soporte Técnico</strong><br>PC-DOCTOR S.A.</p>'
          '<p style="margin:12px 0 0;font-size:13px;line-height:1.7;color:#334155;">WhatsApp: +593 98 746 0591<br>Correo: licencias-orig@ecuadorpcdoctor.com<br>Web: %s</p></td></tr>'
          '<tr><td style="background:#f8fafc;padding:14px 24px;font-size:11.5px;color:#64748b;text-align:center;border-top:1px solid #e2e8f0;">Este mensaje ha sido generado automáticamente por nuestro sistema de gestión de licencias. No contiene claves, seriales ni contraseñas.</td></tr>'
          '</table></td></tr></table></body></html>')%(e(title),BLUE,brand_cid,BLUE,e(stage),e(data['client'] or 'cliente'),body,product_logo,BLUE,rows,BLUE if (left or 1)>0 else '#b91c1c',e(status_line),
                                                                                  '<p style="margin:0;font-size:14px;color:#1f2937;">%s</p>'%e(closing) if closing else '',button,' con el proceso de renovación' if kind=='renewal' else '',SITE)
    text='\n'.join(['Estimado/a %s:'%(data['client'] or 'cliente'),'','Reciba un cordial saludo de parte de PC-DOCTOR S.A.','',*[_fill(p,data,left).strip()+'\n' for p in paragraphs],'INFORMACIÓN DE SU LICENCIA',
                    *['%s: %s'%(a,b) for a,b in facts],'',status_line,closing,*(['','Solicitar renovación por WhatsApp: '+link] if kind=='renewal' else []),'',
                    'Atentamente,','Departamento de Licencias y Soporte Técnico','PC-DOCTOR S.A.','WhatsApp: +593 98 746 0591','licencias-orig@ecuadorpcdoctor.com',SITE,'',
                    'Este mensaje ha sido generado automáticamente por nuestro sistema de gestión de licencias.'])
    message=EmailMessage();message['From']='PC-DOCTOR S.A. <%s>'%config['username'];message['To']=data['email'];message['Subject']=title
    message['Date']=formatdate(localtime=True);message['Message-ID']=make_msgid(domain=config['username'].split('@')[-1])
    message.set_content(text);message.add_alternative(page,subtype='html')
    part=message.get_payload()[1];logo=ROOT/'static'/'logo-firma.png'
    part.add_related(logo.read_bytes(),'image','png',cid='<%s>'%brand_cid,disposition='inline',filename='pc-doctor.png')
    if data.get('logo'):
        mime,content=data['logo'];part.add_related(content,'image',mime.split('/')[1],cid='<%s>'%product_cid,disposition='inline',filename='producto.'+mime.split('/')[1].replace('jpeg','jpg'))
    return message,title,page


def history(c,limit=300):
    """Avisos registrados con el estado real del correo (aceptado por el servidor, entregado o rebotado según el seguimiento)."""
    rows=[]
    for r in c.execute("SELECT n.*,u.code unit_code,i.name product,COALESCE(cl.name,'') client,(SELECT d.status FROM mail_deliveries d WHERE d.archive_id=n.archive_id ORDER BY d.id DESC LIMIT 1) delivery "
                       "FROM license_notices n JOIN license_units u ON u.id=n.unit_id JOIN catalog_items i ON i.id=u.product_id LEFT JOIN clients cl ON cl.id=n.client_id ORDER BY n.id DESC LIMIT ?",(limit,)):
        row=dict(r)
        row['result']=({'entregado':'Entregado al destinatario','abierto':'Entregado al destinatario','rebotado':'Rebotado','fallido':'Error de entrega','demorado':'Entrega demorada'}.get(row['delivery'])
                       or {'enviado':'Aceptado por el servidor de correo','pendiente':'Pendiente de envío','error':'Error de envío','omitido':'No enviado','cancelado':'Suspendido'}[row['status']])
        rows.append(row)
    return rows
