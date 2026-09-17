"""Verifica dependências do YouTube no build; não baixa nenhum vídeo."""
from youtube_import import node_runtime
from importlib.metadata import version
import subprocess

if __name__ == '__main__':
    import yt_dlp
    import yt_dlp_ejs
    node = node_runtime()
    print('YouTube: yt-dlp=' + version('yt-dlp') + ' EJS=' + version('yt-dlp-ejs'))
    print('Node:', subprocess.check_output([node, '--version'], text=True, timeout=5).strip())
