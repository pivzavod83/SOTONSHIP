/** Read-only, loopback benchmark library. Never fits models or executes source. */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { resolve, sep } from 'node:path';
import { buildCatalog } from './catalog.mjs';

export const repositoryRoot = fileURLToPath(new URL('../../', import.meta.url));
const uiRoot = fileURLToPath(new URL('./', import.meta.url));
const staticFiles = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
]);
const headers = {
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
};
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');

export function createBenchmarkServer({
  repoRoot = repositoryRoot,
  catalogLoader = () => buildCatalog({ repoRoot }),
  researchLoader = async () => JSON.parse(await readFile(resolve(uiRoot, 'research.json'), 'utf8')),
} = {}) {
  const catalog = async () => {
    const value = await catalogLoader();
    return { ...value, versions: value.versions.map(version => ({ ...version,
      source: { ...version.source, localReportUrl: `/reports/${encodeURIComponent(version.id)}` },
    })) };
  };
  return createServer(async (request, response) => {
    const send = (status, body, type = 'application/json; charset=utf-8', extra = {}) => {
      const bytes = Buffer.isBuffer(body) || typeof body === 'string' ? body : JSON.stringify(body);
      response.writeHead(status, { ...headers, 'Content-Type': type, ...extra });
      response.end(request.method === 'HEAD' ? undefined : bytes);
    };
    try {
      const host = request.headers.host ?? '';
      if (!/^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host)) return send(403, { message: 'Loopback Host required.' });
      if (request.headers.origin && request.headers.origin !== `http://${host}`) return send(403, { message: 'Same-origin requests required.' });
      if (!['GET', 'HEAD'].includes(request.method)) return send(405, { message: 'This dashboard is read-only.' }, undefined, { Allow: 'GET, HEAD' });
      const url = new URL(request.url, 'http://127.0.0.1');
      if (url.search) return send(404, { message: 'Unknown route.' });
      const file = staticFiles.get(url.pathname);
      if (file) return send(200, await readFile(resolve(uiRoot, file[0])), file[1]);
      if (url.pathname === '/api/catalog') return send(200, await catalog());
      if (url.pathname === '/api/research') return send(200, await researchLoader());
      if (url.pathname === '/api/catalog/download') return send(200, await catalog(), undefined,
        { 'Content-Disposition': 'attachment; filename="parity-benchmark-catalog.json"' });
      if (url.pathname.startsWith('/reports/')) {
        const id = decodeURIComponent(url.pathname.slice('/reports/'.length));
        const version = (await catalog()).versions.find(item => item.id === id);
        if (!version?.source?.reportPath) return send(404, { message: 'Unknown report.' });
        const relative = version.source.reportPath;
        const absolute = resolve(repoRoot, relative);
        if (!relative.startsWith('ml-engine/evaluation/') || !relative.endsWith('.json')
            || !absolute.startsWith(resolve(repoRoot, 'ml-engine/evaluation') + sep)) {
          return send(404, { message: 'Unknown report.' });
        }
        const bytes = await readFile(absolute);
        if (!version.source.sha256 || sha256(bytes) !== version.source.sha256) {
          return send(409, { message: 'The report changed after catalog validation. Reload the dashboard.' });
        }
        return send(200, bytes);
      }
      return send(404, { message: 'Unknown route.' });
    } catch {
      return send(503, { message: 'Benchmark evidence could not be loaded or validated. Check the local artifact files and retry.' });
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.BENCHMARK_PORT ?? 3010);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('BENCHMARK_PORT must be a valid port.');
  const server = createBenchmarkServer();
  server.on('error', error => { process.stderr.write(`Benchmark dashboard could not start (${error.code ?? 'server error'}).\n`); process.exitCode = 1; });
  server.listen(port, '127.0.0.1', () => process.stdout.write(`Parity benchmark lab: http://127.0.0.1:${port}\n`));
}
