// Compression runs here rather than on the page, so a large scan does not
// freeze the interface while it is packed.
import { pack } from "./kwz";

self.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  const packed = pack(new Uint8Array(event.data));
  self.postMessage(packed.buffer, { transfer: [packed.buffer] });
};
