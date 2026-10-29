'use strict';
const UI = window.SafeDriveUI;
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const maxUpload = Number(document.querySelector('meta[name="max-upload-bytes"]').content);
const canUpload = document.querySelector('meta[name="can-upload"]').content === '1';
const canCamera = document.querySelector('meta[name="can-camera"]').content === '1';
const canReview = document.querySelector('meta[name="can-review"]').content === '1';
const publicViewer = document.querySelector('meta[name="user-role"]').content === 'public';
const defaultStatus = $('system-state').textContent;
const scope = UI.createSelectionScope();
const pages = {overview:'Overview', analysis:'Video Analysis', tracking:'Vehicle Tracking', helmets:'Helmet Compliance',
  speed:'Speed Violations', events:'Event Review', analytics:'Analytics', cameras:'Camera Management', settings:'Settings'};
let currentSession = null, tracks = [], events = [], sessions = [];
let historyState = 'loading', trackState = 'none', eventState = 'none', evidenceState = 'unavailable';
let selectedTrack = null, selectedEvent = null, eventsUrl = null, pollTimer = null, reader = null;
let activeMode = 'file', previewUrl = null, calibrationRevision = 0, calibrationCheck = 'missing', retryAction = null, submitting = false;

function el(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text != null) item.textContent = String(text);
  return item;
}
function action(text, handler, className = 'text-button') {
  const item = el('button', className, text); item.type = 'button'; item.addEventListener('click', handler); return item;
}
function empty(container, title, detail = '') {
  const block = el('div', 'empty-inline'); block.append(el('strong', '', title));
  if (detail) block.append(el('p', '', detail)); container.replaceChildren(block);
}
function badge(text, state = 'pending') { const item = el('span', 'state-badge', text); item.dataset.state = state; return item; }
function human(value) { return String(value || 'unknown').replaceAll('_', ' '); }
function dateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Date unavailable' : date.toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
}
function notice(message, retry = null, source = 'workspace') {
  $('workspace-notice').hidden = false; $('workspace-notice-text').textContent = message;
  $('workspace-notice').dataset.source = source;
  $('retry-workspace').hidden = !retry; retryAction = retry;
}
function clearNotice() { $('workspace-notice').hidden = true; retryAction = null; }
$('retry-workspace').addEventListener('click', () => retryAction?.());

