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
import { PythonWorkerModule } from '../../common/infrastructure/python/python-worker.module';

@Module({
  imports: [CqrsModule, FxRatesModule, PythonWorkerModule, MikroOrmModule.forFeature([VerificationEntity])],
  controllers: [VerificationController],
  providers: [
    { provide: VERIFICATION_REPOSITORY, useClass: MikroOrmVerificationRepository },
    { provide: ML_BRIDGE, useClass: PythonMlBridgeService },
    GetVerificationsListHandler, GetVerificationDetailHandler, GetBaselineComparisonMetricsHandler,
    RunVerificationHandler, ApplyVerifiedPatchHandler,
  ],
})
export class VerificationModule {}
