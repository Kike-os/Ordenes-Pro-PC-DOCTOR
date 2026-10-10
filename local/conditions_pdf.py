"""Documento de revisión contractual: nunca registra aceptación ni activa cargos."""
from document_canvas import Canvas,BLUE,GRAY
from corporate import settings
from service_terms import numbered_paragraphs

def render_conditions(document):
    company=settings();pdf=Canvas(595.28,841.89,'BORRADOR · Condiciones PC-DOCTOR S.A.');y=0
    def page():
        nonlocal y
        pdf.page();pdf.logo(36,28,62);pdf.text(company['name'],112,29,18,True,BLUE);pdf.text(company['specialty'].upper(),112,55,8,False,GRAY);pdf.text('CONDICIONES DE RECEPCIÓN Y SERVICIO',112,74,10,True,BLUE);pdf.line(36,109,523)
        pdf.text('BORRADOR PARA REVISIÓN · SIN VIGENCIA CONTRACTUAL',36,120,9,True,BLUE)
        pdf.text('Referencia: '+document['version']+' · Vigencia pendiente de aprobación',36,138,8,False,GRAY)
        pdf.line(36,775,523);pdf.text(company['website']+' | WhatsApp: '+company['whatsapp'],36,787,7,False,GRAY);pdf.text(company['support_email'],36,801,7,False,GRAY);pdf.text(str(pdf.pages),550,801,7,False,GRAY);y=168
    page()
    for number,paragraph in numbered_paragraphs(document['full_text']):
        lines=pdf.wrap(str(number)+'. '+paragraph,523,8.5);height=len(lines)*12+10
        if y+height>758:page()
        if height>590:raise ValueError('Divide la cláusula para que no se corte en impresión.')
        for index,line in enumerate(lines):pdf.text(line,36,y,8.5,index==0);y+=12
        y+=6
    note=pdf.wrap(document['review_note'],523,8)
    if y+len(note)*12+12>758:page()
    for line in note:pdf.text(line,36,y,8,False,GRAY);y+=12
    return pdf.finish()
