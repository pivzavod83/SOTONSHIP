import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { PythonWorkerModule } from '../../common/infrastructure/python/python-worker.module';
import { AI_DEFECT_REVIEW_ENGINE } from './application/ports/ai-defect-review-engine';
import { ReviewPairHandler } from './application/queries/handlers/review-pair.handler';
import { PythonAiDefectReviewService } from './infrastructure/ml-bridge/python-ai-defect-review.service';
import { AiReviewController } from './presentation/controllers/ai-review.controller';

/** Read-only AI review has no persistence or authority over verification/patch commands. */
@Module({
  imports: [CqrsModule, PythonWorkerModule],
  controllers: [AiReviewController],
  providers: [{ provide: AI_DEFECT_REVIEW_ENGINE, useClass: PythonAiDefectReviewService }, ReviewPairHandler],
})
export class AiReviewModule {}
