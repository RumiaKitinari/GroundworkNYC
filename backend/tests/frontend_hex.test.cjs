const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const dashboard = fs.readFileSync(path.resolve(__dirname, '../../demo/static/js/dashboard.js'), 'utf8');
const functions = dashboard.slice(dashboard.indexOf('function clearHexLayer()'), dashboard.indexOf('function setMapViewStatus('));

function environment(fetch, layer = 'concept_demand') {
  const sources = new Map(), layers = new Map(), status = {hidden: true};
  const context = vm.createContext({URL, URLSearchParams, Map, fetch,
    window: {location: {origin: 'https://groundwork.example'}},
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
  vm.runInContext(`let activeLayer = ${JSON.stringify(layer)}; let activeBasemap = 'aerial'; let hoveredHexId = null; let hexRequestId = 0; const hexCache = new Map(); ${functions}`, context);
  return {context, sources, layers, status};
}

const manifest = {source_layer: 'demand', tiles: {'8': '/api/v1/tiles/release/huff/8/{z}/{x}/{y}.mvt'}};

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
