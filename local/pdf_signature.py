"""Verificación de un PDF firmado electrónicamente (PAdES / adbe.pkcs7.detached) en Python puro (1.5.271).

Comprueba, sin librerías externas:
1. que la firma cubre todo el archivo (ByteRange hasta el final, sin añadidos posteriores sin firmar);
2. que la huella del contenido firmado coincide con el atributo messageDigest de la firma;
3. la firma RSA (PKCS#1 v1.5) de los atributos firmados con la clave pública del certificado del firmante.
Extrae firmante, emisor, vigencia del certificado, fecha de firma y si lleva sello de tiempo. NO valida la cadena de confianza
hasta la autoridad raíz (UANATACA, Security Data…) ni la revocación: eso se indica siempre en el detalle. Nunca modifica el archivo."""
import hashlib
import re
import zlib
from datetime import datetime, timezone

OID_NAMES = {'2.5.4.3': 'CN', '2.5.4.5': 'serialNumber', '2.5.4.97': 'organizationIdentifier', '2.5.4.10': 'O', '2.5.4.6': 'C'}
DIGESTS = {'2.16.840.1.101.3.4.2.1': 'sha256', '2.16.840.1.101.3.4.2.2': 'sha384', '2.16.840.1.101.3.4.2.3': 'sha512', '1.3.14.3.2.26': 'sha1'}
MESSAGE_DIGEST, SIGNING_TIME, TIMESTAMP = '1.2.840.113549.1.9.4', '1.2.840.113549.1.9.5', '1.2.840.113549.1.9.16.2.14'
RSA = '1.2.840.113549.1.1.1'
NOT_CHAIN = 'La cadena de confianza y la revocación del certificado no se comprueban en Órdenes Pro: verifícalas en un validador oficial (FirmaEC, Adobe).'


class SignatureError(Exception):
    pass


# ---- DER mínimo --------------------------------------------------------------------------------------------------------------------

def _node(data, pos):
    """(etiqueta, inicio_del_contenido, fin, inicio_del_nodo)."""
    start, tag = pos, data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        count = length & 0x7f
        if not count or count > 4:
            raise SignatureError('Estructura de firma no válida.')
        length = int.from_bytes(data[pos:pos + count], 'big')
        pos += count
    if pos + length > len(data):
        raise SignatureError('Estructura de firma truncada.')
    return tag, pos, pos + length, start


def _children(data, node):
    out, pos = [], node[1]
    while pos < node[2]:
        child = _node(data, pos)
        out.append(child)
        pos = child[2]
    return out


