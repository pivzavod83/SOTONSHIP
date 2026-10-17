/** Real HTTP + PostgreSQL + Python/Z3 integration; run against a disposable DB. */
import assert from 'node:assert/strict';

const base = (process.env.API_URL ?? 'http://localhost:3001').replace(/\/$/, '');
let checks = 0;
async function request(path, { status = 200, body, method = body ? 'POST' : 'GET' } = {}) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(90_000),
  });
  const text = await response.text();
  assert.ok([status].flat().includes(response.status), `${method} ${path}: expected ${status}, got ${response.status}: ${text}`);
  checks += 1;
  return text ? JSON.parse(text) : undefined;
}

const rows = await request('/api/verifications');
assert.ok(Array.isArray(rows) && rows.length >= 4, 'Seed four analyses first (npm run setup)');
assert.ok(rows.some(row => row.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND'));
assert.ok(rows.some(row => row.formalProofStatus === 'UNSAT_PROVEN_SAFE'));
assert.ok(rows.some(row => row.formalProofStatus === 'UNKNOWN_HALTED_LIMIT'));
const fxRow = rows.find(row => row.moduleName === 'FX-WIRE-CALC.cbl');
const limitRow = rows.find(row => row.moduleName === 'CICS-TERMINAL-IO.cbl');
assert.ok(fxRow && limitRow, 'Expected named seed cases');
const fx = await request(`/api/verifications/${fxRow.id}`);
assert.ok(fx.proofScope && fx.cpgGraphJson, 'Detail must retain scope and graph');
await request('/api/verifications/baseline-comparison');
const rates = await request('/api/fx-rates');
assert.ok(rates.length >= 3 && rates.every(rate => typeof rate.rate === 'string'), 'FX precision must survive JSON');
const boe = rates.find(rate => rate.currencyPair === 'GBP/EUR' && rate.source.includes('Bank of England'));
assert.equal(boe.observationDate, '2026-10-15');
assert.equal(boe.collectedDate, '2026-10-17');
assert.ok(rates.some(rate => rate.currencyPair === 'GBP/THB' && rate.source.includes('World Bank')),
  'Historical World Bank corridor rate must remain separately attributed');
const swagger = await request('/api/docs-json');
assert.ok(swagger.paths['/api/verifications']);
const config = await request('/api/generation/configuration');
assert.equal(config.adapterEnabled, false, 'Generation remains inactive until a real provider adapter is implemented');
assert.ok(!('apiKey' in config), 'Only configuration presence flags may leave the server');
await request('/api/verifications/not-a-uuid', { status: 400 });
await request('/api/verifications/00000000-0000-4000-8000-000000000000', { status: 404 });
await request('/api/verifications', { body: {}, status: 400 });

function sourceRequest(detail, moduleName) {
  return {
    moduleName,
    category: detail.category,
    cobolSource: detail.cobolSource,
    javaSource: detail.javaSource,
    patchedJavaSource: detail.patchedJavaSource,
  };
}

// New runs are persisted through CQRS, mapped through MikroORM, and proved by Python.
const run = await request('/api/verifications', {
  body: sourceRequest(fx, 'SMOKE-FX-WIRE.cbl'), status: 201,
});
assert.equal(run.analysisStale, false);
assert.equal(run.currentEngineVersion, run.provenanceJson.engineVersion);
assert.ok(run.cpgGraphJson.nodes.some(node => node.kind === 'method'), 'Java methods must be graph nodes');
assert.ok(run.cpgGraphJson.edges.some(edge => edge.kind === 'READS'), 'Graph must retain data reads');
const review = await request(`/api/verifications/${run.id}/review`);
assert.equal(review.humanReviewStatus, 'PENDING');
assert.equal(review.currentReport.disposition, 'NEEDS_REVIEW');
assert.ok(review.currentReport.witnesses.length > 0);
const initialHistory = await request(`/api/verifications/${run.id}/history`);
assert.deepEqual(initialHistory.map(revision => revision.version), [1]);
assert.equal(run.formalProofStatus, fx.formalProofStatus);
assert.equal(run.proofScope.rate.observationDate, '2026-10-15', 'Observation date must survive database-to-engine round trip');
if (run.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND') {
  assert.ok(run.counterexamplesJson.length > 0, 'SAT must include a witness');
  assert.notEqual(run.counterexamplesJson[0].pennyDrift, '0.00');
}
assert.equal((await request(`/api/verifications/${run.id}`)).javaSource, fx.javaSource);
// Candidate analysis is distinct from the proof of the currently stored Java.
const candidate = await request(`/api/verifications/${run.id}/candidates`, { body: { javaSource: fx.patchedJavaSource }, status: 201 });
assert.equal(candidate.javaSource, fx.javaSource);
assert.equal(candidate.formalProofStatus, 'SAT_COUNTEREXAMPLE_FOUND');
assert.equal(candidate.provenanceJson.candidateReview.analysis.formalProofStatus, 'UNSAT_PROVEN_SAFE');
const patched = await request(`/api/verifications/${run.id}/apply-patch`, { method: 'POST', status: [200, 201] });
assert.equal(patched.formalProofStatus, 'UNSAT_PROVEN_SAFE');
assert.equal(patched.javaSource, fx.patchedJavaSource);
assert.deepEqual(patched.counterexamplesJson, []);
assert.equal((await request(`/api/verifications/${run.id}`)).javaSource, fx.patchedJavaSource);
const reverified = await request(`/api/verifications/${run.id}/reverify`, { method: 'POST', status: 201 });
assert.equal(reverified.formalProofStatus, 'UNSAT_PROVEN_SAFE');
assert.ok(reverified.version > patched.version);
const history = await request(`/api/verifications/${run.id}/history`);
assert.deepEqual(history.map(revision => revision.version), [1, 2, 3, 4]);
assert.equal(history[0].snapshot.javaSource, fx.javaSource);
assert.equal(history[2].snapshot.javaSource, fx.patchedJavaSource);

// A fabricated patch that is still the buggy Java must be rejected without mutation.
if (fx.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND') {
  const badPatch = await request('/api/verifications', {
    body: { ...sourceRequest(fx, 'SMOKE-UNSAFE-PATCH.cbl'), patchedJavaSource: fx.javaSource }, status: 201,
  });
  await request(`/api/verifications/${badPatch.id}/apply-patch`, { method: 'POST', status: [409, 422] });
  const badCandidate = await request(`/api/verifications/${badPatch.id}/candidates`, { body: { javaSource: fx.javaSource }, status: 201 });
  assert.equal(badCandidate.provenanceJson.candidateReview.analysis.formalProofStatus, 'SAT_COUNTEREXAMPLE_FOUND');
  await request(`/api/verifications/${badPatch.id}/apply-patch`, { method: 'POST', status: 422 });
  const unchanged = await request(`/api/verifications/${badPatch.id}`);
  assert.equal(unchanged.javaSource, fx.javaSource);
  assert.equal(unchanged.formalProofStatus, 'SAT_COUNTEREXAMPLE_FOUND');
}

const limit = await request(`/api/verifications/${limitRow.id}`);
const unknown = await request('/api/verifications', {
  body: sourceRequest(limit, 'SMOKE-CICS-LIMIT.cbl'), status: 201,
});
assert.equal(unknown.formalProofStatus, 'UNKNOWN_HALTED_LIMIT');
await request(`/api/verifications/${unknown.id}/apply-patch`, { method: 'POST', status: [409, 422] });
assert.equal((await request(`/api/verifications/${unknown.id}`)).javaSource, limit.javaSource);

const noCandidate = sourceRequest(fx, 'SMOKE-WITHOUT-PATCH.cbl');
delete noCandidate.patchedJavaSource;
const analysedOnly = await request('/api/verifications', { body: noCandidate, status: 201 });
assert.equal(analysedOnly.formalProofStatus, fx.formalProofStatus);
await request(`/api/verifications/${analysedOnly.id}/apply-patch`, { method: 'POST', status: [409, 422] });
await request('/api/verifications', { body: { ...noCandidate, cobolSource: 'x\n'.repeat(1501) }, status: 400 });
await request('/api/verifications', { body: { ...noCandidate, javaSource: 'x'.repeat(100001) }, status: 400 });
await request(`/api/verifications/${analysedOnly.id}/candidates`, { body: { javaSource: 'x\n'.repeat(1501) }, status: 400 });
await request('/api/verifications', { body: { ...noCandidate, javaSource: 'x'.repeat(1048576) }, status: 413 });
// Java octal constants must never be silently interpreted as decimal by the prover.
const octal = await request('/api/verifications', { body: { ...noCandidate,
  moduleName: 'SMOKE-OCTAL.cbl',
  cobolSource: fx.cobolSource.replace('INPUT-AMOUNT * REFERENCE-RATE', '0'),
  javaSource: 'import java.math.BigDecimal; public class OctalCase { public BigDecimal calculate(BigDecimal a, BigDecimal r) { if (010 == 8) { return BigDecimal.ONE; } else { return BigDecimal.ZERO; } } }',
}, status: 201 });
assert.equal(octal.formalProofStatus, 'UNKNOWN_HALTED_LIMIT');
assert.equal(octal.proofScope.reasonCode, 'semantics.java_integer_literal');
console.log(`API integration passed: ${checks} HTTP checks, typed graphs, review reports, candidate isolation, revision history, solver witnesses and safe-patch enforcement.`);
