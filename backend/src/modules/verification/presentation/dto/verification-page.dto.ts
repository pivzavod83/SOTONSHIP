import { Type } from 'class-transformer';
import { IsInt, Max, Min } from 'class-validator';

export class VerificationPageDto {
  @Type(() => Number) @IsInt() @Min(1) @Max(10000)
  page = 1;

  @Type(() => Number) @IsInt() @Min(1) @Max(100)
  pageSize = 50;
}
