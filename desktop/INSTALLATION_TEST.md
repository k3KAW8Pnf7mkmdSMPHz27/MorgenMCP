# Claude Desktop installation test

This record tracks the actual client experience separately from Sigstore
provenance verification. Do not infer publisher trust from a manifest author
name, successful packaging, or a successful command-line launch.

## Local trial

- Date: 2026-10-27
- Platform: macOS (development workspace)
- Claude Desktop: 3.6556.2
- Bundle: local `morgenmcp` development build, version `0.0.0`
- Provenance: local fixture only; no GitHub OIDC attestation has been generated
- Packaging: MCPB 2.1.2 manifest validation and packing succeeded
- Launcher: isolated uv dependency installation and `server.py --help` succeeded
- Installation and publisher display: the bundle was opened with Claude Desktop,
  but macOS denied assistive access (`osascript` error -1728); manual inspection
  was subsequently confirmed from a user-provided screenshot (see below)
- API-key/read-only controls: confirmed in a user-provided configuration screenshot;
  saving configuration and server startup remain untested
- Live Morgen API calls: not performed

## User-observed installer screen

A user-provided screenshot on 2026-10-27 confirms:

- The MorgenMCP installer opens and reports **All requirements met**.
- The **Install** button is available; completed installation is not established.
- Claude displays a warning that installation grants access to the computer and
  that developer information has not been verified by Anthropic.
- The author is shown as **The Morgen MCP Authors**, with Apache-2.0 and version
  `0.0.0`. No verified-publisher indicator is visible in this screen.
- The generic icon and repeated short description make the initial presentation
  sparse. The manifest has since gained a detailed description, setup guidance,
  project links, and tool summaries; the updated rendering needs visual review.

This observation does not establish whether a CA-backed embedded signature
would alter Claude's warning. Sigstore provenance verification remains an
external verification step.

## User-observed configuration screen

A second user-provided screenshot on 2026-10-27 confirms:

- The installer reaches **Configure MorgenMCP**.
- The Morgen API key is marked required, with the developer portal URL shown.
- The API-key field is empty and **Save** is disabled in this state.
- The **Read-only mode** toggle is present and initially off.
- No credential was shared in the screenshot. Credential masking, saving,
  server startup, and live calendar access are not established by this image.
- The displayed help text matches the initial bundle; the later presentation
  changes still require a separate visual check.

## Sigstore Actions trial

- [Actions run 40576996109](https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP/actions/runs/40576996109): passed
- Workflow: `.github/workflows/provenance-trial.yml`
- Source ref: `refs/heads/improve-discovery-and-installation`
- Commit: `0a268e5dc099f3ed559f24af721692dd05b7d75a`
- Artifacts: wheel, source archive, `.mcpb`, and `SHA256SUMS`
- Attestation: `application/vnd.dev.sigstore.bundle.v0.3+json`
- Actions verified all four subjects and rejected a modified bundle
- All four downloaded subjects verified locally with GitHub CLI 2.102.0,
  including the exact repository, trial workflow, branch, commit, and GitHub
  OIDC issuer
- The production release verifier rejected the trial attestation, as expected: it
  requires the release workflow identity and a stable release tag
- [Actions run 40577343071](https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP/actions/runs/40577343071)
  also passed after updating the artifact uploader to Node.js 24
- The trial created no GitHub Release and published nothing to PyPI
- The separate attestation does not establish a Claude Desktop publisher display;
  the user-observed screen above records the initial installer presentation

## First attested release

1. Download the `.mcpb` and `provenance.sigstore.json` from the same release.
2. Follow the [verification commands](RELEASING.md#verify-a-downloaded-bundle).
3. Open the verified `.mcpb` in Claude Desktop.
4. Record the exact app and OS versions, publisher text, warnings, and whether
   installation is permitted. Distinguish manifest metadata from verified identity.
5. Check the required sensitive API-key field and the read-only setting.
6. If completing installation with a real key is intended, verify tool discovery
   and a calendar read, then remove the test installation if no longer needed.

| Platform | Attestation verification | Installation | Publisher display | Settings |
|---|---|---|---|---|
| macOS | Trial passed locally; release pending | Configuration reached; save/startup pending | Developer information unverified by Anthropic | Required key and read-only toggle confirmed |
| Windows | Pending | Pending | Pending | Pending |
