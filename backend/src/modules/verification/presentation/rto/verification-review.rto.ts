import { ApiProperty } from '@nestjs/swagger';
import { JsonObject, JsonValue } from '../../../../common/value-objects/json-value';
export class VerificationReviewRto {
  @ApiProperty() verificationId!: string;
  @ApiProperty() analysisStale!: boolean;
  @ApiProperty() humanReviewStatus!: string;
  @ApiProperty({ type: 'object', additionalProperties: true }) currentReport!: JsonObject;
  @ApiProperty({ type: 'object', additionalProperties: true, nullable: true }) candidateReport!: JsonValue;
}
export class VerificationRevisionRto {
  @ApiProperty() version!: number;
  @ApiProperty() recordedAt!: string;
  @ApiProperty({ type: 'object', additionalProperties: true }) snapshot!: JsonObject;
}
