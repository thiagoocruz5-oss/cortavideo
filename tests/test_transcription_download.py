import io
import json
import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import wave
import app
import processing
import transcription_worker as worker


class WorkerTests(unittest.TestCase):
    def test_render_windows_bounded_and_contiguous(self):
        blocks = list(worker.windows(7200*16000,16000,seconds=56))
        self.assertEqual(len(blocks),129)
        self.assertEqual(blocks[-1][3],7200*16000)
        for a,b,c,d in blocks:
            self.assertLessEqual(b-a,60*16000)
            self.assertTrue(a<=c<d<=b)
        for first, second in zip(blocks,blocks[1:]):
            self.assertEqual(first[3],second[2])

    def test_one_model_per_video_progress_and_render_options(self):
        model=MagicMock()
        def transcribe(audio, **options):
            segment=SimpleNamespace(words=[SimpleNamespace(start=4,end=5,word='fala')])
            return iter([segment]),SimpleNamespace(language='pt')
        model.transcribe.side_effect=transcribe
        ctor=MagicMock(return_value=model)
        events=[]
        with processing.scratch_directory(Path(__file__).parent) as folder:
            wav=folder/'audio.wav'; output=folder/'out.json'
            with wave.open(str(wav),'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'))
                for _ in range(130): stream.writeframes(b'\0'*32000)
            with patch.dict('sys.modules',{'faster_whisper':SimpleNamespace(WhisperModel=ctor)}), \
                 patch.object(Path,'is_file',return_value=True), patch.object(worker,'low_memory',return_value=True), \
                 patch.object(worker,'write_progress',side_effect=lambda path,**state:events.append(state)):
                worker.transcribe_wav(wav,output,folder/'progress.json')
            rows=json.loads(output.read_text())
        ctor.assert_called_once()
        self.assertEqual(model.transcribe.call_count,3)
        for call in model.transcribe.call_args_list:
            self.assertLessEqual(len(call.args[0]),60*16000)
            self.assertEqual(call.kwargs['temperature'],0)
            self.assertEqual(call.kwargs['best_of'],1)
            self.assertTrue(call.kwargs['word_timestamps'])
        self.assertEqual(model.transcribe.call_args_list[1].kwargs['language'],'pt')
        self.assertEqual(events[-1]['completed'],3)
        self.assertEqual(events[-1]['blocks'],3)
        self.assertEqual(len(rows),3)
        self.assertTrue(rows[1]['start']>=56)

    def test_progress_file_is_complete_json(self):
        with processing.scratch_directory(Path(__file__).parent) as folder:
            file=folder/'state.json'
            for number in (1,2,3): worker.write_progress(file,block=number,blocks=3)
            self.assertEqual(json.loads(file.read_text()),{'block':3,'blocks':3})
            self.assertFalse(file.with_suffix('.tmp').exists())

    def test_parent_forwards_worker_progress_without_model_import(self):
        states=[]
        def child(args,**kwargs):
            Path(args[3]).write_text('[]')
            Path(args[4]).write_text(json.dumps({'message':'Transcrevendo bloco 2 de 3','block':2,'blocks':3}))
            kwargs['on_tick'](); kwargs['on_tick']()
        with processing.scratch_directory(Path(__file__).parent) as folder, \
             patch('processing.run'),patch('processing.run_process',side_effect=child):
            self.assertEqual(processing.transcribe(folder/'source.mp4',progress=lambda **s:states.append(s)),[])
        self.assertEqual(len(states),2)
        self.assertEqual(states[-1]['block'],2)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.scratch=processing.scratch_directory(Path(__file__).parent)
        self.root=self.scratch.__enter__().resolve()
        self.folder=self.root/('a'*32); self.folder.mkdir()
        self.name='b'*32+'.mp4'
        self.payload=bytes(range(256))*16384
        (self.folder/self.name).write_bytes(self.payload)
        self.data_patch=patch.object(app,'DATA',self.root);self.data_patch.start()
        self.server=app.LocalServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}/media/{self.folder.name}/{self.name}?download=1'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.data_patch.stop();self.scratch.__exit__(None,None,None)

    def test_attachment_head_full_range_resume_and_validator(self):
        with urlopen(Request(self.url,method='HEAD')) as r:
            self.assertEqual(r.headers['Content-Length'],str(len(self.payload)))
            self.assertIn('attachment',r.headers['Content-Disposition']);self.assertEqual(r.read(),b'')
            etag=r.headers['ETag']
        # Duas requisições reconstituem o arquivo sem duplicar bytes.
        with urlopen(Request(self.url,headers={'Range':'bytes=0-12345'})) as r: prefix=r.read()
        with urlopen(Request(self.url,headers={'Range':'bytes=12346-','If-Range':etag})) as r:
            self.assertEqual(r.status,206); self.assertEqual(prefix+r.read(),self.payload)
        with urlopen(Request(self.url,headers={'Range':'bytes=12346-','If-Range':'"old"'})) as r:
            self.assertEqual(r.status,200); self.assertEqual(r.read(),self.payload)
        self.assertTrue((self.folder/self.name).exists())

    def test_missing_file_and_invalid_range_have_complete_responses(self):
        for header in ['bytes=-0','bytes=999999999-','bytes=1-2,4-5','garbage=0-1']:
            with self.assertRaises(HTTPError) as caught:urlopen(Request(self.url,headers={'Range':header}))
            self.assertEqual(caught.exception.code,416)
            self.assertEqual(caught.exception.read(),b'')
        (self.folder/self.name).unlink()
        with self.assertRaises(HTTPError) as caught:urlopen(self.url)
        self.assertEqual(caught.exception.code,410)
        self.assertIn('message',json.load(caught.exception))

    def test_cleanup_cannot_remove_active_transfer(self):
        started=threading.Event();release=threading.Event()
        original=app.Handler.end_headers
        def headers(handler):
            original(handler)
            started.set();release.wait(5)
        os.utime(self.folder,(1,1))
        try:
            with patch.object(app.Handler,'end_headers',headers):
                response=urlopen(self.url)
                self.assertTrue(started.wait(2))
                app.cleanup_expired()
                self.assertTrue((self.folder/self.name).exists())
                release.set()
                self.assertEqual(response.read(),self.payload);response.close()
        finally: release.set()

    def test_interrupted_write_releases_lease_and_keeps_file(self):
        handler=object.__new__(app.Handler)
        handler.headers={};handler.command='GET';handler.connection=MagicMock()
        handler.send_response=MagicMock();handler.send_header=MagicMock();handler.end_headers=MagicMock()
        handler.wfile=MagicMock();handler.wfile.write.side_effect=BrokenPipeError('disconnected')
        handler.log_message=MagicMock()
        handler.file(self.folder/self.name,'video/mp4',True)
        self.assertNotIn(self.folder,app.ACTIVE_FILES)
        self.assertTrue((self.folder/self.name).exists())
        handler.log_message.assert_called_once()
        self.assertTrue(handler.close_connection)
    def test_client_disconnect_then_resume_has_exact_bytes(self):
        response=urlopen(self.url)
        etag=response.headers['ETag']
        prefix=response.read(12345)
        response.close()  # Simula conexão interrompida no cliente antes do fim.
        with urlopen(Request(self.url,headers={'Range':f'bytes={len(prefix)}-','If-Range':etag})) as resumed:
            self.assertEqual(resumed.status,206)
            self.assertEqual(prefix+resumed.read(),self.payload)



class ConnectionLimitTests(unittest.TestCase):
    def test_saturation_returns_retryable_503_instead_of_silent_close(self):
        server=object.__new__(app.LocalServer)
        server.request_slots=MagicMock();server.request_slots.acquire.return_value=False
        server.shutdown_request=MagicMock();connection=MagicMock()
        server.process_request(connection,('127.0.0.1',1234))
        response=connection.sendall.call_args.args[0]
        self.assertIn(b'503',response);self.assertIn(b'Retry-After: 3',response)
        server.shutdown_request.assert_called_once_with(connection)
