import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import app
import processing
import youtube_import as importer
import youtube_worker as worker

URL='https://www.youtube.com/watch?v=BaW_jenozKc'

def metadata():
    def fmt(id,ext,vcodec,acodec,w=None,h=None,**extra):
        return dict(format_id=id,ext=ext,vcodec=vcodec,acodec=acodec,width=w,height=h,
                    url='https://rr1.googlevideo.com/videoplayback',protocol='https',**extra)
    return {'id':'BaW_jenozKc','title':'Título de teste','duration':60,'extractor':'youtube','extractor_key':'Youtube',
            'webpage_url':URL,'formats':[
                fmt('v','mp4','avc1.640028','none',1920,1080,fps=30),
                fmt('4k','mp4','avc1.640028','none',3840,2160,fps=30),
                fmt('a','m4a','none','mp4a.40.2',abr=128)]}


class YoutubeValidationTests(unittest.TestCase):
    def test_supported_links_are_canonicalized_to_single_video(self):
        for url in [URL, 'https://youtu.be/BaW_jenozKc?t=30', 'https://m.youtube.com/watch?v=BaW_jenozKc&list=abc',
                    'https://www.youtube.com/shorts/BaW_jenozKc', 'http://youtube.com/embed/BaW_jenozKc']:
            self.assertEqual(importer.canonical_url(url),URL)

    def test_invalid_hosts_paths_ports_credentials_and_internal_urls(self):
        for url in [None, [], '', 'file:///source.mp4','http://127.0.0.1/x','http://[::1]/','https://youtube.com.evil.test/watch?v=BaW_jenozKc',
                    'https://evil.test/?url='+URL, 'https://youtube.com@evil.test/watch?v=BaW_jenozKc',
                    'https://youtube.com:443/watch?v=BaW_jenozKc','https://youtube.com/redirect?q=http://localhost',
                    'https://youtube.com/playlist?list=abc','https://youtube.com/watch?v=short',
                    URL+'&v=abcdefghijk','https://youtu.be/BaW_jenozKc/extra',URL+'\n']:
            with self.subTest(url=url),self.assertRaises(ValueError):importer.canonical_url(url)

    def test_network_guard_blocks_redirects_and_private_connections(self):
        worker.network_guard('urllib.Request',('https://rr1.googlevideo.com/video',))
        worker.network_guard('socket.connect',(None,('8.8.8.8',443)))
        for url in ['http://www.youtube.com/','https://127.0.0.1/','https://youtube.com.evil.test/', 'file:///tmp/test']:
            with self.assertRaises(ValueError):worker.network_guard('urllib.Request',(url,))
        for host in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','192.168.0.1','example.com']:
            with self.assertRaises(ValueError):worker.network_guard('socket.connect',(None,(host,443)))

    def test_metadata_rejects_live_private_and_bad_duration(self):
        info=metadata();self.assertEqual(worker.validate_metadata(info)['title'],'Título de teste')
        for changes in [{'is_live':True},{'availability':'private'},{'duration':None},{'duration':7201},{'duration':float('nan')},{'age_limit':18},{'_type':'playlist'}]:
            with self.assertRaises(ValueError):worker.validate_metadata({**info,**changes})

    def test_google_youtube_families_and_new_cdn_subdomains(self):
        for host in ['www.google.com', 'consent.google.com', 'consent.youtube.com',
                     'youtube.googleapis.com', 'youtubei.googleapis.com', 'rr99.sn-new.googlevideo.com',
                     'i.ytimg.com', 'yt3.ggpht.com', 'www.gstatic.com', 'lh3.googleusercontent.com',
                     'WWW.YOUTUBE.COM.']:
            worker.allowed_remote('https://' + host + '/path?token=hidden')

    def test_redirect_targets_revalidated_and_dns_private_result_blocked(self):
        from urllib.request import HTTPRedirectHandler, Request
        handler = HTTPRedirectHandler()
        request = Request(URL)
        for target in ['https://consent.youtube.com/m', 'https://www.google.com/sorry/index',
                       'https://rr9.googlevideo.com/video']:
            request = handler.redirect_request(request, None, 302, 'Found', {}, target)
            worker.network_guard('urllib.Request', (request.full_url,))
        for target in ['https://localhost/', 'https://169.254.169.254/latest/meta-data/',
                       'https://metadata.google.internal/', 'https://127.0.0.1/',
                       'https://youtube.com.evil.test/', 'https://evilgoogle.com/',
                       'https://google.com:444/', 'https://user:pass@youtube.com/']:
            redirected = handler.redirect_request(request, None, 302, 'Found', {}, target)
            with self.assertRaises(ValueError):
                worker.network_guard('urllib.Request', (redirected.full_url,))
        # Mesmo um domínio autorizado não pode conectar a um IP interno (DNS rebinding).
        worker.allowed_remote('https://www.google.com/')
        for ip in ['0.0.0.0', '127.0.0.1', '10.1.2.3', '172.16.0.1', '192.168.1.2',
                   '169.254.169.254', '100.100.100.200', '::1', 'fc00::1', 'fe80::1',
                   '::ffff:127.0.0.1', '224.0.0.1', 'ff02::1']:
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                worker.network_guard('socket.connect', (None, (ip, 443)))

    def test_denied_destination_logs_only_host_and_reason(self):
        log = io.StringIO()
        with patch('sys.stderr', log), self.assertRaises(ValueError) as error:
            worker.allowed_remote('https://bad.example/private-path?token=secret')
        for value in (log.getvalue(), str(error.exception)):
            self.assertIn('bad.example', value)
            self.assertNotIn('private-path', value)
            self.assertNotIn('secret', value)

    def test_appropriate_formats_and_progressive_no_double_audio(self):
        info=metadata();info['formats'][0].pop('protocol');v,a=worker.choose_formats(info)
        self.assertEqual((v['format_id'],a['format_id']),('v','a'))
        info['formats'][0]['acodec']='mp4a.40.2'
        self.assertIsNone(worker.choose_formats(info)[1])
        info['formats'][0]['width']=1080;info['formats'][0]['height']=1920
        self.assertEqual(worker.choose_formats(info)[0]['height'],1920)

    def test_unsafe_or_incompatible_media_is_not_downloaded(self):
        for change in [{'url':'https://localhost/a'},{'protocol':'m3u8_native'},{'vcodec':'vp9'},{'has_drm':True},{'width':640,'height':360}]:
            info=metadata();info['formats'][0].update(change)
            with self.assertRaises(ValueError):worker.choose_formats(info)

    def test_error_messages(self):
        for exc,fragment in [(RuntimeError('HTTP Error 403'),'não permitiu'),(RuntimeError('timed out'),'Tempo limite'),
                             (OSError(28,'No space left on device'),'espaço'),(RuntimeError('other'),'yt-dlp')]:
            self.assertIn(fragment,worker.friendly_error(exc))

    def test_render_errors_are_actionable(self):
        for exc, fragment in [(ModuleNotFoundError('yt_dlp'), 'Build Command'),
                              (RuntimeError('certificate verify failed'), 'certificados'),
                              (RuntimeError('Connection reset by peer'), 'interrompida'),
                              (RuntimeError('Unable to download: HTTP Error 403'), 'não permitiu')]:
            self.assertIn(fragment, worker.friendly_error(exc))

    def test_bot_block_is_distinct_from_unspecific_403(self):
        self.assertIn('bloqueou ou limitou', worker.friendly_error(RuntimeError("Sign in to confirm you’re not a bot")))
        self.assertIn('HTTP 403', worker.friendly_error(RuntimeError('HTTP Error 403')))

    def test_full_stderr_survives_worker_failure_without_tail_truncation(self):
        import sys
        from process_runner import run_process
        lines = []
        with self.assertRaises(RuntimeError):
            run_process([sys.executable, '-c', 'import sys; print("FIRST", file=sys.stderr); print("x"*12000, file=sys.stderr); print("LAST", file=sys.stderr); sys.exit(1)'], on_stderr=lines.append)
        self.assertEqual(lines[0], 'FIRST')
        self.assertEqual(lines[-1], 'LAST')
        self.assertEqual(sum(line.count('x') for line in lines), 12000)
        self.assertLessEqual(max(map(len, lines)), 8192)

    def test_logger_preserves_traceback_lines_and_redacts_secrets(self):
        log = io.StringIO()
        with patch('sys.stderr', log):
            worker.ServerLogger().error('Traceback:\nHTTP 403 https://example.com/?secret=abc\nCookie: secret\nlast line')
        self.assertIn('Traceback:', log.getvalue())
        self.assertIn('last line', log.getvalue())
        self.assertNotIn('secret', log.getvalue())

    def test_diagnostics_hide_signed_urls_credentials_and_bound_size(self):
        detail = worker.safe_diagnostic(RuntimeError('HTTP 403 https://rr.googlevideo.com/video?secret=abc\nCookie: private\nAuthorization: bearer secret\n' + 'x'*3000))
        self.assertIn('HTTP 403', detail)
        self.assertNotIn('secret', detail)
        self.assertNotIn('private', detail)
        self.assertLess(len(detail), 1850)

    def test_screenshot_url_preserves_video_and_removes_timestamp(self):
        self.assertEqual(importer.canonical_url('https://www.youtube.com/watch?v=LN4dE1W9X0U&t=28s'),
                         'https://www.youtube.com/watch?v=LN4dE1W9X0U')


