import { Body, Controller, HttpCode, Post } from '@nestjs/common';
import { QueryBus } from '@nestjs/cqrs';
import { ApiBadRequestResponse, ApiOkResponse, ApiOperation, ApiServiceUnavailableResponse, ApiTags } from '@nestjs/swagger';
import { ErrorRto } from '../../../../common/rto/error.rto';
import { ReviewPairQuery } from '../../application/queries/review-pair.query';
import { ReviewPairDto } from '../dto/review-pair.dto';
import { AiReviewRto } from '../rto/ai-review.rto';

@ApiTags('AI defect review')
@Controller('ai-reviews')
export class AiReviewController {
  constructor(private readonly queryBus: QueryBus) {}

  @Post() @HttpCode(200)
  @ApiOperation({ summary: 'Review a supplied COBOL–Java pair for suspected semantic defects with the configured coding LLM. Findings and suggested inputs are unverified hypotheses.' })
  @ApiOkResponse({ type: AiReviewRto })
  @ApiBadRequestResponse({ type: ErrorRto })
  @ApiServiceUnavailableResponse({ type: ErrorRto })
  review(@Body() dto: ReviewPairDto): Promise<AiReviewRto> { return this.queryBus.execute(new ReviewPairQuery(dto)); }
}
