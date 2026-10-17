import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { MikroOrmModule } from '@mikro-orm/nestjs';
import { ReferenceFxRateEntity } from './entities/reference-fx-rate.entity';
import { FX_RATE_REPOSITORY } from './domain/repositories/reference-fx-rate.repository';
import { MikroOrmReferenceFxRateRepository } from './infrastructure/repositories/mikro-orm-reference-fx-rate.repository';
import { GetReferenceFxRatesHandler } from './application/queries/handlers/get-reference-fx-rates.handler';
import { FxRatesController } from './presentation/controllers/fx-rates.controller';

@Module({
  imports: [CqrsModule, MikroOrmModule.forFeature([ReferenceFxRateEntity])],
  providers: [{ provide: FX_RATE_REPOSITORY, useClass: MikroOrmReferenceFxRateRepository }, GetReferenceFxRatesHandler],
  controllers: [FxRatesController], exports: [FX_RATE_REPOSITORY],
})
export class FxRatesModule {}
