import { useEffect, useState } from "react";
import { analyse, fetchConfig } from "./api";
import { FindingCard } from "./components/FindingCard";
import { UploadForm, type FormState } from "./components/UploadForm";
import type { AnalysisResult, Config } from "./types";

const DISCLAIMER =
  "This is a triage tool, not legal advice. It tells you which clauses are " +
  "unusual compared with other agreements — not whether they are lawful or " +
  "enforceable. For anything that matters, ask a lawyer.";

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div>
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch((e) => setError(`Could not reach the analyser: ${e.message}`));
  }, []);

  async function run(state: FormState & { file: File }) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await analyse(state));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const high = result?.findings.filter((f) => f.severity === "high").length ?? 0;
  const medium = result?.findings.filter((f) => f.severity === "medium").length ?? 0;

  return (
    <div className="min-h-dvh">
      <main className="max-w-3xl mx-auto px-4 py-10 sm:py-14">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold m-0">Know What You Sign</h1>
          <p className="text-ink-2 mt-2 mb-0 max-w-prose">
            Upload an agreement. This tells you which clauses are unusual
            compared with other agreements — and which questions to ask before
            you sign.
          </p>
        </header>

        {error && (
          <p className="border border-critical text-critical rounded-lg px-4 py-3 mb-6 text-sm">
            {error}
          </p>
        )}

        {!config && !error && <p className="text-muted">Starting up…</p>}

        {config && <UploadForm config={config} busy={busy} onSubmit={run} />}

        {result && (
          <section className="mt-10">
            <div className="flex gap-10 border-b border-line pb-6 mb-6">
              <Stat value={result.clausesChecked} label="clauses checked" />
              <Stat value={high} label="need attention" />
              <Stat value={medium} label="worth a look" />
            </div>

            <p className="text-xs text-muted -mt-3 mb-5">
              {result.pageCount} page{result.pageCount === 1 ? "" : "s"}
              {result.wasOcred &&
                " · read from a scan, so check each quoted figure against your copy"}
              {result.corpusLabel &&
                ` · compared against ${result.corpusLabel.toLowerCase()}`}
            </p>

            {result.warnings.map((w) => (
              <p
                key={w}
                className="text-sm text-ink-2 border-l-2 border-serious bg-card px-3 py-2 rounded-r mb-3"
              >
                {w}
              </p>
            ))}

            {result.findings.length === 0 ? (
              <div className="bg-card border border-line rounded-xl p-5">
                <p className="m-0 font-medium">Nothing stood out.</p>
                <p className="text-sm text-muted mt-2 mb-0">
                  That is not the same as saying this contract is fine — only
                  that nothing fell outside the range this tool can check.
                </p>
              </div>
            ) : (
              result.findings.map((f, i) => (
                <FindingCard
                  key={`${f.clauseId}-${i}`}
                  finding={f}
                  index={i + 1}
                  distribution={
                    f.evidence.field
                      ? result.distributions[f.evidence.field]
                      : undefined
                  }
                />
              ))
            )}

            {(result.notChecked?.length ?? 0) > 0 && (
              <div className="border border-line rounded-xl p-5 mt-6">
                <p className="m-0 font-medium">Found, but not checked</p>
                <p className="text-sm text-muted mt-1 mb-3">
                  There is no comparison data, law or rule for these yet, so
                  this report cannot say whether they are fair. Read them
                  yourself.
                </p>
                <ul className="m-0 pl-5 text-sm text-ink-2">
                  {result.notChecked!.map((u) => (
                    <li key={`${u.clauseId}-${u.label}`}>
                      {u.label}: {u.value}{" "}
                      <span className="text-muted">(clause {u.clauseId})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-xs text-muted border-t border-line pt-5 mt-8">
              {DISCLAIMER}
            </p>
          </section>
        )}

        {config && !result && (
          <aside className="mt-10 text-sm text-muted">
            <p className="mb-1">
              <strong className="text-ink-2">How it works.</strong> It compares
              each clause against what is normal across a body of real
              agreements. A term far outside that range is objectively unusual,
              and every flag shows the evidence behind it.
            </p>
            <p className="mb-1">
              It does not decide whether a clause is legal or enforceable, and
              it is not a substitute for a lawyer.
            </p>
            <p className="m-0">
              Clauses are recognised by{" "}
              {config.capabilities.clauseClassifier === "trained"
                ? "a trained model"
                : "keyword rules"}
              ; unfair terms-of-service clauses by{" "}
              {config.capabilities.unfairDetector === "trained"
                ? "a model trained on expert annotations"
                : "keyword rules, which miss a good share of what an expert would flag"}
              .
            </p>
          </aside>
        )}
      </main>
    </div>
  );
}
