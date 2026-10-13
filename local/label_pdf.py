"""Etiqueta independiente: tamaño físico explícito y QR original."""
from datetime import datetime
from document_canvas import Canvas,BLUE,GRAY
from corporate import settings
from reception import DEVICE_TYPES,ECUADOR_TZ

SIZES={'80x50':(80,50),'100x60':(100,60),'100x80':(100,80)}

def dimensions(query):
    size=query.get('size',['100x60'])[0]
    if size in SIZES:return SIZES[size]
    if size!='custom':raise ValueError('Selecciona un tamaño de etiqueta disponible.')
    try:
        width=float(query.get('width',[''])[0]);height=float(query.get('height',[''])[0])
        if not (60<=width<=120 and 50<=height<=120):raise ValueError()
    except (ValueError,TypeError):raise ValueError('El tamaño personalizado admite ancho 60–120 mm y alto 50–120 mm.')
    return width,height

def render_label(order,width=100,height=60,show_client=False,monochrome=False):
    scale=72/25.4;w=width*scale;h=height*scale;m=8;company=settings();pdf=Canvas(w,h,'Etiqueta del equipo '+order['code'],monochrome);pdf.page();pdf.logo(m,7,34)
    pdf.text(company['name'],m+42,10,10,True,BLUE);pdf.text('ETIQUETA DEL EQUIPO',m+42,25,7,False,GRAY)
    pdf.text(order['code'],m,38,11,True,BLUE)
    received=datetime.fromisoformat(order['received_at']).astimezone(ECUADOR_TZ);pdf.text('Recepción: '+received.strftime('%d/%m/%Y %H:%M'),m,52,7,False,GRAY);pdf.line(m,64,w-2*m)
    qr_size=min(64,h-86);text_width=w-3*m-qr_size;y=70
    entries=[]
    if show_client:entries.append(('Cliente',order['client']))
    entries.extend([('Equipo',' · '.join(part for part in (order.get('device_code') or '',DEVICE_TYPES.get(order['type'],order['type'])) if part)),('Marca / modelo',' '.join(str(order.get(k) or '') for k in ('brand','model')) or 'No registrado'),('Serie',order.get('serial') or 'No registrada')])
    for label,value in entries:
        lines=pdf.wrap(label+': '+value,text_width,7)
        for text in lines:
            if y+9>h-m:raise ValueError('Los datos no caben completos en esta etiqueta. Selecciona un tamaño mayor o desactiva el nombre del cliente.')
            pdf.text(text,m,y,7);y+=9
        y+=3
    pdf.qr(order['qr_url'],w-m-qr_size,70,qr_size)
    pdf.text('Seguimiento',w-m-qr_size,70+qr_size+2,5.5,False,GRAY)
    return pdf.finish()
