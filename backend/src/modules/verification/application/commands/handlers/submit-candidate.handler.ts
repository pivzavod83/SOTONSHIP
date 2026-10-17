import { Inject } from '@nestjs/common';
import { CommandHandler, ICommandHandler } from '@nestjs/cqrs';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { VerificationId } from '../../../domain/value-objects/verification-id';
import { VerificationRun } from '../../../domain/entities/verification-run';
import { CodeSnippet } from '../../../domain/value-objects/code-snippet';
import { IMlBridge, ML_BRIDGE } from '../../ports/ml-bridge';
import { IReferenceFxRateRepository, FX_RATE_REPOSITORY } from '../../../../fx-rates/domain/repositories/reference-fx-rate.repository';
import { ApplicationException } from '../../../../../common/exceptions/application.exception';
import { JsonObject } from '../../../../../common/value-objects/json-value';
import { validatedAnalysis } from '../../services/validated-analysis';
import { SubmitCandidateCommand } from '../submit-candidate.command';
import { VerificationDetailRto } from '../../../presentation/rto/verification-detail.rto';
@CommandHandler(SubmitCandidateCommand)
export class SubmitCandidateHandler implements ICommandHandler<SubmitCandidateCommand> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly rows: IVerificationRepository,
    @Inject(ML_BRIDGE) private readonly engine: IMlBridge, @Inject(FX_RATE_REPOSITORY) private readonly rates: IReferenceFxRateRepository) {}
  async execute(command: SubmitCandidateCommand): Promise<VerificationDetailRto> {
    const original = await this.rows.findById(new VerificationId(command.verificationId));
    if (!original) throw new ApplicationException('Verification was not found.', 'verification.not_found', 404);
    const state = original.toPrimitives();
    const candidate = new CodeSnippet(command.dto.javaSource).value;
    const context = { ...state, javaSource: candidate, patchedJavaSource: candidate };
    const result = await this.engine.verify({ id: state.id, moduleName: state.moduleName, category: state.category,
      cobolSource: state.cobolSource, javaSource: candidate, patchedJavaSource: candidate,
      referenceFxRates: (await this.rates.findAll()).map(rate => rate.toPrimitives()) });
    const analysis = validatedAnalysis(result, context);
    const run = new VerificationRun({ ...state, patchedJavaSource: candidate, updatedAt: new Date(), provenanceJson: {
      ...state.provenanceJson, candidateReview: { submittedAt: new Date().toISOString(), analysis: analysis as unknown as JsonObject },
    } });
    return VerificationDetailRto.fromDomain(await this.rows.save(run));
  }
}
