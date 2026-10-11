import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_app
import app
import versioning


def release(version,kind='patch',**changes):
    return {'version':version,'date':'2026-01-02T10:00:00-05:00','type':kind,'status':'publicada','summary':'Versión ficticia de prueba.','changes':changes}


class VersionRulesTests(unittest.TestCase):
    def test_semantic_numbering(self):
        self.assertEqual(versioning.bump('1.0.0','patch'),'1.0.1')
        self.assertEqual(versioning.bump('1.0.9','minor'),'1.1.0')
        self.assertEqual(versioning.bump('1.4.2','major'),'2.0.0')
        self.assertGreater(versioning.parse('1.10.0'),versioning.parse('1.9.9'))
        for bad in ('1.0','v1.0.0','1.0.0-beta','01.0.0','',None):
            with self.assertRaises(versioning.RegistryError):versioning.parse(bad)
        with self.assertRaises(versioning.RegistryError):versioning.bump('1.0.0','hotfix')

    def test_shipped_registry_matches_changelog(self):
        registry=versioning.load()
        self.assertTrue(registry['releases'])
        versions=[versioning.parse(item['version']) for item in registry['releases']]
        self.assertEqual(versions,sorted(versions,reverse=True))
        self.assertEqual(versioning.CHANGELOG.read_text(encoding='utf-8'),versioning.changelog_text(registry))

    def test_publish_requires_pending_changes_and_keeps_history(self):
        registry=versioning.validate({'unreleased':{},'releases':[release('1.0.0','major',features=['Base ficticia.'])]})
        with self.assertRaises(versioning.RegistryError):versioning.publish(registry,'patch')
        registry['unreleased']['fixes'].append('Corrección ficticia.')
        updated=versioning.publish(registry,'patch','Resumen ficticio.',datetime(2026,3,4,5,6,tzinfo=versioning.ECUADOR))
        self.assertEqual([item['version'] for item in updated['releases']],['1.0.1','1.0.0'])
        self.assertEqual(updated['releases'][0]['date'],'2026-03-04T05:06:00-05:00')
        self.assertEqual(updated['releases'][0]['changes']['fixes'],['Corrección ficticia.'])
        self.assertFalse(any(updated['unreleased'].values()))
        self.assertEqual(updated['releases'][1],registry['releases'][0])
        text=versioning.changelog_text(updated)
        self.assertLess(text.index('## v1.0.1'),text.index('## v1.0.0'))
        self.assertIn('### Errores corregidos',text)

    def test_cli_preview_does_not_write_without_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            registry_path=Path(folder)/'releases.json';changelog_path=Path(folder)/'CHANGELOG.md'
            registry_path.write_text(json.dumps({'unreleased':{'fixes':['Corrección ficticia.']},'releases':[release('1.0.0','major')]}),encoding='utf-8')
            before=registry_path.read_text(encoding='utf-8')
            with patch.multiple(versioning,REGISTRY=registry_path,CHANGELOG=changelog_path),patch('sys.stdout',io.StringIO()):
                versioning.main(['publish','minor'])
                self.assertEqual(registry_path.read_text(encoding='utf-8'),before)
                self.assertFalse(changelog_path.exists())
                versioning.main(['publish','minor','--confirmar'])
                self.assertEqual(versioning.load()['releases'][0]['version'],'1.1.0')
                self.assertIn('## v1.1.0',changelog_path.read_text(encoding='utf-8'))

    def test_invalid_registry_is_rejected(self):
        for data in ({},{'releases':[release('1.0.0'),release('1.0.0')]},{'releases':[dict(release('1.0.0'),status='borrador')]},{'releases':[dict(release('1.0.0'),date='2026-01-02T10:00:00')]},{'releases':[release('1.0.0',fixes='texto')]}):
            with self.assertRaises(versioning.RegistryError):versioning.validate(data)


