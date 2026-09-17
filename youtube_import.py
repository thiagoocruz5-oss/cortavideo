"""Validação de links e coordenação; yt-dlp nunca é importado no servidor HTTP."""
import json
import re
import shutil
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from process_runner import run_process
import processing

MAX_BYTES = 1024**3


def canonical_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) < 33 for c in value):
        raise ValueError('Cole uma URL válida de um vídeo do YouTube, sem espaços.')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password or parsed.port is not None:
            raise ValueError()
        host = parsed.hostname
        if host == 'youtu.be':
            video_id = parsed.path.removeprefix('/')
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            if parsed.path == '/watch':
                ids = parse_qs(parsed.query).get('v', [])
                video_id = ids[0] if len(ids) == 1 else ''
            elif parsed.path.startswith(('/shorts/', '/embed/')):
                video_id = parsed.path.split('/')[-1]
                if parsed.path.count('/') != 2:
                    video_id = ''
            else:
                video_id = ''
        else:
            raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise ValueError()
    except ValueError:
        raise ValueError('URL não suportada. Use youtube.com/watch?v=…, youtu.be/… ou youtube.com/shorts/… de um único vídeo.') from None
    # Descarta playlist, redirecionamentos, tempos e quaisquer parâmetros enviados.
    return 'https://www.youtube.com/watch?v=' + video_id


def node_runtime():
    node = shutil.which('node')
    if node:
        try:
            result = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=5, check=True)
            if int(result.stdout.strip().lstrip('v').split('.')[0]) >= 22:
                return node
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    raise ValueError('Importação do YouTube requer Node.js 22 ou superior no servidor. O upload de arquivo continua disponível.')


def obtain(folder, url, progress):
    """Uma extração de metadados, downloads sequenciais e remux sem recodificar."""
    url = canonical_url(url)
    folder = Path(folder).resolve()
    state = folder / 'import-progress.json'
    result = folder / 'import-result.json'
    last = None
    def report():
        nonlocal last
        try:
            value = json.loads(state.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if value != last:
            progress(**value)
            last = value
    try:
        from youtube_worker import redact_log
        def server_log(line):
            print(f'YouTube [{folder.name}] {redact_log(line)}', file=sys.stderr, flush=True)
        run_process([sys.executable, str(Path(__file__).with_name('youtube_worker.py')), url, str(folder)],
                    timeout=1800, on_tick=report, on_stderr=server_log)
    except RuntimeError as exc:
        # O stderr do worker fica em disco; publique somente um diagnóstico
        # sanitizado para que a causa não desapareça dos logs do Render.
        from youtube_worker import safe_diagnostic
        print(f'YouTube import failed [{folder.name}]: {safe_diagnostic(exc)}', file=sys.stderr, flush=True)
        if result.is_file():
            error = json.loads(result.read_text(encoding='utf-8')).get('error')
            if error:
                raise RuntimeError(error) from exc
        raise RuntimeError('A importação foi interrompida ou excedeu 30 minutos. Tente novamente; confira os logs se o serviço reiniciou.') from exc
    metadata = json.loads(result.read_text(encoding='utf-8'))
    if metadata.get('error'):
        raise RuntimeError(metadata['error'])
    progress(message='Preparando vídeo para a prévia (sem recodificar)…', title=metadata['title'])
    video = folder / 'video.mp4'
    audio = folder / 'audio.m4a'
    source = folder / 'source.mp4'
    needed = video.stat().st_size + (audio.stat().st_size if audio.is_file() else 0) + 128*1024**2
    if shutil.disk_usage(folder).free < needed:
        raise RuntimeError('Sem espaço em disco para preparar o vídeo. Aguarde a limpeza ou importe um vídeo menor.')
    args = ['ffmpeg', '-y', '-v', 'error', '-threads', '1', '-i', str(video)]
    if audio.is_file():
        args += ['-i', str(audio), '-map', '0:v:0', '-map', '1:a:0']
    else:
        args += ['-map', '0:v:0', '-map', '0:a:0?']
    args += ['-c', 'copy', '-movflags', '+faststart', str(source)]
    try:
        processing.run(args)
    except Exception as exc:
        source.unlink(missing_ok=True)
        raise RuntimeError('FFmpeg não conseguiu preparar o vídeo importado. Tente outro vídeo ou confira o espaço em disco.') from exc
    video.unlink()
    state.unlink(missing_ok=True)
    result.unlink(missing_ok=True)
    return metadata, audio if audio.is_file() else source
