/** Browser regression test on an isolated episode. No API calls or existing project writes.
 * node scripts/check-vector.mjs
 * Requires the local vendor/engine, its npm deps and Chrome (same as rendering).
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const project = fs.mkdtempSync(path.join(os.tmpdir(), 'btv-vector-test-'));
const oldCwd = process.cwd();
let browser;
try {
  for (const dir of ['pages', 'extras', 'out']) fs.mkdirSync(path.join(project, dir));
  fs.symlinkSync(path.join(root, 'vendor/engine'), path.join(project, 'engine'));
  fs.symlinkSync(path.join(root, 'vendor/deps/node_modules'), path.join(project, 'engine_modules'));
  fs.writeFileSync(path.join(project, 'index.html'), '<!doctype html><html><head><meta charset="utf-8"><meta name="engine-modules" content="engine_modules/"></head><body><script src="script.js"></script><script src="engine/boot.js"></script></body></html>');
  fs.copyFileSync(path.join(root, 'backend/app/js/vector.js'), path.join(project, 'extras/vector.js'));
  const svg = fs.readFileSync(path.join(root, 'docs/assets/vector-demo.svg'), 'utf8');
  fs.writeFileSync(path.join(project, 'extras/assets.js'), `window.BTV_VECTORS = ${JSON.stringify({ 'demo.svg': svg })};`);
  fs.writeFileSync(path.join(project, 'script.js'), `globalThis.SCRIPT = ${JSON.stringify({
    META: { style: 'whiteboard', lang: 'en', extras: ['extras/assets.js', 'extras/vector.js'] },
    PAGES: [{ id: 'p01', cues: [{ t: 'Vector animation test', hold: 3 }] }],
  })};`);
  fs.writeFileSync(path.join(project, 'pages/p01.js'), `ENGINE.visual('p01', P => {
    P.vector('demo.svg', 500, 200, 800, 600, {at: 0.5, dur: 2}).hide(4, 0.5);
  });`);
  process.chdir(project);
  const { openStage } = await import(pathToFileURL(path.join(root, 'vendor/engine/tools/lib.mjs')));
  const stage = await openStage('render');
  browser = stage.browser;
  const page = stage.page;
  async function shot(t) {
    await page.evaluate(async t => { ENGINE.renderAt(t); if (window.__frameReady) await window.__frameReady(t); }, t);
    return page.screenshot();
  }
  const early = await shot(0.1);
  const middle = await shot(1.4);
  const end = await shot(3.5);
  assert(!early.equals(middle), 'drawing must appear after its start');
  assert(!middle.equals(end), 'strokes must progress over time');
  assert.equal(await page.locator('.btv-vector path').count(), 1);
  const cold = await shot(1.4);
  await shot(4.6);
  assert.equal(await page.locator('.btv-vector').evaluate(el => el.style.opacity), '0');
  const warm = await shot(1.4);
  assert(cold.equals(warm), 'backwards seeking must be pixel-identical');
  console.log('PASS: SVG draw progress, hide, and backwards-seek pixel determinism');
} finally {
  if (browser) await browser.close();
  process.chdir(oldCwd);
  fs.rmSync(project, { recursive: true, force: true });
}
