/* Runs the installed extension in a separate desktop profile, never the user's workspace. */
const { existsSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } = require('node:fs');
const { join, resolve } = require('node:path');
const { tmpdir } = require('node:os');
const { runTests } = require('@vscode/test-electron');

async function main() {
  const root = resolve(__dirname, '..');
  const tests = join(root, 'dist', 'test', 'host-suite.js');
  if (!existsSync(tests)) throw new Error('Compile the extension before running native host tests: npm run compile.');
  const requestedExecutable = process.env.VSCODE_EXECUTABLE_PATH;
  if (requestedExecutable && !existsSync(requestedExecutable)) throw new Error('VSCODE_EXECUTABLE_PATH does not exist.');
  const localExecutables = process.platform === 'darwin' ? [
    '/Applications/Visual Studio Code.app/Contents/MacOS/Code',
    '/Applications/Visual Studio Code.app/Contents/MacOS/Electron',
  ] : [];
  const executable = requestedExecutable || localExecutables.find(existsSync);
  const temporaryRoot = mkdtempSync(join(tmpdir(), 'sotonship-vscode-host-'));
  const workspace = join(temporaryRoot, 'workspace');
  mkdirSync(join(workspace, '.vscode'), { recursive: true });
  writeFileSync(join(workspace, '.vscode', 'settings.json'), JSON.stringify({
    'telemetry.telemetryLevel': 'off', 'workbench.startupEditor': 'none',
    'window.newWindowProfile': 'Default', 'security.workspace.trust.enabled': false,
    'extensions.autoUpdate': false, 'extensions.autoCheckUpdates': false,
    'update.mode': 'none', 'files.hotExit': 'off',
  }));
  // A surrounding Electron shell can set this variable; child VS Code must start normally.
  delete process.env.ELECTRON_RUN_AS_NODE;
  console.log(`Native host tests: ${executable || 'downloaded stable VS Code'}; isolated temporary workspace.`);
  try {
    await runTests({
      extensionDevelopmentPath: root, extensionTestsPath: tests,
      ...(executable ? { vscodeExecutablePath: executable } : { version: process.env.VSCODE_TEST_VERSION || 'stable' }),
      reuseMachineInstall: false,
      extensionTestsEnv: { LIVE_VERIFIER_URL: process.env.LIVE_VERIFIER_URL || 'http://127.0.0.1:3002',
        ...(process.env.AI_REVIEW_HOST_ONLY ? { AI_REVIEW_HOST_ONLY: process.env.AI_REVIEW_HOST_ONLY } : {}),
        ...(process.env.LIVE_MATCHING_URL ? { LIVE_MATCHING_URL: process.env.LIVE_MATCHING_URL } : {}) },
      launchArgs: [workspace, '--user-data-dir', join(temporaryRoot, 'profile'),
        '--extensions-dir', join(temporaryRoot, 'extensions'), '--disable-extensions',
        '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes', '--disable-updates'],
    });
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
