import { EventBus } from '@nestjs/cqrs';
import { ApplyVerifiedPatchHandler } from '../src/modules/verification/application/commands/handlers/apply-verified-patch.handler';
import { RunVerificationHandler } from '../src/modules/verification/application/commands/handlers/run-verification.handler';
import { ApplyVerifiedPatchCommand } from '../src/modules/verification/application/commands/apply-verified-patch.command';
import { RunVerificationCommand } from '../src/modules/verification/application/commands/run-verification.command';
import { GetBaselineComparisonMetricsHandler } from '../src/modules/verification/application/queries/handlers/get-baseline-comparison-metrics.handler';
import { IVerificationRepository } from '../src/modules/verification/domain/repositories/verification.repository';
import { IReferenceFxRateRepository } from '../src/modules/fx-rates/domain/repositories/reference-fx-rate.repository';
import { IMlBridge } from '../src/modules/verification/application/ports/ml-bridge';
import { VerificationDetailRto } from '../src/modules/verification/presentation/rto/verification-detail.rto';
import { VerificationRun } from '../src/modules/verification/domain/entities/verification-run';
import { FormalProofStatusValue as Status } from '../src/modules/verification/domain/enums/formal-proof-status.enum';
import { VerificationCategory } from '../src/modules/verification/domain/enums/verification-category.enum';
import { ID, analysis, rate, run } from './fixtures';

describe('Verification command safety and orchestration', () => {
  let repository: jest.Mocked<IVerificationRepository>;
  let engine: jest.Mocked<IMlBridge>;
  let rates: jest.Mocked<IReferenceFxRateRepository>;
  let publishAll: jest.Mock;
  let events: EventBus;

  beforeEach(() => {
    repository = { findAll: jest.fn(), findPage: jest.fn(), findById: jest.fn().mockResolvedValue(run()), save: jest.fn().mockImplementation(async (value: VerificationRun) => value) };
    engine = { verify: jest.fn() };
    rates = { findAll: jest.fn().mockResolvedValue([rate]) };
    publishAll = jest.fn();
    events = { publishAll } as unknown as EventBus;
  });

  it('persists a run before publishing completion and discrepancy, and returns an RTO', async () => {
    const observed: string[] = [];
    repository.save.mockImplementation(async (value) => { observed.push('saved'); return value; });
    publishAll.mockImplementation(() => observed.push('published'));
    engine.verify.mockResolvedValue(analysis());
    const result = await new RunVerificationHandler(repository, engine, rates, events).execute(new RunVerificationCommand({
      moduleName: 'NEW.cbl', category: VerificationCategory.FX_CONVERSION,
      cobolSource: 'COBOL source', javaSource: 'buggy Java', patchedJavaSource: 'fixed Java',
    }));
    expect(result).toBeInstanceOf(VerificationDetailRto);
    expect(observed).toEqual(['saved', 'published']);
    expect(publishAll.mock.calls[0][0]).toHaveLength(2);
    expect(engine.verify.mock.calls[0][0].referenceFxRates[0].rate).toBe('1.158600000000');
    expect(result.id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it.each([Status.SAT_COUNTEREXAMPLE_FOUND, Status.UNKNOWN_HALTED_LIMIT])('preserves source and emits nothing when patch is %s', async (status) => {
    const original = run();
    repository.findById.mockResolvedValue(original);
    engine.verify.mockResolvedValue(analysis(status, 'fixed Java'));
    await expect(new ApplyVerifiedPatchHandler(repository, engine, rates, events).execute(new ApplyVerifiedPatchCommand(ID)))
      .rejects.toMatchObject({ code: 'verification.patch_not_proven', statusCode: 422 });
    expect(repository.save).not.toHaveBeenCalled();
    expect(publishAll).not.toHaveBeenCalled();
    expect(original.toPrimitives().javaSource).toBe('buggy Java');
  });

  it('re-verifies the exact candidate and replaces it only after a scoped UNSAT result', async () => {
    engine.verify.mockResolvedValue(analysis(Status.UNSAT_PROVEN_SAFE, 'fixed Java'));
    const result = await new ApplyVerifiedPatchHandler(repository, engine, rates, events).execute(new ApplyVerifiedPatchCommand(ID));
    expect(engine.verify.mock.calls[0][0].javaSource).toBe('fixed Java');
    expect(result.javaSource).toBe('fixed Java');
    expect(result.formalProofStatus).toBe(Status.UNSAT_PROVEN_SAFE);
    expect(result.counterexamplesJson).toEqual([]);
    expect(repository.save).toHaveBeenCalledTimes(1);
    expect(publishAll.mock.calls[0][0]).toHaveLength(1);
  });

  it('rejects an UNSAT response referring to a different Java source', async () => {
    engine.verify.mockResolvedValue(analysis(Status.UNSAT_PROVEN_SAFE, 'some other source'));
    await expect(new ApplyVerifiedPatchHandler(repository, engine, rates, events).execute(new ApplyVerifiedPatchCommand(ID)))
      .rejects.toMatchObject({ code: 'engine.invalid_result' });
    expect(repository.save).not.toHaveBeenCalled();
  });

  it('rejects fabricated proof status without supported finite bounds', async () => {
    const result = analysis(Status.UNSAT_PROVEN_SAFE, 'fixed Java');
    result.proofScope.bounded = false;
    engine.verify.mockResolvedValue(result);
    await expect(new ApplyVerifiedPatchHandler(repository, engine, rates, events).execute(new ApplyVerifiedPatchCommand(ID)))
      .rejects.toMatchObject({ code: 'engine.invalid_result' });
    expect(repository.save).not.toHaveBeenCalled();
  });

  it('does not publish events when persistence fails', async () => {
    engine.verify.mockResolvedValue(analysis());
    repository.save.mockRejectedValue(new Error('database unavailable'));
    await expect(new RunVerificationHandler(repository, engine, rates, events).execute(new RunVerificationCommand({
      moduleName: 'NEW.cbl', category: VerificationCategory.FX_CONVERSION, cobolSource: 'COBOL source', javaSource: 'buggy Java',
    }))).rejects.toThrow('database unavailable');
    expect(publishAll).not.toHaveBeenCalled();
  });

  it('reports missing records before invoking the engine', async () => {
    repository.findById.mockResolvedValue(null);
    await expect(new ApplyVerifiedPatchHandler(repository, engine, rates, events).execute(new ApplyVerifiedPatchCommand(ID)))
      .rejects.toMatchObject({ statusCode: 404 });
    expect(engine.verify).not.toHaveBeenCalled();
  });

  it('keeps UNKNOWN separate from proven safe in comparison metrics', async () => {
    repository.findAll.mockResolvedValue([run(), run({ ...analysis(Status.UNKNOWN_HALTED_LIMIT) })]);
    const result = await new GetBaselineComparisonMetricsHandler(repository).execute();
    expect(result.totalModules).toBe(2);
    expect(result.unknownModules).toBe(1);
    expect(result.completedProofs).toBe(1);
    expect(result.neuroSymbolic.provenSafeModules).toBe(0);
    expect(result.neuroSymbolic.provenCounterexamples).toBe(1);
    expect(result.interpretation).toContain('not measured alignment accuracy');
  });
});
