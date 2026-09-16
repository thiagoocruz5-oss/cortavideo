import os
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import preparar_modelo


class PrepareModelTests(unittest.TestCase):
    def run_preparation(self, complete, fails=False):
        model = MagicMock()
        if fails:
            model.side_effect = RuntimeError('invalid model')
        download = MagicMock()
        modules = {'faster_whisper': MagicMock(WhisperModel=model),
                   'faster_whisper.utils': MagicMock(download_model=download)}
        with patch.dict(os.environ, {'WHISPER_MODEL': 'base'}), patch.dict('sys.modules', modules), \
             patch.object(Path, 'mkdir'), patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'unlink') as remove, patch.object(Path, 'write_text') as write, \
             patch('preparar_modelo.model_complete', side_effect=complete):
            if fails or not complete[-1]:
                with self.assertRaises(RuntimeError):
                    preparar_modelo.main()
                write.assert_not_called()
            else:
                preparar_modelo.main()
                write.assert_called_once_with('base', encoding='utf-8')
            remove.assert_called_once()
        return model, download

    def test_fresh_deploy_downloads_then_validates_offline(self):
        model, download = self.run_preparation([False, True])
        download.assert_called_once()
        self.assertTrue(model.call_args.kwargs['local_files_only'])
        self.assertEqual(model.call_args.kwargs['compute_type'], 'int8')

    def test_existing_files_skip_network_but_are_validated(self):
        model, download = self.run_preparation([True, True])
        download.assert_not_called()
        model.assert_called_once()

    def test_failed_validation_does_not_mark_ready(self):
        self.run_preparation([True, True], fails=True)

    def test_incomplete_download_fails_build(self):
        model, _ = self.run_preparation([False, False])
        model.assert_not_called()
