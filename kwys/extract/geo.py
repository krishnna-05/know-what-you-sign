"""Distance between the signatory and the venue where disputes must be heard.

An arbitration seat or exclusive jurisdiction clause naming a distant city is
one of the most effective ways to make a contract practically unenforceable
against the drafter, and it is invisible to a lay reader. "The courts at New
Delhi alone shall have exclusive jurisdiction" reads as boilerplate. For a
tenant in Kochi disputing a deposit of Rs.60,000, it means any claim costs more
in travel and lawyers than it could ever recover.

Distance in kilometres turns that from a vague unfairness into a measurable,
objective quantity - which is exactly the kind of thing this project exists to
compute. It is also the one field here that is genuinely novel; nobody else
scores venue clauses this way.

The gazetteer is embedded rather than fetched: contracts are analysed offline
by design, and a network lookup would send the user's city to a third party.
"""

from __future__ import annotations

import math
import re
import unicodedata

EARTH_RADIUS_KM = 6371.0

# Indian cities that plausibly appear as an arbitration seat or jurisdiction,
# plus common alternate and pre-renaming names. Coordinates to ~3 decimal
# places, which is far finer than this measure needs.
CITIES: dict[str, tuple[float, float]] = {
    "mumbai": (19.076, 72.877), "bombay": (19.076, 72.877),
    "delhi": (28.614, 77.209), "new delhi": (28.614, 77.209),
    "bengaluru": (12.972, 77.594), "bangalore": (12.972, 77.594),
    "hyderabad": (17.385, 78.487), "secunderabad": (17.440, 78.498),
    "chennai": (13.083, 80.270), "madras": (13.083, 80.270),
    "kolkata": (22.573, 88.364), "calcutta": (22.573, 88.364),
    "pune": (18.520, 73.857), "poona": (18.520, 73.857),
    "ahmedabad": (23.023, 72.571), "surat": (21.170, 72.831),
    "jaipur": (26.912, 75.787), "lucknow": (26.847, 80.947),
    "kanpur": (26.450, 80.332), "nagpur": (21.146, 79.088),
    "indore": (22.719, 75.857), "bhopal": (23.260, 77.413),
    "visakhapatnam": (17.687, 83.219), "vizag": (17.687, 83.219),
    "patna": (25.594, 85.138), "vadodara": (22.307, 73.181),
    "baroda": (22.307, 73.181), "ghaziabad": (28.670, 77.454),
    "ludhiana": (30.901, 75.857), "agra": (27.177, 78.008),
    "nashik": (19.997, 73.790), "faridabad": (28.408, 77.318),
    "meerut": (28.984, 77.706), "rajkot": (22.303, 70.802),
    "varanasi": (25.317, 82.973), "banaras": (25.317, 82.973),
    "srinagar": (34.084, 74.797), "aurangabad": (19.876, 75.343),
    "dhanbad": (23.796, 86.430), "amritsar": (31.634, 74.872),
    "allahabad": (25.436, 81.847), "prayagraj": (25.436, 81.847),
    "ranchi": (23.344, 85.310), "howrah": (22.595, 88.263),
    "coimbatore": (11.017, 76.956), "jabalpur": (23.181, 79.956),
    "gwalior": (26.218, 78.183), "vijayawada": (16.507, 80.648),
    "jodhpur": (26.238, 73.024), "madurai": (9.925, 78.120),
    "raipur": (21.251, 81.630), "kota": (25.213, 75.865),
    "chandigarh": (30.733, 76.779), "guwahati": (26.145, 91.736),
    "solapur": (17.659, 75.906), "hubli": (15.364, 75.124),
    "mysuru": (12.295, 76.639), "mysore": (12.295, 76.639),
    "tiruchirappalli": (10.790, 78.704), "trichy": (10.790, 78.704),
    "bareilly": (28.367, 79.430), "aligarh": (27.897, 78.088),
    "moradabad": (28.838, 78.773), "gurugram": (28.459, 77.026),
    "gurgaon": (28.459, 77.026), "noida": (28.535, 77.391),
    "jalandhar": (31.326, 75.576), "bhubaneswar": (20.296, 85.825),
    "salem": (11.665, 78.146), "warangal": (17.978, 79.594),
    "guntur": (16.306, 80.437), "bhiwandi": (19.297, 73.063),
    "saharanpur": (29.968, 77.546), "gorakhpur": (26.760, 83.374),
    "bikaner": (28.022, 73.312), "amravati": (20.937, 77.779),
    "noida extension": (28.610, 77.430), "thane": (19.218, 72.978),
    "navi mumbai": (19.033, 73.030), "kalyan": (19.243, 73.130),
    "vasai": (19.391, 72.830), "kochi": (9.932, 76.267),
    "cochin": (9.932, 76.267), "ernakulam": (9.981, 76.299),
    "thiruvananthapuram": (8.524, 76.937), "trivandrum": (8.524, 76.937),
    "kozhikode": (11.259, 75.780), "calicut": (11.259, 75.780),
    "thrissur": (10.527, 76.214), "kollam": (8.893, 76.614),
    "dehradun": (30.317, 78.032), "shimla": (31.104, 77.173),
    "jammu": (32.727, 74.857), "udaipur": (24.586, 73.712),
    "ajmer": (26.449, 74.639), "cuttack": (20.463, 85.883),
    "siliguri": (26.727, 88.395), "durgapur": (23.520, 87.311),
    "asansol": (23.685, 86.974), "jamshedpur": (22.804, 86.203),
    "bokaro": (23.669, 86.151), "belgaum": (15.850, 74.498),
    "mangaluru": (12.914, 74.856), "mangalore": (12.914, 74.856),
    "tirupati": (13.629, 79.419), "nellore": (14.443, 79.987),
    "rajahmundry": (17.005, 81.777), "kurnool": (15.828, 78.037),
    "puducherry": (11.914, 79.812), "pondicherry": (11.914, 79.812),
    "panaji": (15.491, 73.827), "goa": (15.300, 74.124),
    "imphal": (24.817, 93.937), "shillong": (25.579, 91.893),
    "agartala": (23.831, 91.286), "aizawl": (23.727, 92.718),
    "itanagar": (27.084, 93.605), "kohima": (25.674, 94.110),
    "gangtok": (27.339, 88.606), "dispur": (26.141, 91.790),
    "raigarh": (21.897, 83.395), "bilaspur": (22.080, 82.155),
    "muzaffarpur": (26.120, 85.364), "gaya": (24.796, 85.000),
    "bhagalpur": (25.244, 86.972), "darbhanga": (26.152, 85.898),
    "hisar": (29.152, 75.722), "panipat": (29.391, 76.977),
    "karnal": (29.686, 76.990), "rohtak": (28.895, 76.607),
    "sonipat": (28.995, 77.018), "ambala": (30.378, 76.777),
    "patiala": (30.340, 76.386), "bathinda": (30.211, 74.945),
    "mohali": (30.705, 76.717), "zirakpur": (30.643, 76.818),
}

