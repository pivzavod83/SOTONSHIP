import { Controller, Get } from '@nestjs/common';
import { QueryBus } from '@nestjs/cqrs';
import { ApiOkResponse, ApiTags } from '@nestjs/swagger';
import { GetGenerationConfigurationQuery } from '../../application/queries/get-generation-configuration.query';
import { GenerationConfigurationRto } from '../rto/generation-configuration.rto';
@ApiTags('Generation configuration')
@Controller('generation')
export class GenerationController {
  constructor(private readonly queries: QueryBus) {}
  @Get('configuration') @ApiOkResponse({ type: GenerationConfigurationRto })
  configuration(): Promise<GenerationConfigurationRto> { return this.queries.execute(new GetGenerationConfigurationQuery()); }
}
