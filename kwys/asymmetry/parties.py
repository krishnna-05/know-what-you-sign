"""Working out who is who, so obligations can be attributed to a side.

Contracts define their own vocabulary in the preamble — "hereinafter referred to
as the LESSEE" — and then use that label for forty pages. Resolving those labels
to roles is what lets the system say "you must give six months' notice; they must
give fifteen days" rather than reporting two unrelated numbers.

Deliberately dictionary-and-regex rather than learned: the preamble construction
is near-universal, and a wrong party attribution silently inverts the direction
of every risk judgement downstream. That failure must be inspectable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kwys.models import Domain, Role

# Canonical aliases by role. Lowercased, matched on word boundaries.
ROLE_ALIASES: dict[Role, set[str]] = {
    Role.TENANT: {
        "lessee", "tenant", "licensee", "occupant", "renter",
        "party of the second part", "second party",
    },
    Role.LANDLORD: {
        "lessor", "landlord", "owner", "licensor", "landlady",
        "party of the first part", "first party",
    },
    Role.EMPLOYEE: {
        "employee", "candidate", "appointee", "executive", "staff member",
        "the said employee",
    },
    Role.EMPLOYER: {
        "employer", "company", "organisation", "organization", "management",
        "the firm", "corporation",
    },
}

DOMAIN_ROLES: dict[Domain, tuple[Role, Role]] = {
    Domain.RESIDENTIAL_LEASE: (Role.TENANT, Role.LANDLORD),
    Domain.EMPLOYMENT_OFFER: (Role.EMPLOYEE, Role.EMPLOYER),
}

# "hereinafter referred to as the LESSEE" / "(hereinafter the "Tenant")"
_DEFINITION = re.compile(
    r"""hereinafter\s+
        (?:referred\s+to\s+as\s+|called\s+|the\s+)?
        (?:the\s+)?["'“‘]?(?P<label>[A-Za-z][A-Za-z\s]{2,40}?)["'”’]?
        \s*[),.]""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class PartyMap:
    """Which labels in this document mean which role."""

    domain: Domain
    label_to_role: dict[str, Role] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    def resolve(self, text: str) -> Role | None:
        """Return the role named in a fragment, or None if ambiguous or absent.

        None is returned when BOTH sides appear, because a sentence naming both
        parties tells us nothing about who is bound without a parse — the caller
        must not guess.
        """
        lowered = text.lower()
        hits = {
            role
            for label, role in self.label_to_role.items()
            if re.search(rf"\b{re.escape(label)}\b", lowered)
        }
        if len(hits) == 1:
            return next(iter(hits))
        return None

    def mentions(self, text: str) -> set[Role]:
        lowered = text.lower()
        return {
            role
            for label, role in self.label_to_role.items()
            if re.search(rf"\b{re.escape(label)}\b", lowered)
        }

    @property
    def counterparty_of(self) -> dict[Role, Role]:
        a, b = DOMAIN_ROLES[self.domain]
        return {a: b, b: a}


def build_party_map(text: str, domain: Domain) -> PartyMap:
    """Build the label -> role map for one document.

    Two passes: explicit "hereinafter" definitions first, then the standard
    aliases for whatever the definitions missed. Documents that skip the
    preamble formality are common enough that the alias fallback is not
    optional.
    """
    pmap = PartyMap(domain=domain)
    valid_roles = set(DOMAIN_ROLES[domain])

    for m in _DEFINITION.finditer(text):
        label = " ".join(m.group("label").split()).lower().strip()
        if not label or len(label) > 40:
            continue
        role = _role_for_label(label, valid_roles)
        if role:
            pmap.label_to_role[label] = role
        else:
            pmap.unresolved.append(label)

    lowered = text.lower()
    for role in valid_roles:
        for alias in ROLE_ALIASES[role]:
            if alias not in pmap.label_to_role and re.search(
                rf"\b{re.escape(alias)}\b", lowered
            ):
                pmap.label_to_role[alias] = role

    return pmap


def _role_for_label(label: str, valid_roles: set[Role]) -> Role | None:
    for role in valid_roles:
        for alias in ROLE_ALIASES[role]:
            if alias in label or label in alias:
                return role
    return None
