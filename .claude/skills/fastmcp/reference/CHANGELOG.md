# FastMCP version history (3.0.0 → 3.4.3)

Compiled 2026-07-07 from `docs/fastmcp/docs/updates.mdx` (official changelog) plus direct git-log
inspection of the `docs/fastmcp` submodule, then re-audited 2026-07-07 against the submodule docs,
the installed `.venv` package source, and authoritative external sources (NVD/GHSA/PyPI/the
PrefectHQ/fastmcp repo). Every version entry, code-name, date, CVE/GHSA ID, and the `257fe325`
caching commit is confirmed; the re-audit corrected six items (see git history of this file).
Version numbers are as precise as sources allow — flag anything you verify further so this file
stays current (see "How to refresh" below).

## 3.0.0

- **`ResourceResult`/`ResourceContent`** established as the canonical resource return type (list
  of per-item content, individual MIME types/metadata).
- **`version` kwarg** added to `@mcp.resource`/`@mcp.tool`/`@mcp.prompt`; the selected version is
  surfaced through `meta.fastmcp.version`/`meta.fastmcp.versions` (and clients can request one via
  `_meta.fastmcp.version`) — it rides the `_meta` channel, not a field separate from it.
- **RFC 6570 URI template query params** (`{?param1,param2}`) — note: `updates.mdx` attributes
  these to **2.13.0** (Oct 2025), not 3.0.0. The `{param}` / `{param*}` (wildcard) / `{?...}`
  (query) forms are all valid in 3.x; see reference/registration.md for the working syntax.
- **OAuth Proxy gains CIMD** (client ID metadata document) support.
- Component visibility controls added.

## 3.0.2

