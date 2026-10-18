import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsIn, IsInt, IsOptional, IsString, MaxLength, Min, Max, MinLength, Matches, ValidateNested } from 'class-validator';
import { Type } from 'class-transformer';
import { VerificationCategory } from '../../domain/enums/verification-category.enum';

export class ProofInputsDto {
  @ApiProperty({ enum: ['IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1'] })
  @IsIn(['IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1']) cobolDialectProfile!: 'IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1';
  @ApiProperty({ enum: ['FREE', 'FIXED'] }) @IsIn(['FREE', 'FIXED']) cobolSourceFormat!: 'FREE' | 'FIXED';
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(64) amountField!: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(64) rateField!: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(64) resultField!: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(64) javaAmountParameter!: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(64) javaRateParameter!: string;
  @ApiProperty() @IsInt() @Min(-999999999) @Max(999999999) amountMinCents!: number;
  @ApiProperty() @IsInt() @Min(-999999999) @Max(999999999) amountMaxCents!: number;
  @ApiProperty({ example: 'GBP/EUR' }) @Matches(/^[A-Z]{3}\/[A-Z]{3}$/) referenceCurrencyPair!: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(300) referenceSource!: string;
  @ApiProperty({ example: '2026-10-16' }) @Matches(/^\d{4}-\d{2}-\d{2}$/) referenceCollectedDate!: string;
}

export class RunVerificationDto {
  @ApiProperty({ example: 'FX-WIRE-CALC.cbl', maxLength: 160 })
  @IsString() @MinLength(1) @MaxLength(160) @Matches(/^[^\x00-\x1f/\\]+$/)
  moduleName!: string;

  @ApiProperty({ enum: VerificationCategory }) @IsEnum(VerificationCategory)
  category!: VerificationCategory;

  @ApiPropertyOptional({ type: ProofInputsDto, description: 'Exact field mapping, cent bounds and reference-rate identity. Missing or mismatched proof inputs produce UNKNOWN.' })
  @IsOptional() @ValidateNested() @Type(() => ProofInputsDto)
  proofInputs?: ProofInputsDto;

  @ApiProperty({ maxLength: 100000 }) @IsString() @MinLength(1) @MaxLength(100000)
  cobolSource!: string;

  @ApiProperty({ maxLength: 100000 }) @IsString() @MinLength(1) @MaxLength(100000)
  javaSource!: string;

  @ApiPropertyOptional({ maxLength: 100000, description: 'Optional candidate; applying it always requires a fresh supported UNSAT proof.' })
  @IsOptional() @IsString() @MaxLength(100000)
  patchedJavaSource?: string;
}
