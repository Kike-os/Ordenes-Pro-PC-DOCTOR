"""Primitivas PDF vectoriales para documentos corporativos blancos."""
import io
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
import pydyf
import segno
from document_logo import pdf_image
from corporate import settings
WIDTHS=json.loads((Path(__file__).resolve().parent/'data/helvetica-widths.json').read_text())
BLUE=(.08,.25,.47);INK=(.10,.15,.22);GRAY=(.34,.40,.49)

class Canvas:
    def __init__(self,width,height,title,mono=False):
        self.w=width;self.h=height;self.pdf=pydyf.PDF();self.pdf.info['Title']=pydyf.String(title);self.pdf.info['Author']=pydyf.String(settings()['name']);fonts={}
        for key,name in [('F1','Helvetica'),('F2','Helvetica-Bold')]:
            font=pydyf.Dictionary({'Type':'/Font','Subtype':'/Type1','BaseFont':'/'+name,'Encoding':'/WinAnsiEncoding'});self.pdf.add_object(font);fonts[key]=font.reference
        self.image,self.iw,self.ih=pdf_image(self.pdf,mono);self.resources=pydyf.Dictionary({'Font':pydyf.Dictionary(fonts),'XObject':pydyf.Dictionary({'Logo':self.image})});self.mono=mono;self.pages=0
    def page(self):
        self.stream=pydyf.Stream(compress=True);self.pdf.add_object(self.stream);self.current=pydyf.Dictionary({'Type':'/Page','Parent':self.pdf.pages.reference,'MediaBox':pydyf.Array([0,0,self.w,self.h]),'Resources':self.resources,'Contents':self.stream.reference});self.pdf.add_page(self.current);self.pages+=1
    def text(self,value,x,y,size=9,bold=False,color=INK):
        color=(0,0,0) if self.mono else color;self.stream.set_color_rgb(*color);self.stream.begin_text();self.stream.set_font_size('F2' if bold else 'F1',size);self.stream.set_text_matrix(1,0,0,1,x,self.h-y-size);self.stream.show_text_string(str(value).encode('cp1252','replace'));self.stream.end_text()
    def line(self,x,y,width):
        self.stream.set_color_rgb(*((0,0,0) if self.mono else (.75,.80,.86)));self.stream.rectangle(x,self.h-y,width,.5);self.stream.fill()
    def logo(self,x,y,width):
        h=width*self.ih/self.iw;self.stream.push_state();self.stream.set_matrix(width,0,0,h,x,self.h-y-h);self.stream.draw_x_object('Logo');self.stream.pop_state();return h
    def wrap(self,value,width,size=9):
        lines=[]
        for paragraph in str(value or '').splitlines() or ['']:
            current=''
            for char in paragraph:
                candidate=current+char
                if sum(WIDTHS.get(c,556) for c in candidate)*size/1000>width and current:
                    cut=current.rfind(' ')
                    if cut>0:lines.append(current[:cut]);current=current[cut+1:]+char
                    else:lines.append(current);current=char
                else:current=candidate
            lines.append(current)
        return lines
    def qr(self,url,x,y,size):
        values=list(segno.make_qr(url,error='m').matrix);unit=size/(len(values)+8);self.stream.set_color_rgb(0,0,0)
        for row,items in enumerate(values):
            for col,dark in enumerate(items):
                if dark:self.stream.rectangle(x+(col+4)*unit,self.h-y-(row+5)*unit,unit+.01,unit+.01)
        self.stream.fill();annotation=pydyf.Dictionary({'Type':'/Annot','Subtype':'/Link','Rect':pydyf.Array([x,self.h-y-size,x+size,self.h-y]),'Border':pydyf.Array([0,0,0]),'A':pydyf.Dictionary({'S':'/URI','URI':pydyf.String(url)})});self.pdf.add_object(annotation);self.current['Annots']=pydyf.Array([annotation.reference])
    def finish(self):
        result=io.BytesIO();self.pdf.write(result);return result.getvalue()