- Fix: MCP transport auth headers no longer leak through to downstream OpenAPI APIs (issue #3260,
  fixed by PR #3262).
- Fix: background task workers correctly receive the originating request ID.

## 3.1.0 — "Code to Joy" (2026-03-03)

- **Code Mode Transform**: instead of exposing the raw tool catalog, the LLM gets meta-tools —
  search for relevant tools via BM25, inspect schemas, then write Python chaining `call_tool()`
  calls inside a sandbox. Reduces context spent on tool schemas for large tool catalogs.
- **`MultiAuth`**: composes multiple token-verification sources into one auth layer. Tries a
  designated `server` (an OAuth Proxy, which owns all OAuth routes/metadata) first, then
  `verifiers` in list order (contributing only token-verification logic); 401 if all fail.
- PropelAuth provider support.
- Google GenAI sampling handler.

## 3.1.1

- Pin `pydantic-monty<0.0.8` — hotfix for a breaking change in Monty affecting Code Mode.

## 3.2.0 — "Show Don't Tool"

- **The Apps release**: tools can return interactive UIs (charts, dashboards, forms, maps) via
  `FastMCPApp` — `@app.ui()` for LLM-visible tools, `@app.tool()` for backend tools the UI calls.
- **Security hardening pass**, tied to GHSA-vv7q-7jx5-f767 (OpenAPI provider SSRF/path
  traversal): SSRF/path-traversal prevention (URL-encoding path params, restricting `$ref`
  resolution to local refs), JWT algorithm restriction (blocks `HS*` when JWKS is configured),
  OAuth scope enforcement (prefers IdP-granted scopes), CSRF double-submit cookie validation,
  refresh-token misuse prevention (rejects refresh tokens used as Bearer tokens).
- **Breaking change** ⚠️: `FastMCPApp` tool calls now route through `___`-prefixed compound tool
  names internally (PR #3667), replacing a prior `_meta`-injection approach that broke in real MCP
  hosts (Goose, MCP Jam) that don't forward `_meta` on `callServerTool`. **Superseded two patches
  later**: 3.2.4 (#3824) replaced the `___` scheme with hash-based backend tool routing — so the
  literal `AppName___tool_name` format is a 3.2.0–3.2.3-only artifact, not the current mechanism.
- Dev server: `fastmcp dev apps` previews app tools in-browser with an MCP message inspector.

## 3.2.1 – 3.2.4 (patch line)

- 3.2.1: auth-provider audience validation fixes (Cognito `client_id`, Azure `identifier_uri`),
  consent-cookie LRU cap, OpenAPI 3.0 `nullable` field leak fix.
- 3.2.2: fixes the Azure audience regression from 3.2.1.
- 3.2.3: pins `fakeredis<2.35.0` (2.35.0 rename broke pydocket's `memory://` backend).
- 3.2.4: background tasks scoped to authorization context instead of MCP session (**breaking**
  for session-scoped semantics), docstring-derived parameter descriptions, `FileUpload`
  decoded-base64-size validation, proxy stops forwarding inbound headers to unrelated servers,
  Keycloak OAuth provider added, and the 3.2.0 `___`-prefixed app-tool routing replaced with
  hash-based backend routing (#3824) — also breaking for anyone who hard-coded the `___` names.

## 3.3.0 — "Slim Reaper"

- **`fastmcp-slim`**: dependency-light distribution shipping client + transport layer without
  Starlette/Uvicorn/server stack — same import namespace, lighter footprint for CI/agents/library
  dependents.
- OAuth proxy hardening: silent-consent AS-in-the-middle guard, dot-segment redirect rejection,
  per-token response cache partitioning.
- `AzureB2CProvider` user flows, public `update_scopes()` on `OAuthProxy`.
- `@mcp.tool(run_in_thread=False)` for thread-affine tools.

## 3.3.1 — "Loop There It Is"

- Hotfix for the 3.3 packaging split: standalone component imports (`from fastmcp.tools import
  tool`) no longer pull in the server stack or trip a circular import.
- **This is the version MorgenMCP shipped on until 2026-07-07.**

## 3.4.0 — "Remote Control"

- **`fastmcp-remote`**: standalone stdio↔HTTP bridge package — `uvx fastmcp-remote
  https://example.com/mcp` connects stdio-only hosts to HTTP-hosted servers, OAuth auto-enabled
  for HTTPS.
- Proxies now forward `initialize` upstream — a missing/misconfigured backend fails the handshake
  loudly instead of returning an empty-but-connected proxy.
- `fastmcp_access_token_expiry_seconds` decouples client-facing token lifetime from short
  upstream `expires_in`.
- `ToolResult(..., is_error=True)` returns rich errors the model can act on instead of only
  raising.

## 3.4.1 — "Floor It"

- Security patch: floors `starlette>=1.0.1`, closing CVE-2026-48710 (previously only constrained
  transitively via `mcp`).
- OAuthProxy logs refresh-token cache misses instead of failing silently.

## 3.4.2 — "Heads Up"

- Compatibility patch: `JWTVerifier` now accepts JWTs with private, non-critical JWS header
  parameters (e.g. Clerk's `cat`) instead of rejecting before signature/claim validation.

## 3.4.3 — "The Fast and the Secure-ious" (2026-07-05)

- SSRF allow-list hardening: every IPv6 transition form (NAT64, 6to4, Teredo, ISATAP) now
  unwraps to its embedded IPv4 target and is checked against the same allow-list policy.
- DNS rebinding protection: Streamable HTTP validates `Host` and browser `Origin` before session
  handling.
- Stricter OAuth redirects: unsafe schemes rejected before registration, DCR clients bound to
  their registered redirect URIs.
- Reliability: proxy session-teardown races, discriminator-tag handling in JSON schema
  conversion, several middleware/resource-template fixes.
- **This is the version MorgenMCP upgraded to on 2026-07-07** (`fastmcp>=3.4,<3.5`).

## Relevant to a specific bug hunt (caching middleware)

Between 3.3.1 and 3.4.3, commit `257fe325` ("fix: caching middleware TypeError on cache miss due
to mismatched call_next parameter", #4301) patched a positional/keyword mismatch in the
*vendored `fastmcp_slim` docs-submodule snapshot's* middleware chain composition
(`fastmcp_slim/fastmcp/server/server.py`). **This did not reproduce against the actually
installed 3.3.1 package** — the installed chain composition (`partial(mw, call_next=chain)`) is
shaped differently and was verified empirically (via `Client(mcp).list_tools()`) to work fine on
both 3.3.1 and 3.4.3. Lesson: the `docs/fastmcp` submodule's *git history* can contain commits
that don't map cleanly onto the installed PyPI package's actual code layout — always verify
against the installed package (`.venv/lib/.../site-packages/fastmcp/`), not just submodule diffs,
before concluding a changelog entry affects this repo.

**Second lesson from the same investigation**: an earlier version of this file, and of SKILL.md /
reference/middleware.md, claimed `ResponseCachingMiddleware` was hand-rolled by MorgenMCP rather
than FastMCP-provided — sourced from a deep-research pass whose adversarial verifiers refuted the
true claim 0-3, apparently because they only checked public docs pages and never inspected the
actually-installed package. That was wrong (see reference/middleware.md for the corrected facts).
Always cross-check "framework doesn't have X" claims directly against
`.venv/lib/.../site-packages/fastmcp/` before writing them into a skill as fact — a web-search-based
research pass can produce confident false negatives about implementation details that aren't
documented in public docs but are plainly present in the source.

## Not FastMCP framework features (commonly conflated)

- **No `fastmcp.ValidationError`** documented for tool/resource argument validation as of 3.4.3 —
  validation failures surface via Pydantic coercion, not a dedicated FastMCP exception type.
- **Pydantic `by_alias`/`exclude_none` serialization** is a MorgenMCP project convention, not a
  documented FastMCP requirement. The `model_dump(by_alias=True, exclude_none=True)` calls live in
  `client.py` (request bodies); `models.py` supplies the field aliases and `validate_by_name`/
  `validate_by_alias` config that make that round-trip work.

## How to refresh this file

1. `cd docs/fastmcp && git fetch --tags origin && git tag -l "v3.*"` — check for new tags.
2. `git log --oneline <old-tag>..<new-tag>` — skim for security/breaking-change commits.
3. `git show <new-tag>:docs/updates.mdx` — read the official per-release summary.
4. Update `SKILL.md`'s "Pinned version" line and this file's changelog table.
5. Empirically re-verify any claim about MorgenMCP's own code (like the caching-middleware note
   above) against the *installed* package, not just the docs submodule — they can diverge.
