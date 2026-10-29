const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../demo/static/js/dashboard.js'), 'utf8');
const boundary = source.slice(source.indexOf('function installNycBoundary()'), source.indexOf('function propertyFeatureAtPoint('));

for (const style of ['streets','aerial','buildings3d']) {
  test(`${style}: circles and labels stay above the mask and boundary, without idle reordering loops`, () => {
    const ids=['background','property-clusters','property-points','property-cluster-count','property-rank-label','property-selection','property-selection-rank','restaurant-clusters','restaurant-points','restaurant-cluster-count','nyc-context-mask','nyc-boundary-halo','nyc-boundary-line','concept-hex-fill'];
    const layers=ids.map(id=>({id}));let moves=0;let opacity=0;
    const context=vm.createContext({Date,nycBoundaryData:{},activeBasemap:style,currentTheme:'light',locationMap:{
      getStyle:()=>({layers}),isStyleLoaded:()=>true,getSource:()=>true,
      getLayer:id=>layers.find(layer=>layer.id===id),getPaintProperty:()=>opacity,setPaintProperty:(id,key,value)=>{opacity=value;},
      moveLayer:id=>{const index=layers.findIndex(layer=>layer.id===id);layers.push(...layers.splice(index,1));moves++;},
    }});
    vm.runInContext(boundary,context);vm.runInContext('installNycBoundary()',context);
    const index=id=>layers.findIndex(layer=>layer.id===id);
    assert(index('nyc-context-mask')>index('concept-hex-fill'));
    for (const id of ['property-clusters','property-points','property-cluster-count','property-rank-label','property-selection','property-selection-rank','restaurant-clusters','restaurant-points','restaurant-cluster-count']) assert(index(id)>index('nyc-boundary-line'),id);
    assert(index('property-selection-rank')>index('property-selection'));
    const first=moves;vm.runInContext('installNycBoundary()',context);assert.equal(moves,first);
    layers.push({id:'late-heatmap'});vm.runInContext('installNycBoundary()',context);
    assert(index('nyc-context-mask')>index('late-heatmap'));
    assert(index('property-clusters')>index('nyc-boundary-line'));
  });
}
