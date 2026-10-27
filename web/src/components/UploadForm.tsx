import { useRef, useState } from "react";
import type { Config, DomainOption } from "../types";
import { FileIcon, LockIcon, SpinnerIcon, UploadIcon } from "./icons";

// Mirrors MAX_UPLOAD_BYTES in kwys/api/main.py.
const MAX_UPLOAD_MB = 25;

export interface FormState {
  domain: string;
  role: string;
  corpusVersion: string;
  city: string;
  state: string;
  file: File | null;
}

const input =
  "w-full bg-card border border-line-strong rounded-lg px-3 py-2.5 text-sm text-ink " +
  "placeholder:text-muted hover:border-ink-2/40 transition-colors";

function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-medium text-ink mb-1.5">
      {children}
    </label>
  );
}

export function UploadForm({
  config,
  busy,
  onSubmit,
}: {
  config: Config;
  busy: boolean;
  onSubmit: (s: FormState & { file: File }) => void;
}) {
  const [domain, setDomain] = useState(config.domains[0]?.value ?? "");
  const current: DomainOption | undefined = config.domains.find((d) => d.value === domain);
  // The weaker party is the default because it is who this tool exists for -
  // but it is a visible choice, never an assumption, since every risk
  // direction in the report depends on it.
  const [role, setRole] = useState(current?.weakerParty ?? "");
  // The server lists real corpora first, so the first is the honest default.
  // Empty when none is built: the server then runs without comparisons.
  const [corpusVersion, setCorpusVersion] = useState(
    current?.corpora[0]?.version ?? "",
  );
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function pickDomain(value: string) {
    setDomain(value);
    const next = config.domains.find((d) => d.value === value);
    setRole(next?.weakerParty ?? "");
    setCorpusVersion(next?.corpora[0]?.version ?? "");
  }

  // Checked here as well as on the server so a wrong file is caught before the
  // wait, not after it.
  function pickFile(f: File | null) {
    if (f && !/\.pdf$/i.test(f.name) && f.type !== "application/pdf") {
      setFile(null);
      setFileError(`${f.name} is not a PDF.`);
      return;
    }
    if (f && f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setFile(null);
      setFileError(`${f.name} is larger than ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    setFileError(null);
    setFile(f);
  }

  const corpora = current?.corpora ?? [];
  const corpus = corpora.find((c) => c.version === corpusVersion);
  const isTos = domain === "consumer_tos";

  return (
    <form
      className="bg-card border border-line rounded-2xl shadow-sm"
      onSubmit={(e) => {
        e.preventDefault();
        // City and state are only asked for agreements where they mean
        // something; never send values left over from another agreement type.
        if (file)
          onSubmit({
            domain,
            role,
            corpusVersion,
            city: isTos ? "" : city.trim(),
            state: isTos ? "" : state.trim(),
            file,
          });
      }}
    >
      <div className="p-6 sm:p-8 space-y-6">
        <div>
          <Label htmlFor="domain">Agreement type</Label>
          <select
            id="domain"
            value={domain}
            onChange={(e) => pickDomain(e.target.value)}
            className={`${input} select`}
          >
            {config.domains.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </div>

        <fieldset className="border-0 p-0 min-w-0">
          <legend className="text-sm font-medium text-ink mb-1.5 p-0">You are</legend>
          <div className="grid sm:grid-cols-2 gap-2">
            {current?.roles.map((r) => {
              const on = role === r.value;
              return (
                <label
                  key={r.value}
                  className={`flex items-start gap-3 cursor-pointer rounded-lg border px-3.5 py-3 transition-colors ${
                    on
                      ? "border-accent bg-accent/5 ring-1 ring-accent"
                      : "border-line-strong hover:border-ink-2/40"
                  }`}
                >
                  <input
                    type="radio"
                    name="role"
                    value={r.value}
                    checked={on}
                    onChange={() => setRole(r.value)}
                    className="sr-only"
                  />
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 size-4 shrink-0 rounded-full border-2 ${
                      on ? "border-accent border-[5px]" : "border-line-strong"
                    }`}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{r.label}</span>
                    <span className="block text-xs text-muted capitalize">{r.hint}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        {/* A choice of one is not a choice: only offer it when there is one. */}
        {!isTos && corpora.length > 1 && (
          <div>
            <Label htmlFor="corpus">Compare against</Label>
            <select
              id="corpus"
              value={corpusVersion}
              onChange={(e) => setCorpusVersion(e.target.value)}
              className={`${input} select`}
            >
              {corpora.map((c) => (
                <option key={c.version} value={c.version}>
                  {c.label ?? c.version}
                </option>
              ))}
            </select>
          </div>
        )}

        {corpus?.synthetic && (
          <p className="m-0 text-sm text-critical bg-critical/8 border border-critical/30 rounded-lg px-3 py-2">
            Demo data: the comparisons in this report will not be real.
          </p>
        )}

        {!isTos && (
          <div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="city">
                  City <span className="text-muted font-normal">(optional)</span>
                </Label>
                <input
                  id="city"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  placeholder="Bengaluru"
                  autoComplete="address-level2"
                  className={input}
                />
              </div>
              <div>
                <Label htmlFor="state">
                  State <span className="text-muted font-normal">(optional)</span>
                </Label>
                <input
                  id="state"
                  value={state}
                  onChange={(e) => setState(e.target.value)}
                  placeholder="Karnataka"
                  autoComplete="address-level1"
                  className={input}
                />
              </div>
            </div>
            <p className="text-xs text-muted mt-1.5 mb-0">
              Used to check dispute venues and which local laws apply.
            </p>
          </div>
        )}

        <div>
          <Label>Document</Label>
          <div
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) pickFile(dropped);
            }}
            onClick={() => inputRef.current?.click()}
            className={`rounded-xl border border-dashed px-4 cursor-pointer transition-colors ${
              dragging
                ? "border-accent bg-accent/5"
                : file
                  ? "border-line-strong bg-surface-2"
                  : "border-line-strong hover:border-ink-2/40 hover:bg-surface-2"
            } ${file ? "py-4" : "py-9"}`}
          >
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
            {file ? (
              <div className="flex items-center gap-3">
                <span className="grid place-items-center size-10 rounded-lg bg-card border border-line text-accent shrink-0">
                  <FileIcon className="size-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium truncate">{file.name}</span>
                  <span className="block text-xs text-muted">
                    {(file.size / 1024).toFixed(0)} KB
                  </span>
                </span>
                <span className="text-sm text-accent font-medium shrink-0">Change</span>
              </div>
            ) : (
              <div className="text-center">
                <span className="mx-auto mb-3 grid place-items-center size-10 rounded-full bg-surface-2 text-ink-2">
                  <UploadIcon className="size-5" />
                </span>
                <p className="m-0 text-sm">
                  <span className="font-medium text-accent">Choose a PDF</span>{" "}
                  <span className="text-ink-2">or drag it here</span>
                </p>
                <p className="text-xs text-muted mt-1 mb-0">Up to {MAX_UPLOAD_MB} MB</p>
              </div>
            )}
          </div>
          {fileError && (
            <p className="text-sm text-critical mt-2 mb-0" role="alert">
              {fileError}
            </p>
          )}
        </div>
      </div>

      <div className="border-t border-line px-6 sm:px-8 py-4 flex flex-col-reverse sm:flex-row sm:items-center gap-3 sm:justify-between bg-surface-2/50 rounded-b-2xl">
        <p className="m-0 flex items-center gap-1.5 text-xs text-muted">
          <LockIcon className="size-3.5 shrink-0" />
          Your document is deleted as soon as the analysis finishes.
        </p>
        <button
          type="submit"
          disabled={!file || busy}
          className="inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium bg-accent text-accent-ink hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer border-0 transition"
        >
          {busy && <SpinnerIcon />}
          {busy ? "Analysing…" : "Analyse agreement"}
        </button>
      </div>
    </form>
  );
}
