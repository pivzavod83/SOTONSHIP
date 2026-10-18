import { createHash } from 'node:crypto';
import { createServer, type RequestListener, type Server } from 'node:http';
import { once } from 'node:events';
import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiClient, normalizeBackendUrl } from '../src/api-client';
import type { VerificationRequest, VerificationResult } from '../src/contracts';

function request(): VerificationRequest {
  return {
    moduleName: 'FX-WIRE-CALC.cbl', category: 'FX_CONVERSION', cobolSource: 'COBOL source', javaSource: 'Java source',
    proofInputs: {
      cobolDialectProfile: 'IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1', cobolSourceFormat: 'FREE',
      amountField: 'INPUT-AMOUNT', rateField: 'REFERENCE-RATE', resultField: 'SETTLEMENT-RESULT',
      javaAmountParameter: 'principal', javaRateParameter: 'quote', amountMinCents: -999999999, amountMaxCents: 999999999,
      referenceCurrencyPair: 'GBP/EUR', referenceSource: 'Bank of England', referenceCollectedDate: '2026-10-17',
    },
  };
}
function result(input = request()): VerificationResult {
  const hash = (source: string) => createHash('sha256').update(source).digest('hex');
  return {
    ...input, patchedJavaSource: input.patchedJavaSource ?? '', id: '11111111-1111-4111-8111-111111111111',
    formalProofStatus: 'UNSAT_PROVEN_SAFE', gnnAlignmentScore: 0.9, gnnBugRiskScore: 0.1, version: 1,
    fStringSummary: 'Equivalent within the finite input domain.', cpgGraphJson: { nodes: [], edges: [] }, provenanceJson: {}, counterexamplesJson: [],
    proofScope: {
      supported: true, bounded: true, proofInputs: input.proofInputs,
      inputAmountCents: { min: input.proofInputs.amountMinCents, max: input.proofInputs.amountMaxCents },
      rate: { rate: '1.183000000000', currencyPair: 'GBP/EUR', source: 'Bank of England', collectedDate: '2026-10-17' },
      sourceSha256: { cobol: hash(input.cobolSource), java: hash(input.javaSource) },
    },
  };
}
async function serverTest(listener: RequestListener, run: (url: string) => Promise<void>): Promise<void> {
  const server: Server = createServer(listener);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}

test('backend URL normalizes the optional API suffix and permits only local HTTP(S)', () => {
  assert.equal(normalizeBackendUrl(' http://localhost:3001/api/ '), 'http://localhost:3001');
  assert.equal(normalizeBackendUrl('https://127.0.0.1:443/'), 'https://127.0.0.1');
  assert.equal(normalizeBackendUrl('http://[::1]:3001/api'), 'http://[::1]:3001');
  for (const url of ['https://example.com', 'http://localhost.example.com', 'file:///tmp/api', 'http://user:secret@localhost:3001', 'http://localhost/api?secret=x', 'http://localhost/#x', 'http://localhost/other', 'not a URL']) {
    assert.throws(() => normalizeBackendUrl(url));
  }
});

test('verify posts only JSON source/contract fields with no authentication and validates the response', async () => {
  let posted: unknown, path: string | undefined, authorization: string | undefined;
  await serverTest(async (req, res) => {
    path = req.url; authorization = req.headers.authorization;
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(Buffer.from(chunk));
    posted = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    res.writeHead(201, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(result()));
  }, async url => {
    const proof = await new ApiClient(`${url}/api`).verify(request());
    assert.equal(proof.formalProofStatus, 'UNSAT_PROVEN_SAFE');
  });
  assert.deepEqual(posted, request());
  assert.equal(path, '/api/verifications');
  assert.equal(authorization, undefined);
});

test('HTTP failures are bounded and never echo source code from the server', async () => {
  for (const status of [400, 401, 403, 404, 413, 422, 500, 503]) {
    await serverTest((_req, res) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ message: 'PRIVATE COBOL SOURCE'.repeat(1000) })); }, async url => {
      await assert.rejects(new ApiClient(url).verify(request()), (error: Error) => {
        assert.ok(error.message.length < 400); assert.ok(error.message.includes(String(status))); assert.ok(!error.message.includes('PRIVATE'));
        return true;
      });
    });
  }
});

test('invalid JSON, HTML, invalid evidence, oversized declared response and redirects fail closed', async () => {
  const responses: Array<{ status?: number; headers: Record<string, string>; body: string }> = [
    { headers: { 'Content-Type': 'application/json' }, body: '{bad json' },
    { headers: { 'Content-Type': 'text/html' }, body: '<html>Proxy page</html>' },
    { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...result(), formalProofStatus: 'SAFE' }) },
    { headers: { 'Content-Type': 'application/json', 'Content-Length': '20000000' }, body: '' },
    { status: 307, headers: { Location: 'http://example.com/collect' }, body: '' },
  ];
  for (const response of responses) {
    await serverTest((_req, res) => { res.writeHead(response.status ?? 200, response.headers); res.end(response.body); }, async url => {
      await assert.rejects(new ApiClient(url).verify(request()));
    });
  }
});

test('a valid proof for different source code cannot authorize the requested sources', async () => {
  await serverTest((_req, res) => {
    res.writeHead(201, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result({ ...request(), javaSource: 'Different Java source' })));
  }, async url => { await assert.rejects(new ApiClient(url).verify(request()), /requested module and source/); });
});

test('a source-bound proof over narrower bounds cannot authorize the requested contract', async () => {
  await serverTest((_req, res) => {
    res.writeHead(201, { 'Content-Type': 'application/json' });
    const input = request();
    res.end(JSON.stringify(result({ ...input, proofInputs: { ...input.proofInputs, amountMinCents: 0, amountMaxCents: 1 } })));
  }, async url => { await assert.rejects(new ApiClient(url).verify(request()), /exact requested mapping, bounds/); });
});

test('chunked response evidence is bounded even without a declared content length', async () => {
  await serverTest((_req, res) => {
    res.writeHead(201, { 'Content-Type': 'application/json' });
    res.write(Buffer.alloc(8 * 1048576, ' '));
    res.end(Buffer.alloc(8 * 1048576 + 1, ' '));
  }, async url => { await assert.rejects(new ApiClient(url).verify(request()), /16 MiB/); });
});

test('timeout and explicit cancellation stop waiting for the backend', async () => {
  await serverTest((_req, _res) => {}, async url => {
    await assert.rejects(new ApiClient(url, 20).verify(request()), /timed out/);
    const controller = new AbortController();
    const pending = new ApiClient(url).verify(request(), controller.signal);
    controller.abort();
    await assert.rejects(pending, /cancelled/);
    await assert.rejects(new ApiClient(url).verify(request(), controller.signal), /cancelled/);
  });
});

test('request validation and byte limits reject before any network call', async () => {
  const client = new ApiClient('http://127.0.0.1:1');
  await assert.rejects(client.verify({ ...request(), cobolSource: 'x'.repeat(100001) }), /100000/);
  await assert.rejects(client.verify({ ...request(), javaSource: Array(1501).fill('x').join('\n') }), /1500/);
  await assert.rejects(client.verify({ ...request(), cobolSource: '\0'.repeat(100000), javaSource: '\0'.repeat(100000) }), /1 MiB/);
  await assert.rejects(client.verify({ ...request(), proofInputs: { ...request().proofInputs, amountMinCents: 1.5 } }), /integer/);
  assert.throws(() => new ApiClient('http://127.0.0.1:3001', Infinity), /timeout/);
});
