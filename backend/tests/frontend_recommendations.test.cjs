const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname,'../../demo/static/js/dashboard.js'),'utf8');
const helper = source.slice(source.indexOf('function overviewRecommendations('),source.indexOf('function renderMetrics('));

test('overview caps both inventories without reducing full backend results',()=>{
  const context=vm.createContext({OVERVIEW_RESULT_LIMIT:5,mapInventory:'properties',dashboard:{properties:[{id:'registry',lead_type:'registry_record'},...Array.from({length:12},(_,id)=>({id}))],locations:Array.from({length:24},(_,id)=>({id})),saved_locations:[{id:'saved'}]}});
  vm.runInContext(helper,context);
  assert.equal(vm.runInContext('overviewRecommendations().length',context),5);
  assert.equal(vm.runInContext('overviewRecommendations()[0].id',context),0);
  assert.equal(vm.runInContext('overviewRecommendations("areas").length',context),5);
  assert.equal(context.dashboard.properties.length,13);assert.equal(context.dashboard.locations.length,24);
});
test('empty or small inventories are not padded with invented recommendations',()=>{
  const context=vm.createContext({OVERVIEW_RESULT_LIMIT:5,mapInventory:'properties',dashboard:{locations:[{id:'only'}]}});
  vm.runInContext(helper,context);
  assert.equal(vm.runInContext('overviewRecommendations().length',context),0);
  assert.equal(vm.runInContext('overviewRecommendations("areas").length',context),1);
});
