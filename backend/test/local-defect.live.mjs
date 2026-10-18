import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const base = (process.env.API_URL ?? 'http://127.0.0.1:3003').replace(/\/$/, '');
const dataset = JSON.parse(await readFile(new URL('../../ml-engine/evaluation/synthetic-pilot/pilot-10-r3/dataset.json', import.meta.url), 'utf8'));
const family = dataset.families.find(item => item.familyId === 'F006');
const hash = value => createHash('sha256').update(value, 'utf8').digest('hex');
const sources = variantId => ({ moduleName: 'LOCAL-DEFECT-SMOKE', cobolSourceFormat: 'FREE', cobolSource: family.cobolLines.join('\n'), javaSource: family.variants.find(item => item.variantId === variantId).javaLines.join('\n') });
const statusResponse = await fetch(`${base}/api/defect-reviews/status`);
assert.equal(statusResponse.status, 200);
const status = await statusResponse.json();
assert.equal(status.configured, true, 'A trained model must actually be loaded');

function checkResult(result, request) {
  assert.equal(result.status, 'ANALYZED');
  assert.equal(result.aiIsProof, false);
  assert.equal(result.counterexamplesExecuted, false);
  assert.equal(result.engineVersion, 'paired-defect-v1');
  assert.equal(result.sourceHashes.cobol, hash(request.cobolSource));
  assert.equal(result.sourceHashes.java, hash(request.javaSource));
  assert.ok(Number.isFinite(result.risk.score) && result.risk.score >= 0 && result.risk.score <= 1);
  assert.equal(result.risk.calibrated, false);
  assert.equal(result.risk.decision, result.risk.score >= result.risk.threshold ? 'REVIEW_REQUIRED' : 'NO_DEFECT_SIGNAL');
  assert.match(result.model.sha256, /^[a-f0-9]{64}$/);
  assert.equal(result.model.trainingFamilyCount, 6);
  for (const finding of result.findings) {
    assert.equal(finding.evidenceStatus, 'MODEL_HYPOTHESIS');
    assert.ok(finding.cobolLines || finding.javaLines);
    for (const language of ['cobol', 'java']) {
      const span = finding[`${language}Lines`], excerpt = finding[`${language}Excerpt`];
      if (!span) { assert.equal(excerpt, ''); continue; }
      const lines = request[`${language}Source`].split('\n');
      assert.ok(Number.isSafeInteger(span.start) && Number.isSafeInteger(span.end) && span.start >= 1 && span.end >= span.start && span.end <= lines.length);
      assert.equal(excerpt, lines.slice(span.start - 1, span.end).join('\n'));
    }
  }
}
async function analyze(request) {
  const response = await fetch(`${base}/api/defect-reviews`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) });
  assert.equal(response.status, 200, await response.clone().text());
  const result = await response.json(); checkResult(result, request); return result;
}
const badRequest = sources('F006-V4');
const bad = await analyze(badRequest);
const good = await analyze(sources('F006-V2'));
const renamed = await analyze({ ...badRequest, moduleName: 'UNRELATED-NAME' });
assert.equal(renamed.risk.score, bad.risk.score, 'Display names must not be model features');
assert.equal(renamed.model.sha256, bad.model.sha256);
const changedRequest = { ...badRequest, javaSource: `\n${badRequest.javaSource}` };
const changed = await analyze(changedRequest);
assert.notEqual(changed.sourceHashes.java, bad.sourceHashes.java);
const invalid = await fetch(`${base}/api/defect-reviews`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...badRequest, javaSource: '' }) });
assert.equal(invalid.status, 400);
console.log(JSON.stringify({ status: 'PASS', badScore: bad.risk.score, correctScore: good.risk.score, badDecision: bad.risk.decision, findings: bad.findings.map(item => ({ javaLines: item.javaLines, cobolLines: item.cobolLines, title: item.title })), editBoundToNewSource: true, modelSha256: bad.model.sha256 }, null, 2));
