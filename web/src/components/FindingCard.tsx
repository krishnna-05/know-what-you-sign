import { useState } from "react";
import type { Distribution, Finding } from "../types";
import { DistributionChart } from "./DistributionChart";

const SEVERITY: Record<string, { label: string; className: string }> = {
  high: { label: "Needs attention", className: "text-critical border-critical" },
  medium: { label: "Worth a look", className: "text-serious border-serious" },
  low: { label: "Minor", className: "text-muted border-line" },
};

/** Row of the evidence table, omitted entirely when there is nothing to say. */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 py-1">
      <dt className="text-muted">{label}</dt>
      <dd className="text-ink-2 m-0">{children}</dd>
    </div>
  );
}

export function FindingCard({
  finding,
  index,
  distribution,
}: {
  finding: Finding;
  index: number;
  distribution?: Distribution;
}) {
  const [open, setOpen] = useState(false);
  const sev = SEVERITY[finding.severity] ?? SEVERITY.low;
  const ev = finding.evidence;
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const unit = ev.term?.unit ? ` ${ev.term.unit}` : "";

  return (
    <article className="bg-card border border-line rounded-xl p-5 mb-4">
      <header className="flex items-start gap-3 flex-wrap">
        <h3 className="m-0 text-base font-semibold flex-1 min-w-0">
          {index}. {finding.headline}
        </h3>
        <span
          className={`text-[11px] uppercase tracking-wide font-semibold px-2 py-0.5 rounded-full border ${sev.className}`}
        >
          {sev.label}
        </span>
      </header>
      <p className="text-xs text-muted mt-1 mb-3">
        {ev.missingClause ? "not in the document" : `clause ${finding.clauseId}`}
      </p>

      <p className="text-[15px] leading-relaxed m-0">{finding.plainLanguage}</p>

      {distribution && ev.norm && (
        <div className="mt-4">
          <DistributionChart
            dist={distribution}
            norm={ev.norm}
            unit={ev.term?.unit ?? null}
          />
        </div>
      )}

      {finding.question && (
        <p className="mt-4 mb-0 px-3 py-2 border-l-2 border-accent bg-surface rounded-r text-[15px] italic">
          <span className="not-italic font-semibold text-accent">Ask: </span>
          {finding.question}
        </p>
      )}

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="mt-4 text-sm text-muted hover:text-ink-2 cursor-pointer bg-transparent border-0 p-0"
      >
        {open ? "▾" : "▸"} Show the working
      </button>

      {open && (
        <dl className="mt-3 text-sm border-t border-line pt-3 m-0">
          {ev.clauseText && (
            <blockquote className="border-l-2 border-line pl-3 my-0 mb-3 text-muted text-[13px] italic">
              {ev.clauseText.slice(0, 700)}
              {ev.clauseText.length > 700 ? "…" : ""}
            </blockquote>
          )}
          {ev.term && (
            <>
              <Row label="Extracted">
                {String(ev.term.value)} {ev.term.unit ?? ""}
              </Row>
              <Row label="Found as">“{ev.term.raw}”</Row>
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
            <Row label="Statute">
              {ev.anchor.source} —{" "}
              {ev.anchor.comparison === "max" ? "at most" : "at least"}{" "}
              {ev.anchor.value} {ev.anchor.unit.replace(/_/g, " ")}
              {ev.anchor.exceeded ? ", which yours is outside" : ""}
              {ev.anchor.note && (
                <span className="block text-muted">{ev.anchor.note}</span>
              )}
              {!ev.anchor.applies && (
                <span className="text-muted">
                  {" "}
                  — a model law your state has not adopted, so a reference point
                  rather than a rule that binds here
                </span>
              )}
            </Row>
          )}
          {ev.directionRationale && (
            <Row label="Why this direction">{ev.directionRationale}</Row>
          )}
        </dl>
      )}
    </article>
  );
}
