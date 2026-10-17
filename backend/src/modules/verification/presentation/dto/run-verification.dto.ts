import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsOptional, IsString, MaxLength, MinLength, Matches } from 'class-validator';
import { VerificationCategory } from '../../domain/enums/verification-category.enum';

export class RunVerificationDto {
  @ApiProperty({ example: 'FX-WIRE-CALC.cbl', maxLength: 160 })
  @IsString() @MinLength(1) @MaxLength(160) @Matches(/^[^\x00-\x1f/\\]+$/)
  moduleName!: string;

  @ApiProperty({ enum: VerificationCategory }) @IsEnum(VerificationCategory)
  category!: VerificationCategory;

  @ApiProperty({ maxLength: 200000 }) @IsString() @MinLength(1) @MaxLength(200000)
  cobolSource!: string;

  @ApiProperty({ maxLength: 200000 }) @IsString() @MinLength(1) @MaxLength(200000)
  javaSource!: string;

  @ApiPropertyOptional({ maxLength: 200000, description: 'Optional candidate; applying it always requires a fresh supported UNSAT proof.' })
  @IsOptional() @IsString() @MaxLength(200000)
  patchedJavaSource?: string;
}
