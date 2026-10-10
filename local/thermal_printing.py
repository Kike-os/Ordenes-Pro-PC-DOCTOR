#!/usr/bin/env python3
"""Ticket PDF -> ráster exacto 203 dpi -> controlador Epson -> cola explícita.
Por defecto solo comprueba/prepara opciones. --render-only no imprime.
"""
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
from urllib.parse import quote,urlsplit
from urllib.request import urlopen


def inspect_pdf(path):
    info=subprocess.run(['pdfinfo',str(path)],capture_output=True,text=True,check=True,env={**os.environ,'LC_ALL':'C'}).stdout
    pages=re.search(r'^Pages:\s+(\d+)',info,re.M);size=re.search(r'^Page size:\s+([\d.]+) x ([\d.]+) pts',info,re.M)
    if not pages or pages[1]!='1' or not size:raise ValueError('El ticket debe contener exactamente una página PDF.')
    width,height=map(float,size.groups())
    if abs(width*25.4/72-72)>.2 or not 25.4<=height*25.4/72<=2000:raise ValueError('El PDF debe corresponder al área útil de 72 mm y al rollo soportado.')
    return math.ceil(height*203/72)


def queue_options(printer):
    options=subprocess.run(['lpoptions','-p',printer],capture_output=True,text=True,check=True,timeout=5).stdout
    if 'TM Thermal' not in options or '203dpi' not in options:raise ValueError('Selecciona la cola Epson térmica instalada de 203 dpi.')
    return options


def render(pdf,printer,output,height):
    for program in ('gs','/usr/lib/cups/filter/rastertotmtr'):
        if not shutil.which(program):raise ValueError('Falta la herramienta de impresión: '+program)
    with tempfile.TemporaryDirectory(prefix='pcdoctor-thermal-') as folder:
        ppd=Path(folder)/'epson.ppd';raster=Path(folder)/'ticket.raster'
        # PPD de la cola real: no direcciones IP ni controladores ficticios.
        with urlopen('http://localhost:631/printers/'+quote(printer,safe='')+'.ppd',timeout=5) as response:ppd.write_bytes(response.read())
        content=ppd.read_text(errors='replace')
        if 'rastertotmtr' not in content or '203x203dpi' not in content:raise ValueError('El PPD no corresponde al controlador verificado.')
        # Evita el retorno a A4 del filtro pdftopdf al usar papel Custom en este equipo.
        subprocess.run(['gs','-q','-dSAFER','-dBATCH','-dNOPAUSE','-dFIXEDMEDIA','-sDEVICE=cups','-r203',f'-g576x{height}','-dcupsBitsPerColor=1','-dcupsColorSpace=3','-sOutputFile='+str(raster),str(pdf)],check=True,stdout=subprocess.DEVNULL,timeout=20)
        with Path(output).open('wb') as target:
            subprocess.run(['/usr/lib/cups/filter/rastertotmtr','1',os.getenv('USER','operador'),'PC-DOCTOR ticket','1','PageSize=RP80x2000 TmxPaperCut=CutPerJob TmxPaperReduction=Bottom',str(raster)],env={**os.environ,'PPD':str(ppd)},stdout=target,check=True,timeout=20)


def send(pdf,printer,height):
    options=queue_options(printer)
    match=re.search(r'device-uri=(socket://[^\s]+)',options)
    if not match:raise ValueError('Selecciona la cola Epson de red configurada.')
    target=urlsplit(match[1])
    with socket.create_connection((target.hostname,target.port or 9100),3):pass
    with tempfile.TemporaryDirectory(prefix='pcdoctor-print-') as folder:
        raw=Path(folder)/'ticket.prn';render(pdf,printer,raw,height)
        result=subprocess.run(['lp','-d',printer,'-n','1','-t','PC-DOCTOR · Comprobante térmico','-o','raw',str(raw)],capture_output=True,text=True,check=True,timeout=10)
        return result.stdout.strip()


def configuration():
    import json
    path=Path(__file__).resolve().parent/'data/thermal-printer.json'
    return json.loads(path.read_text()) if path.exists() else {}


def capability():
    config=configuration();printer=config.get('queue','')
    if not printer or not all(shutil.which(x) for x in ['lp','lpoptions','gs','pdfinfo','/usr/lib/cups/filter/rastertotmtr']):return {'available':False}
    try:queue_options(printer)
    except (OSError,ValueError,subprocess.CalledProcessError):return {'available':False}
    return {'available':True,'queue':printer,'model':config.get('model','Epson TM Thermal'),'dpi':203,'printable_mm':72,'roll_mm':80}
