import { ApiProperty } from '@nestjs/swagger';
import { VerificationSummaryRto } from './verification-summary.rto';

export class VerificationPageRto {
  @ApiProperty({ type: VerificationSummaryRto, isArray: true }) items!: VerificationSummaryRto[];
  @ApiProperty() page!: number;
  @ApiProperty() pageSize!: number;
  @ApiProperty() hasNext!: boolean;
}
