import { Injectable } from '@nestjs/common';
import { PythonJsonWorkerService } from '../../../../common/infrastructure/python/python-json-worker.service';
import { IDefectReviewEngine } from '../../application/ports/defect-review-engine';
import { DefectReviewRequestState } from '../../domain/value-objects/defect-review-request';

@Injectable()
export class PythonDefectReviewService implements IDefectReviewEngine {
  constructor(private readonly worker: PythonJsonWorkerService) {}
  review(input: DefectReviewRequestState): Promise<unknown> { return this.worker.execute('ml_engine.defect_detection', input); }
  status(): Promise<unknown> { return this.worker.execute('ml_engine.defect_detection', { action: 'status' }); }
}
