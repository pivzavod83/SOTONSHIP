import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import * as vscode from 'vscode';
import type { WorkbenchController } from '../src/extension';
import type { ProofInputs, VerificationResult } from '../src/contracts';

const backendUrl = process.env.LIVE_VERIFIER_URL ?? 'http://127.0.0.1:3002';
let assertions = 0;
let scenarios = 0;

function equal(actual: unknown, expected: unknown, message?: string): void {
  assert.equal(actual, expected, message); assertions++;
}
function ok(value: unknown, message?: string): asserts value {
  assert.ok(value, message); assertions++;
}
async function rejects(action: Promise<unknown>, pattern: RegExp): Promise<void> {
  await assert.rejects(action, pattern); assertions++;
}
function passed(name: string): void { scenarios++; console.log(`  ✓ ${name}`); }
async function eventually(condition: () => boolean, label: string): Promise<void> {
  const deadline = Date.now() + 5000;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error(`Timed out waiting for ${label}.`);
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}
async function replace(document: vscode.TextDocument, content: string): Promise<void> {
  const edit = new vscode.WorkspaceEdit();
  edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length)), content);
  ok(await vscode.workspace.applyEdit(edit), 'The test must be able to edit its untitled document.');
}
function selectedDocument(controller: WorkbenchController, role: 'cobol' | 'java' | 'candidate'): vscode.TextDocument {
  const label = controller.getState().files[role];
  ok(label, `Demo ${role} selection is missing.`);
  const document = vscode.workspace.textDocuments.find(candidate => candidate.uri.toString() === label.path);
  ok(document, `Demo ${role} document is missing.`);
  equal(document.uri.scheme, 'untitled', 'Host tests must never modify repository source files.');
  return document;
}

/** Delays actual backend evidence to exercise editor races; it does not manufacture a proof. */
async function evidenceGate(evidence: VerificationResult): Promise<{
  url: string; holdNext(): { requested: Promise<void>; release(): void }; close(): Promise<void>;
}> {
  let hold: { reached(): void; released: Promise<void> } | undefined;
  const server = createServer(async (request, response) => {
    try {
      const chunks: Buffer[] = [];
      for await (const chunk of request) chunks.push(Buffer.from(chunk));
      const input = JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>;
      assert.equal(request.method, 'POST');
      assert.equal(request.url, '/api/verifications');
      assert.equal(input.cobolSource, evidence.cobolSource);
      assert.equal(input.javaSource, evidence.javaSource);
      assert.equal(input.moduleName, evidence.moduleName);
      assert.deepEqual(input.proofInputs, evidence.proofScope.proofInputs, 'The HTTP request must retain the exact initial mapping.');
      const pending = hold; hold = undefined;
      if (pending) { pending.reached(); await pending.released; }
      response.writeHead(201, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify(evidence));
    } catch (error) {
      response.writeHead(500, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ message: error instanceof Error ? error.message : 'Test gate failed.' }));
    }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  return {
    url: `http://127.0.0.1:${address.port}`,
    holdNext() {
      let reached!: () => void; let release!: () => void;
      const requested = new Promise<void>(resolve => { reached = resolve; });
      hold = { reached, released: new Promise<void>(resolve => { release = resolve; }) };
      return { requested, release };
    },
    async close() { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); },
  };
}

async function reached(requested: Promise<void>): Promise<void> {
  let timer: NodeJS.Timeout | undefined;
  try {
    await Promise.race([requested, new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error('The extension did not reach the controlled HTTP gate.')), 10000);
    })]);
  } finally { if (timer) clearTimeout(timer); }
}

