import type { Distribution, Norm } from "../types";

/**
 * Where the reader's own value sits among comparable agreements.
 *
 * Emphasis form: one bar in the accent, every other receding to gray. Hand-drawn
 * SVG rather than a charting library - this is six bars and two labels, and the
 * control over mark geometry matters more here than the abstraction would.
 *
 * The picture is the point. "85th percentile" is precise and inert; one red bar
 * standing apart is legible to someone with no training, which is the entire
 * audience. It is also more honest than a percentile alone: the reader can see
 * that other agreements DO ask what theirs asks, which a single number hides.
 */
export function DistributionChart({
  dist,
  norm,
  unit,
}: {
  dist: Distribution;
  norm: Norm;
  unit: string | null;
}) {
  const W = 560;
  const H = 150;
  const PAD = { top: 26, right: 18, bottom: 26, left: 34 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const values = dist.counts.map((c) => c.value);
  const lo = Math.min(...values, norm.value);
  const hi = Math.max(...values, norm.value);
  const span = hi - lo || 1;
  // Inset so an edge bar is never half-clipped by the plot bound.
  const x = (v: number) => PAD.left + ((v - lo) / span) * plotW * 0.94 + plotW * 0.03;

  const maxCount = Math.max(...dist.counts.map((c) => c.count));
  const y = (n: number) => PAD.top + plotH - (n / maxCount) * plotH;

  // Five ticks at round positions, deduped - a tick per distinct value gets
  // unreadable once a distribution has a long tail.
  const ticks = Array.from(
    new Set([0, 0.25, 0.5, 0.75, 1].map((t) => +(lo + t * span).toFixed(1))),
  );

  const label = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        role="img"
        aria-label={`Your value is ${norm.value}. The usual across ${dist.n} comparable agreements is ${dist.median}.`}
      >
        <line
          x1={PAD.left} y1={PAD.top + plotH} x2={W - PAD.right} y2={PAD.top + plotH}
          stroke="var(--chart-ctx)" strokeWidth={1} opacity={0.5}
        />
        <text
          x={PAD.left - 8} y={PAD.top + 4} textAnchor="end"
          fontSize={10} fill="var(--chart-ctx)"
        >
          {maxCount}
        </text>
        <text
          x={PAD.left - 8} y={PAD.top + plotH} textAnchor="end"
          fontSize={10} fill="var(--chart-ctx)"
        >
          0
        </text>

        {dist.counts.map((c) => {
          const mine = c.value === norm.value;
          const barH = Math.max(PAD.top + plotH - y(c.count), 2);
          return (
            <rect
              key={c.value}
              x={x(c.value) - 6}
              y={y(c.count)}
              width={12}
              height={barH}
              rx={3}
              fill={mine ? "var(--chart-yours)" : "var(--chart-ctx)"}
              opacity={mine ? 1 : 0.75}
            >
              <title>
                {c.count} of {dist.n} agreements said {label(c.value)}
                {unit ? ` ${unit}` : ""}
              </title>
            </rect>
          );
        })}

        {/* Direct labels rather than a legend: with two marks a legend costs
            more room than it explains, and colour must never carry meaning
            alone. Anchored inward at the edges so nothing is clipped. */}
        {[
          { v: dist.median, t: `usual: ${label(dist.median)}`, c: "var(--chart-ctx)", w: 400 },
          { v: norm.value, t: `yours: ${label(norm.value)}`, c: "var(--chart-yours)", w: 700 },
        ].map((m) => (
          <text
            key={m.t}
            x={x(m.v)}
            y={PAD.top - 10}
            textAnchor={
              x(m.v) > W - PAD.right - 60
                ? "end"
                : x(m.v) < PAD.left + 60
                  ? "start"
                  : "middle"
            }
            fontSize={12}
            fontWeight={m.w}
            fill={m.c}
          >
            {m.t}
          </text>
        ))}

        {ticks.map((t) => (
          <text
            key={t} x={x(t)} y={H - 8} textAnchor="middle"
            fontSize={11} fill="var(--chart-ctx)"
          >
            {label(t)}
          </text>
        ))}
      </svg>
      <figcaption className="text-xs text-muted mt-1">
        Each bar is how many of {dist.n} comparable agreements asked that much
      </figcaption>
    </figure>
  );
}
