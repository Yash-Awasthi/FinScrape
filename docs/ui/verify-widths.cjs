// Read each screenshot's real width/height from the PNG IHDR and fail on a blank file.
//
//   node docs/ui/verify-widths.cjs
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const dir = path.resolve(__dirname, "before");
const files = fs
  .readdirSync(dir)
  .filter((f) => f.endsWith(".png"))
  .sort();
let bad = 0;
for (const file of files) {
  const full = path.join(dir, file);
  const buf = fs.readFileSync(full);
  if (buf.slice(1, 4).toString("ascii") !== "PNG") {
    console.log(`FAIL ${file}: not a PNG`);
    bad += 1;
    continue;
  }
  const width = buf.readUInt32BE(16);
  const height = buf.readUInt32BE(20);
  const okWidth = [360, 768, 1440].includes(width);
  const okSize = buf.length > 8 * 1024;
  if (!okWidth || !okSize) bad += 1;
  console.log(
    `${okWidth && okSize ? "ok  " : "FAIL"} ${file.padEnd(18)} ${width}x${height}  ${buf.length} bytes`,
  );
}
console.log(`\n${files.length} PNGs, ${bad} failed`);
process.exit(bad ? 1 : 0);
