import { DefectReviewRequestState } from '../../domain/value-objects/defect-review-request';

export const DEFECT_REVIEW_ENGINE = 'IDefectReviewEngine';
export interface IDefectReviewEngine {
  review(input: DefectReviewRequestState): Promise<unknown>;
  status(): Promise<unknown>;
}
