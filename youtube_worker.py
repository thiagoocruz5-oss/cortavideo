"""Worker de download isolado. Não importa Whisper nem inicia FFmpeg."""
import errno
import ipaddress
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit
from youtube_import import canonical_url, MAX_BYTES, node_runtime
from transcription_worker import write_progress


# Famílias de serviços, não nomes individuais de servidores/CDNs.
# A lista da URL fornecida pelo usuário continua restrita em canonical_url.
REMOTE_DOMAINS = ('youtube.com', 'youtube-nocookie.com', 'googlevideo.com',
                  'ytimg.com', 'google.com', 'googleapis.com', 'gstatic.com',
                  'ggpht.com', 'googleusercontent.com')


def deny_remote(host, reason):
    # Nunca registrar path, query, credenciais ou a URL assinada.
    host = re.sub(r'[^a-zA-Z0-9.:[\]-]', '?', host or '(ausente)')[:253]
    print(f'YouTube network denied hostname={host} reason={reason}', file=sys.stderr, flush=True)
    raise ValueError(f'Destino de rede não permitido para importação do YouTube (hostname={host}; motivo={reason}).')


def allowed_remote(url):
    h = ''
    try:
        p = urlsplit(url)
        h = (p.hostname or '').rstrip('.').lower()
        port = p.port
    except (ValueError, TypeError):
        deny_remote(h, 'URL inválida')
    if p.scheme != 'https':
        deny_remote(h, 'HTTPS obrigatório')
    if p.username is not None or p.password is not None or port not in (None, 443):
        deny_remote(h, 'credenciais ou porta não permitidas')
    if not any(h == base or h.endswith('.' + base) for base in REMOTE_DOMAINS):
        deny_remote(h, 'domínio fora das famílias Google/YouTube autorizadas')


def network_guard(event, args):
    # Urllib também emite este evento nos redirecionamentos HTTP.
    if event == 'urllib.Request':
        allowed_remote(args[0])
    elif event == 'socket.connect':
        address = args[1]
        try:
            ip = ipaddress.ip_address(address[0]) if isinstance(address, tuple) else None
            public = ip is not None and ip.is_global and not ip.is_multicast
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                public = public and ip.ipv4_mapped.is_global and not ip.ipv4_mapped.is_multicast
        except ValueError:
            public = False
        if not public:
            print('YouTube network denied hostname=(conexão) reason=IP de conexão não público', file=sys.stderr, flush=True)
            raise ValueError('Conexão com endereço interno não permitida.')


def validate_metadata(info):
    duration = info.get('duration')
    if info.get('_type', 'video') != 'video' or info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        raise ValueError('Lives, transmissões em andamento e playlists não são suportadas. Use um vídeo já publicado.')
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 30 <= duration <= 7200:
        raise ValueError('O vídeo deve ter entre 30 segundos e 2 horas.')
    if info.get('availability') in ('private', 'premium_only', 'subscriber_only', 'needs_auth') or (info.get('age_limit') or 0) >= 18:
        raise ValueError('Este vídeo exige autenticação ou possui restrições de acesso. Use outro vídeo público.')
    return {'title': str(info.get('title') or 'Vídeo do YouTube')[:300], 'duration': duration, 'youtube_id': info['id']}


def choose_formats(info):
    from yt_dlp.utils import determine_protocol
    def usable(f):
        try:
            allowed_remote(f.get('url', ''))
            f['protocol'] = determine_protocol(f)
            return f.get('protocol') == 'https' and not f.get('has_drm')
        except ValueError:
            return False
    formats = [f for f in info.get('formats', []) if usable(f)]
    videos = [f for f in formats if f.get('ext') == 'mp4' and str(f.get('vcodec', '')).startswith(('avc1', 'h264'))
              and 0 < (f.get('width') or 0) <= 1920 and 0 < (f.get('height') or 0) <= 1920
              and 720 <= min(f.get('width') or 0, f.get('height') or 0) <= 1080
              and (f.get('fps') or 30) <= 60
              and (f.get('acodec') in ('none', None) or str(f['acodec']).startswith(('mp4a', 'aac')))]
    if not videos:
        raise ValueError('O YouTube não ofereceu um MP4 H.264 compatível entre 720p e 1080p (até 1920 px). Tente outro vídeo ou use upload de arquivo.')
    # Prefere 30 fps quando disponível, sem escolher 360p no lugar de 1080p.
    video = max(videos, key=lambda f: (min(f['width'], f['height']), (f.get('fps') or 30) <= 30, f.get('tbr') or 0))
    if video.get('acodec') not in ('none', None):
        return video, None
    audios = [f for f in formats if f.get('vcodec') == 'none' and f.get('ext') == 'm4a'
              and str(f.get('acodec', '')).startswith(('mp4a', 'aac'))]
    if not audios:
        raise ValueError('Não há uma faixa de áudio AAC compatível disponível. Tente outro vídeo ou use upload.')
    modest = [f for f in audios if (f.get('abr') or f.get('tbr') or 128) <= 160]
    audio = max(modest or audios, key=lambda f: f.get('abr') or f.get('tbr') or 0)
    return video, audio


