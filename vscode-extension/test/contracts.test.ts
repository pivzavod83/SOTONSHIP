import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import test from 'node:test';
import { isScopedEquivalent, parseVerificationResult, proofMatchesSources, validateProofInputs, validateSource, type ProofInputs, type VerificationResult } from '../src/contracts';

function inputs(): ProofInputs {
  return {
    cobolDialectProfile: 'IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1', cobolSourceFormat: 'FREE',
    amountField: 'INPUT-AMOUNT', rateField: 'REFERENCE-RATE', resultField: 'SETTLEMENT-RESULT',
    javaAmountParameter: 'principal', javaRateParameter: 'quote', amountMinCents: -999999999, amountMaxCents: 999999999,
    referenceCurrencyPair: 'GBP/EUR', referenceSource: 'Bank of England', referenceCollectedDate: '2026-10-17',
  };
}
function result(): VerificationResult {
  const cobolSource = 'COBOL source', javaSource = 'Java source';
  const hash = (source: string) => createHash('sha256').update(source).digest('hex');
  return {
    id: '11111111-1111-4111-8111-111111111111', moduleName: 'TEST.cbl', category: 'FX_CONVERSION',
    cobolSource, javaSource, patchedJavaSource: '', formalProofStatus: 'UNSAT_PROVEN_SAFE',
    proofScope: {
      supported: true, bounded: true, inputAmountCents: { min: -999999999, max: 999999999 }, proofInputs: inputs(),
      rate: { currencyPair: 'GBP/EUR', source: 'Bank of England', collectedDate: '2026-10-17', rate: '1.183000000000' },
      sourceSha256: { cobol: hash(cobolSource), java: hash(javaSource) },
    },
    counterexamplesJson: [], fStringSummary: 'Equivalent within the declared finite input domain.',
    cpgGraphJson: { nodes: [], edges: [] }, provenanceJson: {}, gnnAlignmentScore: 0.8, gnnBugRiskScore: 0.1, version: 1,
  };
}
function sat(): VerificationResult {
  return {
    ...result(), formalProofStatus: 'SAT_COUNTEREXAMPLE_FOUND',
    counterexamplesJson: [{ inputAmountGbp: '45.00', referenceRate: '1.183', cobolOutput: '53.24', javaOutput: '53.23', pennyDrift: '-0.01', solverGenerated: true, dataSource: 'Bank of England', collectedDate: '2026-10-17' }],
  };
}

test('proof inputs validate the exact supported contract, including leap days and fixed source', () => {
  const proof = { ...inputs(), referenceCollectedDate: '2024-02-29', cobolSourceFormat: 'FIXED' };
  assert.deepEqual(validateProofInputs(proof), proof);
  assert.notEqual(validateProofInputs(proof), proof);
});

test('proof inputs reject unknown keys, unsupported profiles, coercion and invalid literals', () => {
  for (const change of [
    { unknown: true }, { cobolDialectProfile: 'GNUCOBOL' }, { cobolSourceFormat: 'free' },
    { amountMinCents: '-1' }, { amountMaxCents: Infinity }, { amountMinCents: 0.1 },
    { amountMinCents: 1000000000 }, { amountMinCents: 10, amountMaxCents: 9 },
    { referenceCollectedDate: '2026-02-29' }, { referenceCollectedDate: '2026-02-30' },
    { referenceCollectedDate: '2026-1-01' }, { referenceCurrencyPair: 'gbp/EUR' },
    { amountField: 'A; STOP RUN' }, { javaAmountParameter: 'a.b' }, { referenceSource: '  ' },
  ]) assert.throws(() => validateProofInputs({ ...inputs(), ...change }));
  const missing = { ...inputs() } as Partial<ProofInputs>;
  delete missing.resultField;
  assert.throws(() => validateProofInputs(missing));
  for (const malformed of [null, [], true, 'profile']) assert.throws(() => validateProofInputs(malformed));
});

