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

const page = await request('/api/verifications?page=1&pageSize=50');
const rows = page.items;
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
    proofInputs: detail.proofScope.proofInputs,
  };
}

// New runs are persisted through CQRS, mapped through MikroORM, and proved by Python.
const run = await request('/api/verifications', {
  body: sourceRequest(fx, 'SMOKE-FX-WIRE.cbl'), status: 201,
});
assert.equal(run.formalProofStatus, fx.formalProofStatus);
assert.equal(run.proofScope.rate.observationDate, '2026-10-15', 'Observation date must survive database-to-engine round trip');
if (run.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND') {
  assert.ok(run.counterexamplesJson.length > 0, 'SAT must include a witness');
  assert.notEqual(run.counterexamplesJson[0].pennyDrift, '0.00');
}
assert.equal((await request(`/api/verifications/${run.id}`)).javaSource, fx.javaSource);
const patched = await request(`/api/verifications/${run.id}/apply-patch`, { method: 'POST', status: [200, 201] });
assert.equal(patched.formalProofStatus, 'UNSAT_PROVEN_SAFE');
assert.equal(patched.javaSource, fx.patchedJavaSource);
assert.deepEqual(patched.counterexamplesJson, []);
assert.equal((await request(`/api/verifications/${run.id}`)).javaSource, fx.patchedJavaSource);

// A fabricated patch that is still the buggy Java must be rejected without mutation.
if (fx.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND') {
  const badPatch = await request('/api/verifications', {
    body: { ...sourceRequest(fx, 'SMOKE-UNSAFE-PATCH.cbl'), patchedJavaSource: fx.javaSource }, status: 201,
  });
  await request(`/api/verifications/${badPatch.id}/apply-patch`, { method: 'POST', status: [409, 422] });
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
console.log(`API integration passed: ${checks} HTTP checks, persisted runs, solver witnesses, verified patches and rejected unsafe/limit patches.`);