def redact_log(detail):
    detail = re.sub(r'\x1b\[[0-9;]*m', '', str(detail))
    detail = re.sub(r'https?://\S+', '[URL omitida]', detail)
    return re.sub(r'(?im)(cookie|authorization|token|password)\s*[:=].*', r'\1: [omitido]', detail)


class ServerLogger:
    def debug(self, message):
        for line in redact_log(message).splitlines():
            print(line, file=sys.stderr, flush=True)

    info = debug
    warning = debug
    error = debug


def safe_diagnostic(exc):
    """Logs limitados, sem URLs assinadas, cabeçalhos de autenticação ou ANSI."""
    detail = redact_log(exc)
    return f'{type(exc).__name__}: ' + ' '.join(detail.split())[:1800]


def friendly_error(exc):
    if isinstance(exc, ImportError):
        return 'Dependência de importação ausente no servidor. Refaça o deploy instalando requirements.txt e executando preparar_youtube.py no Build Command.'
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return 'Sem espaço em disco. Aguarde a limpeza ou importe um vídeo menor.'
    message = str(exc).lower()
    if 'not a bot' in message or '429' in message:
        return 'O YouTube bloqueou ou limitou o acesso automatizado deste servidor. Não é possível importar por este acesso agora. Envie o arquivo; não usamos login nem cookies para contornar o bloqueio.'
    if '403' in message:
        return 'O YouTube não permitiu baixar a mídia (HTTP 403). Isso pode ser uma restrição de acesso ou uma URL de mídia recusada; os logs do servidor contêm o diagnóstico.'
    if 'no space left' in message or 'disk full' in message:
        return 'Sem espaço em disco para importar o vídeo.'
    if any(x in message for x in ('sign in', 'confirm', 'bot', '403', '429', 'cookies', 'private', 'age-restricted', 'not available', 'unavailable', 'removed', 'copyright', 'country')):
        return 'O YouTube não permitiu acessar este vídeo a partir do servidor (privado, removido, restrito ou bloqueio do provedor). Tente outro vídeo público ou envie o arquivo.'
    if 'timed out' in message or 'timeout' in message:
        return 'Tempo limite ao acessar o YouTube. Tente novamente mais tarde.'
    if any(x in message for x in ('certificate_verify_failed', 'certificate verify failed', 'ssl:')):
        return 'O servidor não conseguiu validar a conexão segura com o YouTube. Confira os certificados e os logs do Render.'
    if any(x in message for x in ('connection reset', 'connection refused', 'network is unreachable', 'name resolution', 'unable to download', 'remote end closed')):
        return 'A conexão do servidor com o YouTube falhou ou foi interrompida. Tente novamente; se persistir, confira os logs do Render ou envie o arquivo.'
    if isinstance(exc, ValueError):
        return str(exc)
    return 'Falha ao importar pelo yt-dlp. O acesso pode estar bloqueado ou o extrator precisa ser atualizado. Tente outro vídeo ou envie o arquivo.'


