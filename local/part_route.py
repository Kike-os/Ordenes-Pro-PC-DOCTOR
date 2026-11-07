"""Dibujo del mapa de ruta de un repuesto (envío nacional o internacional) a partir de order_part_requests.route_map.

Un solo dibujo para el panel interno y el seguimiento público. SVG escalable (1000 × 158) para pantallas amplias y una lista vertical compacta
para teléfonos (la elige el CSS con una consulta de contenedor). El vehículo recorre una sola vez, al cargar, el trecho desde el paso anterior
hasta el paso real registrado (animateMotion sobre el mismo trazo); con «reducir movimiento» se muestra quieto en su punto real. Los puntos
luminosos solo corren sobre el tramo activo y el CSS los detiene fuera de pantalla. Todo el texto se escapa."""
import html

ICONS = {
    'globe': 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M2 12h20 M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z',
    'customs': 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z M9 12l2 2 4-4',
    'pin': 'M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    'shop': 'M3 9l1.5-5h15L21 9 M3 9v11h18V9 M3 9h18 M9 20v-6h6v6',
    'box': 'M21 8l-9-5-9 5 9 5 9-5z M3 8v8l9 5 9-5V8 M12 13v8',
    'wrench': 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8z',
}
# ---- Vehículos 3D corporativos (1.5.250) ------------------------------------------------------------------------------------------------
# Dibujo vectorial con degradados, brillos y sombras (estilo 3D semirrealista), en colores de PC-DOCTOR (blanco y plata con azul marino y
# rojo). El logotipo es el archivo ORIGINAL (static/logo-original.png) insertado tal cual: un SVG anidado solo deja fuera su margen
# transparente y conserva la proporción real del dibujo (2102 × 1596), sin redibujar, recolorear ni deformar. Los id de los degradados llevan
# el prefijo de cada dibujo para que nunca choquen entre tarjetas. Las animaciones (ruedas, suspensión, tren de aterrizaje) son SMIL y solo
# acompañan el recorrido real; si el navegador no las admite, el vehículo se ve quieto en su punto real.
LOGO = '/static/logo-original.png'
SPLINE = '.55 0 .25 1'   # arranque suave, aceleración y frenado progresivo
DUR = 2.4                # segundos del recorrido (una sola vez, al cargar)
WHEEL_R = 6.6


def logo(x, y, width):
    """Logo original sin su margen transparente (recorte 311, 127 · 2102 × 1596 del archivo de 2826 × 2049), con su proporción real."""
    return ('<svg class="lgx-logo" x="%s" y="%s" width="%s" height="%s" viewBox="311 127 2102 1596" preserveAspectRatio="xMidYMid meet">'
            '<image href="%s" width="2826" height="2049"/></svg>' % (x, y, width, round(width * 1596 / 2102, 2), LOGO))


def vehicle_defs(u):
    """Degradados de la carrocería, vidrios, aros, alas y turbinas (únicos por dibujo)."""
    lin = lambda name, stops, x2=0, y2=1: '<linearGradient id="%s-%s" x1="0" y1="0" x2="%s" y2="%s">%s</linearGradient>' % (
        u, name, x2, y2, ''.join('<stop offset="%s" stop-color="%s"/>' % st for st in stops))
    return (lin('body', (('0', '#ffffff'), ('.5', '#eef2f7'), ('1', '#aebccd'))) + lin('glass', (('0', '#0b1f3d'), ('.55', '#2b5d93'), ('1', '#a9d3f5')), 1, 1)
            + lin('wing', (('0', '#f8fafc'), ('1', '#9aa9bd'))) + lin('far', (('0', '#cbd5e1'), ('1', '#8090a6'))) + lin('fin', (('0', '#24539a'), ('1', '#0b2a5b')), 1, 1)
            + lin('eng', (('0', '#f1f5f9'), ('.6', '#a3b1c3'), ('1', '#5b6b82')))
            + '<radialGradient id="%s-rim" cx=".38" cy=".35" r=".75"><stop offset="0" stop-color="#ffffff"/><stop offset=".6" stop-color="#cbd5e1"/><stop offset="1" stop-color="#7c8aa0"/></radialGradient>' % u)


def _spin(degrees):
    """Giro de una rueda sincronizado con el avance (mismo tiempo y misma curva que el recorrido)."""
    return ('<animateTransform attributeName="transform" type="rotate" values="0;%s" keyTimes="0;1" calcMode="spline" keySplines="%s" dur="%ss" begin="0s" fill="freeze"/>'
            % (round(degrees), SPLINE, DUR))


