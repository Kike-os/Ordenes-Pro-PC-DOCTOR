"""Buscador global del encabezado: órdenes por número, cliente, marca, modelo y serie.

Ignora mayúsculas y tildes, acepta varias palabras en cualquier orden y tolera errores de escritura
(una letra en palabras cortas, dos en las largas). Solo lee; los permisos los aplica la ruta."""
import re
import unicodedata

SCAN = 3000
WORD = re.compile(r'[^\W_]+')


def fold(text):
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text or '')) if not unicodedata.combining(ch)).casefold()


def distance(a, b, limit):
    """Distancia de edición (con transposición de letras vecinas); devuelve limit+1 en cuanto la supera."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    before, row = None, list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            cost = min(row[j] + 1, current[j - 1] + 1, row[j - 1] + (x != y))
            if before and i > 1 and j > 1 and x == b[j - 2] and a[i - 2] == y:
                cost = min(cost, before[j - 2] + 1)
            current.append(cost)
        if min(current) > limit:
            return limit + 1
        before, row = row, current
    return row[-1]


def tolerance(token):
    # Los números (teléfonos, cédulas, fechas del código) no se aproximan: un dígito distinto es otro dato.
    letters = sum(ch.isalpha() for ch in token)
    if len(token) < 4 or letters <= sum(ch.isdigit() for ch in token):
        return 0
    return 1 if len(token) < 8 else 2


def near(token, words):
    """Palabra del registro que se parece al término, completa o por su comienzo (para sugerir mientras se escribe)."""
    limit = tolerance(token)
    if not limit:
        return None
    best = None
    for raw, word in words:
        for candidate in {word, word[:len(token)], word[:len(token) + 1]}:
            if len(candidate) < 3 or candidate[0] != token[0]:
                continue
            found = distance(token, candidate, limit)
            if found <= limit and (best is None or found < best[0]):
                best = (found, raw)
    return best[1] if best else None


def find(c, term, limit=8):
    tokens = [token for token in fold(term).split() if token][:6]
    if not tokens:
        return {'rows': [], 'total': 0, 'fuzzy': False, 'suggestion': ''}
    exact, fuzzy = [], []
    for row in c.execute(
            "SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,c.name client,c.identification,c.phone,d.brand,d.model,d.serial,o.status status_code,s.label status "
            "FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status ORDER BY o.id DESC LIMIT ?", (SCAN,)):
        item = dict(row)
        text = ' '.join(str(item[key] or '') for key in ('code', 'client', 'identification', 'phone', 'brand', 'model', 'serial'))
        hay, words, hits = fold(text), None, []
        for token in tokens:
            if token in hay:
                continue
            if words is None:
                words = [(raw, fold(raw)) for raw in WORD.findall(text)]
            match = near(token, words)
            if not match:
                break
            hits.append(match)
        else:
            item.pop('identification'); item.pop('phone')
            item['hits'] = hits
            if hits:
                fuzzy.append(item)
            else:
                exact.append(item)
    code = fold(term.strip())
    exact.sort(key=lambda item: (fold(item['code']) != code, -item['id']))
    if exact:
        # Con coincidencias exactas no se mezclan parecidos: evita resultados inesperados.
        return {'rows': exact[:limit], 'total': len(exact), 'fuzzy': False, 'suggestion': ''}
    fuzzy.sort(key=lambda item: (len(item['hits']), -item['id']))
    suggestion = ''
    if fuzzy:
        # Sugerencia: el mismo texto con cada palabra dudosa cambiada por la más frecuente entre los resultados.
        raw_tokens, counts = term.split()[:6], {}
        for item in fuzzy[:40]:
            for token in tokens:
                if token in fold(' '.join(str(item[key] or '') for key in ('code', 'client', 'brand', 'model', 'serial'))):
                    continue
                words = [(raw, fold(raw)) for raw in WORD.findall(' '.join(str(item[key] or '') for key in ('code', 'client', 'brand', 'model', 'serial')))]
                match = near(token, words)
                if match:
                    counts.setdefault(token, {}).setdefault(match, 0)
                    counts[token][match] += 1
        suggestion = ' '.join(max(counts[token], key=counts[token].get) if token in counts else raw for raw, token in zip(raw_tokens, tokens))
    return {'rows': fuzzy[:limit], 'total': len(fuzzy), 'fuzzy': bool(fuzzy), 'suggestion': suggestion}
