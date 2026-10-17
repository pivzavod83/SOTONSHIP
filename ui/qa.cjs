const { chromium } = require("C:/Users/boeva/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const path = require("node:path");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
  });
  const context = await browser.newContext({ viewport: { width: 1600, height: 992 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });

  await page.goto("http://127.0.0.1:4173", { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await page.screenshot({ path: path.join(__dirname, "demo-preview.png"), fullPage: true });

  assert(await page.locator("#compareView").isVisible(), "Compare view is not the default");
  assert(await page.locator(".CodeMirror").count() === 2, "Two real CodeMirror editors were not created");
  assert(await page.locator(".queue-data").count() === 3, "Review queue rows are missing");

  // Click an exact Java character position, type, and confirm insertion at that position.
  const clickPoint = await page.evaluate(() => {
    const cm = window.demoEditors.java.cm;
    const position = { line: 12, ch: 8 };
    const coords = cm.charCoords(position, "page");
    return { x: coords.left + 1, y: (coords.top + coords.bottom) / 2, originalLine: cm.getLine(position.line) };
  });
  await page.mouse.click(clickPoint.x, clickPoint.y);
  await page.keyboard.type("/*CLICK*/");
  const clickResult = await page.evaluate(() => ({ line: window.demoEditors.java.cm.getLine(12), cursor: window.demoEditors.java.cm.getCursor() }));
  assert(clickResult.line === `${clickPoint.originalLine.slice(0, 8)}/*CLICK*/${clickPoint.originalLine.slice(8)}`, "Mouse click inserted text at the wrong character");
  assert(clickResult.cursor.line === 12 && clickResult.cursor.ch === 17, "Caret did not remain at the typed position");

  // Undo and redo must behave like an IDE.
  await page.keyboard.press("Control+z");
  assert(await page.evaluate(() => window.demoEditors.java.cm.getLine(12)) === clickPoint.originalLine, "Undo failed");
  await page.keyboard.press("Control+y");
  assert((await page.evaluate(() => window.demoEditors.java.cm.getLine(12))).includes("/*CLICK*/"), "Redo failed");
  await page.keyboard.press("Control+z");

  // Drag-select a precise token with the mouse.
  const selectionPoints = await page.evaluate(() => {
    const cm = window.demoEditors.java.cm;
    const start = cm.charCoords({ line: 17, ch: 12 }, "page");
    const end = cm.charCoords({ line: 17, ch: 22 }, "page");
    return { x1: start.left + 1, y1: (start.top + start.bottom) / 2, x2: end.left + 1, y2: (end.top + end.bottom) / 2 };
  });
  await page.mouse.move(selectionPoints.x1, selectionPoints.y1);
  await page.mouse.down();
  await page.mouse.move(selectionPoints.x2, selectionPoints.y2, { steps: 8 });
  await page.mouse.up();
  assert((await page.evaluate(() => window.demoEditors.java.cm.getSelection())).length >= 8, "Mouse drag selection did not select the intended code");

  // Tab indentation, Shift-Tab, Enter and multiline typing.
  await page.evaluate(() => { const cm = window.demoEditors.cobol.cm; cm.setCursor({ line: 12, ch: 0 }); cm.focus(); });
  const cobolBefore = await page.evaluate(() => window.demoEditors.cobol.cm.getLine(12));
  await page.keyboard.press("Tab");
  assert((await page.evaluate(() => window.demoEditors.cobol.cm.getLine(12))) === `    ${cobolBefore}`, "Tab indentation failed");
  await page.keyboard.press("Shift+Tab");
  assert((await page.evaluate(() => window.demoEditors.cobol.cm.getLine(12))) === cobolBefore, "Shift-Tab indentation failed");
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  await page.keyboard.type("       * EDITED NOTE");
  assert((await page.evaluate(() => window.demoEditors.cobol.cm.getValue())).includes("* EDITED NOTE"), "New-line typing failed");

  // Changes must persist after a browser reload.
  await page.waitForTimeout(100);
  await page.reload({ waitUntil: "networkidle" });
  assert((await page.evaluate(() => window.demoEditors.cobol.cm.getValue())).includes("* EDITED NOTE"), "Edited code did not persist after reload");

  // Synchronized scrolling must move both panes.
  await page.evaluate(() => window.demoEditors.java.cm.scrollTo(0, 160));
  await page.waitForTimeout(50);
  const scroll = await page.evaluate(() => ({ java: window.demoEditors.java.cm.getScrollInfo().top, cobol: window.demoEditors.cobol.cm.getScrollInfo().top }));
  assert(Math.abs(scroll.java - scroll.cobol) < 3, "Synchronized scrolling failed");

  // The surrounding demo remains interactive.
  await page.locator('[data-filter="high"]').click();
  assert(await page.locator(".queue-data").count() === 1, "Severity filtering failed");
  await page.getByRole("button", { name: "DEPENDENCIES" }).click();
  assert(await page.locator("#dependenciesView").isVisible(), "Dependency view failed");
  assert(await page.locator(".dependency-node").count() === 7, "Classic function cards are missing");
  assert(await page.locator(".dependency-edges .edge").count() === 9, "Not all dependency relationships are drawn");
  await page.locator('[data-module="round"]').last().click();
  assert((await page.locator("#mappingTitle").textContent()).trim() === "ROUND-INTEREST", "Function selection did not update graph details");
  assert((await page.locator("#mappingInputs").textContent()).includes("packed decimal"), "Selected function inputs are missing");
  assert((await page.locator("#mappingReturns").textContent()).includes("rounded"), "Selected function return details are missing");
  await page.getByRole("button", { name: "EVIDENCE" }).click();
  assert(await page.getByText("Counterexample found").isVisible(), "Evidence view failed");

  assert(errors.length === 0, `Browser errors: ${errors.join(" | ")}`);
  console.log("QA passed: exact click placement, typing, drag selection, undo/redo, indentation, multiline edits, persistence, synchronized scrolling, syntax editor rendering, and all demo views.");
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
