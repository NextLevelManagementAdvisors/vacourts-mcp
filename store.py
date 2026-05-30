"""Local SQLite store for the ANONYMIZED Virginia bulk court dump.

The anonymized dump has NO names, NO case numbers, and NO DOB (stripped at source).
Criminal rows carry `person_id` as the only cross-case identity; civil rows carry
no identity at all. Rows are per hearing/charge (the dump is denormalized), so a
single case spans multiple rows tied by person_id.

Redistribution guardrail: local store only. Per Va. 2018 bulk-data statute,
aggregated case data may NOT be sold, re-hosted, or redistributed to third parties.
Internal due-diligence use only.
"""
import sqlite3, pathlib

DB = pathlib.Path(__file__).parent / "va_cases.sqlite"

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
           person_id=None, year=None, limit=100):
    c = conn()
    q = f"SELECT {','.join(_OUT)} FROM cases WHERE 1=1"
    a = []
    if fips:         q += " AND fips = ?";               a.append(fips)
    if division:     q += " AND division = ?";           a.append(division)
    if charge:       q += " AND charge_or_cause LIKE ?"; a.append(f"%{charge}%")
    if code_section: q += " AND code_section LIKE ?";    a.append(f"%{code_section}%")
    if person_id:    q += " AND person_id = ?";          a.append(person_id)
    if year:         q += " AND year = ?";               a.append(int(year))
    q += " ORDER BY filed_date DESC LIMIT ?"
    a.append(limit)
    cur = c.execute(q, a)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def stats(group_by="division"):
    """Aggregate row counts grouped by one of: division, court_level, fips, disposition, year."""
    allowed = {"division", "court_level", "fips", "disposition", "year"}
    if group_by not in allowed:
        group_by = "division"
    c = conn()
    cur = c.execute(
        f"SELECT {group_by}, COUNT(*) n FROM cases GROUP BY {group_by} ORDER BY n DESC LIMIT 300"
    )
    return [{group_by: r[0], "count": r[1]} for r in cur.fetchall()]


def total():
    return conn().execute("SELECT COUNT(*) FROM cases").fetchone()[0]
