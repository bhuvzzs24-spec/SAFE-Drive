/* Shared, dependency-free presentation rules. Also exercised by Node's test runner. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SafeDriveUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function number(value) {
    if (value == null || (typeof value === 'string' && !value.trim()) || !['number', 'string'].includes(typeof value)) return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  }
  function count(value) {
    const result = number(value);
    return result == null ? '—' : result.toLocaleString();
  }
  function measurement(value, suffix = '', digits = 1) {
    const result = number(value);
    return result == null ? 'Unavailable' : `${result.toFixed(digits)}${suffix}`;
  }
  function trackSpeed(track) {
    return track.speed_quality === 'calibrated_estimate' ? number(track.speed_kmh) : null;
  }
  function timestamp(value) {
    const result = number(value);
    if (result == null || result < 0) return 'Time unavailable';
    const rounded = Math.round(result * 100) / 100;
    const minutes = Math.floor(rounded / 60);
    return `${minutes}:${(rounded % 60).toFixed(2).padStart(5, '0')}`;
  }
  function trackIds(event) {
    return [...new Set([event.track_id, event.encounter?.track_a, event.encounter?.track_b,
      ...(event.tracks || []).map(track => track.id ?? track.track_id)]
      .filter(value => value != null).map(String))];
  }
  function severity(event) {
    if (event.event_type === 'speed_limit_exceeded') return 'speed';
    const value = event.encounter?.risk || event.risk?.level;
    return ['high', 'elevated', 'moderate', 'low'].includes(value) ? value : 'unknown';
  }
  function filterEvents(events, options = {}) {
    const query = (options.query || '').trim().toLowerCase();
    return events.filter(event => {
      const isSpeed = event.event_type === 'speed_limit_exceeded';
      if (options.type === 'speed_limit_exceeded' && !isSpeed) return false;
      if (options.type === 'risk' && event.event_type !== 'approach_risk_screen') return false;
      if (options.status && options.status !== 'all' && (event.review_status || 'pending') !== options.status) return false;
      if (options.severity && options.severity !== 'all' && severity(event) !== options.severity) return false;
      const text = [event.event_type, event.event_id, event.description, severity(event),
        event.reviewer, ...trackIds(event)].filter(Boolean).join(' ').toLowerCase();
      return !query || text.includes(query);
    }).sort((a, b) => (number(b.timestamp_s) ?? -1) - (number(a.timestamp_s) ?? -1));
  }
  function calibrationState(status) {
    if (status === 'calibrated') return {label: 'Calibrated estimates', tone: 'valid', detail: 'Server geometry checks passed. Field accuracy still needs independent validation.'};
    if (status === 'configured') return {label: 'Calibration supplied', tone: 'pending', detail: 'The analysis worker has not yet confirmed the road geometry.'};
    if (status === 'invalid') return {label: 'Invalid calibration', tone: 'error', detail: 'Detection may continue; metric speed is unavailable.'};
    return {label: 'Speed unavailable', tone: 'pending', detail: 'Supply measured camera calibration to calculate real-world speed.'};
  }
  function nonCollinear(points) {
    const [a, b] = points;
    return points.slice(2).some(c => Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) > 1e-8);
  }
  function validateCalibration(data) {
    if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error('Calibration must be a JSON object.');
    const image = data.image_points_px;
    const road = data.road_points_m;
    if (!Array.isArray(image) || !Array.isArray(road) || image.length < 4 || image.length !== road.length) {
      throw new Error('Provide at least four matching image_points_px and road_points_m pairs.');
    }
    if (image.length > 256) throw new Error('Use 256 or fewer measured reference pairs.');
    for (const [label, points] of [['Image', image], ['Road', road]]) {
      if (points.some(point => !Array.isArray(point) || point.length !== 2 || point.some(value => typeof value !== 'number' || !Number.isFinite(value)))) {
        throw new Error(`${label} points must be finite [x, y] numbers. Image units are pixels; road units are metres.`);
      }
      if (new Set(points.map(point => point.join(','))).size !== points.length) throw new Error(`${label} reference points must be distinct.`);
      if (!nonCollinear(points)) throw new Error(`${label} reference points cannot all lie on one line.`);
    }
    return {pairs: image.length, message: `${image.length} point pairs checked. The server validates the geometry when analysis starts.`};
  }
  function jobFailure(message) {
    const text = String(message || '');
    if (/analysis failed or exceeded|processing deadline/i.test(text)) return 'Analysis did not complete. The input, server configuration or processing deadline needs operator review.';
    if (/optional dependencies|no module named|requires.*dependencies/i.test(text)) return 'Video dependencies are unavailable. Install the project vision extra in the application environment.';
    if (/weights|model.*(not found|exist)|filenotfound/i.test(text)) return 'The detector could not load its weights. Check the configured local model file and compatible classes.';
    if (/camera|rtsp|stream/i.test(text)) return 'Camera analysis failed. Check the configured source, access, and codec.';
    if (/video|frame|source.*(end|open)/i.test(text)) return 'The video could not be processed. Check that the clip is readable and has a supported codec and valid frame rate.';
    return 'Analysis did not complete. Check the local server log for technical details, then retry with a supported input.';
  }
  async function requestJSON(url, options = {}, fetcher = globalThis.fetch) {
    let response;
    try { response = await fetcher(url, {...options, cache: 'no-store'}); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('Cannot reach the local SAFE-Drive server. Check that Flask is running and retry.');
    }
    let data = null;
    if ((response.headers.get('content-type') || '').includes('application/json')) {
      try { data = await response.json(); } catch (_) { /* handled below */ }
    }
    if (!response.ok) {
      const defaults = {403: 'Your session is no longer valid. Refresh the page before retrying.',
        404: 'This saved resource is unavailable on the server.', 413: 'The upload exceeds the server size limit.'};
      const safeMessage = typeof data?.error === 'string' && response.status < 500 ? data.error : null;
      const error = new Error(safeMessage || defaults[response.status] || `The server could not complete this request (HTTP ${response.status}).`);
      error.status = response.status;
      throw error;
    }
    if (data == null || typeof data !== 'object') throw new Error('The server returned an unreadable response. Refresh the page and retry.');
    return data;
  }
  function createSelectionScope() {
    let generation = 0;
    return {next: () => ++generation, current: token => token === generation};
  }
  return {number, count, measurement, trackSpeed, timestamp, trackIds, severity, filterEvents,
    calibrationState, validateCalibration, jobFailure, requestJSON, createSelectionScope};
});
