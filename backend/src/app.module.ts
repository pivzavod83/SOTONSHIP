import { Module } from '@nestjs/common';
import { MikroOrmModule } from '@mikro-orm/nestjs';
import config from './mikro-orm.config';
import { VerificationModule } from './modules/verification/verification.module';
import { FxRatesModule } from './modules/fx-rates/fx-rates.module';
import { MatchingModule } from './modules/matching/matching.module';
import { AiReviewModule } from './modules/ai-review/ai-review.module';
import { DefectDetectionModule } from './modules/defect-detection/defect-detection.module';

@Module({ imports: [MikroOrmModule.forRoot(config), VerificationModule, FxRatesModule, MatchingModule, AiReviewModule, DefectDetectionModule] })
export class AppModule {}
