import * as vscode from 'vscode';
import { basename } from 'node:path';
import { ApiClient, normalizeBackendUrl } from './api-client';
import { isScopedEquivalent, proofMatchesSources, validateProofInputs, validateSource } from './contracts';
import type { ProofInputs, VerificationCategory, VerificationRequest, VerificationResult } from './contracts';
import type { MatchingRequest, MatchingResult, MatchingSourceFormat } from './matching-contracts';
import { aiSourceHash, sameAiReviewBinding, validateAiReviewRequest, type AiReviewBinding, type AiReviewResult, type AiReviewSourceFormat } from './ai-review-contracts';
import type { FileLabel, PanelState, WorkbenchMessage } from './panel-state';
import { getWebviewHtml } from './webview';

type Role = 'cobol' | 'java' | 'candidate';
interface DocumentSnapshot { uri: vscode.Uri; text: string; version: number; }
interface Snapshot {
  cobol: DocumentSnapshot; java: DocumentSnapshot; candidate?: DocumentSnapshot;
  proofInputsText: string; proofInputs: ProofInputs; category: VerificationCategory; backendUrl: string;
}
type OpenedDocuments = Partial<Record<Role, vscode.TextDocument>>;
interface MatchingSnapshot {
  cobol: DocumentSnapshot; candidates: { candidateId: string; document: DocumentSnapshot }[];
  backendUrl: string; sourceFormat: MatchingSourceFormat;
}
interface AiReviewSnapshot { cobol: DocumentSnapshot; java: DocumentSnapshot; binding: AiReviewBinding; }
const categories: VerificationCategory[] = ['FX_CONVERSION', 'INTEREST_CALC', 'REMITTANCE_FEE', 'EXTERNAL_LIMIT_CASE'];

/** Desktop adapter only: proof decisions remain in the independent backend. */
export class WorkbenchController implements vscode.Disposable {
  private panel?: vscode.WebviewPanel;
  private readonly subscriptions: vscode.Disposable[] = [];
  private readonly diagnostics = vscode.languages.createDiagnosticCollection('sotonship');
  private readonly output = vscode.window.createOutputChannel('SOTONSHIP Verifier');
  private files: Partial<Record<Role, vscode.Uri>> = {};
  private candidateSnapshot?: Snapshot;
  private matchingFiles: vscode.Uri[] = [];
  private matchingSnapshot?: MatchingSnapshot;
  private aiReviewGeneration = 0;
  private lastAiReviewQuestion?: { backendUrl: string; moduleName: string; cobolSourceFormat: AiReviewSourceFormat; analysisContext: string };
  private applying = false;
  private abort?: AbortController;
  private state: PanelState;

  constructor(private readonly context: vscode.ExtensionContext) {
    const configuredUrl = vscode.workspace.getConfiguration('sotonship').get<string>('backendUrl', 'http://127.0.0.1:3001');
    let backendUrl = configuredUrl;
    try { backendUrl = normalizeBackendUrl(configuredUrl); } catch { /* Keep the invalid setting editable in the workbench. */ }
    this.state = { backendUrl,
      busy: false, message: 'Choose a source pair or try the penny drift demo. Verification runs only when requested.',
      category: 'FX_CONVERSION', files: {}, proofInputsText: '', resultStale: false, candidateStale: false, canApply: false, applied: false,
      matchingFiles: [], matchingSourceFormat: 'AUTO', matchingStale: false,
      aiReviewStale: false, aiReviewSourceFormat: 'AUTO', aiReviewContext: '' };
    this.subscriptions.push(this.diagnostics, this.output,
      vscode.workspace.onDidChangeTextDocument(event => {
        if (!event.contentChanges.length) return;
        const matchingAffected = this.files.cobol?.toString() === event.document.uri.toString()
          || this.matchingFiles.some(uri => uri.toString() === event.document.uri.toString());
        if (matchingAffected) this.invalidateMatching();
        if (this.applying && event.document.uri.toString() === this.files.java?.toString()) { this.invalidateAiReview(); this.publish(); return; }
        const affected = Object.entries(this.files).filter(([, uri]) => uri?.toString() === event.document.uri.toString()).map(([role]) => role);
        if (!affected.length) { if (matchingAffected) this.publish(); return; }
        if (affected.some(role => role !== 'candidate')) this.invalidate(true);
        else this.invalidate(false);
        this.state.message = 'Selected source changed. Run verification again before relying on its result.';
        this.publish();
      }),
      vscode.workspace.onDidChangeConfiguration(event => {
        if (!event.affectsConfiguration('sotonship.backendUrl')) return;
        const configured = vscode.workspace.getConfiguration('sotonship').get<string>('backendUrl', 'http://127.0.0.1:3001');
        try { this.state.backendUrl = normalizeBackendUrl(configured); } catch { this.state.backendUrl = configured; }
        this.invalidate(true); this.invalidateMatching(); this.publish();
      }),
      vscode.workspace.onDidSaveTextDocument(document => {
        if ([...Object.values(this.files), ...this.matchingFiles].some(uri => uri?.toString() === document.uri.toString())) this.publish();
      }));
  }

