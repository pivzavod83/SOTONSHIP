import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { PythonWorkerModule } from '../../common/infrastructure/python/python-worker.module';
import { DEFECT_REVIEW_ENGINE } from './application/ports/defect-review-engine';
import { GetDefectModelStatusHandler } from './application/queries/handlers/get-defect-model-status.handler';
import { ReviewDefectsHandler } from './application/queries/handlers/review-defects.handler';
import { PythonDefectReviewService } from './infrastructure/ml-bridge/python-defect-review.service';
import { DefectReviewController } from './presentation/controllers/defect-review.controller';

/** Read-only learned defect triage has no persistence or dependency on proof/patch commands. */
@Module({
  imports: [CqrsModule, PythonWorkerModule], controllers: [DefectReviewController],
  providers: [{ provide: DEFECT_REVIEW_ENGINE, useClass: PythonDefectReviewService }, ReviewDefectsHandler, GetDefectModelStatusHandler],
})
export class DefectDetectionModule {}
