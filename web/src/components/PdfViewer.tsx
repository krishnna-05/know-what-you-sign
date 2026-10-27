import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { Span } from "../types";
import { SpinnerIcon } from "./icons";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export type Tone = "high" | "medium" | "low" | "answer";

export interface Highlight {
  clauseId: string;
  spans: Span[];
  tone: Tone;
  title: string;
}

const TONE: Record<Tone, string> = {
  high: "bg-critical/15 ring-critical/50 hover:bg-critical/25",
  medium: "bg-serious/15 ring-serious/50 hover:bg-serious/25",
  low: "bg-muted/15 ring-muted/40 hover:bg-muted/25",
  answer: "bg-accent/15 ring-accent/50 hover:bg-accent/25",
};

/**
 * The reader's own PDF, rendered in the browser with the flagged clauses
 * marked on it.
 *
 * Rendered from the File the reader picked, never from the server: the
 * document is not sent back or kept for this. Highlight boxes come from the
 * clause positions the PDF reader recorded, in PDF points, scaled to the
 * rendered page.
 */
export default function PdfViewer({
  file,
  highlights,
  focus,
  onSelect,
}: {
  file: File;
  highlights: Highlight[];
  focus: string | null;
  onSelect?: (clauseId: string) => void;
}) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(0);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    file
      .arrayBuffer()
      .then((data) => pdfjs.getDocument({ data }).promise)
      .then((d) => {
        loaded = d;
        if (!cancelled) setDoc(d);
      })
      .catch(() => !cancelled && setError("This PDF could not be displayed."));
    return () => {
      cancelled = true;
      loaded?.destroy();
    };
  }, [file]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Bring the focused clause into view once its page has laid out.
  useEffect(() => {
    if (!focus) return;
    const t = window.setTimeout(() => {
      wrap.current
        ?.querySelector(`[data-clause="${CSS.escape(focus)}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 150);
    return () => window.clearTimeout(t);
  }, [focus, doc, width]);

  const byPage = new Map<number, { h: Highlight; span: Span }[]>();
  for (const h of highlights)
    for (const span of h.spans) {
      const list = byPage.get(span.page) ?? [];
      list.push({ h, span });
      byPage.set(span.page, list);
    }

  return (
    <div ref={wrap} className="space-y-4">
      {error && <p className="text-sm text-critical">{error}</p>}
      {!doc && !error && (
        <div className="flex justify-center py-24 text-muted">
          <SpinnerIcon className="size-6" />
        </div>
      )}
      {doc &&
        width > 0 &&
        Array.from({ length: doc.numPages }, (_, i) => (
          <Page
            key={i}
            doc={doc}
            index={i}
            width={width}
            marks={byPage.get(i) ?? []}
            focus={focus}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

function Page({
  doc,
  index,
  width,
  marks,
  focus,
  onSelect,
}: {
  doc: PDFDocumentProxy;
  index: number;
  width: number;
  marks: { h: Highlight; span: Span }[];
  focus: string | null;
  onSelect?: (clauseId: string) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [page, setPage] = useState<PDFPageProxy | null>(null);

  useEffect(() => {
    let cancelled = false;
    doc.getPage(index + 1).then((p) => !cancelled && setPage(p));
    return () => {
      cancelled = true;
    };
  }, [doc, index]);

  const base = page?.getViewport({ scale: 1 });
  const scale = base ? width / base.width : 1;

  useEffect(() => {
    if (!page || !canvas.current) return;
    const dpr = window.devicePixelRatio || 1;
    const viewport = page.getViewport({ scale: scale * dpr });
    const c = canvas.current;
    c.width = Math.floor(viewport.width);
    c.height = Math.floor(viewport.height);
    const task = page.render({ canvas: c, viewport });
    task.promise.catch(() => {
      // Cancelled by a newer render after a resize; nothing to do.
    });
    return () => task.cancel();
  }, [page, scale]);

  if (!base) return <div className="aspect-[1/1.414] bg-card border border-line rounded-lg" />;

  const seen = new Set<string>();
  return (
    <div
      className="relative bg-white border border-line rounded-lg shadow-sm overflow-hidden"
      style={{ width, height: base.height * scale }}
    >
      <canvas ref={canvas} className="block w-full h-full" />
      {marks.map(({ h, span }, k) => {
        // One element per clause carries the anchor the scroller looks for.
        const anchor = !seen.has(h.clauseId);
        seen.add(h.clauseId);
        const pad = 2;
        return (
          <button
            key={`${h.clauseId}-${k}`}
            type="button"
            title={h.title}
            data-clause={anchor ? h.clauseId : undefined}
            onClick={() => onSelect?.(h.clauseId)}
            className={`absolute rounded-sm ring-1 border-0 p-0 cursor-pointer transition-colors mix-blend-multiply ${
              TONE[h.tone]
            } ${focus === h.clauseId ? "ring-2" : ""}`}
            style={{
              left: span.x0 * scale - pad,
              top: span.y0 * scale - pad,
              width: (span.x1 - span.x0) * scale + pad * 2,
              height: (span.y1 - span.y0) * scale + pad * 2,
            }}
          />
        );
      })}
    </div>
  );
}
