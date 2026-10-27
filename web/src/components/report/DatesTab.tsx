import { longDate } from "../../format";
import type { Timeline, TimelineEvent } from "../../types";
import { CalendarIcon } from "../icons";
import { ClauseLink, Empty, Panel, download } from "./shared";

const DOT: Record<TimelineEvent["kind"], string> = {
  milestone: "bg-ink-2",
  deadline: "bg-critical",
  money: "bg-serious",
};

/** An all-day calendar file, built in the browser. */
function toIcs(timeline: Timeline, title: string): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const day = (iso: string) => iso.replace(/-/g, "");
  const next = (iso: string) => {
    const [y, m, d] = iso.split("-").map(Number);
    const t = new Date(Date.UTC(y, m - 1, d + 1));
    return t.toISOString().slice(0, 10).replace(/-/g, "");
  };
  // RFC 5545: commas, semicolons and backslashes are escaped in text values.
  const esc = (s: string) => s.replace(/[\\,;]/g, (c) => `\\${c}`).replace(/\n/g, "\\n");
  const uid = () => `${crypto.randomUUID()}@know-what-you-sign`;

  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Know What You Sign//EN",
    "CALSCALE:GREGORIAN",
  ];
  for (const e of timeline.events) {
    lines.push(
      "BEGIN:VEVENT",
      `UID:${uid()}`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${day(e.date)}`,
      `DTEND;VALUE=DATE:${next(e.date)}`,
      `SUMMARY:${esc(`${e.label} — ${title}`)}`,
      `DESCRIPTION:${esc(`${e.basis} (clause ${e.clauseId})`)}`,
      "END:VEVENT",
    );
  }
  const r = timeline.recurring;
  if (r && r.from) {
    const [y, m] = r.from.split("-").map(Number);
    const first = `${y}-${String(m).padStart(2, "0")}-${String(r.dayOfMonth).padStart(2, "0")}`;
    lines.push(
      "BEGIN:VEVENT",
      `UID:${uid()}`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${day(first)}`,
      `DTEND;VALUE=DATE:${next(first)}`,
      `RRULE:FREQ=MONTHLY;BYMONTHDAY=${r.dayOfMonth};COUNT=${r.months}`,
      `SUMMARY:${esc(`${r.label} — ${title}`)}`,
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}

export function DatesTab({
  timeline,
  title,
  onShowClause,
}: {
  timeline: Timeline;
  title: string;
  onShowClause: (id: string) => void;
}) {
  if (timeline.events.length === 0) {
    return (
      <Empty title="No dates found">
        {timeline.hasStart
          ? "The agreement states a start date, but none of the periods needed to work out the others."
          : "The agreement does not state when it starts, so no deadlines can be worked out from it."}
      </Empty>
    );
  }

  const today = new Date().toISOString().slice(0, 10);
  const r = timeline.recurring;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="m-0 text-sm text-ink-2">
          {timeline.events.length} dates{r ? ", plus rent each month" : ""}
        </p>
        <button
          type="button"
          onClick={() =>
            download("agreement-dates.ics", toIcs(timeline, title), "text/calendar")
          }
          className="no-print inline-flex items-center gap-2 rounded-lg border border-line-strong bg-card px-3.5 py-2 text-sm font-medium hover:bg-surface-2 cursor-pointer"
        >
          <CalendarIcon /> Add to calendar
        </button>
      </div>

      <Panel padded={false}>
        <ol className="m-0 p-0 list-none">
          {timeline.events.map((e, i) => (
            <li
              key={`${e.label}-${e.date}`}
              className={`relative flex gap-4 px-5 sm:px-6 py-4 ${i ? "border-t border-line" : ""} ${
                e.date < today ? "opacity-60" : ""
              }`}
            >
              <div className="w-24 shrink-0 text-sm font-medium tabular-nums">
                {longDate(e.date)}
              </div>
              <span className={`mt-1.5 size-2 rounded-full shrink-0 ${DOT[e.kind]}`} />
              <div className="min-w-0">
                <p className="m-0 font-medium">{e.label}</p>
                <p className="m-0 mt-0.5 text-sm text-muted">
                  {e.stated ? `Stated: ${e.basis}` : `Worked out: ${e.basis}`}
                </p>
                <ClauseLink id={e.clauseId} onShow={onShowClause} />
              </div>
            </li>
          ))}
        </ol>
      </Panel>

      {r && (
        <Panel>
          <p className="m-0 font-medium">
            Rent due by the {r.dayOfMonth}
            {ordinal(r.dayOfMonth)} of each month
          </p>
          <ClauseLink id={r.clauseId} onShow={onShowClause} />
        </Panel>
      )}

      <p className="m-0 text-xs text-muted">
        Worked-out dates assume the periods run from the start date. Deadlines are
        set a day early to be safe.
      </p>
    </div>
  );
}

function ordinal(n: number): string {
  if (n % 100 >= 11 && n % 100 <= 13) return "th";
  return ["th", "st", "nd", "rd"][n % 10] ?? "th";
}
