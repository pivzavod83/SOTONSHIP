import 'reflect-metadata';
import { createHash } from 'node:crypto';
import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { json } from 'express';
import { AiReviewModule } from '../src/modules/ai-review/ai-review.module';
import { AI_DEFECT_REVIEW_ENGINE, IAiDefectReviewEngine } from '../src/modules/ai-review/application/ports/ai-defect-review-engine';
import { ReviewPairHandler } from '../src/modules/ai-review/application/queries/handlers/review-pair.handler';
import { ReviewPairQuery } from '../src/modules/ai-review/application/queries/review-pair.query';
import { validatedAiReview } from '../src/modules/ai-review/application/services/validated-ai-review';
import { AiReviewRequest, AiReviewRequestInput, AiReviewRequestState } from '../src/modules/ai-review/domain/value-objects/ai-review-request';
import { AiReviewRto } from '../src/modules/ai-review/presentation/rto/ai-review.rto';
import { PythonAiDefectReviewService } from '../src/modules/ai-review/infrastructure/ml-bridge/python-ai-defect-review.service';
import { PythonJsonWorkerService } from '../src/common/infrastructure/python/python-json-worker.service';
import { GlobalExceptionFilter } from '../src/common/exceptions/global-exception.filter';

const hash = (source: string): string => createHash('sha256').update(source).digest('hex');
const input = (): AiReviewRequestInput => ({ moduleName: 'Sum', cobolSource: 'PROCEDURE DIVISION.\r\nADD X TO Y GIVING RESULT.\r\n',
  javaSource: 'class Sum {\n  int run(int x, int y) { return x * y; }\n}', analysisContext: 'Both functions return the sum.' });
function envelope(request: AiReviewRequestState): Record<string, any> {
  return {
    status: 'ANALYZED', summary: 'Suspected arithmetic mismatch; requires independent verification.',
    findings: [{ findingId: 'F1', title: 'Multiplication replaces addition', category: 'ARITHMETIC', severity: 'HIGH',
      explanation: 'The COBOL adds the inputs while the Java multiplies them.', cobolLines: { start: 2, end: 2 }, javaLines: { start: 2, end: 2 },
      cobolExcerpt: request.cobolSource.split('\n')[1], javaExcerpt: request.javaSource.split('\n')[1], suggestedFix: 'Preserve the addition operation.',
      candidateInputs: [{ inputsJson: '{"x":2,"y":3}', rationale: 'The sum and product differ.', status: 'NOT_EXECUTED' }], evidenceStatus: 'AI_HYPOTHESIS' }],
    limitations: ['Source inspection can miss defects.'], sourceHashes: { cobol: hash(request.cobolSource), java: hash(request.javaSource) },
    provider: { protocol: 'OPENAI_COMPATIBLE_CHAT', model: 'test-model' }, aiIsProof: false, promptVersion: 'paired-defect-review-v1', counterexamplesExecuted: false,
  };
}

