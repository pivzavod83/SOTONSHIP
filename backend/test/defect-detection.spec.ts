import 'reflect-metadata';
import { createHash } from 'node:crypto';
import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { json } from 'express';
import { GlobalExceptionFilter } from '../src/common/exceptions/global-exception.filter';
import { PythonJsonWorkerService } from '../src/common/infrastructure/python/python-json-worker.service';
import { DefectDetectionModule } from '../src/modules/defect-detection/defect-detection.module';
import { DEFECT_REVIEW_ENGINE, IDefectReviewEngine } from '../src/modules/defect-detection/application/ports/defect-review-engine';
import { ReviewDefectsHandler } from '../src/modules/defect-detection/application/queries/handlers/review-defects.handler';
import { ReviewDefectsQuery } from '../src/modules/defect-detection/application/queries/review-defects.query';
import { validatedDefectModelStatus, validatedDefectReview } from '../src/modules/defect-detection/application/services/validated-defect-review';
import { DefectReviewRequest, DefectReviewRequestInput, DefectReviewRequestState } from '../src/modules/defect-detection/domain/value-objects/defect-review-request';
import { PythonDefectReviewService } from '../src/modules/defect-detection/infrastructure/ml-bridge/python-defect-review.service';
import { DefectReviewRto } from '../src/modules/defect-detection/presentation/rto/defect-review.rto';

const hash = (source: string): string => createHash('sha256').update(source).digest('hex');
const input = (): DefectReviewRequestInput => ({ cobolSource: 'PROCEDURE DIVISION.\r\nADD X TO Y GIVING RESULT.\r\n',
  javaSource: 'class Program {\n  int run(int x, int y) { return x * y; }\n}', cobolSourceFormat: 'FREE' });
const metadata = () => ({ name: 'synthetic-pilot-test-model', sha256: 'a'.repeat(64), datasetSha256: 'b'.repeat(64), trainingFamilyCount: 6,
  evaluation: { test: { pairs: 8, accuracy: 0.5 }, note: 'Synthetic feasibility statistics.' } });
function envelope(request: DefectReviewRequestState): Record<string, any> {
  return { status: 'ANALYZED', engineVersion: 'paired-defect-v1',
    sourceHashes: { cobol: hash(request.cobolSource), java: hash(request.javaSource) }, aiIsProof: false, counterexamplesExecuted: false,
    risk: { score: 0.8, threshold: 0.5, decision: 'REVIEW_REQUIRED', calibrated: false }, model: metadata(),
    summary: 'Learned model flags a possible semantic difference; requires independent verification.',
    limitations: ['Small synthetic pilot; no correctness guarantee.'],
    findings: [{ findingId: 'F1', evidenceStatus: 'MODEL_HYPOTHESIS', title: 'Suspected operation mismatch',
      explanation: 'The learned ranking highlights these source operations.', suggestedFix: 'Review whether the Java operation preserves the COBOL operation.',
      cobolLines: { start: 2, end: 2 }, javaLines: { start: 2, end: 2 }, cobolExcerpt: request.cobolSource.split('\n')[1],
      javaExcerpt: request.javaSource.split('\n')[1], score: 0.75, category: 'SEMANTIC_DIFFERENCE', candidateInputs: [] }] };
}

