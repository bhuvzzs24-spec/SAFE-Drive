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
let currentEvents = [];
let currentTracks = [];

const PAGE_TITLES = {
  overview: 'Overview', analysis: 'Video Analysis', tracking: 'Vehicle Tracking',
  helmets: 'Helmet Compliance', speed: 'Speed Violations', events: 'Event Review',
  analytics: 'Analytics', cameras: 'Camera Management', settings: 'Settings'
};

function navigatePage(page, updateHash = true) {
  if (!PAGE_TITLES[page]) page = 'overview';
  document.querySelectorAll('.page-view').forEach(view => {
    view.hidden = view.dataset.page !== page;
  });
  document.querySelectorAll('[data-page-link]').forEach(item => {
    item.classList.toggle('active', item.dataset.pageLink === page);
  });
  document.getElementById('current-page-title').textContent = PAGE_TITLES[page];
  if (updateHash && location.hash !== `#${page}`) history.replaceState(null, '', `#${page}`);
  if (page === 'events') renderEvents(currentEvents);
  if (page === 'speed') renderSpeedEvents(currentEvents);
}

function pageFromHash() {
  return (location.hash || '#overview').slice(1);
}

document.querySelectorAll('[data-page-link]').forEach(item => item.addEventListener('click', () => {
  navigatePage(item.dataset.pageLink);
}));
document.querySelectorAll('[data-open-page]').forEach(item => item.addEventListener('click', () => {
  navigatePage(item.dataset.openPage);
}));
document.querySelectorAll('[data-action="open-camera"]').forEach(item => item.addEventListener('click', () => {
  navigatePage('analysis');
  document.querySelector('.mode-option[data-mode="camera"]').click();
}));
window.addEventListener('hashchange', () => navigatePage(pageFromHash(), false));
navigatePage(pageFromHash(), false);

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
  document.getElementById('video-empty-state').hidden = activeMode === 'file' && Boolean(previewUrl);
  videoInput.disabled = activeMode !== 'file';
  document.getElementById('stream-url').disabled = activeMode !== 'camera';
  document.getElementById('duration').disabled = activeMode !== 'camera';
  document.getElementById('header-mode').textContent = activeMode === 'camera' ? 'Live camera session' : 'Recorded video analysis';
  document.getElementById('viewer-caption').textContent = activeMode === 'camera' ? 'Connect a configured RTSP/RTSPS source' : 'Your video appears here when selected';
  document.getElementById('viewer-mode-badge').textContent = activeMode === 'camera' ? 'CAMERA' : 'READY';
  button.querySelector('span').textContent = activeMode === 'camera' ? 'Connect to live camera' : 'Start video analysis';
}));
document.getElementById('empty-select-video').addEventListener('click', () => {
  navigatePage('analysis');
  document.querySelector('.mode-option[data-mode="file"]').click();
  videoInput.click();
});

videoInput.addEventListener('change', () => {
  const file = videoInput.files[0];
  document.getElementById('video-name').textContent = file?.name || 'No video selected';
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = file ? URL.createObjectURL(file) : null;
  const preview = document.getElementById('source-preview');
  preview.src = previewUrl || '';
  preview.hidden = !previewUrl || activeMode !== 'file';
  document.getElementById('video-empty-state').hidden = Boolean(previewUrl) && activeMode === 'file';
  document.getElementById('viewer-caption').textContent = file ? file.name : 'Your video appears here when selected';
  document.getElementById('viewer-mode-badge').textContent = file ? 'INPUT PREVIEW' : 'READY';
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
  navigatePage('analysis');
  errorBox.textContent = '';
  button.disabled = true;
  button.querySelector('span').textContent = activeMode === 'camera' ? 'Connecting…' : 'Uploading…';
  const data = new FormData(form);
  try {
    const endpoint = activeMode === 'camera' ? '/api/camera-jobs' : '/api/jobs';
    button.querySelector('span').textContent = activeMode === 'camera' ? 'Connecting to camera…' : 'Uploading video…';
    const response = await fetch(endpoint, {method: 'POST', headers: {'X-CSRF-Token': csrf}, body: data});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not start analysis.');
    showJob(result.id, activeMode === 'camera');
    loadSessions();
  } catch (error) {
    errorBox.textContent = error.message;
    button.disabled = false;
    button.querySelector('span').textContent = activeMode === 'camera' ? 'Connect to live camera' : 'Start video analysis';
  }
});

