"""Entrypoint: scrape -> store -> match -> (optionally) email -> dashboard.

Examples:
  python -m petmatch.main                         # daily: scrape, match, dashboard
  python -m petmatch.main --send-email            # weekly: also email the digest
  python -m petmatch.main --dry-run --limit 20    # quick test, no email
  python -m petmatch.main --skip-scrape           # rematch/rebuild from stored data
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .config import CONFIG
from .dashboard import build_site
from .email_send import send_email
from .match.pipeline import run_matching
from .models import Source
from .report import weekly_digest
from .sources.base import Fetcher
from .sources.craigslist import CraigslistSource
from .sources.petco import PetcoSource
from .storage import (connect, existing_pet_ids, mark_emailed, record_run,
                      upsert_pet)

SOURCES = {"petco": (Source.petco, PetcoSource),
           "craigslist": (Source.craigslist, CraigslistSource)}


def scrape(conn, names, limit):
    fetcher = Fetcher()
    total = 0
    try:
        for name in names:
            src_enum, src_cls = SOURCES[name]
            existing = existing_pet_ids(conn, src_enum)
            n = 0
            for rec in src_cls().fetch(fetcher, limit=limit, existing_ids=existing):
                upsert_pet(conn, rec)
                n += 1
            conn.commit()
            print(f"  scraped {name}: {n} records")
            total += n
    finally:
        fetcher.close()
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NYC Lost & Found Pet Matcher")
    ap.add_argument("--sources", default="petco,craigslist",
                    help="comma-separated: petco,craigslist")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap records per source (for testing)")
    ap.add_argument("--no-photo", action="store_true",
                    help="skip Claude vision; attribute-only matching")
    ap.add_argument("--send-email", action="store_true",
                    help="send the weekly digest (default: no email)")
    ap.add_argument("--dry-run", action="store_true",
                    help="never send email; print the digest to console")
    ap.add_argument("--skip-scrape", action="store_true",
                    help="reuse stored pets; just rematch + rebuild")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--db", default=None, help="override database path")
    args = ap.parse_args(argv)

    db_path = None
    if args.db:
        from pathlib import Path
        db_path = Path(args.db)
    conn = connect(db_path) if db_path else connect()
    started = datetime.now(timezone.utc).isoformat()

    pets_scraped = 0
    try:
        if not args.skip_scrape:
            names = [s.strip() for s in args.sources.split(",") if s.strip()]
            print("Scraping...")
            pets_scraped = scrape(conn, names, args.limit)

        print("Matching...")
        stats = run_matching(conn, do_photo=not args.no_photo)

        # Build the weekly digest (high-confidence, not-yet-emailed matches).
        matches, subject, html, text = weekly_digest(conn)
        print(f"Digest: {len(matches)} high-confidence matches pending email.")

        if args.dry_run:
            print("\n----- DRY RUN: email that WOULD be sent -----")
            print(text)
        elif args.send_email:
            if send_email(subject, html, text):
                mark_emailed(conn, matches)
                conn.commit()

        if not args.no_dashboard:
            print("Building dashboard...")
            build_site(conn)

        record_run(
            conn,
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),
            pets_scraped=pets_scraped,
            matches_total=stats.high + stats.possible,
            matches_high=stats.high,
            matches_possible=stats.possible,
            emailed=1 if (args.send_email and not args.dry_run) else 0,
            note="dry-run" if args.dry_run else "",
        )
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
