"""Registro central de versiones de Órdenes Pro.

`data/releases.json` es la única fuente del número de versión: de ahí salen la versión
instalada, el historial que muestra la página y `CHANGELOG.md`. Una versión solo se
registra con `publish --confirmar`; guardar cambios en Git no publica nada.
"""
import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'data' / 'releases.json'
CHANGELOG = ROOT.parent / 'CHANGELOG.md'
PRODUCT = 'Órdenes Pro | PC-DOCTOR S.A.'
ECUADOR = timezone(timedelta(hours=-5))
CATEGORIES = {
    'features': 'Nuevas funcionalidades',
    'improvements': 'Mejoras realizadas',
    'fixes': 'Errores corregidos',
    'security': 'Actualizaciones de seguridad',
    'performance': 'Optimización del rendimiento',
}
BUMPS = {
    'major': 'Cambios importantes que rompen compatibilidad',
    'minor': 'Nuevas funcionalidades compatibles',
    'patch': 'Corrección de errores',
}
TYPES = {'initial': 'Primera versión registrada', **BUMPS}
UPDATE_NOTE = 'La instalación desde esta página no está habilitada: requiere un mecanismo de despliegue seguro, configurado y autorizado.'


class RegistryError(ValueError):
    pass


def parse(version):
    match = re.fullmatch(r'(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})', str(version))
    if not match:
        raise RegistryError('Número de versión inválido: se espera MAYOR.MENOR.PARCHE.')
    return tuple(int(part) for part in match.groups())


def bump(version, kind):
    major, minor, patch = parse(version)
    if kind == 'major':
        return f'{major + 1}.0.0'
    if kind == 'minor':
        return f'{major}.{minor + 1}.0'
    if kind == 'patch':
        return f'{major}.{minor}.{patch + 1}'
    raise RegistryError('Tipo de actualización inválido: major, minor o patch.')


def clean_changes(changes):
    if not isinstance(changes, dict):
        raise RegistryError('El registro de cambios no tiene el formato esperado.')
    result = {}
    for key in CATEGORIES:
        items = changes.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() or len(item) > 400 for item in items) or len(items) > 100:
            raise RegistryError('Cambios inválidos en la categoría ' + key + '.')
        result[key] = [item.strip() for item in items]
    return result


def validate(data):
    """Devuelve el registro normalizado, con las versiones de la más reciente a la más antigua."""
    if not isinstance(data, dict) or not isinstance(data.get('releases'), list):
        raise RegistryError('El registro de versiones no tiene el formato esperado.')
    releases = []
    for item in data['releases']:
        if not isinstance(item, dict):
            raise RegistryError('Versión con formato inválido.')
        parse(item.get('version'))
        try:
            published = datetime.fromisoformat(str(item.get('date')))
        except ValueError:
            raise RegistryError('Fecha de publicación inválida en la versión ' + str(item.get('version')) + '.')
        if published.tzinfo is None or item.get('type') not in TYPES or item.get('status') != 'publicada':
            raise RegistryError('Datos de publicación inválidos en la versión ' + str(item.get('version')) + '.')
        release = {'version': item['version'], 'date': published.isoformat(timespec='seconds'), 'type': item['type'], 'status': 'publicada',
                   'summary': str(item.get('summary', '')).strip()[:400], 'changes': clean_changes(item.get('changes', {}))}
        # Quién la registró y quién la autorizó: solo desde que se anota (las versiones anteriores no lo tienen y no se inventa).
        for key in ('published_by', 'authorized_by'):
            if str(item.get(key) or '').strip():
                release[key] = str(item[key]).strip()[:80]
        releases.append(release)
    releases.sort(key=lambda release: parse(release['version']), reverse=True)
    if len({release['version'] for release in releases}) != len(releases):
        raise RegistryError('Hay versiones repetidas en el registro.')
    return {'product': PRODUCT, 'unreleased': clean_changes(data.get('unreleased', {})), 'releases': releases}


def load(path=None):
    try:
        return validate(json.loads(Path(path or REGISTRY).read_text(encoding='utf-8')))
    except (OSError, ValueError) as error:
        if isinstance(error, RegistryError):
            raise
        raise RegistryError('No se pudo leer el registro de versiones.')


