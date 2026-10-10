"""PDF térmico de una sola página, rollo 80 mm y área útil 72 mm a 203 dpi."""
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


def render_thermal(order):
    company=settings();pdf=pydyf.PDF();pdf.info['Title']=pydyf.String('Recepción térmica '+order['code']);pdf.info['Author']=pydyf.String(company['name'])
    fonts={}
    for key,name in [('F1','Helvetica'),('F2','Helvetica-Bold')]:
        font=pydyf.Dictionary({'Type':'/Font','Subtype':'/Type1','BaseFont':'/'+name,'Encoding':'/WinAnsiEncoding'});pdf.add_object(font);fonts[key]=font.reference
    ops=[];y=12
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
    def block(value,size=9,bold=False,gap=3,center=False):
        nonlocal y
        for line in wrap(value,size,bold):ops.append(('text',line,y,size,bold,center));y+=size*1.3
        y+=gap
    def section(title):
        nonlocal y
        y+=4;ops.append(('rule',y));y+=8;block(title,9,True,5)
    def pair(label,value):block(label+': '+str(value or 'No registrado'))
    block(company['name'],13,True,4,True)
    block('COMPROBANTE DE RECEPCIÓN',9,True,6,True)
    if order.get('preview'):block('VISTA PREVIA · DATOS FICTICIOS',8,True,5,True)
    # Módulos enteros de impresora y zona de silencio de cuatro módulos.
    matrix=list(segno.make_qr(order['qr_url'],error='m').matrix)
    qr_unit=4*DOT;qr_size=(len(matrix)+8)*qr_unit
    if qr_size>W-2*M:qr_unit=3*DOT;qr_size=(len(matrix)+8)*qr_unit
    if qr_size>W-2*M:raise ValueError('El QR excede el ancho imprimible.')
    ops.append(('qr',y,qr_size,qr_unit,matrix));y+=qr_size+7
    block(order['code'],13,True,4,True)
    received=datetime.fromisoformat(order['received_at']).astimezone(ECUADOR_TZ)
    block('RECEPCIÓN',9,True,3)
    pair('Fecha y hora',received.strftime('%d/%m/%Y %H:%M:%S')+' · Ecuador')
    pair('Estado',order['status_label'])
    section('CLIENTE');pair('Nombre',order['client'])
    pair({'ruc':'RUC','pasaporte':'Pasaporte'}.get(order.get('document_type'),'Identificación'),order.get('identification'))
    pair('Teléfono',order.get('phone'))
    section('EQUIPO');pair('Tipo',DEVICE_TYPES.get(order['type'],order['type']))
    pair('Marca / modelo',' '.join(filter(None,[order.get('brand'),order.get('model')])));pair('Serie',order.get('serial'))
    pair('Accesorios',order.get('accessories'));pair('Estado físico',order.get('physical_condition'));pair('Falla reportada',order['problem'])
    section('AUTORIZACIÓN DE ACCESO TÉCNICO')
    access=order.get('access_authorization')
    block('Acceso técnico: '+({'authorized':'AUTORIZADO','denied':'NO AUTORIZADO'}[access['decision']] if access else 'No consta autorización'),9,True,4)
    if access:
        granted=[label for key,label in SCOPES.items() if access['permissions'].get(key)]
        if granted:block('Alcance autorizado: '+'. '.join(granted)+'.',9)
        block('Decisión registrada: '+datetime.fromisoformat(access['recorded_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S'),8)
        block('Responsable: '+access['operator'],8)
    destructive=order.get('destructive_authorization')
    block('Reinstalar / formatear / eliminar: '+({'authorized':'AUTORIZACIÓN ADICIONAL REGISTRADA','denied':'NO AUTORIZADO'}[destructive['decision']] if destructive else 'Sin autorización adicional'),8,True)
    block('El diagnóstico no autoriza revisar datos privados ni borrar información fuera del alcance expresamente acordado.',8)
    section('CONDICIONES DEL SERVICIO · RESUMEN')
    terms=order.get('terms')
    if terms:
        block('Versión aceptada: '+terms['version'],8,True)
    else:block('Orden histórica: no consta aceptación de condiciones. Este resumen informa; no acredita consentimiento.',9,True,5)
    for n,paragraph in enumerate(SUMMARY,1):block(str(n)+'. '+paragraph,9,gap=4)
    if terms:
        block('Aceptación registrada: '+datetime.fromisoformat(order['terms_accepted_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S'),8)
        block('La versión completa aceptada se conserva sin cambios. Consulta:',8)
        link=terms['url']
    else:
        block('Condiciones vigentes para consulta; requieren aceptación expresa:',8)
        link=company['website'].rstrip('/')+'/conditions'
    link_top=y;block(link,8,gap=7);link_bottom=y
    section('LOCALIZACIÓN DE LA ORDEN')
    block('Uso interno: escanear con sesión autorizada.',8,center=True,gap=8)
    bars=barcode_widths(order['code']);unit=2*DOT;total=(sum(bars)+20)*unit
    if total>W-2*M:raise ValueError('Identificador demasiado largo para Code 128 a dos puntos por módulo.')
    ops.append(('barcode',y,bars,unit,total));y+=17*72/25.4+10
    block(order['code'],10,True,7,True)
    block(company['thanks'],9,True,5,True);block('WhatsApp: '+company['whatsapp'],9,center=True)
    block(company['website'],8,center=True);block(company['support_email'],8,center=True)
    height=y+12;stream=pydyf.Stream(compress=True);pdf.add_object(stream);stream.set_color_rgb(0,0,0)
    for op in ops:
        if op[0]=='text':
            _,value,top,size,bold,center=op;x=(W-text_width(value,size))/2 if center else M
            stream.begin_text();stream.set_font_size('F2' if bold else 'F1',size);stream.set_text_matrix(1,0,0,1,x,height-top-size);stream.show_text_string(value.encode('cp1252','replace'));stream.end_text()
        elif op[0]=='rule':
            stream.set_line_width(.35);stream.move_to(M,height-op[1]);stream.line_to(W-M,height-op[1]);stream.stroke()
        elif op[0]=='qr':
            _,top,size,unit,matrix=op;left=(W-size)/2
            for row,values in enumerate(matrix):
                for col,dark in enumerate(values):
                    if dark:stream.rectangle(left+(col+4)*unit,height-top-(row+5)*unit,unit,unit)
            stream.fill()
        elif op[0]=='barcode':
            _,top,bars,unit,total=op;left=(W-total)/2+10*unit
            for i,width in enumerate(bars):
                if i%2==0:stream.rectangle(left,height-top-17*72/25.4,width*unit,17*72/25.4)
                left+=width*unit
            stream.fill()
    annotation=pydyf.Dictionary({'Type':'/Annot','Subtype':'/Link','Rect':pydyf.Array([M,height-link_bottom,W-M,height-link_top]),'Border':pydyf.Array([0,0,0]),'A':pydyf.Dictionary({'S':'/URI','URI':pydyf.String(link)})});pdf.add_object(annotation)
    page=pydyf.Dictionary({'Type':'/Page','Parent':pdf.pages.reference,'MediaBox':pydyf.Array([0,0,W,height]),'Resources':pydyf.Dictionary({'Font':pydyf.Dictionary(fonts)}),'Contents':stream.reference,'Annots':pydyf.Array([annotation.reference])})
    pdf.add_page(page);output=io.BytesIO();pdf.write(output);return output.getvalue()
