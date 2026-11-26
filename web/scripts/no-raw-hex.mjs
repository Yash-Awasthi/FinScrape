// Guard: tokens.css is the only file allowed to name a raw colour.
// Any other .ts/.tsx/.css under src that spells #rrggbb (or #rgb) fails lint.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.resolve(here, "../src");
const tokenFile = path.resolve(srcDir, "tokens.css");
const hex = /#[0-9a-fA-F]{3,8}\b/g;

const files = [];
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (/\.(ts|tsx|css)$/.test(entry.name)) files.push(full);
  }
}
walk(srcDir);

const offenders = [];
for (const file of files) {
  if (file === tokenFile) continue;
  const lines = fs.readFileSync(file, "utf8").split(/\r?\n/);
  lines.forEach((line, i) => {
    if (hex.test(line)) offenders.push(`${path.relative(process.cwd(), file)}:${i + 1}`);
    hex.lastIndex = 0;
  });
}

if (offenders.length) {
  console.error("no-raw-hex: raw colour outside tokens.css");
  for (const o of offenders) console.error("  " + o);
  process.exit(1);
}
console.log(`no-raw-hex: ok (${files.length} files)`);
