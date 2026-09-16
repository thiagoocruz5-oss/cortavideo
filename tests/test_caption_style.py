import unittest
import processing


class CaptionStyleTests(unittest.TestCase):
    def test_export_uses_same_lines_as_preview_and_explicit_resolution(self):
        segments = [{'start': 8, 'end': 15, 'text': 'Uma explicação com acentuação para testar a legenda final.'}]
        cues = processing.caption_cues(segments)
        ass = processing.ass_subtitles(segments, 10, 40)
        self.assertIn('PlayResX: 720', ass)
        self.assertIn('PlayResY: 1280', ass)
        self.assertIn('Arial,48', ass)
        for cue in cues:
            self.assertLessEqual(len(cue['text'].splitlines()), 2)
            self.assertIn(cue['text'].replace('\n', r'\N'), ass)
        self.assertIn('0:00:00.00', ass)

    def test_excludes_cues_outside_clip_and_ass_commands(self):
        s = [{'start': 2, 'end': 4, 'text': r'{\pos(0,0)}texto'}]
        self.assertNotIn('Dialogue:', processing.ass_subtitles(s, 10, 40))
        self.assertNotIn('{', processing.caption_cues(s)[0]['text'])
