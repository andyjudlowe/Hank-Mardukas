"""Pure-logic tests for scraper + normalization helpers (no network)."""
from petmatch.geo import (boroughs_adjacent, haversine_miles, zip_to_borough,
                          zip_to_latlon)
from petmatch.models import Sex, Species
from petmatch.normalize import detect_colors, detect_sex, detect_species, detect_zip
from petmatch.sources.craigslist import (IMG_RE, _looks_like_pet,
                                         _status_from_title)
from petmatch.sources.petco import _clean_images, _is_non_nyc, _species_from_str
from petmatch.models import Status


def test_geo_zip_to_borough():
    assert zip_to_borough("11201") == "Brooklyn"
    assert zip_to_borough("10001") == "Manhattan"
    assert zip_to_borough("10458") == "Bronx"
    assert zip_to_borough("14219") is None  # Buffalo -> not NYC


def test_geo_distance_and_adjacency():
    assert haversine_miles(40.7, -74.0, 40.7, -74.0) == 0.0
    assert boroughs_adjacent("Manhattan", "Brooklyn") is True
    assert boroughs_adjacent("Staten Island", "Bronx") is False
    assert boroughs_adjacent(None, "Bronx") is True  # unknown -> don't block


def test_normalize_text_parsing():
    assert detect_species("lost black and white kitten") == Species.cat
    assert detect_species("found a small brown dog") == Species.dog
    assert set(detect_colors("black and white cat")) == {"black", "white"}
    assert detect_sex("she is spayed") == Sex.female
    assert detect_zip("near 11215 Park Slope") == "11215"


def test_craigslist_helpers():
    assert _status_from_title("FOUND Cat in Brooklyn") == Status.found
    assert _status_from_title("LOST: black dog") == Status.lost
    assert _status_from_title("missing tabby reward") == Status.lost
    assert _status_from_title("found wallet") == Status.found
    assert _looks_like_pet("brooklyn-lost-cat-tuxedo") is True
    assert _looks_like_pet("brooklyn-lost-blue-fob-key") is False
    m = IMG_RE.search("https://images.craigslist.org/00D0D_abc_DEF_03j_600x450.jpg")
    assert m and m.group(1) == "00D0D_abc_DEF_03j"


def test_petco_helpers():
    assert _species_from_str("Dog") == Species.dog
    assert _species_from_str("cat") == Species.cat
    assert _is_non_nyc("14219", 42.78, -78.84) is True   # Buffalo
    assert _is_non_nyc("11201", 40.69, -73.99) is False  # Brooklyn
    imgs = _clean_images([
        "https://x/photos/pet/1/a.jpg?width=384&format=webp",
        "https://x/photos/pet/1/a.jpg?width=640",
        "https://x/assets/lost/placeholder/pet-placeholder-image-bg.svg",
    ])
    assert imgs == ["https://x/photos/pet/1/a.jpg"]  # deduped, placeholder dropped


def test_zip_to_latlon_fallback():
    assert zip_to_latlon("11201") is not None
    assert zip_to_latlon("99999") is None
