import { ApiProperty } from '@nestjs/swagger';
export class GenerationConfigurationRto {
  @ApiProperty() adapterEnabled!: boolean;
  @ApiProperty() apiKeyPresent!: boolean;
  @ApiProperty() providerSelected!: boolean;
  @ApiProperty() modelSelected!: boolean;
  @ApiProperty() baseUrlPresent!: boolean;
  @ApiProperty() message!: string;
}