class YoutubePipelineTests(unittest.TestCase):
    def test_actual_ytdlp_pipeline_reuses_metadata_downloads_each_track_once(self):
        from yt_dlp import YoutubeDL
        from yt_dlp.downloader.http import HttpFD
        paths=[]
        def fake_http(downloader, filename, info):
            paths.append(Path(filename).name)
            Path(filename).write_bytes(b'fixture')
            downloader._hook_progress({'status':'finished','downloaded_bytes':7,'total_bytes':7,'filename':filename},info)
            return True
        with processing.scratch_directory(Path(__file__).parent) as folder, \
             patch.object(YoutubeDL,'extract_info',return_value=metadata()) as extract, \
             patch.object(HttpFD,'real_download',fake_http),patch('youtube_worker.node_runtime',return_value='node'):
            result=worker.download(URL,folder)
            self.assertEqual(result['duration'],60)
            self.assertTrue((folder/'audio.m4a').exists());self.assertTrue((folder/'video.mp4').exists())
            state=json.loads((folder/'import-progress.json').read_text())
            self.assertIn('100%',state['message'])
        extract.assert_called_once()
        self.assertEqual(paths,['audio.m4a','video.mp4'])

    def test_obtain_copy_mux_and_raw_video_cleanup(self):
        def child(args,**kwargs):
            folder=Path(args[-1]);(folder/'video.mp4').write_bytes(b'v');(folder/'audio.m4a').write_bytes(b'a')
            (folder/'import-result.json').write_text(json.dumps(worker.validate_metadata(metadata())))
        def mux(args):Path(args[-1]).write_bytes(b'mp4')
        with processing.scratch_directory(Path(__file__).parent) as folder, patch('youtube_import.run_process',side_effect=child), \
             patch('processing.run',side_effect=mux) as ffmpeg:
            result,audio=importer.obtain(folder,URL,lambda **s:None)
            args=ffmpeg.call_args.args[0]
            self.assertEqual(args[args.index('-c')+1],'copy')
            self.assertEqual(audio.name,'audio.m4a')
            self.assertTrue((folder/'source.mp4').exists());self.assertFalse((folder/'video.mp4').exists())
            self.assertFalse((folder/'import-result.json').exists())

    def test_imported_audio_reaches_transcription_then_is_removed(self):
        with processing.scratch_directory(Path(__file__).parent) as root, patch.object(app,'DATA',root),patch.object(app,'JOBS',{'a':{}}):
            folder=root/'a';folder.mkdir();audio=folder/'audio.m4a';audio.write_bytes(b'fixture')
            (folder/'source.mp4').write_bytes(b'mp4')
            with patch('youtube_import.obtain',return_value=(worker.validate_metadata(metadata()),audio)), \
                 patch('processing.probe',return_value=(60,True)),patch('processing.transcribe',return_value=[]) as transcribe:
                app.import_youtube('a',URL)
            self.assertEqual(transcribe.call_args.args[0],audio)
            self.assertEqual(app.JOBS['a']['status'],'ready')
            self.assertFalse(audio.exists());self.assertTrue((folder/'source.mp4').exists())
            self.assertTrue((folder/'transcript.json').exists())

    def test_failed_download_cleans_partial_files(self):
        with processing.scratch_directory(Path(__file__).parent) as root,patch.object(app,'DATA',root),patch.object(app,'JOBS',{'a':{}}):
            folder=root/'a';folder.mkdir();(folder/'video.mp4.part').write_bytes(b'partial')
            with patch('youtube_import.obtain',side_effect=RuntimeError('falha de download')):
                app.import_youtube('a',URL)
            self.assertEqual(app.JOBS['a']['status'],'error');self.assertFalse(folder.exists())

    def test_api_queues_import_with_same_heavy_slot(self):
        handler=object.__new__(app.Handler);handler.path='/api/import/youtube';body=json.dumps({'url':URL}).encode()
        handler.headers={'Content-Length':str(len(body))};handler.rfile=io.BytesIO(body);handler.connection=MagicMock();handler.json=MagicMock()
        with processing.scratch_directory(Path(__file__).parent) as root,patch.object(app,'DATA',root),patch.object(app,'JOBS',{}), \
             patch.object(app,'HEAVY_SLOT') as slot,patch.object(app.POOL,'submit') as submit,patch('binaries.health',return_value={'ffmpeg':True,'ffprobe':True}):
            handler.do_POST()
            self.assertEqual(handler.json.call_args.args[1],202)
            self.assertEqual(submit.call_args.args[:2],(app.guarded_task,app.import_youtube))
            slot.release.assert_not_called()

    def test_completed_import_is_reused_without_worker(self):
        handler=object.__new__(app.Handler);handler.path='/api/import/youtube';body=json.dumps({'url':URL}).encode()
        handler.headers={'Content-Length':str(len(body))};handler.rfile=io.BytesIO(body);handler.connection=MagicMock();handler.json=MagicMock()
        with processing.scratch_directory(Path(__file__).parent) as root,patch.object(app,'DATA',root), \
             patch.object(app,'JOBS',{'a':{'status':'ready','duration':60,'source_url':URL}}), \
             patch.object(app,'HEAVY_SLOT') as slot,patch.object(app.POOL,'submit') as submit:
            folder=root/'a';folder.mkdir();(folder/'source.mp4').touch();(folder/'transcript.json').write_text('[]')
            handler.do_POST()
            self.assertEqual(handler.json.call_args.args,({'id':'a','reused':True},200))
            submit.assert_not_called();slot.release.assert_called_once()

