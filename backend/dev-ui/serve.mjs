/** Loopback-only development UI. The proxy never loads or returns provider credentials. */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const root = fileURLToPath(new URL('../../', import.meta.url));
const uiRoot = fileURLToPath(new URL('./', import.meta.url));
const hash = value => createHash('sha256').update(value).digest('hex');
const jsonFile = async path => JSON.parse(await readFile(resolve(root, path), 'utf8'));
const datasetPath = 'ml-engine/evaluation/synthetic-pilot/pilot-10-r3/dataset.json';
const frozenDatasetHash = '7d6f612855da2e75ee5f552ea0ebc9e0fd95e5f3399a28e6d982f10c194c9dcb';
const replayPath = 'ml-engine/evaluation/synthetic-pilot/batch-03/runtime-audit-2026-10-18/report.json';
const replayHash = '4e977d47bec37725fbf73e922b6616951be24df414d0d690caad6431507e81fa';
const joinSource = lines => lines.join('\n');
const evaluationPath = 'ml-engine/evaluation/synthetic-pilot/defect-model-v1/final-test-evaluation.json';
const evaluationSha256 = '6e4f49d42b612f38abcc7b720344a8070468f4ac770809169cde14b818bd0696';
/** Public aggregate metrics only; no held-out code, labels or individual predictions. */
export async function loadEvaluation() {
  const bytes = await readFile(resolve(root, evaluationPath));
  if (hash(bytes) !== evaluationSha256) throw new Error('Final evaluation report hash changed.');
  const report = JSON.parse(bytes);
  if (report.status !== 'COMPLETED' || report.modelFrozenBeforeAssessment !== true || report.modelChangedAfterAssessment !== false || report.datasetSha256 !== frozenDatasetHash) throw new Error('Final evaluation is not bound to a frozen model.');
  return Object.fromEntries(['status', 'modelSha256', 'datasetSha256', 'pairs', 'correct', 'accuracy', 'precision', 'recall', 'f1', 'confusion', 'testFamilies', 'baseline', 'localization', 'limitations', 'completedUtc'].map(key => [key, report[key]]).concat([['reportSha256', evaluationSha256]]));
}
export async function loadExamples() {
  const [datasetBytes, replayBytes] = await Promise.all([readFile(resolve(root, datasetPath)), readFile(resolve(root, replayPath))]);
  if (hash(datasetBytes) !== frozenDatasetHash || hash(replayBytes) !== replayHash) throw new Error('Frozen example or runtime evidence hash changed.');
  const dataset = JSON.parse(datasetBytes), replay = JSON.parse(replayBytes);
  const family = dataset.families.find(item => item.familyId === 'F006');
  const bad = family.variants.find(item => item.variantId === 'F006-V4');
  const good = family.variants.find(item => item.variantId === 'F006-V2');
  const cobolSource = joinSource(family.cobolLines), javaSource = joinSource(bad.javaLines), patchedJavaSource = joinSource(good.javaLines);
  const recorded = family.executionEvidence.sourceHashes;
  if (hash(cobolSource) !== recorded.cobol || hash(javaSource) !== recorded.java[bad.variantId] || hash(patchedJavaSource) !== recorded.java[good.variantId]) throw new Error('Example source hash does not match recorded execution.');
  const witness = replay.cases.find(item => item.familyId === 'F006' && item.testId === 'F006-T5');
  const badRun = witness.variants.find(item => item.variantId === bad.variantId), goodRun = witness.variants.find(item => item.variantId === good.variantId);
  if (witness.referenceRun.exitCode !== 0 || badRun.run.exitCode !== 0 || goodRun.run.exitCode !== 0 || !badRun.observedMismatch || goodRun.observedMismatch) throw new Error('Recorded example witness is invalid.');
  const local = {
    exampleId: 'signed-balance', label: 'Signed balance · training example', moduleName: 'SIGNED-BALANCE', category: 'NUMERIC_STORAGE_AND_SIGN',
    cobolSource, javaSource, patchedJavaSource, cobolSourceFormat: 'FREE', proofInputs: null,
    description: 'Synthetic training-family example. The local model must make its own prediction; the recorded replay below is separate evidence.',
    correctionDescription: 'Preserve the signed final balance: remove only the final .abs(), while retaining unsigned intermediate storage.',
  };
  const evidence = {
    status: 'CONFIRMED_REPLAY', sourceHashes: { cobol: hash(cobolSource), java: hash(javaSource), patchedJava: hash(patchedJavaSource) },
    finding: { title: 'Final absolute value changes a signed COBOL balance', cobolLines: { start: 23, end: 23 }, javaLines: { start: 10, end: 10 },
      explanation: 'The unsigned MID-BAL stores |500 + (-800)| = 300. COBOL END-BAL is signed and stores 300 - 400 = -100. The translated Java applies another .abs() and prints 100. These exact programs were compiled and executed offline.',
      suggestedFix: local.correctionDescription },
    witness: { testId: witness.testId, inputs: { 'OPENING BALANCE': '500', ADJUSTMENT: '-800', FEE: '400' }, outputs: { cobol: witness.observedReferenceValue, java: badRun.observedValue, patchedJava: goodRun.observedValue }, status: 'EXECUTED' },
    toolVersions: replay.toolVersions, checkedAtUtc: replay.checkedAtUtc, reportSha256: replayHash, reproduction: 'ml-engine/evaluation/synthetic-pilot/batch-03/replay.py',
    note: 'This is an actual execution discrepancy in an AI-generated training example, not an unseen model evaluation or a production-bank defect.',
    limitations: ['Recorded finite-input replay only; not a whole-program equivalence proof.', 'The model was trained on this family. Use the frozen test metrics to assess held-out performance.', 'No code entered in the editor is executed by this UI. Editing either source invalidates this recorded evidence.'],
  };
  const [fx, fxEvidence] = await Promise.all([jsonFile('vscode-extension/examples/penny-drift.json'), jsonFile('backend/dev-ui/data/penny-drift-evidence.json')]);
  fx.exampleId = 'fx-rounding'; fx.label = 'FX rounding · scoped Z3 example'; fx.cobolSourceFormat = 'FREE';
  fx.description = 'Recorded decimal-rounding fixture with a supported scoped Z3 mapping.';
  fx.correctionDescription = 'Use decimal inputs and preserve the COBOL result field storage behavior.';
  fxEvidence.note = 'Exact decimal product 53.235; binary-double multiplication changes the final rounded result by one cent.';
  return { defaultExampleId: local.exampleId, examples: [{ example: local, evidence }, { example: fx, evidence: fxEvidence }] };
}

