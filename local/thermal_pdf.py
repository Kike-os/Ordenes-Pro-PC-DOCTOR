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


COPIES={'cliente':('COPIA DEL CLIENTE',),'taller':('COPIA DEL ESTABLECIMIENTO',),'ambas':('COPIA DEL CLIENTE','COPIA DEL ESTABLECIMIENTO')}
# Encabezado ejecutivo sobre fondo blanco: título azul oscuro (#192B45), copia en rosado corporativo (#AA477C) y filete rosado (#D9669F).
# Sin bloques de tinta: en la impresora térmica (un solo tono) el título sale negro pleno y el rosado, en gris tramado.
TITLE_INK=(0x19/255,0x2B/255,0x45/255);COPY_INK=(0xAA/255,0x47/255,0x7C/255);ACCENT_INK=(0xD9/255,0x66/255,0x9F/255)
LOGO_MM=26  # Ancho impreso del logo.
LOGO_PX=416  # Dos píxeles por punto de impresora para conservar el detalle del original.
BAR_HEIGHT=13*72/25.4  # Alto del Code 128: 13 mm, suficiente para el lector y más corto que antes.


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
        ops=[];y=6;link_box=[0,0]
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
            block(str(value or 'No registrado'),9,False,0,x=M+column,lead=1.2);y=max(y,label_end)+2.5
        def paragraph(value,size=8,gap=2.5):block(value,size,gap=gap,justify=True,lead=1.22)
        # 1–2. Logo original y datos del taller.
        logo_width=LOGO_MM*72/25.4;logo_height=logo_width*logo_h/logo_w;ops.append(('logo',y,logo_width,logo_height));y+=logo_height+3
        block(company['name'],10,True,0,True);block(company['specialty'],8,gap=0,center=True)
        block('WhatsApp: '+company['whatsapp'],8,gap=0.5,center=True);block(company['website'],7.5,gap=4,center=True)
        # Título del documento y de la copia, centrados sobre blanco, y filete fino al ancho útil.
        y+=5;block('COMPROBANTE DE RECEPCIÓN',11,True,2.5,True);ops[-1]=ops[-1]+(TITLE_INK,);block(copy_label,8,True,0,True);ops[-1]=ops[-1]+(COPY_INK,)
        if order.get('preview'):y+=2;block('VISTA PREVIA · DATOS FICTICIOS',7,True,0,True)
        y+=4.5;ops.append(('accent',y));y+=8
        # 3. Número de orden destacado.
        block(order['code'],15,True,4,True)
        # 4. QR de la orden a la izquierda; fecha, estado y uso del código a su derecha.
        qr_top=y;ops.append(('qr',y,qr_size,qr_unit,matrix,snap(M)));side=M+qr_size+5;side_width=W-M-side;y+=4*qr_unit
        for label,value in (('FECHA Y HORA',received.strftime('%d/%m/%Y %H:%M:%S')),('ESTADO',order['status_label'])):
            block(label,6.5,True,0,x=side,width=side_width);block(value,9,False,3,x=side,width=side_width,lead=1.15)
        block('Escanea el código para consultar tu reparación.' if tracking else 'Uso interno: escanear con sesión autorizada.',7.5,bool(tracking),0,x=side,width=side_width,lead=1.2)
        y=max(y,qr_top+qr_size)+3
        # 5–9. Cliente, equipo, accesorios, estado físico y falla informada.
        section('CLIENTE');pair('Nombre',order['client'])
        pair({'ruc':'RUC','pasaporte':'Pasaporte'}.get(order.get('document_type'),'Identificación'),order.get('identification'))
        pair('Teléfono',order.get('phone'))
        section('EQUIPO');pair('Tipo',DEVICE_TYPES.get(order['type'],order['type']))
        pair('Marca / modelo',' '.join(filter(None,[order.get('brand'),order.get('model')])));pair('Serie',order.get('serial'))
        pair('Accesorios recibidos',order.get('accessories'));pair('Estado físico',order.get('physical_condition'))
        block('Falla informada por el cliente:',8,True,1);paragraph(str(order['problem'] or 'No registrado'),9,3)
        # 11. Autorización y condiciones: mismos textos y evidencia registrada, sin añadir consentimientos.
        section('AUTORIZACIÓN DE ACCESO TÉCNICO')
        block('Acceso técnico: '+({'authorized':'AUTORIZADO','denied':'NO AUTORIZADO'}[access['decision']] if access else 'No consta autorización'),9,True,2)
        if access:
            granted=[label for key,label in SCOPES.items() if access['permissions'].get(key)]
            if granted:paragraph('Alcance autorizado: '+'. '.join(granted)+'.',8.5)
            if access['decision']=='authorized' and access['permissions'].get('files_decision')=='denied':block('Archivos y respaldos: NO AUTORIZADO',8,True,2)
            block('Decisión registrada: '+datetime.fromisoformat(access['recorded_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S'),7.5,gap=0)
            block('Responsable: '+access['operator'],7.5,gap=2)
        block('Reinstalar / formatear / eliminar: '+({'authorized':'AUTORIZACIÓN ADICIONAL REGISTRADA','denied':'NO AUTORIZADO'}[destructive['decision']] if destructive else 'Sin autorización adicional'),8,True,2)
        paragraph('El diagnóstico no autoriza revisar datos privados ni borrar información fuera del alcance expresamente acordado.',7.5)
        section('CONDICIONES DEL SERVICIO · RESUMEN')
        if terms:block('Versión aceptada: '+terms['version'],8,True,2)
        else:paragraph('Orden histórica: no consta aceptación de condiciones. Este resumen informa; no acredita consentimiento.',8,3);ops[-1]=ops[-1]
        for n,text in enumerate(SUMMARY,1):paragraph(str(n)+'. '+text,8,2)
        if terms:
            block('Aceptación registrada: '+datetime.fromisoformat(order['terms_accepted_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S'),7.5,gap=1)
            block('La versión completa aceptada se conserva sin cambios. Consulta:',7.5,gap=1)
        else:block('Condiciones vigentes para consulta; requieren aceptación expresa:',7.5,gap=1)
        link_box[0]=y;block(link,7.5,gap=3);link_box[1]=y
        # 12. Firma y constancia de recepción: las dos firmas comparten renglón.
        section('FIRMA Y CONSTANCIA DE RECEPCIÓN')
        paragraph(company['name']+' deja constancia de haber recibido el equipo descrito en este comprobante el '+received.strftime('%d/%m/%Y')+' a las '+received.strftime('%H:%M')+'.',8,0)
        y+=30;half=(INNER-8)/2
        for index,label in enumerate(('Firma del cliente','Recibido por '+company['name'])):
            left=M+index*(half+8);ops.append(('line',y,left,left+half))
            lines=wrap_to(label,7.5,False,half)
            for row,(line,_) in enumerate(lines):ops.append(('text',line,y+3+row*9,7.5,False,False,left+(half-text_width(line,7.5))/2,half,False))
        y+=3+9*max(len(wrap_to(label,7.5,False,half)) for label in ('Firma del cliente','Recibido por '+company['name']))+4
        # Code 128 para localizar la orden en el taller.
        ops.append(('rule',y));y+=6
        ops.append(('barcode',y,bars,unit,total));y+=BAR_HEIGHT+5
        block(order['code'],10,True,4,True)
        block(company['thanks'],8.5,True,1,True);block(company['support_email'],7.5,center=True,gap=0)
        return ops,y+8,link_box

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
        annotation=pydyf.Dictionary({'Type':'/Annot','Subtype':'/Link','Rect':pydyf.Array([M,height-link_box[1],W-M,height-link_box[0]]),'Border':pydyf.Array([0,0,0]),'A':pydyf.Dictionary({'S':'/URI','URI':pydyf.String(link)})});pdf.add_object(annotation)
        page=pydyf.Dictionary({'Type':'/Page','Parent':pdf.pages.reference,'MediaBox':pydyf.Array([0,0,W,height]),'Resources':resources,'Contents':stream.reference,'Annots':pydyf.Array([annotation.reference])})
        pdf.add_page(page)
    output=io.BytesIO();pdf.write(output);return output.getvalue()
