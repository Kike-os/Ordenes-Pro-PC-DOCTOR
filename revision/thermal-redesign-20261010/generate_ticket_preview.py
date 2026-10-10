import sys,json
from pathlib import Path
sys.path.insert(0,'local/tests')
import test_app,app
T=test_app.SecurityTests;T.setUpClass();t=T('test_password_is_salted_and_verified');t.setUp()
try:
 cookie,csrf=t.login()
 payload=t.order_data({'brand':'Lenovo','model':'ThinkPad T14','serial':'PCD-DEMO-001','accessories':'Cargador original y funda protectora.','physical_condition':'Rayones leves en la tapa. Pantalla y conectores sin daños visibles.','problem':'El equipo se apaga durante el trabajo y presenta lentitud al iniciar. Revisar temperatura y almacenamiento.','technical_access':'authorized','access_confirmed':True,'access_operating_system':True,'access_signed_in_tests':True})
 result=t.request('/api/orders',payload,cookie=cookie,csrf=csrf);assert result['status']==201,result
 oid=result['body']['id'];order=t.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
 from thermal_pdf import render_thermal
 pdf=render_thermal(dict(order,preview=True));Path('output/pdf/ticket-pcdoctor-vista-previa.pdf').write_bytes(pdf)
 Path('revision/thermal-redesign-20261010/expected-codes.json').write_text(json.dumps({'barcode':order['code'],'qr':order['qr_url']},indent=2))
 # Variantes de autorización y cadenas largas para comprobar que no se trunca contenido.
 from thermal_pdf import render_thermal
 for label,access in [('denied',{'decision':'denied','permissions':{},'recorded_at':order['received_at'],'operator':'Técnico de prueba'}),('historical',None)]:
  sample=dict(order,access_authorization=access,terms=None if label=='historical' else order['terms'])
  Path('tmp/pdfs/ticket-'+label+'.pdf').write_bytes(render_thermal(sample))
 sample=dict(order,client='Cliente de prueba con razón social extensa para comprobar ajuste de líneas y caracteres españoles: áéíóú, Ñ.',model='MODELOEXTENSOSINESPACIOS'*10,accessories='Accesorios recibidos y observaciones extensas. '*20,problem='Falla reportada por el cliente. '*35)
 Path('tmp/pdfs/ticket-long.pdf').write_bytes(render_thermal(sample))
finally:t.tearDown()
