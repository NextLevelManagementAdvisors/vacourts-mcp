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
import yaml, pathlib, argparse, os, logging, json, threading, time, urllib.request
from urllib.parse import parse_qs, urlparse
from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy.ui import create_error_html
from fastmcp.server.auth.providers.google import GoogleProvider, GoogleTokenVerifier
from fastmcp.server.auth.auth import AccessToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
import store

log = logging.getLogger("vacourts.auth")

ROOT = pathlib.Path(__file__).parent
LOCALITIES = yaml.safe_load(open(ROOT / "localities.yaml"))["localities"]
BY_CODE = {l["code"]: l for l in LOCALITIES}
BY_NAME = {l["name"].lower(): l for l in LOCALITIES}

OCIS_URL     = "https://eapps.courts.state.va.us/ocis/landing"
CJIS_CIRCUIT = "https://eapps.courts.state.va.us/CJISWeb/circuit.html"
CJIS_GD      = "https://eapps.courts.state.va.us/gdcourts"


# ---- org-wide approved-domains registry ------------------------------------
# status.nlma.io Domains card (seeded from the claude.ai org's verified domains),
# also read by bright-auth, gbp-mcp, skiptrace-mcp, vacode-mcp, vin-mcp and
# qbo-oauth. Refreshed on a daemon thread so verify_token (called per request)
# never blocks on the network. On fetch failure keep the last-known-good set,
# or the baked-in defaults before the first success. AUTHORIZED_DOMAINS_URL=""
# disables it (env allowlists only).
_REGISTRY_DEFAULTS = frozenset({
    "aristidemanagement.com", "fidumcompany.com", "hvacfrontroyal.com", "mattmirus.com",
    "nextlevelmanagementadvisors.com", "nlma.io", "propmanageplus.com", "tra-lawfirm.com",
    "turboclaim.ai", "zipadeeservices.com"})
_registry: dict = {"domains": frozenset(), "started": False}


def _fetch_registry(url: str) -> frozenset[str] | None:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            doms = frozenset(str(d).strip().lower()
                             for d in json.loads(r.read().decode()).get("domains", [])
                             if str(d).strip())
        return doms or None
    except Exception as e:  # noqa: BLE001 - any failure falls back to last-known-good
        log.warning("vacourts: domain registry fetch failed: %r", e)
        return None


def start_domain_registry() -> None:
    url = os.environ.get("AUTHORIZED_DOMAINS_URL", "https://status.nlma.io/domains.json")
    if not url or _registry["started"]:
        return
    ttl = int(os.environ.get("AUTHORIZED_DOMAINS_TTL", "300"))
    _registry["started"] = True
    _registry["domains"] = _fetch_registry(url) or _REGISTRY_DEFAULTS

    def _loop():
        while True:
            time.sleep(ttl)
            doms = _fetch_registry(url)
            if doms:
                _registry["domains"] = doms

    threading.Thread(target=_loop, name="domain-registry", daemon=True).start()


def registry_domains() -> frozenset[str]:
    return _registry["domains"]


# ---- auth -------------------------------------------------------------------
# claude.ai (and other MCP web clients) only authenticate via OAuth + Dynamic
# Client Registration. FastMCP's GoogleProvider is an OAuthProxy: it synthesizes
# DCR for the client and proxies the real login to Google. Access is then locked
# to an explicit email/domain allowlist (no FastMCP provider ships one), so
# completing a Google login is necessary but not sufficient.
class AllowlistGoogleTokenVerifier(GoogleTokenVerifier):
    """Google token verifier that additionally requires a verified, allowlisted email/domain."""

    def __init__(self, *, allowed_emails: set[str], allowed_domains: set[str], **kw):
        super().__init__(**kw)
        self._emails = {e.strip().lower() for e in allowed_emails if e.strip()}
        self._domains = {d.strip().lower().lstrip("@") for d in allowed_domains if d.strip()}

    def _allowed_email(self, access: AccessToken) -> str | None:
        """The verified, allowlisted email for `access`, or None if it doesn't qualify."""
        claims = access.claims or {}
        email = (claims.get("email") or "").lower()
        if not email or claims.get("email_verified") is False:
            return None
        domain = email.rpartition("@")[2]
        if email in self._emails or (domain and (domain in self._domains
                                                  or domain in registry_domains())):
            return email
        return None

    async def verify_token(self, token: str) -> AccessToken | None:
        access = await super().verify_token(token)
        if access is None:
            return None
        if self._allowed_email(access) is None:
            log.warning("vacourts: rejecting non-allowlisted email %r",
                        (access.claims or {}).get("email") or "<none>")
            return None
        return access


