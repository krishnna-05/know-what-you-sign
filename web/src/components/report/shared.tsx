import type { ReactNode } from "react";
import { clauseRef } from "../../format";

export function Panel({ children, padded = true }: { children: ReactNode; padded?: boolean }) {
  return (
    <div className={`bg-card border border-line rounded-xl shadow-sm ${padded ? "p-5 sm:p-6" : ""}`}>
      {children}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="bg-card border border-line rounded-xl shadow-sm p-8 text-center">
      <p className="m-0 font-semibold">{title}</p>
      <p className="text-sm text-muted mt-1 mb-0 max-w-md mx-auto">{children}</p>
    </div>
  );
}

/** "Clause 4.1", as a link that shows the clause in the document. */
export function ClauseLink({ id, onShow }: { id: string; onShow: (id: string) => void }) {
  if (id.startsWith("missing:")) {
    return <span className="text-xs text-muted">{clauseRef(id)}</span>;
  }
  return (
    <button
      type="button"
      onClick={() => onShow(id)}
      className="no-print mt-1 bg-transparent border-0 p-0 text-xs text-accent hover:underline cursor-pointer"
    >
      {clauseRef(id)}
    </button>
  );
}

/** Copy text, with a moment of confirmation on the button that did it. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Hand the reader a file, built here; nothing goes to the server. */
export function download(name: string, text: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