function showJob(id, isLive) {
  navigatePage('analysis');
  activeJobId = id;
  activeEventsUrl = `/api/jobs/${id}/events`;
  document.getElementById('system-state').textContent = isLive ? 'RTSP CONNECTING' : 'VIDEO ANALYSIS RUNNING';
  const panel = document.getElementById('results');
  panel.hidden = false;
  document.getElementById('results-content').hidden = true;
  document.getElementById('job-error').hidden = true;
  document.getElementById('video-stage').hidden = false;
  panel.scrollIntoView({behavior: 'smooth', block: 'start'});
  document.getElementById('job-summary').textContent = `Job ${id.slice(0, 8)} · detector ${document.getElementById('model').value}`;
  document.getElementById('job-status').textContent = 'QUEUED';
  document.getElementById('viewer-mode-badge').textContent = isLive ? 'CONNECTING' : 'PROCESSING';
  document.getElementById('viewer-frame-label').textContent = 'Analysis is running; annotated output appears when available';
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
  button.querySelector('span').textContent = 'Start another analysis';
    if (job.status === 'failed') {
      document.getElementById('system-state').textContent = 'INPUT ERROR';
      document.getElementById('viewer-mode-badge').textContent = 'FAILED';
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
    document.getElementById('video-stage').hidden = true;
    document.getElementById('system-state').textContent = `${job.source_mode === 'rtsp' ? 'RTSP' : 'VIDEO'} ANALYSIS COMPLETE`;
    document.getElementById('viewer-mode-badge').textContent = 'COMPLETE';
    document.getElementById('viewer-frame-label').textContent = `${job.frames_processed || 0} frames processed`;
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
    document.getElementById('result-track-summary').textContent = `${job.tracks?.unique_track_ids || 0} tracks · ${job.tracks?.tracks_with_valid_speed || 0} valid speeds · ${job.tracks?.tracks_without_valid_speed || 0} unavailable`;
    const eventResponse = await fetch(`/api/jobs/${id}/events`);
    const eventData = await eventResponse.json();
    renderEvents(eventData.events || []);
    loadSessions();
    document.getElementById('results').scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (_error) {
    document.getElementById('job-summary').textContent = 'Could not refresh the local job status.';
  }
}

function renderTrackSummary(summary) {
  const tracks = summary?.tracks || [];
  currentTracks = tracks;
  const tbody = document.getElementById('track-table');
  tbody.replaceChildren();
  document.getElementById('track-count').textContent = `${summary?.unique_track_ids || 0} tracks · ${summary?.tracks_with_valid_speed || 0} valid speeds · ${summary?.tracks_without_valid_speed || 0} unavailable`;
  document.getElementById('tracking-session-name').textContent = activeJobId ? `Session ${activeJobId.slice(0, 8)}` : 'Current analysis';
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
    row.addEventListener('click', () => selectTrack(track, row));
    tbody.append(row);
  });
  applyTrackFilter();
}

function selectTrack(track, row) {
  document.querySelectorAll('#track-table tr').forEach(item => item.classList.remove('selected-track'));
  row.classList.add('selected-track');
  const detail = document.getElementById('track-detail');
  detail.replaceChildren();
  const text = document.createElement('span');
  const speed = track.speed_kmh == null ? 'Speed unavailable' : `${Number(track.speed_kmh).toFixed(1)} km/h (${track.speed_quality})`;
  text.innerHTML = `<strong>Track ${escapeHtml(track.track_id)} · ${escapeHtml(track.vehicle_class)}</strong> · ${escapeHtml(speed)} · ${Number(track.observations || 0)} observations · seen ${Number(track.first_seen_s || 0).toFixed(2)}–${Number(track.last_seen_s || 0).toFixed(2)} s`;
  detail.append(text);
  const related = currentEvents.filter(event => String(event.track_id) === String(track.track_id) ||
    (event.tracks || []).some(item => String(item.id) === String(track.track_id)) ||
    [event.encounter?.track_a, event.encounter?.track_b].includes(String(track.track_id)));
  if (related.length) {
    const tags = document.createElement('div');
    tags.className = 'track-events';
    related.forEach(event => {
      const tag = document.createElement('span');
      tag.className = 'track-event-tag';
      tag.textContent = `${event.event_type.replaceAll('_', ' ')} · ${Number(event.timestamp_s || 0).toFixed(1)} s`;
      tags.append(tag);
    });
    detail.append(tags);
  }
  navigatePage('tracking');
}

