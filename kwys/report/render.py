"""Presenting findings to someone with no legal training.

Three rules, all of which cost precision and buy comprehension:

  1. Counts, not percentiles. "About 4 in 100 agreements ask as much as yours"
     lands; "96th percentile" does not, for the person this tool exists for.
  2. Every finding ends in a QUESTION. A flag the user cannot act on is trivia.
     The output is a negotiating agenda, not a verdict.
  3. The limitation is stated on the report itself, not buried in a footer. This
     measures what is unusual, not what is unlawful.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from kwys.models import AnalysisResult, Finding, Severity

if TYPE_CHECKING:
    from rich.console import Console

SEVERITY_LABEL = {
    Severity.HIGH: "Needs attention",
    Severity.MEDIUM: "Worth a look",
    Severity.LOW: "Minor",
}

DISCLAIMER = (
    "This is a triage tool, not legal advice. It tells you which clauses are "
    "unusual compared with other agreements — not whether they are lawful or "
    "enforceable. For anything that matters, ask a lawyer."
)


def render_terminal(result: AnalysisResult, console: Console) -> None:
    from rich.panel import Panel
    from rich.table import Table

    doc = result.document
    if result.corpus_version and "SYNTHETIC" in result.corpus_version.upper():
        console.print()
        console.print(
            Panel(
                "[bold white on red] SYNTHETIC DEMO DATA [/bold white on red]\n"
                "The comparisons below are computed against invented numbers, to "
                "show that the pipeline works. They say nothing about real "
                "agreements.",
                border_style="red",
            )
        )
    console.print()
    console.print(
        Panel(
            f"[bold]{result.summary_line()}[/bold]\n"
            f"[dim]{doc.path} · {doc.page_count} pages · you are the "
            f"{doc.user_role.value}[/dim]",
            border_style="cyan",
        )
    )

    for w in result.warnings:
        console.print(f"[yellow]![/yellow] [yellow]{w}[/yellow]")
    if result.corpus_bias:
        console.print(
            f"[yellow]![/yellow] [yellow]About the comparison data: {result.corpus_bias}[/yellow]"
        )
    for d in result.diagnostics:
        console.print(f"[dim]setup: {d}[/dim]")
    if result.warnings or result.corpus_bias or result.diagnostics:
        console.print()

    if not result.findings:
        console.print("[green]Nothing stood out.[/green] ", end="")
        console.print(
            "[dim]That is not the same as 'this contract is fine' — see the "
            "note at the end.[/dim]\n"
        )

    for i, f in enumerate(result.findings, start=1):
        colour = {"high": "red", "medium": "yellow", "low": "dim"}[f.severity.value]
        console.print(
            f"[bold {colour}]{i}. {f.headline}[/bold {colour}]  "
            f"[{colour}]{SEVERITY_LABEL[f.severity]}[/{colour}]  "
            f"[dim]clause {f.clause_id}[/dim]"
        )
        console.print(f"   {f.plain_language}")
        if f.question_to_ask:
            console.print(f"   [cyan]->[/cyan] [italic]{f.question_to_ask}[/italic]")

        ev = f.evidence
        if ev.norm:
            n = ev.norm
            table = Table(show_header=False, box=None, padding=(0, 2, 0, 3))
            table.add_row("[dim]your value[/dim]", f"[dim]{n.value:g}[/dim]")
            table.add_row("[dim]typical[/dim]", f"[dim]{n.median:g}[/dim]")
            table.add_row(
                "[dim]percentile[/dim]",
                f"[dim]{n.percentile:.0%} (95% CI {n.ci_low:.0%}-{n.ci_high:.0%}, "
                f"n={n.n})[/dim]",
            )
            console.print(table)
        if ev.anchor and ev.anchor.exceeded:
            console.print(f"   [dim]law: {ev.anchor.source}[/dim]")
        if ev.rule_basis:
            console.print(f"   [dim]based on: {' '.join(ev.rule_basis.split())}[/dim]")
        console.print()

    if result.unassessed:
        console.print(
            "[bold]Found, but not checked[/bold] [dim]- no comparison data, law "
            "or rule yet; read these yourself:[/dim]"
        )
        for u in result.unassessed:
            console.print(f"   {u.label}: {u.value} [dim](clause {u.clause_id})[/dim]")
        console.print()

    console.print(f"[dim]{DISCLAIMER}[/dim]")
    console.print()


def render_html(result: AnalysisResult) -> str:
    """Self-contained HTML report, no external assets."""
    doc = result.document
    rows = []
    for i, f in enumerate(result.findings, start=1):
        rows.append(_finding_html(i, f))

    unassessed_block = (
        '<div class="warn"><strong>Found, but not checked</strong> - no comparison '
        "data, law or rule yet; read these yourself:<ul>"
        + "".join(
            f"<li>{html.escape(u.label)}: {html.escape(u.value)} "
            f"(clause {html.escape(u.clause_id)})</li>"
            for u in result.unassessed
        )
        + "</ul></div>"
        if result.unassessed
        else ""
    )
    notes = list(result.warnings)
    if result.corpus_bias:
        notes.append(f"About the comparison data: {result.corpus_bias}")
    warnings_html = "".join(f'<li>{html.escape(w)}</li>' for w in notes)
    warnings_block = (
        f'<div class="warn"><strong>Before you read this:</strong>'
        f'<ul>{warnings_html}</ul></div>'
        if notes
        else ""
    )
    empty_note = (
        "<p>Nothing stood out. That is not the same as saying the contract is "
        "fine &mdash; see the note below.</p>"
    )

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Know What You Sign - report</title>
<style>
  :root {{ --bg:#fbfbfa; --fg:#1a1a1a; --dim:#666; --line:#e3e3e0;
           --high:#b3261e; --med:#8a6100; --card:#fff; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#16171a; --fg:#e8e8e6; --dim:#9a9a97; --line:#2e3035;
             --high:#f2b8b5; --med:#e8c46a; --card:#1e2024; }}
  }}
  body {{ background:var(--bg); color:var(--fg); margin:0;
          font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  main {{ max-width:760px; margin:0 auto; padding:40px 20px 80px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .meta {{ color:var(--dim); font-size:13px; margin-bottom:28px; }}
  .warn {{ background:var(--card); border-left:3px solid var(--med);
           padding:12px 16px; margin-bottom:24px; font-size:14px; border-radius:4px; }}
  .warn ul {{ margin:6px 0 0; padding-left:20px; }}
  .f {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:18px 20px; margin-bottom:16px; }}
  .f h2 {{ font-size:16px; margin:0 0 2px; }}
  .chip {{ display:inline-block; font-size:11px; font-weight:600;
           text-transform:uppercase; letter-spacing:.04em; padding:2px 8px;
           border-radius:10px; vertical-align:2px; margin-left:8px; }}
  .high {{ color:var(--high); border:1px solid var(--high); }}
  .med  {{ color:var(--med);  border:1px solid var(--med); }}
  .cid {{ color:var(--dim); font-size:12px; }}
  .plain {{ margin:10px 0; }}
  .ask {{ font-style:italic; color:var(--fg); background:var(--bg);
          border-left:3px solid var(--line); padding:8px 12px; margin:12px 0 0;
          border-radius:0 4px 4px 0; }}
  details {{ margin-top:12px; font-size:13px; color:var(--dim); }}
  summary {{ cursor:pointer; }}
  blockquote {{ margin:8px 0; padding-left:12px; border-left:2px solid var(--line);
                color:var(--dim); font-size:13px; }}
  table {{ border-collapse:collapse; margin-top:8px; font-size:13px; }}
  td {{ padding:2px 14px 2px 0; }}
  .bar {{ height:6px; background:var(--line); border-radius:3px; position:relative;
          margin:10px 0 4px; }}
  .bar i {{ position:absolute; top:-3px; width:2px; height:12px;
            background:var(--high); }}
  footer {{ margin-top:40px; padding-top:20px; border-top:1px solid var(--line);
            color:var(--dim); font-size:13px; }}
</style>
<main>
  <h1>{html.escape(result.summary_line())}</h1>
  <div class="meta">{html.escape(doc.path)} &middot; {doc.page_count} pages
    &middot; you are the {doc.user_role.value}</div>
  {warnings_block}
  {"".join(rows) or empty_note}
  {unassessed_block}
  <footer>{html.escape(DISCLAIMER)}</footer>
</main>
"""


