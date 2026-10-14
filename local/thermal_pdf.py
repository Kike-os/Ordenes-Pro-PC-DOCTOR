"""Ticket térmico de recepción: rollo 80 mm, área útil 72 mm a 203 dpi, una página de altura variable por copia."""
from datetime import datetime
import io,re
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
 'El equipo será revisado según el servicio autorizado.',
 'Los costos adicionales requieren aprobación previa.',
 'Se recomienda respaldar la información del equipo.',
 'Las fallas adicionales serán comunicadas al cliente.',
 'Los plazos dependen del diagnóstico y los repuestos.',
 'La garantía se aplica según el servicio realizado.',
 'El retiro y almacenaje se rigen por las condiciones aceptadas.',
)


COPIES={'cliente':('COPIA DEL CLIENTE',),'taller':('COPIA DEL ESTABLECIMIENTO',),'ambas':('COPIA DEL CLIENTE','COPIA DEL ESTABLECIMIENTO')}
# Encabezado ejecutivo sobre fondo blanco: título azul oscuro (#192B45), copia en rosado corporativo (#AA477C) y filete rosado (#D9669F).
# Sin bloques de tinta: en la impresora térmica (un solo tono) el título sale negro pleno y el rosado, en gris tramado.
TITLE_INK=(0x19/255,0x2B/255,0x45/255);COPY_INK=(0xAA/255,0x47/255,0x7C/255);ACCENT_INK=(0xD9/255,0x66/255,0x9F/255)
LOGO_MM=20  # Ancho impreso del logo (compacto).
LOGO_PX=416  # Dos píxeles por punto de impresora para conservar el detalle del original.
BAR_HEIGHT=13*72/25.4  # Alto del Code 128: 13 mm, suficiente para el lector y más corto que antes.


