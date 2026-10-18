import { ApiProperty } from '@nestjs/swagger';
import { VerificationRun } from '../../domain/entities/verification-run';
import { VerificationCategory } from '../../domain/enums/verification-category.enum';
import { FormalProofStatusValue } from '../../domain/enums/formal-proof-status.enum';
import { JsonObject } from '../../../../common/value-objects/json-value';

export class VerificationSummaryRto {
  @ApiProperty({ format: 'uuid' }) id!: string;
  @ApiProperty() moduleName!: string;
  @ApiProperty({ enum: VerificationCategory }) category!: VerificationCategory;
  @ApiProperty({ minimum: 0, maximum: 1 }) gnnAlignmentScore!: number;
  @ApiProperty({ minimum: 0, maximum: 1 }) gnnBugRiskScore!: number;
  @ApiProperty({ minimum: 0, maximum: 1 }) baselineAlignmentScore!: number;
  @ApiProperty() baselineCaughtBug!: boolean;
  @ApiProperty({ enum: FormalProofStatusValue }) formalProofStatus!: FormalProofStatusValue;
  @ApiProperty() bugCategory!: string;
  @ApiProperty() fStringSummary!: string;
  @ApiProperty() isFailureLimitCase!: boolean;
  @ApiProperty({ type: 'object', additionalProperties: true, description: 'Explicit finite proof bounds, reference rate, source hashes and limitations.' }) proofScope!: JsonObject;
  @ApiProperty({ format: 'date-time' }) createdAt!: string;
  @ApiProperty({ format: 'date-time' }) updatedAt!: string;
  @ApiProperty() version!: number;

  static fromDomain(run: VerificationRun): VerificationSummaryRto {
    const state = run.toPrimitives();
    return Object.assign(new VerificationSummaryRto(), {
      id: state.id, moduleName: state.moduleName, category: state.category,
      gnnAlignmentScore: state.gnnAlignmentScore, gnnBugRiskScore: state.gnnBugRiskScore,
      baselineAlignmentScore: state.baselineAlignmentScore, baselineCaughtBug: state.baselineCaughtBug,
      formalProofStatus: state.formalProofStatus, bugCategory: state.bugCategory,
      fStringSummary: state.fStringSummary, isFailureLimitCase: state.isFailureLimitCase,
      proofScope: state.proofScope, createdAt: state.createdAt.toISOString(), updatedAt: state.updatedAt.toISOString(), version: state.version,
    });
  }
}
