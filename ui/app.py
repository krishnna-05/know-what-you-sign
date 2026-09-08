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
}

SEVERITY_STYLE = {
    Severity.HIGH: ("🔴", "Needs attention"),
    Severity.MEDIUM: ("🟡", "Worth a look"),
    Severity.LOW: ("⚪", "Minor"),
}


def _available_versions(domain: Domain) -> list[str]:
    root = DATA_ROOT / "norms"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / domain.value).is_dir())


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

    versions = _available_versions(domain)
    if not versions:
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


def _distribution_chart(norms: NormStore, ev) -> None:
    """Show where the user's value sits among comparable agreements.

    The picture is the point. "96th percentile" is precise and inert; a marker
    far out on the tail is immediately legible to someone with no training.
    """
    import altair as alt
    import pandas as pd

    norm = norms.get(ev.norm.field)
    if norm is None or not norm.values:
        return

    df = pd.DataFrame({"value": norm.values})
    base = (
        alt.Chart(df)
        .mark_bar(opacity=0.75)
        .encode(
            x=alt.X("value:Q", bin=alt.Bin(maxbins=24), title="other agreements"),
            y=alt.Y("count()", title=None, axis=None),
        )
    )
    marker = (
        alt.Chart(pd.DataFrame({"value": [ev.norm.value]}))
        .mark_rule(color="#b3261e", size=3)
        .encode(x="value:Q")
    )
    st.altair_chart((base + marker).properties(height=110), use_container_width=True)
    st.caption(
        f"Red line is your agreement · {norm.n} comparable agreements · "
        f"most sit around {norm.median:g}"
    )


def _html(result) -> str:
    from kwys.report.render import render_html

    return render_html(result)


if __name__ == "__main__":
    main()
