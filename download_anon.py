"""Download the ANONYMIZED Virginia bulk court dump from virginiacourtdata.org.

Reads the live Firebase manifest (the S3 URLs rotate on each refresh, so we never
hardcode them), then streams each zip to --dir. Atomic (.part -> rename) and
resumable (skips files whose size already matches). Anonymized data only — no
party names, no case numbers, no DOB (keyed on person_id). Internal use only;
per Va. 2018 bulk-data statute the store stays local and is never redistributed.

Usage:
  python download_anon.py --list                       # show the plan, download nothing
  python download_anon.py --dir dumps                  # download everything (~3.3 GB)
  python download_anon.py --dir dumps --only district-criminal circuit-criminal
"""
import argparse, pathlib, sys
import httpx

MANIFEST = "https://virginiacourtdata.firebaseio.com/data/anon.json"
CATEGORIES = ["circuit-civil", "circuit-criminal", "district-civil", "district-criminal", "person"]


def fetch_manifest() -> dict:
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        r = c.get(MANIFEST)
        r.raise_for_status()
        return r.json()


def build_plan(man: dict, cats: list[str]) -> list[tuple[str, str, int]]:
    plan = []
    for cat in cats:
        for e in man.get(cat, []):
            url = (e.get("downloadLink") or "").replace(" ", "")  # manifest occasionally has stray spaces
            if url:
                plan.append((cat, url, int(e.get("filesize", 0))))
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download anonymized VA bulk court data")
    ap.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("dumps"))
    ap.add_argument("--only", nargs="*", choices=CATEGORIES, help="subset of categories (default: all)")
    ap.add_argument("--list", action="store_true", help="print the plan and exit")
    args = ap.parse_args(argv)

    cats = args.only or CATEGORIES
    plan = build_plan(fetch_manifest(), cats)
    total = sum(sz for *_, sz in plan)
    print(f"{len(plan)} files, {total/1e9:.2f} GB compressed across: {', '.join(cats)}")
    if args.list:
        for cat, url, sz in plan:
            print(f"  {cat:18} {sz/1e6:8.1f} MB  {url}")
        return 0

    args.dir.mkdir(parents=True, exist_ok=True)
    done = got = 0
    with httpx.Client(timeout=None, follow_redirects=True) as c:
        for i, (cat, url, sz) in enumerate(plan, 1):
            name = url.split("/")[-1]
            dest = args.dir / name
            if dest.exists() and sz and dest.stat().st_size == sz:
                print(f"[{i}/{len(plan)}] skip (size match) {name}")
                done += 1
                continue
            tmp = dest.with_suffix(dest.suffix + ".part")
            with c.stream("GET", url) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for block in r.iter_bytes(chunk_size=1 << 20):
                        f.write(block)
            tmp.replace(dest)  # atomic: only complete files are visible to the ingester
            done += 1
            got += dest.stat().st_size
            print(f"[{i}/{len(plan)}] {name}  ({dest.stat().st_size/1e6:.1f} MB)")
    print(f"done: {done}/{len(plan)} files present, {got/1e9:.2f} GB newly downloaded -> {args.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
