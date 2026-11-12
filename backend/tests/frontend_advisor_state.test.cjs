const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.resolve(__dirname, '../../demo/static/js/dashboard.js'), 'utf8');
const keyFunctions = source.slice(source.indexOf('function advisorSearchKey('), source.indexOf('function renderAdvisorChatActions('));
const resultFunctions = source.slice(source.indexOf('function resetAdvisorResults('), source.indexOf('function renderCompare('));

function state() {
  const elements = new Map();
  const calls = {lab: 0};
  const context = vm.createContext({
    URLSearchParams,
    query: 'borough=Queens&cuisine=italian&saved_id=36081000100',
    dashboard: {meta: {release_id: 'first-release'}},
    conceptParams() { return new URLSearchParams(context.query); },
    resetDecisionLab() { calls.lab++; },
    syncAdvisorChatScope() {},
    document: {querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {hidden: false, textContent: ''});
      return elements.get(selector);
    }},
  });
  vm.runInContext('let advisorRevision=0, advisorEvidenceVersion=null, advisorResearchKey=null, advisorBriefKey=null;', context);
  vm.runInContext(keyFunctions + resultFunctions, context);
  return {context, calls, elements};
}

test('changing saved areas preserves the search and completed Decision Lab', () => {
  const {context, calls, elements} = state();
  vm.runInContext('resetAdvisorResults()', context);
  context.query = 'borough=Queens&cuisine=italian&saved_id=36081000100&saved_id=36081000200';
  vm.runInContext('syncAdvisorResults()', context);
  assert.equal(calls.lab, 1);
  assert.equal(elements.get('#siteBriefResult').hidden, true);
  assert.equal(vm.runInContext('advisorSearchKey()', context), 'borough=Queens&cuisine=italian');
});

test('rerendering selection preserves research while filters and releases invalidate it', () => {
  const {context, calls} = state();
  vm.runInContext('resetAdvisorResults(); syncAdvisorResults()', context);
  assert.equal(calls.lab, 1);
  context.query = 'borough=Brooklyn&cuisine=italian';
  vm.runInContext('syncAdvisorResults()', context);
  assert.equal(calls.lab, 2);
  context.dashboard.meta.release_id = 'second-release';
  vm.runInContext('syncAdvisorResults()', context);
  assert.equal(calls.lab, 3);
});

test('the sample preview can initialize before dashboard data exists', () => {
  const {context, calls} = state();
  context.dashboard = null;
  assert.doesNotThrow(() => vm.runInContext('resetAdvisorResults()', context));
  assert.equal(calls.lab, 1);
});

test('sample-to-live module initialization runs once', () => {
  const calls = [];
  const context = vm.createContext({
    initializeWorkspace(options) { calls.push(['workspace', options.showBrief]); },
    initializePlanningControls() { calls.push(['planning']); },
    initializeMenuLab() { calls.push(['menu']); },
    initializeBusinessWorkspace() { calls.push(['business']); },
  });
  const start = source.indexOf('function initializeDashboardModules(');
  const end = source.indexOf('if (advisorPreview !== "sample")', start);
  vm.runInContext('let dashboardModulesInitialized=false;' + source.slice(start, end), context);
  vm.runInContext('initializeDashboardModules({showBrief:false}); initializeDashboardModules({showBrief:false});', context);
  assert.deepEqual(calls, [['workspace', false], ['planning'], ['menu'], ['business']]);
});

function scenarioRenderer() {
  function node(tag, text = '') {
    return {tag, textContent: text, children: [], setAttribute() {}};
  }
  const context = vm.createContext({
    displayNumber(value) { return String(value); },
    decisionLabText(parent, tag, text) {
      const child = node(tag, text);
      parent.children.push(child);
      return child;
    },
  });
  const start = source.indexOf('function advisorScenarioScore(');
  const end = source.indexOf('function renderAdvisorChatReply(', start);
  vm.runInContext(source.slice(start, end), context);
  const root = node('div');
  const text = item => [item.textContent, ...item.children.map(text)].join(' ');
  return {context, root, text};
}

test('scenario cards retain zero and negative changes while reporting missing scores as unavailable', () => {
  const {context, root, text} = scenarioRenderer();
  context.target = {
    before: {status: 'missing_score', score: null, rank_min: null, rank_max: null},
    after: {status: 'ranked', score: 0, rank_min: 4, rank_max: 4},
    score_delta: -2,
    factors: [],
  };
  context.root = root;
  vm.runInContext('renderAdvisorScenarioTarget(root, target)', context);
  assert.match(text(root), /Unavailable · Rank unavailable/);
  assert.match(text(root), /0 · Rank 4/);
  assert.match(text(root), /Score change -2/);
  assert.equal(vm.runInContext('advisorScenarioRank({status:"ranked",rank_min:2,rank_max:4})', context), 'Tied ranks 2–4');
});

test('neighborhood scenario medians distinguish missing scores from zero and expose changed coverage', () => {
  const {context, root, text} = scenarioRenderer();
  context.root = root;
  context.scenario = {
    before_scope: 'Queens · $35 per guest', after_scope: 'Queens · $50 per guest',
    groups: [{label: 'Astoria', before: {median_score: null, scored_count: 0},
      after: {median_score: 0, scored_count: 1}, coverage_changed: true}],
  };
  vm.runInContext('renderAdvisorScenario(root, scenario)', context);
  assert.match(text(root), /Comparison baseline Queens · \$35 per guest/);
  assert.match(text(root), /Baseline median Unavailable 0 scored tracts/);
  assert.match(text(root), /Preview median 0 1 scored tracts/);
  assert.match(text(root), /set of scored tracts changed/);
});

test('unsupported factor changes are omitted and supported components carry coverage context', () => {
  const {context, root, text} = scenarioRenderer();
  context.root = root;
  context.target = {
    before: {status: 'ranked', score: 50, rank_min: 2, rank_max: 2},
    after: {status: 'ranked', score: 55, rank_min: 1, rank_max: 1},
    score_delta: 5,
    factors: [{label: 'Customer fit', before: 20, after: 30, coverage_changed: true}],
  };
  vm.runInContext('renderAdvisorScenarioTarget(root, target)', context);
  assert.match(text(root), /Score change \+5/);
  assert.match(text(root), /Customer fit: 20 → 30 \(evidence coverage changed\)/);
  assert.match(text(root), /do not add directly to the total score change/);
  context.target.factors = [];
  root.children = [];
  vm.runInContext('renderAdvisorScenarioTarget(root, target)', context);
  assert.doesNotMatch(text(root), /Screening factors that changed/);
});