# "the courts at New Delhi", "seat of arbitration shall be Mumbai"
_NOISE = re.compile(
    r"\b(?:the|at|in|of|city|cities|courts?|tribunal|district|state|only|alone"
    r"|shall|have|having|jurisdiction|seat|venue|place)\b",
    re.I,
)


def normalise(name: str) -> str:
    """Reduce a place name as written in a contract to a lookup key."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _NOISE.sub(" ", text.lower())
    text = re.sub(r"[^a-z\s]", " ", text)
    return " ".join(text.split())


def lookup(name: str) -> tuple[float, float] | None:
    """Coordinates for a place named in a contract, or None if unrecognised."""
    key = normalise(name)
    if not key:
        return None
    if key in CITIES:
        return CITIES[key]
    # "Bangalore Urban", "Mumbai Suburban" - take the leading known city.
    for token_count in (3, 2, 1):
        words = key.split()
        for i in range(len(words) - token_count + 1):
            candidate = " ".join(words[i : i + token_count])
            if candidate in CITIES:
                return CITIES[candidate]
    return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def distance_between(place_a: str, place_b: str) -> float | None:
    """Kilometres between two places named in a document, or None if unknown.

    None is returned when either name is unrecognised, and the caller must not
    treat that as zero: an unknown venue is not a nearby one.
    """
    coord_a, coord_b = lookup(place_a), lookup(place_b)
    if coord_a is None or coord_b is None:
        return None
    return round(haversine_km(coord_a, coord_b), 1)


def is_same_city(place_a: str, place_b: str, tolerance_km: float = 40.0) -> bool | None:
    """Whether two names refer to effectively the same place.

    The tolerance covers a metropolitan region: courts in Gurugram or Noida are
    not a hardship for someone living in Delhi.
    """
    km = distance_between(place_a, place_b)
    return None if km is None else km <= tolerance_km