def _oid(data, node):
    raw = data[node[1]:node[2]]
    parts = [raw[0] // 40, raw[0] % 40]
    value = 0
    for b in raw[1:]:
        value = (value << 7) | (b & 0x7f)
        if not b & 0x80:
            parts.append(value)
            value = 0
    return '.'.join(map(str, parts))


def _int(data, node):
    return int.from_bytes(data[node[1]:node[2]], 'big')


def _text(data, node):
    raw = data[node[1]:node[2]]
    return raw.decode('utf-16-be' if node[0] == 0x1e else 'utf-8', 'replace')


def _name(data, node):
    out = {}
    for rdn in _children(data, node):
        for atv in _children(data, rdn):
            oid, value = _children(data, atv)[:2]
            key = OID_NAMES.get(_oid(data, oid))
            if key:
                out[key] = _text(data, value)
    return out


def _time(data, node):
    raw = data[node[1]:node[2]].decode()
    fmt = '%y%m%d%H%M%SZ' if node[0] == 0x17 else '%Y%m%d%H%M%SZ'
    return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()


# ---- PDF ---------------------------------------------------------------------------------------------------------------------------

def _byte_range(pdf):
    found = list(re.finditer(rb'/ByteRange\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\]', pdf))
    if not found:
        raise SignatureError('El PDF no contiene una firma electrónica (no tiene /ByteRange).')
    a, b, c, d = map(int, found[-1].groups())
    if a != 0 or b <= 0 or c <= b or c + d > len(pdf):
        raise SignatureError('El rango firmado del PDF no es válido.')
    contents = pdf[b:c].strip()
    if not (contents.startswith(b'<') and contents.endswith(b'>')):
        raise SignatureError('El contenido de la firma no es válido.')
    hexs = contents[1:-1].strip()
    if len(hexs) % 2:
        raise SignatureError('El contenido de la firma no es válido.')
    return (a, b, c, d), bytes.fromhex(hexs.decode()), len(found)


def page_text(pdf):
    """Texto plano de los flujos del PDF (para comprobar a qué versión corresponde)."""
    out = []
    for m in re.finditer(rb'/Length (\d+)[^>]*>>\s*stream\r?\n', pdf):
        raw = pdf[m.end():m.end() + int(m[1])]
        try:
            out.append(zlib.decompress(raw))
        except zlib.error:
            out.append(raw)
    return b'\n'.join(out)


def verify(pdf):
    """Resultado de la verificación (nunca lanza por una firma inválida: la informa)."""
    pdf = bytes(pdf)
    if not pdf.startswith(b'%PDF-'):
        raise SignatureError('El archivo no es un PDF.')
    (a, b, c, d), der, count = _byte_range(pdf)
    sub = re.search(rb'/SubFilter\s*/([\w.]+)', pdf)
    when = re.search(rb'/M\s*\(D:(\d{14})([^)]*)\)', pdf)
    result = {'sub_filter': sub[1].decode() if sub else '', 'signatures': count, 'covers_all': c + d == len(pdf),
              'signer': '', 'signer_id': '', 'issuer': '', 'cert_from': '', 'cert_until': '', 'signed_at': '', 'timestamped': False,
              'verified': 'no_verificable', 'detail': ''}
    if when:
        result['signed_at'] = datetime.strptime(when[1].decode(), '%Y%m%d%H%M%S').isoformat() + _pdf_offset(when[2].decode())
    try:
        root = _node(der, 0)
        content = _children(der, root)
        signed = _children(der, _children(der, content[1])[0])
        certs, signer_info = [], None
        for node in signed[1:]:
            if node[0] == 0xa0:
                certs = _children(der, node)
            elif node[0] == 0x31:
                signer_info = _children(der, node)[0]
        info = _children(der, signer_info)
        sid, digest_alg = info[1], DIGESTS.get(_oid(der, _children(der, info[2])[0]))
        attrs_node = next(n for n in info if n[0] == 0xa0)
        signature = next(n for n in info if n[0] == 0x04)
        unsigned = [n for n in info if n[0] == 0xa1]
        attrs = {}
        for attr in _children(der, attrs_node):
            oid, values = _children(der, attr)
            attrs[_oid(der, oid)] = _children(der, values)[0]
        if unsigned:
            result['timestamped'] = any(_oid(der, _children(der, a)[0]) == TIMESTAMP for a in _children(der, unsigned[0]))
        if SIGNING_TIME in attrs and not result['signed_at']:
            result['signed_at'] = _time(der, attrs[SIGNING_TIME])
        # Certificado del firmante: el que coincide con el número de serie de la firma.
        serial = _int(der, _children(der, sid)[1]) if sid[0] == 0x30 else None
        cert = None
        for candidate in certs:
            tbs = _children(der, _children(der, candidate)[0])
            offset = 1 if tbs[0][0] == 0xa0 else 0
            if serial is None or _int(der, tbs[offset]) == serial:
                cert = tbs[offset:]
                break
        if cert is None:
            raise SignatureError('La firma no incluye el certificado del firmante.')
        subject, issuer = _name(der, cert[4]), _name(der, cert[2])
        validity = _children(der, cert[3])
        result.update(signer=subject.get('CN', ''), signer_id=subject.get('organizationIdentifier') or subject.get('serialNumber', ''),
                      issuer=issuer.get('CN', '') + (' · ' + issuer['O'] if issuer.get('O') else ''), cert_from=_time(der, validity[0]), cert_until=_time(der, validity[1]))
        if not digest_alg:
            result['detail'] = 'Algoritmo de huella no reconocido. ' + NOT_CHAIN
            return result
        content_digest = hashlib.new(digest_alg, pdf[a:a + b] + pdf[c:c + d]).digest()
        declared = der[attrs[MESSAGE_DIGEST][1]:attrs[MESSAGE_DIGEST][2]] if MESSAGE_DIGEST in attrs else b''
        if declared != content_digest:
            result.update(verified='invalida', detail='El contenido del PDF cambió después de firmarlo: su huella no coincide con la firma.')
            return result
        spki = _children(der, cert[5])
        if _oid(der, _children(der, spki[0])[0]) != RSA:
            result['detail'] = 'La huella del contenido coincide con la firma; el algoritmo de la clave no es RSA y no se verificó la firma matemática. ' + NOT_CHAIN
            return result
        bits = spki[1]
        key = _children(der, _node(der, bits[1] + 1))
        n, e = _int(der, key[0]), _int(der, key[1])
        signed_attrs = b'\x31' + der[attrs_node[3] + 1:attrs_node[2]]
        if not _rsa_ok(int.from_bytes(der[signature[1]:signature[2]], 'big'), n, e, hashlib.new(digest_alg, signed_attrs).digest()):
            result.update(verified='invalida', detail='La firma matemática no corresponde al certificado incluido.')
            return result
        if not result['covers_all']:
            result.update(verified='invalida', detail='El PDF tiene contenido añadido después de la firma.')
            return result
        result.update(verified='valida', detail='Integridad verificada: el contenido no cambió desde que se firmó y la firma corresponde al certificado de ' + result['signer'] + '. ' + NOT_CHAIN)
        return result
    except (SignatureError, IndexError, StopIteration, ValueError) as error:
        result['detail'] = (str(error) if isinstance(error, SignatureError) else 'No se pudo interpretar la firma.') + ' ' + NOT_CHAIN
        return result


def _rsa_ok(signature, n, e, digest):
    k = (n.bit_length() + 7) // 8
    em = pow(signature, e, n).to_bytes(k, 'big')
    if not em.startswith(b'\x00\x01'):
        return False
    sep = em.find(b'\x00', 2)
    if sep < 10 or set(em[2:sep]) != {0xff}:
        return False
    return em[sep + 1:].endswith(digest) and len(em) - sep - 1 - len(digest) in (15, 17, 19)  # DigestInfo de SHA-1/256/384/512


def _pdf_offset(raw):
    m = re.match(r"([+-])(\d{2})'?(\d{2})?", raw or '')
    return '%s%s:%s' % (m[1], m[2], m[3] or '00') if m else ''
