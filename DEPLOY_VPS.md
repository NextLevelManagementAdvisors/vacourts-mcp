# vacourts-mcp :: VPS deploy runbook

Scaffold built + tested in sandbox; transfer to the VPS was blocked by the Shell MCP host-mount
being intermittently absent (see issue #1). Run this directly on `178.16.141.166` (SSH, where the
mount is not a factor) to finish the install.

## Staged tarball (exact tested bytes)
- URL: https://tmpfiles.org/dl/wyw0AKpGoQPE/vacourts.tgz  (expires ~24h from 2026-05-28; reupload if dead)
- sha256: `9a10b0a8e4b289fc502b3a963868acf45a301c856af000a85794f08c3efb67a1`
- contents: server.py, store.py, schema.py, bulk_ingest.py, patchright_client.py, localities.yaml (133 localities), pyproject.toml, requirements.txt, .env.example, DEPLOYMENT.md

## One-shot install (flat, paste as-is)
```bash
cd /opt && python3.12 -c 'import urllib.request;urllib.request.urlretrieve("https://tmpfiles.org/dl/wyw0AKpGoQPE/vacourts.tgz","/tmp/v.tgz")' \
 && sha256sum /tmp/v.tgz | grep -q 9a10b0a8e4b289fc502b3a963868acf45a301c856af000a85794f08c3efb67a1 \
 && mkdir -p /opt/vacourts-mcp && tar xzf /tmp/v.tgz -C /opt/vacourts-mcp && cd /opt/vacourts-mcp \
 && cp -n .env.example .env \
 && /root/.local/bin/uv venv --python /usr/bin/python3.12 \
 && /root/.local/bin/uv pip install -r requirements.txt \
 && .venv/bin/patchright install chromium \
 && .venv/bin/python -c 'import fastmcp,patchright,yaml;print("DEPS_OK")'
```

## systemd unit  (/etc/systemd/system/vacourts-mcp.service)
Mirrors attom-mcp. Port 3031 (3030/8020/8100 already used).
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

## Caddy vhost (defer until live layer works + MCP_OWNER_PASSWORD set)
Add vacourts.nlma.io -> reverse_proxy 127.0.0.1:3031, mirroring /etc/caddy/attom.nlma.io. Then add
the connector in Claude. Do NOT expose publicly until the password cookie wrapper is in server.py:main (TODO).

## Then: build-out (issue #2)
Live selector recon on OCIS + CJISWeb via patchright (CAPTCHA solved by hand once), fill the
TODO:LIVE selectors in patchright_client.py.
