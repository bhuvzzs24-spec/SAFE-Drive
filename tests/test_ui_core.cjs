const test = require('node:test');
const assert = require('node:assert/strict');
const UI = require('../static/ui-core.js');

test('product and workspace routes resolve safely without losing legacy deep links', () => {
  assert.equal(UI.pageForHash(''), 'home');
  assert.equal(UI.pageForHash('#home'), 'home');
  assert.equal(UI.pageForHash('#story-calibration'), 'home');
  assert.equal(UI.pageForHash('__proto__'), 'home');
  assert.equal(UI.pageForHash('constructor'), 'home');
  assert.equal(UI.pageForHash('unknown'), 'home');
  for (const page of ['overview','analysis','tracking','helmets','speed','events','analytics','cameras','settings']) {
    assert.equal(UI.pageForHash(`#${page}`), page);
  }
});

test('missing measurements never become zero while real zero stays visible', () => {
  for (const value of [null, undefined, '', '  ', false, [], {}, NaN, Infinity]) {
    assert.equal(UI.number(value), null);
    assert.equal(UI.measurement(value, ' km/h'), 'Unavailable');
  }
  assert.equal(UI.measurement(0, ' km/h'), '0.0 km/h');
  assert.equal(UI.count(null), '—');
  assert.equal(UI.count(0), '0');
  assert.equal(UI.timestamp(0), '0:00.00');
  assert.equal(UI.timestamp(62.25), '1:02.25');
  assert.equal(UI.timestamp(59.999), '1:00.00');
  assert.equal(UI.timestamp(null), 'Time unavailable');
  assert.equal(UI.trackSpeed({speed_kmh: 45, speed_quality: 'uncalibrated'}), null);
  assert.equal(UI.trackSpeed({speed_kmh: 45, speed_quality: 'calibrated_estimate'}), 45);
});

const fixture = [
  {event_id:'risk-a',event_type:'approach_risk_screen',timestamp_s:2,encounter:{track_a:'ped-4',track_b:'car-8',risk:'high'},review_status:'pending'},
  {event_id:'speed-b',event_type:'speed_limit_exceeded',timestamp_s:4,track_id:'car-9',review_status:'verified',reviewer:'Reviewer B'},
  {event_id:'risk-c',event_type:'approach_risk_screen',timestamp_s:3,encounter:{track_a:'car-8',track_b:'car-9',risk:'elevated'},review_status:'rejected'},
];
test('event filters combine actual type, review state, severity and related track IDs', () => {
  assert.deepEqual(UI.filterEvents(fixture).map(e => e.event_id), ['speed-b','risk-c','risk-a']);
  assert.deepEqual(UI.filterEvents(fixture,{query:'ped-4',type:'risk',status:'pending',severity:'high'}).map(e => e.event_id), ['risk-a']);
  assert.deepEqual(UI.filterEvents(fixture,{query:'Reviewer B',status:'verified'}).map(e => e.event_id), ['speed-b']);
  assert.equal(UI.filterEvents(fixture,{type:'risk',severity:'speed'}).length, 0);
  assert.deepEqual(UI.trackIds({track_id:'4',encounter:{track_a:'4',track_b:'7'},tracks:[{id:'7'}]}), ['4','7']);
});

