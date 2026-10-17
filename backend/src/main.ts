import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { json } from 'express';
import { AppModule } from './app.module';
import { GlobalExceptionFilter } from './common/exceptions/global-exception.filter';
import { verificationPolicy } from './common/config/verification-policy';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { bodyParser: false });
  app.use(json({ limit: verificationPolicy.maxJsonBytes }));
  app.setGlobalPrefix('api');
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
  app.useGlobalFilters(new GlobalExceptionFilter());
  app.enableShutdownHooks();
  const swagger = new DocumentBuilder()
    .setTitle('Neuro-Symbolic COBOL-to-Java Financial Verifier')
    .setDescription('Layered DDD + CQRS + MikroORM. SAT supplies counterexamples; UNSAT applies only within explicit proofScope; unsupported programs remain UNKNOWN.')
    .setVersion('1.0.0').build();
  SwaggerModule.setup('api/docs', app, SwaggerModule.createDocument(app, swagger));
  await app.listen(Number(process.env.PORT ?? 3001), process.env.HOST ?? '0.0.0.0');
}

bootstrap().catch((error: unknown) => { console.error(error); process.exitCode = 1; });
