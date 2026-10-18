import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import * as vscode from 'vscode';
import type { WorkbenchController } from '../src/extension';
import type { ProofInputs, VerificationResult } from '../src/contracts';
import type { MatchingRequest, MatchingResult } from '../src/matching-contracts';
import type { AiReviewRequest, AiReviewResult } from '../src/ai-review-contracts';

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

/** Protocol fixture for editor workflow only; this does not measure learned model quality. */
async function matchingGate(): Promise<{ url: string; requests: MatchingRequest[]; holdNext(): { requested: Promise<void>; release(): void }; close(): Promise<void> }> {
  const requests: MatchingRequest[] = [];
  let hold: { reached(): void; released: Promise<void> } | undefined;
  const hash = (value: string) => createHash('sha256').update(value).digest('hex');
  const server = createServer(async (req, res) => {
    const chunks: Buffer[] = []; for await (const chunk of req) chunks.push(Buffer.from(chunk));
    assert.equal(req.url, '/api/matches');
    const input = JSON.parse(Buffer.concat(chunks).toString('utf8')) as MatchingRequest; requests.push(input);
    const pending = hold; hold = undefined;
    if (pending) { pending.reached(); await pending.released; }
    const result: MatchingResult = { status: 'REVIEW_REQUIRED', reason: 'Protocol fixture: engineer review required.', matchingIsProof: false, granularity: 'PROGRAM',
      model: { id: 'native-host-protocol-fixture', sha256: 'b'.repeat(64), trainingDataset: 'COBOL-JavaTrans', evaluation: { purpose: 'Editor integration fixture, not a model quality measurement.' } },
      cobolSourceSha256: hash(input.cobolSource), candidates: input.candidates.map((item, index) => ({ candidateId: item.candidateId, moduleName: item.moduleName,
        javaSourceSha256: hash(item.javaSource), rank: index + 1, similarity: 0.8 - index * 0.1 })), thresholds: { minimumSimilarity: 0.85, minimumMargin: 0.1 } };
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(result));
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening'); const address = server.address(); assert.ok(address && typeof address !== 'string');
  return { url: `http://127.0.0.1:${address.port}`, requests,
    holdNext() { let reached!: () => void; let release!: () => void; const requested = new Promise<void>(resolve => { reached = resolve; });
      hold = { reached, released: new Promise<void>(resolve => { release = resolve; }) }; return { requested, release }; },
    async close() { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); } };
}

/** Local protocol fixture only; it exercises the editor and HTTP adapter, not model quality. */
async function aiReviewGate(): Promise<{ url: string; requests: AiReviewRequest[]; holdNext(): { requested: Promise<void>; release(): void }; close(): Promise<void> }> {
  const requests: AiReviewRequest[] = []; let hold: { reached(): void; released: Promise<void> } | undefined;
  const hash = (value: string) => createHash('sha256').update(value).digest('hex');
  const server = createServer(async (req, res) => {
    const chunks: Buffer[] = []; for await (const chunk of req) chunks.push(Buffer.from(chunk));
    assert.equal(req.url, '/api/ai-reviews'); assert.equal(req.headers.authorization, undefined);
    const input = JSON.parse(Buffer.concat(chunks).toString('utf8')) as AiReviewRequest; requests.push(input);
    const pending = hold; hold = undefined; if (pending) { pending.reached(); await pending.released; }
    const result: AiReviewResult = { status: 'ANALYZED', summary: 'Native protocol fixture: inspect the selected pair.',
      findings: [{ findingId: 'F1', title: 'Protocol fixture hypothesis', category: 'ARITHMETIC', severity: 'MEDIUM', explanation: 'Editor integration fixture, not a measured model result.',
        cobolLines: { start: 1, end: 1 }, javaLines: { start: 1, end: 1 }, cobolExcerpt: input.cobolSource.split('\n')[0], javaExcerpt: input.javaSource.split('\n')[0],
        suggestedFix: '', candidateInputs: [{ inputsJson: '{"amount":"45.00"}', rationale: 'An unexecuted fixture input.', status: 'NOT_EXECUTED' }], evidenceStatus: 'AI_HYPOTHESIS' }],
      limitations: ['Mock backend protocol; not AI quality evidence.'], sourceHashes: { cobol: hash(input.cobolSource), java: hash(input.javaSource) },
      provider: { protocol: 'OPENAI_COMPATIBLE_CHAT', model: 'native-host-protocol-fixture' }, aiIsProof: false, promptVersion: 'paired-defect-review-v1', counterexamplesExecuted: false };
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(result));
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening'); const address = server.address(); assert.ok(address && typeof address !== 'string');
  return { url: `http://127.0.0.1:${address.port}`, requests,
    holdNext() { let reached!: () => void; let release!: () => void; const requested = new Promise<void>(resolve => { reached = resolve; });
      hold = { reached, released: new Promise<void>(resolve => { release = resolve; }) }; return { requested, release }; },
    async close() { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); } };
}