function closeNav(focus = false) {
  document.body.classList.remove('nav-open'); $('nav-toggle').setAttribute('aria-expanded','false'); $('nav-toggle').setAttribute('aria-label','Open navigation');
  $('nav-backdrop').hidden = true; if (focus) $('nav-toggle').focus();
}
$('nav-toggle').addEventListener('click', () => {
  const open = !document.body.classList.contains('nav-open');
  document.body.classList.toggle('nav-open', open); $('nav-toggle').setAttribute('aria-expanded',String(open));
  $('nav-toggle').setAttribute('aria-label',open ? 'Close navigation' : 'Open navigation');
  $('nav-backdrop').hidden = !open; if (open) document.querySelector('.nav-item.active')?.focus();
});
$('nav-backdrop').addEventListener('click', () => closeNav(true));
window.matchMedia('(min-width: 761px)').addEventListener('change', event => { if (event.matches) closeNav(); });
document.addEventListener('keydown', event => {
  if (!document.body.classList.contains('nav-open')) return;
  if (event.key === 'Escape') return closeNav(true);
  if (event.key !== 'Tab') return;
  const items = [...$('workspace-navigation').querySelectorAll('a,button')], first = items[0], last = items.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
function navigatePage(page, updateHash = true, focus = false) {
  if (!pages[page]) page = 'overview';
  document.querySelectorAll('.page-view').forEach(view => { view.hidden = view.dataset.page !== page; });
  document.querySelectorAll('[data-page-link]').forEach(item => {
    const active = item.dataset.pageLink === page; item.classList.toggle('active',active);
    if (active && item.classList.contains('nav-item')) item.setAttribute('aria-current','page'); else item.removeAttribute('aria-current');
  });
  $('current-page-title').textContent = pages[page]; document.title = `${pages[page]} | SAFE-Drive`;
  if (updateHash && location.hash !== `#${page}`) history.replaceState(null,'',`#${page}`);
  closeNav();
  if (focus) { const heading = document.querySelector(`#page-${page} h1`); heading.tabIndex = -1; heading.focus({preventScroll:true}); window.scrollTo({top:0,behavior:'auto'}); }
}
document.querySelectorAll('[data-page-link],[data-open-page]').forEach(item => item.addEventListener('click', event => {
  event.preventDefault(); navigatePage(item.dataset.pageLink || item.dataset.openPage,true,true);
}));
window.addEventListener('hashchange', () => navigatePage(location.hash.slice(1),false));
navigatePage(location.hash.slice(1) || 'overview',false);

function restoreAnnotatedVideo() {
  $('video-comparison').prepend(document.querySelector('.annotated-wrap'));
  $('video-stage').classList.remove('has-annotated'); $('result-video').pause();
}
function featureAnnotatedVideo() {
  $('video-stage').append(document.querySelector('.annotated-wrap')); $('video-stage').classList.add('has-annotated');
  $('video-stage').hidden = false; $('source-preview').hidden = true; $('video-empty-state').hidden = true;
}
function showInputPreview() {
  restoreAnnotatedVideo(); $('video-stage').hidden = false;
  $('source-preview').hidden = activeMode !== 'file' || !previewUrl;
  $('video-empty-state').hidden = activeMode === 'file' && Boolean(previewUrl);
}
function runButton(busy, text) {
  $('run-button').disabled = busy || !(activeMode === 'camera' ? canCamera : canUpload);
  $('run-button').querySelector('span').textContent = text || (activeMode === 'camera' ? 'Start camera analysis' : 'Start video analysis');
}
function setMode(mode) {
  if (mode === 'camera' && !canCamera) { notice('Live cameras require a separately secured private operator instance.'); return; }
  activeMode = mode;
  document.querySelectorAll('.mode-option').forEach(item => {
    const selected = item.dataset.mode === mode; item.classList.toggle('selected',selected);
    item.setAttribute('aria-selected',String(selected)); item.tabIndex = selected ? 0 : -1;
  });
  $('file-source').hidden = mode !== 'file'; $('camera-source').hidden = mode !== 'camera';
  $('video-file').disabled = mode !== 'file'; $('stream-url').disabled = mode !== 'camera'; $('duration').disabled = mode !== 'camera';
  $('header-mode').textContent = mode === 'camera' ? 'Camera input' : 'Recorded video';
  $('viewer-caption').textContent = mode === 'camera' ? 'Connect a reachable, configured camera' : $('video-file').files[0]?.name || 'Select a video to preview it';
  $('viewer-mode-badge').textContent = mode === 'camera' ? 'Camera input' : previewUrl ? 'Input preview' : 'Ready';
  runButton(submitting || ['queued','running','stopping'].includes(currentSession?.status)); showInputPreview();
}
document.querySelectorAll('.mode-option').forEach(item => {
  item.addEventListener('click', () => setMode(item.dataset.mode));
  item.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault(); setMode(event.key === 'Home' ? 'file' : event.key === 'End' ? 'camera' : activeMode === 'file' ? 'camera' : 'file'); document.querySelector('.mode-option.selected').focus();
  });
});
document.querySelectorAll('[data-action="open-camera"]').forEach(item => item.addEventListener('click', () => {
  navigatePage('analysis',true,true); setMode('camera'); $('stream-url').focus();
}));
$('empty-select-video').addEventListener('click', () => { setMode('file'); $('video-file').click(); });
$('video-file').addEventListener('change', () => {
  const file = $('video-file').files[0];
  const error = file && !/\.(mp4|mov|mkv|avi|webm)$/i.test(file.name) ? 'Choose an MP4, MOV, MKV, AVI or WEBM video.' :
    file && file.size > maxUpload ? `The video exceeds the ${Math.round(maxUpload/1024/1024)} MB server limit.` : '';
  $('video-file').setCustomValidity(error); $('form-error').textContent = error;
  $('video-name').textContent = file?.name || 'No video selected';
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = file && !error ? URL.createObjectURL(file) : null;
  $('source-preview').src = previewUrl || ''; $('viewer-caption').textContent = file?.name || 'Select a video to preview it';
  $('viewer-mode-badge').textContent = previewUrl ? 'Input preview' : 'Ready'; $('viewer-frame-label').textContent = 'Input preview · not analysed'; $('media-feedback').hidden = true; showInputPreview();
});
['dragenter','dragover'].forEach(name => $('dropzone').addEventListener(name,event => { event.preventDefault(); $('dropzone').classList.add('dragover'); }));
['dragleave','drop'].forEach(name => $('dropzone').addEventListener(name,event => { event.preventDefault(); $('dropzone').classList.remove('dragover'); }));
$('dropzone').addEventListener('drop',event => {
  if (event.dataTransfer.files.length) { $('video-file').files = event.dataTransfer.files; $('video-file').dispatchEvent(new Event('change')); }
});
$('source-preview').addEventListener('error', () => {
  if (!previewUrl) return;
  $('media-feedback').hidden = false; $('media-feedback').textContent = 'This browser cannot preview the selected codec. The server may still process it; choose another clip if analysis fails.';
});

