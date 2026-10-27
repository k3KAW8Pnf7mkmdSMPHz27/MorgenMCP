# Release provenance with Sigstore

Stable `vX.Y.Z` tags run `.github/workflows/release.yml`. After tests, the
workflow builds the Python distributions and a desktop bundle containing the
exact release wheel. It validates and packs that bundle with MCPB 2.1.2,
calculates checksums, and creates a signed Sigstore provenance attestation with
GitHub's `actions/attest@v4` action.

The wheel, source archive, desktop bundle, and `SHA256SUMS` are all attestation
subjects. The workflow saves the resulting verification material as
`provenance.sigstore.json` and verifies every subject before publishing either
to PyPI or GitHub Releases. A failed attestation or verification step fails the
release. There is no unsigned fallback.

The gate uses GitHub CLI to verify the artifact digest, Sigstore signature and
trust evidence, SLSA provenance predicate, GitHub Actions OIDC issuer, expected
repository, `.github/workflows/release.yml` signer identity, release tag, and
full commit SHA. It rejects attestations from self-hosted runners. This proves
provenance and integrity, not that the software is free of bugs or malicious code.

## GitHub configuration

No code-signing certificate subscription or long-lived private key is required.
GitHub Actions obtains a short-lived Sigstore certificate using OIDC. The release
job declares `id-token: write` and `attestations: write` permissions. For public
repositories, GitHub supports artifact attestations on all current plans.

Keep the existing `pypi` environment and PyPI trusted publisher configured for
this workflow. PyPI authentication also uses OIDC. Restrict who can create
release tags and change the release workflow. If PEM-signing secrets or variables
were configured for the earlier proposal, they are no longer used and can be
removed from GitHub's environment settings.

See [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
and the [attestation action](https://github.com/actions/attest).

## Verify a downloaded bundle

Install a recent [GitHub CLI](https://cli.github.com/), authenticate with
`gh auth login` if required, and replace `vX.Y.Z` below with a release created
by this workflow. Older releases do not gain attestations retroactively.

```sh
REPO=k3KAW8Pnf7mkmdSMPHz27/MorgenMCP
TAG=vX.Y.Z
COMMIT="$(gh api "repos/$REPO/commits/$TAG" --jq .sha)"
gh release download "$TAG" --repo "$REPO" --dir release-download \
  --pattern '*.mcpb' --pattern provenance.sigstore.json

gh attestation verify "release-download/morgenmcp-${TAG#v}.mcpb" \
  --bundle release-download/provenance.sigstore.json \
  --repo "$REPO" \
  --signer-workflow "$REPO/.github/workflows/release.yml" \
  --source-ref "refs/tags/$TAG" \
  --source-digest "$COMMIT" \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  --predicate-type https://slsa.dev/provenance/v1 \
  --deny-self-hosted-runners
```

Check the exit status: proceed only if verification succeeds. The command binds
the download to the tag's current commit on GitHub. For stricter independent
review, set `COMMIT` to a full commit SHA you have already reviewed instead.
The same command verifies a downloaded wheel, source archive, or `SHA256SUMS`
by replacing the artifact path. Checksums alone do not authenticate a download.
Do not edit or repack the artifact after verification.

From a source checkout, the workflow's helper verifies multiple files with the
same policy:

```sh
uv run python -m scripts.verify_release \
  --bundle release-download/provenance.sigstore.json \
  --tag "$TAG" --commit "$COMMIT" release-download/*.mcpb
```

Verification uses GitHub CLI's Sigstore implementation rather than custom
cryptography. The attached JSON supplies the attestation; the CLI manages its
trusted verification roots. Initial verification may require network access.
See [GitHub CLI verification options](https://cli.github.com/manual/gh_attestation_verify).

## Claude Desktop installation and publisher identity

The `.mcpb` has Sigstore provenance in a separate file. It has no embedded MCPB
CMS signature. Claude Desktop should not be described as recognizing a trusted
publisher on the basis of this attestation; that behavior must be tested in the
actual desktop client. The manifest's author field is descriptive metadata.

After provenance verification, open the bundle in Claude Desktop. Record the
app version, operating system, any publisher or signature warning, whether
installation is permitted, and whether the API-key and read-only settings are
available. Use the [installation test record](INSTALLATION_TEST.md). Test both
macOS and Windows before claiming cross-platform installation support.

The host provisions Python and installs the release wheel's dependencies at
first run, so an internet connection is required. Only the MorgenMCP wheel is
fixed by the bundle; transitive dependencies follow that wheel's constraints.
The host collects the API key as a sensitive setting. A live calendar read is
an optional subsequent check using a real key, not part of automated CI.

## Checks and recovery

`provenance-trial.yml` provides a manual, non-publishing Actions trial: it
builds version `0.0.0`, attests all four subjects, verifies its own workflow/ref/commit
identity, and requires rejection of a tampered bundle. Its attestations identify
the trial workflow and source ref, so the production release verifier intentionally
does not accept them as stable releases. Download its seven-day Actions artifact
for desktop installation testing.


`desktop-bundle.yml` builds a development wheel, validates and packs a bundle,
checks the isolated launcher, and tests the verification gate without signing
credentials or Morgen API calls. It does not create release attestations for PR
builds. Creating a real GitHub OIDC attestation requires an Actions run; local
checks cannot reproduce the workflow's identity.

After successful provenance verification, the release workflow saves all final
files in an Actions artifact retained for 30 days. This supports recovery if
PyPI publication succeeds but GitHub Release creation fails. Download those
exact files, verify them again, and create the missing GitHub Release. Avoid
blindly rerunning publication: PyPI rejects duplicate version uploads.

MCP Registry publication still requires its own metadata and package ownership
verification; this workflow does not publish to the registry yet.
