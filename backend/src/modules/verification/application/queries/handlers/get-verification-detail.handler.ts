import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { VerificationId } from '../../../domain/value-objects/verification-id';
import { VerificationDetailRto } from '../../../presentation/rto/verification-detail.rto';
import { GetVerificationDetailQuery } from '../get-verification-detail.query';
import { ApplicationException } from '../../../../../common/exceptions/application.exception';
import { TranslationKey } from '../../../../../common/i18n/translation-key';

@QueryHandler(GetVerificationDetailQuery)
export class GetVerificationDetailHandler implements IQueryHandler<GetVerificationDetailQuery> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly repository: IVerificationRepository) {}
  async execute(query: GetVerificationDetailQuery): Promise<VerificationDetailRto> {
    const run = await this.repository.findById(new VerificationId(query.id));
    if (!run) throw new ApplicationException('Verification was not found.', TranslationKey.VerificationNotFound, 404);
    return VerificationDetailRto.fromDomain(run);
  }
}
