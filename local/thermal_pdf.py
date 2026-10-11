"""Ticket térmico de recepción: rollo 80 mm, área útil 72 mm a 203 dpi, una página de altura variable por copia."""
from datetime import datetime
import io
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
import pydyf
import segno
from receipt_pdf import WIDTHS
from reception import ECUADOR_TZ,DEVICE_TYPES
from corporate import settings
from code128 import widths as barcode_widths
from technical_access import SCOPES
from document_logo import pixels as logo_pixels

# El PPD EPSON TM Thermal define RP80 como 204.3 pt (72 mm útiles).
# La impresora aporta el margen físico del rollo; no reducir el PDF al imprimir.
W=72*72/25.4
M=1*72/25.4
DOT=72/203
# Resumen informativo: no sustituye ni modifica la versión histórica aceptada.
SUMMARY=(
 'Diagnóstico: revisiones y pruebas técnicas expresamente acordadas.',
 'Datos personales: se recomienda respaldar la información; las operaciones técnicas pueden implicar riesgos para los datos.',
 'Reparaciones adicionales: los trabajos con costos no autorizados requieren aprobación previa.',
 'Fallas preexistentes: los daños ocultos detectados durante el diagnóstico serán comunicados.',
 'Plazos: estimados según complejidad y disponibilidad de repuestos.',
 'Garantía: servicios y componentes según las condiciones informadas y la ley.',
 'Almacenamiento: cargos solo si fueron informados y aceptados, con base de cálculo definida y conforme a la normativa.',
 'Entrega: el cliente podrá verificar el equipo y registrar observaciones al retirarlo.',
)


COPIES={'cliente':('COPIA CLIENTE',),'taller':('COPIA TALLER',),'ambas':('COPIA CLIENTE','COPIA TALLER')}
LOGO_MM=26  # Ancho impreso del logo.
LOGO_PX=416  # Dos píxeles por punto de impresora para conservar el detalle del original.


