import unittest
import processing


class ProcessingTests(unittest.TestCase):
    def test_suggestions_within_duration_and_low_overlap(self):
        segments = [{'start': i, 'end': i+5, 'text': 'Um trecho de fala completo.'} for i in range(0, 175, 5)]
        clips = processing.suggest(segments, 180)
        self.assertTrue(clips)
        for c in clips:
            self.assertTrue(0 <= c['start'] < c['end'] <= 180)
            self.assertTrue(30 <= c['end']-c['start'] <= 60)
        for a, b in zip(clips, clips[1:]):
            self.assertLess(max(0, a['end']-b['start']), 15)

    def test_silent_video(self):
        self.assertEqual(processing.suggest([], 30)[0]['end'], 30)

    def test_caption_clamps_and_shifts_timestamps(self):
        result = processing.subtitles([{'start': 8, 'end': 14, 'text': 'Teste'}], 10, 12)
        self.assertIn('00:00:00,000 --> 00:00:02,000', result)
        self.assertIn('Teste', result)

    def test_captions_outside_cut_excluded(self):
        self.assertEqual(processing.subtitles([{'start': 1, 'end': 2, 'text': 'fora'}], 10, 40), '')

    def test_timestamp_rounding(self):
        self.assertEqual(processing.stamp(59.9999), '00:01:00,000')


if __name__ == '__main__':
    unittest.main()
