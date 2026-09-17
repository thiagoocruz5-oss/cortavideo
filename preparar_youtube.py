"""Verifica dependências do YouTube no build; não baixa nenhum vídeo."""
from youtube_import import node_runtime
from importlib.metadata import version
import subprocess
import sys
from pathlib import Path
import re

if __name__ == '__main__':
    import yt_dlp
    import yt_dlp_ejs
    node = node_runtime()
    expected = re.search(r'yt-dlp\[default\]==([^\s]+)', Path(__file__).with_name('requirements.txt').read_text()).group(1)
    installed = version('yt-dlp')
    if tuple(map(int, installed.split('.'))) != tuple(map(int, expected.split('.'))):
        raise RuntimeError(f'yt-dlp instalado {installed}, esperado {expected}. Reinstale requirements.txt.')
    print('Python:', sys.version.split()[0])
    print('YouTube: yt-dlp=' + version('yt-dlp') + ' EJS=' + version('yt-dlp-ejs'))
    print('Node:', subprocess.check_output([node, '--version'], text=True, timeout=5).strip())