def render_thermal(order,copy='cliente'):
    company=settings();pdf=pydyf.PDF();pdf.info['Title']=pydyf.String('Recepción térmica '+order['code']);pdf.info['Author']=pydyf.String(company['name'])
    fonts={}
    for key,name in [('F1','Helvetica'),('F2','Helvetica-Bold')]:
        font=pydyf.Dictionary({'Type':'/Font','Subtype':'/Type1','BaseFont':'/'+name,'Encoding':'/WinAnsiEncoding'});pdf.add_object(font);fonts[key]=font.reference
    # Logo original sin retocar: sus mismos trazos y tonos en escala de grises sobre blanco (la impresora térmica los tramará).
    logo_w,logo_h,rgb,alpha,_=logo_pixels(LOGO_PX)
    gray=bytes(min(255,round((.2126*rgb[i*3]+.7152*rgb[i*3+1]+.0722*rgb[i*3+2])*a/255+255-a)) for i,a in enumerate(alpha))
    logo=pydyf.Stream([gray],extra={'Type':'/XObject','Subtype':'/Image','Width':logo_w,'Height':logo_h,'ColorSpace':'/DeviceGray','BitsPerComponent':8,'Interpolate':'true'},compress=True);pdf.add_object(logo)
    resources=pydyf.Dictionary({'Font':pydyf.Dictionary(fonts),'XObject':pydyf.Dictionary({'Logo':logo.reference})})
    def text_width(text,size,bold=False):return sum(WIDTHS.get(c,556) for c in text)*size/1000*(1.06 if bold else 1)
    def wrap(value,size,bold):
        lines=[]
        for paragraph in str(value).splitlines() or ['']:
            current=''
            for char in paragraph:
                if current and text_width(current+char,size,bold)>W-2*M:
                    cut=current.rfind(' ')
                    if cut>0:lines.append(current[:cut]);current=current[cut+1:]+char
                    else:lines.append(current);current=char
                else:current+=char
            lines.append(current)
        return lines
    # El enlace público solo se anuncia si la orden tiene un seguimiento activo; si no, el QR conserva el `qr_url` de uso interno.
    tracking=order.get('tracking_url') or ''
    # El QR lleva integrado el número de la orden como fragmento: lo muestra el lector y no viaja al servidor.
    matrix=list(segno.make_qr((tracking+'#'+order['code']) if tracking else order['qr_url'],error='m').matrix)
    qr_unit=next((n*DOT for n in (5,4,3) if (len(matrix)+8)*n*DOT<=W-2*M),None)
    if qr_unit is None:raise ValueError('El QR excede el ancho imprimible.')
    qr_size=(len(matrix)+8)*qr_unit
    bars=barcode_widths(order['code']);unit=2*DOT;total=(sum(bars)+20)*unit
    if total>W-2*M:raise ValueError('Identificador demasiado largo para Code 128 a dos puntos por módulo.')
    received=datetime.fromisoformat(order['received_at']).astimezone(ECUADOR_TZ)
    access=order.get('access_authorization');destructive=order.get('destructive_authorization');terms=order.get('terms')
    link=terms['url'] if terms else company['website'].rstrip('/')+'/conditions'

    def compose(copy_label):
        ops=[];y=10;link_box=[0,0]
        def block(value,size=9,bold=False,gap=3,center=False):
            nonlocal y
            for line in wrap(value,size,bold):ops.append(('text',line,y,size,bold,center));y+=size*1.3
            y+=gap
        def section(title):
            nonlocal y
            y+=3;ops.append(('rule',y));y+=7;block(title,9,True,4)
        def pair(label,value):block(label+': '+str(value or 'No registrado'))
        def signature(label):
            nonlocal y
            y+=30;ops.append(('line',y,W*.14,W*.86));y+=4;block(label,8,center=True,gap=4)
        # 1–2. Logo original y datos del taller.
        logo_width=LOGO_MM*72/25.4;logo_height=logo_width*logo_h/logo_w;ops.append(('logo',y,logo_width,logo_height));y+=logo_height+5
        block(company['name'],9,True,1,True);block(company['specialty'],8,gap=2,center=True)
        block('WhatsApp: '+company['whatsapp'],8,gap=1,center=True);block(company['website'],8,gap=5,center=True)
        block('COMPROBANTE DE RECEPCIÓN',9,True,2,True);block(copy_label,8,True,5,True)
        if order.get('preview'):block('VISTA PREVIA · DATOS FICTICIOS',8,True,5,True)
        # 3. Número de orden destacado y, justo debajo, el QR de esa orden.
        block(order['code'],14,True,3,True)
        ops.append(('qr',y,qr_size,qr_unit,matrix));y+=qr_size+3
        block('Escanea para consultar tu reparación' if tracking else 'Uso interno: escanear con sesión autorizada.',9 if tracking else 8,bool(tracking),6,True)
        # 4. Fecha y hora.
        pair('Fecha y hora',received.strftime('%d/%m/%Y %H:%M:%S')+' · Ecuador')
        pair('Estado',order['status_label'])
        # 5–9. Cliente, equipo, accesorios, estado físico y falla informada.
        section('CLIENTE');pair('Nombre',order['client'])
        pair({'ruc':'RUC','pasaporte':'Pasaporte'}.get(order.get('document_type'),'Identificación'),order.get('identification'))
        pair('Teléfono',order.get('phone'))
        section('EQUIPO');pair('Tipo',DEVICE_TYPES.get(order['type'],order['type']))
        pair('Marca / modelo',' '.join(filter(None,[order.get('brand'),order.get('model')])));pair('Serie',order.get('serial'))
        pair('Accesorios recibidos',order.get('accessories'));pair('Estado físico',order.get('physical_condition'));pair('Falla informada por el cliente',order['problem'])
        # 11. Autorización y condiciones: mismos textos y evidencia registrada, sin añadir consentimientos.
        section('AUTORIZACIÓN DE ACCESO TÉCNICO')
        block('Acceso técnico: '+({'authorized':'AUTORIZADO','denied':'NO AUTORIZADO'}[access['decision']] if access else 'No consta autorización'),9,True,4)
        if access:
            granted=[label for key,label in SCOPES.items() if access['permissions'].get(key)]
            if granted:block('Alcance autorizado: '+'. '.join(granted)+'.',9)
            block('Decisión registrada: '+datetime.fromisoformat(access['recorded_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S'),8)
            block('Responsable: '+access['operator'],8)
        block('Reinstalar / formatear / eliminar: '+({'authorized':'AUTORIZACIÓN ADICIONAL REGISTRADA','denied':'NO AUTORIZADO'}[destructive['decision']] if destructive else 'Sin autorización adicional'),8,True)
        block('El diagnóstico no autoriza revisar datos privados ni borrar información fuera del alcance expresamente acordado.',8)
        section('CONDICIONES DEL SERVICIO · RESUMEN')
        if terms:block('Versión aceptada: '+terms['version'],8,True)
        else:block('Orden histórica: no consta aceptación de condiciones. Este resumen informa; no acredita consentimiento.',9,True,5)
        for n,paragraph in enumerate(SUMMARY,1):block(str(n)+'. '+paragraph,9,gap=3)
        if terms:
            block('Aceptación registrada: '+datetime.fromisoformat(order['terms_accepted_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S'),8)
            block('La versión completa aceptada se conserva sin cambios. Consulta:',8)
        else:block('Condiciones vigentes para consulta; requieren aceptación expresa:',8)
        link_box[0]=y;block(link,8,gap=5);link_box[1]=y
        # 12. Firma y constancia de recepción.
        section('FIRMA Y CONSTANCIA DE RECEPCIÓN')
        block(company['name']+' deja constancia de haber recibido el equipo descrito en este comprobante el '+received.strftime('%d/%m/%Y')+' a las '+received.strftime('%H:%M')+'.',8,gap=0)
        signature('Firma del cliente');signature('Recibido por '+company['name'])
        # Code 128 para localizar la orden en el taller.
        y+=4;ops.append(('rule',y));y+=8
        ops.append(('barcode',y,bars,unit,total));y+=17*72/25.4+8
        block(order['code'],10,True,6,True)
        block(company['thanks'],9,True,3,True);block(company['support_email'],8,center=True)
        return ops,y+10,link_box

    for copy_label in COPIES[copy]:
        ops,height,link_box=compose(copy_label)
        stream=pydyf.Stream(compress=True);pdf.add_object(stream);stream.set_color_rgb(0,0,0)
        for op in ops:
            if op[0]=='text':
                _,value,top,size,bold,center=op;x=(W-text_width(value,size))/2 if center else M
                stream.begin_text();stream.set_font_size('F2' if bold else 'F1',size);stream.set_text_matrix(1,0,0,1,x,height-top-size);stream.show_text_string(value.encode('cp1252','replace'));stream.end_text()
            elif op[0]=='rule':
                stream.set_line_width(.35);stream.move_to(M,height-op[1]);stream.line_to(W-M,height-op[1]);stream.stroke()
            elif op[0]=='line':
                stream.set_line_width(.6);stream.move_to(op[2],height-op[1]);stream.line_to(op[3],height-op[1]);stream.stroke()
            elif op[0]=='logo':
                _,top,width,tall=op;stream.push_state();stream.set_matrix(width,0,0,tall,(W-width)/2,height-top-tall);stream.draw_x_object('Logo');stream.pop_state()
            elif op[0]=='qr':
                _,top,size,qunit,cells=op;left=(W-size)/2
                for row,values in enumerate(cells):
                    for col,dark in enumerate(values):
                        if dark:stream.rectangle(left+(col+4)*qunit,height-top-(row+5)*qunit,qunit,qunit)
                stream.fill()
            elif op[0]=='barcode':
                _,top,widths,bunit,span=op;left=(W-span)/2+10*bunit
                for i,width in enumerate(widths):
                    if i%2==0:stream.rectangle(left,height-top-17*72/25.4,width*bunit,17*72/25.4)
                    left+=width*bunit
                stream.fill()
        annotation=pydyf.Dictionary({'Type':'/Annot','Subtype':'/Link','Rect':pydyf.Array([M,height-link_box[1],W-M,height-link_box[0]]),'Border':pydyf.Array([0,0,0]),'A':pydyf.Dictionary({'S':'/URI','URI':pydyf.String(link)})});pdf.add_object(annotation)
        page=pydyf.Dictionary({'Type':'/Page','Parent':pdf.pages.reference,'MediaBox':pydyf.Array([0,0,W,height]),'Resources':resources,'Contents':stream.reference,'Annots':pydyf.Array([annotation.reference])})
        pdf.add_page(page)
    output=io.BytesIO();pdf.write(output);return output.getvalue()
