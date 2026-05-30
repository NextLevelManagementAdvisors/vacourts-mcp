"""vacourts-mcp :: Virginia court public-records MCP (bulk historical + human lookup pointer).
FastMCP server, mirrors the *.nlma.io MCP pattern. Read-only. Internal due-diligence use only.

Layers:
  bulk            -> local SQLite (virginiacourtdata dump, historical to 2024)  [store.py / bulk_ingest.py]
  lookup_pointer  -> returns the OFFICIAL OCIS/CJISWeb URL + steps for a HUMAN one-off lookup.
                     Automates nothing: the OCIS 2.0 EULA bars automated scripting/data-mining,
                     so live scraping was intentionally removed.

LEGAL GUARDRAIL: results are for internal due-diligence only. Va. 2018 bulk-data statute bars
selling, re-hosting, or redistributing aggregated case data to third parties. Store stays local.
"""
import yaml, pathlib, argparse, os, logging
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider, GoogleTokenVerifier
from fastmcp.server.auth.auth import AccessToken
import store

log = logging.getLogger("vacourts.auth")

ROOT = pathlib.Path(__file__).parent
LOCALITIES = yaml.safe_load(open(ROOT / "localities.yaml"))["localities"]
BY_CODE = {l["code"]: l for l in LOCALITIES}
BY_NAME = {l["name"].lower(): l for l in LOCALITIES}

OCIS_URL     = "https://eapps.courts.state.va.us/ocis/landing"
CJIS_CIRCUIT = "https://eapps.courts.state.va.us/CJISWeb/circuit.html"
CJIS_GD      = "https://eapps.courts.state.va.us/gdcourts"


# ---- auth -------------------------------------------------------------------
# claude.ai (and other MCP web clients) only authenticate via OAuth + Dynamic
# Client Registration. FastMCP's GoogleProvider is an OAuthProxy: it synthesizes
# DCR for the client and proxies the real login to Google. Access is then locked
# to an explicit email allowlist (no FastMCP provider ships one), so completing a
# Google login is necessary but not sufficient — the email must be on the list.
class AllowlistGoogleTokenVerifier(GoogleTokenVerifier):
    """Google token verifier that additionally requires a verified, allowlisted email."""

    def __init__(self, *, allowed_emails: set[str], **kw):
        super().__init__(**kw)
        self._allowed = {e.strip().lower() for e in allowed_emails if e.strip()}

    async def verify_token(self, token: str) -> AccessToken | None:
        access = await super().verify_token(token)
        if access is None:
            return None
        claims = access.claims or {}
        email = (claims.get("email") or "").lower()
        if claims.get("email_verified") is False:
            log.warning("vacourts: rejecting unverified Google email %r", email)
            return None
        if email not in self._allowed:
            log.warning("vacourts: rejecting non-allowlisted email %r", email or "<none>")
            return None
        return access


class AllowlistGoogleProvider(GoogleProvider):
    """GoogleProvider whose token verifier enforces an email allowlist."""

    def __init__(self, *, allowed_emails: set[str], **kw):
        super().__init__(**kw)
        # OAuthProxy stores the verifier as self._token_validator and routes every
        # verify_token() call through it; swap in the allowlisting one, preserving
        # the normalized required scopes the GoogleProvider computed.
        self._token_validator = AllowlistGoogleTokenVerifier(
            allowed_emails=allowed_emails,
            required_scopes=self._token_validator.required_scopes,
        )


