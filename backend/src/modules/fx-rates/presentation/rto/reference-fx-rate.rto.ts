import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { ReferenceFxRate } from '../../domain/entities/reference-fx-rate';
import { JsonObject } from '../../../../common/value-objects/json-value';

export class ReferenceFxRateRto {
  @ApiProperty({ format: 'uuid' }) id!: string;
  @ApiProperty({ example: 'GBP/EUR' }) currencyPair!: string;
  @ApiProperty({ example: '1.158600000000', description: 'Exact decimal string; never a binary floating-point amount.' }) rate!: string;
  @ApiProperty() source!: string;
  @ApiProperty({ format: 'date' }) collectedDate!: string;
  @ApiPropertyOptional({ format: 'date', description: 'Actual market observation date, distinct from collection date.' }) observationDate?: string;
  @ApiProperty({ type: 'object', additionalProperties: true, description: 'Source URLs, licence and historical provider/survey metadata.' }) provenanceJson!: JsonObject;
  static fromDomain(rate: ReferenceFxRate): ReferenceFxRateRto { return Object.assign(new ReferenceFxRateRto(), rate.toPrimitives()); }
}
