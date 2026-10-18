import { createHash } from 'node:crypto';
import { createServer, type RequestListener } from 'node:http';
import { once } from 'node:events';
import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiClient } from '../src/api-client';
import { parseMatchingResult, validateMatchingRequest, type MatchingRequest, type MatchingResult } from '../src/matching-contracts';

const hash = (value: string) => createHash('sha256').update(value).digest('hex');
export function matchingRequest(): MatchingRequest {
  return { cobolSource: 'ADD A TO B GIVING C.', cobolSourceFormat: 'FREE', candidates: [
    { candidateId: 'candidate-1', moduleName: 'Addition.java', javaSource: 'return a + b;' },
    { candidateId: 'candidate-2', moduleName: 'Subtraction.java', javaSource: 'return a - b;' },
  ], topK: 2 };
}
export function matchingResult(input = matchingRequest()): MatchingResult {
  return { status: 'MATCH_SUGGESTED', reason: 'Review the learned candidate ranking.', matchingIsProof: false, granularity: 'PROGRAM',
    model: { id: 'paired-gnn-test-fixture', sha256: 'a'.repeat(64), trainingDataset: 'COBOL-JavaTrans', evaluation: { purpose: 'Protocol fixture only, not measured model quality.' } },
    cobolSourceSha256: hash(input.cobolSource), candidates: input.candidates.map((item, index) => ({ candidateId: item.candidateId,
      moduleName: item.moduleName, javaSourceSha256: hash(item.javaSource), rank: index + 1, similarity: 0.9 - index * 0.4 })),
    thresholds: { minimumSimilarity: 0.6, minimumMargin: 0.1 } };
}
async function serverTest(listener: RequestListener, run: (url: string) => Promise<void>): Promise<void> {
  const server = createServer(listener); server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }
}

test('matching validates candidate count, unique identity, module names, source limits and topK', () => {
  assert.deepEqual(validateMatchingRequest(matchingRequest()), matchingRequest());
  for (const input of [
    { ...matchingRequest(), candidates: [] },
    { ...matchingRequest(), candidates: Array(21).fill(matchingRequest().candidates[0]) },
    { ...matchingRequest(), candidates: [matchingRequest().candidates[0], matchingRequest().candidates[0]] },
    { ...matchingRequest(), candidates: [{ ...matchingRequest().candidates[0], moduleName: '../Private.java' }] },
    { ...matchingRequest(), candidates: [{ ...matchingRequest().candidates[0], candidateId: 'path/file' }] },
    { ...matchingRequest(), candidates: [{ ...matchingRequest().candidates[0], candidateId: undefined }] },
    { ...matchingRequest(), candidates: [{ ...matchingRequest().candidates[0], candidateId: '.invalid-start' }] },
    { ...matchingRequest(), topK: 3 }, { ...matchingRequest(), topK: 1.5 },
    { ...matchingRequest(), cobolSourceFormat: 'INVALID' }, { ...matchingRequest(), cobolSource: '' },
  ]) assert.throws(() => validateMatchingRequest(input as MatchingRequest));
});

test('matching requires advisory program granularity, provenance, consistent ranking and exact submitted source hashes', () => {
  const input = matchingRequest(); const result = matchingResult();
  assert.deepEqual(parseMatchingResult(result, input), result);
  assert.equal(parseMatchingResult({ ...result, status: 'REVIEW_REQUIRED' }, input).status, 'REVIEW_REQUIRED');
  const broken: unknown[] = [
    { ...result, matchingIsProof: true }, { ...result, granularity: 'FUNCTION' }, { ...result, status: 'SAFE' },
    { ...result, model: { ...result.model, sha256: 'missing' } },
    { ...result, model: { ...result.model, trainingDataset: '' } },
    { ...result, model: { ...result.model, evaluation: null } },
    { ...result, cobolSourceSha256: hash('different COBOL') },
    { ...result, candidates: result.candidates.slice(0, 1) },
    { ...result, candidates: [result.candidates[0], result.candidates[0]] },
    ...['candidateId', 'moduleName', 'javaSourceSha256', 'rank', 'similarity'].map(key => ({ ...result,
      candidates: [{ ...result.candidates[0], [key]: ({ candidateId: 'invented', moduleName: 'Different.java', javaSourceSha256: hash('other'), rank: 2, similarity: 1.5 } as Record<string, unknown>)[key] }, result.candidates[1]] })),
    { ...result, candidates: [{ ...result.candidates[0], similarity: 0.1 }, result.candidates[1]] },
    { ...result, thresholds: { minimumSimilarity: 0.6, minimumMargin: -1 } },
  ];
  for (const value of broken) assert.throws(() => parseMatchingResult(value, input));
});

test('matching posts only explicit sources to the local endpoint and validates source-bound results', async () => {
  let posted: unknown;
  await serverTest(async (req, res) => {
    assert.equal(req.url, '/api/matches'); assert.equal(req.headers.authorization, undefined);
    const chunks: Buffer[] = []; for await (const chunk of req) chunks.push(Buffer.from(chunk));
    posted = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(matchingResult()));
  }, async url => { assert.equal((await new ApiClient(url).match(matchingRequest())).matchingIsProof, false); });
  assert.deepEqual(posted, matchingRequest());
  await serverTest((_req, res) => {
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(matchingResult({ ...matchingRequest(), cobolSource: 'different source' })));
  }, async url => { await assert.rejects(new ApiClient(url).match(matchingRequest()), /submitted COBOL/); });
});

test('matching fails closed for source limits, payload size, HTTP errors, timeout and cancellation', async () => {
  const client = new ApiClient('http://127.0.0.1:1');
  await assert.rejects(client.match({ ...matchingRequest(), cobolSource: 'x'.repeat(100001) }), /100000/);
  await assert.rejects(client.match({ cobolSource: '\0'.repeat(100000), candidates: Array.from({ length: 20 }, (_, index) => ({ candidateId: `candidate-${index}`, moduleName: `File${index}.java`, javaSource: '\0'.repeat(100000) })), topK: 20 }), /2 MiB/);
  await serverTest((_req, res) => { res.writeHead(503, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ message: 'PRIVATE SOURCE' })); }, async url => {
    await assert.rejects(new ApiClient(url).match(matchingRequest()), (error: Error) => error.message.includes('503') && !error.message.includes('PRIVATE'));
  });
  await serverTest((_req, _res) => {}, async url => {
    await assert.rejects(new ApiClient(url, 20).match(matchingRequest()), /timed out/);
    const abort = new AbortController(); const pending = new ApiClient(url).match(matchingRequest(), abort.signal); abort.abort();
    await assert.rejects(pending, /cancelled/);
    await assert.rejects(new ApiClient(url).match(matchingRequest(), abort.signal), /cancelled/);
  });
});
