import { createServer, type RequestListener } from 'node:http';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiClient } from '../src/api-client';
import { aiSourceHash, parseAiReviewResult, sameAiReviewBinding, validateAiReviewRequest, type AiReviewBinding, type AiReviewRequest, type AiReviewResult } from '../src/ai-review-contracts';

const input: AiReviewRequest = { moduleName: 'MEDIAN.cbl', cobolSource: '       PROCEDURE DIVISION.\r\n           MOVE A(2) TO RESULT.\r\n', javaSource: 'class Median {\n  int result = values[2];\n}\n', cobolSourceFormat: 'FIXED', analysisContext: 'Input array contains three ordered values.' };
function review(status: AiReviewResult['status'] = 'ANALYZED'): AiReviewResult {
  return { status, summary: 'Protocol fixture: suspected indexing mismatch.', findings: status !== 'ANALYZED' ? [] : [{ findingId: 'F1', title: 'Index conventions differ', category: 'INDEXING', severity: 'HIGH', explanation: 'COBOL element 2 is Java element 1.',
    cobolLines: { start: 2, end: 2 }, javaLines: { start: 2, end: 2 }, cobolExcerpt: '           MOVE A(2) TO RESULT.\r', javaExcerpt: '  int result = values[2];',
    suggestedFix: 'Review the one-based to zero-based offset.', candidateInputs: [{ inputsJson: '{"values":[10,20,30]}', rationale: 'Distinct adjacent elements expose an index shift.', status: 'NOT_EXECUTED' }], evidenceStatus: 'AI_HYPOTHESIS' }],
    limitations: ['Protocol fixture; not a model quality evaluation.'], sourceHashes: { cobol: aiSourceHash(input.cobolSource), java: aiSourceHash(input.javaSource) },
    provider: { protocol: 'OPENAI_COMPATIBLE_CHAT', model: 'test-model' }, aiIsProof: false, promptVersion: 'paired-defect-review-v1', counterexamplesExecuted: false };
}
async function serverTest(listener: RequestListener, run: (url: string) => Promise<void>): Promise<void> {
  const server = createServer(listener); server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }
}

test('AI review posts the exact source pair and context without a key or proof contract', async () => {
  let posted: unknown;
  await serverTest(async (req, res) => {
    assert.equal(req.url, '/api/ai-reviews'); assert.equal(req.headers.authorization, undefined);
    const chunks: Buffer[] = []; for await (const chunk of req) chunks.push(Buffer.from(chunk));
    posted = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(review()));
  }, async url => {
    const result = await new ApiClient(url).reviewPair(input);
    assert.equal(result.findings[0].javaLines?.start, 2); assert.equal(result.aiIsProof, false);
  });
  assert.deepEqual(posted, input);
  assert.throws(() => validateAiReviewRequest({ ...input, apiKey: 'must not upload' } as AiReviewRequest), /unexpected fields/);
});

test('all non-success AI states remain empty and explicit, including NOT_CONFIGURED', () => {
  for (const status of ['NOT_CONFIGURED', 'PROVIDER_ERROR', 'INVALID_MODEL_OUTPUT', 'REFUSED'] as const) {
    assert.equal(parseAiReviewResult(review(status), input).status, status);
    assert.throws(() => parseAiReviewResult({ ...review(status), findings: review().findings }, input), /findings/);
  }
  const noFindings = parseAiReviewResult({ ...review(), findings: [] }, input);
  assert.equal(noFindings.aiIsProof, false); assert.equal(noFindings.counterexamplesExecuted, false);
});

test('AI review rejects proof claims, executed suggestions, altered sources and fabricated spans/excerpts', () => {
  const mutations: Array<(result: AiReviewResult) => void> = [
    result => { result.sourceHashes.java = '0'.repeat(64); },
    result => { (result as unknown as Record<string, unknown>).aiIsProof = true; },
    result => { (result as unknown as Record<string, unknown>).counterexamplesExecuted = true; },
    result => { result.findings[0].javaExcerpt = '<script>fabricated</script>'; },
    result => { result.findings[0].javaLines!.end = 99; },
    result => { result.findings[0].cobolLines = null; result.findings[0].cobolExcerpt = ''; result.findings[0].javaLines = null; result.findings[0].javaExcerpt = ''; },
    result => { (result.findings[0].candidateInputs[0] as unknown as Record<string, unknown>).status = 'PASSED'; },
    result => { result.findings[0].candidateInputs[0].inputsJson = '[1,2]'; },
    result => { result.findings[0].candidateInputs[0].inputsJson = '{"value":1e400}'; },
    result => { result.findings[0].findingId = 'F900'; },
    result => { (result as unknown as Record<string, unknown>).status = ['ANALYZED']; },
    result => { (result.findings[0] as unknown as Record<string, unknown>).category = ['INDEXING']; },
  ];
  for (const mutate of mutations) { const candidate = review(); mutate(candidate); assert.throws(() => parseAiReviewResult(candidate, input)); }
  assert.equal(parseAiReviewResult(review(), input).findings[0].cobolExcerpt.endsWith('\r'), true, 'CR from raw CRLF source must remain in exact excerpt.');
  const lastLine = review(); lastLine.findings[0].javaLines = { start: 4, end: 4 }; lastLine.findings[0].javaExcerpt = '';
  assert.equal(parseAiReviewResult(lastLine, input).findings[0].javaLines!.start, 4, 'Raw trailing newline produces a trailing empty line.');
});

