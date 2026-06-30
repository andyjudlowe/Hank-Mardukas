"""Interactive terminal review: permanently dismiss obvious-miss matches.

Run `python -m petmatch.review` to walk through current possible/high matches
and mark false positives. Dismissed matches are hidden everywhere (dashboard,
email) from then on, even after future re-runs -- `upsert_match` never resets
the `dismissed` flag on an already-seen pair.
"""
from __future__ import annotations

import argparse

from .config import CONFIG
from .models import MatchTier
from .storage import connect, dismiss_match, get_matches, pets_by_id


def _pet_line(pet) -> str:
    if pet is None:
        return "  (pet record missing)"
    bits = [pet.species.value]
    if pet.breed:
        bits.append(pet.breed)
    if pet.colors:
        bits.append(",".join(pet.colors))
    bits.append(pet.borough or "unknown area")
    name = pet.name or "unnamed"
    return f"  {name} — {' / '.join(bits)}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["possible", "high", "all"], default="possible",
                     help="which tier to review (default: possible)")
    args = ap.parse_args()

    conn = connect()
    try:
        if args.tier == "all":
            matches = get_matches(conn, None)
        else:
            matches = get_matches(conn, MatchTier(args.tier))
        if not matches:
            print("Nothing to review.")
            return

        pets = pets_by_id(conn)
        print(f"{len(matches)} match(es) to review. For each: Enter=keep, "
              "r=reject (permanent), q=quit.\n")
        dismissed = 0
        for i, m in enumerate(matches, 1):
            lost, found = pets.get(m.lost_id), pets.get(m.found_id)
            print(f"[{i}/{len(matches)}] {m.tier.value} · confidence {round(m.confidence * 100)}%")
            print(_pet_line(lost))
            print(_pet_line(found))
            if m.reasons:
                print("  why: " + " · ".join(m.reasons))
            ans = input("  keep / reject / quit [k/r/q]: ").strip().lower()
            if ans in ("q", "quit"):
                break
            if ans in ("r", "reject"):
                dismiss_match(conn, m.lost_id, m.found_id)
                dismissed += 1
                print("  -> rejected\n")
            else:
                print("  -> kept\n")
        conn.commit()
        print(f"\nDone. {dismissed} match(es) rejected and will stay hidden. "
              "Rebuild the dashboard (`python -m petmatch.dashboard`) and commit "
              "data/petmatch.db to publish the change.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
