import { createHash } from 'node:crypto';
import { VerificationAnalysis, VerificationRun, VerificationRunProps } from '../src/modules/verification/domain/entities/verification-run';
import { FormalProofStatusValue as Status } from '../src/modules/verification/domain/enums/formal-proof-status.enum';
import { VerificationCategory } from '../src/modules/verification/domain/enums/verification-category.enum';
import { ReferenceFxRate } from '../src/modules/fx-rates/domain/entities/reference-fx-rate';

export const ID = '11111111-1111-4111-8111-111111111111';
export function analysis(status = Status.SAT_COUNTEREXAMPLE_FOUND, java = 'buggy Java'): VerificationAnalysis {
  return {
    gnnAlignmentScore: 0.8, gnnBugRiskScore: status === Status.SAT_COUNTEREXAMPLE_FOUND ? 0.9 : 0.1,
    baselineAlignmentScore: 0.2, baselineCaughtBug: false, formalProofStatus: status,
    bugCategory: 'IEEE754_PENNY_DRIFT', fStringSummary: 'An actual counterexample or a bounded proof.',
    cpgGraphJson: { nodes: [], edges: [] },
    counterexamplesJson: status === Status.SAT_COUNTEREXAMPLE_FOUND ? [{ pennyDrift: '-0.01', inputAmountGbp: '1.00' }] : [],
    isFailureLimitCase: false,
    proofScope: {
      supported: status !== Status.UNKNOWN_HALTED_LIMIT, bounded: true,
      inputAmountCents: { min: 0, max: 999999 },
      rate: { currencyPair: 'GBP/EUR', source: 'Bank of England', collectedDate: '2026-10-17', rate: '1.158600000000' },
      proofInputs: {
        cobolDialectProfile: 'IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1',
        cobolSourceFormat: 'FREE', amountField: 'INPUT-AMOUNT', rateField: 'REFERENCE-RATE', resultField: 'SETTLEMENT-RESULT',
        javaAmountParameter: 'principal', javaRateParameter: 'quote', amountMinCents: 0, amountMaxCents: 999999,
        referenceCurrencyPair: 'GBP/EUR', referenceSource: 'Bank of England', referenceCollectedDate: '2026-10-17',
      },
      sourceSha256: { cobol: createHash('sha256').update('COBOL source').digest('hex'), java: createHash('sha256').update(java).digest('hex') },
    },
    provenanceJson: { fixture: true },
  };
}
export function run(overrides: Partial<VerificationRunProps> = {}): VerificationRun {
  return new VerificationRun({
    id: ID, moduleName: 'TEST.cbl', category: VerificationCategory.FX_CONVERSION,
    cobolSource: 'COBOL source', javaSource: 'buggy Java', patchedJavaSource: 'fixed Java',
    createdAt: new Date('2026-10-17T12:00:00Z'), updatedAt: new Date('2026-10-17T12:00:00Z'), version: 1,
    ...analysis(), ...overrides,
  });
}
export const rate = new ReferenceFxRate({
  id: '22222222-2222-4222-8222-222222222222', currencyPair: 'GBP/EUR', rate: '1.158600000000',
  source: 'Bank of England', collectedDate: '2026-10-17',
});
