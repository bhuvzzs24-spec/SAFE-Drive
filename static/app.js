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
let activeEventsUrl = null;
let previewUrl = null;

document.querySelectorAll('.mode-option').forEach(option => option.addEventListener('click', () => {
  activeMode = option.dataset.mode;
  document.querySelectorAll('.mode-option').forEach(item => {
    const selected = item === option;
    item.classList.toggle('selected', selected);
    item.setAttribute('aria-selected', String(selected));
  });
  document.getElementById('file-source').hidden = activeMode !== 'file';
  document.getElementById('camera-source').hidden = activeMode !== 'camera';
  document.getElementById('source-preview').hidden = activeMode !== 'file' || !previewUrl;
  videoInput.disabled = activeMode !== 'file';
  document.getElementById('stream-url').disabled = activeMode !== 'camera';
  document.getElementById('duration').disabled = activeMode !== 'camera';
  document.getElementById('run-button').querySelector('span:nth-child(2)').textContent = activeMode === 'camera' ? 'Connect to live camera' : 'Run video analysis';
}));
document.querySelectorAll('.nav-item[data-mode]').forEach(item => item.addEventListener('click', () => {
  const cameraTab = document.querySelector('.mode-option[data-mode="camera"]');
  cameraTab.click();
  document.getElementById('analysis').scrollIntoView({behavior: 'smooth', block: 'start'});
}));

videoInput.addEventListener('change', () => {
  const file = videoInput.files[0];
  document.getElementById('video-name').textContent = file?.name || 'No video selected';
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = file ? URL.createObjectURL(file) : null;
  const preview = document.getElementById('source-preview');
  preview.src = previewUrl || '';
  preview.hidden = !previewUrl || activeMode !== 'file';
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
    loadSessions();
  } catch (error) {
    errorBox.textContent = error.message;
    button.disabled = false;
    button.querySelector('span:nth-child(2)').textContent = 'Run video analysis';
  }
});

function showJob(id, isLive) {
  activeJobId = id;
  activeEventsUrl = `/api/jobs/${id}/events`;
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
        document.querySelector('.video-comparison').hidden = true;
        renderTrackSummary(job.tracks);
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
    const calibrationText = job.calibration_message ? ` · ${job.calibration_message}` : '';
    document.getElementById('job-summary').textContent = `Completed · ${job.source_mode || 'unknown source'} · ${job.name} · ${job.frames_processed || 0} frames${job.warning ? ` · ${job.warning}` : ''}${calibrationText} · manual review required`;
    document.getElementById('results-content').hidden = false;
    document.querySelector('.video-comparison').hidden = false;
    document.querySelector('#original-result').parentElement.hidden = job.source_mode !== 'uploaded_video';
    document.getElementById('job-error').hidden = true;
    const player = document.getElementById('result-video');
    player.src = `/api/jobs/${id}/video`;
    if (job.source_mode === 'uploaded_video' && previewUrl) document.getElementById('original-result').src = previewUrl;
    renderTrackSummary(job.tracks);
    const eventResponse = await fetch(`/api/jobs/${id}/events`);
    const eventData = await eventResponse.json();
    renderEvents(eventData.events || []);
    loadSessions();
  } catch (_error) {
    document.getElementById('job-summary').textContent = 'Could not refresh the local job status.';
  }
}

function renderTrackSummary(summary) {
  const tracks = summary?.tracks || [];
  const tbody = document.getElementById('track-table');
  tbody.replaceChildren();
  document.getElementById('track-count').textContent = `${summary?.unique_track_ids || 0} unique track IDs · ${summary?.tracks_with_valid_speed || 0} with valid speed · ${summary?.tracks_without_valid_speed || 0} unavailable`;
  if (!tracks.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.className = 'empty-track';
    cell.textContent = 'No confirmed tracks observed yet.';
    row.append(cell);
    tbody.append(row);
    return;
  }
  [...tracks].sort((a, b) => String(a.track_id).localeCompare(String(b.track_id))).forEach(track => {
    const row = document.createElement('tr');
    const values = [track.track_id, track.vehicle_class,
      track.speed_kmh == null ? 'Unavailable' : `${Number(track.speed_kmh).toFixed(1)} km/h`,
      track.speed_quality || 'uncalibrated', String(track.observations || 0), track.active ? 'Active' : 'Completed'];
    values.forEach((value, index) => {
      const cell = document.createElement('td');
      cell.textContent = value;
      if (index === 0) cell.className = 'track-id';
      row.append(cell);
    });
    tbody.append(row);
  });
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
    const isSpeed = event.event_type === 'speed_limit_exceeded';
    const card = document.createElement('article');
    card.className = 'event-card';
    const title = document.createElement('div');
    title.className = 'event-title';
    const label = document.createElement('span');
    label.textContent = isSpeed ? 'SPEED LIMIT EXCEEDED · REVIEW' : `${(encounter.risk || 'REVIEW').toUpperCase()} APPROACH`;
    const time = document.createElement('span');
    time.textContent = `${Number(event.timestamp_s || 0).toFixed(2)} s`;
    title.append(label, time);
    const details = document.createElement('div');
    details.className = 'event-details';
    if (isSpeed) {
      details.textContent = `Track ${event.track_id} · ${event.speed_kmh} km/h · limit ${event.speed_limit_kmh} + ${event.tolerance_kmh} km/h tolerance · confirmed ${event.confirmed_duration_s} s`;
    } else {
      const ttc = encounter.ttc_s == null ? 'not closing' : `${encounter.ttc_s} s`;
      details.textContent = `Tracks ${encounter.track_a} / ${encounter.track_b} · TTC ${ttc} · closest distance ${encounter.closest_distance_m} m`;
    }
    const meta = document.createElement('div');
    meta.className = 'event-meta';
    const status = event.review_status || 'pending';
    meta.textContent = `FRAME ${event.frame ?? '—'} · ${status.toUpperCase()} · ${String(event.event_id || '').slice(0, 12)}`;
    card.append(title, details, meta);
    if (status === 'pending' && event.event_id) {
      const actions = document.createElement('div');
      actions.className = 'review-actions';
      [['verified', 'Verify'], ['rejected', 'Reject']].forEach(([decision, text]) => {
        const action = document.createElement('button');
        action.type = 'button';
        action.className = decision === 'verified' ? 'review-verify' : 'review-reject';
        action.textContent = text;
        action.addEventListener('click', () => reviewEvent(event.event_id, decision));
        actions.append(action);
      });
      card.append(actions);
    } else if (event.reviewer) {
      const reviewer = document.createElement('div');
      reviewer.className = 'event-meta';
      reviewer.textContent = `REVIEWED BY ${event.reviewer} · ${event.reviewed_at || ''}`;
      card.append(reviewer);
    }
    list.append(card);
  });
}

