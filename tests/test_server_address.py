import os
import unittest
from unittest.mock import patch
import app


class ServerAddressTests(unittest.TestCase):
    def test_local_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(app.server_address(), ('127.0.0.1', 8001))

    def test_local_custom_port(self):
        with patch.dict(os.environ, {'CORTAVIDEO_PORT': '8100'}, clear=True):
            self.assertEqual(app.server_address(), ('127.0.0.1', 8100))

    def test_render_port_takes_precedence(self):
        with patch.dict(os.environ, {'PORT': '10000', 'CORTAVIDEO_PORT': '8100'}, clear=True):
            self.assertEqual(app.server_address(), ('0.0.0.0', 10000))

    def test_empty_port_keeps_local_binding(self):
        with patch.dict(os.environ, {'PORT': ''}, clear=True):
            self.assertEqual(app.server_address(), ('127.0.0.1', 8001))

    def test_invalid_ports_fail(self):
        for value in ['abc', '0', '-1', '65536']:
            with patch.dict(os.environ, {'PORT': value}, clear=True):
                with self.assertRaises(ValueError):
                    app.server_address()
