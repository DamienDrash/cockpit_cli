# Contributing

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Install optional extras only for the backends you work on.

## Workflow

- keep commands routed through the central dispatcher
- prefer services and adapters over panel-local business logic
- add guards and audit behavior for mutating actions
- persist stable UI state, not volatile runtime internals
- do not store secrets in snapshots or config payloads

## Verification

Run before pushing:

```bash
python -m compileall src tests
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
```

For UI suites:

```bash
PYTHONPATH=src:/tmp/cockpit-deps python -m unittest \
  tests.e2e.test_embedded_terminal_widget \
  tests.e2e.test_app_resume_flow -v
```

## Packaging

- keep `pyproject.toml`, `.github/workflows/ci.yml`, and `packaging/arch/PKGBUILD` aligned
- update `CHANGELOG.md` for user-visible changes
- keep [docs/releasing.md](/home/damien/Dokumente/cockpit/docs/releasing.md) aligned with the actual workflow
- do not bypass the staged release pipeline by rebuilding artifacts inside publish jobs
