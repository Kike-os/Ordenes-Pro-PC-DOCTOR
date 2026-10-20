"""Renderizado del logo original para documentos, sin modificar el archivo fuente."""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import struct
import zlib

ROOT=Path(__file__).resolve().parent
LOGO=ROOT/'static/logo-original.png'
# Píxeles ya decodificados del logo para los anchos que usan los documentos. Decodificar el PNG en Python puro tarda varios segundos
# (en Vercel, en cada instancia nueva: el ticket PDF tardaba ~3 s). El archivo lleva la huella del PNG: si el logo cambia, no se usa.
CACHE=ROOT/'static/logo-original.pixels'
CACHE_WIDTHS=(384,416,900)  # recibo monocromo, ticket térmico (LOGO_PX) y documentos A4


def _paeth(a,b,c):
    p=a+b-c;pa=abs(p-a);pb=abs(p-b);pc=abs(p-c)
    return a if pa<=pb and pa<=pc else b if pb<=pc else c


@lru_cache(maxsize=4)
def pixels(out_width=384):
    cached=_from_cache(out_width)
    return cached if cached else decode(out_width)


def _from_cache(out_width):
    try:
        blob=CACHE.read_bytes()
        if blob[:32]!=hashlib.sha256(LOGO.read_bytes()).digest():return None
        header,_,body=zlib.decompress(blob[32:]).partition(b'\n');index=json.loads(header)
    except (OSError,ValueError,zlib.error):return None
    entry=index.get(str(out_width))
    if not entry:return None
    w,h,start,sizes=entry;parts=[];at=start
    for size in sizes:parts.append(bytes(body[at:at+size]));at+=size
    return (w,h,*parts)


def build_cache():
    """Regenera el archivo de píxeles precalculados (ejecutar si cambia el logo: python -c 'import document_logo;document_logo.build_cache()')."""
    index,body={},bytearray()
    for width in CACHE_WIDTHS:
        w,h,*parts=decode(width);index[str(width)]=[w,h,len(body),[len(part) for part in parts]]
        for part in parts:body.extend(part)
    CACHE.write_bytes(hashlib.sha256(LOGO.read_bytes()).digest()+zlib.compress(json.dumps(index).encode()+b'\n'+bytes(body),9))


def decode(out_width=384):
    data=LOGO.read_bytes()
    if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Logo PNG no válido')
    offset=8;compressed=[]
    while offset<len(data):
        size=struct.unpack('>I',data[offset:offset+4])[0];kind=data[offset+4:offset+8];chunk=data[offset+8:offset+8+size];offset+=size+12
        if kind==b'IHDR':width,height,depth,color,_,_,interlace=struct.unpack('>IIBBBBB',chunk)
        elif kind==b'IDAT':compressed.append(chunk)
    if (depth,color,interlace)!=(8,6,0):raise ValueError('Se requiere logo RGBA de 8 bits sin entrelazado')
    raw=zlib.decompress(b''.join(compressed));stride=width*4;previous=bytearray(stride);rows=[]
    left=width;right=0;top=height;bottom=0
    for y in range(height):
        start=y*(stride+1);mode=raw[start];row=bytearray(raw[start+1:start+stride+1])
        if mode==1:
            for x in range(4,stride):row[x]=(row[x]+row[x-4])&255
        elif mode==2:
            row=bytearray((a+b)&255 for a,b in zip(row,previous))
        elif mode in (3,4):
            for x in range(stride):
                a=row[x-4] if x>=4 else 0;b=previous[x];c=previous[x-4] if x>=4 else 0
                row[x]=(row[x]+((a+b)//2 if mode==3 else _paeth(a,b,c)))&255
        elif mode!=0:raise ValueError('Filtro PNG no compatible')
        alpha=row[3::4];visible=[i for i,a in enumerate(alpha) if a]
        if visible:left=min(left,visible[0]);right=max(right,visible[-1]+1);top=min(top,y);bottom=y+1
        rows.append(row);previous=row
    if left>=right:raise ValueError('El logo no contiene píxeles visibles')
    out_height=round(out_width*(bottom-top)/(right-left));rgb=bytearray();alpha=bytearray();mono=bytearray()
    for y in range(out_height):
        source=rows[min(bottom-1,top+int((y+.5)*(bottom-top)/out_height))];packed=bytearray((out_width+7)//8)
        for x in range(out_width):
            sx=min(right-1,left+int((x+.5)*(right-left)/out_width));r,g,b,a=source[sx*4:sx*4+4];rgb.extend((r,g,b));alpha.append(a)
            gray=(.2126*r+.7152*g+.0722*b)*a/255+255-a
            if gray>=180:packed[x//8]|=1<<(7-x%8)
        mono.extend(packed)
    return out_width,out_height,bytes(rgb),bytes(alpha),bytes(mono)


def pdf_image(pdf,monochrome=False):
    import pydyf
    w,h,rgb,alpha,mono=pixels(384 if monochrome else 900)
    extra={'Type':'/XObject','Subtype':'/Image','Width':w,'Height':h,'ColorSpace':'/DeviceGray' if monochrome else '/DeviceRGB','BitsPerComponent':1 if monochrome else 8,'Interpolate':'false' if monochrome else 'true'}
    if not monochrome:
        mask=pydyf.Stream([alpha],extra={'Type':'/XObject','Subtype':'/Image','Width':w,'Height':h,'ColorSpace':'/DeviceGray','BitsPerComponent':8},compress=True);pdf.add_object(mask);extra['SMask']=mask.reference
    image=pydyf.Stream([mono if monochrome else rgb],extra=extra,compress=True);pdf.add_object(image)
    return image.reference,w,h


@lru_cache(maxsize=1)
def monochrome_png():
    w,h,_,_,mono=pixels();stride=(w+7)//8
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    raw=b''.join(b'\0'+mono[y*stride:(y+1)*stride] for y in range(h))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,1,0,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')