async function reviewEvent(eventId, decision) {
  const reviewer = document.getElementById('reviewer-name').value.trim();
  const feedback = document.getElementById('review-feedback');
  if (!reviewer) {
    feedback.textContent = 'Enter reviewer name or initials first.';
    return;
  }
  feedback.textContent = 'Saving review…';
  try {
    const response = await fetch(`/api/events/${eventId}/review`, {
      method: 'POST',
      headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'},
      body: JSON.stringify({decision, reviewer})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save review.');
    feedback.textContent = 'Review saved.';
    if (activeEventsUrl) {
      const eventResponse = await fetch(activeEventsUrl);
      const eventData = await eventResponse.json();
      renderEvents(eventData.events || []);
    }
  } catch (error) {
    feedback.textContent = error.message;
  }
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

document.getElementById('refresh-history').addEventListener('click', loadSessions);
loadSessions();

async function loadSessions() {
  const list = document.getElementById('history-list');
  try {
    const response = await fetch('/api/sessions');
    const data = await response.json();
    list.replaceChildren();
    if (!data.sessions?.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-events';
      empty.textContent = 'No saved analyses yet. Upload a clip or connect a camera to begin.';
      list.append(empty);
      return;
    }
    data.sessions.forEach(session => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'history-row';
      const name = document.createElement('span');
      name.className = 'history-name';
      name.textContent = session.input_name;
      const source = document.createElement('span');
      source.textContent = session.source_mode.replaceAll('_', ' ').toUpperCase();
      const status = document.createElement('span');
      status.className = 'history-status';
      status.textContent = session.status.toUpperCase();
      const date = document.createElement('span');
      date.textContent = new Date(session.started_at).toLocaleString();
      row.append(name, source, status, date);
      row.addEventListener('click', () => openSavedSession(session));
      list.append(row);
    });
  } catch (_error) {
    list.replaceChildren();
    const error = document.createElement('div');
    error.className = 'empty-events';
    error.textContent = 'Could not load saved analyses from SQLite.';
    list.append(error);
  }
}

async function openSavedSession(session) {
  activeJobId = session.session_id;
  activeEventsUrl = `/api/sessions/${session.session_id}/events`;
  const results = document.getElementById('results');
  results.hidden = false;
  results.scrollIntoView({behavior: 'smooth', block: 'start'});
  document.getElementById('job-status').textContent = session.status.toUpperCase();
  document.getElementById('job-summary').textContent = `${session.source_mode.replaceAll('_', ' ')} · ${session.input_name} · ${session.frames_processed} frames · calibration ${session.calibration_status}`;
  document.getElementById('system-state').textContent = 'SAVED SESSION REVIEW';
  document.getElementById('results-content').hidden = false;
  document.getElementById('video-comparison').hidden = session.status !== 'completed';
  document.getElementById('stop-button').hidden = true;
  const originalWrap = document.getElementById('original-result').parentElement;
  originalWrap.hidden = session.source_mode !== 'uploaded_video';
  document.getElementById('result-video').src = `/api/sessions/${session.session_id}/video`;
  if (session.source_mode === 'uploaded_video') {
    document.getElementById('original-result').src = `/api/sessions/${session.session_id}/original`;
  }
  try {
    const [trackResponse, eventResponse] = await Promise.all([
      fetch(`/api/sessions/${session.session_id}/tracks`),
      fetch(activeEventsUrl)
    ]);
    const tracks = (await trackResponse.json()).tracks || [];
    const events = (await eventResponse.json()).events || [];
    renderTrackSummary({tracks, unique_track_ids: tracks.length,
      tracks_with_valid_speed: tracks.filter(track => track.speed_kmh != null).length,
      tracks_without_valid_speed: tracks.filter(track => track.speed_kmh == null).length});
    renderEvents(events);
  } catch (_error) {
    document.getElementById('job-summary').textContent += ' · Could not retrieve saved details.';
  }
}
