import os
from pathlib import Path
import unittest
from unittest.mock import patch
import binaries
import processing


class BinaryTests(unittest.TestCase):
    def test_refreshed_path_is_used(self):
        with patch.dict(os.environ, {}, clear=True), patch('binaries.search_path', return_value='updated-path'), patch('binaries.shutil.which', return_value=__file__) as which:
            self.assertEqual(binaries.locate('ffmpeg'), str(Path(__file__).resolve()))
            which.assert_called_once_with('ffmpeg', path='updated-path')

    def test_explicit_path_with_spaces(self):
        executable = Path('C:/Video Tools/ffmpeg.exe')
        with patch.dict(os.environ, {'FFMPEG_PATH': str(executable)}), patch('binaries.Path.is_file', return_value=True):
            self.assertEqual(binaries.require('ffmpeg'), str(executable.resolve()))

    def test_invalid_override_is_not_reported_as_installed(self):
        with patch.dict(os.environ, {'FFMPEG_PATH': '/missing/ffmpeg.exe'}):
            self.assertFalse(binaries.health()['ffmpeg'])

    def test_processing_uses_resolved_executable(self):
        with patch('binaries.require', return_value='C:/Video Tools/ffmpeg.exe'), patch('processing.run_process', return_value='ok') as run:
            self.assertEqual(processing.run(['ffmpeg', '-version']), 'ok')
            self.assertEqual(run.call_args.args[0], ['C:/Video Tools/ffmpeg.exe', '-version'])
