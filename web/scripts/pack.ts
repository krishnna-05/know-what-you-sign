// Packs a file the way the browser does before uploading it, so the Python
// tests can check the server decodes what the real encoder produces.
//
//   node scripts/pack.ts <input> <output>
import { readFileSync, writeFileSync } from "node:fs";
import { pack } from "../src/compress/kwz.ts";

const [input, output] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: node scripts/pack.ts <input> <output>");
  process.exit(2);
}
writeFileSync(output, pack(new Uint8Array(readFileSync(input))));