/** Called by the real VS Code Extension Development Host, not by node --test. */
export async function run(): Promise<void> {
  console.log(`SOTONSHIP native Extension Host integration suite; live engine: ${backendUrl}`);
  const extension = vscode.extensions.getExtension<WorkbenchController>('sotonship.sotonship-financial-verifier');
  ok(extension, 'The development extension must be discovered by VS Code.');
  const controller = await extension.activate();
  ok(extension.isActive);
  const commands = await vscode.commands.getCommands(true);
  for (const command of ['sotonship.openWorkbench', 'sotonship.verifyFiles', 'sotonship.matchPrograms', 'sotonship.analyzePairWithAi', 'sotonship.tryDemo', 'sotonship.showFixDiff', 'vscode.diff']) {
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

  const aiGate = await aiReviewGate();
  try {
    await controller.configureAiReview({ cobol: cobol.uri, java: java.uri, backendUrl: aiGate.url, sourceFormat: 'FREE', analysisContext: 'Native fixture context.' });
    equal(aiGate.requests.length, 0, 'AI configuration must not upload selected source.');
    const aiResult = await controller.analyzePairWithAi();
    equal(aiGate.requests.length, 1); equal(aiGate.requests[0].javaSource, original); equal(aiGate.requests[0].cobolSource, cobol.getText());
    equal(aiGate.requests[0].analysisContext, 'Native fixture context.'); equal(aiResult.aiIsProof, false);
    equal(controller.getState().aiReviewStale, false); equal(controller.getState().canApply, false);
    equal(controller.getDiagnosticCount(), 0, 'AI hypotheses must not create formal verification diagnostics.');
    equal(java.getText(), original, 'AI review must not edit the source.');
    passed('explicit AI action sends exact editor text and keeps hypotheses separate from proof and edits');

    const gate = aiGate.holdNext(); const pendingReview = controller.analyzePairWithAi(); await reached(gate.requested);
    await replace(java, `${original}\n// Edited while AI review was pending.\n`);
    await replace(java, original);
    gate.release(); await pendingReview;
    equal(controller.getState().aiReviewStale, true, 'Editing and restoring the same source must invalidate the in-flight result by version/generation.');
    equal(controller.getState().canApply, false); equal(java.getText(), original);
    passed('native editor edit and restoration invalidate delayed AI findings even when source hashes match again');

    await controller.analyzePairWithAi(); equal(controller.getState().aiReviewStale, false);
    await controller.configureAiReview({ cobol: cobol.uri, java: java.uri, sourceFormat: 'FIXED', analysisContext: 'Changed context.' });
    equal(controller.getState().aiReviewStale, true); equal(aiGate.requests.length, 3, 'Changing AI context or format must not send a request.');
    passed('changing AI review context and format invalidates findings without automatic uploads');
  } finally { await aiGate.close(); }
  if (process.env.AI_REVIEW_HOST_ONLY === '1') {
    console.log(`Native Extension Host AI protocol: ${scenarios} scenarios, ${assertions} assertions passed. Mock provider; no model quality measured. All edited documents were untitled.`);
    return;
  }
  await configure();

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
  const rankingGate = await matchingGate();
  try {
    const priorMapping = controller.getState().proofInputsText;
    await controller.configureMatching({ cobol: cobol.uri, candidates: [java.uri, candidate.uri], backendUrl: rankingGate.url, sourceFormat: 'FREE' });
    equal(rankingGate.requests.length, 0, 'Selecting matching files must not upload code.');
    const ranking = await controller.matchPrograms();
    equal(ranking.matchingIsProof, false); equal(ranking.status, 'REVIEW_REQUIRED');
    equal(rankingGate.requests.length, 1);
    equal(rankingGate.requests[0].cobolSource, cobol.getText());
    equal(rankingGate.requests[0].candidates[0].javaSource, original);
    equal(rankingGate.requests[0].candidates[1].javaSource, corrected);
    equal(rankingGate.requests[0].topK, 2, 'Request every selected candidate instead of relying on backend topK defaults.');
    equal(controller.getState().files.java?.path, java.uri.toString(), 'Ranking must not silently choose a Java implementation.');
    equal(controller.getState().proofInputsText, priorMapping, 'Matching must not infer or modify financial proof inputs.');
    equal(controller.getState().matchingStale, false);
    await controller.confirmMatch('candidate-2');
    equal(controller.getState().files.java?.path, candidate.uri.toString());
    equal(controller.getState().confirmedMatchId, 'candidate-2');
    equal(controller.getState().proofInputsText, priorMapping);
    equal(controller.getState().canApply, false);
    equal(controller.getState().resultStale, true);
    equal(rankingGate.requests.length, 1, 'Engineer confirmation only selects a URI; it does not establish a proof or silently send more sources.');
    equal(java.getText(), original); equal(candidate.getText(), corrected);
    passed('matching sends unsaved source snapshots and requires explicit candidate confirmation without changing proof inputs or source text');

    await replace(candidate, `${corrected}\n// Change after learned ranking.\n`);
    equal(controller.getState().matchingStale, true);
    equal(controller.getState().confirmedMatchId, undefined);
    await rejects(controller.confirmMatch('candidate-1'), /current sources|changed/iu);
    equal(controller.getState().files.java?.path, candidate.uri.toString(), 'Stale confirmation must preserve the current Java selection.');
    await replace(candidate, corrected);
    passed('editing a ranked candidate invalidates matching evidence and prevents stale selection');

    await controller.configureMatching({ cobol: cobol.uri, candidates: [java.uri, candidate.uri], backendUrl: rankingGate.url, sourceFormat: 'FREE' });
    const delayedRanking = rankingGate.holdNext(); const inFlight = controller.matchPrograms();
    equal(controller.getState().busy, true);
    await rejects(controller.matchPrograms(), /already running/iu);
    await rejects(controller.configureMatching({ cobol: cobol.uri, candidates: [java.uri] }), /current verification/iu);
    await rejects(controller.confirmMatch('candidate-1'), /already running/iu);
    await reached(delayedRanking.requested);
    await replace(java, `${original}\n// Unsaved during matching.\n`);
    delayedRanking.release(); await inFlight;
    equal(controller.getState().matchingStale, true);
    equal(controller.getState().busy, false);
    await rejects(controller.confirmMatch('candidate-1'), /current sources|changed/iu);
    await replace(java, original);
    passed('matching is busy before snapshots, blocks overlapping operations and rejects evidence changed in flight');
  } finally { await rankingGate.close(); }

  if (process.env.LIVE_MATCHING_URL) {
    const bytes = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(extension.extensionUri, '..', 'ml-engine', 'data', 'seed-verifications.json'));
    const fixtures = (JSON.parse(Buffer.from(bytes).toString('utf8')) as { verifications: VerificationResult[] }).verifications;
    const extra: vscode.TextDocument[] = [];
    for (const category of ['INTEREST_CALC', 'REMITTANCE_FEE']) {
      const fixture = fixtures.find(item => item.category === category); ok(fixture);
      extra.push(await vscode.workspace.openTextDocument({ language: 'java', content: fixture.javaSource }));
    }
    await configure(process.env.LIVE_MATCHING_URL);
    await controller.configureMatching({ cobol: cobol.uri, candidates: [java.uri, ...extra.map(document => document.uri)],
      backendUrl: process.env.LIVE_MATCHING_URL, sourceFormat: 'FREE' });
    const priorMapping = controller.getState().proofInputsText;
    const learnedRanking = await controller.matchPrograms();
    equal(learnedRanking.matchingIsProof, false); equal(learnedRanking.granularity, 'PROGRAM');
    equal(learnedRanking.candidates.length, 3);
    ok(learnedRanking.model.id.length > 0); equal(learnedRanking.model.sha256.length, 64);
    ok(learnedRanking.model.trainingDataset.length > 0);
    equal(controller.getState().matchingStale, false);
    equal(learnedRanking.cobolSourceSha256, createHash('sha256').update(cobol.getText()).digest('hex'));
    // The model's financial-domain accuracy is not asserted: the engineer chooses the known FX program even if another ranks higher.
    const fx = learnedRanking.candidates.find(item => item.candidateId === 'candidate-1'); ok(fx);
    equal(fx.javaSourceSha256, createHash('sha256').update(original).digest('hex'));
    await controller.confirmMatch(fx.candidateId);
    equal(controller.getState().files.java?.path, java.uri.toString());
    equal(controller.getState().proofInputsText, priorMapping);
    const afterMatching = await controller.verify(false);
    equal(afterMatching.formalProofStatus, 'SAT_COUNTEREXAMPLE_FOUND');
    equal(controller.getState().canApply, false);
    for (const document of extra) equal(document.uri.scheme, 'untitled');
    passed('real learned ranking is source-bound; engineer chooses known FX counterpart and independent Z3 still finds its discrepancy');
  } else console.log('  - Real learned ranking integration skipped; set LIVE_MATCHING_URL to exercise the trained matching backend.');

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
