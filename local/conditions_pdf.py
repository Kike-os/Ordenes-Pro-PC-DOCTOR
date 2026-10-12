"""Documento institucional de condiciones (A4). Sirve para el borrador en revisión y para una versión publicada.

Nunca registra aceptación ni contiene firmas: la aceptación del cliente se guarda aparte, en cada orden, vinculada a la
versión exacta y a su huella. Pensado para leerse bien impreso en blanco y negro."""
import hashlib
from datetime import date
from document_canvas import Canvas,BLUE,GRAY,INK
from corporate import settings
from service_terms import numbered_paragraphs

TITLE='CONDICIONES DE RECEPCIÓN Y SERVICIOS'
FILE_NAME='CONDICIONES DE RECEPCIÓN Y SERVICIOS.pdf'
DRAFT_FILE_NAME='BORRADOR - CONDICIONES DE RECEPCIÓN Y SERVICIOS.pdf'
LEFT,RIGHT,BOTTOM=42,553,780


def render_conditions(document):
    company=settings();draft=bool(document.get('draft'));width=RIGHT-LEFT
    pdf=Canvas(595.28,841.89,('BORRADOR · ' if draft else '')+'Condiciones de Recepción y Servicios · '+company['name']);y=0
    digest=document.get('content_hash') or hashlib.sha256(document['full_text'].encode()).hexdigest()

    def fill(x,top,w,h,color):
        pdf.stream.set_color_rgb(*color);pdf.stream.rectangle(x,pdf.h-top-h,w,h);pdf.stream.fill()

    def frame(x,top,w,h,color,weight=.9):
        for box in ((x,top,w,weight),(x,top+h-weight,w,weight),(x,top,weight,h),(x+w-weight,top,weight,h)):fill(*box,color)

    def centered(value,top,size,bold,color):
        pdf.text(value,LEFT+(width-pdf_width(value,size,bold))/2,top,size,bold,color)

    def pdf_width(value,size,bold):
        # Ancho aproximado con las métricas de Helvetica; la negrita es algo más ancha.
        from document_canvas import WIDTHS
        return sum(WIDTHS.get(char,556) for char in value)*size/1000*(1.06 if bold else 1)

    def page():
        nonlocal y
        pdf.page();fill(0,0,pdf.w,5,BLUE)
        pdf.logo(LEFT,26,60);pdf.text(company['name'],LEFT+72,28,18,True,BLUE);pdf.text(company['specialty'].upper(),LEFT+72,52,8,True,GRAY)
        pdf.line(LEFT,86,width)
        # Pie compacto con el contacto oficial y el número de página.
        pdf.line(LEFT,BOTTOM+14,width);pdf.text(company['website']+'  |  WhatsApp: '+company['whatsapp']+'  |  '+company['support_email'],LEFT,BOTTOM+22,7.5,False,GRAY)
        pdf.text(('Borrador ' if draft else 'Versión ')+document['version']+'  ·  Página '+str(pdf.pages),LEFT,BOTTOM+34,7.5,False,GRAY)
        if pdf.pages==1:
            centered(TITLE,100,15.5,True,BLUE)
            if draft:
                frame(LEFT,126,width,34,INK,1.1);centered('BORRADOR PARA REVISIÓN · SIN VIGENCIA CONTRACTUAL',133,9.5,True,INK)
                centered('Referencia '+document['version']+' · Vigencia pendiente de aprobación administrativa',147,8,False,GRAY)
            else:
                effective=document.get('effective_date') or ''
                try:effective=date.fromisoformat(effective).strftime('%d/%m/%Y')
                except ValueError:pass
                fill(LEFT,126,width,34,(.93,.95,.98));fill(LEFT,126,3,34,BLUE);centered('Versión '+document['version']+' · Vigente desde el '+effective,133,9.5,True,BLUE)
                centered('Documento oficial publicado por '+company['name'],147,8,False,GRAY)
            y=170
        else:
            pdf.text(TITLE+' (continuación)',LEFT,96,9,True,BLUE);y=118

    page()
    for number,paragraph in numbered_paragraphs(document['full_text']):
        heading,_,body=paragraph.partition('\n')
        if not body.strip():heading,body='',paragraph
        lines=pdf.wrap(body.strip(),width-14,9.6);height=(22 if heading else 0)+len(lines)*12.8+8
        if height>560:raise ValueError('Divide la cláusula para que no se corte en impresión.')
        if y+height>BOTTOM:page()
        if heading:
            # Encabezado de apartado: banda clara, filete y número en recuadro; legible también sin color.
            fill(LEFT,y,width,19,(.93,.95,.98));fill(LEFT,y,3,19,BLUE);fill(LEFT+9,y+3,15,13,BLUE)
            label=str(number);pdf.text(label,LEFT+16.5-pdf_width(label,8.5,True)/2,y+5.2,8.5,True,(1,1,1));pdf.text(heading.strip().upper(),LEFT+31,y+5,9.6,True,BLUE);y+=23
        for index,line in enumerate(lines):
            pdf.text(line if heading or index else str(number)+'. '+line,LEFT+7,y,9.6,False,INK);y+=12.8
        y+=7
    # Cierre: cómo se acepta y a qué queda vinculada la aceptación. Sin firmas ni consentimientos impresos.
    closing=[('ACEPTACIÓN Y VERSIÓN',True),*((line,False) for line in pdf.wrap('La aceptación del cliente se registra por separado en cada orden de recepción y queda vinculada a esta versión exacta y a su huella. Este documento no contiene firmas ni consentimientos.',width-18,8.2)),
             ('Referencia: '+document['version']+'   ·   Huella SHA-256: '+digest[:32]+'…',False)]
    if draft:closing.append(('Borrador pendiente de aprobación administrativa: no debe entregarse a clientes como documento vigente.',False))
    box=len(closing)*10.8+12
    if y+box>BOTTOM:page()
    frame(LEFT,y,width,box,(.55,.60,.68),.7);top=y+7
    for value,bold in closing:pdf.text(value,LEFT+9,top,8.2,bold,BLUE if bold else GRAY);top+=10.8
    return pdf.finish()
