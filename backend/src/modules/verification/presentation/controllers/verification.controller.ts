import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { CommandBus, QueryBus } from '@nestjs/cqrs';
import { ApiBadRequestResponse, ApiCreatedResponse, ApiNotFoundResponse, ApiOkResponse, ApiOperation, ApiTags, ApiUnprocessableEntityResponse } from '@nestjs/swagger';
import { GetVerificationsListQuery } from '../../application/queries/get-verifications-list.query';
import { GetVerificationDetailQuery } from '../../application/queries/get-verification-detail.query';
import { GetBaselineComparisonMetricsQuery } from '../../application/queries/get-baseline-comparison-metrics.query';
import { RunVerificationCommand } from '../../application/commands/run-verification.command';
import { ApplyVerifiedPatchCommand } from '../../application/commands/apply-verified-patch.command';
import { RunVerificationDto } from '../dto/run-verification.dto';
import { VerificationIdDto } from '../dto/verification-id.dto';
import { VerificationSummaryRto } from '../rto/verification-summary.rto';
import { VerificationDetailRto } from '../rto/verification-detail.rto';
import { BaselineComparisonRto } from '../rto/baseline-comparison.rto';
import { ErrorRto } from '../../../../common/rto/error.rto';

@ApiTags('Verifications')
@ApiBadRequestResponse({ type: ErrorRto })
@Controller('verifications')
export class VerificationController {
  constructor(private readonly commandBus: CommandBus, private readonly queryBus: QueryBus) {}

  @Get()
  @ApiOkResponse({ type: VerificationSummaryRto, isArray: true })
  list(): Promise<VerificationSummaryRto[]> { return this.queryBus.execute(new GetVerificationsListQuery()); }

  @Get('baseline-comparison')
  @ApiOkResponse({ type: BaselineComparisonRto })
  metrics(): Promise<BaselineComparisonRto> { return this.queryBus.execute(new GetBaselineComparisonMetricsQuery()); }

  @Get(':id')
  @ApiOkResponse({ type: VerificationDetailRto })
  @ApiNotFoundResponse({ type: ErrorRto })
  detail(@Param() params: VerificationIdDto): Promise<VerificationDetailRto> {
    return this.queryBus.execute(new GetVerificationDetailQuery(params.id));
  }

  @Post()
  @ApiOperation({ summary: 'Analyse restricted COBOL/Java source; unsupported semantics return UNKNOWN.' })
  @ApiCreatedResponse({ type: VerificationDetailRto })
  run(@Body() dto: RunVerificationDto): Promise<VerificationDetailRto> { return this.commandBus.execute(new RunVerificationCommand(dto)); }

  @Post(':id/apply-patch')
  @ApiOperation({ summary: 'Re-prove the candidate and replace Java source only for supported, bounded UNSAT.' })
  @ApiCreatedResponse({ type: VerificationDetailRto })
  @ApiNotFoundResponse({ type: ErrorRto })
  @ApiUnprocessableEntityResponse({ type: ErrorRto })
  applyPatch(@Param() params: VerificationIdDto): Promise<VerificationDetailRto> {
    return this.commandBus.execute(new ApplyVerifiedPatchCommand(params.id));
  }
}
