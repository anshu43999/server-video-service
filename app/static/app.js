// Live registration endpoint retained for the next API-backed model registry pass: /api/models/register
const nativeFetch = window.fetch.bind(window);
const adminAuth = { user: null, ready: false };
window.aiyoloAuth = adminAuth;
window.fetch = async (input, init = {}) => {
  const headers = new Headers(init.headers || {});
  const url = typeof input === 'string' ? input : input.url;
  const response = await nativeFetch(input, {...init, headers});
  if (response.status === 401 && !String(url).includes('/api/auth/')) {
    lockAdminConsole('登录已过期，请重新登录。');
  }
  return response;
};
function authElement(id){return document.getElementById(id);}
function setAuthStatus(message, error=false){const box=authElement('auth-status');if(box){box.textContent=message||'';box.className=`auth-status ${error?'error':''}`.trim();}}
function lockAdminConsole(message=''){adminAuth.ready=false;adminAuth.user=null;delete window.ADMIN_TOKEN;window.__aiyoloAdminStarted=false;disconnectAuthenticatedRealtime();document.body.classList.add('auth-locked');setAuthStatus(message);}
function unlockAdminConsole(user){adminAuth.ready=true;adminAuth.user=user;delete window.ADMIN_TOKEN;window.OPERATOR_ID=user?.username||'admin';document.body.classList.remove('auth-locked');const avatar=authElement('admin-user-button');if(avatar){avatar.textContent=(user?.username||'管').slice(0,1).toUpperCase();avatar.title=`${user?.username||'管理员'} · 点击退出`;}window.dispatchEvent(new CustomEvent('aiyolo-authenticated',{detail:user}));}
function configureAuthForm(setupRequired){const form=authElement('auth-form');if(!form)return;form.dataset.setup=setupRequired?'true':'false';authElement('auth-title').textContent=setupRequired?'初始化管理员账号':'登录管理后台';authElement('auth-help').textContent=setupRequired?'这是首次使用，请创建第一个管理员账号。创建后即可登录管理后台。':'请输入管理员账号和密码。';authElement('auth-submit').textContent=setupRequired?'创建并登录':'登录';authElement('auth-password').autocomplete=setupRequired?'new-password':'current-password';}
async function requestAuth(path, payload){const response=await nativeFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const body=await response.json().catch(()=>({}));if(!response.ok){const detail=body.detail?.message||body.detail||`HTTP ${response.status}`;throw new Error(typeof detail==='string'?detail:JSON.stringify(detail));}return body;}
async function initialiseAdminAuth(){
  const form=authElement('auth-form');
  form?.addEventListener('submit',async event=>{
    event.preventDefault();
    const username=authElement('auth-username').value.trim(),password=authElement('auth-password').value;
    const submit=authElement('auth-submit');submit.disabled=true;setAuthStatus('正在验证…');
    try{const endpoint=form.dataset.setup==='true'?'/api/auth/setup':'/api/auth/login';const body=await requestAuth(endpoint,{username,password});configureAuthForm(false);unlockAdminConsole(body.user);authElement('auth-password').value='';setAuthStatus('');startAuthenticatedAdmin();}
    catch(error){setAuthStatus(error.message||'登录失败，请重试。',true);}
    finally{submit.disabled=false;}
  });
  authElement('admin-user-button')?.addEventListener('click',async()=>{if(!adminAuth.ready)return;await nativeFetch('/api/auth/logout',{method:'POST'}).catch(()=>{});configureAuthForm(false);lockAdminConsole('已退出登录。');});
  try{
    const response=await nativeFetch('/api/auth/status');const status=await response.json();
    if(status.setupRequired){configureAuthForm(true);}
    else if(status.authenticated){unlockAdminConsole(status.user);startAuthenticatedAdmin();}
    else{configureAuthForm(false);lockAdminConsole();setAuthStatus('请输入管理员账号和密码。');}
  }catch(error){lockAdminConsole('无法连接服务端，请先启动后端服务。');}
}
function startAuthenticatedAdmin(){if(!adminAuth.ready||window.__aiyoloAdminStarted)return;window.__aiyoloAdminStarted=true;state.demo=false;txt('service-state','Live API 已连接');renderOverview();renderStreams();renderStreamBindings();renderAlerts();renderRules();renderModels();renderHealth();renderInspector();renderDashboard();refreshLiveAlerts();refreshLiveStreams();refreshDashboardStats();connectAlertPush();}
document.addEventListener('DOMContentLoaded',initialiseAdminAuth,{once:true});
const MOCK = {
  streams: [['gate-east','入口东侧 · IPC-04',18420,true,.35,20,'人员 / 安全帽'],['tower-crane','塔吊作业面 · IPC-07',12980,true,.25,15,'吊钩 / 人员'],['material-yard','材料堆场 · IPC-02',9610,true,.30,20,'钢筋 / 板材'],['mobile-uplink','移动端推帧 · Android',0,false,.25,10,'远程输入']],
  rules: [['安全帽佩戴','PRESENCE','helmet','入口东侧 / 全画面','运行中','24 次','green'],['吊装禁区入侵','IN_REGION','person','塔吊作业面 / ROI-01','运行中','3 次','amber'],['材料堆放面积','AREA_RATIO','board · wood','材料堆场 / ROI-02','已暂停','—','muted']],

  pushTargets: [['项目群机器人','Webhook','https://hooks.example.com/site-alerts','启用',true],['值班短信网关','HTTP JSON','https://notify.example.com/v1/site-alerts','启用',true],['安全主管邮箱','Email','ops@example.com','停用',false]]
};
const STREAM_PREVIEW_IMAGES=['/admin/evidence/evidence_helmet_violation.png','/admin/evidence/evidence_restricted_zone.png','/admin/evidence/evidence_material_overflow.png','/admin/evidence/evidence_walkway_obstruction.png'];
// One source drives all ranges so usage, distributions and rates remain internally consistent.
const state = { liveRules:null, liveAlerts:[], alertsStatus:'loading', alertsError:null, streamsStatus:'loading', streams: MOCK.streams.map(s => ({stream_id:s[0],source:s[1],frames_received:s[2],yolo_enabled:s[3],confidence:s[4],max_fps:s[5],tag:s[6],state:s[2]?'在线':'等待推帧',publish_state:s[2]?'connected':'idle',model:{modelId:'',name:'未绑定模型',scenario:'',purpose:''}})), models:[], selected:null, playback:null, detections:null, detectionSocket:null, demo:false, alertFilter:'all', selectedAlert:null, dashboardRange:'today', dashboardStats:null, dashboardStatsError:null, modelScenario:'', modelSearch:'', modelPane:'catalog', parameterModel:null, parameterPlatform:'android', parameterProfile:null, demoParameterProfiles:{} };
const $ = id => document.getElementById(id);
setTimeout(()=>{if($('push-table'))renderPushTargets();},0);
const esc = v => String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const txt = (id,v) => $(id) && ($(id).textContent = v);
// M11-T08: management-page alert events use a channel separate from detection
// metadata.  Demo mode remains deterministic; Live mode reconnects quietly.
let alertPushSocket = null;
let alertPushReconnectTimer = null;
function disconnectAuthenticatedRealtime(){
  if(alertPushReconnectTimer){clearTimeout(alertPushReconnectTimer);alertPushReconnectTimer=null;}
  if(alertPushSocket){const socket=alertPushSocket;alertPushSocket=null;socket.onclose=null;socket.close();}
  if(typeof state!=='undefined'&&state.detectionSocket){const socket=state.detectionSocket;state.detectionSocket=null;socket.onclose=null;socket.close();}
}
function connectAlertPush(){
  if(!adminAuth.ready || state.demo || !window.WebSocket || alertPushSocket) return;
  if(alertPushReconnectTimer){clearTimeout(alertPushReconnectTimer);alertPushReconnectTimer=null;}
  const scheme=location.protocol==='https:'?'wss':'ws';
  const socket=new WebSocket(`${scheme}://${location.host}/api/alerts/ws`);
  alertPushSocket=socket;
  alertPushSocket.onmessage=e=>{try{const message=JSON.parse(e.data);if(message.type==='alert'){const box=$('push-operation');if(box){box.classList.remove('hidden');box.innerHTML='<b>实时告警</b><span>收到新的告警事件 · '+esc(message.event?.eventId||'未命名')+'</span>';}refreshLiveAlerts();refreshDashboardStats();}}catch(_){}};
  alertPushSocket.onclose=()=>{if(alertPushSocket===socket)alertPushSocket=null;if(adminAuth.ready&&!state.demo)alertPushReconnectTimer=setTimeout(()=>{alertPushReconnectTimer=null;connectAlertPush();},2000);};
}
document.addEventListener('click',e=>{if(e.target.closest('#mode-toggle'))setTimeout(connectAlertPush,0);});
// Dialog cancel controls must bypass form submit handlers that implement save actions.
document.addEventListener('click',e=>{const close=e.target.closest('.close-btn');if(close){e.preventDefault();e.stopImmediatePropagation();close.closest('dialog')?.close();}},true);
document.addEventListener('submit',e=>{if(e.submitter?.value==='cancel'){e.preventDefault();e.stopImmediatePropagation();e.target.closest('dialog')?.close();}},true);
function bindParameterTermHelp(help,owner){
  if(help.dataset.bound==='true')return;
  help.dataset.bound='true';
  help.addEventListener('mouseenter',()=>showTermHelp(help));
  help.addEventListener('focus',()=>showTermHelp(help));
  owner.addEventListener('mouseleave',()=>{if(!help.dataset.pinned&&document.activeElement!==help)closeTermHelp();});
  help.addEventListener('blur',()=>{if(!help.dataset.pinned)closeTermHelp();});
}
function groupAlertRuleHeaderTerms(){
  const header=document.querySelector('.parameter-rule-head');
  if(!header||header.querySelector('.parameter-rule-head-cell'))return;
  const terms=[...header.children];
  if(terms.length!==9)return;
  const makeCell=(items,separator=false)=>{
    const cell=document.createElement('span');cell.className='parameter-rule-head-cell';
    items.forEach((item,index)=>{if(separator&&index){const slash=document.createElement('span');slash.className='parameter-rule-head-separator';slash.setAttribute('aria-hidden','true');slash.textContent='/';cell.append(slash);}cell.append(item);});
    return cell;
  };
  header.replaceChildren(makeCell(terms.slice(0,2),true),makeCell(terms.slice(2,4),true),...terms.slice(4).map(term=>makeCell([term])));
}
function installParameterTermHelp(){
  const defaults={confidence:{min:'0.01',max:'0.99',step:'0.01',value:'0.35'},iou:{min:'0.10',max:'0.90',step:'0.01',value:'0.45'},maxDetections:{min:'1',max:'300',step:'1',value:'100'}};
  Object.entries(defaults).forEach(([key,meta])=>{const input=$({confidence:'parameter-confidence',iou:'parameter-iou',maxDetections:'parameter-max-detections'}[key]);if(!input)return;Object.entries({min:meta.min,max:meta.max,step:meta.step}).forEach(([name,value])=>input.setAttribute(name,value));input.dataset.default=meta.value;input.title=`范围 ${meta.min}-${meta.max} · 默认 ${meta.value} · 步进 ${meta.step}`;const field=input.closest('.field');if(field&&!field.querySelector('.parameter-range-note')){const note=document.createElement('small');note.className='parameter-range-note';note.textContent=`取值范围 ${meta.min}-${meta.max}，默认值 ${meta.value}，步进 ${meta.step}`;field.append(note);}});
  [
    ['parameter-confidence','识别置信度','保留检测结果的最低模型评分。例如 0.35 表示过滤低于 0.35 的结果，不代表实际正确率为 35%。取值范围 0.01-0.99，默认值 0.35，步进 0.01。调高通常减少误报，也可能增加漏检。'],
    ['parameter-iou','IoU 去重阈值','IoU 是两个检测框交集面积与并集面积的比值，用于去除重复框。取值范围 0.10-0.90，默认值 0.45，步进 0.01。超过阈值的候选框可能被抑制；调低去重更严格，也可能误删靠得很近的目标。'],
    ['parameter-max-detections','单帧最大结果数','每一帧图像经过筛选和去重后，最多保留的检测结果数量。取值范围 1-300，默认值 100，步进 1。例如 100 表示最多保留 100 个框；设置过小可能漏掉拥挤场景中的目标。']
  ].forEach(([inputId,term,explanation])=>{
    const label=$(inputId)?.closest('.field')?.querySelector(':scope > span');if(!label||label.querySelector('.term-help'))return;
    const field=label.parentElement;
    const container=document.createElement('div');container.className=field.className;
    field.replaceWith(container);container.append(...field.childNodes);
    label.classList.add('parameter-field-label');label.textContent='';
    const caption=document.createElement('label');caption.htmlFor=inputId;caption.textContent=term;
    const help=document.createElement('button');help.type='button';help.className='term-help';help.setAttribute('aria-label',`${term}说明`);help.setAttribute('aria-expanded','false');help.textContent='i';
    const tip=document.createElement('span');tip.className='term-tooltip';tip.id=inputId+'-help';tip.setAttribute('role','tooltip');tip.hidden=true;tip.textContent=explanation;
    help.setAttribute('aria-describedby',tip.id);help.setAttribute('aria-controls',tip.id);label.append(caption,help,tip);
    bindParameterTermHelp(help,label);
  });
  groupAlertRuleHeaderTerms();
  const headerExplanations={
    'parameter-header-enabled-help':'是否启用该类别对应的告警规则；关闭后仍可识别，但不按该类别生成告警。默认由类别模板决定：head 默认启用，其他类别默认关闭。',
    'parameter-header-category-help':'模型输出的原始类别标签，例如 head、helmet、person。该字段不是数值参数，没有最小值、最大值或默认数值。',
    'parameter-header-display-name-help':'后台和告警页面中展示给用户的业务名称。文本长度为 1-80 个字符。',
    'parameter-header-event-code-help':'系统内部稳定使用的机器可读事件标识，例如 PPE_NO_HELMET。必须以大写字母开头，长度为 2-64 个字符。',
    'parameter-header-confidence-help':'触发该类别告警所需的最低模型评分。取值范围 0.01-0.99，默认值 0.55，步进 0.01，且不能低于检测置信度。',
    'parameter-header-consecutive-help':'目标连续满足条件的帧数，达到后才触发告警，可减少单帧误报。取值范围 1-120，默认值 4，步进 1。',
    'parameter-header-dwell-help':'目标持续满足条件的最短时间，单位为毫秒。取值范围 0-600000，默认值 800，步进 100。',
    'parameter-header-cooldown-help':'一次告警触发后，抑制同类重复告警的时间，单位为毫秒。取值范围 0-86400000，默认值 60000，步进 1000。',
    'parameter-header-severity-help':'告警严重程度，例如一般、重要、严重，用于后续处置优先级。可选值为一般、重要、严重，默认值为重要。'
  };
  Object.entries(headerExplanations).forEach(([id,explanation])=>{const tip=$(id);if(tip)tip.textContent=explanation;});
  document.querySelectorAll('.parameter-rule-head .term-help').forEach(help=>bindParameterTermHelp(help,help.parentElement));
}
installParameterTermHelp();
function closeTermHelp(except=null){document.querySelectorAll('.term-help.is-open').forEach(help=>{if(help!==except){help.classList.remove('is-open');help.setAttribute('aria-expanded','false');delete help.dataset.pinned;$(help.getAttribute('aria-controls')).hidden=true;}});}
function showTermHelp(help){closeTermHelp(help);help.classList.add('is-open');help.setAttribute('aria-expanded','true');$(help.getAttribute('aria-controls')).hidden=false;}
document.addEventListener('click',event=>{const help=event.target.closest('.term-help');if(!help){if(!event.target.closest('.term-tooltip'))closeTermHelp();return;}event.preventDefault();if(help.dataset.pinned){closeTermHelp();}else{showTermHelp(help);help.dataset.pinned='true';}});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.querySelector('.term-help.is-open')){event.preventDefault();event.stopPropagation();closeTermHelp();}},true);
$('model-parameter-dialog').addEventListener('close',()=>closeTermHelp());
function showView(v){if(v!=='dashboard'&&document.body.classList.contains('dashboard-focus-mode'))setDashboardFocusMode(false);document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active-view',x.id===`view-${v}`));document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.view===v));txt('view-title',{overview:'现场运行总览',dashboard:'数据看板',streams:'视频流管理',alerts:'告警中心',push:'报警推送',rules:'规则配置',models:'模型资产',diagnostics:'系统诊断',verification:'智能复核'}[v]);if(v==='dashboard')refreshDashboardStats(state.dashboardRange);if(v==='push')renderPushTargets();if(v==='rules'&&!state.demo)refreshLiveRules();if(v==='models'){renderModels();renderStreamBindings();if(typeof refreshLiveModels==='function')refreshLiveModels();}document.querySelector('.main-content')?.scrollTo({top:0,behavior:'smooth'});}
function setDashboardFocusMode(enabled){document.body.classList.toggle('dashboard-focus-mode',enabled);const button=$('dashboard-fullscreen-btn');if(button){button.title=enabled?'退出大屏模式':'进入大屏模式';button.innerHTML=enabled?'⤢ <span>退出大屏</span>':'⛶ <span>大屏模式</span>';}if(!enabled&&document.fullscreenElement&&document.exitFullscreen)document.exitFullscreen().catch(()=>{});}
function toggleDashboardFullscreen(){const enabled=document.body.classList.contains('dashboard-focus-mode');if(enabled){setDashboardFocusMode(false);return;}showView('dashboard');setDashboardFocusMode(true);if(document.documentElement.requestFullscreen)document.documentElement.requestFullscreen().catch(()=>{});}
// Live dashboard renderer. Historical values come from the persisted stats API;
// process telemetry and stream state are refreshed independently.
function renderDashboard(range='today'){
  state.dashboardRange=range;
  const data=state.dashboardStats;
  const summary=data?.summary||{};
  txt('dash-events',data?Number(summary.totalEvents||0).toLocaleString('zh-CN'):'--');
  txt('dash-alerts',data?Number(summary.severeAlerts||0).toLocaleString('zh-CN'):'--');
  txt('dash-resolution',data?`${Number(summary.resolutionRate||0).toFixed(1)}%`:'--');
  txt('dash-response',data&&summary.averageResponseMinutes!==null&&summary.averageResponseMinutes!==undefined?`${Number(summary.averageResponseMinutes).toFixed(1)} min`:'--');
  txt('dash-events-note',data?`${Number(summary.handledEvents||0).toLocaleString('zh-CN')} 条已处置`:'等待真实数据');
  txt('dash-alerts-note',data?`${Number(summary.severeAlerts||0).toLocaleString('zh-CN')} 条严重级别`:'等待真实数据');
  txt('dash-resolution-note',data?`${Number(summary.handledEvents||0).toLocaleString('zh-CN')} / ${Number(summary.totalEvents||0).toLocaleString('zh-CN')} 已处置`:'等待真实数据');
  txt('dash-response-note',data&&summary.averageResponseMinutes!==null&&summary.averageResponseMinutes!==undefined?'基于已记录处置时间':'暂无已处置样本');
  txt('dash-chart-note',data?({today:'今日 · 每 2 小时','7d':'近 7 天 · 每日','30d':'近 30 天 · 每 5 天'}[range]||range):'等待真实数据');
  txt('dash-updated',data?`数据更新 ${new Date(data.generatedAt).toLocaleTimeString('zh-CN',{hour12:false})}`:(state.dashboardStatsError?`统计不可用 · ${state.dashboardStatsError}`:'正在读取真实数据'));
  const trend=data?.trend||[];const maxTrend=Math.max(1,...trend.map(item=>Number(item.count||0)));
  $('dash-bars').innerHTML=trend.length?trend.map(item=>{const count=Number(item.count||0);const severe=Number(item.severe||0);const height=Math.max(count?8:3,Math.round(count/maxTrend*112));return `<i class="${severe?'alert-bar':''}" style="height:${height}px" title="${esc(item.label)} · ${count} 个事件 · ${severe} 个严重"></i>`;}).join(''):'<span class="dashboard-empty-chart">暂无告警事件</span>';
  $('dash-x-axis').innerHTML=trend.map(item=>`<span>${esc(item.label)}</span>`).join('');
  const categories=data?.categories||[];const maxCategory=Math.max(1,...categories.map(item=>Number(item.count||0)));
  $('dash-categories').innerHTML=categories.length?categories.map((item,index)=>`<div class="category-row"><span class="category-rank">${index+1}</span><b>${esc(item.label)}</b><i><em style="width:${(Number(item.count||0)/maxCategory*100).toFixed(1)}%"></em></i><strong>${Number(item.percent||0).toFixed(1)}%</strong></div>`).join(''):'<div class="dashboard-empty-state">当前时间范围暂无告警类别数据</div>';
  const nowLabel=new Date().toLocaleTimeString('zh-CN',{hour12:false});
  $('dashboard-stream-wall').innerHTML=state.streams.slice(0,4).map(s=>{const live=Boolean(s.frames_received);const image=live?`<img src="/api/streams/${encodeURIComponent(s.stream_id)}/mjpeg" alt="${esc(s.stream_id)}实时视频流" onerror="this.parentElement.classList.add('missing');this.remove()">`:'';return `<article class="dashboard-stream-card"><div class="dashboard-stream-media ${live?'':'missing'}">${image}<span class="stream-live-badge ${live?'':'waiting'}"><i></i>${live?'LIVE':'WAITING'}</span><span class="dashboard-stream-time">${nowLabel}</span></div><div class="dashboard-stream-meta"><div><b>${esc(s.stream_id)}</b><small>${esc(s.source||'服务端流')}</small></div><span class="dashboard-stream-state ${live?'online':'idle'}">${live?'在线':'等待推帧'}</span></div><div class="dashboard-stream-foot"><span>${Number(s.output_fps||s.max_fps||0).toFixed(1)} FPS</span><span>${esc(s.tag||'未绑定模型')}</span><span>${s.yolo_enabled?'YOLO ON':'RAW'}</span></div></article>`;}).join('')||'<div class="dashboard-empty-state">当前没有视频流会话</div>';
  const actualAlerts=state.liveAlerts||[];const alertClass=value=>{const normalized=String(value||'').toUpperCase();return normalized==='CRITICAL'||normalized==='严重'?'critical':normalized==='MAJOR'||normalized==='重要'?'important':'normal';};const alertTime=event=>{const value=event.confirmedAtUs||event.startedAtUs;return value?new Date(Number(value)/1000).toLocaleTimeString('zh-CN',{hour12:false}):'时间未知';};
  $('dash-alert-feed').innerHTML=actualAlerts.slice(0,4).map(event=>`<div class="dashboard-alert-item"><i class="severity-dot ${alertClass(event.notifySeverity||event.severity)}"></i><div><b>${esc(event.displayName||event.label||event.ruleId||event.eventId)}</b><small>${esc(event.sourceId||'未知来源')} · ${alertTime(event)}</small></div><em>${esc((event.disposition||{}).status||'OPEN')}</em></div>`).join('')||'<div class="dashboard-empty-state">当前没有告警事件</div>';
  const streamSummary=data?.streams||{total:0,online:0,waiting:0,errors:0};const streamTotal=Number(streamSummary.total||0);const onlinePercent=streamTotal?Math.round(Number(streamSummary.online||0)/streamTotal*100):0;
  txt('dashboard-stream-count',`${streamTotal} 路会话`);txt('dashboard-stream-count-side',`${streamTotal} 路会话`);txt('dashboard-online-percent',`${onlinePercent}%`);txt('dashboard-online-count',String(streamSummary.online||0));txt('dashboard-waiting-count',String(streamSummary.waiting||0));txt('dashboard-error-count',String(streamSummary.errors||0));
  const healthRing=document.querySelector('.stream-health-ring');if(healthRing)healthRing.style.background=`conic-gradient(#5e9a70 0 ${onlinePercent}%,#e7eee9 ${onlinePercent}% 100%)`;
  $('dash-health-detail').innerHTML=state.streams.slice(0,4).map(s=>`<div class="dashboard-health-row"><span><i class="health-dot ${s.last_error||s.alert_error?'error':s.frames_received?'online':'waiting'}"></i>${esc(s.stream_id)}</span><b>${s.last_error||s.alert_error?'异常':s.frames_received?`${s.output_fps||s.max_fps||0} FPS`:'等待'}</b></div>`).join('')||'<div class="dashboard-empty-state">当前没有视频流会话</div>';
  const system=data?.system||{};const gpu=Array.isArray(system.gpu)&&system.gpu.length?Number(system.gpu[0].utilization_percent):null;const resources=[['CPU',system.cpu_percent,'%', '#5e9a70'],['进程内存',system.memory_percent,'%', '#6ca784'],['GPU / NPU',gpu,'%', '#7b9dc5'],['磁盘',system.disk_percent,'%', '#d09a53']];
  $('dash-server-status').innerHTML=resources.map(item=>{const numeric=item[1]==null||item[1]===''?null:Number(item[1]);const value=Number.isFinite(numeric)?numeric:null;const display=value===null?'不可用':`${value.toFixed(1)}${item[2]}`;const width=value===null?0:Math.max(0,Math.min(100,value));return `<div class="server-status-row"><div class="server-status-label"><span>${item[0]}</span><b>${display}</b></div><i class="server-status-track"><em style="width:${width}%;background:${item[3]}"></em></i><small>${value===null?'未提供':value>=85?'高负载':'正常'}</small></div>`;}).join('');
  const resolutionBars=[['严重','CRITICAL'],['重要','MAJOR'],['一般','MINOR']];const severity=data?.severity||{};const severityCounts=severity.total||{};const severityHandled=severity.handled||{};
  const totalEvents=Number(summary.totalEvents||0),handledEvents=Number(summary.handledEvents||0);txt('dashboard-workflow-rate',`${Number(summary.resolutionRate||0).toFixed(1)}%`);txt('dashboard-workflow-note',`${handledEvents.toLocaleString('zh-CN')} / ${totalEvents.toLocaleString('zh-CN')} 已处置`);
  const resolutionNode=document.querySelectorAll('.resolution-bars > div');resolutionNode.forEach((node,index)=>{const key=resolutionBars[index]?.[1];const total=severityCounts[key]||0;const percent=total?Math.round(severityHandled[key]/total*100):0;node.querySelector('b').style.width=`${percent}%`;node.querySelector('em').textContent=`${percent}%`;});
  const verification=data?.verification||{used:0,limit:0,conclusions:{},failures:{}};txt('verification-range-note',({today:'今日','7d':'近 7 天','30d':'近 30 天'}[range]||range));txt('verification-used',Number(verification.used||0).toLocaleString('zh-CN'));txt('verification-limit-display',Number(verification.limit||0).toLocaleString('zh-CN'));txt('verification-before-rate','暂无');txt('verification-after-rate','暂无');txt('verification-rate-improvement','当前未记录可比较的复核前后基线');const usageBar=$('verification-usage-bar');if(usageBar)usageBar.style.width=verification.limit?`${Math.min(100,Number(verification.used||0)/Number(verification.limit)*100).toFixed(1)}%`:'0%';
  const conclusionLabels={confirmed:'复核确认',false_positive:'疑似误报',uncertain:'无法判定'};const failureLabels={DISABLED:'未启用',NOT_AUTHORIZED:'未授权图像',MISSING_IMAGE:'缺少证据图片',QUOTA_EXHAUSTED:'额度不足',NOT_CONFIGURED:'供应商未配置',PROVIDER_UNAVAILABLE:'供应商不可用'};const renderBreakdown=(target,values,labels)=>{const node=$(target);if(!node)return;const entries=Object.entries(values||{});const total=entries.reduce((sum,item)=>sum+Number(item[1]||0),0);node.innerHTML=entries.length?entries.map(([key,value])=>`<span><i>${esc(labels[key]||key)}</i><b>${Number(value||0)}</b><em><u style="width:${total?(Number(value||0)/total*100).toFixed(1):0}%"></u></em></span>`).join(''):'<small class="dashboard-empty-state">暂无记录</small>';};renderBreakdown('verification-conclusions',verification.conclusions,conclusionLabels);renderBreakdown('verification-failures',verification.failures,failureLabels);
  document.querySelectorAll('.range-btn').forEach(b=>b.classList.toggle('active',b.dataset.range===range));
}
function renderOverview(){const data=state.dashboardStats,summary=data?.summary||{};txt('overview-live-summary',`服务器当前有 ${state.streams.length} 路视频会话，真实告警和运行数据会在这里汇聚。`);txt('metric-streams',String(state.streams.length).padStart(2,'0'));txt('metric-alerts',data?String(Number(summary.totalEvents||0)).padStart(2,'0'):'--');txt('metric-events',data?Number(summary.totalEvents||0).toLocaleString('zh-CN'):'--');txt('metric-model',state.streams.some(s=>s.yolo_enabled)?'运行中':'未启用');txt('metric-alerts-note',data?`${Number(summary.severeAlerts||0)} 条严重级别`:'正在读取真实数据');txt('metric-events-note',data?'PostgreSQL 已持久化告警':'正在读取真实数据');const trend=data?.trend||[];const max=Math.max(1,...trend.map(item=>Number(item.count||0)));$('activity-bars').innerHTML=trend.length?trend.map(item=>`<i style="height:${Math.max(item.count?8:2,Number(item.count||0)/max*76)}px" title="${esc(item.label)} · ${Number(item.count||0)} 个事件"></i>`).join(''):'<span class="dashboard-empty-chart">暂无告警事件</span>';const rows=state.liveAlerts||[];$('overview-alerts').innerHTML=rows.slice(0,4).map(event=>{const severity=String(event.notifySeverity||event.severity||'MINOR').toUpperCase();const tone=severity==='CRITICAL'?'critical':severity==='MAJOR'?'important':'normal';const image=(event.evidence||{}).snapshotUri||'';const timeValue=event.confirmedAtUs||event.startedAtUs;const timeLabel=timeValue?new Date(Number(timeValue)/1000).toLocaleTimeString('zh-CN',{hour12:false}):'时间未知';return `<button class="compact-alert" data-goto="alerts"><span class="compact-thumb"><img src="${esc(image)}" alt="${esc(event.displayName||event.label||event.ruleId||event.eventId)}证据" onerror="this.parentElement.classList.add('missing');this.remove()"></span><span class="severity-dot ${tone}"></span><span><b>${esc(event.displayName||event.label||event.ruleId||event.eventId)}</b><small>${esc(event.sourceId||'未知来源')} · ${timeLabel}</small></span><em>${esc((event.disposition||{}).status||'OPEN')}</em></button>`;}).join('')||'<div class="dashboard-empty-state">当前没有告警事件</div>';document.querySelectorAll('[data-goto]').forEach(x=>x.onclick=()=>showView(x.dataset.goto));}
function renderStreams(){txt('nav-stream-count',!state.demo&&state.streamsStatus==='ready'?String(state.streams.length).padStart(2,'0'):'--');txt('stream-count-label',String(state.streams.length).padStart(2,'0'));$('stream-list').innerHTML=state.streams.map(s=>{const running=state.demo||s.runtime_available!==false,configLabel=s.enabled===false?'配置已停用':running?'运行中':s.runtime_state==='error'?'恢复异常':'等待恢复';return `<button class="stream-item ${s.stream_id===state.selected?'selected':''}" data-id="${esc(s.stream_id)}"><div class="stream-top"><span><i class="status-dot ${running&&(s.frames_received||s.publish_state==='connected')?'':'off'}"></i><b>${esc(s.display_name||s.stream_id)}</b></span><span class="pill ${s.yolo_enabled?'on':'muted'}">${s.yolo_enabled?'YOLO ON':'RAW'}</span></div><div class="stream-sub"><span>${esc(s.source||'服务端流')}</span><span>${Number(s.frames_received||0).toLocaleString()} frames</span></div><div class="stream-tag">${esc(configLabel)} · ${esc(s.stream_id)}</div></button>`;}).join('');document.querySelectorAll('.stream-item').forEach(x=>x.onclick=()=>{state.selected=x.dataset.id;renderStreams();renderInspector();const selected=state.streams.find(s=>s.stream_id===state.selected);if(selected&&!state.demo)loadLiveStream(selected);});}
function updateStreamPreview(image,fallback,stream){const previewKey=`${state.demo?'demo':'live'}:${stream.stream_id}`;if(!state.demo&&stream.runtime_available===false){image.removeAttribute('src');delete image.dataset.previewKey;image.classList.add('hidden');if(fallback){fallback.textContent=stream.enabled===false?'视频流配置已停用':'视频流正在等待恢复';fallback.classList.remove('hidden');}return;}image.classList.remove('hidden');image.alt=`${stream.stream_id}视频流现场画面`;image.onerror=()=>{image.classList.add('hidden');delete image.dataset.previewKey;fallback?.classList.remove('hidden');};if(fallback)fallback.classList.add('hidden');if(image.dataset.previewKey===previewKey)return;image.dataset.previewKey=previewKey;image.src=state.demo?STREAM_PREVIEW_IMAGES[state.streams.indexOf(stream)%STREAM_PREVIEW_IMAGES.length]:`/api/streams/${encodeURIComponent(stream.stream_id)}/mjpeg?connection=${Date.now()}`;}
function renderInspector(){const s=state.streams.find(x=>x.stream_id===state.selected);$('inspector-empty').classList.toggle('hidden',!!s);$('inspector-content').classList.toggle('hidden',!s);if(!s){txt('inspector-title','选择一个流');txt('inspector-pill','未选择');const image=$('preview-image');if(image){image.removeAttribute('src');delete image.dataset.previewKey;}return;}txt('inspector-title',s.display_name||s.stream_id);txt('inspector-pill',(s.runtime_state||s.publish_state||s.state||'idle').toUpperCase());$('inspector-pill').className=`pill ${s.runtime_available!==false&&(s.publish_state==='connected'||s.frames_received)?'on':'muted'}`;const previewBox=document.querySelector('.fake-preview');let previewImage=$('preview-image');let previewFallback=$('preview-image-fallback');if(previewBox&&!previewImage){previewBox.insertAdjacentHTML('afterbegin','<img id="preview-image" class="stream-preview-image" alt="视频流现场画面"><span id="preview-image-fallback" class="preview-image-fallback hidden">现场画面暂不可用</span>');previewImage=$('preview-image');previewFallback=$('preview-image-fallback');}if(previewImage)updateStreamPreview(previewImage,previewFallback,s);$('stream-enabled-toggle').checked=s.enabled!==false;$('yolo-toggle').checked=!!s.yolo_enabled;$('confidence').value=s.confidence??.25;txt('confidence-value',Number(s.confidence??.25).toFixed(2));$('max-fps').value=s.max_fps??20;txt('fps-value',s.max_fps??20);txt('preview-label',s.frames_received?(s.yolo_enabled?'YOLO OVERLAY · LIVE':'RAW STREAM · LIVE'):(s.enabled===false?'STREAM DISABLED':'WAITING FOR FRAMES'));txt('preview-fps',`${s.max_fps??20} FPS CAP`);const p=state.playback||{};const entry=(name)=>p[name]||{};const whep=entry('whep'),hls=entry('llhls'),rtsp=entry('rtsp');txt('whep-state',whep.available?'可用':'等待连接');txt('hls-state',hls.available?'可回退':'未就绪');txt('rtsp-state','诊断通道');[['whep-url',whep.url],['hls-url',hls.url],['rtsp-url',rtsp.url]].forEach(([id,url])=>{const a=$(id);if(a){a.href=url||'#';a.textContent=url||'地址不可用';a.classList.toggle('disabled',!url);}});const detections=state.detections?.detections||[];$('stream-detections').innerHTML=detections.length?detections.map(d=>`<div class="detection-row"><b>${esc(d.label||d.class_name||'object')}</b><span>${Number(d.confidence||0).toFixed(2)} · ${esc(JSON.stringify(d.bbox||d.box||''))}</span><em>WebSocket</em></div>`).join(''):(s.frames_received&&s.yolo_enabled&&!state.demo?'<div class="detection-empty">等待检测元数据…</div>':'<div class="detection-empty">当前没有结构化检测结果</div>');}
async function loadLiveStream(stream){if(state.detectionSocket){state.detectionSocket.close();state.detectionSocket=null;}state.playback=null;state.detections=null;if(stream.runtime_available===false){renderInspector();return;}try{const response=await fetch(`/api/streams/${encodeURIComponent(stream.stream_id)}/playback`);if(response.ok)state.playback=await response.json();}catch(e){state.playback={};}renderInspector();if(stream.yolo_enabled){const wsUrl=`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/streams/${encodeURIComponent(stream.stream_id)}/detections`;try{const socket=new WebSocket(wsUrl);state.detectionSocket=socket;socket.onmessage=e=>{try{state.detections=JSON.parse(e.data);renderInspector();}catch(_){}};socket.onclose=()=>{if(state.detectionSocket===socket)state.detectionSocket=null;};}catch(_){}}}
async function refreshLiveStreams(){state.streamsStatus='loading';renderStreams();try{const response=await fetch('/api/streams');if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();state.streams=data.map(s=>({...s,source:s.source_url||s.source||s.publish_url||'服务端流',frames_received:s.frames_received||0,tag:s.model?.model_id||s.model_id||'服务端'}));state.streamsStatus='ready';if(!state.streams.some(s=>s.stream_id===state.selected))state.selected=state.streams[0]?.stream_id||null;renderOverview();renderStreams();renderStreamBindings();renderInspector();const selected=state.streams.find(s=>s.stream_id===state.selected);if(selected)await loadLiveStream(selected);txt('service-state','Live API 已连接');}catch(e){state.streamsStatus='error';renderStreams();txt('service-state',`Live API 不可用 · ${e.message}`);}}
async function refreshDashboardStats(range=state.dashboardRange){state.dashboardRange=range;try{const headers=window.ADMIN_TOKEN?{'X-Admin-Token':window.ADMIN_TOKEN}:{};const [statsResponse,healthResponse]=await Promise.all([fetch(`/api/dashboard/stats?range=${encodeURIComponent(range)}`,{headers}),fetch('/healthz')]);if(!statsResponse.ok)throw new Error(`HTTP ${statsResponse.status}`);state.dashboardStats=await statsResponse.json();state.health=await healthResponse.json().catch(()=>null);state.dashboardStatsError=null;renderDashboard(range);renderOverview();renderHealth();}catch(error){state.dashboardStats=null;state.dashboardStatsError=error.message;renderDashboard(range);renderOverview();renderHealth();}}
function alertSeverity(event){
  const value=String(event.notifySeverity||event.severity||'MINOR').trim().toUpperCase();
  if(['CRITICAL','严重','重大'].includes(value))return {key:'critical',label:'严重'};
  if(['MAJOR','IMPORTANT','重要'].includes(value))return {key:'important',label:'重要'};
  return {key:'normal',label:'一般'};
}
function alertTitle(event){return event.displayName||event.label||event.ruleId||event.eventId||'未命名告警';}
function alertSubject(event){const first=Array.isArray(event.detectionResults)?event.detectionResults[0]:null;return event.subjectKey||first?.label||first?.className||'未记录主体';}
function alertTime(event){const value=event.confirmedAtUs||event.startedAtUs;if(!value)return '时间未知';const date=new Date(Number(value)/1000);return Number.isNaN(date.getTime())?'时间未知':date.toLocaleString('zh-CN',{hour12:false});}
function alertDisposition(event){
  const value=String((event.disposition||{}).status||'OPEN').toUpperCase();
  const labels={OPEN:'待确认',ACKNOWLEDGED:'已确认',FALSE_POSITIVE:'误报',CLOSED:'已关闭'};
  return {value,label:labels[value]||value,tone:value==='OPEN'?'pending':'done'};
}
function alertVerificationLabel(verification){
  if(!verification||verification.status==='UNREVIEWED')return '未复核';
  if(verification.status==='PENDING')return '复核中';
  if(verification.status==='FAILED')return '失败';
  const labels={confirmed:'确认',false_positive:'疑似误报',uncertain:'无法判定'};
  return labels[String(verification.verdict||'').toLowerCase()]||'已复核';
}
function renderAlerts(){
  const all=Array.isArray(state.liveAlerts)?state.liveAlerts:[];
  const counts={all:all.length,critical:0,important:0,normal:0};
  all.forEach(event=>{counts[alertSeverity(event).key]+=1;});
  txt('nav-alert-count',state.alertsStatus==='ready'?String(counts.all).padStart(2,'0'):'--');
  Object.entries(counts).forEach(([key,value])=>txt(`alert-count-${key}`,String(value).padStart(2,'0')));
  const table=$('alert-table');
  if(state.alertsStatus==='loading'){
    table.innerHTML='<div class="alert-center-state"><b>正在读取真实告警</b><span>正在连接 PostgreSQL 事件存储…</span></div>';
    return;
  }
  if(state.alertsStatus==='error'){
    table.innerHTML=`<div class="alert-center-state error"><b>告警数据不可用</b><span>请检查服务连接或访问权限。${state.alertsError?` ${esc(state.alertsError)}`:''}</span><button type="button" class="ghost-btn" id="retry-alerts-btn">重新加载</button></div>`;
    $('retry-alerts-btn').onclick=refreshLiveAlerts;
    return;
  }
  const list=state.alertFilter==='all'?all:all.filter(event=>alertSeverity(event).key===state.alertFilter);
  if(!list.length){
    const labels={all:'当前没有告警事件',critical:'当前没有严重告警',important:'当前没有重要告警',normal:'当前没有一般告警'};
    table.innerHTML=`<div class="alert-center-state"><b>${labels[state.alertFilter]||labels.all}</b><span>此处只展示服务端已持久化的真实告警。</span></div>`;
    return;
  }
  table.innerHTML=list.map(event=>{
    const severity=alertSeverity(event),disposition=alertDisposition(event),image=(event.evidence||{}).snapshotUri||'';
    return `<button type="button" class="alert-row" data-event-id="${esc(event.eventId)}"><span class="alert-thumb"><img src="${esc(image)}" alt="${esc(alertTitle(event))}证据" onerror="this.parentElement.classList.add('missing');this.remove()"></span><span class="alert-title"><i class="severity-dot ${severity.key}"></i><b>${esc(alertTitle(event))}</b><small>${severity.label}</small></span><span><b>${esc(event.sourceId||'未知来源')}</b><small>${esc(alertSubject(event))}</small></span><span class="mono">${esc(alertTime(event))}</span><span class="state-chip ${disposition.tone}">${esc(disposition.label)}</span><span class="alert-action"><span class="verification-chip">复核：${esc(alertVerificationLabel(event.verification))}</span><span class="row-arrow" aria-hidden="true">→</span></span></button>`;
  }).join('');
  document.querySelectorAll('.alert-row').forEach(row=>row.onclick=()=>openAlert(row.dataset.eventId));
}
function renderAlertVerification(event,verification=event?.verification){
  const box=$('alert-verification'),button=$('request-verification-btn');
  const status=String(verification?.status||'UNREVIEWED').toUpperCase();
  const title=alertVerificationLabel(verification);
  const reason=verification?.reason||'尚未执行多模态复核';
  const detail=[verification?.modelId&&`模型 ${verification.modelId}`,verification?.promptVersion&&`提示词 ${verification.promptVersion}`,Number.isFinite(Number(verification?.latencyMs))&&Number(verification.latencyMs)>0&&`${verification.latencyMs} ms`].filter(Boolean).join(' · ');
  box.innerHTML=`<b>智能复核：${esc(title)}</b><p>${esc(reason)}</p>${detail?`<small>${esc(detail)}</small>`:''}<em>复核结论只做标注，不会删除原始告警。</em>`;
  button.disabled=status!=='UNREVIEWED';
  button.textContent=status==='UNREVIEWED'?'发起 AI 复核':status==='PENDING'?'复核中':status==='FAILED'?'复核失败':'已复核';
  button.onclick=async()=>{
    button.disabled=true;button.textContent='复核请求中…';alertActionMessage('正在提交复核请求…');
    try{const result=await requestLiveVerification(event.eventId);event.verification=result;renderAlertVerification(event,result);renderAlerts();alertActionMessage('复核请求已记录。','success');}
    catch(error){button.disabled=false;button.textContent='发起 AI 复核';alertActionMessage(`复核请求失败：${error.message}`,'error');}
  };
}
function alertActionMessage(message,tone=''){
  const box=$('alert-action-status');if(!box)return;box.className=`operation-banner ${tone}`.trim();box.textContent=message;
}
function openAlert(eventId){
  const event=state.liveAlerts.find(item=>item.eventId===eventId);if(!event)return;
  state.selectedAlert=event.eventId;txt('alert-detail-title',alertTitle(event));
  const evidence=$('alert-evidence-image'),fallback=$('alert-evidence-fallback'),image=(event.evidence||{}).snapshotUri||'';
  evidence.onerror=()=>{evidence.classList.add('hidden');fallback.classList.remove('hidden');};
  if(image){evidence.classList.remove('hidden');fallback.classList.add('hidden');evidence.alt=`${alertTitle(event)}事件证据`;evidence.src=image;}else{evidence.removeAttribute('src');evidence.classList.add('hidden');fallback.classList.remove('hidden');}
  const severity=alertSeverity(event),disposition=alertDisposition(event);
  $('alert-detail-meta').innerHTML=`<div><b>级别</b><span>${severity.label}</span></div><div><b>状态</b><span>${esc(disposition.label)}</span></div><div><b>来源</b><span>${esc(event.sourceId||'未知来源')}</span></div><div><b>主体</b><span>${esc(alertSubject(event))}</span></div><div><b>发生时间</b><span>${esc(alertTime(event))}</span></div><div><b>事件 ID</b><span>${esc(event.eventId)}</span></div><div><b>规则</b><span>${esc(event.ruleId||'未记录')}</span></div><div><b>模型</b><span>${esc((event.model||{}).modelId||'未记录')}</span></div>`;
  $('alert-action-status').className='operation-banner hidden';
  const confirm=$('confirm-alert-btn'),markFalse=$('mark-false-btn');confirm.disabled=disposition.value==='ACKNOWLEDGED';confirm.textContent=confirm.disabled?'已确认':'确认告警';markFalse.disabled=disposition.value==='FALSE_POSITIVE';markFalse.textContent=markFalse.disabled?'已标记误报':'标记误报';
  renderAlertVerification(event);$('alert-detail-dialog').showModal();loadAlertVerification(event);
}
function renderRules(){const rows=state.liveRules||null;if(rows){$('rule-grid').innerHTML=rows.map((r,i)=>{const rejected=r.rejection||r.bindingRejection;const status=rejected?'能力不满足':(r.enabled===false?'已暂停':'运行中');return `<article class="rule-card"><div class="rule-card-top"><span class="rule-icon ${rejected?'amber':'green'}">⌘</span><span class="pill ${rejected?'muted':status==='运行中'?'on':'muted'}">${status}</span></div><h3>${esc(r.name||r.ruleId)}</h3><p><b>${esc(r.operator)}</b> · ${esc((r.targetLabels||[]).join('、')||'未指定标签')}</p><small>所需能力：${esc((r.requires||[]).join('、')||'无')}${rejected?` · 拒绝：${esc(rejected.message||rejected.code)}`:''}</small><div class="rule-foot"><span>版本 v${r.ruleVersion||1}</span><button class="icon-btn" data-rule-index="${i}">⋯</button></div></article>`}).join('');$('rule-capability-summary').classList.toggle('hidden',!rows.some(r=>r.rejection));$('rule-capability-summary').innerHTML=rows.filter(r=>r.rejection).map(r=>`<b>${esc(r.name||r.ruleId)}</b><span>绑定拒绝：${esc(r.rejection.message||r.rejection.code)}${r.rejection.missing?` · 缺少 ${esc(r.rejection.missing.join('、'))}`:''}</span>`).join('');}else{$('rule-grid').innerHTML=MOCK.rules.map((r,i)=>`<article class="rule-card"><div class="rule-card-top"><span class="rule-icon ${r[6]}">⌘</span><span class="pill ${r[4]==='运行中'?'on':'muted'}">${r[4]}</span></div><h3>${r[0]}</h3><p><b>${r[1]}</b> · ${r[2]}</p><small>${r[3]}</small><div class="rule-foot"><span>近 24 小时命中 <b>${r[5]}</b></span><button class="icon-btn" data-rule-index="${i}">⋯</button></div></article>`).join('');}document.querySelectorAll('[data-rule-index]').forEach(x=>x.onclick=()=>{const r=state.liveRules?state.liveRules[Number(x.dataset.ruleIndex)]:MOCK.rules[Number(x.dataset.ruleIndex)];$('rule-name').value=r.name||r[0];$('rule-operator').value=r.operator||r[1];$('rule-roi').value=r.roiId||r[3]||'';$('rule-dialog').showModal();});}
async function refreshLiveRules(){try{const response=await fetch('/api/rules');if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();state.liveRules=data.rules||[];const audit=await fetch('/api/rules/audit');if(audit.ok){const rows=(await audit.json()).audit||[];$('rule-audit-list').innerHTML=rows.slice(-12).reverse().map(a=>`<div class="compact-alert"><span><b>${esc(a.action)}</b> · ${esc(a.ruleId)}</span><em>v${a.ruleVersion}</em></div>`).join('');}renderRules();}catch(e){state.liveRules=null;}}
function modelRows(){return state.models;}
function modelBytes(value){if(!Number.isFinite(Number(value)))return '大小未知';const bytes=Number(value);if(bytes>=1048576)return `${(bytes/1048576).toFixed(1)} MB`;if(bytes>=1024)return `${Math.round(bytes/1024)} KB`;return `${bytes} B`;}
function modelReadiness(model){
  if(model.placeholder)return {label:'开发占位',tone:'warn',detail:'仅用于接口联调'};
  if(model.serverReady&&model.androidReady)return {label:'双端就绪',tone:'ready',detail:'服务端 + Android'};
  if(model.serverReady)return {label:'服务端就绪',tone:'ready',detail:'可绑定服务端视频流'};
  if(model.androidReady||model.androidConverted)return {label:'移动端产物',tone:'mobile',detail:model.androidReady?'已通过移动端校验':'已生成，待校验'};
  if(model.exists&&model.hashValid)return {label:'文件已登记',tone:'muted',detail:'等待运行时验证'};
  return {label:'需要处理',tone:'error',detail:'文件或哈希未通过'};
}
function updateModelSummary(){
  const rows=modelRows();
  const ready=rows.filter(model=>model.serverReady||(['pt','onnx'].includes(model.format)&&model.exists&&model.hashValid&&!model.placeholder)).length;
  const mobile=rows.filter(model=>model.androidReady).length;
  const active=rows.filter(model=>model.active).length;
  txt('model-total',String(rows.length).padStart(2,'0'));txt('model-server-ready',String(ready).padStart(2,'0'));txt('model-android-ready',String(mobile).padStart(2,'0'));txt('model-active-count',String(active).padStart(2,'0'));
  txt('model-sync-summary',rows.length?`已同步 ${rows.length} 个真实模型`:'真实目录为空');
}
function renderModels(){
  const query=state.modelSearch.trim().toLowerCase();
  const rows=modelRows().filter(model=>{const matchesScenario=!state.modelScenario||model.scenario===state.modelScenario;const haystack=[model.name,model.modelId,model.scenario,model.purpose].filter(Boolean).join(' ').toLowerCase();return matchesScenario&&(!query||haystack.includes(query));});
  const scenarios=[...new Set(modelRows().map(m=>m.scenario).filter(Boolean))];
  const select=$('model-scenario-filter');
  if(select){const current=state.modelScenario;select.innerHTML='<option value="">全部场景</option>'+scenarios.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');select.value=current;}
  updateModelSummary();
  if(!$('model-list'))return;
  $('model-list').innerHTML=rows.length?rows.map(model=>{
    const readiness=modelReadiness(model);const formats=[...new Set((model.artifacts||[]).map(artifact=>artifact.format).filter(Boolean))];const labelCount=Array.isArray(model.labels)?model.labels.length:0;
    const active=model.active&&!model.placeholder;const canActivate=['pt','onnx'].includes(model.format)&&model.exists&&model.hashValid&&!model.placeholder;
    return `<article class="model-card ${active?'active-model':''}" data-model-open="${esc(model.modelId)}"><div class="model-card-accent ${readiness.tone}"></div><div class="model-main"><div class="model-top"><div><h3>${esc(model.name||model.modelId)}</h3><p class="model-id">${esc(model.modelId)}</p></div><span class="model-readiness ${readiness.tone}"><i></i>${readiness.label}</span></div><div class="model-facts"><span>${esc(model.scenario||'未分类')}</span><span>${esc(model.version||'未标版本')}</span><span>${formats.length?formats.map(format=>esc(format.toUpperCase())).join(' / '):'格式未知'}</span><span>${labelCount?`${labelCount} 个类别`:'类别未知'}</span></div></div><div class="model-card-actions"><button class="text-btn model-action model-detail-action" data-model-detail="${esc(model.modelId)}" type="button">详情</button><button class="ghost-btn model-action" data-model-parameters="${esc(model.modelId)}" type="button" ${model.placeholder?'disabled title="占位模型没有可调整参数"':''}>参数</button><button class="ghost-btn model-action hidden" data-model-activate="${esc(model.modelId)}" type="button" ${canActivate?'':'disabled'}>${model.placeholder?'占位模型不可使用':canActivate?'设为默认':'移动端产物'}</button><button class="danger-btn model-action" data-model-uninstall="${esc(model.modelId)}" type="button" ${active?'disabled title="当前生效模型不能卸载"':''}>卸载</button></div></article>`;
  }).join(''):`<div class="model-empty-state"><span>⌕</span><b>${query||state.modelScenario?'没有找到匹配模型':'暂无模型资产'}</b><small>${query||state.modelScenario?'调整搜索词或场景筛选后重试':'上传 PT 或登记 Manifest 后，真实模型会显示在这里。'}</small></div>`;
  document.querySelectorAll('[data-model-detail]').forEach(button=>button.onclick=event=>{event.stopPropagation();openModelDetails(button.dataset.modelDetail);});
  document.querySelectorAll('[data-model-parameters]').forEach(button=>button.onclick=event=>{event.stopPropagation();openModelParameters(button.dataset.modelParameters);});
  document.querySelectorAll('[data-model-uninstall]').forEach(button=>button.onclick=event=>{event.stopPropagation();requestModelUninstall(button.dataset.modelUninstall);});
  document.querySelectorAll('[data-model-open]').forEach(card=>card.addEventListener('click',event=>{if(event.target.closest('button,select,a'))return;openModelDetails(card.dataset.modelOpen);}));
}
  function showModelPane(pane){
    state.modelPane=['catalog','calibration','upload'].includes(pane)?pane:'catalog';
  document.querySelectorAll('.model-tab').forEach(button=>{
    const on=button.dataset.modelTab===state.modelPane;
    button.classList.toggle('is-active',on);
    button.setAttribute('aria-selected',on?'true':'false');
  });
  document.querySelectorAll('[data-model-pane]').forEach(panel=>{
    const on=panel.dataset.modelPane===state.modelPane;
    panel.classList.toggle('is-active',on);
    panel.hidden=!on;
  });
}
function openModelDetails(modelId){
  const model=modelRows().find(item=>item.modelId===modelId);if(!model)return;
  const readiness=modelReadiness(model);const artifacts=Array.isArray(model.artifacts)?model.artifacts:[];const labels=Array.isArray(model.labels)?model.labels:[];
  txt('model-detail-title',model.name||model.modelId);txt('model-detail-identity',`${model.modelId} · ${model.version||'未标版本'}`);$('model-detail-status').innerHTML=`<span class="model-readiness ${readiness.tone}"><i></i>${readiness.label}</span><span>${esc(readiness.detail)}</span>`;
  $('model-detail-meta').innerHTML=[['场景',model.scenario||'未分类'],['用途',model.purpose||'未指定'],['运行时',model.runtime||'未声明'],['输入尺寸',model.inputSize?`${model.inputSize} × ${model.inputSize}`:'未声明'],['签名状态',model.signatureStatus||'未签名'],['许可证',model.license?.status||'未提供']].map(([name,value])=>`<div><span>${name}</span><b>${esc(value)}</b></div>`).join('');
  $('model-detail-artifacts').innerHTML=artifacts.length?artifacts.map(artifact=>`<div class="model-artifact-row"><div><b>${esc(artifact.artifactId||artifact.format||'模型产物')}</b><small>${esc((artifact.platform||'未指定平台').toUpperCase())} · ${artifact.sizeBytes?modelBytes(artifact.sizeBytes):'大小未知'}</small></div><span class="artifact-state ${artifact.exists&&artifact.hashValid?'valid':'invalid'}">${artifact.exists&&artifact.hashValid?'校验通过':'待校验'}</span>${artifact.url?`<a class="icon-btn" href="${esc(artifact.url)}" target="_blank" rel="noopener" title="下载产物">↓</a>`:''}</div>`).join(''):'<div class="model-detail-empty">暂无已登记产物</div>';
  txt('model-detail-label-count',`${labels.length} 个类别`);$('model-detail-labels').innerHTML=labels.length?labels.map(label=>`<span>${esc(label)}</span>`).join(''):'<span class="model-detail-empty">暂无类别信息</span>';
  txt('model-detail-note',model.sha256||model.hash?`完整 SHA-256：${model.sha256||model.hash}`:'服务端尚未返回完整性摘要。');
  const uninstall=$('model-detail-uninstall');uninstall.dataset.modelUninstall=model.modelId;uninstall.disabled=Boolean(model.active);uninstall.title=model.active?'当前生效模型不能卸载':'';
  $('model-detail-dialog').showModal();
}
function requestModelUninstall(modelId){
  const model=modelRows().find(item=>item.modelId===modelId);if(!model||model.active)return;
  state.pendingModelUninstall=modelId;
  txt('model-uninstall-name',model.name||model.modelId);txt('model-uninstall-identity',`${model.modelId} · ${model.version||'未标版本'}`);
  const status=$('model-uninstall-status');status.textContent='';status.className='operation-banner hidden';
  $('model-uninstall-confirm').disabled=false;$('model-uninstall-dialog').showModal();
}
async function confirmModelUninstall(){
  const modelId=state.pendingModelUninstall;if(!modelId)return;
  const button=$('model-uninstall-confirm'),status=$('model-uninstall-status');button.disabled=true;status.className='operation-banner';status.textContent='正在卸载模型并清理产物…';
  try{
    const response=await fetch(`/api/models/${encodeURIComponent(modelId)}`,{method:'DELETE',headers:modelParameterHeaders()});
    const body=await response.json().catch(()=>({}));
    if(!response.ok){const detail=body.detail||body;const message=typeof detail==='string'?detail:(detail.message||`HTTP ${response.status}`);const bound=Array.isArray(detail.streamIds)&&detail.streamIds.length?` · 正在使用：${detail.streamIds.join('、')}`:'';throw new Error(message+bound);}
    $('model-uninstall-dialog').close();$('model-detail-dialog').close();state.pendingModelUninstall=null;await refreshLiveModels();
    const operation=$('model-operation'),deleted=Array.isArray(body.deletedFiles)?body.deletedFiles.length:Number(body.deletedFiles)||0,cleanup=(body.cleanupFailures||[]).length;operation.className=`operation-banner${cleanup?' conversion-error':''}`;operation.textContent=cleanup?`模型已从目录卸载，但有 ${cleanup} 个文件清理失败`:`模型已卸载 · 清理 ${deleted} 个文件`;
  }catch(error){status.className='operation-banner conversion-error';status.textContent=`卸载失败 · ${error.message}`;}finally{button.disabled=false;}
}
function setupModelUninstallActions(){
  const actions=$('model-detail-dialog')?.querySelector('.dialog-actions');if(actions&&!$('model-detail-uninstall')){const button=document.createElement('button');button.id='model-detail-uninstall';button.className='danger-btn';button.type='button';button.textContent='卸载模型';button.onclick=()=>requestModelUninstall(button.dataset.modelUninstall);actions.prepend(button);}
  $('model-uninstall-confirm').onclick=confirmModelUninstall;
}
setupModelUninstallActions();
function renderStreamBindings(){const list=$('stream-binding-list');if(!list)return;if(state.demo){list.innerHTML='<div class="binding-empty">连接管理服务后读取真实视频流绑定</div>';return;}list.innerHTML=state.streams.length?state.streams.map(s=>{const model=s.model||{};const id=model.modelId||model.catalog_model_id||'未绑定';const options=modelRows().filter(m=>m.format!=='LiteRT'&&m.runtime!=='mobile-tflite');const configLabel=s.enabled===false?'配置停用':'配置启用',runtimeLabel=s.runtime_available===false?(s.runtime_state==='error'?'恢复异常':'未运行'):'运行中';return `<div class="stream-binding-row"><div><b>${esc(s.display_name||s.stream_id)}</b><small>${esc(s.source||'服务端流')}</small><span class="stream-binding-state">${esc(configLabel)} · ${esc(runtimeLabel)} · ${esc(s.stream_id)}</span><span>${esc(model.name||id)} · ${esc(model.scenario||'未分类')} · ${esc(model.purpose||'未指定用途')}</span></div><select data-bind-stream="${esc(s.stream_id)}"><option value="">切换模型…</option>${options.map(m=>`<option value="${esc(m.modelId)}" ${m.modelId===id?'selected':''}>${esc(m.name||m.modelId)}</option>`).join('')}</select></div>`;}).join(''):'<div class="binding-empty">暂无持久视频流配置</div>';document.querySelectorAll('[data-bind-stream]').forEach(x=>x.onchange=()=>bindStreamModel(x.dataset.bindStream,x.value));}
async function bindStreamModel(streamId,modelId){if(!modelId)return;const stream=state.streams.find(s=>s.stream_id===streamId);const selected=modelRows().find(m=>m.modelId===modelId);if(state.demo){if(stream){stream.model={modelId,name:selected?.name||modelId,scenario:selected?.scenario||'未分类',purpose:selected?.purpose||'未指定用途'};stream.tag=stream.model.scenario;renderStreamBindings();renderStreams();}return;}try{const response=await fetch(`/api/streams/${encodeURIComponent(streamId)}/model`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_id:modelId})});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();if(stream)stream.model=data.model;renderStreamBindings();renderStreams();txt('model-catalog-state','已同步取流侧');}catch(e){txt('model-catalog-state',`切换失败 · ${e.message}`);renderStreamBindings();}}
async function refreshLiveModels(){try{const response=await fetch('/api/models');if(!response.ok)throw new Error(`HTTP ${response.status}`);state.models=(await response.json()).models||[];txt('model-catalog-state','Live API');renderModels();renderStreamBindings();}catch(e){txt('model-catalog-state',`目录不可用 · ${e.message}`);}}
$('model-search-input')?.addEventListener('input',event=>{state.modelSearch=event.target.value;renderModels();});
$('model-scenario-filter')?.addEventListener('change',event=>{state.modelScenario=event.target.value;renderModels();});
document.querySelectorAll('[data-model-tab]').forEach(button=>button.addEventListener('click',()=>showModelPane(button.dataset.modelTab)));

