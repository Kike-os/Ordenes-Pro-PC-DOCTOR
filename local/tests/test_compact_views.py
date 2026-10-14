"""Indicadores de estado de las citas y Seguimiento de Órdenes ultracompacto: comprobaciones estáticas de la interfaz."""
import re,unittest
from pathlib import Path

STATIC=Path(__file__).resolve().parents[1]/'static'
JS=(STATIC/'app.js').read_text();CSS=(STATIC/'app.css').read_text()


class AppointmentPillTests(unittest.TestCase):
    def test_every_appointment_state_has_a_pill_with_icon_and_text(self):
        block=JS[JS.index('const agendaStatus='):JS.index('function agendaBadge(')]
        for state in ('nueva','confirmada','solicitada','reprogramada','presente','no_asistio','cancelada','completada'):
            self.assertRegex(block,r'\b'+state+r'\b')
        self.assertIn("solicitada:'Por confirmar'",JS);self.assertIn("reprogramada:'Reagendada'",JS)
        self.assertIn('function agendaPill(',JS);self.assertIn('.agenda-badge.state-pill',CSS)

    def test_appointment_badge_only_changes_the_presentation(self):
        # El indicador se pinta con el estado recibido: no llama al servidor ni modifica la cita.
        body=JS[JS.index('function agendaBadge('):];body=body[:body.index('\n')]
        self.assertNotIn('api(',body);self.assertNotIn('fetch(',body)


class CompactTrackingTests(unittest.TestCase):
    def test_rows_keep_every_action_and_a_stable_counter(self):
        for action in ("'ver'","'historial'","'qr'","'ticket'"):self.assertIn(action,JS)
        self.assertIn("menu.dataset.action='mas'",JS);self.assertIn("stableCount(total,{className:'tracking-history-count'",JS)
        self.assertRegex(CSS,r'button\[data-action=historial\] \.tracking-history-count\{flex:0 0 34px;width:34px;min-width:34px')

    def test_group_rows_show_order_unit_and_overall_state(self):
        self.assertIn("'tracking-unit'",JS);self.assertIn("'tracking-overall'",JS);self.assertIn('row.group.overall.label',JS)
        self.assertIn('const trackingSign=',JS);self.assertEqual(JS.count('trackingSign(row)'),2)
        for code in ('completada','parcial','curso','listos','recibidos'):self.assertIn('.tracking-overall[data-overall='+code+']',CSS)

    def test_state_colours_and_compact_layout(self):
        block=CSS[CSS.index('/* Seguimiento de Órdenes ultracompacto'):]
        for selector,colour in (('[data-status=reparacion]','#8cc3ff'),('[data-status=entregado]','#6de4af'),('[data-status=listo]','#62dbe0'),('[data-status=pendiente]','#ffca77'),('[data-status=cancelado]','#ff8794')):
            rule=next(line for line in block.splitlines() if selector in line and '--ts-ink' in line);self.assertIn(colour,rule)
        self.assertIn('.tracking-carousel{--track-row:54px}',block);self.assertIn('table-layout:fixed',block)
        # Sin desplazamiento horizontal en tableta: las acciones secundarias pasan al menú.
        self.assertIn('.tracking-carousel{--track-row:58px;overflow-x:hidden}',block)
        self.assertNotIn('!important',block)


if __name__=='__main__':
    unittest.main()
