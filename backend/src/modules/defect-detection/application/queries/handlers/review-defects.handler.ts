import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { DefectReviewRequest } from '../../../domain/value-objects/defect-review-request';
import { DefectReviewRto } from '../../../presentation/rto/defect-review.rto';
import { DEFECT_REVIEW_ENGINE, IDefectReviewEngine } from '../../ports/defect-review-engine';
import { validatedDefectReview } from '../../services/validated-defect-review';
import { ReviewDefectsQuery } from '../review-defects.query';

@QueryHandler(ReviewDefectsQuery)
export class ReviewDefectsHandler implements IQueryHandler<ReviewDefectsQuery> {
  constructor(@Inject(DEFECT_REVIEW_ENGINE) private readonly engine: IDefectReviewEngine) {}

  async execute(query: ReviewDefectsQuery): Promise<DefectReviewRto> {
    const input = new DefectReviewRequest(query.input).toPrimitives();
    return DefectReviewRto.fromDomain(validatedDefectReview(await this.engine.review(input), input));
  }
}
