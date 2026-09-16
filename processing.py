"""Pipeline local; framing_filter é o ponto de extensão para rastrear rostos."""
import json
import math
import os
import subprocess
import textwrap
import binaries
from pathlib import Path


def run(args, cwd=None):
    if args[0] in ('ffmpeg', 'ffprobe'):
        args = [binaries.require(args[0]), *args[1:]]
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=7200)
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:])
    return result.stdout


def probe(path):
    info = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))
    duration = float(info['format']['duration'])
    if not math.isfinite(duration) or duration < 30 or duration > 7200:
        raise ValueError('Envie um vídeo entre 30 segundos e 2 horas.')
    if not any(s['codec_type'] == 'video' for s in info['streams']):
        raise ValueError('O arquivo não contém vídeo.')
    if 'mp4' not in info['format']['format_name']:
        raise ValueError('Envie um arquivo MP4 válido.')
    return duration, any(s['codec_type'] == 'audio' for s in info['streams'])


def transcribe(path):
    from faster_whisper import WhisperModel
    # Futuro: cache de modelo e seleção de GPU, conforme a memória disponível.
    name = os.getenv('WHISPER_MODEL', 'base')
    local = Path(__file__).resolve().parent / 'models' / name
    if not (local / '.ready').is_file():
        raise RuntimeError('Modelo local ausente. Execute preparar_modelo.py antes de transcrever.')
    try:
        model = WhisperModel(str(local), device='cpu', compute_type='int8', local_files_only=True)
    except Exception as exc:
        raise RuntimeError('Não foi possível carregar o modelo de transcrição. Execute preparar_modelo.py com acesso à internet uma vez e tente novamente. O vídeo continua salvo no computador.') from exc
    segments, _ = model.transcribe(str(path), vad_filter=True, word_timestamps=True)
    return [{'start': s.start, 'end': s.end, 'text': s.text.strip(),
             'words': [{'start': w.start, 'end': w.end, 'text': w.word.strip()} for w in (s.words or [])]} for s in segments]


def suggest(segments, duration):
    # MVP: densidade de fala e finais de frase; futuro: avaliação semântica.
    candidates = []
    starts = [s['start'] for s in segments] or [0]
    for start in starts:
        if duration - start < 30:
            continue
        ends = [s['end'] for s in segments if start + 30 <= s['end'] <= min(duration, start + 60)]
        end = min(ends, key=lambda t: abs(t - start - 45)) if ends else min(duration, start + 45)
        selected = [s for s in segments if s['end'] > start and s['start'] < end]
        text = ' '.join(s['text'] for s in selected)
        score = len(text.split()) / (end - start) + (0.2 if text.endswith(('.', '!', '?')) else 0)
        candidates.append({'start': round(start, 2), 'end': round(end, 2), 'text': text, 'score': score})
    chosen = []
    for c in sorted(candidates, key=lambda c: c['score'], reverse=True):
        if all(max(0, min(c['end'], p['end']) - max(c['start'], p['start'])) < 15 for p in chosen):
            chosen.append(c)
        if len(chosen) == 6:
            break
    return sorted(chosen, key=lambda c: c['start'])


def framing_filter():
    # Futuro: receber uma estratégia de enquadramento com coordenadas de rostos.
    return 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1'


def stamp(seconds):
    ms = max(0, round(seconds * 1000))
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def subtitles(segments, start, end):
    cues = []
    for s in segments:
        words = s.get('words') or [s]
        for i in range(0, len(words), 6):
            group = words[i:i+6]
            a, b = max(start, group[0]['start']), min(end, group[-1]['end'])
            if b > a:
                text = ' '.join(w['text'] for w in group).replace('-->', '→').replace('<', '').replace('>', '').replace('{', '').replace('}', '').replace('\\', '')
                cues.append(f'{len(cues)+1}\n{stamp(a-start)} --> {stamp(b-start)}\n{textwrap.fill(text, 32)}\n')
    return '\n'.join(cues)


def export(folder, segments, start, end, captions, export_id):
    filters = framing_filter()
    if captions:
        name = f'{export_id}.srt'
        (folder / name).write_text(subtitles(segments, start, end), encoding='utf-8')
        filters += f",subtitles={name}:force_style='FontName=Arial,FontSize=20,Outline=2,MarginV=65'"
    output = f'{export_id}.mp4'
    run(['ffmpeg', '-y', '-v', 'error', '-ss', str(start), '-i', 'source.mp4', '-t', str(end-start),
         '-map', '0:v:0', '-map', '0:a:0?', '-vf', filters, '-c:v', 'libx264', '-preset', 'fast',
         '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output], cwd=folder)
    return output
