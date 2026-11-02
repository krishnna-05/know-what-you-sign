// A DEFLATE encoder (RFC 1951) and the KWZ1 upload container around it.
//
// The server's decoder is kwys/compress/inflate.py; the container is described
// in kwys/compress/__init__.py. Output is standard raw DEFLATE, so zlib can
// check it too, and the tests do.
//
// Two algorithms, applied per 64 KB block:
//   1. LZ77 finds repeats. Every position is hashed on its next three bytes;
//      a chain per hash bucket lists earlier positions with the same three
//      bytes, and the longest match within the last 32 KB wins.
//   2. Huffman coding then gives each literal, length and distance symbol a
//      bit pattern whose length follows its frequency in that block.
// A block that would not shrink by at least a tenth is sent stored, as raw
// bytes. Most typed PDFs are already compressed inside, and a stored block
// costs the server nothing to decode.
//
// No imports, so Node can load this file directly in tests.

const WINDOW = 1 << 15; // DEFLATE's maximum back-reference distance
const MIN_MATCH = 3;
const MAX_MATCH = 258;
const HASH_SIZE = 1 << 15;
// How many earlier candidates to try per position. Longer chains find slightly
// longer matches; past ~64 the gain is a percent or two for double the time.
const MAX_CHAIN = 64;
const BLOCK_SIZE = 1 << 16;
const MAX_STORED = 65535;

