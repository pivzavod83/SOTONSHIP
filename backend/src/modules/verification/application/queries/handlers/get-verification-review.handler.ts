import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { VerificationId } from '../../../domain/value-objects/verification-id';
import { ApplicationException } from '../../../../../common/exceptions/application.exception';
import { analysisIsCurrent } from '../../../../../common/config/verification-policy';
import { GetVerificationReviewQuery } from '../get-verification-review.query';
import { VerificationReviewRto } from '../../../presentation/rto/verification-review.rto';
@QueryHandler(GetVerificationReviewQuery)
export class GetVerificationReviewHandler implements IQueryHandler<GetVerificationReviewQuery> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly rows: IVerificationRepository) {}
  async execute(query: GetVerificationReviewQuery): Promise<VerificationReviewRto> {
    const run = await this.rows.findById(new VerificationId(query.verificationId));
    if (!run) throw new ApplicationException('Verification was not found.', 'verification.not_found', 404);
    const state = run.toPrimitives();
    return Object.assign(new VerificationReviewRto(), { verificationId: state.id,
      analysisStale: !analysisIsCurrent(state.provenanceJson, state.proofScope),
      humanReviewStatus: 'PENDING',
      currentReport: state.provenanceJson.reviewReport ?? { title: 'Legacy analysis requires re-verification', disposition: 'NEEDS_REVIEW', proofScope: state.proofScope },
      candidateReport: state.provenanceJson.candidateReview ?? null,
    });
  }
}
