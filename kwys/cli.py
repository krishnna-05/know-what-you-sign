"""Command line interface.

`kwys analyse` is what a user runs. Everything else is maintainer tooling:
building norms from a corpus, checking config health, and inspecting what the
segmenter saw when a document parses badly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from kwys.models import Domain, Role

app = typer.Typer(
    add_completion=False,
    help="Know What You Sign - find the unusual clauses in an agreement.",
)
console = Console()
DATA = Path(__file__).resolve().parent.parent / "data"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def analyse(
    path: Annotated[Path, typer.Argument(help="The agreement to check (PDF).")],
    role: Annotated[Role, typer.Option(help="Which side of the agreement you are on.")],
    domain: Annotated[Domain, typer.Option(help="What kind of agreement this is.")] = (
        Domain.RESIDENTIAL_LEASE
    ),
    city: Annotated[str | None, typer.Option(help="Your city, for venue distance.")] = None,
    state: Annotated[str | None, typer.Option(help="Your state, for statutory anchors.")] = None,
    html_out: Annotated[Path | None, typer.Option("--html", help="Write an HTML report.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json", help="Write evidence JSON.")] = None,
    corpus_version: Annotated[
        str, typer.Option(help="Which norm store to compare against.")
    ] = "v1",
    show_low: Annotated[bool, typer.Option(help="Include low-severity findings.")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """Check one agreement against the norms and report what stands out."""
    _setup_logging(verbose)
    from kwys.pipeline import analyse as run
    from kwys.report.render import render_html, render_terminal

    if not path.exists():
        console.print(f"[red]No such file:[/red] {path}")
        raise typer.Exit(1)

    result = run(
        path,
        role=role,
        domain=domain,
        user_city=city,
        user_state=state,
        corpus_version=corpus_version,
        show_low=show_low,
    )
    render_terminal(result, console)

    if html_out:
        html_out.write_text(render_html(result))
        console.print(f"[dim]HTML report -> {html_out}[/dim]")
    if json_out:
        json_out.write_text(json.dumps(result.to_evidence_json(), indent=2, default=str))
        console.print(f"[dim]Evidence JSON -> {json_out}[/dim]")


@app.command()
def segment(
    path: Annotated[Path, typer.Argument(help="The document to inspect.")],
    domain: Annotated[Domain, typer.Option()] = Domain.RESIDENTIAL_LEASE,
) -> None:
    """Show what the segmenter and classifier saw. Use this when a report looks wrong."""
    from kwys.classify.model import classify_clauses
    from kwys.segment.segmenter import segment_file

    clauses, low, parsed = segment_file(str(path))
    classify_clauses(clauses, domain)

    table = Table(title=f"{path.name} - {len(clauses)} clauses, {parsed.page_count} pages")
    table.add_column("id", style="cyan")
    table.add_column("d", justify="right")
    table.add_column("type", style="green")
    table.add_column("conf", justify="right")
    table.add_column("parent")
    table.add_column("text")

    for c in clauses:
        table.add_row(
            c.id,
            str(c.depth),
            c.clause_type or "-",
            f"{c.type_confidence:.2f}" if c.type_confidence else "-",
            (c.parent_heading or "-")[:20],
            c.text[:60],
        )
    console.print(table)

    if low:
        console.print(
            "[yellow]This document is not consistently numbered; the split above "
            "is unreliable.[/yellow]"
        )
    for w in parsed.warnings:
        console.print(f"[yellow]![/yellow] {w}")


@app.command("build-norms")
def build_norms(
    corpus: Annotated[Path, typer.Option(help="Directory of collected agreements (PDFs).")] = (
        DATA / "raw"
    ),
    domain: Annotated[Domain, typer.Option()] = Domain.RESIDENTIAL_LEASE,
    version: Annotated[str, typer.Option(help="Corpus version label.")] = "v1",
    out: Annotated[Path, typer.Option(help="Where to write the norm store.")] = DATA / "norms",
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """Build the reference distributions from a corpus of real agreements.

    Run once per corpus version. This is the maintainer step that everything
    else depends on: without it the analyser has nothing to compare against and
    will say so rather than guessing.
    """
    _setup_logging(verbose)
    from scripts.build_norms import build

    store, stats = build(corpus, domain, version)
    if store.is_empty:
        console.print(
            f"[red]No terms extracted from {corpus}.[/red] "
            "Put collected agreements there first - see PLAN.md section 3."
        )
        raise typer.Exit(1)

    store.save(out)

    table = Table(title=f"Norms built from {stats['documents']} documents")
    table.add_column("field", style="cyan")
    table.add_column("n", justify="right")
    table.add_column("usable", justify="center")
    table.add_column("median", justify="right")
    for key, info in store.coverage().items():
        norm = store.get(key)
        table.add_row(
            key,
            str(info["n"]),
            "[green]yes[/green]" if info["sufficient"] else "[red]no[/red]",
            f"{norm.median:g}" if norm and norm.values else "-",
        )
    console.print(table)
    console.print(f"[dim]Written to {out / version / domain.value}[/dim]")

    thin = [k for k, v in store.coverage().items() if not v["sufficient"]]
    if thin:
        console.print(
            f"[yellow]{len(thin)} field(s) are below the minimum sample size and "
            f"will not produce deviation findings.[/yellow]"
        )


@app.command("build-norms-from-judgments")
def build_norms_from_judgments(
    values: Annotated[Path, typer.Option(help="values.jsonl from harvest_judgments.py")] = (
        DATA / "corpus" / "judgments" / "values.jsonl"
    ),
    domain: Annotated[Domain, typer.Option()] = Domain.RESIDENTIAL_LEASE,
    version: Annotated[str, typer.Option()] = "judgments-v1",
    residential_only: Annotated[bool, typer.Option(help="drop non-residential judgments.")] = False,
    out: Annotated[Path, typer.Option()] = DATA / "norms",
) -> None:
    """Build norms from terms recited in published court judgments.

    Real executed agreements are private; blank templates carry no figures.
    Judgments quote the operative terms of agreements people actually signed.
    The catch, recorded in the store and shown in every report built on it: only
    disputed tenancies reach court.
    """
    from scripts.build_norms import build_from_judgments

    if not values.exists():
        console.print(
            f"[red]No harvested values at {values}.[/red]\n"
            "Run: python scripts/harvest_judgments.py --pages 5"
        )
        raise typer.Exit(1)

    store, stats = build_from_judgments(
        values, domain, version, residential_only=residential_only
    )
    if store.is_empty:
        console.print("[red]No usable values found.[/red]")
        raise typer.Exit(1)

    store.save(out)

    table = Table(title=f"Norms from {stats['judgments']} judgments")
    table.add_column("field", style="cyan")
    table.add_column("n", justify="right")
    table.add_column("usable", justify="center")
    table.add_column("median", justify="right")
    table.add_column("p25-p75", justify="right")
    for key, info in store.coverage().items():
        norm = store.get(key)
        table.add_row(
            key, str(info["n"]),
            "[green]yes[/green]" if info["sufficient"] else "[red]no[/red]",
            f"{norm.median:g}",
            f"{norm.quantile(0.25):g}-{norm.quantile(0.75):g}",
        )
    console.print(table)
    console.print(f"[yellow]{store.corpus_bias}[/yellow]")


@app.command()
def doctor() -> None:
    """Report what the system can and cannot currently speak to."""
    from kwys import config as C
    from kwys.norms.store import MIN_N, NormStore

    problems = C.validate_all()
    if problems:
        console.print("[red]Config problems:[/red]")
        for p in problems:
            console.print(f"  - {p}")
    else:
        console.print("[green]Config files cross-validate.[/green]")

    pending = C.unverified_anchors()
    if pending:
        console.print(
            f"\n[yellow]{len(pending)} statutory anchor(s) unverified "
            f"(skipped at runtime):[/yellow]"
        )
        for a in pending:
            console.print(f"  - {a}")
        console.print(
            "[dim]  Read the bare Act at indiacode.nic.in, confirm the section and "
            "figure, then set verified: true.[/dim]"
        )

    undeclared = C.undeclared_fields()
    if undeclared:
        console.print(
            f"\n[yellow]{len(undeclared)} numeric field(s) have no direction "
            f"declared and cannot produce findings:[/yellow]"
        )
        for f in undeclared:
            console.print(f"  - {f}")

    console.print("\n[bold]Reference corpus[/bold]")
    for domain in Domain:
        store = NormStore.load(DATA / "norms", domain.value, "v1")
        if store.is_empty:
            console.print(f"  {domain.value}: [red]no norms built[/red]")
            continue
        usable = sum(1 for v in store.coverage().values() if v["sufficient"])
        console.print(
            f"  {domain.value}: {len(store)} fields, {usable} above n={MIN_N}"
        )

    console.print("\n[bold]Classifier[/bold]")
    from kwys.classify.model import MODEL_DIR, active_classifier

    if active_classifier() == "trained":
        console.print(f"  [green]trained model[/green] at {MODEL_DIR}")
    else:
        console.print(
            "  [yellow]rule-based baseline[/yellow] "
            "[dim](no trained model; run scripts/train_classifier.py)[/dim]"
        )


if __name__ == "__main__":
    app()
