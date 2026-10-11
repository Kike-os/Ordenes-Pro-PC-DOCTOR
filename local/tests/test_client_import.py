import base64
import io
import sys
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_app
import app
import client_import

# Datos ficticios: cédulas y RUC de prueba con dígito verificador válido.
CSV=('Listado de clientes de prueba;;;;;;;;\n'
     'CI/RUC;Razón Social;Nombre Comercial;Dirección;Teléfono;Correo;Ciudad;Parroquia;Cupo\n'
     '1710034065;PERSONA FICTICIA UNO;;Calle Falsa 123;991234567 / 022345678;UNO@EXAMPLE.INVALID;Cuenca;Bellavista;100\n'
     '0100000017;CLIENTE YA REGISTRADO;Comercial Ficticio;Otra dirección;0987654321;ya@example.invalid;Cuenca;;0\n'
     '1790016919001;EMPRESA FICTICIA S.A.;Ficticia;Av. Inventada 45;022345678;correo-malo;Quito;;500\n'
     '1710034065;PERSONA FICTICIA UNO REPETIDA;;;;;;;\n'
     '9999999999999;CONSUMIDOR FINAL;;;;;;;\n'
     ';;;Sin nombre;0991112223;;;;\n'
     'AB123456;EXTRANJERA FICTICIA;;;;;;;\n'
     ';SIN IDENTIFICACION FICTICIA;;;0991112224;;;;\n'
     '=1+1;FORMULA FICTICIA;;;;;;;\n').encode()


def xlsx(rows):
    def ref(column,row):return chr(65+column)+str(row)
    sheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join('<row r="%d">%s</row>'%(r+1,''.join('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'%(ref(c,r+1),value) for c,value in enumerate(row) if value)) for r,row in enumerate(rows))+'</sheetData></worksheet>'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as book:book.writestr('xl/worksheets/sheet1.xml',sheet)
    return out.getvalue()


