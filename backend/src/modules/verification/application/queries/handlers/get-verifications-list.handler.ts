import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { VerificationSummaryRto } from '../../../presentation/rto/verification-summary.rto';
import { GetVerificationsListQuery } from '../get-verifications-list.query';

@QueryHandler(GetVerificationsListQuery)
export class GetVerificationsListHandler implements IQueryHandler<GetVerificationsListQuery> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly repository: IVerificationRepository) {}
  async execute(): Promise<VerificationSummaryRto[]> { return (await this.repository.findAll()).map(VerificationSummaryRto.fromDomain); }
}
