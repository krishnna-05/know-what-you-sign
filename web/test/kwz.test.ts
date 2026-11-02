// The encoder's output must be standard DEFLATE, so zlib is the referee: if
// zlib reads back every byte, any correct decoder will.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { crc32 as zlibCrc32, inflateRawSync } from "node:zlib";
import { crc32, deflateRaw, pack } from "../src/compress/kwz.ts";

const FIXTURES = new URL("../../tests/fixtures/", import.meta.url);

function roundTrips(data: Uint8Array) {
  assert.deepEqual(new Uint8Array(inflateRawSync(deflateRaw(data))), data);
}

// A deterministic generator, so a failure reproduces.
function noise(n: number, alphabet = 256, seed = 1): Uint8Array {
  const out = new Uint8Array(n);
  let x = seed;
  for (let i = 0; i < n; i++) {
    x = (Math.imul(x, 1103515245) + 12345) >>> 0;
    out[i] = (x >>> 16) % alphabet;
  }
  return out;
}

test("edge cases round-trip", () => {
  roundTrips(new Uint8Array(0));
  roundTrips(new Uint8Array([7]));
  roundTrips(new Uint8Array([1, 2]));
  roundTrips(new Uint8Array(1_000_000)); // one long run: overlapping copies
  roundTrips(new TextEncoder().encode("abcabcabcabcabcabcabcabc"));
});

test("incompressible data is stored, and stays the same size", () => {
  const data = noise(300_000);
  roundTrips(data);
  // Five bytes of framing per 64 KB stored block, and nothing more.
  assert.ok(deflateRaw(data).length < data.length + 64);
});

test("mixed blocks, matches reaching across block boundaries", () => {
  const text = noise(200_000, 12);
  const data = new Uint8Array(text.length * 2 + 70_000);
  data.set(text, 0);
  data.set(noise(70_000, 256, 9), text.length);
  data.set(text, text.length + 70_000);
  roundTrips(data);
});

test("the fixture PDFs round-trip, and the scan shrinks dramatically", () => {
  for (const name of ["sample_lease.pdf", "sample_tos.pdf", "sample_lease_scanned.pdf"]) {
    roundTrips(new Uint8Array(readFileSync(new URL(name, FIXTURES))));
  }
  const scan = new Uint8Array(readFileSync(new URL("sample_lease_scanned.pdf", FIXTURES)));
  assert.ok(deflateRaw(scan).length < scan.length / 20);
});

test("crc32 agrees with zlib", () => {
  for (const data of [new Uint8Array(0), noise(10_000), new Uint8Array(5000).fill(255)]) {
    assert.equal(crc32(data), zlibCrc32(data));
  }
});

test("the container header", () => {
  const data = noise(5000, 4);
  const packed = pack(data);
  const view = new DataView(packed.buffer);
  assert.equal(new TextDecoder().decode(packed.subarray(0, 4)), "KWZ1");
  assert.equal(view.getUint32(4, true), data.length);
  assert.equal(view.getUint32(8, true), zlibCrc32(data));
  assert.deepEqual(new Uint8Array(inflateRawSync(packed.subarray(16))), data);
});