function modelParameterHeaders(json=false){const headers={};if(json)headers['Content-Type']='application/json';if(window.ADMIN_TOKEN)headers['X-Admin-Token']=window.ADMIN_TOKEN;if(window.OPERATOR_ID)headers['X-Operator-Id']=window.OPERATOR_ID;return headers;}
const PARAMETER_META={
  detection:{confidence:{min:.01,max:.99,step:.01,default:.35},iou:{min:.10,max:.90,step:.01,default:.45},maxDetections:{min:1,max:300,step:1,default:100}},
  image:{confidence:{min:.01,max:.99,step:.01,default:.55},cooldown:{min:0,max:86400000,step:1000,default:60000}},
  camera:{confidence:{min:.01,max:.99,step:.01,default:.55},frames:{min:1,max:120,step:1,default:4},dwell:{min:0,max:600000,step:100,default:800},cooldown:{min:0,max:86400000,step:1000,default:60000}}
};
function parameterMetaText(meta){return `取值范围 ${meta.min}-${meta.max}，默认值 ${meta.default}，步进 ${meta.step}`;}
function normalizeParameterProfile(profile){
  const source=profile||{};const migrated=source.schemaVersion!==2||((source.alertRules||[]).some(rule=>rule&&!rule.image&&!rule.camera));
  const rules=(Array.isArray(source.alertRules)?source.alertRules:[]).map(rule=>{
    const image=rule.image||{minimumConfidence:rule.minimumConfidence??PARAMETER_META.image.confidence.default,cooldownMs:rule.cooldownMs??PARAMETER_META.image.cooldown.default};
    const camera=rule.camera||{minimumConfidence:rule.minimumConfidence??PARAMETER_META.camera.confidence.default,minimumConsecutiveFrames:rule.minimumConsecutiveFrames??PARAMETER_META.camera.frames.default,minimumDwellTimeMs:rule.minimumDwellTimeMs??PARAMETER_META.camera.dwell.default,cooldownMs:rule.cooldownMs??PARAMETER_META.camera.cooldown.default};
    return {...rule,image:{...image},camera:{...camera}};
  });
  return {...source,schemaVersion:2,alertRules:rules,_migratedFromV1:migrated};
}
function setModelParameterBusy(busy){$('model-parameter-save').disabled=busy;$('model-parameter-reset').disabled=busy;document.querySelectorAll('[data-parameter-platform]').forEach(button=>button.disabled=busy);}
function modelParameterMessage(message,type='') {const box=$('model-parameter-status');box.textContent=message;box.className=`parameter-status ${type}`.trim();}
function parameterHelp(term,explanation){const id=`parameter-${Math.random().toString(36).slice(2)}`;return `<span class="parameter-term"><span>${term}</span><button type="button" class="term-help" aria-label="${esc(term)}说明" aria-expanded="false" aria-describedby="${id}" aria-controls="${id}">i</button><span class="term-tooltip" id="${id}" role="tooltip" hidden>${esc(explanation)}</span></span>`;}
function parameterControl(field,term,value,meta,explanation,type='number'){
  const attrs=type==='number'?`type="number" min="${meta.min}" max="${meta.max}" step="${meta.step}" value="${esc(value)}"`:`type="text" value="${esc(value)}" maxlength="80"`;
  return `<label class="parameter-control"><span class="parameter-control-label">${parameterHelp(term,explanation)}</span><input data-parameter-field="${field}" ${attrs} aria-label="${esc(term)}"><small>${type==='number'?parameterMetaText(meta):'取值范围 1-80 个字符'}</small></label>`;
}
function renderModelParameterProfile(profile){
  profile=normalizeParameterProfile(profile);state.parameterProfile=profile;
  $('parameter-confidence').value=profile.detection.confidenceThreshold;
  $('parameter-iou').value=profile.detection.iouThreshold;
  $('parameter-max-detections').value=profile.detection.maxDetections;
  txt('model-parameter-revision',profile.revision?`修订 v${profile.revision} · ${profile.source==='default'?'默认':'已调整'}`:'默认参数');
  txt('model-parameter-label-count',`${profile.alertRules.length} 个类别`);
  const image=profile.alertRules.map((rule,index)=>`${parameterControl('image.minimumConfidence','图片告警置信度',rule.image.minimumConfidence,PARAMETER_META.image.confidence,'现场拍照只依据当前图片评分，不使用连续帧和停留时间。')}${parameterControl('image.cooldownMs','图片冷却时间 ms',rule.image.cooldownMs,PARAMETER_META.image.cooldown,'单张图片告警触发后，抑制同类重复告警的时间。')}`);
  const camera=profile.alertRules.map((rule,index)=>`${parameterControl('camera.minimumConfidence','视频告警置信度',rule.camera.minimumConfidence,PARAMETER_META.camera.confidence,'相机巡检每帧筛选该类别所需的最低模型评分。')}${parameterControl('camera.minimumConsecutiveFrames','连续帧',rule.camera.minimumConsecutiveFrames,PARAMETER_META.camera.frames,'目标连续满足条件的帧数，达到后才触发告警，可减少单帧误报。')}${parameterControl('camera.minimumDwellTimeMs','停留时间 ms',rule.camera.minimumDwellTimeMs,PARAMETER_META.camera.dwell,'目标持续满足条件的最短时间，单位为毫秒。')}${parameterControl('camera.cooldownMs','视频冷却时间 ms',rule.camera.cooldownMs,PARAMETER_META.camera.cooldown,'视频告警触发后，抑制同类重复告警的时间。')}`);
  const openAll=profile.alertRules.length<=6;
  const cards=profile.alertRules.map((rule,index)=>`<article class="parameter-category ${rule.enabled?'is-enabled':'is-muted'} ${openAll||index===0?'is-open':''}" data-parameter-rule="${index}" data-search="${esc((rule.displayName||'')+' '+(rule.rawLabel||'')+' '+(rule.eventCode||'')).toLowerCase()}"><header class="parameter-category-head"><label class="parameter-enabled"><input type="checkbox" data-parameter-field="enabled" ${rule.enabled?'checked':''}><span><b>${esc(rule.displayName||rule.rawLabel)}</b><small>${esc(rule.rawLabel)}</small></span></label><label class="parameter-control parameter-severity"><span class="parameter-control-label">${parameterHelp('告警级别','告警严重程度，用于后续处置优先级。')}</span><select data-parameter-field="severity"><option value="MINOR" ${rule.severity==='MINOR'?'selected':''}>一般</option><option value="MAJOR" ${rule.severity==='MAJOR'?'selected':''}>重要</option><option value="CRITICAL" ${rule.severity==='CRITICAL'?'selected':''}>严重</option></select></label><button type="button" class="parameter-category-toggle" aria-expanded="${openAll||index===0?'true':'false'}">${openAll||index===0?'收起':'展开'}</button></header><div class="parameter-category-body"><div class="parameter-identity">${parameterControl('displayName','业务名称',rule.displayName,{min:1,max:80,step:1,default:rule.displayName},'后台和告警页面展示的名称。','text')}${parameterControl('eventCode','事件编码',rule.eventCode,{min:2,max:64,step:1,default:rule.eventCode},'系统内部稳定使用的机器可读事件标识。','text')}</div><div class="parameter-entry-grid"><section class="parameter-entry" data-entry="image"><h5>拍照识别</h5><p>单张图片命中即可判定。</p><div class="parameter-entry-fields">${image[index]}</div></section><section class="parameter-entry" data-entry="camera"><h5>相机巡检</h5><p>连续帧、停留和冷却共同判定。</p><div class="parameter-entry-fields">${camera[index]}</div></section></div></div></article>`).join('');
  $('model-parameter-rules').innerHTML=`<div class="parameter-category-tools"><label class="parameter-category-filter"><span>筛选</span><input id="parameter-category-filter" type="search" placeholder="按名称、标签或事件编码筛选" autocomplete="off"></label><button type="button" class="text-btn" id="parameter-category-expand">${openAll?'全部收起':'全部展开'}</button></div><section class="parameter-scene-section" id="parameter-common-section"><div class="parameter-scene-heading"><div><p class="eyebrow">COMMON ALERT RULE</p><h4>类别通用参数</h4><small>启用、业务名称、事件编码和告警级别同时作用于两种识别入口。</small></div></div><div class="parameter-scene-list parameter-common-list">${cards}</div></section><section class="parameter-scene-section" id="parameter-image-section" hidden><div class="parameter-scene-heading"><div><p class="eyebrow">STILL IMAGE / PHOTO</p><h4>现场拍照 · 图片识别告警参数</h4><small>单张图片完成识别；此区域明确不配置连续帧和停留时间。</small></div></div></section><section class="parameter-scene-section" id="parameter-camera-section" hidden><div class="parameter-scene-heading"><div><p class="eyebrow">LIVE CAMERA / INSPECTION</p><h4>相机巡检告警参数</h4><small>视频帧按连续帧、停留时间和冷却时间共同判定。</small></div></div></section>`;
  document.querySelectorAll('#model-parameter-rules .term-help').forEach(help=>bindParameterTermHelp(help,help.parentElement));
  bindParameterCategoryUi();
  const audits=(profile.audit||[]).slice().reverse();
  $('model-parameter-audit').innerHTML=audits.length?audits.slice(0,5).map(item=>`<span class="parameter-audit-item">${item.action==='RESET'?'恢复默认':'保存'} v${item.revision} · ${esc(item.actor||'admin')} · ${esc(new Date(item.at).toLocaleString('zh-CN',{hour12:false}))}</span>`).join(''):'暂无修改记录';
  const migration=profile._migratedFromV1?'已按 v1 兼容规则映射到图片识别 / 相机巡检参数。 ':'';
  modelParameterMessage(migration+(profile.source==='default'?'当前使用模型初始参数，尚未做自定义调整。':`参数档案已读取 · ${profile.updatedBy||'admin'} · ${new Date(profile.updatedAt).toLocaleString('zh-CN',{hour12:false})}`));
}
function bindParameterCategoryUi(){
  const filter=$('parameter-category-filter');
  const applyFilter=()=>{const query=(filter?.value||'').trim().toLowerCase();document.querySelectorAll('#parameter-common-section [data-parameter-rule]').forEach(card=>{card.hidden=Boolean(query)&&!(card.dataset.search||'').includes(query);});};
  filter?.addEventListener('input',applyFilter);
  const setOpen=(card,open)=>{card.classList.toggle('is-open',open);const toggle=card.querySelector('.parameter-category-toggle');if(toggle){toggle.textContent=open?'收起':'展开';toggle.setAttribute('aria-expanded',open?'true':'false');}};
  document.querySelectorAll('.parameter-category-toggle').forEach(button=>button.addEventListener('click',()=>{const card=button.closest('[data-parameter-rule]');setOpen(card,!card.classList.contains('is-open'));}));
  document.querySelectorAll('#parameter-common-section [data-parameter-field="enabled"]').forEach(input=>input.addEventListener('change',()=>input.closest('[data-parameter-rule]')?.classList.toggle('is-muted',!input.checked)));
  $('parameter-category-expand')?.addEventListener('click',event=>{const cards=[...document.querySelectorAll('#parameter-common-section [data-parameter-rule]')];const open=cards.some(card=>!card.classList.contains('is-open'));cards.forEach(card=>setOpen(card,open));event.currentTarget.textContent=open?'全部收起':'全部展开';});
}
async function loadModelParameters(platform){
  state.parameterPlatform=platform;
  document.querySelectorAll('[data-parameter-platform]').forEach(button=>button.classList.toggle('active',button.dataset.parameterPlatform===platform));
  setModelParameterBusy(true);modelParameterMessage('正在读取参数档案…');
  try{
    let profile;
    const response=await fetch(`/api/models/${encodeURIComponent(state.parameterModel.modelId)}/parameters?platform=${platform}`,{headers:modelParameterHeaders()});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body?.detail?.message||`HTTP ${response.status}`);profile=body;
    renderModelParameterProfile(profile);
  }catch(error){modelParameterMessage(`读取失败 · ${error.message}`,'error');$('model-parameter-rules').innerHTML='';}
  finally{setModelParameterBusy(false);}
}
function openModelParameters(modelId){
  const model=modelRows().find(item=>item.modelId===modelId);if(!model)return;
  state.parameterModel=model;state.parameterPlatform='android';
  txt('model-parameter-title',model.name||model.modelId);txt('model-parameter-identity',`${model.modelId} · ${model.version||'未标版本'}`);
  $('model-parameter-dialog').showModal();loadModelParameters('android');
}
function collectModelParameterValues(){
  const detection={confidenceThreshold:Number($('parameter-confidence').value),iouThreshold:Number($('parameter-iou').value),maxDetections:Number($('parameter-max-detections').value)};
  const limits=[['识别置信度',detection.confidenceThreshold,.01,.99],['IoU 去重阈值',detection.iouThreshold,.10,.90],['单帧最大结果数',detection.maxDetections,1,300]];
  limits.forEach(([name,value,min,max])=>{if(!Number.isFinite(value)||value<min||value>max)throw new Error(`${name}必须在 ${min}-${max} 范围内`);});
  const number=(input,name,min,max,integer=false)=>{const value=Number(input?.value);if(!Number.isFinite(value)||value<min||value>max||(integer&&!Number.isInteger(value)))throw new Error(`${name}必须在 ${min}-${max} 范围内`);return value;};
  const commonRows=[...document.querySelectorAll('#parameter-common-section [data-parameter-rule]')];
  const alertRules=commonRows.map((row,index)=>{const value=name=>row.querySelector(`[data-parameter-field="${name}"]`);const displayName=value('displayName').value.trim();const eventCode=value('eventCode').value.trim().toUpperCase();if(!displayName||displayName.length>80)throw new Error('业务名称必须填写且不超过 80 个字符');if(!/^[A-Z][A-Z0-9_]{1,63}$/.test(eventCode))throw new Error('事件编码必须为 2-64 位大写字母、数字或下划线');const imageConfidence=number(value('image.minimumConfidence'),'图片告警置信度',.01,.99);const cameraConfidence=number(value('camera.minimumConfidence'),'视频告警置信度',.01,.99);const imageCooldown=number(value('image.cooldownMs'),'图片冷却时间',0,86400000,true);const frames=number(value('camera.minimumConsecutiveFrames'),'连续帧',1,120,true);const dwell=number(value('camera.minimumDwellTimeMs'),'停留时间',0,600000,true);const cameraCooldown=number(value('camera.cooldownMs'),'视频冷却时间',0,86400000,true);if(value('enabled').checked&&(imageConfidence<detection.confidenceThreshold||cameraConfidence<detection.confidenceThreshold))throw new Error('类别告警置信度不能低于识别置信度');const current=state.parameterProfile.alertRules[index];return {rawLabel:current.rawLabel,displayName,eventCode,operator:'PRESENCE',enabled:value('enabled').checked,severity:value('severity').value,image:{minimumConfidence:imageConfidence,cooldownMs:imageCooldown},camera:{minimumConfidence:cameraConfidence,minimumConsecutiveFrames:frames,minimumDwellTimeMs:dwell,cooldownMs:cameraCooldown}};});
  return {schemaVersion:2,expectedRevision:state.parameterProfile.revision,detection,alertRules};
}
async function saveModelParameters(){
  let values;
  try{values=collectModelParameterValues();}
  catch(error){modelParameterMessage(`参数校验失败 · ${error.message}`,'error');return;}
  setModelParameterBusy(true);modelParameterMessage('正在保存参数档案…');
  try{
    let profile;
    const response=await fetch(`/api/models/${encodeURIComponent(state.parameterModel.modelId)}/parameters?platform=${state.parameterPlatform}`,{method:'PUT',headers:modelParameterHeaders(true),body:JSON.stringify(values)});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body?.detail?.message||`HTTP ${response.status}`);profile=body;
    renderModelParameterProfile(profile);modelParameterMessage('保存成功，新的参数档案已持久化。','success');
  }catch(error){modelParameterMessage(`保存失败 · ${error.message}`,'error');}
  finally{setModelParameterBusy(false);}
}
async function resetModelParameters(){
  if(!window.confirm(`确定恢复 ${state.parameterPlatform==='android'?'Android':'服务端'} 的模型初始参数吗？`))return;
  setModelParameterBusy(true);modelParameterMessage('正在恢复初始参数…');
  try{
    let profile;
    const response=await fetch(`/api/models/${encodeURIComponent(state.parameterModel.modelId)}/parameters?platform=${state.parameterPlatform}`,{method:'DELETE',headers:modelParameterHeaders()});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body?.detail?.message||`HTTP ${response.status}`);profile=body;
    renderModelParameterProfile(profile);modelParameterMessage('已恢复模型初始参数并记录审计。','success');
  }catch(error){modelParameterMessage(`恢复失败 · ${error.message}`,'error');}
  finally{setModelParameterBusy(false);}
}
document.querySelectorAll('[data-parameter-platform]').forEach(button=>button.addEventListener('click',()=>loadModelParameters(button.dataset.parameterPlatform)));
$('model-parameter-form')?.addEventListener('submit',event=>{if(event.submitter?.id!=='model-parameter-save')return;event.preventDefault();saveModelParameters();});
$('model-parameter-reset')?.addEventListener('click',resetModelParameters);
function renderPushTargets(){$('push-table').innerHTML=MOCK.pushTargets.map((t,i)=>`<div class="push-row"><b>${esc(t[0])}</b><span class="push-type">${esc(t[1])}</span><code>${esc(t[2])}</code><span class="state-chip ${t[4]?'done':'muted'}">${t[3]}</span><span class="push-actions"><button class="text-btn" data-push-test="${i}">测试推送</button><button class="icon-btn" data-push-toggle="${i}">${t[4]?'停用':'启用'}</button></span></div>`).join('');document.querySelectorAll('[data-push-test]').forEach(x=>x.onclick=()=>simulatePush(Number(x.dataset.pushTest)));document.querySelectorAll('[data-push-toggle]').forEach(x=>x.onclick=()=>{const t=MOCK.pushTargets[Number(x.dataset.pushToggle)];t[4]=!t[4];t[3]=t[4]?'启用':'停用';renderPushTargets();});}
function simulatePush(index,eventTitle='测试告警'){const target=MOCK.pushTargets[index];const box=$('push-operation');box.classList.remove('hidden');box.innerHTML=`<b>${esc(target[0])}</b><span>正在发送告警摘要 · ${esc(eventTitle)}</span>`;setTimeout(()=>{box.innerHTML=`<b>${esc(target[0])}</b><span>模拟发送成功 · HTTP 200 · ${new Date().toLocaleTimeString('zh-CN',{hour12:false})}</span>`;},420);}
document.addEventListener('click',e=>{if(e.target.closest('#new-push-btn'))$('push-dialog').showModal();});document.addEventListener('submit',e=>{if(e.target.id==='push-form'){e.preventDefault();const name=$('push-name').value.trim(),type=$('push-type').value,url=$('push-url').value.trim();if(name&&url){MOCK.pushTargets.push([name,type,url,'启用',true]);$('push-dialog').close();renderPushTargets();}}});
function renderHealth(){const health=state.health||{};const database=health.database||{};const streamSummary=state.dashboardStats?.streams||{};const checks=[['API 服务',health.status==='ok'?'健康检查通过':'健康状态不可用',health.status==='ok'],['流会话管理',`${Number(streamSummary.total||0)} 个会话 · ${Number(streamSummary.errors||0)} 个异常`,Number(streamSummary.errors||0)===0],['事件存储',database.configured?`${database.backend||'database'} · ${database.schema||database.status||'未知状态'}`:'未配置数据库',database.status==='ok'||database.status==='fallback'],['统计数据',state.dashboardStats?`${state.dashboardStats.dataSource} · ${new Date(state.dashboardStats.generatedAt).toLocaleTimeString('zh-CN',{hour12:false})}`:`不可用 · ${state.dashboardStatsError||'等待连接'}`,Boolean(state.dashboardStats)]];$('health-list').innerHTML=checks.map(item=>`<div class="health-row"><span class="health-icon">${item[2]?'✓':'!'}</span><div><b>${esc(item[0])}</b><small>${esc(item[1])}</small></div><em>${item[2]?'正常':'异常'}</em></div>`).join('');const system=state.dashboardStats?.system||{};[['diag-cpu',system.cpu_percent],['diag-memory',system.memory_percent],['diag-gpu',Array.isArray(system.gpu)&&system.gpu[0]?system.gpu[0].utilization_percent:null],['diag-disk',system.disk_percent]].forEach(([id,value])=>{const root=$(id);if(!root)return;const valid=value!==null&&value!==undefined&&Number.isFinite(Number(value));const percent=valid?Math.max(0,Math.min(100,Number(value))):0;root.querySelector('b').textContent=valid?`${Number(value).toFixed(1)}%`:'不可用';root.querySelector('i').style.width=`${percent}%`;});}

