import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsIn, IsOptional, IsString, Matches, MaxLength, MinLength } from 'class-validator';
import { DefectCobolSourceFormat } from '../../domain/value-objects/defect-review-request';

export class ReviewDefectsDto {
  @ApiProperty({ maxLength: 100000, description: 'Exact source, at most 200000 UTF-8 bytes and 1500 LF-delimited lines.' }) @IsString() @MinLength(1) @MaxLength(100000)
  cobolSource!: string;
  @ApiProperty({ maxLength: 100000, description: 'Exact source, at most 200000 UTF-8 bytes and 1500 LF-delimited lines.' }) @IsString() @MinLength(1) @MaxLength(100000)
  javaSource!: string;
  @ApiProperty({ enum: ['FREE', 'FIXED'] }) @IsIn(['FREE', 'FIXED'])
  cobolSourceFormat!: DefectCobolSourceFormat;
  @ApiPropertyOptional({ maxLength: 160 }) @IsOptional() @IsString() @MinLength(1) @MaxLength(160) @Matches(/^[^\x00-\x1f]+$/)
  moduleName?: string;
}
