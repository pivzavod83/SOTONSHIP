/* All response and source text is rendered with textContent, never HTML. */
(() => {
  'use strict';
  const vscode = acquireVsCodeApi();
  const byId = id => document.getElementById(id);
  let state;
  let proofTimer;
  let aiContextTimer;
  let pendingProof = false;
  let pendingAiContext = false;
  const send = (type, value) => vscode.postMessage(value === undefined ? { type } : { type, value });
  const flushProof = () => {
    if (!pendingProof) return;
    clearTimeout(proofTimer);
    pendingProof = false;
    send('updateProofInputs', byId('proof-inputs').value);
  };
  const flushAiContext = () => {
    if (!pendingAiContext) return;
    clearTimeout(aiContextTimer); pendingAiContext = false;
    send('updateAiReviewContext', byId('ai-review-context').value);
  };
  const action = (id, type) => byId(id).addEventListener('click', () => { flushProof(); flushAiContext(); send(type); });
  [
    ['demo', 'demo'], ['choose-cobol', 'chooseCobol'], ['choose-java', 'chooseJava'],
    ['choose-candidate', 'chooseCandidate'], ['choose-contract', 'chooseContract'],
    ['open-cobol', 'openCobol'], ['open-java', 'openJava'], ['open-candidate', 'openCandidate'],
    ['verify', 'verify'], ['verify-candidate', 'verifyCandidate'], ['show-diff', 'showDiff'],
    ['apply-candidate', 'applyCandidate'], ['clear-candidate', 'clearCandidate'],
    ['export-report', 'exportReport'], ['open-settings', 'openSettings'],
    ['choose-matching-files', 'chooseMatchingFiles'], ['match-programs', 'matchPrograms'],
    ['analyze-pair-ai', 'analyzePairWithAi'],
  ].forEach(([id, type]) => action(id, type));
  byId('category').addEventListener('change', event => { flushProof(); send('setCategory', event.target.value); });
  byId('matching-format').addEventListener('change', event => send('setMatchingSourceFormat', event.target.value));
  byId('ai-review-format').addEventListener('change', event => {
    flushAiContext(); send('setAiReviewSourceFormat', event.target.value);
    if (state) renderAiReview({ ...state, aiReviewStale: !!state.aiReviewResult });
  });
  byId('ai-review-context').addEventListener('input', () => {
    pendingAiContext = true; clearTimeout(aiContextTimer);
    aiContextTimer = setTimeout(flushAiContext, 180);
    if (state) renderAiReview({ ...state, aiReviewStale: !!state.aiReviewResult });
  });
  byId('ai-review-context').addEventListener('change', flushAiContext);
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

  function renderMatching(next) {
    const container = byId('matching-result'); container.replaceChildren();
    const result = next.matchingResult;
    if (!result) return;
    const card = element('article', `result-card matching-card${next.matchingStale ? ' stale' : ''}`);
    card.append(element('p', 'eyebrow', 'LEARNED PROGRAM MATCHING'), element('h3', '', result.status === 'MATCH_SUGGESTED' ? 'A candidate match is suggested' : 'Ranking requires engineer review'));
    card.append(element('p', 'result-explanation', result.reason));
    card.append(element('p', 'muted', 'Cosine similarity is an advisory ranking score, not a confidence percentage or equivalence proof. Every candidate requires your review. Matching does not infer proof mappings or identify exact faulty operations.'));
    if (next.matchingStale) card.append(element('p', 'stale-banner', 'The COBOL, Java candidates, format or backend changed. Rank the current candidates again before confirming.'));
    const list = element('ol', 'matching-ranking');
    result.candidates.forEach(candidate => {
      const row = element('li', 'matching-row');
      const heading = element('div');
      heading.append(element('strong', '', `${candidate.rank}. ${candidate.moduleName}`), element('p', 'muted', `Cosine similarity ${candidate.similarity.toFixed(4)}`));
      const selectedFile = next.matchingFiles?.find(item => item.candidateId === candidate.candidateId)?.file;
      if (selectedFile) heading.append(element('p', 'file-path', selectedFile.path));
      const button = element('button', 'secondary', next.confirmedMatchId === candidate.candidateId ? 'Selected by engineer' : 'Confirm this Java candidate');
      button.disabled = !!next.busy || !!next.matchingStale || next.confirmedMatchId === candidate.candidateId;
      button.addEventListener('click', () => { flushProof(); send('confirmMatch', candidate.candidateId); });
      row.append(heading, button); list.append(row);
    });
    card.append(list);
    if (next.confirmedMatchId) card.append(element('p', 'muted', 'The confirmed Java file is selected below. Review the explicit proof contract before running verification.'));
    detail(card, 'Model, training dataset & held-out evaluation', result.model);
    detail(card, 'Ranking thresholds & exact source hashes', { thresholds: result.thresholds, cobolSourceSha256: result.cobolSourceSha256, candidates: result.candidates });
    container.append(card);
  }

  function renderAiReview(next) {
    const container = byId('ai-review-result'); container.replaceChildren();
    const result = next.aiReviewResult;
    if (!result) return;
    const card = element('article', `result-card ai-review-card${next.aiReviewStale ? ' stale' : ''}`);
    card.append(element('p', 'eyebrow', 'AI DEFECT REVIEW · HYPOTHESES'), element('h3', '', next.aiReviewStale ? 'AI review is stale' : ({
      ANALYZED: `${result.findings.length} suspected defect${result.findings.length === 1 ? '' : 's'}`,
      NOT_CONFIGURED: 'Configure the model on your backend', PROVIDER_ERROR: 'The model provider could not complete this review',
      INVALID_MODEL_OUTPUT: 'The model response failed validation', REFUSED: 'The model declined this review',
    })[result.status] || 'AI review unavailable'));
    if (next.aiReviewStale) {
      card.append(element('p', 'stale-banner', 'The sources, editor versions, context, source format or backend changed. Findings are hidden; analyze the current pair again.'));
      container.append(card); return;
    }
    card.append(element('p', 'result-summary', result.summary));
    card.append(element('p', 'muted', 'AI hypotheses can be wrong or incomplete. Source spans locate a suspected mismatch; they are not proven causes. No candidate inputs have been executed. Run supported Z3 verification separately.'));
    if (result.status === 'ANALYZED' && !result.findings.length) card.append(element('p', 'unknown-reason', 'The model reported no suspected mismatch. This does not establish equivalence or safety.'));
    result.findings.forEach(finding => {
      const section = element('section', 'witness ai-finding');
      section.append(element('p', 'eyebrow', `${finding.findingId} · ${finding.severity} · ${finding.category.replace(/_/g, ' ')} · AI HYPOTHESIS`), element('h4', '', finding.title));
      section.append(element('p', 'result-explanation', finding.explanation));
      [['COBOL', finding.cobolLines, finding.cobolExcerpt], ['Java', finding.javaLines, finding.javaExcerpt]].forEach(([language, lines, excerpt]) => {
        if (!lines) return;
        section.append(element('p', 'field-label', `${language} lines ${lines.start}–${lines.end}`), element('pre', 'json-output source-excerpt', excerpt));
      });
      section.append(element('h4', '', 'Suggested correction · engineer review'), element('p', '', finding.suggestedFix || 'No correction proposed.'));
      finding.candidateInputs.forEach((candidate, index) => {
        section.append(element('h4', '', `Proposed input ${index + 1} · NOT EXECUTED`), element('pre', 'json-output', candidate.inputsJson), element('p', 'muted', candidate.rationale));
      });
      card.append(section);
    });
    if (result.limitations.length) {
      const limitations = element('ul', 'ai-limitations'); result.limitations.forEach(item => limitations.append(element('li', '', item)));
      card.append(element('h4', '', 'Review limitations'), limitations);
    }
    detail(card, 'Provider, source hashes & AI evidence status', { provider: result.provider, sourceHashes: result.sourceHashes,
      promptVersion: result.promptVersion, aiIsProof: result.aiIsProof, counterexamplesExecuted: result.counterexamplesExecuted });
    container.append(card);
  }

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
    graphDetails.append(element('summary', '', 'Graph inspection'));
    const graphBody = element('div', 'graph-body');
    graphBody.append(element('p', 'muted', 'Program matching is shown separately above. Defect risk is not estimated; no synthetic risk model is used.'));
    const graphMetrics = element('dl', 'graph-metrics');
    metric(graphMetrics, 'Graph nodes', Array.isArray(graph.nodes) ? graph.nodes.length : 'Unavailable');
    metric(graphMetrics, 'Graph edges', Array.isArray(graph.edges) ? graph.edges.length : 'Unavailable');
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
    byId('empty-state').hidden = !!(next.result || next.candidateResult || next.aiReviewResult);
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
    byId('matching-format').value = next.matchingSourceFormat || 'AUTO';
    byId('ai-review-format').value = next.aiReviewSourceFormat || 'AUTO';
    if (!pendingAiContext && document.activeElement !== byId('ai-review-context')) byId('ai-review-context').value = next.aiReviewContext || '';
    const matchingFiles = byId('matching-files'); matchingFiles.replaceChildren();
    (next.matchingFiles || []).forEach(item => {
      const label = element('li', '', `${item.candidateId} · ${item.file.name}${item.file.dirty ? ' · unsaved' : ''}`);
      label.title = item.file.path; matchingFiles.append(label);
    });
    ['cobol', 'java', 'candidate'].forEach(kind => updateFile(kind, next.files[kind]));
    const paired = !!(next.files.cobol && next.files.java);
    const candidate = !!next.files.candidate;
    ['demo', 'choose-cobol', 'choose-java', 'choose-candidate', 'choose-contract', 'choose-matching-files', 'matching-format', 'ai-review-format', 'ai-review-context', 'save-endpoint', 'open-settings', 'category', 'backend-url', 'proof-inputs'].forEach(id => { byId(id).disabled = busy; });
    byId('match-programs').disabled = busy || !next.files.cobol || !next.matchingFiles?.length;
    byId('verify').disabled = busy || !paired;
    byId('verify').textContent = busy ? 'Working…' : 'Verify source pair';
    byId('analyze-pair-ai').disabled = busy || !paired;
    byId('verify-candidate').disabled = busy || !paired || !candidate;
    byId('clear-candidate').disabled = busy || !candidate;
    byId('show-diff').disabled = busy || !next.files.java || !candidate;
    byId('apply-candidate').disabled = busy || !next.canApply || pendingProof;
    byId('export-report').disabled = busy || !(next.result || next.candidateResult || next.matchingResult || next.aiReviewResult);
    byId('applied-message').hidden = !next.applied;
    renderResults(next);
    renderMatching(next);
    renderAiReview(pendingAiContext ? { ...next, aiReviewStale: !!next.aiReviewResult } : next);
  }
  window.addEventListener('message', event => {
    if (event.data && event.data.type === 'state' && event.data.state) render(event.data.state);
  });
  send('ready');
})();
