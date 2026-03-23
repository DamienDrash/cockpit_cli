# Release And Supply-Chain Gold Standard Design

## Summary

This slice raises Cockpit's release path from "build and upload artifacts" to a verifiable supply-chain pipeline with:

- deterministic release packaging
- keyless artifact signing
- provenance attestations
- SBOM generation
- publication to both GitHub Releases and PyPI
- maintainer-facing release documentation and policy

The target platform remains Linux-first. The release pipeline will publish Python artifacts as the primary distribution outputs and attach additional release metadata for downstream verification.

## Goals

- Publish `sdist` and `wheel` to GitHub Releases and PyPI.
- Generate release-time SBOMs for Python and frontend dependencies.
- Produce keyless Sigstore signatures for release artifacts.
- Produce provenance / artifact attestations from GitHub Actions.
- Minimize CI permissions and isolate build, attest, and publish responsibilities.
- Document maintainer and consumer verification flows.

## Non-Goals

- Flatpak, OBS, or other external distribution channels
- Cross-platform notarization
- GPG-based signing as a parallel required path
- Private package registries

## Current Baseline

The repository already has:

- a CI workflow that compiles, tests, builds packages, and runs a live service matrix
- a release workflow that builds artifacts, emits `SHA256SUMS.txt`, and creates a GitHub release

The current release path does not yet provide:

- provenance attestations
- Sigstore signatures / bundles
- SBOM artifacts
- PyPI Trusted Publishing
- hardened job-level permissions

## Release Architecture

Release moves to a staged pipeline with strict artifact handoff:

1. `verify`
   Runs compile, tests, frontend build, and service-matrix checks. This job never publishes anything.
2. `package`
   Produces the canonical release artifacts. All later jobs consume these exact artifacts rather than rebuilding.
3. `sbom`
   Generates SBOM documents for Python and frontend inputs and publishes them as release assets.
4. `attest-sign`
   Uses GitHub OIDC to create artifact attestations and keyless Sigstore signatures for the packaged artifacts.
5. `publish`
   Publishes the canonical release assets to GitHub Releases and Python packages to PyPI via Trusted Publishing.

The pipeline is tag-driven for publication and branch/PR-driven for verification-only execution.

## Security Model

### Trust Model

Cockpit will use:

- GitHub OIDC for identity in CI
- PyPI Trusted Publishing instead of stored PyPI API tokens
- Sigstore keyless signing instead of long-lived signing keys
- GitHub artifact attestations for build provenance

This avoids persistent release secrets in repository settings for the primary publication path.

### Permission Boundaries

Each job receives only the minimum permissions it needs:

- `verify`: read-only repository permissions
- `package`: read-only repository permissions
- `sbom`: read-only repository permissions plus artifact upload
- `attest-sign`: `id-token: write`, artifact read, attestation write if required
- `publish`: `id-token: write`, contents write for GitHub release, package publishing rights as required by the target

The `publish` job must never rebuild artifacts. It may only consume artifacts emitted by `package`.

### Immutability Rule

Artifacts that are:

- signed
- attested
- uploaded to the GitHub release
- published to PyPI

must all originate from the exact same `package` outputs.

## Artifact Set

The release asset set will include:

- source distribution (`.tar.gz`)
- wheel (`.whl`)
- checksum manifest (`SHA256SUMS.txt`)
- Python SBOM
- frontend SBOM
- Sigstore signature / bundle files for published artifacts
- provenance / attestation files where exported as downloadable assets

Optional future artifacts such as Arch packaging helpers may be attached, but they are not the primary PyPI publication unit.

## SBOM Strategy

Cockpit will emit CycloneDX-compatible SBOM documents for:

- Python dependencies used to build and run the packaged application
- frontend dependencies used to build the web layout editor

SBOM generation must be reproducible inside CI and attached to releases alongside the built artifacts.

## Signing And Provenance

### Sigstore

Every published Python artifact will be keylessly signed in CI. Signature outputs and verification material will be attached to the GitHub release so users can verify downloaded assets outside GitHub.

### Provenance / Attestations

GitHub artifact attestations will be generated from the workflow that built the release artifacts. The release documentation will describe how users can verify provenance against the published release assets.

## Publishing Model

### GitHub Releases

The GitHub Release remains the canonical human-facing release page and must contain:

- built packages
- checksums
- SBOM files
- signing outputs
- verification/provenance artifacts

### PyPI

`sdist` and `wheel` are also published to PyPI using Trusted Publishing. The PyPI publication job must only run on version tags and must consume the same packaged artifacts already built earlier in the workflow.

## Workflow Structure

### CI Workflow

The CI workflow continues to run on pushes and pull requests and will validate:

- source compileability
- unit/integration suites
- service matrix
- package buildability
- frontend buildability
- release helper commands that do not publish

CI should also validate the presence and syntax of release metadata where practical.

### Release Workflow

The release workflow runs on `v*` tags and includes:

- verification gate
- package creation
- SBOM generation
- signing / attestation
- GitHub release publication
- PyPI publication

Jobs are connected only through uploaded artifacts and explicit dependencies.

## Documentation

This slice adds or updates:

- `README.md` release verification section
- `SECURITY.md` for disclosure and supply-chain guidance
- `docs/releasing.md` for maintainer release flow
- release notes / changelog guidance if existing files need alignment

The documentation must explain:

- what gets published
- how maintainers cut a release
- how users verify checksums
- how users verify signatures and provenance

## Testing And Acceptance

This slice is done when:

- PRs exercise the build path without publishing
- a tag workflow can build release artifacts once and publish them without rebuilding
- GitHub Release assets include packages, SBOMs, checksums, and signing outputs
- PyPI publication is configured through Trusted Publishing
- release docs explain verification steps
- workflows use minimized permissions and clear job boundaries

## Rollout Notes

- Existing release behavior should remain functional during migration.
- The old single-job release flow can be replaced in-place once the staged workflow is verified.
- The implementation should prefer common OSS tooling with low operational burden rather than bespoke release scripts where a standard action or tool already solves the problem.
