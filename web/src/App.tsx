import { useEffect, useState } from "react";
import { analyse, compare, fetchConfig, type AnalyseInput } from "./api";
import { AlertIcon, LogoMark, SpinnerIcon } from "./components/icons";
import { Report, type Submitted } from "./components/report/Report";
import { UploadForm, type FormState } from "./components/UploadForm";
import type { Config, Diff, Report as ReportData } from "./types";

interface Shown {
  report: ReportData;
  diff: Diff | null;
  previousName: string | null;
  file: File;
  submitted: Submitted;
  /** What the report was run with, so a revised draft is checked the same way. */
  context: Omit<AnalyseInput, "file">;
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const [busy, setBusy] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch(() => setError("The service is unavailable right now. Please try again shortly."));
  }, []);

  function describe(state: FormState & { file: File }): Submitted {
    const domain = config?.domains.find((d) => d.value === state.domain);
    const role = domain?.roles.find((r) => r.value === state.role);
    return {
      fileName: state.file.name,
      domain: state.domain,
      domainLabel: domain?.label ?? state.domain,
      roleLabel: role?.hint ?? state.role,
      city: state.city,
    };
  }

  async function run(state: FormState & { file: File }) {
    setBusy(true);
    setError(null);
    try {
      const report = await analyse(state);
      const { file, ...context } = state;
      setShown({
        report,
        diff: null,
        previousName: null,
        file,
        submitted: describe(state),
        context,
      });
      window.scrollTo({ top: 0 });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runCompare(newFile: File) {
    if (!shown) return;
    setComparing(true);
    setError(null);
    try {
      const { report, diff } = await compare(shown.context, shown.file, newFile);
      setShown({
        ...shown,
        report,
        diff,
        previousName: shown.submitted.fileName,
        file: newFile,
        submitted: { ...shown.submitted, fileName: newFile.name },
      });
      window.scrollTo({ top: 0 });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setComparing(false);
    }
  }

  return (
    <div className="min-h-dvh flex flex-col">
      <header className="no-print border-b border-line bg-card/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center">
          <button
            type="button"
            onClick={() => setShown(null)}
            className="flex items-center gap-2.5 bg-transparent border-0 p-0 cursor-pointer text-ink"
          >
            <LogoMark />
            <span className="font-semibold tracking-tight">Know What You Sign</span>
          </button>
        </div>
      </header>

      <main className="flex-1 w-full max-w-3xl mx-auto px-4 py-10 sm:py-14">
        {error && (
          <div
            role="alert"
            className="flex gap-3 rounded-xl border border-critical/30 bg-critical/6 px-4 py-3 mb-6 text-sm text-critical"
          >
            <AlertIcon className="size-4 shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {!config && !error && (
          <div className="flex justify-center py-24 text-muted">
            <SpinnerIcon className="size-6" />
          </div>
        )}

        {/* Kept mounted behind the report, so "New check" returns to the same
            inputs - checking the other side of the same agreement is common. */}
        {config && (
          <div hidden={!!shown}>
            <div className="mb-8">
              <h1 className="m-0 text-3xl sm:text-[2rem] font-semibold tracking-tight">
                Check an agreement before you sign
              </h1>
              <p className="text-ink-2 mt-2 mb-0">
                Find unusual or one-sided clauses, and what to ask about them.
              </p>
            </div>
            <UploadForm config={config} busy={busy} onSubmit={run} />
          </div>
        )}

        {shown && (
          <Report
            // A new report (or a new draft) starts on its own first tab.
            key={`${shown.submitted.fileName}-${shown.previousName ?? ""}`}
            report={shown.report}
            diff={shown.diff}
            previousName={shown.previousName}
            file={shown.file}
            submitted={shown.submitted}
            comparing={comparing}
            onBack={() => setShown(null)}
            onCompare={runCompare}
          />
        )}
      </main>

      <footer className="border-t border-line">
        <p className="max-w-3xl mx-auto px-4 py-5 m-0 text-xs text-muted">
          Flags unusual terms by comparison with other agreements. It does not
          assess whether a clause is lawful or enforceable, and is not legal
          advice.
        </p>
      </footer>
    </div>
  );
}
