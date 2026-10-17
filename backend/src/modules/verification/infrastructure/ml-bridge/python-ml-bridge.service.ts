import { Injectable } from '@nestjs/common';
import { spawn } from 'node:child_process';
import { resolve, isAbsolute } from 'node:path';
import { IMlBridge, MlVerificationInput } from '../../application/ports/ml-bridge';
import { VerificationAnalysis } from '../../domain/entities/verification-run';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';
import { TranslationKey } from '../../../../common/i18n/translation-key';

@Injectable()
export class PythonMlBridgeService implements IMlBridge {
  async verify(input: MlVerificationInput): Promise<VerificationAnalysis> {
    const enginePath = resolve(process.env.ML_ENGINE_PATH ?? '../ml-engine');
    const requestedPython = process.env.PYTHON_BIN ?? 'python3';
    // Resolve relative executable paths BEFORE changing the subprocess cwd.
    const python = requestedPython.includes('/') && !isAbsolute(requestedPython) ? resolve(requestedPython) : requestedPython;
    const timeout = Number(process.env.ML_TIMEOUT_MS ?? 120_000);
    if (!Number.isFinite(timeout) || timeout < 1_000 || timeout > 600_000) {
      throw new InfrastructureException('ML_TIMEOUT_MS must be between 1000 and 600000.', TranslationKey.EngineUnavailable);
    }
    return new Promise((resolveResult, reject) => {
      const child = spawn(python, ['-m', 'ml_engine.verify', '--stdin'], { cwd: enginePath, shell: false, stdio: ['pipe', 'pipe', 'pipe'] });
      const stdout: Buffer[] = [];
      let size = 0;
      let settled = false;
      const fail = (message: string, code: string = TranslationKey.EngineUnavailable): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        child.kill('SIGKILL');
        reject(new InfrastructureException(message, code));
      };
      const timer = setTimeout(() => fail('The analysis engine exceeded its time budget.', 'engine.timeout'), timeout);
      child.on('error', () => fail('The analysis engine could not start. Check PYTHON_BIN and ML_ENGINE_PATH.'));
      child.stdin.on('error', () => fail('The analysis engine closed its input unexpectedly.'));
      child.stdout.on('data', (chunk: Buffer) => {
        size += chunk.length;
        if (size > 8 * 1024 * 1024) fail('The analysis engine returned an oversized result.', TranslationKey.InvalidEngineResult);
        else stdout.push(chunk);
      });
      // Always drain stderr; do not expose source, credentials or tracebacks over HTTP.
      child.stderr.resume();
      child.on('close', (code) => {
        if (settled) return;
        if (code !== 0) { fail('The analysis engine failed. Check the engine installation and input syntax.'); return; }
        try {
          const result: unknown = JSON.parse(Buffer.concat(stdout).toString('utf8'));
          if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Expected object');
          // Handlers construct a validated aggregate before any result reaches the database.
          settled = true; clearTimeout(timer); resolveResult(result as VerificationAnalysis);
        } catch { fail('The analysis engine returned invalid JSON.', TranslationKey.InvalidEngineResult); }
      });
      child.stdin.end(JSON.stringify(input));
    });
  }
}
