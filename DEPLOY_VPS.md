# vacourts-mcp :: VPS deploy runbook (superseded)

**This file is stale and unrunnable as written — do not follow it.** It predates the real
deploy and got several facts wrong before the VPS ever ran this service:

- Port 3031 is taken by DocuSeal (and 3030 by attom-mcp) — the live deploy uses **3032**.
- The vhost step describes Caddy — the VPS runs **nginx** (+ certbot DNS-01), not Caddy.
- The "staged tarball" install URL was a temporary tmpfiles.org link that has since expired —
  install from `git clone` instead.

**Use [`DEPLOYMENT.md`](DEPLOYMENT.md)** — it reflects the actual live deployment (nginx,
port 3032, git-based install, OAuth setup, and the nginx-drift check) and is kept in sync with
`deploy/`.

See [#3](https://github.com/NextLevelManagementAdvisors/vacourts-mcp/issues/3) for the full
list of blockers this file caused.
