import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { PythonWorkerModule } from '../../common/infrastructure/python/python-worker.module';
import { PROGRAM_MATCHING_ENGINE } from './application/ports/program-matching-engine';
import { MatchProgramsHandler } from './application/queries/handlers/match-programs.handler';
import { PythonProgramMatchingService } from './infrastructure/ml-bridge/python-program-matching.service';
import { MatchingController } from './presentation/controllers/matching.controller';

/** Read-only discovery has no persistent aggregate; verification is a separate use case. */
@Module({
  imports: [CqrsModule, PythonWorkerModule],
  controllers: [MatchingController],
  providers: [{ provide: PROGRAM_MATCHING_ENGINE, useClass: PythonProgramMatchingService }, MatchProgramsHandler],
})
export class MatchingModule {}