/** Called by the real VS Code Extension Development Host, not by node --test. */
export async function run(): Promise<void> {
  console.log(`SOTONSHIP native Extension Host integration suite; live engine: ${backendUrl}`);
  const extension = vscode.extensions.getExtension<WorkbenchController>('sotonship.sotonship-financial-verifier');
  ok(extension, 'The development extension must be discovered by VS Code.');
  const controller = await extension.activate();
  ok(extension.isActive);
  const commands = await vscode.commands.getCommands(true);
  for (const command of ['sotonship.openWorkbench', 'sotonship.verifyFiles', 'sotonship.tryDemo', 'sotonship.showFixDiff', 'vscode.diff']) {
    ok(commands.includes(command), `${command} must be registered in the native host.`);
  }
  await vscode.commands.executeCommand('sotonship.openWorkbench');
  passed('native activation, commands and workbench panel');

  await vscode.commands.executeCommand('sotonship.tryDemo');
  const cobol = selectedDocument(controller, 'cobol');
  const java = selectedDocument(controller, 'java');
  const candidate = selectedDocument(controller, 'candidate');
  const original = java.getText(); const corrected = candidate.getText();
  const proofInputs = JSON.parse(controller.getState().proofInputsText) as ProofInputs;
  equal(controller.getState().result, undefined, 'Loading a demo must not start a proof.');
  equal(controller.getState().candidateResult, undefined);
  equal(controller.getState().canApply, false);
  ok(original.includes('new BigDecimal(principal * quote)'));
  ok(corrected.includes('principal.multiply(quote)'));
  const configure = (url = backendUrl) => controller.configure({
    cobol: cobol.uri, java: java.uri, candidate: candidate.uri, proofInputs, category: 'FX_CONVERSION', backendUrl: url,
  });
  await configure();
  passed('demo opens three unsaved sources and an explicit mapping without sending code');

  const baseline = await controller.verify(false);
  equal(baseline.formalProofStatus, 'SAT_COUNTEREXAMPLE_FOUND');
  ok(baseline.counterexamplesJson.length > 0);
  ok(baseline.counterexamplesJson.some(witness => witness.cobolOutput !== witness.javaOutput));
  equal(controller.getDiagnosticCount(), 1, 'The Java editor must expose the program-level discrepancy.');
  equal(controller.getState().resultStale, false);
  equal(controller.getState().busy, false);
  passed('real backend and Z3 return a financial discrepancy with an editor diagnostic');

  const verifiedCandidate = await controller.verify(true);
  equal(verifiedCandidate.formalProofStatus, 'UNSAT_PROVEN_SAFE');
  equal(controller.getState().canApply, true);
  equal(controller.getState().candidateStale, false);
  equal(java.getText(), original, 'Checking a candidate must not change the Java source.');
  await vscode.commands.executeCommand('sotonship.showFixDiff');
  await eventually(() => vscode.window.tabGroups.all.some(group => group.tabs.some(tab => tab.input instanceof vscode.TabInputTextDiff)), 'native diff tab');
  ok(vscode.window.tabGroups.all.some(group => group.tabs.some(tab => tab.input instanceof vscode.TabInputTextDiff)));
  passed('real bounded equivalence enables the exact candidate and opens the native diff');

  equal(await controller.applyCandidate(), true);
  equal(java.getText(), corrected);
  equal(java.isDirty, true, 'Applying a verified fix must leave the editor unsaved.');
  equal(controller.getState().applied, true);
  equal(controller.getState().canApply, false);
  equal(controller.getDiagnosticCount(), 0);
  await vscode.window.showTextDocument(java, { preview: false, viewColumn: vscode.ViewColumn.One });
  await vscode.commands.executeCommand('undo');
  await eventually(() => java.getText() === original, 'Undo to restore the original Java');
  equal(java.getText(), original);
  equal(controller.getState().resultStale, true, 'Undo is a source edit and must invalidate the stored result.');
  passed('apply obtains a fresh proof, edits only the unsaved Java editor and supports Undo');

  await configure();
  await controller.verify(false);
  equal(controller.getDiagnosticCount(), 1);
  await controller.verify(true);
  await replace(java, `${original}\n// Unsaved engineer change.\n`);
  equal(controller.getDiagnosticCount(), 0, 'Source changes must clear diagnostic evidence.');
  equal(controller.getState().resultStale, true);
  equal(controller.getState().candidateStale, true);
  equal(controller.getState().canApply, false);
  const changedJava = java.getText();
  await rejects(controller.applyCandidate(), /exact current proposed fix|changed/iu);
  equal(java.getText(), changedJava);
  await replace(java, original);
  await controller.verify(true);
  await replace(candidate, `${corrected}\n// Candidate changed after proof.\n`);
  equal(controller.getState().candidateStale, true);
  equal(controller.getState().canApply, false);
  await rejects(controller.applyCandidate(), /exact current proposed fix|changed/iu);
  equal(java.getText(), original);
  passed('editing either selected source invalidates evidence and blocks application');

  await replace(candidate, original);
  const badCandidate = await controller.verify(true);
  equal(badCandidate.formalProofStatus, 'SAT_COUNTEREXAMPLE_FOUND');
  equal(controller.getState().canApply, false);
  await rejects(controller.applyCandidate(), /exact current proposed fix/iu);
  equal(java.getText(), original);
  passed('a real SAT candidate cannot modify the Java editor');

  await replace(candidate, 'import java.math.BigDecimal;\npublic final class FxWireService {\n public BigDecimal calculate(BigDecimal principal, BigDecimal quote) {\n throw new UnsupportedOperationException();\n }\n}\n');
  const unsupported = await controller.verify(true);
  equal(unsupported.formalProofStatus, 'UNKNOWN_HALTED_LIMIT');
  equal(controller.getState().canApply, false);
  await rejects(controller.applyCandidate(), /exact current proposed fix/iu);
  equal(java.getText(), original);
  passed('unsupported semantics remain UNKNOWN and cannot authorize an edit');

  await replace(candidate, corrected);
  const gate = await evidenceGate(verifiedCandidate);
  try {
    await configure(gate.url);
    const overlapGate = gate.holdNext();
    const initialState = controller.getState();
    const firstVerification = controller.verify(true);
    equal(controller.getState().busy, true, 'Busy must cover source snapshot acquisition before its first await.');
    const alteredMapping = { ...proofInputs, amountMinCents: 0, amountMaxCents: 5000 };
    await rejects(controller.configure({ cobol: cobol.uri, java: java.uri, candidate: candidate.uri,
      proofInputs: alteredMapping, category: 'REMITTANCE_FEE', backendUrl }), /current verification/iu);
    await rejects(controller.verify(false), /already running/iu);
    await rejects(controller.applyCandidate(), /already running/iu);
    await rejects(controller.loadDemo(), /current verification/iu);
    equal(controller.getState().proofInputsText, initialState.proofInputsText, 'Rejected configuration must preserve the captured mapping.');
    equal(controller.getState().backendUrl, initialState.backendUrl);
    equal(controller.getState().category, initialState.category);
    equal(controller.getState().files.java?.path, java.uri.toString());
    await reached(overlapGate.requested);
    equal(controller.getState().busy, true, 'Busy must also cover the pending engine response.');
    overlapGate.release();
    await firstVerification;
    equal(controller.getState().busy, false);
    equal(controller.getState().candidateResult?.id, verifiedCandidate.id, 'Evidence must be committed when the operation resolves.');
    equal(controller.getState().candidateStale, false);
    equal(controller.getState().canApply, true);
    passed('busy starts before snapshot acquisition, blocks overlapping actions and preserves the initial mapping until result commit');

    await configure(gate.url);
    const duringProof = gate.holdNext();
    const proof = controller.verify(true);
    await reached(duringProof.requested);
    equal(controller.getState().busy, true);
    await replace(java, `${original}\n// Changed while proof was in flight.\n`);
    duringProof.release();
    await proof;
    equal(controller.getState().candidateStale, true);
    equal(controller.getState().canApply, false);
    await rejects(controller.applyCandidate(), /exact current proposed fix|changed/iu);
    passed('actual editor changes during an in-flight response make its evidence stale');

    await replace(java, original);
    await configure(gate.url);
    await controller.verify(true);
    equal(controller.getState().canApply, true);
    const duringApply = gate.holdNext();
    const application = controller.applyCandidate();
    // Attach immediately: the promise may reject before later assertions complete.
    const applicationFailure = rejects(application, /changed during re-verification/iu);
    await reached(duringApply.requested);
    const engineerChange = `${original}\n// Preserve this edit during the final proof.\n`;
    await replace(java, engineerChange);
    duringApply.release();
    await applicationFailure;
    equal(java.getText(), engineerChange, 'Fresh-proof races must preserve the engineer\'s exact current text.');
    equal(controller.getState().canApply, false);
    equal(controller.getState().busy, false);
    passed('an edit during final re-verification prevents replacement and preserves engineer changes');

    await replace(java, original);
    await configure(gate.url);
    await controller.verify(true);
    equal(controller.getState().canApply, true);
    const cancelledApply = gate.holdNext();
    const applying = controller.applyCandidate();
    const cancellation = rejects(applying, /cancelled/iu);
    await reached(cancelledApply.requested);
    controller.dispose();
    cancelledApply.release();
    await cancellation;
    equal(java.getText(), original, 'Disposing the workbench must cancel the outstanding proof before any editor edit.');
    equal(controller.getState().busy, false);
    passed('disposing a workbench cancels in-flight application and preserves the Java source');
  } finally { await gate.close(); }

  for (const document of [cobol, java, candidate]) equal(document.uri.scheme, 'untitled');
  console.log(`Native Extension Host: ${scenarios} scenarios, ${assertions} assertions passed. All edited documents were untitled; no repository source was written.`);
}
