/* Real model operations are explicit, async and independent of prototype cards. */
(() => {
  'use strict';
  const host = document.querySelector('#view-models');
  if (!host) return;
  const calibrationPanel = document.createElement('section');
  calibrationPanel.className = 'conversion-panel calibration-manager';
  calibrationPanel.innerHTML = `
    <div class="conversion-heading"><div><span class="eyebrow">CALIBRATION ASSETS</span><h3 id="calibration-title">校准集资产</h3><p>按业务场景独立管理图片校准集。每个版本都有固定内容哈希，转换任务会保留当时的引用。</p></div><div class="calibration-summary"><b id="calibration-count">0</b><span>个档案</span><button class="ghost-btn" id="calibration-refresh" type="button">刷新</button></div></div>
    <div class="calibration-layout">
      <form id="calibration-upload-form" class="calibration-upload-form">
        <label class="conversion-drop calibration-drop"><input id="calibration-file" type="file" accept=".zip,application/zip" required><b>选择校准图片 ZIP</b><small id="calibration-file-name">尚未选择文件</small></label>
        <div class="conversion-fields"><label class="field">名称<input id="calibration-name" maxlength="100" required placeholder="例如：工地巡检"></label><label class="field">版本<input id="calibration-version" maxlength="50" value="1.0.0" required></label></div>
        <label class="field">场景<input id="calibration-scenario" maxlength="100" value="general-detection" required></label>
        <button class="primary-btn" type="submit">上传校准集</button>
        <progress class="conversion-upload-progress" id="calibration-progress" max="100" value="0" aria-label="校准集上传进度"></progress>
      </form>
      <div class="calibration-library"><div class="calibration-library-heading"><strong>已登记版本</strong><span>系统测试集不可删除；已被任务引用的版本受保护。</span></div><div id="calibration-list" class="calibration-list"><p>正在读取校准集。</p></div></div>
    </div>
    <div id="calibration-feedback" class="conversion-feedback" role="status" aria-live="polite"></div>`;
  const panel = document.createElement('section');
  panel.className = 'conversion-panel';
  panel.innerHTML = `
    <div class="conversion-heading"><div><span class="eyebrow">UPLOAD WORKSPACE</span><h3>上传训练模型</h3><p>选择 .pt 文件，确认名称后即可验证。转换环境和令牌只在需要时展开。</p></div><span class="conversion-mode-label" id="conversion-mode-label">尚未连接管理服务 · 操作未启用</span></div>
    <p class="conversion-auth-note">已使用当前管理员登录会话访问管理服务，页面不再单独填写访问令牌。</p>
    <details id="conversion-settings"><summary>转换环境配置</summary>
      <form id="conversion-config-form">
        <div class="conversion-fields"><label class="field">执行方式<select id="conversion-mode"><option value="wsl">本机 WSL</option><option value="local">本机 Python</option><option value="remote">远程转换服务</option></select></label><label class="field" id="conversion-distribution-field">WSL 发行版<input id="conversion-distribution" value="Ubuntu" required></label></div>
        <label class="field">虚拟环境 Python 路径 <span id="conversion-python-purpose">用于转换与复验</span><input id="conversion-python" required placeholder="/home/用户名/转换环境/bin/python"></label>
        <div id="conversion-remote-fields" hidden>
          <label class="field">远程服务地址<input id="conversion-remote-endpoint" type="url" placeholder="https://converter.example.com" autocomplete="off"></label>
          <div class="conversion-fields"><label class="field">令牌环境变量名<input id="conversion-remote-token-env" value="AIYOLO_REMOTE_CONVERSION_TOKEN" autocomplete="off"></label><label class="field">轮询间隔（秒）<input id="conversion-remote-poll" type="number" min="0.5" max="30" step="0.5" value="2"></label></div>
          <div class="conversion-fields"><label class="field">下载后本地复验方式<select id="conversion-remote-verifier"><option value="wsl">WSL Python</option><option value="local">本机 Python</option></select></label><label class="conversion-check"><input id="conversion-remote-http" type="checkbox">允许 HTTP（仅本机开发）</label></div>
          <p>真实 Bearer 令牌只从服务进程环境读取，页面不输入也不回显令牌。远端结果下载后仍由上方 Python 环境复验。</p>
        </div>
        <div class="conversion-fields"><label class="field">新上传模型输入尺寸<select id="conversion-size"><option>640</option><option>416</option><option>320</option></select></label><label class="field">执行超时（秒）<input id="conversion-timeout" type="number" min="30" max="7200" value="1800" required></label></div>
        <label class="field">自动转换默认校准集<select id="conversion-default-calibration" required></select></label>
        <p>默认档案只用于自动转换；手动生成移动端模型时可另选校准集。</p>
        <label class="conversion-check"><input id="conversion-auto" type="checkbox">PT 验证成功后自动生成移动端产物</label>
        <div class="conversion-actions"><button class="primary-btn" type="submit">保存配置</button><button class="ghost-btn" id="conversion-check" type="button">检测已保存环境</button></div>
        <p id="conversion-workspace"></p><p>串行执行 1 个任务；local、WSL 与 remote 共用同一持久化任务队列。</p>
      </form>
    </details>
    <div class="conversion-grid"><form id="conversion-upload-form">
        <label class="conversion-drop" id="conversion-drop"><input id="conversion-file" type="file" accept=".pt" required><span class="conversion-file-mark" aria-hidden="true">PT</span><b id="conversion-file-title">把 .pt 文件拖到这里，或点击选择</b><small id="conversion-file-name" aria-live="polite">尚未选择文件</small><span class="conversion-file-meta" id="conversion-file-meta">仅支持 PyTorch .pt 权重文件</span></label>
        <div class="conversion-fields"><label class="field">模型名称<input id="conversion-name" maxlength="100" required placeholder="例如：工地安全帽检测"></label><label class="field">版本<input id="conversion-version" maxlength="50" value="1.0.0" required></label></div>
        <div class="conversion-fields"><label class="field">场景<input id="conversion-scenario" maxlength="100" value="general-detection" required></label><label class="field">用途<select id="conversion-purpose"><option value="development">功能测试</option><option value="business">业务候选</option></select></label></div>
        <label class="field">本次移动端转换校准集<select id="conversion-calibration-select" required></select></label>
        <p class="conversion-note">这里仅选择已登记校准集。新增、查看版本或删除校准集请前往“校准集”页签。</p>
        <p class="conversion-note">上传不会替换正在运行的视频流。COCO 仅用于功能测试。</p>
        <button class="primary-btn" id="conversion-upload" type="submit">上传并验证 PT</button>
        <div class="conversion-upload-status" id="conversion-upload-status" hidden><div><span>正在上传 PT</span><b id="conversion-upload-percent">0%</b></div><progress class="conversion-upload-progress" id="conversion-progress" max="100" value="0" aria-label="模型上传进度"></progress></div>
      </form>
      <div><div class="conversion-heading"><div><h3>处理任务</h3><p>关闭页面后继续执行，失败可重试。</p></div><button class="ghost-btn" id="conversion-refresh" type="button">刷新</button></div><div id="conversion-jobs" class="conversion-jobs"><p>连接管理服务后查看真实任务。</p></div></div>
    </div><div id="conversion-feedback" class="conversion-feedback" role="status" aria-live="polite"></div>`;
  const calibrationWorkspace = host.querySelector('#model-calibration-workspace');
  const workspace = host.querySelector('#model-conversion-workspace');
  if (calibrationWorkspace) calibrationWorkspace.append(calibrationPanel);
  if (workspace) workspace.append(panel); else host.querySelector('.section-intro').after(panel);
  const byId = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const message = (value, error = false, surface = 'conversion') => {
    const targetPane = surface === 'calibration' ? 'calibration' : 'upload';
    const el = byId(surface === 'calibration' ? 'calibration-feedback' : 'conversion-feedback');
    if (el) { el.textContent = value; el.classList.toggle('conversion-error', error); }
    const banner = byId('model-operation');
    if (!banner) return;
    const showBanner = Boolean(value) && (error || surface === 'banner' || state.modelPane !== targetPane);
    banner.classList.toggle('hidden', !showBanner);
    banner.classList.toggle('conversion-error', error);
    banner.innerHTML = showBanner ? `<b>${error ? '操作失败' : '操作完成'}</b><span>${safe(value)}</span>` : '';
  };
  const headers = () => ({});
  async function api(path, options = {}) {
    const response = await fetch(path, {...options, headers: {...headers(), ...options.headers}});
    const content = await response.text();
    let body;
    try { body = JSON.parse(content); } catch (_) { body = content; }
    if (!response.ok) {
      let reason = body?.detail?.message || body?.detail || body?.error?.message || `HTTP ${response.status}`;
      if (typeof reason !== 'string') reason = JSON.stringify(reason);
      throw new Error(reason);
    }
    return body;
  }
  let connected = false, refreshing = false, uploading = false, jobs = [], lastJobs = '', calibrationDatasets = [];
  function renderModeFields() {
    const remote = byId('conversion-mode').value === 'remote';
    const verifierWsl = !remote || byId('conversion-remote-verifier').value === 'wsl';
    byId('conversion-remote-fields').hidden = !remote;
    byId('conversion-remote-endpoint').required = remote;
    byId('conversion-remote-token-env').required = remote;
    byId('conversion-distribution-field').hidden = !verifierWsl;
    byId('conversion-distribution').required = verifierWsl;
    byId('conversion-python-purpose').textContent = remote ? '用于下载后本地复验' : '用于转换与复验';
  }
  byId('conversion-mode').addEventListener('change', renderModeFields);
  byId('conversion-remote-verifier').addEventListener('change', renderModeFields);
  const formatFileSize = bytes => {
    if (!Number.isFinite(bytes) || bytes <= 0) return '大小未知';
    const units = ['B', 'KB', 'MB', 'GB'];
    const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const value = bytes / Math.pow(1024, unit);
    return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
  };
  function renderSelectedModelFile(file) {
    const selected = Boolean(file);
    const drop = byId('conversion-drop');
    drop.classList.toggle('is-selected', selected);
    byId('conversion-file-title').textContent = selected ? '已选择训练模型' : '把 .pt 文件拖到这里，或点击选择';
    byId('conversion-file-name').textContent = selected ? file.name : '尚未选择文件';
    byId('conversion-file-meta').textContent = selected ? `${formatFileSize(file.size)} · PT 权重文件` : '仅支持 PyTorch .pt 权重文件';
  }
  function resetModelUploadState() {
    byId('conversion-file').value = '';
    byId('conversion-name').value = '';
    renderSelectedModelFile(null);
    const progress = byId('conversion-progress');
    progress.value = 0;
    byId('conversion-upload-percent').textContent = '0%';
    byId('conversion-upload-status').hidden = true;
  }
  function applySelectedFile(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pt')) { message('请选择 .pt 权重文件', true); return; }
    const picker = byId('conversion-file');
    const transfer = new DataTransfer();
    transfer.items.add(file);
    picker.files = transfer.files;
    renderSelectedModelFile(file);
    if (!byId('conversion-name').value.trim()) byId('conversion-name').value = file.name.replace(/\.pt$/i, '');
  }
  byId('conversion-file').addEventListener('change', () => {
    const file = byId('conversion-file').files[0];
    renderSelectedModelFile(file);
    if (file && !byId('conversion-name').value.trim()) byId('conversion-name').value = file.name.replace(/\.pt$/i, '');
  });
  const drop = byId('conversion-drop');
  ['dragenter', 'dragover'].forEach(type => drop.addEventListener(type, event => { event.preventDefault(); drop.classList.add('is-over'); }));
  ['dragleave', 'drop'].forEach(type => drop.addEventListener(type, event => { event.preventDefault(); drop.classList.remove('is-over'); }));
  drop.addEventListener('drop', event => applySelectedFile(event.dataTransfer.files[0]));
  function liveControls() {
    const live = !state.demo && connected;
    byId('conversion-mode-label').textContent = state.demo ? '演示模式 · 操作未启用' : connected ? '已连接 · 真实模型处理' : '尚未连接管理服务';
    const badge = document.querySelector('.demo-badge'); if (badge) badge.textContent = state.demo ? 'DEMO MODE' : 'LIVE API';
    panel.querySelectorAll('form button').forEach(button => button.disabled = !live || uploading);
    calibrationPanel.querySelectorAll('form button').forEach(button => button.disabled = !live || uploading);
    byId('conversion-refresh').disabled = !live;
    byId('calibration-refresh').disabled = !live;
    byId('conversion-jobs').querySelectorAll('button').forEach(button => button.disabled = !live);
    byId('calibration-list').querySelectorAll('button').forEach(button => button.disabled = !live);
  }
  const datasetLabel = item => `${item.name} · ${item.version}${item.builtin ? ' · 测试' : ''}`;
  function renderCalibrationDatasets() {
    const defaultSelect = byId('conversion-default-calibration');
    const taskSelect = byId('conversion-calibration-select');
    const defaultValue = defaultSelect.value;
    const taskValue = taskSelect.value;
    const options = calibrationDatasets.filter(item => item.status === 'ready').map(item => `<option value="${safe(item.datasetId)}">${safe(datasetLabel(item))}</option>`).join('');
    defaultSelect.innerHTML = options;
    taskSelect.innerHTML = options;
    if (calibrationDatasets.some(item => item.datasetId === defaultValue)) defaultSelect.value = defaultValue;
    if (calibrationDatasets.some(item => item.datasetId === taskValue)) taskSelect.value = taskValue;
    byId('calibration-count').textContent = String(calibrationDatasets.length);
    byId('calibration-list').innerHTML = calibrationDatasets.length ? calibrationDatasets.map(item => `<article class="calibration-row"><div class="calibration-state ${safe(item.status)}" aria-hidden="true"></div><div><div class="calibration-row-title"><strong>${safe(item.name)}</strong><span>${safe(item.version)}</span></div><small>${safe(item.scenario)} · ${item.imageCount} 张 · ${item.builtin ? '系统档案' : Math.max(1, Math.round(item.sizeBytes / 1024 / 1024)) + ' MB'}</small><code>${safe(String(item.contentSha256).slice(0, 16))}</code></div>${item.deletable ? `<button class="ghost-btn" type="button" data-delete-calibration="${safe(item.datasetId)}" title="删除校准集">删除</button>` : '<span class="pill muted">测试</span>'}</article>`).join('') : '<p>暂无可用校准集。</p>';
    liveControls();
  }
  async function readCalibrationDatasets() {
    const data = await api('/api/conversion/calibration-datasets');
    calibrationDatasets = data.datasets || [];
    renderCalibrationDatasets();
  }
  async function readConfig() {
    const data = await api('/api/conversion/config'); const c = data.config;
    await readCalibrationDatasets();
    byId('conversion-mode').value = c.mode;
    byId('conversion-distribution').value = c.distribution;
    byId('conversion-python').value = c.python_path;
    byId('conversion-size').value = c.input_size;
    byId('conversion-default-calibration').value = c.default_calibration_dataset_id || 'coco8-dev';
    byId('conversion-calibration-select').value = c.default_calibration_dataset_id || 'coco8-dev';
    byId('conversion-timeout').value = c.timeout_seconds;
    byId('conversion-auto').checked = c.auto_convert;
    byId('conversion-remote-endpoint').value = c.remote_endpoint || '';
    byId('conversion-remote-token-env').value = c.remote_token_env || 'AIYOLO_REMOTE_CONVERSION_TOKEN';
    byId('conversion-remote-http').checked = Boolean(c.remote_allow_insecure_http);
    byId('conversion-remote-poll').value = c.remote_poll_interval_seconds || 2;
    byId('conversion-remote-verifier').value = c.remote_verifier_mode || 'wsl';
    renderModeFields();
    byId('conversion-workspace').textContent = `工作目录：${data.workspace} · 上传上限 ${Math.round(data.max_upload_bytes / 1048576)} MB`;
    if (!c.python_path) byId('conversion-settings').open = true;
    connected = true; liveControls();
  }
  const labels = {queued:'排队中',running:'执行中',succeeded:'完成',failed:'失败',interrupted:'已中断'};
  const actions = {check:'环境检测',inspect:'PT 验证',mobile:'移动端转换'};
  const formatDuration = seconds => {
    const value = Math.max(0, Math.floor(seconds || 0));
    if (value < 60) return `${value} 秒`;
    const minutes = Math.floor(value / 60);
    const remaining = value % 60;
    if (minutes < 60) return `${minutes} 分 ${remaining} 秒`;
    return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
  };
  const jobTiming = job => {
    if (job.status === 'queued') return `已等待 ${formatDuration(Date.now() / 1000 - job.created_at)}`;
    if (!job.started_at) return '';
    const end = job.completed_at || Date.now() / 1000;
    return `${['succeeded','failed','interrupted'].includes(job.status) ? '耗时' : '已运行'} ${formatDuration(end - job.started_at)}`;
  };
  const renderJobProgress = job => {
    if (!['queued','running'].includes(job.status)) return '';
    const exact = Number.isFinite(job.progress);
    const queue = job.status === 'queued' && job.queue_position ? ` · 队列第 ${job.queue_position} 位` : '';
    const label = `${job.stage_label || labels[job.status]}${queue}`;
    const detail = job.progress_message && job.progress_message !== label ? `<small>${safe(job.progress_message)}</small>` : '';
    const bar = exact
      ? `<div class="conversion-progress-track" role="progressbar" aria-label="${safe(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${job.progress}"><span style="width:${job.progress}%"></span></div>`
      : `<div class="conversion-progress-track is-indeterminate" role="progressbar" aria-label="${safe(label)}"><span></span></div>`;
    return `<div class="conversion-job-progress"><div><strong>${safe(label)}</strong><b>${exact ? `${job.progress}%` : '处理中'}</b></div>${bar}${detail}</div>`;
  };
  async function refresh() {
    if (!connected || state.demo || refreshing) return;
    refreshing = true;
    try {
      jobs = (await api('/api/conversion/jobs')).jobs;
      const signature = JSON.stringify(jobs);
      lastJobs = signature;
      byId('conversion-jobs').innerHTML = jobs.length ? jobs.slice(0, 20).map(job => {
        const metadata = job.metadata || {};
        const result = job.result || {};
        const conversion = jobs.find(other => other.action === 'mobile' && (other.metadata || {}).upload_id === metadata.upload_id);
        const canConvert = job.action === 'inspect' && job.status === 'succeeded' && !conversion;
        const text = job.error || result.auto_conversion_error || (job.action === 'check' && job.status === 'succeeded' ? `Python ${result.python || ''} · ${result.mobile_available ? '移动端导出依赖就绪' : result.message || '移动端依赖未就绪'}` : '');
        const calibration = metadata.calibration_dataset;
        const mobileReady = Boolean(
          result.android_ready ||
          (conversion?.status === 'succeeded' && conversion.result?.android_ready === true),
        );
        return `<article class="conversion-job"><div class="conversion-job-top"><strong>${safe(actions[job.action])} · ${safe(metadata.name || '转换环境')}</strong><span class="conversion-job-status ${safe(job.status)}">${safe(labels[job.status])}</span></div><small>${safe(new Date(job.created_at * 1000).toLocaleString())} · 第 ${job.attempt} 次执行 · ${safe(jobTiming(job))}${calibration ? ' · ' + safe(calibration.name + ' ' + calibration.version) : ''}</small>${renderJobProgress(job)}${result.server_ready ? '<div class="conversion-state-pair"><span>服务端已验证</span><span>' + (mobileReady ? '移动端产物已验证' : '移动端单独处理') + '</span></div>' : ''}${text ? `<p class="${job.error ? 'conversion-error' : ''}">${safe(text)}</p>` : ''}<div class="conversion-actions">${['failed','interrupted'].includes(job.status) ? `<button class="ghost-btn" data-retry="${job.id}">按当前配置重试</button>` : ''}${canConvert ? `<button class="ghost-btn" data-convert="${metadata.upload_id}">生成移动端模型</button>` : ''}<button class="ghost-btn" data-log="${job.id}">查看日志</button></div></article>`;
      }).join('') : '<p>暂无任务。上传 PT 或检测转换环境后，任务会显示在这里。</p>';
      liveControls();
      await refreshLiveModels();
    } catch (error) { message(`任务读取失败：${error.message}`, true); }
    finally { refreshing = false; }
  }
  async function connect() {
    try {
      await readConfig();
      state.demo = false; state.models = []; state.streams = [];
      byId('mode-toggle').innerHTML = '返回 Demo 模式 <span>→</span>';
      liveControls();
      await Promise.all([refresh(), refreshLiveModels(), refreshLiveStreams()]);
      message('已连接。上传、配置和任务操作将使用真实服务。');
    } catch (error) { connected = false; liveControls(); message(`连接失败：${error.message}`, true); }
  }
  byId('conversion-config-form').addEventListener('submit', async event => {
    event.preventDefault(); if (state.demo || !connected) return;
    const config = {mode:byId('conversion-mode').value, distribution:byId('conversion-distribution').value,
      python_path:byId('conversion-python').value, input_size:Number(byId('conversion-size').value),
      calibration_data:'', default_calibration_dataset_id:byId('conversion-default-calibration').value, timeout_seconds:Number(byId('conversion-timeout').value), auto_convert:byId('conversion-auto').checked,
      remote_endpoint:byId('conversion-remote-endpoint').value.trim(), remote_token_env:byId('conversion-remote-token-env').value.trim(),
      remote_allow_insecure_http:byId('conversion-remote-http').checked, remote_poll_interval_seconds:Number(byId('conversion-remote-poll').value),
      remote_verifier_mode:byId('conversion-remote-verifier').value};
    try { await api('/api/conversion/config', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(config)}); message('配置已保存。新任务使用此配置，正在执行的任务保持原配置。'); }
    catch (error) { message(`保存失败：${error.message}`, true); }
  });
  byId('conversion-check').addEventListener('click', async () => {
    try { await api('/api/conversion/check', {method:'POST'}); await refresh(); message('环境检测已排队，结果显示在任务列表。'); }
    catch (error) { message(error.message, true); }
  });
  byId('conversion-refresh').addEventListener('click', refresh);
  byId('calibration-refresh').addEventListener('click', async () => { try { await readCalibrationDatasets(); message('校准集列表已刷新。', false, 'calibration'); } catch (error) { message(`校准集读取失败：${error.message}`, true, 'calibration'); } });
  byId('calibration-file').addEventListener('change', () => {
    const file = byId('calibration-file').files[0];
    byId('calibration-file-name').textContent = file ? file.name : '尚未选择文件';
    if (file && !byId('calibration-name').value.trim()) byId('calibration-name').value = file.name.replace(/\.zip$/i, '');
  });
  byId('calibration-upload-form').addEventListener('submit', event => {
    event.preventDefault(); if (state.demo || !connected || uploading) return;
    const file = byId('calibration-file').files[0]; if (!file) return;
    if (!file.name.toLowerCase().endsWith('.zip')) { message('请选择 ZIP 校准图片集', true, 'calibration'); return; }
    uploading = true; liveControls();
    const params = new URLSearchParams({filename:file.name, name:byId('calibration-name').value.trim(), version:byId('calibration-version').value.trim(), scenario:byId('calibration-scenario').value.trim()});
    const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/conversion/calibration-datasets?' + params); xhr.timeout = 310000;
    xhr.setRequestHeader('Content-Type', 'application/zip');
    xhr.upload.onprogress = event => { if (event.lengthComputable) byId('calibration-progress').value = Math.round(event.loaded / event.total * 100); };
    xhr.onload = async () => { if (xhr.status >= 200 && xhr.status < 300) { await readCalibrationDatasets(); message('校准集已保存，可在模型转换中选择。', false, 'calibration'); } else { let detail = xhr.responseText; try { detail = JSON.parse(detail).detail; } catch (_) {} message('校准集上传失败：' + detail, true, 'calibration'); } };
    xhr.onerror = () => message('校准集上传网络中断，请重试', true, 'calibration');
    xhr.onloadend = () => { uploading = false; liveControls(); };
    byId('calibration-progress').value = 0; xhr.send(file);
  });
  byId('calibration-list').addEventListener('click', async event => {
    const button = event.target.closest('[data-delete-calibration]'); if (!button || state.demo || !connected) return;
    if (!window.confirm('删除这个校准集版本？已被转换任务引用的版本不会被删除。')) return;
    button.disabled = true;
    try { await api(`/api/conversion/calibration-datasets/${encodeURIComponent(button.dataset.deleteCalibration)}`, {method:'DELETE'}); await readCalibrationDatasets(); message('校准集已删除。', false, 'calibration'); }
    catch (error) { message(`删除失败：${error.message}`, true, 'calibration'); button.disabled = false; }
  });
  byId('conversion-upload-form').addEventListener('submit', async event => {
    event.preventDefault(); if (state.demo || !connected || uploading) return;
    const file = byId('conversion-file').files[0]; if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pt')) { message('请选择 .pt 权重文件', true); return; }
    uploading = true; liveControls();
    const params = new URLSearchParams({filename:file.name, name:byId('conversion-name').value.trim(),
      version:byId('conversion-version').value.trim(), scenario:byId('conversion-scenario').value.trim(), purpose:byId('conversion-purpose').value});
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/conversion/uploads?' + params);
    xhr.timeout = 310000;
    Object.entries(headers()).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    const progress = byId('conversion-progress');
    progress.value = 0;
    byId('conversion-upload-percent').textContent = '0%';
    byId('conversion-upload-status').hidden = false;
    xhr.upload.onprogress = event => { if (event.lengthComputable) { const value = Math.round(event.loaded / event.total * 100); progress.value = value; byId('conversion-upload-percent').textContent = `${value}%`; } };
    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) { resetModelUploadState(); message('上传完成，正在排队验证 PT。验证通过后可在下方按流绑定。'); await refresh(); }
      else { let detail = xhr.responseText; try { detail = JSON.parse(detail).detail; } catch (_) {} message('上传失败：' + (typeof detail === 'string' ? detail : JSON.stringify(detail)), true); }
    };
    xhr.onerror = () => message('上传网络中断，请重试', true);
    xhr.ontimeout = () => message('上传超时，请重试', true);
    xhr.onloadend = () => { uploading = false; progress.value = 0; byId('conversion-upload-percent').textContent = '0%'; byId('conversion-upload-status').hidden = true; liveControls(); };
    xhr.send(file);
  });
  byId('conversion-jobs').addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || state.demo || !connected) return;
    button.disabled = true;
    try {
      if (button.dataset.retry) await api(`/api/conversion/jobs/${button.dataset.retry}/retry`, {method:'POST'});
      if (button.dataset.convert) {
        const calibrationId = byId('conversion-calibration-select').value;
        if (!calibrationId) throw new Error('请选择本次转换使用的校准集');
        await api(`/api/conversion/uploads/${button.dataset.convert}/mobile?calibrationDatasetId=${encodeURIComponent(calibrationId)}`, {method:'POST'});
      }
      if (button.dataset.log) {
        const text = await api(`/api/conversion/jobs/${button.dataset.log}/log`);
        const dialog = document.createElement('dialog'); dialog.className = 'conversion-log-dialog conversion-panel';
        dialog.innerHTML = '<div class="conversion-heading"><h3>执行日志</h3><button class="ghost-btn">关闭</button></div><pre></pre>';
        dialog.querySelector('pre').textContent = text; dialog.querySelector('button').onclick = () => dialog.close();
        dialog.addEventListener('close', () => dialog.remove()); document.body.append(dialog); dialog.showModal();
      }
      await refresh(); await refreshLiveModels();
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });

  // Model assets always come from the registry, even while other admin views remain in Demo mode.
  const originalRender = renderModels, originalBindings = renderStreamBindings;
  modelRows = () => state.models;
  renderModels = () => {
    originalRender();
    if (state.demo) return;
    host.querySelectorAll('[data-model-activate]').forEach(button => {
      const model = state.models.find(row => row.modelId === button.dataset.modelActivate);
      const server = ['pt','onnx'].includes(model?.format) && model.exists && model.hashValid && !model.placeholder;
      button.classList.remove('hidden');
      button.textContent = model.placeholder ? '占位模型不可使用' : server ? '设为新流默认' : '移动端产物'; button.disabled = !server;
      const badge = button.closest('.model-card')?.querySelector('.pill');
      if (badge && model.placeholder) badge.textContent = '开发占位';
      button.onclick = async event => {
        event.stopPropagation();
        try { await api(`/api/models/${encodeURIComponent(model.modelId)}/activate`, {method:'POST'}); await refreshLiveModels(); message('已设置新流默认模型，已有视频流的绑定保持不变。'); }
        catch (error) { message(error.message, true); }
      };
    });
  };
  renderStreamBindings = () => {
    originalBindings(); if (state.demo) return;
    host.querySelectorAll('[data-bind-stream] option[value]').forEach(option => {
      if (!option.value) return;
      const model = state.models.find(row => row.modelId === option.value);
      if (!model || model.placeholder || !['pt','onnx'].includes(model.format) || !model.exists || !model.hashValid) option.remove();
    });
  };
  refreshLiveModels = async () => {
    try { state.models = (await api('/api/models')).models || []; txt('model-catalog-state', state.models.length ? `Live API · ${state.models.length} 个真实模型` : 'Live API · 目录为空'); renderModels(); renderStreamBindings(); }
    catch (error) { state.models = []; renderModels(); txt('model-catalog-state', `目录不可用 · ${error.message}`); }
  };
  const originalBind = bindStreamModel;
  bindStreamModel = async (streamId, modelId) => {
    if (state.demo) return originalBind(streamId, modelId);
    try {
      const data = await api(`/api/streams/${encodeURIComponent(streamId)}/model`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_id:modelId})});
      const stream = state.streams.find(row => row.stream_id === streamId); if (stream) stream.model = data.model;
      renderStreamBindings(); message('该视频流已绑定所选模型。');
    } catch (error) { renderStreamBindings(); message(`绑定失败：${error.message}`, true); }
  };
  const oldRegister = byId('register-model-form').onsubmit;
  byId('register-model-form').onsubmit = async event => {
    if (state.demo) return oldRegister(event);
    event.preventDefault(); if (event.submitter?.value === 'cancel') return;
    try { await api('/api/models/register', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manifest_path:byId('manifest-path').value})}); byId('register-model-dialog').close(); await refreshLiveModels(); message('Manifest 已通过校验并登记。'); }
    catch (error) { message(`登记失败：${error.message}`, true); }
  };
  setInterval(() => { liveControls(); if (!document.hidden && host.classList.contains('active-view')) refresh(); }, 4000);
  liveControls();
  renderModeFields();
  byId('refresh-models-btn')?.addEventListener('click', () => refreshLiveModels());
  // The login gate dispatches this event after the account session is ready.
  window.addEventListener('aiyolo-authenticated', connect, {once:true});
})();
