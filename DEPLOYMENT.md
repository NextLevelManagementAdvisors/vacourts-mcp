# vacourts-mcp

Virginia court public-records MCP. **Bulk-only + human lookup pointer** (the live
patchright scraper was removed — the OCIS 2.0 EULA bars automated scripting). Read-only,
internal due-diligence use only. Live at **https://vacourts.nlma.io/mcp** (Google OAuth —
access limited to an email allowlist; see **Auth** below).

## Layers / tools
- **bulk** — local SQLite (`va_cases.sqlite`) from the *anonymized* virginiacourtdata.org
  dump (2005–2025). `download_anon.py` (manifest-driven fetch) + `bulk_ingest.py` (streaming
  ingest) + `store.py`.
  - ⚠️ The anonymized dump has **NO names / case numbers / DOB** (stripped at source). Criminal
    rows carry `person_id` as the only cross-case identity; civil rows carry none. Rows are
    per hearing/charge. So bulk search is by locality / division / charge / code_section /
    person_id / year — **not by name**.
- **lookup_pointer** — returns the official OCIS / CJISWeb URL + human steps for a name-based
  one-off lookup. Automates nothing.

FastMCP tools: `list_localities`, `search_bulk`, `bulk_stats`, `lookup_pointer`.

## Files
- `server.py`        FastMCP server (stdio default; `--transport http` for the VPS)
- `store.py`         SQLite schema + search/stats (anon-shaped)
- `bulk_ingest.py`   streaming ingester, verified 4-way anon COLMAP, indexes-after-load
- `download_anon.py` manifest-driven downloader (URLs rotate — read the live manifest)
- `localities.yaml`  133 localities keyed on 3-digit FIPS
- `schema.py`        pydantic record shape
- `deploy/`          systemd unit, nginx vhost (proxies OAuth + /mcp to the app), rate-limit zone, landing page

## Live deployment (VPS 178.16.141.166, nginx, port 3032)
Mirrors attom-mcp (Python uv venv). See `deploy/` for the exact artifacts.
```bash
# on the VPS, /opt/vacourts-mcp
/root/.local/bin/uv venv --python 3.13   # uv fetches a managed CPython 3.13 if the system lacks it
/root/.local/bin/uv pip install -r requirements.txt
# systemd: ExecStart=.venv/bin/python -m server --transport http --host 127.0.0.1 --port 3032
# nginx: deploy/vacourts.nlma.io.nginx  (proxies /mcp + OAuth routes to the app; NO `listen [::]` — Tailscale owns IPv6 :443)
# TLS:  certbot certonly --manual --preferred-challenges dns-01 \
#         --manual-auth-hook /usr/local/bin/certbot-hostinger-auth.sh \
#         --manual-cleanup-hook /usr/local/bin/certbot-hostinger-cleanup.sh \
#         -d vacourts.nlma.io --key-type ecdsa
systemctl enable --now vacourts-mcp
```

## Auth (Google OAuth + email allowlist)

The app (`server.py`) wires FastMCP's `GoogleProvider`, an `OAuthProxy` that synthesizes
Dynamic Client Registration for web clients (claude.ai) and proxies the real login to
Google. nginx no longer gates — it just proxies; the app is both the OAuth authorization
server and the resource server. Access is locked to `ALLOWED_GOOGLE_EMAILS` and/or
`ALLOWED_GOOGLE_DOMAINS` (`AllowlistGoogleTokenVerifier`): a verified Google login is
necessary but **not sufficient**. A non-allowlisted login is rejected at the OAuth callback
with a readable "Not Authorized" page, instead of a bare 401 the MCP client retries forever.

OAuth state (registered clients, issued tokens) is an encrypted file store under
`FASTMCP_HOME` (see `docker-compose.yml`, already on the bind-mounted volume) — it survives
restarts as long as the JWT signing key is stable. Without `FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY`
set, that key is derived from `GOOGLE_OAUTH_CLIENT_SECRET`, so it's stable too *unless* the
secret is ever rotated. Set the signing key explicitly (`openssl rand -hex 32`) to decouple
the two.

