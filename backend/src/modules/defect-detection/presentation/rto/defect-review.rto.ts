import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { JsonObject } from '../../../../common/value-objects/json-value';
import { DEFECT_REVIEW_STATUSES, DefectModelMetadata, DefectModelStatus, DefectReview } from '../../domain/entities/defect-review';

class DefectSourceSpanRto {
  @ApiProperty({ minimum: 1 }) start!: number;
  @ApiProperty({ minimum: 1 }) end!: number;
}
class DefectModelMetadataRto {
  @ApiProperty() name!: string;
  @ApiProperty() sha256!: string;
  @ApiProperty() datasetSha256!: string;
  @ApiProperty({ enum: [6] }) trainingFamilyCount!: 6;
  @ApiPropertyOptional({ type: Object, description: 'Recorded synthetic-pilot evaluation statistics, not a production guarantee.' }) evaluation?: JsonObject;
  static fromDomain(model: DefectModelMetadata): DefectModelMetadataRto { return Object.assign(new DefectModelMetadataRto(), model); }
}
class DefectRiskRto {
  @ApiProperty({ minimum: 0, maximum: 1, description: 'Uncalibrated classifier score, not probability of correctness.' }) score!: number;
  @ApiProperty({ minimum: 0, maximum: 1 }) threshold!: number;
  @ApiProperty({ enum: ['REVIEW_REQUIRED', 'NO_DEFECT_SIGNAL'] }) decision!: DefectReview['risk']['decision'];
  @ApiProperty({ enum: [false] }) calibrated!: false;
}
class DefectFindingRto {
  @ApiProperty() findingId!: string;
  @ApiProperty({ enum: ['MODEL_HYPOTHESIS'] }) evidenceStatus!: 'MODEL_HYPOTHESIS';
  @ApiProperty() title!: string;
  @ApiProperty() explanation!: string;
  @ApiProperty() suggestedFix!: string;
  @ApiProperty({ type: DefectSourceSpanRto, nullable: true }) cobolLines!: DefectSourceSpanRto | null;
  @ApiProperty({ type: DefectSourceSpanRto, nullable: true }) javaLines!: DefectSourceSpanRto | null;
  @ApiProperty() cobolExcerpt!: string;
  @ApiProperty() javaExcerpt!: string;
  @ApiProperty({ minimum: 0, maximum: 1 }) score!: number;
  @ApiProperty({ enum: ['SEMANTIC_DIFFERENCE'] }) category!: 'SEMANTIC_DIFFERENCE';
  @ApiProperty({ type: [Object], maxItems: 0, description: 'This classifier does not execute inputs or invent counterexamples.' }) candidateInputs!: [];
}
class DefectSourceHashesRto {
  @ApiProperty() cobol!: string;
  @ApiProperty() java!: string;
}
export class DefectReviewRto {
  @ApiProperty({ enum: DEFECT_REVIEW_STATUSES }) status!: DefectReview['status'];
  @ApiProperty({ enum: ['paired-defect-v1'] }) engineVersion!: 'paired-defect-v1';
  @ApiProperty({ type: DefectSourceHashesRto }) sourceHashes!: DefectSourceHashesRto;
  @ApiProperty({ enum: [false] }) aiIsProof!: false;
  @ApiProperty({ enum: [false] }) counterexamplesExecuted!: false;
  @ApiProperty({ type: DefectRiskRto }) risk!: DefectRiskRto;
  @ApiProperty({ type: DefectModelMetadataRto, nullable: true }) model!: DefectModelMetadataRto | null;
  @ApiProperty() summary!: string;
  @ApiProperty({ type: [String] }) limitations!: string[];
  @ApiProperty({ type: [DefectFindingRto], maxItems: 8 }) findings!: DefectFindingRto[];

  static fromDomain(review: DefectReview): DefectReviewRto {
    return Object.assign(new DefectReviewRto(), {
      status: review.status, engineVersion: review.engineVersion, sourceHashes: Object.assign(new DefectSourceHashesRto(), review.sourceHashes),
      aiIsProof: false as const, counterexamplesExecuted: false as const, risk: Object.assign(new DefectRiskRto(), review.risk),
      model: review.model === null ? null : DefectModelMetadataRto.fromDomain(review.model), summary: review.summary, limitations: [...review.limitations],
      findings: review.findings.map((finding) => Object.assign(new DefectFindingRto(), finding, {
        cobolLines: finding.cobolLines === null ? null : Object.assign(new DefectSourceSpanRto(), finding.cobolLines),
        javaLines: finding.javaLines === null ? null : Object.assign(new DefectSourceSpanRto(), finding.javaLines), candidateInputs: [],
      })),
    });
  }
}
export class DefectModelStatusRto {
  @ApiProperty() configured!: boolean;
  @ApiProperty({ type: DefectModelMetadataRto, nullable: true }) model!: DefectModelMetadataRto | null;
  @ApiProperty({ type: [String] }) limitations!: string[];
  static fromDomain(status: DefectModelStatus): DefectModelStatusRto {
    return Object.assign(new DefectModelStatusRto(), { configured: status.configured,
      model: status.model === null ? null : DefectModelMetadataRto.fromDomain(status.model), limitations: [...status.limitations] });
  }
}
