const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').resolve(__dirname, '../../demo/static/js/dashboard.js'), 'utf8');
const comparison = source.slice(source.indexOf('function locationComparisonMarkup('), source.indexOf('function renderMarketProfile('));
function markup(population, location) {
  const context = vm.createContext({dashboard:{comparison:population}, escapeHtml: value=>String(value??''), displayNumber:value=>value.toLocaleString('en-US')});
  vm.runInContext(comparison, context);
  context.location=location;
  return vm.runInContext('locationComparisonMarkup(location)',context);
}
const population = {complete_population:true,metric:'opportunity',label:'Location Score',count:2243,eligible_count:2243,mean:52.55,median:52,geography:'Queens',definition:'All eligible Queens tracts before the response cap.'};
test('comparison shows selected score, full population, mean, median and signed difference',()=>{
  const result=markup(population,{opportunity:70,borough:'Queens',assessment_policy:{recommendation_eligible:true}});
  for(const text of ['70.0/100','52.5/100','52.0/100','+18.0 points','2,243 comparable tracts','before the response cap']) assert.ok(result.includes(text),text);
});
test('saved area outside the active geography is not represented as eligible',()=>{
  const result=markup(population,{opportunity:70,borough:'Brooklyn',assessment_policy:{recommendation_eligible:true}});
  assert.match(result,/Outside Comparable Population/);assert.doesNotMatch(result,/\+18.0 points/);
});
test('absent or incomplete populations never fall back to shortlist statistics',()=>{
  for(const data of [undefined,{...population,complete_population:false},{...population,count:0,median:null}])
    assert.match(markup(data,{opportunity:70}),/No median is inferred/);
});
test('active customer access comparison uses the access score and retains negative differences',()=>{
  const result=markup({...population,metric:'inverse_walkability',label:'Customer Access'},{opportunity:99,inverse_walkability:42,borough:'Queens',assessment_policy:{recommendation_eligible:true}});
  assert.match(result,/42.0\/100/);assert.match(result,/-10.0 points/);assert.doesNotMatch(result,/99.0/);
});


test('ACS income sentinel is an open interval and missing values are not shown as money',()=>{
 const ctx=vm.createContext({fmtDollar:n=>'$'+n.toLocaleString('en-US')});
 vm.runInContext(source.slice(source.indexOf('function householdIncome('),source.indexOf('function locationComparisonMarkup(')),ctx);
 assert.equal(vm.runInContext('householdIncome(250001)',ctx),'$250,000+');
 assert.equal(vm.runInContext('householdIncome(123456)',ctx),'$123,500');
 for(const x of [null,undefined,'',-666666666,NaN,true]) {ctx.x=x;assert.equal(vm.runInContext('householdIncome(x)',ctx),'Unavailable');}
});
test('every existing analysis has one understandable destination',()=>{
 const ctx=vm.createContext({});vm.runInContext(source.slice(source.indexOf('function destinationForView('),source.indexOf('const destinationLastView')),ctx);
 for(const [view,group] of Object.entries({discover:'explore',scorecard:'analyze',access:'analyze',whitespace:'analyze',compare:'compare',lease:'plan',finance:'plan',menu:'plan',workspace:'plan',reports:'report',layers:'report',settings:'settings'})) assert.equal(vm.runInContext(`destinationForView('${view}')`,ctx),group);
});

test('property types retain distinct meanings in shared details and reports',()=>{
 const ctx=vm.createContext({});vm.runInContext(source.slice(source.indexOf('function propertyRecordLabel('),source.indexOf('function overviewRecommendations(')),ctx);
 for(const [kind,label] of [['synthetic','Synthetic scenario · not a listing'],['registry_record','Registry research · availability unverified'],['listing','Sourced lead · verify availability']]) assert.equal(vm.runInContext(`propertyRecordLabel({lead_type:'${kind}'})`,ctx),label);
});