class ClientImportTests(test_app.SecurityTests):
    def body(self,raw=CSV,**extra):
        return {'filename':'clientes-prueba.csv','content':base64.b64encode(raw).decode(),**extra}

    def seed(self):
        cookie,csrf=self.login()
        created=self.request('/api/client-registry',{k:v for k,v in self.order_data().items()} | {'name':'Cliente ficticio'},cookie=cookie,csrf=csrf)
        self.assertIn(created['status'],(201,409),created)
        return cookie,csrf

    def test_formats_and_number_cleanup(self):
        self.assertEqual(client_import.cell_text(1712345678.0),'1712345678')
        self.assertEqual(client_import.cell_text('9.91234567E8'),'991234567')
        self.assertEqual(client_import.normalize_identification('100000017')[:2],('0100000017','cedula'))
        self.assertEqual(client_import.normalize_phone('991234567'),'0991234567')
        self.assertEqual(client_import.normalize_phone('2345678'),'2345678')
        import xlrd
        self.assertTrue(xlrd.__version__.startswith('2.'))
        rows=[['Cédula','Nombres','Celular'],['1710034065','Persona Ficticia','0991234567']]
        self.assertEqual(client_import.read_rows(xlsx(rows)),rows)
        html=b'<html><table><tr><th>RUC</th><th>Cliente</th></tr><tr><td>1710034065</td><td>Persona Ficticia</td></tr></table></html>'
        self.assertEqual(client_import.read_rows(html),[['RUC','Cliente'],['1710034065','Persona Ficticia']])
        for bad in (b'',b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1corrupto',b'solo;texto\nsin;encabezados'):
            with self.assertRaises(client_import.ImportError_):
                client_import.detect(client_import.read_rows(bad))

    def test_preview_classifies_rows_and_writes_nothing(self):
        cookie,csrf=self.seed()
        with app.connect() as c:before=c.execute('SELECT COUNT(*) FROM clients').fetchone()[0]
        self.assertEqual(self.request('/api/clients/import/preview',self.body(),cookie=cookie)['status'],403)
        result=self.request('/api/clients/import/preview',self.body(),cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],200,result)
        view=result['body']
        self.assertEqual(view['header_row'],2)
        self.assertEqual(view['counts'],{'new':5,'duplicate':1,'repeated':1,'skipped':1,'error':1,'total':9,'needs_review':4,'with_warnings':4})
        self.assertIn('Cupo',view['unmapped'])
        first=view['new'][0]
        self.assertEqual((first['identification'],first['phone'],first['email'],first['city']),('1710034065','0991234567','uno@example.invalid','Cuenca'))
        self.assertEqual(view['duplicates'][0]['existing']['name'],'Cliente ficticio')
        self.assertTrue(any('Correo con formato inválido' in w for item in view['new'] for w in item['warnings']))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],before)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM client_import_batches').fetchone()[0],0)

    def test_commit_backs_up_keeps_existing_and_reports(self):
        cookie,csrf=self.seed()
        view=self.request('/api/clients/import/preview',self.body(),cookie=cookie,csrf=csrf)['body']
        with app.connect() as c:existing=dict(c.execute("SELECT * FROM clients WHERE identification='0100000017'").fetchone())
        self.assertEqual(self.request('/api/clients/import/commit',self.body(sha256='0'*64),cookie=cookie,csrf=csrf)['status'],400)
        with patch.object(app,'make_backup',side_effect=client_import.ImportError_('sin copia')):
            self.assertEqual(self.request('/api/clients/import/commit',self.body(sha256=view['sha256']),cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],1)
        done=self.request('/api/clients/import/commit',self.body(sha256=view['sha256'],merge=str(view['duplicates'][0]['row'])),cookie=cookie,csrf=csrf)
        self.assertEqual(done['status'],201,done)
        report=done['body']
        self.assertEqual({k:report[k] for k in ('total','imported','merged','duplicates','skipped','errors')},{'total':9,'imported':5,'merged':1,'duplicates':0,'skipped':2,'errors':1})
        self.assertTrue((app.DATA/report['backup']).is_file())
        with app.connect() as c:
            after=dict(c.execute("SELECT * FROM clients WHERE identification='0100000017'").fetchone())
            # La ficha existente no se sobrescribe: solo se completan campos que estaban vacíos.
            self.assertEqual({k:after[k] for k in ('name','phone','address','province_code')},{k:existing[k] for k in ('name','phone','address','province_code')})
            self.assertEqual((after['trade_name'],after['email']),('Comercial Ficticio','ya@example.invalid'))
            person=c.execute("SELECT * FROM clients WHERE identification='1710034065'").fetchone()
            self.assertEqual((person['name'],person['phone'],person['phone_secondary'],person['canton_code'],person['parish_code'],person['needs_review']),('PERSONA FICTICIA UNO','0991234567','022345678','0101','010101',0))
            company=c.execute("SELECT * FROM clients WHERE identification='1790016919001'").fetchone()
            self.assertEqual((company['client_type'],company['document_type'],company['email'],company['needs_review']),('empresa','ruc','',1))
            self.assertEqual(c.execute("SELECT document_type FROM clients WHERE identification='AB123456'").fetchone()[0],'pasaporte')
            self.assertIsNone(c.execute("SELECT identity_key FROM clients WHERE name='SIN IDENTIFICACION FICTICIA'").fetchone()[0])
            self.assertIn('"Cupo": "500"',c.execute('SELECT original FROM client_import_rows WHERE client_id=?',(company['id'],)).fetchone()[0])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
        again=self.request('/api/clients/import/commit',self.body(sha256=view['sha256']),cookie=cookie,csrf=csrf)['body']
        self.assertEqual((again['imported'],again['duplicates']),(0,7))
        csv_report=self.request('/api/clients/import-report.csv?batch='+str(report['batch']),cookie=cookie)
        self.assertEqual(csv_report['status'],200)
        self.assertIn('Importado',csv_report['body'])
        exported=self.request('/api/clients/export.csv',cookie=cookie)['body']
        self.assertIn('PERSONA FICTICIA UNO',exported)
        self.assertIn("'=1+1",exported)

    def test_search_filters_detail_and_permissions(self):
        cookie,csrf=self.seed()
        view=self.request('/api/clients/import/preview',self.body(),cookie=cookie,csrf=csrf)['body']
        self.request('/api/clients/import/commit',self.body(sha256=view['sha256']),cookie=cookie,csrf=csrf)
        find=lambda q:[r['name'] for r in self.request('/api/client-search?q='+q,cookie=cookie)['body']['rows']]
        self.assertEqual(find('uno%40example'),['PERSONA FICTICIA UNO'])
        self.assertEqual(find('022345678'),['EMPRESA FICTICIA S.A.','PERSONA FICTICIA UNO'])
        self.assertEqual(find('1790016919001'),['EMPRESA FICTICIA S.A.'])
        self.assertEqual(find('Ficticia%20S'),['EMPRESA FICTICIA S.A.'])
        self.assertEqual(find(''),[])
        listed=lambda query:self.request('/api/clients?'+query,cookie=cookie)['body']
        self.assertEqual(listed('filter=review')['total'],4)
        self.assertEqual(listed('type=empresa')['total'],1)
        self.assertEqual(listed('filter=imported')['total'],5)
        self.assertEqual(listed('filter=no_id')['total'],1)
        self.assertEqual(self.request('/api/clients?filter=otro',cookie=cookie)['status'],400)
        with app.connect() as c:
            pending=c.execute("SELECT id FROM clients WHERE identification='1790016919001'").fetchone()[0]
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico','tec@example.invalid','Técnico de prueba',?,'tecnico',1)",(self.hash,))
        blocked=self.request('/api/orders',dict(self.order_data({'request_key':'import-order-request-key-0001'}),client_id=str(pending)),cookie=cookie,csrf=csrf)
        self.assertEqual((blocked['status'],blocked['body'].get('incomplete_client')),(409,pending))
        tech=self.request('/api/login',{'login':'tecnico','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tech_csrf=self.request('/api/me',cookie=tech)['body']['user']['csrf']
        for path in ('/api/clients/export.csv','/api/clients/imports','/api/clients/import-report.csv?batch=1'):
            self.assertEqual(self.request(path,cookie=tech)['status'],403,path)
        self.assertEqual(self.request('/api/clients/import/preview',self.body(),cookie=tech,csrf=tech_csrf)['status'],403)
        self.assertEqual(self.request('/api/clients/export.csv')['status'],401)
        detail=self.request('/api/clients/'+str(pending),cookie=tech)['body']
        self.assertTrue(detail['can_edit']);self.assertEqual(detail['imported']['filename'],'clientes-prueba.csv');self.assertEqual(detail['orders'],[])
        fixed=self.order_data({'id':str(pending),'name':'EMPRESA FICTICIA S.A.','client_type':'empresa','document_type':'ruc','identification':'1790016919001','phone':'022345678','phone_secondary':'0991234567','notes':'Observación ficticia.'})
        self.assertEqual(self.request('/api/client-registry',fixed,cookie=tech,csrf=tech_csrf)['status'],200)
        with app.connect() as c:
            row=c.execute('SELECT needs_review,notes,phone_secondary FROM clients WHERE id=?',(pending,)).fetchone()
            self.assertEqual(tuple(row),(0,'Observación ficticia.','0991234567'))
        self.assertEqual(self.request('/api/client-registry',fixed,cookie=tech,csrf=tech_csrf)['status'],403)
        order=self.request('/api/orders',dict(self.order_data({'request_key':'import-order-request-key-0002'}),client_id=str(pending)),cookie=tech,csrf=tech_csrf)
        self.assertEqual(order['status'],201,order)
        history=self.request('/api/clients/'+str(pending),cookie=cookie)['body']['orders']
        self.assertEqual((len(history),history[0]['problem'],history[0]['total_cents']),(1,'No enciende',0))


for name in [name for name in dir(test_app.SecurityTests) if name.startswith('test_')]:
    setattr(ClientImportTests,name,None)
del test_app
