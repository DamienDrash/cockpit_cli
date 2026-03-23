# Secrets/Vault Gold Standard Design

Date: 2026-03-23
Status: Approved for implementation

## Scope

This spec defines the next gold-standard security slice for Cockpit:

- Vault becomes the primary secret platform
- local providers remain only as compatibility and migration paths
- Cockpit gains first-class support for:
  - Vault KV v2
  - Vault Transit
  - dynamic secrets with leases
  - token, AppRole, and OIDC/JWT authentication
  - session-bound auth with optional encrypted local cache

This slice is Linux-first and must integrate with the existing TUI, web admin, datasource system, and snapshot safety model.

## Goals

- Make Vault the canonical secret control plane for Cockpit
- Remove the current “secret provider logic embedded in the resolver” architecture
- Keep secret values out of snapshots, logs, and normal diagnostics
- Add lease-aware runtime behavior for dynamic credentials
- Expose Vault health, auth, lease, and rotation flows through the web admin
- Preserve compatibility for existing `env`, `file`, and `keyring` references

## Non-Goals

- Full enterprise IAM policy authoring inside Cockpit
- Generic support for every external secret manager in this slice
- Browser-based secret value display
- Silent fallback from unavailable Vault back to local providers

## Product Decision

Cockpit will treat Vault as the primary secrets platform.

`env`, `file`, and `keyring` remain readable for:

- compatibility with existing datasource and bootstrap flows
- migration of existing secret references
- minimal local-development edge cases

New managed secrets should default to Vault-backed references. Local secret providers are compatibility providers, not first-class equivalents.

## Architecture

The implementation is split into five layers.

### 1. Vault Control Plane

Responsible for persistent Vault profile metadata:

- server URL
- namespace
- auth mode
- TLS settings
- cache policy
- allowed mounts and role metadata
- profile risk classification

This is configuration and policy state, not live auth state.

### 2. Vault Session Manager

Responsible for runtime login and lease state:

- active token/session material
- lease ids
- TTL / renewable flags
- renewal bookkeeping
- revoke/release flows
- encrypted local resume cache where allowed

This is the runtime boundary between Cockpit and Vault.

### 3. Vault Provider

Provider implementation for:

- KV v2 reads and version metadata
- Transit encrypt/decrypt/sign/verify
- dynamic secret acquisition
- renew/revoke
- health checks

This layer speaks the Vault API and returns normalized Cockpit-facing result objects.

### 4. Secret Registry

`SecretService` becomes a registry and policy layer:

- managed secret definitions
- Vault profile metadata
- compatibility references
- revision and rotation metadata
- migration state

It should not contain direct HTTP logic.

### 5. Secret Resolver

`SecretResolver` becomes a provider dispatcher:

- resolves placeholders
- routes references to registered providers
- applies consistent masking / error semantics

Provider logic must move out of the resolver and into explicit provider implementations.

## Core Model

Three concepts must stay separate.

### Vault Profile

Defines where and how Cockpit authenticates:

- profile id
- display name
- Vault address
- namespace
- auth type
- TLS / CA / verification settings
- risk level
- cache policy

### Vault Session

Defines the live runtime session:

- profile id
- auth method
- token reference
- created at
- expires at
- renewable
- renewal state
- cached or live

### Secret Reference

Defines what is being resolved:

- KV ref
- Transit ref
- dynamic ref
- compatibility provider ref

Secret references must be stable, serializable, and free of resolved secret material.

## Reference Formats

Cockpit will standardize on explicit reference schemes.

### KV v2

`vault://<profile>/<mount>/<path>#<field>`

Examples:

- `vault://prod-vault/kv/apps/api#password`
- `vault://ops-vault/secret/database/reporting#url`

Optional version selection may be added in the reference payload rather than the simple string form.

### Transit

`vault+transit://<profile>/<key>`

Operation-specific payload selects:

- encrypt
- decrypt
- sign
- verify

### Dynamic Secrets

`vault+dynamic://<profile>/<engine>/<role>`

These resolve to lease-bearing runtime values, not long-lived static config.

### Compatibility References

Still supported:

- `env:NAME`
- `file:/path/to/file`
- `keyring:SERVICE:USERNAME`
- `stored:name`

But they are compatibility paths, not the primary operating model.

## Authentication

The initial gold-standard auth set is:

