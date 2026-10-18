/** Real HTTP -> CQRS -> Python paired-GNN smoke. No database writes or proof claims. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const base = (process.env.API_URL ?? 'http://127.0.0.1:3001').replace(/\/$/, '');
const fixture = async (name) => readFile(new URL(`../../ml-engine/data/fixtures/${name}`, import.meta.url), 'utf8');
const hash = (source) => createHash('sha256').update(source).digest('hex');
const [cobolSource, fxJava, cicsJava] = await Promise.all([
  fixture('FX-WIRE-CALC.cbl'), fixture('FX-WIRE-CALC.java.txt'), fixture('CICS-TERMINAL-IO.java.txt'),
]);
const candidates = [
  { candidateId: 'fx-java', moduleName: 'CandidateOne.java', javaSource: fxJava },
  { candidateId: 'cics-java', moduleName: 'CandidateTwo.java', javaSource: cicsJava },
];
let checks = 0;
async function match(body, status = 200) {
  const response = await fetch(`${base}/api/matches`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(120_000),
  });
  const output = await response.json();
  assert.equal(response.status, status, JSON.stringify(output));
  checks += 1;
  return output;
}

const result = await match({ cobolSource, candidates, topK: 2 });
assert.ok(['MATCH_SUGGESTED', 'REVIEW_REQUIRED'].includes(result.status));
assert.equal(result.matchingIsProof, false);
assert.equal(result.granularity, 'PROGRAM');
assert.equal(result.cobolSourceSha256, hash(cobolSource));
assert.match(result.model.sha256, /^[a-f0-9]{64}$/);
assert.match(result.model.trainingDataset, /COBOL.JavaTrans/i);
assert.equal(result.candidates.length, 2);
assert.equal(result.cobolSource, undefined);
assert.equal(result.formalProofStatus, undefined);
for (const [index, candidate] of result.candidates.entries()) {
  const source = candidates.find((entry) => entry.candidateId === candidate.candidateId);
  assert.ok(source);
  assert.equal(candidate.rank, index + 1);
  assert.equal(candidate.moduleName, source.moduleName);
  assert.equal(candidate.javaSourceSha256, hash(source.javaSource));
  assert.ok(Number.isFinite(candidate.similarity) && candidate.similarity >= -1 && candidate.similarity <= 1);
}
const top = await match({ cobolSource, candidates, topK: 1 });
assert.equal(top.candidates.length, 1);
assert.equal(top.candidates[0].candidateId, result.candidates[0].candidateId);
assert.equal(top.status, result.status, 'topK must not affect decision confidence');
const singleton = await match({ cobolSource, candidates: candidates.slice(0, 1) });
assert.equal(singleton.status, 'REVIEW_REQUIRED');
await match({ cobolSource, candidates: [candidates[0], candidates[0]] }, 400);
await match({ cobolSource, candidates, matchingIsProof: true }, 400);
console.log(`Matching real-engine HTTP smoke: ${checks} requests passed (${result.status}; scores are not equivalence evidence).`);
