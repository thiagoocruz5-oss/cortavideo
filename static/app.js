const $ = id => document.getElementById(id);
let current = null, job = null, exporting = false;
function status(message, error = false) { $('status').hidden = false; $('status').textContent = message; $('status').className = error ? 'error' : ''; }
async function request(url, options) { const response = await fetch(url, options); const data = await response.json(); if (!response.ok) throw new Error(data.message || 'Não foi possível concluir.'); return data; }
async function poll(id, notify) { for (;;) { const result = await request(`/api/jobs/${id}`); if (result.status === 'error') throw new Error(result.message); if (result.status === 'ready') return result; notify(result.message); await new Promise(r => setTimeout(r, 1800)); } }
function clock(t) { return `${Math.floor(t / 60).toString().padStart(2, '0')}:${Math.floor(t % 60).toString().padStart(2, '0')}`; }
function values() { return {start: Number($('start').value), end: Number($('end').value)}; }
function validate() { const {start, end} = values(); const valid = $('start').value !== '' && $('end').value !== '' && start >= 0 && end <= job.duration && end - start >= 30 && end - start <= 60; $('duration').textContent = valid ? `${(end-start).toFixed(1)} segundos selecionados` : 'Selecione entre 30 e 60 segundos, dentro do vídeo.'; $('export').disabled = !valid || exporting; $('play').disabled = !valid; return valid; }
function select(c, index) { $('video').pause(); $('start').value = c.start; $('end').value = c.end; $('video').currentTime = c.start; $('download').hidden = true; document.querySelectorAll('.suggestion').forEach((el, i) => el.classList.toggle('selected', index === i)); validate(); caption(); }
function showEditor() { $('uploadSection').hidden = true; $('editor').hidden = false; $('step2').classList.add('active'); $('video').src = `/media/${current}/source.mp4`; $('suggestions').replaceChildren(); $('count').textContent = job.suggestions.length; job.suggestions.forEach((c, i) => { const button = document.createElement('button'); button.className = 'suggestion'; const title = document.createElement('strong'); title.textContent = `${String(i+1).padStart(2,'0')} / ${clock(c.start)} — ${clock(c.end)}`; const text = document.createElement('p'); text.textContent = c.text || 'Trecho sem fala. Ajuste o intervalo ao lado.'; button.append(title, text); button.onclick = () => select(c, i); $('suggestions').append(button); }); $('transcript').textContent = job.segments.map(s => `${clock(s.start)}  ${s.text}`).join('\n') || 'Nenhuma fala detectada.'; $('captions').disabled = !job.segments.length; $('captions').checked = !!job.segments.length; $('start').max = job.duration; $('end').max = job.duration; select(job.suggestions[0] || {start: 0, end: Math.min(45, job.duration)}, 0); }
async function upload(file) { if (!file) return; if (!file.name.toLowerCase().endsWith('.mp4') || file.size > 1024 ** 3) return status('Escolha um MP4 de até 1 GB.', true); $('file').disabled = true; status('Enviando vídeo…'); try { const result = await request('/api/upload', {method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:file}); current = result.id; job = await poll(current, message => status(message)); showEditor(); status(job.message); } catch (error) { status(error.message, true); } finally { $('file').disabled = false; $('file').value = ''; } }
$('file').onchange = e => upload(e.target.files[0]);
for (const type of ['dragenter','dragover']) $('drop').addEventListener(type, e => { e.preventDefault(); $('drop').classList.add('drag'); });
for (const type of ['dragleave','drop']) $('drop').addEventListener(type, e => { e.preventDefault(); $('drop').classList.remove('drag'); });
$('drop').addEventListener('drop', e => { if (!$('file').disabled) upload(e.dataTransfer.files[0]); });
for (const id of ['start','end']) $(id).oninput = () => { $('video').pause(); $('download').hidden = true; document.querySelectorAll('.suggestion').forEach(el => el.classList.remove('selected')); validate(); if (id === 'start') $('video').currentTime = Number($('start').value); caption(); };
function caption() { const t = $('video').currentTime; let text = ''; if (job && $('captions').checked) { for (const s of job.segments) { const words = s.words.length ? s.words : [s]; for (let i = 0; i < words.length; i += 6) { const group = words.slice(i, i+6); if (t >= group[0].start && t < group[group.length-1].end) text = group.map(w => w.text).join(' '); } } } $('caption').textContent = text; }
$('captions').onchange = () => { $('download').hidden = true; caption(); };
$('video').ontimeupdate = () => { caption(); if ($('video').currentTime >= Number($('end').value)) $('video').pause(); };
$('video').onpause = () => { $('play').textContent = '▶ Reproduzir trecho'; };
$('play').onclick = async () => { if (!$('video').paused) return $('video').pause(); if (!validate()) return; const {start,end} = values(); if ($('video').currentTime < start || $('video').currentTime >= end - .1) $('video').currentTime = start; try { await $('video').play(); $('play').textContent = 'Ⅱ Pausar'; } catch { status('O navegador não reproduz este codec. A exportação MP4 ainda pode funcionar.', true); } };
$('newVideo').onclick = () => { $('video').pause(); $('editor').hidden = true; $('uploadSection').hidden = false; $('status').hidden = true; $('step2').classList.remove('active'); $('step3').classList.remove('active'); };
$('export').onclick = async () => { if (!validate()) return; exporting = true; validate(); $('newVideo').disabled = true; $('download').hidden = true; $('export').textContent = 'Exportando…'; status('Preparando MP4 vertical…'); try { const result = await request('/api/export', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:current,...values(),captions:$('captions').checked})}); const finished = await poll(result.id, message => status(message)); $('download').href = finished.url; $('download').hidden = false; $('step3').classList.add('active'); status('Corte pronto! Baixe o MP4 para publicar.'); } catch(error) { status(error.message, true); } finally { exporting = false; $('export').textContent = 'Exportar corte ↗'; $('newVideo').disabled = false; validate(); } };
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
