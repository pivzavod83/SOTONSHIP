import { createHash } from 'node:crypto';

export type VerificationCategory = 'FX_CONVERSION' | 'INTEREST_CALC' | 'REMITTANCE_FEE' | 'EXTERNAL_LIMIT_CASE';
export type FormalProofStatus = 'SAT_COUNTEREXAMPLE_FOUND' | 'UNSAT_PROVEN_SAFE' | 'UNKNOWN_HALTED_LIMIT';

export interface ProofInputs {
  cobolDialectProfile: 'IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1';
  cobolSourceFormat: 'FREE' | 'FIXED';
  amountField: string; rateField: string; resultField: string;
  javaAmountParameter: string; javaRateParameter: string;
  amountMinCents: number; amountMaxCents: number;
  referenceCurrencyPair: string; referenceSource: string; referenceCollectedDate: string;
}

export interface VerificationRequest {
  moduleName: string; category: VerificationCategory;
  cobolSource: string; javaSource: string; patchedJavaSource?: string;
  proofInputs: ProofInputs;
}

export interface VerificationResult {
  id: string; moduleName: string; category: VerificationCategory;
  cobolSource: string; javaSource: string; patchedJavaSource: string;
  formalProofStatus: FormalProofStatus;
  proofScope: Record<string, unknown>; counterexamplesJson: Record<string, unknown>[];
  fStringSummary: string; cpgGraphJson: Record<string, unknown>; provenanceJson: Record<string, unknown>;
  gnnAlignmentScore: number; gnnBugRiskScore: number; version: number;
  [key: string]: unknown;
}