const proxyRoutes = new Map([
  ['/api/defect-reviews', ['POST']], ['/api/defect-reviews/status', ['GET']],
  ['/api/ai-reviews', ['POST']], ['/api/verifications', ['POST']],
]);
const staticFiles = new Map([['/', ['index.html', 'text/html; charset=utf-8']], ['/app.js', ['app.js', 'text/javascript; charset=utf-8']], ['/styles.css', ['styles.css', 'text/css; charset=utf-8']]]);
export function createWorkbenchServer({ backendOrigin = process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:3003', examplesLoader = loadExamples } = {}) {
  const upstream = new URL(backendOrigin);
  if (upstream.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(upstream.hostname) || upstream.username || upstream.password || upstream.pathname !== '/' || upstream.search || upstream.hash) throw new Error('BACKEND_ORIGIN must be an HTTP loopback origin.');
  return createServer(async (request, response) => {
    const send = (status, body, type = 'application/json; charset=utf-8') => {
      response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'" });
      response.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
    };
    try {
      const url = new URL(request.url, 'http://127.0.0.1');
      const host = request.headers.host ?? '';
      if (!/^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host)) return send(403, { message: 'Loopback Host required.' });
      if (request.headers.origin && ![`http://${host}`].includes(request.headers.origin)) return send(403, { message: 'Same-origin requests required.' });
      if (url.search) return send(404, { message: 'Unknown route.' });
      if (url.pathname === '/evaluation' && request.method === 'GET') return send(200, await loadEvaluation());
      if (url.pathname === '/examples' && request.method === 'GET') return send(200, await examplesLoader());
      if (url.pathname === '/demo' && request.method === 'GET') { const examples = await examplesLoader(); return send(200, examples.examples[1]); }
      const staticFile = staticFiles.get(url.pathname);
      if (staticFile && request.method === 'GET') return send(200, await readFile(resolve(uiRoot, staticFile[0])), staticFile[1]);
      const methods = proxyRoutes.get(url.pathname);
      if (!methods || !methods.includes(request.method)) return send(404, { message: 'Unknown route.' });
      let payload;
      if (request.method === 'POST') {
        if (!(request.headers['content-type'] ?? '').startsWith('application/json')) return send(415, { message: 'JSON body required.' });
        const chunks = []; let length = 0;
        for await (const chunk of request) { length += chunk.length; if (length > 600000) return send(413, { message: 'Source pair exceeds the local request limit.' }); chunks.push(chunk); }
        payload = Buffer.concat(chunks).toString('utf8'); JSON.parse(payload);
      }
      const result = await fetch(new URL(url.pathname, upstream), { method: request.method, headers: payload ? { 'Content-Type': 'application/json' } : {}, body: payload, signal: AbortSignal.timeout(110000) });
      const data = await result.text();
      // Return only API JSON; do not relay upstream headers, cookies or credentials.
      try { JSON.parse(data); } catch { return send(502, { message: 'The local backend returned an unreadable response.' }); }
      return send(result.status, data);
    } catch (error) { return send(502, { message: error instanceof SyntaxError ? 'Invalid JSON request.' : 'Local backend unavailable. Start the backend and try again.' }); }
  });
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.UI_PORT ?? 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('UI_PORT must be a valid port.');
  createWorkbenchServer().listen(port, '127.0.0.1', () => process.stdout.write(`Omul local workbench: http://127.0.0.1:${port}\n`));
}
