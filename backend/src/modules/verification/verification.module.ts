import { VerificationRevisionEntity } from './entities/verification-revision.entity';
import { VERIFICATION_HISTORY } from './domain/repositories/verification-history.repository';
import { MikroOrmVerificationHistoryRepository } from './infrastructure/repositories/mikro-orm-verification-history.repository';
import { ReverifyVerificationHandler } from './application/commands/handlers/reverify-verification.handler';
import { SubmitCandidateHandler } from './application/commands/handlers/submit-candidate.handler';
import { GetVerificationReviewHandler } from './application/queries/handlers/get-verification-review.handler';
import { GetVerificationHistoryHandler } from './application/queries/handlers/get-verification-history.handler';
import { CODE_GENERATION_PROVIDER } from './application/ports/code-generation-provider';
import { UnconfiguredCodeGenerationProvider } from './infrastructure/llm-bridge/unconfigured-code-generation.provider';
import { GetGenerationConfigurationHandler } from './application/queries/handlers/get-generation-configuration.handler';
import { GenerationController } from './presentation/controllers/generation.controller';
import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { MikroOrmModule } from '@mikro-orm/nestjs';
import { VerificationEntity } from './entities/verification.entity';
import { VERIFICATION_REPOSITORY } from './domain/repositories/verification.repository';
import { MikroOrmVerificationRepository } from './infrastructure/repositories/mikro-orm-verification.repository';
import { PythonMlBridgeService } from './infrastructure/ml-bridge/python-ml-bridge.service';
import { ML_BRIDGE } from './application/ports/ml-bridge';
import { VerificationController } from './presentation/controllers/verification.controller';
import { GetVerificationsListHandler } from './application/queries/handlers/get-verifications-list.handler';
import { GetVerificationDetailHandler } from './application/queries/handlers/get-verification-detail.handler';
import { GetBaselineComparisonMetricsHandler } from './application/queries/handlers/get-baseline-comparison-metrics.handler';
import { RunVerificationHandler } from './application/commands/handlers/run-verification.handler';
import { ApplyVerifiedPatchHandler } from './application/commands/handlers/apply-verified-patch.handler';
import { FxRatesModule } from '../fx-rates/fx-rates.module';

@Module({
  imports: [CqrsModule, FxRatesModule, MikroOrmModule.forFeature([VerificationEntity, VerificationRevisionEntity])],
  controllers: [VerificationController, GenerationController],
  providers: [
    { provide: VERIFICATION_HISTORY, useClass: MikroOrmVerificationHistoryRepository },
    ReverifyVerificationHandler, SubmitCandidateHandler, GetVerificationReviewHandler, GetVerificationHistoryHandler,
    { provide: CODE_GENERATION_PROVIDER, useClass: UnconfiguredCodeGenerationProvider },
    GetGenerationConfigurationHandler,
    { provide: VERIFICATION_REPOSITORY, useClass: MikroOrmVerificationRepository },
    { provide: ML_BRIDGE, useClass: PythonMlBridgeService },
    GetVerificationsListHandler, GetVerificationDetailHandler, GetBaselineComparisonMetricsHandler,
    RunVerificationHandler, ApplyVerifiedPatchHandler,
  ],
})
export class VerificationModule {}
