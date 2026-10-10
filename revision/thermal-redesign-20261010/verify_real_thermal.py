import sys,json,subprocess
from pathlib import Path
sys.path.insert(0,'local')
import app,service_terms,technical_access
from thermal_pdf import render_thermal
with app.connect() as c:
 row=c.execute('SELECT o.*,d.category type,d.brand,d.model,d.serial,c.name client,c.identification,c.document_type,c.phone,s.label status_label FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id JOIN statuses s ON s.code=o.status ORDER BY o.id LIMIT 1').fetchone()
 order=dict(row)
 if row['reception_snapshot']:order.update(json.loads(row['reception_snapshot']))
 service_terms.attach(c,order);technical_access.attach(c,order)
 Path('tmp/pdfs/real-ticket.pdf').write_bytes(render_thermal(order));Path('tmp/pdfs/real-ticket.pdf').chmod(0o600)
subprocess.run(['pdftoppm','-r','203','-png','-singlefile','tmp/pdfs/real-ticket.pdf','tmp/pdfs/real-ticket'],check=True)
result=subprocess.run(['zbarimg','--quiet','tmp/pdfs/real-ticket.png'],capture_output=True,text=True,check=True).stdout
assert 'QR-Code:'+order['qr_url'] in result and 'CODE-128:'+order['code'] in result
assert order['access_authorization'] is None
Path('revision/thermal-redesign-20261010/real-ticket-checks.json').write_text(json.dumps({'real_order_rendered':True,'qr_destination_unchanged':True,'barcode_matches_order':True,'legacy_authorization_not_invented':True},indent=2))
print('Ticket de orden real: QR y Code 128 correctos; autorización histórica no inventada.')
