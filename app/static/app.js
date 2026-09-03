const state = { streams: [], selected: null };
const $ = (id) => document.getElementById(id);

function setText(id, value) { $(id).textContent = value; }
function selectedStream() { return state.streams.find((s) => s.stream_id === state.selected); }

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
  return response.status === 204 ? null : response.json();
}

function renderMetrics() {
  setText('metric-streams', state.streams.length);
  setText('metric-yolo', state.streams.filter((s) => s.yolo_enabled).length);
  setText('metric-frames', state.streams.reduce((sum, s) => sum + s.frames_received, 0).toLocaleString());
  const modelError = state.streams.find((s) => s.last_error || s.model_error);
  setText('metric-model', modelError ? '检查' : state.streams.some((s) => s.yolo_enabled) ? '运行中' : '待命');
}

function renderStreams() {
  const list = $('stream-list');
  if (!state.streams.length) { list.innerHTML = '<div class="empty-state">还没有视频流会话<br><small>创建一个会话开始接入</small></div>'; return; }
  list.innerHTML = state.streams.map((s) => `<div class="stream-item ${s.stream_id === state.selected ? 'selected' : ''}" data-id="${encodeURIComponent(s.stream_id)}"><div class="stream-top"><span class="stream-name"><i class="status-dot ${s.frames_received ? '' : 'off'}"></i>${escapeHtml(s.stream_id)}</span><span class="pill ${s.yolo_enabled ? 'on' : 'muted'}">${s.yolo_enabled ? 'YOLO ON' : 'RAW'}</span></div><div class="stream-sub"><span>${s.frames_received.toLocaleString()} frames</span><span>${s.max_fps} FPS cap</span></div></div>`).join('');
  list.querySelectorAll('.stream-item').forEach((el) => el.addEventListener('click', () => selectStream(decodeURIComponent(el.dataset.id))));
}

function renderInspector() {
  const stream = selectedStream();
  $('inspector-empty').classList.toggle('hidden', Boolean(stream));
  $('inspector-content').classList.toggle('hidden', !stream);
  if (!stream) { setText('inspector-title', '选择一个流'); $('inspector-pill').textContent = '未选择'; return; }
  setText('inspector-title', stream.stream_id); $('inspector-pill').textContent = stream.yolo_enabled ? 'YOLO ACTIVE' : 'RAW OUTPUT'; $('inspector-pill').className = `pill ${stream.yolo_enabled ? 'on' : 'muted'}`;
  $('preview').src = `/api/streams/${encodeURIComponent(stream.stream_id)}/mjpeg?ts=${Date.now()}`;
  $('yolo-toggle').checked = stream.yolo_enabled; $('confidence').value = stream.confidence ?? .25; $('confidence-value').textContent = Number($('confidence').value).toFixed(2); $('max-fps').value = stream.max_fps ?? 20; $('fps-value').textContent = $('max-fps').value;
  setText('preview-label', stream.frames_received ? (stream.yolo_enabled ? 'YOLO OVERLAY' : 'RAW STREAM') : 'WAITING FOR FRAMES'); setText('preview-fps', `${stream.max_fps} FPS CAP`);
}

async function loadStreams() { try { state.streams = await api('/api/streams'); setText('service-state', '服务在线'); renderMetrics(); renderStreams(); renderInspector(); } catch (error) { setText('service-state', '服务离线'); console.error(error); } }
async function loadModels() { try { const response = await api('/api/models'); const models = response.models || []; setText('model-registry-state', `${models.length} ASSETS`); $('model-list').innerHTML = models.map((m) => `<div class="model-card ${m.hashValid ? '' : 'invalid'}"><div><h3>${escapeHtml(m.name)}</h3><p>${m.format.toUpperCase()} · ${m.inputSize || '-'} px · ${m.exists ? (m.hashValid ? 'HASH OK' : 'HASH MISMATCH') : 'FILE MISSING'}</p><small>${m.modelId}</small></div><button ${m.active ? 'disabled' : (!m.hashValid || !['pt','onnx'].includes(m.format) ? 'disabled' : '')} data-model="${encodeURIComponent(m.modelId)}">${m.active ? 'ACTIVE' : m.format === 'tflite' ? 'MOBILE ONLY' : '激活'}</button></div>`).join(''); $('model-list').querySelectorAll('button[data-model]').forEach((button) => button.addEventListener('click', async () => { try { await api(`/api/models/${decodeURIComponent(button.dataset.model)}/activate`, { method: 'POST' }); await loadModels(); await loadStreams(); } catch (error) { alert(error.message); } })); } catch (error) { setText('model-registry-state', '不可用'); console.error(error); } }
async function saveConfig(patch) { if (!state.selected) return; setText('save-state', '保存中…'); try { await api(`/api/streams/${encodeURIComponent(state.selected)}/config`, { method: 'PATCH', body: JSON.stringify(patch) }); await loadStreams(); setText('save-state', '已自动保存'); } catch (error) { setText('save-state', error.message); } }
function selectStream(id) { state.selected = id; renderStreams(); renderInspector(); }
function escapeHtml(value) { return value.replace(/[&<>"']/g, (c) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c])); }

$('new-stream-btn').addEventListener('click', () => $('new-stream-dialog').showModal());
$('register-model-btn').addEventListener('click', () => $('register-model-dialog').showModal());
$('refresh-btn').addEventListener('click', loadStreams);
$('new-stream-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const created = await api('/api/streams', { method: 'POST', body: JSON.stringify({ stream_id: $('stream-id').value.trim(), source_url: $('source-url').value.trim() || null }) }); $('new-stream-dialog').close(); $('stream-id').value = ''; $('source-url').value = ''; state.selected = created.stream_id; await loadStreams(); } catch (error) { alert(error.message); } });
$('register-model-form').addEventListener('submit', async (event) => { event.preventDefault(); try { await api('/api/models/register', { method: 'POST', body: JSON.stringify({ manifest_path: $('manifest-path').value.trim() }) }); $('register-model-dialog').close(); await loadModels(); } catch (error) { alert(error.message); } });
$('yolo-toggle').addEventListener('change', (event) => saveConfig({ yolo_enabled: event.target.checked }));
$('confidence').addEventListener('change', (event) => { setText('confidence-value', Number(event.target.value).toFixed(2)); saveConfig({ confidence: Number(event.target.value) }); });
$('max-fps').addEventListener('change', (event) => { setText('fps-value', event.target.value); saveConfig({ max_fps: Number(event.target.value) }); });
$('delete-btn').addEventListener('click', async () => { if (!state.selected || !confirm(`确认删除流「${state.selected}」？`)) return; try { await api(`/api/streams/${encodeURIComponent(state.selected)}`, { method: 'DELETE' }); state.selected = null; await loadStreams(); } catch (error) { alert(error.message); } });
setInterval(() => { setText('clock', new Date().toLocaleTimeString('zh-CN', { hour12: false })); }, 1000);
setInterval(loadStreams, 3000);
loadModels();
loadStreams();