class VersionCheckTests(test_app.SecurityTests):
    def registry(self,*versions):
        return versioning.validate({'unreleased':{},'releases':[release(v,fixes=['Cambio ficticio '+v+'.']) for v in versions]})

    def test_overview_requires_session_and_shows_installed_version(self):
        self.assertEqual(self.request('/api/system')['status'],401)
        cookie,csrf=self.login()
        result=self.request('/api/system',cookie=cookie)
        self.assertEqual(result['status'],200)
        body=result['body']
        self.assertEqual(body['product'],'Órdenes Pro | PC-DOCTOR S.A.')
        self.assertEqual(body['installed'],body['releases'][0])
        self.assertEqual(body['installed']['version'],versioning.load()['releases'][0]['version'])
        self.assertEqual(set(body['categories']),{'features','improvements','fixes','security','performance'})

    def test_check_requires_csrf_and_reports_up_to_date_without_remote(self):
        cookie,csrf=self.login()
        self.assertEqual(self.request('/api/system/check',{},cookie=cookie)['status'],403)
        with patch.dict(app.os.environ,{'UPDATE_REGISTRY_URL':''}),patch.object(versioning,'urlopen') as remote:
            result=self.request('/api/system/check',{},cookie=cookie,csrf=csrf)
            remote.assert_not_called()
        self.assertEqual(result['status'],200)
        body=result['body']
        self.assertFalse(body['update_available'])
        self.assertEqual(body['source'],'local')
        self.assertEqual(body['message'],'Órdenes Pro está actualizado. Estás utilizando la última versión disponible.')
        self.assertFalse(body['can_update'])
        self.assertEqual(body['pending'],[])

    def test_check_compares_with_published_registry_without_installing(self):
        published=json.dumps(self.registry('1.2.0','1.1.0','1.0.0')).encode()
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):return False
        files=sorted(p.name for p in versioning.ROOT.iterdir())
        with patch.dict(app.os.environ,{'UPDATE_REGISTRY_URL':'https://example.invalid/releases.json'}),patch.object(versioning,'urlopen',side_effect=lambda *args,**kwargs:Response(published)):
            result=versioning.check(self.registry('1.0.0'))
            same=versioning.check(self.registry('1.2.0'))
        self.assertTrue(result['update_available'])
        self.assertEqual(result['source'],'remote')
        self.assertEqual([item['version'] for item in result['pending']],['1.2.0','1.1.0'])
        self.assertEqual(result['latest']['version'],'1.2.0')
        self.assertFalse(result['can_update'])
        self.assertTrue(result['update_note'])
        self.assertFalse(same['update_available'])
        self.assertEqual(files,sorted(p.name for p in versioning.ROOT.iterdir()))

    def test_available_update_reaches_notification_center_until_installed(self):
        cookie,csrf=self.login()
        newer=dict(release('99.0.0','major',features=['Función ficticia.']),summary='Versión ficticia posterior.')
        found={'installed':versioning.load()['releases'][0],'latest':newer,'update_available':True,'pending':[newer],'source':'remote','checked_at':'2026-01-02T10:00:00-05:00','message':'','can_update':False,'update_note':''}
        with patch.object(versioning,'check',return_value=found):
            self.assertEqual(self.request('/api/system/check',{},cookie=cookie,csrf=csrf)['status'],200)
        items=self.request('/api/notifications',cookie=cookie)['body']['items']
        update=[item for item in items if item['key']=='update:99.0.0']
        self.assertEqual(len(update),1)
        self.assertEqual((update[0]['title'],update[0]['href'],update[0]['read']),('Nueva actualización disponible: v99.0.0','#system',False))
        with patch.object(versioning,'check',return_value=dict(found,update_available=False,pending=[])):
            self.request('/api/system/check',{},cookie=cookie,csrf=csrf)
        self.assertFalse([item for item in self.request('/api/notifications',cookie=cookie)['body']['items'] if item['key'].startswith('update:')])

    def test_check_fails_closed_when_published_registry_is_unusable(self):
        cookie,csrf=self.login()
        with patch.dict(app.os.environ,{'UPDATE_REGISTRY_URL':'http://example.invalid/releases.json'}):
            self.assertEqual(self.request('/api/system/check',{},cookie=cookie,csrf=csrf)['status'],503)
        with patch.dict(app.os.environ,{'UPDATE_REGISTRY_URL':'https://example.invalid/releases.json'}),patch.object(versioning,'urlopen',side_effect=OSError('sin red')):
            result=self.request('/api/system/check',{},cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],503)
        self.assertNotIn('sin red',result['body']['error'])


# La batería heredada ya se ejecuta en test_app; aquí solo interesan las pruebas de versiones.
for name in [name for name in dir(test_app.SecurityTests) if name.startswith('test_')]:
    setattr(VersionCheckTests,name,None)
del test_app
