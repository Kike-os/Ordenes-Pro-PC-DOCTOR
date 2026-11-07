"""Comprobación de actualizaciones (1.5.253): el registro publicado de versiones crece con cada versión. Un registro de más de 256 KB (el límite
anterior, superado en 1.5.252, que dejaba el panel en «Error de comprobación») se lee bien; uno desmedido sigue rechazándose; y el registro del
proyecto avisa con tiempo antes de acercarse al límite. Sin red: la descarga se simula."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import versioning


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def registry_of(size):
    """El registro real del proyecto, rellenado con espacios (JSON válido) hasta `size` bytes."""
    raw = (Path(versioning.__file__).parent / 'data' / 'releases.json').read_bytes().rstrip()
    return raw[:-1] + b' ' * max(0, size - len(raw)) + raw[-1:]


class RegistryFetchTests(unittest.TestCase):
    def test_large_published_registry_is_read(self):
        for size in (263157, 600000, versioning.MAX_REGISTRY_BYTES - 10):
            raw = registry_of(size)
            with patch.object(versioning, 'urlopen', return_value=_Response(raw)):
                got = versioning.fetch_published('https://example.invalid/releases.json')
            self.assertEqual(got['releases'][0]['version'], versioning.load()['releases'][0]['version'], size)

    def test_oversized_or_insecure_registry_is_rejected(self):
        with patch.object(versioning, 'urlopen', return_value=_Response(b'{' + b' ' * (versioning.MAX_REGISTRY_BYTES + 5) + b'}')):
            with self.assertRaises(versioning.RegistryError):
                versioning.fetch_published('https://example.invalid/releases.json')
        with self.assertRaises(versioning.RegistryError):
            versioning.fetch_published('http://example.invalid/releases.json')

    def test_check_reports_up_to_date_with_the_real_registry_size(self):
        raw = (Path(versioning.__file__).parent / 'data' / 'releases.json').read_bytes()
        with patch.object(versioning, 'registry_url', return_value='https://example.invalid/releases.json'), patch.object(versioning, 'urlopen', return_value=_Response(raw)):
            outcome = versioning.check()
        self.assertFalse(outcome['update_available']);self.assertEqual(outcome['source'], 'remote')

    def test_project_registry_keeps_a_wide_margin(self):
        size = (Path(versioning.__file__).parent / 'data' / 'releases.json').stat().st_size
        self.assertLess(size, versioning.MAX_REGISTRY_BYTES // 2, 'El registro de versiones se acerca al límite de descarga: revisa MAX_REGISTRY_BYTES.')


if __name__ == '__main__':
    unittest.main()
