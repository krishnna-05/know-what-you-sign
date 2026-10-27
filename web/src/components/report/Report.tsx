import { useRef, useState } from "react";
import type { Diff, Report as ReportData } from "../../types";
import { FindingCard, SEVERITY } from "../FindingCard";
import {
  AlertIcon,
  ArrowLeftIcon,
  CheckCircleIcon,
  CompareIcon,
  InfoIcon,
  PrinterIcon,
  SpinnerIcon,
} from "../icons";
import { AskTab } from "./AskTab";
import { ChangesTab } from "./ChangesTab";
import { CostsTab } from "./CostsTab";
import { DatesTab } from "./DatesTab";
import { DocumentTab } from "./DocumentTab";
import { NegotiateTab } from "./NegotiateTab";
import { SharePanel } from "./SharePanel";

/** What was submitted, kept beside the result so the report can say what it is a report on. */
export interface Submitted {
  fileName: string;
  domain: string;
  domainLabel: string;
  roleLabel: string;
  city: string;
}

type TabKey = "changes" | "findings" | "document" | "costs" | "dates" | "ask" | "negotiate";

function Stat({ value, label, dot }: { value: number; label: string; dot?: string }) {
  return (
    <div className="px-5 py-4">
      <div className="flex items-center gap-1.5 text-xs text-muted">
        {dot && <span className={`size-1.5 rounded-full ${dot}`} />}
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

export function Report({
  report,
  diff,
  previousName,
  file,
  submitted,
  comparing,
  onBack,
  onCompare,
}: {
  report: ReportData;
  diff: Diff | null;
  previousName: string | null;
  file: File;
  submitted: Submitted;
  comparing: boolean;
  onBack: () => void;
  onCompare: (file: File) => void;
}) {
  const [tab, setTab] = useState<TabKey>(diff ? "changes" : "findings");
  const [focus, setFocus] = useState<string | null>(null);
  const compareInput = useRef<HTMLInputElement>(null);

  const high = report.findings.filter((f) => f.severity === "high").length;
  const medium = report.findings.filter((f) => f.severity === "medium").length;
  const notChecked = report.notChecked ?? [];
  const tos = submitted.domain === "consumer_tos";

  function showClause(id: string) {
    setFocus(id);
    setTab("document");
    window.scrollTo({ top: 0 });
  }

  const tabs: { key: TabKey; label: string; count?: number; show: boolean }[] = [
    { key: "changes", label: "Changes", show: Boolean(diff) },
    { key: "findings", label: "Findings", count: report.findings.length, show: true },
    { key: "document", label: "Document", show: true },
    { key: "costs", label: "Costs", show: Boolean(report.exposure) },
    { key: "dates", label: "Dates", show: !tos && report.timeline.events.length > 0 },
    { key: "ask", label: "Ask", show: true },
    { key: "negotiate", label: "Negotiate", show: !tos && report.findings.length > 0 },
  ];

  return (
    <section>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <button
            type="button"
            onClick={onBack}
            className="no-print inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink bg-transparent border-0 p-0 mb-3 cursor-pointer"
          >
            <ArrowLeftIcon /> New check
          </button>
          <h1 className="m-0 text-2xl font-semibold tracking-tight break-words">
            {submitted.fileName}
          </h1>
          <p className="m-0 mt-1 text-sm text-muted">
            {submitted.domainLabel} · <span className="capitalize">{submitted.roleLabel}</span> ·{" "}
            {report.pageCount} page{report.pageCount === 1 ? "" : "s"}
          </p>
        </div>
        <div className="no-print flex gap-2">
          <input
            ref={compareInput}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onCompare(f);
            }}
          />
          <button
            type="button"
            disabled={comparing}
            onClick={() => compareInput.current?.click()}
            className="inline-flex items-center gap-2 rounded-lg border border-line-strong bg-card px-3.5 py-2 text-sm font-medium text-ink hover:bg-surface-2 cursor-pointer disabled:opacity-50"
          >
            {comparing ? <SpinnerIcon /> : <CompareIcon />}
            {comparing ? "Comparing…" : "Compare revised draft"}
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            title="Save as PDF"
            aria-label="Save as PDF"
            className="inline-flex items-center rounded-lg border border-line-strong bg-card px-2.5 py-2 text-ink hover:bg-surface-2 cursor-pointer"
          >
            <PrinterIcon />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 divide-x divide-line bg-card border border-line rounded-xl shadow-sm mb-6">
        <Stat value={high} label="Needs attention" dot={SEVERITY.high.dot} />
        <Stat value={medium} label="Worth a look" dot={SEVERITY.medium.dot} />
        <Stat value={report.clausesChecked} label="Clauses reviewed" />
      </div>

      <nav
        role="tablist"
        className="no-print flex gap-1 overflow-x-auto border-b border-line mb-6 -mx-4 px-4 sm:mx-0 sm:px-0"
      >
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.key}
              role="tab"
              type="button"
              aria-selected={tab === t.key}
              onClick={() => {
                setTab(t.key);
                if (t.key !== "document") setFocus(null);
              }}
              className={`shrink-0 -mb-px border-0 border-b-2 bg-transparent px-3 py-2.5 text-sm font-medium cursor-pointer whitespace-nowrap ${
                tab === t.key
                  ? "border-accent text-ink"
                  : "border-transparent text-muted hover:text-ink-2"
              }`}
            >
              {t.label}
              {t.count !== undefined && (
                <span className="ml-1.5 rounded-full bg-surface-2 px-1.5 py-0.5 text-xs text-ink-2 tabular-nums">
                  {t.count}
                </span>
              )}
            </button>
          ))}
      </nav>

      {tab === "changes" && diff && (
        <ChangesTab diff={diff} previousName={previousName ?? "the previous draft"} onShowClause={showClause} />
      )}

      {tab === "findings" && (
        <div className="space-y-4">
          {report.warnings.length > 0 && (
            <div className="flex gap-3 rounded-xl border border-serious/30 bg-serious/6 px-4 py-3">
              <AlertIcon className="size-4 text-serious shrink-0 mt-0.5" />
              <ul className="m-0 p-0 list-none space-y-1 text-sm text-ink-2">
                {report.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {report.findings.length === 0 ? (
            <div className="bg-card border border-line rounded-xl shadow-sm p-8 text-center">
              <CheckCircleIcon className="size-8 text-ink-2 mx-auto" />
              <p className="m-0 mt-3 font-semibold">No unusual clauses found</p>
              <p className="text-sm text-muted mt-1 mb-0">
                This covers only the terms this tool can measure. Still read the
                whole agreement.
              </p>
            </div>
          ) : (
            report.findings.map((f, i) => (
              <FindingCard
                key={`${f.clauseId}-${i}`}
                finding={f}
                onShowClause={showClause}
                distribution={
                  f.evidence.field ? report.distributions[f.evidence.field] : undefined
                }
              />
            ))
          )}

          {notChecked.length > 0 && (
            <div className="bg-card border border-line rounded-xl shadow-sm">
              <div className="px-5 sm:px-6 pt-5 pb-3">
                <h2 className="m-0 text-base font-semibold">Not assessed</h2>
                <p className="text-sm text-muted mt-1 mb-0">
                  No reference data covers these terms. Review them yourself.
                </p>
              </div>
              <ul className="m-0 p-0 list-none">
                {notChecked.map((u) => (
                  <li
                    key={`${u.clauseId}-${u.label}`}
                    className="flex items-baseline justify-between gap-4 border-t border-line px-5 sm:px-6 py-3 text-sm"
                  >
                    <span className="text-ink-2">{u.label}</span>
                    <span className="text-right">
                      <span className="font-medium tabular-nums">{u.value}</span>
                      <span className="text-muted text-xs ml-2">Clause {u.clauseId}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <SharePanel
            domain={submitted.domain}
            city={submitted.city}
            figures={report.shareable}
          />

          {(report.corpusLabel || report.corpusBias) && (
            <p className="flex gap-2 text-xs text-muted pt-4 m-0 leading-relaxed">
              <InfoIcon className="size-3.5 shrink-0 mt-px" />
              <span>
                {report.corpusLabel && (
                  <>Compared against {report.corpusLabel.toLowerCase()}. </>
                )}
                {report.corpusBias}
              </span>
            </p>
          )}
        </div>
      )}

      {tab === "document" && <DocumentTab report={report} file={file} focus={focus} />}

      {tab === "costs" && <CostsTab exposure={report.exposure} onShowClause={showClause} />}

      {tab === "dates" && (
        <DatesTab timeline={report.timeline} title={submitted.fileName} onShowClause={showClause} />
      )}

      {tab === "ask" && (
        <AskTab domain={submitted.domain} clauses={report.clauses} onShowClause={showClause} />
      )}

      {tab === "negotiate" && <NegotiateTab report={report} domain={submitted.domain} />}
    </section>
  );
}
