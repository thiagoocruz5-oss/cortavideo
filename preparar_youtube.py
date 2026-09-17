"""Verifica dependências do YouTube no build; não baixa nenhum vídeo."""
from youtube_import import node_runtime

if __name__ == '__main__':
    import yt_dlp
    import yt_dlp_ejs
    print('YouTube: yt-dlp/EJS disponíveis; Node:', node_runtime())
