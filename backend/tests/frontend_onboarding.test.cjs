const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const entry=fs.readFileSync(path.resolve(__dirname,'../../demo/static/js/entry.js'),'utf8');
const dashboard=fs.readFileSync(path.resolve(__dirname,'../../demo/static/js/dashboard.js'),'utf8');
function fields(saved, state) {
 const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,{value:'',hidden:false,selectedOptions:[{textContent:'Italian'}]});return elements.get(id);};
 const ctx=vm.createContext({entryHasSavedBrief:saved,entryHasSubmitted:false,state,ideaOptions:[{value:'other',label:'Other',profile:'restaurant'},{value:'bistro',label:'Bistro',profile:'restaurant'}],ideaInput:get('idea'),cuisineInput:get('cuisine'),cuisineSelect:{value:'italian',selectedOptions:[{textContent:'Italian'}]},descriptionField:get('description'),document:{getElementById:get,querySelector:s=>get(s)}});
 vm.runInContext('let selectedIdea=null;'+entry.slice(entry.indexOf('function syncEntryFields()'),entry.indexOf('function submitEntryBrief()')),ctx);vm.runInContext('syncEntryFields()',ctx);return {ctx,get};
}
test('first-time idea is empty and custom field is hidden',()=>{const {get}=fields(false,{conceptName:''});assert.equal(get('idea').value,'');assert.equal(get('#customIdeaField').hidden,true);});
test('legacy saved custom names restore verbatim without being relabeled Other',()=>{const {get}=fields(true,{conceptName:'Modern Bistro',profile:'restaurant',cuisine:'italian',description:''});assert.equal(get('idea').value,'Modern Bistro');assert.equal(get('#customIdeaField').hidden,true);});
test('an intentional Other choice restores its named concept and custom field',()=>{const {get}=fields(true,{ideaChoice:'other',conceptName:'My neighborhood kitchen',profile:'restaurant',cuisine:'italian',description:''});assert.equal(get('idea').value,'Other');assert.equal(get('#briefCustomIdea').value,'My neighborhood kitchen');assert.equal(get('#customIdeaField').hidden,false);});
test('sample exploration never writes an active or saved brief',()=>{const ctx=vm.createContext({sampleMode:true,state:{conceptName:''}});vm.runInContext(dashboard.slice(dashboard.indexOf('function persistBrief()'),dashboard.indexOf('function syncSavedLocations()')),ctx);assert.doesNotThrow(()=>vm.runInContext('persistBrief()',ctx));});

test('custom names that match a catalog option still restore the user’s Other choice',()=>{const {get}=fields(true,{ideaChoice:'other',conceptName:'Bistro',profile:'coffee',cuisine:'italian',description:''});assert.equal(get('idea').value,'Other');assert.equal(get('#briefCustomIdea').value,'Bistro');});
