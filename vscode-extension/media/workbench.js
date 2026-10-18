/* All response and source text is rendered with textContent, never HTML. */
(() => {
  'use strict';
  const vscode = acquireVsCodeApi();
  const byId = id => document.getElementById(id);
  let state;
  let proofTimer;
  let pendingProof = false;
  const send = (type, value) => vscode.postMessage(value === undefined ? { type } : { type, value });
  const flushProof = () => {
    if (!pendingProof) return;
    clearTimeout(proofTimer);
    pendingProof = false;
    send('updateProofInputs', byId('proof-inputs').value);
  };
  const action = (id, type) => byId(id).addEventListener('click', () => { flushProof(); send(type); });
  [
    ['demo', 'demo'], ['choose-cobol', 'chooseCobol'], ['choose-java', 'chooseJava'],
    ['choose-candidate', 'chooseCandidate'], ['choose-contract', 'chooseContract'],
    ['open-cobol', 'openCobol'], ['open-java', 'openJava'], ['open-candidate', 'openCandidate'],
    ['verify', 'verify'], ['verify-candidate', 'verifyCandidate'], ['show-diff', 'showDiff'],
    ['apply-candidate', 'applyCandidate'], ['clear-candidate', 'clearCandidate'],
    ['export-report', 'exportReport'], ['open-settings', 'openSettings'],
  ].forEach(([id, type]) => action(id, type));
  byId('category').addEventListener('change', event => { flushProof(); send('setCategory', event.target.value); });
  byId('save-endpoint').addEventListener('click', () => send('setBackendUrl', byId('backend-url').value.trim()));
  byId('backend-url').addEventListener('keydown', event => {
    if (event.key === 'Enter') send('setBackendUrl', event.target.value.trim());
  });
  byId('proof-inputs').addEventListener('input', () => {
    pendingProof = true;
    clearTimeout(proofTimer);
    proofTimer = setTimeout(flushProof, 180);
    // A locally edited contract immediately makes the visible evidence stale.
    if (state) renderResults({ ...state, resultStale: !!state.result, candidateStale: !!state.candidateResult, canApply: false });
    byId('apply-candidate').disabled = true;
  });
  byId('proof-inputs').addEventListener('change', flushProof);

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }
  function object(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; }
  function text(value, fallback = 'Not supplied') {
    if (value === null || value === undefined || value === '') return fallback;
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }
  function pretty(value) { return JSON.stringify(value, null, 2); }
  function detail(parent, title, value, expanded = false) {
    const details = element('details', 'details');
    details.open = expanded;
    details.append(element('summary', '', title));
    details.append(element('pre', 'json-output', pretty(value)));
    parent.append(details);
  }
  function metric(parent, label, value) {
    const block = element('div', 'metric');
    block.append(element('dt', '', label), element('dd', '', value));
    parent.append(block);
  }
  function percent(value) { return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : 'Unavailable'; }

  function resultCard(result, label, stale) {
    const scope = object(result.proofScope);
    const provenance = object(result.provenanceJson);
    const graph = object(result.cpgGraphJson);
    const status = ({ SAT_COUNTEREXAMPLE_FOUND: 'SAT', UNSAT_PROVEN_SAFE: 'UNSAT', UNKNOWN_HALTED_LIMIT: 'UNKNOWN' })[result.formalProofStatus] || 'UNKNOWN';
    const flavor = status.toLowerCase();
    const card = element('article', `result-card ${flavor}${stale ? ' stale' : ''}`);
    const heading = element('div', 'result-heading');
    const title = element('div');
    title.append(element('p', 'eyebrow', label), element('h3', '', status === 'SAT' ? 'A differing output was found' : status === 'UNSAT' ? 'Equivalent within the declared scope' : 'The verifier cannot establish equivalence'));
    heading.append(title, element('span', `proof-badge ${flavor}`, status));
    card.append(heading);
    if (stale) card.append(element('p', 'stale-banner', 'Source, candidate, or proof inputs changed. Run verification again before using this result.'));
    if (status === 'UNSAT') card.append(element('p', 'result-explanation', 'No differing cent-observable output was found across the supported bounded scalar model. This result requires human review and applies only to the scope below.'));
    if (status === 'UNKNOWN') card.append(element('p', 'unknown-reason', text(scope.reason, 'Unsupported or incomplete proof inputs. Review the scope and backend response for details.')));
    if (result.fStringSummary) card.append(element('p', 'result-summary', result.fStringSummary));
    const witnesses = Array.isArray(result.counterexamplesJson) ? result.counterexamplesJson : [];
    witnesses.forEach((raw, index) => {
      const witness = object(raw);
      const group = element('section', 'witness');
      group.append(element('h4', '', `Failing transaction${witnesses.length > 1 ? ` ${index + 1}` : ''}`));
      const metrics = element('dl', 'witness-metrics');
      metric(metrics, 'Input amount · GBP', text(witness.inputAmountGbp));
      metric(metrics, 'COBOL output', text(witness.cobolOutput ?? witness.cobolOutputEur));
      metric(metrics, 'Java output', text(witness.javaOutput ?? witness.javaOutputEur));
      metric(metrics, 'Output drift', text(witness.pennyDrift));
      group.append(metrics);
      const reference = element('p', 'muted', `Exact reference rate: ${text(witness.referenceRate)} · ${text(witness.dataSource)} · collected ${text(witness.collectedDate)}`);
      group.append(reference);
      detail(group, 'Complete counterexample', witness);
      card.append(group);
    });
    const scopeSummary = element('dl', 'scope-summary');
    const bounds = object(scope.inputAmountCents);
    metric(scopeSummary, 'Proof domain', bounds.min !== undefined && bounds.max !== undefined ? `${bounds.min} … ${bounds.max} integer cents` : 'See explicit scope');
    const rate = object(scope.rate);
    metric(scopeSummary, 'Reference rate', rate.rate ? `${text(rate.rate)} ${text(rate.currencyPair, '')}` : 'No matching reference rate');
    metric(scopeSummary, 'Supported model', scope.supported === true ? 'Yes · bounded scalar arithmetic' : 'Unsupported or incomplete');
    card.append(scopeSummary);
    detail(card, 'Exact proof scope, assumptions & source hashes', scope);
    const graphDetails = element('details', 'details');
    graphDetails.append(element('summary', '', 'Graph inspection & experimental neural scores'));
    const graphBody = element('div', 'graph-body');
    graphBody.append(element('p', 'muted', 'These scores assist inspection. They do not establish equivalence, authorize a fix, or measure validated defect accuracy.'));
    const graphMetrics = element('dl', 'graph-metrics');
    metric(graphMetrics, 'Graph nodes', Array.isArray(graph.nodes) ? graph.nodes.length : 'Unavailable');
    metric(graphMetrics, 'Graph edges', Array.isArray(graph.edges) ? graph.edges.length : 'Unavailable');
    metric(graphMetrics, 'Alignment · experimental', percent(result.gnnAlignmentScore));
    metric(graphMetrics, 'Risk · unvalidated', percent(result.gnnBugRiskScore));
    graphBody.append(graphMetrics);
    if (graph.semanticExtraction) graphBody.append(element('pre', 'json-output', pretty(graph.semanticExtraction)));
    if (graph.deterministicDiagnostics) detail(graphBody, 'Deterministic graph diagnostics', graph.deterministicDiagnostics);
    graphBody.append(element('p', 'muted', 'Evidence describes whole-program modeled behavior. Graph links and code locations are inspection hints, not proven source-line causes.'));
    graphDetails.append(graphBody);
    card.append(graphDetails);
    detail(card, 'Engine, model & data provenance', provenance);
    return card;
  }

  function renderResults(next) {
    byId('empty-state').hidden = !!(next.result || next.candidateResult);
    const original = byId('original-result');
    original.replaceChildren();
    if (next.result) original.append(resultCard(next.result, 'CURRENT JAVA', next.resultStale));
    const candidate = byId('candidate-result');
    candidate.replaceChildren();
    if (next.candidateResult) candidate.append(resultCard(next.candidateResult, next.applied ? 'APPLIED REPLACEMENT' : 'PROPOSED FIX', next.candidateStale));
  }
  function updateFile(kind, file) {
    const link = byId(`open-${kind}`);
    link.textContent = file ? `${file.name}${file.dirty ? ' · unsaved' : ''}` : kind === 'candidate' ? 'No proposed fix selected' : `No ${kind === 'cobol' ? 'COBOL' : 'Java'} file selected`;
    link.disabled = !file || state.busy;
    link.title = file ? file.path : '';
    byId(`${kind}-path`).textContent = file ? file.path : '';
  }
  function render(next) {
    state = next;
    const busy = !!next.busy;
    document.body.classList.toggle('busy', busy);
    byId('status-message').textContent = next.message || (busy ? 'Verification in progress…' : 'Ready. Verification runs only when requested.');
    byId('status-message').classList.toggle('working', busy);
    if (document.activeElement !== byId('backend-url')) byId('backend-url').value = next.backendUrl;
    if (!pendingProof && document.activeElement !== byId('proof-inputs')) byId('proof-inputs').value = next.proofInputsText || '';
    byId('category').value = next.category;
    ['cobol', 'java', 'candidate'].forEach(kind => updateFile(kind, next.files[kind]));
    const paired = !!(next.files.cobol && next.files.java);
    const candidate = !!next.files.candidate;
    ['demo', 'choose-cobol', 'choose-java', 'choose-candidate', 'choose-contract', 'save-endpoint', 'open-settings', 'category', 'backend-url', 'proof-inputs'].forEach(id => { byId(id).disabled = busy; });
    byId('verify').disabled = busy || !paired;
    byId('verify').textContent = busy ? 'Working…' : 'Verify source pair';
    byId('verify-candidate').disabled = busy || !paired || !candidate;
    byId('clear-candidate').disabled = busy || !candidate;
    byId('show-diff').disabled = busy || !next.files.java || !candidate;
    byId('apply-candidate').disabled = busy || !next.canApply || pendingProof;
    byId('export-report').disabled = busy || !(next.result || next.candidateResult);
    byId('applied-message').hidden = !next.applied;
    renderResults(next);
  }
  window.addEventListener('message', event => {
    if (event.data && event.data.type === 'state' && event.data.state) render(event.data.state);
  });
  send('ready');
})();
