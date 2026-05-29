# vacourts-mcp

Virginia court public-records MCP. Civil = court-by-court (CJISWeb, all 133 localities).
Criminal/traffic = statewide (OCIS 2.0). Read-only. Internal due-diligence use only.

## Layers
- **bulk**  local SQLite from virginiacourtdata.org dump (historical, to 2024) -- `bulk_ingest.py`, `store.py`
- **live**  patchright OCIS + CJISWeb -- `patchright_client.py`. Check bulk first, fall through to live, cache live hits back.

## Files
- `localities.yaml`      133 localities, keyed on 3-digit FIPS (joins bulk + CJISWeb). 3 circuit holdouts flagged.
- `server.py`            FastMCP tools: list_localities, search_bulk, search_criminal_statewide, search_civil, search_civil_all
- `schema.py` `store.py` `bulk_ingest.py` `patchright_client.py`

## Deploy (VPS 178.16.141.166, *.nlma.io)
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    patchright install chromium
    python server.py            # behind vacourts.nlma.io, same reverse-proxy pattern as other MCPs

## OPEN ITEMS before production (the real seams)
1. LIVE SELECTOR RECON (blocking): OCIS + CJISWeb search is behind a clickwrap Accept + reCAPTCHA,
   so selectors in patchright_client.py are TODO:LIVE placeholders. Must capture real DOM once
   (CAPTCHA solved by hand) and fill in fill/select/click/parse steps.
2. CAPTCHA run model: live tools raise CaptchaHandoff; wire to your patchright human-step/handoff
   so a human solves once and the run resumes. Unattended runs will stall on CAPTCHA by design.
3. CJISWeb circuit holdouts: Fairfax County (059), Alexandria (510), Arlington (013) flagged
   cjisweb_circuit:false pending verification against the live court dropdown -- they may run own CMS.
4. virginiacourtdata CSV headers: confirm Circuit vs GD column names on first ingest; adjust COLMAP.

## LEGAL
Va. 2018 bulk-data statute: aggregated case data may NOT be sold, re-hosted, or redistributed to
third parties. Judiciary is exempt from VA FOIA (Code 16.1-69.54:1 / 17.1-208 govern). Keep store local.
