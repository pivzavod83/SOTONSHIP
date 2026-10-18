import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsIn, IsOptional, IsString, Matches, MaxLength, MinLength } from 'class-validator';
import { ReviewCobolSourceFormat } from '../../domain/value-objects/ai-review-request';

export class ReviewPairDto {
  @ApiProperty({ maxLength: 160 }) @IsString() @MinLength(1) @MaxLength(160) @Matches(/^[^\x00-\x1f]+$/)
  moduleName!: string;
  @ApiProperty({ maxLength: 100000 }) @IsString() @MinLength(1) @MaxLength(100000)
  cobolSource!: string;
  @ApiProperty({ maxLength: 100000 }) @IsString() @MinLength(1) @MaxLength(100000)
  javaSource!: string;
  @ApiPropertyOptional({ enum: ['AUTO', 'FREE', 'FIXED'], default: 'AUTO' }) @IsOptional() @IsIn(['AUTO', 'FREE', 'FIXED'])
  cobolSourceFormat?: ReviewCobolSourceFormat;
  @ApiPropertyOptional({ maxLength: 8000, description: 'Optional interface assumptions and observations, never proof premises.' })
  @IsOptional() @IsString() @MaxLength(8000)
  analysisContext?: string;
}