def build_auth():
    """Build the Google OAuth provider from env, or None if not configured.

    GOOGLE_OAUTH_CLIENT_ID present => OAuth is enabled and CLIENT_SECRET,
    MCP_BASE_URL, and ALLOWED_GOOGLE_EMAILS are all required (fail closed).
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        return None
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    base_url = os.environ.get("MCP_BASE_URL")
    allowed = {e.strip().lower()
               for e in os.environ.get("ALLOWED_GOOGLE_EMAILS", "").split(",")
               if e.strip()}
    missing = [n for n, v in (("GOOGLE_OAUTH_CLIENT_SECRET", client_secret),
                              ("MCP_BASE_URL", base_url),
                              ("ALLOWED_GOOGLE_EMAILS", allowed)) if not v]
    if missing:
        raise SystemExit(f"GOOGLE_OAUTH_CLIENT_ID is set but {', '.join(missing)} missing")
    return AllowlistGoogleProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        allowed_emails=allowed,
        # email is required for the allowlist; profile rounds out the identity.
        required_scopes=["openid", "email", "profile"],
    )


AUTH = build_auth()
mcp = FastMCP("vacourts", auth=AUTH)


def _resolve(locality: str) -> dict:
    l = BY_CODE.get(locality) or BY_NAME.get(locality.lower())
    if not l:
        raise ValueError(f"unknown locality '{locality}' (use 3-digit code or name)")
    return l


@mcp.tool
def list_localities() -> list[dict]:
    """All 133 VA localities (counties + cities) with court codes and coverage flags."""
    return LOCALITIES


@mcp.tool
def search_bulk(locality: str = None, division: str = None, charge: str = None,
                code_section: str = None, person_id: str = None, year: int = None,
                limit: int = 100) -> list[dict]:
    """Search the local ANONYMIZED bulk store (virginiacourtdata dump, 2005-2025).
    NOTE: this data has NO party names / case numbers / DOB (stripped at source), so
    you CANNOT look someone up by name here. Filter by locality (3-digit code or name),
    division (civil|criminal), charge keyword, code_section, person_id (the only
    cross-case identity in criminal data), and/or year. For name-based lookups use
    lookup_pointer (official OCIS/CJISWeb). Returns [] if the store isn't ingested yet."""
    fips = _resolve(locality)["code"] if locality else None
    return store.search(fips=fips, division=division, charge=charge,
                        code_section=code_section, person_id=person_id, year=year, limit=limit)


@mcp.tool
def bulk_stats(group_by: str = "division") -> list[dict]:
    """Aggregate row counts in the local bulk store, grouped by one of:
    division | court_level | fips | disposition | year. The anonymized data is best
    used for aggregate/statistical queries (counts by locality, charge, disposition)
    rather than individual name lookups."""
    return store.stats(group_by)


@mcp.tool
def lookup_pointer(locality: str = None, division: str = "criminal") -> dict:
    """For activity newer than the bulk dump (or not covered by it): returns the OFFICIAL Virginia
    court lookup URL + step-by-step instructions for a HUMAN to run the search by hand.
    Automates nothing (OCIS 2.0 EULA bars automated scripting). division: criminal|traffic|civil."""
    if division in ("criminal", "traffic"):
        return {
            "system": "OCIS 2.0 (statewide adult criminal/traffic)",
            "url": OCIS_URL,
            "steps": [
                "Open the URL and Accept the terms (clickwrap).",
                "Solve the reCAPTCHA.",
                "Search by last/first name (optionally DOB).",
                "Open each result for charges, disposition, and hearings.",
            ],
            "note": "Statewide; no locality needed. Manual lookup only.",
        }
    # civil -> per-court CJISWeb
    if locality:
        l = _resolve(locality)
        circuit = l.get("cjisweb_circuit", True)
        return {
            "system": "CJISWeb (per-court civil)",
            "url": CJIS_CIRCUIT if circuit else None,
            "court": l["name"],
            "court_code": l["code"],
            "steps": ([
                "Open the Circuit Court CJISWeb URL.",
                f"Select the court by name: {l['name']}.",
                "Accept terms, solve reCAPTCHA, choose Civil, and search by name.",
            ] if circuit else []),
            "note": ("Civil is court-by-court; one locality at a time. Manual lookup only."
                     + ("" if circuit else f" {l['name']} runs its own CMS — check the locality's own portal.")),
        }
    return {
        "system": "CJISWeb (per-court civil)",
        "url": CJIS_CIRCUIT,
        "note": "Civil is court-by-court. Pass a locality (3-digit code or name) for court-specific steps.",
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="vacourts-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"],
                        default=os.environ.get("MCP_TRANSPORT", "stdio"),
                        help="stdio (default) or http (streamable-HTTP for remote/nginx)")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3032")))
    parser.add_argument("--path", default=os.environ.get("MCP_PATH", "/mcp"))
    args = parser.parse_args()

    if args.transport == "http":
        # Fail closed: never expose court data over HTTP without auth unless
        # explicitly opted out (local testing only).
        if AUTH is None and os.environ.get("ALLOW_UNAUTHENTICATED") != "1":
            raise SystemExit(
                "Refusing to serve HTTP without auth. Set GOOGLE_OAUTH_CLIENT_ID / "
                "GOOGLE_OAUTH_CLIENT_SECRET / MCP_BASE_URL / ALLOWED_GOOGLE_EMAILS, "
                "or set ALLOW_UNAUTHENTICATED=1 for local testing."
            )
        mcp.run(transport="http", host=args.host, port=args.port, path=args.path)
    else:
        mcp.run()  # bare stdio (local Claude Desktop / fastmcp dev)
