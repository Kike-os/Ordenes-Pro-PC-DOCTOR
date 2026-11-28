"""Mide el indicador de batería en Chromium con datos ficticios."""

import argparse
import json
from pathlib import Path
from time import monotonic, sleep

from playwright.sync_api import sync_playwright


STATIC = Path(__file__).resolve().parents[1] / 'static'
VALUES = (0, 0.1, 15, 20, 36, 40, 50, 60, 65, 80, 85, 99.9, 100, None)
FIXTURE = '''<!doctype html><html lang="es"><meta charset="utf-8">
<style>body{background:#15283d;color:#fff;font:15px system-ui}
main{display:flex;gap:12px;flex-wrap:wrap}h1{font-size:20px}</style>
<h1>Salud de batería · Datos ficticios</h1><main></main>'''
MOUNT = '''values=>{
    for(const percent of values){
        const node=document.createElement('div');
        document.querySelector('main').append(node);
        BatteryWidget.render(node,()=> '')({status:percent===null?'pendiente':'evaluada',percent});
    }
}'''
MEASURE = '''()=>{
    window.timerCalls=0;
    for(const method of ['setTimeout','setInterval']){
        const original=window[method];
        window[method]=(...args)=>{timerCalls++;return original(...args);};
    }
    const frames=[];
    let previous=performance.now();
    function frame(time){
        frames.push(time-previous);
        previous=time;
        if(frames.length>3600)frames.shift();
        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    window.frameP95=()=>frames.slice().sort((a,b)=>a-b)[Math.floor(frames.length*.95)];
}'''
REFRESH = '''()=>{
    const widgets=[...document.querySelectorAll('.equip-battery-widget')];
    const glow=widgets.find(node=>node.dataset.tone==='verde').querySelector('.equip-battery-glow');
    window.refreshFixture=()=>{
        const before=glow.getAnimations()[0].currentTime;
        BatteryWidget.preserveMotion(widgets,()=>{
            const parent=document.createElement('main');
            parent.append(...widgets);
            document.querySelector('main').replaceWith(parent);
        });
        const after=glow.getAnimations()[0].currentTime;
        return {
            restart:after<before,before,after,
            nodes:document.querySelectorAll('.equip-battery-widget').length,
            stable:widgets.every(node=>node.isConnected),
            timers:timerCalls,frameP95:frameP95(),animations:document.getAnimations().length
        };
    };
}'''


def mount(page, assets):
    page.add_style_tag(path=STATIC / 'design-tokens.css')
    page.add_style_tag(path=assets / 'battery-widget.css')
    page.add_script_tag(path=assets / 'battery-widget.js')
    page.evaluate(MOUNT, VALUES)


def capture(browser, out, name, assets):
    folder = out / name
    folder.mkdir(exist_ok=True)
    video = name == 'despues'
    context = browser.new_context(viewport={'width': 1280, 'height': 720},
                                  record_video_dir=folder if video else None,
                                  record_video_size={'width': 1280, 'height': 720})
    page = context.new_page()
    page.set_content(FIXTURE)
    mount(page, assets)
    for width, height in [(1280, 720), (768, 1024), (390, 844), (320, 720)]:
        page.set_viewport_size({'width': width, 'height': height})
        page.wait_for_timeout(500)
        page.screenshot(path=folder / f'indicadores-{width}.png', full_page=True)
    if video:
        page.set_viewport_size({'width': 1280, 'height': 720})
        page.wait_for_timeout(7300)
    context.close()
    if video:
        page.video.path().replace(out / 'animacion-chromium.webm')


def measure(browser, out, duration):
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    page.set_content(FIXTURE)
    page.evaluate(MEASURE)
    mount(page, STATIC)
    page.wait_for_function("document.querySelector('[data-tone=verde]').hasAttribute('data-battery-visible')")
    page.evaluate(REFRESH)
    session = page.context.new_cdp_session(page)
    began = monotonic()
    with (out / 'estabilidad-chromium.jsonl').open('w', encoding='utf8') as log:
        while True:
            elapsed = monotonic() - began
            info = page.evaluate('refreshFixture()')
            session.send('HeapProfiler.collectGarbage')
            entry = {
                'seconds': round(elapsed, 2), 'chromium': browser.version, **info,
                **session.send('Runtime.getHeapUsage'), 'dom': session.send('Memory.getDOMCounters'),
                'errors': errors,
            }
            print(json.dumps(entry), file=log, flush=True)
            assert info['stable'] and not info['restart'] and info['nodes'] == len(VALUES), entry
            assert not errors and not info['timers'], entry
            if elapsed >= duration:
                break
            sleep(min(15, duration - elapsed))
    page.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--baseline', type=Path, help='Carpeta con el JS y CSS originales del indicador')
    parser.add_argument('--seconds', type=int, default=1800)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        if args.baseline:
            capture(browser, args.output, 'antes', args.baseline)
        capture(browser, args.output, 'despues', STATIC)
        measure(browser, args.output, args.seconds)
        browser.close()


if __name__ == '__main__':
    main()
