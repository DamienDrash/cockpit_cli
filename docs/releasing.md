# Releasing cockpit-cli

## Overview

Cockpit releases are built and published from GitHub Actions on pushed tags that
match `v*`.

The release pipeline is split into these stages:

1. `verify`
2. `service-matrix`
3. `package`
4. `sbom`
5. `attest-sign`
6. `publish-github`
7. `publish-pypi`

The package job builds the canonical artifacts once. Later jobs consume those
same artifacts rather than rebuilding them.

## Prerequisites

- GitHub Actions must be enabled for the repository.
- PyPI Trusted Publishing must trust this repository and the `Release` workflow.
- The PyPI environment in GitHub should be configured for the publish job if
  environment protection is desired.

## Local Dry Run

Install the release tooling:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[release]'
```

Install frontend tooling:

```bash
cd web/layout-editor
npm ci
npm test
npm run build
cd ../..
```

Sync the built frontend bundle into the packaged static assets:

```bash
PYTHONPATH=src python scripts/release_tooling.py sync-layout-editor
```

Build the Python distributions:

```bash
python -m build
```

Create a clean environment from the built wheel and generate the Python SBOM:

```bash
python -m venv .sbom-venv
.sbom-venv/bin/python -m pip install --upgrade pip
.sbom-venv/bin/pip install release-assets/dist/*.whl
.sbom-venv/bin/python -m pip freeze --all | \
  cyclonedx-py requirements - \
    --pyproject pyproject.toml \
    --output-reproducible \
    --of JSON \
    -o release-assets/sbom/cockpit-python-runtime.cdx.json
```

Generate the frontend SBOM:

```bash
cd web/layout-editor
npm exec -- cyclonedx-npm \
  --output-format JSON \
  --output-file ../../release-assets/sbom/cockpit-frontend.cdx.json
cd ../..
```

Write manifest and checksums:

```bash
PYTHONPATH=src python scripts/release_tooling.py manifest \
  --root release-assets \
  --output release-assets/release-manifest.json \
  --version <version> \
  --git-ref refs/tags/v<version>

PYTHONPATH=src python scripts/release_tooling.py checksums \
  --root release-assets \
  --output release-assets/SHA256SUMS.txt
```

## Cutting A Release

1. Update `CHANGELOG.md` and confirm the version in `pyproject.toml`.
2. Verify the main branch is green in CI.
3. Create and push a tag such as:

```bash
git tag v<version>
git push origin v<version>
```

4. Wait for `.github/workflows/release.yml` to complete.
5. Confirm the GitHub release contains:
   - `sdist`
   - `wheel`
   - `SHA256SUMS.txt`
   - Python SBOM
   - frontend SBOM
   - Sigstore bundle files
   - provenance bundle file
6. Confirm the package appears on PyPI.

## Verifying A Release

Download the release assets and verify checksums:

```bash
sha256sum -c SHA256SUMS.txt
```

Verify a wheel against its Sigstore bundle:

```bash
python -m pip install sigstore
python -m sigstore verify github cockpit_cli-<version>-py3-none-any.whl \
  --bundle cockpit_cli-<version>-py3-none-any.whl.sigstore.json \
  --repository DamienDrash/cockpit_cli \
  --ref refs/tags/v<version> \
  --trigger push
```

Verify GitHub provenance:

```bash
gh attestation verify cockpit_cli-<version>-py3-none-any.whl \
  --repo DamienDrash/cockpit_cli
```

## Notes

- The GitHub release is the canonical human-facing release page.
- PyPI consumes the exact wheel and sdist built earlier in the workflow.
- Release jobs use OIDC and do not depend on a stored PyPI token or a
  long-lived signing key.