def _wheel(u, cx, spin):
    spokes = ''.join('M0 0L%s %s' % (round(3.5 * __import__('math').sin(a * 1.2566), 2), round(-3.5 * __import__('math').cos(a * 1.2566), 2)) for a in range(5))
    return ('<g transform="translate(%s 6)"><circle r="%s" fill="#0b0f19"/><circle r="5.3" fill="#1f2937" stroke="#334155" stroke-width=".7"/>'
            '<g class="lgx-rim"><circle r="3.9" fill="url(#%s-rim)"/><path d="%s" stroke="#64748b" stroke-width=".75" stroke-linecap="round"/><circle r="1.2" fill="#1e293b"/>%s</g></g>'
            % (cx, WHEEL_R, u, spokes, _spin(spin) if spin else ''))


def van(u, distance=0.0, animate=False):
    """Furgoneta de reparto PC-DOCTOR (mira a la derecha; centro en 0,0; ruedas en y = 6). Con `animate`, ruedas que giran según la
    distancia recorrida y suspensión durante el trayecto."""
    spin = distance / (2 * 3.14159 * WHEEL_R) * 360 if animate and distance else 0
    bounce = ('<animateTransform attributeName="transform" type="translate" values="0 0;0 -.8;0 .35;0 0" dur=".48s" repeatDur="%ss" begin="0s" fill="remove"/>' % DUR
              if animate and distance else '')
    body = ('<path d="M-33 5L-33 -16Q-33 -20 -29 -20L10 -20Q14 -20 17 -17L24 -10Q26 -8.5 29 -8Q33.4 -7.2 33.6 -3L33.6 4Q33.6 6 31.5 6L-31 6Q-33 6 -33 5Z" fill="url(#%s-body)" stroke="#6b7a90" stroke-width=".5"/>'
            '<path d="M-33 -3.2H33.3V-2.3H-33Z" fill="#1d4ed8"/><path d="M-33 -1.6H33.5V.2H-33Z" fill="#d71f26"/>'
            '<path d="M-33 1H33.6V4Q33.6 6 31.5 6H-31Q-33 6 -33 5Z" fill="#0b2a5b"/>'
            '<path d="M-29 -19.2H10Q13 -19.2 15 -17.6H-30.4Z" fill="#fff" opacity=".85"/><path d="M-21 -18H-14L-25 -4.6H-32Z" fill="#fff" opacity=".22"/>'
            '<path d="M11 -17.5H16.5L23 -10.3H11Z" fill="url(#%s-glass)"/><path d="M13 -17.3H15L12.6 -10.5H11.3Z" fill="#fff" opacity=".35"/>'
            '<path d="M17.2 -16.4L23 -10.3H24.4L18.2 -16.9Z" fill="#9aa9bd" opacity=".7"/>'
            '<path d="M8 -17V1M-6 -18.6V1" stroke="#94a3b8" stroke-width=".6"/><rect x="4.4" y="-7.6" width="2.6" height=".9" rx=".45" fill="#475569"/>'
            '<rect x="-9.6" y="-7.6" width="2.6" height=".9" rx=".45" fill="#475569"/><path d="M21.4 -9.6L24.4 -10.4L24.8 -8.2L21.9 -7.9Z" fill="#0b2a5b"/>'
            '<path d="M30.2 -6.6Q32.7 -6.4 33.4 -4.2H30.4Z" fill="#fff6c2" stroke="#c7a94a" stroke-width=".3"/>'
            '<rect x="-33.7" y="-8.2" width="1.7" height="4.2" rx=".5" fill="#ef4444"/>'
            '<rect x="30" y="2.2" width="4.2" height="3.4" rx="1" fill="#1f2937"/><rect x="-34.2" y="2.2" width="3.2" height="3.4" rx="1" fill="#1f2937"/>'
            '<path d="M-27.4 6A8.4 8.4 0 0 1 -10.6 6ZM10.6 6A8.4 8.4 0 0 1 27.4 6Z" fill="#0f172a" opacity=".55"/>'
            '<circle class="lgx-hazard" cx="32.2" cy="-5.3" r="1.5" fill="#fbbf24"/><circle class="lgx-hazard" cx="-32.8" cy="-6" r="1.4" fill="#fbbf24"/>'
            % (u, u)) + logo(-27.6, -17.8, 18.6)
    return ('<g class="lgx-van lgx-truck"><ellipse cx="0" cy="13.2" rx="31" ry="2.3" fill="#020617" opacity=".32"/><g class="lgx-body">%s%s</g>%s%s</g>'
            % (body, bounce, _wheel(u, -19, spin), _wheel(u, 19, spin)))