function escapeHtml(value) {
  const node = document.createElement('span');
  node.textContent = String(value);
  return node.innerHTML;
}

function eventCard(event, allowReview = true) {
  const encounter = event.encounter || {};
  const isSpeed = event.event_type === 'speed_limit_exceeded';
  const card = document.createElement('article');
  card.className = 'event-card';
  const title = document.createElement('div');
  title.className = 'event-title';
  const label = document.createElement('span');
  label.textContent = isSpeed ? 'Speed limit exceeded · review' : `${(encounter.risk || event.event_type || 'Safety event').replaceAll('_', ' ')} · review`;
  const time = document.createElement('span');
  time.textContent = `${Number(event.timestamp_s || 0).toFixed(2)} s`;
  title.append(label, time);
  const details = document.createElement('div');
  details.className = 'event-details';
  if (isSpeed) {
    details.textContent = `Track ${event.track_id} · ${event.speed_kmh} km/h · limit ${event.speed_limit_kmh} + ${event.tolerance_kmh} km/h · sustained ${event.confirmed_duration_s} s`;
  } else if (encounter.track_a || encounter.track_b) {
    details.textContent = `Tracks ${encounter.track_a} / ${encounter.track_b} · TTC ${encounter.ttc_s == null ? 'not closing' : `${encounter.ttc_s} s`} · closest approach ${encounter.closest_distance_m} m`;
  } else {
    details.textContent = event.description || 'Screening signal from the analysis pipeline; review the associated footage.';
  }
  const meta = document.createElement('div');
  meta.className = 'event-meta';
  const status = event.review_status || 'pending';
  meta.textContent = `Frame ${event.frame ?? '—'} · ${status} · ${String(event.event_id || '').slice(0, 12)}`;
  card.append(title, details, meta);
  if (allowReview && status === 'pending' && event.event_id) {
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
    reviewer.textContent = `Reviewed by ${event.reviewer} · ${event.reviewed_at || ''}`;
    card.append(reviewer);
  }
  return card;
}

function renderEvents(events) {
  currentEvents = events;
  const list = document.getElementById('event-list');
  const pending = events.filter(event => (event.review_status || 'pending') === 'pending').length;
  document.getElementById('pending-nav-state').textContent = pending ? `${pending} to review` : `${events.length} saved`;
  list.replaceChildren();
  if (!events.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'No reviewable events are saved for this session.';
    list.append(empty);
  } else events.slice().reverse().forEach(event => list.append(eventCard(event)));
  renderSpeedEvents(events);
  renderTimeline(events);
}

function renderTimeline(events) {
  const timeline = document.getElementById('event-timeline');
  const player = document.getElementById('result-video');
  const eventList = events.filter(event => Number.isFinite(Number(event.timestamp_s)));
  timeline.replaceChildren();
  if (!eventList.length) {
    const empty = document.createElement('div');
    empty.className = 'timeline-empty';
    empty.textContent = 'No event markers for this session.';
    timeline.append(empty);
    return;
  }
  const duration = Number(player.duration);
  if (!Number.isFinite(duration) || duration <= 0) {
    const empty = document.createElement('div');
    empty.className = 'timeline-empty';
    empty.textContent = 'Event timestamps are saved; load the annotated video to position markers.';
    timeline.append(empty);
    return;
  }
  eventList.forEach(event => {
    const marker = document.createElement('button');
    marker.type = 'button';
    marker.className = `timeline-marker ${event.event_type === 'speed_limit_exceeded' ? 'speed' : ''}`;
    const timestamp = Number(event.timestamp_s);
    marker.style.left = `${Math.max(0, Math.min(100, timestamp / duration * 100))}%`;
    marker.title = `${event.event_type.replaceAll('_', ' ')} · ${timestamp.toFixed(2)} s`;
    marker.setAttribute('aria-label', marker.title);
    marker.addEventListener('click', () => {
      player.currentTime = Math.max(0, Math.min(duration, timestamp));
      player.play().catch(() => {});
    });
    timeline.append(marker);
  });
}

document.getElementById('result-video').addEventListener('loadedmetadata', () => renderTimeline(currentEvents));

