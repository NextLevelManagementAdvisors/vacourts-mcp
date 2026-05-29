"""Ingest virginiacourtdata.org bulk CSV (Circuit + GD, through 2024) into local SQLite.
Their CSV is per-court (keyed on 3-digit FIPS) -> joins straight to localities.yaml `code`.
NOTE: field names below match the published virginiacourtdata schema; confirm headers on
first run (their Circuit vs GD column sets differ) and adjust COLMAP. This is the
historical layer; live patchright lookups cover post-dump / recent activity.
"""
import csv, io, zipfile, datetime, httpx, yaml, pathlib
import store

ROOT = pathlib.Path(__file__).parent
LOCALITIES = {l["code"]: l for l in yaml.safe_load(open(ROOT/"localities.yaml"))["localities"]}

# virginiacourtdata column -> normalized field. VERIFY against actual header row on first run.
COLMAP_CIVIL = {
    "CaseNumber": "case_number", "Plaintiff": "party_name", "Defendant": "party_name",
    "FiledDate": "filed_date", "CaseType": "charge_or_cause",
    "Disposition": "disposition", "DispositionDate": "disposition_date",
}
COLMAP_CRIMINAL = {
    "CaseNumber": "case_number", "Defendant": "party_name", "Charge": "charge_or_cause",
    "FiledDate": "filed_date", "Disposition": "disposition", "DispositionDate": "disposition_date",
}

def ingest_csv_bytes(data: bytes, court_level: str, court_code: str, division: str):
    colmap = COLMAP_CRIMINAL if division == "criminal" else COLMAP_CIVIL
    loc = LOCALITIES.get(court_code, {})
    recs = []
    for row in csv.DictReader(io.StringIO(data.decode("utf-8", "ignore"))):
        rec = {"source": "bulk", "court_level": court_level, "court_code": court_code,
               "court_name": loc.get("name", court_code), "division": division,
               "fetched_at": datetime.date.today().isoformat(), "hearings": []}
        for src, dst in colmap.items():
            if row.get(src): rec[dst] = row[src]
        if rec.get("case_number") and rec.get("party_name"):
            recs.append(rec)
    return store.upsert(recs)

def ingest_zip(path: str, court_level: str, court_code: str, division: str):
    with zipfile.ZipFile(path) as z:
        total = 0
        for n in z.namelist():
            if n.lower().endswith(".csv"):
                total += ingest_csv_bytes(z.read(n), court_level, court_code, division)
    return total

if __name__ == "__main__":
    import sys
    # usage: python bulk_ingest.py <zip> <circuit|gd> <code> <civil|criminal>
    print("ingested:", ingest_zip(*sys.argv[1:5]))
