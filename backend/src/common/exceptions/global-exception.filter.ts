import { ArgumentsHost, Catch, ExceptionFilter, HttpException, Logger } from '@nestjs/common';
import { Response } from 'express';
import { DomainException } from './domain.exception';
import { ApplicationException } from './application.exception';
import { InfrastructureException } from './infrastructure.exception';

@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(GlobalExceptionFilter.name);

  catch(error: unknown, host: ArgumentsHost): void {
    const response = host.switchToHttp().getResponse<Response>();
    let status = 500;
    let code = 'internal.error';
    let message: string | string[] = 'An unexpected error occurred.';
    if (error instanceof HttpException) {
      status = error.getStatus();
      code = `http.${status}`;
      const body = error.getResponse();
      message = typeof body === 'string' ? body : (body as { message: string | string[] }).message;
    } else if (error instanceof DomainException) {
      status = 400; code = error.code; message = error.message;
    } else if (error instanceof ApplicationException) {
      status = error.statusCode; code = error.code; message = error.message;
    } else if (error instanceof InfrastructureException) {
      status = 503; code = error.code; message = error.message;
    }
    if (status >= 500) this.logger.error(error instanceof Error ? error.stack : String(error));
    response.status(status).json({ statusCode: status, code, message });
  }
}
