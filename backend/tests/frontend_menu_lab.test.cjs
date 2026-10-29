const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../demo/static/js/menu_lab.js'), 'utf8');
function environment() { const context = vm.createContext({structuredClone}); vm.runInContext(source, context); return context; }

test('menu contribution excludes unknown costs and prices while retaining losses', () => {
  const context = environment();
  context.items = [{name:'A',price:20,cost:5},{name:'B',price:10,cost:15},{name:'C',price:0,cost:0},{name:'D',price:10,cost:''}];
  const rows = vm.runInContext('menuContribution(items)',context);
  assert.equal(rows.length,2); assert.equal(rows[0].contribution,15); assert.equal(rows[1].contribution,-5);
});
test('duplicate names remain unique and bounded', () => {
  const context=environment(); context.items=[{name:'Rice (Copy)'}];
  assert.equal(vm.runInContext('duplicateDishName("Rice",items)',context),'Rice (Copy 2)');
  assert.equal(vm.runInContext('duplicateDishName("A".repeat(80),[])',context).length,80);
});
test('undo captures only the removed dish rather than unrelated financial state', () => {
  const context=environment();context.planKey=()=> 'menu:lease';context.savedMenu=[{id:'a',name:'Rice'}];
  context.currentPlan=()=>({menu_details:{a:{ingredients:'Rice'}},basket:{a:2},draft:{price:90}});
  vm.runInContext('rememberRemovedMenuItem("a")',context);
  assert.equal(vm.runInContext('removedMenuItem.quantity',context),2);
  assert.equal(vm.runInContext('removedMenuItem.draft',context),undefined);
  context.savedMenu[0].name='Changed';assert.equal(vm.runInContext('removedMenuItem.item.name',context),'Rice');
});
test('cash CSV preserves numeric losses and escapes formula-like scenario names', () => {
  const context=environment();
  vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../demo/static/js/business_workspace.js'), 'utf8'),context);
  assert.equal(vm.runInContext('businessCsvCell(-4200.5)',context),'"-4200.5"');
  assert.equal(vm.runInContext('businessCsvCell("=HYPERLINK(1)")',context),'"\'=HYPERLINK(1)"');
  assert.equal(vm.runInContext('businessCsvCell(null)',context),'""');
});
