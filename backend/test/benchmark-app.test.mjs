import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../benchmark-ui/app.js', import.meta.url), 'utf8');

// A small DOM harness exercises the rendered comparison and click handlers. It
// does not duplicate the assessment selection logic or require a browser package.
function node() {
  return { innerHTML: '', textContent: '', hidden: false, value: '', dataset: {},
    listeners: {}, attributes: {}, classList: { toggle() {} },
    addEventListener(event, callback) { this.listeners[event] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() { this.focused = true; }, closest() { return null; } };
}

function assessment(id, pairs, accuracy, label) {
  return { id, label, pairs, reused: true, metrics: { accuracy, recall: .75 }, counts: { tp: 3, fn: 1 },
    cohort: `fixture-${id}-${pairs}` };
}

test('24-pair action switches from program matching to grouped defect CV without pooling test results', async () => {
  const nodes = new Map(), handlers = {};
  const get = selector => { if (!nodes.has(selector)) nodes.set(selector, node()); return nodes.get(selector); };
  get('#registry-task').value = get('#registry-status').value = 'all';
  const catalog = { repository: { branch: 'research/current', branchUrl: 'https://example.com/tree/research/current' },
    codeNetReadiness: { status: 'PARSER_SUPPORT_REQUIRED',
      counts: { selectedPairs: 650, selectedPairProblemIds: 325, cobolSources: 1277, javaSources: 251052, problemIds: 340, javaRepairCandidates: 23225 },
      profiles: { FREE: { completePairs: 0, pairs: 650 }, FIXED: { completePairs: 0, pairs: 650 } },
      accuracy: null, recall: null },
    versions: [
      { id: 'defect-fixture', task: 'defect', status: 'experimental', name: 'Defect fixture', defaultAssessmentId: 'regression',
        assessments: [assessment('regression', 8, .5, 'Reused regression'), assessment('oof', 24, 2 / 3, 'Grouped out-of-fold'), assessment('validation', 8, .625, 'Validation')] },
      { id: 'matching-fixture', task: 'matching', status: 'historical', name: 'Matching fixture', defaultAssessmentId: 'regression',
        assessments: [assessment('regression', 29, .9, 'Matching test')] },
    ] };
  const document = { querySelector: get, querySelectorAll: () => [],
    addEventListener(event, callback) { handlers[event] = callback; } };
  vm.runInNewContext(source, { document, window: { addEventListener() {} },
    location: { origin: 'http://127.0.0.1:3010', hash: '' }, history: { replaceState() {} },
    URL, setTimeout, clearTimeout,
    fetch: async path => ({ ok: true, json: async () => path === '/api/catalog' ? catalog : { papers: [], proposals: [] } }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(get('#error-panel').hidden, true);
  assert.equal(get('#codenet-readiness').hidden, false);
  assert.match(get('#codenet-readiness').innerHTML, /650 source-pair comparisons/);
  assert.match(get('#codenet-readiness').innerHTML, /Frozen V2 extractor completes both sides/);
  assert.match(get('#codenet-readiness').innerHTML, /FREE 0 \/ 650 · FIXED 0 \/ 650/);
  assert.match(get('#codenet-readiness').innerHTML, /Model accuracy and defect recall: not measured/);
  assert.doesNotMatch(get('#codenet-readiness').innerHTML, /0%|100%/);
  assert.match(get('#comparison-table tbody').innerHTML, /8 pairs/);
  const task = { dataset: { task: 'matching' } };
  handlers.click({ target: { closest: selector => selector === '[data-task]' ? task : null } });
  assert.match(get('#comparison-table tbody').innerHTML, /Matching fixture/);
  get('#show-pilot-cv').listeners.click();
  const table = get('#comparison-table tbody').innerHTML;
  assert.match(table, /Grouped out-of-fold/);
  assert.match(table, /24 pairs/);
  assert.match(table, /66\.7%/);
  assert.doesNotMatch(table, /8 pairs|Matching fixture/);
  assert.match(get('#assessment-select').innerHTML, /value="cv" selected/);
  assert.equal(get('#assessment-select').focused, true);
  assert.match(get('#comparison-note').innerHTML, /not a pooled leaderboard/);
});

test('initial page explains all forty pairs and never embeds a stale branch URL', async () => {
  const html = await readFile(new URL('../benchmark-ui/index.html', import.meta.url), 'utf8');
  assert.match(html, /40 pairs across 10 source families/);
  assert.match(html, /24 grouped out-of-fold predictions/);
  assert.match(html, /8 validation pairs · 8 reused regression pairs/);
  assert.match(html, /id="show-pilot-cv"/);
  assert.doesNotMatch(html, /\/tree\/research\/benchmark-dashboard|\/commits\/research\/benchmark-dashboard/);
});

test('parser UI preserves unknown stages, switches source-format probes and filters escaped diagnostics', async () => {
  const nodes = new Map();
  const get = selector => { if (!nodes.has(selector)) nodes.set(selector, node()); return nodes.get(selector); };
  get('#registry-task').value = get('#registry-status').value = 'all';
  const metrics = count => ({ syntaxParsed: { count, denominator: 10, status: 'MEASURED', unknown: 0, failed: 10 - count },
    namesTypesResolved: { count: 0, denominator: 10, status: 'MEASURED', unknown: 10, failed: 0 },
    semanticsModeled: { count: 0, denominator: 10, status: 'MEASURED', unknown: 10, failed: 0 } });
  const baselineMetrics = { syntaxParsed: { count: null, denominator: 10, status: 'NOT_SEPARATELY_MEASURED' },
    namesTypesResolved: { count: null, denominator: 10, status: 'NOT_SEPARATELY_MEASURED' },
    semanticsModeled: { count: 0, denominator: 10, status: 'MEASURED' } };
  const catalog = { repository: {}, versions: [], parserExperiments: { versions: [
    { id: 'parser-typed-v2', name: 'V2', profiles: { FREE: { metrics: baselineMetrics }, FIXED: { metrics: baselineMetrics } } },
    { id: 'parser-v3', name: 'V3', status: 'EXPERIMENTAL', profiles: { FREE: { metrics: metrics(10) }, FIXED: { metrics: metrics(6) } },
      failureExamples: [{ language: 'COBOL', profile: 'FREE', path: 'free.cob', message: '<img src=x onerror=alert(1)>' },
        { language: 'COBOL', profile: 'FIXED', path: 'fixed.cob', message: 'Expected division.' },
        { language: 'Java', path: 'source.java', message: 'Unresolved import.' }] },
  ] } };
  const document = { querySelector: get, querySelectorAll: () => [], addEventListener() {} };
  vm.runInNewContext(source, { document, window: { addEventListener() {} },
    location: { origin: 'http://127.0.0.1:3010', hash: '#parsers' }, history: { replaceState() {} }, URL, setTimeout, clearTimeout,
    fetch: async path => ({ ok: true, json: async () => path === '/api/catalog' ? catalog : { papers: [], proposals: [] } }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(get('#error-panel').hidden, true);
  assert.equal(get('#parser-count').textContent, '2');
  assert.equal(get('#version-count').textContent, '0');
  const initial = get('#parser-content').innerHTML;
  assert.match(initial, /Syntax parsed/);
  assert.match(initial, /Names \/ types resolved/);
  assert.match(initial, /Semantic representation complete/);
  assert.match(initial, /Not measured/);
  assert.match(initial, /0 failed · 10 unknown/);
  assert.match(initial, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(initial, /<img|fixed\.cob/);
  get('#parser-profile').listeners.change({ target: { value: 'FIXED' } });
  const fixed = get('#parser-content').innerHTML;
  assert.match(fixed, /60\.0%/);
  assert.match(fixed, /fixed\.cob/);
  assert.doesNotMatch(fixed, /free\.cob/);
  get('#parser-content').listeners.change({ target: { id: 'parser-diagnostic-language', value: 'Java' } });
  const java = get('#parser-content').innerHTML;
  assert.match(java, /source\.java/);
  assert.doesNotMatch(java, /fixed\.cob/);
  assert.match(java, /1 of 2 recorded diagnostic examples/);
  assert.equal(get('#parser-diagnostic-language').focused, true);
});
