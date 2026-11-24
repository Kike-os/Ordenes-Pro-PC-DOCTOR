"""Control visual automatizado de ADI Smart Collections (Playwright). Uso:
    python local/tests/visual_collections.py URL USUARIO CLAVE CARPETA_CAPTURAS
No se ejecuta con la suite unitaria (necesita un servidor y un navegador). Recorre escritorio, portátil, tableta y móvil, y simula el zoom del
navegador (80 %, 100 %, 125 % y 150 %) con el ancho CSS equivalente. Falla si encuentra: desbordamiento horizontal de la página, botones
superpuestos, encabezados recortados o encimados, palabras o números de orden partidos, textos fuera de su contenedor, o el menú de acciones
fuera de la pantalla. Solo lee: no crea, cambia ni envía nada."""
import json
import sys

from playwright.sync_api import sync_playwright

SIZES = [(1920, 1080), (1600, 900), (1366, 768), (1280, 720), (1024, 768), (768, 1024), (390, 844)]
ZOOMS = [0.8, 1.0, 1.25, 1.5]

CHECK = r"""(()=>{
 const out={problems:[]};const W=document.documentElement;if(W.scrollWidth>W.clientWidth+1)out.problems.push('desbordamiento horizontal de la página '+W.scrollWidth+'>'+W.clientWidth);
 const t=document.querySelector('.cc32');if(!t){out.problems.push('sin tabla');return out;}
 const wr=document.querySelector('.cc32-wrap');if(wr.scrollWidth>wr.clientWidth+1)out.problems.push('desplazamiento horizontal dentro de la tabla '+wr.scrollWidth+'>'+wr.clientWidth);
 const inter=(A,B)=>A.left<B.right-1&&B.left<A.right-1&&A.top<B.bottom-1&&B.top<A.bottom-1;
 for(const row of t.querySelectorAll('tbody tr')){const bs=[...row.querySelectorAll('.cc32-btn,.cc32-icon')].filter(b=>b.offsetParent).map(b=>b.getBoundingClientRect());
  for(let i=0;i<bs.length;i++)for(let j=i+1;j<bs.length;j++)if(inter(bs[i],bs[j]))out.problems.push('botones superpuestos');
  for(const b of row.querySelectorAll('.cc32-btn span')){if(b.offsetParent&&(b.getClientRects().length>1||b.scrollWidth>b.clientWidth+1))out.problems.push('texto de botón partido: '+b.textContent);}
  for(const c of row.querySelectorAll('.cc32-link')){if(c.getClientRects().length>1||c.getBoundingClientRect().height>24)out.problems.push('número de orden partido: '+c.textContent);}
  for(const n of row.querySelectorAll('.cc32-amount strong,.cc-state')){if(n.scrollWidth>n.clientWidth+1)out.problems.push('texto fuera de su contenedor: '+n.textContent);}
  const cells=[...row.children].filter(c=>c.offsetParent);for(const c of cells){if(c.scrollWidth>c.clientWidth+2)out.problems.push('celda desbordada: '+(c.dataset.label||''));}
  // palabras partidas: ninguna palabra puede ocupar más de una línea
  for(const n of row.querySelectorAll('td *')){if(!n.childNodes.length||[...n.childNodes].some(x=>x.nodeType!==3))continue;const text=n.textContent.trim();if(!text)continue;
   const range=document.createRange();let pos=0;for(const word of text.split(/\s+/)){const i=n.textContent.indexOf(word,pos);if(i<0)continue;pos=i+word.length;range.setStart(n.firstChild,i);range.setEnd(n.firstChild,i+word.length);
    const rects=[...range.getClientRects()].filter(r=>r.width>0);if(rects.length>1&&new Set(rects.map(r=>Math.round(r.top))).size>1)out.problems.push('palabra partida: «'+word+'»');}}}
 const ths=[...t.querySelectorAll('th')].filter(x=>x.offsetParent).map(x=>x.getBoundingClientRect());for(let i=0;i<ths.length;i++)for(let j=i+1;j<ths.length;j++)if(inter(ths[i],ths[j]))out.problems.push('encabezados encimados');
 for(const th of t.querySelectorAll('th'))if(th.offsetParent&&th.scrollWidth>th.clientWidth+1)out.problems.push('encabezado recortado: '+th.textContent);
 out.mode=getComputedStyle(t.querySelector('thead')).display==='none'?'tarjetas':'tabla';out.rows=t.querySelectorAll('tbody tr').length;out.problems=[...new Set(out.problems)];return out;})()"""


def main(base, user, password, out_dir):
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.goto(base + '/login' if 'ecuadorpcdoctor' in base else base + '/')
        page.fill('#login', user)
        page.fill('#password', password)
        page.click('button[type=submit]')
        page.wait_for_load_state('networkidle')
        page.evaluate("go('invoicing')")
        page.wait_for_timeout(1200)
        page.evaluate("invoiceGo('cartera')")
        page.wait_for_selector('.cc32', timeout=20000)
        for w, h in SIZES:
            for zoom in ZOOMS:
                if w <= 768 and zoom != 1.0:
                    continue
                vw, vh = round(w / zoom), round(h / zoom)
                page.set_viewport_size({'width': vw, 'height': vh})
                page.wait_for_timeout(350)
                result = page.evaluate(CHECK)
                more = page.locator('.cc32-more').first
                more.scroll_into_view_if_needed()
                more.click()
                page.wait_for_selector('.cc-menu', timeout=3000)
                inside = page.evaluate("(()=>{const r=document.querySelector('.cc-menu').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight})()")
                page.keyboard.press('Escape')
                if not inside:
                    result['problems'].append('menú fuera de la pantalla')
                label = '%dx%d@%d%%' % (w, h, round(zoom * 100))
                print(label, result['mode'], 'filas', result['rows'], 'OK' if not result['problems'] else 'FALLA: ' + '; '.join(result['problems'][:6]))
                if result['problems']:
                    failures.append((label, result['problems']))
                if zoom == 1.0:
                    page.locator('.cc32-wrap').screenshot(path='%s/cartera-%d.png' % (out_dir, w))
        browser.close()
    print(json.dumps({'fallos': len(failures)}))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:5]))
