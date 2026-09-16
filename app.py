"""Servidor de uso local, sem serviços pagos. Inicie com python app.py."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json
import math
import binaries
import threading
import uuid
import processing
import socket
import os


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

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


def analyze(key):
    try:
        folder = DATA / key
        duration, audio = processing.probe(folder / 'source.mp4')
        update(key, status='transcribing', message='Transcrevendo o áudio com o modelo local…')
        segments = processing.transcribe(folder / 'source.mp4') if audio else []
        update(key, status='ready', message='Cortes prontos para revisar.' if segments else 'Sem fala detectada. Ajuste seu corte manualmente.',
               duration=duration, segments=segments, caption_cues=processing.caption_cues(segments), suggestions=processing.suggest(segments, duration))
    except Exception as exc:
        update(key, status='error', message=str(exc))


def render(key, parent, start, end, captions, position=0.5):
    try:
        name = processing.export(DATA / parent, JOBS[parent]['segments'], start, end, captions, key, position)
        update(key, status='ready', url=f'/media/{parent}/{name}')
    except Exception as exc:
        update(key, status='error', message=str(exc))


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
            if 'segments' in job:
                job['caption_cues'] = processing.caption_cues(job['segments'])
            return self.json(job or {'message': 'Tarefa não encontrada.'}, 200 if job else 404)
        if path.startswith('/media/'):
            parts = path.split('/')
            if len(parts) != 4 or not all(c in '0123456789abcdef' for c in parts[2]) or len(parts[2]) != 32:
                return self.send_error(404)
            name = parts[3]
            if name != 'source.mp4' and (len(name) != 36 or not name.endswith('.mp4') or not all(c in '0123456789abcdef' for c in name[:-4])):
                return self.send_error(404)
            return self.file(DATA / parts[2] / name, 'video/mp4')
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
        if path not in files:
            return self.send_error(404)
        name, mime = files[path]
        self.file(ROOT / 'static' / name, mime)

    def file(self, path, mime):
        if not path.is_file():
            return self.send_error(404)
        size = path.stat().st_size
        start, end = 0, size-1
        partial = self.headers.get('Range') if self.command != 'HEAD' else None
        if partial:
            try:
                a, b = partial.removeprefix('bytes=').split('-')
                start, end = (int(a), min(int(b), end) if b else end) if a else (max(0, size-int(b)), end)
                if start < 0 or start > end:
                    raise ValueError()
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', mime)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end-start+1))
        self.send_header('X-Content-Type-Options', 'nosniff')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            with path.open('rb') as f:
                f.seek(start)
                remaining = end-start+1
                while remaining:
                    chunk = f.read(min(1024*1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        # Evita requisições de outras páginas para o servidor local.
        origin = self.headers.get('Origin')
        if not origin_allowed(origin, self.headers.get('Host', '')):
            return self.json({'message': 'Origem não permitida.'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.path == '/api/upload':
                if not 0 < length <= MAX_UPLOAD:
                    return self.json({'message': 'Limite de upload: 1 GB.'}, 413)
                missing = [name for name, available in binaries.health().items() if not available]
                if missing:
                    return self.json({'message': 'Não foi possível localizar: ' + ', '.join(missing) + '. Configure o caminho conforme o README.'}, 503)
                key = uuid.uuid4().hex
                folder = DATA / key
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
                    JOBS[key] = {'status': 'queued', 'message': 'Vídeo recebido. Aguardando análise…'}
                POOL.submit(analyze, key)
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
                key = uuid.uuid4().hex
                with LOCK:
                    JOBS[key] = {'status': 'rendering', 'message': 'Exportando seu corte…'}
                POOL.submit(render, key, parent, start, end, data.get('captions') is True, position)
                return self.json({'id': key}, 202)
            self.json({'message': 'Rota não encontrada.'}, 404)
        except (ValueError, KeyError, TypeError) as exc:
            self.json({'message': str(exc)}, 400)
        except Exception:
            self.json({'message': 'Não foi possível concluir. Confira o terminal e tente novamente.'}, 500)


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
    print(f'CortaVideo: http://{host}:{port}', flush=True)
    server.serve_forever()
