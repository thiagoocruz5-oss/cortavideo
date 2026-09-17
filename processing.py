"""Pipeline local; framing_filter é o ponto de extensão para rastrear rostos."""
import json
import math
import os
import sys
import uuid
import shutil
from contextlib import contextmanager
from process_runner import run_process
import textwrap
import binaries
from pathlib import Path


def run(args, cwd=None):
    if args[0] in ('ffmpeg', 'ffprobe'):
        args = [binaries.require(args[0]), *args[1:]]
    return run_process(args, cwd=cwd)



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


@contextmanager
def scratch_directory(parent):
    # Herda as ACLs no Windows; mkdir(0700) pode excluir o usuário do sandbox.
    folder = Path(parent) / ('transcribe-' + uuid.uuid4().hex)
    folder.mkdir(mode=0o777 if os.name == 'nt' else 0o700)
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


def transcribe(path, progress=None):
    path = Path(path).resolve()
    # FFmpeg termina ANTES do carregamento do modelo, evitando somar os picos.
    with scratch_directory(path.parent) as scratch:
        wav = Path(scratch) / 'audio.wav'
        result = Path(scratch) / 'transcript.json'
        state = Path(scratch) / 'progress.json'
        last_progress = None
        def report():
            nonlocal last_progress
            if progress and state.is_file():
                try:
                    value = json.loads(state.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    return
                if value != last_progress:
                    progress(**value)
                    last_progress = value
        if progress:
            progress(message='Extraindo áudio mono/16 kHz…')
        run(['ffmpeg', '-y', '-v', 'error', '-threads', '1', '-i', str(path),
             '-vn', '-sn', '-dn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)])
        run_process([sys.executable, str(Path(__file__).with_name('transcription_worker.py')),
                     str(wav), str(result), str(state)], on_tick=report)
        return json.loads(result.read_text(encoding='utf-8'))


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


def framing_filter(position=0.5):
    # Futuro: receber uma estratégia de enquadramento com coordenadas de rostos.
    position = float(position)
    if not math.isfinite(position) or not 0 <= position <= 1:
        raise ValueError('Enquadramento deve estar entre 0 e 1.')
    # Equivalente a object-fit: cover + object-position: p% 50%.
    # dar considera pixels não quadrados; o resultado usa pixels quadrados.
    # exact=1 evita que o crop arredonde x para múltiplos de 2 (chroma 4:2:0).
    return ("scale=w='ceil(max(720,1280*dar))':h='ceil(max(1280,720/dar))',setsar=1,"
            f'crop=720:1280:x=round((iw-ow)*{position}):y=round((ih-oh)/2):exact=1')


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


def caption_cues(segments):
    """Texto e quebras compartilhados pela prévia e pelo renderizador ASS."""
    cues = []
    for segment in segments:
        words = segment.get('words') or [segment]
        for i in range(0, len(words), 6):
            group = words[i:i + 6]
            text = ' '.join(w['text'] for w in group)
            text = ' '.join(text.replace('\\', '').replace('{', '').replace('}', '').split())
            lines = textwrap.wrap(text, width=26, break_long_words=True, break_on_hyphens=False)
            # Grupos muito longos são divididos em blocos de no máximo duas linhas.
            chunks = ['\n'.join(lines[n:n + 2]) for n in range(0, len(lines), 2)]
            for n, chunk in enumerate(chunks):
                length = (group[-1]['end'] - group[0]['start']) / len(chunks)
                cues.append({'start': group[0]['start'] + n * length,
                             'end': group[0]['start'] + (n + 1) * length, 'text': chunk})
    return cues


def ass_subtitles(segments, start, end):
    # Coordenadas explícitas evitam a resolução implícita do SRT/libass.
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,43,43,205,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    def timecode(value):
        cs = max(0, round(value * 100))
        return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'
    events = []
    for cue in caption_cues(segments):
        a, b = max(start, cue['start']), min(end, cue['end'])
        if b > a:
            text = cue['text'].replace('\n', r'\N')
            events.append(f'Dialogue: 0,{timecode(a-start)},{timecode(b-start)},Default,,0,0,0,,{text}')
    return header + '\n'.join(events) + '\n'


def export(folder, segments, start, end, captions, export_id, position=0.5):
    filters = framing_filter(position)
    if captions:
        name = f'{export_id}.ass'
        (folder / name).write_text(ass_subtitles(segments, start, end), encoding='utf-8')
        filters += f',ass={name}'
    output = f'{export_id}.mp4'
    try:
        run(['ffmpeg', '-y', '-v', 'error', '-threads', '1', '-filter_threads', '1',
             '-ss', str(start), '-i', 'source.mp4', '-t', str(end-start),
             '-map', '0:v:0', '-map', '0:a:0?', '-vf', filters, '-c:v', 'libx264',
             # veryfast reduz custo de CPU; zerolatency evita buffers de lookahead.
             '-threads', '1', '-preset', 'veryfast', '-tune', 'zerolatency',
             '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
             '-movflags', '+faststart', output], cwd=folder)
        return output
    except BaseException:
        (folder / output).unlink(missing_ok=True)
        raise
    finally:
        (folder / f'{export_id}.ass').unlink(missing_ok=True)
