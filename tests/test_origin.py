import unittest
import app
import test_api
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class OriginTests(unittest.TestCase):
    def test_render_https(self):
        self.assertTrue(app.origin_allowed('https://cortavideo.onrender.com', 'cortavideo.onrender.com'))
        self.assertTrue(app.origin_allowed('https://cortavideo.onrender.com', 'internal-proxy:10000'))

    def test_local_aliases_same_port(self):
        for origin in ['http://localhost:8001', 'http://127.0.0.1:8001']:
            for host in ['localhost:8001', '127.0.0.1:8001']:
                self.assertTrue(app.origin_allowed(origin, host))
        self.assertTrue(app.origin_allowed('http://localhost', '127.0.0.1:80'))
        self.assertTrue(app.origin_allowed(None, '127.0.0.1:8001'))

    def test_block_other_domains_and_malformed_origins(self):
        for origin in ['', 'null', 'https://evil.example',
                       'https://cortavideo.onrender.com.evil.example',
                       'https://cortavideo.onrender.com@evil.example',
                       'https://cortavideo.onrender.com:444',
                       'http://cortavideo.onrender.com',
                       'http://localhost:8001/path', 'http://localhost:8001?x=1',
                       'http://localhost:8001#x', 'http://user@localhost:8001',
                       'http://localhost:invalid', 'http://localhost:8002',
                       'http://[invalid', 'http://localhost:8001/']:
            with self.subTest(origin=origin):
                self.assertFalse(app.origin_allowed(origin, 'localhost:8001'))

    def test_host_cannot_authorize_arbitrary_origin(self):
        self.assertFalse(app.origin_allowed('http://evil.example', 'evil.example'))
        self.assertFalse(app.origin_allowed('http://localhost:8001', 'evil.example:8001'))


class OriginHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_api.ApiTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        test_api.ApiTests.tearDownClass()

    def test_allowed_origin_reaches_export_validation(self):
        port = test_api.ApiTests.server.server_port
        for origin in ['https://cortavideo.onrender.com', f'http://127.0.0.1:{port}', f'http://localhost:{port}']:
            with self.subTest(origin=origin), self.assertRaises(HTTPError) as error:
                urlopen(Request(test_api.ApiTests.base + '/api/export', data=b'{}', headers={'Origin': origin}))
            self.assertEqual(error.exception.code, 400)  # Pedido incompleto, não bloqueio de origem.

    def test_rejected_origin_blocks_upload_and_export_even_with_forwarded(self):
        for route in ['/api/upload', '/api/export']:
            with self.subTest(route=route), self.assertRaises(HTTPError) as error:
                urlopen(Request(test_api.ApiTests.base + route, data=b'{}', headers={
                    'Origin': 'https://evil.example', 'X-Forwarded-Host': 'evil.example',
                    'X-Forwarded-Proto': 'https'}))
            self.assertEqual(error.exception.code, 403)
