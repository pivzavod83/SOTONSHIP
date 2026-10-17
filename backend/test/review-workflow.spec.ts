import { EventBus } from '@nestjs/cqrs';
import { validate } from 'class-validator';
import { sourceWithinPolicy, verificationPolicy } from '../src/common/config/verification-policy';
import { SubmitCandidateHandler } from '../src/modules/verification/application/commands/handlers/submit-candidate.handler';
import { SubmitCandidateCommand } from '../src/modules/verification/application/commands/submit-candidate.command';
import { ReverifyVerificationHandler } from '../src/modules/verification/application/commands/handlers/reverify-verification.handler';
import { ReverifyVerificationCommand } from '../src/modules/verification/application/commands/reverify-verification.command';
import { GetVerificationReviewHandler } from '../src/modules/verification/application/queries/handlers/get-verification-review.handler';
import { GetVerificationReviewQuery } from '../src/modules/verification/application/queries/get-verification-review.query';
import { IVerificationRepository } from '../src/modules/verification/domain/repositories/verification.repository';
import { IMlBridge } from '../src/modules/verification/application/ports/ml-bridge';
import { IReferenceFxRateRepository } from '../src/modules/fx-rates/domain/repositories/reference-fx-rate.repository';
import { UnconfiguredCodeGenerationProvider } from '../src/modules/verification/infrastructure/llm-bridge/unconfigured-code-generation.provider';
import { GetGenerationConfigurationHandler } from '../src/modules/verification/application/queries/handlers/get-generation-configuration.handler';
import { VerificationSummaryRto } from '../src/modules/verification/presentation/rto/verification-summary.rto';
import { RunVerificationDto } from '../src/modules/verification/presentation/dto/run-verification.dto';
import { FormalProofStatusValue as Status } from '../src/modules/verification/domain/enums/formal-proof-status.enum';
import { VerificationRun } from '../src/modules/verification/domain/entities/verification-run';
import { ID, analysis, rate, run } from './fixtures';

describe('Engineer review workflow', () => {
  let rows: jest.Mocked<IVerificationRepository>;
  let engine: jest.Mocked<IMlBridge>;
  let rates: jest.Mocked<IReferenceFxRateRepository>;
  beforeEach(() => {
    rows = { findAll: jest.fn(), findById: jest.fn().mockResolvedValue(run()), save: jest.fn().mockImplementation(async (value: VerificationRun) => value) };
    engine = { verify: jest.fn() };
    rates = { findAll: jest.fn().mockResolvedValue([rate]) };
  });
  it('verifies a candidate separately and retains current Java, proof and witness', async () => {
    engine.verify.mockResolvedValue(analysis(Status.UNSAT_PROVEN_SAFE, 'revised Java'));
    const result = await new SubmitCandidateHandler(rows, engine, rates).execute(new SubmitCandidateCommand(ID, { javaSource: 'revised Java' }));
    expect(engine.verify.mock.calls[0][0].javaSource).toBe('revised Java');
    expect(engine.verify.mock.calls[0][0]).not.toHaveProperty('cpgGraphJson');
    expect(result.javaSource).toBe('buggy Java');
    expect(result.patchedJavaSource).toBe('revised Java');
    expect(result.formalProofStatus).toBe(Status.SAT_COUNTEREXAMPLE_FOUND);
    expect(result.counterexamplesJson).toHaveLength(1);
    expect(result.provenanceJson.candidateReview).toMatchObject({ analysis: { formalProofStatus: Status.UNSAT_PROVEN_SAFE } });
  });
  it('reverifies current Java and retains the separately reviewed candidate', async () => {
    rows.findById.mockResolvedValue(run({ provenanceJson: { ...analysis().provenanceJson, candidateReview: { submittedAt: 'previous' } } }));
    engine.verify.mockResolvedValue(analysis());
    const publishAll = jest.fn();
    const result = await new ReverifyVerificationHandler(rows, engine, rates, { publishAll } as unknown as EventBus)
      .execute(new ReverifyVerificationCommand(ID));
    expect(engine.verify.mock.calls[0][0].javaSource).toBe('buggy Java');
    expect(engine.verify.mock.calls[0][0]).not.toHaveProperty('provenanceJson');
    expect(result.analysisStale).toBe(false);
    expect(result.provenanceJson.candidateReview).toMatchObject({ submittedAt: 'previous' });
    expect(publishAll).toHaveBeenCalledTimes(1);
  });
  it('marks legacy results stale and leaves human review pending', async () => {
    rows.findById.mockResolvedValue(run({ provenanceJson: { engineVersion: '0.1.0' } }));
    const result = await new GetVerificationReviewHandler(rows).execute(new GetVerificationReviewQuery(ID));
    expect(result).toMatchObject({ analysisStale: true, humanReviewStatus: 'PENDING', candidateReport: null });
    expect(VerificationSummaryRto.fromDomain(run({ proofScope: { ...analysis().proofScope, semanticsVersion: 'old' } })).analysisStale).toBe(true);
  });
  it('rejects an old-engine response before replacing the current analysis', async () => {
    engine.verify.mockResolvedValue({ ...analysis(), provenanceJson: { engineVersion: '0.1.0' } });
    await expect(new ReverifyVerificationHandler(rows, engine, rates, { publishAll: jest.fn() } as unknown as EventBus)
      .execute(new ReverifyVerificationCommand(ID))).rejects.toMatchObject({ code: 'engine.invalid_result' });
    expect(rows.save).not.toHaveBeenCalled();
  });
});

it('uses identical line and size caps at the HTTP DTO boundary', async () => {
  expect(sourceWithinPolicy('x\n'.repeat(verificationPolicy.maxSourceLines))).toBe(true);
  expect(sourceWithinPolicy('x\n'.repeat(verificationPolicy.maxSourceLines + 1))).toBe(false);
  expect(sourceWithinPolicy('x'.repeat(verificationPolicy.maxSourceCharacters + 1))).toBe(false);
  const dto = Object.assign(new RunVerificationDto(), { moduleName: 'TEST.cbl', category: 'FX_CONVERSION',
    cobolSource: 'x\n'.repeat(1501), javaSource: 'valid content' });
  expect((await validate(dto)).some(error => error.property === 'cobolSource')).toBe(true);
});

it('keeps generation inactive even with configuration and never exposes credential values', async () => {
  const previous = { ...process.env };
  try {
    process.env.LLM_API_KEY = 'test-secret-never-return'; process.env.LLM_PROVIDER = 'future-provider';
    const provider = new UnconfiguredCodeGenerationProvider();
    const config = await new GetGenerationConfigurationHandler(provider).execute();
    expect(config).toMatchObject({ adapterEnabled: false, apiKeyPresent: true, providerSelected: true });
    expect(JSON.stringify(config)).not.toContain('test-secret-never-return');
    await expect(provider.generate({ moduleName: 'TEST', cobolSource: 'source', inputOutputContract: {} }))
      .rejects.toMatchObject({ code: 'generation.not_configured' });
  } finally { process.env = previous; }
});
