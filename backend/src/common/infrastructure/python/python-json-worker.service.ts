import { Injectable } from '@nestjs/common';
import { spawn } from 'node:child_process';
import { isAbsolute, resolve } from 'node:path';
import { InfrastructureException } from '../../exceptions/infrastructure.exception';
import { TranslationKey } from '../../i18n/translation-key';

interface WorkerTask {
  module: 'ml_engine.verify' | 'ml_engine.matching';
  input: unknown;
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
}

/** One bounded queue is shared by verification and discovery subprocesses. */
@Injectable()
export class PythonJsonWorkerService {
  private readonly queue: WorkerTask[] = [];
  private active = 0;

  execute(module: WorkerTask['module'], input: unknown): Promise<unknown> {
    const concurrency = Number(process.env.ML_WORKER_CONCURRENCY ?? 2);
    const queueLimit = Number(process.env.ML_WORKER_QUEUE_LIMIT ?? 64);
    if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 8
      || !Number.isInteger(queueLimit) || queueLimit < 1 || queueLimit > 1024) {
      return Promise.reject(new InfrastructureException('ML worker concurrency/queue settings are invalid.', TranslationKey.EngineUnavailable));
    }
    if (this.queue.length >= queueLimit) {
      return Promise.reject(new InfrastructureException('Analysis capacity is full; retry after queued work completes.', 'engine.queue_full'));
    }
    return new Promise((resolveResult, reject) => {
      this.queue.push({ module, input, resolve: resolveResult, reject });
      this.pump();
    });
  }

  private pump(): void {
    // Invalid runtime setting changes must not stall requests already accepted.
    const configured = Number(process.env.ML_WORKER_CONCURRENCY ?? 2);
    const concurrency = Number.isInteger(configured) && configured >= 1 && configured <= 8 ? configured : 1;
    while (this.active < concurrency && this.queue.length) {
      const task = this.queue.shift()!;
      this.active += 1;
      this.run(task.module, task.input).then(task.resolve, task.reject).finally(() => {
        this.active -= 1;
        this.pump();
      });
    }
  }

  private async run(module: WorkerTask['module'], input: unknown): Promise<unknown> {
    const enginePath = resolve(process.env.ML_ENGINE_PATH ?? '../ml-engine');
    const requestedPython = process.env.PYTHON_BIN ?? 'python3';
    const python = requestedPython.includes('/') && !isAbsolute(requestedPython) ? resolve(requestedPython) : requestedPython;
    const timeout = Number(process.env.ML_TIMEOUT_MS ?? 120_000);
    if (!Number.isFinite(timeout) || timeout < 1_000 || timeout > 600_000) {
      throw new InfrastructureException('ML_TIMEOUT_MS must be between 1000 and 600000.', TranslationKey.EngineUnavailable);
    }
    return new Promise((resolveResult, reject) => {
      const child = spawn(python, ['-m', module, '--stdin'], { cwd: enginePath, shell: false, stdio: ['pipe', 'pipe', 'pipe'] });
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
      // Drain diagnostic output without exposing sources or tracebacks over HTTP.
      child.stderr.resume();
      child.on('close', (code) => {
        if (settled) return;
        if (code !== 0) { fail('The analysis engine failed. Check the engine installation and input syntax.'); return; }
        try {
          const result: unknown = JSON.parse(Buffer.concat(stdout).toString('utf8'));
          if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Expected object');
          settled = true;
          clearTimeout(timer);
          resolveResult(result);
        } catch { fail('The analysis engine returned invalid JSON.', TranslationKey.InvalidEngineResult); }
      });
      child.stdin.end(JSON.stringify(input));
    });
  }
}
