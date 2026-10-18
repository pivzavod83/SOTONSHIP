import 'reflect-metadata';
import { createHash } from 'node:crypto';
import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { MatchingModule } from '../src/modules/matching/matching.module';
import { PROGRAM_MATCHING_ENGINE, IProgramMatchingEngine } from '../src/modules/matching/application/ports/program-matching-engine';
import { MatchProgramsHandler } from '../src/modules/matching/application/queries/handlers/match-programs.handler';
import { MatchProgramsQuery } from '../src/modules/matching/application/queries/match-programs.query';
import { validatedProgramMatches } from '../src/modules/matching/application/services/validated-program-matches';
import { MatchingRequest, MatchingRequestInput, MatchingRequestState } from '../src/modules/matching/domain/value-objects/matching-request';
import { ProgramMatchesRto } from '../src/modules/matching/presentation/rto/program-matches.rto';
import { GlobalExceptionFilter } from '../src/common/exceptions/global-exception.filter';

const hash = (source: string): string => createHash('sha256').update(source).digest('hex');
const input = (): MatchingRequestInput => ({
  cobolSource: 'IDENTIFICATION DIVISION.\nPROGRAM-ID. SUM.\nPROCEDURE DIVISION.\nADD X TO Y GIVING RESULT.',
  candidates: [
    { candidateId: 'add', moduleName: 'Sum.java', javaSource: 'class Sum { int run(int x, int y) { return x + y; } }' },
    { candidateId: 'multiply', moduleName: 'Product.java', javaSource: 'class Product { int run(int x, int y) { return x * y; } }' },
  ], topK: 1,
});
function envelope(request: MatchingRequestState): Record<string, any> {
  return {
    status: 'MATCH_SUGGESTED', reason: 'The first candidate meets the calibrated similarity and margin thresholds.',
    matchingIsProof: false, granularity: 'PROGRAM', cobolSourceSha256: hash(request.cobolSource),
    model: { id: 'paired-gnn-test', sha256: 'a'.repeat(64), trainingDataset: 'COBOL-JavaTrans', evaluation: { test: { retrievalAt1: 0.4 }, disclaimer: 'Not correctness evidence' } },
    thresholds: { minimumSimilarity: 0.6, minimumMargin: 0.1 },
    candidates: request.candidates.map((candidate, index) => ({ candidateId: candidate.candidateId, moduleName: candidate.moduleName,
      javaSourceSha256: hash(candidate.javaSource), rank: index + 1, similarity: 0.9 - index * 0.4 })),
  };
}

