"""Foto de perfil: cada usuario la suya, solo imágenes reales PNG/JPG/WebP y con sesión para verla."""
import base64,unittest
import test_app
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

PNG=b'\x89PNG\r\n\x1a\n'+b'\x00'*300
JPG=b'\xff\xd8\xff\xe0'+b'\x00'*300+b'\xff\xd9'
WEBP=b'RIFF'+b'\x00\x00\x00\x00'+b'WEBP'+b'\x00'*300


class ProfilePhotoTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request

    def test_upload_replace_view_and_remove(self):
        cookie,csrf=self.login();send=lambda content:self.request('/api/profile/photo',{'data':base64.b64encode(content).decode()},cookie=cookie,csrf=csrf)
        self.assertEqual(self.request('/api/me',cookie=cookie)['body']['user']['photo'],'')
        self.assertEqual(self.request('/api/users/%d/photo'%self.uid,cookie=cookie)['status'],404)
        for content,kind in ((PNG,'image/png'),(WEBP,'image/webp'),(JPG,'image/jpeg')):
            saved=send(content);self.assertEqual(saved['status'],200,saved);self.assertTrue(saved['body']['photo'])
            with app.connect() as c:self.assertEqual(tuple(c.execute('SELECT mime,size FROM user_photos WHERE user_id=?',(self.uid,)).fetchone()),(kind,len(content)))
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM user_photos').fetchone()[0],1)
        self.assertEqual(self.request('/api/users/%d/photo'%self.uid,cookie=cookie)['body'],JPG)
        self.assertTrue(self.request('/api/me',cookie=cookie)['body']['user']['photo'])
        # Sin sesión no se ve; sin CSRF no se cambia.
        self.assertEqual(self.request('/api/users/%d/photo'%self.uid)['status'],401)
        self.assertEqual(self.request('/api/profile/photo',{'data':base64.b64encode(PNG).decode()},cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/profile/photo',{'action':'delete'},cookie=cookie,csrf=csrf)['body']['photo'],'')
        self.assertEqual(self.request('/api/users/%d/photo'%self.uid,cookie=cookie)['status'],404)

    def test_rejects_anything_that_is_not_a_real_image_or_is_too_large(self):
        cookie,csrf=self.login()
        for content in (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'+b' '*200,b'GIF89a'+b'\x00'*300,b'MZ'+b'\x00'*300,b'%PDF-1.4'+b'\x00'*300,b'\xff\xd8\xff'+b'\x00'*300,PNG[:50],PNG+b'\x00'*app.PROFILE_PHOTO_LIMIT):
            self.assertEqual(self.request('/api/profile/photo',{'data':base64.b64encode(content).decode()},cookie=cookie,csrf=csrf)['status'],400,content[:12])
        self.assertEqual(self.request('/api/profile/photo',{'data':'no es base64 !!'},cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM user_photos').fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