def render_thermal(order,copy='cliente'):
    company=settings();pdf=pydyf.PDF();pdf.info['Title']=pydyf.String('TICKET-'+order['code']);pdf.info['Author']=pydyf.String(company['name'])
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
    access=order.get('access_authorization');destructive=order.get('destructive_authorization');terms=order.get('terms')
    link=terms['url'] if terms else settings()['website'].rstrip('/')+'/conditions'
    # Segundo QR: condiciones completas (la versión aceptada o, si no hay aceptación, las vigentes). Los dos QR comparten fila y tamaño.
    terms_matrix=list(segno.make_qr(link,error='m').matrix)
    half_width=(W-2*M-8)/2
    qr_unit=next((n*DOT for n in (5,4,3) if (max(len(matrix),len(terms_matrix))+8)*n*DOT<=half_width),None)
    if qr_unit is None:raise ValueError('El QR excede el ancho imprimible.')
    qr_size=(len(matrix)+8)*qr_unit;terms_size=(len(terms_matrix)+8)*qr_unit
    bars=barcode_widths(order['code']);unit=2*DOT;total=(sum(bars)+20)*unit
    if total>W-2*M:raise ValueError('Identificador demasiado largo para Code 128 a dos puntos por módulo.')
    received=datetime.fromisoformat(order['received_at']).astimezone(ECUADOR_TZ)

    INNER=W-2*M
    def snap(value):
        """Posición alineada a la rejilla de puntos de la impresora: QR y código de barras salen con bordes nítidos."""
        return round(value/DOT)*DOT
    def wrap_to(value,size,bold,width):
        lines=[]
        for paragraph in str(value).splitlines() or ['']:
            current=''
            for word in paragraph.split(' '):
                trial=(current+' '+word).strip() if current else word
                if current and text_width(trial,size,bold)>width:lines.append((current,False));current=word
                else:current=trial
                # Una palabra más ancha que la línea (un enlace, por ejemplo) se parte por caracteres.
                while text_width(current,size,bold)>width:
                    cut=len(current)
                    while cut>1 and text_width(current[:cut],size,bold)>width:cut-=1
                    lines.append((current[:cut],False));current=current[cut:]
            lines.append((current,True))
        return lines

    def compose(copy_label):
        ops=[];y=5;link_box=[0,0,M,W-M]
        def block(value,size=9,bold=False,gap=3,center=False,x=M,width=None,justify=False,lead=1.25):
            nonlocal y
            width=INNER-(x-M) if width is None else width
            for line,last in wrap_to(value,size,bold,width):
                ops.append(('text',line,y,size,bold,center,x,width,justify and not last and ' ' in line));y+=size*lead
            y+=gap
        def section(title):
            nonlocal y
            y+=2;ops.append(('rule',y));y+=5;block(title,8.5,True,3)
        def pair(label,value,column=70):
            """Etiqueta en negrita en una columna fija y valor alineado a su derecha: todas las filas comparten el mismo margen."""
            nonlocal y
            start=y;block(label,8,True,0,width=column-4,lead=1.25);label_end=y;y=start
            block(str(value or 'No registrado'),8.5,False,0,x=M+column,lead=1.2);y=max(y,label_end)+2
        def paragraph(value,size=8,gap=2.5):block(value,size,gap=gap,justify=True,lead=1.22)
        def item(number,value,size=8,gap=1.6,lead=1.2):
            # Condición numerada: «N. Término:» en negrita y el texto a continuación, alineado a la izquierda con sangría francesa.
            nonlocal y
            term,_,rest=value.partition(': ')
            mark=str(number)+'. ';hang=text_width(mark,size,True);lead_text=mark+term+':'
            # La negrita real es algo más ancha que la estimada: el texto empieza tras un espacio holgado (1,8 espacios).
            start=text_width(lead_text,size,True)+text_width(' ',size)*1.8;first=INNER-start;words=rest.split(' ');line=''
            while words and text_width((line+' '+words[0]).strip(),size)<=first:line=(line+' '+words.pop(0)).strip()
            ops.append(('text',lead_text,y,size,True,False,M,INNER,False))
            if line:ops.append(('text',line,y,size,False,False,M+start,first,False))
            y+=size*lead
            for text,_ in (wrap_to(' '.join(words),size,False,INNER-hang) if words else []):
                ops.append(('text',text,y,size,False,False,M+hang,INNER-hang,False));y+=size*lead
            y+=gap
        def numbered(number,value,size=8,gap=1.4,lead=1.2):
            # Punto numerado alineado a la izquierda con sangría francesa (sin justificado: no abre huecos en líneas cortas).
            nonlocal y
            mark=str(number)+'.';hang=text_width(mark+'  ',size,True)
            ops.append(('text',mark,y,size,True,False,M,hang,False))
            for text,_ in wrap_to(value,size,False,INNER-hang):
                ops.append(('text',text,y,size,False,False,M+hang,INNER-hang,False));y+=size*lead
            y+=gap
        # 1. Logo compacto y datos del taller.
        logo_width=LOGO_MM*72/25.4;logo_height=logo_width*logo_h/logo_w;ops.append(('logo',y,logo_width,logo_height));y+=logo_height+2
        block(company['name'],9.5,True,0,True);block(company['specialty'],7.5,gap=0,center=True,lead=1.2)
        block('WhatsApp '+company['whatsapp'],7.5,gap=0,center=True,lead=1.2);block(re.sub(r'^https?://|/$','',company['website']),7,gap=3,center=True,lead=1.2)
        y+=2;block('COMPROBANTE DE RECEPCIÓN',10.5,True,1.5,True);ops[-1]=ops[-1]+(TITLE_INK,);block(copy_label,7.5,True,0,True);ops[-1]=ops[-1]+(COPY_INK,)
        if order.get('preview'):y+=2;block('VISTA PREVIA · DATOS FICTICIOS',7,True,0,True)
        y+=3.5;ops.append(('accent',y));y+=7
        # 2–3. Número de orden destacado, fecha y hora de recepción.
        block(order['code'],15,True,2,True)
        block('Recepción: '+received.strftime('%d/%m/%Y · %H:%M'),8.5,False,1,True)
        # 4. Cliente.
        section('CLIENTE');pair('Nombre',order['client'])
        pair({'ruc':'RUC','pasaporte':'Pasaporte'}.get(order.get('document_type'),'Identificación'),order.get('identification'))
        pair('Teléfono',order.get('phone'))
        # 5–6. Equipo y accesorios.
        section('EQUIPO');pair('Tipo',DEVICE_TYPES.get(order['type'],order['type']))
        pair('Marca / modelo',' '.join(filter(None,[order.get('brand'),order.get('model')])));pair('Serie',order.get('serial'))
        pair('Accesorios',order.get('accessories'));pair('Estado físico',order.get('physical_condition'))
        # 7–8. Falla reportada y servicio solicitado (datos reales de la recepción; las notas internas no se imprimen).
        section('FALLA REPORTADA');block(str(order['problem'] or 'No registrado'),8.5,False,1,lead=1.22)
        section('SERVICIO SOLICITADO');pair('Servicio','Diagnóstico técnico de la falla informada');pair('Estado',order['status_label'])
        # Autorización de acceso técnico: obligatoria, con su evidencia, sin añadir consentimientos.
        section('AUTORIZACIÓN DE ACCESO TÉCNICO')
        block('Acceso técnico: '+({'authorized':'AUTORIZADO','denied':'NO AUTORIZADO'}[access['decision']] if access else 'No consta autorización'),8.5,True,1.5)
        if access:
            granted=[label for key,label in SCOPES.items() if access['permissions'].get(key)]
            if granted:block('Alcance autorizado: '+'. '.join(granted)+'.',8,gap=1.5,lead=1.2)
            if access['decision']=='authorized' and access['permissions'].get('files_decision')=='denied':block('Archivos y respaldos: NO AUTORIZADO',8,True,1.5)
            block('Registrada: '+datetime.fromisoformat(access['recorded_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')+' · '+access['operator'],7.5,gap=1.5,lead=1.2)
        block('Reinstalar / formatear / eliminar: '+({'authorized':'AUTORIZACIÓN ADICIONAL REGISTRADA','denied':'NO AUTORIZADO'}[destructive['decision']] if destructive else 'Sin autorización adicional'),8,True,1.5,lead=1.2)
        block('El diagnóstico no autoriza revisar datos privados ni borrar información fuera del alcance acordado.',7.5,gap=1,lead=1.2)
        # 9. Condiciones resumidas: el resumen informa; la versión completa aceptada no cambia y se consulta con el QR.
        section('CONDICIONES DE RECEPCIÓN')
        if terms:block('Versión aceptada '+terms['version']+' · '+datetime.fromisoformat(order['terms_accepted_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'),7.5,True,2)
        else:block('Orden histórica: no consta aceptación de condiciones. Este resumen informa; no acredita consentimiento.',7.5,gap=2,lead=1.2)
        for n,text in enumerate(SUMMARY,1):numbered(n,text)
        # 10. Dos QR en una fila: condiciones completas (versión aceptada) y seguimiento de la reparación.
        y+=3;ops.append(('rule',y));y+=5;top=y;column=(INNER-8)/2
        terms_left=snap(M+(column-terms_size)/2);track_left=snap(M+column+8+(column-qr_size)/2)
        ops.append(('qr',top,terms_size,qr_unit,terms_matrix,terms_left));ops.append(('qr',top,qr_size,qr_unit,matrix,track_left))
        link_box[:]=[top,top+terms_size,terms_left,terms_left+terms_size]
        y=top+max(qr_size,terms_size)+1
        captions=(('Condiciones completas',('Versión '+terms['version']) if terms else 'Versión vigente'),('Seguimiento de tu reparación','Escanea el código' if tracking else 'Uso interno con sesión'))
        start=y;bottom=y
        for index,(title,detail) in enumerate(captions):
            y=start;left=M+index*(column+8)
            for line,_ in wrap_to(title,7.5,True,column):ops.append(('text',line,y,7.5,True,False,left+(column-text_width(line,7.5,True))/2,column,False));y+=7.5*1.2
            for line,_ in wrap_to(detail,7,False,column):ops.append(('text',line,y,7,False,False,left+(column-text_width(line,7))/2,column,False));y+=7*1.2
            bottom=max(bottom,y)
        y=bottom+2
        # 11. Firma y constancia de recepción.
        section('FIRMA Y CONSTANCIA DE RECEPCIÓN')
        block(company['name']+' recibió el equipo descrito el '+received.strftime('%d/%m/%Y')+' a las '+received.strftime('%H:%M')+'.',7.5,gap=0,lead=1.2)
        y+=24;half=(INNER-8)/2
        for index,label in enumerate(('Firma del cliente','Recibido por '+company['name'])):
            left=M+index*(half+8);ops.append(('line',y,left,left+half))
            lines=wrap_to(label,7,False,half)
            for row,(line,_) in enumerate(lines):ops.append(('text',line,y+3+row*8.5,7,False,False,left+(half-text_width(line,7))/2,half,False))
        y+=3+8.5*max(len(wrap_to(label,7,False,half)) for label in ('Firma del cliente','Recibido por '+company['name']))+3
        # Code 128 para localizar la orden en el taller.
        ops.append(('rule',y));y+=5
        ops.append(('barcode',y,bars,unit,total));y+=BAR_HEIGHT+4
        block(order['code'],9.5,True,3,True)
        block(company['thanks'],8,True,0.5,True);block(company['support_email'],7,center=True,gap=0)
        return ops,y+6,link_box

    for copy_label in COPIES[copy]:
        ops,height,link_box=compose(copy_label)
        stream=pydyf.Stream(compress=True);pdf.add_object(stream);stream.set_color_rgb(0,0,0)
        def draw(value,x,top,size,bold):
            stream.begin_text();stream.set_font_size('F2' if bold else 'F1',size);stream.set_text_matrix(1,0,0,1,x,height-top-size);stream.show_text_string(value.encode('cp1252','replace'));stream.end_text()
        for op in ops:
            if op[0]=='text':
                _,value,top,size,bold,center,x,width,justify=op[:9];inked=len(op)>9
                if inked:stream.set_color_rgb(*op[9])
                if center:draw(value,(W-text_width(value,size,bold))/2,top,size,bold)
                elif justify:
                    # Justificado: el espacio sobrante de la línea se reparte entre sus palabras.
                    words=value.split(' ');spare=(width-sum(text_width(word,size,bold) for word in words))/(len(words)-1)
                    if spare>size*.9:draw(value,x,top,size,bold)
                    else:
                        cursor=x
                        for word in words:draw(word,cursor,top,size,bold);cursor+=text_width(word,size,bold)+spare
                else:draw(value,x,top,size,bold)
                if inked:stream.set_color_rgb(0,0,0)
            elif op[0]=='accent':
                stream.set_color_rgb(*ACCENT_INK);stream.rectangle(M,height-op[1]-1.2,INNER,1.2);stream.fill();stream.set_color_rgb(0,0,0)
            elif op[0]=='rule':
                stream.set_line_width(.5);stream.move_to(M,height-op[1]);stream.line_to(W-M,height-op[1]);stream.stroke()
            elif op[0]=='line':
                stream.set_line_width(.6);stream.move_to(op[2],height-op[1]);stream.line_to(op[3],height-op[1]);stream.stroke()
            elif op[0]=='logo':
                _,top,width,tall=op;stream.push_state();stream.set_matrix(width,0,0,tall,(W-width)/2,height-top-tall);stream.draw_x_object('Logo');stream.pop_state()
            elif op[0]=='qr':
                _,top,size,qunit,cells,left=op
                for row,values in enumerate(cells):
                    for col,dark in enumerate(values):
                        if dark:stream.rectangle(left+(col+4)*qunit,height-top-(row+5)*qunit,qunit,qunit)
                stream.fill()
            elif op[0]=='barcode':
                _,top,widths,bunit,span=op;left=snap((W-span)/2)+10*bunit
                for i,width in enumerate(widths):
                    if i%2==0:stream.rectangle(left,height-top-BAR_HEIGHT,width*bunit,BAR_HEIGHT)
                    left+=width*bunit
                stream.fill()
        annotation=pydyf.Dictionary({'Type':'/Annot','Subtype':'/Link','Rect':pydyf.Array([link_box[2],height-link_box[1],link_box[3],height-link_box[0]]),'Border':pydyf.Array([0,0,0]),'A':pydyf.Dictionary({'S':'/URI','URI':pydyf.String(link)})});pdf.add_object(annotation)
        page=pydyf.Dictionary({'Type':'/Page','Parent':pdf.pages.reference,'MediaBox':pydyf.Array([0,0,W,height]),'Resources':resources,'Contents':stream.reference,'Annots':pydyf.Array([annotation.reference])})
        pdf.add_page(page)
    output=io.BytesIO();pdf.write(output);return output.getvalue()