Endpoints the app serves (all proxied by nginx): `/.well-known/oauth-authorization-server`,
`/.well-known/oauth-protected-resource/mcp`, `/authorize`, `/token`, `/register`,
`/auth/callback`, `/consent`, `/mcp`.

**Google Cloud setup (one-time):**

1. console.cloud.google.com → APIs & Services → OAuth consent screen → **External**;
   add your email(s) as **Test users** (or publish). Scopes: `openid`, `email`, `profile`.
2. Credentials → Create credentials → **OAuth client ID** → **Web application**.
3. Authorized redirect URI: `https://vacourts.nlma.io/auth/callback`
4. Copy the client ID + secret into `/opt/vacourts-mcp/.env` (see `.env.example`):
   `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `MCP_BASE_URL=https://vacourts.nlma.io`,
   `ALLOWED_GOOGLE_EMAILS=forrest@nlma.io[,...]` (and/or `ALLOWED_GOOGLE_DOMAINS=nlma.io[,...]`),
   `FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY=$(openssl rand -hex 32)`.
   `chmod 600 .env`, then `systemctl restart vacourts-mcp`.

The app **fails closed**: with `MCP_TRANSPORT=http` and no `GOOGLE_OAUTH_CLIENT_ID` it refuses
to start (unless `ALLOW_UNAUTHENTICATED=1`, for local testing only).

### Verifying the live vhost matches this repo (nginx drift check)

`deploy/vacourts.nlma.io.nginx` in git is the only auth model this app supports: nginx proxies
everything and the app (Google OAuth) gates access. There is no CD for this repo — the VPS is
updated by hand over SSH — so the live `/etc/nginx/sites-enabled/vacourts.nlma.io` can silently
drift from what's committed (this is exactly what caused #5: a static `Bearer` `if`-gate got
added on the box outside of git, which 401'd every OAuth-based connector, incl. claude.ai,
before it ever reached the app). After any manual nginx edit, or periodically, confirm the two
are identical and the OAuth surface is actually reachable:

```bash
# on the VPS: byte-for-byte diff against what's checked in
diff /etc/nginx/sites-enabled/vacourts.nlma.io /opt/vacourts-mcp/deploy/vacourts.nlma.io.nginx

# from anywhere: the app's OAuth metadata must be reachable with NO Authorization header
curl -s -o /dev/null -w '%{http_code}\n' https://vacourts.nlma.io/.well-known/oauth-authorization-server
# -> 200 (a 401/404 here means nginx is gating before the app, or the vhost is stale)
```

If the diff shows any local edit (e.g. an `if ($http_authorization ...)` block), that edit is
the bug: replace it with the repo's version, `nginx -t && systemctl reload nginx`, then re-add
the connector in Claude.ai.

## Load / refresh bulk data
```bash
.venv/bin/python download_anon.py --dir dumps           # ~3.3 GB compressed
.venv/bin/python bulk_ingest.py  --dir dumps --reset    # 4 core types -> va_cases.sqlite
```
The store stays local; never expose it without auth and never redistribute (see LEGAL).

## LEGAL
- Va. 2018 bulk-data statute (§ 17.1-208(D) circuit / § 16.1-69.54:1(C) district): aggregated
  case data may NOT be sold, re-hosted, or redistributed to third parties, and must not be made
  available to the general public. Internal-only + auth-gated + local store satisfies this.
- Use the **anonymized** dump only. Name-bearing "complete" data is gated to journalists /
  non-profits / research / government; do not misrepresent eligibility to obtain it. The
  sanctioned channel for consented name-based screening is the VDBC (see `VDBC_registration_NLMA.md`).
- Judiciary is exempt from VA FOIA; access flows from the public-record provisions above.

(`DEPLOY_VPS.md` is an earlier runbook and is superseded by this file — it predates the nginx /
port-3032 / anon-data facts established at deploy time.)