def _code_from_redirect(response: RedirectResponse) -> str | None:
    location = response.headers.get("location")
    if not location:
        return None
    return parse_qs(urlparse(location).query).get("code", [None])[0]


class AllowlistGoogleProvider(GoogleProvider):
    """GoogleProvider whose token verifier enforces an email/domain allowlist."""

    def __init__(self, *, allowed_emails: set[str], allowed_domains: set[str], **kw):
        super().__init__(**kw)
        # OAuthProxy stores the verifier as self._token_validator and routes every
        # verify_token() call through it; swap in the allowlisting one, preserving
        # the normalized required scopes the GoogleProvider computed.
        self._token_validator = AllowlistGoogleTokenVerifier(
            allowed_emails=allowed_emails,
            allowed_domains=allowed_domains,
            required_scopes=self._token_validator.required_scopes,
        )

    async def _handle_idp_callback(self, request: Request) -> HTMLResponse | RedirectResponse:
        """Reject non-allowlisted users here, before a client code is issued.

        Without this, a non-allowlisted user completes Google sign-in successfully,
        the connector gets a valid-looking code/token, and only discovers they're
        rejected when the MCP client calls the server and gets a bare 401 -- which
        looks like an expired token and sends the client into a retry loop instead
        of telling the user to ask the admin for access.
        """
        response = await super()._handle_idp_callback(request)
        if not isinstance(response, RedirectResponse):
            return response
        code = _code_from_redirect(response)
        code_model = await self._code_store.get(key=code) if code else None
        idp_access_token = (code_model.idp_tokens or {}).get("access_token") if code_model else None
        if not idp_access_token:
            return response
        verifier = self._token_validator
        access = await GoogleTokenVerifier.verify_token(verifier, idp_access_token)
        if access is not None and verifier._allowed_email(access) is not None:
            return response
        await self._code_store.delete(key=code)
        email = (access.claims or {}).get("email") if access else None
        log.warning("vacourts: rejecting non-allowlisted email %r at OAuth callback", email or "<none>")
        html_content = create_error_html(
            error_title="Not Authorized",
            error_message=f"{email or 'This Google account'} is not authorized for vacourts. "
                          "Ask the admin to add it to ALLOWED_GOOGLE_EMAILS or ALLOWED_GOOGLE_DOMAINS.",
        )
        return HTMLResponse(content=html_content, status_code=403)


