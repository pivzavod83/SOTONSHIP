import { Controller, Get } from '@nestjs/common';
import { QueryBus } from '@nestjs/cqrs';
import { ApiOkResponse, ApiTags } from '@nestjs/swagger';
import { GetReferenceFxRatesQuery } from '../../application/queries/get-reference-fx-rates.query';
import { Roles } from '../../../../common/auth/roles.decorator';
import { ReferenceFxRateRto } from '../rto/reference-fx-rate.rto';

@ApiTags('Reference FX rates')
@Controller('fx-rates')
export class FxRatesController {
  constructor(private readonly queryBus: QueryBus) {}
  @Get()
  @Roles('verifications:read')
  @ApiOkResponse({ type: ReferenceFxRateRto, isArray: true })
  list(): Promise<ReferenceFxRateRto[]> { return this.queryBus.execute(new GetReferenceFxRatesQuery()); }
}
