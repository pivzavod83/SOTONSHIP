import * as vscode from 'vscode';
import { randomBytes } from 'node:crypto';

/** The webview only renders state; the extension host owns files and HTTP. */
export function getWebviewHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const stylesheet = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'workbench.css'));
  const script = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'workbench.js'));
  const nonce = randomBytes(24).toString('base64');
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
  <link rel="stylesheet" href="${stylesheet}">
  <title>COBOL Verification Workbench</title>
</head>
<body>
  <div class="workbench">
    <header class="page-header">
      <div><p class="eyebrow">COBOL → JAVA</p><h1>Migration workbench</h1><p class="subtitle">Find corresponding programs with a GNN, then check supported financial behavior.</p></div>
      <button id="demo" class="secondary">Try penny drift demo</button>
    </header>
    <section class="connection" aria-label="Backend connection">
      <div class="connection-label"><span class="connection-dot" aria-hidden="true"></span><label for="backend-url">Verification backend</label></div>
      <div class="endpoint-control"><input id="backend-url" type="url" spellcheck="false" aria-describedby="endpoint-help"><button id="save-endpoint" class="quiet">Use address</button><button id="open-settings" class="quiet">Settings</button></div>
      <p id="endpoint-help" class="muted">Source code is sent to this address only when you request matching or verification. No LLM is connected.</p>
    </section>
    <p id="status-message" class="status-message" role="status" aria-live="polite">Choose a COBOL source and a Java candidate to begin.</p>
    <main class="workspace-grid">
      <aside class="setup-column" aria-label="Verification setup">
        <section class="card source-card">
          <div class="section-heading"><span class="step" aria-hidden="true">1</span><div><h2>Select your source pair</h2><p>Uses the current editor contents, including unsaved edits.</p></div></div>
          <div class="file-slot"><div class="file-heading"><label>COBOL source</label><button id="choose-cobol" class="quiet">Choose file</button></div><button id="open-cobol" class="file-link" disabled>No COBOL file selected</button><p id="cobol-path" class="file-path"></p></div>
          <div class="matching-setup">
            <h3>Find its Java counterpart</h3><p class="muted">Optional whole-program GNN ranking. You confirm the match before verification.</p>
            <div class="button-row"><button id="choose-matching-files" class="secondary">Choose Java candidates</button></div>
            <ul id="matching-files" class="matching-files"></ul>
            <label for="matching-format" class="field-label">COBOL format for matching</label>
            <select id="matching-format"><option value="AUTO">Auto-detect</option><option value="FREE">Free format</option><option value="FIXED">Fixed format</option></select>
            <button id="match-programs" class="secondary wide" disabled>Rank Java candidates with GNN</button>
          </div>
          <div class="file-slot"><div class="file-heading"><label>Java to verify</label><button id="choose-java" class="quiet">Choose file</button></div><button id="open-java" class="file-link" disabled>No Java file selected</button><p id="java-path" class="file-path"></p></div>
          <label for="category" class="field-label">Financial context</label>
          <select id="category"><option value="FX_CONVERSION">Foreign exchange</option><option value="INTEREST_CALC">Interest calculation</option><option value="REMITTANCE_FEE">Remittance fee</option><option value="EXTERNAL_LIMIT_CASE">External / unsupported case</option></select>
        </section>
        <section class="card contract-card">
          <div class="section-heading"><span class="step" aria-hidden="true">2</span><div><h2>Declare the proof scope</h2><p>Map fields and parameters explicitly; choose finite input bounds and the exact reference rate.</p></div></div>
          <div class="contract-actions"><label for="proof-inputs" class="field-label">Input mapping &amp; proof bounds · JSON</label><button id="choose-contract" class="quiet">Load JSON</button></div>
          <textarea id="proof-inputs" spellcheck="false" rows="15" aria-describedby="proof-help"></textarea>
          <p id="proof-help" class="muted">An absent or mismatched contract produces UNKNOWN. The demo includes a complete example.</p>
          <button id="verify" class="primary wide" disabled>Verify source pair</button>
        </section>
        <section class="card candidate-card">
          <div class="section-heading"><span class="step" aria-hidden="true">3</span><div><h2>Review a proposed fix</h2><p>Select a revised Java file, verify it, then inspect its diff.</p></div></div>
          <div class="file-heading"><label>Proposed Java replacement</label><button id="choose-candidate" class="quiet">Choose file</button></div>
          <button id="open-candidate" class="file-link" disabled>No proposed fix selected</button><p id="candidate-path" class="file-path"></p>
          <div class="button-row"><button id="verify-candidate" class="secondary" disabled>Verify proposed fix</button><button id="clear-candidate" class="quiet" disabled>Clear</button></div>
          <div class="button-row"><button id="show-diff" class="secondary" disabled>Inspect diff</button><button id="apply-candidate" class="primary" disabled>Apply verified fix</button></div>
          <p class="muted">Applying requires a fresh supported UNSAT proof. The extension checks the current editor contents again before replacing Java.</p>
          <p id="applied-message" class="applied-message" hidden>✓ Verified replacement applied to the Java editor.</p>
        </section>
      </aside>
      <section class="evidence-column" aria-label="Verification evidence">
        <div class="evidence-heading"><div><p class="eyebrow">ENGINEER REVIEW</p><h2>Evidence before approval</h2></div><button id="export-report" class="secondary" disabled>Export report</button></div>
        <div id="matching-result"></div>
        <div id="empty-state" class="empty-state"><div class="empty-mark" aria-hidden="true">≠</div><h3>Find the transaction that changes.</h3><p>Run the source pair to see a concrete counterexample, a bounded equivalence result, or an explicit reason the verifier cannot decide.</p><div class="legend"><span><i class="dot sat" aria-hidden="true"></i>SAT · differing output found</span><span><i class="dot unsat" aria-hidden="true"></i>UNSAT · equivalent within scope</span><span><i class="dot unknown" aria-hidden="true"></i>UNKNOWN · human review needed</span></div></div>
        <div id="original-result"></div>
        <div id="candidate-result"></div>
        <footer class="evidence-footer">A proof covers the supported scalar model and declared bounds. It does not certify arbitrary COBOL, external systems, or production readiness. GNN similarities rank whole programs; they are not proof, calibrated confidence, or exact fault localization.</footer>
      </section>
    </main>
  </div>
  <script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
}
