import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402

LOCAL = 'http://127.0.0.1:8010'
CODESPACES = {'ORDENES_ENTORNO': 'codespaces', 'CODESPACE_NAME': 'demo-codespace-x1', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev'}
FORWARDED = 'https://demo-codespace-x1-8010.app.github.dev'


class CodespacesOriginTests(unittest.TestCase):
    def check(self, origin, env, expected=LOCAL):
        with patch.dict(app.os.environ, env, clear=False):
            for key in set(CODESPACES) | {'VERCEL'}:
                if key not in env:app.os.environ.pop(key, None)
            return app.allowed_request_origin(origin, expected)

    def test_local_aliases_still_allowed(self):
        self.assertTrue(self.check('http://localhost:8010', {}))
        self.assertTrue(self.check('http://127.0.0.1:8010', {}))
        self.assertFalse(self.check('http://evil.example', {}))

    def test_codespaces_forwarded_port_allowed_only_in_codespaces(self):
        self.assertTrue(self.check(FORWARDED, CODESPACES))
        self.assertFalse(self.check(FORWARDED, {}))
        self.assertFalse(self.check(FORWARDED, {k: v for k, v in CODESPACES.items() if k != 'ORDENES_ENTORNO'}))
        self.assertFalse(self.check(FORWARDED, {**CODESPACES, 'VERCEL': '1'}))

    def test_codespaces_rejects_other_names_ports_and_schemes(self):
        self.assertFalse(self.check('https://otro-codespace-8010.app.github.dev', CODESPACES))
        self.assertFalse(self.check('https://demo-codespace-x1-8011.app.github.dev', CODESPACES))
        self.assertFalse(self.check('http://demo-codespace-x1-8010.app.github.dev', CODESPACES))
        self.assertFalse(self.check(FORWARDED, {**CODESPACES, 'CODESPACE_NAME': 'mal/nombre'}))

    def test_public_app_url_unchanged(self):
        self.assertFalse(self.check(FORWARDED, CODESPACES, 'https://ordenes-pro.ecuadorpcdoctor.com'))
        self.assertTrue(self.check('https://ordenes-pro.ecuadorpcdoctor.com', CODESPACES, 'https://ordenes-pro.ecuadorpcdoctor.com'))


if __name__ == '__main__':
    unittest.main()
