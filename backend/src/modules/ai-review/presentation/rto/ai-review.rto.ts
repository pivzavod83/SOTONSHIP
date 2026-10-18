import { ApiProperty } from '@nestjs/swagger';
import { AI_DEFECT_CATEGORIES, AI_REVIEW_STATUSES, AiDefectFinding, AiReview } from '../../domain/entities/ai-review';

class SourceLineSpanRto {
  @ApiProperty({ minimum: 1 }) start!: number;
  @ApiProperty({ minimum: 1 }) end!: number;
}
class CandidateDefectInputRto {
  @ApiProperty({ description: 'Proposed JSON object, not executed or verified.' }) inputsJson!: string;
  @ApiProperty() rationale!: string;
  @ApiProperty({ enum: ['NOT_EXECUTED'] }) status!: 'NOT_EXECUTED';
}
class AiDefectFindingRto {
  @ApiProperty() findingId!: string;
  @ApiProperty() title!: string;
  @ApiProperty({ enum: AI_DEFECT_CATEGORIES }) category!: AiDefectFinding['category'];
  @ApiProperty({ enum: ['LOW', 'MEDIUM', 'HIGH'] }) severity!: AiDefectFinding['severity'];
  @ApiProperty() explanation!: string;
  @ApiProperty({ type: SourceLineSpanRto, nullable: true }) cobolLines!: SourceLineSpanRto | null;
  @ApiProperty({ type: SourceLineSpanRto, nullable: true }) javaLines!: SourceLineSpanRto | null;
  @ApiProperty() cobolExcerpt!: string;
  @ApiProperty() javaExcerpt!: string;
  @ApiProperty({ description: 'Suggested correction description. Never applied automatically.' }) suggestedFix!: string;
  @ApiProperty({ type: [CandidateDefectInputRto] }) candidateInputs!: CandidateDefectInputRto[];
  @ApiProperty({ enum: ['AI_HYPOTHESIS'] }) evidenceStatus!: 'AI_HYPOTHESIS';
}
class ReviewSourceHashesRto {
  @ApiProperty() cobol!: string;
  @ApiProperty() java!: string;
}
class ReviewProviderRto {
  @ApiProperty({ enum: ['OPENAI_COMPATIBLE_CHAT'] }) protocol!: 'OPENAI_COMPATIBLE_CHAT';
  @ApiProperty({ type: String, nullable: true }) model!: string | null;
}
export class AiReviewRto {
  @ApiProperty({ enum: AI_REVIEW_STATUSES }) status!: AiReview['status'];
  @ApiProperty() summary!: string;
  @ApiProperty({ type: [AiDefectFindingRto], maxItems: 8 }) findings!: AiDefectFindingRto[];
  @ApiProperty({ type: [String] }) limitations!: string[];
  @ApiProperty({ type: ReviewSourceHashesRto }) sourceHashes!: ReviewSourceHashesRto;
  @ApiProperty({ type: ReviewProviderRto }) provider!: ReviewProviderRto;
  @ApiProperty({ enum: [false], description: 'Model output cannot establish formal equivalence.' }) aiIsProof!: false;
  @ApiProperty({ enum: ['paired-defect-review-v1'] }) promptVersion!: 'paired-defect-review-v1';
  @ApiProperty({ enum: [false], description: 'Candidate inputs are suggestions, not reproducible witnesses.' }) counterexamplesExecuted!: false;

  static fromDomain(review: AiReview): AiReviewRto {
    return Object.assign(new AiReviewRto(), {
      status: review.status, summary: review.summary, limitations: [...review.limitations], aiIsProof: false as const,
      promptVersion: 'paired-defect-review-v1' as const, counterexamplesExecuted: false as const,
      sourceHashes: Object.assign(new ReviewSourceHashesRto(), review.sourceHashes),
      provider: Object.assign(new ReviewProviderRto(), review.provider),
      findings: review.findings.map((finding) => Object.assign(new AiDefectFindingRto(), {
        findingId: finding.findingId, title: finding.title, category: finding.category, severity: finding.severity,
        explanation: finding.explanation, cobolExcerpt: finding.cobolExcerpt, javaExcerpt: finding.javaExcerpt,
        cobolLines: finding.cobolLines === null ? null : Object.assign(new SourceLineSpanRto(), finding.cobolLines),
        javaLines: finding.javaLines === null ? null : Object.assign(new SourceLineSpanRto(), finding.javaLines),
        suggestedFix: finding.suggestedFix, candidateInputs: finding.candidateInputs.map((candidate) => Object.assign(new CandidateDefectInputRto(), candidate)),
        evidenceStatus: 'AI_HYPOTHESIS' as const,
      })),
    });
  }
}