  public getState(): PanelState { return structuredClone(this.state); }
  public getDiagnosticCount(): number { return this.diagnostics.get(this.files.java ?? vscode.Uri.parse('untitled:none'))?.length ?? 0; }

  public open(): void {
    if (this.panel) { this.panel.reveal(vscode.ViewColumn.Two); this.publish(); return; }
    this.panel = vscode.window.createWebviewPanel('sotonship.verifier', 'SOTONSHIP · Verification', vscode.ViewColumn.Two, {
      enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'media')],
    });
    this.panel.webview.html = getWebviewHtml(this.panel.webview, this.context.extensionUri);
    this.panel.onDidDispose(() => { this.panel = undefined; }, undefined, this.subscriptions);
    this.panel.webview.onDidReceiveMessage((message: unknown) => { void this.receive(message); }, undefined, this.subscriptions);
  }

  private async receive(value: unknown): Promise<void> {
    if (!value || typeof value !== 'object' || !('type' in value) || typeof value.type !== 'string') return;
    const message = value as WorkbenchMessage;
    if (message.type === 'ready') { this.publish(); return; }
    if (this.state.busy) return;
    await this.safely(async () => {
      switch (message.type) {
        case 'chooseCobol': await this.chooseFile('cobol'); break;
        case 'chooseJava': await this.chooseFile('java'); break;
        case 'chooseCandidate': await this.chooseFile('candidate'); break;
        case 'chooseMatchingFiles': await this.chooseMatchingFiles(); break;
        case 'matchPrograms': await this.matchPrograms(); break;
        case 'analyzePairWithAi': await this.analyzePairWithAi(); break;
        case 'setAiReviewSourceFormat':
          if (!['AUTO', 'FREE', 'FIXED'].includes(message.value)) throw new Error('Unsupported AI review source format.');
          this.state.aiReviewSourceFormat = message.value as AiReviewSourceFormat; this.invalidateAiReview(); break;
        case 'updateAiReviewContext':
          if (typeof message.value !== 'string' || message.value.length > 8000 || message.value.includes('\0')) throw new Error('AI review context must be under 8000 characters without NUL.');
          this.state.aiReviewContext = message.value; this.invalidateAiReview(); break;
        case 'confirmMatch': if (typeof message.value === 'string') await this.confirmMatch(message.value); break;
        case 'setMatchingSourceFormat':
          if (['AUTO', 'FREE', 'FIXED'].includes(message.value)) {
            this.state.matchingSourceFormat = message.value as MatchingSourceFormat; this.invalidateMatching();
          }
          break;
        case 'chooseContract': await this.chooseContract(); break;
        case 'demo': await this.loadDemo(); break;
        case 'verify': await this.verify(false); break;
        case 'verifyCandidate': await this.verify(true); break;
        case 'showDiff': await this.showDiff(); break;
        case 'applyCandidate': await this.applyCandidate(); break;
        case 'openCobol': await this.openFile('cobol'); break;
        case 'openJava': await this.openFile('java'); break;
        case 'openCandidate': await this.openFile('candidate'); break;
        case 'clearCandidate': this.files.candidate = undefined; this.invalidate(false); break;
        case 'openSettings': await vscode.commands.executeCommand('workbench.action.openSettings', 'sotonship'); break;
        case 'exportReport': await this.exportReport(); break;
        case 'updateProofInputs':
          if (typeof message.value !== 'string' || message.value.length > 32000) throw new Error('Proof mapping JSON must be under 32,000 characters.');
          this.state.proofInputsText = message.value; this.invalidate(true); break;
        case 'setBackendUrl':
          if (typeof message.value !== 'string') return;
          this.state.backendUrl = normalizeBackendUrl(message.value); this.invalidate(true); this.invalidateMatching();
          this.state.message = `Backend set for this session: ${this.state.backendUrl}`; break;
        case 'setCategory':
          if (typeof message.value !== 'string' || !categories.includes(message.value as VerificationCategory)) return;
          this.state.category = message.value as VerificationCategory; this.invalidate(true); break;
      }
    });
    this.publish();
  }

  public async safely(action: () => Promise<unknown>): Promise<void> {
    try { await action(); }
    catch (error) {
      this.state.message = error instanceof Error ? error.message : 'The verification action failed.';
      this.output.appendLine(this.state.message);
      void vscode.window.showErrorMessage(`SOTONSHIP: ${this.state.message}`);
    }
    finally { this.publish(); }
  }

  private invalidate(baseline: boolean): void {
    if (baseline) this.invalidateAiReview();
    if (baseline && this.state.result) this.state.resultStale = true;
    if (this.state.candidateResult) this.state.candidateStale = true;
    this.state.canApply = false; this.state.applied = false;
    if (baseline) this.diagnostics.clear();
    else for (const [uri] of this.diagnostics) {
      if (uri.toString() !== this.files.java?.toString()) this.diagnostics.delete(uri);
    }
  }

  private invalidateAiReview(): void {
    this.aiReviewGeneration++;
    if (this.state.aiReviewResult) this.state.aiReviewStale = true;
  }

  private invalidateMatching(): void {
    if (this.state.matchingResult) this.state.matchingStale = true;
    this.state.confirmedMatchId = undefined;
  }

  private label(uri: vscode.Uri | undefined): FileLabel | undefined {
    if (!uri) return undefined;
    const document = vscode.workspace.textDocuments.find(doc => doc.uri.toString() === uri.toString());
    return { name: basename(uri.path), path: uri.scheme === 'file' ? uri.fsPath : uri.toString(), dirty: document?.isDirty ?? false };
  }

  private publish(): void {
    this.state.files = { cobol: this.label(this.files.cobol), java: this.label(this.files.java), candidate: this.label(this.files.candidate) };
    this.state.matchingFiles = this.matchingFiles.map((uri, index) => ({ candidateId: `candidate-${index + 1}`, file: this.label(uri)! }));
    void this.panel?.webview.postMessage({ type: 'state', state: this.getState() });
  }

  public async chooseFile(role: Role): Promise<boolean> {
    if (this.state.busy) throw new Error('Wait for the current verification to finish.');
    const chosen = await vscode.window.showOpenDialog({ canSelectMany: false, canSelectFolders: false,
      title: role === 'cobol' ? 'Choose original COBOL source' : role === 'java' ? 'Choose Java implementation' : 'Choose proposed Java fix',
      filters: role === 'cobol' ? { 'COBOL source': ['cbl', 'cob', 'cobol'], 'All files': ['*'] } : { 'Java source': ['java', 'txt'], 'All files': ['*'] } });
    if (!chosen?.[0]) return false;
    if (this.state.busy) throw new Error('Wait for the current verification to finish.');
    this.files[role] = chosen[0]; this.invalidate(role !== 'candidate');
    if (role === 'cobol') this.invalidateMatching();
    if (role === 'java') this.state.confirmedMatchId = undefined;
    await this.openFile(role); this.publish(); return true;
  }

  public async chooseContract(): Promise<boolean> {
    const chosen = await vscode.window.showOpenDialog({ canSelectMany: false, canSelectFolders: false,
      title: 'Choose explicit proof-input mapping JSON', filters: { 'Verification mapping': ['json'] } });
    if (!chosen?.[0]) return false;
    const bytes = await vscode.workspace.fs.readFile(chosen[0]);
    if (bytes.length > 32000) throw new Error('Proof mapping file exceeds 32,000 bytes.');
    const mapping = validateProofInputs(JSON.parse(Buffer.from(bytes).toString('utf8')));
    this.state.proofInputsText = JSON.stringify(mapping, null, 2); this.invalidate(true); this.publish(); return true;
  }

  private async openFile(role: Role): Promise<void> {
    const uri = this.files[role]; if (!uri) return;
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri), { viewColumn: vscode.ViewColumn.One, preview: false });
  }

  public async loadDemo(): Promise<void> {
    if (this.state.busy) throw new Error('Wait for the current verification to finish.');
    const bytes = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(this.context.extensionUri, 'examples', 'penny-drift.json'));
    const demo = JSON.parse(Buffer.from(bytes).toString('utf8')) as VerificationRequest;
    this.diagnostics.clear(); this.candidateSnapshot = undefined;
    const cobol = await vscode.workspace.openTextDocument({ language: 'cobol', content: demo.cobolSource });
    const java = await vscode.workspace.openTextDocument({ language: 'java', content: demo.javaSource });
    const candidate = await vscode.workspace.openTextDocument({ language: 'java', content: demo.patchedJavaSource ?? '' });
    this.files = { cobol: cobol.uri, java: java.uri, candidate: candidate.uri };
    this.matchingFiles = []; this.matchingSnapshot = undefined;
    this.state = { ...this.state, category: demo.category, proofInputsText: JSON.stringify(validateProofInputs(demo.proofInputs), null, 2),
      result: undefined, candidateResult: undefined, resultStale: false, candidateStale: false, canApply: false, applied: false,
      matchingFiles: [], matchingResult: undefined, matchingStale: false, confirmedMatchId: undefined,
      aiReviewResult: undefined, aiReviewStale: false, aiReviewSourceFormat: 'AUTO', aiReviewContext: '',
      message: 'Demo loaded into three unsaved editors. Verify the original pair to find the penny discrepancy; no code has been sent yet.' };
    this.aiReviewGeneration++;
    this.lastAiReviewQuestion = undefined;
    await vscode.window.showTextDocument(java, { viewColumn: vscode.ViewColumn.One, preview: false });
    this.open(); this.publish();
  }

  /** Useful to callers/tests too: selection itself never starts a network request. */
  public async configure(input: { cobol: vscode.Uri; java: vscode.Uri; candidate?: vscode.Uri; proofInputs: ProofInputs; category?: VerificationCategory; backendUrl?: string }): Promise<void> {
    if (this.state.busy) throw new Error('Wait for the current verification to finish.');
    this.files = { cobol: input.cobol, java: input.java, candidate: input.candidate };
    this.state.proofInputsText = JSON.stringify(validateProofInputs(input.proofInputs), null, 2);
    if (input.backendUrl) this.state.backendUrl = normalizeBackendUrl(input.backendUrl);
    if (input.category) this.state.category = input.category;
    this.invalidate(true); this.invalidateMatching(); this.publish();
  }

  public async chooseMatchingFiles(): Promise<boolean> {
    if (this.state.busy) throw new Error('Wait for the current verification to finish.');
    const chosen = await vscode.window.showOpenDialog({ canSelectMany: true, canSelectFolders: false,
      title: 'Choose up to 20 candidate Java implementations for GNN matching', filters: { 'Java source': ['java', 'txt'], 'All files': ['*'] } });
    if (!chosen?.length) return false;
    if (this.state.busy) throw new Error('Wait for the current verification to finish.');
    if (chosen.length > 20) throw new Error('Choose between 1 and 20 Java candidates.');
    this.matchingFiles = [...chosen]; this.invalidateMatching(); this.publish(); return true;
  }

  /** Selection never uploads code or infers financial proof inputs. */
  public async configureMatching(input: { cobol: vscode.Uri; candidates: vscode.Uri[]; backendUrl?: string; sourceFormat?: MatchingSourceFormat }): Promise<void> {
    if (this.state.busy) throw new Error('Wait for the current verification to finish.');
    if (!input.candidates.length || input.candidates.length > 20 || new Set(input.candidates.map(uri => uri.toString())).size !== input.candidates.length) throw new Error('Choose between 1 and 20 distinct Java candidates.');
    if (input.sourceFormat && !['AUTO', 'FREE', 'FIXED'].includes(input.sourceFormat)) throw new Error('Unsupported matching source format.');
    const backendUrl = input.backendUrl ? normalizeBackendUrl(input.backendUrl) : this.state.backendUrl;
    this.files.cobol = input.cobol; this.matchingFiles = [...input.candidates]; this.state.backendUrl = backendUrl;
    if (input.sourceFormat) this.state.matchingSourceFormat = input.sourceFormat;
    this.invalidate(true); this.invalidateMatching(); this.publish();
  }

  /** Configuration alone never uploads source. No proof mapping or API key is needed in the client. */
  public async configureAiReview(input: { cobol: vscode.Uri; java: vscode.Uri; backendUrl?: string; sourceFormat?: AiReviewSourceFormat; analysisContext?: string }): Promise<void> {
    if (this.state.busy) throw new Error('Wait for the current analysis to finish.');
    if (input.sourceFormat && !['AUTO', 'FREE', 'FIXED'].includes(input.sourceFormat)) throw new Error('Unsupported AI review source format.');
    if (input.analysisContext !== undefined && (input.analysisContext.length > 8000 || input.analysisContext.includes('\0'))) throw new Error('AI review context must be under 8000 characters without NUL.');
    const backendUrl = input.backendUrl ? normalizeBackendUrl(input.backendUrl) : this.state.backendUrl;
    this.files.cobol = input.cobol; this.files.java = input.java; this.state.backendUrl = backendUrl;
    if (input.sourceFormat) this.state.aiReviewSourceFormat = input.sourceFormat;
    if (input.analysisContext !== undefined) this.state.aiReviewContext = input.analysisContext;
    this.invalidate(true); this.invalidateMatching(); this.publish();
  }

  private aiBinding(cobol: DocumentSnapshot, java: DocumentSnapshot, generation = this.aiReviewGeneration): AiReviewBinding {
    return { cobolUri: cobol.uri.toString(), javaUri: java.uri.toString(), cobolVersion: cobol.version, javaVersion: java.version,
      backendUrl: this.state.backendUrl, sourceFormat: this.state.aiReviewSourceFormat, analysisContext: this.state.aiReviewContext,
      cobolHash: aiSourceHash(cobol.text), javaHash: aiSourceHash(java.text), generation };
  }

  private async aiReviewUnchanged(snapshot: AiReviewSnapshot): Promise<boolean> {
    try {
      const [cobol, java] = await Promise.all([vscode.workspace.openTextDocument(snapshot.cobol.uri), vscode.workspace.openTextDocument(snapshot.java.uri)]);
      if (this.files.cobol?.toString() !== snapshot.cobol.uri.toString() || this.files.java?.toString() !== snapshot.java.uri.toString()) return false;
      return sameAiReviewBinding(snapshot.binding, this.aiBinding(
        { uri: cobol.uri, text: cobol.getText(), version: cobol.version }, { uri: java.uri, text: java.getText(), version: java.version }));
    } catch { return false; }
  }

  public async analyzePairWithAi(): Promise<AiReviewResult> {
    return this.operation('Reviewing COBOL–Java defects with AI', async signal => {
      this.invalidateAiReview();
      const generation = this.aiReviewGeneration;
      const backendUrl = normalizeBackendUrl(this.state.backendUrl);
      const sourceFormat = this.state.aiReviewSourceFormat; const analysisContext = this.state.aiReviewContext;
      const [cobol, java] = await Promise.all([this.document(this.files.cobol, 'COBOL source'), this.document(this.files.java, 'Java implementation')]);
      const moduleName = basename(cobol.uri.path).replace(/[\x00-\x1f/\\]/g, '_').slice(0, 160) || 'Selected-COBOL.cbl';
      const request = validateAiReviewRequest({ moduleName, cobolSource: cobol.text, javaSource: java.text, cobolSourceFormat: sourceFormat, analysisContext });
      const snapshot: AiReviewSnapshot = { cobol, java, binding: { ...this.aiBinding(cobol, java, generation), backendUrl, sourceFormat, analysisContext } };
      if (signal.aborted || !await this.aiReviewUnchanged(snapshot)) throw new Error('Sources or AI review settings changed before upload. Run AI analysis again.');
      const result = await this.client({ backendUrl }).reviewPair(request, signal);
      const current = !signal.aborted && await this.aiReviewUnchanged(snapshot);
      this.lastAiReviewQuestion = { backendUrl, moduleName, cobolSourceFormat: sourceFormat, analysisContext };
      this.state.aiReviewResult = result; this.state.aiReviewStale = !current;
      this.state.message = !current ? 'Sources or AI review settings changed during analysis. AI findings are hidden; analyze the current pair again.'
        : result.status === 'ANALYZED' ? `AI review produced ${result.findings.length} suspected defect(s). These are hypotheses; inspect the code and verify supported behavior separately.`
          : `AI review ${result.status.toLowerCase().replace(/_/g, ' ')}: ${result.summary}`;
      this.output.appendLine(`AI review: ${result.status}; source-bound hypotheses only; no candidate inputs executed.`);
      this.publish(); return result;
    });
  }

  private async matchingDocuments(snapshot: MatchingSnapshot): Promise<vscode.TextDocument[]> {
    return Promise.all([snapshot.cobol, ...snapshot.candidates.map(item => item.document)].map(item => vscode.workspace.openTextDocument(item.uri)));
  }

  private matchingUnchanged(snapshot: MatchingSnapshot, documents: vscode.TextDocument[]): boolean {
    if (this.files.cobol?.toString() !== snapshot.cobol.uri.toString() || this.state.backendUrl !== snapshot.backendUrl
      || this.state.matchingSourceFormat !== snapshot.sourceFormat || this.matchingFiles.length !== snapshot.candidates.length) return false;
    if (documents[0]?.getText() !== snapshot.cobol.text) return false;
    return snapshot.candidates.every((item, index) => item.document.uri.toString() === this.matchingFiles[index]?.toString() && documents[index + 1]?.getText() === item.document.text);
  }

  public async matchPrograms(): Promise<MatchingResult> {
    return this.operation('Matching COBOL with Java candidates', async signal => {
      const cobolUri = this.files.cobol; const candidates = [...this.matchingFiles];
      const backendUrl = normalizeBackendUrl(this.state.backendUrl); const sourceFormat = this.state.matchingSourceFormat;
      if (!candidates.length) throw new Error('Choose Java candidates for program matching first.');
      this.invalidateMatching();
      const [cobol, ...java] = await Promise.all([this.document(cobolUri, 'COBOL source'), ...candidates.map(uri => this.document(uri, 'Java candidate'))]);
      const snapshot: MatchingSnapshot = { cobol, candidates: java.map((document, index) => ({ candidateId: `candidate-${index + 1}`, document })), backendUrl, sourceFormat };
      const request: MatchingRequest = { cobolSource: cobol.text, cobolSourceFormat: sourceFormat,
        candidates: snapshot.candidates.map(item => ({ candidateId: item.candidateId, moduleName: basename(item.document.uri.path).replace(/[\x00-\x1f/\\]/g, '_').slice(0, 160) || item.candidateId, javaSource: item.document.text })), topK: java.length };
      const result = await this.client(snapshot).match(request, signal);
      const current = this.matchingUnchanged(snapshot, await this.matchingDocuments(snapshot)) && !signal.aborted;
      this.matchingSnapshot = snapshot; this.state.matchingResult = result; this.state.matchingStale = !current;
      this.state.message = current ? 'Program matching completed. Inspect the advisory ranking and confirm a candidate; proof inputs still require your review.'
        : 'Matching sources or backend changed during analysis. Run program matching again.';
      this.publish(); return result;
    });
  }

  public async confirmMatch(candidateId: string): Promise<void> {
    await this.operation('Confirming selected program match', async signal => {
      const snapshot = this.matchingSnapshot; const result = this.state.matchingResult;
      if (!snapshot || !result || this.state.matchingStale || !result.candidates.some(item => item.candidateId === candidateId)) throw new Error('Run matching on the current sources before confirming a candidate.');
      const selected = snapshot.candidates.find(item => item.candidateId === candidateId);
      const documents = await this.matchingDocuments(snapshot);
      if (!selected || signal.aborted || !this.matchingUnchanged(snapshot, documents)) {
        this.invalidateMatching(); throw new Error('Matching sources or backend changed. Run matching again before selecting Java.');
      }
      // No await between the current-source check and selecting the confirmed URI.
      this.files.java = selected.document.uri; this.invalidate(true); this.state.confirmedMatchId = candidateId;
      this.state.message = 'Java candidate selected by engineer review. Review or supply the explicit proof inputs, then verify this pair. Matching is not equivalence proof.';
      this.publish();
    });
  }

  private async document(uri: vscode.Uri | undefined, name: string): Promise<DocumentSnapshot> {
    if (!uri) throw new Error(`Choose the ${name} file first.`);
    const document = await vscode.workspace.openTextDocument(uri);
    validateSource(document.getText(), name);
    return { uri, text: document.getText(), version: document.version };
  }

  private async snapshot(requireCandidate: boolean): Promise<Snapshot> {
    const files = { ...this.files };
    const proofInputsText = this.state.proofInputsText;
    const category = this.state.category;
    const backendUrl = normalizeBackendUrl(this.state.backendUrl);
    let mapping: unknown;
    try { mapping = JSON.parse(proofInputsText); }
    catch { throw new Error('Provide valid proof-input JSON with exact field names, bounds and rate identity. Try the demo for an example.'); }
    const [cobol, java, candidate] = await Promise.all([
      this.document(files.cobol, 'COBOL source'), this.document(files.java, 'Java implementation'),
      files.candidate ? this.document(files.candidate, 'proposed Java fix') : Promise.resolve(undefined),
    ]);
    if (requireCandidate && !candidate) throw new Error('Choose a proposed Java fix file first.');
    return { cobol, java, candidate, proofInputsText, proofInputs: validateProofInputs(mapping), category, backendUrl };
  }

  private request(snapshot: Snapshot, candidate: boolean): VerificationRequest {
    const java = candidate ? snapshot.candidate!.text : snapshot.java.text;
    const name = basename(snapshot.cobol.uri.path).replace(/[\x00-\x1f/\\]/g, '_').slice(0, 160) || 'Selected-COBOL.cbl';
    return { moduleName: name, category: snapshot.category, cobolSource: snapshot.cobol.text, javaSource: java,
      patchedJavaSource: snapshot.candidate?.text ?? '', proofInputs: snapshot.proofInputs };
  }

  private async openedDocuments(snapshot: Snapshot): Promise<OpenedDocuments> {
    const entries = await Promise.all((['cobol', 'java', 'candidate'] as const).map(async role => {
      const expected = snapshot[role];
      return [role, expected ? await vscode.workspace.openTextDocument(expected.uri) : undefined] as const;
    }));
    return Object.fromEntries(entries);
  }

  /** Compare all already-open texts in one synchronous turn, without intervening awaits. */
  private matches(snapshot: Snapshot, documents: OpenedDocuments): boolean {
    if (snapshot.proofInputsText !== this.state.proofInputsText || snapshot.backendUrl !== this.state.backendUrl || snapshot.category !== this.state.category) return false;
    for (const role of ['cobol', 'java', 'candidate'] as const) {
      const expected = snapshot[role]; const selected = this.files[role];
      if (!expected && !selected) continue;
      if (!expected || expected.uri.toString() !== selected?.toString()) return false;
      if (documents[role]?.getText() !== expected.text) return false;
    }
    return true;
  }

  private async unchanged(snapshot: Snapshot): Promise<boolean> {
    try { return this.matches(snapshot, await this.openedDocuments(snapshot)); }
    catch { return false; }
  }

  private async operation<T>(title: string, action: (signal: AbortSignal) => Promise<T>): Promise<T> {
    if (this.state.busy) throw new Error('Another verification is already running.');
    this.state.busy = true; this.abort = new AbortController(); this.publish();
    try {
      return await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `SOTONSHIP: ${title}`, cancellable: true }, async (_progress, token) => {
        const cancellation = token.onCancellationRequested(() => this.abort?.abort());
        try { return await action(this.abort!.signal); } finally { cancellation.dispose(); }
      });
    } finally { this.abort = undefined; this.state.busy = false; this.publish(); }
  }

  private client(snapshot: { backendUrl: string }): ApiClient {
    return new ApiClient(snapshot.backendUrl, vscode.workspace.getConfiguration('sotonship').get<number>('requestTimeoutMs', 120000));
  }

  public async verify(candidate: boolean): Promise<VerificationResult> {
    return this.operation(candidate ? 'Checking proposed fix' : 'Verifying source pair', async signal => {
      const snapshot = await this.snapshot(candidate);
      const result = await this.client(snapshot).verify(this.request(snapshot, candidate), signal);
      const current = await this.unchanged(snapshot) && !signal.aborted;
      if (candidate) {
        this.candidateSnapshot = snapshot; this.state.candidateResult = result; this.state.candidateStale = !current;
        this.state.canApply = current && isScopedEquivalent(result) && proofMatchesSources(result, snapshot.cobol.text, snapshot.candidate!.text);
        if (current) this.diagnose(snapshot.candidate!.uri, result);
      } else {
        this.state.result = result; this.state.resultStale = !current;
        if (current) this.diagnose(snapshot.java.uri, result);
      }
      this.state.applied = false;
      this.state.message = current ? `${candidate ? 'Proposed fix' : 'Source pair'}: ${this.statusLabel(result)}. Inspect the scope and evidence before accepting it.`
        : 'The sources or mapping changed during analysis. This result is stale; verify again.';
      this.output.appendLine(`${candidate ? 'Candidate' : 'Pair'} ${result.id}: ${result.formalProofStatus}`);
      this.publish(); return result;
    });
  }

  private statusLabel(result: VerificationResult): string {
    return result.formalProofStatus === 'UNSAT_PROVEN_SAFE' ? 'equivalent within scope' : result.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND' ? 'financial outputs differ' : 'inconclusive; engineer review required';
  }

  private diagnose(uri: vscode.Uri, result: VerificationResult): void {
    if (isScopedEquivalent(result)) { this.diagnostics.delete(uri); return; }
    const witness = result.counterexamplesJson[0];
    const detail = result.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND'
      ? `Modeled outputs differ for GBP ${String(witness?.inputAmountGbp ?? '?')}: COBOL ${String(witness?.cobolOutput ?? '?')}, Java ${String(witness?.javaOutput ?? '?')}.`
      : `Verification is inconclusive: ${String(result.proofScope.reason ?? 'Unsupported semantics or a proof limit.')}`;
    const diagnostic = new vscode.Diagnostic(new vscode.Range(0, 0, 0, 0), `${detail} Program-level finding; this first-line anchor does not identify an exact defect location. See the SOTONSHIP workbench.`,
      result.formalProofStatus === 'SAT_COUNTEREXAMPLE_FOUND' ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Information);
    diagnostic.source = 'SOTONSHIP'; diagnostic.code = result.formalProofStatus;
    this.diagnostics.set(uri, [diagnostic]);
  }

  public async showDiff(): Promise<void> {
    if (!this.files.java || !this.files.candidate) throw new Error('Choose the current Java and proposed fix files first.');
    await vscode.commands.executeCommand('vscode.diff', this.files.java, this.files.candidate, 'Java implementation ↔ proposed fix');
  }

  public async applyCandidate(): Promise<boolean> {
    return this.operation('Re-verifying before applying to the Java editor', async signal => {
      const snapshot = this.candidateSnapshot;
      if (!snapshot?.candidate || this.state.candidateStale || !this.state.canApply || !this.state.candidateResult
        || !isScopedEquivalent(this.state.candidateResult) || !proofMatchesSources(this.state.candidateResult, snapshot.cobol.text, snapshot.candidate.text)
        || !await this.unchanged(snapshot)) throw new Error('Check the exact current proposed fix before applying it. The sources or proof mapping may have changed.');
      const result = await this.client(snapshot).verify(this.request(snapshot, true), signal);
      if (!isScopedEquivalent(result) || !proofMatchesSources(result, snapshot.cobol.text, snapshot.candidate!.text)) {
        this.state.candidateResult = result; this.state.canApply = false;
        throw new Error('The fresh result did not establish equivalence within scope. The Java editor was preserved.');
      }
      if (!await this.unchanged(snapshot)) {
        this.invalidate(true); throw new Error('Source or mapping changed during re-verification. The Java editor was preserved.');
      }
      const document = await vscode.workspace.openTextDocument(snapshot.java.uri);
      const editor = await vscode.window.showTextDocument(document, { viewColumn: vscode.ViewColumn.One, preview: false });
      const documents = await this.openedDocuments(snapshot);
      this.applying = true;
      let applied = false;
      try {
        applied = await editor.edit(builder => {
          if (signal.aborted) throw new Error('Applying the fix was cancelled; the Java editor was preserved.');
          if (!this.matches(snapshot, documents)) {
            this.invalidate(true); throw new Error('The source or mapping changed. Check the candidate again; the Java editor was preserved.');
          }
          builder.replace(new vscode.Range(document.positionAt(0), document.positionAt(snapshot.java.text.length)), snapshot.candidate!.text);
        }, { undoStopBefore: true, undoStopAfter: true });
      } finally { this.applying = false; }
      if (!applied) { this.invalidate(true); throw new Error('VS Code could not apply the edit; the document may have changed. Verify again.'); }
      const updated = { ...snapshot, java: { ...snapshot.java, text: snapshot.candidate!.text, version: document.version } };
      if (!await this.unchanged(updated)) {
        this.state.result = result; this.state.candidateResult = result; this.invalidate(true);
        this.state.message = 'The verified replacement was applied, but another source or mapping edit followed it. Verify the current editor text again.';
        this.publish(); return true;
      }
      this.diagnostics.clear(); this.state.result = result; this.state.resultStale = false;
      this.state.candidateResult = result; this.state.candidateStale = false; this.state.canApply = false; this.state.applied = true;
      this.candidateSnapshot = undefined;
      this.state.message = 'Verified fix applied to the Java editor. It remains unsaved: review it, save it when ready, or use Undo to restore the previous text.';
      this.output.appendLine(`Applied source-bound result ${result.id} to Java editor; no automatic save.`);
      this.publish(); return true;
    });
  }

  private async exportReport(): Promise<void> {
    if (!this.state.result && !this.state.candidateResult && !this.state.matchingResult && !this.state.aiReviewResult) throw new Error('Run AI review, matching or verification before exporting evidence.');
    const content = JSON.stringify({ exportedAt: new Date().toISOString(), backend: this.state.backendUrl,
      resultStale: this.state.resultStale, candidateStale: this.state.candidateStale,
      humanReviewStatus: 'PENDING', matching: this.state.matchingResult, matchingStale: this.state.matchingStale,
      confirmedMatchId: this.state.confirmedMatchId, aiReview: this.state.aiReviewResult, aiReviewStale: this.state.aiReviewStale,
      aiReviewQuestion: this.lastAiReviewQuestion,
      original: this.state.result, candidate: this.state.candidateResult }, null, 2);
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument({ language: 'json', content }), { preview: false });
  }

  dispose(): void { this.abort?.abort(); this.panel?.dispose(); this.subscriptions.forEach(item => item.dispose()); }
}

