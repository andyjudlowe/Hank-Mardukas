"""Offline NYC geography: ZIP -> lat/lon, ZIP/text -> borough, distance & adjacency.

No external geocoding API. ZIP centroids cover common NYC ZIPs; anything missing
falls back to the borough centroid (derived from the ZIP prefix or location text).
"""
from __future__ import annotations

import math
import re
from typing import Optional, Tuple

BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]

# Approximate borough centroids (lat, lon).
BOROUGH_CENTROID = {
    "Manhattan": (40.7831, -73.9712),
    "Brooklyn": (40.6782, -73.9442),
    "Queens": (40.7282, -73.7949),
    "Bronx": (40.8448, -73.8648),
    "Staten Island": (40.5795, -74.1502),
}

# Which boroughs share a border (used as the geo gate when exact coords absent).
BOROUGH_ADJACENCY = {
    "Manhattan": {"Manhattan", "Bronx", "Brooklyn", "Queens"},
    "Bronx": {"Bronx", "Manhattan", "Queens"},
    "Brooklyn": {"Brooklyn", "Queens", "Manhattan", "Staten Island"},
    "Queens": {"Queens", "Brooklyn", "Manhattan", "Bronx"},
    "Staten Island": {"Staten Island", "Brooklyn"},
}

# A representative set of NYC ZIP centroids. Missing ZIPs fall back to borough.
ZIP_CENTROIDS = {
    # Manhattan
    "10001": (40.7506, -73.9971), "10002": (40.7156, -73.9863),
    "10003": (40.7322, -73.9889), "10009": (40.7264, -73.9786),
    "10011": (40.7421, -74.0008), "10016": (40.7459, -73.9786),
    "10019": (40.7657, -73.9870), "10022": (40.7585, -73.9683),
    "10025": (40.7986, -73.9681), "10027": (40.8115, -73.9536),
    "10029": (40.7916, -73.9438), "10031": (40.8253, -73.9498),
    "10032": (40.8389, -73.9425), "10128": (40.7816, -73.9505),
    # Bronx
    "10451": (40.8200, -73.9230), "10452": (40.8377, -73.9230),
    "10453": (40.8525, -73.9126), "10456": (40.8300, -73.9080),
    "10458": (40.8624, -73.8884), "10462": (40.8430, -73.8590),
    "10463": (40.8810, -73.9060), "10467": (40.8696, -73.8714),
    "10468": (40.8676, -73.9006), "10469": (40.8690, -73.8470),
    # Brooklyn
    "11201": (40.6940, -73.9903), "11203": (40.6494, -73.9344),
    "11205": (40.6948, -73.9663), "11206": (40.7019, -73.9419),
    "11207": (40.6707, -73.8939), "11211": (40.7127, -73.9533),
    "11215": (40.6627, -73.9857), "11216": (40.6809, -73.9494),
    "11217": (40.6829, -73.9787), "11218": (40.6435, -73.9764),
    "11220": (40.6413, -74.0146), "11221": (40.6912, -73.9277),
    "11225": (40.6627, -73.9547), "11226": (40.6464, -73.9569),
    "11229": (40.6004, -73.9446), "11233": (40.6786, -73.9209),
    "11234": (40.6079, -73.9209), "11235": (40.5836, -73.9505),
    "11237": (40.7041, -73.9209), "11238": (40.6796, -73.9647),
    # Queens
    "11101": (40.7505, -73.9370), "11102": (40.7720, -73.9260),
    "11103": (40.7626, -73.9130), "11104": (40.7445, -73.9200),
    "11105": (40.7785, -73.9060), "11106": (40.7616, -73.9320),
    "11354": (40.7690, -73.8270), "11355": (40.7510, -73.8210),
    "11368": (40.7498, -73.8627), "11372": (40.7515, -73.8836),
    "11373": (40.7390, -73.8780), "11375": (40.7210, -73.8460),
    "11377": (40.7440, -73.9050), "11385": (40.7000, -73.8880),
    "11411": (40.6940, -73.7360), "11432": (40.7150, -73.7940),
    "11691": (40.6010, -73.7560),
    # Staten Island
    "10301": (40.6440, -74.0840), "10304": (40.6090, -74.0850),
    "10306": (40.5710, -74.1290), "10309": (40.5310, -74.2200),
    "10312": (40.5450, -74.1780), "10314": (40.6010, -74.1640),
}

_BOROUGH_TEXT_PATTERNS = [
    ("Staten Island", re.compile(r"staten\s*island|\bsi\b", re.I)),
    ("Manhattan", re.compile(r"manhattan|harlem|chelsea|tribeca|soho|midtown|"
                             r"upper\s*(east|west)|lower\s*east|washington\s*heights|"
                             r"east\s*village|west\s*village|inwood|nyc\b|new\s*york,?\s*ny",
                             re.I)),
    ("Brooklyn", re.compile(r"brooklyn|bushwick|williamsburg|bed[-\s]?stuy|park\s*slope|"
                            r"crown\s*heights|flatbush|bay\s*ridge|greenpoint|"
                            r"sunset\s*park|canarsie|\bbk\b", re.I)),
    ("Bronx", re.compile(r"bronx|riverdale|fordham|pelham|throgs?\s*neck", re.I)),
    ("Queens", re.compile(r"queens|astoria|flushing|jamaica|jackson\s*heights|"
                          r"long\s*island\s*city|\blic\b|elmhurst|corona|"
                          r"forest\s*hills|ridgewood|far\s*rockaway|woodside", re.I)),
]


def zip_to_borough(zipcode: Optional[str]) -> Optional[str]:
    if not zipcode:
        return None
    z = zipcode.strip()[:5]
    if not z.isdigit():
        return None
    n = int(z)
    if 10001 <= n <= 10282:
        return "Manhattan"
    if 10301 <= n <= 10314:
        return "Staten Island"
    if 10451 <= n <= 10475:
        return "Bronx"
    if 11201 <= n <= 11256:
        return "Brooklyn"
    if (11004 <= n <= 11109) or (11351 <= n <= 11697):
        return "Queens"
    return None


def borough_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for borough, pat in _BOROUGH_TEXT_PATTERNS:
        if pat.search(text):
            return borough
    return None


def zip_to_latlon(zipcode: Optional[str]) -> Optional[Tuple[float, float]]:
    if not zipcode:
        return None
    z = zipcode.strip()[:5]
    if z in ZIP_CENTROIDS:
        return ZIP_CENTROIDS[z]
    borough = zip_to_borough(z)
    if borough:
        return BOROUGH_CENTROID[borough]
    return None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8  # earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def boroughs_adjacent(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return True  # unknown borough -> don't hard-block on geography
    return b in BOROUGH_ADJACENCY.get(a, {a})
