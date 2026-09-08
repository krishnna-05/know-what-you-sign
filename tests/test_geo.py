"""Venue distance — the measure behind the arbitration-seat finding.

A clause naming a distant seat is one of the most effective ways to make a
contract unenforceable against the drafter, and it is invisible to a lay reader.
Getting the distance wrong in either direction matters: a false alarm on a local
venue erodes trust, and a missed distant venue hides the finding this measure
exists to surface.
"""

from __future__ import annotations

import pytest

from kwys.extract.geo import distance_between, haversine_km, is_same_city, lookup, normalise


@pytest.mark.parametrize(
    "written,expected_key",
    [
        ("the courts at New Delhi", "new delhi"),
        ("Seat of arbitration shall be Mumbai", "mumbai"),
        ("BENGALURU", "bengaluru"),
        ("Bangalore Urban District", "bangalore urban"),
    ],
)
def test_contract_phrasing_is_stripped_to_a_place(written, expected_key):
    assert lookup(written) is not None, f"{normalise(written)!r} did not resolve"


def test_renamed_cities_are_the_same_place():
    """Contracts use both names, often in the same document."""
    for old, new in [("Bombay", "Mumbai"), ("Madras", "Chennai"),
                     ("Calcutta", "Kolkata"), ("Bangalore", "Bengaluru")]:
        assert distance_between(old, new) == 0.0


def test_metropolitan_region_is_not_a_hardship():
    """Courts in Thane or Gurugram are not a burden for someone in the
    neighbouring metro, and flagging them would be noise."""
    assert is_same_city("Mumbai", "Thane")
    assert is_same_city("Delhi", "Gurgaon")


def test_genuinely_distant_venue_is_recognised():
    km = distance_between("Kochi", "New Delhi")
    assert km is not None and km > 2000


def test_unknown_place_returns_none_not_zero():
    """An unrecognised venue is not a nearby one. Returning 0 would silently
    turn 'we don't know' into 'no problem'."""
    assert distance_between("Atlantis", "Mumbai") is None
    assert is_same_city("Atlantis", "Mumbai") is None


def test_haversine_against_a_known_distance():
    # Delhi to Mumbai is roughly 1150 km great-circle.
    km = haversine_km((28.614, 77.209), (19.076, 72.877))
    assert 1100 < km < 1200
