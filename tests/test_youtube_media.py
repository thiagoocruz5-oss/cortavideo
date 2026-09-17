"""Integração offline: transporte YouTube simulado, servidor e FFmpeg reais."""
import json
import os
import shutil
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
import app
import processing
from test_youtube import URL, metadata
from youtube_worker import validate_metadata


@unittest.skipUnless(os.getenv('CORTAVIDEO_MEDIA_TESTS') == '1', 'FFmpeg real opt-in')
class YoutubeMediaTests(unittest.TestCase):
    def test_import_preview_cut_export_download_and_reuse(self):
        with processing.scratch_directory(Path(__file__).parent) as temporary:
            root=temporary.resolve();data=root/'data';data.mkdir()
            processing.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:s=640x360:r=5',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','31','-threads','1',
                '-c:v','libx264','-c:a','aac',str(root/'fixture.mp4')])
            processing.run(['ffmpeg','-y','-v','error','-i',str(root/'fixture.mp4'),'-vn','-c:a','copy',str(root/'fixture.m4a')])
            processing.run(['ffmpeg','-y','-v','error','-i',str(root/'fixture.mp4'),'-an','-c:v','copy',str(root/'fixture-video.mp4')])
            def downloaded(args,**kwargs):
                folder=Path(args[-1]);shutil.copyfile(root/'fixture-video.mp4',folder/'video.mp4');shutil.copyfile(root/'fixture.m4a',folder/'audio.m4a')
                info=validate_metadata(metadata());info['duration']=31
                (folder/'import-result.json').write_text(json.dumps(info))
                (folder/'import-progress.json').write_text(json.dumps({'message':'Baixando vídeo… 100%',**info}))
                kwargs['on_tick']()
            def transcribed(path,progress):
                self.assertEqual(path.name,'audio.m4a');self.assertTrue(path.is_file())
                progress(message='Transcrevendo bloco 1 de 1')
                return [{'start':0,'end':31,'text':'Legenda da mídia importada'}]
            with patch.object(app,'DATA',data),patch.object(app,'JOBS',{}),patch('youtube_import.run_process',side_effect=downloaded) as downloader, \
                 patch('processing.transcribe',side_effect=transcribed):
                server=app.LocalServer(('127.0.0.1',0),app.Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                def api(route,payload=None):
                    body=json.dumps(payload).encode() if payload is not None else None
                    with urlopen(Request(base+route,data=body,headers={'Content-Type':'application/json'}),timeout=20) as response:return json.load(response)
                def ready(key):
                    deadline=time.monotonic()+60
                    while time.monotonic()<deadline:
                        job=api('/api/jobs/'+key)
                        self.assertNotEqual(job['status'],'error',job)
                        if job['status']=='ready':return job
                        time.sleep(.1)
                    self.fail('Timeout da integração')
                try:
                    key=api('/api/import/youtube',{'url':URL})['id'];job=ready(key)
                    self.assertEqual(job['title'],'Título de teste');self.assertTrue(job['segments']);self.assertTrue(job['suggestions'])
                    with urlopen(base+f'/media/{key}/source.mp4') as preview:
                        self.assertEqual(preview.headers['Content-Type'],'video/mp4');self.assertTrue(preview.read(100))
                    self.assertFalse((data/key/'audio.m4a').exists());self.assertFalse((data/key/'video.mp4').exists())
                    export=api('/api/export',{'id':key,'start':.25,'end':30.25,'captions':True,'position':.8})['id']
                    result=ready(export)
                    with urlopen(base+result['download_url']) as response:
                        self.assertIn('attachment',response.headers['Content-Disposition'])
                        body=response.read();self.assertEqual(len(body),int(response.headers['Content-Length']))
                    info=json.loads(processing.run(['ffprobe','-v','error','-show_streams','-of','json',str(data/key/(export+'.mp4'))]))
                    video=next(s for s in info['streams'] if s['codec_type']=='video')
                    self.assertEqual((video['width'],video['height']),(720,1280));self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
                    reused=api('/api/import/youtube',{'url':URL});self.assertEqual(reused['id'],key);self.assertTrue(reused['reused'])
                    downloader.assert_called_once()
                finally:
                    server.shutdown();server.server_close();thread.join()
