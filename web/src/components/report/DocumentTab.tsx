import { lazy, Suspense, useState } from "react";
import type { Report } from "../../types";
import { SEVERITY } from "../FindingCard";
import type { Highlight } from "../PdfViewer";
import { SpinnerIcon } from "../icons";

// pdf.js is most of a megabyte: loaded only when someone opens this tab.
const PdfViewer = lazy(() => import("../PdfViewer"));

export function DocumentTab({
  report,
  file,
  focus,
}: {
  report: Report;
  file: File;
  focus: string | null;
}) {
  const [selected, setSelected] = useState<string | null>(focus);
  const byId = new Map(report.clauses.map((c) => [c.id, c]));

  const highlights: Highlight[] = [];
  const flagged = new Set<string>();
  for (const f of report.findings) {
    const c = byId.get(f.clauseId);
    if (!c || flagged.has(c.id)) continue;
    flagged.add(c.id);
    highlights.push({ clauseId: c.id, spans: c.spans, tone: f.severity, title: f.headline });
  }
  // A clause opened from elsewhere - an answer, a date - that drew no finding.
  if (focus && !flagged.has(focus) && byId.get(focus)) {
    highlights.push({ clauseId: focus, spans: byId.get(focus)!.spans, tone: "answer", title: "" });
  }

  const current = selected ? report.findings.filter((f) => f.clauseId === selected) : [];

  return (
    <div>
      <div className="sticky top-14 z-[5] -mx-4 px-4 py-2 bg-surface/90 backdrop-blur mb-3">
        {current.length > 0 ? (
          <div className="bg-card border border-line rounded-xl shadow-sm px-4 py-3">
            {current.map((f, i) => {
              const sev = SEVERITY[f.severity] ?? SEVERITY.low;
              return (
                <div key={i} className={i ? "mt-2 pt-2 border-t border-line" : ""}>
                  <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${sev.text}`}>
                    <span className={`size-1.5 rounded-full ${sev.dot}`} />
                    {sev.label} · Clause {f.clauseId}
                  </span>
                  <p className="m-0 mt-0.5 font-medium">{f.headline}</p>
                  {f.question && <p className="m-0 text-sm text-ink-2">{f.question}</p>}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            <span className="inline-flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-critical/30" /> Needs attention
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-serious/30" /> Worth a look
            </span>
            <span>Select a highlight to see why it was flagged.</span>
          </div>
        )}
      </div>
      <Suspense
        fallback={
          <div className="flex justify-center py-24 text-muted">
            <SpinnerIcon className="size-6" />
          </div>
        }
      >
        <PdfViewer file={file} highlights={highlights} focus={focus} onSelect={setSelected} />
      </Suspense>
    </div>
  );
}
