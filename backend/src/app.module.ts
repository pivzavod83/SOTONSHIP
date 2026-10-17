import { Module } from '@nestjs/common';
import { MikroOrmModule } from '@mikro-orm/nestjs';
import config from './mikro-orm.config';
import { VerificationModule } from './modules/verification/verification.module';
import { FxRatesModule } from './modules/fx-rates/fx-rates.module';

@Module({ imports: [MikroOrmModule.forRoot(config), VerificationModule, FxRatesModule] })
export class AppModule {}