export function activate(context: vscode.ExtensionContext): WorkbenchController {
  const controller = new WorkbenchController(context);
  context.subscriptions.push(controller,
    vscode.commands.registerCommand('sotonship.openWorkbench', () => controller.open()),
    vscode.commands.registerCommand('sotonship.tryDemo', () => controller.safely(() => controller.loadDemo())),
    vscode.commands.registerCommand('sotonship.showFixDiff', () => controller.safely(() => controller.showDiff())),
    vscode.commands.registerCommand('sotonship.analyzePairWithAi', () => controller.safely(async () => {
      controller.open();
      if (!await controller.chooseFile('cobol') || !await controller.chooseFile('java')) return;
      await controller.analyzePairWithAi();
    })),
    vscode.commands.registerCommand('sotonship.matchPrograms', () => controller.safely(async () => {
      controller.open();
      if (!await controller.chooseFile('cobol') || !await controller.chooseMatchingFiles()) return;
      await controller.matchPrograms();
    })),
    vscode.commands.registerCommand('sotonship.verifyFiles', () => controller.safely(async () => {
      controller.open();
      if (!await controller.chooseFile('cobol') || !await controller.chooseFile('java') || !await controller.chooseContract()) return;
      await controller.verify(false);
    })));
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.text = '$(check-all) SOTONSHIP'; status.tooltip = 'Open COBOL → Java verification workbench'; status.command = 'sotonship.openWorkbench'; status.show();
  context.subscriptions.push(status);
  return controller;
}

export function deactivate(): void {}
