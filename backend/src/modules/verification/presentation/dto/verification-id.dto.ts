import { ApiProperty } from '@nestjs/swagger';
import { IsUUID } from 'class-validator';

export class VerificationIdDto {
  @ApiProperty({ format: 'uuid' }) @IsUUID()
  id!: string;
}