- token
- AppRole
- OIDC/JWT

Rules:

- auth sessions are session-bound by default
- optional encrypted local cache may be used for restart/resume
- no cleartext token persistence in snapshots or unprotected local state
- auth failures must be explicit and visible in the web admin

## Runtime Behavior

### KV v2

- resolve values by path + field
- expose version metadata
- allow rotation by writing a new version where policy permits
- support read-only and mutating flows distinctly

### Transit

- never store cryptographic key material locally
- all cryptographic operations are delegated to Vault
- only operation metadata and non-sensitive result summaries may be logged

### Dynamic Secrets

- acquire dynamic credentials on demand
- track lease ids and expiration
- renew automatically when allowed
- revoke explicitly on shutdown or operator request when appropriate
- surface lease health in diagnostics and admin views

## Safety and Security Rules

### Secret Material

- never write resolved values into snapshots
- never include resolved values in regular diagnostics
- never include resolved values in audit payloads
- default UI behavior is masked display only

### Failures

- no silent fallback from failed Vault resolution to a less secure provider
- failures must be explicit, typed, and actionable
- compatibility providers are only used when the reference explicitly points to them

### Guards

Risk-sensitive operations must require explicit confirmation where appropriate:

- profile deletion
- destructive secret operations
- lease revocation across active sessions
- mutating Vault operations in high-risk environments

### Logging

Audit logs may contain:

- profile ids
- mount/path metadata
- operation type
- success/failure
- lease ids when safe

Audit logs must not contain:

- token values
- secret values
- decrypted plaintext

## Persistence

Persistent storage should include:

- Vault profiles
- managed secret metadata
- compatibility reference metadata
- encrypted local auth/session cache when enabled
- lease metadata and health state needed for recovery

Persistent storage must not include:

- raw tokens in plaintext
- resolved secret values
- decrypted Transit outputs by default

## Web Admin Requirements

The web admin becomes the primary control plane for this slice.

It must support:

- Vault profile creation and editing
- auth/login flows
- session status
- lease visibility
- rotation/revoke operations
- health diagnostics
- migration of legacy managed secrets toward Vault references

It should clearly distinguish:

- profile configuration
- live session state
- secret references
- compatibility entries

## Integration Points

### Datasources

Datasource secret resolution must continue to flow through the shared resolver, but Vault-backed references become first-class supported values for:

- connection URLs
- usernames/passwords
- TLS paths and blobs
- dynamic DB credentials

### Plugins

Plugins should only consume normalized secret resolution, not direct Vault client objects, unless an explicit future plugin capability is introduced.

### Sessions and Snapshots

Snapshots may keep:

- profile ids
- secret reference identifiers
- non-sensitive lease metadata when necessary

Snapshots may not keep:

- secret values
- raw auth tokens

## Testing Strategy

The slice is complete only when covered by:

### Unit

- reference parsing
- provider dispatch
- auth policy validation
- masking behavior
- cache policy rules
- lease state transitions

### Integration

- fake Vault HTTP flows for KV v2
- Transit operation routing
- dynamic secret acquisition and renewal
- compatibility provider migration behavior

### Web Admin

- profile CRUD
- login flows
- revoke/rotate actions
- diagnostics rendering

### Optional Live Gates

Feature-gated tests for a real Vault instance may be added for local/CI environments where Vault is available.

## Migration

Existing secret entries must remain readable.

Migration path:

1. read legacy secret definitions as before
2. expose them as compatibility entries in the admin plane
3. allow operators to map or rewrite them to Vault references
4. keep legacy support until explicitly removed in a later cycle

No automatic destructive migration should happen silently.

## Implementation Order

1. Define new secret and Vault contracts
2. Add Vault client/provider modules
3. Add session and lease management
4. Refactor `SecretResolver` into provider dispatch
5. Refactor `SecretService` into registry/control-plane service
6. Integrate datasources and other existing consumers
7. Expand web admin
8. Add tests, docs, and diagnostics

## Definition of Done

This slice is done when:

- Vault is the primary managed secret platform in Cockpit
- KV v2, Transit, and dynamic secrets are supported
- token, AppRole, and OIDC/JWT auth are supported
- lease-aware runtime behavior exists
- snapshots remain secret-safe
- local providers still work as compatibility paths
- web admin exposes the full control-plane surface
- the test suite covers resolver, provider, session, and admin flows