def save(registry, path=None):
    Path(path or REGISTRY).write_text(json.dumps({'unreleased': registry['unreleased'], 'releases': registry['releases']}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


OFFICIAL_REGISTRY = 'https://raw.githubusercontent.com/Kike-os/Ordenes-Pro-PC-DOCTOR/main/local/data/releases.json'


def registry_url():
    """Registro publicado de versiones. Sin configurar se usa el oficial; vacío u «off» limita la comparación a esta instalación."""
    value = os.environ.get('UPDATE_REGISTRY_URL')
    if value is None:
        return OFFICIAL_REGISTRY
    value = value.strip()
    return '' if value.lower() in ('', 'off', 'no', 'false', '0') else value


def overview(registry=None):
    """Datos para el módulo «Sistema y actualizaciones»."""
    registry = registry or load()
    releases = registry['releases']
    return {'product': PRODUCT, 'installed': releases[0] if releases else None, 'releases': releases,
            'categories': CATEGORIES, 'types': TYPES, 'remote_configured': bool(registry_url())}


def fetch_published(url):
    if not url.startswith('https://'):
        raise RegistryError('El registro de versiones publicado debe consultarse por HTTPS.')
    try:
        with urlopen(Request(url, headers={'User-Agent': 'OrdenesPro-versiones'}), timeout=6) as response:
            raw = response.read(262145)
    except (OSError, URLError, ValueError):
        raise RegistryError('No se pudo consultar el registro de versiones publicado. Inténtalo más tarde.')
    if len(raw) > 262144:
        raise RegistryError('El registro de versiones publicado no es válido.')
    try:
        return validate(json.loads(raw.decode('utf-8')))
    except (ValueError, UnicodeDecodeError):
        raise RegistryError('El registro de versiones publicado no es válido.')


def check(registry=None, now=None):
    """Compara la versión instalada con el registro publicado. Nunca descarga ni instala nada."""
    registry = registry or load()
    installed = registry['releases'][0] if registry['releases'] else None
    url = registry_url()
    published = fetch_published(url) if url else registry
    latest = published['releases'][0] if published['releases'] else None
    current = parse(installed['version']) if installed else (0, 0, 0)
    pending = [release for release in published['releases'] if parse(release['version']) > current]
    available = bool(pending)
    if available:
        message = 'Hay una actualización disponible: v' + latest['version'] + '.'
    elif installed:
        message = 'Órdenes Pro está actualizado. Estás utilizando la última versión disponible.'
    else:
        message = 'Todavía no hay versiones publicadas en el registro.'
    return {'installed': installed, 'latest': latest, 'update_available': available, 'pending': pending, 'source': 'remote' if url else 'local',
            'checked_at': (now or datetime.now(ECUADOR)).isoformat(timespec='seconds'), 'message': message,
            'can_update': False, 'update_note': UPDATE_NOTE if available else ''}


def changelog_text(registry):
    lines = ['# Registro de cambios — ' + PRODUCT, '',
             'Generado desde `local/data/releases.json` con `python local/versioning.py changelog`. No editar a mano.', '',
             'Numeración semántica: MAYOR (cambios que rompen compatibilidad), MENOR (nuevas funcionalidades compatibles), PARCHE (corrección de errores).', '']
    if any(registry['unreleased'].values()):
        lines += ['## Sin publicar', '']
        for key, title in CATEGORIES.items():
            if registry['unreleased'][key]:
                lines += ['### ' + title, ''] + ['- ' + item for item in registry['unreleased'][key]] + ['']
    for release in registry['releases']:
        published = datetime.fromisoformat(release['date'])
        lines += ['## v' + release['version'] + ' — ' + published.strftime('%Y-%m-%d %H:%M') + ' (UTC' + published.strftime('%z')[:3] + ':' + published.strftime('%z')[3:] + ')', '']
        if release['summary']:
            lines += [release['summary'], '']
        for key, title in CATEGORIES.items():
            if release['changes'][key]:
                lines += ['### ' + title, ''] + ['- ' + item for item in release['changes'][key]] + ['']
    return '\n'.join(lines).rstrip('\n') + '\n'


def publish(registry, kind, summary='', now=None, published_by='', authorized_by=''):
    """Registra una versión nueva con los cambios pendientes. No toca Git ni despliega."""
    if not any(registry['unreleased'].values()):
        raise RegistryError('No hay cambios pendientes que publicar. Regístralos con «add».')
    if kind not in BUMPS:
        raise RegistryError('Tipo de actualización inválido: major, minor o patch.')
    version = bump(registry['releases'][0]['version'], kind) if registry['releases'] else '1.0.0'
    release = {'version': version, 'date': (now or datetime.now(ECUADOR)).isoformat(timespec='seconds'), 'type': kind if registry['releases'] else 'initial', 'status': 'publicada',
               'summary': summary.strip()[:400], 'changes': registry['unreleased'], 'published_by': published_by, 'authorized_by': authorized_by}
    return validate({'unreleased': {}, 'releases': [release] + registry['releases']})


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT.parent), *args], capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Versiones de ' + PRODUCT)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='Muestra la versión instalada y los cambios pendientes.')
    add = commands.add_parser('add', help='Anota un cambio pendiente de publicar.')
    add.add_argument('category', choices=list(CATEGORIES))
    add.add_argument('text')
    release = commands.add_parser('publish', help='Registra una versión nueva con los cambios pendientes.')
    release.add_argument('kind', choices=list(BUMPS))
    release.add_argument('--resumen', default='')
    release.add_argument('--autorizado-por', default='', help='Quién autorizó la publicación (queda en el registro).')
    release.add_argument('--confirmar', action='store_true', help='Autoriza el registro; sin esta opción solo se muestra la vista previa.')
    commands.add_parser('changelog', help='Regenera CHANGELOG.md desde el registro.')
    commands.add_parser('tag', help='Crea la etiqueta de Git de la versión instalada (no la sube).')
    args = parser.parse_args(argv)
    try:
        registry = load()
        if args.command == 'status':
            installed = registry['releases'][0] if registry['releases'] else None
            print('Versión instalada: ' + ('v' + installed['version'] + ' · ' + installed['date'] if installed else 'sin versiones registradas'))
            pending = [(CATEGORIES[key], item) for key in CATEGORIES for item in registry['unreleased'][key]]
            print('Cambios pendientes de publicar: ' + (str(len(pending)) if pending else 'ninguno'))
            for title, item in pending:
                print('  - [' + title + '] ' + item)
        elif args.command == 'add':
            registry['unreleased'][args.category].append(args.text.strip())
            save(validate(registry))
            CHANGELOG.write_text(changelog_text(load()), encoding='utf-8')
            print('Cambio anotado como pendiente. Aún no forma parte de ninguna versión.')
        elif args.command == 'publish':
            updated = publish(registry, args.kind, args.resumen, published_by=git('config', 'user.name').stdout.strip(), authorized_by=args.autorizado_por)
            print('Versión a registrar: v' + updated['releases'][0]['version'] + ' (' + BUMPS[args.kind] + ')')
            if not args.confirmar:
                print('Vista previa: no se registró nada. Repite el comando con --confirmar tras las pruebas y la autorización.')
                return 0
            save(updated)
            CHANGELOG.write_text(changelog_text(updated), encoding='utf-8')
            print('Registrada en local/data/releases.json y CHANGELOG.md. Falta confirmar en Git y etiquetar: python local/versioning.py tag')
        elif args.command == 'changelog':
            CHANGELOG.write_text(changelog_text(registry), encoding='utf-8')
            print('CHANGELOG.md regenerado.')
        elif args.command == 'tag':
            if not registry['releases']:
                raise RegistryError('No hay versiones registradas.')
            name = 'v' + registry['releases'][0]['version']
            if git('status', '--porcelain', '--', 'local/data/releases.json', 'CHANGELOG.md').stdout.strip():
                raise RegistryError('Confirma primero en Git el registro de versiones y CHANGELOG.md.')
            if git('rev-parse', '-q', '--verify', 'refs/tags/' + name).returncode == 0:
                raise RegistryError('La etiqueta ' + name + ' ya existe.')
            result = git('tag', '-a', name, '-m', PRODUCT + ' ' + name)
            if result.returncode:
                raise RegistryError('Git no pudo crear la etiqueta: ' + result.stderr.strip())
            print('Etiqueta ' + name + ' creada en este equipo. No se subió ni se desplegó nada.')
    except RegistryError as error:
        raise SystemExit(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
