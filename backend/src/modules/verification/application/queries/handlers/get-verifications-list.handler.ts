import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { VerificationSummaryRto } from '../../../presentation/rto/verification-summary.rto';
import { VerificationPageRto } from '../../../presentation/rto/verification-page.rto';
import { GetVerificationsListQuery } from '../get-verifications-list.query';

@QueryHandler(GetVerificationsListQuery)
export class GetVerificationsListHandler implements IQueryHandler<GetVerificationsListQuery> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly repository: IVerificationRepository) {}
  async execute(query: GetVerificationsListQuery): Promise<VerificationPageRto> {
    const rows = await this.repository.findPage(query.pageSize + 1, (query.page - 1) * query.pageSize);
    const hasNext = rows.length > query.pageSize;
    return Object.assign(new VerificationPageRto(), {
      items: rows.slice(0, query.pageSize).map(VerificationSummaryRto.fromDomain),
      page: query.page, pageSize: query.pageSize, hasNext,
    });
  }
}
