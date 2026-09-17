const $ = id => document.getElementById(id);
let current = null, job = null, exporting = false;
let activeCut = 0;
const cutPositions = new Map();
function status(message, error = false) { $('status').hidden = false; $('status').textContent = message; $('status').className = error ? 'error' : ''; }
async function request(url, options) {
  let response, body;
  try {
    response = await fetch(url, options);
    body = await response.text();
  } catch {
    throw new Error('A conexão com o servidor foi interrompida. Ele pode estar reiniciando. Aguarde e tente novamente.');
  }
  let data;
  try { data = JSON.parse(body); } catch {
    throw new Error(`O servidor retornou uma resposta vazia ou inválida (HTTP ${response.status}). Ele pode estar reiniciando por falta de memória. Aguarde e tente novamente.`);
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Resposta inesperada do servidor. Aguarde e tente novamente.');
  }
  if (!response.ok) throw new Error(data.message || `Não foi possível concluir (HTTP ${response.status}).`);
  return data;
}

async function poll(id, notify) { for (;;) { const result = await request(`/api/jobs/${id}`); if (result.status === 'error') throw new Error(result.message); if (result.status === 'ready') return result; notify(result.message); await new Promise(r => setTimeout(r, 1800)); } }
function clock(t) { return `${Math.floor(t / 60).toString().padStart(2, '0')}:${Math.floor(t % 60).toString().padStart(2, '0')}`; }
// Não reformata durante a digitação: apagar ou escrever uma vírgula é transitório.
function parseTime(text) {
  const value = text.trim().replace(',', '.');
  return /^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value) ? Number(value) : NaN;
}
function values() { return {start: parseTime($('start').value), end: parseTime($('end').value)}; }
function timeState(start, end, duration) {
  const finite = Number.isFinite(start) && Number.isFinite(end);
  const inside = finite && start >= 0 && end <= duration && end > start;
  let message = '';
  if (!finite) message = 'Digite início e fim em segundos, com ponto ou vírgula.';
  else if (start < 0) message = 'O início não pode ser negativo.';
  else if (end > duration) message = 'O fim não pode ultrapassar a duração do vídeo.';
  else if (end <= start) message = 'O fim deve ser maior que o início.';
  else if (end - start < 30 || end - start > 60) message = 'Selecione entre 30 e 60 segundos para exportar.';
  return {inside, valid: inside && !message, message};
}
function validate() {
  const {start, end} = values();
  const state = timeState(start, end, job.duration);
  const duration = Number.isFinite(end - start) && end > start ? `${(end-start).toFixed(2).replace('.', ',')} segundos selecionados. ` : '';
  $('duration').textContent = duration + state.message;
  $('export').disabled = !state.valid || exporting;
  $('play').disabled = !state.inside || exporting;
  return state.valid;
}
function editTime(id) {
  $('video').pause();
  $('download').hidden = true;
  $('finalPreview').hidden = true;
  $('finalVideo').pause();
  document.querySelectorAll('.suggestion').forEach(el => el.classList.remove('selected'));
  validate();
  const {start, end} = values();
  if (timeState(start, end, job.duration).inside) {
    // Ao editar o fim, mostra o último instante do trecho, sem ultrapassá-lo.
    $('video').currentTime = id === 'start' ? start : Math.max(start, end - 0.05);
  }
  caption();
}
function stepTime(id, delta) {
  if (exporting) return;
  const {start, end} = values();
  const current = id === 'start' ? start : end;
  if (!Number.isFinite(current)) return;
  const min = id === 'start' ? 0 : Math.max(0, start + 0.01);
  const max = id === 'end' ? job.duration : Math.min(job.duration, end - 0.01);
  if (!Number.isFinite(min) || !Number.isFinite(max) || min > max) return;
  const next = Math.max(min, Math.min(max, Math.round((current + delta) * 100) / 100));
  $(id).value = String(next).replace('.', ',');
  editTime(id);
}
function select(c, index) { activeCut = index; $('framing').value = cutPositions.get(`${current}:${index}`) ?? 50; updateFraming(); $('video').pause(); $('start').value = c.start; $('end').value = c.end; $('video').currentTime = c.start; $('download').hidden = true; $('finalPreview').hidden = true; $('finalVideo').pause(); document.querySelectorAll('.suggestion').forEach((el, i) => el.classList.toggle('selected', index === i)); validate(); caption(); }
function showEditor() { $('uploadSection').hidden = true; $('editor').hidden = false; $('step2').classList.add('active'); $('video').src = `/media/${current}/source.mp4`; $('suggestions').replaceChildren(); $('count').textContent = job.suggestions.length; job.suggestions.forEach((c, i) => { const button = document.createElement('button'); button.className = 'suggestion'; const title = document.createElement('strong'); title.textContent = `${String(i+1).padStart(2,'0')} / ${clock(c.start)} — ${clock(c.end)}`; const text = document.createElement('p'); text.textContent = c.text || 'Trecho sem fala. Ajuste o intervalo ao lado.'; button.append(title, text); button.onclick = () => select(c, i); $('suggestions').append(button); }); $('transcript').textContent = job.segments.map(s => `${clock(s.start)}  ${s.text}`).join('\n') || 'Nenhuma fala detectada.'; $('captions').disabled = !job.segments.length; $('captions').checked = !!job.segments.length; $('start').max = job.duration; $('end').max = job.duration; select(job.suggestions[0] || {start: 0, end: Math.min(45, job.duration)}, 0); }
async function upload(file) { if (!file) return; if (!file.name.toLowerCase().endsWith('.mp4') || file.size > 1024 ** 3) return status('Escolha um MP4 de até 1 GB.', true); $('file').disabled = true; status('Enviando vídeo…'); try { const result = await request('/api/upload', {method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:file}); current = result.id; job = await poll(current, message => status(message)); showEditor(); status(job.message); } catch (error) { status(error.message, true); } finally { $('file').disabled = false; $('file').value = ''; } }
$('file').onchange = e => upload(e.target.files[0]);
for (const type of ['dragenter','dragover']) $('drop').addEventListener(type, e => { e.preventDefault(); $('drop').classList.add('drag'); });
for (const type of ['dragleave','drop']) $('drop').addEventListener(type, e => { e.preventDefault(); $('drop').classList.remove('drag'); });
$('drop').addEventListener('drop', e => { if (!$('file').disabled) upload(e.dataTransfer.files[0]); });
for (const id of ['start','end']) $(id).oninput = () => editTime(id);
document.querySelectorAll('[data-time]').forEach(button => {
  button.onclick = () => stepTime(button.dataset.time, Number(button.dataset.delta));
});
function caption() {
  const t = $('video').currentTime;
  const cue = job && $('captions').checked && (job.caption_cues || []).find(c => t >= c.start && t < c.end);
  $('caption').textContent = cue ? cue.text : '';
}
$('captions').onchange = () => { $('download').hidden = true; $('finalPreview').hidden = true; $('finalVideo').pause(); caption(); };
$('video').ontimeupdate = () => { caption(); if (Number.isFinite(values().end) && $('video').currentTime >= values().end) $('video').pause(); };
$('video').onpause = () => { $('play').textContent = '▶ Reproduzir trecho'; };
$('play').onclick = async () => { if (!$('video').paused) return $('video').pause(); const {start,end} = values(); if (!timeState(start, end, job.duration).inside) return; if ($('video').currentTime < start || $('video').currentTime >= end - .1) $('video').currentTime = start; try { await $('video').play(); $('play').textContent = 'Ⅱ Pausar'; } catch { status('O navegador não reproduz este codec. A exportação MP4 ainda pode funcionar.', true); } };
$('newVideo').onclick = () => { $('video').pause(); $('editor').hidden = true; $('uploadSection').hidden = false; $('status').hidden = true; $('step2').classList.remove('active'); $('step3').classList.remove('active'); };
$('export').onclick = async () => { if (!validate()) return; exporting = true; validate(); for (const id of ['start','end','captions','framing']) $(id).disabled = true; document.querySelectorAll('.suggestion, [data-time]').forEach(el => el.disabled = true); $('newVideo').disabled = true; $('download').hidden = true; $('finalPreview').hidden = true; $('finalVideo').pause(); $('export').textContent = 'Exportando…'; status('Preparando MP4 vertical…'); try { const result = await request('/api/export', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:current,...values(),captions:$('captions').checked,position:Number($('framing').value)/100})}); const finished = await poll(result.id, message => status(message)); $('download').href = finished.url; $('finalVideo').src = finished.url; $('finalPreview').hidden = false; $('download').hidden = false; $('step3').classList.add('active'); status('Corte pronto! Baixe o MP4 para publicar.'); } catch(error) { status(error.message, true); } finally { exporting = false; for (const id of ['start','end','framing']) $(id).disabled = false; $('captions').disabled = !job.segments.length; document.querySelectorAll('.suggestion, [data-time]').forEach(el => el.disabled = false); $('export').textContent = 'Exportar corte ↗'; $('newVideo').disabled = false; validate(); } };
request('/api/health').then(h => { if (!h.ffmpeg || !h.ffprobe) status('Para processar vídeos, instale FFmpeg e ffprobe. Veja as instruções no README.', true); }).catch(() => status('Não foi possível conectar ao servidor local.', true));
const resumeId = new URLSearchParams(location.search).get('job');
if (resumeId && /^[a-f0-9]{32}$/.test(resumeId)) {
  current = resumeId;
  $('uploadSection').hidden = true;
  status('Recuperando seu vídeo…');
  poll(current, message => status(message)).then(result => {
    job = result;
    showEditor();
    status(job.message);
  }).catch(error => {
    status(error.message, true);
    $('uploadSection').hidden = false;
  });
}

function updateFraming() {
  const p = Math.max(0, Math.min(100, Number($('framing').value)));
  $('video').style.objectPosition = `${p}% 50%`;
  const label = p === 50 ? 'Centro' : p < 50 ? 'Esquerda' : 'Direita';
  $('framingValue').textContent = `${label} · ${p}%`;
  $('framing').setAttribute('aria-valuetext', `${label}, ${p}%`);
}
$('framing').oninput = () => {
  cutPositions.set(`${current}:${activeCut}`, Number($('framing').value));
  updateFraming();
  $('download').hidden = true;
  $('finalPreview').hidden = true;
  $('finalVideo').pause();
};
$('video').addEventListener('loadedmetadata', () => {
  updateFraming();
  const video = $('video');
  $('framingHint').textContent = video.videoWidth / video.videoHeight <= 9 / 16
    ? 'Este vídeo não tem sobra lateral; o enquadramento horizontal permanece fixo.'
    : 'A posição será aplicada ao MP4.';
});
