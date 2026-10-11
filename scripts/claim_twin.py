"""Claim an OLD (unowned) twin for an existing account, or list the unowned twins. Offline tool for the person who runs the database.

Twins that were created before accounts existed have no owner, so the website and API hide them from everyone. This script is the only way to attach one to an account.

Safety rules (enforced in glycotwin.backend.ownership.claim_twin and covered by tests):
  * DRY RUN by default: it shows what it WOULD do and changes nothing. Add --apply to write.
  * It refuses a twin that already has an owner. There is no --force and no transfer feature: ownership is never overwritten.
  * The account must already exist (the person registers first) and must not be a temporary guest.
  * It only ADDS one row to twin_owners. It never edits or deletes twins, forecasts, observations or history.
  * It prints the database it is about to use. Take a copy of the database file first.

Usage (PowerShell, project root; the database comes from GLYCOTWIN_DATABASE_URL or the default file):
    python scripts\\claim_twin.py --list-unowned
    python scripts\\claim_twin.py --twin-id <id> --email person@example.com            # dry run
    python scripts\\claim_twin.py --twin-id <id> --email person@example.com --apply    # really claim it
"""

from __future__ import annotations

import argparse
import json
import sys

from glycotwin.backend.config import get_settings
from glycotwin.backend.db import init_db, make_engine, session_factory
from glycotwin.backend.ownership import ClaimError, claim_twin, list_unowned


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--database-url", default=None, help="Overrides GLYCOTWIN_DATABASE_URL (default: SQLite file under data/interim).")
    ap.add_argument("--list-unowned", action="store_true", help="Read-only: list twins that have no owner.")
    ap.add_argument("--twin-id", default=None)
    ap.add_argument("--email", default=None, help="Email of an EXISTING, non-guest account.")
    ap.add_argument("--apply", action="store_true", help="Actually write the claim. Without it nothing is changed.")
    args = ap.parse_args(argv)
    if not args.list_unowned and not (args.twin_id and args.email):
        ap.error("give --list-unowned, or both --twin-id and --email")
    url = args.database_url or get_settings().database_url
    print(f"database: {url.split('///')[-1] if url.startswith('sqlite') else '(non-sqlite url)'}")
    engine = make_engine(url)
    init_db(engine)                                    # adds missing tables only (never drops or alters); needed on a database made before accounts existed
    session = session_factory(engine)()
    try:
        if args.list_unowned:
            rows = list_unowned(session)
            print(json.dumps({"unowned_twins": rows, "count": len(rows)}, indent=2))
            return 0
        try:
            res = claim_twin(session, args.twin_id.strip().lower(), args.email, apply=args.apply)
        except ClaimError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        res["note"] = "claimed" if res["applied"] else "DRY RUN: nothing was changed. Add --apply to claim."
        print(json.dumps(res, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
