import { useState } from "react";
import { ask } from "../../api";
import type { AskResult, Clause } from "../../types";
import { SearchIcon, SpinnerIcon } from "../icons";
import { ClauseLink, Panel } from "./shared";

const SUGGESTIONS: Record<string, string[]> = {
  residential_lease: [
    "Can I sublet?",
    "What if I move out early?",
    "When do I get my deposit back?",
    "Who pays for repairs?",
    "Can I keep a pet?",
    "Can the owner enter without telling me?",
  ],
  employment_offer: [
    "What if I resign?",
    "Do I have to repay anything if I leave?",
    "Can I join a competitor?",
    "How long is probation?",
    "Who owns my side projects?",
  ],
  consumer_tos: [
    "Can they delete my account?",
    "Can they change these terms?",
    "Can I get a refund?",
    "Where would a dispute be heard?",
  ],
};

/**
 * Questions answered with the agreement's own clauses - never generated text.
 * "This agreement does not say" is a real answer, and often the important one.
 */
export function AskTab({
  domain,
  clauses,
  onShowClause,
}: {
  domain: string;
  clauses: Clause[];
  onShowClause: (id: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<AskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(q: string) {
    const text = q.trim();
    if (text.length < 2) return;
    setQuestion(text);
    setBusy(true);
    setError(null);
    try {
      setResult(await ask(text, domain, clauses));
      setAsked(text);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const byId = new Map(clauses.map((c) => [c.id, c]));

  return (
    <div className="space-y-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(question);
        }}
        className="flex gap-2"
      >
        <div className="relative flex-1">
          <SearchIcon className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={300}
            placeholder="Ask about this agreement"
            aria-label="Your question"
            className="w-full bg-card border border-line-strong rounded-lg pl-9 pr-3 py-2.5 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={busy || question.trim().length < 2}
          className="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium bg-accent text-accent-ink disabled:opacity-40 cursor-pointer border-0"
        >
          {busy && <SpinnerIcon />}Ask
        </button>
      </form>

      <div className="flex flex-wrap gap-2">
        {(SUGGESTIONS[domain] ?? []).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => run(s)}
            className="rounded-full border border-line-strong bg-card px-3 py-1 text-xs text-ink-2 hover:bg-surface-2 cursor-pointer"
          >
            {s}
          </button>
        ))}
      </div>

      {error && <p className="text-sm text-critical m-0">{error}</p>}

      {result && asked && (
        <div className="space-y-3">
          {result.silent ? (
            <Panel>
              <p className="m-0 font-semibold">This agreement does not say</p>
              <p className="m-0 mt-1 text-sm text-ink-2">
                No clause covers “{asked}”. If it matters to you, ask for it to be
                added in writing before you sign.
              </p>
            </Panel>
          ) : (
            <>
              <p className="m-0 text-sm text-muted">
                {result.answers.length === 1
                  ? "The clause that covers this:"
                  : `${result.answers.length} clauses cover this, most relevant first:`}
              </p>
              {result.answers.map((a) => {
                const c = byId.get(a.clauseId);
                return (
                  <Panel key={a.clauseId}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-medium text-ink-2">
                        {c?.typeLabel && c.type !== "other" ? c.typeLabel : c?.heading ?? ""}
                      </span>
                      <ClauseLink id={a.clauseId} onShow={onShowClause} />
                    </div>
                    <blockquote className="m-0 mt-2 text-[15px] leading-relaxed">
                      {a.text}
                    </blockquote>
                  </Panel>
                );
              })}
            </>
          )}
        </div>
      )}
    </div>
  );
}
