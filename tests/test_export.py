import unittest
from pathlib import Path
from unittest.mock import patch
import processing


class ExportTests(unittest.TestCase):
    def command(self, captions=True, position=1):
        with patch('processing.run') as run, patch.object(Path, 'write_text'), patch.object(Path, 'unlink'):
            processing.export(Path('.'), [], 243.73, 293.26, captions, 'clip', position)
        run.assert_called_once()
        return run.call_args.args[0]

    def test_single_pass_seeks_before_input_and_preserves_fractional_duration(self):
        args = self.command()
        self.assertLess(args.index('-ss'), args.index('-i'))
        self.assertEqual(float(args[args.index('-ss') + 1]), 243.73)
        self.assertAlmostEqual(float(args[args.index('-t') + 1]), 49.53)
        self.assertEqual(args.count('-i'), 1)
        self.assertNotIn('-pass', args)

    def test_fast_encoder_has_bounded_threads_and_no_lookahead(self):
        args = self.command()
        self.assertEqual(args[args.index('-preset') + 1], 'veryfast')
        self.assertEqual(args[args.index('-tune') + 1], 'zerolatency')
        for i, arg in enumerate(args):
            if arg in ('-threads', '-filter_threads'):
                self.assertEqual(args[i + 1], '1')
        self.assertEqual(args[args.index('-crf') + 1], '22')

    def test_video_audio_and_subtitles_preserved(self):
        args = self.command()
        self.assertIn('0:a:0?', args)
        self.assertEqual(args[args.index('-c:a') + 1], 'aac')
        self.assertEqual(args[args.index('-c:v') + 1], 'libx264')
        self.assertEqual(args[args.index('-pix_fmt') + 1], 'yuv420p')
        self.assertEqual(args[args.index('-vf') + 1], processing.framing_filter(1) + ',ass=clip.ass')
        self.assertEqual(args[-1], 'clip.mp4')

    def test_caption_free_export_still_uses_selected_crop(self):
        args = self.command(False, 0)
        self.assertEqual(args[args.index('-vf') + 1], processing.framing_filter(0))

    def test_captions_shift_to_fractional_cut_origin(self):
        text = processing.ass_subtitles([{'start': 244.73, 'end': 246.73, 'text': 'Legenda'}], 243.73, 293.26)
        self.assertIn('0:00:01.00,0:00:03.00', text)
