# Phase 2: EventBus Scoping & CI Hardening

**Goal**: Optimize event communication and establish strict quality gates.

## Tasks

### 1. EventBus Optimization
- **PanelEventScope**: Implement a filtering mechanism to restrict event broadcasts to panels that actually need them.
- **Ring Buffer**: Cap `EventBus._published` with a ring buffer (max 10,000 events) to prevent infinite memory growth during long sessions.

### 2. Static Analysis & Linting
- **Mypy**: Add `mypy --strict src/` to CI. Resolve initial errors incrementally.
- **Ruff**: Add `ruff check src/ tests/` and `ruff format --check` to the CI pipeline.
- **Type Information**: Add a `src/cockpit/py.typed` marker for PEP 561 compatibility.

### 3. Dependency Management
- **Rich**: Explicitly add `rich` to the `[project.dependencies]` section in `pyproject.toml`.

## Verification Criteria
- [ ] `mypy --strict src/` passes.
- [ ] `ruff check src/` is clean.
- [ ] CI pipeline is green.
- [ ] Verified that memory usage remains stable after publishing many events.