def download(url, folder):
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.youtube import YoutubeIE
    from yt_dlp.networking._urllib import UrllibRH
    class RestrictedYoutubeDL(YoutubeDL):
        def build_request_director(self, handlers, preferences=None):
            # Um único transporte Python: o guard cobre redirects e IPs de conexão.
            return super().build_request_director([UrllibRH])
        def urlopen(self, request):
            allowed_remote(request if isinstance(request, str) else request.url)
            return super().urlopen(request)
    folder = Path(folder)
    progress = folder / 'import-progress.json'
    node = node_runtime()
    logger = ServerLogger()
    logger.info(f'YouTube runtime: Python={sys.version.split()[0]} yt-dlp={version("yt-dlp")} EJS={version("yt-dlp-ejs")} Node={node}')
    # Memória do JS limitada; ele termina antes de carregar Whisper.
    os.environ['NODE_OPTIONS'] = '--max-old-space-size=96'
    options = {'quiet': True, 'noprogress': True, 'no_warnings': False, 'verbose': True, 'logger': logger, 'noplaylist': True, 'cachedir': False,
               'socket_timeout': 20, 'retries': 2, 'fragment_retries': 2, 'extractor_retries': 1,
               'concurrent_fragment_downloads': 1, 'buffersize': 64*1024, 'noresizebuffer': True,
               'max_filesize': MAX_BYTES, 'continuedl': True, 'overwrites': False,
               'proxy': '', 'enable_file_urls': False, 'js_runtimes': {'node': {'path': node}},
               'remote_components': set(), 'postprocessors': []}
    write_progress(progress, message='Obtendo informações do vídeo…')
    with RestrictedYoutubeDL(options, auto_init=False) as ydl:
        ydl.add_info_extractor(YoutubeIE())
        info = ydl.extract_info(canonical_url(url), download=False, process=False, ie_key='Youtube')
        metadata = validate_metadata(info)
        video, audio = choose_formats(info)
        logger.info(f'Selected video={video.get("format_id")} audio={audio.get("format_id") if audio else "combined"}; protocol={video.get("protocol")}')
        tracks = [('áudio', audio, 'audio.m4a'), ('vídeo', video, 'video.mp4')] if audio else [('vídeo e áudio', video, 'video.mp4')]
        estimate = sum(f.get('filesize') or f.get('filesize_approx') or 0 for _, f, _ in tracks)
        reserve = int(metadata['duration'] * 32000) + 128*1024**2
        if estimate > MAX_BYTES:
            raise ValueError('As faixas selecionadas excedem o limite de 1 GB. Use um vídeo menor.')
        if shutil.disk_usage(folder).free < 2*estimate + reserve:
            raise ValueError('Sem espaço em disco para importar e preparar este vídeo.')
        write_progress(progress, message='Vídeo reconhecido. Preparando download…', **metadata)
        already = 0
        for label, fmt, filename in tracks:
            last_update = 0
            def hook(state):
                nonlocal last_update
                downloaded = state.get('downloaded_bytes', 0)
                if already + downloaded > MAX_BYTES:
                    raise ValueError('Download excedeu o limite de 1 GB.')
                now = time.monotonic()
                if now-last_update < 1 and state['status'] != 'finished':
                    return
                last_update = now
                if shutil.disk_usage(folder).free < reserve:
                    raise ValueError('Sem espaço livre suficiente para continuar a importação.')
                total = state.get('total_bytes') or state.get('total_bytes_estimate')
                fraction = f' {min(100, int(downloaded/total*100))}%' if total else f' {downloaded/1024**2:.1f} MB'
                write_progress(progress, message=f'Baixando {label}…{fraction}', **metadata)
            write_progress(progress, message=f'Baixando {label}…', **metadata)
            logger.info(f'Download stage: {label}; format={fmt.get("format_id")}')
            # Reutiliza metadados/URLs assinadas: não chama o extrator outra vez.
            ydl.params['outtmpl'] = {'default': str(folder / filename)}
            ydl._progress_hooks = [hook]
            track = {k: v for k, v in info.items() if k not in ('formats', 'requested_formats', 'requested_downloads', 'entries')}
            track.update(fmt)
            ydl.process_info(track)
            target = folder / filename
            if not target.is_file() or target.stat().st_size == 0:
                raise ValueError('O download não produziu um arquivo completo. Tente novamente.')
            already += target.stat().st_size
            if already > MAX_BYTES:
                raise ValueError('Download excedeu o limite de 1 GB.')
        return metadata


if __name__ == '__main__':
    # Apenas este worker recebe restrições de rede, sem afetar o servidor local.
    sys.addaudithook(network_guard)
    folder = Path(sys.argv[2])
    try:
        result = download(sys.argv[1], folder)
    except Exception as exc:
        ServerLogger().error('YouTube import failed:\n' + ''.join(traceback.format_exception(exc)))
        result = {'error': friendly_error(exc)}
    (folder / 'import-result.json').write_text(json.dumps(result), encoding='utf-8')
    sys.exit(1 if 'error' in result else 0)