describe('Paired AI defect review source/evidence boundary', () => {
  it('retains exact source text, defaults source format, and whitelists the RTO', async () => {
    const engine: IAiDefectReviewEngine = { review: jest.fn(async (request) => ({ ...envelope(request), secret: 'never expose', proofStatus: 'UNSAT_PROVEN_SAFE' })) };
    const result = await new ReviewPairHandler(engine).execute(new ReviewPairQuery(input()));
    expect(engine.review).toHaveBeenCalledWith({ ...input(), cobolSourceFormat: 'AUTO' });
    expect(result).toBeInstanceOf(AiReviewRto);
    expect(result.findings[0].cobolExcerpt).toBe('ADD X TO Y GIVING RESULT.\r');
    expect(result.aiIsProof).toBe(false);
    expect(result.counterexamplesExecuted).toBe(false);
    expect(result.findings[0].candidateInputs[0].status).toBe('NOT_EXECUTED');
    expect(result).not.toHaveProperty('secret');
    expect(result).not.toHaveProperty('proofStatus');
  });

  it('returns an honest unconfigured status without fabricating findings', async () => {
    const engine: IAiDefectReviewEngine = { review: jest.fn(async (request) => ({ ...envelope(request), status: 'NOT_CONFIGURED',
      findings: [], provider: { protocol: 'OPENAI_COMPATIBLE_CHAT', model: null }, summary: 'Configure LLM_MODEL and LLM_API_KEY on the backend.' })) };
    const result = await new ReviewPairHandler(engine).execute(new ReviewPairQuery(input()));
    expect(result).toMatchObject({ status: 'NOT_CONFIGURED', findings: [], aiIsProof: false });
  });

  it('permits no findings without treating that as a proof or a verified pass', () => {
    const request = new AiReviewRequest(input()).toPrimitives();
    const result = envelope(request); result.findings = [];
    expect(validatedAiReview(result, request)).toMatchObject({ status: 'ANALYZED', findings: [], aiIsProof: false, counterexamplesExecuted: false });
  });

  it('permits an honest finding without an invented correction', () => {
    const request = new AiReviewRequest(input()).toPrimitives();
    const result = envelope(request); result.findings[0].suggestedFix = '';
    expect(validatedAiReview(result, request).findings[0].suggestedFix).toBe('');
  });

  it.each([
    ['wrong COBOL hash', (result: Record<string, any>) => { result.sourceHashes.cobol = 'a'.repeat(64); }],
    ['wrong Java hash', (result: Record<string, any>) => { result.sourceHashes.java = 'a'.repeat(64); }],
    ['proof assertion', (result: Record<string, any>) => { result.aiIsProof = true; }],
    ['execution assertion', (result: Record<string, any>) => { result.counterexamplesExecuted = true; }],
    ['unsupported prompt version', (result: Record<string, any>) => { result.promptVersion = 'unreviewed'; }],
    ['unrecognized status', (result: Record<string, any>) => { result.status = 'VERIFIED'; }],
    ['missing provider', (result: Record<string, any>) => { delete result.provider; }],
    ['missing provenance', (result: Record<string, any>) => { result.provider.protocol = 'UNKNOWN'; }],
    ['out-of-range span', (result: Record<string, any>) => { result.findings[0].javaLines.end = 4; }],
    ['fractional line', (result: Record<string, any>) => { result.findings[0].javaLines.start = 1.5; }],
    ['reversed span', (result: Record<string, any>) => { result.findings[0].javaLines = { start: 3, end: 2 }; }],
    ['zero-based line', (result: Record<string, any>) => { result.findings[0].cobolLines.start = 0; }],
    ['missing both anchors', (result: Record<string, any>) => { Object.assign(result.findings[0], { cobolLines: null, javaLines: null, cobolExcerpt: '', javaExcerpt: '' }); }],
    ['invented source excerpt', (result: Record<string, any>) => { result.findings[0].javaExcerpt = 'return x + y;'; }],
    ['normalized raw excerpt', (result: Record<string, any>) => { result.findings[0].cobolExcerpt = result.findings[0].cobolExcerpt.trim(); }],
    ['nonsequential finding ID', (result: Record<string, any>) => { result.findings[0].findingId = 'F2'; }],
    ['claim of verified evidence', (result: Record<string, any>) => { result.findings[0].evidenceStatus = 'VERIFIED'; }],
    ['unrecognized severity', (result: Record<string, any>) => { result.findings[0].severity = 'CRITICAL'; }],
    ['unrecognized category', (result: Record<string, any>) => { result.findings[0].category = 'SECURITY'; }],
    ['findings on a provider failure', (result: Record<string, any>) => { result.status = 'PROVIDER_ERROR'; }],
    ['too many findings', (result: Record<string, any>) => { result.findings = Array(9).fill(result.findings[0]); }],
    ['too many suggested inputs', (result: Record<string, any>) => { result.findings[0].candidateInputs = Array(4).fill(result.findings[0].candidateInputs[0]); }],
    ['executed suggested input', (result: Record<string, any>) => { result.findings[0].candidateInputs[0].status = 'EXECUTED'; }],
    ['non-JSON suggested input', (result: Record<string, any>) => { result.findings[0].candidateInputs[0].inputsJson = '{'; }],
    ['array suggested input', (result: Record<string, any>) => { result.findings[0].candidateInputs[0].inputsJson = '[]'; }],
    ['non-finite suggested input', (result: Record<string, any>) => { result.findings[0].candidateInputs[0].inputsJson = '{"x":1e999}'; }],
    ['oversized suggested input', (result: Record<string, any>) => { result.findings[0].candidateInputs[0].inputsJson = JSON.stringify({ x: 'a'.repeat(4000) }); }],
  ])('rejects %s before HTTP receives a result', (_name, change) => {
    const request = new AiReviewRequest(input()).toPrimitives();
    const result = envelope(request); change(result);
    expect(() => validatedAiReview(result, request)).toThrow(expect.objectContaining({ code: 'engine.invalid_result' }));
  });

  it.each([
    ['empty module name', { moduleName: ' ' }],
    ['oversized module name', { moduleName: 'a'.repeat(161) }],
    ['empty source', { javaSource: '  \n ' }],
    ['source null bytes', { javaSource: 'class X {\0}' }],
    ['too many lines', { cobolSource: 'x\n'.repeat(1500) }],
    ['oversized source', { cobolSource: 'x'.repeat(100001) }],
    ['unknown source format', { cobolSourceFormat: 'UNKNOWN' }],
    ['oversized context', { analysisContext: 'x'.repeat(8001) }],
    ['malformed Unicode source', { cobolSource: '\ud800' }],
    ['malformed Unicode module name', { moduleName: '\udfff' }],
    ['malformed Unicode context', { analysisContext: '\ud800' }],
    ['oversized encoded payload', { cobolSource: '\x01'.repeat(100000), javaSource: '\x01'.repeat(100000) }],
  ])('rejects %s before calling the engine outside HTTP', async (_name, change) => {
    const engine = { review: jest.fn() };
    await expect(new ReviewPairHandler(engine).execute(new ReviewPairQuery({ ...input(), ...change } as AiReviewRequestInput)))
      .rejects.toMatchObject({ code: 'ai_review.invalid_request' });
    expect(engine.review).not.toHaveBeenCalled();
  });

  it('dispatches only the AI module through the shared Python worker', async () => {
    const worker = { execute: jest.fn(async () => ({ status: 'NOT_CONFIGURED' })) };
    const request = new AiReviewRequest(input()).toPrimitives();
    await new PythonAiDefectReviewService(worker as unknown as PythonJsonWorkerService).review(request);
    expect(worker.execute).toHaveBeenCalledWith('ml_engine.ai_review', request);
  });
});