// M11-T09 Live API adapter.  Read-only alert snapshots are available to both
// clients; disposition mutations require an admin token and operator header.
async function refreshLiveAlerts(){
  state.alertsStatus='loading';state.alertsError=null;renderAlerts();
  try{
    const headers=window.ADMIN_TOKEN?{'X-Admin-Token':window.ADMIN_TOKEN}:{};
    const response=await fetch('/api/alerts',{headers});
    if(!response.ok)throw Error(`HTTP ${response.status}`);
    const body=await response.json();
    state.liveAlerts=Array.isArray(body.events)?body.events:[];
    state.alertsStatus='ready';state.alertsError=null;renderAlerts();renderOverview();
  }catch(error){
    state.liveAlerts=[];state.alertsStatus='error';state.alertsError=error.message;renderAlerts();renderOverview();
  }
}
async function submitLiveDisposition(eventId,status){const path=status==='FALSE_POSITIVE'?'false-positive':status==='ACKNOWLEDGED'?'acknowledge':'close';const h={'Content-Type':'application/json'};if(window.ADMIN_TOKEN)h['X-Admin-Token']=window.ADMIN_TOKEN;if(window.OPERATOR_ID)h['X-Operator-Id']=window.OPERATOR_ID;const r=await fetch(`/api/alerts/${encodeURIComponent(eventId)}/${path}`,{method:'POST',headers:h,body:'{}'});if(!r.ok)throw Error(`HTTP ${r.status}`);await refreshLiveAlerts();await refreshDashboardStats();}
async function loadAlertVerification(event){
  const headers=window.ADMIN_TOKEN?{'X-Admin-Token':window.ADMIN_TOKEN}:{};
  try{const response=await fetch(`/api/alerts/${encodeURIComponent(event.eventId)}/verification`,{headers});if(!response.ok)throw Error(`HTTP ${response.status}`);event.verification=await response.json();if(state.selectedAlert===event.eventId)renderAlertVerification(event,event.verification);renderAlerts();}
  catch(error){if(state.selectedAlert===event.eventId)alertActionMessage(`复核状态读取失败：${error.message}`,'error');}
}
async function requestLiveVerification(eventId){const h={'Content-Type':'application/json'};if(window.ADMIN_TOKEN)h['X-Admin-Token']=window.ADMIN_TOKEN;if(window.OPERATOR_ID)h['X-Operator-Id']=window.OPERATOR_ID;const r=await fetch(`/api/alerts/${encodeURIComponent(eventId)}/verification`,{method:'POST',headers:h,body:'{}'});const body=await r.json().catch(()=>({}));if(!r.ok)throw Error(body?.detail?.message||`HTTP ${r.status}`);return body;}
async function syncLiveVerificationConfig(){if(state.demo)return;const h={'Content-Type':'application/json'};if(window.ADMIN_TOKEN)h['X-Admin-Token']=window.ADMIN_TOKEN;if(window.OPERATOR_ID)h['X-Operator-Id']=window.OPERATOR_ID;await fetch('/api/verification/config',{method:'POST',headers:h,body:JSON.stringify({enabled:!!$('verification-enabled')?.checked,imageEgressAuthorized:!!$('verification-image-consent')?.checked,dailyLimit:Number($('verification-limit')?.value||100),modelId:$('verification-model')?.value||'',providerConfigured:!!$('verification-key')?.value&&$('verification-key').value!=='••••••••••••'})});}
document.querySelectorAll('.nav-item').forEach(x=>x.onclick=()=>showView(x.dataset.view));
$('new-stream-btn').onclick=$('new-stream-btn-alt').onclick=()=>$('new-stream-dialog').showModal();
$('register-model-btn').onclick=()=>$('register-model-dialog').showModal();
$('new-rule-btn').onclick=()=>$('rule-dialog').showModal();
$('refresh-btn').onclick=()=>state.demo?(renderStreams(),renderInspector()):refreshLiveStreams();
$('refresh-models-btn')?.addEventListener('click',()=>refreshLiveModels());
$('refresh-bindings-btn')?.addEventListener('click',()=>{if(state.demo){renderStreamBindings();}else refreshLiveStreams();});
$('model-scenario-filter')?.addEventListener('change',e=>{state.modelScenario=e.target.value;renderModels();});
$('new-stream-form').onsubmit=async e=>{e.preventDefault();const id=$('stream-id').value.trim()||`inspection-${state.streams.length+1}`,source=$('source-url').value.trim(),submit=$('create-stream-submit'),status=$('new-stream-status');if(state.demo){state.streams.push({stream_id:id,source:source||'移动端推帧 · 新会话',frames_received:0,yolo_enabled:true,confidence:.25,max_fps:20,state:'等待推帧',tag:'待配置',model:{modelId:'site-safety-yolo11n',name:'工地安全生产模型',scenario:'工地安全',purpose:'business'}});state.selected=id;$('new-stream-dialog').close();renderOverview();renderStreams();renderStreamBindings();renderInspector();showView('streams');return;}submit.disabled=true;status.className='operation-banner';status.textContent='正在创建真实流会话…';try{const response=await fetch('/api/streams',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stream_id:id,source_url:source||null})});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body?.detail?.message||body?.detail||`HTTP ${response.status}`);state.selected=body.stream_id;$('new-stream-form').reset();$('new-stream-dialog').close();showView('streams');await refreshLiveStreams();}catch(error){status.className='operation-banner error';status.textContent=`创建失败 · ${error.message}`;}finally{submit.disabled=false;}};
$('register-model-form').onsubmit=e=>{e.preventDefault();const box=$('model-operation');box.classList.remove('hidden');box.textContent='请先连接管理服务，Manifest 登记只写入真实模型目录。';};
$('rule-form').onsubmit=e=>{e.preventDefault();$('rule-dialog').close();MOCK.rules.push([$('rule-name').value,'IN_REGION','person',$('rule-roi').value,'运行中','0 次','green']);renderRules();};
$('yolo-toggle').onchange=async e=>{const s=state.streams.find(x=>x.stream_id===state.selected);if(!s)return;if(state.demo){s.yolo_enabled=e.target.checked;renderStreams();renderInspector();return;}e.target.disabled=true;try{const response=await fetch(`/api/streams/${encodeURIComponent(s.stream_id)}/yolo`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:e.target.checked})});if(!response.ok)throw new Error(`HTTP ${response.status}`);await refreshLiveStreams();}catch(error){e.target.checked=s.yolo_enabled;txt('service-state',`YOLO 切换失败 · ${error.message}`);}finally{e.target.disabled=false;}};
$('stream-enabled-toggle').onchange=async e=>{const input=e.target,s=state.streams.find(x=>x.stream_id===state.selected);if(!s)return;const previous=s.enabled!==false,desired=input.checked;if(state.demo){s.enabled=desired;s.runtime_available=desired;renderStreams();renderInspector();return;}input.disabled=true;try{const saved=await updateSelectedStreamConfig({enabled:desired});if(!saved)input.checked=previous;}finally{input.disabled=false;}};
$('confidence').oninput=e=>txt('confidence-value',Number(e.target.value).toFixed(2));
$('max-fps').oninput=e=>txt('fps-value',e.target.value);
$('confidence').onchange=e=>updateSelectedStreamConfig({confidence:Number(e.target.value)});
$('max-fps').onchange=e=>updateSelectedStreamConfig({max_fps:Number(e.target.value)});
async function updateSelectedStreamConfig(values){const s=state.streams.find(x=>x.stream_id===state.selected);if(!s)return false;if(state.demo){Object.assign(s,values);renderInspector();return true;}try{const response=await fetch(`/api/streams/${encodeURIComponent(s.stream_id)}/config`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body?.detail?.message||body?.detail||`HTTP ${response.status}`);await refreshLiveStreams();return true;}catch(error){txt('service-state',`参数保存失败 · ${error.message}`);renderInspector();return false;}}
$('delete-btn').onclick=async()=>{const s=state.streams.find(x=>x.stream_id===state.selected);if(!s)return;if(state.demo){state.streams=state.streams.filter(item=>item.stream_id!==s.stream_id);state.selected=null;renderOverview();renderStreams();renderStreamBindings();renderInspector();return;}const button=$('delete-btn');button.disabled=true;try{const response=await fetch(`/api/streams/${encodeURIComponent(s.stream_id)}`,{method:'DELETE'});if(!response.ok)throw new Error(`HTTP ${response.status}`);state.selected=null;await refreshLiveStreams();}catch(error){txt('service-state',`删除失败 · ${error.message}`);}finally{button.disabled=false;}};
$('mode-toggle').onclick=()=>{state.demo=!state.demo;txt('service-state',state.demo?'演示数据已就绪':'Live API 待接入');$('mode-toggle').innerHTML=state.demo?'切换 Live API <span>→</span>':'返回 Demo 模式 <span>→</span>';};
document.querySelectorAll('.filter-chip').forEach(x=>x.onclick=()=>{document.querySelectorAll('.filter-chip').forEach(b=>b.classList.remove('active'));x.classList.add('active');state.alertFilter=x.dataset.filter||'all';renderAlerts();});
document.querySelectorAll('.range-btn').forEach(x=>x.onclick=()=>renderDashboard(x.dataset.range));
$('dashboard-fullscreen-btn').onclick=toggleDashboardFullscreen;
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement&&document.body.classList.contains('dashboard-focus-mode'))setDashboardFocusMode(false);});
$('confirm-alert-btn').onclick=async()=>{if(!state.selectedAlert)return;alertActionMessage('正在确认告警…');try{await submitLiveDisposition(state.selectedAlert,'ACKNOWLEDGED');$('alert-detail-dialog').close();}catch(error){alertActionMessage(`确认失败：${error.message}`,'error');}};
$('mark-false-btn').onclick=async()=>{if(!state.selectedAlert)return;alertActionMessage('正在标记误报…');try{await submitLiveDisposition(state.selectedAlert,'FALSE_POSITIVE');$('alert-detail-dialog').close();}catch(error){alertActionMessage(`标记失败：${error.message}`,'error');}};
setInterval(()=>txt('clock',new Date().toLocaleTimeString('zh-CN',{hour12:false})),1000);
// Business data is rendered only after the authentication gate opens.
document.querySelectorAll('.range-btn').forEach(x=>x.onclick=()=>refreshDashboardStats(x.dataset.range));
document.getElementById('verification-test')?.addEventListener('click',async()=>{const out=$('verification-status');if(state.demo){out.textContent='Mock：连接成功（演示）';out.className='operation-banner success';return;}try{await syncLiveVerificationConfig();out.textContent='Live API：配置已保存，可手动发起复核';out.className='operation-banner success';}catch(error){out.textContent=`Live API：保存失败 · ${error.message}`;out.className='operation-banner error';}});
['verification-enabled','verification-image-consent','verification-limit','verification-model','verification-key'].forEach(id=>$(id)?.addEventListener('change',()=>{if(!state.demo)syncLiveVerificationConfig().catch(()=>{});}));
