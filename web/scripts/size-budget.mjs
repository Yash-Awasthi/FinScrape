// gzip budget for the shipped bundle (plan M3.3). The globe is a lazy chunk and is
// accounted for separately: it is 1.8MB of three.js that a visitor who never opens
// Today should not be charged for, so folding it into one total would hide the win.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";

const ENTRY_BUDGET_KB = 400;
const GLOBE_BUDGET_KB = 800;

const assets = "dist/assets";
const files = readdirSync(assets).filter((f) => f.endsWith(".js"));
const gz = (f) => gzipSync(readFileSync(`${assets}/${f}`)).length / 1024;
const isGlobe = (f) => /globe\.gl|three/i.test(f);

// Every JS chunk that is not the globe. Vite already tree-shakes; this asserts that
// the shell (entry + shared + panels) stays small enough for a mid-range phone.
const entry = files.filter((f) => !isGlobe(f)).reduce((sum, f) => sum + gz(f), 0);
const globe = files.filter(isGlobe).reduce((sum, f) => sum + gz(f), 0);

console.log(`entry JS: ${entry.toFixed(1)} KB gzip (budget ${ENTRY_BUDGET_KB})`);
console.log(`globe JS: ${globe.toFixed(1)} KB gzip (budget ${GLOBE_BUDGET_KB}, lazy)`);
console.log(`index.html: ${(statSync("dist/index.html").size / 1024).toFixed(1)} KB raw`);

const problems = [];
if (entry > ENTRY_BUDGET_KB)
  problems.push(`entry JS ${entry.toFixed(1)} KB > ${ENTRY_BUDGET_KB} KB`);
if (globe > GLOBE_BUDGET_KB)
  problems.push(`globe JS ${globe.toFixed(1)} KB > ${GLOBE_BUDGET_KB} KB`);
if (!files.some(isGlobe)) problems.push("no globe chunk in dist: the glob is no longer lazy");
if (problems.length) {
  console.error(`size-budget: ${problems.join("; ")}`);
  process.exit(1);
}
console.log("size-budget: ok");