const valid = {image_points_px:[[0,0],[100,0],[100,100],[0,100]],road_points_m:[[0,0],[10,0],[10,20],[0,20]]};
test('calibration structure checks require measured finite, distinct, non-collinear pairs', () => {
  assert.equal(UI.validateCalibration(valid).pairs, 4);
  assert.match(UI.validateCalibration(valid).message, /server validates the geometry/);
  assert.throws(() => UI.validateCalibration([]), /JSON object/);
  assert.throws(() => UI.validateCalibration({...valid,road_points_m:[[0,0]]}), /matching/);
  assert.throws(() => UI.validateCalibration({...valid,image_points_px:[[null,0],[1,0],[1,1],[0,1]]}), /finite/);
  assert.throws(() => UI.validateCalibration({...valid,image_points_px:[[0,0],[0,0],[1,1],[0,1]]}), /distinct/);
  assert.throws(() => UI.validateCalibration({...valid,road_points_m:[[0,0],[1,1],[2,2],[3,3]]}), /one line/);
});
test('supplied calibration is distinguished from server-checked geometry', () => {
  assert.equal(UI.calibrationState('configured').tone, 'pending');
  assert.equal(UI.calibrationState('calibrated').tone, 'valid');
  assert.match(UI.calibrationState('calibrated').detail, /independent validation/);
  assert.match(UI.calibrationState('missing').label, /unavailable/);
  assert.equal(UI.calibrationState('invalid').tone, 'error');
});

function response(status, type, data) {
  return {ok:status < 400,status,headers:{get:() => type},json:async() => data};
}
test('HTTP failures surface usable messages without displaying an HTML error page', async () => {
  await assert.rejects(UI.requestJSON('/test',{},async()=>response(500,'text/html','<traceback>')), /HTTP 500/);
  await assert.rejects(UI.requestJSON('/test',{},async()=>response(403,'text/html','')), /Refresh the page/);
  await assert.rejects(UI.requestJSON('/test',{},async()=>response(413,'text/html','')), /size limit/);
  await assert.rejects(UI.requestJSON('/test',{},async()=>response(400,'application/json',{error:'Choose a valid video.'})), /Choose a valid video/);
  await assert.rejects(UI.requestJSON('/test',{},async()=>response(200,'text/html','')), /unreadable/);
  assert.deepEqual(await UI.requestJSON('/test',{},async()=>response(200,'application/json',{sessions:[]})), {sessions:[]});
});
test('network errors are clear and aborts remain distinguishable', async () => {
  await assert.rejects(UI.requestJSON('/test',{},async()=>{throw new TypeError('network')}), /Check that Flask is running/);
  const aborted = Object.assign(new Error('cancelled'), {name:'AbortError'});
  await assert.rejects(UI.requestJSON('/test',{},async()=>{throw aborted}), error=>error.name==='AbortError');
});
test('a late result cannot overwrite a newly selected session', async () => {
  const scope = UI.createSelectionScope();
  let shown = null, resolveOld;
  const oldToken = scope.next();
  const oldRequest = new Promise(resolve=>{resolveOld=resolve}).then(value=>{if(scope.current(oldToken))shown=value});
  const newToken = scope.next();
  if (scope.current(newToken)) shown='new session';
  resolveOld('old session'); await oldRequest;
  assert.equal(shown, 'new session');
});
test('job failures explain missing assets without exposing private paths', () => {
  assert.match(UI.jobFailure('Analysis failed or exceeded its processing deadline. Check the video, configured weights and calibration.'), /operator review/);
  const message = UI.jobFailure('FileNotFoundError: /Users/private/models/weights.pt');
  assert.match(message, /weights/);
  assert.doesNotMatch(message, /Users/);
  assert.match(UI.jobFailure('ImportError: Video mode needs optional dependencies'), /vision extra/);
});

test('helmet review filters preserve rider and motorcycle references without treating review as risk', () => {
  const saved=[{event_id:'helmet-1',event_type:'helmet_review',track_id:'rider-1',motorcycle_track_id:'bike-2',helmet_class:'half_face_helmet',review_status:'pending',timestamp_s:1},...fixture];
  assert.equal(UI.filterEvents(saved,{type:'helmet_review',query:'bike-2'}).length,1);
  assert.equal(UI.filterEvents(saved,{type:'helmet_review',query:'half_face_helmet'}).length,1);
  assert.equal(UI.filterEvents(saved,{type:'risk'}).some(e=>e.event_type==='helmet_review'),false);
  assert.match(UI.jobFailure('Helmet weights are missing'),/helmet detector/);
});
