"""Baixe uma vez; o servidor usará a cópia local sem acessar o Hub."""
import os
from pathlib import Path
from runtime_config import model_name
os.environ.setdefault('HF_HOME', str(Path(__file__).resolve().parent / 'models' / '.cache'))
ROOT = Path(__file__).resolve().parent
REQUIRED_FILES = ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')


def model_complete(folder):
    return all((folder / name).is_file() and (folder / name).stat().st_size > 0
               for name in REQUIRED_FILES)


def main():
    name = model_name()
    # Mesma pasta e WHISPER_MODEL utilizados por processing.transcribe.
    folder = ROOT / 'models' / name
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / '.ready'
    if marker.exists():
        marker.unlink()  # Só marca pronto após a validação desta execução.
    from faster_whisper import WhisperModel
    if not model_complete(folder):
        from faster_whisper.utils import download_model
        print('Baixando modelo de transcricao: ' + name, flush=True)
        download_model(name, output_dir=str(folder))
    if not model_complete(folder):
        raise RuntimeError('Download incompleto do modelo. O deploy foi interrompido.')
    print('Validando modelo local: ' + name, flush=True)
    WhisperModel(str(folder), device='cpu', compute_type='int8', local_files_only=True)
    marker.write_text(name, encoding='utf-8')
    print('Modelo verificado. A transcricao pode funcionar offline.', flush=True)


if __name__ == '__main__':
    main()
