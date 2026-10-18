import { AiReviewRequestState } from '../../domain/value-objects/ai-review-request';

export const AI_DEFECT_REVIEW_ENGINE = 'IAiDefectReviewEngine';
export interface IAiDefectReviewEngine { review(input: AiReviewRequestState): Promise<unknown>; }