def plane(u, gear='up', animate=False):
    """Avión de carga PC-DOCTOR en vista de tres cuartos (mira a la derecha; centro en 0,0). `gear`: down (en tierra), up (en vuelo),
    retract (se recoge al despegar) o deploy (se despliega al aproximarse); los dos últimos solo con animación."""
    if gear in ('retract', 'deploy') and not animate:
        gear = 'up' if gear == 'retract' else 'down'
    move = {'retract': 'values="1 1;1 1;1 0;1 0" keyTimes="0;.3;.55;1"', 'deploy': 'values="1 0;1 0;1 1;1 1" keyTimes="0;.45;.75;1"'}.get(gear)  # keyTimes debe terminar en 1
    legs = ('<g transform="translate(0 7.5)"><g class="lgx-gear"%s><path d="M33 0V5.6M-4 0V6.6M2 0V6.6" stroke="#334155" stroke-width="1.2"/>'
            '<circle cx="33" cy="7.2" r="2" fill="#0b0f19"/><circle cx="-4" cy="8.6" r="2.4" fill="#0b0f19"/><circle cx="2" cy="8.6" r="2.4" fill="#0b0f19"/>%s</g></g>'
            % (' transform="scale(1 0)"' if gear == 'deploy' else '', '<animateTransform attributeName="transform" type="scale" %s dur="%ss" begin="0s" fill="freeze"/>' % (move, DUR) if move else '')
            if gear != 'up' else '')
    windows = ''.join('<rect x="%s" y="-5.8" width="1.9" height="2.3" rx=".8" fill="#1e3a5f"/>' % x for x in range(0, 32, 4))
    art = ('<path d="M6 -3L-6 -16L-13 -16L-5 -3Z" fill="url(#%(u)s-far)"/><path d="M-31 -5L-38 -11.5L-42.5 -11.5L-37 -5Z" fill="#8a99ad"/>'
           '<path d="M44 -1Q44 -8.6 34 -9.5L-26 -9.5L-40 -13Q-45 -13.6 -44.4 -9.6L-40 2Q-37.5 7.4 -30 7.5L31 7.5Q44 6.8 44 -1Z" fill="url(#%(u)s-body)" stroke="#64748b" stroke-width=".45"/>'
           '<path d="M-37.4 3.4H38.4Q36.4 7.1 31 7.5H-30Q-35.4 7.3 -37.4 3.4Z" fill="#0b2a5b"/><path d="M-38.6 1.1H41.8L41.2 2.4H-38Z" fill="#d71f26"/>'
           '<path d="M34 -8.8H-26V-7.3H36.2Q35.2 -8.4 34 -8.8Z" fill="#fff" opacity=".85"/>'
           '<path d="M-26 -9.3L-36 -27Q-37.5 -29 -40.5 -29H-44L-41 -12.6Z" fill="url(#%(u)s-fin)"/><path d="M-36.4 -24.6H-42.6L-43.2 -21.8H-34.9Z" fill="#d71f26"/>'
           '<path d="M36 -6.6Q40.4 -6.3 41.8 -3.4H36.4Z" fill="url(#%(u)s-glass)"/><path d="M37 -6.2L38.2 -6.1L37.4 -3.7H36.6Z" fill="#fff" opacity=".4"/>%(windows)s'
           '<rect x="-9.2" y="-8.6" width="6.4" height="11" rx="1" fill="none" stroke="#94a3b8" stroke-width=".5"/>%(logo)s'
           '<g transform="translate(4 10.6)"><path d="M10 -3.4Q12 -3.4 12 0Q12 3.4 10 3.4H-6Q-9 3.4 -9 0Q-9 -3.4 -6 -3.4Z" fill="url(#%(u)s-eng)" stroke="#475569" stroke-width=".4"/>'
           '<ellipse cx="11.3" rx="1.3" ry="3.1" fill="#0f172a"/><rect x="-3" y="-3.4" width="2.2" height="6.8" fill="#d71f26" opacity=".9"/><ellipse cx="-8.6" rx=".9" ry="2.4" fill="#334155"/></g>'
           '<path d="M10 2.5L-6 21Q-7 22.5 -9 22.5L-17 22.5L-6 3.4Z" fill="url(#%(u)s-wing)" stroke="#64748b" stroke-width=".4"/><path d="M10 2.5L-6 21" stroke="#0b2a5b" stroke-width="1.2"/>'
           '<path d="M-9 22.5H-17L-19 25.6H-15Z" fill="#d71f26"/><path d="M-32 1L-44 9H-48.5L-40 1Z" fill="url(#%(u)s-wing)" stroke="#64748b" stroke-width=".35"/>'
           % {'u': u, 'windows': windows, 'logo': logo(-25.4, -9.1, 13.4)})
    return '<g class="lgx-plane-3d" transform="scale(.9)">%s%s</g>' % (art, legs)


