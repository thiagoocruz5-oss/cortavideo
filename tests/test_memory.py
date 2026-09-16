import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, MagicMock
import app
import processing
import process_runner
from runtime_config import model_name
from transcription_worker import windows


class MemoryTests(unittest.TestCase):
    def test_windows_are_bounded_with_nonoverlapping_ownership(self):
        total, rate = 7200 * 16000, 16000
        blocks = list(windows(total, rate))
        self.assertEqual(blocks[0][2], 0)
        self.assertEqual(blocks[-1][3], total)
        for first, last, a, b in blocks:
            self.assertLessEqual(last-first, 32*rate)
            self.assertTrue(first <= a < b <= last <= total)
        for previous, following in zip(blocks, blocks[1:]):
            self.assertEqual(previous[3], following[2])

    def test_model_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(model_name(), 'base')
        with patch.dict(os.environ, {'RENDER': 'true'}, clear=True):
            self.assertEqual(model_name(), 'tiny')

    def test_task_releases_slot_after_error(self):
        slot = MagicMock()
        with patch.object(app, 'HEAVY_SLOT', slot):
            with self.assertRaises(ValueError):
                app.guarded_task(lambda: (_ for _ in ()).throw(ValueError()))
        slot.release.assert_called_once()

    def test_timeout_kills_and_reaps_child(self):
        child = MagicMock()
        child.wait.side_effect = [subprocess.TimeoutExpired('worker', 1), 0]
        child.poll.return_value = None
        with patch('process_runner.subprocess.Popen', return_value=child), patch('process_runner.subprocess.run'), \
             patch('process_runner.tempfile.TemporaryFile', side_effect=lambda: io.BytesIO()):
            with self.assertRaises(RuntimeError):
                process_runner.run_process(['worker'], timeout=1)
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_count, 2)
        self.assertNotIn(child, process_runner.ACTIVE)

    def test_extract_completes_before_model_process_and_cleanup_on_failure(self):
        scratch = MagicMock()
        scratch.__enter__.return_value = 'scratch'
        calls = []
        def extract(*a, **kw): calls.append('ffmpeg')
        def worker(*a, **kw):
            calls.append('model')
            raise RuntimeError('worker failed')
        with patch('processing.scratch_directory', return_value=scratch), \
             patch('processing.run', side_effect=extract), patch('processing.run_process', side_effect=worker):
            with self.assertRaises(RuntimeError):
                processing.transcribe('source.mp4')
        self.assertEqual(calls, ['ffmpeg', 'model'])
        scratch.__exit__.assert_called_once()

    def test_export_error_removes_partial_mp4_and_subtitle(self):
        with patch('processing.run', side_effect=RuntimeError('failed')), \
             patch.object(Path, 'write_text'), patch.object(Path, 'unlink') as unlink:
            with self.assertRaises(RuntimeError):
                processing.export(Path('.'), [], 0, 30, True, 'broken')
        self.assertEqual(unlink.call_count, 2)

    def test_render_loads_transcript_only_when_captions_enabled(self):
        with patch('app.load_segments') as load, patch('processing.export', return_value='ok.mp4'), patch('app.update'):
            app.render('export', 'source', 0, 30, False)
        load.assert_not_called()

    def upload_handler(self, stream, length):
        handler = object.__new__(app.Handler)
        handler.headers = {'Content-Length': str(length)}
        handler.path = '/api/upload'
        handler.connection = MagicMock()
        handler.rfile = stream
        handler.json = MagicMock()
        return handler

    def test_upload_streams_in_bounded_reads_before_scheduling(self):
        stream = MagicMock()
        stream.read.side_effect = [b'x' * 1048576, b'y']
        handler = self.upload_handler(stream, 1048577)
        with patch.object(app, 'JOBS', {}), patch.object(app, 'HEAVY_SLOT') as slot, \
             patch.object(app.POOL, 'submit') as submit, patch('app.binaries.health', return_value={'ffmpeg': True}), \
             patch.object(Path, 'mkdir'), patch.object(Path, 'open', return_value=MagicMock()):
            handler.do_POST()
        self.assertEqual([c.args[0] for c in stream.read.call_args_list], [1048576, 1])
        self.assertEqual(submit.call_args.args[:2], (app.guarded_task, app.analyze))
        slot.release.assert_not_called()  # Posse transferida ao worker.
        self.assertEqual(handler.json.call_args.args[1], 202)

    def test_incomplete_upload_cleans_file_and_releases_slot(self):
        handler = self.upload_handler(io.BytesIO(b''), 20)
        with patch.object(app, 'HEAVY_SLOT') as slot, patch.object(app.POOL, 'submit') as submit, \
             patch('app.binaries.health', return_value={'ffmpeg': True}), patch.object(Path, 'mkdir'), \
             patch.object(Path, 'open', return_value=MagicMock()), patch('app.shutil.rmtree') as cleanup:
            handler.do_POST()
        slot.release.assert_called_once()
        cleanup.assert_called_once()
        submit.assert_not_called()
        self.assertEqual(handler.json.call_args.args[1], 400)

    def test_busy_upload_is_not_read_or_scheduled(self):
        handler = self.upload_handler(MagicMock(), 20)
        with patch.object(app, 'HEAVY_SLOT') as slot, patch.object(app.POOL, 'submit') as submit, \
             patch('app.binaries.health', return_value={'ffmpeg': True}):
            slot.acquire.return_value = False
            handler.do_POST()
        handler.rfile.read.assert_not_called()
        submit.assert_not_called()
        self.assertEqual(handler.json.call_args.args[1], 429)
