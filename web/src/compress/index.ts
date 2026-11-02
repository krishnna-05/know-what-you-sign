// Mirror MAX_UPLOAD_BYTES and MAX_PDF_BYTES in kwys/api/main.py: what may be
// sent, and how large the PDF may be once the server has unpacked it.
export const MAX_UPLOAD_MB = 25;
export const MAX_PDF_MB = 100;

// Typed PDFs are compressed inside already and shrink by a few percent at
// most. Sending those as they are spares the server a pointless decode.
const WORTH_IT = 0.9;

function packInWorker(data: ArrayBuffer): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      worker.terminate();
      resolve(event.data);
    };
    worker.onerror = (event) => {
      worker.terminate();
      reject(new Error(event.message));
    };
    worker.postMessage(data, [data]);
  });
}

/**
 * The PDF as it should be uploaded: compressed into a KWZ1 container when that
 * makes it meaningfully smaller, and untouched otherwise. Compression is only
 * an optimisation, so if it fails for any reason the original file is sent.
 */
export async function forUpload(file: File): Promise<Blob> {
  try {
    const packed = await packInWorker(await file.arrayBuffer());
    if (packed.byteLength <= file.size * WORTH_IT) {
      return new File([packed], file.name, { type: "application/octet-stream" });
    }
  } catch {
    // Fall through: the server accepts the plain PDF too.
  }
  return file;
}
