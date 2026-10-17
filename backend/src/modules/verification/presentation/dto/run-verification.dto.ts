import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsOptional, IsString, MaxLength, MinLength, Matches } from 'class-validator';
import { IsSourceCode } from '../../../../common/decorators/is-source-code.decorator';
import { verificationPolicy } from '../../../../common/config/verification-policy';
import { VerificationCategory } from '../../domain/enums/verification-category.enum';

export class RunVerificationDto {
  @ApiProperty({ example: 'FX-WIRE-CALC.cbl', maxLength: 160 })
  @IsString() @MinLength(1) @MaxLength(160) @Matches(/^[^\x00-\x1f/\\]+$/)
  moduleName!: string;

  @ApiProperty({ enum: VerificationCategory }) @IsEnum(VerificationCategory)
  category!: VerificationCategory;

  @ApiProperty({ maxLength: verificationPolicy.maxSourceCharacters }) @IsSourceCode()
  cobolSource!: string;

  @ApiProperty({ maxLength: verificationPolicy.maxSourceCharacters }) @IsSourceCode()
  javaSource!: string;

  @ApiPropertyOptional({ maxLength: verificationPolicy.maxSourceCharacters, description: 'Optional candidate; applying it always requires a fresh supported UNSAT proof.' })
  @IsOptional() @IsSourceCode(true)
  patchedJavaSource?: string;
}
