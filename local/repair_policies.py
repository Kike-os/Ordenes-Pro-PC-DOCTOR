"""Políticas de Reparaciones de PC-DOCTOR S.A.: texto oficial, literal, que acompaña al comprobante de recepción.

El contenido vive en data/repair-policies.json y no se edita desde el código. Se identifica por versión y SHA-256 para
dejar constancia de qué texto acompañó a cada documento enviado. Incluirlo en el comprobante no registra aceptación.
"""
import hashlib,json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load():
    data=json.loads((Path(__file__).resolve().parent/'data/repair-policies.json').read_text(encoding='utf-8'))
    data['sha256']=hashlib.sha256(data['text'].encode('utf-8')).hexdigest()
    data['paragraphs']=[block.strip() for block in data['text'].split('\n\n') if block.strip()]
    return data
