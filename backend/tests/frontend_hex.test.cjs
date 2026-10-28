const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const dashboard = fs.readFileSync(path.resolve(__dirname, '../../demo/static/js/dashboard.js'), 'utf8');
const functions = dashboard.slice(dashboard.indexOf('function clearHexLayer()'), dashboard.indexOf('function setMapViewStatus('));

function environment(fetch, layer = 'concept_demand') {
  const sources = new Map(), layers = new Map(), status = {hidden: true};
  const context = vm.createContext({URL, URLSearchParams, Map, fetch, installNycBoundary: () => {},
    window: {location: {origin: 'https://groundwork.example'}, GROUNDWORK_SPATIAL_BACKEND: true},
    document: {querySelector: () => status},
    locationMap: {
      getStyle: () => ({layers: []}), getZoom: () => 12,
      getLayer: id => layers.get(id), getSource: id => sources.get(id),
      removeLayer: id => layers.delete(id), removeSource: id => sources.delete(id),
      addLayer: definition => layers.set(definition.id, definition),
      addSource: (id, definition) => sources.set(id, definition),
    },
    dashboard: {meta: {data_release: 'test_release'}},
    conceptParams: () => new URLSearchParams({cuisine: 'korean'}),
  });
  vm.runInContext(`let activeLayer = ${JSON.stringify(layer)}; let activeHeatMetric = ''; let activeBasemap = 'aerial'; let hoveredHexId = null; let hexRequestId = 0; const hexCache = new Map(); ${functions}`, context);
  return {context, sources, layers, status};
}

const manifest = {data_release: 'test_release', source_layer: 'demand', tiles: {'8': '/api/v1/tiles/release/huff/8/{z}/{x}/{y}.mvt'}};

test('published concept uses vector tiles with the correct MVT source layer', async () => {
  const calls = [];
  const env = environment(async url => {calls.push(url); return {ok: true, json: async () => manifest};});
  await vm.runInContext('showHexLayer()', env.context);
  assert.equal(calls.length, 1);
  assert.equal(env.sources.get('concept-hexes').type, 'vector');
  assert.equal(env.sources.get('concept-hexes').tiles[0], 'https://groundwork.example/api/v1/tiles/release/huff/8/{z}/{x}/{y}.mvt');
  assert.equal(env.layers.get('concept-hex-fill')['source-layer'], 'demand');
});

test('missing precomputed concept retains the existing GeoJSON map contract', async () => {
  const calls = [];
  const geojson = {type: 'FeatureCollection', features: []};
  const env = environment(async url => {calls.push(url); return {ok: url.includes('/api/hex-demand?'), json: async () => geojson};});
  await vm.runInContext('showHexLayer()', env.context);
  assert.equal(calls.length, 2);
  assert.equal(env.sources.get('concept-hexes').type, 'geojson');
  assert.equal(env.sources.get('concept-hexes').data, geojson);
});

test('outdated concept tiles fall back to the current GeoJSON surface', async () => {
  const calls = [];
  const geojson = {type: 'FeatureCollection', features: []};
  const env = environment(async url => {
    calls.push(url);
    return {ok: true, json: async () => url.includes('/api/hex-demand?') ? geojson : {...manifest, data_release: 'old_release'}};
  });
  await vm.runInContext('showHexLayer()', env.context);
  assert.equal(calls.length, 2);
  assert.equal(env.sources.get('concept-hexes').type, 'geojson');
});

test('provenance rejection falls back to current GeoJSON', async () => {
  const calls = [];
  const env = environment(async url => {
    calls.push(url);
    return {ok: url.includes('/api/hex-demand?'), status: url.includes('/api/hex-demand?') ? 200 : 409,
      json: async () => ({type: 'FeatureCollection', features: []})};
  });
  await vm.runInContext('showHexLayer()', env.context);
  assert.equal(calls.length, 2);
  assert.equal(env.sources.get('concept-hexes').type, 'geojson');
});

test('a feature with no coverage reports absence rather than a colored zero', async () => {
  const env = environment(async url => ({ok: url.includes('/api/hex-demand?'), json: async () => ({type:'FeatureCollection',features:[],meta:{status:'no_feature_coverage'}})}));
  await vm.runInContext('showHexLayer()', env.context);
  assert.equal(env.status.hidden, false);
  assert.match(env.status.textContent, /No Recorded Coverage/);
  assert.equal(env.sources.get('concept-hexes').data.features.length, 0);
});

test('assessment basis distinguishes limited evidence without inventing cuisine fit', () => {
  const basis = dashboard.slice(dashboard.indexOf('function assessmentBasis('), dashboard.indexOf('function renderIntel('));
  const context = vm.createContext({});
  vm.runInContext(basis, context);
  for (const [mode, expected] of [
    ['cuisine_supply_supported', 'Cuisine-Supported Fit'],
    ['pooled_cuisine_supply', 'Limited Cuisine Evidence'],
    ['related_supply_context_only', 'General Location Fit'],
    ['general_concept_suitability', 'General Location Fit'],
  ]) {
    assert.equal(vm.runInContext(`assessmentBasis({assessment_policy:{cuisine_mode:${JSON.stringify(mode)}}})`, context), expected);
  }
  assert.equal(vm.runInContext('assessmentBasis({assessment_policy:{recommendation_eligible:false}})', context), 'Insufficient Evidence');
});

test('cost-based menu pricing validates targets and rounds up without inventing costs', () => {
  const source = dashboard.slice(dashboard.indexOf('function targetMenuPrice('), dashboard.indexOf('document.querySelector("#menuApplyPricing").addEventListener'));
  const context = vm.createContext({});
  vm.runInContext(source, context);
  assert.equal(vm.runInContext('targetMenuPrice(4,30)', context), 13.5);
  assert.equal(vm.runInContext('targetMenuPrice(12,30)', context), 40);
  for (const expression of ['targetMenuPrice("",30)', 'targetMenuPrice(-1,30)', 'targetMenuPrice(10,0)', 'targetMenuPrice(10,NaN)', 'targetMenuPrice(1000,10)']) {
    assert.equal(vm.runInContext(expression, context), null);
  }
});

test('unavailable Huff scenario reports absence without showing screening results as Huff', async () => {
  const calls = [];
  const env = environment(async url => {calls.push(url); return {ok: false};}, 'huff_demand');
  await vm.runInContext('showHexLayer()', env.context);
  assert.equal(calls.length, 1);
  assert.equal(env.sources.size, 0);
  assert.match(env.status.textContent, /Huff/);
});

test('late response cannot overwrite the layer selected after its request', async () => {
  let release;
  const pending = new Promise(resolve => {release = resolve;});
  const env = environment(async () => {await pending; return {ok: true, json: async () => manifest};});
  const request = vm.runInContext('showHexLayer()', env.context);
  vm.runInContext("activeLayer = 'opportunity'", env.context);
  release();
  await request;
  assert.equal(env.sources.size, 0);
});
