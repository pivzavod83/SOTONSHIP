import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { DefectModelStatusRto } from '../../../presentation/rto/defect-review.rto';
import { DEFECT_REVIEW_ENGINE, IDefectReviewEngine } from '../../ports/defect-review-engine';
import { validatedDefectModelStatus } from '../../services/validated-defect-review';
import { GetDefectModelStatusQuery } from '../get-defect-model-status.query';

@QueryHandler(GetDefectModelStatusQuery)
export class GetDefectModelStatusHandler implements IQueryHandler<GetDefectModelStatusQuery> {
  constructor(@Inject(DEFECT_REVIEW_ENGINE) private readonly engine: IDefectReviewEngine) {}
  async execute(_query: GetDefectModelStatusQuery): Promise<DefectModelStatusRto> {
    return DefectModelStatusRto.fromDomain(validatedDefectModelStatus(await this.engine.status()));
  }
}
