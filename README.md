# vacourts-mcp

Virginia court public-records MCP. Bulk historical search over the **anonymized**
virginiacourtdata.org dump (2005–2025) plus a human **lookup pointer** to the official
OCIS / CJISWeb systems. Read-only, internal due-diligence use only.

Note: the anonymized bulk data has **no party names, case numbers, or DOB** (stripped at
source) — you search it by locality / division / charge / code section / person_id / year,
not by name. For name lookups, `lookup_pointer` hands you the official URL + steps. The live
patchright scraper was removed (the OCIS 2.0 EULA bars automated scripting).

Tools: `list_localities`, `search_bulk`, `bulk_stats`, `lookup_pointer`.
Deploy + data-load instructions: see `DEPLOYMENT.md`.
## License

Copyright © 2026 Next Level Management Advisors, LLC.

Licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0) — see [LICENSE](LICENSE). If you run a modified version over a network, the AGPL requires you to make your modified source available to its users.

**Commercial licensing:** to use this in a closed-source or commercial product, or to host a modified version without publishing your source, a commercial license is available — contact **forrest@nlma.io**.
