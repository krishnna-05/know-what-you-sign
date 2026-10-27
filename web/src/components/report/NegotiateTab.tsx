import { useMemo, useState } from "react";
import { clauseRef } from "../../format";
import type { Report } from "../../types";
import { SEVERITY } from "../FindingCard";
import { CopyIcon, DownloadIcon, MailIcon } from "../icons";
import { Empty, Panel, copyText, download } from "./shared";

const DOC_NAME: Record<string, string> = {
  residential_lease: "rental agreement",
  employment_offer: "offer letter",
  consumer_tos: "terms",
};

type Item = Report["findings"][number];

function compose(items: Item[], domain: string): string {
  const doc = DOC_NAME[domain] ?? "agreement";
  const points = items.map((f, i) => {
    const where = f.clauseId.startsWith("missing:") ? "" : ` (${clauseRef(f.clauseId).toLowerCase()})`;
    const ask = f.question ?? "";
    const wording = f.suggestedWording ? `\n   Suggested wording: "${f.suggestedWording}"` : "";
    return `${i + 1}. ${f.label}${where}. ${ask}${wording}`;
  });
  return [
    "Dear [name],",
    "",
    `Thank you for sending the ${doc}. Before I sign, I would like to discuss a few points:`,
    "",
    ...points.flatMap((p) => [p, ""]),
    "I am happy to talk these through. Thank you.",
    "",
    "Regards,",
    "[your name]",
  ].join("\n");
}

/**
 * Each ask with wording to propose, and one message to the other side built
 * from the asks the reader picks. The message is theirs to edit and send;
 * nothing here sends it.
 */
export function NegotiateTab({ report, domain }: { report: Report; domain: string }) {
  const findings = report.findings;
  const [picked, setPicked] = useState<Set<number>>(
    () => new Set(findings.flatMap((f, i) => (f.severity !== "low" ? [i] : []))),
  );
  const [edited, setEdited] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const generated = useMemo(
    () => compose(findings.filter((_, i) => picked.has(i)), domain),
    [findings, picked, domain],
  );
  const message = edited ?? generated;

  async function copy(key: string, text: string) {
    if (await copyText(text)) {
      setCopied(key);
      window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
    }
  }

  if (findings.length === 0) {
    return <Empty title="Nothing to negotiate">No clause in this agreement was flagged.</Empty>;
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        {findings.map((f, i) => {
          const sev = SEVERITY[f.severity] ?? SEVERITY.low;
          const on = picked.has(i);
          return (
            <Panel key={`${f.clauseId}-${i}`}>
              <label className="flex gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => {
                    const next = new Set(picked);
                    if (on) next.delete(i);
                    else next.add(i);
                    setPicked(next);
                    setEdited(null);
                  }}
                  className="mt-1 size-4 accent-[var(--accent)] shrink-0"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-3">
                    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${sev.text}`}>
                      <span className={`size-1.5 rounded-full ${sev.dot}`} />
                      {sev.label}
                    </span>
                    <span className="text-xs text-muted">{clauseRef(f.clauseId)}</span>
                  </span>
                  <span className="block mt-1 font-semibold">{f.label}</span>
                  {f.question && (
                    <span className="block mt-0.5 text-sm text-ink-2">{f.question}</span>
                  )}
                </span>
              </label>
              {f.suggestedWording && (
                <div className="mt-3 ml-7 rounded-lg bg-surface-2 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                      Suggested wording
                    </span>
                    <button
                      type="button"
                      onClick={() => copy(`w${i}`, f.suggestedWording!)}
                      className="no-print inline-flex items-center gap-1 bg-transparent border-0 p-0 text-xs text-accent cursor-pointer"
                    >
                      <CopyIcon className="size-3.5" />
                      {copied === `w${i}` ? "Copied" : "Copy"}
                    </button>
                  </div>
                  <p className="m-0 mt-1.5 text-sm leading-relaxed font-serif">
                    {f.suggestedWording}
                  </p>
                </div>
              )}
            </Panel>
          );
        })}
      </section>

      <section>
        <div className="flex flex-wrap items-end justify-between gap-3 mb-2">
          <div>
            <h2 className="m-0 text-base font-semibold">Message to the other side</h2>
            <p className="m-0 text-sm text-muted">
              {picked.size} point{picked.size === 1 ? "" : "s"} included. Edit freely.
            </p>
          </div>
          <div className="no-print flex gap-2">
            <button
              type="button"
              onClick={() => copy("msg", message)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong bg-card px-3 py-2 text-sm hover:bg-surface-2 cursor-pointer"
            >
              <CopyIcon /> {copied === "msg" ? "Copied" : "Copy"}
            </button>
            <button
              type="button"
              onClick={() => download("message.txt", message)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong bg-card px-3 py-2 text-sm hover:bg-surface-2 cursor-pointer"
            >
              <DownloadIcon /> Download
            </button>
            <a
              href={`mailto:?subject=${encodeURIComponent(
                `About the ${DOC_NAME[domain] ?? "agreement"}`,
              )}&body=${encodeURIComponent(message)}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent text-accent-ink px-3 py-2 text-sm font-medium no-underline"
            >
              <MailIcon /> Email
            </a>
          </div>
        </div>
        <textarea
          value={message}
          onChange={(e) => setEdited(e.target.value)}
          rows={Math.min(24, message.split("\n").length + 2)}
          aria-label="Message"
          className="w-full bg-card border border-line-strong rounded-xl p-4 text-sm leading-relaxed font-mono"
        />
        {edited !== null && (
          <button
            type="button"
            onClick={() => setEdited(null)}
            className="no-print bg-transparent border-0 p-0 text-xs text-accent cursor-pointer"
          >
            Discard edits
          </button>
        )}
        <p className="m-0 mt-2 text-xs text-muted">
          Suggested wording is a starting point for the conversation, not legal
          drafting.
        </p>
      </section>
    </div>
  );
}
