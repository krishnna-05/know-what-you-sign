import type { AskResult, Clause, Config, Diff, Report } from "./types";

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
  /** Empty means "the server's default corpus". */
  corpusVersion: string;
  city?: string;
  state?: string;
}

function contextFields(form: FormData, input: Omit<AnalyseInput, "file">) {
  form.append("role", input.role);
  form.append("domain", input.domain);
  if (input.corpusVersion) form.append("corpus_version", input.corpusVersion);
  if (input.city) form.append("city", input.city);
  if (input.state) form.append("state", input.state);
}

export function analyse(input: AnalyseInput): Promise<Report> {
  const form = new FormData();
  form.append("file", input.file);
  contextFields(form, input);
  return fetch("/api/analyse", { method: "POST", body: form }).then((r) =>
    unwrap<Report>(r),
  );
}

/** Two drafts of one agreement: the new draft's report, and what changed. */
export function compare(
  input: Omit<AnalyseInput, "file">,
  oldFile: File,
  newFile: File,
): Promise<{ report: Report; diff: Diff }> {
  const form = new FormData();
  form.append("old_file", oldFile);
  form.append("new_file", newFile);
  contextFields(form, input);
  return fetch("/api/compare", { method: "POST", body: form }).then((r) =>
    unwrap<{ report: Report; diff: Diff }>(r),
  );
}

/** The server keeps no copy of the document, so the clauses travel with the question. */
export function ask(question: string, domain: string, clauses: Clause[]): Promise<AskResult> {
  return fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      domain,
      clauses: clauses.map((c) => ({ id: c.id, text: c.text, type: c.type })),
    }),
  }).then((r) => unwrap<AskResult>(r));
}

export function contribute(
  domain: string,
  city: string | undefined,
  figures: { key: string; value: number }[],
): Promise<{ stored: boolean; duplicate: boolean }> {
  return fetch("/api/contribute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain, city: city || null, figures }),
  }).then((r) => unwrap<{ stored: boolean; duplicate: boolean }>(r));
}
