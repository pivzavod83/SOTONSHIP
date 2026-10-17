import { DomainException } from '../../../../common/exceptions/domain.exception';
import { VerificationRun, VerificationAnalysis, assertSupportedProof } from './verification-run';
import { FormalProofStatusValue } from '../enums/formal-proof-status.enum';
import { VerificationCompletedEvent } from '../events/verification-completed.event';

export class PatchedVerificationRun extends VerificationRun {
  constructor(original: VerificationRun, analysis: VerificationAnalysis) {
    const state = original.toPrimitives();
    if (!state.patchedJavaSource.trim() || analysis.formalProofStatus !== FormalProofStatusValue.UNSAT_PROVEN_SAFE) {
      throw new DomainException('Only a verified UNSAT patch may replace the original Java source.', 'verification.patch_not_proven');
    }
    assertSupportedProof(analysis);
    super({ ...state, ...analysis, javaSource: state.patchedJavaSource, updatedAt: new Date() });
    this.events.push(new VerificationCompletedEvent(state.id, analysis.formalProofStatus));
  }
}
