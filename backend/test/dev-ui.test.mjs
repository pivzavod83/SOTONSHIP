import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { tokenizeSource, sourceHash, evidenceVariant, validateLocalReview, validateReview, spanOffsets, isCurrentResponse, findingDecoration } from '../dev-ui/app.js';
import { createWorkbenchServer, loadExamples, loadEvaluation } from '../dev-ui/serve.mjs';

const start = async server => { server.listen(0, '127.0.0.1'); await once(server, 'listening'); return `http://127.0.0.1:${server.address().port}`; };
const close = server => new Promise(resolve => server.close(resolve));
const request = { cobolSource: '01 RESULT PIC S9(6).\nCOMPUTE RESULT = A - B', javaSource: 'int result = Math.abs(a - b);', cobolSourceFormat: 'FREE' };
async function validResult() {
  return { status: 'ANALYZED', engineVersion: 'paired-defect-v1', aiIsProof: false, counterexamplesExecuted: false,
    sourceHashes: { cobol: await sourceHash(request.cobolSource), java: await sourceHash(request.javaSource) },
    summary: 'Review signed result.', limitations: ['Synthetic feasibility only.'], model: { name: 'test-fixture', sha256: 'a'.repeat(64), datasetSha256: 'b'.repeat(64) },
    risk: { score: .9, threshold: .5, decision: 'REVIEW_REQUIRED', calibrated: false },
    findings: [{ findingId: 'F1', evidenceStatus: 'MODEL_HYPOTHESIS', category: 'SEMANTIC_DIFFERENCE', title: 'Sign', explanation: 'Review abs.', suggestedFix: 'Preserve signed result.', score: .9,
      cobolLines: { start: 2, end: 2 }, javaLines: { start: 1, end: 1 }, cobolExcerpt: 'COMPUTE RESULT = A - B', javaExcerpt: request.javaSource, candidateInputs: [] }] };
}
test('syntax highlighting preserves exact program text including HTML-shaped literals', () => {
  for (const language of ['cobol', 'java']) {
    const samples = language === 'java' ? ['long x = Long.parseLong("<script>&"); // no markup\n', 'String s = "\\\"";\nif (x < 0) x = Math.abs(x);'] : ['PERFORM UNTIL X > 9\n MOVE FUNCTION ABS(X) TO Y\nEND-PERFORM', 'DISPLAY "<img src=x>" *> & comment'];
    for (const source of samples) assert.equal(tokenizeSource(source, language).map(token => token.text).join(''), source);
  }
  assert.ok(tokenizeSource('long x = Long.parseLong("3");', 'java').some(token => token.kind === 'type' && token.text === 'Long'));
  assert.ok(tokenizeSource('PERFORM UNTIL X = 0', 'cobol').some(token => token.kind === 'keyword' && token.text === 'PERFORM'));
});
test('source hashes use exact bytes and replay disappears after any edit', async () => {
  const { examples } = await loadExamples();
  assert.equal(examples[0].example.exampleId, 'signed-balance');
  const { example, evidence } = examples[0];
  assert.deepEqual(evidence.witness.outputs, { cobol: '-100', java: '100', patchedJava: '-100' });
  assert.equal(await evidenceVariant(evidence, example.cobolSource, example.javaSource), 'original');
  assert.equal(await evidenceVariant(evidence, example.cobolSource, example.patchedJavaSource), 'patched');
  assert.equal(await evidenceVariant(evidence, `${example.cobolSource}\n`, example.javaSource), null);
  assert.equal(await evidenceVariant(evidence, example.cobolSource, `${example.javaSource} `), null);
});
test('public final evaluation is hash-bound and excludes held-out code, labels and individual predictions', async () => {
  const result = await loadEvaluation();
  assert.equal(result.correct, 1); assert.equal(result.pairs, 8); assert.equal(result.accuracy, .125);
  assert.equal(result.confusion.falsePositive, 4); assert.equal(result.confusion.falseNegative, 3);
  assert.equal(result.baseline.constantNoDefect.accuracy, .5);
  assert.match(result.modelSha256, /^[a-f0-9]{64}$/); assert.match(result.reportSha256, /^[a-f0-9]{64}$/);
  assert.equal(result.predictions, undefined); assert.equal(result.cobolSource, undefined); assert.equal(result.javaSource, undefined);
});
test('inclusive line spans select exact text without adjacent statements', () => {
  const code = 'first\n  second();\n  third();\nlast';
  const range = spanOffsets(code, { start: 2, end: 3 });
  assert.equal(code.slice(range.start, range.end), '  second();\n  third();');
  assert.throws(() => spanOffsets(code, { start: 0, end: 2 }));
  assert.throws(() => spanOffsets(code, { start: 2, end: 9 }));
});
test('stale async responses are rejected after edit, reload, or newer run', () => {
  const ticket = { revision: 1, generation: 1, cobolSource: 'c', javaSource: 'j' };
  assert.equal(isCurrentResponse(ticket, { ...ticket }), true);
  for (const difference of [{ revision: 2 }, { generation: 2 }, { cobolSource: 'edited' }, { javaSource: 'edited' }]) assert.equal(isCurrentResponse(ticket, { ...ticket, ...difference }), false);
});
test('confirmed replay keeps its red class and ! marker when model hypotheses overlap', () => {
  const replay = { evidenceStatus: 'CONFIRMED_REPLAY' }, model = { evidenceStatus: 'MODEL_HYPOTHESIS' };
  assert.deepEqual(findingDecoration([model, replay]), { className: 'flag-confirmed', marker: '!' });
  assert.deepEqual(findingDecoration([replay, model]), { className: 'flag-confirmed', marker: '!' });
  assert.deepEqual(findingDecoration([model]), { className: 'flag-hypothesis', marker: 'M' });
  assert.equal(findingDecoration([]), null);
});
test('local review rejects mismatched hashes, invented spans, fake execution, and invalid scores', async () => {
  assert.equal((await validateLocalReview(await validResult(), request)).findings.length, 1);
  for (const change of [result => result.sourceHashes.java = 'f'.repeat(64), result => result.findings[0].javaLines.end = 20, result => result.findings[0].javaExcerpt = 'invented', result => result.findings[0].evidenceStatus = 'CONFIRMED_REPLAY', result => result.counterexamplesExecuted = true, result => result.risk.score = NaN, result => result.risk.decision = 'NO_DEFECT_SIGNAL', result => result.findings.push(result.findings[0])]) {
    const result = await validResult(); change(result); await assert.rejects(validateLocalReview(result, request));
  }
});
test('unavailable or unsupported local model cannot claim findings; cloud output cannot masquerade as local output', async () => {
  for (const status of ['NOT_CONFIGURED', 'UNSUPPORTED']) {
    const result = await validResult(); result.status = status; result.findings = []; result.risk = null; result.model = null;
    assert.equal((await validateLocalReview(result, request)).status, status);
    result.findings = (await validResult()).findings; await assert.rejects(validateLocalReview(result, request));
  }
  await assert.rejects(validateReview(await validResult(), request));
});
test('workbench exposes only loopback static/examples and narrow JSON proxy routes', async () => {
  const forwarded = [];
  const backend = createServer(async (req, res) => { let body = ''; for await (const chunk of req) body += chunk; forwarded.push({ path: req.url, method: req.method, body }); res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ received: true })); });
  const backendOrigin = await start(backend), ui = createWorkbenchServer({ backendOrigin }), origin = await start(ui);
  try {
    const page = await fetch(origin); assert.equal(page.status, 200); assert.match(await page.text(), /Run local defect model/);
    const examples = await (await fetch(`${origin}/examples`)).json(); assert.equal(examples.examples[0].example.exampleId, 'signed-balance');
    const response = await fetch(`${origin}/api/defect-reviews`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) }); assert.equal(response.status, 200);
    assert.deepEqual(forwarded[0], { path: '/api/defect-reviews', method: 'POST', body: JSON.stringify(request) });
    for (const route of ['/api/anything', '/.env', '/app.js?file=../../.env', '/api/defect-reviews?api_key=secret']) assert.equal((await fetch(`${origin}${route}`)).status, 404);
    assert.equal((await fetch(`${origin}/api/defect-reviews`, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: 'https://example.com' }, body: '{}' })).status, 403);
    assert.equal((await fetch(`${origin}/api/defect-reviews`, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: '{}' })).status, 415);
    assert.equal(forwarded.length, 1);
    assert.throws(() => createWorkbenchServer({ backendOrigin: 'https://example.com' }), /loopback/);
  } finally { await close(ui); await close(backend); }
});