const PROOF_KEYS = [
  'cobolDialectProfile', 'cobolSourceFormat', 'amountField', 'rateField', 'resultField',
  'javaAmountParameter', 'javaRateParameter', 'amountMinCents', 'amountMaxCents',
  'referenceCurrencyPair', 'referenceSource', 'referenceCollectedDate',
] as const;
const CATEGORIES: readonly string[] = ['FX_CONVERSION', 'INTEREST_CALC', 'REMITTANCE_FEE', 'EXTERNAL_LIMIT_CASE'];
const STATUSES: readonly string[] = ['SAT_COUNTEREXAMPLE_FOUND', 'UNSAT_PROVEN_SAFE', 'UNKNOWN_HALTED_LIMIT'];
const MAX_AMOUNT = 999_999_999;

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be a JSON object.`);
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string, maximum: number): string {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum || /[\x00-\x1f\x7f]/u.test(value)) {
    throw new Error(`${label} must be nonempty text of at most ${maximum} characters without control characters.`);
  }
  return value;
}

function date(value: unknown, label: string): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/u.test(value)
    || !Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    || new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) {
    throw new Error(`${label} must be a real calendar date in YYYY-MM-DD format.`);
  }
  return value;
}

function bound(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || Math.abs(value) > MAX_AMOUNT) {
    throw new Error(`${label} must be an integer between -999999999 and 999999999 cents.`);
  }
  return value;
}

export function validateProofInputs(value: unknown): ProofInputs {
  const input = object(value, 'Proof inputs');
  if (Object.keys(input).length !== PROOF_KEYS.length || Object.keys(input).some(key => !(PROOF_KEYS as readonly string[]).includes(key))) {
    throw new Error('Proof inputs must contain exactly the documented profile, field mapping, amount bounds and reference-rate identity.');
  }
  if (input.cobolDialectProfile !== 'IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1') throw new Error('Unsupported COBOL dialect profile.');
  if (input.cobolSourceFormat !== 'FREE' && input.cobolSourceFormat !== 'FIXED') throw new Error('COBOL source format must be FREE or FIXED.');
  for (const key of ['amountField', 'rateField', 'resultField'] as const) {
    if (!/^[A-Za-z][A-Za-z0-9_-]*$/u.test(text(input[key], key, 64))) throw new Error(`${key} must identify a COBOL field.`);
  }
  for (const key of ['javaAmountParameter', 'javaRateParameter'] as const) {
    if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/u.test(text(input[key], key, 64))) throw new Error(`${key} must identify a Java parameter.`);
  }
  const minimum = bound(input.amountMinCents, 'amountMinCents');
  const maximum = bound(input.amountMaxCents, 'amountMaxCents');
  if (minimum > maximum) throw new Error('amountMinCents must not exceed amountMaxCents.');
  if (typeof input.referenceCurrencyPair !== 'string' || !/^[A-Z]{3}\/[A-Z]{3}$/u.test(input.referenceCurrencyPair)) throw new Error('referenceCurrencyPair must use the form GBP/EUR.');
  text(input.referenceSource, 'referenceSource', 300);
  date(input.referenceCollectedDate, 'referenceCollectedDate');
  return { ...input } as unknown as ProofInputs;
}

export function validateSource(source: string, field: string): void {
  if (typeof source !== 'string' || !source.trim()) throw new Error(`${field} must contain source code.`);
  if (source.length > 100_000) throw new Error(`${field} exceeds the 100000-character source limit.`);
  const lines = source.split(/\r\n|[\n\v\f\r\x1c-\x1e\x85\u2028\u2029]/u);
  // Python str.splitlines() does not count a trailing line separator as another line.
  if (lines.at(-1) === '') lines.pop();
  if (lines.length > 1500) throw new Error(`${field} exceeds the 1500-line source limit.`);
}

export function validateVerificationRequest(request: VerificationRequest): VerificationRequest {
  text(request.moduleName, 'Module name', 160);
  if (/[\/\\]/u.test(request.moduleName)) throw new Error('Module name must be a name, without directory separators.');
  if (!CATEGORIES.includes(request.category)) throw new Error('Unsupported verification category.');
  validateSource(request.cobolSource, 'COBOL source');
  validateSource(request.javaSource, 'Java source');
  if (request.patchedJavaSource !== undefined && request.patchedJavaSource !== '') validateSource(request.patchedJavaSource, 'Candidate Java source');
  if (request.patchedJavaSource !== undefined && typeof request.patchedJavaSource !== 'string') throw new Error('Candidate Java source must be text.');
  return {
    moduleName: request.moduleName, category: request.category,
    cobolSource: request.cobolSource, javaSource: request.javaSource,
    ...(request.patchedJavaSource !== undefined ? { patchedJavaSource: request.patchedJavaSource } : {}),
    proofInputs: validateProofInputs(request.proofInputs),
  };
}

function supportedScope(scope: Record<string, unknown>): ProofInputs {
  if (scope.supported !== true || scope.bounded !== true) throw new Error('A completed proof requires supported, bounded semantics.');
  const inputs = validateProofInputs(scope.proofInputs);
  const bounds = object(scope.inputAmountCents, 'Proof amount bounds');
  if (bound(bounds.min, 'Proof minimum') !== inputs.amountMinCents || bound(bounds.max, 'Proof maximum') !== inputs.amountMaxCents) {
    throw new Error('Proof amount bounds do not match the explicit proof inputs.');
  }
  const rate = object(scope.rate, 'Reference rate');
  if (rate.currencyPair !== inputs.referenceCurrencyPair || rate.source !== inputs.referenceSource || rate.collectedDate !== inputs.referenceCollectedDate) {
    throw new Error('Proof reference rate does not match the explicit proof inputs.');
  }
  if (typeof rate.rate !== 'string' || rate.rate.length > 100 || !/^[+-]?\d+(?:\.\d+)?$/u.test(rate.rate) || !Number.isFinite(Number(rate.rate))) {
    throw new Error('Proof reference rate must be an exact finite decimal string.');
  }
  return inputs;
}

function cents(value: unknown, label: string): bigint {
  if (typeof value !== 'string' || value.length > 100 || !/^-?\d+\.\d{2}$/u.test(value)) throw new Error(`${label} must be an exact monetary value with two decimal places.`);
  const negative = value.startsWith('-');
  const magnitude = BigInt(value.replace('-', '').replace('.', ''));
  return negative ? -magnitude : magnitude;
}

function canonicalDecimal(value: string): string {
  const [integer, fraction = ''] = value.replace(/^[+-]/u, '').split('.');
  const normalized = `${integer.replace(/^0+(?=\d)/u, '')}.${fraction.replace(/0+$/u, '')}`;
  return value.startsWith('-') && /[1-9]/u.test(normalized) ? `-${normalized}` : normalized;
}

function validateWitness(witness: Record<string, unknown>, scope: Record<string, unknown>, inputs: ProofInputs): void {
  const amount = cents(witness.inputAmountGbp, 'Witness input amount');
  if (amount < BigInt(inputs.amountMinCents) || amount > BigInt(inputs.amountMaxCents)) throw new Error('Counterexample input is outside the proof bounds.');
  const expected = cents(witness.cobolOutput, 'Witness COBOL output');
  const actual = cents(witness.javaOutput, 'Witness Java output');
  const drift = cents(witness.pennyDrift, 'Witness monetary difference');
  if (expected === actual || actual - expected !== drift || witness.solverGenerated !== true) throw new Error('SAT requires a concrete solver-generated output difference.');
  const rate = object(scope.rate, 'Reference rate');
  if (typeof witness.referenceRate !== 'string' || witness.referenceRate.length > 100
    || !/^[+-]?\d+(?:\.\d+)?$/u.test(witness.referenceRate)
    || canonicalDecimal(witness.referenceRate) !== canonicalDecimal(rate.rate as string)
    || witness.dataSource !== inputs.referenceSource || witness.collectedDate !== inputs.referenceCollectedDate) {
    throw new Error('Counterexample rate provenance does not match the proof scope.');
  }
}

export function proofMatchesSources(result: VerificationResult, cobol: string, java: string): boolean {
  const hashes = result.proofScope.sourceSha256;
  if (!hashes || typeof hashes !== 'object' || Array.isArray(hashes)) return false;
  const record = hashes as Record<string, unknown>;
  return record.cobol === createHash('sha256').update(cobol, 'utf8').digest('hex')
    && record.java === createHash('sha256').update(java, 'utf8').digest('hex');
}

export function parseVerificationResult(value: unknown): VerificationResult {
  const result = object(value, 'Verification response');
  if (typeof result.id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(result.id)) throw new Error('Verification response has an invalid ID.');
  text(result.moduleName, 'Response module name', 160);
  if (!CATEGORIES.includes(result.category as string) || !STATUSES.includes(result.formalProofStatus as string)) throw new Error('Verification response has an unsupported category or proof status.');
  validateSource(result.cobolSource as string, 'Response COBOL source');
  validateSource(result.javaSource as string, 'Response Java source');
  if (typeof result.patchedJavaSource !== 'string') throw new Error('Verification response candidate source must be text.');
  if (result.patchedJavaSource) validateSource(result.patchedJavaSource, 'Response candidate Java source');
  if (typeof result.fStringSummary !== 'string' || result.fStringSummary.length > 20_000) throw new Error('Verification response summary is missing or oversized.');
  for (const key of ['gnnAlignmentScore', 'gnnBugRiskScore'] as const) {
    if (typeof result[key] !== 'number' || !Number.isFinite(result[key]) || result[key] < 0 || result[key] > 1) throw new Error('Verification response has an invalid graph score.');
  }
  if (typeof result.version !== 'number' || !Number.isSafeInteger(result.version) || result.version < 1) throw new Error('Verification response has an invalid revision.');
  const scope = object(result.proofScope, 'Proof scope');
  object(result.cpgGraphJson, 'Code graph');
  object(result.provenanceJson, 'Provenance');
  if (!Array.isArray(result.counterexamplesJson) || result.counterexamplesJson.length > 1000) throw new Error('Verification response counterexamples must be a bounded array.');
  const witnesses = result.counterexamplesJson.map(item => object(item, 'Counterexample'));
  const parsed = { ...result, counterexamplesJson: witnesses } as VerificationResult;
  if (scope.sourceSha256 !== undefined) {
    const hashes = object(scope.sourceSha256, 'Proof source hashes');
    if (typeof hashes.cobol !== 'string' || typeof hashes.java !== 'string'
      || !/^[a-f0-9]{64}$/u.test(hashes.cobol) || !/^[a-f0-9]{64}$/u.test(hashes.java)
      || !proofMatchesSources(parsed, parsed.cobolSource, parsed.javaSource)) throw new Error('Proof source hashes do not match the returned source code.');
  }
  if (result.formalProofStatus === 'UNSAT_PROVEN_SAFE') {
    supportedScope(scope);
    if (witnesses.length || result.isFailureLimitCase === true || !proofMatchesSources(parsed, parsed.cobolSource, parsed.javaSource)) throw new Error('UNSAT requires a supported source-bound proof without counterexamples or limit flags.');
  } else if (result.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND') {
    const inputs = supportedScope(scope);
    if (!witnesses.length || result.isFailureLimitCase === true) throw new Error('SAT requires a concrete counterexample without limit flags.');
    for (const witness of witnesses) validateWitness(witness, scope, inputs);
  } else if (witnesses.length) {
    throw new Error('UNKNOWN cannot contain a completed counterexample proof.');
  }
  return parsed;
}

export function isScopedEquivalent(result: VerificationResult): boolean {
  try { return result.analysisStale !== true && result.reVerificationRequired !== true && parseVerificationResult(result).formalProofStatus === 'UNSAT_PROVEN_SAFE'; }
  catch { return false; }
}
