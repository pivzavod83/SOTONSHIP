import { ApiProperty } from '@nestjs/swagger';
import { IsSourceCode } from '../../../../common/decorators/is-source-code.decorator';
import { verificationPolicy } from '../../../../common/config/verification-policy';
export class SubmitCandidateDto {
  @ApiProperty({ maxLength: verificationPolicy.maxSourceCharacters, description: 'A complete Java candidate; current Java is retained until apply-patch succeeds.' })
  @IsSourceCode() javaSource!: string;
}
