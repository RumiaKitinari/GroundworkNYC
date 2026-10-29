const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../demo/static/js/planning.js'), 'utf8');

function environment() {
  const context = vm.createContext({});
  vm.runInContext(source, context);
  return context;
}

test('workspace reconciliation retains remote-only edits without resurrecting local deletions', () => {
  const context=environment();
  context.base={plans:{cafe:{scenarios:{Expected:{price:35},Old:{price:20}},property_ids:['a','b']}}};
  context.remote={plans:{cafe:{scenarios:{Expected:{price:40},Old:{price:20}},property_ids:['a','b']}}};
  context.local={plans:{cafe:{scenarios:{Expected:{price:35}},property_ids:['b']}}};
  const result=JSON.parse(JSON.stringify(vm.runInContext('reconcileWorkspace(base,remote,local)',context)));
  assert.deepEqual(result,{plans:{cafe:{scenarios:{Expected:{price:40}},property_ids:['b']}}});
});

test('same-field conflicts preserve this editor while independent remote fields survive', () => {
  const context=environment();context.base={profile:{company:'Old',display_name:'Chef'}};
  context.remote={profile:{company:'Remote',display_name:'New Name'}};
  context.local={profile:{company:'Local',display_name:'Chef'}};
  const result=JSON.parse(JSON.stringify(vm.runInContext('reconcileWorkspace(base,remote,local)',context)));
  assert.deepEqual(result,{profile:{company:'Local',display_name:'New Name'}});
});

test('lease and purchase financial plans have separate keys', () => {
  const context=environment();context.menuKey=()=> 'groundwork-menu-v2:["chef","Cafe","any","coffee","none"]';context.state={dealType:'lease'};
  const lease=vm.runInContext('planKey()',context);context.state.dealType='purchase';
  assert.notEqual(vm.runInContext('planKey()',context),lease);
});

test('a guest basket requires every selected dish to be priced and costed separately', () => {
  const context=environment();context.syncSavedMenu=()=>{};
  context.savedMenu=[{id:'main',price:'25',cost:'8'},{id:'drink',price:'',cost:''}];
  context.plan={basket:{main:1,drink:1}};
  let result=vm.runInContext('basketSummary(plan)',context);
  assert.equal(result.priced,false);assert.equal(result.costed,false);
  context.savedMenu[1].price='5';result=vm.runInContext('basketSummary(plan)',context);
  assert.equal(result.priced,true);assert.equal(result.price,30);assert.equal(result.costed,false);
});
