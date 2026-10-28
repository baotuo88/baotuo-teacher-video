// Prints a project's script.js as JSON: { META, PAGES }. Run with the project dir as cwd or argv[2].
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const dir = process.argv[2] || process.cwd();
const ctx = { console };
ctx.window = ctx;
ctx.globalThis = ctx;
vm.createContext(ctx);
try {
  vm.runInContext(fs.readFileSync(path.join(dir, 'script.js'), 'utf8'), ctx, { filename: 'script.js', timeout: 2000 });
} catch (e) {
  console.log(JSON.stringify({ error: String(e && e.message || e) }));
  process.exit(0);
}
const S = ctx.SCRIPT;
if (!S || !Array.isArray(S.PAGES)) {
  console.log(JSON.stringify({ error: 'script.js does not define SCRIPT.PAGES' }));
} else {
  console.log(JSON.stringify({ META: S.META || {}, PAGES: S.PAGES }));
}
