"""ADI como asistente técnica (1.5.256, datos ficticios, base temporal, SIN llamar a ningún proveedor: las respuestas del modelo se simulan).
Comprueba lo que no depende del modelo: tipo de informe y modo recomendado, estructura pedida, revisión de repeticiones, avisos de trabajos o
especificaciones no registrados, privacidad del contexto (sin cliente, serie, credenciales ni precios), cabecera real y alertas de atención."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import adi_ai
import adi_admin
import adi_reports
import test_part_requests as parts
import app

REPORT = ("INFORME TÉCNICO — EVALUACIÓN DE DIAGNÓSTICO\nDescripción de la incidencia:\nEl equipo portátil presenta lentitud general y sobrecalentamiento. "
          "El equipo portátil presenta lentitud general y sobrecalentamiento.\nHallazgos comprobados:\nPendiente de comprobación.\nPosibles causas:\n"
          "La unidad de almacenamiento podría presentar deterioro.\nIntervenciones recomendadas:\n1. Evaluar la unidad de almacenamiento con herramientas de diagnóstico.\n"
          "2. Evaluar la unidad de almacenamiento con herramientas de diagnóstico.\n3. Sustituir el compuesto térmico.\nVerificaciones pendientes:\n1. Lectura SMART de la unidad.\n"
          "Conclusión técnica:\nSe sustituyó el disco por una unidad NVMe. Se recomienda elaborar un presupuesto sujeto al diagnóstico.")


class ReportRulesTests(unittest.TestCase):
    def test_kind_and_recommended_mode(self):
        cases = {'no da imagen, hay corto en la placa': 'electronica', 'pide contraseña de bios al encender': 'bios', 'la impresora epson no jala tinta': 'impresora',
                 'el disco hace ruido y está lento': 'almacenamiento', 'pantalla azul y se reinicia, puede ser la ram': 'memoria',
                 'se calienta mucho, cambiar pasta térmica': 'refrigeracion', 'limpieza y mantenimiento preventivo': 'mantenimiento', 'revisar equipo': 'diagnostico'}
        for text, kind in cases.items():
            self.assertEqual(adi_reports.report_kind(text), kind, text)
        self.assertEqual(adi_reports.report_kind('lo que sea', 'budget'), 'presupuesto')
        self.assertEqual(adi_reports.report_kind('lo que sea', 'work'), 'entrega')
        self.assertEqual(adi_reports.report_kind('disco lento', 'findings', 'bios'), 'bios')  # el técnico manda
        self.assertEqual(adi_reports.recommend('client_message', 'x'), 'cliente')
        self.assertEqual(adi_reports.recommend('findings', 'la portátil está lenta, el disco falla, se calienta y hay que cambiarlo por un SSD'), 'informe')
        self.assertEqual(adi_reports.recommend('findings', 'disco malo'), 'tecnica')  # poco texto: no se infla a informe
        self.assertEqual(adi_reports.recommend('problem', 'no prende'), 'redaccion')

    def test_dedupe_and_unsupported(self):
        text, removed = adi_reports.dedupe(REPORT)
        self.assertEqual(removed, 2)
        self.assertEqual(text.count('presenta lentitud general'), 1)
        self.assertIn('2. Sustituir el compuesto térmico.', text)  # la lista se renumera
        claims, specs = adi_reports.unsupported('la portátil está lenta, el disco falla, cambiar por SSD', text)
        self.assertTrue(any('sustituy' in c for c in claims));self.assertEqual(specs, ['NVMe'])
        claims, specs = adi_reports.unsupported('se sustituyó el disco por una unidad NVMe', text)
        self.assertEqual((claims, specs), ([], []))  # lo registrado no se avisa
        self.assertEqual(adi_reports.tidy('**INFORME**\n## Conclusión:'), 'INFORME\nConclusión:')

    def test_improve_report_with_simulated_model(self):
        seen = {}

        def fake(system, user, long=False):
            seen.update(system=system, user=user, long=long)
            return REPORT, 900, 400
        with patch.object(adi_ai, '_complete', fake):
            out = adi_ai.improve('La portátil está lenta, el disco falla, se calienta y hay que cambiarlo por un SSD y poner pasta térmica', 'informe', 'findings', None)
        self.assertTrue(seen['long'])
        self.assertIn('Secciones, en este orden: Descripción de la incidencia; Hallazgos comprobados', seen['user'])
        self.assertIn('nunca afirmes pruebas realizadas', seen['system'].lower())
        self.assertEqual((out['report'], out['report_label']), ('almacenamiento', 'Falla de almacenamiento'))
        self.assertEqual(out['suggestion'].count('presenta lentitud general'), 1)
        joined = ' '.join(out['warnings'])
        for expected in ('quitó 2 frases repetidas', 'no constan como realizadas', 'NVMe', 'Informe preliminar'):
            self.assertIn(expected, joined)


class ReportContextTests(unittest.TestCase):
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link

    def test_context_is_technical_and_private_and_header_is_real(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        with app.connect() as c:
            client, serial = c.execute('SELECT cl.name,d.serial FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (oid,)).fetchone()
            c.execute("UPDATE orders SET findings='Disco con sectores reasignados (SMART), temperatura de CPU 96 °C en carga' WHERE id=?", (oid,))
            uid = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
            c.execute("INSERT INTO order_followups(order_id,kind,internal_note,client_message,client_visible,status_code,next_action,next_date,priority,request_key,created_by,created_at) "
                      "VALUES (?,'pruebas','Prueba de estrés 20 min estable. clave: Secreta123 · %s',''," % client.replace("'", "''") + "0,'','','','normal','adi-ctx',?,?)",
                      (oid, uid, app.reception_now().isoformat(timespec='seconds')))
            c.commit()
            ctx = adi_reports.order_context(c, oid)
        blob = json.dumps(ctx['data'], ensure_ascii=False)
        self.assertIn('sectores reasignados', blob);self.assertIn('Prueba de estrés 20 min estable', blob)
        self.assertIn('Presupuesto (sin importes)', ctx['data'])
        for secret in (client, 'Secreta123', '105', '$'):
            self.assertNotIn(secret, blob, secret)
        if serial:
            self.assertNotIn(serial, blob);self.assertIn(serial, ctx['header'])
        self.assertIn(order['code'], ctx['header'])
        # Por la ruta: el proveedor (simulado) recibe solo el contexto depurado; la cabecera real se agrega después.
        seen = {}

        def fake(system, user, long=False):
            seen['user'] = user
            return REPORT.replace('Se sustituyó el disco por una unidad NVMe. ', ''), 900, 400
        with patch.object(adi_ai, 'provider', lambda: 'openai'), patch.object(adi_ai, '_complete', fake):
            got = post('/api/adi/write', text='el disco falla y se calienta, hay que cambiar a ssd', mode='informe', field='findings', order_id=str(oid))
        self.assertEqual(got['status'], 200, got['body'])
        self.assertNotIn(client, seen['user']);self.assertNotIn('Secreta123', seen['user']);self.assertNotIn(order['code'], seen['user'])
        lines = got['body']['suggestion'].split('\n')
        self.assertTrue(lines[0].startswith('INFORME TÉCNICO'));self.assertTrue(lines[1].startswith('Orden: ' + order['code']))
        self.assertEqual(got['body']['report'], 'almacenamiento')

    def test_attention_alerts_recommend_without_changing(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)  # presupuesto aprobado
        oid = order['id']
        with app.connect() as c:
            c.execute("UPDATE orders SET status='presupuesto' WHERE id=?", (oid,));c.commit()
        self.part(post, oid, eta=(app.reception_now().date() - timedelta(days=3)).isoformat())
        with app.connect() as c:
            before = c.execute('SELECT status,revision FROM orders WHERE id=?', (oid,)).fetchone()
            data = adi_admin.alerts(c, app.reception_now())
            after = c.execute('SELECT status,revision FROM orders WHERE id=?', (oid,)).fetchone()
        kinds = {item['tipo'] for item in data['avisos']}
        self.assertIn('presupuesto_desfasado', kinds)  # aprobado, pero la orden sigue esperando el presupuesto
        self.assertIn('presupuesto_sin_diagnostico', kinds)
        self.assertIn('repuesto_atrasado', kinds)
        self.assertTrue(all(item.get('accion') for item in data['avisos'] if item['tipo'] in ('presupuesto_desfasado', 'repuesto_atrasado')))
        self.assertGreaterEqual(data['inconsistencias'], 2)
        self.assertEqual(tuple(before), tuple(after))  # solo lectura


if __name__ == '__main__':
    unittest.main()