class YoutubeResourceTests(unittest.TestCase):
    def test_low_disk_space_aborts_before_downloading(self):
        from yt_dlp import YoutubeDL
        with processing.scratch_directory(Path(__file__).parent) as folder,patch.object(YoutubeDL,'extract_info',return_value=metadata()), \
             patch.object(YoutubeDL,'process_info') as download,patch('youtube_worker.node_runtime',return_value='node'), \
             patch('youtube_worker.shutil.disk_usage',return_value=MagicMock(free=1)):
            with self.assertRaisesRegex(ValueError,'espaço'):worker.download(URL,folder)
            download.assert_not_called()

    def test_worker_failure_surfaces_readable_error(self):
        def failed(args,**kwargs):
            (Path(args[-1])/'import-result.json').write_text(json.dumps({'error':'Vídeo privado'}))
            raise RuntimeError('worker failed')
        with processing.scratch_directory(Path(__file__).parent) as folder,patch('youtube_import.run_process',side_effect=failed):
            with self.assertRaisesRegex(RuntimeError,'Vídeo privado'):importer.obtain(folder,URL,lambda **state:None)

    def test_expired_exports_removed_but_source_and_active_transfers_preserved(self):
        with processing.scratch_directory(Path(__file__).parent) as root,patch.object(app,'DATA',root),patch.object(app,'JOBS',{}):
            folder=root/('a'*32);folder.mkdir();source=folder/'source.mp4';source.touch()
            old=folder/('b'*32+'.mp4');old.touch();os.utime(old,(1,1))
            with patch.object(app,'ACTIVE_FILES',{folder:1}):app.cleanup_expired()
            self.assertTrue(old.exists())
            app.cleanup_expired();self.assertFalse(old.exists());self.assertTrue(source.exists())
