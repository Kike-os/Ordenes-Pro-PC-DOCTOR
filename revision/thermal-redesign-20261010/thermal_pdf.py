"""Ticket PDF monocromático, 80 mm / área imprimible de 72 mm (Epson TM-m30)."""
from datetime import datetime
import io
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
import pydyf
import segno
from document_logo import pdf_image
from receipt_pdf import WIDTHS
from reception import ECUADOR_TZ,DEVICE_TYPES
from service_terms import numbered_paragraphs
from corporate import settings

W=80*72/25.4
M=4*72/25.4


def render_thermal(order):
    company=settings()
    pdf=pydyf.PDF();pdf.info['Title']=pydyf.String('Recepción térmica '+order['code']);pdf.info['Author']=pydyf.String('PC-DOCTOR S.A.')
    fonts={}
    for key,name in [('F1','Helvetica'),('F2','Helvetica-Bold')]:
        font=pydyf.Dictionary({'Type':'/Font','Subtype':'/Type1','BaseFont':'/'+name,'Encoding':'/WinAnsiEncoding'});pdf.add_object(font);fonts[key]=font.reference
    image,iw,ih=pdf_image(pdf,True)
    operations=[];y=10
    def wrap(value,size=9):
        result=[];current='';limit=W-2*M
        for paragraph in str(value).splitlines() or ['']:
            current=''
            for char in paragraph:
                candidate=current+char
                if sum(WIDTHS.get(c,556) for c in candidate)*size/1000>limit and current:
                    cut=current.rfind(' ')
                    if cut>0:result.append(current[:cut]);current=current[cut+1:]+char
                    else:result.append(current);current=char
                else:current=candidate
            result.append(current)
        return result
    def block(value,size=9,bold=False,space=5,center=False):
        nonlocal y
        for line in wrap(value,size):operations.append(('text',line,y,size,bold,center));y+=size*1.35
        y+=space
    logo_width=120;logo_height=logo_width*ih/iw;operations.append(('logo',y,logo_width,logo_height));y+=logo_height+7
    block(company['name'],12,True,3,True);block(company['specialty'].upper(),8,True,3,True);block('COMPROBANTE DE RECEPCIÓN TÉCNICA',9,True,7,True)
    block(order['code'],11,True,3,True)
    received=datetime.fromisoformat(order['received_at']).astimezone(ECUADOR_TZ)
    block(received.strftime('%d/%m/%Y  %H:%M:%S')+' · Ecuador',8,False,8,True)
    block('Estado: '+order['status_label'],8,True);block('Cliente: '+order['client']);
    if order.get('identification'):block(({'ruc':'RUC: ','pasaporte':'Pasaporte: '}.get(order.get('document_type'),'Cédula: '))+order['identification'],8)
    if order.get('phone'):block('Teléfono / WhatsApp: '+order['phone'],8)
    if order.get('email'):block('Correo: '+order['email'],8)
    block('Equipo: '+DEVICE_TYPES.get(order['type'],order['type'])+' '+(order.get('brand') or '')+' '+(order.get('model') or ''))
    if order.get('serial'):block('Serie: '+order['serial'])
    if order.get('accessories'):block('Accesorios: '+order['accessories'],8)
    if order.get('physical_condition'):block('Estado físico: '+order['physical_condition'],8)
    block('Falla: '+order['problem']);
    if order.get('customer_notes'):block('Observaciones de recepción: '+order['customer_notes'],8)
    terms=order.get('terms')
    if terms:
        block('CONDICIONES DE SERVICIO',10,True,4,True)
        block('Versión '+terms['version']+' | Vigencia '+terms['effective_date'],8,True,8)
        for number,paragraph in numbered_paragraphs(terms['compact_text']):block(f'{number}. {paragraph}',9,False,7)
        block('Versión compacta. Consulta las condiciones completas aceptadas:',8,True,4)
        link_top=y;block(terms['url'],8,False,8);link_bottom=y
        accepted=datetime.fromisoformat(order['terms_accepted_at']).astimezone(ECUADOR_TZ)
        block('Aceptación: '+accepted.strftime('%d/%m/%Y %H:%M:%S')+' (Ecuador)',8)
        block('Confirmación en pantalla registrada por el técnico.',8)
        block('Registro: '+order['terms_acceptance_id'],7)
    else:block('Sin condiciones ni aceptación registradas para esta recepción.',8,False,8)
    block('SEGUIMIENTO DE REPARACIÓN',9,True,5,True)
    qr_top=y;qr_size=104;y+=qr_size+7;block('Escanee para consultar el estado de su reparación.',8,False,4,True);block('Datos privados: acceso autorizado.',7,False,8,True)
    block(company['commitment'],8,False,5,True);block(company['thanks'],9,True,6,True);block('WhatsApp: '+company['whatsapp'],8,False,3,True);block(company['website'],8,False,3,True);block(company['support_email'],8,False,3,True)
    height=y+10;stream=pydyf.Stream(compress=True);pdf.add_object(stream)
    stream.set_color_rgb(0,0,0)
    for op in operations:
        if op[0]=='logo':
            _,top,width,h=op;stream.push_state();stream.set_matrix(width,0,0,h,(W-width)/2,height-top-h);stream.draw_x_object('Logo');stream.pop_state()
        else:
            _,value,top,size,bold,center=op;width=sum(WIDTHS.get(c,556) for c in value)*size/1000;x=(W-width)/2 if center else M
            stream.begin_text();stream.set_font_size('F2' if bold else 'F1',size);stream.set_text_matrix(1,0,0,1,x,height-top-size);stream.show_text_string(value.encode('cp1252','replace'));stream.end_text()
    matrix=list(segno.make_qr(order['qr_url'],error='m').matrix);unit=qr_size/(len(matrix)+8);left=(W-qr_size)/2
    for row,values in enumerate(matrix):
        for col,dark in enumerate(values):
            if dark:stream.rectangle(left+(col+4)*unit,height-qr_top-(row+5)*unit,unit+.01,unit+.01)
    stream.fill()
    page=pydyf.Dictionary({'Type':'/Page','Parent':pdf.pages.reference,'MediaBox':pydyf.Array([0,0,W,height]),'Resources':pydyf.Dictionary({'Font':pydyf.Dictionary(fonts),'XObject':pydyf.Dictionary({'Logo':image})}),'Contents':stream.reference})
    if terms:
        annotation=pydyf.Dictionary({'Type':'/Annot','Subtype':'/Link','Rect':pydyf.Array([M,height-link_bottom,W-M,height-link_top]),'Border':pydyf.Array([0,0,0]),'A':pydyf.Dictionary({'S':'/URI','URI':pydyf.String(terms['url'])})});pdf.add_object(annotation);page['Annots']=pydyf.Array([annotation.reference])
    pdf.add_page(page);output=io.BytesIO();pdf.write(output);return output.getvalue()
