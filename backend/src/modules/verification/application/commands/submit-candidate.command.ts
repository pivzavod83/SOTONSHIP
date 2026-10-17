import { SubmitCandidateDto } from '../../presentation/dto/submit-candidate.dto';
export class SubmitCandidateCommand { constructor(readonly verificationId: string, readonly dto: SubmitCandidateDto) {} }
