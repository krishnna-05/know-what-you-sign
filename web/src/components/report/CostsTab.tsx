import { useState } from "react";
import { inr, months } from "../../format";
import type { Exposure } from "../../types";
import { ClauseLink, Empty, Panel } from "./shared";

/**
 * What leaving costs, month by month. The schedule is computed on the server
 * from the extracted figures; this only picks the month and, for a job,
 * prices the notice period with a salary the reader types in - which never
 * leaves the browser.
 */
export function CostsTab({
  exposure,
  onShowClause,
}: {
  exposure: Exposure | null;
  onShowClause: (id: string) => void;
}) {
  const [month, setMonth] = useState(1);
  const [salary, setSalary] = useState("");

  if (!exposure || exposure.schedule.length === 0) {
    return (
      <Empty title="No costs to estimate">
        The figures needed to price leaving early (rent, lock-in, notice or a
        bond) were not found in this agreement.
      </Empty>
    );
  }

  const row = exposure.schedule[Math.min(month, exposure.horizon) - 1];
  const pay = Number(salary.replace(/[^\d.]/g, "")) || 0;
  const priced = row.lines.map((l) => ({
    ...l,
    value: l.amount ?? (l.salaryMonths && pay ? l.salaryMonths * pay : null),
  }));
  const lease = exposure.kind === "lease";
  // Lease charges overlap (the same months of rent), so the worst one is the
  // figure; a bond and notice pay are separate debts, so they add up.
  const total = lease
    ? Math.max(0, ...priced.map((l) => l.value ?? 0))
    : priced.reduce((s, l) => s + (l.value ?? 0), 0);

  return (
    <div className="space-y-4">
      <Panel>
        <label htmlFor="exit-month" className="block text-sm text-ink-2">
          If you {lease ? "move out" : "resign"} after
        </label>
        <div className="flex items-baseline justify-between gap-4 mt-1">
          <span className="text-2xl font-semibold tabular-nums">{months(month)}</span>
          <span className="text-right">
            <span className="block text-xs text-muted">Could cost you up to</span>
            <span className="block text-2xl font-semibold tabular-nums text-critical">
              {inr(total)}
            </span>
          </span>
        </div>
        <input
          id="exit-month"
          type="range"
          min={1}
          max={exposure.horizon}
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="w-full mt-4 accent-[var(--accent)]"
        />
        <div className="flex justify-between text-xs text-muted tabular-nums">
          <span>1 month</span>
          {(exposure.lockInMonths || exposure.bondMonths) && (
            <span>
              {lease ? "Lock-in" : "Bond"} ends at{" "}
              {months((exposure.lockInMonths || exposure.bondMonths)!)}
            </span>
          )}
          <span>{months(exposure.horizon)}</span>
        </div>
      </Panel>

      {!lease && (
        <Panel>
          <label htmlFor="salary" className="block text-sm font-medium mb-1.5">
            Monthly salary <span className="text-muted font-normal">(optional)</span>
          </label>
          <input
            id="salary"
            inputMode="numeric"
            value={salary}
            onChange={(e) => setSalary(e.target.value)}
            placeholder="50,000"
            className="w-full bg-card border border-line-strong rounded-lg px-3 py-2.5 text-sm"
          />
          <p className="text-xs text-muted mt-1.5 mb-0">
            Prices the notice period. Stays in your browser.
          </p>
        </Panel>
      )}

      <Panel padded={false}>
        <ul className="m-0 p-0 list-none divide-y divide-line">
          {priced.map((l) => (
            <li key={l.key} className="px-5 sm:px-6 py-4 flex gap-4 justify-between">
              <div className="min-w-0">
                <p className="m-0 font-medium">{l.label}</p>
                <p className="m-0 mt-0.5 text-sm text-muted">{l.note}</p>
                <ClauseLink id={l.clauseId} onShow={onShowClause} />
              </div>
              <div className="text-right shrink-0">
                <p className="m-0 font-semibold tabular-nums">
                  {l.value !== null ? inr(l.value) : <span className="text-muted">—</span>}
                </p>
                {l.proRata != null && (
                  <p className="m-0 text-xs text-muted tabular-nums">
                    {inr(l.proRata)} if pro rata
                  </p>
                )}
                {l.value === null && (
                  <p className="m-0 text-xs text-muted">Enter salary</p>
                )}
              </div>
            </li>
          ))}
          {priced.length === 0 && (
            <li className="px-5 sm:px-6 py-4 text-sm text-ink-2">
              Nothing in the agreement charges you for leaving at this point.
            </li>
          )}
        </ul>
        {lease && priced.length > 1 && (
          <p className="m-0 border-t border-line px-5 sm:px-6 py-3 text-xs text-muted">
            These cover the same months of rent, so the larger one is the realistic
            worst case, not the sum.
          </p>
        )}
      </Panel>

      {lease && (exposure.depositHeld || exposure.lateFee) && (
        <div className="grid sm:grid-cols-2 gap-4">
          {exposure.depositHeld && (
            <Panel>
              <p className="m-0 text-sm text-ink-2">Deposit held after you leave</p>
              <p className="m-0 mt-1 text-xl font-semibold tabular-nums">
                {inr(exposure.depositHeld.amount)}
              </p>
              <p className="m-0 mt-1 text-xs text-muted">
                {exposure.depositHeld.days
                  ? `Due back within ${exposure.depositHeld.days} days`
                  : "No refund deadline stated"}
              </p>
              <ClauseLink id={exposure.depositHeld.clauseId} onShow={onShowClause} />
            </Panel>
          )}
          {exposure.lateFee && (
            <Panel>
              <p className="m-0 text-sm text-ink-2">Paying one month's rent late</p>
              <p className="m-0 mt-1 text-xl font-semibold tabular-nums">
                {inr(exposure.lateFee.amount)}
              </p>
              <p className="m-0 mt-1 text-xs text-muted">
                {exposure.lateFee.pctPerMonth}% a month, about{" "}
                {Math.round(exposure.lateFee.pctPerMonth * 12)}% a year
              </p>
              <ClauseLink id={exposure.lateFee.clauseId} onShow={onShowClause} />
            </Panel>
          )}
        </div>
      )}

      {!lease && exposure.nonCompeteMonths && (
        <Panel>
          <p className="m-0 text-sm text-ink-2">After you leave</p>
          <p className="m-0 mt-1 font-medium">
            No joining a competitor for {months(exposure.nonCompeteMonths)}
          </p>
          <p className="m-0 mt-1 text-xs text-muted">
            Post-employment non-competes are generally void in India under s.27 of
            the Contract Act, but challenging one still costs time.
          </p>
        </Panel>
      )}

      <p className="text-xs text-muted m-0">
        Estimated from the figures in your agreement. What is actually charged
        depends on its exact wording.
      </p>
    </div>
  );
}
