import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { spawn } from 'node:child_process';
import { PythonJsonWorkerService } from '../src/common/infrastructure/python/python-json-worker.service';

jest.mock('node:child_process', () => ({ spawn: jest.fn() }));
const spawnMock = jest.mocked(spawn);

function processStub(): ReturnType<typeof spawn> {
  const child = Object.assign(new EventEmitter(), { stdin: Object.assign(new EventEmitter(), { end: jest.fn() }),
    stdout: new PassThrough(), stderr: new PassThrough(), kill: jest.fn() });
  return child as unknown as ReturnType<typeof spawn>;
}
function finish(child: ReturnType<typeof spawn>, output: string, exit = 0): void {
  child.stdout!.emit('data', Buffer.from(output));
  child.emit('close', exit, null);
}
const tick = (): Promise<void> => new Promise((resolve) => setImmediate(resolve));

describe('Shared Python subprocess capacity and protocol', () => {
  const settings = ['ML_WORKER_CONCURRENCY', 'ML_WORKER_QUEUE_LIMIT', 'ML_TIMEOUT_MS', 'ML_ENGINE_PATH', 'PYTHON_BIN'] as const;
  const original = Object.fromEntries(settings.map((key) => [key, process.env[key]]));

  beforeEach(() => {
    spawnMock.mockReset();
    settings.forEach((key) => { delete process.env[key]; });
    process.env.ML_WORKER_CONCURRENCY = '1';
    process.env.ML_WORKER_QUEUE_LIMIT = '1';
  });
  afterEach(() => {
    jest.useRealTimers();
    settings.forEach((key) => { if (original[key] === undefined) delete process.env[key]; else process.env[key] = original[key]; });
  });

  it('shares the concurrency limit across verification and matching, bounds queued work, and drains after completion', async () => {
    const first = processStub(); const second = processStub();
    spawnMock.mockReturnValueOnce(first).mockReturnValueOnce(second);
    const worker = new PythonJsonWorkerService();
    const verify = worker.execute('ml_engine.verify', { task: 'verify' });
    const match = worker.execute('ml_engine.matching', { task: 'match' });
    await expect(worker.execute('ml_engine.matching', {})).rejects.toMatchObject({ code: 'engine.queue_full' });
    expect(spawnMock).toHaveBeenCalledTimes(1);
    finish(first, '{"ok":true}');
    await expect(verify).resolves.toEqual({ ok: true });
    await tick();
    expect(spawnMock.mock.calls[1][1]).toEqual(['-m', 'ml_engine.matching', '--stdin']);
    expect(spawnMock.mock.calls[1][2]).toMatchObject({ shell: false });
    finish(second, '{"ok":2}');
    await expect(match).resolves.toEqual({ ok: 2 });
  });

  it('kills timed-out workers and admits the next task without exposing stderr', async () => {
    jest.useFakeTimers();
    process.env.ML_TIMEOUT_MS = '1000';
    const child = processStub(); spawnMock.mockReturnValue(child);
    const result = new PythonJsonWorkerService().execute('ml_engine.matching', {});
    const rejection = expect(result).rejects.toMatchObject({ code: 'engine.timeout' });
    child.stderr!.emit('data', Buffer.from('sensitive source traceback'));
    jest.advanceTimersByTime(1000);
    await rejection;
    expect(child.kill).toHaveBeenCalledWith('SIGKILL');
  });

  it('runs AI review through the same bounded stdin worker without a shell', async () => {
    const child = processStub(); spawnMock.mockReturnValue(child);
    const input = { cobolSource: 'COBOL', javaSource: 'Java' };
    const result = new PythonJsonWorkerService().execute('ml_engine.ai_review', input);
    expect(spawnMock.mock.calls[0][1]).toEqual(['-m', 'ml_engine.ai_review', '--stdin']);
    expect(spawnMock.mock.calls[0][2]).toMatchObject({ shell: false });
    expect(child.stdin!.end).toHaveBeenCalledWith(JSON.stringify(input));
    finish(child, '{"status":"NOT_CONFIGURED"}');
    await expect(result).resolves.toEqual({ status: 'NOT_CONFIGURED' });
  });

  it.each(['[]', 'not json', 'null'])('rejects non-object or invalid JSON: %s', async (payload) => {
    const child = processStub(); spawnMock.mockReturnValue(child);
    const result = new PythonJsonWorkerService().execute('ml_engine.matching', {});
    finish(child, payload);
    await expect(result).rejects.toMatchObject({ code: 'engine.invalid_result' });
  });

  it('rejects excessive engine output and kills the worker', async () => {
    const child = processStub(); spawnMock.mockReturnValue(child);
    const result = new PythonJsonWorkerService().execute('ml_engine.matching', {});
    child.stdout!.emit('data', Buffer.alloc(8 * 1024 * 1024 + 1));
    await expect(result).rejects.toMatchObject({ code: 'engine.invalid_result' });
    expect(child.kill).toHaveBeenCalledWith('SIGKILL');
  });

  it('rejects invalid capacity settings without spawning a process', async () => {
    process.env.ML_WORKER_CONCURRENCY = '0';
    await expect(new PythonJsonWorkerService().execute('ml_engine.matching', {})).rejects.toMatchObject({ code: 'engine.unavailable' });
    expect(spawnMock).not.toHaveBeenCalled();
  });
});
