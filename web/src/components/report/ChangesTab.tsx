import { useState } from "react";
import { withUnit } from "../../format";
import type { Change, Diff } from "../../types";
import { SEVERITY } from "../FindingCard";
import { ChevronIcon } from "../icons";
import { ClauseLink, Panel } from "./shared";

const CHANGE: Record<Change, { label: string; className: string }> = {
  better: { label: "Better for you", className: "text-good bg-good/10" },
  worse: { label: "Worse for you", className: "text-critical bg-critical/10" },
  changed: { label: "Changed", className: "text-ink-2 bg-surface-2" },
  added: { label: "New", className: "text-ink-2 bg-surface-2" },
  removed: { label: "Removed", className: "text-ink-2 bg-surface-2" },
};

function Count({ n, label, tone }: { n: number; label: string; tone?: string }) {
  return (
    <div className="px-5 py-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{n}</div>
    </div>
  );
}

/** What changed between the previous draft and this one, judged for the reader. */
export function ChangesTab({
  diff,
  previousName,
  onShowClause,
}: {
  diff: Diff;
  previousName: string;
  onShowClause: (id: string) => void;
}) {
  const better = diff.figures.filter((f) => f.change === "better").length;
  const worse = diff.figures.filter((f) => f.change === "worse").length;
  const { resolved, raised } = diff.findings;
  const c = diff.clauses;

  return (
    <div className="space-y-4">
      <p className="m-0 text-sm text-ink-2">
        Compared with <span className="font-medium">{previousName}</span>
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-line bg-card border border-line rounded-xl shadow-sm">
        <Count n={better} label="Terms improved" tone="text-good" />
        <Count n={worse} label="Terms worsened" tone={worse ? "text-critical" : ""} />
        <Count n={resolved.length} label="Issues resolved" />
        <Count n={raised.length} label="New issues" tone={raised.length ? "text-critical" : ""} />
      </div>

      {diff.figures.length > 0 && (
        <Panel padded={false}>
          <h3 className="m-0 px-5 sm:px-6 pt-5 pb-3 text-base font-semibold">Key terms</h3>
          <ul className="m-0 p-0 list-none">
            {diff.figures.map((f) => (
              <li
                key={f.key}
                className="border-t border-line px-5 sm:px-6 py-3 flex flex-wrap items-center gap-x-4 gap-y-1"
              >
                <span className="flex-1 min-w-40 text-sm">{f.label}</span>
                <span className="text-sm tabular-nums">
                  <span className="text-muted line-through decoration-1">
                    {f.old !== null ? withUnit(f.old, f.unit) : "—"}
                  </span>
                  <span className="mx-2 text-muted">→</span>
                  <span className="font-medium">
                    {f.new !== null ? withUnit(f.new, f.unit) : "—"}
                  </span>
                </span>
                <span
                  className={`text-xs font-medium rounded-full px-2 py-0.5 ${CHANGE[f.change].className}`}
                >
                  {CHANGE[f.change].label}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {(resolved.length > 0 || raised.length > 0) && (
        <div className="grid sm:grid-cols-2 gap-4">
          {[
            { title: "Resolved", items: resolved, empty: "None" },
            { title: "Newly raised", items: raised, empty: "None" },
          ].map((col) => (
            <Panel key={col.title}>
              <h3 className="m-0 text-base font-semibold">{col.title}</h3>
              {col.items.length === 0 ? (
                <p className="m-0 mt-2 text-sm text-muted">{col.empty}</p>
              ) : (
                <ul className="m-0 mt-2 p-0 list-none space-y-2">
                  {col.items.map((f) => (
                    <li key={`${f.clauseId}-${f.headline}`} className="flex gap-2 text-sm">
                      <span
                        className={`mt-1.5 size-1.5 rounded-full shrink-0 ${
                          (SEVERITY[f.severity] ?? SEVERITY.low).dot
                        }`}
                      />
                      {f.headline}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          ))}
        </div>
      )}

      <Panel padded={false}>
        <h3 className="m-0 px-5 sm:px-6 pt-5 pb-1 text-base font-semibold">Clauses</h3>
        <p className="m-0 px-5 sm:px-6 pb-3 text-sm text-muted">
          {c.modified.length} reworded · {c.added.length} added · {c.removed.length} removed ·{" "}
          {c.unchanged} unchanged
        </p>
        {c.modified.map((m) => (
          <ClauseDiff key={m.newId} m={m} onShowClause={onShowClause} />
        ))}
        {c.added.map((a) => (
          <div key={`a${a.id}`} className="border-t border-line px-5 sm:px-6 py-3">
            <div className="flex justify-between gap-3">
              <span className="text-xs font-medium text-good">Added</span>
              <ClauseLink id={a.id} onShow={onShowClause} />
            </div>
            <p className="m-0 mt-1 text-sm">{a.text}</p>
          </div>
        ))}
        {c.removed.map((r) => (
          <div key={`r${r.id}`} className="border-t border-line px-5 sm:px-6 py-3">
            <span className="text-xs font-medium text-critical">
              Removed (was clause {r.id})
            </span>
            <p className="m-0 mt-1 text-sm text-muted line-through decoration-1">{r.text}</p>
          </div>
        ))}
      </Panel>
    </div>
  );
}

/** A reworded clause: word-level changes, old struck through, new underlined. */
function ClauseDiff({
  m,
  onShowClause,
}: {
  m: Diff["clauses"]["modified"][number];
  onShowClause: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-line px-5 sm:px-6 py-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 bg-transparent border-0 p-0 text-left cursor-pointer"
      >
        <ChevronIcon className={`size-4 text-muted transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="text-sm font-medium flex-1">Clause {m.newId} reworded</span>
        <span className="text-xs text-muted">{Math.round((1 - m.similarity) * 100)}% changed</span>
      </button>
      {open && (
        <>
          <p className="m-0 mt-2 text-sm leading-relaxed">
            {wordDiff(m.oldText, m.newText).map((p, i) =>
              p.op === "same" ? (
                <span key={i}>{p.text}</span>
              ) : p.op === "del" ? (
                <del key={i} className="text-critical bg-critical/10 decoration-1">
                  {p.text}
                </del>
              ) : (
                <ins key={i} className="text-good bg-good/10 no-underline">
                  {p.text}
                </ins>
              ),
            )}
          </p>
          <ClauseLink id={m.newId} onShow={onShowClause} />
        </>
      )}
    </div>
  );
}

/** Longest-common-subsequence over words; clauses are short enough for O(n·m). */
function wordDiff(a: string, b: string): { op: "same" | "del" | "ins"; text: string }[] {
  const x = a.split(/(\s+)/);
  const y = b.split(/(\s+)/);
  const n = x.length;
  const m = y.length;
  const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);

  const out: { op: "same" | "del" | "ins"; text: string }[] = [];
  const push = (op: "same" | "del" | "ins", text: string) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.text += text;
    else out.push({ op, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      push("same", x[i]);
      i++;
      j++;
    } else if (L[i + 1][j] >= L[i][j + 1]) push("del", x[i++]);
    else push("ins", y[j++]);
  }
  while (i < n) push("del", x[i++]);
  while (j < m) push("ins", y[j++]);
  return out;
}
