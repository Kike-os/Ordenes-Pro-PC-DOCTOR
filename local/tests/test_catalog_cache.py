"""Imágenes del catálogo en caché: con la versión en la dirección (?v=fecha de la imagen) se guardan en la caché privada del navegador;
sin versión, y en cualquier otra respuesta, nada se guarda (no-store). La política se aplica a una sola respuesta. Base temporal."""
import io,json,unittest
from email.message import Message
import test_app
import app,wsgi_app

PNG=b'\x89PNG\r\n\x1a\n'+b'\x00'*64


class CatalogImageCacheTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login;request=test_app.SecurityTests.request

    def get_policy(self,path,cookie):
        handler=object.__new__(app.Handler);handler.path=path;handler.client_address=('127.0.0.1',12345);handler.headers=Message();handler.headers['Cookie']=cookie
        handler.rfile=io.BytesIO(b'');seen={}
        def reply(status,body,content_type=None,cookie=None,filename=None):seen.update(status=status,policy=getattr(handler,'cache_policy',None))
        handler.reply=reply;handler.do_GET();return seen

    def test_versioned_image_is_cached_privately_and_only_that_response(self):
        cookie,_=self.login()
        with app.connect() as c:
            item=c.execute("INSERT INTO catalog_items(code,name,category,price_cents,available,created_at,updated_at) VALUES ('LIC-CACHE','Licencia ficticia','licencia',1000,1,'2026-10-21T08:00:00','2026-10-21T08:00:00')").lastrowid
            c.execute("INSERT INTO catalog_images(item_id,mime,data,updated_at,updated_by) VALUES (?,?,?,?,1)",(item,'image/png',PNG,'2026-10-21T08:00:00-05:00'))
        versioned=self.get_policy('/api/catalog/%d/image?v=2026-10-21T08%%3A00%%3A00-05%%3A00'%item,cookie)
        self.assertEqual((versioned['status'],versioned['policy']),(200,'private, max-age=2592000, immutable'))
        self.assertIsNone(self.get_policy('/api/catalog/%d/image'%item,cookie)['policy'])
        self.assertIsNone(self.get_policy('/api/catalog/%d/image?v=<script>'%item,cookie)['policy'])

    def test_policy_is_reset_after_one_response_in_production_layer(self):
        handler=object.__new__(wsgi_app.WSGIHandler);handler.cache_policy='private, max-age=60'
        handler.reply(200,b'x','image/png');first=dict(handler.response_headers)['Cache-Control']
        handler.reply(200,{'ok':True});second=dict(handler.response_headers)['Cache-Control']
        self.assertEqual((first,second),('private, max-age=60','no-store'))


if __name__=='__main__':unittest.main()
