import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { MikroOrmModule } from '@mikro-orm/nestjs';
import config from './mikro-orm.config';
import { VerificationModule } from './modules/verification/verification.module';
import { FxRatesModule } from './modules/fx-rates/fx-rates.module';
import { JwtAuthGuard } from './common/auth/jwt-auth.guard';

@Module({ imports: [MikroOrmModule.forRoot(config), VerificationModule, FxRatesModule], providers: [{ provide: APP_GUARD, useClass: JwtAuthGuard }] })
export class AppModule {}
