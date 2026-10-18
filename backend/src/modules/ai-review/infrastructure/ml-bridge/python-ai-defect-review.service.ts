import { Injectable } from '@nestjs/common';
import { PythonJsonWorkerService } from '../../../../common/infrastructure/python/python-json-worker.service';
import { IAiDefectReviewEngine } from '../../application/ports/ai-defect-review-engine';
import { AiReviewRequestState } from '../../domain/value-objects/ai-review-request';

@Injectable()
export class PythonAiDefectReviewService implements IAiDefectReviewEngine {
  constructor(private readonly worker: PythonJsonWorkerService) {}

  review(input: AiReviewRequestState): Promise<unknown> { return this.worker.execute('ml_engine.ai_review', input); }
}
