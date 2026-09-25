"""Streaming ingester for the ANONYMIZED Virginia bulk court dump -> local SQLite.

Point it at a folder of downloaded zips (download_anon.py). It auto-detects
court_level / division / year from each filename, streams rows (never reads a
whole file into RAM), maps columns with the verified anon COLMAP below, and
INSERT-OR-IGNOREs into the `cases` table keyed by a per-physical-row hash
(idempotent re-runs, no false dedup). Indexes are built once after the load.

Anon data has NO names / case numbers / DOB. Criminal rows carry person_id;
civil rows carry no identity. Rows are per hearing/charge.

Redistribution guardrail: local store only (Va. 2018 bulk-data statute).

Usage:
  python bulk_ingest.py --dir dumps                 # ingest the 4 core types
  python bulk_ingest.py --dir dumps --reset         # drop + rebuild from scratch
  python bulk_ingest.py --dir dumps --only district criminal
"""
from __future__ import annotations
import argparse, csv, datetime, hashlib, io, pathlib, re, sqlite3, sys, zipfile

import yaml
import store

ROOT = pathlib.Path(__file__).parent
LOCALITIES = {l["code"]: l for l in yaml.safe_load(open(ROOT / "localities.yaml"))["localities"]}
BATCH = 5000
csv.field_size_limit(1 << 24)

# target field <- source column, per (court_level, division). Verified against the
# real 2025 anon headers. fips/year/court_level/division come from filename + the
# fips column; court_name is joined from localities.yaml.
COLMAP = {
    ("circuit", "civil"): {
        "charge_or_cause": "FilingType", "filed_date": "Filed",
        "disposition": "Judgment", "disposition_date": "FinalOrderDate",
    },
    ("circuit", "criminal"): {
        "person_id": "person_id", "charge_or_cause": "Charge", "code_section": "CodeSection",
        "charge_class": "Class", "filed_date": "Filed", "offense_date": "OffenseDate",
        "disposition": "DispositionCode", "disposition_date": "DispositionDate",
        "sentence": "SentenceTime", "hearing_date": "HearingDate", "hearing_result": "HearingResult",
        "sex": "Sex", "race": "Race", "locality": "Locality",
    },
    ("district", "civil"): {
        "charge_or_cause": "CaseType", "filed_date": "FiledDate",
        "disposition": "Judgment", "disposition_date": "DateSatisfactionFiled",
    },
    ("district", "criminal"): {
        "person_id": "person_id", "charge_or_cause": "Charge", "code_section": "CodeSection",
        "charge_class": "Class", "filed_date": "FiledDate", "offense_date": "OffenseDate",
        "disposition": "FinalDisposition", "sentence": "SentenceTime",
        "hearing_date": "HearingDate", "hearing_result": "HearingResult",
        "sex": "Gender", "race": "Race", "locality": "Locality",
    },
}

_FNAME = re.compile(r"(circuit|district)_(civil|criminal)_(\d{4})_anon", re.I)

TABLE_ONLY_DDL = store.DDL.split("CREATE INDEX")[0]  # table without indexes (faster bulk load)
INDEX_DDL = "CREATE INDEX" + store.DDL.split("CREATE INDEX", 1)[1]


def detect(fname: str):
    m = _FNAME.search(fname)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).lower(), int(m.group(3))


def bulk_conn(reset: bool) -> sqlite3.Connection:
    c = sqlite3.connect(store.DB)
    if reset:
        c.execute("DROP TABLE IF EXISTS cases")
    c.executescript(TABLE_ONLY_DDL)
    for p in ("journal_mode=WAL", "synchronous=OFF", "temp_store=MEMORY", "cache_size=-262144"):
        c.execute(f"PRAGMA {p}")
    return c


def ingest_zip(path: pathlib.Path, c: sqlite3.Connection, fetched_at: str) -> int:
    det = detect(path.name)
    if not det:
        return 0
    level, division, year = det
    colmap = COLMAP[(level, division)]
    sql = f"INSERT OR IGNORE INTO cases ({','.join(store.COLS)}) VALUES ({','.join('?' for _ in store.COLS)})"
    total = 0
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            if not member.lower().endswith(".csv"):
                continue
            with z.open(member) as raw:
                rdr = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", errors="ignore", newline=""))
                batch = []
                for i, row in enumerate(rdr):
                    fips = (row.get("fips") or "").strip().zfill(3) if row.get("fips") else None
                    rec = {k: None for k in store.COLS}
                    rec.update(source="bulk", court_level=level, division=division, fips=fips,
                               court_name=(LOCALITIES.get(fips, {}) or {}).get("name", fips),
                               year=year, fetched_at=fetched_at)
                    for dst, src in colmap.items():
                        v = row.get(src)
                        if v:
                            rec[dst] = v.strip()
                    rec["rowhash"] = hashlib.md5(f"{path.name}|{member}|{i}".encode()).hexdigest()
                    batch.append([rec[k] for k in store.COLS])
                    if len(batch) >= BATCH:
                        c.executemany(sql, batch); c.commit(); total += len(batch); batch = []
                if batch:
                    c.executemany(sql, batch); c.commit(); total += len(batch)
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ingest anonymized VA bulk court data")
    ap.add_argument("--dir", type=pathlib.Path, required=True)
    ap.add_argument("--reset", action="store_true", help="drop + rebuild the cases table")
    ap.add_argument("--only", nargs=2, metavar=("LEVEL", "DIVISION"),
                    help="restrict to one level+division, e.g. --only district criminal")
    args = ap.parse_args(argv)

    files = sorted(p for p in args.dir.glob("*.zip") if detect(p.name))
    if args.only:
        lvl, div = args.only[0].lower(), args.only[1].lower()
        files = [p for p in files if detect(p.name)[:2] == (lvl, div)]
    if not files:
        print(f"no matching core-type zips under {args.dir}", file=sys.stderr)
        return 1

    fetched_at = datetime.date.today().isoformat()
    c = bulk_conn(args.reset)
    grand = 0
    for n, f in enumerate(files, 1):
        rows = ingest_zip(f, c, fetched_at)
        grand += rows
        print(f"[{n}/{len(files)}] {f.name}: +{rows:,} (total {grand:,})", flush=True)
    print("building indexes ...", flush=True)
    c.executescript(INDEX_DDL)
    print("building meta (coverage/bulk_stats cache) ...", flush=True)
    store.build_meta(c)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    print(f"DONE: {grand:,} rows across {len(files)} files -> {store.DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
