"""Local SQLite store for the ANONYMIZED Virginia bulk court dump.

The anonymized dump has NO names, NO case numbers, and NO DOB (stripped at source).
Criminal rows carry `person_id` as the only cross-case identity; civil rows carry
no identity at all. Rows are per hearing/charge (the dump is denormalized), so a
single case spans multiple rows tied by person_id.

Redistribution guardrail: local store only. Per Va. 2018 bulk-data statute,
aggregated case data may NOT be sold, re-hosted, or redistributed to third parties.
Internal due-diligence use only.
"""
import json, sqlite3, pathlib

DB = pathlib.Path(__file__).parent / "va_cases.sqlite"

# group_by keys bulk_stats() accepts; also the set of "stats:<key>" rows cached in `meta`.
STATS_KEYS = ("division", "court_level", "fips", "disposition", "year", "filed_year")

DDL = """
CREATE TABLE IF NOT EXISTS cases (
  rowhash         TEXT PRIMARY KEY,   -- hash(zip, member, line) -> idempotent re-ingest
  source          TEXT,
  court_level     TEXT,               -- circuit | district
  division        TEXT,               -- civil | criminal
  fips            TEXT,               -- 3-digit locality/court code (joins localities.yaml)
  court_name      TEXT,
  year            INTEGER,            -- dump year (from filename)
  person_id       TEXT,               -- criminal only; the only cross-case identity in anon data
  charge_or_cause TEXT,               -- Charge (criminal) | FilingType/CaseType (civil)
  code_section    TEXT,
  charge_class    TEXT,
  filed_date      TEXT,
  offense_date    TEXT,
  disposition     TEXT,
  disposition_date TEXT,
  sentence        TEXT,
  hearing_date    TEXT,
  hearing_result  TEXT,
  sex             TEXT,
  race            TEXT,
  locality        TEXT,
  fetched_at      TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,   -- 'coverage' or 'stats:<group_by>'
  value TEXT                -- JSON-encoded result, precomputed at ingest
);
CREATE INDEX IF NOT EXISTS idx_person ON cases(person_id);
CREATE INDEX IF NOT EXISTS idx_fips   ON cases(fips, division);
CREATE INDEX IF NOT EXISTS idx_charge ON cases(charge_or_cause);
CREATE INDEX IF NOT EXISTS idx_filed  ON cases(filed_date);
"""

# Columns written by the ingester (order matters for executemany).
COLS = (
    "rowhash", "source", "court_level", "division", "fips", "court_name", "year",
    "person_id", "charge_or_cause", "code_section", "charge_class", "filed_date",
    "offense_date", "disposition", "disposition_date", "sentence", "hearing_date",
    "hearing_result", "sex", "race", "locality", "fetched_at",
)

# Columns returned by search() (skip internal/noisy ones).
_OUT = ("court_level", "division", "fips", "court_name", "year", "person_id",
        "charge_or_cause", "code_section", "charge_class", "filed_date",
        "offense_date", "disposition", "disposition_date", "sentence",
        "hearing_date", "hearing_result", "sex", "race")


def conn():
    c = sqlite3.connect(DB)
    c.executescript(DDL)
    return c


def search(fips=None, division=None, charge=None, code_section=None,
           person_id=None, year=None, filed_from=None, filed_to=None, limit=100):
    c = conn()
    q = f"SELECT {','.join(_OUT)} FROM cases WHERE 1=1"
    a = []
    if fips:         q += " AND fips = ?";               a.append(fips)
    if division:     q += " AND division = ?";           a.append(division)
    if charge:       q += " AND charge_or_cause LIKE ?"; a.append(f"%{charge}%")
    if code_section: q += " AND code_section LIKE ?";    a.append(f"%{code_section}%")
    if person_id:    q += " AND person_id = ?";          a.append(person_id)
    if year:         q += " AND year = ?";               a.append(int(year))
    if filed_from:   q += " AND filed_date >= ?";        a.append(filed_from)
    if filed_to:     q += " AND filed_date <= ?";        a.append(filed_to)
    q += " ORDER BY filed_date DESC LIMIT ?"
    a.append(limit)
    cur = c.execute(q, a)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _live_stats(c, group_by):
    expr = "substr(filed_date, 1, 4)" if group_by == "filed_year" else group_by
    cur = c.execute(
        f"SELECT {expr} AS {group_by}, COUNT(*) n FROM cases GROUP BY {expr} ORDER BY n DESC LIMIT 300"
    )
    return [{group_by: r[0], "count": r[1]} for r in cur.fetchall()]


def _live_coverage(c):
    cur = c.execute(
        "SELECT division, MIN(filed_date), MAX(filed_date), COUNT(*) "
        "FROM cases GROUP BY division ORDER BY division"
    )
    return [{"division": r[0], "min_filed_date": r[1], "max_filed_date": r[2], "count": r[3]}
            for r in cur.fetchall()]


def _cached(c, key):
    row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def stats(group_by="division"):
    """Aggregate row counts grouped by one of: division, court_level, fips, disposition,
    year (source export batch), filed_year (calendar year of filed_date).

    Reads the precomputed `meta` row written at ingest (O(1)); falls back to a live
    GROUP BY scan if `meta` hasn't been populated yet (see rebuild_meta.py)."""
    if group_by not in STATS_KEYS:
        group_by = "division"
    c = conn()
    cached = _cached(c, f"stats:{group_by}")
    if cached is not None:
        return cached
    return _live_stats(c, group_by)


def coverage():
    """MIN/MAX(filed_date) and row count per division -- the real, queryable freshness signal.

    `year` is the source export-batch year, not the filing year, so it under/over-states
    how current the data is (see README). This reports actual filed_date coverage instead.

    Reads the precomputed `meta` row written at ingest (O(1)); falls back to a live
    GROUP BY scan if `meta` hasn't been populated yet (see rebuild_meta.py)."""
    c = conn()
    cached = _cached(c, "coverage")
    if cached is not None:
        return cached
    return _live_coverage(c)


def build_meta(c=None):
    """Compute coverage() + bulk_stats() for every allowed group_by and persist them into
    `meta`, so coverage()/stats() become O(1) reads instead of full scans of `cases`.

    Called at the end of bulk_ingest.py, and by rebuild_meta.py for a one-time backfill
    against an existing DB (no re-ingest needed). Takes an open connection so bulk_ingest
    can call it before closing its own; opens/closes one itself otherwise."""
    owns = c is None
    if owns:
        c = conn()
    rows = [("coverage", json.dumps(_live_coverage(c)))]
    rows += [(f"stats:{key}", json.dumps(_live_stats(c, key))) for key in STATS_KEYS]
    c.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", rows)
    c.commit()
    if owns:
        c.close()
    return rows


def total():
    return conn().execute("SELECT COUNT(*) FROM cases").fetchone()[0]
