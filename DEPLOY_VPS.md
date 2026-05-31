# vacourts-mcp :: VPS deploy runbook

Bulk-first design, no live scraping (OCIS 2.0 EULA bars automated scripting/data-mining).
Programmatic data = local SQLite from virginiacourtdata.org CSVs (Circuit + GD, civil + criminal,
names present, through 2024). `bulk_ingest.py` auto-detects all 4 dataset schemas. `lookup_pointer`
returns a URL + steps for a human one-off lookup; it does not automate access.

Deploy is run directly on `178.16.141.166` over SSH (the Shell MCP host mount is unreliable, issue #1).

## Staged tarball (exact tested bytes)
- URL: https://tmpfiles.org/dl/wpw1eZAbLwph/vacourts.tgz  (expires ~24h from 2026-05-28; reupload if dead)
- sha256: `1812b4fc871372591d83ce012c963a1a9731c88ec1d06e04ad1c20ccd0d82fa4`
- contents: server.py, store.py, schema.py, bulk_ingest.py, lookups.py, localities.yaml (133), pyproject.toml, requirements.txt, .env.example, DEPLOYMENT.md

## One-shot install (flat, paste as-is over SSH)
```bash
cd /opt && python3 -c 'import urllib.request;urllib.request.urlretrieve("https://tmpfiles.org/dl/wpw1eZAbLwph/vacourts.tgz","/tmp/v.tgz")' \
 && sha256sum /tmp/v.tgz | grep -q 1812b4fc871372591d83ce012c963a1a9731c88ec1d06e04ad1c20ccd0d82fa4 \
 && mkdir -p /opt/vacourts-mcp && tar xzf /tmp/v.tgz -C /opt/vacourts-mcp && cd /opt/vacourts-mcp \
 && cp -n .env.example .env && /root/.local/bin/uv venv --python 3.13 \
 && /root/.local/bin/uv pip install -r requirements.txt \
 && .venv/bin/python -c 'import fastmcp,yaml,bulk_ingest,server;print("OK")'
```
(No chromium step anymore; patchright dependency removed with the scraper.)

## systemd unit  (/etc/systemd/system/vacourts-mcp.service)
Port 3031 (3030/8020/8100 already used). Mirrors attom-mcp.
```ini
[Unit]
Description=Virginia Courts MCP (vacourts.nlma.io)
After=network.target
[Service]
Type=simple
User=root
WorkingDirectory=/opt/vacourts-mcp
EnvironmentFile=/opt/vacourts-mcp/.env
ExecStart=/opt/vacourts-mcp/.venv/bin/python -m server --transport http --host 127.0.0.1 --port 3031
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now vacourts-mcp && systemctl status vacourts-mcp --no-pager
```

## Load bulk data
Download Circuit + GD CSV/ZIPs from virginiacourtdata.org, then:
```bash
.venv/bin/python bulk_ingest.py /path/to/*.zip
```

## Caddy vhost + connector (defer until MCP_OWNER_PASSWORD cookie added to server.main)
vacourts.nlma.io -> 127.0.0.1:3031, mirror /etc/caddy/attom.nlma.io, then add the connector in Claude.

## After install
`git init` if needed and push the working tree to origin so the repo holds source once the tarball lapses.
