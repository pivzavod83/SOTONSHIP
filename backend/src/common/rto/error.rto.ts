import { ApiProperty } from '@nestjs/swagger';

export class ErrorRto {
  @ApiProperty() statusCode!: number;
  @ApiProperty() code!: string;
  @ApiProperty() message!: string | string[];
}