describe('Local defect model source/evidence boundary', () => {
  it('preserves raw source, serializes source-bound hypotheses, and strips unknown proof/provider fields', async () => {
    const engine: IDefectReviewEngine = { review: jest.fn(async (request) => ({ ...envelope(request), proofStatus: 'UNSAT_PROVEN_SAFE', providerKey: 'never expose' })), status: jest.fn() };
    const result = await new ReviewDefectsHandler(engine).execute(new ReviewDefectsQuery(input()));
    expect(engine.review).toHaveBeenCalledWith(input());
    expect(result).toBeInstanceOf(DefectReviewRto);
    expect(result.findings[0].cobolExcerpt).toBe('ADD X TO Y GIVING RESULT.\r');
    expect(result).toMatchObject({ aiIsProof: false, counterexamplesExecuted: false, model: { trainingFamilyCount: 6 },
      findings: [{ candidateInputs: [], evidenceStatus: 'MODEL_HYPOTHESIS' }] });
    expect(result).not.toHaveProperty('proofStatus');
    expect(result).not.toHaveProperty('providerKey');
  });

  it('permits no signal without interpreting it as equivalence', () => {
    const request = new DefectReviewRequest(input()).toPrimitives();
    const raw = envelope(request); raw.findings = [];
    raw.risk = { score: 0.2, threshold: 0.5, decision: 'NO_DEFECT_SIGNAL', calibrated: false };
    expect(validatedDefectReview(raw, request)).toMatchObject({ status: 'ANALYZED', findings: [], aiIsProof: false,
      counterexamplesExecuted: false, risk: { decision: 'NO_DEFECT_SIGNAL' } });
  });

  it.each(['NOT_CONFIGURED', 'UNSUPPORTED'])('returns an honest %s response without fabricated hypotheses', (status) => {
    const request = new DefectReviewRequest(input()).toPrimitives();
    const raw = envelope(request); Object.assign(raw, { status, findings: [], model: status === 'NOT_CONFIGURED' ? null : metadata() });
    raw.risk = { score: 0, threshold: 0.5, decision: 'NO_DEFECT_SIGNAL', calibrated: false };
    expect(validatedDefectReview(raw, request)).toMatchObject({ status, findings: [], aiIsProof: false });
  });

  it('requires no invented correction or invented witness for a hypothesis', () => {
    const request = new DefectReviewRequest(input()).toPrimitives();
    const raw = envelope(request); raw.findings[0].suggestedFix = '';
    expect(validatedDefectReview(raw, request).findings[0]).toMatchObject({ suggestedFix: '', candidateInputs: [] });
  });

  it.each([
    ['changed COBOL hash', (raw: Record<string, any>) => { raw.sourceHashes.cobol = 'c'.repeat(64); }],
    ['changed Java hash', (raw: Record<string, any>) => { raw.sourceHashes.java = 'c'.repeat(64); }],
    ['proof assertion', (raw: Record<string, any>) => { raw.aiIsProof = true; }],
    ['execution assertion', (raw: Record<string, any>) => { raw.counterexamplesExecuted = true; }],
    ['calibration assertion', (raw: Record<string, any>) => { raw.risk.calibrated = true; }],
    ['unknown engine version', (raw: Record<string, any>) => { raw.engineVersion = 'new-version'; }],
    ['unknown status', (raw: Record<string, any>) => { raw.status = 'VERIFIED'; }],
    ['non-finite score', (raw: Record<string, any>) => { raw.risk.score = NaN; }],
    ['score above one', (raw: Record<string, any>) => { raw.risk.score = 1.1; }],
    ['negative threshold', (raw: Record<string, any>) => { raw.risk.threshold = -0.1; }],
    ['contradictory decision', (raw: Record<string, any>) => { raw.risk.decision = 'NO_DEFECT_SIGNAL'; }],
    ['missing model provenance', (raw: Record<string, any>) => { raw.model = null; }],
    ['invalid artifact digest', (raw: Record<string, any>) => { raw.model.sha256 = 'missing'; }],
    ['unexpected training family count', (raw: Record<string, any>) => { raw.model.trainingFamilyCount = 10; }],
    ['non-finite evaluation', (raw: Record<string, any>) => { raw.model.evaluation = { accuracy: Infinity }; }],
    ['out-of-range source anchor', (raw: Record<string, any>) => { raw.findings[0].javaLines.end = 4; }],
    ['fractional source line', (raw: Record<string, any>) => { raw.findings[0].javaLines.start = 1.5; }],
    ['reversed source anchor', (raw: Record<string, any>) => { raw.findings[0].javaLines = { start: 3, end: 2 }; }],
    ['zero-based source anchor', (raw: Record<string, any>) => { raw.findings[0].cobolLines.start = 0; }],
    ['unanchored finding', (raw: Record<string, any>) => { Object.assign(raw.findings[0], { cobolLines: null, javaLines: null, cobolExcerpt: '', javaExcerpt: '' }); }],
    ['stale edited excerpt', (raw: Record<string, any>) => { raw.findings[0].javaExcerpt = 'return x + y;'; }],
    ['normalized raw excerpt', (raw: Record<string, any>) => { raw.findings[0].cobolExcerpt = raw.findings[0].cobolExcerpt.trim(); }],
    ['invented executed candidate', (raw: Record<string, any>) => { raw.findings[0].candidateInputs = [{ input: '2\n3\n' }]; }],
    ['verified finding', (raw: Record<string, any>) => { raw.findings[0].evidenceStatus = 'VERIFIED'; }],
    ['non-finite ranking score', (raw: Record<string, any>) => { raw.findings[0].score = Infinity; }],
    ['unknown category', (raw: Record<string, any>) => { raw.findings[0].category = 'PROVEN_DEFECT'; }],
    ['nonsequential finding identifier', (raw: Record<string, any>) => { raw.findings[0].findingId = 'F2'; }],
    ['too many findings', (raw: Record<string, any>) => { raw.findings = Array(9).fill(raw.findings[0]); }],
    ['hypotheses on unsupported input', (raw: Record<string, any>) => { raw.status = 'UNSUPPORTED'; }],
    ['model on unconfigured input', (raw: Record<string, any>) => { raw.status = 'NOT_CONFIGURED'; raw.findings = []; }],
  ])('rejects %s', (_name, change) => {
    const request = new DefectReviewRequest(input()).toPrimitives();
    const raw = envelope(request); change(raw);
    expect(() => validatedDefectReview(raw, request)).toThrow(expect.objectContaining({ code: 'engine.invalid_result' }));
  });

  it.each([
    ['empty source', { javaSource: ' \n' }], ['source null byte', { cobolSource: 'x\0' }],
    ['too many lines', { javaSource: 'x\n'.repeat(1500) }], ['too many characters', { javaSource: 'x'.repeat(100001) }],
    ['too many UTF-8 bytes', { javaSource: '界'.repeat(70000) }],
    ['invalid Unicode', { cobolSource: '\ud800' }], ['invalid source format', { cobolSourceFormat: 'AUTO' }],
    ['empty module name', { moduleName: ' ' }], ['module control character', { moduleName: 'A\nB' }],
    ['excessive encoded payload', { cobolSource: '\x01'.repeat(100000), javaSource: '\x01'.repeat(100000) }],
  ])('rejects %s before calling the engine', async (_name, change) => {
    const engine = { review: jest.fn(), status: jest.fn() };
    await expect(new ReviewDefectsHandler(engine).execute(new ReviewDefectsQuery({ ...input(), ...change } as DefectReviewRequestInput)))
      .rejects.toMatchObject({ code: 'defect_review.invalid_request' });
    expect(engine.review).not.toHaveBeenCalled();
  });

  it('validates model status and strips unknown provider/proof fields', () => {
    expect(validatedDefectModelStatus({ configured: true, model: metadata(), limitations: [], apiKey: 'hidden', proofStatus: 'SAFE' }))
      .toEqual({ configured: true, model: metadata(), limitations: [] });
    expect(validatedDefectModelStatus({ configured: false, model: null, limitations: ['Model artifact missing.'] })).toMatchObject({ configured: false });
    expect(() => validatedDefectModelStatus({ configured: true, model: null, limitations: [] })).toThrow(expect.objectContaining({ code: 'engine.invalid_result' }));
  });

  it('dispatches inference and server-only status through the shared bounded worker, without compiler or shell arguments', async () => {
    const worker = { execute: jest.fn(async () => ({})) };
    const service = new PythonDefectReviewService(worker as unknown as PythonJsonWorkerService);
    const request = new DefectReviewRequest(input()).toPrimitives();
    await service.review(request); await service.status();
    expect(worker.execute.mock.calls).toEqual([['ml_engine.defect_detection', request], ['ml_engine.defect_detection', { action: 'status' }]]);
  });
});

