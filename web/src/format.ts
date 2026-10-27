/** Rupees with Indian digit grouping: ₹1,92,000. */
export function inr(x: number): string {
  return `₹${Math.round(x).toLocaleString("en-IN")}`;
}

/** "6 months", "15 days", "1 month". */
export function months(x: number): string {
  if (x < 1) {
    const d = Math.round(x * 30);
    return `${d} day${d === 1 ? "" : "s"}`;
  }
  const v = Number.isInteger(x) ? x : Math.round(x * 10) / 10;
  return `${v} month${v === 1 ? "" : "s"}`;
}

/** A value with the unit the backend gave it, for comparisons and shared figures. */
export function withUnit(value: number, unit: string): string {
  switch (unit) {
    case "INR":
      return inr(value);
    case "months":
    case "months_of_rent":
      return months(value);
    case "days":
      return `${Math.round(value)} days`;
    case "%":
    case "pct_per_year":
      return `${value}% a year`;
    case "% a month":
    case "pct_per_month":
      return `${value}% a month`;
    default:
      return `${value} ${unit}`;
  }
}

/** "1 May 2026", read as a local calendar date, never shifted by time zone. */
export function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function clauseRef(id: string): string {
  if (id.startsWith("missing:")) return "Missing from document";
  if (id === "preamble") return "Opening paragraph";
  return `Clause ${id}`;
}
