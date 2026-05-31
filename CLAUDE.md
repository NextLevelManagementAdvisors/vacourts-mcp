# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`vacourts-mcp` is a FastMCP server exposing Virginia court public records as MCP tools. It is **read-only, internal due-diligence use only**, deployed at `https://vacourts.nlma.io/mcp` (Google-OAuth gated). Two data layers:

- **bulk** — a local SQLite (`va_cases.sqlite`) loaded from the *anonymized* virginiacourtdata.org dump. Queried by `search_bulk` / `bulk_stats`.
- **lookup_pointer** — returns the official OCIS/CJISWeb URL + human steps for a name-based lookup. It **automates nothing** (the live patchright scraper was deliberately removed: the OCIS 2.0 EULA bars automated scripting).

Tools: `list_localities`, `search_bulk`, `bulk_stats`, `lookup_pointer`.

## The single most important constraint: the bulk data has no names

The only lawfully-obtainable bulk dump is **anonymized** — it has **no party names, no case numbers, no DOB** (stripped at source). Criminal rows carry `person_id` as the *only* cross-case identity; civil rows carry no identity at all. Consequences that shape the whole design:

- `search_bulk` filters by **locality / division / charge / code_section / person_id / year — never by name**. Do not add a name parameter; there is no name column. Name lookups are the job of `lookup_pointer`.
- Name-bearing ("complete") data is gated to journalists/non-profits/research/government. NLMA does not qualify — **do not misrepresent eligibility to obtain it.** The lawful name-based channel is the VDBC (see `VDBC_registration_NLMA.md`).
- **Legal (Va. 2018 bulk-data statute, § 17.1-208(D) / § 16.1-69.54:1(C)):** aggregated case data may not be sold, re-hosted, redistributed, or made available to the general public. Keep the store local; the deployment must stay auth-gated; never expose it unauthenticated.

## Commands

```bash
# install (uv on the VPS; plain venv works locally)
uv venv --python 3.13 && uv pip install -r requirements.txt   # or: pip install -r requirements.txt

# run locally — stdio (Claude Desktop / fastmcp dev). Default transport.
python server.py
fastmcp dev server.py

# run as the remote HTTP server (what systemd runs)
python -m server --transport http --host 127.0.0.1 --port 3032

# data: download the anonymized dump, then ingest (do these in order)
python download_anon.py --list                    # show plan against the LIVE manifest
python download_anon.py --dir dumps               # ~3.3 GB compressed (98 files)
python bulk_ingest.py  --dir dumps --reset        # rebuild va_cases.sqlite (~49M rows)
python bulk_ingest.py  --dir dumps --only district criminal   # one level+division

# sanity / smoke (there is no unit-test suite)
python -c "import server, store, bulk_ingest; print('imports OK')"
python -c "import store; print(store.total()); print(store.stats('division'))"
```

There are **no automated tests**. Verification is: the import check above, `store.total()`/`store.stats()` against the DB, and a JSON-RPC smoke test against `/mcp` (initialize → notifications/initialized → tools/list → tools/call). Deploy + the full HTTPS smoke sequence live in `DEPLOYMENT.md`.

## Architecture / data flow

`download_anon.py` → `dumps/*.zip` → `bulk_ingest.py` → `va_cases.sqlite` → `store.py` ← `server.py` tools.

- **`server.py`** — the FastMCP server, tool definitions, and the `__main__` entrypoint (argparse `--transport/--host/--port/--path`, env fallbacks `MCP_TRANSPORT/HOST/PORT/MCP_PATH`). Also the **auth layer**: `build_auth()` constructs `AllowlistGoogleProvider` (a `GoogleProvider`/OAuthProxy subclass whose `AllowlistGoogleTokenVerifier` requires a *verified, allowlisted* Google email — a Google login is necessary but not sufficient). The server **fails closed**: in `--transport http` with no `GOOGLE_OAUTH_CLIENT_ID` it refuses to start unless `ALLOW_UNAUTHENTICATED=1` (local testing only).
- **`store.py`** — owns the SQLite schema (`DDL`), the write column order (`COLS`), `search(...)`, `stats(group_by)`, `total()`. The `cases` PK is a per-physical-row `rowhash` (idempotent re-ingest). `conn()` runs the full DDL incl. `CREATE INDEX IF NOT EXISTS` on every connect — **don't open a live `store.conn()` against the DB mid-bulk-load**, it interferes with the indexes-after-load path.
- **`bulk_ingest.py`** — streaming, memory-safe ingester. Detects `(court_level, division, year)` from each zip filename; maps columns via `COLMAP[(level, division)]` (a **4-way map verified against the real anon headers** — circuit vs district and civil vs criminal have different column names, e.g. `Filed` vs `FiledDate`, `DispositionCode` vs `FinalDisposition`, `Sex` vs `Gender`). Loads with `synchronous=OFF`/WAL and **builds indexes once after the load** (`TABLE_ONLY_DDL` then `INDEX_DDL`, both derived by splitting `store.DDL`). If you change `store.DDL`'s index section, that split still must hold.
- **`download_anon.py`** — reads the live Firebase manifest (`data/anon.json`); **the S3 URLs rotate on every refresh, so never hardcode them** — always re-read the manifest. Atomic `.part`→rename, size-skip resume.
- **`localities.yaml`** — 133 VA localities keyed on 3-digit FIPS `code` (the join key for both the bulk `fips` column and `localities.yaml`). `cjisweb_circuit:false` marks the ~3 circuits not on statewide CJISWeb (own CMS) — relevant only to `lookup_pointer`.
- **`schema.py`** — pydantic `CaseRecord` shape (reference; the anon store is wider/flatter than this).

## Deployment shape (see DEPLOYMENT.md for the full runbook)

VPS `178.16.141.166`, `/opt/vacourts-mcp`, **nginx** (not Caddy) → `127.0.0.1:3032`, systemd unit `vacourts-mcp`, uv venv, `fastmcp>=3.2,<4`. nginx just proxies — the app is the OAuth server + resource server. TLS via `certbot certonly --manual` DNS-01 Hostinger hooks (ECDSA). The vhost has **no `listen [::]` line** — Tailscale Funnel holds IPv6 :443 and nginx reload silently fails otherwise. `deploy/` holds the exact systemd unit, nginx vhost, rate-limit zone, and landing page. Secrets live only in `/opt/vacourts-mcp/.env` (chmod 600, gitignored); `.env.example` documents the keys.

(`DEPLOY_VPS.md` is an earlier, superseded runbook — it predates the nginx/port-3032/anon-data facts; trust `DEPLOYMENT.md`.)
