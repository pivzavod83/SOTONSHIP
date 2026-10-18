import { VerificationRun } from '../../domain/entities/verification-run';
import { VerificationEntity } from '../../entities/verification.entity';

/** The sole domain ↔ persistence translation boundary. */
export class VerificationMapper {
  static toDomain(entity: VerificationEntity): VerificationRun {
    return new VerificationRun({
      id: entity.id, moduleName: entity.moduleName, category: entity.category,
      cobolSource: entity.cobolSource, javaSource: entity.javaSource, patchedJavaSource: entity.patchedJavaSource,
      gnnAlignmentScore: entity.gnnAlignmentScore, gnnBugRiskScore: entity.gnnBugRiskScore,
      baselineAlignmentScore: entity.baselineAlignmentScore, baselineCaughtBug: entity.baselineCaughtBug,
      formalProofStatus: entity.formalProofStatus, bugCategory: entity.bugCategory, fStringSummary: entity.fStringSummary,
      cpgGraphJson: entity.cpgGraphJson, counterexamplesJson: entity.counterexamplesJson,
      isFailureLimitCase: entity.isFailureLimitCase, proofScope: entity.proofScope, provenanceJson: entity.provenanceJson,
      createdAt: entity.createdAt, updatedAt: entity.updatedAt, version: entity.version,
    });
  }
  static toPersistence(run: VerificationRun, target = new VerificationEntity()): VerificationEntity {
    Object.assign(target, run.toPrimitives());
    return target;
  }
}
