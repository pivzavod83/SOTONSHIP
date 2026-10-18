/** Local workbench. Provider credentials never enter this module or its requests. */
export function tokenizeSource(text, language) {
  const pattern = language === 'java'
    ? /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\/.*|\b(?:import|public|final|class|return|new|double|static|void|package|private|if|else|for|while|int|long|boolean|true|false|break|continue|switch|case|throw|throws)\b|\b(?:BigDecimal|RoundingMode|String|System|Scanner|Integer|Long|Math)\b|\b\d+(?:\.\d+)?[Ll]?\b)/g
    : /("(?:[^"]|"")*"|'(?:[^']|'')*'|\*>.*|\b(?:IDENTIFICATION|DIVISION|PROGRAM-ID|DATA|WORKING-STORAGE|SECTION|PIC|COMP-3|VALUE|PROCEDURE|COMPUTE|ROUNDED|GOBACK|MOVE|TO|DISPLAY|ACCEPT|FUNCTION|NUMVAL|STOP|RUN|END-COMPUTE|PERFORM|UNTIL|VARYING|FROM|BY|END-PERFORM|IF|THEN|ELSE|END-IF|ADD|SUBTRACT|MULTIPLY|DIVIDE|GIVING|REMAINDER|ABS|FREE|FORMAT|SOURCE)\b|\b\d+(?:\.\d+)?\b)/gi;
  const tokens = []; let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) tokens.push({ text: text.slice(cursor, match.index), kind: '' });
    const value = match[0];
    const kind = value.startsWith('//') || value.startsWith('*>') ? 'comment' : /^["']/.test(value) ? 'string' : /^\d/.test(value) ? 'number' : /^(BigDecimal|RoundingMode|String|System|Scanner|Integer|Long|Math)$/.test(value) ? 'type' : 'keyword';
    tokens.push({ text: value, kind }); cursor = match.index + value.length;
  }
  if (cursor < text.length) tokens.push({ text: text.slice(cursor), kind: '' });
  return tokens;
}
export async function sourceHash(source) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(source));
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}
export async function evidenceVariant(evidence, cobol, java) {
  if (evidence?.status !== 'CONFIRMED_REPLAY') return null;
  const [cobolHash, javaHash] = await Promise.all([sourceHash(cobol), sourceHash(java)]);
  if (cobolHash !== evidence.sourceHashes?.cobol) return null;
  return javaHash === evidence.sourceHashes.java ? 'original' : javaHash === evidence.sourceHashes.patchedJava ? 'patched' : null;
}
function validSpan(span, source, excerpt) {
  if (span === null) return excerpt === '';
  const lines = source.split('\n');
  return span && Number.isSafeInteger(span.start) && Number.isSafeInteger(span.end) && span.start >= 1 && span.end >= span.start && span.end <= lines.length && excerpt === lines.slice(span.start - 1, span.end).join('\n');
}
export async function validateReview(result, request) {
  if (!result || !['ANALYZED', 'NOT_CONFIGURED', 'PROVIDER_ERROR', 'INVALID_MODEL_OUTPUT', 'REFUSED'].includes(result.status) || result.aiIsProof !== false || result.counterexamplesExecuted !== false || result.promptVersion !== 'paired-defect-review-v1') throw new Error('The API returned an invalid AI review.');
  const [cobol, java] = await Promise.all([sourceHash(request.cobolSource), sourceHash(request.javaSource)]);
  if (result.sourceHashes?.cobol !== cobol || result.sourceHashes?.java !== java) throw new Error('The AI result does not match this exact source pair.');
  if (typeof result.summary !== 'string' || result.summary.length > 8000 || !Array.isArray(result.findings) || result.findings.length > 8 || !Array.isArray(result.limitations) || result.limitations.length > 20 || result.limitations.some(value => typeof value !== 'string' || value.length > 4000) || (result.status !== 'ANALYZED' && result.findings.length)) throw new Error('The AI review has invalid findings.');
  for (const finding of result.findings) {
    if (finding.evidenceStatus !== 'AI_HYPOTHESIS' || typeof finding.title !== 'string' || finding.title.length > 160 || typeof finding.explanation !== 'string' || finding.explanation.length > 4000 || typeof finding.suggestedFix !== 'string' || finding.suggestedFix.length > 4000 || !validSpan(finding.cobolLines, request.cobolSource, finding.cobolExcerpt) || !validSpan(finding.javaLines, request.javaSource, finding.javaExcerpt) || (!finding.cobolLines && !finding.javaLines) || !Array.isArray(finding.candidateInputs) || finding.candidateInputs.length > 3) throw new Error('An AI finding is not anchored to the supplied source.');
    for (const input of finding.candidateInputs) {
      if (input.status !== 'NOT_EXECUTED' || typeof input.inputsJson !== 'string' || input.inputsJson.length > 4000 || typeof input.rationale !== 'string' || input.rationale.length > 1000) throw new Error('The AI response contains an invalid candidate input.');
      const object = JSON.parse(input.inputsJson);
      if (!object || Array.isArray(object) || typeof object !== 'object') throw new Error('Candidate inputs must be JSON objects.');
    }
  }
  return result;
}
export async function validateProof(result, request) {
  if (!result || !['SAT_COUNTEREXAMPLE_FOUND', 'UNSAT_PROVEN_SAFE', 'UNKNOWN_HALTED_LIMIT'].includes(result.formalProofStatus) || result.cobolSource !== request.cobolSource || result.javaSource !== request.javaSource || !Array.isArray(result.counterexamplesJson)) throw new Error('The verification response does not match the submitted source pair.');
  const hashes = result.proofScope?.sourceSha256;
  if (result.formalProofStatus !== 'UNKNOWN_HALTED_LIMIT') {
    if (hashes?.cobol !== await sourceHash(request.cobolSource) || hashes?.java !== await sourceHash(request.javaSource) || result.proofScope.supported !== true || result.proofScope.bounded !== true) throw new Error('The verification response has no valid source-bound scope.');
    if (result.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND' && !result.counterexamplesJson.length) throw new Error('A discrepancy requires a recorded counterexample.');
    if (result.formalProofStatus === 'UNSAT_PROVEN_SAFE' && result.counterexamplesJson.length) throw new Error('A successful proof cannot contain counterexamples.');
  }
  return result;
}

/** Exact source offsets for the inclusive one-based line span. */
export function spanOffsets(source, span) {
  if (!span || !validSpan(span, source, source.split('\n').slice(span.start - 1, span.end).join('\n'))) throw new Error('Invalid source span.');
  const lines = source.split('\n');
  const start = lines.slice(0, span.start - 1).reduce((sum, line) => sum + line.length + 1, 0);
  return { start, end: start + lines.slice(span.start - 1, span.end).join('\n').length };
}
export function isCurrentResponse(ticket, current) {
  return ticket.revision === current.revision && ticket.generation === current.generation && ticket.cobolSource === current.cobolSource && ticket.javaSource === current.javaSource;
}
export function findingDecoration(matches) {
  if (matches.some(item => item.evidenceStatus === 'CONFIRMED_REPLAY')) return { className: 'flag-confirmed', marker: '!' };
  if (matches.some(item => item.evidenceStatus === 'MODEL_HYPOTHESIS')) return { className: 'flag-hypothesis', marker: 'M' };
  return matches.length ? { className: 'flag-hypothesis', marker: 'AI' } : null;
}
export async function validateLocalReview(result, request) {
  if (!result || !['ANALYZED', 'NOT_CONFIGURED', 'UNSUPPORTED'].includes(result.status) || result.engineVersion !== 'paired-defect-v1' || result.aiIsProof !== false || result.counterexamplesExecuted !== false) throw new Error('The local model returned an invalid review.');
  const [cobol, java] = await Promise.all([sourceHash(request.cobolSource), sourceHash(request.javaSource)]);
  if (result.sourceHashes?.cobol !== cobol || result.sourceHashes?.java !== java) throw new Error('The local model result belongs to a different source pair.');
  if (typeof result.summary !== 'string' || result.summary.length > 8000 || !Array.isArray(result.limitations) || result.limitations.length > 20 || result.limitations.some(value => typeof value !== 'string' || value.length > 4000) || !Array.isArray(result.findings) || result.findings.length > 12 || (result.status !== 'ANALYZED' && result.findings.length)) throw new Error('The local model returned invalid findings.');
  if (result.status === 'ANALYZED') {
    const { risk, model } = result;
    if (!risk || !Number.isFinite(risk.score) || risk.score < 0 || risk.score > 1 || !Number.isFinite(risk.threshold) || risk.threshold < 0 || risk.threshold > 1 || risk.calibrated !== false || risk.decision !== (risk.score >= risk.threshold ? 'REVIEW_REQUIRED' : 'NO_DEFECT_SIGNAL') || !model || typeof model.name !== 'string' || !/^[a-f0-9]{64}$/.test(model.sha256) || !/^[a-f0-9]{64}$/.test(model.datasetSha256)) throw new Error('The local model returned invalid risk metadata.');
  }
  const ids = new Set();
  for (const finding of result.findings) {
    if (typeof finding.findingId !== 'string' || ids.has(finding.findingId) || finding.evidenceStatus !== 'MODEL_HYPOTHESIS' || finding.category !== 'SEMANTIC_DIFFERENCE' || typeof finding.title !== 'string' || finding.title.length > 160 || typeof finding.explanation !== 'string' || finding.explanation.length > 4000 || typeof finding.suggestedFix !== 'string' || finding.suggestedFix.length > 4000 || !Number.isFinite(finding.score) || finding.score < 0 || finding.score > 1 || !validSpan(finding.cobolLines, request.cobolSource, finding.cobolExcerpt) || !validSpan(finding.javaLines, request.javaSource, finding.javaExcerpt) || (!finding.cobolLines && !finding.javaLines) || !Array.isArray(finding.candidateInputs) || finding.candidateInputs.length !== 0) throw new Error('A local model finding is not anchored to the supplied source.');
    ids.add(finding.findingId);
  }
  return result;
}

if (typeof document !== 'undefined') {
  const $ = id => document.getElementById(id);
  const source = language => $(`${language}-source`).value;
  const node = (tag, className, text) => { const element = document.createElement(tag); if (className) element.className = className; if (text !== undefined) element.textContent = text; return element; };
  let examples = [], example = null, evidence = null, variant = null, revision = 0, auditedEvaluation = null;
  let localReview = null, cloudReview = null, proof = null, selected = null, localGeneration = 0, cloudGeneration = 0, proofGeneration = 0;
  const currentTicket = generation => ({ revision, generation, cobolSource: source('cobol'), javaSource: source('java') });
  const findings = () => [
    ...(localReview?.findings ?? []),
    ...(variant === 'original' ? [{ ...evidence.finding, findingId: 'replay', evidenceStatus: 'CONFIRMED_REPLAY', candidateInputs: [] }] : []),
    ...(cloudReview?.findings ?? []),
  ];
  function notice(message) { $('notice').textContent = message; $('notice').classList.toggle('hidden', !message); }
  function requestPair() { return { moduleName: example?.moduleName ?? 'EDITOR-PAIR', cobolSource: source('cobol'), javaSource: source('java'), cobolSourceFormat: example?.cobolSourceFormat ?? 'FREE' }; }
  function editor(language) {
    const pre = $(`${language}-highlight`); pre.replaceChildren(); const items = findings();
    source(language).split('\n').forEach((text, index) => {
      const line = node('span', 'code-line'); line.dataset.line = String(index + 1);
      const matches = items.filter(item => { const span = item[`${language}Lines`]; return span && index + 1 >= span.start && index + 1 <= span.end; });
      const decoration = findingDecoration(matches);
      if (decoration) { line.classList.add(decoration.className); line.dataset.marker = decoration.marker; }
      if (selected && matches.some(item => item.findingId === selected)) line.classList.add('selected');
      for (const token of tokenizeSource(text, language)) line.append(node('span', token.kind ? `token-${token.kind}` : '', token.text));
      if (!text) line.append(document.createTextNode(' ')); pre.append(line);
    });
    $(`${language}-position`).textContent = `${source(language).split('\n').length} lines`; syncScroll(language);
  }
  function syncScroll(language) { const area = $(`${language}-source`); $(`${language}-highlight`).style.transform = `translate(${-area.scrollLeft}px, ${-area.scrollTop}px)`; }
  function selectFinding(finding, { revealWorkspace = false } = {}) {
    selected = finding.findingId; renderFindings(); editor('cobol'); editor('java');
    for (const language of ['cobol', 'java']) {
      const span = finding[`${language}Lines`]; if (!span) continue;
      const area = $(`${language}-source`), offsets = spanOffsets(area.value, span);
      area.setSelectionRange(offsets.start, offsets.end); area.scrollTop = Math.max(0, (span.start - 4) * 23); area.scrollLeft = 0; syncScroll(language);
    }
    $('java-anchor-label').textContent = finding.javaLines ? `Selected: lines ${finding.javaLines.start}–${finding.javaLines.end}` : 'Finding is anchored to COBOL';
    if (revealWorkspace) $('workspace').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function renderFindings() {
    const list = $('finding-list'); list.replaceChildren(); const items = findings(); $('finding-count').textContent = String(items.length);
    $('review-status').textContent = localReview ? 'LOCAL MODEL + INDEPENDENT EVIDENCE' : variant === 'original' ? 'RECORDED REPLAY · MODEL NOT RUN' : 'SOURCE-BOUND FINDINGS';
    for (const finding of items) {
      const article = node('article', `finding${selected === finding.findingId ? ' selected' : ''}`);
      const button = node('button', 'finding-button'); button.type = 'button'; button.setAttribute('aria-label', `Locate finding: ${finding.title}`);
      button.append(node('span', 'finding-icon', finding.evidenceStatus === 'MODEL_HYPOTHESIS' ? 'M' : '!'));
      const text = node('span'); text.append(node('span', 'finding-title', finding.title));
      const badges = node('span', 'finding-badges'); badges.append(node('span', `badge${finding.evidenceStatus !== 'CONFIRMED_REPLAY' ? ' ai' : ''}`, finding.evidenceStatus.replaceAll('_', ' ')));
      const spans = ['cobol', 'java'].flatMap(language => finding[`${language}Lines`] ? [`${language === 'java' ? 'Java' : 'COBOL'} ${finding[`${language}Lines`].start}–${finding[`${language}Lines`].end}`] : []);
      badges.append(node('span', 'span-link', spans.join(' · ')));
      if (Number.isFinite(finding.score)) badges.append(node('span', 'span-link', `Score ${finding.score.toFixed(3)} · uncalibrated`));
      text.append(badges); button.append(text); button.addEventListener('click', () => selectFinding(finding, { revealWorkspace: true })); article.append(button);
      const body = node('div', 'finding-body'); body.append(node('p', '', finding.explanation));
      if (finding.suggestedFix) { const fix = node('div', 'finding-correction'); fix.append(node('strong', '', 'REVIEW SUGGESTION'), node('p', '', finding.suggestedFix)); body.append(fix); }
      for (const input of finding.candidateInputs ?? []) body.append(node('code', 'candidate-input', input.inputsJson), node('span', 'not-executed', 'PROPOSED INPUT · NOT EXECUTED'), node('p', '', input.rationale));
      article.append(body); list.append(article);
    }
    if (!items.length) list.append(node('p', 'empty', localReview?.status === 'ANALYZED' ? 'No defect signal was flagged. This is not evidence of equivalence. Inspect the independent checks and limitations.' : variant === 'patched' ? 'The reviewed correction is loaded. Run the local model to compare its prediction, then inspect the recorded matching witness.' : 'Run the local defect model on the current source pair. Findings will point to exact code lines.'));
    const summary = $('ai-summary'); summary.replaceChildren(); summary.classList.toggle('hidden', !localReview && !cloudReview);
    for (const [label, review] of [['LOCAL MODEL', localReview], ['OPTIONAL CLOUD REVIEW', cloudReview]]) {
      if (!review) continue; summary.append(node('p', '', `${label} · ${review.status.replaceAll('_', ' ')}`), node('p', '', review.summary));
      if (review.status === 'ANALYZED' && review.risk) summary.append(node('p', 'risk-score', `${review.risk.decision.replaceAll('_', ' ')} · score ${review.risk.score.toFixed(3)} / threshold ${review.risk.threshold.toFixed(3)} · not a calibrated probability`));
      for (const limitation of review.limitations) summary.append(node('p', '', limitation));
    }
  }
  function renderWitness() {
    const container = $('witness-content'); container.replaceChildren();
    $('evidence-title').textContent = example?.exampleId === 'signed-balance' ? 'A sign changes the result.' : 'A penny is behavior.';
    if (!variant) { container.append(node('p', 'empty', 'Your edits have no source-bound runtime replay. Reload an example to inspect its recorded execution; running the local model does not execute code.')); $('evidence-description').textContent = 'Recorded replay hidden because the current source bytes changed.'; return; }
    $('evidence-description').textContent = variant === 'original' ? 'CONFIRMED REPLAY · These exact COBOL and Java sources produced different outputs in an offline execution.' : 'RECORDED MATCH · This exact reviewed correction matched COBOL for the displayed input only.';
    const row = node('div', 'input-row');
    for (const [label, value] of Object.entries(evidence.witness.inputs)) { const field = node('div', 'input-field'); field.append(node('span', '', label.toUpperCase()), node('strong', '', value)); row.append(field); }
    container.append(row); const outputs = node('div', 'output-row');
    for (const [label, value, bad] of [['COBOL OUTPUT', evidence.witness.outputs.cobol, false], [variant === 'original' ? 'JAVA OUTPUT' : 'CORRECTED JAVA OUTPUT', variant === 'original' ? evidence.witness.outputs.java : evidence.witness.outputs.patchedJava, variant === 'original']]) {
      if (outputs.childNodes.length) outputs.append(node('span', 'output-arrow', variant === 'original' ? '≠' : '='));
      const box = node('div', `output-box${bad ? ' bad' : ''}`); box.append(node('span', '', label), node('strong', '', value)); outputs.append(box);
    }
    container.append(outputs, node('p', 'witness-note', variant === 'patched' ? 'The reviewed Java candidate matched COBOL for this exact recorded input. A finite matching example does not prove general equivalence.' : evidence.note ?? 'Recorded replay is independent of AI findings.'));
    container.append(node('p', 'evidence-source', `Executed: ${evidence.toolVersions.cobol}; ${evidence.toolVersions.java}. Source hashes are checked before displaying this evidence.`));
    const details = node('details', 'evidence-source'); details.append(node('summary', '', 'Inspect replay provenance and limits'));
    for (const limitation of evidence.limitations ?? []) details.append(node('p', '', limitation));
    details.append(node('p', '', `Recorded: ${evidence.checkedAtUtc}`), node('p', '', `Replay: ${evidence.reproduction}`), node('p', '', `COBOL SHA-256: ${evidence.sourceHashes.cobol}`), node('p', '', `Java SHA-256: ${variant === 'original' ? evidence.sourceHashes.java : evidence.sourceHashes.patchedJava}`)); container.append(details);
  }
  function renderProof() {
    const badge = $('proof-badge'); badge.className = 'verification-badge'; const details = $('proof-details'); details.replaceChildren();
    if (!proof) { badge.textContent = example?.proofInputs ? 'NOT RUN' : 'UNSUPPORTED'; $('proof-summary').textContent = example?.proofInputs ? 'Run Z3 on the current source pair with this example’s recorded finite mapping. AI findings never count as a formal proof.' : 'This stdin-based program is outside the current Z3 financial-scalar subset. Its formal result is UNKNOWN; use the recorded runtime witness and review the model’s hypotheses. Select the FX example to exercise the supported Z3 flow.'; return; }
    const status = proof.formalProofStatus;
    badge.textContent = status === 'SAT_COUNTEREXAMPLE_FOUND' ? 'MISMATCH FOUND' : status === 'UNSAT_PROVEN_SAFE' ? 'EQUIVALENT IN SCOPE' : 'UNKNOWN';
    if (status === 'SAT_COUNTEREXAMPLE_FOUND') badge.classList.add('sat'); if (status === 'UNSAT_PROVEN_SAFE') badge.classList.add('unsat');
    $('proof-summary').textContent = status === 'UNSAT_PROVEN_SAFE' ? 'Z3 found no differing result in the recorded finite input domain. This applies only to the exact current sources and scope below.' : status === 'SAT_COUNTEREXAMPLE_FOUND' ? 'Z3 found a concrete input for which COBOL and Java produce different stored results.' : 'The verifier could not establish equivalence. UNKNOWN is not a pass.';
    if (proof.counterexamplesJson.length) details.append(node('pre', 'proof-witness', JSON.stringify(proof.counterexamplesJson, null, 2)));
    const scope = proof.proofScope, info = node('div', 'proof-scope');
    if (scope?.rate) info.append(node('span', '', `Fixed rate ${scope.rate.rate} · ${scope.rate.currencyPair}`));
    if (scope?.inputAmountCents) info.append(node('span', '', `Amount bounds ${scope.inputAmountCents.min}…${scope.inputAmountCents.max} cents`));
    if (scope?.solver) info.append(node('span', '', `${scope.solver.name} ${scope.solver.version} · ${scope.solver.result}`)); details.append(info);
    if (proof.fStringSummary) details.append(node('p', 'empty', proof.fStringSummary));
  }
  function render() {
    editor('cobol'); editor('java'); renderFindings(); renderWitness(); renderProof();
    $('java-variant').textContent = variant === 'patched' ? 'REVIEWED CORRECTION' : 'CANDIDATE';
    $('pair-state').textContent = variant === 'original' ? 'Synthetic example · recorded mismatch · local model not yet run' : variant === 'patched' ? 'Reviewed correction loaded · run the local model' : 'Edited pair · earlier evidence cleared';
    if (localReview?.status === 'ANALYZED') $('pair-state').textContent = `Local model: ${localReview.risk.decision.replaceAll('_', ' ').toLowerCase()} · exact current sources`;
    $('variant-select').value = variant === 'patched' ? 'correct' : variant === 'original' ? 'defective' : 'edited'; $('fix-description').textContent = example?.correctionDescription ?? '';
    $('verify').textContent = example?.proofInputs ? 'Run Z3 check ↗' : 'Explain Z3 scope ↗';
  }
  function resetResults() { revision++; localGeneration++; cloudGeneration++; proofGeneration++; localReview = null; cloudReview = null; proof = null; selected = null; variant = null; for (const id of ['analyze', 'cloud-analyze', 'verify']) $(id).disabled = false; $('analyze').textContent = 'Run local defect model ✦'; $('cloud-analyze').textContent = 'Optional cloud review ↗'; }
  function changed() { resetResults(); render(); notice('Source changed. Model findings, recorded replay and verification results were cleared. Run the local model again.'); }
  async function loadExample(id = $('example-select').value, correct = false) {
    const item = examples.find(item => item.example.exampleId === id); if (!item) return;
    resetResults(); example = item.example; evidence = item.evidence; $('example-select').value = id;
    $('cobol-source').value = example.cobolSource; $('java-source').value = correct ? example.patchedJavaSource : example.javaSource; $('module-name').textContent = example.moduleName;
    const expected = revision, next = await evidenceVariant(evidence, source('cobol'), source('java')); if (expected !== revision) return;
    variant = next; selected = next === 'original' ? 'replay' : null; for (const lang of ['cobol', 'java']) $(`${lang}-source`).scrollTop = 0;
    render(); notice(example.description); if (variant === 'original') selectFinding(findings().find(item => item.findingId === 'replay'));
  }
  async function post(path, payload) {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(115000) });
    let result; try { result = await response.json(); } catch { throw new Error('The local API returned an unreadable response.'); }
    if (!response.ok) throw new Error(typeof result.message === 'string' ? result.message : Array.isArray(result.message) ? result.message.join(' ') : `API request failed (${response.status}).`); return result;
  }
  function showModelMetadata(model) {
    const container = $('model-metadata'); container.replaceChildren(); if (!model) return;
    container.append(node('strong', '', model.name), node('p', '', `Trained locally on ${model.trainingFamilyCount ?? 6} synthetic families. Pair-only predictions; no provider API required.`));
    const finalTest = auditedEvaluation?.modelSha256 === model.sha256 && auditedEvaluation?.datasetSha256 === model.datasetSha256 ? auditedEvaluation : null;
    $('model-evaluation').textContent = finalTest ? `Final test: ${finalTest.correct}/${finalTest.pairs} correct · ${finalTest.accuracy <= .5 ? 'failed held-out evaluation' : 'synthetic pilot only'}` : 'Experimental · evaluation unavailable';
    if (finalTest && Number.isFinite(finalTest.accuracy)) {
      const result = node('div', `test-result${finalTest.accuracy <= .5 ? ' poor' : ''}`);
      result.append(node('strong', '', 'FROZEN FINAL TEST · HELD-OUT FAMILIES'));
      const metrics = node('div', 'metric-row');
      for (const [label, value] of [['Accuracy', finalTest.accuracy], ['Precision', finalTest.precision], ['Recall', finalTest.recall], ['F1', finalTest.f1]]) {
        if (!Number.isFinite(value)) continue;
        const metric = node('div'); metric.append(node('span', '', label), node('strong', '', `${(value * 100).toFixed(1)}%`)); metrics.append(metric);
      }
      result.append(metrics, node('p', '', `${finalTest.correct ?? '?'} of ${finalTest.pairs ?? finalTest.testPairs ?? '?'} pairs classified correctly across ${Array.isArray(finalTest.testFamilies) ? finalTest.testFamilies.length : 2} test families.`));
      if (finalTest.accuracy <= .5) result.append(node('p', 'evaluation-warning', 'Experimental — failed held-out evaluation; human review required. The working training example demonstrates the workflow, not reliable defect detection.'));
      if (finalTest.confusion) result.append(node('p', '', `${finalTest.confusion.falsePositive} false positives · ${finalTest.confusion.falseNegative} missed defects.`));
      const baseline = finalTest.baseline?.constantNoDefect?.accuracy;
      if (Number.isFinite(baseline)) result.append(node('p', '', `Always predicting no defect achieves ${(baseline * 100).toFixed(1)}% accuracy on the same test set.`));
      container.append(result);
    }
    if (auditedEvaluation && !finalTest) container.append(node('p', 'evaluation-warning', 'The recorded final evaluation belongs to a different model. Its metrics are hidden until the model hash matches.'));
    if (!auditedEvaluation) container.append(node('p', 'evaluation-warning', 'Final evaluation report unavailable. The training example cannot establish model quality.'));
    const details = node('details'); details.append(node('summary', '', 'Model evaluation and provenance'));
    details.append(node('p', '', 'Small synthetic feasibility experiment. Held-out results do not establish reliable real-world or unseen-company accuracy. Scores are uncalibrated; a low score is not proof of equivalence.'));
    if (finalTest) details.append(node('pre', 'metrics-json', JSON.stringify(finalTest, null, 2)));
    if (model.evaluation) details.append(node('pre', 'metrics-json', JSON.stringify(model.evaluation, null, 2)));
    details.append(node('p', '', `Model SHA-256: ${model.sha256}`), node('p', '', `Dataset SHA-256: ${model.datasetSha256}`)); container.append(details);
  }
  $('analyze').addEventListener('click', async () => {
    const ticket = currentTicket(++localGeneration), request = requestPair(); $('analyze').disabled = true; $('analyze').textContent = 'Running local model…'; notice('The trained local model is examining this exact pair. No LLM or cloud API is called.');
    try {
      const result = await validateLocalReview(await post('/api/defect-reviews', request), request);
      if (!isCurrentResponse(ticket, currentTicket(localGeneration))) return;
      localReview = { ...result, findings: result.findings.map(item => ({ ...item, findingId: `local-${item.findingId}` })) }; selected = localReview.findings[0]?.findingId ?? (variant === 'original' ? 'replay' : null); render();
      if (result.model) showModelMetadata(result.model);
      notice(result.status === 'ANALYZED' ? `Local model complete: ${result.findings.length} suspected location${result.findings.length === 1 ? '' : 's'}. Model hypotheses and confirmed runtime replay are displayed separately.` : result.summary);
      if (localReview.findings.length) selectFinding(localReview.findings[0]);
    } catch (error) { if (isCurrentResponse(ticket, currentTicket(localGeneration))) notice(error.message); }
    finally { if (ticket.generation === localGeneration) { $('analyze').disabled = false; $('analyze').textContent = 'Run local defect model ✦'; } }
  });
  $('cloud-analyze').addEventListener('click', async () => {
    const ticket = currentTicket(++cloudGeneration), request = requestPair(); $('cloud-analyze').disabled = true; $('cloud-analyze').textContent = 'Requesting cloud review…'; notice('You requested an optional cloud review. This action sends the current source pair to the server-configured LLM provider.');
    try { const result = await validateReview(await post('/api/ai-reviews', request), request); if (!isCurrentResponse(ticket, currentTicket(cloudGeneration))) return; cloudReview = { ...result, findings: result.findings.map(item => ({ ...item, findingId: `cloud-${item.findingId}` })) }; render(); notice(result.summary); if (cloudReview.findings.length) selectFinding(cloudReview.findings[0]); }
    catch (error) { if (isCurrentResponse(ticket, currentTicket(cloudGeneration))) notice(error.message); }
    finally { if (ticket.generation === cloudGeneration) { $('cloud-analyze').disabled = false; $('cloud-analyze').textContent = 'Optional cloud review ↗'; } }
  });
  $('verify').addEventListener('click', async () => {
    if (!example?.proofInputs) { renderProof(); notice('Z3 returns UNKNOWN for this program shape. The signed-balance replay remains real execution evidence; choose the FX example for a supported scoped Z3 check.'); $('verification').scrollIntoView({ behavior: 'smooth', block: 'center' }); return; }
    const ticket = currentTicket(++proofGeneration), request = { moduleName: example.moduleName, category: example.category, cobolSource: source('cobol'), javaSource: source('java'), proofInputs: example.proofInputs };
    $('verify').disabled = true; $('verify').textContent = 'Running Z3…'; notice('Running Z3 with the FX example’s recorded mapping, finite amount bounds and fixed rate.');
    try { const result = await validateProof(await post('/api/verifications', request), request); if (!isCurrentResponse(ticket, currentTicket(proofGeneration))) return; proof = result; renderProof(); notice('Z3 complete for the exact current pair. Inspect the recorded scope.'); $('verification').scrollIntoView({ behavior: 'smooth', block: 'center' }); }
    catch (error) { if (isCurrentResponse(ticket, currentTicket(proofGeneration))) notice(error.message); }
    finally { if (ticket.generation === proofGeneration) { $('verify').disabled = false; $('verify').textContent = 'Run Z3 check ↗'; } }
  });
  $('load-example').addEventListener('click', () => void loadExample()); $('example-select').addEventListener('change', () => void loadExample());
  $('variant-select').addEventListener('change', () => void loadExample($('example-select').value, $('variant-select').value === 'correct'));
  $('use-fix').addEventListener('click', async () => { await loadExample($('example-select').value, true); notice('The reviewed correction is loaded. It is a prewritten example, not an automatic model repair. Run the local model to compare its finding.'); $('workspace').scrollIntoView({ behavior: 'smooth', block: 'start' }); });
  for (const language of ['cobol', 'java']) {
    const area = $(`${language}-source`); area.addEventListener('input', changed); area.addEventListener('scroll', () => syncScroll(language));
    area.addEventListener('keydown', event => { if (event.key === 'Tab') { event.preventDefault(); area.setRangeText('    ', area.selectionStart, area.selectionEnd, 'end'); changed(); } });
  }
  try {
    const response = await fetch('/examples'); if (!response.ok) throw new Error('Source examples could not be loaded.'); const data = await response.json(); examples = data.examples;
    for (const { example: item } of examples) { const option = node('option', '', item.label); option.value = item.exampleId; $('example-select').append(option); }
    await loadExample(data.defaultExampleId);
  } catch (error) { notice(error.message); for (const id of ['analyze', 'cloud-analyze', 'verify', 'use-fix', 'load-example', 'example-select', 'variant-select']) $(id).disabled = true; }
  try {
    const response = await fetch('/evaluation'); if (!response.ok) throw new Error(); const report = await response.json();
    if (report.status === 'COMPLETED' && /^[a-f0-9]{64}$/.test(report.modelSha256) && /^[a-f0-9]{64}$/.test(report.datasetSha256) && /^[a-f0-9]{64}$/.test(report.reportSha256)) auditedEvaluation = report;
  } catch { $('model-metadata').textContent = 'Final evaluation report unavailable; do not infer model quality from the training example.'; }
  try {
    const response = await fetch('/api/defect-reviews/status'); if (!response.ok) throw new Error(); const status = await response.json();
    $('model-status').textContent = status.configured ? `Local trained model ready · ${status.model?.name ?? 'paired defect model'}` : 'Local defect model not configured'; $('model-dot').classList.toggle('configured', status.configured); showModelMetadata(status.model);
  } catch { $('model-status').textContent = 'Local model status unavailable · start the backend'; }
  $('cloud-status').textContent = 'Cloud configuration is checked only when you request this separate action. The local defect model works without an API key.';
}
