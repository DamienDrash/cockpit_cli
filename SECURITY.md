# Security Policy

## Supported Versions

`cockpit-cli` currently ships as a Linux-first project on the `0.1.x` line.
Security fixes are applied on the latest `main` branch and the latest tagged
release.

## Reporting A Vulnerability

If you believe you found a security issue in `cockpit-cli`, please do not open a
public issue with exploit details first.

Send the report to the repository maintainer through GitHub Security Advisories
or a private maintainer contact channel. Include:

- affected version or commit
- impact summary
- reproduction steps
- whether secrets, plugin isolation, release verification, or remote access are involved

## Supply-Chain Policy

Release artifacts are designed to be verifiable:

- Python distributions are built in GitHub Actions
- GitHub Releases publish checksums, SBOMs, Sigstore bundles, and provenance metadata
- PyPI publication uses Trusted Publishing rather than a stored API token
- release-time signing uses GitHub OIDC-based keyless identity

Consumers should prefer tagged releases and verify:

- `SHA256SUMS.txt`
- Sigstore bundles
- GitHub artifact attestations

Detailed maintainer and consumer verification steps live in
[docs/releasing.md](/home/damien/Dokumente/cockpit/docs/releasing.md).

## Scope Notes

The following areas are especially security-sensitive and should be reported
with clear reproduction details:

- Vault-backed secret resolution
- plugin installation, isolation, and permission gating
- SSH tunnels and remote datasource access
- release workflow integrity and artifact verification
