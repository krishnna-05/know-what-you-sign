"""Streamlit interface — the thing an actual user touches.

Design constraints that differ from the CLI:

  - The role question is unavoidable and comes FIRST. Every risk direction
    depends on it, and a default would silently produce an inverted report.
  - Findings show a distribution picture, not a percentile. Seeing your value
    sitting out on the tail is what makes it land for someone who cannot
    evaluate the reasoning.
  - The working is always one click away, never on by default.
  - Nothing is written to disk. The uploaded file lives in memory for the life
    of the request and is deleted straight after.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kwys import config as C  # noqa: E402
from kwys.models import Domain, Role, Severity  # noqa: E402
from kwys.norms.store import NormStore  # noqa: E402
from kwys.pipeline import DATA_ROOT, analyse  # noqa: E402
from kwys.report.render import DISCLAIMER  # noqa: E402

st.set_page_config(page_title="Know What You Sign", page_icon="📄", layout="centered")

ROLE_BY_DOMAIN = {
    Domain.RESIDENTIAL_LEASE: [
        (Role.TENANT, "I'm renting the place", "I am the tenant / lessee"),
        (Role.LANDLORD, "I own the place", "I am the landlord / lessor"),
    ],
    Domain.EMPLOYMENT_OFFER: [
        (Role.EMPLOYEE, "I'm taking the job", "I am the employee"),
        (Role.EMPLOYER, "I'm offering the job", "I am the employer"),
    ],
    Domain.CONSUMER_TOS: [
        (Role.CONSUMER, "I'm the user", "I am the customer / user"),
        (Role.PROVIDER, "I run the service", "I am the company"),
    ],
}

SEVERITY_STYLE = {
    Severity.HIGH: ("🔴", "Needs attention"),
    Severity.MEDIUM: ("🟡", "Worth a look"),
    Severity.LOW: ("⚪", "Minor"),
}


def _available_versions(domain: Domain) -> list[str]:
    """Built norm stores for this domain, REAL ONES FIRST.

    Plain alphabetical sorting put "SYNTHETIC-DEMO" above "judgments-v1", so the
    selector defaulted to invented numbers. The banner said so, but a default
    that has to be read to be safe is the wrong default: anyone skimming would
    take fabricated percentiles at face value. Synthetic corpora now sort last
    and can never be the initial selection.
    """
    root = DATA_ROOT / "norms"
    if not root.exists():
        return []
    names = [p.name for p in root.iterdir() if (p / domain.value).is_dir()]
    return sorted(names, key=lambda n: ("SYNTHETIC" in n.upper(), n.lower()))


def main() -> None:
    st.title("Know What You Sign")
    st.caption(
        "Upload an agreement. This tells you which clauses are unusual compared "
        "with other agreements — and which questions to ask before you sign."
    )

    with st.sidebar:
        st.subheader("What this is")
        st.write(
            "It compares each clause against what is normal across a body of "
            "real agreements. A term far outside that range is objectively "
            "unusual, and the report shows you the evidence for every flag."
        )
        st.subheader("What this is not")
        st.write(
            "It does not tell you whether a clause is legal or enforceable, and "
            "it is not a substitute for a lawyer."
        )

    domain = Domain(
        st.selectbox(
            "What kind of agreement is this?",
            [d.value for d in Domain],
            format_func=lambda v: C.taxonomy()["domains"][v]["display_name"],
        )
    )

    # Asked before upload, deliberately: the whole report inverts on this answer.
    options = ROLE_BY_DOMAIN[domain]
    picked = st.radio(
        "Which side are you on?",
        options,
        format_func=lambda o: o[1],
        horizontal=True,
        help="Every risk in this report depends on which side you are on. "
        "A long notice period is a burden for whoever has to give it.",
    )
    role = picked[0]

    if domain is Domain.CONSUMER_TOS:
        from kwys.classify.unfair import active_detector

        corpus_version = "v1"  # unused on this path: no numeric norms apply
        if active_detector() == "rules":
            st.info(
                "Using the rule baseline for unfair clauses. It finds roughly a "
                "third of what an expert would flag — train the detector for "
                "better coverage."
            )
        versions = []
    elif not (versions := _available_versions(domain)):
        st.warning(
            "No reference corpus is built yet, so nothing can be compared "
            "against what is normal. One-sided obligations and missing clauses "
            "will still be reported. Run `kwys build-norms` to enable the rest."
        )
        corpus_version = "v1"
    else:
        corpus_version = st.selectbox("Compare against", versions, index=0)
        if "SYNTHETIC" in corpus_version.upper():
            st.error(
                "**Synthetic demo data.** The comparisons below are computed "
                "against invented numbers to show the pipeline works. They say "
                "nothing about real agreements."
            )

    col1, col2 = st.columns(2)
    with col1:
        city = st.text_input("Your city (optional)", placeholder="Bengaluru")
    with col2:
        state = st.text_input("Your state (optional)", placeholder="Karnataka")

    uploaded = st.file_uploader("The agreement (PDF)", type=["pdf"])
    if uploaded is None:
        st.info("Your document is analysed on this machine and is never stored.")
        return

    with st.status("Reading the document...", expanded=False) as status:
        # NamedTemporaryFile rather than a project directory: the file must not
        # outlive the request, and must never land somewhere backed up or synced.
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(uploaded.getvalue())
            tmp.flush()
            status.update(label="Finding clauses and comparing against the norms...")
            result = analyse(
                tmp.name,
                role=role,
                domain=domain,
                user_city=city or None,
                user_state=state or None,
                corpus_version=corpus_version,
            )
        status.update(label="Done", state="complete")

    _render(result, domain, corpus_version)


def _render(result, domain: Domain, corpus_version: str) -> None:
    st.divider()
    high = len(result.by_severity(Severity.HIGH))
    med = len(result.by_severity(Severity.MEDIUM))

    a, b, c = st.columns(3)
    a.metric("Clauses checked", result.clauses_checked)
    b.metric("Need attention", high)
    c.metric("Worth a look", med)

    for w in result.warnings:
        st.warning(w)
    if result.corpus_bias:
        st.warning(f"About the comparison data: {result.corpus_bias}")

    if not result.findings:
        st.success("Nothing stood out.")
        st.caption(
            "That is not the same as saying this contract is fine — only that "
            "nothing fell outside the range this tool can check."
        )

    norms = NormStore.load(DATA_ROOT / "norms", domain.value, corpus_version)

    for i, f in enumerate(result.findings, start=1):
        icon, label = SEVERITY_STYLE[f.severity]
        with st.container(border=True):
            st.markdown(f"**{icon} {i}. {f.headline}**  \n`{label}` · clause {f.clause_id}")
            st.write(f.plain_language)

            ev = f.evidence
            if ev.norm and ev.norm.sufficient:
                _distribution_chart(norms, ev)

            if f.question_to_ask:
                st.info(f"**Ask:** {f.question_to_ask}")

            with st.expander("Show the working"):
                if ev.clause_text:
                    st.caption("From your document:")
                    st.markdown(f"> {ev.clause_text[:800]}")
                rows = {}
                if ev.term:
                    rows["Extracted value"] = f"{ev.term.value} {ev.term.unit or ''}"
                    rows["Found in the text as"] = f'"{ev.term.raw}"'
                if ev.norm:
                    n = ev.norm
                    rows["Typical (median)"] = f"{n.median:g}"
                    rows["Percentile"] = (
                        f"{n.percentile:.0%} (95% CI {n.ci_low:.0%}–{n.ci_high:.0%})"
                    )
                    rows["Agreements compared"] = str(n.n)
                    rows["Robust z-score"] = f"{n.robust_z:+.2f}"
                    rows["Corpus version"] = n.corpus_version
                if ev.direction_rationale:
                    rows["Why this direction is worse"] = ev.direction_rationale
                if ev.anchor:
                    rows["Statute"] = ev.anchor.source
                st.table({"": list(rows), " ": list(rows.values())})

    st.divider()
    st.caption(DISCLAIMER)

    html = _html(result)
    st.download_button(
        "Download this report", html, file_name="know-what-you-sign.html",
        mime="text/html",
    )


# Emphasis form: the reader's own value is the point, every other agreement is
# context. Bars with a visible count, not the earlier histogram whose y-axis was
# hidden - which left the bars meaning nothing at all. Gray is the de-emphasis
# role rather than a failed categorical slot; the pair separates at CVD
# delta-E 9.1 and both clear 3:1 on either surface.
_CONTEXT_INK = "#898781"   # muted; identical in light and dark
_YOURS_INK = "#d03b3b"     # status/critical, 4.68 light / 3.62 dark


def _distribution_chart(norms: NormStore, ev) -> None:
    """Show where the reader's value sits among comparable agreements.

    The picture is the point. "84th percentile" is precise and inert; one red bar
    standing apart from the others is legible to someone with no training, which
    is the entire audience for this tool. It is also more honest: the reader can
    see that a fair number of agreements DO ask what theirs asks, which a single
    percentile hides.
    """
    import altair as alt
    import pandas as pd

    norm = norms.get(ev.norm.field)
    if norm is None or not norm.values:
        return

    yours = float(ev.norm.value)
    typical = float(norm.median)

    counts = pd.Series(norm.values).value_counts().sort_index().reset_index()
    counts.columns = ["value", "n"]
    counts["mine"] = counts["value"].eq(yours)

    # Headroom so the labels sit above the tallest bar instead of clipping it.
    headroom = float(counts["n"].max()) * 1.20
    lo, hi = float(counts["value"].min()), float(counts["value"].max())

    bars = alt.Chart(counts).mark_bar(
        size=14, cornerRadiusTopLeft=3, cornerRadiusTopRight=3
    ).encode(
        x=alt.X(
            "value:Q",
            scale=alt.Scale(nice=False, padding=26),
            axis=alt.Axis(title=None, grid=False, tickCount=6,
                          domainColor=_CONTEXT_INK, tickColor=_CONTEXT_INK,
                          labelColor=_CONTEXT_INK, labelFontSize=11),
        ),
        y=alt.Y(
            "n:Q",
            scale=alt.Scale(domain=[0, headroom], nice=False),
            axis=alt.Axis(title="agreements", grid=False, tickCount=3, domain=False,
                          ticks=False, labelColor=_CONTEXT_INK,
                          titleColor=_CONTEXT_INK, labelFontSize=10, titleFontSize=10),
        ),
        color=alt.condition(alt.datum.mine, alt.value(_YOURS_INK),
                            alt.value(_CONTEXT_INK)),
        tooltip=[alt.Tooltip("value:Q", title="value"),
                 alt.Tooltip("n:Q", title="agreements")],
    )

    layers = [bars]
    for value, label, ink, bold in (
        (typical, f"usual: {typical:g}", _CONTEXT_INK, "normal"),
        (yours, f"yours: {yours:g}", _YOURS_INK, "bold"),
    ):
        # Anchor an edge label inward so the plot bound cannot clip it. Direct
        # labels rather than a legend: with two marks a legend costs more room
        # than it explains, and a status colour must never carry meaning alone.
        align = "right" if value >= hi else ("left" if value <= lo else "center")
        layers.append(
            alt.Chart(pd.DataFrame([{"v": value, "t": label}])).mark_text(
                baseline="top", dy=2, fontSize=12, color=ink,
                align=align, fontWeight=bold,
            ).encode(x="v:Q", y=alt.value(0), text="t:N")
        )

    st.altair_chart(
        alt.layer(*layers).properties(height=140).configure_view(stroke=None),
        use_container_width=True,
    )
    st.caption(
        f"Each bar is how many of {norm.n} comparable agreements asked that much "
        f"\u00b7 {_share_sentence(ev.norm)}"
    )


def _share_sentence(norm) -> str:
    """Say the comparison in counts. "84th percentile" means nothing to most people."""
    share = 1.0 - norm.percentile
    in_hundred = max(1, round(share * 100))
    return f"about {in_hundred} in 100 ask as much as yours"


def _html(result) -> str:
    from kwys.report.render import render_html

    return render_html(result)


if __name__ == "__main__":
    main()