def _finding_html(i: int, f: Finding) -> str:
    chip = "high" if f.severity is Severity.HIGH else "med"
    ev = f.evidence
    parts = [
        f'<div class="f"><h2>{i}. {html.escape(f.headline)}'
        f'<span class="chip {chip}">{SEVERITY_LABEL[f.severity]}</span></h2>'
        f'<div class="cid">clause {html.escape(f.clause_id)}</div>'
        f'<p class="plain">{html.escape(f.plain_language)}</p>'
    ]

    if ev.norm and ev.norm.sufficient:
        n = ev.norm
        lo, hi = n.quantile_bounds if hasattr(n, "quantile_bounds") else (None, None)
        pos = max(0.0, min(1.0, n.percentile)) * 100
        parts.append(
            f'<div class="bar"><i style="left:{pos:.1f}%"></i></div>'
            f'<div class="cid">where yours sits among {n.n} comparable agreements</div>'
        )

    if f.question_to_ask:
        parts.append(f'<p class="ask">{html.escape(f.question_to_ask)}</p>')

    detail_rows = []
    if ev.term:
        detail_rows.append(
            f"<tr><td>extracted</td><td>{html.escape(str(ev.term.value))} "
            f"{html.escape(ev.term.unit or '')}</td></tr>"
        )
    if ev.norm:
        n = ev.norm
        detail_rows.append(f"<tr><td>median</td><td>{n.median:g}</td></tr>")
        detail_rows.append(
            f"<tr><td>percentile</td><td>{n.percentile:.0%} "
            f"(95% CI {n.ci_low:.0%}&ndash;{n.ci_high:.0%})</td></tr>"
        )
        detail_rows.append(f"<tr><td>sample size</td><td>{n.n}</td></tr>")
        detail_rows.append(f"<tr><td>robust z</td><td>{n.robust_z:+.2f}</td></tr>")
    if ev.anchor:
        detail_rows.append(
            f"<tr><td>statute</td><td>{html.escape(ev.anchor.source)}</td></tr>"
        )

    quote = (
        f"<blockquote>{html.escape(ev.clause_text[:600])}"
        f"{'&hellip;' if len(ev.clause_text) > 600 else ''}</blockquote>"
        if ev.clause_text
        else ""
    )
    parts.append(
        "<details><summary>Show the working</summary>"
        f"{quote}"
        f"<table>{''.join(detail_rows)}</table></details></div>"
    )
    return "".join(parts)
