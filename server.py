"""vacourts-mcp :: Virginia court public-records MCP (civil per-court + criminal statewide).
FastMCP server, mirrors the *.nlma.io MCP pattern. Read-only.

Layers:
  bulk  -> local SQLite (virginiacourtdata dump, historical to 2024)  [store.py / bulk_ingest.py]
  live  -> patchright OCIS (statewide criminal) + CJISWeb (per-court civil/criminal)  [patchright_client.py]
Strategy: check bulk first; fall through to live for recent/missing; cache live hits back to SQLite.

LEGAL GUARDRAIL: results are for internal due-diligence only. Va. 2018 bulk-data statute bars
selling, re-hosting, or redistributing aggregated case data to third parties.
"""
import yaml, pathlib, asyncio
from fastmcp import FastMCP
import store, patchright_client as live

ROOT = pathlib.Path(__file__).parent
LOCALITIES = yaml.safe_load(open(ROOT / "localities.yaml"))["localities"]
BY_CODE = {l["code"]: l for l in LOCALITIES}
BY_NAME = {l["name"].lower(): l for l in LOCALITIES}

mcp = FastMCP("vacourts")

def _resolve(locality: str) -> dict:
    l = BY_CODE.get(locality) or BY_NAME.get(locality.lower())
    if not l: raise ValueError(f"unknown locality '{locality}' (use 3-digit code or name)")
    return l

@mcp.tool
def list_localities() -> list[dict]:
    """All 133 VA localities (counties + cities) with court codes and coverage flags."""
    return LOCALITIES

@mcp.tool
def search_bulk(party: str, locality: str = None, division: str = None, limit: int = 100) -> list[dict]:
    """Instant historical search of the local bulk store (to 2024). division: civil|criminal|traffic."""
    code = _resolve(locality)["code"] if locality else None
    return store.search(party=party, court_code=code, division=division, limit=limit)

@mcp.tool
def search_criminal_statewide(party: str, dob: str = None) -> dict:
    """LIVE statewide adult criminal/traffic via OCIS 2.0. May require a CAPTCHA handoff."""
    try:
        recs = asyncio.run(live.search_criminal_statewide(party, dob))
        store.upsert(recs); return {"status": "ok", "count": len(recs), "results": recs}
    except live.CaptchaHandoff as h:
        return {"status": "captcha_handoff", "target_url": h.target_url,
                "note": "solve reCAPTCHA via patchright human-step, then re-run"}
    except NotImplementedError as e:
        return {"status": "pending_live_recon", "detail": str(e)}

@mcp.tool
def search_civil(party: str, locality: str, division: str = "civil") -> dict:
    """LIVE per-court CJISWeb search (civil default; division=criminal also valid).
    Civil is court-by-court: one locality per call (no statewide civil exists)."""
    l = _resolve(locality)
    level = "circuit"  # civil lives in both circuit & gd; circuit first. Loop gd separately if needed.
    if not l.get("cjisweb_circuit", True):
        return {"status": "not_on_cjisweb", "locality": l["name"],
                "note": "this circuit runs its own CMS; needs a dedicated adapter"}
    try:
        recs = asyncio.run(live.search_court(party, l["code"], l["name"], level, division))
        store.upsert(recs); return {"status": "ok", "count": len(recs), "results": recs}
    except live.CaptchaHandoff as h:
        return {"status": "captcha_handoff", "target_url": h.target_url}
    except NotImplementedError as e:
        return {"status": "pending_live_recon", "detail": str(e)}

@mcp.tool
def search_civil_all(party: str, division: str = "civil", limit_courts: int = 0) -> dict:
    """Fan-out civil search across EVERY CJISWeb locality (the comprehensive court-by-court sweep).
    Heavy + CAPTCHA-gated; intended for batch/overnight runs. limit_courts=0 means all."""
    targets = [l for l in LOCALITIES if l.get("cjisweb_circuit", True)]
    if limit_courts: targets = targets[:limit_courts]
    return {"status": "planned", "courts": len(targets),
            "note": "execute per-court via search_civil; throttle + handoff per CAPTCHA"}

if __name__ == "__main__":
    mcp.run()