const LENGTH_BASE = [
  3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131,
  163, 195, 227, 258,
];
const LENGTH_EXTRA = [
  0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DIST_BASE = [
  1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049,
  3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
const DIST_EXTRA = [
  0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
];
const CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
const CL_EXTRA: Record<number, number> = { 16: 2, 17: 3, 18: 7 };

// Value -> symbol, for every length and distance, so encoding is one lookup.
const LENGTH_CODE = new Uint8Array(MAX_MATCH + 1);
const DIST_CODE = new Uint8Array(WINDOW + 1);
for (let c = 0; c < 29; c++) {
  const end = c === 28 ? MAX_MATCH : LENGTH_BASE[c] + (1 << LENGTH_EXTRA[c]) - 1;
  for (let v = LENGTH_BASE[c]; v <= end; v++) LENGTH_CODE[v] = c;
}
for (let c = 0; c < 30; c++) {
  const end = Math.min(WINDOW, DIST_BASE[c] + (1 << DIST_EXTRA[c]) - 1);
  for (let v = DIST_BASE[c]; v <= end; v++) DIST_CODE[v] = c;
}

/** Bits packed least-significant first, as DEFLATE requires. */
class BitWriter {
  buf: Uint8Array;
  len = 0;
  acc = 0;
  nbits = 0;

  constructor(capacity: number) {
    this.buf = new Uint8Array(Math.max(1024, capacity));
  }

  private reserve(n: number) {
    if (this.len + n <= this.buf.length) return;
    const next = new Uint8Array(Math.max(this.buf.length * 2, this.len + n));
    next.set(this.buf.subarray(0, this.len));
    this.buf = next;
  }

  /** Writes the low `n` bits of `value`; n is at most 16. */
  bits(value: number, n: number) {
    this.acc |= value << this.nbits;
    this.nbits += n;
    while (this.nbits >= 8) {
      this.reserve(1);
      this.buf[this.len++] = this.acc & 0xff;
      this.acc >>>= 8;
      this.nbits -= 8;
    }
  }

  align() {
    if (this.nbits > 0) this.bits(0, 8 - this.nbits);
  }

  bytes(src: Uint8Array) {
    this.reserve(src.length);
    this.buf.set(src, this.len);
    this.len += src.length;
  }

  result(): Uint8Array {
    this.align();
    return this.buf.subarray(0, this.len);
  }
}

/**
 * Optimal code lengths no longer than `limit` bits, by package-merge.
 *
 * Plain Huffman can produce codes longer than DEFLATE allows (15 bits, 7 for
 * the code-length code). Package-merge finds the best code under that cap
 * directly: each round pairs up the cheapest items into packages and merges
 * them back with the original symbols, and a symbol's code length is the
 * number of rounds it is chosen in.
 */
function codeLengths(freq: Uint32Array, limit: number): Uint8Array {
  const used: number[] = [];
  for (let s = 0; s < freq.length; s++) if (freq[s] > 0) used.push(s);
  // DEFLATE decoders reject a code with spare room, and a lone symbol leaves
  // half the tree empty. Two symbols of length 1 fill it exactly.
  for (let s = 0; used.length < 2; s++) if (!used.includes(s)) used.push(s);

  type Item = { w: number; syms: number[] };
  const leaves: Item[] = used
    .map((s) => ({ w: freq[s], syms: [s] }))
    .sort((a, b) => a.w - b.w || a.syms[0] - b.syms[0]);

  let current = leaves;
  for (let round = 1; round < limit; round++) {
    const packages: Item[] = [];
    for (let i = 0; i + 1 < current.length; i += 2) {
      packages.push({
        w: current[i].w + current[i + 1].w,
        syms: current[i].syms.concat(current[i + 1].syms),
      });
    }
    const merged: Item[] = [];
    let a = 0;
    let b = 0;
    while (a < leaves.length || b < packages.length) {
      if (b >= packages.length || (a < leaves.length && leaves[a].w <= packages[b].w)) {
        merged.push(leaves[a++]);
      } else {
        merged.push(packages[b++]);
      }
    }
    current = merged;
  }

  const lengths = new Uint8Array(freq.length);
  for (let i = 0; i < 2 * used.length - 2; i++) {
    for (const s of current[i].syms) lengths[s]++;
  }
  return lengths;
}

/** Canonical codes for the lengths, bit-reversed so they can be written LSB-first. */
function canonicalCodes(lengths: Uint8Array): Uint16Array {
  const maxBits = Math.max(...lengths);
  const count = new Uint16Array(maxBits + 1);
  for (const n of lengths) if (n) count[n]++;
  const next = new Uint16Array(maxBits + 2);
  let code = 0;
  for (let n = 1; n <= maxBits; n++) {
    code = (code + count[n - 1]) << 1;
    next[n] = code;
  }
  const codes = new Uint16Array(lengths.length);
  for (let s = 0; s < lengths.length; s++) {
    const n = lengths[s];
    if (!n) continue;
    let c = next[n]++;
    let rev = 0;
    for (let i = 0; i < n; i++) {
      rev = (rev << 1) | (c & 1);
      c >>= 1;
    }
    codes[s] = rev;
  }
  return codes;
}

/**
 * The run-length encoding DEFLATE applies to a block's code lengths: 16 repeats
 * the previous length 3-6 times, 17 and 18 send runs of zeros. Returns
 * [symbol, extra-bits value] pairs.
 */
function encodeLengths(lengths: number[]): [number, number][] {
  const out: [number, number][] = [];
  let i = 0;
  while (i < lengths.length) {
    const v = lengths[i];
    let run = 1;
    while (i + run < lengths.length && lengths[i + run] === v) run++;
    i += run;
    if (v === 0) {
      while (run >= 11) {
        const r = Math.min(run, 138);
        out.push([18, r - 11]);
        run -= r;
      }
      if (run >= 3) {
        out.push([17, run - 3]);
        run = 0;
      }
    } else {
      out.push([v, 0]);
      run--;
      while (run >= 3) {
        const r = Math.min(run, 6);
        out.push([16, r - 3]);
        run -= r;
      }
    }
    for (; run > 0; run--) out.push([v, 0]);
  }
  return out;
}

function lastUsed(lengths: Uint8Array, min: number): number {
  let n = lengths.length;
  while (n > min && lengths[n - 1] === 0) n--;
  return n;
}

/** LZ77 state that persists across blocks, so matches can reach back into earlier ones. */
class Matcher {
  data: Uint8Array;
  head = new Int32Array(HASH_SIZE).fill(-1);
  prev = new Int32Array(WINDOW);

  constructor(data: Uint8Array) {
    this.data = data;
  }

  private insert(pos: number) {
    const d = this.data;
    if (pos + 2 >= d.length) return;
    const h = ((d[pos] << 10) ^ (d[pos + 1] << 5) ^ d[pos + 2]) & (HASH_SIZE - 1);
    this.prev[pos & (WINDOW - 1)] = this.head[h];
    this.head[h] = pos;
  }

  /**
   * Tokens for data[start, end): a literal byte is stored as itself, a match
   * as (distance << 9) | length, which is always above 255.
   */
  tokens(start: number, end: number): Uint32Array {
    const d = this.data;
    const out = new Uint32Array(end - start);
    let n = 0;
    let i = start;
    while (i < end) {
      let best = 0;
      let bestDist = 0;
      const maxLen = Math.min(MAX_MATCH, end - i);
      if (maxLen >= MIN_MATCH && i + 2 < d.length) {
        const h = ((d[i] << 10) ^ (d[i + 1] << 5) ^ d[i + 2]) & (HASH_SIZE - 1);
        let cand = this.head[h];
        for (let chain = MAX_CHAIN; cand >= 0 && i - cand <= WINDOW && chain > 0; chain--) {
          // Checking the byte that would extend the best match first rejects
          // most candidates without a full comparison.
          if (d[cand + best] === d[i + best]) {
            let l = 0;
            while (l < maxLen && d[cand + l] === d[i + l]) l++;
            if (l > best) {
              best = l;
              bestDist = i - cand;
              if (l === maxLen) break;
            }
          }
          cand = this.prev[cand & (WINDOW - 1)];
        }
      }
      if (best >= MIN_MATCH) {
        out[n++] = (bestDist << 9) | best;
        for (let k = 0; k < best; k++) this.insert(i + k);
        i += best;
      } else {
        out[n++] = d[i];
        this.insert(i);
        i++;
      }
    }
    return out.subarray(0, n);
  }
}

function writeStored(w: BitWriter, data: Uint8Array, final: boolean) {
  let off = 0;
  do {
    const len = Math.min(MAX_STORED, data.length - off);
    const last = off + len === data.length;
    w.bits(final && last ? 1 : 0, 1);
    w.bits(0, 2);
    w.align();
    w.bits(len, 16);
    w.bits(~len & 0xffff, 16);
    w.bytes(data.subarray(off, off + len));
    off += len;
  } while (off < data.length);
}

/**
 * Writes the block with dynamic Huffman codes if that is at least a tenth
 * smaller than storing it, and stores it otherwise.
 */
function writeBlock(w: BitWriter, raw: Uint8Array, tokens: Uint32Array, final: boolean) {
  const litFreq = new Uint32Array(286);
  const distFreq = new Uint32Array(30);
  for (const t of tokens) {
    if (t < 256) {
      litFreq[t]++;
    } else {
      litFreq[257 + LENGTH_CODE[t & 0x1ff]]++;
      distFreq[DIST_CODE[t >>> 9]]++;
    }
  }
  litFreq[256] = 1; // end of block

  const litLens = codeLengths(litFreq, 15);
  const distLens = codeLengths(distFreq, 15);
  const hlit = lastUsed(litLens, 257);
  const hdist = lastUsed(distLens, 1);
  const header = encodeLengths([...litLens.subarray(0, hlit), ...distLens.subarray(0, hdist)]);

  const clFreq = new Uint32Array(19);
  for (const [s] of header) clFreq[s]++;
  const clLens = codeLengths(clFreq, 7);
  let hclen = 19;
  while (hclen > 4 && clLens[CL_ORDER[hclen - 1]] === 0) hclen--;

  // The exact size of the compressed block, to compare against storing it.
  let cost = 3 + 14 + 3 * hclen;
  for (const [s] of header) cost += clLens[s] + (CL_EXTRA[s] ?? 0);
  for (let s = 0; s < 286; s++) {
    cost += litFreq[s] * (litLens[s] + (s > 256 ? LENGTH_EXTRA[s - 257] : 0));
  }
  for (let s = 0; s < 30; s++) cost += distFreq[s] * (distLens[s] + DIST_EXTRA[s]);
  const storedCost = 8 * raw.length + 40 * Math.max(1, Math.ceil(raw.length / MAX_STORED));
  if (cost * 10 > storedCost * 9) {
    writeStored(w, raw, final);
    return;
  }

  const litCodes = canonicalCodes(litLens);
  const distCodes = canonicalCodes(distLens);
  const clCodes = canonicalCodes(clLens);

  w.bits(final ? 1 : 0, 1);
  w.bits(2, 2);
  w.bits(hlit - 257, 5);
  w.bits(hdist - 1, 5);
  w.bits(hclen - 4, 4);
  for (let i = 0; i < hclen; i++) w.bits(clLens[CL_ORDER[i]], 3);
  for (const [s, extra] of header) {
    w.bits(clCodes[s], clLens[s]);
    if (s >= 16) w.bits(extra, CL_EXTRA[s]);
  }

  for (const t of tokens) {
    if (t < 256) {
      w.bits(litCodes[t], litLens[t]);
      continue;
    }
    const len = t & 0x1ff;
    const dist = t >>> 9;
    const lc = LENGTH_CODE[len];
    w.bits(litCodes[257 + lc], litLens[257 + lc]);
    w.bits(len - LENGTH_BASE[lc], LENGTH_EXTRA[lc]);
    const dc = DIST_CODE[dist];
    w.bits(distCodes[dc], distLens[dc]);
    w.bits(dist - DIST_BASE[dc], DIST_EXTRA[dc]);
  }
  w.bits(litCodes[256], litLens[256]);
}

/** Raw DEFLATE (no zlib or gzip wrapper). */
export function deflateRaw(data: Uint8Array): Uint8Array {
  const w = new BitWriter(data.length / 4);
  if (data.length === 0) {
    writeStored(w, data, true);
    return w.result();
  }
  const matcher = new Matcher(data);
  for (let start = 0; start < data.length; start += BLOCK_SIZE) {
    const end = Math.min(data.length, start + BLOCK_SIZE);
    writeBlock(w, data.subarray(start, end), matcher.tokens(start, end), end === data.length);
  }
  return w.result();
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

/** CRC-32 as zlib computes it, so the server can check with zlib.crc32. */
export function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < data.length; i++) c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export const KWZ_MAGIC = "KWZ1";
const HEADER_SIZE = 16;

/** The KWZ1 container: a 16-byte header, then raw DEFLATE. */
export function pack(data: Uint8Array): Uint8Array {
  const body = deflateRaw(data);
  // A fresh, exactly-sized buffer, so it can be transferred out of a worker whole.
  const out = new Uint8Array(HEADER_SIZE + body.length);
  const view = new DataView(out.buffer);
  for (let i = 0; i < 4; i++) out[i] = KWZ_MAGIC.charCodeAt(i);
  view.setUint32(4, data.length, true);
  view.setUint32(8, crc32(data), true);
  view.setUint32(12, 0, true);
  out.set(body, HEADER_SIZE);
  return out;
}
