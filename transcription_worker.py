"""Processo isolado: somente aqui são importadas as bibliotecas do Whisper."""
import json
import os
import sys
import wave
from pathlib import Path
from runtime_config import low_memory, model_name


def windows(total, rate, seconds=28, context=2):
    step, padding = seconds * rate, context * rate
    for core in range(0, total, step):
        yield max(0, core-padding), min(total, core+step+padding), core, min(total, core+step)


def write_progress(path, **values):
    if path:
        target = Path(path)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(values), encoding='utf-8')
        temporary.replace(target)


def transcribe_wav(source, destination, progress=None):
    write_progress(progress, message='Carregando modelo de transcrição…')
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    import numpy as np
    from faster_whisper import WhisperModel
    model_path = Path(__file__).resolve().parent / 'models' / model_name()
    if not (model_path / '.ready').is_file():
        raise RuntimeError('Modelo local ausente. Execute a preparação do modelo no build.')
    model = WhisperModel(str(model_path), device='cpu', compute_type='int8',
                         cpu_threads=1, num_workers=1, local_files_only=True)
    language = None
    lean = low_memory()
    seconds = 56 if lean else 28
    options = {'temperature': 0.0, 'best_of': 1} if lean else {}
    with wave.open(str(source), 'rb') as wav, open(destination, 'w', encoding='utf-8') as output:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('Áudio temporário inválido.')
        total, rate = wav.getnframes(), wav.getframerate()
        output.write('[')
        separator = ''
        count = (total + seconds * rate - 1) // (seconds * rate)
        for index, (first, last, core, core_end) in enumerate(windows(total, rate, seconds=seconds), 1):
            write_progress(progress, message=f'Transcrevendo bloco {index} de {count}', block=index, blocks=count, completed=index-1)
            wav.setpos(first)
            audio = np.frombuffer(wav.readframes(last-first), dtype='<i2').astype(np.float32)
            audio /= 32768.0
            segments, info = model.transcribe(audio, language=language, vad_filter=True,
                                             word_timestamps=True, beam_size=1 if lean else 5,
                                             condition_on_previous_text=False, **options)
            for segment in segments:
                words = []
                for word in segment.words or []:
                    a, b = first/rate + word.start, first/rate + word.end
                    # Contexto sobreposto, mas cada palavra pertence a um só bloco.
                    if core/rate <= (a+b)/2 < core_end/rate:
                        words.append({'start': max(core/rate, a), 'end': min(core_end/rate, b),
                                      'text': word.word.strip()})
                if words:
                    language = info.language
                    row = {'start': words[0]['start'], 'end': words[-1]['end'],
                           'text': ' '.join(w['text'] for w in words), 'words': words}
                    output.write(separator + json.dumps(row, ensure_ascii=False))
                    separator = ','
            del segments, audio
            write_progress(progress, message=f'Bloco {index} de {count} concluído', block=index, blocks=count, completed=index)
        output.write(']')
    # Processo termina: pesos e alocações nativas são devolvidos ao SO.


if __name__ == '__main__':
    transcribe_wav(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
