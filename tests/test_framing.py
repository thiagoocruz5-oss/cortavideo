import math
import unittest
from unittest.mock import patch
from pathlib import Path
import processing


class FramingTests(unittest.TestCase):
    def test_center_default_and_extremes(self):
        self.assertEqual(processing.framing_filter(), processing.framing_filter(.5))
        for p in [0, .25, .5, 1]:
            self.assertIn(f'round((iw-ow)*{float(p)})', processing.framing_filter(p))
        for p in [-1, 1.01, math.nan, math.inf]:
            with self.assertRaises(ValueError):
                processing.framing_filter(p)

    def test_export_position_reaches_crop_and_captions_follow_crop(self):
        with patch('processing.run') as run, patch.object(Path, 'write_text'):
            processing.export(Path('.'), [], 0, 30, True, 'test', .8)
        command = run.call_args.args[0]
        filters = command[command.index('-vf') + 1]
        self.assertIn('round((iw-ow)*0.8)', filters)
        self.assertTrue(filters.endswith(',ass=test.ass'))
