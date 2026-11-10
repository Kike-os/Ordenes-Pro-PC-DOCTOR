"""Comprobante A4 con QR vectorial; biblioteca PDF portable, sin procesos externos."""
from datetime import datetime
import io
import re
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
import pydyf
import segno
from reception import DEVICE_TYPES, ECUADOR_TZ
from document_logo import pdf_image
from service_terms import numbered_paragraphs,clauses
from corporate import settings

WIDTHS=json.loads((ROOT/'data/helvetica-widths.json').read_text())
W,H=595.28,841.89
BG=(1,1,1)
PANEL=(.93,.96,.99)
TEXT=(.10,.15,.22)
MUTED=(.34,.40,.49)
BLUE=(.08,.25,.47)


def render_receipt(order):
    company=settings()
    # «dinamico»: autorizaciones según el tipo de equipo y composición compacta. Las órdenes anteriores sin versión corregida se
    # generan exactamente como se emitieron (misma huella SHA-256 que el comprobante enviado).
    dynamic=order.get('receipt_layout')=='dinamico';fix=(order.get('receipt_corrections') or [None])[-1] if dynamic else None
    pdf=pydyf.PDF()
    for key,value in [('Title',('Hoja de servicio técnico ' if order.get('_service') else 'Comprobante de recepción ')+order['code']),('Author','PC-DOCTOR S.A.')]:
        pdf.info[key]=pydyf.String(value)
    fonts={}
    for key,name in [('F1','Helvetica'),('F2','Helvetica-Bold')]:
        font=pydyf.Dictionary({'Type':'/Font','Subtype':'/Type1','BaseFont':'/'+name,'Encoding':'/WinAnsiEncoding'})
        pdf.add_object(font);fonts[key]=font.reference
    logo,logo_width,logo_height=pdf_image(pdf)
    resources=pydyf.Dictionary({'Font':pydyf.Dictionary(fonts),'XObject':pydyf.Dictionary({'Logo':logo})})
    stream=None;page_count=0;y=0

    def rect(x,top,w,h,color):
        stream.set_color_rgb(*color);stream.rectangle(x,H-top-h,w,h);stream.fill()

    def text(value,x,top,size=10,color=TEXT,bold=False):
        clean=str(value).replace('\r',' ').replace('\n',' ').encode('cp1252','replace')
        stream.set_color_rgb(*color);stream.begin_text();stream.set_font_size('F2' if bold else 'F1',size)
        stream.set_text_matrix(1,0,0,1,x,H-top-size);stream.show_text_string(clean);stream.end_text()

    def line(top):
        rect(36,top,W-72,.6,(.16,.25,.36))

    def new_page(first=False):
        nonlocal stream,page_count,y
        stream=pydyf.Stream(compress=True);pdf.add_object(stream)
        page=pydyf.Dictionary({'Type':'/Page','Parent':pdf.pages.reference,'MediaBox':pydyf.Array([0,0,W,H]),'Resources':resources,'Contents':stream.reference})
        pdf.add_page(page);page_count+=1
        rect(0,0,W,H,BG);rect(0,0,W,5,(.15,.40,.76))
        stream.push_state();stream.set_matrix(64,0,0,64*logo_height/logo_width,36,H-28-64*logo_height/logo_width);stream.draw_x_object('Logo');stream.pop_state()
        text(company['name'],112,29,18,BLUE,True)
        text(company['specialty'].upper(),112,55,8,MUTED,True)
        text('HOJA DE SERVICIO TÉCNICO' if order.get('_service') else 'COMPROBANTE DE RECEPCIÓN TÉCNICA',112,74,10,TEXT,True)
        if first:
            text('ESTADO: '+order['status_label'].upper(),36,110,8,BLUE,True)
            text('N.º DE ORDEN',36,135,8,MUTED,True)
            size=18 if len(order['code'])<24 else 14
            text(order['code'],36,151,size,TEXT,True)
            received=datetime.fromisoformat(order['received_at']).astimezone(ECUADOR_TZ)
            text('Fecha de recepción: '+received.strftime('%d/%m/%Y'),36,185,10,TEXT)
            text('Hora: '+received.strftime('%H:%M:%S')+'  |  Ecuador (UTC-05:00)',36,204,9,MUTED)
            qr=segno.make_qr(order['qr_url'],error='m')
            matrix=list(qr.matrix);count=len(matrix)+8;size=122;unit=size/count;left=W-36-size;top=36
            rect(left,top,size,size,(1,1,1))
            stream.set_color_rgb(.04,.10,.18)
            for row,values in enumerate(matrix):
                for col,dark in enumerate(values):
                    if dark:stream.rectangle(left+(col+4)*unit,H-top-(row+5)*unit,unit+.015,unit+.015)
            stream.fill()
            text('Escanee para consultar el estado',left+5,top+size+8,7,BLUE,True)
            text('de su reparación',left+5,top+size+19,7,BLUE,True)
            annotation=pydyf.Dictionary({'Type':'/Annot','Subtype':'/Link','Rect':pydyf.Array([left,H-top-size,left+size,H-top]),'Border':pydyf.Array([0,0,0]),'A':pydyf.Dictionary({'S':'/URI','URI':pydyf.String(order['qr_url'])})})
            pdf.add_object(annotation);page['Annots']=pydyf.Array([annotation.reference])
            y=224
            if fix:
                text('COMPROBANTE CORREGIDO · REVISIÓN '+str(fix['revision'])+' · '+datetime.fromisoformat(fix['created_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y'),36,219,7.5,BLUE,True);y=236
        else:
            text(order['code']+'  |  Continuación',36,100,10,BLUE,True);y=124
        line(H-85)
        text(company['commitment'],36,H-76,7,MUTED)
        text(company['thanks'],36,H-63,8,BLUE,True)
        text('WhatsApp: '+company['whatsapp']+' | '+company['website'],36,H-48,7,MUTED)
        text(company['support_email'],36,H-35,7,MUTED)
        text(str(page_count),W-45,H-35,8,MUTED)

    def wrapped(value,width,size=10):
        lines=[]
        for para in str(value or 'No registrado').splitlines() or ['No registrado']:
            current=''
            for char in para:
                candidate=current+char
                measured=sum(WIDTHS.get(c,556) for c in candidate)*size/1000
                if measured>width and current:
                    # Cortar en palabra cuando sea posible y también admitir series largas.
                    if ' ' in current:
                        cut=current.rfind(' ');lines.append(current[:cut]);current=current[cut+1:]+char
                    else:lines.append(current);current=char
                else:current=candidate
            lines.append(current or ' ')
        return lines

    def section(title):
        nonlocal y
        # Un título de sección nunca queda solo al pie de la página.
        if y+78>H-100:new_page()
        y+=3;rect(36,y,W-72,19,PANEL);rect(36,y,3,19,(.15,.40,.76));text(title.upper(),47,y+5,8.5,BLUE,True);y+=25

    def item(label,value):
        nonlocal y
        lines=wrapped(value,W-94,9.5)
        height=11+len(lines)*12.5+4
        if height<=H-238 and y+height>H-100:new_page()
        elif y+34>H-100:new_page()
        text(label,47,y,7.5,MUTED,True);y+=11
        for content in lines:
            if y+15>H-100:new_page();text(label+' (continuación)',47,y,7.5,MUTED,True);y+=13
            text(content,47,y,9.5,TEXT);y+=12.5
        y+=4

    def pair(left_label,left_value,right_label,right_value):
        nonlocal y
        width=(W-114)/2
        left=wrapped(left_value,width,9.5);right=wrapped(right_value,width,9.5)
        height=11+max(len(left),len(right))*12.5+4
        if height>H-238:
            item(left_label,left_value);item(right_label,right_value);return
        if y+height>H-100:new_page()
        for x,label,lines in [(47,left_label,left),(W/2+10,right_label,right)]:
            text(label,x,y,7.5,MUTED,True)
            for index,value in enumerate(lines):text(value,x,y+11+index*12.5,9.5,TEXT)
        y+=height

    def coded(name,code):
        value=order.get(name) or 'No registrado'
        return value+(' ('+order[code]+')' if order.get(code) else '')

    new_page(True)
    section('Datos del cliente')
    pair('Nombres y Apellidos / Razón social',order['client'],
         'Identificación',({'ruc':'RUC','pasaporte':'Pasaporte'}.get(order.get('document_type'),'Cédula'))+': '+(order.get('identification') or 'No registrado'))
    if order.get('trade_name'):item('Nombre comercial',order['trade_name'])
    pair('Teléfono / WhatsApp',order.get('phone'),'Correo electrónico',order.get('email'))
    pair('Provincia / Cantón',coded('province','province_code')+' / '+coded('canton','canton_code'),
         'Parroquia / Ciudad o localidad',coded('parish','parish_code')+' / '+(order.get('city') or 'No registrado'))
    item('Dirección',order.get('address'))
    if order.get('location_reference'):item('Referencia',order['location_reference'])
    section('Información del equipo')
    pair('Tipo de equipo',DEVICE_TYPES.get(order['type'],order['type']),
         'Marca y modelo',' '.join(v for v in [order.get('brand'),order.get('model')] if v))
    pair('Número de serie',order.get('serial'),'Color',order.get('color'))
    pair('Estado de reparación',order['status_label'],'Accesorios recibidos',order.get('accessories'))
    if order.get('physical_condition'):item('Estado físico del equipo',order['physical_condition'])
    section('Motivo de ingreso')
    item('Problema reportado por el cliente',order['problem'])
    if order.get('customer_notes'):item('Observaciones autorizadas de recepción',order['customer_notes'])
    # Autorizaciones del cliente: estado real de cada una. Lo que no se decidió figura como PENDIENTE, nunca como aceptación ni rechazo.
    access=order.get('access_authorization');risk=order.get('destructive_authorization')
    GREEN,RED,GREY=(.05,.40,.25),(.70,.12,.16),(.42,.46,.52)

    def authorization_height(detail):
        return max(22,14+len(wrapped(detail,W-72-150,8.5))*10.5)+5

    def authorization(title,state,detail):
        """Indicador estático legible también en blanco y negro: relleno oscuro (autorizado), contorno (no autorizado), gris claro
        (pendiente) o contorno gris (no aplica)."""
        nonlocal y
        lines=wrapped(detail,W-72-150,8.5);height=max(22,14+len(lines)*10.5)+5
        if y+height>H-100:new_page()
        label={'authorized':'AUTORIZADO','denied':'NO AUTORIZADO','pending':'PENDIENTE','not_applicable':'NO APLICA'}[state];left,top,bw,bh=47,y,112,17
        if state=='authorized':rect(left,top,bw,bh,GREEN);ink=(1,1,1)
        elif state=='denied':rect(left,top,bw,bh,RED);rect(left+1.3,top+1.3,bw-2.6,bh-2.6,(1,1,1));ink=RED
        elif state=='not_applicable':rect(left,top,bw,bh,(.70,.73,.77));rect(left+1,top+1,bw-2,bh-2,(1,1,1));ink=GREY
        else:rect(left,top,bw,bh,(.90,.92,.94));ink=GREY
        # Icono vectorial: visto, aspa, guion o barra.
        stream.set_color_rgb(*ink,stroke=True);stream.set_line_width(1.5);cx,cy=left+11,H-top-bh/2
        if state=='authorized':stream.move_to(cx-4,cy);stream.line_to(cx-1.2,cy-3);stream.line_to(cx+4.2,cy+3.4)
        elif state=='denied':stream.move_to(cx-3.4,cy-3.4);stream.line_to(cx+3.4,cy+3.4);stream.move_to(cx-3.4,cy+3.4);stream.line_to(cx+3.4,cy-3.4)
        elif state=='not_applicable':stream.move_to(cx-3,cy-3.6);stream.line_to(cx+3,cy+3.6)
        else:stream.move_to(cx-3.6,cy);stream.line_to(cx+3.6,cy)
        stream.stroke();text(label,left+20,top+4.6,7.6,ink,True)
        text(title,left+bw+11,top,9.5,TEXT,True)
        for index,content in enumerate(lines):text(content,left+bw+11,top+12.5+index*10.5,8.5,MUTED)
        y+=height

    def note(content,size=7.5):
        nonlocal y
        for part in wrapped(content,W-94,size):
            if y+10>H-100:new_page()
            text(part,47,y,size,MUTED);y+=size+2
    if dynamic:
        # Solo los apartados que aplican al tipo de equipo; los demás, en una sola fila «NO APLICA». El bloque no se parte entre páginas.
        import device_authorizations
        shown,missing=device_authorizations.presentation(order)
        profile=order.get('authorization_profile') or {}
        rows=[(title,state,detail) for _,title,state,detail in shown]
        if missing:rows.append(device_authorizations.not_applicable_text(order,missing)[0:1]+('not_applicable',device_authorizations.not_applicable_text(order,missing)[1]))
        decided=[proof for proof in (access,risk) if proof]
        proof=decided[0] if decided and any(state!='pending' for _,state,_ in rows if state!='not_applicable') else None
        notes=[]
        if profile.get('exception'):notes.append('El equipo guarda información del cliente: se aplican las autorizaciones de datos.'+((' '+profile['exception_note']) if profile.get('exception_note') else ''))
        if proof:notes.append('Decisiones expresadas por '+(proof.get('acceptor') or 'el cliente')+' y registradas el '+datetime.fromisoformat(proof['recorded_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S')+' (Ecuador) por '+(proof.get('operator') or 'el personal')+'. Confirmación en pantalla ante el técnico; no constituye una firma.')
        if fix:notes.append('Revisión '+str(fix['revision'])+' del '+datetime.fromisoformat(fix['created_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')+': se muestran solo los apartados que aplican al tipo de equipo. Las decisiones registradas no cambiaron; el comprobante original se conserva (SHA-256 '+fix['original_sha256'][:16]+'…).')
        total=28+sum(authorization_height(detail) for _,_,detail in rows)+sum(len(wrapped(n,W-94,7.5))*9.5 for n in notes)+4
        if y+total>H-100 and total<=H-238:new_page()
        section('Autorizaciones del cliente')
        for row in rows:authorization(*row)
        for content in notes:note(content)
        y+=4
    elif access or risk:
        section('Autorizaciones del cliente')

        permissions=(access or {}).get('permissions') or {};decision=(access or {}).get('decision')
        def scoped(keys,none):
            granted=[label for key,label in keys if permissions.get(key)]
            if decision=='denied':return 'denied','El cliente no autorizó el acceso técnico.'
            if decision=='authorized' and granted:return 'authorized','Alcance autorizado: '+'; '.join(granted)+'.'
            return 'pending',none
        authorization('Acceso al sistema operativo',*scoped((('operating_system','ingreso al sistema operativo'),('signed_in_tests','pruebas de funcionamiento con sesión iniciada')),'Sin autorización registrada para ingresar al sistema operativo.'))
        state,detail=scoped((('specific_files','acceso a archivos específicamente autorizados'),('backup','respaldo de información')),'Sin autorización registrada para revisar archivos ni realizar respaldos.')
        if decision=='authorized' and permissions.get('files_decision')=='denied':state,detail='denied','El cliente rechazó expresamente el acceso a sus archivos personales y la realización de respaldos.'
        if state=='authorized' and access.get('justification'):detail+=' '+access['justification']
        authorization('Acceso a archivos personales y respaldos',state,detail)
        if not risk:authorization('Formateo, reinstalación y eliminación de datos','pending','No se solicitó autorización para modificar o eliminar datos.')
        elif risk['decision']=='authorized':authorization('Formateo, reinstalación y eliminación de datos','authorized','Autorización específica del cliente. '+(risk.get('justification') or ''))
        else:authorization('Formateo, reinstalación y eliminación de datos','denied','El cliente rechazó cualquier modificación o eliminación de datos.')
        proof=access or risk
        when=datetime.fromisoformat(proof['recorded_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S')
        for content in wrapped('Decisiones expresadas por '+(proof.get('acceptor') or 'el cliente')+' y registradas el '+when+' (Ecuador) por '+(proof.get('operator') or 'el personal')+'. Confirmación en pantalla ante el técnico; no constituye una firma.',W-94,7.5):
            if y+10>H-100:new_page()
            text(content,47,y,7.5,MUTED);y+=9.5
        y+=4
    if not order.get('_service'):
        # Constancia de recepción con los dos espacios de firma en un mismo renglón.
        if y+78>H-100:new_page()
        section('Constancia de recepción')
        y+=30;half=(W-72-40)/2
        for index,label in enumerate(('Firma del cliente','Recibido por '+company['name'])):
            left=47+index*(half+18);rect(left,y,half,.6,(.16,.25,.36));text(label,left,y+5,7.5,MUTED,True)
        y+=24
    if order.get('_service') and order.get('technician_notes'):item('Observaciones internas de recepción',order['technician_notes'])
    if order.get('_service'):
        section('Seguimiento técnico interno')
        pair('Responsable',order.get('responsible'),'Prioridad',str(order.get('priority') or 'Normal').capitalize())
        item('Entrega estimada',order.get('estimated_delivery') or 'Sin definir')
        for key,label in [('current_problem','Descripción de trabajo actual'),('internal_notes','Observaciones del técnico'),('findings','Hallazgos internos'),('recommendations','Recomendaciones')]:
            if order.get(key):item(label,order[key])
        section('Presupuesto')
        from quotes import usd  # mismo formato de importes de todos los documentos: $1.250,00
        money=lambda key:usd(order['budget'].get(key+'_cents',0))
        pair('Mano de obra',money('labor'),'Repuestos',money('parts'))
        pair('Servicios',money('services'),'Productos digitales',money('digital'))
        item('Total',money('total'))
        for entry in order.get('budget_lines',[]):item(entry['description'],usd(entry['amount_cents']))
        section('Historial técnico')
        for entry in order.get('history',[]):
            when=datetime.fromisoformat(entry['occurred_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S')
            item(when+' | '+(entry.get('actor') or 'Migración del sistema'),entry['status_label']+' · '+entry['comment'])
    terms=order.get('terms')
    if terms:
        section('Resumen de condiciones del servicio')
        item('Versión / Vigencia',terms['version']+' / '+terms['effective_date'])
        if dynamic:
            # Número y texto en el mismo renglón con sangría francesa: mismo tamaño de letra, sin una línea solo para el número.
            for number,paragraph in numbered_paragraphs(terms['compact_text']):
                lines=wrapped(paragraph,W-94-16,9.5)
                if y+len(lines)*12.5+3>H-100:new_page()
                text(str(number)+'.',47,y,9.5,TEXT,True)
                for content in lines:text(content,63,y,9.5,TEXT);y+=12.5
                y+=3
            y+=3
        else:
            for number,paragraph in numbered_paragraphs(terms['compact_text']):item(str(number)+'.',paragraph)
        if y+110>H-100:new_page()
        section('Aceptación de condiciones')
        accepted=datetime.fromisoformat(order['terms_accepted_at']).astimezone(ECUADOR_TZ)
        pair('Aceptación del cliente',order['terms_acceptor'],'Fecha y hora',accepted.strftime('%d/%m/%Y %H:%M:%S')+' Ecuador')
        pair('Mecanismo',order['terms_mechanism_label'],'Registro / Usuario responsable',order['terms_acceptance_id']+' / '+order['terms_operator'])
        item('Consulta segura de esta versión',terms['url'])
        item('Integridad SHA-256',terms['content_hash'])
        if dynamic:
            # El título del texto completo no queda solo al pie: necesita espacio para su primera cláusula.
            first=next(iter(clauses(terms['full_text'])),{'number':1,'title':'','paragraphs':['']})
            if y+28+len(wrapped(str(first['number'])+'. '+(first['title']+'\n' if first['title'] else '')+first['paragraphs'][0],W-94,9))*13+12>H-100:new_page()
        section(terms['title'])
        # 1.5.271: cada cláusula lleva su número una sola vez; sus párrafos de continuación no se numeran.
        for clause in clauses(terms['full_text']):
            for index,paragraph in enumerate(clause['paragraphs']):
                lines=wrapped((str(clause['number'])+'. '+(clause['title']+'\n' if clause['title'] else '') if index==0 else '')+paragraph,W-94,9)
                height=len(lines)*13+(12 if index==len(clause['paragraphs'])-1 else 5)
                if y+height>H-100:new_page()
                for content in lines:text(content,47,y,9,TEXT);y+=13
                y+=12 if index==len(clause['paragraphs'])-1 else 5
    else:
        if order.get('_service'):
            item('Condiciones / aceptación','No registradas; no se atribuye aceptación retroactiva.')
        else:
            if y+100>H-100:new_page()
            section('Condiciones de servicio')
            item('Historial','Esta recepción no tiene condiciones ni aceptación registradas. No se ha atribuido una aceptación retroactiva.')
    if not order.get('_service'):
        # Políticas de Reparaciones: texto oficial literal en página propia. Acompañan al comprobante; no acreditan aceptación.
        from repair_policies import load as load_policies
        policies=load_policies()
        if y+170>H-100:new_page()
        section(policies['title'])
        # Texto oficial literal, compuesto en dos columnas para aprovechar la página.
        gap=18;column=(W-72-gap-11)/2;col=0;top=y;bottom=H-100;tallest=y
        def advance():
            nonlocal col,top,y,tallest
            tallest=max(tallest,y)
            if col==0:col=1;y=top
            else:new_page();section(policies['title']+' (continuación)');col=0;top=y;tallest=y
        is_heading=lambda paragraph:bool(re.match(r'^(\d+\.|\d+ -)\s',paragraph)) and len(paragraph)<60
        # Si el texto no cabe en las dos columnas restantes se compone más ajustado (hasta 7,2 pt) antes de abrir otra página.
        def fits(size,leading):
            column_index,cursor=0,top
            for paragraph in policies['paragraphs']:
                head=is_heading(paragraph);count=len(wrapped(paragraph,column,size+.5 if head else size))
                if cursor+(count*leading+(46 if head else 0))>bottom and cursor>top:
                    if column_index:return False
                    column_index,cursor=1,top
                for _ in range(count):
                    if cursor+leading>bottom:
                        if column_index:return False
                        column_index,cursor=1,top
                    cursor+=leading
                cursor+=5
            return True
        body,lead=next((pair for pair in ((8,10.5),(7.6,9.9),(7.2,9.3)) if fits(*pair)),(8,10.5))
        for paragraph in policies['paragraphs']:
            heading=is_heading(paragraph)
            size=body+.5 if heading else body;lines=wrapped(paragraph,column,size)
            # Un título no se queda solo al pie de la columna.
            if y+(len(lines)*lead+(46 if heading else 0))>bottom and y>top:advance()
            for content in lines:
                if y+lead>bottom:advance()
                text(content,47+col*(column+gap),y,size,TEXT,heading);y+=lead
            y+=5
        y=max(tallest,y)
        # La línea de versión cabe en el margen previo al pie; no justifica una página adicional.
        if y+14>H-78:new_page()
        text('Versión del documento: '+policies['version']+' · Integridad SHA-256: '+policies['sha256'][:32]+'…',47,y+2,7,MUTED)
    # 1.5.271: firma visual empresarial al final (si administración la activó para este documento), con su leyenda: es una imagen de
    # identificación, no una firma electrónica.
    import business_signature
    signature=business_signature.for_doc('servicio' if order.get('_service') else 'comprobante')
    if signature:
        sig_w,sig_h=business_signature.size_pt(signature);box=max(sig_w,230);caption=wrapped(business_signature.CAPTION,box,6.5)
        if y+10+sig_h+6+len(caption)*8.5>H-78:new_page()
        x=business_signature.x_for(signature,47,W-47);business_signature.draw(pdf,stream,resources,H,x,y+10,signature);y+=10+sig_h+6
        tx=max(47,min(x if signature['align']=='izquierda' else x+(sig_w-box)/2 if signature['align']=='centro' else x+sig_w-box,W-47-box))
        for line in caption:text(line,tx,y,6.5,MUTED);y+=8.5
    output=io.BytesIO();pdf.write(output);return output.getvalue()
