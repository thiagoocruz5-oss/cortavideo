"""Servidor de uso local, sem serviços pagos. Inicie com python app.py."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json
import math
import binaries
import threading
import uuid
import processing
import youtube_import
import socket
import os
import shutil
import time
import signal
from process_runner import stop_all


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    request_slots = threading.BoundedSemaphore(8)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nRetry-After: 3\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
JOBS = {}
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1)
HEAVY_SLOT = threading.BoundedSemaphore(1)
FILE_LOCK = threading.RLock()
ACTIVE_FILES = {}
MAX_UPLOAD = 1024 * 1024 * 1024


def origin_allowed(origin, host):
    """Lista explícita; não confia em Host/Forwarded para liberar domínios."""
    # Clientes locais sem Origin (scripts/CLI) mantêm o comportamento existente.
    if origin is None:
        return True
    if origin == 'https://cortavideo.onrender.com':
        return True
    try:
        source = urlparse(origin)
        target = urlparse('http://' + host)
        loopback = {'127.0.0.1', 'localhost'}
        return (
            source.scheme == 'http'
            and source.hostname in loopback and target.hostname in loopback
            and source.username is None and source.password is None
            and target.username is None and target.password is None
            and not any((source.path, source.params, source.query, source.fragment,
                         target.path, target.params, target.query, target.fragment))
            and (source.port or 80) == (target.port or 80)
            and origin == f'http://{source.netloc}'
        )
    except (ValueError, TypeError):
        return False


def update(key, **values):
    with LOCK:
        JOBS[key].update(values)


def load_segments(key):
    # Compatibilidade com testes/clientes internos; resultados reais ficam no disco.
    if 'segments' in JOBS.get(key, {}):
        return JOBS[key]['segments']
    return json.loads((DATA / key / 'transcript.json').read_text(encoding='utf-8'))


def analyze(key, audio_source=None):
    folder = DATA / key
    try:
        duration, audio = processing.probe(folder / 'source.mp4')
        update(key, status='transcribing', message='Transcrevendo em blocos com o modelo local…')
        segments = processing.transcribe(audio_source or folder / 'source.mp4', progress=lambda **state: update(key, **state)) if audio else []
        (folder / 'transcript.json').write_text(json.dumps(segments), encoding='utf-8')
        update(key, message='Gerando sugestões de cortes…')
        update(key, status='ready', message='Cortes prontos para revisar.' if segments else 'Sem fala detectada. Ajuste seu corte manualmente.',
               duration=duration, suggestions=processing.suggest(segments, duration))
    except Exception as exc:
        update(key, status='error', message=str(exc))
        shutil.rmtree(folder, ignore_errors=True)


def import_youtube(key, url):
    folder = DATA / key
    try:
        metadata, audio = youtube_import.obtain(folder, url, lambda **state: update(key, **state))
        update(key, title=metadata['title'], youtube_id=metadata['youtube_id'])
        analyze(key, audio_source=audio)
    except Exception as exc:
        update(key, status='error', message=str(exc))
        shutil.rmtree(folder, ignore_errors=True)
    finally:
        # Só a faixa separada; source.mp4 é necessário para prévia e cortes.
        (folder / 'audio.m4a').unlink(missing_ok=True)


def render(key, parent, start, end, captions, position=0.5):
    try:
        name = processing.export(DATA / parent, load_segments(parent) if captions else [], start, end, captions, key, position)
        url = f'/media/{parent}/{name}'
        update(key, status='ready', url=url, download_url=url + '?download=1')
    except Exception as exc:
        update(key, status='error', message=str(exc))


def guarded_task(function, *args):
    try:
        function(*args)
    finally:
        HEAVY_SLOT.release()


def cleanup_expired():
    # Só remove pastas UUID criadas pelo aplicativo, nunca caminhos enviados pelo cliente.
    if not HEAVY_SLOT.acquire(blocking=False):
        return
    try:
        cutoff = time.time() - int(os.getenv('FILE_TTL_HOURS', '24')) * 3600
        for folder in DATA.iterdir():
            if folder.is_dir() and not folder.is_symlink() and len(folder.name) == 32 and all(c in '0123456789abcdef' for c in folder.name):
                with FILE_LOCK:
                    if not ACTIVE_FILES.get(folder):
                        for export in folder.glob('*.mp4'):
                            stem = export.stem
                            if len(stem) == 32 and all(c in '0123456789abcdef' for c in stem) and export.stat().st_atime < cutoff:
                                export.unlink()
                        if folder.stat().st_mtime < cutoff:
                            shutil.rmtree(folder, ignore_errors=True)
        with LOCK:
            for key, job in list(JOBS.items()):
                if job.get('created', time.time()) < cutoff and job.get('status') in ('ready', 'error'):
                    JOBS.pop(key, None)
    finally:
        HEAVY_SLOT.release()


def janitor():
    while True:
        try:
            cleanup_expired()
        except OSError:
            pass
        time.sleep(60)


class Handler(BaseHTTPRequestHandler):
    def json(self, data, status=200):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/health':
            return self.json({**binaries.health(), 'version': 'local-model-v2'})
        if path.startswith('/api/jobs/'):
            with LOCK:
                job = dict(JOBS.get(path.split('/')[-1], {}))
            if job.get('status') == 'ready' and 'duration' in job:
                key = path.split('/')[-1]
                try:
                    job['segments'] = load_segments(key)
                    job['caption_cues'] = processing.caption_cues(job['segments'])
                    os.utime(DATA / key, None)
                except OSError:
                    return self.json({'message': 'Vídeo expirado. Envie novamente.'}, 410)
            return self.json(job or {'message': 'Tarefa não encontrada. O servidor pode ter reiniciado; envie o vídeo novamente.'}, 200 if job else 404)
        if path.startswith('/media/'):
            parts = path.split('/')
            if len(parts) != 4 or not all(c in '0123456789abcdef' for c in parts[2]) or len(parts[2]) != 32:
                return self.send_error(404)
            name = parts[3]
            if name != 'source.mp4' and (len(name) != 36 or not name.endswith('.mp4') or not all(c in '0123456789abcdef' for c in name[:-4])):
                return self.send_error(404)
            return self.file(DATA / parts[2] / name, 'video/mp4', attachment=parse_qs(urlparse(self.path).query).get('download') == ['1'])
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
        if path not in files:
            return self.send_error(404)
        name, mime = files[path]
        self.file(ROOT / 'static' / name, mime)

    def file(self, path, mime, attachment=False):
        # Abre antes dos headers; limpeza e abertura usam o mesmo lock.
        media = mime == 'video/mp4'
        folder = path.parent
        try:
            with FILE_LOCK:
                stream = path.open('rb')
                if media:
                    ACTIVE_FILES[folder] = ACTIVE_FILES.get(folder, 0) + 1
        except OSError:
            return self.json({'message': 'Arquivo indisponível ou expirado. Se o serviço reiniciou, envie o vídeo e exporte novamente.'}, 410 if media else 404)
        sent = 0
        try:
            stat = os.fstat(stream.fileno())
            size = stat.st_size
            etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
            start, end = 0, size-1
            partial = self.headers.get('Range') if self.command != 'HEAD' else None
            if self.headers.get('If-Range') not in (None, etag):
                partial = None
            if partial:
                try:
                    if not partial.startswith('bytes=') or ',' in partial:
                        raise ValueError()
                    a, b = partial[6:].split('-')
                    if not a:
                        suffix = int(b)
                        if suffix <= 0:
                            raise ValueError()
                        start = max(0, size-suffix)
                    else:
                        start = int(a)
                        end = min(int(b), end) if b else end
                    if start < 0 or start > end or start >= size:
                        raise ValueError()
                except ValueError:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
            if media and not size:
                return self.json({'message': 'O MP4 está vazio. Exporte novamente.'}, 409)
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', mime)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(max(0, end-start+1)))
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', 'private, no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if attachment:
                self.send_header('Content-Disposition', 'attachment; filename="cortavideo.mp4"')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if self.command == 'HEAD':
                return
            stream.seek(start)
            remaining = max(0, end-start+1)
            # Buffers pequenos por conexão; downloads lentos não prendem RAM de vídeo.
            self.connection.settimeout(120)
            while remaining:
                chunk = stream.read(min(256*1024, remaining))
                if not chunk:
                    raise OSError('MP4 truncado durante a transferência')
                self.wfile.write(chunk)
                remaining -= len(chunk)
                sent += len(chunk)
            if attachment:
                self.log_message('DOWNLOAD complete bytes=%s range=%s pid=%s', sent, partial, os.getpid())
        except (OSError, TimeoutError) as exc:
            self.close_connection = True
            self.log_message('TRANSFER interrupted bytes=%s pid=%s reason=%s', sent, os.getpid(), exc)
        finally:
            stream.close()
            if media:
                with FILE_LOCK:
                    ACTIVE_FILES[folder] -= 1
                    if not ACTIVE_FILES[folder]:
                        ACTIVE_FILES.pop(folder)
                    try:
                        file_stat = path.stat()
                        os.utime(path, ns=(time.time_ns(), file_stat.st_mtime_ns))
                        os.utime(folder, None)
                    except OSError:
                        pass

    def do_POST(self):
        # Evita requisições de outras páginas para o servidor local.
        origin = self.headers.get('Origin')
        if not origin_allowed(origin, self.headers.get('Host', '')):
            return self.json({'message': 'Origem não permitida.'}, 403)
        owns_slot = False
        upload_folder = None
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.path == '/api/import/youtube':
                if not 0 < length < 4096:
                    raise ValueError('Pedido de importação inválido.')
                self.connection.settimeout(30)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Pedido de importação inválido.')
                url = youtube_import.canonical_url(data.get('url'))
                if not HEAVY_SLOT.acquire(blocking=False):
                    return self.json({'message': 'Outro vídeo está sendo processado. Aguarde e tente novamente.'}, 429)
                owns_slot = True
                # Reutiliza apenas trabalhos completos desta instância e com os arquivos presentes.
                with LOCK, FILE_LOCK:
                    for existing, task in JOBS.items():
                        if task.get('source_url') == url and task.get('status') == 'ready' and 'duration' in task:
                            directory = DATA / existing
                            if (directory / 'source.mp4').is_file() and (directory / 'transcript.json').is_file():
                                os.utime(directory, None)
                                task['created'] = time.time()
                                return self.json({'id': existing, 'reused': True}, 200)
                if not all(binaries.health().values()):
                    return self.json({'message': 'FFmpeg e ffprobe precisam estar instalados para importar. Veja o README.'}, 503)
                key = uuid.uuid4().hex
                folder = DATA / key
                upload_folder = folder
                folder.mkdir()
                with LOCK:
                    JOBS[key] = {'created': time.time(), 'status': 'importing', 'source_url': url,
                                 'message': 'Obtendo informações do vídeo…'}
                POOL.submit(guarded_task, import_youtube, key, url)
                owns_slot = False
                upload_folder = None
                return self.json({'id': key}, 202)
            if self.path == '/api/upload':
                if not 0 < length <= MAX_UPLOAD:
                    return self.json({'message': 'Limite de upload: 1 GB.'}, 413)
                missing = [name for name, available in binaries.health().items() if not available]
                if missing:
                    return self.json({'message': 'Não foi possível localizar: ' + ', '.join(missing) + '. Configure o caminho conforme o README.'}, 503)
                if not HEAVY_SLOT.acquire(blocking=False):
                    return self.json({'message': 'Outro vídeo está sendo processado. Aguarde e tente novamente.'}, 429)
                owns_slot = True
                key = uuid.uuid4().hex
                folder = DATA / key
                upload_folder = folder
                folder.mkdir()
                self.connection.settimeout(120)
                with (folder / 'source.mp4').open('wb') as f:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1024*1024, remaining))
                        if not chunk:
                            raise ValueError('Upload interrompido.')
                        f.write(chunk)
                        remaining -= len(chunk)
                with LOCK:
                    JOBS[key] = {'created': time.time(), 'status': 'queued', 'message': 'Vídeo recebido. Aguardando análise…'}
                POOL.submit(guarded_task, analyze, key)
                owns_slot = False
                upload_folder = None
                return self.json({'id': key}, 202)
            if self.path == '/api/export':
                if not 0 < length < 4096:
                    raise ValueError('Pedido inválido.')
                data = json.loads(self.rfile.read(length))
                parent = data.get('id')
                job = JOBS.get(parent, {})
                if job.get('status') != 'ready' or 'duration' not in job:
                    raise ValueError('A análise ainda não está pronta.')
                start, end = float(data['start']), float(data['end'])
                position = float(data.get('position', 0.5))
                if not math.isfinite(position) or not 0 <= position <= 1:
                    raise ValueError('Enquadramento deve estar entre 0 e 1.')
                if not all(map(math.isfinite, [start, end])) or not 0 <= start < end <= job['duration'] or not 30 <= end-start <= 60:
                    raise ValueError('Escolha um trecho de 30 a 60 segundos dentro do vídeo.')
                if not HEAVY_SLOT.acquire(blocking=False):
                    return self.json({'message': 'Outro vídeo está sendo processado. Aguarde e tente novamente.'}, 429)
                owns_slot = True
                os.utime(DATA / parent, None)
                key = uuid.uuid4().hex
                with LOCK:
                    JOBS[key] = {'created': time.time(), 'status': 'rendering', 'message': 'Exportando seu corte…'}
                POOL.submit(guarded_task, render, key, parent, start, end, data.get('captions') is True, position)
                owns_slot = False
                return self.json({'id': key}, 202)
            self.json({'message': 'Rota não encontrada.'}, 404)
        except (ValueError, KeyError, TypeError) as exc:
            self.json({'message': str(exc)}, 400)
        except Exception:
            self.json({'message': 'Não foi possível concluir. Confira o terminal e tente novamente.'}, 500)
        finally:
            if upload_folder is not None:
                shutil.rmtree(upload_folder, ignore_errors=True)
            if owns_slot:
                HEAVY_SLOT.release()


def server_address():
    # Render fornece PORT e precisa de bind em todas as interfaces.
    # Sem PORT, preserva o acesso somente local e CORTAVIDEO_PORT.
    platform_port = os.getenv('PORT')
    port = int(platform_port or os.getenv('CORTAVIDEO_PORT', '8001'))
    if not 1 <= port <= 65535:
        raise ValueError('A porta deve estar entre 1 e 65535.')
    return ('0.0.0.0' if platform_port else '127.0.0.1', port)


if __name__ == '__main__':
    host, port = server_address()
    server = LocalServer((host, port), Handler)
    print(f'CortaVideo: http://{host}:{port} pid={os.getpid()} started={time.time()}', flush=True)
    def terminate(signum, frame):
        print(f'SHUTDOWN signal={signum} pid={os.getpid()}', flush=True)
        stop_all()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    threading.Thread(target=janitor, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        stop_all()
        server.server_close()
