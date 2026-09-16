import json
import threading
import socket
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import app


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_home(self):
        with urlopen(self.base) as response:
            self.assertIn('CortaVídeo', response.read().decode())

    def test_head_matches_get_headers_without_body(self):
        for route in ['/', '/app.js', '/style.css', '/api/health', '/api/jobs/missing', '/missing']:
            with self.subTest(route=route):
                try:
                    get = urlopen(self.base + route)
                except HTTPError as error:
                    get = error
                with get:
                    status = get.code
                    content_type = get.headers['Content-Type']
                    content_length = get.headers['Content-Length']
                    self.assertTrue(get.read())
                # Lê os bytes reais: HTTPResponse.read() ocultaria um corpo HEAD indevido.
                with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=5) as connection:
                    connection.sendall(f'HEAD {route} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n'.encode())
                    response = b''
                    while chunk := connection.recv(65536):
                        response += chunk
                headers, body = response.split(b'\r\n\r\n', 1)
                self.assertEqual(body, b'')
                self.assertEqual(int(headers.split(b' ')[1]), status)
                self.assertIn(f'Content-Type: {content_type}'.encode(), headers)
                self.assertIn(f'Content-Length: {content_length}'.encode(), headers)

    def test_head_ignores_range(self):
        with urlopen(Request(self.base + '/app.js', method='HEAD', headers={'Range': 'bytes=0-9'})) as response:
            self.assertEqual(response.status, 200)
            self.assertIsNone(response.headers.get('Content-Range'))
            self.assertEqual(response.read(), b'')

    def test_unknown_job(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + '/api/jobs/missing')
        self.assertEqual(error.exception.code, 404)

    def test_reject_invalid_clip_and_nan(self):
        app.JOBS['test'] = {'status': 'ready', 'duration': 100, 'segments': []}
        for start, end in [(0, 20), (-1, 40), (50, 110), (0, float('nan'))]:
            body = json.dumps({'id': 'test', 'start': start, 'end': end}).encode()
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base + '/api/export', data=body, headers={'Content-Type': 'application/json'}))
            self.assertEqual(error.exception.code, 400)
        del app.JOBS['test']

    def test_block_cross_origin(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.base + '/api/export', data=b'{}', headers={'Origin': 'https://unrelated.example'}))
        self.assertEqual(error.exception.code, 403)

    def test_static_range(self):
        with urlopen(Request(self.base + '/app.js', headers={'Range': 'bytes=0-9'})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(len(response.read()), 10)
