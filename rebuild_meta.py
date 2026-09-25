"""One-time backfill of the `meta` table against an existing va_cases.sqlite.

bulk_ingest.py now writes `meta` (coverage + bulk_stats aggregates) at the end of every
ingest, but a DB built before that change has no `meta` rows yet. This computes them
against the DB in place -- no re-ingest, no re-download. Safe to re-run (INSERT OR REPLACE).

Usage:
  python rebuild_meta.py
"""
import sys

import store


def main(argv=None) -> int:
    if not store.DB.exists():
        print(f"no DB at {store.DB}", file=sys.stderr)
        return 1
    c = store.conn()
    rows = store.build_meta(c)
    c.close()
    print(f"wrote {len(rows)} meta rows to {store.DB}:")
    for key, _ in rows:
        print(f"  {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
