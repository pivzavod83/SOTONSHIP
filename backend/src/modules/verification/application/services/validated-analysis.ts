import { createHash } from 'node:crypto';
import { VerificationAnalysis, VerificationRun, VerificationRunProps } from '../../domain/entities/verification-run';
import { FormalProofStatusValue } from '../../domain/enums/formal-proof-status.enum';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';
import { TranslationKey } from '../../../../common/i18n/translation-key';
import { verificationPolicy } from '../../../../common/config/verification-policy';

/** Whitelist subprocess fields and validate all invariants before persistence. */
export function validatedAnalysis(result: VerificationAnalysis, context: Omit<VerificationRunProps, keyof VerificationAnalysis>): VerificationAnalysis {
  try {
    const analysis: VerificationAnalysis = {
      gnnAlignmentScore: result.gnnAlignmentScore, gnnBugRiskScore: result.gnnBugRiskScore,
      baselineAlignmentScore: result.baselineAlignmentScore, baselineCaughtBug: result.baselineCaughtBug,
      formalProofStatus: result.formalProofStatus, bugCategory: result.bugCategory,
      fStringSummary: result.fStringSummary, cpgGraphJson: result.cpgGraphJson,
      counterexamplesJson: result.counterexamplesJson, isFailureLimitCase: result.isFailureLimitCase,
      proofScope: result.proofScope, provenanceJson: result.provenanceJson,
    };
    new VerificationRun({ ...context, ...analysis });
    if (analysis.provenanceJson.engineVersion !== verificationPolicy.engineVersion
      || analysis.proofScope.engineVersion !== verificationPolicy.engineVersion
      || analysis.proofScope.semanticsVersion !== verificationPolicy.semanticsVersion) {
      throw new Error('Analysis requires the current engine and semantics versions.');
    }
    if (analysis.formalProofStatus === FormalProofStatusValue.UNSAT_PROVEN_SAFE) {
      const hashes = analysis.proofScope.sourceSha256;
      if (!hashes || typeof hashes !== 'object' || Array.isArray(hashes)
        || hashes.cobol !== createHash('sha256').update(context.cobolSource).digest('hex')
        || hashes.java !== createHash('sha256').update(context.javaSource).digest('hex')) {
        throw new Error('Proof does not refer to the submitted sources.');
      }
    }
    return analysis;
  } catch (cause) {
    throw new InfrastructureException('The engine result did not satisfy verification invariants.', TranslationKey.InvalidEngineResult, { cause });
  }
}
