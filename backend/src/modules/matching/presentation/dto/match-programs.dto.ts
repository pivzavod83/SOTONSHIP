import { Type } from 'class-transformer';
import { ArrayMaxSize, ArrayMinSize, ArrayUnique, IsArray, IsIn, IsInt, IsOptional, IsString, Matches, Max, MaxLength, Min, MinLength, ValidateNested } from 'class-validator';
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { CobolSourceFormat } from '../../domain/value-objects/matching-request';

export class MatchingCandidateDto {
  @ApiProperty({ maxLength: 80 }) @IsString() @Matches(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/)
  candidateId!: string;
  @ApiProperty({ maxLength: 160 }) @IsString() @MinLength(1) @MaxLength(160) @Matches(/^[^\x00-\x1f/\\]+$/)
  moduleName!: string;
  @ApiProperty({ maxLength: 100000 }) @IsString() @MinLength(1) @MaxLength(100000)
  javaSource!: string;
}

export class MatchProgramsDto {
  @ApiProperty({ maxLength: 100000 }) @IsString() @MinLength(1) @MaxLength(100000)
  cobolSource!: string;
  @ApiPropertyOptional({ enum: ['AUTO', 'FREE', 'FIXED'], default: 'AUTO' }) @IsOptional() @IsIn(['AUTO', 'FREE', 'FIXED'])
  cobolSourceFormat?: CobolSourceFormat;
  @ApiProperty({ type: [MatchingCandidateDto], minItems: 1, maxItems: 20 })
  @IsArray() @ArrayMinSize(1) @ArrayMaxSize(20) @ArrayUnique((candidate: MatchingCandidateDto) => candidate?.candidateId)
  @ValidateNested({ each: true }) @Type(() => MatchingCandidateDto)
  candidates!: MatchingCandidateDto[];
  @ApiPropertyOptional({ minimum: 1, maximum: 20, default: 5 }) @IsOptional() @IsInt() @Min(1) @Max(20)
  topK?: number;
}