describe('Paired program matching contract', () => {
  it('requests every candidate, validates before truncation, and constructs a response without source or arbitrary engine fields', async () => {
    const engine: IProgramMatchingEngine = { match: jest.fn(async (request) => ({ ...envelope(request), javaSource: 'must not leak', proofStatus: 'UNSAT_PROVEN_SAFE' })) };
    const response = await new MatchProgramsHandler(engine).execute(new MatchProgramsQuery(input()));
    expect(engine.match).toHaveBeenCalledWith(expect.objectContaining({ topK: 2, cobolSourceFormat: 'AUTO' }));
    expect(response).toBeInstanceOf(ProgramMatchesRto);
    expect(response.candidates).toHaveLength(1);
    expect(response.candidates[0].candidateId).toBe('add');
    expect(response.matchingIsProof).toBe(false);
    expect(response).not.toHaveProperty('javaSource');
    expect(response).not.toHaveProperty('proofStatus');
  });

  it.each([
    ['mismatched COBOL hash', (result: Record<string, any>) => { result.cobolSourceSha256 = 'f'.repeat(64); }],
    ['mismatched Java hash', (result: Record<string, any>) => { result.candidates[0].javaSourceSha256 = 'f'.repeat(64); }],
    ['candidate impersonation', (result: Record<string, any>) => { result.candidates[0].moduleName = 'Wrong.java'; }],
    ['duplicate candidates', (result: Record<string, any>) => { result.candidates[1].candidateId = result.candidates[0].candidateId; }],
    ['missing runner-up', (result: Record<string, any>) => { result.candidates.pop(); }],
    ['non-contiguous ranks', (result: Record<string, any>) => { result.candidates[1].rank = 3; }],
    ['unsorted candidates', (result: Record<string, any>) => { result.candidates[1].similarity = 0.95; }],
    ['nonfinite scores', (result: Record<string, any>) => { result.candidates[0].similarity = Number.NaN; }],
    ['out-of-range scores', (result: Record<string, any>) => { result.candidates[0].similarity = 1.1; }],
    ['weak top score', (result: Record<string, any>) => { result.thresholds.minimumSimilarity = 0.99; }],
    ['insufficient margin', (result: Record<string, any>) => { result.thresholds.minimumMargin = 0.9; }],
    ['proof claim', (result: Record<string, any>) => { result.matchingIsProof = true; }],
    ['non-string status', (result: Record<string, any>) => { result.status = ['MATCH_SUGGESTED']; }],
    ['function-level claim', (result: Record<string, any>) => { result.granularity = 'FUNCTION'; }],
    ['missing evaluation', (result: Record<string, any>) => { result.model.evaluation = {}; }],
    ['invalid evaluation number', (result: Record<string, any>) => { result.model.evaluation.test.retrievalAt1 = Number.POSITIVE_INFINITY; }],
  ])('rejects %s before a result reaches HTTP', (_name, change) => {
    const request = new MatchingRequest(input()).toPrimitives();
    const result = envelope(request); change(result);
    expect(() => validatedProgramMatches(result, request)).toThrow(expect.objectContaining({ code: 'engine.invalid_result' }));
  });

  it('permits a review-required result for one candidate but rejects an automatic singleton suggestion', () => {
    const request = new MatchingRequest({ ...input(), candidates: input().candidates.slice(0, 1) }).toPrimitives();
    const result = envelope(request);
    expect(() => validatedProgramMatches(result, request)).toThrow();
    result.status = 'REVIEW_REQUIRED'; result.reason = 'Insufficient alternatives to measure a ranking margin.';
    expect(validatedProgramMatches(result, request).status).toBe('REVIEW_REQUIRED');
  });

  it.each([
    ['duplicate identifiers', () => ({ ...input(), candidates: [input().candidates[0], input().candidates[0]] })],
    ['too many candidates', () => ({ ...input(), candidates: Array.from({ length: 21 }, (_, index) => ({ ...input().candidates[0], candidateId: String(index) })) })],
    ['excessive lines', () => ({ ...input(), cobolSource: 'X\r\n'.repeat(1500) })],
    ['empty source', () => ({ ...input(), cobolSource: '  \n ' })],
    ['path-like module names', () => ({ ...input(), candidates: [{ ...input().candidates[0], moduleName: '../secret.java' }] })],
    ['invalid topK', () => ({ ...input(), topK: 0 })],
    ['oversized aggregate', () => ({ cobolSource: 'x'.repeat(100000), candidates: Array.from({ length: 20 }, (_, index) => ({ candidateId: String(index), moduleName: 'X.java', javaSource: 'x'.repeat(100000) })) })],
  ])('rejects %s even when invoked outside HTTP', async (_name, invalid) => {
    const engine = { match: jest.fn() };
    await expect(new MatchProgramsHandler(engine).execute(new MatchProgramsQuery(invalid()))).rejects.toMatchObject({ code: 'matching.invalid_request' });
    expect(engine.match).not.toHaveBeenCalled();
  });
});

describe('Matching HTTP / CQRS boundary', () => {
  let app: INestApplication;
  let base: string;
  let engine: jest.Mocked<IProgramMatchingEngine>;

  beforeAll(async () => {
    engine = { match: jest.fn(async (request) => envelope(request)) };
    const module = await Test.createTestingModule({ imports: [MatchingModule] }).overrideProvider(PROGRAM_MATCHING_ENGINE).useValue(engine).compile();
    app = module.createNestApplication();
    app.setGlobalPrefix('api');
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
    app.useGlobalFilters(new GlobalExceptionFilter());
    await app.listen(0, '127.0.0.1');
    base = await app.getUrl();
  });
  afterAll(async () => { await app.close(); });

  async function post(body: unknown): Promise<Response> {
    return fetch(`${base}/api/matches`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  }

  it('executes a validated POST through the query bus without persisting or starting verification', async () => {
    const response = await post(input());
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ matchingIsProof: false, granularity: 'PROGRAM', candidates: [{ candidateId: 'add', rank: 1 }] });
    expect(engine.match).toHaveBeenCalledTimes(1);
  });

  it.each([
    () => ({ ...input(), unexpectedProof: true }),
    () => ({ ...input(), candidates: [{ ...input().candidates[0], surprise: true }] }),
    () => ({ ...input(), candidates: [] }),
    () => ({ ...input(), topK: '1' }),
    () => ({ ...input(), candidates: [null] }),
  ])('rejects malformed nested DTOs before invoking the engine', async (invalid) => {
    const before = engine.match.mock.calls.length;
    const response = await post(invalid());
    expect(response.status).toBe(400);
    expect(engine.match).toHaveBeenCalledTimes(before);
  });
});
