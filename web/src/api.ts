import type { AnalysisResult, Config } from "./types";

/** Anything the server refused, with the reason it gave. */
export class ApiError extends Error {}

async function unwrap<T>(res: Response): Promise<T> {
  if (res.ok) return res.json() as Promise<T>;
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // A non-JSON error body is not worth a second failure; keep the status.
  }
  throw new ApiError(detail);
}

export function fetchConfig(): Promise<Config> {
  return fetch("/api/config").then((r) => unwrap<Config>(r));
}

export interface AnalyseInput {
  file: File;
  role: string;
  domain: string;
  corpusVersion: string;
  city?: string;
  state?: string;
  semantic?: boolean;
}

export function analyse(input: AnalyseInput): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("role", input.role);
  form.append("domain", input.domain);
  form.append("corpus_version", input.corpusVersion);
  if (input.city) form.append("city", input.city);
  if (input.state) form.append("state", input.state);
  form.append("semantic", String(Boolean(input.semantic)));
  return fetch("/api/analyse", { method: "POST", body: form }).then((r) =>
    unwrap<AnalysisResult>(r),
  );
}
