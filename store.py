"""Local SQLite cache. Bulk dump + live-lookup cache share one table.
Redistribution guardrail: local store only. Per Va. 2018 bulk-data statute,
aggregated case data may NOT be sold, re-hosted, or redistributed to third parties.
Internal due-diligence use only.
"""
import sqlite3, json, pathlib
DB = pathlib.Path(__file__).parent / "va_cases.sqlite"

DDL = """
CREATE TABLE IF NOT EXISTS cases (
  source TEXT, court_level TEXT, court_code TEXT, court_name TEXT,
  division TEXT, case_number TEXT, party_name TEXT, role TEXT,
  charge_or_cause TEXT, status TEXT, filed_date TEXT,
  disposition TEXT, disposition_date TEXT, hearings TEXT,
  fetched_at TEXT, raw_url TEXT,
  PRIMARY KEY (court_level, court_code, case_number, party_name)
);
CREATE INDEX IF NOT EXISTS idx_party ON cases(party_name);
CREATE INDEX IF NOT EXISTS idx_court ON cases(court_code, division);
"""

def conn():
    c = sqlite3.connect(DB); c.executescript(DDL); return c

def upsert(records: list[dict]):
    c = conn()
    with c:
        for r in records:
            r = dict(r); r["hearings"] = json.dumps(r.get("hearings", []))
            cols = ",".join(r); ph = ",".join("?" * len(r))
            c.execute(f"INSERT OR REPLACE INTO cases ({cols}) VALUES ({ph})", list(r.values()))
    return len(records)

def search(party: str = None, court_code: str = None, division: str = None, limit: int = 100):
    c = conn(); q = "SELECT * FROM cases WHERE 1=1"; a = []
    if party:      q += " AND party_name LIKE ?"; a.append(f"%{party}%")
    if court_code: q += " AND court_code = ?";    a.append(court_code)
    if division:   q += " AND division = ?";      a.append(division)
    q += " LIMIT ?"; a.append(limit)
    cur = c.execute(q, a); cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