CHECK = '<g class="lgx-ok"><circle r="9"/><path d="m-4 .2 2.6 2.6L4.2-3"/></g>'
WORD = {'done': 'completado', 'current': 'en curso', 'pending': 'pendiente', 'active': 'en curso'}
SEGMENT_TEXT = {'aire': 'Vuelo internacional', 'tierra': 'Traslado terrestre'}


def _icon(name, size=26):
    scale = size / 24
    return '<path class="lgx-icon" transform="translate(%s %s) scale(%s)" d="%s"/>' % (-size / 2, -size / 2, round(scale, 3), ICONS[name])


def _date(value):
    from datetime import datetime
    from reception import ECUADOR_TZ
    try:
        return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return ''


def render(route, uid, title=''):
    """HTML del mapa. `uid` hace únicos los id del SVG cuando hay varios repuestos en la página."""
    if not route:
        return ''
    e = html.escape
    uid = ''.join(ch for ch in str(uid) if ch.isalnum()) or 'x'
    vehicle = route['vehicle']
    defs = ''.join('<path id="lgx-%s-%s" d="%s"/>' % (uid, s['code'], s['path']) for s in route['segments'])
    tracks = ''
    for s in route['segments']:
        moving = vehicle and vehicle['segment'] == s['code'] and vehicle['motion'] == 'moving'
        tracks += ('<g class="lgx-seg" data-kind="%s" data-state="%s"><use class="lgx-base" href="#lgx-%s-%s"/><use class="lgx-fill" href="#lgx-%s-%s"/>%s</g>'
                   % (e(s['kind']), e(s['state']), uid, s['code'], uid, s['code'], '<use class="lgx-flow" href="#lgx-%s-%s"/>' % (uid, s['code']) if moving else ''))
    nodes = ''
    for n in route['nodes']:
        badge = '<g transform="translate(15 -15)">%s</g>' % CHECK if n['state'] == 'done' else ''
        nodes += ('<g class="lgx-node" data-state="%s" data-code="%s"%s transform="translate(%s 80)"><circle class="lgx-halo" r="27"/><circle class="lgx-dot" r="20"/>%s%s'
                  '<text class="lgx-label" y="40">%s</text><text class="lgx-sub" y="58">%s</text><text class="lgx-sub lgx-when" y="74">%s</text></g>'
                  % (e(n['state']), e(n['code']), ' data-customs="1"' if n['customs'] else '', n['x'], _icon(n['icon'], 23), badge, e(n['label']), e(n['sub']), e(_date(n['at']))))
    craft = clouds = ''
    if vehicle:
        kind, motion = vehicle['kind'], vehicle['motion']
        on_ground = motion in ('parked', 'landed')
        badge = ('<g transform="translate(25 -17)">%s</g>' % CHECK) if motion == 'arrived' else ''
        warn = ('<g class="lgx-warn" transform="translate(0 -31)"><circle r="6.4" fill="#f59e0b" stroke="#78350f" stroke-width=".8"/>'
                '<path d="M0 -3.4V.8M0 3V3.2" stroke="#1f1300" stroke-width="1.8" stroke-linecap="round"/></g>') if motion == 'stopped' else ''
        if kind == 'plane':
            static_art = plane(uid, 'down' if on_ground else 'up')
        else:
            static_art = van(uid)
        body = '<g class="lgx-float">%s</g>%s%s' % (static_art, badge, warn)
        static = '<g class="lgx-veh-static" transform="translate(%s %s) rotate(%s)">%s</g>' % (vehicle['x'], vehicle['y'], vehicle['angle'], body)
        animated = ''
        if vehicle['animate']:
            if kind == 'plane':
                moving_art = plane(uid, 'deploy' if motion == 'landed' else 'retract', animate=True)
                pop = ''
            else:
                moving_art = van(uid, vehicle.get('distance', 0), animate=True)
                pop = ('<g transform="translate(25 -17)"><g transform="scale(0)">%s<animateTransform attributeName="transform" type="scale" values="0;1.18;1" '
                       'keyTimes="0;.7;1" begin="%ss" dur=".45s" fill="freeze"/></g></g>' % (CHECK, DUR - .1)) if motion == 'arrived' else ''
            # El recorrido sigue el mismo trazo; la furgoneta va en su carril (desplazada sobre la línea) dentro del grupo animado.
            animated = ('<g class="lgx-veh-anim"><g transform="translate(0 %s)"><g class="lgx-float">%s</g>%s</g><animateMotion begin="0s" dur="%ss" fill="freeze" calcMode="spline" '
                        'keyTimes="0;1" keySplines="%s" keyPoints="%s;%s" rotate="%s"><mpath href="#lgx-%s-%s"/></animateMotion></g>'
                        % (vehicle['lane'], moving_art, pop, DUR, SPLINE, vehicle['from'], vehicle['to'], 'auto' if kind == 'plane' else '0', uid, vehicle['segment']))
        craft = '<g class="lgx-veh" data-kind="%s" data-motion="%s" data-anim="%d">%s%s</g>' % (e(kind), e(motion), 1 if animated else 0, animated, static)
        if kind == 'plane' and motion == 'moving':
            cloud = 'M0 0a6 6 0 0 1 10-4a8 8 0 0 1 14 2a5 5 0 0 1 2 9h-26a5 5 0 0 1 0-7z'
            clouds = '<g class="lgx-clouds" aria-hidden="true">%s</g>' % ''.join(
                '<path transform="translate(%s %s) scale(%s)" d="%s"/>' % (x, y, k, cloud) for x, y, k in ((230, 44, 1), (330, 22, .8), (420, 40, 1.15), (470, 18, .7)))
    status = vehicle['text'] + '.' if vehicle else ''
    svg = ('<svg class="lgx-svg" viewBox="%s" role="img" aria-label="%s" preserveAspectRatio="xMidYMid meet"><defs>%s%s</defs>%s%s%s%s</svg>'
           % ('0 14 1000 144' if route['mode'] == 'internacional' else '0 34 1000 124',  # sin franjas vacías: el nacional no tiene arco
              e((title or 'Ruta del envío') + (': ' + status if status else '')), defs, vehicle_defs(uid) if vehicle else '', clouds, tracks, nodes, craft))
    # Lista vertical para teléfonos: nodos y tramos intercalados; el vehículo, junto a su tramo o su punto.
    items = []
    for i, n in enumerate(route['nodes']):
        items.append('<li class="lgx-li" data-state="%s"%s><svg viewBox="-16 -16 32 32" aria-hidden="true">%s</svg><span><b>%s</b><small>%s</small></span><em class="sr-only">%s</em></li>'
                     % (e(n['state']), ' data-customs="1"' if n['customs'] else '', _icon(n['icon'], 20), e(n['label']), e(' · '.join(filter(None, [n['sub'], _date(n['at'])]))), WORD[n['state']]))
        if i < len(route['segments']):
            s = route['segments'][i]
            here = vehicle and vehicle['segment'] == s['code']
            mu = uid + 'm'
            mark = (('<svg class="lgx-mini" viewBox="-48 -30 96 58" aria-hidden="true"><defs>%s</defs>%s</svg>' % (vehicle_defs(mu), plane(mu, 'down' if vehicle['motion'] in ('parked', 'landed') else 'up')))
                    if vehicle['kind'] == 'plane' else '<svg class="lgx-mini" viewBox="-36 -22 72 38" aria-hidden="true"><defs>%s</defs>%s</svg>' % (vehicle_defs(mu), van(mu))) if here else ''
            items.append('<li class="lgx-leg" data-state="%s" data-kind="%s"%s>%s<span>%s%s</span></li>'
                         % (e(s['state']), e(s['kind']), ' data-motion="%s"' % e(vehicle['motion']) if here else '', mark, e(SEGMENT_TEXT[s['kind']]),
                            ' · ' + e(vehicle['text'].lower()) if here else ''))
    return ('<div class="lgx" data-mode="%s"%s%s>%s<ol class="lgx-list" aria-label="%s">%s</ol><p class="sr-only">%s</p></div>'
            % (e(route['mode']), ' data-cancelled="1"' if route['cancelled'] else '', ' data-customs="1"' if route['customs_active'] else '', svg,
               e(title or 'Ruta del envío'), ''.join(items), e(status)))
