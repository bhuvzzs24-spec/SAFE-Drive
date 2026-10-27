const csrf = document.querySelector('meta[name="csrf-token"]').content;
const form = document.getElementById('analysis-form');
const videoInput = document.getElementById('video-file');
const calibrationInput = document.getElementById('calibration-file');
const dropzone = document.getElementById('dropzone');
const button = document.getElementById('run-button');
const errorBox = document.getElementById('form-error');
let pollTimer = null;
let activeMode = 'file';
let activeJobId = null;

document.querySelectorAll('.mode-option').forEach(option => option.addEventListener('click', () => {
  activeMode = option.dataset.mode;
  document.querySelectorAll('.mode-option').forEach(item => {
    const selected = item === option;
    item.classList.toggle('selected', selected);
    item.setAttribute('aria-selected', String(selected));
  });
  document.getElementById('file-source').hidden = activeMode !== 'file';
  document.getElementById('camera-source').hidden = activeMode !== 'camera';
  videoInput.disabled = activeMode !== 'file';
  document.getElementById('stream-url').disabled = activeMode !== 'camera';
  document.getElementById('duration').disabled = activeMode !== 'camera';
  document.getElementById('run-button').querySelector('span:nth-child(2)').textContent = activeMode === 'camera' ? 'Connect to live camera' : 'Run video analysis';
}));

videoInput.addEventListener('change', () => {
  document.getElementById('video-name').textContent = videoInput.files[0]?.name || 'No video selected';
});
calibrationInput.addEventListener('change', () => {
  document.getElementById('calibration-name').textContent = calibrationInput.files[0]?.name || 'Select site calibration…';
});
['dragenter', 'dragover'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.add('dragover'); }));
['dragleave', 'drop'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.remove('dragover'); }));
dropzone.addEventListener('drop', event => {
  if (event.dataTransfer.files.length) {
    videoInput.files = event.dataTransfer.files;
    videoInput.dispatchEvent(new Event('change'));
  }
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  errorBox.textContent = '';
  button.disabled = true;
  button.querySelector('span:nth-child(2)').textContent = 'Uploading video…';
  const data = new FormData(form);
  try {
    const endpoint = activeMode === 'camera' ? '/api/camera-jobs' : '/api/jobs';
    button.querySelector('span:nth-child(2)').textContent = activeMode === 'camera' ? 'Connecting to camera…' : 'Uploading video…';
    const response = await fetch(endpoint, {method: 'POST', headers: {'X-CSRF-Token': csrf}, body: data});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not start analysis.');
    showJob(result.id, activeMode === 'camera');
  } catch (error) {
    errorBox.textContent = error.message;
    button.disabled = false;
    button.querySelector('span:nth-child(2)').textContent = 'Run video analysis';
  }
});

function showJob(id, isLive) {
  activeJobId = id;
  document.getElementById('system-state').textContent = isLive ? 'RTSP CONNECTING' : 'VIDEO ANALYSIS RUNNING';
  const panel = document.getElementById('results');
  panel.hidden = false;
  panel.scrollIntoView({behavior: 'smooth', block: 'start'});
  document.getElementById('job-summary').textContent = `Job ${id.slice(0, 8)} · detector ${document.getElementById('model').value}`;
  document.getElementById('job-status').textContent = 'QUEUED';
  document.getElementById('stop-button').hidden = !isLive;
  document.getElementById('stop-button').disabled = false;
  document.getElementById('stop-button').textContent = 'Stop live analysis';
  if (pollTimer) clearInterval(pollTimer);
  pollJob(id);
  pollTimer = setInterval(() => pollJob(id), 1800);
}

