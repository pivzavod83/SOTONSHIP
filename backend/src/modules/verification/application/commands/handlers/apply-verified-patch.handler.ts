import { Inject } from '@nestjs/common';
import { CommandHandler, EventBus, ICommandHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { PatchedVerificationRun } from '../../../domain/entities/patched-verification-run';
import { VerificationId } from '../../../domain/value-objects/verification-id';
import { FormalProofStatusValue } from '../../../domain/enums/formal-proof-status.enum';
import { IMlBridge, ML_BRIDGE } from '../../ports/ml-bridge';
import { FX_RATE_REPOSITORY, IReferenceFxRateRepository } from '../../../../fx-rates/domain/repositories/reference-fx-rate.repository';
import { VerificationDetailRto } from '../../../presentation/rto/verification-detail.rto';
import { ApplyVerifiedPatchCommand } from '../apply-verified-patch.command';
import { validatedAnalysis } from '../../services/validated-analysis';
import { ApplicationException } from '../../../../../common/exceptions/application.exception';
import { TranslationKey } from '../../../../../common/i18n/translation-key';

@CommandHandler(ApplyVerifiedPatchCommand)
export class ApplyVerifiedPatchHandler implements ICommandHandler<ApplyVerifiedPatchCommand> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly repository: IVerificationRepository,
    @Inject(ML_BRIDGE) private readonly engine: IMlBridge,
    @Inject(FX_RATE_REPOSITORY) private readonly rates: IReferenceFxRateRepository,
    private readonly eventBus: EventBus) {}

  async execute({ verificationId }: ApplyVerifiedPatchCommand): Promise<VerificationDetailRto> {
    const original = await this.repository.findById(new VerificationId(verificationId));
    if (!original) throw new ApplicationException('Verification was not found.', TranslationKey.VerificationNotFound, 404);
    const state = original.toPrimitives();
    if (!state.patchedJavaSource.trim()) {
      throw new ApplicationException('This verification has no patch candidate.', TranslationKey.PatchNotProven);
    }
    const context = { ...state, javaSource: state.patchedJavaSource };
    const result = await this.engine.verify({
      id: state.id, moduleName: state.moduleName, category: state.category, cobolSource: state.cobolSource,
      javaSource: state.patchedJavaSource, patchedJavaSource: state.patchedJavaSource,
      referenceFxRates: (await this.rates.findAll()).map((rate) => rate.toPrimitives()),
    });
    if (result.formalProofStatus !== FormalProofStatusValue.UNSAT_PROVEN_SAFE) {
      throw new ApplicationException('The candidate did not receive a supported UNSAT proof; the original source is preserved.', TranslationKey.PatchNotProven);
    }
    const run = new PatchedVerificationRun(original, validatedAnalysis(result, context));
    const saved = await this.repository.save(run);
    this.eventBus.publishAll(run.pullEvents());
    return VerificationDetailRto.fromDomain(saved);
  }
}
