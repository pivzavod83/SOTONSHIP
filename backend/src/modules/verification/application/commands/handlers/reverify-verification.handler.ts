import { Inject } from '@nestjs/common';
import { CommandHandler, EventBus, ICommandHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { VerificationId } from '../../../domain/value-objects/verification-id';
import { ReverifiedVerificationRun } from '../../../domain/entities/reverified-verification-run';
import { IMlBridge, ML_BRIDGE } from '../../ports/ml-bridge';
import { IReferenceFxRateRepository, FX_RATE_REPOSITORY } from '../../../../fx-rates/domain/repositories/reference-fx-rate.repository';
import { ApplicationException } from '../../../../../common/exceptions/application.exception';
import { validatedAnalysis } from '../../services/validated-analysis';
import { ReverifyVerificationCommand } from '../reverify-verification.command';
import { VerificationDetailRto } from '../../../presentation/rto/verification-detail.rto';
@CommandHandler(ReverifyVerificationCommand)
export class ReverifyVerificationHandler implements ICommandHandler<ReverifyVerificationCommand> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly rows: IVerificationRepository,
    @Inject(ML_BRIDGE) private readonly engine: IMlBridge, @Inject(FX_RATE_REPOSITORY) private readonly rates: IReferenceFxRateRepository,
    private readonly events: EventBus) {}
  async execute(command: ReverifyVerificationCommand): Promise<VerificationDetailRto> {
    const original = await this.rows.findById(new VerificationId(command.verificationId));
    if (!original) throw new ApplicationException('Verification was not found.', 'verification.not_found', 404);
    const state = original.toPrimitives();
    const result = await this.engine.verify({ id: state.id, moduleName: state.moduleName, category: state.category,
      cobolSource: state.cobolSource, javaSource: state.javaSource, patchedJavaSource: state.patchedJavaSource,
      referenceFxRates: (await this.rates.findAll()).map(rate => rate.toPrimitives()) });
    const analysis = validatedAnalysis(result, state);
    if (state.provenanceJson.candidateReview) analysis.provenanceJson.candidateReview = state.provenanceJson.candidateReview;
    const run = new ReverifiedVerificationRun({ ...state, ...analysis, updatedAt: new Date() });
    const saved = await this.rows.save(run);
    this.events.publishAll(run.pullEvents());
    return VerificationDetailRto.fromDomain(saved);
  }
}
