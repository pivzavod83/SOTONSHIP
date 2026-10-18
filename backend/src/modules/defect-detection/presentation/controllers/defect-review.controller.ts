import { Body, Controller, Get, HttpCode, Post } from '@nestjs/common';
import { QueryBus } from '@nestjs/cqrs';
import { ApiBadRequestResponse, ApiOkResponse, ApiOperation, ApiServiceUnavailableResponse, ApiTags } from '@nestjs/swagger';
import { ErrorRto } from '../../../../common/rto/error.rto';
import { GetDefectModelStatusQuery } from '../../application/queries/get-defect-model-status.query';
import { ReviewDefectsQuery } from '../../application/queries/review-defects.query';
import { ReviewDefectsDto } from '../dto/review-defects.dto';
import { DefectModelStatusRto, DefectReviewRto } from '../rto/defect-review.rto';

@ApiTags('Local defect detection')
@Controller('defect-reviews')
export class DefectReviewController {
  constructor(private readonly queryBus: QueryBus) {}

  @Post() @HttpCode(200)
  @ApiOperation({ summary: 'Assess a supplied COBOL–Java pair with a locally trained model. Findings are source-bound hypotheses, not equivalence proof.' })
  @ApiOkResponse({ type: DefectReviewRto })
  @ApiBadRequestResponse({ type: ErrorRto })
  @ApiServiceUnavailableResponse({ type: ErrorRto })
  review(@Body() dto: ReviewDefectsDto): Promise<DefectReviewRto> { return this.queryBus.execute(new ReviewDefectsQuery(dto)); }

  @Get('status')
  @ApiOperation({ summary: 'Inspect the local defect model provenance and synthetic-pilot evaluation. Requires no API credentials.' })
  @ApiOkResponse({ type: DefectModelStatusRto })
  @ApiServiceUnavailableResponse({ type: ErrorRto })
  status(): Promise<DefectModelStatusRto> { return this.queryBus.execute(new GetDefectModelStatusQuery()); }
}
