import { useState } from "react";
import type { Distribution, Finding } from "../types";
import { DistributionChart } from "./DistributionChart";
import { ChevronIcon, QuestionIcon } from "./icons";

export const SEVERITY: Record<string, { label: string; text: string; edge: string; dot: string }> = {
  high: {
    label: "Needs attention",
    text: "text-critical",
    edge: "border-l-critical",
    dot: "bg-critical",
  },
  medium: {
    label: "Worth a look",
    text: "text-serious",
    edge: "border-l-serious",
    dot: "bg-serious",
  },
  low: { label: "Minor", text: "text-muted", edge: "border-l-line-strong", dot: "bg-muted" },
};

/** Row of the evidence table, omitted entirely when there is nothing to say. */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid sm:grid-cols-[9rem_1fr] gap-x-4 gap-y-0.5 py-2 border-b border-line last:border-b-0">
      <dt className="text-muted text-xs sm:text-sm">{label}</dt>
      <dd className="text-ink-2 m-0">{children}</dd>
    </div>
  );
}

export function FindingCard({
  finding,
  distribution,
  onShowClause,
}: {
  finding: Finding;
  distribution?: Distribution;
  onShowClause?: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const sev = SEVERITY[finding.severity] ?? SEVERITY.low;
  const ev = finding.evidence;
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const unit = ev.term?.unit ? ` ${ev.term.unit}` : "";

  return (
    <article
      className={`bg-card border border-line border-l-4 ${sev.edge} rounded-xl shadow-sm`}
    >
      <div className="p-5 sm:p-6">
        <div className="flex items-center justify-between gap-3 mb-2">
          <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${sev.text}`}>
            <span className={`size-1.5 rounded-full ${sev.dot}`} />
            {sev.label}
          </span>
          {ev.missingClause || !onShowClause ? (
            <span className="text-xs text-muted tabular-nums">
              {ev.missingClause ? "Missing from document" : `Clause ${finding.clauseId}`}
            </span>
          ) : (
            <button
              type="button"
              onClick={() => onShowClause(finding.clauseId)}
              title="Show in document"
              className="text-xs text-accent hover:underline tabular-nums bg-transparent border-0 p-0 cursor-pointer"
            >
              Clause {finding.clauseId}
            </button>
          )}
        </div>

        <h3 className="m-0 text-base sm:text-lg font-semibold leading-snug">
          {finding.headline}
        </h3>
        <p className="text-[15px] leading-relaxed text-ink-2 mt-2 mb-0">
          {finding.plainLanguage}
        </p>

        {distribution && ev.norm && (
          <div className="mt-5 rounded-lg border border-line p-4">
            <DistributionChart
              dist={distribution}
              norm={ev.norm}
              unit={ev.term?.unit ?? null}
            />
          </div>
        )}

        {finding.question && (
          <div className="mt-5 flex gap-3 rounded-lg bg-accent/6 px-4 py-3">
            <QuestionIcon className="size-5 text-accent shrink-0 mt-px" />
            <div>
              <p className="m-0 text-xs font-semibold uppercase tracking-wide text-accent">
                What to ask
              </p>
              <p className="m-0 mt-0.5 text-[15px] text-ink">{finding.question}</p>
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="no-print w-full flex items-center gap-1.5 border-0 border-t border-line bg-transparent px-5 sm:px-6 py-3 text-sm text-ink-2 hover:text-ink hover:bg-surface-2/60 cursor-pointer rounded-b-xl text-left"
      >
        <ChevronIcon className={`size-4 transition-transform ${open ? "rotate-90" : ""}`} />
        {open ? "Hide evidence" : "View evidence"}
      </button>

      {open && (
        <dl className="m-0 px-5 sm:px-6 pb-5 text-sm">
          {ev.clauseText && (
            <blockquote className="m-0 mb-3 rounded-lg bg-surface-2 px-4 py-3 text-[13px] leading-relaxed text-ink-2">
              {ev.clauseText.slice(0, 700)}
              {ev.clauseText.length > 700 ? "…" : ""}
            </blockquote>
          )}
          {ev.term && (
            <>
              <Row label="Value found">
                {String(ev.term.value)} {ev.term.unit ?? ""}
              </Row>
              <Row label="Wording">“{ev.term.raw}”</Row>
            </>
          )}
          {ev.norm && (
            <>
              <Row label="Typical">
                {ev.norm.median}
                {unit}
              </Row>
              <Row label="Percentile">
                {pct(ev.norm.percentile)}{" "}
                <span className="text-muted">
                  (95% CI {pct(ev.norm.ciLow)}–{pct(ev.norm.ciHigh)})
                </span>
              </Row>
              <Row label="Compared with">{ev.norm.n} agreements</Row>
            </>
          )}
          {ev.venueDistanceKm !== null && (
            <Row label="Distance">{Math.round(ev.venueDistanceKm)} km from you</Row>
          )}
          {ev.unfairTypes.length > 0 && (
            <Row label="Category">{ev.unfairTypes.join(", ")}</Row>
          )}
          {ev.anchor && (
            <Row label="Law">
              {ev.anchor.source} —{" "}
              {ev.anchor.comparison === "max" ? "at most" : "at least"}{" "}
              {ev.anchor.value} {ev.anchor.unit.replace(/_/g, " ")}
              {ev.anchor.exceeded ? ", which yours is outside" : ""}
              {ev.anchor.note && (
                <span className="block text-muted">{ev.anchor.note}</span>
              )}
              {!ev.anchor.applies && (
                <span className="block text-muted">
                  Not adopted in your state, so a reference point rather than a
                  binding rule.
                </span>
              )}
            </Row>
          )}
          {ev.ruleBasis && <Row label="Basis">{ev.ruleBasis}</Row>}
          {ev.directionRationale && (
            <Row label="Why it matters">{ev.directionRationale}</Row>
          )}
        </dl>
      )}
    </article>
  );
}