describe('Local defect review HTTP / CQRS boundary', () => {
  let app: INestApplication;
  let base: string;
  let engine: jest.Mocked<IDefectReviewEngine>;

  beforeAll(async () => {
    engine = { review: jest.fn(async (request) => envelope(request)), status: jest.fn(async () => ({ configured: true, model: metadata(), limitations: [] })) };
    const module = await Test.createTestingModule({ imports: [DefectDetectionModule] }).overrideProvider(DEFECT_REVIEW_ENGINE).useValue(engine).compile();
    app = module.createNestApplication({ bodyParser: false });
    app.use(json({ limit: '3mb' })); app.setGlobalPrefix('api');
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
    app.useGlobalFilters(new GlobalExceptionFilter());
    await app.listen(0, '127.0.0.1'); base = await app.getUrl();
  });
  afterAll(async () => { await app.close(); });
  const post = async (body: unknown): Promise<Response> => fetch(`${base}/api/defect-reviews`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });

  it('runs source-only inference through CQRS without importing persistence or proof modules', async () => {
    const response = await post(input());
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ status: 'ANALYZED', engineVersion: 'paired-defect-v1', aiIsProof: false,
      counterexamplesExecuted: false, sourceHashes: { java: hash(input().javaSource) }, findings: [{ evidenceStatus: 'MODEL_HYPOTHESIS' }] });
    expect(engine.review).toHaveBeenCalledTimes(1);
  });

  it('returns local model provenance and evaluation without accepting status actions from the caller', async () => {
    const response = await fetch(`${base}/api/defect-reviews/status`);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ configured: true, model: metadata(), limitations: [] });
    expect(engine.status).toHaveBeenCalledTimes(1);
  });

  it.each([
    () => ({ ...input(), action: 'status' }), () => ({ ...input(), label: 'DEFECTIVE' }),
    () => ({ ...input(), testPredictions: [] }), () => ({ ...input(), modelPath: '/tmp/injected.json' }),
    () => ({ ...input(), apiKey: 'not accepted' }), () => ({ ...input(), javaSource: 42 }),
    () => ({ ...input(), cobolSourceFormat: 'AUTO' }), () => ({ ...input(), cobolSourceFormat: undefined }),
    () => ({ ...input(), javaSource: '\ud800' }), () => ({ ...input(), javaSource: ' ' }),
  ])('rejects labels, configuration overrides and malformed requests before inference', async (invalid) => {
    const calls = engine.review.mock.calls.length;
    const response = await post(invalid());
    expect(response.status).toBe(400);
    expect(engine.review).toHaveBeenCalledTimes(calls);
  });

  it('sanitizes a malformed engine result rather than publishing false source evidence', async () => {
    engine.review.mockImplementationOnce(async (request) => {
      const raw = envelope(request); raw.findings[0].javaExcerpt = 'private malformed model output'; return raw;
    });
    const response = await post(input());
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(JSON.stringify(body)).not.toContain('private malformed model output');
    expect(body).toMatchObject({ code: 'engine.invalid_result', statusCode: 503 });
  });
});
