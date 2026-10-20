"""Errores encontrados en la revisión general (20/10/2026). Datos ficticios."""
import ast,unittest
from pathlib import Path
import test_app
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class RegressionTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def test_adi_admin_panel_responds(self):
        # El panel de ADI fallaba: «adi_ai» se usaba antes de importarse en esa rama (UnboundLocalError, la conexión se cerraba sin respuesta).
        cookie,_=self.login()
        result=self.request('/api/adi/admin',cookie=cookie)
        self.assertEqual(result['status'],200,result['body']);self.assertIn('live',result['body']);self.assertIn('enabled',result['body'])

    def test_no_module_used_in_a_branch_without_its_local_import(self):
        # Un «import X» dentro de un método convierte X en variable local de todo el método: usarlo en otra rama sin importarlo falla.
        tree=ast.parse((Path(app.ROOT)/'app.py').read_text(encoding='utf-8'));problems=[]
        for cls in [n for n in tree.body if isinstance(n,ast.ClassDef)]:
            for fn in [n for n in cls.body if isinstance(n,ast.FunctionDef)]:
                parents={child:node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
                def chain(n):
                    out=[]
                    while n in parents:
                        n=parents[n]
                        if isinstance(n,(ast.If,ast.Try,ast.For,ast.While,ast.With,ast.ExceptHandler)):out.append(n)
                    return out[::-1]
                imports={}
                for n in ast.walk(fn):
                    if isinstance(n,(ast.Import,ast.ImportFrom)):
                        for alias in n.names:imports.setdefault((alias.asname or alias.name).split('.')[0],[]).append(n)
                for n in ast.walk(fn):
                    if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id in imports:
                        if not any(imp.lineno<n.lineno and chain(imp)==chain(n)[:len(chain(imp))] for imp in imports[n.id]):problems.append('%s:%d %s'%(fn.name,n.lineno,n.id))
        self.assertEqual(problems,[])


class LoginNoticeTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def test_intellectual_property_notice_below_the_button_without_unproven_claims(self):
        page=self.request('/login')['body'];page=page.decode() if isinstance(page,bytes) else page
        button=page.index('<span>Iniciar sesión</span>');notice=page.index('class="login-ip"');self.assertLess(button,notice)
        self.assertLess(page.index('</form>'),notice)  # fuera del formulario: no altera el envío
        for text in ('Software privado · Propiedad intelectual protegida','uso exclusivo de PC-DOCTOR S.A.','acceso no autorizado al código fuente','© 2026 PC-DOCTOR S.A. | Todos los derechos reservados.'):self.assertIn(text,page)
        block=page[notice:page.index('</aside>',notice)].lower()
        for claim in ('registrado','certificado','patente','iepi','senadi'):self.assertNotIn(claim,block)
        self.login()  # el inicio de sesión sigue funcionando


if __name__=='__main__':unittest.main()
