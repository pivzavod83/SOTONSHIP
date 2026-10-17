# Sotonship UI demo

This is a self-contained frontend implementation of the approved comparison-first IDE design. It contains no backend, machine-learning model, framework, build step, or external dependency.

## Run

```powershell
cd "D:\2 personal\sotonship\ui"
node serve.mjs
```

Open `http://127.0.0.1:4173`.

If port `4173` is already in use, the server automatically tries `4174`, then subsequent ports. Open the exact URL printed after `Sotonship comparison demo:`.

## Demo functionality

- Edit COBOL and Java side by side with syntax and semantic-region highlighting.
- Inspect aligned logic using the numbered mapping gutter.
- Filter, open, resolve, and reopen review findings.
- Navigate to the dependency graph and verification-evidence views.
- Run the simulated verification flow and apply the suggested Java remediation.
- Export demo evidence, toggle the queue, synchronize scrolling, save edits locally, and reset the demo.

All files for this implementation are contained in this folder.
