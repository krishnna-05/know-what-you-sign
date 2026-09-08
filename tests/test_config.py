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


def test_unverified_statutory_anchors_are_never_used():
    """The whole safety property: a citation nobody has checked against the bare
    Act must not reach a user who cannot check it themselves."""
    assert C.unverified_anchors(), "fixture expects anchors still pending verification"
    assert C.statutory_anchor("security_deposit.deposit_months", 6.0) is None


def test_expected_clauses_are_real_types():
    for domain in Domain:
        known = set(C.clause_types())
        assert set(C.expected_clauses(domain)) <= known