function calibrationMessage(message,state) { $('calibration-status').textContent = message; $('calibration-status').dataset.state = state; }
$('calibration-file').addEventListener('change',async () => {
  const revision = ++calibrationRevision, file = $('calibration-file').files[0];
  $('calibration-file').setCustomValidity(''); $('clear-calibration').hidden = !file;
  $('calibration-name').textContent = file?.name || 'Choose measured calibration';
  if (!file) { calibrationCheck = 'missing'; calibrationMessage('No calibration. Speed will be unavailable.','pending'); return; }
  calibrationCheck = 'checking'; calibrationMessage('Checking the calibration file…','pending');
  try {
    if (file.size > 1024*1024) throw new Error('Use a calibration JSON file smaller than 1 MB.');
    const checked = UI.validateCalibration(JSON.parse(await file.text()));
    if (revision !== calibrationRevision) return;
    calibrationCheck = 'checked'; calibrationMessage(checked.message,'valid');
  } catch (error) {
    if (revision !== calibrationRevision) return;
    calibrationCheck = 'invalid';
    const message = error instanceof SyntaxError ? 'This is not valid JSON. Replace it or remove calibration to continue without speed.' : error.message;
    $('calibration-file').setCustomValidity(message); calibrationMessage(message,'error');
  }
});
$('clear-calibration').addEventListener('click', () => { $('calibration-file').value = ''; $('calibration-file').dispatchEvent(new Event('change')); });
$('calibration-template').addEventListener('click', () => {
  const template = {camera_id:'replace-with-camera-id',image_points_px:Array.from({length:4},()=>[null,null]),
    road_points_m:Array.from({length:4},()=>[null,null]),notes:'Replace every null with measured pixel/metre correspondences. Blank coordinates are intentionally invalid.'};
  const url = URL.createObjectURL(new Blob([JSON.stringify(template,null,2)],{type:'application/json'}));
  const link = el('a'); link.href = url; link.download = 'camera-calibration-template.json'; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('analysis-form').addEventListener('invalid',event => { $('form-error').textContent = event.target.validationMessage || 'Check the required analysis inputs.'; },true);
$('analysis-form').addEventListener('submit',async event => {
  if (!(activeMode === 'camera' ? canCamera : canUpload)) { event.preventDefault(); notice('This account cannot start analysis. Public samples are read-only.'); return; }
  event.preventDefault();
  if (submitting) return;
  if (calibrationCheck === 'checking') { $('form-error').textContent = 'Wait for the calibration file check to finish.'; return; }
  const mode = activeMode, inputName = $('video-file').files[0]?.name;
  submitting = true; $('form-error').textContent = ''; runButton(true,mode === 'camera' ? 'Connecting…' : 'Uploading…');
  const token = scope.next(); clearTimeout(pollTimer);
  try {
    const data = await UI.requestJSON(mode === 'camera' ? '/api/camera-jobs' : '/api/jobs',{
      method:'POST',headers:{'X-CSRF-Token':csrf},body:new FormData($('analysis-form'))});
    if (scope.current(token)) showJob(data.id,mode === 'camera',inputName);
    loadSessions();
  } catch (error) { if (scope.current(token)) $('form-error').textContent = error.message; runButton(false); }
  finally { submitting = false; }
});

function activateSession(session) {
  clearTimeout(pollTimer); reader?.abort();
  const token = scope.next(); currentSession = {...session,session_id:session.session_id || session.id};
  tracks = []; events = []; selectedTrack = null; selectedEvent = null; trackState = 'loading'; eventState = 'loading'; evidenceState = 'unavailable';
  $('result-video').pause(); $('result-video').removeAttribute('src'); $('result-video').load();
  $('media-feedback').hidden = true; $('review-feedback').textContent = ''; $('job-error').hidden = true;
  restoreAnnotatedVideo(); renderTracks(); renderEvents(); updateContext(); return token;
}
function updateContext() {
  renderSessionPicker();
  if (!currentSession) return;
  const session = currentSession, source = session.source_mode === 'rtsp' ? 'Camera recording' : 'Uploaded video';
  const name = session.input_name || session.name || `Session ${session.session_id.slice(0,8)}`;
  const calibration = UI.calibrationState(session.calibration_status);
  $('session-source-label').textContent = `${source} · ${name}`;
  $('session-calibration-status').textContent = calibration.label; $('session-calibration-status').dataset.state = calibration.tone;
  $('session-calibration-status').title = calibration.detail; $('system-state').textContent = `${human(session.status)} · ${source.toLowerCase()}`;
  $('header-mode').textContent = source; $('tracking-session-name').textContent = name;
  $('event-session-label').textContent = `${name} · ${session.session_id.slice(0,8)} · ${human(session.status)}`;
}
function showJob(id,live,inputName) {
  const token = activateSession({id,source_mode:live?'rtsp':'uploaded_video',status:'queued',
    name:live?'Camera session':inputName || 'Video session',calibration_status:calibrationCheck === 'checked'?'configured':'missing'});
  eventsUrl = `/api/jobs/${id}/events`; navigatePage('analysis');
  $('results').hidden = false; $('results-content').hidden = true; $('processing-state').hidden = false;
  $('processing-message').textContent = 'Queued for the local worker…'; $('stop-button').hidden = !live; $('stop-button').disabled = false;
  runButton(true,'Analysis running…'); showInputPreview(); pollJob(id,token);
}
async function refreshEvents(token) {
  try {
    const data = await UI.requestJSON(eventsUrl); if (!scope.current(token)) return;
    events = data.events || []; eventState = 'loaded'; renderEvents();
  } catch (error) { if (scope.current(token)) { eventState = 'error'; renderEvents(); $('event-results-summary').textContent = error.message; } }
}
async function pollJob(id,token) {
  if (!scope.current(token)) return;
  clearTimeout(pollTimer);
  try {
    const job = await UI.requestJSON(`/api/jobs/${id}`); if (!scope.current(token)) return;
    if ($('workspace-notice').dataset.source === 'job') clearNotice();
    currentSession = {...currentSession,...job,session_id:id}; updateContext();
    $('job-status').textContent = human(job.status); $('job-status').dataset.state = job.status; $('viewer-mode-badge').textContent = human(job.status);
    const running = ['queued','running','stopping'].includes(job.status), frames = UI.count(job.frames_processed), elapsed = UI.number(job.elapsed_s);
    $('processing-state').hidden = !running;
    $('stop-button').hidden = !job.live || !running;
    $('processing-message').textContent = job.status === 'queued' ? 'Queued. Waiting for the local worker.' : `${human(job.status)} · ${frames === '—'?'frame count unavailable':`${frames} frames processed`}${elapsed == null?'':` · ${elapsed.toFixed(1)} s elapsed`}`;
    $('job-summary').textContent = running ? 'Detection, tracking and configured rules run locally. Annotated playback appears after processing completes.' :
      `${job.name || 'Analysis'} · ${frames} frames · ${UI.calibrationState(job.calibration_status).label}${job.warning?` · ${job.warning}`:''}`;
    if (job.tracks) { tracks = job.tracks.tracks || []; trackState = 'loaded'; renderTracks(); $('results-content').hidden = false; }
    if (running) {
      $('stop-button').disabled = job.status === 'stopping';
      if (job.status !== 'queued') await refreshEvents(token);
      if (scope.current(token)) pollTimer = setTimeout(()=>pollJob(id,token),2000);
      return;
    }
    runButton(false); $('stop-button').hidden = true;
    if (job.status === 'failed') { $('job-error').hidden = false; $('job-error').textContent = UI.jobFailure(job.error); eventState = 'error'; renderEvents(); }
    else if (job.status === 'completed') {
      $('results-content').hidden = false;
      loadRecording(`/api/jobs/${id}/video`,job.source_mode === 'uploaded_video'?`/api/sessions/${id}/original`:null);
      await refreshEvents(token);
    } else { $('job-summary').textContent = 'This session was cancelled before usable output became available.'; eventState = 'loaded'; renderEvents(); }
    loadSessions();
  } catch (error) {
    if (!scope.current(token)) return;
    $('job-summary').textContent = error.status === 404 ? 'Live job state is unavailable, possibly after a server restart. Saved metadata remains in history.' : 'Could not refresh processing status. The worker may still be running.';
    notice(error.message,()=>pollJob(id,token),'job');
    if (error.status !== 404) pollTimer = setTimeout(()=>pollJob(id,token),7000);
    else { $('processing-state').hidden = true; runButton(false); }
  }
}
function loadRecording(url,original) {
  evidenceState = 'loading'; $('media-feedback').hidden = true; $('result-video').src = url;
  $('original-result').parentElement.hidden = !original; $('video-comparison').hidden = !original;
  if (original) $('original-result').src = original; else $('original-result').removeAttribute('src');
  featureAnnotatedVideo(); $('viewer-frame-label').textContent = 'Annotated output · loading recording';
}
$('result-video').addEventListener('loadedmetadata',()=>{
  if (currentSession?.status !== 'completed') return;
  evidenceState = 'ready'; $('viewer-frame-label').textContent = 'Annotated recording · boxes are encoded in the video'; renderEvents();
});
$('result-video').addEventListener('error',()=>{
  if (!currentSession || evidenceState === 'unavailable') return;
  evidenceState = 'unavailable'; $('media-feedback').hidden = false;
  $('media-feedback').textContent = 'The recording is missing or cannot be decoded by this browser. Saved tracks and events remain available; check that evidence files exist on this host.';
  $('viewer-frame-label').textContent = 'Recording unavailable'; renderEvents();
});
$('stop-button').addEventListener('click',async()=>{
  if (!currentSession) return;
  const id = currentSession.session_id; $('stop-button').disabled = true; $('stop-button').textContent = 'Stopping…';
  try {
    await UI.requestJSON(`/api/jobs/${id}/stop`,{method:'POST',headers:{'X-CSRF-Token':csrf}});
    if (currentSession?.session_id === id) $('processing-message').textContent = 'Stop requested. Waiting for the worker to release the stream.';
  } catch (error) { $('stop-button').disabled = false; notice(error.message); }
  finally { $('stop-button').textContent = 'Stop camera'; }
});

function tableEmpty(tbody,columns,message) {
  const row = el('tr'), cell = el('td','empty-track',message); cell.colSpan = columns; row.append(cell); tbody.replaceChildren(row);
}
function detailList(pairs) {
  const list = el('dl','detail-list'); pairs.forEach(([label,value])=>list.append(el('dt','',label),el('dd','',value))); return list;
}
function renderTracks() {
  const loaded = trackState === 'loaded', pedestrians = tracks.filter(track=>['person','pedestrian'].includes(track.object_class || track.vehicle_class)).length;
  const valid = tracks.filter(track=>UI.trackSpeed(track)!=null).length;
  for (const [id,value] of [['result-object-count',tracks.length],['result-vehicle-count',tracks.length-pedestrians],['result-pedestrian-count',pedestrians],['result-speed-count',valid]]) $(id).textContent = loaded?UI.count(value):'—';
  $('track-count').textContent = loaded?`${tracks.length} tracks · ${valid} with valid speed`:trackState === 'loading'?'Loading tracks…':'No track data loaded';
  $('result-track-summary').textContent = loaded?`${tracks.length} tracked objects · ${valid} available speeds`:'Select or process a session to inspect actual results.';
  applyTrackFilter(); renderTrackDetail();
}
function applyTrackFilter() {
  const tbody = $('track-table'), query = $('track-filter').value.trim().toLowerCase();
  if (trackState !== 'loaded') { tableEmpty(tbody,6,trackState === 'loading'?'Loading saved tracks…':trackState === 'error'?'Could not load tracks. Retry the selected session.':'Choose an analysis session to inspect its tracks.'); return; }
  const filtered = tracks.filter(track=>`${track.track_id} ${track.object_class || track.vehicle_class}`.toLowerCase().includes(query));
  if (!filtered.length) { tableEmpty(tbody,6,tracks.length?'No tracks match this search.':'No confirmed tracks were saved for this session.'); return; }
  tbody.replaceChildren();
  filtered.forEach(track=>{
    const row = el('tr'); row.tabIndex = 0; row.setAttribute('aria-label',`Inspect ${track.object_class || track.vehicle_class} track ${track.track_id}`);
    row.setAttribute('aria-selected',String(String(track.track_id)===selectedTrack)); row.classList.toggle('selected-track',String(track.track_id)===selectedTrack);
    [track.track_id,track.object_class || track.vehicle_class,UI.measurement(UI.trackSpeed(track),' km/h'),human(track.speed_quality),UI.count(track.observations),track.active?'Active':'Completed'].forEach((value,index)=>row.append(el('td',index===0?'track-id':'',value)));
    const inspect=()=>{ selectedTrack=String(track.track_id); applyTrackFilter(); renderTrackDetail(); };
    row.addEventListener('click',inspect); row.addEventListener('keydown',event=>{if (['Enter',' '].includes(event.key)) {event.preventDefault();inspect();}}); tbody.append(row);
  });
}
function renderTrackDetail() {
  const detail=$('track-detail'), track=tracks.find(item=>String(item.track_id)===selectedTrack);
  if (!track) {empty(detail,'Inspect a track','Choose a row with the mouse, Enter or Space to see its measurements and related events.');return;}
  detail.replaceChildren(el('h3','',`Track ${track.track_id} · ${track.object_class || track.vehicle_class}`));
  detail.append(detailList([['Observed',`${UI.timestamp(track.first_seen_s)} to ${UI.timestamp(track.last_seen_s)}`],['Latest speed',UI.measurement(UI.trackSpeed(track),' km/h')],['Speed quality',human(track.speed_quality)],
    ['Detection confidence',UI.number(track.confidence)==null?'Unavailable':`${(Number(track.confidence)*100).toFixed(1)}%`],['Observations',UI.count(track.observations)],
    ['Last box (pixels)',(track.bbox_xyxy || []).map(value=>Number(value).toFixed(0)).join(', ') || 'Unavailable'],['Helmet model',track.helmet_class?`${human(track.helmet_class)} · experimental`:'No classification available']]));
  const related=events.filter(event=>UI.trackIds(event).includes(selectedTrack)), links=el('div','track-events');
  related.forEach(event=>links.append(action(`${eventLabel(event)} · ${UI.timestamp(event.timestamp_s)}`,()=>{selectedEvent=event.event_id;navigatePage('events',true,true);renderEventDetail();},'event-evidence')));
  detail.append(related.length?links:el('p','data-caption','No saved events reference this track.'));
}
$('track-filter').addEventListener('input',applyTrackFilter);

function eventLabel(event) {return event.event_type==='speed_limit_exceeded'?'Speed-rule event':event.event_type==='approach_risk_screen'?'Approach-risk signal':human(event.event_type || 'Saved event');}
function severityLabel(event) {const value=UI.severity(event);return value==='speed'?'Configured rule':value==='unknown'?'Unrated signal':`${value} risk · experimental`;}
function eventDescription(event) {
  if (event.event_type==='speed_limit_exceeded') return `Track ${event.track_id ?? '—'} · ${UI.measurement(event.speed_kmh,' km/h')} · limit ${UI.measurement(event.speed_limit_kmh,' km/h',0)} · tolerance ${UI.measurement(event.tolerance_kmh,' km/h',0)}`;
  const encounter=event.encounter || {};
  if (encounter.track_a!=null) return `Tracks ${UI.trackIds(event).join(' / ')} · TTC ${UI.measurement(encounter.ttc_s,' s')} · closest approach ${UI.measurement(encounter.closest_distance_m,' m')}`;
  return event.description || 'Saved screening signal. Inspect the measurements and recording before review.';
}
function eventCard(event) {
  const card=el('article','event-card');card.dataset.severity=UI.severity(event);card.classList.toggle('selected-event',event.event_id===selectedEvent);
  const badges=el('div','event-badges');badges.append(badge(severityLabel(event),UI.severity(event)),badge(human(event.review_status || 'pending'),event.review_status || 'pending'));
  const title=el('div','event-title');title.append(el('strong','',eventLabel(event)),el('span','event-time',UI.timestamp(event.timestamp_s)));
  card.append(badges,title,el('p','event-details',eventDescription(event)),el('p','event-meta',`Frame ${event.frame ?? 'unavailable'} · ${String(event.event_id || '').slice(0,14) || 'ID unavailable'}`));
  const controls=el('div','event-card-actions');controls.append(action('Inspect event',()=>{selectedEvent=event.event_id;applyEventFilters();renderEventDetail();$('event-detail').focus({preventScroll:true});},'button button-secondary'));
  if (evidenceState==='ready' && UI.number(event.timestamp_s)!=null) controls.append(action('View recording',()=>jumpToEvent(event.timestamp_s),'event-evidence'));
  card.append(controls);return card;
}
function renderEvents() {
  $('pending-nav-state').textContent=eventState==='loaded'?`${events.filter(event=>(event.review_status || 'pending')==='pending').length} pending`:'—';
  applyEventFilters();renderEventDetail();renderSpeedEvents();renderTimeline();renderTrackDetail();
}
function applyEventFilters() {
  const list=$('event-list');
  if (eventState!=='loaded') {
    empty(list,eventState==='loading'?'Loading session events…':eventState==='error'?'Events could not be loaded':'Choose a session to begin',eventState==='error'?'Use the session selector or refresh history to retry.':'Only actual saved events appear here.');
    $('event-results-summary').textContent=eventState==='loading'?'Loading…':'No event data loaded.';return;
  }
  const filtered=UI.filterEvents(events,{query:$('event-search').value,type:$('event-type-filter').value,status:$('event-status-filter').value,severity:$('event-severity-filter').value});
  $('event-results-summary').textContent=`${filtered.length} of ${events.length} saved events · newest first`;
  if (!filtered.length) {empty(list,events.length?'No events match these filters':'No events saved for this session',events.length?'Clear the filters or try another track ID.':'This does not establish that the footage is free of safety incidents.');return;}
  list.replaceChildren(...filtered.map(eventCard));
}
function renderEventDetail() {
  const detail=$('event-detail'),event=events.find(item=>item.event_id===selectedEvent);
  if (!event) {empty(detail,'Inspect an event','Select a saved event to view measurements, related tracks and the available recording.');return;}
  detail.replaceChildren(el('h3','',eventLabel(event)));detail.append(badge(severityLabel(event),UI.severity(event)),badge(human(event.review_status || 'pending'),event.review_status || 'pending'));
  detail.append(detailList([['Event ID',event.event_id],['Time in recording',UI.timestamp(event.timestamp_s)],['Frame',event.frame ?? 'Unavailable'],['Review status',human(event.review_status || 'pending')],['Measurement',eventDescription(event)],['Recorded confirmation',UI.number(event.confirmed_duration_s)==null?'Not available':`${event.confirmed_duration_s} seconds`]]));
  const links=el('div','track-events');UI.trackIds(event).forEach(id=>links.append(action(`Inspect track ${id}`,()=>{selectedTrack=id;$('track-filter').value='';navigatePage('tracking',true,true);renderTracks();},'event-evidence')));detail.append(links);
  if (evidenceState==='ready' && UI.number(event.timestamp_s)!=null) detail.append(action('Open recording at this time',()=>jumpToEvent(event.timestamp_s),'button button-secondary'));
  else detail.append(el('p','data-caption',evidenceState==='loading'?'Recording is loading. Evidence controls appear when playback is available.':'No playable recording is available for this session on this host.'));
  if (canReview && (event.review_status || 'pending')==='pending' && event.event_id) {
    const controls=el('div','review-actions');controls.append(action('Verify event',()=>reviewEvent(event.event_id,'verified'),'review-verify'),action('Reject event',()=>reviewEvent(event.event_id,'rejected'),'review-reject'));
    detail.append(el('p','data-caption','Enter your reviewer name above before saving a decision.'),controls);
  } else if (event.reviewer) detail.append(el('p','data-caption',`Reviewed by ${event.reviewer} · ${dateTime(event.reviewed_at)}`));
}
async function reviewEvent(eventId,decision) {
  if (!canReview) return notice('This account cannot save review decisions.');
  const reviewer=$('reviewer-name').value.trim();
  if (!reviewer) {$('review-feedback').textContent='Enter your reviewer name or initials before saving a decision.';$('reviewer-name').setAttribute('aria-invalid','true');$('reviewer-name').focus();return;}
  $('reviewer-name').removeAttribute('aria-invalid');const id=currentSession?.session_id;
  $('review-feedback').textContent='Saving your review…';document.querySelectorAll('.review-actions button').forEach(button=>{button.disabled=true;});
  let saved=false;
  try {
    await UI.requestJSON(`/api/events/${encodeURIComponent(eventId)}/review`,{method:'POST',headers:{'X-CSRF-Token':csrf,'Content-Type':'application/json'},body:JSON.stringify({decision,reviewer})});saved=true;
    if (currentSession?.session_id!==id) return;
    const data=await UI.requestJSON(eventsUrl);if (currentSession?.session_id!==id)return;
    events=data.events || [];eventState='loaded';renderEvents();$('review-feedback').textContent='Review saved to SQLite.';loadSessions();
  } catch(error) {if(currentSession?.session_id===id)$('review-feedback').textContent=saved?'Review saved, but the event list could not refresh. Reload the selected session.':error.message;}
  finally {document.querySelectorAll('.review-actions button').forEach(button=>{button.disabled=false;});}
}
['event-search','event-type-filter','event-status-filter','event-severity-filter'].forEach(id=>$(id).addEventListener(id==='event-search'?'input':'change',applyEventFilters));
$('clear-event-filters').addEventListener('click',()=>{$('event-search').value='';['event-type-filter','event-status-filter','event-severity-filter'].forEach(id=>{$(id).value='all';});applyEventFilters();});
function jumpToEvent(value) {
  if(evidenceState!=='ready')return;const player=$('result-video'),time=UI.number(value);if(time==null)return;
  navigatePage('analysis');featureAnnotatedVideo();player.currentTime=Math.max(0,Math.min(player.duration,time));player.scrollIntoView({behavior:'smooth',block:'center'});player.play().catch(()=>{});
}
function renderTimeline() {
  const timeline=$('event-timeline'),player=$('result-video'),items=events.filter(event=>UI.number(event.timestamp_s)!=null && Number(event.timestamp_s)>=0);
  if (!items.length || evidenceState!=='ready' || !Number.isFinite(player.duration) || player.duration<=0) {timeline.replaceChildren(el('div','timeline-empty',items.length?'Load a playable recording to position saved timestamps.':'No saved event timestamps.'));return;}
  timeline.replaceChildren();items.forEach(event=>{
    const marker=action('',()=>jumpToEvent(event.timestamp_s),`timeline-marker ${event.event_type==='speed_limit_exceeded'?'speed':''}`);
    marker.style.left=`${Math.max(0,Math.min(100,Number(event.timestamp_s)/player.duration*100))}%`;marker.title=`${eventLabel(event)} · ${UI.timestamp(event.timestamp_s)}`;marker.setAttribute('aria-label',marker.title);timeline.append(marker);
  });
}
function renderSpeedEvents() {
  const all=events.filter(event=>event.event_type==='speed_limit_exceeded'),loaded=eventState==='loaded';
  $('speed-event-count').textContent=loaded?UI.count(all.length):'—';
  const speeds=all.map(event=>UI.number(event.speed_kmh)).filter(value=>value!=null),limits=[...new Set(all.map(event=>UI.number(event.speed_limit_kmh)).filter(value=>value!=null))];
  $('speed-peak-speed').textContent=speeds.length?UI.measurement(Math.max(...speeds),' km/h'):'—';$('speed-limit-summary').textContent=limits.length?limits.map(value=>`${value} km/h`).join(', '):'—';
  const list=$('speed-event-list');if(!loaded){tableEmpty(list,7,eventState==='loading'?'Loading speed-rule events…':'Choose a session to see its saved speed-rule events.');return;}
  const filtered=UI.filterEvents(all,{query:$('speed-search').value,status:$('speed-status-filter').value});
  if(!filtered.length){tableEmpty(list,7,all.length?'No speed events match these filters.':'No confirmed speed-rule events were saved.');return;}
  list.replaceChildren();filtered.forEach(event=>{
    const row=el('tr'),speed=UI.number(event.speed_kmh),limit=UI.number(event.speed_limit_kmh);
    [UI.timestamp(event.timestamp_s),event.track_id ?? 'Unavailable',UI.measurement(speed,' km/h'),`${UI.measurement(limit,' km/h',0)} + ${UI.measurement(event.tolerance_kmh,' km/h',0)}`,speed!=null && limit!=null?`+${(speed-limit).toFixed(1)} km/h`:'Unavailable',human(event.review_status || 'pending')].forEach(value=>row.append(el('td','',value)));
    const cell=el('td');cell.append(action('Inspect',()=>{selectedEvent=event.event_id;navigatePage('events',true,true);renderEvents();},'event-evidence'));row.append(cell);list.append(row);
  });
}
$('speed-search').addEventListener('input',renderSpeedEvents);$('speed-status-filter').addEventListener('change',renderSpeedEvents);

function renderSessionPicker() {
  const select=$('session-select');select.replaceChildren(new Option(historyState==='loading'?'Loading saved sessions…':sessions.length?'Choose a session':'No saved sessions yet',''));
  const options=sessions.slice();if(currentSession && !options.some(item=>item.session_id===currentSession.session_id))options.unshift(currentSession);
  options.forEach(session=>select.add(new Option(`${session.input_name || session.name || session.session_id.slice(0,8)} · ${human(session.status)}`,session.session_id)));
  select.value=currentSession?.session_id || '';select.disabled=historyState==='loading' && !options.length;
}
function renderHistory() {
  const list=$('history-list');
  if(historyState!=='loaded'){empty(list,historyState==='loading'?'Loading saved sessions…':'Session history unavailable',historyState==='error'?'Refresh history to retry the local database request.':'Reading actual records from SQLite.');$('history-summary').textContent=historyState==='loading'?'Loading…':'History request failed.';return;}
  const query=$('history-search').value.trim().toLowerCase(),status=$('history-status').value;
  const filtered=sessions.filter(session=>(status==='all' || session.status===status) && `${session.input_name} ${session.camera_id} ${session.session_id}`.toLowerCase().includes(query));
  $('history-summary').textContent=`${filtered.length} of ${sessions.length} recent sessions${sessions.length>=50?' · API shows the latest 50 records':''}`;
  if(!filtered.length){empty(list,sessions.length?'No sessions match this search':'Your first analysis starts here',sessions.length?'Try another filename, camera or status.':'Upload a traffic clip or configure a reachable camera. No sample results are populated.');return;}
  list.replaceChildren();filtered.forEach(session=>{
    const row=action('',()=>openSavedSession(session),'history-row');row.classList.toggle('selected-session',currentSession?.session_id===session.session_id);
    row.setAttribute('aria-label',`Open ${session.input_name}, ${session.status}, ${dateTime(session.started_at)}`);
    const name=el('div','history-identity');name.append(el('strong','history-name',session.input_name),el('small','',`${session.source_mode==='rtsp'?'Camera':'Video'} · ${session.session_id.slice(0,8)}`));
    row.append(name,badge(human(session.status),session.status),el('span','history-date',dateTime(session.started_at)),el('span','history-calibration',UI.calibrationState(session.calibration_status).label),el('span','history-open','Open →'));list.append(row);
  });
}
async function loadSessions() {
  $('refresh-history').disabled=true;$('history-list').setAttribute('aria-busy','true');
  const results=await Promise.allSettled([UI.requestJSON('/api/sessions'),UI.requestJSON('/api/analytics')]),errors=[];
  if(results[0].status==='fulfilled'){sessions=results[0].value.sessions || [];historyState='loaded';}else{historyState='error';errors.push(results[0].reason.message);}
  if(results[1].status==='fulfilled')updateAnalytics(results[1].value);else{updateAnalytics(null);errors.push('Workspace analytics could not be loaded.');}
  renderSessionPicker();renderHistory();$('refresh-history').disabled=false;$('history-list').setAttribute('aria-busy','false');
  if(errors.length)notice(errors.join(' '),loadSessions);else if(!retryAction || retryAction===loadSessions)clearNotice();
}
function updateAnalytics(data) {
  const mappings={'overview-session-count':'sessions','overview-track-count':'vehicle_tracks','overview-pedestrian-count':'pedestrians','overview-pending-count':'pending_events','overview-calibrated-count':'tracks_with_valid_speed','analytics-sessions':'sessions','analytics-frames':'frames_processed','analytics-tracks':'vehicle_tracks','analytics-reviewed':'reviewed_events'};
  Object.entries(mappings).forEach(([id,key])=>{$(id).textContent=UI.count(data?.[key]);});
  const chart=$('analytics-chart');if(!data){empty(chart,'Analytics unavailable','Retry the workspace request. Missing data is not represented as zero.');return;}
  if(!data.activity?.length){empty(chart,'No session activity yet','The chart uses saved session counts by day.');return;}
  const bars=el('div','chart-bars'),max=Math.max(...data.activity.map(day=>Number(day.sessions)),1);
  data.activity.forEach(day=>{const bar=el('div','chart-bar');bar.style.height=`${Number(day.sessions)/max*100}%`;bar.title=`${day.day}: ${day.sessions} sessions`;bar.append(el('span','',`${day.day.slice(5)} · ${day.sessions}`));bars.append(bar);});chart.replaceChildren(bars);
}
async function openSavedSession(session,keepPage=false) {
  const token=activateSession(session);reader=new AbortController();eventsUrl=`/api/sessions/${session.session_id}/events`;
  if(!keepPage)navigatePage('analysis',true,true);
  $('results').hidden=false;$('results-content').hidden=false;$('processing-state').hidden=true;$('stop-button').hidden=true;runButton(false);
  $('job-status').textContent=human(session.status);$('job-status').dataset.state=session.status;
  $('job-summary').textContent=`${session.input_name} · ${UI.count(session.frames_processed)} frames · ${UI.calibrationState(session.calibration_status).label}`;
  $('viewer-caption').textContent=session.input_name;$('viewer-mode-badge').textContent='Saved session';restoreAnnotatedVideo();$('source-preview').hidden=true;$('video-empty-state').hidden=false;
  if(session.status==='failed'){$('job-error').hidden=false;$('job-error').textContent=UI.jobFailure(session.error_message);}
  if(session.status==='completed')loadRecording(`/api/sessions/${session.session_id}/video`,session.source_mode==='uploaded_video'?`/api/sessions/${session.session_id}/original`:null);
  const results=await Promise.allSettled([UI.requestJSON(`/api/sessions/${session.session_id}/tracks`,{signal:reader.signal}),UI.requestJSON(eventsUrl,{signal:reader.signal})]);
  if(!scope.current(token))return;
  if(results[0].status==='fulfilled'){tracks=results[0].value.tracks || [];trackState='loaded';}else trackState='error';
  if(results[1].status==='fulfilled'){events=results[1].value.events || [];eventState='loaded';}else eventState='error';
  renderTracks();renderEvents();renderHistory();
  if(results.some(result=>result.status==='rejected'))notice('Some saved details could not be loaded.',()=>openSavedSession(session,true),'details');
  else if($('workspace-notice').dataset.source==='details')clearNotice();
  if(['queued','running','stopping'].includes(session.status))pollJob(session.session_id,token);
}
$('session-select').addEventListener('change',()=>{const session=sessions.find(item=>item.session_id===$('session-select').value);if(session)openSavedSession(session,true);});
$('refresh-history').addEventListener('click',loadSessions);$('history-search').addEventListener('input',renderHistory);$('history-status').addEventListener('change',renderHistory);
window.addEventListener('beforeunload',()=>{if(previewUrl)URL.revokeObjectURL(previewUrl);});
document.querySelectorAll('.mode-option[data-mode="camera"]').forEach(button=>{button.disabled=!canCamera;});
$('stream-url').readOnly=true;$('stream-url').placeholder='Server-registered camera only; leave blank';
if(publicViewer){
  $('header-mode').textContent='Read-only public sample';
  const sample=$('demo-video-button');
  UI.requestJSON('/api/demo').then(data=>{
    if(!sample || !data.available)return;
    sample.hidden=false;sample.addEventListener('click',()=>{
      navigatePage('analysis',true,true);restoreAnnotatedVideo();
      $('source-preview').src=data.video_url;$('source-preview').hidden=false;$('video-empty-state').hidden=true;
      $('viewer-caption').textContent=`Licensed sample playback · no inference · ${data.license}`;
      $('viewer-mode-badge').textContent='Sample / no inference';
    });
  }).catch(()=>notice('The public sample is unavailable. No AI results are shown.'));
}
runButton(false);
renderTracks();renderEvents();loadSessions();