test('AI request limits and binding guard edits, Undo, endpoint, selection, context and format races', () => {
  assert.throws(() => validateAiReviewRequest({ ...input, javaSource: '\n'.repeat(1500) + 'x' }), /1500/);
  assert.throws(() => validateAiReviewRequest({ ...input, analysisContext: 'x'.repeat(8001) }), /context/);
  for (const value of ['\ud800', '\udc00', '\ud800a']) assert.throws(() => validateAiReviewRequest({ ...input, javaSource: value }), /Unicode/);
  const binding: AiReviewBinding = { cobolUri: 'untitled:cobol', javaUri: 'untitled:java', cobolVersion: 1, javaVersion: 1,
    backendUrl: 'http://127.0.0.1:3001', sourceFormat: 'FREE', analysisContext: '', cobolHash: aiSourceHash(input.cobolSource), javaHash: aiSourceHash(input.javaSource), generation: 1 };
  assert.equal(sameAiReviewBinding(binding, { ...binding }), true);
  for (const [key, value] of Object.entries({ cobolUri: 'untitled:other', javaUri: 'untitled:other', cobolVersion: 2, javaVersion: 3,
    backendUrl: 'http://127.0.0.1:3002', sourceFormat: 'FIXED', analysisContext: 'new behavior', cobolHash: 'a'.repeat(64), javaHash: 'b'.repeat(64), generation: 2 })) {
    assert.equal(sameAiReviewBinding(binding, { ...binding, [key]: value }), false, key);
  }
});

test('AI provider errors never echo backend payloads; cancellation and timeout fail closed', async () => {
  await assert.rejects(new ApiClient('http://127.0.0.1:1').reviewPair({ ...input, cobolSource: '\x01'.repeat(100000), javaSource: '\x01'.repeat(100000) }), /1000000-byte/);
  await serverTest((_req, res) => { res.writeHead(503, { 'Content-Type': 'application/json' }); res.end('{"secret":"PRIVATE SOURCE"}'); }, async url => {
    await assert.rejects(new ApiClient(url).reviewPair(input), (error: Error) => error.message.includes('503') && !error.message.includes('PRIVATE'));
  });
  await serverTest((_req, _res) => {}, async url => {
    await assert.rejects(new ApiClient(url, 20).reviewPair(input), /timed out/);
    const controller = new AbortController(); const pending = new ApiClient(url).reviewPair(input, controller.signal); controller.abort();
    await assert.rejects(pending, /cancelled/);
  });
});

test('webview renders model strings as literal text and hides stale findings', () => {
  class Node {
    children: Node[] = []; textContent = ''; value = ''; hidden = false; disabled = false; title = ''; className = ''; open = false;
    classList = { toggle: (_name: string, _enabled: boolean) => {} };
    append(...children: Node[]): void { this.children.push(...children); }
    replaceChildren(...children: Node[]): void { this.children = children; }
    addEventListener(_event: string, _action: unknown): void {}
  }
  const nodes = new Map<string, Node>(); const listeners: Record<string, (event: unknown) => void> = {};
  const document = { activeElement: null, body: new Node(), createElement: (_tag: string) => new Node(), getElementById: (id: string) => {
    if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id)!;
  } };
  const script = readFileSync(resolve(__dirname, '../../media/workbench.js'), 'utf8');
  assert.ok(!script.includes('innerHTML') && !script.includes('insertAdjacentHTML'));
  runInNewContext(script, { document, window: { addEventListener: (name: string, listener: (event: unknown) => void) => { listeners[name] = listener; } }, acquireVsCodeApi: () => ({ postMessage: (_message: unknown) => {} }), setTimeout, clearTimeout }, { timeout: 1000 });
  const result = review(); result.summary = '<script>stealKey()</script>'; result.findings[0].title = '<img src=x onerror=stealKey()>';
  const state = { busy: false, backendUrl: 'http://127.0.0.1:3001', files: {}, matchingFiles: [], aiReviewResult: result, aiReviewStale: false };
  const allText = (node: Node): string => node.textContent + node.children.map(allText).join('');
  listeners.message({ data: { type: 'state', state } });
  const rendered = allText(nodes.get('ai-review-result')!);
  assert.ok(rendered.includes(result.summary)); assert.ok(rendered.includes(result.findings[0].title)); assert.ok(rendered.includes('NOT EXECUTED'));
  listeners.message({ data: { type: 'state', state: { ...state, aiReviewStale: true } } });
  const stale = allText(nodes.get('ai-review-result')!);
  assert.ok(stale.includes('Findings are hidden')); assert.ok(!stale.includes(result.findings[0].title));
});
