from __future__ import annotations

from kwys import config as C
from kwys.models import Domain, Role


def test_configs_cross_validate():
    assert C.validate_all() == []


def test_direction_map_flips_by_role():
    """The same term is a burden for one side and a protection for the other.
    If this ever stops holding, the tool is telling tenants that a small deposit
    is risky."""
    tenant, _ = C.direction_for("security_deposit.deposit_months", Role.TENANT)
    landlord, _ = C.direction_for("security_deposit.deposit_months", Role.LANDLORD)
    assert tenant == -landlord


def test_every_direction_entry_has_a_rationale():
    """A field nobody can explain in a sentence has no business producing a flag."""
    for field_key, roles in C.direction_map().items():
        for role, spec in roles.items():
            assert spec.get("rationale"), f"{field_key}/{role} has no rationale"
            assert spec["direction"] in (1, -1)


def test_undeclared_direction_returns_none_not_neutral():
    """None must mean "nobody decided", not "no risk" — the scorer skips these."""
    assert C.direction_for("no_such_type.no_such_field", Role.TENANT) is None


def test_unverified_statutory_anchors_are_never_used(monkeypatch):
    """The safety property: a citation nobody has checked against the bare Act
    must not reach a user who cannot check it themselves.

    Tests the MECHANISM rather than the current contents of the file. An earlier
    version asserted that unverified anchors existed, which quietly became a
    test of "nobody has done the research yet" and broke the moment someone did.
    """
    fake = {
        "anchors": {
            "security_deposit.deposit_months": {
                "residential": {
                    "value": 2, "comparison": "max", "unit": "months_of_rent",
                    "source": "Unchecked Act, s.1", "applies_in": ["ALL_INDIA"],
                    "verified": False,
                }
            }
        }
    }
    monkeypatch.setattr(C, "_anchors_raw", lambda: fake)
    assert C.statutory_anchor("security_deposit.deposit_months", 6.0) is None
    assert C.unverified_anchors() == ["security_deposit.deposit_months/residential "
                                      "— Unchecked Act, s.1"]


def test_verified_anchor_is_used_and_reports_exceedance():
    """The other half: once someone has done the checking, the anchor works."""
    hit = C.statutory_anchor("security_deposit.deposit_months", 6.0, user_state="Assam")
    assert hit is not None, "the Model Tenancy Act deposit cap has been verified"
    assert hit.exceeded, "six months' rent exceeds the two-month cap"
    assert hit.applies, "Assam adopted the Model Tenancy Act"


def test_model_law_does_not_bind_a_non_adopting_state():
    """The Model Tenancy Act binds nobody until a state adopts it, and only a
    few have. Telling a reader elsewhere that "the law caps this" would be false
    in the direction that starts an argument they cannot win."""
    hit = C.statutory_anchor("security_deposit.deposit_months", 6.0, user_state="Karnataka")
    assert hit is not None and hit.exceeded
    assert not hit.applies, "Karnataka has not formally adopted the Model Act"


def test_every_verified_anchor_records_who_checked_it_and_when():
    raw = C._anchors_raw()["anchors"]
    for field_key, variants in raw.items():
        for variant, spec in variants.items():
            if spec.get("verified"):
                assert spec.get("verified_by"), f"{field_key}/{variant} has no verifier"
                assert spec.get("verified_on"), f"{field_key}/{variant} has no date"
                assert spec.get("quote"), (
                    f"{field_key}/{variant} is marked verified but quotes no text; "
                    "a citation nobody can check is not verification"
                )


def test_expected_clauses_are_real_types():
    for domain in Domain:
        known = set(C.clause_types())
        assert set(C.expected_clauses(domain)) <= known
