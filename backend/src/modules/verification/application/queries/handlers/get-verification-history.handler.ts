import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { IVerificationHistoryRepository, VERIFICATION_HISTORY } from '../../../domain/repositories/verification-history.repository';
import { VerificationId } from '../../../domain/value-objects/verification-id';
import { ApplicationException } from '../../../../../common/exceptions/application.exception';
import { GetVerificationHistoryQuery } from '../get-verification-history.query';
import { VerificationRevisionRto } from '../../../presentation/rto/verification-review.rto';
@QueryHandler(GetVerificationHistoryQuery)
export class GetVerificationHistoryHandler implements IQueryHandler<GetVerificationHistoryQuery> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly rows: IVerificationRepository,
    @Inject(VERIFICATION_HISTORY) private readonly history: IVerificationHistoryRepository) {}
  async execute(query: GetVerificationHistoryQuery): Promise<VerificationRevisionRto[]> {
    const id = new VerificationId(query.verificationId);
    if (!await this.rows.findById(id)) throw new ApplicationException('Verification was not found.', 'verification.not_found', 404);
    return (await this.history.findByVerification(id)).map(row => Object.assign(new VerificationRevisionRto(), {
      version: row.version, recordedAt: row.recordedAt.toISOString(), snapshot: row.snapshot,
    }));
  }
}
