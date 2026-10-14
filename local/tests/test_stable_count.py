"""Contador estable de la interfaz: el texto se limita a «999+» sin alterar el valor real y la píldora tiene tamaño fijo."""
import json,re,shutil,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


class StableCountTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node no está disponible')
    def test_text_is_capped_and_real_value_is_kept(self):
        source=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
        helper=re.search(r'^const countText=.*$',source,re.M).group(0);component=re.search(r'^function stableCount\(.*$',source,re.M).group(0)
        script=("const el=(tag,text,cls)=>({tag,textContent:text,className:cls,dataset:{}});"+helper+component+
                "console.log(JSON.stringify([0,1,8,9,10,12,99,100,125,999,1000,25000,-3,'x'].map(v=>{const n=stableCount(v);return [countText(v),n.textContent,n.dataset.count,n.className];})))")
        out=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=30);self.assertEqual(out.returncode,0,out.stderr)
        rows=json.loads(out.stdout)
        self.assertEqual([row[0] for row in rows],['0','1','8','9','10','12','99','100','125','999','999+','999+','0','0'])
        self.assertEqual([row[1] for row in rows],[row[0] for row in rows])
        self.assertEqual([row[2] for row in rows][9:12],['999','1000','25000'])            # el valor real no se altera
        self.assertTrue(all(row[3]=='stable-count' for row in rows))

    def test_pill_and_history_button_have_fixed_size(self):
        css=(ROOT/'static'/'app.css').read_text(encoding='utf-8')
        pill=re.search(r'^\.stable-count\{([^}]*)\}',css,re.M).group(1)
        for rule in ('width:35px','min-width:35px','max-width:35px','height:23px','box-sizing:border-box','white-space:nowrap','font-variant-numeric:tabular-nums','flex:0 0 35px'):self.assertIn(rule,pill)
        self.assertRegex(css,r'button\[data-action=historial\]\{flex:0 0 146px;width:146px;min-width:146px;max-width:146px;')
        self.assertIn("stableCount(total,{className:'tracking-history-count'",(ROOT/'static'/'app.js').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
