import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { AiReviewRequest } from '../../../domain/value-objects/ai-review-request';
import { AiReviewRto } from '../../../presentation/rto/ai-review.rto';
import { AI_DEFECT_REVIEW_ENGINE, IAiDefectReviewEngine } from '../../ports/ai-defect-review-engine';
import { validatedAiReview } from '../../services/validated-ai-review';
import { ReviewPairQuery } from '../review-pair.query';

@QueryHandler(ReviewPairQuery)
export class ReviewPairHandler implements IQueryHandler<ReviewPairQuery> {
  constructor(@Inject(AI_DEFECT_REVIEW_ENGINE) private readonly engine: IAiDefectReviewEngine) {}

  async execute(query: ReviewPairQuery): Promise<AiReviewRto> {
    const input = new AiReviewRequest(query.input).toPrimitives();
    return AiReviewRto.fromDomain(validatedAiReview(await this.engine.review(input), input));
  }
}
