import { useRef, useState } from "react";
import type { Config, DomainOption } from "../types";

export interface FormState {
  domain: string;
  role: string;
  corpusVersion: string;
  city: string;
  state: string;
  file: File | null;
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
  const [corpusVersion, setCorpusVersion] = useState(
    current?.corpora[0]?.version ?? "v1",
  );
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function pickDomain(value: string) {
    setDomain(value);
    const next = config.domains.find((d) => d.value === value);
    setRole(next?.weakerParty ?? "");
    setCorpusVersion(next?.corpora[0]?.version ?? "v1");
  }

  const corpus = current?.corpora.find((c) => c.version === corpusVersion);
  const isTos = domain === "consumer_tos";

  return (
    <form
      className="bg-card border border-line rounded-xl p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (file) onSubmit({ domain, role, corpusVersion, city, state, file });
      }}
    >
      <label className="block text-sm font-medium mb-1">
        What kind of agreement is this?
      </label>
      <select
        value={domain}
        onChange={(e) => pickDomain(e.target.value)}
        className="w-full bg-surface border border-line rounded-lg px-3 py-2 mb-5 text-ink"
      >
        {config.domains.map((d) => (
          <option key={d.value} value={d.value}>
            {d.label}
          </option>
        ))}
      </select>

      <fieldset className="border-0 p-0 m-0 mb-5">
        <legend className="text-sm font-medium mb-1 p-0">Which side are you on?</legend>
        <p className="text-xs text-muted mt-0 mb-2">
          Every risk in this report depends on this. A long notice period is a
          burden for whoever has to give it.
        </p>
        <div className="flex gap-2 flex-wrap">
          {current?.roles.map((r) => (
            <label
              key={r.value}
              className={`flex-1 min-w-[160px] cursor-pointer border rounded-lg px-3 py-2 ${
                role === r.value
                  ? "border-accent bg-surface"
                  : "border-line hover:border-ink-2"
              }`}
            >
              <input
                type="radio"
                name="role"
                value={r.value}
                checked={role === r.value}
                onChange={() => setRole(r.value)}
                className="sr-only"
              />
              <span className="block text-sm font-medium">{r.label}</span>
              <span className="block text-xs text-muted">{r.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {!isTos && (current?.corpora.length ?? 0) > 0 && (
        <>
          <label className="block text-sm font-medium mb-1">Compare against</label>
          <select
            value={corpusVersion}
            onChange={(e) => setCorpusVersion(e.target.value)}
            className="w-full bg-surface border border-line rounded-lg px-3 py-2 text-ink"
          >
            {current?.corpora.map((c) => (
              <option key={c.version} value={c.version}>
                {c.version} — {c.usable} field{c.usable === 1 ? "" : "s"} usable
                {c.synthetic ? " (synthetic demo data)" : ""}
              </option>
            ))}
          </select>
          {corpus?.synthetic && (
            <p className="mt-2 mb-0 text-sm text-critical border border-critical rounded-lg px-3 py-2">
              <strong>These numbers are invented.</strong> This corpus exists to
              show the pipeline works; it says nothing about real agreements.
            </p>
          )}
          <div className="h-5" />
        </>
      )}

      {!isTos && (current?.corpora.length ?? 0) === 0 && (
        <p className="text-sm text-serious border border-serious rounded-lg px-3 py-2 mb-5">
          No reference data is built for this kind of agreement yet, so nothing
          can be compared against what is normal. One-sided obligations and
          missing clauses will still be reported.
        </p>
      )}

      {!isTos && (
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div>
            <label className="block text-sm font-medium mb-1">
              Your city <span className="text-muted font-normal">(optional)</span>
            </label>
            <input
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="Bengaluru"
              className="w-full bg-surface border border-line rounded-lg px-3 py-2 text-ink"
            />
            <p className="text-xs text-muted mt-1 mb-0">
              Lets us check how far away any dispute would have to be heard.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">
              Your state <span className="text-muted font-normal">(optional)</span>
            </label>
            <input
              value={state}
              onChange={(e) => setState(e.target.value)}
              placeholder="Karnataka"
              className="w-full bg-surface border border-line rounded-lg px-3 py-2 text-ink"
            />
            <p className="text-xs text-muted mt-1 mb-0">
              Decides whether a statutory cap actually binds where you are.
            </p>
          </div>
        </div>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const dropped = e.dataTransfer.files?.[0];
          if (dropped) setFile(dropped);
        }}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl px-4 py-8 text-center cursor-pointer transition-colors ${
          dragging ? "border-accent bg-surface" : "border-line hover:border-ink-2"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="sr-only"
        />
        {file ? (
          <p className="m-0 text-sm">
            <strong>{file.name}</strong>{" "}
            <span className="text-muted">
              ({(file.size / 1024).toFixed(0)} KB) — click to change
            </span>
          </p>
        ) : (
          <p className="m-0 text-sm text-muted">
            Drop the agreement here, or click to choose a PDF
          </p>
        )}
      </div>

      <button
        type="submit"
        disabled={!file || busy}
        className="mt-4 w-full rounded-lg px-4 py-2.5 font-medium bg-accent text-white disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer border-0"
      >
        {busy ? "Reading the document…" : "Check this agreement"}
      </button>

      <p className="text-xs text-muted text-center mt-3 mb-0">
        Analysed on this machine. Your document is never stored.
      </p>
    </form>
  );
}
