import { parseVerificationResult, proofMatchesSources, validateVerificationRequest, type VerificationRequest, type VerificationResult } from './contracts';

const MAX_REQUEST_BYTES = 1_048_576;
const MAX_RESPONSE_BYTES = 16 * 1_048_576;

export function normalizeBackendUrl(input: string): string {
  let url: URL;
  try { url = new URL(input.trim()); } catch { throw new Error('Backend URL must be a complete local HTTP or HTTPS address.'); }
  const loopback = url.hostname === 'localhost' || url.hostname === '[::1]' || /^127(?:\.\d{1,3}){3}$/u.test(url.hostname);
  if (!['http:', 'https:'].includes(url.protocol) || !loopback) throw new Error('Use a loopback backend address such as http://127.0.0.1:3001.');
  if (url.username || url.password || url.search || url.hash || !['/', '/api', '/api/'].includes(url.pathname)) {
    throw new Error('Backend URL must contain only the local server address and optional /api path, without credentials, query or fragment.');
  }
  return url.origin;
}

function statusMessage(status: number): string {
  if (status === 400 || status === 422) return `The backend rejected the verification request (HTTP ${status}). Check the source limits and exact proof inputs.`;
  if (status === 413) return 'The verification request exceeds the backend payload limit (HTTP 413).';
  if (status === 404) return 'The verification endpoint was not found (HTTP 404). Check the backend URL and start the SOTONSHIP backend.';
  if (status === 401 || status === 403) return `The backend denied this request (HTTP ${status}). This extension expects the local API without authentication.`;
  if (status === 503) return 'The verification engine is unavailable (HTTP 503). Check the local backend and Python engine configuration.';
  return `The local backend could not complete verification (HTTP ${status}). Check its terminal output.`;
}

async function responseJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase();
  if (contentType !== 'application/json' && !contentType?.endsWith('+json')) {
    await response.body?.cancel();
    throw new Error('The local backend returned a non-JSON response. Check its URL.');
  }
  const declaredLength = response.headers.get('content-length');
  if (declaredLength && (!/^\d+$/u.test(declaredLength) || Number(declaredLength) > MAX_RESPONSE_BYTES)) {
    await response.body?.cancel();
    throw new Error('The verification response exceeds the 16 MiB evidence limit.');
  }
  if (!response.body) throw new Error('The local backend returned an empty verification response.');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      received += chunk.value.byteLength;
      if (received > MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw new Error('The verification response exceeds the 16 MiB evidence limit.');
      }
      chunks.push(chunk.value);
    }
  } finally { reader.releaseLock(); }
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); }
  catch { throw new Error('The local backend returned invalid JSON evidence.'); }
}

export class ApiClient {
  readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(baseUrl: string, timeoutMs = 120_000) {
    this.baseUrl = normalizeBackendUrl(baseUrl);
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 600_000) throw new Error('Request timeout must be between 1 and 600000 milliseconds.');
    this.timeoutMs = timeoutMs;
  }

  async verify(request: VerificationRequest, signal?: AbortSignal): Promise<VerificationResult> {
    if (signal?.aborted) throw new Error('Verification was cancelled.');
    const validated = validateVerificationRequest(request);
    const body = JSON.stringify(validated);
    if (Buffer.byteLength(body, 'utf8') > MAX_REQUEST_BYTES) throw new Error('The verification request exceeds the 1 MiB payload limit.');
    const controller = new AbortController();
    let timedOut = false;
    const cancel = () => controller.abort();
    signal?.addEventListener('abort', cancel, { once: true });
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, this.timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}/api/verifications`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body, signal: controller.signal, redirect: 'error',
      });
      if (!response.ok) {
        await response.body?.cancel();
        throw new Error(statusMessage(response.status));
      }
      const result = parseVerificationResult(await responseJson(response));
      if (result.cobolSource !== validated.cobolSource || result.javaSource !== validated.javaSource
        || result.moduleName !== validated.moduleName || result.category !== validated.category) {
        throw new Error('The backend evidence does not refer to the requested module and source code.');
      }
      if (result.formalProofStatus !== 'UNKNOWN_HALTED_LIMIT') {
        const proofInputs = result.proofScope.proofInputs as Record<string, unknown>;
        if (!Object.entries(validated.proofInputs).every(([key, value]) => proofInputs[key] === value)) {
          throw new Error('The backend proof does not use the exact requested mapping, bounds and reference-rate identity.');
        }
      }
      if (result.formalProofStatus === 'UNSAT_PROVEN_SAFE' && !proofMatchesSources(result, validated.cobolSource, validated.javaSource)) {
        throw new Error('The equivalence proof is not bound to the exact submitted source code.');
      }
      return result;
    } catch (error) {
      if (timedOut) throw new Error(`Verification timed out after ${Math.round(this.timeoutMs / 1000)} seconds. Check the local engine or retry with narrower bounds.`);
      if (signal?.aborted) throw new Error('Verification was cancelled.');
      if (error instanceof TypeError) throw new Error(`Could not reach the local verifier at ${this.baseUrl}. Start the backend and check its address. Redirects are not followed.`);
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
    }
  }
}
