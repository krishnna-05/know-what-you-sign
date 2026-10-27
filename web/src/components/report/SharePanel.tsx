import { useState } from "react";
import { contribute } from "../../api";
import { withUnit } from "../../format";
import type { ShareableFigure } from "../../types";
import { HeartIcon, SpinnerIcon } from "../icons";

/**
 * Opt-in: the reader sees exactly which numbers would be shared, and nothing
 * is sent until they say so. No text, names or dates are ever part of it.
 */
export function SharePanel({
  domain,
  city,
  figures,
}: {
  domain: string;
  city: string;
  figures: ShareableFigure[];
}) {
  const [open, setOpen] = useState(false);
  const [includeCity, setIncludeCity] = useState(Boolean(city));
  const [state, setState] = useState<"idle" | "busy" | "done" | "dup" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  if (figures.length === 0) return null;

  async function send() {
    setState("busy");
    try {
      const r = await contribute(
        domain,
        includeCity ? city : undefined,
        figures.map((f) => ({ key: f.key, value: f.value })),
      );
      setState(r.stored ? "done" : "dup");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  }

  if (state === "done" || state === "dup") {
    return (
      <div className="no-print rounded-xl border border-line bg-card px-5 py-4 text-sm">
        <p className="m-0 font-medium">Thank you.</p>
        <p className="m-0 mt-0.5 text-muted">
          {state === "done"
            ? "These figures will help others see what is normal."
            : "These figures were already shared."}
        </p>
      </div>
    );
  }

  return (
    <div className="no-print rounded-xl border border-line bg-card">
      <div className="px-5 sm:px-6 py-4 flex items-start gap-3">
        <HeartIcon className="size-5 text-accent shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="m-0 font-medium">Help others know what is normal</p>
          <p className="m-0 mt-0.5 text-sm text-muted">
            Share this agreement's figures, anonymously. Only numbers, never text.
          </p>
          {!open && (
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="mt-2 bg-transparent border-0 p-0 text-sm font-medium text-accent cursor-pointer"
            >
              See what would be shared
            </button>
          )}
        </div>
      </div>
      {open && (
        <div className="border-t border-line px-5 sm:px-6 py-4">
          <ul className="m-0 p-0 list-none text-sm space-y-1">
            {figures.map((f) => (
              <li key={f.key} className="flex justify-between gap-4">
                <span className="text-ink-2">{f.label}</span>
                <span className="font-medium tabular-nums">{withUnit(f.value, f.unit)}</span>
              </li>
            ))}
            {city && (
              <li className="flex justify-between gap-4">
                <label className="text-ink-2 flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={includeCity}
                    onChange={(e) => setIncludeCity(e.target.checked)}
                    className="accent-[var(--accent)]"
                  />
                  City
                </label>
                <span className={`font-medium ${includeCity ? "" : "text-muted line-through"}`}>
                  {city}
                </span>
              </li>
            )}
          </ul>
          <p className="m-0 mt-3 text-xs text-muted">
            Rupee amounts are rounded. Nothing else from your document is sent, and
            shared figures are kept apart from the court-case data.
          </p>
          {error && <p className="m-0 mt-2 text-sm text-critical">{error}</p>}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={send}
              disabled={state === "busy"}
              className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium bg-accent text-accent-ink border-0 cursor-pointer disabled:opacity-50"
            >
              {state === "busy" && <SpinnerIcon />}Share these figures
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-lg px-4 py-2 text-sm bg-transparent border border-line-strong cursor-pointer"
            >
              Not now
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