def build_auth():
    """Build the Google OAuth provider from env, or None if not configured.

    GOOGLE_OAUTH_CLIENT_ID present => OAuth is enabled and CLIENT_SECRET,
    MCP_BASE_URL, and at least one of ALLOWED_GOOGLE_EMAILS/ALLOWED_GOOGLE_DOMAINS
    are all required (fail closed).
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        return None
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    base_url = os.environ.get("MCP_BASE_URL")
    allowed_emails = {e.strip().lower()
                      for e in os.environ.get("ALLOWED_GOOGLE_EMAILS", "").split(",")
                      if e.strip()}
    allowed_domains = {d.strip().lower().lstrip("@")
                       for d in os.environ.get("ALLOWED_GOOGLE_DOMAINS", "").split(",")
                       if d.strip()}
    missing = [n for n, v in (("GOOGLE_OAUTH_CLIENT_SECRET", client_secret),
                              ("MCP_BASE_URL", base_url),
                              ("ALLOWED_GOOGLE_EMAILS or ALLOWED_GOOGLE_DOMAINS",
                               allowed_emails or allowed_domains)) if not v]
    if missing:
        raise SystemExit(f"GOOGLE_OAUTH_CLIENT_ID is set but {', '.join(missing)} missing")
    kw = {}
    # A fixed signing key keeps the FastMCP-issued JWTs (and the derived, disk-persisted
    # OAuth-state directory under FASTMCP_HOME) stable across restarts and client-secret
    # rotations. Without it, OAuthProxy derives the key from GOOGLE_OAUTH_CLIENT_SECRET,
    # which is deterministic but silently invalidates every session if that secret ever
    # changes. Optional: falls back to that derivation, unchanged, when unset.
    jwt_signing_key = os.environ.get("FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY")
    if jwt_signing_key:
        kw["jwt_signing_key"] = jwt_signing_key
    # Env allowlists are unioned with the org-wide registry (see start_domain_registry).
    start_domain_registry()
    return AllowlistGoogleProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        allowed_emails=allowed_emails,
        allowed_domains=allowed_domains,
        # email is required for the allowlist; profile rounds out the identity.
        required_scopes=["openid", "email", "profile"],
        **kw,
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
def lookup_pointer(locality: str = None, division: str = "criminal",
                    court_level: str = "district") -> dict:
    """For activity newer than the bulk dump (or not covered by it): returns the OFFICIAL Virginia
    court lookup URL + step-by-step instructions for a HUMAN to run the search by hand.
    Automates nothing (OCIS 2.0 EULA bars automated scripting). division: criminal|traffic|civil.
    court_level (civil only): district|circuit. Defaults to district: the bulk data shows the vast
    majority of civil filings (warrants in debt, unlawful detainer) are General District Court, not
    Circuit — passing court_level="circuit" only when you specifically need circuit civil (e.g.
    larger-dollar suits, appeals)."""
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
    if court_level not in ("district", "circuit"):
        raise ValueError("court_level must be 'district' or 'circuit'")
    # civil, General District Court (warrants in debt, unlawful detainer, etc.)
    if court_level == "district":
        result = {
            "system": "GDC Online Case Information (per-court civil, General District Court)",
            "url": CJIS_GD,
            "note": "Covers warrants in debt, unlawful detainer, and other GDC civil matters. "
                    "Manual lookup only.",
        }
        if locality:
            l = _resolve(locality)
            result["court"] = l["name"]
            result["court_code"] = l["code"]
            result["steps"] = [
                "Open the GDC Online Case Information URL.",
                f"Select the court by name: {l['name']}.",
                "Search by name (case types include warrant in debt / unlawful detainer).",
            ]
        else:
            result["steps"] = [
                "Open the GDC Online Case Information URL.",
                "Select the court by locality name.",
                "Search by name.",
            ]
        return result
    # civil, Circuit Court -> per-court CJISWeb
    if locality:
        l = _resolve(locality)
        circuit = l.get("cjisweb_circuit", True)
        return {
            "system": "CJISWeb (per-court civil, Circuit Court)",
            "url": CJIS_CIRCUIT if circuit else None,
            "court": l["name"],
            "court_code": l["code"],
            "steps": ([
                "Open the Circuit Court CJISWeb URL.",
                f"Select the court by name: {l['name']}.",
                "Accept terms, solve reCAPTCHA, choose Civil, and search by name.",
            ] if circuit else []),
            "note": ("Circuit civil is court-by-court; one locality at a time. Manual lookup only."
                     + ("" if circuit else f" {l['name']} runs its own CMS — check the locality's own portal.")),
        }
    return {
        "system": "CJISWeb (per-court civil, Circuit Court)",
        "url": CJIS_CIRCUIT,
        "note": "Circuit civil is court-by-court. Pass a locality (3-digit code or name) for court-specific steps.",
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
