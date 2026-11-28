"""Chromium regression for the order battery widget, with synthetic assessments."""
from pathlib import Path
import os
import unittest

from test_public_identity_visual import contrast, sync_playwright

STATIC = Path(__file__).resolve().parents[1] / 'static'
VALUES = (0, 0.1, 35, 50, 65, 85, 99.9, 100)
TONES = ('rojo', 'rojo', 'rojo', 'naranja', 'amarillo', 'verde', 'esmeralda', 'esmeralda')
COLORS = {
    'dark': ('rgb(255, 129, 144)', 'rgb(255, 163, 103)', 'rgb(255, 215, 102)',
             'rgb(18, 235, 186)', 'rgb(81, 232, 173)'),
    'light': ('rgb(179, 38, 64)', 'rgb(163, 65, 11)', 'rgb(121, 86, 0)',
              'rgb(7, 109, 86)', 'rgb(8, 117, 81)'),
}


@unittest.skipUnless(sync_playwright, 'La regresión requiere Python Playwright y Chromium.')
class OrderBatteryVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pw = sync_playwright().start()
        cls.addClassCleanup(pw.stop)
        if not Path(pw.chromium.executable_path).is_file():
            raise unittest.SkipTest('Instala Chromium mediante playwright install chromium.')
        cls.browser = pw.chromium.launch()
        cls.addClassCleanup(cls.browser.close)
        app = (STATIC / 'app.js').read_text()
        helpers = '\n'.join(line for line in app.splitlines() if line.startswith(
            ('function el(', 'function button(', 'function field(', 'function smallDialog(', 'function closeIcon(', 'function formatOrderDate(')))
        icons = app[app.index('const PA_ICONS='):app.index('const systemIcons=')]
        cls.component = helpers + '\n' + icons + '\n' + app[app.index('const {states:BATTERY_STATES'):app.index('function equipmentGroupSection(')]

    def page(self, width, theme, motion='no-preference'):
        page = self.browser.new_page(viewport={'width': width, 'height': 720}, reduced_motion=motion)
        self.addCleanup(page.close)
        page.route('**/*', lambda route: route.fulfill(
            content_type='text/html',
            body='<main id="module-content"><div class="equip-cards equip-picker"></div></main>'))
        page.goto('http://battery.test')
        page.evaluate('(theme)=>{if(theme==="light")document.documentElement.dataset.theme=theme}', theme)
        for file in ('design-tokens.css', 'battery-widget.css', 'app.css'):
            page.add_style_tag(path=STATIC / file)
        page.add_script_tag(path=STATIC / 'battery-widget.js')
        page.add_script_tag(content=self.component + """
            const admin=()=>true;
            const requestModalClose=dialog=>dialog.close();
            let fixtureResponse={available:true,battery:{id:0,status:'evaluada',percent:85},history:[]};
            const api=async()=>fixtureResponse;
            const record=percent=>({status:percent===null?'pendiente':'evaluada',percent});
            const addBattery=(percent,id)=> {
                const card=el('div',undefined,'equip-card equip-tab equip-battery-card');
                card.append(batteryIndicator({id,battery:record(percent)}));
                document.querySelector('.equip-picker').append(card);
            };
        """)
        return page

    def test_advanced_dialog_tabs_selects_and_alert_at_responsive_sizes(self):
        for width, theme in ((320, 'dark'), (390, 'light'), (768, 'dark'), (1280, 'dark')):
            with self.subTest(width=width, theme=theme):
                page = self.page(width, theme, 'reduce')
                page.add_script_tag(path=STATIC / 'ui-select.js')
                page.add_script_tag(content="""
                    const fixture={
                        available:true,advanced_available:true,
                        battery:{id:82,status:'evaluada',percent:85,
                            advanced:{battery_key:'pack-1',hazards:['inflamacion']}},
                        history:[{id:82,status:'evaluada',percent:85,created_at:'2026-11-27T09:15',
                            actor:'Personal ficticio',advanced:{battery_key:'pack-1'},
                            previous:{status:'pendiente',percent:null}}],
                    };
                """)
                page.evaluate('()=>{fixtureResponse=fixture;return openBatteryDiagnosis(82)}')
                dialog = page.get_by_role('dialog')
                self.assertEqual(dialog.get_by_role('tab').count(), 3)
                self.assertTrue(dialog.get_by_role('alert').is_visible())
                self.assertEqual(dialog.locator('.battery-advanced-panel[open]').count(), 0)
                control = dialog.locator('[name=status]')
                control.focus()
                control.press('ArrowDown')
                menu = dialog.get_by_role('listbox')
                self.assertTrue(menu.is_visible())
                self.assertTrue(menu.locator('[aria-selected=true] .ui-select-check').is_visible())
                self.assertEqual(menu.evaluate('node=>getComputedStyle(node).animationName'), 'none')
                fg, bg = menu.evaluate('node=>[getComputedStyle(node).color,getComputedStyle(node).backgroundColor]')
                self.assertGreater(contrast(fg, bg), 4.5)
                control.press('Escape')
                self.assertFalse(menu.is_visible())
                self.assertTrue(dialog.is_visible())
                self.assertTrue(control.evaluate('node=>node===document.activeElement'))
                dialog.get_by_text('Mediciones eléctricas avanzadas', exact=True).click()
                self.assertTrue(dialog.locator('[name=battery_nominal]').is_visible())
                self.assertTrue(dialog.locator('[name=battery_measured]').is_disabled())
                dialog.get_by_text('Condición física y eléctrica', exact=True).click()
                self.assertEqual(dialog.locator('.battery-tool-card[open]').count(), 1)
                self.assertFalse(dialog.locator('[name=battery_nominal]').is_visible())
                self.assertTrue(dialog.evaluate('node=>node.scrollWidth<=node.clientWidth+1'))
                tab = dialog.get_by_role('tab', name='Diagnóstico')
                tab.focus()
                tab.press('ArrowRight')
                self.assertEqual(dialog.get_by_role('tab', name='Reemplazo').get_attribute('aria-selected'), 'true')
                self.assertTrue(dialog.get_by_role('alert').is_visible())
                dialog.get_by_role('tab', name='Historial').click()
                self.assertEqual(dialog.locator('.battery-evolution-plot circle').count(), 2)

    def test_enterprise_dialog_has_one_scroll_region_and_fixed_actions(self):
        captures = os.getenv('BATTERY_CAPTURE_DIR')
        for width, height in ((1920, 1080), (1366, 768), (1280, 720), (768, 1024), (390, 844)):
            with self.subTest(width=width, height=height):
                page = self.page(width, 'dark', 'reduce')
                page.set_viewport_size({'width': width, 'height': height})
                page.add_script_tag(path=STATIC / 'ui-select.js')
                page.evaluate("""()=>{
                    document.body.dataset.page='dashboard';
                    fixtureResponse={available:true,advanced_available:true,
                        battery:{id:82,status:'evaluada',percent:85,created_at:'2026-11-28T09:30:00-05:00',
                            advanced:{battery_key:'fixture',hazards:['inflamacion']}},
                        history:[]};
                    return openBatteryDiagnosis(82);
                }""")
                dialog = page.get_by_role('dialog', name='Gestión de batería')
                self.assertTrue(dialog.get_by_role('heading', name='Gestión de batería').is_visible())
                self.assertEqual(dialog.get_by_role('tab').locator('svg').count(), 3)
                self.assertEqual(dialog.locator('.battery-tool-card').count(), 4)
                self.assertTrue(dialog.get_by_text('Battery Health Premium 6.4',exact=True).is_visible())
                self.assertEqual(dialog.locator('.battery-advanced-panel[open]').count(), 0)
                self.assertTrue(dialog.get_by_role('alert').is_visible())
                if width >= 768:
                    self.assertTrue(dialog.locator('.battery-tool-grid').evaluate('node=>node.getBoundingClientRect().bottom <= node.closest(".battery-dialog-body").getBoundingClientRect().bottom'))
                self.assertEqual(dialog.evaluate('node=>getComputedStyle(node).overflowY'), 'hidden')
                self.assertEqual(dialog.locator('.battery-dialog-body').evaluate('node=>getComputedStyle(node).overflowY'), 'auto')
                self.assertTrue(dialog.evaluate('node=>node.scrollWidth<=node.clientWidth+1 && node.clientHeight<=innerHeight*.9'))
                footer = dialog.locator('.battery-footer')
                initial = footer.bounding_box()
                if captures:
                    path = Path(captures)
                    path.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=path / f'bateria-{width}x{height}.png')
                dialog.get_by_text('Mediciones eléctricas avanzadas', exact=True).click()
                dialog.locator('.battery-dialog-body').evaluate('node=>node.scrollTop=node.scrollHeight')
                self.assertEqual(initial['y'], footer.bounding_box()['y'])
                self.assertTrue(dialog.get_by_role('button', name='Guardar').is_visible())
                self.assertTrue(dialog.get_by_role('alert').is_visible())

    def test_pending_overview_uses_one_visible_label_and_no_percent(self):
        page = self.page(768, 'dark', 'reduce')
        page.evaluate("""()=>{
            fixtureResponse={available:true,advanced_available:true,
             battery:{id:0,status:'pendiente',percent:null},history:[]};
            return openBatteryDiagnosis(82);
        }""")
        summary = page.locator('.battery-overview')
        self.assertEqual(summary.inner_text().count('Pendiente de diagnóstico'), 1)
        self.assertIn('Salud — · Desgaste —', summary.inner_text())
        self.assertNotIn('%', summary.inner_text())
        self.assertEqual(summary.locator('.battery-overview-state').get_attribute('data-state'), 'pendiente')
        self.assertFalse(summary.locator('.equip-battery-percent').is_visible())

    def test_geometry_colors_and_proportions_across_viewports(self):
        for width, theme in ((320, 'light'), (390, 'dark'), (768, 'light'), (1280, 'dark')):
            with self.subTest(width=width, theme=theme):
                page = self.page(width, theme, 'reduce')
                page.evaluate('(values)=>values.forEach(addBattery)', [*VALUES, None])
                widgets = page.locator('.equip-battery-widget')
                observed = widgets.evaluate_all("""nodes=>nodes.map(n=>{
                    const icon=n.querySelector('svg');
                    const geometry=s=>[...icon.querySelectorAll(s)].map(r=>
                        ['x','y','width','height','rx'].map(a=>Number(r.getAttribute(a))));
                    return {tone:n.dataset.tone, color:getComputedStyle(icon).color,
                        condition:getComputedStyle(n.querySelector('.equip-battery-condition')).color,
                        box:icon.getAttribute('viewBox'),
                        shell:geometry('.equip-battery-case,.equip-battery-rim,.equip-battery-terminal'),
                        slots:geometry('.equip-battery-slot'),
                        fill:[...icon.querySelectorAll('.equip-battery-level')].map(r=>
                            Number(r.style.getPropertyValue('--battery-fill'))),
                        size:[n.offsetWidth,n.offsetHeight,icon.getBoundingClientRect().width],
                        overflow:n.scrollWidth>n.clientWidth || n.scrollHeight>n.clientHeight};
                })""")
                for index, (item, value, tone) in enumerate(zip(observed, VALUES, TONES)):
                    self.assertEqual(item['tone'], tone)
                    self.assertEqual(item['color'], COLORS[theme][[0, 0, 0, 1, 2, 3, 4, 4][index]])
                    self.assertEqual(item['condition'], item['color'])
                    self.assertGreater(contrast(item['color'], 'rgb(255,255,255)' if theme == 'light'
                                                else 'rgb(21,40,61)'), 4.5)
                    self.assertEqual(item['box'], '0 0 600 244')
                    self.assertEqual(item['shell'], [[16, 16, 526, 215, 37], [27, 27, 504, 193, 27],
                                                     [555, 78, 30, 91, 14]])
                    self.assertEqual(item['slots'], [[x, 42, w, 162, 13] for x, w in
                                                     ((43, 91), (144, 91), (244, 91), (345, 91), (439, 77))])
                    for segment, actual in enumerate(item['fill']):
                        self.assertAlmostEqual(actual, min(1, max(0, value / 20 - segment)))
                    self.assertEqual(item['size'], observed[0]['size'])
                    self.assertFalse(item['overflow'])
                self.assertEqual(observed[-1]['tone'], 'pendiente')
                self.assertEqual(observed[-1]['size'], observed[0]['size'])
                self.assertEqual(observed[-1]['fill'], [0] * 5)
                self.assertIn('Pendiente de diagnóstico', widgets.last.inner_text())
                self.assertNotIn('%', widgets.last.inner_text())
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))

    def test_dialog_keyboard_transition_and_motion_controls(self):
        page = self.page(390, 'dark')
        page.evaluate('addBattery(85,1)')
        trigger = page.locator('.equip-battery-trigger')
        page.keyboard.press('Tab')
        self.assertTrue(trigger.evaluate('n=>n.matches(":focus-visible") && getComputedStyle(n).outlineWidth==="2px"'))
        page.keyboard.press('Enter')
        dialog = page.get_by_role('dialog')
        self.assertTrue(dialog.is_visible())
        wear = dialog.locator('[name=wear]')
        preview = dialog.locator('.equip-battery-preview')
        level = preview.locator('.equip-battery-level').first
        dialog.evaluate('node=>Promise.all(node.getAnimations().map(animation=>animation.finished))')
        before = preview.bounding_box()
        wear.fill('99,9')
        self.assertEqual(dialog.locator('[name=percent]').input_value(), '0,1')
        self.assertEqual(preview.get_attribute('data-tone'), 'rojo')
        self.assertEqual(level.evaluate('n=>getComputedStyle(n).transitionDuration'), '0.6s')
        page.wait_for_function("""()=>Math.abs(new DOMMatrix(getComputedStyle(
            document.querySelector('.equip-battery-preview .equip-battery-level')).transform).a-.005)<.0001""")
        self.assertEqual(preview.bounding_box(), before)
        dialog.get_by_text('Configuración avanzada',exact=True).click()
        toggle = dialog.get_by_label('Desactivar animaciones de batería')
        toggle.focus()
        page.keyboard.press('Space')
        self.assertTrue(toggle.is_checked())
        terminal = preview.locator('.equip-battery-terminal')
        self.assertEqual(terminal.evaluate('n=>getComputedStyle(n).animationName'), 'none')
        self.assertEqual(page.evaluate('localStorage.getItem(batteryMotionKey)'), '1')
        page.keyboard.press('Space')
        page.emulate_media(reduced_motion='reduce')
        self.assertEqual(terminal.evaluate('n=>getComputedStyle(n).animationName'), 'none')
        page.keyboard.press('Escape')
        self.assertFalse(dialog.locator('.battery-preferences').evaluate('node=>node.open'))
        page.keyboard.press('Escape')
        dialog.wait_for(state='detached')
        self.assertTrue(trigger.evaluate('n=>document.activeElement===n'))

    def test_animation_profiles_and_exact_band_edges(self):
        page = self.page(390, 'dark')
        page.evaluate('(values)=>values.forEach(addBattery)', [39.99, 40, 59.99, 60, 79.99, 80, 89.99, 90, None])
        widgets = page.locator('.equip-battery-widget')
        self.assertEqual(widgets.evaluate_all('nodes=>nodes.map(n=>n.dataset.tone)'), [
            'rojo', 'naranja', 'naranja', 'amarillo', 'amarillo', 'verde', 'verde', 'esmeralda', 'pendiente',
        ])
        profiles = widgets.evaluate_all("""nodes=>nodes.map(n=>['.equip-battery-case','.equip-battery-terminal',
            '.equip-battery-glow'].map(s=>{const c=getComputedStyle(n.querySelector(s));
                return [c.animationName,c.animationDuration];}))""")
        self.assertEqual(profiles[0], [['equip-battery-outline-pulse', '4.8s']] * 2 + [['none', '0s']])
        self.assertEqual(profiles[1][2], ['equip-battery-inner-pulse', '4.8s'])
        self.assertEqual(profiles[3][2], ['equip-battery-wave', '4.4s'])
        self.assertEqual(profiles[5][2], ['equip-battery-inner-pulse', '4s'])
        self.assertEqual(profiles[7][2], ['equip-battery-wave', '3.6s'])
        self.assertEqual(profiles[8], [['none', '0s']] * 3)

    def test_mount_on_existing_portal_node_runs_without_changing_fill(self):
        page = self.page(390, 'dark')
        page.evaluate("""()=>{
            const node=document.createElement('div');
            document.querySelector('main').append(node);
            BatteryWidget.render(node,()=> '')({status:'evaluada',percent:85});
        }""")
        widget = page.locator('.equip-battery-widget')
        widget.scroll_into_view_if_needed()
        page.wait_for_function("""()=>{
            const glow=document.querySelector('.equip-battery-glow');
            return glow.getAnimations().some(a=>a.playState==='running'&&a.currentTime>0);
        }""", timeout=1500)
        self.assertEqual(widget.locator('.equip-battery-level').evaluate_all(
            "nodes=>nodes.map(n=>Number(n.style.getPropertyValue('--battery-fill')))"), [1, 1, 1, 1, .25])
        self.assertEqual(widget.locator('.equip-battery-percent').inner_text(), '85 %')

    def test_only_visible_widgets_run_animations(self):
        page = self.page(390, 'dark')
        page.evaluate('()=>{for(let i=0;i<80;i++)addBattery(80,i)}')
        widgets = page.locator('.equip-battery-widget')
        first, last = widgets.first, widgets.last
        first.locator('[data-battery-filled]').first.wait_for(state='attached')
        page.wait_for_function('document.querySelector(".equip-battery-widget").hasAttribute("data-battery-visible")')
        states = lambda widget: widget.locator('.equip-battery-glow').evaluate_all(
            'nodes=>nodes.map(n=>[getComputedStyle(n).animationName,getComputedStyle(n).animationPlayState])')
        self.assertEqual(states(first)[:4], [['equip-battery-inner-pulse', 'running']] * 4)
        self.assertEqual(states(first)[4][0], 'none')
        page.evaluate("""()=>{
            Object.defineProperty(document,'hidden',{configurable:true,value:true});
            document.dispatchEvent(new Event('visibilitychange'));
        }""")
        self.assertEqual(states(first)[:4], [['equip-battery-inner-pulse', 'paused']] * 4)
        page.evaluate("""()=>{
            delete document.hidden;
            document.dispatchEvent(new Event('visibilitychange'));
        }""")
        self.assertEqual(states(last)[:4], [['equip-battery-inner-pulse', 'paused']] * 4)
        last.scroll_into_view_if_needed()
        page.wait_for_function("""()=>document.querySelector('.equip-picker').lastElementChild
            .querySelector('.equip-battery-widget').hasAttribute('data-battery-visible')""")
        self.assertEqual(states(last)[:4], [['equip-battery-inner-pulse', 'running']] * 4)
        self.assertEqual(states(first)[:4], [['equip-battery-inner-pulse', 'paused']] * 4)
