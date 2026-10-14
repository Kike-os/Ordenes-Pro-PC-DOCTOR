"""Catálogo: iconos técnicos por servicio, logotipos de marca disponibles y ventana de selección."""
import re,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import catalog_icons


class CatalogIconTests(unittest.TestCase):
    def test_each_service_gets_its_technical_icon(self):
        table=[('Diagnóstico de memoria RAM','memoria'),('Programación y recuperación BIOS','bios'),('Reparación electrónica','placa'),('Reparación de portátiles','portatil'),('Reparación de computadoras','escritorio'),
               ('Mantenimiento preventivo','mantenimiento'),('Mantenimiento correctivo','mantenimiento'),('Limpieza interna','limpieza'),('Cambio de pasta térmica','termica'),('Reparación de impresoras','impresora'),
               ('Reparación de pantallas','pantalla'),('Reparación de redes','red'),('Instalación de sistemas operativos','windows'),('Recuperación de datos','almacenamiento'),('Diagnóstico técnico','diagnostico'),('Servicio técnico de PlayStation 5','consola')]
        for name,icon in table:self.assertEqual(catalog_icons.guess('servicio',name),icon,name)
        # Productos de marcas sin logotipo disponible: icono técnico de su tipo, nunca vacío ni inventado.
        for category,name,icon in (('licencia','Microsoft Office 2024 Estándar','ofimatica'),('licencia','Windows 11 Pro – Licencia empresarial','windows'),('seguridad','ESET NOD32 Antivirus – Licencia de 1 Año','antivirus'),('seguridad','Defender Plus – Licencia Antivirus, 1 año','antivirus'),('otro','Producto sin palabras clave','producto')):
            self.assertEqual(catalog_icons.guess(category,name),icon,name)
        # Los que ya estaban no cambian.
        self.assertEqual((catalog_icons.guess('otro','Cambio de pantalla de portátil gamer de 15,6 pulgadas'),catalog_icons.guess('servicio','Pegado de bisagras de portátil de 14 pulgadas'),catalog_icons.guess('servicio','Mantenimiento de PC Gamer con cambio de pasta térmica')),('pantalla_gamer','bisagra','pc_gamer'))

    def test_every_icon_draws_and_brand_logos_are_untouched_files(self):
        icons=catalog_icons.catalog();self.assertGreaterEqual(len(icons),25)
        for key,info in icons.items():self.assertRegex(info['path'],r'^M[\d. ]',key);self.assertTrue(info['label'],key)
        brands=ROOT/'static'/'brands'
        for name in ('kaspersky','mcafee','norton','playstation','epson','bitdefender'):
            text=(brands/(name+'.svg')).read_text(encoding='utf-8');self.assertTrue(text.startswith('<svg'),name);self.assertNotIn('<script',text);self.assertIn('viewBox="0 0 24 24"',text)
        # No se inventan logotipos: Microsoft y ESET no tienen archivo hasta que administración suba el oficial.
        for name in ('microsoft','windows','eset'):self.assertFalse((brands/(name+'.svg')).exists(),name)

    def test_picker_keeps_search_filters_and_add_logic(self):
        source=(ROOT/'static'/'app.js').read_text(encoding='utf-8');picker=source[source.index('async function openCatalogPicker('):source.index('// Configuración → Catálogo de productos y servicios: alta')]
        for needed in ("normalize('NFD')","setTimeout(paint,110)","add.dataset.busy","'IVA por confirmar'","'Limpiar búsqueda y filtros'","catalogLogo(item,data.brand_logos","inQuote(item.id)","quoteMoney(item.price_cents)","await api('/api/catalog')"):self.assertIn(needed,picker)
        self.assertEqual(picker.count("api('/api/catalog')"),1)   # una sola carga: escribir no genera peticiones


if __name__=='__main__':unittest.main()