describe('AI review HTTP / CQRS boundary', () => {
  let app: INestApplication;
  let base: string;
  let engine: jest.Mocked<IAiDefectReviewEngine>;

  beforeAll(async () => {
    engine = { review: jest.fn(async (request) => envelope(request)) };
    const module = await Test.createTestingModule({ imports: [AiReviewModule] }).overrideProvider(AI_DEFECT_REVIEW_ENGINE).useValue(engine).compile();
    app = module.createNestApplication({ bodyParser: false });
    app.use(json({ limit: '3mb' }));
    app.setGlobalPrefix('api');
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
    app.useGlobalFilters(new GlobalExceptionFilter());
    await app.listen(0, '127.0.0.1');
    base = await app.getUrl();
  });
  afterAll(async () => { await app.close(); });

  const post = async (body: unknown): Promise<Response> => fetch(`${base}/api/ai-reviews`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });

  it('runs the pair review through CQRS with source hashes and advisory evidence', async () => {
    const response = await post(input());
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ status: 'ANALYZED', aiIsProof: false,
      sourceHashes: { java: hash(input().javaSource) }, findings: [{ evidenceStatus: 'AI_HYPOTHESIS' }], counterexamplesExecuted: false });
    expect(engine.review).toHaveBeenCalledTimes(1);
  });

  it.each([
    () => ({ ...input(), apiKey: 'must never be accepted' }),
    () => ({ ...input(), model: 'client override not accepted' }),
    () => ({ ...input(), javaSource: 12 }),
    () => ({ ...input(), javaSource: ' ' }),
    () => ({ ...input(), cobolSourceFormat: 'INVALID' }),
    () => ({ ...input(), analysisContext: 'x'.repeat(8001) }),
    () => ({ ...input(), cobolSource: '\ud800' }),
    () => ({ ...input(), cobolSource: '\x01'.repeat(100000), javaSource: '\x01'.repeat(100000) }),
  ])('rejects malformed DTOs and client provider overrides before calling the engine', async (invalid) => {
    const calls = engine.review.mock.calls.length;
    const response = await post(invalid());
    expect(response.status).toBe(400);
    expect(engine.review).toHaveBeenCalledTimes(calls);
  });

  it('fails closed with a sanitized error if an engine invents source anchors', async () => {
    engine.review.mockImplementationOnce(async (request) => {
      const result = envelope(request); result.findings[0].javaExcerpt = 'private model output'; return result;
    });
    const response = await post(input());
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(JSON.stringify(body)).not.toContain('private model output');
    expect(body).toMatchObject({ code: 'engine.invalid_result', statusCode: 503 });
  });
});