test('source limits count CRLF and Python-compatible Unicode line separators consistently', () => {
  validateSource('x'.repeat(100000), 'COBOL');
  validateSource('x\r\n'.repeat(1500), 'COBOL');
  validateSource('x\u2028'.repeat(1500), 'COBOL');
  assert.throws(() => validateSource('x'.repeat(100001), 'COBOL'), /100000/);
  assert.throws(() => validateSource(Array(1501).fill('x').join('\r\n'), 'COBOL'), /1500/);
  assert.throws(() => validateSource(Array(1501).fill('x').join('\x85'), 'COBOL'), /1500/);
  assert.throws(() => validateSource(' \n', 'COBOL'), /source code/);
});

test('supported UNSAT is source-bound and the equivalence gate rejects changed code', () => {
  const proof = parseVerificationResult(result());
  assert.equal(isScopedEquivalent(proof), true);
  assert.equal(proofMatchesSources(proof, proof.cobolSource, proof.javaSource), true);
  assert.equal(proofMatchesSources(proof, proof.cobolSource, `${proof.javaSource}\n`), false);
  assert.equal(isScopedEquivalent({ ...proof, javaSource: 'changed Java source' }), false);
  assert.equal(isScopedEquivalent({ ...proof, analysisStale: true }), false);
  assert.equal(isScopedEquivalent({ ...proof, reVerificationRequired: true }), false);
});

test('UNSAT rejects missing scope, unbounded/unsupported claims, mismatched bounds and rate identity', () => {
  for (const change of [
    { supported: false }, { bounded: false }, { inputAmountCents: { min: 0, max: Infinity } },
    { inputAmountCents: { min: 0, max: 10 } }, { proofInputs: undefined }, { sourceSha256: undefined },
    { rate: { currencyPair: 'GBP/USD', source: 'Bank of England', collectedDate: '2026-10-17', rate: '1.183' } },
  ]) {
    const proof = result();
    assert.throws(() => parseVerificationResult({ ...proof, proofScope: { ...proof.proofScope, ...change } }));
  }
  assert.throws(() => parseVerificationResult({ ...result(), counterexamplesJson: [{}] }));
  assert.throws(() => parseVerificationResult({ ...result(), isFailureLimitCase: true }));
});

test('SAT accepts a concrete exact witness and rejects inconsistent or out-of-scope witnesses', () => {
  assert.equal(parseVerificationResult(sat()).formalProofStatus, 'SAT_COUNTEREXAMPLE_FOUND');
  assert.equal(isScopedEquivalent(sat()), false);
  for (const change of [
    { javaOutput: '53.24' }, { pennyDrift: '0.01' }, { inputAmountGbp: '10000000.00' },
    { inputAmountGbp: 45 }, { javaOutput: 'NaN' }, { solverGenerated: false },
    { referenceRate: '1.1830000000000001' }, { dataSource: 'Other source' }, { collectedDate: '2026-10-18' },
  ]) {
    const proof = sat();
    assert.throws(() => parseVerificationResult({ ...proof, counterexamplesJson: [{ ...proof.counterexamplesJson[0], ...change }] }));
  }
  assert.throws(() => parseVerificationResult({ ...sat(), counterexamplesJson: [] }));
});

test('UNKNOWN remains inconclusive and malformed result fields fail closed', () => {
  const unknown = { ...result(), formalProofStatus: 'UNKNOWN_HALTED_LIMIT', proofScope: { supported: false, bounded: true, reason: 'Unsupported statement.' } };
  assert.equal(parseVerificationResult(unknown).formalProofStatus, 'UNKNOWN_HALTED_LIMIT');
  assert.equal(isScopedEquivalent(unknown as VerificationResult), false);
  for (const change of [
    { formalProofStatus: 'SAFE' }, { category: 'PAYMENTS' }, { id: 'bad' }, { version: 0 },
    { gnnAlignmentScore: NaN }, { gnnBugRiskScore: 1.1 }, { proofScope: [] }, { cpgGraphJson: null },
    { provenanceJson: [] }, { counterexamplesJson: null }, { patchedJavaSource: undefined },
  ]) assert.throws(() => parseVerificationResult({ ...result(), ...change }));
  assert.throws(() => parseVerificationResult({ ...unknown, counterexamplesJson: [{}] }));
});

test('source hash tampering fails even for a counterexample result', () => {
  const proof = sat();
  assert.throws(() => parseVerificationResult({ ...proof, proofScope: { ...proof.proofScope, sourceSha256: { cobol: '0'.repeat(64), java: '0'.repeat(64) } } }), /hashes/);
});
