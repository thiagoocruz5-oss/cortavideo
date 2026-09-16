"""Baixe uma vez; o servidor usará a cópia local sem acessar o Hub."""
import os
from pathlib import Path
os.environ.setdefault('HF_HOME', str(Path(__file__).resolve().parent / 'models' / '.cache'))
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model


def main():
    name = os.getenv('WHISPER_MODEL', 'base')
    folder = Path(__file__).resolve().parent / 'models' / name
    folder.mkdir(parents=True, exist_ok=True)
    print('Baixando modelo de transcricao: ' + name, flush=True)
    download_model(name, output_dir=str(folder))
    WhisperModel(str(folder), device='cpu', compute_type='int8', local_files_only=True)
    (folder / '.ready').write_text(name, encoding='utf-8')
    print('Modelo verificado. A transcricao pode funcionar offline.', flush=True)


if __name__ == '__main__':
    main()