async function pollJob(id) {
  try {
    const response = await fetch(`/api/jobs/${id}`);
    const job = await response.json();
    const status = document.getElementById('job-status');
    status.textContent = job.status.toUpperCase();
    if (job.status === 'queued' || job.status === 'running' || job.status === 'stopping') {
      document.getElementById('system-state').textContent = job.live ? (job.status === 'stopping' ? 'RTSP STOPPING' : job.status === 'running' && job.frames_processed ? 'RTSP STREAM ACTIVE' : 'RTSP CONNECTING') : `VIDEO ${job.status.toUpperCase()}`;
      document.getElementById('job-summary').textContent = job.status === 'queued' ? 'Queued locally. The analysis worker will start shortly…' : job.status === 'stopping' ? 'Stopping the camera stream…' : job.live ? `Live analysis active · ${job.frames_processed || 0} frames processed · event review updates as alerts appear` : 'Running detection, tracking, calibration and approach-risk screening…';
      if (job.status === 'stopping') document.getElementById('stop-button').disabled = true;
      if (job.status === 'running' && job.live) {
        document.getElementById('results-content').hidden = false;
        document.querySelector('.video-wrap').hidden = true;
        fetch(`/api/jobs/${id}/events`).then(response => response.json()).then(data => renderEvents(data.events || [])).catch(() => {});
      }
      return;
    }
    clearInterval(pollTimer);
    button.disabled = false;
    button.querySelector('span:nth-child(2)').textContent = 'Run another analysis';
    if (job.status === 'failed') {
      document.getElementById('system-state').textContent = 'INPUT ERROR';
      document.getElementById('job-summary').textContent = 'Analysis did not complete.';
      const error = document.getElementById('job-error');
      error.hidden = false;
      error.textContent = job.error || 'See the local terminal for details.';
      return;
    }
    if (job.status === 'cancelled') {
      document.getElementById('system-state').textContent = 'DEMO / UPLOAD MODE';
      document.getElementById('job-summary').textContent = 'Live analysis was stopped before it started.';
      return;
    }
    document.getElementById('stop-button').hidden = true;
    document.getElementById('system-state').textContent = `${job.source_mode === 'rtsp' ? 'RTSP' : 'VIDEO'} ANALYSIS COMPLETE`;
    document.getElementById('job-summary').textContent = `Completed · ${job.source_mode || 'unknown source'} · ${job.name} · ${job.frames_processed || 0} frames${job.warning ? ` · ${job.warning}` : ''} · manual review required`;
    document.getElementById('results-content').hidden = false;
    document.querySelector('.video-wrap').hidden = false;
    document.getElementById('job-error').hidden = true;
    const player = document.getElementById('result-video');
    player.src = `/api/jobs/${id}/video`;
    const eventResponse = await fetch(`/api/jobs/${id}/events`);
    const eventData = await eventResponse.json();
    renderEvents(eventData.events || []);
  } catch (_error) {
    document.getElementById('job-summary').textContent = 'Could not refresh the local job status.';
  }
}

function renderEvents(events) {
  const list = document.getElementById('event-list');
  document.getElementById('event-count').textContent = `${events.length} EVENT${events.length === 1 ? '' : 'S'}`;
  list.replaceChildren();
  if (!events.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-events';
    empty.textContent = 'No approach-risk events were logged for this clip.';
    list.append(empty);
    return;
  }
  [...events].reverse().forEach(event => {
    const encounter = event.encounter || {};
    const card = document.createElement('article');
    card.className = 'event-card';
    const title = document.createElement('div');
    title.className = 'event-title';
    const label = document.createElement('span');
    label.textContent = `${(encounter.risk || 'REVIEW').toUpperCase()} APPROACH`;
    const time = document.createElement('span');
    time.textContent = `${Number(event.timestamp_s || 0).toFixed(2)} s`;
    title.append(label, time);
    const details = document.createElement('div');
    details.className = 'event-details';
    const ttc = encounter.ttc_s == null ? 'not closing' : `${encounter.ttc_s} s`;
    details.textContent = `Tracks ${encounter.track_a} / ${encounter.track_b} · TTC ${ttc} · closest distance ${encounter.closest_distance_m} m`;
    const meta = document.createElement('div');
    meta.className = 'event-meta';
    meta.textContent = `FRAME ${event.frame} · ${String(event.event_id || '').slice(0, 12)}`;
    card.append(title, details, meta);
    list.append(card);
  });
}

document.getElementById('stop-button').addEventListener('click', async () => {
  if (!activeJobId) return;
  const stopButton = document.getElementById('stop-button');
  stopButton.disabled = true;
  stopButton.textContent = 'Stopping…';
  try {
    await fetch(`/api/jobs/${activeJobId}/stop`, {method: 'POST', headers: {'X-CSRF-Token': csrf}});
  } catch (_error) {
    stopButton.disabled = false;
    stopButton.textContent = 'Stop live analysis';
  }
});
