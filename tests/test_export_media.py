"""Validação real opcional: CORTAVIDEO_MEDIA_TESTS=1 antes do unittest."""
import json
import os
from pathlib import Path
import subprocess
import unittest
import binaries
import processing


@unittest.skipUnless(os.getenv('CORTAVIDEO_MEDIA_TESTS') == '1', 'Teste real FFmpeg opt-in')
class ExportMediaTests(unittest.TestCase):
    def test_export_extremes_center_audio_captions_and_cleanup(self):
        ffmpeg = binaries.require('ffmpeg')
        with processing.scratch_directory(Path(__file__).resolve().parent) as folder:
            w, h = 640, 360
            pattern = folder / 'pattern.ppm'
            pattern.write_bytes(f'P6\n{w} {h}\n255\n'.encode() + bytes(c for y in range(h) for x in range(w) for c in (round(x*255/(w-1)),60,round(y*255/(h-1)))))
            processing.run(['ffmpeg','-y','-v','error','-loop','1','-framerate','30','-i',str(pattern),
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','35','-threads','1',
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(folder/'source.mp4')])
            for position in (0, .5, 1):
                output = processing.export(folder,[{'start':2.25,'end':32.25,'text':'Legenda visível'}],2.25,32.25,True,f'cut-{position}',position)
                info = json.loads(processing.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(folder/output)]))
                video = next(s for s in info['streams'] if s['codec_type']=='video')
                self.assertEqual((video['width'],video['height'],video['codec_name']),(720,1280,'h264'))
                self.assertTrue(any(s['codec_type']=='audio' and s['codec_name']=='aac' for s in info['streams']))
                self.assertAlmostEqual(float(info['format']['duration']),30,delta=.25)
                self.assertAlmostEqual(float(video.get('start_time',0)),0,delta=.05)
                raw = subprocess.check_output([ffmpeg,'-v','error','-ss','1','-i',str(folder/output),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                # Geometria independente do CSS cover. Fora da área de legendas.
                scale=max(720/w,1280/h)
                for x,y in [(10,100),(360,640),(709,700)]:
                    i=(y*720+x)*3
                    expected=(x+(w*scale-720)*position)/(w*scale)*255
                    self.assertLess(abs(raw[i]-expected),7)
                white=sum(1 for i in range(900*720*3,1100*720*3,3) if min(raw[i:i+3])>230)
                self.assertGreater(white,100, 'Legenda deve estar gravada na área inferior do quadro')
                self.assertFalse((folder/f'cut-{position}.ass').exists())

