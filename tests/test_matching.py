"""Stage-1 gates/scoring and pipeline tiering."""
from datetime import date

from petmatch.config import CONFIG
from petmatch.match.filter import stage1
from petmatch.match.pipeline import _confidence, _tier, run_matching
from petmatch.models import MatchTier, Sex, Source, Species, Status
from petmatch.storage import connect, get_matches, upsert_pet


def make_pet(sid, status, **kw):
    return type("P", (), {})  # placeholder, replaced below


def pet(sid, status, **kw):
    from petmatch.models import PetRecord
    return PetRecord.build(Source.craigslist, sid, status=status, **kw)


# ---- a known TRUE match: same black/white cat, same borough, close dates ----
def test_true_match_passes_and_corroborates():
    lost = pet("L1", Status.lost, species=Species.cat, colors=["black", "white"],
               borough="Brooklyn", date_reported=date(2026, 6, 10),
               description="lost black and white cat named Oreo")
    found = pet("F1", Status.found, species=Species.cat, colors=["black", "white"],
                borough="Brooklyn", date_reported=date(2026, 6, 12),
                description="found black white cat")
    res = stage1(lost, found, CONFIG)
    assert res.passed
    assert res.corroborated
    assert res.score >= CONFIG.attr_threshold


# ---- a known NON-match: different species is hard-gated ----
def test_species_mismatch_rejected():
    lost = pet("L2", Status.lost, species=Species.cat, borough="Queens")
    found = pet("F2", Status.found, species=Species.dog, borough="Queens")
    assert stage1(lost, found, CONFIG).passed is False


# ---- geography hard gate via coordinates ----
def test_far_distance_rejected():
    lost = pet("L3", Status.lost, species=Species.dog, lat=40.70, lon=-74.00)
    found = pet("F3", Status.found, species=Species.dog, lat=40.90, lon=-73.10)
    assert stage1(lost, found, CONFIG).passed is False


# ---- date hard gate: found reported long before the pet was lost ----
def test_impossible_date_rejected():
    lost = pet("L4", Status.lost, species=Species.cat, borough="Bronx",
               date_reported=date(2026, 6, 20))
    found = pet("F4", Status.found, species=Species.cat, borough="Bronx",
                date_reported=date(2026, 1, 1))
    assert stage1(lost, found, CONFIG).passed is False


# ---- species-only (no descriptors, no location): at the species floor and
#      NOT corroborated, so it can be a photo candidate but never surfaces on the
#      attribute-only (no-photo) path. ----
def test_species_only_is_floor_and_uncorroborated():
    lost = pet("L5", Status.lost, species=Species.cat)
    found = pet("F5", Status.found, species=Species.cat)
    res = stage1(lost, found, CONFIG)
    assert res.passed
    assert res.corroborated is False
    assert res.score == 0.30  # species contributes exactly the floor


def test_confidence_caps_without_photo():
    # strong attributes, but no photo -> capped
    assert _confidence(0.95, None, CONFIG) == CONFIG.no_photo_confidence_cap
    # photo dominates when present
    assert _confidence(0.5, 0.9, CONFIG) > 0.7


def test_tier_thresholds():
    assert _tier(CONFIG.email_threshold, CONFIG) == MatchTier.high
    assert _tier(CONFIG.dash_threshold, CONFIG) == MatchTier.possible
    assert _tier(0.1, CONFIG) == MatchTier.rejected


def test_pipeline_creates_possible_match(tmp_path):
    conn = connect(tmp_path / "t.db")
    upsert_pet(conn, pet("L9", Status.lost, species=Species.cat,
                         colors=["black", "white"], borough="Brooklyn",
                         date_reported=date(2026, 6, 10),
                         description="lost tuxedo cat"))
    upsert_pet(conn, pet("F9", Status.found, species=Species.cat,
                         colors=["black", "white"], borough="Brooklyn",
                         date_reported=date(2026, 6, 11),
                         description="found black and white cat"))
    conn.commit()
    stats = run_matching(conn, do_photo=False, verbose=False)
    matches = get_matches(conn, MatchTier.possible)
    assert stats.possible >= 1
    assert len(matches) >= 1
    conn.close()
