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
from service_terms import numbered_paragraphs
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
            y=239
        else:
            text(order['code']+'  |  Continuación',36,105,10,BLUE,True);y=138
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
        if y+53>H-100:new_page()
        rect(36,y,W-72,24,PANEL);text(title.upper(),47,y+6,9,BLUE,True);y+=30

    def item(label,value):
        nonlocal y
        lines=wrapped(value,W-94)
        height=14+len(lines)*14+6
        if height<=H-238 and y+height>H-100:new_page()
        elif y+38>H-100:new_page()
        text(label,47,y,8,MUTED,True);y+=14
        for content in lines:
            if y+17>H-100:new_page();text(label+' (continuación)',47,y,8,MUTED,True);y+=16
            text(content,47,y,10,TEXT);y+=14
        y+=6

    def pair(left_label,left_value,right_label,right_value):
        nonlocal y
        width=(W-114)/2
        left=wrapped(left_value,width);right=wrapped(right_value,width)
        height=14+max(len(left),len(right))*14+6
        if height>H-238:
            item(left_label,left_value);item(right_label,right_value);return
        if y+height>H-100:new_page()
        for x,label,lines in [(47,left_label,left),(W/2+10,right_label,right)]:
            text(label,x,y,8,MUTED,True)
            for index,value in enumerate(lines):text(value,x,y+14+index*14,10,TEXT)
        y+=height

    def coded(name,code):
        value=order.get(name) or 'No registrado'
        return value+(' ('+order[code]+')' if order.get(code) else '')

    new_page(True)
    section('Datos del cliente')
    pair('Nombres y apellidos / Razón social',order['client'],
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
    if order.get('_service') and order.get('technician_notes'):item('Observaciones internas de recepción',order['technician_notes'])
    if order.get('_service'):
        section('Seguimiento técnico interno')
        pair('Responsable',order.get('responsible'),'Prioridad',str(order.get('priority') or 'Normal').capitalize())
        item('Entrega estimada',order.get('estimated_delivery') or 'Sin definir')
        for key,label in [('current_problem','Descripción de trabajo actual'),('internal_notes','Observaciones del técnico'),('findings','Hallazgos internos'),('recommendations','Recomendaciones')]:
            if order.get(key):item(label,order[key])
        section('Presupuesto USD')
        money=lambda key:format(order['budget'].get(key+'_cents',0)/100,'.2f')+' USD'
        pair('Mano de obra',money('labor'),'Repuestos',money('parts'))
        pair('Servicios',money('services'),'Productos digitales',money('digital'))
        item('Total',money('total'))
        for entry in order.get('budget_lines',[]):item(entry['description'],format(entry['amount_cents']/100,'.2f')+' USD')
        section('Historial técnico')
        for entry in order.get('history',[]):
            when=datetime.fromisoformat(entry['occurred_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S')
            item(when+' | '+(entry.get('actor') or 'Migración del sistema'),entry['status_label']+' · '+entry['comment'])
    terms=order.get('terms')
    if terms:
        section('Resumen de condiciones del servicio')
        item('Versión / Vigencia',terms['version']+' / '+terms['effective_date'])
        for number,paragraph in numbered_paragraphs(terms['compact_text']):item(str(number)+'.',paragraph)
        item('Condiciones completas',terms['url'])
        if y+120>H-100:new_page()
        section('Aceptación de condiciones')
        item('Versión / Vigencia',terms['version']+' / '+terms['effective_date'])
        item('Aceptación del cliente',order['terms_acceptor'])
        accepted=datetime.fromisoformat(order['terms_accepted_at']).astimezone(ECUADOR_TZ)
        item('Fecha, hora y mecanismo',accepted.strftime('%d/%m/%Y %H:%M:%S')+' Ecuador | '+order['terms_mechanism_label'])
        item('Registro / Usuario responsable',order['terms_acceptance_id']+' / '+order['terms_operator'])
        item('Consulta segura de esta versión',terms['url'])
        item('Integridad SHA-256',terms['content_hash'])
        section(terms['title'])
        item('Versión / Vigencia',terms['version']+' / '+terms['effective_date'])
        for number,paragraph in numbered_paragraphs(terms['full_text']):
            lines=wrapped(str(number)+'. '+paragraph,W-94,9)
            height=len(lines)*13+12
            if y+height>H-100:new_page()
            for content in lines:text(content,47,y,9,TEXT);y+=13
            y+=12
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
        policies=load_policies();new_page();section(policies['title'])
        for paragraph in policies['paragraphs']:
            heading=bool(re.match(r'^(\d+\.|\d+ -)\s',paragraph)) and len(paragraph)<60
            lines=wrapped(paragraph,W-94,9.5 if heading else 9)
            if y+len(lines)*13+8>H-100:new_page()
            for content in lines:text(content,47,y,9.5 if heading else 9,TEXT,heading);y+=13
            y+=7
        if y+30>H-100:new_page()
        text('Versión del documento: '+policies['version']+' · Integridad SHA-256: '+policies['sha256'][:32]+'…',47,y+4,7,MUTED)
    output=io.BytesIO();pdf.write(output);return output.getvalue()
