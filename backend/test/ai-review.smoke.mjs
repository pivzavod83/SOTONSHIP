/**
 * HTTP -> CQRS -> real Python -> local MOCK provider -> source-bound response.
 * This tests integration, NOT actual AI quality. No database, key or internet.
 */
import 'reflect-metadata';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { NestFactory } = require('@nestjs/core');
const { ValidationPipe } = require('@nestjs/common');
const { AiReviewModule } = require('../dist/modules/ai-review/ai-review.module.js');
const { GlobalExceptionFilter } = require('../dist/common/exceptions/global-exception.filter.js');
const root = new URL('../../', import.meta.url);
const fixture = (name) => readFile(new URL(`ml-engine/data/fixtures/${name}`, root), 'utf8');
const [cobolSource, javaSource] = await Promise.all([fixture('FX-WIRE-CALC.cbl'), fixture('FX-WIRE-CALC.java.txt')]);
const cobolLine = cobolSource.split('\n').findIndex((line) => /COMPUTE.*ROUNDED/i.test(line)) + 1;
const javaLine = javaSource.split('\n').findIndex((line) => /new BigDecimal/.test(line)) + 1;
assert.ok(cobolLine > 0 && javaLine > 0, 'fixture anchors must exist');
const request = { moduleName: 'FX-WIRE-CALC', cobolSource, javaSource, cobolSourceFormat: 'FREE', analysisContext: 'Mock integration check, no measured AI diagnosis.' };
const digest = (text) => createHash('sha256').update(text).digest('hex');
const dummyToken = 'mock-only-not-a-real-provider-key';
const privateBody = 'provider-private-body-must-not-appear';
const finding = {
  title: 'Mock rounding hypothesis', category: 'ROUNDING', severity: 'HIGH',
  explanation: 'Mock review fixture for validating the response protocol; not a real model diagnosis.',
  cobolLines: { start: cobolLine, end: cobolLine }, javaLines: { start: javaLine, end: javaLine },
  suggestedFix: 'Review decimal input representation and preserve the COBOL rounding/storage contract.',
  candidateInputs: [{ inputsJson: '{"amount":"45.00","rate":"1.1830"}', rationale: 'Mock proposed input; no execution occurs.' }],
};
let mode = 'normal';
let calls = 0;
const providerErrors = [];
const provider = createServer(async (incoming, outgoing) => {
  try {
    calls += 1;
    assert.equal(incoming.method, 'POST');
    assert.equal(incoming.url, '/v1/chat/completions');
    assert.equal(incoming.headers.authorization, `Bearer ${dummyToken}`);
    let raw = '';
    for await (const chunk of incoming) raw += chunk;
    const body = JSON.parse(raw);
    assert.equal(body.model, 'mock-coding-model');
    assert.equal(body.response_format.type, 'json_schema');
    assert.equal(body.response_format.json_schema.strict, true);
    const supplied = JSON.parse(body.messages[1].content);
    assert.equal(supplied.cobolSourceLines.map((line) => line.text).join('\n'), cobolSource);
    assert.equal(supplied.javaSourceLines.map((line) => line.text).join('\n'), javaSource);
    assert.equal(supplied.analysisContext, request.analysisContext);
    assert.equal(supplied.cobolSourceFormat, 'FREE');
    assert.equal(raw.includes(dummyToken), false, 'key must not be in model prompt');
    if (mode === 'http-error') {
      outgoing.writeHead(401, { 'content-type': 'application/json' });
      outgoing.end(JSON.stringify({ error: privateBody })); return;
    }
    const proposed = structuredClone(finding);
    if (mode === 'bad-span') proposed.javaLines.end = javaSource.split('\n').length + 1;
    if (mode === 'empty-fix') proposed.suggestedFix = '';
    const content = JSON.stringify({ summary: 'Mock provider integration check only.', findings: mode === 'empty' ? [] : [proposed], limitations: ['No real model was evaluated.'] });
    const message = mode === 'refused' ? { refusal: 'Refused', content: null } : { content };
    outgoing.writeHead(200, { 'content-type': 'application/json' });
    outgoing.end(JSON.stringify({ choices: [{ finish_reason: mode === 'truncated' ? 'length' : 'stop', message }] }));
  } catch (error) {
    providerErrors.push(error);
    outgoing.writeHead(500); outgoing.end('mock assertion failed');
  }
});
process.env.PYTHON_BIN = fileURLToPath(new URL('ml-engine/.venv/bin/python', root));
process.env.ML_ENGINE_PATH = fileURLToPath(new URL('ml-engine/', root));
process.env.ML_TIMEOUT_MS = '10000';
process.env.LLM_TIMEOUT_SECONDS = '5';
process.env.LLM_RESPONSE_FORMAT = 'json_schema';
process.env.LLM_MAX_COMPLETION_TOKENS = '4096';
delete process.env.LLM_MODEL;
delete process.env.LLM_API_KEY;
let app;
let checks = 0;
try {
  await new Promise((resolve) => provider.listen(0, '127.0.0.1', resolve));
  process.env.LLM_BASE_URL = `http://127.0.0.1:${provider.address().port}/v1`;
  app = await NestFactory.create(AiReviewModule, { logger: false });
  app.setGlobalPrefix('api');
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
  app.useGlobalFilters(new GlobalExceptionFilter());
  await app.listen(0, '127.0.0.1');
  const base = await app.getUrl();
  async function review(body = request, expectedHttp = 200) {
    const response = await fetch(`${base}/api/ai-reviews`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(15000),
    });
    const result = await response.json();
    assert.equal(response.status, expectedHttp, 'unexpected API HTTP status');
    const encoded = JSON.stringify(result);
    assert.equal(encoded.includes(dummyToken), false, 'response leaked credentials');
    assert.equal(encoded.includes(privateBody), false, 'response leaked provider body');
    checks += 1;
    return result;
  }
  const unconfigured = await review();
  assert.equal(unconfigured.status, 'NOT_CONFIGURED');
  assert.deepEqual(unconfigured.findings, []);
  assert.equal(calls, 0);
  process.env.LLM_MODEL = 'mock-coding-model';
  process.env.LLM_API_KEY = dummyToken;
  const analyzed = await review();
  assert.equal(analyzed.status, 'ANALYZED');
  assert.equal(analyzed.aiIsProof, false);
  assert.equal(analyzed.counterexamplesExecuted, false);
  assert.equal(analyzed.promptVersion, 'paired-defect-review-v1');
  assert.deepEqual(analyzed.sourceHashes, { cobol: digest(cobolSource), java: digest(javaSource) });
  assert.equal(analyzed.findings[0].evidenceStatus, 'AI_HYPOTHESIS');
  assert.equal(analyzed.findings[0].candidateInputs[0].status, 'NOT_EXECUTED');
  assert.equal(analyzed.findings[0].cobolExcerpt, cobolSource.split('\n')[cobolLine - 1]);
  assert.equal(analyzed.findings[0].javaExcerpt, javaSource.split('\n')[javaLine - 1]);
  assert.equal(analyzed.formalProofStatus, undefined);
  for (const [nextMode, status] of [['bad-span', 'INVALID_MODEL_OUTPUT'], ['refused', 'REFUSED'], ['truncated', 'INVALID_MODEL_OUTPUT'], ['http-error', 'PROVIDER_ERROR'], ['empty', 'ANALYZED']]) {
    mode = nextMode;
    const result = await review();
    assert.equal(result.status, status, `unexpected ${mode} outcome`);
    assert.deepEqual(result.findings, []);
    assert.equal(result.aiIsProof, false);
  }
  mode = 'empty-fix';
  const noFix = await review();
  assert.equal(noFix.status, 'ANALYZED');
  assert.equal(noFix.findings[0].suggestedFix, '');
  const previousCalls = calls;
  await review({ ...request, apiKey: dummyToken }, 400);
  await review({ ...request, cobolSource: ' ' }, 400);
  assert.equal(calls, previousCalls, 'invalid requests must not reach model');
  assert.deepEqual(providerErrors, []);
  console.log(`AI review integration: ${checks} HTTP checks passed through CQRS and real Python using a LOCAL MOCK provider. No real AI accuracy was measured.`);
} finally {
  if (app) await app.close();
  provider.closeAllConnections();
  await new Promise((resolve) => provider.close(resolve));
}
