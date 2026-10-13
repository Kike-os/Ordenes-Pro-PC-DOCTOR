"""Cédula y RUC ecuatorianos: reglas por tipo, mensajes específicos y paridad entre el servidor y el navegador. Datos ficticios."""
import json,shutil,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import reception

# (número, tipo declarado, fragmento del error esperado o '' si se acepta, ¿aviso no bloqueante?)
CASES=[
 ('1710034065','cedula','',False),('0100000017','cedula','',False),('0100000017','','',False),
 ('1710034066','cedula','no es válido',False),('9910034065','cedula','provincia',False),('0010034065','cedula','provincia',False),('1760034065','cedula','tercer dígito',False),
 ('171003406','cedula','exactamente 10',False),('17100340651','cedula','exactamente 10',False),('1710034065001','cedula','exactamente 10',False),('17100340a5','cedula','exactamente 10',False),('','cedula','exactamente 10',False),
 # RUC de persona natural: su cédula más el establecimiento.
 ('1710034065001','ruc','',False),('0100000017001','ruc','',False),('1710034065002','ruc','',False),
 ('1710034066001','ruc','cédula válida',False),('1710034065000','ruc','establecimiento',False),
 # RUC de sociedad (tercer dígito 9) y de entidad pública (6): reglas propias, no las de la cédula.
 ('1790016919001','ruc','',False),('1760001550001','ruc','',False),
 ('1790016918001','ruc','',True),('1760001560001','ruc','',True),('1790016919000','ruc','establecimiento',False),('1760001550000','ruc','establecimiento',False),
 ('1780016919001','ruc','ningún tipo de RUC',False),('1770016919001','ruc','ningún tipo de RUC',False),('9990016919001','ruc','provincia',False),
 ('1710034065','ruc','exactamente 13',False),('171003406500','ruc','exactamente 13',False),('17100340650011','ruc','exactamente 13',False),('1710034065-01','ruc','exactamente 13',False),
 ('12345','','10 dígitos para cédula o 13 para RUC',False),
]


class IdentificationTests(unittest.TestCase):
    def test_each_document_type_follows_its_own_rule(self):
        for number,kind,expected,notice in CASES:
            with self.subTest(number=number,kind=kind):
                error,warning=reception.document_check(number,kind)
                if expected:self.assertIn(expected,error)
                else:self.assertEqual(error,'')
                self.assertEqual(bool(warning),notice)
                # El aviso nunca bloquea; en modo estricto (restituir ceros al importar) sí cuenta como error.
                self.assertEqual(reception.document_error(number,kind),error);self.assertEqual(bool(reception.document_error(number,kind,strict=True)),bool(error or warning))

    def test_valid_cedula_keeps_leading_zeros_and_rejects_bad_check_digit(self):
        self.assertTrue(reception.valid_cedula('0100000017'));self.assertFalse(reception.valid_cedula('100000017'));self.assertFalse(reception.valid_cedula('0100000018'))

    @unittest.skipUnless(shutil.which('node'),'Node no está disponible')
    def test_browser_validator_matches_the_server(self):
        script=("const fs=require('fs'),vm=require('vm');const box={};vm.createContext(box);vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';this.check=documentCheck;',box);"
                "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(([n,k])=>{const r=box.check(n,k);return [r.error,r.notice];})));")
        out=subprocess.run(['node','-e',script,str(ROOT/'static'/'form-validation.js'),json.dumps([[n,k] for n,k,_,_ in CASES])],capture_output=True,text=True,timeout=30)
        self.assertEqual(out.returncode,0,out.stderr)
        self.assertEqual([tuple(row) for row in json.loads(out.stdout)],[reception.document_check(n,k) for n,k,_,_ in CASES])


if __name__=='__main__':unittest.main()