function renderSpeedEvents(events) {
  const list = document.getElementById('speed-event-list');
  const speedEvents = events.filter(event => event.event_type === 'speed_limit_exceeded');
  document.getElementById('speed-event-count').textContent = `${speedEvents.length} ${speedEvents.length === 1 ? 'event' : 'events'}`;
  list.replaceChildren();
  if (!speedEvents.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'No confirmed speed-rule events are saved for this session.';
    list.append(empty);
    return;
  }
  speedEvents.slice().reverse().forEach(event => list.append(eventCard(event, false)));
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
    feedback.textContent = 'Review saved to the local event record.';
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
document.getElementById('track-filter').addEventListener('input', applyTrackFilter);
loadSessions();

function applyTrackFilter() {
  const query = document.getElementById('track-filter').value.trim().toLowerCase();
  document.querySelectorAll('#track-table tr').forEach(row => {
    row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
  });
}

async function loadSessions() {
  const list = document.getElementById('history-list');
  try {
    const [response, analyticsResponse] = await Promise.all([
      fetch('/api/sessions'), fetch('/api/analytics')
    ]);
    const data = await response.json();
    const analytics = await analyticsResponse.json();
    updateAnalytics(analytics);
    list.replaceChildren();
    if (!data.sessions?.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-inline';
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
      source.textContent = session.source_mode.replaceAll('_', ' ');
      const status = document.createElement('span');
      status.className = `history-status ${session.status}`;
      status.textContent = session.status;
      const date = document.createElement('span');
      date.textContent = new Date(session.started_at).toLocaleString();
      row.append(name, source, status, date);
      row.addEventListener('click', () => openSavedSession(session));
      list.append(row);
    });
  } catch (_error) {
    list.replaceChildren();
    const error = document.createElement('div');
    error.className = 'empty-inline';
    error.textContent = 'Could not load saved analyses from SQLite.';
    list.append(error);
  }
}

function updateAnalytics(data) {
  const value = (key) => Number(data?.[key] || 0).toLocaleString();
  document.getElementById('overview-session-count').textContent = value('sessions');
  document.getElementById('overview-track-count').textContent = value('vehicle_tracks');
  document.getElementById('overview-pending-count').textContent = value('pending_events');
  document.getElementById('overview-calibrated-count').textContent = value('tracks_with_valid_speed');
  document.getElementById('analytics-sessions').textContent = value('sessions');
  document.getElementById('analytics-frames').textContent = value('frames_processed');
  document.getElementById('analytics-tracks').textContent = value('vehicle_tracks');
  document.getElementById('analytics-reviewed').textContent = value('reviewed_events');
  const chart = document.getElementById('analytics-chart');
  chart.replaceChildren();
  const activity = data?.activity || [];
  if (!activity.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = 'No completed sessions have been recorded yet.';
    chart.append(empty);
    return;
  }
  const bars = document.createElement('div');
  bars.className = 'chart-bars';
  const max = Math.max(...activity.map(day => day.sessions), 1);
  activity.forEach(day => {
    const bar = document.createElement('div');
    bar.className = 'chart-bar';
    bar.style.height = `${Math.max(12, day.sessions / max * 100)}%`;
    bar.title = `${day.day}: ${day.sessions} sessions`;
    const label = document.createElement('span');
    label.textContent = `${day.day.slice(5)} · ${day.sessions}`;
    bar.append(label);
    bars.append(bar);
  });
  chart.append(bars);
}

async function openSavedSession(session) {
  navigatePage('analysis');
  activeJobId = session.session_id;
  activeEventsUrl = `/api/sessions/${session.session_id}/events`;
  const results = document.getElementById('results');
  results.hidden = false;
  results.scrollIntoView({behavior: 'smooth', block: 'start'});
  document.getElementById('job-status').textContent = session.status.toUpperCase();
  document.getElementById('job-summary').textContent = `${session.source_mode.replaceAll('_', ' ')} · ${session.input_name} · ${session.frames_processed} frames · calibration ${session.calibration_status}`;
  document.getElementById('viewer-mode-badge').textContent = session.status.toUpperCase();
  document.getElementById('viewer-caption').textContent = session.input_name;
  document.getElementById('viewer-frame-label').textContent = `${session.frames_processed || 0} processed frames`;
  document.getElementById('system-state').textContent = 'SAVED SESSION REVIEW';
  document.getElementById('results-content').hidden = false;
  document.getElementById('video-stage').hidden = session.status === 'completed';
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
