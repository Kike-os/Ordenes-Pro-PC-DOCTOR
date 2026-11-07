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
PLANE = ('<path class="lgx-plane" d="M-22 0c0-1 .8-1.8 1.8-1.8H-6L3.5-12.2h4.2L2.8-1.8H14l3.3-4.1h3.4l-2.1 6.1 2.1 6.1h-3.4L14 2.2H2.8l4.9 10.4H3.5L-6 1.8H-20.2'
         'c-1 0-1.8-.8-1.8-1.8z"/>')
TRUCK = ('<g class="lgx-truck"><path class="lgx-t-box" d="M-24-10a3 3 0 0 1 3-3h20a3 3 0 0 1 3 3v12h-26z"/><path class="lgx-t-cab" d="M4-8h8.5a3 3 0 0 1 2.5 1.3l4.2 6.2a3 3 0 0 1 .5 1.7V2'
         'H4z"/><path class="lgx-t-win" d="M6-6h6l3.4 5H6z"/><circle class="lgx-t-wheel" cx="-16" cy="4" r="3.6"/><circle class="lgx-t-wheel" cx="11" cy="4" r="3.6"/></g>')
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
    craft = ''
    if vehicle:
        shape = PLANE if vehicle['kind'] == 'plane' else TRUCK
        arrived = CHECK if vehicle['motion'] == 'arrived' else ''
        body = '<g class="lgx-float">%s</g>%s' % (shape, '<g transform="translate(0 -22)">%s</g>' % arrived if arrived else '')
        static = '<g class="lgx-veh-static" transform="translate(%s %s) rotate(%s)">%s</g>' % (vehicle['x'], vehicle['y'], vehicle['angle'], body)
        animated = ''
        if vehicle['animate']:
            # El recorrido sigue el mismo trazo; el camión va en su carril (desplazado sobre la línea) dentro del grupo animado.
            animated = ('<g class="lgx-veh-anim"><g transform="translate(0 %s)">%s</g><animateMotion begin="0s" dur="1.6s" fill="freeze" calcMode="spline" keyTimes="0;1" '
                        'keySplines=".45 0 .2 1" keyPoints="%s;%s" rotate="%s"><mpath href="#lgx-%s-%s"/></animateMotion></g>'
                        % (vehicle['lane'], body, vehicle['from'], vehicle['to'], 'auto' if vehicle['kind'] == 'plane' else '0', uid, vehicle['segment']))
        craft = '<g class="lgx-veh" data-kind="%s" data-motion="%s" data-anim="%d">%s%s</g>' % (e(vehicle['kind']), e(vehicle['motion']), 1 if animated else 0, animated, static)
    status = vehicle['text'] + '.' if vehicle else ''
    svg = ('<svg class="lgx-svg" viewBox="%s" role="img" aria-label="%s" preserveAspectRatio="xMidYMid meet"><defs>%s</defs>%s%s%s</svg>'
           % ('0 14 1000 144' if route['mode'] == 'internacional' else '0 34 1000 124',  # sin franjas vacías: el nacional no tiene arco
              e((title or 'Ruta del envío') + (': ' + status if status else '')), defs, tracks, nodes, craft))
    # Lista vertical para teléfonos: nodos y tramos intercalados; el vehículo, junto a su tramo o su punto.
    items = []
    for i, n in enumerate(route['nodes']):
        items.append('<li class="lgx-li" data-state="%s"%s><svg viewBox="-16 -16 32 32" aria-hidden="true">%s</svg><span><b>%s</b><small>%s</small></span><em class="sr-only">%s</em></li>'
                     % (e(n['state']), ' data-customs="1"' if n['customs'] else '', _icon(n['icon'], 20), e(n['label']), e(' · '.join(filter(None, [n['sub'], _date(n['at'])]))), WORD[n['state']]))
        if i < len(route['segments']):
            s = route['segments'][i]
            here = vehicle and vehicle['segment'] == s['code']
            mark = ('<svg class="lgx-mini" viewBox="-26 -16 52 32" aria-hidden="true">%s</svg>' % (PLANE if vehicle['kind'] == 'plane' else TRUCK)) if here else ''
            items.append('<li class="lgx-leg" data-state="%s" data-kind="%s"%s>%s<span>%s%s</span></li>'
                         % (e(s['state']), e(s['kind']), ' data-motion="%s"' % e(vehicle['motion']) if here else '', mark, e(SEGMENT_TEXT[s['kind']]),
                            ' · ' + e(vehicle['text'].lower()) if here else ''))
    return ('<div class="lgx" data-mode="%s"%s%s>%s<ol class="lgx-list" aria-label="%s">%s</ol><p class="sr-only">%s</p></div>'
            % (e(route['mode']), ' data-cancelled="1"' if route['cancelled'] else '', ' data-customs="1"' if route['customs_active'] else '', svg,
               e(title or 'Ruta del envío'), ''.join(items), e(status)))
