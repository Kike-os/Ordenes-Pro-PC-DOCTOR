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

def jpeg_size(data):
    """(ancho, alto, componentes) leídos del marcador SOF de un JPEG, o None."""
    if not data or data[:3]!=b'\xff\xd8\xff':return None
    i=2
    while i+9<len(data):
        if data[i]!=0xFF:return None
        marker=data[i+1];length=int.from_bytes(data[i+2:i+4],'big')
        if marker in (0xC0,0xC1,0xC2):return int.from_bytes(data[i+7:i+9],'big'),int.from_bytes(data[i+5:i+7],'big'),data[i+9]
        i+=2+length
    return None

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
    def box(self,x,y,width,height,color):
        """Rectángulo relleno (fondos de encabezados y filas alternas); y es el borde superior, como en text()."""
        if self.mono:return
        self.stream.set_color_rgb(*color);self.stream.rectangle(x,self.h-y-height,width,height);self.stream.fill()
    def width_of(self,value,size=9,bold=False):
        return sum(WIDTHS.get(c,556) for c in str(value))*size/1000*(1.06 if bold else 1)
    def jpeg(self,name,data):
        """Registra una fotografía JPEG (se incrusta tal cual, sin recodificar). Devuelve (ancho, alto) o None si no es un JPEG válido."""
        size=jpeg_size(data)
        if not size:return None
        if name not in self.resources['XObject']:
            image=pydyf.Stream([data],extra={'Type':'/XObject','Subtype':'/Image','Width':size[0],'Height':size[1],'ColorSpace':'/DeviceRGB' if size[2]==3 else '/DeviceGray','BitsPerComponent':8,'Filter':'/DCTDecode'})
            self.pdf.add_object(image);self.resources['XObject'][name]=image.reference
        return size[:2]
    def photo(self,name,data,x,y,box):
        """Fotografía centrada en un cuadro de `box` puntos (y es el borde superior). Devuelve True si se dibujó."""
        size=self.jpeg(name,data)
        if not size:return False
        scale=box/max(size);w,h=size[0]*scale,size[1]*scale;self.stream.push_state();self.stream.set_matrix(w,0,0,h,x+(box-w)/2,self.h-y-box+(box-h)/2);self.stream.draw_x_object(name);self.stream.pop_state();return True
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
    def business_signature(self, kind, y, bottom, new_page=None, left=42, right=None, sig=None):
        """1.5.271 · Bloque de firma visual empresarial (si administración la activó para este tipo de documento), con su leyenda:
        es una imagen de identificación, no una firma electrónica. Si no cabe, usa new_page() (que devuelve el nuevo y) o no se dibuja.
        Devuelve el y siguiente."""
        import business_signature as bs
        sig=sig or bs.for_doc(kind)
        if not sig:return y
        right=self.w-42 if right is None else right
        w,h=bs.size_pt(sig);box=max(w,230);lines=self.wrap(bs.CAPTION,box,6.5);need=h+6+len(lines)*8.5
        if y+need>bottom:
            if not new_page:return y
            y=new_page()
        x=bs.x_for(sig,left,right);bs.draw(self.pdf,self.stream,self.resources,self.h,x,y,sig);y+=h+5
        tx=min(max(left,x+(w-box)/2 if sig['align']=='centro' else x if sig['align']=='izquierda' else x+w-box),right-box)
        for line in lines:self.text(line,tx,y,6.5,False,GRAY);y+=8.5
        return y
    def finish(self):
        result=io.BytesIO();self.pdf.write(result);return result.getvalue()
