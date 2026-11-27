"""Local retrieval of approved lab excerpts using controlled concepts."""
import re
import unicodedata

CONCEPTS = {
    'Alimentación y carga': ('alimentacion', 'circuito de carga', 'power delivery', 'usb c pd', 'carga de bateria'),
    'Secuencia de encendido': ('secuencia de encendido', 'power sequence', 'power good', 'senal de habilitacion'),
    'Autodiagnóstico de arranque': ('post', 'autodiagnostico de arranque', 'codigo de diagnostico', 'beep code'),
    'Pantalla e iluminación': ('sin imagen', 'pantalla negra', 'backlight', 'retroiluminacion', 'sin video'),
    'Firmware de arranque': ('bios', 'uefi', 'firmware de arranque', 'spi nor', 'firmware del sistema'),
    'Controlador integrado': ('embedded controller', 'controlador integrado', 'firmware ec', 'kbc'),
    'Esquemas de placa': ('esquematico', 'esquematicos', 'diagrama electrico', 'boardview', 'board view'),
    'Refrigeración': ('control termico', 'sobrecalentamiento', 'refrigeracion', 'disipacion', 'thermal management'),
    'Almacenamiento': ('almacenamiento', 'disco duro', 'ssd', 'hdd', 'unidad de estado solido'),
    'Sistema de tinta': ('sistema de tinta', 'cabezal de impresion', 'cabezal', 'alimentacion de tinta'),
}
COMMON = {'el','la','las','los','un','una','de','del','en','que','y','para','por','con','es','como','cual','puede','mi'}


def words(text):
    normalized = unicodedata.normalize('NFKD', text.casefold())
    return re.findall(r'[^\W_]+', ''.join(ch for ch in normalized if not unicodedata.combining(ch)))


def _features(text):
    tokens = words(text)
    phrase = ' ' + ' '.join(tokens) + ' '
    concepts = {name for name, variants in CONCEPTS.items() if any(' '+variant+' ' in phrase for variant in variants)}
    return set(tokens) - COMMON, concepts


def _score(query, text):
    terms, concepts = _features(text)
    word_matches = terms & query[0]
    concept_matches = concepts & query[1]
    return len(word_matches) + 2 * len(concept_matches), concept_matches


def rank(rows, query, limit=15):
    """Return matching excerpts and citation metadata, without generating technical claims."""
    query = _features(query[:180])
    results = []
    for row in rows:
        item = dict(row)
        title_score, title_concepts = _score(query, item['title'])
        text_score, text_concepts = _score(query, item['source'] + ' ' + item['content'])
        if any(query) and not (title_score or text_score):
            continue
        item['matched_concepts'] = sorted(title_concepts | text_concepts)
        results.append((3 * title_score + text_score, item))
    results.sort(key=lambda entry: (-entry[0], -entry[1]['id']))
    selected = [item for _, item in results[:limit]]
    for item in selected:
        # Cite the most relevant original paragraph without generating a diagnosis.
        lines = re.split(r'\n\s*\n|\n', item['content'])
        item['excerpt'] = max(lines, key=lambda line: _score(query, line)[0]).strip()[:520]
    return selected
