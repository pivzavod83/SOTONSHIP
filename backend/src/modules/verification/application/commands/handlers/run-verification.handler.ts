import { Inject } from '@nestjs/common';
import { CommandHandler, EventBus, ICommandHandler } from '@nestjs/cqrs';
import { randomUUID } from 'node:crypto';
import { IVerificationRepository, VERIFICATION_REPOSITORY } from '../../../domain/repositories/verification.repository';
import { NewVerificationRun } from '../../../domain/entities/new-verification-run';
import { CodeSnippet } from '../../../domain/value-objects/code-snippet';
import { ModuleName } from '../../../domain/value-objects/module-name';
import { IMlBridge, ML_BRIDGE } from '../../ports/ml-bridge';
import { FX_RATE_REPOSITORY, IReferenceFxRateRepository } from '../../../../fx-rates/domain/repositories/reference-fx-rate.repository';
import { VerificationDetailRto } from '../../../presentation/rto/verification-detail.rto';
import { RunVerificationCommand } from '../run-verification.command';
import { validatedAnalysis } from '../../services/validated-analysis';

@CommandHandler(RunVerificationCommand)
export class RunVerificationHandler implements ICommandHandler<RunVerificationCommand> {
  constructor(@Inject(VERIFICATION_REPOSITORY) private readonly repository: IVerificationRepository,
    @Inject(ML_BRIDGE) private readonly engine: IMlBridge,
    @Inject(FX_RATE_REPOSITORY) private readonly rates: IReferenceFxRateRepository,
    private readonly eventBus: EventBus) {}

  async execute({ dto }: RunVerificationCommand): Promise<VerificationDetailRto> {
    const now = new Date();
    const context = {
      id: randomUUID(), moduleName: new ModuleName(dto.moduleName).value, category: dto.category,
      cobolSource: new CodeSnippet(dto.cobolSource).value, javaSource: new CodeSnippet(dto.javaSource).value,
      patchedJavaSource: dto.patchedJavaSource ?? '', createdAt: now, updatedAt: now, version: 1,
    };
    if (context.patchedJavaSource) new CodeSnippet(context.patchedJavaSource);
    const result = await this.engine.verify({ ...context, referenceFxRates: (await this.rates.findAll()).map((rate) => rate.toPrimitives()) });
    const run = new NewVerificationRun({ ...context, ...validatedAnalysis(result, context) });
    const saved = await this.repository.save(run);
    this.eventBus.publishAll(run.pullEvents());
    return VerificationDetailRto.fromDomain(saved);
  }
}
