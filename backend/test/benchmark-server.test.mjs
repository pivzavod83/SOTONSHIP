import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { request as httpRequest } from 'node:http';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createBenchmarkServer } from '../benchmark-ui/serve.mjs';

const catalog = { versions: [{ id: 'sample', source: { reportPath: 'ml-engine/evaluation/does-not-exist.json', sha256: '0'.repeat(64) } }], repository: { branch: 'test' } };
const start = async options => {
  const server = createBenchmarkServer(options);
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  return { server, url: `http://127.0.0.1:${server.address().port}` };
};
const close = server => new Promise(resolve => server.close(resolve));

test('dashboard only reads explicit API routes, preserves nulls and supplies stable report links', async () => {
  const { server, url } = await start({ catalogLoader: async () => catalog, researchLoader: async () => ({ papers: [], proposals: [] }) });
  try {
    const response = await fetch(`${url}/api/catalog`);
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.versions[0].source.localReportUrl, '/reports/sample');
    assert.match(response.headers.get('content-security-policy'), /frame-ancestors 'none'/);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await (await fetch(`${url}/api/research`)).json(), { papers: [], proposals: [] });
    assert.match((await fetch(`${url}/api/catalog/download`)).headers.get('content-disposition'), /attachment/);
    for (const path of ['/api/catalog?key=secret', '/.env', '/api/train', '/reports/unknown', '/styles.css?file=../.env']) {
      assert.equal((await fetch(url + path)).status, 404, path);
    }
    assert.equal((await fetch(`${url}/api/train`, { method: 'POST' })).status, 405);
    assert.equal((await fetch(`${url}/api/catalog`, { headers: { Origin: 'https://example.com' } })).status, 403);
    assert.equal((await fetch(`${url}/api/catalog`, { method: 'HEAD' })).status, 200);
    assert.equal(await (await fetch(`${url}/api/catalog`, { method: 'HEAD' })).text(), '');
    const hostile = await new Promise((resolve, reject) => {
      const req = httpRequest(`${url}/api/catalog`, { headers: { Host: 'example.com' } }, res => { res.resume(); resolve(res.statusCode); });
      req.on('error', reject); req.end();
    });
    assert.equal(hostile, 403);
  } finally { await close(server); }
});

test('unavailable evidence returns an explicit failure, never an empty successful benchmark', async () => {
  const { server, url } = await start({ catalogLoader: async () => { throw new Error('private filesystem details'); } });
  try {
    const response = await fetch(`${url}/api/catalog`);
    assert.equal(response.status, 503);
    assert.doesNotMatch(await response.text(), /private filesystem details/);
  } finally { await close(server); }
});

test('report download cannot escape the evaluation artifact directory', async () => {
  const { server, url } = await start({ catalogLoader: async () => ({ versions: [{ id: 'bad', source: { reportPath: 'ml-engine/evaluation/../../.env' } }] }) });
  try { assert.equal((await fetch(`${url}/reports/bad`)).status, 404); }
  finally { await close(server); }
});

test('report bytes must match the catalog hash at download time', async () => {
  const root = await mkdtemp(join(tmpdir(), 'parity-benchmark-test-'));
  const relative = 'ml-engine/evaluation/test/report.json';
  await mkdir(join(root, 'ml-engine/evaluation/test'), { recursive: true });
  const bytes = Buffer.from('{"pairs":8,"accuracy":0.5}\n');
  await writeFile(join(root, relative), bytes);
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  const { server, url } = await start({ repoRoot: root,
    catalogLoader: async () => ({ versions: [{ id: 'recorded', source: { reportPath: relative, sha256 } }] }),
  });
  try {
    const good = await fetch(`${url}/reports/recorded`);
    assert.equal(good.status, 200); assert.equal(await good.text(), bytes.toString());
    await writeFile(join(root, relative), '{"accuracy":1}');
    const changed = await fetch(`${url}/reports/recorded`);
    assert.equal(changed.status, 409); assert.match(await changed.text(), /changed after catalog validation/);
  } finally { await close(server); await rm(root, { recursive: true, force: true }); }
});
